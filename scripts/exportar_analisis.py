"""Trae al repositorio el análisis del corpus, REDACTANDO los datos personales.

El trabajo de análisis (sondas de detección de falsedad, evidencia de duraciones, informes de
verificación, benchmark) vive junto al corpus, en `../dataset-falsedad/`, que está **fuera del
repositorio** porque el corpus son documentos de salud (Ley 1581). El problema práctico: si ese
análisis no se versiona, un `git pull` en otra máquina no lo trae y hay que rehacerlo.

Este script separa las dos cosas:

* **Se copia al repo** (`analisis/`): scripts, sondas e informes — el CONOCIMIENTO.
* **No se copia nunca**: los documentos, el texto OCR y cualquier archivo con datos de personas.

Y para que los informes sigan siendo legibles sin exponer a nadie, **redacta**: cada documento
del corpus pasa a un seudónimo estable (`FALSA-03`, `REAL-11`), cada cédula a `CED-xx` y cada
nombre de persona a `<NOMBRE>`. El seudónimo es estable entre corridas, así que dos informes
que hablan del mismo documento siguen coincidiendo. La correspondencia seudónimo → documento
real se queda FUERA del repo (`../dataset-falsedad/SEUDONIMOS.csv`): es el puente con la PII.

Al final **verifica su propio trabajo**: vuelve a barrer lo copiado buscando cualquier término
personal y aborta si encuentra uno. Si el barrido falla, no se copia nada.

    python scripts/exportar_analisis.py [--dry-run]
"""
from __future__ import annotations

import argparse
import csv
import re
import shutil
import sys
from pathlib import Path

try:  # consola Windows (cp1252) → forzar UTF-8 para acentos y flechas
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # noqa: BLE001
    pass

REPO = Path(__file__).resolve().parent.parent
DATASET = REPO.parent / "dataset-falsedad"
DESTINO = REPO / "analisis"
MAPA_SEUDONIMOS = DATASET / "SEUDONIMOS.csv"

# Qué se copia: extensiones de CONOCIMIENTO (código y texto). Todo lo demás se ignora por
# defecto — es la lista blanca la que decide, no una lista negra que se pueda quedar corta.
EXT_COPIABLES = {".py", ".md", ".sql", ".json", ".txt", ".csv"}
# Sub-árboles que NO se copian jamás, por mucho que su extensión esté en la lista blanca.
EXCLUIR_DIRS = {"docs", "ocr", "__pycache__"}
# Archivos que son PURO puente con la PII (nombres de archivo del cliente + cédulas): no se
# copian ni redactados, porque su valor ES la correspondencia con las personas.
EXCLUIR_ARCHIVOS = {"manifest.csv", "seed_bd_prueba.sql", "SEUDONIMOS.csv"}


