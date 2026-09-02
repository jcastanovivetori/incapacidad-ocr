"""Caza de duraciones INVENTADAS: ataque al lector de dias (numeros + letras).

Verificador (NO implementador): este script no toca el paquete, solo lo interroga.

Cada caso declara la ENTRADA exacta, lo ESPERADO y lo que se OBTIENE, y se compara
ademas contra los DOS patrones historicos que tenia `_dias_por_etiqueta` antes del
cambio, para poder decir si un falso positivo es NUEVO (regresion) o PREEXISTENTE.

Sin PII: los fragmentos son sinteticos o recortes de estructura de documentos
reales (nombre de archivo + patron de texto, nunca nombres/cedulas/diagnosticos).

Uso:
    .venv/Scripts/python.exe 01_ataque_falsos_positivos.py
"""
from __future__ import annotations

import sys
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
OCR = Path(str(_DATASET / "ocr"))
sys.path.insert(0, str(REPO))

from incapacidad_ocr.erp import mapear_a_staging  # noqa: E402
from incapacidad_ocr.extract import (  # noqa: E402
    HybridExtractor, RuleBasedExtractor, _dias_de_celda, _first, normalizar_fechas,
)
from incapacidad_ocr.numeros_es import duracion_en_texto, numerales_en_texto  # noqa: E402

# --- Los DOS patrones que `_dias_por_etiqueta` tenia ANTES del cambio (con su
#     captura original `(\d{1,3})`, sin el guardarrail `_NUM_DIAS`). Sirven para
#     separar "falso positivo nuevo" de "falso positivo de siempre".
VIEJO_1 = r"(?i)duraci[oó]n\b[^\d]{0,10}(\d{1,3})"
VIEJO_2 = r"(?i)d[ií]as?(?:\s*de\s*incapacidad)?\b[^\d\n]{0,15}(\d{1,3})"

CAB = "CERTIFICADO DE INCAPACIDAD MEDICA\nPaciente: <NOMBRE> PEREZ\nCC 1098765432\n"

_fallos: list[str] = []
_n = 0


def antes(texto: str) -> int | None:
    """Lo que habrian leido los patrones historicos (simulacion del pre-cambio)."""
    for pat in (VIEJO_1, VIEJO_2):
        v = _first(texto, pat)
        if v and v.isdigit():
            return int(v)
    return None


def caso(titulo: str, texto: str, esperado: int | None, *, frag: str = "") -> None:
    """Corre el pipeline de reglas + reconciliacion y compara con lo esperado."""
    global _n
    _n += 1
    rec = normalizar_fechas(RuleBasedExtractor().extract(texto))
    inc = rec["incapacidad"]
    ok = inc["dias"] == esperado
    prev = antes(texto)
    marca = "OK  " if ok else ("FP  " if prev != inc["dias"] else "fp- ")
    if not ok:
        _fallos.append(titulo)
    print(f"  [{marca}] {titulo}")
    print(f"          entrada  : {frag or texto.replace(chr(10), ' | ')[:110]}")
    print(f"          esperado : dias={esperado}   obtenido: dias={inc['dias']} "
          f"letra={inc['dias_letra']} coin={inc['dias_letra_coincide']} "
          f"tipo={rec['tipo_documento']} ini={inc['fecha_inicio']} fin={inc['fecha_fin']}")
    if not ok:
        print(f"          pre-cambio (patrones viejos): dias={prev}"
              f"   -> {'REGRESION (antes None/correcto)' if prev != inc['dias'] else 'PREEXISTENTE'}")


def solo_modulo(titulo: str, frag: str, esperado: int | None) -> None:
    """Interroga el LECTOR (`numeros_es.duracion_en_texto`) sobre un fragmento."""
    global _n
    _n += 1
    r = duracion_en_texto(frag)
    val = r["valor"] if r else None
    ok = val == esperado
    if not ok:
        _fallos.append(titulo)
    print(f"  [{'OK  ' if ok else 'FP  '}] {titulo}")
    print(f"          entrada  : {frag!r}")
    ev = repr(r["evidencia"]) if r else "-"
    print(f"          esperado : {esperado}   obtenido: {val}"
          f"   evidencia={ev}   pre-cambio={antes(frag)}")


