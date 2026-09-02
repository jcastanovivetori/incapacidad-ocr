"""Barrido 5 — falsos positivos por LECTURA (rótulo↔valor) y por SOLAPE de módulos.

Parte 1 — el confusor documentado del corpus: sin coordenadas del OCR el pipeline empareja
rótulo y valor por ORDEN DEL TEXTO, y hay formatos reales donde el valor va ANTES de su
rótulo (R04) o donde las celdas de fecha salen partidas y desordenadas (formato SURA:
`extract._fecha_inicio_fin_escrita` empareja día+mes con año POR POSICIÓN). Cuando eso
pasa, el motor recibe una tripleta bien formada pero MAL ATRIBUIDA y T01/T02 (las dos
GRAVES) acusan a un documento legítimo. Se reproduce con textos sintéticos que copian el
layout medido en `senales/aritmetica_fechas/INFORME.md` §4.

Parte 2 — `authenticity` trae su PROPIA versión del cruce días↔rango
(`_revisar_consistencia_fechas_dias`) que también llega al auxiliar por `problemas` y
además pone `estado=POSIBLE_MANIPULACION`. Se comprueba si los 16 documentos legítimos
disparan esa vía (y si puede duplicar el mensaje de T01).
"""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from _comun import cargar_docs, evaluar_doc, registro_como_processor, reglas_tiempo

from incapacidad_ocr import authenticity

AQUI = Path(__file__).resolve().parent
HOY = date(2026, 9, 2)


# --------------------------------------------------------------------------- #
# Parte 1 — layouts reales que desordenan rótulo y valor
# --------------------------------------------------------------------------- #
# (a) Formato "Clínica Medical" (R04, 38f40c48): CADA valor PRECEDE a su rótulo.
#     Copiado del texto OCR real, con datos sintéticos y con la celda de días RELLENA
#     (en el documento real quedó vacía y por eso hoy T01 no llega a opinar).
LAYOUT_VALOR_ANTES = (
    "CLINICAMEDICALS.A.S.\nINCAPACIDADEXTRAHOSPITALARIA\n"
    "Nombre del Paciente:\nNOMBRE DEMO\nCC\n1111111111\n"
    "Dx Principal de Egreso:\nS80.1\nCONTUSION DEMO\n"
    "Presunto origen de la incapacidad:\nComun\nProrroga:No\n"
    "2\n"                               # <- la celda de días, ANTES de su rótulo
    "Dias de Incapacidad:\n"
    "11/7/2026\n"                       # <- el valor del INICIO, antes de su rótulo
    "Fecha de Inicio de Incapacidad:\n"
    "12/7/2026\n"                       # <- el valor del FIN, antes de su rótulo
    "Fecha Fin de Incapacidad:\n"
    "Nombre del Medico:\nMEDICO DEMO\n"
)

# (b) Formato SURA con las celdas de fecha en el orden en que el OCR las emitió en el
#     documento F04 del corpus (la fecha MAYOR primero). Datos sintéticos; el documento
#     es LEGÍTIMO: 10 → 23 de julio, 14 días.
LAYOUT_SURA_CELDAS_INVERTIDAS = (
    "EPS\nsura\nEPS SURAMERICANA S.A.800088702\nCERTIFICADO DE INCAPACIDAD\n"
    "CC\nAfiliado\n1111111111 NOMBRE DEMO\n"
    "Diagnostico principal\nM545\nOrigen\nENFERMEDAD GENERAL\n"
    "Fecha P.P\nFecha Inicio\n"
    "JUEVES 23 DE JULIO\n"              # <- la celda del FIN sale PRIMERO
    "Fecha Fin\nDuracion\n"
    "VIERNES 10 DEJULIO\n"              # <- la celda del INICIO sale DESPUES
    "DE 2026\nDE 2026\n"
    "INFORMACION DEL PROFESIONAL\nProfesional\nCC - CED-23 MEDICO DEMO\n"
)

