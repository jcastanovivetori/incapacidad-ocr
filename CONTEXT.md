# CONTEXT — incapacidad-ocr (fuente única de contexto)

**Última actualización:** 2026-09-01 · **Estado:** PoC funcional con soporte PDF, servicio web + UI dockerizado, evaluado sobre incapacidades reales (§5.1), Ollama (IA local) para casos difíciles (§5.2), integración a BD/staging (§5.4), **flujo de revisión humana — completar/aprobar/rechazar** (§5.5), **ingesta masiva por lotes (carpetas + nomenclatura) con corrida programada** (§5.6) y **estructura de ingesta en tres zonas numeradas** (§5.7).

Este documento es el **contexto completo** del proyecto: por qué existe, qué se construyó, cómo se probó y cómo encaja en la plataforma de nómina. Para *cómo usarlo* → [`README.md`](README.md); para *cómo trabajar el repo* → [`CLAUDE.md`](CLAUDE.md).

---

## 1. Origen y objetivo

**Necesidad:** una lógica que **traduzca incapacidades médicas (imágenes/escaneos) a texto plano** y de ahí a datos estructurados, para alimentar nómina **sin digitación manual** (el cliente Gruppo recibe ~7000 incapacidades/mes por WhatsApp y correo, de ~20 EPS con formatos distintos).

**Objetivo de este repo:** una versión **limpia, local y funcional** de un pipeline de **dos pasos** — imagen → texto plano → JSON — **adaptado a incapacidades (Colombia)**, sin API paga, que además **mapea el resultado a una tabla staging del ERP** para que un auxiliar revise y apruebe.

### Enfoque base (patrón de dos pasos)

El patrón es estándar para documentos: (1) un motor de **OCR/visión** transcribe TODO el texto de la imagen → texto plano; (2) un **extractor** (reglas o LLM) lo estructura a JSON. Aquí ambos pasos corren **100% local** (RapidOCR/ONNX o un modelo de visión en Ollama para el paso 1; regex o un LLM local para el paso 2) — sin SDK de OpenAI/Gemini/Anthropic ni APIs de pago. La salida JSON se mapea luego a la fila de staging del ERP (§5.4).

---

## 3. Qué se construyó

Proyecto Python limpio (`incapacidad_ocr/`) que separa **imagen→texto** (OCR) de **texto→JSON** (extractor), ambos **pluggables**:

```
imagen ──► [OCR backend] ──► texto plano ──► [extractor] ──► JSON incapacidad
           rapidocr / ollama-vision          rule-based / ollama-llm
```

| Componente | Archivo | Opciones |
|---|---|---|
| Preprocesado | `preprocess.py` | carga imagen/PDF, **PDF→imágenes (PDFium)**, resize ≤1600px, PNG→base64 |
| OCR (imagen/PDF→texto) | `ocr.py` | `RapidOCRBackend` (ONNX/CPU local, **acepta PDF multipágina**) · `OllamaVisionOCR` (visión local) · `StubOCR` (pruebas) |
| Extractor (texto→JSON) | `extract.py` | `RuleBasedExtractor` (regex, determinista) · `OllamaLLMExtractor` (LLM local) · `HybridExtractor` (reglas+LLM fusionados) · `normalizar_fechas()` (regla de fecha de inicio) |
| Orquestador | `processor.py` | `process()` / `IncapacidadProcessor` (OCR + extractor + reconciliación de fechas) |
| **Mapeo ERP** | `erp.py` | `mapear_a_staging()` (lookups + homologación + `overrides` manuales + `campos_faltantes`), `Lookups` (cédula/CIE/EPS + nombre canónico del catálogo) |
| **BD (MySQL/ASTGU)** | `db.py` + `sql/init.sql` | INSERT/UPDATE en `lp_ausentismos_ia`; flujo `PENDIENTE_REVISION`/`APROBADO`/`RECHAZADO` |
| CLI | `cli.py` | `python -m incapacidad_ocr.cli foto.jpg [--ocr ollama --extractor ollama]` |
| **Servicio web** | `webapp.py` + `static/index.html` | API FastAPI (`/api/procesar`, `/api/mapear`, `/api/registrar`, `/api/revisar`, `/api/staging`) + UI moderna (drag&drop, **formulario de revisión editable**, **bandeja** aprobar/rechazar). RapidOCR cargado una vez; uploads procesados en temporal y **borrados** (PII). |
| **Docker** | `Dockerfile` · `docker-compose.yml` | `docker compose up --build` → `http://localhost:8000`. 3 servicios (web + ollama + db). Instala todo desde `requirements.txt`. |

**Esquema de salida** (incapacidad Colombia): `paciente{nombre, documento_tipo, documento_numero}`, `entidad{eps, ips_prestador}`, `incapacidad{fecha_inicio, fecha_fin, dias, dias_letra, dias_letra_coincide, fecha_expedicion, tipo, origen}`, `diagnostico{cie10, descripcion}`, `medico{nombre, registro}`. Los dos campos de letras son **instrumentación** de la duración escrita en palabras (ver §5.8): `dias` es el valor a usar, `dias_letra` lo que decía la palabra y `dias_letra_coincide` si cuadran (`null` si el documento solo trae una de las dos formas). `normalizar_fechas()` añade además los avisos `fecha_inicio_calculada` y `fecha_fin_recalculada`.

---

## 4. Decisiones de diseño

- **D1 — Todo local, sin API paga.** OCR con RapidOCR (ONNX/CPU) o modelo de visión en Ollama; estructuración con regex o LLM local. Motivo: costo $0 + **PII sensible (Ley 1581)** no debe salir a terceros.
- **D2 — Dos backends de OCR.** `RapidOCR` para correr ya en cualquier PC (sin instalar Ollama); `Ollama-visión` para imágenes difíciles (manuscritos/sellos) con modelos más fuertes.
- **D3 — Dos estrategias de estructuración.** `RuleBasedExtractor` (determinista, reproducible, ideal para impreso y para tests) y `OllamaLLMExtractor` (tolerante a ruido). Se elige por la calidad del documento.
- **D4 — Imports perezosos** de `httpx`/`rapidocr` → el módulo es importable y testeable aunque falte una dependencia.
- **D5 — Normalización de CIE-10 robusta a OCR** (ver §5): el OCR confunde `0↔O`, `1↔I/l` en códigos; se normaliza solo la parte numérica anclada al contexto "Diagnóstico".

---

## 5. Evidencia de pruebas (ejecutadas localmente)

Entorno: Windows, **Python 3.14**, venv con **RapidOCR** (onnxruntime 1.27 + opencv 4.13, wheels cp314 OK) y **pypdfium2 5.x** (render de PDF).

`python tests/test_processor.py` → **EXIT=0, TODO OK**:
- `[1]` Extractor por reglas sobre texto canónico → **14/14 campos correctos**.
- `[2]` `parse_json_response` (limpia ```json``` + rescata objeto embebido).
- `[3]` Preprocesado (genera imagen sintética + resize + base64).
- `[4]` End-to-end con `StubOCR` (pipeline completo determinista).
- `[5]` **OCR REAL (RapidOCR)** sobre imagen sintética → texto correcto → JSON correcto.

