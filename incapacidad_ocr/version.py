"""Huella del código que está corriendo, para detectar una imagen de Docker DESFASADA.

Por qué existe. El código va DENTRO de la imagen (no montado), así que tras editar Python
hay que reconstruir. Si no se hace, el contenedor sigue sirviendo la versión anterior — y eso
**no se ve**: la API responde `200` con una carga plausible. Pasó de verdad: un contenedor con
la imagen previa a la reestructuración de la ingesta contestaba
`{"archivos": 0, ...}` a `/api/lote/pendientes` mientras en disco había 31 documentos, porque
ese código buscaba el `inbox/` antiguo. Se lee igual que «la bandeja está vacía y todo bien».

La huella es un hash de los `.py` del paquete. Cambia con cualquier edición, así que comparar
la del contenedor con la del host responde «¿está corriendo mi código?» sin llevar a mano un
número de versión que se olvida de subir:

    curl -s http://localhost:8000/api/health          # la del contenedor
    python -c "from incapacidad_ocr.version import huella_codigo; print(huella_codigo())"

Si no coinciden:  docker compose up -d --build incapacidad-ocr
"""
from __future__ import annotations

import hashlib
from functools import lru_cache
from pathlib import Path

PAQUETE = Path(__file__).resolve().parent


@lru_cache(maxsize=1)
def huella_codigo() -> str:
    """Hash corto de los `.py` del paquete. Se calcula UNA vez por proceso.

    Se ordenan los nombres para que el hash no dependa del orden del sistema de archivos, y
    se incluye el NOMBRE de cada archivo además de su contenido: así, añadir o quitar un
    módulo también mueve la huella. Los bytes se leen en crudo (no texto) para que no
    influya el final de línea, que en Windows cambia sin que cambie el código.
    """
    h = hashlib.sha256()
    try:
        archivos = sorted(p for p in PAQUETE.glob("*.py") if p.is_file())
        for p in archivos:
            h.update(p.name.encode("utf-8"))
            h.update(p.read_bytes())
    except OSError:
        # Nunca debe tumbar el health check: una huella desconocida es un dato, no un fallo.
        return "desconocida"
    return h.hexdigest()[:12]
