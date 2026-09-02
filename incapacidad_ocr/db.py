"""Acceso a MySQL (BD ASTGU): conexión, INSERT a staging y consultas de revisión.

Credenciales por variables de entorno (nunca hardcodeadas). Insertamos en la tabla STAGING
`lp_ausentismos_ia` (estado PENDIENTE_REVISION); el ERP promueve al aprobar. 100% local.
"""
from __future__ import annotations

import os
from contextlib import contextmanager
from typing import Any, Optional

STAGING_TABLE = "lp_ausentismos_ia"


def db_config() -> dict[str, Any]:
    return {
        "host": os.environ.get("DB_HOST", "localhost"),
        "port": int(os.environ.get("DB_PORT", 3306)),
        "database": os.environ.get("DB_NAME", "ASTGU"),
        "user": os.environ.get("DB_USER", "ocr"),
        "password": os.environ.get("DB_PASSWORD", "ocr"),
    }


def crear_conexion():
    import mysql.connector  # import perezoso

    cfg = db_config()
    return mysql.connector.connect(
        host=cfg["host"], port=cfg["port"], database=cfg["database"],
        user=cfg["user"], password=cfg["password"],
        autocommit=False, charset="utf8mb4", connection_timeout=5,
    )


@contextmanager
def conexion_mysql():
    cx = crear_conexion()
    try:
        yield cx
    finally:
        cx.close()


def db_disponible() -> bool:
    try:
        cx = crear_conexion()
        cx.close()
        return True
    except Exception:
        return False


def insertar_staging(cx, row: dict[str, Any]) -> int:
    """INSERT de una fila (dict columna→valor) en lp_ausentismos_ia. Devuelve el id."""
    cols = list(row.keys())
    marcadores = ", ".join(["%s"] * len(cols))
    sql = f"INSERT INTO {STAGING_TABLE} ({', '.join(cols)}) VALUES ({marcadores})"
    cur = cx.cursor()
    try:
        cur.execute(sql, [row[c] for c in cols])
        cx.commit()
        return cur.lastrowid
    except Exception:
        cx.rollback()
        raise
    finally:
        cur.close()


REGLAS_TIEMPO_TABLE = "lp_reglas_tiempo_ia"
UMBRALES_TIEMPO_TABLE = "lp_umbrales_tiempo_ia"


def leer_config_reglas_tiempo(cx) -> dict[str, Any]:
    """Config del motor de tiempos guardada en BD → forma que entiende `reglas_tiempo`.

    Es la vía para cambiar una severidad o un umbral en producción SIN volver a
    desplegar (el código Python va dentro de la imagen). Si las tablas no existen
    todavía (BD anterior a `sql/migracion_reglas_tiempo.sql`, o el esquema real del ERP
    sin migrar), se devuelve ``{}``: el motor sigue con el archivo/los defaults —
    la misma degradación que `Lookups.documentos_requeridos`.
    """
    datos: dict[str, Any] = {}
    cur = cx.cursor()
    try:
        try:
            cur.execute(f"SELECT codigo, severidad, activa FROM {REGLAS_TIEMPO_TABLE}")
            reglas = {}
            for codigo, severidad, activa in cur.fetchall():
                ajuste: dict[str, Any] = {}
                if severidad is not None:
                    ajuste["severidad"] = severidad
                if activa is not None:
                    ajuste["activa"] = bool(activa)
                if ajuste:
                    reglas[str(codigo)] = ajuste
            if reglas:
                datos["reglas"] = reglas
        except Exception:  # noqa: BLE001 — tabla ausente: se sigue con los defaults
            pass
        try:
            cur.execute(f"SELECT nombre, valor FROM {UMBRALES_TIEMPO_TABLE}")
            umbrales = {str(n): v for n, v in cur.fetchall() if v is not None}
            if umbrales:
                datos["umbrales"] = umbrales
        except Exception:  # noqa: BLE001
            pass
    finally:
        cur.close()
    return datos


