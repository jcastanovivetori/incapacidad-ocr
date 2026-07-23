"""Servicio web: sube una incapacidad (imagen/PDF) → texto plano + JSON estructurado.

API FastAPI + UI estática (una sola página). El backend de OCR (RapidOCR) se carga
UNA vez al arrancar y se reutiliza entre peticiones (cargar los modelos ONNX es lo caro).

Privacidad (Ley 1581): los archivos subidos se procesan en un temporal y se BORRAN
de inmediato; nada se persiste ni se envía a servicios externos.

    uvicorn incapacidad_ocr.webapp:app --host 0.0.0.0 --port 8000
"""
from __future__ import annotations

import contextlib
import logging
import os
import tempfile
import threading
from pathlib import Path

from fastapi import Body, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse

from . import batch, db, erp
from .extract import HybridExtractor, OllamaLLMExtractor, RuleBasedExtractor
from .ocr import OllamaError, OllamaVisionOCR, get_ocr_backend
from .processor import IncapacidadProcessor

logger = logging.getLogger("incapacidad_ocr.webapp")

STATIC_DIR = Path(__file__).resolve().parent / "static"
ALLOWED_SUFFIXES = {".pdf", ".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff"}
MAX_BYTES = int(os.environ.get("MAX_UPLOAD_BYTES", 50 * 1024 * 1024))  # 50 MB por defecto
MAX_MB = MAX_BYTES // (1024 * 1024)

# --- Configuración de Ollama: SOLO desde el entorno del servidor (no del cliente).
#     El cliente NO puede elegir la URL ni el modelo → evita SSRF (que un atacante
#     apunte el servidor a una URL interna) y el uso de modelos arbitrarios.
DEFAULT_OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434")
OCR_MODEL = os.environ.get("OCR_MODEL", "qwen2.5vl:3b")  # VLM que SÍ transcribe (no moondream)
LLM_MODEL = os.environ.get("LLM_MODEL", "gemma3:4b")

VALID_OCR = {"rapidocr", "ollama"}
VALID_EXTRACTOR = {"rule", "ollama", "hibrido"}
VALID_RECEPCION = {"ORIGINAL", "WHATSAPP", "CORREO"}

# --- Corrida programada de la ingesta por lotes (cron in-process, opcional).
#     INGESTA_CRON vacío = desactivada. La lógica corre en contenedores Linux, así que
#     este scheduler funciona igual en Windows y Linux (Docker nivela el SO).
INGESTA_CRON = os.environ.get("INGESTA_CRON", "").strip()          # p.ej. "0 2 * * *" (diario 02:00)
BATCH_TZ = os.environ.get("BATCH_TZ", "America/Bogota")
INGESTA_EXTRACTOR = os.environ.get("INGESTA_EXTRACTOR", "rule")
# Un único lock protege TODA corrida del lote (manual o programada) → nunca se solapan.
_lote_lock = threading.Lock()
_scheduler = None


def _correr_lote(extractor: str) -> dict:
    """Ejecuta el lote bajo el lock (no reentrante). Si ya hay una corrida en curso,
    devuelve ``{"en_curso": True}`` en vez de solaparse."""
    if not _lote_lock.acquire(blocking=False):
        return {"en_curso": True, "error": "Ya hay una corrida del lote en curso."}
    try:
        return batch.procesar_todo(_get_rapidocr(), extractor_name=extractor)
    finally:
        _lote_lock.release()


def _job_programado() -> None:
    """Trabajo del scheduler: corre el lote y registra el resumen (sin PII)."""
    if not db.db_disponible():
        logger.warning("Lote programado: BD no disponible; se omite esta corrida.")
        return
    try:
        r = _correr_lote(INGESTA_EXTRACTOR if INGESTA_EXTRACTOR in VALID_EXTRACTOR else "rule")
        logger.info("Lote programado: %s", {k: r.get(k) for k in
                    ("procesados", "incompletos", "cuarentena", "sin_nomenclatura", "en_curso")})
    except Exception:
        logger.exception("Error en la corrida programada del lote")
# Estados del flujo de revisión humana.
ESTADO_PENDIENTE, ESTADO_APROBADO, ESTADO_RECHAZADO = "PENDIENTE_REVISION", "APROBADO", "RECHAZADO"
# Campos que el auxiliar puede corregir/llenar a mano (overrides de la revisión).
CAMPOS_OVERRIDE = {"cedula", "cie10", "eps", "fecha_inicio", "fecha_fin", "dias", "paciente", "tipo", "nivel", "numeroorden"}


