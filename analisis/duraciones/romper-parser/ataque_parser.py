"""Ataque adversario al lector de numerales (incapacidad_ocr.numeros_es).

No modifica nada del paquete: solo lo importa y le mete entradas hostiles.
Cada caso declara ESPERADO; el script imprime solo los que difieren.

Uso:
  .venv/Scripts/python.exe ataque_parser.py
"""
from __future__ import annotations

import re
import sys
import time
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
sys.path.insert(0, str(REPO))

from incapacidad_ocr.numeros_es import (  # noqa: E402
    duracion_en_texto,
    normalizar,
    numerales_en_texto,
    texto_a_entero,
)

FALLOS: list[tuple[str, str, object, object]] = []
TOTAL = 0


def _chk(grupo: str, entrada, esperado, obtenido) -> None:
    global TOTAL
    TOTAL += 1
    if obtenido != esperado:
        FALLOS.append((grupo, repr(entrada), esperado, obtenido))


def t2e(grupo: str, casos: list[tuple[str, object]]) -> None:
    for entrada, esperado in casos:
        try:
            obtenido = texto_a_entero(entrada)
        except Exception as exc:  # noqa: BLE001
            obtenido = f"EXCEPCION {type(exc).__name__}: {exc}"
        _chk(grupo, entrada, esperado, obtenido)


def dur(grupo: str, casos: list[tuple[str, object]]) -> None:
    """`esperado` = valor de días esperado (o None si no debe leer nada)."""
    for entrada, esperado in casos:
        try:
            d = duracion_en_texto(entrada)
            obtenido = d["valor"] if d else None
        except Exception as exc:  # noqa: BLE001
            obtenido = f"EXCEPCION {type(exc).__name__}: {exc}"
        _chk(grupo, entrada, esperado, obtenido)


def durx(grupo: str, casos: list[tuple[str, tuple]]) -> None:
    """Comprueba la TERNA (valor, letra, numero)."""
    for entrada, esperado in casos:
        try:
            d = duracion_en_texto(entrada)
            obtenido = (d["valor"], d["letra"], d["numero"]) if d else None
        except Exception as exc:  # noqa: BLE001
            obtenido = f"EXCEPCION {type(exc).__name__}: {exc}"
        _chk(grupo, entrada, esperado, obtenido)


# ===========================================================================
# 1. NUMERALES COMPUESTOS  (texto_a_entero)
# ===========================================================================
t2e("1-compuestos", [
    ("cuarenta y uno", 41),
    ("CUARENTA Y UNO", 41),
    ("cuarenta y un", 41),
    ("cuarentayuno", 41),          # OCR pega
    ("cuarenta uno", 41),          # OCR pierde la "y"
    ("ciento uno", 101),
    ("ciento un", 101),
    ("cientouno", 101),
    ("quinientos cuarenta", 540),
    ("quinientos cuarenta y uno", 541),
    ("novecientos noventa y nueve", 999),
    ("doscientas veinte", 220),
    ("trescientos", 300),
    ("cien", 100),
    ("ciento", 100),              # prefijo suelto: el modulo lo admite
    ("treinta y cinco", 35),
    ("treinta cinco", 35),
    ("veintiun", 21),
    ("veintiuna", 21),
    ("veinte", 20),
    ("cero", 0),
    ("uno", 1),
    ("una", 1),
    ("un", 1),
    ("dieciseis", 16),
    ("diecis\u00e9is", 16),        # con tilde
    ("DIECIS\u00c9IS", 16),
])

# Formas ARCAICAS/analiticas que la ley y las cartas colombianas si usan.
t2e("2-arcaicas", [
    ("diez y seis", 16),
    ("diez y ocho", 18),
    ("veinte y uno", 21),
    ("veinte y cinco", 25),
])

