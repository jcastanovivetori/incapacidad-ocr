"""Metricas agregadas + tabla por documento a partir de `resultados_motor.json`.

Separa lo que el cliente pidio de lo que no es responsabilidad de este motor:

  * Universo: 31 documentos del corpus MENOS los 5 en cuarentena de `manifest.csv`
    (parejas byte-identicas con etiqueta contradictoria + un titular compartido).
    Los de cuarentena se imprimen igual, marcados CUAR, pero NO cuentan en ninguna metrica.
  * La metrica que importa: falsas cuyo motivo DECLARADO en `ground_truth.json` es temporal
    (senal `FECHAS_INCOHERENTES`). Las falsas por firma / tipografia / diagnostico NO son
    de este motor y contarlas como fallo seria injusto: van en su propia columna.
  * Falsos positivos: documentos REALES a los que el motor les pone un hallazgo que exige
    revision (GRAVE/MEDIA). Un LEVE se cuenta aparte: avisa, no bloquea.
  * NO EVALUABLES: documentos de los que el motor no pudo comprobar la coherencia por falta
    de datos LEIDOS (veredicto SIN_DATOS, o T01 no evaluable por tripleta incompleta).

Se apoya en el chequeo de referencia de `medir_motor.py` (aritmetica pura sobre la tripleta
leida) para poder decir si el motor acierta contra algo que no es el propio motor.

Uso:
    <repo>/.venv/Scripts/python.exe agregar_motor.py
"""
from __future__ import annotations

import json
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

AQUI = Path(__file__).resolve().parent
ENTRADA = AQUI / "resultados_motor.json"
TABLA_MD = AQUI / "tabla_motor.md"
METRICAS = AQUI / "metricas_motor.json"

PASADA = "B_pipeline"     # la ruta de PRODUCCION (foto + reconciliacion) es la que se mide


def marca_revision(p: dict) -> bool:
    """El motor MARCA el documento (hallazgo GRAVE/MEDIA → entra en `problemas`)."""
    return bool(p["exige_revision"])


