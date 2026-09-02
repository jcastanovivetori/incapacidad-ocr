"""Mide el motor de validacion temporal sobre el corpus real de 31 documentos.

NO ejecuta OCR: reutiliza los campos ya extraidos en ocr/{falsas,falsa,reales,real}/*.json
y su texto_plano. Dos pasadas por documento:

  A) "stored": el registro `incapacidad` tal como quedo guardado en el JSON del corpus
     (ya paso por normalizar_fechas cuando se genero) -> mapear_a_staging().
  B) "recalc": se vuelve a extraer desde texto_plano con el RuleBasedExtractor ACTUAL,
     capturando los valores CRUDOS (antes de normalizar_fechas) para poder distinguir
     "lo que el lector leyo" de "lo que la reconciliacion derivo/reescribio".

La pasada B es la que permite auditar de verdad los tiempos: normalizar_fechas() reescribe
fecha_fin cuando no cuadra con inicio+dias, asi que despues de ella la incoherencia YA NO
es observable.

Se degrada sin BD por diseno: se usa LookupsNulos (igual que el resto del repo).
"""
from __future__ import annotations

import csv
import json
import sys
import unicodedata
from datetime import date, timedelta
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

REPO = Path(str(_REPO))
DATASET = Path(str(_DATASET))
SALIDA = DATASET / "validacion" / "medir-corpus"

sys.path.insert(0, str(REPO))

from incapacidad_ocr.erp import LookupsNulos, mapear_a_staging  # noqa: E402
from incapacidad_ocr.extract import RuleBasedExtractor, normalizar_fechas  # noqa: E402

HOY = date(2026, 9, 2)  # fecha fija: la medicion tiene que ser reproducible

# Mensajes de `problemas` que hablan de TIEMPOS. Son los unicos que el motor actual
# sabe emitir sobre fechas/dias (ver erp.mapear_a_staging).
PROBLEMAS_TEMPORALES = (
    "No se detectó la fecha de inicio",
    "No se detectó el número de días",
    "Número de días fuera de rango",
)


def _norm_stem(s: str) -> str:
    """Normaliza para cotejar nombres entre manifest y archivos (tildes/mayusculas)."""
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    return s.upper().strip()


def indice_ocr() -> dict[str, Path]:
    idx: dict[str, Path] = {}
    for sub in ("falsas", "falsa", "reales", "real"):
        d = DATASET / "ocr" / sub
        if not d.is_dir():
            continue
        for j in d.glob("*.json"):
            idx.setdefault(_norm_stem(j.stem), j)
    return idx


def _d(s):
    try:
        return date.fromisoformat(str(s)[:10])
    except Exception:
        return None


def chequeo_referencia(fecha_inicio, fecha_fin, dias):
    """Verificacion temporal de REFERENCIA (invariantes de CLAUDE.md), independiente
    del motor: fin = inicio + dias - 1 (inclusivo); dias valido 1..540.

    Devuelve (estado, detalle) con estado in {COHERENTE, INCOHERENTE, NO_EVALUABLE}.
    """
    ini, fin = fecha_inicio, fecha_fin
    di, df = _d(ini), _d(fin)
    n = dias if isinstance(dias, int) else (int(dias) if isinstance(dias, str) and dias.strip().isdigit() else None)
    leidos = sum(1 for x in (di, df, n) if x is not None)
    if leidos < 2:
        return "NO_EVALUABLE", f"solo {leidos}/3 datos temporales leidos (inicio={ini} fin={fin} dias={dias})"
    if n is not None and not (1 <= n <= 540):
        return "INCOHERENTE", f"dias fuera de rango 1..540 (dias={n})"
    if di and df and n:
        esperado = di + timedelta(days=n - 1)
        if df != esperado:
            return "INCOHERENTE", (
                f"inicio={di} + {n} dias (inclusive) => fin esperado {esperado}, "
                f"pero el documento dice fin={df} (delta {(df - esperado).days} dias)"
            )
        return "COHERENTE", f"inicio={di} + {n} dias = fin {df}"
    if di and df and not n:
        d = (df - di).days + 1
        if d < 1:
            return "INCOHERENTE", f"fin={df} anterior a inicio={di}"
        return "COHERENTE", f"solo par inicio/fin: dias derivables = {d} (sin dias leidos que contradecir)"
    return "COHERENTE", "solo un par de datos: no hay tercer dato que pueda contradecir"


