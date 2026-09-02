# Requisitos de instalación — `incapacidad-ocr` (Gruppo)

**Fecha:** 2026-09-02 · **Estado:** documento de referencia para **aprobar la compra** e **instalar**.

Dos lectores, dos caminos de lectura:

- **Quien aprueba la compra** → §1 (perfiles de hardware), §3 (de dónde salen los números y qué
  supuestos hay que confirmar), §8 (preguntas abiertas).
- **Quien instala** → §2 (qué se instala), §4 (paso a paso, con y sin internet), §5 (preparación del
  SO), §6 (verificación), §7 (límites conocidos).

**Regla de este documento:** cada cifra es (a) una **medición** hecha en esta máquina, (b) un dato
**leído del repo** (con archivo y línea) o (c) un **cálculo explícito** a partir de (a)/(b). Lo que no
tiene base dice **«sin medir»** y explica cómo medirlo. Docker y Ollama **no corren en la máquina donde
se midió** (Docker Desktop exige elevación UAC que la sesión no tiene), así que **todo tamaño de imagen
Docker va marcado «estimado, sin verificar»**.

> **La conclusión honesta, por delante de todo lo demás: hace falta medir en el hardware real antes de
> comprar.** La medición base se hizo en un **portátil de 15 W con núcleos heterogéneos** (i7-1255U:
> 2 P-cores + 8 E-cores) y bajo contención real; el mismo documento varió **×1,55 (p50) y hasta ×2,86**
> entre dos pasadas. Los perfiles de §1 son un **orden de magnitud (~10 CPU-s/documento/núcleo)**, no un
> SLA. El script para repetir la medición en el servidor definitivo está en
> `../dataset-falsedad/requisitos/bench_ocr.py` (§3.5). Lo que **sí** está cerrado y no depende del
> hardware: el inventario de software (§2), el procedimiento de instalación aislada (§4.2) y los límites
> del diseño actual (§7).

**Informes de origen** (detalle y datos crudos; este documento los sintetiza y resuelve sus
contradicciones en §9): `../dataset-falsedad/requisitos/01_software.md` ·
`02_benchmark.md` · `03_dimensionamiento.md` · `04_host_y_so.md`.

---

## 1. Resumen para decidir (30 segundos)

**SO recomendado: Linux x86-64 (Ubuntu Server LTS o RHEL-family) con Docker Engine CE habilitado como
servicio del sistema.** Razón que no es de preferencia sino de compatibilidad: los **tres** servicios de
`docker-compose.yml` son contenedores **Linux** (`python:3.12-slim`, `mysql:8`, `ollama/ollama`), y un
host Windows Server no los ejecuta de forma nativa — necesita una VM Linux o WSL2 por debajo. Si TI
impone Windows, la única variante sin un «pero» estructural es **Windows Server como hipervisor
(Hyper-V) + VM Linux de autoarranque** (§4.3).

| | **A — Mínimo** | **B — Recomendado** | **C — Con IA local (opcional)** |
|---|---|---|---|
| **Escenario** | RapidOCR + reglas, BD ASTGU remota, un solo proceso de OCR | RapidOCR + reglas, UI en uso durante el drenaje, margen para el pool de la Fase 2 | + Ollama para **permisos manuscritos** y casos difíciles |
| **CPU** (físicos, x86-64 uniformes) | **4 núcleos** ≥ 2,4 GHz sostenido | **8 núcleos** ≥ 2,6 GHz sostenido | **16 núcleos** |
| **RAM** (host Linux) | **8 GB** — *solo con* `OCR_MAX_PIXELS=8000000`; con el default de 40 MP: **16 GB** | **16 GB** | **32 GB** |
| **RAM** (Windows Server + VM Linux: +4-6 GB solo para el host) | **12 GB** con el cap / 22 GB con el default de 40 MP | **24 GB** | 40 GB |
| **Disco** | **250 GB SSD** → ~3 años de soportes (206 GB ocupados, 18 % libre: al límite) | **500 GB SSD NVMe** → 5 años (337 GB, 33 % libre) | **1 TB SSD NVMe** |
| **GPU** | ninguna | ninguna | NVIDIA ≥ 12 GB VRAM — **solo acelera Ollama; NUNCA el OCR** (§2.3) |
| **Red en runtime** | **ninguna** (100 % offline por diseño — PII de salud, Ley 1581) | igual | igual |
| **Lo que drena HOY** (runner serial de 1 proceso, ventana 02:00-07:00) | **1 400 – 2 100 docs/noche**, con un **tope duro de 500 casos por corrida** (§7 L1) | idéntico: el código de hoy **no usa más de ~1 núcleo por documento** | idéntico |
| **Lo que drenaría con el pool de la Fase 2** (no implementado) | 2 workers → 2 100 – 4 200 docs/noche | 4 workers → **4 200 – 8 400** | 8 workers → 8 400 – 16 900 |
| **Necesidad medida/calculada** | día hábil medio **350** docs · **día pico 875** · ráfaga 1 500 · mes 7 000 | igual | igual |

**Lectura de la tabla en una línea:** el volumen del cliente **no necesita CPU** — necesita **RAM** (por
el pico de una sola página, §3.3), **disco** (por la retención, §3.4) y **dos arreglos de software que no
son hardware**: el tope de 500 casos por corrida y el cap de píxeles (§7). El perfil **B** es el que se
recomienda comprar; el **A** cubre el día pico con la aritmética derateada, pero sin margen para un fallo.

> **Aviso al que aprueba:** `INSTALACION_CLIENTE.md` §2 (documento ejecutivo previo) publica «4 núcleos /
> 16 GB / 250 GB» y «6,3 GB/mes». Prevalece esta tabla; la diferencia y el motivo están en §9.1.

---

## 2. Qué se instala

### 2.1 Camino Docker (recomendado)

Todo el runtime va dentro de los contenedores: **no hace falta instalar Python, Poppler, Tesseract ni
ningún servicio de OCR en el servidor**.

| Componente | Versión | Para qué | ¿Obligatorio? | Tamaño |
|---|---|---|---|---|
| **Docker Engine** + plugin **Compose v2** | Engine **≥ 23.0** (trae el plugin `compose`) | runtime de contenedores | **Sí** | ~0,5 GB *[estimado]* |
| Imagen **`incapacidad-ocr`** (se construye del `Dockerfile`) | base **`python:3.12-slim`** + `libgl1`, `libglib2.0-0`, `libgomp1` | la app: FastAPI + UI + OCR + lote | **Sí** | **0,8 – 1,2 GB en disco** *[estimado]*; componente **medido**: `site-packages` = **430 MB** en el venv de este repo (de los cuales **PyMuPDF 54 MB**), base slim ~130 MB |
| Imagen **`mysql:8`** → hoy **8.4.11-oraclelinux9** | fijar el tag exacto | BD de **demo** (catálogos + staging de prueba) | **No** en producción: allí `DB_*` apunta a la **ASTGU real** | 0,239 GB de descarga (**medido**) / ~0,6 GB en disco *[estimado]* |
| Imagen **`ollama/ollama`** → hoy **v0.33.2** | fijar el tag exacto | servidor de inferencia local | **No** | **3,383 GB de descarga (medido)** / ~8 GB en disco *[estimado]* |
| Volumen **`ollama-models`** | — | persiste los modelos | solo con IA | **6,54 GB (medido)** con los dos modelos |
| Volumen **`db-data`** | — | datadir de MySQL demo | solo con la BD local | ~0,3–0,5 GB *[estimado]* |
| Bind mount **`./ingesta` → `/data/ingesta`** | — | zona de ingesta masiva | **Sí** para el flujo por lotes | **5,4 GB/mes** (§3.4) |
| **`sql/init.sql`** | — | catálogos + tabla staging de demo | solo demo | 13,5 KB (**medido**) |
| **Python en el HOST** (3.12) | — | `scripts/` **no va dentro de la imagen** (el `Dockerfile` solo copia `requirements.txt` y `incapacidad_ocr/`) | Sí si se usan `scripts/sembrar_demo.py` (necesita **Pillow**), `scripts/guia_a_pdf.py` (necesita **fpdf2**); `scripts/migrar_estructura_ingesta.py` corre con stdlib pura | ~120 MB + los wheels que use |

### 2.2 Camino sin Docker (nativo)

| Componente | Versión | Para qué | ¿Obligatorio? | Tamaño |
|---|---|---|---|---|
| **CPython x86-64** | **3.12** (es la del `Dockerfile`). **No usar 3.13/3.14** | intérprete | **Sí** | ~120 MB en disco |
| Dependencias de `requirements.txt` | ver el pin de §2.4 | todo el pipeline | **Sí** | ruedas **162 MB** (linux/cp312) · **115 MB** (win/cp314) — **medidas**, pero **antes** de que `PyMuPDF` entrara al `requirements.txt`: hay que sumarle su wheel (**54 MB desempaquetado, medido**; el wheel, sin medir). Desempaquetado: **430 MB** (este venv, medido) |
| Libs de sistema en **Linux** | `libgl1`, `libglib2.0-0`, `libgomp1` | `cv2` (RapidOCR) y `onnxruntime` (OpenMP) | **Sí en Linux** | sin medir |
| Libs de sistema en **Windows** | ninguna: los wheels traen las DLL | — | — | incluido arriba |
| Acceso a **MySQL 8.x (ASTGU)** | 8.x | tabla staging `lp_ausentismos_ia` | **Sí** para registrar; sin BD la UI degrada | — |
| **Artefacto de servicio** (`systemd` / NSSM) | — | mantener `uvicorn` vivo y arrancar sin login | **Sí** en producción | **NO EXISTE EN EL REPO** — es un entregable pendiente (§5, paso 12) |

