"""Pruebas de incapacidad_ocr.authenticity (sub-bandera DUDOSA).

    python tests/test_authenticity.py

Genera PDFs sintéticos con `fitz` (misma dependencia que usa el módulo bajo prueba)
para no depender de documentos reales. Sin pytest, mismo estilo que test_processor.py.
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

try:  # consola Windows (cp1252) → forzar UTF-8 para acentos
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # noqa: BLE001
    pass

from incapacidad_ocr.authenticity import (  # noqa: E402
    analizar_autenticidad,
    _revisar_consistencia_fechas_dias,
    _revisar_periodos_multiples,
)

_fail = 0


def check(name: str, cond: bool, detail: str = "") -> None:
    global _fail
    ok = bool(cond)
    if not ok:
        _fail += 1
    print(("  PASS " if ok else "  FAIL ") + name + (f"  ->  {detail}" if detail else ""))


RECORD = {
    "paciente": {"documento_numero": "1020727050", "nombre": "CASTELLANOS ARRIZA JOHAN ESNEIDER"},
    "incapacidad": {"dias": "2", "fecha_inicio": "11/7/2026", "fecha_fin": "12/7/2026"},
    "diagnostico": {"cie10": "S80.1"},
}


def _pdf_uniforme() -> Path:
    """Un solo tipo de letra para todo el documento (caso legítimo)."""
    import fitz

    doc = fitz.open()
    pagina = doc.new_page()
    y = 50
    lineas = [
        "CLINICA MEDICAL S.A.S.",
        "Nombre del Paciente: CASTELLANOS ARRIZA JOHAN ESNEIDER",
        "Identificacion: CC 1020727050",
        "Dx Principal de Egreso: S80.1 CONTUSION",
        "Dias de Incapacidad: 2",
        "Fecha de Inicio de Incapacidad: 11/7/2026",
        "Fecha Fin de Incapacidad: 12/7/2026",
    ]
    for linea in lineas:
        pagina.insert_text((50, y), linea, fontname="helv", fontsize=11)
        y += 20
    tmp = Path(tempfile.mktemp(suffix=".pdf"))
    doc.save(str(tmp))
    doc.close()
    return tmp


def _pdf_fuente_mezclada(n_campos_distintos: int) -> Path:
    """`n_campos_distintos` campos clave en una fuente distinta al resto (simula edición)."""
    import fitz

    doc = fitz.open()
    pagina = doc.new_page()
    y = 50
    todos_los_campos = ["1020727050", "S80.1", "2"]
    campos_a_alterar = set(todos_los_campos[:n_campos_distintos])
    lineas = [
        "CLINICA MEDICAL S.A.S.",
        "Nombre del Paciente: CASTELLANOS ARRIZA JOHAN ESNEIDER",
        "Identificacion: CC 1020727050",
        "Dx Principal de Egreso: S80.1 CONTUSION",
        "Dias de Incapacidad: 2",
        "Fecha de Inicio de Incapacidad: 11/7/2026",
        "Fecha Fin de Incapacidad: 12/7/2026",
    ]
    for linea in lineas:
        # Si la línea contiene alguno de los valores a alterar, se dibuja en 2 spans:
        # el prefijo con la fuente normal y el valor con una fuente distinta (Times).
        alterado = next((v for v in campos_a_alterar if v in linea), None)
        if alterado:
            idx = linea.index(alterado)
            pagina.insert_text((50, y), linea[:idx], fontname="helv", fontsize=11)
            ancho_prefijo = fitz.get_text_length(linea[:idx], fontname="helv", fontsize=11)
            pagina.insert_text((50 + ancho_prefijo, y), linea[idx:], fontname="tiro", fontsize=11)
        else:
            pagina.insert_text((50, y), linea, fontname="helv", fontsize=11)
        y += 20
    tmp = Path(tempfile.mktemp(suffix=".pdf"))
    doc.save(str(tmp))
    doc.close()
    return tmp


def _pdf_sin_texto() -> Path:
    """PDF con una página vacía (sin capa de texto) — simula un PDF-imagen escaneado."""
    import fitz

    doc = fitz.open()
    doc.new_page()
    tmp = Path(tempfile.mktemp(suffix=".pdf"))
    doc.save(str(tmp))
    doc.close()
    return tmp


def _pdf_escaneado_con_imagen() -> Path:
    """PDF sin capa de texto pero con una foto/escaneo JPEG embebido — el caso real
    reportado por el usuario (Clínica Medical S.A.S.): un PDF que es, en el fondo,
    una imagen envuelta en PDF (ni RapidOCR ni el chequeo de fuentes ven texto
    vectorial; solo el fallback de imagen embebida tiene algo que analizar)."""
    import io

    import fitz
    from PIL import Image, ImageDraw

    img = Image.new("RGB", (800, 600), "white")
    d = ImageDraw.Draw(img)
    d.text((40, 40), "INCAPACIDAD MEDICA", fill="black")
    d.text((40, 80), "Nombre: PACIENTE DE PRUEBA", fill="black")
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=85)
    jpeg_bytes = buf.getvalue()

    doc = fitz.open()
    pagina = doc.new_page(width=800, height=600)
    pagina.insert_image(fitz.Rect(0, 0, 800, 600), stream=jpeg_bytes)
    tmp = Path(tempfile.mktemp(suffix=".pdf"))
    doc.save(str(tmp))
    doc.close()
    return tmp


def test_pdf_fuente_uniforme() -> None:
    print("[1] PDF con fuente uniforme -> no dispara (anti falso-positivo)")
    path = _pdf_uniforme()
    try:
        r = analizar_autenticidad(path, "texto irrelevante " * 5, RECORD)
        check("sospechosa=False", r["sospechosa"] is False, str(r))
    finally:
        path.unlink(missing_ok=True)


def test_pdf_fuente_mezclada_dispara() -> None:
    print("[2] PDF con 2+ campos clave en fuente distinta -> dispara")
    path = _pdf_fuente_mezclada(2)
    try:
        r = analizar_autenticidad(path, "texto irrelevante " * 5, RECORD)
        check("sospechosa=True", r["sospechosa"] is True, str(r))
        check("motivo menciona campos", bool(r["motivo"]) and "Fuente inconsistente" in r["motivo"], r["motivo"])
    finally:
        path.unlink(missing_ok=True)


def test_pdf_un_solo_campo_no_dispara() -> None:
    print("[3] PDF con UN solo campo en fuente distinta -> no dispara (umbral conservador)")
    path = _pdf_fuente_mezclada(1)
    try:
        r = analizar_autenticidad(path, "texto irrelevante " * 5, RECORD)
        check("sospechosa=False", r["sospechosa"] is False, str(r))
    finally:
        path.unlink(missing_ok=True)


def test_pdf_sin_texto_vectorial_omite() -> None:
    print("[4] PDF sin capa de texto (escaneado) -> se omite, no rompe")
    path = _pdf_sin_texto()
    try:
        r = analizar_autenticidad(path, "", RECORD)
        check("sospechosa=False", r["sospechosa"] is False, str(r))
        check("sin excepción", "detalle" in r, str(r))
    finally:
        path.unlink(missing_ok=True)


def test_pdf_escaneado_con_imagen_flag_off() -> None:
    print("[7] PDF escaneado con imagen embebida, chequeo de imagen DESACTIVADO (default) -> no dispara")
    import os

    os.environ.pop("AUTHENTICITY_IMAGE_CHECK", None)
    path = _pdf_escaneado_con_imagen()
    try:
        r = analizar_autenticidad(path, "", RECORD)
        check("sospechosa=False", r["sospechosa"] is False, str(r))
        check("omitido por flag", r["detalle"].get("omitido") == "chequeo de imagen desactivado", str(r))
    finally:
        path.unlink(missing_ok=True)


def test_pdf_escaneado_con_imagen_flag_on() -> None:
    print("[8] PDF escaneado con imagen embebida, chequeo de imagen ACTIVADO -> corre ELA sin romper")
    import os

    path = _pdf_escaneado_con_imagen()
    try:
        os.environ["AUTHENTICITY_IMAGE_CHECK"] = "1"
        r = analizar_autenticidad(path, "", RECORD)
        check("no lanza excepción", isinstance(r, dict) and "sospechosa" in r, str(r))
        # No se quedó en un "gate" previo a la extracción/ELA (sin imagen, sin PyMuPDF,
        # chequeo desactivado): "sin variación de compresión" es un resultado VÁLIDO de
        # haber corrido ELA de verdad (imagen sintética casi plana, sin doble compresión).
        omitido = r.get("detalle", {}).get("omitido")
        check("llegó a extraer la imagen y correr ELA",
              omitido not in ("chequeo de imagen desactivado", "PyMuPDF no instalado",
                              "sin imágenes embebidas", "no se pudo abrir el PDF"), str(r))
    finally:
        os.environ.pop("AUTHENTICITY_IMAGE_CHECK", None)
        path.unlink(missing_ok=True)


def test_sin_pymupdf_no_rompe() -> None:
    print("[5] Sin PyMuPDF instalado (import forzado a fallar) -> no rompe")
    import builtins

    real_import = builtins.__import__

    def fake_import(name, *a, **kw):
        if name == "fitz":
            raise ImportError("simulado: PyMuPDF no instalado")
        return real_import(name, *a, **kw)

    path = _pdf_uniforme()
    try:
        builtins.__import__ = fake_import
        r = analizar_autenticidad(path, "texto", RECORD)
        check("sospechosa=False", r["sospechosa"] is False, str(r))
    finally:
        builtins.__import__ = real_import
        path.unlink(missing_ok=True)


def test_no_pdf_ni_jpeg_no_aplica() -> None:
    print("[6] Extensión no cubierta (.png) -> sospechosa=False, sin excepción")
    r = analizar_autenticidad(Path("dummy.png"), "texto", RECORD)
    check("sospechosa=False", r["sospechosa"] is False, str(r))


# Caso real reportado: "Días de incapacidad: 02" con "Desde: 05/06/2026 - Hasta:
# 06/07/2026" (32 días reales según las fechas).
RECORD_FECHAS_INCONSISTENTES = {
    "paciente": {"documento_numero": "1013096147", "nombre": "JUAN ESTEBAN ROJAS GONZALEZ"},
    "incapacidad": {"dias": 2, "fecha_inicio": "2026-06-05", "fecha_fin": "2026-07-06"},
    "diagnostico": {"cie10": "A09"},
}


def test_fechas_dias_inconsistentes_dispara() -> None:
    print("[13] Días declarados no coinciden con el rango de fechas -> dispara (caso real)")
    r = _revisar_consistencia_fechas_dias(RECORD_FECHAS_INCONSISTENTES)
    check("sospechosa=True", r["sospechosa"] is True, str(r))
    check("detalle trae ambos conteos",
          r["detalle"].get("dias_declarados") == 2 and r["detalle"].get("dias_por_fechas") == 32, str(r))


def test_fechas_dias_consistentes_no_dispara() -> None:
    print("[14] Días declarados SÍ coinciden con el rango de fechas -> no dispara")
    record = {"incapacidad": {"dias": 5, "fecha_inicio": "2026-06-10", "fecha_fin": "2026-06-14"}}
    r = _revisar_consistencia_fechas_dias(record)
    check("sospechosa=False", r["sospechosa"] is False, str(r))


def test_fechas_dias_tolerancia_un_dia_no_dispara() -> None:
    print("[15] Diferencia de 1 día (conteo no-inclusivo de algunos formatos) -> no dispara")
    record = {"incapacidad": {"dias": 4, "fecha_inicio": "2026-06-10", "fecha_fin": "2026-06-14"}}
    r = _revisar_consistencia_fechas_dias(record)
    check("sospechosa=False", r["sospechosa"] is False, str(r))


def test_fechas_dias_incompleto_no_opina() -> None:
    print("[16] Falta fecha_fin o dias no es int -> no opina, sin excepción")
    check("sin fecha_fin", _revisar_consistencia_fechas_dias(
        {"incapacidad": {"dias": 2, "fecha_inicio": "2026-06-05"}})["sospechosa"] is False)
    check("dias como string (ya normalizado a otra cosa)", _revisar_consistencia_fechas_dias(
        {"incapacidad": {"dias": "2", "fecha_inicio": "2026-06-05", "fecha_fin": "2026-07-06"}})["sospechosa"] is False)
    check("record None", _revisar_consistencia_fechas_dias(None)["sospechosa"] is False)


def test_fechas_dias_integrado_en_analizar_autenticidad() -> None:
    print("[17] Integrado en analizar_autenticidad (combinado con otras señales)")
    r = analizar_autenticidad(Path("no_existe.jpg"), "", RECORD_FECHAS_INCONSISTENTES)
    check("sospechosa=True", r["sospechosa"] is True, str(r))
    check("motivo menciona los días", "no coinciden con el rango de fechas" in (r["motivo"] or ""), r["motivo"])


# Texto real (extraído con fitz) del documento 1124053450_INCAPACIDAD.pdf reportado
# como falso: trae DOS periodos de incapacidad distintos en la misma página.
TEXTO_DOS_PERIODOS = (
    "Dianóstico: N23X: COLICORENAL, NOESPECIFICADO\n"
    "INCAPACIDADPOR:\n"
    "SE DAINCAPACIDAD MEDICAPOR 5 DIAS DESDE 09-06-26 HASTAEL 13-06-26\n"
    "OBSERVACIÓNES:\n"
    "SE DA INCAPACIDAD MEDICA POR 4 DIAS DESDE EL 29-07-26 HASTA EL 01/07/29\n"
)


def test_periodos_multiples_dispara() -> None:
    print("[9] Texto con DOS periodos de incapacidad distintos -> dispara (caso real reportado)")
    r = _revisar_periodos_multiples(TEXTO_DOS_PERIODOS)
    check("sospechosa=True", r["sospechosa"] is True, str(r))
    check("detalle trae ambos periodos", len(r["detalle"].get("periodos", [])) == 2, str(r))


def test_periodos_repetidos_iguales_no_dispara() -> None:
    print("[10] El mismo periodo mencionado DOS veces (igual) -> no dispara")
    texto = (
        "SE DA INCAPACIDAD MEDICA POR 5 DIAS DESDE 09-06-26 HASTA EL 13-06-26\n"
        "Resumen: incapacidad por 5 dias desde 09-06-26 hasta el 13-06-26\n"
    )
    r = _revisar_periodos_multiples(texto)
    check("sospechosa=False", r["sospechosa"] is False, str(r))


def test_periodo_unico_no_dispara() -> None:
    print("[11] Un solo periodo mencionado -> no dispara")
    r = _revisar_periodos_multiples("SE DA INCAPACIDAD MEDICA POR 5 DIAS DESDE 09-06-26 HASTA EL 13-06-26")
    check("sospechosa=False", r["sospechosa"] is False, str(r))


def test_periodos_multiples_integrado_en_pdf() -> None:
    print("[12] Integrado en analizar_autenticidad para un PDF (extensión .pdf, sin campos clave)")
    # No hace falta que sea un PDF real: analizar_autenticidad corre la señal de texto
    # aunque el archivo en sí no exista/falle (fail-open), porque opera sobre texto_plano.
    r = analizar_autenticidad(Path("no_existe.pdf"), TEXTO_DOS_PERIODOS, None)
    check("sospechosa=True", r["sospechosa"] is True, str(r))
    check("motivo menciona periodos", "periodos de incapacidad distintos" in (r["motivo"] or ""), r["motivo"])


def main() -> int:
    print("=" * 64)
    print("PRUEBAS incapacidad_ocr.authenticity")
    print("=" * 64)
    test_pdf_fuente_uniforme()
    test_pdf_fuente_mezclada_dispara()
    test_pdf_un_solo_campo_no_dispara()
    test_pdf_sin_texto_vectorial_omite()
    test_pdf_escaneado_con_imagen_flag_off()
    test_pdf_escaneado_con_imagen_flag_on()
    test_sin_pymupdf_no_rompe()
    test_no_pdf_ni_jpeg_no_aplica()
    test_periodos_multiples_dispara()
    test_periodos_repetidos_iguales_no_dispara()
    test_periodo_unico_no_dispara()
    test_periodos_multiples_integrado_en_pdf()
    test_fechas_dias_inconsistentes_dispara()
    test_fechas_dias_consistentes_no_dispara()
    test_fechas_dias_tolerancia_un_dia_no_dispara()
    test_fechas_dias_incompleto_no_opina()
    test_fechas_dias_integrado_en_analizar_autenticidad()
    print("-" * 64)
    print("RESULTADO:", "TODO OK" if _fail == 0 else f"{_fail} fallo(s)")
    return 1 if _fail else 0


if __name__ == "__main__":
    sys.exit(main())
