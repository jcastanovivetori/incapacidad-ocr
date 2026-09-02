#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Casos LEGITIMOS pero ATIPICOS que NO deben marcarse.

Texto 100% SINTETICO (cedulas/nombres/IPS inventados: sin PII), pero copiando el
LAYOUT que el OCR produce de verdad en cada formato del corpus (Colsubsidio,
NUEVA EPS, Clinica Medical, Sura, SYSNET/ESE, permiso por horas). Cada caso declara
lo que un auxiliar leeria en el papel; el script contrasta contra:

  (A) PRODUCCION: RuleBasedExtractor -> normalizar_fechas -> erp.mapear_a_staging
  (B) CANDIDATA : checks AF01..AF06 de senales/aritmetica_fechas/probe.py

Un caso PASA si (A) reproduce la tripleta del papel sin avisos de tiempos
innecesarios y (B) no emite ningun hallazgo.

Solo lectura del paquete. Sin red, sin BD (LookupsNulos), sin OCR.
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

import probe  # noqa: E402
from incapacidad_ocr import erp  # noqa: E402
from incapacidad_ocr.extract import RuleBasedExtractor, normalizar_fechas  # noqa: E402

# Avisos de mapear_a_staging que dependen de la BD (LookupsNulos los dispara
# siempre y no son del frente de tiempos).
BD = ("no encontrada en empleados", "catálogo", "catalogo", "EPS no identificada",
      "No se detectó el código de diagnóstico", "No se detectó la cédula")


def es_tiempo(p: str) -> bool:
    return not any(b in p for b in BD)


