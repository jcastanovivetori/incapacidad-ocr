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
from pathlib import Path

from fastapi import Body, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse

from . import db, erp
from .extract import HybridExtractor, OllamaLLMExtractor, RuleBasedExtractor
from .ocr import OllamaError, OllamaVisionOCR, get_ocr_backend
from .processor import IncapacidadProcessor

logger = logging.getLogger("incapacidad_ocr.webapp")

STATIC_DIR = Path(__file__).resolve().parent / "static"
ALLOWED_SUFFIXES = {".pdf", ".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff"}
MAX_BYTES = int(os.environ.get("MAX_UPLOAD_BYTES", 25 * 1024 * 1024))  # 25 MB por defecto

# --- Configuración de Ollama: SOLO desde el entorno del servidor (no del cliente).
#     El cliente NO puede elegir la URL ni el modelo → evita SSRF (que un atacante
#     apunte el servidor a una URL interna) y el uso de modelos arbitrarios.
DEFAULT_OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434")
OCR_MODEL = os.environ.get("OCR_MODEL", "qwen2.5vl:3b")  # VLM que SÍ transcribe (no moondream)
LLM_MODEL = os.environ.get("LLM_MODEL", "gemma3:4b")

VALID_OCR = {"rapidocr", "ollama"}
VALID_EXTRACTOR = {"rule", "ollama", "hibrido"}
VALID_RECEPCION = {"ORIGINAL", "WHATSAPP", "CORREO"}


def _mapear_staging(result: dict, estado_recepcion: str) -> dict:
    """Mapea el resultado a la fila staging usando lookups de la BD si está disponible;
    si no, usa lookups nulos (los IDs quedan pendientes de revisión)."""
    try:
        with db.conexion_mysql() as cx:
            mapeo = erp.mapear_a_staging(result, estado_recepcion, erp.Lookups(cx))
            mapeo["db_disponible"] = True
            return mapeo
    except Exception:
        mapeo = erp.mapear_a_staging(result, estado_recepcion, erp.LookupsNulos())
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
    yield


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
        raise HTTPException(status_code=413, detail="Archivo demasiado grande (máx. 25 MB).")
    data = await archivo.read()
    if not data:
        raise HTTPException(status_code=400, detail="Archivo vacío.")
    if len(data) > MAX_BYTES:
        raise HTTPException(status_code=413, detail="Archivo demasiado grande (máx. 25 MB).")

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


@app.post("/api/registrar")
def registrar(
    resultado: dict = Body(..., embed=True),
    estado_recepcion: str = Body("WHATSAPP", embed=True),
) -> JSONResponse:
    """Inserta el registro en la tabla STAGING `lp_ausentismos_ia` (estado PENDIENTE_REVISION).

    Recibe el resultado ya extraído (no re-procesa la imagen) y lo mapea con lookups de BD.
    El ERP promueve el registro a `lpausentismos` cuando el auxiliar APRUEBA.
    """
    if not isinstance(resultado, dict) or "incapacidad" not in resultado:
        raise HTTPException(status_code=400, detail="Cuerpo inválido: falta 'resultado.incapacidad'.")
    estado = (estado_recepcion or "WHATSAPP").upper()
    if estado not in VALID_RECEPCION:
        estado = "WHATSAPP"
    if not db.db_disponible():
        raise HTTPException(
            status_code=503,
            detail="Base de datos no disponible. Levanta el servicio 'db' (docker compose up -d db).",
        )
    try:
        with db.conexion_mysql() as cx:
            mapeo = erp.mapear_a_staging(resultado, estado, erp.Lookups(cx))
            new_id = db.insertar_staging(cx, mapeo["row"])
    except Exception:
        logger.exception("Error insertando en staging")
        raise HTTPException(status_code=500, detail="Error al registrar en la base de datos.") from None
    return JSONResponse({
        "id": new_id,
        "tabla": db.STAGING_TABLE,
        "estado": "PENDIENTE_REVISION",
        "requiere_revision": mapeo["requiere_revision"],
        "problemas": mapeo["problemas"],
        "row": mapeo["row"],
    })


@app.get("/api/staging")
def staging() -> JSONResponse:
    """Lista los últimos registros en revisión (pantalla del auxiliar)."""
    if not db.db_disponible():
        return JSONResponse({"db_disponible": False, "registros": []})
    try:
        with db.conexion_mysql() as cx:
            return JSONResponse({"db_disponible": True, "registros": db.listar_staging(cx)})
    except Exception:
        logger.exception("Error listando staging")
        return JSONResponse({"db_disponible": False, "registros": []})


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")
