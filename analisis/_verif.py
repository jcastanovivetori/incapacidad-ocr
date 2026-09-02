# -*- coding: utf-8 -*-
import json, csv, collections

# --- Rutas relativas (añadidas por scripts/exportar_analisis.py) --------------------------
# Este script se escribió con rutas ABSOLUTAS de la máquina donde se investigó. Se resuelven
# desde la ubicación del propio archivo para que funcione tras un `git pull` en cualquier
# equipo. El corpus (`dataset-falsedad/`) NO está en el repositorio: lo aporta el cliente.
import pathlib as _pl
_REPO = _pl.Path(__file__).resolve().parents[1]
_DATASET = _REPO.parent / "dataset-falsedad"
_EJEMPLOS = _REPO.parent / "Ejemplos"
# ------------------------------------------------------------------------------------------
norm = json.load(open(str(_DATASET / "requisitos_eps.json"), encoding="utf-8"))

# A) separacion perfecta env=1 -> max(archivo)==1 ; env=2 -> max>=2 (excluyendo todo-cero)
viol1 = viol2 = 0; todocero = collections.Counter()
for r in norm:
    arcs = [d["archivo"] for d in r["documentos"]]
    if not arcs: continue
    if max(arcs) == 0: todocero[r["tipo_envio"]] += 1; continue
    if r["tipo_envio"] == 1 and max(arcs) != 1: viol1 += 1
    if r["tipo_envio"] == 2 and max(arcs) < 2: viol2 += 1
print("A) violaciones env=1 con max(archivo)>1:", viol1)
print("A) violaciones env=2 con max(archivo)==1:", viol2)
print("A) combos con TODOS los archivo=0, por tipo_envio:", dict(todocero))
print("A) combos con MEZCLA de 0 y >0:",
      sum(1 for r in norm if r["documentos"] and 0 in [d["archivo"] for d in r["documentos"]]
          and max(d["archivo"] for d in r["documentos"]) > 0))

# B) 'archivo' monotono respecto a iddocumento? (si lo fuera seria un contador de orden)
mono = nomono = 0
for r in norm:
    ds = sorted(r["documentos"], key=lambda d: d["iddocumento"])
    a = [d["archivo"] for d in ds]
    if len(set(a)) < 2: continue
    (mono := mono + 1) if a == sorted(a) else (nomono := nomono + 1)
print("B) combos con archivo NO monotono vs iddocumento:", nomono, "| monotono:", mono)

# C) medioradicacion: ninguna EPS mezcla 1 y 2?
per = collections.defaultdict(set)
for r in norm:
    if r["medioradicacion"]: per[(r["idlpeps"], r["nombre_eps"])].add(r["medioradicacion"])
print("C) EPS que mezclan medio 1 y 2:", [k for k, v in per.items() if len(v) > 1])
print("C) EPS con medio=1:", sorted(k[1] for k, v in per.items() if v == {1}))
print("C) EPS con medio=2:", sorted(k[1] for k, v in per.items() if v == {2}))

# D) tipo_envio: se mezcla dentro de la misma EPS?
pe = collections.defaultdict(set)
for r in norm:
    if r["tipo_envio"]: pe[(r["idlpeps"], r["nombre_eps"])].add(r["tipo_envio"])
print("D) EPS que mezclan envio 1 y 2:", sorted(k[1] for k, v in pe.items() if len(v) > 1))

# E) medio=1 -> docs uno por archivo?
c = collections.Counter()
for r in norm:
    arcs = [d["archivo"] for d in r["documentos"] if d["archivo"]]
    if not arcs: continue
    c[(r["medioradicacion"], "1doc_x_archivo" if len(set(arcs)) == len(arcs) else "agrupa")] += 1
print("E)", dict(sorted(c.items())))

# F) filas sin checklist: que valor trae la columna?
raw = open("<descargas>/lpeps.csv", encoding="utf-8-sig").read().splitlines()
vals = collections.Counter(); nombres_sin = []
for ln in raw[1:]:
    if '{"ausentismos"' in ln: continue
    f = next(csv.reader([ln]))
    vals[(f[7], f[8], f[9])] += 1
    nombres_sin.append((f[0], f[1]))
print("F) (cheklistradicaciones, observaciones, codigoarl) en filas sin JSON:", dict(vals))
print("F) total EPS en catalogo:", len(raw) - 1)
print("F) ids sin checklist:", [n[0] for n in nombres_sin])

# G) huella exacta por EPS para el reporte (tipos configurados con docs)
for eps in sorted({(r["idlpeps"], r["nombre_eps"]) for r in norm}):
    conf = [(r["idlptipoausentismo"], r["tipo_envio"], r["medioradicacion"], len(r["documentos"]),
             max([d["archivo"] for d in r["documentos"]], default=0))
            for r in norm if r["idlpeps"] == eps[0]]
    print("G) eps=%-3s %-42s %s" % (eps[0], eps[1], sorted(conf)))
