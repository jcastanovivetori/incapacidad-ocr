"""Siembra el escenario de demo de la INGESTA por lotes en ``ingesta/inbox/whatsapp``.

Deja 5 casos + 1 archivo mal nombrado, con la nomenclatura ``cedula_TIPODOC.ext``
(la FECHA no va en el nombre: sale del OCR del documento):
  - 13742111 (LEONARDO, Salud Total)  INCAPACIDAD + EPICRISIS  → enf. general, COMPLETO
  - 63523940 (ALIX, Famisanar)        INCAPACIDAD              → enf. general, INCOMPLETO (falta soporte)
  - 1005542119 (MICHAEL, Seg. Estado) INCAPACIDAD + FURAT      → accidente de trabajo, COMPLETO   [sintético]
  - 1095912481 (JAIDER)               VACACIONES               → vacaciones, COMPLETO             [sintético]
  - 1098757631 (YARITZA)              PERMISO                  → licencia remunerada, COMPLETO    [sintético]
  - documento_suelto.jpeg (sin nomenclatura → se omite / va a sin_nomenclatura)

Los dos primeros usan documentos REALES de ../Ejemplos; los tres sintéticos se generan
como imágenes de texto claro (RapidOCR las lee bien). Ejecutar en el HOST (necesita PIL y
una fuente TTF; usa Arial en Windows o DejaVu en Linux, con respaldo a la fuente por defecto).

    python scripts/sembrar_demo.py
"""
from __future__ import annotations

import shutil
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

REPO = Path(__file__).resolve().parent.parent
INBOX = REPO / "ingesta" / "inbox" / "whatsapp"
EJEMPLOS = REPO.parent / "Ejemplos"

_FUENTES = [
    r"C:/Windows/Fonts/arial.ttf", r"C:/Windows/Fonts/arialbd.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
]


def _font(size: int):
    for ruta in _FUENTES:
        try:
            return ImageFont.truetype(ruta, size)
        except OSError:
            continue
    return ImageFont.load_default()


FONT, FONT_B = _font(26), _font(30)


def render(lines: list[str], path: Path) -> None:
    W, pad, lh = 1500, 40, 42
    img = Image.new("RGB", (W, pad * 2 + lh * len(lines)), "white")
    d = ImageDraw.Draw(img)
    for i, ln in enumerate(lines):
        d.text((pad, pad + i * lh), ln, fill="black", font=(FONT_B if i == 0 else FONT))
    img.save(path)
    print("  generado:", path.name)


def main() -> None:
    INBOX.mkdir(parents=True, exist_ok=True)
    for f in INBOX.glob("*"):
        if f.is_file() and f.name != ".gitkeep":  # preserva el marcador de estructura versionado
            f.unlink()

    # --- Casos con documentos REALES (../Ejemplos) ---
    shutil.copy(EJEMPLOS / "incapacidad.pdf", INBOX / "13742111_INCAPACIDAD.pdf")
    shutil.copy(EJEMPLOS / "incapacidad.pdf", INBOX / "13742111_EPICRISIS.pdf")
    shutil.copy(EJEMPLOS / "incapacidad.jpeg", INBOX / "63523940_INCAPACIDAD.jpeg")
    shutil.copy(EJEMPLOS / "incapacidad_.jpeg", INBOX / "documento_suelto.jpeg")  # sin nomenclatura
    print("  copiados: 13742111 (x2), 63523940, documento_suelto")

    # --- Casos SINTÉTICOS (texto claro para OCR; la fecha va DENTRO del documento) ---
    render([
        "INCAPACIDAD MEDICA",
        "Entidad: SEGUROS DEL ESTADO ARL",
        "Paciente:",
        "CC 1005542119 MICHAEL ALEXIZ MORENO VELANDIA",
        "Origen: Accidente de trabajo",
        "Diagnostico principal: S42.0 FRACTURA DE LA CLAVICULA",
        "Fecha inicio: 2026-06-15",
        "Fecha fin: 2026-06-24",
        "Dias de incapacidad: 10",
        "Medico: Dr. CARLOS PEREZ  Registro: 12345",
    ], INBOX / "1005542119_INCAPACIDAD.png")
    shutil.copy(EJEMPLOS / "incapacidad.pdf", INBOX / "1005542119_FURAT.pdf")
    print("  generado: 1005542119_FURAT.pdf")

    render([
        "NOTIFICACION DE PERIODO DE VACACIONES",
        "Senor(a): JAIDER SEBASTIAN HERNANDEZ ARDILA",
        "Documento: CC 1095912481",
        "Nos permitimos informar que disfrutara su periodo de vacaciones:",
        "a partir del primero (01) de julio de dos mil veintiseis (2026)",
        "hasta el quince (15) de julio de dos mil veintiseis (2026).",
        "Departamento de Gestion Humana",
    ], INBOX / "1095912481_VACACIONES.png")

    render([
        "FORMATO SOLICITUD DE PERMISO",
        "1. DATOS DE LA SOLICITUD",
        "Fecha: 2026-06-20",
        "Nombre completo del solicitante: Yaritza Contreras Rivera",
        "Documento de identidad: 1098757631",
        "Empresa: Indulacteos de Colombia",
        "2. TIPO DE PERMISO",
        "[ ] No Remunerado",
        "[X] Remunerado",
        "Detalle: Cita medica prioritaria",
        "3. DURACION DEL PERMISO",
        "Desde: 2026-06-20    Hasta: 2026-06-20",
        "4. APROBACION DE LA SOLICITUD",
        "SOLICITADO POR",
        "Nombre: Yaritza Contreras",
        "Cargo: Operaria",
        "AUTORIZADO POR",
        "Nombre: Diana Gelvez",
        "Cargo: Jefe de Gestion Humana",
    ], INBOX / "1098757631_PERMISO.png")

    print(f"OK — escenario sembrado en {INBOX}")


if __name__ == "__main__":
    main()
