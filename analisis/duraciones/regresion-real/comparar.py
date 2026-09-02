# -*- coding: utf-8 -*-
"""Regresion ANTES vs. AHORA del extractor por reglas sobre los 31 textos OCR cacheados.

Verificacion del frente 'regresion-real': el cambio de duraciones en numeros/letras
no debe EMPEORAR ningun campo de los documentos reales.

Metodo (sin re-OCR, para no contaminar la medicion de rendimiento en paralelo):
  * ANTES  = `incapacidad_ocr/extract.py` de git HEAD (volcado en `extract_antes.py`).
             El diff de trabajo de ese archivo es EXACTAMENTE el cambio de duraciones,
             asi que HEAD es el estado previo exacto.
  * AHORA  = el paquete del repo tal como esta en el working tree.
  * Entrada = `dataset-falsedad/ocr/{falsas,falsa,reales,real}/*.txt` (texto que el
             pipeline vio: es el `texto_plano` que guardo el shard, ya combinado por
             paginas relevantes).
  * Los dos caminos aplican `RuleBasedExtractor().extract()` + `normalizar_fechas()`,
    que es lo que hace `IncapacidadProcessor.run` (y lo que produjo los .json cacheados).

Salidas: tabla por campo y por documento en stdout + `resultado.json`.
Sin PII: solo nombres de ARCHIVO y nombres de CAMPO; los valores se comparan pero
solo se imprimen los de campos NO sensibles (dias/fechas/flags). Los valores de
nombre/diagnostico se reportan como <IGUAL>/<DISTINTO> sin contenido.
"""
from __future__ import annotations

import importlib.util
import json
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
BASE = Path(str(_DATASET))
OCRDIR = BASE / "ocr"
AQUI = Path(__file__).resolve().parent

sys.path.insert(0, str(REPO))
from incapacidad_ocr.extract import RuleBasedExtractor as RBAhora  # noqa: E402
from incapacidad_ocr.extract import normalizar_fechas as norm_ahora  # noqa: E402

# --- carga del extractor ANTES (modulo suelto: HEAD no tiene imports relativos) ---
spec = importlib.util.spec_from_file_location("extract_antes", AQUI / "extract_antes.py")
antes_mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(antes_mod)
RBAntes = antes_mod.RuleBasedExtractor
norm_antes = antes_mod.normalizar_fechas

# Campos nuevos que el cambio AÑADE al esquema: no cuentan como diferencia, se
# reportan aparte (instrumentacion).
CAMPOS_NUEVOS = {
    "incapacidad.dias_letra",
    "incapacidad.dias_letra_coincide",
    "incapacidad.fecha_fin_recalculada",
}
# Campos con PII de salud: se comparan, pero su VALOR no se imprime (Ley 1581).
CAMPOS_PII = {
    "paciente.nombre", "paciente.documento_numero", "diagnostico.cie10",
    "diagnostico.descripcion", "medico.nombre", "medico.registro",
    "permiso.autorizado_por", "permiso.detalle", "permiso.empresa", "permiso.cargo",
    "permiso.autorizado_cargo",
}


def aplanar(rec: dict) -> dict:
    """{'seccion.campo': valor} para un registro del esquema."""
    out = {}
    for k, v in rec.items():
        if isinstance(v, dict):
            for k2, v2 in v.items():
                if k2.startswith("_"):  # marcas internas (_inicio_anclada)
                    continue
                out[f"{k}.{k2}"] = v2
        else:
            out[k] = v
    return out


def textos() -> list[tuple[str, Path]]:
    salida = []
    for sub in ("falsas", "falsa", "reales", "real"):
        for p in sorted((OCRDIR / sub).glob("*.txt")):
            salida.append((f"{sub}/{p.stem}", p))
    return salida


