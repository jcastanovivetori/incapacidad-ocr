"""Pruebas del motor de VALIDACIÓN TEMPORAL (ejecutable con python puro, sin pytest).

    python tests/test_validacion_temporal.py     ->  código de salida 0 = todo OK

Qué se protege aquí (por orden de importancia):

  1. **La frontera LEÍDO / CALCULADO.** Es el requisito de corrección más fuerte del motor:
     una regla solo puede opinar sobre lo que el documento IMPRIMÍA (o lo que tecleó una
     persona mirándolo), nunca sobre lo que rellenó `extract.normalizar_fechas()`. Si esa
     frontera se rompe, el motor marca documentos LEGÍTIMOS a los que el pipeline solo les
     completó un hueco — el peor fallo posible en una bandeja de ~7000 casos/mes.
  2. **Un dato ausente no es una violación**: CUMPLE / NO_CUMPLE / NO_EVALUABLE.
  3. **Escalabilidad real**: se declara una regla NUEVA en caliente y el motor la recoge
     sin que se toque una línea del motor.
  4. **Actualizable sin desplegar**: severidad, apagado y umbrales desde configuración
     externa; y una configuración CORRUPTA cae a los defaults sin excepción.
  5. **Integración sin canal nuevo**: los hallazgos viajan por `problemas` /
     `requiere_revision` de `erp.mapear_a_staging`, y la evidencia impresa queda en la fila.

Todo es determinista y local: sin OCR, sin red y sin MySQL (`hoy` se inyecta).
"""
from __future__ import annotations

import contextlib
import inspect
import json
import os
import re
import shutil
import sys
import tempfile
from dataclasses import replace
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

try:  # consola Windows (cp1252) → forzar UTF-8 para acentos
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # noqa: BLE001
    pass

from incapacidad_ocr import erp, reglas_tiempo as rt  # noqa: E402
from incapacidad_ocr import validacion_temporal as vt  # noqa: E402
from incapacidad_ocr.extract import normalizar_fechas  # noqa: E402

# Fecha de proceso fija: las reglas de ventana temporal (futuro/antigüedad) tienen que dar
# el mismo resultado hoy y en dos años.
HOY = date(2026, 9, 2)

_fail = 0


def check(name: str, cond: bool, detail: str = "") -> None:
    global _fail
    ok = bool(cond)
    if not ok:
        _fail += 1
    print(("  PASS " if ok else "  FAIL ") + name + (f"  ->  {detail}" if detail else ""))


# --------------------------------------------------------------------------- #
# Ayudas
# --------------------------------------------------------------------------- #
def _ctx(*, inicio=None, fin=None, dias=None, dias_letra=None, hoy: date = HOY,
         overrides=None, id_empleado=None, historial=None, **marcas) -> rt.ContextoTiempos:
    """Contexto por el camino de PRODUCCIÓN: la foto que deja `processor` + las marcas.

    Se usa `CLAVE_SNAPSHOT` a propósito (y no se construye el `ContextoTiempos` a mano):
    así las pruebas ejercitan `valores_leidos()`, que es donde vive la separación entre
    evidencia y valor derivado. ``marcas`` va tal cual al registro (`fecha_expedicion`,
    `prorroga`, `fecha_inicio_calculada`…).
    """
    inca = {rt.CLAVE_SNAPSHOT: {"fecha_inicio": inicio, "fecha_fin": fin,
                                "dias": dias, "dias_letra": dias_letra}}
    inca.update(marcas)
    return rt.construir_contexto(inca, hoy=hoy, overrides=overrides,
                                 id_empleado=id_empleado, historial=historial)


class _HistorialFalso:
    """Adaptador de histórico de PRUEBA: documenta la interfaz que exigen T15/T16/T17.

    En producción esta pieza hará SELECTs de solo lectura contra el histórico del ERP
    (`lpausentismos`) y contra la propia tabla de staging; aquí devuelve lo que se le pase
    para poder probar las reglas ANTES de tener el acceso a esa BD (pregunta P5).
    """

    def __init__(self, cruces=(), gemelas=(), previo=None, antecedentes=True) -> None:
        self._cruces, self._gemelas = list(cruces), list(gemelas)
        self._previo, self._antecedentes = previo, antecedentes

    def solapamientos(self, ctx):        # noqa: ARG002
        return self._cruces

    def duplicados_exactos(self, ctx):   # noqa: ARG002
        return self._gemelas

    def tiene_antecedentes(self, ctx):   # noqa: ARG002
        return self._antecedentes

    def ausentismo_previo_contiguo(self, ctx):  # noqa: ARG002
        return self._previo


def _regla(ctx: rt.ContextoTiempos, codigo: str, cfg=None) -> rt.ResultadoRegla:
    for r in rt.evaluar_reglas(ctx, cfg):
        if r.codigo == codigo:
            return r
    raise AssertionError(f"{codigo} no está en el catálogo")


def _estado(ctx: rt.ContextoTiempos, codigo: str, cfg=None) -> str:
    return _regla(ctx, codigo, cfg).estado


def _cfg_archivo(datos, carpeta: Path, nombre: str = "reglas_tiempo.json") -> rt.ConfigReglas:
    """Escribe una configuración y devuelve la config efectiva leyéndola de ese archivo."""
    ruta = carpeta / nombre
    ruta.write_text(datos if isinstance(datos, str) else json.dumps(datos), encoding="utf-8")
    return rt.cargar_config(ruta=ruta)


@contextlib.contextmanager
def _catalogo_con(*reglas: rt.ReglaTiempo):
    """Añade reglas al catálogo SOLO durante el bloque (prueba de extensibilidad)."""
    orig, orig_map = rt.CATALOGO, rt.CATALOGO_POR_CODIGO
    rt.CATALOGO = orig + reglas
    rt.CATALOGO_POR_CODIGO = {r.codigo: r for r in rt.CATALOGO}
    try:
        yield
    finally:
        rt.CATALOGO, rt.CATALOGO_POR_CODIGO = orig, orig_map


class _LookupsFalsos(erp.LookupsNulos):
    """Catálogos que SÍ resuelven (cédula/CIE/EPS), sin MySQL.

    Aísla el canal de TIEMPOS: con los lookups nulos, `problemas` se llena de "cédula no
    encontrada"/"CIE-10 no está en el catálogo" y no se puede afirmar que un mensaje
    concreto viene del motor temporal. Hereda de `LookupsNulos` para que cualquier método
    nuevo que `erp` empiece a consultar siga degradando igual que en producción sin BD.
    """

    def empleado_por_cedula(self, cedula):
        return (7, "PACIENTE DE PRUEBA", "SALUD TOTAL") if cedula else (None, None, None)

    def id_empleado_por_cedula(self, cedula):
        return self.empleado_por_cedula(cedula)[0]

    def diagnostico_por_codigo(self, codigo):
        return (11, "INFECCION AGUDA DE LAS VIAS RESPIRATORIAS") if codigo else (None, None)

    def id_entidad_por_nombre(self, nombre):
        return (3, 1, "SALUD TOTAL") if nombre else (None, None, None)


def _resultado(inca: dict, **extra) -> dict:
    """Resultado tipo `processor.process()` con los campos que mira `erp.mapear_a_staging`."""
    registro = {
        "tipo_documento": "incapacidad",
        "paciente": {"nombre": "PACIENTE DE PRUEBA", "documento_numero": "13742111"},
        "entidad": {"eps": "SALUD TOTAL"},
        "diagnostico": {"cie10": "J06.9"},
        "incapacidad": inca,
    }
    registro.update(extra)
    return {"fuente": "documento_de_prueba.pdf", "ocr_backend": "stub", "extractor": "rule",
            "incapacidad": registro}


