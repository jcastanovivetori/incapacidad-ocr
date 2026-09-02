"""Genera y carga los CATÁLOGOS de prueba de la BD, calcados del corpus real.

El `sql/init.sql` trae catálogos mínimos pensados para `../Ejemplos`. Con el corpus real del
cliente (31 documentos) esos catálogos no resuelven nada: ninguna cédula, ningún diagnóstico
y casi ninguna EPS coinciden, así que TODO cae a «datos por revisar» y la prueba no dice nada.
Este script construye unos catálogos que **sí** corresponden a lo que dicen esos documentos:

  * `lpempleados`   — las cédulas que el corpus usa de verdad, con el nombre BIEN escrito
                      (el catálogo es la fuente autoritativa: es lo que corrige los nombres
                      que el OCR entrega pegados).
  * `lpdiagnosticos`— los CIE-10 que traen los documentos… **menos los que el cliente marcó
                      como inexistentes** (`R50.5`, `A09`, `A00`, `G43`). Eso es deliberado y
                      es lo que hace que la prueba valga: si se sembraran, la señal de
                      «diagnóstico que no existe» no dispararía nunca.
  * `lpentidades` + `lpeps` — las EPS con su `cheklistradicaciones` REAL (el JSON que exporta
                      el ERP), tomado de `lpeps.csv`. `lpeps` no existe en `init.sql`, así que
                      sin esto el checklist de radicación nunca se evalúa.
  * `lprequisitos_eps` — los requisitos reales por EPS y tipo de ausentismo.

**PII (Ley 1581):** el SQL generado lleva cédulas y nombres de personas reales, así que se
escribe FUERA del repositorio (junto al corpus, en `../dataset-falsedad/`) y no se versiona.
Lo que se versiona es este generador.

    python scripts/sembrar_bd_prueba.py              # genera el SQL y lo aplica si hay BD
    python scripts/sembrar_bd_prueba.py --solo-sql   # genera el SQL y no toca la BD
"""
from __future__ import annotations

import argparse
import csv
import glob
import json
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

DATASET = REPO.parent / "dataset-falsedad"
SALIDA = DATASET / "seed_bd_prueba.sql"
MAPEO = REPO / "ingesta" / "_sistema" / "semilla" / "MAPEO.csv"
LPEPS_CSV = Path.home() / "Downloads" / "lpeps.csv"

# --------------------------------------------------------------------------- #
# Diagnósticos
# --------------------------------------------------------------------------- #
# Códigos que el CLIENTE declaró inexistentes en su catálogo (tabla de motivos de
# `Explicacion de archivos.jpeg`). NO se siembran: son justo la evidencia que la señal
# "el CIE-10 no está en el catálogo" tiene que encontrar. Sembrarlos volvería la prueba
# incapaz de detectar 4 de los 15 documentos adulterados.
CIE10_INEXISTENTES = {"R505", "A09", "A00", "G43"}

