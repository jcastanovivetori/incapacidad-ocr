"""Genera las tablas de ESTADO_CORPUS.md a partir de los artefactos ya medidos.

100% local. No imprime PII: identifica documentos por sha8 y por un id de titular
opaco (F1..F7 / L1..L15) derivado de la agrupacion, nunca por nombre ni cedula.
"""
import csv
import json
import re
import collections

# --- Rutas relativas (añadidas por scripts/exportar_analisis.py) --------------------------
# Este script se escribió con rutas ABSOLUTAS de la máquina donde se investigó. Se resuelven
# desde la ubicación del propio archivo para que funcione tras un `git pull` en cualquier
# equipo. El corpus (`dataset-falsedad/`) NO está en el repositorio: lo aporta el cliente.
import pathlib as _pl
_REPO = _pl.Path(__file__).resolve().parents[1]
_DATASET = _REPO.parent / "dataset-falsedad"
_EJEMPLOS = _REPO.parent / "Ejemplos"
# ------------------------------------------------------------------------------------------

BASE = str(_DATASET)

man = list(csv.DictReader(open(BASE + 'manifest.csv', encoding='utf-8')))
gt = {r['archivo']: r for r in json.load(open(BASE + 'ground_truth.json', encoding='utf-8'))['filas']}
dx = {d['archivo']: d for d in json.load(open(BASE + 'senales/dx_catalogo/resultados.json', encoding='utf-8'))['resultados']}
af = {d['archivo']: d for d in json.load(open(BASE + 'senales/aritmetica_fechas/resultados.json', encoding='utf-8'))['documentos']}
tp = {d['archivo']: d for d in json.load(open(BASE + 'senales/tipografia_pdf/resultado.json', encoding='utf-8'))}
dd = {d['archivo']: d for d in json.load(open(BASE + 'senales/dias_vs_diagnostico/medicion.json', encoding='utf-8'))['documentos']}
fr = json.load(open(BASE + 'senales/firma_y_reuso/resultado.json', encoding='utf-8'))['resultado']


def clave_titular(a, et):
    if et == 'falsa':
        m = re.match(r'INC (.+?) \d', a)
        # 'FALSA-15.pdf' comparte titular con el grupo <NOMBRE> <NOMBRE>
        return m.group(1) if m else '<NOMBRE> <NOMBRE> <NOMBRE> <NOMBRE>'
    return a.split('_')[0]


ids = {}
for r in man:
    k = clave_titular(r['archivo'], r['etiqueta'])
    if k not in ids:
        pref = 'F' if r['etiqueta'] == 'falsa' else 'L'
        ids[k] = pref + str(1 + sum(1 for v in ids.values() if v[0] == pref))


def familias(a):
    c = dx.get(a, {})
    dxap = bool(c.get('aplica')) and c.get('checks', {}).get('DX_FORMATO_LONGITUD', {}).get('estado') != 'no_verificable'
    dxh = c.get('checks', {}).get('DX_FORMATO_LONGITUD', {}).get('estado') == 'dispara'
    x = af.get(a, {})
    afap, afh = bool(x.get('tripleta_completa')), bool(x.get('hallazgos'))
    t = tp.get(a, {})
    tpap, tph = t.get('estado') != 'NO_APLICABLE', bool(t.get('disparados'))
    y = dd.get(a, {})
    ddap = y.get('checks', {}).get('DXDIAS_PAR_LEGIBLE', ['', ''])[0] == 'OK'
    ddh = y.get('veredicto') == 'SOSPECHA'
    z = fr.get(a, {})
    frap = 'no_evaluable' not in z.get('FIRMA_REUSO_EXACTO_CROSS_PACIENTE', {})
    frh = any(z.get(k, {}).get('hit') for k in (
        'FIRMA_REUSO_EXACTO_CROSS_PACIENTE', 'FIRMA_REUSO_PERCEPTUAL_CROSS_PACIENTE',
        'FIRMA_REUSO_RECOMPRIMIDA', 'FONDO_REUSO_CROSS_PACIENTE', 'FIRMA_ID_INCOHERENTE'))
    nombres = ('fechas', 'tipografia', 'dx', 'dias', 'firma')
    aps = (afap, tpap, dxap, ddap, frap)
    hits = (afh, tph, dxh, ddh, frh)
    return sum(aps), [n for n, h in zip(nombres, hits) if h]


def ext(r):
    return r['ext'] + ('/' + r['paginas'] + 'p' if r['paginas'] else '')


BT = chr(96)


def sha(r):
    return BT + r['sha256'][:8] + BT


print('### FALSAS')
for r in man:
    if r['etiqueta'] != 'falsa':
        continue
    a = r['archivo']
    g = gt.get(a, {})
    n, hh = familias(a)
    cua = 'SI' if r['cuarentena'] == 'si' else '-'
    print('| %s | %s | %s | %s | %s | %s | %d/5 | %s |' % (
        sha(r), ids[clave_titular(a, 'falsa')], ext(r), ', '.join(g.get('senales', [])),
        'ROJO' if g.get('en_rojo') else '-', cua, n, ', '.join(hh) or '**ninguna**'))

print()
print('### REALES')
for r in man:
    if r['etiqueta'] != 'real':
        continue
    a = r['archivo']
    n, hh = familias(a)
    tipo = re.sub(r'\..*', '', a.split('_')[-1]).upper()
    cua = 'SI' if r['cuarentena'] == 'si' else '-'
    print('| %s | %s | %s | %s | %s | %d/5 | %s |' % (
        sha(r), ids[clave_titular(a, 'real')], tipo, ext(r), cua, n, ', '.join(hh) or '-'))

print()
print('### AGREGADOS')
noq = [r for r in man if r['cuarentena'] == 'no']
for et in ('falsa', 'real'):
    sub = [r for r in noq if r['etiqueta'] == et]
    hist = collections.Counter(familias(r['archivo'])[0] for r in sub)
    print(et, 'n=%d' % len(sub), 'histograma familias aplicables:', dict(sorted(hist.items())))
    print('  con >=1 hit:', sum(1 for r in sub if familias(r['archivo'])[1]),
          ' con >=2 familias:', sum(1 for r in sub if len(familias(r['archivo'])[1]) >= 2))
    print('  titulares distintos:', len({ids[clave_titular(r['archivo'], et)] for r in sub}))
sig, sigev = collections.Counter(), collections.Counter()
for r in man:
    g = gt.get(r['archivo'])
    if not g:
        continue
    for s in g['senales']:
        sig[s] += 1
        if r['cuarentena'] == 'no':
            sigev[s] += 1
for s in sorted(sig):
    print('  senal %-24s total=%d evaluables=%d' % (s, sig[s], sigev[s]))
