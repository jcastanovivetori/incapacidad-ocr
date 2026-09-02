"""ATAQUE 3 — LA propiedad clave: ninguna regla puede juzgar un valor CALCULADO.

Se recorre el camino REAL de produccion (foto de `processor` -> `normalizar_fechas` ->
`erp.mapear_a_staging`) y despues el camino de la REVISION HUMANA (el formulario de la UI
devuelve los mismos valores que se le pintaron: `static/index.html:518`).
"""
from __future__ import annotations

from datetime import date

from _comun import (HOY, LookupsFalsos, cierre, ctx_sin_foto, disparadas, estado, estados, ok,
                    resultado_process, rt, titulo)
from incapacidad_ocr.extract import normalizar_fechas

# --------------------------------------------------------------------------- #
titulo("A. Camino de produccion: foto + normalizar_fechas (reconciliacion real)")
# --------------------------------------------------------------------------- #
CASOS = [
    # (nombre, lo que LEYO el extractor)  -> se reconcilia de verdad con normalizar_fechas
    ("inicio derivado (fin + dias)", {"fecha_inicio": None, "fecha_fin": "2029-01-10", "dias": 5}),
    ("inicio derivado, fin muy antiguo", {"fecha_inicio": None, "fecha_fin": "2023-01-10", "dias": 5}),
    ("fin derivado (inicio + dias)", {"fecha_inicio": "2026-06-01", "fecha_fin": None, "dias": 5}),
    ("dias derivado (inicio + fin)", {"fecha_inicio": "2026-06-01", "fecha_fin": "2026-06-05",
                                      "dias": None}),
    ("fin reescrito (no cuadraba)", {"fecha_inicio": "2026-06-01", "fecha_fin": "2026-06-20",
                                     "dias": 5}),
    ("inicio derivado en el futuro", {"fecha_inicio": None, "fecha_fin": "2027-01-10", "dias": 5}),
    ("todo vacio", {"fecha_inicio": None, "fecha_fin": None, "dias": None}),
]
for nombre, leido in CASOS:
    rec = {"tipo_documento": "incapacidad", "incapacidad": dict(leido)}
    inca = rec["incapacidad"]
    inca[rt.CLAVE_SNAPSHOT] = rt.snapshot_leidos(inca)      # lo que hace processor.run()
    normalizar_fechas(rec)                                   # reconciliacion UNICA
    ctx = rt.construir_contexto(inca, hoy=HOY)
    d = disparadas(ctx)
    # Ningun hallazgo puede citar un valor que el documento no imprimio.
    valores_impresos = {str(v) for v in leido.values() if v}
    mensajes = " | ".join(r.mensaje or "" for r in rt.evaluar_reglas(ctx) if r.estado == rt.NO_CUMPLE)
    # Solo la fecha de INICIO derivada: T01 cita a proposito el fin HIPOTETICO ("con esos
    # dias la fecha fin seria X") como explicacion del desfase, no como valor juzgado.
    derivados = {v for k, v in inca.items()
                 if k == "fecha_inicio" and v and str(v) not in valores_impresos}
    citados = [v for v in derivados if str(v) in mensajes]
    ok(f"[{nombre}] ningun mensaje cita un valor DERIVADO", not citados,
       f"derivados={derivados} citados={citados} mensajes={mensajes}")
    esperado = ["T11_FIN_REESCRITO_SIN_EVIDENCIA"] if nombre == "fin reescrito (no cuadraba)" else []
    # con foto, T11 no aplica: la evidencia esta guardada y T01 es quien opina
    if nombre == "fin reescrito (no cuadraba)":
        esperado = ["T01_DURACION_VS_RANGO"]
    ok(f"[{nombre}] hallazgos = {esperado}", d == esperado, str(d))

# --------------------------------------------------------------------------- #
titulo("B. Registro SIN foto (BD, API, reproceso): solo las marcas protegen")
# --------------------------------------------------------------------------- #
for nombre, inca, prohibidas in [
    ("inicio calculado", {"fecha_inicio": "2029-01-06", "fecha_fin": "2029-01-10", "dias": 5,
                          "fecha_inicio_calculada": True},
     ("T01_DURACION_VS_RANGO", "T02_FIN_ANTES_DE_INICIO", "T04_RANGO_MAYOR_AL_MAXIMO",
      "T06_FECHA_INICIO_ILEGIBLE", "T09_INICIO_EN_FUTURO", "T10_INICIO_MUY_ANTIGUO",
      "T14_EXPEDICION_POSTERIOR_AL_INICIO")),
    ("inicio calculado muy antiguo", {"fecha_inicio": "2019-01-06", "fecha_fin": "2019-01-10",
                                      "dias": 5, "fecha_inicio_calculada": True},
     ("T10_INICIO_MUY_ANTIGUO", "T01_DURACION_VS_RANGO")),
    ("fin recalculado", {"fecha_inicio": "2026-06-01", "fecha_fin": "2026-06-05", "dias": 5,
                         "fecha_fin_recalculada": True},
     ("T01_DURACION_VS_RANGO", "T02_FIN_ANTES_DE_INICIO", "T04_RANGO_MAYOR_AL_MAXIMO",
      "T07_FECHA_FIN_ILEGIBLE")),
    ("marca con valor raro ('si')", {"fecha_inicio": "2029-01-06", "fecha_fin": "2029-01-10",
                                     "dias": 5, "fecha_inicio_calculada": "si"},
     ("T09_INICIO_EN_FUTURO", "T01_DURACION_VS_RANGO")),
    ("marca 0/1 en vez de bool", {"fecha_inicio": "2029-01-06", "fecha_fin": "2029-01-10",
                                  "dias": 5, "fecha_inicio_calculada": 1},
     ("T09_INICIO_EN_FUTURO", "T01_DURACION_VS_RANGO")),
]:
    d = disparadas(ctx_sin_foto(inca))
    ok(f"[sin foto: {nombre}] no dispara sobre el valor derivado",
       not (set(d) & set(prohibidas)), f"disparadas={d}")

