# CLAUDE.md — guía para trabajar este repo

Guía operativa para Claude Code (y el equipo). Para el **qué/por qué** ver [`CONTEXT.md`](CONTEXT.md);
para *cómo usarlo* ver [`README.md`](README.md). Comentarios y mensajes al usuario: **en español**.

## Qué es

Pipeline **100% local** que convierte una **incapacidad médica** (imagen/PDF) en **JSON** y lo
mapea a una tabla **staging** del ERP para revisión humana. Sin APIs pagas; sin datos a internet
en runtime (PII de salud — Ley 1581).

```
imagen/PDF ─► [OCR] ─► texto ─► [extractor] ─► JSON ─► [erp.mapear_a_staging] ─► lp_ausentismos_ia (MySQL)
            rapidocr/visión   reglas/IA/híbrido     lookups + homologación      el auxiliar APRUEBA → ERP promueve
```

## Arquitectura (paquete `incapacidad_ocr/`)

| Archivo | Responsabilidad |
|---|---|
| `preprocess.py` | carga imagen/PDF, **PDF→imágenes (PDFium, sin Poppler)**, resize, base64 |
| `ocr.py` | backends OCR: `RapidOCRBackend` (ONNX/CPU), `OllamaVisionOCR` (visión local), `StubOCR` (tests). `OllamaError` + `translate_ollama_error` |
| `extract.py` | extractores: `RuleBasedExtractor`, `OllamaLLMExtractor`, `HybridExtractor`; `normalizar_fechas()` (regla de fecha de inicio); `_split_glued_name()` (nombres pegados) |
| `processor.py` | `IncapacidadProcessor` une OCR+extractor y llama `normalizar_fechas()`. Guarda `MIN_OCR_CHARS` (no estructurar texto vacío → anti-fabricación de PII) |
| `erp.py` | `mapear_a_staging()` (JSON→fila staging), `Lookups` (cédula/CIE/EPS + nombre canónico), homologación de tipo |
| `db.py` | MySQL (BD ASTGU): `insertar_staging`, `listar_staging`, `obtener_staging`, `actualizar_revision`, `actualizar_estado` |
| `webapp.py` | API FastAPI + estado del flujo (`PENDIENTE_REVISION`/`APROBADO`/`RECHAZADO`) |
| `static/index.html` | UI de una sola página (vanilla JS): procesar, formulario de revisión editable, bandeja |
| `cli.py` | `python -m incapacidad_ocr.cli foto.jpg [--ocr ollama --extractor ollama]` |

**Endpoints:** `POST /api/procesar` (multipart) · `POST /api/mapear` (preview con correcciones) ·
`POST /api/registrar` (INSERT con `estado`) · `POST /api/revisar` (aprobar/rechazar/guardar) ·
`GET /api/staging[?estado=]` · `GET /api/staging/{id}` · `GET /api/health`.

## Comandos

Stack en Docker (3 servicios: `incapacidad-ocr`, `ollama`, `db`). Shell: **Git Bash** o **PowerShell 5.1** (Windows).

```bash
docker compose up -d --build                      # levantar todo (UI en http://localhost:8000)
docker compose up -d --build incapacidad-ocr      # reconstruir SOLO la web tras cambiar código Python/HTML
docker compose ps                                 # estado
docker compose logs -f incapacidad-ocr            # logs de la web (aquí salen los tracebacks)
docker compose exec ollama ollama pull gemma3:4b      # modelo LLM (texto→JSON), una vez
docker compose exec ollama ollama pull qwen2.5vl:3b   # modelo visión/OCR (lento en CPU), una vez

# BD (catálogos + staging):
docker exec ocr-db mysql -uocr -pocr ASTGU -e "SELECT id,estado,paciente_leido,fechainicio,Numerodias FROM lp_ausentismos_ia ORDER BY id;"

# Pruebas (local, fuera de Docker):
python tests/test_processor.py          # unitarias deterministas (StubOCR + RapidOCR si está)
python tests/test_ejemplos_reales.py    # evalúa los 8 documentos reales de ../Ejemplos

# Local sin Docker:
pip install -r requirements.txt
uvicorn incapacidad_ocr.webapp:app --host 0.0.0.0 --port 8000
```

### Probar un documento por API (multipart)

En **PowerShell 5.1 `Invoke-RestMethod` NO tiene `-Form`** → usa `curl.exe`:

```bash
curl.exe -s -X POST http://localhost:8000/api/procesar \
  -F "archivo=@../Ejemplos/incapacidad.jpeg" -F "ocr=rapidocr" -F "extractor=hibrido" -F "estado_recepcion=WHATSAPP"
```

