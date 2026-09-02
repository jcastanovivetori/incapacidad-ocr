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
* ``duracion_de_celda(celda)`` → igual, para una CELDA de tabla (ancla POSICIONAL:
                                 la celda solo puede contener el valor).
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

**El ancla NO es suficiente.** En un certificado la palabra "días" aparece muchas
veces y casi ninguna es la duración de la incapacidad: plazos de trámite ("3 dias
habiles"), validez del certificado, recomendaciones ("control en 3 dias"), relato
clínico ("3 dias de evolucion") y la fórmula de cierre notarial ("a los 15 dias del
mes de agosto"). Por eso el candidato se veta por los DOS lados —``_RE_VETO`` justo
antes del valor y ``_RE_VETO_DER`` justo después— y el rótulo ``Duracion`` no vale
si lo que sigue está medido en HORAS, SEMANAS o MESES.

Todo lo que hay aquí sale de patrones vistos en documentos reales; el inventario
completo (formas A1..A10 / B1 / C1..C6, degradaciones del OCR y falsos positivos)
está en ``dataset-falsedad/duraciones/01_evidencia.md``.
"""
from __future__ import annotations

import re
from typing import Any

__all__ = ["normalizar", "texto_a_entero", "duracion_en_texto", "duracion_de_celda",
           "numerales_en_texto"]


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
    # "Dias de Incapacldad:" (PDF legítimo del corpus): la 'i' leída como 'l'.
    (r"incapac[il]dad", "incapacidad"),
    # "D1AS" / "DlAS": la I de DIAS leída como 1 o como l. Solo el token PLURAL y
    # SUELTO: un "d1a"/"dla" DENTRO de otra cosa (un código, unas iniciales) no se
    # toca, porque convertirlo en "dia" fabricaría una unidad de días donde no hay.
    (r"(?<![a-z])d[1l]as(?![a-z])", "dias"),
    # NO se corrige "3Dian" ('s' final leída como 'n'): medido sobre las 44 entradas
    # reales del corpus (31 textos OCR + 13 capas de texto de PDF), esa corrección
    # cambia el resultado en UNA sola entrada —otro documento, y para peor: deja el
    # renglón del REGISTRO PROFESIONAL como "… 1 dias" y lo lee como una duración de
    # 1 día, que además hace que `normalizar_fechas` sobrescriba la fecha fin del
    # documento. En el documento que la motivaba los días ya salían del rango de
    # fechas, así que quitarla no cuesta nada.
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
    if not isinstance(texto, str) or not texto:
        return ""
    t = texto.replace("\r\n", "\n").replace("\r", "\n").lower().translate(_SIN_TILDES)
    # Las correcciones van ANTES de separar dígitos de letras: "D1AS" es una sola
    # palabra rota por dentro y, una vez separada ("d 1 as"), ya no hay nada que
    # corregir. Ninguna de las otras correcciones depende de la separación.
    for patron, repl in _CORRECCIONES_OCR:
        t = re.sub(patron, repl, t)
    t = _SEP_DIGITO_LETRA.sub(" ", t)
    t = _SEP_LETRA_DIGITO.sub(" ", t)
    t = re.sub(r"[^\S\n]+", " ", t)  # colapsa espacios/tabs SIN comerse los \n
    return "\n".join(linea.strip() for linea in t.split("\n"))


# --------------------------------------------------------------------------- #
# 3. PIEZAS DEL RECONOCEDOR
# --------------------------------------------------------------------------- #
# Alternación de palabras-numeral, la más larga primero ("veintiuno" antes que
# "veinte", "ciento" antes que "cien") para que gane la lectura más específica.
# Es la alternación del LÉXICO (la que compone valores); la de la FRASE va más abajo
# y añade "mil", que se reconoce pero no compone.
_ALT_PALABRAS = "|".join(sorted(_LEXICO_NUMERAL, key=len, reverse=True))

# Palabras que el OCR deja PEGADAS justo después de la unidad; se listan para que
# "dia"/"dias" siga contando como token completo ("POR1DIAAPARTIRDE" → "1 dia").
# PARA AÑADIR UNA CONTINUACIÓN NUEVA: añádela aquí (una línea).
_CONTINUACIONES_PEGADAS: tuple[str, ...] = (
    "apartir", "desde", "hasta", "habiles", "calendario", "de",
)
# La UNIDAD como token completo: "dias"/"dia" seguido de no-letra o de una de las
# continuaciones que el OCR pega. Ya NO lleva la guarda `(?![ \t]*[:\-])` que tenía
# antes: descartar la unidad por el simple hecho de que la siga un separador
# también tiraba el valor que iba DELANTE ("INCAPACIDAD: 3 DIAS - INICIA 01/09/2026"
# se perdía). Distinguir el rótulo "DIAS:" de la unidad es cosa de
# `_es_rotulo_no_unidad`, que mira si detrás del separador hay de verdad un valor.
_UNIDAD = r"dias?(?:(?![a-z])|(?=" + "|".join(_CONTINUACIONES_PEGADAS) + r"))"
_RE_UNIDAD = re.compile(_UNIDAD)

# Frase numeral: una o más palabras-numeral, con "y" opcional entre ellas
# ("treinta y cinco") y separadores opcionales, porque el OCR pega las palabras
# ("dosdias", "cientoveinte").
#   (?<![a-z])  la palabra NO puede venir pegada detrás de otras letras. Es la
#               guarda que rechaza "hacetresdias" (falso positivo nº1) sin
#               depender de un diccionario de contextos.
#   al final    debe cerrar en no-letra... salvo que lo que siga sea la UNIDAD
#               ("dosdias" es legítimo: palabra + unidad pegadas). Se exige la
#               unidad COMPLETA: con un simple `(?=dias?)` la frase cerraba dentro
#               de cualquier palabra que empezara por "dia" y "dosdiagnosticos"
#               anclaba un 2.
# "mil" entra en la ALTERNACIÓN pero NO en el léxico: así la frase captura el
# millar entero ("dos mil veintiseis", "mil ochenta") y `texto_a_entero` la rechaza
# completa. Si no estuviera aquí, la frase casaría solo con el fragmento y un AÑO
# escrito en palabras se leería como duración (80, 2).
_ALT_FRASE = "|".join(sorted([*_LEXICO_NUMERAL, "mil"], key=len, reverse=True))
_RE_PAL_FRASE = rf"(?:{_ALT_FRASE})"
_RE_FRASE = (
    rf"(?<![a-z]){_RE_PAL_FRASE}(?:\s*(?:y\s*)?{_RE_PAL_FRASE})*(?:(?![a-z])|(?={_UNIDAD}))"
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
# con la unidad que va DESPUÉS del valor ("... 2 Dias") y exige el PLURAL: en los
# formularios colombianos "Dia:" en singular es SIEMPRE un campo de fecha
# ("Dia: 27 Mes: 08 Ano: 2026") o prosa ("se expide el dia: 27"), nunca una
# duración, así que aceptarlo devolvía el día del mes (falso positivo nº7).
# `duracion` cierra en no-letra o en una continuación pegada conocida: sin eso el
# rótulo casaba dentro de "Duraciones anteriores: 9".
# Los de VARIAS palabras van aparte porque tienen un uso extra: si el OCR los emite
# PEGADOS ("DIASDEINCAPACIDAD") es un CAMPO de formulario, y entonces ese "dias" es
# la cabeza del rótulo y no la unidad de un valor anterior (el "3" de
# "3 DIASDEINCAPACIDAD" es el índice de fila). En prosa las palabras van separadas
# —"se otorgan 5 dias de incapacidad"— y ahí sí es la unidad: el espacio es lo que
# distingue los dos casos (ver `_es_rotulo_no_unidad`).
_ETIQUETAS_VARIAS_PALABRAS: tuple[str, ...] = (
    r"dias?\s*de\s*incapacidad",          # A1/A10/C2/C5 (SYSNET, Colsanitas, Sofisis)
    r"dias?\s*incapacidad",               # A10 ("Dias Incapacidad", sin "de")
    r"no\.?\s*total\s*(?:de\s*)?dias?",   # A10 ("No.Total dias:")
)
_ETIQUETAS_DURACION: tuple[str, ...] = (
    *_ETIQUETAS_VARIAS_PALABRAS,
    r"dias?\s*inc\.?",                    # tabla "DETALLE DE LA INCAPACIDAD"
    r"duracion(?:(?![a-z])|(?=de|dias?|total))",   # A4/B1/C4 (Sura, Medical Duarte)
    r"dias\s*[:\-]",                      # A2/C1/C3/C6 ("Dias:3", "DIAS: 30 (TREINTA)")
)


def _rx_etiqueta(patron: str) -> re.Pattern[str]:
    """Compila un rótulo con su frontera izquierda OBLIGATORIA.

    El rótulo no puede empezar dentro de otra palabra ("GUARDIAS: 3", "MEDIAS: 2"
    no son duraciones). Cuesta un lookbehind, y como el saneo separa siempre dígito
    de letra, "3 DIASDEINCAPACIDAD" sigue casando.
    """
    return re.compile(r"(?<![a-z])(?:" + patron + r")")


_RE_ETIQUETAS = tuple(_rx_etiqueta(p) for p in _ETIQUETAS_DURACION)
_RE_ETIQUETAS_PEGADAS = tuple(_rx_etiqueta(p) for p in _ETIQUETAS_VARIAS_PALABRAS)

# Contextos que INVALIDAN un candidato: si alguno aparece JUSTO ANTES del valor (o
# del rótulo), eso no es una duración. Cada uno viene de un falso positivo real del
# corpus o de su clase. PARA AÑADIR UN VETO NUEVO: añádelo aquí.
_CONTEXTOS_PROHIBIDOS: tuple[str, ...] = (
    r"\bedad\b",                    # nº2  "Edad: 33 Ano(s), 1 mes(es), 8 dia(s)"
    r"\bhace",                      # nº1  "...desdo hacetresdias'." (queja del paciente)
    r"\bvig\b|vigencia",            # nº4  "Vig: 1 dia" (vigencia de la dosis)
    r"valid[oa]\b|validez",         # "certificado valido por 30 dias" (no es la incapacidad)
    r"mes\(es\)|\bmes(?:es)?\b",    # nº2  "1 mes(es), 8 dia(s)"
    r"ano\(s\)|\banos?\b",          # nº15 "24 anos 05 meses"
    r"\bhoras?\b|\bhrs?\b|\bminutos?\b",   # nº9  permisos y órdenes médicas por horas
    r"semanas?|gestacion",          # nº10 "EDADGESTASIONAL: 40.00 Semanas"
    r"\bcada\b",                    # nº9  "CADA 8 HORAS"
    r"\bcontrol\b",                 # recomendación ("CONTROL EN 3 DIAS"), no la incapacidad
    r"\bradicar",                   # nota de trámite impresa en el propio certificado
    r"\btratamiento\b",             # "DURACION DEL TRATAMIENTO: 7 DIAS" es la fórmula médica
)
_RE_VETO = re.compile("|".join(_CONTEXTOS_PROHIBIDOS))

# Contextos que invalidan el candidato por la DERECHA. Son imprescindibles: la
# palabra "días" aparece muchas veces en un certificado y casi ninguna es la
# duración de la incapacidad, y lo que la distingue va DETRÁS del valor —"3 dias
# HABILES" es un plazo de trámite, "15 dias DEL MES de agosto" la fórmula de cierre
# notarial, "3 dias DE EVOLUCION" el relato clínico (en el corpus está la misma
# frase en horas), y "4 HORAS"/"40 SEMANAS"/"3 MESES" son otra unidad de tiempo que
# el rótulo `Duracion` alcanzaba sin que nada lo vetara.
_MESES_ES_RE = (r"enero|febrero|marzo|abril|mayo|junio|julio|agosto|septiembre|"
                r"setiembre|octubre|noviembre|diciembre")
_CONTEXTOS_PROHIBIDOS_DER: tuple[str, ...] = (
    r"horas?|hrs?|minutos?|min(?![a-z])",       # otra unidad ("DURACION DEL PERMISO: 4 HORAS")
    r"semanas?|meses|mes(?![a-z])",             # "Duracion del tratamiento: 3 meses"
    r"anos?(?![a-z])",                          # "Duracion aproximada: 2 anos"
    r"habiles",                                 # plazo de radicación ("3 dias habiles")
    r"del\s*mes",                               # cierre notarial ("a los 15 dias del mes de…")
    rf"de\s*(?:{_MESES_ES_RE})",                # día del mes ("el dia 27 de agosto")
    r"de\s*evolucion",                          # relato clínico ("3 dias de evolucion")
    r"de\s*(?:validez|vigencia|plazo)",         # validez del certificado
)
# El `(?:dias?[ \t]*)?` deja que la unidad quede en medio ("Dias: 3 dias habiles").
_RE_VETO_DER = re.compile(
    r"[ \t]*(?:dias?[ \t]*)?(?:" + "|".join(_CONTEXTOS_PROHIBIDOS_DER) + r")"
)

# Lo que NO puede haber ENTRE el rótulo y el valor:
#  • una preposición de rango → lo que sigue es una FECHA, no la duración (falso
#    positivo nº5: "POR 4 DIAS DESDE EL 29-07-26" devolvía 29);
#  • el complemento de OTRA duración → "DURACION DEL TRATAMIENTO / DEL EMBARAZO /
#    DE LA CONSULTA / DEL PERMISO" no es la duración de la INCAPACIDAD (en los
#    permisos la duración se mide en HORAS y los días salen del rango de fechas).
#    Ningún rótulo real del corpus lleva estas palabras entre el rótulo y el valor.
_RE_ENTRE_PROHIBIDO = re.compile(
    r"desde|hasta|a\s*partir|apartir|vigencia|tratamiento|embarazo|gestacion|"
    r"consulta|permiso"
)

_VENTANA_IZQ = 40       # contexto a la izquierda del valor donde se busca (chars)
_VENTANA_VETO = 14      # cuánto se mira JUSTO ANTES del valor/rótulo para vetarlo
_VENTANA_ETIQUETA = 25  # a qué distancia del rótulo puede EMPEZAR el valor
# …y cuánto puede OCUPAR ese valor. Los dos límites son necesarios y distintos: el
# primero es proximidad al rótulo, el segundo espacio para el valor entero
# ("DOSCIENTOS CINCUENTA Y CINCO (255)" son 34 caracteres). Además acotan el trozo
# de renglón que ve el motor de regex: con el renglón completo, la forma C5 (frase
# numeral + paréntesis) es cuadrática y un renglón artificial de 58 KB con "dos y
# dos y …" tardaba minutos.
_COLA_VALOR = 48
# Un renglón que contiene SOLO el valor no necesita más que esto; por encima, no es
# un renglón de valor (y así el mismo coste queda acotado en los vecinos).
_MAX_LINEA_VALOR = 80

# ¿La frase numeral seguía más allá del corte del segmento? Entonces se ha leído un
# PREFIJO, y el prefijo de un numeral español siempre vale MENOS que el total
# ("CIENTO OCHENTA" → 100): antes que un valor redondo y creíble, ninguno.
_RE_FRASE_SIGUE = re.compile(rf"\s*(?:y\s*)?{_RE_PAL_FRASE}")


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
            # Formas analíticas arcaicas, corrientes en la redacción jurídica
            # colombiana: "diez y seis" (16), "veinte y uno" (21). Solo con los
            # redondos 10 y 20 y solo con la "y" EXPLÍCITA: "diez seis" no existe
            # (sería un dato inventado) y "quince y dos" tampoco.
            if p in ("diez", "veinte") and i + 1 < n and palabras[i] == "y":
                unidad = _UNIDADES.get(palabras[i + 1])
                if unidad:  # 0 excluido: "diez y cero" no existe
                    total += unidad
                    i += 2
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

    Cualquier entrada que no sea ``str`` devuelve None en vez de reventar: por aquí
    pasan valores del JSON del LLM, donde el tipo no está garantizado.
    """
    if not isinstance(texto, str) or not texto:
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
    """Valor MÁS A LA IZQUIERDA de ``seg`` → (letra, numero, ini, fin).

    Se elige por POSICIÓN y, a igualdad de posición, por la forma con más evidencia
    (la mixta antes que la suelta: en "2 (DOS)" las dos empiezan en el mismo sitio).
    Antes se devolvía la primera FORMA que casara en cualquier parte del segmento, y
    eso hacía que una lectura posterior e irrelevante ganara a la duración real.

    ``al_final=True`` exige que el valor TERMINE donde acaba el segmento (se usa
    cuando el segmento es lo que precede a la unidad: en "... 2 (DOS DIAS)" el
    valor es lo pegado a "DIAS", no un número cualquiera del renglón).
    """
    cola = r"\s*[\(\[\-–]?\s*$" if al_final else ""
    mejor: tuple[tuple[int, int], tuple[int | None, int | None, int, int]] | None = None
    for prioridad, patron in enumerate(_PATRONES_VALOR):
        for m in re.finditer(patron + cola, seg):
            grupos = m.groupdict()
            crudo_pal, crudo_num = grupos.get("pal"), grupos.get("num")
            letra = texto_a_entero(crudo_pal) if crudo_pal else None
            if crudo_pal and letra is None:
                # Lo capturado no compone un numeral válido ("cien veinte", "dos mil
                # veintiseis"): se sigue buscando MÁS ADELANTE con este mismo patrón.
                continue
            numero = int(crudo_num) if crudo_num else None
            if letra is None and numero is None:
                continue
            clave = (m.start(), prioridad)
            if mejor is None or clave < mejor[0]:
                mejor = (clave, (letra, numero, m.start(), m.end()))
            break  # de este patrón ya tenemos su primer match VÁLIDO
    return mejor[1] if mejor else None


def _valor_de_linea(linea: str) -> tuple[int | None, int | None, int, int] | None:
    """Lectura de un renglón que contiene SOLO el valor ("DOS (02)", "126", "-DOS").

    Es lo que permite tomar el valor del renglón de al lado sin abrir la puerta a la
    rejilla "DIA / MES / ANO" (falso positivo nº7). Dos condiciones:

    * en el renglón no hay palabras ajenas (solo el numeral, la unidad y separadores), y
    * hay UN SOLO valor: "15 09 2026" o "27 08 2026" es un trozo de FECHA repartido
      en columnas —el OCR emite renglones así— y trae dos números, así que se
      rechaza. Antes cualquiera de ellos se leía como duración.
    """
    if not linea.strip() or len(linea) > _MAX_LINEA_VALOR:
        return None
    leido = _leer_valor(linea, al_final=False)
    if not leido:
        return None
    _letra, _numero, ini, fin = leido
    resto = re.sub(_RE_UNIDAD, " ", linea[:ini] + " " + linea[fin:])  # la unidad sí acompaña
    if re.search(_RE_NUM, resto) or re.search(_RE_FRASE, resto):
        return None  # hay OTRO valor en el renglón → no es un renglón de valor
    return leido if not re.sub(r"[\d\s()\[\]\-–.:,]", "", resto) else None


def _es_rotulo_no_unidad(linea: str, m: re.Match[str]) -> bool:
    """True si ese "dias" es la cabeza de un RÓTULO y no la unidad de un valor previo.

    Dos formas, las dos observadas: (a) el rótulo de varias palabras que el OCR
    emitió PEGADO ("3 DIASDEINCAPACIDAD" → el 3 es el índice de fila y el valor lo
    perdió el OCR; en prosa el rótulo va separado y ahí sí es la unidad), y (b)
    "DIAS:" / "DIAS -" con un valor DETRÁS ("1 DIAS: 30 (TREINTA)", falso positivo
    nº9). En (b) se comprueba que el valor exista de verdad: si no, "3 DIAS - INICIA
    01/09/2026" perdería el 3.
    """
    for rx in _RE_ETIQUETAS_PEGADAS:
        r = rx.match(linea, m.start())
        if r and not re.search(r"\s", r.group(0)):
            return True
    cola = linea[m.end():]
    sep = re.match(r"[ \t]*[:\-]", cola)
    return bool(sep and _leer_valor(cola[sep.end():sep.end() + _VENTANA_ETIQUETA], al_final=False))


def _candidatos_por_unidad(idx: int, linea: str) -> list[tuple[tuple[int, int, int], dict[str, Any]]]:
    """Valor pegado a la UNIDAD ("POR 4 DIAS", "2 (DOS DIAS)", "02 dos dia(s)")."""
    salida = []
    for m in _RE_UNIDAD.finditer(linea):
        if _es_rotulo_no_unidad(linea, m):
            continue
        pre = linea[:m.start()]
        ctx = pre[-_VENTANA_IZQ:]
        if not ctx.strip():
            continue
        leido = _leer_valor(ctx, al_final=True)
        if not leido:
            continue
        letra, numero, ini, _fin = leido
        # El veto se mide JUSTO ANTES del valor (no en todo el contexto): un "horas"
        # o un "mes" al principio del renglón no invalida una duración que está al
        # final ("Reposo 24 horas y se otorgan 5 dias de incapacidad" son 5 días).
        abs_ini = len(pre) - len(ctx) + ini
        if _RE_VETO.search(linea[max(0, abs_ini - _VENTANA_VETO):abs_ini]):
            continue
        if _RE_VETO_DER.match(linea[m.end():]):
            continue  # "3 dias habiles", "15 dias del mes de agosto": no es la duración
        rec = _armar(letra, numero, ctx[ini:] + m.group(0))
        salida.append(((idx, m.start(), 0 if rec["origen"] == "ambos" else 1), rec))
    return salida


def _candidatos_por_etiqueta(idx: int, lineas: list[str]) -> list[tuple[tuple[int, int, int], dict[str, Any]]]:
    """Valor anclado a un RÓTULO de duración, en su renglón o en uno adyacente."""
    salida = []
    linea = lineas[idx]
    for rx in _RE_ETIQUETAS:
        for m in rx.finditer(linea):
            if _RE_VETO.search(linea[max(0, m.start() - _VENTANA_VETO):m.start()]):
                continue
            # La ventana acota dónde puede EMPEZAR el valor; el valor tiene ADEMÁS su
            # propio espacio (_COLA_VALOR). Con una sola ventana corta, una frase
            # numeral larga se leía a medias, y el prefijo de un numeral español
            # siempre vale MENOS que el total ("CIENTO OCHENTA" → 100, "DOSCIENTOS
            # CINCUENTA Y CINCO (255)" → 250): un valor redondo, en rango y sin
            # ninguna señal de que faltaba texto.
            resto_linea = linea[m.end():]
            seg = resto_linea[:_VENTANA_ETIQUETA + _COLA_VALOR]
            leido = _leer_valor(seg, al_final=False)
            if leido and leido[2] >= _VENTANA_ETIQUETA:
                continue  # hay un valor, pero demasiado lejos del rótulo: no es suyo
            if leido and leido[3] >= len(seg) and _RE_FRASE_SIGUE.match(resto_linea, leido[3]):
                continue  # el numeral seguía más allá del corte: no se lee a medias
            if leido:
                letra, numero, ini, fin = leido
                entre = seg[:ini]
                if _RE_ENTRE_PROHIBIDO.search(entre) or _RE_VETO.search(entre):
                    continue  # lo que sigue al rótulo es una fecha u OTRA duración
                if _RE_VETO_DER.match(seg[fin:]):
                    continue  # la unidad escrita a la derecha no son días
                # C6 (Colsubsidio): el dígito en el renglón del rótulo y la
                # palabra en el siguiente ("Dias de Incapacidad:  2" ⏎ "DOS").
                if letra is None and idx + 1 < len(lineas):
                    vecino = _valor_de_linea(lineas[idx + 1])
                    if vecino and vecino[0] is not None and vecino[1] is None:
                        letra = vecino[0]
                rec = _armar(letra, numero, m.group(0) + seg[:fin])
            else:
                # A4/C5: el valor quedó en el renglón SIGUIENTE ("DURACION:" ⏎ "126").
                # B1/C4: o en el ANTERIOR, porque el OCR de tabla invierte el orden
                # de lectura en el formato Sura ("-DOS" ⏎ "Duracion"). Se prueban los
                # DOS vecinos: quedarse con el primero que "parezca" renglón de valor
                # hacía que un consecutivo en el renglón siguiente tapara el valor del
                # anterior — y ése es justo el caso donde la palabra es el único dato.
                rec = None
                for j in (idx + 1, idx - 1):
                    if not 0 <= j < len(lineas):
                        continue
                    vecino = _valor_de_linea(lineas[j])
                    if vecino:
                        rec = _armar(vecino[0], vecino[1], m.group(0) + " " + lineas[j])
                        break
                if rec is None:
                    continue
            salida.append(((idx, m.start(), 0 if rec["origen"] == "ambos" else 1), rec))
    return salida


def duracion_en_texto(texto: str | None) -> dict[str, Any] | None:
    """Lee la duración de un fragmento. None si no hay ninguna justificada.

    Devuelve ``{"valor", "origen", "letra", "numero", "coincide", "evidencia"}``:

    * ``origen``  : "numero" | "letra" | "ambos" (la forma mixta "DOS (2) DIAS").
    * ``coincide``: solo con origen "ambos" — True/False según cuadren palabra y
      dígito; None cuando solo hay uno de los dos. Un ``False`` es una SEÑAL para
      otro módulo (aquí no se decide nada).
    * ``evidencia``: el trozo normalizado que justificó la lectura.

    Gana el candidato que aparece PRIMERO en el orden de lectura (renglón, columna)
    y, a igualdad de posición, la forma MIXTA sobre las sueltas (doble evidencia).
    Al contrario: preferir la mixta ANTES que la posición hacía que un "3 (TRES)" de
    cualquier otra parte del documento le quitara el campo a la duración real.
    Recibe un FRAGMENTO: si se le pasa el documento entero y hay varias duraciones
    (pasa en PDFs adulterados), devuelve una sola.
    """
    if not isinstance(texto, str) or not texto:
        return None
    lineas = normalizar(texto).split("\n")
    candidatos: list[tuple[tuple[int, int, int], dict[str, Any]]] = []
    for idx, linea in enumerate(lineas):
        candidatos.extend(_candidatos_por_unidad(idx, linea))
        candidatos.extend(_candidatos_por_etiqueta(idx, lineas))
    if not candidatos:
        return None
    candidatos.sort(key=lambda c: c[0])
    elegido = candidatos[0][1]
    if elegido["letra"] is None and elegido["numero"] is not None:
        # La palabra puede estar en OTRO renglón: el formato repite la duración en
        # prosa ("…INCAPACIDAD POR 2 DIAS", que va ANTES) y en el campo con las dos
        # escrituras ("Dias: 2 (DOS DIAS)"). Se toma la palabra de ese otro candidato
        # solo si acompaña AL MISMO dígito; con otro dígito es otra cosa del
        # documento y hacerla pasar por confirmación sería fabricar evidencia. Si la
        # palabra no cuadra con el dígito, el desacuerdo se registra (no se resuelve).
        for _clave, otro in candidatos[1:]:
            if otro["letra"] is not None and otro["numero"] == elegido["numero"]:
                return _armar(otro["letra"], elegido["numero"],
                              f"{elegido['evidencia']} + {otro['evidencia']}")
    return elegido


def duracion_de_celda(celda: str | None) -> dict[str, Any] | None:
    """Duración de una CELDA de tabla, donde el ancla es la POSICIÓN (columna fija).

    Misma forma de resultado que ``duracion_en_texto``. No se exige rótulo ni unidad
    —los da la tabla, y es un ancla más fiable que cualquier rótulo— pero SÍ que la
    celda contenga ÚNICAMENTE el valor: "3", "TRES", "3 (TRES)", "02 dos dia(s)",
    "DOS (02)". Cuando el OCR desplaza el bloque, en esa columna caen un CIE-10
    ("J069"), una dosis ("X 500 MG") o una paginación ("1 de 1"), y ninguno es una
    duración: darle a la celda un rótulo prestado ("Dias: " + celda) las leía como
    69, 500 y 1.
    """
    if not isinstance(celda, str) or not celda.strip():
        return None
    lineas = normalizar(celda).split("\n")
    if len(lineas) != 1:
        return None  # una celda es UN renglón; varios significan que el bloque bailó
    leido = _valor_de_linea(lineas[0])
    if not leido:
        return None
    return _armar(leido[0], leido[1], lineas[0])


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
    nada) y el léxico de numerales de ``_RE_FRASE`` — que incluye "mil" como pieza
    de la frase pero no del léxico, así que un AÑO escrito en palabras ("dos mil
    veintiseis") tampoco ancla nada (antes anclaba el 2 y el 26).
    """
    if not isinstance(texto, str) or not texto:
        return set()
    t = normalizar(texto)
    valores = {int(m.group(0)) for m in re.finditer(_RE_NUM, t)}
    for m in re.finditer(_RE_FRASE, t):
        toks = _tokenizar(m.group(0))
        valor = _combinar(toks) if toks else None
        if valor is not None:
            valores.add(valor)
    return valores
