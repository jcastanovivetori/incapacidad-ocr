"""ATAQUE 1 — contextos degenerados: fechas nulas/imposibles, dias 0/negativos/enormes,
tipos mezclados, campos ausentes, bisiesto, cambios de mes y de anio.

Cada bloque dice ENTRADA -> ESPERADO y comprueba lo OBTENIDO.
"""
from __future__ import annotations

import datetime as dt
import json
from datetime import date

from _comun import (HOY, cierre, ctx_foto, ctx_sin_foto, disparadas, estado, estados, ok,
                    regla, rt, titulo, vt)

# --------------------------------------------------------------------------- #
titulo("A. Vacio total y formas raras del registro (no debe caerse)")
# --------------------------------------------------------------------------- #
inf = vt.validar_registro({}, hoy=HOY)
ok("registro {} -> SIN_DATOS", inf["veredicto"] == rt.V_SIN_DATOS, inf["veredicto"])
ok("registro {} -> sin hallazgos", inf["problemas"] == [] and inf["avisos"] == [])
ok("registro {} -> informe serializable", isinstance(json.dumps(inf), str))
# La cobertura es lo que evita leer un COHERENTE como "documento verificado": si no se
# leyo NADA no puede haber ninguna regla "comprobada".
ok("registro {} -> cobertura 0.0 y 0 reglas comprobadas",
   inf["resumen"]["cobertura"] == 0.0 and inf["resumen"]["cumplen"] == 0,
   f"cobertura={inf['resumen']['cobertura']} cumplen={inf['resumen']['cumplen']}")

for forma, dato in [("None", None), ("cadena", "2026-06-01"), ("lista", [1, 2]),
                    ("int", 7), ("{'incapacidad': None}", {"incapacidad": None}),
                    ("{'incapacidad': 'x'}", {"incapacidad": "x"}),
                    ("anidado process()", {"incapacidad": {"incapacidad": {"dias": 3}}})]:
    try:
        i = vt.validar_registro(dato, hoy=HOY)
        ok(f"validar_registro({forma}) no revienta", i["veredicto"] in
           (rt.V_SIN_DATOS, rt.V_COHERENTE, rt.V_AVISOS, rt.V_REVISAR), i["veredicto"])
    except Exception as exc:                                     # noqa: BLE001
        ok(f"validar_registro({forma}) no revienta", False, f"{type(exc).__name__}: {exc}")

for forma, snap in [("lista", [1]), ("cadena", "x"), ("int", 3), ("None", None)]:
    try:
        c = rt.construir_contexto({rt.CLAVE_SNAPSHOT: snap, "fecha_inicio": "2026-06-01",
                                   "dias": 3}, hoy=HOY)
        ok(f"snapshot {forma} -> se ignora y se usa el registro",
           c.inicio_leido == date(2026, 6, 1), str(c.inicio_leido))
    except Exception as exc:                                     # noqa: BLE001
        ok(f"snapshot {forma} no revienta", False, f"{type(exc).__name__}: {exc}")

# --------------------------------------------------------------------------- #
titulo("B. Fechas imposibles / basura (ilegible != violacion)")
# --------------------------------------------------------------------------- #
CASOS_FECHA_MALA = ["2026-02-30", "2026-02-29", "2026-13-01", "2026-00-10", "2026-06-31",
                    "2016-06-54", "0000-00-00", "26-06-01", "2026-6-1", "2026/06/01",
                    "01/06/2026", "2026-06-01T00:00:00", "2026-W23-1", "20260601",
                    "", "   ", "-", "None", "9999-99-99"]
for v in CASOS_FECHA_MALA:
    e = estados(ctx_foto(inicio=v, fin="2026-06-05", dias=5))
    esperado_t06 = rt.NO_EVALUABLE if v.strip() == "" else rt.NO_CUMPLE
    ok(f"inicio={v!r}: T06={esperado_t06} y T01/T02/T04 NO_EVALUABLE",
       e["T06_FECHA_INICIO_ILEGIBLE"] == esperado_t06
       and e["T01_DURACION_VS_RANGO"] == rt.NO_EVALUABLE
       and e["T02_FIN_ANTES_DE_INICIO"] == rt.NO_EVALUABLE
       and e["T04_RANGO_MAYOR_AL_MAXIMO"] == rt.NO_EVALUABLE,
       f"T06={e['T06_FECHA_INICIO_ILEGIBLE']} T01={e['T01_DURACION_VS_RANGO']} "
       f"T02={e['T02_FIN_ANTES_DE_INICIO']} T04={e['T04_RANGO_MAYOR_AL_MAXIMO']}")

