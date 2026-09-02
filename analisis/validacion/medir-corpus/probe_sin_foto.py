"""Sonda: que dice el motor cuando el registro llega SIN la foto `tiempos_leidos`.

Sale de una discrepancia medida en el corpus (`agregar_motor.py`, seccion
`discrepancias_A_vs_B`): el MISMO documento F09 da

  * `REVISAR / T01_DURACION_VS_RANGO` (GRAVE) por la ruta de produccion (con foto), y
  * `COHERENTE`, puntaje 100, cobertura 0.85 leyendo el registro tal como quedo guardado.

Aqui se aisla la causa con dos casos minimos y sin PII, para que el hallazgo sea
reproducible sin el corpus:

  CASO 1 — fin COMPLETADO por la reconciliacion (el papel no imprimia fin).
     `normalizar_fechas` rellena `fecha_fin` = inicio + (dias-1) y NO deja ninguna marca
     (`fecha_inicio_calculada` es solo para el inicio; `fecha_fin_recalculada` solo se marca
     cuando habia un fin que NO cuadraba). Sin la foto, `valores_leidos()` toma ese fin
     derivado como EVIDENCIA: T01 pasa a CUMPLE (tautologia: la aritmetica que lo derivo
     garantiza que cuadra) y la cobertura del informe sube como si se hubiera comprobado el
     cruce duracion↔rango, que es justo lo que no se comprobo.

  CASO 2 — fin RE-DERIVADO y registro guardado por un pipeline que no dejo la marca
     (es literalmente el JSON de F09 en el corpus, extraido antes de que existiera la foto):
     el fin que contradecia los dias desaparece y el veredicto sale COHERENTE.

Ruta de produccion de hoy (processor → webapp/batch) NO pasa por aqui: `processor.run()`
guarda la foto y el front reenvia el `resultado` completo a `/api/mapear`. Lo que si pasa por
aqui es cualquier registro construido a mano o releido de disco (la propia API publica
`validar_registro` se documenta "para auditar un documento, para el CLI y para las pruebas",
y `/api/mapear` acepta el `resultado` que le manden).

Uso:
    <repo>/.venv/Scripts/python.exe probe_sin_foto.py
"""
from __future__ import annotations

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
HOY = date(2026, 9, 2)

sys.path.insert(0, str(REPO))

from incapacidad_ocr.extract import normalizar_fechas  # noqa: E402
from incapacidad_ocr.validacion_temporal import (  # noqa: E402
    CLAVE_SNAPSHOT, config_por_defecto, snapshot_leidos, validar_registro,
)

CFG = config_por_defecto()


