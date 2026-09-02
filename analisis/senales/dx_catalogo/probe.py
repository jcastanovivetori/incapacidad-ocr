# -*- coding: utf-8 -*-
"""SONDA de la familia de senales `dx_catalogo` (Diagnostico contra catalogo CIE-10).

Cubre los checks DX_NO_LEIDO, DX_AUSENTE_EN_DOC, DX_FORMATO_LONGITUD,
DX_CAPITULO_INCOHERENTE (autonomos, 100% locales) y DX_INEXISTENTE /
DX_NOMBRE_DISTINTO (requieren el catalogo real `lpdiagnosticos` de ASTGU, que hoy
NO tenemos: degradan a NO_VERIFICABLE, nunca acusan).

Entradas (solo lectura):
  ../../manifest.csv          etiqueta / cuarentena / sha256 por documento
  ../../ocr/<etiqueta>/*.json texto_plano + campos extraidos + senales estructurales

Catalogo CIE-10 (OPCIONAL, si algun dia lo entregan):
  senales/dx_catalogo/catalogo/lpdiagnosticos.csv  con cabecera `codigo,descripcion`
  (o la ruta que indique la variable de entorno DX_CATALOGO)

Uso:
  python probe.py                # una linea por documento + resumen
  python probe.py --debug        # ademas: candidatos a CIE-10 y su puntaje
  python probe.py --json ruta    # vuelca los resultados a JSON

100% local: solo stdlib (re, csv, json, difflib, unicodedata). Sin red, sin IA externa.
NO escribe fuera de senales/dx_catalogo/.
"""

from __future__ import annotations

import argparse
import csv
import difflib
import json
import os
import re
import sys
import unicodedata
from pathlib import Path

AQUI = Path(__file__).resolve().parent
RAIZ = AQUI.parent.parent                      # dataset-falsedad/
MANIFEST = RAIZ / "manifest.csv"
DIR_OCR = RAIZ / "ocr"
CATALOGO_DEF = AQUI / "catalogo" / "lpdiagnosticos.csv"

# --------------------------------------------------------------------------- #
# 0. Convencion de codigo CIE-10 que asume esta familia
# --------------------------------------------------------------------------- #
# El cliente anoto en su tabla de motivos: "TODOS LOS DX SON DE 4 CARACTERES".
# Eso coincide con la tabla CIE-10 que MinSalud/SISPRO distribuye en Colombia y que
# se carga en `lpdiagnosticos`: letra + 2 digitos + 1 caracter, donde el 4o caracter
# es un digito (J06.9 -> J069) o la letra 'X' de relleno cuando la categoria no se
# subdivide (N23 -> N23X, A09 -> A09X, R51 -> R51X).
# CONSECUENCIA CLAVE: 'N23X' es VALIDO (4 caracteres) y 'N23' NO lo es.
LONGITUD_CATALOGO = 4

# El OCR confunde digitos con letras. Mismo mapa que incapacidad_ocr.extract._DIGIT_FIX.
_FIX = {"O": "0", "I": "1", "L": "1", "|": "1", "Z": "2", "S": "5"}
_CONF = "0123456789OoIiLlZzSs|"          # caracteres que pueden ser un digito
_SEP4 = ".,·-"                            # separador opcional antes del 4o caracter (J06.9)

# Nucleo del candidato: letra + 2 caracteres "posible-digito". El 4o caracter se
# resuelve a mano (ver _candidatos) porque el codigo suele venir PEGADO a la
# descripcion y un regex goloso convierte "G43 DOLOR..." en "G430".
_CAND = re.compile(r"(?<![A-Za-z0-9])([A-Za-z])[ ]?([" + _CONF + r"]{2})")

# Ancla de diagnostico, tolerante al OCR: "Diagnostico", "Dlagnostico", "Dianostico",
# "Diagndstico", "DX", "DXPrincipal", "CIE 10", "CIE1O".
_ANCLA = re.compile(
    r"(?i)(?:d[i1lí]a?g?n.{0,1}st[i1l]c|(?<![A-Za-z])dx|c[i1l]e\s*-?\s*1[o0])"
)
# Sub-etiquetas que indican DX PRINCIPAL (lo que se factura) vs DX secundario.
_ES_PRINCIPAL = re.compile(r"(?i)(principal|ppal|pral|princ|genera\s*la?s?\s*incapacidad|egreso|ingreso)")
_ES_SECUNDARIO = re.compile(r"(?i)(relacionad|secundari|\brel\b|otros?\s*diagn)")
# Cola de la etiqueta hasta los dos puntos ("Diagnostico que genera la incapacidad:").
_HASTA_DOSPUNTOS = re.compile(r"[^\n:]{0,45}:")
# El propio documento declara que no hay diagnostico impreso.
_NO_REGISTRA = re.compile(r"(?i)no\s*registra|no\s*aplica|sin\s*diagn")
# Patron de serial/fecha compacta ("D22M01A2006"): letra+2digitos seguidos de letra+digito.
_SERIAL = re.compile(r"^[A-Za-z][0-9]$")

