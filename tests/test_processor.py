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
from incapacidad_ocr.extract import parse_json_response  # noqa: E402
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


def main() -> int:
    print("=" * 64)
    print("PRUEBAS incapacidad-ocr")
    print("=" * 64)
    test_rule_based()
    test_parse_json()
    test_preprocess()
    test_e2e_stub()
    test_e2e_real_ocr()
    print("-" * 64)
    print("RESULTADO:", "TODO OK" if _fail == 0 else f"{_fail} fallo(s)")
    return 1 if _fail else 0


if __name__ == "__main__":
    sys.exit(main())
