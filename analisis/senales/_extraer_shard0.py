"""Extraccion OCR + señales estructurales del corpus de falsedad — SHARD 0 de 4.

100% LOCAL: RapidOCR (ONNX/CPU) + pypdfium2 + Pillow. Ninguna llamada de red.

Que hace
--------
1. Lee `manifest.csv`, ordena por (etiqueta, archivo) y se queda con los indices
   globales i tales que ``i % NSHARDS == SHARD``. El orden es el mismo para los 4
   shards, asi que la particion es estable y sin solapes.
2. Por documento: OCR + extraccion con el pipeline del repo hermano
   (`IncapacidadProcessor(RapidOCRBackend, RuleBasedExtractor)`). El backend se
   construye UNA vez (cargar los modelos ONNX es lo caro).
3. Por documento: señales ESTRUCTURALES (materia prima de las familias
   TIPOGRAFIA_MIXTA y FIRMA_MEDICO):
     - metadatos del PDF (Producer/Creator/CreationDate/ModDate...), version, id
     - numero de paginas y tamaño de pagina
     - por pagina: conteo de objetos por tipo (texto/imagen/path/forma/shading),
       NOMBRES DE FUENTES usadas (base/familia/peso/embebida) y tamaños de fuente
     - runs de texto (fuente + tamaño + bbox + texto) → permite ver si un campo
       concreto quedo en una fuente distinta al resto del formulario
     - sha256 de cada imagen embebida, en dos variantes:
         * del stream crudo (detecta copia byte a byte)
         * de los pixeles normalizados a RGB (detecta la MISMA firma recomprimida)
     - 'incremental updates': conteo de '%%EOF' / 'startxref' en los bytes crudos
       (heuristica barata: >1 generacion = el PDF fue reescrito encima)
   Para JPEG (no hay estructura PDF) se recogen las señales equivalentes de imagen:
   EXIF, tablas de cuantizacion JPEG (hash), ICC, progresivo, numero de SOI.
4. Escribe `ocr/<clase>/<nombre-sin-ext>.json` y `.txt`.

PII: los artefactos de salida CONTIENEN PII de salud (Ley 1581) y se quedan en
disco. El resumen que imprime este script solo lleva conteos y nombres de archivo.

Uso:
    <repo>/.venv/Scripts/python.exe \
      <dataset-falsedad>/senales/_extraer_shard0.py
"""
from __future__ import annotations

import csv
import hashlib
import json
import re
import sys
import traceback
from collections import Counter
from datetime import datetime
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

SHARD = 0
NSHARDS = 4

# El manifest usa etiqueta singular ('falsa'/'real'); las carpetas de docs/ usan
# plural. La salida espeja docs/ para que el arbol sea uno solo y navegable.
CARPETA = {"falsa": "falsas", "real": "reales"}

# Tope de pixeles para hashear una imagen embebida (protege RAM).
MAX_PX_HASH = 25_000_000
# Tope de runs de texto que se guardan por pagina (los formularios reales rondan 200).
MAX_RUNS = 4000

sys.path.insert(0, REPO)

from incapacidad_ocr.extract import RuleBasedExtractor  # noqa: E402
from incapacidad_ocr.ocr import get_ocr_backend  # noqa: E402
from incapacidad_ocr.processor import IncapacidadProcessor  # noqa: E402


# --------------------------------------------------------------------------- utils
def sha256_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def parse_fecha_pdf(v: str | None) -> str | None:
    """'D:20260715210250-05'00'' → ISO-8601. None si no se puede parsear."""
    if not v:
        return None
    m = re.match(r"D?:?(\d{4})(\d{2})?(\d{2})?(\d{2})?(\d{2})?(\d{2})?", v.strip())
    if not m:
        return None
    y, mo, d, h, mi, s = (int(x) if x else None for x in m.groups())
    try:
        dt = datetime(y, mo or 1, d or 1, h or 0, mi or 0, s or 0)
    except ValueError:
        return None
    iso = dt.isoformat()
    tz = re.search(r"([+-]\d{2})'?(\d{2})'?$|Z$", v.strip())
    if tz:
        iso += "Z" if tz.group(0) == "Z" else f"{tz.group(1)}:{tz.group(2)}"
    return iso


