"""Shard 1/4 - OCR + extraccion + señales estructurales del corpus de falsedad.

100% LOCAL: RapidOCR (ONNX/CPU) + pypdfium2 + Pillow. Ningun servicio remoto.

Selecciona los documentos del manifest ordenados por (etiqueta, archivo) cuyo indice
global i cumple i % 4 == 1, y por cada uno escribe:

    dataset-falsedad/ocr/<carpeta_etiqueta>/<stem>.json
    dataset-falsedad/ocr/<carpeta_etiqueta>/<stem>.txt   (solo el texto plano del OCR)

El JSON lleva el texto OCR, el registro estructurado del extractor de reglas y las
señales estructurales (materia prima de las familias TIPOGRAFIA_MIXTA y FIRMA_MEDICO).

Uso:
    <repo>/.venv/Scripts/python.exe \
        <dataset-falsedad>/senales/_extraer_shard1.py
"""
from __future__ import annotations

import csv
import hashlib
import json
import sys
import time
import traceback
from pathlib import Path

# --- Rutas relativas (añadidas por scripts/exportar_analisis.py) --------------------------
# Este script se escribió con rutas ABSOLUTAS de la máquina donde se investigó. Se resuelven
# desde la ubicación del propio archivo para que funcione tras un `git pull` en cualquier
# equipo. El corpus (`dataset-falsedad/`) NO está en el repositorio: lo aporta el cliente.
import pathlib as _pl
_REPO = _pl.Path(__file__).resolve().parents[2]
_DATASET = _REPO.parent / "dataset-falsedad"
_EJEMPLOS = _REPO.parent / "Ejemplos"
# ------------------------------------------------------------------------------------------

REPO = str(_REPO)
sys.path.insert(0, REPO)

BASE = Path(str(_DATASET))
MANIFEST = BASE / "manifest.csv"
DOCS = BASE / "docs"
OUT = BASE / "ocr"
SHARD, NSHARDS = 1, 4

# El arbol de salida espeja docs/ (falsas|reales), no el valor crudo de la columna.
CARPETA = {"falsa": "falsas", "real": "reales"}
# Tope de pixeles para hashear una imagen embebida ya decodificada (protege RAM).
CAP_PX_HASH = 4_000_000
# Tope de objetos de texto detallados por pagina (el resumen agregado no se limita).
CAP_DETALLE_TEXTO = 3000


# --------------------------------------------------------------------------- utils
def sha256_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def _s(v):
    """Normaliza a str/None sin inventar nada (pdfium puede devolver bytes)."""
    if v is None:
        return None
    if isinstance(v, bytes):
        return v.decode("utf-8", errors="replace")
    return str(v)


def _attr(obj, nombre, errores: list):
    """Lee ``obj.nombre`` sea metodo o propiedad; devuelve None si no existe.

    La API de pypdfium2 varia entre versiones (p.ej. ``PdfFont.is_embedded`` es
    propiedad, no metodo): probamos ambas formas y NO inventamos valores.
    """
    try:
        v = getattr(obj, nombre)
    except Exception as e:  # noqa: BLE001
        errores.append(f"{nombre}: {e!r}")
        return None
    if callable(v):
        try:
            return v()
        except Exception as e:  # noqa: BLE001
            errores.append(f"{nombre}(): {e!r}")
            return None
    return v


# ------------------------------------------------------------ señales estructurales
def eof_markers(path: Path) -> dict:
    """Heuristica barata de 'incremental updates' sobre los bytes crudos del PDF."""
    data = path.read_bytes()
    return {
        "eof_markers": data.count(b"%%EOF"),
        "startxref": data.count(b"startxref"),
        "prev_en_trailer": data.count(b"/Prev"),
        "objstm": data.count(b"/ObjStm"),
        # >1 %%EOF => el archivo fue guardado en varias generaciones (edicion posterior)
        "generaciones_estimadas": max(1, data.count(b"%%EOF")),
        "tiene_actualizacion_incremental": data.count(b"%%EOF") > 1,
        "bytes": len(data),
        "sha256_archivo": sha256_bytes(data),
        "cabecera": data[:9].decode("latin-1", errors="replace"),
    }