# --------------------------------------------------------------------------- #
# [1] Invariantes del CATÁLOGO: lo que hace que ampliarlo sea seguro
# --------------------------------------------------------------------------- #
def test_catalogo() -> None:
    print("[1] Invariantes del catálogo (escalabilidad + frontera leído/calculado)")
    codigos = [r.codigo for r in rt.CATALOGO]
    check("códigos únicos", len(codigos) == len(set(codigos)), str(codigos))
    check("hay reglas declaradas", len(rt.CATALOGO) >= 13, str(len(rt.CATALOGO)))
    check("todas con severidad válida",
          all(r.severidad in rt.ORDEN_SEVERIDAD for r in rt.CATALOGO))
    check("todas explican QUÉ afirman (va a la UI y al informe)",
          all(r.afirma and len(r.afirma) > 15 for r in rt.CATALOGO))
    check("todas apuntan a un campo del formulario",
          all(r.campo in {"dias", "fecha_inicio", "fecha_fin"} for r in rt.CATALOGO))

    # LA invariante: una regla solo puede EXIGIR evidencia. Ningún `*_efectivo` (valor que
    # salió de la reconciliación) es exigible → por construcción no se puede escribir una
    # regla que dependa de un dato derivado.
    fuera = {c for r in rt.CATALOGO for c in r.requiere if c not in rt.CAMPOS_EXIGIBLES}
    check("`requiere` solo nombra campos exigibles (evidencia)", not fuera, str(fuera))
    check("ningún campo exigible es un valor efectivo",
          not any(c.endswith("_efectivo") for c in rt.CAMPOS_EXIGIBLES))

    # Y el cuerpo de las reglas tampoco puede leer un valor efectivo: se comprueba en el
    # CÓDIGO FUENTE, que es lo que impide que la siguiente regla lo haga por descuido.
    culpables = [r.codigo for r in rt.CATALOGO
                 if "_efectivo" in inspect.getsource(r.evaluar)]
    check("ninguna regla mira un valor efectivo en su cuerpo", not culpables, str(culpables))

    # Un umbral mal escrito en una regla sería un KeyError que el motor convierte en
    # NO_EVALUABLE: la regla quedaría muda en producción sin que nadie se enterase.
    usados = {m for r in rt.CATALOGO
              for m in re.findall(r"""u\[["'](\w+)["']\]""", inspect.getsource(r.evaluar))}
    check("los umbrales usados existen en UMBRALES_DEFAULT",
          usados <= set(rt.UMBRALES_DEFAULT), str(usados - set(rt.UMBRALES_DEFAULT)))
    check("todo umbral tiene rango admisible declarado",
          set(rt.UMBRALES_DEFAULT) == set(rt.LIMITES_UMBRAL))

    # La plantilla de configuración es lo que el cliente edita: si falta una regla, esa
    # regla es invisible para quien tiene que gobernarla.
    ejemplo = json.loads((ROOT / "config" / "reglas_tiempo.example.json").read_text(encoding="utf-8"))
    faltan = [c for c in codigos if c not in ejemplo["reglas"]]
    check("la plantilla config/reglas_tiempo.example.json lista TODAS las reglas",
          not faltan, str(faltan))
    faltan_u = [u for u in rt.UMBRALES_DEFAULT if u not in ejemplo["umbrales"]]
    check("la plantilla lista TODOS los umbrales", not faltan_u, str(faltan_u))
    check("tabla_reglas() expone el catálogo entero (para la UI/documentación)",
          len(rt.tabla_reglas()) == len(rt.CATALOGO))


