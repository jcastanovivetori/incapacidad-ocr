"""Orquestador: imagen → (OCR) texto plano → (extractor) JSON de incapacidad."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from .extract import Extractor, RuleBasedExtractor, empty_record, normalizar_fechas
from .ocr import OCRBackend, get_ocr_backend

# Mínimo de caracteres de OCR para intentar estructurar. Por debajo, NO se llama al
# extractor: un LLM puede INVENTAR un registro completo a partir de texto vacío
# (alucinación de PII médica). Mejor devolver vacío + aviso honesto.
MIN_OCR_CHARS = 10


class IncapacidadProcessor:
    """Une un backend de OCR con un extractor. Ambos son intercambiables."""

    def __init__(self, ocr: OCRBackend, extractor: Extractor | None = None) -> None:
        self.ocr = ocr
        self.extractor = extractor or RuleBasedExtractor()

    def run(self, image_path: str | Path) -> dict[str, Any]:
        texto_plano = self.ocr.read_text(image_path)
        out: dict[str, Any] = {
            "fuente": str(image_path),
            "ocr_backend": self.ocr.name,
            "extractor": self.extractor.name,
            "texto_plano": texto_plano,
        }
        if len(texto_plano.strip()) < MIN_OCR_CHARS:
            # Sin texto utilizable: no estructuramos (evita que el LLM fabrique datos).
            out["incapacidad"] = empty_record()
            out["aviso"] = (
                "El OCR no extrajo texto legible del documento. Si usaste 'Ollama visión', "
                "prueba con el motor 'RapidOCR' (más fiable para texto impreso) o sube una "
                "imagen/escaneo más nítido."
            )
            return out
        # extract() devuelve el registro completo (paciente/entidad/incapacidad/…).
        rec = self.extractor.extract(texto_plano)
        normalizar_fechas(rec)  # reconciliación única de fechas/días (regla del cliente)
        out["incapacidad"] = rec
        return out


def process(
    image_path: str | Path,
    ocr: str | OCRBackend = "rapidocr",
    extractor: Extractor | None = None,
    **ocr_kwargs,
) -> dict[str, Any]:
    """Atajo: ``process("foto.jpg")`` o ``process("foto.jpg", ocr="ollama")``."""
    backend = ocr if not isinstance(ocr, str) else get_ocr_backend(ocr, **ocr_kwargs)
    return IncapacidadProcessor(backend, extractor).run(image_path)