def _terminos_pii() -> tuple[dict[str, str], list[tuple[re.Pattern, str]]]:
    """(mapa literal → reemplazo, patrones regex → reemplazo) construidos DEL CORPUS REAL."""
    literales: dict[str, str] = {}
    # 1) Nombres de archivo del cliente → seudónimo estable por clase y orden alfabético.
    for clase, prefijo in (("falsas", "FALSA"), ("reales", "REAL")):
        base = DATASET / "docs" / clase
        for i, f in enumerate(sorted(base.iterdir()) if base.is_dir() else [], start=1):
            if not f.is_file():
                continue
            seudo = f"{prefijo}-{i:02d}"
            literales[f.name] = f"{seudo}{f.suffix}"      # con extensión
            literales[f.stem] = seudo                      # y sin ella (los informes usan las dos)
    # 2) Nombres de persona sueltos: los tokens de los nombres de archivo de las adulteradas
    #    (son nombres escritos por una persona, así que están completos y bien escritos).
    #    OJO con el ruido: el campo "nombre del paciente" que devuelve el OCR trae a veces
    #    RÓTULOS del documento en vez del nombre ("DETALLE DE LA INCAPACIDAD", "Remunerado",
    #    "FIRMA DEL MEDICO"). Si esos tokens entran en la lista, la redacción destroza el
    #    CÓDIGO: `detalle` es un nombre de variable normalísimo y sustituirlo por <NOMBRE>
    #    deja los scripts sin compilar (pasó: 7 archivos). La lista de ruido es la guarda.
    ruido = {
        "INC", "INCAPACIDAD", "DIAS", "DÍAS", "DETALLE", "REMUNERADO", "FIRMA", "MEDICO",
        "HISTORIA", "CLINICA", "PACIENTE", "USUARIO", "NOMBRE", "NOMBRES", "APELLIDOS",
        "DOCUMENTO", "IDENTIFICACION", "CEDULA", "PERMISO", "VACACIONES", "EPICRISIS",
        "DIAGNOSTICO", "ENTIDAD", "PRESTADOR", "CERTIFICADO", "SOLICITUD", "FORMATO",
        "RESPONSABLE", "PERSONA", "TRABAJADOR", "EMPLEADO", "GENERAL", "TOTAL", "SALUD",
        "CONTRIBUTIVO", "COTIZANTE", "REGIMEN", "FECHA", "FECHAS", "INICIO", "FINAL",
        "DURACION", "ORIGEN", "TIPO", "CODIGO", "REGISTRO", "PROFESIONAL", "ATENCION",
        "CONSULTA", "EXTERNA", "MEDICA", "MEDICAS", "AUTORIZADO", "SOLICITADO", "CARGO",
        "EMPRESA", "SEDE", "CIUDAD", "DIRECCION", "TELEFONO", "CORREO", "WHATSAPP",
    }
    nombres: set[str] = set()
    d = DATASET / "docs" / "falsas"
    for f in (d.iterdir() if d.is_dir() else []):
        m = re.match(r"^INC\s+(.+?)\s+\d", f.stem, re.I)
        if m:
            nombres |= {t.upper() for t in m.group(1).split() if len(t) >= 4} - ruido
    # 3) Cédulas: las de los nombres de archivo de las legítimas y las que leyó el OCR.
    cedulas: set[str] = set()
    d = DATASET / "docs" / "reales"
    for f in (d.iterdir() if d.is_dir() else []):
        m = re.match(r"^(\d{7,12})", f.stem)
        if m:
            cedulas.add(m.group(1))
    if (DATASET / "ocr").is_dir():
        import json
        for j in (DATASET / "ocr").rglob("*.json"):
            try:
                dd = json.loads(j.read_text(encoding="utf-8"))
            except Exception:  # noqa: BLE001
                continue
            pac = ((dd.get("incapacidad") or {}).get("paciente") or {})
            ced = re.sub(r"\D", "", str(pac.get("documento_numero") or ""))
            if 7 <= len(ced) <= 12:
                cedulas.add(ced)
            nom = str(pac.get("nombre") or "").upper()
            nombres |= {t for t in re.split(r"[^A-ZÑ]+", nom) if len(t) >= 6} - ruido

    for i, ced in enumerate(sorted(cedulas), start=1):
        literales[ced] = f"CED-{i:02d}"
    # 4) La carpeta de entrega del cliente lleva el nombre de usuario de la máquina: no es
    #    dato de un paciente, pero tampoco tiene por qué quedar en el repositorio.
    descargas = Path.home() / "Downloads"
    for forma in (descargas.as_posix(), str(descargas), str(descargas).replace("\\", "\\\\")):
        literales[forma] = "<descargas>"
    casa = Path.home()
    for forma in (casa.as_posix(), str(casa), str(casa).replace("\\", "\\\\")):
        literales[forma] = "<usuario>"
    # Los nombres van por regex con frontera de palabra e insensible a mayúsculas, porque en
    # los informes aparecen en cualquier caja. Los más largos primero: si no, redactar
    # "RIVERA" dentro de "RIVERA OLIVEROS" deja el apellido suelto a medias.
    patrones = [(re.compile(rf"\b{re.escape(n)}\b", re.I), "<NOMBRE>")
                for n in sorted(nombres, key=len, reverse=True)]
    return literales, patrones


def redactar(texto: str, literales: dict[str, str], patrones) -> str:
    # Literales largos primero (un nombre de archivo contiene la cédula: si se redacta la
    # cédula antes, el nombre de archivo ya no se reconoce).
    for viejo in sorted(literales, key=len, reverse=True):
        texto = texto.replace(viejo, literales[viejo])
    for pat, repl in patrones:
        texto = pat.sub(repl, texto)
    return texto


