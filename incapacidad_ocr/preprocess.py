"""Carga y normalización de imágenes (y PDFs) para los backends de OCR.

Robustez con documentos PESADOS: las páginas se generan de a UNA (streaming), así el
pico de memoria es una página a la vez (no el PDF entero materializado); y cada página
se acota a ``OCR_MAX_PIXELS`` para que un escaneo enorme no dispare la RAM ni el OCR.
Todos los topes son configurables por variables de entorno.
"""
from __future__ import annotations

import base64
import logging
import os
from io import BytesIO
from pathlib import Path
from typing import Iterator

from PIL import Image

log = logging.getLogger("incapacidad_ocr.preprocess")

MAX_DIM = 1600
# ~216 DPI: buen balance nitidez/tamaño para OCR de formularios (configurable).
PDF_RENDER_SCALE = float(os.environ.get("PDF_RENDER_SCALE", 3.0))
# Tope de páginas a procesar de un PDF (anti-DoS: PDFs de miles de páginas).
MAX_PDF_PAGES = int(os.environ.get("MAX_PDF_PAGES", 30))
# Tope de píxeles por página que se entrega al OCR: por encima, se reescala (protege la
# RAM y evita que un escaneo a muy alta resolución tumbe el proceso). 40 MP deja pasar
# intactos los documentos normales (una A4 a escala 3.0 ≈ 8.7 MP).
OCR_MAX_PIXELS = int(os.environ.get("OCR_MAX_PIXELS", 40_000_000))
# Anti "bomba de descompresión" (Pillow). Configurable; ampliado para escaneos grandes
# legítimos de un feeder de confianza. None lo desactiva (no recomendado).
_mp = os.environ.get("MAX_IMAGE_PIXELS", "200000000")
Image.MAX_IMAGE_PIXELS = None if _mp.lower() in ("", "none", "0") else int(_mp)


def _cap_pixels(img: Image.Image, max_px: int = OCR_MAX_PIXELS) -> Image.Image:
    """Reescala la imagen SOLO si supera ``max_px`` (protege RAM/OCR en escaneos enormes)."""
    px = img.width * img.height
    if max_px and px > max_px:
        ratio = (max_px / px) ** 0.5
        nueva = (max(1, int(img.width * ratio)), max(1, int(img.height * ratio)))
        log.info("Página grande (%d MP) reescalada a %dx%d", px // 1_000_000, *nueva)
        img = img.resize(nueva, Image.LANCZOS)
    return img


def load_image(path: str | Path) -> Image.Image:
    """Abre la imagen y la deja en un modo manejable (RGB/L)."""
    img = Image.open(path)
    if img.mode not in ("RGB", "L"):
        img = img.convert("RGB")
    return img


def pdf_to_images(path: str | Path, scale: float | None = None) -> Iterator[Image.Image]:
    """Renderiza cada página de un PDF a una imagen PIL (local, vía pypdfium2/PDFium).

    GENERADOR: rinde una página a la vez (memoria acotada). Procesa como máximo
    ``MAX_PDF_PAGES`` páginas; si el PDF trae más, lo registra (no falla en silencio).
    """
    import pypdfium2 as pdfium  # import perezoso (dependencia opcional)

    scale = scale if scale is not None else PDF_RENDER_SCALE
    pdf = pdfium.PdfDocument(str(path))
    try:
        total = len(pdf)
        n = min(total, MAX_PDF_PAGES)
        if total > MAX_PDF_PAGES:
            log.warning("PDF con %d páginas; se procesan solo las primeras %d (MAX_PDF_PAGES)", total, n)
        for i in range(n):
            page = pdf[i]
            img = page.render(scale=scale).to_pil()
            yield _cap_pixels(img)
    finally:
        pdf.close()


def load_pages(path: str | Path) -> Iterator[Image.Image]:
    """Carga un documento como imágenes (GENERADOR): PDF → una por página; imagen → una."""
    if str(path).lower().endswith(".pdf"):
        yield from pdf_to_images(path)
    else:
        yield _cap_pixels(load_image(path))


def resize_max(img: Image.Image, max_dim: int = MAX_DIM) -> Image.Image:
    """Reduce la imagen si su lado mayor supera ``max_dim`` (mantiene proporción)."""
    if max(img.size) <= max_dim:
        return img
    ratio = max_dim / max(img.size)
    new_size = (max(1, int(img.width * ratio)), max(1, int(img.height * ratio)))
    return img.resize(new_size, Image.LANCZOS)


def to_png_base64(img: Image.Image, max_dim: int = MAX_DIM) -> str:
    """Imagen → PNG → base64 (formato que espera el endpoint de visión de Ollama)."""
    img = resize_max(img, max_dim)
    buf = BytesIO()
    img.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode("utf-8")
