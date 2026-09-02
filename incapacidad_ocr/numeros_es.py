"""Numerales en español: leer la duración escrita en NÚMEROS, en LETRAS o en las dos.

Las incapacidades reales escriben los días de las dos formas —"2", "DOS" y
"DOS (2) DIAS"— y el OCR degrada unas veces el dígito y otras la palabra. Este
módulo es el LECTOR de esos numerales; NO decide nada de dominio: no aplica el
rango válido (1..540, eso lo impone quien valida) y no juzga si un desacuerdo
palabra↔dígito es fraude — solo lo reporta (``coincide=False``).

API pública (pequeña a propósito):

* ``normalizar(texto)``        → saneo tolerante al OCR (minúsculas, sin tildes,
                                 correcciones observadas, espacios colapsados).
* ``texto_a_entero(texto)``    → numeral en palabras → int (0..999) | None.
* ``duracion_en_texto(texto)`` → dict con el valor, su origen y la evidencia | None.
* ``numerales_en_texto(texto)``→ set de enteros PRESENTES en el texto (dígitos o
                                 palabras). NO son duraciones: es el material para
                                 la guarda de ANCLAJE del camino LLM.

**Por qué exige un ANCLA.** Un diccionario de numerales suelto dispara en la prosa
legal ("...se trate de UNA fuerza mayor..."), en las cantidades de insumos
("1 (Uno)"), en la edad ("31 ano(s), 3 mes(es), 22 dia(s)") y en la queja del
paciente ("hacetresdias" = "hace tres días", que es literalmente `<palabra> dias`).
Por eso ``duracion_en_texto`` solo acepta un valor cuando está justificado por la
UNIDAD pegada al valor (``... 2 DIAS``) o por un RÓTULO de duración
(``Dias de Incapacidad:``, ``Duracion``) en el MISMO renglón (o en un renglón
adyacente que contenga SOLO el valor). Esa restricción de renglón es la que evita
leer la rejilla "DIA / MES / ANO" de los formularios Sofisis como si fuera la
duración: no se puede relajar.

Todo lo que hay aquí sale de patrones vistos en documentos reales; el inventario
completo (formas A1..A10 / B1 / C1..C6, degradaciones del OCR y falsos positivos)
está en ``dataset-falsedad/duraciones/01_evidencia.md``.
"""
from __future__ import annotations

import re
from typing import Any

__all__ = ["normalizar", "texto_a_entero", "duracion_en_texto", "numerales_en_texto"]


# --------------------------------------------------------------------------- #
# 1. LÉXICO DE NUMERALES  (ampliable: una variante nueva = una línea)
# --------------------------------------------------------------------------- #
# PARA AÑADIR UNA VARIANTE NUEVA (p.ej. una forma femenina o un apócope que
# aparezca en un documento nuevo): añádela al diccionario que le corresponda por
# su papel gramatical. `texto_a_entero` compone a partir de estos cuatro grupos y
# NO hay que tocar su lógica.
#
# Nota de alcance: NO existe "mil" a propósito. En el corpus todos los numerales
# de miles escritos en palabras son AÑOS de una carta en prosa ("dos mil
# veintiseis (2026)"), nunca duraciones; dejarlo fuera hace que `texto_a_entero`
# devuelva None para un año, que es lo que se quiere.
_UNIDADES: dict[str, int] = {
    "cero": 0,
    "un": 1, "uno": 1, "una": 1,          # apócope + masculino/femenino
    "dos": 2, "tres": 3, "cuatro": 4, "cinco": 5, "seis": 6, "siete": 7,
    "ocho": 8, "nueve": 9,
}
# 10..29 no se componen: van de una pieza (y el 21..29 se escribe PEGADO).
_ESPECIALES: dict[str, int] = {
    "diez": 10, "once": 11, "doce": 12, "trece": 13, "catorce": 14, "quince": 15,
    "dieciseis": 16, "diecisiete": 17, "dieciocho": 18, "diecinueve": 19,
    "veinte": 20,
    "veintiun": 21, "veintiuno": 21, "veintiuna": 21,
    "veintidos": 22, "veintitres": 23, "veinticuatro": 24, "veinticinco": 25,
    "veintiseis": 26, "veintisiete": 27, "veintiocho": 28, "veintinueve": 29,
}
_DECENAS: dict[str, int] = {
    "treinta": 30, "cuarenta": 40, "cincuenta": 50, "sesenta": 60,
    "setenta": 70, "ochenta": 80, "noventa": 90,
}
# "cien" es exacto (100) y "ciento" es el prefijo compuesto ("ciento veinte").
_CENTENAS: dict[str, int] = {
    "cien": 100, "ciento": 100,
    "doscientos": 200, "doscientas": 200,
    "trescientos": 300, "trescientas": 300,
    "cuatrocientos": 400, "cuatrocientas": 400,
    "quinientos": 500, "quinientas": 500,
    "seiscientos": 600, "seiscientas": 600,
    "setecientos": 700, "setecientas": 700,
    "ochocientos": 800, "ochocientas": 800,
    "novecientos": 900, "novecientas": 900,
}
_LEXICO_NUMERAL: dict[str, int] = {**_UNIDADES, **_ESPECIALES, **_DECENAS, **_CENTENAS}