def señales_crudas(data: bytes) -> dict:
    """Heuristicas sobre los BYTES del PDF (no requieren parsear el documento)."""
    eofs = data.count(b"%%EOF")
    return {
        "eof_markers": eofs,
        "startxref_markers": data.count(b"startxref"),
        # >1 %%EOF ≈ el PDF tiene mas de una generacion (incremental update):
        # alguien lo abrio y lo volvio a guardar encima.
        "incremental_updates_probables": max(0, eofs - 1),
        "linearizado": b"/Linearized" in data[:4096],
        "tiene_xref_stream": b"/XRef" in data,
        "tiene_objstm": b"/ObjStm" in data,
        "tiene_xmp": b"<x:xmpmeta" in data or b"/Metadata" in data,
        "tiene_anotaciones": b"/Annots" in data,
        "tiene_firma_digital": b"/Sig" in data and b"/ByteRange" in data,
        "tiene_javascript": b"/JavaScript" in data or b"/JS" in data,
        "tiene_cifrado": b"/Encrypt" in data,
    }


def _sanear(v):
    """Deja el valor serializable y acotado (los blobs binarios no van al JSON)."""
    if isinstance(v, bytes):
        return f"<{len(v)} bytes sha256={sha256_bytes(v)[:16]}>"
    if isinstance(v, (int, float, bool)) or v is None:
        return v
    s = str(v)
    return s if len(s) <= 300 else s[:300] + "…"