**Hallazgo de la prueba (real):** RapidOCR leyó el código `J06.9` como **`Jo6.9`** (confusión `0→o`). El test lo detectó (no se aflojó); se corrigió el extractor con `_normalize_cie10` (`O/o→0`, `I/l→1`, `,→.`). Resultado: `cie10 = J06.9` correcto.

Imagen de prueba: `tests/make_sample.py` genera `tests/sample_incapacidad.png` (no se commitea; ver `.gitignore`).

### 5.1 Evaluación sobre incapacidades REALES (`Ejemplos/`, 2026-06-16)

Se procesaron los **8 documentos reales** de la carpeta `Ejemplos/` (6 PDF + 2 JPEG, de 8 EPS/IPS distintas: Famisanar, Salud Total, Nueva EPS, Sura, Seguros del Estado, Salud Mía, Colpatria, FOSCAL) con el pipeline **PDF/imagen → RapidOCR → RuleBasedExtractor** (100% local, sin Ollama). Ground-truth y script: `tests/test_ejemplos_reales.py`.

**Precisión campos núcleo: 36/45 = 80%** *(medido el 2026-06-16 con las versiones de entonces; re-ejecutado el 2026-09-02 en el venv actual da 34/45 = 76% porque Python 3.14 arrastra `rapidocr` 1.2.3 — el stack de Docker con Python 3.12 y `rapidocr` 1.4.4 midió 82%)*. Por campo:

| Campo | Acierto | Notas |
|---|---|---|
| `cie10` | **7/7** | Códigos pegados sin punto (`S42O`→`S42.0`, `M544`, `K429`, `A099`, `J399`, `R074`) normalizados; el 8º doc no trae código en el OCR. |
| `documento_numero` | **7/8** | Patrón `CC/TI/CE<num>` evitando el NIT del proveedor/empleador; el fallo (FOSCAL) no trae rótulo de tipo en el OCR. |
| `fecha_inicio` / `fecha_fin` | 6/8 c/u | 3 formatos (`dd/mm/yyyy`, `yyyy-mm-dd`, `10-jun-26`); rótulo→valor incluso en la línea siguiente o anterior. |
| `dias` | 6/8 | Etiqueta o **cálculo inclusivo desde las fechas** (respaldo fiable). |
| `origen` | 4/6 | `Comun`/`Laboral`/`Enfermedad general`. |

**Hallazgos clave:** el OCR de formularios reales sale **desordenado** (no línea a línea como la muestra sintética) y cada EPS usa **rótulos distintos**; el `RuleBasedExtractor` original (ajustado a la muestra) caía a ~30%. Tras endurecer las reglas sobre datos reales subió a 80%. Los **9 fallos restantes se concentran en 2 fotos** con OCR muy degradado (rótulos mal leídos: `Iniclal`, `Focha`; texto muy disperso) → es justo el caso para **Ollama-visión + `OllamaLLMExtractor`** (D3). Nombres de paciente/médico salen a veces **pegados** (sin espacios) por el OCR: legibles pero no perfectos.

### 5.2 Ollama habilitado (IA local en Docker, 2026-06-17)

Se añadió un contenedor **`ollama`** al `docker-compose.yml` (volumen persistente, red interna; el web lo alcanza vía `OLLAMA_URL=http://ollama:11434`). Modelo: **`gemma3:4b`** como `OllamaLLMExtractor` (texto→JSON). Entorno: i7-1255U, **sin GPU → inferencia CPU** (1ª petición ~1 min al cargar el modelo, luego más rápida). El `OllamaLLMExtractor` ahora fuerza `format:"json"` y **normaliza el CIE-10** que devuelve el LLM (`M544`→`M54.4`).

**Combo recomendado para casos difíciles: RapidOCR (imagen→texto) + Ollama-LLM (texto→JSON).** Comparado con reglas en las 2 fotos degradadas:

| Doc | Campo | Reglas | Ollama-LLM |
|---|---|---|---|
| FOSCAL | documento | ❌ (sin rótulo "CC") | ✅ `1098757631` |
| FOSCAL | nombre / eps / origen / fecha_inicio | ❌ / "FOSCAL" / ❌ / ❌ | ✅ YARITZA / SEGUROS COLPATRIA ARL / Accidente de Trabajo / 2026-06-10 |
| Nueva EPS | nombre / médico / eps | basura | ✅ JAIDER SEBASTIAN HERNANDEZ ARDILA / CARVALHO MARTINS… / NUEVA EPS |

**El LLM recupera campos que las reglas no pueden** (documento sin rótulo, nombre/EPS en texto disperso). **Limitaciones observadas (CPU + modelo 4B):** alucina fechas a partir de números de contrato (Nueva EPS: `fecha_inicio` errónea), y si el OCR destroza el nombre del paciente puede tomar el del médico (CESAR). → Para producción: revisión humana, y/o subir a un modelo de visión fuerte (`qwen2.5vl`, `llama3.2-vision`) y/o GPU. El path queda **configurado y probado**; la elección reglas-vs-LLM es por documento (impreso limpio → reglas; ruidoso/sin rótulos → LLM).

**Sobre el motor OCR de visión:** `moondream` **no sirve** para OCR (es *captioning*/VQA: devuelve texto vacío al pedirle transcripción). Se reemplazó por **`qwen2.5vl:3b`** (VLM multilingüe que sí transcribe). Con él, el flujo **Ollama visión + Ollama-LLM funciona con imágenes y PDF** (2026-06-17):

- **PDF** (Salud Total): nombre `LEONARDO GARNICA REYES` (con espacios, mejor que RapidOCR), doc `13742111`, EPS `SALUD TOTAL EPS-S.A.`, inicio `2026-06-09`, fin `2026-06-23`, días `15`, CIE `K42.9` → **todos correctos**.
- **Imagen** (FOSCAL, caso difícil): texto OCR limpio; fechas `2026-06-10`/`2026-06-12` y origen `LABORAL` correctos; nombre aproximado (`YABITZA`≈YARITZA); doc/EPS/CIE imperfectos (límite de modelos 3B/4B).
- **Velocidad (CPU, sin GPU):** ~1-2 min por imagen y ~4 min por PDF (render + visión + LLM). El timeout del servidor se subió a `OLLAMA_TIMEOUT=900s`; la imagen se reescala a `VISION_MAX_DIM=1200px` para acelerar.

Optimizaciones de código: `OllamaVisionOCR` usa `/api/chat` con imagen reescalada y timeout amplio; el modelo de visión se fija por env `OCR_MODEL=qwen2.5vl:3b`.

### 5.3 Extractor HÍBRIDO (reglas + LLM) — el recomendado (2026-06-17)

Observación de uso: para varios documentos (p.ej. `incapacidad___.jpeg`) **RapidOCR lee bien y es rápido**, mientras la visión por IA es lenta y no aporta. La mejor estrategia no es "uno u otro" sino **fusionar** sobre el texto rápido de RapidOCR: nace `HybridExtractor` (`extract=hibrido`, ahora **default** en la UI).

