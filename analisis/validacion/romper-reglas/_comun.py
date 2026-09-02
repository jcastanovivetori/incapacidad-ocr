"""Andamiaje comun de los ataques al motor de reglas de tiempos.

Solo LECTURA del paquete: aqui no se importa nada que escriba en BD ni en disco del
repo. `REGLAS_TIEMPO_CONFIG` se apunta a un archivo inexistente para que
`cargar_config()` no lea por accidente el JSON de la maquina y contamine los ataques.
"""
from __future__ import annotations

import os
import sys
from datetime import date
from pathlib import Path
from typing import Any

# --- Rutas relativas (añadidas por scripts/exportar_analisis.py) --------------------------
# Este script se escribió con rutas ABSOLUTAS de la máquina donde se investigó. Se resuelven
# desde la ubicación del propio archivo para que funcione tras un `git pull` en cualquier
# equipo. El corpus (`dataset-falsedad/`) NO está en el repositorio: lo aporta el cliente.
import pathlib as _pl
_REPO = _pl.Path(__file__).resolve().parents[3]
_DATASET = _REPO.parent / "dataset-falsedad"
_EJEMPLOS = _REPO.parent / "Ejemplos"
# ------------------------------------------------------------------------------------------

RAIZ = Path(str(_REPO))
sys.path.insert(0, str(RAIZ))
try:  # consola Windows (cp1252): los mensajes del motor traen acentos y flechas
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # noqa: BLE001
    pass
os.environ["REGLAS_TIEMPO_CONFIG"] = str(Path(__file__).parent / "_no_existe.json")

from incapacidad_ocr import erp, reglas_tiempo as rt          # noqa: E402
from incapacidad_ocr import validacion_temporal as vt         # noqa: E402

HOY = date(2026, 9, 2)

_fallos: list[str] = []
_total = 0


def ok(nombre: str, cond: bool, detalle: str = "") -> bool:
    """PASS = el motor se comporto como se esperaba. FAIL = hallazgo."""
    global _total
    _total += 1
    bien = bool(cond)
    if not bien:
        _fallos.append(nombre + (f"  ->  {detalle}" if detalle else ""))
    print(("  ok   " if bien else "  FALLA ") + nombre + (f"  ->  {detalle}" if detalle else ""))
    return bien


def titulo(t: str) -> None:
    print("\n" + "=" * 78 + "\n" + t + "\n" + "=" * 78)


def cierre() -> int:
    print("\n" + "-" * 78)
    print(f"comprobaciones: {_total}   fallas: {len(_fallos)}")
    for f in _fallos:
        print("  FALLA:", f)
    return 1 if _fallos else 0


# --------------------------------------------------------------------------- #
# Contextos
# --------------------------------------------------------------------------- #
def ctx_foto(*, inicio=None, fin=None, dias=None, dias_letra=None, hoy=HOY,
             overrides=None, **marcas) -> rt.ContextoTiempos:
    """Camino de PRODUCCION: la foto que deja `processor` antes de reconciliar."""
    inca: dict[str, Any] = {rt.CLAVE_SNAPSHOT: {"fecha_inicio": inicio, "fecha_fin": fin,
                                                "dias": dias, "dias_letra": dias_letra}}
    inca.update(marcas)
    return rt.construir_contexto(inca, hoy=hoy, overrides=overrides)


def ctx_sin_foto(inca: dict, *, hoy=HOY, overrides=None) -> rt.ContextoTiempos:
    """Registro que NO paso por `processor` (sin foto): se deduce de las marcas."""
    return rt.construir_contexto(inca, hoy=hoy, overrides=overrides)


def estado(ctx, codigo: str, cfg=None) -> str:
    return regla(ctx, codigo, cfg).estado


def regla(ctx, codigo: str, cfg=None) -> rt.ResultadoRegla:
    for r in rt.evaluar_reglas(ctx, cfg):
        if r.codigo == codigo:
            return r
    raise AssertionError(f"{codigo} no esta en el catalogo")


def estados(ctx, cfg=None) -> dict[str, str]:
    return {r.codigo: r.estado for r in rt.evaluar_reglas(ctx, cfg)}


def disparadas(ctx, cfg=None) -> list[str]:
    return [r.codigo for r in rt.evaluar_reglas(ctx, cfg) if r.estado == rt.NO_CUMPLE]


# --------------------------------------------------------------------------- #
# Lookups que SI resuelven (aisla el canal de tiempos en erp, sin MySQL)
# --------------------------------------------------------------------------- #
class LookupsFalsos(erp.LookupsNulos):
    def empleado_por_cedula(self, cedula):
        return (7, "PACIENTE DE PRUEBA", "SALUD TOTAL") if cedula else (None, None, None)

    def id_empleado_por_cedula(self, cedula):
        return self.empleado_por_cedula(cedula)[0]

    def diagnostico_por_codigo(self, codigo):
        return (11, "INFECCION AGUDA") if codigo else (None, None)

    def id_entidad_por_nombre(self, nombre):
        return (3, 1, "SALUD TOTAL") if nombre else (None, None, None)


def resultado_process(inca: dict, **extra) -> dict:
    registro = {
        "tipo_documento": "incapacidad",
        "paciente": {"nombre": "PACIENTE DE PRUEBA", "documento_numero": "13742111"},
        "entidad": {"eps": "SALUD TOTAL"},
        "diagnostico": {"cie10": "J06.9"},
        "incapacidad": inca,
    }
    registro.update(extra)
    return {"fuente": "documento_de_prueba.pdf", "ocr_backend": "stub", "extractor": "rule",
            "incapacidad": registro}
