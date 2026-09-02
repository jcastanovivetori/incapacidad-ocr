"""Mide cuan REALISTAS son los ataques: busca en los 31 .txt ya cacheados los
patrones que los disparan. NO imprime PII: solo el archivo y el patron generico.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

# --- Rutas relativas (añadidas por scripts/exportar_analisis.py) --------------------------
# Este script se escribió con rutas ABSOLUTAS de la máquina donde se investigó. Se resuelven
# desde la ubicación del propio archivo para que funcione tras un `git pull` en cualquier
# equipo. El corpus (`dataset-falsedad/`) NO está en el repositorio: lo aporta el cliente.
import pathlib as _pl
_REPO = _pl.Path(__file__).resolve().parents[3]
_DATASET = _REPO.parent / "dataset-falsedad"
_EJEMPLOS = _REPO.parent / "Ejemplos"
# ------------------------------------------------------------------------------------------

REPO = Path(str(_REPO))
sys.path.insert(0, str(REPO))
from incapacidad_ocr.numeros_es import normalizar  # noqa: E402

BASE = Path(str(_DATASET / "ocr"))

SONDAS: dict[str, str] = {
    "rejilla_fecha_suelta (dd mm aaaa en su renglon)": r"(?m)^\s*\d{1,2}[ ]+\d{1,2}[ ]+\d{4}\s*$",
    "rotulo dias/duracion + guion o dos puntos en el MISMO renglon que dia/mes/ano":
        r"(?m)^.*\bdias?\s*[:\-].*\b(mes|ano)\b.*$",
    "unidad 'dias' seguida de guion/dos puntos": r"\bdias?[ \t]*[:\-]",
    "veto 'hace' en el mismo renglon que 'dias'": r"(?m)^.*\bhace.*\bdias?\b.*$",
    "veto 'horas' en el mismo renglon que 'dias'": r"(?m)^.*\bhoras?\b.*\bdias?\b.*$",
    "veto 'mes/es' en el mismo renglon que 'dias'": r"(?m)^.*\bmes(?:es)?\b.*\bdias?\b.*$",
    "rotulo 'duracion' con algo a su derecha": r"duracion[^\n]{1,25}\S",
    "numeral en letras de 3+ palabras": r"(?:ciento|doscientos|trescientos|cuatrocientos|quinientos)\s+\w+\s+y\s+\w+",
}

archivos = sorted(BASE.rglob("*.txt"))
print(f"{len(archivos)} textos cacheados\n")
for nombre, patron in SONDAS.items():
    rx = re.compile(patron)
    hits = []
    for f in archivos:
        t = normalizar(f.read_text(encoding="utf-8", errors="replace"))
        n = len(rx.findall(t))
        if n:
            hits.append(f"{f.parent.name}/{f.name}({n})")
    print(f"- {nombre}\n    {len(hits)}/{len(archivos)} archivos: {', '.join(hits[:8]) or '-'}")
