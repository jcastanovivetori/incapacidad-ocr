"""Pruebas de las señales DUDOSA relacionadas con el diagnóstico CIE-10 en
`erp.mapear_a_staging`: texto del documento vs. descripción oficial del catálogo
(`erp._diagnostico_coincide`), código que no resuelve contra `lpdiagnosticos`, y
código estructuralmente incompleto (3 caracteres en vez de 4).

    python tests/test_erp_diagnostico.py
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # noqa: BLE001
    pass

from incapacidad_ocr import erp  # noqa: E402

_fail = 0


def check(name: str, cond: bool, detail: str = "") -> None:
    global _fail
    ok = bool(cond)
    if not ok:
        _fail += 1
    print(("  PASS " if ok else "  FAIL ") + name + (f"  ->  {detail}" if detail else ""))


class LookupsFake:
    """Como LookupsNulos pero con un catálogo CIE-10 fijo para las pruebas."""

    _CIE = {"M54.4": "LUMBAGO CON CIATICA", "J06.9": "INFECCION AGUDA DE VIAS RESPIRATORIAS SUPERIORES"}

    def empleado_por_cedula(self, cedula):
        return (1, "PACIENTE DE PRUEBA", None) if cedula else (None, None, None)

    def empleado_por_nombre(self, nombre):
        return None, None, None

    def diagnostico_por_codigo(self, codigo):
        desc = self._CIE.get((codigo or "").upper())
        return (2, desc) if desc else (None, None)

    def catalogo_diagnosticos_disponible(self):
        """Este falso SÍ tiene catálogo (`_CIE`), así que un código que no resuelve aquí
        significa de verdad "no existe" — que es lo que estas pruebas quieren comprobar.
        Con `LookupsNulos` (sin catálogo) la señal de sospecha no se activa a propósito."""
        return True

    def id_entidad_por_nombre(self, nombre):
        return None, None, None

    def documentos_requeridos(self, id_entidad, id_tipo):
        return []


def _resultado(cie10: str, descripcion_doc: str | None) -> dict:
    return {
        "ocr_backend": "stub", "extractor": "rule", "fuente": "x.pdf", "texto_plano": "x",
        "incapacidad": {
            "paciente": {"nombre": "PACIENTE DE PRUEBA", "documento_numero": "123"},
            "entidad": {"eps": "NUEVA EPS"},
            "incapacidad": {"fecha_inicio": "2026-07-18", "fecha_fin": "2026-07-19", "dias": "2"},
            "diagnostico": {"cie10": cie10, "descripcion": descripcion_doc},
        },
    }


def test_coincide_no_dispara() -> None:
    print("[1] Descripción del documento SÍ coincide con el catálogo -> no dispara")
    r = erp.mapear_a_staging(
        _resultado("M54.4", "LUMBAGO CON CIATICA"), lookups=LookupsFake(),
    )
    check("sospecha=False", r["row"]["sospecha_manipulacion"] == 0, str(r["row"]["motivo_sospecha"]))


def test_no_coincide_dispara() -> None:
    print("[2] Descripción del documento NO tiene relación con el catálogo -> dispara (caso real)")
    # Caso real reportado: código M54.5/M54.4 con descripción de cólicos/vómito/cefalea
    # (nada que ver con "lumbago con ciática").
    r = erp.mapear_a_staging(
        _resultado("M54.4", "COLICOS ABDOMINALES, VOMITO, CEFALEA, DOLOR EN HUESOS"),
        lookups=LookupsFake(),
    )
    check("sospecha=True", r["row"]["sospecha_manipulacion"] == 1)
    check("motivo menciona el código", "M54.4" in (r["row"]["motivo_sospecha"] or ""),
          r["row"]["motivo_sospecha"])


def test_sin_descripcion_no_dispara() -> None:
    print("[3] El formato omite la descripción del diagnóstico -> no se evalúa (no dispara)")
    r = erp.mapear_a_staging(_resultado("M54.4", None), lookups=LookupsFake())
    check("sospecha=False", r["row"]["sospecha_manipulacion"] == 0, str(r["row"]["motivo_sospecha"]))


def test_codigo_no_catalogado_dispara() -> None:
    print("[4] Código NO está en el catálogo -> dispara DUDOSA (Diana: todo CIE-10 vigente debe resolver)")
    r = erp.mapear_a_staging(_resultado("Z99.9", "LO QUE SEA"), lookups=LookupsFake())
    check("sospecha_manipulacion=True", r["row"]["sospecha_manipulacion"] == 1)
    check("motivo menciona el código", "Z99.9" in (r["row"]["motivo_sospecha"] or ""),
          r["row"]["motivo_sospecha"])
    check("problema de código catalogado presente",
          any("no está en el catálogo" in p for p in r["problemas"]), str(r["problemas"]))


def test_codigo_3_caracteres_dispara() -> None:
    print("[6] Código CIE-10 de solo 3 caracteres (categoría sin subdividir) -> dispara "
          "(caso real: 'A09' en INCAPACIDAD KEVIN RONALDO SARMIENTO)")
    # "A09" no está en el catálogo de prueba (solo M54.4/J06.9) -> además dispara por
    # "no catalogado"; ambos motivos deben quedar reflejados.
    r = erp.mapear_a_staging(_resultado("A09", "GASTROENTERITIS BACTERIANA"), lookups=LookupsFake())
    check("sospecha_manipulacion=True", r["row"]["sospecha_manipulacion"] == 1)
    check("motivo menciona longitud incompleta",
          "incompleto" in (r["row"]["motivo_sospecha"] or ""), r["row"]["motivo_sospecha"])


def test_codigo_4_caracteres_no_dispara_por_longitud() -> None:
    print("[7] Código CIE-10 de 4 caracteres y SÍ catalogado -> no dispara por longitud")
    r = erp.mapear_a_staging(_resultado("M54.4", "LUMBAGO CON CIATICA"), lookups=LookupsFake())
    check("sospecha_manipulacion=False", r["row"]["sospecha_manipulacion"] == 0,
          str(r["row"]["motivo_sospecha"]))


def test_helper_umbral_conservador() -> None:
    print("[5] _diagnostico_coincide: descripciones muy cortas -> None (no opina)")
    check("None con textos cortos", erp._diagnostico_coincide("dolor", "malestar") is None)
    check("None si falta alguna", erp._diagnostico_coincide("LUMBAGO CON CIATICA", None) is None)
    check("True con solapamiento", erp._diagnostico_coincide("LUMBAGO CON CIATICA", "Lumbago cronico") is True)
    check("False sin solapamiento",
          erp._diagnostico_coincide("LUMBAGO CON CIATICA", "COLICOS ABDOMINALES VOMITO") is False)


def test_sin_catalogo_no_dispara() -> None:
    print("[8] SIN catálogo cargado -> el código que no resuelve NO es sospecha (solo problema)")
    # Es la diferencia entre «no existe» y «no lo pude comprobar». Sin `lpdiagnosticos`
    # NINGÚN código resuelve, así que si esta señal disparara marcaría el 100% de los
    # documentos legítimos — con 7000 al mes, eso tapa las alertas de verdad.
    r = erp.mapear_a_staging(_resultado("Z99.9", "LO QUE SEA"), lookups=erp.LookupsNulos())
    check("sospecha_manipulacion=0", r["row"]["sospecha_manipulacion"] == 0,
          str(r["row"]["motivo_sospecha"]))
    check("el problema SÍ se registra para revisión humana",
          any("no está en el catálogo" in p for p in r["problemas"]), str(r["problemas"]))
    check("y no queda en el estado de posible manipulación",
          r["row"]["estado"] != erp.ESTADO_POSIBLE_MANIPULACION, r["row"]["estado"])

    # Un objeto de lookups incompleto (duck-typing) debe degradar igual, no reventar.
    class _Incompleto(erp.LookupsNulos):
        catalogo_diagnosticos_disponible = None  # simula que el método no existe

    del _Incompleto.catalogo_diagnosticos_disponible
    r2 = erp.mapear_a_staging(_resultado("Z99.9", "LO QUE SEA"), lookups=_Incompleto())
    check("lookups sin el método: no explota y no acusa",
          r2["row"]["sospecha_manipulacion"] == 0)


def test_basura_ocr_no_dispara() -> None:
    print("[9] Basura del OCR en el campo del diagnóstico -> NO es sospecha de manipulación")
    # Medido sobre el corpus real: los 2 únicos falsos positivos de esta señal venían de aquí.
    # "0039" no empieza por letra y "FECHA" no tiene dígitos: no son códigos falsificados,
    # son lecturas fallidas. Acusar a un documento legítimo por eso es el error más caro.
    for basura in ("0039", "FECHA", "IDENTI", "S", "12345"):
        r = erp.mapear_a_staging(_resultado(basura, "LO QUE SEA"), lookups=LookupsFake())
        check(f"{basura!r}: sospecha_manipulacion=0", r["row"]["sospecha_manipulacion"] == 0,
              str(r["row"]["motivo_sospecha"]))
        check(f"{basura!r}: pero SÍ queda como problema para el auxiliar",
              any("catálogo" in p or "CIE-10" in p for p in r["problemas"]), str(r["problemas"]))
    # Contraste: un código BIEN FORMADO que no está en el catálogo sí es sospecha.
    r = erp.mapear_a_staging(_resultado("Z99.9", "LO QUE SEA"), lookups=LookupsFake())
    check("Z99.9 (bien formado, no catalogado): sí dispara",
          r["row"]["sospecha_manipulacion"] == 1, str(r["row"]["motivo_sospecha"]))


def main() -> int:
    print("=" * 64)
    print("PRUEBAS erp.py — coincidencia diagnóstico vs. catálogo CIE-10")
    print("=" * 64)
    test_coincide_no_dispara()
    test_no_coincide_dispara()
    test_sin_descripcion_no_dispara()
    test_codigo_no_catalogado_dispara()
    test_codigo_3_caracteres_dispara()
    test_codigo_4_caracteres_no_dispara_por_longitud()
    test_helper_umbral_conservador()
    test_sin_catalogo_no_dispara()
    test_basura_ocr_no_dispara()
    print("-" * 64)
    print("RESULTADO:", "TODO OK" if _fail == 0 else f"{_fail} fallo(s)")
    return 1 if _fail else 0


if __name__ == "__main__":
    sys.exit(main())
