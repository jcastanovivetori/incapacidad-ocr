"""Migra la carpeta de ingesta del árbol ANTIGUO al de tres zonas numeradas.

    antiguo                        →  nuevo
    inbox/whatsapp|correo/            1_entrada/whatsapp|correo/
    inbox/original/                   1_entrada/ventanilla/
    inbox/sin_nomenclatura/           2_revisar/mal_nombrados/
    incompletos/                      2_revisar/faltan_soportes/
    cuarentena/                       2_revisar/con_error/
    procesados/                       3_archivo/
    logs/                             _sistema/logs/

Mueve el CONTENIDO conservando la sub-ruta (p.ej. ``procesados/LEONARDO GARNICA/2026/06/09/x.pdf``
→ ``3_archivo/LEONARDO GARNICA/2026/06/09/x.pdf``), nunca sobre-escribe (si el destino ya
existe deja el archivo donde está y lo reporta) y al final borra las carpetas viejas que
quedaron vacías. Es idempotente: correrlo dos veces no hace nada la segunda vez.

    python scripts/migrar_estructura_ingesta.py [--root RUTA] [--dry-run]
"""
from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
from incapacidad_ocr.batch import (ARCHIVO, CON_ERROR, ENTRADA, FALTAN_SOPORTES,  # noqa: E402
                                   LOGS, MAL_NOMBRADOS, REVISAR, SISTEMA, asegurar_estructura)

# (ruta vieja relativa, ruta nueva relativa). El orden importa: las rutas más específicas
# del inbox van ANTES que el inbox genérico.
MOVIMIENTOS: list[tuple[str, str]] = [
    (f"inbox/sin_nomenclatura", f"{REVISAR}/{MAL_NOMBRADOS}"),
    ("inbox/original", f"{ENTRADA}/ventanilla"),
    ("inbox", ENTRADA),
    ("incompletos", f"{REVISAR}/{FALTAN_SOPORTES}"),
    ("cuarentena", f"{REVISAR}/{CON_ERROR}"),
    ("procesados", ARCHIVO),
    ("logs", f"{SISTEMA}/{LOGS}"),
]


def _mover_arbol(origen: Path, destino: Path, dry_run: bool) -> tuple[int, list[str]]:
    """Mueve los archivos de ``origen`` a ``destino`` conservando la sub-ruta relativa."""
    movidos, choques = 0, []
    if not origen.is_dir():
        return movidos, choques
    for f in sorted(origen.rglob("*")):
        if not f.is_file() or f.name == ".gitkeep":
            continue
        rel = f.relative_to(origen)
        dst = destino / rel
        if dst.exists():
            choques.append(f"{origen.name}/{rel.as_posix()} (el destino ya existe)")
            continue
        print(f"  {origen.name}/{rel.as_posix()}  ->  {dst.relative_to(destino.parent.parent).as_posix()}")
        if not dry_run:
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(f), str(dst))
        movidos += 1
    return movidos, choques


def _borrar_vacias(base: Path, dry_run: bool) -> None:
    """Borra ``base`` y sus subcarpetas si quedaron vacías (solo .gitkeep cuenta como vacío)."""
    if not base.is_dir():
        return
    for d in sorted((p for p in base.rglob("*") if p.is_dir()), reverse=True):
        if not any(p.name != ".gitkeep" for p in d.iterdir()):
            print(f"  (vacía) elimina {d.relative_to(base.parent).as_posix()}")
            if not dry_run:
                for p in d.iterdir():
                    p.unlink()
                d.rmdir()
    if not any(p.name != ".gitkeep" for p in base.iterdir()):
        print(f"  (vacía) elimina {base.name}/")
        if not dry_run:
            for p in base.iterdir():
                p.unlink()
            base.rmdir()


def main() -> int:
    ap = argparse.ArgumentParser(description="Migra la ingesta al árbol de tres zonas.")
    ap.add_argument("--root", default=str(REPO / "ingesta"), help="Raíz de la ingesta.")
    ap.add_argument("--dry-run", action="store_true", help="Solo reporta lo que haría.")
    args = ap.parse_args()

    root = Path(args.root).resolve()
    if not root.is_dir():
        print(f"No existe la carpeta {root}")
        return 1

    viejas = [v for v, _ in MOVIMIENTOS if (root / v).is_dir()]
    if not viejas:
        print(f"Nada que migrar en {root}: ya está en el árbol nuevo.")
        return 0

    print(f"Migrando {root}{' (DRY-RUN)' if args.dry_run else ''}")
    if not args.dry_run:
        asegurar_estructura(root)

    total, choques = 0, []
    for viejo, nuevo in MOVIMIENTOS:
        m, c = _mover_arbol(root / viejo, root / nuevo, args.dry_run)
        total += m
        choques += c
    for viejo in ("inbox", "incompletos", "cuarentena", "procesados", "logs"):
        _borrar_vacias(root / viejo, args.dry_run)

    print(f"\n{total} archivo(s) movido(s).")
    if choques:
        print("Sin mover (revisar a mano):")
        for c in choques:
            print("  -", c)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