# --------------------------------------------------------------------------- #
# 2. SANEO TOLERANTE AL OCR  (ampliable: una degradación nueva = una línea)
# --------------------------------------------------------------------------- #
# PARA AÑADIR UNA CORRECCIÓN NUEVA: añade la pareja (patrón, reemplazo) a esta
# tupla, con un comentario que diga DÓNDE se observó. Solo van degradaciones
# REALES del corpus: inventar correcciones "por si acaso" es lo que hace que un
# parser empiece a leer duraciones donde no hay.
_CORRECCIONES_OCR: tuple[tuple[str, str], ...] = (
    # "Dias de incapacidad: 02 dos dia(s)" (Colsanitas) — la unidad se emite así
    # EN LA CAPA DE TEXTO DEL PDF, no es culpa del OCR.
    (r"d[ií]a\(s\)", "dias"),
    # "3Dian" (visto en un JPEG legítimo del corpus): la 's' final leída como 'n'.
    # Con frontera de palabra para NO tocar "Dianostico".
    (r"\bdian\b", "dias"),
    # "Dias de Incapacldad:" (PDF legítimo del corpus): la 'i' leída como 'l'.
    (r"incapac[il]dad", "incapacidad"),
    # Los documentos concretos NO se citan por cédula: este archivo se versiona y la
    # cédula es dato personal (Ley 1581). La trazabilidad vive en el manifiesto del
    # corpus, que queda fuera del repositorio.
)

# El OCR PEGA el valor al rótulo o a la preposición ("POR1DIA", "02dosdia(s)",
# "de2026"). Separar dígitos de letras deja tokens manejables sin tocar fechas
# (18/05/2026) ni códigos con punto.
_SEP_DIGITO_LETRA = re.compile(r"(?<=\d)(?=[a-z])")
_SEP_LETRA_DIGITO = re.compile(r"(?<=[a-z])(?=\d)")

# Traducción length-preserving (mantiene índices): tildes fuera. El OCR pierde la
# tilde de "DIAS" en TODO el corpus, pero las capas de texto de los PDF sí la
# traen → hay que aceptar las dos.
_SIN_TILDES = str.maketrans("áéíóúüñ", "aeiouun")


