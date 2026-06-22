"""Capa ERP: convierte el JSON extraído en una fila de la tabla STAGING `lp_ausentismos_ia`.

Replica lo confirmado con Diana (mentoría Gruppo, 11 jun 2026):
  • NO se inserta en `lpausentismos` directo → se escribe en STAGING y el ERP promueve al aprobar.
  • Lookups que faltaban en la prueba de la Sesión 1:
      cédula → idlpempleado · CIE-10 → idlpdiagnosticos · EPS → idlpentidad
  • Homologación de tipo de ausentismo (texto → código 2/3/5/8/9/10/11), default 3.
  • fecha_registro = hoy · fechavencimiento = fecha_inicio + Numerodias.
  • Si falta un dato CRÍTICO (empleado/diagnóstico/EPS/fecha/días) → `requiere_revision`.

100% local: solo consulta la BD de catálogos (sin internet).
"""
from __future__ import annotations

import re
import unicodedata
from datetime import date, timedelta
from typing import Any, Optional

# Estados de recepción (códigos placeholder — confirmar con el catálogo real del ERP).
ESTADO_RECEPCION = {"ORIGINAL": 1, "WHATSAPP": 2, "CORREO": 3}

# Etiquetas de tipo de ausentismo (códigos entregados por Diana).
ETIQUETAS_TIPO = {
    2: "ACCIDENTE DE TRABAJO", 3: "ENFERMEDAD GENERAL", 5: "LICENCIA MATERNIDAD",
    8: "ENFERMEDAD LABORAL", 9: "LICENCIA PATERNIDAD", 10: "PRELICENCIA",
    11: "TRANSITO NO LABORAL",
}
# Reglas palabra-clave → código (orden: de más específica a más general). Default 3.
_REGLAS_TIPO = [
    (r"accidente.*trabajo|accidente laboral", 2),
    (r"enfermedad laboral", 8),
    (r"licencia.*maternidad|maternidad", 5),
    (r"licencia.*paternidad|paternidad", 9),
    (r"prelicencia", 10),
    (r"transito", 11),
    (r"enfermedad general|enfermedad comun|comun", 3),
]
_TIPO_DEFAULT = 3


def _norm(texto: str) -> str:
    s = (texto or "").lower()
    s = "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn")
    return re.sub(r"\s+", " ", s).strip()


def homologar_tipo(texto: str) -> tuple[int, str]:
    """Texto del documento → (código, etiqueta) de tipo de ausentismo."""
    t = _norm(texto)
    for patron, codigo in _REGLAS_TIPO:
        if re.search(patron, t):
            return codigo, ETIQUETAS_TIPO[codigo]
    return _TIPO_DEFAULT, ETIQUETAS_TIPO[_TIPO_DEFAULT]


def _safe_date(s: Any) -> Optional[date]:
    if not isinstance(s, str):
        return None
    try:
        return date.fromisoformat(s)
    except ValueError:
        return None