# --------------------------------------------------------------------------- #
# Los casos. `esperado` = lo que dice el PAPEL (lo que un humano transcribiria).
# --------------------------------------------------------------------------- #
CASOS: list[dict] = [
    # ---------------------------------------------------------------- 1 dia --
    {
        "id": "L01_UN_DIA_COLSUBSIDIO",
        "porque": "Incapacidad de 1 dia: inicio == fin. El caso mas comun de todos "
                  "y el que mas facil rompe una regla que asuma fin > inicio.",
        "esperado": {"inicio": "2026-06-10", "fin": "2026-06-10", "dias": 1},
        "texto": """CLINICA SINTETICA S.A.S.
NIT:800000000-0
Consecutivo: 0000000001
Nombre del Paciente
PACIENTE SINTETICO ALFA
Numero de documento 1.000.000.001
Fecha Ingreso a Consulta: 10/06/2026
Clase incapacidad: Enfermedad General
Tipo Incapacidad:
Inicial
Dias de Incapacidad:  1
UNO
Fecha Inicio Incapacidad:10/06/2026
Fecha Fin Incapacidad:
10/06/2026
Diagnostico Principal: J00
""",
    },
    # ------------------------------------------------- 1 dia, layout REAL R16 --
    {
        "id": "L02_UN_DIA_SURA_LAYOUT_OCR",
        "porque": "Mismo caso de 1 dia, pero con el layout que el OCR produce de "
                  "verdad en el certificado tipo Sura (columnas desordenadas, "
                  "'Duracion' sin valor al lado y el anio en la linea siguiente).",
        "esperado": {"inicio": "2026-06-09", "fin": "2026-06-09", "dias": 1},
        "texto": """Trabajador
Responsable
Profesional
Registro Medico
INFORMACION DELPROFESIONAL
Tipo Generacion
Fecha lnicio
Diagnostico principal
Fecha
Afiliado
CC1000000002 PACIENTE SINTETICO BETA
09/0/202607:4624
MARTES 09 DE/JUNIO Duracion
DE2026
GENERAL
intramural
Tipo de prestacion
Fecha Fin
MARTES09DE JUNIO
DE2026
INICIAL
""",
    },
    # ------------------------------------------------------------- prorroga --
    {
        "id": "L03_PRORROGA_DIA_SIGUIENTE",
        "porque": "Prorroga que arranca EXACTAMENTE el dia siguiente al fin de la "
                  "anterior (14/06 tras un 10..13/06). No hay solape: es legitima.",
        "esperado": {"inicio": "2026-06-14", "fin": "2026-06-16", "dias": 3},
        "texto": """CLINICA SINTETICA S.A.S.
NIT:800000000-0
Nombre del Paciente
PACIENTE SINTETICO GAMMA
Numero de documento 1.000.000.003
Tipo Incapacidad:
Prorroga
Prorroga: Si
Dias de Incapacidad:  3
TRES
Fecha Inicio Incapacidad:14/06/2026
Fecha Fin Incapacidad:
16/06/2026
Diagnostico Principal: M545
""",
        "antecedente": {"inicio": "2026-06-10", "fin": "2026-06-13", "dias": 4},
    },
    # -------------------------------------------------------- cruza fin de anio --
    {
        "id": "L04_CRUZA_FIN_DE_ANIO",
        "porque": "Incapacidad que empieza en 2026 y termina en 2027. Rompe cualquier "
                  "regla que compare el anio de las patas contra 'el anio del documento'.",
        "esperado": {"inicio": "2026-12-28", "fin": "2027-01-06", "dias": 10},
        "texto": """CLINICA SINTETICA S.A.S.
NIT:800000000-0
Fecha de Impresion: 28/12/2026
Nombre del Paciente
PACIENTE SINTETICO DELTA
Numero de documento 1.000.000.004
Fecha Ingreso a Consulta: 28/12/2026
Dias de Incapacidad:  10
DIEZ
Fecha Inicio Incapacidad:28/12/2026
Fecha Fin Incapacidad:
06/01/2027
Diagnostico Principal: A09
""",
    },
    # ------------------------------------------------ licencia de maternidad --
    {
        "id": "L05_MATERNIDAD_126_DIAS",
        "porque": "Licencia de maternidad de 126 dias (Ley 1822): duracion larga "
                  "legitima, cerca del tope de las reglas de 'dias razonables'.",
        "esperado": {"inicio": "2026-06-07", "fin": "2026-10-10", "dias": 126},
        "texto": """CLINICA SINTETICA MEDICAL DUARTE
NIT:800000000-0
LICENCIA DE MATERNIDAD
Paciente: PACIENTE SINTETICO EPSILON
Identificacion: 1000000005
Fecha de Emision: 07/06/2026
Duracion:
126
Fecha de Terminacion: 10/10/2026
Diagnostico(s): O80.0
""",
    },
    # -------------------------------------------- el OCR solo leyo UN campo --
    {
        "id": "L06_SOLO_UN_CAMPO_LEIDO",
        "porque": "Escaneo malo: el OCR solo rescata la fecha de inicio. Con una sola "
                  "pata NO se puede afirmar incoherencia -> tiene que ser NO_APLICA, "
                  "nunca 'sospechoso'.",
        "esperado": {"inicio": "2026-06-10", "fin": None, "dias": None},
        "texto": """CLNCA SNTETCA
Fecha Inicio Incapacidad:10/06/2026
lllll
""",
        "tolera_faltantes": True,
    },
    # ------------------------------------------------------------- bisiesto --
    {
        "id": "L07_ANIO_BISIESTO_29_FEB",
        "porque": "Incapacidad que termina el 29 de febrero de un anio bisiesto: "
                  "una validacion de calendario mal hecha la declara imposible.",
        "esperado": {"inicio": "2028-02-27", "fin": "2028-02-29", "dias": 3},
        "texto": """CLINICA SINTETICA S.A.S.
NIT:800000000-0
Nombre del Paciente
PACIENTE SINTETICO ZETA
Numero de documento 1.000.000.007
Dias de Incapacidad:  3
TRES
Fecha Inicio Incapacidad:27/02/2028
Fecha Fin Incapacidad:
29/02/2028
Diagnostico Principal: J039
""",
    },
    # ------------------------------------------- prosa con anio de 2 cifras --
    {
        "id": "L08_PROSA_ANIO_2_CIFRAS",
        "porque": "Formato de prosa (ESE/SYSNET): 'POR 3 DIAS DESDE EL 10-06-26 HASTA "
                  "EL 12-06-26'. Anio de 2 cifras, legitimo y frecuente.",
        "esperado": {"inicio": "2026-06-10", "fin": "2026-06-12", "dias": 3},
        "texto": """ESE HOSPITAL SINTETICO
Identificacion Interna: 890000000
Fechadelmpresion:10/06/202611:30:00
Paciente:CC1000000008-PACIENTE SINTETICO ETA
FechadeNacimiento:07/04/1995
Edad:31 ano(s), 2 mes(es), 3 dia(s)
Administradora:EPS SINTETICA
Dianostico:
N23X: COLICORENAL, NOESPECIFICADO
INCAPACIDADPOR:
SE DA INCAPACIDAD MEDICA POR 3 DIAS DESDE EL 10-06-26 HASTA EL 12-06-26
OBSERVACIONES:
""",
    },
    # ------------------------------------------------- NUEVA EPS (layout OCR) --
    {
        "id": "L09_NUEVA_EPS_LABELS_OCR",
        "porque": "Certificado NUEVA EPS tal como lo devuelve el OCR: rotulos en "
                  "bloque ('Fecha Inicio / Dias Incapacidad / Fecha termlnacion') con "
                  "la 'i' leida como 'l' y el valor de dias perdido por el OCR.",
        "esperado": {"inicio": "2026-06-10", "fin": "2026-06-11", "dias": 2},
        "texto": """nueva
eps
NUEVA EPS S.A
CERTIFICADO DE INCAPACIDAD O LICENCIA POR MATERNIDAD
NIT.900.156.264-2
CC-1000000009 PACIENTE SINTETICO THETA
Fecha Recepcidn
10/06/2026
Focha Expedicion
10/06/2026
Codigo REPS
685470367113
Fecha Inicio
Dlas Incapacidad
10/06/2026
Fecha termlnacion
11/06/2026
NO
R51X
Diagnostico Ppal
Contingencia
Enfermedad General
""",
    },
    # ------------------------------------- Clinica Medical: valor ANTES del rotulo --
    {
        "id": "L10_VALOR_ANTES_DEL_ROTULO",
        "porque": "Formato Clinica Medical: el OCR emite el VALOR antes de su ROTULO. "
                  "La pista de que el bloque esta desalineado es que lo que sigue al "
                  "rotulo 'Dias de Incapacidad:' es una FECHA, no un numero de dias.",
        "esperado": {"inicio": "2026-07-11", "fin": "2026-07-12", "dias": 2},
        "texto": """CLINICA SINTETICA S.A.S.
NIT:800000000-0 Cod.Habilitacion:110012215001
INCAPACIDAD EXTRAHOSPITALARIA
Nimero:
Fecha:
607712
Bogota D.c.
11/7/2026
Fecha y Hora Ing:
07:24
Admision:
11/7/2026
FechaEgreso:11/7/2026
Nombre del Paciente:
PACIENTE SINTETICO IOTA
Identificacion:
1000000010
Dx Principal de Egreso:
S80.1
Prorroga:No
Dias de Incapacidad:
11/7/2026
Fecha de Inicio de Incapacidad:
12/7/2026
Fecha Fin de Incapacidad:
Nombre del Medico:
MEDICO SINTETICO
""",
    },
    # ------------------------------------------- Sura a caballo entre 2 meses --
    {
        "id": "L11_SURA_DOS_MESES",
        "porque": "Certificado Sura legitimo cuyo rango cruza de mes (30/06 -> 03/07) "
                  "y cuyo OCR emite las celdas en orden invertido. El dia de la semana "
                  "impreso es correcto en el papel: si la sonda lo empareja por "
                  "POSICION, se lo atribuye al papel y marca un documento sano.",
        "esperado": {"inicio": "2026-06-30", "fin": "2026-07-03", "dias": 4},
        "texto": """Trabajador
Responsable
Profesional
INFORMACION DELPROFESIONAL
Tipo Generacion
Fecha lnicio
Diagnostico principal
Afiliado
CC1000000011 PACIENTE SINTETICO KAPPA
VIERNES 03 DE/JULIO Duracion
DE2026
CUATRO
Fecha Fin
MARTES30DE JUNIO
DE2026
INICIAL
""",
    },
    # --------------------------------------------------- permiso por HORAS --
    {
        "id": "L12_PERMISO_POR_HORAS",
        "porque": "Permiso de 4 HORAS dentro de un mismo dia. No tiene 'numero de "
                  "dias' impreso: exigirlo es un aviso que NUNCA se puede satisfacer.",
        "esperado": {"inicio": "2026-06-04", "fin": "2026-06-04", "dias": 1},
        "texto": """GESTION SEGURIDAD Y SALUD EN EL TRABAJO
FORMATO SOLICITUD DE PERMISO
PSF156-00
1.DATOSDELA SOLICITUD
FECHA DE
NOMBRECOMPLETODELSOLICITANTE
DOCUMENTO
SOLICITUD
EMPRESA
Paciente Sintetico Lambda
Empresa Sintetica
04
06
26
1000000012
2.TIPO DEPERMISO
X Remunerado
No Remunerado
Detalle:
3.DURACIONDELPERMISO
DiAS
HORAS
DESDE
HASTA
DESDE
HASTA
08:00 a.m.
12:00 m.
NUMERO TOTAL DE HORAS
4
""",
        "es_permiso_horas": True,
    },
    # ----------------------------------------- anio modal != anio del tramite --
    {
        "id": "L13_ANIO_MODAL_ES_UN_ANIO_MAL_LEIDO",
        "porque": "Documento legitimo cuyo anio de impresion el OCR lee mal DOS veces "
                  "(en el encabezado y en el pie: 2026 -> 2028; el corpus real ya trae "
                  "ese error en dos documentos). Entonces el anio que MAS se repite en "
                  "el texto no es el del tramite y una regla de 'anio atipico' por moda "
                  "se invierte: marca las patas CORRECTAS por raras.",
        "esperado": {"inicio": "2026-06-10", "fin": "2026-06-11", "dias": 2},
        "texto": """CLINICA SINTETICA S.A.S.
Fecha de Impreslon: 1006/2028
Nombre del Paciente
PACIENTE SINTETICO MU
Numero de documento 1.000.000.013
Fecha de nacimiento 11/12/1990
Dias de Incapacidad:  2
DOS
Fecha Inicio Incapacidad:10/06/2026
Fecha Fin Incapacidad:
11/06/2026
Diagnostico Principal: G43
Fecha de Impreslon:10/06/202817:08:27 Impreso por: SISTEMA
""",
    },
    # ---------------------------- NUEVA EPS con el rotulo de fin BIEN escrito --
    {
        "id": "L09B_NUEVA_EPS_ROTULO_LIMPIO",
        "porque": "Igual que L09 pero con 'Fecha terminacion' bien escrito, para "
                  "separar las dos causas: aunque el OCR NO se equivoque en la 'i', "
                  "el valor sigue perdiendose porque la ventana de busqueda del "
                  "rotulo de fin es mas corta que el rotulo vecino que hay en medio.",
        "esperado": {"inicio": "2026-06-10", "fin": "2026-06-11", "dias": 2},
        "texto": """nueva
NUEVA EPS S.A
eps
NIT. 900.156.264-2
CERTIFICADO DE INCAPACIDAD O LICENCIA POR MATERNIDAD
CC-1000000014 PACIENTE SINTETICO NU
Fecha Expedicion
10/06/2026
Fecha Recepcion
10/06/2026
Codigo REPS
685470367113
10/06/2026
Fecha Inicio
Fecha terminacion
Dias Incapacidad
11/06/2026
NO
A099
Diagnostico Ppal
Contingencia
Enfermedad General
""",
    },
    # --------------------------- Sura: OCR desordena dias y meses entre columnas --
    {
        "id": "L14_SURA_OCR_DESORDENA_COLUMNAS",
        "porque": "Certificado Sura legitimo (30/06 -> 03/07) en el que el OCR emite "
                  "los DIAS en un orden y los MESES en el otro. Al emparejar por "
                  "POSICION sale una fecha cuyo dia de la semana no cuadra, y el "
                  "desajuste (que es de LECTURA) se le atribuye al PAPEL.",
        "esperado": {"inicio": "2026-06-30", "fin": "2026-07-03", "dias": 4},
        "texto": """Trabajador
Responsable
Profesional
INFORMACION DELPROFESIONAL
Fecha lnicio
Fecha Fin
Diagnostico principal
Afiliado
CC1000000015 PACIENTE SINTETICO XI
MARTES 30
VIERNES 03
DE/JULIO
DE JUNIO
DE2026
Duracion
CUATRO
INICIAL
""",
    },
    # ------------- el MISMO caso de L10 pero con un OCR bueno: peor resultado --
    {
        "id": "L15_VALOR_ANTES_DEL_ROTULO_CON_DIAS",
        "porque": "Igual que L10 (valor antes del rotulo) pero con un escaneo BUENO: "
                  "el numero de dias SI se lee. Al haber inicio+dias, normalizar_fechas "
                  "re-deriva la fecha fin y la fila queda internamente COHERENTE... "
                  "corrida un dia entera. Resultado: cero avisos y un dato erroneo que "
                  "ninguna regla de tiempos puede detectar.",
        "esperado": {"inicio": "2026-07-11", "fin": "2026-07-12", "dias": 2},
        "texto": """CLINICA SINTETICA S.A.S.
NIT:800000000-0 Cod.Habilitacion:110012215001
INCAPACIDAD EXTRAHOSPITALARIA
Fecha:
11/7/2026
Fecha y Hora Ing: 07:24
Admision: 11/7/2026
FechaEgreso:11/7/2026
Nombre del Paciente:
PACIENTE SINTETICO OMICRON
Identificacion:
1000000016
Dx Principal de Egreso:
S80.1
Prorroga:No
Dias de Incapacidad: 2
11/7/2026
Fecha de Inicio de Incapacidad:
12/7/2026
Fecha Fin de Incapacidad:
Nombre del Medico:
MEDICO SINTETICO
""",
    },
]


