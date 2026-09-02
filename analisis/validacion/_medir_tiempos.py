"""Medicion de la señal TEMPORAL sobre el corpus ya OCR-eado (no vuelve a correr OCR).

Por que existe este script: los JSON de `ocr/**` se generaron con `IncapacidadProcessor.run()`,
que YA aplica `extract.normalizar_fechas()`. Esa funcion **sobrescribe** la fecha fin leida
cuando no cuadra con inicio+dias, y **rellena** dias por diferencia de fechas cuando no hay
rotulo. Es decir: los JSON borran exactamente la evidencia que queremos medir.

Aqui se reconstruye la PROCEDENCIA de cada dato (leido del documento vs derivado) llamando a
los mismos helpers del extractor sobre el `.txt` guardado, sin normalizar. Asi se puede medir
la regla estrella (inicio/fin/dias impresos que se contradicen) sin falsos positivos por
valores que el propio pipeline calculo.

Uso:  .venv/Scripts/python.exe validacion/_medir_tiempos.py
"""
from __future__ import annotations

import csv
import json
import sys
from datetime import date
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]           # dataset-falsedad/
REPO = RAIZ.parent / "incapacidad-ocr"
sys.path.insert(0, str(REPO))

from incapacidad_ocr.extract import (  # noqa: E402
    _fecha_inicio_fin_escrita,
    _find_date,
    _first,
    _extraer_detalle_incapacidad,
    _safe_date,
)

CARPETAS = {"falsa": ("falsas", "falsa"), "real": ("reales", "real")}


def buscar_txt(etiqueta: str, archivo: str) -> Path | None:
    """El corpus se extrajo en shards: hay carpetas plural y singular por clase."""
    stem = Path(archivo).stem
    for sub in CARPETAS[etiqueta]:
        p = RAIZ / "ocr" / sub / f"{stem}.txt"
        if p.exists():
            return p
    return None