## Reglas de dominio (no romper)

- **Fecha de inicio:** preferir la rotulada "Fecha Inicia/Inicial". Si falta → `inicio = fin − (días − 1)`
  (inclusivo) y marcar `fecha_inicio_calculada` (aviso, no bloquea). Toda la reconciliación vive en
  `extract.normalizar_fechas()` y se reaplica en `erp.mapear_a_staging()` al corregir días/fin a mano.
- **`fechavencimiento = fechainicio + Numerodias`** (no inclusivo). **`dias` válido = 1..540**.
- **Nombres pegados** (`HERNANDEZSANDOVAL`): el **nombre del catálogo** (vía cédula→empleado) es
  autoritativo; `_split_glued_name()` es solo respaldo genérico. Si la cédula no resuelve, intentar por nombre.
- **Lookups:** cédula→`idlpempleado`, CIE-10→`idlpdiagnosticos` (compara **sin punto**), EPS→`idlpentidad`
  (match por contención **sin espacios**). Tipo ausentismo: códigos **2/3/5/7/8/9/10/11/12** (default 3).
  Recepción: ORIGINAL=1 / WHATSAPP=2 / CORREO=3.
- **CIE-10:** normalización robusta a OCR (`0↔O`, `1↔I/l`), exige ≥1 dígito real (evita falsos como `FOSCAL`→F05).
- **SOAT (tránsito):** si la EPS leída contiene "soat" → tipo **11 TRANSITO NO LABORAL** siempre, y la EPS a
  asignar es la del EMPLEADO en catálogo (una aseguradora SOAT nunca es la EPS real del paciente).
- **EPS no clara → EPS del empleado:** si el texto del documento no trae EPS o no matchea el catálogo (y sí
  hay cédula resuelta), se usa la EPS registrada del empleado como respaldo (aviso `eps_de_empleado`, no bloquea).
- **PERMISOS** (`FORMATO SOLICITUD DE PERMISO`, detectado por texto en `extract.es_formato_permiso`): tipo de
  documento distinto a la incapacidad — **sin diagnóstico ni EPS**. Tipo **7 LICENCIA NO REMUNERADA** /
  **12 LICENCIA REMUNERADA** según el checkbox marcado (heurística de orden de texto, no de coordenadas — el
  pipeline no expone cajas OCR hoy). Ver `erp.mapear_a_staging` (`es_permiso`) y `extract._extraer_permiso`.
- **Staging, no directo:** NUNCA insertar en `lpausentismos`. Se escribe en `lp_ausentismos_ia`
  (`estado=PENDIENTE_REVISION`); el ERP promueve al APROBAR. No se aprueba con obligatorios faltantes (→ 409).
- **Nivel de incapacidad** (`idlpnivelincapacidad`, FK a `lpnivelincapacidad`): estudiado contra el histórico
  real (`lpausentismos`) — **ni los días ni el diagnóstico predicen el nivel de forma limpia** (el mismo
  CIE-10 aparece con niveles distintos; los rangos de días se solapan entre niveles), es un juicio clínico
  del analista. Se asigna un **default fijo por tipo de ausentismo** (`erp.NIVEL_INCAPACIDAD_DEFAULT`), que
  el auxiliar corrige en revisión si el caso lo amerita: **2 Accidente trabajo→2 LEVE · 3 Enfermedad
  general→9 NO CRITICA · 5 Licencia maternidad→12 NO APLICA · 8 Enfermedad laboral→7 NO CALIFICADA ·
  9 Licencia paternidad→13 NO APLICA. · 10 Prelicencia→14 NO APLICA.. · 11 Tránsito no laboral→11 NO
  CRITICO**. Los permisos y vacaciones (tipo 7/12/13) no tienen niveles definidos en el ERP → queda `NULL`.
- **VACACIONES** (carta "Notificación Periodo de Vacaciones", detectada por texto en
  `extract.es_formato_vacaciones`): tipo de documento distinto a la incapacidad — **sin diagnóstico, EPS ni
  nivel**, tipo fijo **13 VACACIONES** (sin ambigüedad que resolver, a diferencia de permisos). Es una CARTA en
  prosa (no un formulario de casillas): las fechas salen escritas en palabras con el número real entre
  paréntesis ("...a partir del veintinueve (29) de mayo... (2026)... hasta el seis (6) de julio... (2026)"),
  puede traer VARIOS periodos consecutivos — se toma la primera fecha tras "a partir del" y la última tras
  "hasta el". Los días NO se buscan por etiqueta en este formato (frases tipo "el día siete (07) de julio"
  romperían el patrón de días) — se calculan siempre por diferencia de fechas. Ver `erp.mapear_a_staging`
  (`es_vacaciones`) y `extract._fechas_vacaciones`/`extract.es_formato_vacaciones`.
