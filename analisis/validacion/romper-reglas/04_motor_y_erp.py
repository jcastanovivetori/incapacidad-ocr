"""ATAQUE 4 — el MOTOR y la frontera con `erp`: extender el catalogo mal, reglas que se
contradicen, y lo que acaba en la fila de staging (columnas con tipo/longitud fijos).
"""
from __future__ import annotations

import contextlib
import json
from datetime import date

from _comun import (HOY, LookupsFalsos, cierre, ctx_foto, disparadas, estado, ok,
                    resultado_process, rt, titulo)
from incapacidad_ocr import erp


@contextlib.contextmanager
def catalogo_con(*reglas):
    orig, orig_map = rt.CATALOGO, rt.CATALOGO_POR_CODIGO
    rt.CATALOGO = orig + reglas
    rt.CATALOGO_POR_CODIGO = {r.codigo: r for r in rt.CATALOGO}
    try:
        yield
    finally:
        rt.CATALOGO, rt.CATALOGO_POR_CODIGO = orig, orig_map


CTX = ctx_foto(inicio="2026-06-01", fin="2026-06-05", dias=5)

# --------------------------------------------------------------------------- #
titulo("A. Anadir una regla mal declarada (receta del CATALOGO)")
# --------------------------------------------------------------------------- #
# A1 severidad mal escrita en la declaracion (paso 2 de la receta)
mala_sev = rt.ReglaTiempo("T90_SEVERIDAD_MAL_ESCRITA", "severidad con una errata en la declaracion",
                          "ALTA", lambda ctx, u: "no cuadra", requiere=("inicio_leido",),
                          campo="dias")
with catalogo_con(mala_sev):
    try:
        v = rt.evaluar(CTX)
        _ = v.severidad_max, v.puntaje, v.problemas
        ok("regla nueva con severidad 'ALTA' -> degrada con aviso, no revienta", True)
    except Exception as exc:                                        # noqa: BLE001
        ok("regla nueva con severidad 'ALTA' -> degrada con aviso, no revienta", False,
           f"{type(exc).__name__}: {exc}")
    try:
        m = erp.mapear_a_staging(resultado_process({"fecha_inicio": "2026-06-01", "dias": 5}),
                                 "WHATSAPP", LookupsFalsos(), hoy=HOY)
        ok("...y el mapeo del documento sigue saliendo", bool(m["row"]))
    except Exception as exc:                                        # noqa: BLE001
        ok("...y el mapeo del documento sigue saliendo", False, f"{type(exc).__name__}: {exc}")

# A2 'requiere' con una errata: la regla queda muda para siempre
erratica = rt.ReglaTiempo("T91_REQUIERE_CON_ERRATA", "requiere un campo que no existe en el contexto",
                          rt.MEDIA, lambda ctx, u: "no cuadra", requiere=("fin_leidoo",),
                          campo="dias")
with catalogo_con(erratica):
    r = [x for x in rt.evaluar_reglas(CTX) if x.codigo == "T91_REQUIERE_CON_ERRATA"][0]
    ok("requiere con errata -> se detecta (no queda muda en silencio)",
       r.estado != rt.NO_EVALUABLE or "no existe" in (r.motivo or "").lower(),
       f"estado={r.estado} motivo={r.motivo}")

# A3 una regla que mira un valor EFECTIVO (lo que la invariante prohibe)
espia = rt.ReglaTiempo("T92_MIRA_EL_EFECTIVO", "juzga el valor reconciliado en vez del leido",
                       rt.GRAVE, lambda ctx, u: (f"el fin efectivo es {ctx.fin_efectivo}"
                                                 if ctx.fin_efectivo else None),
                       requiere=("inicio_leido",), campo="fecha_fin")
with catalogo_con(espia):
    ctx_ef = rt.construir_contexto({rt.CLAVE_SNAPSHOT: {"fecha_inicio": "2026-06-01"}},
                                   hoy=HOY, fin_efectivo="2026-06-05")
    r = [x for x in rt.evaluar_reglas(ctx_ef) if x.codigo == "T92_MIRA_EL_EFECTIVO"][0]
    ok("el motor impide EN EJECUCION que una regla juzgue un *_efectivo",
       r.estado != rt.NO_CUMPLE, f"estado={r.estado} mensaje={r.mensaje}")

