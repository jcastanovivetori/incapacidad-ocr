# -*- coding: utf-8 -*-
"""Genera requisitos_eps.sql (INSERTs para lprequisitos_eps) + mide el diff vs el repo."""
import json, collections, sys

# --- Rutas relativas (añadidas por scripts/exportar_analisis.py) --------------------------
# Este script se escribió con rutas ABSOLUTAS de la máquina donde se investigó. Se resuelven
# desde la ubicación del propio archivo para que funcione tras un `git pull` en cualquier
# equipo. El corpus (`dataset-falsedad/`) NO está en el repositorio: lo aporta el cliente.
import pathlib as _pl
_REPO = _pl.Path(__file__).resolve().parents[1]
_DATASET = _REPO.parent / "dataset-falsedad"
_EJEMPLOS = _REPO.parent / "Ejemplos"
# ------------------------------------------------------------------------------------------
sys.path.insert(0, str(_REPO))
from incapacidad_ocr.erp import REQUISITOS_DEFAULT, ETIQUETAS_TIPO, DOC_CANON, EQUIVALENCIAS_DOC

NORM = str(_DATASET / "requisitos_eps.json")
OUT = str(_DATASET / "requisitos_eps.sql")
norm = json.load(open(NORM, encoding="utf-8"))

# nombredocumento (texto libre del ERP) -> codigo canonico del repo (erp.DOC_CANON)
MAPA = {
    "CERTIFICADO DE INCAPACIDAD":         "INCAPACIDAD",
    "HISTORIA CLINICA":                   "HISTORIA_CLINICA",
    "CEDULA DEL TRABAJADOR":              "CEDULA",
    "CERTIFICADO NACIDO VIVO":            "CERTIFICADO_NACIDO_VIVO",
    "REGISTRO CIVIL":                     "REGISTRO_CIVIL_NACIMIENTO",
    "FURIPS":                             "FURIPS",
    # --- sin equivalente en erp.DOC_CANON: codigos NUEVOS (ver comentario del .sql)
    "SOAT":                               "SOAT",
    "REPORTE ACCIDENTE DE TRANSITO RAT":  "RAT",
    "FORMATO DE DESCARTE EVENTO LABORAL": "DESCARTE_EVENTO_LABORAL",
    "CERTICADO LABORAL":                  "CERTIFICADO_LABORAL",
}
NUEVOS = {"SOAT", "RAT", "DESCARTE_EVENTO_LABORAL", "CERTIFICADO_LABORAL"}
assert set(MAPA) == {d["nombredocumento"] for r in norm for d in r["documentos"]}, "falta mapear un doc"


def esc(s):
    return s.replace("\\", "\\\\").replace("'", "''")


