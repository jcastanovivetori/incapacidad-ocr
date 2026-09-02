"""Ataque 2: los DOS recortes de ventana y los limites de los rotulos.

- _VENTANA_ETIQUETA (25) recorta el numeral por DETRAS del rotulo.
- _VENTANA_IZQ (40) lo recorta por DELANTE de la unidad.
- los rotulos no tienen frontera de palabra a la izquierda ("MEDIAS:").
- el vecino se elige por 'parece linea de valor', y si el elegido no da valor NO
  se prueba el otro vecino.
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

FALLOS = []


def caso(grupo: str, texto: str, esperado, nota: str = "") -> None:
    d = N.duracion_en_texto(texto)
    got = d["valor"] if d else None
    estado = "OK " if got == esperado else "*** FALLO"
    print(f"{estado} [{grupo}] {texto!r}\n        esperado={esperado} obtenido={got} "
          f"evidencia={(d or {}).get('evidencia')!r} {nota}")
    if got != esperado:
        FALLOS.append((grupo, texto, esperado, got))


print("### A · recorte por DELANTE de la unidad (_VENTANA_IZQ = 40)")
caso("A", "se concede incapacidad por ciento ochenta dias", 180,
     "<- 'ciento' cae fuera de los 40 chars")
caso("A", "se otorga reposo por doscientos setenta y tres dias", 273)
caso("A", "el paciente requiere reposo domiciliario por ciento veinte dias", 120)
caso("A", "incapacidad medica general por ciento ochenta dias", 180)
caso("A", "por ciento ochenta dias", 180, "<- control: cabe en la ventana")

print("\n### B · recorte por DETRAS del rotulo (_VENTANA_ETIQUETA = 25)")
caso("B", "Duracion: ciento ochenta y cinco dias", 185)
caso("B", "Duracion: doscientos setenta y tres dias", 273)
caso("B", "Dias de incapacidad: doscientos cincuenta y cinco", 255)
caso("B", "Duracion:    ciento cincuenta y dos", 152, "<- OCR mete espacios")
caso("B", "Duracion: ciento ochenta", 180, "<- control: cabe")

print("\n### C · rotulos sin frontera de palabra por la izquierda")
caso("C", "MEDIAS DE COMPRESION TALLA MEDIAS: 2", None)
caso("C", "GUARDIAS: 3", None)
caso("C", "MEDIAS: 2 PARES", None)
caso("C", "Duraciones anteriores: 9", None, "<- 'duracion' sin \\b")

print("\n### D · eleccion de vecino: si el primero no da valor, no se prueba el otro")
caso("D", "-DOS\nDuracion\n0081523489", 2,
     "<- el consecutivo de 10 cifras 'gana' el hueco y tapa el -DOS del renglon anterior")
caso("D", "-DOS\nDuracion", 2, "<- control: sin el consecutivo si lee")
caso("D", "-DOS\nDuracion\nCED-13", 2, "<- cedula real del corpus como vecino")
caso("D", "126\nDURACION:\n0081523489", 126)

print("\n### E · el valor del renglon de al lado no comprueba que sea una duracion")
print("    (NO son 'fallos': es la forma A4 legitima 'DURACION:'+'126'. Se dejan como")
print("     evidencia de que un FRAGMENTO de fecha en un renglon propio es")
print("     indistinguible de una duracion, y el corpus tiene 7 renglones asi en")
print("     real/REAL-08.txt: '04','06','26','06','06','26','06')")
caso("E", "Duracion\n2026", None, "<- control: 4 cifras rechazadas")
caso("E", "Duracion\n26", 26, "<- fragmento de anio leido como duracion")
caso("E", "Dias Incapacidad\n06", 6, "<- fragmento de mes leido como duracion")

print("\n### F · unidad correcta pero con la palabra recortada -> valor MENOR")
caso("F", "DIAS DE INCAPACIDAD: quinientos treinta y cinco", 535)
caso("F", "DURACION: novecientos noventa y nueve", 999)

print()
print("=" * 90)
print(f"fallos: {len(FALLOS)}")
for g, t, e, o in FALLOS:
    print(f"  [{g}] {t!r}  esperado={e}  obtenido={o}")