# --------------------------------------------------------------------------- #
# [2] Cada regla ACTIVA: un caso que CUMPLE y otro que NO CUMPLE
# --------------------------------------------------------------------------- #
def test_reglas_cumple_y_no_cumple() -> None:
    print("[2] Cada regla activa: caso que CUMPLE y caso que NO CUMPLE")

    # --- T01 duración vs. rango de fechas (la regla estrella: el motivo del cliente)
    ok = _ctx(inicio="2026-06-01", fin="2026-06-05", dias=5)
    mal = _ctx(inicio="2026-06-01", fin="2026-07-06", dias=5)
    check("T01 CUMPLE con 01→05 jun y 5 días", _estado(ok, "T01_DURACION_VS_RANGO") == rt.CUMPLE)
    r = _regla(mal, "T01_DURACION_VS_RANGO")
    check("T01 NO_CUMPLE con 01 jun→06 jul y 5 días", r.estado == rt.NO_CUMPLE, r.estado)
    check("T01 cita los DOS valores leídos y el desfase",
          all(t in (r.mensaje or "") for t in ("2026-06-01", "2026-07-06", "36", "5", "31")),
          r.mensaje or "")
    check("T01 dice cuál sería la fecha fin con esos días (acción concreta)",
          "2026-06-05" in (r.mensaje or ""), r.mensaje or "")

    # --- T02 fin antes que inicio
    check("T02 CUMPLE con fin == inicio (incapacidad de un día)",
          _estado(_ctx(inicio="2026-06-10", fin="2026-06-10"), "T02_FIN_ANTES_DE_INICIO") == rt.CUMPLE)
    r = _regla(_ctx(inicio="2026-06-20", fin="2026-06-10"), "T02_FIN_ANTES_DE_INICIO")
    check("T02 NO_CUMPLE con fin anterior al inicio", r.estado == rt.NO_CUMPLE, r.estado)
    check("T02 cita las dos fechas", "2026-06-20" in r.mensaje and "2026-06-10" in r.mensaje)

    # --- T03 días fuera del rango legal (sobre el valor LEÍDO, no el saneado)
    check("T03 CUMPLE con 5 días", _estado(_ctx(dias=5), "T03_DIAS_FUERA_DE_RANGO") == rt.CUMPLE)
    r = _regla(_ctx(dias=900), "T03_DIAS_FUERA_DE_RANGO")
    check("T03 NO_CUMPLE con 900 días", r.estado == rt.NO_CUMPLE, r.estado)
    check("T03 cita el valor leído y el rango", "900" in r.mensaje and "1..540" in r.mensaje, r.mensaje)
    check("T03 NO_CUMPLE con 0 días (un cero no es 'sin dato')",
          _estado(_ctx(dias=0), "T03_DIAS_FUERA_DE_RANGO") == rt.NO_CUMPLE)
    check("T03 NO_CUMPLE con días negativos",
          _estado(_ctx(dias="-3"), "T03_DIAS_FUERA_DE_RANGO") == rt.NO_CUMPLE)

    # --- T04 el rango de fechas dura más que el máximo legal
    check("T04 CUMPLE con un rango de 540 días exactos",
          _estado(_ctx(inicio="2026-01-01", fin=(date(2026, 1, 1) + timedelta(days=539)).isoformat()),
                  "T04_RANGO_MAYOR_AL_MAXIMO") == rt.CUMPLE)
    r = _regla(_ctx(inicio="2024-01-01", fin="2026-06-30"), "T04_RANGO_MAYOR_AL_MAXIMO")
    check("T04 NO_CUMPLE con un rango de más de 540 días", r.estado == rt.NO_CUMPLE, r.estado)

    # --- T05/T06/T07 el dato SE LEYÓ pero no se puede usar (≠ 'no se detectó')
    check("T05 CUMPLE con días '5'", _estado(_ctx(dias="5"), "T05_DIAS_NO_NUMERICO") == rt.CUMPLE)
    r = _regla(_ctx(dias="dos dia(s)"), "T05_DIAS_NO_NUMERICO")
    check("T05 NO_CUMPLE con días 'dos dia(s)'", r.estado == rt.NO_CUMPLE, r.estado)
    check("T05 muestra lo que se leyó", "dos dia(s)" in r.mensaje, r.mensaje)
    check("T06 CUMPLE con una fecha de inicio válida",
          _estado(_ctx(inicio="2026-06-01"), "T06_FECHA_INICIO_ILEGIBLE") == rt.CUMPLE)
    r = _regla(_ctx(inicio="2026-02-31"), "T06_FECHA_INICIO_ILEGIBLE")
    check("T06 NO_CUMPLE con 31 de febrero (fecha imposible, no ilegible)",
          r.estado == rt.NO_CUMPLE, r.estado)
    check("T06 distingue 'se detectó y no sirve' de 'no se detectó'",
          "no se puede usar" in r.mensaje, r.mensaje)
    check("T07 CUMPLE con una fecha fin válida",
          _estado(_ctx(fin="2026-06-05"), "T07_FECHA_FIN_ILEGIBLE") == rt.CUMPLE)
    check("T07 NO_CUMPLE con día 54",
          _estado(_ctx(fin="2026-06-54"), "T07_FECHA_FIN_ILEGIBLE") == rt.NO_CUMPLE)

    # --- T08 duración larga SIN fecha fin con la que cruzarla
    check("T08 CUMPLE con 126 días (licencia de maternidad real, sin fechas)",
          _estado(_ctx(dias=126), "T08_DURACION_SIN_RESPALDO") == rt.CUMPLE)
    r = _regla(_ctx(dias=202), "T08_DURACION_SIN_RESPALDO")
    check("T08 NO_CUMPLE con 202 días sin fecha fin (el '202' del corpus)",
          r.estado == rt.NO_CUMPLE, r.estado)
    check("T08 dice el umbral que usó (para poder discutirlo)", "180" in r.mensaje, r.mensaje)
    check("T08 CUMPLE si SÍ hay fecha fin (de eso opina T01, no T08)",
          _estado(_ctx(inicio="2026-01-01", fin="2026-07-21", dias=202),
                  "T08_DURACION_SIN_RESPALDO") == rt.CUMPLE)

    # --- T09/T10 ventana temporal contra la fecha de proceso inyectada
    check("T09 CUMPLE con inicio 10 días en el futuro (prelicencia/maternidad)",
          _estado(_ctx(inicio=(HOY + timedelta(days=10)).isoformat()),
                  "T09_INICIO_EN_FUTURO") == rt.CUMPLE)
    r = _regla(_ctx(inicio=(HOY + timedelta(days=120)).isoformat()), "T09_INICIO_EN_FUTURO")
    check("T09 NO_CUMPLE con inicio 120 días en el futuro", r.estado == rt.NO_CUMPLE, r.estado)
    check("T09 cita hoy y el margen", HOY.isoformat() in r.mensaje and "30" in r.mensaje, r.mensaje)
    check("T10 CUMPLE con inicio de hace 100 días",
          _estado(_ctx(inicio=(HOY - timedelta(days=100)).isoformat()),
                  "T10_INICIO_MUY_ANTIGUO") == rt.CUMPLE)
    r = _regla(_ctx(inicio=(HOY - timedelta(days=900)).isoformat()), "T10_INICIO_MUY_ANTIGUO")
    check("T10 NO_CUMPLE con inicio de hace 900 días", r.estado == rt.NO_CUMPLE, r.estado)
    check("T10 es LEVE (el plazo de radicación es pregunta abierta al cliente)",
          r.severidad == rt.LEVE and not rt.evaluar(_ctx(inicio=(HOY - timedelta(days=900)).isoformat())).exige_revision,
          r.severidad)

    # --- T11 el fin impreso se re-derivó y no quedó registrado (registro SIN foto)
    check("T11 CUMPLE cuando no se re-derivó nada",
          _estado(rt.construir_contexto({"fecha_inicio": "2026-06-01", "dias": 5}, hoy=HOY),
                  "T11_FIN_REESCRITO_SIN_EVIDENCIA") == rt.CUMPLE)
    ctx_sin_foto = rt.construir_contexto(
        {"fecha_inicio": "2026-06-01", "fecha_fin": "2026-06-05", "dias": 5,
         "fecha_fin_recalculada": True}, hoy=HOY)
    r = _regla(ctx_sin_foto, "T11_FIN_REESCRITO_SIN_EVIDENCIA")
    check("T11 NO_CUMPLE si el fin se re-derivó sin conservar el original",
          r.estado == rt.NO_CUMPLE, r.estado)
    check("T11 no toma el fin re-derivado como evidencia",
          ctx_sin_foto.fin_leido is None, str(ctx_sin_foto.fin_leido))

    # --- T12 dígito vs. letra en el MISMO campo ("TRES (2) días")
    check("T12 CUMPLE cuando dígito y letra coinciden",
          _estado(_ctx(dias=2, dias_letra=2), "T12_DIAS_LETRA_DISCREPA") == rt.CUMPLE)
    r = _regla(_ctx(dias=2, dias_letra=3), "T12_DIAS_LETRA_DISCREPA")
    check("T12 NO_CUMPLE cuando discrepan", r.estado == rt.NO_CUMPLE, r.estado)
    check("T12 cita los dos valores", "3" in r.mensaje and "2" in r.mensaje, r.mensaje)

    # --- T14 expedición posterior al inicio (retroactividad: aviso, nunca bloqueo)
    check("T14 CUMPLE si se expidió el mismo día que empieza",
          _estado(_ctx(inicio="2026-06-01", fecha_expedicion="2026-06-01"),
                  "T14_EXPEDICION_POSTERIOR_AL_INICIO") == rt.CUMPLE)
    check("T14 CUMPLE si se expidió ANTES de empezar (maternidad/prelicencia)",
          _estado(_ctx(inicio="2026-06-10", fecha_expedicion="2026-06-01"),
                  "T14_EXPEDICION_POSTERIOR_AL_INICIO") == rt.CUMPLE)
    r = _regla(_ctx(inicio="2026-06-01", fecha_expedicion="2026-07-15"),
               "T14_EXPEDICION_POSTERIOR_AL_INICIO")
    check("T14 NO_CUMPLE si se expidió 44 días después", r.estado == rt.NO_CUMPLE, r.estado)
    check("T14 es LEVE y nombra la retroactividad (el auxiliar lo descarta en un vistazo)",
          r.severidad == rt.LEVE and "retroactiva" in r.mensaje, r.mensaje)
    check("T14 NO_EVALUABLE si el documento no trae fecha de expedición",
          _estado(_ctx(inicio="2026-06-01"), "T14_EXPEDICION_POSTERIOR_AL_INICIO") == rt.NO_EVALUABLE)

    # --- T13 declarada y DESACTIVADA de fábrica (el dato aún no existe en el registro)
    ctx = _ctx(inicio="2026-06-09")
    check("T13 viene DESACTIVADA (se reporta, no se silencia)",
          _estado(ctx, "T13_DIA_SEMANA_INCONSISTENTE") == rt.DESACTIVADA)
    raiz = Path(tempfile.mkdtemp(prefix="cfg_t13_"))
    try:
        cfg = _cfg_archivo({"reglas": {"T13_DIA_SEMANA_INCONSISTENTE": {"activa": True}}}, raiz)
        # 2026-06-09 fue MARTES: con el dato disponible la regla ya funciona.
        martes = replace(ctx, dia_semana_inicio_leido="MARTES 09")
        viernes = replace(ctx, dia_semana_inicio_leido="VIERNES")
        check("T13 activada por config: CUMPLE si el día impreso es el real",
              _estado(martes, "T13_DIA_SEMANA_INCONSISTENTE", cfg) == rt.CUMPLE)
        check("T13 activada por config: NO_CUMPLE si no lo es",
              _estado(viernes, "T13_DIA_SEMANA_INCONSISTENTE", cfg) == rt.NO_CUMPLE)
    finally:
        shutil.rmtree(raiz, ignore_errors=True)


