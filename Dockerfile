# incapacidad-ocr — servicio web (FastAPI + UI). 100% local, sin APIs pagas.
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

# Dependencias de sistema para OpenCV (cv2 → RapidOCR) y onnxruntime (OpenMP).
RUN apt-get update && apt-get install -y --no-install-recommends \
        libgl1 \
        libglib2.0-0 \
        libgomp1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Instala TODO desde requirements.txt (incluye fastapi/uvicorn para el servicio web).
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Código de la aplicación (la UI estática va dentro del paquete).
COPY incapacidad_ocr ./incapacidad_ocr

# Usuario no-root (los modelos ONNX vienen embebidos en el wheel de RapidOCR).
RUN useradd --create-home app && chown -R app:app /app
USER app

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://localhost:8000/api/health').status==200 else 1)"

CMD ["uvicorn", "incapacidad_ocr.webapp:app", "--host", "0.0.0.0", "--port", "8000"]
