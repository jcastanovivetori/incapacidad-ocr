# -*- coding: utf-8 -*-
"""Contexto de los candidatos a duracion en la capa de texto de 3 PDF concretos."""
import sys, re
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
import pypdfium2 as pdfium
from incapacidad_ocr.numeros_es import (normalizar, _candidatos_por_unidad,
                                        _candidatos_por_etiqueta)

OBJETIVO = [
    "falsas/FALSA-04.pdf",
    "falsas/FALSA-03.pdf",
    "falsas/FALSA-15.pdf",
]
for rel in OBJETIVO:
    p = BASE / "docs" / rel
    doc = pdfium.PdfDocument(str(p))
    partes = [doc[i].get_textpage().get_text_bounded() or "" for i in range(len(doc))]
    doc.close()
    print(f"\n########## {rel}  ({len(partes)} pagina(s)) ##########")
    lineas = normalizar("\n".join(partes)).split("\n")
    cands = []
    for i, l in enumerate(lineas):
        cands += _candidatos_por_unidad(i, l)
        cands += _candidatos_por_etiqueta(i, lineas)
    cands.sort(key=lambda c: c[0])
    for clave, rec in cands:
        print(f"  prio={clave} valor={rec['valor']} origen={rec['origen']:6s} "
              f"letra={rec['letra']} num={rec['numero']} ev={rec['evidencia']!r}")
    # renglones que mencionan duracion/dias, para ver donde vive cada candidato
    print("  --- renglones con 'dia'/'duracion' (normalizados) ---")
    for i, l in enumerate(lineas):
        if re.search(r"dia|duracion", l):
            print(f"   [{i:3d}] {l[:110]!r}")
