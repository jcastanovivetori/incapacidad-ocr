"""Barrido 4 — falsos positivos que NO vienen del OCR.

Tres familias:

A) **Alcance real de cada regla.** `extract` normaliza o descarta el dato ANTES de que
   `processor` tome la foto (`_norm_date` devuelve None ante `31/02/2026`;
   `_dias_por_etiqueta`/`_dias_de_celda`/`_days_between` acotan a 1..540). Se comprueba,
   regla por regla, si puede llegar a NO_CUMPLE por el camino del documento.

B) **Correcciones del auxiliar (`overrides`).** Es evidencia humana y el motor la juzga
   igual. Interesa (1) que no aparezca un mensaje doble con el de `erp`, (2) que corregir
   un campo no dispare una regla sobre el valor VIEJO de otro.

C) **Registro sin la foto de `processor`** (`CLAVE_SNAPSHOT`): T11 es GRAVE y su premisa
   es "el fin original no quedó registrado". ¿Qué caminos de producción llegan así?

Al final se comprueba que las correcciones propuestas son un cambio de CONFIGURACIÓN
(sin desplegar), como exige el requisito (4) del cliente.
"""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from _comun import evaluar_doc, registro_como_processor, reglas_tiempo

from incapacidad_ocr import erp

AQUI = Path(__file__).resolve().parent
HOY = date(2026, 9, 2)
CFG = reglas_tiempo.config_por_defecto()


def _ctx(inca: dict, overrides: dict | None = None, hoy: date = HOY):
    return reglas_tiempo.construir_contexto(inca, hoy=hoy, overrides=overrides or {})


def _ev(inca: dict, overrides: dict | None = None, hoy: date = HOY, cfg=None):
    ctx = _ctx(inca, overrides, hoy)
    return reglas_tiempo.evaluar(ctx, cfg or CFG), ctx


def seccion(titulo: str) -> None:
    print(f"\n{'='*100}\n{titulo}\n{'='*100}")


# --------------------------------------------------------------------------- #
# A) ¿Qué reglas pueden disparar por el camino del DOCUMENTO?
# --------------------------------------------------------------------------- #
TEXTOS_SONDA = {
    # Fecha imposible impresa: el documento SÍ la imprime, el pipeline la descarta.
    "fecha_imposible": ("CERTIFICADO DE INCAPACIDAD\nIPS DEMO\nPaciente: NOMBRE DEMO\n"
                        "Fecha Inicio Incapacidad: 31/02/2026\n"
                        "Fecha Fin Incapacidad: 05/13/2026\n"
                        "Dias de Incapacidad: 3\n"),
    # Días fuera de rango impresos.
    "dias_0": ("CERTIFICADO DE INCAPACIDAD\nIPS DEMO\nDias de Incapacidad: 0\n"
               "Fecha Inicio Incapacidad: 20/08/2026\n"),
    "dias_900": ("CERTIFICADO DE INCAPACIDAD\nIPS DEMO\nDias de Incapacidad: 900\n"
                 "Fecha Inicio Incapacidad: 20/08/2026\n"),
    # Días en letras que el lector no puede convertir a entero.
    "dias_palabra_rara": ("CERTIFICADO DE INCAPACIDAD\nIPS DEMO\n"
                          "Dias de Incapacidad: DOSCIENTOS CINCUENTA Y OCHO\n"
                          "Fecha Inicio Incapacidad: 20/08/2026\n"),
}


