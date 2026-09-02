# -*- coding: utf-8 -*-
"""Auditoria del ANCLA con que el modulo nuevo lee la duracion en cada documento.

Un valor correcto por CASUALIDAD (leido de otro sitio del documento) es una
regresion latente: aqui se imprime de donde sale cada lectura para revisarla a mano.
"""
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
BASE = Path(str(_DATASET))
sys.path.insert(0, str(_REPO))
from incapacidad_ocr.numeros_es import duracion_en_texto

for sub in ("falsas", "falsa", "reales", "real"):
    for p in sorted((BASE / "ocr" / sub).glob("*.txt")):
        d = duracion_en_texto(p.read_text(encoding="utf-8"))
        nom = f"{sub}/{p.stem}"[:52]
        if d is None:
            print(f"{nom:52s} -> None")
        else:
            print(f"{nom:52s} -> valor={d['valor']} origen={d['origen']:6s} "
                  f"letra={d['letra']} num={d['numero']} coin={d['coincide']} "
                  f"ev={d['evidencia']!r}")
