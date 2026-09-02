# -*- coding: utf-8 -*-
"""Sonda de la familia de senales `tipografia_pdf`.

Familia: "Tipografia y estructura del PDF (texto anadido)".
Cubre la senal TIPOGRAFIA_MIXTA ("VARIOS TIPOS DE LETRAS EN EL DOCUMENTO") y,
en general, cualquier rastro estructural de que alguien abrio el PDF y le
anadio, tapo o reemplazo texto.

100% LOCAL Y DETERMINISTA: solo pypdfium2 (la misma libreria que usa el
pipeline de OCR del repo incapacidad-ocr) + lectura de bytes crudos del PDF.
Sin red, sin IA, sin servicios externos.

Uso:
    python probe.py                      # corre sobre todo el corpus del manifest
    python probe.py --json               # ademas volca resultado.json
    python probe.py --umbral-familias 3  # exige 3 familias para votar SOSPECHA
    python probe.py <ruta.pdf> ...       # analiza archivos concretos

PII (Ley 1581): la sonda NUNCA imprime el contenido de los documentos. Solo
geometria, nombres de fuente, metadatos del contenedor y conteos.
"""
from __future__ import annotations

import argparse
import csv
import ctypes
import json
import os
import re
import sys
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
MANIFEST = BASE + "/manifest.csv"
DOCS = BASE + "/docs"
AQUI = os.path.dirname(os.path.abspath(__file__))

# --------------------------------------------------------------------------- #
# Umbrales. Estan aqui arriba a proposito: son los parametros discutibles.
# --------------------------------------------------------------------------- #
UMBRAL_FAMILIAS_LEVE = 2     # >= 2 familias tipograficas distintas -> AVISO
UMBRAL_FAMILIAS_FUERTE = 3   # >= 3 familias distintas -> ALERTA
MIN_OBJ_PARA_MINORITARIA = 50   # con menos texto que esto no se juzga "minoria"
MAX_SHARE_MINORITARIA = 0.15    # familia con <= 15% de los objetos de texto
FRAC_IMG_ESCANEO = 0.70      # imagen que cubre >= 70% de la pagina = escaneo
FRAC_SOLAPE_TEXTO_IMG = 0.60  # texto contenido >= 60% dentro de esa imagen
MAX_TEXTO_ESTAMPADO = 40     # mas objetos que esto = documento nativo con fondo
PARCHE_MIN_FRAC = 0.0005     # parche blanco: entre 0.05% ...
PARCHE_MAX_FRAC = 0.20       # ... y 20% del area de la pagina
PARCHE_SOLAPE = 0.30         # el parche cubre >= 30% de su propia area de algo

# Productores/creadores que SINTETIZAN una capa de texto encima de un escaneo.
# En esos PDF las "fuentes" las invento el OCR: comparar familias no significa nada.
OCR_SINTETICO = re.compile(
    r"clearscan|paper\s*capture|tesseract|ocrmypdf|abbyy|finereader|readiris|"
    r"acrobat.*capture|scansnap|omnipage",
    re.IGNORECASE,
)
# pdfium bautiza asi las fuentes que ClearScan y similares fabrican por glifo:
FUENTE_SINTETICA = re.compile(r"^\*.+-\d{3,}$")
# Productores que ANONIMIZAN el nombre de la fuente (no se puede comparar familia):
FUENTE_ANONIMA = re.compile(r"^(CIDFont\+F\d+|F\d+|T\d+_\d+)$")
FAMILIA_ANONIMA = re.compile(r"\.(tmp|ttf|otf|ttc|pfb|pfa)$", re.IGNORECASE)

SUBSET_RE = re.compile(r"^[A-Z]{6}\+")
ESTILO_RE = re.compile(
    r"(PSMT|PS|MT|-BoldItalic|-BoldMT|-ItalicMT|-Bold|-Italic|-Oblique|-Regular|"
    r"-Light|-Medium|-Black|-Semibold|-Roman|,BoldItalic|,Bold|,Italic)+$",
    re.IGNORECASE,
)
INSTANCIA_RE = re.compile(r"-\d{3,}$")

RENDER_INVISIBLE = 3
TIPO_NOMBRE = {1: "texto", 2: "path", 3: "imagen", 4: "shading", 5: "form"}


