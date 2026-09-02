#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Sonda de la familia de señales **aritmetica_fechas** (cubre FECHAS_INCOHERENTES).

Qué hace
--------
Relee el TEXTO PLANO ya OCR-eado de `dataset-falsedad/ocr/<etiqueta>/*.json` y trata de
recuperar la **TRIPLETA IMPRESA** (fecha de inicio, fecha de fin, número de días) tal
como aparece en el papel, para después comprobar la invariante del negocio:

    (fin - inicio) + 1 == dias          # convención INCLUSIVA de extract.normalizar_fechas()
    fechavencimiento  == inicio + dias  # equivalente no-inclusiva del ERP (CLAUDE.md)

Por qué NO se usan los campos ya extraídos del JSON
---------------------------------------------------
Los JSON del dataset se produjeron con `IncapacidadProcessor`, que aplica
`extract.normalizar_fechas()`. Esa función **RE-DERIVA** la fecha de fin cuando
inicio+días son fiables y la fin no cuadra (extract.py: `df = di + timedelta(days=n-1)`),
y lo hace **sin dejar marca** (sólo existe el aviso `fecha_inicio_calculada`, para el
inicio). Es decir: el pipeline actual *borra la evidencia* justo del caso que esta
familia debe detectar. Por eso la sonda vuelve al texto y lee cada pata de la tripleta
con su PROCEDENCIA.

Regla anti-falso-positivo (la que pide el cliente)
--------------------------------------------------
El check SÓLO aplica cuando las TRES patas vienen IMPRESAS. Si una se calculó
(`fecha_inicio_calculada`) o simplemente no está en el papel, el resultado es
`NO_APLICA`, nunca "sospechoso".

Ejecutar
--------
    <repo>/.venv/Scripts/python.exe probe.py
    ... --con-nombres     # muestra el nombre real del archivo (contiene PII: úsalo local)

Salidas: una línea por documento en stdout + `resultados.json` (detalle completo).
100% local: sólo `re`/`datetime` y helpers del paquete `incapacidad_ocr` (sólo lectura).
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sys
from collections import Counter
from datetime import date, timedelta

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
if REPO not in sys.path:
    sys.path.insert(0, REPO)

# --- Reutilización del repo (NO se modifica nada del paquete) ------------------
from incapacidad_ocr.extract import (  # noqa: E402
    _DATE,
    _DMA_TRIPLET,
    _MESES_ES,
    _days_between,
    _extraer_detalle_incapacidad,
    _fecha_valida,
    _find_date,
    _norm_date,
)

DIAS_MIN, DIAS_MAX = 1, 540  # regla de dominio del repo (CLAUDE.md)

# --------------------------------------------------------------------------- #
# 1. Léxico y patrones
# --------------------------------------------------------------------------- #
# Etiquetas ESTRICTAS (copiadas de RuleBasedExtractor.extract, sin "fecha de
# emisión" ni "desde/hasta" sueltos: esos se leen por otras vías con su propia
# procedencia, para no fabricar tripletas mezclando semánticas distintas).
LBL_INICIO = r"(?:fecha\s*(?:de\s*)?[il]nic\w?(?:o|al|a)|[il]nic\w?(?:o|al|a)\s*(?:de\s*)?incapacidad)"
LBL_FIN = (
    r"(?:fecha\s*(?:de\s*)?(?:termina|final|fin)|(?:final|fin|termina\w*)\s*(?:de\s*)?incapacidad)"
)
LBL_EMISION = r"fecha\s*(?:de\s*)?emisi[oó]n"

# Números escritos en español (1..31 + decenas). El OCR de los certificados EPS
# imprime la duración como palabra ("-DOS", "14- CATORCE"): la palabra es
# AUTO-IDENTIFICABLE, a diferencia de un "02" suelto que puede ser el día del mes.
_UNIDADES = {
    "un": 1, "uno": 1, "una": 1, "dos": 2, "tres": 3, "cuatro": 4, "cinco": 5, "seis": 6,
    "siete": 7, "ocho": 8, "nueve": 9, "diez": 10, "once": 11, "doce": 12, "trece": 13,
    "catorce": 14, "quince": 15, "dieciseis": 16, "dieciséis": 16, "diecisiete": 17,
    "dieciocho": 18, "diecinueve": 19, "veinte": 20, "veintiuno": 21, "veintiun": 21,
    "veintidos": 22, "veintidós": 22, "veintitres": 23, "veintitrés": 23,
    "veinticuatro": 24, "veinticinco": 25, "veintiseis": 26, "veintiséis": 26,
    "veintisiete": 27, "veintiocho": 28, "veintinueve": 29,
}
_DECENAS = {
    "treinta": 30, "cuarenta": 40, "cincuenta": 50, "sesenta": 60, "setenta": 70,
    "ochenta": 80, "noventa": 90,
}
_NUM_PALABRA = dict(_UNIDADES)
_NUM_PALABRA.update(_DECENAS)
_NUM_PALABRA["ciento"] = 100
_NUM_PALABRA["cien"] = 100
_RE_NUM_PALABRA = re.compile(
    r"(?i)\b(" + "|".join(sorted(_NUM_PALABRA, key=len, reverse=True)) + r")\b"
    r"(?:\s*y\s*(" + "|".join(sorted(_UNIDADES, key=len, reverse=True)) + r"))?"
)

