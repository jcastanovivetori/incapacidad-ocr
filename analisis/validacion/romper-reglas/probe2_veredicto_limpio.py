#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Parte 2 del frente adversario: demostrar el VEREDICTO INCORRECTO.

probe.py mostro que con ``LookupsNulos`` todos los casos salen
``requiere_revision=True`` — pero por cedula/CIE/EPS sin resolver, NO por los
tiempos. Aqui se usa un lookup que SI resuelve (como en produccion con MySQL)
para aislar la pregunta real:

    ¿un documento con TIEMPOS CONTRADICTORIOS llega al auxiliar marcado?

Sin PII: cedula "00000000", nombre "PACIENTE DE PRUEBA".
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

from incapacidad_ocr import erp  # noqa: E402
from incapacidad_ocr.extract import normalizar_fechas  # noqa: E402


class LookupsResuelve:
    """Todo resuelve (simula la BD con el empleado/CIE/EPS ya en catalogo)."""

    def empleado_por_cedula(self, cedula):
        return (7, "PACIENTE DE PRUEBA", "NUEVA EPS") if cedula else (None, None, None)

    def empleado_por_nombre(self, nombre):  # noqa: ARG002
        return None, None, None

    def id_empleado_por_cedula(self, cedula):  # noqa: ARG002
        return 7

    def diagnostico_por_codigo(self, codigo):
        return (11, "RINOFARINGITIS AGUDA") if codigo else (None, None)

    def id_entidad_por_nombre(self, nombre):
        return (3, 1, "NUEVA EPS") if nombre else (None, None, None)

    def documentos_requeridos(self, id_entidad, id_tipo):  # noqa: ARG002
        return []


def doc(**tiempos: Any) -> dict[str, Any]:
    """Documento completo (cedula/CIE/EPS OK) con los tiempos que se le pasen."""
    return {
        "incapacidad": {
            "paciente": {"documento_numero": "00000000", "nombre": "PACIENTE DE PRUEBA"},
            "entidad": {"eps": "NUEVA EPS"},
            "diagnostico": {"cie10": "J00", "descripcion": "RINOFARINGITIS AGUDA"},
            "incapacidad": dict(tiempos),
        },
        "texto_plano": "incapacidad medica enfermedad general",
    }


SALIDA: list[dict[str, Any]] = []


def caso(nombre: str, entrada: str, esperado: str, tiempos: dict[str, Any],
         por_extract: bool = True, overrides: dict[str, Any] | None = None) -> None:
    res = doc(**tiempos)
    if por_extract:
        # Igual que el pipeline real: process() aplica normalizar_fechas().
        res["incapacidad"] = normalizar_fechas(res["incapacidad"])
    m = erp.mapear_a_staging(res, "WHATSAPP", LookupsResuelve(), overrides=overrides)
    r = m["row"]
    obtenido = {
        "requiere_revision": m["requiere_revision"],
        "problemas": m["problemas"],
        "fechainicio": r["fechainicio"],
        "Numerodias": r["Numerodias"],
        "fechavencimiento": r["fechavencimiento"],
        "confianza_ocr": r["confianza_ocr"],
        "fecha_inicio_calculada": m["fecha_inicio_calculada"],
        "fecha_fin_tras_normalizar": res["incapacidad"]["incapacidad"].get("fecha_fin"),
        "observaciones": r["observaciones"],
    }
    SALIDA.append({"caso": nombre, "entrada": entrada, "esperado": esperado,
                   "obtenido": obtenido})
    print(f"--- {nombre}\n    entrada : {entrada}\n    esperado: {esperado}\n"
          f"    obtenido: {json.dumps(obtenido, ensure_ascii=False)}\n")


print("=== Documento COMPLETO (cedula/CIE/EPS resueltos) con tiempos rotos ===\n")

caso("D1 REFERENCIA sana",
     "inicio 2026-06-01, fin 2026-06-10, dias 10 (coherente)",
     "requiere_revision=False, venc=2026-06-11",
     {"fecha_inicio": "2026-06-01", "fecha_fin": "2026-06-10", "dias": 10})

caso("D2 fin IMPRESO no cuadra con dias (30 dias de span vs 3 dias)",
     "inicio 2026-06-01, fin 2026-06-30, dias 3",
     "requiere_revision=True + problema de coherencia de tiempos",
     {"fecha_inicio": "2026-06-01", "fecha_fin": "2026-06-30", "dias": 3})

