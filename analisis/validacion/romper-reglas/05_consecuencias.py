"""ATAQUE 5 — consecuencias medibles de los hallazgos (para dimensionar la severidad)."""
from __future__ import annotations

from _comun import HOY, LookupsFalsos, cierre, ok, resultado_process, rt, titulo
from incapacidad_ocr import erp
from incapacidad_ocr.extract import normalizar_fechas

# --------------------------------------------------------------------------- #
titulo("A. El reenvio del formulario BLOQUEA la aprobacion (409 en /api/registrar)")
# --------------------------------------------------------------------------- #
# Documento tipo 'prelicencia'/procedimiento programado: el OCR solo saca fin + dias.
rec = {"tipo_documento": "incapacidad",
       "paciente": {"nombre": "X", "documento_numero": "13742111"},
       "entidad": {"eps": "SALUD TOTAL"}, "diagnostico": {"cie10": "J06.9"},
       "incapacidad": {"fecha_inicio": None, "fecha_fin": "2026-11-30", "dias": 5}}
inca = rec["incapacidad"]
inca[rt.CLAVE_SNAPSHOT] = rt.snapshot_leidos(inca)
normalizar_fechas(rec)
res = {"fuente": "doc.pdf", "ocr_backend": "stub", "extractor": "rule", "incapacidad": rec}
m1 = erp.mapear_a_staging(res, "WHATSAPP", LookupsFalsos(), hoy=HOY)
print("   1a pasada: fechainicio =", m1["row"]["fechainicio"],
      "| requiere_revision =", m1["requiere_revision"], "|", m1["problemas"])
m2 = erp.mapear_a_staging(res, "WHATSAPP", LookupsFalsos(), hoy=HOY,
                          overrides={"fecha_inicio": m1["row"]["fechainicio"],
                                     "dias": m1["row"]["Numerodias"]})
print("   2a pasada: requiere_revision =", m2["requiere_revision"], "|", m2["problemas"])
ok("reenviar el formulario sin tocar nada no puede crear un bloqueo nuevo",
   m2["requiere_revision"] == m1["requiere_revision"],
   f"{m1['requiere_revision']} -> {m2['requiere_revision']} ({m2['problemas']})")

# --------------------------------------------------------------------------- #
titulo("B. Vacaciones: los dias los deriva el extractor; el reenvio los vuelve 'leidos'")
# --------------------------------------------------------------------------- #
recv = {"tipo_documento": "vacaciones",
        "paciente": {"nombre": "X", "documento_numero": "13742111"},
        "entidad": {}, "diagnostico": {},
        "incapacidad": {"fecha_inicio": "2026-06-01", "fecha_fin": "2026-06-15", "dias": None}}
iv = recv["incapacidad"]
iv[rt.CLAVE_SNAPSHOT] = rt.snapshot_leidos(iv)
normalizar_fechas(recv)
resv = {"fuente": "vac.pdf", "ocr_backend": "stub", "extractor": "rule", "incapacidad": recv}
v1 = erp.mapear_a_staging(resv, "WHATSAPP", LookupsFalsos(), hoy=HOY)
v2 = erp.mapear_a_staging(resv, "WHATSAPP", LookupsFalsos(), hoy=HOY,
                          overrides={"dias": v1["row"]["Numerodias"]})
e1 = {r["codigo"]: r["estado"] for r in v1["tiempos"]["reglas"]}
e2 = {r["codigo"]: r["estado"] for r in v2["tiempos"]["reglas"]}
ok("T01 no pasa de NO_EVALUABLE a CUMPLE por reenviar los dias derivados",
   e1["T01_DURACION_VS_RANGO"] == e2["T01_DURACION_VS_RANGO"],
   f"{e1['T01_DURACION_VS_RANGO']} -> {e2['T01_DURACION_VS_RANGO']} "
   f"(cobertura {v1['tiempos']['resumen']['cobertura']} -> "
   f"{v2['tiempos']['resumen']['cobertura']})")

# --------------------------------------------------------------------------- #
titulo("C. Longitud de alertas_tiempos con TODAS las reglas encendidas por config")
# --------------------------------------------------------------------------- #
activables = [r.codigo for r in rt.CATALOGO]
peor_hoy = [c for c in activables if c not in ("T02_FIN_ANTES_DE_INICIO", "T03_DIAS_FUERA_DE_RANGO",
                                               "T05_DIAS_NO_NUMERICO", "T06_FECHA_INICIO_ILEGIBLE",
                                               "T07_FECHA_FIN_ILEGIBLE", "T08_DURACION_SIN_RESPALDO",
                                               "T09_INICIO_EN_FUTURO", "T11_FIN_REESCRITO_SIN_EVIDENCIA")]
s = "; ".join(peor_hoy)
ok("alertas_tiempos (VARCHAR(255)) aguanta el peor caso con T13/T15/T16/T17 encendidas",
   len(s) <= 255, f"len={len(s)} ({len(peor_hoy)} codigos compatibles entre si): {s}")
print(f"   catalogo completo ({len(activables)} codigos) = {len('; '.join(activables))} caracteres")

# --------------------------------------------------------------------------- #
titulo("D. dias enorme por la API: lo que quedaria en la fila")
# --------------------------------------------------------------------------- #
for n in [10 ** 10, int("9" * 24), int("9" * 400)]:
    m = erp.mapear_a_staging(resultado_process({"fecha_inicio": "2026-06-01", "dias": 5}),
                             "WHATSAPP", LookupsFalsos(), hoy=HOY, overrides={"dias": n})
    v = m["row"]["dias_leidos"]
    ok(f"dias={len(str(n))} cifras -> dias_leidos cabe en INT",
       v is None or abs(v) <= 2147483647, f"dias_leidos tiene {len(str(v))} cifras")
    ok(f"dias={len(str(n))} cifras -> `problemas` acotado (<=500)",
       len(m["row"]["problemas"] or "") <= 500, f"len={len(m['row']['problemas'] or '')}")

raise SystemExit(cierre())
