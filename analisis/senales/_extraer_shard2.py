"""Shard 2/4 — OCR + extraccion de campos + señales estructurales del corpus de falsedad.

100% LOCAL: RapidOCR (ONNX/CPU) + pypdfium2 + Pillow. Ningun servicio remoto.

Selecciona los documentos del manifest ordenados por (etiqueta, archivo) cuyo indice
global cumple  i % 4 == 2, y por cada uno escribe:

    dataset-falsedad/ocr/<etiqueta>/<nombre-sin-extension>.json
    dataset-falsedad/ocr/<etiqueta>/<nombre-sin-extension>.txt

El JSON lleva el texto plano del OCR, el registro estructurado del extractor de reglas
del repo, y un bloque "estructura" con la materia prima de las familias TIPOGRAFIA_MIXTA
y FIRMA_MEDICO (metadatos del PDF, fuentes por pagina, objetos texto/imagen, sha256 de
cada imagen embebida, generaciones del PDF via conteo de '%%EOF').

Uso:
    incapacidad-ocr/.venv/Scripts/python.exe dataset-falsedad/senales/_extraer_shard2.py
"""
from __future__ import annotations

import csv
import hashlib
import json
import sys
import traceback
from collections import Counter
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
sys.path.insert(0, REPO)

SHARD = 2
NUM_SHARDS = 4

# Carpeta de documentos por etiqueta del manifest (docs/falsas, docs/reales).
DOCS_DIR = {"falsa": "falsas", "real": "reales"}


# --------------------------------------------------------------------------- #
# Señales estructurales
# --------------------------------------------------------------------------- #
def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _generaciones_pdf(raw_bytes: bytes) -> dict:
    """Heuristica barata de 'incremental updates': cuantas veces se cerro el fichero.

    Un PDF generado de una sola vez trae un unico '%%EOF'. Cada guardado incremental
    (p.ej. editar y volver a guardar con una herramienta que preserva el original)
    añade otro '%%EOF' y un '/Prev' en el trailer apuntando al xref anterior.
    """
    return {
        "eof_count": raw_bytes.count(b"%%EOF"),
        "prev_count": raw_bytes.count(b"/Prev"),
        "startxref_count": raw_bytes.count(b"startxref"),
        "linearized": b"/Linearized" in raw_bytes,
        "tiene_objstm": b"/ObjStm" in raw_bytes,
        "tiene_annots": b"/Annot" in raw_bytes,
        "nota": "eof_count>1 o prev_count>0 sugiere guardado incremental (varias generaciones)",
    }


def _info_fuente(font) -> dict:
    """Datos de una fuente. Lo que la version instalada no exponga queda en None."""
    info = {
        "base_name": None,
        "family_name": None,
        "embedded": None,
        "weight": None,
        "italic_angle": None,
        "flags": None,
    }
    # En pypdfium2 5.10 ``is_embedded`` es una cached_property (no un metodo).
    for clave, getter in (
        ("base_name", font.get_base_name),
        ("family_name", font.get_family_name),
        ("embedded", lambda: font.is_embedded),
        ("weight", font.get_weight),
    ):
        try:
            info[clave] = getter()
        except Exception as e:  # API ausente/fallo puntual: se anota, no se inventa
            info[clave] = None
            info.setdefault("_errores", {})[clave] = f"{type(e).__name__}: {e}"
    # italic_angle / flags no tienen wrapper en pypdfium2 5.x -> se piden al raw handle.
    # FPDFFont_GetItalicAngle usa parametro de salida; FPDFFont_GetFlags devuelve el int.
    try:
        import ctypes

        import pypdfium2.raw as raw

        handle = getattr(font, "raw", None)
        if handle is not None:
            angulo = ctypes.c_int()
            if raw.FPDFFont_GetItalicAngle(handle, ctypes.byref(angulo)):
                info["italic_angle"] = angulo.value
            info["flags"] = raw.FPDFFont_GetFlags(handle)
    except Exception as e:
        info.setdefault("_errores", {})["italic_angle_flags"] = f"{type(e).__name__}: {e}"
    return info


