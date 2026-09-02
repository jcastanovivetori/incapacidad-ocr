# -*- coding: utf-8 -*-
"""SONDA de la familia de senales `firma_y_reuso`.

Cubre FIRMA_MEDICO ('FIRMA DEL MEDICO') desde el unico angulo que un motor local
puede sostener: NO verificar que una firma sea autentica (eso es peritaje grafologico,
fuera de alcance), sino detectar el REUSO y la INCOHERENCIA de los recursos graficos
(firma, sello, membrete, fondo) entre documentos del corpus.

100% LOCAL. Sin IA externa, sin APIs pagas, sin Docker, sin Ollama.
Librerias usadas: pypdfium2 (extraer XObjects de imagen), Pillow + numpy (bitmap,
hash perceptual propio via DCT), rapidocr-onnxruntime (leer el TEXTO que hay DENTRO
del recorte de firma/sello, para el check de coherencia de identidad).

PII: la sonda escribe los datos a ARCHIVOS en disco. En stdout imprime nombre de
archivo, etiqueta y resultado de los checks; nunca diagnosticos, y las identidades
del personal medico se reducen a un hash corto (`id#xxxxxxxx`).

Uso:
    python probe.py                 # corre todo (usa cache si existe)
    python probe.py --recalcular    # ignora la cache y vuelve a extraer + OCR
"""
from __future__ import annotations

import csv
import glob
import hashlib
import json
import os
import re
import sys
import unicodedata
from collections import defaultdict

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
AQUI = os.path.join(BASE, 'senales', 'firma_y_reuso')
REPO = str(_REPO)
sys.path.insert(0, REPO)

import numpy as np                                    # noqa: E402
import pypdfium2 as pdfium                            # noqa: E402
from PIL import Image                                 # noqa: E402

CACHE = os.path.join(AQUI, 'recursos.json')
SALIDA = os.path.join(AQUI, 'resultado.json')

# ----------------------------------------------------------------------------
# Umbrales (declarados arriba, no escondidos en el codigo)
# ----------------------------------------------------------------------------
UMB = {
    # degeneracion: una imagen plana (mascara, relleno solido, franja vacia) tiene
    # hash perceptual constante y colisiona con TODAS las demas -> es incomparable.
    'std_min': 4.0,
    'niveles_min': 8,
    'lado_px_min': 12,
    'area_px_min': 900,
    # roles por geometria (y medido desde el borde INFERIOR de la pagina, 0..1)
    'fondo_area_rel': 0.55,
    'membrete_y': 0.88,
    'pie_y': 0.06,
    'firma_asp_min': 0.25,
    'firma_asp_max': 14.0,
    'firma_area_rel_min': 0.0008,
    'firma_area_rel_max': 0.30,
    'firma_ink_min': 0.005,
    # similitud perceptual
    'phash_max': 6,
    'dhash_max': 10,
    'asp_tol': 0.10,
}

# Marcas de herramienta de captura/edicion. NO son firmas ni logos de la EPS:
# son la huella del software con que se fotografio o re-armo el documento.
# Se excluyen de los checks de reuso (si no, disparan en todo el corpus).
MARCAS_HERRAMIENTA = [
    'CAMSCANNER', 'CAM SCANNER', 'TAPSCANNER', 'TAP SCANNER', 'DOCSCANNER',
    'OFFICE LENS', 'GENIUS SCAN', 'SCANNER PRO', 'ADOBE SCAN', 'ILOVEPDF',
    'SMALLPDF', 'SEJDA', 'PDF24', 'FOXIT', 'WPS OFFICE', 'CANVA', 'SCANNED BY',
    'ESCANEADO CON', 'POWERED BY', 'CREADO CON', 'FREE VERSION', 'TRIAL VERSION',
]
# Marcas de proveedor de software clinico: se ven en el membrete y son ESPERABLES.
MARCAS_PROVEEDOR = ['SYSNET', 'CARVAJAL', 'HEON', 'DINAMICA GERENCIAL', 'SERVINTE']

RE_ANCLA_FIRMA_MEDICO = re.compile(
    r'FIRMA\s*(Y\s*SELLO\s*)?(DEL?\s*)?(MEDIC|PROFESIONAL|PRESTADOR|GALEN)')
RE_ID = re.compile(r'\b(\d{1,3}[\.\s]\d{3}[\.\s]\d{3,4}|\d{4,12})\b')


def es_telefono_co(x: str) -> bool:
    """Un celular colombiano son 10 digitos que empiezan en 3; una cedula no."""
    return len(x) == 10 and x.startswith('3')


# ----------------------------------------------------------------------------
# utilidades
# ----------------------------------------------------------------------------
def sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def norm(s) -> str:
    s = unicodedata.normalize('NFD', str(s or ''))
    s = ''.join(c for c in s if unicodedata.category(c) != 'Mn')
    return re.sub(r'\s+', ' ', s).upper().strip()


def corto(s: str, n: int = 8) -> str:
    """Hash corto y estable: permite comparar identidades sin exponerlas (PII)."""
    return hashlib.sha256(norm(s).encode()).hexdigest()[:n]


