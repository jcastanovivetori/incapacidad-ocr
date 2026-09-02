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

import json
import logging
import re
import unicodedata
from datetime import date, timedelta
from typing import Any, Optional

from . import reglas_tiempo

log = logging.getLogger("incapacidad_ocr.erp")

# Estados de recepción (códigos placeholder — confirmar con el catálogo real del ERP).
ESTADO_RECEPCION = {"ORIGINAL": 1, "WHATSAPP": 2, "CORREO": 3}

# Estado de flujo aparte de PENDIENTE_REVISION: cuando `analizar_autenticidad` (o las
# señales adicionales de CIE-10/fechas de abajo) marcan `sospecha_manipulacion`, el
# registro entra a staging con este estado en vez de PENDIENTE_REVISION, para que
# quede fácilmente identificable en la bandeja sin depender solo del badge DUDOSA.
ESTADO_POSIBLE_MANIPULACION = "POSIBLE_MANIPULACION"

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
    # documentos que solo exige la RADICACIÓN ante la EPS (ver checklist_radicacion)
    "SOAT": "SOAT", "RAT": "RAT", "DESCARTE": "DESCARTE_EVENTO_LABORAL",
    "DESCARTE_EVENTO_LABORAL": "DESCARTE_EVENTO_LABORAL",
    "CERTIFICADOLABORAL": "CERTIFICADO_LABORAL", "CERTIFICADO_LABORAL": "CERTIFICADO_LABORAL",
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


# --------------------------------------------------------------------------- #
# Radicación ante la EPS: el paquete que hay que armar para COBRAR la incapacidad.
# Es una exigencia distinta (y casi siempre mayor) a la de la recepción interna:
# sale del JSON `lpeps.cheklistradicaciones`, que cada EPS configura por tipo de
# ausentismo. Se avisa desde la ingesta, pero NO bloquea: el caso entra a staging
# igual y el auxiliar consigue lo que falte antes de radicar.
# --------------------------------------------------------------------------- #
# Nombre del documento TAL COMO lo escribe el ERP en el JSON → código canónico nuestro.
# (Las claves van normalizadas: mayúsculas, sin tildes, un solo espacio. "CERTICADO
# LABORAL" viene así, con el error de digitación, en los datos del ERP.)
RADICACION_DOC_CANON = {
    "CERTIFICADO DE INCAPACIDAD": "INCAPACIDAD",
    "HISTORIA CLINICA": "HISTORIA_CLINICA",
    "CEDULA DEL TRABAJADOR": "CEDULA",
    "CERTIFICADO NACIDO VIVO": "CERTIFICADO_NACIDO_VIVO",
    "REGISTRO CIVIL": "REGISTRO_CIVIL_NACIMIENTO",
    "SOAT": "SOAT",
    "REPORTE ACCIDENTE DE TRANSITO RAT": "RAT",
    "FORMATO DE DESCARTE EVENTO LABORAL": "DESCARTE_EVENTO_LABORAL",
    "FURIPS": "FURIPS",
    "CERTICADO LABORAL": "CERTIFICADO_LABORAL",
    "CERTIFICADO LABORAL": "CERTIFICADO_LABORAL",
}
# Etiquetas legibles para el aviso al auxiliar (el código canónico es para la lógica).
ETIQUETAS_DOC = {
    "INCAPACIDAD": "certificado de incapacidad",
    "HISTORIA_CLINICA": "historia clínica",
    "EPICRISIS": "epicrisis",
    "RESUMEN_ATENCION": "resumen de atención",
    "CEDULA": "cédula del trabajador",
    "CERTIFICADO_NACIDO_VIVO": "certificado de nacido vivo",
    "REGISTRO_CIVIL_NACIMIENTO": "registro civil",
    "SOAT": "SOAT",
    "RAT": "reporte de accidente de tránsito (RAT)",
    "DESCARTE_EVENTO_LABORAL": "formato de descarte de evento laboral",
    "FURIPS": "FURIPS",
    "FURAT": "FURAT",
    "CERTIFICADO_LABORAL": "certificado laboral",
}