> **Por qué Python 3.12 y no 3.14.** `rapidocr-onnxruntime` declara `requires-python <3.13` en **todas**
> sus versiones desde la 1.3.x hasta la 1.4.4. En Python ≥ 3.13 pip **degrada en silencio** a la
> **1.2.3 de 2023** (modelos PP-OCRv3) y el pipeline pierde **6 puntos de precisión medidos**: **82 %**
> con 1.4.4 (lo que resuelve `python:3.12-slim`) frente a **76 %** con 1.2.3 — que es lo que hay hoy en el
> venv de este repo y se **re-ejecutó ahora** para confirmarlo: `python tests/test_ejemplos_reales.py` →
> **34/45 = 76 %**, con `rapidocr-onnxruntime 1.2.3` sobre Python 3.14.5. El **80 %** que publican
> `README.md` y `CONTEXT.md` §5.1 no corresponde a ninguna de las dos configuraciones reales.
>
> **Consecuencia de instalación, no de desarrollo:** qué motor de OCR acaba en producción lo decide hoy
> un accidente de metadata de un paquete. Se cierra con **dos** decisiones: Python 3.12 y
> `rapidocr-onnxruntime==1.4.4` en el pin.

Detalle específico del camino nativo en **Windows**: `incapacidad_ocr/batch.py:39` fija
`INGESTA_ROOT = Path(os.environ.get("INGESTA_ROOT", "/data/ingesta"))`, que en Windows apunta a
`C:\data\ingesta` → **hay que exportar `INGESTA_ROOT` explícitamente**, y activar
`LongPathsEnabled=1` como red de seguridad (§5, paso 8).

### 2.3 IA local con Ollama — opcional

Los modelos los **fija el servidor** en `docker-compose.yml:23-24` (anti-SSRF: el cliente de la API no
puede elegirlos).

| Modelo | Rol | ¿Obligatorio? | Descarga (**medida** en `registry.ollama.ai`) |
|---|---|---|---|
| **`gemma3:4b`** (`LLM_MODEL`) | estructurador texto→JSON del extractor `hibrido`/`ollama` | **No**: sin Ollama, `HybridExtractor` **degrada solo a reglas** | **3,339 GB** |
| **`qwen2.5vl:3b`** (`OCR_MODEL`) | OCR de visión — **necesario para permisos manuscritos** (`CLAUDE.md`: RapidOCR los lee muy mal) | **No**, pero sin él esos casos quedan a revisión manual | **3,201 GB** |

Dos advertencias que cambian el presupuesto:

1. **La GPU NO acelera el OCR de este repo**, y no es cuestión de drivers:
   `rapidocr_onnxruntime/config.yaml` trae `use_cuda: false` en las tres secciones, `ocr.py:96`
   construye `RapidOCR()` **sin kwargs**, y `requirements.txt` instala el `onnxruntime` de **CPU**
   (medido en esta máquina: expone `['AzureExecutionProvider','CPUExecutionProvider']`). Comprar GPU
   esperando OCR más rápido es tirar el dinero. La GPU **sí** cambia a Ollama de minutos a segundos.
2. **Ollama en el hot path del lote saca el volumen de la ventana nocturna.** `hibrido` = OCR (8,5 s) +
   una inferencia de LLM (**20-40 s** según `CONTEXT.md` §5.3, junio 2026, **no re-verificado**) →
   74-126 docs/h con un worker, por debajo del día pico. `docker-compose.yml:43` pone bien
   `INGESTA_EXTRACTOR=rule`, pero la UI ofrece «Híbrido» y `POST /api/lote/procesar` acepta
   `{"extractor":"hibrido"}`: **un auxiliar puede convertir el drenaje nocturno en uno de 10 h con un
   clic** (§7 L3).

### 2.4 Fijar versiones (pin) — requisito de instalación, no mejora

`requirements.txt` usa `>=` en **todas** sus líneas de dependencia (**13** tras añadir `numpy` y `fpdf2`,
§9.5) y no hay `pyproject.toml`, lock ni
`constraints.txt`, ni pin de las ~30 transitivas (`onnxruntime`, `opencv-python`, `numpy`, `shapely`,
`pyclipper`, `protobuf`). En un despliegue **offline y reproducible** eso rompe tres cosas:

1. El artefacto que se traslada al equipo aislado se congela el día del `pip download`. Reejecutando la
   resolución hoy contra PyPI sale otro stack: `opencv-python 4.13.0.92 → **5.0.0.93**` (major),
   `onnxruntime 1.27 → 1.29`, `numpy 2.4.6 → 2.5.2`, y aparece `tqdm`. Se **probó** ese stack
   re-resuelto y no rompe nada hoy — pero es una constatación de un día, y ninguna prueba del repo
   vigila el salto de major de OpenCV.
2. **La resolución depende de la plataforma:** el mismo `requirements.txt` instala rapidocr **1.4.4** en
   Linux/3.12 y **1.2.3** en Windows/3.14 → motores de OCR distintos y **6 puntos** de diferencia
   medidos. Sin pin, «reproducible» es falso incluso el mismo día.
3. Sin pin no se puede **firmar el bundle**: un `MANIFEST.sha256` deja de servir si pip puede traer otra cosa.

**Qué hacer en la instalación:** generar `requirements-lock.txt` a partir del venv que se valide, con
`rapidocr-onnxruntime==1.4.4`, `numpy` y `PyMuPDF` fijados, y **fijar también los tags de imagen**
(`ollama/ollama:latest → 0.33.2`, `mysql:8 → 8.4.11`, idealmente por digest). El lock propuesto completo
está en `../dataset-falsedad/requisitos/01_software.md` §4 — **con una corrección**: ese lock se escribió
antes de que `PyMuPDF>=1.24` entrara al `requirements.txt`, así que hay que añadirle
**`PyMuPDF==1.28.2`** (versión verificada en el venv).

---

## 3. Cómo se dimensionó

### 3.1 El volumen del cliente

| | Valor | Origen |
|---|---|---|
| Trámites/mes | **7 000** | el cliente (WhatsApp + correo, ~20 EPS, con ráfagas) |
| Documentos que se **OCR-ean**/mes | **7 000** | = 1 documento base por trámite: `batch.py:68` `TIPODOC_BASE = {INCAPACIDAD, PERMISO, VACACIONES}` y `batch.py:231` toma **solo** `bases[0]`. Los adjuntos (`FURAT`, `EPICRISIS`, …) se identifican **por el nombre** y **no pasan por OCR** → coste de CPU ≈ 0 |
| Archivos que se **mueven**/mes | **14 700** | calculado: 7 000 × (1 base + 1,0 adjunto) × 1,05 de reenvíos |
| Días hábiles/mes | **20** | 365 − 104 findes − 18 festivos = 243/año = 20,25 → 20 (redondear abajo es conservador) |
| Factor de día pico | **2,5×** | supuesto declarado (S2): martes después de un puente (Ley Emiliani concentra festivos en lunes) |

**Confundir los dos ejes cuesta caro:** CPU/RAM escalan con **7 000** (solo el documento base); disco,
número de ficheros, backup y MAX_PATH escalan con **14 700**. Son un factor **2,1** de diferencia.

### 3.2 La medición real (qué máquina, qué cifras)

**Máquina:** HP ProBook 440 G9 — **Intel Core i7-1255U** (10 núcleos físicos: 2 P + 8 E; 12 hilos;
base 1,70 GHz), 32 GB RAM, Windows 11 Pro 10.0.26200, Python 3.14.5 del venv del repo,
`onnxruntime 1.27.0` **solo-CPU**. Pipeline medido: `RapidOCRBackend` + `RuleBasedExtractor` — **el mismo
par que usa el lote** (`INGESTA_EXTRACTOR=rule`). Sin Docker, sin Ollama, sin MySQL.
**Corpus: 35 documentos únicos** (26 PDF de 1 pág · 5 JPEG · 4 PDF de 2 pág), 2 pasadas, se toma la
observación **menos contendida** de cada documento.

**Condiciones (leer antes de citar cualquier cifra):** la máquina **no estaba libre** (90-94 % de la CPU
del sistema la consumían otros procesos). Por eso se mide **CPU-segundos**, no solo tiempo de pared, y se
verifica el ratio CPU/pared = **0,96 (p50)** → el proceso **sí tuvo un núcleo casi entero**. Dispersión
residual entre pasadas: **×1,55 (p50) a ×2,86 (máx)**.

| Coste por documento, 1 hilo de OCR (= el coste de un worker) | p50 | p90 | máx | media |
|---|---|---|---|---|
| **CPU-segundos** (35 docs) | **8,6** | **12,6** | **31,4** | **9,92** |
| CPU-s, **solo documentos base** (34; el `HISTORIA.pdf` no se OCR-ea en producción) | 8,55 | 12,11 | 31,41 | **9,53** |
| CPU-s, base **con `OCR_MAX_PIXELS=8 MP`** | — | — | 15,25 | **8,53** |
| Tiempo de pared | 10,9 s | 21,8 s | 78,4 s | — |

**Dónde se va el tiempo:** OCR ONNX **97,2 %** · render de PDF/decode JPEG **2,8 %** · reglas de
extracción **0,013 %** (0,062 s para los **35 documentos juntos**). Consecuencia operativa: **el extractor
por reglas es gratis** — añadir formatos de EPS o endurecer heurísticas no cuesta rendimiento; **todo el
presupuesto es el OCR**, y el OCR escala con el **área rasterizada**, no con el peso del archivo (prueba:
`1056122540_INCAPACIDAD.pdf` pesa **12 KB**, el más liviano del corpus, y es el **más caro**: 78,4 s,
porque su página mide 7152×10110 px al rasterizar).

**Arranque (no se cobra por documento):** cargar los 3 modelos ONNX = **1,22 s** y **101,7 MB** de RSS.
La primera inferencia paga **~5 s** extra (inicialización perezosa de ONNX), una vez por proceso.