# fecha fin ilegible: misma simetria
e = estados(ctx_foto(inicio="2026-06-01", fin="2026-02-30", dias=5))
ok("fin='2026-02-30': T07 NO_CUMPLE, T01/T02/T04 NO_EVALUABLE",
   e["T07_FECHA_FIN_ILEGIBLE"] == rt.NO_CUMPLE
   and e["T01_DURACION_VS_RANGO"] == rt.NO_EVALUABLE, str(e["T07_FECHA_FIN_ILEGIBLE"]))

# --------------------------------------------------------------------------- #
titulo("C. Bisiesto, cambio de mes y cambio de anio (aritmetica inclusiva)")
# --------------------------------------------------------------------------- #
CASOS_SPAN = [
    ("2024-02-27", "2024-03-01", 4, True),    # bisiesto 2024: 27,28,29,1
    ("2024-02-27", "2024-03-01", 5, False),   # el mismo rango con 5 dias NO cuadra
    ("2023-02-27", "2023-03-01", 3, True),    # no bisiesto: 27,28,1
    ("2023-02-27", "2023-03-01", 4, False),
    ("2025-12-28", "2026-01-03", 7, True),    # cambio de anio
    ("2026-01-31", "2026-02-01", 2, True),    # cambio de mes
    ("2026-06-01", "2026-06-01", 1, True),    # un solo dia
    ("2024-02-29", "2024-02-29", 1, True),    # 29 de febrero bisiesto
    ("2026-01-01", "2026-12-31", 365, True),  # anio completo (por encima de dias_max)
]
for ini, fin, dias, cuadra in CASOS_SPAN:
    r = regla(ctx_foto(inicio=ini, fin=fin, dias=dias), "T01_DURACION_VS_RANGO")
    esperado = rt.CUMPLE if cuadra else rt.NO_CUMPLE
    ok(f"T01 {ini}->{fin} dias={dias}: {esperado}", r.estado == esperado,
       f"{r.estado} {r.mensaje or ''}")

# 29-feb en anio NO bisiesto ya cubierto arriba; aqui el limite exacto de dias_max
r = regla(ctx_foto(inicio="2026-01-01", fin="2027-06-24", dias=540), "T01_DURACION_VS_RANGO")
ok("T01 span 540 exacto (dias_max) -> CUMPLE", r.estado == rt.CUMPLE, f"{r.estado} {r.mensaje}")
e = estados(ctx_foto(inicio="2026-01-01", fin="2027-06-25", dias=541))
ok("dias=541 -> T03 NO_CUMPLE y T01/T04 callados (un solo mensaje)",
   e["T03_DIAS_FUERA_DE_RANGO"] == rt.NO_CUMPLE and e["T01_DURACION_VS_RANGO"] == rt.CUMPLE
   and e["T04_RANGO_MAYOR_AL_MAXIMO"] == rt.CUMPLE, str(e))