# --------------------------------------------------------------------------- #
# Utilidades geometricas
# --------------------------------------------------------------------------- #
def area(b) -> float:
    return max(0.0, b[2] - b[0]) * max(0.0, b[3] - b[1])


def interseccion(a, b) -> float:
    w = min(a[2], b[2]) - max(a[0], b[0])
    h = min(a[3], b[3]) - max(a[1], b[1])
    return w * h if (w > 0 and h > 0) else 0.0


def fill_color(obj):
    c = [ctypes.c_uint() for _ in range(4)]
    if not raw.FPDFPageObj_GetFillColor(obj, *c):
        return None
    return tuple(x.value for x in c)


def familia_norm(base: str, familia: str) -> str:
    """Familia tipografica comparable: sin tag de subset ni sufijo de estilo.

    'ACWIYO+Arial-BoldMT' -> 'arial'          'Arial,Bold' -> 'arial'
    '*Times New Roman-12358' -> 'timesnewroman'
    Nota: pdfium resuelve Helvetica -> familia 'Arial' (sustituto metrico);
    eso es deseado, no queremos contar Helvetica y Arial como dos letras.
    """
    nombre = (familia or "").strip()
    if FAMILIA_ANONIMA.search(nombre):   # 'z@r2a13.tmp' de Print-To-PDF
        nombre = ""
    if not nombre:
        nombre = SUBSET_RE.sub("", base or "").lstrip("*")
        nombre = INSTANCIA_RE.sub("", nombre)
        nombre = ESTILO_RE.sub("", nombre)
    return re.sub(r"[\s_]+", "", nombre).lower() or "?"


def raiz_sin_subset(base: str) -> str:
    return SUBSET_RE.sub("", base or "")


def hull(bboxes):
    return [round(min(b[0] for b in bboxes), 1), round(min(b[1] for b in bboxes), 1),
            round(max(b[2] for b in bboxes), 1), round(max(b[3] for b in bboxes), 1)]


# --------------------------------------------------------------------------- #
# Lectura de rasgos (una sola pasada por PDF)
# --------------------------------------------------------------------------- #
def rasgos_bytes(ruta: str) -> dict:
    with open(ruta, "rb") as fh:
        crudo = fh.read()
    return {
        "eof": crudo.count(b"%%EOF"),
        "startxref": crudo.count(b"startxref"),
        "prev": len(re.findall(rb"/Prev\s+\d+", crudo)),
        "linearizado": b"/Linearized" in crudo,
    }


