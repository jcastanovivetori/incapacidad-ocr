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


def listar_staging(cx, limite: int = 20) -> list[dict[str, Any]]:
    """Últimos registros en revisión (para la pantalla del auxiliar)."""
    cur = cx.cursor(dictionary=True)
    try:
        cur.execute(
            "SELECT id, creado_en, estado, cedula_leida, paciente_leido, idlpempleado, "
            "fechainicio, Numerodias, fechavencimiento, idlpdiagnosticos, idlpentidad, "
            "idlptipoausentismo, documentacion_estado, problemas, archivo_origen "
            f"FROM {STAGING_TABLE} ORDER BY id DESC LIMIT %s",
            (int(limite),),
        )
        filas = cur.fetchall()
    finally:
        cur.close()
    # DATE/TIMESTAMP → str para que sean serializables a JSON.
    import datetime as _dt
    for f in filas:
        for k, v in f.items():
            if isinstance(v, (_dt.date, _dt.datetime)):
                f[k] = v.isoformat() if hasattr(v, "isoformat") else str(v)
    return filas