VENTANA_ANTES = 70      # el codigo puede venir ANTES de la etiqueta (tablas)
VENTANA_DESPUES = 95
ADYACENTE = 14          # "Diagnostico Ppal: A099" -> codigo pegado a la etiqueta

TIPOS_SIN_DX = {"permiso", "vacaciones", "historia", "incapacidad_no"}


def _sin_tildes(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn")


def _norm_desc(s: str) -> str:
    """Normaliza una descripcion para comparar: sin tildes, sin espacios ni signos, MAYUS."""
    return re.sub(r"[^A-Z0-9]", "", _sin_tildes(s or "").upper())


# --------------------------------------------------------------------------- #
# 1. Lectura del codigo tal como esta IMPRESO (no se confia en el extractor)
# --------------------------------------------------------------------------- #
def _candidatos(texto: str):
    """Todos los candidatos a CIE-10 del texto, con su posicion y calidad.

    Paso a paso (determinista):
      1. `letra + 2 caracteres posible-digito` (regex `_CAND`), con la letra no
         precedida de alfanumerico (asi "C.CCED-06" no produce "C101").
      2. Normaliza los 2 del medio a digitos con el mapa de confusiones OCR y
         cuenta cuantas correcciones hizo (calidad de lectura).
      3. Resuelve el 4o caracter MIRANDO el texto, no con el regex:
           - digito real         -> es el 4o caracter
           - 'X'/'x'             -> relleno del catalogo colombiano (N23X) -> 4 caracteres
           - confusable (O,I,L,Z,S,|) -> solo si el codigo TERMINA ahi (el
             siguiente caracter no es letra); asi "G43 DOLOR" queda en 3 y no en "G430"
           - cualquier otra cosa -> el codigo impreso tiene 3 caracteres
      4. Descarta si justo despues viene otro digito (era un numero largo) o si
         parece un serial/fecha compacta ("D22M01A2006").
    """
    salida = []
    for m in _CAND.finditer(texto):
        letra, medio = m.group(1), m.group(2)
        correcciones = 0
        digitos = []
        for ch in medio:
            if ch.isdigit():
                digitos.append(ch)
            else:
                digitos.append(_FIX[ch.upper()])
                correcciones += 1
        fin = m.end()
        relleno = False
        # 3. cuarto caracter
        j = fin
        if j < len(texto) and texto[j] in _SEP4:
            j += 1
        c4 = texto[j] if j < len(texto) else ""
        sig = texto[j + 1] if j + 1 < len(texto) else ""
        if c4.isdigit():
            digitos.append(c4)
            fin = j + 1
        elif c4 in "Xx":
            relleno = True
            fin = j + 1
        elif c4 and c4.upper() in _FIX and not sig.isalpha():
            digitos.append(_FIX[c4.upper()])
            correcciones += 1
            fin = j + 1
        # 4. guardas
        if fin < len(texto) and texto[fin].isdigit():
            continue                                   # numero largo (cedula, consecutivo)
        if _SERIAL.match(texto[fin:fin + 2] or ""):
            continue                                   # "D22M01A2006"
        crudo = texto[m.start():fin]
        codigo = letra.upper() + "".join(digitos) + ("X" if relleno else "")
        salida.append({
            "crudo": crudo,
            "codigo": codigo,
            "longitud": len(codigo),
            "correcciones": correcciones,
            "relleno_x": relleno,
            # Sin ningun digito REAL casi siempre es una palabra ("COLS"->C015); solo se
            # acepta pegado a la etiqueta (la confusion 0<->O es universal: "Aoo" = A00).
            "digitos_reales": sum(1 for c in crudo if c.isdigit()),
            "ini": m.start(),
            "fin": fin,
        })
    return salida


def _anclas(texto: str):
    """Etiquetas de diagnostico con su peso: 2 = DX principal, 1 = generica, 0 = secundario."""
    out = []
    for m in _ANCLA.finditer(texto):
        cola = texto[m.end():m.end() + 34]
        if _ES_SECUNDARIO.search(cola):          # primero lo secundario: "DX Rel Ingreso"
            peso = 0
        elif _ES_PRINCIPAL.search(cola):
            peso = 2
        else:
            peso = 1
        # Fin efectivo de la etiqueta: hasta los dos puntos si estan en la misma linea.
        mm = _HASTA_DOSPUNTOS.match(texto, m.end())
        out.append({"ini": m.start(), "fin": m.end(),
                    "fin_etiqueta": mm.end() if mm else m.end(),
                    "peso": peso, "cola": cola})
    return out


def leer_dx(texto: str):
    """Localiza el DX principal impreso. Devuelve (mejor_candidato|None, debug)."""
    anclas = _anclas(texto)
    cands = _candidatos(texto)
    puntuados = []
    for c in cands:
        mejor = None
        for a in anclas:
            dist = c["ini"] - a["fin_etiqueta"]
            if dist > VENTANA_DESPUES or (c["ini"] - a["ini"]) < -VENTANA_ANTES:
                continue
            adj = 1 if 0 <= dist <= ADYACENTE else 0
            # sin digitos reales solo se acepta pegado a la etiqueta
            if c["digitos_reales"] == 0 and not adj:
                continue
            clave = (a["peso"], adj, -c["correcciones"], -abs(dist))
            if mejor is None or clave > mejor[0]:
                mejor = (clave, a)
        if mejor is None:
            continue
        c = dict(c)
        c["puntaje"] = mejor[0]
        c["ancla_peso"] = mejor[1]["peso"]
        c["ancla_cola"] = mejor[1]["cola"]
        c["dist"] = c["ini"] - mejor[1]["fin_etiqueta"]
        puntuados.append(c)
    puntuados.sort(key=lambda x: x["puntaje"], reverse=True)
    return (puntuados[0] if puntuados else None), puntuados


_OTRO_CAMPO = re.compile(r"(?i)(dx|d[i1l]a?g?n\w*|incapacidad|observ\w*|obse\w*|nota|tipo|dias|fecha|firma|medico)")


def _limpia_desc(s: str) -> str:
    s = re.sub(r"^\s*[-:.,·]\s*", "", s)
    s = re.sub(r"(?i)\b(dx|diagn\w*|incapacidad|observacion\w*|nota|tipo|dias)\b.*$", "", s)
    return s.strip(" -:.,|")


def descripcion_impresa(texto: str, cand: dict) -> str | None:
    """Descripcion que la IPS imprimio junto al codigo.

    Se busca en 3 sitios, en orden: (1) resto de la misma linea DESPUES del codigo,
    (2) la linea siguiente cuando NO parece un campo etiquetado nuevo (sin ':' al
    principio ni palabra de etiqueta), (3) lo que hay ANTES del codigo en la misma
    linea (hay formatos que imprimen "Sindrome febril en estudio r509").
    """
    if not cand:
        return None
    ini_linea = texto.rfind("\n", 0, cand["ini"]) + 1
    fin_linea = texto.find("\n", cand["fin"])
    fin_linea = len(texto) if fin_linea < 0 else fin_linea

    d = _limpia_desc(texto[cand["fin"]:fin_linea][:120])
    if len(re.sub(r"[^A-Za-z]", "", d)) >= 5:
        return d

    sig = texto[fin_linea + 1: fin_linea + 1 + 120].split("\n")[0]
    if ":" not in sig[:25] and not _OTRO_CAMPO.match(sig.strip()):
        d = _limpia_desc(sig)
        if len(re.sub(r"[^A-Za-z]", "", d)) >= 6:
            return d

    antes = texto[ini_linea:cand["ini"]]
    if _OTRO_CAMPO.search(antes):
        antes = antes.rsplit(":", 1)[-1] if ":" in antes else ""
    antes = _limpia_desc(antes)
    if len(re.sub(r"[^A-Za-z]", "", antes)) >= 6:
        return antes
    return None


# --------------------------------------------------------------------------- #
# 2. Lexico de capitulos CIE-10 (para el check autonomo de coherencia)
# --------------------------------------------------------------------------- #
# Palabra clave -> letras de capitulo CIE-10 donde ESA palabra es admisible.
# Derivado de los TITULOS oficiales de los capitulos CIE-10 (estructura publica),
# no del texto de este corpus. Multi-letra cuando el termino cabe en varios capitulos
# (p.ej. "INTOXICACION" puede ser A05 alimentaria o T intoxicacion por sustancia).
LEXICO_CAPITULO = {
    "COLERA": "A", "TUBERCULOSIS": "A", "DENGUE": "A", "PARASIT": "AB", "MICOSIS": "B",
    "GASTROENTERI": "AK", "DIARREA": "AK", "COLITIS": "AK", "AMEBIA": "A",
    "INFECCIONVIRAL": "AB", "VIRAL": "AB", "VIRUS": "AB", "SEPSIS": "A",
    "NEOPLASIA": "CD", "TUMOR": "CD", "CANCER": "C", "CARCINOMA": "C", "MALIGN": "C",
    "ANEMIA": "D", "LEUCOCIT": "D", "COAGULA": "D",
    "DIABETES": "E", "TIROID": "E", "OBESIDAD": "E", "DESNUTRICION": "E", "METABOL": "E",
    "DEPRES": "F", "ANSIEDAD": "F", "ESQUIZOFREN": "F", "TRASTORNOMENTAL": "F", "ESTRES": "FZ",
    "MIGRANA": "G", "JAQUECA": "G", "EPILEPS": "G", "NEURITIS": "G", "NEUROPATIA": "G",
    "PARALISIS": "G", "VERTIGOPOSICIONAL": "H",
    "CONJUNTIVITIS": "H", "OCULAR": "H", "CATARATA": "H", "MIOPIA": "H", "OJO": "H",
    "OTITIS": "H", "OIDO": "H", "HIPOACUSIA": "H",
    "HIPERTENSION": "I", "INFARTO": "I", "CARDIAC": "I", "VARICES": "I", "TROMBO": "I",
    "RINOFARINGITIS": "J", "FARINGITIS": "J", "AMIGDALITIS": "J", "RESPIRATOR": "J",
    "ASMA": "J", "BRONQUITIS": "J", "NEUMONIA": "J", "INFLUENZA": "J", "SINUSITIS": "J",
    "RINITIS": "J", "LARINGITIS": "J",
    "DIENTE": "K", "MUELA": "K", "DENTAL": "K", "CARIES": "K", "PULPITIS": "K",
    "GASTRITIS": "K", "ULCERAGASTRICA": "K", "HERNIA": "K", "APENDIC": "K", "HEMORROID": "K",
    "DERMATITIS": "L", "URTICARIA": "L", "ACNE": "L", "CELULITIS": "L", "PIEL": "L",
    "LUMBAGO": "M", "DORSALGIA": "M", "CERVICALGIA": "M", "ARTRITIS": "M", "ARTROSIS": "M",
    "TENDIN": "M", "OSTEO": "M", "SINOVITIS": "M", "MIALGIA": "M", "ESCOLIOSIS": "M",
    "BURSITIS": "M", "DISCO": "M",
    "RENAL": "N", "RINON": "N", "CISTITIS": "N", "URINARIA": "N", "VAGINITIS": "N",
    "PROSTAT": "N", "URETR": "N", "MENSTRUA": "N",
    "EMBARAZO": "O", "ABORTO": "O", "PARTO": "O", "CESAREA": "O", "PUERPERIO": "O",
    "GESTAC": "O", "MATERNIDAD": "O",
    "RECIENNACIDO": "P", "CONGENIT": "Q", "MALFORMACION": "Q",
    "FIEBRE": "R", "FEBRIL": "R", "CEFALEA": "GR", "MALESTAR": "R", "NAUSEA": "R",
    "VOMITO": "R", "DOLORABDOMINAL": "R", "DOLORENELPECHO": "R", "SINCOPE": "R",
    "TOS": "R", "MAREO": "R",
    "FRACTURA": "ST", "ESGUINCE": "ST", "TORCEDURA": "ST", "TRAUMA": "ST",
    "CONTUSION": "ST", "HERIDA": "ST", "LUXACION": "ST", "QUEMADURA": "T",
    "INTOXICACION": "AT", "ENVENENAMIENTO": "T", "MORDEDURA": "ST",
    "CONTROL": "Z", "EXAMEN": "Z", "SEGUIMIENTO": "Z", "ANTICONCEP": "Z",
}


def coherencia_capitulo(codigo: str, desc: str | None):
    """(veredicto, detalle). Compara la LETRA del codigo con el lexico de la descripcion."""
    if not codigo or not desc:
        return "no_verificable", "sin descripcion impresa"
    d = _norm_desc(desc)
    if len(d) < 6:
        return "no_verificable", "descripcion demasiado corta"
    letra = codigo[0]
    encontrados = [(k, v) for k, v in LEXICO_CAPITULO.items() if k in d]
    if not encontrados:
        return "no_verificable", "ninguna palabra del lexico de capitulos"
    if any(letra in v for _, v in encontrados):
        return "coherente", "+".join(k for k, _ in encontrados)[:60]
    esperadas = "".join(sorted({c for _, v in encontrados for c in v}))
    return "incoherente", "%s -> capitulo(s) %s, codigo es %s" % (
        "+".join(k for k, _ in encontrados)[:40], esperadas, letra)


# --------------------------------------------------------------------------- #
# 3. Catalogo CIE-10 (ausente hoy)
# --------------------------------------------------------------------------- #
def cargar_catalogo(ruta: Path | None):
    """{codigo_sin_punto: descripcion}. Devuelve None si no hay catalogo."""
    ruta = ruta or Path(os.environ.get("DX_CATALOGO", str(CATALOGO_DEF)))
    if not ruta.exists():
        return None, str(ruta)
    cat = {}
    with ruta.open(encoding="utf-8-sig", newline="") as fh:
        for fila in csv.DictReader(fh):
            cod = (fila.get("codigo") or "").replace(".", "").strip().upper()
            if cod:
                cat[cod] = (fila.get("descripcion") or "").strip()
    return cat, str(ruta)


# --------------------------------------------------------------------------- #
# 4. Los checks
# --------------------------------------------------------------------------- #
def evaluar(doc: dict, catalogo):
    """Aplica los checks de la familia a un documento ya OCReado."""
    texto = doc.get("texto_plano") or ""
    inc = doc.get("incapacidad") or {}
    tipo = (inc.get("tipo_documento") or "").lower()
    tipo_nombre = doc["_tipo_nombre"]
    res = {"checks": {}, "dx_leido": None, "dx_crudo": None, "desc_impresa": None}

    aplica = not (tipo in TIPOS_SIN_DX or tipo_nombre in TIPOS_SIN_DX)
    res["aplica"] = aplica

    cand, todos = leer_dx(texto)
    res["_cands"] = todos
    if cand:
        res["dx_leido"] = cand["codigo"]
        res["dx_crudo"] = cand["crudo"]
        res["correcciones_ocr"] = cand["correcciones"]
        res["desc_impresa"] = descripcion_impresa(texto, cand)

    C = res["checks"]

    # --- DX_AUSENTE_EN_DOC: el propio papel dice "NO REGISTRA" junto a la etiqueta.
    anclas = _anclas(texto)
    ausente = any(a["peso"] >= 1 and _NO_REGISTRA.search(a["cola"]) for a in anclas)
    if not aplica:
        C["DX_AUSENTE_EN_DOC"] = {"estado": "no_aplica", "detalle": "tipo de documento sin diagnostico"}
    elif ausente and cand is None:
        C["DX_AUSENTE_EN_DOC"] = {"estado": "dispara",
                                  "detalle": "el documento imprime 'NO REGISTRA' y no hay ningun codigo legible"}
    elif ausente:
        # Hay 'NO REGISTRA' pero tambien un codigo: en las tablas el OCR mezcla el orden
        # de columnas, asi que el 'NO REGISTRA' puede pertenecer al DX secundario.
        C["DX_AUSENTE_EN_DOC"] = {"estado": "revisar",
                                  "detalle": "'NO REGISTRA' presente pero hay codigo %s; posible mezcla de columnas"
                                             % cand["codigo"]}
    else:
        C["DX_AUSENTE_EN_DOC"] = {"estado": "ok", "detalle": ""}

    # --- DX_SIN_PRINCIPAL (heuristico estructural): el formato imprime etiqueta de DX
    # secundario/relacionado pero NO hay ningun codigo principal legible.
    hay_secundario = any(a["peso"] == 0 for a in anclas)
    if not aplica:
        C["DX_SIN_PRINCIPAL"] = {"estado": "no_aplica", "detalle": "tipo de documento sin diagnostico"}
    elif cand is None and hay_secundario:
        C["DX_SIN_PRINCIPAL"] = {"estado": "dispara",
                                 "detalle": "hay etiqueta de DX relacionado/secundario pero ningun codigo principal"}
    elif cand is None:
        C["DX_SIN_PRINCIPAL"] = {"estado": "no_verificable", "detalle": "no se leyo ningun codigo"}
    else:
        C["DX_SIN_PRINCIPAL"] = {"estado": "ok", "detalle": ""}

    # --- DX_NO_LEIDO: no se pudo aislar un codigo legible (letra + 2 digitos).
    if not aplica:
        C["DX_NO_LEIDO"] = {"estado": "no_aplica", "detalle": "tipo de documento sin diagnostico"}
    elif cand is None:
        C["DX_NO_LEIDO"] = {"estado": "dispara",
                            "detalle": "sin candidato CIE-10 junto a una etiqueta de diagnostico"}
    else:
        C["DX_NO_LEIDO"] = {"estado": "ok", "detalle": "codigo aislado: %s" % cand["crudo"]}

    # --- DX_FORMATO_LONGITUD: el catalogo usa 4 caracteres (con 'X' de relleno).
    if not aplica or cand is None:
        C["DX_FORMATO_LONGITUD"] = {"estado": "no_verificable",
                                    "detalle": "no hay codigo legible que validar"}
    elif cand["longitud"] == LONGITUD_CATALOGO:
        C["DX_FORMATO_LONGITUD"] = {"estado": "ok",
                                    "detalle": "%s (4 caracteres%s)" % (
                                        cand["codigo"], ", relleno X" if cand["relleno_x"] else "")}
    elif cand["longitud"] == 3:
        C["DX_FORMATO_LONGITUD"] = {
            "estado": "dispara",
            "detalle": "impreso '%s' = 3 caracteres; el catalogo exige 4 (seria '%sX' o '%s0'..'%s9')"
                       % (cand["crudo"], cand["codigo"], cand["codigo"], cand["codigo"]),
        }
    else:
        C["DX_FORMATO_LONGITUD"] = {"estado": "dispara",
                                    "detalle": "longitud %d inesperada (%s)" % (cand["longitud"], cand["crudo"])}

    # --- DX_INEXISTENTE: exige catalogo. Sin catalogo NO puede afirmar nada.
    if not aplica or cand is None:
        C["DX_INEXISTENTE"] = {"estado": "no_verificable", "detalle": "sin codigo legible"}
    elif catalogo is None:
        C["DX_INEXISTENTE"] = {"estado": "no_verificable",
                               "detalle": "falta el catalogo lpdiagnosticos (ASTGU); no se afirma inexistencia"}
    else:
        clave = cand["codigo"].replace(".", "")
        if clave in catalogo:
            C["DX_INEXISTENTE"] = {"estado": "ok", "detalle": "%s existe en el catalogo" % clave}
        else:
            C["DX_INEXISTENTE"] = {"estado": "dispara", "detalle": "%s no esta en lpdiagnosticos" % clave}

    # --- DX_NOMBRE_DISTINTO: exige catalogo. Heuristico (difflib sobre la descripcion).
    desc = res["desc_impresa"]
    if not aplica or cand is None or not desc:
        C["DX_NOMBRE_DISTINTO"] = {"estado": "no_verificable", "detalle": "sin descripcion impresa utilizable"}
    elif catalogo is None:
        C["DX_NOMBRE_DISTINTO"] = {"estado": "no_verificable",
                                   "detalle": "falta el catalogo lpdiagnosticos (ASTGU)"}
    else:
        oficial = catalogo.get(cand["codigo"].replace(".", ""))
        if not oficial:
            C["DX_NOMBRE_DISTINTO"] = {"estado": "no_verificable", "detalle": "codigo no esta en el catalogo"}
        else:
            r = difflib.SequenceMatcher(None, _norm_desc(desc), _norm_desc(oficial)).ratio()
            if r >= 0.90:
                est = "ok"
            elif r >= 0.60:
                est = "revisar"
            else:
                est = "dispara"
            C["DX_NOMBRE_DISTINTO"] = {"estado": est, "detalle": "similitud %.2f" % r}

    # --- DX_CAPITULO_INCOHERENTE: autonomo pero HEURISTICO y EXPERIMENTAL.
    if not aplica or cand is None:
        C["DX_CAPITULO_INCOHERENTE"] = {"estado": "no_verificable", "detalle": "sin codigo legible"}
    else:
        ver, det = coherencia_capitulo(cand["codigo"], desc)
        C["DX_CAPITULO_INCOHERENTE"] = {
            "estado": {"incoherente": "dispara", "coherente": "ok"}.get(ver, "no_verificable"),
            "detalle": det,
        }
    return res


# Checks que se cuentan como ACUSACION (los que pueden marcar un documento).
ACUSAN_DURO = ["DX_FORMATO_LONGITUD"]
ACUSAN_EXPERIMENTAL = ["DX_CAPITULO_INCOHERENTE", "DX_SIN_PRINCIPAL"]
ACUSAN_CON_CATALOGO = ["DX_INEXISTENTE", "DX_NOMBRE_DISTINTO"]


# --------------------------------------------------------------------------- #
# 5. Corpus
# --------------------------------------------------------------------------- #
def tipo_por_nombre(archivo: str) -> str:
    base = os.path.splitext(archivo)[0]
    if "_" in base:
        suf = base.rsplit("_", 1)[-1].strip().lower()
        suf = {"inpacacidad": "incapacidad"}.get(suf, suf)
        if suf in {"incapacidad", "permiso", "historia", "vacaciones", "epicrisis", "formula"}:
            return suf
    return ""


def cargar_corpus():
    porjson = {}
    for p in sorted(DIR_OCR.glob("*/*.json")):
        d = json.loads(p.read_text(encoding="utf-8"))
        porjson[d["archivo"]] = d
    filas = []
    with MANIFEST.open(encoding="utf-8", newline="") as fh:
        for fila in csv.DictReader(fh):
            d = porjson.get(fila["archivo"])
            if d is None:
                print("  ! sin OCR: %s" % fila["archivo"], file=sys.stderr)
                continue
            d["_etiqueta"] = fila["etiqueta"]
            d["_cuarentena"] = fila["cuarentena"] == "si"
            d["_motivo_cuarentena"] = fila["motivo_cuarentena"]
            d["_tipo_nombre"] = tipo_por_nombre(fila["archivo"])
            filas.append((fila["archivo"], d))
    return filas


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--debug", action="store_true")
    ap.add_argument("--json", default=str(AQUI / "resultados.json"))
    ap.add_argument("--catalogo", default=None)
    args = ap.parse_args()
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    catalogo, ruta_cat = cargar_catalogo(Path(args.catalogo) if args.catalogo else None)
    print("SONDA familia dx_catalogo (Diagnostico vs catalogo CIE-10)")
    print("catalogo CIE-10: %s" % ("%d codigos desde %s" % (len(catalogo), ruta_cat) if catalogo
                                   else "AUSENTE (%s) -> DX_INEXISTENTE y DX_NOMBRE_DISTINTO = no_verificable" % ruta_cat))
    print("-" * 118)
    print("%-52s %-7s %-4s %-7s %-11s %s" % ("archivo", "etiq", "cuar", "dx", "FORMATO", "resultado"))
    print("-" * 118)

    resultados = []
    for archivo, doc in cargar_corpus():
        r = evaluar(doc, catalogo)
        C = r["checks"]
        duro = [k for k in ACUSAN_DURO if C[k]["estado"] == "dispara"]
        exper = [k for k in ACUSAN_EXPERIMENTAL if C[k]["estado"] == "dispara"]
        concat = [k for k in ACUSAN_CON_CATALOGO if C[k]["estado"] == "dispara"]
        marcas = duro + concat
        if marcas:
            veredicto = "MARCA: " + ",".join(marcas)
        elif not r["aplica"]:
            veredicto = "no_aplica (sin DX por tipo de documento)"
        elif C["DX_AUSENTE_EN_DOC"]["estado"] == "dispara":
            veredicto = "AVISO: DX_AUSENTE_EN_DOC"
        elif C["DX_NO_LEIDO"]["estado"] == "dispara":
            veredicto = "no_verificable: DX_NO_LEIDO"
        else:
            veredicto = "limpio (formato ok; catalogo no verificado)" if catalogo is None else "limpio"
        if exper:
            veredicto += "  [+exp: %s]" % ",".join(exper)
        print("%-52s %-7s %-4s %-7s %-11s %s" % (
            archivo[:52], doc["_etiqueta"], "SI" if doc["_cuarentena"] else "no",
            (r["dx_crudo"] or "-")[:7], C["DX_FORMATO_LONGITUD"]["estado"], veredicto))
        if args.debug:
            for c in r["_cands"][:6]:
                print("        cand %-8s -> %-7s len=%d fix=%d anc=%d dist=%+d cola=%r" % (
                    c["crudo"], c["codigo"], c["longitud"], c["correcciones"],
                    c["ancla_peso"], c["dist"], c["ancla_cola"][:26]))
            for k, v in C.items():
                print("        %-24s %-14s %s" % (k, v["estado"], v["detalle"][:78]))
            print("        desc_impresa=%r" % (r["desc_impresa"],))
        resultados.append({
            "archivo": archivo, "etiqueta": doc["_etiqueta"], "cuarentena": doc["_cuarentena"],
            "tipo": (doc["incapacidad"] or {}).get("tipo_documento"), "aplica": r["aplica"],
            "dx_crudo": r["dx_crudo"], "dx_leido": r["dx_leido"],
            "desc_impresa": r["desc_impresa"],
            "checks": {k: v for k, v in C.items()},
            "marca_dura": duro, "marca_experimental": exper, "marca_con_catalogo": concat,
            "veredicto": veredicto,
        })

    # ---------------- Medicion ----------------
    def cuenta(pred):
        return sum(1 for x in resultados if pred(x))

    val = [x for x in resultados if not x["cuarentena"]]
    f_tot = sum(1 for x in val if x["etiqueta"] == "falsa")
    r_tot = sum(1 for x in val if x["etiqueta"] == "real")
    f_det = sum(1 for x in val if x["etiqueta"] == "falsa" and x["marca_dura"])
    r_fp = sum(1 for x in val if x["etiqueta"] == "real" and x["marca_dura"])
    f_det_e = sum(1 for x in val if x["etiqueta"] == "falsa" and (x["marca_dura"] or x["marca_experimental"]))
    r_fp_e = sum(1 for x in val if x["etiqueta"] == "real" and (x["marca_dura"] or x["marca_experimental"]))

    print("-" * 118)
    print("CUARENTENA excluida de los conteos: %d documentos (%s)" % (
        cuenta(lambda x: x["cuarentena"]),
        ", ".join(x["archivo"][:34] for x in resultados if x["cuarentena"])))
    print("Validos: %d falsas + %d reales = %d" % (f_tot, r_tot, len(val)))
    print()
    print("[A] Solo checks DETERMINISTAS y AUTONOMOS (DX_FORMATO_LONGITUD)")
    print("    falsas detectadas : %d / %d" % (f_det, f_tot))
    print("    reales marcadas   : %d / %d  (falsos positivos)" % (r_fp, r_tot))
    for x in val:
        if x["marca_dura"]:
            print("      %-7s %-46s %s" % (x["etiqueta"], x["archivo"][:46],
                                            x["checks"]["DX_FORMATO_LONGITUD"]["detalle"][:64]))
    print()
    print("[B] Anadiendo los HEURISTICOS experimentales (%s)" % ", ".join(ACUSAN_EXPERIMENTAL))
    print("    falsas detectadas : %d / %d" % (f_det_e, f_tot))
    print("    reales marcadas   : %d / %d" % (r_fp_e, r_tot))
    for x in val:
        for k in x["marca_experimental"]:
            print("      %-7s %-46s %-24s %s" % (x["etiqueta"], x["archivo"][:46], k,
                                                 x["checks"][k]["detalle"][:52]))
    print()
    print("[C] Checks que HOY no son evaluables (falta el catalogo lpdiagnosticos de ASTGU)")
    print("    DX_INEXISTENTE      : detectadas 0 / %d  -> %s" % (
        f_tot, "no_verificable en %d/%d documentos" % (
            cuenta(lambda x: x["checks"]["DX_INEXISTENTE"]["estado"] == "no_verificable"), len(resultados))))
    print("    DX_NOMBRE_DISTINTO  : detectadas 0 / %d  -> %s" % (
        f_tot, "no_verificable en %d/%d documentos" % (
            cuenta(lambda x: x["checks"]["DX_NOMBRE_DISTINTO"]["estado"] == "no_verificable"), len(resultados))))
    print()
    print("[D] Cobertura de lectura del DX (calidad del insumo, no acusa)")
    print("    con codigo legible   : %d / %d" % (cuenta(lambda x: x["dx_leido"] and x["aplica"]),
                                                  cuenta(lambda x: x["aplica"])))
    print("    DX_NO_LEIDO          : %d  (%s)" % (
        cuenta(lambda x: x["checks"]["DX_NO_LEIDO"]["estado"] == "dispara"),
        ", ".join(x["archivo"][:30] for x in resultados
                  if x["checks"]["DX_NO_LEIDO"]["estado"] == "dispara")))
    print("    DX_AUSENTE_EN_DOC    : %d  (%s)" % (
        cuenta(lambda x: x["checks"]["DX_AUSENTE_EN_DOC"]["estado"] == "dispara"),
        ", ".join(x["archivo"][:30] for x in resultados
                  if x["checks"]["DX_AUSENTE_EN_DOC"]["estado"] == "dispara")))
    print("    con descripcion      : %d / %d" % (cuenta(lambda x: bool(x["desc_impresa"])),
                                                  cuenta(lambda x: x["aplica"])))

    Path(args.json).write_text(json.dumps({
        "familia": "dx_catalogo",
        "catalogo": None if catalogo is None else ruta_cat,
        "medicion": {"falsas_detectadas": f_det, "falsas_totales": f_tot,
                     "reales_marcadas": r_fp, "reales_totales": r_tot,
                     "falsas_detectadas_con_experimental": f_det_e,
                     "reales_marcadas_con_experimental": r_fp_e},
        "resultados": resultados,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print("\nresultados -> %s" % args.json)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
