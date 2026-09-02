# 02 · Benchmark: cuánto cuesta procesar UN documento (medido, no estimado)

**Fecha:** 2026-09-02 · **Medido en:** portátil de desarrollo (ver §2) · **Script:** [`bench_ocr.py`](bench_ocr.py)
**Datos crudos:** [`bench_1hilo.json`](bench_1hilo.json) (config A, 1 hilo ONNX) ·
[`bench_multihilo.json`](bench_multihilo.json) (config B, hilos por defecto) ·
[`bench_cap8mp.json`](bench_cap8mp.json) (config C, `OCR_MAX_PIXELS=8 MP`, subconjunto de 5 docs)

Todas las cifras de este documento salen de una medición ejecutada en esta máquina con el
pipeline local real (`RapidOCRBackend` + `RuleBasedExtractor`, el mismo par que usa el lote:
`INGESTA_EXTRACTOR=rule` en `docker-compose.yml`), o de un cálculo explícito a partir de ellas.
Donde no hay medición, el documento dice **«sin medir»**.

> **Esto es una BASE POR DOCUMENTO para extrapolar, no una promesa de throughput.** No se midió
> paralelismo con varios workers, ni Ollama, ni MySQL, ni el hardware del servidor real. Ver §11.

---

## 1. Resumen ejecutivo

**Coste de un documento con 1 hilo de OCR (= el coste de un worker del pool, plan §6.2):**

| | p50 | p90 | máx | n |
|---|---|---|---|---|
| **Tiempo de pared** | **10.9 s** | **21.8 s** | **78.4 s** | 35 |
| **CPU-segundos** | **8.6** | **12.6** | **31.4** | 35 |
| Imagen (JPEG, 0.9–1.4 MP) | 3.6 s | 6.6 s | 6.6 s | 5 |
| PDF 1 página (4.4–4.5 MP) | 10.9 s | 19.7 s | 78.4 s | 26 |
| PDF 2 páginas | 12.5 s | 27.4 s | 27.4 s | 4 |

**RAM:** 102 MB tras cargar los modelos · **971 MB de pico** en un documento normal ·
**7.6 GB de pico** en un documento real del cliente con la caja de página sobredimensionada.

**Dónde se va el tiempo:** **OCR 97.2 %**, render de PDF 2.8 %, reglas de extracción **0.01 %**
(0.062 s para los 35 documentos juntos; máximo 4.5 ms). Optimizar las reglas no sirve de nada:
el coste es el OCR, y el OCR crece con los **píxeles rasterizados de la página**.

**Los cinco hallazgos que cambian el dimensionamiento:**

1. **`PLAN_INGESTA_MASIVA.md` §6.6 es ~3× optimista.** Dice «~2–4 s/doc/core» y «6 workers →
   ~1.5–2 docs/s → 6–7 k docs/hora; 7000/mes en ~1 h». Medido: **8.6 CPU-s/doc (p50)**, es decir
   **6 workers → ~0.6 docs/s → ~2 200 docs/hora**, y **7000/mes ≈ 3.2 h**, no 1 h. La *conclusión*
   del plan (el volumen es holgadamente viable) se sostiene; sus *números* no. Ver §9.
2. **Dos de 35 documentos reales cuestan 7–8 GB de RAM cada uno** por tener la caja de página
   sobredimensionada (86.5 MP y 72.3 MP al rasterizar). Los demás se quedan en ≤971 MB. Ver §7.
3. **`OCR_MAX_PIXELS=40 MP` no protege nada.** RapidOCR usa `limit_type: min` con
   `limit_side_len: 736`: si el lado corto ya supera 736 px **no reescala**, y el detector corre a
   resolución completa. Bajarlo a **8 MP** (medido) recorta el pico de RAM de 7.6 GB a 1.6 GB y el
   coste de esos documentos a la mitad, **sin tocar los documentos normales** (4.4–4.5 MP). Ver §7.
4. **El cap de hilos ONNX del plan §6.2 no está implementado, y `OMP_NUM_THREADS` no lo hace.**
   Con los hilos por defecto un documento usa **8.67 núcleos** para ir solo **1.7× más rápido**
   (≈20 % de eficiencia) y consume **6.4× más CPU** (54.8 vs 8.6 CPU-s). El plan tiene razón; falta
   escribir el código. Ver §8.
5. **Un PDF multipágina paga TODAS sus páginas**, aunque solo una traiga la incapacidad:
   `ocr._combinar_paginas` filtra por `es_pagina_relevante` **después** de OCR-ear cada página. Un
   bundle de 30 páginas (`MAX_PDF_PAGES`) costaría ≈**260 CPU-s ≈ 4.3 min** con 1 hilo. Ver §6 y §10.

---

## 2. La máquina

| | |
|---|---|
| Equipo | HP ProBook 440 14 inch G9 Notebook PC (portátil) |
| CPU | **Intel Core i7-1255U (12ª gen)** — 10 núcleos físicos (**2 P-cores + 8 E-cores**), **12 hilos lógicos**, base 1.70 GHz |
| RAM | **32 GB** (32 400 MB visibles al SO) |
| GPU | Intel **Iris Xe** integrada — **no se usa**: `onnxruntime` expone solo `['AzureExecutionProvider', 'CPUExecutionProvider']`, todo corre en CPU |
| SO | Windows 11 Pro 10.0.26200 |
| Python | 3.14.5 · onnxruntime **1.27.0** · rapidocr-onnxruntime · pypdfium2 |
| Config del pipeline | `PDF_RENDER_SCALE=3.0` · `MAX_PDF_PAGES=30` · `OCR_MAX_PIXELS=40 000 000` (defaults del repo) |