# --------------------------------------------------------------------------- #
titulo("D. Dias: 0, negativos, enormes, tipos mezclados")
# --------------------------------------------------------------------------- #
CASOS_DIAS = [
    # (valor crudo, dias_leido esperado, T03 esperado, T05 esperado)
    (0, 0, rt.NO_CUMPLE, rt.CUMPLE),
    (-3, -3, rt.NO_CUMPLE, rt.CUMPLE),
    (541, 541, rt.NO_CUMPLE, rt.CUMPLE),
    (900, 900, rt.NO_CUMPLE, rt.CUMPLE),
    ("5", 5, rt.CUMPLE, rt.CUMPLE),
    ("05", 5, rt.CUMPLE, rt.CUMPLE),
    (" 5 ", 5, rt.CUMPLE, rt.CUMPLE),
    ("+5", 5, rt.CUMPLE, rt.CUMPLE),
    ("-5", -5, rt.NO_CUMPLE, rt.CUMPLE),
    (5.0, 5, rt.CUMPLE, rt.CUMPLE),
    (5.5, None, rt.NO_EVALUABLE, rt.NO_CUMPLE),
    ("5.0", None, rt.NO_EVALUABLE, rt.NO_CUMPLE),
    ("dos", None, rt.NO_EVALUABLE, rt.NO_CUMPLE),
    ("DOS (2) dias", None, rt.NO_EVALUABLE, rt.NO_CUMPLE),
    ("5 dias", None, rt.NO_EVALUABLE, rt.NO_CUMPLE),
    ("1234567", None, rt.NO_EVALUABLE, rt.NO_CUMPLE),      # 7 cifras: no entra
    ("٥", None, rt.NO_EVALUABLE, rt.NO_CUMPLE),        # digito arabe-indico
    ("²", None, rt.NO_EVALUABLE, rt.NO_CUMPLE),        # superindice
    (True, None, rt.NO_EVALUABLE, rt.NO_CUMPLE),
    (False, None, rt.NO_EVALUABLE, rt.NO_EVALUABLE),        # False == "sin dato"
    ([5], None, rt.NO_EVALUABLE, rt.NO_CUMPLE),
    ({"d": 5}, None, rt.NO_EVALUABLE, rt.NO_CUMPLE),
    (b"5", None, rt.NO_EVALUABLE, rt.NO_CUMPLE),
    ("", None, rt.NO_EVALUABLE, rt.NO_EVALUABLE),
    (None, None, rt.NO_EVALUABLE, rt.NO_EVALUABLE),
    (10 ** 20, 10 ** 20, rt.NO_CUMPLE, rt.CUMPLE),
    (int("9" * 400), int("9" * 400), rt.NO_CUMPLE, rt.CUMPLE),
]
for crudo, leido_esp, t03_esp, t05_esp in CASOS_DIAS:
    c = ctx_foto(dias=crudo)
    e = estados(c)
    etq = repr(crudo)[:24]
    ok(f"dias={etq}: dias_leido={leido_esp!r}", c.dias_leido == leido_esp, repr(c.dias_leido))
    ok(f"dias={etq}: T03={t03_esp} T05={t05_esp}",
       e["T03_DIAS_FUERA_DE_RANGO"] == t03_esp and e["T05_DIAS_NO_NUMERICO"] == t05_esp,
       f"T03={e['T03_DIAS_FUERA_DE_RANGO']} T05={e['T05_DIAS_NO_NUMERICO']}")

# longitud del mensaje que acaba en la columna `problemas` y en la pantalla
r = regla(ctx_foto(dias=int("9" * 400)), "T03_DIAS_FUERA_DE_RANGO")
ok("mensaje de T03 acotado (<=200 car.) con dias de 400 cifras",
   len(r.mensaje or "") <= 200, f"len={len(r.mensaje or '')}")
c = ctx_foto(dias=int("9" * 400))
ok("dias_leidos que iria a la columna INT cabe en INT (2147483647)",
   c.dias_leido is None or abs(c.dias_leido) <= 2147483647, repr(c.dias_leido)[:60])

# --------------------------------------------------------------------------- #
titulo("E. Fin anterior al inicio (rango imposible)")
# --------------------------------------------------------------------------- #
e = estados(ctx_foto(inicio="2026-06-10", fin="2026-06-01", dias=5))
ok("fin<inicio: solo T02 NO_CUMPLE (T01 y T04 se callan)",
   e["T02_FIN_ANTES_DE_INICIO"] == rt.NO_CUMPLE
   and e["T01_DURACION_VS_RANGO"] == rt.CUMPLE
   and e["T04_RANGO_MAYOR_AL_MAXIMO"] == rt.CUMPLE, str(e))