def _dct_mat(n: int) -> np.ndarray:
    k = np.arange(n)
    m = np.cos(np.pi * (2 * k[None, :] + 1) * k[:, None] / (2 * n))
    m[0] *= 1 / np.sqrt(2)
    return m * np.sqrt(2.0 / n)


_D32 = _dct_mat(32)


def phash64(gray: np.ndarray) -> int:
    """pHash 64 bits (DCT-II 32x32 -> 8x8 baja frecuencia vs mediana).

    Implementado con numpy para no anadir la dependencia `imagehash` (que arrastra
    scipy). Es el mismo algoritmo, deterministico y auditable en 6 lineas.
    """
    a = np.asarray(Image.fromarray(gray).resize((32, 32), Image.LANCZOS), dtype=np.float64)
    c = _D32 @ a @ _D32.T
    low = c[:8, :8].flatten()
    bits = (low > np.median(low[1:])).astype(np.uint8)
    bits[0] = 0
    return int(''.join(map(str, bits)), 2)


def dhash64(gray: np.ndarray) -> int:
    """dHash 64 bits (gradiente horizontal). Complementa a pHash: tolera reescalado."""
    a = np.asarray(Image.fromarray(gray).resize((9, 8), Image.LANCZOS), dtype=np.int16)
    return int(''.join(map(str, (a[:, 1:] > a[:, :-1]).astype(np.uint8).flatten())), 2)


def ham(x: int, y: int) -> int:
    return bin(x ^ y).count('1')


# ----------------------------------------------------------------------------
# 1. inventario de recursos graficos por documento
# ----------------------------------------------------------------------------
def _rasgos(pil: Image.Image) -> dict:
    g = np.asarray(pil.convert('L'))
    return {'sha256_pixeles': sha(pil.convert('RGB').tobytes()),
            'px_bitmap': list(pil.size),
            'phash': phash64(g), 'dhash': dhash64(g),
            'ink': round(float((g < 200).mean()), 4),
            'std': round(float(g.astype(np.float64).std()), 2),
            'niveles': int(len(np.unique(g)))}


def recursos_pdf(path: str) -> list:
    out = []
    pdf = pdfium.PdfDocument(path)
    try:
        for pi in range(len(pdf)):
            page = pdf[pi]
            pw, ph = page.get_width(), page.get_height()
            try:
                # max_depth>0: los XObject de imagen suelen venir DENTRO de Form
                # XObjects; sin recursion se pierden (asi paso en la fase de OCR).
                objs = list(page.get_objects(filter=(pdfium.raw.FPDF_PAGEOBJ_IMAGE,), max_depth=15))
            except Exception as e:
                out.append({'pagina': pi, 'error': repr(e)[:120]})
                page.close()
                continue
            for oi, ob in enumerate(objs):
                r = {'pagina': pi, 'obj': oi, 'pw': round(pw, 1), 'ph': round(ph, 1)}
                try:
                    raw = bytes(ob.get_data(decode_simple=False))
                    r['bytes_stream'] = len(raw)
                    r['sha256_stream'] = sha(raw)
                except Exception as e:
                    r['err_stream'] = repr(e)[:80]
                try:
                    r['filtros'] = ob.get_filters()
                except Exception:
                    r['filtros'] = None
                try:
                    md = ob.get_metadata()
                    r['px'] = [md.width, md.height]
                    r['dpi'] = [round(md.horizontal_dpi, 1), round(md.vertical_dpi, 1)]
                except Exception:
                    r['px'] = None
                try:
                    l, b, rr, t = ob.get_bounds()
                    r['bbox'] = [round(l, 1), round(b, 1), round(rr, 1), round(t, 1)]
                except Exception:
                    r['bbox'] = None
                try:
                    r.update(_rasgos(ob.get_bitmap(render=False).to_pil()))
                except Exception as e:
                    r['err_bmp'] = repr(e)[:80]
                out.append(r)
            page.close()
    finally:
        pdf.close()
    return out


def recursos_raster(path: str) -> list:
    raw = open(path, 'rb').read()
    pil = Image.open(path)
    r = {'pagina': 0, 'obj': 0, 'pw': pil.size[0], 'ph': pil.size[1],
         'bytes_stream': len(raw), 'sha256_stream': sha(raw),
         'filtros': ['<contenedor>'], 'px': list(pil.size),
         'bbox': [0, 0, pil.size[0], pil.size[1]], 'es_contenedor': True}
    r.update(_rasgos(pil))
    return [r]