> **Precisión sobre `CONTEXT.md` §5.2**, que dice «i7-1255U, **sin GPU** → inferencia CPU»: la
> máquina **sí** tiene GPU (Iris Xe integrada); lo correcto es que **no se aprovecha**, porque el
> build de onnxruntime instalado es solo-CPU. El efecto práctico es el mismo, pero la causa importa
> si algún día se plantea acelerar por GPU.

> **La CPU es un i7 de portátil de 15 W con núcleos heterogéneos (P y E).** Un trabajo de 1 hilo
> puede caer en un P-core (rápido) o en un E-core (lento) según el planificador, y el reloj sostenido
> depende de la temperatura. Esto es la causa principal de la dispersión de §3 y la razón por la que
> **estas cifras no se trasladan tal cual a un servidor** (§11).

---

## 3. Condiciones reales de la medición (leer antes de citar cualquier número)

La máquina **no estaba libre**. Durante todo el trabajo hubo otros procesos del mismo lote de
tareas ejecutándose (otros scripts de OCR `_explora2.py` que consumían ~7.5 de 12 hilos lógicos,
dos servidores `uvicorn` del proyecto, `pip download`/`pip install`, VS Code, Chrome/Firefox,
Defender `MsMpEng.exe`). Antes de medir, la CPU estuvo **fijada en 100 % durante minutos**.

Medidas tomadas para que la cifra no sea una mentira cómoda:

- El script **espera** hasta que la CPU del sistema baje del 55 % (3 lecturas consecutivas) antes de
  cada pasada. La pasada 1 esperó **394 s** hasta lograrlo; la pasada 2, 6 s.
- **Dos pasadas completas** sobre los 35 documentos; por documento se toma la **observación menos
  contendida** (mínimo).
- Se registra la CPU ajena consumida durante cada pasada:

| Pasada | Duración | CPU mía | CPU ajena | % del total ocupado |
|---|---|---|---|---|
| 1 | 1 162 s | 948 s | 9 114 s | **90.6 %** |
| 2 | 1 053 s | 696 s | 10 191 s | **93.6 %** |

- Se mide **CPU-segundos por documento**, no solo tiempo de pared. Los CPU-segundos son mucho más
  robustos a la contención (miden trabajo hecho, no espera). Además se calcula el ratio
  **CPU/pared por documento = núcleos efectivamente usados**: con el cap de 1 hilo salió
  **p50 = 0.96, p90 = 0.99** → en la observación seleccionada el proceso **sí tuvo un núcleo casi
  entero**, así que su tiempo de pared es una medida válida del coste de un worker.

**Dispersión residual — la advertencia importante:** entre las dos pasadas, el mismo documento varió
**×1.55 (p50), ×2.45 (p90) y hasta ×2.86 (máx)** incluso en CPU-segundos (en tiempo de pared: ×1.52
p50, ×3.98 máx). Es contención + reloj térmico +
P-core/E-core. **Léanse estas cifras como un orden de magnitud (≈10 s/documento/núcleo), no con
precisión de décimas.** Un banco de pruebas en el servidor definitivo, con la máquina quieta, es
obligatorio antes de comprometer un SLA (§12).

---

## 4. Qué se midió y qué no

**Sí, y serialmente** (un documento a la vez, un solo proceso, sin red, sin Docker, sin Ollama, sin MySQL):

```python
sys.path.insert(0, '.../incapacidad-ocr')
from incapacidad_ocr.ocr import get_ocr_backend        # RapidOCRBackend (ONNX/CPU)
from incapacidad_ocr.processor import IncapacidadProcessor
from incapacidad_ocr.extract import RuleBasedExtractor
```

El backend se construye **una sola vez** y su coste se mide aparte (§5). Por documento se cronometra:

| Fase | Qué es exactamente |
|---|---|
| `render` | `preprocess.load_pages()` — rasterizado PDFium por página, o decode del JPEG |
| `ocr` | `RapidOCRBackend._ocr_one(page)` — det + cls + rec ONNX |
| `combinar` | `ocr._combinar_paginas()` — selección de páginas relevantes |
| `extract` | `RuleBasedExtractor.extract()` + `extract.normalizar_fechas()` |

**Control de la instrumentación:** cada documento se procesó también por la API real
`IncapacidadProcessor.run(path)`. La mediana del delta fue **−2.09 s** (la API salió *más rápida*
que la suma de fases, porque corre segunda y encuentra el archivo en caché del SO). Es decir, **las
cifras publicadas son las de caché frío y por tanto conservadoras**, no infladas por la instrumentación.

**Corpus: 39 archivos → 35 documentos únicos medidos.** Se colapsaron 4 pares con contenido
idéntico (sha256), que habrían sesgado los percentiles:

| sha256[:8] | Aparece en |
|---|---|
| `28c4a946` | `falsas/FALSA-03.pdf` = `reales/REAL-15.pdf` |
| `d86ae595` | `falsas/FALSA-11.pdf` = `reales/REAL-01.pdf` |
| `b68fe146` | `reales/REAL-03.pdf` = `Ejemplos/INCAPACIDAD <NOMBRE> <NOMBRE> <NOMBRE> VĘLANDIA.pdf` |
| `942de664` | `reales/REAL-12.jpeg` = `Ejemplos/incapacidad___.jpeg` |

Composición de los 35: **26 PDF de 1 página · 5 JPEG · 4 PDF de 2 páginas**.

> **Corrección al enunciado del corpus:** el conjunto de 31 documentos de `dataset-falsedad/docs/`
> contiene «PDF multipágina», pero **todos los multipágina son de exactamente 2 páginas**. No hay ni
> un bundle profundo (10–30 páginas) como los que teme el plan §6.8. La cifra de «PDF multipágina»
> de este informe es, en rigor, **una cifra de 2 páginas**; para bundles grandes solo hay la
> extrapolación por página de §6, **sin medir**.

> **Nota de alcance con el lote real:** `batch.py` solo OCR-ea el **documento base**
> (`TIPODOC_BASE = {INCAPACIDAD, PERMISO, VACACIONES}`); los adjuntos se verifican por el nombre y
> **cuestan ~0**. En el corpus medido hay un adjunto (`REAL-10.pdf`, 23.2 CPU-s) que en
> producción **no se OCR-earía**. Medirlo hace la cifra conservadora.

---

## 5. Arranque: el coste de una sola vez (NO se cobra por documento)

| | Config A (1 hilo) | Config B (hilos por defecto) |
|---|---|---|
| `import incapacidad_ocr...` | 0.10 s | 0.01 s |
| **`RapidOCRBackend()`** (carga de los 3 modelos ONNX) | **1.22 s** | **0.86 s** |
| **RSS con el backend ya cargado (`ram_arranque_mb`)** | **101.7 MB** | 106.7 MB |
| RSS antes de importar | 39.0 MB | 38.9 MB |

**Sobrecoste de la primera inferencia:** el mismo documento corrido 3 veces seguidas tras cargar el
backend dio `[13.08, 8.28, 17.03] s` → la primera pagó **≈4.8 s extra** (inicialización perezosa de
ONNX). Es **una medición única y ruidosa** (el 3.er valor, 17.03 s, es contención pura), tómese como
«del orden de 5 s». Un pool de workers lo paga **una vez por proceso**, no por documento — razón de
más para procesos persistentes con `maxtasksperchild` alto, como ya plantea el plan §6.1.

Cargar los modelos es baratísimo (~1 s, ~63 MB de RSS). **El coste real está íntegramente en
inferir, no en arrancar.**

---

## 6. Dónde se va el tiempo

Reparto sobre la suma de los 35 documentos (config A, 1 hilo):

| Fase | % del total | p50 | p90 | máx | Suma (35 docs) |
|---|---|---|---|---|---|
| **OCR** (ONNX det+cls+rec) | **97.2 %** | 10.75 s | 21.44 s | 73.28 s | 448.8 s |
| **Render** PDF/decode JPEG | **2.8 %** | 0.14 s | 0.38 s | 5.10 s | 12.83 s |
| `combinar_paginas` | ~0 % | 0.000 s | 0.000 s | 0.0004 s | — |
| **Reglas** (`extract` + `normalizar_fechas`) | **0.013 %** | 0.002 s | 0.003 s | **0.0045 s** | **0.062 s** |

**Conclusiones operativas:**

- **El extractor por reglas es gratis.** 2 ms por documento. Cambiar reglas, añadir formatos de EPS o
  endurecer heurísticas **no tiene coste de rendimiento**. (El extractor híbrido sí lo tendría: mete
  una llamada a Ollama — **sin medir aquí**, §11.)
- **El render de PDF es casi gratis** en documentos normales (0.14 s p50). Solo se dispara en las
  páginas sobredimensionadas (5.10 s), donde además hay que rasterizar 346 MB de bitmap RGBA.
- **Todo el presupuesto es el OCR**, y el OCR escala con el **área rasterizada**, no con el peso del
  archivo ni con la cantidad de texto. Prueba: `REAL-07.pdf` pesa **12 KB** (el
  archivo más liviano del corpus) y es el **más caro** (78.4 s de pared), porque su página mide
  7152×10110 px al rasterizar.

**Modelo empírico del coste de OCR** (config A, ajustado a 0.9 / 4.45 / 40 MP):

```
CPU-s ≈ 2.2 + 1.4 × (megapíxeles rasterizados)      para páginas de hasta ~5 MP
```
Comprobación: 0.9 MP → 3.5 predicho vs **3.50 medido** · 4.45 MP → 8.4 vs **8.6 medido**.
Por encima de ~5 MP el crecimiento se vuelve sublineal (40 MP → 31 CPU-s, ~0.78 CPU-s/MP).