**Modelo empírico ajustado:** `CPU-s ≈ 2,2 + 1,4 × megapíxeles` hasta ~5 MP (comprobado: 0,9 MP → 3,5
predicho vs 3,50 medido; 4,45 MP → 8,4 vs 8,6 medido); por encima se vuelve sublineal (40 MP → 31 CPU-s).

### 3.3 De la medición al hardware — la aritmética a la vista

```
CPU/mes   = 7 000 docs × 9,53 CPU-s = 66 710 CPU-s = 18,5 CPU-h/mes
                        (con cap 8 MP: 8,53 → 16,6 CPU-h/mes)
día medio = 7 000 / 20            = 350 docs → 0,93 CPU-h
día PICO  = 350 × 2,5             = 875 docs → 875 × 9,53 = 8 339 CPU-s = 2,32 CPU-h
ráfaga    = 1 500 docs            → 3,97 CPU-h
```

Throughput por worker (1 hilo de OCR cada uno), con `OCR_MAX_PIXELS=8 MP`:

```
lineal   : 3 600 / 8,53 = 422 docs/h por worker
derateado: ÷1,5 (núcleo de servidor más lento — SUPUESTO) y ×0,75 para W≥2
           (eficiencia del pool — SUPUESTO, SIN MEDIR)
```

| Workers | docs/h lineal | docs/h derateado | Día pico (875) derateado | Cabe en 5 h (02:00-07:00) |
|---|---|---|---|---|
| **1 (lo que hay HOY)** | 422 | 281 | **3,1 h** | 1 405 docs |
| 2 | 844 | 422 | 2,1 h | 2 110 docs |
| **4 (perfil B)** | 1 688 | 844 | **1,0 h** | 4 220 docs |
| 8 (perfil C) | 3 376 | 1 688 | 31 min | 8 439 docs |

**Conclusión de CPU: el volumen exige UN worker.** Se recomiendan **4** por cuatro razones concretas,
ninguna genérica: (1) la dispersión medida es **×2,86** y con 1 worker el día pico ya consume 3,1 de las
5 h; (2) la velocidad del núcleo del servidor es **desconocida** y puede ser peor que el ÷1,5 supuesto;
(3) el **backfill** de un año de histórico (84 000 docs) son **199-222 CPU-h** = **8,3-9,3 días** con 1
worker y **50-56 h** con 4 (aritmética lineal; derateado es el doble);
(4) con 4 workers un fallo **cabe** en la ventana (el drenaje del día pico termina hacia las 03:00 y
quedan 4 h para reintentar).

**RAM — es el eje que decide la compra, no la CPU.**

| | Valor medido |
|---|---|
| RSS con los modelos cargados, sin procesar | **101,7 MB** |
| Pico de RSS, documentos normales (33 de 35, ≤ 10 MP/pág) | p50 **899 MB** · **máx 971 MB** |
| Pico de RSS, **documentos patológicos** (2 de 35: páginas de 86,5 MP y 72,3 MP al rasterizar) | **7 647 MB** y **6 810 MB** |
| Los mismos dos, con `OCR_MAX_PIXELS=8000000` | **1 555 MB** y **1 589 MB** (÷4,4 a ÷4,9) y **la mitad de CPU** (31,2→15,3 y 31,4→13,3 CPU-s) |
| RSS al terminar | 72 MB → **no hay fuga** |

**`OCR_MAX_PIXELS=40 MP` (el default) no protege nada**, y esto es un hallazgo, no una opinión: RapidOCR
usa `limit_type: min` con `limit_side_len: 736` (`rapidocr_onnxruntime/config.yaml`), así que si el lado
corto ya supera 736 px **no reescala** y el detector recibe la página **completa**; un tensor de 40 MP × 3
canales × 4 bytes = 480 MB, más los mapas de activación → varios GB. Con una incidencia medida de
**2/31 = 6,5 %**, a 7 000 trámites/mes son **~450 documentos al mes** que pedirían ~7,6 GB cada uno: **no
es la cola, es la rutina.**

Reparto de RAM usado en los perfiles: **1,6 GB por worker** (peor caso medido con el cap de 8 MP) +
0,9 GB (uvicorn/UI con un documento en vuelo) + 4 GB (MySQL si es local) + 1,5 GB (SO) — y **+4-6 GB** si
el host es Windows Server con una VM Linux por debajo. Matiz de hoy: la UI y el lote **comparten proceso y
la misma instancia de RapidOCR** (`webapp.py:138-144`), así que puede haber **dos documentos en vuelo en
un proceso** → con el default de 40 MP el peor caso son ~15 GB en un solo proceso.

### 3.4 Disco

Tamaño de archivo **medido** sobre los 31 documentos reales de `../dataset-falsedad/docs`:
**media 378,6 KB** (medida ahora, 31 archivos, 12 018 846 B), **384,7 KB** sobre los 29 únicos por sha256,
mediana 221,6 KB, rango 12,2 KB – 1 788 KB. Contraste independiente: la semilla de la ingesta
(`ingesta/_sistema/semilla/`, 32 archivos) da **366,9 KB**. **n es pequeño en las tres: hay que remedir con
un mes real antes de comprar disco.**

```
14 700 archivos/mes × 384,7 KB = 5,39 GB/mes → 65 GB/año → 194 GB (3 años) → 324 GB (5 años)
```

Sin descontar compresión (PDF y JPEG ya vienen comprimidos: un zip de este corpus gana ~5-10 %) ni
dedup (hoy **no existe**, y `batch._destino_libre` guarda el reenvío como `_dupNN` **a propósito**, para
no perder un soporte en silencio).

| Sensibilidad (los dos supuestos que mandan) | GB/mes | 1 año | 3 años | **5 años** |
|---|---|---|---|---|
| **Base** (384,7 KB · 1,0 adjunto/trámite) | 5,39 | 65 | 194 | **324** |
| Si el promedio real es la mediana (221,6 KB) | 3,11 | 37 | 112 | **186** |
| **Si son 2 adjuntos/trámite** (22 050 archivos/mes) | 8,09 | 97 | 291 | **485** |
| Si además los adjuntos pesan 2× | 10,79 | 130 | 389 | **648** |

**Rango a 5 años: 186 – 648 GB.** Software fijo: **~2,5 GB sin IA**, **~20 GB con Ollama y los dos
modelos** *[estimado]*, más **~10 GB de caché de capas de Docker** *[estimado]* que conviene provisionar.
**La BD no es un factor:** fila de `lp_ausentismos_ia` medida sobre el DDL real = **407 B de datos** (0,6 KB
asignados con overhead e índices) → 7 000 filas de staging + 7 000 alertas = **6,5 MB/mes = 390 MB a 5
años**, ruido frente a 324 GB de árbol.

### 3.5 Los SUPUESTOS que el cliente tiene que confirmar

Cada uno se confirma con **una frase**. Ordenados por cuánto mueven la compra.

| # | Supuesto | Valor usado | Qué cambia si es distinto | Pregunta |
|---|---|---|---|---|
| **S1** | `OCR_MAX_PIXELS=8 MP` **no degrada la exactitud** | asumido, **SIN MEDIR** | Si degrada → hay que volver a 40 MP → **RAM/worker 1,6 → 7,6 GB** y **los perfiles A y B dejan de servir** | interno: re-correr `tests/test_ejemplos_reales.py` y el ground-truth de `dataset-falsedad` con los dos caps y comparar campo a campo |
| **S2** | Adjuntos por trámite | **1,0** (+5 % de reenvíos → 2,1 archivos/trámite) | 2 adjuntos → **disco a 5 años 324 → 485 GB**; con adjuntos 2× más pesados, 648 GB. **La CPU no cambia** (no se OCR-ean) | «¿Cuántos documentos trae en promedio un trámite además de la incapacidad?» |
| **S3** | El lote corre con `extractor=rule` | `rule` | `hibrido` en los 7 000 → **+39-78 h de reloj/mes** de LLM en CPU → hace falta el **perfil C con GPU** | «¿Se acepta que el lote use solo reglas y el auxiliar suba a IA los casos difíciles a mano?» |
| **S4** | Retención legal de los soportes | **5 años** (fiscalización UGPP) | 3 años → 194 GB · 15 años (historia clínica) → 971 GB. Decide entre 250 GB y 1 TB | «Jurídico: ¿cuántos años hay que conservar el original del soporte?» |
| **S5** | «7 000 incapacidades/mes» = **7 000 trámites**, no 7 000 ficheros | trámites | Si fueran ficheros → ~3 500 trámites y **toda la CPU se parte por 2** | «¿Los 7 000 son casos o archivos?» |
| **S6** | Un núcleo del servidor es **1,5× más lento** que el medido | ÷1,5 | 3× más lento → día pico 6,9 CPU-h con 1 worker; con 4 sigue cabiendo | **se resuelve midiendo, no preguntando** (§3.6) |
| **S7** | El pool escala **lineal** (derateo ×0,75) | ×0,75 | Si escalara al 0,4, 4 workers = 2 efectivos. Sigue cubriendo el día pico | **SIN MEDIR**: sembrar 200 documentos y correr con W = 1, 2, 4, 8 |
| **S8** | Factor de día pico | **2,5×** | 4× → día pico 3,7 CPU-h; **sigue cabiendo**. Sensible al confort, no a la compra | «¿Nos pasas el conteo de radicados por día de la semana de un mes?» |
| **S9** | Peso medio de archivo | **384,7 KB** (n=29) | ver tabla de sensibilidad de §3.4 | «¿Cuánto pesa una epicrisis escaneada típica?» |
| **S10** | Ventana nocturna | **5 h (02:00-07:00)** | 2 h → 4 workers siguen cubriendo el día pico. Tiempo real → cambia el diseño | «¿A qué hora empieza a revisar el auxiliar?» |
| **S11** | Tamaños de imagen Docker | 1,1 / 8,5 / 0,7 GB | ±50 % → ±10 GB en el fijo; irrelevante frente a 324 GB de árbol | **estimado, sin verificar** (Docker no arranca en esta máquina) |

