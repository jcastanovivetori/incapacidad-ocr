# -*- coding: utf-8 -*-
"""Reproduccion de los hallazgos ANTES de la correccion (linea base)."""
import sys, json
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
from incapacidad_ocr.extract import normalizar_fechas

HOY = date(2026, 9, 2)

class LookupsResuelve(erp.LookupsNulos):
    def empleado_por_cedula(self, c): return (1, "PACIENTE DEMO", "NUEVA EPS") if c else (None, None, None)
    def diagnostico_por_codigo(self, c): return (7, "DX DEMO") if c else (None, None)
    def id_entidad_por_nombre(self, n): return (1, 1, "NUEVA EPS") if n else (None, None, None)

def rec(**inc):
    return {"incapacidad": {"tipo_documento": "incapacidad",
            "paciente": {"nombre": "X", "documento_numero": "1098765432"},
            "entidad": {"eps": "NUEVA EPS"},
            "diagnostico": {"cie10": "J06.9"},
            "incapacidad": dict(inc)}}

def corre(nombre, normaliza=True, overrides=None, **inc):
    r = rec(**inc)
    if normaliza:
        normalizar_fechas(r["incapacidad"])
    m = erp.mapear_a_staging(r, "WHATSAPP", LookupsResuelve(), hoy=HOY, overrides=overrides)
    print(f"--- {nombre}")
    print("   inc final :", {k: r['incapacidad']['incapacidad'].get(k) for k in
                              ('fecha_inicio','fecha_fin','dias','fecha_inicio_calculada','fecha_fin_recalculada')})
    print("   row       :", {k: m['row'].get(k) for k in ('fechainicio','Numerodias','fechavencimiento','confianza_ocr')})
    print("   revision  :", m['requiere_revision'], "| problemas:", m['problemas'])
    return m

corre("G1/A26/D2 30 dias impresos vs 3 dias", fecha_inicio="2026-06-01", fecha_fin="2026-06-30", dias=3)
corre("G2/A7/D3 fin ANTERIOR al inicio con dias", fecha_inicio="2026-06-10", fecha_fin="2026-06-01", dias=3)
corre("G3/D4 dias=99999 CON fin", fecha_inicio="2026-06-01", fecha_fin="2026-06-10", dias=99999)
corre("G3/D5 dias=99999 SIN fin", fecha_inicio="2026-06-01", dias=99999)
corre("G4/D8 dias=0 con fechas", fecha_inicio="2026-06-01", fecha_fin="2026-06-01", dias=0)
corre("G5/A8/D6 fin<inicio sin dias", fecha_inicio="2026-06-10", fecha_fin="2026-06-01")
corre("M-D9/A23 span de 541 dias", fecha_inicio="2026-01-01", fecha_fin="2027-06-25")
corre("M-D11/H12 fin tecleado anterior al inicio", fecha_inicio="2026-06-10", dias=3,
      overrides={"fecha_fin": "2026-05-01"})
corre("M-D12 dias tecleados vs fin impreso", fecha_inicio="2026-06-01", fecha_fin="2026-06-30",
      overrides={"dias": "3"})
corre("M-B4 dias=0 sin fechas", dias=0)
corre("M-H10 dias='-3'", fecha_inicio="2026-06-09", overrides={"dias": "-3"})
corre("M-B5 dias=-5 int", fecha_inicio="2026-06-09", dias=-5)
corre("M-D7/H8 fecha imposible 2026-02-30", fecha_inicio="2026-02-30", dias=3)
corre("M-B15 dias=5.0 float", fecha_inicio="2026-06-09", dias=5.0)
corre("M-A12/D16 dias=True", fecha_inicio="2026-06-01", fecha_fin="2026-06-10", dias=True)
corre("M-A10 dias=' 5 '", fecha_fin="2026-06-10", dias=" 5 ")
corre("M-D10 inicio CALCULADO -> confianza", fecha_fin="2026-06-10", dias=5)
corre("M-D13 inicio 2030 (futuro)", fecha_inicio="2030-01-01", dias=5)
corre("M-D14 inicio 1900 (antiguo)", fecha_inicio="1900-01-01", dias=5)
corre("G7/H6/D15 fecha ISO de semana 2026-W23-1", fecha_inicio="2026-W23-1", dias=3)
corre("G6/H2 dias='\u00b2' (digito unicode)", fecha_inicio="2026-06-01", dias="\u00b2")
corre("G6/H11 dias con 10000 digitos", fecha_inicio="2026-06-01", dias="9"*10000)
# H4/H5: sub-dicts que llegan como lista
try:
    r = {"incapacidad": {"incapacidad": [1], "paciente": {}, "entidad": {}, "diagnostico": {}}}
    erp.mapear_a_staging(r, "WHATSAPP", erp.LookupsNulos(), hoy=HOY)
    print("--- G6/H4 incapacidad=[1]: OK (no explota)")
except Exception as e:
    print("--- G6/H4 incapacidad=[1]:", type(e).__name__, e)
try:
    r = {"incapacidad": {"incapacidad": {}, "paciente": ["X"], "entidad": {}, "diagnostico": {}}}
    erp.mapear_a_staging(r, "WHATSAPP", erp.LookupsNulos(), hoy=HOY)
    print("--- G6/H5 paciente=['X']: OK (no explota)")
except Exception as e:
    print("--- G6/H5 paciente=['X']:", type(e).__name__, e)