def _limpiar_overrides(campos) -> dict:
    """Acepta solo las claves conocidas (lista blanca) con valores no vacíos."""
    if not isinstance(campos, dict):
        return {}
    return {k: v for k, v in campos.items() if k in CAMPOS_OVERRIDE and v not in (None, "")}


def _mapear_staging(result: dict, estado_recepcion: str, overrides: dict | None = None) -> dict:
    """Mapea el resultado a la fila staging usando lookups de la BD si está disponible;
    si no, usa lookups nulos (los IDs quedan pendientes de revisión)."""
    try:
        with db.conexion_mysql() as cx:
            mapeo = erp.mapear_a_staging(result, estado_recepcion, erp.Lookups(cx), overrides=overrides)
            mapeo["db_disponible"] = True
            return mapeo
    except Exception:
        mapeo = erp.mapear_a_staging(result, estado_recepcion, erp.LookupsNulos(), overrides=overrides)
        mapeo["db_disponible"] = False
        return mapeo

# Cache del backend pesado de OCR (RapidOCR): se inicializa una vez y se reutiliza.
_rapidocr_backend = None


def _get_rapidocr():
    global _rapidocr_backend
    if _rapidocr_backend is None:
        _rapidocr_backend = get_ocr_backend("rapidocr")
    return _rapidocr_backend


@contextlib.asynccontextmanager
async def lifespan(app: FastAPI):
    # Pre-carga los modelos ONNX al arrancar para que la primera petición sea rápida.
    with contextlib.suppress(Exception):
        _get_rapidocr()
    # Corrida programada (opcional): si INGESTA_CRON está definido, arranca el scheduler.
    global _scheduler
    if INGESTA_CRON:
        try:
            from apscheduler.schedulers.background import BackgroundScheduler
            from apscheduler.triggers.cron import CronTrigger

            _scheduler = BackgroundScheduler(timezone=BATCH_TZ)
            _scheduler.add_job(
                _job_programado, CronTrigger.from_crontab(INGESTA_CRON, timezone=BATCH_TZ),
                id="ingesta_lote", max_instances=1, coalesce=True, misfire_grace_time=3600,
            )
            _scheduler.start()
            logger.info("Corrida programada ACTIVA (cron=%r tz=%s)", INGESTA_CRON, BATCH_TZ)
        except Exception:
            logger.exception("No se pudo iniciar el scheduler de ingesta (cron=%r)", INGESTA_CRON)
            _scheduler = None
    yield
    if _scheduler is not None:
        with contextlib.suppress(Exception):
            _scheduler.shutdown(wait=False)


app = FastAPI(
    title="incapacidad-ocr",
    description="Imagen/PDF de incapacidad médica → texto plano → JSON estructurado. 100% local.",
    version="1.0.0",
    lifespan=lifespan,
)


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok", "service": "incapacidad-ocr"}