def crudos(rec: dict) -> dict:
    inca = (rec.get("incapacidad") or {}) if isinstance(rec, dict) else {}
    return {
        "fecha_inicio": inca.get("fecha_inicio"),
        "fecha_fin": inca.get("fecha_fin"),
        "dias": inca.get("dias"),
    }


def pasada(rec: dict, meta: dict) -> dict:
    resultado = {
        "fuente": meta["archivo"],
        "ocr_backend": meta.get("ocr_backend"),
        "extractor": meta.get("extractor"),
        "texto_plano": meta.get("texto_plano") or "",
        "incapacidad": rec,
    }
    try:
        out = mapear_a_staging(resultado, lookups=LookupsNulos(), hoy=HOY)
    except Exception as exc:  # el motor NUNCA deberia caerse: si cae, es hallazgo GRAVE
        return {"excepcion": f"{type(exc).__name__}: {exc}"}
    problemas = out["problemas"]
    temporales = [p for p in problemas if any(p.startswith(t) for t in PROBLEMAS_TEMPORALES)]
    row = out["row"]
    return {
        "problemas": problemas,
        "problemas_temporales": temporales,
        "requiere_revision": out["requiere_revision"],
        "fecha_inicio_calculada": out["fecha_inicio_calculada"],
        "fechainicio": row["fechainicio"],
        "Numerodias": row["Numerodias"],
        "fechavencimiento": row["fechavencimiento"],
        "confianza_ocr": row["confianza_ocr"],
    }


def main() -> None:
    idx = indice_ocr()
    gt = json.loads((DATASET / "ground_truth.json").read_text(encoding="utf-8"))
    motivos = {_norm_stem(Path(f["archivo"]).stem): f for f in gt["filas"]}

    filas = []
    with (DATASET / "manifest.csv").open(encoding="utf-8", newline="") as fh:
        for m in csv.DictReader(fh):
            stem = _norm_stem(Path(m["archivo"]).stem)
            jp = idx.get(stem)
            fila = {
                "archivo": m["archivo"],
                "etiqueta": m["etiqueta"],
                "cuarentena": m["cuarentena"],
                "motivo_cuarentena": m["motivo_cuarentena"],
                "ocr_json": str(jp) if jp else None,
                "senales_gt": (motivos.get(stem) or {}).get("senales") or [],
                "motivo_gt": (motivos.get(stem) or {}).get("motivo_texto"),
            }
            if jp is None:
                fila["error"] = "sin JSON de OCR en el corpus"
                filas.append(fila)
                continue
            d = json.loads(jp.read_text(encoding="utf-8"))
            meta = {
                "archivo": m["archivo"],
                "ocr_backend": d.get("ocr_backend"),
                "extractor": d.get("extractor"),
                "texto_plano": d.get("texto_plano") or "",
            }
            rec_stored = d.get("incapacidad") or {}
            fila["tipo_documento"] = rec_stored.get("tipo_documento")
            fila["stored_crudo"] = crudos(rec_stored)
            fila["stored"] = pasada(json.loads(json.dumps(rec_stored)), meta)

            # Pasada B: re-extraccion con el codigo ACTUAL, capturando el crudo.
            try:
                rec_new = RuleBasedExtractor().extract(meta["texto_plano"])
                fila["recalc_crudo"] = crudos(rec_new)
                fila["ref_crudo"] = chequeo_referencia(**fila["recalc_crudo"])
                rec_norm = normalizar_fechas(json.loads(json.dumps(rec_new)))
                fila["recalc_normalizado"] = crudos(rec_norm)
                fila["recalc"] = pasada(rec_norm, meta)
            except Exception as exc:
                fila["recalc_excepcion"] = f"{type(exc).__name__}: {exc}"
            fila["ref_stored"] = chequeo_referencia(**fila["stored_crudo"])
            filas.append(fila)

    (SALIDA / "resultados.json").write_text(
        json.dumps({"hoy": HOY.isoformat(), "filas": filas}, ensure_ascii=False, indent=1),
        encoding="utf-8",
    )
    print(f"documentos en manifest: {len(filas)}")
    print(f"con JSON de OCR: {sum(1 for f in filas if f.get('ocr_json'))}")
    print(f"en cuarentena: {sum(1 for f in filas if f['cuarentena'] == 'si')}")


if __name__ == "__main__":
    main()