def estructura_pdf(path: Path) -> dict:
    """Señales estructurales de un PDF (local, pypdfium2 + bytes crudos)."""
    import pypdfium2 as pdfium
    import pypdfium2.raw as raw

    raw_bytes = path.read_bytes()
    est: dict = {
        "tipo_contenedor": "pdf",
        "bytes": len(raw_bytes),
        "sha256_archivo": _sha256_file(path),
        "generaciones": _generaciones_pdf(raw_bytes),
        "avisos": [],
    }

    pdf = pdfium.PdfDocument(str(path))
    try:
        try:
            est["metadatos"] = pdf.get_metadata_dict(skip_empty=False)
        except Exception as e:
            est["metadatos"] = None
            est["avisos"].append(f"get_metadata_dict fallo: {type(e).__name__}: {e}")
        try:
            est["version_pdf"] = pdf.get_version()
        except Exception as e:
            est["version_pdf"] = None
            est["avisos"].append(f"get_version fallo: {type(e).__name__}: {e}")
        try:
            est["identificador"] = {
                "permanent": (pdf.get_identifier(raw.FILEIDTYPE_PERMANENT) or b"").hex() or None,
                "changing": (pdf.get_identifier(raw.FILEIDTYPE_CHANGING) or b"").hex() or None,
            }
        except Exception as e:
            est["identificador"] = None
            est["avisos"].append(f"get_identifier fallo: {type(e).__name__}: {e}")
        try:
            est["formulario"] = pdf.get_formtype()
            est["etiquetado"] = pdf.is_tagged()
        except Exception as e:
            est["avisos"].append(f"formtype/is_tagged fallo: {type(e).__name__}: {e}")

        est["n_paginas"] = len(pdf)
        est["paginas"] = []
        fuentes_doc: Counter = Counter()
        imagenes_doc: list[dict] = []

        for idx in range(len(pdf)):
            page = pdf[idx]
            pag: dict = {"indice": idx, "avisos": []}
            try:
                pag["tamano_pt"] = list(page.get_size())
                pag["mediabox"] = list(page.get_mediabox())
                pag["rotacion"] = page.get_rotation()
            except Exception as e:
                pag["avisos"].append(f"geometria fallo: {type(e).__name__}: {e}")

            # Capa de texto digital: si el PDF es un escaneo puro, count_chars() ~ 0.
            try:
                tp = page.get_textpage()
                pag["chars_capa_texto"] = tp.count_chars()
                pag["capa_texto_extraida"] = tp.get_text_bounded() if pag["chars_capa_texto"] else ""
                tp.close()
            except Exception as e:
                pag["chars_capa_texto"] = None
                pag["capa_texto_extraida"] = None
                pag["avisos"].append(f"textpage fallo: {type(e).__name__}: {e}")

            # Objetos de pagina: se recorre en profundidad (los XObject/Form anidan objetos).
            tipos: Counter = Counter()
            fuentes_pag: Counter = Counter()
            detalle_fuentes: dict[str, dict] = {}
            tamanos: Counter = Counter()
            imagenes_pag: list[dict] = []
            try:
                for obj in page.get_objects(max_depth=15):
                    nombre_tipo = {
                        raw.FPDF_PAGEOBJ_TEXT: "texto",
                        raw.FPDF_PAGEOBJ_IMAGE: "imagen",
                        raw.FPDF_PAGEOBJ_PATH: "path",
                        raw.FPDF_PAGEOBJ_SHADING: "shading",
                        raw.FPDF_PAGEOBJ_FORM: "form",
                    }.get(obj.type, f"desconocido_{obj.type}")
                    tipos[nombre_tipo] += 1

                    if obj.type == raw.FPDF_PAGEOBJ_TEXT:
                        try:
                            font = obj.get_font()
                            info = _info_fuente(font)
                            clave = info["base_name"] or info["family_name"] or "?"
                            fuentes_pag[clave] += 1
                            detalle_fuentes.setdefault(clave, info)
                            tamanos[round(float(obj.get_font_size()), 2)] += 1
                        except Exception as e:
                            pag["avisos"].append(f"fuente de objeto texto fallo: {type(e).__name__}: {e}")

                    elif obj.type == raw.FPDF_PAGEOBJ_IMAGE:
                        img: dict = {"nivel": getattr(obj, "level", None)}
                        try:
                            img["px"] = list(obj.get_px_size())
                        except Exception as e:
                            img["px"] = None
                            img["error_px"] = f"{type(e).__name__}: {e}"
                        try:
                            img["filtros"] = list(obj.get_filters())
                        except Exception as e:
                            img["filtros"] = None
                            img["error_filtros"] = f"{type(e).__name__}: {e}"
                        try:
                            md = obj.get_metadata()
                            img["metadata"] = {
                                "width": md.width,
                                "height": md.height,
                                "horizontal_dpi": round(md.horizontal_dpi, 3),
                                "vertical_dpi": round(md.vertical_dpi, 3),
                                "bits_per_pixel": md.bits_per_pixel,
                                "colorspace": md.colorspace,
                                "marked_content_id": md.marked_content_id,
                            }
                        except Exception as e:
                            img["metadata"] = None
                            img["error_metadata"] = f"{type(e).__name__}: {e}"
                        try:
                            img["bbox_pt"] = [round(v, 2) for v in obj.get_bounds()]
                        except Exception as e:
                            img["bbox_pt"] = None
                            img["error_bbox"] = f"{type(e).__name__}: {e}"
                        # sha256 del STREAM CRUDO: identifica una firma copiada entre documentos
                        try:
                            data = bytes(obj.get_data(decode_simple=False))
                            img["bytes_stream"] = len(data)
                            img["sha256_stream"] = hashlib.sha256(data).hexdigest()
                        except Exception as e:
                            img["sha256_stream"] = None
                            img["error_stream"] = f"{type(e).__name__}: {e}"
                        # sha256 de los PIXELES: sobrevive a un recomprimido/cambio de filtro
                        try:
                            bmp = obj.get_bitmap(render=False)
                            pil = bmp.to_pil()
                            img["px_bitmap"] = list(pil.size)
                            img["modo_bitmap"] = pil.mode
                            img["sha256_pixeles"] = hashlib.sha256(pil.tobytes()).hexdigest()
                        except Exception as e:
                            img["sha256_pixeles"] = None
                            img["error_pixeles"] = f"{type(e).__name__}: {e}"
                        imagenes_pag.append(img)
                        imagenes_doc.append({"pagina": idx, **img})
            except Exception as e:
                pag["avisos"].append(f"get_objects fallo: {type(e).__name__}: {e}")

            pag["objetos"] = dict(tipos)
            pag["n_objetos_texto"] = tipos.get("texto", 0)
            pag["n_objetos_imagen"] = tipos.get("imagen", 0)
            pag["fuentes"] = dict(fuentes_pag)
            pag["fuentes_detalle"] = detalle_fuentes
            pag["n_fuentes_distintas"] = len(fuentes_pag)
            pag["tamanos_fuente"] = {str(k): v for k, v in sorted(tamanos.items())}
            pag["imagenes"] = imagenes_pag
            fuentes_doc.update(fuentes_pag)
            est["paginas"].append(pag)

        est["fuentes_documento"] = dict(fuentes_doc)
        est["n_fuentes_distintas_documento"] = len(fuentes_doc)
        est["imagenes_documento"] = imagenes_doc
        est["n_imagenes_documento"] = len(imagenes_doc)
        est["sha256_imagenes"] = [i["sha256_stream"] for i in imagenes_doc if i.get("sha256_stream")]
        est["chars_capa_texto_total"] = sum(
            p.get("chars_capa_texto") or 0 for p in est["paginas"]
        )
        est["es_escaneo_puro"] = est["chars_capa_texto_total"] == 0
    finally:
        pdf.close()
    return est