### 3.6 Medir en el servidor definitivo (antes de firmar la compra)

`bench_ocr.py` es autocontenido: solo necesita el venv del proyecto + `psutil`. No usa red, ni Docker, ni
Ollama, ni MySQL.

```bash
PY=/ruta/al/venv/bin/python                     # Windows: .venv/Scripts/python.exe
$PY -m pip install psutil
# A) coste por WORKER (el número que se multiplica por N) — el que importa
$PY bench_ocr.py --repo /ruta/incapacidad-ocr --docs /ruta/muestra \
   --repeats 3 --hilos 1 --esperar-cpu 25 --etiqueta "servidor-1hilo" \
   --out-json bench_1hilo.json --out-md tabla_1hilo.md
# B) latencia tal como corre la UI hoy (sin cap de hilos)
$PY bench_ocr.py --repo /ruta/incapacidad-ocr --docs /ruta/muestra --repeats 2 \
   --etiqueta "servidor-multihilo" --out-json bench_multihilo.json
# C) efecto de acotar los píxeles por página
OCR_MAX_PIXELS=8000000 $PY bench_ocr.py ... --hilos 1 --out-json bench_cap8.json
```

Con la máquina **quieta** (`--esperar-cpu 25`) y **≥3 pasadas**. En orden de importancia, lo que falta
medir: (1) escalado real del pool con el cap de hilos implementado; (2) exactitud con 8 MP (S1);
(3) un bundle real de 10-30 páginas para fijar el `INGESTA_REAPER_TTL`; (4) latencia de MySQL contra
ASTGU con N workers; (5) sobrecoste del bind mount en el SO elegido.

---

## 4. Instalación paso a paso

### 4.1 Caso (a): servidor CON salida a internet

```bash
# 1) Docker Engine + Compose v2, habilitado como servicio del sistema (Ubuntu/Debian)
curl -fsSL https://get.docker.com | sh          # o el repo oficial de la distro
sudo systemctl enable --now docker
docker version && docker compose version        # Engine >= 23.0, Compose v2.x

# 2) Código en una ruta corta y estable
sudo mkdir -p /opt/incapacidad-ocr && cd /opt/incapacidad-ocr
#    (copiar el repo aquí: git clone / tar / git bundle)

# 3) EDITAR docker-compose.yml (cuatro cambios, todos de instalación):
#    a) línea 60: ollama/ollama:latest -> ollama/ollama:0.33.2     (§2.4)
#    b) línea 72: mysql:8              -> mysql:8.4.11             (§2.4)
#    c) línea 49: ./ingesta:/data/ingesta -> /datos/ingesta:/data/ingesta
#       (el bind mount está CABLEADO a ./ingesta: para llevar los documentos al disco de datos
#        hay que cambiarlo aquí; `INGESTA_ROOT` solo dice dónde los ve el contenedor)
#    d) añadir al bloque `environment:` del servicio incapacidad-ocr:
#         - OCR_MAX_PIXELS=${OCR_MAX_PIXELS:-8000000}
#         - TZ=${BATCH_TZ:-America/Bogota}
#       (ninguna de las dos existe hoy, y por .env NO llegan al contenedor — ver §4.4)

# 4) Crear el .env  (NO EXISTE en el repo: hay que escribirlo — plantilla en §4.4)
$EDITOR .env && chmod 600 .env

# 5) Construir y levantar
docker compose up -d --build

# 6) Crear el árbol de la ingesta
docker compose exec incapacidad-ocr python -m incapacidad_ocr.batch --init

# 7) (Opcional) IA local — una sola vez, queda en el volumen
docker compose exec ollama ollama pull gemma3:4b       # 3,339 GB
docker compose exec ollama ollama pull qwen2.5vl:3b    # 3,201 GB

# 8) Verificar: §6 completo
```

> **Dos avisos de este camino.** (1) `docker compose up -d` levanta **también el MySQL de demo** (el
> servicio `db` está en `depends_on` del servicio web, `docker-compose.yml:50-52`): en producción, con
> `DB_*` apuntando a ASTGU, ese contenedor sobra — hay que quitar `db` de `depends_on` y de `services`
> para no gastar ~0,6 GB de disco y RAM en una BD de juguete. (2) La UI se publica **solo en
> `127.0.0.1:8000`** (`docker-compose.yml:18`): si tiene que verse desde otro PC hacen falta
> reverse-proxy + TLS + autenticación, que **no están en el repo**.

### 4.2 Caso (b): servidor AISLADO, sin salida a internet — el que probablemente aplique

**Dos reglas que hay que interiorizar antes de empezar:**

1. **`docker build` es IMPOSIBLE en el equipo aislado.** El `Dockerfile` hace `apt-get update &&
   apt-get install` (líneas 9-13) y `pip install -r requirements.txt` (línea 19). La imagen de la app hay
   que **construirla en el equipo con internet** y trasladarla ya construida.
2. **El equipo puente debe coincidir en plataforma con el destino** (`docker save` guarda binarios de una
   sola plataforma; un portátil Windows con Docker Desktop **sí** produce `linux/amd64`, que es lo que
   hace falta). Para las ruedas de pip hay que declarar plataforma y versión de Python **a mano**.

#### PARTE A — en el equipo CON internet («puente»)

```bash
# A1) Imágenes: tags EXACTOS, nunca :latest
docker pull python:3.12-slim
docker pull ollama/ollama:0.33.2
docker pull mysql:8.4.11
cd incapacidad-ocr && docker build -t incapacidad-ocr:1.0.0 -t incapacidad-ocr:latest .
docker images --digests | grep -E "ollama|mysql|incapacidad-ocr|python"   # anotar digests
docker save incapacidad-ocr:1.0.0 ollama/ollama:0.33.2 mysql:8.4.11 \
  | gzip -9 > imagenes-incapacidad-ocr-$(date +%F).tgz
#   Tamaño esperado del .tgz: ~4 GB con Ollama · < 1 GB sin él  (docker save NO comprime; gzip lo acerca
#   a los tamaños de registro medidos: ollama 3,383 + mysql 0,239 + app ~0,4 [estimado])

# A2) Modelos de Ollama (el contenido del volumen)
docker compose -p incapacidad-ocr up -d ollama
docker compose -p incapacidad-ocr exec ollama ollama pull gemma3:4b
docker compose -p incapacidad-ocr exec ollama ollama pull qwen2.5vl:3b
docker compose -p incapacidad-ocr exec ollama ollama list      # verificar nombre:tag exactos
docker run --rm -v incapacidad-ocr_ollama-models:/from -v "$PWD":/to alpine \
  tar czf /to/ollama-models-$(date +%F).tgz -C /from .
docker compose -p incapacidad-ocr down
#   El .tgz no comprime (los GGUF ya están cuantizados): ~6,5 GB los dos modelos, ~3,4 GB solo gemma3.
#   Variante sin Docker en el puente: Ollama nativo y copiar ~/.ollama/models (mismo layout).

# A3) Ruedas de pip — SOLO si el destino es sin Docker (o para poder reinstalar dentro del contenedor)
python -m pip download -r requirements-lock.txt -d wheels-linux-cp312 \
  --only-binary :all: --python-version 3.12 \
  --platform manylinux_2_28_x86_64 --platform manylinux_2_17_x86_64 --platform manylinux2014_x86_64
python -m pip download -r requirements-lock.txt -d wheels-win-cp312 \
  --only-binary :all: --python-version 3.12 --platform win_amd64

# A4) Sellar el paquete
sha256sum imagenes-*.tgz ollama-models-*.tgz wheels-*/*.whl > MANIFEST.sha256
git bundle create incapacidad-ocr-repo.bundle --all
#   Llevar además: requirements-lock.txt, el .env preparado y este documento.
```

**Tres trampas verificadas empíricamente en A3** (no son teoría: fallaron al hacerlo):

1. **Un solo `--platform manylinux2014_x86_64` NO alcanza** → `ResolutionImpossible`. `onnxruntime` y
   `mysql-connector-python` solo publican `manylinux_2_28_x86_64` para cp312, mientras `shapely` solo
   publica `manylinux_2_17`. Hay que pasar **los tres** (`manylinux_2_28` es compatible con
   `python:3.12-slim`, Debian bookworm, glibc 2.36).
2. **`pip download --platform` evalúa los markers con el SO del PUENTE, no del destino.** Descargando
   desde Windows para Linux, el bundle trajo `colorama` (inútil en Linux) y **NO trajo `uvloop`** (que
   `uvicorn[standard]` exige con marker `sys_platform != 'win32'`) → `pip install --no-index` en el
   destino **falla**. Arreglo: generar el bundle en un puente del mismo SO, o añadir a mano lo que el
   marker se comió (`pip download uvloop==0.22.1 -d wheels-linux-cp312 --only-binary :all:
   --python-version 3.12 --platform manylinux_2_28_x86_64`). Verificar siempre:
   `ls wheels-linux-cp312 | grep -E "uvloop|onnxruntime|rapidocr|opencv|pymupdf"`.
3. **Los modelos ONNX de RapidOCR van DENTRO del wheel** (verificado abriéndolo): 1.2.3 → 12,3 MB de
   wheel con 13,7 MB de ONNX (PP-OCRv3); 1.4.4 → 14,9 MB con 16,2 MB (PP-OCRv4). El wheel es
   `py3-none-any` y **no contiene ninguna URL de descarga** → **no baja nada en runtime**. Esa parte de la
   promesa offline se sostiene. `pip` tampoco hay que llevarlo: `python -m venv` lo siembra con
   `ensurepip`, que es offline.