CAB = """-- ===========================================================================
--  requisitos_eps.sql - requisitos documentales REALES por EPS + tipo de ausentismo
--  Fuente: <descargas>/lpeps.csv, columna `cheklistradicaciones`
--          (JSON {"ausentismos":[...]} embebido). El CSV NO esta bien citado: el JSON
--          viene envuelto en comillas dobles DUPLICADAS y contiene comas, por lo que
--          csv.DictReader lo parte en la primera coma -> se recupero por subcadena
--          ('{"ausentismos"' .. ultimo '}') y se valido con json.loads: 19/19 OK, 0 errores.
--  Generado por dataset-falsedad/_gen_sql.py - 100% local, sin PII (solo catalogos).
--
--  COBERTURA MEDIDA
--    * 64 EPS en el catalogo; 19 traen checklist JSON (las otras 45 traen el literal 'I',
--      que es como el export escribe NULL - igual que observaciones_radicacion y codigoarl).
--    * 19 EPS x 7 tipos de ausentismo (2,3,5,8,9,10,11) = 133 combinaciones; 66 con documentos.
--    * 320 filas de requisito (este archivo) - 10 nombres de documento distintos.
--    * Los tipos 7/12/13 (permisos y vacaciones) NO existen en el checklist: no se radican
--      ante la EPS (son internos) -> para esos sigue mandando erp.REQUISITOS_DEFAULT.
--
--  DDL de destino (incapacidad-ocr/sql/init.sql):
--    lprequisitos_eps(id AI PK, idlpentidad INT NOT NULL, idlptipoausentismo INT NOT NULL,
--                     documento VARCHAR(60) NOT NULL, obligatorio TINYINT(1) NOT NULL DEFAULT 1)
--
--  MAPEO idlpeps -> idlpentidad
--    Se usa `idlpeps` TAL CUAL como `idlpentidad`: en el ERP real la vista que consulta
--    erp.Lookups (`vlpentidades_ss`) se define como `idlpentidad AS idlpeps`, o sea es la
--    MISMA llave. OJO: los ids DEMO de sql/init.sql (1..8) son OTROS (demo 1 = NUEVA EPS,
--    pero el id real de NUEVA EPS S.A es 36; demo 5 = SALUD MIA vs real 5 = ALIANZA SALUD)
--    -> cargar esto en la BD demo sin limpiarla primero le cuelga los requisitos a la EPS
--    equivocada. Ver el bloque OPCIONAL 1 al final.
--
--  MAPEO nombredocumento -> codigo de documento del repo (erp.DOC_CANON / erp.canon_doc)
--    'CERTIFICADO DE INCAPACIDAD'         -> INCAPACIDAD
--    'HISTORIA CLINICA'                   -> HISTORIA_CLINICA
--    'CEDULA DEL TRABAJADOR'              -> CEDULA
--    'CERTIFICADO NACIDO VIVO'            -> CERTIFICADO_NACIDO_VIVO
--    'REGISTRO CIVIL'                     -> REGISTRO_CIVIL_NACIMIENTO
--    'FURIPS'                             -> FURIPS
--    SIN equivalente hoy en erp.DOC_CANON -> se crean codigos NUEVOS (no se fuerza un
--    sinonimo existente, que enmascararia el requisito):
--    'SOAT'                               -> SOAT
--    'REPORTE ACCIDENTE DE TRANSITO RAT'  -> RAT
--    'FORMATO DE DESCARTE EVENTO LABORAL' -> DESCARTE_EVENTO_LABORAL
--    'CERTICADO LABORAL'                  -> CERTIFICADO_LABORAL  (typo del ERP: 'CERTICADO')
--    NO se mapeo nada a EPICRISIS ni a FURAT: ninguna EPS pide 'EPICRISIS' (piden 'HISTORIA
--    CLINICA'; el grupo de equivalencia EPICRISIS<->HISTORIA_CLINICA del repo ya la acepta),
--    y FURAT no aparece en NINGUNA de las 320 filas (el FURAT va a la ARL, no a la EPS).
--    PENDIENTE en el paquete (fase siguiente; aqui NO se toca codigo): el TIPODOC del nombre
--    de archivo solo admite letras (`{cedula}_{TIPODOC}`), asi que para que colapse a estos
--    codigos hay que agregar a erp.DOC_CANON:
--        'SOAT': 'SOAT', 'RAT': 'RAT',
--        'DESCARTELABORAL': 'DESCARTE_EVENTO_LABORAL',
--        'CERTIFICADOLABORAL': 'CERTIFICADO_LABORAL'
--    Sin eso, erp.canon_doc('DESCARTELABORAL') devuelve 'DESCARTELABORAL', que no iguala al
--    codigo de estas filas y el soporte se contaria como faltante.
--
--  obligatorio = 1 en TODAS las filas: el JSON de la EPS no tiene ningun flag de
--    opcionalidad, todo documento listado es exigido. (Nota: erp.Lookups.documentos_requeridos
--    hoy NO filtra por `obligatorio`, asi que cualquier fila cuenta como obligatoria.)
--
--  METADATOS QUE ESTE DDL NO PUEDE GUARDAR (quedan solo como comentario por EPS/tipo):
--    tipo_envio      1 = todo en UN archivo / 2 = varios archivos separados (medido: env=1 =>
--                    max(archivo)=1 en 21/21 combos; env=2 => max(archivo)>=2 en 47/47).
--    medioradicacion canal de radicacion; es CONSTANTE por EPS (ninguna mezcla 1 y 2).
--    archivo         en cual de los N archivos va cada documento (0 = sin asignar).
--    Ver el bloque OPCIONAL 2 al final si se decide persistirlos.
-- ===========================================================================

USE ASTGU;
"""

L = [CAB]
L.append("-- Recarga idempotente: solo borra los requisitos de las 19 EPS que SI traen checklist.")
L.append("DELETE FROM lprequisitos_eps WHERE idlpentidad IN (%s);"
         % ", ".join(str(e) for e in sorted({r["idlpeps"] for r in norm})))
L.append("")
L.append("INSERT INTO lprequisitos_eps (idlpentidad, idlptipoausentismo, documento, obligatorio) VALUES")

por_eps = collections.defaultdict(list)
for r in norm:
    por_eps[(r["idlpeps"], r["nombre_eps"])].append(r)

filas = 0
for eps in sorted(por_eps):
    combos = sorted(por_eps[eps], key=lambda r: r["idlptipoausentismo"])
    con_doc = [c for c in combos if c["documentos"]]
    vacios = [c["idlptipoausentismo"] for c in combos if not c["documentos"]]
    L.append("")
    L.append("-- ------------------------------------------------------------------")
    L.append("-- idlpeps=%d  %s  (NIT %s)" % (eps[0], eps[1], combos[0]["identificacion"]))
    if vacios:
        L.append("--   tipos SIN documentos configurados (la EPS no exige nada / sin definir): %s"
                 % "; ".join("%d %s" % (t, ETIQUETAS_TIPO.get(t, "?")) for t in vacios))
    for c in con_doc:
        n_arch = len({d["archivo"] for d in c["documentos"] if d["archivo"]})
        L.append("--   tipo %d %s | tipo_envio=%d medioradicacion=%d | %d docs en %d archivo(s): %s"
                 % (c["idlptipoausentismo"], ETIQUETAS_TIPO.get(c["idlptipoausentismo"], "?"),
                    c["tipo_envio"], c["medioradicacion"], len(c["documentos"]), n_arch,
                    ", ".join("%s#%d" % (MAPA[d["nombredocumento"]], d["archivo"])
                              for d in c["documentos"])))
        for d in c["documentos"]:
            L.append("  (%d, %d, '%s', 1)," % (eps[0], c["idlptipoausentismo"],
                                               esc(MAPA[d["nombredocumento"]])))
            filas += 1