def fila(titulo: str, texto: str) -> None:
    """Muestra la FILA de staging que se escribiria (impacto en nomina)."""
    o = mapear_a_staging({"incapacidad": normalizar_fechas(RuleBasedExtractor().extract(texto))})
    r = o["row"]
    # ¿queda alguna señal para el revisor? El único aviso que puede delatar el dato
    # inventado es `fecha_fin_recalculada`, y solo existe si el documento TRAÍA un fin.
    recalc = any("re-deriv" in p for p in o["problemas"])
    print(f"  {titulo:46s} Numerodias={str(r.get('Numerodias')):4s} "
          f"fechainicio={r.get('fechainicio')} fechavencimiento={r.get('fechavencimiento')} "
          f"aviso_fin_recalculada={recalc}")


# =========================================================================== #
def h1_unidad_sin_contexto() -> None:
    """H1: cualquier '<N> DIAS' del documento se toma como LA duracion."""
    print("\n[H1] La UNIDAD pegada al valor no distingue la duracion de la incapacidad")
    print("     de cualquier otra mencion de dias. El veto solo mira a la IZQUIERDA.")
    # Precedente real de esta clase de frase impresa en el certificado: la nota de
    # tramite de `falsas/FALSA-10.txt` linea 25
    # ("Favortramitar la incapacidad antes de 72 horas") — en HORAS ahi, pero la
    # misma nota escrita en DIAS entra como duracion.
    for frag, esp in [
        ("La incapacidad debe radicarse dentro de los 3 dias habiles siguientes", None),
        ("Debe radicarse dentro de los tres dias habiles siguientes", None),
        ("Este certificado es valido por 30 dias", None),
        ("RECOMENDACIONES: CONTROL EN 3 DIAS POR CONSULTA EXTERNA", None),
        ("RECOMENDACIONES: CONTROL EN TRES DIAS", None),
        ("CUADRO CLINICO DE 3 DIAS DE EVOLUCION", None),
        ("CUADRO CLINICO DE TRES DIAS DE EVOLUCION", None),
        ("SE RECOMIENDA REPOSO POR 2 DIAS", None),
        ("Dada en Malambo a los 15 dias del mes de agosto de 2026", None),
        ("Dada en Malambo a los quince (15) dias del mes de agosto de 2026", None),
        ("Dada en Malambo a los quince dias del mes de agosto", None),
    ]:
        solo_modulo(f"'{frag[:52]}...'", frag, esp)

    print("\n     -- y end-to-end, sobre un rotulo SIN valor (forma A10 del corpus,"
          "\n        7 de los 31 textos): el dato inventado sustituye al ausente")
    caso("A10 + 'valido por 30 dias'",
         CAB + "Dias de Incapacidad:\nEste certificado es valido por 30 dias\n"
               "Fecha Inicial: 10/06/2026\n", None)
    caso("A10 + 'CONTROL EN 3 DIAS'",
         CAB + "Dias de Incapacidad:\nRECOMENDACIONES: CONTROL EN 3 DIAS\n"
               "Fecha Inicial: 10/06/2026\n", None)

    print("\n     -- lo PEOR: el falso positivo GANA al rotulo verdadero cuando aparece"
          "\n        antes en el orden de lectura del OCR (empate roto por nº de renglon)")
    caso("boilerplate de cierre ANTES del rotulo real (correcto = 2)",
         CAB + "Dada en Malambo a los 15 dias del mes de agosto de 2026\n"
               "Dias de Incapacidad: 2\nFecha Inicial: 10/06/2026\nFecha Final: 11/06/2026\n", 2)
    caso("el mismo texto con el boilerplate DESPUES (control: sale bien)",
         CAB + "Dias de Incapacidad: 2\nFecha Inicial: 10/06/2026\nFecha Final: 11/06/2026\n"
               "Dada en Malambo a los 15 dias del mes de agosto de 2026\n", 2)