def normalizar(texto: str) -> str:
    """Saneo del texto antes de buscar numerales.

    Minúsculas, sin tildes, degradaciones conocidas del OCR corregidas, dígitos
    separados de letras y espacios colapsados. Los SALTOS DE LÍNEA se conservan:
    el renglón es la unidad de proximidad que separa una duración de la rejilla
    "DIA / MES / ANO" que viene debajo del rótulo en algunos formularios.
    """
    if not texto:
        return ""
    t = texto.replace("\r\n", "\n").replace("\r", "\n").lower().translate(_SIN_TILDES)
    t = _SEP_DIGITO_LETRA.sub(" ", t)
    t = _SEP_LETRA_DIGITO.sub(" ", t)
    for patron, repl in _CORRECCIONES_OCR:
        t = re.sub(patron, repl, t)
    t = re.sub(r"[^\S\n]+", " ", t)  # colapsa espacios/tabs SIN comerse los \n
    return "\n".join(linea.strip() for linea in t.split("\n"))


# --------------------------------------------------------------------------- #
# 3. PIEZAS DEL RECONOCEDOR
# --------------------------------------------------------------------------- #
# Alternación de palabras-numeral, la más larga primero ("veintiuno" antes que
# "veinte", "ciento" antes que "cien") para que gane la lectura más específica.
_ALT_PALABRAS = "|".join(sorted(_LEXICO_NUMERAL, key=len, reverse=True))
_RE_PAL = rf"(?:{_ALT_PALABRAS})"

# Palabras que el OCR deja PEGADAS justo después de la unidad; se listan para que
# "dia"/"dias" siga contando como token completo ("POR1DIAAPARTIRDE" → "1 dia").
# PARA AÑADIR UNA CONTINUACIÓN NUEVA: añádela aquí (una línea).
_CONTINUACIONES_PEGADAS: tuple[str, ...] = (
    "apartir", "desde", "hasta", "habiles", "calendario", "de",
)
#   (?![ \t]*[:\-])  "Dias:" / "DIAS -" es un RÓTULO (el valor viene después), no
#                    la unidad de un valor anterior. Sin esta guarda, el "1" de
#                    índice de fila que el OCR pega delante del rótulo
#                    ("1 DIAS: 30 (TREINTA)") se leería como duración.
_RE_UNIDAD = re.compile(
    r"dias?(?:(?![a-z])|(?=" + "|".join(_CONTINUACIONES_PEGADAS) + r"))(?![ \t]*[:\-])"
)

# Frase numeral: una o más palabras-numeral, con "y" opcional entre ellas
# ("treinta y cinco") y separadores opcionales, porque el OCR pega las palabras
# ("dosdias", "cientoveinte").
#   (?<![a-z])  la palabra NO puede venir pegada detrás de otras letras. Es la
#               guarda que rechaza "hacetresdias" (falso positivo nº1) sin
#               depender de un diccionario de contextos.
#   al final    debe cerrar en no-letra... salvo que lo que siga sea la UNIDAD
#               ("dosdias" es legítimo: palabra + unidad pegadas).
_RE_FRASE = (
    rf"(?<![a-z]){_RE_PAL}(?:\s*(?:y\s*)?{_RE_PAL})*(?:(?![a-z])|(?=dias?))"
)

# Número de días: 1..3 dígitos SUELTOS. Los lookarounds rechazan de raíz
#   • años y consecutivos: "2026" / "0081523489" (más de 3 dígitos),
#   • fechas y horas: el 29 de "29-07-26", el 23 de "08:23:39", el 25 de
#     "25/05/2026" (dígito pegado a / - . : por cualquiera de los dos lados).
# Ese solo guardarraíl cierra los falsos positivos nº6 (año leído como duración)
# y nº11 (números de trámite).
_RE_NUM = r"(?<!\d)(?<![\d][/.\-:])\d{1,3}(?!\d)(?![/.\-:]\d)"

