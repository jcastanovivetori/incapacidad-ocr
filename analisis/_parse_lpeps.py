# -*- coding: utf-8 -*-
"""Parseo defensivo de lpeps.csv -> requisitos_eps.json (100% local, sin PII de salud)."""
import csv, io, json, re, sys, collections

# --- Rutas relativas (añadidas por scripts/exportar_analisis.py) --------------------------
# Este script se escribió con rutas ABSOLUTAS de la máquina donde se investigó. Se resuelven
# desde la ubicación del propio archivo para que funcione tras un `git pull` en cualquier
# equipo. El corpus (`dataset-falsedad/`) NO está en el repositorio: lo aporta el cliente.
import pathlib as _pl
_REPO = _pl.Path(__file__).resolve().parents[1]
_DATASET = _REPO.parent / "dataset-falsedad"
_EJEMPLOS = _REPO.parent / "Ejemplos"
# ------------------------------------------------------------------------------------------

CSV = "<descargas>/lpeps.csv"
raw = open(CSV, "r", encoding="utf-8-sig", newline="").read()
lineas = raw.splitlines()
print("lineas totales (incl. header):", len(lineas))
print("header:", lineas[0])

hdr = lineas[0].split(",")
print("n columnas header:", len(hdr))

ANCLA = '{"ausentismos"'
filas, errores, sin_json = [], [], []

for ln in lineas[1:]:
    if not ln.strip():
        continue
    i = ln.find(ANCLA)
    if i < 0:
        # sin checklist: parsear normalmente para obtener id/nombre/identificacion
        try:
            campos = next(csv.reader([ln]))
        except Exception as e:
            errores.append((ln[:60], "csv-reader: %s" % e)); continue
        sin_json.append(campos)
        continue
    cab = ln[:i]
    cola = ln[i:]
    # el JSON termina en el ultimo '}' de la linea (la cola es ...}"" ,I,I / ,algo,I)
    j = cola.rfind("}")
    if j < 0:
        errores.append((ln[:60], "sin cierre }")); continue
    js = cola[: j + 1]
    # desescapar comillas dobles duplicadas del CSV
    js_limpio = js.replace('""', '"')
    try:
        obj = json.loads(js_limpio)
    except Exception as e1:
        try:
            obj = json.loads(js)  # por si alguna linea no viniera duplicada
        except Exception as e2:
            errores.append((ln[:60], "json: %s / %s" % (e1, e2))); continue
    # cabecera: idlpeps,nombre,identificacion,codigo,idcpuc,idcpuc_gasto,idcpuc_costo,<json>
    # 'cab' termina con la coma antes de ""{  y puede traer ""  antes -> quitar
    cab_l = cab.rstrip()
    cab_l = re.sub(r'"*,?\s*$', "", cab_l)          # quita el ,"" residual
    pre = next(csv.reader([cab_l + ","]))            # coma final -> ultimo campo vacio
    pre = [p for p in pre]
    filas.append({"pre": pre, "json": obj, "cola": cola[j + 1 :]})

print("filas CON checklist JSON:", len(filas))
print("filas SIN checklist:", len(sin_json))
print("errores de parseo:", len(errores))
for e in errores: print("  ERROR:", e)

# ---- normalizacion
norm = []
colas = collections.Counter()
for f in filas:
    pre = f["pre"]
    idlpeps = int(pre[0]); nombre = pre[1]; ident = pre[2]
    colas[f["cola"]] += 1
    for a in f["json"]["ausentismos"]:
        norm.append({
            "idlpeps": idlpeps, "nombre_eps": nombre, "identificacion": ident,
            "idlptipoausentismo": a["idlptipoausentismo"],
            "tipo_envio": a["tipo_envio"], "medioradicacion": a["medioradicacion"],
            "documentos": [
                {"iddocumento": d["iddocumento"], "nombredocumento": d["nombredocumento"],
                 "archivo": d["archivo"]} for d in a.get("documentos", [])
            ],
        })

print("combinaciones (eps x tipo):", len(norm))
print("colas observadas:", dict(colas))
print("claves de ausentismo vistas:",
      sorted({k for f in filas for a in f["json"]["ausentismos"] for k in a}))
