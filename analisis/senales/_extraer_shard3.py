"""Shard 3/4 — OCR + extraccion de campos + señales estructurales del corpus de falsedad.

100% LOCAL: RapidOCR (ONNX/CPU) + pypdfium2 + Pillow. Sin servicios remotos.

Uso:
    .venv/Scripts/python.exe _extraer_shard3.py [--shard 3] [--total 4]

Escribe, por documento:
    dataset-falsedad/ocr/<etiqueta_dir>/<nombre-sin-ext>.json
    dataset-falsedad/ocr/<etiqueta_dir>/<nombre-sin-ext>.txt
y un resumen SIN PII en:
    dataset-falsedad/senales/_resumen_shard3.json
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sys
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
BASE = Path(str(_DATASET))
MANIFEST = BASE / "manifest.csv"
DOCS = BASE / "docs"
OUT = BASE / "ocr"

sys.path.insert(0, REPO)

import pypdfium2 as pdfium  # noqa: E402
import pypdfium2.raw as pdfium_c  # noqa: E402
from PIL import Image  # noqa: E402

from incapacidad_ocr.extract import RuleBasedExtractor  # noqa: E402
from incapacidad_ocr.ocr import get_ocr_backend  # noqa: E402
from incapacidad_ocr.processor import IncapacidadProcessor  # noqa: E402

# etiqueta del manifest -> carpeta del corpus (docs/ y ocr/ usan el plural)
ETIQUETA_DIR = {"falsa": "falsas", "real": "reales"}

TIPO_OBJ = {
    pdfium_c.FPDF_PAGEOBJ_UNKNOWN: "desconocido",
    pdfium_c.FPDF_PAGEOBJ_TEXT: "texto",
    pdfium_c.FPDF_PAGEOBJ_PATH: "path",
    pdfium_c.FPDF_PAGEOBJ_IMAGE: "imagen",
    pdfium_c.FPDF_PAGEOBJ_SHADING: "shading",
    pdfium_c.FPDF_PAGEOBJ_FORM: "form",
}


def sha256_bytes(b) -> str:
    h = hashlib.sha256()
    h.update(bytes(b))
    return h.hexdigest()


def sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


# ---------------------------------------------------------------- señales crudas
def senales_bytes_crudos(p: Path) -> dict:
    """Heuristicas baratas sobre los bytes del PDF (generaciones / incremental updates)."""
    raw = p.read_bytes()
    return {
        "bytes": len(raw),
        "cuenta_eof": raw.count(b"%%EOF"),
        "cuenta_startxref": raw.count(b"startxref"),
        "cuenta_trailer": raw.count(b"trailer"),
        "cuenta_obj": raw.count(b" obj"),
        "linearizado": b"/Linearized" in raw,
        "tiene_xref_stream": b"/XRef" in raw,
        "tiene_objstm": b"/ObjStm" in raw,
        "cabecera": raw[:9].decode("latin-1", "replace"),
        # >1 generacion => el PDF fue guardado de nuevo encima (incremental update)
        "generaciones_estimadas": max(1, raw.count(b"%%EOF")),
    }


# ---------------------------------------------------------------- señales PDF
def senales_pdf(p: Path, avisos: list[str]) -> dict:
    info: dict = {}
    pdf = pdfium.PdfDocument(str(p))
    try:
        try:
            info["version"] = pdf.get_version()
        except Exception as e:  # noqa: BLE001
            avisos.append(f"version no disponible: {e.__class__.__name__}")
        try:
            info["metadatos"] = pdf.get_metadata_dict(skip_empty=False)
        except Exception as e:  # noqa: BLE001
            avisos.append(f"metadatos no disponibles: {e.__class__.__name__}")
        for k, campo in (("id_permanente", 0), ("id_cambiante", 1)):
            try:
                info[k] = pdf.get_identifier(campo).hex()
            except Exception as e:  # noqa: BLE001
                info[k] = None
                avisos.append(f"{k} no disponible: {e.__class__.__name__}")
        # IDs distintos => el archivo fue modificado despues de su creacion.
        # Cadena vacia = el trailer NO trae /ID (senal en si misma), != API no disponible.
        info["ids_presentes"] = bool(info.get("id_permanente")) and bool(info.get("id_cambiante"))
        info["ids_difieren"] = (
            info["id_permanente"] != info["id_cambiante"] if info["ids_presentes"] else None
        )
        for k, fn in (("etiquetado", pdf.is_tagged), ("formtype", pdf.get_formtype),
                      ("adjuntos", pdf.count_attachments)):
            try:
                info[k] = fn()
            except Exception as e:  # noqa: BLE001
                avisos.append(f"{k} no disponible: {e.__class__.__name__}")

        info["paginas"] = len(pdf)
        info["por_pagina"] = [_pagina(pdf, i, avisos) for i in range(len(pdf))]
    finally:
        pdf.close()

    # agregados utiles para las familias TIPOGRAFIA_MIXTA / FIRMA_MEDICO
    fuentes = {}
    imgs = []
    for pg in info.get("por_pagina", []):
        for f in pg.get("fuentes", []):
            key = (f["base"], f["familia"], f["peso"], f["embebida"])
            d = fuentes.setdefault(key, {"base": f["base"], "familia": f["familia"],
                                         "peso": f["peso"], "embebida": f["embebida"],
                                         "n_objetos": 0, "tamanos": set()})
            d["n_objetos"] += f["n_objetos"]
            d["tamanos"].update(f["tamanos"])
        imgs.extend(pg.get("imagenes", []))
    info["fuentes_documento"] = sorted(
        ({**v, "tamanos": sorted(v["tamanos"])} for v in fuentes.values()),
        key=lambda d: (-d["n_objetos"], d["base"] or ""),
    )
    info["n_fuentes_distintas"] = len(info["fuentes_documento"])
    info["n_imagenes_total"] = len(imgs)
    info["sha256_imagenes"] = sorted({i["sha256_raw"] for i in imgs if i.get("sha256_raw")})
    info["n_objetos_texto_total"] = sum(
        pg.get("por_tipo", {}).get("texto", 0) for pg in info.get("por_pagina", [])
    )
    info["caracteres_texto_embebido"] = sum(
        pg.get("caracteres_texto_embebido") or 0 for pg in info.get("por_pagina", [])
    )
    return info


def _pagina(pdf, i: int, avisos: list[str]) -> dict:
    page = pdf[i]
    d: dict = {"indice": i}
    try:
        w, h = page.get_size()
        d["ancho_pt"], d["alto_pt"] = round(w, 2), round(h, 2)
        d["rotacion"] = page.get_rotation()
        d["mediabox"] = [round(v, 2) for v in page.get_mediabox()]
    except Exception as e:  # noqa: BLE001
        avisos.append(f"p{i}: geometria no disponible: {e.__class__.__name__}")

    # tamaño de la capa de texto real (0 => pagina puramente escaneada)
    try:
        tp = page.get_textpage()
        try:
            d["caracteres_texto_embebido"] = tp.count_chars()
        finally:
            tp.close()
    except Exception as e:  # noqa: BLE001
        d["caracteres_texto_embebido"] = None
        avisos.append(f"p{i}: capa de texto no disponible: {e.__class__.__name__}")

    por_tipo: dict[str, int] = {}
    fuentes: dict[tuple, dict] = {}
    imagenes: list[dict] = []
    try:
        objetos = list(page.get_objects())
    except Exception as e:  # noqa: BLE001
        avisos.append(f"p{i}: get_objects fallo: {e.__class__.__name__}: {e}")
        objetos = []

    d["n_objetos"] = len(objetos)
    for n, obj in enumerate(objetos):
        tipo = TIPO_OBJ.get(obj.type, f"tipo_{obj.type}")
        por_tipo[tipo] = por_tipo.get(tipo, 0) + 1
        if obj.type == pdfium_c.FPDF_PAGEOBJ_TEXT:
            _acumular_fuente(obj, fuentes, i, avisos)
        elif obj.type == pdfium_c.FPDF_PAGEOBJ_IMAGE:
            imagenes.append(_imagen(obj, n, i, avisos))

    d["por_tipo"] = por_tipo
    d["fuentes"] = sorted(
        ({**v, "tamanos": sorted(v["tamanos"])} for v in fuentes.values()),
        key=lambda x: (-x["n_objetos"], x["base"] or ""),
    )
    d["n_fuentes_distintas"] = len(d["fuentes"])
    d["imagenes"] = imagenes
    return d


def _acumular_fuente(obj, fuentes: dict, i: int, avisos: list[str]) -> None:
    base = familia = None
    peso = embebida = None
    try:
        font = obj.get_font()
        try:
            base = font.get_base_name()
        except Exception:  # noqa: BLE001
            pass
        try:
            familia = font.get_family_name()
        except Exception:  # noqa: BLE001
            pass
        try:
            peso = font.get_weight()
        except Exception:  # noqa: BLE001
            pass
        try:
            embebida = font.is_embedded
        except Exception:  # noqa: BLE001
            pass
    except Exception as e:  # noqa: BLE001
        avisos.append(f"p{i}: fuente no disponible: {e.__class__.__name__}")
    try:
        tam = round(obj.get_font_size(), 2)
    except Exception:  # noqa: BLE001
        tam = None
    key = (base, familia, peso, embebida)
    d = fuentes.setdefault(key, {"base": base, "familia": familia, "peso": peso,
                                 "embebida": embebida, "n_objetos": 0, "tamanos": set()})
    d["n_objetos"] += 1
    if tam is not None:
        d["tamanos"].add(tam)


def _imagen(obj, n: int, i: int, avisos: list[str]) -> dict:
    d: dict = {"indice_objeto": n}
    try:
        d["px"] = list(obj.get_px_size())
    except Exception as e:  # noqa: BLE001
        avisos.append(f"p{i}: px_size imagen {n}: {e.__class__.__name__}")
    try:
        d["filtros"] = list(obj.get_filters())
    except Exception as e:  # noqa: BLE001
        avisos.append(f"p{i}: filtros imagen {n}: {e.__class__.__name__}")
    try:
        raw = obj.get_data(decode_simple=False)
        d["bytes_stream"] = len(raw)
        # sha256 del stream embebido: identico => misma imagen (firma) reutilizada
        d["sha256_raw"] = sha256_bytes(raw)
    except Exception as e:  # noqa: BLE001
        avisos.append(f"p{i}: datos imagen {n}: {e.__class__.__name__}")
    try:
        dec = obj.get_data(decode_simple=True)
        d["bytes_decodificado"] = len(dec)
        d["sha256_decodificado"] = sha256_bytes(dec)
    except Exception as e:  # noqa: BLE001
        avisos.append(f"p{i}: datos decodificados imagen {n}: {e.__class__.__name__}")
    try:
        bx = obj.get_bounds()
        d["bbox"] = [round(float(v), 2) for v in bx]
    except Exception:  # noqa: BLE001
        d["bbox"] = None
    try:
        m = obj.get_metadata()
        d["dpi_horizontal"] = m.horizontal_dpi
        d["dpi_vertical"] = m.vertical_dpi
        d["bits_por_pixel"] = m.bits_per_pixel
        d["colorspace"] = m.colorspace
    except Exception as e:  # noqa: BLE001
        avisos.append(f"p{i}: metadata imagen {n}: {e.__class__.__name__}")
    return d


# ---------------------------------------------------------------- señales imagen
def senales_imagen(p: Path, avisos: list[str]) -> dict:
    d: dict = {}
    try:
        with Image.open(p) as im:
            d["formato"] = im.format
            d["modo"] = im.mode
            d["ancho_px"], d["alto_px"] = im.size
            d["n_frames"] = getattr(im, "n_frames", 1)
            info = {k: v for k, v in (im.info or {}).items()
                    if isinstance(v, (str, int, float, bool, type(None)))}
            d["info"] = info
            # tablas de cuantizacion JPEG: su huella cambia al re-guardar/editar
            q = getattr(im, "quantization", None)
            if q:
                d["jpeg_qtables"] = {str(k): sha256_bytes(bytes(v))[:16] for k, v in q.items()}
            try:
                exif = im.getexif()
                d["exif"] = {str(k): str(v)[:200] for k, v in dict(exif).items()} if exif else {}
            except Exception as e:  # noqa: BLE001
                d["exif"] = None
                avisos.append(f"exif no disponible: {e.__class__.__name__}")
    except Exception as e:  # noqa: BLE001
        avisos.append(f"Pillow no pudo inspeccionar el archivo: {e.__class__.__name__}: {e}")
    return d


# ---------------------------------------------------------------- estructura
def estructura(p: Path, etiqueta: str) -> dict:
    avisos: list[str] = []
    est: dict = {
        "archivo": p.name,
        "extension": p.suffix.lower().lstrip("."),
        "bytes": p.stat().st_size,
        "sha256_archivo": sha256_file(p),
        "avisos": avisos,
    }
    if p.suffix.lower() == ".pdf":
        est["bytes_crudos"] = senales_bytes_crudos(p)
        try:
            est["pdf"] = senales_pdf(p, avisos)
        except Exception as e:  # noqa: BLE001
            est["pdf"] = None
            avisos.append(f"pypdfium2 fallo al abrir el PDF: {e.__class__.__name__}: {e}")
    else:
        est["imagen"] = senales_imagen(p, avisos)
        est["pdf"] = None
        avisos.append("No es PDF: metadatos/fuentes/EOF de PDF no aplican.")
    return est


# ---------------------------------------------------------------- corpus
def cargar_corpus() -> list[dict]:
    with MANIFEST.open(encoding="utf-8-sig", newline="") as fh:
        filas = list(csv.DictReader(fh))
    # orden estable: etiqueta y luego nombre de archivo
    filas.sort(key=lambda r: (r["etiqueta"], r["archivo"]))
    return filas


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--shard", type=int, default=3)
    ap.add_argument("--total", type=int, default=4)
    args = ap.parse_args()

    filas = cargar_corpus()
    mios = [(i, r) for i, r in enumerate(filas) if i % args.total == args.shard]
    print(f"corpus={len(filas)} shard={args.shard}/{args.total} mios={len(mios)}", flush=True)

    proc = IncapacidadProcessor(get_ocr_backend("rapidocr"), RuleBasedExtractor())
    print("backend rapidocr listo", flush=True)

    resumen = {"shard": args.shard, "total_shards": args.total, "corpus": len(filas),
               "asignados": len(mios), "procesados": 0, "docs": [], "fallidos": [],
               "sin_texto": [], "rutas": [],
               "campos_leidos": {"cedula": 0, "cie10": 0, "fecha_inicio": 0,
                                 "fecha_fin": 0, "dias": 0}}

    for i, fila in mios:
        nombre = fila["archivo"]
        etiqueta = fila["etiqueta"]
        edir = ETIQUETA_DIR.get(etiqueta, etiqueta)
        ruta = DOCS / edir / nombre
        destino = OUT / edir
        destino.mkdir(parents=True, exist_ok=True)
        stem = Path(nombre).stem
        print(f"[{i}] {edir}/{stem[:40]}...", flush=True)
        try:
            res = proc.run(str(ruta))
            texto = res.get("texto_plano") or ""
            rec = res.get("incapacidad") or {}
            est = estructura(ruta, etiqueta)

            doc = {
                "archivo": nombre,
                "etiqueta": etiqueta,
                "ocr_backend": res.get("ocr_backend"),
                "extractor": res.get("extractor"),
                "texto_plano": texto,
                "incapacidad": rec,
                "estructura": est,
            }
            if res.get("aviso"):
                doc["aviso"] = res["aviso"]

            fj = destino / f"{stem}.json"
            ft = destino / f"{stem}.txt"
            fj.write_text(json.dumps(doc, ensure_ascii=False, indent=1, default=str),
                          encoding="utf-8")
            ft.write_text(texto, encoding="utf-8")

            campos = {
                "cedula": (rec.get("paciente") or {}).get("documento_numero"),
                "cie10": (rec.get("diagnostico") or {}).get("cie10"),
                "fecha_inicio": (rec.get("incapacidad") or {}).get("fecha_inicio"),
                "fecha_fin": (rec.get("incapacidad") or {}).get("fecha_fin"),
                "dias": (rec.get("incapacidad") or {}).get("dias"),
            }
            for k, v in campos.items():
                if v not in (None, "", []):
                    resumen["campos_leidos"][k] += 1

            resumen["procesados"] += 1
            resumen["rutas"] += [str(fj).replace("\\", "/"), str(ft).replace("\\", "/")]
            n_txt = len(texto.strip())
            if n_txt < 50:
                resumen["sin_texto"].append({"archivo": nombre, "etiqueta": etiqueta,
                                             "chars": n_txt})
            resumen["docs"].append({
                "indice": i, "archivo": nombre, "etiqueta": etiqueta,
                "chars_ocr": n_txt,
                "campos_no_nulos": {k: v not in (None, "", []) for k, v in campos.items()},
                "cuarentena": fila.get("cuarentena"),
                "avisos_estructura": len(est.get("avisos") or []),
            })
            print(f"     ok chars={n_txt} campos={sum(v not in (None,'',[]) for v in campos.values())}/5",
                  flush=True)
        except Exception as e:  # noqa: BLE001
            resumen["fallidos"].append({
                "archivo": nombre, "etiqueta": etiqueta,
                "error": f"{e.__class__.__name__}: {e}",
                "traceback": traceback.format_exc()[-1500:],
            })
            print(f"     FALLO {e.__class__.__name__}: {e}", flush=True)

    rp = BASE / "senales" / f"_resumen_shard{args.shard}.json"
    rp.write_text(json.dumps(resumen, ensure_ascii=False, indent=1), encoding="utf-8")
    print("RESUMEN:", str(rp).replace("\\", "/"), flush=True)
    print(json.dumps({k: v for k, v in resumen.items() if k != "docs"},
                     ensure_ascii=False, indent=1), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
