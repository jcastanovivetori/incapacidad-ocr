"""Sondas dirigidas sobre el motor de tiempos, con datos del corpus ya extraidos.

Tres preguntas que la medicion agregada deja abiertas:

  P1. ¿El motor NO detecta F04 (la unica falsa con motivo temporal declarado) porque la
      REGLA no sirve, o porque el extractor no le pasa las dos fechas? Se le entrega a mano
      la tripleta que SI esta impresa en ese documento y se mira que hace T01.
  P2. ¿Cuanto dependen del reloj las reglas de ventana temporal (T09/T10/T14)? Se repite la
      pasada de produccion con varias fechas de proceso y se cuentan las REALES marcadas.
      Importa porque reprocesar un lote viejo (o un contenedor con la fecha mal puesta)
      desplaza esas dos reglas — es la pregunta abierta P6 del propio modulo.
  P3. ¿Es determinista? Las dos parejas byte-identicas del corpus (en cuarentena) tienen que
      dar EXACTAMENTE el mismo veredicto. Es el uso legitimo de los documentos en cuarentena
      (caso de humo), no cuentan como acierto ni como fallo.

No ejecuta OCR: parte de `texto_plano` de los JSON del corpus.
PII: por consola solo IDs del corpus + sha256[:8].

Uso:
    <repo>/.venv/Scripts/python.exe probes_motor.py
"""
from __future__ import annotations

import csv
import json
import sys
from datetime import date
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

REPO = Path(str(_REPO))
BASE = Path(str(_DATASET))
AQUI = Path(__file__).resolve().parent
SALIDA = AQUI / "probes_motor.json"
HOY = date(2026, 9, 2)

sys.path.insert(0, str(REPO))

from incapacidad_ocr.extract import RuleBasedExtractor, normalizar_fechas  # noqa: E402
from incapacidad_ocr.validacion_temporal import (  # noqa: E402
    CLAVE_SNAPSHOT, config_por_defecto, snapshot_leidos, validar_registro,
)

CARPETAS = ("falsas", "falsa", "reales", "real")


def json_de(archivo: str) -> Path | None:
    for c in CARPETAS:
        p = BASE / "ocr" / c / f"{Path(archivo).stem}.json"
        if p.is_file():
            return p
    return None


def manifest() -> list[dict[str, str]]:
    with (BASE / "manifest.csv").open(encoding="utf-8", newline="") as fh:
        filas = list(csv.DictReader(fh))
    for etiqueta, pre in (("falsa", "F"), ("real", "R")):
        for i, f in enumerate(sorted((x for x in filas if x["etiqueta"] == etiqueta),
                                     key=lambda x: x["archivo"]), start=1):
            f["id"] = f"{pre}{i:02d}"
    return filas