# Prefijos absolutos de la máquina donde se hizo la investigación, en las cuatro formas en
# que los agentes los escribieron (mayúscula/minúscula de la unidad × barras / barras dobles).
_RAIZ = REPO.parent
_PREFIJOS = []
for _base, _marca in ((REPO.name, "_REPO"), ("dataset-falsedad", "_DATASET"),
                      ("Ejemplos", "_EJEMPLOS")):
    _p = f"{_RAIZ.as_posix()}/{_base}"
    # Se generan las 6 formas de escribir la MISMA ruta, incluida la unidad en minúscula:
    # asumir que `as_posix()` la devuelve en un caso concreto dejó sin sustituir las que los
    # agentes escribieron como `c:/…` (52 archivos con la ruta absoluta viva).
    for _variante in (_p, _p[0].lower() + _p[1:], _p[0].upper() + _p[1:]):
        _PREFIJOS += [(_variante, _marca),
                      (_variante.replace("/", "\\\\"), _marca),
                      (_variante.replace("/", "\\"), _marca)]
_PREFIJOS = sorted(set(_PREFIJOS), key=lambda t: -len(t[0]))

_CABECERA = '''
# --- Rutas relativas (añadidas por scripts/exportar_analisis.py) --------------------------
# Este script se escribió con rutas ABSOLUTAS de la máquina donde se investigó. Se resuelven
# desde la ubicación del propio archivo para que funcione tras un `git pull` en cualquier
# equipo. El corpus (`dataset-falsedad/`) NO está en el repositorio: lo aporta el cliente.
import pathlib as _pl
_REPO = _pl.Path(__file__).resolve().parents[{n}]
_DATASET = _REPO.parent / "dataset-falsedad"
_EJEMPLOS = _REPO.parent / "Ejemplos"
# ------------------------------------------------------------------------------------------
'''


def _relativizar(texto: str, rel: Path) -> tuple[str, int]:
    """Sustituye las rutas absolutas por expresiones basadas en `__file__`.

    En LÍNEAS DE CÓDIGO el literal `"<raiz>/incapacidad-ocr/x/y"` pasa a `str(_REPO / "x/y")`
    (una expresión es válida en cualquier sitio donde cabía un literal de cadena). En
    COMENTARIOS y texto se deja una forma legible (`<repo>/x/y`), porque ahí una expresión
    no significaría nada. Devuelve (texto, nº de sustituciones).
    """
    n_sub = 0
    profundidad = len(rel.parts)          # analisis/a/b/x.py -> parents[3] es la raíz del repo
    salida = []
    for linea in texto.splitlines():
        es_codigo = not linea.lstrip().startswith("#")
        for prefijo, marca in _PREFIJOS:
            if prefijo not in linea:
                continue
            if es_codigo:
                # Literal completo entre comillas: se convierte en expresión.
                def _rep(m):
                    nonlocal n_sub
                    n_sub += 1
                    suf = m.group("suf").lstrip("/\\").replace("\\\\", "/").replace("\\", "/")
                    return f'str({marca} / "{suf}")' if suf else f"str({marca})"
                patron = re.compile(
                    r"[rRbBfF]{0,2}(?P<q>['\"])" + re.escape(prefijo) + r"(?P<suf>[^'\"]*)(?P=q)")
                linea, k = patron.subn(_rep, linea)
                if k:
                    continue
            # Comentario, docstring o literal que no se pudo aislar: forma legible.
            legible = {"_REPO": "<repo>", "_DATASET": "<dataset-falsedad>",
                   "_EJEMPLOS": "<Ejemplos>"}[marca]
            linea = linea.replace(prefijo, legible)
            n_sub += 1
        salida.append(linea)
    texto = "\n".join(salida) + ("\n" if texto.endswith("\n") else "")
    if n_sub and rel.suffix == ".py" and "_REPO = _pl.Path" not in texto:
        # La cabecera tiene que ir ANTES del primer uso de _REPO/_DATASET (si no, el script
        # referencia un nombre que aún no existe: pasó, y dejó 7 archivos sin compilar) y
        # DESPUÉS de `from __future__`, que por regla del lenguaje va primero.
        lineas = texto.splitlines()
        primer_uso = next((i for i, l in enumerate(lineas)
                           if "_REPO" in l or "_DATASET" in l), len(lineas))
        tras_future = next((i + 1 for i, l in enumerate(lineas)
                            if l.startswith("from __future__")), 0)
        corte = max(tras_future, 0)
        # Dentro de ese margen, se busca el final del bloque de imports para no cortar en
        # medio de un docstring; nunca más allá del primer uso.
        for i, l in enumerate(lineas[:primer_uso]):
            if l.startswith(("import ", "from ")):
                corte = i + 1
        corte = min(corte, primer_uso)
        cabecera = _CABECERA.format(n=profundidad).strip("\n").splitlines()
        texto = "\n".join(lineas[:corte] + [""] + cabecera + lineas[corte:]) + "\n"
    return texto, n_sub