def evaluar_caso(c: dict) -> dict:
    texto = c["texto"]
    rec = RuleBasedExtractor().extract(texto)
    normalizar_fechas(rec)
    res = {"incapacidad": rec, "texto_plano": texto, "ocr_backend": "sintetico",
           "extractor": "rule-based", "fuente": c["id"]}
    m = erp.mapear_a_staging(res, lookups=erp.LookupsNulos())
    inca = rec.get("incapacidad", {})
    ev = probe.evaluar(texto, {})

    esp = c["esperado"]
    obt = {"inicio": inca.get("fecha_inicio"), "fin": inca.get("fecha_fin"),
           "dias": inca.get("dias")}
    probs_t = [p for p in m["problemas"] if es_tiempo(p)]
    # El checkbox remunerado/no-remunerado NO es del frente de tiempos (CLAUDE.md lo
    # declara comportamiento esperado).
    probs_t = [p for p in probs_t if "remunerado" not in p]

    fallos: list[str] = []
    for k in ("inicio", "fin", "dias"):
        if c.get("tolera_faltantes") and esp[k] is None:
            continue
        if obt[k] != esp[k]:
            fallos.append(f"{k}: esperado {esp[k]} != obtenido {obt[k]}")
    if ev["hallazgos"]:
        fallos.append("checks AF que disparan: " + ",".join(h["check"] for h in ev["hallazgos"]))
    if probs_t and not c.get("tolera_faltantes"):
        fallos.append("avisos de tiempos innecesarios: " + "; ".join(probs_t))
    if inca.get("fecha_inicio_calculada") and esp["inicio"]:
        fallos.append("fecha_inicio_calculada=True aunque el papel imprime el inicio")

    return {
        "id": c["id"], "porque": c["porque"], "esperado": esp, "obtenido": obt,
        "fecha_inicio_calculada": inca.get("fecha_inicio_calculada"),
        "tipo_documento": rec.get("tipo_documento"),
        "fechavencimiento": m["row"]["fechavencimiento"],
        "Numerodias_row": m["row"]["Numerodias"],
        "problemas_tiempo": probs_t,
        "impresos_sonda": {k: ev["impresos"][k] for k in ("inicio", "fin", "dias")},
        "checks": [h["check"] for h in ev["hallazgos"]],
        "hallazgos": ev["hallazgos"], "motivo_no_aplica": ev["motivo_no_aplica"],
        "fallos": fallos, "ok": not fallos,
    }


