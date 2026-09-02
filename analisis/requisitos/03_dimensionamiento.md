# 03 — Dimensionamiento de hardware para `incapacidad-ocr` (Gruppo)

**Fecha:** 2026-09-02 · **Base de cálculo:** la medición de [`02_benchmark.md`](02_benchmark.md)
(`bench_1hilo.json`, `bench_cap8mp.json`) + lectura del código del repo + medición del corpus de
`dataset-falsedad/docs`. **Ninguna cifra de este documento viene de un blog o de un promedio de
industria**: cada una tiene al lado su origen (medido / leído del repo / calculado).

> **Lo que este documento NO es.** No es un compromiso de SLA. La medición base se hizo en un
> **portátil de 15 W con núcleos heterogéneos** (i7-1255U: 2 P-cores + 8 E-cores) y **bajo contención
> real**, y el mismo documento varió **×1.55 (p50) a ×2.86 (max)** entre dos pasadas incluso en
> CPU-segundos. Todas las cifras por documento se leen como **orden de magnitud (~10 s/documento/núcleo)**.
> Antes de comprometer una ventana horaria hay que **repetir el banco en el servidor definitivo**, con
> la máquina quieta y ≥3 pasadas.

---

## 0. Resumen para decidir la compra

| | Valor | Origen |
|---|---|---|
| Trámites/mes (lo que dice el cliente) | **7 000** | cliente (CONTEXT §1) |
| Documentos que se **OCR-ean**/mes | **7 000** | = 1 doc base por trámite (`batch.TIPODOC_BASE`) |
| Documentos que se **mueven**/mes (base + soportes + reenvíos) | **14 700** | calculado, §1 |
| CPU necesaria/mes | **16,6 – 18,5 CPU-h** | calculado sobre 8,53 / 9,53 CPU-s/doc medidos |
| CPU necesaria en el **día pico** | **2,1 – 2,3 CPU-h** | calculado, §2 |
| Workers recomendados | **4** | §2.4 (el volumen solo exige 1; los otros 3 son margen justificado) |
| Perfil recomendado | **8 núcleos / 16 GB / 500 GB SSD / sin GPU** | §3 |
| Crecimiento de disco | **~5,4 GB/mes → 65 GB/año → 324 GB a 5 años** | calculado sobre 384,7 KB/archivo medidos |

**El volumen del cliente cabe de sobra** — igual que concluía `PLAN_INGESTA_MASIVA.md` §6.6. Lo que
cambia respecto al plan son los **números** (el plan es ~3× optimista, §6) y, sobre todo, que el
dimensionamiento **depende de dos cambios que hoy NO están en el repo**:

> ### ⚠ Dos precondiciones del dimensionamiento (sin ellas, estos perfiles no aplican)
>
> 1. **`OCR_MAX_PIXELS=8000000`** (hoy 40 MP). Con el default, **2 de 31** documentos reales del corpus
>    piden **7,6 GB y 6,8 GB de RAM cada uno** (§4.2). Con 8 MP: medido 1 555 y 1 589 MB (÷4,4 a ÷4,9) y
>    **10,5 % menos CPU** en el conjunto. Es un cambio de variable de entorno, sin código.
>    **Condición: hay que re-validar la EXACTITUD de extracción con el cap nuevo** — reescalar 40→8 MP
>    puede degradar letra pequeña, y eso NO se midió.
> 2. **Cap de hilos ONNX a 1 por worker** (`PLAN §6.2`, `intra_op_num_threads=1`). **No está implementado**
>    y `OMP_NUM_THREADS` no lo consigue: `rapidocr_onnxruntime/utils.py::OrtInferSession.__init__`
>    construye `SessionOptions()` **sin tocar `intra_op_num_threads`** (verificado leyendo el paquete
>    instalado), y onnxruntime 1.27 CPU usa su propio pool, no OpenMP. Sin el cap, un solo documento
>    ocupa **8,67 núcleos para ir solo 1,7× más rápido** (~20 % de eficiencia paralela, 6,4× más CPU):
>    la tabla de throughput por workers de §2 deja de valerse.
>
> Ambas son baratas. La primera es una variable de entorno; la segunda son ~3 líneas en el
> `initializer` del pool de la Fase 2 (`PLAN §6.1`).

---

## 1. De «7 000 incapacidades/mes» a carga real

### 1.1 Un trámite ≠ un documento, y solo UNO se OCR-ea

Regla de dominio del repo (`CLAUDE.md` §Reglas de dominio · `batch.py:67` y `batch.py:230-234`):

```python
TIPODOC_BASE = {"INCAPACIDAD", "PERMISO", "VACACIONES"}
...
bases = [a for a in archivos if a["tipo"] in TIPODOC_BASE]
base  = bases[0] if bases else None
if base is not None:
    result = IncapacidadProcessor(ocr_backend, extractor).run(base["path"])
```

Los adjuntos (`FURAT` · `FURIPS` · `EPICRISIS` · `HISTORIA` · `NACIDOVIVO` · `REGISTROCIVIL` ·
`DEFUNCION` · `CEDULA` · `FORMULA` · `ORDEN` · `OTRO`) **se identifican por el NOMBRE del archivo y no
pasan por el OCR**: solo entran a `presentes` para `erp.validar_documentacion`. **Coste de CPU de un
adjunto = 0** (solo un `stat`, un `shutil.move` y una entrada en un `set`).

Esto parte el dimensionamiento en dos ejes que **no se dimensionan igual**:

| Eje | Qué lo consume | Escala con |
|---|---|---|
| **CPU / RAM / tiempo de ventana** | solo el documento BASE | **7 000/mes** |
| **Disco / número de ficheros / I-O / MAX_PATH / tiempo de backup** | TODOS los archivos | **14 700/mes** |

**Confundirlos sobredimensiona la CPU por ×2,1 o subdimensiona el disco por ×2,1.**

### 1.2 Cuántos adjuntos por trámite (supuesto, §7 S4)

Derivado de `erp.REQUISITOS_DEFAULT` / `PLAN §7.4` cruzado con una mezcla de tipos declarada:

| Tipo de ausentismo | Adjuntos obligatorios | Mezcla supuesta |
|---|---|---|
| Enfermedad general (3) | 1 (soporte clínico) | 88 % |
| Accidente de trabajo / Enf. laboral (2/8) | 1 (`FURAT`) | 5 % |
| Licencia maternidad (5) | 2 (`HISTORIA` + nacido vivo/registro civil) | 2 % |
| Licencia paternidad (9) | 1 | 1 % |
| Tránsito no laboral (11) | 1 (`FURIPS`) | 1 % |
| Permiso / Vacaciones / Prelicencia (7/12/13/10) | 0 | 3 % |

`0,88×1 + 0,05×1 + 0,02×2 + 0,01×1 + 0,01×1 + 0,03×0 = 0,99` → **1,0 adjunto/trámite**.

```
archivos que se mueven/mes = 7 000 trámites × (1 base + 1,0 adjunto) × 1,05 (reenvíos) = 14 700
```

El 1,05 cubre el reenvío recomprimido por WhatsApp (`PLAN §11` riesgo 18: llega con **hash distinto** y
hoy **no hay dedup**, §5 B4). Si el punto de recepción adjunta además cédula/fórmula/orden por
costumbre, el ratio sube a 2 y el disco a **485 GB a 5 años** (§4.3) — **es el supuesto más sensible de
todo el documento** y es una pregunta de una frase para Diana.

---

## 2. Carga diaria, día pico y ventana nocturna

### 2.1 Coste medido por documento OCR-eado

De `bench_1hilo.json` (35 documentos únicos, 2 pasadas, se toma la observación menos contendida;
ratio CPU/pared p50 = 0,96 → el proceso tuvo un núcleo casi entero, así que el tiempo de pared es
una medida válida del coste de un worker):