# Descripciones CIE-10. Son las que se usan para comparar contra el texto impreso en el
# documento (`erp._diagnostico_coincide`), así que una descripción equivocada aquí genera
# una falsa alarma de manipulación. Las marcadas [APROX] son aproximaciones nuestras y hay
# que REEMPLAZARLAS por las de `lpdiagnosticos` de ASTGU antes de dar por bueno cualquier
# número de precisión.
CIE10_DESCRIPCIONES = {
    "M54.5": "LUMBAGO NO ESPECIFICADO",
    "M54.4": "LUMBAGO CON CIATICA",
    "N20.0": "CALCULO DEL RINON",
    "N23":   "COLICO RENAL NO ESPECIFICADO",
    "O20.0": "AMENAZA DE ABORTO",
    "O82.9": "PARTO POR CESAREA SIN OTRA INDICACION",
    "H10.2": "OTRAS CONJUNTIVITIS AGUDAS",
    "B34.9": "INFECCION VIRAL NO ESPECIFICADA",
    "A09.9": "GASTROENTERITIS Y COLITIS DE ORIGEN NO ESPECIFICADO",
    "J33.4": "POLIPO DE LA NARIZ Y DEL SENO PARANASAL",
    "S52.0": "FRACTURA DE LA EPIFISIS SUPERIOR DEL CUBITO",
    "S83.6": "ESGUINCES Y TORCEDURAS DE OTRAS PARTES DE LA RODILLA",
    "R07.4": "DOLOR EN EL PECHO, NO ESPECIFICADO",
    "S09.9": "TRAUMATISMO NO ESPECIFICADO DE LA CABEZA",
    "S80.1": "CONTUSION DE OTRAS PARTES Y DE LAS NO ESPECIFICADAS DE LA PIERNA",
    "M93.9": "OSTEOCONDROPATIA NO ESPECIFICADA",           # [APROX]
    "B04.0": "INFECCION VIRAL NO ESPECIFICADA",            # [APROX] confirmar con ASTGU
    "C10.1": "TUMOR MALIGNO DE LA CARA LINGUAL DE LA EPIGLOTIS",  # [APROX]
    "Q07.3": "OTRAS MALFORMACIONES CONGENITAS DEL SISTEMA NERVIOSO",  # [APROX]
    "S19.0": "TRAUMATISMO SUPERFICIAL DEL CUELLO",         # [APROX]
    # Códigos de los documentos legítimos de ../Ejemplos, para que esa demo siga resolviendo.
    "J06.9": "INFECCION AGUDA DE LAS VIAS RESPIRATORIAS SUPERIORES, NO ESPECIFICADA",
    "K42.9": "HERNIA UMBILICAL SIN OBSTRUCCION NI GANGRENA",
    "S42.0": "FRACTURA DE LA CLAVICULA",
}
# Un código con menos de 4 caracteres útiles está estructuralmente incompleto para este
# catálogo (regla del cliente: "TODOS LOS DX SON DE 4 CARACTERES") y no se siembra.
APROX = {"M93.9", "B04.0", "C10.1", "Q07.3", "S19.0"}

# Palabras clave de EPS que el OCR deja reconocibles en el corpus. El lookup hace match por
# CONTENCIÓN sin espacios, así que la clave debe ser la parte distintiva y estable.
EPS_EXTRA = [
    "SURA", "SURAMERICANA", "FAMISANAR", "SANITAS", "NUEVA EPS", "SALUD TOTAL",
    "COLPATRIA", "SALUDMIA", "EMERMEDICA", "COMPENSAR", "COOSALUD", "MUTUAL SER",
    "SEGUROS DEL ESTADO", "SALUD MIA",
]


def _q(v) -> str:
    """Literal SQL (o NULL). Escapa comillas y barras invertidas."""
    if v is None or v == "":
        return "NULL"
    s = str(v).replace("\\", "\\\\").replace("'", "''")
    return f"'{s}'"


def _nombre_limpio(archivo_original: str) -> str | None:
    """Nombre de persona a partir del nombre de archivo del cliente.

    Los archivos de las adulteradas vienen como `INC APELLIDO APELLIDO NOMBRE fecha.pdf`:
    ese nombre lo escribió una persona, así que está BIEN escrito — mejor fuente que el OCR,
    que los devuelve pegados. Los legítimos vienen como `cedula_TIPODOC` y no traen nombre.
    """
    m = re.match(r"^INC\s+(.+?)\s+\d", Path(archivo_original).stem, re.I)
    if not m:
        return None
    nombre = re.sub(r"\s+", " ", m.group(1)).strip().upper()
    return nombre or None


