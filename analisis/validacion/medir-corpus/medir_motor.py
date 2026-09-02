"""Mide el MOTOR DE VALIDACION TEMPORAL (`incapacidad_ocr.validacion_temporal`) sobre
los 31 documentos del corpus de falsedad.

Frente de verificacion: `medir-corpus`. Reemplaza la medicion previa (`medir.py`), que se
hizo cuando el motor todavia no existia y solo habia la aritmetica de
`extract.normalizar_fechas()` + tres `problemas.append()` en `erp.mapear_a_staging`.

Que hace
--------
No ejecuta OCR: usa los campos YA extraidos que estan en `ocr/{falsas,falsa,reales,real}/*.json`
(con su `.txt`). Por cada documento corre TRES pasadas y guarda las tres, porque miden
cosas distintas y el motor se comporta distinto en cada una:

  A) `almacenado`  — `validar_registro(json['incapacidad'])`: el registro tal como quedo
     guardado, es decir DESPUES de `normalizar_fechas()` y SIN la foto `tiempos_leidos`.
     Es la ruta degradada de `reglas_tiempo.valores_leidos()` (deduce lo leido de las
     marcas `fecha_inicio_calculada` / `fecha_fin_recalculada`).
  B) `pipeline`    — re-extraccion desde `texto_plano` con el `RuleBasedExtractor` ACTUAL,
     foto `tiempos_leidos` tomada igual que en `processor.IncapacidadProcessor.run()` y
     luego `normalizar_fechas()`. Es la ruta de PRODUCCION de hoy y la medicion que vale.
  C) `staging`     — `erp.mapear_a_staging()` sobre el resultado de (B) con `LookupsNulos()`:
     comprueba que el hallazgo temporal llega de verdad al auxiliar (canal `problemas`,
     `requiere_revision`, columnas `alertas_tiempos` / `severidad_tiempos`).

Ademas calcula un CHEQUEO DE REFERENCIA independiente del motor (aritmetica pura sobre la
tripleta de la foto: `span = (fin-inicio)+1`, `span == dias`, `1 <= dias <= 540`), para
poder decir si el motor acierta/falla contra algo que no es el propio motor.

Determinismo: `hoy` se fija (no `date.today()`) porque T09/T10/T14 se miden contra hoy.
Configuracion: se fuerza `config_por_defecto()` (defaults del codigo) y se registra que
`cargar_config()` no encontro ni BD ni archivo, para que la medicion no dependa del entorno.

PII (Ley 1581): la salida de maquina (`resultados_motor.json`) contiene nombres de archivo
del corpus (que a su vez contienen nombres de pacientes) porque se queda en esta carpeta,
que no se versiona. Lo que se IMPRIME por consola usa el ID estable del corpus
(`F01..F15` / `R01..R16`, orden de `manifest.csv` por (etiqueta, archivo)) + `sha256[:8]`.

Uso:
    <repo>/.venv/Scripts/python.exe medir_motor.py
"""
from __future__ import annotations

import csv
import hashlib
import json
import sys
from datetime import date, timedelta
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
SALIDA = BASE / "validacion" / "medir-corpus" / "resultados_motor.json"

# Fecha de proceso FIJA: T09_INICIO_EN_FUTURO / T10_INICIO_MUY_ANTIGUO /
# T14_EXPEDICION_POSTERIOR_AL_INICIO se miden contra "hoy". Sin fijarla, la medicion
# cambia sola de un dia para otro y no es reproducible.
HOY = date(2026, 9, 2)

sys.path.insert(0, str(REPO))

from incapacidad_ocr import erp  # noqa: E402
from incapacidad_ocr.extract import RuleBasedExtractor, normalizar_fechas  # noqa: E402
from incapacidad_ocr.validacion_temporal import (  # noqa: E402
    CLAVE_SNAPSHOT, CATALOGO, cargar_config, config_por_defecto, entero_dias, fecha_iso,
    snapshot_leidos, validar_registro,
)

CARPETAS = ("falsas", "falsa", "reales", "real")


def sha8(s: str) -> str:
    return (s or "")[:8]


def cargar_manifest() -> list[dict[str, str]]:
    with (BASE / "manifest.csv").open(encoding="utf-8", newline="") as fh:
        filas = list(csv.DictReader(fh))
    # ID estable = posicion dentro de (etiqueta, archivo) ordenado: es la misma
    # numeracion que usan los informes hermanos del dataset (senales/, duraciones/).
    for etiqueta, prefijo in (("falsa", "F"), ("real", "R")):
        grupo = sorted((f for f in filas if f["etiqueta"] == etiqueta),
                       key=lambda f: f["archivo"])
        for i, f in enumerate(grupo, start=1):
            f["id"] = f"{prefijo}{i:02d}"
    return filas