| Conjunto | n | media CPU-s | p50 | p90 | max |
|---|---|---|---|---|---|
| Los 35 medidos | 35 | 9,92 | 8,61 | 12,58 | 31,41 |
| **Solo documentos BASE** (sin `REAL-10.pdf`, que en producción NO se OCR-ea) | 34 | **9,53** | 8,55 | 12,11 | 31,41 |
| Solo BASE, **con `OCR_MAX_PIXELS=8 MP`** (sustituyendo los 2 patológicos por su medición del cap) | 34 | **8,53** | — | — | 15,25 |

Para agregados se usa la **media**, no el p50 (el trabajo total es `N × media`; el p50 subestimaría
la cola). **Se redondea a ~10 CPU-s/documento/núcleo** para la aritmética de cabeza, coherente con la
dispersión medida ×1,55–×2,86.

> **Reparto del tiempo** (medido, suma de los 35): OCR ONNX **97,2 %** · render PDF/decode JPEG 2,8 % ·
> `RuleBasedExtractor.extract` + `normalizar_fechas` **0,013 %** (0,062 s para los **35 documentos
> juntos**, 2 ms/doc). **El extractor por reglas es gratis:** añadir formatos de EPS o endurecer
> heurísticas no cuesta rendimiento. Todo el presupuesto es el OCR, y el OCR escala con el **área
> rasterizada**, no con el peso del archivo (prueba: `REAL-07.pdf` pesa 12 KB —el más
> liviano del corpus— y es el más caro, 78,4 s de pared, porque su página mide 7152×10110 px a
> `PDF_RENDER_SCALE=3.0`). Modelo empírico ajustado: **CPU-s ≈ 2,2 + 1,4 × megapíxeles** hasta ~5 MP;
> por encima se vuelve sublineal (40 MP → 31 CPU-s).

### 2.2 Mes laboral y factor de pico (DECLARADOS, no escondidos)

- **Días hábiles/mes = 20.** Colombia: 365 − 104 fines de semana − 18 festivos = 243 hábiles/año =
  20,25/mes → se usa **20** (redondear hacia abajo es conservador: más carga por día).
- **Factor de pico = 2,5×.** Las incapacidades no llegan planas: el certificado llega cuando la
  persona vuelve. Se declara así:
  - **Lunes:** supuesto de que concentra el **35 % de la semana** (vs. 20 % si fuera uniforme entre 5
    días) → **1,75× el día medio**.
  - **Día siguiente a un puente:** Colombia tiene ~13-14 festivos en lunes (Ley Emiliani), así que el
    martes absorbe el fin de semana **+ el festivo** → **≈2,5× el día medio**. **Ese es el día de
    diseño.**
  - **Ráfaga excepcional** (BD o batch caídos 3 días, o carga de un atraso): **1 500 trámites en una
    corrida** — la misma cifra que usa `PLAN §6.6`, se conserva para poder comparar.
  - **Este factor es un supuesto, no una medición** (§7 S2). Se puede confirmar en una frase pidiendo
    a Gruppo el conteo de radicados por día de la semana de un mes cualquiera. Si el pico real fuera
    4× en vez de 2,5×, el día pico pasa de 2,3 a 3,7 CPU-h → **sigue cabiendo en la ventana**, así que
    el supuesto es sensible para el confort pero **no** para la decisión de compra.

### 2.3 Carga diaria resultante

| | Trámites | Docs OCR | Archivos que se mueven | CPU-h (8,53 CPU-s) | CPU-h (9,53 CPU-s) |
|---|---|---|---|---|---|
| Mes | 7 000 | 7 000 | 14 700 | **16,6** | **18,5** |
| Día hábil medio (÷20) | 350 | 350 | 735 | **0,83** | **0,93** |
| **Día PICO (×2,5)** | **875** | **875** | **1 838** | **2,07** | **2,32** |
| Ráfaga 1 500 | 1 500 | 1 500 | 3 150 | 3,55 | 3,97 |
| Backfill histórico de 12 meses | 84 000 | 84 000 | 176 400 | 199 | 222 |

Aritmética del día pico: `7000 / 20 × 2,5 = 875 docs` · `875 × 9,53 CPU-s = 8 339 CPU-s = 2,32 CPU-h`.

### 2.4 Workers para drenar en la ventana nocturna

**Ventana de diseño = 5 h (02:00 → 07:00).** El disparo es `INGESTA_CRON` (`docker-compose.yml:41`),
que **viene VACÍO por defecto** (`${INGESTA_CRON:-}` → scheduler desactivado); el ejemplo del README y
de `CLAUDE.md` es `"0 2 * * *"` con `BATCH_TZ=America/Bogota`. 07:00 es cuando el auxiliar empieza a
revisar la bandeja: todo lo de anoche tiene que estar ya en staging.

Throughput **lineal** (supuesto S7, **SIN MEDIR**), con 8,53 CPU-s/doc (cap 8 MP):

| Workers | docs/s | docs/h | Día pico (875) | Ráfaga (1 500) | Cabe en 5 h |
|---|---|---|---|---|---|
| **1 (lo que hay HOY: bucle serial)** | 0,117 | 422 | 124 min | 213 min | 2 110 docs |
| 2 | 0,234 | 844 | 62 min | 107 min | 4 220 docs |
| **4 (recomendado)** | 0,469 | **1 688** | **31 min** | **53 min** | **8 439 docs** |
| 6 | 0,703 | 2 532 | 21 min | 36 min | 12 659 docs |
| 8 | 0,938 | 3 376 | 16 min | 27 min | 16 879 docs |

**Con derateo prudente** (núcleo de servidor 1,5× más lento que un P-core en turbo × 0,75 de
eficiencia de escalado por contención de ancho de banda de memoria y L3 — ambos **supuestos**, S6/S7):

| Workers | docs/h derateado | Cabe en 5 h |
|---|---|---|
| 2 | 422 | 2 110 |
| **4** | **844** | **4 220** |
| 8 | 1 688 | 8 439 |

**Conclusión honesta: el volumen del cliente exige UN worker.** 875 docs del día pico ÷ 422 docs/h
derateados = 2,1 h < 5 h. **Se recomiendan 4** por cuatro razones concretas, ninguna de ellas
"por si acaso genérico":

1. **La dispersión medida es ×2,86.** El presupuesto de 1 worker (2,1 h de 5) se agota si el día
   resulta ser el peor de la distribución.
2. **La velocidad del núcleo del servidor es DESCONOCIDA** (§7 S6) y puede ser peor que el derateo de 1,5×.
3. **El backfill histórico** (199 CPU-h por año de histórico) con 1 worker son **8,3 días corridos**;
   con 4, **50 h**.
4. **Con 4 workers un fallo cabe en la ventana:** el drenaje termina a las 02:31 y quedan 4,5 h para
   reintentar sin invadir la jornada. Con 1 worker el drenaje del día pico ya invade las 04:00-06:00.

> **`INGESTA_WORKERS` no se puede fijar todavía.** Requiere las dos precondiciones del §0 **y** medir
> la escala real del pool de la Fase 2 (`PLAN §6.1`). Cómo medirlo: sembrar 200 documentos
> representativos, correr con `W = 1, 2, 4, 8` y graficar docs/s y RSS/worker; se acepta el W donde
> docs/s deja de crecer >15 % al doblar workers.

> **El extractor cambia el techo.** Con `INGESTA_EXTRACTOR=hibrido` (que **es el default de la UI**,
> aunque en `docker-compose.yml:43` el lote va bien puesto en `rule`) cada documento suma una
> inferencia de LLM: **20-40 s** según `CONTEXT §5.3` (junio 2026, **no re-verificado aquí**) → un
> worker haría **74-126 docs/h** y **la ventana de 5 h no cubriría el día pico con 1-2 workers**. Y con
> `ocr=ollama` (visión, obligatorio para permisos manuscritos según `CLAUDE.md`): **1-2 min/imagen y
> ~4 min/PDF en CPU** (`CONTEXT §5.2`) → **15-60 docs/h**. Si los permisos manuscritos son el 5 % del
> volumen (350/mes), a 4 min = **23 h de RELOJ al mes solo de visión** — más de lo que tarda todo el
> OCR de reglas del mes (18,5 CPU-h). Ojo: esas son **horas de reloj, no CPU-h**: Ollama en CPU usa
> varios núcleos, así que los CPU-h reales son un múltiplo de eso y **están SIN MEDIR**.