# Lo que NO debe leerse como numeral de 0..999.
t2e("3-no-numeral", [
    ("dos mil veintiseis", None),   # anio en palabras
    ("mil", None),
    ("cien veinte", None),          # "cien" es exacto
    ("doscientos trescientos", None),
    ("treinta y cero", None),
    ("treinta y", None),
    ("y", None),
    ("y y y", None),
    ("cuarenta y i cinco", None),   # separador ilegible
    ("", None),
    ("   ", None),
    ("\n\n", None),
    (None, None),
    ("-", None),
    ("(", None),
    ("paciente", None),
    ("veinteava", None),            # contiene "veinte"
    ("veinteavo", None),
    ("cientifico", None),           # contiene "cien"
    ("docente", None),              # contiene "doce"
    ("seismico", None),             # contiene "seis"
    ("unidad", None),               # contiene "un"
    ("dosis", None),                # contiene "dos"
    ("trece\u00f1o", None),
    ("diario", None),
    ("nueves", None),               # plural inventado
    ("doses", None),
    ("tresmil", None),
])

# Palabras LARGAS que empiezan por numeral (subsumidas por 3, aparte por claridad)
t2e("4-prefijo-numeral", [
    ("seiscientos", 600),
    ("seiscientas", 600),
    ("ochocientos ochenta y ocho", 888),
    ("ochentavo", None),
    ("quinceava", None),
    ("dosificacion", None),
    ("unicamente", None),
    ("tresillo", None),
])

# ===========================================================================
# 5. AMBIGUEDAD "un": articulo vs numero  (duracion_en_texto)
# ===========================================================================
dur("5-ambiguedad-un", [
    ("Se concede un dia de incapacidad", 1),          # numeral: OK leerlo
    ("un paciente", None),
    ("Se atendio un paciente con un cuadro clinico", None),
    ("una vez al dia", None),                          # frecuencia, NO duracion
    ("tomar una tableta cada dia", None),
    ("Aplicar una dosis por dia", None),
    ("control en un dia", 1),                          # ambiguo; se acepta
    ("hace un dia inicio el cuadro", None),            # veto \bhace
])

# ===========================================================================
# 6. UNIDAD EQUIVOCADA DETRAS DEL ROTULO  (el veto solo mira a la IZQUIERDA)
# ===========================================================================
dur("6-unidad-equivocada", [
    ("DURACION: 2 HORAS", None),
    ("DURACION DEL PERMISO: 4 HORAS", None),
    ("Duracion del tratamiento: 3 meses", None),
    ("Duracion: 40 semanas", None),
    ("Duracion: dos meses", None),
    ("Duracion: 8 horas diarias", None),
    ("DIAS: 4 HORAS", None),
    ("Duracion 24 horas", None),
    ("Duracion aproximada: 2 anos", None),
    # control: la unidad correcta si debe leerse
    ("DURACION: 2 DIAS", 2),
    ("Duracion: 15", 15),
])

# ===========================================================================
# 7. REJILLA DIA/MES/ANO Y FECHAS COLADAS POR EL ROTULO
# ===========================================================================
dur("7-rejilla-fechas", [
    ("DURACION DIA MES ANO\n15 09 2026", None),
    ("Duracion  Dia Mes Ano\n03 09 2026", None),
    ("FECHA INICIAL DIA-MES-ANO\n01 09 2026", None),
    ("Duracion\n01-09-2026", None),
    ("Duracion\n01/09/2026", None),
    ("Duracion\n15 09 2026", None),
    ("Dias:\n27 08 2026", None),
    # control: valor real en la linea siguiente
    ("DURACION:\n126", 126),
])

# ===========================================================================
# 8. VETO DEMASIADO AMPLIO: pierde duraciones legitimas
# ===========================================================================
dur("8-veto-amplio", [
    ("Por lo anterior se hace entrega de incapacidad por 3 dias", 3),
    ("Se hace necesario otorgar 5 dias de incapacidad", 5),
    ("Reposo 24 horas y se otorgan 5 dias de incapacidad", 5),
    ("Acetaminofen cada 8 horas. Se incapacita por 5 dias", 5),
    ("Control en 1 mes. Incapacidad por 7 dias", 7),
    ("Gestante de 40 semanas. Incapacidad de 30 dias", 30),
    # "Hora Aten." y "Fecha y Hora Ing:" son texto REAL del corpus; si el OCR junta
    # el encabezado con la fila de valores, el veto \bhoras?\b mata la duracion.
    ("Hora Aten. 08:23 Dias de Incapacidad: 3", 3),
    ("Fecha y Hora Ing: 01/09/2026 08:23 Dias: 3", 3),
])

