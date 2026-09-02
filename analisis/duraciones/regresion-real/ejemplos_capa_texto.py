# -*- coding: utf-8 -*-
"""Reduce el punto ciego de ../Ejemplos SIN correr OCR: lee la CAPA DE TEXTO de los
PDF con PDFium (extraccion de texto, no reconocimiento) y compara el 'dias' que leen
el extractor ANTES y AHORA. No sustituye a tests/test_ejemplos_reales.py (que necesita
RapidOCR sobre los escaneos), pero cubre los PDF que traen texto.
"""
import importlib.util, sys
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
EJ = Path(str(_EJEMPLOS))
AQUI = Path(__file__).resolve().parent
sys.path.insert(0, str(_REPO))
import pypdfium2 as pdfium
from incapacidad_ocr.extract import RuleBasedExtractor, normalizar_fechas
from incapacidad_ocr.numeros_es import duracion_en_texto

spec = importlib.util.spec_from_file_location("ea", AQUI / "extract_antes.py")
ea = importlib.util.module_from_spec(spec); spec.loader.exec_module(ea)

# dias esperados (ground truth de tests/test_ejemplos_reales.py)
GT = {
    "ALEJANDRO LINARES.pdf": 30,
    "CESAR ARMANDO LANCHEROS CHAPARRO_INCAPACIDAD.pdf": 3,
    "INCAPACIDAD <NOMBRE> <NOMBRE> <NOMBRE> V\u0118LANDIA.pdf": 30,
    "Incapacidad (19)_unlocked.pdf": None,   # no esta en el GT por nombre; se anota
    "incapacidad.pdf": None,
}
for p in sorted(EJ.glob("*.pdf")):
    doc = pdfium.PdfDocument(str(p))
    try:
        partes = []
        for i in range(len(doc)):
            tp = doc[i].get_textpage()
            partes.append(tp.get_text_bounded() or "")
    finally:
        doc.close()
    texto = "\n".join(partes)
    if len(texto.strip()) < 50:
        print(f"{p.name[:50]:52s} SIN capa de texto ({len(texto.strip())} chars) -> no evaluable sin OCR")
        continue
    ra = ea.RuleBasedExtractor().extract(texto); ea.normalizar_fechas(ra)
    rb = RuleBasedExtractor().extract(texto); normalizar_fechas(rb)
    d = duracion_en_texto(texto)
    print(f"{p.name[:50]:52s} chars={len(texto):5d} antes={ra['incapacidad']['dias']} "
          f"ahora={rb['incapacidad']['dias']} letra={rb['incapacidad']['dias_letra']} "
          f"coin={rb['incapacidad']['dias_letra_coincide']} "
          f"modulo={(d or {}).get('valor')} ev={(d or {}).get('evidencia')!r} GT={GT.get(p.name)}")
