"""Barrido 7 — robustez: ¿algún registro degenerado tumba el motor o el mapeo?

Un falso positivo GRAVE incluye "caída del motor": si `validar_tiempos` o
`mapear_a_staging` lanzan, el documento legítimo no llega a staging. `evaluar_reglas`
protege CADA regla con try/except, pero `construir_contexto`, `resumen_evidencia` y
`validar_tiempos` corren fuera de esa red.
"""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from _comun import reglas_tiempo

from incapacidad_ocr import erp
from incapacidad_ocr.validacion_temporal import validar_registro

AQUI = Path(__file__).resolve().parent
HOY = date(2026, 9, 2)
S = reglas_tiempo.CLAVE_SNAPSHOT

DEGENERADOS: list[tuple[str, dict]] = [
    ("dias como lista", {"fecha_inicio": "2026-08-20", "dias": [3]}),
    ("dias como dict", {"fecha_inicio": "2026-08-20", "dias": {"n": 3}}),
    ("dias booleano True", {"fecha_inicio": "2026-08-20", "dias": True}),
    ("dias float 3.5", {"fecha_inicio": "2026-08-20", "dias": 3.5}),
    ("dias digito unicode", {"fecha_inicio": "2026-08-20", "dias": "²"}),
    ("dias cadena larguisima", {"fecha_inicio": "2026-08-20", "dias": "9" * 5000}),
    ("dias negativo", {"fecha_inicio": "2026-08-20", "dias": -3}),
    ("fecha como dict", {"fecha_inicio": {"y": 2026}, "dias": 3}),
    ("fecha ISO de semana", {"fecha_inicio": "2026-W23-1", "dias": 3}),
    ("fecha basica 20260820", {"fecha_inicio": "20260820", "dias": 3}),
    ("fecha con hora", {"fecha_inicio": "2026-08-20T00:00:00", "dias": 3}),
    ("foto que no es dict", {"fecha_inicio": "2026-08-20", "dias": 3, S: "nada"}),
    ("foto con tipos raros", {"fecha_inicio": "2026-08-20", "dias": 3,
                              S: {"fecha_inicio": 20260820, "fecha_fin": None,
                                  "dias": ["3"], "dias_letra": "tres"}}),
    ("todo None", {"fecha_inicio": None, "fecha_fin": None, "dias": None}),
    ("bloque vacio", {}),
    ("año 1", {"fecha_inicio": "0001-01-01", "fecha_fin": "0001-01-03", "dias": 3}),
    ("año 9999", {"fecha_inicio": "9999-12-30", "fecha_fin": "9999-12-31", "dias": 2}),
]

OVERRIDES_RAROS: list[tuple[str, dict]] = [
    ("override dias lista", {"dias": [1, 2]}),
    ("override fecha dict", {"fecha_inicio": {"a": 1}}),
    ("override fecha vacia", {"fecha_fin": "   "}),
    ("override expedicion basura", {"fecha_expedicion": "no-es-fecha"}),
]


def main() -> None:
    filas = []
    print(f"{'='*100}\nA) validar_registro / validar_tiempos con bloques degenerados\n{'='*100}")
    for nombre, bloque in DEGENERADOS:
        try:
            inf = validar_registro({"incapacidad": bloque}, hoy=HOY)
            json.dumps(inf)                                  # ¿es serializable de verdad?
            estado = f"OK veredicto={inf['veredicto']} codigos={inf['codigos']}"
        except Exception as exc:  # noqa: BLE001
            estado = f"EXCEPCION {type(exc).__name__}: {exc}"
        print(f"  {nombre:28} -> {estado}")
        filas.append({"caso": nombre, "resultado": estado})

    print(f"\n{'='*100}\nB) mapear_a_staging con los mismos bloques (camino real al ERP)\n{'='*100}")
    for nombre, bloque in DEGENERADOS:
        try:
            m = erp.mapear_a_staging({"incapacidad": {"incapacidad": bloque}}, "WHATSAPP",
                                     erp.LookupsNulos(), hoy=HOY)
            json.dumps(m, default=str)
            estado = (f"OK alertas={m['row'].get('alertas_tiempos')} "
                      f"dias={m['row'].get('Numerodias')} venc={m['row'].get('fechavencimiento')}")
        except Exception as exc:  # noqa: BLE001
            estado = f"EXCEPCION {type(exc).__name__}: {exc}"
        print(f"  {nombre:28} -> {estado}")
        filas.append({"caso": f"erp:{nombre}", "resultado": estado})

    print(f"\n{'='*100}\nC) overrides raros del auxiliar\n{'='*100}")
    base = {"fecha_inicio": "2026-08-20", "fecha_fin": "2026-08-22", "dias": 3,
            S: {"fecha_inicio": "2026-08-20", "fecha_fin": "2026-08-22", "dias": 3,
                "dias_letra": None}}
    for nombre, ov in OVERRIDES_RAROS:
        try:
            inf = validar_registro({"incapacidad": base}, hoy=HOY, overrides=ov)
            json.dumps(inf)
            estado = f"OK veredicto={inf['veredicto']} codigos={inf['codigos']}"
        except Exception as exc:  # noqa: BLE001
            estado = f"EXCEPCION {type(exc).__name__}: {exc}"
        print(f"  {nombre:28} -> {estado}")
        filas.append({"caso": f"ov:{nombre}", "resultado": estado})

    print(f"\n{'='*100}\nD) hoy = None por la API pública (date.today) y config rota\n{'='*100}")
    try:
        inf = validar_registro({"incapacidad": base})
        print(f"  hoy por defecto -> OK veredicto={inf['veredicto']}")
    except Exception as exc:  # noqa: BLE001
        print(f"  hoy por defecto -> EXCEPCION {type(exc).__name__}: {exc}")
    for datos in ({"reglas": "no-es-dict"}, {"umbrales": {"dias_max": "540"}},
                  {"reglas": {"T99_NO_EXISTE": {"severidad": "GRAVE"}}},
                  {"umbrales": {"dias_min": 20, "dias_max": 5}}):
        cfg = reglas_tiempo._aplicar(reglas_tiempo.config_por_defecto(), datos, "prueba")
        print(f"  config {datos} -> avisos={list(cfg.avisos)}")
        filas.append({"caso": f"config:{datos}", "avisos": list(cfg.avisos)})

    (AQUI / "resultados_robustez.json").write_text(
        json.dumps(filas, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    print(f"\n-> {AQUI / 'resultados_robustez.json'}")


if __name__ == "__main__":
    main()