# Formas de valor, EN ORDEN DE PRIORIDAD: primero las mixtas (traen doble
# evidencia), luego las sueltas. PARA AÑADIR UNA FORMA NUEVA: añade su patrón
# aquí, con los grupos <num> y/o <pal>.
_PATRONES_VALOR: tuple[str, ...] = (
    # C1 "2 (DOS DIAS)" · C2 "02 dos dia(s)" · C3 "30 (TREINTA)" · C4 "14 - CATORCE"
    rf"(?P<num>{_RE_NUM})\s*[\(\[\-–]?\s*(?P<pal>{_RE_FRASE})",
    # C5 "DOS (02)" — la PALABRA va primero y el número entre paréntesis.
    rf"(?P<pal>{_RE_FRASE})\s*[\(\[]\s*(?P<num>{_RE_NUM})\s*[\)\]]?",
    # A1..A9 — solo dígitos.
    rf"(?P<num>{_RE_NUM})",
    # B1 "-DOS" — solo la palabra: el OCR se comió el dígito. Es el único caso del
    # corpus donde leer letras es la ÚNICA forma de tener el dato.
    rf"(?P<pal>{_RE_FRASE})",
)

# Rótulos que anuncian una duración. PARA AÑADIR UN RÓTULO NUEVO: añádelo aquí.
# \s* (no \s+) en todas: el OCR pega las palabras del rótulo
# ("DIASDEINCAPACIDAD"). El rótulo escueto "Dias" exige : o - para no confundirse
# con la unidad que va DESPUÉS del valor ("... 2 Dias").
_ETIQUETAS_DURACION: tuple[str, ...] = (
    r"dias?\s*de\s*incapacidad",          # A1/A10/C2/C5 (SYSNET, Colsanitas, Sofisis)
    r"dias?\s*incapacidad",               # A10 ("Dias Incapacidad", sin "de")
    r"dias?\s*inc\.?",                    # tabla "DETALLE DE LA INCAPACIDAD"
    r"no\.?\s*total\s*(?:de\s*)?dias?",   # A10 ("No.Total dias:")
    r"duracion",                          # A4/B1/C4 (Sura, Medical Duarte)
    r"dias?\s*[:\-]",                     # A2/C1/C3/C6 ("Dias:3", "DIAS: 30 (TREINTA)")
)
_RE_ETIQUETAS = tuple(re.compile(p) for p in _ETIQUETAS_DURACION)

# Contextos que INVALIDAN un candidato: si alguno aparece en el trozo de renglón
# que precede al valor, eso no es una duración. Cada uno viene de un falso
# positivo real del corpus. PARA AÑADIR UN VETO NUEVO: añádelo aquí.
_CONTEXTOS_PROHIBIDOS: tuple[str, ...] = (
    r"\bedad\b",                    # nº2  "Edad: 33 Ano(s), 1 mes(es), 8 dia(s)"
    r"\bhace",                      # nº1  "...desdo hacetresdias'." (queja del paciente)
    r"\bvig\b|vigencia",            # nº4  "Vig: 1 dia" (vigencia de la dosis)
    r"mes\(es\)|\bmes(?:es)?\b",    # nº2  "1 mes(es), 8 dia(s)"
    r"ano\(s\)|\banos?\b",          # nº15 "24 anos 05 meses"
    r"\bhoras?\b",                  # nº9  permisos por horas
    r"semanas?|gestacional",        # nº10 "EDADGESTASIONAL: 40.00 Semanas"
    r"\bcada\b",                    # nº9  "CADA 8 HORAS"
)
_RE_VETO = re.compile("|".join(_CONTEXTOS_PROHIBIDOS))

# Lo que NO puede haber ENTRE el rótulo y el valor: si hay una preposición de
# rango, lo que sigue es una FECHA, no la duración (falso positivo nº5:
# "POR 4 DIAS DESDE EL 29-07-26" devolvía 29).
_RE_ENTRE_PROHIBIDO = re.compile(r"desde|hasta|a\s*partir|apartir|vigencia")

_VENTANA_IZQ = 40       # contexto a la izquierda del valor que se revisa (chars)
_VENTANA_ETIQUETA = 25  # cuánto se mira tras el rótulo, en su MISMO renglón


