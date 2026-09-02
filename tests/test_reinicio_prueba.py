"""Pruebas del REINICIO DE PRUEBA de la ingesta (ejecutable con python puro, sin pytest).

    python tests/test_reinicio_prueba.py

Cubre `batch.reiniciar_prueba()` en sus dos modos y las invariantes de seguridad del borrado en
BD (`db.eliminar_staging_por_archivos`). Todo con carpetas temporales y una conexión falsa: NO
toca la carpeta de ingesta real ni necesita MySQL.

Lo que se protege aquí es el daño: el modo con semilla BORRA documentos, y el borrado en BD corre
contra la misma función que en producción apunta a la BD ASTGU real.
"""
from __future__ import annotations

import os
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

try:  # consola Windows (cp1252) → forzar UTF-8 para acentos
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # noqa: BLE001
    pass

from incapacidad_ocr import batch, db  # noqa: E402

_fail = 0


def check(name: str, cond: bool, detail: str = "") -> None:
    global _fail
    ok = bool(cond)
    if not ok:
        _fail += 1
    print(("  PASS " if ok else "  FAIL ") + name + (f"  ->  {detail}" if detail else ""))


def _raiz() -> Path:
    """Árbol de ingesta nuevo en un temporal (el módulo lee INGESTA_ROOT, así que se pasa explícito)."""
    raiz = Path(tempfile.mkdtemp(prefix="test_reinicio_"))
    batch.asegurar_estructura(raiz)
    return raiz


def _doc(ruta: Path, nombre: str, contenido: bytes = b"%PDF-1.4 falso") -> Path:
    ruta.mkdir(parents=True, exist_ok=True)
    f = ruta / nombre
    f.write_bytes(contenido)
    return f


def _docs(base: Path) -> list[str]:
    return sorted(p.name for p in base.rglob("*") if p.is_file() and p.suffix.lower() in batch.EXT_OK)


def test_modo_semilla() -> None:
    print("[1] Modo SEMILLA: restaura el estado inicial exacto y conserva el canal")
    raiz = _raiz()
    try:
        semilla = raiz / batch.SISTEMA / batch.SEMILLA
        _doc(semilla / "whatsapp", "111_INCAPACIDAD.pdf")
        _doc(semilla / "correo", "222_INCAPACIDAD.pdf")
        _doc(semilla / "ventanilla", "333_PERMISO.pdf")
        # Estado "después de una corrida": los documentos ya se movieron a las zonas de salida,
        # con las carpetas por persona/fecha que crea el lote.
        _doc(raiz / batch.ARCHIVO / "ANA GOMEZ" / "2026" / "06" / "09", "111_INCAPACIDAD.pdf")
        _doc(raiz / batch.REVISAR / batch.FALTAN_SOPORTES / "LUIS PEREZ" / "2026" / "07" / "01",
             "222_INCAPACIDAD.pdf")
        _doc(raiz / batch.ENTRADA / "whatsapp", "sobra.pdf")   # residuo de una prueba anterior

        r = batch.reiniciar_prueba(raiz, limpiar_bd=False)

        check("modo", r["modo"] == "semilla", r["modo"])
        check("restaurados = 3", r["restaurados"] == 3, str(r["restaurados"]))
        check("descartados = 3 (2 de salida + 1 residuo de la entrada)", r["descartados"] == 3,
              str(r["descartados"]))
        check("entrada tiene los 3 de la semilla",
              _docs(raiz / batch.ENTRADA) == ["111_INCAPACIDAD.pdf", "222_INCAPACIDAD.pdf", "333_PERMISO.pdf"],
              str(_docs(raiz / batch.ENTRADA)))
        check("el residuo 'sobra.pdf' desapareció", "sobra.pdf" not in _docs(raiz / batch.ENTRADA))
        check("canal conservado: whatsapp",
              (raiz / batch.ENTRADA / "whatsapp" / "111_INCAPACIDAD.pdf").is_file())
        check("canal conservado: correo",
              (raiz / batch.ENTRADA / "correo" / "222_INCAPACIDAD.pdf").is_file())
        check("canal conservado: ventanilla",
              (raiz / batch.ENTRADA / "ventanilla" / "333_PERMISO.pdf").is_file())
        check("zonas de salida vacías",
              _docs(raiz / batch.REVISAR) == [] and _docs(raiz / batch.ARCHIVO) == [])
        check("carpetas por persona/fecha podadas", r["carpetas_podadas"] > 0, str(r["carpetas_podadas"]))
        check("la semilla sigue intacta (se copia, no se mueve)", len(_docs(semilla)) == 3)

        # Repetible: reiniciar dos veces deja exactamente lo mismo.
        r2 = batch.reiniciar_prueba(raiz, limpiar_bd=False)
        check("idempotente: 2º reinicio restaura los mismos 3", r2["restaurados"] == 3, str(r2["restaurados"]))
    finally:
        shutil.rmtree(raiz, ignore_errors=True)


