"""API pública de la VALIDACIÓN TEMPORAL (coherencia de fechas y duración).

Este módulo es la **puerta de entrada**: lo que importa el resto del mundo (la API web,
el lote, el CLI, otros motores de análisis y las pruebas). La lógica NO vive aquí.

    ┌─ incapacidad_ocr/reglas_tiempo.py ─ CATÁLOGO de reglas + motor + configuración
    └─ incapacidad_ocr/validacion_temporal.py ─ ESTE archivo: nombre estable + atajos

Por qué está separado y por qué no duplica nada
-----------------------------------------------
La regla de oro de esta familia es que **haya UNA sola verdad**: la reconciliación de
fechas vive solo en ``extract.normalizar_fechas()`` y el juicio sobre los tiempos vive
solo en ``reglas_tiempo``. Duplicar cualquiera de las dos deja dos verdades que se
contradicen en cuanto alguien toque una. Así que aquí **no hay ni una regla, ni un
umbral, ni un recorrido del catálogo**: solo se re-exporta lo de ``reglas_tiempo`` y se
añaden dos atajos que no existían (``validar_registro`` y el informe por consola).

Uso típico
----------
    from incapacidad_ocr.validacion_temporal import validar_registro

    informe = validar_registro(resultado_de_process)      # dict serializable a JSON
    informe["veredicto"]            # COHERENTE / AVISOS / REVISAR / SIN_DATOS
    informe["reglas"]               # estado de CADA regla: CUMPLE/NO_CUMPLE/NO_EVALUABLE
    informe["problemas"]            # los mismos textos que ve el auxiliar en la UI

Ver la tabla de reglas y la configuración que está aplicando ahora mismo (sirve para
comprobar, dentro del contenedor, que un cambio de severidad ya surtió efecto):

    python -m incapacidad_ocr.validacion_temporal

Dónde se toca cada cosa
-----------------------
* **Añadir una regla** → una entrada más en ``reglas_tiempo.CATALOGO`` (hay una receta
  paso a paso justo encima de esa tupla). El motor no se toca.
* **Cambiar una severidad / un umbral / apagar una regla SIN desplegar** → tabla
  ``lp_reglas_tiempo_ia`` / ``lp_umbrales_tiempo_ia`` en la BD, o el JSON del volumen
  (``ingesta/_sistema/control/reglas_tiempo.json``; plantilla comentada en
  ``config/reglas_tiempo.example.json``). Prioridad: BD > archivo > defaults del código.
"""
from __future__ import annotations

from datetime import date
from typing import Any, Optional

from .reglas_tiempo import (  # noqa: F401 — re-exportado a propósito (API pública)
    # --- severidades y estados
    GRAVE, MEDIA, LEVE, ORDEN_SEVERIDAD, SEVERIDADES_QUE_EXIGEN_REVISION,
    CUMPLE, NO_CUMPLE, NO_EVALUABLE, DESACTIVADA, ESTADOS,
    V_COHERENTE, V_AVISOS, V_REVISAR, V_SIN_DATOS,
    # --- declaración de reglas (lo que se amplía)
    CATALOGO, CATALOGO_POR_CODIGO, CAMPOS_EXIGIBLES, ReglaTiempo, tabla_reglas,
    # --- contexto y evidencia
    ContextoTiempos, construir_contexto, valores_leidos, resumen_evidencia,
    hay_evidencia_temporal,
    CLAVE_SNAPSHOT, snapshot_leidos, fecha_iso, entero_dias,
    # --- configuración en caliente
    ConfigReglas, cargar_config, config_por_defecto, UMBRALES_DEFAULT, LIMITES_UMBRAL,
    ENV_RUTA_CONFIG,
    # --- motor
    Hallazgo, ResultadoRegla, ResultadoTiempos, evaluar, evaluar_reglas, validar_tiempos,
)

