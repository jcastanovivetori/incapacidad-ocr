"""Estructuración del texto OCR → esquema de incapacidad médica (Colombia).

Dos estrategias intercambiables:
- ``RuleBasedExtractor`` : regex/heurísticas. Determinista, sin LLM, ideal para
  texto impreso limpio y para pruebas reproducibles.
- ``OllamaLLMExtractor`` : usa un LLM local en Ollama para textos ruidosos
  (manuscritos, sellos). No requiere API paga.
"""
from __future__ import annotations

import json
import re
from typing import Any, Protocol


def empty_record() -> dict[str, Any]:
    """Esquema objetivo de una incapacidad (campos en None por defecto)."""
    return {
        "tipo_documento": "incapacidad",  # o "permiso" (FORMATO SOLICITUD DE PERMISO)
        "paciente": {"nombre": None, "documento_tipo": None, "documento_numero": None},
        "entidad": {"eps": None, "ips_prestador": None},
        "incapacidad": {
            "fecha_inicio": None,
            "fecha_fin": None,
            "dias": None,
            "fecha_expedicion": None,
            "tipo": None,
            "origen": None,
            # Certificados EPS de licencia de maternidad (tipo Sura): "Tipo de
            # Licencia" (PARTO VIABLE / PARTO NO VIABLE) no es un campo del ERP,
            # se lleva como nota en observaciones (ver erp._observaciones).
            "tipo_licencia": None,
        },
        "diagnostico": {"cie10": None, "descripcion": None},
        "medico": {"nombre": None, "registro": None},
        # Solo se llena cuando tipo_documento == "permiso" (licencia remunerada/no
        # remunerada). No aplica diagnóstico ni EPS para este tipo de ausentismo.
        "permiso": {
            "empresa": None,
            "cargo": None,
            "fecha_solicitud": None,
            "tipo_remunerado": None,  # "REMUNERADO" | "NO_REMUNERADO"
            "detalle": None,
            "horas_desde": None,
            "horas_hasta": None,
            "horas_total": None,
            "autorizado_por": None,
            "autorizado_cargo": None,
        },
    }


class Extractor(Protocol):
    name: str

    def extract(self, text: str) -> dict[str, Any]:
        ...


# --------------------------------------------------------------------------- #
# Estrategia 1: reglas (determinista)
# --------------------------------------------------------------------------- #
# Las incapacidades reales (Colombia) salen del OCR con el texto desordenado
# (son formularios) y con etiquetas muy variadas según la EPS/IPS. Estas reglas
# se ajustaron sobre documentos reales priorizando patrones GENERALIZABLES.

_MONTHS_ES = {
    "ene": "01", "feb": "02", "mar": "03", "abr": "04", "may": "05", "jun": "06",
    "jul": "07", "ago": "08", "sep": "09", "set": "09", "oct": "10", "nov": "11", "dic": "12",
}


def _first(text: str, pattern: str, group: int = 1, flags: int = re.I) -> str | None:
    m = re.search(pattern, text, flags)
    if not m:
        return None
    out = m.group(group).strip()
    return out or None


def _fecha_valida(y: int, mo: int, d: int) -> bool:
    """True si (y, mo, d) es una fecha de calendario real (rechaza día 54, mes 13,
    31 de febrero, etc.) — el OCR a veces deja pasar dígitos imposibles."""
    from datetime import date as _date
    try:
        _date(y, mo, d)
        return True
    except ValueError:
        return False


def _norm_date(value: str | None) -> str | None:
    """Normaliza a YYYY-MM-DD desde dd/mm/yyyy, yyyy-mm-dd o dd-mmm-yy(yy).
    Devuelve None si el resultado no es una fecha de calendario válida (nunca se
    fabrica ni se deja pasar un día/mes imposible)."""
    if not value:
        return None
    value = value.strip()
    m = re.fullmatch(r"(\d{4})-(\d{2})-(\d{2})", value)
    if m:
        y, mo, d = m.groups()
        return value if _fecha_valida(int(y), int(mo), int(d)) else None
    m = re.fullmatch(r"(\d{1,2})[/-](\d{1,2})[/-](\d{4})", value)
    if m:
        d, mo, y = m.groups()
        if not _fecha_valida(int(y), int(mo), int(d)):
            return None
        return f"{y}-{int(mo):02d}-{int(d):02d}"
    # dd-mmm-yy(yy): 10-jun-26, 10-jun26, 10 Jun.2026
    m = re.fullmatch(r"(\d{1,2})[\s.\-]*([A-Za-zÁÉÍÓÚáéíóú]{3})[a-z]*[\s.\-]*(\d{2,4})", value)
    if m:
        d, mon, y = m.groups()
        mo = _MONTHS_ES.get(mon[:3].lower())
        if mo:
            year = y if len(y) == 4 else f"20{y}"
            if not _fecha_valida(int(year), int(mo), int(d)):
                return None
            return f"{year}-{mo}-{int(d):02d}"
    return None


# Patrón de fecha que tolera los tres formatos vistos en documentos reales.
_DATE = r"(\d{4}-\d{2}-\d{2}|\d{1,2}[/-]\d{1,2}[/-]\d{4}|\d{1,2}[\s.\-]*[A-Za-z]{3}[a-z]*[\s.\-]*\d{2,4})"

# --- Fecha "escrita" en español, sin año (certificados EPS tipo Sura) ------------
# "VIERNES 10 DEJULIO" / "JUEVES23DEJULIO": día de la semana opcional + día + "DE"
# + mes, todo pegado sin espacios por el OCR. El AÑO en este formato sale del OCR
# DESPUÉS, aparte ("DE 2026"), una vez por cada fecha, en el MISMO orden en que
# aparecen las fechas — por eso se emparejan por posición, no por cercanía.
_MESES_ES = {
    "enero": "01", "febrero": "02", "marzo": "03", "abril": "04", "mayo": "05", "junio": "06",
    "julio": "07", "agosto": "08", "septiembre": "09", "setiembre": "09", "octubre": "10",
    "noviembre": "11", "diciembre": "12",
}
_FECHA_DM_ESCRITA = re.compile(
    r"(?i)(\d{1,2})\s*DE\s*(" + "|".join(_MESES_ES) + r")\w*"
)


def _fecha_inicio_fin_escrita(text: str) -> tuple[str | None, str | None]:
    """(inicio, fin) para certificados EPS con fecha escrita (sin año pegado): sólo
    se activa si el documento trae la etiqueta "Fecha Inicio" en algún lado (evita
    falsos positivos con otras fechas escritas del documento), pero NO se acota a
    un bloque cerca de esa etiqueta — la posición de "Tipo Generación" respecto a
    "Fecha Inicio" varía de un documento a otro (a veces antes, a veces después),
    así que se buscan las DOS parejas día+mes / año en TODO el texto, en orden de
    aparición (1ª = inicio, 2ª = fin)."""
    if not re.search(r"(?i)fecha\s*[il]nici\w*", text):
        return None, None

    dm = _FECHA_DM_ESCRITA.findall(text)
    years = re.findall(r"(?i)\bDE\s*(\d{4})\b", text)
    if len(dm) < 2 or len(years) < 2:
        return None, None
    fechas: list[str | None] = []
    for (dia, mes), anio in zip(dm[:2], years[:2]):
        mo = _MESES_ES.get(mes.lower())
        if mo and _fecha_valida(int(anio), int(mo), int(dia)):
            fechas.append(f"{anio}-{mo}-{int(dia):02d}")
        else:
            fechas.append(None)
    inicio = fechas[0] if fechas else None
    fin = fechas[1] if len(fechas) > 1 else None
    return inicio, fin