def leer_pdf(ruta: str) -> dict:
    r: dict = {"tipo": "pdf", **rasgos_bytes(ruta)}
    pdf = pdfium.PdfDocument(ruta)
    try:
        r["meta"] = {}
        for k in ("Creator", "Producer", "CreationDate", "ModDate", "Author"):
            try:
                r["meta"][k] = pdf.get_metadata_value(k) or ""
            except Exception:  # noqa: BLE001
                r["meta"][k] = ""
        fuentes = Counter()
        familias = Counter()
        familia_bboxes: dict[str, list] = {}
        detalle_fuente: dict[str, dict] = {}
        colores = Counter()
        alfas = Counter()
        n_texto = n_texto_vis = n_invisible = n_img = 0
        texto_sobre_escaneo = 0
        parches: list[dict] = []
        for i in range(len(pdf)):
            page = pdf[i]
            pw, ph = page.get_size()
            apag = (pw * ph) or 1.0
            try:
                tp = page.get_textpage()
            except Exception:  # noqa: BLE001
                tp = None
            # `pintados` respeta el orden del content stream = z-order de pintado.
            # Solo texto e imagen: un rectangulo blanco encima de OTRO rectangulo
            # blanco es el par relleno+borde de una figura de Word, no un parche.
            pintados: list[tuple[str, tuple]] = []
            textos_vis: list[dict] = []
            imgs_grandes: list[tuple] = []
            for obj in page.get_objects(textpage=tp):
                try:
                    b = tuple(obj.get_bounds())
                except Exception:  # noqa: BLE001
                    continue
                if obj.type == raw.FPDF_PAGEOBJ_TEXT:
                    n_texto += 1
                    try:
                        f = obj.get_font()
                        base = f.get_base_name() or "?"
                        fam_pdf = f.get_family_name() or ""
                        emb = bool(f.is_embedded)
                    except Exception:  # noqa: BLE001
                        base, fam_pdf, emb = "?", "", False
                    modo = raw.FPDFTextObj_GetTextRenderMode(obj)
                    nch = 0
                    if tp is not None:
                        try:
                            nch = len((obj.extract() or "").strip())
                        except Exception:  # noqa: BLE001
                            nch = 0
                    if modo == RENDER_INVISIBLE:
                        n_invisible += 1
                    # Solo cuentan los objetos que de verdad PINTAN caracteres:
                    # los de solo espacios no aportan "un tipo de letra visible".
                    if modo != RENDER_INVISIBLE and nch > 0:
                        n_texto_vis += 1
                        fam = familia_norm(base, fam_pdf)
                        fuentes[base] += 1
                        familias[fam] += 1
                        familia_bboxes.setdefault(fam, []).append(b)
                        detalle_fuente.setdefault(base, {
                            "familia_norm": fam,
                            "familia_pdf": fam_pdf,
                            "raiz": raiz_sin_subset(base),
                            "subset": bool(SUBSET_RE.match(base)),
                            "embebida": emb,
                            "sintetica": bool(FUENTE_SINTETICA.match(base)),
                            "anonima": bool(FUENTE_ANONIMA.match(base))
                            or bool(FAMILIA_ANONIMA.search(fam_pdf)),
                        })
                        c = fill_color(obj)
                        colores[str(c)] += 1
                        if c:
                            alfas[c[3]] += 1
                        textos_vis.append({"b": b, "base": base})
                        pintados.append(("texto", b))
                elif obj.type == raw.FPDF_PAGEOBJ_IMAGE:
                    n_img += 1
                    if area(b) / apag >= FRAC_IMG_ESCANEO:
                        imgs_grandes.append(b)
                    pintados.append(("imagen", b))
                elif obj.type == raw.FPDF_PAGEOBJ_PATH:
                    c = fill_color(obj)
                    frac = area(b) / apag
                    blanco_opaco = bool(c) and min(c[0], c[1], c[2]) > 240 and c[3] > 200
                    if blanco_opaco and PARCHE_MIN_FRAC < frac < PARCHE_MAX_FRAC:
                        tapa, que = 0.0, None
                        for tipo, bb in pintados:
                            s = interseccion(b, bb) / max(area(b), 1e-9)
                            if s > tapa:
                                tapa, que = s, tipo
                        if tapa >= PARCHE_SOLAPE:
                            parches.append({"pagina": i, "bbox": [round(v, 1) for v in b],
                                            "cubre": que, "fraccion_cubierta": round(tapa, 2)})
            for t in textos_vis:
                if any(interseccion(t["b"], im) / max(area(t["b"]), 1e-9) >= FRAC_SOLAPE_TEXTO_IMG
                       for im in imgs_grandes):
                    texto_sobre_escaneo += 1
        r.update({
            "n_paginas": len(pdf), "n_texto": n_texto, "n_texto_visible": n_texto_vis,
            "n_texto_invisible": n_invisible, "n_imagenes": n_img,
            "fuentes": dict(fuentes.most_common()), "familias": dict(familias.most_common()),
            "familia_zona": {f: hull(bb) for f, bb in familia_bboxes.items()},
            "detalle_fuente": detalle_fuente, "colores": dict(colores.most_common()),
            "alfas": {str(k): v for k, v in alfas.most_common()},
            "texto_sobre_escaneo": texto_sobre_escaneo, "parches_blancos": parches,
        })
    finally:
        pdf.close()
    return r