def clasificar_rol(r: dict) -> str:
    """Rol geometrico del recurso. Deterministico: solo geometria y estadistica."""
    if r.get('std') is None:
        return 'ERROR'
    px = r.get('px') or r.get('px_bitmap') or [0, 0]
    if (r['std'] < UMB['std_min'] or r.get('niveles', 0) < UMB['niveles_min']
            or min(px) < UMB['lado_px_min'] or px[0] * px[1] < UMB['area_px_min']):
        return 'DEGENERADA'          # plana -> hash perceptual inutil
    if r.get('es_contenedor'):
        return 'FONDO_PAGINA'
    bb = r.get('bbox') or [0, 0, 0, 0]
    pw = r.get('pw') or 1
    ph = r.get('ph') or 1
    r['area_rel'] = round(abs((bb[2] - bb[0]) * (bb[3] - bb[1])) / (pw * ph), 4)
    r['y_rel'] = round(((bb[1] + bb[3]) / 2) / ph, 3)
    r['asp'] = round(px[0] / max(1, px[1]), 3)
    if r['area_rel'] >= UMB['fondo_area_rel']:
        return 'FONDO_PAGINA'
    if r['y_rel'] >= UMB['membrete_y']:
        return 'MEMBRETE'
    if r['y_rel'] <= UMB['pie_y']:
        return 'PIE'
    if (UMB['firma_asp_min'] <= r['asp'] <= UMB['firma_asp_max']
            and UMB['firma_area_rel_min'] <= r['area_rel'] <= UMB['firma_area_rel_max']
            and r['ink'] >= UMB['firma_ink_min']):
        return 'FIRMA_SELLO_CAND'
    return 'OTRA'


# ----------------------------------------------------------------------------
# 2. OCR del recorte: marcas de herramienta + identidades dentro del sello
# ----------------------------------------------------------------------------
def ocr_recortes(docs: dict, man: dict) -> None:
    """Lee el texto que hay DENTRO de cada recurso no degenerado (RapidOCR local)."""
    from rapidocr_onnxruntime import RapidOCR
    eng = RapidOCR()
    for a, d in docs.items():
        objetivo = [r for r in d['recursos']
                    if r.get('rol') in ('FIRMA_SELLO_CAND', 'MEMBRETE', 'PIE', 'OTRA')]
        if not objetivo:
            continue
        if man[a]['ext'].lower() == 'pdf':
            pdf = pdfium.PdfDocument(man[a]['ruta_original'])
            cache = {}
            for pi in range(len(pdf)):
                page = pdf[pi]
                for oi, ob in enumerate(page.get_objects(
                        filter=(pdfium.raw.FPDF_PAGEOBJ_IMAGE,), max_depth=15)):
                    cache[(pi, oi)] = ob
                for r in objetivo:
                    ob = cache.get((r['pagina'], r['obj']))
                    if ob is None:
                        continue
                    try:
                        pil = ob.get_bitmap(render=False).to_pil().convert('RGB')
                        if max(pil.size) < 320:      # ampliar: RapidOCR falla en crops chicos
                            k = 320 / max(pil.size)
                            pil = pil.resize((max(1, int(pil.width * k)),
                                              max(1, int(pil.height * k))), Image.LANCZOS)
                        det, _ = eng(np.asarray(pil))
                        r['texto_recorte'] = norm(' '.join(i[1] for i in (det or [])))
                    except Exception as e:
                        r['texto_recorte'] = ''
                        r['err_ocr'] = repr(e)[:60]
                page.close()
            pdf.close()


def marcar_semantica(docs: dict) -> None:
    for d in docs.values():
        for r in d['recursos']:
            t = r.get('texto_recorte') or ''
            r['es_marca_herramienta'] = any(m in t for m in MARCAS_HERRAMIENTA)
            r['es_marca_proveedor'] = any(m in t for m in MARCAS_PROVEEDOR)
            ids = {m.group(1).replace('.', '').replace(' ', '') for m in RE_ID.finditer(t)}
            r['ids_en_recorte'] = sorted(x for x in ids if not es_telefono_co(x))
            if r['es_marca_herramienta'] or r['es_marca_proveedor']:
                r['rol'] = 'MARCA_HERRAMIENTA' if r['es_marca_herramienta'] else 'MARCA_PROVEEDOR'


# ----------------------------------------------------------------------------
# 3. identidades del documento (paciente / medico) tomadas de la fase de OCR
# ----------------------------------------------------------------------------
def cargar_ocr_fase() -> dict:
    j = {}
    for p in glob.glob(os.path.join(BASE, 'ocr', '*', '*.json')):
        try:
            d = json.load(open(p, encoding='utf-8'))
            j[d['archivo']] = d
        except Exception:
            pass
    return j


