# -*- coding: utf-8 -*-
"""Reproduccion minima del hallazgo 'DIAN': la correccion OCR `\bdian\b -> dias`
(añadida por el '3Dian' de real/CED-18) convierte el renglon del registro
profesional de otro documento REAL en una duracion de 1 dia.

Linea real (capa de texto de docs/falsas/INC <NOMBRE> ... 02.09.2025.pdf, renglon 85):
    'Profaslonal ce -,tl 295787.t1 DIAN'
No lleva nombre ni cedula ni diagnostico: es el numero de registro profesional
degradado. Se cita porque es la ENTRADA exacta del fallo.
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
AQUI = Path(__file__).resolve().parent
sys.path.insert(0, str(_REPO))
from incapacidad_ocr.extract import RuleBasedExtractor, normalizar_fechas
from incapacidad_ocr.numeros_es import duracion_en_texto, normalizar

spec = importlib.util.spec_from_file_location("ea3", AQUI / "extract_antes.py")
ea = importlib.util.module_from_spec(spec); spec.loader.exec_module(ea)

LINEA = "Profaslonal ce -,tl 295787.t1 DIAN"
print("1) linea suelta")
print("   normalizada     :", repr(normalizar(LINEA)))
print("   duracion_en_texto:", duracion_en_texto(LINEA))

print("\n2) documento minimo con el rotulo de dias PERDIDO por el OCR (caso A10 del")
print("   inventario: pasa en 7 de los 31 textos reales)")
DOC = (
    "CERTIFICADO DE INCAPACIDAD MEDICA\n"
    "CC 1111111111 PACIENTE DE PRUEBA\n"
    "Dias de Incapacidad:\n"          # rotulo sin valor (A10)
    "Fecha Inicio: 02/09/2025\n"
    "Fecha Fin: 04/09/2025\n"
    "Registro Profaslonal ce -,tl 295787.t1 DIAN\n"
)
for etiqueta, mod in (("ANTES", ea), ("AHORA", sys.modules["incapacidad_ocr.extract"])):
    RB = ea.RuleBasedExtractor if etiqueta == "ANTES" else RuleBasedExtractor
    NF = ea.normalizar_fechas if etiqueta == "ANTES" else normalizar_fechas
    r = RB().extract(DOC); NF(r)
    inc = r["incapacidad"]
    print(f"   {etiqueta}: dias={inc['dias']} inicio={inc['fecha_inicio']} fin={inc['fecha_fin']} "
          f"letra={inc.get('dias_letra')} fin_recalc={inc.get('fecha_fin_recalculada')}")
print("   esperado: dias=3 (02/09 -> 04/09 inclusive) y fecha_fin 2025-09-04")