# --------------------------------------------------------------------------- #
# Lookups (cédula/CIE/EPS) contra los catálogos en MySQL, con caché en memoria.
# --------------------------------------------------------------------------- #
class Lookups:
    def __init__(self, conexion) -> None:
        self._cx = conexion
        self._cache_emp: dict[str, Optional[int]] = {}
        self._cache_dx: dict[str, tuple[Optional[int], Optional[str]]] = {}
        self._entidades: Optional[list[tuple[int, str, int]]] = None  # (id, nombre_norm, tipo)

    def _query(self, sql: str, params: tuple):
        cur = self._cx.cursor()
        try:
            cur.execute(sql, params)
            return cur.fetchall()
        finally:
            cur.close()

    def id_empleado_por_cedula(self, cedula: Optional[str]) -> Optional[int]:
        if not cedula:
            return None
        ced = re.sub(r"\D", "", str(cedula))
        if ced in self._cache_emp:
            return self._cache_emp[ced]
        filas = self._query("SELECT idlpempleado FROM lpempleados WHERE cedula = %s LIMIT 1", (ced,))
        res = int(filas[0][0]) if filas else None
        self._cache_emp[ced] = res
        return res

    def diagnostico_por_codigo(self, codigo: Optional[str]) -> tuple[Optional[int], Optional[str]]:
        if not codigo:
            return None, None
        key = str(codigo).replace(".", "").upper()
        if key in self._cache_dx:
            return self._cache_dx[key]
        # Comparación sin punto en ambos lados (J06.9 == J069).
        filas = self._query(
            "SELECT idlpdiagnosticos, descripcion FROM lpdiagnosticos "
            "WHERE REPLACE(codigo_cie10, '.', '') = %s LIMIT 1",
            (key,),
        )
        res = (int(filas[0][0]), filas[0][1]) if filas else (None, None)
        self._cache_dx[key] = res
        return res

    def id_entidad_por_nombre(self, nombre: Optional[str]) -> tuple[Optional[int], Optional[int]]:
        """Match por CONTENCIÓN: la palabra clave del catálogo dentro del nombre leído."""
        if not nombre:
            return None, None
        if self._entidades is None:
            filas = self._query("SELECT idlpentidad, nombre, tipoentidad FROM lpentidades", ())
            # guardamos la clave sin espacios (el OCR suele pegar "SALUD TOTAL" → "SALUDTOTAL")
            self._entidades = [(int(i), _norm(n).replace(" ", ""), int(t)) for (i, n, t) in filas]
        leido = _norm(nombre).replace(" ", "")
        for id_ent, clave, tipo in self._entidades:
            if clave and clave in leido:
                return id_ent, tipo
        return None, None

    def documentos_requeridos(self, id_entidad: Optional[int], id_tipo: Optional[int]) -> list[str]:
        if id_entidad is None or id_tipo is None:
            return []
        filas = self._query(
            "SELECT documento FROM lprequisitos_eps WHERE idlpentidad = %s AND idlptipoausentismo = %s",
            (id_entidad, id_tipo),
        )
        return [f[0] for f in filas]


class LookupsNulos:
    """Sin BD: todo None (la validación marcará los IDs como pendientes de revisión)."""

    def id_empleado_por_cedula(self, cedula):  # noqa: ARG002
        return None

    def diagnostico_por_codigo(self, codigo):  # noqa: ARG002
        return None, None

    def id_entidad_por_nombre(self, nombre):  # noqa: ARG002
        return None, None

    def documentos_requeridos(self, id_entidad, id_tipo):  # noqa: ARG002
        return []


# --------------------------------------------------------------------------- #
# Mapeo: JSON extraído → fila de lp_ausentismos_ia (+ problemas / revisión)
# --------------------------------------------------------------------------- #
def _observaciones(etiqueta_tipo, cie, desc, inca) -> str:
    partes = []
    if etiqueta_tipo:
        partes.append(etiqueta_tipo)
    if cie and desc:
        partes.append(f"DX {cie} - {desc}")
    elif cie:
        partes.append(f"DX {cie}")
    elif desc:
        partes.append(desc)
    if inca.get("fecha_expedicion"):
        partes.append(f"Exp {inca['fecha_expedicion']}")
    return " | ".join(partes)[:500]