def marca_aviso(p: dict) -> bool:
    """Solo avisos LEVE (no bloquea)."""
    return bool(p["codigos"]) and not p["exige_revision"]


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        pass
    d = json.loads(ENTRADA.read_text(encoding="utf-8"))
    docs = d["documentos"]
    evaluables = [f for f in docs if not f["cuarentena"]]
    falsas = [f for f in evaluables if f["etiqueta"] == "falsa"]
    reales = [f for f in evaluables if f["etiqueta"] == "real"]
    temporales = [f for f in falsas if f["gt_temporal"]]
    otras = [f for f in falsas if not f["gt_temporal"]]

    def cnt(grupo, pred) -> int:
        return sum(1 for f in grupo if pred(f))

    m: dict[str, object] = {
        "hoy_fijado": d["hoy_fijado"],
        "huellas_codigo": d["huellas_codigo"],
        "reglas_en_catalogo": d["reglas_en_catalogo"],
        "corpus_total": len(docs),
        "cuarentena_excluidos": [f["id"] for f in docs if f["cuarentena"]],
        "universo_evaluado": {"total": len(evaluables), "falsas": len(falsas),
                              "reales": len(reales)},
        # --- la metrica que pidio el cliente
        "falsas_motivo_temporal": {
            "universo": [f["id"] for f in temporales],
            "detectadas": [f["id"] for f in temporales if marca_revision(f[PASADA])],
        },
        "falsas_otros_motivos": {
            "universo": len(otras),
            "marcadas_por_tiempos": [f["id"] for f in otras if marca_revision(f[PASADA])],
            "nota": "no son responsabilidad de este motor; marcarlas es extra, no marcarlas no es fallo",
        },
        # --- coste: reales marcadas por error
        "reales_marcadas_grave_o_media": [f["id"] for f in reales if marca_revision(f[PASADA])],
        "reales_solo_aviso_leve": [f["id"] for f in reales if marca_aviso(f[PASADA])],
        # --- cuanto pudo mirar de verdad
        "veredictos": {},
        "sin_datos": [f["id"] for f in evaluables if f[PASADA]["veredicto"] == "SIN_DATOS"],
        "t01_no_evaluable": [f["id"] for f in evaluables
                             if "T01_DURACION_VS_RANGO" in f[PASADA]["no_evaluables"]],
        "tripleta_leida_completa": [f["id"] for f in evaluables
                                    if f["B_referencia"]["tripleta_completa"]],
        "cobertura_media": round(sum(f[PASADA]["cobertura"] for f in evaluables) / len(evaluables), 3),
        # --- contraste con el chequeo de referencia (independiente del motor)
        "referencia_incoherentes": [f["id"] for f in evaluables if f["B_referencia"]["incoherente"]],
        "referencia_invertidos": [f["id"] for f in evaluables if f["B_referencia"]["invertido"]],
        "referencia_dias_fuera_rango": [f["id"] for f in evaluables
                                        if f["B_referencia"]["dias_fuera_rango"]],
        # --- cada regla: en cuantos documentos CUMPLE / NO CUMPLE / no se pudo comprobar
        "por_regla": {},
        # --- la pasada A (registro almacenado, sin la foto de processor) para contraste
        "discrepancias_A_vs_B": [],
        # --- post-condicion R-T05 sobre la fila final (propuesta no implementada como regla)
        "vencimiento_incoherente": [f["id"] for f in evaluables
                                    if f["C_staging"]["vencimiento_coherente"] is False],
        # --- canal por el que llega el hallazgo al auxiliar
        "hallazgo_temporal_en_problemas": [],
        "requiere_revision_todos": cnt(evaluables, lambda f: f["C_staging"]["requiere_revision"]),
        "requiere_revision_solo_por_tiempos": [],
    }

    for v in ("COHERENTE", "AVISOS", "REVISAR", "SIN_DATOS"):
        m["veredictos"][v] = [f["id"] for f in evaluables if f[PASADA]["veredicto"] == v]

    codigos = [r["codigo"] for r in
               json.loads((AQUI / "catalogo_motor.json").read_text(encoding="utf-8"))] \
        if (AQUI / "catalogo_motor.json").is_file() else None
    if codigos is None:
        codigos = sorted({c for f in evaluables for c in
                          list(f[PASADA]["cumplen"]) + list(f[PASADA]["no_cumplen"]) +
                          list(f[PASADA]["no_evaluables"])})
    for cod in codigos:
        m["por_regla"][cod] = {
            "no_cumple": [f["id"] for f in evaluables if cod in f[PASADA]["no_cumplen"]],
            "cumple": cnt(evaluables, lambda f: cod in f[PASADA]["cumplen"]),
            "no_evaluable": cnt(evaluables, lambda f: cod in f[PASADA]["no_evaluables"]),
        }

    for f in evaluables:
        a, b = f["A_almacenado"], f["B_pipeline"]
        if a["veredicto"] != b["veredicto"] or a["codigos"] != b["codigos"]:
            m["discrepancias_A_vs_B"].append({
                "id": f["id"], "etiqueta": f["etiqueta"],
                "A": {"veredicto": a["veredicto"], "codigos": a["codigos"],
                      "cobertura": a["cobertura"], "leido": a["leido"]},
                "B": {"veredicto": b["veredicto"], "codigos": b["codigos"],
                      "cobertura": b["cobertura"], "leido": b["leido"]},
            })
        c = f["C_staging"]
        if c["hallazgos_tiempos"]:
            en_problemas = any(cod in (c["alertas_tiempos"] or "") for cod in c["hallazgos_tiempos"])
            m["hallazgo_temporal_en_problemas"].append(
                {"id": f["id"], "codigos": c["hallazgos_tiempos"],
                 "severidad": c["severidad_tiempos"], "en_alertas_tiempos": en_problemas,
                 "n_problemas_total": c["n_problemas"],
                 "problemas_temporales": [p for p in c["problemas"]
                                          if "tiempos" in p.lower() or "fecha fin" in p.lower()
                                          or "rango" in p.lower()]})

    METRICAS.write_text(json.dumps(m, ensure_ascii=False, indent=1), encoding="utf-8")

    # ------------------------------- tabla markdown -------------------------------
    lineas = [
        "| ID | sha8 | clase | cuar | motivo GT | leído inicio→fin (días) | span/desfase |"
        " veredicto motor | códigos | severidad | cobertura | puntaje |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for f in docs:
        b, r, c = f[PASADA], f["B_referencia"], f["C_staging"]
        rango = f"{r['inicio'] or '—'} → {r['fin'] or '—'} ({r['dias'] if r['dias'] is not None else '—'})"
        span = f"{r['span'] if r['span'] is not None else '—'}/{r['desfase'] if r['desfase'] is not None else '—'}"
        lineas.append(
            f"| `{f['id']}` | `{f['sha8']}` | {f['etiqueta']} | {'SÍ' if f['cuarentena'] else ''} |"
            f" {', '.join(f['gt_senales']) or '—'} | {rango} | {span} |"
            f" **{b['veredicto']}** | {', '.join(b['codigos']) or '—'} |"
            f" {c['severidad_tiempos'] or '—'} | {b['cobertura']:.2f} | {b['puntaje']} |")
    TABLA_MD.write_text("\n".join(lineas) + "\n", encoding="utf-8")

    # ------------------------------- consola -------------------------------
    print(f"universo evaluado: {len(evaluables)} = {len(falsas)} falsas + {len(reales)} reales "
          f"(excluidos {len(docs) - len(evaluables)} en cuarentena: "
          f"{', '.join(m['cuarentena_excluidos'])})")
    ft = m["falsas_motivo_temporal"]
    print(f"\nFALSAS con motivo TEMPORAL declarado (FECHAS_INCOHERENTES): "
          f"{len(ft['detectadas'])}/{len(ft['universo'])}  universo={ft['universo']} "
          f"detectadas={ft['detectadas']}")
    fo = m["falsas_otros_motivos"]
    print(f"FALSAS por OTROS motivos (firma/tipografia/DX/sin motivo): {fo['universo']}; "
          f"marcadas por tiempos (extra): {fo['marcadas_por_tiempos']}")
    print(f"REALES marcadas GRAVE/MEDIA (falsos positivos): "
          f"{len(m['reales_marcadas_grave_o_media'])}/{len(reales)} "
          f"{m['reales_marcadas_grave_o_media']}")
    print(f"REALES solo con aviso LEVE: {m['reales_solo_aviso_leve']}")
    print(f"\nveredictos: " + "  ".join(f"{k}={len(v)}" for k, v in m["veredictos"].items()))
    print(f"SIN_DATOS: {m['sin_datos']}")
    print(f"T01 no evaluable (tripleta leida incompleta): {len(m['t01_no_evaluable'])}/{len(evaluables)} "
          f"{m['t01_no_evaluable']}")
    print(f"tripleta leida COMPLETA: {len(m['tripleta_leida_completa'])}/{len(evaluables)} "
          f"{m['tripleta_leida_completa']}")
    print(f"cobertura media: {m['cobertura_media']}")
    print(f"\nchequeo de REFERENCIA (aritmetica independiente del motor):")
    print(f"  incoherentes={m['referencia_incoherentes']}  invertidos={m['referencia_invertidos']}"
          f"  dias fuera de rango={m['referencia_dias_fuera_rango']}")
    print(f"  post-condicion vencimiento (R-T05) incoherente: {m['vencimiento_incoherente']}")
    print("\npor regla (documentos evaluables):")
    for cod, v in m["por_regla"].items():
        print(f"  {cod:34s} NO_CUMPLE={len(v['no_cumple']):2d} {str(v['no_cumple']):12s} "
              f"CUMPLE={v['cumple']:2d}  no_evaluable={v['no_evaluable']:2d}")
    print(f"\ndiscrepancias pasada A (registro almacenado, sin foto) vs B (produccion): "
          f"{len(m['discrepancias_A_vs_B'])}")
    for x in m["discrepancias_A_vs_B"]:
        print(f"  {x['id']} ({x['etiqueta']}): A={x['A']['veredicto']}/{x['A']['codigos']} "
              f"cob={x['A']['cobertura']} leido={x['A']['leido']['fecha_inicio']}→"
              f"{x['A']['leido']['fecha_fin']}/{x['A']['leido']['dias']}  ||  "
              f"B={x['B']['veredicto']}/{x['B']['codigos']} cob={x['B']['cobertura']} "
              f"leido={x['B']['leido']['fecha_inicio']}→{x['B']['leido']['fecha_fin']}/"
              f"{x['B']['leido']['dias']}")
    print(f"\ncanal al auxiliar: {m['hallazgo_temporal_en_problemas']}")
    print(f"requiere_revision (por cualquier motivo, con LookupsNulos): "
          f"{m['requiere_revision_todos']}/{len(evaluables)}")
    print(f"\nTabla: {TABLA_MD}\nMetricas: {METRICAS}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