**Política de fusión** (`_merge_records`): documento ← reglas; nombre/EPS/CIE-10/origen/descripción ← LLM (contexto); **fechas ← LLM con anclaje y reglas de respaldo**. Guardas anti-error:
- **Anclaje de fechas:** una fecha solo se acepta si **aparece en el texto OCR** → mata las fechas que el LLM inventa (vimos `2023-02-01`/`2026-02-01`).
- **Rango válido** (0–540 días) y **recálculo de `dias`** desde el rango.
- **Derivación anclada:** si falta una fecha, se deriva de `dias` + la otra y se acepta solo si está en el texto.
- **`origen` saneado** a valores conocidos (descarta códigos/basura del LLM).
- **CIE-10** exige ≥1 dígito real → mata falsos positivos de puras letras (`FOSCAL`→F05).
- **Degradación elegante:** si Ollama no responde, el híbrido usa solo reglas.

**Resultado (RapidOCR + Híbrido, 8 docs reales):** mayoría con **6/6 campos núcleo** (ALEJANDRO, MICHAEL, Salud Total, Suramericana); los casos antes problemáticos quedan sin alucinaciones ni basura (`incapacidad___`: doc/nombre/EPS/CIE/fin/días correctos, inicio `None` honesto porque el OCR no lo leyó; FOSCAL: todo bien y CIE `None` correcto). Rápido (~RapidOCR + 1 llamada LLM ~20-40s), sin necesidad de la visión lenta.

**Corrección de seguridad asociada:** si el OCR devuelve texto vacío/ilegible (`< MIN_OCR_CHARS`), el orquestador **NO llama al extractor** y devuelve registro vacío + `aviso` — antes el `OllamaLLMExtractor` **fabricaba** un registro completo (PII médica inventada) a partir de texto vacío. Si falta el modelo en Ollama la API responde **503 con mensaje accionable** (qué `ollama pull` ejecutar), no un 500 genérico.

### 5.4 Integración al ERP — tabla STAGING `lp_ausentismos_ia` (2026-06-18)

Para cerrar la brecha con lo que pide el cliente (extraer → **insertar en BD** → el auxiliar aprueba), se añadió la capa de integración al ERP:

- **`erp.py`** — homologación de tipo (texto → `2/3/5/8/9/10/11`, default 3), **lookups** cédula→`idlpempleado` · CIE-10→`idlpdiagnosticos` (sin punto) · EPS→`idlpentidad` (match por contención), estado de recepción (1/2/3), `fecharegistro=hoy`, `fechavencimiento=inicio+días`, y `mapear_a_staging()` que arma la fila + lista `problemas`/`requiere_revision`. Degrada a `LookupsNulos` sin BD.
- **`db.py`** — conexión MySQL por env (`DB_*`) + `insertar_staging()` + `listar_staging()`.
- **`sql/init.sql`** — catálogos mínimos + `lp_ausentismos_ia` (mismos nombres de columna del ERP) + `lp_alertas_documentacion` + **datos de prueba que coinciden con `../Ejemplos`** (cédulas, CIE, EPS) para que los lookups resuelvan en la demo.
- **Web/UI** — `POST /api/procesar` incluye `staging` (preview, no inserta); `POST /api/registrar` hace el **INSERT**; `GET /api/staging` lista lo pendiente. La UI tiene selector de **recepción** y la sección **«Registro ERP»** (los IDs resueltos + problemas).
- **Compose** — servicio `db` (mysql:8) que carga `sql/init.sql` al primer arranque.

**Decisión clave respetada:** NO se inserta en `lpausentismos`; se escribe en **staging** y el ERP promueve al aprobar (preserva división de novedades, validación de cotización, etc.). Pendiente para producción: apuntar a la BD ASTGU real (catálogos reales de empleados/CIE/EPS), `numero_orden`, score de confianza OCR real, y el envío de alertas documentales.

### 5.5 Revisión humana + reglas de fecha/nombre (2026-06-22)

Sobre la base de §5.4 se cerró el **flujo de revisión humana** y se afinaron tres reglas pedidas por el cliente:

1. **Fecha de inicio.** El extractor por reglas reconoce el layout `Dias Fecha Inicia` (formularios tipo AM-Sistemas) donde el nº de días viene **pegado** a la fecha (`5 11/06/2026`) y **ancla** esa fecha como inicio. Si no hay fecha de inicio rotulada, se aplica la **regla de respaldo**: `inicio = fin − (días − 1)`, marcando el campo como **calculado** (aviso no bloqueante en la UI). Toda la reconciliación de fechas/días vive en `extract.normalizar_fechas()` (corre para todos los extractores) y se reaplica al corregir días/fin a mano. *Verificado:* `incapacidad.jpeg` pasó de `inicio/días = None` a `inicio 2026-06-11, fin 2026-06-15, días 5` correctos, incluso en modo solo-reglas.
2. **Campos obligatorios faltantes → revisión humana.** `mapear_a_staging()` devuelve `campos_faltantes` (estructurado) además de `problemas`. La UI muestra un **formulario editable** con los obligatorios (cédula, paciente, CIE-10, EPS, fecha inicio, días, tipo) resaltando los que faltan; el auxiliar los completa, pulsa **«Recalcular IDs»** (`POST /api/mapear`, re-resuelve lookups sin escribir en BD) y luego **Aprobar** / **Guardar para revisión** / **Rechazar**. Estados del flujo: `PENDIENTE_REVISION` / `APROBADO` / `RECHAZADO` (no se aprueba con obligatorios faltantes → 409). La **«Bandeja de revisión»** lista por estado y permite aprobar/rechazar (`POST /api/revisar`); `GET /api/staging/{id}` trae uno.
3. **Nombres pegados por el OCR.** Cuando la cédula resuelve, el **nombre del catálogo es autoritativo** → `ALIX HERNANDEZSANDOVAL` se corrige a `ALIX HERNANDEZ SANDOVAL`. Como respaldo genérico (médicos / sin match), `extract._split_glued_name()` separa tokens largos con un léxico de nombres/apellidos frecuentes (word-break por DP). Si la cédula no resuelve, se intenta recuperar `idlpempleado` **por nombre**.

Nuevos endpoints: `POST /api/mapear` (preview con correcciones), `POST /api/revisar` (aprobar/rechazar/guardar), `GET /api/staging/{id}`; `POST /api/registrar` acepta `campos` (overrides) y `estado`.

### 5.6 Ingesta masiva por lotes + corrida programada (2026-07-23)

Para procesar **volumen** (no de a un documento), se añadió un **runner por lotes** que toma los documentos de una estructura de carpetas y los registra en staging para revisión. Diseño técnico completo en [`PLAN_INGESTA_MASIVA.md`](PLAN_INGESTA_MASIVA.md).

