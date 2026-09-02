"""Heurísticas de detección de posible manipulación del documento.

NO es un motor forense: son señales baratas y conservadoras que alimentan la
sub-bandera `sospecha_manipulacion` sobre PENDIENTE_REVISION (no bloquean el flujo,
solo alertan al auxiliar para que revise con más cuidado):

  • PDF de texto nativo: compara la fuente/tamaño de los campos clave (nombre, cédula,
    CIE-10, días, fecha_inicio, fecha_fin) contra la fuente dominante del documento.
    Requiere `PyMuPDF` (import perezoso); si no está instalado, se omite sin romper
    el pipeline. Umbral conservador: hacen falta 2+ campos con fuente distinta.
  • Imagen JPEG (subida directa o embebida dentro de un PDF sin capa de texto — p.ej.
    un escaneo o "imprimir a PDF" de una foto): Error Level Analysis (ELA) — busca una
    región compacta de alto error de recompresión que además coincida con una zona de
    texto/bordes. Experimental y de baja confianza; desactivada por defecto (env
    `AUTHENTICITY_IMAGE_CHECK=1` para activarla) porque no se ha calibrado contra un
    corpus grande de fotos reales.
  • Texto plano (PDF nativo, OCR de imagen o de visión — cualquier fuente): busca
    DOS O MÁS periodos de incapacidad (días + rango de fechas) distintos dentro del
    mismo documento. Un documento legítimo declara el periodo UNA sola vez; dos
    periodos que no coinciden es evidencia de un documento duplicado/pegado o de
    fechas alteradas sin recalcular el resto. No depende del tipo de archivo ni de
    dependencias opcionales — corre siempre, es solo un regex sobre `texto_plano`.

Fail-open: cualquier excepción interna se traduce en `sospechosa=False`, nunca se
propaga (un error en la heurística no debe tumbar el procesamiento del documento).
"""
from __future__ import annotations

import os
import re
from datetime import date
from pathlib import Path
from typing import Any

# Mismo umbral que `processor.MIN_OCR_CHARS` (duplicado aquí para no crear un
# import circular con processor.py, que es quien llama a este módulo).
_MIN_TEXTO_VECTORIAL = 10

_CAMPOS_CLAVE = ("cedula", "cie10", "dias", "fecha_inicio", "fecha_fin", "paciente")
_ETIQUETAS_CAMPO = {
    "cedula": "cédula", "cie10": "diagnóstico CIE-10", "dias": "días de incapacidad",
    "fecha_inicio": "fecha de inicio", "fecha_fin": "fecha fin", "paciente": "nombre del paciente",
}


def _valores_campos_clave(record: dict[str, Any] | None) -> dict[str, str]:
    """Extrae del record del extractor los valores crudos (como texto) de los campos clave."""
    if not record:
        return {}
    pac = record.get("paciente") or {}
    inca = record.get("incapacidad") or {}
    diag = record.get("diagnostico") or {}
    valores = {
        "cedula": pac.get("documento_numero"),
        "cie10": diag.get("cie10"),
        "dias": inca.get("dias"),
        "fecha_inicio": inca.get("fecha_inicio"),
        "fecha_fin": inca.get("fecha_fin"),
        "paciente": pac.get("nombre"),
    }
    return {k: str(v) for k, v in valores.items() if v not in (None, "")}


# "5 DIAS DESDE 09-06-26 HASTA EL 13-06-26" / "4 dias... desde el 29-07-26 hastael 01/07/29"
# (tolera que el OCR pegue palabras, p.ej. "HASTAEL"). Se usa `[^\n]` en vez de `.` para no
# cruzar de una línea/campo a otro por casualidad (evita falsos positivos entre secciones
# no relacionadas del documento).
_RE_PERIODO_INCAPACIDAD = re.compile(
    r"(\d{1,3})\s*d[ií]as?\b[^\n]{0,80}?desde\s*(?:el\s*)?([\d/\-]{6,10})[^\n]{0,20}?hasta\s*(?:el\s*)?([\d/\-]{6,10})",
    re.IGNORECASE,
)


