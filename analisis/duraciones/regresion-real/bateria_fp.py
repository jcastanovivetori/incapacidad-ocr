# -*- coding: utf-8 -*-
"""Bateria de los falsos positivos que el inventario (01_evidencia.md §5) dice que
NO deben leerse como duracion. Cadenas tomadas de ese inventario (sin PII) mas
variantes plausibles del mismo formato. Esperado: None en todas."""
import sys

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
from incapacidad_ocr.numeros_es import duracion_en_texto

CASOS = [
    # --- del inventario, deben dar None ---
    "Causa que motiva la atencion: dolor desdo hacetresdias'.",
    "Edad: 33 Ano(s), 1 mes(es), 8 dia(s)",
    "Edad:31 ano(s), 3 mes(es), 22 dia(s)",
    "Insumos: 1 (Una)   1 (Uno)",
    "Vig: 1 dia",
    "SE DA INCAPACIDAD MEDICA POR 4 DIAS DESDE EL 29-07-26",   # debe dar 4, no 29
    "MARTES 09 DE/JUNIO Duracion\nDE2026",
    "DIASDEINCAPACIDAD\nAPARTIRDELAFECHA\nVIGENCIAS\nDIA\nMES\nANO\nFECHA DEINICIO\n12\n08\n2026",
    "3.DURACIONDELPERMISO",
    "NUMERO TOTAL DE HORAS  4 irs",
    "CUADRO CLINICO DE 3 HORAS DE EVOLUCION",
    "CADA 8 HORAS",
    "EDADGESTASIONAL:\n40.00 Semanas",
    "IncapacidadN:362.355",
    "Consecutivo:\n0081523489",
    "LICENCIA Nro. 0C41474361",
    "Regimen: 1 - Contributivo",
    "Nivel: 1",
    "Tipo de Usuario:COTIZANTE NIVEL1",
    "Pagina 1 de 1",
    "salvo que se trate de una fuerza mayor",
    "debera tener una cuenta bancaria inscrita",
    "Edad:22Anas   24 anos 05 meses   Rango de edad: 25-34",
    "F. Cardiaca: 80  Peso: 95  Sat.Oxigeno: 98  glasgow 15/15",
    "DX Relacionado 1:",
    "Tarjota Profesionat:661458",
    "01-Consulta externa",
    # --- variantes del hallazgo (numero de registro + unidad en el mismo renglon) ---
    "Profaslonal ce -,tl 295787.t1 DIAN",
    "Registro Profesional 295787 1 DIAS",
    "Tarjeta Profesional 52369 2 DIAS",
]
mal = 0
for s in CASOS:
    d = duracion_en_texto(s)
    ok = d is None
    esperado_valor = 4 if "POR 4 DIAS" in s else None
    if esperado_valor is not None:
        ok = d is not None and d["valor"] == esperado_valor
    print(f"{'OK  ' if ok else 'FALLA'} {s[:62]!r:66s} -> {None if d is None else d['valor']}")
    mal += 0 if ok else 1
print(f"\nfallos: {mal} de {len(CASOS)}")
