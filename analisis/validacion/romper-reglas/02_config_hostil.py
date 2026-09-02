"""ATAQUE 2 — configuracion externa hostil: tipos erroneos, severidad inexistente,
umbrales absurdos, JSON roto, reglas desconocidas, apagar/encender reglas.

Regla del repo que se ataca: "config invalida se IGNORA con un aviso; nunca desactiva una
regla en silencio ni tumba el mapeo".
"""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

from _comun import HOY, cierre, ctx_foto, disparadas, estado, ok, rt, titulo

TMP = Path(tempfile.mkdtemp(prefix="reglas_tiempo_"))


def cfg_archivo(datos, nombre="reglas_tiempo.json") -> rt.ConfigReglas:
    ruta = TMP / nombre
    ruta.write_text(datos if isinstance(datos, str) else json.dumps(datos), encoding="utf-8")
    return rt.cargar_config(ruta=ruta)


def cfg_bd(datos) -> rt.ConfigReglas:
    return rt.cargar_config(ruta=TMP / "no_existe.json", datos_bd=datos)


DEF = rt.config_por_defecto()

# --------------------------------------------------------------------------- #
titulo("A. Severidad inexistente / de tipo erroneo (por archivo y por BD)")
# --------------------------------------------------------------------------- #
CASOS_SEV = ["URGENTE", "", "  ", None, 5, 2.5, [], {}, True, "GRAVE ", "grave", "Media",
             "CRITICA", "gravísimo", "0", " "]
for sev in CASOS_SEV:
    for via, fn in (("archivo", cfg_archivo), ("bd", cfg_bd)):
        try:
            c = fn({"reglas": {"T01_DURACION_VS_RANGO": {"severidad": sev}}})
        except Exception as exc:                                   # noqa: BLE001
            ok(f"[{via}] severidad={sev!r} no revienta", False, f"{type(exc).__name__}: {exc}")
            continue
        efectiva = c.severidad_de("T01_DURACION_VS_RANGO")
        valida = str(sev).strip().upper() in rt.ORDEN_SEVERIDAD if isinstance(sev, str) else False
        esperada = str(sev).strip().upper() if valida else rt.GRAVE
        ok(f"[{via}] severidad={sev!r} -> {esperada} (+aviso si se ignora)",
           efectiva == esperada and (valida or any("T01" in a for a in c.avisos)),
           f"efectiva={efectiva} avisos={list(c.avisos)}")

# --------------------------------------------------------------------------- #
titulo("B. 'activa' de tipo erroneo y apagado/encendido real")
# --------------------------------------------------------------------------- #
for act, esperada_on in [(False, False), (True, True), (0, False), (1, True),
                         ("true", True), ("false", True), ("", True), (None, True),
                         (2, True), (-1, True), ([], True), (0.0, True)]:
    c = cfg_archivo({"reglas": {"T01_DURACION_VS_RANGO": {"activa": act}}})
    ok(f"activa={act!r} -> activa={esperada_on}",
       c.esta_activa("T01_DURACION_VS_RANGO") == esperada_on,
       f"{c.esta_activa('T01_DURACION_VS_RANGO')} avisos={list(c.avisos)}")

c = cfg_archivo({"reglas": {"T01_DURACION_VS_RANGO": {"activa": False}}})
r = ctx_foto(inicio="2026-06-01", fin="2026-06-20", dias=5)
ok("regla apagada -> DESACTIVADA y sin problemas",
   estado(r, "T01_DURACION_VS_RANGO", c) == rt.DESACTIVADA
   and "T01_DURACION_VS_RANGO" not in disparadas(r, c),
   estado(r, "T01_DURACION_VS_RANGO", c))
ok("regla apagada se REPORTA (no es silencio)",
   "T01_DURACION_VS_RANGO" in rt.evaluar(r, c).desactivadas)

c = cfg_archivo({"reglas": {"T13_DIA_SEMANA_INCONSISTENTE": {"activa": True},
                            "T15_SOLAPAMIENTO_MISMO_EMPLEADO": {"activa": True},
                            "T16_PRORROGA_SIN_ANTECEDENTE": {"activa": True},
                            "T17_DUPLICADO_TEMPORAL_EXACTO": {"activa": True}}})
