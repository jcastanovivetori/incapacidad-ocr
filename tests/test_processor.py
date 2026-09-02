"""Pruebas del pipeline incapacidad-ocr (ejecutable con python puro, sin pytest).

    python tests/test_processor.py

Cubre: extractor por reglas (determinista), preprocesado, parseo JSON, pipeline
end-to-end con StubOCR y —si rapidocr está instalado— OCR REAL sobre una imagen
sintética generada al vuelo (imagen → texto → JSON).
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

try:  # consola Windows (cp1252) → forzar UTF-8 para acentos
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # noqa: BLE001
    pass

from incapacidad_ocr import IncapacidadProcessor, RuleBasedExtractor, StubOCR, process  # noqa: E402
from incapacidad_ocr.extract import HybridExtractor, parse_json_response  # noqa: E402
from incapacidad_ocr.preprocess import load_image, to_png_base64  # noqa: E402
from make_sample import CANONICAL_TEXT, EXPECTED, make_sample  # noqa: E402

_fail = 0


def check(name: str, cond: bool, detail: str = "") -> None:
    global _fail
    ok = bool(cond)
    if not ok:
        _fail += 1
    print(("  PASS " if ok else "  FAIL ") + name + (f"  ->  {detail}" if detail else ""))


def test_rule_based() -> None:
    print("[1] Extractor por reglas (texto canónico)")
    rec = RuleBasedExtractor().extract(CANONICAL_TEXT)
    p, e, i, d = rec["paciente"], rec["entidad"], rec["incapacidad"], rec["diagnostico"]
    check("paciente.nombre", p["nombre"] == EXPECTED["paciente_nombre"], p["nombre"])
    check("documento_tipo", p["documento_tipo"] == EXPECTED["documento_tipo"], p["documento_tipo"])
    check("documento_numero", p["documento_numero"] == EXPECTED["documento_numero"], p["documento_numero"])
    check("eps", e["eps"] == "SURA", e["eps"])
    check("ips_prestador", e["ips_prestador"] == "CLINICA LAS AMERICAS", e["ips_prestador"])
    check("fecha_inicio", i["fecha_inicio"] == EXPECTED["fecha_inicio"], i["fecha_inicio"])
    check("fecha_fin", i["fecha_fin"] == EXPECTED["fecha_fin"], i["fecha_fin"])
    check("fecha_expedicion", i["fecha_expedicion"] == EXPECTED["fecha_expedicion"], i["fecha_expedicion"])
    check("dias", i["dias"] == EXPECTED["dias"], str(i["dias"]))
    check("tipo", i["tipo"] == EXPECTED["tipo"], i["tipo"])
    check("cie10", d["cie10"] == EXPECTED["cie10"], d["cie10"])
    check("diagnostico.descripcion", (d["descripcion"] or "").startswith("Infeccion aguda"), d["descripcion"])
    check("medico.nombre", rec["medico"]["nombre"] == "ANA TORRES", rec["medico"]["nombre"])
    check("medico.registro", rec["medico"]["registro"] == "12345", rec["medico"]["registro"])


def test_parse_json() -> None:
    print("[2] parse_json_response (tolera ```json``` y texto extra)")
    raw = '```json\n{"dias": 3, "ok": true}\n```'
    check("limpia fences", parse_json_response(raw) == {"dias": 3, "ok": True})
    raw2 = 'Claro, aquí tienes:\n{"a": 1}\nfin'
    check("rescata objeto embebido", parse_json_response(raw2) == {"a": 1})


def test_preprocess() -> None:
    print("[3] Preprocesado (genera imagen + resize + base64)")
    path = make_sample()
    check("imagen creada", path.exists(), str(path))
    b64 = to_png_base64(load_image(path), max_dim=800)
    check("base64 no vacío", isinstance(b64, str) and len(b64) > 100, f"{len(b64)} chars")


def test_e2e_stub() -> None:
    print("[4] End-to-end con StubOCR (pipeline completo, determinista)")
    res = IncapacidadProcessor(StubOCR(CANONICAL_TEXT), RuleBasedExtractor()).run("fake.png")
    inc = res["incapacidad"]
    check("backend=stub", res["ocr_backend"] == "stub")
    check("doc number", inc["paciente"]["documento_numero"] == EXPECTED["documento_numero"])
    check("dias", inc["incapacidad"]["dias"] == EXPECTED["dias"], str(inc["incapacidad"]["dias"]))


def test_e2e_real_ocr() -> None:
    print("[5] End-to-end OCR REAL (rapidocr) sobre imagen sintética")
    try:
        import rapidocr_onnxruntime  # noqa: F401
    except Exception as exc:  # noqa: BLE001
        print(f"  SKIP  rapidocr no instalado ({exc.__class__.__name__}); "
              "el OCR real corre con rapidocr u ollama en runtime.")
        return
    path = make_sample()
    res = process(path, ocr="rapidocr", extractor=RuleBasedExtractor())
    texto = res["texto_plano"]
    print("  --- texto OCR (primeras líneas) ---")
    for ln in [l for l in texto.splitlines() if l.strip()][:8]:
        print("     ", ln)
    inc = res["incapacidad"]
    check("OCR contiene documento", EXPECTED["documento_numero"] in texto.replace(" ", ""))
    check("OCR contiene fecha", EXPECTED["fecha_inicio"] in texto)
    check("estructura doc number",
          inc["paciente"]["documento_numero"] == EXPECTED["documento_numero"],
          inc["paciente"]["documento_numero"])
    check("estructura dias", inc["incapacidad"]["dias"] == EXPECTED["dias"], str(inc["incapacidad"]["dias"]))
    check("estructura fecha_inicio",
          inc["incapacidad"]["fecha_inicio"] == EXPECTED["fecha_inicio"],
          inc["incapacidad"]["fecha_inicio"])
    check("estructura cie10 (J06*)", (inc["diagnostico"]["cie10"] or "").startswith("J06"),
          inc["diagnostico"]["cie10"])


# --------------------------------------------------------------------------- #
# Duraciones escritas en NÚMEROS, en LETRAS y en las dos ("DOS (2) DIAS")
# --------------------------------------------------------------------------- #
# Textos SINTÉTICOS que reproducen las formas del corpus real (A/B/C de
# dataset-falsedad/duraciones/01_evidencia.md) con datos inventados: aquí no va
# ningún nombre, cédula ni diagnóstico de un documento real (PII, Ley 1581).
_CABECERA = (
    "EPS SURA\n"
    "CERTIFICADO DE INCAPACIDAD MEDICA\n"
    "Paciente: JUAN PEREZ GOMEZ\n"
    "Documento: CC 1098765432\n"
)

# B1 (Sura): el OCR se comió el dígito y sobrevive SOLO la palabra, en el renglón
# ANTERIOR al rótulo. Leer la letra es la ÚNICA forma de tener el dato.
TEXTO_SOLO_LETRA = _CABECERA + (
    "Fecha Inicial: 10/06/2026\n"
    "-DOS\n"
    "Duracion\n"
    "Diagnostico: J06.9 Infeccion aguda\n"
)
# C1: número y palabra CONCUERDAN (la forma más frecuente del corpus).
TEXTO_MIXTO_OK = _CABECERA + (
    "Fecha Inicial: 10/06/2026\n"
    "Fecha Final: 11/06/2026\n"
    "Dias: 2 (DOS DIAS)\n"
)
# C1 con DESACUERDO palabra↔dígito: no se ha visto en el corpus, se instrumenta.
TEXTO_MIXTO_DISCREPANTE = _CABECERA + (
    "Fecha Inicial: 10/06/2026\n"
    "Fecha Final: 11/06/2026\n"
    "Dias: 2 (TRES DIAS)\n"
)
# C5 (Sofisis): la PALABRA va primero y el número entre paréntesis con cero a la
# izquierda. Es la forma "DOS (2)" que describe el cliente.
TEXTO_PALABRA_PRIMERO = _CABECERA + (
    "DIASDEINCAPACIDAD\n"
    "DOS (02)\n"
    "APARTIRDELAFECHA\n"
    "Fecha Inicial: 10/06/2026\n"
)
# A5: el día del mes de la fecha NO es la duración (falso positivo nº5).
TEXTO_PROSA = _CABECERA + (
    "SE DA INCAPACIDAD MEDICA POR 4 DIAS DESDE EL 29-07-2026 HASTA EL 01-08-2026\n"
)
# Carta de VACACIONES: aquí "(07) de julio" es un DÍA DEL MES y "dos mil
# veintiseis" el AÑO en palabras. Los días salen SIEMPRE de la diferencia de
# fechas (07/07 → 20/07 = 14), nunca de una etiqueta: si el parser de letras se
# activara aquí, leería 7 o 20 y corrompería la nómina.
TEXTO_VACACIONES = (
    "NOTIFICACION DE PERIODO DE VACACIONES\n"
    "Señor(a): JUAN PEREZ GOMEZ  CC: 1098765432\n"
    "Nos permitimos informar que disfrutara su periodo de vacaciones a partir del\n"
    "dia siete (07) de julio de dos mil veintiseis (2026) hasta el veinte (20) de\n"
    "julio de dos mil veintiseis (2026).\n"
    "Departamento de Gestion Humana\n"
)


# Tabla "DETALLE DE LA INCAPACIDAD" (Clínica del Cesar): 5 encabezados y sus 5
# valores en bloque. La celda de días es una COLUMNA FIJA, así que su posición ya
# es el ancla: se acepta el dígito, la palabra o las dos.
def _texto_detalle(celda_dias: str) -> str:
    return _CABECERA + (
        "DETALLE DE LA INCAPACIDAD\n"
        "Causa Externa Diagnostico Dias Inc. Inicio Finalizacion\n"
        "ENFERMEDAD_GENERAL\n"
        "J069 INFECCION AGUDA DE VIAS RESPIRATORIAS\n"
        f"{celda_dias}\n"
        "10/06/2026\n"
        "12/06/2026\n"
    )


def _corre(texto: str) -> dict:
    """Pipeline completo (StubOCR + reglas + normalizar_fechas) sobre un texto."""
    return IncapacidadProcessor(StubOCR(texto), RuleBasedExtractor()).run("fake.png")["incapacidad"]


def test_dias_en_letras() -> None:
    print("[6] Duración en LETRAS / mixta / vacaciones (end-to-end con StubOCR)")
    inc = _corre(TEXTO_SOLO_LETRA)["incapacidad"]
    check("B1 solo letra ('-DOS') → dias=2", inc["dias"] == 2, str(inc["dias"]))
    check("B1 dias_letra=2", inc["dias_letra"] == 2, str(inc["dias_letra"]))
    check("B1 coincide=None (no hay dígito que comparar)",
          inc["dias_letra_coincide"] is None, str(inc["dias_letra_coincide"]))
    check("B1 fin derivado por normalizar_fechas", inc["fecha_fin"] == "2026-06-11", inc["fecha_fin"])

    inc = _corre(TEXTO_MIXTO_OK)["incapacidad"]
    check("C1 mixta coincidente → dias=2", inc["dias"] == 2, str(inc["dias"]))
    check("C1 dias_letra=2 y coincide=True",
          inc["dias_letra"] == 2 and inc["dias_letra_coincide"] is True,
          f"{inc['dias_letra']} / {inc['dias_letra_coincide']}")

    inc = _corre(TEXTO_MIXTO_DISCREPANTE)["incapacidad"]
    check("mixta DISCREPANTE → manda el DÍGITO (dias=2)", inc["dias"] == 2, str(inc["dias"]))
    check("mixta DISCREPANTE → dias_letra=3 y coincide=False",
          inc["dias_letra"] == 3 and inc["dias_letra_coincide"] is False,
          f"{inc['dias_letra']} / {inc['dias_letra_coincide']}")

    inc = _corre(TEXTO_PALABRA_PRIMERO)["incapacidad"]
    check("C5 'DOS (02)' (palabra primero) → dias=2", inc["dias"] == 2, str(inc["dias"]))

    inc = _corre(TEXTO_PROSA)["incapacidad"]
    check("A5 'POR 4 DIAS DESDE EL 29-07-2026' → 4, no el día del mes (29)",
          inc["dias"] == 4, str(inc["dias"]))

    # Layout de formulario "Dias Fecha Inicia" (AM-Sistemas): el valor va PEGADO a la
    # fecha que el rótulo ancla ("511/06/2026" = 5 días + 11/06). El ancla es
    # posicional, así que también vale en letras; y una palabra que NO es numeral
    # ("Comun 11/06/2026") no lee nada.
    def _texto_dias_fecha(celda: str) -> str:
        return _CABECERA + f"Dias Fecha Inicia Fecha Final\n{celda}\n15/06/2026\n"

    inc = _corre(_texto_dias_fecha("511/06/2026"))["incapacidad"]
    check("'Dias Fecha Inicia' con dígito pegado → dias=5 (sin regresión)",
          inc["dias"] == 5, str(inc["dias"]))
    inc = _corre(_texto_dias_fecha("CINCO 11/06/2026"))["incapacidad"]
    check("'Dias Fecha Inicia' con la duración en letras → dias=5",
          inc["dias"] == 5 and inc["dias_letra"] == 5, f"{inc['dias']} / {inc['dias_letra']}")
    inc = _corre(_texto_dias_fecha("COMUN 11/06/2026"))["incapacidad"]
    check("'Dias Fecha Inicia': una palabra que no es numeral no inventa duración",
          inc["dias_letra"] is None, str(inc["dias_letra"]))

    # Tabla "DETALLE DE LA INCAPACIDAD": el dígito solo (como siempre), el mixto y
    # la palabra sola. Antes, una celda que no fueran dígitos puros tumbaba TODO el
    # bloque (y con él el CIE-10 y las fechas de la tabla).
    inc = _corre(_texto_detalle("3"))["incapacidad"]
    check("tabla DETALLE con dígito → dias=3 (sin regresión)", inc["dias"] == 3, str(inc["dias"]))
    rec = _corre(_texto_detalle("3 (TRES)"))
    inc = rec["incapacidad"]
    check("tabla DETALLE con '3 (TRES)' → dias=3 y coincide=True",
          inc["dias"] == 3 and inc["dias_letra"] == 3 and inc["dias_letra_coincide"] is True,
          f"{inc['dias']} / {inc['dias_letra']} / {inc['dias_letra_coincide']}")
    check("tabla DETALLE: el CIE-10 sigue saliendo de la tabla",
          rec["diagnostico"]["cie10"] == "J06.9", rec["diagnostico"]["cie10"])
    inc = _corre(_texto_detalle("TRES"))["incapacidad"]
    check("tabla DETALLE con solo la palabra ('TRES') → dias=3",
          inc["dias"] == 3 and inc["dias_letra"] == 3, f"{inc['dias']} / {inc['dias_letra']}")

    # VACACIONES: ni una duración leída por etiqueta/letra; solo la diferencia de fechas.
    res = _corre(TEXTO_VACACIONES)
    inc = res["incapacidad"]
    check("vacaciones: tipo_documento", res["tipo_documento"] == "vacaciones", res["tipo_documento"])
    check("vacaciones: fechas de la prosa",
          (inc["fecha_inicio"], inc["fecha_fin"]) == ("2026-07-07", "2026-07-20"),
          f"{inc['fecha_inicio']} → {inc['fecha_fin']}")
    check("vacaciones: dias por diferencia de fechas (14), no '7'/'20'/'2026'",
          inc["dias"] == 14, str(inc["dias"]))
    check("vacaciones: NO se lee ninguna duración en letras",
          inc["dias_letra"] is None and inc["dias_letra_coincide"] is None,
          f"{inc['dias_letra']} / {inc['dias_letra_coincide']}")


# --------------------------------------------------------------------------- #
# Fusión híbrida con el LLM SIMULADO
# --------------------------------------------------------------------------- #
# Ollama no está disponible en el entorno de pruebas (y no debe estarlo: las
# pruebas son deterministas y offline), así que se inyecta un extractor falso que
# devuelve un JSON fijo — mismo patrón que ``StubOCR`` para el OCR. Esto cubre la
# POLÍTICA de fusión y sus guardas; NO valida el prompt ni el modelo real.
class StubLLM:
    """Extractor que devuelve una respuesta fija (o revienta, si se le pide)."""

    name = "stub-llm"

    def __init__(self, rec: dict | None = None, falla: bool = False) -> None:
        self.rec = rec or {}
        self.falla = falla

    def extract(self, text: str) -> dict:
        if self.falla:
            raise RuntimeError("Ollama no disponible (simulado)")
        return self.rec


def test_hibrido_llm_simulado() -> None:
    print("[7] HybridExtractor con LLM SIMULADO (fusión + guardas de anclaje)")
    # Rótulo con el valor perdido por el OCR (forma A10) y la palabra suelta lejos
    # del rótulo: las reglas no pueden anclarla → aquí sí aporta el LLM.
    texto_a10 = _CABECERA + (
        "Dias de Incapacidad:\n"
        "Estado Civil: SOLTERO\n"
        "Observaciones: SE CONCEDE INCAPACIDAD DE DOS\n"
    )
    solo_reglas = RuleBasedExtractor().extract(texto_a10)
    check("reglas solas no inventan la duración perdida",
          solo_reglas["incapacidad"]["dias"] is None, str(solo_reglas["incapacidad"]["dias"]))
    rec = HybridExtractor(llm=StubLLM({"incapacidad": {"dias": 2}})).extract(texto_a10)
    check("LLM dias=2 ANCLADO por la palabra 'DOS' del texto → se acepta",
          rec["incapacidad"]["dias"] == 2, str(rec["incapacidad"]["dias"]))

    texto_fechas = _CABECERA + "Incapacidad desde: 10/06/2026 hasta: 11/06/2026\n"
    rec = HybridExtractor(llm=StubLLM({"incapacidad": {"dias": 45}})).extract(texto_fechas)
    check("LLM dias=45 que NO está en el texto → se descarta (se queda el de reglas)",
          rec["incapacidad"]["dias"] == 2, str(rec["incapacidad"]["dias"]))
    rec = HybridExtractor(llm=StubLLM({"incapacidad": {"dias": "2"}})).extract(texto_fechas)
    check("LLM dias='2' (cadena) → se convierte a entero", rec["incapacidad"]["dias"] == 2,
          repr(rec["incapacidad"]["dias"]))
    rec = HybridExtractor(llm=StubLLM({"incapacidad": {"dias": 700}})).extract(texto_fechas)
    check("LLM dias=700 (fuera de 1..540) → se descarta", rec["incapacidad"]["dias"] == 2,
          str(rec["incapacidad"]["dias"]))
    rec = HybridExtractor(llm=StubLLM({"incapacidad": {"fecha_fin": "2026-12-31"}})).extract(texto_fechas)
    check("guarda de fechas: una fecha que no está en el texto se descarta",
          rec["incapacidad"]["fecha_fin"] == "2026-06-11", rec["incapacidad"]["fecha_fin"])

    # Doble evidencia (dígito + palabra concordantes) → las reglas pesan más que el LLM.
    texto_mixto = TEXTO_MIXTO_OK + "Nivel: 1\n"
    rec = HybridExtractor(llm=StubLLM({"incapacidad": {"dias": 1}})).extract(texto_mixto)
    check("mixta coincidente: gana la lectura de reglas (2), no el LLM (1)",
          rec["incapacidad"]["dias"] == 2, str(rec["incapacidad"]["dias"]))
    check("la fusión conserva dias_letra/coincide",
          rec["incapacidad"]["dias_letra"] == 2 and rec["incapacidad"]["dias_letra_coincide"] is True,
          f"{rec['incapacidad']['dias_letra']} / {rec['incapacidad']['dias_letra_coincide']}")

    # VACACIONES: la fusión NO deja que el LLM ponga los días (regla de dominio) y
    # conserva el tipo de documento que detectaron las reglas.
    rec = HybridExtractor(llm=StubLLM({"incapacidad": {"dias": 7}})).extract(TEXTO_VACACIONES)
    check("vacaciones: la fusión conserva tipo_documento",
          rec["tipo_documento"] == "vacaciones", str(rec["tipo_documento"]))
    check("vacaciones: el LLM NO impone los días (14 por fechas, no 7)",
          rec["incapacidad"]["dias"] == 14, str(rec["incapacidad"]["dias"]))

    # Degradación: Ollama caído → solo reglas (comportamiento de siempre).
    rec = HybridExtractor(llm=StubLLM(falla=True)).extract(texto_fechas)
    check("LLM caído → degrada a reglas", rec["incapacidad"]["dias"] == 2,
          str(rec["incapacidad"]["dias"]))
    rec = HybridExtractor(llm=StubLLM({"error": "respuesta no-JSON del modelo"})).extract(texto_fechas)
    check("respuesta no-JSON del modelo → degrada a reglas", rec["incapacidad"]["dias"] == 2,
          str(rec["incapacidad"]["dias"]))


def main() -> int:
    print("=" * 64)
    print("PRUEBAS incapacidad-ocr")
    print("=" * 64)
    test_rule_based()
    test_parse_json()
    test_preprocess()
    test_e2e_stub()
    test_e2e_real_ocr()
    test_dias_en_letras()
    test_hibrido_llm_simulado()
    print("-" * 64)
    print("RESULTADO:", "TODO OK" if _fail == 0 else f"{_fail} fallo(s)")
    return 1 if _fail else 0


if __name__ == "__main__":
    sys.exit(main())