e = estados(ctx_foto(inicio="2026-06-10", fin="2026-06-01"))
ok("fin<inicio sin dias: T02 NO_CUMPLE", e["T02_FIN_ANTES_DE_INICIO"] == rt.NO_CUMPLE)
e = estados(ctx_foto(inicio="2026-06-10", fin="2020-01-01", dias=5))
ok("fin 6 anios antes: solo T02", disparadas(ctx_foto(inicio="2026-06-10", fin="2020-01-01",
                                                     dias=5)) == ["T02_FIN_ANTES_DE_INICIO"],
   str(disparadas(ctx_foto(inicio="2026-06-10", fin="2020-01-01", dias=5))))

# --------------------------------------------------------------------------- #
titulo("F. Doble mensaje del mismo problema (T01 + T04)")
# --------------------------------------------------------------------------- #
d = disparadas(ctx_foto(inicio="2020-01-01", fin="2026-01-01", dias=5))
ok("inicio 2020 / fin 2026 / dias 5: no se emiten DOS GRAVES por lo mismo",
   len([x for x in d if x in ("T01_DURACION_VS_RANGO", "T04_RANGO_MAYOR_AL_MAXIMO")]) <= 1,
   str(d))
res = rt.evaluar(ctx_foto(inicio="2020-01-01", fin="2026-01-01", dias=5))
ok("puntaje no se hunde por doble contabilizacion del mismo problema",
   res.puntaje >= 55, f"puntaje={res.puntaje} codigos={res.codigos}")

# --------------------------------------------------------------------------- #
titulo("G. Limites de calendario (date.max) y tipos date/datetime")
# --------------------------------------------------------------------------- #
r = regla(ctx_foto(inicio="9999-12-31", fin="9999-12-31", dias=5), "T01_DURACION_VS_RANGO")
ok("inicio=fin=9999-12-31 dias=5 -> T01 NO_CUMPLE (no se pierde el hallazgo)",
   r.estado == rt.NO_CUMPLE, f"{r.estado} motivo={r.motivo} mensaje={r.mensaje}")
r = regla(ctx_foto(inicio="0001-01-01", fin="0001-01-05", dias=9), "T01_DURACION_VS_RANGO")
ok("inicio=0001-01-01 (T10 resta 730 dias) -> T10 evaluable sin reventar",
   estado(ctx_foto(inicio="0001-01-01"), "T10_INICIO_MUY_ANTIGUO") in
   (rt.NO_CUMPLE, rt.NO_EVALUABLE), estado(ctx_foto(inicio="0001-01-01"),
                                          "T10_INICIO_MUY_ANTIGUO"))

# date y datetime nativos (lo que devolveria un driver de BD o un caller Python)
r = regla(ctx_foto(inicio=date(2026, 6, 1), fin=date(2026, 6, 5), dias=5),
          "T01_DURACION_VS_RANGO")
ok("date nativo: T01 CUMPLE (5 dias)", r.estado == rt.CUMPLE, f"{r.estado} {r.mensaje}")
r = regla(ctx_foto(inicio=date(2026, 6, 1), fin=date(2026, 6, 5), dias=9),
          "T01_DURACION_VS_RANGO")
ok("date nativo: T01 detecta el desfase (9 vs 5)", r.estado == rt.NO_CUMPLE,
   f"{r.estado} {r.mensaje}")
r = regla(ctx_foto(inicio=dt.datetime(2026, 6, 1, 10, 0), fin=date(2026, 6, 5), dias=9),
          "T01_DURACION_VS_RANGO")
ok("datetime + date mezclados: T01 sigue detectando el desfase",
   r.estado == rt.NO_CUMPLE, f"{r.estado} motivo={r.motivo}")
r = regla(ctx_foto(inicio=dt.datetime(2026, 6, 1, 10, 0), fin=dt.datetime(2026, 6, 3, 9, 0),
                   dias=3), "T01_DURACION_VS_RANGO")
ok("datetime con hora: 01-jun 10:00 -> 03-jun 09:00 son 3 dias -> CUMPLE",
   r.estado == rt.CUMPLE, f"{r.estado} {r.mensaje}")

