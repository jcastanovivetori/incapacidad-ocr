"""Motor de reglas de coherencia TEMPORAL (fechas y duración) de un ausentismo.

Qué resuelve
------------
Lo que el cliente pidió literalmente: *"valida los tiempos, para cuando no coincida
déjalo de tal forma que sea escalable y actualizado"*. Aquí se valida que las TRES
patas temporales del documento (fecha de inicio, fecha fin, número de días) digan lo
mismo, y cuando NO coinciden se emite un hallazgo con **código de regla + severidad +
mensaje en español** para que el auxiliar lo vea y decida.

Invariante que nunca se rompe — **validar NO es reconciliar**
------------------------------------------------------------
``extract.normalizar_fechas()`` COMPLETA lo que falta (regla del cliente:
``inicio = fin − (días − 1)``). Este módulo no completa nada: solo mira los valores
**LEÍDOS** del documento (o TECLEADOS por el auxiliar, que también son un dato humano
sobre el papel) y nunca los valores **CALCULADOS** por esa reconciliación. Si una regla
pudiera dispararse sobre un valor derivado, la aritmética que lo derivó garantiza que
"cuadra" y el hallazgo sería una tautología o —peor— un falso positivo contra un
documento legítimo al que el OCR solo le leyó dos de las tres patas.

Cómo se garantiza en el código (no por disciplina, por construcción):
  1. ``ReglaTiempo.requiere`` solo puede nombrar campos ``*_leido``/``*_crudo`` del
     contexto (lo verifica ``tests/test_validacion_temporal.py``).
  2. El motor descarta la regla ANTES de llamarla si le falta un dato leído → la regla
     queda "no evaluable" (se reporta como tal; no es ni acierto ni fallo).
  3. Los valores leídos salen de la FOTO que ``processor`` toma antes de reconciliar
     (``CLAVE_SNAPSHOT``); si no hay foto, se deducen de las marcas
     ``fecha_inicio_calculada`` / ``fecha_fin_recalculada`` de forma conservadora.

Escalable (añadir una regla = añadir una declaración)
----------------------------------------------------
Una regla es una fila del ``CATALOGO``: código, qué afirma, severidad por defecto, qué
datos leídos exige y una función ``evaluar(ctx, umbrales) -> mensaje | None``. El motor
(``evaluar_reglas``) no sabe qué reglas existen: las recorre. La receta paso a paso está
justo encima del ``CATALOGO``, en este mismo archivo (es el único sitio que hay que
tocar; el motor no se toca nunca).

Dos vistas del MISMO recorrido del catálogo
-------------------------------------------
* ``evaluar(ctx, cfg) -> ResultadoTiempos`` — veredicto OPERATIVO: solo lo que NO cuadra.
  Es el que consume ``erp.mapear_a_staging`` para alimentar ``problemas`` /
  ``requiere_revision`` (el canal que ya tenían la UI, la API y el enrutado del lote).
* ``validar_tiempos(ctx, cfg) -> dict`` — informe COMPLETO y serializable: el estado de
  CADA regla (``CUMPLE`` / ``NO_CUMPLE`` / ``NO_EVALUABLE`` / ``DESACTIVADA``) con su
  motivo, la evidencia usada y un resumen ordenable. Es la entrada única para quien
  quiera auditar por qué el motor dijo lo que dijo.
  El alias público de esta función es ``incapacidad_ocr.validacion_temporal``.

Un dato AUSENTE nunca es una violación: si la regla no pudo mirar lo que necesita, su
estado es ``NO_EVALUABLE`` con el motivo. Confundir "no lo pude comprobar" con "no
cumple" convertiría un documento legítimo mal leído en un caso sospechoso.

Actualizable (severidad/umbral sin volver a desplegar)
-----------------------------------------------------
Prioridad: **tabla en BD > archivo JSON > defaults del código**. Los defaults del código
hacen que el motor funcione igual **sin BD y sin archivo** (misma degradación que
``LookupsNulos``). Config inválida (severidad inexistente, tipo erróneo, umbral absurdo,
código desconocido) se IGNORA con un aviso: nunca desactiva una regla en silencio ni
tumba el mapeo.

100% local y determinista: sin red, sin modelo entrenado, sin BD obligatoria.
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Callable, Optional

# --------------------------------------------------------------------------- #
# Severidades
# --------------------------------------------------------------------------- #
# GRAVE / MEDIA mandan el caso a REVISIÓN HUMANA (entran en `problemas`).
# LEVE solo informa (aviso en la UI, no bloquea): es la palanca para bajar de tono una
# regla que resulte ruidosa en producción sin tener que desactivarla ni tocar código.
GRAVE, MEDIA, LEVE = "GRAVE", "MEDIA", "LEVE"
ORDEN_SEVERIDAD = {LEVE: 1, MEDIA: 2, GRAVE: 3}
SEVERIDADES_QUE_EXIGEN_REVISION = frozenset({GRAVE, MEDIA})

# --------------------------------------------------------------------------- #
# Estados de una regla frente a UN documento (tri-estado obligatorio)
# --------------------------------------------------------------------------- #
# NO_EVALUABLE no es un aprobado ni un suspenso: es "no pude mirarlo". Se reporta con el
# motivo para que el auxiliar sepa que esa comprobación NO se hizo (p.ej. el documento no
# imprime la fecha fin) en vez de creer que el documento la pasó.
CUMPLE, NO_CUMPLE = "CUMPLE", "NO_CUMPLE"
NO_EVALUABLE, DESACTIVADA = "NO_EVALUABLE", "DESACTIVADA"
ESTADOS = (CUMPLE, NO_CUMPLE, NO_EVALUABLE, DESACTIVADA)

# Penalización de cada severidad en el ÍNDICE de coherencia temporal (100 = nada que
# objetar). NO es una probabilidad de fraude ni la salida de un modelo: es una forma
# estable de ORDENAR una cola de ~7000 casos/mes para que lo más grave se vea primero.
PENALIZACION_SEVERIDAD = {GRAVE: 40, MEDIA: 20, LEVE: 5}

# Veredicto global del informe (deriva de los estados; no añade criterio nuevo).
V_COHERENTE = "COHERENTE"        # todo lo comprobable cuadra
V_AVISOS = "AVISOS"              # algo no cuadra, pero solo con severidad LEVE
V_REVISAR = "REVISAR"            # algo no cuadra con severidad que exige revisión
V_SIN_DATOS = "SIN_DATOS"        # no se pudo comprobar NADA (documento ilegible)

# Clave donde `processor` guarda la FOTO de los tiempos tal como los leyó el extractor,
# ANTES de que `normalizar_fechas()` complete/re-derive nada. Es la evidencia que este
# motor necesita: sin ella, un fin leído que no cuadraba se pierde al re-derivarse.
CLAVE_SNAPSHOT = "tiempos_leidos"

# --------------------------------------------------------------------------- #
# Umbrales (todos configurables sin desplegar)
# --------------------------------------------------------------------------- #
UMBRALES_DEFAULT: dict[str, int] = {
    # Rango legal de una incapacidad en Colombia (mismo 1..540 del resto del repo).
    "dias_min": 1,
    "dias_max": 540,
    # Duración a partir de la cual se avisa cuando NO hay rango de fechas que la
    # respalde. 180 días es la frontera de dominio (a partir de ahí el caso es trámite
    # de pensión/prórroga, no una incapacidad corriente); una licencia de maternidad
    # (126) queda por debajo a propósito.
    "dias_sin_respaldo_aviso": 180,
    # Ventana temporal plausible alrededor de HOY. El plazo real de radicación está en
    # las PREGUNTAS ABIERTAS al cliente: mientras no se confirme, "muy antiguo" es LEVE.
    "dias_futuro_max": 30,
    "dias_antiguedad_max": 730,
    # Tolerancia del cruce duración↔rango. 0 = exacto (el rango es inclusivo).
    "desfase_tolerado_dias": 0,
    # Días que se admite que un certificado se expida DESPUÉS de que la incapacidad
    # empezó. 0 = cualquier expedición posterior se avisa (LEVE). La incapacidad
    # RETROACTIVA es legítima y frecuente → es pregunta abierta al cliente (P7); mientras
    # no se confirme, este umbral es la palanca para callar el aviso sin tocar código.
    "dias_expedicion_posterior_tolerados": 0,
    # Holgura admitida entre el fin del ausentismo anterior y el inicio de la prórroga.
    "dias_contiguidad_prorroga": 1,
}
# Rango admisible de CADA umbral: un valor absurdo en la config se ignora (con aviso) en
# vez de desactivar de facto una regla (p.ej. dias_max = 99999 dejaría pasar todo).
LIMITES_UMBRAL: dict[str, tuple[int, int]] = {
    "dias_min": (1, 30),
    "dias_max": (1, 1095),
    "dias_sin_respaldo_aviso": (1, 1095),
    "dias_futuro_max": (0, 365),
    "dias_antiguedad_max": (30, 36500),
    "desfase_tolerado_dias": (0, 5),
    "dias_expedicion_posterior_tolerados": (0, 90),
    "dias_contiguidad_prorroga": (0, 30),
}

# Ruta del archivo de configuración. Por defecto vive DENTRO del bind mount de la
# ingesta (`_sistema/control/`), que es lo único editable en caliente: el código Python
# va dentro de la imagen Docker y cambiarlo exige reconstruirla.
ENV_RUTA_CONFIG = "REGLAS_TIEMPO_CONFIG"


def _ruta_config_por_defecto() -> Path:
    raiz = os.environ.get("INGESTA_ROOT", "/data/ingesta")
    return Path(raiz) / "_sistema" / "control" / "reglas_tiempo.json"


# --------------------------------------------------------------------------- #
# Contexto: lo LEÍDO (evidencia) vs lo EFECTIVO (lo que irá a la fila)
# --------------------------------------------------------------------------- #
@dataclass
class ContextoTiempos:
    """Datos sobre los que se evalúan las reglas.

    Los campos ``*_leido``/``*_crudo`` son EVIDENCIA (documento u override humano); los
    ``*_efectivo`` son el resultado de la reconciliación y están aquí solo para que un
    mensaje pueda citarlos. Ninguna regla debe decidir con un ``*_efectivo``.
    """

    hoy: date
    # --- evidencia ya interpretada (None = no se leyó o no es interpretable)
    inicio_leido: Optional[date] = None
    fin_leido: Optional[date] = None
    dias_leido: Optional[int] = None
    # --- evidencia CRUDA, tal como llegó (para poder decir "leí esto y no lo entendí")
    inicio_crudo: Any = None
    fin_crudo: Any = None
    dias_crudo: Any = None
    # --- marcas de la reconciliación (extract.normalizar_fechas)
    inicio_calculado: bool = False
    fin_recalculado: bool = False
    # True cuando hubo un fin leído que no cuadraba y NO se conservó el original
    # (registro que llega sin la foto de `processor`).
    fin_perdido: bool = False
    # --- instrumentación del lector de duraciones en letras ("DOS (2) días")
    dias_letra: Optional[int] = None
    # --- otra evidencia del papel (NO la toca la reconciliación: se lee del registro)
    expedicion_leida: Optional[date] = None
    expedicion_cruda: Any = None
    # "Prórroga: SI/No" impreso en 9 de 31 documentos del corpus. HOY el extractor no lo
    # publica → la regla que lo usa queda NO EVALUABLE (ver T16 en el CATALOGO).
    prorroga_declarada: Optional[bool] = None
    # --- accesos externos declarados (no son datos del papel, son consultas al sistema)
    # `historial`: adaptador de SOLO LECTURA al histórico de ausentismos del empleado.
    # None (lo normal hoy) → las reglas que lo exigen quedan NO EVALUABLE, igual que
    # `LookupsNulos` deja los IDs sin resolver en vez de explotar. Interfaz esperada
    # (duck typing, como `Lookups`; ver T15/T16/T17):
    #     solapamientos(ctx)              -> list[dict]  ausentismos que cruzan el intervalo
    #     duplicados_exactos(ctx)         -> list[dict]  misma terna (empleado, inicio, días)
    #     tiene_antecedentes(ctx)         -> bool        ¿el empleado tiene algún ausentismo?
    #     ausentismo_previo_contiguo(ctx) -> dict|None   el que termina justo antes
    historial: Any = None
    id_empleado: Optional[int] = None
    # --- valores efectivos (informativos)
    inicio_efectivo: Optional[date] = None
    fin_efectivo: Optional[date] = None
    dias_efectivo: Optional[int] = None
    # --- contexto del documento
    tipo_documento: Optional[str] = None
    id_tipo: Optional[int] = None
    # Día de la semana IMPRESO junto a la fecha de inicio ("MARTES 09 DE JUNIO").
    # Hoy el extractor no lo publica → la regla que lo usa queda NO EVALUABLE (a
    # propósito: ver T13 en el CATALOGO).
    dia_semana_inicio_leido: Optional[str] = None


@dataclass(frozen=True)
class Hallazgo:
    codigo: str
    severidad: str
    mensaje: str
    afirma: str
    campo: Optional[str] = None

    @property
    def exige_revision(self) -> bool:
        return self.severidad in SEVERIDADES_QUE_EXIGEN_REVISION

    def como_dict(self) -> dict[str, Any]:
        return {"codigo": self.codigo, "severidad": self.severidad, "mensaje": self.mensaje,
                "afirma": self.afirma, "campo": self.campo}


@dataclass(frozen=True)
class ResultadoRegla:
    """Qué dijo UNA regla sobre ESTE documento (con su motivo si no pudo opinar).

    ``mensaje`` solo viene en ``NO_CUMPLE`` (es el texto que lee el auxiliar); ``motivo``
    solo en ``NO_EVALUABLE``/``DESACTIVADA`` (por qué no se comprobó). Los dos juntos
    nunca: o hay hallazgo o hay explicación de la ausencia de hallazgo.
    """

    codigo: str
    estado: str
    severidad: str
    afirma: str
    campo: Optional[str] = None
    mensaje: Optional[str] = None
    motivo: Optional[str] = None
    faltan: tuple[str, ...] = ()

    def como_dict(self) -> dict[str, Any]:
        return {"codigo": self.codigo, "estado": self.estado, "severidad": self.severidad,
                "afirma": self.afirma, "campo": self.campo, "mensaje": self.mensaje,
                "motivo": self.motivo, "faltan": list(self.faltan)}


@dataclass(frozen=True)
class ResultadoTiempos:
    """Veredicto temporal SEPARADO de los problemas de lookup (cédula/CIE/EPS).

    Tener canal propio es lo que permite priorizar la cola de ~7000 casos/mes: "los
    tiempos no cuadran" no es lo mismo que "no encontré la cédula".
    """

    hallazgos: tuple[Hallazgo, ...] = ()
    no_evaluables: tuple[dict[str, Any], ...] = ()
    desactivadas: tuple[str, ...] = ()
    avisos_config: tuple[str, ...] = ()
    # Estado de TODAS las reglas (incluidas las que CUMPLEN). Va aquí para que el
    # veredicto operativo y el informe detallado salgan del MISMO recorrido del catálogo:
    # dos recorridos serían dos verdades que se contradicen en cuanto alguien toque una.
    resultados: tuple[ResultadoRegla, ...] = ()

    @property
    def problemas(self) -> list[str]:
        return [h.mensaje for h in self.hallazgos if h.exige_revision]

    @property
    def avisos(self) -> list[str]:
        return [h.mensaje for h in self.hallazgos if not h.exige_revision]

    @property
    def exige_revision(self) -> bool:
        return any(h.exige_revision for h in self.hallazgos)

    @property
    def severidad_max(self) -> Optional[str]:
        if not self.hallazgos:
            return None
        return max((h.severidad for h in self.hallazgos), key=lambda s: ORDEN_SEVERIDAD[s])

    @property
    def codigos(self) -> list[str]:
        return [h.codigo for h in self.hallazgos]

    @property
    def puntaje(self) -> int:
        """Índice de coherencia temporal 0..100 (100 = nada que objetar).

        Sirve para ORDENAR la cola de revisión, no para decidir: la decisión es del
        auxiliar. Un documento del que no se pudo comprobar nada NO baja de 100 por eso
        (ilegible ≠ incoherente); esa distinción la da ``cobertura`` en el resumen.
        """
        castigo = sum(PENALIZACION_SEVERIDAD[h.severidad] for h in self.hallazgos)
        return max(0, 100 - castigo)

    def como_dict(self) -> dict[str, Any]:
        return {
            "hallazgos": [h.como_dict() for h in self.hallazgos],
            "severidad_max": self.severidad_max,
            "puntaje": self.puntaje,
            "no_evaluables": list(self.no_evaluables),
            "desactivadas": list(self.desactivadas),
            "avisos_config": list(self.avisos_config),
            # Estado de cada regla (CUMPLE incluido): lo que permite auditar el veredicto.
            "reglas": [r.como_dict() for r in self.resultados],
        }


# --------------------------------------------------------------------------- #
# Utilidades
# --------------------------------------------------------------------------- #
_ISO_FECHA = re.compile(r"\d{4}-\d{2}-\d{2}")
# Ningún número de días real pasa de 6 cifras. El tope evita dos cosas: que `int()`
# reviente con una cadena larguísima (Python 3.11+ limita a 4300 dígitos) y que una
# cadena de basura del OCR entre como duración.
_MAX_DIGITOS_DIAS = 6
_DIGITOS_ASCII = re.compile(r"[+-]?[0-9]{1,%d}" % _MAX_DIGITOS_DIAS)


def fecha_iso(valor: Any) -> Optional[date]:
    """Cadena ``YYYY-MM-DD`` (y solo esa forma) → date. Cualquier otra cosa → None.

    Es deliberadamente MÁS ESTRICTO que ``date.fromisoformat``: en Python 3.11+ esa
    función acepta formas ISO que MySQL DATE no entiende (``2026-W23-1`` semana,
    ``20260601`` básico), y ningún documento imprime una fecha ISO de semana.
    """
    if isinstance(valor, date):
        return valor
    if not isinstance(valor, str):
        return None
    v = valor.strip()
    if not _ISO_FECHA.fullmatch(v):
        return None
    try:
        return date.fromisoformat(v)
    except ValueError:
        return None


def entero_dias(valor: Any) -> Optional[int]:
    """Valor de días → int, o None si no es un entero interpretable.

    Rechaza a propósito: ``bool`` (en Python ``True`` es 1, pero nunca es "un día
    leído"), dígitos Unicode no decimales (``²``, ``⁵`` — ``str.isdigit()`` los acepta
    y ``int()`` revienta), cadenas larguísimas y floats no enteros. Acepta el signo
    para que un ``-3`` llegue a la regla de rango en vez de morir como "no se detectó".
    """
    if isinstance(valor, bool):
        return None
    if isinstance(valor, int):
        return valor
    if isinstance(valor, float):
        return int(valor) if valor.is_integer() and abs(valor) < 10 ** _MAX_DIGITOS_DIAS else None
    if isinstance(valor, str):
        v = valor.strip()
        if _DIGITOS_ASCII.fullmatch(v):
            return int(v)
    return None


def recortar(valor: Any, tope: int = 40) -> str:
    """Valor → texto acotado para un mensaje (una cadena de 10.000 dígitos del OCR no
    puede acabar en la columna `problemas` ni en la pantalla del auxiliar)."""
    s = str(valor)
    return s if len(s) <= tope else s[:tope] + "…"


def snapshot_leidos(inca: dict[str, Any]) -> dict[str, Any]:
    """Foto de los tiempos TAL COMO LOS LEYÓ el extractor (antes de reconciliar)."""
    return {
        "fecha_inicio": inca.get("fecha_inicio"),
        "fecha_fin": inca.get("fecha_fin"),
        "dias": inca.get("dias"),
        "dias_letra": inca.get("dias_letra"),
    }


def valores_leidos(inca: dict[str, Any], overrides: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    """Extrae del registro los tiempos que SÍ son evidencia (nunca los derivados).

    Un override del auxiliar cuenta como evidencia: lo tecleó una persona mirando el
    documento, y si teclea un fin anterior al inicio hay que decírselo.
    """
    inca = inca if isinstance(inca, dict) else {}
    overrides = overrides or {}
    snap = inca.get(CLAVE_SNAPSHOT)
    inicio_calculado = bool(inca.get("fecha_inicio_calculada"))
    fin_recalculado = bool(inca.get("fecha_fin_recalculada"))
    fin_perdido = False
    if isinstance(snap, dict):
        inicio_crudo, fin_crudo = snap.get("fecha_inicio"), snap.get("fecha_fin")
        dias_crudo, dias_letra = snap.get("dias"), snap.get("dias_letra")
    else:
        # Sin foto previa (registro que no pasó por `processor`): se deduce de las marcas.
        # Un valor CALCULADO no es evidencia → se descarta. Del fin re-derivado solo
        # queda la marca: el original ya no está, así que se avisa con `fin_perdido`.
        inicio_crudo = None if inicio_calculado else inca.get("fecha_inicio")
        fin_crudo = None if fin_recalculado else inca.get("fecha_fin")
        fin_perdido = fin_recalculado
        # `dias` no tiene marca de "calculado" en el registro (extract.normalizar_fechas
        # marca el inicio y el fin, no los días). Tratarlo como leído es seguro: si se derivó, fue de
        # las dos fechas, y entonces cuadra con ellas y está dentro de 1..540 — ninguna
        # regla puede dispararse por ese camino.
        dias_crudo, dias_letra = inca.get("dias"), inca.get("dias_letra")
    if "fecha_inicio" in overrides:
        inicio_crudo, inicio_calculado = overrides["fecha_inicio"], False
    if "fecha_fin" in overrides:
        fin_crudo, fin_recalculado, fin_perdido = overrides["fecha_fin"], False, False
    if "dias" in overrides:
        dias_crudo = overrides["dias"]
    # La fecha de EXPEDICIÓN y el flag de PRÓRROGA se leen del registro sin pasar por la
    # foto: la reconciliación no los toca (solo mueve inicio/fin/días), así que lo que hay
    # en el registro ES lo leído. Si algún día se derivaran, habría que meterlos en la foto.
    expedicion_cruda = overrides.get("fecha_expedicion", inca.get("fecha_expedicion"))
    return {
        "inicio_crudo": inicio_crudo, "fin_crudo": fin_crudo, "dias_crudo": dias_crudo,
        "inicio_calculado": inicio_calculado, "fin_recalculado": fin_recalculado,
        "fin_perdido": fin_perdido, "dias_letra": entero_dias(dias_letra),
        "expedicion_cruda": expedicion_cruda,
        "prorroga_declarada": inca.get("prorroga") if isinstance(inca.get("prorroga"), bool) else None,
    }


def construir_contexto(inca: dict[str, Any], *, hoy: date,
                       overrides: Optional[dict[str, Any]] = None,
                       inicio_efectivo: Any = None, fin_efectivo: Any = None,
                       dias_efectivo: Optional[int] = None,
                       tipo_documento: Optional[str] = None,
                       id_tipo: Optional[int] = None,
                       id_empleado: Optional[int] = None,
                       historial: Any = None) -> ContextoTiempos:
    """Registro (+ overrides del auxiliar) → contexto de evaluación.

    ``historial``/``id_empleado`` son opcionales: sin ellos, las reglas que comparan
    contra el histórico del empleado quedan NO EVALUABLE (nunca dan un falso veredicto).
    """
    v = valores_leidos(inca, overrides)
    return ContextoTiempos(
        hoy=hoy,
        inicio_leido=fecha_iso(v["inicio_crudo"]),
        fin_leido=fecha_iso(v["fin_crudo"]),
        dias_leido=entero_dias(v["dias_crudo"]),
        inicio_crudo=v["inicio_crudo"], fin_crudo=v["fin_crudo"], dias_crudo=v["dias_crudo"],
        inicio_calculado=v["inicio_calculado"], fin_recalculado=v["fin_recalculado"],
        fin_perdido=v["fin_perdido"], dias_letra=v["dias_letra"],
        expedicion_leida=fecha_iso(v["expedicion_cruda"]), expedicion_cruda=v["expedicion_cruda"],
        prorroga_declarada=v["prorroga_declarada"],
        inicio_efectivo=fecha_iso(inicio_efectivo), fin_efectivo=fecha_iso(fin_efectivo),
        dias_efectivo=dias_efectivo, tipo_documento=tipo_documento, id_tipo=id_tipo,
        id_empleado=id_empleado, historial=historial,
    )


# --------------------------------------------------------------------------- #
# Declaración de una regla
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class ReglaTiempo:
    codigo: str
    afirma: str                       # qué afirma la regla, en una línea (va a la UI/doc)
    severidad: str                    # severidad POR DEFECTO (la config puede cambiarla)
    evaluar: Callable[[ContextoTiempos, dict[str, int]], Optional[str]]
    # Datos LEÍDOS que la regla exige para poder opinar. Si falta uno → NO EVALUABLE
    # (nunca se opina sobre un dato ausente ni sobre uno derivado).
    requiere: tuple[str, ...] = ()
    campo: Optional[str] = None        # campo del formulario al que apunta el hallazgo
    activa: bool = True                # activa POR DEFECTO


# Único conjunto de campos del contexto que una regla puede EXIGIR: evidencia del papel
# (más los accesos externos declarados y la fecha de proceso). Que NINGÚN campo
# `*_efectivo` esté aquí es lo que impide, por construcción, que una regla se dispare
# sobre un valor reconciliado. Lo verifica la prueba del catálogo, que además revisa el
# código fuente de cada regla.
CAMPOS_EXIGIBLES = frozenset({
    "hoy",
    # --- lo que traía el documento (o tecleó el auxiliar mirándolo)
    "inicio_leido", "fin_leido", "dias_leido",
    "inicio_crudo", "fin_crudo", "dias_crudo", "dias_letra", "dia_semana_inicio_leido",
    "expedicion_leida", "expedicion_cruda", "prorroga_declarada",
    # --- accesos externos declarados (consultas de SOLO LECTURA al sistema)
    "historial", "id_empleado",
})


def _sin_dato(valor: Any) -> bool:
    return valor is None or valor is False or valor == ""


# --------------------------------------------------------------------------- #
# CATÁLOGO DE REGLAS  (añadir una regla = añadir UNA entrada a la tupla CATALOGO)
# --------------------------------------------------------------------------- #
# RECETA — el motor NO se toca en ningún paso:
#   1. Escribe la función de la regla junto a las demás, aquí abajo:
#          def _t14_lo_que_afirma(ctx: ContextoTiempos, u: dict[str, int]) -> Optional[str]:
#              if <se cumple>:
#                  return None                      # None = CUMPLE
#              return "mensaje para el auxiliar, citando los valores leídos"
#      Solo puede mirar campos de EVIDENCIA del contexto (``*_leido`` / ``*_crudo``);
#      NUNCA un ``*_efectivo`` (esos son el resultado de la reconciliación: dispararían
#      contra documentos legítimos a los que el pipeline les completó un hueco).
#      Si otra regla ya explica ese caso, devuelve None y déjaselo a ella (así el auxiliar
#      no lee dos mensajes distintos del mismo problema).
#   2. Declárala al final de ``CATALOGO`` (ver el hueco marcado) con: código nuevo,
#      ``afirma`` en una línea, severidad por defecto, ``requiere=(...)`` — solo nombres
#      de ``CAMPOS_EXIGIBLES`` — y ``campo`` (el input del formulario al que apunta).
#   3. Si el dato que necesita todavía no lo publica el extractor, déjala ``activa=False``
#      con el motivo en un comentario: queda DECLARADA (sale en ``tabla_reglas()`` y se
#      puede activar por configuración) y no opina sobre lo que no puede ver.
#   4. Añádela a ``config/reglas_tiempo.example.json`` y a
#      ``tests/test_validacion_temporal.py`` (un caso que CUMPLE y otro que NO CUMPLE).
#   No hay paso 5: ``evaluar()`` y ``validar_tiempos()`` la recogen solas.
def _t01_duracion_vs_rango(ctx: ContextoTiempos, u: dict[str, int]) -> Optional[str]:
    if ctx.fin_leido < ctx.inicio_leido:          # eso lo explica T02
        return None
    if not (u["dias_min"] <= ctx.dias_leido <= u["dias_max"]):   # eso lo explica T03
        return None
    span = (ctx.fin_leido - ctx.inicio_leido).days + 1
    desfase = span - ctx.dias_leido
    if abs(desfase) <= u["desfase_tolerado_dias"]:
        return None
    esperado = ctx.inicio_leido + timedelta(days=ctx.dias_leido - 1)
    return (f"Los tiempos del documento no cuadran: el rango {ctx.inicio_leido.isoformat()} → "
            f"{ctx.fin_leido.isoformat()} son {span} día(s), pero declara {ctx.dias_leido} día(s) "
            f"(con esos días la fecha fin sería {esperado.isoformat()}; desfase de {desfase} día(s))")


def _t02_fin_antes_de_inicio(ctx: ContextoTiempos, u: dict[str, int]) -> Optional[str]:
    if ctx.fin_leido >= ctx.inicio_leido:
        return None
    return (f"La fecha fin leída ({ctx.fin_leido.isoformat()}) es ANTERIOR a la de inicio "
            f"({ctx.inicio_leido.isoformat()}): el rango es imposible")


def _t03_dias_fuera_de_rango(ctx: ContextoTiempos, u: dict[str, int]) -> Optional[str]:
    if u["dias_min"] <= ctx.dias_leido <= u["dias_max"]:
        return None
    return (f"El número de días leído (={ctx.dias_leido}) está fuera del rango válido "
            f"{u['dias_min']}..{u['dias_max']}")


def _t04_rango_mayor_al_maximo(ctx: ContextoTiempos, u: dict[str, int]) -> Optional[str]:
    if ctx.dias_leido is not None and not (u["dias_min"] <= ctx.dias_leido <= u["dias_max"]):
        return None                                # ya lo explica T03
    if ctx.fin_leido < ctx.inicio_leido:           # ya lo explica T02
        return None
    span = (ctx.fin_leido - ctx.inicio_leido).days + 1
    if span <= u["dias_max"]:
        return None
    return (f"El rango de fechas leído ({ctx.inicio_leido.isoformat()} → "
            f"{ctx.fin_leido.isoformat()}) dura {span} día(s), por encima del máximo "
            f"de {u['dias_max']}")


def _t05_dias_no_numerico(ctx: ContextoTiempos, u: dict[str, int]) -> Optional[str]:
    if ctx.dias_crudo is None or ctx.dias_leido is not None:
        return None
    return (f"El número de días leído no es un entero utilizable "
            f"(={recortar(ctx.dias_crudo)!s})")


def _t06_fecha_inicio_ilegible(ctx: ContextoTiempos, u: dict[str, int]) -> Optional[str]:
    if ctx.inicio_crudo is None or ctx.inicio_leido is not None:
        return None
    return (f"La fecha de inicio leída no es una fecha válida "
            f"(={recortar(ctx.inicio_crudo)!s}): se detectó el dato pero no se puede usar")


def _t07_fecha_fin_ilegible(ctx: ContextoTiempos, u: dict[str, int]) -> Optional[str]:
    if ctx.fin_crudo is None or ctx.fin_leido is not None:
        return None
    return (f"La fecha fin leída no es una fecha válida (={recortar(ctx.fin_crudo)!s})")


def _t08_duracion_sin_respaldo(ctx: ContextoTiempos, u: dict[str, int]) -> Optional[str]:
    if ctx.fin_leido is not None:                  # hay rango con el que cruzarla: T01 decide
        return None
    if not (u["dias_min"] <= ctx.dias_leido <= u["dias_max"]):   # eso lo explica T03
        return None
    if ctx.dias_leido <= u["dias_sin_respaldo_aviso"]:
        return None
    return (f"Duración larga ({ctx.dias_leido} días) sin fecha fin en el documento con la "
            f"que cruzarla: confirmar contra el papel (umbral de aviso: "
            f"{u['dias_sin_respaldo_aviso']} días)")


def _t09_inicio_en_futuro(ctx: ContextoTiempos, u: dict[str, int]) -> Optional[str]:
    margen = ctx.hoy + timedelta(days=u["dias_futuro_max"])
    if ctx.inicio_leido <= margen:
        return None
    return (f"La fecha de inicio ({ctx.inicio_leido.isoformat()}) está en el futuro, más de "
            f"{u['dias_futuro_max']} día(s) después de hoy ({ctx.hoy.isoformat()})")


def _t10_inicio_muy_antiguo(ctx: ContextoTiempos, u: dict[str, int]) -> Optional[str]:
    limite = ctx.hoy - timedelta(days=u["dias_antiguedad_max"])
    if ctx.inicio_leido >= limite:
        return None
    return (f"La fecha de inicio ({ctx.inicio_leido.isoformat()}) es de hace más de "
            f"{u['dias_antiguedad_max']} día(s) (hoy {ctx.hoy.isoformat()})")


def _t11_fin_reescrito(ctx: ContextoTiempos, u: dict[str, int]) -> Optional[str]:
    if not ctx.fin_perdido:
        return None
    return ("El documento traía una fecha fin que NO cuadraba con los días y el lector la "
            "re-derivó; el valor original no quedó registrado. Verificar los tiempos contra "
            "el papel")


def _t12_dias_letra_discrepa(ctx: ContextoTiempos, u: dict[str, int]) -> Optional[str]:
    if ctx.dias_letra == ctx.dias_leido:
        return None
    # El mensaje NO dice "las dos formas del documento": ``dias_leido`` puede venir de un
    # override del auxiliar, y entonces el desacuerdo es entre lo tecleado y la palabra
    # impresa. En los dos casos hay que mirar el papel, pero no se afirma de dónde salió.
    return (f"La duración escrita en LETRAS en el documento ({ctx.dias_letra}) no coincide "
            f"con el número de días registrado ({ctx.dias_leido})")


def _t13_dia_semana(ctx: ContextoTiempos, u: dict[str, int]) -> Optional[str]:
    # Reservada: ver la nota del CATALOGO. No evaluable hoy (falta el dato).
    nombres = ["lunes", "martes", "miercoles", "jueves", "viernes", "sabado", "domingo"]
    leido = str(ctx.dia_semana_inicio_leido or "").strip().lower()
    real = nombres[ctx.inicio_leido.weekday()]
    if not leido or leido.startswith(real[:4]):
        return None
    return (f"El día de la semana impreso ({leido}) no corresponde a la fecha de inicio "
            f"{ctx.inicio_leido.isoformat()}, que fue {real}")


def _t14_expedicion_posterior(ctx: ContextoTiempos, u: dict[str, int]) -> Optional[str]:
    desfase = (ctx.expedicion_leida - ctx.inicio_leido).days
    if desfase <= u["dias_expedicion_posterior_tolerados"]:
        return None
    return (f"El certificado se expidió el {ctx.expedicion_leida.isoformat()}, {desfase} día(s) "
            f"DESPUÉS de que la incapacidad empezara ({ctx.inicio_leido.isoformat()}): "
            f"confirmar que es una incapacidad retroactiva")


# --- Reglas que comparan contra el HISTÓRICO del empleado -------------------------------
# Van DECLARADAS y DESACTIVADAS: ni la tabla del histórico está en el esquema local
# (`sql/init.sql` no tiene `lpausentismos`) ni hay adaptador que la consulte, y el acceso
# de solo lectura es una pregunta abierta al cliente (P5). Cada una dice, en su comentario,
# el dato y la consulta que necesita: activarlas será un cambio de configuración
# (`activa: true`) + implementar el adaptador, no reescribir el motor.
def _t15_solapamiento(ctx: ContextoTiempos, u: dict[str, int]) -> Optional[str]:
    # Consulta que debe hacer `historial.solapamientos(ctx)` (SOLO LECTURA), excluyendo la
    # PRÓRROGA legítima (prorroga = 0 AND idlpausentismo_inicial IS NULL) y la propia fila
    # (id <> …, archivo_origen <> …), porque sin eso lo primero que encuentra es ella misma:
    #   a.fechainicio <= DATE_ADD(:inicio, INTERVAL :dias-1 DAY)
    #   AND DATE_SUB(a.fechavencimiento, INTERVAL 1 DAY) >= :inicio   -- vencimiento NO inclusivo
    cruces = ctx.historial.solapamientos(ctx) or []
    if not cruces:
        return None
    d = cruces[0]
    return (f"El periodo {ctx.inicio_leido.isoformat()} + {ctx.dias_leido} día(s) se cruza con "
            f"otro ausentismo ya registrado del mismo empleado "
            f"({d.get('fechainicio')} a {d.get('fechavencimiento')}, tipo {d.get('idlptipoausentismo')})")


def _t16_prorroga_sin_antecedente(ctx: ContextoTiempos, u: dict[str, int]) -> Optional[str]:
    if not ctx.prorroga_declarada:
        return None
    # `historial.ausentismo_previo_contiguo(ctx)` debe devolver el ausentismo del mismo
    # empleado cuyo fin cae dentro de `dias_contiguidad_prorroga` días antes del inicio.
    # Guarda contra el falso positivo del arranque: si el empleado no tiene NINGÚN
    # ausentismo previo en el sistema, la ausencia de antecedente no informa nada.
    if not ctx.historial.tiene_antecedentes(ctx):
        return None
    if ctx.historial.ausentismo_previo_contiguo(ctx):
        return None
    return (f"El documento declara PRÓRROGA pero no hay un ausentismo previo del empleado que "
            f"termine dentro de {u['dias_contiguidad_prorroga']} día(s) antes del "
            f"{ctx.inicio_leido.isoformat()}")


def _t17_duplicado_temporal(ctx: ContextoTiempos, u: dict[str, int]) -> Optional[str]:
    # `historial.duplicados_exactos(ctx)`: misma terna (idlpempleado, fechainicio,
    # Numerodias) en `lp_ausentismos_ia` con estado <> 'RECHAZADO', excluyendo la propia
    # fila y el propio `archivo_origen`. Es cotidiano con ~7000 casos/mes por WhatsApp +
    # correo + ventanilla y sin dedup en la ingesta.
    gemelas = ctx.historial.duplicados_exactos(ctx) or []
    if not gemelas:
        return None
    d = gemelas[0]
    return (f"Ya hay un registro con el mismo empleado, inicio {ctx.inicio_leido.isoformat()} y "
            f"{ctx.dias_leido} día(s), de otro archivo (id {d.get('id')}, "
            f"{d.get('archivo_origen')}): posible documento repetido")


CATALOGO: tuple[ReglaTiempo, ...] = (
    # --- Contradicciones internas del documento: la señal de alteración más barata de
    #     detectar y la única respaldada por el corpus (duración vs. rango de fechas).
    ReglaTiempo(
        "T01_DURACION_VS_RANGO",
        "los días declarados no coinciden con el rango de fechas impreso",
        GRAVE, _t01_duracion_vs_rango,
        requiere=("inicio_leido", "fin_leido", "dias_leido"), campo="dias",
    ),
    ReglaTiempo(
        "T02_FIN_ANTES_DE_INICIO",
        "la fecha fin es anterior a la fecha de inicio (rango imposible)",
        GRAVE, _t02_fin_antes_de_inicio,
        requiere=("inicio_leido", "fin_leido"), campo="fecha_fin",
    ),
    ReglaTiempo(
        "T03_DIAS_FUERA_DE_RANGO",
        "los días leídos están fuera del rango legal 1..540",
        GRAVE, _t03_dias_fuera_de_rango,
        requiere=("dias_leido",), campo="dias",
    ),
    ReglaTiempo(
        "T04_RANGO_MAYOR_AL_MAXIMO",
        "el rango de fechas dura más que el máximo legal",
        GRAVE, _t04_rango_mayor_al_maximo,
        requiere=("inicio_leido", "fin_leido"), campo="fecha_fin",
    ),
    # --- Datos leídos pero inutilizables: el motor NUNCA debe decir "no se detectó" un
    #     dato que el documento sí imprime (el auxiliar iría a buscar lo que ya está).
    # Exigen el valor CRUDO: sin ningún valor en el documento no hay nada que declarar
    # ilegible (que el dato NO esté es cosa de `erp`, que pide el campo al auxiliar).
    ReglaTiempo(
        "T05_DIAS_NO_NUMERICO",
        "hay un valor de días leído que no es un entero utilizable",
        MEDIA, _t05_dias_no_numerico, requiere=("dias_crudo",), campo="dias",
    ),
    ReglaTiempo(
        "T06_FECHA_INICIO_ILEGIBLE",
        "hay una fecha de inicio leída que no es una fecha válida",
        MEDIA, _t06_fecha_inicio_ilegible, requiere=("inicio_crudo",), campo="fecha_inicio",
    ),
    ReglaTiempo(
        "T07_FECHA_FIN_ILEGIBLE",
        "hay una fecha fin leída que no es una fecha válida",
        MEDIA, _t07_fecha_fin_ilegible, requiere=("fin_crudo",), campo="fecha_fin",
    ),
    # --- Plausibilidad. Umbrales de DOMINIO (no ajustados al corpus): 180 días es la
    #     frontera del trámite pensional; la ventana temporal es un aviso mientras el
    #     cliente confirme el plazo de radicación.
    ReglaTiempo(
        "T08_DURACION_SIN_RESPALDO",
        "duración por encima del umbral de aviso y sin rango de fechas que la respalde",
        MEDIA, _t08_duracion_sin_respaldo,
        requiere=("dias_leido",), campo="dias",
    ),
    ReglaTiempo(
        "T09_INICIO_EN_FUTURO",
        "la fecha de inicio está en el futuro más allá del margen admitido",
        MEDIA, _t09_inicio_en_futuro,
        requiere=("inicio_leido", "hoy"), campo="fecha_inicio",
    ),
    ReglaTiempo(
        "T10_INICIO_MUY_ANTIGUO",
        "la fecha de inicio es más antigua que la ventana de radicación",
        # LEVE a propósito: el plazo real de radicación es una PREGUNTA ABIERTA al
        # cliente. Hasta que se confirme, informa sin bloquear.
        LEVE, _t10_inicio_muy_antiguo,
        requiere=("inicio_leido", "hoy"), campo="fecha_inicio",
    ),
    # --- Evidencia destruida por la reconciliación (registro sin foto de `processor`):
    #     versión degradada de T01, sin los valores originales que citar.
    ReglaTiempo(
        "T11_FIN_REESCRITO_SIN_EVIDENCIA",
        "el lector re-derivó una fecha fin que no cuadraba y el original no quedó registrado",
        GRAVE, _t11_fin_reescrito, campo="fecha_fin",
    ),
    # --- Contradicción dígito vs. letra dentro del MISMO campo ("TRES (2) días").
    #     MEDIA: el corpus no muestra falsos positivos, pero el lector de letras es
    #     reciente; si en producción resulta ruidoso, bajar a LEVE por config.
    ReglaTiempo(
        "T12_DIAS_LETRA_DISCREPA",
        "la duración en letras no coincide con la del dígito en el mismo campo",
        MEDIA, _t12_dias_letra_discrepa,
        requiere=("dias_leido", "dias_letra"), campo="dias",
    ),
    # --- RESERVADA Y DESACTIVADA. El día de la semana impreso ("MARTES 09 DE JUNIO")
    #     cuadraría solo si el lector lo anclara a SU fecha: hoy el OCR desordena las
    #     celdas y la sonda del corpus demostró que la versión "por posición" marca
    #     documentos LEGÍTIMOS (dataset-falsedad, caso L14). Se deja declarada para que
    #     el día que el extractor publique `dia_semana_inicio_leido` sea un cambio de
    #     config (activa=true), no de código.
    ReglaTiempo(
        "T13_DIA_SEMANA_INCONSISTENTE",
        "el día de la semana impreso no corresponde a la fecha de inicio",
        LEVE, _t13_dia_semana,
        requiere=("inicio_leido", "dia_semana_inicio_leido"), campo="fecha_inicio",
        activa=False,
    ),
    # --- Fecha de EXPEDICIÓN contra el inicio. LEVE: la incapacidad retroactiva es
    #     legítima y frecuente (el rótulo "Incapacidad retroactiva" sale en 13 documentos
    #     del corpus), así que esto informa, no bloquea. El extractor solo ancla en
    #     "expedición" (no en "impresión", que sí puede ser posterior por una reimpresión),
    #     así que lo que llega aquí es una fecha de expedición de verdad.
    ReglaTiempo(
        "T14_EXPEDICION_POSTERIOR_AL_INICIO",
        "el certificado se expidió después de que la incapacidad empezara",
        LEVE, _t14_expedicion_posterior,
        requiere=("expedicion_leida", "inicio_leido"), campo="fecha_inicio",
    ),
    # --- DECLARADAS Y DESACTIVADAS: necesitan consultar el histórico del empleado.
    #     No es que "falten de programar": están escritas y probadas contra un adaptador
    #     falso; lo que falta es el ACCESO (P5: usuario de solo lectura sobre
    #     `lpausentismos`, que no existe en el esquema local) y el adaptador que lo use.
    #     Activarlas = implementar `ContextoTiempos.historial` + `activa: true` en la
    #     configuración. Sin él quedan NO EVALUABLE, nunca "no cumple".
    ReglaTiempo(
        "T15_SOLAPAMIENTO_MISMO_EMPLEADO",
        "el periodo se cruza con otro ausentismo ya registrado del mismo empleado",
        # MEDIA y no GRAVE: dos ausentismos concurrentes de origen distinto (accidente de
        # trabajo + enfermedad general) existen en la práctica (P4).
        MEDIA, _t15_solapamiento,
        requiere=("inicio_leido", "dias_leido", "id_empleado", "historial"), campo="fecha_inicio",
        activa=False,
    ),
    ReglaTiempo(
        "T16_PRORROGA_SIN_ANTECEDENTE",
        "el documento declara prórroga pero no hay un ausentismo previo contiguo",
        # LEVE: al arrancar el sistema el histórico está vacío, así que la ausencia de
        # antecedente es lo NORMAL y no puede bloquear una nómina.
        LEVE, _t16_prorroga_sin_antecedente,
        requiere=("prorroga_declarada", "inicio_leido", "id_empleado", "historial"),
        campo="fecha_inicio", activa=False,
    ),
    ReglaTiempo(
        "T17_DUPLICADO_TEMPORAL_EXACTO",
        "ya existe un registro con el mismo empleado, inicio y días, de otro archivo",
        MEDIA, _t17_duplicado_temporal,
        requiere=("inicio_leido", "dias_leido", "id_empleado", "historial"), campo="fecha_inicio",
        activa=False,
    ),
    # ======================================================================= #
    #  >>> AQUÍ se añade una regla nueva (receta al principio de esta sección) <<<
    #  Una entrada más en esta tupla y ya está: el motor la recorre, la
    #  configuración puede cambiarle severidad/umbral y la UI la muestra por el
    #  canal que ya existe. No hay registro que actualizar en ningún otro sitio.
    # ======================================================================= #
)

CATALOGO_POR_CODIGO = {r.codigo: r for r in CATALOGO}


# --------------------------------------------------------------------------- #
# Configuración: BD > archivo > defaults del código
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class ConfigReglas:
    severidades: dict[str, str]
    activas: dict[str, bool]
    umbrales: dict[str, int]
    fuentes: tuple[str, ...] = ()
    avisos: tuple[str, ...] = ()

    def severidad_de(self, codigo: str) -> str:
        return self.severidades.get(codigo, CATALOGO_POR_CODIGO[codigo].severidad)

    def esta_activa(self, codigo: str) -> bool:
        return self.activas.get(codigo, CATALOGO_POR_CODIGO[codigo].activa)


def config_por_defecto() -> ConfigReglas:
    return ConfigReglas(
        severidades={r.codigo: r.severidad for r in CATALOGO},
        activas={r.codigo: r.activa for r in CATALOGO},
        umbrales=dict(UMBRALES_DEFAULT),
        fuentes=("codigo",),
    )


def _aplicar(cfg: ConfigReglas, datos: Any, origen: str) -> ConfigReglas:
    """Superpone una capa de configuración sobre otra, VALIDANDO cada entrada.

    Lo que no se entiende se ignora con un aviso: una config mal escrita no puede
    desactivar una regla en silencio ni tumbar el mapeo de un documento.
    """
    if not isinstance(datos, dict):
        if datos is None:
            return cfg
        return ConfigReglas(cfg.severidades, cfg.activas, cfg.umbrales, cfg.fuentes,
                            cfg.avisos + (f"{origen}: se esperaba un objeto JSON",))
    severidades, activas = dict(cfg.severidades), dict(cfg.activas)
    umbrales, avisos = dict(cfg.umbrales), list(cfg.avisos)
    reglas = datos.get("reglas")
    if reglas is not None and not isinstance(reglas, dict):
        avisos.append(f"{origen}: 'reglas' debe ser un objeto código→{{severidad,activa}}")
        reglas = None
    for codigo, ajuste in (reglas or {}).items():
        if str(codigo).startswith("_"):
            continue                                  # comentario del archivo de ejemplo
        if codigo not in CATALOGO_POR_CODIGO:
            avisos.append(f"{origen}: regla desconocida '{recortar(codigo)}' (se ignora)")
            continue
        if not isinstance(ajuste, dict):
            avisos.append(f"{origen}: {codigo} debe ser un objeto {{severidad,activa}}")
            continue
        if "severidad" in ajuste:
            sev = str(ajuste["severidad"]).strip().upper()
            if sev in ORDEN_SEVERIDAD:
                severidades[codigo] = sev
            else:
                avisos.append(f"{origen}: {codigo} severidad '{recortar(ajuste['severidad'])}' "
                              f"no existe (válidas: {', '.join(ORDEN_SEVERIDAD)})")
        if "activa" in ajuste:
            act = ajuste["activa"]
            if isinstance(act, bool):
                activas[codigo] = act
            elif isinstance(act, int) and act in (0, 1):
                activas[codigo] = bool(act)
            else:
                avisos.append(f"{origen}: {codigo} 'activa' debe ser true/false")
    umbrales_nuevos = datos.get("umbrales")
    if umbrales_nuevos is not None and not isinstance(umbrales_nuevos, dict):
        avisos.append(f"{origen}: 'umbrales' debe ser un objeto nombre→entero")
        umbrales_nuevos = None
    for nombre, valor in (umbrales_nuevos or {}).items():
        if str(nombre).startswith("_"):
            continue
        if nombre not in UMBRALES_DEFAULT:
            avisos.append(f"{origen}: umbral desconocido '{recortar(nombre)}' (se ignora)")
            continue
        if isinstance(valor, bool) or not isinstance(valor, int):
            avisos.append(f"{origen}: umbral {nombre} debe ser un entero (llegó "
                          f"{recortar(type(valor).__name__)})")
            continue
        lo, hi = LIMITES_UMBRAL[nombre]
        if not (lo <= valor <= hi):
            avisos.append(f"{origen}: umbral {nombre}={valor} fuera de {lo}..{hi} (se ignora)")
            continue
        umbrales[nombre] = valor
    if umbrales["dias_min"] > umbrales["dias_max"]:
        avisos.append(f"{origen}: dias_min ({umbrales['dias_min']}) > dias_max "
                      f"({umbrales['dias_max']}): se conservan los valores anteriores")
        umbrales["dias_min"], umbrales["dias_max"] = cfg.umbrales["dias_min"], cfg.umbrales["dias_max"]
    return ConfigReglas(severidades, activas, umbrales, cfg.fuentes + (origen,), tuple(avisos))


def _leer_archivo(ruta: Optional[Path]) -> tuple[Any, list[str]]:
    ruta = ruta or Path(os.environ.get(ENV_RUTA_CONFIG) or _ruta_config_por_defecto())
    try:
        if not ruta.is_file():
            return None, []
        return json.loads(ruta.read_text(encoding="utf-8")), []
    except Exception as exc:  # noqa: BLE001 — JSON roto/ilegible: se sigue con defaults
        return None, [f"archivo {ruta.name}: no se pudo leer ({type(exc).__name__})"]


def cargar_config(ruta: Optional[Path] = None, datos_bd: Any = None) -> ConfigReglas:
    """Config efectiva: defaults del código, luego el archivo JSON, luego la BD.

    Se relee en cada corrida (igual que ``lookups.documentos_requeridos()``): cambiar
    una severidad o un umbral en producción es editar el JSON del volumen o un UPDATE
    en ``lp_reglas_tiempo_ia``/``lp_umbrales_tiempo_ia``, sin reconstruir la imagen.
    """
    cfg = config_por_defecto()
    datos, avisos = _leer_archivo(ruta)
    if avisos:
        cfg = ConfigReglas(cfg.severidades, cfg.activas, cfg.umbrales, cfg.fuentes,
                           cfg.avisos + tuple(avisos))
    if datos is not None:
        cfg = _aplicar(cfg, datos, "archivo")
    if datos_bd is not None:
        cfg = _aplicar(cfg, datos_bd, "bd")
    return cfg


# --------------------------------------------------------------------------- #
# Motor
# --------------------------------------------------------------------------- #
# Nombre del dato que falta → cómo se le dice a una persona. Sin esto, un
# "NO_EVALUABLE: faltan ['fin_leido']" no le sirve al auxiliar para nada.
ETIQUETA_DATO: dict[str, str] = {
    "hoy": "la fecha de proceso",
    "inicio_leido": "la fecha de inicio impresa en el documento",
    "fin_leido": "la fecha fin impresa en el documento",
    "dias_leido": "el número de días impreso en el documento",
    "inicio_crudo": "algún valor de fecha de inicio en el documento",
    "fin_crudo": "algún valor de fecha fin en el documento",
    "dias_crudo": "algún valor de días en el documento",
    "dias_letra": "la duración escrita en letras",
    "dia_semana_inicio_leido": "el día de la semana impreso junto a la fecha",
    "expedicion_leida": "la fecha de expedición del certificado",
    "prorroga_declarada": "el campo 'Prórroga: SI/No' del documento",
    "id_empleado": "el empleado resuelto en el catálogo",
    "historial": "el acceso al histórico de ausentismos del empleado",
}


def evaluar_reglas(ctx: ContextoTiempos,
                   config: Optional[ConfigReglas] = None) -> tuple[ResultadoRegla, ...]:
    """Recorre el CATÁLOGO y devuelve el estado de CADA regla (único recorrido del motor).

    El motor no conoce ninguna regla en particular: añadir una es añadir una entrada al
    catálogo. Tres cosas que hace a propósito:
      • Salta la regla ANTES de llamarla si le falta un dato LEÍDO → ``NO_EVALUABLE`` con
        el motivo en español (nunca un veredicto sobre un dato que no existe).
      • Una regla que revienta (bug en una regla nueva) queda ``NO_EVALUABLE`` y NO tumba
        el mapeo del documento: el resto del veredicto sigue saliendo.
      • Una regla desactivada por configuración se REPORTA como tal: apagarla es una
        decisión trazable, no un silencio.
    """
    cfg = config or config_por_defecto()
    salida: list[ResultadoRegla] = []
    for regla in CATALOGO:
        sev = cfg.severidad_de(regla.codigo)
        base = {"codigo": regla.codigo, "severidad": sev, "afirma": regla.afirma,
                "campo": regla.campo}
        if not cfg.esta_activa(regla.codigo):
            salida.append(ResultadoRegla(estado=DESACTIVADA, motivo="desactivada por configuración",
                                         **base))
            continue
        faltan = tuple(c for c in regla.requiere if _sin_dato(getattr(ctx, c, None)))
        if faltan:
            detalle = ", ".join(ETIQUETA_DATO.get(c, c) for c in faltan)
            salida.append(ResultadoRegla(estado=NO_EVALUABLE, faltan=faltan,
                                         motivo=f"no se pudo comprobar: falta {detalle}", **base))
            continue
        try:
            mensaje = regla.evaluar(ctx, cfg.umbrales)
        except Exception as exc:  # noqa: BLE001 — una regla con bug no rompe el pipeline
            salida.append(ResultadoRegla(
                estado=NO_EVALUABLE,
                motivo=f"la regla falló al evaluarse ({type(exc).__name__})", **base))
            continue
        if mensaje:
            salida.append(ResultadoRegla(estado=NO_CUMPLE, mensaje=str(mensaje), **base))
        else:
            salida.append(ResultadoRegla(estado=CUMPLE, **base))
    return tuple(salida)


def evaluar(ctx: ContextoTiempos, config: Optional[ConfigReglas] = None) -> ResultadoTiempos:
    """Veredicto OPERATIVO: lo que NO cuadra, ordenado de más grave a menos.

    Es lo que consume ``erp.mapear_a_staging`` para alimentar ``problemas`` /
    ``requiere_revision``. El informe completo (con las reglas que CUMPLEN y las que no se
    pudieron comprobar) es ``validar_tiempos``; las dos salen del mismo recorrido.
    """
    cfg = config or config_por_defecto()
    resultados = evaluar_reglas(ctx, cfg)
    hallazgos = [Hallazgo(r.codigo, r.severidad, r.mensaje or "", r.afirma, r.campo)
                 for r in resultados if r.estado == NO_CUMPLE]
    hallazgos.sort(key=lambda h: (-ORDEN_SEVERIDAD[h.severidad], h.codigo))
    no_evaluables = [{"codigo": r.codigo, "faltan": list(r.faltan), "motivo": r.motivo}
                     for r in resultados if r.estado == NO_EVALUABLE]
    desactivadas = [r.codigo for r in resultados if r.estado == DESACTIVADA]
    return ResultadoTiempos(tuple(hallazgos), tuple(no_evaluables), tuple(desactivadas),
                            cfg.avisos, resultados)


def resumen_evidencia(ctx: ContextoTiempos) -> dict[str, Any]:
    """Con qué se juzgó: lo LEÍDO (evidencia) separado de lo DERIVADO (informativo).

    Va en el informe para que la distinción no haya que reconstruirla: quien lo lea ve de
    un golpe qué imprimía el papel y qué puso la reconciliación.
    """
    def _iso(f: Optional[date]) -> Optional[str]:
        return f.isoformat() if f else None

    return {
        "hoy": ctx.hoy.isoformat(),
        # --- lo que se leyó del documento (o lo tecleó una persona mirándolo)
        "leido": {
            "fecha_inicio": _iso(ctx.inicio_leido),
            "fecha_fin": _iso(ctx.fin_leido),
            "dias": ctx.dias_leido,
            "dias_letra": ctx.dias_letra,
            "fecha_expedicion": _iso(ctx.expedicion_leida),
            "prorroga_declarada": ctx.prorroga_declarada,
            "fecha_inicio_cruda": None if ctx.inicio_crudo is None else recortar(ctx.inicio_crudo),
            "fecha_fin_cruda": None if ctx.fin_crudo is None else recortar(ctx.fin_crudo),
            "dias_crudo": None if ctx.dias_crudo is None else recortar(ctx.dias_crudo),
        },
        # --- lo que puso la reconciliación (NUNCA se juzga: solo se informa)
        "derivado": {
            "fecha_inicio_calculada": ctx.inicio_calculado,
            "fecha_fin_recalculada": ctx.fin_recalculado,
            "fin_original_no_conservado": ctx.fin_perdido,
            "fecha_inicio_efectiva": _iso(ctx.inicio_efectivo),
            "fecha_fin_efectiva": _iso(ctx.fin_efectivo),
            "dias_efectivo": ctx.dias_efectivo,
        },
        "documento": {"tipo_documento": ctx.tipo_documento, "id_tipo_ausentismo": ctx.id_tipo},
        # Accesos externos disponibles en esta evaluación (para saber por qué una regla del
        # histórico quedó sin comprobar).
        "accesos": {"empleado_resuelto": ctx.id_empleado is not None,
                    "historial_disponible": ctx.historial is not None},
    }


def hay_evidencia_temporal(ctx: ContextoTiempos) -> bool:
    """¿El documento (o el auxiliar) aportó ALGÚN tiempo que comprobar?

    Distingue "no encontré nada raro" de "no había nada que mirar": un documento ilegible
    y uno coherente no exigen la misma acción humana y no pueden dar el mismo veredicto.
    """
    return any([
        ctx.inicio_leido is not None, ctx.fin_leido is not None,
        ctx.dias_leido is not None, ctx.dias_letra is not None,
        not _sin_dato(ctx.inicio_crudo), not _sin_dato(ctx.fin_crudo),
        not _sin_dato(ctx.dias_crudo), ctx.fin_perdido,
        not _sin_dato(ctx.expedicion_cruda),
    ])


def validar_tiempos(contexto: ContextoTiempos, config: Optional[ConfigReglas] = None,
                    veredicto: Optional[ResultadoTiempos] = None) -> dict[str, Any]:
    """ENTRADA ÚNICA del motor: contexto → informe serializable (listo para ``json.dumps``).

    Devuelve el veredicto global, el estado de CADA regla con su mensaje/motivo, la
    evidencia usada, el resumen con el índice de coherencia y la procedencia de la
    configuración aplicada. No decide nada sobre el documento: MARCA y explica; aprobar o
    devolver es del auxiliar (este motor nunca rechaza solo).

    ``veredicto`` es para quien YA llamó a ``evaluar`` (``erp.mapear_a_staging`` lo hace
    porque necesita los objetos ``Hallazgo``): se reutiliza ese recorrido en vez de repetirlo.
    """
    cfg = config or cargar_config()
    # Sin `resultados` no se puede armar el informe por regla (un veredicto construido a
    # mano): se recalcula en vez de devolver un informe vacío que parecería "todo bien".
    if veredicto is None or not veredicto.resultados:
        veredicto = evaluar(contexto, cfg)
    resultados = veredicto.resultados
    por_estado = {e: [r.codigo for r in resultados if r.estado == e] for e in ESTADOS}
    comprobables = len(por_estado[CUMPLE]) + len(por_estado[NO_CUMPLE])
    activas = comprobables + len(por_estado[NO_EVALUABLE])
    if veredicto.exige_revision:
        veredicto_global = V_REVISAR
    elif veredicto.hallazgos:
        veredicto_global = V_AVISOS
    elif hay_evidencia_temporal(contexto):
        veredicto_global = V_COHERENTE
    else:
        # No había NADA que comprobar (el OCR no recuperó ni una fecha ni los días). No es
        # "coherente" (no se comprobó) ni "incoherente" (no hay contradicción): es un
        # documento del que hay que sacar los datos a mano.
        veredicto_global = V_SIN_DATOS
    return {
        "veredicto": veredicto_global,
        "exige_revision": veredicto.exige_revision,
        "severidad_max": veredicto.severidad_max,
        "puntaje_coherencia": veredicto.puntaje,
        "resumen": {
            "reglas_en_catalogo": len(resultados),
            "cumplen": len(por_estado[CUMPLE]),
            "no_cumplen": len(por_estado[NO_CUMPLE]),
            "no_evaluables": len(por_estado[NO_EVALUABLE]),
            "desactivadas": len(por_estado[DESACTIVADA]),
            "graves": sum(1 for h in veredicto.hallazgos if h.severidad == GRAVE),
            "medias": sum(1 for h in veredicto.hallazgos if h.severidad == MEDIA),
            "leves": sum(1 for h in veredicto.hallazgos if h.severidad == LEVE),
            # Qué parte de lo activo se pudo comprobar de verdad (0..1). Una cobertura
            # baja con veredicto COHERENTE significa "no encontré nada raro PORQUE casi
            # no pude mirar", que es una situación distinta y hay que poder verla.
            "cobertura": round(comprobables / activas, 3) if activas else 0.0,
        },
        "reglas": [r.como_dict() for r in resultados],
        # Mismos textos que viajan por el canal `problemas` / avisos de la UI: el informe
        # no inventa una segunda redacción del mismo hallazgo.
        "problemas": veredicto.problemas,
        "avisos": veredicto.avisos,
        "codigos": veredicto.codigos,
        "evidencia": resumen_evidencia(contexto),
        "config": {
            "fuentes": list(cfg.fuentes),          # ('codigo', 'archivo', 'bd')
            "avisos": list(cfg.avisos),            # entradas de config ignoradas y por qué
            "umbrales": dict(cfg.umbrales),
            "severidades": {r.codigo: cfg.severidad_de(r.codigo) for r in CATALOGO},
        },
    }


def tabla_reglas() -> list[dict[str, Any]]:
    """Catálogo en forma de tabla (para la documentación y para exponerlo en la UI)."""
    return [{"codigo": r.codigo, "afirma": r.afirma, "severidad_default": r.severidad,
             "activa_default": r.activa, "requiere": list(r.requiere), "campo": r.campo}
            for r in CATALOGO]