---

## 3. Perfiles de hardware

Reglas de reparto usadas en los tres:

- **RAM por worker = 1,6 GB** (pico RSS medido del peor documento con `OCR_MAX_PIXELS=8 MP`: 1 589 MB;
  p50 901 MB, p90 964 MB). **Con el default de 40 MP serían 7,6 GB/worker** (§4.2) y ningún perfil de
  esta tabla sirve. Corrige `PLAN §6.6`, que usa `floor(RAM_libre_GB / 1.0)`.
- **Núcleos = workers + 1 (uvicorn/UI) + 1 (MySQL si es local) + 1 (SO/Defender/backup)**. Corrige
  `PLAN §6.6`, que usa `cores − 1`.
- **Sobrecoste del SO del host** (la decisión "P2" del plan §5 sigue **PENDIENTE**): un host **Linux**
  con Docker Engine añade ~1-1,5 GB; un host **Windows Server con Docker Desktop/WSL2** añade la VM de
  WSL2 más el propio Windows, **~4-6 GB antes de levantar un contenedor**. La columna RAM da el valor
  para Linux y, entre paréntesis, el de Windows.
- **La lógica corre en contenedores Linux en los dos casos**; lo único que cambia es el arranque
  (`PLAN §5`) y el coste del bind mount (§5 B7).

| | **A — Mínimo viable** | **B — Recomendado** | **C — Con holgura para Ollama/manuscritos** |
|---|---|---|---|
| **Escenario** | solo RapidOCR + reglas, MySQL remoto (ASTGU real) | RapidOCR + reglas, MySQL local o remoto, UI en uso durante el drenaje | + híbrido/visión para permisos manuscritos y casos difíciles |
| **CPU** | **4 núcleos** físicos x86-64 uniformes, ≥2,4 GHz sostenido → **2 workers** | **8 núcleos** físicos uniformes, ≥2,6 GHz sostenido → **4 workers** | **16 núcleos** físicos → **8 workers** + 2 reservados para Ollama |
| **RAM** | **8 GB** (Linux) / **12 GB** (Windows Server) | **16 GB** (Linux) / **24 GB** (Windows Server) | **32 GB** (Linux) / **40 GB** (Windows Server) |
| | 2×1,6 + web 0,9 + SO 1,5 = 5,2 → 8 GB | 4×1,6 + web 0,9 + MySQL 4 + SO 1,5 = 12,8 → 16 GB | 8×1,6 + web 0,9 + MySQL 4 + Ollama 5 + SO 2 = 24,7 → 32 GB |
| **Disco** | **250 GB SSD** (NVMe o SATA) | **500 GB SSD NVMe** | **1 TB SSD NVMe** |
| | fijo 2,2 GB + 3 años de árbol (194 GB) | fijo 20 GB + 5 años (324 GB) + margen | fijo 20 GB + 5 años + 2 modelos + margen |
| **GPU** | **ninguna** | **ninguna** | **NVIDIA con ≥12 GB VRAM** (p.ej. RTX 4060 Ti 16 GB / L4) |
| **Cubre (lineal / derateado, ventana 5 h)** | 4 220 / **2 110 docs/noche** | 8 439 / **4 220 docs/noche** | 16 879 / **8 439 docs/noche** |
| **Vs. la necesidad** (con las cifras DERATEADAS) | día medio 350 ✅ (50 min, ×6,0 de margen) · día pico 875 ✅ (2,1 h, ×2,4) · ráfaga 1 500 ✅ (**3,6 h de 5**) | día pico ✅ (1,0 h, ×4,8) · ráfaga ✅ (**1,8 h**) · **el mes entero (7 000) cabe en una noche si escala lineal; derateado, el 60 % del mes** | día pico ✅ (31 min) · ráfaga ✅ (53 min) · el mes entero derateado ✅ |
| **NO cubre** | Ollama en ninguna forma (ni híbrido ni visión); backfill de 12 meses = **100 h ≈ 4,1 días**; la UI queda degradada durante el drenaje (§5 B3); MySQL local no cabe | Ollama en el hot path (híbrido en los 7 000 → **39-78 h de reloj/mes** solo de LLM); backfill 12 meses = **50 h** | nada del alcance conocido; el techo pasa a ser Ollama, **sin medir** |

### 3.1 Sobre la GPU — qué acelera y qué no

**La GPU NO acelera RapidOCR en este repo, y no es cuestión de drivers.** Verificado leyendo el
paquete instalado y el código:

- `rapidocr_onnxruntime/config.yaml` trae **`use_cuda: false`** en las tres secciones (`Det`/`Cls`/`Rec`).
- `ocr.py:96` construye **`RapidOCR()` sin kwargs** → nunca se pasa `det_use_cuda`/`rec_use_cuda`.
- `OrtInferSession.__init__` solo ofrece `CUDAExecutionProvider` (nada de DirectML/OpenVINO/ROCm), y
  `requirements.txt` instala `rapidocr-onnxruntime`, que trae el **onnxruntime de CPU**.
- Medido en la máquina de prueba: `onnxruntime 1.27.0` expone
  `['AzureExecutionProvider', 'CPUExecutionProvider']`. **La Iris Xe integrada está presente y no se usa
  ni se puede usar.**

Para que una GPU acelerara el OCR habría que: cambiar a `onnxruntime-gpu`, meter el runtime CUDA en la
imagen (`Dockerfile` pasa de ~1 GB a ~5 GB), pasar `use_cuda=True` y **medirlo**. No está hecho, no es el
cuello de botella a este volumen, y **no se recomienda** salvo que se decida usar visión en masa.

**La GPU sí aporta, y mucho, a Ollama** (LLM `gemma3:4b` y visión `qwen2.5vl:3b`): es la diferencia
entre ~4 min/PDF en CPU (`CONTEXT §5.2`) y segundos. VRAM necesaria: `gemma3:4b` ~3,3 GB +
`qwen2.5vl:3b` ~3,2 GB (tamaños del README, **estimados, sin verificar aquí**) + caché KV → **8 GB
carga uno a la vez, 12-16 GB deja los dos residentes**. **La aceleración concreta NO está medida**
(Ollama no está corriendo en esta máquina: solo el proceso de bandeja, 12 MB de RSS, sin modelo cargado).

### 3.2 Lo que ninguno de los tres perfiles arregla

Los perfiles compran **capacidad**, no **corrección**. Los cuellos de botella del §5 (B1 el tope de 500
casos, B3 el scheduler in-process, B4 la doble inserción sin ledger) **no se resuelven con hardware** y
son la Fase 2 del plan.

---

## 4. Disco — la aritmética completa

### 4.1 Tamaño real de un documento (MEDIDO)

`dataset-falsedad/docs`, 31 archivos, 29 únicos por sha256 (se colapsan 2 pares duplicados
`28c4a946` y `d86ae595` para no sesgar la media):

| | Valor |
|---|---|
| n archivos / únicos | 31 / **29** |
| Suma (únicos) | 11 425 022 B = **10,90 MB** |
| **Media (únicos)** | **384,7 KB** |
| Mediana (únicos) | 221,6 KB |
| min / max | 12,2 KB (`REAL-07.pdf`) / 1 788,0 KB (`REAL-05.pdf`) |
| Por extensión | 28 PDF (media 406,8 KB) · 3 JPEG (media 115,5 KB) |