ult = max(i for i, s in enumerate(L) if s.startswith("  ("))
L[ult] = L[ult][:-1] + ";"

L += ["",
      "-- ===========================================================================",
      "--  OPCIONAL 1 - sembrar `lpentidades` con los ids REALES (solo si se quiere probar",
      "--  en la BD demo de docker compose). CHOCA con los ids demo 1..8 de sql/init.sql:",
      "--  ejecutar antes `DELETE FROM lprequisitos_eps; DELETE FROM lpentidades;`.",
      "--  `nombre` es la palabra clave con la que erp.Lookups matchea por contencion, asi que",
      "--  conviene revisarla a mano (p.ej. 'FAMISANAR LTDA. CAFAM COLSUBSIDIO' no matchea un",
      "--  documento que diga solo 'FAMISANAR').",
      "-- ---------------------------------------------------------------------------"]
for eps in sorted(por_eps):
    r0 = por_eps[eps][0]
    L.append("-- INSERT INTO lpentidades (idlpentidad, nombre, nit, tipoentidad) VALUES (%d, '%s', '%s', 1);"
             % (eps[0], esc(eps[1]), esc(r0["identificacion"])))
L += ["",
      "-- ===========================================================================",
      "--  OPCIONAL 2 - persistir los metadatos de radicacion que el DDL actual no tiene",
      "--  (propuesta; NO se ejecuta aqui porque cambia el esquema del repo).",
      "-- ---------------------------------------------------------------------------",
      "-- ALTER TABLE lprequisitos_eps",
      "--   ADD COLUMN archivo         TINYINT     NOT NULL DEFAULT 0  COMMENT 'en cual de los N archivos va (0=sin asignar)',",
      "--   ADD COLUMN iddocumento     INT         NULL                COMMENT 'id del catalogo de documentos del ERP (1..8,11,12)',",
      "--   ADD COLUMN nombredocumento VARCHAR(60) NULL                COMMENT 'texto original del checklist de la EPS';",
      "-- CREATE TABLE lpradicacion_eps (   -- 1 fila por (EPS, tipo de ausentismo)",
      "--   idlpentidad        INT     NOT NULL,",
      "--   idlptipoausentismo INT     NOT NULL,",
      "--   tipo_envio         TINYINT NOT NULL,   -- 0=sin definir 1=un archivo 2=archivos separados",
      "--   medioradicacion    TINYINT NOT NULL,   -- 0=sin definir 1/2=canal (etiqueta a confirmar con el cliente)",
      "--   PRIMARY KEY (idlpentidad, idlptipoausentismo));",
      ""]
open(OUT, "w", encoding="utf-8").write("\n".join(L))
print("SQL escrito:", OUT, "| filas INSERT:", filas)

# ---------------- diff vs repo ----------------
print("\n===== DIFF vs erp.REQUISITOS_DEFAULT =====")
obs = collections.defaultdict(collections.Counter)
tot = collections.Counter()
for r in norm:
    if r["documentos"]:
        tot[r["idlptipoausentismo"]] += 1
        for d in r["documentos"]:
            obs[r["idlptipoausentismo"]][MAPA[d["nombredocumento"]]] += 1
for t in sorted(set(REQUISITOS_DEFAULT) | set(obs)):
    req = set(REQUISITOS_DEFAULT.get(t, []))
    o = obs.get(t, collections.Counter())
    n = tot.get(t, 0)
    print("\ntipo %2d %-24s (EPS que configuran docs: %d/19)" % (t, ETIQUETAS_TIPO.get(t, "?"), n))
    print("   repo pide : %s" % sorted(req))
    print("   EPS piden : %s" % [(k, "%d/%d" % (v, n)) for k, v in o.most_common()])
    print("   repo pide y NINGUNA EPS pide : %s" % sorted(req - set(o)))
    print("   EPS piden y repo NO pide     : %s" % sorted(set(o) - req))
print("\nEQUIVALENCIAS_DOC del repo:", EQUIVALENCIAS_DOC)
amb = sum(1 for r in norm
          if {MAPA[d["nombredocumento"]] for d in r["documentos"]}
          >= {"CERTIFICADO_NACIDO_VIVO", "REGISTRO_CIVIL_NACIMIENTO"})
print("combinaciones donde la EPS pide NACIDO_VIVO **Y** REGISTRO_CIVIL a la vez:", amb)
print("codigos nuevos (no estan en DOC_CANON):", sorted(NUEVOS - set(DOC_CANON.values())))
print("filas por codigo:", collections.Counter(MAPA[d["nombredocumento"]]
                                               for r in norm for d in r["documentos"]).most_common())
print("EPS con checklist:", len(por_eps), "| combinaciones:", len(norm))
