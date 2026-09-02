# -*- coding: utf-8 -*-
"""Exploracion 3: perfil objeto-por-objeto de documentos concretos.

Imprime SOLO geometria, fuente, color, alfa y longitud de texto (nunca el texto).
"""
from __future__ import annotations

import ctypes
import sys

import pypdfium2 as pdfium
import pypdfium2.raw as raw


def fill_color(obj):
    a = [ctypes.c_uint() for _ in range(4)]
    if not raw.FPDFPageObj_GetFillColor(obj, *a):
        return None
    return tuple(x.value for x in a)


def main(ruta):
    pdf = pdfium.PdfDocument(ruta)
    for i in range(len(pdf)):
        page = pdf[i]
        tp = page.get_textpage()
        print(f"--- pagina {i} tam={page.get_size()}")
        for k, obj in enumerate(page.get_objects(textpage=tp)):
            b = tuple(round(v, 1) for v in obj.get_bounds())
            if obj.type == raw.FPDF_PAGEOBJ_TEXT:
                f = obj.get_font()
                n = len((obj.extract() or "").strip())
                c = fill_color(obj)
                m = raw.FPDFTextObj_GetTextRenderMode(obj)
                if (c and c[3] != 255) or (f.get_base_name() or "").find("+") >= 0:
                    print(f"  [{k:3}] TEXTO* {f.get_base_name():28} tam={obj.get_font_size():5.2f} "
                          f"emb={int(bool(f.is_embedded))} color={c} modo={m} nchars={n} bbox={b}")
            elif obj.type == raw.FPDF_PAGEOBJ_PATH:
                c = fill_color(obj)
                if c and c[0] > 240 and c[1] > 240 and c[2] > 240:
                    print(f"  [{k:3}] PATH-BLANCO color={c} bbox={b}")
    pdf.close()


if __name__ == "__main__":
    main(sys.argv[1])