#### PARTE B — en el equipo AISLADO

```bash
# B0) Integridad
sha256sum -c MANIFEST.sha256

# B1) Cargar imágenes (NO hay pull, NO hay build)
gunzip -c imagenes-incapacidad-ocr-*.tgz | docker load
docker images        # incapacidad-ocr, ollama/ollama:0.33.2, mysql:8.4.11

# B2) Restaurar el volumen de modelos ANTES de levantar ollama
docker volume create incapacidad-ocr_ollama-models
docker run --rm -v incapacidad-ocr_ollama-models:/to -v "$PWD":/from alpine \
  tar xzf /from/ollama-models-*.tgz -C /to

# B3) Fijar en docker-compose.yml los tags que se cargaron (si no, compose intentará PULL y fallará)
docker tag incapacidad-ocr:1.0.0 incapacidad-ocr:latest

# B4) Levantar. NUNCA con --build (intentaría apt-get/pip sin red).
docker compose -p incapacidad-ocr up -d

# B5) Verificación: §6 completo, y REPETIRLO con la NIC del servidor deshabilitada
#     (es la prueba dura de la promesa offline)
```

**Variante sin Docker en el equipo aislado** (procedimiento **validado de verdad en esta máquina**: venv
limpio + `pip install --no-index --find-links=<bundle de 115 MB> -r requirements.txt` → **37 paquetes
instalados, cero accesos a red**, y después `tests/test_processor.py` y `tests/test_ejemplos_reales.py`
corrieron completos):

```bash
python -m venv /srv/incapacidad-ocr/.venv          # ensurepip: offline
/srv/incapacidad-ocr/.venv/bin/python -m pip install \
    --no-index --find-links=/traslado/wheels-linux-cp312 -r requirements-lock.txt
# Si se pinea rapidocr 1.4.4 sobre Python >= 3.13, añadir --ignore-requires-python (probado: funciona)
```

Lo que **no** cubre el repo y hay que hacer después: variables `DB_*`, `INGESTA_ROOT`, `TZ`, `BATCH_TZ`,
`INGESTA_CRON`; `LongPathsEnabled` en Windows; **el artefacto de servicio** (`systemd`/NSSM); ACL sobre
`ingesta/` y cifrado del volumen. Todo eso es §5.

### 4.3 Si TI impone Windows Server

| Variante | ¿Arranca sin sesión iniciada? | Veredicto |
|---|---|---|
| **W1 — Windows Server como hipervisor (Hyper-V) + VM Linux** | **Sí**: VM con *Automatic Start Action = Always start*, y dentro igual que Linux | **la única contingencia sin un «pero» estructural.** `INGESTA_ROOT` **dentro de un disco virtual de la VM**, no en un recurso SMB del host |
| **W2 — WSL2 + Docker Engine dentro de la distro** | **Frágil**: WSL es por usuario; hay que forzarlo con una tarea programada al arranque + `systemd=true` en `/etc/wsl.conf` | no soportado ni probado en este proyecto |
| **W3 — Windows nativo, sin Docker** (`uvicorn` + venv + NSSM) | Sí | duplica la superficie de despliegue: hay que **escribir** el servicio (no existe), usar **Python 3.12** y **revalidar la precisión** en Windows (sin medir) |
| Windows + **Docker Desktop** | **No**: el motor lo levanta la app en la sesión del usuario | **descartado**, y además Windows Server no está en su matriz de soporte *[confirmar con el proveedor]* |

**Corrección al repo (agujero lógico, no matiz):** `PLAN_INGESTA_MASIVA.md` §5 llama «camino preferido en
Windows» a *Windows Server con Docker Engine/containerd como servicio*. Esos runtimes ejecutan
contenedores **Windows**; las tres imágenes de este compose son **Linux** y no existe versión Windows de
ellas (LCOW quedó descontinuado) *[confirmar con el proveedor]*. Y el «modo B» que el plan propone para
Windows headless con Docker Desktop (`docker compose up -d` / `docker compose exec` desde el Programador
de tareas) **no puede funcionar**: ambos son **clientes** de un daemon que Docker Desktop solo levanta
cuando un usuario inicia sesión. Si el motor está en modo servicio, el APScheduler in-process **ya basta**
y el modo B sobra.

### 4.4 Plantilla de `.env` (no existe en el repo — hay que crearla)

`docker-compose.yml` hace `DB_HOST=${DB_HOST:-db}`: **si el `.env` falta, el sistema escribe el staging en
un MySQL de juguete dentro de un contenedor y nadie se da cuenta.**

```ini
# --- BD ASTGU real (staging lp_ausentismos_ia) ---
DB_HOST=srv-astgu.interno
DB_PORT=3306
DB_NAME=ASTGU
DB_USER=ocr
DB_PASSWORD=********
# --- Corrida programada del lote (vacío = DESACTIVADA) ---
INGESTA_CRON=0 2 * * *
BATCH_TZ=America/Bogota
INGESTA_EXTRACTOR=rule
# --- SEGURIDAD: en producción SIEMPRE 0. Con 1, el botón «Reiniciar prueba» puede VACIAR
#     la tabla de staging de la BD real (db.py:280, docker-compose.yml:47 trae 1 por defecto).
RESET_BD_PRUEBA=0
```

> **Trampa verificada leyendo el compose: dos variables NO llegan al contenedor por el `.env`.** El
> `.env` de Compose sirve para **interpolar** en el YAML; al contenedor solo llega lo que está en el bloque
> `environment:`. `OCR_MAX_PIXELS` **no está** en ese bloque (ni `PDF_RENDER_SCALE`, ni `TZ`), así que
> **el cap de 8 MP y la zona horaria hay que AÑADIRLOS al `docker-compose.yml`**, no solo al `.env`:
>
> ```yaml
>     environment:
>       - OCR_MAX_PIXELS=${OCR_MAX_PIXELS:-8000000}   # §3.3: RAM ÷4,4 y CPU ÷2 en los patológicos
>       - TZ=${BATCH_TZ:-America/Bogota}              # §5 paso 4: hoy el contenedor corre en UTC
> ```

---

## 5. Preparación del servidor (checklist, en orden)

Cada paso trae **cómo se comprueba**. Los pasos marcados **(W)** son solo para el host Windows de W1.

1. **SO base y disco de datos.** Ubuntu Server LTS x86-64 (o Rocky/RHEL), instalación mínima, sin
   escritorio. **Partición o disco separado** para `INGESTA_ROOT`, dimensionado con **5,4 GB/mes**
   (§3.4) + el software (§3.4). *Comprobación:* `lsblk`, `df -h`.
2. **Cifrado en reposo ANTES de escribir el primer documento.** LUKS con desbloqueo por TPM2 para que el
   reboot sea desatendido: `cryptsetup luksFormat /dev/sdX && systemd-cryptenroll --tpm2-device=auto
   /dev/sdX` + entrada en `/etc/crypttab`. **(W)** BitLocker en el volumen que aloja el VHDX, con
   **TPM-only** (un PIN pre-boot **rompe** el reinicio desatendido). *Comprobación:* reboot y que monte
   solo (`lsblk -o NAME,FSTYPE,MOUNTPOINT` / `manage-bde -status`).
   **Requisito de compra, no de configuración: sin TPM (o vTPM en la VM) no se puede tener cifrado y
   reboot desatendido a la vez.**
3. **Zona horaria del host + NTP:** `timedatectl set-timezone America/Bogota && timedatectl set-ntp true`.
   **(W)** `Set-TimeZone -Id 'SA Pacific Standard Time'` + `w32tm /resync`.
4. **Zona horaria del CONTENEDOR — hoy es un defecto real del compose.** `docker-compose.yml:42` pasa
   `BATCH_TZ`, pero eso **solo** configura el cron de APScheduler (`webapp.py:160`). **No hay ninguna
   variable `TZ`** → el contenedor corre en **UTC**, y `date.today()` (`erp.py:615`) es lo que alimenta
   `fecharegistro` (`erp.py:920`) y el «hoy» de las reglas de tiempo. *Consecuencia concreta:* cualquier
   corrida entre las **19:00 y 23:59 de Bogotá** estampa `fecharegistro` **un día adelantado**.
   *Acción:* añadir `- TZ=${BATCH_TZ:-America/Bogota}` al servicio `incapacidad-ocr`. *Comprobación:*
   `docker compose exec incapacidad-ocr python -c "from datetime import datetime;print(datetime.now())"`
   contra el reloj de pared de Bogotá.
5. **Docker Engine como servicio:** `systemctl enable --now docker`. *Comprobación:*
   `systemctl is-enabled docker` → `enabled`. **(W)** VM con
   `Set-VM -Name ocr -AutomaticStartAction Start -AutomaticStartDelay 0`.
6. **Usuario de servicio sin shell, con el uid que espera el contenedor:**
   `useradd -r -u 1000 -g 1000 -s /usr/sbin/nologin ocr-svc`. El `Dockerfile:25` hace
   `useradd --create-home app` → uid **1000** en Debian *[verificar con
   `docker compose exec incapacidad-ocr id`]*. **Nunca** cuentas de personas en el grupo `docker`.
7. **Permisos de la carpeta de ingesta — el paso que más rompe el día 1:**
   `mkdir -p /datos/ingesta && chown -R 1000:1000 /datos/ingesta && chmod -R 0750 /datos/ingesta`.
   *Comprobación dura, no opcional:*
   `docker compose exec incapacidad-ocr touch /data/ingesta/_sistema/tmp/prueba && echo OK`.
   **Si esto falla, el runner inserta en staging y NO mueve los archivos, y la corrida siguiente
   DUPLICA las filas** (§7 L4).
