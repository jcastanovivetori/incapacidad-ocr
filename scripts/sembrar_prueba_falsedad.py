"""Siembra el corpus REAL de prueba (incapacidades falsas y reales) en la ingesta.

Toma los 31 documentos que el cliente entregó (15 adulterados + 16 legítimos, organizados en
``../dataset-falsedad/docs/``), los renombra a la **nomenclatura de entrada**
``{cedula}_{TIPODOC}.{ext}`` y los deja en ``ingesta/_sistema/semilla/<canal>/``. Después llama a
``batch.reiniciar_prueba()``, que copia la semilla a ``1_entrada/`` — de modo que la prueba se puede
repetir tantas veces como se quiera (con el botón «Reiniciar prueba» de la UI o con
``python -m incapacidad_ocr.batch --reiniciar``).

De dónde sale la cédula de cada archivo:
  - **reales:** ya vienen nombrados ``cedula_TIPODOC.ext`` → se toma del propio nombre.
  - **falsas:** los nombres del cliente no siguen la nomenclatura (``INC APELLIDO NOMBRE fecha.pdf``),
    así que se usa la cédula que el **OCR leyó** del documento (``dataset-falsedad/ocr/falsas/*.json``).
  - si el OCR no pudo leer ninguna, se genera una **cédula sintética** determinista (empieza por 9 y
    tiene 10 dígitos, para que se reconozca a simple vista como inventada) y se marca en el mapeo.

AVISO SOBRE LA AGRUPACIÓN — no es un error, es el dominio: la **llave de caso es la cédula**, así que
varios documentos del MISMO empleado forman UN solo trámite y sólo se OCR-ea un documento base. Tres
incapacidades de la misma persona (pasa en este corpus) entran como un caso y el lote lo marca con
"Hay N documentos base para la cédula X (¿trámites distintos?)". El mapeo (``MAPEO.csv``) deja a la
vista cuántos documentos comparten cédula para que nadie interprete que se perdieron archivos. Para
evaluar un documento suelto, la UI tiene el arrastrar-y-soltar (``/api/procesar``).

    python scripts/sembrar_prueba_falsedad.py [--dry-run]
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import shutil
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
from incapacidad_ocr.batch import ENTRADA, SEMILLA, SISTEMA, asegurar_estructura, reiniciar_prueba  # noqa: E402

DATASET = REPO.parent / "dataset-falsedad"
INGESTA = REPO / "ingesta"
DESTINO = INGESTA / SISTEMA / SEMILLA
# Los tres canales se reparten de forma estable para ejercitar el estado de recepción
# (ORIGINAL/WHATSAPP/CORREO) sin que el canal quede correlacionado con la etiqueta.
CANALES = ("whatsapp", "correo", "ventanilla")

# Tipos de documento del vocabulario del repo (ver erp.canon_doc). El corpus de falsas es todo
# incapacidades; en los reales el tipo viene en el propio nombre (con una errata: "inpacacidad").
_ALIAS_TIPO = {
    "INPACACIDAD": "INCAPACIDAD",
    "INCAPACIDAD": "INCAPACIDAD",
    "PERMISO": "PERMISO",
    "VACACIONES": "VACACIONES",
    "HISTORIA": "HISTORIA",
    "EPICRISIS": "EPICRISIS",
    "FURAT": "FURAT",
}


def _cedula_sintetica(nombre: str) -> str:
    """Cédula inventada, estable y reconocible: 9 + 9 dígitos derivados del nombre del archivo."""
    h = hashlib.sha256(nombre.encode("utf-8")).hexdigest()
    return "9" + str(int(h[:12], 16))[:9].rjust(9, "0")


def _cedula_de_nombre(nombre: str) -> tuple[str | None, str | None]:
    """Para los reales: `1000000001_INCAPACIDAD.pdf` → ('1000000001', 'INCAPACIDAD').

    La cédula del ejemplo es ficticia a propósito: este archivo se versiona (Ley 1581)."""
    m = re.match(r"^(\d{5,15})[_-]([A-Za-z]+)", Path(nombre).stem)
    if not m:
        return None, None
    return m.group(1), _ALIAS_TIPO.get(m.group(2).upper(), "OTRO")


def _cedula_de_ocr(etiqueta: str, nombre: str) -> str | None:
    """Para las falsas: la cédula que el OCR leyó del documento (si la leyó)."""
    j = DATASET / "ocr" / etiqueta / (Path(nombre).stem + ".json")
    if not j.is_file():
        return None
    try:
        d = json.loads(j.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001 — un JSON ilegible no debe tumbar el sembrado
        return None
    pac = ((d.get("incapacidad") or {}).get("paciente") or {})
    ced = re.sub(r"\D", "", str(pac.get("documento_numero") or ""))
    return ced if 5 <= len(ced) <= 15 else None


def _motivos_ground_truth() -> dict[str, str]:
    """archivo original → señales de adulteración declaradas por el cliente (si hay ground truth)."""
    p = DATASET / "ground_truth.json"
    if not p.is_file():
        return {}
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}
    out = {}
    for fila in d.get("filas") or []:
        senales = fila.get("senales") or []
        out[fila.get("archivo", "")] = ";".join(senales) if senales else (fila.get("motivo_texto") or "")
    return out


def _cuarentena() -> dict[str, str]:
    """archivo → motivo, leído del manifest (etiquetas en conflicto que no son verdad usable)."""
    p = DATASET / "manifest.csv"
    if not p.is_file():
        return {}
    out = {}
    with p.open(encoding="utf-8", newline="") as fh:
        for r in csv.DictReader(fh):
            if (r.get("cuarentena") or "").strip().lower() == "si":
                out[r.get("archivo", "")] = r.get("motivo_cuarentena", "") or "en cuarentena"
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="Siembra el corpus real de prueba (falsas y reales).")
    ap.add_argument("--dry-run", action="store_true", help="Solo reporta lo que haría.")
    args = ap.parse_args()

    if not (DATASET / "docs").is_dir():
        print(f"No existe {DATASET / 'docs'}. Corre antes la organización del corpus.")
        return 1

    motivos, cuarentena = _motivos_ground_truth(), _cuarentena()
    filas, i = [], 0
    for etiqueta in ("falsas", "reales"):
        base = DATASET / "docs" / etiqueta
        for f in sorted(base.iterdir()) if base.is_dir() else []:
            if not f.is_file():
                continue
            if etiqueta == "reales":
                ced, tipo = _cedula_de_nombre(f.name)
                origen_ced = "nombre"
            else:
                ced, tipo, origen_ced = _cedula_de_ocr(etiqueta, f.name), "INCAPACIDAD", "ocr"
            if not ced:
                ced, origen_ced = _cedula_sintetica(f.name), "sintetica"
            tipo = tipo or "INCAPACIDAD"
            canal = CANALES[i % len(CANALES)]
            i += 1
            filas.append({
                "archivo_original": f.name, "ruta_original": str(f),
                "archivo_semilla": f"{ced}_{tipo}{f.suffix.lower()}",
                "canal": canal, "etiqueta": "falsa" if etiqueta == "falsas" else "real",
                "cedula": ced, "origen_cedula": origen_ced, "tipodoc": tipo,
                "senales_declaradas": motivos.get(f.name, ""),
                "cuarentena": "si" if f.name in cuarentena else "no",
                "motivo_cuarentena": cuarentena.get(f.name, ""),
            })

    # Varios documentos pueden caer en el MISMO nombre de semilla (misma cédula y mismo tipo):
    # se numeran con el sufijo _NN que la propia nomenclatura contempla, para no sobre-escribir.
    # La unicidad se exige GLOBALMENTE, no por canal: aunque estén en carpetas distintas, el lote
    # los agrupa en el mismo caso y acabarían en la misma carpeta de salida.
    vistos: dict[str, int] = {}
    for fila in filas:
        clave = fila["archivo_semilla"]
        if clave in vistos:
            vistos[clave] += 1
            stem = Path(fila["archivo_semilla"]).stem
            ext = Path(fila["archivo_semilla"]).suffix
            fila["archivo_semilla"] = f"{stem}_{vistos[clave]:02d}{ext}"
        else:
            vistos[clave] = 1

    por_cedula: dict[str, int] = {}
    for fila in filas:
        por_cedula[fila["cedula"]] = por_cedula.get(fila["cedula"], 0) + 1
    for fila in filas:
        fila["docs_misma_cedula"] = por_cedula[fila["cedula"]]

    print(f"{len(filas)} documentos · {len(por_cedula)} cédulas distintas (= casos que verá el lote)")
    compartidas = {c: n for c, n in por_cedula.items() if n > 1}
    if compartidas:
        print(f"  {len(compartidas)} cédulas con varios documentos "
              f"(el lote los agrupa en un caso y avisa): {compartidas}")
    if args.dry_run:
        for fila in filas:
            print(f"  {fila['etiqueta']:5} {fila['archivo_original'][:46]:48} -> "
                  f"{fila['canal']}/{fila['archivo_semilla']}  (cédula {fila['origen_cedula']})")
        return 0

    # Semilla limpia: se rehace desde cero para que sembrar dos veces dé el mismo resultado.
    asegurar_estructura(INGESTA)
    if DESTINO.exists():
        shutil.rmtree(DESTINO)
    for fila in filas:
        destino = DESTINO / fila["canal"] / fila["archivo_semilla"]
        destino.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(fila["ruta_original"], destino)

    campos = ["archivo_original", "archivo_semilla", "canal", "etiqueta", "cedula", "origen_cedula",
              "tipodoc", "docs_misma_cedula", "senales_declaradas", "cuarentena", "motivo_cuarentena"]
    with (DESTINO / "MAPEO.csv").open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=campos, extrasaction="ignore")
        w.writeheader()
        w.writerows(filas)

    print(f"Semilla escrita en {DESTINO}")
    r = reiniciar_prueba(INGESTA, limpiar_bd=True)
    print(f"1_entrada cargada: {r['restaurados']} documentos (modo {r['modo']})")
    for aviso in r["avisos"]:
        print("  aviso:", aviso)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