# A4 'requiere' nombrando directamente un campo efectivo (no esta en CAMPOS_EXIGIBLES)
pide_ef = rt.ReglaTiempo("T93_REQUIERE_EFECTIVO", "declara requerir un valor efectivo",
                         rt.GRAVE, lambda ctx, u: "dispara", requiere=("dias_efectivo",),
                         campo="dias")
with catalogo_con(pide_ef):
    ctx_ef = rt.construir_contexto({rt.CLAVE_SNAPSHOT: {"fecha_inicio": "2026-06-01"}},
                                   hoy=HOY, dias_efectivo=5)
    r = [x for x in rt.evaluar_reglas(ctx_ef) if x.codigo == "T93_REQUIERE_EFECTIVO"][0]
    ok("requiere=('dias_efectivo',) -> el motor lo rechaza (no evalua la regla)",
       r.estado != rt.NO_CUMPLE, f"estado={r.estado} mensaje={r.mensaje}")

# A5 codigo DUPLICADO (copiar-pegar la entrada del catalogo)
dup = rt.ReglaTiempo("T01_DURACION_VS_RANGO", "copia pegada de la regla estrella",
                     rt.MEDIA, lambda ctx, u: "mensaje de la copia",
                     requiere=("inicio_leido",), campo="dias")
with catalogo_con(dup):
    v = rt.evaluar(CTX)
    i = rt.validar_tiempos(CTX)
    ok("codigo duplicado -> no se emiten dos hallazgos con el mismo codigo",
       len(v.codigos) == len(set(v.codigos)), str(v.codigos))
    ok("codigo duplicado -> el informe no lista dos veces el mismo codigo",
       len({r["codigo"] for r in i["reglas"]}) == len(i["reglas"]),
       str([r["codigo"] for r in i["reglas"]]))

# A6 una regla que devuelve algo que no es texto
for valor, etiqueta in [(True, "True"), (0, "0"), (1, "1"), ([], "[]"), (["a"], "['a']"),
                        ({"m": 1}, "dict"), (3.14, "float")]:
    r_raro = rt.ReglaTiempo("T94_DEVUELVE_RARO", "devuelve algo que no es un mensaje",
                            rt.MEDIA, lambda ctx, u, _v=valor: _v,
                            requiere=("inicio_leido",), campo="dias")
    with catalogo_con(r_raro):
        r = [x for x in rt.evaluar_reglas(CTX) if x.codigo == "T94_DEVUELVE_RARO"][0]
        malo = r.estado == rt.NO_CUMPLE and not isinstance(valor, str)
        ok(f"regla que devuelve {etiqueta} -> no se convierte en mensaje para el auxiliar",
           not malo, f"estado={r.estado} mensaje={r.mensaje!r}")

# A7 una regla que revienta / que se cuelga con una excepcion no-Exception
r_bug = rt.ReglaTiempo("T95_CON_BUG", "tiene un bug y revienta al evaluarse", rt.GRAVE,
                       lambda ctx, u: 1 / 0, requiere=("inicio_leido",), campo="dias")
with catalogo_con(r_bug):
    r = [x for x in rt.evaluar_reglas(CTX) if x.codigo == "T95_CON_BUG"][0]
    ok("regla con bug -> NO_EVALUABLE y el resto del veredicto sale",
       r.estado == rt.NO_EVALUABLE and "ZeroDivisionError" in (r.motivo or ""), str(r.motivo))

# A8 una regla nueva que SI funciona: escalabilidad real
buena = rt.ReglaTiempo("T96_INICIO_EN_DOMINGO", "la fecha de inicio cae en domingo", rt.LEVE,
                       lambda ctx, u: (None if ctx.inicio_leido.weekday() != 6
                                       else f"inicio en domingo ({ctx.inicio_leido.isoformat()})"),
                       requiere=("inicio_leido",), campo="fecha_inicio")
with catalogo_con(buena):
    ok("regla nueva: CUMPLE en lunes", estado(ctx_foto(inicio="2026-06-01"),
                                             "T96_INICIO_EN_DOMINGO") == rt.CUMPLE)
    ok("regla nueva: NO_CUMPLE en domingo", estado(ctx_foto(inicio="2026-06-07"),
                                                  "T96_INICIO_EN_DOMINGO") == rt.NO_CUMPLE)
    ok("regla nueva: la config puede cambiarle la severidad desde el primer dia",
       rt._aplicar(rt.config_por_defecto(), {"reglas": {"T96_INICIO_EN_DOMINGO":
                                                        {"severidad": "GRAVE"}}}, "archivo")
       .severidad_de("T96_INICIO_EN_DOMINGO") == rt.GRAVE)

