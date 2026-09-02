"""Barrido 6 — dos remates del frente.

Parte 1 — el respaldo histórico de duración sigue leyendo el DÍA DEL MES.
`extract._dias_por_etiqueta` (extract.py:330) cae, cuando `numeros_es` no encuentra nada
anclado, al patrón `duraci[oó]n\\b[^\\d]{0,10}` + `_NUM_DIAS`. En el formato SURA el rótulo
`Duracion` queda pegado a la celda de la fecha ESCRITA, cuyo día del mes es un número de 1-2
cifras suelto: exactamente lo que `_NUM_DIAS` deja pasar. El corpus ya midió este defecto
(R16: `dias = 202` de `"Duracion\\nDE2026"`, `senales/aritmetica_fechas/INFORME.md` §3.2);
hoy R16 se salva por 1 carácter. Se mide qué pasa cuando el OCR deja 10 caracteres o menos
entre el rótulo y el día del mes: el número de días queda mal y la GRAVE T01 acusa al papel.

Parte 2 — ¿es alcanzable la SEGUNDA implementación del cruce días↔rango
(`authenticity._revisar_consistencia_fechas_dias`)? Se ejecuta el orden REAL de
`processor.run()` (normalizar_fechas ANTES de la autenticidad) sobre los 31 documentos del
corpus y se cuenta cuántas veces dispara.
"""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from _comun import (CARPETAS_FALSAS, CARPETAS_REALES, cargar_docs, evaluar_doc,
                    registro_como_processor, reglas_tiempo)

import incapacidad_ocr.extract as ex
from incapacidad_ocr import authenticity

AQUI = Path(__file__).resolve().parent
HOY = date(2026, 9, 2)

# Formato SURA legítimo: 10 → 23 de julio (14 días). Lo único que cambia entre las
# variantes es CUÁNTOS caracteres deja el OCR entre el rótulo "Duracion" y el siguiente
# número, que es el DÍA DEL MES de la otra celda de fecha.
SURA_BASE = (
    "EPS\nsura\nCERTIFICADO DE INCAPACIDAD\n"
    "CC\nAfiliado\n1111111111 NOMBRE DEMO\n"
    "Diagnostico principal\nM545\nOrigen\nENFERMEDAD GENERAL\n"
    "Fecha Inicio\nVIERNES 10 DEJULIO\n"
    "{medio}"
    "JUEVES 23 DE JULIO\nDE 2026\nDE 2026\n"
    "INFORMACION DEL PROFESIONAL\nProfesional\nMEDICO DEMO\n"
)
VARIANTES_SURA = [
    ("A_como_el_corpus", "Duracion\nFecha Fin\n",           # R07 real: 11 chars -> NO lee
     "el rotulo y el dia del mes quedan a 11 caracteres: el respaldo NO dispara (suerte)"),
    ("B_un_char_menos", "Duracion\nFechaFin\n",             # 10 chars -> SI lee
     "el OCR pega 'FechaFin' (una celda menos): 10 caracteres y el respaldo lee el dia del mes"),
    ("C_rotulo_pegado", "Duracion Fecha Fin ",              # 12 -> no
     "variante con espacios"),
    ("D_solo_rotulo", "Duracion\n",                         # 1 char -> SI lee
     "el OCR omite el rotulo 'Fecha Fin': el dia del mes queda pegado a 'Duracion'"),
]


def parte1() -> list[dict]:
    print(f"\n{'='*100}\nPARTE 1 — respaldo de 'Duracion' leyendo el DÍA DEL MES\n{'='*100}")
    print("Documento LEGITIMO en todas las variantes: 10/07/2026 -> 23/07/2026 = 14 dias\n")
    filas = []
    for cid, medio, nota in VARIANTES_SURA:
        texto = SURA_BASE.format(medio=medio)
        dias_etq, letra, _ = ex._dias_por_etiqueta(texto)
        rec = registro_como_processor(texto)
        inca = rec.get("incapacidad") or {}
        snap = inca.get(reglas_tiempo.CLAVE_SNAPSHOT) or {}
        res = evaluar_doc(rec, HOY)
        ver = res["veredicto"]
        marca = "FP!" if ver.exige_revision else "ok "
        print(f"[{marca}] {cid}: {nota}")
        print(f"       _dias_por_etiqueta -> {dias_etq!r}   FOTO dias={snap.get('dias')!r} "
              f"inicio={snap.get('fecha_inicio')} fin={snap.get('fecha_fin')}")
        print(f"       FILA inicio={inca.get('fecha_inicio')} fin={inca.get('fecha_fin')} "
              f"dias={inca.get('dias')}")
        for h in ver.hallazgos:
            print(f"       !! {h.severidad} {h.codigo}: {h.mensaje}")
        print()
        filas.append({"caso": cid, "nota": nota, "dias_etiqueta": dias_etq,
                      "foto": snap, "codigos": ver.codigos,
                      "exige_revision": ver.exige_revision,
                      "fila_dias": inca.get("dias"), "fila_fin": inca.get("fecha_fin")})
    return filas


def parte2() -> dict:
    print(f"\n{'='*100}\nPARTE 2 — alcance real de authenticity._revisar_consistencia_fechas_dias"
          f"\n{'='*100}")
    resumen = {"reales": [], "falsas": []}
    for clase, carpetas in (("reales", CARPETAS_REALES), ("falsas", CARPETAS_FALSAS)):
        for doc in cargar_docs(carpetas):
            rec = registro_como_processor(doc["texto_plano"])   # ya con normalizar_fechas
            coh = authenticity._revisar_consistencia_fechas_dias(rec)
            ver = evaluar_doc(rec, HOY)["veredicto"]
            resumen[clase].append({"id": doc["id"], "sha8": doc["sha8"],
                                   "authenticity": coh["sospechosa"],
                                   "motivo": coh["motivo"], "motor": ver.codigos})
    for clase in ("reales", "falsas"):
        n = sum(1 for f in resumen[clase] if f["authenticity"])
        con_motor = [f["id"] for f in resumen[clase] if f["motor"]]
        print(f"  {clase}: authenticity dispara en {n}/{len(resumen[clase])} documentos; "
              f"el motor de tiempos dispara en {len(con_motor)} -> {con_motor}")
    for clase in ("reales", "falsas"):
        for f in resumen[clase]:
            if f["authenticity"]:
                print(f"    [{f['id']}] {f['motivo']}")
    print("\n  Motivo: `processor.run()` llama a `normalizar_fechas()` (processor.py:57) ANTES "
          "de\n  `analizar_autenticidad()` (processor.py:60), y esa reconciliación RE-DERIVA la "
          "fecha fin\n  cuando no cuadra con los días -> el registro que recibe la señal ya es "
          "coherente.")
    return resumen


def main() -> None:
    salida = {"parte1_duracion": parte1(), "parte2_autenticidad": parte2()}
    (AQUI / "resultados_duracion_autenticidad.json").write_text(
        json.dumps(salida, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    print(f"\n-> {AQUI / 'resultados_duracion_autenticidad.json'}")


if __name__ == "__main__":
    main()