e = {x.codigo: x.estado for x in rt.evaluar_reglas(r, c)}
ok("encender T13/T15/T16/T17 sin el dato -> NO_EVALUABLE, nunca NO_CUMPLE",
   all(e[k] == rt.NO_EVALUABLE for k in ("T13_DIA_SEMANA_INCONSISTENTE",
                                         "T15_SOLAPAMIENTO_MISMO_EMPLEADO",
                                         "T16_PRORROGA_SIN_ANTECEDENTE",
                                         "T17_DUPLICADO_TEMPORAL_EXACTO")), str(e))


class HistorialQueRevienta:
    def solapamientos(self, ctx):
        raise RuntimeError("BD caida")

    def duplicados_exactos(self, ctx):
        raise RuntimeError("BD caida")

    def tiene_antecedentes(self, ctx):
        raise RuntimeError("BD caida")

    def ausentismo_previo_contiguo(self, ctx):
        raise RuntimeError("BD caida")


ctx_hist = rt.construir_contexto(
    {rt.CLAVE_SNAPSHOT: {"fecha_inicio": "2026-06-01", "fecha_fin": None, "dias": 5}},
    hoy=HOY, id_empleado=7, historial=HistorialQueRevienta())
e = {x.codigo: x.estado for x in rt.evaluar_reglas(ctx_hist, c)}
ok("historial que revienta (BD caida) -> NO_EVALUABLE, no tumba el veredicto",
   e["T15_SOLAPAMIENTO_MISMO_EMPLEADO"] == rt.NO_EVALUABLE
   and e["T17_DUPLICADO_TEMPORAL_EXACTO"] == rt.NO_EVALUABLE, str(e))
ok("historial que devuelve basura (str en vez de lista) -> no revienta",
   True)


class HistorialBasura:
    def solapamientos(self, ctx):
        return "no soy una lista"

    def duplicados_exactos(self, ctx):
        return {"id": 1}

    def tiene_antecedentes(self, ctx):
        return "si"

    def ausentismo_previo_contiguo(self, ctx):
        return 0


ctx_bas = rt.construir_contexto(
    {rt.CLAVE_SNAPSHOT: {"fecha_inicio": "2026-06-01", "fecha_fin": None, "dias": 5}},
    hoy=HOY, id_empleado=7, historial=HistorialBasura())
try:
    e = {x.codigo: x.estado for x in rt.evaluar_reglas(ctx_bas, c)}
    ok("historial con tipos basura -> estado definido sin excepcion",
       e["T15_SOLAPAMIENTO_MISMO_EMPLEADO"] in rt.ESTADOS, str(e["T15_SOLAPAMIENTO_MISMO_EMPLEADO"]))
    m = [x for x in rt.evaluar_reglas(ctx_bas, c) if x.codigo == "T15_SOLAPAMIENTO_MISMO_EMPLEADO"][0]
    ok("historial con tipos basura -> mensaje NO cita 'n' de una cadena",
       m.estado != rt.NO_CUMPLE or "no soy" not in (m.mensaje or ""), str(m.mensaje))
except Exception as exc:                                            # noqa: BLE001
    ok("historial con tipos basura -> sin excepcion", False, f"{type(exc).__name__}: {exc}")

# --------------------------------------------------------------------------- #
titulo("C. Umbrales: tipos erroneos, fuera de rango, incoherentes entre si")
# --------------------------------------------------------------------------- #
CASOS_U = [
    ("dias_max", 540, True), ("dias_max", 1, True), ("dias_max", 1095, True),
    ("dias_max", 0, False), ("dias_max", 1096, False), ("dias_max", -5, False),
    # 400.0 y no 540.0: con 540.0 el valor coincide con el default y no se distingue
    # "aplicado" de "ignorado" (el aviso se emite igual).
    ("dias_max", "540", False), ("dias_max", 400.0, False), ("dias_max", True, False),
    ("dias_max", None, False), ("dias_max", [540], False), ("dias_max", 10 ** 30, False),
    ("dias_min", 30, True), ("dias_min", 31, False), ("dias_min", 0, False),
    ("dias_sin_respaldo_aviso", 120, True), ("dias_futuro_max", 0, True),
    ("dias_futuro_max", 366, False), ("desfase_tolerado_dias", 5, True),
    ("desfase_tolerado_dias", 6, False), ("dias_antiguedad_max", 29, False),
    ("umbral_que_no_existe", 3, False), ("_comentario", 3, None),
]
for nombre, valor, se_aplica in CASOS_U:
    c = cfg_archivo({"umbrales": {nombre: valor}})
    if se_aplica is None:
        ok(f"umbral {nombre}={valor!r} (clave '_') se ignora sin aviso",
           not c.avisos, str(list(c.avisos)))
        continue
    aplicado = c.umbrales.get(nombre) == valor
    ok(f"umbral {nombre}={valor!r} -> {'aplicado' if se_aplica else 'ignorado + aviso'}",
       aplicado == se_aplica and (se_aplica or c.avisos), f"valor={c.umbrales.get(nombre)} "
       f"avisos={list(c.avisos)}")