Se dimensiona con la **media 384,7 KB** (la mediana subestimaría el total). **El corpus es casi todo
documentos BASE:** el único adjunto que contiene es `REAL-10.pdf` (202,2 KB, 2 páginas).
**Supuesto S5:** los adjuntos pesan lo mismo que un documento base. Una epicrisis escaneada de 5
páginas pesaría 2-3× más → ver sensibilidad en §4.3.

### 4.2 El árbol de ingesta

```
archivos/mes = 14 700  (§1.2)
GB/mes = 14 700 × 384,7 KB / 1 048 576 = 5,39 GB/mes
```

| Retención | Árbol de ingesta |
|---|---|
| **1 año** | **65 GB** |
| **3 años** | **194 GB** |
| **5 años** | **324 GB** |

**No se descuenta compresión.** `PLAN §4.1` prevé `_sistema/retencion/<yyyymm>.zip`, pero PDF y JPEG ya
vienen comprimidos: un zip de este corpus gana ~5-10 %, no la mitad. **Tampoco se descuenta dedup:**
hoy no existe (§5 B4) y `batch._destino_libre` guarda el reenvío como `_dupNN` a propósito, para no
perder un soporte en silencio.

### 4.3 Sensibilidad del disco (los dos supuestos que mandan)

| Escenario | GB/mes | 1 año | 3 años | **5 años** |
|---|---|---|---|---|
| **Base** (384,7 KB · 1,0 adjunto) | 5,39 | 65 | 194 | **324** |
| Si el promedio real es la mediana (221,6 KB) | 3,11 | 37 | 112 | **186** |
| **Si son 2 adjuntos/trámite** (22 050 archivos/mes) | 8,09 | 97 | 291 | **485** |
| Si además los adjuntos pesan 2× (770 KB medio) | 10,79 | 130 | 389 | **648** |

**Rango a 5 años: 186 – 648 GB.** Los dos supuestos que mueven el resultado son S4 (adjuntos/trámite) y
S5 (peso del adjunto), y **los dos se confirman con una frase**: «¿cuántos documentos trae en promedio
un trámite y cuánto pesa una epicrisis escaneada?».

### 4.4 Imágenes Docker y modelos (ESTIMADO — Docker no está corriendo en esta máquina)

Docker no se puede levantar aquí (requiere elevación UAC que la sesión no tiene), así que estas cifras
se **deducen del `Dockerfile`/`docker-compose.yml`** y se marcan como estimadas.

| Componente | Tamaño | Origen |
|---|---|---|
| Imagen `incapacidad-ocr` | **0,7 – 1,2 GB** (usar **1,5 GB**) | **medido**: `site-packages` del venv = **430 MB** (cv2 109 · pymupdf 54 · onnxruntime 44 · mysql 43 · numpy 55 · PIL 16 · rapidocr 14) + `python:3.12-slim` ~130 MB + `libgl1`+`libglib2.0-0`+`libgomp1` ~60-120 MB. El README dice 1,1 GB → compatible |
| Imagen `mysql:8` | **~0,7 GB** | estimado. **El README lo OMITE** aunque `docker-compose.yml` siempre levanta el servicio `db` |
| Imagen `ollama/ollama:latest` | **~8,5 GB** | README (estimado, sin verificar) |
| Modelo `gemma3:4b` | **~3,3 GB** | README (estimado) |
| Modelo `qwen2.5vl:3b` | **~3,2 GB** | README (estimado); necesario para permisos manuscritos |
| Volumen `db-data` inicial | **~0,5 GB** | estimado (datadir de MySQL 8 recién inicializado + redo) |
| Caché de capas y builds de Docker | **~10 GB** | estimado; cada `up --build` deja capas huérfanas |
| **Fijo sin Ollama** | **~2,2 GB** (+10 caché) | |
| **Fijo con Ollama y los 2 modelos** | **~20,2 GB** (+10 caché) | |

> **Corrección al README** (`Requisitos mínimos`): la fila «Disco ~1,5 GB / ~13 GB» (a) **omite
> `mysql:8`**, que compose siempre levanta; (b) omite `qwen2.5vl:3b`, que `CLAUDE.md` declara
> **obligatorio** para permisos manuscritos → con los dos modelos son **~19,5 GB, no 13**; y (c) mide
> solo la **instalación**, no la operación: el driver real del disco es el árbol de ingesta,
> **65 GB/año**, que la tabla no menciona.

### 4.5 La BD MySQL — medida sobre el DDL real

Tamaño de fila de `lp_ausentismos_ia` **medido**, no estimado: se procesaron 5 documentos del corpus con
`IncapacidadProcessor` + `erp.mapear_a_staging` (con `LookupsNulos`, sin BD) y se midieron los bytes
UTF-8 de cada columna contra el DDL de `sql/init.sql`.

| | Bytes |
|---|---|
| Columnas de ancho FIJO (20 columnas: 11 INT, 5 DATE, 2 TINYINT, 1 DECIMAL(4,3), 1 TIMESTAMP = 44+15+2+2+4) | **67** |
| Columnas VARCHAR/TEXT (media medida de 5 filas) | **340** |
| **Total de datos por fila** | **media 407 · mediana 394 · rango 365-472** |

Reparto de la parte variable (media de 5 filas, bytes): `problemas` 148 · `observaciones` 54 ·
`archivo_origen` 30 · `paciente_leido` 24 · `estado` 18 · `eps_leida` 13 · `extractor` 10 ·
`ocr_backend` 8 · `documentacion_estado` 8 · `cedula_leida` 8 · `codigo_diagnostico_leido` 4.

`problemas` sale inflado porque sin BD **todos** los lookups fallan; con el catálogo ASTGU real será
más corto en los casos resueltos → **407 B es una cota superior**, y a la vez `documentos_faltantes` /
`alertas_tiempos` / `motivo_sospecha` salieron vacías en estas 5 filas y en producción se llenarán a
veces. Se dimensiona con **0,6 KB/fila asignados** (407 B de datos + ~20 B de cabecera InnoDB +
trx_id/roll_ptr, ÷0,9375 de relleno de página, + los dos índices secundarios `idx_ia_estado` e
`idx_ia_empleado`).

`lp_alertas_documentacion`: ~215 B de datos (`mensaje` VARCHAR(500) es la columna gorda; los mensajes
que arma `batch._alerta` rondan 110 B) → **0,35 KB/fila asignados**. Se supone **1 alerta por trámite**
en promedio (hay dos generadores: `PENDIENTE` por soportes faltantes y `PENDIENTE_RADICACION` por el
checklist de la EPS, y este último se dispara a menudo).

```
7 000 × 0,60 KB = 4,10 MB/mes  (staging)
7 000 × 0,35 KB = 2,39 MB/mes  (alertas)
                = 6,49 MB/mes
```

| | Total BD |
|---|---|
| 1 año | **78 MB** |
| 3 años | **234 MB** |
| 5 años | **390 MB** |

**La BD NO es un factor de dimensionamiento.** 390 MB a 5 años es ruido frente a 324 GB de árbol. Los
catálogos (`vlpempleados`, `lpdiagnosticos`, `lpentidades`) son del ERP y ya existen; nosotros solo
añadimos dos tablas. Lo único que crecería de verdad es el **binlog** si está activo (≈ el doble de lo
escrito, aún en MB) y las tablas de la **Fase 0** del plan (`lp_ingesta_documentos` con 1 fila por
archivo = 14 700 filas/mes × ~0,3 KB ≈ 4,4 MB/mes; **no medido, la tabla no existe todavía**).

### 4.6 Totales de disco

| | Sin Ollama (perfil A) | Con Ollama y 2 modelos (perfiles B/C) |
|---|---|---|
| Fijo (imágenes + modelos + datadir + caché) | 12,2 GB | 30,2 GB |
| **1 año** (árbol 65 + BD 0,08 + logs 0,07) | **77 GB** | **95 GB** |
| **3 años** (árbol 194 + BD 0,23) | **206 GB** | **224 GB** |
| **5 años** (árbol 324 + BD 0,39) | **337 GB** | **355 GB** |
| **Disco a provisionar** (≥30 % libre; un FS lleno rompe `os.replace`) | **250 GB** (3 años) / **500 GB** (5 años) | **500 GB** (5 años) |