8. **Longitud de la ruta y rutas largas.** Verificar **`len(INGESTA_ROOT) ≤ 115`** (presupuesto calculado:
   el árbol consume como máximo `99 + 1 + 44 = 144` caracteres de los 259 utilizables de MAX_PATH; con
   `D:\ingesta` el peor caso queda en **155**). **(W)** además
   `Set-ItemProperty 'HKLM:\SYSTEM\CurrentControlSet\Control\FileSystem' LongPathsEnabled 1` como red de
   seguridad — **medido**: con la clave a 1, rutas de 250/259/270/300 caracteres se crearon y `cmd.exe` y
   PowerShell 5.1 las leyeron todas. El que se rompería no es el contenedor (Linux, límite 4096) sino el
   **host**: Explorer, antivirus y backup.
9. **Antivirus** *(aplica a Windows; en Linux normalmente no hay AV on-access)*. Excluir del escaneo **en
   tiempo real**: `INGESTA_ROOT`, la carpeta de VHDX/`%LOCALAPPDATA%\Docker`. **La exclusión NO se pide por
   rendimiento** — medido, el AV cuesta **×35 en la primera lectura** (45,19 ms vs 1,28 ms por archivo),
   que a 11 000 archivos/mes son **8,3 min/mes = 1,2 %** del coste de OCR. Se pide porque **la cuarentena
   de un PDF destruye la ÚNICA copia de un soporte legal**, y **pasa en silencio**: `batch._mover` captura
   toda excepción (`batch.py:211-212` → `log.exception` y sigue). **Contrapeso obligatorio en el runbook:**
   los archivos llegan de WhatsApp y correo, así que hace falta un **escaneo programado diario de esa misma
   ruta configurado para ALERTAR, no para borrar**, y que la alerta la lea una persona. Además desactivar
   **Windows Search** sobre esa ruta. *Comprobación:* copiar un PDF real a `1_entrada/` y confirmar que
   sigue ahí un minuto después.
10. **`.env` (§4.4) con la BD real y `RESET_BD_PRUEBA=0`**, permisos `600`. *Comprobación:* §6.2.
11. **Fijar los tags de imagen y el pin de dependencias** (§2.4), en particular
    `rapidocr-onnxruntime==1.4.4`: son **+6 puntos de precisión medidos**.
12. **Arranque sin login — la prueba que cierra la precondición «P2» del plan.** Los tres servicios ya
    llevan `restart: unless-stopped`; eso **solo** sirve si el runtime arranca en el boot, y el cron es
    **in-process** (si el contenedor no está vivo, no hay cron). **Prueba de aceptación: reinicio en frío
    SIN INICIAR SESIÓN** → esperar la hora de `INGESTA_CRON` → `GET /api/lote/estado` responde
    `programado: true` con `proxima_ejecucion` coherente **y** la corrida movió documentos de `1_entrada/`.
    En el camino sin Docker, aquí hay que **escribir** la unidad `systemd`/servicio NSSM: **no existe en el
    repo**.
13. **Monitoreo de disco con umbrales calculados:** crecimiento **5,4 GB/mes** de documentos + 6,54 GB del
    volumen de modelos si se usa IA. Alertar al **20 % libre** y vigilar que el disco de Docker no se llene
    (cada `up --build` deja capas huérfanas). *Comprobación:* `df -h`, `docker system df`, y que la alerta
    llegue a una persona.
14. **Retención y respaldo.** El **único dato irremplazable de este servidor es el árbol `ingesta/`**: el
    volumen `db-data` no contiene nada de valor en producción (`DB_*` apunta a ASTGU) y `ollama-models` se
    reconstruye con un `pull`. Respaldo **on-premise y cifrado — NUNCA a la nube**: rompería la restricción
    «nada sale a internet» y es el escenario de fuga más probable del diseño (la copia lleva la PII
    completa: la **cédula va en el nombre del archivo** y el **nombre de la persona en la ruta**). Coste
    real del respaldo: no son los GB, es el **número de ficheros** — 176 400/año y ~882 000 a 5 años → usar
    **snapshot de volumen**, no backup fichero a fichero. *Comprobación:* restaurar un mes en un directorio
    aparte y contar archivos (medido en NTFS: crear 11 000 archivos = 23,3 s; borrarlos = 9,4 s).
15. **Auditar quién está en el grupo `docker` / `docker-users`:** es equivalente a root sobre el host y por
    tanto sobre **toda** la PII. Debe ser una lista corta y revisada. **Es un control de Ley 1581 y no está
    documentado en el repo.**
16. **Registrar la decisión de SO y su prueba** en `CONTEXT.md` §7 (hoy dice «pendiente») y corregir
    `PLAN_INGESTA_MASIVA.md` §5 con §4.3 de este documento.

---

## 6. Verificación post-instalación

Todos los comandos y endpoints de esta sección **existen hoy** y se verificaron contra el código (o se
ejecutaron en esta máquina). Sustituir `docker compose exec incapacidad-ocr` por
`.venv/bin/python` en el camino sin Docker.

### 6.1 El servicio está arriba

```bash
docker compose ps                                    # los servicios en 'running'/'healthy'
curl -s http://localhost:8000/api/health             # -> {"status":"ok","service":"incapacidad-ocr"}
curl -s http://localhost:8000/docs -o /dev/null -w "%{http_code}\n"   # 200 (OpenAPI)
```

> **Corrección importante:** `/api/health` **NO informa del estado de la BD** — devuelve exactamente
> `{"status":"ok","service":"incapacidad-ocr"}` (`webapp.py:185-187`). Cualquier runbook que diga que
> `health` reporta `db_disponible` es falso; para la BD hay que usar §6.2.

### 6.2 La BD es la correcta (y no el MySQL de juguete)

```bash
curl -s http://localhost:8000/api/staging | python -m json.tool | head
#   -> {"db_disponible": true, "registros": [...]}   (webapp.py:448-463)
#   Si sale false: DB_* mal, BD inalcanzable, o el .env no se cargó.
# Y la comprobación que de verdad cierra: que la fila aparezca en ASTGU.
#   SELECT id,estado,paciente_leido,fechainicio,Numerodias FROM lp_ausentismos_ia ORDER BY id DESC LIMIT 5;
```

### 6.3 El motor de OCR que quedó instalado es el que se pinó

```bash
docker compose exec incapacidad-ocr python -c \
 "import importlib.metadata as md, glob, os, rapidocr_onnxruntime as r; \
  print('rapidocr', md.version('rapidocr-onnxruntime')); \
  print(sorted(os.path.basename(p) for p in glob.glob(os.path.dirname(r.__file__)+'/**/*.onnx', recursive=True)))"
#   Esperado: 1.4.4 y modelos PP-OCRv4.  Si sale 1.2.3 -> se colaron Python >=3.13 / falta el pin (§2.2).
```

### 6.4 Procesar un documento de prueba (extremo a extremo)

```bash
# En PowerShell 5.1 usar curl.exe (Invoke-RestMethod no tiene -Form).
# En el servidor: cualquier incapacidad real (PDF o imagen) que se deje a mano.
curl -s -F "archivo=@/tmp/incapacidad_prueba.pdf" -F "ocr=rapidocr" -F "extractor=rule" \
     -F "estado_recepcion=WHATSAPP" http://localhost:8000/api/procesar | python -m json.tool
#   Debe traer: texto_plano no vacío, incapacidad.{fecha_inicio,fecha_fin,dias}, diagnostico.cie10
#   y el bloque .staging con los IDs resueltos (PREVIEW: no inserta).
```

Y la UI en **http://localhost:8000** (solo desde el propio servidor).

### 6.5 La ingesta masiva está montada

```bash
docker compose exec incapacidad-ocr python -m incapacidad_ocr.batch --init
#   -> {"root": "/data/ingesta", "creado": ["1_entrada/whatsapp", ..., "_sistema/control"]}   (11 rutas)

curl -s http://localhost:8000/api/lote/pendientes | python -m json.tool
#   -> {"root","entrada":"1_entrada","archivos","con_nomenclatura","mal_nombrados","casos"}
#   Ejecutado en esta máquina sobre el repo: {"archivos":31,"con_nomenclatura":31,"mal_nombrados":0,"casos":27}

# Corrida EN SECO: lee, agrupa, OCR-ea y valida, pero NO inserta ni mueve (y no exige BD)
docker compose exec incapacidad-ocr python -m incapacidad_ocr.batch --dry-run
```

### 6.6 La corrida programada quedó activa

```bash
curl -s http://localhost:8000/api/lote/estado | python -m json.tool
#   -> {"programado": true, "cron": "0 2 * * *", "tz": "America/Bogota",
#       "proxima_ejecucion": "2026-09-03T02:00:00-05:00", "en_curso": false}
#   "programado": false  =>  INGESTA_CRON vacío: el lote NO corre solo (webapp.py:49).
```

Y después de la primera corrida programada: que los documentos **se movieron** de `1_entrada/` a
`3_archivo/` o `2_revisar/`, y que en `/api/staging?estado=PENDIENTE_REVISION` hay filas nuevas.

### 6.7 Zona horaria, IA y promesa offline

```bash
docker compose exec incapacidad-ocr python -c "from datetime import datetime;print(datetime.now())"
docker compose exec incapacidad-ocr python -m incapacidad_ocr.validacion_temporal   # config efectiva de reglas
docker compose exec ollama ollama list        # solo si se instaló IA: gemma3:4b / qwen2.5vl:3b
```

**Prueba dura de la promesa offline: repetir §6.1 a §6.6 con la NIC del servidor deshabilitada.** Nada
debe fallar (los modelos ONNX viajan dentro del wheel de RapidOCR; se verificó que el paquete no contiene
ninguna URL de descarga).