def main() -> int:
    salida = [evaluar_caso(c) for c in CASOS]
    print("=" * 110)
    print("CASOS LEGITIMOS ATIPICOS (texto sintetico, sin PII) — ninguno deberia marcarse")
    print("=" * 110)
    for r in salida:
        print(f"\n[{'OK ' if r['ok'] else 'FALLA'}] {r['id']}")
        print(f"   papel      inicio={r['esperado']['inicio']} fin={r['esperado']['fin']} "
              f"dias={r['esperado']['dias']}")
        print(f"   pipeline   inicio={r['obtenido']['inicio']} fin={r['obtenido']['fin']} "
              f"dias={r['obtenido']['dias']} calc_inicio={r['fecha_inicio_calculada']} "
              f"venc={r['fechavencimiento']} tipo_doc={r['tipo_documento']}")
        print(f"   sonda      impreso={r['impresos_sonda']} checks={r['checks'] or '-'} "
              f"{r['motivo_no_aplica'] or ''}")
        if r["problemas_tiempo"]:
            print(f"   avisos     {r['problemas_tiempo']}")
        for f in r["fallos"]:
            print(f"   -> FALLA:  {f}")
    ok = sum(1 for r in salida if r["ok"])
    print("\n" + "=" * 110)
    print(f"RESULTADO: {ok}/{len(salida)} casos legitimos pasan sin marcarse")
    print("fallan: " + ", ".join(r["id"] for r in salida if not r["ok"]))
    with open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                           "casos_legitimos.json"), "w", encoding="utf-8") as fh:
        json.dump(salida, fh, ensure_ascii=False, indent=1)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
