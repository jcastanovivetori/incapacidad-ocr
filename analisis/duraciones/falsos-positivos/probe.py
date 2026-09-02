"""Sonda rapida: pasa un texto por el modulo y por el extractor completo."""
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

sys.path.insert(0, str(_REPO))

from incapacidad_ocr.extract import (  # noqa: E402
    RuleBasedExtractor, _dias_por_etiqueta, es_formato_permiso, es_formato_vacaciones,
    normalizar_fechas,
)
from incapacidad_ocr.numeros_es import duracion_en_texto, normalizar, numerales_en_texto  # noqa: E402


def probe(nombre: str, texto: str) -> None:
    dur = duracion_en_texto(texto)
    etq = _dias_por_etiqueta(texto)
    rec = normalizar_fechas(RuleBasedExtractor().extract(texto))
    inc = rec["incapacidad"]
    print(f"--- {nombre}")
    print(f"    modulo      : {dur}")
    print(f"    _dias_por_et: {etq}")
    print(f"    tipo        : {rec['tipo_documento']}  (perm={es_formato_permiso(texto)} "
          f"vac={es_formato_vacaciones(texto)})")
    print(f"    dias={inc['dias']} letra={inc['dias_letra']} coin={inc['dias_letra_coincide']} "
          f"ini={inc['fecha_inicio']} fin={inc['fecha_fin']}")


if __name__ == "__main__":
    for arg in sys.argv[1:]:
        p = Path(arg)
        probe(p.name, p.read_text(encoding="utf-8", errors="replace"))
