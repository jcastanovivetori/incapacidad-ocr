"""Capa ERP: convierte el JSON extraído en una fila de la tabla STAGING `lp_ausentismos_ia`.

Replica lo confirmado con Diana (mentoría Gruppo, 11 jun 2026):
  • NO se inserta en `lpausentismos` directo → se escribe en STAGING y el ERP promueve al aprobar.
  • Lookups que faltaban en la prueba de la Sesión 1:
      cédula → idlpempleado · CIE-10 → idlpdiagnosticos · EPS → idlpentidad
  • Homologación de tipo de ausentismo (texto → código 2/3/5/7/8/9/10/11/12), default 3.
  • PERMISOS (FORMATO SOLICITUD DE PERMISO): tipo 7 (no remunerada) / 12 (remunerada),
    sin diagnóstico ni EPS — ver ``es_permiso`` en ``mapear_a_staging``.
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
    7: "LICENCIA NO REMUNERADA", 8: "ENFERMEDAD LABORAL", 9: "LICENCIA PATERNIDAD",
    10: "PRELICENCIA", 11: "TRANSITO NO LABORAL", 12: "LICENCIA REMUNERADA",
    13: "VACACIONES",
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

# Nivel de incapacidad por defecto según tipo de ausentismo (Diana, 17-jul-2026).
# Estudiado contra el histórico real (lpausentismos + lpnivelincapacidad): ni los días
# ni el diagnóstico predicen el nivel de forma limpia (el mismo CIE-10 aparece en
# niveles distintos, y los rangos de días se solapan entre niveles) → es un juicio
# clínico del analista, no derivable del documento. Se deja un nivel por defecto por
# tipo (el más común/neutral en el histórico) y el auxiliar lo corrige en revisión si
# el caso lo amerita. Los permisos (tipo 7/12) no tienen niveles definidos en el ERP.
NIVEL_INCAPACIDAD_DEFAULT = {
    2: 2,    # ACCIDENTE DE TRABAJO -> LEVE
    3: 9,    # ENFERMEDAD GENERAL -> NO CRITICA
    5: 12,   # LICENCIA MATERNIDAD -> NO APLICA
    8: 7,    # ENFERMEDAD LABORAL -> NO CALIFICADA
    9: 13,   # LICENCIA PATERNIDAD -> NO APLICA.
    10: 14,  # PRELICENCIA -> NO APLICA..
    11: 11,  # TRANSITO NO LABORAL -> NO CRITICO
}
# Catálogo completo de `lpnivelincapacidad` (para mostrar la etiqueta en la UI y permitir
# que el auxiliar escoja otro nivel a mano, ej. escalar un accidente de LEVE a GRAVE).
ETIQUETAS_NIVEL = {
    1: "INDEFINIDO", 2: "LEVE", 3: "SEVERO", 4: "GRAVE", 5: "MORTAL",
    6: "CALIFICADA", 7: "NO CALIFICADA", 8: "CRITICA", 9: "NO CRITICA",
    10: "CRITICO", 11: "NO CRITICO", 12: "NO APLICA", 13: "NO APLICA.", 14: "NO APLICA..",
}


# --------------------------------------------------------------------------- #
# Validación documental: qué soportes exige cada tipo de ausentismo.
# --------------------------------------------------------------------------- #
# Normaliza el token de tipo de documento (del nombre del archivo o de la
# clasificación por OCR) al código canónico usado por los requisitos.
DOC_CANON = {
    "INCAPACIDAD": "INCAPACIDAD", "PERMISO": "PERMISO", "VACACIONES": "VACACIONES",
    "FURAT": "FURAT", "FURIPS": "FURIPS",
    "EPICRISIS": "EPICRISIS",
    "HISTORIA": "HISTORIA_CLINICA", "HISTORIACLINICA": "HISTORIA_CLINICA",
    "HISTORIA_CLINICA": "HISTORIA_CLINICA", "RESUMEN": "RESUMEN_ATENCION",
    "RESUMEN_ATENCION": "RESUMEN_ATENCION",
    "NACIDOVIVO": "CERTIFICADO_NACIDO_VIVO", "CERTIFICADO_NACIDO_VIVO": "CERTIFICADO_NACIDO_VIVO",
    "REGISTROCIVIL": "REGISTRO_CIVIL_NACIMIENTO", "REGISTRO_CIVIL_NACIMIENTO": "REGISTRO_CIVIL_NACIMIENTO",
    "DEFUNCION": "CERTIFICADO_DEFUNCION", "CEDULA": "CEDULA",
    "FORMULA": "FORMULA_MEDICA", "ORDEN": "ORDEN_MEDICA", "OTRO": "OTRO",
}
# Grupos de equivalencia: un documento requerido se satisface si hay algún
# documento presente del mismo grupo (p.ej. una EPICRISIS satisface "historia clínica").
EQUIVALENCIAS_DOC = [
    {"EPICRISIS", "HISTORIA_CLINICA", "RESUMEN_ATENCION"},
    {"CERTIFICADO_NACIDO_VIVO", "REGISTRO_CIVIL_NACIMIENTO"},
]
# Requisitos por tipo de ausentismo (default; `lprequisitos_eps` prevalece si tiene filas).
REQUISITOS_DEFAULT = {
    2: ["INCAPACIDAD", "FURAT"],
    3: ["INCAPACIDAD", "EPICRISIS"],  # soporte clínico (epicrisis/historia por equivalencia)
    5: ["INCAPACIDAD", "HISTORIA_CLINICA", "CERTIFICADO_NACIDO_VIVO"],
    7: ["PERMISO"], 8: ["INCAPACIDAD", "FURAT"],
    9: ["INCAPACIDAD", "REGISTRO_CIVIL_NACIMIENTO"], 10: ["INCAPACIDAD"],
    11: ["INCAPACIDAD", "FURIPS"], 12: ["PERMISO"], 13: ["VACACIONES"],
}


def canon_doc(token: Optional[str]) -> Optional[str]:
    """Token de tipo de documento → código canónico (o el token en mayúsculas si no mapea)."""
    if not token:
        return None
    clave = re.sub(r"[^A-Z_]", "", str(token).upper())
    return DOC_CANON.get(clave, clave or None)


def _grupo_doc(doc: str) -> set:
    for g in EQUIVALENCIAS_DOC:
        if doc in g:
            return g
    return {doc}


def validar_documentacion(presentes, id_tipo: Optional[int],
                          requeridos_tabla=None) -> tuple[str, list[str]]:
    """Cruza los documentos PRESENTES (canónicos) contra los requeridos por el tipo.

    ``requeridos_tabla`` (de `lprequisitos_eps`) prevalece; si no hay, usa REQUISITOS_DEFAULT.
    Devuelve (estado ∈ COMPLETA/INCOMPLETA, faltantes[]). Aplica grupos de equivalencia.
    """
    pres = {canon_doc(p) for p in (presentes or []) if p}
    if requeridos_tabla:
        requeridos = [canon_doc(d) for d in requeridos_tabla]
    else:
        requeridos = REQUISITOS_DEFAULT.get(id_tipo or 0, ["INCAPACIDAD"])
    faltantes = [r for r in requeridos if r and not (_grupo_doc(r) & pres)]
    return ("COMPLETA" if not faltantes else "INCOMPLETA"), faltantes


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
        self._cache_emp: dict[str, tuple[Optional[int], Optional[str], Optional[str]]] = {}
        self._cache_dx: dict[str, tuple[Optional[int], Optional[str]]] = {}
        self._entidades: Optional[list[tuple[int, str, int, str]]] = None  # (id, nombre_norm, tipo, nombre)
        self._empleados_nombre: Optional[list[tuple[int, str, str, str]]] = None  # (id, nombre, eps, clave)

    def _query(self, sql: str, params: tuple):
        cur = self._cx.cursor()
        try:
            cur.execute(sql, params)
            return cur.fetchall()
        finally:
            cur.close()

    def empleado_por_cedula(self, cedula: Optional[str]) -> tuple[Optional[int], Optional[str], Optional[str]]:
        """(idlpempleado, nombre_catalogo, eps_catalogo). El nombre del catálogo es AUTORITATIVO
        (corrige los nombres que el OCR deja pegados, p.ej. 'HERNANDEZSANDOVAL'). ``eps_catalogo``
        es la EPS asignada al empleado en `vlpempleados` (para la regla SOAT: la EPS real del
        empleado, no la aseguradora de tránsito que emite la incapacidad)."""
        if not cedula:
            return None, None, None
        ced = re.sub(r"\D", "", str(cedula))
        if not ced:
            return None, None, None
        if ced in self._cache_emp:
            return self._cache_emp[ced]
        filas = self._query(
            "SELECT idlpempleado, nombrecompleto, nombreeps FROM vlpempleados "
            "WHERE nroidentificacion = %s LIMIT 1", (ced,)
        )
        res = (int(filas[0][0]), filas[0][1], filas[0][2]) if filas else (None, None, None)
        self._cache_emp[ced] = res
        return res

    def id_empleado_por_cedula(self, cedula: Optional[str]) -> Optional[int]:
        return self.empleado_por_cedula(cedula)[0]

    def empleado_por_nombre(self, nombre: Optional[str]) -> tuple[Optional[int], Optional[str], Optional[str]]:
        """Respaldo cuando la cédula no resuelve: busca por nombre (sin espacios/tildes)."""
        if not nombre:
            return None, None, None
        leido = _norm(nombre).replace(" ", "")
        if len(leido) < 8:  # evita matches espurios con nombres muy cortos
            return None, None, None
        if self._empleados_nombre is None:
            filas = self._query("SELECT idlpempleado, nombrecompleto, nombreeps FROM vlpempleados", ())
            self._empleados_nombre = [(int(i), nm, eps, _norm(nm).replace(" ", "")) for (i, nm, eps) in filas]
        for idp, nm, eps_cat, clave in self._empleados_nombre:
            if clave and (clave == leido or clave in leido or leido in clave):
                return idp, nm, eps_cat
        return None, None, None

    def diagnostico_por_codigo(self, codigo: Optional[str]) -> tuple[Optional[int], Optional[str]]:
        if not codigo:
            return None, None
        key = str(codigo).replace(".", "").upper()
        if key in self._cache_dx:
            return self._cache_dx[key]
        # Comparación sin punto en ambos lados (J06.9 == J069).
        filas = self._query(
            "SELECT idlpdiagnosticos, descripcion FROM lpdiagnosticos "
            "WHERE REPLACE(codigo, '.', '') = %s LIMIT 1",
            (key,),
        )
        res = (int(filas[0][0]), filas[0][1]) if filas else (None, None)
        self._cache_dx[key] = res
        return res

    def id_entidad_por_nombre(self, nombre: Optional[str]) -> tuple[Optional[int], Optional[int], Optional[str]]:
        """Match por CONTENCIÓN: la palabra clave del catálogo dentro del nombre leído.
        Devuelve también el nombre TAL COMO está en el catálogo, para mostrarlo en la UI."""
        if not nombre:
            return None, None, None
        if self._entidades is None:
            filas = self._query("SELECT idlpeps, nombre, tipoentidad FROM vlpentidades_ss", ())
            # guardamos la clave sin espacios (el OCR suele pegar "SALUD TOTAL" → "SALUDTOTAL")
            self._entidades = [(int(i), _norm(n).replace(" ", ""), int(t), n) for (i, n, t) in filas]
        leido = _norm(nombre).replace(" ", "")
        for id_ent, clave, tipo, nombre_catalogo in self._entidades:
            if clave and clave in leido:
                return id_ent, tipo, nombre_catalogo
        return None, None, None

    def documentos_requeridos(self, id_entidad: Optional[int], id_tipo: Optional[int]) -> list[str]:
        if id_entidad is None or id_tipo is None:
            return []
        try:
            filas = self._query(
                "SELECT documento FROM lprequisitos_eps WHERE idlpentidad = %s AND idlptipoausentismo = %s",
                (id_entidad, id_tipo),
            )
        except Exception:
            # `lprequisitos_eps` no existe todavía en algunos entornos (p.ej. BD de
            # pruebas con el esquema real del ERP) — degrada a "sin requisitos".
            return []
        return [f[0] for f in filas]


class LookupsNulos:
    """Sin BD: todo None (la validación marcará los IDs como pendientes de revisión)."""

    def empleado_por_cedula(self, cedula):  # noqa: ARG002
        return None, None, None

    def empleado_por_nombre(self, nombre):  # noqa: ARG002
        return None, None, None

    def id_empleado_por_cedula(self, cedula):  # noqa: ARG002
        return None

    def diagnostico_por_codigo(self, codigo):  # noqa: ARG002
        return None, None

    def id_entidad_por_nombre(self, nombre):  # noqa: ARG002
        return None, None, None

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
    if inca.get("tipo_licencia"):
        partes.append(f"Tipo licencia: {inca['tipo_licencia']}")
    if inca.get("fecha_expedicion"):
        partes.append(f"Exp {inca['fecha_expedicion']}")
    return " | ".join(partes)[:500]


def _observaciones_permiso(etiqueta_tipo: Optional[str], perm: dict[str, Any]) -> str:
    partes = []
    if etiqueta_tipo:
        partes.append(etiqueta_tipo)
    if perm.get("empresa"):
        partes.append(f"Empresa: {perm['empresa']}")
    if perm.get("cargo"):
        partes.append(f"Cargo: {perm['cargo']}")
    if perm.get("detalle"):
        partes.append(f"Detalle: {perm['detalle']}")
    if perm.get("autorizado_por"):
        aut = perm["autorizado_por"]
        if perm.get("autorizado_cargo"):
            aut += f" ({perm['autorizado_cargo']})"
        partes.append(f"Autorizado por: {aut}")
    if perm.get("horas_total") or (perm.get("horas_desde") and perm.get("horas_hasta")):
        rango = f"{perm.get('horas_desde') or '?'}-{perm.get('horas_hasta') or '?'}"
        total = f" ({perm['horas_total']}h)" if perm.get("horas_total") else ""
        partes.append(f"Horas: {rango}{total}")
    if perm.get("fecha_solicitud"):
        partes.append(f"Solicitado {perm['fecha_solicitud']}")
    return " | ".join(partes)[:500]


def _num_dias(v: Any) -> Optional[int]:
    if isinstance(v, int):
        return v
    if isinstance(v, str) and v.strip().isdigit():
        return int(v.strip())
    return None


def mapear_a_staging(
    resultado: dict[str, Any],
    estado_recepcion: str = "WHATSAPP",
    lookups=None,
    hoy: Optional[date] = None,
    overrides: Optional[dict[str, Any]] = None,
    documentos_presentes=None,
) -> dict[str, Any]:
    """Construye la fila staging desde el resultado de ``process()``. No toca la BD.

    ``overrides`` permite que el AUXILIAR corrija/complete a mano los campos
    obligatorios (cédula, CIE-10, EPS, fecha de inicio, días, nombre, tipo); esos
    valores MANDAN sobre lo leído por el OCR y se vuelven a resolver los lookups.
    """
    hoy = hoy or date.today()
    lookups = lookups or LookupsNulos()
    overrides = {k: v for k, v in (overrides or {}).items() if v not in (None, "")}
    inc = resultado.get("incapacidad", {}) or {}
    pac = inc.get("paciente", {}) or {}
    ent = inc.get("entidad", {}) or {}
    inca = inc.get("incapacidad", {}) or {}
    diag = inc.get("diagnostico", {}) or {}
    perm = inc.get("permiso", {}) or {}
    # PERMISO (licencia remunerada/no remunerada): no lleva diagnóstico ni EPS.
    es_permiso = inc.get("tipo_documento") == "permiso"
    # VACACIONES (carta de notificación de periodo): tampoco lleva diagnóstico, EPS
    # ni nivel de incapacidad — tipo de ausentismo fijo 13, sin ambigüedad a resolver.
    es_vacaciones = inc.get("tipo_documento") == "vacaciones"

    # Valores efectivos: el override del auxiliar manda sobre lo leído por el OCR.
    cedula = overrides.get("cedula") or pac.get("documento_numero")
    cie = overrides.get("cie10") or diag.get("cie10")
    eps = overrides.get("eps") or ent.get("eps")
    fecha_inicio = overrides.get("fecha_inicio") or inca.get("fecha_inicio")
    fecha_fin = overrides.get("fecha_fin") or inca.get("fecha_fin")
    num_dias = _num_dias(overrides.get("dias")) if "dias" in overrides else _num_dias(inca.get("dias"))
    nombre_ocr = overrides.get("paciente") or pac.get("nombre")
    fecha_inicio_calculada = bool(inca.get("fecha_inicio_calculada")) and "fecha_inicio" not in overrides

    # Nunca se escribe una fecha inválida en la fila (protege el INSERT contra un
    # día/mes imposible que se cuele del OCR, del LLM o de un tecleo manual — MySQL
    # rechaza el registro completo con un 500 si llega algo como "2016-06-54").
    if fecha_inicio and not _safe_date(fecha_inicio):
        fecha_inicio = None
    if fecha_fin and not _safe_date(fecha_fin):
        fecha_fin = None
    estado = (estado_recepcion or "WHATSAPP").upper()
    if estado not in ESTADO_RECEPCION:
        estado = "WHATSAPP"

    # Regla del cliente (también al corregir a mano): si NO hay fecha de inicio pero sí
    # fecha final + días → inicio = fin − (días − 1). Recalcula al editar los días/el fin.
    if not fecha_inicio and fecha_fin and num_dias and 1 <= num_dias <= 540:
        _df = _safe_date(fecha_fin)
        if _df:
            fecha_inicio = (_df - timedelta(days=num_dias - 1)).isoformat()
            fecha_inicio_calculada = True
    # Simétrico: si hay inicio + fin pero NO días, se calculan por diferencia (inclusive).
    # Cubre p.ej. vacaciones donde el inicio vino del nombre del archivo y el fin del OCR.
    if fecha_inicio and fecha_fin and not num_dias:
        _di, _df = _safe_date(fecha_inicio), _safe_date(fecha_fin)
        if _di and _df and 1 <= (_df - _di).days + 1 <= 540:
            num_dias = (_df - _di).days + 1

    problemas: list[str] = []
    faltantes_campos: list[dict[str, Any]] = []  # campos OBLIGATORIOS para revisión manual

    def _faltan(campo: str, etiqueta: str, valor: Any) -> None:
        faltantes_campos.append({"campo": campo, "etiqueta": etiqueta, "valor": valor})

    # Regla de negocio (Diana, 16-17 jul 2026): toda incapacidad emitida por una
    # aseguradora SOAT (accidente de tránsito) se marca como tránsito no laboral,
    # independientemente de la causa/origen que diga el documento; y la EPS a
    # asignar es la propia del empleado en el catálogo (`vlpempleados`), no la
    # aseguradora de tránsito que emitió la incapacidad.
    es_soat = bool(eps) and "soat" in _norm(eps)

    # Homologación de tipo (override manual de código si llega; si no, texto del doc).
    if _num_dias(overrides.get("tipo")) in ETIQUETAS_TIPO:
        id_tipo = _num_dias(overrides.get("tipo"))
        etiqueta_tipo = ETIQUETAS_TIPO[id_tipo]
    elif es_permiso:
        # Checkbox "Remunerado" / "No Remunerado" del FORMATO SOLICITUD DE PERMISO.
        id_tipo = {"REMUNERADO": 12, "NO_REMUNERADO": 7}.get(perm.get("tipo_remunerado"))
        etiqueta_tipo = ETIQUETAS_TIPO.get(id_tipo)
    elif es_vacaciones:
        id_tipo, etiqueta_tipo = 13, ETIQUETAS_TIPO[13]
    elif es_soat:
        id_tipo, etiqueta_tipo = 11, ETIQUETAS_TIPO[11]
    else:
        texto_tipo = " ".join(filter(None, [
            inca.get("tipo"), inca.get("origen"), diag.get("descripcion"),
            (resultado.get("texto_plano") or "")[:2000],
        ]))
        id_tipo, etiqueta_tipo = homologar_tipo(texto_tipo)
    if es_permiso and id_tipo is None:
        problemas.append("No se identificó si el permiso es remunerado o no remunerado")
        _faltan("tipo", "Tipo de permiso", None)

    id_nivel = _num_dias(overrides.get("nivel"))
    if id_nivel is None:
        id_nivel = NIVEL_INCAPACIDAD_DEFAULT.get(id_tipo) if id_tipo is not None else None

    # --- Empleado: por cédula (nombre del catálogo es AUTORITATIVO). Si la cédula no
    #     resuelve, intentamos por NOMBRE como respaldo (recupera un campo obligatorio).
    id_empleado, nombre_catalogo, eps_empleado = lookups.empleado_por_cedula(cedula)
    if id_empleado is None and nombre_ocr:
        id_empleado, nombre_catalogo, eps_empleado = lookups.empleado_por_nombre(nombre_ocr)
    if not cedula and id_empleado is None:
        problemas.append("No se detectó la cédula del paciente")
        _faltan("cedula", "Cédula del paciente", None)
    elif id_empleado is None:
        problemas.append(f"Cédula {cedula} no encontrada en empleados")
        _faltan("cedula", "Cédula del paciente", cedula)
    # El nombre del catálogo corrige los nombres pegados por el OCR (HERNANDEZSANDOVAL).
    paciente_final = nombre_catalogo or nombre_ocr

    if es_permiso or es_vacaciones:
        # Los permisos y las vacaciones no llevan diagnóstico.
        id_dx, desc_dx = None, None
    else:
        id_dx, desc_dx = lookups.diagnostico_por_codigo(cie)
        if not cie:
            problemas.append("No se detectó el código de diagnóstico (CIE-10)")
            _faltan("cie10", "Código CIE-10", None)
        elif id_dx is None:
            problemas.append(f"Diagnóstico {cie} no está en el catálogo CIE-10")
            _faltan("cie10", "Código CIE-10", cie)

    eps_de_empleado = False
    if es_permiso or es_vacaciones:
        # Los permisos y las vacaciones no llevan EPS/entidad — no aplica ni se pide.
        id_ent, tipo_ent, nombre_entidad = None, None, None
    else:
        # EPS: para SOAT (aseguradora de tránsito, nunca es la EPS real del paciente)
        # vamos directo a la EPS del empleado en el catálogo. En cualquier otro caso,
        # probamos primero lo leído en el documento; si no es claro (vacío o no matchea
        # ningún nombre del catálogo), también respaldamos con la EPS del empleado.
        if es_soat:
            id_ent, tipo_ent, nombre_entidad = None, None, None
        else:
            id_ent, tipo_ent, nombre_entidad = lookups.id_entidad_por_nombre(eps)
        if id_ent is None and eps_empleado:
            id_ent, tipo_ent, nombre_entidad = lookups.id_entidad_por_nombre(eps_empleado)
            eps_de_empleado = id_ent is not None
        if id_ent is None:
            id_ent, tipo_ent = 1, 1  # default + aviso
            if es_soat:
                problemas.append("SOAT: no se pudo determinar la EPS del empleado en el catálogo")
            else:
                problemas.append("EPS no identificada en el documento")
            _faltan("eps", "EPS / Entidad", eps)

    # Fechas / días (campos obligatorios). Una fecha de inicio CALCULADA (fin − días)
    # es un valor válido según la regla del cliente: NO bloquea, pero se avisa en la UI
    # (campo ``fecha_inicio_calculada``) para que el revisor lo confirme si quiere.
    if not fecha_inicio:
        problemas.append("No se detectó la fecha de inicio")
        _faltan("fecha_inicio", "Fecha de inicio", None)
    if not num_dias:
        problemas.append("No se detectó el número de días")
        _faltan("dias", "Días de incapacidad", None)
    elif not (1 <= num_dias <= 540):
        problemas.append(f"Número de días fuera de rango (={num_dias})")
        _faltan("dias", "Días de incapacidad", num_dias)

    fecha_venc = None
    di = _safe_date(fecha_inicio)
    if di and num_dias and 1 <= num_dias <= 540:
        fecha_venc = (di + timedelta(days=num_dias)).isoformat()  # inicio + dias

    # "Confianza": completitud de los campos núcleo (no tenemos score de OCR aún).
    # Los permisos y vacaciones no llevan CIE-10, así que no cuenta para su completitud.
    nucleo = [cedula, fecha_inicio, num_dias] if (es_permiso or es_vacaciones) \
        else [cedula, cie, fecha_inicio, num_dias]
    confianza = round(sum(1 for x in nucleo if x) / len(nucleo), 3)

    # Requisitos documentales. Si el lote pasa los documentos REALES presentes del caso
    # (por nombre/nomenclatura), se valida contra ellos con grupos de equivalencia; si no,
    # se degrada al comportamiento simple (asume que llegó la INCAPACIDAD).
    requeridos_tabla = lookups.documentos_requeridos(id_ent, id_tipo) or None
    if documentos_presentes is not None:
        # Permisos y vacaciones NO exigen incapacidad: su requisito base es el propio
        # documento (aunque el tipo remunerado/no-remunerado no se haya podido leer).
        if es_permiso:
            doc_estado, faltantes = validar_documentacion(documentos_presentes, None, ["PERMISO"])
        elif es_vacaciones:
            doc_estado, faltantes = validar_documentacion(documentos_presentes, None, ["VACACIONES"])
        else:
            doc_estado, faltantes = validar_documentacion(documentos_presentes, id_tipo, requeridos_tabla)
        if faltantes:
            problemas.append("Faltan documentos requeridos: " + ", ".join(faltantes))
    else:
        requeridos = requeridos_tabla or []
        faltantes = [d for d in requeridos if d != "INCAPACIDAD"]
        doc_estado = "COMPLETA" if not faltantes else "INCOMPLETA"

    observaciones = (
        _observaciones_permiso(etiqueta_tipo, perm) if es_permiso
        else _observaciones(
            etiqueta_tipo,
            None if es_vacaciones else cie,
            None if es_vacaciones else (desc_dx or diag.get("descripcion")),
            inca,
        )
    )

    row = {
        "fecharegistro": hoy.isoformat(),
        "fechaaccidente": None,
        "fechainicio": fecha_inicio,
        "Numerodias": num_dias,
        "fechavencimiento": fecha_venc,
        "numeroorden": overrides.get("numeroorden"),
        "observaciones": observaciones,
        "original": 1 if estado == "ORIGINAL" else 0,
        "idlpdiagnosticos": id_dx,
        "idlpempleado": id_empleado,
        "idlptipoausentismo": id_tipo,
        "idlpnivelincapacidad": id_nivel,
        "idlpentidad": id_ent,
        "tipoentidad": tipo_ent,
        "idlpestadosrecepausentismos": ESTADO_RECEPCION[estado],
        "cedula_leida": cedula,
        "codigo_diagnostico_leido": None if (es_permiso or es_vacaciones) else cie,
        "eps_leida": None if (es_permiso or es_vacaciones) else eps,
        "paciente_leido": paciente_final,
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
        "campos_faltantes": faltantes_campos,
        "tipo_ausentismo": etiqueta_tipo,
        "nivel_incapacidad": ETIQUETAS_NIVEL.get(id_nivel),
        "estado_recepcion": estado,
        "documentos_faltantes": faltantes,
        "paciente_catalogo": nombre_catalogo,
        "paciente_ocr": nombre_ocr,
        "entidad_catalogo": nombre_entidad,
        "eps_de_empleado": eps_de_empleado,
        "fecha_inicio_calculada": fecha_inicio_calculada,
    }