# --- Carta de "Notificación Periodo de Vacaciones" (tipo ausentismo 13) ----------
# No es un formulario de casillas sino una CARTA en prosa: las fechas salen
# escritas en palabras con el número real entre paréntesis, p.ej. "...a partir del
# veintinueve (29) de mayo de dos mil veintiseis (2026)...". No lleva diagnóstico
# ni EPS (ver es_vacaciones en erp.mapear_a_staging) — el nombre/cédula del
# empleado SÍ se extraen con las reglas genéricas de paciente (mismo patrón "CC:").
_VACACIONES_ANCHOR = re.compile(r"(?i)notificaci[oó]n\s*(?:de\s*)?periodos?\s*de\s*vacaciones")


def es_formato_vacaciones(text: str) -> bool:
    return bool(_VACACIONES_ANCHOR.search(text))


def _fecha_parentesis(text: str, pos: int, window: int = 60) -> str | None:
    """Fecha escrita en prosa con el número real entre paréntesis: '...veintinueve
    (29) de mayo de dos mil veintiseis (2026)...'. Busca desde `pos` hacia adelante."""
    seg = text[pos: pos + window]
    m = re.search(
        r"(?i)\((\d{1,2})\)\s*de\s*(" + "|".join(_MESES_ES) + r")\w*\s*de\s*[^(]{0,40}?\((\d{4})\)",
        seg,
    )
    if not m:
        return None
    d, mes, y = m.groups()
    mo = _MESES_ES.get(mes.lower())
    if mo and _fecha_valida(int(y), int(mo), int(d)):
        return f"{y}-{mo}-{int(d):02d}"
    return None


def _fechas_vacaciones(text: str) -> tuple[str | None, str | None]:
    """(inicio, fin): toma la PRIMERA fecha tras "a partir del" y la ÚLTIMA tras
    "hasta el" — la carta puede asignar varios periodos consecutivos seguidos."""
    inicios = [_fecha_parentesis(text, m.end()) for m in re.finditer(r"(?i)a\s*partir\s*del?\b", text)]
    fines = [_fecha_parentesis(text, m.end()) for m in re.finditer(r"(?i)\bhasta\s*el\b", text)]
    inicios = [f for f in inicios if f]
    fines = [f for f in fines if f]
    return (inicios[0] if inicios else None), (fines[-1] if fines else None)


# "Tipo de Licencia" (maternidad): enumeración conocida del ERP/EPS, glued por el
# OCR ("PARTONOVIABLE") — se normaliza solo para los valores conocidos; cualquier
# otro se deja tal cual (se muestra igual como observación, sin bloquear nada).
_TIPO_LICENCIA_CONOCIDOS = {
    "PARTOVIABLE": "PARTO VIABLE",
    "PARTONOVIABLE": "PARTO NO VIABLE",
}


def _norm_tipo_licencia(valor: str | None) -> str | None:
    if not valor:
        return None
    clave = re.sub(r"[^A-ZÑ]", "", valor.upper())
    return _TIPO_LICENCIA_CONOCIDOS.get(clave, valor.strip())


def _find_date(text: str, label_pattern: str) -> str | None:
    """Busca una fecha (3 formatos) cerca de una etiqueta.

    Primero después de la etiqueta (tolerando el resto de la palabra y separadores);
    si no la halla, justo antes (los formularios reales salen del OCR desordenados y
    a veces el valor queda antes de su rótulo).
    """
    # Después del rótulo: la fecha MÁS CERCANA (no-greedy), tolerando que el valor
    # esté en la línea siguiente (se permite \n, pero con un límite corto).
    after = re.search(rf"(?i){label_pattern}[^\d]{{0,18}}?{_DATE}", text)
    if after:
        return _norm_date(after.group(1))
    # Si no, justo antes del rótulo (sólo separadores/saltos, sin cruzar letras).
    before = re.search(rf"(?i){_DATE}[\s).:\-]{{0,4}}{label_pattern}", text)
    if not before:
        return None
    # PERO: si esa fecha ya está pegada a SU PROPIA etiqueta justo antes
    # ("...Fecha Fin:2026-06-11\nFecha Inicio:"), es el valor de OTRO campo que
    # quedó ahí por el desorden del OCR de tabla — no es un valor suelto para
    # el rótulo que buscamos. Se descarta en vez de robarle el dato al campo vecino.
    previo = text[max(0, before.start() - 20): before.start()]
    if re.search(r"(?i)[a-záéíóúñ]\s*:\s*$", previo):
        return None
    return _norm_date(before.group(1))


def _days_between(inicio: str | None, fin: str | None) -> int | None:
    """Días de incapacidad (inclusivo) calculados desde las fechas, si ambas existen."""
    if not (inicio and fin):
        return None
    try:
        from datetime import date
        di = date.fromisoformat(inicio)
        df = date.fromisoformat(fin)
    except ValueError:
        return None
    delta = (df - di).days + 1
    return delta if 1 <= delta <= 540 else None


# El OCR confunde dígitos con letras en los códigos (0↔O, 1↔I/l/L, 2↔Z, 5↔S).
# Se normaliza SOLO la parte numérica del CIE-10 (la primera posición sí es letra).
_DIGIT_FIX = {"O": "0", "o": "0", "I": "1", "l": "1", "L": "1", "|": "1", "Z": "2", "S": "5"}


def _normalize_cie10(token: str) -> tuple[str | None, int]:
    """Normaliza un candidato a CIE-10. Devuelve (código, nº de correcciones letra→dígito).

    Acepta ``S42.0``/``S420``/``A09``. Inserta el punto en los códigos de 4
    caracteres (``X##N`` → ``X##.N``) y arregla confusiones de OCR en los dígitos.
    """
    if not token:
        return None, 99
    raw = token.upper().replace(",", ".").strip(".")
    m = re.fullmatch(r"([A-Z])([0-9OILZS|]{2})\.?([0-9OILZS|]{0,2})", raw)
    if not m:
        return None, 99
    letter, mid, tail = m.groups()
    fixes = 0
    out_digits = []
    for ch in mid + tail:
        if ch.isdigit():
            out_digits.append(ch)
        elif ch in _DIGIT_FIX:
            out_digits.append(_DIGIT_FIX[ch])
            fixes += 1
        else:
            return None, 99
    digits = "".join(out_digits)
    if len(digits) < 2:
        return None, 99
    code = f"{letter}{digits[:2]}" + (f".{digits[2:]}" if len(digits) > 2 else "")
    return code, fixes


_CIE_ANCHOR = re.compile(r"(?i)(diag|dx|cie\s*-?\s*10|principal)")


def _extract_cie10(text: str) -> str | None:
    """Encuentra el mejor candidato a CIE-10 en el texto.

    Prefiere candidatos cercanos a una etiqueta de diagnóstico y con menos
    correcciones de OCR (un '4' real gana a una 'L' interpretada como '1').
    """
    best = None  # (near_anchor, -fixes, -pos) mayor es mejor
    # Sin \b final: el código suele venir pegado a la descripción (p.ej. "K429HERNIA").
    for m in re.finditer(r"(?<![A-Za-z])([A-Z][0-9OoIiLlZzSs|]{2,3})(?:[.,][0-9OoIiLlZzSs|])?", text):
        # Debe tener al menos un dígito REAL → evita falsos positivos de puras letras
        # (p.ej. "FOS"→F05 de FOSCAL, "SOL"→S01). Un CIE-10 real siempre trae dígitos.
        if not any(ch.isdigit() for ch in m.group(0)):
            continue
        code, fixes = _normalize_cie10(m.group(0))
        if not code:
            continue
        ctx = text[max(0, m.start() - 40): m.start()]
        near = 1 if _CIE_ANCHOR.search(ctx) else 0
        key = (near, -fixes, -m.start())
        if best is None or key > best[0]:
            best = (key, code)
    return best[1] if best else None


# Palabras que no forman parte de un nombre (cortan la captura del nombre).
_NAME_STOP = re.compile(
    r"(?i)\b(usuario|pagina|edad|a[nñ]os|fecha|documento|nombres?|sexo|genero|tipo|"
    r"entidad|administrad|cod|telefono|historia|consecutivo|estado|empleador?|nit|"
    r"registro|reg\.?\s*med|especialidad)\b"
)