def estructura_imagen(path: Path) -> dict:
    """Señales estructurales de una imagen suelta (JPEG/PNG): no hay objetos PDF.

    Aqui la materia prima equivalente son los metadatos EXIF/JFIF: el tag 'Software'
    delata edicion, y la ausencia total de EXIF es tipica de una captura de pantalla
    o de un re-guardado desde un editor.
    """
    from PIL import Image, ExifTags

    raw_bytes = path.read_bytes()
    est: dict = {
        "tipo_contenedor": "imagen",
        "bytes": len(raw_bytes),
        "sha256_archivo": _sha256_file(path),
        "avisos": ["no aplica: metadatos/fuentes/objetos de PDF (el archivo no es PDF)"],
    }
    with Image.open(path) as im:
        est["formato"] = im.format
        est["modo"] = im.mode
        est["px"] = list(im.size)
        est["n_paginas"] = getattr(im, "n_frames", 1)
        est["info_claves"] = sorted(k for k in im.info.keys() if k != "exif")
        est["jfif"] = {k: im.info[k] for k in ("jfif", "jfif_version", "jfif_unit", "jfif_density", "dpi")
                       if k in im.info and isinstance(im.info[k], (int, float, str, tuple, list))}
        try:
            est["progresivo"] = bool(im.info.get("progressive")) or bool(im.info.get("progression"))
        except Exception:
            est["progresivo"] = None
        # Tablas de cuantizacion JPEG: su huella distingue el software que guardo el fichero
        try:
            q = getattr(im, "quantization", None)
            est["jpeg_quant_tablas"] = len(q) if q else 0
            est["jpeg_quant_sha256"] = (
                hashlib.sha256(
                    b"".join(bytes(bytearray(v)) for v in q.values())
                ).hexdigest()
                if q
                else None
            )
        except Exception as e:
            est["jpeg_quant_tablas"] = None
            est["jpeg_quant_sha256"] = None
            est["avisos"].append(f"quantization fallo: {type(e).__name__}: {e}")
        exif = {}
        try:
            bruto = im.getexif()
            for tag_id, valor in bruto.items():
                nombre = ExifTags.TAGS.get(tag_id, str(tag_id))
                exif[nombre] = valor if isinstance(valor, (int, float, str)) else repr(valor)[:200]
        except Exception as e:
            est["avisos"].append(f"getexif fallo: {type(e).__name__}: {e}")
        est["exif"] = exif
        est["tiene_exif"] = bool(exif)
        est["exif_software"] = exif.get("Software")
        est["sha256_pixeles"] = hashlib.sha256(im.convert("RGB").tobytes()).hexdigest()
    # Marcadores crudos: cuantos segmentos SOI/EOI (un JPEG re-guardado puede traer miniaturas)
    est["marcadores_jpeg"] = {
        "soi": raw_bytes.count(b"\xff\xd8\xff"),
        "eoi": raw_bytes.count(b"\xff\xd9"),
        "app_adobe": b"Adobe" in raw_bytes,
        "app_photoshop": b"Photoshop" in raw_bytes,
        "xmp": b"http://ns.adobe.com/xap/1.0/" in raw_bytes,
    }
    return est


