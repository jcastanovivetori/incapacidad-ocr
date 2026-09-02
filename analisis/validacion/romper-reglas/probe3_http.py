#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Parte 3: confirmar que las caidas llegan al CLIENTE como HTTP 500.

Las excepciones de probe.py (A14/B8 ValueError, B12/B13 AttributeError) solo son
GRAVES si escapan del endpoint. Se prueba con TestClient (sin red, sin OCR: se
llama /api/mapear, que NO procesa imagen). Sin BD levantada -> _mapear_staging
degrada a LookupsNulos, que es el camino que igual revienta.

Sin PII: cedula "00000000".
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

# --- Rutas relativas (añadidas por scripts/exportar_analisis.py) --------------------------
# Este script se escribió con rutas ABSOLUTAS de la máquina donde se investigó. Se resuelven
# desde la ubicación del propio archivo para que funcione tras un `git pull` en cualquier
# equipo. El corpus (`dataset-falsedad/`) NO está en el repositorio: lo aporta el cliente.
import pathlib as _pl
_REPO = _pl.Path(__file__).resolve().parents[3]
_DATASET = _REPO.parent / "dataset-falsedad"
_EJEMPLOS = _REPO.parent / "Ejemplos"
# ------------------------------------------------------------------------------------------

RAIZ = Path(str(_REPO))
sys.path.insert(0, str(RAIZ))

from fastapi.testclient import TestClient  # noqa: E402

from incapacidad_ocr.webapp import app  # noqa: E402

SALIDA: list[dict[str, Any]] = []
cli = TestClient(app, raise_server_exceptions=False)


def post(nombre: str, esperado: str, cuerpo: dict[str, Any]) -> None:
    r = cli.post("/api/mapear", json=cuerpo)
    try:
        cuerpo_resp = r.json()
    except Exception:  # noqa: BLE001
        cuerpo_resp = r.text[:200]
    resumen: Any
    if r.status_code == 200 and isinstance(cuerpo_resp, dict) and "row" in cuerpo_resp:
        resumen = {
            "fechainicio": cuerpo_resp["row"]["fechainicio"],
            "Numerodias": cuerpo_resp["row"]["Numerodias"],
            "fechavencimiento": cuerpo_resp["row"]["fechavencimiento"],
            "problemas": cuerpo_resp["problemas"],
            "requiere_revision": cuerpo_resp["requiere_revision"],
        }
    else:
        resumen = cuerpo_resp
    obtenido = {"http": r.status_code, "cuerpo": resumen}
    SALIDA.append({"caso": nombre, "entrada": cuerpo, "esperado": esperado,
                   "obtenido": obtenido})
    print(f"--- {nombre}\n    esperado: {esperado}\n"
          f"    obtenido: HTTP {r.status_code} · {json.dumps(resumen, ensure_ascii=False)[:400]}\n")


def res(**tiempos: Any) -> dict[str, Any]:
    return {"incapacidad": {"paciente": {"documento_numero": "00000000"},
                            "incapacidad": dict(tiempos)}}


print("=== /api/mapear con entradas degeneradas (sin BD, degrada a LookupsNulos) ===\n")

post("H1 sano (referencia)", "HTTP 200",
     {"resultado": res(fecha_inicio="2026-06-01", dias=10)})

post("H2 override dias='\\u00b2' (digito unicode NO decimal)",
     "HTTP 200 o 400 con mensaje; NUNCA 500",
     {"resultado": res(fecha_inicio="2026-06-01"), "campos": {"dias": "\u00b2"}})

post("H3 override dias='\\u2075' (superindice 5)",
     "HTTP 200 o 400; NUNCA 500",
     {"resultado": res(fecha_inicio="2026-06-01"), "campos": {"dias": "\u2075"}})

post("H4 'incapacidad' anidada es lista",
     "HTTP 200 degradado o 400; NUNCA 500",
     {"resultado": {"incapacidad": {"incapacidad": [1]}}})

post("H5 'paciente' es lista",
     "HTTP 200 degradado o 400; NUNCA 500",
     {"resultado": {"incapacidad": {"paciente": ["X"], "incapacidad": {}}}})

post("H6 override fecha_inicio='2026-W23-1' (ISO de semana)",
     "no escribir en la fila una cadena que MySQL DATE no entiende",
     {"resultado": res(dias=3), "campos": {"fecha_inicio": "2026-W23-1"}})

post("H7 override fecha_inicio='2026-152' (ISO ordinal)",
     "no escribir en la fila una cadena que MySQL DATE no entiende",
     {"resultado": res(dias=3), "campos": {"fecha_inicio": "2026-152"}})

post("H8 override fecha_inicio='2026-02-30' (imposible)",
     "se descarta + problema explicito de fecha invalida",
     {"resultado": res(dias=3), "campos": {"fecha_inicio": "2026-02-30"}})

post("H9 override dias='0'", "problema de dias invalidos",
     {"resultado": res(fecha_inicio="2026-06-01"), "campos": {"dias": "0"}})

post("H10 override dias='-3'",
     "problema de dias invalidos (no 'no se detecto')",
     {"resultado": res(fecha_inicio="2026-06-01"), "campos": {"dias": "-3"}})

post("H11 override dias con 10.000 digitos (entrada abusiva)",
     "rechazo acotado; sin colgar el proceso",
     {"resultado": res(fecha_inicio="2026-06-01"), "campos": {"dias": "9" * 10000}})

post("H12 override fecha_fin anterior al inicio",
     "problema 'fin anterior al inicio'",
     {"resultado": res(fecha_inicio="2026-06-10", dias=3),
      "campos": {"fecha_fin": "2026-05-01"}})

sal = Path(__file__).with_name("resultados_http.json")
sal.write_text(json.dumps(SALIDA, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
quinientos = [c["caso"] for c in SALIDA if c["obtenido"]["http"] >= 500]
print("=== CASOS QUE DEVUELVEN 5xx ===")
for c in quinientos or ["(ninguno)"]:
    print("   ", c)
print(f"\n--- {len(SALIDA)} casos -> {sal}")