# --------------------------------------------------------------------------- #
# [2b] Reglas DECLARADAS y desactivadas: las que dependen del histórico del empleado
# --------------------------------------------------------------------------- #
def test_reglas_del_historico() -> None:
    print("[2b] T15/T16/T17: declaradas, apagadas, y NO_EVALUABLE sin acceso al histórico")
    inca = _ctx(inicio="2026-06-01", dias=5, id_empleado=7)
    for codigo in ("T15_SOLAPAMIENTO_MISMO_EMPLEADO", "T16_PRORROGA_SIN_ANTECEDENTE",
                   "T17_DUPLICADO_TEMPORAL_EXACTO"):
        check(f"{codigo} viene DESACTIVADA (declarada, no activada sin datos)",
              _estado(inca, codigo) == rt.DESACTIVADA)

    raiz = Path(tempfile.mkdtemp(prefix="cfg_hist_"))
    try:
        cfg = _cfg_archivo({"reglas": {c: {"activa": True} for c in (
            "T15_SOLAPAMIENTO_MISMO_EMPLEADO", "T16_PRORROGA_SIN_ANTECEDENTE",
            "T17_DUPLICADO_TEMPORAL_EXACTO")}}, raiz)

        # Activadas SIN adaptador de histórico: no opinan, y dicen por qué.
        r = _regla(inca, "T15_SOLAPAMIENTO_MISMO_EMPLEADO", cfg)
        check("activada sin histórico: NO_EVALUABLE (nunca 'no cumple' por falta de datos)",
              r.estado == rt.NO_EVALUABLE, r.estado)
        check("y el motivo nombra el acceso que falta",
              r.motivo and "histórico" in r.motivo, r.motivo or "")
        check("T17 igual sin histórico",
              _estado(inca, "T17_DUPLICADO_TEMPORAL_EXACTO", cfg) == rt.NO_EVALUABLE)
        check("sin empleado resuelto tampoco se opina",
              _estado(_ctx(inicio="2026-06-01", dias=5, historial=_HistorialFalso()),
                      "T15_SOLAPAMIENTO_MISMO_EMPLEADO", cfg) == rt.NO_EVALUABLE)

        # Con un adaptador (el día que exista el acceso a BD) las reglas ya funcionan.
        limpio = _ctx(inicio="2026-06-01", dias=5, id_empleado=7, historial=_HistorialFalso())
        check("T15 CUMPLE si el histórico no devuelve cruces",
              _estado(limpio, "T15_SOLAPAMIENTO_MISMO_EMPLEADO", cfg) == rt.CUMPLE)
        cruzado = _ctx(inicio="2026-06-01", dias=5, id_empleado=7, historial=_HistorialFalso(
            cruces=[{"fechainicio": "2026-05-28", "fechavencimiento": "2026-06-03",
                     "idlptipoausentismo": 3}]))
        r = _regla(cruzado, "T15_SOLAPAMIENTO_MISMO_EMPLEADO", cfg)
        check("T15 NO_CUMPLE si hay un cruce", r.estado == rt.NO_CUMPLE, r.estado)
        check("T15 muestra el ausentismo que cruza (para decidir en un vistazo)",
              "2026-05-28" in r.mensaje and "tipo 3" in r.mensaje, r.mensaje)

        gemela = _ctx(inicio="2026-06-01", dias=5, id_empleado=7, historial=_HistorialFalso(
            gemelas=[{"id": 41, "archivo_origen": "13742111_INCAPACIDAD.pdf"}]))
        r = _regla(gemela, "T17_DUPLICADO_TEMPORAL_EXACTO", cfg)
        check("T17 NO_CUMPLE con una fila gemela de otro archivo", r.estado == rt.NO_CUMPLE, r.estado)
        check("T17 cita el id y el archivo de la gemela",
              "41" in r.mensaje and "13742111_INCAPACIDAD.pdf" in r.mensaje, r.mensaje)

        # T16 necesita además el flag del documento, que el extractor todavía no publica.
        sin_flag = _ctx(inicio="2026-06-01", dias=5, id_empleado=7, historial=_HistorialFalso())
        check("T16 NO_EVALUABLE si el documento no dice si es prórroga",
              _estado(sin_flag, "T16_PRORROGA_SIN_ANTECEDENTE", cfg) == rt.NO_EVALUABLE)
        con_previo = _ctx(inicio="2026-06-01", dias=5, id_empleado=7, prorroga=True,
                          historial=_HistorialFalso(previo={"id": 9}))
        check("T16 CUMPLE si hay ausentismo previo contiguo",
              _estado(con_previo, "T16_PRORROGA_SIN_ANTECEDENTE", cfg) == rt.CUMPLE)
        huerfana = _ctx(inicio="2026-06-01", dias=5, id_empleado=7, prorroga=True,
                        historial=_HistorialFalso(previo=None))
        check("T16 NO_CUMPLE si declara prórroga y no hay antecedente contiguo",
              _estado(huerfana, "T16_PRORROGA_SIN_ANTECEDENTE", cfg) == rt.NO_CUMPLE)
        # Guarda contra el falso positivo del arranque (histórico vacío).
        nuevo = _ctx(inicio="2026-06-01", dias=5, id_empleado=7, prorroga=True,
                     historial=_HistorialFalso(previo=None, antecedentes=False))
        check("T16 CUMPLE si el empleado no tiene NINGÚN ausentismo previo (sistema recién puesto)",
              _estado(nuevo, "T16_PRORROGA_SIN_ANTECEDENTE", cfg) == rt.CUMPLE)
    finally:
        shutil.rmtree(raiz, ignore_errors=True)


# --------------------------------------------------------------------------- #
# [3] NO_EVALUABLE: un dato ausente NO es una violación
# --------------------------------------------------------------------------- #
def test_no_evaluable() -> None:
    print("[3] NO_EVALUABLE por dato ausente (con motivo en español)")
    solo_inicio = _ctx(inicio="2026-06-01")
    r = _regla(solo_inicio, "T01_DURACION_VS_RANGO")
    check("T01 NO_EVALUABLE sin fecha fin ni días", r.estado == rt.NO_EVALUABLE, r.estado)
    check("dice QUÉ falta, en español y sin jerga",
          r.motivo and "fecha fin impresa" in r.motivo, r.motivo or "")
    check("lista los campos que faltan (para depurar)",
          set(r.faltan) == {"fin_leido", "dias_leido"}, str(r.faltan))
    check("T02 NO_EVALUABLE sin fecha fin",
          _estado(solo_inicio, "T02_FIN_ANTES_DE_INICIO") == rt.NO_EVALUABLE)
    check("T12 NO_EVALUABLE si el documento no trae la duración en letras",
          _estado(_ctx(dias=2), "T12_DIAS_LETRA_DISCREPA") == rt.NO_EVALUABLE)
    check("T05 NO_EVALUABLE si no hay NINGÚN valor de días (eso lo pide erp, no el motor)",
          _estado(_ctx(inicio="2026-06-01"), "T05_DIAS_NO_NUMERICO") == rt.NO_EVALUABLE)
    check("T05 NO_EVALUABLE con el campo vacío (no se declara ilegible una cadena vacía)",
          _estado(_ctx(dias=""), "T05_DIAS_NO_NUMERICO") == rt.NO_EVALUABLE)

    vacio = rt.evaluar(_ctx())
    check("documento sin ningún tiempo: NINGÚN hallazgo", not vacio.hallazgos,
          str([h.codigo for h in vacio.hallazgos]))
    check("documento sin ningún tiempo: no exige revisión POR LOS TIEMPOS",
          not vacio.exige_revision)
    informe = rt.validar_tiempos(_ctx())
    check("veredicto SIN_DATOS (≠ COHERENTE: no se comprobó nada)",
          informe["veredicto"] == rt.V_SIN_DATOS, informe["veredicto"])
    # La cobertura delata que "no encontré nada raro" era "casi no pude mirar": de las
    # reglas activas solo opina la única que no necesita ningún dato del documento.
    # Se comprueba con la RELACIÓN entre los contadores, no con números fijos: el catálogo
    # crece, y una prueba que fije "11 de 12" se rompe al añadir la regla 13 sin que nada
    # esté mal (fue exactamente lo que pasó).
    res = informe["resumen"]
    activas = res["reglas_en_catalogo"] - res["desactivadas"]
    check("todas las reglas activas quedan contabilizadas",
          res["cumplen"] + res["no_cumplen"] + res["no_evaluables"] == activas, str(res))
    check("casi ninguna regla activa pudo comprobar algo",
          res["no_evaluables"] == activas - 1 and res["cobertura"] < 0.1, str(res))