# --------------------------------------------------------------------------- #
# 4. NUMERAL EN PALABRAS → ENTERO
# --------------------------------------------------------------------------- #
_RE_TOKEN = re.compile(rf"(?:{_ALT_PALABRAS}|y)")
_SEPARADORES_TOKEN = " \t\n-–().:,"


def _tokenizar(texto: str) -> list[str] | None:
    """Parte un numeral en sus palabras. None si aparece algo que no es numeral.

    Tolera que el OCR las pegue ("cientoveinte") y los separadores que mete el
    formato ("14 - CATORCE", "(DOS)"). Que un solo token desconocido invalide
    TODO es deliberado: "dos mil veintiseis" (un año) y "dosdias" deben dar None.
    """
    toks: list[str] = []
    i, n = 0, len(texto)
    while i < n:
        if texto[i] in _SEPARADORES_TOKEN:
            i += 1
            continue
        m = _RE_TOKEN.match(texto, i)
        if not m:
            return None
        toks.append(m.group(0))
        i = m.end()
    return toks or None


def _combinar(palabras: list[str]) -> int | None:
    """Compone [centena] [especial | decena [y unidad] | unidad] → 0..999."""
    total, i, n = 0, 0, len(palabras)
    if palabras[0] in _CENTENAS:
        total += _CENTENAS[palabras[0]]
        exacta = palabras[0] == "cien"  # "cien" no admite resto ("cien veinte" no existe)
        i = 1
        if exacta and i < n:
            return None
    if i < n:
        p = palabras[i]
        if p in _ESPECIALES:
            total += _ESPECIALES[p]
            i += 1
        elif p in _DECENAS:
            total += _DECENAS[p]
            i += 1
            if i < n:
                # La "y" es OPCIONAL: el OCR la pierde ("treinta cinco").
                if palabras[i] == "y":
                    i += 1
                unidad = _UNIDADES.get(palabras[i]) if i < n else None
                if not unidad:  # 0 incluido: "treinta y cero" no existe
                    return None
                total += unidad
                i += 1
        elif p in _UNIDADES:
            total += _UNIDADES[p]
            i += 1
        else:
            return None
    return total if i == n else None


def texto_a_entero(texto: str | None) -> int | None:
    """Numeral escrito en palabras → entero (0..999). None si no es un numeral.

    Cubre unidades, 10..29 (incluidos los pegados "veintiuno"), decenas con "y"
    ("treinta y cinco"), centenas ("cien", "ciento veinte", "quinientos cuarenta")
    y los apócopes ("un", "veintiun"). NO impone rango de días: 0 y 999 son
    respuestas válidas; el rango 1..540 lo aplica quien valida.
    """
    if not texto:
        return None
    palabras = _tokenizar(normalizar(texto))
    if not palabras:
        return None
    return _combinar(palabras)


# --------------------------------------------------------------------------- #
# 5. DURACIÓN EN UN FRAGMENTO DE TEXTO
# --------------------------------------------------------------------------- #
def _armar(letra: int | None, numero: int | None, evidencia: str) -> dict[str, Any]:
    """Resultado en la forma pública. ``valor`` prefiere el DÍGITO cuando hay los
    dos, porque en las 6 formas mixtas del corpus el dígito es el campo y la
    palabra la redundancia entre paréntesis o tras el guion. El desacuerdo NO se
    resuelve aquí: se reporta con ``coincide=False`` para que otro módulo decida
    (la evidencia lo señala como posible adulteración)."""
    if letra is not None and numero is not None:
        origen, coincide, valor = "ambos", letra == numero, numero
    elif numero is not None:
        origen, coincide, valor = "numero", None, numero
    else:
        origen, coincide, valor = "letra", None, letra
    return {
        "valor": valor,
        "origen": origen,
        "letra": letra,
        "numero": numero,
        "coincide": coincide,
        # Trozo NORMALIZADO que justificó la lectura (para auditar/depurar; es
        # texto del documento, no se debe loguear: PII de salud, Ley 1581).
        "evidencia": evidencia.strip()[:80],
    }