def identidades(man: dict, fase: dict) -> dict:
    """id_paciente por documento (agrupacion por union-find).

    En produccion la cedula del paciente NO se adivina: llega del nombre de archivo
    de la ingesta batch (`{cedula}_{AAAAMMDD}_{TIPODOC}`) o del registro de
    radicacion del ERP. Aqui hay que reconstruirla porque el corpus 'Falsas' viene
    nombrado con el NOMBRE del paciente y el corpus 'Reales' con la cedula.

    Claves de agrupacion por documento:
      - cedula del nombre de archivo (fuente fuerte),
      - firma de nombre del archivo (fuente fuerte para 'Falsas'),
      - cedula extraida por OCR, pero SOLO si coincide con la cedula de archivo de
        algun otro documento (corroboracion cruzada). Sin esa corroboracion el OCR
        confunde la cedula del paciente con el registro del medico -- se midio: en
        4 de 31 documentos `paciente.documento_numero` es otro numero del formato.
    Dos documentos quedan en el mismo grupo si comparten cualquier clave.
    """
    RUIDO = {'INC', 'INCAPACIDAD', 'INPACACIDAD', 'PERMISO', 'HISTORIA', 'DIAS', 'DIA',
             'PDF', 'JPEG', 'JPG', 'PNG', 'COPIA', 'SOPORTE'}
    crudo = {}
    for a, r in man.items():
        f = fase.get(a) or {}
        inc = (f.get('incapacidad') or {})
        ced_ocr = re.sub(r'\D', '', str((inc.get('paciente') or {}).get('documento_numero') or ''))
        m = re.match(r'^(\d{6,12})[_\-\s]', a)
        ced_fn = m.group(1) if m else ''
        # nombre del paciente en el nombre de archivo: solo tokens alfabeticos de >=3
        # letras que no sean palabras de tipo de documento. Si quedan <2 tokens no se
        # usa (evita que '_INCAPACIDAD' se convierta en una clave que une a TODOS).
        toks = [t for t in re.split(r'[^A-Z]+', norm(os.path.splitext(a)[0]))
                if len(t) >= 3 and t not in RUIDO]
        crudo[a] = {'ced_fn': ced_fn, 'ced_ocr': ced_ocr,
                    'nombre_fn': ''.join(toks) if len(toks) >= 2 else '',
                    'inc': inc, 'texto': norm(f.get('texto_plano') or '')}

    ced_fn_todas = {v['ced_fn'] for v in crudo.values() if v['ced_fn']}
    claves = {}
    for a, v in crudo.items():
        ks = set()
        if v['ced_fn']:
            ks.add('C:' + v['ced_fn'])
        else:
            # sin cedula en el nombre: se admite la del OCR SOLO si otro documento la
            # trae en su nombre de archivo (corroboracion de dos fuentes distintas).
            if v['ced_ocr'] and v['ced_ocr'] in ced_fn_todas:
                ks.add('C:' + v['ced_ocr'])
            if v['nombre_fn']:
                ks.add('N:' + v['nombre_fn'])
        claves[a] = ks or {'A:' + a}

    padre = {a: a for a in crudo}

    def find(x):
        while padre[x] != x:
            padre[x] = padre[padre[x]]
            x = padre[x]
        return x

    por_clave = defaultdict(list)
    for a, ks in claves.items():
        for k in ks:
            por_clave[k].append(a)
    for k, lst in por_clave.items():
        for b in lst[1:]:
            ra, rb = find(lst[0]), find(b)
            if ra != rb:
                padre[rb] = ra

    out = {}
    for a, v in crudo.items():
        med = (v['inc'].get('medico') or {})
        out[a] = {
            'id_paciente': 'pac#' + corto(find(a)),
            'ced_ocr_corroborada': bool(v['ced_ocr'] and v['ced_ocr'] in ced_fn_todas),
            'claves': sorted('k#' + corto(k) for k in claves[a]),
            'medico_registro': re.sub(r'\D', '', str(med.get('registro') or '')),
            'medico_nombre_h': ('med#' + corto(med.get('nombre'))) if med.get('nombre') else '',
            'fecha_inicio': ((v['inc'].get('incapacidad') or {}).get('fecha_inicio') or ''),
            'texto': v['texto'],
        }
    return out


# ----------------------------------------------------------------------------
# 4. checks
# ----------------------------------------------------------------------------
def comparable(r: dict) -> bool:
    return r.get('rol') not in ('DEGENERADA', 'ERROR', 'MARCA_HERRAMIENTA',
                                'MARCA_PROVEEDOR', None)