_DIAS_SEMANA = {
    "lunes": 0, "martes": 1, "miercoles": 2, "miércoles": 2, "jueves": 3, "viernes": 4,
    "sabado": 5, "sábado": 5, "domingo": 6,
}
# `(?!\d)` en vez de `\b`: el OCR pega el día al mes ("MARTES09DE JUNIO") y `\b`
# no existe entre '9' y 'D' (ambos son \w).
_RE_DIA_SEMANA_DIA = re.compile(
    r"(?i)\b(lunes|martes|mi[eé3]rcoles|jueves|viernes|s[aá]bado|domingo)\s*[.\-/]?\s*(\d{1,2})(?!\d)"
)

# Rótulos de "número de días". La 1ª alternativa admite la frase COMPLETA aunque el
# OCR la pegue ("DIASDEINCAPACIDAD"); la 3ª exige límites de palabra a ambos lados
# para que "DIAGNOSTICO" no case como "DIA" (falso positivo medido en el corpus).
LBL_DIAS = r"(?:d[ií]as?\s*(?:de\s*)?incapacidad|duraci[oó]n|\bd[ií]as?\b)"
H = r"[^\S\n]*"  # espacios horizontales: el valor debe estar en la MISMA línea


def _mes_tolerante(nombre: str) -> str:
    """Mes en español tolerando las confusiones OCR que el repo ya documenta
    (`0↔O`, `1↔I/l`): 'SEPT1EMBRE' == 'SEPTIEMBRE'. Genérico, no ad-hoc."""
    twins = {"i": "[i1l]", "l": "[l1i]", "o": "[o0]"}
    return "".join(twins.get(ch, ch) for ch in nombre)


_MES_ALT = "|".join(_mes_tolerante(m) for m in _MESES_ES)
# `(?:DE)?` opcional: el OCR pega la preposición al mes ("DESEPTIEMBRE", "DEJULIO")
# y entonces el mes no empieza en un límite de palabra.
_RE_MES = re.compile(r"(?i)\b(?:DE)?\s*(" + _MES_ALT + r")")
_RE_ANIO_DE = re.compile(r"(?i)\bDE\s*(\d{4})\b")
# "10 DE JULIO", "23 DE/JULIO", "04 DE\nSEPTIEMBRE" (día y mes contiguos)
_RE_DIA_DE_MES = re.compile(r"(?i)\b(\d{1,2})\s*DE[\s/.\-]*(" + _MES_ALT + r")\w*")


def _mes_num(txt: str) -> str | None:
    """Devuelve '01'..'12' para un nombre de mes posiblemente con ruido OCR."""
    limpio = txt.lower().translate(str.maketrans({"1": "i", "0": "o"}))
    for nombre, num in _MESES_ES.items():
        if limpio.startswith(nombre[:4]):
            return num
    return None


def _iso(y: int, m: int, d: int) -> str | None:
    return f"{y:04d}-{m:02d}-{d:02d}" if _fecha_valida(y, m, d) else None


def _norm_fecha_libre(txt: str) -> str | None:
    """dd/mm/aaaa, aaaa-mm-dd, dd-mmm-aa y dd-mm-aa (año de 2 cifras)."""
    f = _norm_date(txt)
    if f:
        return f
    m = re.fullmatch(_DMA_TRIPLET, txt.strip())
    if m:
        d, mo, y = m.groups()
        y = y if len(y) == 4 else f"20{y}"
        return _iso(int(y), int(mo), int(d))
    return None


# --------------------------------------------------------------------------- #
# 2. Lectores de la TRIPLETA IMPRESA (cada uno declara su procedencia)
# --------------------------------------------------------------------------- #
_RE_FECHA_O_TRIPLETE = f"(?:{_DATE}|{_DMA_TRIPLET})"


