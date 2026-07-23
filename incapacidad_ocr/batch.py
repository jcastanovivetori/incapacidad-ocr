"""Ingesta masiva por lotes.

Escanea la carpeta de "sin procesar" (``INGESTA_ROOT/inbox``), agrupa los archivos de
un mismo trámite por la NOMENCLATURA del nombre  ``{cedula}_{TIPODOC}[_NN].{ext}`` (sin fecha),
OCR-ea SOLO el documento base (incapacidad/permiso/vacaciones), valida que estén los
soportes requeridos según el tipo de ausentismo, registra cada caso en la tabla STAGING
``lp_ausentismos_ia`` (estado PENDIENTE_REVISION) y mueve los archivos a ``procesados/`` o
``incompletos/`` (o ``cuarentena/`` si falla). Los adjuntos NO se OCR-ean: se identifican
por su ``TIPODOC`` en el nombre.

100% local. No se inserta en ``lpausentismos`` directo (el ERP promueve al aprobar).

Uso por CLI:   python -m incapacidad_ocr.batch [--extractor rule|hibrido] [--dry-run]
"""
from __future__ import annotations

import logging
import os
import re
import shutil
import unicodedata
from datetime import date
from pathlib import Path
from typing import Any, Optional

from . import db, erp
from .extract import HybridExtractor, OllamaLLMExtractor, RuleBasedExtractor, primer_nombre_apellido
from .processor import IncapacidadProcessor

log = logging.getLogger("incapacidad_ocr.batch")

# Raíz de la estructura de carpetas (bind mount en Docker; carpeta local fuera de Docker).
INGESTA_ROOT = Path(os.environ.get("INGESTA_ROOT", "/data/ingesta"))
INBOX = "inbox"
SIN_NOMENCLATURA = "sin_nomenclatura"
PROCESADOS = "procesados"
INCOMPLETOS = "incompletos"
CUARENTENA = "cuarentena"

EXT_OK = {".pdf", ".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff"}
TIPODOC_BASE = {"INCAPACIDAD", "PERMISO", "VACACIONES"}
# Sub-árbol del inbox → estado de recepción.
RECEPCION_POR_CARPETA = {"whatsapp": "WHATSAPP", "correo": "CORREO", "original": "ORIGINAL"}

# {cedula}_{TIPODOC}[_{NN}]  — sin fecha: se toma del documento (OCR). La llave de caso
# es la CÉDULA (todos los archivos de un empleado en el inbox = un trámite).
_RE_NOMBRE = re.compile(
    r"^(?P<cedula>\d{5,15})[_-](?P<tipo>[A-Za-zÑñ]+)(?:[_-](?P<nn>\d{1,3}))?$"
)


def parse_nombre(nombre: str) -> Optional[dict[str, Any]]:
    """Parsea el nombre del archivo según la nomenclatura ``cedula_TIPODOC[_NN]``. None si no cumple."""
    m = _RE_NOMBRE.match(Path(nombre).stem)
    if not m:
        return None
    return {
        "cedula": m.group("cedula"),
        "tipo": m.group("tipo").upper(),
        "nn": m.group("nn"),
        "caso": m.group("cedula"),   # agrupa por cédula (la fecha sale del OCR)
    }


def _sub(root: Path, *partes: str) -> Path:
    p = root.joinpath(*partes)
    p.mkdir(parents=True, exist_ok=True)
    return p


def _archivos_inbox(root: Path):
    """Itera (Path, recepcion) de los archivos del inbox (recursivo), saltando sin_nomenclatura."""
    inbox = root / INBOX
    if not inbox.is_dir():
        return
    for f in sorted(inbox.rglob("*")):
        if not f.is_file() or f.suffix.lower() not in EXT_OK:
            continue
        rel = f.relative_to(inbox)
        if rel.parts and rel.parts[0] == SIN_NOMENCLATURA:
            continue
        recepcion = "WHATSAPP"
        for parte in rel.parts:
            if parte.lower() in RECEPCION_POR_CARPETA:
                recepcion = RECEPCION_POR_CARPETA[parte.lower()]
                break
        yield f, recepcion


def escanear(root: Path) -> tuple[dict[str, list[dict]], list[Path]]:
    """Agrupa los archivos del inbox por caso (llave del nombre). Devuelve (casos, sin_nomenclatura)."""
    casos: dict[str, list[dict]] = {}
    sueltos: list[Path] = []
    for f, recepcion in _archivos_inbox(root):
        info = parse_nombre(f.name)
        if not info:
            sueltos.append(f)
            continue
        info["path"] = f
        info["recepcion"] = recepcion
        casos.setdefault(info["caso"], []).append(info)
    return casos, sueltos


def _sanit_carpeta(s: str) -> str:
    """Nombre seguro de carpeta (ASCII, sin caracteres inválidos, espacios simples)."""
    s = "".join(c for c in unicodedata.normalize("NFD", s or "") if unicodedata.category(c) != "Mn")
    s = re.sub(r'[\\/:*?"<>|]+', " ", s)
    s = re.sub(r"\s+", " ", s).strip(" .")
    return s[:60]


