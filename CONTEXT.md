# CONTEXT — incapacidad-ocr (fuente única de contexto)

**Última actualización:** 2026-06-17 · **Autor:** Julian Castaño (DevOps) · **Estado:** PoC funcional con soporte PDF, servicio web + UI dockerizado, evaluado sobre incapacidades reales (§5.1) y con Ollama (IA local) habilitado para casos difíciles (§5.2).

Este documento es el **contexto completo** del proyecto: por qué existe, qué se investigó en los repos de SIESA, qué se construyó, cómo se probó y cómo encaja en la plataforma. Para *cómo usarlo* → [`README.md`](README.md).

---

## 1. Origen y objetivo

**Necesidad:** una lógica que **traduzca incapacidades médicas (imágenes/escaneos) a texto plano** y de ahí a datos estructurados, para alimentar nómina sin digitación manual.

La búsqueda arrancó por dos pistas que resultaron ser **cosas distintas**:

| Pista | Qué resultó ser | ¿Sirve para OCR de incapacidades? |
|---|---|---|
| **"Generic Transfer"** | Integrador **Connekta**: transferencia de **datos en archivos planos** hacia/desde el ERP | ❌ No es OCR — es integración de datos |
| **imagen → texto plano** | Patrón del **invoice-processor** (`quality-business-scripts`): OCR + estructuración con IA local | ✅ Sí — es el patrón base de este proyecto |

**Objetivo de este repo:** una versión **limpia, local y funcional** del patrón imagen→texto→JSON, **adaptada a incapacidades (Colombia)**, sin API paga.

---

## 2. Lo que se encontró en los repos de SIESA (hallazgos verificados)

### 2.1 "Generic Transfer" = Connekta (NO es OCR)
Vive en la familia de repos **Connekta**:
- `connekta-integration-manager-services-cloud-sqlserver` → `src/Connekta/GenericTransfer/CoreApp.Servicios/GenericTransfer.cs`
- `connekta-integration-manager-api-on-premise-sqlserver` → `Api/GenericTransfer/Plano.cs`, `Estructura.cs`
- `connekta-integration-manager-services-cloud-postgresql` → `Compartida/LogicaNegocio/Connekta/GenericTransfer/PlanoEstandar.cs`
- `connekta-integrador-v200` / `connekta-integrador-v300`

Hace **transferencia genérica de datos en archivos planos** (`Plano`/`PlanoEstandar`) entre sistemas y el ERP. El "texto plano" aquí = formato del archivo de intercambio (datos estructurados), **no** salida de OCR.

### 2.2 imagen → texto plano = invoice-processor
- Repo: **`SiesaTeams/quality-business-scripts`** (rama `Carlos_Diaz_QA`), ruta `Apps/invoice-processor/`
- Núcleo: `services/ai_processor.py` → `process_image()` / `_call_ollama_ocr()` / `_call_ollama_text()`
- **Enfoque de 2 pasos:** (1) modelo de **visión (Ollama)** transcribe TODO el texto de la imagen → texto plano; (2) modelo de **texto (Ollama)** estructura a JSON.
- **100% local, sin API paga** (Ollama). Las APIs externas (Google Sheets / OneDrive) son solo para **guardar** el resultado, no para la IA. `requirements.txt` sin SDK de OpenAI/Gemini/Anthropic.
- Nota: su `info.md` menciona "Tesseract" pero el **código real usa el modelo de visión de Ollama** (diagrama desactualizado).

### 2.3 No existe lógica de incapacidad→texto en la org
Se buscó `incapac` en todos los repos: lo único que aparece es **procesamiento de incapacidades en nómina legacy** (SQL/`NomLiqProCruceIncapacidadesController.cs`, reportes), **no** conversión de imágenes. → Este proyecto cubre ese vacío reutilizando el patrón 2.2.

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
| Extractor (texto→JSON) | `extract.py` | `RuleBasedExtractor` (regex, determinista) · `OllamaLLMExtractor` (LLM local) |
| Orquestador | `processor.py` | `process()` / `IncapacidadProcessor` |
| CLI | `cli.py` | `python -m incapacidad_ocr.cli foto.jpg [--ocr ollama --extractor ollama]` |
| **Servicio web** | `webapp.py` + `static/index.html` | API FastAPI (`POST /api/procesar`, `/api/health`, `/docs`) + UI moderna (drag&drop, JSON, descarga). RapidOCR cargado una vez; uploads procesados en temporal y **borrados** (PII). |
| **Docker** | `Dockerfile` · `docker-compose.yml` | `docker compose up --build` → `http://localhost:8000`. Instala todo desde `requirements.txt`. Probado OK (python:3.12-slim). |