# --- Separación de nombres pegados por el OCR ("HERNANDEZSANDOVAL"). -----------
# El OCR a veces une dos palabras de un nombre. Con un léxico de nombres/apellidos
# frecuentes en Colombia partimos un token largo en sus palabras (word-break por DP,
# minimizando el nº de segmentos). El catálogo de empleados (en erp.py) sigue siendo
# la fuente AUTORITATIVA del nombre cuando la cédula resuelve; esto es el respaldo
# genérico para médicos/pacientes no encontrados.
_NAME_LEX = {
    # apellidos frecuentes
    "GARCIA", "RODRIGUEZ", "MARTINEZ", "LOPEZ", "GONZALEZ", "HERNANDEZ", "PEREZ",
    "SANCHEZ", "RAMIREZ", "TORRES", "FLOREZ", "FLORES", "RIVERA", "GOMEZ", "DIAZ",
    "REYES", "MORALES", "JIMENEZ", "RUIZ", "ALVAREZ", "MORENO", "MUNOZ", "ROJAS",
    "MEDINA", "CASTRO", "ORTIZ", "RAMOS", "SUAREZ", "VARGAS", "CASTILLO", "ROMERO",
    "HERRERA", "MENDOZA", "GUERRERO", "SANDOVAL", "CHAPARRO", "LANCHEROS", "AFANADOR",
    "VELANDIA", "LINARES", "RICARDO", "GARNICA", "CONTRERAS", "ARDILA", "NAVARRO",
    "ACOSTA", "CARDENAS", "PARRA", "CARDONA", "RINCON", "OSORIO", "BERMUDEZ", "BELTRAN",
    "VILLAMIZAR", "QUINTERO", "PINEDA", "SALAZAR", "AGUILAR", "PENA", "LEON", "GALLEGO",
    "ARIAS", "CABRERA", "CARDOZO", "ESCOBAR", "FRANCO", "FUENTES", "GUTIERREZ", "MEJIA",
    "MOLINA", "OCHOA", "PARDO", "PRIETO", "RUEDA", "SERRANO", "SOTO", "VALENCIA",
    "VELASQUEZ", "ZAPATA", "AMAYA", "ANGULO", "BARRERA", "BAUTISTA", "BUSTOS", "CAMACHO",
    "CARO", "CASAS", "CORTES", "DUARTE", "DURAN", "FORERO", "GALVIS", "GAMBOA", "GUZMAN",
    "IBARRA", "LOZANO", "MARIN", "MONTOYA", "NINO", "OSPINA", "PATINO", "PORRAS",
    "QUIROGA", "RANGEL", "RIOS", "SIERRA", "TOVAR", "URIBE", "VEGA", "VERA", "VILLA",
    "GELVEZ", "NORIEGA", "MANTILLA", "CARRILLO", "ESPINOSA", "FAJARDO", "ORTEGA", "ROA",
    "SOLANO", "TELLEZ", "ZAMBRANO", "BARRIOS", "CESPEDES", "CHACON", "DELGADO", "ESTUPINAN",
    # nombres de pila frecuentes
    "JUAN", "CARLOS", "LUIS", "JOSE", "JORGE", "MIGUEL", "ANDRES", "DAVID", "DANIEL",
    "FERNANDO", "ALEJANDRO", "JAIME", "CESAR", "ARMANDO", "MICHAEL", "ALEXIZ", "ALIX",
    "YARITZA", "JAIDER", "SEBASTIAN", "ISAAC", "LEONARDO", "MARIA", "ANA", "LUISA",
    "PAULA", "LAURA", "CAMILA", "VALENTINA", "SARA", "SOFIA", "DIANA", "CLAUDIA",
    "SANDRA", "PATRICIA", "MARTHA", "ANGELA", "LILIANA", "OSCAR", "JAVIER", "MAURICIO",
    "GERMAN", "GUSTAVO", "HERNAN", "EDGAR", "NELSON", "WILSON", "FABIAN", "FELIPE",
    "SANTIAGO", "NICOLAS", "MATEO", "SAMUEL", "GABRIEL", "EDUARDO", "RAFAEL", "ROBERTO",
    "PEDRO", "PABLO", "FRANCISCO", "ANTONIO", "MANUEL", "ALBERTO", "ALFONSO", "ALFREDO",
    "RUBEN", "RAUL", "VICTOR", "HECTOR", "MARCO", "ENRIQUE", "ARTURO", "ESTEBAN", "IVAN",
    "JULIAN", "KEVIN", "BRAYAN", "JEISON", "YEISON", "MARIANA", "DANIELA", "NATALIA",
    "CAROLINA", "ANDREA", "JOHANA", "YESICA", "KAREN", "TATIANA", "ALEXANDRA", "VIVIANA",
    "ADRIANA", "MONICA", "ELIANA", "GLORIA", "ROCIO", "ESPERANZA", "CONSUELO", "BLANCA",
    "AMANDA", "EDWIN", "JESUS", "OMAR", "WILLIAM", "YENNY", "YINETH",
}
# Traducción length-preserving para comparar sin tildes/Ñ (mantiene los índices).
_UPPER_ASCII = str.maketrans("ÁÉÍÓÚÜÑ", "AEIOUUN")


def _ascii_upper(s: str) -> str:
    return s.upper().translate(_UPPER_ASCII)


def _wordbreak(token: str, lex: set[str]) -> list[str] | None:
    """Parte ``token`` en palabras del léxico (DP, mín. nº de segmentos). None si no cubre."""
    n = len(token)
    best: list[list[str] | None] = [None] * (n + 1)
    best[n] = []
    for i in range(n - 1, -1, -1):
        cand = None
        for j in range(i + 3, n + 1):  # palabras de ≥3 letras
            if token[i:j] in lex and best[j] is not None:
                seg = [token[i:j]] + best[j]
                if cand is None or len(seg) < len(cand):
                    cand = seg
        best[i] = cand
    return best[0]


def _split_glued_name(name: str | None) -> str | None:
    """Separa tokens largos pegados ("HERNANDEZSANDOVAL" → "HERNANDEZ SANDOVAL")."""
    if not name:
        return name
    parts: list[str] = []
    for tok in name.split():
        norm = _ascii_upper(tok)
        # Solo intentamos partir tokens largos que NO sean ya una palabra conocida.
        if len(norm) >= 9 and norm not in _NAME_LEX:
            seg = _wordbreak(norm, _NAME_LEX)
            if seg and len(seg) >= 2:
                idx = 0
                for w in seg:  # aplica los cortes al token ORIGINAL (misma longitud)
                    parts.append(tok[idx:idx + len(w)])
                    idx += len(w)
                continue
        parts.append(tok)
    return " ".join(parts)


def _clean_name(raw: str | None) -> str | None:
    if not raw:
        return None
    name = _NAME_STOP.split(raw)[0]
    name = re.sub(r"\s{2,}", " ", name).strip(" .:-")
    name = re.sub(r"\s+[A-ZÑ]$", "", name).strip()  # quita letra suelta final (p.ej. "R" de Registro)
    name = _split_glued_name(name)  # separa nombres pegados por el OCR
    return name or None


# --------------------------------------------------------------------------- #
# Formato "SOLICITUD DE PERMISO" (licencia remunerada/no remunerada) — un tipo de
# ausentismo distinto a la incapacidad médica: no lleva diagnóstico ni EPS. Es un
# formulario de casillas (X), no de texto libre, así que se trata aparte.
# --------------------------------------------------------------------------- #
# \s* (no \s+): el RapidOCR real pega las palabras de los rótulos sin espacio
# ("SOLICITUDDEPERMISO"), así que la tolerancia debe ser CERO-o-más, no una-o-más.
_PERMISO_ANCHOR = re.compile(r"(?i)solicitud\s*de\s*permiso")

# Triplete D M A suelto (celdas de tabla que el OCR separa: "06 06 26"), como
# respaldo cuando la fecha NO sale ya unida en un solo token (dd/mm/aaaa).
_DMA_TRIPLET = r"(\d{1,2})[\s/\-]+(\d{1,2})[\s/\-]+(\d{2,4})"