# ---------------------------------------------------------------------- estructura
def estructura_pdf(path: Path, data: bytes) -> dict:
    import pypdfium2 as pdfium
    import pypdfium2.raw as raw

    TIPOS = {
        raw.FPDF_PAGEOBJ_UNKNOWN: "desconocido",
        raw.FPDF_PAGEOBJ_TEXT: "texto",
        raw.FPDF_PAGEOBJ_PATH: "path",
        raw.FPDF_PAGEOBJ_IMAGE: "imagen",
        raw.FPDF_PAGEOBJ_SHADING: "shading",
        raw.FPDF_PAGEOBJ_FORM: "forma",
    }

    est: dict = {"tipo_archivo": "pdf", "notas": []}
    est["bytes_crudos"] = señales_crudas(data)

    pdf = pdfium.PdfDocument(str(path))
    try:
        try:
            est["pdf_version"] = pdf.get_version()
        except Exception as e:  # noqa: BLE001
            est["pdf_version"] = None
            est["notas"].append(f"get_version no disponible: {type(e).__name__}")
        try:
            est["identificador"] = (pdf.get_identifier() or b"").hex() or None
        except Exception as e:  # noqa: BLE001
            est["identificador"] = None
            est["notas"].append(f"get_identifier no disponible: {type(e).__name__}")
        try:
            est["etiquetado"] = bool(pdf.is_tagged())
        except Exception as e:  # noqa: BLE001
            est["etiquetado"] = None
            est["notas"].append(f"is_tagged no disponible: {type(e).__name__}")
        try:
            est["formulario_acroform"] = pdf.get_formtype()
        except Exception as e:  # noqa: BLE001
            est["formulario_acroform"] = None
            est["notas"].append(f"get_formtype no disponible: {type(e).__name__}")

        meta = {}
        for k in pdfium.PdfDocument.METADATA_KEYS:
            try:
                v = pdf.get_metadata_value(k)
            except Exception:  # noqa: BLE001
                v = None
            meta[k] = v or None
        est["metadatos"] = meta
        creac, modif = parse_fecha_pdf(meta.get("CreationDate")), parse_fecha_pdf(meta.get("ModDate"))
        est["fechas"] = {
            "creacion": creac,
            "modificacion": modif,
            # Producido y modificado en el mismo instante = generado de una sola pasada.
            # Fechas distintas (o ModDate < CreationDate) = el archivo se retoco.
            "difieren": bool(creac and modif and creac != modif),
            "modificacion_anterior_a_creacion": bool(creac and modif and modif < creac),
        }

        total = len(pdf)
        est["paginas_total"] = total
        paginas = []
        fuentes_doc: Counter = Counter()
        img_hashes: list[str] = []
        for i in range(total):
            page = pdf[i]
            p: dict = {"indice": i}
            try:
                w, h = page.get_size()
                p["ancho_pt"], p["alto_pt"] = round(w, 2), round(h, 2)
            except Exception as e:  # noqa: BLE001
                p["ancho_pt"] = p["alto_pt"] = None
                p["nota"] = f"get_size fallo: {type(e).__name__}"
            try:
                p["rotacion"] = page.get_rotation()
            except Exception:  # noqa: BLE001
                p["rotacion"] = None

            conteo: Counter = Counter()
            fuentes: Counter = Counter()
            tam_fuente: Counter = Counter()
            runs: list[dict] = []
            imagenes: list[dict] = []
            errores_obj = 0
            # `PdfTextObj.extract()` exige que el objeto traiga un textpage asociado;
            # se pasa UNA vez por pagina (crearlo por objeto seria carisimo).
            try:
                tp = page.get_textpage()
            except Exception as e:  # noqa: BLE001
                tp = None
                est["notas"].append(f"get_textpage fallo en pagina {i}: {type(e).__name__}")
            for obj in page.get_objects(textpage=tp):
                tipo = TIPOS.get(obj.type, f"tipo_{obj.type}")
                conteo[tipo] += 1
                try:
                    if obj.type == raw.FPDF_PAGEOBJ_TEXT:
                        f = obj.get_font()
                        base = f.get_base_name()
                        clave = (base, f.get_family_name(), f.get_weight(), bool(f.is_embedded))
                        fuentes[clave] += 1
                        fuentes_doc[clave] += 1
                        tam = round(obj.get_font_size(), 2)
                        tam_fuente[tam] += 1
                        if len(runs) < MAX_RUNS and tp is not None:
                            txt = obj.extract()
                            if txt and txt.strip():
                                runs.append({
                                    "fuente": base,
                                    "tam": tam,
                                    "bbox": [round(x, 1) for x in obj.get_bounds()],
                                    "texto": txt,
                                })
                    elif obj.type == raw.FPDF_PAGEOBJ_IMAGE:
                        imagenes.append(info_imagen(obj, img_hashes))
                except Exception:  # noqa: BLE001
                    errores_obj += 1

            p["n_objetos_total"] = sum(conteo.values())
            p["objetos_por_tipo"] = dict(conteo)
            p["n_texto"] = conteo.get("texto", 0)
            p["n_imagen"] = conteo.get("imagen", 0)
            p["fuentes"] = [
                {"base": b, "familia": fa, "peso": pe, "embebida": em, "n_objetos": n}
                for (b, fa, pe, em), n in sorted(fuentes.items(), key=lambda kv: -kv[1])
            ]
            p["n_fuentes_distintas"] = len(fuentes)
            p["nombres_fuentes"] = sorted({b for (b, _, _, _) in fuentes})
            p["tamanos_fuente"] = {str(k): v for k, v in sorted(tam_fuente.items())}
            p["n_tamanos_fuente_distintos"] = len(tam_fuente)
            # Sin objetos de texto = pagina puramente rasterizada (escaneo/foto pegada).
            p["capa_texto"] = conteo.get("texto", 0) > 0
            p["runs_texto"] = runs
            p["runs_truncados"] = len(runs) >= MAX_RUNS
            p["imagenes"] = imagenes
            p["errores_objetos"] = errores_obj
            paginas.append(p)

        est["paginas"] = paginas
        est["paginas_analizadas"] = len(paginas)
        est["resumen_fuentes"] = [
            {"base": b, "familia": fa, "peso": pe, "embebida": em, "n_objetos": n}
            for (b, fa, pe, em), n in sorted(fuentes_doc.items(), key=lambda kv: -kv[1])
        ]
        est["n_fuentes_distintas_doc"] = len(fuentes_doc)
        est["nombres_fuentes_doc"] = sorted({b for (b, _, _, _) in fuentes_doc})
        est["n_imagenes_doc"] = sum(p["n_imagen"] for p in paginas)
        est["sha256_imagenes_doc"] = img_hashes
        est["tamanos_pagina_distintos"] = sorted({
            (p["ancho_pt"], p["alto_pt"]) for p in paginas if p["ancho_pt"]
        })
        est["tamanos_pagina_distintos"] = [list(t) for t in est["tamanos_pagina_distintos"]]
    finally:
        pdf.close()
    return est


