"""Barrido 2 — ¿el `dias_leido` que juzga el motor es EVIDENCIA o un valor DERIVADO?

Motivo. `RuleBasedExtractor` cierra el bloque de días con
    rec["incapacidad"]["dias"] = dias_val if dias_val is not None else dias_calc
(extract.py:930, y en el PERMISO directamente `_days_between`, extract.py:760), donde
`dias_calc = _days_between(inicio, fin)` es la DIFERENCIA DE LAS DOS FECHAS. `processor`
toma la foto DESPUÉS de eso (processor.py:56), así que `snapshot['dias']` puede ser un
valor calculado que el motor tratará como "el número de días impreso en el documento".

Esto no produce un falso positivo de T01 (calculado de las fechas, cuadra con ellas por
construcción) — produce lo contrario: un **CUMPLE tautológico** que sube la `cobertura`
del informe y hace leer un COHERENTE como "documento verificado".

Aquí se mide, documento por documento, de dónde salió el número de días.
"""
from __future__ import annotations

import json
from pathlib import Path

from _comun import cargar_docs, registro_como_processor, reglas_tiempo

import incapacidad_ocr.extract as ex

AQUI = Path(__file__).resolve().parent


def main() -> None:
    filas = []
    for grupo, docs in (("real", cargar_docs()),):
        for doc in docs:
            t = doc["texto_plano"]
            rec = registro_como_processor(t)
            inca = rec.get("incapacidad") or {}
            snap = inca.get(reglas_tiempo.CLAVE_SNAPSHOT) or {}
            # Lo que el lector de duraciones sacó del PAPEL (por rótulo/unidad/letra).
            dias_etiqueta, letra, coincide = ex._dias_por_etiqueta(t)
            # Lo que sale de la resta de las dos fechas.
            dias_calc = ex._days_between(snap.get("fecha_inicio"), snap.get("fecha_fin"))
            dias_snap = snap.get("dias")
            if dias_snap is None:
                proc = "no_leido"
            elif dias_etiqueta is not None and dias_snap == dias_etiqueta:
                proc = "ETIQUETA (evidencia)"
            elif dias_calc is not None and dias_snap == dias_calc:
                proc = "DERIVADO de las 2 fechas"
            else:
                proc = f"otro (tabla/ancla posicional) = {dias_snap}"
            filas.append({
                "id": doc["id"], "sha8": doc["sha8"], "archivo": doc["archivo"],
                "tipo_documento": rec.get("tipo_documento"),
                "dias_snapshot": dias_snap, "dias_etiqueta": dias_etiqueta,
                "dias_calc": dias_calc, "procedencia": proc,
                "inicio": snap.get("fecha_inicio"), "fin": snap.get("fecha_fin"),
            })
    print(f"{'id':5}{'tipo':13}{'dias':6}{'etiq':6}{'calc':6}  procedencia")
    for f in filas:
        print(f"{f['id']:5}{str(f['tipo_documento']):13}{str(f['dias_snapshot']):6}"
              f"{str(f['dias_etiqueta']):6}{str(f['dias_calc']):6}  {f['procedencia']}")
    derivados = [f["id"] for f in filas if f["procedencia"].startswith("DERIVADO")]
    print(f"\nDERIVADOS (T01 tautológico): {len(derivados)} -> {derivados}")
    (AQUI / "resultados_procedencia_dias.json").write_text(
        json.dumps(filas, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