def cargar_gt() -> dict[str, list[str]]:
    gt = json.loads((BASE / "ground_truth.json").read_text(encoding="utf-8"))
    return {f["archivo"]: f.get("senales") or [] for f in gt["filas"]}


def buscar_json(archivo: str) -> Path | None:
    tallo = Path(archivo).stem
    for carpeta in CARPETAS:
        p = BASE / "ocr" / carpeta / f"{tallo}.json"
        if p.is_file():
            return p
    return None


def chequeo_referencia(inicio: object, fin: object, dias: object) -> dict[str, object]:
    """Aritmetica de referencia, SIN pasar por el motor (para juzgar al motor).

    Convencion INCLUSIVA (la del papel, la que usa `normalizar_fechas`):
    `span = (fin - inicio).days + 1` y debe ser igual a los dias impresos.
    """
    di, df, n = fecha_iso(inicio), fecha_iso(fin), entero_dias(dias)
    out: dict[str, object] = {
        "inicio": di.isoformat() if di else None,
        "fin": df.isoformat() if df else None,
        "dias": n,
        "span": None, "desfase": None,
        "incoherente": False, "invertido": False, "dias_fuera_rango": False,
        "tripleta_completa": bool(di and df and n is not None),
    }
    if n is not None and not (1 <= n <= 540):
        out["dias_fuera_rango"] = True
    if di and df:
        span = (df - di).days + 1
        out["span"] = span
        out["invertido"] = span <= 0
        if n is not None and not out["dias_fuera_rango"] and span > 0:
            out["desfase"] = span - n
            out["incoherente"] = span != n
    return out