**Logs:** `_sistema/logs/ingesta-YYYYMMDD.ndjson` (aún no implementado, Fase 2), 1 línea JSON por
archivo ≈ 400 B → 14 700 × 400 B = **5,9 MB/mes = 71 MB/año**. Despreciable. **Calculado, no medido.**

**Backup:** el árbol de ingesta contiene los **originales** y `PLAN §9.4` dice que la retención legal
«nunca borra la única copia del original» → **hay que respaldarlo**, y el respaldo duplica la cifra
donde caiga. Su coste no es en GB sino en **número de ficheros**: **176 400 ficheros/año, ~882 000 a los
5 años**, repartidos en el árbol `3_archivo/<Persona>/AAAA/MM/DD` (el número de directorios hoja =
personas distintas × días, y la plantilla de Gruppo es desconocida — §5 B8). Un backup incremental
fichero a fichero sobre eso es lento; un snapshot a nivel de volumen no. **No medido.**

### 4.7 Retención — es una pregunta jurídica, no técnica

**Se dimensiona a 5 años** por la ventana de fiscalización de la UGPP en aportes parafiscales.
`PLAN §9.4` reconoce explícitamente que el plazo está **«a confirmar con jurídico»**, y hay al menos
tres plazos en tensión que apuntan a números muy distintos: los soportes de nómina, la retención de
historia clínica (mucho más larga) y la prescripción del cobro del ausentismo a la EPS (mucho más
corta). **Hasta que jurídico lo fije, la cifra de 5 años (324 GB de árbol) es un supuesto de
ingeniería, no un requisito.** Es la variable que decide entre un disco de 250 GB y uno de 1 TB.

---

## 5. Cuellos de botella reales del diseño ACTUAL (leídos en el código)

Ordenados por «a qué volumen se rompe». Nótese que **los tres primeros se rompen por configuración o
por probabilidad, no por volumen** — y ese es el hallazgo importante: el sistema no se cae por falta de
CPU.

### B1 — `procesar_todo(limite=500)`: tope duro de 500 casos por corrida

`batch.py:344` y `batch.py:376-378`:

```python
def procesar_todo(ocr_backend, extractor_name="rule", limite: int = 500, dry_run=False):
    ...
    for i, (caso, archivos) in enumerate(casos.items()):
        if i >= limite:
            break
```

`webapp._correr_lote` (`webapp.py:63`) llama `batch.procesar_todo(_get_rapidocr(), extractor_name=extractor)`
**sin pasar `limite`** → el tope efectivo es 500, y **no hay variable de entorno para cambiarlo**.

- **Se rompe a:** >500 casos en una corrida. Día medio 350 ✅. **Día pico 875 ✗** — se drenan 500 y
  **375 se quedan en `1_entrada/`** para la noche siguiente.
- **Se autocura** mientras las llegadas queden por debajo de 500/día (la noche siguiente arrastra el
  resto). **Deja de autocurarse** si las llegadas sostenidas superan 500 casos/día = **10 000/mes**, o
  si el cron pasa a semanal, o si nadie se da cuenta de que hay backlog (no hay alerta de cola).
- **Es lo primero que se rompe, y se rompe a 1,4× del factor de pico que asumí.** Arreglo: exponer
  `limite` por env y ponerlo ≥3× el día pico.

### B2 — El OCR es serial: HOY no hay pool, es un `for` de un solo proceso

`batch.procesar_todo` es un bucle plano; `IncapacidadProcessor(...).run()` se llama documento a
documento. El pool de procesos del `PLAN §6.1` es **Fase 2, no existe**.

- **Capacidad de hoy:** 1 proceso. Con el cap de hilos → 422 docs/h → **2 110 docs por ventana de 5 h**.
  **Sí cubre el día pico (875)**, y eso es una buena noticia que conviene decir en claro.
- **Matiz medido, y no es menor:** hoy, **sin** el cap de hilos, ese mismo proceso serial va **más
  rápido en tiempo de pared** — media medida **7,23 s/doc** (34 docs base, `bench_multihilo.json`) =
  **498 docs/h** — pero **consumiendo 59,86 CPU-s por documento (8,3 núcleos de media)**. Es decir: el
  lote **monopoliza la máquina entera** aunque procese de a uno, y esos 498 docs/h **no se pueden
  multiplicar por workers** porque ya no queda CPU libre. En un servidor de 4 núcleos esa cifra caerá
  hacia la del cap (422 docs/h), porque los 60 CPU-s ya no caben en 7 s.
- **Se rompe a:** ~2 100 docs en una corrida = 6× el día medio, 2,4× el día pico. Es decir, a un
  volumen sostenido de ~42 000 docs/mes, o a la primera ráfaga >2 100.
- **Se rompe MUCHO antes con Ollama.** `hibrido` = OCR (8,5 s) + 1 inferencia de LLM (20-40 s,
  `CONTEXT §5.3`, **no re-verificado**) = 28,5-48,5 s/doc → **74-126 docs/h** → la ventana de 5 h da
  **371-632 docs**, **por debajo del día pico de 875**. `docker-compose.yml:43` pone bien
  `INGESTA_EXTRACTOR=rule`, pero la UI ofrece «Híbrido» como default y `POST /api/lote/procesar` acepta
  `{"extractor":"hibrido"}`: **un auxiliar puede convertir el drenaje nocturno en uno de 10 h con un
  clic**. Con `ocr=ollama` (visión) es peor: **15-60 docs/h** (~4 min/PDF → 15/h; 1-2 min/imagen →
  30-60/h, `CONTEXT §5.2`).

### B3 — Scheduler in-process, `threading.Lock`, y el drenaje dentro de la petición HTTP

`webapp.py:53-65` y `webapp.py:150-163`: `BackgroundScheduler` de APScheduler **dentro del proceso de
uvicorn**, con `_lote_lock = threading.Lock()` compartido por la corrida manual y la programada. El
`CMD` del `Dockerfile` no pasa `--workers`, así que hay **1 worker de uvicorn** y el lock funciona.

Tres roturas distintas:

1. **El lock solo vale dentro de un proceso.** Se rompe **el día que alguien añada `--workers N`, una
   segunda réplica o el servicio `ocr-worker` del plan**: N schedulers, N locks, N drenajes sobre la
   misma carpeta, el mismo archivo reclamado dos veces. **No es un umbral de volumen: es un cambio de
   configuración.** `CLAUDE.md` ya lo declara MVP y apunta a `GET_LOCK` en BD (`PLAN §9.5`).
2. **`POST /api/lote/procesar` ejecuta el drenaje SÍNCRONO dentro de la petición** (`webapp.py:502`).
   Un drenaje de 875 documentos dura ~2 h con 1 worker → **una petición HTTP de 2 h**. Cualquier
   proxy/navegador/timeout de uvicorn corta la conexión y el auxiliar no recibe el resumen (el drenaje
   sigue en el threadpool, a ciegas). **Se rompe a:** un drenaje más largo que el timeout del cliente,
   ≈ **300-600 documentos** con los timeouts típicos de un proxy corporativo. `PLAN §5.2` ya especifica
   la solución (encolar y responder **202**); no está implementada.
3. **El drenaje y la UI comparten el singleton `_rapidocr_backend`** (`webapp.py:135-142`). Durante las
   2 h de drenaje, el auxiliar que suba un documento por la UI usa **la misma instancia de RapidOCR** de
   forma concurrente, y ambos compiten por la CPU con hilos ONNX sin capar (medido: 8,67 núcleos por
   documento). La latencia interactiva se vuelve impredecible. La seguridad ante hilos de
   `rapidocr-onnxruntime` **no está documentada ni probada**; leyendo `text_recognize.py` el estado
   por llamada parece local, así que probablemente funcione, pero **no se verificó**.

