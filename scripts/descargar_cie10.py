"""Descarga UNA VEZ un catálogo público CIE-10 y lo deja versionado en `datos/cie10.csv`.

**Por qué existe.** La señal «este diagnóstico no existe» es la que más documentos adulterados
detecta, y sin catálogo no se puede afirmar nada: sin él *ningún* código resuelve y la señal
marcaría el 100% de los documentos legítimos. El catálogo autoritativo es `lpdiagnosticos` de
ASTGU, que el cliente todavía no nos ha dado. Esto es el **puente verificable** mientras llega.

**Por qué no viola el "100% local, sin APIs de pago".** Es una descarga de DATOS, una sola vez,
igual que los modelos ONNX que `rapidocr` trae dentro del wheel. No hay clave, no hay servicio de
IA, y **en runtime no se consulta nada**: el catálogo queda en MySQL (`lpdiagnosticos`) y la
consulta es un SELECT local. Si el servidor está aislado, el CSV viaja con el repositorio.

**Procedencia, dicha claramente.** La fuente es un repositorio público con la clasificación CIE-10
de la OMS en español. NO es la tabla oficial del Ministerio de Salud de Colombia — esa no está
publicada como dato abierto (se buscó en datos.gov.co y no existe como catálogo, solo datasets que
USAN los códigos). Por eso el script **valida** lo que descarga contra hechos que el cliente
confirmó, y aborta si no cuadran. Y es una edición ANTIGUA de la CIE-10: le faltan subdivisiones
que ediciones nuevas sí tienen (p.ej. `A09.0`/`A09.9`). Eso NO se puede tratar como "el código no
existe" — ver `erp.Lookups.categoria_subdividida` y el comentario de la regla.

    python scripts/descargar_cie10.py [--forzar]
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import sys
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SALIDA = REPO / "datos" / "cie10.csv"
FUENTE = "https://raw.githubusercontent.com/cayasso/cie10/master/cie10-array.json"

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # noqa: BLE001
    pass

# Hechos que el CLIENTE confirmó (tabla de motivos de los documentos adulterados) y que sirven
# para saber si el catálogo descargado es el correcto. Si alguno falla, el archivo NO se escribe:
# un catálogo equivocado no es un catálogo incompleto, es una fábrica de acusaciones falsas.
DEBE_FALTAR = ["R505"]                       # el cliente lo declaró inexistente; en CIE-10 no está
DEBE_ESTAR = ["R509", "M545", "N200", "O200", "S520", "G430", "A00", "G43"]
MINIMO_FILAS = 10_000                        # la CIE-10 completa ronda las 14.000 entradas


def descargar() -> list[dict]:
    print(f"descargando {FUENTE}")
    with urllib.request.urlopen(FUENTE, timeout=120) as r:  # noqa: S310 — URL fija, https
        crudo = r.read().decode("utf-8")
    datos = json.loads(crudo)
    # El formato de la fuente es [{"c": "A00", "d": "Cólera"}, ...]; se normaliza a claves
    # explícitas para no depender de nombres de una letra en el resto del código.
    filas = []
    for x in datos:
        cod = str(x.get("c") or x.get("code") or x.get("codigo") or "").strip().upper()
        desc = str(x.get("d") or x.get("description") or x.get("descripcion") or "").strip()
        if cod and desc:
            filas.append({"codigo": cod, "descripcion": desc})
    return filas


def validar(filas: list[dict]) -> list[str]:
    """Comprueba el catálogo contra los hechos confirmados. Devuelve la lista de problemas."""
    codigos = {f["codigo"].replace(".", "") for f in filas}
    problemas = []
    if len(filas) < MINIMO_FILAS:
        problemas.append(f"solo {len(filas)} filas (se esperaban >= {MINIMO_FILAS})")
    for c in DEBE_FALTAR:
        if c in codigos:
            problemas.append(f"{c} SÍ está en el catálogo y el cliente lo declaró inexistente "
                             "→ no es el catálogo que creemos")
    for c in DEBE_ESTAR:
        if c not in codigos:
            problemas.append(f"falta {c}, que debería existir")
    if not any(re.fullmatch(r"[A-Z]\d{3}", c) for c in codigos):
        problemas.append("no hay ningún código de 4 caracteres (el nivel reportable)")
    return problemas


def main() -> int:
    ap = argparse.ArgumentParser(description="Descarga el catálogo CIE-10 público.")
    ap.add_argument("--forzar", action="store_true", help="Sobrescribe aunque ya exista.")
    args = ap.parse_args()

    if SALIDA.is_file() and not args.forzar:
        with SALIDA.open(encoding="utf-8", newline="") as fh:
            n = sum(1 for _ in csv.DictReader(fh))
        print(f"{SALIDA} ya existe ({n} filas). Usa --forzar para volver a descargarlo.")
        return 0

    filas = descargar()
    print(f"{len(filas)} entradas")
    problemas = validar(filas)
    if problemas:
        print("\n*** El catálogo descargado NO pasa la validación — no se escribe nada ***")
        for p in problemas:
            print("  -", p)
        return 1

    subdiv = {f["codigo"].replace(".", "")[:3] for f in filas
              if len(f["codigo"].replace(".", "")) == 4}
    cat3 = {c for c in (f["codigo"].replace(".", "") for f in filas) if len(c) == 3}
    SALIDA.parent.mkdir(parents=True, exist_ok=True)
    with SALIDA.open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=["codigo", "descripcion"])
        w.writeheader()
        w.writerows(sorted(filas, key=lambda f: f["codigo"]))
    print(f"\nescrito {SALIDA}")
    print(f"  validación OK: {len(filas)} entradas · {len(cat3)} categorías de 3 caracteres, "
          f"{len(subdiv)} de ellas subdivididas")
    print("  (esa diferencia importa: una categoría SIN subdividir en esta edición NO permite "
          "afirmar que un código de 4 no existe — ver erp.Lookups.categoria_subdividida)")
    print("\nPara cargarlo en la BD:  python scripts/sembrar_bd_prueba.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