# --------------------------------------------------------------------------- #
titulo("H. hoy: inyectado, nulo, y ventanas temporales")
# --------------------------------------------------------------------------- #
ok("T09 dispara a hoy+31", estado(ctx_foto(inicio="2026-10-03"), "T09_INICIO_EN_FUTURO")
   == rt.NO_CUMPLE)
ok("T09 calla a hoy+30 (borde)", estado(ctx_foto(inicio="2026-10-02"), "T09_INICIO_EN_FUTURO")
   == rt.CUMPLE)
ok("T10 dispara a hoy-731", estado(ctx_foto(inicio="2024-09-01"), "T10_INICIO_MUY_ANTIGUO")
   == rt.NO_CUMPLE)
ok("T10 calla a hoy-730 (borde)", estado(ctx_foto(inicio="2024-09-03"), "T10_INICIO_MUY_ANTIGUO")
   == rt.CUMPLE)
try:
    c = rt.construir_contexto({"fecha_inicio": "2026-06-01", "dias": 5}, hoy=None)
    i = rt.validar_tiempos(c)
    ok("hoy=None -> informe sin caerse", i["veredicto"] in
       (rt.V_SIN_DATOS, rt.V_COHERENTE, rt.V_AVISOS, rt.V_REVISAR), i["veredicto"])
except Exception as exc:                                          # noqa: BLE001
    ok("hoy=None -> informe sin caerse", False, f"{type(exc).__name__}: {exc}")

# --------------------------------------------------------------------------- #
titulo("I. Campos ausentes y overrides que borran evidencia")
# --------------------------------------------------------------------------- #
e = estados(ctx_foto(inicio="2026-06-01"))
ok("solo inicio: T01/T12 NO_EVALUABLE, nada NO_CUMPLE",
   e["T01_DURACION_VS_RANGO"] == rt.NO_EVALUABLE and not disparadas(ctx_foto(inicio="2026-06-01")),
   str(disparadas(ctx_foto(inicio="2026-06-01"))))

# override con None: el auxiliar no teclea nada y se borra el fin IMPRESO que no cuadraba
base = {rt.CLAVE_SNAPSHOT: {"fecha_inicio": "2026-06-01", "fecha_fin": "2026-06-20",
                            "dias": 5, "dias_letra": None}}
sin_ov = rt.construir_contexto(base, hoy=HOY)
con_ov = rt.construir_contexto(base, hoy=HOY, overrides={"fecha_fin": None})
ok("override fecha_fin=None NO borra la evidencia del fin impreso",
   estado(con_ov, "T01_DURACION_VS_RANGO") == estado(sin_ov, "T01_DURACION_VS_RANGO"),
   f"sin override={estado(sin_ov, 'T01_DURACION_VS_RANGO')} "
   f"con override={estado(con_ov, 'T01_DURACION_VS_RANGO')}")

# --------------------------------------------------------------------------- #
titulo("J. Sin foto de processor: marcas de la reconciliacion")
# --------------------------------------------------------------------------- #
c = ctx_sin_foto({"fecha_inicio": "2026-06-06", "fecha_fin": "2026-06-10", "dias": 5,
                  "fecha_inicio_calculada": True, "fecha_fin_recalculada": False})
e = estados(c)
ok("sin foto + fecha_inicio_calculada: T01/T09/T10 NO_EVALUABLE",
   e["T01_DURACION_VS_RANGO"] == rt.NO_EVALUABLE
   and e["T09_INICIO_EN_FUTURO"] == rt.NO_EVALUABLE
   and e["T10_INICIO_MUY_ANTIGUO"] == rt.NO_EVALUABLE, str(e))
c = ctx_sin_foto({"fecha_inicio": "2026-06-01", "fecha_fin": "2026-06-05", "dias": 5,
                  "fecha_fin_recalculada": True})
ok("sin foto + fecha_fin_recalculada: T11 NO_CUMPLE (GRAVE) y T01 NO_EVALUABLE",
   estado(c, "T11_FIN_REESCRITO_SIN_EVIDENCIA") == rt.NO_CUMPLE
   and estado(c, "T01_DURACION_VS_RANGO") == rt.NO_EVALUABLE,
   f"T11={estado(c, 'T11_FIN_REESCRITO_SIN_EVIDENCIA')} T01={estado(c, 'T01_DURACION_VS_RANGO')}")

