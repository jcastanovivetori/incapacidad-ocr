"""Carga y normalización de imágenes (y PDFs) para los backends de OCR."""
from __future__ import annotations

import base64
import os
from io import BytesIO
from pathlib import Path

from PIL import Image

MAX_DIM = 1600
PDF_RENDER_SCALE = 3.0  # ~216 DPI: buen balance nitidez/tamaño para OCR de formularios
# Tope de páginas a procesar de un PDF (anti-DoS: PDFs de miles de páginas).
MAX_PDF_PAGES = int(os.environ.get("MAX_PDF_PAGES", 20))
# Anti "bomba de descompresión": Pillow lanza DecompressionBombError por encima de
# ~2x este valor. 64 MP cubre escaneos grandes sin permitir imágenes maliciosas enormes.
Image.MAX_IMAGE_PIXELS = 64_000_000


def load_image(path: str | Path) -> Image.Image:
    """Abre la imagen y la deja en un modo manejable (RGB/L)."""
    img = Image.open(path)
    if img.mode not in ("RGB", "L"):
        img = img.convert("RGB")
    return img


def pdf_to_images(path: str | Path, scale: float = PDF_RENDER_SCALE) -> list[Image.Image]:
    """Renderiza cada página de un PDF a una imagen PIL (local, vía pypdfium2/PDFium).

    Procesa como máximo ``MAX_PDF_PAGES`` páginas (anti-DoS).
    """
    import pypdfium2 as pdfium  # import perezoso (dependencia opcional)

    pdf = pdfium.PdfDocument(str(path))
    try:
        n = min(len(pdf), MAX_PDF_PAGES)
        return [pdf[i].render(scale=scale).to_pil() for i in range(n)]
    finally:
        pdf.close()


def load_pages(path: str | Path) -> list[Image.Image]:
    """Carga un documento como lista de imágenes: PDF → una por página; imagen → [imagen]."""
    if str(path).lower().endswith(".pdf"):
        return pdf_to_images(path)
    return [load_image(path)]


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