def firma_imagen(img, idx: int, nivel: int) -> dict:
    """sha256 del stream crudo y de los pixeles decodificados de una imagen embebida."""
    d: dict = {"indice": idx, "nivel": nivel, "tipo": "imagen"}
    try:
        d["px_size"] = list(img.get_px_size())
    except Exception as e:  # noqa: BLE001
        d["px_size"] = None
        d["error_px_size"] = repr(e)
    try:
        d["filtros"] = [_s(f) for f in img.get_filters()]
    except Exception as e:  # noqa: BLE001
        d["filtros"] = None
        d["error_filtros"] = repr(e)
    try:
        d["bounds"] = [round(x, 2) for x in img.get_bounds()]
    except Exception as e:  # noqa: BLE001
        d["bounds"] = None
        d["error_bounds"] = repr(e)
    try:
        meta = img.get_metadata()
        d["metadata"] = {
            "width": meta.width, "height": meta.height,
            "horizontal_dpi": meta.horizontal_dpi, "vertical_dpi": meta.vertical_dpi,
            "bits_per_pixel": meta.bits_per_pixel, "colorspace": meta.colorspace,
            "marked_content_id": meta.marked_content_id,
        }
    except Exception as e:  # noqa: BLE001
        d["metadata"] = None
        d["error_metadata"] = repr(e)
    try:
        raw = img.get_data(decode_simple=False)
        d["bytes_stream"] = len(raw)
        d["sha256_stream"] = sha256_bytes(bytes(raw))
    except Exception as e:  # noqa: BLE001
        d["bytes_stream"] = None
        d["sha256_stream"] = None
        d["error_stream"] = repr(e)
    px = d.get("px_size")
    if px and px[0] * px[1] <= CAP_PX_HASH:
        try:
            pil = img.get_bitmap(render=False).to_pil()
            d["sha256_pixeles"] = sha256_bytes(pil.tobytes())
            d["modo_pixeles"] = pil.mode
        except Exception as e:  # noqa: BLE001
            d["sha256_pixeles"] = None
            d["error_pixeles"] = repr(e)
    else:
        d["sha256_pixeles"] = None
        d["nota_pixeles"] = f"omitido: supera el tope de {CAP_PX_HASH} px"
    return d