def h2_rotulo_duracion() -> None:
    """H2: 'duracion' casa como palabra suelta y alcanza OTRA duracion."""
    print("\n[H2] El rotulo `duracion` es una palabra suelta y la ventana de 25 chars"
          "\n     alcanza el valor de una duracion que NO es la incapacidad."
          "\n     (los patrones viejos usaban una ventana de 10 chars sin digitos)")
    for frag, esp in [
        ("DURACION DEL PERMISO: 4 HORAS", None),
        ("DURACION: CUATRO HORAS", None),
        ("Duracion del reposo en horas: 8", None),
        ("DURACION DEL EMBARAZO: 40 SEMANAS", None),
        ("Duracion gestacion: 39 semanas", None),
        ("DURACION DE LA CONSULTA: 20 MINUTOS", None),
        ("DURACION DEL TRATAMIENTO: 7 DIAS", None),
    ]:
        solo_modulo(f"'{frag}'", frag, esp)


def h3_celda_detalle() -> None:
    """H3: un CIE-10 sin punto en la celda 'Dias Inc.' se vuelve duracion."""
    print("\n[H3] `_dias_de_celda` le REGALA el ancla ('Dias: ' + celda) y `normalizar`"
          "\n     separa letra de digito, asi que un CIE-10 sin punto (la forma que"
          "\n     emite el OCR: M544/R074/A099/S420, ver 01_evidencia.md §7) se lee"
          "\n     como duracion. Antes del cambio la celda exigia digitos puros: el"
          "\n     bloque entero no casaba (se perdia el dato, no se inventaba).")
    global _n
    for celda, esp in [("J069", None), ("A099", None), ("R074", None), ("S420", None),
                       ("R509", None), ("K429", None), ("O039", None), ("B349", None),
                       ("X 500 MG", None), ("1 de 1", None),
                       ("3", 3), ("TRES", 3), ("3 (TRES)", 3)]:  # los 3 ultimos deben SI leerse
        _n += 1
        got = _dias_de_celda(celda)[0]
        ok = got == esp
        if not ok:
            _fallos.append(f"celda {celda!r}")
        print(f"  [{'OK  ' if ok else 'FP  '}] celda 'Dias Inc.' = {celda!r:14s} "
              f"esperado={esp}  obtenido={got}")


def h4_vacaciones() -> None:
    """H4: la carta de VACACIONES pierde su deteccion si sobrevive la tilde."""
    print("\n[H4] `es_formato_vacaciones` tolera la tilde de 'notificacion' pero NO la"
          "\n     de 'periodo'. Si el OCR la conserva (7 de los 31 textos del corpus"
          "\n     traen tildes: 'Medico', 'Telefono', 'Termino'), la carta se procesa"
          "\n     como INCAPACIDAD y el respaldo historico lee el DIA DEL MES.")
    carta = ("{titulo}\n"
             "Senor(a): <NOMBRE> PEREZ  CC: 1098765432\n"
             "Nos permitimos informar que disfrutara su periodo de vacaciones a partir del\n"
             "dia siete (07) de julio de dos mil veintiseis (2026) hasta el veinte (20) de\n"
             "julio de dos mil veintiseis (2026).\n"
             "Departamento de Gestion Humana\n")
    caso("titulo canonico (control: la regla de dominio funciona)",
         carta.format(titulo="NOTIFICACION DE PERIODO DE VACACIONES"), 14,
         frag="NOTIFICACION DE PERIODO DE VACACIONES + 'dia siete (07) de julio ... hasta el veinte (20)'")
    caso("titulo con TILDE en 'Periodo'",
         carta.format(titulo="Notificacion Per\u00edodo de Vacaciones"), 14,
         frag="Notificacion Per\u00edodo de Vacaciones + la misma prosa")
    for t in ("NOTIFICACION DE VACACIONES", "PERIODO DE VACACIONES", "CARTA DE VACACIONES"):
        caso(f"titulo variante: {t!r}", carta.format(titulo=t), 14, frag=f"{t} + la misma prosa")


def h5_dia_del_mes() -> None:
    """H5: el respaldo historico lee el dia del mes de cualquier prosa."""
    print("\n[H5] El respaldo historico (`extract._dias_por_etiqueta`, patron 2) lee el"
          "\n     DIA DEL MES de 'el dia NN de <mes>'. PREEXISTENTE (misma lectura antes"
          "\n     del cambio) e inerte en los 31 textos cacheados, pero es el vector de H4.")
    for frag in ["Se expide en Malambo el dia 15 de agosto de 2026",
                 "Certifico que el dia primero (01) de julio se atendio al paciente",
                 "Firmado el dia 21 de mayo de 2026"]:
        caso(f"A10 + '{frag[:46]}...'",
             CAB + f"Dias de Incapacidad:\n{frag}\n", None)