# --------------------------------------------------------------------------- #
titulo("C. Camino de la REVISION HUMANA: el formulario devuelve lo calculado")
# --------------------------------------------------------------------------- #
# `static/index.html:518` rellena el campo de la fecha de inicio con `row.fechainicio`
# (el valor EFECTIVO, que puede ser el derivado) y `overrides()` lo reenvia SIEMPRE, aunque
# el auxiliar no toque nada. Aqui se reproduce ese ida y vuelta con erp.
rec = {"tipo_documento": "incapacidad",
       "paciente": {"nombre": "PACIENTE DE PRUEBA", "documento_numero": "13742111"},
       "entidad": {"eps": "SALUD TOTAL"}, "diagnostico": {"cie10": "J06.9"},
       "incapacidad": {"fecha_inicio": None, "fecha_fin": "2029-01-10", "dias": 5}}
inca = rec["incapacidad"]
inca[rt.CLAVE_SNAPSHOT] = rt.snapshot_leidos(inca)
normalizar_fechas(rec)
res = {"fuente": "doc.pdf", "ocr_backend": "stub", "extractor": "rule", "incapacidad": rec}

m1 = __import__("incapacidad_ocr.erp", fromlist=["erp"]).mapear_a_staging(
    res, "WHATSAPP", LookupsFalsos(), hoy=HOY)
ok("1a pasada: la fila lleva el inicio DERIVADO y lo declara",
   m1["row"]["fechainicio"] == "2029-01-06" and m1["fecha_inicio_calculada"] is True,
   f"{m1['row']['fechainicio']} calculada={m1['fecha_inicio_calculada']}")
t1 = {r["codigo"]: r["estado"] for r in m1["tiempos"]["reglas"]}
ok("1a pasada: T01/T09 NO_EVALUABLE (no se juzga lo derivado)",
   t1["T01_DURACION_VS_RANGO"] == rt.NO_EVALUABLE and t1["T09_INICIO_EN_FUTURO"] == rt.NO_EVALUABLE,
   f"T01={t1['T01_DURACION_VS_RANGO']} T09={t1['T09_INICIO_EN_FUTURO']}")

# --- el auxiliar abre el caso y pulsa guardar SIN tocar ningun campo -------------------
ov_ui = {"cedula": m1["row"]["cedula_leida"], "paciente": m1["paciente_ocr"],
         "cie10": m1["row"]["codigo_diagnostico_leido"], "eps": m1["row"]["eps_leida"],
         "fecha_inicio": m1["row"]["fechainicio"],          # <- index.html:518 (valor DERIVADO)
         "dias": m1["row"]["Numerodias"]}
m2 = __import__("incapacidad_ocr.erp", fromlist=["erp"]).mapear_a_staging(
    res, "WHATSAPP", LookupsFalsos(), hoy=HOY, overrides=ov_ui)
t2 = {r["codigo"]: r["estado"] for r in m2["tiempos"]["reglas"]}
ok("2a pasada (reenvio del formulario): T09 sigue NO_EVALUABLE, no dispara sobre lo derivado",
   t2["T09_INICIO_EN_FUTURO"] == rt.NO_EVALUABLE,
   f"T09={t2['T09_INICIO_EN_FUTURO']} problemas={m2['problemas']}")
ok("2a pasada: T01 sigue NO_EVALUABLE (no se convierte en un CUMPLE tautologico)",
   t2["T01_DURACION_VS_RANGO"] == rt.NO_EVALUABLE, t2["T01_DURACION_VS_RANGO"])
ok("2a pasada: la fila sigue declarando que el inicio es CALCULADO",
   m2["fecha_inicio_calculada"] is True, str(m2["fecha_inicio_calculada"]))
ok("2a pasada: la confianza no sube por un valor que el documento no imprime",
   m2["row"]["confianza_ocr"] == m1["row"]["confianza_ocr"],
   f"{m1['row']['confianza_ocr']} -> {m2['row']['confianza_ocr']}")
ok("2a pasada: la cobertura del informe no sube sin dato nuevo",
   m2["tiempos"]["resumen"]["cobertura"] <= m1["tiempos"]["resumen"]["cobertura"],
   f"{m1['tiempos']['resumen']['cobertura']} -> {m2['tiempos']['resumen']['cobertura']}")

