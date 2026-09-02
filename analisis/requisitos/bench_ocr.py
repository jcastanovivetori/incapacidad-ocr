#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""bench_ocr.py — mide el coste POR DOCUMENTO del pipeline 100% local de incapacidad-ocr.

Qué mide (SERIALMENTE, un documento a la vez, un solo proceso):

  1. ARRANQUE (una sola vez, NO se cobra por documento):
     - tiempo de import del paquete,
     - tiempo de construcción de ``RapidOCRBackend()`` (carga de los modelos ONNX),
     - RSS del proceso justo después de tener el backend listo  -> ``ram_arranque_mb``.
  2. POR DOCUMENTO, desagregado en fases:
     - ``render``  : rasterizado de cada página del PDF con PDFium (``preprocess.load_pages``),
                     o decode del JPEG/PNG. Es el ``next()`` del generador de páginas.
     - ``ocr``     : ``RapidOCRBackend._ocr_one(page)`` (det+cls+rec ONNX en CPU).
     - ``combinar``: ``ocr._combinar_paginas`` (selección de páginas relevantes).
     - ``extract`` : ``RuleBasedExtractor.extract`` + ``extract.normalizar_fechas``.
     - ``total_fases`` = suma de las anteriores.
  3. CONTROL: el mismo documento por la API real ``IncapacidadProcessor.run(path)``,
     cronometrado de punta a punta. Sirve para verificar que la instrumentación por
     fases no distorsiona el total (se reporta el delta).
  4. RAM: pico de RSS por documento (hilo muestreador cada ``--sample-ms``) y
     ``peak_wset`` del proceso (pico de working set de todo el proceso, Windows).
  5. CONDICIONES: carga de CPU del sistema y CPU consumida por OTROS procesos durante
     cada pasada. Una medición hecha con la máquina ocupada NO es comparable con una
     limpia: el script la registra en vez de esconderla, y con ``--esperar-cpu`` se
     bloquea hasta que la máquina esté libre.

NO mide (a propósito): paralelismo con varios workers, Ollama (visión/LLM), MySQL.
Ver el informe ``02_benchmark.md`` para el alcance y las advertencias.

Uso típico (Windows / Git Bash):

    PY=<repo>/.venv/Scripts/python.exe

    # A) como corre hoy el servicio (ONNX usa todos los núcleos):
    $PY bench_ocr.py --repo <repo> \
        --docs <dataset-falsedad>/docs/falsas \
        --docs <dataset-falsedad>/docs/reales \
        --repeats 3 --esperar-cpu 25 --etiqueta "onnx-multihilo" \
        --out-json bench_multihilo.json

    # B) como prescribe PLAN_INGESTA_MASIVA.md §6.2 para un pool de N workers
    #    (1 hilo ONNX por worker -> este es el coste que se multiplica por W):
    $PY bench_ocr.py ... --hilos 1 --etiqueta "onnx-1hilo" --out-json bench_1hilo.json

Requisitos: el venv del proyecto (rapidocr-onnxruntime, pypdfium2, Pillow) + ``psutil``
(``python -m pip install psutil``). Todo local, sin red, sin Docker, sin servicios.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import statistics
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

# --- Rutas relativas (añadidas por scripts/exportar_analisis.py) --------------------------
# Este script se escribió con rutas ABSOLUTAS de la máquina donde se investigó. Se resuelven
# desde la ubicación del propio archivo para que funcione tras un `git pull` en cualquier
# equipo. El corpus (`dataset-falsedad/`) NO está en el repositorio: lo aporta el cliente.
import pathlib as _pl
_REPO = _pl.Path(__file__).resolve().parents[2]
_DATASET = _REPO.parent / "dataset-falsedad"
_EJEMPLOS = _REPO.parent / "Ejemplos"
# ------------------------------------------------------------------------------------------

EXTS = {".pdf", ".jpg", ".jpeg", ".png", ".tif", ".tiff", ".bmp", ".webp"}