# --------------------------------------------------------------------------- #
titulo("B. Dos reglas que se contradicen entre si")
# --------------------------------------------------------------------------- #
si = rt.ReglaTiempo("T97_DICE_QUE_SI", "afirma que el rango cuadra", rt.GRAVE,
                    lambda ctx, u: None if (ctx.fin_leido - ctx.inicio_leido).days + 1
                    == ctx.dias_leido else "no cuadra (segun T97)",
                    requiere=("inicio_leido", "fin_leido", "dias_leido"), campo="dias")
no = rt.ReglaTiempo("T98_DICE_QUE_NO", "afirma lo contrario que T97", rt.GRAVE,
                    lambda ctx, u: "SI cuadra (segun T98)" if (ctx.fin_leido - ctx.inicio_leido).days
                    + 1 == ctx.dias_leido else None,
                    requiere=("inicio_leido", "fin_leido", "dias_leido"), campo="dias")
with catalogo_con(si, no):
    i = rt.validar_tiempos(CTX)
    d = [r for r in i["reglas"] if r["estado"] == rt.NO_CUMPLE]
    ok("dos reglas contradictorias -> el informe las muestra las dos con su codigo",
       len(d) == 1 and d[0]["codigo"] == "T98_DICE_QUE_NO", str([x["codigo"] for x in d]))
    ok("dos reglas contradictorias -> veredicto determinista (no depende del orden)",
       i["veredicto"] == rt.V_REVISAR and i["severidad_max"] == rt.GRAVE,
       f"{i['veredicto']} {i['severidad_max']}")
    ok("...y el auxiliar puede saber QUE afirma cada una",
       all(r["afirma"] for r in i["reglas"]))

# --------------------------------------------------------------------------- #
titulo("C. Lo que llega a la FILA de staging (tipos y longitudes de columna)")
# --------------------------------------------------------------------------- #
# C1 dias enorme por override (webapp._limpiar_overrides deja pasar cualquier int)
enorme = int("9" * 24)
m = erp.mapear_a_staging(resultado_process({"fecha_inicio": "2026-06-01", "dias": 5}),
                         "WHATSAPP", LookupsFalsos(), hoy=HOY, overrides={"dias": enorme})
ok("dias enorme: Numerodias queda NULL (no viaja a la columna INT)",
   m["row"]["Numerodias"] is None, repr(m["row"]["Numerodias"]))
ok("dias enorme: dias_leidos cabe en la columna INT (max 2147483647)",
   m["row"]["dias_leidos"] is None or abs(m["row"]["dias_leidos"]) <= 2147483647,
   repr(m["row"]["dias_leidos"])[:70])
ok("dias enorme: el texto de `problemas` esta acotado",
   len(m["row"]["problemas"] or "") <= 500, f"len={len(m['row']['problemas'] or '')}")

# C2 fecha con solo espacios (pasa el filtro de erp: ' ' not in (None, ''))
m = erp.mapear_a_staging(resultado_process({"fecha_inicio": None, "dias": 5}),
                         "WHATSAPP", LookupsFalsos(), hoy=HOY, overrides={"fecha_inicio": "   "})
ok("fecha_inicio='   ': el mensaje no dice 'no es una fecha valida (=   )'",
   not any("(=   )" in p or "(= )" in p for p in m["problemas"]), str(m["problemas"]))
ok("fecha_inicio='   ': el auxiliar recibe algun mensaje sobre la fecha",
   any("fecha" in p.lower() for p in m["problemas"]), str(m["problemas"]))

# C3 longitud de alertas_tiempos (VARCHAR(255)) con muchas reglas disparadas
peor = erp.mapear_a_staging(
    resultado_process({"fecha_inicio": "2020-01-01", "fecha_fin": "2026-01-01", "dias": 5,
                       "dias_letra": 9, "fecha_expedicion": "2020-06-01"}),
    "WHATSAPP", LookupsFalsos(), hoy=HOY)