def etiqueta_doc(codigo: str) -> str:
    return ETIQUETAS_DOC.get(codigo, (codigo or "").replace("_", " ").lower())


def _canon_doc_radicacion(nombre: str) -> Optional[str]:
    """Nombre del documento en el JSON del ERP → código canónico."""
    txt = "".join(c for c in unicodedata.normalize("NFD", str(nombre or "").upper())
                  if unicodedata.category(c) != "Mn")
    txt = re.sub(r"[^A-Z ]", " ", txt)
    txt = re.sub(r"\s+", " ", txt).strip()
    if not txt:
        return None
    return RADICACION_DOC_CANON.get(txt) or canon_doc(txt.replace(" ", "_"))


def documentos_checklist_radicacion(json_texto: Optional[str], id_tipo: Optional[int]) -> list[str]:
    """Parsea `lpeps.cheklistradicaciones` y devuelve los documentos (canónicos) del tipo.

    El ERP guarda el JSON ENVUELTO en comillas dobles sin escapar el contenido
    (``"{"ausentismos":[...]}"``), así que no es JSON válido tal cual: hay que quitar
    esas comillas externas antes de parsear. Formato real:
    ``{"ausentismos":[{"idlptipoausentismo":N, "documentos":[{"nombredocumento":"..."}]}]}``
    Devuelve [] si el campo está vacío, es ilegible o el tipo no está configurado.
    """
    if not json_texto or id_tipo is None:
        return []
    texto = str(json_texto).strip()
    if len(texto) > 1 and texto[0] == '"' and texto[-1] == '"':
        texto = texto[1:-1]
    try:
        datos = json.loads(texto)
        if isinstance(datos, str):          # por si algún día queda bien serializado
            datos = json.loads(datos)
    except (ValueError, TypeError):
        return []
    if not isinstance(datos, dict):
        return []
    for aus in datos.get("ausentismos") or []:
        if not isinstance(aus, dict):
            continue
        try:
            if int(aus.get("idlptipoausentismo")) != int(id_tipo):
                continue
        except (TypeError, ValueError):
            continue
        docs = []
        for d in aus.get("documentos") or []:
            codigo = _canon_doc_radicacion((d or {}).get("nombredocumento"))
            if codigo and codigo not in docs:
                docs.append(codigo)
        return docs
    return []


def validar_radicacion(presentes, requeridos) -> tuple[Optional[str], list[str]]:
    """Cruza los documentos presentes contra los que la EPS exige para RADICAR.

    Devuelve (estado ∈ COMPLETA/INCOMPLETA | None si la EPS no tiene checklist, faltantes[]).
    Aplica las mismas equivalencias que la recepción, PERO solo entre documentos que la EPS
    no pidió por separado: si el checklist exige nacido vivo Y registro civil, se exigen los
    dos (uno no cubre al otro).
    """
    if not requeridos:
        return None, []
    pres = {canon_doc(p) for p in (presentes or []) if p}
    req = [canon_doc(r) for r in requeridos if r]
    faltantes = []
    for r in req:
        equivalentes = (_grupo_doc(r) - set(req)) | {r}
        if not (equivalentes & pres):
            faltantes.append(r)
    return ("COMPLETA" if not faltantes else "INCOMPLETA"), faltantes


def _norm(texto: str) -> str:
    s = (texto or "").lower()
    s = "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn")
    return re.sub(r"\s+", " ", s).strip()


# Palabras vacías del español que no aportan a comparar dos descripciones de diagnóstico
# (conectores/artículos muy frecuentes; NO son términos clínicos).
_STOPWORDS_DX = {
    "de", "del", "la", "el", "los", "las", "en", "con", "por", "sin", "no", "y", "o",
    "u", "al", "sus", "otra", "otro", "otras", "otros", "no especificada", "especificada",
}


def _palabras_significativas(texto: str) -> set[str]:
    palabras = re.findall(r"[a-z]+", _norm(texto))
    return {p for p in palabras if len(p) > 3 and p not in _STOPWORDS_DX}


