# -*- coding: utf-8 -*-
"""Exploracion (temporal) de rasgos tipograficos/estructurales del corpus.

Solo lee. Volca un JSON con los rasgos crudos por documento para poder mirar la
distribucion falsas-vs-reales ANTES de fijar los umbrales de los checks.
"""
from __future__ import annotations

import csv
import ctypes
import json
import os
import re
from collections import Counter

import pypdfium2 as pdfium
import pypdfium2.raw as raw

# --- Rutas relativas (añadidas por scripts/exportar_analisis.py) --------------------------
# Este script se escribió con rutas ABSOLUTAS de la máquina donde se investigó. Se resuelven
# desde la ubicación del propio archivo para que funcione tras un `git pull` en cualquier
# equipo. El corpus (`dataset-falsedad/`) NO está en el repositorio: lo aporta el cliente.
import pathlib as _pl
_REPO = _pl.Path(__file__).resolve().parents[3]
_DATASET = _REPO.parent / "dataset-falsedad"
_EJEMPLOS = _REPO.parent / "Ejemplos"
# ------------------------------------------------------------------------------------------

BASE = str(_DATASET)
DOCS = BASE + "/docs"
OUT = BASE + "/senales/tipografia_pdf/_rasgos.json"

SUBSET_RE = re.compile(r"^[A-Z]{6}\+")
ESTILO_RE = re.compile(
    r"(PS|MT|PSMT|-?Bold|-?Italic|-?Oblique|-?Regular|-?Light|-?Medium|-?Black|-?Semibold"
    r"|-?BoldItalic|-?BoldMT|-?ItalicMT|,Bold|,Italic|,BoldItalic)+$",
    re.IGNORECASE,
)

RENDER = {
    0: "FILL", 1: "STROKE", 2: "FILL_STROKE", 3: "INVISIBLE",
    4: "FILL_CLIP", 5: "STROKE_CLIP", 6: "FILL_STROKE_CLIP", 7: "CLIP", -1: "UNKNOWN",
}


def familia_normalizada(base: str, familia: str) -> str:
    """Nombre de familia comparable: sin tag de subset ni sufijos de estilo."""
    nombre = (familia or "").strip()
    if not nombre:
        nombre = SUBSET_RE.sub("", base or "")
        nombre = ESTILO_RE.sub("", nombre)
    return nombre.replace(" ", "").lower() or "?"


def raiz_sin_subset(base: str) -> str:
    return SUBSET_RE.sub("", base or "")


def rasgos_bytes(ruta: str) -> dict:
    with open(ruta, "rb") as fh:
        crudo = fh.read()
    return {
        "eof": crudo.count(b"%%EOF"),
        "startxref": crudo.count(b"startxref"),
        "prev": len(re.findall(rb"/Prev\s+\d+", crudo)),
        "linearized": b"/Linearized" in crudo,
        "objstm": b"/ObjStm" in crudo,
        "incremental_obj": len(re.findall(rb"\n\d+\s+[1-9]\d*\s+obj", crudo)),
    }


def area(b) -> float:
    return max(0.0, b[2] - b[0]) * max(0.0, b[3] - b[1])


def solapa(t, i) -> float:
    """Fraccion del bbox de texto t contenida en el bbox de imagen i."""
    ancho = min(t[2], i[2]) - max(t[0], i[0])
    alto = min(t[3], i[3]) - max(t[1], i[1])
    if ancho <= 0 or alto <= 0:
        return 0.0
    at = area(t)
    return (ancho * alto) / at if at > 0 else 0.0