def _leer_valor(seg: str, al_final: bool) -> tuple[int | None, int | None, int, int] | None:
    """Primera forma de valor que casa en ``seg`` → (letra, numero, ini, fin).

    ``al_final=True`` exige que el valor TERMINE donde acaba el segmento (se usa
    cuando el segmento es lo que precede a la unidad: en "... 2 (DOS DIAS)" el
    valor es lo pegado a "DIAS", no un número cualquiera del renglón).
    """
    cola = r"\s*[\(\[\-–]?\s*$" if al_final else ""
    for patron in _PATRONES_VALOR:
        m = re.search(patron + cola, seg)
        if not m:
            continue
        grupos = m.groupdict()
        crudo_pal, crudo_num = grupos.get("pal"), grupos.get("num")
        letra = texto_a_entero(crudo_pal) if crudo_pal else None
        if crudo_pal and letra is None:
            continue  # lo capturado no compone un numeral válido ("cien veinte")
        numero = int(crudo_num) if crudo_num else None
        if letra is None and numero is None:
            continue
        return letra, numero, m.start(), m.end()
    return None


def _es_linea_de_valor(linea: str) -> bool:
    """True si el renglón contiene SOLO el valor ("DOS (02)", "126", "-DOS").

    Es lo que permite leer el valor del renglón de al lado sin abrir la puerta a
    la rejilla "DIA / MES / ANO" (falso positivo nº7): esos renglones traen
    palabras que no son numerales, así que no pasan por aquí.
    """
    if not linea.strip():
        return False
    if not (re.search(r"\d", linea) or re.search(_RE_FRASE, linea)):
        return False
    resto = re.sub(_RE_FRASE, " ", linea)
    resto = re.sub(r"[\d\s()\[\]\-–.:,]", "", resto)
    return not resto


def _candidatos_por_unidad(idx: int, linea: str) -> list[tuple[tuple[int, int, int], dict[str, Any]]]:
    """Valor pegado a la UNIDAD ("POR 4 DIAS", "2 (DOS DIAS)", "02 dos dia(s)")."""
    salida = []
    for m in _RE_UNIDAD.finditer(linea):
        ctx = linea[:m.start()][-_VENTANA_IZQ:]
        if not ctx.strip() or _RE_VETO.search(ctx):
            continue
        leido = _leer_valor(ctx, al_final=True)
        if not leido:
            continue
        letra, numero, ini, _fin = leido
        rec = _armar(letra, numero, ctx[ini:] + m.group(0))
        salida.append(((0 if rec["origen"] == "ambos" else 1, idx, m.start()), rec))
    return salida


def _candidatos_por_etiqueta(idx: int, lineas: list[str]) -> list[tuple[tuple[int, int, int], dict[str, Any]]]:
    """Valor anclado a un RÓTULO de duración, en su renglón o en uno adyacente."""
    salida = []
    linea = lineas[idx]
    for rx in _RE_ETIQUETAS:
        for m in rx.finditer(linea):
            if _RE_VETO.search(linea[:m.start()][-_VENTANA_IZQ:]):
                continue
            seg = linea[m.end():m.end() + _VENTANA_ETIQUETA]
            leido = _leer_valor(seg, al_final=False)
            if leido:
                letra, numero, ini, fin = leido
                if _RE_ENTRE_PROHIBIDO.search(seg[:ini]):
                    continue  # lo que sigue al rótulo es una fecha, no la duración
                # C6 (Colsubsidio): el dígito en el renglón del rótulo y la
                # palabra en el siguiente ("Dias de Incapacidad:  2" ⏎ "DOS").
                if letra is None and idx + 1 < len(lineas) and _es_linea_de_valor(lineas[idx + 1]):
                    vecino = _leer_valor(lineas[idx + 1], al_final=False)
                    if vecino and vecino[0] is not None and vecino[1] is None:
                        letra = vecino[0]
                rec = _armar(letra, numero, m.group(0) + seg[:fin])
            else:
                # A4/C5: el valor quedó en el renglón SIGUIENTE ("DURACION:" ⏎ "126").
                # B1/C4: o en el ANTERIOR, porque el OCR de tabla invierte el orden
                # de lectura en el formato Sura ("-DOS" ⏎ "Duracion").
                vecinos = [i for i in (idx + 1, idx - 1) if 0 <= i < len(lineas)]
                vecino_ok = next((i for i in vecinos if _es_linea_de_valor(lineas[i])), None)
                if vecino_ok is None:
                    continue
                leido = _leer_valor(lineas[vecino_ok], al_final=False)
                if not leido:
                    continue
                letra, numero, ini, fin = leido
                rec = _armar(letra, numero, m.group(0) + " " + lineas[vecino_ok])
            salida.append(((0 if rec["origen"] == "ambos" else 1, idx, m.start()), rec))
    return salida