# --------------------------------------------------------------------------- #
# [4] EL CASO CRÍTICO: un valor CALCULADO no puede disparar nada
# --------------------------------------------------------------------------- #
def test_valor_calculado_no_dispara() -> None:
    print("[4] CRÍTICO: los valores DERIVADOS por la reconciliación no disparan reglas")

    # Caso legítimo y frecuente: el documento imprime fin + días y NO el inicio.
    # `normalizar_fechas` deriva inicio = fin − (días − 1) y lo marca.
    rec = {"incapacidad": {"fecha_fin": "2026-06-30", "dias": 5}}
    inca = rec["incapacidad"]
    inca[rt.CLAVE_SNAPSHOT] = rt.snapshot_leidos(inca)     # foto ANTES de reconciliar
    normalizar_fechas(rec)
    check("la reconciliación derivó el inicio y lo marcó",
          inca["fecha_inicio"] == "2026-06-26" and inca["fecha_inicio_calculada"] is True,
          str(inca))
    ctx = rt.construir_contexto(inca, hoy=HOY, inicio_efectivo=inca["fecha_inicio"],
                                fin_efectivo=inca["fecha_fin"], dias_efectivo=inca["dias"])
    check("el inicio DERIVADO no entra como evidencia", ctx.inicio_leido is None)
    check("pero sí está disponible como valor efectivo (para poder citarlo)",
          ctx.inicio_efectivo == date(2026, 6, 26))
    check("T01 queda NO_EVALUABLE (no hay inicio impreso que cruzar)",
          _estado(ctx, "T01_DURACION_VS_RANGO") == rt.NO_EVALUABLE)
    check("T02 queda NO_EVALUABLE", _estado(ctx, "T02_FIN_ANTES_DE_INICIO") == rt.NO_EVALUABLE)
    check("T06 queda NO_EVALUABLE (no hay valor de inicio leído que declarar ilegible)",
          _estado(ctx, "T06_FECHA_INICIO_ILEGIBLE") == rt.NO_EVALUABLE)
    res = rt.evaluar(ctx)
    check("documento LEGÍTIMO con inicio derivado: CERO hallazgos",
          not res.hallazgos, str([h.codigo for h in res.hallazgos]))
    check("y por tanto no exige revisión por tiempos", not res.exige_revision)
    check("el informe deja ver que el inicio es derivado",
          rt.validar_tiempos(ctx)["evidencia"]["derivado"]["fecha_inicio_calculada"] is True)

    # Variante: días derivados de las dos fechas (inicio + fin sin días impresos).
    rec2 = {"incapacidad": {"fecha_inicio": "2026-06-01", "fecha_fin": "2026-06-05"}}
    inca2 = rec2["incapacidad"]
    inca2[rt.CLAVE_SNAPSHOT] = rt.snapshot_leidos(inca2)
    normalizar_fechas(rec2)
    ctx2 = rt.construir_contexto(inca2, hoy=HOY)
    check("días derivados del rango: no hay hallazgos (la aritmética cuadra por definición)",
          not rt.evaluar(ctx2).hallazgos, str([h.codigo for h in rt.evaluar(ctx2).hallazgos]))
    check("y los días derivados NO se toman como leídos", ctx2.dias_leido is None,
          str(ctx2.dias_leido))

    # Un override del auxiliar SÍ es evidencia: lo teclea una persona mirando el papel.
    ctx3 = _ctx(inicio="2026-06-01", fin="2026-06-05", overrides={"dias": 30})
    check("un día tecleado a mano SÍ se juzga (T01 dispara con la tripleta corregida)",
          _estado(ctx3, "T01_DURACION_VS_RANGO") == rt.NO_CUMPLE)


# --------------------------------------------------------------------------- #
# [5] La evidencia sobrevive a la reconciliación (foto de `processor`)
# --------------------------------------------------------------------------- #
def test_evidencia_sobrevive() -> None:
    print("[5] Extremo a extremo: el fin IMPRESO que no cuadra se conserva y se reporta")
    # Caso del informe de huecos: el papel dice 06/06 → 06/07 y "1 día".
    # `normalizar_fechas` reescribe el fin a 06/06 (y antes de este motor nadie se enteraba).
    rec = {"incapacidad": {"fecha_inicio": "2026-06-06", "fecha_fin": "2026-07-06", "dias": 1}}
    inca = rec["incapacidad"]
    inca[rt.CLAVE_SNAPSHOT] = rt.snapshot_leidos(inca)
    normalizar_fechas(rec)
    check("la reconciliación reescribió el fin", inca["fecha_fin"] == "2026-06-06", str(inca))
    check("y lo marcó", inca["fecha_fin_recalculada"] is True)

    ctx = rt.construir_contexto(inca, hoy=HOY, inicio_efectivo=inca["fecha_inicio"],
                                fin_efectivo=inca["fecha_fin"], dias_efectivo=inca["dias"])
    check("el motor sigue viendo el fin IMPRESO (2026-07-06)",
          ctx.fin_leido == date(2026, 7, 6), str(ctx.fin_leido))
    r = _regla(ctx, "T01_DURACION_VS_RANGO")
    check("T01 NO_CUMPLE sobre los valores impresos", r.estado == rt.NO_CUMPLE, r.estado)
    check("el mensaje cita el fin impreso, no el re-derivado", "2026-07-06" in r.mensaje, r.mensaje)
    check("T11 NO se dispara (el original SÍ quedó registrado: no hay dos mensajes)",
          _estado(ctx, "T11_FIN_REESCRITO_SIN_EVIDENCIA") == rt.CUMPLE)
    informe = rt.validar_tiempos(ctx)
    check("veredicto REVISAR", informe["veredicto"] == rt.V_REVISAR, informe["veredicto"])
    check("el informe conserva las dos versiones del fin",
          informe["evidencia"]["leido"]["fecha_fin"] == "2026-07-06"
          and informe["evidencia"]["derivado"]["fecha_fin_efectiva"] == "2026-06-06",
          str(informe["evidencia"]))