def _fecha_tras_etiqueta(texto: str, etiqueta: str, ventana: int = 8) -> str | None:
    """Fecha PEGADA a una etiqueta de prosa ('Desde: 05/06/2026'). Ventana corta a
    propósito: si hay que cruzar otra etiqueta, el valor no es de este campo."""
    m = re.search(rf"(?i){etiqueta}\s*(?:el\s*)?[:\-–]?\s*[^\d\n]{{0,{ventana}}}?{_RE_FECHA_O_TRIPLETE}",
                  texto)
    if not m:
        return None
    bruto = next((g for g in m.groups() if g and re.search(r"\d", g)), None)
    if bruto is None:
        return None
    # el grupo puede ser el del triplete partido en 3 → reconstruir
    if m.group(1):
        return _norm_fecha_libre(m.group(1))
    d, mo, y = m.group(2), m.group(3), m.group(4)
    y = y if len(y) == 4 else f"20{y}"
    return _iso(int(y), int(mo), int(d))


def _dias_impresos(texto: str) -> tuple[int | None, list[str], bool, list[int]]:
    """Número de días IMPRESO. Devuelve (valor, procedencias, hay_conflicto, crudos).

    Fuentes (todas ancladas a etiqueta, nunca un número suelto):
      a) 'Duración' + dígitos DESPUÉS del rótulo (tolera salto de línea corto).
      b) 'Días [de incapacidad]' + dígitos en la MISMA línea.
      c) prosa 'POR n DÍA(S)'.
      d) número ESCRITO EN PALABRA junto a 'Duración' (antes o después).

    Reglas duras contra falsos positivos:
      • el número no puede ser parte de una fecha (guardas `(?<![\\d/-])`/`(?![\\d/-])`),
        lo que evita leer '11' de 'Dias de Incapacidad:\\n11/7/2026'.
      • hacia ATRÁS del rótulo sólo se aceptan PALABRAS ('-DOS Duracion'), nunca
        dígitos: '...MARTES 09 DE JUNIO Duracion' daría dias=9 (falso positivo real
        medido en el corpus).
      • si dos fuentes discrepan → conflicto → la tripleta se considera no fiable.
    """
    NUM = r"(?<![\d/\-])(\d{1,3})(?![\d/\-])"
    hallados: list[tuple[int, str]] = []
    crudos: list[int] = []  # candidatos ANTES del filtro 1..540 (para AF03)

    # 'Duración' + dígitos: es el único rótulo al que se le permite el valor en la
    # línea siguiente ("Duracion:\n126", visto en Clínica Medical Duarte).
    m = re.search(rf"(?i)duraci[oó]n\b[^\d]{{0,12}}?(?<![\d/\-])(\d{{1,4}})(?![\d/\-])", texto)
    if m:
        crudos.append(int(m.group(1)))
        if len(m.group(1)) <= 3:
            hallados.append((int(m.group(1)), "duracion+digitos"))
    # 'Días [de incapacidad]' + dígitos en la MISMA línea (H = espacios horizontales).
    m = re.search(rf"(?i){LBL_DIAS}{H}[:\-]?[^\d\n]{{0,12}}?{NUM}", texto)
    if m:
        crudos.append(int(m.group(1)))
        hallados.append((int(m.group(1)), "dias+digitos"))
    # Prosa: sin `\b` antes de 'por' porque el OCR pega la frase entera
    # ("SEGENERAINCAPACIDADMEDICAPOR1DIAAPARTIRDE...").
    m = re.search(rf"(?i)por{H}{NUM}{H}d[ií]a", texto)
    if m:
        crudos.append(int(m.group(1)))
        hallados.append((int(m.group(1)), "prosa_por_n_dias"))
    for anc in re.finditer(r"(?i)duraci[oó]n", texto):
        for seg, quien in ((texto[max(0, anc.start() - 40):anc.start()], "palabra_antes"),
                           (texto[anc.end():anc.end() + 40], "palabra_despues")):
            mp = _RE_NUM_PALABRA.search(seg)
            if mp:
                val = _NUM_PALABRA[mp.group(1).lower()]
                if mp.group(2):
                    val += _UNIDADES[mp.group(2).lower()]
                crudos.append(val)
                hallados.append((val, f"duracion+{quien}"))
                break
    hallados = [(v, f) for v, f in hallados if DIAS_MIN <= v <= DIAS_MAX]
    if not hallados:
        return None, [], False, crudos
    valores = {v for v, _ in hallados}
    fuentes = [f for _, f in hallados]
    if len(valores) > 1:
        return None, fuentes, True, crudos
    return hallados[0][0], fuentes, False, crudos