def _revisar_periodos_multiples(texto_plano: str) -> dict[str, Any]:
    """Dos o más periodos de incapacidad (días + fechas) DISTINTOS en el mismo texto.

    Deliberadamente NO exige que las fechas sean válidas ni las reconcilia con la regla
    de negocio (eso ya lo hace `extract.normalizar_fechas`); aquí basta con detectar la
    duplicidad/discrepancia cruda como señal de alteración o de un documento pegado.
    """
    coincidencias = _RE_PERIODO_INCAPACIDAD.findall(texto_plano or "")
    if len(coincidencias) < 2:
        return {"sospechosa": False, "motivo": None, "detalle": {}}
    distintos = sorted(set(coincidencias))
    if len(distintos) < 2:
        return {"sospechosa": False, "motivo": None, "detalle": {"periodos_repetidos": len(coincidencias)}}
    resumen = "; ".join(f"{dias} días ({ini} a {fin})" for dias, ini, fin in distintos)
    return {
        "sospechosa": True,
        "motivo": f"Se detectaron periodos de incapacidad distintos en el mismo documento: {resumen}",
        "detalle": {"periodos": distintos},
    }


def _safe_date(s: Any) -> date | None:
    if not isinstance(s, str):
        return None
    try:
        return date.fromisoformat(s)
    except ValueError:
        return None


def _revisar_consistencia_fechas_dias(record: dict[str, Any] | None) -> dict[str, Any]:
    """Los días declarados deben coincidir con `fecha_fin − fecha_inicio + 1` (inclusive).

    Aritmética exacta, no depende de OCR de fuentes ni de imagen — barata y muy confiable:
    un documento legítimo nunca tiene esta discrepancia (si el auxiliar corrige un campo a
    mano, `erp.mapear_a_staging` recalcula el otro; esta señal es sobre lo que trae CRUDO
    el documento). Caso real que la motivó: "Días de incapacidad: 02" con
    "Desde: 05/06/2026 - Hasta: 06/07/2026" (32 días reales) — típico de una fecha fin
    alterada sin tocar el campo de días, o viceversa.
    """
    if not record:
        return {"sospechosa": False, "motivo": None, "detalle": {}}
    inca = record.get("incapacidad") or {}
    fecha_inicio = _safe_date(inca.get("fecha_inicio"))
    fecha_fin = _safe_date(inca.get("fecha_fin"))
    dias = inca.get("dias")
    if not (fecha_inicio and fecha_fin and isinstance(dias, int)):
        return {"sospechosa": False, "motivo": None, "detalle": {}}
    dias_por_fechas = (fecha_fin - fecha_inicio).days + 1
    # Tolerancia de 1 día: algunos formatos cuentan el rango de forma no inclusiva.
    if abs(dias_por_fechas - dias) <= 1:
        return {"sospechosa": False, "motivo": None,
                "detalle": {"dias_declarados": dias, "dias_por_fechas": dias_por_fechas}}
    motivo = (
        f"Los días declarados ({dias}) no coinciden con el rango de fechas del documento "
        f"({fecha_inicio.isoformat()} a {fecha_fin.isoformat()} = {dias_por_fechas} días)"
    )
    return {
        "sospechosa": True,
        "motivo": motivo,
        "detalle": {"dias_declarados": dias, "dias_por_fechas": dias_por_fechas},
    }


def _localizar(texto_completo: str, valor: str) -> int:
    """Offset del valor en el texto, evitando falsos matches de valores puramente
    numéricos cortos (p.ej. "2" días) dentro de OTRO número más largo (p.ej. la
    cédula "1020727050" contiene un "2"). Para valores 100% dígitos exige que no
    esté pegado a otro dígito; para el resto, substring simple."""
    if valor.isdigit():
        m = re.search(r"(?<!\d)" + re.escape(valor) + r"(?!\d)", texto_completo)
        return m.start() if m else -1
    return texto_completo.find(valor)


def _familia_base(nombre_fuente: str) -> str:
    """'Helvetica-Bold' / 'Helvetica,Italic' / 'ArialMT' -> 'helvetica'/'arial' (ignora
    negrita/itálico). El sufijo "MT"/"PSMT" (convención habitual en PDFs para el peso
    REGULAR, p.ej. "ArialMT", "TimesNewRomanPSMT") se despega aparte del "-Bold": sin
    esto, "ArialMT" y "Arial-BoldMT" quedaban como familias DISTINTAS (caso real:
    "arial" con 405 caracteres vs "arialmt" con 401 — casi empatados, por lo que
    cualquier campo en regular se veía "distinto" de uno en negrita — falso positivo
    sistemático del chequeo de fuentes)."""
    base = (nombre_fuente or "").split("+")[-1]  # subsets tipo "ABCDEF+Helvetica"
    base = base.split(",")[0].split("-")[0].strip().lower()
    for suf in ("psmt", "mt", "ps"):
        if base.endswith(suf) and len(base) > len(suf) + 2:
            base = base[: -len(suf)]
            break
    return base