### 6.8 Pruebas del repo (en el host, fuera de la imagen)

`tests/` **no va dentro de la imagen** (`.dockerignore` lo excluye), así que estas corren en el host con
el venv:

```bash
python tests/test_processor.py          # unitarias deterministas (StubOCR + RapidOCR si está)
python tests/test_ejemplos_reales.py    # precisión sobre los 8 documentos reales de ../Ejemplos
```

Referencia para comparar: **82 %** de los campos núcleo con el stack de Docker (rapidocr 1.4.4) y **76 %**
con el del venv (rapidocr 1.2.3) — este último **re-ejecutado hoy en esta máquina: 34/45 = 76 %**. El
**80 %** que publica el README no corresponde a ninguna de las dos (§9.3).

---

## 7. Límites conocidos y a partir de qué volumen hay que escalar

Ordenados por **a qué volumen se rompen**. Los tres primeros se rompen por **configuración o
probabilidad, no por volumen** — y ese es el punto: **el sistema no se cae por falta de CPU, y ninguno de
estos límites se arregla comprando hardware.** Son la Fase 2 del `PLAN_INGESTA_MASIVA.md`.

| # | Límite | Verificado en | Se rompe a |
|---|---|---|---|
| **L1** | **Tope duro de 500 casos por corrida.** `procesar_todo(..., limite: int = 500)` y `if i >= limite: break`; `webapp._correr_lote` la llama **sin pasar `limite`** y **no hay variable de entorno** para cambiarlo | `batch.py:345`, `batch.py:395`, `webapp.py:66` | **>500 casos en una corrida**. Día medio 350 ✅ · **día pico 875 ✗**: se drenan 500 y **375 se quedan en `1_entrada/`**. Se autocura mientras las llegadas queden bajo 500/día; **deja de autocurarse** por encima de ~10 000/mes o si nadie mira la cola (no hay alerta de backlog). **Es lo primero que se rompe, y a 1,4× del pico supuesto.** *Arreglo: exponer `limite` por env y ponerlo ≥3× el día pico.* |
| **L2** | **El OCR es serial: hoy NO hay pool.** `procesar_todo` es un `for` plano en un solo proceso; el pool es Fase 2 | `batch.py:345-398` | Capacidad de hoy: **1 400-2 100 docs por ventana de 5 h** (§3.3) — **sí cubre el día pico**, y conviene decirlo en claro. Matiz medido: hoy, **sin** el cap de hilos, ese mismo proceso va más rápido en pared (**7,23 s/doc**) pero consumiendo **59,9 CPU-s (8,3 núcleos de media)** → **monopoliza la máquina** aunque procese de a uno, y esa cifra **no se puede multiplicar por workers**. En un servidor de 4 núcleos caerá hacia los 422 docs/h del cap. |
| **L3** | **Ollama en el hot path** | `docker-compose.yml:43` (bien puesto en `rule`) vs UI/`POST /api/lote/procesar` que aceptan `hibrido` | `hibrido` → **74-126 docs/h** → la ventana de 5 h da 371-632 docs, **por debajo del día pico**. `ocr=ollama` (visión) → **15-60 docs/h**. **Un clic del auxiliar cambia el régimen.** *Arreglo: no ofrecer `hibrido` en el lote, o encolar Ollama fuera del hot path (Fase 4).* |
| **L4** | **Sin ledger ni dedup: la doble inserción es una certeza estadística.** `insertar_staging` hace `cx.commit()` **por fila**; el `_mover` posterior **se traga la excepción**. Si el INSERT commitea y el move falla, el archivo se queda en `1_entrada/` **con la fila ya insertada** y la corrida siguiente **inserta otra**. No hay `UNIQUE(caso_id, hash)` | `db.py:62`, `batch.py:211-212` | **No hay umbral: es una probabilidad por archivo.** A 14 700 archivos/mes, un 0,1 % de fallos de move son **~15 casos duplicados/mes**. Vía garantizada además: `restart: unless-stopped` + un reinicio del contenedor a mitad del drenaje. Si el auxiliar aprueba los dos, el ERP promueve **dos ausentismos**. |
| **L5** | **Scheduler in-process + `threading.Lock` + drenaje SÍNCRONO dentro de la petición HTTP** | `webapp.py:53`, `webapp.py:160`, `webapp.py:493` | (a) el lock **solo vale dentro de un proceso**: se rompe el día que alguien añada `--workers N`, una réplica o el `ocr-worker` del plan → N drenajes sobre la misma carpeta; (b) `POST /api/lote/procesar` puede durar **horas** → cualquier proxy corta la conexión (**~300-600 documentos** con timeouts corporativos típicos) y el auxiliar no recibe el resumen; (c) UI y lote comparten el singleton de RapidOCR → latencia interactiva impredecible durante el drenaje. |
| **L6** | **Pico de RAM de UNA página, y ningún límite de memoria en compose** | §3.3; `docker-compose.yml` sin `mem_limit` | **1 documento**. Con 6,5 % de incidencia medida son **~450 documentos/mes** pidiendo 7,6 GB. Sin `mem_limit`, el OOM killer de Linux elige el proceso **más gordo**, que puede ser **MySQL o uvicorn** → se cae la UI y la bandeja, no solo el documento. *Arreglo: `OCR_MAX_PIXELS=8000000` (medido) + `mem_limit` para que un pico sea un reinicio visible.* |
| **L7** | **Una sola conexión MySQL sostenida durante todo el drenaje**, sin keepalive ni statement-timeout (`connection_timeout=5` es de conexión, no de sentencia) | `batch.py:391-393`, `db.py:25-33` | **cualquier reinicio o failover de la BD a mitad del drenaje**: a partir de ahí cada caso restante cae en el `except` genérico y **`_mover(... 2_revisar/con_error/)`** → **cientos de archivos al bucket de error** por un fallo de red de 3 s. La probabilidad crece con la duración del drenaje, y por tanto con el volumen. |
| **L8** | **`MAX_PATH` y número de directorios en el host Windows** | `batch.py:160` (`[:60]`), árbol `3_archivo/<Persona>/AAAA/MM/DD/` | Por longitud de nombre, no por volumen: peor caso **193 chars** con la raíz de esta máquina; el requisito es `len(INGESTA_ROOT) ≤ 115` (§5 paso 8). Recuento de directorios: ~1 hoja por **persona-día** (con 3 000 personas distintas, ~36 000/año, ~180 000 a 5 años): NTFS lo soporta; un antivirus o un backup fichero-a-fichero, no con gracia. |
| **L9** | **`INGESTA_REAPER_TTL` (Fase 2): el suelo lo fija el bundle multipágina.** `read_text` OCR-ea **todas** las páginas y `_combinar_paginas` filtra **después**: un PDF de 12 páginas donde la incapacidad está en la 3 paga **las 12** | `ocr.py:111` | Extrapolado (**el corpus no tiene ni un bundle profundo: todos los multipágina son de 2 páginas**): 30 páginas ≈ **258 CPU-s ≈ 4,3 min**. Un TTL calculado sobre «el peor documento medido» (31 CPU-s) **reencolaría un bundle legítimo a mitad de proceso** → doble inserción. **El TTL debe superar ~5 min con `rule` y ~20 min si puede escalar a Ollama** (`OLLAMA_TIMEOUT=900`). |

**Umbrales de escalado, en una línea cada uno:**

- **>500 casos/día** (día pico ya lo supera): arreglar **L1** — es una variable, no hardware.
- **>1 400-2 100 docs por corrida** (≈ ráfaga grande o backfill): hace falta el **pool de la Fase 2** y con
  él el **cap de hilos ONNX** (hoy **no implementado**: `OMP_NUM_THREADS` **no** lo consigue, porque
  `OrtInferSession` construye `SessionOptions()` sin tocar `intra_op_num_threads` y onnxruntime 1.27 CPU
  usa su propio pool; medido sin cap: **8,67 núcleos por documento para ir solo 1,7× más rápido** ≈ 20 % de
  eficiencia).
- **~10 000 docs/mes sostenidos**: L1 deja de autocurarse y hace falta ledger + dedup (L4).
- **Ollama en el lote** (cualquier volumen): perfil **C con GPU**, o Ollama fuera del hot path.
- **>1 instancia / `--workers >1`**: mover el lock a la BD (`GET_LOCK`) antes, o habrá doble drenaje (L5).

---

## 8. Preguntas abiertas para el cliente

Bloquean el cierre del dimensionamiento y de la decisión de SO. Todas son concretas y de una frase.

**Volumen y datos** (deciden CPU y disco)

1. **¿Los 7 000 al mes son trámites (casos) o archivos?** (S5: si son archivos, la CPU se parte por 2.)
2. **¿Cuántos documentos trae en promedio un trámite además de la incapacidad, y cuánto pesa una
   epicrisis escaneada?** (S2/S9: mueve el disco a 5 años entre **186 y 648 GB**.)
3. **¿Nos pasan el conteo de radicados por día de la semana de un mes cualquiera?** (S8: el factor de pico
   de 2,5× es hoy un supuesto.)
4. **¿Cuántos empleados distintos generan esos 7 000 trámites al mes?** (Decide el número de directorios
   hoja del árbol y con ello el coste del backup y del antivirus — L8.)
5. **¿Hay que cargar histórico (backfill) y de cuántos meses?** (Un año son **199-222 CPU-h**: 8,3 días con
   1 worker, 50 h con 4.)

**Legal y operación**

6. **Jurídico: ¿cuántos años hay que conservar el ORIGINAL del soporte?** (S4: decide entre 250 GB y 1 TB.
   `PLAN_INGESTA_MASIVA.md` §9.4 ya lo deja «a confirmar con jurídico».)