def analiza_pdf(ruta: str) -> dict:
    r = {"tipo": "pdf", **rasgos_bytes(ruta)}
    pdf = pdfium.PdfDocument(ruta)
    try:
        meta = {}
        for k in ("Creator", "Producer", "CreationDate", "ModDate", "Author", "Title"):
            try:
                meta[k] = pdf.get_metadata_value(k) or ""
            except Exception:
                meta[k] = ""
        r["meta"] = meta
        fuentes = Counter()          # base -> n objetos
        detalle = {}                 # base -> dict
        familias = Counter()         # familia normalizada -> n objetos
        tamanos = Counter()
        modos = Counter()
        n_texto = n_img = 0
        chars = 0
        sobre_img = []               # objetos de texto visibles encima de imagen grande
        area_img_max_frac = 0.0
        paginas = []
        for i in range(len(pdf)):
            page = pdf[i]
            pw, ph = page.get_size()
            apag = pw * ph
            try:
                tp = page.get_textpage()
            except Exception:
                tp = None
            imgs = []
            textos = []
            for obj in page.get_objects(textpage=tp):
                try:
                    b = obj.get_bounds()
                except Exception:
                    b = (0, 0, 0, 0)
                if obj.type == raw.FPDF_PAGEOBJ_IMAGE:
                    n_img += 1
                    imgs.append(b)
                    area_img_max_frac = max(area_img_max_frac, area(b) / apag if apag else 0)
                elif obj.type == raw.FPDF_PAGEOBJ_TEXT:
                    n_texto += 1
                    f = obj.get_font()
                    base = f.get_base_name() or "?"
                    fam = f.get_family_name() or ""
                    emb = bool(f.is_embedded)
                    peso = f.get_weight()
                    fuentes[base] += 1
                    detalle.setdefault(base, {
                        "familia": fam, "embebida": emb, "peso": peso,
                        "subset": bool(SUBSET_RE.match(base)),
                        "raiz": raiz_sin_subset(base),
                        "familia_norm": familia_normalizada(base, fam),
                    })
                    familias[familia_normalizada(base, fam)] += 1
                    tam = round(raw.FPDFTextObj_GetFontSize(obj) if False else obj.get_font_size(), 2)
                    tamanos[tam] += 1
                    modo = raw.FPDFTextObj_GetTextRenderMode(obj)
                    modos[RENDER.get(modo, str(modo))] += 1
                    txt = ""
                    if tp is not None:
                        try:
                            txt = obj.extract() or ""
                        except Exception:
                            txt = ""
                    chars += len(txt)
                    textos.append({"base": base, "bbox": b, "modo": modo,
                                   "tam": tam, "nchars": len(txt.strip())})
            grandes = [im for im in imgs if apag and area(im) / apag >= 0.30]
            for t in textos:
                if t["modo"] == 3 or t["nchars"] == 0:
                    continue
                if any(solapa(t["bbox"], im) >= 0.60 for im in grandes):
                    sobre_img.append({"pagina": i, "base": t["base"], "tam": t["tam"],
                                      "nchars": t["nchars"]})
            paginas.append({"i": i, "n_texto": len(textos), "n_img": len(imgs),
                            "fuentes_pag": sorted({t["base"] for t in textos})})
        r["fuentes"] = dict(fuentes.most_common())
        r["detalle"] = detalle
        r["familias"] = dict(familias.most_common())
        r["tamanos"] = {str(k): v for k, v in sorted(tamanos.items())}
        r["modos"] = dict(modos)
        r["n_texto"] = n_texto
        r["n_img"] = n_img
        r["chars"] = chars
        r["n_paginas"] = len(pdf)
        r["paginas"] = paginas
        r["texto_sobre_imagen"] = sobre_img
        r["area_img_max_frac"] = round(area_img_max_frac, 3)
    finally:
        pdf.close()
    return r


def main() -> None:
    filas = list(csv.DictReader(open(BASE + "/manifest.csv", encoding="utf-8")))
    salida = []
    for fila in filas:
        carpeta = "falsas" if fila["etiqueta"] == "falsa" else "reales"
        ruta = os.path.join(DOCS, carpeta, fila["archivo"]).replace("\\", "/")
        reg = {"archivo": fila["archivo"], "etiqueta": fila["etiqueta"],
               "cuarentena": fila["cuarentena"], "sha8": fila["sha256"][:8]}
        if not os.path.exists(ruta):
            reg["error"] = "no existe"
        elif fila["ext"].lower() in ("jpeg", "jpg", "png"):
            reg.update({"tipo": "imagen", "n_texto": 0})
        else:
            try:
                reg.update(analiza_pdf(ruta))
            except Exception as e:
                reg["error"] = f"{type(e).__name__}: {e}"
        salida.append(reg)
    with open(OUT, "w", encoding="utf-8") as fh:
        json.dump(salida, fh, ensure_ascii=False, indent=1)
    print("escrito", OUT, len(salida), "docs")


if __name__ == "__main__":
    main()