# --------------------------------------------------------------------------- #
# Checks
# --------------------------------------------------------------------------- #
def evaluar(rasgos: dict, ext: str, umbral_familias: int = UMBRAL_FAMILIAS_LEVE) -> dict:
    """Aplica los checks de la familia. Devuelve estado global + estado por check.

    Estados de check: SOSPECHA / SOSPECHA_LEVE / LIMPIO / NO_EVALUABLE /
    NO_APLICABLE, y los INFO_* de los checks que NO votan.
    """
    ch: dict[str, dict] = {}

    def poner(cid, estado, detalle=""):
        ch[cid] = {"estado": estado, "detalle": detalle}

    # ------------------- 0. contenedor ------------------- #
    if ext.lower() != "pdf":
        poner("TP_APLICABILIDAD", "NO_APLICABLE",
              f"contenedor '{ext}': una imagen suelta no tiene objetos de texto ni fuentes")
        return {"estado": "NO_APLICABLE", "motivo": f"no es PDF ({ext})",
                "checks": ch, "disparados": []}
    if rasgos.get("error"):
        poner("TP_APLICABILIDAD", "ERROR", rasgos["error"])
        return {"estado": "ERROR", "motivo": rasgos["error"], "checks": ch, "disparados": []}

    meta = rasgos["meta"]

    # --- checks INFORMATIVOS de contenedor: valen para TODO PDF, tambien escaneos --- #
    gen_extra = rasgos["eof"] > 1 or rasgos["prev"] >= 1
    poner("TP_GENERACIONES_MULTIPLES",
          "INFO_SOSPECHA" if (gen_extra and not rasgos["linearizado"]) else "INFO_LIMPIO",
          f"%%EOF={rasgos['eof']} /Prev={rasgos['prev']} linearizado={rasgos['linearizado']}")

    def marca(s):
        return re.sub(r"[^a-z]", "", s.lower())[:8]

    creator, producer = meta.get("Creator", ""), meta.get("Producer", "")
    cadena_distinta = bool(creator and producer and marca(creator) != marca(producer))
    remod = bool(meta.get("ModDate") and meta.get("CreationDate")
                 and meta["ModDate"][:16] != meta["CreationDate"][:16])
    poner("TP_CADENA_HERRAMIENTAS",
          "INFO_SOSPECHA" if (cadena_distinta or remod) else "INFO_LIMPIO",
          f"Creator!=Producer={cadena_distinta} ModDate!=CreationDate={remod}")

    # ------------------- 1. puertas de aplicabilidad de la tipografia ------------------- #
    n_vis = rasgos["n_texto_visible"]
    cadena = f"{creator} {producer}"
    sint = [b for b, d in rasgos["detalle_fuente"].items() if d["sintetica"]]
    ocr_sint = bool(OCR_SINTETICO.search(cadena)) or (
        bool(rasgos["detalle_fuente"]) and len(sint) >= 0.5 * len(rasgos["detalle_fuente"])
    )
    anon = [b for b, d in rasgos["detalle_fuente"].items() if d["anonima"]]

    if n_vis == 0:
        poner("TP_APLICABILIDAD", "NO_APLICABLE",
              f"ninguna pagina tiene capa de texto visible: escaneo/foto puro "
              f"({rasgos['n_imagenes']} imagenes, {rasgos['n_texto']} objetos de texto, "
              f"{rasgos['n_texto_invisible']} invisibles)")
        return {"estado": "NO_APLICABLE",
                "motivo": "escaneo puro: no hay fuentes que comparar",
                "checks": ch, "disparados": []}
    if ocr_sint:
        poner("TP_APLICABILIDAD", "NO_APLICABLE",
              f"la capa de texto la sintetizo un OCR ({len(sint)} fuentes fabricadas por glifo; "
              f"cadena='{cadena.strip()}'): las fuentes no son las del emisor")
        return {"estado": "NO_APLICABLE",
                "motivo": "capa de texto generada por OCR sobre un escaneo",
                "checks": ch, "disparados": []}

    fam = rasgos["familias"]
    total = max(n_vis, 1)
    poner("TP_APLICABILIDAD", "APLICABLE",
          f"{n_vis} objetos de texto visibles, {len(rasgos['fuentes'])} fuentes, "
          f"{len(fam)} familias")

    # ------------------- 2. checks que VOTAN ------------------- #
    # C1 numero de familias tipograficas distintas
    if anon:
        poner("TP_FAMILIAS_MULTIPLES", "NO_EVALUABLE",
              f"el productor anonimizo los nombres de fuente ({anon}); la identidad "
              "de la letra no es recuperable y contar familias no significa nada")
    elif len(fam) >= UMBRAL_FAMILIAS_FUERTE:
        poner("TP_FAMILIAS_MULTIPLES", "SOSPECHA",
              f"{len(fam)} familias tipograficas distintas: {fam}")
    elif len(fam) >= UMBRAL_FAMILIAS_LEVE:
        estado = "SOSPECHA" if umbral_familias <= UMBRAL_FAMILIAS_LEVE else "SOSPECHA_LEVE"
        poner("TP_FAMILIAS_MULTIPLES", estado,
              f"{len(fam)} familias tipograficas distintas: {fam} "
              f"zonas={rasgos['familia_zona']}")
    else:
        poner("TP_FAMILIAS_MULTIPLES", "LIMPIO", f"una sola familia: {fam}")

    # C2 familia minoritaria (el "parrafo escrito con otra letra")
    if anon:
        poner("TP_FUENTE_MINORITARIA", "NO_EVALUABLE", "nombres de fuente anonimizados")
    elif n_vis < MIN_OBJ_PARA_MINORITARIA:
        poner("TP_FUENTE_MINORITARIA", "NO_EVALUABLE",
              f"solo {n_vis} objetos de texto visibles: sin masa para hablar de minoria")
    else:
        minor = {f: n for f, n in fam.items() if n / total <= MAX_SHARE_MINORITARIA}
        if minor and len(fam) > 1:
            zonas = {k: rasgos["familia_zona"].get(k) for k in minor}
            poner("TP_FUENTE_MINORITARIA", "SOSPECHA",
                  f"familia(s) minoritaria(s) {minor} sobre {total} objetos de texto; "
                  f"zona ocupada (bbox pt) = {zonas}")
        else:
            poner("TP_FUENTE_MINORITARIA", "LIMPIO",
                  f"ninguna familia por debajo del {int(MAX_SHARE_MINORITARIA*100)}%: {fam}")

    # C3 opacidad no uniforme del texto
    alfas = rasgos["alfas"]
    if len(alfas) > 1:
        poner("TP_ALFA_TEXTO_NO_UNIFORME", "SOSPECHA",
              f"el texto se pinta con {len(alfas)} opacidades distintas {alfas}: un unico "
              "generador usa una sola; el texto semitransparente lo estampo otra herramienta")
    else:
        poner("TP_ALFA_TEXTO_NO_UNIFORME", "LIMPIO", f"opacidad uniforme {alfas}")

    # C4 texto vectorial estampado sobre un escaneo de pagina completa
    tse = rasgos["texto_sobre_escaneo"]
    if 1 <= tse <= MAX_TEXTO_ESTAMPADO:
        poner("TP_TEXTO_SOBRE_ESCANEO", "SOSPECHA",
              f"{tse} objetos de texto visibles estampados encima de una imagen que cubre "
              f">={int(FRAC_IMG_ESCANEO*100)}% de la pagina")
    elif tse > MAX_TEXTO_ESTAMPADO:
        poner("TP_TEXTO_SOBRE_ESCANEO", "LIMPIO",
              f"{tse} objetos sobre imagen de pagina completa: es un documento nativo con "
              "fondo/marca de agua, no unas palabras pegadas")
    else:
        poner("TP_TEXTO_SOBRE_ESCANEO", "LIMPIO",
              "ningun texto encima de una imagen de pagina completa")

    # C5 parche blanco opaco tapando contenido ya pintado
    par = rasgos["parches_blancos"]
    if par:
        poner("TP_PARCHE_BLANCO", "SOSPECHA",
              f"{len(par)} rectangulo(s) blanco(s) opaco(s) pintados encima de contenido "
              f"previo: {[(p['bbox'], p['cubre']) for p in par[:6]]}")
    else:
        poner("TP_PARCHE_BLANCO", "LIMPIO", "sin rectangulos blancos tapando contenido")

    # ------------------- 3. checks INFORMATIVOS de tipografia ------------------- #
    raices: dict[str, set] = {}
    for b, d in rasgos["detalle_fuente"].items():
        raices.setdefault(d["raiz"], set()).add(d["subset"])
    mixtas = [r_ for r_, s in raices.items() if len(s) > 1]
    poner("TP_SUBSET_MAS_COMPLETA", "INFO_SOSPECHA" if mixtas else "INFO_LIMPIO",
          f"raices con variante subset embebida y variante completa: {mixtas}"
          if mixtas else "sin mezcla subset/completa")

    votan = ("TP_FAMILIAS_MULTIPLES", "TP_FUENTE_MINORITARIA", "TP_ALFA_TEXTO_NO_UNIFORME",
             "TP_TEXTO_SOBRE_ESCANEO", "TP_PARCHE_BLANCO")
    disparados = [c for c in votan if ch[c]["estado"] == "SOSPECHA"]
    leves = [c for c in votan if ch[c]["estado"] == "SOSPECHA_LEVE"]
    if disparados:
        estado = "SOSPECHOSO"
    elif leves:
        estado = "SOSPECHA_LEVE"
    else:
        estado = "LIMPIO"
    return {"estado": estado,
            "motivo": "; ".join(disparados or leves) or "ningun check disparado",
            "checks": ch, "disparados": disparados, "leves": leves}


