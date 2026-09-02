"""Aplica la regla del cliente sobre las filas EN ROJO de la tabla de motivos.

Diana (2026-09-02), sobre `Explicacion de archivos.jpeg`: **«el rojo es que está mal y se repite
la razón de la fila inmediatamente anterior»**.

Al medir la imagen por píxeles se vio que las filas rojas van en **rachas consecutivas** y que la
PRIMERA de cada racha sí trae motivo escrito; las siguientes lo tienen vacío. Es decir: el motivo
se escribió una vez por racha y el rojo marca «lo mismo que arriba». Este script propaga ese
motivo hacia abajo dentro de cada racha, sobre `ground_truth.json`.

Con eso desaparece la etiqueta `SIN_MOTIVO_REGISTRADO`, que era un «no sabemos qué buscar» y
bloqueaba la evaluación de 3 documentos.

    python scripts/resolver_motivos_heredados.py [--dry-run]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
GT = REPO.parent / "dataset-falsedad" / "ground_truth.json"

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # noqa: BLE001
    pass

SIN_MOTIVO = "SIN_MOTIVO_REGISTRADO"


def main() -> int:
    ap = argparse.ArgumentParser(description="Propaga el motivo en las filas rojas.")
    ap.add_argument("--dry-run", action="store_true", help="Solo reporta lo que haría.")
    args = ap.parse_args()

    if not GT.is_file():
        print(f"No existe {GT}")
        return 1
    d = json.loads(GT.read_text(encoding="utf-8"))
    filas = d.get("filas") or []

    cambios = []
    # `anterior` guarda las señales de la fila previa, que es de donde HEREDA una fila roja
    # sin motivo. Se recorre en orden: una racha de 3 rojas hereda en cascada desde la primera.
    anterior: list[str] = []
    for i, f in enumerate(filas, start=1):
        senales = list(f.get("senales") or [])
        if f.get("en_rojo") and f.get("motivo_vacio") and anterior:
            heredadas = [s for s in anterior if s != SIN_MOTIVO]
            if heredadas:
                cambios.append((i, f.get("archivo", ""), senales, heredadas))
                senales = heredadas
                f["senales"] = heredadas
                f["motivo_heredado_de_fila_anterior"] = True
                f["motivo_texto"] = (f.get("motivo_texto") or "") or "(heredado de la fila anterior)"
        anterior = senales

    # La taxonomía deja de necesitar SIN_MOTIVO_REGISTRADO si ya no lo usa nadie.
    usadas = {s for f in filas for s in (f.get("senales") or [])}
    tax = d.get("taxonomia") or {}
    if SIN_MOTIVO in tax and SIN_MOTIVO not in usadas:
        tax.pop(SIN_MOTIVO)
        d["taxonomia"] = tax
    d["regla_filas_rojas"] = (
        "Diana 2026-09-02: el rojo indica que el documento está mal y que la razón es la de la "
        "fila inmediatamente anterior. Las filas rojas van en rachas y solo la primera trae el "
        "motivo escrito; las demás lo heredan en cascada. Aplicado por "
        "scripts/resolver_motivos_heredados.py."
    )

    print(f"{len(cambios)} fila(s) con motivo heredado:")
    for i, arch, antes, ahora in cambios:
        print(f"  fila {i:2}  {','.join(antes) or '(vacío)'} -> {','.join(ahora)}")
    if not args.dry_run:
        GT.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8", newline="\n")
        print(f"\nescrito {GT}")
        print("Ahora regenera el mapeo del corpus para que el cambio llegue a la prueba:")
        print("  python scripts/sembrar_prueba_falsedad.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
