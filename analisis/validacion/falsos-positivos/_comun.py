"""Utilidades compartidas de la caza de falsos positivos (100% local, sin OCR).

Por qué existe: los JSON de `dataset-falsedad/ocr/*` NO traen la foto
`reglas_tiempo.CLAVE_SNAPSHOT` (se produjeron antes de que `processor` la guardara), así
que evaluar el motor sobre ellos tal cual mediría un pipeline que ya no existe. Aquí se
REPLICA lo que hace `processor.run()` a partir del `texto_plano` ya OCR-eado:
extractor de reglas -> foto -> `normalizar_fechas()`. Sin OCR: la medición de rendimiento
que corre en esta máquina no se toca.

PII (Ley 1581): los documentos se citan por su ID del corpus (R01..R16) + los 8 primeros
del sha256, nunca por nombre de paciente. El nombre de ARCHIVO sí se muestra porque el
informe del repo lo usa como referencia técnica.
"""
from __future__ import annotations

import csv
import json
import sys
from datetime import date
from pathlib import Path
from typing import Any, Optional

# --- Rutas relativas (añadidas por scripts/exportar_analisis.py) --------------------------
# Este script se escribió con rutas ABSOLUTAS de la máquina donde se investigó. Se resuelven
# desde la ubicación del propio archivo para que funcione tras un `git pull` en cualquier
# equipo. El corpus (`dataset-falsedad/`) NO está en el repositorio: lo aporta el cliente.
import pathlib as _pl
_REPO = _pl.Path(__file__).resolve().parents[3]
_DATASET = _REPO.parent / "dataset-falsedad"
_EJEMPLOS = _REPO.parent / "Ejemplos"
# ------------------------------------------------------------------------------------------

RAIZ_DATASET = Path(str(_DATASET))
RAIZ_REPO = Path(str(_REPO))
if str(RAIZ_REPO) not in sys.path:
    sys.path.insert(0, str(RAIZ_REPO))

from incapacidad_ocr import reglas_tiempo  # noqa: E402
from incapacidad_ocr.extract import RuleBasedExtractor, normalizar_fechas  # noqa: E402

# Carpetas donde quedó el OCR ya extraído (dos tandas: `reales/` y `real/`).
CARPETAS_REALES = (RAIZ_DATASET / "ocr" / "reales", RAIZ_DATASET / "ocr" / "real")
CARPETAS_FALSAS = (RAIZ_DATASET / "ocr" / "falsas", RAIZ_DATASET / "ocr" / "falsa")


def _manifest() -> list[dict[str, str]]:
    with (RAIZ_DATASET / "manifest.csv").open(encoding="utf-8", errors="replace") as fh:
        return list(csv.DictReader(fh))


def ids_corpus() -> dict[str, dict[str, Any]]:
    """sha256 -> {id, etiqueta, cuarentena}. Los IDs se numeran POR CLASE desde 1, igual
    que `senales/aritmetica_fechas/INFORME.md` (para poder citar sus hallazgos)."""
    salida: dict[str, dict[str, Any]] = {}
    contador = {"real": 0, "falsa": 0}
    for fila in _manifest():
        et = fila["etiqueta"]
        contador[et] = contador.get(et, 0) + 1
        pre = "R" if et == "real" else "F"
        salida[fila["sha256"]] = {
            "id": f"{pre}{contador[et]:02d}",
            "etiqueta": et,
            "cuarentena": fila.get("cuarentena") == "si",
            "motivo_cuarentena": fila.get("motivo_cuarentena") or "",
            "archivo": fila["archivo"],
        }
    return salida


def cargar_docs(carpetas=CARPETAS_REALES) -> list[dict[str, Any]]:
    """Documentos del corpus con su texto OCR ya extraído, ordenados por ID."""
    idx = ids_corpus()
    docs: list[dict[str, Any]] = []
    for carpeta in carpetas:
        for ruta in sorted(carpeta.glob("*.json")):
            d = json.loads(ruta.read_text(encoding="utf-8"))
            sha = ((d.get("estructura") or {}).get("sha256_archivo")) or ""
            meta = idx.get(sha, {})
            docs.append({
                "ruta_json": ruta,
                "archivo": d.get("archivo") or ruta.stem,
                "sha8": sha[:8],
                "id": meta.get("id", "??"),
                "etiqueta": d.get("etiqueta"),
                "cuarentena": meta.get("cuarentena", False),
                "texto_plano": d.get("texto_plano") or "",
                # registro tal como quedó guardado en el dataset (para detectar deriva)
                "registro_dataset": d.get("incapacidad") or {},
            })
    docs.sort(key=lambda x: (x["id"], x["archivo"]))
    return docs


def registro_como_processor(texto: str) -> dict[str, Any]:
    """Reproduce `IncapacidadProcessor.run()` desde el texto OCR ya extraído.

    Mismo orden que processor.py:56-57 (foto ANTES de reconciliar) para que el motor vea
    la evidencia que vería en producción.
    """
    rec = RuleBasedExtractor().extract(texto)
    inca = rec.get("incapacidad")
    if isinstance(inca, dict):
        inca[reglas_tiempo.CLAVE_SNAPSHOT] = reglas_tiempo.snapshot_leidos(inca)
    normalizar_fechas(rec)
    return rec


def evaluar_doc(rec: dict[str, Any], hoy: date,
                config: Optional[reglas_tiempo.ConfigReglas] = None) -> dict[str, Any]:
    inca = rec.get("incapacidad") or {}
    ctx = reglas_tiempo.construir_contexto(
        inca, hoy=hoy,
        inicio_efectivo=inca.get("fecha_inicio"), fin_efectivo=inca.get("fecha_fin"),
        dias_efectivo=reglas_tiempo.entero_dias(inca.get("dias")),
        tipo_documento=rec.get("tipo_documento"),
    )
    cfg = config or reglas_tiempo.config_por_defecto()
    ver = reglas_tiempo.evaluar(ctx, cfg)
    return {"ctx": ctx, "veredicto": ver,
            "informe": reglas_tiempo.validar_tiempos(ctx, cfg, ver)}


def fecha_proceso(rec: dict[str, Any], por_defecto: date = date(2026, 9, 2)) -> date:
    """`hoy` plausible: el documento se radica pocos días después de empezar.

    Se usa para NO castigar al corpus por el simple hecho de que se procese meses
    después (T09/T10 se miden contra `hoy`). Si el documento no trae fecha, se usa la de
    corte del corpus.
    """
    inca = rec.get("incapacidad") or {}
    f = reglas_tiempo.fecha_iso(inca.get("fecha_inicio")) or reglas_tiempo.fecha_iso(inca.get("fecha_fin"))
    if f is None:
        return por_defecto
    from datetime import timedelta
    return f + timedelta(days=3)
