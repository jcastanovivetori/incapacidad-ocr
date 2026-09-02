"""Impacto end-to-end del truncamiento: de la lectura mal leida a la fila staging.

Muestra que un numeral en letras RECORTADO (H1) produce un valor MENOR, en rango
valido, que la reconciliacion de fechas convierte en 'coherente' -> erp NO lo
marca como problema. El unico rastro es `fecha_fin_recalculada`, que la UI no pinta.
"""
from __future__ import annotations

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

REPO = Path(str(_REPO))
sys.path.insert(0, str(REPO))
sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]

from incapacidad_ocr import erp  # noqa: E402
from incapacidad_ocr.extract import RuleBasedExtractor  # noqa: E402

EX = RuleBasedExtractor()

DOCS = {
    # 255 dias reales (01/09/2026 -> 13/05/2027). El rotulo trae el numeral en LETRAS.
    "letras largas (255) + fechas coherentes": (
        "INCAPACIDAD MEDICA\n"
        "Fecha Inicial: 01/09/2026\n"
        "Fecha Final: 13/05/2027\n"
        "Dias de incapacidad: DOSCIENTOS CINCUENTA Y CINCO\n"
        "Diagnostico: A09\n"
        "Cedula: 1\n", 255),
    # 35 dias, rotulo con una palabra extra ('otorgados' cabe, 'del periodo' no).
    "rotulo con palabra extra (35)": (
        "INCAPACIDAD MEDICA\n"
        "Fecha Inicial: 01/09/2026\n"
        "Fecha Final: 05/10/2026\n"
        "Duracion del periodo: TREINTA Y CINCO\n"
        "Diagnostico: A09\n", 35),
    # 180 dias: 'ciento' cabe, 'ochenta' no -> 100.
    "rotulo con palabra extra (180)": (
        "INCAPACIDAD MEDICA\n"
        "Fecha Inicial: 01/09/2026\n"
        "Fecha Final: 27/02/2027\n"
        "Dias de incapacidad autorizados: CIENTO OCHENTA\n"
        "Diagnostico: A09\n", 180),
}

for nombre, (texto, esperado) in DOCS.items():
    rec = EX.extract(texto)
    inc = rec["incapacidad"]
    fila = erp.mapear_a_staging({"incapacidad": rec})
    tiempos = [p for p in (fila.get("problemas") or []) if "día" in p or "dia" in p]
    print(f"\n=== {nombre}")
    print(f"  dias esperados      : {esperado}")
    print(f"  dias leidos         : {inc['dias']}   (dias_letra={inc['dias_letra']})")
    print(f"  fecha_inicio/fin    : {inc['fecha_inicio']} -> {inc['fecha_fin']}")
    print(f"  fecha_fin_recalculada: {inc.get('fecha_fin_recalculada')}")
    print(f"  Numerodias (staging): {fila.get('Numerodias')}")
    print(f"  problemas de tiempos: {tiempos or 'NINGUNO'}")