# --------------------------------------------------------------------------- #
# Corrida sobre el corpus
# --------------------------------------------------------------------------- #
def analizar(ruta: str, ext: str) -> dict:
    if ext.lower() != "pdf":
        return {"tipo": "imagen"}
    try:
        return leer_pdf(ruta)
    except Exception as e:  # noqa: BLE001
        return {"error": f"{type(e).__name__}: {e}", "meta": {}, "detalle_fuente": {}}


CHECKS_ORDEN = [
    "TP_APLICABILIDAD", "TP_FAMILIAS_MULTIPLES", "TP_FUENTE_MINORITARIA",
    "TP_ALFA_TEXTO_NO_UNIFORME", "TP_TEXTO_SOBRE_ESCANEO", "TP_PARCHE_BLANCO",
    "TP_SUBSET_MAS_COMPLETA", "TP_GENERACIONES_MULTIPLES", "TP_CADENA_HERRAMIENTAS",
]


def corpus(volcar_json: bool, umbral: int) -> int:
    filas = list(csv.DictReader(open(MANIFEST, encoding="utf-8")))
    res = []
    print(f"umbral de familias para votar SOSPECHA: >= {umbral}\n")
    print(f"{'ID':<4} {'ETIQUETA':<6} {'CUAR':<5} {'ESTADO':<14} {'ARCHIVO':<58} CHECKS DISPARADOS")
    print("-" * 175)
    for k, fila in enumerate(filas):
        carpeta = "falsas" if fila["etiqueta"] == "falsa" else "reales"
        ruta = os.path.join(DOCS, carpeta, fila["archivo"]).replace("\\", "/")
        ident = f"{'F' if fila['etiqueta'] == 'falsa' else 'R'}{k:02d}"
        if not os.path.exists(ruta):
            print(f"{ident:<4} {fila['etiqueta']:<6} {'':<5} {'ERROR':<14} "
                  f"{fila['archivo'][:58]:<58} archivo no encontrado en {ruta}")
            continue
        rasgos = analizar(ruta, fila["ext"])
        ver = evaluar(rasgos, fila["ext"], umbral)
        cuar = "SI" if fila["cuarentena"] == "si" else "-"
        print(f"{ident:<4} {fila['etiqueta']:<6} {cuar:<5} {ver['estado']:<14} "
              f"{fila['archivo'][:58]:<58} {ver['motivo']}")
        res.append({
            "id": ident, "archivo": fila["archivo"], "etiqueta": fila["etiqueta"],
            "cuarentena": fila["cuarentena"], "sha256": fila["sha256"],
            "estado": ver["estado"], "disparados": ver["disparados"],
            "leves": ver.get("leves", []), "checks": ver["checks"],
            "rasgos": {k2: v for k2, v in rasgos.items() if k2 in (
                "meta", "fuentes", "familias", "familia_zona", "n_texto",
                "n_texto_visible", "n_texto_invisible", "n_imagenes", "alfas",
                "colores", "texto_sobre_escaneo", "parches_blancos", "eof",
                "prev", "linearizado", "n_paginas")},
        })
    resumen(res, umbral)
    if volcar_json:
        salida = os.path.join(AQUI, "resultado.json").replace("\\", "/")
        with open(salida, "w", encoding="utf-8") as fh:
            json.dump(res, fh, ensure_ascii=False, indent=1)
        print(f"\ndetalle -> {salida}")
    return 0


