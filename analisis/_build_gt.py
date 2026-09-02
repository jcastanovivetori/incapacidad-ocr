# -*- coding: utf-8 -*-
import json, os, unicodedata

# --- Rutas relativas (añadidas por scripts/exportar_analisis.py) --------------------------
# Este script se escribió con rutas ABSOLUTAS de la máquina donde se investigó. Se resuelven
# desde la ubicación del propio archivo para que funcione tras un `git pull` en cualquier
# equipo. El corpus (`dataset-falsedad/`) NO está en el repositorio: lo aporta el cliente.
import pathlib as _pl
_REPO = _pl.Path(__file__).resolve().parents[1]
_DATASET = _REPO.parent / "dataset-falsedad"
_EJEMPLOS = _REPO.parent / "Ejemplos"
# ------------------------------------------------------------------------------------------

OUT_DIR = str(_DATASET)
FALSAS  = r'<descargas>/Falsas'
os.makedirs(OUT_DIR, exist_ok=True)

TAXONOMIA = {
    "DX_INEXISTENTE":        "El codigo CIE-10 reportado no existe en el catalogo oficial.",
    "DX_FORMATO":            "El codigo CIE-10 no cumple el formato/longitud esperada (p. ej. 3 caracteres en vez de 4).",
    "DX_NOMBRE_DISTINTO":    "La descripcion del diagnostico no coincide exactamente con la del catalogo para ese codigo.",
    "FECHAS_INCOHERENTES":   "Fecha de inicio, duracion en dias y fecha de fin no cuadran aritmeticamente.",
    "DIAS_VS_DIAGNOSTICO":   "La cantidad de dias de incapacidad no es plausible para el diagnostico reportado.",
    "FIRMA_MEDICO":          "La firma del medico es sospechosa (copiada, pegada o inconsistente).",
    "TIPOGRAFIA_MIXTA":      "Varios tipos de letra en el documento, indicio de texto anadido o reemplazado.",
    "SIN_MOTIVO_REGISTRADO": "La celda de motivo venia vacia en la tabla del cliente; no hay motivo documentado.",
}

# (archivo, motivo_texto, en_rojo, senales)  -- orden EXACTO de la imagen
DATA = [
    ("FALSA-02.pdf",
     "NO EXISTE EL DX R505", False, ["DX_INEXISTENTE"]),
    ("FALSA-01.pdf",
     "FIRMA DEL MEDICO", False, ["FIRMA_MEDICO"]),
    ("FALSA-03.pdf",
     "VARIOS TIPOS DE LETRAS EN EL DOCUMENTO", False, ["TIPOGRAFIA_MIXTA"]),
    ("INC <NOMBRE> DE LA HOZ <NOMBRE> <NOMBRE> 3 D\u00cdAS 02.09.2025.pdf",
     "ALTERACION EN FECHA DE INICIO, DURACION Y FECHA FIN, LOS DIAS NO CORRESPONDEN A LA FECHA DE FINALIZACION CALCULADA",
     False, ["FECHAS_INCOHERENTES"]),
    ("FALSA-05.pdf",
     "NO CONCUERDA EL NUMERO DE DIAS CON EL DIAGNOSTICO", True, ["DIAS_VS_DIAGNOSTICO"]),
    ("FALSA-06.pdf",
     "", True, ["SIN_MOTIVO_REGISTRADO"]),
    ("FALSA-07.pdf",
     "EL NOMBRE DEL DX NO ES EXACTAMENTE IGUAL", False, ["DX_NOMBRE_DISTINTO"]),
    ("FALSA-08.pdf",
     "FIRMA DEL MEDICO", False, ["FIRMA_MEDICO"]),
    ("FALSA-09.jpeg",
     "NO EXISTE EL DX A09 - TODOS LOS DX SON DE 4 CARACTERES", False, ["DX_INEXISTENTE", "DX_FORMATO"]),
    ("FALSA-10.pdf",
     "NO EXISTE EL DX A00", False, ["DX_INEXISTENTE"]),
    ("FALSA-11.pdf",
     "NO EXISTE EL DX G43", False, ["DX_INEXISTENTE"]),
    ("FALSA-13.pdf",
     "EL NOMBRE DEL DX NO ES EXACTAMENTE IGUAL", True, ["DX_NOMBRE_DISTINTO"]),
    ("FALSA-14.pdf",
     "", True, ["SIN_MOTIVO_REGISTRADO"]),
    ("FALSA-12.pdf",
     "", True, ["SIN_MOTIVO_REGISTRADO"]),
    ("FALSA-15.pdf",
     "EL NOMBRE DEL DX NO ES EXACTAMENTE IGUAL", False, ["DX_NOMBRE_DISTINTO"]),
]

def nfc(s):
    return unicodedata.normalize('NFC', s)

en_disco = {nfc(n) for n in os.listdir(FALSAS)}

filas = []
for i, (arch, motivo, rojo, senales) in enumerate(DATA, start=1):
    filas.append({
        "fila": i,
        "archivo": arch,
        "motivo_texto": motivo,
        "en_rojo": rojo,
        "motivo_vacio": motivo == "",
        "archivo_existe": nfc(arch) in en_disco,
        "senales": senales,
    })

gt = {
    "fuente": "Explicacion de archivos.jpeg",
    "filas": filas,
    "taxonomia": TAXONOMIA,
}

path = os.path.join(OUT_DIR, 'ground_truth.json')
with open(path, 'w', encoding='utf-8') as f:
    json.dump(gt, f, ensure_ascii=False, indent=2)
    f.write('\n')

# controles
faltan = [r["archivo"] for r in filas if not r["archivo_existe"]]
extra  = sorted(n for n in en_disco
                if n.lower().endswith(('.pdf', '.jpeg', '.jpg', '.png'))
                and n != 'Explicacion de archivos.jpeg'
                and n not in {nfc(r["archivo"]) for r in filas})
print('escrito:', path)
print('filas:', len(filas), '| en_rojo:', sum(r["en_rojo"] for r in filas),
      '| motivo_vacio:', sum(r["motivo_vacio"] for r in filas))
print('no existen en disco:', faltan)
print('docs en disco fuera de la tabla:', extra)
print('ids usados:', sorted({s for r in filas for s in r["senales"]}))
