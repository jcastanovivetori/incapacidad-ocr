#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Reconocimiento: que dispara HOY sobre los 16 documentos LEGITIMOS.

Dos superficies, porque hoy no existe un motor de reglas de tiempos en el paquete:
  (A) PRODUCCION: extract.RuleBasedExtractor + normalizar_fechas + erp.mapear_a_staging
      -> `problemas` / `campos_faltantes` / `fecha_inicio_calculada` (esto es lo que
      ve el auxiliar hoy).
  (B) CANDIDATA: los checks AF01..AF06 de senales/aritmetica_fechas/probe.py (el
      unico codigo que valida la coherencia de los tiempos).

Solo lee. No toca el paquete ni el dataset. PII: se imprime el ID del corpus, no el
nombre de archivo (el mapeo queda en el JSON de salida, en disco).
"""
from __future__ import annotations

import json
import os
import sys

# --- Rutas relativas (añadidas por scripts/exportar_analisis.py) --------------------------
# Este script se escribió con rutas ABSOLUTAS de la máquina donde se investigó. Se resuelven
# desde la ubicación del propio archivo para que funcione tras un `git pull` en cualquier
# equipo. El corpus (`dataset-falsedad/`) NO está en el repositorio: lo aporta el cliente.
import pathlib as _pl
_REPO = _pl.Path(__file__).resolve().parents[3]
_DATASET = _REPO.parent / "dataset-falsedad"
_EJEMPLOS = _REPO.parent / "Ejemplos"
# ------------------------------------------------------------------------------------------

REPO = str(_REPO)
BASE = str(_DATASET)
for p in (REPO, os.path.join(BASE, "senales", "aritmetica_fechas")):
    if p not in sys.path:
        sys.path.insert(0, p)

import probe  # noqa: E402  (sonda de aritmetica_fechas, solo lectura)
from incapacidad_ocr import erp  # noqa: E402
from incapacidad_ocr.extract import RuleBasedExtractor, normalizar_fechas  # noqa: E402

# Problemas de mapear_a_staging que dependen de la BD (LookupsNulos los dispara
# siempre): se separan para no confundirlos con avisos de TIEMPOS.
BD = ("no encontrada en empleados", "no esta en el catalogo", "no está en el catálogo",
      "EPS no identificada", "No se detectó el código de diagnóstico",
      "No se detectó la cédula")


def es_tiempo(p: str) -> bool:
    return not any(b in p for b in BD)


def main() -> None:
    man = probe.cargar_manifest()
    docs = probe.cargar_jsons()
    # ID estable IGUAL que la sonda: orden (etiqueta, archivo) -> R01..R16.
    docs.sort(key=lambda d: (d.get("etiqueta", ""), d.get("archivo", "")))
    reales = [d for d in docs if not str(d.get("etiqueta", "")).startswith("fals")]
    salida = []
    print("=" * 118)
    print("A+B sobre los 16 documentos LEGITIMOS")
    print("=" * 118)
    for i, d in enumerate(reales, 1):
        did = f"R{i:02d}"
        texto = d.get("texto_plano") or ""
        fila = man.get(d["archivo"], {})
        sha = (fila.get("sha256") or "")[:8]
        cuar = fila.get("cuarentena") == "si"

        # (A) PRODUCCION: se re-extrae del texto para ver el camino completo.
        rec = RuleBasedExtractor().extract(texto)
        normalizar_fechas(rec)
        res = {"incapacidad": rec, "texto_plano": texto,
               "ocr_backend": d.get("ocr_backend"), "extractor": d.get("extractor"),
               "fuente": d["archivo"]}
        m = erp.mapear_a_staging(res, lookups=erp.LookupsNulos())
        probs_t = [p for p in m["problemas"] if es_tiempo(p)]
        probs_bd = [p for p in m["problemas"] if not es_tiempo(p)]

        # (B) CANDIDATA
        ev = probe.evaluar(texto, d)
        checks = [h["check"] for h in ev["hallazgos"]]

        inca = rec.get("incapacidad", {})
        print(f"\n{did} {sha} {'[CUARENTENA] ' if cuar else ''}len_txt={len(texto)}")
        print(f"   pipeline   inicio={inca.get('fecha_inicio')} fin={inca.get('fecha_fin')} "
              f"dias={inca.get('dias')} calc_inicio={inca.get('fecha_inicio_calculada')} "
              f"tipo_doc={rec.get('tipo_documento')}")
        print(f"   impreso    inicio={ev['impresos']['inicio']} fin={ev['impresos']['fin']} "
              f"dias={ev['impresos']['dias']}  fuentes="
              f"{ev['impresos']['fuente_inicio']}/{ev['impresos']['fuente_fin']}/"
              f"{ev['impresos']['fuente_dias']}")
        print(f"   (A) TIEMPO {probs_t or '-'}")
        print(f"       otros  {len(probs_bd)} problemas de BD (LookupsNulos)")
        print(f"   (B) checks {checks or '-'}  {ev['motivo_no_aplica'] or ''}")
        for h in ev["hallazgos"]:
            print(f"       -> {h}")
        salida.append({
            "id": did, "archivo": d["archivo"], "sha8": sha, "cuarentena": cuar,
            "pipeline": {k: inca.get(k) for k in
                         ("fecha_inicio", "fecha_fin", "dias", "fecha_inicio_calculada")},
            "impresos": ev["impresos"], "checks": checks,
            "hallazgos": ev["hallazgos"], "motivo_no_aplica": ev["motivo_no_aplica"],
            "problemas_tiempo": probs_t, "problemas_bd": probs_bd,
            "requiere_revision": m["requiere_revision"],
            "tipo_documento": rec.get("tipo_documento"),
        })

    print("\n" + "=" * 118)
    n_check = sum(1 for s in salida if s["checks"])
    n_t = sum(1 for s in salida if s["problemas_tiempo"])
    print(f"reales con algun check AF disparado : {n_check}/16 -> "
          f"{[s['id'] for s in salida if s['checks']]}")
    print(f"reales con aviso de TIEMPOS en (A)  : {n_t}/16 -> "
          f"{[s['id'] for s in salida if s['problemas_tiempo']]}")
    with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "recon.json"),
              "w", encoding="utf-8") as fh:
        json.dump(salida, fh, ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()