**Por página (PDF):** p50 **10.9 s/página**, p90 15.1 s/página. Los 4 PDF de 2 páginas costaron
10.8–23.2 CPU-s, ≈2× un PDF de 1 página → **el coste es por página, sin economía de escala**.
Extrapolación (**calculada, sin medir**): un bundle de 30 páginas (`MAX_PDF_PAGES=30`) ≈
30 × 8.6 = **258 CPU-s ≈ 4.3 min** con 1 hilo. Esto fija el suelo del `INGESTA_REAPER_TTL`
(plan §6.4/§9.3): un TTL calculado sobre «el peor documento medido» (31 CPU-s) reencolaría un bundle
legítimo a mitad de proceso y provocaría doble inserción. **El TTL debe superar los ~5 min, no los ~30 s.**

---

## 7. RAM — y el hallazgo de las páginas sobredimensionadas

| | Valor |
|---|---|
| **`ram_arranque_mb`** (proceso con el backend cargado, sin procesar nada) | **101.7 MB** |
| Pico de RSS, documentos normales (33 de 35, ≤10 MP/página) | p50 **899 MB** · **máx 971 MB** |
| Pico de RSS, imágenes JPEG (0.9–1.4 MP) | 229–328 MB |
| **`ram_pico_mb`** (documento más caro: `REAL-07.pdf`, 72.3 MP) | **7 647 MB** |
| Segundo peor (`INC <NOMBRE> DE LA HOZ … 02.09.2025.pdf`, 86.5 MP) | 6 810 MB |
| `peak_wset` del proceso (pico de working set, Windows) | 7 782 MB |
| RSS al terminar las 2 pasadas | **72 MB** → la memoria **se libera** correctamente; no hay fuga |

**Por qué 7.6 GB.** `preprocess.pdf_to_images` rasteriza a `PDF_RENDER_SCALE=3.0`. Esos dos
documentos tienen la caja de página enorme, así que salen a 11784×7344 px (86.5 MP) y 7152×10110 px
(72.3 MP) — **346 MB y 289 MB de bitmap RGBA**, materializados *antes* de `_cap_pixels`. Después
`_cap_pixels` los baja a 40 MP… y **40 MP siguen siendo enormes**: RapidOCR entrega la página al
detector DB **sin reescalar**, porque su config es `limit_type: min` con `limit_side_len: 736`
(`ch_ppocr_v3_det/utils.py`: si `min(h,w) >= 736` entonces `ratio = 1.0`). Un tensor de entrada de
40 MP × 3 canales × 4 bytes = 480 MB, más los mapas de activación del backbone → varios GB.

**El lever, medido.** Con `OCR_MAX_PIXELS=8000000` (8 MP) y todo lo demás igual:

| Documento | MP/pág | 40 MP (default): pared / CPU-s / pico RAM | **8 MP: pared / CPU-s / pico RAM** |
|---|---|---|---|
| `REAL-07.pdf` | 72.3 | 78.4 s / 31.2 / **7 648 MB** | **15.9 s / 15.3 / 1 555 MB** |
| `INC <NOMBRE> DE LA HOZ …pdf` | 86.5 | 32.5 s / 31.4 / **6 810 MB** | **13.7 s / 13.3 / 1 589 MB** |
| `REAL-14.pdf` | 4.4 | 13.1 s / 8.4 / 864 MB | 9.4 s / 9.1 / 908 MB |
| `REAL-04.pdf` | 4.4 | 11.0 s / 8.6 / 899 MB | 4.2 s / 4.0 / 905 MB |
| `REAL-12.jpeg` | 0.9 | 3.6 s / 3.5 / 229 MB | 3.9 s / 3.6 / 221 MB |

**Pico de RAM ÷4.3–4.9 y coste ÷2.0–2.4 en los documentos patológicos; los normales, intactos** (sus 4.4 MP
están por debajo del cap nuevo, así que ni se tocan — las diferencias que se ven en esas filas son
la dispersión de ±1.5× de §3, no efecto del cap).

**Recomendación (con su condición):** bajar `OCR_MAX_PIXELS` de 40 MP a **8–10 MP**. Es un cambio de
variable de entorno, sin código. **Condición:** hay que **re-validar la precisión de extracción** con
el cap nuevo antes de adoptarlo — reescalar de 40 MP a 8 MP puede degradar la lectura de letra
pequeña en esos escaneos. Eso **no se midió aquí** (este informe mide coste, no exactitud).

### 7.1 Correcciones que exige este hallazgo

- **`README.md` §Requisitos mínimos: «RAM mínimo 4 GB (solo RapidOCR)» es falso con los defaults
  actuales.** Un documento real del cliente pide **7.6 GB** en un solo proceso. Con 4 GB ese
  documento muere por falta de memoria. Incluso un documento **normal** llega a **971 MB**, que con
  el SO y el contenedor no cabe cómodamente en 4 GB. Redacción correcta: **8 GB mínimo con los
  defaults actuales**, o 4 GB **solo si** se baja `OCR_MAX_PIXELS` a ~8 MP y se procesa de a un
  documento.
- **`README.md` §Seguridad: «cada página se acota a `OCR_MAX_PIXELS` (40 MP) para no disparar la RAM
  en escaneos enormes»** describe un guardarraíl que, con su valor por defecto, **no guarda**: 40 MP
  es precisamente el régimen en el que la RAM se dispara. El mecanismo está bien; el default está mal.
- **`PLAN_INGESTA_MASIVA.md` §6.8** atribuye el riesgo de RAM a «un bundle grande a scale 3.0
  materializado entero» y lo resuelve con streaming. El streaming **ya está** (`load_pages` es
  generador) y **no ayuda aquí**: el pico lo produce **una sola página** con MediaBox
  sobredimensionada. El riesgo real es por página, no por bundle.