@app.post("/api/procesar")
async def procesar(
    archivo: UploadFile = File(...),
    ocr: str = Form("rapidocr"),
    extractor: str = Form("rule"),
    estado_recepcion: str = Form("WHATSAPP"),
) -> JSONResponse:
    # Validación de parámetros (lista blanca → 400, no 500).
    if ocr not in VALID_OCR:
        raise HTTPException(status_code=400, detail=f"ocr inválido (usa {sorted(VALID_OCR)}).")
    if extractor not in VALID_EXTRACTOR:
        raise HTTPException(status_code=400, detail=f"extractor inválido (usa {sorted(VALID_EXTRACTOR)}).")

    suffix = Path(archivo.filename or "").suffix.lower()
    if suffix not in ALLOWED_SUFFIXES:
        raise HTTPException(
            status_code=415,
            detail=f"Tipo de archivo no soportado: {suffix or '(desconocido)'}. "
                   f"Permitidos: {', '.join(sorted(ALLOWED_SUFFIXES))}",
        )

    # Límite de tamaño ANTES de leer todo a memoria (DoS): UploadFile.size viene del
    # Content-Length / multipart; el chequeo post-lectura queda como respaldo.
    if archivo.size is not None and archivo.size > MAX_BYTES:
        raise HTTPException(status_code=413, detail=f"Archivo demasiado grande (máx. {MAX_MB} MB).")
    data = await archivo.read()
    if not data:
        raise HTTPException(status_code=400, detail="Archivo vacío.")
    if len(data) > MAX_BYTES:
        raise HTTPException(status_code=413, detail=f"Archivo demasiado grande (máx. {MAX_MB} MB).")

    # Selección de motores. La URL/modelo de Ollama vienen del SERVIDOR (env), no del
    # cliente → sin SSRF ni modelos arbitrarios.
    if ocr == "ollama":
        ocr_backend = OllamaVisionOCR(base_url=DEFAULT_OLLAMA_URL, model=OCR_MODEL)
    else:
        ocr_backend = _get_rapidocr()
    if extractor == "ollama":
        extr = OllamaLLMExtractor(base_url=DEFAULT_OLLAMA_URL, model=LLM_MODEL)
    elif extractor == "hibrido":
        # Reglas + LLM fusionados (rápido sobre RapidOCR). Si Ollama no está, usa reglas.
        extr = HybridExtractor(OllamaLLMExtractor(base_url=DEFAULT_OLLAMA_URL, model=LLM_MODEL))
    else:
        extr = RuleBasedExtractor()

    # Procesa en un temporal y lo borra de inmediato (no se persiste PII).
    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            tmp.write(data)
            tmp_path = Path(tmp.name)
        result = IncapacidadProcessor(ocr_backend, extr).run(tmp_path)
    except OllamaError as exc:
        # Error operativo (modelo de Ollama faltante o servicio caído): el mensaje es
        # accionable y seguro de mostrar (no expone internos).
        raise HTTPException(status_code=503, detail=str(exc)) from None
    except Exception:
        # Se registra el detalle en el servidor; al cliente solo un mensaje genérico
        # (no filtrar rutas/internos). El texto puede contener PII → no se loguea el contenido.
        logger.exception("Error procesando archivo subido")
        raise HTTPException(status_code=500, detail="Error al procesar el documento.") from None
    finally:
        if tmp_path and tmp_path.exists():
            tmp_path.unlink(missing_ok=True)

    # Devolvemos solo el nombre base del archivo (sin rutas) y nunca la ruta temporal.
    result["fuente"] = Path(archivo.filename or "archivo").name

    # Mapeo a la tabla staging del ERP (lookups + homologación + derivados). Preview: NO inserta.
    estado = estado_recepcion.upper() if estado_recepcion else "WHATSAPP"
    if estado not in VALID_RECEPCION:
        estado = "WHATSAPP"
    with contextlib.suppress(Exception):
        result["staging"] = _mapear_staging(result, estado)
    return JSONResponse(result)


@app.post("/api/mapear")
def mapear(
    resultado: dict = Body(..., embed=True),
    estado_recepcion: str = Body("WHATSAPP", embed=True),
    campos: dict = Body(None, embed=True),
) -> JSONResponse:
    """Recalcula el mapeo a staging con las correcciones manuales del auxiliar (SIN escribir
    en la BD). Re-resuelve los lookups (cédula/CIE/EPS) y las fechas/días tras editar."""
    if not isinstance(resultado, dict) or "incapacidad" not in resultado:
        raise HTTPException(status_code=400, detail="Cuerpo inválido: falta 'resultado.incapacidad'.")
    estado = (estado_recepcion or "WHATSAPP").upper()
    if estado not in VALID_RECEPCION:
        estado = "WHATSAPP"
    mapeo = _mapear_staging(resultado, estado, _limpiar_overrides(campos))
    return JSONResponse(mapeo)


