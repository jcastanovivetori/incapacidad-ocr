"""Backends de OCR: imagen → texto plano. Pluggables e intercambiables.

- ``RapidOCRBackend``  : OCR local con rapidocr-onnxruntime (ONNX/CPU, sin servicios externos).
- ``OllamaVisionOCR``  : OCR con un modelo de visión local en Ollama (mismo enfoque que el invoice-processor).
- ``StubOCR``          : devuelve un texto fijo (para pruebas deterministas).

Ningún backend usa una API paga. ``httpx`` y ``rapidocr`` se importan de forma
perezosa para que el módulo sea utilizable aunque esas dependencias no estén.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Protocol, runtime_checkable

OCR_PROMPT = (
    "Lee TODO el texto visible en esta imagen. Transcribe cada palabra, número y "
    "símbolo exactamente como aparece, conservando el orden y los saltos de línea. "
    "NO describas la imagen. NO resumas. Devuelve únicamente el texto transcrito."
)


class OllamaError(RuntimeError):
    """Error operativo al comunicarse con Ollama (modelo faltante o servicio caído).

    Lleva un mensaje en español apto para mostrarse al usuario (sin internos).
    """


def translate_ollama_error(exc: Exception, model: str, kind: str) -> "OllamaError":
    """Convierte un fallo de httpx contra Ollama en un mensaje accionable."""
    import httpx  # import perezoso

    if isinstance(exc, httpx.HTTPStatusError):
        if exc.response.status_code == 404:
            base = model.split(":")[0]
            return OllamaError(
                f"El modelo de {kind} '{model}' no está disponible en Ollama. "
                f"Descárgalo una vez con:  docker compose exec ollama ollama pull {base}"
            )
        return OllamaError(f"Ollama respondió un error {exc.response.status_code}.")
    return OllamaError(
        "No se pudo conectar con Ollama. Verifica que el contenedor 'ollama' esté corriendo."
    )


@runtime_checkable
class OCRBackend(Protocol):
    name: str

    def read_text(self, image_path: str | Path) -> str:
        ...


class StubOCR:
    """Backend determinista para pruebas: devuelve el texto que se le pasa."""

    name = "stub"

    def __init__(self, text: str) -> None:
        self._text = text

    def read_text(self, image_path: str | Path) -> str:  # noqa: ARG002
        return self._text


class RapidOCRBackend:
    """OCR local vía rapidocr-onnxruntime (CPU, modelos ONNX embebidos).

    Acepta imágenes (JPG/PNG/...) y PDFs. Los PDFs se renderizan página a página
    con PDFium y el texto de todas las páginas se concatena.
    """

    name = "rapidocr"

    def __init__(self) -> None:
        from rapidocr_onnxruntime import RapidOCR  # import perezoso

        self._engine = RapidOCR()

    def _ocr_one(self, image) -> str:
        import numpy as np  # import perezoso

        result, _elapsed = self._engine(np.asarray(image))
        if not result:
            return ""
        # result: lista [[box, texto, score], ...] ya en orden de lectura
        return "\n".join(item[1] for item in result)

    def read_text(self, image_path: str | Path) -> str:
        from .preprocess import load_pages

        pages = load_pages(image_path)
        return "\n".join(self._ocr_one(page) for page in pages).strip()


class OllamaVisionOCR:
    """OCR con un modelo de visión servido localmente por Ollama.

    Usa un VLM capaz de transcribir (p.ej. ``qwen2.5vl:3b``). Para acelerar en CPU,
    la imagen se reescala a ``vision_max_dim`` (un VLM no necesita 1600px para leer).
    """

    name = "ollama-vision"

    def __init__(
        self,
        base_url: str = "http://localhost:11434",
        model: str = "qwen2.5vl:3b",
        timeout: float | None = None,
        vision_max_dim: int | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        # En CPU la inferencia de visión es lenta → timeout amplio (configurable).
        self.timeout = timeout if timeout is not None else float(os.environ.get("OLLAMA_TIMEOUT", 900))
        self.vision_max_dim = vision_max_dim or int(os.environ.get("VISION_MAX_DIM", 1200))

    def read_text(self, image_path: str | Path) -> str:
        import httpx  # import perezoso

        from .preprocess import load_pages, to_png_base64

        pages = load_pages(image_path)
        out = []
        with httpx.Client(timeout=self.timeout) as client:
            for page in pages:
                try:
                    resp = client.post(
                        f"{self.base_url}/api/chat",
                        json={
                            "model": self.model,
                            "messages": [
                                {"role": "user", "content": OCR_PROMPT,
                                 "images": [to_png_base64(page, max_dim=self.vision_max_dim)]}
                            ],
                            "stream": False,
                            "options": {"temperature": 0.0},
                        },
                    )
                    resp.raise_for_status()
                except (httpx.HTTPStatusError, httpx.RequestError) as e:
                    raise translate_ollama_error(e, self.model, "visión") from e
                out.append(resp.json()["message"]["content"])
        return "\n".join(out).strip()


def get_ocr_backend(name: str, **kwargs) -> OCRBackend:
    """Factory por nombre: ``rapidocr`` | ``ollama`` (alias ``ollama-vision``)."""
    key = name.lower()
    if key == "rapidocr":
        return RapidOCRBackend()
    if key in ("ollama", "ollama-vision"):
        return OllamaVisionOCR(**kwargs)
    raise ValueError(f"Backend de OCR desconocido: {name!r} (usa 'rapidocr' u 'ollama').")