- **`CONTEXT.md` §9 (fila 3 de la tabla de seguridad)** está desactualizado: dice
  `MAX_PDF_PAGES=20` e `Image.MAX_IMAGE_PIXELS=64M`. El código (`preprocess.py`) usa **30** y
  **200 000 000**. El `README.md` sí está correcto; hay que alinear `CONTEXT.md`.

---

## 8. Hilos de ONNX: el plan §6.2 tiene razón, y aquí está el número

Se midió el corpus completo dos veces con dos configuraciones:

| | **A — 1 hilo ONNX** (`intra_op_num_threads=1`) | **B — hilos por defecto** |
|---|---|---|
| Núcleos efectivos por documento (CPU/pared) | **0.96** (p50) | **8.67** (p50) |
| Pared p50 | 10.9 s | **6.3 s** |
| Pared p90 / máx | 21.8 s / 78.4 s | 12.3 s / 22.7 s |
| **CPU-s p50** | **8.6** | **54.8** |
| CPU-s p90 / máx | 12.6 / 31.4 | 106.9 / 148.5 |
| CPU-s media (35 docs) | **9.9** | **62.0** |
| Pico de RAM (doc normal / patológico) | 971 MB / 7 648 MB | 993 MB / 7 795 MB |

**Interpretación:** los hilos por defecto usan **8.67 núcleos** para conseguir solo **1.7× menos
latencia** → **≈20 % de eficiencia paralela**, y **6.4× más CPU por documento**. Para *throughput*
(7000/mes) eso es un desperdicio de 6×. Para *latencia interactiva* de la UI (un auxiliar esperando
un documento) los 6.3 s son mejores que 10.9 s, pero solo si la máquina está libre.

**Dos correcciones importantes:**

1. **El cap de hilos NO está implementado en el repo.** `rapidocr-onnxruntime` construye sus
   `SessionOptions` (`rapidocr_onnxruntime/utils.py`, clase `OrtInferSession`) **sin tocar
   `intra_op_num_threads`**, así que onnxruntime aplica su default (todos los núcleos físicos). Ni
   `webapp.py` ni `batch.py` lo capan. El plan §6.2 y el riesgo §11.20 lo dan por resuelto con
   «`OMP_NUM_THREADS=1` + `intra_op_num_threads=1` antes de importar rapidocr»: **la primera mitad no
   funciona** — onnxruntime 1.27 CPU usa su propio pool de hilos, no OpenMP, así que
   `OMP_NUM_THREADS` no tiene efecto. Hay que fijar `intra_op_num_threads` de verdad.
2. **En este benchmark se logró** sustituyendo la clase `SessionOptions` que ve el módulo antes de
   construir `RapidOCR()` (ver `capar_hilos_onnx()` en `bench_ocr.py`). Se verificó **empíricamente**
   con el ratio CPU/pared: 0.96 con el cap vs 8.67 sin él. En el producto conviene resolverlo mejor
   (p. ej. pasando `intra_op_num_threads` por la config de RapidOCR, o fijando
   `session_options` en un wrapper propio) en vez de parchear la librería.

**Buena noticia para el escalado:** como un solo documento **no** aprovecha más de ~1 núcleo de forma
eficiente, añadir workers **sí** debería escalar casi linealmente, tal como afirma el plan §6.2.
**Pero eso no se midió** (§11) — competencia por ancho de banda de memoria y por la caché L3 puede
recortarlo, y en esta CPU los E-cores rinden menos que los P-cores, así que el worker nº 3 no valdrá
lo mismo que el nº 1.

---

## 9. Extrapolación a los ~7000 documentos/mes del cliente

**Base:** media **9.92 CPU-s/documento** (35 docs, config A, mezcla medida incluyendo los 2
patológicos). Si se excluyen los 2 patológicos: 8.63 CPU-s.

```
7000 docs/mes × 9.92 CPU-s = 69 440 CPU-s = 19.3 CPU-horas/mes
```

| Workers (1 hilo cada uno) | 7000 docs/mes | Ráfaga de 1500 docs | docs/hora | docs/s |
|---|---|---|---|---|
| 1 | 19.3 h | 4.1 h | 363 | 0.10 |
| 4 | **4.8 h** | 1.0 h | 1 451 | 0.40 |
| **6** | **3.2 h** | **41 min** | **2 176** | **0.60** |
| 8 | 2.4 h | 31 min | 2 902 | 0.81 |
| 12 | 1.6 h | 21 min | 4 353 | 1.21 |

**Supuestos explícitos** (si alguno cae, la tabla cae):
1. Escalado **lineal** con los workers — **sin medir** (§11), y con el cap de hilos §8 aún **sin implementar**.
2. Todos los 7000 son documentos base que se OCR-ean. En la práctica los adjuntos cuestan ~0, así
   que 7000 *archivos*/mes serían **menos** de 7000 OCR → la tabla es conservadora por ese lado.
3. La mezcla de tipos y tamaños del cliente se parece a la medida (26/5/4 y 4.4–4.5 MP por página).
4. El servidor rinde por núcleo como este i7-1255U de portátil — **el supuesto más frágil** (§11).
5. No incluye MySQL, ni movimiento de archivos, ni Ollama, ni la revisión humana.

