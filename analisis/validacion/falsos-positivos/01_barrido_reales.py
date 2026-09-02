"""Barrido 1 — ¿qué regla dispara sobre los 16 documentos LEGÍTIMOS del corpus?

Un falso positivo del motor de tiempos cuesta 7000 revisiones/mes: este barrido evalúa
cada documento real con el catálogo COMPLETO por defecto y lista, regla por regla, qué
NO_CUMPLE (falso positivo candidato) y qué queda NO_EVALUABLE (cobertura perdida).

Dos fechas de proceso, porque T09/T10 se miden contra `hoy`:
  * `hoy` = inicio + 3 días  → simula la radicación normal (el caso de producción).
  * `hoy` = 2026-09-02       → fecha de corte del corpus (reproceso de un lote viejo).

Salida: tabla por documento + `resultados.json` para máquina.
100% local: no ejecuta OCR (lee el `texto_plano` ya extraído del dataset).
"""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from _comun import (cargar_docs, evaluar_doc, fecha_proceso, registro_como_processor,
                    reglas_tiempo)

AQUI = Path(__file__).resolve().parent
CORTE = date(2026, 9, 2)


def _linea(doc, rec, res, etiqueta_hoy):
    ctx, ver = res["ctx"], res["veredicto"]
    inf = res["informe"]
    print(f"\n{'='*100}")
    print(f"{doc['id']} {doc['sha8']}  {doc['archivo']}"
          + ("   [CUARENTENA]" if doc["cuarentena"] else ""))
    print(f"  hoy={etiqueta_hoy}  tipo_documento={rec.get('tipo_documento')}")
    print(f"  LEIDO    inicio={ctx.inicio_crudo!r} fin={ctx.fin_crudo!r} "
          f"dias={ctx.dias_crudo!r} dias_letra={ctx.dias_letra!r} exped={ctx.expedicion_crudo if hasattr(ctx,'expedicion_crudo') else ctx.expedicion_cruda!r}")
    inca = rec.get("incapacidad") or {}
    print(f"  EFECTIVO inicio={inca.get('fecha_inicio')} fin={inca.get('fecha_fin')} "
          f"dias={inca.get('dias')} calc_inicio={inca.get('fecha_inicio_calculada')} "
          f"fin_recalc={inca.get('fecha_fin_recalculada')}")
    print(f"  VEREDICTO {inf['veredicto']}  sev_max={ver.severidad_max} "
          f"puntaje={ver.puntaje} cobertura={inf['resumen']['cobertura']} "
          f"exige_revision={ver.exige_revision}")
    for h in ver.hallazgos:
        print(f"    !! {h.severidad:5} {h.codigo}: {h.mensaje}")
    if not ver.hallazgos:
        print("    (sin hallazgos)")
    ne = [f"{r['codigo']}({','.join(r['faltan']) or '-'})" for r in ver.no_evaluables]
    print(f"    no_evaluables: {', '.join(ne) if ne else '-'}")


def main() -> None:
    docs = cargar_docs()
    salida = []
    for doc in docs:
        rec = registro_como_processor(doc["texto_plano"])
        fila = {"id": doc["id"], "sha8": doc["sha8"], "archivo": doc["archivo"],
                "cuarentena": doc["cuarentena"], "escenarios": {}}
        for etiqueta, hoy in (("radicacion", fecha_proceso(rec)), ("corte_corpus", CORTE)):
            res = evaluar_doc(rec, hoy)
            _linea(doc, rec, res, f"{hoy.isoformat()} ({etiqueta})")
            ver = res["veredicto"]
            fila["escenarios"][etiqueta] = {
                "hoy": hoy.isoformat(),
                "veredicto": res["informe"]["veredicto"],
                "severidad_max": ver.severidad_max,
                "exige_revision": ver.exige_revision,
                "puntaje": ver.puntaje,
                "cobertura": res["informe"]["resumen"]["cobertura"],
                "hallazgos": [h.como_dict() for h in ver.hallazgos],
                "no_evaluables": list(ver.no_evaluables),
            }
        inca = rec.get("incapacidad") or {}
        fila["leido"] = {
            "inicio_crudo": (rec.get("incapacidad") or {}).get(reglas_tiempo.CLAVE_SNAPSHOT, {}).get("fecha_inicio"),
            "fin_crudo": (rec.get("incapacidad") or {}).get(reglas_tiempo.CLAVE_SNAPSHOT, {}).get("fecha_fin"),
            "dias_crudo": (rec.get("incapacidad") or {}).get(reglas_tiempo.CLAVE_SNAPSHOT, {}).get("dias"),
            "dias_letra": (rec.get("incapacidad") or {}).get(reglas_tiempo.CLAVE_SNAPSHOT, {}).get("dias_letra"),
        }
        fila["efectivo"] = {"fecha_inicio": inca.get("fecha_inicio"), "fecha_fin": inca.get("fecha_fin"),
                            "dias": inca.get("dias"),
                            "fecha_inicio_calculada": inca.get("fecha_inicio_calculada"),
                            "fecha_fin_recalculada": inca.get("fecha_fin_recalculada")}
        fila["dataset_dias"] = ((doc["registro_dataset"].get("incapacidad") or {}).get("dias")
                                if isinstance(doc["registro_dataset"], dict) else None)
        salida.append(fila)

    # ---- Resumen agregado: cuántos documentos LEGÍTIMOS acabarían en revisión ----
    print(f"\n{'='*100}\nRESUMEN (16 documentos legítimos)\n{'='*100}")
    for etiqueta in ("radicacion", "corte_corpus"):
        marcados = [f["id"] for f in salida if f["escenarios"][etiqueta]["exige_revision"]]
        avisos = [f["id"] for f in salida
                  if not f["escenarios"][etiqueta]["exige_revision"]
                  and f["escenarios"][etiqueta]["hallazgos"]]
        print(f"\n[{etiqueta}] exigen revisión: {len(marcados)}/{len(salida)} -> {marcados}")
        print(f"[{etiqueta}] solo avisos LEVE: {len(avisos)}/{len(salida)} -> {avisos}")
        conteo: dict[str, int] = {}
        for f in salida:
            for h in f["escenarios"][etiqueta]["hallazgos"]:
                conteo[h["codigo"]] = conteo.get(h["codigo"], 0) + 1
        for cod, n in sorted(conteo.items(), key=lambda kv: -kv[1]):
            print(f"    {cod}: {n} documento(s)")
    (AQUI / "resultados_reales.json").write_text(
        json.dumps(salida, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\n-> {AQUI / 'resultados_reales.json'}")


if __name__ == "__main__":
    main()
