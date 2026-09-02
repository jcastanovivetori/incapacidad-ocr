# -*- coding: utf-8 -*-
"""Exploracion 2: localizar la zona de firma via anclas OCR y extraer el trazo."""
import csv, hashlib, json, os, re, sys, unicodedata

# --- Rutas relativas (añadidas por scripts/exportar_analisis.py) --------------------------
# Este script se escribió con rutas ABSOLUTAS de la máquina donde se investigó. Se resuelven
# desde la ubicación del propio archivo para que funcione tras un `git pull` en cualquier
# equipo. El corpus (`dataset-falsedad/`) NO está en el repositorio: lo aporta el cliente.
import pathlib as _pl
_REPO = _pl.Path(__file__).resolve().parents[3]
_DATASET = _REPO.parent / "dataset-falsedad"
_EJEMPLOS = _REPO.parent / "Ejemplos"
# ------------------------------------------------------------------------------------------

BASE = str(_DATASET)
OUT = BASE + '/senales/firma_y_reuso'
sys.path.insert(0, str(_REPO))

import numpy as np
from PIL import Image
from incapacidad_ocr.preprocess import load_pages

ANCLA = re.compile(r'\bFIRMA\b|\bSELLO\b|\bF\s?I\s?R\s?M\s?A\b')


def norm(s):
    s = unicodedata.normalize('NFD', s or '')
    return ''.join(c for c in s if unicodedata.category(c) != 'Mn').upper()


def main():
    from rapidocr_onnxruntime import RapidOCR
    eng = RapidOCR()
    man = list(csv.DictReader(open(BASE + '/manifest.csv', encoding='utf-8')))
    os.makedirs(OUT + '/_band', exist_ok=True)
    res = {}
    for r in man:
        a = r['archivo']
        rows = []
        for pi, page in enumerate(load_pages(r['ruta_original'])):
            if pi > 2:
                break
            arr = np.asarray(page.convert('L'))
            H, W = arr.shape
            det, _ = eng(np.asarray(page))
            det = det or []
            boxes = []
            for it in det:
                box, txt, sc = it[0], it[1], it[2]
                xs = [p[0] for p in box]; ys = [p[1] for p in box]
                boxes.append((min(xs), min(ys), max(xs), max(ys), norm(txt), float(sc)))
            anclas = [b for b in boxes if ANCLA.search(b[4])]
            # mascara de texto reconocido
            mask = np.zeros((H, W), bool)
            for x0, y0, x1, y1, t, s in boxes:
                mask[max(0, int(y0)):int(y1) + 1, max(0, int(x0)):int(x1) + 1] = True
            ink = (arr < 190) & (~mask)
            rows.append({'pagina': pi, 'W': W, 'H': H, 'n_boxes': len(boxes),
                         'anclas': [{'txt': b[4][:28], 'rel': [round(b[0] / W, 3), round(b[1] / H, 3),
                                                               round(b[2] / W, 3), round(b[3] / H, 3)]} for b in anclas],
                         'ink_fuera_texto_pct': round(float(ink.mean()) * 100, 2)})
        res[a] = {'etiqueta': r['etiqueta'], 'cuarentena': r['cuarentena'], 'paginas': rows}
        na = sum(len(p['anclas']) for p in rows)
        print('%-6s q=%-2s pg=%d anclas=%d  %s' % (r['etiqueta'][:6], r['cuarentena'], len(rows), na, a[:58]))
        for p in rows:
            for x in p['anclas']:
                print('        p%d %-28s rel=%s' % (p['pagina'], x['txt'], x['rel']))
    json.dump(res, open(OUT + '/_anclas.json', 'w', encoding='utf-8'), ensure_ascii=False, indent=1)


if __name__ == '__main__':
    main()