**Corrección a `PLAN_INGESTA_MASIVA.md` §6.6.** La tabla del plan dice:

| | Plan §6.6 | **Medido / calculado aquí** |
|---|---|---|
| Coste por documento | «~2–4 s/doc/core» | **8.6 CPU-s p50**, 12.6 p90, 31.4 máx |
| 8 cores / 6 workers | «~1.5–2 docs/s → ~6–7 k docs/hora» | **~0.60 docs/s → ~2 200 docs/hora** |
| 7000/mes | «en ~1 h» | **≈3.2 h** |
| Ráfaga de 1500 | «en ~12–15 min» | **≈41 min** |
| Presupuesto de RAM | `floor(RAM_libre_GB / 1.0)` → 1 GB/worker | **971 MB de pico en documentos normales** → 1 GB deja **cero** margen; recomendable **1.5 GB/worker**. Y con los defaults actuales **un** documento patológico pide **7.6 GB** (§7) |

El plan sigue siendo correcto en lo esencial (7000/mes cabe de sobra en una ventana nocturna), pero
si se le vende al cliente «7000 en 1 hora» se le está vendiendo ~3× más de lo que da esta base.

---

## 10. Coste que este informe NO carga pero el sistema sí paga

- **PDF multipágina completo.** `RapidOCRBackend.read_text` hace
  `[self._ocr_one(page) for page in pages]` y **solo después** `_combinar_paginas` descarta las
  páginas irrelevantes. Un trámite escaneado en un solo PDF de 12 páginas donde la incapacidad está
  en la página 3 paga **las 12**. Optimización posible (no implementada): parar cuando ya se encontró
  una página relevante, o clasificar por página con un OCR más barato antes del OCR completo.
  Ahorro potencial **sin medir**.
- **Adjuntos.** Cuestan ~0 (solo parseo del nombre) — el lote ya lo hace bien.

---

## 11. Lo que esta medición NO cubre (y por qué)

1. **Rendimiento con varios workers en paralelo — SIN MEDIR.** Todo se midió con **un solo proceso**.
   No es lineal: las sesiones ONNX compiten por ancho de banda de memoria y caché L3, el pico de RAM
   se multiplica por worker (§7: 2 workers con documentos patológicos = ~15 GB), y en esta CPU
   híbrida los workers que caigan en E-cores rendirán menos. La tabla de §9 **asume** linealidad;
   hay que medirla con el pool real (plan Fase 2) antes de fijar `INGESTA_WORKERS`.
2. **Ollama (visión y LLM) — SIN MEDIR.** No está corriendo en esta máquina (solo el proceso de
   bandeja, 12 MB de RSS, sin modelo cargado) y no se puede levantar aquí. El extractor **híbrido**
   (default de la UI) y el path `ocr=ollama` (necesario para permisos manuscritos, `CLAUDE.md`)
   añaden una o más llamadas de inferencia LLM que, según `CONTEXT.md` §5.2/§5.3, van de ~20–40 s
   (híbrido) a 1–4 min (visión) en CPU. **Esos números son de junio de 2026 y no se re-verificaron
   aquí.** El lote usa `rule`, así que el hot path medido es el correcto; pero cualquier documento
   que escale a Ollama sale de este presupuesto.
3. **Latencia de MySQL — SIN MEDIR.** No hay BD levantada. Los lookups (cédula→empleado, CIE-10,
   EPS), el INSERT en `lp_ausentismos_ia`, la alerta documental y —en la Fase 2— el claim con
   `SELECT … FOR UPDATE SKIP LOCKED` y el `GET_LOCK` por caso son round-trips que no están en estas
   cifras. Con la BD en el mismo host serán milisegundos frente a ~10 s de OCR (irrelevante); con la
   BD ASTGU remota, y con N workers golpeando la misma tabla, puede dejar de serlo.
4. **El hardware del servidor real — DESCONOCIDO.** Esto es un **portátil de 15 W** con núcleos
   heterogéneos (2 P + 8 E), reloj base 1.70 GHz y límites térmicos. Un servidor con núcleos
   uniformes y reloj sostenido puede rendir bastante distinto **en cualquiera de los dos sentidos**.
   Además **el SO del servidor sigue sin decidirse** (Windows Server vs Linux — precondición «P2»,
   plan §5): la lógica corre en contenedores Linux en ambos casos, pero **no se midió** el sobrecoste
   del bind mount, que en Docker Desktop/Windows va por gRPC-FUSE y es notoriamente más lento que un
   bind mount nativo de Linux. Con documentos de 100–1800 KB y ~10 s de CPU por documento se espera
   que sea despreciable, pero **es una expectativa, no una medición**.
5. **Docker — NO VERIFICADO EN ESTA MÁQUINA.** Docker no está corriendo (requiere elevación UAC que
   la sesión no tiene). Todo se midió **nativo en Windows con el venv del proyecto**. Dentro del
   contenedor (`python:3.12-slim`, Python **3.12** vs **3.14** aquí, glibc vs Windows, distinto build
   de onnxruntime) las cifras pueden moverse. Los tamaños de imagen del README (~1.1 GB web, ~8.3 GB
   Ollama, ~3.3 GB `gemma3:4b`) quedan como **estimados, sin verificar en esta máquina**.