ok("alertas_tiempos cabe en VARCHAR(255) en el peor caso de hoy",
   len(peor["row"]["alertas_tiempos"] or "") <= 255,
   f"len={len(peor['row']['alertas_tiempos'] or '')} -> {peor['row']['alertas_tiempos']}")
todos = "; ".join(r.codigo for r in rt.CATALOGO)
ok("alertas_tiempos cabria en VARCHAR(255) si TODAS las reglas del catalogo disparasen",
   len(todos) <= 255, f"len={len(todos)} con {len(rt.CATALOGO)} reglas")
ok("severidad_tiempos cabe en VARCHAR(10)",
   len(peor["row"]["severidad_tiempos"] or "") <= 10, str(peor["row"]["severidad_tiempos"]))

# C4 fechafin_leida: siempre una fecha valida o NULL (columna DATE)
for fin in ["2026-02-30", "0000-00-00", "2026-06-05", None, "   ", 12345]:
    m = erp.mapear_a_staging(
        resultado_process({"fecha_inicio": "2026-06-01", "fecha_fin": fin, "dias": 5}),
        "WHATSAPP", LookupsFalsos(), hoy=HOY)
    v = m["row"]["fechafin_leida"]
    ok(f"fechafin_leida con fin={fin!r} -> None o ISO valido",
       v is None or rt.fecha_iso(v) is not None, repr(v))

# C5 el informe completo siempre es serializable (viaja por la API)
for extra in [{"dias": int("9" * 30)}, {"fecha_inicio": "2026-02-30"},
              {"fecha_inicio": date(2026, 6, 1)}, {"dias": [1, 2]}, {"dias": {"a": 1}}]:
    m = erp.mapear_a_staging(resultado_process({**{"fecha_inicio": "2026-06-01", "dias": 5},
                                               **extra}), "WHATSAPP", LookupsFalsos(), hoy=HOY)
    try:
        json.dumps(m["tiempos"])
        ok(f"informe serializable con {list(extra)[0]}={str(list(extra.values())[0])[:12]}", True)
    except Exception as exc:                                        # noqa: BLE001
        ok(f"informe serializable con {extra}", False, f"{type(exc).__name__}: {exc}")

# C6 `problemas` no puede quedar VACIO cuando hay un hallazgo GRAVE
m = erp.mapear_a_staging(
    resultado_process({"fecha_inicio": "2026-06-01", "fecha_fin": "2026-06-20", "dias": 5}),
    "WHATSAPP", LookupsFalsos(), hoy=HOY)
ok("hallazgo GRAVE -> viaja por `problemas` y exige revision",
   m["requiere_revision"] and any("no cuadran" in p for p in m["problemas"]), str(m["problemas"]))
ok("hallazgo GRAVE -> queda el codigo y la severidad en columnas propias",
   m["row"]["alertas_tiempos"] == "T01_DURACION_VS_RANGO"
   and m["row"]["severidad_tiempos"] == rt.GRAVE, str(m["row"]["alertas_tiempos"]))

# C7 apagar T01 por config NO debe dejar la fila incoherente (fechavencimiento)
cfg = rt._aplicar(rt.config_por_defecto(),
                  {"reglas": {"T01_DURACION_VS_RANGO": {"activa": False}}}, "archivo")
m = erp.mapear_a_staging(
    resultado_process({"fecha_inicio": "2026-06-01", "fecha_fin": "2026-06-20", "dias": 5}),
    "WHATSAPP", LookupsFalsos(), hoy=HOY, config_reglas=cfg)
di, nd, fv = m["row"]["fechainicio"], m["row"]["Numerodias"], m["row"]["fechavencimiento"]
ok("fechavencimiento == fechainicio + Numerodias (post-condicion de la fila)",
   rt.fecha_iso(fv) == rt.fecha_iso(di).__add__(__import__("datetime").timedelta(days=nd)),
   f"{di} + {nd} -> {fv}")
ok("T01 apagada: la fila NO conserva un fin leido que contradiga la propia fila sin avisar",
   m["row"]["fechafin_leida"] is None or m["row"]["alertas_tiempos"]
   or m["row"]["fechafin_leida"] == m["row"]["fechavencimiento"],
   f"fechafin_leida={m['row']['fechafin_leida']} venc={fv} alertas={m['row']['alertas_tiempos']}")

raise SystemExit(cierre())
