"""Mide la detección de documentos adulterados cruzando la BD contra el ground truth.

Existe porque derivar esta cifra a mano sale mal. Dos trampas, y se cayó en las dos:

  1. **Hay DOS canales de señal.** `sospecha_manipulacion` (catálogo de diagnósticos, coherencia
     de la fuente) y `alertas_tiempos` (motor de reglas temporales, `reglas_tiempo.py`). Contar
     solo el primero da **3 de 9** en vez de 4 y parece una regresión que no existe: el caso del
     desfase de 30 días entre los días declarados y el rango de fechas dispara **solo** por el
     canal de tiempos.
  2. **Se cuenta por CASO, no por documento.** La llave del trámite es la cédula, así que 31
     documentos son 27 casos. Y los casos en **cuarentena** (etiqueta en disputa: el mismo
     archivo entregado como falso y como legítimo) no cuentan ni a favor ni en contra — decir
     «0 falsos positivos sobre los 16 legítimos» sobrestima, porque 2 de esos 16 documentos
     viven en casos en cuarentena que sí se marcan.

Necesita el corpus sembrado (`MAPEO.csv`) y la BD con el lote ya procesado.

    python scripts/medir_deteccion.py
"""
from __future__ import annotations

import csv
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

MAPEO = REPO / "ingesta" / "_sistema" / "semilla" / "MAPEO.csv"

CONSULTA = (
    "SELECT archivo_origen, sospecha_manipulacion, "
    "IF(alertas_tiempos IS NULL OR alertas_tiempos='','0','1') FROM lp_ausentismos_ia;"
)


def _señales_de_la_bd() -> dict[str, list[str]]:
    """archivo_origen -> canales que dispararon. Vía cliente `mysql` (basta Docker)."""
    import shutil

    from incapacidad_ocr import db

    cfg = db.db_config()
    intentos = []
    if shutil.which("mysql"):
        intentos.append(["mysql", f"-h{cfg['host']}", f"-P{cfg['port']}", f"-u{cfg['user']}",
                         f"-p{cfg['password']}", "-N", "-B", "-e", CONSULTA, cfg["database"]])
    if shutil.which("docker"):
        intentos.append(["docker", "exec", "-i", "ocr-db", "mysql", f"-u{cfg['user']}",
                         f"-p{cfg['password']}", "-N", "-B", "-e", CONSULTA, cfg["database"]])
    for cmd in intentos:
        try:
            r = subprocess.run(cmd, capture_output=True, timeout=60)
        except Exception:  # noqa: BLE001
            continue
        if r.returncode != 0:
            continue
        out: dict[str, list[str]] = {}
        for linea in r.stdout.decode("utf-8", "replace").splitlines():
            p = linea.split("\t")
            if len(p) < 3:
                continue
            canales = []
            if p[1] == "1":
                canales.append("manipulacion")
            if p[2] == "1":
                canales.append("tiempos")
            if canales:
                out[p[0]] = canales
        return out
    raise SystemExit("No se pudo consultar la BD (¿está arriba? ¿hay cliente mysql o docker?).")


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        pass
    if not MAPEO.is_file():
        raise SystemExit(f"Falta {MAPEO}. Corre antes: python scripts/sembrar_prueba_falsedad.py")

    filas = list(csv.DictReader(MAPEO.open(encoding="utf-8")))
    señales = _señales_de_la_bd()

    etiquetas: dict[str, set[str]] = defaultdict(set)
    cuarentena: dict[str, bool] = defaultdict(bool)
    archivos: dict[str, list[str]] = defaultdict(list)
    for f in filas:
        ced = f["cedula"]
        etiquetas[ced].add(f["etiqueta"])
        if f["cuarentena"] == "si":
            cuarentena[ced] = True
        archivos[ced].append(f["archivo_semilla"])

    def clase(ced: str) -> str:
        if cuarentena[ced]:
            return "cuarentena"
        e = etiquetas[ced]
        if e == {"falsa"}:
            return "adulterada"
        if e == {"real"}:
            return "legitima"
        return "mixta"

    marcado = {c: any(a in señales for a in archivos[c]) for c in archivos}
    grupos: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    for c in archivos:
        k = clase(c)
        grupos[k][0] += 1
        if marcado[c]:
            grupos[k][1] += 1

    if not señales:
        print("La BD no tiene ninguna señal registrada. ¿Se corrió el lote?"
              " (POST /api/lote/procesar o «⚙ Procesar todos»)\n")

    print(f"{len(archivos)} casos ({len(filas)} documentos) · con señal: {sum(marcado.values())}\n")
    for k in ("adulterada", "legitima", "cuarentena", "mixta"):
        if k in grupos:
            tot, m = grupos[k][0], grupos[k][1]
            nota = "  <- FALSOS POSITIVOS" if k == "legitima" and m else ""
            print(f"  {k:11}: {m} de {tot} marcados{nota}")

    adult = grupos["adulterada"]
    legit = grupos["legitima"]
    print(f"\nDETECCIÓN: {adult[1]} de {adult[0]} casos adulterados")
    print(f"FALSOS POSITIVOS: {legit[1]} de {legit[0]} casos legítimos")
    print("Los casos en cuarentena no cuentan: su etiqueta está en disputa.")

    print("\nAdulterados DETECTADOS, y por qué canal:")
    for c in sorted(archivos):
        if clase(c) == "adulterada" and marcado[c]:
            canales = sorted({x for a in archivos[c] for x in señales.get(a, [])})
            print(f"  caso {c}: {'+'.join(canales)}")
    sin = [c for c in sorted(archivos) if clase(c) == "adulterada" and not marcado[c]]
    print(f"\nAdulterados SIN detectar ({len(sin)}): {', '.join(sin) or '(ninguno)'}")
    if legit[1]:
        print("\nATENCIÓN: hay falsos positivos. La regla del proyecto es bajar la severidad o "
              "exigir más evidencia, NO mover el umbral hasta que acierte en el corpus.")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