def _carpeta_persona(nombre: Optional[str], cedula: str) -> str:
    """Carpeta de la persona = 'PRIMER_NOMBRE PRIMER_APELLIDO' (del nombre del catálogo/OCR)."""
    base = _sanit_carpeta(primer_nombre_apellido(nombre) or "") if nombre else ""
    return base or f"SIN NOMBRE {cedula}"


def _partes_persona(subdir: str, nombre_persona: str, fecha_iso: Optional[str]) -> list[str]:
    """Ruta relativa organizada: <subdir>/<Nombre persona>/<AAAA>/<MM>/<DD>.

    La fecha es la de inicio de la incapacidad (ISO, del OCR/staging); si no se pudo leer,
    queda en 'sin_fecha' (el revisor la completa)."""
    y = m = d = None
    if fecha_iso and re.match(r"^\d{4}-\d{2}-\d{2}", fecha_iso):
        y, m, d = fecha_iso[:4], fecha_iso[5:7], fecha_iso[8:10]
    partes = [subdir, nombre_persona]
    partes += [p for p in (y or "sin_fecha", m, d) if p]
    return partes


def _mover(archivos: list[Path], destino: Path) -> None:
    destino.mkdir(parents=True, exist_ok=True)
    for f in archivos:
        try:
            shutil.move(str(f), str(destino / f.name))
        except Exception:  # noqa: BLE001 — un fallo de move no debe tumbar el lote
            log.exception("No se pudo mover %s", f.name)


def _construir_extractor(nombre: str):
    url = os.environ.get("OLLAMA_URL", "http://localhost:11434")
    if nombre == "hibrido":
        return HybridExtractor(OllamaLLMExtractor(base_url=url, model=os.environ.get("LLM_MODEL", "gemma3:4b")))
    if nombre == "ollama":
        return OllamaLLMExtractor(base_url=url, model=os.environ.get("LLM_MODEL", "gemma3:4b"))
    return RuleBasedExtractor()


def procesar_caso(caso: str, archivos: list[dict], ocr_backend, extractor, cx, lookups,
                  hoy: Optional[date] = None, dry_run: bool = False) -> dict[str, Any]:
    """Procesa un caso (grupo de archivos con la misma llave). Registra en staging y mueve."""
    root = INGESTA_ROOT
    cedula_nombre = archivos[0]["cedula"]
    recepcion = archivos[0]["recepcion"]
    presentes = {erp.canon_doc(a["tipo"]) for a in archivos}
    bases = [a for a in archivos if a["tipo"] in TIPODOC_BASE]
    base = bases[0] if bases else None

    if base is not None:
        result = IncapacidadProcessor(ocr_backend, extractor).run(base["path"])
        result["fuente"] = base["path"].name
    else:
        # Sin documento base: no hay qué OCR-ear. Se registra el caso como incompleto
        # (falta la incapacidad) usando la cédula del nombre.
        result = {"ocr_backend": getattr(ocr_backend, "name", "?"),
                  "extractor": getattr(extractor, "name", "?"),
                  "fuente": archivos[0]["path"].name, "incapacidad": {}}

    # Override: la cédula del NOMBRE respalda al OCR (no lo pisa si el OCR sí la leyó).
    # La FECHA NO viene en el nombre: sale del OCR/derivación del modelo.
    inc = (result.get("incapacidad") or {})
    pac = inc.get("paciente") or {}
    overrides: dict[str, Any] = {}
    if not pac.get("documento_numero"):
        overrides["cedula"] = cedula_nombre

    mapeo = erp.mapear_a_staging(result, recepcion, lookups, hoy=hoy,
                                 overrides=overrides, documentos_presentes=presentes)
    row = mapeo["row"]
    row["archivo_origen"] = (base or archivos[0])["path"].name

    problemas = list(mapeo["problemas"])
    # Cotejo de seguridad: cédula del nombre vs la leída por el OCR.
    ced_ocr = re.sub(r"\D", "", str(pac.get("documento_numero") or ""))
    mismatch = bool(ced_ocr) and ced_ocr != cedula_nombre
    if mismatch:
        problemas.append(f"Cédula del nombre ({cedula_nombre}) ≠ leída ({ced_ocr})")
    # Varios documentos base para la misma cédula → posibles trámites distintos juntos.
    if len(bases) > 1:
        problemas.append(f"Hay {len(bases)} documentos base para la cédula {cedula_nombre} "
                         "(¿trámites distintos?): revisar")
    if problemas != mapeo["problemas"]:
        row["problemas"] = "; ".join(problemas) or None

    requiere_revision = bool(problemas)
    doc_estado = row.get("documentacion_estado")
    completo = doc_estado == "COMPLETA" and not requiere_revision

    # Carpeta destino organizada por persona / año / mes / día (fecha = inicio de la
    # incapacidad leída por el OCR; si no se pudo leer, queda en 'sin_fecha').
    nombre_persona = _carpeta_persona(row.get("paciente_leido") or mapeo.get("paciente_catalogo"),
                                      cedula_nombre)
    subdir = PROCESADOS if completo else INCOMPLETOS
    partes = _partes_persona(subdir, nombre_persona, row.get("fechainicio"))

    resultado_caso = {
        "caso": caso, "cedula": cedula_nombre, "persona": nombre_persona,
        "archivos": [a["path"].name for a in archivos],
        "tiene_base": base is not None, "presentes": sorted(p for p in presentes if p),
        "tipo_ausentismo": mapeo.get("tipo_ausentismo"),
        "documentacion_estado": doc_estado, "faltantes": mapeo.get("documentos_faltantes"),
        "requiere_revision": requiere_revision, "problemas": problemas,
        "mismatch_cedula": mismatch, "id": None, "destino": "/".join(partes),
    }
    if dry_run:
        return resultado_caso

    new_id = db.insertar_staging(cx, row)
    resultado_caso["id"] = new_id

    # Alerta de documentación si el caso quedó incompleto.
    if doc_estado == "INCOMPLETA":
        with_ = ", ".join(mapeo.get("documentos_faltantes") or []) or "documentos requeridos"
        try:
            db.insertar_alerta(cx, {
                "id_ausentismo_ia": new_id, "idlpempleado": row.get("idlpempleado"),
                "cedula": cedula_nombre, "idlpentidad": row.get("idlpentidad"),
                "eps": row.get("eps_leida"),
                "documentos_faltantes": with_,
                "mensaje": f"Faltan soportes para el ausentismo del empleado {cedula_nombre}: {with_}.",
                "canal": recepcion, "estado": "PENDIENTE",
            })
        except Exception:  # noqa: BLE001
            log.exception("No se pudo crear la alerta del caso %s", caso)

    destino = _sub(root, *partes)
    _mover([a["path"] for a in archivos], destino)
    resultado_caso["destino"] = destino.relative_to(root).as_posix()
    return resultado_caso