@app.post("/api/registrar")
def registrar(
    resultado: dict = Body(..., embed=True),
    estado_recepcion: str = Body("WHATSAPP", embed=True),
    campos: dict = Body(None, embed=True),
    estado: str = Body(ESTADO_PENDIENTE, embed=True),
    motivo: str = Body(None, embed=True),
) -> JSONResponse:
    """Inserta el registro en la tabla STAGING `lp_ausentismos_ia`.

    Recibe el resultado ya extraído (no re-procesa la imagen) + las correcciones manuales
    (``campos``) y lo mapea con lookups de BD. ``estado`` ∈ {PENDIENTE_REVISION, APROBADO,
    RECHAZADO}: el auxiliar puede dejarlo en revisión, aprobarlo o rechazarlo (con ``motivo``).
    El ERP promueve a `lpausentismos` solo cuando el registro queda APROBADO.
    """
    if not isinstance(resultado, dict) or "incapacidad" not in resultado:
        raise HTTPException(status_code=400, detail="Cuerpo inválido: falta 'resultado.incapacidad'.")
    recep = (estado_recepcion or "WHATSAPP").upper()
    if recep not in VALID_RECEPCION:
        recep = "WHATSAPP"
    flujo = (estado or ESTADO_PENDIENTE).upper()
    if flujo not in (ESTADO_PENDIENTE, ESTADO_APROBADO, ESTADO_RECHAZADO):
        flujo = ESTADO_PENDIENTE
    if not db.db_disponible():
        raise HTTPException(
            status_code=503,
            detail="Base de datos no disponible. Levanta el servicio 'db' (docker compose up -d db).",
        )
    try:
        with db.conexion_mysql() as cx:
            mapeo = erp.mapear_a_staging(resultado, recep, erp.Lookups(cx),
                                         overrides=_limpiar_overrides(campos))
            # No se aprueba con campos obligatorios faltantes.
            if flujo == ESTADO_APROBADO and mapeo["requiere_revision"]:
                raise HTTPException(
                    status_code=409,
                    detail="No se puede aprobar: faltan datos obligatorios. " +
                           "; ".join(mapeo["problemas"]),
                )
            mapeo["row"]["estado"] = flujo
            if flujo == ESTADO_RECHAZADO and motivo:
                obs = mapeo["row"].get("observaciones") or ""
                mapeo["row"]["observaciones"] = (f"{obs} | RECHAZADO: {motivo}").strip(" |")[:65000]
            new_id = db.insertar_staging(cx, mapeo["row"])
    except HTTPException:
        raise
    except Exception:
        logger.exception("Error insertando en staging")
        raise HTTPException(status_code=500, detail="Error al registrar en la base de datos.") from None
    return JSONResponse({
        "id": new_id,
        "tabla": db.STAGING_TABLE,
        "estado": flujo,
        "requiere_revision": mapeo["requiere_revision"],
        "problemas": mapeo["problemas"],
        "campos_faltantes": mapeo.get("campos_faltantes", []),
        "row": mapeo["row"],
    })


@app.post("/api/revisar")
def revisar(
    id: int = Body(..., embed=True),
    accion: str = Body(..., embed=True),
    resultado: dict = Body(None, embed=True),
    campos: dict = Body(None, embed=True),
    estado_recepcion: str = Body("WHATSAPP", embed=True),
    motivo: str = Body(None, embed=True),
) -> JSONResponse:
    """Revisión humana de un registro ya insertado: aprobar / rechazar / guardar.

    - ``aprobar``  → re-mapea con las correcciones manuales y fija estado APROBADO.
    - ``guardar``  → re-mapea y guarda correcciones, sigue PENDIENTE_REVISION.
    - ``rechazar`` → fija estado RECHAZADO (con ``motivo``); no exige completar campos.
    El ERP promueve a `lpausentismos` solo cuando el registro queda APROBADO.
    """
    accion = (accion or "").lower()
    if accion not in ("aprobar", "rechazar", "guardar"):
        raise HTTPException(status_code=400, detail="accion inválida (aprobar|rechazar|guardar).")
    if not db.db_disponible():
        raise HTTPException(status_code=503, detail="Base de datos no disponible.")

    recep = (estado_recepcion or "WHATSAPP").upper()
    if recep not in VALID_RECEPCION:
        recep = "WHATSAPP"
    try:
        with db.conexion_mysql() as cx:
            if accion == "rechazar":
                nota = f"RECHAZADO: {motivo}" if motivo else "RECHAZADO en revisión"
                ok = db.actualizar_estado(cx, id, ESTADO_RECHAZADO, nota)
                if not ok:
                    raise HTTPException(status_code=404, detail=f"Registro {id} no encontrado.")
                return JSONResponse({"id": id, "estado": ESTADO_RECHAZADO})

            # --- aprobar / guardar con correcciones (re-mapeo) cuando llega el 'resultado'.
            if isinstance(resultado, dict) and "incapacidad" in resultado:
                mapeo = erp.mapear_a_staging(resultado, recep, erp.Lookups(cx),
                                             overrides=_limpiar_overrides(campos))
                if accion == "aprobar" and mapeo["requiere_revision"]:
                    raise HTTPException(
                        status_code=409,
                        detail="No se puede aprobar: faltan datos obligatorios. " +
                               "; ".join(mapeo["problemas"]),
                    )
                destino = ESTADO_APROBADO if accion == "aprobar" else ESTADO_PENDIENTE
                ok = db.actualizar_revision(cx, id, mapeo["row"], destino,
                                            nota="Revisado manualmente" if campos else None)
                if not ok:
                    raise HTTPException(status_code=404, detail=f"Registro {id} no encontrado.")
                return JSONResponse({
                    "id": id, "estado": destino,
                    "requiere_revision": mapeo["requiere_revision"],
                    "problemas": mapeo["problemas"],
                    "row": mapeo["row"],
                })

            # --- Acción rápida desde la bandeja (sin re-mapeo): solo aprobar.
            if accion == "guardar":
                raise HTTPException(status_code=400, detail="Nada que guardar sin 'resultado'.")
            fila = db.obtener_staging(cx, id)
            if not fila:
                raise HTTPException(status_code=404, detail=f"Registro {id} no encontrado.")
            # Solo se aprueba si los campos OBLIGATORIOS ya están resueltos en el registro.
            obligatorios = {
                "idlpempleado": "empleado (cédula)", "idlpdiagnosticos": "diagnóstico (CIE-10)",
                "fechainicio": "fecha de inicio", "Numerodias": "días",
            }
            faltan = [etq for col, etq in obligatorios.items() if not fila.get(col)]
            if faltan:
                raise HTTPException(
                    status_code=409,
                    detail="No se puede aprobar: faltan " + ", ".join(faltan) +
                           ". Edita el registro re-procesando el documento.",
                )
            db.actualizar_estado(cx, id, ESTADO_APROBADO)
            return JSONResponse({"id": id, "estado": ESTADO_APROBADO})
    except HTTPException:
        raise
    except Exception:
        logger.exception("Error en revisión de staging")
        raise HTTPException(status_code=500, detail="Error al revisar el registro.") from None