def duracion_en_texto(texto: str | None) -> dict[str, Any] | None:
    """Lee la duración de un fragmento. None si no hay ninguna justificada.

    Devuelve ``{"valor", "origen", "letra", "numero", "coincide", "evidencia"}``:

    * ``origen``  : "numero" | "letra" | "ambos" (la forma mixta "DOS (2) DIAS").
    * ``coincide``: solo con origen "ambos" — True/False según cuadren palabra y
      dígito; None cuando solo hay uno de los dos. Un ``False`` es una SEÑAL para
      otro módulo (aquí no se decide nada).
    * ``evidencia``: el trozo normalizado que justificó la lectura.

    Se prefiere la forma MIXTA sobre las sueltas (doble evidencia) y, a igualdad,
    la primera del texto. Recibe un FRAGMENTO: si se le pasa el documento entero
    y hay varias duraciones (pasa en PDFs adulterados), devuelve una sola.
    """
    if not texto:
        return None
    lineas = normalizar(texto).split("\n")
    candidatos: list[tuple[tuple[int, int, int], dict[str, Any]]] = []
    for idx, linea in enumerate(lineas):
        candidatos.extend(_candidatos_por_unidad(idx, linea))
        candidatos.extend(_candidatos_por_etiqueta(idx, lineas))
    if not candidatos:
        return None
    candidatos.sort(key=lambda c: c[0])
    return candidatos[0][1]


# --------------------------------------------------------------------------- #
# 6. ENTEROS PRESENTES EN EL TEXTO  (material para la guarda de ANCLAJE del LLM)
# --------------------------------------------------------------------------- #
def numerales_en_texto(texto: str | None) -> set[int]:
    """Todos los enteros 0..999 que se pueden LEER en el texto: dígitos y palabras.

    OJO: esto NO son duraciones — aquí NO se exige ancla, a propósito. Es el
    conjunto de valores que el documento contiene, y sirve para la guarda de
    ANCLAJE del camino LLM (``extract._merge_records``): igual que una fecha del
    modelo solo se acepta si aparece en el texto OCR, la duración que devuelve el
    modelo solo se acepta si su EXPRESIÓN —el dígito ("2") o la palabra ("DOS")—
    está de verdad en el documento. Es condición NECESARIA, no suficiente: quien
    elige el valor es la política de fusión.

    Se reutilizan los mismos guardarraíles del módulo: ``_RE_NUM`` (máximo 3
    cifras y nunca pegado a ``/ - . :``, así un año o un consecutivo no anclan
    nada) y el léxico de numerales de ``_RE_FRASE``.
    """
    if not texto:
        return set()
    t = normalizar(texto)
    valores = {int(m.group(0)) for m in re.finditer(_RE_NUM, t)}
    for m in re.finditer(_RE_FRASE, t):
        toks = _tokenizar(m.group(0))
        valor = _combinar(toks) if toks else None
        if valor is not None:
            valores.add(valor)
    return valores
