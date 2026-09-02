# -*- coding: utf-8 -*-
"""Exploracion 2: superposiciones (texto-texto, path blanco sobre texto),
colores de relleno del texto y geometria imagen-vs-texto.

Solo lee. No imprime contenido de los documentos (solo conteos y geometria).
"""
from __future__ import annotations

import csv
import json
import os

import pypdfium2 as pdfium
import pypdfium2.raw as raw
import ctypes

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


def area(b):
    return max(0.0, b[2] - b[0]) * max(0.0, b[3] - b[1])


def inter(a, b):
    w = min(a[2], b[2]) - max(a[0], b[0])
    h = min(a[3], b[3]) - max(a[1], b[1])
    return w * h if (w > 0 and h > 0) else 0.0


def fill_color(obj):
    r_, g_, b_, a_ = (ctypes.c_uint(), ctypes.c_uint(), ctypes.c_uint(), ctypes.c_uint())
    ok = raw.FPDFPageObj_GetFillColor(obj, r_, g_, b_, a_)
    if not ok:
        return None
    return (r_.value, g_.value, b_.value, a_.value)


def analiza(ruta):
    pdf = pdfium.PdfDocument(ruta)
    out = {"paginas": []}
    try:
        for i in range(len(pdf)):
            page = pdf[i]
            pw, ph = page.get_size()
            apag = pw * ph or 1.0
            try:
                tp = page.get_textpage()
            except Exception:
                tp = None
            textos, imgs, paths = [], [], []
            for obj in page.get_objects(textpage=tp):
                try:
                    b = obj.get_bounds()
                except Exception:
                    continue
                if obj.type == raw.FPDF_PAGEOBJ_TEXT:
                    n = 0
                    if tp is not None:
                        try:
                            n = len((obj.extract() or "").strip())
                        except Exception:
                            n = 0
                    textos.append({"b": b, "c": fill_color(obj), "n": n,
                                   "m": raw.FPDFTextObj_GetTextRenderMode(obj)})
                elif obj.type == raw.FPDF_PAGEOBJ_IMAGE:
                    imgs.append({"b": b, "frac": area(b) / apag})
                elif obj.type == raw.FPDF_PAGEOBJ_PATH:
                    paths.append({"b": b, "c": fill_color(obj), "frac": area(b) / apag})
            # texto-texto solapado (>=40% del menor)
            solapes_tt = 0
            vis = [t for t in textos if t["m"] != 3 and t["n"] > 0]
            for x in range(len(vis)):
                for y in range(x + 1, len(vis)):
                    ai, aj = area(vis[x]["b"]), area(vis[y]["b"])
                    if min(ai, aj) <= 0:
                        continue
                    if inter(vis[x]["b"], vis[y]["b"]) / min(ai, aj) >= 0.40:
                        solapes_tt += 1
            # paths blancos/opacos que tapan texto
            tapones = 0
            for p in paths:
                c = p["c"]
                if not c:
                    continue
                blanco = c[0] > 240 and c[1] > 240 and c[2] > 240 and c[3] > 200
                if blanco and 0.0005 < p["frac"] < 0.5:
                    tapones += 1
            colores = {}
            for t in vis:
                colores[str(t["c"])] = colores.get(str(t["c"]), 0) + 1
            grandes = [im for im in imgs if im["frac"] >= 0.70]
            sobre_grande = sum(
                1 for t in vis
                if any(inter(t["b"], im["b"]) / max(area(t["b"]), 1e-9) >= 0.6 for im in grandes)
            )
            out["paginas"].append({
                "i": i, "n_texto": len(textos), "n_vis": len(vis), "n_img": len(imgs),
                "n_path": len(paths), "solapes_texto_texto": solapes_tt,
                "paths_blancos": tapones, "colores_texto": colores,
                "img_fracs": [round(im["frac"], 3) for im in imgs],
                "n_img_grandes": len(grandes), "texto_sobre_img_grande": sobre_grande,
                "bbox_txt": [[round(v, 1) for v in t["b"]] for t in vis][:6] if len(vis) <= 6 else None,
            })
    finally:
        pdf.close()
    return out


def main():
    filas = list(csv.DictReader(open(BASE + "/manifest.csv", encoding="utf-8")))
    for k, fila in enumerate(filas):
        if fila["ext"].lower() != "pdf":
            print(f"{k:<3} {fila['etiqueta'][:5]:5} IMAGEN")
            continue
        carpeta = "falsas" if fila["etiqueta"] == "falsa" else "reales"
        ruta = os.path.join(DOCS, carpeta, fila["archivo"]).replace("\\", "/")
        try:
            r = analiza(ruta)
        except Exception as e:
            print(k, "ERROR", e)
            continue
        q = "Q" if fila["cuarentena"] == "si" else "."
        for p in r["paginas"]:
            print(f"{k:<3} {fila['etiqueta'][:5]:5} {q} pg{p['i']} txt={p['n_texto']:<4} vis={p['n_vis']:<4} "
                  f"img={p['n_img']:<3} imgG={p['n_img_grandes']} sobreG={p['texto_sobre_img_grande']:<4} "
                  f"path={p['n_path']:<4} blancos={p['paths_blancos']:<3} solTT={p['solapes_texto_texto']:<4} "
                  f"cols={len(p['colores_texto'])} {p['colores_texto'] if len(p['colores_texto'])<=4 else ''} "
                  f"fracs={sorted(p['img_fracs'], reverse=True)[:4]}")


if __name__ == "__main__":
    main()
