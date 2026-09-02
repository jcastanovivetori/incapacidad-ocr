"""¿Cuánta de la ceguera del motor es recuperable en el extractor?

De los documentos en los que `T01_DURACION_VS_RANGO` queda NO EVALUABLE (le falta el inicio
o el fin LEIDO), cuenta cuántos tienen **en el texto OCR** una fecha que el extractor no
publica. Es la diferencia entre "el papel no lo dice" (nada que hacer) y "el papel lo dice y
no lo leemos" (recuperable sin tocar el motor).

Deliberadamente TOLERANTE al ruido del OCR: los tokens salen pegados a la palabra anterior
("...A PARTIR DE18/05/2026HASTA18/05/2026", "MARTES09DE JUNIO"), asi que NO se usa `\\b`.
Se descartan los años < 2020 (fechas de nacimiento) y los tokens de mas de 4 cifras de año.

No es un extractor: solo cuenta evidencia disponible. No decide nada.

Uso:
    <repo>/.venv/Scripts/python.exe cobertura_lectura.py
"""
from __future__ import annotations

import csv
import json
import re
import sys
from pathlib import Path

# --- Rutas relativas (añadidas por scripts/exportar_analisis.py) --------------------------
# Este script se escribió con rutas ABSOLUTAS de la máquina donde se investigó. Se resuelven
# desde la ubicación del propio archivo para que funcione tras un `git pull` en cualquier
# equipo. El corpus (`dataset-falsedad/`) NO está en el repositorio: lo aporta el cliente.
import pathlib as _pl
_REPO = _pl.Path(__file__).resolve().parents[3]
_DATASET = _REPO.parent / "dataset-falsedad"
_EJEMPLOS = _REPO.parent / "Ejemplos"
# ------------------------------------------------------------------------------------------

BASE = Path(str(_DATASET))
AQUI = Path(__file__).resolve().parent
CARPETAS = ("falsas", "falsa", "reales", "real")

# dd/mm/aaaa | dd-mm-aa | dd.mm.aaaa, sin exigir frontera de palabra (el OCR pega el token)
NUM = re.compile(r"(?<![\d])(\d{1,2})[/.\-](\d{1,2})[/.\-](\d{2,4})(?![\d])")
MES = (r"(ENERO|FEBRERO|MARZO|ABRIL|MAYO|JUNIO|JULIO|AGOSTO|SEPT?[I1]?E?MBRE|"
       r"OCTUBRE|NOVIEMBRE|DICIEMBRE)")
# "02 DE SEPTIEMBRE", "MARTES09DE JUNIO", "09 DE/JUNIO"  (el OCR mete '/' y quita espacios)
PALABRA = re.compile(r"(\d{1,2})\s*/?\s*DE\s*/?\s*" + MES, re.I)
ROTULOS = re.compile(r"(?i)(hasta|a\s*partir\s*de|desde|fecha\s*fin|fechafin|fecha\s*inicio|"
                     r"fecha\s*lnicio|inicia|duraci[o0][nm]|d[i1íl]as?\s*de\s*incapacidad)")


def json_de(archivo: str) -> Path | None:
    for c in CARPETAS:
        p = BASE / "ocr" / c / f"{Path(archivo).stem}.json"
        if p.is_file():
            return p
    return None


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        pass
    med = json.loads((AQUI / "resultados_motor.json").read_text(encoding="utf-8"))
    with (BASE / "manifest.csv").open(encoding="utf-8", newline="") as fh:
        man = {f["archivo"]: f for f in csv.DictReader(fh)}

    filas, recuperables, sin_nada = [], [], []
    for f in med["documentos"]:
        if f["cuarentena"] or "T01_DURACION_VS_RANGO" not in f["B_pipeline"]["no_evaluables"]:
            continue
        texto = json.loads(json_de(f["archivo"]).read_text(encoding="utf-8"))["texto_plano"]
        num = [f"{d}/{m}/{a}" for d, m, a in NUM.findall(texto)
               if 2020 <= (int(a) + 2000 if len(a) == 2 else int(a)) <= 2100]
        pal = ["".join(x) for x in PALABRA.findall(texto)]
        rot = sorted({r.lower() for r in ROTULOS.findall(texto)})
        fila = {"id": f["id"], "etiqueta": f["etiqueta"], "sha8": f["sha8"],
                "leido": {k: f["B_pipeline"]["leido"][k] for k in ("fecha_inicio", "fecha_fin", "dias")},
                "faltan": f["B_pipeline"]["no_evaluables"]["T01_DURACION_VS_RANGO"],
                "fechas_num_en_texto": num, "fechas_palabra_en_texto": pal, "rotulos": rot}
        filas.append(fila)
        (recuperables if (num or pal) else sin_nada).append(f["id"])

    (AQUI / "cobertura_lectura.json").write_text(
        json.dumps({"documentos": filas, "recuperables": recuperables, "sin_fecha_en_texto": sin_nada},
                   ensure_ascii=False, indent=1), encoding="utf-8")

    print(f"documentos evaluables donde T01 NO puede opinar: {len(filas)}")
    for x in filas:
        print(f"  {x['id']} ({x['etiqueta'][:1]}) leido={x['leido']['fecha_inicio']}→"
              f"{x['leido']['fecha_fin']}/{x['leido']['dias']}  "
              f"num={x['fechas_num_en_texto']} palabra={x['fechas_palabra_en_texto']}")
    print(f"\nCON fecha en el texto OCR que el extractor no publica (recuperable): "
          f"{len(recuperables)} {recuperables}")
    print(f"SIN ninguna fecha aprovechable en el texto: {len(sin_nada)} {sin_nada}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