- **Nomenclatura de archivos (contrato de entrada).** Los documentos llegan **separados** (uno por archivo), nombrados `cedula_TIPODOC[_NN].ext` — **sin fecha** (más simple para quien nombra los soportes; la fecha se toma del OCR del documento). La **llave de caso** es la **cédula** (agrupa el trámite); `TIPODOC` base (único que se OCR-ea) = `INCAPACIDAD`/`PERMISO`/`VACACIONES`, y los adjuntos (`FURAT`/`FURIPS`/`EPICRISIS`/`HISTORIA`/`NACIDOVIVO`/`REGISTROCIVIL`/…) **solo se verifican por nombre**. RH puede estructurar `1_entrada/` en subcarpetas (escaneo recursivo).
- **`batch.py`** — escanea `INGESTA_ROOT/1_entrada`, agrupa por nomenclatura, **OCR solo del documento base** (de ahí sale el tipo de ausentismo), **valida los soportes requeridos según el tipo** (`erp.validar_documentacion`: `lprequisitos_eps` o `REQUISITOS_DEFAULT`, con **grupos de equivalencia** — p.ej. epicrisis satisface "historia clínica"), inserta en `lp_ausentismos_ia` (`PENDIENTE_REVISION`), crea **alerta** (`lp_alertas_documentacion`) si falta un soporte, y **mueve** los archivos a la zona que corresponda (§5.7), organizados por **`<Nombre persona>/AAAA/MM/DD`** (nombre = primer nombre + primer apellido del catálogo; fecha = inicio de la incapacidad), para que RH revise el historial de un empleado fácilmente. Permisos y vacaciones no exigen incapacidad; el cotejo cédula-nombre↔OCR marca `requiere_revision` ante discrepancia; nunca se cruzan cédulas distintas.
- **Documentos pesados** — el PDF se rasteriza **página a página en streaming** (`preprocess.load_pages` es generador → una página en RAM), con topes configurables (`MAX_UPLOAD_BYTES=50MB`, `MAX_PDF_PAGES`, `OCR_MAX_PIXELS`, `MAX_IMAGE_PIXELS`, `PDF_RENDER_SCALE`).
- **UI + API** — panel **«Procesar todos»** + `POST /api/lote/procesar`, `GET /api/lote/pendientes`, `GET /api/lote/estado`. La carpeta `ingesta/` es un **bind mount** (`./ingesta:/data/ingesta`); sus documentos **no** se versionan (PII, Ley 1581), solo la estructura. El escenario de demo se reproduce con `python scripts/sembrar_demo.py` (5 casos: enf. general, accidente+FURAT, vacaciones, permiso + 1 sin nomenclatura).
- **Corrida programada** — scheduler **in-process** (APScheduler) dentro del contenedor web, activado por `INGESTA_CRON` (vacío = desactivado; p.ej. `0 2 * * *`). Comparte un **lock** con la corrida manual (no se solapan). **Depende de que el servicio esté levantado** (el contenedor sube solo con `restart: unless-stopped` mientras Docker arranque en el boot: `systemctl enable docker` en Linux / Docker Engine como servicio en Windows Server). Para un servidor **Windows headless** sin login, la alternativa robusta es el Programador de tareas del SO disparando `docker compose exec … batch --once` (modo B del plan §5, no implementado por ahora).

### 5.7 Estructura de la carpeta de ingesta: tres zonas numeradas (2026-09-01)

La estructura original (`inbox/` · `procesados/` · `incompletos/` · `cuarentena/` · `logs/`, todo plano en la raíz) resultó **ambigua de leer**: mezclaba entrada, salida, excepciones e internos al mismo nivel; el bucket de descarte (`sin_nomenclatura/`) vivía **dentro** del `inbox/` (una carpeta de entrada); el historial de una persona quedaba **partido** entre `procesados/` e `incompletos/`; y la Fase 2 del plan añadía 5 carpetas más a la raíz. Se reorganizó en **tres zonas numeradas que se leen en el orden del flujo**, más un área interna:

```
ingesta/
├── 1_entrada/{whatsapp,correo,ventanilla}/   # lo ÚNICO que se escribe a mano (contrato de entrada)
├── 2_revisar/                                # TODO lo que necesita acción humana, junto
│   ├── mal_nombrados/                        #   no cumplen la nomenclatura → renombrar y reingresar
│   ├── faltan_soportes/<Persona>/<AAAA>/<MM>/<DD>/     #   falta un soporte → alerta
│   ├── datos_por_revisar/<Persona>/<AAAA>/<MM>/<DD>/   #   soportes OK, el dato necesita revisión
│   └── con_error/<caso>/                     #   fallo técnico
├── 3_archivo/<Persona>/<AAAA>/<MM>/<DD>/     # historial de los casos COMPLETOS
└── _sistema/{logs,tmp,control}/              # interno del runner (tmp/control son de la Fase 2)
```

- **Una sub-carpeta por MOTIVO en `2_revisar/`:** la carpeta explica por qué el caso está ahí y qué hacer — `faltan_soportes` (hay que pedir un documento) es distinto de `datos_por_revisar` (los soportes están completos, pero el OCR/los lookups dejaron `problemas` que el auxiliar debe confirmar). Mezclarlos era el defecto de la primera versión de este cambio.
- **Invariante de diseño:** cada archivo termina en **exactamente una** zona → «¿dónde quedó este documento?» tiene una sola respuesta, y «¿qué me falta hacer?» es literalmente el contenido de `2_revisar/`.
- **Decisión (nombres de archivo):** al mover a la salida se **conserva el nombre original** (`13742111_INCAPACIDAD.pdf`) en vez del renombrado sin PII `NN_<tipo>.<ext>` que planteaba el plan §4.4. Se priorizó la **trazabilidad** contra lo que envió el punto de recepción; el trade-off es que la cédula queda en el nombre del archivo (el **directorio** no la lleva, y el volumen es local con ACL/cifrado — Ley 1581). Queda registrado como desvío consciente del plan.
- **Compatibilidad:** `scripts/migrar_estructura_ingesta.py` migra un árbol viejo conservando las sub-rutas (idempotente, no sobre-escribe), y el runner **sigue leyendo** un `inbox/` antiguo si existe para no dejar documentos huérfanos. El árbol se crea con `asegurar_estructura()` / `python -m incapacidad_ocr.batch --init`.
- **Documentación:** el árbol se explica **dentro de la propia carpeta** (`ingesta/LEEME.md`, dirigido a RH: qué es cada zona y qué hacer con lo que aparece en `2_revisar/`), y las claves del resumen del lote se renombraron para hablar el mismo vocabulario: `completos` / `faltan_soportes` / `datos_por_revisar` / `con_error` / `mal_nombrados`.

---

### 5.8 Duración en NÚMEROS y en LETRAS — `numeros_es.py` (2026-09-02)

**Qué pidió el cliente:** que el sistema entienda los días escritos como número **y** como palabra, porque las incapacidades reales llegan de las dos formas y a veces de las dos a la vez (`DOS (2) DIAS`).

**Evidencia que motivó el cambio** (fase previa sin tocar código; inventario completo en `dataset-falsedad/duraciones/01_evidencia.md`): se revisaron **31 textos OCR ya cacheados** (29 distintos) más la **capa de texto de 13 PDF** originales, sin volver a correr OCR. Resultado:

- **17 formas reales** de escribir la duración: 10 solo con número (`Dias de Incapacidad: 1`, `Dias:3`, `DURACION:`⏎`126`, prosa `POR 4 DIAS DESDE EL …`, incluso todo pegado `…POR1DIAAPARTIRDE18/05/2026`), **6 mixtas** (`Dias: 2 (DOS DIAS)`, `02 dos dia(s)`, `DIAS: 30 (TREINTA)`, `14 - CATORCE`, `DOS (02)`, número y palabra en renglones distintos) y **1 solo con palabra**.
- Esa única forma "solo palabra" es un **artefacto del OCR**: el dígito de `NN - PALABRA` se perdió y sobrevivió `-DOS`. O sea que **el valor real de leer letras es servir de red cuando el número se pierde** — no es un formato nuevo. Y es justamente un documento etiquetado como adulterado: la palabra dice 2 y el rango de fechas 3.
- Solo aparecen **4 numerales cortos** en palabras (`UN`, `DOS`, `CATORCE`, `TREINTA`): las duraciones largas se escriben **siempre en dígitos** (el máximo del corpus, 126 días, no lleva palabra). Cubrir `CIENTO…`/`QUINIENTOS…` es gratis y consistente con el rango 1..540, pero no es lo que determina la precisión.
- **17 clases de falso positivo** que un léxico de numerales suelto lee como duración: la edad (`33 Ano(s), 1 mes(es), 8 dia(s)`), las cantidades de insumo (`1 (Uno)`), las horas de un permiso, las semanas de gestación, el día del mes de una fecha, el AÑO, los consecutivos, los CIE-10, `hacetresdias` (la queja del paciente — literalmente `<palabra> dias`) y la prosa de las cartas de vacaciones.

**Qué se construyó:** `numeros_es.py`, un **lector puro** (no aplica reglas de dominio, ni el rango 1..540) con su léxico ampliable por diccionarios, el saneo tolerante al OCR y **dos anclas**: la unidad pegada al valor o un rótulo de duración en el mismo renglón (o en uno adyacente que contenga SOLO el valor). En el registro aparecen dos campos nuevos —`dias_letra` y `dias_letra_coincide`— porque **el dígito manda y la discrepancia se registra, no se juzga**: decidir si un desacuerdo es adulteración es de otro módulo. Se reutiliza el mismo mecanismo de anclaje de las fechas para que la duración que devuelve el LLM solo se acepte si su expresión —el dígito **o la palabra**— está de verdad en el texto (`numerales_en_texto`).

**Medido sobre los 31 textos cacheados:** de los 26 campos del esquema, **ninguno empeoró**. `dias`: 3 documentos que antes no tenían dato ahora lo tienen, 2 valores corregidos (uno leía `29`, el día del mes de la fecha) y 1 dato **inventado retirado** (leía `202`, el año). Coste ≈ +0,3 ms/documento (mismo orden que antes, ~1,5-3 ms según carga de la máquina).

**Ronda de verificación adversaria** (tres frentes: 251 entradas hostiles contra el lector, regresión campo a campo sobre el corpus, y caza de duraciones inventadas). Encontró que **el ancla no era suficiente** y de ahí salieron las correcciones que hoy tiene el módulo:

- **Veto por los DOS lados.** La lista negra solo miraba a la izquierda, así que cualquier `<N> DIAS` del certificado entraba: `3 dias habiles` (plazo de trámite — la versión en HORAS está impresa en un certificado real del corpus), `valido por 30 dias`, `control en 3 dias`, `3 dias de evolucion` y la fórmula de cierre notarial `a los 15 dias del mes de agosto`. Peor: si el falso positivo iba antes en el orden de lectura, **le quitaba el campo a la duración real**. Y el rótulo `Duracion` alcanzaba la duración de **otra cosa** medida en horas, semanas o meses (`DURACION DEL PERMISO: 4 HORAS` es rótulo real de los permisos).
- **La frase numeral se lee completa.** Con una ventana de 25 caracteres tras el rótulo, `CIENTO OCHENTA` se leía como **100** y `DOSCIENTOS CINCUENTA Y CINCO (255)` como **250** —el prefijo de un numeral español siempre vale menos que el total, así que sale un valor redondo, en rango y sin ninguna señal—, y encima el recorte tapaba el dígito que lo confirmaba. Ahora la ventana acota dónde puede **empezar** el valor y el valor tiene su propio espacio; si el numeral se cortó, no se lee a medias.
- **El rótulo escueto exige plural** (`Dias:`): `Dia:` en singular es un campo de fecha (`Dia: 27 Mes: 08 Ano: 2026`) y devolvía el día del mes. Lo mismo en el respaldo histórico de `extract`, del que además se **eliminó** el patrón sin rótulo (subsumido por el ancla de unidad y sin forma de vetar lo que va detrás).
- **`mil` fuera del léxico pero dentro de la frase:** `Duracion: mil ochenta` daba 80 y `dos mil veintiseis` daba 2. Ahora el millar se captura entero y se rechaza entero — eso cierra también el único camino por el que el AÑO escrito en palabras podía anclar una duración del LLM.
- **La celda de la tabla DETALLE tiene su propia puerta** (`duracion_de_celda`, ancla POSICIONAL): prestarle un rótulo escrito (`"Dias: " + celda`) hacía que un CIE-10 desplazado a esa columna (`J069`) se leyera como **69 días**, dentro de 1..540 y por tanto sin señal.
- **La regla de VACACIONES tenía un solo guardián y era frágil:** el patrón del título toleraba la tilde de `Notificación` pero no la de `Período`, y con la tilde la carta se procesaba como incapacidad, se quedaba sin fechas y devolvía el `7` del "día siete (07) de julio" — exactamente lo que la regla prohíbe.
- **Se retiró una corrección de OCR** (`3Dian` → `3 dias`): medida sobre las 44 entradas reales, cambiaba el resultado de **un** documento y para peor (convertía el renglón del registro profesional en 1 día y hacía que se sobrescribiera la fecha fin leída). En el documento que la motivaba los días ya salían del rango de fechas.
- **Rendimiento:** abrir la ventana del rótulo al renglón completo hizo **cuadrática** una de las formas (frase numeral + paréntesis); un renglón artificial de 58 KB tardaba minutos. Los dos límites (proximidad al rótulo + espacio del valor) están puestos también por esto.

**Lo que NO se cambió, a propósito:** `reposo por 2 dias` se sigue leyendo (en el corpus la duración se escribe justo así, `SE DA INCAPACIDAD MEDICA POR 4 DIAS`, y vetar "reposo" perdería duraciones reales); y un número suelto de 1-2 cifras en el renglón de al lado se sigue leyendo, porque es indistinguible de la forma real `DURACION:`⏎`126` (sin coordenadas del OCR no hay más información). Los dos casos están fijados como límites en `tests/test_numeros_es.py` [14].

**Limitaciones declaradas:**

