"""Baseline: que dias lee el extractor HOY sobre los 31 .txt YA CACHEADOS.

No corre OCR (hay otra medicion de rendimiento en la maquina): lee los textos de
dataset-falsedad/ocr/**. Imprime solo NOMBRE DE ARCHIVO + duracion (sin PII).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

# --- Rutas relativas (añadidas por scripts/exportar_analisis.py) --------------------------
# Este script se escribió con rutas ABSOLUTAS de la máquina donde se investigó. Se resuelven
# desde la ubicación del propio archivo para que funcione tras un `git pull` en cualquier
# equipo. El corpus (`dataset-falsedad/`) NO está en el repositorio: lo aporta el cliente.
import pathlib as _pl
_REPO = _pl.Path(__file__).resolve().parents[3]
_DATASET = _REPO.parent / "dataset-falsedad"
_EJEMPLOS = _REPO.parent / "Ejemplos"
# ------------------------------------------------------------------------------------------

REPO = Path(str(_REPO))
sys.path.insert(0, str(REPO))

from incapacidad_ocr.extract import (  # noqa: E402
    RuleBasedExtractor, es_formato_permiso, es_formato_vacaciones, normalizar_fechas,
)
from incapacidad_ocr.numeros_es import duracion_en_texto  # noqa: E402

OCR = Path(str(_DATASET / "ocr"))
GT = json.loads((OCR.parent / "ground_truth.json").read_text(encoding="utf-8", errors="replace"))


def main() -> None:
    ext = RuleBasedExtractor()
    print(f"{'archivo':62s} {'tipo':12s} {'dias':>5s} {'letra':>5s} {'coin':>5s} {'modulo':>7s}")
    print("-" * 106)
    for d in sorted(OCR.iterdir()):
        if not d.is_dir():
            continue
        for f in sorted(d.glob("*.txt")):
            texto = f.read_text(encoding="utf-8", errors="replace")
            rec = normalizar_fechas(ext.extract(texto))
            inc = rec["incapacidad"]
            dur = duracion_en_texto(texto)
            tipo = rec["tipo_documento"]
            print(f"{d.name + '/' + f.stem[:52]:62s} {tipo:12s} "
                  f"{str(inc['dias']):>5s} {str(inc['dias_letra']):>5s} "
                  f"{str(inc['dias_letra_coincide']):>5s} "
                  f"{(str(dur['valor']) + '/' + dur['origen']) if dur else '-':>7s}")


if __name__ == "__main__":
    main()
