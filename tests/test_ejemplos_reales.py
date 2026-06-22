"""Evaluación del pipeline sobre las incapacidades REALES de ``Ejemplos/``.

    python tests/test_ejemplos_reales.py

Corre el pipeline completo (PDF/imagen → RapidOCR → RuleBasedExtractor) sobre cada
documento de la carpeta y compara los campos núcleo contra un ground-truth leído a
mano del OCR. Imprime el JSON extraído y un puntaje de precisión por documento y total.

Campos núcleo evaluados: documento_numero, cie10, fecha_inicio, fecha_fin, dias, origen.
(El nombre del paciente/médico se muestra pero no se puntúa: el OCR suele pegar o
distorsionar los nombres y eso es justo lo que el path de Ollama-visión resolvería.)
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # noqa: BLE001
    pass

from incapacidad_ocr import process, RuleBasedExtractor  # noqa: E402

EJEMPLOS = ROOT.parent / "Ejemplos"

# Ground-truth (campos núcleo). Un valor, o un set de valores aceptables, o None
# para "no puntuar este campo en este documento".
GROUND_TRUTH = {
    "ALEJANDRO LINARES.pdf": {
        "documento_numero": "1151480134", "cie10": "S42.0",
        "fecha_inicio": "2026-06-08", "fecha_fin": "2026-07-07", "dias": 30,
        "origen": "Comun",
    },
    "CESAR ARMANDO LANCHEROS CHAPARRO_INCAPACIDAD.pdf": {
        "documento_numero": "1095817662", "cie10": "M54.4",
        "fecha_inicio": "2026-06-11", "fecha_fin": "2026-06-13", "dias": 3,
        "origen": None,
    },
    "Incapacidad (19)_unlocked.pdf": {
        "documento_numero": "91349897", "cie10": "M75.1",
        "fecha_inicio": "2026-05-25", "fecha_fin": "2026-06-23", "dias": 30,
        "origen": "Laboral",
    },
    "INCAPACIDAD MICHAEL ALEXIZ MORENO VĘLANDIA.pdf": {
        "documento_numero": "1005542119", "cie10": "A09.9",
        "fecha_inicio": "2026-06-10", "fecha_fin": "2026-06-11", "dias": 2,
        "origen": "Comun",
    },
    "incapacidad.jpeg": {
        "documento_numero": "63523940", "cie10": "J39.9",
        "fecha_inicio": "2026-06-11", "fecha_fin": "2026-06-15", "dias": 5,
        "origen": None,
    },
    "incapacidad.pdf": {
        "documento_numero": "13742111", "cie10": "K42.9",
        "fecha_inicio": "2026-06-09", "fecha_fin": "2026-06-23", "dias": 15,
        "origen": "Comun",
    },
    "incapacidad_.jpeg": {
        "documento_numero": "1098757631", "cie10": None,
        "fecha_inicio": "2026-06-10", "fecha_fin": "2026-06-12", "dias": 3,
        "origen": "Laboral",
    },
    "incapacidad___.jpeg": {
        "documento_numero": {"1095912481", "1095012481"}, "cie10": "R07.4",
        "fecha_inicio": "2026-05-25", "fecha_fin": "2026-05-27", "dias": 3,
        "origen": "Laboral",
    },
}

FIELD_PATH = {
    "documento_numero": ("paciente", "documento_numero"),
    "cie10": ("diagnostico", "cie10"),
    "fecha_inicio": ("incapacidad", "fecha_inicio"),
    "fecha_fin": ("incapacidad", "fecha_fin"),
    "dias": ("incapacidad", "dias"),
    "origen": ("incapacidad", "origen"),
}


def _get(rec: dict, path: tuple[str, str]):
    return rec.get(path[0], {}).get(path[1])


def _ok(expected, got) -> bool:
    if isinstance(expected, set):
        return got in expected
    if isinstance(expected, str) and isinstance(got, str):
        return expected.lower() in got.lower() or got.lower() in expected.lower()
    return expected == got


def main() -> int:
    if not EJEMPLOS.exists():
        print("No existe la carpeta Ejemplos/:", EJEMPLOS)
        return 1
    try:
        import rapidocr_onnxruntime  # noqa: F401
    except Exception as exc:  # noqa: BLE001
        print(f"SKIP: rapidocr no instalado ({exc.__class__.__name__}).")
        return 0

    total_ok = total = 0
    print("=" * 78)
    print("EVALUACIÓN sobre incapacidades reales (Ejemplos/)")
    print("=" * 78)
    for fname, truth in GROUND_TRUTH.items():
        path = EJEMPLOS / fname
        print("\n" + "-" * 78)
        print("DOC:", fname)
        if not path.exists():
            print("  (archivo no encontrado, se omite)")
            continue
        res = process(path, ocr="rapidocr", extractor=RuleBasedExtractor())
        inc = res["incapacidad"]
        print("  nombre   :", inc["paciente"]["nombre"])
        print("  medico   :", inc["medico"]["nombre"], "| reg:", inc["medico"]["registro"])
        print("  eps      :", inc["entidad"]["eps"])
        doc_ok = 0
        doc_n = 0
        for field, expected in truth.items():
            if expected is None:
                continue
            got = _get(inc, FIELD_PATH[field])
            ok = _ok(expected, got)
            doc_n += 1
            doc_ok += int(ok)
            exp_disp = expected if not isinstance(expected, set) else "/".join(expected)
            print(f"  [{'OK ' if ok else 'XX '}] {field:16} esperado={exp_disp!s:14} obtenido={got!s}")
        total_ok += doc_ok
        total += doc_n
        print(f"  -> {doc_ok}/{doc_n} campos núcleo correctos")
    print("\n" + "=" * 78)
    pct = (100 * total_ok / total) if total else 0
    print(f"PRECISIÓN TOTAL (campos núcleo): {total_ok}/{total} = {pct:.0f}%")
    print("=" * 78)
    return 0


if __name__ == "__main__":
    sys.exit(main())
