"""Convierte GUIA_RECEPCION_INCAPACIDADES.md en un PDF legible (para compartir).

Conversor Markdown→PDF acotado a lo que usa la guía (títulos, párrafos, listas, tablas,
bloques de código, citas). Usa fpdf2 + una fuente TTF Unicode (Arial en Windows, DejaVu en
Linux) para soportar tildes/ñ. Requiere ``pip install fpdf2``. Ejecutar en el HOST:

    python scripts/guia_a_pdf.py
"""
from __future__ import annotations

import re
from pathlib import Path

from fpdf import FPDF

REPO = Path(__file__).resolve().parent.parent
MD = REPO / "GUIA_RECEPCION_INCAPACIDADES.md"
PDF = REPO / "GUIA_RECEPCION_INCAPACIDADES.pdf"

_FONTS = {
    "": [r"C:/Windows/Fonts/arial.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"],
    "B": [r"C:/Windows/Fonts/arialbd.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"],
    "I": [r"C:/Windows/Fonts/ariali.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Oblique.ttf"],
    "BI": [r"C:/Windows/Fonts/arialbi.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans-BoldOblique.ttf"],
}
FAM = "Doc"
# Emoji que las fuentes de texto no traen → equivalentes en texto.
_REPL = {"✅": "[OK]", "❌": "[NO]", "☑": "[OK]", "✓": "OK"}


def _clean(s: str) -> str:
    for k, v in _REPL.items():
        s = s.replace(k, v)
    return s


def _plain(s: str) -> str:
    """Quita marcadores markdown (**, `) para celdas de tabla."""
    return _clean(re.sub(r"[`*]", "", s))


def _md(s: str) -> str:
    """Convierte `code` → **negrita** para que resalte con markdown=True; limpia emoji."""
    return _clean(re.sub(r"`([^`]+)`", r"**\1**", s))


def _add_fonts(pdf: FPDF) -> None:
    for style, rutas in _FONTS.items():
        for r in rutas:
            if Path(r).exists():
                pdf.add_font(FAM, style, r)
                break


def build() -> None:
    lines = MD.read_text(encoding="utf-8").splitlines()
    pdf = FPDF(format="A4")
    pdf.set_auto_page_break(True, margin=15)
    pdf.set_margins(18, 16, 18)
    pdf.add_page()
    _add_fonts(pdf)
    pdf.set_font(FAM, "", 11)
    epw = pdf.w - pdf.l_margin - pdf.r_margin

    i, n = 0, len(lines)
    while i < n:
        ln = lines[i]
        s = ln.rstrip()

        if not s.strip():
            pdf.ln(3); i += 1; continue

        # Regla horizontal
        if re.fullmatch(r"-{3,}", s.strip()):
            y = pdf.get_y() + 1; pdf.set_draw_color(200); pdf.line(pdf.l_margin, y, pdf.w - pdf.r_margin, y)
            pdf.ln(4); i += 1; continue

        # Títulos
        m = re.match(r"^(#{1,4})\s+(.*)$", s)
        if m:
            nivel = len(m.group(1)); tam = {1: 18, 2: 14, 3: 12, 4: 11}[nivel]
            pdf.ln(3 if nivel > 1 else 1)
            pdf.set_font(FAM, "B", tam)
            pdf.multi_cell(epw, tam * 0.5 + 3, _clean(m.group(2)), markdown=True)
            pdf.set_font(FAM, "", 11); pdf.ln(1); i += 1; continue

        # Bloque de código ```
        if s.strip().startswith("```"):
            i += 1; buf = []
            while i < n and not lines[i].strip().startswith("```"):
                buf.append(_clean(lines[i])); i += 1
            i += 1
            pdf.set_font(FAM, "", 9.5); pdf.set_fill_color(244, 246, 249)
            pdf.multi_cell(epw, 5, "\n".join(buf) or " ", fill=True, border=0)
            pdf.set_font(FAM, "", 11); pdf.ln(2); continue

        # Tabla
        if s.lstrip().startswith("|") and i + 1 < n and re.search(r"\|?\s*:?-{2,}", lines[i + 1]):
            filas = []
            while i < n and lines[i].lstrip().startswith("|"):
                celdas = [c.strip() for c in lines[i].strip().strip("|").split("|")]
                if not re.match(r"^\s*:?-{2,}", celdas[0]):  # salta el separador |---|
                    filas.append([_plain(c) for c in celdas])
                i += 1
            if filas:
                pdf.set_font(FAM, "", 9.5)
                with pdf.table(borders_layout="SINGLE_TOP_LINE", line_height=5.5,
                               headings_style=__import__("fpdf").fonts.FontFace(emphasis="BOLD")) as table:
                    for fila in filas:
                        r = table.row()
                        for c in fila:
                            r.cell(c)
                pdf.set_font(FAM, "", 11); pdf.ln(2)
            continue

        # Cita (> ...)
        if s.lstrip().startswith(">"):
            txt = _md(re.sub(r"^\s*>\s?", "", s))
            pdf.set_fill_color(238, 242, 255); pdf.set_font(FAM, "I", 10.5)
            pdf.multi_cell(epw, 5.5, txt, fill=True, markdown=True)
            pdf.set_font(FAM, "", 11); pdf.ln(2); i += 1; continue

        # Lista con viñetas
        if re.match(r"^\s*[-*]\s+", s):
            item = _md(re.sub(r"^\s*[-*]\s+", "", s))
            x = pdf.get_x()
            pdf.multi_cell(epw, 5.5, "•  " + item, markdown=True)
            pdf.set_x(x); i += 1; continue

        # Párrafo normal
        pdf.multi_cell(epw, 5.5, _md(s), markdown=True)
        pdf.ln(1); i += 1

    pdf.output(str(PDF))
    print("PDF generado:", PDF)


if __name__ == "__main__":
    build()