### B4 — Sin ledger ni dedup: la doble inserción es una certeza estadística, no un caso raro

`db.insertar_staging` hace **`cx.commit()` por fila** (`db.py:62`), y el movimiento del archivo ocurre
**después** (`batch.py:302` → `batch.py:338-339`). Y `_mover` **se traga la excepción**
(`batch.py:210-211`):

```python
except Exception:  # noqa: BLE001 — un fallo de move no debe tumbar el lote
    log.exception("No se pudo mover %s", f.name)
```

→ Si el INSERT commitea y el move falla, **el archivo se queda en `1_entrada/` con la fila ya insertada**,
y la corrida siguiente **inserta una segunda fila** para el mismo documento. No hay `UNIQUE (caso_id, hash)`,
no hay dedup semántica, no hay ledger (todo eso es Fase 0/2 del plan). El auxiliar ve dos pendientes
idénticos y, si aprueba los dos, el ERP promueve **dos ausentismos** para la misma persona.

- **Causas reales del fallo de move:** `WinError 32` de Defender/indexador/backup (`PLAN §11` riesgo 8),
  `MAX_PATH` en el host Windows (§B6), disco lleno, permisos del bind mount.
- **Se rompe a:** no hay umbral de volumen — es una **probabilidad por archivo**. A 14 700 archivos/mes,
  una tasa de fallo de move del **0,1 % son ~15 casos duplicados al mes**. Y hay una segunda vía
  garantizada: `restart: unless-stopped` + un reinicio del contenedor a mitad del drenaje (actualización
  de Windows, reinicio de Docker) deja el caso en vuelo insertado y su archivo en su sitio.
- La afirmación de `CLAUDE.md` («reprocesar es seguro **solo porque** los archivos se mueven fuera de
  `1_entrada/` al terminar») **es exactamente la que se cae** cuando el move falla en silencio.

### B5 — Una sola conexión MySQL sostenida durante todo el drenaje, sin keepalive ni statement-timeout

`batch.py:374`: `with db.conexion_mysql() as cx:` envuelve **el bucle completo**, y `erp.Lookups(cx)` se
construye **una vez**. `db.crear_conexion` pasa `connection_timeout=5` — que es el timeout de **conexión**,
no de sentencia — y **no** fija `MAX_EXECUTION_TIME` ni reconecta (`PLAN §8.2` lo pide; no está hecho).

- Un drenaje de 2 h con un INSERT cada ~10 s no dispara `wait_timeout`, pero **cualquier reinicio o
  failover de la BD ASTGU a mitad del drenaje mata el socket**. A partir de ahí, cada caso restante
  entra al `except` genérico de `procesar_todo` (`batch.py:393-398`) → `con_error += 1` y
  **`_mover(... 2_revisar/con_error/<caso>)`**: **cientos de archivos se mudan al bucket de error** por
  un fallo de red de 3 segundos, y hay que sacarlos a mano.
- **Se rompe a:** cualquier interrupción de BD durante el drenaje. La probabilidad crece linealmente con
  la duración del drenaje → **crece con el volumen**.
- Nota menor: `docker-compose.yml:68` pinza `mysql:8`, una etiqueta flotante. `PLAN §1` diseña el claim
  sobre **MySQL 8.4** (`SKIP LOCKED`, `GET_LOCK`). Conviene pinzar la versión exacta: un salto de minor
  silencioso cambia defaults de `wait_timeout`/redo bajo un diseño que depende de ellos.

### B6 — Pico de RAM de UNA página, y ningún límite de memoria en compose

- Medido: **2 de 31** documentos reales piden **7 648 MB** y **6 810 MB** de pico de RSS, por tener la
  caja de página sobredimensionada (**86,5 MP** y **72,3 MP** al rasterizar a `PDF_RENDER_SCALE=3.0`;
  bitmaps RGBA de 346 y 289 MB antes de `_cap_pixels`). Los otros 33 se quedan en **≤971 MB**.
- **`OCR_MAX_PIXELS=40 MP` NO protege nada.** RapidOCR usa `limit_type: min` con `limit_side_len: 736`
  (verificado en `rapidocr_onnxruntime/config.yaml:16-17`): si `min(h,w) ≥ 736`, `ratio = 1.0` y el
  detector DB recibe la página **sin reescalar**. Un tensor de 40 MP × 3 canales × 4 bytes = **480 MB**,
  más los mapas de activación → varios GB. **Un guardarraíl cuyo default no guarda.**
- **`docker-compose.yml` no fija `mem_limit` ni `deploy.resources.limits`** para ningún servicio. Un
  documento de 7,6 GB en un host de 8 GB no falla limpio: el OOM killer de Linux elige el proceso más
  gordo, que puede ser **MySQL** o el propio uvicorn — se cae la UI y la bandeja, no solo el documento.
- **Se rompe a:** **1 documento**. Con una incidencia medida de 2/31 = **6,5 %**, a 7 000 trámites/mes son
  **~450 documentos al mes** que pedirían 7,6 GB cada uno. **No es la cola, es la rutina.**
- Arreglo medido: `OCR_MAX_PIXELS=8000000` → 7 648→1 555 MB y 6 810→1 589 MB (÷4,4 a ÷4,9), con
  31,2→15,3 y 31,4→13,3 CPU-s (÷2,0 a ÷2,4) y **los documentos normales de 4,4 MP intactos**. Falta
  **re-validar exactitud** (§7 S8). Añadir además `mem_limit` para que un pico sea un reinicio visible
  del contenedor, no una caída silenciosa de MySQL.
- `PLAN §6.8` atribuye este riesgo a «un bundle grande materializado entero» y lo resuelve con streaming.
  **El streaming ya está** (`preprocess.load_pages` es un generador) y **no ayuda**: el pico lo produce
  **UNA SOLA página**.

### B7 — El escaneo de `1_entrada/` sobre el bind mount (el punto donde la decisión Windows-vs-Linux se ve)

`batch._archivos_entrada` hace `sorted(base.rglob("*"))` sobre todo el árbol de entrada, y
`contar_pendientes` (que la UI llama en `GET /api/lote/pendientes`) **repite el mismo recorrido completo**.

- A 1 838 archivos del día pico esto es irrelevante. El punto es **de qué depende**: en Docker Desktop
  para Windows el bind mount va por **gRPC-FUSE**, notoriamente más lento por operación que un bind
  mount nativo de Linux. **NO SE MIDIÓ** (Docker no está corriendo aquí).
- **Cota de indiferencia calculada:** el día pico son 2,32 CPU-h de OCR sobre 1 838 archivos → el
  sistema de ficheros tendría que costar **>4,5 s por archivo** para duplicar la duración del drenaje.
  Ninguna sobrecarga plausible de FS está en ese orden, así que **se espera que sea despreciable —
  pero es una EXPECTATIVA aritmética, no una medición.**
- **Cómo medirlo** (10 minutos, cuando haya servidor): dentro del contenedor, cronometrar
  `sum(1 for _ in Path('/data/ingesta/1_entrada').rglob('*'))` y un `open().read()` de 200 archivos, en
  el bind mount y en un `tmpfs`; el cociente es el sobrecoste. Repetir en los dos SO candidatos.

### B8 — `MAX_PATH` y número de directorios en el host Windows

`3_archivo/<Nombre persona>/<AAAA>/<MM>/<DD>/<cedula>_TIPODOC.ext`. `_sanit_carpeta` permite **60
caracteres** de nombre de persona (`batch.py:160`) y el nombre de archivo se **conserva** tal cual
(decisión 2026-09-01), con casos reales de 57 caracteres (`INC <NOMBRE> DE LA HOZ <NOMBRE> <NOMBRE> 3
DIAS 02.09.2025.pdf`).