def senales_pdf(path: Path) -> dict:
    import pypdfium2 as pdfium
    import pypdfium2.raw as raw

    est: dict = {
        "tipo_archivo": "pdf",
        "pypdfium2": _s(pdfium.PYPDFIUM_INFO),
        "pdfium": _s(pdfium.PDFIUM_INFO),
        "notas": [],
    }
    est.update(eof_markers(path))

    doc = pdfium.PdfDocument(str(path))
    try:
        try:
            est["metadatos"] = {k: _s(v) for k, v in doc.get_metadata_dict().items()}
        except Exception as e:  # noqa: BLE001
            est["metadatos"] = None
            est["notas"].append(f"metadatos no disponibles: {e!r}")
        for clave, fn in (
            ("version_pdf", doc.get_version),
            ("etiquetado", doc.is_tagged),
            ("adjuntos", doc.count_attachments),
            ("formtype", doc.get_formtype),
            ("pagemode", doc.get_pagemode),
        ):
            try:
                est[clave] = _s(fn()) if clave in ("pagemode",) else fn()
            except Exception as e:  # noqa: BLE001
                est[clave] = None
                est["notas"].append(f"{clave} no disponible: {e!r}")
        try:
            ident = doc.get_identifier()
            est["identificador_permanente"] = ident.hex() if isinstance(ident, bytes) else _s(ident)
        except Exception as e:  # noqa: BLE001
            est["identificador_permanente"] = None
            est["notas"].append(f"identificador no disponible: {e!r}")

        est["paginas"] = len(doc)
        est["detalle_paginas"] = []
        fuentes_doc: dict[str, int] = {}
        imagenes_doc: list[dict] = []

        for i in range(len(doc)):
            page = doc[i]
            pg: dict = {"pagina": i + 1}
            try:
                pg["tamano_pt"] = [round(x, 2) for x in page.get_size()]
                pg["mediabox"] = [round(x, 2) for x in page.get_mediabox()]
                pg["rotacion"] = page.get_rotation()
            except Exception as e:  # noqa: BLE001
                pg["error_geometria"] = repr(e)
            conteos = {"texto": 0, "imagen": 0, "trazo": 0, "form": 0, "sombreado": 0, "otro": 0}
            fuentes_pg: dict[str, int] = {}
            tamanos: list[float] = []
            detalle_texto: list[dict] = []
            imgs_pg: list[dict] = []
            try:
                textpage = page.get_textpage()
            except Exception as e:  # noqa: BLE001
                textpage = None
                pg["error_textpage"] = repr(e)
            try:
                for j, obj in enumerate(page.get_objects(textpage=textpage)):
                    t = obj.type
                    nivel = getattr(obj, "level", 0)
                    if t == raw.FPDF_PAGEOBJ_TEXT:
                        conteos["texto"] += 1
                        nombre = familia = None
                        peso = None
                        emb = None
                        tam = None
                        errs: list = []
                        try:
                            fo = obj.get_font()
                            nombre = _s(_attr(fo, "get_base_name", errs))
                            familia = _s(_attr(fo, "get_family_name", errs))
                            peso = _attr(fo, "get_weight", errs)
                            e_emb = _attr(fo, "is_embedded", errs)
                            emb = None if e_emb is None else bool(e_emb)
                        except Exception as e:  # noqa: BLE001
                            errs.append(f"get_font(): {e!r}")
                        if errs:
                            pg.setdefault("errores_fuente", []).extend(errs)
                        try:
                            tam = round(float(obj.get_font_size()), 3)
                            tamanos.append(tam)
                        except Exception:  # noqa: BLE001
                            tam = None
                        clave = f"base={nombre}|fam={familia}|emb={emb}|peso={peso}"
                        fuentes_pg[clave] = fuentes_pg.get(clave, 0) + 1
                        fuentes_doc[clave] = fuentes_doc.get(clave, 0) + 1
                        if len(detalle_texto) < CAP_DETALLE_TEXTO:
                            texto = None
                            try:
                                # extract() usa el textpage con el que se listo el objeto
                                texto = _s(obj.extract())
                            except Exception:  # noqa: BLE001
                                texto = None
                            try:
                                bounds = [round(x, 2) for x in obj.get_bounds()]
                            except Exception:  # noqa: BLE001
                                bounds = None
                            detalle_texto.append({
                                "i": j, "nivel": nivel, "texto": texto,
                                "fuente": nombre, "familia": familia,
                                "peso": peso, "embebida": emb,
                                "tamano": tam, "bounds": bounds,
                            })
                    elif t == raw.FPDF_PAGEOBJ_IMAGE:
                        conteos["imagen"] += 1
                        sig = firma_imagen(obj, j, nivel)
                        sig["pagina"] = i + 1
                        imgs_pg.append(sig)
                        imagenes_doc.append(sig)
                    elif t == raw.FPDF_PAGEOBJ_PATH:
                        conteos["trazo"] += 1
                    elif t == raw.FPDF_PAGEOBJ_FORM:
                        conteos["form"] += 1
                    elif t == raw.FPDF_PAGEOBJ_SHADING:
                        conteos["sombreado"] += 1
                    else:
                        conteos["otro"] += 1
            except Exception as e:  # noqa: BLE001
                pg["error_objetos"] = repr(e)
            # texto de la capa embebida (no OCR): sirve para contrastar con el OCR
            if textpage is not None:
                try:
                    emb_txt = textpage.get_text_bounded()
                    pg["capa_texto_chars"] = len(emb_txt or "")
                    pg["capa_texto"] = emb_txt
                except Exception as e:  # noqa: BLE001
                    pg["capa_texto_chars"] = None
                    pg["error_capa_texto"] = repr(e)
            if pg.get("errores_fuente"):  # dedupe: un mismo fallo se repite por objeto
                pg["errores_fuente"] = sorted(set(pg["errores_fuente"]))
            pg["objetos"] = conteos
            pg["objetos_total"] = sum(conteos.values())
            pg["fuentes"] = fuentes_pg
            pg["fuentes_distintas"] = len(fuentes_pg)
            if tamanos:
                pg["tamanos_fuente"] = {
                    "min": min(tamanos), "max": max(tamanos),
                    "distintos": sorted(set(tamanos)),
                }
            pg["objetos_texto_detalle"] = detalle_texto
            pg["detalle_truncado"] = conteos["texto"] > len(detalle_texto)
            pg["imagenes"] = imgs_pg
            est["detalle_paginas"].append(pg)

        est["fuentes_documento"] = fuentes_doc
        est["fuentes_distintas_documento"] = len(fuentes_doc)
        est["imagenes_documento"] = imagenes_doc
        est["imagenes_total"] = len(imagenes_doc)
        est["sha256_imagenes"] = [x.get("sha256_stream") for x in imagenes_doc]
        est["sha256_pixeles_imagenes"] = [x.get("sha256_pixeles") for x in imagenes_doc]
    finally:
        doc.close()
    return est