# ===========================================================================
# 9. ROTULO/UNIDAD SEGUIDOS DE GUION: el valor ya leido se descarta
# ===========================================================================
dur("9-guion-tras-unidad", [
    ("INCAPACIDAD: 3 DIAS - INICIA 01/09/2026", 3),
    ("Total 5 DIAS: calendario", 5),
    ("Se otorgan 10 DIAS-CALENDARIO", 10),
    ("30 DIAS : del 01/09/2026 al 30/09/2026", 30),
])

# ===========================================================================
# 10. OCR DEGRADADO SOBRE LA UNIDAD Y EL ROTULO
# ===========================================================================
dur("10-ocr-degradado", [
    ("D\u00cdAS DE INCAPACIDAD: 3", 3),
    ("Dias de Incapacldad: 3", 3),        # correccion declarada
    ("DIAS DE INCAPACIDAD: TRES", 3),
    ("Dias de incapacidad: 02 dos dia(s)", 2),
    ("D1AS DE INCAPACIDAD: 3", 3),        # I leida como 1
    ("DlAS DE INCAPACIDAD: 3", 3),        # I leida como l minuscula
    ("DIAS DE INCAPACIDAD 3", 3),
    ("DURACION 3 D1AS", 3),
    ("POR 3 D\u00cdAS", 3),
    ("POR TRES DIAS", 3),
    ("POR TRES D\u00cdAS", 3),
    ("3Dian de incapacidad", 3),          # correccion declarada
    ("DURACION: TREINTA (30) DIAS", 30),
    ("DURACION: TREINTA(30)DIAS", 30),
])

# ===========================================================================
# 11. RANGO DE DOMINIO: valores imposibles que el modulo entrega igual
# ===========================================================================
durx("11-rango", [
    ("Duracion: 0 dias", (0, None, 0)),
    ("Duracion: cero dias", (0, 0, None)),
    ("Duracion: 999 dias", (999, None, 999)),
    ("Duracion: novecientos noventa y nueve dias", (999, 999, None)),
])

# ===========================================================================
# 12. DESACUERDO PALABRA vs DIGITO
# ===========================================================================
durx("12-desacuerdo", [
    ("DIAS DE INCAPACIDAD: 2 (TRES)", (2, 3, 2)),
    ("DIAS DE INCAPACIDAD: TRES (2)", (2, 3, 2)),
    ("DIAS: 30 (TREINTA)", (30, 30, 30)),
])

# ===========================================================================
# 13. PRIORIDAD "ambos": una forma mixta LEJANA gana a la duracion real
# ===========================================================================
dur("13-prioridad-mixta", [
    ("INCAPACIDAD POR 15 DIAS\nFORMULA: DIAS: 3 (TRES) DE TRATAMIENTO", 15),
    ("Se incapacita 15 dias\nCantidad: 1 (UNO) frasco por dia", 15),
])

# ===========================================================================
# 14. ENTRADAS DEGENERADAS
# ===========================================================================
dur("13b-fechas-horas-decimales", [
    ("Hora de atencion 08:23:39 Dias 3", 3),
    ("Duracion 1.5 dias", None),        # medio dia no es dominio: mejor None
    ("Duracion: 08:23", None),
    ("Consecutivo 0081523489 dias", None),
    ("Duracion\n01-09-2026", None),
    ("Duracion\n01/09/2026", None),
    ("POR 4 DIAS DESDE EL 29-07-26", 4),
    ("Duracion\nDE2026", None),         # falso positivo n.6 (daba 202)
])

dur("14-degeneradas", [
    (None, None),
    ("", None),
    ("   ", None),
    ("\n\n\n", None),
    ("\x00\x00", None),
    ("dias", None),
    ("DIAS:", None),
    ("Duracion", None),
    ("Duracion:", None),
    ("dias dias dias", None),
    ("()", None),
    ("- - -", None),
])

for grupo, entrada, esperado in [
    ("14-degeneradas", 5, "no revienta"),
    ("14-degeneradas", 5.0, "no revienta"),
    ("14-degeneradas", True, "no revienta"),
    ("14-degeneradas", ["dos dias"], "no revienta"),
    ("14-degeneradas", {"a": 1}, "no revienta"),
]:
    for fn in (texto_a_entero, duracion_en_texto, numerales_en_texto, normalizar):
        try:
            fn(entrada)  # type: ignore[arg-type]
            got = "no revienta"
        except Exception as exc:  # noqa: BLE001
            got = f"EXCEPCION {type(exc).__name__} en {fn.__name__}"
        _chk(grupo, f"{fn.__name__}({entrada!r})", esperado, got)