def _revisar_fuentes_pdf(path: Path, texto_plano: str, record: dict[str, Any] | None) -> dict[str, Any]:
    try:
        import fitz  # PyMuPDF — import perezoso, dependencia opcional
    except ImportError:
        return {"sospechosa": False, "motivo": None, "detalle": {"omitido": "PyMuPDF no instalado"}}

    try:
        doc = fitz.open(str(path))
    except Exception:
        return {"sospechosa": False, "motivo": None, "detalle": {"omitido": "no se pudo abrir el PDF"}}

    try:
        if doc.page_count == 0:
            return {"sospechosa": False, "motivo": None, "detalle": {"omitido": "PDF sin páginas"}}
        texto_vectorial = sum(len(p.get_text()) for p in doc)
        # Se revisa el texto vectorial ANTES que los campos clave: si el PDF es
        # escaneado, `analizar_autenticidad` necesita ver exactamente este mensaje de
        # "omitido" para activar el fallback de ELA sobre la imagen embebida — si en
        # cambio se cortara antes por "sin campos clave" (p.ej. porque el OCR/extractor
        # no resolvió ningún campo), ese fallback nunca se dispararía.
        if texto_vectorial < _MIN_TEXTO_VECTORIAL:
            return {"sospechosa": False, "motivo": None, "detalle": {"omitido": "sin texto vectorial (PDF escaneado)"}}

        campos = _valores_campos_clave(record)
        if not campos:
            return {"sospechosa": False, "motivo": None, "detalle": {"omitido": "sin campos clave para comparar"}}

        # Recolecta spans en orden de lectura, concatenando texto para poder mapear offsets.
        spans: list[dict[str, Any]] = []  # {"texto","fuente","tamano","inicio","fin"}
        texto_concat = []
        cursor = 0
        for num_pagina, pagina in enumerate(doc):
            n_lineas_pagina = 0
            bloques = pagina.get_text("dict").get("blocks", [])
            total_lineas = sum(len(b.get("lines", [])) for b in bloques if b.get("type") == 0)
            for bloque in bloques:
                if bloque.get("type") != 0:
                    continue
                for linea in bloque.get("lines", []):
                    n_lineas_pagina += 1
                    es_borde = n_lineas_pagina <= 2 or n_lineas_pagina > total_lineas - 2
                    for span in linea.get("spans", []):
                        texto_span = span.get("text", "")
                        if not texto_span:
                            continue
                        inicio = cursor
                        texto_concat.append(texto_span)
                        cursor += len(texto_span)
                        spans.append({
                            "texto": texto_span,
                            "fuente": _familia_base(span.get("font", "")),
                            "tamano": round(span.get("size", 0) * 2) / 2,  # redondeo a 0.5pt
                            "inicio": inicio,
                            "fin": cursor,
                            "borde": es_borde,
                        })
                texto_concat.append("\n")
                cursor += 1

        if not spans:
            return {"sospechosa": False, "motivo": None, "detalle": {"omitido": "sin spans de texto"}}

        texto_completo = "".join(texto_concat)

        # Fuente dominante: la tupla (familia, tamaño) que cubre más caracteres, contando
        # cada span ÚNICO una sola vez. Sin este dedup, un watermark de fondo tileado
        # decenas de veces (visto en un caso real: "EPS SURA" repetido ~40 veces a tamaño
        # gigante) infla su cobertura y "gana" como dominante aunque sea decorativo, lo que
        # hace que TODO el contenido real del formulario se vea "distinto" — falso positivo
        # sistemático. Un span de contenido real casi nunca se repite idéntico (mismo
        # texto+fuente+tamaño) muchas veces; uno decorativo/watermark sí.
        cobertura: dict[tuple[str, float], int] = {}
        vistos: set[tuple[str, str, float]] = set()
        for sp in spans:
            clave_span = (sp["texto"], sp["fuente"], sp["tamano"])
            if clave_span in vistos:
                continue
            vistos.add(clave_span)
            clave = (sp["fuente"], sp["tamano"])
            cobertura[clave] = cobertura.get(clave, 0) + len(sp["texto"])
        dominante = max(cobertura, key=cobertura.get)

        campos_distintos: list[str] = []
        for campo, valor in campos.items():
            offset = _localizar(texto_completo, valor)
            if offset < 0:
                continue  # el valor normalizado no aparece literal en el texto crudo del PDF
            fin_valor = offset + len(valor)
            spans_del_campo = [
                sp for sp in spans
                if not sp["borde"] and sp["inicio"] < fin_valor and sp["fin"] > offset
            ]
            if not spans_del_campo:
                continue
            fuentes_campo = {(sp["fuente"], sp["tamano"]) for sp in spans_del_campo}
            if len(fuentes_campo) > 1:
                continue  # señal ambigua (campo autocompletado con varios spans) → se descarta
            (fuente_campo,) = fuentes_campo
            if fuente_campo != dominante:
                campos_distintos.append(_ETIQUETAS_CAMPO[campo])

        if len(campos_distintos) >= 2:
            motivo = f"Fuente inconsistente en: {', '.join(campos_distintos)}"
            return {"sospechosa": True, "motivo": motivo, "detalle": {"campos_distintos": campos_distintos}}
        return {"sospechosa": False, "motivo": None, "detalle": {"campos_distintos": campos_distintos}}
    finally:
        doc.close()