# --------------------------------------------------------------------------- #
titulo("K. T12 dias en letras")
# --------------------------------------------------------------------------- #
ok("sin letras -> T12 NO_EVALUABLE",
   estado(ctx_foto(dias=5), "T12_DIAS_LETRA_DISCREPA") == rt.NO_EVALUABLE)
ok("letras=2 digito=5 -> T12 NO_CUMPLE",
   estado(ctx_foto(dias=5, dias_letra=2), "T12_DIAS_LETRA_DISCREPA") == rt.NO_CUMPLE)
ok("letras=5 digito=5 -> T12 CUMPLE",
   estado(ctx_foto(dias=5, dias_letra=5), "T12_DIAS_LETRA_DISCREPA") == rt.CUMPLE)
ok("letras='cinco' (no entero) -> T12 NO_EVALUABLE",
   estado(ctx_foto(dias=5, dias_letra="cinco"), "T12_DIAS_LETRA_DISCREPA") == rt.NO_EVALUABLE)
ok("letras=0 -> T12 NO_EVALUABLE o CUMPLE, nunca hallazgo contra dias ausente",
   estado(ctx_foto(dias_letra=0), "T12_DIAS_LETRA_DISCREPA") == rt.NO_EVALUABLE,
   estado(ctx_foto(dias_letra=0), "T12_DIAS_LETRA_DISCREPA"))

# --------------------------------------------------------------------------- #
titulo("L. Coherencia interna del informe")
# --------------------------------------------------------------------------- #
for nombre, c in [("todo vacio", ctx_foto()),
                  ("solo grave", ctx_foto(inicio="2026-06-01", fin="2026-06-20", dias=5)),
                  ("solo leve", ctx_foto(inicio="2024-01-01")),
                  ("mezcla", ctx_foto(inicio="2024-01-01", fin="2026-06-20", dias=5,
                                      dias_letra=9, fecha_expedicion="2024-03-01"))]:
    i = rt.validar_tiempos(c)
    n = i["resumen"]
    ok(f"[{nombre}] resumen suma el catalogo entero",
       n["cumplen"] + n["no_cumplen"] + n["no_evaluables"] + n["desactivadas"]
       == n["reglas_en_catalogo"] == len(rt.CATALOGO), json.dumps(n))
    ok(f"[{nombre}] no_cumplen == graves+medias+leves",
       n["no_cumplen"] == n["graves"] + n["medias"] + n["leves"], json.dumps(n))
    ok(f"[{nombre}] exige_revision <-> severidad_max en (GRAVE, MEDIA)",
       i["exige_revision"] == (i["severidad_max"] in (rt.GRAVE, rt.MEDIA)),
       f"{i['exige_revision']} / {i['severidad_max']}")
    ok(f"[{nombre}] veredicto coherente con los hallazgos",
       (i["veredicto"] == rt.V_REVISAR) == i["exige_revision"], i["veredicto"])
    ok(f"[{nombre}] puntaje en 0..100", 0 <= i["puntaje_coherencia"] <= 100,
       str(i["puntaje_coherencia"]))
    ok(f"[{nombre}] serializable", isinstance(json.dumps(i), str))
    ok(f"[{nombre}] mensaje solo en NO_CUMPLE / motivo solo en el resto",
       all((r["mensaje"] is None) != (r["estado"] == rt.NO_CUMPLE) for r in i["reglas"]),
       str([r["codigo"] for r in i["reglas"]
            if (r["mensaje"] is None) == (r["estado"] == rt.NO_CUMPLE)]))

# documento del que solo se leyo la fecha de expedicion: COHERENTE con cobertura 0
i = rt.validar_tiempos(ctx_foto(fecha_expedicion="2026-06-01"))
ok("solo expedicion: no se declara COHERENTE con cobertura 0",
   not (i["veredicto"] == rt.V_COHERENTE and i["resumen"]["cobertura"] == 0.0),
   f"veredicto={i['veredicto']} cobertura={i['resumen']['cobertura']}")

raise SystemExit(cierre())