def senales_imagen(path: Path) -> dict:
    from PIL import Image

    data = path.read_bytes()
    est: dict = {
        "tipo_archivo": "imagen",
        "bytes": len(data),
        "sha256_archivo": sha256_bytes(data),
        "notas": [
            "documento de imagen: no aplican metadatos PDF, objetos de pagina, "
            "nombres de fuente ni conteo de %%EOF",
        ],
        "metadatos": None,
        "fuentes_documento": {},
        "fuentes_distintas_documento": 0,
        "eof_markers": None,
        "tiene_actualizacion_incremental": None,
    }
    with Image.open(path) as im:
        est["paginas"] = getattr(im, "n_frames", 1)
        est["formato"] = im.format
        est["modo"] = im.mode
        est["tamano_px"] = list(im.size)
        est["info_dpi"] = list(im.info.get("dpi")) if im.info.get("dpi") else None
        try:
            exif = im.getexif()
            est["exif"] = {str(k): _s(v) for k, v in dict(exif).items()} if exif else {}
        except Exception as e:  # noqa: BLE001
            est["exif"] = None
            est["notas"].append(f"exif no disponible: {e!r}")
        try:
            rgb = im.convert("RGB")
            est["sha256_pixeles"] = sha256_bytes(rgb.tobytes())
        except Exception as e:  # noqa: BLE001
            est["sha256_pixeles"] = None
            est["notas"].append(f"hash de pixeles no disponible: {e!r}")
    est["imagenes_documento"] = []
    est["imagenes_total"] = 0
    return est


def senales(path: Path) -> dict:
    if path.suffix.lower() == ".pdf":
        return senales_pdf(path)
    return senales_imagen(path)


# ------------------------------------------------------------------------- pipeline
def cargar_shard() -> list[dict]:
    with MANIFEST.open(encoding="utf-8-sig", newline="") as fh:
        filas = list(csv.DictReader(fh))
    filas.sort(key=lambda r: (r["etiqueta"], r["archivo"]))
    mios = []
    for i, r in enumerate(filas):
        if i % NSHARDS == SHARD:
            r["_i"] = i
            mios.append(r)
    return mios


