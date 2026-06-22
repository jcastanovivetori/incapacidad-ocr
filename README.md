# incapacidad-ocr

Convierte una **imagen/escaneo de una incapacidad médica** (Colombia) en **texto plano** y luego en **JSON estructurado**.

**100% local — sin APIs pagas.** El OCR corre con **RapidOCR** (ONNX/CPU) o con un **modelo de visión en Ollama**. Es el mismo enfoque de dos pasos del `invoice-processor` de `SiesaTeams/quality-business-scripts`, adaptado a incapacidades.

> 📄 **Contexto completo** (origen, hallazgos en repos SIESA, decisiones, evidencia de pruebas, cómo encaja en nómina, pendientes): [`CONTEXT.md`](CONTEXT.md).

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

El mapeo resuelve lo que faltaba en la prueba de la Sesión 1:
- **Lookups:** cédula → `idlpempleado` · CIE-10 → `idlpdiagnosticos` · EPS → `idlpentidad` (contra catálogos en MySQL).
- **Homologación** de tipo de ausentismo (texto → código `2/3/5/8/9/10/11`, default 3).
- **Estado de recepción** (Original/WhatsApp/Correo → `idlpestadosrecepausentismos`), `fecharegistro = hoy`, `fechavencimiento = fechainicio + Numerodias`.
- Si falta un dato **crítico** (empleado/diagnóstico/EPS/fecha/días) → queda **`PENDIENTE_REVISION`** con los problemas listados.

En la UI: procesa el documento, revisa la sección **«Registro ERP»** y pulsa **«Registrar en revisión»**. El stack ya incluye un **MySQL** con catálogos y datos de prueba que coinciden con los documentos de `../Ejemplos`.

```bash
# API:
curl -s -F "archivo=@../Ejemplos/incapacidad.pdf" -F "extractor=hibrido" -F "estado_recepcion=WHATSAPP" \
     http://localhost:8000/api/procesar | python -m json.tool          # incluye .staging (preview, no inserta)

# Ver los registros en revisión:
curl -s http://localhost:8000/api/staging | python -m json.tool
```

> Los datos de prueba (`sql/init.sql`) son catálogos mínimos. En producción se apunta a la BD ASTGU real (variables `DB_*`).

## Arquitectura (piezas intercambiables)

| Capa | Opciones | Notas |
|---|---|---|
| **OCR** (`incapacidad_ocr/ocr.py`) | `RapidOCRBackend` · `OllamaVisionOCR` · `StubOCR` | RapidOCR = local, sin servicios; Ollama = modelo de visión local; Stub = pruebas |
| **Extractor** (`incapacidad_ocr/extract.py`) | `RuleBasedExtractor` · `OllamaLLMExtractor` | reglas = determinista (impreso limpio); LLM = textos ruidosos/manuscritos |
| **Orquestador** (`incapacidad_ocr/processor.py`) | `process()` / `IncapacidadProcessor` | une OCR + extractor |

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
- **Anti-DoS:** límite de subida (25 MB, configurable con `MAX_UPLOAD_BYTES`), tope de páginas de PDF (`MAX_PDF_PAGES=20`) y guarda contra *decompression bombs* de imágenes (Pillow ≤ 64 MP).
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
ollama pull moondream      # visión (OCR)
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
  (paso 1). Reutilizable tal cual; es lo equivalente al `_call_ollama_ocr` del invoice-processor.
- El `RuleBasedExtractor` funciona bien con **texto impreso**. Para incapacidades
  **manuscritas o con sellos**, usa el OCR de Ollama con un modelo de visión más
  fuerte (`llama3.2-vision`, `qwen2.5vl`) y/o el `OllamaLLMExtractor`.
- Ningún componente envía datos a servicios externos ni usa APIs de pago. (PII: las
  incapacidades contienen datos sensibles — manténlo local / Ley 1581.)