# Nombre/razón social en Título ("Mishell Dayana Gamarra Gómez", "Indulacteos de
# Colombia"): primera palabra Capitalizada+minúsculas (así NO matchea encabezados
# en MAYÚSCULA sostenida como "DOCUMENTO"/"CARGO"/"EMPRESA"), y admite conectores
# en minúscula (de/del/la/...) entre palabras siguientes.
_NOMBRE_PROPIO = (
    r"([A-ZÑÁÉÍÓÚ][a-zñáéíóúü]+(?:\s+(?:[A-ZÑÁÉÍÓÚ][a-zñáéíóúü]+|de|del|la|las|los|y))"
    r"{0,5})"
)
# Nombre de PERSONA: 2-4 palabras en Título, SIN conectores (evita que se fusione
# con lo que venga justo después, p.ej. el nombre de la empresa en la misma fila).
_NOMBRE_PERSONA = r"([A-ZÑÁÉÍÓÚ][a-zñáéíóúü]+(?:\s+[A-ZÑÁÉÍÓÚ][a-zñáéíóúü]+){1,3})"


def _valores_tras_etiqueta(text: str, label_pattern: str, window: int = 60) -> list[str]:
    """Para CADA aparición de la etiqueta, la primera línea no vacía que sigue.

    Sirve para rótulos que se repiten (p.ej. "NOMBRE"/"CARGO" salen dos veces en
    la sección de aprobación: solicitante y quien autoriza, en ese orden).
    """
    out = []
    for m in re.finditer(rf"(?i){label_pattern}", text):
        seg = re.sub(r"^\s*[:\-]?\s*", "", text[m.end():m.end() + window])
        for line in seg.split("\n"):
            line = line.strip()
            if line:
                out.append(line)
                break
    return out


def es_formato_permiso(text: str) -> bool:
    """Detecta el FORMATO SOLICITUD DE PERMISO (vs. certificado de incapacidad)."""
    return bool(_PERMISO_ANCHOR.search(text))


# PDFs reales suelen traer la incapacidad JUNTO con otras páginas del mismo trámite
# clínico (certificado de nacido vivo, epicrisis, cédula escaneada...) que si se
# mezclan en el mismo texto confunden al extractor (otras cédulas/diagnósticos/
# fechas que no son los del ausentismo). Estos anclajes identifican la página que
# SÍ trae el certificado de incapacidad en sí (título/encabezado de esa página).
_INCAPACIDAD_PAGE_ANCHOR = re.compile(
    r"(?i)incapacidad\s*medica\b|certificado\s*de\s*incapacidad|detalle\s*de\s*la\s*incapacidad"
)


def es_pagina_relevante(text: str) -> bool:
    """True si esta PÁGINA (de un documento multi-página) trae el ausentismo en sí
    (incapacidad/permiso/vacaciones), no una página acompañante del mismo trámite."""
    return bool(
        _INCAPACIDAD_PAGE_ANCHOR.search(text)
        or es_formato_permiso(text)
        or es_formato_vacaciones(text)
    )


def _find_date_or_triplet(text: str, label_pattern: str) -> str | None:
    """Como ``_find_date``, pero además tolera un D/M/A separado por espacios
    (celdas de tabla) cuando la fecha no viene en un solo token dd/mm/aaaa."""
    d = _find_date(text, label_pattern)
    if d:
        return d
    m = re.search(rf"(?i){label_pattern}[^\d]{{0,60}}?{_DMA_TRIPLET}", text)
    if not m:
        return None
    dd, mo, yy = m.groups()
    yy = yy if len(yy) == 4 else f"20{yy}"
    try:
        d1, m1, y1 = int(dd), int(mo), int(yy)
    except ValueError:
        return None
    if not _fecha_valida(y1, m1, d1):
        return None
    return f"{yy}-{m1:02d}-{d1:02d}"


def _near_label(text: str, label_pattern: str, value_pattern: str, window: int = 80) -> str | None:
    """Valor que aparece dentro de ``window`` caracteres después de la etiqueta
    (tolera que etiqueta y valor queden en filas distintas de una tabla OCR'd)."""
    m = re.search(rf"(?i){label_pattern}", text)
    if not m:
        return None
    seg = text[m.end():m.end() + window]
    mv = re.search(value_pattern, seg)
    return mv.group(1).strip() if mv else None


def _extraer_tipo_remunerado(text: str) -> str | None:
    """'X'/'✓' junto a la casilla de Remunerado / No Remunerado.

    Heurística de ORDEN DE TEXTO (no de coordenadas: RapidOCR no las expone hoy):
    en este formato la fila es "[X] Remunerado   [ ] No Remunerado", así que la
    marca queda pegada -antes o después- de la etiqueta de SU PROPIA casilla.
    """
    if re.search(
        r"(?i)(?:[X✓]\s*[.)\-]?\s*No\s*Remunerado|No\s*Remunerado\s*[.)\-]?\s*[X✓])", text
    ):
        return "NO_REMUNERADO"
    for m in re.finditer(r"(?i)Remunerado\b", text):
        antes = text[max(0, m.start() - 12):m.start()]
        despues = text[m.end():m.end() + 4]
        if re.search(r"(?i)\bno\b", antes):
            continue  # es la casilla "No Remunerado", ya descartada arriba
        if re.search(r"[X✓]", antes) or re.search(r"[X✓]", despues):
            return "REMUNERADO"
    return None


