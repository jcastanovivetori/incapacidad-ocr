# -*- coding: utf-8 -*-
"""Ataques adicionales del frente 'regresion-real' (sin re-OCR).

1. FILA STAGING antes vs. ahora: es el dato que de verdad llega a la nomina
   (`erp.mapear_a_staging`, sin BD -> LookupsNulos). Cualquier campo de la fila que
   cambie es lo que hay que justificar.
2. RESPALDO HISTORICO de `_dias_por_etiqueta`: cuantas veces dispara de verdad sobre
   los 31 textos (la decision del cambio afirma que es inerte).
3. Valores CRUDOS (antes de `normalizar_fechas`) para saber que documento traia una
   fecha fin propia que NO cuadraba con los dias -> comprobar que
   `fecha_fin_recalculada` marca TODOS esos casos y solo esos.
4. COSTE: tiempo de extraccion por reglas antes vs. ahora (el batch procesa lotes).
5. Idempotencia: extraer dos veces el mismo texto da el mismo registro.
"""
from __future__ import annotations

import importlib.util
import json
import sys
import time
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
OCRDIR = BASE / "ocr"
AQUI = Path(__file__).resolve().parent

sys.path.insert(0, str(REPO))
from incapacidad_ocr import erp, numeros_es  # noqa: E402
from incapacidad_ocr.extract import RuleBasedExtractor as RBAhora  # noqa: E402
from incapacidad_ocr.extract import normalizar_fechas as norm_ahora  # noqa: E402

spec = importlib.util.spec_from_file_location("extract_antes2", AQUI / "extract_antes.py")
antes = importlib.util.module_from_spec(spec)
spec.loader.exec_module(antes)

CAMPOS_PII_FILA = {
    "paciente_leido", "cedula_leida", "Observaciones", "eps_leida", "cie10_leido",
    "diagnostico_leido", "medico_leido",
}


def textos():
    for sub in ("falsas", "falsa", "reales", "real"):
        for p in sorted((OCRDIR / sub).glob("*.txt")):
            yield f"{sub}/{p.stem}", p.read_text(encoding="utf-8")


def rec_antes(texto):
    r = antes.RuleBasedExtractor().extract(texto)
    antes.normalizar_fechas(r)
    return r


def rec_ahora(texto):
    r = RBAhora().extract(texto)
    norm_ahora(r)
    return r


def main() -> int:
    docs = list(textos())

    # ---------------- 1. fila staging ----------------
    print("== 1. FILA STAGING (erp.mapear_a_staging, LookupsNulos) antes vs. ahora ==")
    conteo = {}
    detalle = []
    for nombre, texto in docs:
        fa = erp.mapear_a_staging({"incapacidad": rec_antes(texto)})
        fb = erp.mapear_a_staging({"incapacidad": rec_ahora(texto)})
        difs = {}
        for k in sorted(set(fa) | set(fb)):
            if fa.get(k) != fb.get(k):
                difs[k] = (fa.get(k), fb.get(k))
        if difs:
            detalle.append((nombre, difs))
            for k in difs:
                conteo[k] = conteo.get(k, 0) + 1
    print("  campos de la fila que cambian:",
          json.dumps(conteo, ensure_ascii=False) if conteo else "(ninguno)")
    for nombre, difs in detalle:
        print(f"\n  {nombre}")
        for k, (va, vb) in difs.items():
            if k in CAMPOS_PII_FILA:
                print(f"    {k:26s} <valor omitido: PII>  cambio={va != vb}")
            else:
                print(f"    {k:26s} antes={va!r}  ahora={vb!r}")

    # ---------------- 2. respaldo historico ----------------
    print("\n== 2. RESPALDO HISTORICO de _dias_por_etiqueta: ¿dispara? ==")
    disparos = []
    for nombre, texto in docs:
        if numeros_es.duracion_en_texto(texto) is None:
            # el modulo no leyo nada -> el respaldo es lo unico que puede actuar
            import re

            from incapacidad_ocr.extract import _NUM_DIAS, _first
            d = _first(texto, rf"(?i)duraci[oó]n\b[^\d]{{0,10}}{_NUM_DIAS}")
            via = "duracion"
            if not d:
                d = _first(texto, rf"(?i)d[ií]as?(?:\s*de\s*incapacidad)?\b[^\d\n]{{0,15}}{_NUM_DIAS}")
                via = "dias"
            if d:
                disparos.append((nombre, via, d))
    print("  disparos del respaldo:", disparos or "(ninguno: es inerte en este corpus)")

    # ---------------- 3. crudos vs. fecha_fin_recalculada ----------------
    print("\n== 3. fecha_fin_recalculada: ¿marca TODOS los desacuerdos duracion<->fechas? ==")
    print(f"  {'documento':52s} {'d':>4s} {'fi_crudo':>11s} {'ff_crudo':>11s} {'esperado':>8s} {'flag':>6s}")
    fallos = []
    for nombre, texto in docs:
        crudo = RBAhora().extract(texto)
        ic = crudo["incapacidad"]
        d, fi, ff = ic.get("dias"), ic.get("fecha_inicio"), ic.get("fecha_fin")
        norm = rec_ahora(texto)["incapacidad"]
        flag = norm.get("fecha_fin_recalculada")
        # el flag debe ser True exactamente cuando habia fi, dias y un ff propio que
        # no cuadraba (df<fi o (df-fi)+1 != dias)
        esperado = False
        if fi and ff and d and 1 <= int(d) <= 540:
            from datetime import date
            try:
                a, b = date.fromisoformat(fi), date.fromisoformat(ff)
                esperado = (b < a) or ((b - a).days + 1 != int(d))
            except ValueError:
                esperado = False
        if esperado != bool(flag):
            fallos.append(nombre)
        if esperado or flag:
            print(f"  {nombre[:52]:52s} {str(d):>4s} {str(fi):>11s} {str(ff):>11s} "
                  f"{str(esperado):>8s} {str(flag):>6s}")
    print("  desajustes flag vs. esperado:", fallos or "(ninguno)")

    # ---------------- 4. coste ----------------
    print("\n== 4. COSTE de la extraccion por reglas (31 textos, 5 pasadas) ==")
    for etiqueta, fn in (("antes", antes.RuleBasedExtractor), ("ahora", RBAhora)):
        t0 = time.perf_counter()
        for _ in range(5):
            for _n, texto in docs:
                fn().extract(texto)
        dt = time.perf_counter() - t0
        print(f"  {etiqueta}: {dt*1000/5:.1f} ms por pasada de 31 documentos "
              f"({dt*1000/5/len(docs):.2f} ms/documento)")

    # ---------------- 5. idempotencia ----------------
    print("\n== 5. IDEMPOTENCIA (mismo texto -> mismo registro) ==")
    malos = [n for n, t in docs if json.dumps(rec_ahora(t), sort_keys=True, default=str)
             != json.dumps(rec_ahora(t), sort_keys=True, default=str)]
    print("  no deterministas:", malos or "(ninguno)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
