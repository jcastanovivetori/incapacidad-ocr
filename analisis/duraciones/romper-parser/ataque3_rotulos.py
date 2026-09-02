"""Ataque 3: los ROTULOS de duracion y lo que dejan entrar.

- `dias?\\s*[:\\-]` acepta el SINGULAR "dia:" / "dia-", que en los formularios
  colombianos es SIEMPRE un campo de FECHA ("Dia: 27  Mes: 08  Ano: 2026").
- ningun rotulo tiene frontera de palabra por la izquierda ("MEDIAS:", "GUARDIAS:").
- el veto de contexto solo se aplica a la IZQUIERDA del rotulo, asi que la unidad
  equivocada ("4 HORAS", "3 meses") pasa entera.
- "mil" no esta en el lexico para que un anio no se lea; eso protege a
  `texto_a_entero`, pero NO a `duracion_en_texto`, que se queda con el fragmento.

Cada caso imprime la lectura del modulo y el `dias` que sale del extractor de
reglas (lo que viajaria a la fila staging).
"""
from __future__ import annotations

import sys
from pathlib import Path

# --- Rutas relativas (añadidas por scripts/exportar_analisis.py) --------------------------
# Este script se escribió con rutas ABSOLUTAS de la máquina donde se investigó. Se resuelven
# desde la ubicación del propio archivo para que funcione tras un `git pull` en cualquier
# equipo. El corpus (`dataset-falsedad/`) NO está en el repositorio: lo aporta el cliente.
import pathlib as _pl
_REPO = _pl.Path(__file__).resolve().parents[3]
_DATASET = _REPO.parent / "dataset-falsedad"
_EJEMPLOS = _REPO.parent / "Ejemplos"
# ------------------------------------------------------------------------------------------

REPO = Path(str(_REPO))
sys.path.insert(0, str(REPO))
from incapacidad_ocr import numeros_es as N  # noqa: E402
from incapacidad_ocr.extract import RuleBasedExtractor  # noqa: E402

EX = RuleBasedExtractor()
FALLOS = []


def caso(grupo: str, texto: str, esperado, nota: str = "") -> None:
    d = N.duracion_en_texto(texto)
    got = d["valor"] if d else None
    ext = EX.extract(texto)["incapacidad"]["dias"]
    ok = got == esperado
    if not ok:
        FALLOS.append((grupo, texto, esperado, got))
    print(f"{'OK  ' if ok else '*** FALLO'} [{grupo}] {texto!r}")
    print(f"        esperado={esperado}  modulo={got}  extract.dias={ext}  "
          f"ev={(d or {}).get('evidencia')!r} {nota}")


print("### G · rotulo en SINGULAR 'dia:' / 'dia-' = campo de FECHA, no duracion")
caso("G", "EXPEDIDA EL DIA: 27 DE AGOSTO DE 2026", None)
caso("G", "Se expide el dia: 27\nFecha Inicial: 01/09/2026\nFecha Final: 03/09/2026", 3,
     "<- el dia del mes pisa los 3 dias reales")
caso("G", "FECHA DE EXPEDICION (DIA-MES-ANO)\n27 08 2026", None)
caso("G", "FECHA INICIAL DIA - MES - ANO\n15 09 2026", None)
caso("G", "DURACION DIA MES ANO\n15 09 2026", None)
caso("G", "Dias:\n27 08 2026", None)
caso("G", "EXPEDIDA EL DIA 27 DE AGOSTO DE 2026", None, "<- control: sin ':' no dispara")
caso("G", "FECHA DE EXPEDICION (DIA/MES/ANO)\n27 08 2026", None, "<- control: con '/' no dispara")

print("\n### H · rotulos sin frontera de palabra por la izquierda")
caso("H", "MEDIAS DE COMPRESION: 2", None)
caso("H", "GUARDIAS: 3", None)
caso("H", "Duraciones anteriores: 9", None)

print("\n### I · el veto solo mira a la IZQUIERDA del rotulo")
caso("I", "3.DURACION DEL PERMISO: 4 HORAS", None, "<- rotulo REAL (2/31 del corpus)")
caso("I", "DURACION: 2 HORAS", None)
caso("I", "Duracion del tratamiento: 3 meses", None)
caso("I", "Duracion: 40 semanas", None)
caso("I", "Duracion: dos meses", None)
caso("I", "Duracion aproximada: 2 anos", None)
caso("I", "DURACION: 2 DIAS", 2, "<- control")

print("\n### J · 'mil' fuera del lexico NO protege a duracion_en_texto")
caso("J", "Duracion: mil ochenta", None, "<- 1080 esta fuera de dominio")
caso("J", "Dias de incapacidad: dos mil veintiseis", None, "<- es un anio")
caso("J", "Duracion: del dos de enero de dos mil veintiseis", None)

print("\n### K · frase numeral PARCIAL aceptada (ventana de 25 tras el rotulo)")
caso("K", "Dias de incapacidad autorizados: CIENTO OCHENTA", 180)
caso("K", "Duracion del periodo: TREINTA Y CINCO", 35)
caso("K", "No. Total dias de incapacidad: TREINTA Y CINCO", 35,
     "<- 'No.Total dias:' es rotulo REAL (reales/REAL-06.txt)")
caso("K", "DIAS: DOSCIENTOS CINCUENTA Y CINCO (255)", 255,
     "<- ademas IGNORA el digito 255 que esta al lado")
caso("K", "DIAS DE INCAPACIDAD (CALENDARIO): ciento cincuenta y dos", 152)
caso("K", "Duracion: novecientos noventa y nueve", 999)
caso("K", "Duracion: TREINTA Y CINCO", 35, "<- control: cabe en la ventana")

print("\n### L · numerales_en_texto: que ancla de mas")
for t, esp in [("dos mil veintiseis (2026)", set()), ("dosdiagnosticos", set()),
               ("unadiabetes mellitus", set()), ("dos dias", {2})]:
    got = N.numerales_en_texto(t)
    ok = got == esp
    if not ok:
        FALLOS.append(("L", t, esp, got))
    print(f"{'OK  ' if ok else '*** FALLO'} [L] {t!r} esperado={esp} obtenido={got}")

print()
print("=" * 90)
print(f"fallos: {len(FALLOS)}")
for g, t, e, o in FALLOS:
    print(f"  [{g}] {t!r}  esperado={e}  obtenido={o}")