def mapear_a_staging(
    resultado: dict[str, Any],
    estado_recepcion: str = "WHATSAPP",
    lookups=None,
    hoy: Optional[date] = None,
) -> dict[str, Any]:
    """Construye la fila staging desde el resultado de ``process()``. No toca la BD."""
    hoy = hoy or date.today()
    lookups = lookups or LookupsNulos()
    inc = resultado.get("incapacidad", {}) or {}
    pac = inc.get("paciente", {}) or {}
    ent = inc.get("entidad", {}) or {}
    inca = inc.get("incapacidad", {}) or {}
    diag = inc.get("diagnostico", {}) or {}

    cedula = pac.get("documento_numero")
    cie = diag.get("cie10")
    eps = ent.get("eps")
    fecha_inicio = inca.get("fecha_inicio")
    num_dias = inca.get("dias")
    estado = (estado_recepcion or "WHATSAPP").upper()
    if estado not in ESTADO_RECEPCION:
        estado = "WHATSAPP"

    problemas: list[str] = []

    # Homologación de tipo (usa tipo/origen/descr + algo del texto OCR como respaldo).
    texto_tipo = " ".join(filter(None, [
        inca.get("tipo"), inca.get("origen"), diag.get("descripcion"),
        (resultado.get("texto_plano") or "")[:2000],
    ]))
    id_tipo, etiqueta_tipo = homologar_tipo(texto_tipo)

    # Lookups (los que faltaban en la prueba de la Sesión 1).
    id_empleado = lookups.id_empleado_por_cedula(cedula)
    if not cedula:
        problemas.append("No se detectó la cédula del paciente")
    elif id_empleado is None:
        problemas.append(f"Cédula {cedula} no encontrada en empleados")

    id_dx, desc_dx = lookups.diagnostico_por_codigo(cie)
    if not cie:
        problemas.append("No se detectó el código de diagnóstico (CIE-10)")
    elif id_dx is None:
        problemas.append(f"Diagnóstico {cie} no está en el catálogo CIE-10")

    id_ent, tipo_ent = lookups.id_entidad_por_nombre(eps)
    if id_ent is None:
        id_ent, tipo_ent = 1, 1  # default + aviso (regla del prompt de Diana)
        problemas.append("EPS no identificada en el documento")

    # Fechas / días.
    if not fecha_inicio:
        problemas.append("No se detectó la fecha de inicio")
    if not num_dias:
        problemas.append("No se detectó el número de días")
    elif not (1 <= int(num_dias) <= 540):
        problemas.append(f"Número de días fuera de rango (={num_dias})")

    fecha_venc = None
    di = _safe_date(fecha_inicio)
    if di and num_dias and 1 <= int(num_dias) <= 540:
        fecha_venc = (di + timedelta(days=int(num_dias))).isoformat()  # inicio + dias

    # "Confianza": completitud de los campos núcleo (no tenemos score de OCR aún).
    nucleo = [cedula, cie, fecha_inicio, num_dias]
    confianza = round(sum(1 for x in nucleo if x) / len(nucleo), 3)

    # Requisitos documentales → faltantes (asume que llegó la INCAPACIDAD).
    requeridos = lookups.documentos_requeridos(id_ent, id_tipo)
    faltantes = [d for d in requeridos if d != "INCAPACIDAD"]
    doc_estado = "COMPLETA" if not faltantes else "INCOMPLETA"

    row = {
        "fecharegistro": hoy.isoformat(),
        "fechaaccidente": None,
        "fechainicio": fecha_inicio,
        "Numerodias": int(num_dias) if num_dias else None,
        "fechavencimiento": fecha_venc,
        "numeroorden": None,
        "observaciones": _observaciones(etiqueta_tipo, cie, desc_dx or diag.get("descripcion"), inca),
        "original": 1 if estado == "ORIGINAL" else 0,
        "idlpdiagnosticos": id_dx,
        "idlpempleado": id_empleado,
        "idlptipoausentismo": id_tipo,
        "idlpentidad": id_ent,
        "tipoentidad": tipo_ent,
        "idlpestadosrecepausentismos": ESTADO_RECEPCION[estado],
        "cedula_leida": cedula,
        "codigo_diagnostico_leido": cie,
        "eps_leida": eps,
        "paciente_leido": pac.get("nombre"),
        "confianza_ocr": confianza,
        "ocr_backend": resultado.get("ocr_backend"),
        "extractor": resultado.get("extractor"),
        "archivo_origen": resultado.get("fuente"),
        "problemas": "; ".join(problemas) or None,
        "documentacion_estado": doc_estado,
        "documentos_faltantes": ", ".join(faltantes) or None,
        "estado": "PENDIENTE_REVISION",
    }
    return {
        "row": row,
        "requiere_revision": len(problemas) > 0,
        "problemas": problemas,
        "tipo_ausentismo": etiqueta_tipo,
        "estado_recepcion": estado,
        "documentos_faltantes": faltantes,
    }