def _diagnostico_coincide(desc_catalogo: Optional[str], desc_documento: Optional[str]) -> Optional[bool]:
    """¿El texto del diagnóstico que trae el documento es compatible con la descripción
    OFICIAL del código CIE-10 en el catálogo? Comparación conservadora por solapamiento
    de palabras significativas (no exige coincidencia exacta: cada IPS redacta distinto).

    Devuelve None si no se puede evaluar con confianza (falta alguna descripción, o
    son demasiado cortas) — en ese caso NO se reporta nada, se prefiere no opinar.
    """
    if not desc_catalogo or not desc_documento:
        return None
    sig_cat = _palabras_significativas(desc_catalogo)
    sig_doc = _palabras_significativas(desc_documento)
    if len(sig_cat) < 2 or len(sig_doc) < 2:
        return None
    return bool(sig_cat & sig_doc)


def homologar_tipo(texto: str) -> tuple[int, str]:
    """Texto del documento → (código, etiqueta) de tipo de ausentismo."""
    t = _norm(texto)
    for patron, codigo in _REGLAS_TIPO:
        if re.search(patron, t):
            return codigo, ETIQUETAS_TIPO[codigo]
    return _TIPO_DEFAULT, ETIQUETAS_TIPO[_TIPO_DEFAULT]


def _safe_date(s: Any) -> Optional[date]:
    """Cadena ``YYYY-MM-DD`` → date (una sola implementación: ``reglas_tiempo.fecha_iso``).

    Es MÁS ESTRICTO que ``date.fromisoformat``, que en Python 3.11+ acepta formas ISO
    que la columna DATE de MySQL rechaza (semana ``2026-W23-1``, básico ``20260601``) y
    que ningún documento imprime.
    """
    return reglas_tiempo.fecha_iso(s)


def _dic(contenedor: Any, clave: str) -> dict[str, Any]:
    """Sub-dict defensivo: lo que no sea un dict se trata como vacío.

    El registro puede llegar de un cliente del API con otro tipo en cualquier rama (una
    lista donde se espera un objeto). El repo DEGRADA, no explota — igual que hace
    ``extract`` con ``isinstance``; el idiom ``or {}`` salvaba la lista vacía pero no la
    lista con elementos.
    """
    valor = contenedor.get(clave) if isinstance(contenedor, dict) else None
    return valor if isinstance(valor, dict) else {}


def _config_tiempos(lookups) -> Any:
    """Config de las reglas de tiempos guardada en BD, si el ``lookups`` sabe leerla.

    Sin BD (``LookupsNulos``) o sin las tablas → None y el motor sigue con el archivo del
    volumen y los defaults del código. Mismo patrón que ``documentos_requeridos``.
    """
    leer = getattr(lookups, "config_reglas_tiempo", None)
    if leer is None:
        return None
    try:
        return leer()
    except Exception:  # noqa: BLE001 — BD/tabla ausente: no es un error del documento
        return None


