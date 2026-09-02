"""Confirmacion de los hallazgos del ataque: causa exacta y efecto end-to-end.

No modifica nada del paquete. Muestra, para cada hallazgo:
  - la lectura del modulo (numeros_es.duracion_en_texto),
  - la ventana que la origina (para los de truncamiento),
  - y el campo 'dias' que sale del extractor de REGLAS (lo que llega a staging).
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


def ver(titulo: str, texto: str, esperado: str) -> None:
    d = N.duracion_en_texto(texto)
    rec = EX.extract(texto)
    inc = rec["incapacidad"]
    print(f"\n--- {titulo}")
    print(f"  texto      : {texto!r}")
    print(f"  esperado   : {esperado}")
    print(f"  modulo     : {None if not d else {k: d[k] for k in ('valor','origen','letra','numero','evidencia')}}")
    print(f"  extract    : dias={inc['dias']} dias_letra={inc['dias_letra']} "
          f"coincide={inc['dias_letra_coincide']} tipo={rec['tipo_documento']}")


print("=" * 100)
print("H1 · VENTANA DE 25 CHARS TRAS EL ROTULO: el numeral en letras se TRUNCA")
print("=" * 100)
print("  _VENTANA_ETIQUETA =", N._VENTANA_ETIQUETA, " _VENTANA_IZQ =", N._VENTANA_IZQ)
for txt in (
    "Duracion: novecientos noventa y nueve dias",
    "Dias de incapacidad: doscientos cincuenta y cinco",
    "DURACION: doscientos setenta y tres dias",
    "DIAS DE INCAPACIDAD: quinientos treinta y cinco",
    "Dias: ciento ochenta y cinco dias",
):
    rot_fin = N.normalizar(txt).find(":") + 1
    seg = N.normalizar(txt)[rot_fin:rot_fin + N._VENTANA_ETIQUETA]
    ver(txt, txt, "el numeral completo")
    print(f"  ventana    : {seg!r}   <-- lo unico que ve _leer_valor")

print()
print("=" * 100)
print("H2 · VENTANA DE 40 CHARS A LA IZQUIERDA DE LA UNIDAD: se corta por delante")
print("=" * 100)
for txt in (
    "el medico tratante ordena reposo por doscientos setenta y tres dias",
    "se concede incapacidad medica domiciliaria por ciento ochenta dias",
):
    ver(txt, txt, "el numeral completo")
    linea = N.normalizar(txt)
    pos = linea.rfind("dias")
    print(f"  ventana izq: {linea[:pos][-N._VENTANA_IZQ:]!r}")

print()
print("=" * 100)
print("H3 · ROTULO + UNIDAD EQUIVOCADA A LA DERECHA (el veto solo mira a la izquierda)")
print("=" * 100)
for txt, esp in (
    ("3.DURACION DEL PERMISO: 4 HORAS", "None (permiso en HORAS)"),
    ("DURACION: 2 HORAS", "None"),
    ("Duracion del tratamiento: 3 meses", "None"),
    ("Duracion: 40 semanas", "None"),
    ("Duracion: dos meses", "None"),
):
    ver(txt, txt, esp)

print()
print("=" * 100)
print("H4 · REJILLA DIA/MES/ANO EN EL RENGLON DE AL LADO (FP n.7 reabierto)")
print("=" * 100)
for txt, esp in (
    ("DURACION DIA MES ANO\n15 09 2026", "None (es una fecha)"),
    ("Dias:\n27 08 2026", "None (es una fecha)"),
    ("FECHA INICIAL DIA-MES-ANO\n01 09 2026", "None (es una fecha)"),
    ("Duracion  Fecha Inicial\nDia Mes Ano\n15 09 2026", "None -- control: rejilla en linea propia"),
):
    ver(txt, txt, esp)

print()
print("=" * 100)
print("H5 · VETO DEMASIADO AMPLIO: se PIERDE la duracion correcta")
print("=" * 100)
for txt, esp in (
    ("Por lo anterior se hace entrega de incapacidad por 3 dias", "3"),
    ("Reposo 24 horas y se otorgan 5 dias de incapacidad", "5"),
    ("Control en 1 mes. Incapacidad por 7 dias", "7"),
    ("Gestante de 40 semanas. Incapacidad de 30 dias", "30"),
):
    ver(txt, txt, esp)

print()
print("=" * 100)
print("H6 · UNIDAD/ROTULO SEGUIDO DE GUION O DOS PUNTOS: se PIERDE el valor de delante")
print("=" * 100)
for txt, esp in (
    ("INCAPACIDAD: 3 DIAS - INICIA 01/09/2026", "3"),
    ("Se otorgan 10 DIAS-CALENDARIO", "10"),
    ("30 DIAS : del 01/09/2026 al 30/09/2026", "30"),
):
    ver(txt, txt, esp)

print()
print("=" * 100)
print("H7 · PRIORIDAD 'ambos': una forma mixta POSTERIOR gana a la duracion real")
print("=" * 100)
ver("mixta lejana", "INCAPACIDAD POR 15 DIAS\nFORMULA: DIAS: 3 (TRES) DE TRATAMIENTO", "15")

print()
print("=" * 100)
print("H8 · SIN RANGO DE DOMINIO en _dias_por_etiqueta (0 y 999 pasan)")
print("=" * 100)
for txt, esp in (
    ("Duracion: 0 dias\nFecha Inicial: 01/09/2026\nFecha Final: 03/09/2026", "3 por fechas, no 0"),
    ("Duracion: 999 dias", "descartado por rango"),
):
    ver(txt, txt, esp)

print()
print("=" * 100)
print("H9 · numerales_en_texto ancla valores de palabras PEGADAS a otra palabra")
print("=" * 100)
for txt in ("dosdiagnosticos", "unadiabetes mellitus", "presenta dos diagnosticos"):
    print(f"  {txt!r:34} -> {sorted(N.numerales_en_texto(txt))}")

print()
print("=" * 100)
print("H10 · formas arcaicas analiticas ('diez y seis') -> None")
print("=" * 100)
for txt in ("diez y seis", "diez y ocho", "veinte y uno"):
    print(f"  texto_a_entero({txt!r:16}) -> {N.texto_a_entero(txt)}")
    print(f"  duracion_en_texto('Duracion: {txt} dias') -> "
          f"{(N.duracion_en_texto('Duracion: ' + txt + ' dias') or {}).get('valor')}")