def h6_indice_de_fila() -> None:
    """H6: el indice de fila pegado delante del rotulo GLUED se lee como duracion."""
    print("\n[H6] `_RE_UNIDAD` acepta 'dias' de 'DIASDEINCAPACIDAD' como UNIDAD (por la"
          "\n     continuacion `(?=de)`), y la guarda `(?![ \\t]*[:\\-])` que protege"
          "\n     '1 DIAS: 30 (TREINTA)' (falso positivo nº9) no aplica al rotulo pegado."
          "\n     Texto REAL de falsas/INC <NOMBRE> ... 12082026.txt (dias correctos = 1,"
          "\n     12/08 -> 12/08), con un indice de fila '3' delante del rotulo.")
    t = (OCR / "falsas/FALSA-13.txt").read_text(
        encoding="utf-8", errors="replace")
    caso("texto real tal cual (control: no inventa nada)", t, None,
         frag="falsas/INC <NOMBRE> ... 12082026.txt (sin tocar)")
    caso("mismo texto con indice de fila: '3 DIASDEINCAPACIDAD'",
         t.replace("DIASDEINCAPACIDAD", "3 DIASDEINCAPACIDAD"), None,
         frag="el mismo, con 'DIASDEINCAPACIDAD' -> '3 DIASDEINCAPACIDAD'")
    caso("control: con dos puntos ('3 DIAS:') la guarda SI protege",
         CAB + "3 DIAS:\nAPARTIRDELAFECHA\n", None)


def h7_dia_singular() -> None:
    """H7: 'DIA:' singular (rotulo de FECHA) cuenta como rotulo de duracion."""
    print("\n[H7] `_ETIQUETAS_DURACION` incluye `dias?\\s*[:\\-]`, que casa con el SINGULAR"
          "\n     'DIA:' — un rotulo de FECHA en los formularios de rejilla DIA/MES/ANO"
          "\n     (falso positivo nº7). Preexistente por el respaldo, ahora tambien por"
          "\n     el modulo. No aparece con ':' en los 31 textos (construccion plausible).")
    caso("rejilla en una linea: 'DIA: 12 MES: 08 ANO: 2026'",
         CAB + "FECHA DE INICIO\nDIA: 12 MES: 08 ANO: 2026\n", None)
    caso("rejilla sin dos puntos: 'DIA 12 MES 08 ANO 2026'",
         CAB + "FECHA DE INICIO\nDIA 12 MES 08 ANO 2026\n", None)
    caso("rejilla en renglones: 'Dia: 12' / 'Mes: 08' / 'Ano: 2026'",
         CAB + "Fecha de expedicion\nDia: 12\nMes: 08\nAno: 2026\n", None)


def h8_ano_en_palabras() -> None:
    """H8: el ano escrito en palabras ANCLA una duracion del LLM."""
    print("\n[H8] `numerales_en_texto` (guarda de anclaje del LLM) extrae 2 y 26 de"
          "\n     'dos mil veintiseis (2026)': el ANO en palabras basta para que una"
          "\n     duracion del modelo pase por anclada. El camino de REGLAS es inmune"
          "\n     ('mil' no esta en el lexico), el del LLM no.")
    print(f"  numerales_en_texto('de dos mil veintiseis (2026)') = "
          f"{sorted(numerales_en_texto('de dos mil veintiseis (2026)'))}")

    class StubLLM:  # mismo patron que StubOCR/StubLLM del repo (Ollama no corre aqui)
        name = "stub-llm"

        def __init__(self, dias): self.dias = dias

        def extract(self, _t): return {"incapacidad": {"dias": self.dias}}

    txt = CAB + "Dias de Incapacidad:\nExpedida en Malambo a dos mil veintiseis (2026)\n"
    global _n
    for v, esp in [(2, None), (26, None), (20, None)]:
        _n += 1
        rec = normalizar_fechas(HybridExtractor(llm=StubLLM(v)).extract(txt))
        got = rec["incapacidad"]["dias"]
        ok = got == esp
        if not ok:
            _fallos.append(f"LLM dias={v} anclado por el ano en palabras")
        print(f"  [{'OK  ' if ok else 'FP  '}] LLM devuelve dias={v:3d} -> se acepta como "
              f"dias={got} (esperado {esp})")


