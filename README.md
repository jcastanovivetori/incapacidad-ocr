# incapacidad-ocr

Convierte una **imagen/escaneo de una incapacidad médica** (Colombia) en **texto plano** y luego en **JSON estructurado**.

**100% local — sin APIs pagas.** El OCR corre con **RapidOCR** (ONNX/CPU) o con un **modelo de visión en Ollama**. Sigue un enfoque de **dos pasos** (imagen → texto plano → JSON estructurado), adaptado a incapacidades médicas.

> 📄 **Contexto completo** (origen, decisiones, evidencia de pruebas, cómo encaja en nómina, pendientes): [`CONTEXT.md`](CONTEXT.md). Guía para trabajar el repo: [`CLAUDE.md`](CLAUDE.md).

```
imagen/PDF ─► [OCR] ─► texto ─► [extractor] ─► JSON ─► [mapeo ERP] ─► staging lp_ausentismos_ia (MySQL)
              rapidocr/visión    reglas/IA/híbrido       lookups + homologación        el auxiliar APRUEBA en el ERP
```

Acepta **imágenes** (JPG/PNG/JPEG) y **PDF** (cada página se renderiza a imagen con
PDFium —local, sin Poppler— y el texto de todas las páginas se concatena).

## 🚀 Inicio rápido — cómo levantar el proyecto