def _nombre_ocr(cedula: str) -> str | None:
    """Respaldo: el nombre que leyó el OCR, si es utilizable (no basura pegada corta)."""
    for j in glob.glob(str(DATASET / "ocr" / "*" / "*.json")):
        try:
            d = json.loads(Path(j).read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            continue
        pac = ((d.get("incapacidad") or {}).get("paciente") or {})
        if re.sub(r"\D", "", str(pac.get("documento_numero") or "")) != cedula:
            continue
        nom = re.sub(r"\s+", " ", str(pac.get("nombre") or "")).strip().upper()
        # Se descarta lo que claramente no es un nombre (rótulos que el OCR arrastró).
        if not nom or len(nom) < 8 or any(x in nom for x in ("FIRMA", "HISTORIA", "CC")):
            return None
        return nom[:110]
    return None


def _cie10_del_corpus() -> set[str]:
    """Códigos CIE-10 que el OCR leyó de los documentos (con formato válido)."""
    out = set()
    for j in glob.glob(str(DATASET / "ocr" / "*" / "*.json")):
        try:
            d = json.loads(Path(j).read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            continue
        cie = ((d.get("incapacidad") or {}).get("diagnostico") or {}).get("cie10")
        if cie and re.fullmatch(r"[A-Z]\d{2}(\.\d)?", str(cie).upper()):
            out.add(str(cie).upper())
    return out


def _checklists_reales() -> list[dict]:
    """(idlpeps, nombre, identificacion, cheklistradicaciones) del export real del ERP.

    El CSV NO está bien citado: el JSON lleva comas y viene envuelto en comillas dobles
    duplicadas, así que `csv.DictReader` lo parte en la primera coma. Se recupera de la
    línea CRUDA por subcadena y se valida con `json.loads`.
    """
    if not LPEPS_CSV.is_file():
        return []
    filas = []
    for linea in LPEPS_CSV.read_text(encoding="utf-8-sig").splitlines()[1:]:
        if '{"ausentismos"' not in linea:
            continue
        ini = linea.index('{"ausentismos"')
        fin = linea.rindex("}") + 1
        crudo = linea[ini:fin].replace('""', '"')
        try:
            json.loads(crudo)
        except Exception:  # noqa: BLE001 — un JSON roto se omite, no se inventa
            continue
        campos = linea[:ini].split(",")
        try:
            idlpeps = int(campos[0])
        except (ValueError, IndexError):
            continue
        nombre = (campos[1] if len(campos) > 1 else "").strip().strip('"')
        ident = (campos[2] if len(campos) > 2 else "").strip().strip('"')
        filas.append({"idlpeps": idlpeps, "nombre": nombre, "identificacion": ident,
                      "checklist": crudo})
    return filas


def generar_sql() -> str:
    if not MAPEO.is_file():
        raise SystemExit(f"Falta {MAPEO}. Corre antes: python scripts/sembrar_prueba_falsedad.py")
    filas_mapeo = list(csv.DictReader(MAPEO.open(encoding="utf-8")))

    # --- empleados: solo las cédulas REALES (las sintéticas no existen en ningún ERP) ---
    empleados: dict[str, str] = {}
    for f in filas_mapeo:
        if f["origen_cedula"] == "sintetica":
            continue
        ced = f["cedula"]
        nombre = _nombre_limpio(f["archivo_original"]) or empleados.get(ced) or _nombre_ocr(ced)
        empleados[ced] = nombre or f"EMPLEADO {ced}"

    cie_corpus = _cie10_del_corpus()
    sembrables = sorted(
        c for c in (cie_corpus | set(CIE10_DESCRIPCIONES))
        if c.replace(".", "") not in CIE10_INEXISTENTES and c in CIE10_DESCRIPCIONES
    )
    omitidos = sorted(c for c in cie_corpus if c.replace(".", "") in CIE10_INEXISTENTES)
    sin_descripcion = sorted(c for c in cie_corpus
                             if c not in CIE10_DESCRIPCIONES
                             and c.replace(".", "") not in CIE10_INEXISTENTES)
    checklists = _checklists_reales()
    # El catálogo CIE-10 completo se lee ANTES de la cabecera porque su conteo se
    # anuncia ahí. Si no está descargado, se cae al mínimo hecho a mano.
    cie10_csv = REPO / "datos" / "cie10.csv"
    catalogo: list[tuple[str, str]] = []
    if cie10_csv.is_file():
        with cie10_csv.open(encoding="utf-8", newline="") as fh:
            for r in csv.DictReader(fh):
                cod = (r.get("codigo") or "").strip().upper()
                desc = (r.get("descripcion") or "").strip()
                if cod and desc:
                    catalogo.append((cod, desc))
    n_catalogo = len(catalogo)

    L: list[str] = []
    add = L.append
    add("-- =========================================================================")
    add("--  seed_bd_prueba.sql — catálogos de prueba CALCADOS DEL CORPUS REAL")
    add("--  GENERADO por scripts/sembrar_bd_prueba.py — no editar a mano.")
    add("--")
    add("--  CONTIENE DATOS PERSONALES (cédulas y nombres reales): este archivo vive")
    add("--  FUERA del repositorio y NO se versiona (Ley 1581).")
    add("--")
    add(f"--  empleados sembrados ............ {len(empleados)}")
    add(f"--  diagnósticos sembrados ......... {n_catalogo or len(sembrables)}"
        f"{'  (catálogo CIE-10 completo, datos/cie10.csv)' if n_catalogo else '  (mínimo a mano)'}")
    add(f"--  diagnósticos OMITIDOS a propósito {omitidos}  (el cliente los declaró inexistentes)")
    add(f"--  leídos sin descripción conocida . {sin_descripcion}  (no se siembran: no inventamos texto)")
    add(f"--  EPS con checklist de radicación .. {len(checklists)}")
    add("--")
    add("--  LAS DESCRIPCIONES marcadas [APROX] son aproximaciones nuestras y se comparan")
    add("--  contra el texto del documento: reemplazarlas por las de ASTGU antes de dar")
    add("--  por válida cualquier métrica de precisión.")
    add("-- =========================================================================")
    add("")
    add("-- lpeps: NO existe en init.sql y es la tabla que `erp.Lookups.documentos_radicacion`")
    add("-- consulta. Sin ella el checklist de radicación nunca se evalúa (degrada a []).")
    add("CREATE TABLE IF NOT EXISTS lpeps (")
    add("  idlpeps               INT PRIMARY KEY,")
    add("  nombre                VARCHAR(120) NOT NULL,")
    add("  identificacion        VARCHAR(20)  NULL,")
    add("  cheklistradicaciones  LONGTEXT     NULL   -- así se llama en el ERP (con la errata)")
    add(") ENGINE=InnoDB;")
    add("")

    add("-- Empleados del corpus. El nombre del catálogo es AUTORITATIVO: es lo que corrige")
    add("-- los nombres que el OCR entrega pegados (ALIX HERNANDEZSANDOVAL -> ... SANDOVAL).")
    for ced, nombre in sorted(empleados.items()):
        add(f"INSERT INTO lpempleados (cedula, nombre, eps, activo) VALUES "
            f"({_q(ced)}, {_q(nombre[:110])}, NULL, 1) "
            f"ON DUPLICATE KEY UPDATE nombre=VALUES(nombre);")
    add("")

    # Catálogo CIE-10 COMPLETO si está descargado (`scripts/descargar_cie10.py`). Es lo que
    # convierte la señal "este diagnóstico no existe" en algo verificable: con 25 códigos
    # puestos a mano, cualquier código legítimo fuera de esa lista se veía como inexistente.
    if catalogo:
        add("-- Catálogo CIE-10 completo (datos/cie10.csv). El código se guarda CON punto en el")
        add("-- nivel de 4 caracteres (X##.#), que es la forma que el ERP muestra; el lookup")
        add("-- compara sin punto, así que las dos formas resuelven igual.")
        add("--")
        add("-- Se REEMPLAZA el catálogo entero, no se añade encima. Un catálogo mezclado es peor")
        add("-- que uno incompleto: los códigos sueltos que hubiera antes TAPAN los huecos reales")
        add("-- y hacen que `categoria_subdividida` opine sobre una base que no es la del catálogo")
        add("-- (se vio: 4 códigos puestos a mano hacían 'existir' a 3 que el catálogo niega).")
        add("-- Ojo: los `idlpdiagnosticos` cambian, así que hay que reiniciar la prueba después")
        add("-- («Reiniciar prueba» vacía staging, que es donde se guardaban esos ids).")
        add("DELETE FROM lpdiagnosticos;")
        for cod, desc in catalogo:
            con_punto = f"{cod[:3]}.{cod[3:]}" if len(cod) >= 4 else cod
            add(f"INSERT INTO lpdiagnosticos (codigo, descripcion) VALUES "
                f"({_q(con_punto)}, {_q(desc[:200])}) "
                f"ON DUPLICATE KEY UPDATE descripcion=VALUES(descripcion);")
        add("")
    else:
        add("-- Diagnósticos: catálogo mínimo hecho a mano (no se descargó datos/cie10.csv).")
        add("-- Los declarados inexistentes por el cliente NO están, a propósito.")
        for cod in sembrables:
            desc = CIE10_DESCRIPCIONES[cod]
            marca = "  -- [APROX] confirmar con ASTGU" if cod in APROX else ""
            add(f"INSERT INTO lpdiagnosticos (codigo, descripcion) VALUES "
                f"({_q(cod)}, {_q(desc)}) ON DUPLICATE KEY UPDATE descripcion=VALUES(descripcion);{marca}")
        add("")

    if checklists:
        add("-- Entidades + checklist de radicación REAL (export del ERP). Los ids son los del")
        add("-- ERP y se usan en las DOS tablas: `documentos_radicacion` cruza lpeps.idlpeps")
        add("-- con el idlpentidad que resolvió el lookup, así que tienen que coincidir.")
        for e in checklists:
            add(f"INSERT INTO lpentidades (idlpentidad, nombre, nit, tipoentidad) VALUES "
                f"({e['idlpeps']}, {_q(e['nombre'][:78])}, {_q(e['identificacion'])}, 1) "
                f"ON DUPLICATE KEY UPDATE nombre=VALUES(nombre), nit=VALUES(nit);")
            add(f"INSERT INTO lpeps (idlpeps, nombre, identificacion, cheklistradicaciones) VALUES "
                f"({e['idlpeps']}, {_q(e['nombre'][:118])}, {_q(e['identificacion'])}, "
                f"{_q(e['checklist'])}) ON DUPLICATE KEY UPDATE "
                f"cheklistradicaciones=VALUES(cheklistradicaciones);")
        add("")

    add("-- Palabras clave de EPS extra: el OCR del corpus deja cadenas ruidosas")
    add("-- ('EPS.SURAMERICANA S.A/8', 'NUEVAEPS') y el match es por contención sin espacios.")
    for nombre in EPS_EXTRA:
        add(f"INSERT INTO lpentidades (nombre, nit, tipoentidad) "
            f"SELECT {_q(nombre)}, NULL, 1 FROM DUAL WHERE NOT EXISTS "
            f"(SELECT 1 FROM lpentidades WHERE nombre = {_q(nombre)});")
    add("")
    return "\n".join(L) + "\n"


def _aplicar_con_cliente_mysql(ruta_sql: Path) -> bool:
    """Aplica el .sql con el cliente `mysql`, que es como se aplica en un despliegue real.

    Se prefiere al conector de Python a propósito: `mysql-connector` con la extensión C se
    atraganta con un script de varias sentencias ("Commands out of sync") aunque se consuman
    los resultados, y dejaba el sembrado a medias. El cliente lee el script tal cual.
    Devuelve True si lo aplicó.
    """
    import shutil as _sh
    import subprocess

    from incapacidad_ocr import db as _db

    cfg = _db.db_config()
    sql_bytes = ruta_sql.read_bytes()
    intentos = []
    if _sh.which("mysql"):                      # cliente en el host (o dentro del contenedor)
        intentos.append(["mysql", f"-h{cfg['host']}", f"-P{cfg['port']}", f"-u{cfg['user']}",
                         f"-p{cfg['password']}", cfg["database"]])
    if _sh.which("docker"):                     # el cliente que ya vive en el contenedor de BD
        intentos.append(["docker", "exec", "-i", "ocr-db", "mysql", f"-u{cfg['user']}",
                         f"-p{cfg['password']}", cfg["database"]])
    for cmd in intentos:
        try:
            r = subprocess.run(cmd, input=sql_bytes, capture_output=True, timeout=180)
        except Exception:  # noqa: BLE001 — se prueba el siguiente
            continue
        err = r.stderr.decode("utf-8", "replace")
        # El aviso de contraseña en la línea de comandos no es un error.
        err_real = "\n".join(l for l in err.splitlines() if "Using a password" not in l).strip()
        if r.returncode == 0 and not err_real:
            print(f"BD sembrada con el cliente mysql ({cmd[0]}).")
            return True
        if err_real:
            print(f"  {cmd[0]}: {err_real[:200]}")
    return False


def cargar(sql: str) -> None:
    """Aplica el SQL a la BD configurada por las variables DB_* (si está disponible)."""
    from incapacidad_ocr import db

    if not db.db_disponible():
        print("BD no disponible: el SQL quedó generado, aplícalo cuando la levantes "
              "(docker compose up -d db && python scripts/sembrar_bd_prueba.py).")
        return
    if _aplicar_con_cliente_mysql(SALIDA):
        return
    print("  (sin cliente mysql utilizable: se intenta con el conector de Python)")
    # `multi=True` no está en todos los conectores; se parten las sentencias por ';\n'.
    sentencias = [s.strip() for s in re.split(r";\s*\n", sql) if s.strip() and not s.strip().startswith("--")]
    # `consume_results=True` es obligatorio aquí: con la extensión C, `with_rows` no basta y
    # cualquier resultado sin leer hace que la sentencia siguiente muera con "Commands out of
    # sync", dejando el sembrado a medias (se ve como "la tabla lpeps no existe").
    import mysql.connector  # import perezoso, igual que en db.py

    cx = mysql.connector.connect(**db.db_config(), consume_results=True)
    try:
        cur = cx.cursor()
        try:
            ok, fallos = 0, []
            for s in sentencias:
                # Se quitan los comentarios de línea para no confundir al conector.
                limpio = "\n".join(ln for ln in s.splitlines() if not ln.strip().startswith("--"))
                if not limpio.strip():
                    continue
                try:
                    cur.execute(limpio)
                    ok += 1
                except Exception as exc:  # noqa: BLE001 — se reporta la sentencia concreta
                    fallos.append(f"{limpio.splitlines()[0][:80]} -> {str(exc)[:90]}")
            cx.commit()
            print(f"BD sembrada: {ok} sentencias aplicadas" +
                  (f", {len(fallos)} con error" if fallos else ""))
            for f in fallos[:10]:
                print("  ERROR:", f)
        finally:
            cur.close()
    finally:
        cx.close()


def main() -> int:
    ap = argparse.ArgumentParser(description="Genera y carga los catálogos de prueba.")
    ap.add_argument("--solo-sql", action="store_true", help="Genera el SQL y no toca la BD.")
    args = ap.parse_args()

    sql = generar_sql()
    SALIDA.parent.mkdir(parents=True, exist_ok=True)
    SALIDA.write_text(sql, encoding="utf-8", newline="\n")
    print(f"SQL generado: {SALIDA}  ({len(sql.splitlines())} líneas)")
    for ln in sql.splitlines():
        if ln.startswith("--  ") and ("....." in ln or "OMITIDOS" in ln or "sin descripción" in ln):
            print("  " + ln[4:])
    if not args.solo_sql:
        cargar(sql)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
