# -*- coding: utf-8 -*-
import json, collections

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

print("== 1) por combinacion: (tipo_envio, medio, n_docs, archivos ordenados, set==1..max?)")
pat = collections.Counter()
for r in norm:
    arcs = sorted(d["archivo"] for d in r["documentos"])
    nz = sorted({a for a in arcs if a})
    contig = (nz == list(range(1, len(nz) + 1))) if nz else None
    todos_distintos = len(set(arcs)) == len(arcs) if arcs else None
    pat[(r["tipo_envio"], r["medioradicacion"], len(arcs), tuple(arcs), contig, todos_distintos)] += 1
for k, v in sorted(pat.items(), key=lambda x: (x[0][0], x[0][1], x[0][2])):
    print("   env=%s med=%s n=%d arch=%s contiguo=%s todos_distintos=%s  x%d" % (k[0], k[1], k[2], k[3], k[4], k[5], v))

print("\n== 2) max(archivo) vs n_docs cuando env=2 y hay docs")
c = collections.Counter()
for r in norm:
    if r["tipo_envio"] == 2 and r["documentos"]:
        arcs = [d["archivo"] for d in r["documentos"]]
        c[(len(arcs), max(arcs), len(set(arcs)))] += 1
for k, v in sorted(c.items()): print("   n_docs=%d max_arch=%d distintos=%d -> %d" % (k[0], k[1], k[2], v))

print("\n== 3) tipo_envio / medioradicacion son constantes por EPS?")
per = collections.defaultdict(lambda: (set(), set()))
for r in norm:
    per[(r["idlpeps"], r["nombre_eps"])][0].add(r["tipo_envio"])
    per[(r["idlpeps"], r["nombre_eps"])][1].add(r["medioradicacion"])
for k in sorted(per):
    print("   eps=%-3s %-42s env=%s med=%s" % (k[0], k[1], sorted(per[k][0]), sorted(per[k][1])))

print("\n== 4) tipo_envio / medioradicacion por TIPO de ausentismo (a traves de EPS)")
pt = collections.defaultdict(collections.Counter)
for r in norm: pt[r["idlptipoausentismo"]][(r["tipo_envio"], r["medioradicacion"])] += 1
for t in sorted(pt): print("   tipo=%-3s %s" % (t, dict(sorted(pt[t].items()))))

print("\n== 5) misma EPS: se repite el mismo 'archivo' entre docs? (agrupacion)")
g = collections.Counter()
for r in norm:
    arcs = [d["archivo"] for d in r["documentos"] if d["archivo"]]
    if not arcs: continue
    grupos = collections.Counter(arcs)
    g["combos_con_agrupacion(>=1 archivo con 2+ docs)" if any(v > 1 for v in grupos.values())
      else "combos_1doc_por_archivo"] += 1
print("  ", dict(g))

print("\n== 6) que docs comparten el mismo 'archivo' (pares mas frecuentes)")
pares = collections.Counter()
for r in norm:
    porarch = collections.defaultdict(list)
    for d in r["documentos"]:
        if d["archivo"]: porarch[d["archivo"]].append(d["nombredocumento"])
    for a, ds in porarch.items():
        if len(ds) > 1: pares[tuple(sorted(ds))] += 1
for k, v in pares.most_common(15): print("   %d  %s" % (v, " + ".join(k)))

print("\n== 7) requisitos por tipo: frecuencia de cada documento (sobre EPS que SI configuran ese tipo)")
tot = collections.Counter(); doc = collections.defaultdict(collections.Counter)
for r in norm:
    if r["documentos"]:
        tot[r["idlptipoausentismo"]] += 1
        for d in r["documentos"]: doc[r["idlptipoausentismo"]][d["nombredocumento"]] += 1
for t in sorted(doc):
    print("   tipo=%s (n=%d EPS con docs)" % (t, tot[t]))
    for k, v in doc[t].most_common(): print("        %2d/%2d  %s" % (v, tot[t], k))

print("\n== 8) EPS con checklist pero SIN ningun documento en ningun tipo")
z = collections.defaultdict(int)
for r in norm: z[(r["idlpeps"], r["nombre_eps"])] += len(r["documentos"])
print("  ", [k for k in sorted(z) if z[k] == 0])
print("\n== 9) EPS x tipos presentes en el JSON (siempre los mismos 7?)")
tp = collections.defaultdict(set)
for r in norm: tp[r["idlpeps"]].add(r["idlptipoausentismo"])
print("  ", collections.Counter(tuple(sorted(v)) for v in tp.values()))