def _fechas_escritas(texto: str) -> tuple[list[str], list[str], bool]:
    """Fechas escritas en palabras de los certificados EPS (formato Sura).

    El OCR pierde el layout de columnas y deja las piezas separadas:
        'JUEVES 04 DE' / 'MARTES 02' / <rótulos> / 'SEPT1EMBRE DE2025' / 'DESEPTIEMBRE DE 2025'
    Se ensamblan por POSICIÓN (día-k con mes-k y año-k, convención que ya usa
    `extract._fecha_inicio_fin_escrita`) y **se exige que el DÍA DE LA SEMANA impreso
    cuadre** con la fecha resultante: ese nombre es una suma de verificación gratuita
    que confirma que el ensamblado es correcto. Si algún día de la semana no cuadra,
    el ensamblado se declara NO fiable (sin coordenadas del OCR no se puede saber si
    la culpa es del orden de lectura o del papel).

    Devuelve (fechas_iso, dias_semana_no_cuadran, ensamblado_fiable).
    """
    if not re.search(r"(?i)fecha\s*[il]nici\w*", texto):
        return [], [], False
    dias_sem = _RE_DIA_SEMANA_DIA.findall(texto)          # [(nombre, dd), ...]
    sueltos = _RE_DIA_DE_MES.findall(texto)              # [(dd, mes), ...]
    meses = [g for g in _RE_MES.findall(texto)]
    anios = _RE_ANIO_DE.findall(texto)
    if not anios:
        anios = re.findall(r"\b(20\d{2})\b", texto)

    dias_num: list[int] = [int(d) for _, d in dias_sem]
    nombres_sem: list[str] = [n for n, _ in dias_sem]
    if not dias_num and sueltos:            # formato sin día de la semana impreso
        dias_num = [int(d) for d, _ in sueltos]
        meses = [m for _, m in sueltos]
        nombres_sem = []
    if len(dias_num) < 2 or len(meses) < len(dias_num) or not anios:
        return [], [], False
    # Si hay MÁS meses que días y no todos son el mismo mes, el emparejamiento por
    # posición no es defendible → se abandona (mejor NO_APLICA que un dato inventado).
    if len(meses) != len(dias_num) and len({_mes_num(m) for m in meses}) > 1:
        return [], [], False
    if len(set(anios)) == 1:
        anios = anios * len(dias_num)
    if len(anios) < len(dias_num):
        return [], [], False

    fechas: list[str] = []
    malos: list[str] = []
    for i, dd in enumerate(dias_num):
        mo = _mes_num(meses[i]) if i < len(meses) else None
        if not mo:
            return [], [], False
        f = _iso(int(anios[i]), int(mo), dd)
        if not f:
            return [], [], False
        fechas.append(f)
        if nombres_sem:
            esperado = date.fromisoformat(f).weekday()
            leido = _DIAS_SEMANA.get(
                nombres_sem[i].lower().replace("3", "e").replace("á", "a").replace("é", "e")
            )
            if leido is not None and leido != esperado:
                malos.append(f"{nombres_sem[i].upper()}!={f}")
    return fechas, malos, not malos