def test_modo_movimiento() -> None:
    print("[2] Modo MOVIMIENTO (sin semilla): devuelve sin borrar nada")
    raiz = _raiz()
    try:
        _doc(raiz / batch.ARCHIVO / "ANA GOMEZ" / "2026" / "06" / "09", "111_INCAPACIDAD.pdf")
        _doc(raiz / batch.REVISAR / batch.CON_ERROR / "222", "222_INCAPACIDAD.pdf")

        r = batch.reiniciar_prueba(raiz, limpiar_bd=False)

        check("modo", r["modo"] == "movimiento", r["modo"])
        check("restaurados = 2", r["restaurados"] == 2, str(r["restaurados"]))
        check("NO borra nada (descartados = 0)", r["descartados"] == 0, str(r["descartados"]))
        check("vuelven a 1_entrada/whatsapp",
              _docs(raiz / batch.ENTRADA / "whatsapp") == ["111_INCAPACIDAD.pdf", "222_INCAPACIDAD.pdf"],
              str(_docs(raiz / batch.ENTRADA / "whatsapp")))
        check("avisa de la pérdida del canal original",
              any("canal" in a.lower() for a in r["avisos"]), str(r["avisos"]))
    finally:
        shutil.rmtree(raiz, ignore_errors=True)


def test_movimiento_no_sobreescribe() -> None:
    print("[3] Modo MOVIMIENTO: no sobre-escribe un archivo que ya está en la entrada")
    raiz = _raiz()
    try:
        _doc(raiz / batch.ENTRADA / "whatsapp", "111_INCAPACIDAD.pdf", b"ORIGINAL")
        _doc(raiz / batch.ARCHIVO / "ANA GOMEZ" / "2026" / "06" / "09", "111_INCAPACIDAD.pdf", b"OTRO")

        r = batch.reiniciar_prueba(raiz, limpiar_bd=False)

        check("no lo cuenta como restaurado", r["restaurados"] == 0, str(r["restaurados"]))
        check("el de la entrada NO se pisó",
              (raiz / batch.ENTRADA / "whatsapp" / "111_INCAPACIDAD.pdf").read_bytes() == b"ORIGINAL")
        check("el otro se queda donde estaba (no se pierde)",
              (raiz / batch.ARCHIVO / "ANA GOMEZ" / "2026" / "06" / "09" / "111_INCAPACIDAD.pdf").is_file())
        check("lo avisa", any("ya existía" in a for a in r["avisos"]), str(r["avisos"]))
    finally:
        shutil.rmtree(raiz, ignore_errors=True)


def test_nada_que_reiniciar() -> None:
    print("[4] Árbol vacío: no falla y lo dice")
    raiz = _raiz()
    try:
        r = batch.reiniciar_prueba(raiz, limpiar_bd=False)
        check("restaurados = 0", r["restaurados"] == 0, str(r["restaurados"]))
        check("avisa que no había nada", any("nada que reiniciar" in a for a in r["avisos"]), str(r["avisos"]))
    finally:
        shutil.rmtree(raiz, ignore_errors=True)


def test_colision_de_nombres_al_mover() -> None:
    print("[5] batch._mover: dos archivos con el mismo nombre NO se sobre-escriben")
    raiz = _raiz()
    try:
        a = _doc(raiz / batch.ENTRADA / "whatsapp", "555_INCAPACIDAD.pdf", b"PRIMERO")
        b = _doc(raiz / batch.ENTRADA / "correo", "555_INCAPACIDAD.pdf", b"SEGUNDO")
        destino = raiz / batch.ARCHIVO / "ANA GOMEZ" / "2026" / "06" / "09"
        batch._mover([a, b], destino)
        nombres = _docs(destino)
        check("los DOS llegaron (uno con sufijo _dupNN)", len(nombres) == 2, str(nombres))
        check("ningún contenido se perdió",
              sorted(p.read_bytes() for p in destino.iterdir()) == [b"PRIMERO", b"SEGUNDO"])
    finally:
        shutil.rmtree(raiz, ignore_errors=True)


class _CursorFalso:
    def __init__(self, registro: list) -> None:
        self.registro = registro
        self.rowcount = 2

    def execute(self, sql: str, params=None) -> None:
        self.registro.append((" ".join(sql.split()), params))

    def fetchall(self):
        return [(11,), (12,)]

    def fetchone(self):
        return (11,)          # COUNT(*) que ve `vaciar_staging_prueba`

    def close(self) -> None:
        pass


class _ConexionFalsa:
    """Conexión que solo registra el SQL: prueba el borrado sin una BD y sin riesgo."""

    def __init__(self) -> None:
        self.registro: list = []
        self.commits = 0
        self.rollbacks = 0

    def cursor(self, **_kw):
        return _CursorFalso(self.registro)

    def commit(self) -> None:
        self.commits += 1

    def rollback(self) -> None:
        self.rollbacks += 1