def _iso_fechas(filas: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """DATE/TIMESTAMP → str para que sean serializables a JSON."""
    import datetime as _dt
    for f in filas:
        for k, v in f.items():
            if isinstance(v, (_dt.date, _dt.datetime)):
                f[k] = v.isoformat() if hasattr(v, "isoformat") else str(v)
    return filas


ALERTAS_TABLE = "lp_alertas_documentacion"


def insertar_alerta(cx, row: dict[str, Any]) -> int:
    """INSERT de una alerta de documentación faltante. Devuelve el id."""
    cols = list(row.keys())
    marcadores = ", ".join(["%s"] * len(cols))
    sql = f"INSERT INTO {ALERTAS_TABLE} ({', '.join(cols)}) VALUES ({marcadores})"
    cur = cx.cursor()
    try:
        cur.execute(sql, [row[c] for c in cols])
        cx.commit()
        return cur.lastrowid
    except Exception:
        cx.rollback()
        raise
    finally:
        cur.close()


def listar_staging(cx, limite: int = 20, estado: Optional[str] = None) -> list[dict[str, Any]]:
    """Últimos registros (para la pantalla del auxiliar). Filtra por estado si se da."""
    cur = cx.cursor(dictionary=True)
    base = (
        "SELECT id, creado_en, estado, cedula_leida, paciente_leido, idlpempleado, "
        "fechainicio, Numerodias, fechavencimiento, idlpdiagnosticos, codigo_diagnostico_leido, idlpentidad, "
        "idlptipoausentismo, idlpnivelincapacidad, documentacion_estado, problemas, archivo_origen "
        f"FROM {STAGING_TABLE} "
    )
    try:
        if estado:
            cur.execute(base + "WHERE estado = %s ORDER BY id DESC LIMIT %s", (estado, int(limite)))
        else:
            cur.execute(base + "ORDER BY id DESC LIMIT %s", (int(limite),))
        filas = cur.fetchall()
    finally:
        cur.close()
    return _iso_fechas(filas)


def obtener_staging(cx, registro_id: int) -> Optional[dict[str, Any]]:
    """Un registro completo (para cargarlo en el formulario de revisión)."""
    cur = cx.cursor(dictionary=True)
    try:
        cur.execute(f"SELECT * FROM {STAGING_TABLE} WHERE id = %s", (int(registro_id),))
        fila = cur.fetchone()
    finally:
        cur.close()
    if not fila:
        return None
    return _iso_fechas([fila])[0]


# Columnas que la revisión humana puede sobre-escribir al guardar/aprobar.
_COLS_ACTUALIZABLES = {
    "fechainicio", "Numerodias", "fechavencimiento", "fechaaccidente", "numeroorden",
    "observaciones", "original", "idlpdiagnosticos", "idlpempleado", "idlptipoausentismo",
    "idlpnivelincapacidad", "idlpentidad", "tipoentidad", "idlpestadosrecepausentismos", "cedula_leida",
    "codigo_diagnostico_leido", "eps_leida", "paciente_leido", "problemas",
    "documentacion_estado", "documentos_faltantes",
    # El veredicto temporal se RECALCULA al guardar (el auxiliar corrigió las fechas/días).
    # `fechafin_leida`/`dias_leidos` NO están aquí a propósito: son la EVIDENCIA de lo que
    # el documento imprimía y no se pisan con una corrección manual.
    "alertas_tiempos", "severidad_tiempos",
}


def actualizar_revision(cx, registro_id: int, row: dict[str, Any], estado: str,
                        nota: Optional[str] = None) -> bool:
    """Guarda las correcciones manuales (row re-mapeado) y fija el estado del flujo.

    estado ∈ {PENDIENTE_REVISION, APROBADO, RECHAZADO}. ``nota`` se anexa a observaciones.
    """
    datos = {k: v for k, v in (row or {}).items() if k in _COLS_ACTUALIZABLES}
    if nota:
        obs = datos.get("observaciones") or ""
        datos["observaciones"] = (f"{obs} | {nota}".strip(" |"))[:65000]
    datos["estado"] = estado
    sets = ", ".join(f"{c} = %s" for c in datos)
    valores = list(datos.values()) + [int(registro_id)]
    cur = cx.cursor()
    try:
        cur.execute(f"UPDATE {STAGING_TABLE} SET {sets} WHERE id = %s", valores)
        cx.commit()
        return cur.rowcount > 0
    except Exception:
        cx.rollback()
        raise
    finally:
        cur.close()


def actualizar_estado(cx, registro_id: int, estado: str, nota: Optional[str] = None) -> bool:
    """Cambia solo el estado (aprobar/rechazar sin re-mapear). Anexa nota a observaciones."""
    cur = cx.cursor()
    try:
        if nota:
            cur.execute(
                f"UPDATE {STAGING_TABLE} SET estado = %s, "
                "observaciones = LEFT(CONCAT(COALESCE(observaciones,''), ' | ', %s), 65000) "
                "WHERE id = %s",
                (estado, nota, int(registro_id)),
            )
        else:
            cur.execute(f"UPDATE {STAGING_TABLE} SET estado = %s WHERE id = %s",
                        (estado, int(registro_id)))
        cx.commit()
        return cur.rowcount > 0
    except Exception:
        cx.rollback()
        raise
    finally:
        cur.close()


def eliminar_staging_por_archivos(cx, archivos: list[str], solo_pendientes: bool = True) -> dict[str, int]:
    """Borra las filas de staging (y sus alertas) que vinieron de estos archivos.

    Es el apoyo del REINICIO DE PRUEBA (`batch.reiniciar_prueba`): deja la BD como antes de
    la corrida para poder repetir el lote sobre los mismos documentos.

    Deliberadamente NO existe un borrado masivo: se filtra por `archivo_origen` con la lista
    exacta de archivos que se están reiniciando, porque estas mismas funciones apuntan a la BD
    ASTGU **real** en producción y un DELETE sin filtro ahí sería catastrófico. Por el mismo
    motivo `solo_pendientes` está activo por defecto: lo que un auxiliar ya aprobó o rechazó
    es una decisión humana y no se toca.
    """
    if not archivos:
        return {"staging": 0, "alertas": 0}
    marcadores = ", ".join(["%s"] * len(archivos))
    cur = cx.cursor()
    try:
        # Las alertas primero: cuelgan del id de staging (id_ausentismo_ia).
        cond = f"archivo_origen IN ({marcadores})"
        params = list(archivos)
        if solo_pendientes:
            cond += " AND estado = %s"
            params.append("PENDIENTE_REVISION")
        cur.execute(f"SELECT id FROM {STAGING_TABLE} WHERE {cond}", tuple(params))
        ids = [f[0] for f in cur.fetchall()]
        alertas = 0
        if ids:
            m_ids = ", ".join(["%s"] * len(ids))
            try:
                cur.execute(f"DELETE FROM {ALERTAS_TABLE} WHERE id_ausentismo_ia IN ({m_ids})", tuple(ids))
                alertas = cur.rowcount
            except Exception:  # noqa: BLE001 — la tabla de alertas puede no existir en algunos entornos
                alertas = 0
            cur.execute(f"DELETE FROM {STAGING_TABLE} WHERE id IN ({m_ids})", tuple(ids))
        cx.commit()
        return {"staging": len(ids), "alertas": alertas}
    except Exception:
        cx.rollback()
        raise
    finally:
        cur.close()