def a_alcance_reglas() -> list[dict]:
    seccion("A) ¿Puede cada regla llegar a NO_CUMPLE por el camino del DOCUMENTO?")
    filas = []
    for nombre, texto in TEXTOS_SONDA.items():
        rec = registro_como_processor(texto)
        inca = rec.get("incapacidad") or {}
        snap = inca.get(reglas_tiempo.CLAVE_SNAPSHOT) or {}
        res = evaluar_doc(rec, HOY)
        ver = res["veredicto"]
        print(f"\n[{nombre}]")
        print(f"  FOTO leida: inicio={snap.get('fecha_inicio')!r} fin={snap.get('fecha_fin')!r} "
              f"dias={snap.get('dias')!r} letra={snap.get('dias_letra')!r}")
        print(f"  hallazgos: {[h.codigo for h in ver.hallazgos] or '-'}   "
              f"veredicto={res['informe']['veredicto']}")
        filas.append({"sonda": nombre, "foto": snap, "codigos": ver.codigos})
    return filas


# --------------------------------------------------------------------------- #
# B) Correcciones del auxiliar
# --------------------------------------------------------------------------- #
def b_overrides() -> list[dict]:
    seccion("B) Correcciones del auxiliar (overrides) — ¿mensaje doble? ¿regla sobre el "
            "valor viejo?")
    filas = []

    def caso(titulo: str, inca: dict, overrides: dict, espera: str) -> None:
        mapeo = erp.mapear_a_staging({"incapacidad": {"incapacidad": inca}}, "WHATSAPP",
                                     erp.LookupsNulos(), hoy=HOY, overrides=overrides)
        cods = mapeo["row"].get("alertas_tiempos")
        print(f"\n[{titulo}]")
        print(f"  overrides={overrides}")
        print(f"  alertas_tiempos={cods}  severidad={mapeo['row'].get('severidad_tiempos')}")
        for p in mapeo["problemas"]:
            print(f"    - {p}")
        print(f"  FILA fechainicio={mapeo['row'].get('fechainicio')} "
              f"venc={mapeo['row'].get('fechavencimiento')} dias={mapeo['row'].get('Numerodias')}")
        print(f"  esperado: {espera}")
        filas.append({"caso": titulo, "overrides": overrides, "alertas": cods,
                      "problemas": mapeo["problemas"],
                      "fila": {k: mapeo["row"].get(k) for k in
                               ("fechainicio", "fechavencimiento", "Numerodias",
                                "fechafin_leida", "dias_leidos")}})

    # B1 — el documento imprimía inicio+fin y los días se DERIVARON de esas dos fechas;
    #      el auxiliar corrige SOLO la fecha fin (el OCR había leído mal el día).
    inca_b1 = {
        "fecha_inicio": "2026-08-20", "fecha_fin": "2026-08-28", "dias": 9,
        "fecha_inicio_calculada": False, "fecha_fin_recalculada": False,
        reglas_tiempo.CLAVE_SNAPSHOT: {"fecha_inicio": "2026-08-20", "fecha_fin": "2026-08-28",
                                       "dias": 9, "dias_letra": None},
    }
    caso("B1 corrige SOLO fecha_fin (los dias venian derivados del fin viejo)",
         inca_b1, {"fecha_fin": "2026-08-22"},
         "los dias deberian recalcularse a 3; si no, T01 acusa al DOCUMENTO de algo que "
         "hizo la correccion")

    # B2 — el auxiliar teclea un número de días imposible (dedo).
    inca_b2 = {"fecha_inicio": "2026-08-20", "fecha_fin": "2026-08-22", "dias": 3,
               reglas_tiempo.CLAVE_SNAPSHOT: {"fecha_inicio": "2026-08-20",
                                              "fecha_fin": "2026-08-22", "dias": 3,
                                              "dias_letra": None}}
    caso("B2 teclea dias=0", inca_b2, {"dias": 0},
         "T03 (GRAVE) explica el 0 y erp NO debe repetir 'Numero de dias fuera de rango'")
    caso("B3 teclea dias='dos'", inca_b2, {"dias": "dos"},
         "T05 (MEDIA) explica que no es un entero; erp no debe decir 'no se detecto'")
    caso("B4 teclea fecha_inicio='2026-02-31'", inca_b2, {"fecha_inicio": "2026-02-31"},
         "T06 (MEDIA) explica la fecha imposible; la fila queda con la fecha valida y NO "
         "debe escribirse la imposible")
    caso("B5 teclea fecha_fin anterior al inicio", inca_b2, {"fecha_fin": "2026-08-18"},
         "T02 (GRAVE) explica el rango imposible (una sola vez)")

    # B6 — la palabra del documento contra el dígito corregido por el auxiliar.
    inca_b6 = {"fecha_inicio": "2026-08-20", "fecha_fin": "2026-08-28", "dias": 9,
               "dias_letra": 3,
               reglas_tiempo.CLAVE_SNAPSHOT: {"fecha_inicio": "2026-08-20",
                                              "fecha_fin": "2026-08-22", "dias": 9,
                                              "dias_letra": 3}}
    caso("B6 el papel dice TRES (3) y el OCR leyo 9; el auxiliar corrige dias=3",
         inca_b6, {"dias": 3}, "T12 y T01 deben CUMPLIR tras la correccion")
    return filas


