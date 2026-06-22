"""
incapacidad_ocr — imagen de incapacidad médica → texto plano → JSON estructurado.

100% local: el OCR corre con RapidOCR (ONNX/CPU) o con un modelo de visión en
Ollama. NO usa ninguna API paga. Patrón inspirado en el invoice-processor de
SiesaTeams/quality-business-scripts, adaptado a incapacidades (Colombia).
"""
from .processor import process, IncapacidadProcessor
from .ocr import get_ocr_backend, StubOCR, RapidOCRBackend, OllamaVisionOCR
from .extract import RuleBasedExtractor, OllamaLLMExtractor, HybridExtractor, empty_record

__all__ = [
    "process", "IncapacidadProcessor",
    "get_ocr_backend", "StubOCR", "RapidOCRBackend", "OllamaVisionOCR",
    "RuleBasedExtractor", "OllamaLLMExtractor", "HybridExtractor", "empty_record",
]
