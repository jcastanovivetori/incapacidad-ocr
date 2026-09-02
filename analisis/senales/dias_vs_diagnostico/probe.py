# -*- coding: utf-8 -*-
"""
Sonda de la familia de senales  dias_vs_diagnostico  (motivo declarado por el area:
"NO CONCUERDA EL NUMERO DE DIAS CON EL DIAGNOSTICO").

100% LOCAL. No sale ni un byte a internet: solo lee los artefactos ya producidos en
`dataset-falsedad/` y la capa de texto de los PDF con pypdfium2 (misma libreria que ya
usa `incapacidad_ocr.preprocess`). No importa ni modifica el paquete `incapacidad_ocr`.

AVISO PII: la salida de esta sonda es un artefacto derivado de historia clinica. Por
defecto NO imprime el codigo CIE-10 completo (solo el CAPITULO y si el codigo cae en un
bloque con piso legal). Use `--con-codigos` solo para depurar en local.

Checks implementados (detalle y justificacion en INFORME.md):

  DXDIAS_PAR_LEGIBLE               cobertura / compuerta de la familia (determinista)
  DIAS_BAJO_MINIMO_LEGAL_ABORTO    piso legal CST art. 237 (determinista, evaluable hoy)
  DIAS_VS_MINIMO_LEGAL_MATERNIDAD  piso legal CST art. 236 / Ley 2114-2021 (determinista)
  DIAS_LARGOS_SIN_DX_VERIFICABLE   riesgo de cobertura, NO afirma falsedad (determinista)
  DIAS_VS_DX_RANGO_HISTORICO       percentiles por CIE-10 del historico del ERP (heuristico)
                                   -> requiere `referencia_dias_por_dx.json`; sin el archivo
                                      devuelve SIN_INSUMO y NO inventa rangos clinicos.

Uso:
  <python-del-proyecto> probe.py [--con-codigos] [--json]

  --con-codigos  imprime el CIE-10 completo (PII; solo depuracion local)
  --json         escribe `medicion.json` en el directorio de la sonda
"""

from __future__ import annotations

import argparse
import csv
import datetime as _dt
import io
import json
import os
import re
import sys

AQUI = os.path.dirname(os.path.abspath(__file__))
DATASET = os.path.abspath(os.path.join(AQUI, "..", ".."))
DOCS = os.path.join(DATASET, "docs")
OCR = os.path.join(DATASET, "ocr")
MANIFEST = os.path.join(DATASET, "manifest.csv")
GROUND_TRUTH = os.path.join(DATASET, "ground_truth.json")
REFERENCIA = os.path.join(AQUI, "referencia_dias_por_dx.json")

DIAS_MIN, DIAS_MAX = 1, 540          # rango valido de dias (regla de dominio del repo)
DIAS_LARGOS = 30                     # umbral de "incapacidad prolongada" para la compuerta
N_MIN_HISTORICO = 30                 # n minimo por celda para usar percentiles del historico

# --------------------------------------------------------------------------- #
# Pisos/rangos de dias con ANCLA LEGAL (no clinica). Es lo unico que se puede
# afirmar hoy sin historico: son normas escritas, no juicio medico.
#   * CST art. 237 - licencia por aborto: descanso remunerado de DOS a CUATRO
#     semanas -> 14..28 dias. Aplica a "embarazo terminado en aborto" (O00-O08).
#   * CST art. 236 (mod. Ley 2114 de 2021) - licencia de maternidad: 18 semanas
#     -> 126 dias (140 si parto multiple; se suma la diferencia si es pretermino).
# Los rangos por diagnostico CLINICO (cuantos dias "toca" una lumbalgia) NO estan
# aqui a proposito: no existe norma local que los fije y no se inventan.
# --------------------------------------------------------------------------- #
PISOS_LEGALES = [
    {
        "check": "DIAS_BAJO_MINIMO_LEGAL_ABORTO",
        "bloque": "O00-O08",
        "prefijos": ("O00", "O01", "O02", "O03", "O04", "O05", "O06", "O07", "O08"),
        "min_dias": 14,
        "max_dias": 28,
        "norma": "CST art. 237 (2 a 4 semanas de descanso remunerado)",
        "severidad": "ALERTA",
    },
    {
        "check": "DIAS_VS_MINIMO_LEGAL_MATERNIDAD",
        "bloque": "O80-O84 / Z37",
        "prefijos": ("O80", "O81", "O82", "O83", "O84", "Z37"),
        "min_dias": 126,
        "max_dias": 140,
        "norma": "CST art. 236 mod. Ley 2114 de 2021 (18 semanas)",
        "severidad": "AVISO",
    },
]