# ===========================================================================
# 15. numerales_en_texto: ancla del camino LLM
# ===========================================================================
NUM_CASOS: list[tuple[str, set[int]]] = [
    ("dos dias", {2}),
    ("18/05/2026", set()),               # fecha: no ancla nada
    ("0081523489", set()),               # consecutivo
    ("Edad: 33 anos", {33}),             # ancla lo que NO es duracion (documentado)
    ("dosdiagnosticos", set()),          # "dos" pegado a "diagnosticos"
    ("unadiabetes mellitus", set()),
    ("El paciente refiere diarrea", set()),
    ("veinteava semana", set()),
    (None, set()),
    ("", set()),
]
for entrada, esperado in NUM_CASOS:
    try:
        obtenido = numerales_en_texto(entrada)
    except Exception as exc:  # noqa: BLE001
        obtenido = f"EXCEPCION {type(exc).__name__}: {exc}"
    _chk("15-anclaje-llm", entrada, esperado, obtenido)

# ===========================================================================
# 16. CADENAS LARGUISIMAS (coste): no debe degenerar
# ===========================================================================
def _cronometra(nombre: str, texto: str, limite_s: float = 2.0) -> None:
    global TOTAL
    TOTAL += 1
    t0 = time.perf_counter()
    try:
        duracion_en_texto(texto)
        numerales_en_texto(texto)
        err = None
    except Exception as exc:  # noqa: BLE001
        err = f"{type(exc).__name__}: {exc}"
    dt = time.perf_counter() - t0
    if err or dt > limite_s:
        FALLOS.append(("16-coste", f"{nombre} (len={len(texto)})",
                       f"< {limite_s}s sin excepcion", err or f"{dt:.2f}s"))
    print(f"  [coste] {nombre:34s} len={len(texto):>8} {dt:7.3f}s")

_cronometra("dos repetido (una linea)", "dos " * 20000)
_cronometra("dos pegado + corte", "dos" * 20000 + "z")
_cronometra("dos y dos y ...", "dos y " * 20000)
_cronometra("numeral + espacios + corte", "dos" + " " * 200000 + "z")
_cronometra("bloques dos+espacios", ("dos" + " " * 200) * 2000)
_cronometra("digitos", "123 " * 50000)
_cronometra("muchas lineas con rotulo", "Duracion:\n" * 20000)
_cronometra("lineas de valor", "Duracion\n" + "12\n" * 20000)
_cronometra("rotulo y unidad juntos", "DIAS DE INCAPACIDAD: 2 DIAS\n" * 10000)
_cronometra("centenas pegadas", "novecientosnoventaynueve" * 5000)
_cronometra("una linea gigante con veto", ("hace " + "x" * 100) * 2000 + " 5 dias")

# ===========================================================================
# 17. normalizar: invariantes que el resto asume
# ===========================================================================
NORM = [
    ("A\u00d1O", "ano"),
    ("D\u00cdA(S)", "dias"),
    ("POR1DIA", "por 1 dia"),
    ("18/05/2026", "18/05/2026"),
    ("l\u00ednea1\nl\u00ednea2", "linea 1\nlinea 2"),
    ("  a  \n  b  ", "a\nb"),
]
for entrada, esperado in NORM:
    try:
        obtenido = normalizar(entrada)
    except Exception as exc:  # noqa: BLE001
        obtenido = f"EXCEPCION {type(exc).__name__}: {exc}"
    _chk("17-normalizar", entrada, esperado, obtenido)

# ===========================================================================
# INFORME
# ===========================================================================
print()
print("=" * 100)
print(f"casos ejecutados: {TOTAL}   discrepancias: {len(FALLOS)}")
print("=" * 100)
grupo_actual = None
for grupo, entrada, esperado, obtenido in FALLOS:
    if grupo != grupo_actual:
        print(f"\n### {grupo}")
        grupo_actual = grupo
    print(f"  entrada : {entrada}")
    print(f"  esperado: {esperado!r}")
    print(f"  obtenido: {obtenido!r}")