def _copiables() -> list[Path]:
    if not DATASET.is_dir():
        return []
    salida = []
    for f in sorted(DATASET.rglob("*")):
        if not f.is_file() or f.suffix.lower() not in EXT_COPIABLES:
            continue
        rel = f.relative_to(DATASET)
        if set(rel.parts) & EXCLUIR_DIRS or f.name in EXCLUIR_ARCHIVOS:
            continue
        salida.append(f)
    return salida


def _quedo_pii(texto: str, literales: dict[str, str], patrones) -> list[str]:
    """Términos personales que SOBREVIVIERON a la redacción (debería estar vacío)."""
    encontrados = []
    up = texto.upper()
    for viejo in literales:
        if viejo.upper() in up:
            encontrados.append(viejo)
    for pat, _ in patrones:
        if pat.search(texto):
            encontrados.append(pat.pattern)
    return encontrados


def main() -> int:
    ap = argparse.ArgumentParser(description="Exporta el análisis al repo, redactando PII.")
    ap.add_argument("--dry-run", action="store_true", help="Solo reporta lo que haría.")
    args = ap.parse_args()

    if not DATASET.is_dir():
        print(f"No existe {DATASET}: no hay análisis que exportar.")
        return 1
    literales, patrones = _terminos_pii()
    archivos = _copiables()
    print(f"{len(archivos)} archivo(s) copiables · "
          f"{len(literales)} literales y {len(patrones)} nombres a redactar")

    if not literales and not patrones:
        print("AVISO: no se construyó ningún término de redacción (¿falta el corpus en "
              "docs/?). Sin términos NO se copia nada: copiar sin redactar es el error que "
              "este script existe para evitar.")
        return 1

    problemas, escritos, rutas_arregladas = [], 0, 0
    for f in archivos:
        rel = f.relative_to(DATASET)
        try:
            texto = f.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            # Capturas de consola de Windows (cp1252). Se leen tolerando el encoding en vez
            # de descartarlas: son la salida medida de las sondas, y la redacción + su
            # verificación se aplican igual. Solo se pierden acentos.
            texto = f.read_text(encoding="cp1252", errors="replace")
            problemas.append(f"{rel}: no era UTF-8, se copió reinterpretado (acentos aproximados)")
        limpio = redactar(texto, literales, patrones)
        resto = _quedo_pii(limpio, literales, patrones)
        if resto:
            problemas.append(f"{rel}: quedó PII sin redactar ({resto[:3]}) — NO se copia")
            continue
        limpio, n_rutas = _relativizar(limpio, rel)
        if n_rutas:
            rutas_arregladas += 1
        destino = DESTINO / rel
        if not args.dry_run:
            destino.parent.mkdir(parents=True, exist_ok=True)
            destino.write_text(limpio, encoding="utf-8", newline="\n")
        escritos += 1

    if not args.dry_run:
        MAPA_SEUDONIMOS.write_text(
            "\n".join(["seudonimo,documento_real"] +
                      [f"{v},{k}" for k, v in sorted(literales.items(), key=lambda kv: kv[1])]),
            encoding="utf-8", newline="\n")
    print(f"{escritos} archivo(s) {'se copiarían' if args.dry_run else 'copiados'} a {DESTINO}")
    print(f"{rutas_arregladas} archivo(s) con rutas absolutas relativizadas")

    # VERIFICACIÓN OBLIGATORIA: redactar y relativizar EDITAN código, así que hay que
    # comprobar que lo escrito sigue siendo Python válido. Sin esto, un término de redacción
    # que coincida con un identificador (`detalle` → `<NOMBRE>`) rompe archivos en silencio.
    if not args.dry_run:
        import ast
        roto = []
        for f in DESTINO.rglob("*.py"):
            try:
                ast.parse(f.read_text(encoding="utf-8"))
            except SyntaxError as exc:
                roto.append(f"{f.relative_to(DESTINO)}:{exc.lineno} {exc.msg}")
        if roto:
            print(f"\n*** {len(roto)} archivo(s) .py quedaron SIN COMPILAR — revisar antes de commitear ***")
            for r in roto[:15]:
                print("  ", r)
            return 1
        print(f"verificado: los {sum(1 for _ in DESTINO.rglob('*.py'))} .py copiados compilan")
    print(f"correspondencia seudónimo → real: {MAPA_SEUDONIMOS} (FUERA del repo, es el puente con la PII)")
    for p in problemas:
        print("  AVISO:", p)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