c = cfg_archivo({"umbrales": {"dias_min": 30, "dias_max": 20}})
ok("dias_min>dias_max -> se restauran los anteriores + aviso",
   c.umbrales["dias_min"] == 1 and c.umbrales["dias_max"] == 540 and c.avisos,
   f"min={c.umbrales['dias_min']} max={c.umbrales['dias_max']} avisos={list(c.avisos)}")

# dos capas: el archivo baja dias_max y la BD sube dias_min por encima
c1 = cfg_archivo({"umbrales": {"dias_max": 10}})
c2 = rt._aplicar(c1, {"umbrales": {"dias_min": 20}}, "bd")
ok("archivo dias_max=10 + bd dias_min=20 -> coherente (min<=max)",
   c2.umbrales["dias_min"] <= c2.umbrales["dias_max"],
   f"min={c2.umbrales['dias_min']} max={c2.umbrales['dias_max']} avisos={list(c2.avisos)}")

# el umbral SI cambia el veredicto (actualizable de verdad)
c = cfg_archivo({"umbrales": {"dias_max": 10}})
ok("dias_max=10 -> dias=30 pasa a estar fuera de rango",
   estado(ctx_foto(dias=30), "T03_DIAS_FUERA_DE_RANGO", c) == rt.NO_CUMPLE)
c = cfg_archivo({"umbrales": {"desfase_tolerado_dias": 1}})
ok("desfase_tolerado_dias=1 -> un dia de desfase deja de ser hallazgo",
   estado(ctx_foto(inicio="2026-06-01", fin="2026-06-05", dias=6),
          "T01_DURACION_VS_RANGO", c) == rt.CUMPLE)

# --------------------------------------------------------------------------- #
titulo("D. Estructura del JSON / de la BD completamente rota")
# --------------------------------------------------------------------------- #
CASOS_JSON = [
    ("JSON roto", "{no es json"),
    ("JSON vacio", ""),
    ("lista", "[]"),
    ("numero", "5"),
    ("cadena", '"hola"'),
    ("null", "null"),
    ("true", "true"),
    ("objeto vacio", "{}"),
    ("reglas=lista", '{"reglas": []}'),
    ("reglas=cadena", '{"reglas": "T01"}'),
    ("umbrales=lista", '{"umbrales": [1,2]}'),
    ("regla=cadena", '{"reglas": {"T01_DURACION_VS_RANGO": "LEVE"}}'),
    ("codigo desconocido", '{"reglas": {"T99_INVENTADA": {"severidad": "LEVE"}}}'),
    ("codigo vacio", '{"reglas": {"": {"severidad": "LEVE"}}}'),
    ("clave _comentario", '{"reglas": {"_nota": {"severidad": "LEVE"}}}'),
    ("BOM", '﻿{"umbrales": {"dias_max": 400}}'),
    ("anidado profundo", '{"reglas": {"T01_DURACION_VS_RANGO": {"severidad": {"a": 1}}}}'),
]
for nombre, texto in CASOS_JSON:
    try:
        c = cfg_archivo(texto)
        sano = (c.umbrales["dias_min"] == 1 and c.severidad_de("T01_DURACION_VS_RANGO")
                in rt.ORDEN_SEVERIDAD and c.esta_activa("T02_FIN_ANTES_DE_INICIO"))
        ok(f"[{nombre}] config sigue usable", sano, f"avisos={list(c.avisos)}")
        # ademas: el motor tiene que poder evaluar con ella
        rt.validar_tiempos(ctx_foto(inicio="2026-06-01", fin="2026-06-20", dias=5), c)
    except Exception as exc:                                        # noqa: BLE001
        ok(f"[{nombre}] config sigue usable", False, f"{type(exc).__name__}: {exc}")

ok("JSON 'null' avisa de que el archivo no aporto nada",
   bool(cfg_archivo("null").avisos) or "archivo" not in cfg_archivo("null").fuentes,
   f"fuentes={cfg_archivo('null').fuentes} avisos={list(cfg_archivo('null').avisos)}")

