"""Agrega la medicion de medir.py: tabla por documento + metricas.

Definiciones que se usan (explicitas, porque el motor actual no tiene un veredicto
temporal propio y hay que decir con que se cuenta):

  MARCA_TEMPORAL_INCOHERENCIA : el motor dice que los tiempos NO cuadran.
  MARCA_TEMPORAL_FALTA_DATO   : el motor dice que no leyo inicio/dias (o dias fuera de rango).
  REQUIERE_REVISION           : bandera global de mapear_a_staging (mezcla cedula/CIE-10/EPS/docs).
  REF                         : chequeo de referencia independiente sobre los valores CRUDOS
                                (antes de normalizar_fechas), segun las invariantes de CLAUDE.md.
"""
from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path

SALIDA = Path(__file__).parent
D = json.loads((SALIDA / "resultados.json").read_text(encoding="utf-8"))

TEMPORAL_ES_INCOHERENCIA = ("Número de días fuera de rango",)
TEMPORAL_ES_FALTA = ("No se detectó la fecha de inicio", "No se detectó el número de días")


def clasifica(temporales):
    inc = [p for p in temporales if any(p.startswith(t) for t in TEMPORAL_ES_INCOHERENCIA)]
    falta = [p for p in temporales if any(p.startswith(t) for t in TEMPORAL_ES_FALTA)]
    return inc, falta


filas = D["filas"]
tabla = []
for f in filas:
    rc = f.get("recalc") or {}
    inc, falta = clasifica(rc.get("problemas_temporales") or [])
    ref_est, ref_det = f.get("ref_crudo") or ["?", ""]
    crudo = f.get("recalc_crudo") or {}
    leidos = sum(1 for k in ("fecha_inicio", "fecha_fin", "dias") if crudo.get(k) is not None)
    norm = f.get("recalc_normalizado") or {}
    tabla.append({
        "archivo": f["archivo"],
        "etiqueta": f["etiqueta"],
        "cuarentena": f["cuarentena"],
        "senales_gt": f["senales_gt"],
        "temporal_gt": "FECHAS_INCOHERENTES" in (f["senales_gt"] or []),
        "datos_leidos": f"{leidos}/3",
        "crudo": crudo,
        "normalizado": norm,
        "fin_reescrito": crudo.get("fecha_fin") is not None
                         and crudo.get("fecha_fin") != norm.get("fecha_fin"),
        "inicio_descartado": crudo.get("fecha_inicio") is not None
                             and norm.get("fecha_inicio") is None,
        "ref": ref_est,
        "ref_detalle": ref_det,
        "marca_incoherencia": bool(inc),
        "marca_falta_dato": bool(falta),
        "requiere_revision": rc.get("requiere_revision"),
        "fila_Numerodias": rc.get("Numerodias"),
        "fila_fechainicio": rc.get("fechainicio"),
        "fila_fechavencimiento": rc.get("fechavencimiento"),
        "excepcion": rc.get("excepcion") or f.get("recalc_excepcion"),
    })

ev = [t for t in tabla if t["cuarentena"] != "si"]
cuar = [t for t in tabla if t["cuarentena"] == "si"]
fal = [t for t in ev if t["etiqueta"] == "falsa"]
rea = [t for t in ev if t["etiqueta"] == "real"]
temp = [t for t in fal if t["temporal_gt"]]
otras = [t for t in fal if not t["temporal_gt"]]

# Invariante fechavencimiento = fechainicio + Numerodias (NO inclusivo)
malas_venc = []
for t in tabla:
    fi, nd, fv = t["fila_fechainicio"], t["fila_Numerodias"], t["fila_fechavencimiento"]
    if fi and isinstance(nd, int) and 1 <= nd <= 540:
        esp = (date.fromisoformat(fi) + timedelta(days=nd)).isoformat()
        if fv != esp:
            malas_venc.append((t["archivo"], fi, nd, fv, esp))
    elif fv is not None and not (fi and isinstance(nd, int)):
        malas_venc.append((t["archivo"], fi, nd, fv, "None esperado"))