def senales_estructurales(path: Path) -> dict:
    if path.suffix.lower() == ".pdf":
        return estructura_pdf(path)
    return estructura_imagen(path)


# --------------------------------------------------------------------------- #
# Orquestacion
# --------------------------------------------------------------------------- #
def cargar_shard() -> list[dict]:
    with open(BASE / "manifest.csv", encoding="utf-8", newline="") as fh:
        filas = list(csv.DictReader(fh))
    ordenado = sorted(filas, key=lambda r: (r["etiqueta"], r["archivo"]))
    return [
        {**r, "indice_global": i}
        for i, r in enumerate(ordenado)
        if i % NUM_SHARDS == SHARD
    ]


def main() -> int:
    from incapacidad_ocr.extract import RuleBasedExtractor
    from incapacidad_ocr.ocr import get_ocr_backend
    from incapacidad_ocr.processor import IncapacidadProcessor

    docs = cargar_shard()
    print(f"[shard {SHARD}/{NUM_SHARDS}] documentos asignados: {len(docs)}", flush=True)

    # Los modelos ONNX se cargan UNA vez y se reutilizan (es la parte caraa).
    backend = get_ocr_backend("rapidocr")
    extractor = RuleBasedExtractor()
    procesador = IncapacidadProcessor(backend, extractor)

    resumen = {
        "procesados": 0,
        "fallidos": [],
        "sin_texto": [],
        "rutas": [],
        "campos_leidos": {"cedula": 0, "cie10": 0, "fecha_inicio": 0, "fecha_fin": 0, "dias": 0},
        "detalle": [],
    }

    for d in docs:
        etiqueta = d["etiqueta"]
        nombre = d["archivo"]
        ruta = BASE / "docs" / DOCS_DIR[etiqueta] / nombre
        salida_dir = BASE / "ocr" / etiqueta
        salida_dir.mkdir(parents=True, exist_ok=True)
        tallo = Path(nombre).stem
        print(f"  [{d['indice_global']:>2}] {etiqueta:<5} {nombre}", flush=True)

        if not ruta.exists():
            resumen["fallidos"].append({"archivo": nombre, "motivo": f"no existe: {ruta}"})
            continue

        # Señales estructurales: aunque fallen, el OCR debe continuar.
        try:
            est = senales_estructurales(ruta)
        except Exception as e:
            est = {"error": f"{type(e).__name__}: {e}", "traceback": traceback.format_exc()}
            print(f"        ! estructura fallo: {type(e).__name__}: {e}", flush=True)

        try:
            res = procesador.run(str(ruta))
        except Exception as e:
            resumen["fallidos"].append(
                {"archivo": nombre, "motivo": f"{type(e).__name__}: {e}"}
            )
            print(f"        ! OCR fallo: {type(e).__name__}: {e}", flush=True)
            traceback.print_exc()
            continue

        texto = res.get("texto_plano") or ""
        registro = res.get("incapacidad") or {}

        doc_json = {
            "archivo": nombre,
            "etiqueta": etiqueta,
            "ocr_backend": res.get("ocr_backend"),
            "extractor": res.get("extractor"),
            "texto_plano": texto,
            "incapacidad": registro,
            "estructura": est,
            # trazabilidad del shard (no es PII)
            "_meta": {
                "shard": SHARD,
                "indice_global": d["indice_global"],
                "sha256_manifest": d["sha256"],
                "cuarentena": d["cuarentena"],
                "motivo_cuarentena": d["motivo_cuarentena"],
                "aviso_pipeline": res.get("aviso"),
                "ruta_documento": str(ruta).replace("\\", "/"),
            },
        }
        ruta_json = salida_dir / f"{tallo}.json"
        ruta_txt = salida_dir / f"{tallo}.txt"
        ruta_json.write_text(
            json.dumps(doc_json, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
        )
        ruta_txt.write_text(texto, encoding="utf-8")

        resumen["procesados"] += 1
        resumen["rutas"].extend([str(ruta_json).replace("\\", "/"), str(ruta_txt).replace("\\", "/")])

        n_chars = len(texto.strip())
        n_lineas = len([l for l in texto.splitlines() if l.strip()])
        if n_chars < 40:
            resumen["sin_texto"].append({"archivo": nombre, "chars": n_chars})

        inc = registro.get("incapacidad") or {}
        pac = registro.get("paciente") or {}
        dx = registro.get("diagnostico") or {}
        presentes = {
            "cedula": pac.get("documento_numero") is not None,
            "cie10": dx.get("cie10") is not None,
            "fecha_inicio": inc.get("fecha_inicio") is not None,
            "fecha_fin": inc.get("fecha_fin") is not None,
            "dias": inc.get("dias") is not None,
        }
        for k, ok in presentes.items():
            if ok:
                resumen["campos_leidos"][k] += 1

        resumen["detalle"].append(
            {
                "archivo": nombre,
                "etiqueta": etiqueta,
                "chars": n_chars,
                "lineas": n_lineas,
                "tipo_documento": registro.get("tipo_documento"),
                "campos": presentes,
                "n_campos": sum(presentes.values()),
                "cuarentena": d["cuarentena"],
                "estructura_ok": "error" not in est,
                "es_escaneo_puro": est.get("es_escaneo_puro"),
                "n_fuentes": est.get("n_fuentes_distintas_documento"),
                "n_imagenes": est.get("n_imagenes_documento"),
                "eof_count": (est.get("generaciones") or {}).get("eof_count"),
            }
        )
        print(
            f"        ok chars={n_chars} lineas={n_lineas} campos={sum(presentes.values())}/5",
            flush=True,
        )

    ruta_resumen = BASE / "senales" / f"_resumen_shard{SHARD}.json"
    ruta_resumen.write_text(
        json.dumps(resumen, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print("\n=== RESUMEN (sin PII) ===")
    print(json.dumps({k: v for k, v in resumen.items() if k != "rutas"}, ensure_ascii=False, indent=2))
    print(f"\nresumen -> {ruta_resumen}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