def correr_checks(docs: dict, ident: dict) -> dict:
    # --- indices de reuso -----------------------------------------------------
    por_hash = defaultdict(list)          # (sha_stream|sha_pixeles) -> [(arch, rec)]
    items = []
    for a, d in docs.items():
        for r in d['recursos']:
            if not comparable(r):
                continue
            items.append((a, r))
            for k in ('sha256_stream', 'sha256_pixeles'):
                if r.get(k):
                    por_hash[r[k]].append((a, r))

    res = {a: {c: {'hit': False, 'ev': []} for c in CHECKS} for a in docs}

    def pac(a):
        return ident[a]['id_paciente']

    # C1/C2/C5: colisiones EXACTAS
    for h, lst in por_hash.items():
        docsh = {a for a, _ in lst}
        if len(docsh) < 2:
            continue
        for a, r in lst:
            otros = sorted(x for x in docsh if x != a)
            cross = sorted(x for x in otros if pac(x) != pac(a))
            ev = {'hash': h[:12], 'rol': r['rol'], 'px': r.get('px'),
                  'n_docs': len(docsh), 'otros_pacientes': len(cross),
                  'otros': [os.path.basename(x) for x in (cross or otros)][:6]}
            if r['rol'] == 'FIRMA_SELLO_CAND' and cross:
                res[a]['FIRMA_REUSO_EXACTO_CROSS_PACIENTE']['hit'] = True
                res[a]['FIRMA_REUSO_EXACTO_CROSS_PACIENTE']['ev'].append(ev)
            if r['rol'] == 'FONDO_PAGINA' and cross:
                res[a]['FONDO_REUSO_CROSS_PACIENTE']['hit'] = True
                res[a]['FONDO_REUSO_CROSS_PACIENTE']['ev'].append(ev)
            if r['rol'] in ('MEMBRETE', 'PIE') and cross:
                res[a]['MEMBRETE_COMPARTIDO']['hit'] = True
                res[a]['MEMBRETE_COMPARTIDO']['ev'].append(ev)

    # C3/C4: colisiones PERCEPTUALES (reescalado / recompresion)
    for i in range(len(items)):
        a1, r1 = items[i]
        for j in range(i + 1, len(items)):
            a2, r2 = items[j]
            if a1 == a2:
                continue
            if r1['rol'] != 'FIRMA_SELLO_CAND' or r2['rol'] != 'FIRMA_SELLO_CAND':
                continue
            dp, dd = ham(r1['phash'], r2['phash']), ham(r1['dhash'], r2['dhash'])
            if dp > UMB['phash_max'] or dd > UMB['dhash_max']:
                continue
            asp1, asp2 = r1.get('asp') or 1, r2.get('asp') or 1
            if abs(asp1 - asp2) / max(asp1, asp2) > UMB['asp_tol']:
                continue
            exacto = (r1.get('sha256_stream') == r2.get('sha256_stream')
                      or r1.get('sha256_pixeles') == r2.get('sha256_pixeles'))
            mismo_pac = pac(a1) == pac(a2)
            ev = {'dp': dp, 'dd': dd, 'px1': r1.get('px'), 'px2': r2.get('px'),
                  'exacto': exacto, 'mismo_paciente': mismo_pac}
            for (aa, bb) in ((a1, a2), (a2, a1)):
                e = dict(ev, otro=os.path.basename(bb))
                if not mismo_pac and not exacto:
                    res[aa]['FIRMA_REUSO_PERCEPTUAL_CROSS_PACIENTE']['hit'] = True
                    res[aa]['FIRMA_REUSO_PERCEPTUAL_CROSS_PACIENTE']['ev'].append(e)
                if not exacto:
                    res[aa]['FIRMA_REUSO_RECOMPRIMIDA']['hit'] = True
                    res[aa]['FIRMA_REUSO_RECOMPRIMIDA']['ev'].append(e)

    # C6: coherencia entre la identidad IMPRESA en el sello y la del texto
    for a, d in docs.items():
        reg = ident[a]['medico_registro']
        for r in d['recursos']:
            if r.get('rol') != 'FIRMA_SELLO_CAND':
                continue
            ids = [x for x in (r.get('ids_en_recorte') or []) if 4 <= len(x) <= 12]
            if not ids:
                continue
            if reg and len(reg) >= 4 and reg not in ids:
                # el sello declara una identidad y el campo medico otra
                res[a]['FIRMA_ID_INCOHERENTE']['hit'] = True
                res[a]['FIRMA_ID_INCOHERENTE']['ev'].append(
                    {'ids_sello': ['id#' + corto(x) for x in ids],
                     'registro_texto': 'id#' + corto(reg), 'px': r.get('px')})

    # C7: marca de herramienta de captura/edicion
    for a, d in docs.items():
        for r in d['recursos']:
            if r.get('rol') == 'MARCA_HERRAMIENTA':
                res[a]['MARCA_HERRAMIENTA_CAPTURA']['hit'] = True
                res[a]['MARCA_HERRAMIENTA_CAPTURA']['ev'].append(
                    {'px': r.get('px'), 'marca_len': len(r.get('texto_recorte') or '')})

    # C8: la etiqueta 'FIRMA DEL MEDICO' existe pero no hay grafico de firma
    for a, d in docs.items():
        tiene_ancla = bool(RE_ANCLA_FIRMA_MEDICO.search(ident[a]['texto']))
        tiene_firma = any(r.get('rol') == 'FIRMA_SELLO_CAND' for r in d['recursos'])
        es_escaneo = any(r.get('rol') == 'FONDO_PAGINA' for r in d['recursos'])
        if not tiene_ancla:
            res[a]['FIRMA_MEDICO_AUSENTE']['no_evaluable'] = 'sin etiqueta FIRMA DEL MEDICO en el texto'
        elif es_escaneo:
            res[a]['FIRMA_MEDICO_AUSENTE']['no_evaluable'] = 'escaneo/foto: la firma no es un XObject aislable'
        elif not tiene_firma:
            res[a]['FIRMA_MEDICO_AUSENTE']['hit'] = True
            res[a]['FIRMA_MEDICO_AUSENTE']['ev'].append({'motivo': 'etiqueta presente, sin grafico de firma'})

    # C9/C10: no evaluables hoy (faltan datos externos)
    for a in docs:
        res[a]['RECURSO_REUSO_CROSS_EMISOR']['no_evaluable'] = (
            'el extractor no entrega EPS/IPS fiable (devuelve fragmentos de direccion)')
        res[a]['FIRMA_HISTORICO_ERP']['no_evaluable'] = (
            'falta el indice de hashes del historico de radicaciones del ERP')

    # --- marcar NO EVALUABLE lo que estructuralmente no puede disparar ----------
    # Sin un XObject de firma aislable (documento fotografiado / escaneo de pagina
    # completa) los checks de reuso de firma no pueden dar ni positivo ni negativo:
    # contarlos como "0 detectados" seria hacer pasar una ceguera por un acierto.
    for a, d in docs.items():
        firmas = [r for r in d['recursos'] if r.get('rol') == 'FIRMA_SELLO_CAND']
        if not firmas:
            motivo = ('sin XObject de firma/sello aislable (escaneo o foto de pagina completa)'
                      if any(r.get('rol') == 'FONDO_PAGINA' for r in d['recursos'])
                      else 'sin grafico candidato a firma/sello en el documento')
            for c in ('FIRMA_REUSO_EXACTO_CROSS_PACIENTE',
                      'FIRMA_REUSO_PERCEPTUAL_CROSS_PACIENTE',
                      'FIRMA_REUSO_RECOMPRIMIDA', 'FIRMA_ID_INCOHERENTE'):
                res[a][c]['no_evaluable'] = motivo
        else:
            reg = ident[a]['medico_registro']
            hay = any(x for r in firmas for x in (r.get('ids_en_recorte') or [])
                      if 4 <= len(x) <= 12)
            if not (reg and len(reg) >= 4 and hay):
                res[a]['FIRMA_ID_INCOHERENTE']['no_evaluable'] = (
                    'no hay par comparable: registro del texto=%s, IDs leidos en el sello=%s'
                    % ('si' if (reg and len(reg) >= 4) else 'no', 'si' if hay else 'no'))
        if not any(r.get('rol') == 'FONDO_PAGINA' for r in d['recursos']):
            res[a]['FONDO_REUSO_CROSS_PACIENTE']['no_evaluable'] = (
                'el documento no tiene imagen de pagina completa')
    return res


