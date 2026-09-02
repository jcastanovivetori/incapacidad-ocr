# -*- coding: utf-8 -*-
"""Arma el corpus organizado (docs/falsas, docs/reales) y su manifest.csv.

Copia (no mueve) los documentos desde Descargas, calcula sha256, cuenta paginas
de los PDF con pypdfium2 y marca la cuarentena de los conflictos de etiqueta.
NO imprime contenido de los documentos (solo nombres, hashes y metricas).
"""
import csv
import hashlib
import json
import shutil
import sys
from pathlib import Path

# --- Rutas relativas (añadidas por scripts/exportar_analisis.py) --------------------------
# Este script se escribió con rutas ABSOLUTAS de la máquina donde se investigó. Se resuelven
# desde la ubicación del propio archivo para que funcione tras un `git pull` en cualquier
# equipo. El corpus (`dataset-falsedad/`) NO está en el repositorio: lo aporta el cliente.
import pathlib as _pl
_REPO = _pl.Path(__file__).resolve().parents[1]
_DATASET = _REPO.parent / "dataset-falsedad"
_EJEMPLOS = _REPO.parent / "Ejemplos"
# ------------------------------------------------------------------------------------------

SRC_FALSAS = Path("<descargas>/Falsas")
SRC_REALES = Path("<descargas>/Reales")
DEST = Path(str(_DATASET))
EXPLICACION = "Explicacion de archivos.jpeg"

IMG_EXT = {".jpeg", ".jpg", ".png", ".tif", ".tiff", ".bmp", ".webp"}

# Conflictos de etiqueta conocidos -> motivo de cuarentena
CUARENTENA = {
    ("falsa", "FALSA-03.pdf"):
        "mismo sha256 en ambas clases (pareja: Reales/REAL-15.pdf)",
    ("real", "REAL-15.pdf"):
        "mismo sha256 en ambas clases (pareja: Falsas/FALSA-03.pdf); "
        "ademas misma cedula que Falsas/FALSA-15.pdf con contenido distinto",
    ("falsa", "FALSA-11.pdf"):
        "mismo sha256 en ambas clases (pareja: Reales/REAL-01.pdf)",
    ("real", "REAL-01.pdf"):
        "mismo sha256 en ambas clases (pareja: Falsas/FALSA-11.pdf)",
    ("falsa", "FALSA-15.pdf"):
        "misma cedula, contenido distinto (pareja: Reales/REAL-15.pdf)",
}


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def paginas(path):
    if path.suffix.lower() != ".pdf":
        return ""
    try:
        import pypdfium2 as pdfium
        doc = pdfium.PdfDocument(str(path))
        try:
            return str(len(doc))
        finally:
            doc.close()
    except Exception as exc:  # no abortar el manifest por un PDF roto
        return "ERROR:%s" % type(exc).__name__


def listar(src):
    out = []
    for p in sorted(src.iterdir()):
        if not p.is_file():
            continue
        if p.name == EXPLICACION:
            continue
        out.append(p)
    return out


def main():
    notas = []
    rows = []
    verif = {"copiados": 0, "hash_ok": 0, "hash_mismatch": [], "bytes_mismatch": []}

    for etiqueta, src in (("falsa", SRC_FALSAS), ("real", SRC_REALES)):
        destdir = DEST / "docs" / ("falsas" if etiqueta == "falsa" else "reales")
        archivos = listar(src)
        for p in archivos:
            dst = destdir / p.name
            shutil.copy2(str(p), str(dst))
            verif["copiados"] += 1
            h_src = sha256(p)
            h_dst = sha256(dst)
            if h_src == h_dst:
                verif["hash_ok"] += 1
            else:
                verif["hash_mismatch"].append(p.name)
            if p.stat().st_size != dst.stat().st_size:
                verif["bytes_mismatch"].append(p.name)
            motivo = CUARENTENA.get((etiqueta, p.name), "")
            rows.append({
                "archivo": p.name,
                "etiqueta": etiqueta,
                "sha256": h_dst,
                "bytes": str(dst.stat().st_size),
                "ext": p.suffix.lower().lstrip("."),
                "paginas": paginas(dst),
                "ruta_original": str(p).replace("\\", "/"),
                "cuarentena": "si" if motivo else "no",
                "motivo_cuarentena": motivo,
            })

    # Copiar la tabla de motivos a la raiz del dataset (no a docs/)
    src_exp = SRC_FALSAS / EXPLICACION
    if src_exp.is_file():
        shutil.copy2(str(src_exp), str(DEST / EXPLICACION))

    campos = ["archivo", "etiqueta", "sha256", "bytes", "ext", "paginas",
              "ruta_original", "cuarentena", "motivo_cuarentena"]
    with open(DEST / "manifest.csv", "w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=campos)
        w.writeheader()
        w.writerows(rows)

    # --- verificaciones ---
    n_falsas_src = len(listar(SRC_FALSAS))
    n_reales_src = len(listar(SRC_REALES))
    n_falsas_dst = len(list((DEST / "docs" / "falsas").iterdir()))
    n_reales_dst = len(list((DEST / "docs" / "reales").iterdir()))

    if n_falsas_src != n_falsas_dst:
        notas.append("MISMATCH falsas: origen %d vs destino %d" % (n_falsas_src, n_falsas_dst))
    if n_reales_src != n_reales_dst:
        notas.append("MISMATCH reales: origen %d vs destino %d" % (n_reales_src, n_reales_dst))
    if verif["hash_mismatch"]:
        notas.append("sha256 distinto tras copiar: %s" % verif["hash_mismatch"])
    if verif["bytes_mismatch"]:
        notas.append("tamano distinto tras copiar: %s" % verif["bytes_mismatch"])

    # duplicados de sha256 (intra e inter clase) detectados de forma independiente
    porhash = {}
    for r in rows:
        porhash.setdefault(r["sha256"], []).append((r["etiqueta"], r["archivo"]))
    dups = {h: v for h, v in porhash.items() if len(v) > 1}

    resumen = {
        "falsas_origen": n_falsas_src, "falsas_destino": n_falsas_dst,
        "reales_origen": n_reales_src, "reales_destino": n_reales_dst,
        "copiados": verif["copiados"], "hash_ok": verif["hash_ok"],
        "cuarentena": [(r["etiqueta"], r["archivo"]) for r in rows if r["cuarentena"] == "si"],
        "sha256_duplicados": {h[:12]: v for h, v in dups.items()},
        "paginas_error": [r["archivo"] for r in rows if str(r["paginas"]).startswith("ERROR")],
        "paginas_total_pdf": sum(int(r["paginas"]) for r in rows
                                 if r["paginas"].isdigit()),
        "ext_conteo": {},
        "notas": notas,
    }
    for r in rows:
        resumen["ext_conteo"][r["ext"]] = resumen["ext_conteo"].get(r["ext"], 0) + 1

    print(json.dumps(resumen, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
