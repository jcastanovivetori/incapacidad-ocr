#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Frente adversario: romper las reglas de tiempos y el motor de veredicto.

NO ejecuta OCR (el corpus ya esta extraido y hay una medicion corriendo en la
maquina). Ataca DIRECTO las dos funciones que hoy son el unico "motor de tiempos"
del repo:

  * ``extract.normalizar_fechas()``  -> reconciliacion inicio/fin/dias
  * ``erp.mapear_a_staging()``       -> veredicto (problemas / requiere_revision /
                                        campos_faltantes) que ve el auxiliar

Cada caso declara ENTRADA -> ESPERADO -> OBTENIDO. El "esperado" se deriva de
CLAUDE.md §Reglas de dominio (fechavencimiento = inicio + dias no inclusivo,
dias validos 1..540, fecha_inicio_calculada es aviso NO bloqueante) y del pedido
del cliente ("valida los tiempos, para cuando no coincida dejalo de tal forma
que sea escalable").

Sin PII: cedulas/nombres son sinteticos ("00000000"/"PACIENTE DE PRUEBA").
"""
from __future__ import annotations

import json
import sys
import traceback
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

from incapacidad_ocr import erp  # noqa: E402
from incapacidad_ocr.extract import normalizar_fechas  # noqa: E402

RESULTADOS: list[dict[str, Any]] = []


def _inc(**campos: Any) -> dict[str, Any]:
    """Envoltorio minimo con la forma que produce ``process()``."""
    return {"incapacidad": {"incapacidad": dict(campos)}}


def caso(nombre: str, entrada: Any, esperado: str, obtenido: Any, ok: bool | None = None,
         nota: str = "") -> None:
    RESULTADOS.append({
        "caso": nombre, "entrada": entrada, "esperado": esperado,
        "obtenido": obtenido, "ok": ok, "nota": nota,
    })
    marca = {True: "OK  ", False: "FALLA", None: "??  "}[ok]
    print(f"[{marca}] {nombre}\n        entrada : {entrada}\n"
          f"        esperado: {esperado}\n        obtenido: {obtenido}")
    if nota:
        print(f"        nota    : {nota}")


def _norm(campos: dict[str, Any]) -> Any:
    """normalizar_fechas sobre {'incapacidad': campos}; devuelve dict o la excepcion."""
    rec = {"incapacidad": dict(campos)}
    try:
        return normalizar_fechas(rec)["incapacidad"]
    except Exception as exc:  # noqa: BLE001 — queremos ver la caida
        return {"_EXCEPCION": f"{type(exc).__name__}: {exc}",
                "_traza": traceback.format_exc(limit=3).splitlines()[-3:]}


def _mapa(campos: dict[str, Any], **kw: Any) -> Any:
    """mapear_a_staging con lookups nulos (degrada sin BD); devuelve mapeo o excepcion."""
    res = _inc(**campos) if not isinstance(campos, str) else campos
    try:
        return erp.mapear_a_staging(res, "WHATSAPP", erp.LookupsNulos(), **kw)
    except Exception as exc:  # noqa: BLE001
        return {"_EXCEPCION": f"{type(exc).__name__}: {exc}",
                "_traza": traceback.format_exc(limit=4).splitlines()[-3:]}


def _resumen(m: Any) -> Any:
    if "_EXCEPCION" in m:
        return m
    r = m["row"]
    return {
        "fechainicio": r["fechainicio"], "Numerodias": r["Numerodias"],
        "fechavencimiento": r["fechavencimiento"], "problemas": m["problemas"],
        "requiere_revision": m["requiere_revision"],
        "fecha_inicio_calculada": m["fecha_inicio_calculada"],
        "confianza_ocr": r["confianza_ocr"],
    }


# ===================================================================== #
# A. Contextos degenerados sobre normalizar_fechas()
# ===================================================================== #
print("\n=== A. normalizar_fechas: contextos degenerados ===\n")

caso("A1 todo nulo",
     {"fecha_inicio": None, "fecha_fin": None, "dias": None},
     "no explota; deja los tres nulos",
     _norm({"fecha_inicio": None, "fecha_fin": None, "dias": None}))

caso("A2 campos ausentes (dict vacio)",
     {}, "no explota", _norm({}))

caso("A3 fecha imposible 2026-02-30 + dias 3",
     {"fecha_inicio": "2026-02-30", "dias": 3},
     "descarta la fecha invalida y SEÑALA que la fecha leida es invalida",
     _norm({"fecha_inicio": "2026-02-30", "dias": 3}))

caso("A4 dias = 0",
     {"fecha_inicio": "2026-06-01", "dias": 0},
     "dias fuera de 1..540 -> se ignora y se SEÑALA",
     _norm({"fecha_inicio": "2026-06-01", "dias": 0}))

caso("A5 dias negativo",
     {"fecha_inicio": "2026-06-01", "dias": -5},
     "dias fuera de rango -> se ignora y se SEÑALA",
     _norm({"fecha_inicio": "2026-06-01", "dias": -5}))

caso("A6 dias enorme (99999) con inicio y fin coherentes",
     {"fecha_inicio": "2026-06-01", "fecha_fin": "2026-06-10", "dias": 99999},
     "SEÑALA la incoherencia (doc dice 99999, fechas dicen 10)",
     _norm({"fecha_inicio": "2026-06-01", "fecha_fin": "2026-06-10", "dias": 99999}))

caso("A7 fin ANTERIOR al inicio, con dias",
     {"fecha_inicio": "2026-06-10", "fecha_fin": "2026-06-01", "dias": 3},
     "SEÑALA fin<inicio (senal de alteracion), no lo arregla en silencio",
     _norm({"fecha_inicio": "2026-06-10", "fecha_fin": "2026-06-01", "dias": 3}))

caso("A8 fin ANTERIOR al inicio, SIN dias",
     {"fecha_inicio": "2026-06-10", "fecha_fin": "2026-06-01"},
     "SEÑALA fin<inicio conservando ambas fechas leidas",
     _norm({"fecha_inicio": "2026-06-10", "fecha_fin": "2026-06-01"}))

caso("A9 dias como str '5' (tipos mezclados)",
     {"fecha_fin": "2026-06-10", "dias": "5"},
     "inicio = fin-(5-1) = 2026-06-06 + fecha_inicio_calculada=True",
     _norm({"fecha_fin": "2026-06-10", "dias": "5"}))

caso("A10 dias como str con espacios ' 5 '",
     {"fecha_fin": "2026-06-10", "dias": " 5 "},
     "igual que A9 (mismo criterio que erp._num_dias, que si hace strip)",
     _norm({"fecha_fin": "2026-06-10", "dias": " 5 "}))

caso("A11 dias como float 5.0",
     {"fecha_fin": "2026-06-10", "dias": 5.0},
     "igual que A9 (5 dias) o bien SEÑALAR tipo no soportado",
     _norm({"fecha_fin": "2026-06-10", "dias": 5.0}))

caso("A12 dias booleano True (bool ES int en Python)",
     {"fecha_inicio": "2026-06-01", "fecha_fin": "2026-06-10", "dias": True},
     "True no es un numero de dias -> ignorar y SEÑALAR",
     _norm({"fecha_inicio": "2026-06-01", "fecha_fin": "2026-06-10", "dias": True}))

caso("A13 dias str NO numerico 'DOS'",
     {"fecha_fin": "2026-06-10", "dias": "DOS"},
     "no explota; dias no evaluable",
     _norm({"fecha_fin": "2026-06-10", "dias": "DOS"}))

caso("A14 dias str digito UNICODE no decimal '\\u00b2' (superindice 2)",
     {"fecha_inicio": "2026-06-01", "dias": "\u00b2"},
     "no explota (isdigit() es True pero int() revienta)",
     _norm({"fecha_inicio": "2026-06-01", "dias": "\u00b2"}))

caso("A15 fechas como int (tipo mezclado donde se espera str)",
     {"fecha_inicio": 20260601, "fecha_fin": 20260610, "dias": 10},
     "no explota; fechas no evaluables",
     _norm({"fecha_inicio": 20260601, "fecha_fin": 20260610, "dias": 10}))

def _norm_crudo(rec: Any) -> Any:
    try:
        return normalizar_fechas(rec)
    except Exception as exc:  # noqa: BLE001
        return {"_EXCEPCION": f"{type(exc).__name__}: {exc}"}


caso("A16 'incapacidad' no es dict (lista)",
     {"incapacidad": [1, 2]}, "no explota (guarda isinstance)",
     _norm_crudo({"incapacidad": [1, 2]}),
     nota="deberia estar guardado por el isinstance de extract.py:1134")

caso("A17 año bisiesto: 2028-02-27 + 3 dias",
     {"fecha_inicio": "2028-02-27", "dias": 3},
     "fin = 2028-02-29 (2028 es bisiesto)",
     _norm({"fecha_inicio": "2028-02-27", "dias": 3}))

caso("A18 año NO bisiesto: 2026-02-27 + 3 dias",
     {"fecha_inicio": "2026-02-27", "dias": 3},
     "fin = 2026-03-01",
     _norm({"fecha_inicio": "2026-02-27", "dias": 3}))

caso("A19 cambio de año: 2026-12-30 + 5 dias",
     {"fecha_inicio": "2026-12-30", "dias": 5},
     "fin = 2027-01-03",
     _norm({"fecha_inicio": "2026-12-30", "dias": 5}))

caso("A20 fin+dias sin inicio cruzando año: fin 2027-01-02, dias 5",
     {"fecha_fin": "2027-01-02", "dias": 5},
     "inicio = 2026-12-29, fecha_inicio_calculada=True",
     _norm({"fecha_fin": "2027-01-02", "dias": 5}))

caso("A21 limite 540 exacto (inicio+dias)",
     {"fecha_inicio": "2026-01-01", "dias": 540},
     "fin = 2027-06-24 (540 inclusivo) y dias se conserva",
     _norm({"fecha_inicio": "2026-01-01", "dias": 540}))

caso("A22 limite 541 (fuera de rango) con inicio",
     {"fecha_inicio": "2026-01-01", "dias": 541},
     "dias fuera de rango -> ignorar y SEÑALAR",
     _norm({"fecha_inicio": "2026-01-01", "dias": 541}))

caso("A23 span de 541 dias por fechas, sin dias leidos",
     {"fecha_inicio": "2026-01-01", "fecha_fin": "2027-06-25"},
     "span 541 > 540 -> SEÑALAR span fuera de rango",
     _norm({"fecha_inicio": "2026-01-01", "fecha_fin": "2027-06-25"}),
     nota="diff=540 pasa el saneo (0<=540<=540) pero dias=541 no pasa 1..540")

caso("A24 inicio == fin, sin dias",
     {"fecha_inicio": "2026-06-01", "fecha_fin": "2026-06-01"},
     "dias = 1",
     _norm({"fecha_inicio": "2026-06-01", "fecha_fin": "2026-06-01"}))

caso("A25 fecha con formato ISO 'semana' 2026-W23-1 (basura que ISO acepta)",
     {"fecha_inicio": "2026-W23-1", "dias": 3},
     "no aceptar una fecha que ningun documento imprime; o al menos SEÑALAR",
     _norm({"fecha_inicio": "2026-W23-1", "dias": 3}))

caso("A26 CONTRADICCION fuerte: inicio+fin+dias los tres leidos e incompatibles",
     {"fecha_inicio": "2026-06-01", "fecha_fin": "2026-06-30", "dias": 3},
     "SEÑALAR incoherencia (30 dias impresos vs 3) -> a revision humana",
     _norm({"fecha_inicio": "2026-06-01", "fecha_fin": "2026-06-30", "dias": 3}))

# ===================================================================== #
# B. Veredicto de mapear_a_staging() con esos mismos contextos
# ===================================================================== #
print("\n=== B. mapear_a_staging: veredicto al auxiliar ===\n")

caso("B1 contradiccion inicio/fin/dias, ya 'normalizada' por extract",
     "extract(A26) -> mapear",
     "requiere_revision=True con problema de coherencia de tiempos",
     _resumen(_mapa(_norm({"fecha_inicio": "2026-06-01", "fecha_fin": "2026-06-30",
                           "dias": 3}))),
     nota="entra el registro YA reescrito por normalizar_fechas")

caso("B2 contradiccion cruda (sin pasar por extract)",
     {"fecha_inicio": "2026-06-01", "fecha_fin": "2026-06-30", "dias": 3},
     "requiere_revision=True con problema de coherencia de tiempos",
     _resumen(_mapa({"fecha_inicio": "2026-06-01", "fecha_fin": "2026-06-30",
                     "dias": 3, "paciente": None})))

caso("B3 fecha de inicio CALCULADA (propiedad clave del frente)",
     {"fecha_fin": "2026-06-10", "dias": "5"},
     "NINGUNA regla dispara por el valor calculado: aviso, no violacion; "
     "y la confianza NO debe contar el inicio calculado como leido",
     _resumen(_mapa(_norm({"fecha_fin": "2026-06-10", "dias": "5"}))))

caso("B4 dias = 0 llega al veredicto",
     {"fecha_inicio": "2026-06-01", "dias": 0},
     "problema 'dias fuera de rango' o 'no se detecto'; nunca fila limpia",
     _resumen(_mapa({"fecha_inicio": "2026-06-01", "dias": 0})))

caso("B5 dias negativo llega al veredicto",
     {"fecha_inicio": "2026-06-01", "dias": -5},
     "problema explicito de dias invalidos",
     _resumen(_mapa({"fecha_inicio": "2026-06-01", "dias": -5})))

caso("B6 dias enorme 99999",
     {"fecha_inicio": "2026-06-01", "dias": 99999},
     "problema 'Numero de dias fuera de rango (=99999)'",
     _resumen(_mapa({"fecha_inicio": "2026-06-01", "dias": 99999})))

caso("B7 dias enorme via OVERRIDE del auxiliar (dias='99999')",
     "overrides={'dias':'99999'}",
     "problema de rango; fechavencimiento NO se calcula",
     _resumen(_mapa({"fecha_inicio": "2026-06-01"},
                    overrides={"dias": "99999"})))

caso("B8 override 'dias' con digito unicode no decimal ('\\u00b2')",
     "overrides={'dias':'\\u00b2'}  (llega por POST, lista blanca lo acepta)",
     "no 500: se ignora o se SEÑALA como valor invalido",
     _resumen(_mapa({"fecha_inicio": "2026-06-01"}, overrides={"dias": "\u00b2"})))

caso("B9 override 'fecha_inicio' imposible '2026-02-30'",
     "overrides={'fecha_inicio':'2026-02-30'}",
     "se descarta la fecha (no romper el INSERT) y se SEÑALA que era invalida",
     _resumen(_mapa({"dias": 3}, overrides={"fecha_inicio": "2026-02-30"})))

caso("B10 override 'fecha_fin' anterior al inicio",
     "overrides={'fecha_fin':'2026-05-01'} con inicio 2026-06-10",
     "problema explicito: fin anterior al inicio",
     _resumen(_mapa({"fecha_inicio": "2026-06-10", "dias": 3},
                    overrides={"fecha_fin": "2026-05-01"})))

caso("B11 fechavencimiento = inicio + dias (NO inclusivo)",
     {"fecha_inicio": "2026-06-01", "dias": 10},
     "fechainicio=2026-06-01, Numerodias=10, fechavencimiento=2026-06-11",
     _resumen(_mapa({"fecha_inicio": "2026-06-01", "dias": 10})))

def _mapa_crudo(res: Any, **kw: Any) -> Any:
    """Igual que _mapa pero recibe el resultado COMPLETO (formas que _inc no cubre)."""
    try:
        return _resumen(erp.mapear_a_staging(res, "WHATSAPP", erp.LookupsNulos(), **kw))
    except Exception as exc:  # noqa: BLE001
        return {"_EXCEPCION": f"{type(exc).__name__}: {exc}"}


caso("B12 'incapacidad' anidada es una LISTA no vacia (p.ej. lo devuelve el LLM)",
     "{'incapacidad': {'incapacidad': [1]}}",
     "no explota (degradar, como LookupsNulos)",
     _mapa_crudo({"incapacidad": {"incapacidad": [1]}}))

caso("B13 'paciente' es una LISTA no vacia",
     "{'incapacidad': {'paciente': ['X'], 'incapacidad': {...}}}",
     "no explota",
     _mapa_crudo({"incapacidad": {"paciente": ["X"],
                                  "incapacidad": {"fecha_inicio": "2026-06-01",
                                                  "dias": 3}}}))

caso("B14 resultado vacio total",
     "{}", "fila con problemas de campos faltantes, sin caida",
     _mapa_crudo({}))

caso("B15 dias float 5.0 (tipo mezclado)",
     {"fecha_inicio": "2026-06-01", "dias": 5.0},
     "5 dias, o problema explicito de tipo; no 'no se detecto'",
     _resumen(_mapa({"fecha_inicio": "2026-06-01", "dias": 5.0})))

caso("B16 dias True (bool)",
     {"fecha_inicio": "2026-06-01", "dias": True},
     "True no es un numero de dias -> SEÑALAR",
     _resumen(_mapa({"fecha_inicio": "2026-06-01", "dias": True})))

# ===================================================================== #
# C. Configuracion externa / severidades / reglas desactivables
# ===================================================================== #
print("\n=== C. escalabilidad y actualizacion (config externa) ===\n")

import importlib.util  # noqa: E402

_hay_modulo_reglas = any(
    importlib.util.find_spec(m) is not None
    for m in ("incapacidad_ocr.reglas", "incapacidad_ocr.reglas_tiempo",
              "incapacidad_ocr.validaciones", "incapacidad_ocr.motor")
)
_ficheros_config = sorted(
    p.name for p in RAIZ.rglob("*regla*")
    if p.is_file() and ".venv" not in str(p) and ".git" not in str(p)
)
caso("C1 existe un motor de reglas declarativo",
     "importlib.find_spec(incapacidad_ocr.{reglas,reglas_tiempo,validaciones,motor})",
     "un modulo con reglas DECLARADAS (añadir regla = añadir declaracion)",
     {"modulo_encontrado": _hay_modulo_reglas, "ficheros_*regla*": _ficheros_config})

caso("C2 severidades/umbrales configurables sin redespliegue",
     "buscar severidad GRAVE/MEDIA/LEVE y umbral 540 en config externa",
     "umbrales y severidades en config externa (json/yaml/env/BD)",
     {"540_hardcodeado_en": sorted(
         f"{p.name}:{i}" for p in (RAIZ / "incapacidad_ocr").glob("*.py")
         for i, l in enumerate(p.read_text(encoding="utf-8").splitlines(), 1)
         if "540" in l)})

caso("C3 severidad inexistente / regla desactivada",
     "config con severidad 'CATASTROFICA' o regla enabled=false",
     "el motor ignora la severidad desconocida y respeta el switch",
     "NO APLICABLE: no hay motor ni config; los 'problemas' son strings "
     "sin severidad, generados por 'if' inline en erp.mapear_a_staging")

caso("C4 dos reglas contradictorias",
     "regla X dice CUMPLE y regla Y dice VIOLA sobre el mismo campo",
     "el motor conserva ambas y gana la de mayor severidad (trazable)",
     "NO APLICABLE: no hay registro de reglas; la contradiccion hoy se "
     "resuelve por ORDEN DE ESCRITURA de los 'if' y se pierde el dato leido")

caso("C5 columnas para auditar lo LEIDO vs lo CALCULADO",
     "sql/init.sql lp_ausentismos_ia",
     "columnas fecha_fin_leida / dias_leidos (como cedula_leida)",
     {"columnas_*_leida*": [l.split()[0] for l in
                            (RAIZ / "sql" / "init.sql").read_text(encoding="utf-8").splitlines()
                            if "_leid" in l]})

# ===================================================================== #
salida = Path(__file__).with_name("resultados.json")
salida.write_text(json.dumps(RESULTADOS, ensure_ascii=False, indent=2, default=str),
                  encoding="utf-8")
print(f"\n--- {len(RESULTADOS)} casos -> {salida}")