CHECKS = [
    'FIRMA_REUSO_EXACTO_CROSS_PACIENTE',
    'FIRMA_REUSO_PERCEPTUAL_CROSS_PACIENTE',
    'FIRMA_REUSO_RECOMPRIMIDA',
    'FONDO_REUSO_CROSS_PACIENTE',
    'FIRMA_ID_INCOHERENTE',
    'MEMBRETE_COMPARTIDO',
    'MARCA_HERRAMIENTA_CAPTURA',
    'FIRMA_MEDICO_AUSENTE',
    'RECURSO_REUSO_CROSS_EMISOR',
    'FIRMA_HISTORICO_ERP',
]
# Checks que, si disparan, cuentan como DETECCION de la familia. `MEMBRETE_COMPARTIDO`,
# `MARCA_HERRAMIENTA_CAPTURA` y `FIRMA_MEDICO_AUSENTE` NO cuentan: son informativos y
# se midieron por separado porque disparan en documentos legitimos.
CHECKS_ACUSATORIOS = [
    'FIRMA_REUSO_EXACTO_CROSS_PACIENTE',
    'FIRMA_REUSO_PERCEPTUAL_CROSS_PACIENTE',
    'FIRMA_REUSO_RECOMPRIMIDA',
    'FONDO_REUSO_CROSS_PACIENTE',
    'FIRMA_ID_INCOHERENTE',
]