def impacto_en_nomina() -> None:
    print("\n[FILA DE STAGING] que se escribiria en lp_ausentismos_ia (el auxiliar la ve asi)")
    print("  Documento real: 10/06/2026 -> 11/06/2026 = 2 dias.")
    fila("2 dias, texto limpio (referencia)",
         CAB + "Dias de Incapacidad: 2\nFecha Inicial: 10/06/2026\nFecha Final: 11/06/2026\n")
    fila("+ 'dentro de los 3 dias habiles'",
         CAB + "Dias de Incapacidad:\nLa incapacidad debe radicarse dentro de los 3 dias "
               "habiles siguientes\nFecha Inicial: 10/06/2026\nFecha Final: 11/06/2026\n")
    fila("+ 'valido por 30 dias' (con fecha fin)",
         CAB + "Dias de Incapacidad:\nEste certificado es valido por 30 dias\n"
               "Fecha Inicial: 10/06/2026\nFecha Final: 11/06/2026\n")
    print("  Documento SIN fecha fin (forma A10): no hay contradiccion que avisar ->")
    fila("+ 'valido por 30 dias' (SIN fecha fin)",
         CAB + "Dias de Incapacidad:\nEste certificado es valido por 30 dias\n"
               "Fecha Inicial: 10/06/2026\n")
    fila("+ 'a los 15 dias del mes' (SIN fecha fin)",
         CAB + "Dias de Incapacidad:\nDada en Malambo a los 15 dias del mes de agosto de "
               "2026\nFecha Inicial: 10/06/2026\n")


