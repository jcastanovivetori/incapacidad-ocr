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
        "paciente": {"nombre": None, "documento_tipo": None, "documento_numero": None},
        "entidad": {"eps": None, "ips_prestador": None},
        "incapacidad": {
            "fecha_inicio": None,
            "fecha_fin": None,
            "dias": None,
            "fecha_expedicion": None,
            "tipo": None,
            "origen": None,
        },
        "diagnostico": {"cie10": None, "descripcion": None},
        "medico": {"nombre": None, "registro": None},
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


def _norm_date(value: str | None) -> str | None:
    """Normaliza a YYYY-MM-DD desde dd/mm/yyyy, yyyy-mm-dd o dd-mmm-yy(yy)."""
    if not value:
        return None
    value = value.strip()
    m = re.fullmatch(r"(\d{4})-(\d{2})-(\d{2})", value)
    if m:
        return value
    m = re.fullmatch(r"(\d{1,2})[/-](\d{1,2})[/-](\d{4})", value)
    if m:
        d, mo, y = m.groups()
        return f"{y}-{int(mo):02d}-{int(d):02d}"
    # dd-mmm-yy(yy): 10-jun-26, 10-jun26, 10 Jun.2026
    m = re.fullmatch(r"(\d{1,2})[\s.\-]*([A-Za-zÁÉÍÓÚáéíóú]{3})[a-z]*[\s.\-]*(\d{2,4})", value)
    if m:
        d, mon, y = m.groups()
        mo = _MONTHS_ES.get(mon[:3].lower())
        if mo:
            year = y if len(y) == 4 else f"20{y}"
            return f"{year}-{mo}-{int(d):02d}"
    return None


# Patrón de fecha que tolera los tres formatos vistos en documentos reales.
_DATE = r"(\d{4}-\d{2}-\d{2}|\d{1,2}[/-]\d{1,2}[/-]\d{4}|\d{1,2}[\s.\-]*[A-Za-z]{3}[a-z]*[\s.\-]*\d{2,4})"


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
    return _norm_date(before.group(1)) if before else None


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


def _clean_name(raw: str | None) -> str | None:
    if not raw:
        return None
    name = _NAME_STOP.split(raw)[0]
    name = re.sub(r"\s{2,}", " ", name).strip(" .:-")
    name = re.sub(r"\s+[A-ZÑ]$", "", name).strip()  # quita letra suelta final (p.ej. "R" de Registro)
    return name or None