# ----------------------------------------------------------------------------
# main
# ----------------------------------------------------------------------------
def autotest() -> int:
    """CONTROL POSITIVO sintetico.

    El corpus real NO contiene ni un solo caso de la misma firma cruzando pacientes
    distintos, asi que los checks centrales devuelven False en los 29 documentos
    evaluables. Sin este control no habria forma de saber si eso es una MEDICION o
    un bug. Aqui se fabrican documentos con firmas sinteticas (garabatos generados
    con PIL, cero PII) y se verifica que los checks disparan cuando deben y callan
    cuando no deben.
    """
    import random
    import tempfile
    from PIL import ImageDraw
    from fpdf import FPDF

    def garabato(semilla, w=560, h=190):
        rnd = random.Random(semilla)
        im = Image.new('L', (w, h), 255)
        d = ImageDraw.Draw(im)
        x, y = 20, h // 2
        for _ in range(26):
            nx = min(w - 20, x + rnd.randint(10, 34))
            ny = max(15, min(h - 15, y + rnd.randint(-52, 52)))
            d.line([(x, y), (nx, ny)], fill=0, width=rnd.randint(2, 5))
            x, y = nx, ny
        d.text((60, 12), 'REG %d' % (1000000 + semilla * 7919 % 8999999), fill=40)
        return im.convert('RGB')

    tmp = tempfile.mkdtemp(prefix='firma_autotest_')
    firmaA, firmaB = garabato(1), garabato(2)
    pA = os.path.join(tmp, 'A.png'); firmaA.save(pA)
    pB = os.path.join(tmp, 'B.png'); firmaB.save(pB)
    # misma firma reescalada y recomprimida a JPEG (otro byte-stream, mismos pixeles)
    pA2 = os.path.join(tmp, 'A2.jpg')
    firmaA.resize((392, 133), Image.LANCZOS).save(pA2, 'JPEG', quality=88)

    casos = {
        # nombre_archivo (cedula distinta = paciente distinto) -> imagen de firma
        '1111111111_INCAPACIDAD.pdf': pA,   # firma A
        '2222222222_INCAPACIDAD.pdf': pA,   # firma A IDENTICA, otro paciente -> EXACTO
        '3333333333_INCAPACIDAD.pdf': pA2,  # firma A reescalada/recomprimida -> PERCEPTUAL
        '4444444444_INCAPACIDAD.pdf': pB,   # firma distinta -> no debe disparar (control -)
    }
    rutas = {}
    for nombre, img in casos.items():
        out = os.path.join(tmp, nombre)
        pdf = FPDF(unit='pt', format=(612, 792))
        pdf.add_page()
        pdf.set_font('helvetica', size=9)
        pdf.set_xy(40, 60)
        pdf.cell(0, 12, 'CERTIFICADO DE INCAPACIDAD (documento sintetico de prueba)')
        pdf.set_xy(40, 80)
        pdf.cell(0, 12, 'PACIENTE CC %s' % nombre[:10])
        pdf.image(img, x=200, y=380, w=180)     # zona media = candidata a firma
        pdf.output(out)
        rutas[nombre] = out

    docs = {}
    for nombre, ruta in rutas.items():
        rec = recursos_pdf(ruta)
        for r in rec:
            r['rol'] = clasificar_rol(r)
            r['texto_recorte'] = ''
            r['ids_en_recorte'] = []
            r['es_marca_herramienta'] = False
            r['es_marca_proveedor'] = False
        docs[nombre] = {'etiqueta': 'sintetico', 'cuarentena': 'no', 'ext': 'pdf',
                        'recursos': rec}
    man = {n: {'archivo': n, 'ext': 'pdf', 'ruta_original': r} for n, r in rutas.items()}
    ident = identidades(man, {})
    res = correr_checks(docs, ident)

    E, P, R = ('FIRMA_REUSO_EXACTO_CROSS_PACIENTE',
               'FIRMA_REUSO_PERCEPTUAL_CROSS_PACIENTE', 'FIRMA_REUSO_RECOMPRIMIDA')
    # docs 1 y 2 comparten la firma byte a byte (EXACTO) y ademas coinciden
    # perceptualmente con la copia reescalada del doc 3 (PERCEPTUAL + RECOMPRIMIDA).
    esperado = {
        '1111111111_INCAPACIDAD.pdf': {E, P, R},
        '2222222222_INCAPACIDAD.pdf': {E, P, R},
        '3333333333_INCAPACIDAD.pdf': {P, R},
        '4444444444_INCAPACIDAD.pdf': set(),
    }
    fallos = 0
    print('AUTOTEST (control positivo/negativo con firmas sinteticas)')
    print('  %d grupos de paciente para %d documentos' % (
        len({ident[a]['id_paciente'] for a in docs}), len(docs)))
    for a in sorted(docs):
        nfir = sum(1 for r in docs[a]['recursos'] if r.get('rol') == 'FIRMA_SELLO_CAND')
        got = {c for c in CHECKS_ACUSATORIOS if res[a][c]['hit']}
        exp = esperado[a]
        ok = got == exp
        fallos += 0 if ok else 1
        print('  %-34s nFir=%d  esperado=%-58s obtenido=%-58s %s'
              % (a, nfir, ','.join(sorted(exp)) or '(ninguno)',
                 ','.join(sorted(got)) or '(ninguno)', 'OK' if ok else 'FALLA'))
    print('  resultado: %s' % ('TODOS OK' if fallos == 0 else '%d FALLAS' % fallos))
    return 1 if fallos else 0