- `C:\ruta\del\host\ingesta\3_archivo\` (≈40) + 60 + `\2026\09\02\` (11) + 57 = **~168 caracteres**, y
  crece con la profundidad de `INGESTA_HOST_ROOT`. **El contenedor (Linux) escribe sin problema**; el
  que no lee es **Explorer / el antivirus / el backup del host Windows** sin `LongPathsEnabled`.
  `PLAN §11` riesgo 19 lo anticipa; el runbook de Fase 3 lo incluye. **Se rompe por longitud de nombre,
  no por volumen.**
- **Recuento de directorios:** ~1 hoja por **persona-día**. La plantilla de Gruppo es **DESCONOCIDA**, así
  que esto es una cota, no un dato: si de los 7 000 trámites/mes salen `P` personas distintas, el árbol
  gana ~`P` directorios hoja al mes (con `P = 3 000` serían ~36 000/año y ~180 000 a 5 años). NTFS lo
  soporta; un escaneo completo de antivirus o un backup fichero-a-fichero, no con gracia. Se recomienda
  **excluir `INGESTA_ROOT` del escaneo en tiempo real** (`PLAN §9.2` ya lo dice) y respaldar por snapshot
  de volumen, no por fichero. **Pregunta de una frase: «¿cuántos empleados distintos generan esos 7 000
  trámites al mes?»**

### B9 — `INGESTA_REAPER_TTL` (Fase 2): el suelo lo fija el bundle multipágina

`RapidOCRBackend.read_text` (`ocr.py:107-111`) hace `[self._ocr_one(page) for page in pages]` y
`_combinar_paginas` filtra por `es_pagina_relevante` **DESPUÉS**: **un PDF multipágina paga TODAS sus
páginas** aunque solo una traiga la incapacidad. Medido: los 4 PDF de 2 páginas costaron ~2× uno de 1
página (sin economía de escala, p50 10,9 s/página).

- **Extrapolado (calculado, no medido — el corpus no tiene ni un bundle profundo):** un bundle de 30
  páginas (`MAX_PDF_PAGES=30`) ≈ **258 CPU-s ≈ 4,3 min** con 1 hilo.
- `PLAN §6.4/§9.3` define `INGESTA_REAPER_TTL > peor_caso + timeout_ollama + margen`. **Un TTL calculado
  sobre «el peor documento medido» (31 CPU-s) reencolaría un bundle legítimo a mitad de proceso** →
  doble inserción (`PLAN §11` riesgo 2). **El TTL debe superar ~5 min con `rule`, y ~20 min si el
  documento puede escalar a Ollama** (`OLLAMA_TIMEOUT=900` = 15 min, `docker-compose.yml:25`).

---

## 6. Correcciones a los documentos del repo

| # | Documento | Dice | Corrección (con su evidencia) |
|---|---|---|---|
| 1 | `PLAN §6.6` | «~2-4 s/doc/core»; «8 cores → 6 workers → ~1,5-2 docs/s → ~6-7k docs/hora»; «7000/mes en ~1 h; ráfaga de 1500 en ~12-15 min» | **~3× optimista.** Medido 9,53 CPU-s/doc (media, 34 docs base) → 6 workers = **0,63 docs/s = 2 266 docs/h**; 7 000/mes = **3,1 h**; ráfaga 1 500 = **40 min**. Con el cap de 8 MP: 2 532 docs/h y 2,8 h. La fila de 16 cores/12 workers («3-4 docs/s») medida da **1,26-1,41 docs/s**, también ~3× off. **La CONCLUSIÓN del plan se sostiene; sus NÚMEROS no.** |
| 2 | `PLAN §6.6` | `W = min(cores − 1, floor(RAM_libre_GB / 1.0))` | **Los dos términos.** `cores − 1` no reserva para uvicorn + MySQL local + SO → **`cores − 2` (o −3 con MySQL y Ollama locales)**. `RAM/1.0` coincide con el p50/p90 medido (901/964 MB) pero **ignora la cola**: con el default de 40 MP el peor documento pide **7,6 GB**, y con el cap de 8 MP son **1,6 GB** → **`RAM_libre_GB / 1.6`**. |
| 3 | `PLAN §6.8` | El pico de RAM lo causa «un bundle grande materializado entero» y se resuelve con **streaming** | **El streaming YA está** (`preprocess.load_pages` es generador) y **no ayuda**: el pico lo produce **UNA SOLA página** (86,5 MP → 7,6 GB medidos). La causa es `OCR_MAX_PIXELS` + `limit_type:'min'` de RapidOCR, no la materialización del bundle. |
| 4 | `PLAN §6.2` | Cap de hilos ONNX a 1 por worker | **Correcto como decisión, NO implementado.** `OMP_NUM_THREADS` **no lo consigue**: `OrtInferSession` construye `SessionOptions()` sin tocar `intra_op_num_threads` y onnxruntime 1.27 CPU usa su propio pool, no OpenMP. Medido sin cap: 8,67 núcleos por documento para 1,7× de velocidad (~20 % de eficiencia, 6,4× más CPU). **Lado bueno:** como un documento no aprovecha más de ~1 núcleo eficientemente, añadir workers **sí** debería escalar casi linealmente. |
| 5 | `README` §Requisitos | «RAM mínimo **4 GB** (solo RapidOCR)» | **FALSO con los defaults actuales.** Un documento real del cliente pide **7 648 MB**; hasta uno normal llega a 971 MB. Correcto: **8 GB mínimo**, o 4 GB **solo si** `OCR_MAX_PIXELS≈8000000` (medido: peor caso 1 589 MB). |
| 6 | `README` §Seguridad | «cada página se acota a `OCR_MAX_PIXELS` (40 MP) para no disparar la RAM en escaneos enormes» | Describe un guardarraíl que **con su default NO guarda** (ver #3 y §5 B6). Con 40 MP el detector recibe la página sin reescalar. |
| 7 | `README` §Requisitos | «Disco ~1,5 GB / ~13 GB (web 1,1 + Ollama 8,3 + modelo 3,3)» | **Omite `mysql:8`** (~0,7 GB, y compose siempre levanta el servicio `db`) y **omite `qwen2.5vl:3b`** (~3,2 GB, que `CLAUDE.md` declara obligatorio para permisos manuscritos) → con los dos modelos son **~19,5 GB**. Y mide solo la instalación: **el driver real es el árbol de ingesta, 65 GB/año**. |
| 8 | `README` §Requisitos | «GPU: No requerida (corre en CPU)» / «Opcional; acelera mucho el LLM/visión» | Correcto para Ollama, **incompleto para RapidOCR**: en este repo una GPU **no puede** acelerar el OCR sin cambios de código e imagen (`config.yaml: use_cuda: false` ×3, `RapidOCR()` sin kwargs en `ocr.py:96`, `requirements.txt` instala el onnxruntime de **CPU**, y `OrtInferSession` solo contempla `CUDAExecutionProvider`). Conviene decirlo para que nadie compre una GPU esperando OCR más rápido. |
| 9 | `CONTEXT §9` fila 3 | «`MAX_PDF_PAGES=20`; `Image.MAX_IMAGE_PIXELS=64M`» | **Desactualizado.** El código usa **30** y **200 000 000** (`preprocess.py:25,32`). El README sí está correcto. |
| 10 | `CONTEXT §5.2` | «i7-1255U, **sin GPU** → inferencia CPU» | La máquina **SÍ tiene GPU** (Iris Xe integrada). Lo correcto: **no se aprovecha**, porque onnxruntime solo expone `['AzureExecutionProvider','CPUExecutionProvider']`. |
| 11 | `preprocess.py:28` (comentario) | «40 MP deja pasar intactos los documentos normales (**una A4 a escala 3.0 ≈ 8,7 MP**)» | **Está 2× mal.** `PDF_RENDER_SCALE=3.0` en PDFium = 3 × 72 = **216 DPI** → A4 (8,268 × 11,693 in) = 1 786 × 2 526 px = **4,51 MP**, que es exactamente lo medido en el corpus (4,4-4,5 MP en 30 de 35 documentos). Los 8,7 MP corresponden a **300 DPI**, no a escala 3.0. La conclusión del comentario no cambia, pero el número sí. |
| 12 | `CLAUDE.md` §Gotchas | «reprocesar es seguro **solo porque** los archivos se mueven fuera de `1_entrada/` al terminar» | Verdadero como enunciado, y **es justo el que se cae**: `_mover` se traga la excepción (`batch.py:210`) **después** de que `insertar_staging` ya hizo `commit()` (`db.py:62`) → archivo que no se mueve = **doble inserción** en la corrida siguiente (§5 B4). |
| 13 | `PLAN §6.6` | «El benchmark inicial (100 docs representativos + bundles multipágina reales)…» | El corpus disponible **no tiene ni un bundle profundo**: los 31 documentos de `dataset-falsedad/docs` incluyen multipágina, pero **todos los multipágina son de exactamente 2 páginas**. La cifra de 258 CPU-s / 4,3 min para 30 páginas es una **extrapolación por página**, y es precisamente la que fija el `INGESTA_REAPER_TTL`. |

---

## 7. Supuestos — uno por uno, cada uno confirmable en una frase

| # | Supuesto | Valor usado | ¿Qué cambia si es distinto? | Pregunta para el cliente |
|---|---|---|---|---|
| **S1** | «7 000 incapacidades/mes» = **7 000 trámites**, no 7 000 ficheros | 7 000 trámites | Si fueran 7 000 **ficheros**, los trámites bajan a ~3 500 y **toda la CPU se parte por 2** | «¿Los 7 000 son casos o archivos?» |
| **S2** | Factor de pico del día siguiente a un puente | **2,5×** el día hábil medio | 4× → día pico 3,7 CPU-h; **sigue cabiendo en la ventana**. Sensible al confort, **no** a la compra | «¿Nos pasas el conteo de radicados por día de la semana de un mes?» |
| **S3** | Días hábiles/mes | **20** | 22 → −9 % por día. Irrelevante | — (dato de calendario) |
| **S4** | Adjuntos por trámite | **1,0** (+5 % reenvíos) | **2 adjuntos → disco a 5 años 324→485 GB.** **El supuesto más sensible del documento.** CPU **no cambia** (los adjuntos no se OCR-ean) | «¿Cuántos documentos trae en promedio un trámite además de la incapacidad?» |
| **S5** | Peso medio de un archivo | **384,7 KB** (medido, 29 únicos) | Mediana (221,6) → 5 años 186 GB. Adjuntos 2× más pesados → 648 GB | «¿Cuánto pesa una epicrisis escaneada típica?» |
| **S6** | Un núcleo del servidor es **1,5× más lento** que el P-core medido | ÷1,5 | 3× más lento → día pico 6,9 CPU-h con 1 worker; con 4 workers sigue cabiendo | Se resuelve **midiendo en el servidor**, no preguntando |
| **S7** | El pool escala **lineal** (derateo 0,75) | ×0,75 | Si escalara al 0,4 (contención de ancho de banda), 4 workers = 2 workers efectivos. **Sigue cubriendo el día pico** | **SIN MEDIR.** Método en §2.4 |
| **S8** | `OCR_MAX_PIXELS=8 MP` **no degrada la exactitud** | asumido | Si degrada, hay que volver a 40 MP → **RAM/worker 1,6→7,6 GB** y los perfiles A y B **dejan de servir** | **SIN MEDIR y es una precondición.** Método: re-correr `tests/test_ejemplos_reales.py` + el ground-truth de `dataset-falsedad` con los dos caps y comparar campo a campo |
| **S9** | Retención legal | **5 años** | 3 años → 194 GB; 15 años (historia clínica) → 971 GB | «Jurídico: ¿cuántos años hay que conservar el original del soporte?» (`PLAN §9.4` ya lo deja abierto) |
| **S10** | Ventana nocturna | **5 h (02:00-07:00)** | 2 h → 4 workers siguen cubriendo el día pico (31 min). 0 h (tiempo real) → cambia el diseño entero | «¿A qué hora empieza a revisar el auxiliar?» |
| **S11** | El lote corre con `extractor=rule` | `rule` | `hibrido` en los 7 000 → +39-78 h/mes de LLM en CPU → **hace falta el perfil C con GPU** | «¿Se acepta que el lote use solo reglas y el auxiliar suba a IA los casos difíciles a mano?» |
| **S12** | 1 alerta de `lp_alertas_documentacion` por trámite | 1,0 | 2 → BD 6,5→8,9 MB/mes. Irrelevante | — |
| **S13** | Tamaño de fila de staging **0,6 KB asignados** | 407 B de datos medidos + overhead InnoDB | ×2 → 780 MB a 5 años. Irrelevante | — |
| **S14** | Mezcla de tipos de ausentismo (88 % enf. general…) | §1.2 | Solo afecta a S4 | «¿Nos pasas el reparto por tipo de un mes de `lpausentismos`?» |
| **S15** | Los tamaños de imágenes Docker del README | 1,1 / 8,3 / 3,3 / 3,2 GB | ±50 % → ±10 GB en el fijo. Irrelevante frente a 324 GB de árbol | **ESTIMADO, sin verificar** (Docker no arranca en esta máquina) |

---

## 8. Lo que sigue SIN MEDIR (y cómo medirlo en el servidor definitivo)

1. **Paralelismo real del pool.** Todo se midió con **un solo proceso, serialmente**. Las sesiones ONNX
   compiten por ancho de banda de memoria y caché L3, y el pico de RAM se **multiplica por worker**.
   → Sembrar 200 documentos, correr `W = 1,2,4,8`, graficar docs/s y RSS/worker.
2. **Ollama (visión y LLM).** No está corriendo aquí y no se puede levantar. Los únicos números que
   existen son de `CONTEXT §5.2/§5.3` (junio 2026): ~20-40 s el híbrido, 1-2 min/imagen y ~4 min/PDF la
   visión en CPU. **No re-verificados.** → Medir con el modelo cargado, en CPU y en GPU.
3. **Latencia de MySQL.** No hay BD levantada. Quedan fuera los lookups (cédula→`idlpempleado`,
   CIE-10→`idlpdiagnosticos`, EPS→`idlpentidad`), el INSERT en staging, la alerta y —en Fase 2— el claim
   con `SELECT … FOR UPDATE SKIP LOCKED` y el `GET_LOCK` por caso. Con la BD en el mismo host serán
   milisegundos frente a ~10 s de OCR (irrelevante); con **ASTGU remota y N workers golpeando la misma
   tabla**, puede dejar de serlo. → Medir el RTT de un lookup contra ASTGU real y `max_connections`.
4. **Docker.** No verificado en esta máquina. Dentro del contenedor (Python **3.12** vs 3.14 aquí, glibc
   vs Windows, otro build de onnxruntime) las cifras pueden moverse. → Repetir `bench_ocr.py` dentro
   del contenedor.
5. **El sobrecoste del bind mount** (§5 B7) y con él **la decisión P2 Windows-vs-Linux**.
6. **Exactitud con `OCR_MAX_PIXELS=8 MP`** (S8) — es una **precondición**, no un detalle.
7. **Bundles multipágina profundos** (10-30 páginas): el corpus solo tiene 1 y 2 páginas. La cifra que
   fija el `INGESTA_REAPER_TTL` es una extrapolación.
8. **Ráfagas y coste de la cola:** no se cronometraron el escaneo recursivo de `1_entrada/`, el `sha256`
   por archivo (Fase 2), la verificación de estabilidad ni los movimientos de archivos.
9. **El hardware del servidor real** — DESCONOCIDO, y **el SO sigue sin decidirse** (`PLAN §5`, «P2»).
