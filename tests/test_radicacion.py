"""Pruebas del checklist de RADICACIÓN ante la EPS (`lpeps.cheklistradicaciones`).

    python tests/test_radicacion.py

Deterministas y sin BD: el JSON de muestra es una copia literal (recortada) de lo que
guarda el ERP, incluidas sus rarezas — el campo viene envuelto en comillas dobles sin
escapar el contenido, y el nombre del certificado laboral está mal escrito ("CERTICADO").
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

try:  # consola Windows (cp1252) → forzar UTF-8 para acentos
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # noqa: BLE001
    pass

from incapacidad_ocr import erp  # noqa: E402

_fail = 0

# Copia literal del formato del ERP: el JSON va DENTRO de comillas dobles sin escapar.
JSON_ERP = (
    '"{"ausentismos":['
    '{"idlptipoausentismo":2,"tipo_envio":1,"medioradicacion":2,"documentos":['
    '{"iddocumento":1,"nombredocumento":"CERTIFICADO DE INCAPACIDAD","archivo":1}]},'
    '{"idlptipoausentismo":3,"tipo_envio":1,"medioradicacion":2,"documentos":['
    '{"iddocumento":1,"nombredocumento":"CERTIFICADO DE INCAPACIDAD","archivo":1},'
    '{"iddocumento":2,"nombredocumento":"HISTORIA CLINICA","archivo":1},'
    '{"iddocumento":12,"nombredocumento":"CERTICADO LABORAL","archivo":1}]},'
    '{"idlptipoausentismo":5,"tipo_envio":2,"medioradicacion":2,"documentos":['
    '{"iddocumento":1,"nombredocumento":"CERTIFICADO DE INCAPACIDAD","archivo":1},'
    '{"iddocumento":4,"nombredocumento":"CERTIFICADO NACIDO VIVO","archivo":1},'
    '{"iddocumento":5,"nombredocumento":"REGISTRO CIVIL","archivo":1}]},'
    '{"idlptipoausentismo":10,"tipo_envio":0,"medioradicacion":0,"documentos":[]}'
    ']}"'
)


def check(nombre: str, obtenido, esperado) -> None:
    global _fail
    ok = obtenido == esperado
    if not ok:
        _fail += 1
    print(f"  {'PASS' if ok else 'FALLA'} {nombre}" + ("" if ok else f"  ->  {obtenido!r} != {esperado!r}"))


def main() -> int:
    print("[1] Parseo del JSON del ERP (envuelto en comillas, nombres tal cual)")
    check("enfermedad general", erp.documentos_checklist_radicacion(JSON_ERP, 3),
          ["INCAPACIDAD", "HISTORIA_CLINICA", "CERTIFICADO_LABORAL"])
    check("accidente de trabajo", erp.documentos_checklist_radicacion(JSON_ERP, 2), ["INCAPACIDAD"])
    check("tipo sin documentos", erp.documentos_checklist_radicacion(JSON_ERP, 10), [])
    check("tipo no configurado", erp.documentos_checklist_radicacion(JSON_ERP, 11), [])
    check("campo vacío", erp.documentos_checklist_radicacion("", 3), [])
    check("campo ilegible", erp.documentos_checklist_radicacion("no soy json", 3), [])
    check("campo None", erp.documentos_checklist_radicacion(None, 3), [])

    print("[2] Validación contra los documentos presentes")
    req_eg = erp.documentos_checklist_radicacion(JSON_ERP, 3)
    check("faltan dos", erp.validar_radicacion(["INCAPACIDAD"], req_eg),
          ("INCOMPLETA", ["HISTORIA_CLINICA", "CERTIFICADO_LABORAL"]))
    check("la epicrisis cubre la historia clínica",
          erp.validar_radicacion(["INCAPACIDAD", "EPICRISIS", "CERTIFICADOLABORAL"], req_eg),
          ("COMPLETA", []))
    check("EPS sin checklist no opina", erp.validar_radicacion(["INCAPACIDAD"], []), (None, []))

    print("[3] Equivalencias: si la EPS pide los DOS, uno no cubre al otro")
    req_mat = erp.documentos_checklist_radicacion(JSON_ERP, 5)
    check("nacido vivo no reemplaza al registro civil",
          erp.validar_radicacion(["INCAPACIDAD", "NACIDOVIVO"], req_mat),
          ("INCOMPLETA", ["REGISTRO_CIVIL_NACIMIENTO"]))
    check("con ambos, completa",
          erp.validar_radicacion(["INCAPACIDAD", "NACIDOVIVO", "REGISTROCIVIL"], req_mat),
          ("COMPLETA", []))

    print("[4] Etiquetas legibles para el aviso")
    check("etiqueta conocida", erp.etiqueta_doc("REGISTRO_CIVIL_NACIMIENTO"), "registro civil")
    check("etiqueta desconocida", erp.etiqueta_doc("ALGO_RARO"), "algo raro")

    print("-" * 64)
    print("RESULTADO: TODO OK" if _fail == 0 else f"RESULTADO: {_fail} FALLAS")
    return 1 if _fail else 0


if __name__ == "__main__":
    sys.exit(main())