**Esquema de salida** (incapacidad Colombia): `paciente{nombre, documento_tipo, documento_numero}`, `entidad{eps, ips_prestador}`, `incapacidad{fecha_inicio, fecha_fin, dias, fecha_expedicion, tipo, origen}`, `diagnostico{cie10, descripcion}`, `medico{nombre, registro}`.

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

**Precisión campos núcleo: 36/45 = 80%.** Por campo:

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

Para cerrar la brecha con lo que pide Diana (extraer → **insertar en BD** → el auxiliar aprueba), se añadió la capa que faltaba, alineada con la solución de referencia `middleware-ia-gruppo`:

- **`erp.py`** — homologación de tipo (texto → `2/3/5/8/9/10/11`, default 3), **lookups** cédula→`idlpempleado` · CIE-10→`idlpdiagnosticos` (sin punto) · EPS→`idlpentidad` (match por contención), estado de recepción (1/2/3), `fecharegistro=hoy`, `fechavencimiento=inicio+días`, y `mapear_a_staging()` que arma la fila + lista `problemas`/`requiere_revision`. Degrada a `LookupsNulos` sin BD.
- **`db.py`** — conexión MySQL por env (`DB_*`) + `insertar_staging()` + `listar_staging()`.
- **`sql/init.sql`** — catálogos mínimos + `lp_ausentismos_ia` (mismos nombres de columna del ERP) + `lp_alertas_documentacion` + **datos de prueba que coinciden con `../Ejemplos`** (cédulas, CIE, EPS) para que los lookups resuelvan en la demo.
- **Web/UI** — `POST /api/procesar` ahora incluye `staging` (preview, no inserta); `POST /api/registrar` hace el **INSERT** (estado `PENDIENTE_REVISION`); `GET /api/staging` lista lo pendiente. La UI tiene selector de **recepción**, sección **«Registro ERP»** (muestra los IDs resueltos + problemas) y botón **«Registrar en revisión»**.
- **Compose** — nuevo servicio `db` (mysql:8) que carga `sql/init.sql` al primer arranque.

**Decisión clave respetada:** NO se inserta en `lpausentismos`; se escribe en **staging** y el ERP promueve al aprobar (preserva división de novedades, validación de cotización, etc.). Pendiente para producción: apuntar a la BD ASTGU real (catálogos reales de empleados/CIE/EPS), `numero_orden`, score de confianza OCR real, y el envío de alertas documentales.

---

## 6. Cómo encaja en SIESA

```
[Foto/escaneo incapacidad] → incapacidad-ocr (OCR local + estructuración) → JSON
        → (opcional) archivo plano vía GenericTransfer/Connekta → carga a NÓMINA (ERP)
```

- **incapacidad-ocr = la pieza de OCR** que hoy NO existe en la org.
- **GenericTransfer (Connekta) = la pieza que metería el resultado al ERP** como archivo plano (si el flujo objetivo es cargar a nómina).
- Verticales relacionadas: `business-nomina-payroll-*`, `business-payroll-*` (procesan incapacidades hoy de forma manual/legacy).

---

## 7. Estado y pendientes

**Hecho:** PoC funcional; **soporte de PDF (PDFium, multipágina)**; extractor por reglas endurecido sobre documentos reales; **evaluación con 8 incapacidades reales = 80% campos núcleo** (§5.1); CLI, README, tests.

**Pendiente / próximos pasos:**
- ✅ *(hecho)* Probar con **incapacidades reales** → ver §5.1 (80% con reglas, 100% en CIE-10/documento legibles).
- ✅ *(hecho)* **Ollama habilitado** como contenedor Docker con `gemma3:4b` (§5.2): mejora los casos difíciles (recupera documento/nombre/EPS/origen que las reglas no pueden). Pendiente subir el techo con modelo de **visión fuerte** (`qwen2.5vl`/`llama3.2-vision`) y/o **GPU** (CPU es lento y el 4B alucina fechas ocasionalmente).
- Ampliar el esquema/validaciones (tipos de incapacidad: enfermedad general / laboral / licencia maternidad; prórrogas; validación de CIE-10 contra catálogo).
- Definir la **entrada** real (carpeta vigilada, endpoint que reciba las fotos) y la **salida** (archivo plano para GenericTransfer o API de nómina).
- Gobernanza de datos: confirmar manejo de PII (Ley 1581), retención y borrado de las imágenes/uploads.

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
