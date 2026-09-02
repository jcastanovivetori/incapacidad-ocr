"""Pruebas del módulo de numerales en español (ejecutable con python puro, sin pytest).

    python tests/test_numeros_es.py

Cubre: `texto_a_entero` (1..40 + valores largos, apócopes, "y", pegados),
`normalizar` (degradaciones REALES del OCR) y `duracion_en_texto` sobre las formas
del corpus (A1..A10 / B1 / C1..C6), la forma mixta coincidente y la discrepante, y
—la mitad del valor de este archivo— los FALSOS POSITIVOS que deben dar None: si
el parser los acepta, el sistema empieza a inventar duraciones.

Los recortes de texto vienen de `dataset-falsedad/ocr/**` y de
`dataset-falsedad/duraciones/01_evidencia.md`; se citan SOLO renglones de duración
(sin nombres, cédulas ni diagnósticos — PII de salud, Ley 1581).
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

try:  # consola Windows (cp1252) → forzar UTF-8 para acentos
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # noqa: BLE001
    pass

from incapacidad_ocr.numeros_es import (  # noqa: E402
    duracion_en_texto,
    normalizar,
    numerales_en_texto,
    texto_a_entero,
)

_fail = 0


def check(name: str, cond: bool, detail: str = "") -> None:
    global _fail
    ok = bool(cond)
    if not ok:
        _fail += 1
    print(("  PASS " if ok else "  FAIL ") + name + (f"  ->  {detail}" if detail else ""))


def check_dur(name: str, texto: str, esperado: dict | None) -> None:
    """Compara solo las claves que interesan del resultado de `duracion_en_texto`."""
    got = duracion_en_texto(texto)
    if esperado is None:
        check(name, got is None, "None" if got is None else str(got))
        return
    if got is None:
        check(name, False, "None (se esperaba una duración)")
        return
    dif = {k: (v, got.get(k)) for k, v in esperado.items() if got.get(k) != v}
    check(name, not dif, f"{dif}  ev={got['evidencia']!r}" if dif else "")


# --- Numerales 1..40 escritos en palabras (los 40, sin huecos) ---------------
_PALABRAS = {
    1: "uno", 2: "dos", 3: "tres", 4: "cuatro", 5: "cinco", 6: "seis", 7: "siete",
    8: "ocho", 9: "nueve", 10: "diez", 11: "once", 12: "doce", 13: "trece",
    14: "catorce", 15: "quince", 16: "dieciseis", 17: "diecisiete", 18: "dieciocho",
    19: "diecinueve", 20: "veinte", 21: "veintiuno", 22: "veintidos",
    23: "veintitres", 24: "veinticuatro", 25: "veinticinco", 26: "veintiseis",
    27: "veintisiete", 28: "veintiocho", 29: "veintinueve", 30: "treinta",
    31: "treinta y uno", 32: "treinta y dos", 33: "treinta y tres",
    34: "treinta y cuatro", 35: "treinta y cinco", 36: "treinta y seis",
    37: "treinta y siete", 38: "treinta y ocho", 39: "treinta y nueve",
    40: "cuarenta",
}
# Valores largos: en el corpus solo se escriben en dígitos, pero el rango válido
# del repo llega a 540 y el parser debe ser correcto en todo él.
_PALABRAS_LARGAS = {
    45: "cuarenta y cinco", 60: "sesenta", 90: "noventa", 120: "ciento veinte",
    180: "ciento ochenta", 365: "trescientos sesenta y cinco",
    540: "quinientos cuarenta",
}


def test_texto_a_entero() -> None:
    print("[1] texto_a_entero: numerales 1..40 y valores largos (hasta 540)")
    malos = {n: texto_a_entero(p) for n, p in _PALABRAS.items() if texto_a_entero(p) != n}
    check("1..40 en palabras", not malos, str(malos))
    malos_l = {n: texto_a_entero(p) for n, p in _PALABRAS_LARGAS.items() if texto_a_entero(p) != n}
    check("45/60/90/120/180/365/540", not malos_l, str(malos_l))
    check("cero", texto_a_entero("cero") == 0, str(texto_a_entero("cero")))
    check("999 (tope del alcance)", texto_a_entero("novecientos noventa y nueve") == 999,
          str(texto_a_entero("novecientos noventa y nueve")))


def test_formas_y_apocopes() -> None:
    print("[2] texto_a_entero: apócopes, 'y', pegados, mayúsculas y tildes")
    check("un (apócope)", texto_a_entero("UN") == 1)
    check("una", texto_a_entero("una") == 1)
    check("veintiun (apócope)", texto_a_entero("veintiun") == 21)
    check("veintiuno pegado", texto_a_entero("veintiuno") == 21)
    check("veintidós con tilde", texto_a_entero("veintidós") == 22)
    check("dieciséis con tilde", texto_a_entero("DIECISÉIS") == 16)
    check("treinta y cinco (con 'y')", texto_a_entero("treinta y cinco") == 35)
    check("treinta cinco (el OCR pierde la 'y')", texto_a_entero("treinta cinco") == 35)
    check("cien exacto", texto_a_entero("cien") == 100)
    check("ciento veinte", texto_a_entero("ciento veinte") == 120)
    check("cientoveinte pegado por el OCR", texto_a_entero("cientoveinte") == 120)
    check("CATORCE en mayúsculas", texto_a_entero("CATORCE") == 14)
    check("'14 - CATORCE' → solo la palabra", texto_a_entero("- CATORCE") == 14)
    check("(DOS) entre paréntesis", texto_a_entero("(DOS)") == 2)


def test_texto_a_entero_none() -> None:
    print("[3] texto_a_entero: lo que NO es un numeral de 0..999 → None")
    check("vacío", texto_a_entero("") is None)
    check("None", texto_a_entero(None) is None)
    # 'mil' está FUERA del léxico a propósito: en el corpus los miles en palabras
    # son siempre el AÑO de una carta en prosa, nunca una duración.
    check("dos mil veintiseis (año)", texto_a_entero("dos mil veintiseis") is None,
          str(texto_a_entero("dos mil veintiseis")))
    check("mil", texto_a_entero("mil") is None, str(texto_a_entero("mil")))
    check("ordinal 'primero'", texto_a_entero("primero") is None, str(texto_a_entero("primero")))
    check("palabra + unidad pegadas ('dosdias')", texto_a_entero("dosdias") is None,
          str(texto_a_entero("dosdias")))
    check("gramática inválida 'cien veinte'", texto_a_entero("cien veinte") is None,
          str(texto_a_entero("cien veinte")))
    check("'treinta y' incompleto", texto_a_entero("treinta y") is None,
          str(texto_a_entero("treinta y")))
    check("'treinta y cero'", texto_a_entero("treinta y cero") is None,
          str(texto_a_entero("treinta y cero")))
    check("dígitos, no letras ('2')", texto_a_entero("2") is None, str(texto_a_entero("2")))
    check("texto cualquiera", texto_a_entero("una fuerza mayor") is None,
          str(texto_a_entero("una fuerza mayor")))


def test_normalizar() -> None:
    print("[4] normalizar: degradaciones REALES del OCR observadas en el corpus")
    check("dia(s) → dias", "dias" in normalizar("Dias de incapacidad: 02 dos dia(s)"),
          normalizar("Dias de incapacidad: 02 dos dia(s)"))
    check("tilde fuera ('Días de Incapacidad')",
          normalizar("Días de Incapacidad:  2") == "dias de incapacidad: 2",
          normalizar("Días de Incapacidad:  2"))
    check("doble espacio colapsado",
          normalizar("Dias de Incapacidad:  2") == "dias de incapacidad: 2")
    check("'3Dian' → '3 dias'", normalizar("3Dian") == "3 dias", normalizar("3Dian"))
    check("'Dianostico' NO se toca", "dianostico" in normalizar("Dianostico:"),
          normalizar("Dianostico:"))
    check("'Incapacldad' → 'incapacidad'",
          normalizar("Dias de Incapacldad:") == "dias de incapacidad:",
          normalizar("Dias de Incapacldad:"))
    # Se separan dígitos de letras (el valor pegado a la palabra); los signos de
    # puntuación se dejan como están (no hacen falta y tocarlos rompería fechas).
    check("pegado dígito-letra separado",
          normalizar("Dias de incapacidad:02dosdia(s)") == "dias de incapacidad:02 dosdias",
          normalizar("Dias de incapacidad:02dosdia(s)"))
    check("'POR1DIA' → 'por 1 dia...'", normalizar("POR1DIAAPARTIRDE").startswith("por 1 dia"),
          normalizar("POR1DIAAPARTIRDE"))
    check("saltos de línea conservados", normalizar("DURACION:\n126") == "duracion:\n126",
          normalizar("DURACION:\n126"))


def test_formas_solo_numero() -> None:
    print("[5] duracion_en_texto: formas A (solo número) del corpus")
    check_dur("A1 'Dias de Incapacidad: 1'", "Dias de Incapacidad: 1",
              {"valor": 1, "origen": "numero", "coincide": None})
    check_dur("A2 'Dias:3' (sin espacio)", "Dias:3", {"valor": 3, "origen": "numero"})
    check_dur("A3 'Dias de Incapacidad: 2 Dias' (unidad repetida)",
              "Dias de Incapacidad: 2 Dias", {"valor": 2, "origen": "numero"})
    check_dur("A4 'DURACION:' + valor en la línea siguiente", "DURACION:\n126",
              {"valor": 126, "origen": "numero"})
    check_dur("A5 prosa 'POR 4 DIAS DESDE EL <fecha>'",
              "SE DA INCAPACIDAD MEDICA POR 4 DIAS DESDE EL 29-07-26 HASTA EL 01/07/29",
              {"valor": 4, "origen": "numero"})
    check_dur("A6 prosa TODA pegada 'POR1DIAAPARTIRDE'",
              "SEGENERAINCAPACIDADMEDICAPOR1DIAAPARTIRDE18/05/2026HASTA18/05/2026",
              {"valor": 1, "origen": "numero"})
    check_dur("A7 'Descripcion: INCAPACIDAD POR 2 DIAS.'",
              "Descripcion: INCAPACIDAD POR 2 DIAS.", {"valor": 2, "origen": "numero"})
    check_dur("A7 pegada 'DeSCripcIOn:INCAPACIDADMEDICADE2DIAS'",
              "DeSCripcIOn:INCAPACIDADMEDICADE2DIAS", {"valor": 2, "origen": "numero"})
    check_dur("A8 rótulo degradado '3Dian'", "3Dian", {"valor": 3, "origen": "numero"})
    check_dur("A9 '30 DIAS' como línea suelta", "30 DIAS", {"valor": 30, "origen": "numero"})
    check_dur("A10 rótulo SIN valor → None (no se inventa)",
              "Dias de Incapacidad:\nEstado Civil:", None)
    check_dur("A10 'DIASDEINCAPACIDAD' sin valor → None", "DIASDEINCAPACIDAD", None)


def test_formas_con_letra() -> None:
    print("[6] duracion_en_texto: formas B y C (letra sola / letra + número)")
    # B1: el dígito lo perdió el OCR y sobrevive SOLO la palabra, en el renglón
    # ANTERIOR al rótulo (el formato Sura invierte el orden de lectura). Es el
    # único caso del corpus donde leer letras es la única forma de tener el dato.
    check_dur("B1 '-DOS' + 'Duracion' (solo la palabra)",
              "Fecha Inicio\n-DOS\nDuracion\nFecha Fin",
              {"valor": 2, "origen": "letra", "letra": 2, "numero": None, "coincide": None})
    check_dur("C1 'Dias: 2 (DOS DIAS)'", "Dias: 2 (DOS DIAS)",
              {"valor": 2, "origen": "ambos", "letra": 2, "numero": 2, "coincide": True})
    check_dur("C1 'DiaS:2(DOSDIAS)' (todo pegado)", "DiaS:2(DOSDIAS)",
              {"valor": 2, "origen": "ambos", "coincide": True})
    check_dur("C1 'Dias: 1 (UN DIA)' (apócope + singular)", "Dias: 1 (UN DIA)",
              {"valor": 1, "origen": "ambos", "letra": 1, "numero": 1, "coincide": True})
    check_dur("C2 'Dias de incapacidad: 02 dos dia(s)' (cero a la izquierda)",
              "Dias de incapacidad: 02 dos dia(s)",
              {"valor": 2, "origen": "ambos", "letra": 2, "numero": 2, "coincide": True})
    check_dur("C2 'Dias de incapacidad:02dosdia(s)' (pegado en el PDF)",
              "Dias de incapacidad:02dosdia(s)", {"valor": 2, "origen": "ambos", "coincide": True})
    check_dur("C3 'DIAS: 30 (TREINTA)' (palabra sola en paréntesis)", "DIAS: 30 (TREINTA)",
              {"valor": 30, "origen": "ambos", "letra": 30, "numero": 30, "coincide": True})
    check_dur("C3 con '1' de índice de fila delante del rótulo",
              "1 DIAS: 30 (TREINTA) DESDE: 25/05/2026 HASTA: 23/06/2026",
              {"valor": 30, "origen": "ambos", "coincide": True})
    check_dur("C4 'Duracion' + '14- CATORCE'", "Duracion\n14- CATORCE",
              {"valor": 14, "origen": "ambos", "letra": 14, "numero": 14, "coincide": True})
    check_dur("C5 'DIASDEINCAPACIDAD' + 'DOS (02)' (PALABRA primero)",
              "DIASDEINCAPACIDAD\nDOS (02)\nAPARTIRDELAFECHA",
              {"valor": 2, "origen": "ambos", "letra": 2, "numero": 2, "coincide": True})
    check_dur("C6 número y palabra en líneas distintas", "Dias de Incapacidad:  2\nDOS",
              {"valor": 2, "origen": "ambos", "letra": 2, "numero": 2, "coincide": True})


def test_mixta_y_discrepancia() -> None:
    print("[7] duracion_en_texto: forma mixta 'DOS (2)' y la DISCREPANTE 'TRES (2)'")
    check_dur("'DOS (2) DIAS' → ambos, coincide=True", "DOS (2) DIAS",
              {"valor": 2, "origen": "ambos", "letra": 2, "numero": 2, "coincide": True})
    # Instrumentación: no se ha visto en este corpus, pero el desacuerdo se
    # REPORTA (no se decide nada aquí; otro módulo lo trata como señal).
    check_dur("'TRES (2) DIAS' → coincide=False (señal para otro módulo)", "TRES (2) DIAS",
              {"valor": 2, "origen": "ambos", "letra": 3, "numero": 2, "coincide": False})
    check_dur("'2 (TRES DIAS)' discrepante al revés", "Dias: 2 (TRES DIAS)",
              {"valor": 2, "origen": "ambos", "letra": 3, "numero": 2, "coincide": False})
    check_dur("compuesto 'VEINTIUN (21) DIAS'", "VEINTIUN (21) DIAS",
              {"valor": 21, "origen": "ambos", "coincide": True})
    check_dur("compuesto 'CIENTO VEINTE (120) DIAS'", "CIENTO VEINTE (120) DIAS",
              {"valor": 120, "origen": "ambos", "coincide": True})
    check_dur("solo letra con 'y': 'TREINTA Y CINCO DIAS'", "TREINTA Y CINCO DIAS",
              {"valor": 35, "origen": "letra", "letra": 35, "numero": None})
    check_dur("sin rango impuesto: 'Dias: 700' (lo acota quien valida)", "Dias: 700",
              {"valor": 700, "origen": "numero"})


def test_falsos_positivos() -> None:
    print("[8] duracion_en_texto: FALSOS POSITIVOS del corpus → None")
    check_dur("nº1 síntoma del paciente 'hacetresdias'",
              "Medueletoda la cabeza desdo hacetresdias'.", None)
    check_dur("nº1 con espacios 'hace tres dias'", "el dolor comenzo hace tres dias", None)
    check_dur("nº2 edad 'Edad: 33 Ano(s), 1 mes(es), 8 dia(s)'",
              "Edad: 33 Ano(s), 1 mes(es), 8 dia(s)", None)
    check_dur("nº2 edad 'Edad:31 ano(s), 3 mes(es), 22 dia(s)'",
              "Edad:31 ano(s), 3 mes(es), 22 dia(s)", None)
    check_dur("nº3 cantidad de insumo '1 (Uno)'", "Nro Orden\n1 (Uno)", None)
    check_dur("nº3 cantidad de insumo '1 (Una)'", "J3344JERINGAS5ML\n1 (Una)", None)
    check_dur("nº4 vigencia de la dosis 'Vig: 1 dia'", "Vig: 1 dia", None)
    check_dur("nº6 el AÑO tras 'Duracion' ('DE2026')",
              "MARTES 09 DE/JUNIO Duracion\nDE2026", None)
    check_dur("nº7 rejilla DIA/MES/ANO bajo el rótulo",
              "DIASDEINCAPACIDAD\nAPARTIRDELAFECHA\nVIGENCIAS\nDIA\nMES\nANO\n"
              "FECHA DEINICIO\n12\n08\n2026", None)
    check_dur("nº8 nº de sección '3.DURACIONDELPERMISO'",
              "3.DURACIONDELPERMISO\nDiAS\nHORAS\nDESDE\nHASTA", None)
    check_dur("nº9 horas 'NUMERO TOTAL DE HORAS'", "NUMERO TOTAL DE HORAS\n4 irs", None)
    check_dur("nº9 'CUADRO CLINICO DE 3 HORAS DE EVOLUCION'",
              "CUADRO CLINICO DE 3 HORAS DE EVOLUCION", None)
    check_dur("nº9 'CADA 8 HORAS'", "CADA 8 HORAS", None)
    check_dur("nº10 semanas de gestación", "EDADGESTASIONAL:\n40.00 Semanas", None)
    check_dur("nº11 nº de trámite 'IncapacidadN:362.355'", "Incapacidad N: 362.355", None)
    check_dur("nº11 consecutivo largo", "Consecutivo:\n0081523489", None)
    check_dur("nº11 'INCAPACIDADMEDICA#146012'", "INCAPACIDADMEDICA#146012", None)
    check_dur("nº12 'Regimen: 1 - Contributivo'", "Regimen: 1 - Contributivo", None)
    check_dur("nº12 'Pagina 1 de 1'", "Pagina 1 de 1", None)
    check_dur("nº13 signo vital 'F. Cardiaca: 113'", "F. Cardiaca: 113", None)
    check_dur("nº14 'una' como artículo en la prosa legal",
              "salvo que se trate de una fuerza mayor o caso fortuito.", None)
    check_dur("nº16 CIE-10 con dígitos", "DIAGNOSTICO CIE10 R509 FIEBRE NOESPECIFICADA", None)
    check_dur("nº17 vacaciones: 'el dia siete (07) de julio' es un DÍA DEL MES",
              "a partir del dia siete (07) de julio de dos mil veintiseis (2026)", None)
    check_dur("nº17 vacaciones: 'hasta el quince (15) de julio'",
              "hasta el quince (15) de julio de dos mil veintiseis (2026)", None)
    # Carta de vacaciones completa (texto sintético de scripts/sembrar_demo.py: no
    # hay ninguna carta real en el corpus). Aun dando None, la regla del repo sigue
    # siendo que en vacaciones los días se calculan por diferencia de fechas y este
    # parser debe quedar DESACTIVADO para tipo_documento == "vacaciones".
    check_dur("nº17 carta de vacaciones completa", "\n".join([
        "NOTIFICACION DE PERIODO DE VACACIONES",
        "Nos permitimos informar que disfrutara su periodo de vacaciones:",
        "a partir del primero (01) de julio de dos mil veintiseis (2026)",
        "hasta el quince (15) de julio de dos mil veintiseis (2026).",
        "Departamento de Gestion Humana",
    ]), None)
    check_dur("texto sin duración", "CERTIFICADO DE INCAPACIDAD", None)
    check_dur("vacío", "", None)
    check_dur("None", None, None)


def test_contrato() -> None:
    print("[9] Contrato del resultado (lo que consumirá la fase de integración)")
    got = duracion_en_texto("Dias: 2 (DOS DIAS)")
    esperadas = {"valor", "origen", "letra", "numero", "coincide", "evidencia"}
    check("claves exactas", got is not None and set(got) == esperadas,
          str(sorted(got)) if got else "None")
    check("valor es int", isinstance(got["valor"], int), type(got["valor"]).__name__)
    check("evidencia acotada (<=80 chars)", len(got["evidencia"]) <= 80, got["evidencia"])
    solo_num = duracion_en_texto("Dias:3")
    check("solo número → letra=None y coincide=None",
          solo_num["letra"] is None and solo_num["coincide"] is None, str(solo_num))


def test_limitaciones_conocidas() -> None:
    print("[10] Límites declarados (se prueban para que un cambio los haga visibles)")
    # C4 real: el OCR mete 'Fecha Fin' ENTRE el rótulo y el valor. Permitir saltar
    # renglones intermedios haría fallar el falso positivo nº7 (la rejilla
    # DIA/MES/ANO acaba en un número suelto), así que se prefiere None: el
    # extractor cae a calcular los días por el rango de fechas.
    check_dur("C4 con renglón intermedio → None (se degrada a cálculo por fechas)",
              "VIERNES 10 DEJULIODuracion\nFecha Fin\n14- CATORCE", None)
    # Dos duraciones en el mismo documento (visto en un PDF adulterado): devuelve
    # UNA sola; detectar el conflicto es trabajo del módulo que integra.
    got = duracion_en_texto("POR 4 DIAS DESDE EL 29-07-26\nPOR 5 DIAS DESDE 09-06-26")
    check("dos duraciones en el texto → devuelve la primera",
          got is not None and got["valor"] == 4, str(got))


def test_numerales_en_texto() -> None:
    print("[11] numerales_en_texto: material de la guarda de ANCLAJE del LLM")
    # No son duraciones (no se exige ancla): es el conjunto de valores PRESENTES,
    # para poder rechazar una duración que el modelo se haya inventado.
    vals = numerales_en_texto("Dias de Incapacidad: 2 (DOS DIAS) desde 10/06/2026 hasta 11/06/2026")
    check("el dígito y la palabra anclan el mismo 2", vals == {2}, str(sorted(vals)))
    check("una duración en LETRAS ancla su entero", 2 in numerales_en_texto("Duracion\n-DOS"),
          str(sorted(numerales_en_texto("Duracion\n-DOS"))))
    check("'treinta y cinco' ancla 35", 35 in numerales_en_texto("por treinta y cinco dias"))
    # El guardarraíl de _RE_NUM: años, consecutivos y fechas NO anclan nada.
    check("el año 2026 no ancla 2026 ni 202", not ({2026, 202} & numerales_en_texto("DE2026")),
          str(sorted(numerales_en_texto("DE2026"))))
    check("un consecutivo largo no ancla", numerales_en_texto("Consecutivo: 0081523489") == set(),
          str(sorted(numerales_en_texto("Consecutivo: 0081523489"))))
    check("una fecha no ancla su día/mes",
          numerales_en_texto("DESDE EL 29-07-26 HASTA EL 01/08/26") == set(),
          str(sorted(numerales_en_texto("DESDE EL 29-07-26 HASTA EL 01/08/26"))))
    check("vacío / None", numerales_en_texto("") == set() and numerales_en_texto(None) == set())


def main() -> int:
    print("=" * 64)
    print("PRUEBAS numeros_es (duraciones en números y en letras)")
    print("=" * 64)
    test_texto_a_entero()
    test_formas_y_apocopes()
    test_texto_a_entero_none()
    test_normalizar()
    test_formas_solo_numero()
    test_formas_con_letra()
    test_mixta_y_discrepancia()
    test_falsos_positivos()
    test_contrato()
    test_limitaciones_conocidas()
    test_numerales_en_texto()
    print("-" * 64)
    print("RESULTADO:", "TODO OK" if _fail == 0 else f"{_fail} fallo(s)")
    return 1 if _fail else 0


if __name__ == "__main__":
    sys.exit(main())