caso("D3 fin ANTERIOR al inicio (con dias)",
     "inicio 2026-06-10, fin 2026-06-01, dias 3",
     "requiere_revision=True + problema 'fin anterior al inicio'",
     {"fecha_inicio": "2026-06-10", "fecha_fin": "2026-06-01", "dias": 3})

caso("D4 dias ENORME borrado por las fechas",
     "inicio 2026-06-01, fin 2026-06-10, dias 99999",
     "requiere_revision=True (el doc imprime 99999 dias)",
     {"fecha_inicio": "2026-06-01", "fecha_fin": "2026-06-10", "dias": 99999})

caso("D5 mismo caso SIN fin (la regla de rango si existe en erp)",
     "inicio 2026-06-01, dias 99999",
     "requiere_revision=True 'fuera de rango' — contraste con D4",
     {"fecha_inicio": "2026-06-01", "dias": 99999})

caso("D6 fin ANTERIOR al inicio, SIN dias",
     "inicio 2026-06-10, fin 2026-06-01",
     "problema 'fin anterior al inicio', NO 'no se detecto la fecha de inicio'",
     {"fecha_inicio": "2026-06-10", "fecha_fin": "2026-06-01"})

caso("D7 fecha de inicio IMPOSIBLE",
     "inicio 2026-02-30, dias 3",
     "problema 'fecha de inicio invalida', NO 'no se detecto'",
     {"fecha_inicio": "2026-02-30", "dias": 3})

caso("D8 dias = 0",
     "inicio 2026-06-01, fin 2026-06-01, dias 0",
     "problema explicito de dias invalidos (0 no es 1..540)",
     {"fecha_inicio": "2026-06-01", "fecha_fin": "2026-06-01", "dias": 0})

caso("D9 span de 541 dias (fuera del maximo legal)",
     "inicio 2026-01-01, fin 2027-06-25 (541 dias)",
     "problema de duracion fuera de rango",
     {"fecha_inicio": "2026-01-01", "fecha_fin": "2027-06-25"})

caso("D10 PROPIEDAD CLAVE: inicio CALCULADO no debe ser violacion",
     "fin 2026-06-10, dias 5 (sin inicio impreso)",
     "requiere_revision=False (aviso, no bloquea) pero confianza NO debe ser 1.0",
     {"fecha_fin": "2026-06-10", "dias": 5})

caso("D11 el AUXILIAR teclea un fin anterior al inicio",
     "override fecha_fin=2026-05-01 sobre inicio 2026-06-10, dias 3",
     "problema 'fin anterior al inicio'",
     {"fecha_inicio": "2026-06-10", "dias": 3}, por_extract=False,
     overrides={"fecha_fin": "2026-05-01"})

caso("D12 el AUXILIAR teclea dias que no cuadran con el fin",
     "override dias=3 sobre inicio 2026-06-01 / fin 2026-06-30",
     "problema de coherencia (el fin del doc sigue siendo 06-30)",
     {"fecha_inicio": "2026-06-01", "fecha_fin": "2026-06-30"}, por_extract=False,
     overrides={"dias": "3"})

caso("D13 fecha de inicio en el FUTURO lejano",
     "inicio 2030-01-01, dias 5 (hoy 2026-09)",
     "problema: incapacidad que empieza en el futuro",
     {"fecha_inicio": "2030-01-01", "dias": 5})

caso("D14 fecha de inicio absurdamente vieja",
     "inicio 1900-01-01, dias 5",
     "problema: fecha fuera de una ventana razonable",
     {"fecha_inicio": "1900-01-01", "dias": 5})

caso("D15 formato ISO 'semana' aceptado como fecha",
     "inicio 2026-W23-1, dias 3",
     "problema: la fecha no es una fecha de documento",
     {"fecha_inicio": "2026-W23-1", "dias": 3})

caso("D16 dias booleano True",
     "inicio 2026-06-01, fin 2026-06-10, dias True",
     "problema: dias no es un entero valido",
     {"fecha_inicio": "2026-06-01", "fecha_fin": "2026-06-10", "dias": True})

lim = Path(__file__).with_name("resultados_veredicto.json")
lim.write_text(json.dumps(SALIDA, ensure_ascii=False, indent=2, default=str),
               encoding="utf-8")

limpios = [c["caso"] for c in SALIDA if not c["obtenido"]["requiere_revision"]]
print("=== CASOS QUE SALEN 'LIMPIOS' (requiere_revision=False) ===")
for c in limpios:
    print("   ", c)
print(f"\n--- {len(SALIDA)} casos -> {lim}")
