"""Prueba `scripts/cargar_catalogos.py`: sin PII, y el checklist demo NO queda inerte.

No necesita base de datos ni el corpus: solo genera el SQL en memoria y comprueba invariantes.

Por qué existe: al escribir el script se guardó el checklist de la EPS demo imitando la forma
del export CSV del ERP (envuelto en comillas dobles y con las internas DUPLICADAS), y
`erp.documentos_checklist_radicacion` devolvía `[]` — quita las comillas externas pero no
deshace el duplicado. El efecto era el peor posible: el checklist quedaba **inerte en
silencio**, o sea justo el fallo que ese script viene a cerrar («sin `lpeps` la radicación
degrada a [] sin avisar»). Nada lo habría delatado, porque «no hay documentos faltantes» se ve
igual que «no se evaluó nada».

    python tests/test_catalogos.py
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "scripts"))

import cargar_catalogos as cc  # noqa: E402
from incapacidad_ocr import erp  # noqa: E402

fallos: list[str] = []


def check(cond: bool, etiqueta: str, detalle: str = "") -> None:
    if cond:
        print(f"  OK    {etiqueta}")
    else:
        print(f"  FALLA {etiqueta}" + (f" -> {detalle}" if detalle else ""))
        fallos.append(etiqueta)


print("[1] El checklist de la EPS demo se parsea de verdad")
plano = cc.EPS_DEMO_CHECKLIST
docs3 = erp.documentos_checklist_radicacion(plano, 3)
docs2 = erp.documentos_checklist_radicacion(plano, 2)
docs5 = erp.documentos_checklist_radicacion(plano, 5)
check(bool(docs3), "tipo 3 (enfermedad general) devuelve documentos", str(docs3))
check(bool(docs2), "tipo 2 (accidente de trabajo) devuelve documentos", str(docs2))
check(bool(docs5), "tipo 5 (maternidad) devuelve documentos", str(docs5))
check("INCAPACIDAD" in docs3, "el tipo 3 exige la incapacidad", str(docs3))
# La errata viene del catálogo REAL del cliente: si el canonizador dejara de reconocerla, el
# requisito se perdería sin ruido.
check(erp._canon_doc_radicacion("CERTICADO LABORAL") == "CERTIFICADO_LABORAL",
      "la errata 'CERTICADO LABORAL' del catálogo del cliente sigue canonizando")

print("[2] Un tipo sin checklist NO inventa requisitos")
check(erp.documentos_checklist_radicacion(plano, 7) == [],
      "tipo 7 (no configurado) devuelve lista vacía")
check(erp.validar_radicacion(set(), [])[0] is None,
      "sin checklist el estado es None (no se opina), no 'COMPLETA'")

print("[3] La validación de radicación opina con ese checklist")
estado, faltan = erp.validar_radicacion({"INCAPACIDAD"}, docs3)
check(estado == "INCOMPLETA" and bool(faltan),
      "con solo la incapacidad, faltan soportes", f"estado={estado} faltan={faltan}")

print("[4] El SQL generado no lleva NI UN dato personal")
sql = cc.generar_sql()
cedulas = re.findall(r"'\d{7,11}'", sql)
check(not cedulas, "no hay literales con forma de cédula", str(cedulas[:5]))
check("lpempleados" not in sql, "no siembra empleados (una cédula no se inventa)")

print("[5] El catálogo se carga completo y no tapa los huecos que la señal necesita")
check(sql.count("DELETE FROM lpdiagnosticos;") == 1,
      "reemplaza el catálogo entero (mezclarlo tapa los huecos reales)")
check("'R50.5'" not in sql,
      "R50.5 NO está: el cliente lo declaró inexistente y es la evidencia de la señal")
check("'M54.5'" in sql, "M54.5 sí está (código legítimo del corpus)")
check("CREATE TABLE IF NOT EXISTS lpeps" in sql,
      "crea lpeps, que sql/init.sql no crea")

print("[6] El SQL es sintaxis de MySQL, no de MariaDB")


def sql_efectivo(texto: str) -> str:
    """El SQL sin las líneas de comentario, que es lo único que el servidor interpreta.

    Hay que quitarlas: los comentarios de `init.sql` MENCIONAN la sintaxis prohibida para
    explicar por qué no se usa, y buscar en el archivo entero daba un falso positivo.
    """
    return "\n".join(l for l in texto.splitlines() if not l.lstrip().startswith("--")).upper()


# `ADD COLUMN IF NOT EXISTS` no existe en MySQL y, en un script de initdb, aborta el arranque
# entero del contenedor: en una máquina nueva no se creaba ni una tabla. Pasó de verdad.
check("ADD COLUMN IF NOT EXISTS" not in sql_efectivo(sql),
      "no usa 'ADD COLUMN IF NOT EXISTS' (es de MariaDB)")
# MySQL exige que `--` vaya seguido de un espacio o del fin de línea; un `--> texto` NO es un
# comentario y da error 1064. También pasó de verdad, al marcar las líneas del resumen.
malos = [l for l in sql.splitlines()
         if l.startswith("--") and l.rstrip() != "--" and not l.startswith("-- ")]
check(not malos, "todo comentario es '-- ' o '--' a solas (MySQL lo exige)", str(malos[:3]))

for archivo in ("init.sql", "catalogos_publicos.sql"):
    ruta = REPO / "sql" / archivo
    if not ruta.is_file():
        check(archivo == "catalogos_publicos.sql", f"{archivo} existe",
              "falta y lo monta docker-compose en initdb")
        continue
    texto = ruta.read_text(encoding="utf-8")
    check("ADD COLUMN IF NOT EXISTS" not in sql_efectivo(texto),
          f"sql/{archivo} no usa sintaxis de MariaDB (o el contenedor db muere en frío)")
    malos_a = [l for l in texto.splitlines()
               if l.startswith("--") and l.rstrip() != "--" and not l.startswith("-- ")]
    check(not malos_a, f"sql/{archivo}: comentarios válidos en MySQL", str(malos_a[:3]))

print()
if fallos:
    print(f"FALLARON {len(fallos)}: {', '.join(fallos)}")
    raise SystemExit(1)
print("TODO OK")