# (c) El mismo formato SURA pero cruzando el fin de año: los AÑOS se emparejan por
#     posición, así que si el OCR emite el año del fin primero el rango se invierte.
LAYOUT_SURA_FIN_DE_ANIO = (
    "EPS\nsura\nCERTIFICADO DE INCAPACIDAD\n"
    "CC\nAfiliado\n1111111111 NOMBRE DEMO\n"
    "Diagnostico principal\nM545\nOrigen\nENFERMEDAD GENERAL\n"
    "Fecha Inicio\n"
    "LUNES 28 DE DICIEMBRE\n"
    "Fecha Fin\n"
    "DOMINGO 03 DE ENERO\n"
    "DE 2027\nDE 2026\n"                # <- los dos años, en el orden CONTRARIO
    "INFORMACION DEL PROFESIONAL\nProfesional\nMEDICO DEMO\n"
)

# (d) Documento que imprime las fechas en orden mm/dd/aaaa (software en inglés). Los dos
#     días son <= 12, así que las dos fechas se leen "bien formadas" pero con el mes y el
#     día intercambiados: 10 de julio -> 7 de octubre.
LAYOUT_MMDD = (
    "MEDICAL CERTIFICATE / CERTIFICADO DE INCAPACIDAD\nIPS DEMO\n"
    "Paciente: NOMBRE DEMO  CC 1111111111\n"
    "Fecha Inicio Incapacidad: 07/10/2026\n"
    "Fecha Fin Incapacidad: 07/12/2026\n"
    "Dias de Incapacidad: 3\n"
    "Diagnostico: M545\n"
)

CASOS_LAYOUT = [
    ("P1_VALOR_ANTES_DEL_ROTULO", LAYOUT_VALOR_ANTES,
     "inicio real 2026-07-11, fin real 2026-07-12, 2 dias (documento coherente)"),
    ("P2_SURA_CELDAS_INVERTIDAS", LAYOUT_SURA_CELDAS_INVERTIDAS,
     "inicio real 2026-07-10, fin real 2026-07-23, 14 dias (documento coherente)"),
    ("P3_SURA_FIN_DE_ANIO", LAYOUT_SURA_FIN_DE_ANIO,
     "inicio real 2026-12-28, fin real 2027-01-03 (documento coherente)"),
    ("P4_FECHAS_MMDD", LAYOUT_MMDD,
     "inicio real 2026-07-10, fin real 2026-07-12, 3 dias (documento coherente)"),
]


def parte1() -> list[dict]:
    print(f"\n{'='*100}\nPARTE 1 — rótulo↔valor sin coordenadas del OCR\n{'='*100}")
    filas = []
    for cid, texto, verdad in CASOS_LAYOUT:
        rec = registro_como_processor(texto)
        inca = rec.get("incapacidad") or {}
        snap = inca.get(reglas_tiempo.CLAVE_SNAPSHOT) or {}
        res = evaluar_doc(rec, HOY)
        ver = res["veredicto"]
        marca = "FP!" if ver.exige_revision else "ok "
        print(f"\n[{marca}] {cid}")
        print(f"  documento (verdad): {verdad}")
        print(f"  el pipeline LEYO:   inicio={snap.get('fecha_inicio')} fin={snap.get('fecha_fin')} "
              f"dias={snap.get('dias')}")
        print(f"  fila EFECTIVA:      inicio={inca.get('fecha_inicio')} fin={inca.get('fecha_fin')} "
              f"dias={inca.get('dias')}")
        print(f"  veredicto={res['informe']['veredicto']} sev={ver.severidad_max}")
        for h in ver.hallazgos:
            print(f"    !! {h.severidad:5} {h.codigo}: {h.mensaje}")
        filas.append({"caso": cid, "verdad": verdad, "leido": snap,
                      "efectivo": {k: inca.get(k) for k in ("fecha_inicio", "fecha_fin", "dias")},
                      "codigos": ver.codigos, "severidad": ver.severidad_max,
                      "exige_revision": ver.exige_revision,
                      "mensajes": [h.mensaje for h in ver.hallazgos]})
    return filas