def main() -> None:
    if '--autotest' in sys.argv:
        sys.exit(autotest())
    recalc = '--recalcular' in sys.argv
    man = {r['archivo']: r for r in csv.DictReader(
        open(os.path.join(BASE, 'manifest.csv'), encoding='utf-8'))}

    if os.path.exists(CACHE) and not recalc:
        docs = json.load(open(CACHE, encoding='utf-8'))
        print('[cache] recursos leidos de %s (usa --recalcular para rehacer)' % os.path.basename(CACHE))
    else:
        docs = {}
        for a, r in man.items():
            try:
                rec = (recursos_pdf(r['ruta_original']) if r['ext'].lower() == 'pdf'
                       else recursos_raster(r['ruta_original']))
            except Exception as e:
                rec = [{'error_doc': repr(e)[:200]}]
            for x in rec:
                x['rol'] = clasificar_rol(x)
            docs[a] = {'etiqueta': r['etiqueta'], 'cuarentena': r['cuarentena'],
                       'ext': r['ext'], 'recursos': rec}
        print('[extraer] %d documentos, %d recursos graficos'
              % (len(docs), sum(len(d['recursos']) for d in docs.values())))
        ocr_recortes(docs, man)
        marcar_semantica(docs)
        json.dump(docs, open(CACHE, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)

    ident = identidades(man, cargar_ocr_fase())
    res = correr_checks(docs, ident)

    # ---------------- salida: una linea por documento ------------------------
    ab = {'FIRMA_REUSO_EXACTO_CROSS_PACIENTE': 'FIRMA-EXACT',
          'FIRMA_REUSO_PERCEPTUAL_CROSS_PACIENTE': 'FIRMA-PERC',
          'FIRMA_REUSO_RECOMPRIMIDA': 'FIRMA-RECOMP',
          'FONDO_REUSO_CROSS_PACIENTE': 'FONDO-REUSO',
          'FIRMA_ID_INCOHERENTE': 'FIRMA-ID-INCOH',
          'MEMBRETE_COMPARTIDO': 'membrete',
          'MARCA_HERRAMIENTA_CAPTURA': 'marca-tool',
          'FIRMA_MEDICO_AUSENTE': 'firma-ausente'}
    grupos = defaultdict(list)
    for a in docs:
        grupos[ident[a]['id_paciente']].append(a)
    print('\n[agrupacion] %d documentos -> %d grupos de paciente; grupos con >1 doc:'
          % (len(docs), len(grupos)))
    for g, lst in sorted(grupos.items()):
        if len(lst) > 1:
            print('   %s : %s' % (g, ' | '.join(x[:38] for x in sorted(lst))))

    print()
    print('%-58s %-6s %-4s %-4s %-4s %-12s  %s'
          % ('ARCHIVO', 'ETIQ', 'CUAR', 'nRec', 'nFir', 'RESULTADO', 'CHECKS QUE DISPARAN'))
    print('-' * 155)
    for a in sorted(docs, key=lambda x: (docs[x]['etiqueta'], x)):
        d = docs[a]
        nfir = sum(1 for r in d['recursos'] if r.get('rol') == 'FIRMA_SELLO_CAND')
        hits = [ab[c] for c in CHECKS if c in ab and res[a][c]['hit']]
        acus = [c for c in CHECKS_ACUSATORIOS if res[a][c]['hit']]
        ver = 'SOSPECHOSO' if acus else 'sin-senal'
        print('%-58s %-6s %-4s %4d %4d %-12s  %s'
              % (a[:58], d['etiqueta'], d['cuarentena'], len(d['recursos']), nfir,
                 ver, ','.join(hits) if hits else '-'))

    # ---------------- medicion ----------------------------------------------
    ev = [a for a in docs if docs[a]['cuarentena'] != 'si']
    fal = [a for a in ev if docs[a]['etiqueta'] == 'falsa']
    rea = [a for a in ev if docs[a]['etiqueta'] == 'real']
    det = [a for a in fal if any(res[a][c]['hit'] for c in CHECKS_ACUSATORIOS)]
    fp = [a for a in rea if any(res[a][c]['hit'] for c in CHECKS_ACUSATORIOS)]

    print()
    print('=' * 150)
    print('MEDICION (excluye los %d documentos en CUARENTENA)'
          % sum(1 for a in docs if docs[a]['cuarentena'] == 'si'))
    print('  FALSAS detectadas : %d / %d' % (len(det), len(fal)))
    print('  REALES marcadas   : %d / %d  (falsos positivos)' % (len(fp), len(rea)))
    for a in det:
        print('    [DET] %s -> %s' % (a[:60], ','.join(c for c in CHECKS_ACUSATORIOS if res[a][c]['hit'])))
    for a in fp:
        print('    [ FP] %s -> %s' % (a[:60], ','.join(c for c in CHECKS_ACUSATORIOS if res[a][c]['hit'])))
    print()
    print('  Por check. "hit" = disparo; "n.ev" = documentos donde el check NO es')
    print('  evaluable (no puede dar positivo ni negativo) sobre los %d evaluables.' % len(ev))
    print('  %-40s %-11s %-11s %-6s %s' % ('CHECK', 'hit falsas', 'hit reales', 'n.ev', 'tipo'))
    tipo = {c: ('acusatorio' if c in CHECKS_ACUSATORIOS else 'informativo') for c in CHECKS}
    for c in CHECKS:
        nf = sum(1 for a in fal if res[a][c]['hit'])
        nr = sum(1 for a in rea if res[a][c]['hit'])
        ne = sum(1 for a in ev if res[a][c].get('no_evaluable'))
        print('  %-40s %d/%-9d %d/%-9d %-6d %s' % (c, nf, len(fal), nr, len(rea), ne, tipo[c]))

    json.dump({'umbrales': UMB, 'identidades_hash': {a: {k: v for k, v in ident[a].items()
                                                         if k != 'texto'} for a in ident},
               'resultado': res,
               'medicion': {'evaluables': len(ev), 'falsas_totales': len(fal),
                            'reales_totales': len(rea), 'falsas_detectadas': len(det),
                            'reales_marcadas': len(fp),
                            'detectadas': det, 'falsos_positivos': fp}},
              open(SALIDA, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    print('\n[ok] detalle -> %s' % SALIDA)


if __name__ == '__main__':
    main()