# --------------------------------------------------------------------------- #
# [6] Actualizable sin desplegar: severidad, apagado y umbrales por configuración
# --------------------------------------------------------------------------- #
def test_config_en_caliente() -> None:
    print("[6] Configuración externa: severidad, apagado y umbral sin volver a desplegar")
    raiz = Path(tempfile.mkdtemp(prefix="cfg_ok_"))
    try:
        ctx = _ctx(inicio="2026-06-01", fin="2026-07-06", dias=5)
        base = rt.evaluar(ctx)
        check("por defecto T01 es GRAVE y exige revisión",
              base.severidad_max == rt.GRAVE and base.exige_revision, str(base.severidad_max))

        # (a) bajar de tono una regla: sigue avisando, deja de bloquear.
        cfg = _cfg_archivo({"reglas": {"T01_DURACION_VS_RANGO": {"severidad": "LEVE"}}}, raiz)
        res = rt.evaluar(ctx, cfg)
        check("archivo: T01 pasa a LEVE", res.severidad_max == rt.LEVE, str(res.severidad_max))
        check("LEVE ya NO exige revisión (no entra en `problemas`)", not res.exige_revision)
        check("pero el hallazgo sigue estando (como aviso)",
              len(res.avisos) == 1 and not res.problemas, str(res.avisos))
        check("el mensaje es el mismo (solo cambió el tono)",
              res.avisos[0] == base.problemas[0])

        # (b) subir de tono un aviso.
        cfg = _cfg_archivo({"reglas": {"T10_INICIO_MUY_ANTIGUO": {"severidad": "grave"}}}, raiz)
        antiguo = _ctx(inicio=(HOY - timedelta(days=900)).isoformat())
        check("archivo: T10 sube a GRAVE (acepta minúsculas)",
              rt.evaluar(antiguo, cfg).severidad_max == rt.GRAVE)

        # (c) apagar una regla: se reporta como DESACTIVADA, no se silencia.
        cfg = _cfg_archivo({"reglas": {"T01_DURACION_VS_RANGO": {"activa": False}}}, raiz)
        res = rt.evaluar(ctx, cfg)
        check("archivo: T01 desactivada → sin hallazgo",
              not any(h.codigo == "T01_DURACION_VS_RANGO" for h in res.hallazgos))
        check("y queda REGISTRADA como desactivada (decisión trazable)",
              "T01_DURACION_VS_RANGO" in res.desactivadas, str(res.desactivadas))

        # (d) mover un umbral: 126 días pasa a avisar si el cliente baja el umbral a 100.
        cfg = _cfg_archivo({"umbrales": {"dias_sin_respaldo_aviso": 100}}, raiz)
        check("umbral por defecto: 126 días CUMPLE",
              _estado(_ctx(dias=126), "T08_DURACION_SIN_RESPALDO") == rt.CUMPLE)
        check("umbral 100 por archivo: 126 días ya NO_CUMPLE",
              _estado(_ctx(dias=126), "T08_DURACION_SIN_RESPALDO", cfg) == rt.NO_CUMPLE)
        check("el mensaje cita el umbral nuevo",
              "100" in _regla(_ctx(dias=126), "T08_DURACION_SIN_RESPALDO", cfg).mensaje)

        # (e) la ruta también se puede dar por variable de entorno (despliegue Docker).
        ruta = raiz / "por_env.json"
        ruta.write_text(json.dumps({"reglas": {"T01_DURACION_VS_RANGO": {"severidad": "MEDIA"}}}),
                        encoding="utf-8")
        previo = os.environ.get(rt.ENV_RUTA_CONFIG)
        os.environ[rt.ENV_RUTA_CONFIG] = str(ruta)
        try:
            cfg_env = rt.cargar_config()
            check(f"{rt.ENV_RUTA_CONFIG} apunta al archivo y se aplica",
                  cfg_env.severidad_de("T01_DURACION_VS_RANGO") == rt.MEDIA
                  and "archivo" in cfg_env.fuentes, str(cfg_env.fuentes))
        finally:
            if previo is None:
                os.environ.pop(rt.ENV_RUTA_CONFIG, None)
            else:
                os.environ[rt.ENV_RUTA_CONFIG] = previo

        # (f) prioridad: la BD manda sobre el archivo (y el archivo sobre el código).
        cfg = rt.cargar_config(ruta=raiz / "reglas_tiempo.json",
                               datos_bd={"reglas": {"T01_DURACION_VS_RANGO": {"activa": True,
                                                                             "severidad": "GRAVE"}}})
        check("BD > archivo", cfg.esta_activa("T01_DURACION_VS_RANGO")
              and cfg.severidad_de("T01_DURACION_VS_RANGO") == rt.GRAVE, str(cfg.fuentes))
        check("y se registra de dónde salió la config",
              cfg.fuentes == ("codigo", "archivo", "bd"), str(cfg.fuentes))
    finally:
        shutil.rmtree(raiz, ignore_errors=True)


# --------------------------------------------------------------------------- #
# [7] Configuración CORRUPTA: defaults + aviso, nunca una excepción
# --------------------------------------------------------------------------- #
def test_config_corrupta() -> None:
    print("[7] Configuración corrupta: cae a los defaults, avisa y NO revienta")
    raiz = Path(tempfile.mkdtemp(prefix="cfg_mal_"))
    try:
        defaults = rt.config_por_defecto()

        # (a) JSON roto (el caso real: alguien edita el archivo a mano y se come una coma)
        cfg = _cfg_archivo('{"reglas": {"T01_DURACION_VS_RANGO": {"severidad": "LEVE",}}', raiz)
        check("JSON ilegible: severidades por defecto",
              cfg.severidades == defaults.severidades and cfg.umbrales == defaults.umbrales)
        check("JSON ilegible: lo avisa", any("no se pudo leer" in a for a in cfg.avisos),
              str(cfg.avisos))

        # (b) JSON válido pero no es un objeto
        cfg = _cfg_archivo(["T01"], raiz)
        check("lista en vez de objeto: defaults + aviso",
              cfg.umbrales == defaults.umbrales
              and any("objeto JSON" in a for a in cfg.avisos), str(cfg.avisos))

        # (c) contenido plausible pero equivocado en TODAS sus formas
        cfg = _cfg_archivo({
            "reglas": {
                "T99_NO_EXISTE": {"severidad": "GRAVE"},                  # regla inventada
                "T01_DURACION_VS_RANGO": {"severidad": "CRITICA"},        # severidad inexistente
                "T02_FIN_ANTES_DE_INICIO": {"activa": "si"},              # no es booleano
                "T03_DIAS_FUERA_DE_RANGO": "GRAVE",                       # no es un objeto
            },
            "umbrales": {
                "dias_maximos": 100,        # nombre inventado
                "dias_max": "540",          # no es entero
                "dias_futuro_max": 9999,    # fuera del rango admisible
                "desfase_tolerado_dias": True,   # bool no es entero
            },
        }, raiz)
        check("regla desconocida ignorada", any("regla desconocida" in a for a in cfg.avisos))
        check("severidad inexistente ignorada: T01 sigue GRAVE",
              cfg.severidad_de("T01_DURACION_VS_RANGO") == rt.GRAVE)
        check("'activa' no booleana ignorada: T02 sigue activa",
              cfg.esta_activa("T02_FIN_ANTES_DE_INICIO"))
        check("ajuste que no es objeto ignorado: T03 sigue GRAVE y activa",
              cfg.severidad_de("T03_DIAS_FUERA_DE_RANGO") == rt.GRAVE
              and cfg.esta_activa("T03_DIAS_FUERA_DE_RANGO"))
        check("umbral desconocido ignorado", any("umbral desconocido" in a for a in cfg.avisos))
        check("umbrales inválidos ignorados: siguen los del código",
              cfg.umbrales == defaults.umbrales, str(cfg.umbrales))
        check("cada error se explica por separado", len(cfg.avisos) >= 6, str(cfg.avisos))
        check("una config corrupta NO desactiva ninguna regla",
              all(cfg.esta_activa(r.codigo) == r.activa for r in rt.CATALOGO))

        # (d) rango invertido: dias_min > dias_max dejaría pasar cualquier duración
        cfg = _cfg_archivo({"umbrales": {"dias_min": 30, "dias_max": 10}}, raiz)
        check("dias_min > dias_max: se conservan los valores anteriores",
              cfg.umbrales["dias_min"] == 1 and cfg.umbrales["dias_max"] == 540,
              str(cfg.umbrales))
        check("y lo avisa", any("dias_min" in a and "dias_max" in a for a in cfg.avisos))

        # (e) el motor SIGUE funcionando con la config corrupta (esto es lo que importa)
        ctx = _ctx(inicio="2026-06-01", fin="2026-07-06", dias=5)
        res = rt.evaluar(ctx, cfg)
        check("con config corrupta el veredicto sale igual",
              [h.codigo for h in res.hallazgos] == ["T01_DURACION_VS_RANGO"],
              str([h.codigo for h in res.hallazgos]))
        check("los avisos de configuración viajan en el veredicto (visibles en la API)",
              bool(res.avisos_config))

        # (f) basura desde la BD (una fila con severidad mal escrita)
        cfg = rt.cargar_config(ruta=raiz / "no_existe.json", datos_bd="???")
        check("datos_bd que no son un objeto: defaults + aviso",
              cfg.severidades == defaults.severidades
              and any("objeto JSON" in a for a in cfg.avisos), str(cfg.avisos))

        # (g) archivo inexistente: no es un error, es lo normal (nadie ha configurado nada)
        cfg = rt.cargar_config(ruta=raiz / "tampoco_existe.json")
        check("archivo inexistente: sin avisos y con los defaults",
              not cfg.avisos and cfg.umbrales == defaults.umbrales, str(cfg.avisos))
    finally:
        shutil.rmtree(raiz, ignore_errors=True)


