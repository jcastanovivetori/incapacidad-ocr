#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Consolida las metricas del frente 'falsos positivos' desde los dos JSON.

Requiere haber corrido antes `recon.py` (corpus) y `casos_legitimos.py` (sinteticos).
No recalcula nada: solo cuenta, para que las cifras del INFORME no se escriban a mano.
"""
from __future__ import annotations

import json
import os

AQUI = os.path.dirname(os.path.abspath(__file__))

# Clasificacion MANUAL, documentada en INFORME.md §2 (cada etiqueta se justifica ahi
# contra el texto OCR del documento). Se declara aqui para que el conteo sea
# reproducible y auditable, no un numero suelto en la prosa.
CLASE = {
    "R01": ("incapacidad", "aviso_evitable", "fecha_inicio_calculada aunque el papel la imprime"),
    "R02": ("incapacidad", "aviso_evitable", "fin impresa no leida -> dias no derivables"),
    "R03": ("incapacidad", "aviso_evitable", "fin impresa no leida -> dias no derivables"),
    "R04": ("incapacidad", "valor_erroneo", "inicio toma el valor de la fin (bloque desalineado)"),
    "R05": ("permiso", "esperado", "permiso manuscrito con RapidOCR (CLAUDE.md: usar vision)"),
    "R06": ("incapacidad", "limpio", "dias derivados de las dos fechas impresas"),
    "R07": ("incapacidad", "limpio", ""),
    "R08": ("permiso", "limpio", "solo el aviso del checkbox remunerado (esperado)"),
    "R09": ("incapacidad", "limpio", "maternidad 126 dias"),
    "R10": ("adjunto", "no_aplica", "HISTORIA CLINICA: en produccion no se OCR-ea (batch.TIPODOC_BASE)"),
    "R11": ("incapacidad", "limpio", ""),
    "R12": ("incapacidad", "limpio", "dias derivados de las dos fechas impresas"),
    "R13": ("incapacidad", "limpio", ""),
    "R14": ("incapacidad", "aviso_evitable", "fecha_inicio_calculada aunque el papel la imprime"),
    # R15/R16: el trabajo paralelo (numeros_es + guardarrail _NUM_DIAS, extract.py:286)
    # cerro los DOS valores erroneos de dias que este frente habia medido antes
    # (R15 dias=29 -> 4 correcto; R16 dias=202 -> None). Lo que queda son avisos.
    "R15": ("incapacidad", "aviso_evitable", "inicio/fin impresos en dd-mm-aa no se leen (H03)"),
    "R16": ("incapacidad", "aviso_evitable", "las dos fechas escritas del Sura no se leen (H11)"),
}


def main() -> None:
    rec = json.load(open(os.path.join(AQUI, "recon.json"), encoding="utf-8"))
    cas = json.load(open(os.path.join(AQUI, "casos_legitimos.json"), encoding="utf-8"))

    print("=" * 100)
    print("1. CORPUS: 16 documentos etiquetados REAL")
    print("=" * 100)
    tipos: dict[str, int] = {}
    clases: dict[str, list[str]] = {}
    for s in rec:
        t, c, _ = CLASE[s["id"]]
        tipos[t] = tipos.get(t, 0) + 1
        clases.setdefault(c, []).append(s["id"])
    print("   composicion por tipo de documento: " + ", ".join(f"{k}={v}" for k, v in sorted(tipos.items())))
    for c in ("limpio", "aviso_evitable", "valor_erroneo", "esperado", "no_aplica"):
        ids = clases.get(c, [])
        print(f"   {c:<16s} {len(ids):>2d}  {ids}")

    inc = [s for s in rec if CLASE[s["id"]][0] == "incapacidad"]
    malos = [s for s in inc if CLASE[s["id"]][1] in ("aviso_evitable", "valor_erroneo")]
    print(f"\n   incapacidades reales                     : {len(inc)}")
    print(f"   con aviso evitable o valor erroneo       : {len(malos)} "
          f"({100 * len(malos) / len(inc):.0f}%) -> {[s['id'] for s in malos]}")

    print("\n   checks de coherencia AF01..AF06 que disparan sobre REALES:")
    for s in rec:
        if s["checks"]:
            print(f"      {s['id']} cuarentena={s['cuarentena']} -> {s['checks']}")
    sin_cuar = [s for s in rec if not s["cuarentena"]]
    disp = [s for s in sin_cuar if s["checks"]]
    print(f"      falsos positivos de coherencia en reales NO en cuarentena: "
          f"{len(disp)}/{len(sin_cuar)}")

    print("\n   avisos de tiempos que hoy llegan al auxiliar (superficie de produccion):")
    for s in rec:
        for p in s["problemas_tiempo"]:
            print(f"      {s['id']:<4s} {p}")

    print("\n" + "=" * 100)
    print("2. CASOS LEGITIMOS ATIPICOS SINTETICOS")
    print("=" * 100)
    ok = [c for c in cas if c["ok"]]
    print(f"   pasan {len(ok)}/{len(cas)}")
    for c in cas:
        estado = "OK   " if c["ok"] else "FALLA"
        print(f"   {estado} {c['id']}")
        for f in c["fallos"]:
            print(f"           {f}")


if __name__ == "__main__":
    main()