def leer_impresos(texto: str) -> dict:
    """Recupera la tripleta IMPRESA con procedencia. No inventa ni deriva nada."""
    out: dict = {
        "inicio": None, "fin": None, "dias": None,
        "fuente_inicio": None, "fuente_fin": None, "fuente_dias": [],
        "orden_incierto": False, "conflicto_dias": False, "conflicto_fechas": [],
        "dias_semana_malos": [], "fechas_invalidas": [], "dias_crudos": [],
    }

    # (a) Tabla "DETALLE DE LA INCAPACIDAD": las 3 patas en un bloque tabulado fiable.
    det = _extraer_detalle_incapacidad(texto)
    if det:
        out.update(inicio=det["fecha_inicio"], fin=det["fecha_fin"], dias=det["dias"],
                   fuente_inicio="tabla_detalle", fuente_fin="tabla_detalle",
                   fuente_dias=["tabla_detalle"])

    # (b) Etiquetas numéricas clásicas ("Fecha Inicio: 10/11/2025").
    if not out["inicio"]:
        f = _find_date(texto, LBL_INICIO)
        if f:
            out["inicio"], out["fuente_inicio"] = f, "etiqueta_inicio"
    if not out["fin"]:
        f = _find_date(texto, LBL_FIN)
        if f:
            out["fin"], out["fuente_fin"] = f, "etiqueta_fin"

    # (c) Prosa: "POR 4 DIAS DESDE EL 29-07-26 HASTA EL 01/07/29".
    pi = _fecha_tras_etiqueta(texto, r"(?:a\s*partir\s*de(?:l)?|desde)")
    pf = _fecha_tras_etiqueta(texto, r"hasta")
    for pata, valor, fuente in (("inicio", pi, "prosa_desde"), ("fin", pf, "prosa_hasta")):
        if valor is None:
            continue
        if out[pata] is None:
            out[pata], out[f"fuente_{pata}"] = valor, fuente
        elif out[pata] != valor:
            out["conflicto_fechas"].append(f"{pata}:{out['fuente_' + pata]}!={fuente}")

    # (d) Fechas escritas en palabras (certificados EPS tipo Sura).
    if not (out["inicio"] and out["fin"]):
        fechas, malos, fiable = _fechas_escritas(texto)
        out["dias_semana_malos"] = malos
        if fiable and len(fechas) >= 2:
            # sin coordenadas no se sabe qué celda es inicio y qué celda es fin →
            # se ordenan cronológicamente y se marca `orden_incierto`.
            a, b = sorted(fechas[:2])
            if not out["inicio"] and not out["fin"]:
                out.update(inicio=a, fin=b, fuente_inicio="escrita_sura",
                           fuente_fin="escrita_sura", orden_incierto=True)

    # (e) Respaldo del formato Clínica Medical Duarte: "FECHA DE EMISION" hace de
    #     inicio (el repo ya lo asume). Es un PROXY semántico → nivel MEDIA.
    if not out["inicio"] and out["fin"]:
        f = _find_date(texto, LBL_EMISION)
        if f:
            out["inicio"], out["fuente_inicio"] = f, "emision_como_inicio"

    d, fuentes, conflicto, crudos = _dias_impresos(texto)
    out["dias"] = out["dias"] if out["dias"] else d
    out["fuente_dias"] = fuentes or out["fuente_dias"]
    out["conflicto_dias"] = conflicto
    out["dias_crudos"] = crudos

    # Fechas con día/mes fuera de calendario escritas junto a un rótulo de fecha.
    for m in re.finditer(r"(?<![\d])(\d{1,2})[/\-](\d{1,2})[/\-](\d{2,4})(?![\d])", texto):
        dd, mo, yy = (int(x) for x in m.groups())
        yy = yy if yy > 99 else 2000 + yy
        if not _fecha_valida(yy, mo, dd) and not _fecha_valida(yy, dd, mo):
            out["fechas_invalidas"].append(m.group(0))
    return out


