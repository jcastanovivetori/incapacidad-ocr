"""Ingesta masiva por lotes.

Escanea la zona de entrada (``INGESTA_ROOT/1_entrada``), agrupa los archivos de
un mismo trámite por la NOMENCLATURA del nombre  ``{cedula}_{TIPODOC}[_NN].{ext}`` (sin fecha),
OCR-ea SOLO el documento base (incapacidad/permiso/vacaciones), valida que estén los
soportes requeridos según el tipo de ausentismo, registra cada caso en la tabla STAGING
``lp_ausentismos_ia`` (estado PENDIENTE_REVISION) y mueve los archivos a la zona que
corresponda (``3_archivo/`` si está completo, ``2_revisar/`` si necesita acción humana).
Los adjuntos NO se OCR-ean: se identifican por su ``TIPODOC`` en el nombre.

100% local. No se inserta en ``lpausentismos`` directo (el ERP promueve al aprobar).

Uso por CLI:   python -m incapacidad_ocr.batch [--extractor rule|hibrido] [--dry-run] [--init]
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

# --- Estructura de carpetas (documentada para RH en ``ingesta/LEEME.md``) ---------------
# Tres zonas NUMERADAS que se leen en orden de flujo, más un área interna:
#   1_entrada/   lo que deja el punto de recepción (contrato de entrada = la nomenclatura)
#   2_revisar/   lo que necesita ACCIÓN HUMANA (mal nombrados / faltan soportes / con error)
#   3_archivo/   historial de los casos COMPLETOS, por persona y fecha
#   _sistema/    logs y temporales del runner (nadie navega aquí)
# Cada archivo termina en EXACTAMENTE UNA de las tres zonas → "dónde está" es inequívoco.
ENTRADA = "1_entrada"
REVISAR = "2_revisar"
ARCHIVO = "3_archivo"
SISTEMA = "_sistema"
# Sub-carpetas de la zona de revisión: UNA POR MOTIVO, para que la carpeta diga por qué
# el caso está ahí (y qué hay que hacer). No mezclar motivos en la misma carpeta.
MAL_NOMBRADOS = "mal_nombrados"          # no cumplen la nomenclatura → no se pueden agrupar
FALTAN_SOPORTES = "faltan_soportes"      # documentación INCOMPLETA → hay que pedir un soporte
DATOS_POR_REVISAR = "datos_por_revisar"  # soportes completos, pero el OCR/lookups dejaron problemas
CON_ERROR = "con_error"                  # fallo técnico procesando el caso
LOGS = "logs"                        # dentro de _sistema
# Copia inmutable del corpus de prueba (dentro de _sistema): permite REPETIR una demo, porque
# procesar el lote mueve los archivos fuera de la entrada. Ver `reiniciar_prueba`.
SEMILLA = "semilla"
# Estructura ANTERIOR (inbox/ · procesados/ · incompletos/ · cuarentena/). Ya no se escribe
# ahí, pero la entrada se sigue LEYENDO para no dejar documentos huérfanos tras el cambio.
ENTRADA_LEGACY = "inbox"
LEGACY_EXCEPCION = "sin_nomenclatura"   # sub-árbol de descarte del inbox viejo

EXT_OK = {".pdf", ".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff"}
TIPODOC_BASE = {"INCAPACIDAD", "PERMISO", "VACACIONES"}
# Sub-árbol de la zona de entrada → estado de recepción ("original" se acepta como
# sinónimo de "ventanilla" por compatibilidad con el árbol anterior).
RECEPCION_POR_CARPETA = {"whatsapp": "WHATSAPP", "correo": "CORREO",
                         "ventanilla": "ORIGINAL", "original": "ORIGINAL"}
# Árbol completo que se crea de entrada (idempotente) — ver ``asegurar_estructura``.
ESTRUCTURA = (
    (ENTRADA, "whatsapp"), (ENTRADA, "correo"), (ENTRADA, "ventanilla"),
    (REVISAR, MAL_NOMBRADOS), (REVISAR, FALTAN_SOPORTES), (REVISAR, DATOS_POR_REVISAR),
    (REVISAR, CON_ERROR),
    (ARCHIVO,), (SISTEMA, LOGS), (SISTEMA, "tmp"), (SISTEMA, "control"),
)

# {cedula}_{TIPODOC}[_{NN}]  — sin fecha: se toma del documento (OCR). La llave de caso
# es la CÉDULA (todos los archivos de un empleado en la entrada = un trámite).
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


def asegurar_estructura(root: Optional[Path] = None) -> Path:
    """Crea el árbol de la ingesta (idempotente) para que RH lo encuentre ya armado."""
    root = root or INGESTA_ROOT
    for partes in ESTRUCTURA:
        _sub(root, *partes)
    return root


def _archivos_entrada(root: Path):
    """Itera (Path, recepcion) de los documentos de la zona de entrada (recursivo).

    Se recorre también el ``inbox/`` del árbol anterior si aún existe, para no dejar
    documentos sin procesar tras el cambio de estructura; en ese árbol se salta el
    sub-árbol de descarte (``sin_nomenclatura/``, ya revisado por una persona)."""
    for base, saltar in ((root / ENTRADA, None), (root / ENTRADA_LEGACY, LEGACY_EXCEPCION)):
        if not base.is_dir():
            continue
        for f in sorted(base.rglob("*")):
            if not f.is_file() or f.suffix.lower() not in EXT_OK:
                continue
            rel = f.relative_to(base)
            if saltar and rel.parts and rel.parts[0] == saltar:
                continue
            recepcion = "WHATSAPP"
            for parte in rel.parts:
                if parte.lower() in RECEPCION_POR_CARPETA:
                    recepcion = RECEPCION_POR_CARPETA[parte.lower()]
                    break
            yield f, recepcion


def escanear(root: Path) -> tuple[dict[str, list[dict]], list[Path]]:
    """Agrupa los documentos de la entrada por caso (llave del nombre).

    Devuelve ``(casos, mal_nombrados)``: los que no cumplen la nomenclatura no se
    pueden agrupar y salen aparte (van a ``2_revisar/mal_nombrados/``)."""
    casos: dict[str, list[dict]] = {}
    sueltos: list[Path] = []
    for f, recepcion in _archivos_entrada(root):
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


def _partes_destino(zona: list[str], nombre_persona: str, fecha_iso: Optional[str]) -> list[str]:
    """Ruta relativa organizada: <zona…>/<Nombre persona>/<AAAA>/<MM>/<DD>.

    ``zona`` es ``[ARCHIVO]`` (caso completo) o la sub-carpeta de ``2_revisar/`` del motivo.
    La fecha es la de inicio de la incapacidad (ISO, del OCR/staging); si no se pudo leer,
    queda en 'sin_fecha' (el revisor la completa)."""
    y = m = d = None
    if fecha_iso and re.match(r"^\d{4}-\d{2}-\d{2}", fecha_iso):
        y, m, d = fecha_iso[:4], fecha_iso[5:7], fecha_iso[8:10]
    partes = [*zona, nombre_persona]
    partes += [p for p in (y or "sin_fecha", m, d) if p]
    return partes


def _destino_libre(destino: Path, nombre: str) -> Path:
    """Ruta destino que NO existe, añadiendo `_dupNN` si hace falta.

    Nunca se sobre-escribe: dos archivos distintos pueden llegar con el mismo nombre (p.ej. la
    misma cédula entregada por dos canales), y perder uno en silencio significaría perder el
    soporte de una incapacidad. El plan (`PLAN_INGESTA_MASIVA.md` §4.4) lo exige explícitamente.
    """
    candidato = destino / nombre
    if not candidato.exists():
        return candidato
    stem, suf = Path(nombre).stem, Path(nombre).suffix
    for n in range(1, 100):
        alt = destino / f"{stem}_dup{n:02d}{suf}"
        if not alt.exists():
            return alt
    raise FileExistsError(f"Demasiadas colisiones de nombre para {nombre}")


def _mover(archivos: list[Path], destino: Path) -> None:
    destino.mkdir(parents=True, exist_ok=True)
    for f in archivos:
        try:
            final = _destino_libre(destino, f.name)
            if final.name != f.name:
                log.warning("Colisión de nombre en %s: %s se guarda como %s",
                            destino.name, f.name, final.name)
            shutil.move(str(f), str(final))
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

    # Zona destino + carpeta por persona / año / mes / día (fecha = inicio de la
    # incapacidad leída por el OCR; si no se pudo leer, queda en 'sin_fecha').
    # La sub-carpeta de revisión se elige por el MOTIVO, no por "no está completo":
    # falta un soporte (hay que pedirlo) ≠ los soportes están y el dato necesita revisión.
    nombre_persona = _carpeta_persona(row.get("paciente_leido") or mapeo.get("paciente_catalogo"),
                                      cedula_nombre)
    if completo:
        zona = [ARCHIVO]
    elif doc_estado == "INCOMPLETA":
        zona = [REVISAR, FALTAN_SOPORTES]
    else:
        zona = [REVISAR, DATOS_POR_REVISAR]
    partes = _partes_destino(zona, nombre_persona, row.get("fechainicio"))

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
    """Procesa TODOS los casos de la entrada. Devuelve un resumen para la UI/CLI.

    Las claves del resumen nombran las carpetas del árbol: ``completos`` → ``3_archivo/``;
    ``faltan_soportes``/``datos_por_revisar``/``con_error``/``mal_nombrados`` → sub-carpetas
    de ``2_revisar/``."""
    root = INGESTA_ROOT
    if not dry_run:
        asegurar_estructura(root)
    extractor = _construir_extractor(extractor_name)
    casos, sueltos = escanear(root)

    resumen: dict[str, Any] = {
        "root": str(root), "extractor": extractor_name,
        "casos_total": len(casos), "completos": 0, "faltan_soportes": 0,
        "datos_por_revisar": 0, "con_error": 0,
        "mal_nombrados": len(sueltos), "detalle": [],
    }
    # Los mal nombrados no se pueden agrupar → van a la zona de revisión (no se procesan).
    if sueltos and not dry_run:
        _mover(sueltos, _sub(root, REVISAR, MAL_NOMBRADOS))

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
                    resumen["completos"] += 1
                elif r["documentacion_estado"] == "INCOMPLETA":
                    resumen["faltan_soportes"] += 1
                else:
                    resumen["datos_por_revisar"] += 1
                resumen["detalle"].append(r)
            except Exception as exc:  # noqa: BLE001 — un caso no debe tumbar el lote
                log.exception("Error procesando caso %s", caso)
                resumen["con_error"] += 1
                if not dry_run:
                    _mover([a["path"] for a in archivos], _sub(root, REVISAR, CON_ERROR, caso))
                resumen["detalle"].append({"caso": caso, "error": str(exc)[:200]})
    return resumen


def _documentos_en(base: Path) -> list[Path]:
    """Documentos (por extensión) que hay bajo `base`, recursivo. Ignora los `.gitkeep`."""
    if not base.is_dir():
        return []
    return [f for f in sorted(base.rglob("*")) if f.is_file() and f.suffix.lower() in EXT_OK]


def _podar_vacias(base: Path) -> int:
    """Borra las subcarpetas que quedaron vacías bajo `base` (no borra `base`)."""
    n = 0
    if not base.is_dir():
        return n
    for d in sorted((p for p in base.rglob("*") if p.is_dir()), reverse=True):
        if not any(d.iterdir()):
            d.rmdir()
            n += 1
    return n


def reiniciar_prueba(root: Optional[Path] = None, limpiar_bd: bool = True) -> dict[str, Any]:
    """Devuelve los documentos a ``1_entrada/`` para volver a correr el lote sobre lo mismo.

    Es el respaldo del botón «Reiniciar prueba» de la UI: procesar un lote MUEVE los archivos
    fuera de la entrada, así que sin esto una demo solo se puede hacer una vez.

    Dos modos, y el que aplica depende de si hay semilla:

    * **Con semilla** (``_sistema/semilla/<canal>/…``, la crea ``scripts/sembrar_prueba_falsedad.py``):
      se restaura el estado inicial EXACTO — se descartan los documentos que haya en las tres
      zonas y se vuelve a copiar la semilla, conservando el canal de cada archivo (y con él el
      `estado_recepcion`). Es el modo repetible: la prueba arranca siempre igual.
    * **Sin semilla:** modo conservador de solo-movimiento. Se devuelve a ``1_entrada/whatsapp/``
      lo que haya en ``2_revisar/`` y ``3_archivo/``. NO se borra nada. Se pierde el canal
      original (todo queda como WHATSAPP) porque el árbol de salida no lo registra.

    El modo destructivo exige semilla a propósito: sin ella no hay forma de reconstruir lo que se
    borre, y esta misma función podría acabar ejecutándose contra una carpeta de producción.

    ``limpiar_bd`` borra además las filas de staging PENDIENTE_REVISION de esos archivos
    (``db.eliminar_staging_por_archivos``), para que el lote no las duplique al repetirse. Lo ya
    aprobado o rechazado por un auxiliar no se toca nunca.
    """
    root = root or INGESTA_ROOT
    asegurar_estructura(root)
    entrada = root / ENTRADA
    semilla = root / SISTEMA / SEMILLA
    docs_semilla = _documentos_en(semilla)
    salidas = [root / REVISAR, root / ARCHIVO]

    resumen: dict[str, Any] = {
        "root": str(root), "modo": "semilla" if docs_semilla else "movimiento",
        "restaurados": 0, "descartados": 0, "carpetas_podadas": 0,
        "archivos": [], "bd": {"staging": 0, "alertas": 0}, "avisos": [],
    }

    if docs_semilla:
        # Estado inicial exacto: fuera lo que haya en las tres zonas, dentro la semilla.
        for base in [entrada, *salidas]:
            for f in _documentos_en(base):
                f.unlink()
                resumen["descartados"] += 1
        for f in docs_semilla:
            rel = f.relative_to(semilla)          # <canal>/<archivo> (puede traer subcarpetas)
            destino = entrada / rel
            destino.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(str(f), str(destino))
            resumen["restaurados"] += 1
            resumen["archivos"].append(f.name)
    else:
        pendientes = [f for base in salidas for f in _documentos_en(base)]
        if not pendientes:
            resumen["avisos"].append(
                "No hay semilla ni documentos en las zonas de salida: no había nada que reiniciar.")
        destino = _sub(root, ENTRADA, "whatsapp")
        for f in pendientes:
            if (destino / f.name).exists():
                resumen["avisos"].append(f"{f.name}: ya existía en la entrada, se deja donde está.")
                continue
            shutil.move(str(f), str(destino / f.name))
            resumen["restaurados"] += 1
            resumen["archivos"].append(f.name)
        if pendientes:
            resumen["avisos"].append(
                "Sin semilla: los documentos vuelven a 1_entrada/whatsapp y se pierde el canal "
                "original (el estado de recepción quedará WHATSAPP).")

    for base in salidas:
        resumen["carpetas_podadas"] += _podar_vacias(base)

    if limpiar_bd and resumen["archivos"]:
        if db.db_disponible():
            try:
                with db.conexion_mysql() as cx:
                    resumen["bd"] = db.eliminar_staging_por_archivos(cx, resumen["archivos"])
            except Exception as exc:  # noqa: BLE001 — el reinicio de archivos ya se hizo; no se pierde
                log.exception("Reinicio: no se pudo limpiar la BD")
                resumen["avisos"].append(f"No se pudo limpiar la BD: {str(exc)[:120]}")
        else:
            resumen["avisos"].append("BD no disponible: las filas de staging anteriores siguen ahí.")
    return resumen


def contar_pendientes() -> dict[str, Any]:
    """Cuenta lo que espera en la zona de entrada (para el botón de la UI)."""
    root = INGESTA_ROOT
    con_nom = 0
    sin_nom = 0
    casos = set()
    for f, _recepcion in _archivos_entrada(root):
        info = parse_nombre(f.name)
        if info:
            con_nom += 1
            casos.add(info["caso"])
        else:
            sin_nom += 1
    return {"root": str(root), "entrada": ENTRADA, "archivos": con_nom + sin_nom,
            "con_nomenclatura": con_nom, "mal_nombrados": sin_nom, "casos": len(casos)}


def _main() -> None:
    import argparse
    import json

    from .ocr import get_ocr_backend

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    ap = argparse.ArgumentParser(description="Ingesta masiva de documentos de ausentismo.")
    ap.add_argument("--extractor", default="rule", choices=["rule", "hibrido", "ollama"])
    ap.add_argument("--ocr", default="rapidocr", choices=["rapidocr", "ollama"])
    ap.add_argument("--dry-run", action="store_true", help="No inserta ni mueve; solo reporta.")
    ap.add_argument("--init", action="store_true",
                    help="Solo crea el árbol de carpetas de la ingesta y termina.")
    ap.add_argument("--reiniciar", action="store_true",
                    help="Devuelve los documentos a 1_entrada para repetir la prueba, y termina.")
    ap.add_argument("--conservar-bd", action="store_true",
                    help="Con --reiniciar: NO borra las filas de staging pendientes de esos archivos.")
    args = ap.parse_args()

    if args.reiniciar:
        print(json.dumps(reiniciar_prueba(limpiar_bd=not args.conservar_bd),
                         ensure_ascii=False, indent=2))
        return

    if args.init:
        root = asegurar_estructura()
        print(json.dumps({"root": str(root),
                          "creado": ["/".join(p) for p in ESTRUCTURA]}, ensure_ascii=False, indent=2))
        return

    backend = get_ocr_backend(args.ocr)
    resumen = procesar_todo(backend, extractor_name=args.extractor, dry_run=args.dry_run)
    print(json.dumps(resumen, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    _main()