def limpio() -> None:
    """Construcciones ATACADAS que el lector rechaza correctamente."""
    print("\n[LIMPIO] construcciones atacadas donde NO se inventa duracion (todas OK)")
    ok_casos = [
        ("horas: 'CADA 8 HORAS'", "TOMAR ACETAMINOFEN X500 CADA 8 HORAS"),
        ("horas: 'NUMERO TOTAL DE HORAS' + '4 irs'", "NUMERO TOTAL DE HORAS\n4 irs"),
        ("horas: nota real 'antes de 72 horas'", "Favortramitar la incapacidad antes de 72 horas"),
        ("horas: 'CUADRO CLINICO DE 3 HORAS DE EVOLUCION'", "CUADRO CLINICO DE 3 HORAS DE EVOLUCION"),
        ("horas: 'permiso de dos (2) horas'", "Se concede permiso de dos (2) horas"),
        ("horas desde/hasta: bloque real del permiso", "3.DURACIONDELPERMISO\nDIAS\nHORAS\nDESDE 8:00\nHASTA 12:00"),
        ("ano en palabras (reglas): 'dos mil veintiseis'", "Duracion\nde dos mil veintiseis"),
        ("ano en palabras: 'a los dos mil veintiseis (2026) dias'",
         "Dias de Incapacidad:\nExpedido a los dos mil veintiseis (2026) dias del mes"),
        ("dia del mes de una FECHA: 'POR 4 DIAS DESDE EL 29-07-26'", None),  # ver aparte
        ("edad: 'Edad: 33 Ano(s), 1 mes(es), 8 dia(s)'", "Edad: 33 Ano(s), 1 mes(es), 8 dia(s)"),
        ("edad: '24 anos 05 meses'", "24 anos 05 meses"),
        ("edad: 'Rango de edad: 25-34'", "Rango de edad: 25-34"),
        ("gestacion: 'EDADGESTASIONAL:' / '40.00 Semanas'", "EDADGESTASIONAL:\n40.00 Semanas"),
        ("vigencia de dosis: 'Vig: 1 dia'", "Vig: 1 dia"),
        ("insumo: 'ACETAMINOFEN 1 (Uno)'", "MEDICAMENTO ACETAMINOFEN 1 (Uno)"),
        ("sintoma del paciente: 'hacetresdias'", "Causa que motiva la atencion: dolor desdo hacetresdias."),
        ("articulo: 'una fuerza mayor'", "salvo que se trate de una fuerza mayor o caso fortuito"),
        ("articulo: 'una cuenta bancaria'", "debera tener una cuenta bancaria inscrita"),
        ("medicamento: 'CADA 8 HORAS POR 5 DIAS'", "TOMAR ACETAMINOFEN X500 CADA 8 HORAS POR 5 DIAS"),
        ("medicamento en letras: 'CADA 8 HORAS POR CINCO DIAS'", "ACETAMINOFEN CADA 8 HORAS POR CINCO DIAS"),
        ("tramite: 'IncapacidadN:362.355'", "IncapacidadN:362.355"),
        ("tramite: 'Consecutivo:' / '0081523489'", "Consecutivo:\n0081523489"),
        ("tramite: 'INC15247'", "INC15247"),
        ("registro medico: 'Registro Medico: 123'", "Dias de Incapacidad:\nRegistro Medico: 123"),
        ("registro medico: 'R.M. 100946'", "Dias de Incapacidad:\nR.M. 100946"),
        ("registro medico: 'Reg.Medico:1030539622'", "MedicinaGeneral-Reg.Medico:1030539622"),
        ("registro medico: 'R.M14035.1'", "R.M14035.1"),
        ("signos vitales: 'glasgow 15/15'", "glasgow 15/15"),
        ("regimen/nivel/pagina", "Regimen: 1 - Contributivo\nNivel: 1\nPagina 1 de 1\n01-Consulta externa"),
        ("CIE-10 en texto libre: 'M545 LUMBAGO'", "Diagnostico: M545 LUMBAGO NO ESPECIFICADO"),
    ]
    global _n
    for titulo, frag in ok_casos:
        if frag is None:
            continue
        _n += 1
        r = duracion_en_texto(frag)
        val = r["valor"] if r else None
        if val is not None:
            _fallos.append(titulo)
        print(f"  [{'OK  ' if val is None else 'FP  '}] {titulo:58s} -> {val}")
    # el dia del mes de una fecha SI debe descartarse pero la duracion SI leerse:
    _n += 1
    r = duracion_en_texto("SE DA INCAPACIDAD MEDICA POR 4 DIAS DESDE EL 29-07-2026 HASTA EL 01-08-2026")
    val = r["valor"] if r else None
    if val != 4:
        _fallos.append("A5 'POR 4 DIAS DESDE EL 29-07-2026'")
    print(f"  [{'OK  ' if val == 4 else 'FP  '}] {'A5: POR 4 DIAS DESDE EL 29-07-2026 -> 4, no 29':58s} -> {val}")
    # permisos reales, con y sin ancla de formato
    for f in ("reales/REAL-05.txt", "real/REAL-08.txt"):
        t = (OCR / f).read_text(encoding="utf-8", errors="replace")
        for etiqueta, tt in (("tal cual", t),
                             ("ancla PERMISO destruida", t.replace("PERMISO", "PERMTSO"))):
            _n += 1
            r = duracion_en_texto(tt)
            val = r["valor"] if r else None
            if val is not None:
                _fallos.append(f"{f} ({etiqueta})")
            print(f"  [{'OK  ' if val is None else 'FP  '}] permiso real {f.split('/')[0]:6s} "
                  f"({etiqueta:24s}) -> {val}")


def main() -> int:
    print("=" * 78)
    print("CAZA DE DURACIONES INVENTADAS — frente 'falsos-positivos'")
    print("=" * 78)
    h1_unidad_sin_contexto()
    h2_rotulo_duracion()
    h3_celda_detalle()
    h4_vacaciones()
    h5_dia_del_mes()
    h6_indice_de_fila()
    h7_dia_singular()
    h8_ano_en_palabras()
    impacto_en_nomina()
    limpio()
    print("\n" + "-" * 78)
    print(f"casos: {_n}   con duracion INVENTADA / perdida: {len(_fallos)}")
    for f in _fallos:
        print(f"   - {f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