# --------------------------------------------------------------------------- #
# 3. Los CHECKS
# --------------------------------------------------------------------------- #
def evaluar(texto: str, meta: dict) -> dict:
    """Aplica los checks de la familia. Devuelve hallazgos + trazas de por qué."""
    imp = leer_impresos(texto)
    hall: list[dict] = []
    completa = bool(imp["inicio"] and imp["fin"] and imp["dias"])
    motivo_no_aplica = None
    if not completa:
        faltan = [k for k in ("inicio", "fin", "dias") if not imp[k]]
        motivo_no_aplica = "falta_impreso:" + "+".join(faltan)
    elif imp["conflicto_dias"] or imp["conflicto_fechas"]:
        completa = False
        motivo_no_aplica = "lectura_en_conflicto"

    # --- AF01: la tripleta impresa se contradice -----------------------------
    if completa:
        di = date.fromisoformat(imp["inicio"])
        df = date.fromisoformat(imp["fin"])
        span = (df - di).days + 1                     # inclusivo (extract.normalizar_fechas)
        desfase = span - imp["dias"]
        if desfase != 0:
            nivel = "MEDIA" if imp["fuente_inicio"] == "emision_como_inicio" else "ALTA"
            hall.append({
                "check": "AF01_TRIPLE_IMPRESA_INCOHERENTE", "nivel": nivel,
                "desfase_dias": desfase,
                "esperado_fin_inclusivo": (di + timedelta(days=imp["dias"] - 1)).isoformat()
                if 1 <= imp["dias"] <= DIAS_MAX else None,
                "clase": "off_by_one" if abs(desfase) == 1 else "grueso",
                # ¿se puede confirmar la contradicción SIN depender del OCR (capa de
                # texto embebida en el PDF)? True/False/None(=no se sabe: ese campo
                # no lo escribieron todos los shards de extracción del dataset).
                "confirmable_sin_ocr": meta.get("confirmable_sin_ocr"),
            })
        # --- AF02: rango invertido (sólo si sabemos qué celda es cuál) -------
        if span <= 0 and not imp["orden_incierto"]:
            hall.append({"check": "AF02_RANGO_INVERTIDO", "nivel": "ALTA", "span": span})

    # --- AF03: días impresos fuera de 1..540 --------------------------------
    # Se usan los candidatos CRUDOS de `_dias_impresos` (mismas guardas), no un
    # patrón más laxo: un patrón laxo leía "Duracion\nDE2026" -> 2026 y marcaba
    # como sospechoso un documento REAL (falso positivo medido y corregido).
    fuera = [v for v in imp["dias_crudos"] if not (DIAS_MIN <= v <= DIAS_MAX) and v < 1000]
    if fuera:
        hall.append({"check": "AF03_DIAS_FUERA_DE_RANGO", "nivel": "MEDIA", "valores": fuera})

    # --- AF04: el día de la semana impreso no cuadra con la fecha -----------
    if imp["dias_semana_malos"]:
        hall.append({"check": "AF04_DIA_SEMANA_INCONSISTENTE", "nivel": "MEDIA",
                     "detalle": imp["dias_semana_malos"]})

    # --- AF05: fecha fuera de calendario (31/02/2026) -----------------------
    if imp["fechas_invalidas"]:
        hall.append({"check": "AF05_FECHA_FUERA_DE_CALENDARIO", "nivel": "ALTA",
                     "detalle": imp["fechas_invalidas"]})

    # --- AF06: año atípico en una pata de la tripleta (heurístico) ----------
    # Sin `(?!\d)` al final: el OCR pega la hora al año ("29/07/202614:30:23") y con
    # la guarda de cola no se encontraba NINGÚN año en el documento.
    anios = [int(a) for a in re.findall(r"(?<!\d)((?:19|20)\d{2})", texto)]
    if anios:
        modal = Counter(anios).most_common(1)[0][0]
        raros = [f for f in (imp["inicio"], imp["fin"])
                 if f and abs(int(f[:4]) - modal) >= 2]
        if raros:
            hall.append({"check": "AF06_ANIO_ATIPICO", "nivel": "MEDIA",
                         "anio_modal": modal, "n_patas": len(raros)})

    return {"impresos": imp, "hallazgos": hall, "tripleta_completa": completa,
            "motivo_no_aplica": motivo_no_aplica}


# --------------------------------------------------------------------------- #
# 4. Corrida sobre el corpus
# --------------------------------------------------------------------------- #
def cargar_manifest() -> dict[str, dict]:
    filas: dict[str, dict] = {}
    with open(os.path.join(BASE, "manifest.csv"), encoding="utf-8-sig", newline="") as fh:
        for r in csv.DictReader(fh):
            filas[r["archivo"]] = r
    return filas


def cargar_jsons() -> list[dict]:
    docs = []
    raiz = os.path.join(BASE, "ocr")
    for carpeta in sorted(os.listdir(raiz)):
        d = os.path.join(raiz, carpeta)
        if not os.path.isdir(d):
            continue
        for nombre in sorted(os.listdir(d)):
            if nombre.endswith(".json"):
                with open(os.path.join(d, nombre), encoding="utf-8") as fh:
                    docs.append(json.load(fh))
    return docs


# Casos SINTÉTICOS (datos inventados, sin PII) para demostrar que cada check
# funciona aunque el corpus de 31 documentos no traiga ningún ejemplo suyo.
AUTOPRUEBA = [
    ("coherente inclusivo",
     "Fecha Inicio: 10/06/2026 Fecha Fin: 12/06/2026\nDias de Incapacidad: 3", []),
    ("off-by-one (emisor con convencion NO inclusiva)",
     "Fecha Inicio: 10/06/2026 Fecha Fin: 12/06/2026\nDias de Incapacidad: 2",
     ["AF01_TRIPLE_IMPRESA_INCOHERENTE"]),
    ("desfase grueso (mes alterado)",
     "Fecha Inicio: 05/06/2026 Fecha Fin: 06/07/2026\nDias de Incapacidad: 2",
     ["AF01_TRIPLE_IMPRESA_INCOHERENTE"]),
    ("solo fin+dias -> el pipeline CALCULA el inicio: NO es evidencia",
     "Fecha Fin: 12/06/2026\nDias de Incapacidad: 3", []),
    ("rango invertido",
     "Fecha Inicio: 12/06/2026 Fecha Fin: 10/06/2026\nDias de Incapacidad: 3",
     ["AF01_TRIPLE_IMPRESA_INCOHERENTE", "AF02_RANGO_INVERTIDO"]),
    ("dias fuera de 1..540",
     "Fecha Inicio: 10/06/2026\nDuracion: 600", ["AF03_DIAS_FUERA_DE_RANGO"]),
    ("dia de la semana que no cuadra (formato escrito)",
     "Fecha Inicio\nLUNES 02 DE SEPTIEMBRE DE 2025\nFecha Fin\nJUEVES 04 DE SEPTIEMBRE DE 2025\n"
     "Duracion TRES", ["AF04_DIA_SEMANA_INCONSISTENTE"]),
    ("fecha fuera de calendario",
     "Fecha Inicio: 31/02/2026 Fecha Fin: 05/03/2026\nDias de Incapacidad: 3",
     ["AF05_FECHA_FUERA_DE_CALENDARIO"]),
    ("dos lecturas de dias que se contradicen -> no se juzga",
     "Fecha Inicio: 10/06/2026 Fecha Fin: 12/06/2026\nDias de Incapacidad: 3\nDuracion: 7", []),
]