- **PDFs multi-página**: cuando el mismo PDF trae la incapacidad JUNTO con otras páginas del trámite
  (certificado de nacido vivo, epicrisis, cédula escaneada...), el OCR se hace página por página y solo se
  usa el texto de la(s) página(s) que traen el ausentismo en sí (`extract.es_pagina_relevante`, ancla por
  "incapacidad medica"/"certificado de incapacidad"/"detalle de la incapacidad" o los formatos de
  permiso/vacaciones) — si ninguna página matchea, se concatenan todas como antes (sin cambios). Ver
  `ocr._combinar_paginas` (usado por ambos backends).
- **Variantes de etiquetas de fecha/días vistas en documentos reales** (todas en `RuleBasedExtractor.extract`):
  "Fecha de Emisión" (Clínica Medical Duarte) también cuenta como fecha de inicio en licencias de maternidad de
  ese formato; "Fecha de Terminación" (a veces el OCR la pega: "Fecha Determinacion") como fecha fin; "Duración"
  como días (el patrón tolera que el valor quede en la línea siguiente). "Diagnostico(s):" es una variante más
  del ancla de diagnóstico (además de "Diagnostico principal").
- **Tabla "DETALLE DE LA INCAPACIDAD"** (formato Clínica del Cesar): 5 columnas (Causa Externa/Diagnóstico/Días
  Inc./Inicio/Finalización) seguidas de sus 5 valores en bloque — se parsea aparte
  (`extract._extraer_detalle_incapacidad`) porque es más fiable que las heurísticas genéricas y evita falsos
  positivos (tomar "Dias Inc." como si fuera la descripción del diagnóstico, etc.).

## Restricciones / convenciones

- **100% local, sin API paga.** Nada de datos a internet en runtime.
- **Ollama desde el servidor, no el cliente** (anti-SSRF): la URL/modelo se fijan por env
  (`OLLAMA_URL`/`OCR_MODEL`/`LLM_MODEL`). La API NO acepta esos parámetros del cliente.
- **No fabricar PII:** si el OCR no da texto (`< MIN_OCR_CHARS`), NO llamar al extractor → registro vacío + `aviso`.
- **Errores al cliente genéricos** (sin rutas/internos); el detalle va al log del servidor; **no loguear** contenido (PII).
- **Imports perezosos** de `httpx`/`rapidocr`/`mysql.connector` (el módulo importa aunque falte la dependencia).
- **`moondream` NO sirve** para OCR (captioning); usar `qwen2.5vl:3b` para visión.
- **Híbrido** es el extractor por defecto (RapidOCR + LLM fusionados, degrada a solo reglas si Ollama no está).
- **Permisos manuscritos → usar `ocr=ollama` (visión), no RapidOCR.** Validado contra 12 documentos reales de
  `H:\Gruppo\archivos\Ausentismos`: RapidOCR (texto impreso) lee muy mal la letra manuscrita en los formularios
  de permiso (nombre/cédula/fechas quedan irreconocibles); Ollama visión (`qwen2.5vl`) mejora sustancialmente
  esos campos. Aun así, **el checkbox Remunerado/No Remunerado no se detecta de forma confiable con NINGUNO
  de los dos motores** (a veces el modelo de visión ni transcribe la marca) → queda pendiente de revisión y
  el auxiliar elige el tipo (7/12) a mano en la UI; es el comportamiento esperado, no un bug a corregir.

## Gotchas del entorno

- Hoy es **2026** en este proyecto: las fechas de los ejemplos son `2026-06-xx` (no asumir años pasados).
- El **volumen `db-data` persiste** entre reinicios; `sql/init.sql` solo corre en el **primer** init de un
  volumen vacío. Para recargar el esquema: `docker compose down -v` (borra datos) o `ALTER`/`DELETE` manual.
- Tras editar Python/HTML hay que **reconstruir la imagen web** (`up -d --build incapacidad-ocr`) — el código
  va dentro de la imagen, no montado.
- Los datos de `sql/init.sql` (cédulas/CIE/EPS) **coinciden con `../Ejemplos`** para que la demo resuelva lookups.