# el mismo ida y vuelta con un inicio derivado MUY ANTIGUO (T10, LEVE)
rec2 = {"tipo_documento": "incapacidad",
        "paciente": {"nombre": "X", "documento_numero": "13742111"},
        "entidad": {"eps": "SALUD TOTAL"}, "diagnostico": {"cie10": "J06.9"},
        "incapacidad": {"fecha_inicio": None, "fecha_fin": "2023-01-10", "dias": 5,
                        "fecha_expedicion": "2023-02-01"}}
inca2 = rec2["incapacidad"]
inca2[rt.CLAVE_SNAPSHOT] = rt.snapshot_leidos(inca2)
normalizar_fechas(rec2)
res2 = {"fuente": "doc2.pdf", "ocr_backend": "stub", "extractor": "rule", "incapacidad": rec2}
erp_mod = __import__("incapacidad_ocr.erp", fromlist=["erp"])
n1 = erp_mod.mapear_a_staging(res2, "WHATSAPP", LookupsFalsos(), hoy=HOY)
n2 = erp_mod.mapear_a_staging(res2, "WHATSAPP", LookupsFalsos(), hoy=HOY,
                              overrides={"fecha_inicio": n1["row"]["fechainicio"]})
ok("reenvio: T10/T14 no aparecen de la nada sobre un inicio derivado",
   set(n2["row"]["alertas_tiempos"].split("; ") if n2["row"]["alertas_tiempos"] else [])
   <= set(n1["row"]["alertas_tiempos"].split("; ") if n1["row"]["alertas_tiempos"] else []),
   f"1a={n1['row']['alertas_tiempos']}  2a={n2['row']['alertas_tiempos']}")

# --------------------------------------------------------------------------- #
titulo("D. dias derivado por el propio extractor (vacaciones/permisos)")
# --------------------------------------------------------------------------- #
# En vacaciones los dias los deriva el extractor de las dos fechas: T01 seria tautologico.
rec3 = {"tipo_documento": "vacaciones",
        "incapacidad": {"fecha_inicio": "2026-06-01", "fecha_fin": "2026-06-15", "dias": None}}
i3 = rec3["incapacidad"]
i3[rt.CLAVE_SNAPSHOT] = rt.snapshot_leidos(i3)
normalizar_fechas(rec3)
ctx3 = rt.construir_contexto(i3, hoy=HOY, tipo_documento="vacaciones")
ok("dias derivado (vacaciones): T01/T03 NO_EVALUABLE, no CUMPLE tautologico",
   estado(ctx3, "T01_DURACION_VS_RANGO") == rt.NO_EVALUABLE
   and estado(ctx3, "T03_DIAS_FUERA_DE_RANGO") == rt.NO_EVALUABLE,
   f"T01={estado(ctx3, 'T01_DURACION_VS_RANGO')} T03={estado(ctx3, 'T03_DIAS_FUERA_DE_RANGO')} "
   f"dias_efectivo={i3['dias']}")

# --------------------------------------------------------------------------- #
titulo("E. Saneo final de normalizar_fechas (anula una de las dos fechas)")
# --------------------------------------------------------------------------- #
# Rango imposible sin dias: la reconciliacion ANULA una fecha. La foto tiene que conservarla.
rec4 = {"tipo_documento": "incapacidad",
        "incapacidad": {"fecha_inicio": "2026-06-10", "fecha_fin": "2026-06-01", "dias": None}}
i4 = rec4["incapacidad"]
i4[rt.CLAVE_SNAPSHOT] = rt.snapshot_leidos(i4)
normalizar_fechas(rec4)
ok("saneo anula una fecha en la fila...",
   i4["fecha_inicio"] is None or i4["fecha_fin"] is None,
   f"inicio={i4['fecha_inicio']} fin={i4['fecha_fin']}")
ok("...pero el motor SIGUE viendo el rango imposible (T02 GRAVE)",
   estado(rt.construir_contexto(i4, hoy=HOY), "T02_FIN_ANTES_DE_INICIO") == rt.NO_CUMPLE,
   estado(rt.construir_contexto(i4, hoy=HOY), "T02_FIN_ANTES_DE_INICIO"))

# rango de 600 dias sin dias declarados: el saneo lo deja pasar (0..540 sobre la DIFERENCIA)
rec5 = {"tipo_documento": "incapacidad",
        "incapacidad": {"fecha_inicio": "2025-01-01", "fecha_fin": "2026-06-01", "dias": None}}
i5 = rec5["incapacidad"]
i5[rt.CLAVE_SNAPSHOT] = rt.snapshot_leidos(i5)
normalizar_fechas(rec5)
ok("rango de 517 dias sin dias: T04 opina sobre lo leido y el saneo no lo tapa",
   estado(rt.construir_contexto(i5, hoy=HOY), "T04_RANGO_MAYOR_AL_MAXIMO") in
   (rt.CUMPLE, rt.NO_CUMPLE), estado(rt.construir_contexto(i5, hoy=HOY),
                                     "T04_RANGO_MAYOR_AL_MAXIMO"))

raise SystemExit(cierre())