def fila(inf: dict) -> str:
    t01 = next(r for r in inf["reglas"] if r["codigo"] == "T01_DURACION_VS_RANGO")
    t11 = next(r for r in inf["reglas"] if r["codigo"] == "T11_FIN_REESCRITO_SIN_EVIDENCIA")
    leido = inf["evidencia"]["leido"]
    return (f"veredicto={inf['veredicto']:9s} pts={inf['puntaje_coherencia']:3d} "
            f"cobertura={inf['resumen']['cobertura']:.2f} "
            f"T01={t01['estado']:12s} T11={t11['estado']:6s} "
            f"leido(inicio→fin/dias)={leido['fecha_inicio']}→{leido['fecha_fin']}/{leido['dias']}")


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        pass
    out = {}

    # ---------------- CASO 1: fin COMPLETADO (el papel no traia fecha fin) ----------------
    # Entrada: un documento que solo imprime inicio y dias (es la mitad del corpus).
    base = {"fecha_inicio": "2026-06-01", "fecha_fin": None, "dias": 5}
    con_foto = {"incapacidad": dict(base)}
    con_foto["incapacidad"][CLAVE_SNAPSHOT] = snapshot_leidos(con_foto["incapacidad"])
    normalizar_fechas(con_foto)
    sin_foto = {"incapacidad": dict(base)}
    normalizar_fechas(sin_foto)
    reg_sin_foto = dict(sin_foto["incapacidad"])          # lo que se guardaria en disco/BD
    i_con, i_sin = validar_registro(con_foto, hoy=HOY, config=CFG), \
        validar_registro({"incapacidad": reg_sin_foto}, hoy=HOY, config=CFG)
    out["caso1_fin_completado"] = {
        "entrada": base, "registro_guardado": reg_sin_foto,
        "con_foto": {"veredicto": i_con["veredicto"], "cobertura": i_con["resumen"]["cobertura"],
                     "t01": next(r["estado"] for r in i_con["reglas"]
                                 if r["codigo"] == "T01_DURACION_VS_RANGO")},
        "sin_foto": {"veredicto": i_sin["veredicto"], "cobertura": i_sin["resumen"]["cobertura"],
                     "t01": next(r["estado"] for r in i_sin["reglas"]
                                 if r["codigo"] == "T01_DURACION_VS_RANGO")},
    }
    print("CASO 1 — el papel imprime inicio + dias, NO imprime fecha fin")
    print(f"   entrada          : {base}")
    print(f"   registro guardado: {reg_sin_foto}")
    print(f"   con foto  : {fila(i_con)}")
    print(f"   sin foto  : {fila(i_sin)}   <-- T01 CUMPLE sobre un fin que el papel no traia")

    # ---------------- CASO 2: fin RE-DERIVADO, registro sin marca ni foto ----------------
    # El papel imprime inicio + fin + dias y NO cuadran (es F09 del corpus).
    papel = {"fecha_inicio": "2026-06-05", "fecha_fin": "2026-07-06", "dias": 2}
    con_foto2 = {"incapacidad": dict(papel)}
    con_foto2["incapacidad"][CLAVE_SNAPSHOT] = snapshot_leidos(con_foto2["incapacidad"])
    normalizar_fechas(con_foto2)
    sin_foto2 = {"incapacidad": dict(papel)}
    normalizar_fechas(sin_foto2)
    reg2 = dict(sin_foto2["incapacidad"])
    # ... y el mismo registro sin la marca `fecha_fin_recalculada` (pipeline anterior).
    reg2_sin_marca = {k: v for k, v in reg2.items() if k != "fecha_fin_recalculada"}
    i2_con = validar_registro(con_foto2, hoy=HOY, config=CFG)
    i2_marca = validar_registro({"incapacidad": reg2}, hoy=HOY, config=CFG)
    i2_sin = validar_registro({"incapacidad": reg2_sin_marca}, hoy=HOY, config=CFG)
    print("\nCASO 2 — el papel imprime inicio + fin + dias y NO cuadran (=F09 del corpus)")
    print(f"   papel                       : {papel}")
    print(f"   con foto                    : {fila(i2_con)}")
    print(f"   sin foto, CON marca         : {fila(i2_marca)}")
    print(f"   sin foto, SIN marca         : {fila(i2_sin)}   <-- COHERENTE: la contradiccion desaparecio")
    out["caso2_fin_rederivado"] = {
        "papel": papel, "registro_con_marca": reg2, "registro_sin_marca": reg2_sin_marca,
        "con_foto": {"veredicto": i2_con["veredicto"], "codigos": i2_con["codigos"]},
        "sin_foto_con_marca": {"veredicto": i2_marca["veredicto"], "codigos": i2_marca["codigos"]},
        "sin_foto_sin_marca": {"veredicto": i2_sin["veredicto"], "codigos": i2_sin["codigos"],
                               "cobertura": i2_sin["resumen"]["cobertura"]},
    }

    # ---------------- CASO 3: el JSON real del corpus (F09), tal cual ----------------
    p = BASE / "ocr" / "falsas" / "FALSA-09.json"
    reg_corpus = json.loads(p.read_text(encoding="utf-8"))["incapacidad"]
    i3 = validar_registro(reg_corpus, hoy=HOY, config=CFG)
    print("\nCASO 3 — el JSON del corpus de F09 (d5b72739) tal como quedo guardado")
    print(f"   bloque incapacidad: {json.dumps(reg_corpus['incapacidad'], ensure_ascii=False)}")
    print(f"   {fila(i3)}")
    out["caso3_corpus_F09"] = {"archivo_json": p.name,
                               "veredicto": i3["veredicto"], "codigos": i3["codigos"],
                               "cobertura": i3["resumen"]["cobertura"],
                               "papel_dice": "Desde:05/06/2026 - Hasta:06/07/2026, 'Dias de incapacidad:02'"}

    (AQUI / "probe_sin_foto.json").write_text(json.dumps(out, ensure_ascii=False, indent=1),
                                             encoding="utf-8")
    print(f"\nDetalle: {AQUI / 'probe_sin_foto.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
