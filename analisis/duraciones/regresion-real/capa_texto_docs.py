# -*- coding: utf-8 -*-
"""Segunda superficie de ataque, tambien sin OCR: la CAPA DE TEXTO nativa de los PDF
de `dataset-falsedad/docs/`. Son los MISMOS documentos reales, pero con otra
degradacion (tildes conservadas, 'dia(s)', tablas de insumos, TODAS las paginas del
PDF) -> puede sacar regresiones que el texto de RapidOCR no ve.
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
BASE = Path(str(_DATASET))
AQUI = Path(__file__).resolve().parent
sys.path.insert(0, str(_REPO))
import pypdfium2 as pdfium
from incapacidad_ocr.extract import RuleBasedExtractor, normalizar_fechas
from incapacidad_ocr.numeros_es import duracion_en_texto

spec = importlib.util.spec_from_file_location("ea2", AQUI / "extract_antes.py")
ea = importlib.util.module_from_spec(spec); spec.loader.exec_module(ea)

def aplanar(rec):
    out = {}
    for k, v in rec.items():
        if isinstance(v, dict):
            for k2, v2 in v.items():
                if not k2.startswith("_"):
                    out[f"{k}.{k2}"] = v2
        else:
            out[k] = v
    return out

NUEVOS = {"incapacidad.dias_letra", "incapacidad.dias_letra_coincide",
          "incapacidad.fecha_fin_recalculada"}
PII = {"paciente.nombre", "paciente.documento_numero", "diagnostico.cie10",
       "diagnostico.descripcion", "medico.nombre", "medico.registro"}

con_texto = 0
con_dif = []
for sub in ("falsas", "reales"):
    for p in sorted((BASE / "docs" / sub).glob("*.pdf")):
        try:
            doc = pdfium.PdfDocument(str(p))
            partes = []
            for i in range(len(doc)):
                partes.append(doc[i].get_textpage().get_text_bounded() or "")
            doc.close()
        except Exception as e:
            print(f"  {sub}/{p.stem[:44]:46s} NO ABRE: {type(e).__name__}")
            continue
        texto = "\n".join(partes)
        if len(texto.strip()) < 50:
            continue
        con_texto += 1
        ra = ea.RuleBasedExtractor().extract(texto); ea.normalizar_fechas(ra)
        rb = RuleBasedExtractor().extract(texto); normalizar_fechas(rb)
        a, b = aplanar(ra), aplanar(rb)
        difs = {k: (a.get(k), b.get(k)) for k in set(a) | set(b)
                if k not in NUEVOS and a.get(k) != b.get(k)}
        d = duracion_en_texto(texto)
        marca = "DIF" if difs else "   "
        print(f"{marca} {sub}/{p.stem[:42]:44s} chars={len(texto):5d} "
              f"antes={str(a.get('incapacidad.dias')):>4s} ahora={str(b.get('incapacidad.dias')):>4s} "
              f"letra={str(b.get('incapacidad.dias_letra')):>4s} coin={str(b.get('incapacidad.dias_letra_coincide')):>5s} "
              f"finrec={str(b.get('incapacidad.fecha_fin_recalculada')):>5s} ev={(d or {}).get('evidencia')!r}")
        if difs:
            con_dif.append((f"{sub}/{p.stem}", difs))

print(f"\nPDF con capa de texto evaluados: {con_texto}")
print("== documentos con alguna diferencia ==")
if not con_dif:
    print("  (ninguno)")
for nombre, difs in con_dif:
    print(f"\n  {nombre}")
    for k, (va, vb) in sorted(difs.items()):
        if k in PII:
            print(f"    {k:38s} antes=<{'None' if va is None else 'valor'}> ahora=<{'None' if vb is None else 'valor'}>")
        else:
            print(f"    {k:38s} antes={va!r}  ahora={vb!r}")