def _extraer_permiso(text: str) -> dict[str, Any]:
    rec = empty_record()
    rec["tipo_documento"] = "permiso"
    perm = rec["permiso"]
    t = text

    # --- 1. Datos de la solicitud: fecha, nombre, documento, empresa ---
    # OJO: en documentos reales el OCR NO respeta el orden de columnas (el nombre
    # puede salir ANTES que la fecha, y la empresa partida en dos por los dígitos
    # de la fecha en medio). Por eso NO se consume secuencialmente: cada campo se
    # busca en TODO el bloque, con un patrón lo bastante específico para no cruzarse
    # con los demás (dígitos largos = documento; texto Título = nombre/empresa).
    m1 = re.search(r"(?i)datos\s*de\s*la\s*solicitud", t)
    m2 = re.search(r"(?i)tipo\s*de\s*permiso", t)
    bloque = t[m1.end():m2.start()] if (m1 and m2) else (t[m1.end():] if m1 else t)

    fm = re.search(_DATE, bloque)
    if fm:
        perm["fecha_solicitud"] = _norm_date(fm.group(0))
    else:
        tm = re.search(_DMA_TRIPLET, bloque)
        if tm:
            dd, mo, yy = tm.groups()
            yy = yy if len(yy) == 4 else f"20{yy}"
            try:
                if _fecha_valida(int(yy), int(mo), int(dd)):
                    perm["fecha_solicitud"] = f"{yy}-{int(mo):02d}-{int(dd):02d}"
            except ValueError:
                pass

    # El nombre de la persona se aísla con un patrón ESTRICTO (2-4 palabras, sin
    # conectores en minúscula) para que NO se fusione con lo que venga justo
    # después en la misma fila (p.ej. el nombre de la empresa: "Mishell Dayana
    # Gamarra Gomez" + "Indulacteos de" se verían como un solo nombre de 6
    # palabras si se usara el patrón permisivo de razón social).
    nm = re.search(_NOMBRE_PERSONA, bloque)
    if nm:
        rec["paciente"]["nombre"] = _clean_name(nm.group(1))
        resto = bloque[:nm.start()] + bloque[nm.end():]  # el resto, sin el nombre
    else:
        resto = bloque
    # La empresa queda en los tramos de texto-Título restantes (a veces partida en
    # dos, p.ej. "Indulacteos de" ... "Colombia" con la fecha/documento en medio).
    frag_empresa = [re.sub(r"\s+", " ", m.group(1)).strip() for m in re.finditer(_NOMBRE_PROPIO, resto)]
    if frag_empresa:
        perm["empresa"] = " ".join(frag_empresa)

    dm = re.search(r"(\d{6,12})", bloque)
    if dm:
        rec["paciente"]["documento_numero"] = dm.group(1)
        rec["paciente"]["documento_tipo"] = "CC"

    # Respaldo genérico si el bloque no se pudo acotar (p.ej. no se detectó "2. TIPO
    # DE PERMISO"): intenta por etiqueta directa antes de dejarlo vacío.
    if not rec["paciente"]["nombre"]:
        rec["paciente"]["nombre"] = _clean_name(_near_label(
            t, r"nombre\s*completo\s*(?:del\s*solicitante)?\s*[:\-]?", _NOMBRE_PROPIO, window=250
        ))
    if not rec["paciente"]["documento_numero"]:
        doc = _near_label(t, r"documento\s*(?:de\s*identidad)?", r"(\d{6,12})", window=250)
        if doc:
            rec["paciente"]["documento_numero"] = doc
            rec["paciente"]["documento_tipo"] = "CC"

    # --- 2. Tipo de permiso: casilla remunerado / no remunerado ---
    perm["tipo_remunerado"] = _extraer_tipo_remunerado(t)
    rec["incapacidad"]["tipo"] = {
        "REMUNERADO": "LICENCIA REMUNERADA", "NO_REMUNERADO": "LICENCIA NO REMUNERADA",
    }.get(perm["tipo_remunerado"])
    perm["detalle"] = _first(
        t, r"(?is)detalle\s*[:\-]?\s*(.*?)(?:\n\s*\n|(?:\d+\.\s*)?duraci[oó]n\s*del\s*permiso|$)"
    )

    # --- 3. Duración: días (desde/hasta) u horas, si es un permiso parcial ---
    # Las DOS fechas (desde/hasta) salen del OCR una detrás de otra, DESPUÉS de
    # todos los rótulos de esta sección — por eso se toman en orden de aparición
    # (la primera = desde, la segunda = hasta) en vez de buscar cada una "cerca"
    # de su etiqueta (ambas etiquetas quedan pegadas juntas, lejos de sus fechas).
    m3 = re.search(r"(?i)duraci[oó]n\s*del\s*permiso", t)
    m4 = re.search(r"(?i)aprobaci[oó]n\s*de\s*la\s*solicitud", t)
    bloque_dur = t[m3.end():m4.start()] if (m3 and m4) else (t[m3.end():] if m3 else "")
    fechas = [_norm_date(m.group(0)) for m in re.finditer(_DATE, bloque_dur)]
    if len(fechas) < 2:
        for m in re.finditer(_DMA_TRIPLET, bloque_dur):
            dd, mo, yy = m.groups()
            yy = yy if len(yy) == 4 else f"20{yy}"
            try:
                if _fecha_valida(int(yy), int(mo), int(dd)):
                    fechas.append(f"{yy}-{int(mo):02d}-{int(dd):02d}")
            except ValueError:
                pass
    fechas = [f for f in fechas if f][:2]
    if fechas:
        rec["incapacidad"]["fecha_inicio"] = fechas[0]
    if len(fechas) > 1:
        rec["incapacidad"]["fecha_fin"] = fechas[1]
    elif fechas:
        rec["incapacidad"]["fecha_fin"] = fechas[0]  # un solo día: desde == hasta
    rec["incapacidad"]["dias"] = _days_between(
        rec["incapacidad"]["fecha_inicio"], rec["incapacidad"]["fecha_fin"]
    )
    _TIME = r"(\d{1,2}:\d{2}\s*(?:[ap]\.?\s*m\.?)?)"
    perm["horas_desde"] = _near_label(t, r"horas?[^\n]{0,20}\bdesde\b", _TIME, window=20)
    perm["horas_hasta"] = _near_label(t, r"\bhasta\b[^\n]{0,20}horas?", _TIME, window=20)
    perm["horas_total"] = _first(t, r"(?i)n[uú]mero\s*total\s*de\s*horas\s*[:\-]?\s*(\d{1,3})")

    # --- 4. Aprobación: cargo del solicitante / nombre y cargo de quien autoriza ---
    # "SOLICITADO POR" y "AUTORIZADO POR" suelen salir del OCR PEGADOS uno al otro
    # (dos encabezados de columna juntos), seguidos de "NOMBRE"/"CARGO" que TAMBIÉN
    # se repiten dos veces (solicitante primero, autorizador después) — por eso se
    # toman por POSICIÓN (1ª aparición = solicitante, 2ª = quien autoriza) en vez
    # de intentar acotar un segmento de texto por etiqueta.
    m_sol = re.search(r"(?i)solicitado\s*por", t)
    seg_aprob = t[m_sol.start():] if m_sol else t
    cargos = _valores_tras_etiqueta(seg_aprob, r"\bcargo\b\s*[:\-]?")
    nombres = _valores_tras_etiqueta(seg_aprob, r"\bnombre\b\s*[:\-]?")
    if cargos:
        perm["cargo"] = cargos[0]
    if len(cargos) > 1:
        perm["autorizado_cargo"] = cargos[1]
    if len(nombres) > 1:
        perm["autorizado_por"] = _clean_name(nombres[1])

    return rec


# --------------------------------------------------------------------------- #
# Tabla "DETALLE DE LA INCAPACIDAD" (formato Clínica del Cesar y similares): 5
# encabezados de columna seguidos de sus 5 valores, en el MISMO orden — mucho más
# fiable que las heurísticas genéricas cuando este bloque está presente (evita
# falsos positivos como tomar un CIE-10 de otra parte de la página o confundir
# "Dias Inc." con la descripción del diagnóstico).
# --------------------------------------------------------------------------- #
def _extraer_detalle_incapacidad(text: str) -> dict[str, Any] | None:
    m = re.search(
        r"(?i)detalle\s*de\s*la\s*incapacidad\s*"
        r"causa\s*externa\s*diagnostico\s*dias\s*inc\.?\s*inicio\s*finalizaci[oó]n\s*"
        r"([^\n]+)\n([^\n]+)\n(\d{1,3})\n(\d{1,2}/\d{1,2}/\d{4})\n(\d{1,2}/\d{1,2}/\d{4})",
        text,
    )
    if not m:
        return None
    origen, dx, dias, fi, ff = (g.strip() for g in m.groups())
    dxm = re.match(r"([A-Za-z0-9]{3,4})\s*(.*)$", dx)
    cie_raw = dxm.group(1).upper() if dxm else None
    desc = (dxm.group(2).strip() if dxm else dx) or None
    code, _fixes = _normalize_cie10(cie_raw) if cie_raw else (None, 99)
    dias_val = int(dias) if dias.isdigit() and 1 <= int(dias) <= 540 else None
    return {
        "origen": origen.replace("_", " ") or None,
        "cie10": code or cie_raw,  # cruda si el OCR perdió la letra inicial (p.ej. "0820")
        "descripcion": desc,
        "dias": dias_val,
        "fecha_inicio": _norm_date(fi),
        "fecha_fin": _norm_date(ff),
    }