Requiere **Docker Desktop / Docker Engine** + **Compose v2** corriendo (ver [Requisitos mínimos](#requisitos-mínimos)).

```bash
cd incapacidad-ocr
docker compose up --build -d        # construye y levanta (web + Ollama) en segundo plano
```

Abre la UI en el navegador: **http://localhost:8000**

Arrastra una incapacidad (PDF o imagen) y procésala. Por defecto usa **RapidOCR + reglas** (100% local, sin descargar nada más).

**(Opcional) IA local con Ollama** — mejora nombre/EPS/diagnóstico en casos difíciles. Baja el modelo **una vez** (queda persistido):

```bash
docker compose exec ollama ollama pull gemma3:4b     # estructurador texto→JSON (~3.3 GB)
```
El estructurador por defecto es **Híbrido** (combo recomendado: **Motor OCR = RapidOCR + Estructurador = Híbrido**): usa reglas para fechas/documento (deterministas, no alucinan) + el LLM para nombre/EPS/diagnóstico, con anclaje de fechas al texto (anti-alucinación). Si Ollama no está, degrada solo a reglas automáticamente.

**Comandos útiles:**
```bash
docker compose ps         # estado de los contenedores
docker compose logs -f    # ver logs en vivo
docker compose down       # detener (los modelos quedan en el volumen)
```

> Primera vez: la construcción descarga ~1 GB (imagen web) y la imagen de Ollama ~8 GB. Si no usarás IA, puedes ignorar el contenedor `ollama`.

## Registro en el ERP (tabla staging `lp_ausentismos_ia`)

Lo que pidió Diana (Gruppo): la IA lee → extrae → **inserta en la BD**; el auxiliar **revisa y aprueba**, no digita. Este servicio mapea el JSON extraído a la tabla **staging** `lp_ausentismos_ia` (BD **ASTGU**, MySQL) — **no** escribe en `lpausentismos` directo (eso se saltaría la lógica del ERP); el ERP **promueve** el registro al aprobar.

El mapeo resuelve los datos clave:
- **Lookups:** cédula → `idlpempleado` · CIE-10 → `idlpdiagnosticos` · EPS → `idlpentidad` (contra catálogos en MySQL). Si la cédula no resuelve, se intenta por **nombre** como respaldo.
- **Nombre canónico:** cuando la cédula resuelve, el **nombre del catálogo** es autoritativo → corrige los nombres que el OCR deja **pegados** (`HERNANDEZSANDOVAL` → `HERNANDEZ SANDOVAL`).
- **Homologación** de tipo de ausentismo (texto → código `2/3/5/8/9/10/11`, default 3).
- **Estado de recepción** (Original/WhatsApp/Correo → `idlpestadosrecepausentismos`), `fecharegistro = hoy`, `fechavencimiento = fechainicio + Numerodias`.
- **Fecha de inicio:** se toma la rotulada "Fecha Inicia/Inicial"; si no se detecta, se **calcula** `inicio = fin − (días − 1)` (se marca como calculada para que el revisor la confirme).
- Si falta un dato **obligatorio** (empleado/diagnóstico/EPS/fecha/días) → queda **`PENDIENTE_REVISION`** con los campos faltantes señalados.

### Revisión humana: completar, aprobar o rechazar

En la UI, tras procesar, la sección **«Registro ERP»** es un **formulario editable**: los campos obligatorios que el OCR no pudo leer salen **resaltados**; el auxiliar los **completa a mano**, pulsa **«Recalcular IDs»** (re-resuelve lookups y fechas) y luego:

- **✓ Aprobar** → inserta como `APROBADO` (se bloquea si aún faltan datos obligatorios).
- **Guardar para revisión** → inserta como `PENDIENTE_REVISION`.
- **✗ Rechazar** → inserta como `RECHAZADO` (con motivo).

La **«Bandeja de revisión»** (abajo) lista los registros por estado y permite **aprobar/rechazar** los pendientes directamente. El ERP **promueve** a `lpausentismos` solo cuando el registro queda `APROBADO`. El stack ya incluye un **MySQL** con catálogos y datos de prueba que coinciden con los documentos de `../Ejemplos`.

```bash
# Procesar (incluye .staging = preview con IDs resueltos, NO inserta):
curl -s -F "archivo=@../Ejemplos/incapacidad.pdf" -F "extractor=hibrido" -F "estado_recepcion=WHATSAPP" \
     http://localhost:8000/api/procesar | python -m json.tool

# Recalcular con correcciones manuales (sin escribir en BD):
curl -s -X POST http://localhost:8000/api/mapear -H "Content-Type: application/json" \
     -d '{"resultado": {...}, "campos": {"cedula":"13742111","cie10":"K42.9"}}'

# Registrar (estado: PENDIENTE_REVISION | APROBADO | RECHAZADO):
curl -s -X POST http://localhost:8000/api/registrar -H "Content-Type: application/json" \
     -d '{"resultado": {...}, "estado":"APROBADO", "campos":{...}}'

# Bandeja / aprobar-rechazar / ver uno:
curl -s "http://localhost:8000/api/staging?estado=PENDIENTE_REVISION" | python -m json.tool
curl -s -X POST http://localhost:8000/api/revisar -H "Content-Type: application/json" -d '{"id":1,"accion":"aprobar"}'
curl -s http://localhost:8000/api/staging/1 | python -m json.tool
```

> Los datos de prueba (`sql/init.sql`) son catálogos mínimos. En producción se apunta a la BD ASTGU real (variables `DB_*`).

## Ingesta masiva por lotes (carpeta «sin procesar» + botón «Procesar todos»)

Para procesar **muchos documentos de una vez** (no de uno en uno), hay un flujo por **carpetas**. Quien recibe los documentos (WhatsApp/correo/escáner) los deja en la carpeta de ingesta **con una nomenclatura fija**; el sistema los agrupa por trámite, OCR-ea la incapacidad, valida los soportes requeridos según el tipo y los registra en `lp_ausentismos_ia`.

**Nomenclatura de los archivos** (el nombre indica el caso y el tipo de documento):

```
cedula_AAAAMMDD_TIPODOC[_NN].ext
```
- **Llave del trámite** = `cedula_AAAAMMDD` (misma cédula + fecha ⇒ mismo caso). La fecha es la de inicio de la incapacidad (o la de recepción); el sistema re-lee la real por OCR y avisa si difiere.
- **`TIPODOC` base** (el único que se OCR-ea): `INCAPACIDAD` · `PERMISO` · `VACACIONES`.
- **Adjuntos** (solo se verifican por el nombre): `FURAT` · `FURIPS` · `EPICRISIS` · `HISTORIA` · `NACIDOVIVO` · `REGISTROCIVIL` · `DEFUNCION` · `CEDULA` · `FORMULA` · `ORDEN` · `OTRO`.

```
Ejemplo (enfermedad general con soporte clínico):
  13742111_20260609_INCAPACIDAD.pdf
  13742111_20260609_EPICRISIS.pdf
Ejemplo (accidente de trabajo):
  1005542119_20260601_INCAPACIDAD.pdf
  1005542119_20260601_FURAT.pdf
```

**Estructura de carpetas** (en la raíz del repo, montada en el contenedor como `/data/ingesta`):

```
ingesta/
├── inbox/whatsapp | correo | original/   # AQUÍ se dejan los documentos (con nomenclatura).
│   │                                      #   RH puede crear subcarpetas: el escaneo es recursivo.
│   └── sin_nomenclatura/                  # los mal nombrados caen aquí (se omiten)
├── procesados/<Nombre persona>/<AAAA>/<MM>/<DD>/   # COMPLETOS, organizados por persona y fecha
├── incompletos/<Nombre persona>/<AAAA>/<MM>/<DD>/  # falta un soporte requerido → genera alerta
└── cuarentena/<caso>/                              # fallo técnico
```

En `procesados/` e `incompletos/` los documentos quedan organizados por **persona → año → mes → día**, para revisar fácil el historial de un empleado. El nombre de la carpeta es **primer nombre + primer apellido** (tomado de la incapacidad vía el catálogo, p.ej. `LEONARDO GARNICA`), y la fecha es la de **inicio de la incapacidad**.

**Documentos requeridos por tipo** (mínimo la incapacidad; el resto según el tipo — la tabla `lprequisitos_eps` manda, con estos valores por defecto):

| Tipo de ausentismo | Requiere además |
|---|---|
| Accidente de trabajo / Enf. laboral | `FURAT` |
| Enfermedad general | soporte clínico (`EPICRISIS`/`HISTORIA`) |
| Licencia maternidad | `HISTORIA` + (`NACIDOVIVO`\|`REGISTROCIVIL`) |
| Licencia paternidad | `REGISTROCIVIL`\|`NACIDOVIVO` |
| Tránsito no laboral | `FURIPS` |
| Permiso / Vacaciones / Prelicencia | solo el documento base |

**Cómo usarlo:**
- **UI:** en el panel **«Procesamiento por lotes»** pulsa **«⚙ Procesar todos»** → agrupa, procesa y registra todo lo del `inbox`; el resumen muestra completos/incompletos y la **bandeja** de abajo lista los registros para revisar/aprobar.
- **API:** `POST /api/lote/procesar` (equivale al botón) · `GET /api/lote/pendientes` (cuenta la carpeta).
- **CLI:** `docker compose exec incapacidad-ocr python -m incapacidad_ocr.batch --dry-run` (reporta sin escribir) · `... python -m incapacidad_ocr.batch` (procesa).

Los archivos base se OCR-ean con RapidOCR + reglas; los adjuntos **no** se OCR-ean (se cuentan por su nombre). Todo entra a staging como `PENDIENTE_REVISION`; el auxiliar revisa/aprueba. Diseño técnico completo en [`PLAN_INGESTA_MASIVA.md`](PLAN_INGESTA_MASIVA.md).

## Arquitectura (piezas intercambiables)

| Capa | Opciones | Notas |
|---|---|---|
| **OCR** (`incapacidad_ocr/ocr.py`) | `RapidOCRBackend` · `OllamaVisionOCR` · `StubOCR` | RapidOCR = local, sin servicios; Ollama = modelo de visión local; Stub = pruebas |
| **Extractor** (`incapacidad_ocr/extract.py`) | `RuleBasedExtractor` · `OllamaLLMExtractor` · `HybridExtractor` | reglas = determinista (impreso limpio); LLM = ruidoso/manuscrito; **híbrido = reglas + LLM fusionados (recomendado)** |
| **Orquestador** (`incapacidad_ocr/processor.py`) | `process()` / `IncapacidadProcessor` | une OCR + extractor; reconcilia fechas/días (regla de fecha de inicio) |
| **Mapeo ERP** (`incapacidad_ocr/erp.py`) | `mapear_a_staging()` · `Lookups` | lookups + homologación + `overrides` (correcciones manuales) → fila staging |
| **BD** (`incapacidad_ocr/db.py`) | MySQL (BD ASTGU) | INSERT/UPDATE en `lp_ausentismos_ia` + alertas, flujo `PENDIENTE_REVISION`/`APROBADO`/`RECHAZADO` |
| **Lote** (`incapacidad_ocr/batch.py`) | `procesar_todo()` · `parse_nombre()` | ingesta masiva por carpetas (nomenclatura → agrupar → validar por tipo → staging) |

## Esquema de salida

```json
{
  "paciente":     {"nombre": "...", "documento_tipo": "CC", "documento_numero": "..."},
  "entidad":      {"eps": "...", "ips_prestador": "..."},
  "incapacidad":  {"fecha_inicio": "YYYY-MM-DD", "fecha_fin": "YYYY-MM-DD", "dias": 0,
                   "fecha_expedicion": "YYYY-MM-DD", "tipo": "...", "origen": "..."},
  "diagnostico":  {"cie10": "J06.9", "descripcion": "..."},
  "medico":       {"nombre": "...", "registro": "..."}
}
```

## Requisitos mínimos

**Con Docker (recomendado):**

| | Mínimo (solo RapidOCR) | Recomendado (con Ollama/IA) |
|---|---|---|
| **SO** | Windows 10/11, macOS o Linux con **Docker** + Compose v2 | igual |
| **CPU** | x86-64, 2 núcleos | 4+ núcleos |
| **RAM** | 4 GB | **8 GB+** (el modelo `gemma3:4b` usa ~4-5 GB al inferir) |
| **Disco** | ~1.5 GB (imagen web) | **~13 GB** (imagen web 1.1 GB + imagen Ollama 8.3 GB + modelo 3.3 GB) |
| **GPU** | No requerida (corre en CPU) | Opcional; acelera mucho el LLM/visión |
| **Red** | Solo para la **descarga inicial** de imágenes/modelos; en runtime es 100% offline | igual |

> La imagen de Ollama es grande (~8 GB, incluye libs de aceleración). Si **no** vas a usar IA, puedes correr solo el servicio web (RapidOCR) y omitir el contenedor `ollama`.

**Sin Docker (local):** Python **3.11–3.14**, `pip install -r requirements.txt`. RapidOCR descarga modelos ONNX embebidos en el wheel (sin servicios externos).

## Seguridad y privacidad

Revisado y endurecido (ver detalle en [`CONTEXT.md`](CONTEXT.md) §9):

- **Sin SSRF:** la URL y el modelo de Ollama se fijan **en el servidor** (variables de entorno `OLLAMA_URL`/`LLM_MODEL`); el cliente **no** puede elegirlos. La API solo acepta `archivo`, `ocr`, `extractor` (lista blanca).
- **PII (Ley 1581):** los archivos subidos se procesan en un temporal y se **borran** de inmediato; nada se persiste ni sale a terceros. Los errores no devuelven detalles internos y **no se loguea** el contenido.
- **Documentos pesados / anti-DoS:** límite de subida **50 MB** (`MAX_UPLOAD_BYTES`); el PDF se rasteriza **página a página en streaming** (una en memoria a la vez) hasta `MAX_PDF_PAGES` (30); cada página se acota a `OCR_MAX_PIXELS` (40 MP) para no disparar la RAM en escaneos enormes; guarda contra *decompression bombs* (`MAX_IMAGE_PIXELS`, 200 MP). Todo configurable por env.
- **Red:** la UI se publica **solo en `127.0.0.1`** (no en la LAN). **Ollama no expone puerto al host** (no tiene autenticación) — solo es accesible desde la red interna del contenedor web.
- **Contenedor:** corre como **usuario no-root**, con `no-new-privileges` y `cap_drop: ALL` en el servicio web.

## Servicio web (Docker) — para probarlo tú mismo

Una UI moderna (arrastra y suelta una incapacidad, ve el texto OCR y el JSON, descarga el resultado) + API REST. **Todo se levanta con Docker** instalando desde `requirements.txt`:

```bash
docker compose up --build
# abre http://localhost:8000
```

- **UI:** http://localhost:8000
- **API:** `POST /api/procesar` (multipart: `archivo`, y opcionales `ocr`, `extractor`) · `GET /api/health` · docs OpenAPI en `/docs`
- 100% local: RapidOCR corre dentro del contenedor; los archivos subidos se procesan en un temporal y **se borran** (no se persiste PII — Ley 1581).

```bash
# Ejemplo por API (cURL) con uno de los documentos de prueba:
curl -s -F "archivo=@../Ejemplos/ALEJANDRO LINARES.pdf" http://localhost:8000/api/procesar | python -m json.tool
```

### Mejorar los casos difíciles con Ollama (IA local)

`docker compose` levanta **también un contenedor de Ollama** (100% local). El combo recomendado para documentos con OCR ruidoso/desordenado es **Motor OCR = RapidOCR + Estructurador = LLM Ollama**: RapidOCR lee el texto y el LLM lo entiende por contexto aunque salga desordenado.

Baja el modelo **una sola vez** (queda persistido en un volumen):

```bash
docker compose exec ollama ollama pull gemma3:4b      # estructurador texto→JSON (~3.3 GB)
docker compose exec ollama ollama pull qwen2.5vl:3b   # (opcional) OCR de visión por IA (~3.2 GB), lento en CPU
```

Luego, en la UI elige **LLM Ollama** como estructurador, o por API:
```bash
curl -s -F "archivo=@../Ejemplos/incapacidad_.jpeg" -F "extractor=ollama" http://localhost:8000/api/procesar | python -m json.tool
```

> Sin GPU el LLM corre en CPU: la **primera** petición carga el modelo (~1 min) y las siguientes son más rápidas. El `OLLAMA_URL` del contenedor web apunta a `http://ollama:11434` automáticamente.

## Instalación (local, sin Docker)

```bash
python -m venv .venv
.venv/Scripts/activate        # Windows ; en Linux/Mac: source .venv/bin/activate
pip install -r requirements.txt
```

Levantar el servicio web sin Docker:
```bash
uvicorn incapacidad_ocr.webapp:app --host 0.0.0.0 --port 8000
```

Opcional (mejor lectura de manuscritos): instala [Ollama](https://ollama.com) y baja modelos:
```bash
ollama pull qwen2.5vl:3b   # visión (OCR) — modelo que SÍ transcribe (no usar moondream)
ollama pull gemma3:4b      # texto (estructuración)
```

## Uso

```bash
# OCR local con RapidOCR + estructuración por reglas (default) — imagen o PDF
python -m incapacidad_ocr.cli incapacidad.jpg
python -m incapacidad_ocr.cli incapacidad.pdf

# Solo el texto plano (paso 1)
python -m incapacidad_ocr.cli incapacidad.jpg --solo-texto

# Todo con Ollama (visión + LLM) para imágenes difíciles
python -m incapacidad_ocr.cli incapacidad.jpg --ocr ollama --extractor ollama
```

Como librería:
```python
from incapacidad_ocr import process, RuleBasedExtractor
res = process("incapacidad.jpg", ocr="rapidocr", extractor=RuleBasedExtractor())
print(res["texto_plano"])   # paso 1: imagen → texto plano
print(res["incapacidad"])   # paso 2: JSON estructurado
```

## Pruebas

```bash
python tests/test_processor.py        # pruebas unitarias (sintéticas, deterministas)
python tests/test_ejemplos_reales.py  # evaluación sobre las incapacidades REALES de ../Ejemplos
```

`test_processor.py` genera una incapacidad sintética y valida el extractor por reglas,
el preprocesado, el parseo JSON y el pipeline end-to-end (con `StubOCR` siempre; con
**OCR real (RapidOCR)** si está instalado).

`test_ejemplos_reales.py` corre el pipeline completo **PDF/imagen → RapidOCR →
RuleBasedExtractor** sobre los 8 documentos reales de la carpeta `Ejemplos/` y mide la
precisión contra un ground-truth. Resultado actual: **80% de los campos núcleo**
(documento, CIE-10, fechas, días, origen); CIE-10 y documento ~100% en los documentos
con etiqueta legible. Los fallos se concentran en 2 fotos con OCR muy degradado
(rótulos mal leídos, texto desordenado) — el caso para el path **Ollama-visión + LLM**.

## Notas

- **Imagen → texto plano** = `OllamaVisionOCR.read_text()` / `RapidOCRBackend.read_text()`
  (paso 1). Reutilizable tal cual.
- El `RuleBasedExtractor` funciona bien con **texto impreso**. Para incapacidades
  **manuscritas o con sellos**, usa el OCR de Ollama con un modelo de visión más
  fuerte (`llama3.2-vision`, `qwen2.5vl`) y/o el `OllamaLLMExtractor`.
- Ningún componente envía datos a servicios externos ni usa APIs de pago. (PII: las
  incapacidades contienen datos sensibles — manténlo local / Ley 1581.)