def resumen(res: list[dict], umbral: int) -> None:
    fuera = [r for r in res if r["cuarentena"] == "si"]
    limpio = [r for r in res if r["cuarentena"] != "si"]
    f = [r for r in limpio if r["etiqueta"] == "falsa"]
    v = [r for r in limpio if r["etiqueta"] == "real"]
    det = lambda g: [r["id"] for r in g if r["estado"] == "SOSPECHOSO"]  # noqa: E731
    apl = lambda g: [r["id"] for r in g if r["estado"] != "NO_APLICABLE"]  # noqa: E731
    fd, vd, fa, va = det(f), det(v), apl(f), apl(v)
    print("\n" + "=" * 175)
    print(f"MEDICION  (umbral familias >= {umbral})")
    print(f"  EXCLUIDOS por CUARENTENA: {len(fuera)} documentos -> "
          f"{[(r['id'], r['estado']) for r in fuera]}")
    print(f"  FALSAS no-cuarentena: {len(f):>2}  |  aplicables: {len(fa):>2} {fa}  |  "
          f"DETECTADAS: {len(fd)} {fd}")
    print(f"  REALES no-cuarentena: {len(v):>2}  |  aplicables: {len(va):>2} {va}  |  "
          f"FALSOS POSITIVOS: {len(vd)} {vd}")
    if fa:
        print(f"  recall sobre falsas APLICABLES: {len(fd)}/{len(fa)} = {100*len(fd)/len(fa):.0f}%")
    print(f"  recall sobre TODAS las falsas:  {len(fd)}/{len(f)} = {100*len(fd)/max(len(f),1):.0f}%")
    tot = len(fd) + len(vd)
    if tot:
        print(f"  precision: {len(fd)}/{tot} = {100*len(fd)/tot:.0f}%   "
              f"(ojo: solo {len(va)} reales son aplicables, la precision NO esta medida de verdad)")
    print("\n  Detalle por check (no-cuarentena). Los 5 primeros VOTAN; los INFO_ no votan:")
    print(f"    {'CHECK':<28} {'falsas+':>7} {'reales+':>7}   falsas / reales")
    for cid in CHECKS_ORDEN[1:]:
        ff = [r["id"] for r in f if r["checks"].get(cid, {}).get("estado", "").endswith(
            ("SOSPECHA", "SOSPECHA_LEVE"))]
        rr = [r["id"] for r in v if r["checks"].get(cid, {}).get("estado", "").endswith(
            ("SOSPECHA", "SOSPECHA_LEVE"))]
        print(f"    {cid:<28} {len(ff):>7} {len(rr):>7}   {ff} / {rr}")
    print("\n  Aplicabilidad (por que la familia NO se puede juzgar en un documento):")
    motivos = (("contenedor no PDF (jpeg/png)", "contenedor '"),
               ("escaneo/foto puro sin capa de texto", "escaneo/foto puro"),
               ("capa de texto sintetizada por OCR", "la sintetizo un OCR"))
    for et, grupo in (("falsa", f), ("real", v)):
        for etiqueta_motivo, marca_txt in motivos:
            ids = [r["id"] for r in grupo if r["estado"] == "NO_APLICABLE"
                   and marca_txt in r["checks"].get("TP_APLICABILIDAD", {}).get("detalle", "")]
            if ids:
                print(f"    {et:<6} NO_APLICABLE - {etiqueta_motivo}: {len(ids)} {ids}")
    print("=" * 175)


def main() -> int:
    ap = argparse.ArgumentParser(description="Sonda de la familia tipografia_pdf")
    ap.add_argument("archivos", nargs="*", help="PDFs concretos (por defecto: corpus del manifest)")
    ap.add_argument("--json", action="store_true", help="volcar resultado.json")
    ap.add_argument("--umbral-familias", type=int, default=UMBRAL_FAMILIAS_LEVE,
                    help="familias distintas necesarias para votar SOSPECHA (2 o 3)")
    a = ap.parse_args()
    if not a.archivos:
        return corpus(a.json, a.umbral_familias)
    for ruta in a.archivos:
        ext = os.path.splitext(ruta)[1].lstrip(".")
        ver = evaluar(analizar(ruta, ext), ext, a.umbral_familias)
        print(f"\n{os.path.basename(ruta)}: {ver['estado']} :: {ver['motivo']}")
        for cid in CHECKS_ORDEN:
            c = ver["checks"].get(cid)
            if c:
                print(f"   {cid:<28} {c['estado']:<14} {c['detalle']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