def info_imagen(obj, img_hashes: list[str]) -> dict:
    """Señales de una imagen embebida. El sha256 de pixeles es la llave para
    detectar una MISMA firma reutilizada entre documentos (aunque se recomprima)."""
    import hashlib as _h

    info: dict = {}
    try:
        info["px"] = list(obj.get_px_size())
    except Exception as e:  # noqa: BLE001
        info["px"] = None
        info["nota_px"] = type(e).__name__
    try:
        info["filtros"] = list(obj.get_filters())
    except Exception:  # noqa: BLE001
        info["filtros"] = None
    try:
        info["bbox"] = [round(x, 1) for x in obj.get_bounds()]
    except Exception:  # noqa: BLE001
        info["bbox"] = None
    try:
        m = obj.get_metadata()
        info["bits_por_pixel"] = m.bits_per_pixel
        info["dpi"] = [round(m.horizontal_dpi, 2), round(m.vertical_dpi, 2)]
        info["colorspace"] = m.colorspace
    except Exception as e:  # noqa: BLE001
        info["nota_metadata"] = type(e).__name__
    try:
        crudo = obj.get_data(decode_simple=False)
        info["bytes_stream"] = len(crudo)
        info["sha256_stream"] = sha256_bytes(crudo)
    except Exception as e:  # noqa: BLE001
        info["sha256_stream"] = None
        info["nota_stream"] = type(e).__name__
    px = info.get("px") or [0, 0]
    if px[0] * px[1] and px[0] * px[1] <= MAX_PX_HASH:
        try:
            pil = obj.get_bitmap(render=False).to_pil().convert("RGB")
            info["sha256_pixeles"] = _h.sha256(pil.tobytes()).hexdigest()
        except Exception as e:  # noqa: BLE001
            info["sha256_pixeles"] = None
            info["nota_pixeles"] = type(e).__name__
    else:
        info["sha256_pixeles"] = None
        info["nota_pixeles"] = "imagen demasiado grande para hashear pixeles"
    if info.get("sha256_pixeles"):
        img_hashes.append(info["sha256_pixeles"])
    return info


def estructura_imagen(path: Path, data: bytes) -> dict:
    """Equivalente de las señales estructurales cuando el documento es un JPEG/PNG."""
    from PIL import ExifTags, Image

    est: dict = {"tipo_archivo": "imagen", "notas": [
        "No es un PDF: no hay metadatos de productor, objetos de pagina ni fuentes; "
        "las señales analogas son EXIF/tablas de cuantizacion/recompresion."
    ]}
    est["bytes_crudos"] = {
        # Varios SOI = la imagen trae miniatura(s) embebida(s) (EXIF thumbnail).
        "jpeg_soi_markers": data.count(b"\xff\xd8\xff"),
        "tiene_exif": b"Exif\x00\x00" in data[:65536],
        "tiene_xmp": b"<x:xmpmeta" in data,
        "tiene_icc": b"ICC_PROFILE" in data,
        "tiene_photoshop_irb": b"Photoshop 3.0" in data,
    }
    with Image.open(path) as img:
        est["formato"] = img.format
        est["modo"] = img.mode
        est["ancho_px"], est["alto_px"] = img.size
        est["paginas_total"] = getattr(img, "n_frames", 1)
        est["paginas_analizadas"] = 1
        est["info"] = {k: _sanear(v) for k, v in img.info.items() if k != "exif"}
        q = getattr(img, "quantization", None)
        if q:
            # Las tablas de cuantizacion identifican al ENCODER (camara vs Photoshop
            # vs libjpeg) y delatan una recompresion: firma barata y muy estable.
            est["quantization_tables"] = {
                # se hashea la representacion textual: los valores pueden ser de 16
                # bits (tablas de alta calidad) y no caben en un bytearray.
                str(k): {"n": len(v), "sha256": sha256_bytes(repr(list(v)).encode())}
                for k, v in q.items()
            }
        else:
            est["quantization_tables"] = None
        try:
            exif = img.getexif()
            est["exif"] = {
                ExifTags.TAGS.get(t, str(t)): _sanear(v) for t, v in exif.items()
            } or None
        except Exception as e:  # noqa: BLE001
            est["exif"] = None
            est["notas"].append(f"EXIF no legible: {type(e).__name__}")
        est["sha256_pixeles"] = sha256_bytes(img.convert("RGB").tobytes())
    est["n_imagenes_doc"] = 1
    est["sha256_imagenes_doc"] = [est["sha256_pixeles"]]
    est["nombres_fuentes_doc"] = []
    est["n_fuentes_distintas_doc"] = 0
    return est