class RuleBasedExtractor:
    """Extrae los campos con expresiones regulares ajustadas a incapacidades reales."""

    name = "rule-based"

    def extract(self, text: str) -> dict[str, Any]:
        rec = empty_record()
        t = text

        # --- Paciente: documento (primer CC/TI/CE/PA/RC del paciente, evitando NITs
        #     de proveedor/empleador) + nombre inline justo después si lo hay. ---
        doc = re.search(r"(?<![A-Za-z])(CC|TI|CE|PA|RC)[\s.\-:]*(\d{6,12})", t)
        if doc:
            rec["paciente"]["documento_tipo"] = doc.group(1).upper()
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
        # 'inic\w?(?:o|al|a)' tolera errores de OCR en "inicio/inicial/inicia/iniclal".
        rec["incapacidad"]["fecha_inicio"] = _find_date(
            t, r"(?:fecha\s*(?:de\s*)?inic\w?(?:o|al|a)|inic\w?(?:o|al|a)\s*incapacidad|desde)"
        )
        rec["incapacidad"]["fecha_fin"] = _find_date(
            t, r"(?:fecha\s*(?:de\s*)?(?:termina|final|fin)|"
               r"(?:final|fin|termina\w*)\s*incapacidad|hasta)"
        )

        # --- Días: etiqueta o, como respaldo fiable, calculado desde las fechas ---
        dias = _first(t, r"(?i)d[ií]as?(?:\s*de\s*incapacidad)?\b[^\d\n]{0,15}(\d{1,3})")
        if not dias:
            dias = _first(t, r"(?i)(\d{1,3})\s*[\(\-]?\s*(?:un|dos|tres|cuatro|cinco|"
                             r"seis|siete|ocho|nueve|diez|quince|veinte|treinta)\w*\s*d[ií]as?")
        dias_val = int(dias) if dias and dias.isdigit() else None
        dias_calc = _days_between(rec["incapacidad"]["fecha_inicio"], rec["incapacidad"]["fecha_fin"])
        rec["incapacidad"]["dias"] = dias_val if dias_val is not None else dias_calc

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
        diag_line = _first(t, r"(?im)^.*(?:diagn[oó]stico|dx\s*p\w*|diag\.?\s*ppal)\s*[:\-]?\s*(.+)$")
        if diag_line:
            # quita un posible código (con o sin punto decimal) al inicio de la descripción
            desc = re.sub(r"^\s*[A-Za-z][0-9OoIiLlZzSs|]{2,3}(?:[.,][0-9OoIiLlZzSs|])?\s*[:\-]?\s*",
                          "", diag_line).strip(" :-")
            rec["diagnostico"]["descripcion"] = desc or None

        # --- Médico (límites de palabra: "dr" NO debe casar dentro de "alejanDRo") ---
        rec["medico"]["nombre"] = _clean_name(_first(
            t, r"(?im)^.*(?:\bm[eé]dico\b|\bdoctor\b|\bdr\.?\b|\bmedicina\s+general\b)\s*[:\-]?\s*"
               r"(?-i:([A-ZÑÁÉÍÓÚ][A-ZÑÁÉÍÓÚ ]{5,40}))"
        ))
        rec["medico"]["registro"] = _first(
            t, r"(?i)(?:registro(?:\s*m[eé]dico)?|reg\.?\s*med|r\.?\s*m\.?|tarjeta\s+profesional)"
               r"\s*[:\-.]?\s*([A-Z]*\d[\d\-]*)"
        )
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

    # --- Fechas: preferir LLM, luego reglas, pero SOLO si la fecha aparece en el
    #     texto OCR (anclaje anti-alucinación). Resuelve también el caso en que un
    #     rótulo roto por el OCR hace que las reglas mal-asignen una fecha.
    text_dates = _dates_in_text(text) if text else None

    def _resolve_date(key: str) -> str | None:
        for cand in (linc.get(key), rinc.get(key)):
            if cand and (text_dates is None or cand in text_dates):
                return cand
        return None

    inc["fecha_inicio"] = _resolve_date("fecha_inicio")
    inc["fecha_fin"] = _resolve_date("fecha_fin")
    inc["fecha_expedicion"] = _resolve_date("fecha_expedicion")

    # Rango imposible (negativo o > 540 días) → descarta el inicio (probable error).
    di, df = _safe_date(inc["fecha_inicio"]), _safe_date(inc["fecha_fin"])
    if di and df and not (0 <= (df - di).days <= 540):
        inc["fecha_inicio"] = None
        di = None

    # --- Días: recalcular desde el rango si es válido (lo más fiable); si no,
    #     usar el valor del LLM o, en su defecto, el de reglas.
    if di and df and 0 <= (df - di).days <= 540:
        inc["dias"] = (df - di).days + 1
    else:
        lv, rv = linc.get("dias"), rinc.get("dias")
        inc["dias"] = lv if not _empty(lv) else rv

    # --- Deriva la fecha faltante desde 'dias' + la otra fecha, SOLO si el
    #     resultado aparece en el texto OCR (anclaje): recupera, p.ej.,
    #     inicio = fin - (dias-1) cuando el OCR rompió el rótulo de inicio.
    from datetime import timedelta
    n = inc["dias"]
    if isinstance(n, int) and 1 <= n <= 540 and text_dates:
        di, df = _safe_date(inc["fecha_inicio"]), _safe_date(inc["fecha_fin"])
        if df and not di:
            cand = (df - timedelta(days=n - 1)).isoformat()
            if cand in text_dates:
                inc["fecha_inicio"] = cand
        elif di and not df:
            cand = (di + timedelta(days=n - 1)).isoformat()
            if cand in text_dates:
                inc["fecha_fin"] = cand

    # --- Origen: saneado a valores conocidos (el LLM a veces devuelve basura).
    inc["origen"] = _clean_origen(inc["origen"]) or _clean_origen(rinc.get("origen"))
    return out


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
        if self.llm is None:
            return rule_rec
        try:
            llm_rec = self.llm.extract(text)
        except Exception:  # noqa: BLE001 — Ollama caído/sin modelo → seguimos con reglas
            return rule_rec
        if not isinstance(llm_rec, dict) or "error" in llm_rec:
            return rule_rec
        return _merge_records(rule_rec, llm_rec, text)