def procesar_todo(ocr_backend, extractor_name: str = "rule", limite: int = 500,
                  dry_run: bool = False) -> dict[str, Any]:
    """Procesa TODOS los casos del inbox. Devuelve un resumen para la UI/CLI."""
    root = INGESTA_ROOT
    extractor = _construir_extractor(extractor_name)
    casos, sueltos = escanear(root)

    resumen: dict[str, Any] = {
        "root": str(root), "extractor": extractor_name,
        "casos_total": len(casos), "procesados": 0, "incompletos": 0, "cuarentena": 0,
        "sin_nomenclatura": len(sueltos), "detalle": [],
    }
    # Mueve los archivos mal nombrados a su bucket (no se procesan).
    if sueltos and not dry_run:
        _mover(sueltos, _sub(root, INBOX, SIN_NOMENCLATURA))

    if not casos:
        return resumen
    if not db.db_disponible():
        resumen["error"] = "Base de datos no disponible."
        return resumen

    hoy = date.today()
    with db.conexion_mysql() as cx:
        lookups = erp.Lookups(cx)
        for i, (caso, archivos) in enumerate(casos.items()):
            if i >= limite:
                break
            try:
                r = procesar_caso(caso, archivos, ocr_backend, extractor, cx, lookups, hoy, dry_run)
                if r["documentacion_estado"] == "COMPLETA" and not r["requiere_revision"]:
                    resumen["procesados"] += 1
                else:
                    resumen["incompletos"] += 1
                resumen["detalle"].append(r)
            except Exception as exc:  # noqa: BLE001 — un caso no debe tumbar el lote
                log.exception("Error procesando caso %s", caso)
                resumen["cuarentena"] += 1
                if not dry_run:
                    _mover([a["path"] for a in archivos], _sub(root, CUARENTENA, caso))
                resumen["detalle"].append({"caso": caso, "error": str(exc)[:200]})
    return resumen


def contar_pendientes() -> dict[str, Any]:
    """Cuenta lo que hay en el inbox (para el botón de la UI)."""
    root = INGESTA_ROOT
    con_nom = 0
    sin_nom = 0
    casos = set()
    for f, _recepcion in _archivos_inbox(root):
        info = parse_nombre(f.name)
        if info:
            con_nom += 1
            casos.add(info["caso"])
        else:
            sin_nom += 1
    return {"root": str(root), "archivos": con_nom + sin_nom, "con_nomenclatura": con_nom,
            "sin_nomenclatura": sin_nom, "casos": len(casos)}


def _main() -> None:
    import argparse
    import json

    from .ocr import get_ocr_backend

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    ap = argparse.ArgumentParser(description="Ingesta masiva de documentos de ausentismo.")
    ap.add_argument("--extractor", default="rule", choices=["rule", "hibrido", "ollama"])
    ap.add_argument("--ocr", default="rapidocr", choices=["rapidocr", "ollama"])
    ap.add_argument("--dry-run", action="store_true", help="No inserta ni mueve; solo reporta.")
    args = ap.parse_args()

    backend = get_ocr_backend(args.ocr)
    resumen = procesar_todo(backend, extractor_name=args.extractor, dry_run=args.dry_run)
    print(json.dumps(resumen, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    _main()