# --------------------------------------------------------------------------- CLI
def parse_args(argv=None):
    p = argparse.ArgumentParser(
        description="Benchmark por documento del pipeline local (RapidOCR + reglas).",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument("--repo", default=str(Path(__file__).resolve().parents[2] / "incapacidad-ocr"),
                   help="Raíz del repo incapacidad-ocr (se inserta en sys.path).")
    p.add_argument("--docs", action="append", default=None, metavar="DIR",
                   help="Carpeta con documentos (repetible). Recursivo.")
    p.add_argument("--repeats", type=int, default=3,
                   help="Pasadas completas sobre el set. Por documento se reporta el "
                        "MÍNIMO (la observación menos contendida) y la mediana.")
    p.add_argument("--hilos", type=int, default=0,
                   help="intra_op_num_threads de cada sesión ONNX. 0 = default de "
                        "onnxruntime (= nº de núcleos físicos). 1 = lo que prescribe "
                        "PLAN_INGESTA_MASIVA.md §6.2 por worker del pool.")
    p.add_argument("--sample-ms", type=int, default=25, help="Periodo del muestreo de RSS.")
    p.add_argument("--esperar-cpu", type=float, default=0.0, metavar="PCT",
                   help="Antes de cada pasada, espera hasta que la CPU del sistema esté "
                        "por debajo de PCT%% (0 = no esperar). Ver --espera-max.")
    p.add_argument("--espera-max", type=float, default=1800.0,
                   help="Segundos máximos de espera por --esperar-cpu antes de rendirse.")
    p.add_argument("--sin-dedup", action="store_true",
                   help="No colapsar documentos con contenido idéntico (sha256).")
    p.add_argument("--sin-control", action="store_true",
                   help="Omite la pasada de control con IncapacidadProcessor.run().")
    p.add_argument("--etiqueta", default="", help="Etiqueta libre de la corrida.")
    p.add_argument("--out-json", default="bench_ocr.json", help="Salida JSON.")
    p.add_argument("--out-md", default="", help="(opcional) tabla Markdown por documento.")
    return p.parse_args(argv)


# ----------------------------------------------------------------- inventario
def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def geometria_pdf(path: Path, scale: float):
    """(nº páginas, megapíxeles de la página MAYOR al rasterizar a ``scale``).

    Los MP rasterizados son el predictor real del coste: RapidOCR usa
    ``limit_type='min'`` con ``limit_side_len=736``, así que si el lado corto de la
    página ya supera 736 px el detector NO reescala y corre a resolución completa
    -> el tiempo y la RAM crecen con el ÁREA de la página, no con su contenido.
    """
    import pypdfium2 as pdfium
    pdf = pdfium.PdfDocument(str(path))
    try:
        mp = 0.0
        for i in range(len(pdf)):
            w, h = pdf[i].get_size()
            mp = max(mp, (w * scale) * (h * scale) / 1e6)
        return len(pdf), round(mp, 1)
    finally:
        pdf.close()


def geometria_img(path: Path):
    from PIL import Image
    with Image.open(path) as im:
        return 1, round(im.width * im.height / 1e6, 1)


def inventariar(dirs, dedup=True, scale=3.0):
    """Descubre documentos, cuenta páginas y clasifica por tipo. Colapsa duplicados."""
    vistos, docs, dups = {}, [], []
    for d in dirs:
        raiz = Path(d)
        if not raiz.exists():
            print(f"[aviso] carpeta inexistente, se omite: {raiz}", file=sys.stderr)
            continue
        for f in sorted(raiz.rglob("*")):
            if not f.is_file() or f.suffix.lower() not in EXTS:
                continue
            h = sha256(f)
            if dedup and h in vistos:
                dups.append({"archivo": str(f), "duplicado_de": vistos[h], "sha8": h[:8]})
                continue
            vistos[h] = str(f)
            es_pdf = f.suffix.lower() == ".pdf"
            n, mp = geometria_pdf(f, scale) if es_pdf else geometria_img(f)
            tipo = "imagen" if not es_pdf else ("pdf_1pag" if n == 1 else "pdf_multipag")
            docs.append({"archivo": str(f), "nombre": f.name, "sha8": h[:8], "tipo": tipo,
                         "paginas": n, "mp_pagina_mayor": mp, "bytes": f.stat().st_size})
    return docs, dups


# ------------------------------------------------------------------ muestreo
class MuestreadorRSS(threading.Thread):
    """Muestrea el RSS del proceso en un hilo aparte -> pico por documento."""

    def __init__(self, proc, periodo_s: float):
        super().__init__(daemon=True)
        self.proc, self.periodo = proc, periodo_s
        self._stop = threading.Event()
        self.pico = 0

    def run(self):
        while not self._stop.is_set():
            try:
                self.pico = max(self.pico, self.proc.memory_info().rss)
            except Exception:
                pass
            self._stop.wait(self.periodo)

    def detener(self) -> int:
        self._stop.set()
        self.join(timeout=2.0)
        try:
            self.pico = max(self.pico, self.proc.memory_info().rss)
        except Exception:
            pass
        return self.pico


def esperar_cpu_libre(psutil_mod, umbral_pct: float, max_s: float):
    """Bloquea hasta que la CPU del sistema baje del umbral. Devuelve el diagnóstico."""
    t0 = time.perf_counter()
    consecutivas = 0
    ultima = None
    while time.perf_counter() - t0 < max_s:
        ultima = psutil_mod.cpu_percent(interval=2.0)
        consecutivas = consecutivas + 1 if ultima < umbral_pct else 0
        if consecutivas >= 3:                       # 3 lecturas seguidas por debajo
            return {"esperado_s": round(time.perf_counter() - t0, 1),
                    "cpu_pct_final": ultima, "logrado": True}
        print(f"    [espera] CPU del sistema {ultima:.0f}% >= {umbral_pct:.0f}% "
              f"({time.perf_counter() - t0:.0f}s)", file=sys.stderr)
    return {"esperado_s": round(time.perf_counter() - t0, 1),
            "cpu_pct_final": ultima, "logrado": False}


def top_procesos(psutil_mod, mi_pid: int, n: int = 6):
    """Procesos ajenos que más CPU usan en una ventana de 1 s (para 'condiciones')."""
    procs = []
    for p in psutil_mod.process_iter(["pid", "name"]):
        try:
            p.cpu_percent(None)
            procs.append(p)
        except Exception:
            pass
    time.sleep(1.0)
    filas = []
    for p in procs:
        try:
            pct = p.cpu_percent(None)
            if p.pid != mi_pid and pct > 5.0:
                filas.append({"pid": p.pid, "nombre": p.info.get("name"), "cpu_pct": round(pct, 1)})
        except Exception:
            pass
    return sorted(filas, key=lambda r: -r["cpu_pct"])[:n]


# ------------------------------------------------------------------- métricas
def pctl(vals, q):
    """Percentil por rango más cercano (nearest-rank). Determinista y sin interpolar."""
    if not vals:
        return None
    xs = sorted(vals)
    import math
    k = max(1, math.ceil(q * len(xs)))
    return xs[k - 1]


def resumen(vals):
    if not vals:
        return None
    return {"n": len(vals), "min": round(min(vals), 2), "p50": round(pctl(vals, 0.50), 2),
            "p90": round(pctl(vals, 0.90), 2), "max": round(max(vals), 2),
            "media": round(statistics.fmean(vals), 2)}


# --------------------------------------------------------------------- pipeline
def medir_doc(doc, backend, extractor, ocr_mod, preprocess_mod, extract_mod, proc, sample_s):
    """Una pasada instrumentada por fases sobre un documento.

    Replica exactamente ``RapidOCRBackend.read_text`` (generador de páginas ->
    _ocr_one por página -> _combinar_paginas) para poder cronometrar render y OCR
    por separado, y luego el extractor.

    Nota honesta: para IMÁGENES, ``Image.open`` es perezoso y el decode real ocurre
    dentro de ``np.asarray`` (fase OCR). Aquí se fuerza con ``img.load()`` en la fase
    render para que el decode quede atribuido a "render/decode". El TOTAL no cambia.
    """
    rss_inicio = proc.memory_info().rss
    mu = MuestreadorRSS(proc, sample_s)
    mu.start()
    cpu0 = proc.cpu_times()
    t_ini = time.perf_counter()

    t_render = t_ocr = 0.0
    textos, paginas = [], 0
    gen = preprocess_mod.load_pages(doc["archivo"])
    while True:
        t0 = time.perf_counter()
        try:
            page = next(gen)
        except StopIteration:
            t_render += time.perf_counter() - t0
            break
        try:                       # decode perezoso de PIL -> a la fase render
            page.load()
        except Exception:
            pass
        t_render += time.perf_counter() - t0
        paginas += 1
        t0 = time.perf_counter()
        textos.append(backend._ocr_one(page))
        t_ocr += time.perf_counter() - t0
        del page

    t0 = time.perf_counter()
    texto = ocr_mod._combinar_paginas(textos)
    t_comb = time.perf_counter() - t0

    t0 = time.perf_counter()
    if len(texto.strip()) < 10:                     # processor.MIN_OCR_CHARS
        rec, aviso = extract_mod.empty_record(), True
    else:
        rec = extractor.extract(texto)
        extract_mod.normalizar_fechas(rec)
        aviso = False
    t_ext = time.perf_counter() - t0

    total = time.perf_counter() - t_ini
    cpu1 = proc.cpu_times()
    pico = mu.detener()
    return {
        "render_s": round(t_render, 3), "ocr_s": round(t_ocr, 3),
        "combinar_s": round(t_comb, 4), "extract_s": round(t_ext, 4),
        "total_fases_s": round(total, 3),
        "cpu_propia_s": round((cpu1.user + cpu1.system) - (cpu0.user + cpu0.system), 2),
        "paginas_ocr": paginas, "chars_ocr": len(texto), "ocr_vacio": aviso,
        "pico_rss_mb": round(pico / 1048576, 1),
        "rss_inicio_mb": round(rss_inicio / 1048576, 1),
    }


def cpu_modelo() -> str:
    """Nombre comercial de la CPU (Windows: registro; Linux: /proc/cpuinfo)."""
    try:
        if platform.system() == "Windows":
            import winreg
            k = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
                               r"HARDWARE\DESCRIPTION\System\CentralProcessor\0")
            return winreg.QueryValueEx(k, "ProcessorNameString")[0].strip()
        for linea in Path("/proc/cpuinfo").read_text().splitlines():
            if linea.startswith("model name"):
                return linea.split(":", 1)[1].strip()
    except Exception:
        pass
    return platform.processor() or "desconocido"