# --------------------------------------------------------------------------- #
# C) Registro SIN la foto de processor  →  T11 (GRAVE)
# --------------------------------------------------------------------------- #
def c_sin_foto() -> list[dict]:
    seccion("C) Registro sin la foto de `processor` (CLAVE_SNAPSHOT) → T11 GRAVE")
    filas = []
    # Registro tal como lo devolvía el pipeline ANTES de que existiera la foto (y tal como
    # lo puede mandar cualquier cliente de /api/mapear o /api/revisar): el fin ya está
    # re-derivado y solo queda la marca.
    inca = {"fecha_inicio": "2026-08-20", "fecha_fin": "2026-08-22", "dias": 3,
            "fecha_inicio_calculada": False, "fecha_fin_recalculada": True}
    ver, ctx = _ev(inca)
    print(f"  sin foto  -> fin_perdido={ctx.fin_perdido}  hallazgos={ver.codigos} "
          f"severidad={ver.severidad_max}")
    for h in ver.hallazgos:
        print(f"    !! {h.severidad} {h.codigo}: {h.mensaje}")
    filas.append({"caso": "sin_foto_fin_recalculada", "codigos": ver.codigos,
                  "severidad": ver.severidad_max})

    # El MISMO documento con la foto: el hallazgo pasa a ser T01, que sí cita los valores.
    inca2 = dict(inca)
    inca2[reglas_tiempo.CLAVE_SNAPSHOT] = {"fecha_inicio": "2026-08-20",
                                           "fecha_fin": "2026-08-25", "dias": 3,
                                           "dias_letra": None}
    ver2, _ = _ev(inca2)
    print(f"\n  con foto  -> hallazgos={ver2.codigos}")
    for h in ver2.hallazgos:
        print(f"    !! {h.severidad} {h.codigo}: {h.mensaje}")
    filas.append({"caso": "con_foto", "codigos": ver2.codigos, "severidad": ver2.severidad_max})

    # ¿Y un registro legítimo re-mapeado dos veces? (el segundo re-mapeo parte de la fila,
    # no del JSON: es el escenario del integrador que solo guardó la fila).
    inca3 = {"fecha_inicio": "2026-08-20", "fecha_fin": "2026-08-22", "dias": 3,
             "fecha_inicio_calculada": False, "fecha_fin_recalculada": False}
    ver3, _ = _ev(inca3)
    print(f"\n  sin foto y sin marcas (fila re-mapeada) -> hallazgos={ver3.codigos}")
    filas.append({"caso": "sin_foto_sin_marcas", "codigos": ver3.codigos})
    return filas