# --------------------------------------------------------------------------- #
# [8] Degradación sin BD (mismo patrón que LookupsNulos)
# --------------------------------------------------------------------------- #
def test_sin_bd() -> None:
    print("[8] Sin MySQL: el motor no se apaga, solo pierde la config de la tabla")
    check("LookupsNulos no ofrece config de BD",
          erp._config_tiempos(erp.LookupsNulos()) is None)

    class _LookupsSinTabla(erp.LookupsNulos):
        def config_reglas_tiempo(self):
            raise RuntimeError("Table 'ASTGU.lp_reglas_tiempo_ia' doesn't exist")

    check("una BD sin la tabla de reglas degrada a None (no propaga la excepción)",
          erp._config_tiempos(_LookupsSinTabla()) is None)

    class _LookupsViejo:
        """Lookups de una versión anterior: ni siquiera tiene el método."""

    check("un lookups sin el método también degrada",
          erp._config_tiempos(_LookupsViejo()) is None)

    cfg = rt.cargar_config(datos_bd=erp._config_tiempos(erp.LookupsNulos()))
    check("sin BD y sin archivo, el motor usa los defaults del código",
          cfg.umbrales == rt.UMBRALES_DEFAULT and "codigo" in cfg.fuentes, str(cfg.fuentes))
    ctx = _ctx(inicio="2026-06-01", fin="2026-07-06", dias=5)
    check("y las reglas siguen evaluándose",
          rt.evaluar(ctx, cfg).codigos == ["T01_DURACION_VS_RANGO"])


# --------------------------------------------------------------------------- #
# [9] Escalabilidad: una regla NUEVA sin tocar el motor
# --------------------------------------------------------------------------- #
def test_regla_nueva() -> None:
    print("[9] Añadir una regla = añadir un objeto al catálogo (el motor no se toca)")

    def _t99_inicio_en_domingo(ctx, u):     # noqa: ARG001 — firma fija de las reglas
        if ctx.inicio_leido.weekday() != 6:
            return None
        return f"La incapacidad empieza en domingo ({ctx.inicio_leido.isoformat()})"

    nueva = rt.ReglaTiempo(
        "T99_INICIO_EN_DOMINGO", "la incapacidad empieza un domingo",
        rt.LEVE, _t99_inicio_en_domingo, requiere=("inicio_leido",), campo="fecha_inicio",
    )
    with _catalogo_con(nueva):
        domingo = _ctx(inicio="2026-06-07")     # 2026-06-07 fue domingo
        martes = _ctx(inicio="2026-06-09")
        check("el motor recoge la regla nueva sin cambios en el motor",
              _estado(domingo, "T99_INICIO_EN_DOMINGO") == rt.NO_CUMPLE)
        check("y CUMPLE cuando toca", _estado(martes, "T99_INICIO_EN_DOMINGO") == rt.CUMPLE)
        check("NO_EVALUABLE si falta su dato",
              _estado(_ctx(dias=3), "T99_INICIO_EN_DOMINGO") == rt.NO_EVALUABLE)
        check("aparece en tabla_reglas() (documentación/UI automáticas)",
              any(f["codigo"] == "T99_INICIO_EN_DOMINGO" for f in rt.tabla_reglas()))
        raiz = Path(tempfile.mkdtemp(prefix="cfg_nueva_"))
        try:
            cfg = _cfg_archivo({"reglas": {"T99_INICIO_EN_DOMINGO": {"severidad": "MEDIA"}}}, raiz)
            check("y se le puede cambiar la severidad por configuración desde el día 1",
                  _regla(domingo, "T99_INICIO_EN_DOMINGO", cfg).severidad == rt.MEDIA)
        finally:
            shutil.rmtree(raiz, ignore_errors=True)

    check("al salir, el catálogo vuelve a su estado original",
          not any(r.codigo == "T99_INICIO_EN_DOMINGO" for r in rt.CATALOGO))

    # Una regla con BUG no puede tumbar el procesamiento de un documento.
    def _t98_con_bug(ctx, u):               # noqa: ARG001
        return 1 / 0

    with _catalogo_con(rt.ReglaTiempo("T98_CON_BUG", "una regla recién escrita con un fallo",
                                      rt.GRAVE, _t98_con_bug, campo="dias")):
        ctx = _ctx(inicio="2026-06-01", fin="2026-07-06", dias=5)
        r = _regla(ctx, "T98_CON_BUG")
        check("una regla que revienta queda NO_EVALUABLE", r.estado == rt.NO_EVALUABLE, r.estado)
        check("y dice que falló (no finge que el documento cumple)",
              r.motivo and "ZeroDivisionError" in r.motivo, r.motivo or "")
        check("el resto del veredicto sigue saliendo",
              "T01_DURACION_VS_RANGO" in rt.evaluar(ctx).codigos)


# --------------------------------------------------------------------------- #
# [10] El informe: serializable, tri-estado y con resumen coherente
# --------------------------------------------------------------------------- #
def test_informe() -> None:
    print("[10] validar_tiempos / validar_registro: informe serializable y coherente")
    informe = vt.validar_registro(
        _resultado({"fecha_inicio": "2026-06-01", "fecha_fin": "2026-07-06", "dias": 5,
                    rt.CLAVE_SNAPSHOT: {"fecha_inicio": "2026-06-01", "fecha_fin": "2026-07-06",
                                        "dias": 5, "dias_letra": None}}),
        hoy=HOY)
    check("acepta la salida de process() tal cual",
          informe["evidencia"]["leido"]["fecha_fin"] == "2026-07-06", str(informe["evidencia"]))
    texto = json.dumps(informe, ensure_ascii=False)
    check("el informe entero es serializable a JSON", len(texto) > 500)
    check("veredicto REVISAR", informe["veredicto"] == rt.V_REVISAR, informe["veredicto"])
    check("severidad_max GRAVE", informe["severidad_max"] == rt.GRAVE)
    check("trae el estado de TODAS las reglas del catálogo",
          len(informe["reglas"]) == len(rt.CATALOGO), str(len(informe["reglas"])))
    check("cada regla trae id, estado, severidad y qué afirma",
          all({"codigo", "estado", "severidad", "afirma"} <= set(r) for r in informe["reglas"]))
    check("solo NO_CUMPLE trae mensaje para el auxiliar",
          all((r["mensaje"] is not None) == (r["estado"] == rt.NO_CUMPLE)
              for r in informe["reglas"]))
    check("NO_EVALUABLE y DESACTIVADA traen motivo",
          all(r["motivo"] for r in informe["reglas"]
              if r["estado"] in (rt.NO_EVALUABLE, rt.DESACTIVADA)))
    res = informe["resumen"]
    check("el resumen cuadra con el catálogo",
          res["cumplen"] + res["no_cumplen"] + res["no_evaluables"] + res["desactivadas"]
          == res["reglas_en_catalogo"] == len(rt.CATALOGO), str(res))
    check("cuenta los hallazgos por severidad", res["graves"] == 1 and res["medias"] == 0)
    check("`problemas` del informe == los textos que ve el auxiliar",
          informe["problemas"] == list(rt.evaluar(_ctx(inicio="2026-06-01", fin="2026-07-06",
                                                       dias=5)).problemas))
    check("dice de dónde salió la configuración aplicada",
          informe["config"]["fuentes"][0] == "codigo" and informe["config"]["umbrales"]["dias_max"] == 540)
    compacto = rt.evaluar(_ctx(inicio="2026-06-01", fin="2026-07-06", dias=5)).como_dict()
    check("el veredicto operativo se serializa solo (ResultadoTiempos.como_dict)",
          json.loads(json.dumps(compacto))["hallazgos"][0]["codigo"] == "T01_DURACION_VS_RANGO"
          and compacto["puntaje"] == 60, str(compacto["puntaje"]))

    limpio = vt.validar_registro(
        _resultado({"fecha_inicio": "2026-06-01", "fecha_fin": "2026-06-05", "dias": 5}), hoy=HOY)
    check("documento coherente: veredicto COHERENTE", limpio["veredicto"] == rt.V_COHERENTE,
          limpio["veredicto"])
    check("y puntaje 100", limpio["puntaje_coherencia"] == 100, str(limpio["puntaje_coherencia"]))
    check("sin exigir revisión", limpio["exige_revision"] is False)

    # El puntaje ordena la cola: más grave = más abajo.
    grave = vt.validar_tiempos(_ctx(inicio="2026-06-01", fin="2026-07-06", dias=5))
    leve = vt.validar_tiempos(_ctx(inicio=(HOY - timedelta(days=900)).isoformat()))
    check("el puntaje ordena por gravedad (GRAVE < LEVE < limpio)",
          grave["puntaje_coherencia"] < leve["puntaje_coherencia"] < 100,
          f"{grave['puntaje_coherencia']} / {leve['puntaje_coherencia']}")
    check("un aviso LEVE da veredicto AVISOS (no bloquea)",
          leve["veredicto"] == rt.V_AVISOS, leve["veredicto"])
    check("validar_registro también acepta el bloque de fechas suelto",
          vt.validar_registro({"fecha_inicio": "2026-06-01", "fecha_fin": "2026-07-06", "dias": 5},
                              hoy=HOY)["veredicto"] == rt.V_REVISAR)
    check("y algo que no es un registro no revienta",
          vt.validar_registro(None, hoy=HOY)["veredicto"] == rt.V_SIN_DATOS)