def _ela_desde_bytes(datos: bytes) -> dict[str, Any]:
    """Núcleo del Error Level Analysis: recibe los bytes crudos de una imagen (JPEG) y
    devuelve la señal de sospecha. Reutilizable tanto para archivos .jpg subidos
    directamente como para la imagen embebida dentro de un PDF escaneado."""
    try:
        import numpy as np
        from PIL import Image, ImageChops, ImageFilter
    except ImportError:
        return {"sospechosa": False, "motivo": None, "detalle": {"omitido": "Pillow/numpy no disponibles"}}

    import io

    try:
        original = Image.open(io.BytesIO(datos)).convert("L")
        buf = io.BytesIO()
        Image.open(io.BytesIO(datos)).convert("RGB").save(buf, "JPEG", quality=90)
        buf.seek(0)
        recomprimida = Image.open(buf).convert("L")
        if recomprimida.size != original.size:
            recomprimida = recomprimida.resize(original.size)
        diff = np.asarray(ImageChops.difference(original, recomprimida), dtype=np.float32)

        bordes = np.asarray(original.filter(ImageFilter.FIND_EDGES), dtype=np.float32)

        bloque = 16
        alto, ancho = diff.shape
        filas, cols = alto // bloque, ancho // bloque
        if filas < 2 or cols < 2:
            return {"sospechosa": False, "motivo": None, "detalle": {"omitido": "imagen demasiado pequeña"}}
        err_bloques = diff[: filas * bloque, : cols * bloque].reshape(filas, bloque, cols, bloque).mean(axis=(1, 3))
        bordes_bloques = bordes[: filas * bloque, : cols * bloque].reshape(filas, bloque, cols, bloque).mean(axis=(1, 3))

        mediana = float(np.median(err_bloques))
        if mediana <= 0:
            return {"sospechosa": False, "motivo": None, "detalle": {"omitido": "sin variación de compresión"}}
        umbral = mediana * 4
        alto_error = err_bloques >= umbral
        area_total = filas * cols
        area_alto_error = int(alto_error.sum())

        # (a) región compacta y pequeña: ≤15% del área total, y no vacía.
        condicion_area = 0 < area_alto_error <= 0.15 * area_total
        # (b) esa región se solapa con zona de bordes/texto (umbral relativo al propio bloque).
        condicion_bordes = bool(alto_error.any()) and float(bordes_bloques[alto_error].mean()) > float(bordes_bloques.mean()) * 1.5 if area_alto_error else False

        if condicion_area and condicion_bordes:
            return {
                "sospechosa": True,
                "motivo": "Posible edición localizada detectada (patrón de compresión inconsistente sobre texto)",
                "detalle": {"area_alto_error_pct": round(area_alto_error / area_total, 3)},
            }
        return {"sospechosa": False, "motivo": None, "detalle": {"area_alto_error_pct": round(area_alto_error / area_total, 3)}}
    except Exception:
        return {"sospechosa": False, "motivo": None, "detalle": {"omitido": "error en ELA"}}