# --------------------------------------------------------------------------- #
# D) Las correcciones propuestas son configuración, no código
# --------------------------------------------------------------------------- #
def d_correcciones_por_config() -> list[dict]:
    seccion("D) Las correcciones propuestas se aplican SIN desplegar (config en caliente)")
    filas = []
    # D1 — vacaciones/prelicencia futuras: subir `dias_futuro_max`.
    inca_fut = {"fecha_inicio": "2026-10-17", "fecha_fin": "2026-11-01", "dias": 16,
                reglas_tiempo.CLAVE_SNAPSHOT: {"fecha_inicio": "2026-10-17",
                                               "fecha_fin": "2026-11-01", "dias": 16,
                                               "dias_letra": None}}
    for umbral in (30, 120):
        cfg = reglas_tiempo._aplicar(reglas_tiempo.config_por_defecto(),
                                     {"umbrales": {"dias_futuro_max": umbral}}, "prueba")
        ver, _ = _ev(inca_fut, cfg=cfg)
        print(f"  dias_futuro_max={umbral:4} -> {ver.codigos or '-'} (sev {ver.severidad_max})")
        filas.append({"caso": f"dias_futuro_max={umbral}", "codigos": ver.codigos})
    # D1b — o bajar T09 a LEVE (deja de bloquear, sigue avisando).
    cfg = reglas_tiempo._aplicar(reglas_tiempo.config_por_defecto(),
                                 {"reglas": {"T09_INICIO_EN_FUTURO": {"severidad": "LEVE"}}},
                                 "prueba")
    ver, _ = _ev(inca_fut, cfg=cfg)
    print(f"  T09 severidad=LEVE      -> {ver.codigos} exige_revision={ver.exige_revision}")
    filas.append({"caso": "T09=LEVE", "codigos": ver.codigos, "exige_revision": ver.exige_revision})

    # D2 — emisor no inclusivo: tolerancia de 1 día en T01.
    inca_ni = {"fecha_inicio": "2026-08-20", "fecha_fin": "2026-08-23", "dias": 3,
               reglas_tiempo.CLAVE_SNAPSHOT: {"fecha_inicio": "2026-08-20",
                                              "fecha_fin": "2026-08-23", "dias": 3,
                                              "dias_letra": None}}
    for tol in (0, 1):
        cfg = reglas_tiempo._aplicar(reglas_tiempo.config_por_defecto(),
                                     {"umbrales": {"desfase_tolerado_dias": tol}}, "prueba")
        ver, _ = _ev(inca_ni, cfg=cfg)
        print(f"  desfase_tolerado_dias={tol} -> {ver.codigos or '-'} (sev {ver.severidad_max})")
        filas.append({"caso": f"desfase_tolerado_dias={tol}", "codigos": ver.codigos})
    print("  NOTA: con tolerancia 1 se pierde el UNICO acierto propio de la familia de "
          "aritmetica del corpus (F04, desfase +1) -> no es la correccion recomendada.")

    # D3 — T08 sobre una incapacidad larga sin fin: subir el umbral.
    inca_larga = {"fecha_inicio": "2026-02-01", "fecha_fin": None, "dias": 210,
                  reglas_tiempo.CLAVE_SNAPSHOT: {"fecha_inicio": "2026-02-01",
                                                 "fecha_fin": None, "dias": 210,
                                                 "dias_letra": None}}
    for umbral in (180, 365):
        cfg = reglas_tiempo._aplicar(reglas_tiempo.config_por_defecto(),
                                     {"umbrales": {"dias_sin_respaldo_aviso": umbral}}, "prueba")
        ver, _ = _ev(inca_larga, cfg=cfg)
        print(f"  dias_sin_respaldo_aviso={umbral} -> {ver.codigos or '-'}")
        filas.append({"caso": f"dias_sin_respaldo_aviso={umbral}", "codigos": ver.codigos})
    return filas


def main() -> None:
    salida = {"A_alcance": a_alcance_reglas(), "B_overrides": b_overrides(),
              "C_sin_foto": c_sin_foto(), "D_config": d_correcciones_por_config()}
    (AQUI / "resultados_caminos_no_ocr.json").write_text(
        json.dumps(salida, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    print(f"\n-> {AQUI / 'resultados_caminos_no_ocr.json'}")


if __name__ == "__main__":
    main()