print("### UNIVERSO")
print(f"manifest.csv                          : {len(tabla)}")
print(f"EXCLUIDOS por cuarentena              : {len(cuar)}  -> {[t['archivo'] for t in cuar]}")
print(f"evaluados                             : {len(ev)}  ({len(fal)} falsas / {len(rea)} reales)")
print()
print("### DISPONIBILIDAD DE DATOS TEMPORALES (lector actual, valores crudos)")
for grupo, nom in ((fal, "falsas"), (rea, "reales")):
    tri = sum(1 for t in grupo if t["datos_leidos"] == "3/3")
    par = sum(1 for t in grupo if t["datos_leidos"] == "2/3")
    no = sum(1 for t in grupo if t["ref"] == "NO_EVALUABLE")
    print(f"{nom:7s} n={len(grupo):2d} | tripleta 3/3={tri} | par 2/3={par} | NO EVALUABLE={no}")
print(f"NO EVALUABLES totales                 : {sum(1 for t in ev if t['ref']=='NO_EVALUABLE')}/{len(ev)}")
print()
print("### MARCAS DEL MOTOR")
print(f"marca INCOHERENCIA temporal (falsas)  : {sum(1 for t in fal if t['marca_incoherencia'])}/{len(fal)}")
print(f"marca INCOHERENCIA temporal (reales)  : {sum(1 for t in rea if t['marca_incoherencia'])}/{len(rea)}  <- falsos positivos")
print(f"marca FALTA DATO temporal   (falsas)  : {sum(1 for t in fal if t['marca_falta_dato'])}/{len(fal)}")
print(f"marca FALTA DATO temporal   (reales)  : {sum(1 for t in rea if t['marca_falta_dato'])}/{len(rea)}")
print(f"requiere_revision           (falsas)  : {sum(1 for t in fal if t['requiere_revision'])}/{len(fal)}")
print(f"requiere_revision           (reales)  : {sum(1 for t in rea if t['requiere_revision'])}/{len(rea)}")
print()
print("### METRICA QUE IMPORTA: falsas con motivo TEMPORAL declarado")
print(f"universo                              : {len(temp)}  -> {[t['archivo'] for t in temp]}")
print(f"detectadas como incoherencia temporal : {sum(1 for t in temp if t['marca_incoherencia'])}/{len(temp)}")
print(f"marcadas solo por 'no lei el dato'    : {sum(1 for t in temp if t['marca_falta_dato'])}/{len(temp)}")
print(f"falsas por OTROS motivos (fuera de alcance de este motor): {len(otras)}")
from collections import Counter
print("  desglose:", dict(Counter(s for t in otras for s in (t['senales_gt'] or ['-']))))
print()
print("### INCOHERENCIAS REALES QUE EL MOTOR NO DIJO (ref=INCOHERENTE y sin marca)")
for t in tabla:
    if t["ref"] == "INCOHERENTE" and not t["marca_incoherencia"]:
        print(f"  [{t['cuarentena']=='si' and 'CUAR' or 'eval'}] {t['archivo']}: {t['ref_detalle']}")
print()
print("### EVIDENCIA DESTRUIDA POR normalizar_fechas()")
for t in tabla:
    if t["fin_reescrito"] or t["inicio_descartado"]:
        print(f"  {t['archivo']}: crudo={t['crudo']} -> norm={t['normalizado']} "
              f"(fin_reescrito={t['fin_reescrito']}, inicio_descartado={t['inicio_descartado']})")
print()
print("### ROBUSTEZ")
print("excepciones del motor                 :", [t["archivo"] for t in tabla if t["excepcion"]] or "ninguna")
print("violaciones de fechavencimiento=inicio+dias:", malas_venc or "ninguna")
print()
print("### TABLA POR DOCUMENTO")
hdr = f"{'archivo':<50} {'et':<5} {'cuar':<4} {'gt':<22} {'lee':<4} {'ref':<12} {'inc':<4} {'falta':<5} {'rev':<4} {'dias':<5} venc"
print(hdr); print("-" * len(hdr))
for t in tabla:
    print(f"{t['archivo'][:50]:<50} {t['etiqueta']:<5} {t['cuarentena']:<4} "
          f"{(','.join(t['senales_gt']) or '-')[:22]:<22} {t['datos_leidos']:<4} {t['ref']:<12} "
          f"{'SI' if t['marca_incoherencia'] else 'no':<4} {'SI' if t['marca_falta_dato'] else 'no':<5} "
          f"{'SI' if t['requiere_revision'] else 'no':<4} {str(t['fila_Numerodias']):<5} {t['fila_fechavencimiento']}")

(SALIDA / "tabla.json").write_text(json.dumps(tabla, ensure_ascii=False, indent=1), encoding="utf-8")
