# `analisis/` — el trabajo de investigación sobre el corpus real

Aquí está el **conocimiento** que salió de analizar los 31 documentos reales del cliente
(15 adulterados + 16 legítimos): las sondas de detección, la evidencia medida, los informes de
verificación y el benchmark. Se versiona para que un `git pull` en otra máquina lo traiga y no
haya que rehacerlo.

**Lo que NO está aquí, y no va a estar: el corpus.** Son documentos de salud con nombre y cédula
de personas reales (Ley 1581), y este repositorio se comparte fuera de Gruppo. Los documentos y
el texto OCR viven en `../dataset-falsedad/`, fuera del árbol de git.

## Los informes hablan con seudónimos

Para que los informes sigan siendo útiles sin exponer a nadie, todo está **redactado**:

| En el corpus real | En estos archivos |
|---|---|
| `INC APELLIDOS NOMBRES fecha.pdf` | `FALSA-03.pdf` |
| `1095912481_INCAPACIDAD.pdf` | `REAL-12.pdf` |
| una cédula | `CED-07` |
| un nombre de persona | `<NOMBRE>` |

El seudónimo es **estable**: dos informes que hablan del mismo documento usan el mismo
`FALSA-03`, así que se pueden cruzar entre sí. La correspondencia seudónimo → documento real es
el puente con los datos personales y se queda **fuera del repo**, en
`../dataset-falsedad/SEUDONIMOS.csv`.

Todo esto lo produce `scripts/exportar_analisis.py`, que además **relativiza las rutas** (los
scripts se escribieron con rutas absolutas de la máquina donde se investigó) y **comprueba que
lo que escribe sigue compilando**. Para regenerarlo: `python scripts/exportar_analisis.py`.

## Qué hay en cada carpeta

| Carpeta | Qué contiene |
|---|---|
| `senales/` | Las cinco familias de señales de adulteración, una carpeta cada una: `probe.py` (la sonda ejecutable) e `INFORME.md` (qué detecta, medido, y su confusor principal). Cubre diagnóstico contra catálogo, aritmética de fechas, días vs diagnóstico, tipografía del PDF y reuso de la firma. |
| `duraciones/` | `01_evidencia.md` = el inventario de **cómo se escriben las duraciones de verdad** en los documentos (formas A1..A10 / B1 / C1..C6, degradaciones del OCR y 17 falsos positivos a evitar). Y los tres frentes de verificación adversarial del parser de numerales. |
| `validacion/` | Inventario de la lógica temporal que ya existía, catálogo de reglas propuesto y los tres frentes que verificaron el motor de tiempos (romper reglas, medir sobre el corpus, cazar falsos positivos). |
| `requisitos/` | `bench_ocr.py` (**el script para repetir la medición en el servidor real antes de comprar**), el inventario de software con las versiones medidas, y el dimensionamiento. |
| `*.py` en la raíz | Los generadores del corpus: manifiesto, ground truth y el parseo de `cheklistradicaciones`. |

## Para volver a ejecutar cualquier sonda

Hace falta el corpus. Los scripts lo esperan en `../dataset-falsedad/` (documentos en
`docs/{falsas,reales}/`, texto OCR en `ocr/`) y resuelven las rutas desde su propia ubicación,
así que funcionan tal cual una vez el corpus está en su sitio. Cómo reconstruirlo:
[`../REPLICAR.md`](../REPLICAR.md).

**Aviso al leer las métricas:** 5 de los 31 documentos están en **cuarentena** — dos pares son
byte-idénticos entre las dos clases (el mismo archivo entregado como falso y como real) y uno
comparte cédula con un legítimo. No sirven para medir precisión hasta que el cliente resuelva la
contradicción, y los informes lo señalan donde corresponde.