6. **Exactitud de la extracción — FUERA DE ALCANCE.** Este informe mide **coste**, no si el JSON sale
   bien. Se registró `chars_ocr` por documento (mínimo 730, mediana 1 044, **ningún** documento cayó
   por debajo de `MIN_OCR_CHARS`, así que el extractor corrió en los 35) pero no se comparó contra
   ground-truth.
7. **Ráfagas y cola en caliente — SIN MEDIR.** El escaneo de `1_entrada/`, el hash sha256 de cada
   archivo, la verificación de estabilidad y los movimientos de archivos no se cronometraron.

---

## 12. Cómo reproducir esto en el servidor del cliente

`bench_ocr.py` es autocontenido: solo necesita el venv del proyecto + `psutil`. No usa red, ni
Docker, ni Ollama, ni MySQL — se puede correr en el servidor definitivo antes de dimensionar.

```bash
PY=/ruta/al/venv/bin/python          # en Windows: .venv/Scripts/python.exe
$PY -m pip install psutil

# A) coste por WORKER (el que se multiplica por N workers) — el número que importa
$PY bench_ocr.py --repo /ruta/incapacidad-ocr --docs /ruta/muestra \
   --repeats 3 --hilos 1 --esperar-cpu 25 --etiqueta "servidor-1hilo" \
   --out-json bench_1hilo.json --out-md tabla_1hilo.md

# B) latencia de un documento tal como corre la UI hoy (sin cap de hilos)
$PY bench_ocr.py --repo /ruta/incapacidad-ocr --docs /ruta/muestra \
   --repeats 2 --etiqueta "servidor-multihilo" --out-json bench_multihilo.json

# C) efecto de acotar los píxeles por página (§7)
OCR_MAX_PIXELS=8000000 $PY bench_ocr.py ... --hilos 1 --out-json bench_cap8.json
```

**Con la máquina quieta** (`--esperar-cpu 25`) y **≥3 pasadas**, para que la dispersión de §3 no
domine. El JSON incluye las condiciones de cada pasada (CPU ajena, procesos que competían, RAM
disponible), así que siempre se puede saber si una cifra es limpia o no.

**Lo que falta medir en el servidor, en orden de importancia:**
1. Escalado real del pool (1, 2, 4, 6, 8 workers) con el cap de hilos §8 **ya implementado**: docs/s
   y RSS agregado. Es lo único que convierte §9 de cálculo en compromiso.
2. Coste con `OCR_MAX_PIXELS=8 MP` **junto con** la re-validación de exactitud (§7).
3. Un bundle real de 10–30 páginas, para fijar `INGESTA_REAPER_TTL` (§6).
4. Latencia de MySQL contra la BD ASTGU real, con N workers concurrentes.
5. Sobrecoste del bind mount en el SO que se elija (§11.4).

---

## 13. Tabla completa: los 35 documentos (config A, 1 hilo ONNX)

`total s` = tiempo de pared de la observación menos contendida de 2 pasadas ·
`CPU s` = CPU-segundos (robusto a contención) · `MP/pág` = megapíxeles de la página mayor al
rasterizar a `PDF_RENDER_SCALE=3.0` · `pico RSS` = máximo muestreado cada 25 ms.
Ordenada por CPU-segundos descendente. Recordar la dispersión de ±1.5× de §3.