# --------------------------------------------------------------------------- #
# [11] Integración: los hallazgos viajan por el canal que YA existía
# --------------------------------------------------------------------------- #
def test_integracion_erp() -> None:
    print("[11] erp.mapear_a_staging: `problemas` / `requiere_revision` + evidencia en la fila")
    inca = {"fecha_inicio": "2026-06-06", "fecha_fin": "2026-06-06", "dias": 1,
            "fecha_fin_recalculada": True,
            rt.CLAVE_SNAPSHOT: {"fecha_inicio": "2026-06-06", "fecha_fin": "2026-07-06",
                                "dias": 1, "dias_letra": None}}
    mapeo = erp.mapear_a_staging(_resultado(inca), "WHATSAPP", _LookupsFalsos(), hoy=HOY)

    check("el hallazgo entra en `problemas` (canal existente) y es el ÚNICO problema",
          len(mapeo["problemas"]) == 1 and "no cuadran" in mapeo["problemas"][0],
          str(mapeo["problemas"]))
    check("y marca requiere_revision", mapeo["requiere_revision"] is True)
    check("severidad del veredicto en la fila", mapeo["row"]["severidad_tiempos"] == rt.GRAVE)
    check("código de regla en la fila (para ordenar la cola)",
          mapeo["row"]["alertas_tiempos"] == "T01_DURACION_VS_RANGO",
          str(mapeo["row"]["alertas_tiempos"]))
    check("la fila conserva el fin IMPRESO, no el re-derivado",
          mapeo["row"]["fechafin_leida"] == "2026-07-06", str(mapeo["row"]["fechafin_leida"]))
    check("y los días impresos", mapeo["row"]["dias_leidos"] == 1)
    check("estructura detallada disponible para la UI/API",
          mapeo["tiempos"]["reglas"] and mapeo["hallazgos_tiempos"][0]["codigo"] == "T01_DURACION_VS_RANGO")
    # El motor MARCA y explica; no decide. Un hallazgo GRAVE de tiempos no cambia por sí
    # mismo el estado del flujo (eso es de otras señales) ni aprueba/rechaza nada.
    check("NUNCA se rechaza solo: la fila entra a revisión humana",
          mapeo["row"]["estado"] == "PENDIENTE_REVISION", str(mapeo["row"]["estado"]))
    check("nunca escribe en la tabla del ERP (solo staging)",
          "fechafin_leida" in mapeo["row"] and mapeo["row"]["fechavencimiento"] == "2026-06-07")

    # Con la severidad bajada por configuración, el MISMO documento deja de bloquear.
    raiz = Path(tempfile.mkdtemp(prefix="cfg_erp_"))
    try:
        cfg = _cfg_archivo({"reglas": {"T01_DURACION_VS_RANGO": {"severidad": "LEVE"}}}, raiz)
        m2 = erp.mapear_a_staging(_resultado(inca), "WHATSAPP", _LookupsFalsos(), hoy=HOY,
                                  config_reglas=cfg)
        check("severidad LEVE por config: el mensaje pasa a avisos",
              any("no cuadran" in a for a in m2["avisos_tiempos"])
              and not any("no cuadran" in p for p in m2["problemas"]), str(m2["problemas"]))
        check("y la fila lo registra como LEVE", m2["row"]["severidad_tiempos"] == rt.LEVE)
        # Consecuencia práctica del cambio de severidad (esto es lo que pidió el cliente):
        # el MISMO documento deja de bloquear la aprobación, sin desplegar nada.
        check("con LEVE el documento ya no exige revisión por tiempos",
              m2["requiere_revision"] is False and not m2["problemas"], str(m2["problemas"]))
    finally:
        shutil.rmtree(raiz, ignore_errors=True)

    # El motor no puede duplicar mensajes con los que erp ya emitía.
    dias_malos = {"fecha_inicio": None, "fecha_fin": None, "dias": 900,
                  rt.CLAVE_SNAPSHOT: {"fecha_inicio": None, "fecha_fin": None, "dias": 900,
                                      "dias_letra": None}}
    m3 = erp.mapear_a_staging(_resultado(dias_malos), "WHATSAPP", _LookupsFalsos(), hoy=HOY)
    sobre_dias = [p for p in m3["problemas"] if "días" in p or "dias" in p]
    check("días fuera de rango: UN solo mensaje (el de la regla, con el valor leído)",
          len(sobre_dias) == 1 and "fuera del rango válido" in sobre_dias[0], str(sobre_dias))
    check("el valor inutilizable no viaja a la columna del ERP",
          m3["row"]["Numerodias"] is None and m3["row"]["fechavencimiento"] is None)
    check("pero queda como evidencia de lo leído", m3["row"]["dias_leidos"] == 900)
    check("y el campo se pide al auxiliar",
          any(c["campo"] == "dias" for c in m3["campos_faltantes"]))

    # Documento legítimo con inicio DERIVADO: nada que reportar por tiempos.
    rec = {"incapacidad": {"fecha_fin": "2026-06-30", "dias": 5}}
    rec["incapacidad"][rt.CLAVE_SNAPSHOT] = rt.snapshot_leidos(rec["incapacidad"])
    normalizar_fechas(rec)
    m4 = erp.mapear_a_staging(_resultado(rec["incapacidad"]), "WHATSAPP", _LookupsFalsos(), hoy=HOY)
    check("inicio derivado: sin alertas de tiempos",
          m4["row"]["alertas_tiempos"] is None and m4["row"]["severidad_tiempos"] is None,
          str(m4["row"]["alertas_tiempos"]))
    check("el aviso de fecha calculada sigue siendo el de siempre (no bloquea)",
          m4["fecha_inicio_calculada"] is True
          and not any("cuadran" in p for p in m4["problemas"]), str(m4["problemas"]))


def main() -> int:
    print("=" * 72)
    print("PRUEBAS del motor de validación temporal (incapacidad_ocr/reglas_tiempo.py)")
    print("=" * 72)
    test_catalogo()
    test_reglas_cumple_y_no_cumple()
    test_reglas_del_historico()
    test_no_evaluable()
    test_valor_calculado_no_dispara()
    test_evidencia_sobrevive()
    test_config_en_caliente()
    test_config_corrupta()
    test_sin_bd()
    test_regla_nueva()
    test_informe()
    test_integracion_erp()
    print("-" * 72)
    print("RESULTADO:", "TODO OK" if _fail == 0 else f"{_fail} fallo(s)")
    return 1 if _fail else 0


if __name__ == "__main__":
    sys.exit(main())