@app.get("/api/staging")
def staging(estado: str = "") -> JSONResponse:
    """Lista los últimos registros (pantalla del auxiliar). Filtra por estado opcional."""
    if not db.db_disponible():
        return JSONResponse({"db_disponible": False, "registros": []})
    filtro = estado.upper() if estado else None
    try:
        with db.conexion_mysql() as cx:
            return JSONResponse({
                "db_disponible": True,
                "registros": db.listar_staging(cx, estado=filtro),
            })
    except Exception:
        logger.exception("Error listando staging")
        return JSONResponse({"db_disponible": False, "registros": []})


@app.get("/api/staging/{registro_id}")
def staging_uno(registro_id: int) -> JSONResponse:
    """Un registro completo (para cargarlo en el formulario de revisión)."""
    if not db.db_disponible():
        raise HTTPException(status_code=503, detail="Base de datos no disponible.")
    try:
        with db.conexion_mysql() as cx:
            fila = db.obtener_staging(cx, registro_id)
    except Exception:
        logger.exception("Error obteniendo registro de staging")
        raise HTTPException(status_code=500, detail="Error al obtener el registro.") from None
    if not fila:
        raise HTTPException(status_code=404, detail=f"Registro {registro_id} no encontrado.")
    return JSONResponse(fila)


@app.get("/api/lote/pendientes")
def lote_pendientes() -> JSONResponse:
    """Cuenta lo que hay en la carpeta de ingesta 'sin procesar' (para el botón de la UI)."""
    try:
        return JSONResponse(batch.contar_pendientes())
    except Exception:
        logger.exception("Error contando la carpeta de ingesta")
        raise HTTPException(status_code=500, detail="Error al leer la carpeta de ingesta.") from None


@app.post("/api/lote/procesar")
def lote_procesar(extractor: str = Body("rule", embed=True)) -> JSONResponse:
    """Procesa TODOS los documentos de la carpeta 'sin procesar' (ingesta masiva por lotes).

    Agrupa por nomenclatura, OCR-ea el documento base, valida requisitos por tipo, registra
    en staging (`PENDIENTE_REVISION`) y mueve los archivos a procesados/incompletos/cuarentena.
    """
    extr = extractor if extractor in VALID_EXTRACTOR else "rule"
    if not db.db_disponible():
        raise HTTPException(status_code=503, detail="Base de datos no disponible.")
    try:
        resumen = _correr_lote(extr)
    except Exception:
        logger.exception("Error en el procesamiento por lotes")
        raise HTTPException(status_code=500, detail="Error en el procesamiento por lotes.") from None
    if resumen.get("en_curso"):
        raise HTTPException(status_code=409, detail=resumen["error"])
    return JSONResponse(resumen)


@app.get("/api/lote/estado")
def lote_estado() -> JSONResponse:
    """Estado de la corrida programada (para la UI): si está activa, cron y próxima ejecución."""
    prox = None
    if _scheduler is not None:
        with contextlib.suppress(Exception):
            job = _scheduler.get_job("ingesta_lote")
            if job is not None and job.next_run_time is not None:
                prox = job.next_run_time.isoformat()
    return JSONResponse({
        "programado": bool(INGESTA_CRON), "cron": INGESTA_CRON or None, "tz": BATCH_TZ,
        "proxima_ejecucion": prox, "en_curso": _lote_lock.locked(),
    })


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")
