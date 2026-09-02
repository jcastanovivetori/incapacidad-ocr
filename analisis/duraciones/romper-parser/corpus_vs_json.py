"""Contraste sobre los 31 textos OCR ya cacheados (NO se corre OCR).

Compara la lectura del modulo (`duracion_en_texto`) y la del extractor de reglas
completo contra el campo `dias` que quedo guardado en el .json de cada documento
(salida del sistema ANTERIOR a este cambio). Sirve para detectar si el lector
nuevo cambia a PEOR alguna respuesta en documentos reales.
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
from incapacidad_ocr.extract import RuleBasedExtractor  # noqa: E402
from incapacidad_ocr.numeros_es import duracion_en_texto  # noqa: E402

BASE = Path(str(_DATASET / "ocr"))
EX = RuleBasedExtractor()

print(f"{'archivo':52} {'json':>5} {'modulo':>7} {'extract':>8} evidencia")
print("-" * 120)
difs = 0
for txt in sorted(BASE.rglob("*.txt")):
    t = txt.read_text(encoding="utf-8", errors="replace")
    js = txt.with_suffix(".json")
    prev = None
    if js.exists():
        d = json.loads(js.read_text(encoding="utf-8"))
        prev = (d.get("incapacidad", {}).get("incapacidad", {}) or {}).get("dias")
    dur = duracion_en_texto(t)
    rec = EX.extract(t)
    mod = dur["valor"] if dur else None
    ext = rec["incapacidad"]["dias"]
    marca = " " if ext == prev else "*"
    if marca == "*":
        difs += 1
    print(f"{marca}{txt.parent.name + '/' + txt.name:51.51} {str(prev):>5} {str(mod):>7} {str(ext):>8} "
          f"{(dur or {}).get('evidencia', '')[:38]!r}")
print("-" * 120)
print(f"filas con 'dias' distinto del .json: {difs}")