class RuleBasedExtractor:
    """Extrae los campos con expresiones regulares ajustadas a incapacidades reales."""

    name = "rule-based"

    def extract(self, text: str) -> dict[str, Any]:
        if es_formato_permiso(text):
            return _extraer_permiso(text)
        rec = empty_record()
        t = text
        if es_formato_vacaciones(t):
            rec["tipo_documento"] = "vacaciones"

        # --- Paciente: documento (primer CC/TI/CE/PA/RC del paciente, evitando NITs
        #     de proveedor/empleador) + nombre inline justo después si lo hay. ---
        # Certificados EPS tipo Sura traen VARIOS "CC-######" en el mismo documento
        # (médico, tercero...) y el primero en aparecer no siempre es el paciente
        # (visto en un caso real: el 1º era ruido de OCR, el del paciente salía
        # después). "...IPS Afiliado" es la señal más fiable de cuál es el correcto
        # en ese formato — se prueba primero y, si no aparece, cae al genérico.
        # "C.C" con punto (historias clínicas tipo FCV): también es válido como CC.
        _TIPO_DOC = r"(?:C\.?C\.?|TI|CE|PA|RC)"
        doc = re.search(
            rf"(?<![A-Za-z])({_TIPO_DOC})[\s.\-:]*(\d{{6,12}})(?=[A-ZÑÁÉÍÓÚ\s]{{0,60}}I{{1,2}}PS\s*Afiliado)",
            t, re.I,
        )
        if not doc:
            doc = re.search(rf"(?<![A-Za-z])({_TIPO_DOC})[\s.\-:]*(\d{{6,12}})", t)
        if not doc:
            # "Cedula_Ciudadania Numero:1003391273" (historias clínicas tipo Clínica
            # del Cesar): tipo de documento escrito completo, no como sigla CC.
            m_ced = re.search(
                r"(?i)cedula[_\s]*(?:de\s*)?ciudadania\s*n[uú]mero\s*[:\-]?\s*(\d{6,12})", t
            )
            if m_ced:
                rec["paciente"]["documento_tipo"] = "CC"
                rec["paciente"]["documento_numero"] = m_ced.group(1)
        if doc:
            rec["paciente"]["documento_tipo"] = doc.group(1).upper().replace(".", "")
            rec["paciente"]["documento_numero"] = doc.group(2)
            after = t[doc.end():doc.end() + 60]
            mname = re.match(r"\s*([A-ZÑÁÉÍÓÚ][A-ZÑÁÉÍÓÚ ]{4,40})", after)
            if mname:
                rec["paciente"]["nombre"] = _clean_name(mname.group(1))
        if not rec["paciente"]["nombre"]:  # respaldo: línea con etiqueta "Paciente:"
            rec["paciente"]["nombre"] = _clean_name(
                _first(t, r"(?im)^.*paciente\s*[:\-]?\s*(.+)$")
            )

        # --- Entidad (EPS/Administradora/Aseguradora) e IPS prestador ---
        rec["entidad"]["eps"] = _first(
            t,
            r"(?im)(?:administrad(?:ora|\.)?|entidad(?:\s+promotora)?|aseguradora|\bEPS\b)"
            r"\s*[:\-,]?\s*(.+)$",
        )
        rec["entidad"]["ips_prestador"] = _first(t, r"(?im)^.*\bIPS\b\s*[:\-]?\s*(.+)$")

        # --- Fechas (3 formatos) ---
        rec["incapacidad"]["fecha_expedicion"] = _find_date(t, r"expedici[oó]n")
        # '[il]nic\w?(?:o|al|a)' tolera errores de OCR en "inicio/inicial/inicia/iniclal"
        # e incluso la I inicial leída como l minúscula ("lnicio", visualmente idéntica).
        # "Fecha de Emision" (formato Clínica Medical Duarte y similares): en licencias
        # de maternidad de ese formato la fecha de inicio es la de emisión del certificado.
        rec["incapacidad"]["fecha_inicio"] = _find_date(
            t, r"(?:fecha\s*(?:de\s*)?[il]nic\w?(?:o|al|a)|[il]nic\w?(?:o|al|a)\s*incapacidad|"
               r"fecha\s*de\s*emisi[oó]n|desde)"
        )
        rec["incapacidad"]["fecha_fin"] = _find_date(
            t, r"(?:fecha\s*(?:de\s*)?(?:termina|final|fin)|"
               r"(?:final|fin|termina\w*)\s*incapacidad|hasta)"
        )
        # Respaldo: fecha "escrita" en español sin año pegado (certificados EPS tipo
        # Sura, licencias de maternidad — ver _fecha_inicio_fin_escrita).
        if not rec["incapacidad"]["fecha_inicio"] or not rec["incapacidad"]["fecha_fin"]:
            fi_esc, ff_esc = _fecha_inicio_fin_escrita(t)
            if not rec["incapacidad"]["fecha_inicio"] and fi_esc:
                rec["incapacidad"]["fecha_inicio"] = fi_esc
                rec["incapacidad"]["_inicio_anclada"] = True  # viene del rótulo "Fecha Inicio"
            if not rec["incapacidad"]["fecha_fin"] and ff_esc:
                rec["incapacidad"]["fecha_fin"] = ff_esc
        # Respaldo: carta de notificación de vacaciones (fechas en prosa, ver arriba).
        if rec["tipo_documento"] == "vacaciones" and (
            not rec["incapacidad"]["fecha_inicio"] or not rec["incapacidad"]["fecha_fin"]
        ):
            fi_vac, ff_vac = _fechas_vacaciones(t)
            if not rec["incapacidad"]["fecha_inicio"] and fi_vac:
                rec["incapacidad"]["fecha_inicio"] = fi_vac
            if not rec["incapacidad"]["fecha_fin"] and ff_vac:
                rec["incapacidad"]["fecha_fin"] = ff_vac

        # --- Días: etiqueta o, como respaldo fiable, calculado desde las fechas ---
        # "Duracion" + nº (a veces seguido de las letras redundantes: "14-CATORCE").
        # Las cartas de vacaciones son prosa libre: "el dia siete (07) de julio" (un
        # DÍA DEL MES, no una duración) engañaría a estos patrones — para ese tipo de
        # documento se confía solo en la diferencia de fechas (ver más abajo).
        dias = None
        if rec["tipo_documento"] != "vacaciones":
            # (sin excluir \n: el valor suele quedar en la línea siguiente, "Duracion:\n126").
            dias = _first(t, r"(?i)duraci[oó]n\b[^\d]{0,10}(\d{1,3})")
            if not dias:
                dias = _first(t, r"(?i)d[ií]as?(?:\s*de\s*incapacidad)?\b[^\d\n]{0,15}(\d{1,3})")
            if not dias:
                dias = _first(t, r"(?i)(\d{1,3})\s*[\(\-]?\s*(?:un|dos|tres|cuatro|cinco|"
                                 r"seis|siete|ocho|nueve|diez|quince|veinte|treinta)\w*\s*d[ií]as?")
        dias_val = int(dias) if dias and dias.isdigit() else None
        dias_calc = _days_between(rec["incapacidad"]["fecha_inicio"], rec["incapacidad"]["fecha_fin"])
        rec["incapacidad"]["dias"] = dias_val if dias_val is not None else dias_calc

        # Layout de formulario (AM-Sistemas y similares): el rótulo "Dias Fecha Inicia" precede al valor
        # "<días><dd/mm/aaaa>" (a veces pegados: "511/06/2026" = 5 días + 11/06/2026).
        # Es el ancla MÁS fiable de la fecha de inicio (lo que pide el cliente: tomar
        # la que sea "Fecha Inicia / Fecha inicial").
        anc = re.search(r"(?i)d[ií]as?\s+fecha\s+[il]nic\w+", t)
        if anc:
            seg = t[anc.end():anc.end() + 160]
            dm = re.search(_DATE, seg)
            if dm:
                fi = _norm_date(dm.group(0))
                if fi:
                    rec["incapacidad"]["fecha_inicio"] = fi
                    rec["incapacidad"]["_inicio_anclada"] = True
                    # dígitos pegados justo delante de la fecha → nº de días
                    pre = re.search(r"(\d{1,3})$", seg[:dm.start()])
                    if pre and dias_val is None:
                        d = int(pre.group(1))
                        if 1 <= d <= 540:
                            rec["incapacidad"]["dias"] = d

        # tipo: preferir "Tipo (de) Incapacidad"; el respaldo genérico excluye
        # "Tipo de Usuario/DX/Atención" (lookahead negativo) para no capturar basura.
        rec["incapacidad"]["tipo"] = _first(t, r"(?im)^.*tipo\s*(?:de\s*)?incapacidad\s*[:\-]?\s*(.+)$") \
            or _first(t, r"(?im)^.*\btipo\b\s*[:\-]?\s*(?!\s*de\b)(.+)$")
        # origen restringido a valores conocidos (evita capturar líneas de basura).
        # Tolera el rótulo "Origen [de (la)] incapacidad" y el valor en la línea siguiente.
        rec["incapacidad"]["origen"] = _first(
            t, r"(?i)origen(?:\s+(?:de\s+)?(?:la\s+)?incapacidad)?[\s:\-]*\n?\s*"
               r"(com[uú]n|laboral|enfermedad\s+general|enfermedad\s+laboral|accidente\s+\w+)"
        )

        # --- Diagnóstico (CIE-10 + descripción) ---
        rec["diagnostico"]["cie10"] = _extract_cie10(t)
        if not rec["diagnostico"]["cie10"]:
            # Respaldo anclado a "Diagnostico principal" / "Diagnostico(s):": a veces
            # el OCR pierde POR COMPLETO la letra inicial del código (queda solo
            # dígitos, p.ej. "0039" en vez de "O039"). Se deja el valor CRUDO (sin
            # adivinar la letra) para que el auxiliar lo corrija — nunca se fabrica.
            raw_dx = _near_label(
                t, r"diagn[oó]stico(?:\s*principal|\(s\))?\s*[:\-]?", r"([A-Za-z0-9]{3,6})", window=20
            )
            if raw_dx:
                code, _fixes = _normalize_cie10(raw_dx)
                rec["diagnostico"]["cie10"] = code or raw_dx.upper()
        diag_line = _first(t, r"(?im)^.*(?:diagn[oó]stico|dx\s*p\w*|diag\.?\s*ppal)\s*[:\-]?\s*(.+)$")
        if diag_line:
            # quita un posible código (con o sin punto decimal) al inicio de la descripción
            desc = re.sub(r"^\s*[A-Za-z][0-9OoIiLlZzSs|]{2,3}(?:[.,][0-9OoIiLlZzSs|])?\s*[:\-]?\s*",
                          "", diag_line).strip(" :-")
            # "Diagnostico principal"/"relacionado"/"(s):" son encabezados de sección
            # en algunos formatos EPS (Sura, Medical Duarte), no una descripción real.
            if desc and desc.strip().lower() not in ("principal", "relacionado", "ppal", "(s)", "(s):"):
                rec["diagnostico"]["descripcion"] = desc

        # --- Tipo de Licencia (maternidad: PARTO VIABLE / PARTO NO VIABLE) — no es
        #     un campo del ERP, se lleva como observación (ver erp._observaciones).
        rec["incapacidad"]["tipo_licencia"] = _norm_tipo_licencia(
            _near_label(t, r"tipo\s*de\s*licencia\s*[:\-]?", r"([A-ZÑ][A-ZÑ .]{2,40})", window=60)
        )

        # --- Médico (límites de palabra: "dr" NO debe casar dentro de "alejanDRo") ---
        rec["medico"]["nombre"] = _clean_name(_first(
            t, r"(?im)^.*(?:\bm[eé]dico\b|\bdoctor\b|\bdr\.?\b|\bmedicina\s+general\b)\s*[:\-]?\s*"
               r"(?-i:([A-ZÑÁÉÍÓÚ][A-ZÑÁÉÍÓÚ ]{5,40}))"
        ))
        rec["medico"]["registro"] = _first(
            t, r"(?i)(?:registro(?:\s*m[eé]dico)?|reg\.?\s*med|r\.?\s*m\.?|tarjeta\s+profesional)"
               r"\s*[:\-.]?\s*([A-Z]*\d[\d\-]*)"
        )

        # --- Tabla "DETALLE DE LA INCAPACIDAD" (Clínica del Cesar y similares): si
        # está presente, sus valores son más fiables que las heurísticas genéricas de
        # arriba (evita el CIE-10/fecha que las reglas genéricas adivinaron mal).
        detalle = _extraer_detalle_incapacidad(t)
        if detalle:
            if detalle["cie10"]:
                rec["diagnostico"]["cie10"] = detalle["cie10"]
            if detalle["descripcion"]:
                rec["diagnostico"]["descripcion"] = detalle["descripcion"]
            if detalle["origen"]:
                rec["incapacidad"]["origen"] = detalle["origen"]
            if detalle["fecha_inicio"]:
                rec["incapacidad"]["fecha_inicio"] = detalle["fecha_inicio"]
                rec["incapacidad"]["_inicio_anclada"] = True
            if detalle["fecha_fin"]:
                rec["incapacidad"]["fecha_fin"] = detalle["fecha_fin"]
            if detalle["dias"]:
                rec["incapacidad"]["dias"] = detalle["dias"]

        return rec