def autoprueba() -> int:
    fallos = 0
    print("AUTOPRUEBA con casos sinteticos (sin PII):")
    for nombre, texto, esperado in AUTOPRUEBA:
        res = evaluar(texto, {})
        obtenido = sorted(h["check"] for h in res["hallazgos"])
        ok = obtenido == sorted(esperado)
        fallos += 0 if ok else 1
        print(f"  [{'OK ' if ok else 'MAL'}] {nombre}\n        esperado={sorted(esperado)} "
              f"obtenido={obtenido} impreso={res['impresos']['inicio']}/"
              f"{res['impresos']['fin']}/{res['impresos']['dias']} "
              f"{res['motivo_no_aplica'] or ''}")
    print(f"  -> {len(AUTOPRUEBA) - fallos}/{len(AUTOPRUEBA)} casos sinteticos correctos\n")
    return fallos


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--con-nombres", action="store_true",
                    help="imprime el nombre real del archivo (contiene PII)")
    ap.add_argument("--solo-autoprueba", action="store_true")
    args = ap.parse_args()
    fallos_auto = autoprueba()
    if args.solo_autoprueba:
        return 1 if fallos_auto else 0

    man = cargar_manifest()
    docs = cargar_jsons()
    # ID estable y sin PII por documento: <F|R><nn> + 8 primeros del sha256.
    docs.sort(key=lambda d: (d.get("etiqueta", ""), d.get("archivo", "")))
    cont = Counter()
    resultados = []
    for d in docs:
        arch = d.get("archivo", "?")
        fila = man.get(arch, {})
        etiqueta = fila.get("etiqueta") or d.get("etiqueta") or "?"
        pre = "F" if etiqueta.startswith("fals") else "R"
        cont[pre] += 1
        sha = fila.get("sha256", "")
        pdfmeta = (d.get("estructura") or {}).get("pdf") or {}
        chars = pdfmeta.get("caracteres_texto_embebido")
        ext = (fila.get("ext") or "").lower()
        meta = {"confirmable_sin_ocr": False if ext in ("jpeg", "jpg", "png")
                else (None if chars is None else chars > 0)}
        res = evaluar(d.get("texto_plano") or "", meta)
        res.update(
            id=f"{pre}{cont[pre]:02d}", sha8=sha[:8], etiqueta=etiqueta,
            cuarentena=(fila.get("cuarentena") == "si"), archivo=arch,
            extension=fila.get("ext"),
            campos_pipeline=((d.get("incapacidad") or {}).get("incapacidad") or {}),
        )
        resultados.append(res)

    # ---------------- salida por documento ----------------
    print("=" * 118)
    print("SONDA aritmetica_fechas — una linea por documento "
          "(la tripleta se relee del texto, NO del JSON normalizado)")
    print("=" * 118)
    for r in resultados:
        etiq = "FALSA" if r["etiqueta"].startswith("fals") else "REAL "
        cuar = " [CUARENTENA]" if r["cuarentena"] else ""
        imp = r["impresos"]
        checks = ",".join(h["check"].split("_", 1)[0] for h in r["hallazgos"]) or "-"
        if r["hallazgos"]:
            veredicto = "SOSPECHOSO"
        elif r["tripleta_completa"]:
            veredicto = "COHERENTE"
        else:
            veredicto = "NO_APLICA"
        nombre = f"  ({r['archivo']})" if args.con_nombres else ""
        print(f"{r['id']} {r['sha8']} {etiq}{cuar:<14s} {veredicto:<11s} checks={checks:<10s} "
              f"impreso[inicio={imp['inicio']} fin={imp['fin']} dias={imp['dias']}] "
              f"fuentes[{imp['fuente_inicio']}/{imp['fuente_fin']}/{','.join(imp['fuente_dias']) or None}]"
              f"{'' if r['tripleta_completa'] else ' ' + str(r['motivo_no_aplica'])}{nombre}")
        for h in r["hallazgos"]:
            print(f"      -> {h['check']} nivel={h['nivel']} "
                  + " ".join(f"{k}={v}" for k, v in h.items() if k not in ("check", "nivel")))

    # ---------------- medición ----------------
    evaluables = [r for r in resultados if not r["cuarentena"]]
    falsas = [r for r in evaluables if r["etiqueta"].startswith("fals")]
    reales = [r for r in evaluables if not r["etiqueta"].startswith("fals")]
    marcada = lambda r: bool(r["hallazgos"])  # noqa: E731
    fdet = [r for r in falsas if marcada(r)]
    rmarc = [r for r in reales if marcada(r)]
    cuar_marcadas = [r for r in resultados if r["cuarentena"] and marcada(r)]

    print("\n" + "=" * 118)
    print("MEDICION (los documentos en CUARENTENA quedan FUERA de estos conteos)")
    print("=" * 118)
    print(f"corpus total                 : {len(resultados)} documentos "
          f"({sum(1 for r in resultados if r['etiqueta'].startswith('fals'))} falsas / "
          f"{sum(1 for r in resultados if not r['etiqueta'].startswith('fals'))} reales)")
    print(f"en cuarentena (excluidos)    : {sum(1 for r in resultados if r['cuarentena'])} "
          f"-> {[r['id'] for r in resultados if r['cuarentena']]}")
    print(f"FALSAS detectadas            : {len(fdet)}/{len(falsas)}  -> {[r['id'] for r in fdet]}")
    print(f"REALES marcadas (falsos pos.): {len(rmarc)}/{len(reales)}  -> {[r['id'] for r in rmarc]}")
    print(f"tripleta impresa COMPLETA    : falsas {sum(1 for r in falsas if r['tripleta_completa'])}"
          f"/{len(falsas)} · reales {sum(1 for r in reales if r['tripleta_completa'])}/{len(reales)}"
          "   (el resto = NO_APLICA por diseño)")
    print(f"cuarentena que SI dispara    : {[r['id'] for r in cuar_marcadas]}")
    por_check = Counter(h["check"] for r in evaluables for h in r["hallazgos"])
    for chk in ("AF01_TRIPLE_IMPRESA_INCOHERENTE", "AF02_RANGO_INVERTIDO",
                "AF03_DIAS_FUERA_DE_RANGO", "AF04_DIA_SEMANA_INCONSISTENTE",
                "AF05_FECHA_FUERA_DE_CALENDARIO", "AF06_ANIO_ATIPICO"):
        f_ = sum(1 for r in falsas for h in r["hallazgos"] if h["check"] == chk)
        r_ = sum(1 for r in reales for h in r["hallazgos"] if h["check"] == chk)
        print(f"   {chk:<34s} falsas={f_}  reales={r_}  (total corpus evaluable={por_check.get(chk, 0)})")
    print("\ndesfase (span_impreso - dias_impreso) por documento con tripleta completa:")
    for r in evaluables:
        if not r["tripleta_completa"]:
            continue
        imp = r["impresos"]
        span = (date.fromisoformat(imp["fin"]) - date.fromisoformat(imp["inicio"])).days + 1
        print(f"   {r['id']} {'FALSA' if r['etiqueta'].startswith('fals') else 'REAL '} "
              f"span={span:<5d} dias={imp['dias']:<4d} desfase={span - imp['dias']}")

    salida = os.path.join(os.path.dirname(os.path.abspath(__file__)), "resultados.json")
    with open(salida, "w", encoding="utf-8") as fh:
        json.dump({
            "familia": "aritmetica_fechas",
            "convencion": "inclusiva: (fin - inicio) + 1 == dias  (== extract.normalizar_fechas)",
            "medicion": {
                "falsas_detectadas": len(fdet), "falsas_totales": len(falsas),
                "reales_marcadas": len(rmarc), "reales_totales": len(reales),
                "cuarentena_excluida": [r["id"] for r in resultados if r["cuarentena"]],
                "cuarentena_que_dispara": [r["id"] for r in cuar_marcadas],
            },
            "documentos": resultados,
        }, fh, ensure_ascii=False, indent=2)
    print(f"\ndetalle completo (con nombres de archivo) -> {salida}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
