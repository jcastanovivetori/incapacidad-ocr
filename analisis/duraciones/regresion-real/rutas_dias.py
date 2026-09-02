# -*- coding: utf-8 -*-
"""De DONDE sale 'dias' antes y ahora: rotulo viejo / modulo nuevo / respaldo / fechas.

Objetivo: detectar los casos donde el valor final coincide por CASUALIDAD porque la
diferencia de fechas tapa que el lector por rotulo dejo de leer (regresion latente:
si el documento no trajera fechas, el dato se perderia).
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
from incapacidad_ocr.extract import (RuleBasedExtractor, _NUM_DIAS, _days_between,
                                     _first, normalizar_fechas)
from incapacidad_ocr.numeros_es import duracion_en_texto

# los TRES patrones historicos, tal como estaban ANTES del cambio (sin guardarrail)
def viejo(t):
    d = _first(t, r"(?i)duraci[oó]n\b[^\d]{0,10}(\d{1,3})")
    if d: return int(d), "P1 duracion"
    d = _first(t, r"(?i)d[ií]as?(?:\s*de\s*incapacidad)?\b[^\d\n]{0,15}(\d{1,3})")
    if d: return int(d), "P2 dias"
    d = _first(t, r"(?i)(\d{1,3})\s*[\(\-]?\s*(?:un|dos|tres|cuatro|cinco|"
                  r"seis|siete|ocho|nueve|diez|quince|veinte|treinta)\w*\s*d[ií]as?")
    if d: return int(d), "P3 num+palabra"
    return None, "-"

def nuevo_respaldo(t):
    d = _first(t, rf"(?i)duraci[oó]n\b[^\d]{{0,10}}{_NUM_DIAS}")
    if d: return int(d), "R1 duracion"
    d = _first(t, rf"(?i)d[ií]as?(?:\s*de\s*incapacidad)?\b[^\d\n]{{0,15}}{_NUM_DIAS}")
    if d: return int(d), "R2 dias"
    return None, "-"

print(f"{'documento':52s} {'viejo':>6s} {'via':14s} {'modulo':>6s} {'respald':>7s} "
      f"{'fechas':>6s} {'FINAL':>6s}  riesgo")
for sub in ("falsas", "falsa", "reales", "real"):
    for p in sorted((BASE / "ocr" / sub).glob("*.txt")):
        t = p.read_text(encoding="utf-8")
        v, via = viejo(t)
        dur = duracion_en_texto(t)
        m = dur["valor"] if dur else None
        r, _via_r = (nuevo_respaldo(t) if dur is None else (None, "-"))
        rec = RuleBasedExtractor().extract(t); normalizar_fechas(rec)
        inc = rec["incapacidad"]
        fechas = _days_between(inc.get("fecha_inicio"), inc.get("fecha_fin"))
        final = inc.get("dias")
        # riesgo: el rotulo viejo leia algo, el modulo no, y el valor final solo se
        # sostiene por la diferencia de fechas
        riesgo = ""
        if v is not None and m is None:
            riesgo = "rotulo perdido; final se sostiene por FECHAS" if r is None else "cubierto por respaldo"
        print(f"{f'{sub}/{p.stem}'[:52]:52s} {str(v):>6s} {via:14s} {str(m):>6s} {str(r):>7s} "
              f"{str(fechas):>6s} {str(final):>6s}  {riesgo}")