def capar_hilos_onnx(n: int) -> bool:
    """Fija ``intra_op_num_threads=n`` en las sesiones ONNX de RapidOCR.

    rapidocr-onnxruntime construye sus ``SessionOptions`` sin tocar los hilos, así que
    onnxruntime usa su default (todos los núcleos físicos). ``OMP_NUM_THREADS`` NO
    sirve: onnxruntime 1.27 CPU usa su propio pool de hilos, no OpenMP. La única vía
    desde fuera es sustituir la clase ``SessionOptions`` que ve el módulo ANTES de
    construir ``RapidOCR()``. Se verifica a posteriori con ``cpu_propia_s``: con 1 hilo
    la CPU consumida debe aproximarse al tiempo de pared (ratio ~1x), no multiplicarlo.
    """
    try:
        from rapidocr_onnxruntime import utils as ru
        base = ru.SessionOptions

        class SessionOptionsCapadas(base):                    # noqa: N801
            def __init__(self, *args, **kw):
                super().__init__(*args, **kw)
                self.intra_op_num_threads = n
                self.inter_op_num_threads = 1

        ru.SessionOptions = SessionOptionsCapadas
        return True
    except Exception as e:                                    # pragma: no cover
        print(f"[aviso] no se pudo capar los hilos ONNX a {n}: {e}", file=sys.stderr)
        return False