- **El camino LLM no se ha ejecutado nunca.** Ollama no está levantado en esta máquina (ni Docker, falta elevación). El prompt nuevo y la política de fusión se validaron **por inspección** y con un `StubLLM` inyectado (extractor falso con respuesta JSON fija, al estilo de `StubOCR`) que cubre las guardas de anclaje, no el modelo. Para probarlo: `docker compose up -d --build`, `docker compose exec ollama ollama pull gemma3:4b` y procesar un documento con `--extractor hibrido` mirando `incapacidad.dias`/`dias_letra`/`dias_letra_coincide`.
- **`tests/test_ejemplos_reales.py` no se ha corrido** con este cambio (necesita RapidOCR sobre 7 escaneos y había otra medición en curso en la máquina). Es el punto ciego: si un rótulo de días de esos documentos vive fuera de la lista del módulo, hoy depende del respaldo histórico.
- **No hay ninguna carta de vacaciones real en el corpus:** la regla se verifica con un texto sintético.
- **La comparación duración vs. rango de fechas —la señal de fraude respaldada por la evidencia— no se implementa aquí.** Solo hay instrumentación (`dias_letra_coincide` y `fecha_fin_recalculada`), y el aviso de fecha fin solo puede dispararse si el documento traía las dos cosas.
- **La UI y el staging no muestran los campos nuevos:** viajan en la respuesta de la API pero `static/index.html` pinta con lista blanca y `erp.mapear_a_staging` los ignora. Que el revisor vea la discrepancia es otro alcance (etiqueta en la UI y columna o nota en observaciones).
- **Una sola duración por documento:** si el texto trae dos (pasa en un PDF adulterado real), se lee la primera y el conflicto no se detecta.

### 5.9 Validación de TIEMPOS — motor de reglas `reglas_tiempo.py` (2026-09-02)

**Qué pidió el cliente, literal:** *"código sustantivo de trabajo, valida los tiempos, para cuando no coincida déjalo de tal forma que sea escalable y actualizado"*. Traducido: código de producción (no un script suelto), que detecte cuándo las fechas y la duración no cuadran, que **añadir una regla sea añadir una declaración** y que **severidades y umbrales se cambien sin volver a desplegar**.

**Qué se construyó:** un motor de **reglas deterministas** (sin modelo, sin red, sin BD obligatoria) con **17 reglas declaradas** en un `CATALOGO` (`T01…T17`; cuatro declaradas y **apagadas** porque les falta un dato del lector o el acceso al histórico del ERP). El motor no conoce ninguna regla: las recorre. Cada regla responde en **tri-estado** —`CUMPLE` / `NO_CUMPLE` / `NO_EVALUABLE` con el motivo en español— más `DESACTIVADA`, y los hallazgos viajan por el canal que ya existía (`problemas` → `requiere_revision`, `alertas_tiempos`/`severidad_tiempos` en la fila). Severidad y umbrales se leen en cada corrida con prioridad **BD > JSON del volumen > defaults del código**. Documentación completa —tabla de reglas, receta para añadir una, procedimiento de cambio en producción, medición y preguntas abiertas— en [`VALIDACION_TEMPORAL.md`](VALIDACION_TEMPORAL.md).

**Por qué la invariante "validar NO es reconciliar" es la parte importante:** `extract.normalizar_fechas()` **completa** lo que falta (`inicio = fin − (días − 1)`) y re-deriva un fin que no cuadre. Si una regla pudiera juzgar ese valor derivado, la aritmética que lo produjo garantiza que "cuadra" y el resultado es una tautología o —peor— un falso positivo contra un documento legítimo al que el OCR solo le leyó dos de las tres patas. Por eso a una regla **no se le pasa el contexto**, se le pasa una vista de solo-evidencia (`EvidenciaTiempos`) que **no tiene ningún campo `*_efectivo`**, `CAMPOS_EXIGIBLES` se **deriva** de esa vista y la declaración se valida **al importar el módulo**. La evidencia sobrevive porque `processor` guarda una **foto** de los tiempos leídos antes de reconciliar y llega al ERP en `fechafin_leida`/`dias_leidos`.

**Medido sobre el corpus de falsedad** (31 documentos ya extraídos, **sin ejecutar OCR**; 5 excluidos por etiqueta contradictoria → **26 evaluables = 12 falsas + 14 reales**; `hoy` fijado, defaults del código, ruta de producción completa):

- **0 falsos positivos sobre documentos reales** (0/14 GRAVE·MEDIA y 0/14 avisos LEVE).
- **1/12 falsas marcadas** (F09, `T01` GRAVE, desfase +30). Contrastado con un chequeo aritmético independiente (`span = fin−inicio+1`): el único documento incoherente observable es ese, y el motor lo detecta → **0 falsos negativos sobre lo observable**.
- **La única falsa cuyo motivo declarado es temporal (F04) NO se detecta**, y no es un defecto de la regla: el papel imprime las dos fechas **en palabras** y el extractor solo saca los días, así que `T01` queda `NO_EVALUABLE`. Entregándole a mano la tripleta que sí imprime el papel, el mismo motor responde REVISAR / `T01` GRAVE con el desfase exacto. **El techo del motor es la cobertura de LECTURA**: `T01` no se puede evaluar en 13 de 26 documentos (50 %), y en 10 de esos 13 la fecha **sí está** en el texto OCR.
- Veredictos: COHERENTE 21 · REVISAR 1 · SIN_DATOS 4. Cobertura media del informe **0,554** (el número que evita leer un COHERENTE de cobertura 0,33 como "documento verificado").
- **Nunca rechaza solo:** 31/31 filas quedan en revisión humana, 0 excepciones, y degrada sin BD (`cargar_config()` → defaults, sin avisos).

**Ronda de verificación adversaria (tres frentes) y qué se corrigió.** 345 comprobaciones hostiles contra el motor, la medición sobre el corpus y una caza específica de marcas indebidas sobre documentos legítimos. El núcleo aguantó (la configuración externa es a prueba de balas: 105 comprobaciones con severidades inválidas, JSON roto y tipos del driver, 0 fallos reales; ningún contexto degenerado produjo un veredicto incorrecto). Lo que **sí** se rompió y se arregló:

- **Un valor CALCULADO entraba como evidencia por el camino real de la revisión humana:** la UI rellena el formulario con el valor EFECTIVO (que puede ser el derivado) y lo reenvía en cada `/api/mapear` y `/api/registrar` aunque no se toque nada. Efecto medido: `T09` acusaba a un documento legítimo, `T01` daba un CUMPLE tautológico, desaparecía el aviso "(calculada: fin − días)", `confianza_ocr` subía a 1.0 **y se guardaba así** en la fila, y la aprobación quedaba bloqueada con un 409 sin salida (el auxiliar solo podía salir tecleando otra fecha, o sea falseando el dato). Ahora un override es evidencia **solo si cambia algo** (`es_correccion_humana`); una corrección de verdad se sigue juzgando igual.
- **Una errata en la severidad de una regla nueva tumbaba el mapeo de TODOS los documentos** (`KeyError` → 500 y documento perdido en el lote). Ahora se usa una severidad de respaldo y la errata sale como aviso de configuración: contradecía a la vez el requisito "añadir una regla = añadir una declaración" y la promesa de que una regla con bug queda no evaluable sin romper el pipeline.
- **La frontera leído/calculado no era una restricción, solo documentación:** un `requiere` podía nombrar un valor reconciliado o traer una errata (y dejar la regla muda para siempre con un motivo ilegible para el auxiliar), un código repetido pasaba desapercibido y el cuerpo de una regla podía leer un `*_efectivo` esquivando la prueba que inspecciona el código fuente. Se cerró por construcción (vista de evidencia + validación en la declaración + `verificar_catalogo()` al importar).
- **`erp.mapear_a_staging` lanzaba `OverflowError`** al calcular `fechavencimiento` con un año al límite del calendario: un dígito mal leído perdía el documento con un 500 en vez de mandarlo a staging, contra la invariante "nunca se rechaza solo". Igual `T01`, que quedaba muda justo cuando los tiempos NO cuadran.
- **Los días DERIVADOS por el lector de las dos fechas entraban en la foto como "días impresos":** si el auxiliar corregía solo la fecha fin, `T01` acusaba de GRAVE una incoherencia que produjo el pipeline, y la fila se quedaba con `Numerodias`/`fechavencimiento` del rango viejo, contradiciendo su propia columna de evidencia. Se resolvió con el criterio "unos días que son exactamente el span de las dos fechas leídas no son evidencia independiente" y recalculando la fila; el día que el lector publique `dias_calculado` la precisión vuelve a ser exacta en los dos sentidos (ya está soportado y probado).
- **Un fin COMPLETADO por la reconciliación se contaba como leído** en los registros que llegan sin la foto (los 31 JSON del corpus y la API pública de auditoría): el informe afirmaba haber cruzado duración↔rango sobre un papel que no imprimía ningún rango, con cobertura 0,85, **incluso sobre un documento adulterado**. Ahora ese fin se degrada a "no verificable" (y `T08` sabe que no es lo mismo que "no hay fecha fin", para no crear un falso positivo nuevo).
- **Menores del mismo barrido:** `dias` sin techo llegaba verbatim a una columna `INT` y MySQL estricto rechazaba el INSERT completo (1264); un override de solo espacios se reportaba como "leí este dato y no sirve" y encima silenciaba el mensaje claro; un `datetime` dejaba muda a `T01` o le hacía dar un GRAVE falso por truncar las horas; `T01` y `T04` emitían dos GRAVES por el mismo span y castigaban dos veces el puntaje que ordena la cola; un override `None` borraba la evidencia impresa; `hoy=None` tumbaba el informe; una regla que devolvía algo que no era texto ponía `True` en la pantalla del auxiliar; `alertas_tiempos` se desbordaba de `VARCHAR(255)` en cuanto se encendieran las reglas apagadas; y la cobertura se inflaba con la única regla que no mira el documento.

**Decisiones sobre falsos positivos (bajar severidad o exigir evidencia, NO ajustar el umbral):**

- **`T09_INICIO_EN_FUTURO` no aplica a vacaciones (tipo 13) ni a prelicencia de maternidad (tipo 10)**: empezar en el futuro es el propósito de esos documentos, y la regla marcaba el **100 %** de ellos en cuanto la antelación pasaba de 30 días (no depende de que el OCR falle). Se eligió **exención por TIPO** en vez de subir `dias_futuro_max` o bajar la severidad, porque las dos alternativas debilitan la regla para todas las incapacidades y la exención no.
- **`T08_DURACION_SIN_RESPALDO` pasa a LEVE** (avisa, no bloquea) con el umbral intacto en 180: una duración larga sin fecha fin no es una contradicción del documento, y era la **única** regla que marcaba un documento REAL en toda la medición (bloqueaba una prórroga legítima de 210 días). Coste asumido y anotado: un `dias` basura tipo `202` pasa a ser aviso.
- **No se toca `desfase_tolerado_dias`** (queda en 0): subirlo a 1 taparía el riesgo de un emisor con convención no inclusiva, pero silencia también F04, el único acierto propio de la aritmética en el corpus. La recomendación es convención por emisor (NIT/EPS) y revalidar cuando entre una EPS nueva.
- **`T02`/`T04` se quedan en GRAVE**: pueden disparar por un defecto de LECTURA (el OCR emite las celdas al revés, o un `DE 2016` de un pie legal desplaza el emparejamiento de años), pero bajarlas a MEDIA no evita el bloqueo —MEDIA también bloquea—, solo cambiaría el orden de la cola. El arreglo de fondo es en `extract.py`; mientras tanto el mensaje de `T02` nombra las dos causas posibles para que el auxiliar lo resuelva de un vistazo.
- **Una sola verdad para la aritmética duración↔rango:** se **eliminó** la comprobación duplicada que vivía en `authenticity.py`. Estaba muerta (recibía el registro ya reconciliado), toleraba ±1 día donde el motor no tolera nada —así que el único documento adulterado con desfase +1 salía "no sospechoso" allí y GRAVE aquí— y si despertaba el auxiliar leía dos mensajes del mismo hecho por dos canales distintos.

**Limitaciones declaradas:**

- **El techo lo pone el LECTOR, no las reglas.** Las fechas escritas en palabras, la cadena que el lector RECHAZA (`31/02/2026`), la procedencia de los días y el flag de prórroga no se publican hoy: el motor ya sabe consumirlos (constantes `CLAVE_*`, con prueba), así que son cambios aditivos en `extract.py` — enumerados uno a uno en `VALIDACION_TEMPORAL.md` §7. Sin ellos, cuatro reglas (`T03`/`T05`/`T06`/`T07`) son inalcanzables por el camino del documento y `T01` no se puede evaluar en la mitad del corpus.
- **La ventana temporal se mide contra la fecha de PROCESO**, no contra la de recepción del archivo: reprocesar un lote histórico o un contenedor con el reloj mal desplazan `T09`/`T10` (medido: 8 de 14 reales marcadas con `hoy`=2026-05-01 frente a 0 con `hoy`=2026-09-02). `T10` es LEVE a propósito; `T09` es MEDIA y bloquea. Es la pregunta abierta P6.
- **Las cuatro reglas apagadas siguen apagadas:** `T13` necesita que el lector publique el día de la semana impreso; `T15`/`T16`/`T17` necesitan el acceso de solo lectura al histórico del ERP (P5) y el adaptador que lo consulte (las consultas y sus filtros anti-falso-positivo están escritos en comentario dentro de cada regla).
- **`R-T05` (`fechavencimiento == fechainicio + Numerodias`) no es una regla del catálogo a propósito:** es una post-condición sobre la fila FINAL y el contrato prohíbe que una regla lea un valor efectivo. Queda como propuesta para `erp.mapear_a_staging` o como guardarraíl del INSERT (medido: 0 violaciones en las 19 filas comprobables).
- **La UI no tiene el panel de tiempos.** `static/index.html` tiene el contenedor (`div #erpTiempos`) pero no el JS que lo pinta: el auxiliar ve los textos por `problemas` de siempre y **no** ve el veredicto ni la cobertura, que es justo lo que le permitiría distinguir "no encontré nada raro" de "casi no pude mirar". No se escribió porque otro trabajo estaba editando ese archivo en paralelo.
- **Requisito de despliegue (no opcional):** las columnas `fechafin_leida`, `dias_leidos`, `alertas_tiempos`, `severidad_tiempos` tienen que existir; `sql/init.sql` solo corre en el primer arranque de un volumen vacío, así que en una BD ya existente hay que correr a mano `sql/migracion_reglas_tiempo.sql`.
- **El índice `puntaje_coherencia` sirve para ORDENAR la cola**, no es una probabilidad de fraude ni sale de un modelo. Y **1 de 15 falsas** lo es por un motivo temporal: la tasa de detección global del corpus no es la tasa del motor.