__all__ = [
    "validar_tiempos", "validar_registro", "construir_contexto", "cargar_config",
    "evaluar", "evaluar_reglas", "tabla_reglas", "resumen_evidencia",
    "CATALOGO", "ReglaTiempo", "ContextoTiempos", "ConfigReglas",
    "ResultadoRegla", "ResultadoTiempos", "Hallazgo",
    "CUMPLE", "NO_CUMPLE", "NO_EVALUABLE", "DESACTIVADA",
    "GRAVE", "MEDIA", "LEVE",
    "V_COHERENTE", "V_AVISOS", "V_REVISAR", "V_SIN_DATOS",
]


def _partes(dato: Any) -> tuple[dict[str, Any], Optional[str]]:
    """(bloque de tiempos, tipo_documento) desde cualquiera de las formas del registro.

    Se aceptan las tres que circulan por el repo para que el llamador no tenga que
    recordar cuál tiene en la mano: la salida de ``processor.process()``
    (``{"incapacidad": {registro}}``), el registro del extractor
    (``{"tipo_documento":…, "incapacidad": {fechas}}``) y el bloque de fechas suelto.
    """
    if not isinstance(dato, dict):
        return {}, None
    registro = dato
    interno = dato.get("incapacidad")
    if isinstance(interno, dict) and isinstance(interno.get("incapacidad"), dict):
        registro = interno                      # venía la salida de process()
    bloque = registro.get("incapacidad")
    if not isinstance(bloque, dict):
        bloque = registro                       # ya era el bloque de fechas
    return bloque, registro.get("tipo_documento")


def validar_registro(registro: Any, *, hoy: Optional[date] = None,
                     overrides: Optional[dict[str, Any]] = None,
                     config: Optional[ConfigReglas] = None) -> dict[str, Any]:
    """Atajo: registro extraído (+ correcciones del auxiliar) → informe temporal completo.

    Es el mismo veredicto que ``erp.mapear_a_staging`` mete en ``problemas``, pero con el
    informe entero (estado de cada regla, evidencia y resumen) y sin necesitar BD, ERP ni
    lookups. Pensado para auditar un documento, para el CLI y para las pruebas.

    ``hoy`` es inyectable a propósito: las reglas de ventana temporal (inicio en el futuro
    / demasiado antiguo) se prueban de forma determinista, igual que en ``mapear_a_staging``.
    """
    bloque, tipo_documento = _partes(registro)
    contexto = construir_contexto(
        bloque, hoy=hoy or date.today(), overrides=overrides,
        # Los "efectivos" son informativos (los cita un mensaje, no los juzga ninguna
        # regla): aquí son lo que quedó en el registro tras la reconciliación.
        inicio_efectivo=bloque.get("fecha_inicio"), fin_efectivo=bloque.get("fecha_fin"),
        dias_efectivo=entero_dias(bloque.get("dias")), tipo_documento=tipo_documento,
    )
    return validar_tiempos(contexto, config)


def _main() -> int:
    """Informe por consola del catálogo y de la configuración EFECTIVA.

    Para operación: comprobar que un cambio de severidad/umbral hecho por SQL o en el JSON
    del volumen está realmente aplicado, sin tener que procesar un documento.
    """
    try:  # consola de Windows (cp1252): forzar UTF-8 para que se lean los acentos
        import sys

        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001 — si no se puede, se imprime igual
        pass
    cfg = cargar_config()
    print("Configuración de reglas de tiempos — fuentes aplicadas:", " > ".join(cfg.fuentes))
    for aviso in cfg.avisos:
        print("  AVISO de configuración:", aviso)
    print("\nUmbrales efectivos:")
    for nombre, valor in sorted(cfg.umbrales.items()):
        lo, hi = LIMITES_UMBRAL[nombre]
        print(f"  {nombre:26s} = {valor:<6d} (admisible {lo}..{hi})")
    print("\nReglas:")
    for r in CATALOGO:
        estado = "activa " if cfg.esta_activa(r.codigo) else "APAGADA"
        print(f"  {r.codigo:32s} {cfg.severidad_de(r.codigo):5s} {estado}  {r.afirma}")
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
