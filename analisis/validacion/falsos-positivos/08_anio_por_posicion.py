"""Barrido 8 — el AÑO emparejado por posición (formato SURA / fecha escrita en palabras).

`extract._fecha_inicio_fin_escrita` (extract.py:151-175) recupera las dos fechas de un
certificado que las imprime en palabras así:

    dm    = _FECHA_DM_ESCRITA.findall(text)          # [(10,'JULIO'), (23,'JULIO')]
    years = re.findall(r"(?i)\\bDE\\s*(\\d{4})\\b", text)   # ['2026', '2026']
    zip(dm[:2], years[:2])

Los años se buscan en TODO el texto y se emparejan por ORDEN DE APARICIÓN, sin exigir
cercanía a la fecha a la que pertenecen. Cualquier `DE <4 dígitos>` que el OCR devuelva
ANTES de las celdas de fecha desplaza el emparejamiento — y los certificados de EPS citan
resoluciones y decretos con año ("Resolución 2388 DE 2016").

Consecuencia: el documento es LEGÍTIMO y el motor lo marca GRAVE (T04: el rango dura años),
o —peor— los dos años se desplazan a la vez, la fila queda con fechas de otra década y
NINGUNA regla puede verlo (la tripleta es coherente entre sí).

Parte 2: se mide, sobre los 16 documentos legítimos, cuántos años sueltos hay antes de las
celdas (a cuánto está el defecto de activarse por sí solo).
"""
from __future__ import annotations

import json
import re
from datetime import date
from pathlib import Path

from _comun import cargar_docs, evaluar_doc, registro_como_processor, reglas_tiempo

import incapacidad_ocr.extract as ex

AQUI = Path(__file__).resolve().parent
HOY = date(2026, 9, 2)

# Certificado SURA LEGÍTIMO: 10/07/2026 → 23/07/2026, 14 días. Lo único que cambia es si
# el pie legal con un año cae ANTES o DESPUÉS de las celdas de fecha.
BASE = ("EPS\nsura\nCERTIFICADO DE INCAPACIDAD\n"
        "CC\nAfiliado\n1111111111 NOMBRE DEMO\n"
        "Diagnostico principal\nM545\nOrigen\nENFERMEDAD GENERAL\n"
        "{pie_arriba}"
        "Fecha Inicio\nVIERNES 10 DEJULIO\nFecha Fin\n"
        "JUEVES 23 DE JULIO\nDE 2026\nDE 2026\n"
        "INFORMACION DEL PROFESIONAL\nProfesional\nMEDICO DEMO\n"
        "{pie_abajo}")

CASOS = [
    ("P5a_sin_pie_legal", "", "", "control: sin ningun 'DE <anio>' extra"),
    ("P5b_resolucion_ANTES", "Expedido conforme a la Resolucion 2388 DE 2016\n", "",
     "el pie legal sale ANTES de las celdas: el anio del INICIO se toma de la resolucion"),
    ("P5c_resolucion_DESPUES", "", "Expedido conforme a la Resolucion 2388 DE 2016\n",
     "el mismo pie DESPUES: no molesta (zip toma los dos primeros)"),
    ("P5d_dos_anios_ANTES", "Resolucion 2388 DE 2016 y Decreto 780 DE 2016\n", "",
     "dos anios extra: las DOS fechas se van a 2016 y la tripleta queda coherente entre "
     "si -> ninguna regla puede verlo, la fila entra con 10 anios de error"),
]


def parte1() -> list[dict]:
    print(f"\n{'='*100}\nPARTE 1 — el pie legal con año desplaza el emparejamiento\n{'='*100}")
    print("Documento LEGITIMO en las cuatro variantes: 10/07/2026 -> 23/07/2026 = 14 dias\n")
    filas = []
    for cid, arriba, abajo, nota in CASOS:
        texto = BASE.format(pie_arriba=arriba, pie_abajo=abajo)
        rec = registro_como_processor(texto)
        inca = rec["incapacidad"]
        snap = inca[reglas_tiempo.CLAVE_SNAPSHOT]
        res = evaluar_doc(rec, HOY)
        ver = res["veredicto"]
        # ¿la fila queda con datos correctos, aunque el motor no diga nada?
        fila_ok = (inca.get("fecha_inicio") == "2026-07-10"
                   and inca.get("fecha_fin") == "2026-07-23" and inca.get("dias") == 14)
        marca = "FP!" if ver.exige_revision else ("ok " if fila_ok else "MAL")
        print(f"[{marca}] {cid}: {nota}")
        print(f"      LEIDO inicio={snap['fecha_inicio']} fin={snap['fecha_fin']} dias={snap['dias']}")
        print(f"      FILA  inicio={inca['fecha_inicio']} fin={inca['fecha_fin']} "
              f"dias={inca['dias']}  (correcta={fila_ok})")
        for h in ver.hallazgos:
            print(f"      !! {h.severidad} {h.codigo}: {h.mensaje}")
        print()
        filas.append({"caso": cid, "nota": nota, "leido": snap,
                      "fila": {k: inca.get(k) for k in ("fecha_inicio", "fecha_fin", "dias")},
                      "fila_correcta": fila_ok, "codigos": ver.codigos,
                      "exige_revision": ver.exige_revision,
                      "mensajes": [h.mensaje for h in ver.hallazgos]})
    return filas


def parte2() -> list[dict]:
    print(f"\n{'='*100}\nPARTE 2 — ¿cuántos 'DE <año>' sueltos trae cada documento legítimo?"
          f"\n{'='*100}")
    filas = []
    for doc in cargar_docs():
        t = doc["texto_plano"]
        ancla = bool(re.search(r"(?i)fecha\s*[il]nici\w*", t))
        dm = ex._FECHA_DM_ESCRITA.findall(t)
        years = re.findall(r"(?i)\bDE\s*(\d{4})\b", t)
        usa_via = ancla and len(dm) >= 2 and len(years) >= 2
        print(f"  {doc['id']} {doc['sha8']}  ancla_fecha_inicio={int(ancla)}  "
              f"parejas_dia_mes={len(dm)}  anios_'DE nnnn'={len(years)}  "
              f"{'<-- usa la via de fecha escrita' if usa_via else ''}")
        filas.append({"id": doc["id"], "sha8": doc["sha8"], "ancla": ancla,
                      "dm": len(dm), "years": len(years), "usa_via": usa_via,
                      "years_valores": years[:4]})
    return filas


def main() -> None:
    salida = {"parte1": parte1(), "parte2": parte2()}
    (AQUI / "resultados_anio_por_posicion.json").write_text(
        json.dumps(salida, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    print(f"\n-> {AQUI / 'resultados_anio_por_posicion.json'}")


if __name__ == "__main__":
    main()