# --------------------------------------------------------------------------- #
# Lookups (cédula/CIE/EPS) contra los catálogos en MySQL, con caché en memoria.
# --------------------------------------------------------------------------- #
class Lookups:
    def __init__(self, conexion) -> None:
        self._cx = conexion
        self._cache_emp: dict[str, tuple[Optional[int], Optional[str], Optional[str]]] = {}
        self._cache_dx: dict[str, tuple[Optional[int], Optional[str]]] = {}
        self._cache_checklist: dict[int, Optional[str]] = {}  # idlpeps → JSON crudo de radicación
        self._entidades: Optional[list[tuple[int, str, int, str]]] = None  # (id, nombre_norm, tipo, nombre)
        self._empleados_nombre: Optional[list[tuple[int, str, str, str]]] = None  # (id, nombre, eps, clave)
        self._cfg_tiempos: Optional[dict[str, Any]] = None
        self._catalogo_dx: Optional[bool] = None   # ¿`lpdiagnosticos` tiene filas? (una sonda)

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
            # `vlpempleados` del ERP real trae filas con id o nombre en NULL (empleados sin
            # ficha completa): se descartan, no sirven para buscar por nombre.
            self._empleados_nombre = [(int(i), nm, eps, _norm(nm).replace(" ", ""))
                                      for (i, nm, eps) in filas if i is not None and nm]
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

    def catalogo_diagnosticos_disponible(self) -> bool:
        """True si `lpdiagnosticos` existe y tiene filas (se consulta una vez y se cachea).

        Hace falta para poder afirmar "este CIE-10 NO existe". Sin catálogo cargado, un
        código que no resuelve no significa nada: TODOS fallarían, y la señal de sospecha
        marcaría el 100% de los documentos legítimos. Es la diferencia entre "no existe" y
        "no lo pude comprobar".
        """
        if self._catalogo_dx is None:
            try:
                filas = self._query("SELECT 1 FROM lpdiagnosticos LIMIT 1", ())
                self._catalogo_dx = bool(filas)
            except Exception:  # noqa: BLE001 — entorno sin la tabla: no hay catálogo
                self._catalogo_dx = False
        return self._catalogo_dx

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

    def config_reglas_tiempo(self) -> dict[str, Any]:
        """Severidades/umbrales del motor de tiempos guardados en BD (una vez por corrida).

        Es la vía para cambiarlos en producción sin volver a desplegar. Si las tablas no
        existen (BD sin `sql/migracion_reglas_tiempo.sql`) devuelve ``{}`` y el motor sigue
        con el archivo del volumen y los defaults del código.
        """
        if self._cfg_tiempos is None:
            from .db import leer_config_reglas_tiempo  # import perezoso (no exige mysql)

            try:
                self._cfg_tiempos = leer_config_reglas_tiempo(self._cx)
            except Exception:  # noqa: BLE001
                self._cfg_tiempos = {}
        return self._cfg_tiempos

    def documentos_radicacion(self, id_entidad: Optional[int], id_tipo: Optional[int]) -> list[str]:
        """Documentos que la EPS exige para RADICAR el cobro (`lpeps.cheklistradicaciones`).

        Distinto de `documentos_requeridos` (recepción interna): esto es lo que hay que
        entregarle a la EPS. Solo una parte de las EPS tiene el checklist cargado; si está
        vacío, o la columna/tabla no existe en el entorno, devuelve [] (no se opina)."""
        if id_entidad is None or id_tipo is None:
            return []
        if id_entidad not in self._cache_checklist:
            try:
                filas = self._query(
                    "SELECT cheklistradicaciones FROM lpeps WHERE idlpeps = %s LIMIT 1",
                    (id_entidad,),
                )
                self._cache_checklist[id_entidad] = filas[0][0] if filas else None
            except Exception:  # noqa: BLE001 — entorno sin `lpeps` (BD demo): sin checklist
                self._cache_checklist[id_entidad] = None
        return documentos_checklist_radicacion(self._cache_checklist[id_entidad], id_tipo)


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

    def catalogo_diagnosticos_disponible(self):
        """Sin BD no hay catálogo: por eso un CIE-10 que no resuelve NO puede tratarse como
        indicio de manipulación (marcaría el 100% de los documentos). Ver la versión con BD."""
        return False

    def id_entidad_por_nombre(self, nombre):  # noqa: ARG002
        return None, None, None

    def documentos_requeridos(self, id_entidad, id_tipo):  # noqa: ARG002
        return []

    def config_reglas_tiempo(self):
        """Sin BD: no hay config en tabla → el motor usa el archivo del volumen y los
        defaults del código (las reglas siguen evaluándose, no se "apagan")."""
        return None

    def documentos_radicacion(self, id_entidad, id_tipo):  # noqa: ARG002
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
    """Valor → entero (una sola implementación: ``reglas_tiempo.entero_dias``).

    Rechaza ``bool`` (``True`` no es "un día"), dígitos Unicode no decimales (``²``:
    ``isdigit()`` los acepta y ``int()`` revienta) y cadenas larguísimas; acepta el signo
    para que un ``-3`` llegue a la regla de rango en vez de morir como "no se detectó".
    """
    return reglas_tiempo.entero_dias(v)


