"""Probe dirigida: que hace el motor cuando los tiempos SI se leen y NO cuadran.

La medicion sobre el corpus (medir.py) muestra que en muchos documentos el lector no
saca los 3 datos temporales, asi que la aritmetica nunca se llega a evaluar. Esta probe
aisla la pregunta de ingenieria: SUPONIENDO extraccion correcta, ¿el motor detecta la
incoherencia y se la explica al auxiliar?

Los tres primeros casos son TRIPLETAS REALES tomadas del texto OCR del corpus (no
inventadas): se citan la linea del documento de la que salen.
"""
from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path

# --- Rutas relativas (añadidas por scripts/exportar_analisis.py) --------------------------
# Este script se escribió con rutas ABSOLUTAS de la máquina donde se investigó. Se resuelven
# desde la ubicación del propio archivo para que funcione tras un `git pull` en cualquier
# equipo. El corpus (`dataset-falsedad/`) NO está en el repositorio: lo aporta el cliente.
import pathlib as _pl
_REPO = _pl.Path(__file__).resolve().parents[4]
_DATASET = _REPO.parent / "dataset-falsedad"
_EJEMPLOS = _REPO.parent / "Ejemplos"
# ------------------------------------------------------------------------------------------

sys.path.insert(0, str(_REPO))

from incapacidad_ocr.erp import LookupsNulos, mapear_a_staging  # noqa: E402
from incapacidad_ocr.extract import empty_record, normalizar_fechas  # noqa: E402

HOY = date(2026, 9, 2)

CASOS = [
    ("<NOMBRE> DE LA HOZ 02.09.2025 (falsa, motivo GT=FECHAS_INCOHERENTES) -- texto: "
     "'MARTES 02 ... DE SEPTIEMBRE DE 2025' / 'Duracion -DOS' / 'JUEVES 04 DE SEPT1EMBRE DE2025'",
     "2025-09-02", "2025-09-04", 2),
    ("<NOMBRE> <NOMBRE> 05062026 (falsa) -- texto: 'Dias de incapacidad:02dosdia(s)' / "
     "'Desde:05/06/2026-Hasta:06/07/2026'",
     "2026-06-05", "2026-07-06", 2),
    ("<NOMBRE> <NOMBRE> 29072026 (falsa, en cuarentena) -- texto: 'SE DA INCAPACIDAD MEDICA POR 4 "
     "DIAS DESDE EL 29-07-26 HASTA EL 01/07/29'",
     "2026-07-29", "2029-07-01", 4),
    ("control coherente (REAL-06, real)", "2026-06-09", "2026-06-10", 2),
    ("fin anterior al inicio, sin dias", "2026-06-10", "2026-06-05", None),
    ("dias = 0 (fuera de rango)", "2026-06-09", None, 0),
    ("dias = 600 (fuera de rango 1..540)", "2026-06-09", None, 600),
    ("dias = 541 con fin coherente con 541", "2026-06-09", "2027-12-02", 541),
]


def corre(ini, fin, dias):
    rec = empty_record()
    rec["tipo_documento"] = "incapacidad"
    rec["paciente"]["documento_numero"] = "1000000000"
    rec["diagnostico"]["cie10"] = "M54.5"
    rec["entidad"]["eps"] = "NUEVA EPS"
    rec["incapacidad"]["fecha_inicio"] = ini
    rec["incapacidad"]["fecha_fin"] = fin
    rec["incapacidad"]["dias"] = dias
    antes = dict(rec["incapacidad"])
    normalizar_fechas(rec)
    despues = dict(rec["incapacidad"])
    out = mapear_a_staging(
        {"fuente": "probe", "texto_plano": "", "incapacidad": rec},
        lookups=LookupsNulos(), hoy=HOY,
    )
    return antes, despues, out


def main():
    salida = []
    for titulo, ini, fin, dias in CASOS:
        antes, despues, out = corre(ini, fin, dias)
        row = out["row"]
        reg = {
            "caso": titulo,
            "leido": {"inicio": antes["fecha_inicio"], "fin": antes["fecha_fin"], "dias": antes["dias"]},
            "tras_normalizar": {"inicio": despues["fecha_inicio"], "fin": despues["fecha_fin"],
                                "dias": despues["dias"], "inicio_calculada": despues["fecha_inicio_calculada"]},
            "fin_reescrito": antes["fecha_fin"] != despues["fecha_fin"],
            "problemas": out["problemas"],
            "requiere_revision": out["requiere_revision"],
            "fila_al_auxiliar": {"fechainicio": row["fechainicio"], "Numerodias": row["Numerodias"],
                                 "fechavencimiento": row["fechavencimiento"],
                                 "problemas": row["problemas"]},
        }
        salida.append(reg)
        print("=" * 100)
        print(titulo)
        print("  leido           :", reg["leido"])
        print("  tras normalizar :", reg["tras_normalizar"], "| fin reescrito:", reg["fin_reescrito"])
        print("  problemas       :", out["problemas"] or "(ninguno)")
        print("  fila al auxiliar:", reg["fila_al_auxiliar"])
    Path(__file__).with_name("probe_tiempos.json").write_text(
        json.dumps(salida, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