| # | Documento | Tipo | Pág | MP/pág | KB | render s | OCR s | reglas s | **total s** | **CPU s** | pico RSS MB | chars OCR |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | FALSA-04.pdf | pdf_1pag | 1 | 86.5 | 1575 | 2.96 | 29.52 | 0.002 | **32.51** | **31.41** | 6810 | 994 |
| 2 | REAL-07.pdf | pdf_1pag | 1 | 72.3 | 12 | 5.10 | 73.28 | 0.002 | **78.39** | **31.22** | 7648 | 1218 |
| 3 | REAL-10.pdf *(adjunto: en producción no se OCR-ea)* | pdf_multipag | 2 | 4.4 | 202 | 0.12 | 27.29 | 0.003 | **27.41** | **23.20** | 854 | 3152 |
| 4 | REAL-05.pdf | pdf_multipag | 2 | 4.5 | 1787 | 0.31 | 21.44 | 0.004 | **21.76** | **12.58** | 971 | 1022 |
| 5 | ALEJANDRO LINARES.pdf | pdf_multipag | 2 | 4.4 | 223 | 0.24 | 12.24 | 0.001 | **12.48** | **12.11** | 868 | 1865 |
| 6 | FALSA-15.pdf | pdf_1pag | 1 | 4.4 | 170 | 0.10 | 11.40 | 0.003 | **11.51** | **11.20** | 901 | 1231 |
| 7 | FALSA-10.pdf | pdf_multipag | 2 | 4.5 | 156 | 0.11 | 11.41 | 0.002 | **11.52** | **10.83** | 945 | 933 |
| 8 | FALSA-11.pdf | pdf_1pag | 1 | 4.5 | 240 | 0.29 | 11.58 | 0.002 | **11.87** | **10.78** | 962 | 1127 |
| 9 | FALSA-01.pdf | pdf_1pag | 1 | 4.4 | 190 | 0.06 | 10.75 | 0.002 | **10.81** | **10.44** | 904 | 1513 |
| 10 | FALSA-03.pdf | pdf_1pag | 1 | 4.4 | 339 | 0.11 | 11.90 | 0.002 | **12.02** | **10.39** | 910 | 1272 |
| 11 | REAL-06.pdf | pdf_1pag | 1 | 4.5 | 947 | 0.38 | 19.31 | 0.002 | **19.69** | **10.23** | 955 | 1486 |
| 12 | FALSA-12.pdf | pdf_1pag | 1 | 4.5 | 310 | 0.23 | 10.27 | 0.002 | **10.49** | **10.17** | 964 | 951 |
| 13 | REAL-03.pdf | pdf_1pag | 1 | 4.5 | 913 | 0.19 | 13.72 | 0.003 | **13.91** | **10.09** | 957 | 1450 |
| 14 | FALSA-02.pdf | pdf_1pag | 1 | 4.4 | 258 | 0.07 | 10.39 | 0.002 | **10.46** | **10.00** | 906 | 1179 |
| 15 | FALSA-14.pdf | pdf_1pag | 1 | 4.5 | 319 | 0.15 | 12.18 | 0.002 | **12.32** | **9.45** | 963 | 915 |
| 16 | REAL-09.pdf | pdf_1pag | 1 | 4.4 | 945 | 0.42 | 10.48 | 0.002 | **10.89** | **9.09** | 883 | 1179 |
| 17 | REAL-11.pdf | pdf_1pag | 1 | 4.4 | 140 | 0.18 | 13.27 | 0.002 | **13.45** | **9.09** | 873 | 1326 |
| 18 | FALSA-13.pdf | pdf_1pag | 1 | 4.5 | 385 | 0.13 | 8.70 | 0.001 | **8.83** | **8.61** | 963 | 948 |
| 19 | REAL-04.pdf | pdf_1pag | 1 | 4.4 | 164 | 0.11 | 10.84 | 0.001 | **10.95** | **8.55** | 899 | 964 |
| 20 | REAL-14.pdf | pdf_1pag | 1 | 4.4 | 221 | 0.17 | 12.96 | 0.003 | **13.13** | **8.41** | 864 | 1244 |
| 21 | FALSA-07.pdf | pdf_1pag | 1 | 4.4 | 148 | 0.06 | 8.47 | 0.002 | **8.53** | **8.33** | 904 | 1160 |
| 22 | REAL-08.pdf | pdf_1pag | 1 | 4.4 | 298 | 0.27 | 14.87 | 0.003 | **15.14** | **8.33** | 858 | 1113 |
| 23 | REAL-13.pdf | pdf_1pag | 1 | 4.5 | 123 | 0.04 | 8.71 | 0.001 | **8.76** | **8.31** | 897 | 864 |
| 24 | FALSA-06.pdf | pdf_1pag | 1 | 4.5 | 350 | 0.17 | 10.11 | 0.002 | **10.28** | **7.39** | 884 | 1015 |
| 25 | FALSA-08.pdf | pdf_1pag | 1 | 4.5 | 208 | 0.16 | 7.07 | 0.001 | **7.23** | **7.19** | 962 | 899 |
| 26 | REAL-02.pdf | pdf_1pag | 1 | 4.4 | 256 | 0.24 | 11.48 | 0.002 | **11.72** | **7.11** | 899 | 1287 |
| 27 | FALSA-05.pdf | pdf_1pag | 1 | 4.4 | 144 | 0.05 | 6.51 | 0.001 | **6.56** | **6.34** | 904 | 1031 |
| 28 | Incapacidad (19)_unlocked.pdf | pdf_1pag | 1 | 4.5 | 66 | 0.05 | 6.35 | 0.001 | **6.40** | **6.33** | 896 | 1000 |
| 29 | CESAR ARMANDO LANCHEROS CHAPARRO_INCAPACIDAD.pdf | pdf_1pag | 1 | 4.4 | 204 | 0.14 | 6.29 | 0.003 | **6.43** | **6.19** | 858 | 1054 |
| 30 | incapacidad.pdf | pdf_1pag | 1 | 4.5 | 891 | 0.14 | 5.99 | 0.001 | **6.12** | **6.03** | 909 | 1044 |
| 31 | REAL-16.jpeg | imagen | 1 | 1.4 | 140 | 0.02 | 6.61 | 0.002 | **6.63** | **4.86** | 316 | 889 |
| 32 | incapacidad.jpeg | imagen | 1 | 1.4 | 192 | 0.03 | 4.00 | 0.001 | **4.04** | **3.84** | 328 | 875 |
| 33 | REAL-12.jpeg | imagen | 1 | 0.9 | 113 | 0.02 | 3.62 | 0.001 | **3.64** | **3.50** | 229 | 801 |
| 34 | FALSA-09.jpeg | imagen | 1 | 1.1 | 93 | 0.01 | 3.17 | 0.001 | **3.19** | **3.09** | 268 | 821 |
| 35 | incapacidad_.jpeg | imagen | 1 | 1.4 | 157 | 0.02 | 2.61 | 0.001 | **2.63** | **2.66** | 314 | 730 |

La tabla equivalente de la config B (hilos por defecto) está en
[`_tabla_multihilo.md`](_tabla_multihilo.md).