def main() -> int:
    docs = textos()
    print(f"documentos: {len(docs)}\n")

    filas = []
    for etiqueta, p in docs:
        texto = p.read_text(encoding="utf-8")
        jpath = p.with_suffix(".json")
        cache = json.loads(jpath.read_text(encoding="utf-8")).get("incapacidad") or {}

        r_antes = RBAntes().extract(texto)
        norm_antes(r_antes)
        r_ahora = RBAhora().extract(texto)
        norm_ahora(r_ahora)

        a, b = aplanar(r_antes), aplanar(r_ahora)
        c = aplanar(cache) if cache else {}

        difs = {}
        for k in sorted(set(a) | set(b)):
            if k in CAMPOS_NUEVOS:
                continue
            if a.get(k) != b.get(k):
                difs[k] = (a.get(k), b.get(k))

        # Cross-check: el ANTES reproducido debe coincidir con el .json cacheado
        # (si no, el .json no sirve como linea base y hay que decirlo).
        desajuste_cache = {}
        if c:
            for k in sorted(set(a) | set(c)):
                if k in CAMPOS_NUEVOS:
                    continue
                if a.get(k) != c.get(k):
                    desajuste_cache[k] = (a.get(k), c.get(k))

        filas.append({
            "doc": etiqueta,
            "chars": len(texto),
            "tipo": b.get("tipo_documento"),
            "dias_antes": a.get("incapacidad.dias"),
            "dias_ahora": b.get("incapacidad.dias"),
            "dias_letra": b.get("incapacidad.dias_letra"),
            "coincide": b.get("incapacidad.dias_letra_coincide"),
            "fin_recalc": b.get("incapacidad.fecha_fin_recalculada"),
            "fi_antes": a.get("incapacidad.fecha_inicio"),
            "fi_ahora": b.get("incapacidad.fecha_inicio"),
            "ff_antes": a.get("incapacidad.fecha_fin"),
            "ff_ahora": b.get("incapacidad.fecha_fin"),
            "fic_antes": a.get("incapacidad.fecha_inicio_calculada"),
            "fic_ahora": b.get("incapacidad.fecha_inicio_calculada"),
            "difs": {k: (list(v) if not isinstance(v, tuple) else list(v)) for k, v in difs.items()},
            "desajuste_cache": {k: list(v) for k, v in desajuste_cache.items()},
        })

    # ---------------- reporte ----------------
    def cell(v):
        return "-" if v is None else str(v)

    print("== DIAS: antes -> ahora ==")
    print(f"{'documento':60s} {'antes':>6s} {'ahora':>6s} {'letra':>6s} {'coin':>6s} {'finrec':>7s}")
    mejoran, empeoran, cambian, iguales = [], [], [], []
    for f in filas:
        da, db = f["dias_antes"], f["dias_ahora"]
        marca = "  "
        if da is None and db is not None:
            marca = "+ "
            mejoran.append(f)
        elif da is not None and db is None:
            marca = "! "
            empeoran.append(f)
        elif da != db:
            marca = "~ "
            cambian.append(f)
        else:
            iguales.append(f)
        print(f"{marca}{f['doc']:58s} {cell(da):>6s} {cell(db):>6s} {cell(f['dias_letra']):>6s} "
              f"{cell(f['coincide']):>6s} {cell(f['fin_recalc']):>7s}")

    print(f"\ndias: iguales={len(iguales)} nuevos(antes None)={len(mejoran)} "
          f"perdidos(ahora None)={len(empeoran)} cambiados={len(cambian)}")

    print("\n== DIFERENCIAS por campo (excluidos los campos NUEVOS del esquema) ==")
    conteo = {}
    for f in filas:
        for k in f["difs"]:
            conteo[k] = conteo.get(k, 0) + 1
    if not conteo:
        print("  (ninguna)")
    for k, n in sorted(conteo.items(), key=lambda kv: -kv[1]):
        print(f"  {k:42s} {n} documento(s)")

    print("\n== DETALLE de cada documento con alguna diferencia ==")
    for f in filas:
        if not f["difs"]:
            continue
        print(f"\n  {f['doc']}  (tipo={f['tipo']}, chars={f['chars']})")
        for k, (va, vb) in f["difs"].items():
            if k in CAMPOS_PII:
                print(f"    {k:38s} antes=<{'None' if va is None else 'valor'}>  "
                      f"ahora=<{'None' if vb is None else 'valor'}>  "
                      f"{'IGUALES' if va == vb else 'DISTINTOS'}")
            else:
                print(f"    {k:38s} antes={va!r}  ahora={vb!r}")

    print("\n== CROSS-CHECK: ANTES reproducido vs. .json cacheado ==")
    malos = [f for f in filas if f["desajuste_cache"]]
    if not malos:
        print("  OK: los 31 .json cacheados se reproducen byte a byte con el extractor de HEAD")
    for f in malos:
        print(f"  {f['doc']}: {list(f['desajuste_cache'])}")
        for k, (va, vc) in f["desajuste_cache"].items():
            if k in CAMPOS_PII:
                print(f"     {k}: reproducido=<{'None' if va is None else 'valor'}> "
                      f"cache=<{'None' if vc is None else 'valor'}>")
            else:
                print(f"     {k}: reproducido={va!r} cache={vc!r}")

    (AQUI / "resultado.json").write_text(
        json.dumps(filas, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    print(f"\nresultado -> {AQUI / 'resultado.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
