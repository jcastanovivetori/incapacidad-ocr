# -*- coding: utf-8 -*-
"""Casos que NO pasan por normalizar_fechas (ruta del API /api/mapear)."""
import sys
from datetime import date

# --- Rutas relativas (añadidas por scripts/exportar_analisis.py) --------------------------
# Este script se escribió con rutas ABSOLUTAS de la máquina donde se investigó. Se resuelven
# desde la ubicación del propio archivo para que funcione tras un `git pull` en cualquier
# equipo. El corpus (`dataset-falsedad/`) NO está en el repositorio: lo aporta el cliente.
import pathlib as _pl
_REPO = _pl.Path(__file__).resolve().parents[3]
_DATASET = _REPO.parent / "dataset-falsedad"
_EJEMPLOS = _REPO.parent / "Ejemplos"
# ------------------------------------------------------------------------------------------
sys.path.insert(0, str(_REPO))
from incapacidad_ocr import erp
HOY = date(2026, 9, 2)

def base(**inc):
    return {"incapacidad": {"tipo_documento": "incapacidad",
            "paciente": {"documento_numero": "1098765432"}, "entidad": {"eps": "NUEVA EPS"},
            "diagnostico": {"cie10": "J06.9"}, "incapacidad": dict(inc)}}

for nombre, kw, ov in [
    ("H2 dias='\u00b2'", {"fecha_inicio": "2026-06-01"}, {"dias": "\u00b2"}),
    ("H3 dias='\u2075'", {"fecha_inicio": "2026-06-01"}, {"dias": "\u2075"}),
    ("H11 dias 10000 digitos", {"fecha_inicio": "2026-06-01"}, {"dias": "9"*10000}),
]:
    try:
        m = erp.mapear_a_staging(base(**kw), "WHATSAPP", erp.LookupsNulos(), hoy=HOY, overrides=ov)
        print(f"--- {nombre}: OK Numerodias={m['row']['Numerodias']!r} problemas={m['problemas']}")
    except Exception as e:
        print(f"--- {nombre}: {type(e).__name__}: {ascii(str(e))[:90]}")
for nombre, r in [
    ("H4 incapacidad=[1]", {"incapacidad": {"incapacidad": [1], "paciente": {}, "entidad": {}, "diagnostico": {}}}),
    ("H5 paciente=['X']", {"incapacidad": {"incapacidad": {}, "paciente": ["X"], "entidad": {}, "diagnostico": {}}}),
]:
    try:
        erp.mapear_a_staging(r, "WHATSAPP", erp.LookupsNulos(), hoy=HOY)
        print(f"--- {nombre}: OK (no explota)")
    except Exception as e:
        print(f"--- {nombre}: {type(e).__name__}: {ascii(str(e))[:90]}")