7. **¿Existe una política de respaldo ON-PREMISE?** Un respaldo en la nube **rompe** la restricción «nada
   sale a internet» y es el escenario de fuga de PII más probable del diseño.
8. **¿A qué hora empieza el auxiliar a revisar la bandeja?** (S10: define la ventana de drenaje; hoy se
   asume 02:00-07:00.)
9. **¿Se acepta que el lote use SOLO reglas y que el auxiliar suba a IA los casos difíciles a mano?**
   (S3: si no, hace falta GPU. Y en particular: **¿qué porcentaje del volumen son permisos manuscritos**,
   que RapidOCR lee muy mal y exigen visión?)

**Servidor y TI**

10. **¿Linux o Windows Server, y quién administra ese servidor?** (Precondición «P2», abierta desde el
    plan. Si hay licencias de Windows ociosas y cero administración Linux, el coste de personal puede
    invertir la recomendación; si no, Linux es estrictamente más barato: SO 0 + Docker CE 0.)
11. **¿El servidor tendrá TPM (o vTPM si es virtual)?** Sin él **no se puede tener cifrado en reposo y
    reboot desatendido a la vez**. Es un requisito de compra.
12. **¿Se permite virtualización (Hyper-V) en la política de TI?** Si no, la única contingencia Windows es
    W3 (nativo sin Docker), que duplica la superficie de despliegue.
13. **¿Dónde vive la BD ASTGU (mismo host, misma LAN, remota)?** La latencia de MySQL **no se midió**; con
    la BD remota y N workers puede dejar de ser despreciable.
14. **¿Quién queda en el grupo `docker` del servidor?** Es equivalente a root sobre toda la PII: es una
    lista que hay que aprobar, no heredar.
15. **¿Se acepta que la UI quede accesible SOLO desde el propio servidor?** Hoy escucha en
    `127.0.0.1:8000`; abrirla a la LAN exige reverse-proxy + TLS + autenticación, que **no están en el
    repo**.

---

## 9. Contradicciones resueltas (qué se descartó y por qué)

1. **Perfiles de hardware: `INSTALACION_CLIENTE.md` §2 («4 núcleos / 16 GB / 250 GB», 6,3 GB/mes) vs §1 de
   este documento («8 / 16 / 500»).** Se **conserva §1**. Las dos diferencias tienen causa: (a) el disco de
   aquel documento asume **2,5 archivos/trámite** (de ahí 379 GB a 5 años) mientras la mezcla derivada de
   `erp.REQUISITOS_DEFAULT` da **1,0 adjunto obligatorio** → 2,1 archivos/trámite y **324 GB**; los 250 GB
   solo cubren ~3 años, así que quedan como **perfil mínimo**, no recomendado. (b) Los 4 núcleos son
   correctos **para el código de hoy** (serial); los 8 del perfil B compran el pool de la Fase 2 y el
   backfill. `INSTALACION_CLIENTE.md` sigue siendo válido como resumen ejecutivo, pero sus cifras hay que
   leerlas contra esta tabla.
2. **Archivos movidos/mes: 11 000 (01/04, «7 000 × ~1,6») vs 14 700 (03, «7 000 × 2 × 1,05»).** Se adopta
   **14 700**: el 1,6 es un redondeo, mientras el 2,1 se deriva de los requisitos por tipo del repo y
   añade explícitamente el 5 % de reenvíos recomprimidos por WhatsApp (que llegan con **hash distinto** y
   hoy **no se deduplican**). Consecuencia: 5,4 GB/mes en vez de 3,8-3,9 GB/mes. Para disco, la cifra
   conservadora es la correcta.
3. **Precisión: 80 % (`README.md`, `CONTEXT.md` §5.1) vs 76 % (venv) vs 82 % (Docker).** Se descarta el
   80 %: no corresponde a ninguna configuración real. La diferencia 76/82 es la versión de
   `rapidocr-onnxruntime` (1.2.3 vs 1.4.4) que pip elige **según la versión de Python** (§2.2). El 76 % se
   **re-ejecutó hoy** en este venv (`tests/test_ejemplos_reales.py` → **34/45**, con rapidocr **1.2.3** y
   Python **3.14.5**, versiones verificadas con `importlib.metadata`). El 82 % de la rama Docker sigue
   siendo la medición de `01_software.md` §1.3 (rapidocr 1.4.4 forzada), **no re-verificada aquí**.
4. **Tamaño de `site-packages`: 364 MB (01, «venv Windows limpio») vs 430 MB (03) vs 476 MB (linux/cp312).**
   Todas son correctas y miden cosas distintas: **medido ahora, este venv = 430 MB**, de los cuales
   **PyMuPDF son 54 MB** (más `fpdf2`+`fonttools` y `psutil`, que no están en el `requirements.txt` de la
   app). Los 364 MB son un venv limpio **anterior** a que `PyMuPDF` se declarara; los 476 MB son la
   resolución de Linux/cp312, que trae wheels distintos.
5. **Inventario de dependencias de `01_software.md` §1.1/§1.2:** está **desactualizado por una hora**. Hoy
   `requirements.txt` **sí declara** `PyMuPDF>=1.24` (lo usa `authenticity.py:168,348` de forma perezosa;
   sin él, la señal de fuentes PDF degrada a `sospechosa: false` con `omitido: "PyMuPDF no instalado"`).
   Siguen sin declarar **`numpy`** (usado en `ocr.py:99` y `authenticity.py:280`) y **`fpdf2`**
   (`scripts/guia_a_pdf.py:14`) → **se añaden en este cambio**. `psutil` **no** se añade: no lo importa
   ningún archivo del repo (solo lo necesita `bench_ocr.py`, que vive fuera).
6. **Números de sección del plan.** El **dimensionamiento** está en `PLAN_INGESTA_MASIVA.md` **§6.6** (no
   §10) y los **riesgos** en **§11** (no §9); §9 es «Robustez, errores, configuración, seguridad/PII,
   observabilidad» y §10 es el plan por fases. El **arranque programado** sí es §5.
7. **Líneas de código citadas en los informes previos** (por deriva del archivo): `INGESTA_ROOT` está en
   **`batch.py:39`** (no 33 ni 38), `procesar_todo(..., limite=500)` en **345** con el corte en **395** (no
   344/376-378), y `sql/init.sql` pesa **13,5 KB** (no 10 KB). Las de este documento se verificaron hoy.
8. **`PLAN_INGESTA_MASIVA.md` §6.6 es ~3× optimista.** Dice «~2-4 s/doc/core» y «6 workers → ~1,5-2 docs/s
   → 6-7 k docs/hora; 7 000/mes en ~1 h». Medido: **9,53 CPU-s/doc** → 6 workers = **0,63 docs/s ≈ 2 270
   docs/h**, 7 000/mes ≈ **3,1 h**, ráfaga de 1 500 ≈ **40 min**. Su **conclusión** (el volumen cabe de
   sobra en una ventana nocturna) **se sostiene**; sus **números** no. También corrige su fórmula
   `W = min(cores − 1, floor(RAM_libre_GB / 1.0))`: debe ser **`cores − 2`** (uvicorn + SO; −3 con MySQL y
   Ollama locales) y **`RAM_libre_GB / 1.6`**.
9. **`PLAN_INGESTA_MASIVA.md` §6.8 atribuye el pico de RAM a «un bundle grande materializado entero» y lo
   resuelve con streaming.** El streaming **ya está** (`preprocess.load_pages` es un generador) y **no
   ayuda**: el pico lo produce **UNA SOLA página** con la caja sobredimensionada (§3.3).
10. **`PLAN_INGESTA_MASIVA.md` §9.3 dice que `INGESTA_CRON` tiene default `0 2 * * *`.** El código usa
    **default vacío = desactivado** (`webapp.py:49`, y el compose pasa `${INGESTA_CRON:-}`). Aquí el
    **README está bien y el plan está mal**.
11. **`PLAN_INGESTA_MASIVA.md` §9.2 («reintentos con backoff ante `WinError 32`»)** se mantiene como seguro
    barato, pero **no compensa un problema medido**: 300 ciclos de «escribir 300 KB + `os.replace`
    inmediato» con Defender en tiempo real activo dieron **0 fallos** (p50 0,75 ms).
12. **Riesgo #19 del plan (MAX_PATH) baja de «riesgo» a «verificación de instalación de una línea»**
    (`len(INGESTA_ROOT) ≤ 115`, §5 paso 8), y los nombres cortos `NN_<tipo>` que proponía **no hacen
    falta**.
13. **`CONTEXT.md` §9 (tabla de seguridad) está desactualizado:** dice `MAX_PDF_PAGES=20` e
    `Image.MAX_IMAGE_PIXELS=64M`; el código usa **30** y **200 000 000** (`preprocess.py:25,32`). El README
    está correcto. También, `CONTEXT.md` §5.2 dice «i7-1255U **sin GPU**»: la máquina **sí** tiene GPU
    (Iris Xe); lo correcto es que **no se aprovecha**, porque el build de onnxruntime es solo-CPU.
14. **Comentario de `preprocess.py:27-28` («una A4 a escala 3.0 ≈ 8,7 MP») está 2× mal:**
    `PDF_RENDER_SCALE=3.0` en PDFium = 3 × 72 = **216 DPI** → A4 = 1 786 × 2 526 px = **4,51 MP**, que es
    exactamente lo medido en 30 de los 35 documentos (4,4-4,5 MP). Los 8,7 MP son 300 DPI. La conclusión
    del comentario no cambia; el número sí.
15. **`README.md` §Seguridad («cada página se acota a `OCR_MAX_PIXELS` (40 MP) para no disparar la RAM»)**
    describe un guardarraíl que, **con su valor por defecto, no guarda** (§3.3). El mecanismo está bien; el
    default está mal.