def test_borrado_bd_seguro() -> None:
    print("[6] db.eliminar_staging_por_archivos: invariantes de seguridad del borrado")
    cx = _ConexionFalsa()
    r = db.eliminar_staging_por_archivos(cx, ["a.pdf", "b.pdf"])
    sqls = [s for s, _ in cx.registro]

    check("devuelve lo borrado", r == {"staging": 2, "alertas": 2}, str(r))
    check("hace commit una vez", cx.commits == 1, str(cx.commits))
    check("filtra por archivo_origen", all("archivo_origen IN" in s for s in sqls if "SELECT id" in s))
    check("filtra por estado PENDIENTE_REVISION por defecto",
          any("estado = %s" in s for s in sqls)
          and any(p and "PENDIENTE_REVISION" in p for _, p in cx.registro))
    check("borra las alertas ANTES que el staging",
          next(i for i, s in enumerate(sqls) if "lp_alertas_documentacion" in s)
          < next(i for i, s in enumerate(sqls) if s.startswith("DELETE FROM lp_ausentismos_ia")))
    check("NINGÚN DELETE sin WHERE",
          all("WHERE" in s for s in sqls if s.startswith("DELETE")), str(sqls))
    check("usa marcadores, no interpolación (no hay .pdf dentro del SQL)",
          all(".pdf" not in s for s in sqls), str(sqls))

    vacio = _ConexionFalsa()
    check("lista vacía → no toca la BD",
          db.eliminar_staging_por_archivos(vacio, []) == {"staging": 0, "alertas": 0}
          and not vacio.registro)

    todos = _ConexionFalsa()
    db.eliminar_staging_por_archivos(todos, ["a.pdf"], solo_pendientes=False)
    check("solo_pendientes=False no filtra por estado",
          not any("estado = %s" in s for s, _ in todos.registro))


def test_vaciado_bd_exige_declaracion() -> None:
    print("[7] db.vaciar_staging_prueba: sin RESET_BD_PRUEBA=1 no vacía NADA")
    previo = os.environ.pop("RESET_BD_PRUEBA", None)
    try:
        class _CxProhibida:
            def cursor(self, **_kw):
                raise AssertionError("no debería llegar a abrir un cursor")

            def commit(self):
                pass

            def rollback(self):
                pass

        check("reset_bd_prueba_permitido() es False", not db.reset_bd_prueba_permitido())
        try:
            db.vaciar_staging_prueba(_CxProhibida())
            check("lanza RuntimeError antes de tocar la BD", False, "no lanzó")
        except RuntimeError as exc:
            check("lanza RuntimeError antes de tocar la BD", True)
            check("el mensaje explica cómo habilitarlo", "RESET_BD_PRUEBA" in str(exc), str(exc))
        except AssertionError:
            check("lanza RuntimeError antes de tocar la BD", False, "abrió un cursor")

        # Con la declaración presente: vacía, y las alertas ANTES del staging.
        os.environ["RESET_BD_PRUEBA"] = "1"
        cx = _ConexionFalsa()
        r = db.vaciar_staging_prueba(cx)
        sqls = [s for s, _ in cx.registro]
        check("cuenta lo vaciado", r == {"staging": 11, "alertas": 11}, str(r))
        check("usa TRUNCATE de las dos tablas",
              sum(1 for s in sqls if s.startswith("TRUNCATE TABLE")) == 2, str(sqls))
        check("vacía las alertas ANTES del staging",
              next(i for i, s in enumerate(sqls) if "TRUNCATE" in s and db.ALERTAS_TABLE in s)
              < next(i for i, s in enumerate(sqls) if "TRUNCATE" in s and db.STAGING_TABLE in s))
        check("NO toca ninguna tabla de catálogo",
              not any(t in s for s in sqls
                      for t in ("lpempleados", "lpdiagnosticos", "lpentidades", "lpeps",
                                "lprequisitos_eps")), str(sqls))
    finally:
        os.environ.pop("RESET_BD_PRUEBA", None)
        if previo is not None:
            os.environ["RESET_BD_PRUEBA"] = previo


def main() -> int:
    print("=" * 64)
    print("PRUEBAS reinicio de prueba de la ingesta")
    print("=" * 64)
    test_modo_semilla()
    test_modo_movimiento()
    test_movimiento_no_sobreescribe()
    test_nada_que_reiniciar()
    test_colision_de_nombres_al_mover()
    test_borrado_bd_seguro()
    test_vaciado_bd_exige_declaracion()
    print("-" * 64)
    print("RESULTADO:", "TODO OK" if _fail == 0 else f"{_fail} fallo(s)")
    return 1 if _fail else 0


if __name__ == "__main__":
    sys.exit(main())
