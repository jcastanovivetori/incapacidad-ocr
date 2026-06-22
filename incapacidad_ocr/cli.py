"""CLI: procesa una imagen de incapacidad y emite el JSON.

Ejemplos:
    python -m incapacidad_ocr.cli foto.jpg
    python -m incapacidad_ocr.cli foto.jpg --ocr ollama --extractor ollama
    python -m incapacidad_ocr.cli foto.jpg --solo-texto
"""
from __future__ import annotations

import argparse
import json
import sys

from .extract import OllamaLLMExtractor, RuleBasedExtractor
from .ocr import get_ocr_backend
from .processor import IncapacidadProcessor


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Incapacidad médica: imagen → texto → JSON.")
    p.add_argument("imagen", help="Ruta a la imagen/escaneo de la incapacidad.")
    p.add_argument("--ocr", default="rapidocr", choices=["rapidocr", "ollama"],
                   help="Motor de OCR local (default: rapidocr).")
    p.add_argument("--extractor", default="rule", choices=["rule", "ollama"],
                   help="Estructurador: 'rule' (regex) u 'ollama' (LLM local).")
    p.add_argument("--ollama-url", default="http://localhost:11434")
    p.add_argument("--ocr-model", default="moondream:latest")
    p.add_argument("--llm-model", default="gemma3:4b")
    p.add_argument("--solo-texto", action="store_true", help="Solo imprime el texto OCR.")
    args = p.parse_args(argv)

    ocr_kwargs = {}
    if args.ocr == "ollama":
        ocr_kwargs = {"base_url": args.ollama_url, "model": args.ocr_model}
    ocr = get_ocr_backend(args.ocr, **ocr_kwargs)

    if args.solo_texto:
        print(ocr.read_text(args.imagen))
        return 0

    extractor = (
        OllamaLLMExtractor(base_url=args.ollama_url, model=args.llm_model)
        if args.extractor == "ollama"
        else RuleBasedExtractor()
    )
    result = IncapacidadProcessor(ocr, extractor).run(args.imagen)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