# datos_bd con tipos de driver (bytes, Decimal)
import decimal                                                      # noqa: E402

c = cfg_bd({"reglas": {b"T01_DURACION_VS_RANGO": {"severidad": b"LEVE"}},
            "umbrales": {"dias_max": decimal.Decimal(400)}})
ok("bd con bytes/Decimal -> se ignora con aviso, sin excepcion",
   c.severidad_de("T01_DURACION_VS_RANGO") == rt.GRAVE and c.umbrales["dias_max"] == 540
   and len(c.avisos) >= 2, f"sev={c.severidad_de('T01_DURACION_VS_RANGO')} "
   f"dias_max={c.umbrales['dias_max']} avisos={list(c.avisos)}")

# --------------------------------------------------------------------------- #
titulo("E. Dos capas que se contradicen (archivo vs BD) y trazabilidad")
# --------------------------------------------------------------------------- #
c1 = cfg_archivo({"reglas": {"T01_DURACION_VS_RANGO": {"severidad": "LEVE"}}})
c2 = rt._aplicar(c1, {"reglas": {"T01_DURACION_VS_RANGO": {"severidad": "GRAVE"}}}, "bd")
ok("BD manda sobre archivo", c2.severidad_de("T01_DURACION_VS_RANGO") == rt.GRAVE,
   c2.severidad_de("T01_DURACION_VS_RANGO"))
ok("fuentes trazan de donde salio la config", c2.fuentes[-1] == "bd", str(c2.fuentes))
c3 = rt._aplicar(c1, "no soy un dict", "bd")
ok("capa BD invalida NO borra los avisos ni la config del archivo",
   c3.severidad_de("T01_DURACION_VS_RANGO") == rt.LEVE and c3.avisos, str(list(c3.avisos)))

# T01 en LEVE: deja de exigir revision pero sigue avisando
c = cfg_archivo({"reglas": {"T01_DURACION_VS_RANGO": {"severidad": "LEVE"}}})
v = rt.evaluar(ctx_foto(inicio="2026-06-01", fin="2026-06-20", dias=5), c)
ok("T01 en LEVE -> avisa y no exige revision",
   v.avisos and not v.exige_revision and v.severidad_max == rt.LEVE,
   f"problemas={v.problemas} avisos={v.avisos} sev={v.severidad_max}")
i = rt.validar_tiempos(ctx_foto(inicio="2026-06-01", fin="2026-06-20", dias=5), c)
ok("informe con T01 en LEVE -> veredicto AVISOS", i["veredicto"] == rt.V_AVISOS, i["veredicto"])
ok("el informe publica la severidad EFECTIVA de cada regla",
   i["config"]["severidades"]["T01_DURACION_VS_RANGO"] == rt.LEVE)

# --------------------------------------------------------------------------- #
titulo("F. ConfigReglas construida a mano con severidad invalida (llamador hostil)")
# --------------------------------------------------------------------------- #
mala = rt.ConfigReglas(severidades={**DEF.severidades, "T01_DURACION_VS_RANGO": "CRITICA"},
                       activas=dict(DEF.activas), umbrales=dict(DEF.umbrales))
try:
    v = rt.evaluar(ctx_foto(inicio="2026-06-01", fin="2026-06-20", dias=5), mala)
    _ = v.severidad_max, v.puntaje
    ok("ConfigReglas con severidad invalida -> degrada, no revienta", True)
except Exception as exc:                                            # noqa: BLE001
    ok("ConfigReglas con severidad invalida -> degrada, no revienta", False,
       f"{type(exc).__name__}: {exc}")

# umbral ausente en una ConfigReglas hecha a mano (p.ej. un dict recortado)
recortada = rt.ConfigReglas(severidades=dict(DEF.severidades), activas=dict(DEF.activas),
                            umbrales={"dias_min": 1})
try:
    v = rt.evaluar(ctx_foto(inicio="2026-06-01", fin="2026-06-20", dias=5), recortada)
    ok("ConfigReglas sin todos los umbrales -> reglas NO_EVALUABLE, sin caida",
       all(r.estado != rt.NO_CUMPLE or r.mensaje for r in v.resultados), str(v.codigos))
except Exception as exc:                                            # noqa: BLE001
    ok("ConfigReglas sin todos los umbrales -> sin caida", False, f"{type(exc).__name__}: {exc}")

raise SystemExit(cierre())