---

## 6. Cómo encaja en el flujo de nómina / ERP

```
[Foto/escaneo incapacidad] → incapacidad-ocr (OCR local + estructuración) → JSON
        → mapeo a staging lp_ausentismos_ia (lookups + homologación) → revisión humana
        → el ERP PROMUEVE a lpausentismos al APROBAR
```

- **incapacidad-ocr = la pieza de OCR + estructuración + staging** que automatiza la digitación.
- El **auxiliar revisa y aprueba** (no digita): completa lo que el OCR no leyó, aprueba o rechaza.
- El **ERP** mantiene su lógica: promueve el registro aprobado a `lpausentismos` (división de novedades, validación de cotización, etc.).

---

## 7. Estado y pendientes

**Hecho:** PoC funcional; **soporte de PDF (PDFium, multipágina)**; extractor por reglas endurecido + **híbrido (reglas+LLM)**; **evaluación con 8 incapacidades reales = 80% campos núcleo** (§5.1); **integración a BD/staging** (§5.4); **flujo de revisión humana — completar/aprobar/rechazar + bandeja** (§5.5); **ingesta masiva por lotes (carpetas + nomenclatura), organización por persona/fecha, corrida programada y robustez con documentos pesados** (§5.6); regla de fecha de inicio y separación de nombres pegados; CLI, README, CLAUDE.md, tests.

**Pendiente / próximos pasos:**
- ✅ *(hecho)* Probar con **incapacidades reales** → ver §5.1 (80% con reglas, 100% en CIE-10/documento legibles).
- ✅ *(hecho)* **Ollama habilitado** como contenedor Docker con `gemma3:4b` (§5.2): mejora los casos difíciles. Pendiente subir el techo con modelo de **visión fuerte** (`qwen2.5vl`/`llama3.2-vision`) y/o **GPU** (CPU es lento y el 4B alucina fechas ocasionalmente).
- ✅ *(hecho)* **Integración a BD + revisión humana** (§5.4, §5.5): mapeo a staging, completar a mano, aprobar/rechazar.
- ✅ *(hecho)* **Entrada por carpetas (ingesta por lotes) + nomenclatura + corrida programada** (§5.6). Guía ejecutiva para el punto de recepción: [`GUIA_RECEPCION_INCAPACIDADES.md`](GUIA_RECEPCION_INCAPACIDADES.md).
- ✅ *(hecho)* **Duración en números y en letras** (`numeros_es.py`, §5.8) con su ronda de verificación adversaria. **Pendiente de este cambio:** correr `tests/test_ejemplos_reales.py` (necesita RapidOCR sobre los escaneos) y **validar el camino híbrido con Ollama vivo** — hoy solo está probado con `StubLLM`; y decidir si la discrepancia palabra↔dígito se le muestra al auxiliar (etiqueta en la UI) o se persiste (columna/observación en staging).
- **Acordar con el negocio la nomenclatura y el punto de recepción** (WhatsApp/correo → carpeta): compartir la guía de recepción y validar con una muestra que los archivos llegan bien nombrados.
- Apuntar a la **BD ASTGU real** (catálogos reales de empleados/CIE/EPS) en vez de los datos de prueba; `numero_orden` y score de confianza OCR real.
- **Corrida programada en Windows headless** (modo B: Programador de tareas del SO) si el servidor no mantiene Docker activo sin login (§5.6 / plan §5). Escalar concurrencia (ledger/lock en BD) si el volumen lo exige.
- Ampliar validaciones (prórrogas; validación de CIE-10 contra catálogo completo).
- Gobernanza de datos: confirmar manejo de PII (Ley 1581), retención y borrado de imágenes/uploads.

---

## 8. Guardrails

- **Todo local.** Ningún componente envía datos a servicios externos ni usa APIs de pago.
- **PII (Ley 1581):** las incapacidades contienen datos de salud (sensibles). Mantener el procesamiento local, con retención mínima y borrado de uploads.
- **RapidOCR vs Ollama:** RapidOCR para impreso; para manuscrito subir a Ollama-visión. No asumir 100% de exactitud → dejar revisión humana en el flujo de nómina.

---

## 9. Revisión de seguridad (2026-06-17)

Revisión del servicio web + Docker. Hallazgos y correcciones aplicadas:

| # | Riesgo | Severidad | Corrección |
|---|---|---|---|
| 1 | **SSRF**: `ollama_url`/`ocr_model`/`llm_model` venían del cliente → un atacante podía apuntar el servidor a una URL interna (metadata cloud, servicios internos). | **Alta** | La URL/modelo de Ollama se fijan en el servidor (env `OLLAMA_URL`/`OCR_MODEL`/`LLM_MODEL`). La API solo acepta `archivo`/`ocr`/`extractor` (lista blanca → 400 si inválido). |
| 2 | **Fuga de información** en errores 500 (`str(exc)` exponía rutas/internos). | Media | Se loguea el detalle en el servidor; al cliente solo mensaje genérico. El contenido (PII) no se loguea. |
| 3 | **DoS por subida**: tamaño se chequeaba *después* de leer todo a memoria; PDFs de miles de páginas; *decompression bombs*. | Media | Chequeo de tamaño con `UploadFile.size` antes de leer (+ respaldo); `MAX_PDF_PAGES=20`; `Image.MAX_IMAGE_PIXELS=64M`. Todo configurable por env. |
| 4 | **Exposición de red**: web y Ollama publicados en `0.0.0.0` (LAN). Ollama **no tiene autenticación**. | Media | Web enlazado a `127.0.0.1:8000`; Ollama **sin puerto al host** (solo red interna de compose). |
| 5 | **Endurecimiento del contenedor**. | Baja | `no-new-privileges`, `cap_drop: ALL` (web), usuario no-root (ya existente). |
| 6 | **Dependencia** `python-multipart` (CVE-2024-53981, DoS). | Baja | Piso subido a `>=0.0.18`. |

**Verificado:** la API solo expone `archivo/ocr/extractor` (OpenAPI); un `ollama_url` malicioso enviado por el cliente se **ignora**; el puerto 11434 está **cerrado** en el host; el web alcanza Ollama por la red interna; el procesamiento sigue OK bajo `cap_drop: ALL`.

**Pendiente (producción):** TLS/reverse-proxy si se expone fuera de localhost; autenticación si es multiusuario; `/docs` y `/openapi.json` quedan abiertos (útiles en PoC, desactivar en prod); fijar versiones (pin) de dependencias; antivirus/validación de contenido de los archivos si la fuente no es de confianza.