# --------------------------------------------------------------------------- #
# Estrategia 2: LLM local (Ollama)
# --------------------------------------------------------------------------- #
INCAPACIDAD_PROMPT = """Eres un experto en extraer datos de CERTIFICADOS DE INCAPACIDAD MÉDICA de Colombia.
Analiza el texto y devuelve ÚNICAMENTE un JSON (sin markdown, sin texto extra) con esta estructura exacta:
{
  "paciente": {"nombre": "", "documento_tipo": "CC|TI|CE|PA|NIT|RC", "documento_numero": ""},
  "entidad": {"eps": "", "ips_prestador": ""},
  "incapacidad": {"fecha_inicio": "YYYY-MM-DD", "fecha_fin": "YYYY-MM-DD", "dias": 0,
                   "fecha_expedicion": "YYYY-MM-DD", "tipo": "", "origen": ""},
  "diagnostico": {"cie10": "", "descripcion": ""},
  "medico": {"nombre": "", "registro": ""}
}
Usa null si un campo no aparece. Las fechas en formato YYYY-MM-DD. 'dias' como número entero.

Texto del certificado:
"""


def parse_json_response(content: str) -> dict[str, Any]:
    """Extrae el JSON de la respuesta del modelo (tolera ```json``` y texto extra)."""
    content = content.strip()
    if content.startswith("```"):
        lines = content.split("\n")[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        content = "\n".join(lines)
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        start, end = content.find("{"), content.rfind("}") + 1
        if start != -1 and end > start:
            try:
                return json.loads(content[start:end])
            except json.JSONDecodeError:
                pass
    return {"error": "respuesta no-JSON del modelo", "raw": content}


class OllamaLLMExtractor:
    """Estructura el texto OCR con un LLM local servido por Ollama."""

    name = "ollama-llm"

    def __init__(
        self,
        base_url: str = "http://localhost:11434",
        model: str = "gemma3:4b",
        timeout: float = 300.0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout = timeout

    def extract(self, text: str) -> dict[str, Any]:
        import httpx  # import perezoso

        from .ocr import translate_ollama_error

        with httpx.Client(timeout=self.timeout) as client:
            try:
                resp = client.post(
                    f"{self.base_url}/api/chat",
                    json={
                        "model": self.model,
                        "messages": [
                            {"role": "user", "content": INCAPACIDAD_PROMPT + text}
                        ],
                        "stream": False,
                        "format": "json",  # fuerza JSON válido (Ollama) → estructurado fiable
                        "options": {"temperature": 0.0},
                    },
                )
                resp.raise_for_status()
            except (httpx.HTTPStatusError, httpx.RequestError) as e:
                raise translate_ollama_error(e, self.model, "texto") from e
            rec = parse_json_response(resp.json()["message"]["content"])
        # El LLM suele devolver el CIE-10 pegado y sin punto (M544, R074, A099);
        # lo normalizamos con la misma lógica robusta del extractor por reglas.
        diag = rec.get("diagnostico") if isinstance(rec, dict) else None
        if isinstance(diag, dict) and diag.get("cie10"):
            code, _ = _normalize_cie10(str(diag["cie10"]).replace(".", ""))
            if code:
                diag["cie10"] = code
        return rec


# --------------------------------------------------------------------------- #
# Estrategia 3: híbrido (reglas + LLM, fusionados campo a campo)
# --------------------------------------------------------------------------- #
# Combina lo mejor de cada uno SOBRE EL MISMO TEXTO OCR (rápido: no usa visión):
#   - Reglas mandan en fechas/documento/días: deterministas, NO alucinan.
#   - El LLM manda en nombre/EPS/CIE-10/origen/descripción: entiende el contexto.
# Más una guarda anti-alucinación de fechas del LLM.
# Campos donde las REGLAS mandan (patrones precisos, no alucinan). El resto lo
# prefiere el LLM (contexto). Las FECHAS y 'dias' se resuelven aparte (con anclaje
# al texto), porque el OCR puede romper rótulos y hacer que las reglas mal-asignen.
_RULE_PREFERRED = {
    ("paciente", "documento_numero"), ("paciente", "documento_tipo"),
}


def _empty(v: Any) -> bool:
    return v in (None, "", [], {})


def _safe_date(s: Any):
    from datetime import date
    if not isinstance(s, str):
        return None
    try:
        return date.fromisoformat(s)
    except ValueError:
        return None


def _dates_in_text(text: str) -> set[str]:
    """Conjunto de fechas (ISO) que REALMENTE aparecen en el texto OCR."""
    found = set()
    for m in re.finditer(_DATE, text):
        d = _norm_date(m.group(0))
        if d:
            found.add(d)
    return found


def _clean_origen(val: Any) -> str | None:
    """Normaliza 'origen' a un valor conocido; descarta basura (códigos, texto largo)."""
    if not isinstance(val, str) or not val.strip():
        return None
    low = val.lower()
    if "accidente" in low and "trabajo" in low:
        return "Accidente de trabajo"
    for kw, norm in (("común", "Común"), ("comun", "Común"), ("laboral", "Laboral"),
                     ("enfermedad general", "Enfermedad general"),
                     ("enfermedad laboral", "Enfermedad laboral")):
        if kw in low:
            return norm
    # Sospechoso de basura: contiene dígitos o es muy largo → se descarta.
    if re.search(r"\d", val) or len(val) > 30:
        return None
    return val.strip()


def _merge_records(rule_rec: dict[str, Any], llm_rec: dict[str, Any], text: str = "") -> dict[str, Any]:
    """Fusiona por campo: el preferido manda si no está vacío; si no, el otro."""
    out = empty_record()
    for section in out:
        rsec = rule_rec.get(section) or {}
        lsec = llm_rec.get(section) if isinstance(llm_rec, dict) else {}
        lsec = lsec or {}
        for key in out[section]:
            rv, lv = rsec.get(key), lsec.get(key)
            if (section, key) in _RULE_PREFERRED:
                out[section][key] = rv if not _empty(rv) else lv
            else:
                out[section][key] = lv if not _empty(lv) else rv

    inc = out["incapacidad"]
    rinc = rule_rec.get("incapacidad") or {}
    linc = (llm_rec.get("incapacidad") or {}) if isinstance(llm_rec, dict) else {}

    # --- Fechas: SOLO se ELIGEN aquí los mejores candidatos (anclaje anti-alucinación);
    #     la RECONCILIACIÓN (derivar inicio/fin/días con la regla del cliente) la hace
    #     normalizar_fechas() de forma única para todos los extractores.
    text_dates = _dates_in_text(text) if text else None

    def grounded(*cands: Any) -> str | None:
        for c in cands:
            if c and (text_dates is None or c in text_dates):
                return c
        return None

    # La fecha de inicio anclada al rótulo "Fecha Inicia/Inicial" (reglas) MANDA: es
    # justo lo que pide el cliente. Si no la hay, preferimos LLM y luego reglas (grounded).
    if rinc.get("_inicio_anclada"):
        inc["fecha_inicio"] = rinc.get("fecha_inicio")
        inc["_inicio_anclada"] = True
    else:
        inc["fecha_inicio"] = grounded(linc.get("fecha_inicio"), rinc.get("fecha_inicio"))
    inc["fecha_fin"] = grounded(linc.get("fecha_fin"), rinc.get("fecha_fin"))
    inc["fecha_expedicion"] = grounded(linc.get("fecha_expedicion"), rinc.get("fecha_expedicion"))

    # Días: si el inicio está anclado, confiamos en los días de reglas (mismo origen);
    #       si no, preferimos LLM y luego reglas.
    if rinc.get("_inicio_anclada") and not _empty(rinc.get("dias")):
        inc["dias"] = rinc.get("dias")
    else:
        lv, rv = linc.get("dias"), rinc.get("dias")
        inc["dias"] = lv if not _empty(lv) else rv

    # --- Origen: saneado a valores conocidos (el LLM a veces devuelve basura).
    inc["origen"] = _clean_origen(inc["origen"]) or _clean_origen(rinc.get("origen"))
    return out


def normalizar_fechas(rec: dict[str, Any]) -> dict[str, Any]:
    """Reconciliación ÚNICA de fechas/días (aplica a TODOS los extractores).

    Regla del cliente:
      • Tomar la fecha similar a "Fecha Inicia / Fecha inicial Incapacidad".
      • Si no se está seguro de la fecha de inicio → inicio = fin − (días − 1).
    Y, simétricamente, completa fin o días cuando faltan y se pueden derivar.
    Marca ``fecha_inicio_calculada`` cuando la fecha de inicio fue DERIVADA (no leída),
    para que el revisor lo vea.
    """
    from datetime import timedelta

    inc = rec.get("incapacidad")
    if not isinstance(inc, dict):
        return rec
    anclada = bool(inc.pop("_inicio_anclada", False))
    di, df = _safe_date(inc.get("fecha_inicio")), _safe_date(inc.get("fecha_fin"))
    raw_n = inc.get("dias")
    n = int(raw_n) if (isinstance(raw_n, int) or (isinstance(raw_n, str) and str(raw_n).isdigit())) else None
    if n is not None and not (1 <= n <= 540):
        n = None
    inc["fecha_inicio_calculada"] = False

    if di and n:
        # Inicio + días confiables → (re)derivar fin si falta o es inconsistente.
        if not df or df < di or (df - di).days + 1 != n:
            df = di + timedelta(days=n - 1)
            inc["fecha_fin"] = df.isoformat()
    elif df and n and not di:
        # Regla del cliente: fin + días, sin inicio → inicio = fin − (días − 1).
        di = df - timedelta(days=n - 1)
        inc["fecha_inicio"] = di.isoformat()
        inc["fecha_inicio_calculada"] = True
    elif di and df and not n:
        d = (df - di).days + 1
        if 1 <= d <= 540:
            inc["dias"] = d

    # Saneo final: rango imposible y sin días para arreglarlo → conservamos el dato
    # más fiable (el inicio si venía anclado al rótulo).
    di, df = _safe_date(inc.get("fecha_inicio")), _safe_date(inc.get("fecha_fin"))
    if di and df and not (0 <= (df - di).days <= 540):
        if anclada:
            inc["fecha_fin"] = None
        else:
            inc["fecha_inicio"] = None
    return rec


class HybridExtractor:
    """Reglas + LLM fusionados (rápido, sobre texto de RapidOCR).

    Si el LLM (Ollama) no está disponible, degrada con elegancia a solo reglas.
    """

    name = "hibrido"

    def __init__(self, llm: "OllamaLLMExtractor | None" = None) -> None:
        self.rule = RuleBasedExtractor()
        self.llm = llm

    def extract(self, text: str) -> dict[str, Any]:
        rule_rec = self.rule.extract(text)
        # Los PERMISOS son un formulario de casillas de layout fijo (no texto libre
        # médico): las reglas ya son deterministas y el LLM (prompt de incapacidad,
        # fusión con el esquema de incapacidad) no aporta ni aplica aquí.
        if rule_rec.get("tipo_documento") == "permiso":
            return rule_rec
        if self.llm is None:
            return rule_rec
        try:
            llm_rec = self.llm.extract(text)
        except Exception:  # noqa: BLE001 — Ollama caído/sin modelo → seguimos con reglas
            return rule_rec
        if not isinstance(llm_rec, dict) or "error" in llm_rec:
            return rule_rec
        return _merge_records(rule_rec, llm_rec, text)