def main(argv=None):
    a = parse_args(argv)
    sys.path.insert(0, a.repo)
    import psutil

    docs_dirs = a.docs or [str(Path(a.repo).parent / "Ejemplos")]
    escala = float(os.environ.get("PDF_RENDER_SCALE", 3.0))   # igual default que preprocess
    docs, dups = inventariar(docs_dirs, dedup=not a.sin_dedup, scale=escala)
    if not docs:
        print("No se encontró ningún documento.", file=sys.stderr)
        return 2

    proc = psutil.Process()
    rss_base = proc.memory_info().rss

    # ---- 1. ARRANQUE (coste de una sola vez; NO se cobra por documento) ----
    t0 = time.perf_counter()
    from incapacidad_ocr import ocr as ocr_mod
    from incapacidad_ocr import preprocess as preprocess_mod
    from incapacidad_ocr import extract as extract_mod
    from incapacidad_ocr.ocr import get_ocr_backend
    from incapacidad_ocr.processor import IncapacidadProcessor
    from incapacidad_ocr.extract import RuleBasedExtractor
    t_import = time.perf_counter() - t0
    rss_import = proc.memory_info().rss

    # El cap de hilos ONNX se aplica ANTES de construir el backend (plan §6.2).
    hilos_capados = capar_hilos_onnx(a.hilos) if a.hilos and a.hilos > 0 else False

    t0 = time.perf_counter()
    backend = get_ocr_backend("rapidocr")
    t_backend = time.perf_counter() - t0
    rss_arranque = proc.memory_info().rss

    extractor = RuleBasedExtractor()
    processor = IncapacidadProcessor(backend, extractor)

    # ---- warm-up: el PRIMER documento paga la inicialización perezosa de ONNX ----
    # Se corre el MISMO documento varias veces seguidas: la diferencia entre la 1ª y las
    # siguientes es el sobrecoste de la primera inferencia (que un pool de workers paga
    # una vez por proceso, no por documento).
    warm = docs[0]
    curva = []
    for _ in range(3):
        t0 = time.perf_counter()
        processor.run(warm["archivo"])
        curva.append(round(time.perf_counter() - t0, 2))
    t_warmup = curva[0]

    entorno = {
        "etiqueta": a.etiqueta, "fecha_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "host": platform.node(), "so": f"{platform.system()} {platform.release()} {platform.version()}",
        "python": sys.version.split()[0], "cpu_modelo": cpu_modelo(),
        "cores_fisicos": psutil.cpu_count(logical=False), "cores_logicos": psutil.cpu_count(logical=True),
        "ram_total_mb": round(psutil.virtual_memory().total / 1048576),
        "ram_disponible_mb_inicio": round(psutil.virtual_memory().available / 1048576),
        "hilos_onnx": a.hilos if hilos_capados else "default(onnxruntime = nº cores físicos)",
        "hilos_onnx_capados_ok": hilos_capados,
        "pdf_render_scale": preprocess_mod.PDF_RENDER_SCALE,
        "max_pdf_pages": preprocess_mod.MAX_PDF_PAGES,
        "ocr_max_pixels": preprocess_mod.OCR_MAX_PIXELS,
        "repeats": a.repeats, "dedup": not a.sin_dedup,
    }
    try:
        import onnxruntime as ort
        entorno["onnxruntime"] = ort.__version__
        entorno["onnx_providers"] = ort.get_available_providers()
    except Exception:
        pass

    arranque = {
        "import_s": round(t_import, 2), "backend_init_s": round(t_backend, 2),
        "warmup_primer_doc_s": round(t_warmup, 2), "warmup_doc": warm["nombre"],
        "warmup_curva_s": curva,
        "sobrecoste_1a_inferencia_s": round(curva[0] - min(curva[1:]), 2),
        "rss_base_mb": round(rss_base / 1048576, 1),
        "rss_tras_import_mb": round(rss_import / 1048576, 1),
        "ram_arranque_mb": round(rss_arranque / 1048576, 1),
    }
    print(f"[arranque] import {t_import:.2f}s · backend {t_backend:.2f}s · "
          f"RSS {arranque['ram_arranque_mb']} MB · warm-up {t_warmup:.1f}s", file=sys.stderr)

    # ---- 2/3. PASADAS ----
    medidas = {d["sha8"]: [] for d in docs}
    control = {d["sha8"]: [] for d in docs}
    pasadas = []
    for r in range(a.repeats):
        cond = {"pasada": r + 1}
        if a.esperar_cpu > 0:
            cond["espera"] = esperar_cpu_libre(psutil, a.esperar_cpu, a.espera_max)
        cond["cpu_sistema_pct_antes"] = psutil.cpu_percent(interval=1.0)
        cond["top_procesos_ajenos"] = top_procesos(psutil, proc.pid)
        cond["ram_disponible_mb"] = round(psutil.virtual_memory().available / 1048576)
        t_pasada = time.perf_counter()
        cpu_prop0 = sum(proc.cpu_times()[:2])
        cpu_sys0 = psutil.cpu_times()
        for i, d in enumerate(docs, 1):
            m = medir_doc(d, backend, extractor, ocr_mod, preprocess_mod, extract_mod,
                          proc, a.sample_ms / 1000.0)
            medidas[d["sha8"]].append(m)
            if not a.sin_control:
                t0 = time.perf_counter()
                processor.run(d["archivo"])
                control[d["sha8"]].append(round(time.perf_counter() - t0, 3))
            print(f"  [{r+1}/{a.repeats}] {i:>2}/{len(docs)} {m['total_fases_s']:>7.2f}s "
                  f"(render {m['render_s']:.2f} ocr {m['ocr_s']:.2f} ext {m['extract_s']:.3f}) "
                  f"{d['tipo']:<13} {d['nombre'][:52]}", file=sys.stderr)
        dur = time.perf_counter() - t_pasada
        cpu_sys1 = psutil.cpu_times()
        busy = sum(cpu_sys1) - sum(cpu_sys0) - ((cpu_sys1.idle - cpu_sys0.idle))
        cond.update({
            "duracion_s": round(dur, 1),
            "cpu_propia_s": round(sum(proc.cpu_times()[:2]) - cpu_prop0, 1),
            "cpu_sistema_ocupada_s": round(busy, 1),
            "cpu_sistema_pct_despues": psutil.cpu_percent(interval=1.0),
        })
        cond["cpu_ajena_s"] = round(cond["cpu_sistema_ocupada_s"] - cond["cpu_propia_s"], 1)
        cond["pct_cpu_ajena"] = (round(100.0 * cond["cpu_ajena_s"] / cond["cpu_sistema_ocupada_s"], 1)
                                 if cond["cpu_sistema_ocupada_s"] > 0 else None)
        pasadas.append(cond)
        print(f"[pasada {r+1}] {dur:.0f}s · CPU propia {cond['cpu_propia_s']}s · "
              f"CPU ajena {cond['cpu_ajena_s']}s ({cond['pct_cpu_ajena']}% del total ocupado)",
              file=sys.stderr)

    # ---- consolidación por documento: MIN (menos contendido) y mediana ----
    filas = []
    for d in docs:
        ms = medidas[d["sha8"]]
        tot = [m["total_fases_s"] for m in ms]
        i_min = tot.index(min(tot))
        mejor = ms[i_min]
        cpus = [m["cpu_propia_s"] for m in ms]
        fila = dict(d)
        fila.update({
            # CPU-segundos = trabajo real, casi inmune a la contención de la máquina.
            # Es la cifra que se extrapola a un servidor con otra CPU / otros workers.
            "cpu_s_min": round(min(cpus), 2),
            "cpu_s_mediana": round(statistics.median(cpus), 2),
            "rss_inicio_mb": mejor["rss_inicio_mb"],
            "render_s": mejor["render_s"], "ocr_s": mejor["ocr_s"],
            "combinar_s": mejor["combinar_s"], "extract_s": mejor["extract_s"],
            "total_s": mejor["total_fases_s"], "cpu_propia_s": mejor["cpu_propia_s"],
            "chars_ocr": mejor["chars_ocr"], "ocr_vacio": mejor["ocr_vacio"],
            "pico_rss_mb": max(m["pico_rss_mb"] for m in ms),
            "total_mediana_s": round(statistics.median(tot), 2),
            "total_max_s": round(max(tot), 2),
            "totales_por_pasada_s": tot,
            "control_run_s": (min(control[d["sha8"]]) if control[d["sha8"]] else None),
            "s_por_pagina": round(mejor["total_fases_s"] / max(1, mejor["paginas_ocr"]), 2),
        })
        filas.append(fila)

    def sub(tipo):
        return [f for f in filas if f["tipo"] == tipo]

    tot_all = [f["total_s"] for f in filas]
    glob = {
        "global": resumen(tot_all),
        "global_cpu_s": resumen([f["cpu_s_min"] for f in filas]),
        "por_tipo": {t: resumen([f["total_s"] for f in sub(t)])
                     for t in ("imagen", "pdf_1pag", "pdf_multipag") if sub(t)},
        "por_tipo_cpu_s": {t: resumen([f["cpu_s_min"] for f in sub(t)])
                           for t in ("imagen", "pdf_1pag", "pdf_multipag") if sub(t)},
        "fases_s": {k: resumen([f[k] for f in filas])
                    for k in ("render_s", "ocr_s", "combinar_s", "extract_s")},
        "reparto_pct": {},
        "s_por_pagina_pdf": resumen([f["s_por_pagina"] for f in filas if f["tipo"] != "imagen"]),
        # CPU consumida / tiempo de pared = nº EFECTIVO de núcleos usados por documento.
        # Con --hilos 1 debe rondar 1.0; con el default de ONNX es >1 (paraleliza dentro
        # del documento, y por eso añadir workers NO multiplica el throughput linealmente).
        "nucleos_efectivos": resumen([round(f["cpu_propia_s"] / f["total_s"], 2)
                                      for f in filas if f["total_s"] > 0]),
        "mediana_por_pasada_s": [round(statistics.median([medidas[d['sha8']][r]["total_fases_s"]
                                                          for d in docs]), 2)
                                 for r in range(a.repeats)],
    }
    s_tot = sum(tot_all)
    if s_tot > 0:
        for k in ("render_s", "ocr_s", "combinar_s", "extract_s"):
            glob["reparto_pct"][k] = round(100.0 * sum(f[k] for f in filas) / s_tot, 1)

    doc_pico = max(filas, key=lambda f: f["pico_rss_mb"])
    ram = {
        "ram_arranque_mb": arranque["ram_arranque_mb"],
        "ram_pico_mb": doc_pico["pico_rss_mb"],
        "doc_del_pico": doc_pico["nombre"], "tipo_del_pico": doc_pico["tipo"],
        "peak_wset_proceso_mb": round(getattr(proc.memory_info(), "peak_wset", 0) / 1048576, 1) or None,
        "rss_final_mb": round(proc.memory_info().rss / 1048576, 1),
        "nota_peak_wset": ("peak_wset es el pico de WORKING SET de todo el proceso que "
                           "reporta Windows (incluye páginas reclamables/arenas de ONNX). "
                           "Para dimensionar RAM por worker usar ram_pico_mb (RSS muestreado)."),
    }

    salida = {"entorno": entorno, "arranque": arranque, "condiciones_por_pasada": pasadas,
              "resumen": glob, "ram": ram, "documentos": filas, "duplicados_omitidos": dups,
              "control_vs_fases": {
                  "control_medido": not a.sin_control,
                  "delta_mediano_s": (round(statistics.median(
                      [f["control_run_s"] - f["total_s"] for f in filas
                       if f["control_run_s"] is not None]), 3) if not a.sin_control else None)}}

    Path(a.out_json).write_text(json.dumps(salida, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\n[ok] JSON -> {a.out_json}", file=sys.stderr)

    if a.out_md:
        lin = ["| # | Documento | Tipo | Pág | MP/pág | KB | render s | OCR s | reglas s | **total s** | **CPU s** | pico RSS MB | chars OCR |",
               "|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
        for i, f in enumerate(sorted(filas, key=lambda x: -x["cpu_s_min"]), 1):
            lin.append(f"| {i} | {f['nombre']} | {f['tipo']} | {f['paginas']} | {f['mp_pagina_mayor']} | "
                       f"{f['bytes']//1024} | {f['render_s']:.2f} | {f['ocr_s']:.2f} | {f['extract_s']:.3f} | "
                       f"**{f['total_s']:.2f}** | **{f['cpu_s_min']:.2f}** | {f['pico_rss_mb']:.0f} | {f['chars_ocr']} |")
        Path(a.out_md).write_text("\n".join(lin) + "\n", encoding="utf-8")
        print(f"[ok] Markdown -> {a.out_md}", file=sys.stderr)

    g, gc = glob["global"], glob["global_cpu_s"]
    print(f"\nGLOBAL pared n={g['n']}  min {g['min']}s  p50 {g['p50']}s  p90 {g['p90']}s  max {g['max']}s")
    print(f"GLOBAL CPU-s n={gc['n']}  min {gc['min']}s  p50 {gc['p50']}s  p90 {gc['p90']}s  max {gc['max']}s")
    for t, v in glob["por_tipo"].items():
        c = glob["por_tipo_cpu_s"][t]
        print(f"  {t:<13} n={v['n']}  pared p50 {v['p50']}s p90 {v['p90']}s max {v['max']}s "
              f"| CPU-s p50 {c['p50']}s p90 {c['p90']}s max {c['max']}s")
    print(f"reparto: {glob['reparto_pct']}")
    print(f"RAM: arranque {ram['ram_arranque_mb']} MB · pico {ram['ram_pico_mb']} MB "
          f"({ram['doc_del_pico']})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
