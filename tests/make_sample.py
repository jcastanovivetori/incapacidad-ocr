"""Genera una imagen sintética de incapacidad médica para las pruebas."""
from __future__ import annotations

import os
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

# Texto canónico que se "imprime" en la imagen (ASCII para OCR estable).
LINES = [
    "EPS SURA",
    "CERTIFICADO DE INCAPACIDAD MEDICA",
    "",
    "Paciente: JUAN PEREZ GOMEZ",
    "Documento: CC 1098765432",
    "IPS: CLINICA LAS AMERICAS",
    "",
    "Fecha de expedicion: 2026-06-10",
    "Incapacidad desde: 2026-06-10 hasta: 2026-06-14",
    "Dias de incapacidad: 5",
    "",
    "Diagnostico: J06.9 Infeccion aguda de vias respiratorias superiores",
    "Tipo: Enfermedad general",
    "Origen: Comun",
    "",
    "Medico: ANA TORRES   Registro: 12345",
]
CANONICAL_TEXT = "\n".join(LINES)

EXPECTED = {
    "paciente_nombre": "JUAN PEREZ GOMEZ",
    "documento_tipo": "CC",
    "documento_numero": "1098765432",
    "fecha_expedicion": "2026-06-10",
    "fecha_inicio": "2026-06-10",
    "fecha_fin": "2026-06-14",
    "dias": 5,
    "cie10": "J06.9",
    "tipo": "Enfermedad general",
}


def _font(size: int = 30) -> ImageFont.ImageFont:
    win_fonts = os.path.join(os.environ.get("WINDIR", "C:\\Windows"), "Fonts")
    for name in ("arial.ttf", "calibri.ttf", "segoeui.ttf", "tahoma.ttf", "verdana.ttf",
                 "DejaVuSans.ttf"):
        for candidate in (name, os.path.join(win_fonts, name)):
            try:
                return ImageFont.truetype(candidate, size)
            except OSError:
                continue
    return ImageFont.load_default()


def make_sample(path: str | Path = None) -> Path:
    if path is None:
        path = Path(__file__).resolve().parent / "sample_incapacidad.png"
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    img = Image.new("RGB", (1100, 770), "white")
    draw = ImageDraw.Draw(img)
    font = _font(30)
    y = 40
    for line in LINES:
        if line:
            draw.text((50, y), line, fill="black", font=font)
        y += 45
    img.save(path)
    return path


if __name__ == "__main__":
    print("imagen generada:", make_sample())