def informe_pipeline(texto: str, hoy: date, cfg) -> dict:
    """Ruta de produccion: extraer → foto → reconciliar → validar."""
    rec = RuleBasedExtractor().extract(texto)
    inca = rec.get("incapacidad")
    if isinstance(inca, dict):
        inca[CLAVE_SNAPSHOT] = snapshot_leidos(inca)
    normalizar_fechas(rec)
    return validar_registro(rec, hoy=hoy, config=cfg)


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        pass
    cfg = config_por_defecto()
    filas = manifest()
    por_id = {f["id"]: f for f in filas}
    out: dict[str, object] = {}

    # ---------------- P1: F04 con la tripleta que SI imprime el papel ----------------
    # Lo que el OCR de F04 sí trae (verificado en su .txt): "MARTES 02 ... SEPTIEMBRE DE 2025"
    # (inicio), "JUEVES 04 DE ... SEPTIEMBRE DE 2025" (fin) y "Duracion -DOS" (2 dias).
    # El extractor de hoy solo publica los dias (lector de letras); las dos fechas escritas
    # en palabras no las ancla, asi que T01 se queda sin fin y no puede opinar.
    f04 = por_id["F04"]
    j = json.loads(json_de(f04["archivo"]).read_text(encoding="utf-8"))
    inf_real = informe_pipeline(j["texto_plano"], HOY, cfg)
    # Misma foto, pero con las dos fechas que el papel imprime (simula que el extractor las
    # publicara). NO se toca el paquete: se construye el registro a mano.
    inca_mano = {"fecha_inicio": "2025-09-02", "fecha_fin": "2025-09-04", "dias": 2,
                 "dias_letra": 2}
    inca_mano[CLAVE_SNAPSHOT] = snapshot_leidos(inca_mano)
    inf_mano = validar_registro({"tipo_documento": "incapacidad", "incapacidad": inca_mano},
                                hoy=HOY, config=cfg)
    out["P1_F04"] = {
        "sha8": f04["sha256"][:8],
        "como_llega_hoy": {"veredicto": inf_real["veredicto"],
                           "leido": inf_real["evidencia"]["leido"],
                           "codigos": inf_real["codigos"],
                           "cobertura": inf_real["resumen"]["cobertura"],
                           "t01": [r for r in inf_real["reglas"]
                                   if r["codigo"] == "T01_DURACION_VS_RANGO"]},
        "con_la_tripleta_impresa": {"veredicto": inf_mano["veredicto"],
                                    "codigos": inf_mano["codigos"],
                                    "severidad_max": inf_mano["severidad_max"],
                                    "problemas": inf_mano["problemas"]},
    }

    # ---------------- P2: sensibilidad de T09/T10/T14 a la fecha de proceso ----------------
    fechas = [date(2025, 1, 1), date(2026, 5, 1), HOY, date(2027, 6, 1), date(2028, 9, 2)]
    textos = {}
    for f in filas:
        p = json_de(f["archivo"])
        if p:
            textos[f["id"]] = (f, json.loads(p.read_text(encoding="utf-8")).get("texto_plano") or "")
    p2 = {}
    for hoy in fechas:
        marcadas_r, marcadas_f, avisos_r = [], [], []
        for fid, (f, texto) in sorted(textos.items()):
            if f["cuarentena"] == "si":
                continue
            inf = informe_pipeline(texto, hoy, cfg)
            cods = [c for c in inf["codigos"] if c in
                    ("T09_INICIO_EN_FUTURO", "T10_INICIO_MUY_ANTIGUO",
                     "T14_EXPEDICION_POSTERIOR_AL_INICIO")]
            if not cods:
                continue
            destino = marcadas_r if f["etiqueta"] == "real" else marcadas_f
            if inf["exige_revision"]:
                destino.append({"id": fid, "codigos": cods})
            elif f["etiqueta"] == "real":
                avisos_r.append({"id": fid, "codigos": cods})
        p2[hoy.isoformat()] = {"reales_marcadas": marcadas_r, "reales_solo_aviso": avisos_r,
                               "falsas_marcadas": marcadas_f}
    out["P2_sensibilidad_hoy"] = p2

    # ---------------- P3: determinismo sobre las parejas byte-identicas ----------------
    parejas = [("F03", "R15"), ("F11", "R01")]
    p3 = []
    for a, b in parejas:
        ia = informe_pipeline(textos[a][1], HOY, cfg)
        ib = informe_pipeline(textos[b][1], HOY, cfg)
        # Se comparan las partes que dependen del documento (no la config ni 'hoy').
        recorte = lambda i: {k: i[k] for k in ("veredicto", "codigos", "severidad_max",
                                              "puntaje_coherencia", "resumen", "evidencia")}
        p3.append({"pareja": [a, b], "identico": recorte(ia) == recorte(ib),
                   "veredicto": [ia["veredicto"], ib["veredicto"]]})
        # y dos corridas del MISMO texto
        p3.append({"pareja": [a, a + "(2a corrida)"],
                   "identico": recorte(ia) == recorte(informe_pipeline(textos[a][1], HOY, cfg)),
                   "veredicto": [ia["veredicto"], ia["veredicto"]]})
    out["P3_determinismo"] = p3

    SALIDA.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")

    print("P1 — F04 (unica falsa con motivo temporal declarado)")
    q = out["P1_F04"]
    print(f"   tal como llega hoy: veredicto={q['como_llega_hoy']['veredicto']} "
          f"codigos={q['como_llega_hoy']['codigos']} cobertura={q['como_llega_hoy']['cobertura']}")
    print(f"     leido = inicio={q['como_llega_hoy']['leido']['fecha_inicio']} "
          f"fin={q['como_llega_hoy']['leido']['fecha_fin']} "
          f"dias={q['como_llega_hoy']['leido']['dias']} "
          f"dias_letra={q['como_llega_hoy']['leido']['dias_letra']}")
    print(f"     T01 = {q['como_llega_hoy']['t01']}")
    print(f"   con la tripleta impresa (02→04 sept, 2 dias): "
          f"veredicto={q['con_la_tripleta_impresa']['veredicto']} "
          f"{q['con_la_tripleta_impresa']['codigos']} "
          f"sev={q['con_la_tripleta_impresa']['severidad_max']}")
    for p in q["con_la_tripleta_impresa"]["problemas"]:
        print(f"     → {p}")

    print("\nP2 — sensibilidad a la fecha de proceso (reglas de ventana temporal)")
    for hoy, v in out["P2_sensibilidad_hoy"].items():
        print(f"   hoy={hoy}: reales marcadas={v['reales_marcadas']} "
              f"reales solo aviso={v['reales_solo_aviso']} falsas marcadas={len(v['falsas_marcadas'])}")

    print("\nP3 — determinismo (parejas byte-identicas del corpus, en cuarentena)")
    for x in out["P3_determinismo"]:
        print(f"   {x['pareja']}: identico={x['identico']} veredictos={x['veredicto']}")
    print(f"\nDetalle: {SALIDA}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