def main() -> int:
    from incapacidad_ocr.extract import RuleBasedExtractor
    from incapacidad_ocr.ocr import get_ocr_backend
    from incapacidad_ocr.processor import IncapacidadProcessor

    mios = cargar_shard()
    print(f"[shard {SHARD}/{NSHARDS}] documentos asignados: {len(mios)}", flush=True)
    for r in mios:
        print(f"  i={r['_i']:>2} {r['etiqueta']:<5} {r['archivo']}", flush=True)

    t0 = time.time()
    backend = get_ocr_backend("rapidocr")  # los modelos ONNX se cargan UNA vez
    proc = IncapacidadProcessor(backend, RuleBasedExtractor())
    print(f"[backend rapidocr listo en {time.time()-t0:.1f}s]", flush=True)

    resumen = {"procesados": [], "fallidos": [], "sin_texto": [],
               "campos": {"cedula": 0, "cie10": 0, "fecha_inicio": 0, "fecha_fin": 0, "dias": 0},
               "rutas": []}

    for r in mios:
        etiqueta = r["etiqueta"]
        carpeta = CARPETA.get(etiqueta, etiqueta)
        ruta = DOCS / carpeta / r["archivo"]
        stem = Path(r["archivo"]).stem
        destino = OUT / carpeta
        destino.mkdir(parents=True, exist_ok=True)
        t = time.time()
        try:
            est: dict = {}
            try:
                est = senales(ruta)
            except Exception as e:  # noqa: BLE001
                est = {"error_estructura": repr(e),
                       "traceback": traceback.format_exc(limit=4)}
            res = proc.run(ruta)
            texto = res.get("texto_plano") or ""
            rec = res.get("incapacidad") or {}
            doc = {
                "archivo": r["archivo"],
                "etiqueta": etiqueta,
                "indice_global": r["_i"],
                "shard": SHARD,
                "sha256_manifest": r["sha256"],
                "cuarentena": r.get("cuarentena"),
                "motivo_cuarentena": r.get("motivo_cuarentena") or None,
                "ruta": str(ruta).replace("\\", "/"),
                "ocr_backend": res.get("ocr_backend"),
                "extractor": res.get("extractor"),
                "aviso": res.get("aviso"),
                "texto_plano": texto,
                "texto_chars": len(texto.strip()),
                "incapacidad": rec,
                "estructura": est,
            }
            jpath = destino / f"{stem}.json"
            tpath = destino / f"{stem}.txt"
            with jpath.open("w", encoding="utf-8", errors="replace") as fh:
                json.dump(doc, fh, ensure_ascii=False, indent=2)
            with tpath.open("w", encoding="utf-8", errors="replace") as fh:
                fh.write(texto)
            resumen["rutas"] += [str(jpath).replace("\\", "/"), str(tpath).replace("\\", "/")]

            inc = rec.get("incapacidad") or {}
            if (rec.get("paciente") or {}).get("documento_numero"):
                resumen["campos"]["cedula"] += 1
            if (rec.get("diagnostico") or {}).get("cie10"):
                resumen["campos"]["cie10"] += 1
            for k in ("fecha_inicio", "fecha_fin", "dias"):
                if inc.get(k) not in (None, "", []):
                    resumen["campos"][k] += 1
            if len(texto.strip()) < 200:
                resumen["sin_texto"].append({"archivo": r["archivo"], "chars": len(texto.strip())})
            resumen["procesados"].append(r["archivo"])
            print(f"OK  [{r['_i']:>2}] {r['archivo']}  chars={len(texto.strip())} "
                  f"paginas={est.get('paginas')} fuentes={est.get('fuentes_distintas_documento')} "
                  f"imgs={est.get('imagenes_total')} eof={est.get('eof_markers')} "
                  f"({time.time()-t:.1f}s)", flush=True)
        except Exception as e:  # noqa: BLE001
            resumen["fallidos"].append({"archivo": r["archivo"], "error": repr(e),
                                        "traceback": traceback.format_exc(limit=6)})
            print(f"FALLO [{r['_i']:>2}] {r['archivo']}: {e!r}", flush=True)
            traceback.print_exc()

    rpath = BASE / "senales" / f"_resumen_shard{SHARD}.json"
    with rpath.open("w", encoding="utf-8", errors="replace") as fh:
        json.dump(resumen, fh, ensure_ascii=False, indent=2)
    print(f"\n[fin] procesados={len(resumen['procesados'])} fallidos={len(resumen['fallidos'])} "
          f"sin_texto={len(resumen['sin_texto'])} en {time.time()-t0:.1f}s", flush=True)
    print(f"[campos] {resumen['campos']}", flush=True)
    print(f"[resumen] {rpath}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
