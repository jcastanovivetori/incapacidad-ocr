# -*- coding: utf-8 -*-
"""TODOS los candidatos a duracion que el modulo genera por documento (texto OCR).

Sirve para medir cuan ajustada es la eleccion: si un documento tiene varios
candidatos con valores DISTINTOS y la misma prioridad, el resultado depende del
ORDEN de las lineas -> riesgo latente (basta que el OCR reordene para que cambie).
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
from incapacidad_ocr.numeros_es import (normalizar, _candidatos_por_unidad,
                                        _candidatos_por_etiqueta)

for sub in ("falsas", "falsa", "reales", "real"):
    for p in sorted((BASE / "ocr" / sub).glob("*.txt")):
        lineas = normalizar(p.read_text(encoding="utf-8")).split("\n")
        cands = []
        for i, l in enumerate(lineas):
            cands += _candidatos_por_unidad(i, l)
            cands += _candidatos_por_etiqueta(i, lineas)
        cands.sort(key=lambda c: c[0])
        vals = {c[1]["valor"] for c in cands}
        aviso = "  <-- VARIOS VALORES DISTINTOS" if len(vals) > 1 else ""
        print(f"{f'{sub}/{p.stem}'[:50]:52s} n={len(cands)} valores={sorted(v for v in vals if v is not None)}{aviso}")
        if len(vals) > 1:
            for clave, rec in cands:
                print(f"      prio={clave} valor={rec['valor']} origen={rec['origen']} ev={rec['evidencia']!r}")