def resumen_informe(inf: dict) -> dict:
    """Lo que interesa de un informe de `validar_tiempos` (sin repetir el catalogo entero)."""
    reglas = inf["reglas"]
    return {
        "veredicto": inf["veredicto"],
        "exige_revision": inf["exige_revision"],
        "severidad_max": inf["severidad_max"],
        "puntaje": inf["puntaje_coherencia"],
        "cobertura": inf["resumen"]["cobertura"],
        "codigos": inf["codigos"],
        "problemas": inf["problemas"],
        "avisos": inf["avisos"],
        "no_cumplen": [r["codigo"] for r in reglas if r["estado"] == "NO_CUMPLE"],
        "cumplen": [r["codigo"] for r in reglas if r["estado"] == "CUMPLE"],
        "no_evaluables": {r["codigo"]: r["motivo"] for r in reglas
                          if r["estado"] == "NO_EVALUABLE"},
        "leido": inf["evidencia"]["leido"],
        "derivado": inf["evidencia"]["derivado"],
    }


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        pass

    # --- huella del codigo medido (extract.py lo esta editando otro trabajo en paralelo)
    huellas = {f: hashlib.sha256((REPO / "incapacidad_ocr" / f).read_bytes()).hexdigest()[:16]
               for f in ("extract.py", "erp.py", "reglas_tiempo.py", "validacion_temporal.py",
                         "processor.py", "numeros_es.py")}
    cfg_entorno = cargar_config()
    cfg = config_por_defecto()          # medicion contra los defaults del codigo
    extractor = RuleBasedExtractor()
    lookups = erp.LookupsNulos()

    manifest = cargar_manifest()
    gt = cargar_gt()
    filas: list[dict] = []

    for m in sorted(manifest, key=lambda f: f["id"]):
        archivo = m["archivo"]
        ruta = buscar_json(archivo)
        fila: dict[str, object] = {
            "id": m["id"], "archivo": archivo, "etiqueta": m["etiqueta"],
            "sha8": sha8(m["sha256"]), "ext": m["ext"],
            "cuarentena": m["cuarentena"] == "si",
            "motivo_cuarentena": m["motivo_cuarentena"] or None,
            "gt_senales": gt.get(archivo, []),
            "gt_temporal": "FECHAS_INCOHERENTES" in gt.get(archivo, []),
            "ocr_json": ruta.name if ruta else None,
        }
        if ruta is None:
            fila["error"] = "sin JSON de OCR en el corpus"
            filas.append(fila)
            continue

        d = json.loads(ruta.read_text(encoding="utf-8"))
        texto = d.get("texto_plano") or ""
        almacenado = d.get("incapacidad") or {}
        fila["tipo_documento"] = almacenado.get("tipo_documento")
        fila["chars_ocr"] = len(texto)

        # ---------- A) registro ALMACENADO (post-reconciliacion, sin foto) ----------
        inf_a = validar_registro(almacenado, hoy=HOY, config=cfg)
        fila["A_almacenado"] = resumen_informe(inf_a)

        # ---------- B) ruta de PRODUCCION (re-extraccion + foto + reconciliacion) ----------
        rec = extractor.extract(texto)
        inca = rec.get("incapacidad") if isinstance(rec, dict) else None
        crudo = dict(inca) if isinstance(inca, dict) else {}
        if isinstance(inca, dict):
            inca[CLAVE_SNAPSHOT] = snapshot_leidos(inca)   # igual que processor.run()
        normalizar_fechas(rec)
        inf_b = validar_registro(rec, hoy=HOY, config=cfg)
        fila["B_pipeline"] = resumen_informe(inf_b)
        fila["B_crudo_extractor"] = {
            "fecha_inicio": crudo.get("fecha_inicio"), "fecha_fin": crudo.get("fecha_fin"),
            "dias": crudo.get("dias"), "dias_letra": crudo.get("dias_letra"),
            "dias_letra_coincide": crudo.get("dias_letra_coincide"),
            "fecha_expedicion": crudo.get("fecha_expedicion"),
        }
        fila["B_referencia"] = chequeo_referencia(
            crudo.get("fecha_inicio"), crudo.get("fecha_fin"), crudo.get("dias"))

        # ---------- C) fila de STAGING (canal real que ve el auxiliar) ----------
        resultado = {"incapacidad": rec, "texto_plano": texto, "fuente": archivo}
        st = erp.mapear_a_staging(resultado, lookups=lookups, hoy=HOY, config_reglas=cfg)
        fila["C_staging"] = {
            "requiere_revision": st["requiere_revision"],
            "alertas_tiempos": st["row"].get("alertas_tiempos"),
            "severidad_tiempos": st["row"].get("severidad_tiempos"),
            "fechafin_leida": st["row"].get("fechafin_leida"),
            "dias_leidos": st["row"].get("dias_leidos"),
            "fechainicio_fila": st["row"].get("fechainicio"),
            "fechavencimiento_fila": st["row"].get("fechavencimiento"),
            "numerodias_fila": st["row"].get("Numerodias"),
            "hallazgos_tiempos": [h["codigo"] for h in st.get("hallazgos_tiempos", [])],
            "problemas": st.get("problemas", []),
            "n_problemas": len(st.get("problemas", [])),
            "avisos_tiempos": st.get("avisos_tiempos", []),
        }
        # Post-condicion R-T05 (propuesta NO implementada como regla): la fila final debe
        # cumplir fechavencimiento == fechainicio + Numerodias (NO inclusivo).
        fi = fecha_iso(st["row"].get("fechainicio"))
        fv = fecha_iso(st["row"].get("fechavencimiento"))
        nd = st["row"].get("Numerodias")
        fila["C_staging"]["vencimiento_coherente"] = (
            None if not (fi and fv and nd) else (fi + timedelta(days=int(nd))) == fv)
        filas.append(fila)

    salida = {
        "generado_por": "validacion/medir-corpus/medir_motor.py",
        "hoy_fijado": HOY.isoformat(),
        "huellas_codigo": huellas,
        "config_medida": "config_por_defecto() (defaults del codigo)",
        "config_del_entorno": {"fuentes": list(cfg_entorno.fuentes),
                               "avisos": list(cfg_entorno.avisos)},
        "reglas_en_catalogo": len(CATALOGO),
        "documentos": filas,
    }
    SALIDA.write_text(json.dumps(salida, ensure_ascii=False, indent=1), encoding="utf-8")

    # ------------------------- informe por consola (sin PII) -------------------------
    print(f"hoy fijado = {HOY}   reglas en catalogo = {len(CATALOGO)}")
    print("huellas:", "  ".join(f"{k}={v}" for k, v in huellas.items()))
    print("config del entorno: fuentes =", cfg_entorno.fuentes, "avisos =", cfg_entorno.avisos)
    print()
    cab = ("ID    sha8     et cuar  tipo        | B: leido i/f/dias        ref span/desf "
           "| B veredicto  codigos                        | C rev alertas")
    print(cab)
    print("-" * len(cab))
    for f in filas:
        if f.get("error"):
            print(f"{f['id']}  {f['sha8']} {f['etiqueta'][:1]}  "
                  f"{'CUAR' if f['cuarentena'] else '    '}  ERROR: {f['error']}")
            continue
        b, r, c = f["B_pipeline"], f["B_referencia"], f["C_staging"]
        leido = f"{r['inicio'] or '-':10s} {r['fin'] or '-':10s} {str(r['dias'] or '-'):>4s}"
        ref = f"{str(r['span'] or '-'):>4s}/{str(r['desfase']) if r['desfase'] is not None else '-':>4s}"
        print(f"{f['id']}  {f['sha8']} {f['etiqueta'][:1]}  "
              f"{'CUAR' if f['cuarentena'] else '    '}  {str(f['tipo_documento'])[:11]:11s} | "
              f"{leido} {ref} | {b['veredicto']:10s} {','.join(b['codigos'])[:30]:30s} | "
              f"{'SI' if c['requiere_revision'] else 'no':3s} {c['alertas_tiempos'] or '-'}")
    print(f"\nDetalle maquina: {SALIDA}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
