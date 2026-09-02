#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Demostración EJECUTABLE de los huecos de validación temporal del pipeline actual.

No es una prueba de regresión: es la evidencia que acompaña a `01_inventario.md`.
Cada caso es TEXTO SINTÉTICO (sin PII: cédula/nombre de `sql/init.sql`) que se pasa por
el camino real de producción — `RuleBasedExtractor` → `normalizar_fechas()` →
`erp.mapear_a_staging()` — y se imprime QUÉ leyó, QUÉ quedó en la fila de staging y
QUÉ dijo el sistema en `problemas`.

La pregunta que responde cada caso es siempre la misma: *cuando los datos del papel se
contradicen, ¿el sistema lo DICE, o lo arregla en silencio?*

`FakeLookups` resuelve todos los catálogos a propósito: sin él, `problemas` se llena de
"cédula no encontrada"/"EPS no identificada" (ruido de BD) y no se ve que NINGÚN problema
habla de los tiempos. Es el equivalente "sin BD" de `LookupsNulos`, pero al revés.

    <repo>/.venv/Scripts/python.exe 00_demo_huecos.py
"""
from __future__ import annotations

import sys
from datetime import date

# --- Rutas relativas (añadidas por scripts/exportar_analisis.py) --------------------------
# Este script se escribió con rutas ABSOLUTAS de la máquina donde se investigó. Se resuelven
# desde la ubicación del propio archivo para que funcione tras un `git pull` en cualquier
# equipo. El corpus (`dataset-falsedad/`) NO está en el repositorio: lo aporta el cliente.
import pathlib as _pl
_REPO = _pl.Path(__file__).resolve().parents[2]
_DATASET = _REPO.parent / "dataset-falsedad"
_EJEMPLOS = _REPO.parent / "Ejemplos"
# ------------------------------------------------------------------------------------------

REPO = str(_REPO)
if REPO not in sys.path:
    sys.path.insert(0, REPO)

try:  # consola Windows (cp1252) → forzar UTF-8 para acentos (igual que tests/ del repo)
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # noqa: BLE001
    pass

from incapacidad_ocr import erp                                   # noqa: E402
from incapacidad_ocr.extract import RuleBasedExtractor, normalizar_fechas  # noqa: E402

HOY = date(2026, 9, 2)


class FakeLookups:
    """Catálogos que SIEMPRE resuelven → `problemas` queda limpio de ruido de BD."""

    def empleado_por_cedula(self, cedula):
        return (1, "<NOMBRE> PEREZ GOMEZ", "SALUD MIA") if cedula else (None, None, None)

    def empleado_por_nombre(self, nombre):  # noqa: ARG002
        return None, None, None

    def id_empleado_por_cedula(self, cedula):
        return self.empleado_por_cedula(cedula)[0]

    def diagnostico_por_codigo(self, codigo):
        return (8, "INFECCION AGUDA DE LAS VIAS RESPIRATORIAS SUPERIORES") if codigo else (None, None)

    def id_entidad_por_nombre(self, nombre):
        return (5, 1, "SALUD MIA") if nombre else (None, None, None)

    def documentos_requeridos(self, id_entidad, id_tipo):  # noqa: ARG002
        return []


ENCABEZADO = (
    "CERTIFICADO DE INCAPACIDAD MEDICA\n"
    "Paciente: <NOMBRE> PEREZ GOMEZ\n"
    "CC 1098765432\n"
    "Entidad: SALUD MIA\n"
    "Diagnostico principal: J06.9 INFECCION AGUDA DE VIAS RESPIRATORIAS\n"
)

CASOS = [
    (
        "A. TRIPLETA IMPRESA CONTRADICTORIA (el hueco central)",
        "El papel trae los TRES datos: inicio 05/06, fin 06/07 y 2 días. 05/06→06/07 son 32 "
        "días, no 2. Uno de los tres está adulterado o mal leído.",
        ENCABEZADO + "Fecha Inicio: 05/06/2026\nFecha Terminacion: 06/07/2026\nDias de incapacidad: 2\n",
    ),
    (
        "B. DÍAS IMPRESOS FUERA DE RANGO, pero con las dos fechas",
        "El papel dice 900 días (imposible: el tope legal del repo es 540) y además trae "
        "inicio y fin que dan 5 días.",
        ENCABEZADO + "Fecha Inicio: 01/06/2026\nFecha Terminacion: 05/06/2026\nDias de incapacidad: 900\n",
    ),
    (
        "C. RANGO INVERTIDO (fin ANTES del inicio), sin días impresos",
        "El papel dice que la incapacidad empieza el 20/06 y termina el 10/06.",
        ENCABEZADO + "Fecha Inicio: 20/06/2026\nFecha Terminacion: 10/06/2026\n",
    ),
    (
        "D. EXPEDIDA DESPUÉS DE HABER TERMINADO",
        "La incapacidad cubre 05/06-06/06 pero el certificado se expidió el 20/07, seis "
        "semanas después de terminar.",
        ENCABEZADO + "Fecha de Expedicion: 20/07/2026\nFecha Inicio: 05/06/2026\n"
        "Fecha Terminacion: 06/06/2026\nDias de incapacidad: 2\n",
    ),
    (
        "E. FECHA DE INICIO EN EL FUTURO LEJANO",
        "El papel fecha el inicio en 2027 (hoy es 2026-09-02): 4 meses hacia adelante.",
        ENCABEZADO + "Fecha Inicio: 05/01/2027\nFecha Terminacion: 06/01/2027\nDias de incapacidad: 2\n",
    ),
]


def corre(titulo: str, porque: str, texto: str) -> None:
    print("=" * 100)
    print(titulo)
    print("-" * 100)
    print("  el papel dice   :", porque)
    rec = RuleBasedExtractor().extract(texto)
    leido = dict(rec["incapacidad"])  # ANTES de reconciliar (lo que el extractor leyó)
    normalizar_fechas(rec)
    tras = rec["incapacidad"]
    mapeo = erp.mapear_a_staging({"incapacidad": rec}, "WHATSAPP", FakeLookups(), hoy=HOY)
    row = mapeo["row"]
    print(f"  extractor LEE   : inicio={leido.get('fecha_inicio')} fin={leido.get('fecha_fin')} "
          f"dias={leido.get('dias')} expedicion={leido.get('fecha_expedicion')}")
    print(f"  normalizar_fechas DEJA: inicio={tras.get('fecha_inicio')} fin={tras.get('fecha_fin')} "
          f"dias={tras.get('dias')} calculada={tras.get('fecha_inicio_calculada')}")
    print(f"  fila staging    : fechainicio={row['fechainicio']} Numerodias={row['Numerodias']} "
          f"fechavencimiento={row['fechavencimiento']}")
    print(f"  (la fila NO tiene columna fecha_fin: el fin impreso no se persiste en ningún sitio)")
    print(f"  problemas       : {mapeo['problemas'] or '[] (ninguno)'}")
    print(f"  requiere_revision: {mapeo['requiere_revision']}   confianza_ocr: {row['confianza_ocr']}")
    print()


def main() -> int:
    print("DEMOSTRACIÓN — qué hace HOY el pipeline cuando los tiempos NO cuadran")
    print("(camino real: RuleBasedExtractor → normalizar_fechas → erp.mapear_a_staging)\n")
    for titulo, porque, texto in CASOS:
        corre(titulo, porque, texto)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