# --------------------------------------------------------------------------- main
def main() -> int:
    filas = list(csv.DictReader(MANIFEST.open(encoding="utf-8")))
    filas.sort(key=lambda r: (r["etiqueta"], r["archivo"]))
    mios = [(i, r) for i, r in enumerate(filas) if i % NSHARDS == SHARD]
    print(f"corpus={len(filas)}  shard={SHARD}/{NSHARDS}  me tocan={len(mios)}", flush=True)

    proc = IncapacidadProcessor(get_ocr_backend("rapidocr"), RuleBasedExtractor())
    print("backend rapidocr listo", flush=True)

    campos = Counter()
    fallidos: list[str] = []
    sin_texto: list[str] = []
    rutas: list[str] = []
    resumen: list[dict] = []

    for i, fila in mios:
        nombre = fila["archivo"]
        etiqueta = fila["etiqueta"]
        clase = CARPETA[etiqueta]
        src = DOCS / clase / nombre
        dest_dir = OUT / clase
        dest_dir.mkdir(parents=True, exist_ok=True)
        stem = Path(nombre).stem
        print(f"[{i}] {clase}/{nombre}", flush=True)
        try:
            data = src.read_bytes()
            res = proc.run(src)
            texto = res.get("texto_plano") or ""
            rec = res.get("incapacidad") or {}
            if src.suffix.lower() == ".pdf":
                est = estructura_pdf(src, data)
            else:
                est = estructura_imagen(src, data)
            est["sha256_archivo"] = sha256_bytes(data)
            est["bytes"] = len(data)
            est["ext"] = src.suffix.lower().lstrip(".")

            doc = {
                "archivo": nombre,
                "etiqueta": etiqueta,
                "cuarentena": fila.get("cuarentena"),
                "motivo_cuarentena": fila.get("motivo_cuarentena") or None,
                "indice_corpus": i,
                "shard": SHARD,
                "ocr_backend": res.get("ocr_backend"),
                "extractor": res.get("extractor"),
                "texto_plano": texto,
                "incapacidad": rec,
                "estructura": est,
            }
            if res.get("aviso"):
                doc["aviso"] = res["aviso"]

            jpath = dest_dir / f"{stem}.json"
            tpath = dest_dir / f"{stem}.txt"
            jpath.write_text(json.dumps(doc, ensure_ascii=False, indent=1), encoding="utf-8")
            tpath.write_text(texto, encoding="utf-8")
            rutas += [str(jpath).replace("\\", "/"), str(tpath).replace("\\", "/")]

            inc = rec.get("incapacidad") or {}
            leidos = {
                "cedula": (rec.get("paciente") or {}).get("documento_numero"),
                "cie10": (rec.get("diagnostico") or {}).get("cie10"),
                "fecha_inicio": inc.get("fecha_inicio"),
                "fecha_fin": inc.get("fecha_fin"),
                "dias": inc.get("dias"),
            }
            for k, v in leidos.items():
                if v not in (None, ""):
                    campos[k] += 1
            if len(texto.strip()) < 200:
                sin_texto.append(nombre)
            resumen.append({
                "archivo": nombre, "etiqueta": etiqueta, "chars": len(texto),
                "campos": {k: v is not None and v != "" for k, v in leidos.items()},
                "fuentes": est.get("n_fuentes_distintas_doc"),
                "imgs": est.get("n_imagenes_doc"),
                "eof": (est.get("bytes_crudos") or {}).get("eof_markers"),
            })
            print(f"     chars={len(texto)} campos={sum(1 for v in leidos.values() if v not in (None,''))}/5"
                  f" fuentes={est.get('n_fuentes_distintas_doc')} imgs={est.get('n_imagenes_doc')}", flush=True)
        except Exception as e:  # noqa: BLE001
            fallidos.append(f"{nombre}: {type(e).__name__}: {e}")
            print(f"     FALLO {type(e).__name__}: {e}", flush=True)
            traceback.print_exc()

    print("\n===== RESUMEN (sin PII) =====")
    print("procesados:", len(mios) - len(fallidos), "de", len(mios))
    print("campos_leidos:", json.dumps(dict(campos), ensure_ascii=False))
    print("fallidos:", json.dumps(fallidos, ensure_ascii=False))
    print("texto_escaso(<200 chars):", json.dumps(sin_texto, ensure_ascii=False))
    print("detalle:", json.dumps(resumen, ensure_ascii=False, indent=1))
    print("rutas:", json.dumps(rutas, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