def _revisar_artefactos_imagen(path: Path) -> dict[str, Any]:
    if os.environ.get("AUTHENTICITY_IMAGE_CHECK", "0") != "1":
        return {"sospechosa": False, "motivo": None, "detalle": {"omitido": "chequeo de imagen desactivado"}}
    try:
        return _ela_desde_bytes(path.read_bytes())
    except Exception:
        return {"sospechosa": False, "motivo": None, "detalle": {"omitido": "error en ELA"}}


def _revisar_imagen_embebida_pdf(path: Path) -> dict[str, Any]:
    """PDF sin capa de texto (escaneado/foto envuelta en PDF): en vez de omitir el
    documento por completo, extrae la imagen embebida más grande y corre ELA sobre
    sus bytes JPEG originales (con su historial real de compresión, a diferencia del
    PNG que produce `preprocess.pdf_to_images` al rasterizar para OCR)."""
    if os.environ.get("AUTHENTICITY_IMAGE_CHECK", "0") != "1":
        return {"sospechosa": False, "motivo": None, "detalle": {"omitido": "chequeo de imagen desactivado"}}
    try:
        import fitz
    except ImportError:
        return {"sospechosa": False, "motivo": None, "detalle": {"omitido": "PyMuPDF no instalado"}}
    try:
        doc = fitz.open(str(path))
    except Exception:
        return {"sospechosa": False, "motivo": None, "detalle": {"omitido": "no se pudo abrir el PDF"}}
    try:
        mejor: tuple[int, int] | None = None  # (area, xref)
        for pagina in doc:
            for img in pagina.get_images(full=True):
                xref, ancho, alto = img[0], img[2], img[3]
                area = (ancho or 0) * (alto or 0)
                if mejor is None or area > mejor[0]:
                    mejor = (area, xref)
        if mejor is None:
            return {"sospechosa": False, "motivo": None, "detalle": {"omitido": "sin imágenes embebidas"}}
        info = doc.extract_image(mejor[1])
        if info.get("ext", "").lower() not in ("jpg", "jpeg"):
            # ELA depende del historial de recompresión JPEG; PNG/otros formatos sin
            # pérdida no tienen esa señal.
            return {"sospechosa": False, "motivo": None, "detalle": {"omitido": f"imagen embebida no es JPEG ({info.get('ext')})"}}
        return _ela_desde_bytes(info["image"])
    except Exception:
        return {"sospechosa": False, "motivo": None, "detalle": {"omitido": "error extrayendo imagen del PDF"}}
    finally:
        doc.close()


def analizar_autenticidad(
    path: str | Path,
    texto_plano: str,
    record: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Devuelve {"sospechosa": bool, "motivo": str|None, "detalle": dict}.

    Fail-open: nunca lanza excepción; si ninguna heurística aplica o falla, devuelve
    `sospechosa=False`.
    """
    p = Path(path)
    suf = p.suffix.lower()
    resultado: dict[str, Any] = {"sospechosa": False, "motivo": None, "detalle": {}}
    try:
        if suf == ".pdf":
            resultado = _revisar_fuentes_pdf(p, texto_plano, record)
            # Sin texto vectorial (PDF escaneado/foto envuelta en PDF): el chequeo de
            # fuentes no tuvo con qué trabajar. En vez de quedarnos sin ninguna señal,
            # probamos ELA sobre la imagen embebida (si la hay y es JPEG).
            if resultado.get("detalle", {}).get("omitido") == "sin texto vectorial (PDF escaneado)":
                resultado = _revisar_imagen_embebida_pdf(p)
        elif suf in (".jpg", ".jpeg"):
            resultado = _revisar_artefactos_imagen(p)
    except Exception:
        resultado = {"sospechosa": False, "motivo": None, "detalle": {}}

    # Señales de texto/record (periodos múltiples, fechas↔días inconsistentes):
    # independientes del tipo de archivo, corren siempre y se COMBINAN (no
    # reemplazan) con la señal anterior — cualquiera que dispare, dispara el total.
    for revisor, arg in (
        (_revisar_periodos_multiples, texto_plano),
        (_revisar_consistencia_fechas_dias, record),
    ):
        try:
            extra = revisor(arg)
        except Exception:
            extra = {"sospechosa": False, "motivo": None, "detalle": {}}
        if not extra.get("sospechosa"):
            continue
        if resultado.get("sospechosa"):
            resultado = {
                "sospechosa": True,
                "motivo": f"{resultado['motivo']}; {extra['motivo']}",
                "detalle": {**resultado.get("detalle", {}), **extra.get("detalle", {})},
            }
        else:
            resultado = extra
    return resultado