# Ancla de diagnostico: etiquetas vistas en los documentos reales del corpus.
RE_ANCLA_DX = re.compile(
    r"(?:DX|DIAGN[OÓ]STIC[OA]S?)[ \t]*"
    r"(?:PRINCIPAL(?:\s*INGRESO)?|INGRESO|QUE\s+GENERA\s+LA\s+INCAPACIDAD|\(S\))?"
    r"[ \t]*:?[ \t]*",
    re.I,
)
# CIE-10 tolerante al OCR y al kerning del PDF ("M 5 4. 5" -> M545).
RE_CIE = re.compile(r"\b([A-TV-Z])[ \t]*(\d)[ \t]*(\d)[ \t]*\.?[ \t]*(\d)?\b")
RE_PRORROGA = re.compile(r"pr[oó]rroga\s*:?\s*(s[ií]|no)", re.I)


# --------------------------------------------------------------------------- #
# Carga de insumos
# --------------------------------------------------------------------------- #
def cargar_manifest():
    with io.open(MANIFEST, encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


def cargar_ground_truth():
    """archivo -> lista de senales declaradas por el area (para contexto, no para calibrar)."""
    if not os.path.exists(GROUND_TRUTH):
        return {}
    with io.open(GROUND_TRUTH, encoding="utf-8") as fh:
        gt = json.load(fh)
    return {f["archivo"]: f.get("senales", []) for f in gt.get("filas", [])}


def cargar_ocr():
    """archivo -> json de OCR (los shards escribieron esquemas distintos; solo se usan
    las claves comunes: `archivo`, `texto_plano`, `incapacidad`)."""
    salida = {}
    for raiz, _dirs, ficheros in os.walk(OCR):
        for nombre in ficheros:
            if not nombre.lower().endswith(".json"):
                continue
            ruta = os.path.join(raiz, nombre)
            try:
                with io.open(ruta, encoding="utf-8") as fh:
                    d = json.load(fh)
            except Exception:
                continue
            clave = d.get("archivo") or os.path.splitext(nombre)[0]
            salida[clave] = d
    return salida


def cargar_referencia():
    """Tabla de percentiles de dias por CIE-10 derivada del historico del ERP.

    Formato esperado (lo produce la consulta SQL documentada en INFORME.md):
      {"generado": "...", "fuente": "ASTGU.lpausentismos", "n_total": 123456,
       "celdas": {"M54.5": {"nivel": "categoria4", "n": 812, "p05": 1, "p50": 3,
                            "p95": 15, "p99": 30, "max": 90}, ...}}
    """
    if not os.path.exists(REFERENCIA):
        return None
    with io.open(REFERENCIA, encoding="utf-8") as fh:
        return json.load(fh)


def ruta_documento(fila):
    sub = "falsas" if fila["etiqueta"] == "falsa" else "reales"
    return os.path.join(DOCS, sub, fila["archivo"])


# --------------------------------------------------------------------------- #
# Lectura del par (diagnostico, dias)
# --------------------------------------------------------------------------- #
def texto_capa_pdf(ruta):
    """Texto de la capa de texto del PDF (pypdfium2). '' si es imagen o no hay capa."""
    if not ruta.lower().endswith(".pdf") or not os.path.exists(ruta):
        return ""
    try:
        import pypdfium2 as pdfium
    except Exception:
        return ""
    try:
        pdf = pdfium.PdfDocument(ruta)
    except Exception:
        return ""
    trozos = []
    try:
        for i in range(len(pdf)):
            try:
                trozos.append(pdf[i].get_textpage().get_text_range() or "")
            except Exception:
                pass
    finally:
        try:
            pdf.close()
        except Exception:
            pass
    txt = "\n".join(trozos)
    return txt if len(txt.strip()) > 20 else ""


def normalizar_cie(m):
    codigo = (m.group(1) + m.group(2) + m.group(3)).upper()
    if m.group(4):
        codigo += "." + m.group(4)
    return codigo


def cie_anclado(texto):
    """Primer CIE-10 que aparece DESPUES de una etiqueta de diagnostico.

    El anclaje es lo que evita el falso positivo clasico: en un documento del corpus el
    extractor devolvio un codigo que en realidad venia de la cedula del medico mal leida
    por el OCR ("C.C.1073168481" -> "C.Q073168481" -> "Q07.3"). Sin ancla, el check de
    dias-vs-diagnostico habria opinado sobre un numero de cedula.
    """
    if not texto:
        return None
    for m in RE_ANCLA_DX.finditer(texto):
        ventana = texto[m.end(): m.end() + 40]
        c = RE_CIE.search(ventana)
        if c:
            return normalizar_cie(c)
    return None


def leer_dias(inc):
    dias = inc.get("dias")
    if isinstance(dias, int) and DIAS_MIN <= dias <= DIAS_MAX:
        return dias, "campo"
    ini, fin = inc.get("fecha_inicio"), inc.get("fecha_fin")
    if ini and fin:
        try:
            d0 = _dt.date.fromisoformat(ini)
            d1 = _dt.date.fromisoformat(fin)
            n = (d1 - d0).days + 1
            if DIAS_MIN <= n <= DIAS_MAX:
                return n, "fechas"
        except Exception:
            pass
    return None, None


def leer_par(fila, doc_ocr):
    """Devuelve el par (cie10, dias) con su procedencia y nivel de confianza."""
    inc_raiz = doc_ocr.get("incapacidad") or {}
    inc = inc_raiz.get("incapacidad") or {}
    dx = inc_raiz.get("diagnostico") or {}
    texto_ocr = doc_ocr.get("texto_plano") or ""
    capa = texto_capa_pdf(ruta_documento(fila))

    # Prioridad de la fuente del diagnostico: capa de texto anclada > OCR anclado >
    # campo del extractor sin ancla (confianza BAJA: en el corpus produjo 'IDENTI',
    # 'FECHA', '0039' y un codigo salido de una cedula).
    cie = cie_anclado(capa)
    fuente, confianza = "capa_texto", "ALTA"
    if not cie:
        cie = cie_anclado(texto_ocr)
        fuente, confianza = "ocr_anclado", "ALTA"
    if not cie:
        crudo = (dx.get("cie10") or "").upper().replace(" ", "")
        m = RE_CIE.match(crudo)
        cie = normalizar_cie(m) if m else None
        fuente, confianza = ("extractor", "BAJA") if cie else (None, "NULA")

    dias, fuente_dias = leer_dias(inc)

    texto_todo = (capa + "\n" + texto_ocr)
    mp = RE_PRORROGA.search(texto_todo)
    prorroga = None
    if mp:
        prorroga = not mp.group(1).lower().startswith("no")

    return {
        "cie10": cie,
        "cie_capitulo": cie[0] if cie else None,
        "cie_fuente": fuente,
        "cie_confianza": confianza,
        "dias": dias,
        "dias_fuente": fuente_dias,
        "prorroga": prorroga,
        "tipo_documento": inc_raiz.get("tipo_documento"),
        "tiene_capa_texto": bool(capa),
    }


def piso_de(cie):
    if not cie:
        return None
    for p in PISOS_LEGALES:
        if cie.replace(".", "").startswith(p["prefijos"]):
            return p
    return None


# --------------------------------------------------------------------------- #
# Checks
# --------------------------------------------------------------------------- #
def check_par_legible(par):
    """DXDIAS_PAR_LEGIBLE - compuerta: sin par (dx, dias) la familia no puede opinar."""
    if par["tipo_documento"] in ("permiso", "vacaciones"):
        return "NO_APLICA", "el documento no es una incapacidad (sin diagnostico por diseno)"
    faltan = []
    if par["dias"] is None:
        faltan.append("dias")
    if not par["cie10"]:
        faltan.append("cie10")
    elif par["cie_confianza"] != "ALTA":
        faltan.append("cie10_confiable")
    if faltan:
        return "NO_EVALUABLE", "falta " + "+".join(faltan)
    return "OK", "par (cie10, dias) legible con confianza ALTA"


def check_piso_legal(par):
    """DIAS_BAJO_MINIMO_LEGAL_ABORTO / DIAS_VS_MINIMO_LEGAL_MATERNIDAD."""
    if par["dias"] is None or not par["cie10"] or par["cie_confianza"] != "ALTA":
        return None, "NO_EVALUABLE", "sin par (dx, dias) de confianza"
    piso = piso_de(par["cie10"])
    if not piso:
        return None, "NO_APLICA", "el diagnostico no cae en un bloque con duracion fijada por norma"
    if par["prorroga"] is True:
        return piso["check"], "NO_APLICA", "el documento se declara prorroga: el piso aplica al episodio, no al certificado"
    if par["dias"] < piso["min_dias"]:
        # La severidad la fija la tabla, no el codigo: el piso del aborto es duro
        # (ALERTA) porque no hay lectura legitima de "2 dias por aborto" en un
        # certificado inicial; el de maternidad es AVISO porque la licencia se puede
        # fraccionar y porque un codigo de parto tambien aparece en certificados de
        # complicacion posparto, que si son cortos.
        return piso["check"], ("SOSPECHA" if piso["severidad"] == "ALERTA" else "AVISO"), (
            "dias=%d < minimo legal %d del bloque %s (%s)"
            % (par["dias"], piso["min_dias"], piso["bloque"], piso["norma"])
        )
    if par["dias"] > piso["max_dias"]:
        return piso["check"], "AVISO", (
            "dias=%d > maximo legal %d del bloque %s (puede ser prorroga o complicacion)"
            % (par["dias"], piso["max_dias"], piso["bloque"])
        )
    return piso["check"], "OK", "dias dentro del rango fijado por norma para el bloque %s" % piso["bloque"]


def check_dias_largos_sin_dx(par):
    """DIAS_LARGOS_SIN_DX_VERIFICABLE - NO afirma falsedad; pide ojo humano."""
    if par["dias"] is None:
        return "NO_EVALUABLE", "sin dias"
    if par["dias"] < DIAS_LARGOS:
        return "NO_APLICA", "incapacidad corta (<%d dias)" % DIAS_LARGOS
    if par["cie10"] and par["cie_confianza"] == "ALTA":
        return "OK", "incapacidad prolongada con diagnostico legible"
    return "REVISION", (
        "dias=%d (prolongada) y el diagnostico no se pudo leer con confianza -> "
        "ningun check de la familia puede validarla" % par["dias"]
    )


def _percentiles_celda(ref, cie):
    """Backoff codigo4 -> categoria3 -> capitulo, exigiendo n >= N_MIN_HISTORICO."""
    if not ref or not cie:
        return None
    celdas = ref.get("celdas") or {}
    for clave in (cie, cie.replace(".", ""), cie[:3], cie[0]):
        c = celdas.get(clave)
        if c and int(c.get("n", 0)) >= N_MIN_HISTORICO:
            return dict(c, clave=clave)
    return None


def check_rango_historico(par, ref):
    """DIAS_VS_DX_RANGO_HISTORICO - el check "natural" de la familia. Heuristico."""
    if ref is None:
        return "SIN_INSUMO", (
            "no existe %s: hace falta el historico del ERP (ASTGU.lpausentismos)"
            % os.path.basename(REFERENCIA)
        )
    if par["dias"] is None or not par["cie10"] or par["cie_confianza"] != "ALTA":
        return "NO_EVALUABLE", "sin par (dx, dias) de confianza"
    # Dos guardas que la prueba de humo demostro imprescindibles (sin ellas, con
    # percentiles a nivel de CAPITULO se marcaron 2 documentos REALES):
    #  a) si la duracion la fija una norma (aborto, maternidad), manda el piso legal:
    #     esos tipos estan EXCLUIDOS del universo historico, comparar es un error de
    #     poblacion (el real de 126 dias = licencia de maternidad salia SOSPECHA).
    #  b) el historico solo contiene CERTIFICADOS INICIALES (prorroga=0): un documento
    #     que se declara prorroga no pertenece a esa distribucion (el real de 30 dias
    #     con "Prorroga: SI" salia SOSPECHA).
    if piso_de(par["cie10"]):
        return "NO_APLICA", "duracion fijada por norma: manda el check de piso legal, no el percentil"
    if par["prorroga"] is True:
        return "NO_APLICA", "el documento se declara prorroga y el historico solo tiene certificados iniciales"
    celda = _percentiles_celda(ref, par["cie10"])
    if not celda:
        return "SIN_INSUMO", "el diagnostico no tiene n>=%d en el historico" % N_MIN_HISTORICO
    d = par["dias"]
    if d > celda["p99"] and d > 3 * max(1, celda["p50"]):
        return "SOSPECHA", "dias=%d > p99=%s y > 3x p50=%s (n=%s, nivel=%s)" % (
            d, celda["p99"], celda["p50"], celda["n"], celda.get("nivel"))
    if d > celda["p95"]:
        return "AVISO", "dias=%d > p95=%s (n=%s)" % (d, celda["p95"], celda["n"])
    if d < celda["p05"] and piso_de(par["cie10"]):
        return "AVISO", "dias=%d < p05=%s en un bloque con piso legal" % (d, celda["p05"])
    return "OK", "dias=%d dentro de p05..p95 (%s..%s, n=%s)" % (
        d, celda["p05"], celda["p95"], celda["n"])


# --------------------------------------------------------------------------- #
# Corrida
# --------------------------------------------------------------------------- #
def evaluar(fila, doc_ocr, ref):
    par = leer_par(fila, doc_ocr)
    res = {}
    res["DXDIAS_PAR_LEGIBLE"] = check_par_legible(par)
    cid, estado, motivo = check_piso_legal(par)
    res["PISO_LEGAL"] = (estado, motivo, cid)
    res["DIAS_LARGOS_SIN_DX_VERIFICABLE"] = check_dias_largos_sin_dx(par)
    res["DIAS_VS_DX_RANGO_HISTORICO"] = check_rango_historico(par, ref)

    sospechas, avisos, revisiones = [], [], []
    for cid_, val in (
        (res["PISO_LEGAL"][2] or "PISO_LEGAL", res["PISO_LEGAL"][:2]),
        ("DIAS_VS_DX_RANGO_HISTORICO", res["DIAS_VS_DX_RANGO_HISTORICO"]),
    ):
        if val[0] == "SOSPECHA":
            sospechas.append((cid_, val[1]))
        elif val[0] == "AVISO":
            avisos.append((cid_, val[1]))
    if res["DIAS_LARGOS_SIN_DX_VERIFICABLE"][0] == "REVISION":
        revisiones.append(("DIAS_LARGOS_SIN_DX_VERIFICABLE",
                           res["DIAS_LARGOS_SIN_DX_VERIFICABLE"][1]))

    # Precedencia: SOSPECHA > REVISION > AVISO > NO_APLICA > NO_EVALUABLE > OK.
    # REVISION va antes que NO_EVALUABLE a proposito: "no pude leer el diagnostico Y son
    # muchos dias" es mas informativo que "no pude leer el diagnostico".
    if sospechas:
        veredicto = "SOSPECHA"
    elif revisiones:
        veredicto = "REVISION"
    elif avisos:
        veredicto = "AVISO"
    elif res["DXDIAS_PAR_LEGIBLE"][0] == "NO_APLICA":
        veredicto = "NO_APLICA"
    elif res["DXDIAS_PAR_LEGIBLE"][0] == "NO_EVALUABLE":
        veredicto = "NO_EVALUABLE"
    else:
        veredicto = "OK"

    return par, res, veredicto, sospechas, avisos, revisiones


def main(argv=None):
    ap = argparse.ArgumentParser(description="Sonda de la familia dias_vs_diagnostico")
    ap.add_argument("--con-codigos", action="store_true",
                    help="imprime el CIE-10 completo (PII; solo depuracion local)")
    ap.add_argument("--json", action="store_true", help="escribe medicion.json")
    args = ap.parse_args(argv)

    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    manifest = cargar_manifest()
    ocr = cargar_ocr()
    gt = cargar_ground_truth()
    ref = cargar_referencia()

    print("SONDA dias_vs_diagnostico  (100%% local; artefacto derivado de historia clinica)")
    print("referencia historica del ERP: %s" % ("CARGADA" if ref else "AUSENTE -> el check central devuelve SIN_INSUMO"))
    print("")
    cab = "%-5s %-2s %5s %-3s %-4s %-9s %-11s %s" % (
        "ETIQ", "Q", "DIAS", "CAP", "CONF", "PISO", "VEREDICTO", "ARCHIVO")
    print(cab)
    print("-" * len(cab))

    filas_salida = []
    for fila in sorted(manifest, key=lambda f: (f["etiqueta"], f["archivo"])):
        doc = ocr.get(fila["archivo"]) or ocr.get(os.path.splitext(fila["archivo"])[0]) or {}
        par, res, veredicto, sosp, avis, revs = evaluar(fila, doc, ref)
        piso = piso_de(par["cie10"])
        etiqueta_piso = piso["bloque"].split(" ")[0] if piso else "-"
        cie_vis = par["cie10"] if args.con_codigos else (par["cie_capitulo"] or "-")
        print("%-5s %-2s %5s %-3s %-4s %-9s %-11s %s" % (
            fila["etiqueta"], fila["cuarentena"],
            par["dias"] if par["dias"] is not None else "-",
            (cie_vis or "-")[:3] if not args.con_codigos else (cie_vis or "-"),
            par["cie_confianza"], etiqueta_piso, veredicto, fila["archivo"]))
        motivo = (sosp or avis or revs or [(None, res["DXDIAS_PAR_LEGIBLE"][1])])[0][-1]
        print("        %s | dx=%s dias=%s prorroga=%s | %s" % (
            veredicto, par["cie_fuente"], par["dias_fuente"], par["prorroga"], motivo))
        filas_salida.append({
            "archivo": fila["archivo"],
            "etiqueta": fila["etiqueta"],
            "cuarentena": fila["cuarentena"],
            "senales_declaradas": gt.get(fila["archivo"], []),
            "dias": par["dias"],
            "cie_capitulo": par["cie_capitulo"],
            "cie10": par["cie10"] if args.con_codigos else None,
            "cie_fuente": par["cie_fuente"],
            "cie_confianza": par["cie_confianza"],
            "prorroga": par["prorroga"],
            "tiene_capa_texto": par["tiene_capa_texto"],
            "veredicto": veredicto,
            "checks": {k: (v[0], v[1]) for k, v in res.items()},
            "sospechas": [s[0] for s in sosp],
        })

    # ------------------------------ medicion ------------------------------- #
    util = [f for f in filas_salida if f["cuarentena"] != "si"]
    cuar = [f for f in filas_salida if f["cuarentena"] == "si"]
    falsas = [f for f in util if f["etiqueta"] == "falsa"]
    reales = [f for f in util if f["etiqueta"] == "real"]
    fam = [f for f in util if "DIAS_VS_DIAGNOSTICO" in f["senales_declaradas"]]

    det_falsas = [f for f in falsas if f["veredicto"] == "SOSPECHA"]
    fp_reales = [f for f in reales if f["veredicto"] == "SOSPECHA"]
    det_fam = [f for f in fam if f["veredicto"] == "SOSPECHA"]
    evaluables = [f for f in util if f["checks"]["DXDIAS_PAR_LEGIBLE"][0] == "OK"]
    rev_reales = [f for f in reales if f["veredicto"] == "REVISION"]
    avi_reales = [f for f in reales if f["veredicto"] == "AVISO"]

    print("")
    print("=" * 78)
    print("MEDICION (excluye los %d documentos en CUARENTENA del manifest)" % len(cuar))
    print("=" * 78)
    print("corpus utilizable            : %d (%d falsas + %d reales)" % (len(util), len(falsas), len(reales)))
    print("pares (dx, dias) legibles    : %d de %d  -> cobertura %.0f%%" % (
        len(evaluables), len(util), 100.0 * len(evaluables) / max(1, len(util))))
    print("FALSAS con SOSPECHA           : %d de %d" % (len(det_falsas), len(falsas)))
    print("  de ellas, de esta familia   : %d de %d falsas con motivo DIAS_VS_DIAGNOSTICO" % (
        len(det_fam), len(fam)))
    print("REALES con SOSPECHA (FP)      : %d de %d" % (len(fp_reales), len(reales)))
    print("REALES en AVISO               : %d   REALES en REVISION: %d" % (len(avi_reales), len(rev_reales)))
    for f in det_falsas:
        print("  + detectada  : %s  [%s]" % (f["archivo"], ",".join(f["sospechas"])))
    for f in fp_reales:
        print("  ! FALSO POSITIVO: %s  [%s]" % (f["archivo"], ",".join(f["sospechas"])))
    for f in rev_reales:
        print("  ~ revision   : %s" % f["archivo"])
    print("")
    print("Cuarentena (documentado, NO cuenta): %s" % ", ".join(f["archivo"] for f in cuar))

    if args.json:
        salida = {
            "generado": _dt.datetime.now().isoformat(timespec="seconds"),
            "familia": "dias_vs_diagnostico",
            "referencia_historica": bool(ref),
            "totales": {
                "corpus": len(filas_salida), "utilizable": len(util),
                "cuarentena": len(cuar), "falsas": len(falsas), "reales": len(reales),
                "pares_legibles": len(evaluables),
                "falsas_detectadas": len(det_falsas), "reales_marcadas": len(fp_reales),
                "reales_aviso": len(avi_reales), "reales_revision": len(rev_reales),
                "familia_declarada": len(fam), "familia_detectada": len(det_fam),
            },
            "documentos": filas_salida,
        }
        with io.open(os.path.join(AQUI, "medicion.json"), "w", encoding="utf-8") as fh:
            json.dump(salida, fh, ensure_ascii=False, indent=2)
        print("escrito: %s" % os.path.join(AQUI, "medicion.json"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
