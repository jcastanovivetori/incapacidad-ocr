# -*- coding: utf-8 -*-
"""¿Que APORTA la correccion OCR `\bdian\b -> dias` en el corpus real?

Se recompila `numeros_es` SIN esa correccion (monkeypatch en memoria, no se toca el
repo) y se comparan los 31 textos OCR + las 13 capas de texto de docs/.
"""
import re, sys
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
from incapacidad_ocr import numeros_es
from incapacidad_ocr.extract import RuleBasedExtractor, normalizar_fechas

CON = tuple(numeros_es._CORRECCIONES_OCR)
SIN = tuple(c for c in CON if "dian" not in c[0])
assert len(SIN) == len(CON) - 1

def dias(texto):
    r = RuleBasedExtractor().extract(texto); normalizar_fechas(r)
    i = r["incapacidad"]
    return i["dias"], i["fecha_inicio"], i["fecha_fin"]

def barrido(pares):
    difs = []
    for nombre, texto in pares:
        numeros_es._CORRECCIONES_OCR = CON
        a = dias(texto)
        numeros_es._CORRECCIONES_OCR = SIN
        b = dias(texto)
        numeros_es._CORRECCIONES_OCR = CON
        if a != b:
            difs.append((nombre, a, b))
    return difs

pares = []
for sub in ("falsas", "falsa", "reales", "real"):
    for p in sorted((BASE / "ocr" / sub).glob("*.txt")):
        pares.append((f"ocr/{sub}/{p.stem}", p.read_text(encoding="utf-8")))
for sub in ("falsas", "reales"):
    for p in sorted((BASE / "docs" / sub).glob("*.pdf")):
        try:
            d = pdfium.PdfDocument(str(p))
            t = "\n".join(d[i].get_textpage().get_text_bounded() or "" for i in range(len(d)))
            d.close()
        except Exception:
            continue
        if len(t.strip()) >= 50:
            pares.append((f"capa/{sub}/{p.stem}", t))

print(f"entradas comparadas: {len(pares)}")
print("documentos donde la correccion 'dian->dias' CAMBIA el resultado")
print("  (con_correccion) vs (sin_correccion)  ->  (dias, inicio, fin)")
for nombre, a, b in barrido(pares):
    print(f"  {nombre[:56]:58s} con={a}  sin={b}")