def mapear_a_staging(
    resultado: dict[str, Any],
    estado_recepcion: str = "WHATSAPP",
    lookups=None,
    hoy: Optional[date] = None,
    overrides: Optional[dict[str, Any]] = None,
    documentos_presentes=None,
    config_reglas=None,
) -> dict[str, Any]:
    """Construye la fila staging desde el resultado de ``process()``. No toca la BD.

    ``overrides`` permite que el AUXILIAR corrija/complete a mano los campos
    obligatorios (cédula, CIE-10, EPS, fecha de inicio, días, nombre, tipo); esos
    valores MANDAN sobre lo leído por el OCR y se vuelven a resolver los lookups.

    ``config_reglas`` (``reglas_tiempo.ConfigReglas``) permite al lote cargar UNA vez la
    configuración de severidades/umbrales y reutilizarla en todo el lote; si no se pasa,
    se carga aquí (BD > archivo > defaults del código).
    """
    hoy = hoy or date.today()
    lookups = lookups or LookupsNulos()
    overrides = {k: v for k, v in (overrides or {}).items() if v not in (None, "")}
    inc = _dic(resultado, "incapacidad")
    pac = _dic(inc, "paciente")
    ent = _dic(inc, "entidad")
    inca = _dic(inc, "incapacidad")
    diag = _dic(inc, "diagnostico")
    perm = _dic(inc, "permiso")
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

    # Configuración de las reglas de tiempos (severidades/umbrales). Se relee por corrida:
    # BD > archivo del volumen > defaults del código. Aquí ya se necesita porque el rango
    # de días válido (1..540 por defecto) es uno de esos umbrales.
    cfg_tiempos = config_reglas or reglas_tiempo.cargar_config(datos_bd=_config_tiempos(lookups))
    dias_min = cfg_tiempos.umbrales["dias_min"]
    dias_max = cfg_tiempos.umbrales["dias_max"]

    # Nunca se escribe una fecha inválida en la fila (protege el INSERT contra un
    # día/mes imposible que se cuele del OCR, del LLM o de un tecleo manual — MySQL
    # rechaza el registro completo con un 500 si llega algo como "2016-06-54").
    # Se guarda la forma CANÓNICA, no la cadena original: validar con `_safe_date` y
    # escribir el texto tal cual dejaría pasar un ISO que MySQL DATE no entiende y la
    # fila quedaría incoherente consigo misma (fechavencimiento calculado desde otra
    # fecha que la escrita).
    _di_ef, _df_ef = _safe_date(fecha_inicio), _safe_date(fecha_fin)
    fecha_inicio = _di_ef.isoformat() if _di_ef else None
    fecha_fin = _df_ef.isoformat() if _df_ef else None
    estado = str(estado_recepcion or "WHATSAPP").upper()
    if estado not in ESTADO_RECEPCION:
        estado = "WHATSAPP"

    # Regla del cliente (también al corregir a mano): si NO hay fecha de inicio pero sí
    # fecha final + días → inicio = fin − (días − 1). Recalcula al editar los días/el fin.
    if not fecha_inicio and _df_ef and num_dias and dias_min <= num_dias <= dias_max:
        fecha_inicio = (_df_ef - timedelta(days=num_dias - 1)).isoformat()
        fecha_inicio_calculada = True
    # Simétrico: si hay inicio + fin pero NO días, se calculan por diferencia (inclusive).
    # Cubre p.ej. vacaciones donde el inicio vino del nombre del archivo y el fin del OCR.
    if fecha_inicio and fecha_fin and not num_dias:
        _di, _df = _safe_date(fecha_inicio), _safe_date(fecha_fin)
        if _di and _df and dias_min <= (_df - _di).days + 1 <= dias_max:
            num_dias = (_df - _di).days + 1

    problemas: list[str] = []
    faltantes_campos: list[dict[str, Any]] = []  # campos OBLIGATORIOS para revisión manual

    # Sub-bandera DUDOSA (no bloquea, solo alerta): señal de posible manipulación del
    # documento calculada en processor.analizar_autenticidad. No confundir con
    # `problemas`/`requiere_revision`: hoy se suma ahí también para que dispare la
    # revisión estándar, pero queda además en columnas propias para que la UI pinte
    # el badge sin tener que parsear el string de `problemas`.
    auten = resultado.get("autenticidad") or {}
    sospecha_manipulacion = bool(auten.get("sospechosa"))
    motivo_sospecha = auten.get("motivo") if sospecha_manipulacion else None
    if sospecha_manipulacion:
        problemas.append(f"Posible manipulación del documento: {motivo_sospecha}")

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

    # Nivel tecleado: se valida contra el catálogo (un id inexistente rompería la FK).
    id_nivel = _num_dias(overrides.get("nivel"))
    if id_nivel not in ETIQUETAS_NIVEL:
        id_nivel = None
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
            motivo_nf = f"Diagnóstico {cie} no está en el catálogo CIE-10"
            problemas.append(motivo_nf)
            _faltan("cie10", "Código CIE-10", cie)
            # Tercera señal DUDOSA (Diana, confirmado contra la tabla real): todo CIE-10
            # vigente debe resolver contra `lpdiagnosticos` — si no matchea, es indicio de
            # un código fabricado/alterado a mano (o un error de tecleo/OCR severo).
            # SOLO si el catálogo está realmente cargado: sin él NADA resuelve, y la señal
            # marcaría el 100% de los documentos legítimos (con 7000 al mes, eso no es una
            # alerta, es ruido que tapa las de verdad). Sin catálogo queda el problema
            # anotado para revisión, pero NO como sospecha de manipulación.
            # `getattr` y no una llamada directa: `lookups` es duck-typed (hay dobles de
            # prueba y podría llegar otro origen de catálogos). Si al objeto le falta el
            # método se asume SIN catálogo, que es el lado seguro: no acusar de manipulación
            # a un documento legítimo. Se registra para que la carencia no pase inadvertida.
            _hay_catalogo = getattr(lookups, "catalogo_diagnosticos_disponible", None)
            if _hay_catalogo is None:
                log.warning("El objeto de lookups no expone catalogo_diagnosticos_disponible: "
                            "la señal de CIE-10 inexistente queda desactivada.")
            if _hay_catalogo is not None and _hay_catalogo():
                sospecha_manipulacion = True
                motivo_sospecha = f"{motivo_sospecha}; {motivo_nf}" if motivo_sospecha else motivo_nf
        else:
            # Segunda señal DUDOSA: el código CIE-10 existe en el catálogo, pero el texto
            # del diagnóstico que trae el documento no tiene relación con la descripción
            # OFICIAL de ese código — típico de una incapacidad donde se cambió el código
            # a mano pero no (o mal) la descripción, o viceversa. Algunos formatos omiten
            # la descripción del todo: en ese caso no se evalúa (no hay con qué comparar).
            if _diagnostico_coincide(desc_dx, diag.get("descripcion")) is False:
                motivo_dx = (
                    f"El texto del diagnóstico no coincide con {cie} "
                    f"({desc_dx}) según el catálogo CIE-10"
                )
                problemas.append(f"Posible manipulación del documento: {motivo_dx}")
                sospecha_manipulacion = True
                motivo_sospecha = f"{motivo_sospecha}; {motivo_dx}" if motivo_sospecha else motivo_dx

        # Cuarta señal DUDOSA: un CIE-10 vigente reportable tiene 4 caracteres (categoría
        # + subcategoría, p.ej. "S801"/"S80.1"); un código de solo 3 (la categoría sin
        # subdividir, p.ej. "A09") está estructuralmente incompleto para este catálogo —
        # independiente de si además matcheó o no contra `lpdiagnosticos`.
        if cie and len(cie.replace(".", "")) == 3:
            motivo_len = f"Código CIE-10 {cie} incompleto (3 caracteres; se esperan 4)"
            problemas.append(f"Posible manipulación del documento: {motivo_len}")
            sospecha_manipulacion = True
            motivo_sospecha = f"{motivo_sospecha}; {motivo_len}" if motivo_sospecha else motivo_len

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

    # --- VEREDICTO TEMPORAL (motor de reglas: incapacidad_ocr/reglas_tiempo.py) --------
    # Valida la COHERENCIA de los tiempos sobre los valores LEÍDOS del documento (o
    # tecleados por el auxiliar), nunca sobre los derivados por la reconciliación: ver la
    # invariante "validar NO es reconciliar" en ese módulo y en CLAUDE.md. El motor MARCA
    # y explica con código de regla + severidad; NUNCA rechaza: el auxiliar decide.
    ctx_tiempos = reglas_tiempo.construir_contexto(
        inca, hoy=hoy, overrides=overrides,
        inicio_efectivo=fecha_inicio, fin_efectivo=fecha_fin, dias_efectivo=num_dias,
        tipo_documento=inc.get("tipo_documento") if isinstance(inc, dict) else None,
        id_tipo=id_tipo, id_empleado=id_empleado,
        # Acceso de SOLO LECTURA al histórico del empleado para las reglas T15/T16/T17
        # (solapamiento / prórroga / duplicado). Hoy ningún `lookups` lo expone → None y
        # esas reglas quedan NO EVALUABLE; el día que exista el adaptador (pregunta P5 al
        # cliente: usuario de lectura sobre `lpausentismos`) basta con publicarlo aquí.
        historial=getattr(lookups, "historial_ausentismos", None),
    )
    veredicto = reglas_tiempo.evaluar(ctx_tiempos, cfg_tiempos)
    problemas.extend(veredicto.problemas)
    # Campos que el motor ya explicó: evita decirle al auxiliar "no se detectó" un dato
    # que SÍ se leyó (y que el hallazgo acaba de citar con su valor y su motivo).
    campos_explicados = {h.campo for h in veredicto.hallazgos if h.exige_revision}

    # Fechas / días (campos obligatorios). Una fecha de inicio CALCULADA (fin − días)
    # es un valor válido según la regla del cliente: NO bloquea, pero se avisa en la UI
    # (campo ``fecha_inicio_calculada``) para que el revisor lo confirme si quiere.
    # El valor que se registra en ``campos_faltantes`` es el CRUDO leído (no None): así el
    # formulario muestra qué había en el papel aunque no se pudiera usar.
    if not fecha_inicio:
        if "fecha_inicio" not in campos_explicados:
            problemas.append("No se detectó la fecha de inicio")
        _faltan("fecha_inicio", "Fecha de inicio", ctx_tiempos.inicio_crudo)
    if num_dias is None:
        if "dias" not in campos_explicados:
            problemas.append("No se detectó el número de días")
        _faltan("dias", "Días de incapacidad", ctx_tiempos.dias_crudo)
    elif not (dias_min <= num_dias <= dias_max):
        # Suelo NO configurable: un valor fuera de rango no es usable para la fila (deja
        # `Numerodias`/`fechavencimiento` en NULL) aunque se desactive la regla T03.
        if "dias" not in campos_explicados:
            problemas.append(f"Número de días fuera de rango (={num_dias})")
        _faltan("dias", "Días de incapacidad", num_dias)

    fecha_venc = None
    di = _safe_date(fecha_inicio)
    if di and num_dias and dias_min <= num_dias <= dias_max:
        fecha_venc = (di + timedelta(days=num_dias)).isoformat()  # inicio + dias
    # Un valor de días inutilizable no viaja a la fila (la columna es INT y el ERP lo
    # promueve tal cual): queda NULL y el auxiliar lo teclea.
    dias_fila = num_dias if (num_dias is not None and dias_min <= num_dias <= dias_max) else None

    # "Confianza": completitud de lo que se LEYÓ del documento (no hay score de OCR aún).
    # Un valor DERIVADO por regla NO cuenta como leído: si contara, la UI mostraría 100%
    # de confianza sobre una fecha de inicio que el documento no imprime.
    # Los permisos y vacaciones no llevan CIE-10, así que no cuenta para su completitud.
    inicio_leido_para_confianza = None if fecha_inicio_calculada else fecha_inicio
    nucleo = [cedula, inicio_leido_para_confianza, dias_fila] if (es_permiso or es_vacaciones) \
        else [cedula, cie, inicio_leido_para_confianza, dias_fila]
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

    # Radicación ante la EPS: qué faltará para COBRAR el ausentismo (aviso, no bloquea).
    # Los permisos y las vacaciones no se radican ante ninguna EPS → no aplica.
    rad_estado: Optional[str] = None
    rad_faltantes: list[str] = []
    rad_requeridos: list[str] = []
    if documentos_presentes is not None and not (es_permiso or es_vacaciones):
        consultar_radicacion = getattr(lookups, "documentos_radicacion", None)
        if callable(consultar_radicacion):
            rad_requeridos = consultar_radicacion(id_ent, id_tipo) or []
            rad_estado, rad_faltantes = validar_radicacion(documentos_presentes, rad_requeridos)

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
        "Numerodias": dias_fila,
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
        # EVIDENCIA temporal: lo que el documento IMPRIME, aunque no cuadre con la fila.
        # Sin estas dos columnas la reconciliación re-deriva el fin y la contradicción
        # (la señal de alteración más barata de detectar) desaparece del registro.
        "fechafin_leida": ctx_tiempos.fin_leido.isoformat() if ctx_tiempos.fin_leido else None,
        "dias_leidos": ctx_tiempos.dias_leido,
        # Canal propio del veredicto temporal: permite ordenar la cola por gravedad y
        # distinguir "los tiempos no cuadran" de "no encontré la cédula".
        "alertas_tiempos": ("; ".join(veredicto.codigos) or None),
        "severidad_tiempos": veredicto.severidad_max,
        "sospecha_manipulacion": 1 if sospecha_manipulacion else 0,
        "motivo_sospecha": motivo_sospecha,
        # El estado de sospecha manda sobre el pendiente normal: es una cola distinta para
        # el auxiliar. El veredicto temporal viaja aparte (`severidad_tiempos`) porque son
        # dos ejes independientes — un documento puede tener los tiempos incoherentes sin
        # ser una manipulación, y al revés.
        "estado": ESTADO_POSIBLE_MANIPULACION if sospecha_manipulacion else "PENDIENTE_REVISION",
    }
    return {
        "row": row,
        "requiere_revision": len(problemas) > 0,
        "problemas": problemas,
        # Veredicto temporal estructurado y COMPLETO (veredicto global, estado de cada
        # regla —incluidas las que cumplen y las que no se pudieron comprobar—, evidencia
        # leída vs. derivada, resumen y configuración aplicada), para que la UI lo muestre
        # aparte, la cola se pueda priorizar y el hallazgo sea auditable. Reutiliza el
        # recorrido de `evaluar` (no vuelve a evaluar el catálogo).
        "tiempos": reglas_tiempo.validar_tiempos(ctx_tiempos, cfg_tiempos, veredicto),
        "hallazgos_tiempos": [h.como_dict() for h in veredicto.hallazgos],
        "severidad_tiempos": veredicto.severidad_max,
        "avisos_tiempos": veredicto.avisos,
        "campos_faltantes": faltantes_campos,
        "tipo_ausentismo": etiqueta_tipo,
        "nivel_incapacidad": ETIQUETAS_NIVEL.get(id_nivel),
        "estado_recepcion": estado,
        "documentos_faltantes": faltantes,
        # Radicación ante la EPS (aviso anticipado; None = esa EPS no tiene checklist cargado)
        "radicacion_estado": rad_estado,
        "radicacion_requeridos": rad_requeridos,
        "radicacion_faltantes": rad_faltantes,
        "paciente_catalogo": nombre_catalogo,
        "paciente_ocr": nombre_ocr,
        "entidad_catalogo": nombre_entidad,
        "eps_de_empleado": eps_de_empleado,
        "fecha_inicio_calculada": fecha_inicio_calculada,
    }