def leidos_crudos(t: str) -> dict:
    """Valores LEIDOS del texto, con procedencia explicita (sin ninguna derivacion).

    Replica los anclajes de `RuleBasedExtractor.extract` pero SIN los respaldos que
    calculan: no se completa inicio desde fin-dias, ni dias desde la diferencia de
    fechas. Lo que sale de aqui es "lo que el documento imprime".

    LIMITE CONOCIDO: no replica `extract._extraer_permiso` (lee las fechas del bloque
    "3. DURACION DEL PERMISO" por POSICION y tolera el D/M/A partido en celdas, "06 06 26").
    Los permisos salen aqui sin fechas leidas aunque las tengan. No afecta a la medicion
    de la regla estrella: ningun permiso imprime un numero de dias (se deriva siempre por
    diferencia, igual que en vacaciones), asi que nunca entra en "los tres leidos".
    """
    fi = _find_date(
        t, r"(?:fecha\s*(?:de\s*)?[il]nic\w?(?:o|al|a)|[il]nic\w?(?:o|al|a)\s*incapacidad|"
           r"fecha\s*de\s*emisi[oó]n|desde)"
    )
    ff = _find_date(t, r"(?:fecha\s*(?:de\s*)?(?:termina|final|fin)|"
                       r"(?:final|fin|termina\w*)\s*incapacidad|hasta)")
    origen_fi = "rotulo" if fi else None
    origen_ff = "rotulo" if ff else None
    # Respaldo de fechas ESCRITAS en español ("MARTES 02 DE SEPTIEMBRE DE 2025"): sigue
    # siendo un dato LEIDO (esta impreso), solo con otro patron.
    if not fi or not ff:
        fi_esc, ff_esc = _fecha_inicio_fin_escrita(t)
        if not fi and fi_esc:
            fi, origen_fi = fi_esc, "escrita"
        if not ff and ff_esc:
            ff, origen_ff = ff_esc, "escrita"
    # Dias: SOLO los patrones con rotulo. `dias_calc` (diferencia de fechas) se excluye
    # a proposito: es el valor derivado que hundiria la regla con falsos positivos.
    d = _first(t, r"(?i)duraci[oó]n\b[^\d]{0,10}(\d{1,3})")
    origen_d = "duracion" if d else None
    if not d:
        d = _first(t, r"(?i)d[ií]as?(?:\s*de\s*incapacidad)?\b[^\d\n]{0,15}(\d{1,3})")
        origen_d = "dias_label" if d else None
    if not d:
        d = _first(t, r"(?i)(\d{1,3})\s*[\(\-]?\s*(?:un|dos|tres|cuatro|cinco|"
                      r"seis|siete|ocho|nueve|diez|quince|veinte|treinta)\w*\s*d[ií]as?")
        origen_d = "num_mas_letra" if d else None
    dias = int(d) if d and str(d).isdigit() else None
    # La tabla "DETALLE DE LA INCAPACIDAD" es un anclaje de columnas: sus 3 valores son
    # todos LEIDOS y mandan sobre las heuristicas genericas (igual que en el extractor).
    det = _extraer_detalle_incapacidad(t)
    if det:
        if det.get("fecha_inicio"):
            fi, origen_fi = det["fecha_inicio"], "detalle_tabla"
        if det.get("fecha_fin"):
            ff, origen_ff = det["fecha_fin"], "detalle_tabla"
        if det.get("dias"):
            dias, origen_d = det["dias"], "detalle_tabla"
    exp = _find_date(t, r"expedici[oó]n")
    return {"fecha_inicio": fi, "origen_fi": origen_fi,
            "fecha_fin": ff, "origen_ff": origen_ff,
            "dias": dias, "origen_dias": origen_d,
            "fecha_expedicion": exp}


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    filas = list(csv.DictReader((RAIZ / "manifest.csv").open(encoding="utf-8")))
    hoy = date(2026, 9, 2)

    reporte = []
    for f in filas:
        etiqueta, archivo = f["etiqueta"], f["archivo"]
        txt = buscar_txt(etiqueta, archivo)
        fila = {
            "archivo": archivo, "etiqueta": etiqueta,
            "cuarentena": f.get("cuarentena") == "si",
            "tiene_texto": txt is not None,
        }
        if txt:
            t = txt.read_text(encoding="utf-8")
            fila["chars_ocr"] = len(t.strip())
            fila.update(leidos_crudos(t))
            di, df = _safe_date(fila["fecha_inicio"]), _safe_date(fila["fecha_fin"])
            n = fila["dias"]
            fila["tres_leidos"] = bool(di and df and n)
            fila["dias_por_fechas"] = (df - di).days + 1 if (di and df) else None
            fila["coherente"] = (fila["dias_por_fechas"] == n) if fila["tres_leidos"] else None
            fila["desfase"] = (n - fila["dias_por_fechas"]) if fila["tres_leidos"] else None
            fila["orden_ok"] = (di <= df) if (di and df) else None
            fila["dias_en_rango"] = (1 <= n <= 540) if n else None
            de = _safe_date(fila["fecha_expedicion"])
            fila["exp_vs_inicio_dias"] = (di - de).days if (di and de) else None
            fila["inicio_vs_hoy_dias"] = (hoy - di).days if di else None
        reporte.append(fila)

    limpio = [r for r in reporte if not r["cuarentena"]]

    def bloque(nombre, rs):
        con_txt = [r for r in rs if r["tiene_texto"]]
        tres = [r for r in con_txt if r.get("tres_leidos")]
        incoh = [r for r in tres if r.get("coherente") is False]
        return {
            "clase": nombre, "docs": len(rs), "con_texto_ocr": len(con_txt),
            "fi_leida": sum(1 for r in con_txt if r.get("fecha_inicio")),
            "ff_leida": sum(1 for r in con_txt if r.get("fecha_fin")),
            "dias_leidos": sum(1 for r in con_txt if r.get("dias")),
            "exp_leida": sum(1 for r in con_txt if r.get("fecha_expedicion")),
            "TRES_LEIDOS": len(tres),
            "TRES_LEIDOS_INCOHERENTES": len(incoh),
            "incoherentes_detalle": [
                {"archivo": r["archivo"], "ini": r["fecha_inicio"], "fin": r["fecha_fin"],
                 "dias_impresos": r["dias"], "dias_por_fechas": r["dias_por_fechas"],
                 "desfase": r["desfase"], "origen": [r["origen_fi"], r["origen_ff"], r["origen_dias"]]}
                for r in incoh],
            "orden_invertido": [r["archivo"] for r in con_txt if r.get("orden_ok") is False],
            "dias_fuera_rango": [(r["archivo"], r["dias"]) for r in con_txt
                                 if r.get("dias_en_rango") is False],
            "exp_posterior_al_inicio": [(r["archivo"], r["exp_vs_inicio_dias"]) for r in con_txt
                                        if (r.get("exp_vs_inicio_dias") or 0) < 0],
            "antiguedad_dias": sorted(r["inicio_vs_hoy_dias"] for r in con_txt
                                      if r.get("inicio_vs_hoy_dias") is not None),
        }

    out = {
        "corpus_total": len(reporte),
        "en_cuarentena_excluidos": [r["archivo"] for r in reporte if r["cuarentena"]],
        "corpus_limpio": len(limpio),
        "falsas": bloque("falsa", [r for r in limpio if r["etiqueta"] == "falsa"]),
        "reales": bloque("real", [r for r in limpio if r["etiqueta"] == "real"]),
        "por_documento": [
            {k: v for k, v in r.items() if k != "chars_ocr"} for r in reporte
        ],
    }
    (RAIZ / "validacion" / "medicion_tiempos.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    resumen = {k: v for k, v in out.items() if k != "por_documento"}
    print(json.dumps(resumen, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