# --------------------------------------------------------------------------- #
# Parte 2 — la segunda implementación del mismo cruce, en `authenticity`
# --------------------------------------------------------------------------- #
def parte2() -> list[dict]:
    print(f"\n{'='*100}\nPARTE 2 — `authenticity` y su propio cruce dias↔rango\n{'='*100}")
    filas = []
    for doc in cargar_docs():
        rec = registro_como_processor(doc["texto_plano"])
        # Igual que processor.run: la autenticidad se calcula DESPUES de normalizar_fechas.
        per = authenticity._revisar_periodos_multiples(doc["texto_plano"])
        coh = authenticity._revisar_consistencia_fechas_dias(rec)
        res = evaluar_doc(rec, HOY)
        if per["sospechosa"] or coh["sospechosa"] or res["veredicto"].hallazgos:
            print(f"\n[{doc['id']} {doc['sha8']}] {doc['archivo']}")
            if per["sospechosa"]:
                print(f"  periodos_multiples: {per['motivo']}")
            if coh["sospechosa"]:
                print(f"  authenticity dias<->rango: {coh['motivo']}")
            for h in res["veredicto"].hallazgos:
                print(f"  motor tiempos: {h.severidad} {h.codigo}: {h.mensaje}")
        filas.append({"id": doc["id"], "sha8": doc["sha8"],
                      "periodos_multiples": per["sospechosa"],
                      "motivo_periodos": per["motivo"],
                      "authenticity_fechas_dias": coh["sospechosa"],
                      "motivo_authenticity": coh["motivo"],
                      "codigos_motor": res["veredicto"].codigos})
    marcados = [f["id"] for f in filas if f["periodos_multiples"] or f["authenticity_fechas_dias"]]
    print(f"\nLEGITIMOS marcados por `authenticity` (via temporal): {len(marcados)} -> {marcados}")

    # ¿Los dos módulos pueden hablar a la vez del MISMO problema?
    print("\n-- ¿mensaje duplicado? registro con la tripleta incoherente y foto presente --")
    inca = {"fecha_inicio": "2026-06-05", "fecha_fin": "2026-07-06", "dias": 2,
            reglas_tiempo.CLAVE_SNAPSHOT: {"fecha_inicio": "2026-06-05",
                                           "fecha_fin": "2026-07-06", "dias": 2,
                                           "dias_letra": None}}
    coh = authenticity._revisar_consistencia_fechas_dias({"incapacidad": inca})
    ctx = reglas_tiempo.construir_contexto(inca, hoy=HOY)
    ver = reglas_tiempo.evaluar(ctx, reglas_tiempo.config_por_defecto())
    print(f"  authenticity: {coh['motivo']}")
    for h in ver.hallazgos:
        print(f"  motor:        {h.codigo}: {h.mensaje}")
    # Y el desacuerdo de tolerancia entre las dos implementaciones (off-by-one).
    print("\n-- desacuerdo de TOLERANCIA (desfase de 1 día, el caso F04 del corpus) --")
    inca1 = {"fecha_inicio": "2025-09-02", "fecha_fin": "2025-09-04", "dias": 2,
             reglas_tiempo.CLAVE_SNAPSHOT: {"fecha_inicio": "2025-09-02",
                                            "fecha_fin": "2025-09-04", "dias": 2,
                                            "dias_letra": 2}}
    coh1 = authenticity._revisar_consistencia_fechas_dias({"incapacidad": inca1})
    ver1 = reglas_tiempo.evaluar(reglas_tiempo.construir_contexto(inca1, hoy=date(2025, 9, 5)),
                                 reglas_tiempo.config_por_defecto())
    print(f"  authenticity sospechosa={coh1['sospechosa']} (tolerancia ±1)")
    print(f"  motor        codigos={ver1.codigos} (desfase_tolerado_dias=0)")
    filas.append({"caso": "duplicado", "authenticity": coh["motivo"],
                  "motor": [h.mensaje for h in ver.hallazgos],
                  "offbyone_authenticity": coh1["sospechosa"],
                  "offbyone_motor": ver1.codigos})
    return filas


def main() -> None:
    salida = {"parte1_layout": parte1(), "parte2_solape": parte2()}
    (AQUI / "resultados_lectura_y_solapes.json").write_text(
        json.dumps(salida, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    print(f"\n-> {AQUI / 'resultados_lectura_y_solapes.json'}")


if __name__ == "__main__":
    main()
