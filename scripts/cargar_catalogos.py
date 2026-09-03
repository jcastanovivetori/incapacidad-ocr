"""Carga los catálogos que el repositorio SÍ trae consigo. No necesita el corpus.

Este script existe porque faltaba un eslabón: el catálogo CIE-10 completo viaja en el
repositorio (`datos/cie10.csv`, 14.484 códigos) pero el único que lo cargaba era
`sembrar_bd_prueba.py`, que **exige el corpus del cliente** (`MAPEO.csv`). Resultado: quien
clonaba el repo y no tenía los documentos se quedaba con los catálogos mínimos de
`sql/init.sql` — sin CIE-10 y **sin la tabla `lpeps`**, que `init.sql` no crea. Con eso, dos
piezas quedaban apagadas sin avisar:

  * la señal «este diagnóstico no existe» (exige catálogo cargado, ver `datos/LEEME.md`);
  * el checklist de radicación ante la EPS (consulta `lpeps`, y sin la tabla degrada a []).

Lo que carga, todo de fuentes que están en el repositorio y **sin un solo dato personal**:

  * `lpdiagnosticos` — el CIE-10 completo de `datos/cie10.csv`, REEMPLAZANDO lo que hubiera.
  * `lpeps`          — crea la tabla (con la errata `cheklistradicaciones` del ERP).
  * `lpentidades`    — las palabras clave de EPS con las que hace match el lookup.
  * checklist de radicación de una **EPS DEMO ficticia**, solo para poder ejercitar ese
    camino sin datos del cliente (`--sin-demo` lo omite).

Lo que NO carga, a propósito: **empleados**. Una cédula es un dato personal y no se inventa;
mientras no lleguen los de ASTGU, los casos salen con «cédula no encontrada», que es la
verdad. Los empleados del corpus real los siembra `sembrar_bd_prueba.py`.

    python scripts/cargar_catalogos.py              # genera el SQL y lo aplica
    python scripts/cargar_catalogos.py --solo-sql   # genera el SQL y no toca la BD
    python scripts/cargar_catalogos.py --sin-demo   # sin la EPS de demostración
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(Path(__file__).resolve().parent))

# Se reutiliza la aplicación del SQL de `sembrar_bd_prueba` a propósito: el conector de Python
# muere con "Commands out of sync" en un script de varias sentencias, y allí ya está resuelto
# con el cliente `mysql`. Una sola implementación de eso en el repo.
from sembrar_bd_prueba import EPS_EXTRA, _aplicar_con_cliente_mysql, _q  # noqa: E402

CIE10_CSV = REPO / "datos" / "cie10.csv"
SALIDA = REPO / "sql" / "catalogos_publicos.sql"

# EPS ficticia. El id 9999 está fuera del rango de los ids reales del ERP para que, cuando
# lleguen los de ASTGU, no choque con ninguno.
#
# El checklist se guarda como **JSON plano**, que es la forma que tienen las filas reales en la
# tabla (comprobado con un SELECT sobre `lpeps`). El export CSV del ERP sí lo entrega envuelto
# en comillas dobles y con las internas duplicadas, pero eso es un artefacto del CSV: quien lo
# desenvuelve es el cargador. Aquí se intentó primero imitar esa forma duplicando las comillas
# y `erp.documentos_checklist_radicacion` devolvía [] —quita las comillas EXTERNAS pero no
# deshace el duplicado—, o sea que el checklist habría quedado inerte en silencio, que es
# exactamente el fallo que este script viene a cerrar.
#
# Sí se conserva la errata `CERTICADO LABORAL` del catálogo del cliente: es un nombre de
# documento real y el canonizador tiene que seguir reconociéndolo.
EPS_DEMO_ID = 9999
EPS_DEMO_NOMBRE = "EPS DEMO (ficticia, para pruebas)"
EPS_DEMO_CHECKLIST = json.dumps({
    "ausentismos": [
        {"idlptipoausentismo": 3, "documentos": [                    # enfermedad general
            {"nombredocumento": "INCAPACIDAD"},
            {"nombredocumento": "HISTORIA CLINICA"},
            {"nombredocumento": "CERTICADO LABORAL"},
        ]},
        {"idlptipoausentismo": 2, "documentos": [                    # accidente de trabajo
            {"nombredocumento": "INCAPACIDAD"},
            {"nombredocumento": "FURAT"},
        ]},
        {"idlptipoausentismo": 5, "documentos": [                    # licencia de maternidad
            {"nombredocumento": "INCAPACIDAD"},
            {"nombredocumento": "CERTIFICADO DE NACIDO VIVO"},
            {"nombredocumento": "REGISTRO CIVIL"},
        ]},
    ]
}, ensure_ascii=False, separators=(",", ":"))


def _catalogo_cie10() -> list[tuple[str, str]]:
    if not CIE10_CSV.is_file():
        raise SystemExit(
            f"Falta {CIE10_CSV}. Debería venir en el repositorio; si no está: "
            f"python scripts/descargar_cie10.py"
        )
    filas: list[tuple[str, str]] = []
    with CIE10_CSV.open(encoding="utf-8", newline="") as fh:
        for r in csv.DictReader(fh):
            cod = (r.get("codigo") or "").strip().upper()
            desc = (r.get("descripcion") or "").strip()
            if cod and desc:
                filas.append((cod, desc))
    if len(filas) < 10_000:
        # El catálogo se valida al descargarlo (`descargar_cie10.py`); aquí solo se comprueba
        # que no se esté cargando un archivo truncado, porque un catálogo incompleto NO es
        # inocuo: convierte códigos legítimos en "diagnósticos que no existen".
        raise SystemExit(f"{CIE10_CSV} tiene {len(filas)} entradas: parece truncado, no se carga.")
    return filas


def generar_sql(con_demo: bool = True) -> str:
    catalogo = _catalogo_cie10()
    L: list[str] = []
    add = L.append
    add("-- =========================================================================")
    add("--  catalogos_publicos.sql — GENERADO por scripts/cargar_catalogos.py")
    add("--")
    add("--  SIN DATOS PERSONALES: solo el catálogo CIE-10 público y nombres de EPS.")
    add("--  Por eso este archivo SÍ se versiona (a diferencia de seed_bd_prueba.sql).")
    add("--")
    add(f"-- > diagnósticos ......... {len(catalogo)}  (datos/cie10.csv)")
    add(f"-- > palabras clave de EPS  {len(EPS_EXTRA)}")
    add(f"-- > EPS de demostración .. {'sí (id 9999, ficticia)' if con_demo else 'no'}")
    add("-- > empleados ............ 0  (una cédula es un dato personal: no se inventa)")
    add("-- =========================================================================")
    add("")
    add("-- `lpeps` NO está en sql/init.sql y es la tabla que consulta")
    add("-- `erp.Lookups.documentos_radicacion`. Sin ella el checklist degrada a [] en")
    add("-- silencio, así que la ausencia de alertas de radicación no significaba nada.")
    add("CREATE TABLE IF NOT EXISTS lpeps (")
    add("  idlpeps               INT PRIMARY KEY,")
    add("  nombre                VARCHAR(120) NOT NULL,")
    add("  identificacion        VARCHAR(20)  NULL,")
    add("  cheklistradicaciones  LONGTEXT     NULL   -- así se llama en el ERP (con la errata)")
    add(") ENGINE=InnoDB;")
    add("")
    add("-- Catálogo CIE-10 completo. Se REEMPLAZA entero, no se añade encima: un catálogo")
    add("-- mezclado es peor que uno incompleto, porque los códigos sueltos que hubiera antes")
    add("-- TAPAN los huecos reales y hacen que `erp.Lookups.categoria_subdividida` opine")
    add("-- sobre una base que no es la del catálogo (ver datos/LEEME.md).")
    add("-- El código se guarda CON punto en el nivel de 4 caracteres (X##.#), que es la forma")
    add("-- que muestra el ERP; el lookup compara sin punto, así que las dos formas resuelven.")
    add("DELETE FROM lpdiagnosticos;")
    # Se insertan en LOTES de 500 filas por sentencia. Con una sentencia por código, cargar el
    # catálogo tardaba más de dos minutos (14.484 idas y vueltas al servidor); así son ~30
    # sentencias y baja a segundos. Importa porque este paso lo corre el cliente al instalar.
    valores = []
    for cod, desc in catalogo:
        con_punto = f"{cod[:3]}.{cod[3:]}" if len(cod) >= 4 else cod
        valores.append(f"({_q(con_punto)}, {_q(desc[:200])})")
    for i in range(0, len(valores), 500):
        bloque = ",\n  ".join(valores[i:i + 500])
        add("INSERT INTO lpdiagnosticos (codigo, descripcion) VALUES\n  " + bloque +
            "\nON DUPLICATE KEY UPDATE descripcion=VALUES(descripcion);")
    add("")
    add("-- Palabras clave de EPS: el match es por CONTENCIÓN sin espacios, así que la clave")
    add("-- es la parte distintiva y estable ('SURA' casa con 'EPS.SURAMERICANA S.A/8').")
    for nombre in EPS_EXTRA:
        add(f"INSERT INTO lpentidades (nombre, nit, tipoentidad) "
            f"SELECT {_q(nombre)}, NULL, 1 FROM DUAL WHERE NOT EXISTS "
            f"(SELECT 1 FROM lpentidades WHERE nombre = {_q(nombre)});")
    add("")
    if con_demo:
        add("-- EPS DEMO: checklist de radicación FICTICIO, solo para ejercitar ese camino sin")
        add("-- datos del cliente. NO son los requisitos de ninguna EPS real — cuando llegue")
        add("-- `lpeps` de ASTGU hay que reemplazarlo. El id 9999 no choca con los ids del ERP.")
        add("-- Se guarda como JSON PLANO, que es la forma que tienen las filas reales de la")
        add("-- tabla; el envuelto-en-comillas del export CSV lo deshace el cargador.")
        add(f"INSERT INTO lpentidades (idlpentidad, nombre, nit, tipoentidad) VALUES "
            f"({EPS_DEMO_ID}, {_q(EPS_DEMO_NOMBRE[:78])}, NULL, 1) "
            f"ON DUPLICATE KEY UPDATE nombre=VALUES(nombre);")
        add(f"INSERT INTO lpeps (idlpeps, nombre, identificacion, cheklistradicaciones) VALUES "
            f"({EPS_DEMO_ID}, {_q(EPS_DEMO_NOMBRE)}, NULL, {_q(EPS_DEMO_CHECKLIST)}) "
            f"ON DUPLICATE KEY UPDATE cheklistradicaciones=VALUES(cheklistradicaciones);")
        add("")
    return "\n".join(L) + "\n"


def _consulta_escalar(sql: str) -> int | None:
    """Cuenta filas usando el cliente `mysql` (host o `docker exec`), no el conector.

    Igual que al aplicar el SQL: el objetivo es que este script funcione en una máquina que
    solo tenga **Docker**, que es el único requisito que documentamos. Exigir
    `mysql-connector-python` aquí dejaría el catálogo sin cargar en el escenario normal.
    """
    import shutil as _sh
    import subprocess

    from incapacidad_ocr import db as _db

    cfg = _db.db_config()          # solo lee variables de entorno; no importa el conector
    intentos = []
    if _sh.which("mysql"):
        intentos.append(["mysql", f"-h{cfg['host']}", f"-P{cfg['port']}", f"-u{cfg['user']}",
                         f"-p{cfg['password']}", "-N", "-B", "-e", sql, cfg["database"]])
    if _sh.which("docker"):
        intentos.append(["docker", "exec", "-i", "ocr-db", "mysql", f"-u{cfg['user']}",
                         f"-p{cfg['password']}", "-N", "-B", "-e", sql, cfg["database"]])
    for cmd in intentos:
        try:
            r = subprocess.run(cmd, capture_output=True, timeout=60)
        except Exception:  # noqa: BLE001 — se prueba el siguiente
            continue
        if r.returncode == 0:
            salida = r.stdout.decode("utf-8", "replace").strip().splitlines()
            if salida:
                try:
                    return int(salida[0].strip())
                except ValueError:
                    return None
    return None


def main() -> int:
    ap = argparse.ArgumentParser(description="Carga los catálogos públicos del repositorio.")
    ap.add_argument("--solo-sql", action="store_true", help="Genera el SQL y no toca la BD.")
    ap.add_argument("--sin-demo", action="store_true", help="Omite la EPS de demostración.")
    args = ap.parse_args()

    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        pass

    sql = generar_sql(con_demo=not args.sin_demo)
    SALIDA.parent.mkdir(parents=True, exist_ok=True)
    SALIDA.write_text(sql, encoding="utf-8", newline="\n")
    print(f"SQL generado: {SALIDA.relative_to(REPO)}  ({len(sql.splitlines())} líneas)")
    for ln in sql.splitlines():
        if ln.startswith("-- > "):
            print("  " + ln[5:])
    if args.solo_sql:
        return 0

    if not _aplicar_con_cliente_mysql(SALIDA):
        print("\nNo se pudo aplicar el SQL. Comprueba que la BD esté arriba:")
        print("  docker compose up -d db     (espera a que diga 'healthy')")
        print("Desde el host, la BD escucha en 127.0.0.1 -> usa DB_HOST=127.0.0.1.")
        print(f"El SQL quedó generado en {SALIDA.relative_to(REPO)}: aplicarlo es idempotente.")
        return 1
    n_dx = _consulta_escalar("SELECT COUNT(*) FROM lpdiagnosticos")
    n_eps = _consulta_escalar("SELECT COUNT(*) FROM lpentidades")
    n_chk = _consulta_escalar("SELECT COUNT(*) FROM lpeps WHERE cheklistradicaciones IS NOT NULL")
    if n_dx is None:
        print("\nSQL aplicado, pero no se pudo verificar el conteo. Compruébalo a mano:")
        print("  docker exec ocr-db mysql -uocr -pocr ASTGU -e 'SELECT COUNT(*) FROM lpdiagnosticos;'")
        return 0
    print(f"\nVerificado en la BD: {n_dx} diagnósticos · {n_eps} entidades · "
          f"{n_chk} EPS con checklist de radicación")
    if n_dx < 10_000:
        print("ATENCIÓN: el catálogo quedó incompleto. La señal «el diagnóstico no existe» "
              "marcaría documentos legítimos: revisa el error de arriba antes de probar.")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