print("claves de documento vistas:",
      sorted({k for f in filas for a in f["json"]["ausentismos"] for d in a.get("documentos", []) for k in d}))
print("claves top-level:", sorted({k for f in filas for k in f["json"]}))

json.dump(norm, open(str(_DATASET / "requisitos_eps.json"), "w", encoding="utf-8"),
          ensure_ascii=False, indent=2)

# ---- distribuciones
tipos = collections.Counter(r["idlptipoausentismo"] for r in norm)
env = collections.Counter(r["tipo_envio"] for r in norm)
med = collections.Counter(r["medioradicacion"] for r in norm)
arch = collections.Counter(d["archivo"] for r in norm for d in r["documentos"])
docs = collections.Counter(d["nombredocumento"] for r in norm for d in r["documentos"])
iddoc = collections.Counter((d["iddocumento"], d["nombredocumento"]) for r in norm for d in r["documentos"])
ndocs = collections.Counter(len(r["documentos"]) for r in norm)

print("\n-- tipos ausentismo:", sorted(tipos.items()))
print("-- tipo_envio:", sorted(env.items()))
print("-- medioradicacion:", sorted(med.items()))
print("-- archivo:", sorted(arch.items()))
print("-- n documentos por combinacion:", sorted(ndocs.items()))
print("-- iddocumento<->nombre:", sorted(iddoc.items()))
print("-- documentos distintos (%d):" % len(docs))
for k, v in docs.most_common(): print("    %4d  %s" % (v, k))

# cross-tabs para deducir semantica
print("\n-- cruce tipo_envio x medioradicacion:")
ct = collections.Counter((r["tipo_envio"], r["medioradicacion"]) for r in norm)
for k, v in sorted(ct.items()): print("   env=%s med=%s -> %d" % (k[0], k[1], v))
print("-- cruce tipo_envio x (tiene documentos?):")
ct2 = collections.Counter((r["tipo_envio"], bool(r["documentos"])) for r in norm)
for k, v in sorted(ct2.items()): print("   env=%s docs=%s -> %d" % (k[0], k[1], v))
print("-- cruce medioradicacion x (tiene documentos?):")
ct3 = collections.Counter((r["medioradicacion"], bool(r["documentos"])) for r in norm)
for k, v in sorted(ct3.items()): print("   med=%s docs=%s -> %d" % (k[0], k[1], v))
print("-- combinaciones con 0 documentos por tipo:")
ct4 = collections.Counter((r["idlptipoausentismo"], bool(r["documentos"])) for r in norm)
for k, v in sorted(ct4.items()): print("   tipo=%s docs=%s -> %d" % (k[0], k[1], v))

print("\n-- archivo x nombredocumento (top):")
ct5 = collections.Counter((d["nombredocumento"], d["archivo"]) for r in norm for d in r["documentos"])
for k, v in sorted(ct5.items()): print("   %-45s archivo=%s -> %d" % (k[0], k[1], v))

print("\n-- archivo x tipo_envio:")
ct6 = collections.Counter((r["tipo_envio"], d["archivo"]) for r in norm for d in r["documentos"])
for k, v in sorted(ct6.items()): print("   env=%s archivo=%s -> %d" % (k[0], k[1], v))
print("-- archivo x medioradicacion:")
ct7 = collections.Counter((r["medioradicacion"], d["archivo"]) for r in norm for d in r["documentos"])
for k, v in sorted(ct7.items()): print("   med=%s archivo=%s -> %d" % (k[0], k[1], v))
print("-- archivo: valores por EPS (cuantas EPS usan cada valor):")
ct8 = collections.defaultdict(set)
for r in norm:
    for d in r["documentos"]:
        ct8[d["archivo"]].add(r["idlpeps"])
for k in sorted(ct8): print("   archivo=%s -> %d EPS" % (k, len(ct8[k])))
print("-- por EPS: set de valores 'archivo' usados:")
ct9 = collections.defaultdict(set)
for r in norm:
    for d in r["documentos"]:
        ct9[(r["idlpeps"], r["nombre_eps"])].add(d["archivo"])
for k in sorted(ct9): print("   eps=%s %-30s -> %s" % (k[0], k[1], sorted(ct9[k])))
