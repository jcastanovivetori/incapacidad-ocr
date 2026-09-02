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
| `reglas_tiempo.py` | **motor de reglas de coherencia TEMPORAL**: `CATALOGO` declarativo (T01…T17; T13/T15/T16/T17 declaradas y **apagadas** por falta de dato o de acceso al histórico), `construir_contexto`, `EvidenciaTiempos` (**vista de solo-evidencia: lo único que ve una regla**), `evaluar` (veredicto operativo), `evaluar_reglas`/`validar_tiempos` (informe CUMPLE/NO_CUMPLE/NO_EVALUABLE), `verificar_catalogo` (la declaración se valida al importar), configuración en caliente `cargar_config` (BD > JSON del volumen > defaults). Doc completa: **`VALIDACION_TEMPORAL.md`** |
| `validacion_temporal.py` | **API pública** del motor (re-exporta `reglas_tiempo`, sin lógica propia): `validar_registro(registro)` → informe serializable · `python -m incapacidad_ocr.validacion_temporal` imprime el catálogo y la config efectiva |
| `numeros_es.py` | numerales en español: `normalizar` (saneo OCR), `texto_a_entero`, `duracion_en_texto` (días en **números, letras o las dos**; exige ANCLA y veta por los dos lados), `duracion_de_celda` (celda de tabla: ancla POSICIONAL, la celda solo puede traer el valor), `numerales_en_texto` (enteros presentes → anclaje del LLM). Lector puro: no aplica reglas de dominio (ni el rango 1..540) |
| `processor.py` | `IncapacidadProcessor` une OCR+extractor y llama `normalizar_fechas()`. Guarda `MIN_OCR_CHARS` (no estructurar texto vacío → anti-fabricación de PII) |
| `erp.py` | `mapear_a_staging()` (JSON→fila staging), `Lookups` (cédula/CIE/EPS + nombre canónico), homologación de tipo, **validación documental** (`REQUISITOS_DEFAULT`, `EQUIVALENCIAS_DOC`, `validar_documentacion`, `canon_doc`) y **checklist de radicación ante la EPS** (`documentos_checklist_radicacion`, `validar_radicacion`, `Lookups.documentos_radicacion`, `etiqueta_doc`) |
| `db.py` | MySQL (BD ASTGU): `insertar_staging`, `insertar_alerta`, `listar_staging`, `obtener_staging`, `actualizar_revision`, `actualizar_estado` |
| `batch.py` | **Ingesta masiva por lotes**: escanea `INGESTA_ROOT/1_entrada`, agrupa por nomenclatura del nombre, OCR-ea solo el doc base, valida requisitos por tipo, inserta en staging + alerta, mueve a `3_archivo/` o `2_revisar/…`. `parse_nombre`, `procesar_todo`, `contar_pendientes`, `asegurar_estructura` |
| `webapp.py` | API FastAPI + estado del flujo (`PENDIENTE_REVISION`/`APROBADO`/`RECHAZADO`) + endpoints de lote |
| `static/index.html` | UI de una sola página (vanilla JS): procesar, formulario de revisión editable, bandeja, **panel "Procesar todos"** (lote) |
| `cli.py` · `python -m incapacidad_ocr.batch` | CLI de un doc (`cli`) · CLI del lote (`batch [--extractor rule\|hibrido] [--dry-run]`) |

**Endpoints:** `POST /api/procesar` (multipart) · `POST /api/mapear` (preview con correcciones) ·
`POST /api/registrar` (INSERT con `estado`) · `POST /api/revisar` (aprobar/rechazar/guardar) ·
`GET /api/staging[?estado=]` · `GET /api/staging/{id}` · **`GET /api/lote/pendientes`** (cuenta la entrada) ·
**`POST /api/lote/procesar`** (procesa todo `1_entrada/`) · **`GET /api/lote/estado`** (corrida programada) · `GET /api/health`.

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
python tests/test_processor.py           # unitarias deterministas (StubOCR + RapidOCR si está)
python tests/test_numeros_es.py          # numerales en español ("DOS", "DOS (2)") y sus falsos positivos
python tests/test_validacion_temporal.py # motor de tiempos: reglas, config en caliente, integración
python tests/test_reinicio_prueba.py     # reinicio de la prueba + invariantes del borrado en BD
python tests/test_radicacion.py          # checklist de radicación (parseo del JSON del ERP, sin BD)
python tests/test_authenticity.py        # señales de manipulación del documento
python tests/test_erp_diagnostico.py     # validación del diagnóstico contra el catálogo
python tests/test_ejemplos_reales.py     # evalúa los 8 documentos reales de ../Ejemplos

# Reglas de tiempos: ver el catálogo y la configuración EFECTIVA (comprobar un cambio en caliente):
python -m incapacidad_ocr.validacion_temporal
docker compose exec incapacidad-ocr python -m incapacidad_ocr.validacion_temporal

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

### Ingesta masiva por lotes

La carpeta `ingesta/` (raíz del repo) se monta en el contenedor como `/data/ingesta` (bind mount en
`docker-compose.yml`). **Tres zonas numeradas** (`1_entrada/` → `2_revisar/` → `3_archivo/`) + `_sistema/`;
el árbol y su porqué están en `ingesta/LEEME.md` (documento para RH). Los feeders dejan los documentos
en `ingesta/1_entrada/<whatsapp|correo|ventanilla>/` con la **nomenclatura** `cedula_TIPODOC[_NN].ext`
(ver §Reglas de dominio).

```bash
# Botón "Procesar todos" de la UI == este endpoint:
curl.exe -s http://localhost:8000/api/lote/pendientes                                   # cuenta 1_entrada
curl.exe -s -X POST http://localhost:8000/api/lote/procesar -H "Content-Type: application/json" -d '{"extractor":"rule"}'

# CLI equivalente (dentro del contenedor):
docker compose exec incapacidad-ocr python -m incapacidad_ocr.batch --dry-run           # reporta sin insertar/mover
docker compose exec incapacidad-ocr python -m incapacidad_ocr.batch --extractor rule    # procesa de verdad
docker compose exec incapacidad-ocr python -m incapacidad_ocr.batch --init              # solo crea el árbol

# Migrar un árbol viejo (inbox/procesados/incompletos/cuarentena) — correr en el HOST:
python scripts/migrar_estructura_ingesta.py --dry-run    # reporta
python scripts/migrar_estructura_ingesta.py              # mueve conservando sub-rutas

# Sembrar el escenario de prueba en 1_entrada/whatsapp (5 casos + 1 mal nombrado) — en el HOST:
python scripts/sembrar_demo.py
#   13742111  INCAPACIDAD+EPICRISIS  -> enf. general COMPLETO
#   63523940  INCAPACIDAD            -> enf. general INCOMPLETO (falta HISTORIA_CLINICA -> alerta)
#   1005542119 INCAPACIDAD+FURAT     -> accidente de trabajo COMPLETO   (sintético)
#   1095912481 VACACIONES            -> vacaciones COMPLETO             (sintético)
#   1098757631 PERMISO               -> licencia remunerada COMPLETO    (sintético)
#   documento_suelto.jpeg            -> mal nombrado (se omite -> 2_revisar/mal_nombrados/)
# Los reales salen de ../Ejemplos; los sintéticos son imágenes de texto (RapidOCR las lee).

# Corrida PROGRAMADA (cron in-process, APScheduler). Vacío = desactivada.
INGESTA_CRON='0 2 * * *' docker compose up -d incapacidad-ocr    # procesa 1_entrada cada día 02:00
INGESTA_CRON='*/5 * * * *' docker compose up -d incapacidad-ocr  # cada 5 min (demo)
docker compose up -d incapacidad-ocr                             # sin INGESTA_CRON -> desactivada
curl.exe -s http://localhost:8000/api/lote/estado                # {programado, cron, proxima_ejecucion, en_curso}
```

## Reglas de dominio (no romper)

- **Fecha de inicio:** preferir la rotulada "Fecha Inicia/Inicial". Si falta → `inicio = fin − (días − 1)`
  (inclusivo) y marcar `fecha_inicio_calculada` (aviso, no bloquea). Toda la reconciliación vive en
  `extract.normalizar_fechas()` y se reaplica en `erp.mapear_a_staging()` al corregir días/fin a mano.
- **`fechavencimiento = fechainicio + Numerodias`** (no inclusivo). **`dias` válido = 1..540**.
- **Días en NÚMEROS y en LETRAS** (`numeros_es.duracion_en_texto`, cableado en `RuleBasedExtractor`): los
  documentos reales escriben la duración como `2`, como `DOS` y como las dos a la vez (`DOS (2) DIAS`,
  `02 dos dia(s)`, `30 (TREINTA)`, `14 - CATORCE`, `DOS (02)`). **Todo candidato exige un ANCLA**: la unidad
  pegada al valor (`POR 4 DIAS`) o un rótulo de duración en el MISMO renglón (o en un renglón adyacente que
  contenga SOLO el valor) — sin eso, un léxico de numerales dispara en `una fuerza mayor`, en el `8 dia(s)`
  de la edad y en `hacetresdias` (la queja del paciente). **Y el ancla NO es suficiente:** en un certificado
  la palabra "días" aparece muchas veces y casi ninguna es la duración de la incapacidad, así que el
  candidato se veta **por los dos lados** — `_CONTEXTOS_PROHIBIDOS` justo ANTES del valor (edad, horas,
  semanas, `vigencia`, `valido`, `control`, `radicar`, `tratamiento`) y `_CONTEXTOS_PROHIBIDOS_DER` justo
  DESPUÉS (`3 dias HABILES` = plazo de trámite, `15 dias DEL MES de agosto` = fórmula de cierre notarial,
  `3 dias DE EVOLUCION` = relato clínico, `<N> DE <mes>` = día del mes, y `4 HORAS`/`40 SEMANAS`/`3 MESES` =
  otra unidad de tiempo, que es como el rótulo `Duracion` se llevaba la duración del permiso o del embarazo).
  Otras dos reglas del lector, las dos por falsos positivos reales: el rótulo escueto exige **PLURAL**
  (`Dias:`, nunca `Dia:` — en los formularios colombianos `Dia:` es un campo de FECHA) y la frase numeral se
  lee **COMPLETA** (leer un prefijo da un valor redondo y creíble: `CIENTO OCHENTA` → 100).
  **Cuando hay palabra y dígito manda el DÍGITO** y
  el desacuerdo se REGISTRA en `incapacidad.dias_letra` (int|None) y `incapacidad.dias_letra_coincide`
  (True/False solo si el documento trae las dos formas; None si trae una): son **instrumentación**, aquí
  NO se juzga si es adulteración (eso es de otro módulo). La señal de fraude respaldada por el corpus es
  **duración vs. rango de fechas**, y cuando `normalizar_fechas()` re-deriva un fin que no cuadraba con los
  días lo marca con `fecha_fin_recalculada` (aviso, no bloquea; solo puede dispararse si el documento traía
  las DOS cosas). **Ampliar el lector = una línea en el diccionario que toque**, sin lógica nueva:
  `_UNIDADES` (1..9 y apócopes) · `_ESPECIALES` (10..29, incluidos los pegados `veintiun…`) · `_DECENAS` ·
  `_CENTENAS`; los rótulos en `_ETIQUETAS_DURACION`, las degradaciones de OCR en `_CORRECCIONES_OCR`, los
  vetos en las dos listas de contextos. `mil` está **fuera del léxico a propósito** (un millar en palabras es
  el AÑO de una carta en prosa) pero **sí entra en la frase**, para que `dos mil veintiseis` se rechace
  entero en vez de leerse a trozos. Inventario de formas, degradaciones de OCR y falsos positivos:
  `dataset-falsedad/duraciones/01_evidencia.md`; los ataques al anclaje y su resultado, en
  `tests/test_numeros_es.py` secciones [10]-[13].
- **Validación de TIEMPOS — validar NO es reconciliar** (`reglas_tiempo.py`, API pública en
  `validacion_temporal.py`, doc completa en **`VALIDACION_TEMPORAL.md`**):
  `extract.normalizar_fechas()` sigue siendo el ÚNICO sitio que decide qué
  dato queda (rellena/deriva/sanea); el motor de reglas solo **opina sobre lo que traía el papel**
  (lee, compara, califica y explica) y **nunca escribe** `fecha_inicio`/`fecha_fin`/`dias`.
  **Una regla de coherencia solo puede dispararse con valores LEÍDOS, nunca calculados** — y eso está
  garantizado por construcción, no por disciplina: a la regla no se le pasa el contexto, se le pasa la
  vista `EvidenciaTiempos`, que **no tiene ningún campo `*_efectivo`** (`CAMPOS_EXIGIBLES` se DERIVA de
  esa vista y `ReglaTiempo` rechaza al importar un `requiere` que nombre otra cosa). Opinar sobre un
  valor DERIVADO marcaría documentos legítimos a los que el pipeline solo les completó un hueco, o daría
  un CUMPLE tautológico que parece una verificación.
  Corolarios que también son invariantes: **un override del auxiliar es evidencia solo si CAMBIA algo**
  (el formulario reenvía el valor que se le pintó —que puede ser el derivado— en cada llamada:
  `es_correccion_humana`), y un `dias` que es exactamente el span de las dos fechas leídas **no** es
  evidencia independiente (`dias_derivable_del_rango`).
  La evidencia se conserva porque `processor` guarda una **foto** de los tiempos leídos
  (`reglas_tiempo.CLAVE_SNAPSHOT`) ANTES de reconciliar, y llega al ERP en `fechafin_leida`/`dias_leidos`.
  Tres estados por regla: **CUMPLE / NO_CUMPLE / NO_EVALUABLE** (un dato ausente NO es una violación);
  `resumen.cobertura` dice qué parte se pudo comprobar de verdad, para no leer un COHERENTE de cobertura
  0,33 como "documento verificado".
  Severidades: **GRAVE/MEDIA** entran en `problemas` (→ `requiere_revision`, la aprobación pide
  confirmación como siempre), **LEVE** solo avisa. El motor **jamás rechaza solo**: marca y explica.
  **Añadir una regla = añadir un objeto a `reglas_tiempo.CATALOGO`** (receta paso a paso justo encima de
  esa tupla; el motor no se toca). **Cambiar severidad/umbral o apagar una regla SIN desplegar**:
  tablas `lp_reglas_tiempo_ia`/`lp_umbrales_tiempo_ia` (`sql/migracion_reglas_tiempo.sql`) o el JSON del
  volumen `ingesta/_sistema/control/reglas_tiempo.json` (plantilla comentada en
  `config/reglas_tiempo.example.json`, ruta alterna por `REGLAS_TIEMPO_CONFIG`) — prioridad **BD >
  archivo > defaults del código**, se relee en cada corrida y una config mal escrita se ignora entrada
  por entrada con aviso (nunca apaga una regla en silencio ni tumba el mapeo).
  **Falso positivo sobre un documento legítimo = bajar la severidad o exigir más evidencia, NUNCA
  ajustar el umbral hasta que acierte en el corpus** (31 documentos: sobreajustar ahí es peor que no
  validar). Dos decisiones ya tomadas así, con la medición detrás: `T09_INICIO_EN_FUTURO` **no aplica**
  a vacaciones (tipo 13) ni a prelicencia de maternidad (tipo 10) —empezar en el futuro es el propósito
  de esos documentos, y la exención es por TIPO para no debilitar la regla en las incapacidades—, y
  `T08_DURACION_SIN_RESPALDO` es **LEVE** (una duración larga sin fecha fin no es una contradicción del
  papel; bloqueaba prórrogas legítimas de 210 días). La aritmética duración↔rango vive SOLO aquí (T01):
  la comprobación duplicada que había en `authenticity.py` se eliminó (tenía otra tolerancia y otro
  canal → dos veredictos del mismo hecho).
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
- **Estado `POSIBLE_MANIPULACION`:** si `erp.mapear_a_staging` detecta `sospecha_manipulacion` (heurísticas de
  `authenticity.analizar_autenticidad` + señales de CIE-10/fechas en el propio `erp.py`) y el flujo no fue
  aprobado/rechazado explícitamente, el registro entra a staging con `estado=POSIBLE_MANIPULACION` en vez de
  PENDIENTE_REVISION (`erp.ESTADO_POSIBLE_MANIPULACION`) — así queda filtrable/identificable en la bandeja sin
  depender solo del badge 🚩 DUDOSA (`sospecha_manipulacion`/`motivo_sospecha`, que se conservan igual). Es
  ortogonal al ciclo aprobar/rechazar: `POST /api/revisar` con `guardar` conserva ese estado si la sospecha
  sigue vigente tras el re-mapeo; `aprobar`/`rechazar` lo reemplazan igual que a PENDIENTE_REVISION.
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
  romperían el patrón de días) — se calculan siempre por diferencia de fechas. **El lector de duraciones en
  letras queda DESACTIVADO aquí** (ni en `RuleBasedExtractor` ni en la fusión del híbrido, donde el LLM
  tampoco vota los días): "siete (07)" es un DÍA DEL MES y "dos mil veintiseis (2026)" el AÑO en palabras —
  son las formas C3/C5 invertidas, así que entender letras AUMENTA el riesgo en este formato. **El patrón del
  título (`extract._VACACIONES_ANCHOR`) es el ÚNICO guardián de toda esta regla** y por eso tolera la tilde en
  las DOS palabras (`Notificación`, `Período`): si no casa, la carta se procesa como incapacidad, se queda sin
  fechas, el tipo pasa de 13 a 3 y el lector de días devuelve el `7` del "día siete (07) de julio" — o sea
  exactamente lo que esta regla prohíbe. Ver `erp.mapear_a_staging` (`es_vacaciones`) y
  `extract._fechas_vacaciones`/`extract.es_formato_vacaciones`.
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
  del ancla de diagnóstico (además de "Diagnostico principal"). Los rótulos de **días** los resuelve
  `numeros_es` (`Dias de Incapacidad`, `Dias Incapacidad`, `Dias Inc.`, `No.Total dias`, `Duracion`, `Dias:`);
  el respaldo histórico de `extract._dias_por_etiqueta` son **dos patrones de RÓTULO** que solo cubren
  variantes fuera de esa lista, con el guardarraíl `_NUM_DIAS` (máx. 3 cifras, nunca pegado a `/ - . :`) y en
  **plural** (`el dia 15 de agosto` es una fecha en prosa, y en singular el respaldo devolvía 15). El tercer
  patrón histórico —número pegado a la unidad SIN rótulo— se **eliminó**: eso ya lo lee `numeros_es` por el
  ancla de unidad, y allí no había forma de vetar lo que va detrás (`3 dias habiles`), así que era la puerta
  por la que volvían a entrar las duraciones que el módulo rechaza.
- **Tabla "DETALLE DE LA INCAPACIDAD"** (formato Clínica del Cesar): 5 columnas (Causa Externa/Diagnóstico/Días
  Inc./Inicio/Finalización) seguidas de sus 5 valores en bloque — se parsea aparte
  (`extract._extraer_detalle_incapacidad`) porque es más fiable que las heurísticas genéricas y evita falsos
  positivos (tomar "Dias Inc." como si fuera la descripción del diagnóstico, etc.). La celda de días se lee
  como LÍNEA completa (`_dias_de_celda` → `numeros_es.duracion_de_celda`): la posición en la tabla ya es el
  ancla, así que vale el dígito, la palabra o las dos — antes, una celda que no fuera dígitos puros tumbaba
  TODO el bloque (con su CIE-10 y sus fechas). **La celda solo puede contener el valor**: cuando el OCR
  desplaza el bloque, en esa columna caen un CIE-10 (`J069`), una dosis (`X 500 MG`) o la paginación
  (`1 de 1`) — prestarle a la celda un rótulo escrito (`"Dias: " + celda`) las leía como 69, 500 y 1 días, y
  todas caen dentro de 1..540, así que llegaban a la revisión sin ninguna señal.
- **Ingesta por lotes — nomenclatura de archivos** (`batch.py`): los documentos llegan **separados**, uno por
  archivo, nombrados `cedula_TIPODOC[_NN].ext` (`parse_nombre`, **sin fecha**). **Llave de caso** = la `cedula`
  (agrupa el trámite; la fecha sale del OCR). `TIPODOC` base (único que se OCR-ea) = `INCAPACIDAD`/`PERMISO`/`VACACIONES`; adjuntos
  (solo se verifican por nombre, no se OCR-ean) = `FURAT`/`FURIPS`/`EPICRISIS`/`HISTORIA`/`NACIDOVIVO`/
  `REGISTROCIVIL`/`DEFUNCION`/`CEDULA`/`FORMULA`/`ORDEN`/`OTRO`. La cédula del nombre se **coteja** con la que
  el OCR lee de la incapacidad (mismatch → se anota en `problemas`); **nunca se cruzan cédulas distintas**.
  Diseño completo en `PLAN_INGESTA_MASIVA.md`.
- **Ingesta por lotes — estructura de carpetas** (`batch.py`, constantes al inicio del módulo; documento para
  RH en `ingesta/LEEME.md`): **tres zonas numeradas** que se leen en orden de flujo, más un área interna.
  `1_entrada/<whatsapp|correo|ventanilla>/` (lo único que se escribe a mano; sub-carpeta → estado de recepción,
  `original` sigue aceptándose como sinónimo de `ventanilla`; RH puede anidar más subcarpetas, el escaneo es
  **recursivo**) → `2_revisar/{mal_nombrados,faltan_soportes,datos_por_revisar,con_error}/` (**todo lo que necesita
  acción humana**, junto, con **una sub-carpeta por MOTIVO**: falta un soporte ≠ el soporte está y el
  dato necesita revisión → la carpeta dice qué hacer) → `3_archivo/` (historial de los COMPLETOS) → `_sistema/{logs,tmp,control}/`.
  **Invariante: cada archivo termina en exactamente UNA zona** → "¿dónde quedó?" tiene respuesta única.
  `3_archivo/` y las sub-carpetas por caso de `2_revisar/` (`faltan_soportes`, `datos_por_revisar`) se
  organizan por **`<Nombre persona>/AAAA/MM/DD`** — nombre = primer nombre
  + primer apellido del catálogo (`extract.primer_nombre_apellido` sobre el nombre canónico resuelto por
  cédula); fecha = inicio de la incapacidad (si el OCR no la leyó → `sin_fecha`). La cédula y el diagnóstico
  NO van en el **directorio**; el **nombre de archivo** sí conserva la cédula (decisión 2026-09-01: se prefirió
  trazabilidad contra lo que envió RH sobre el renombrado sin PII del plan §4.4 — el volumen es local con ACL).
  Las claves del resumen del lote nombran las carpetas:
  `completos`/`faltan_soportes`/`datos_por_revisar`/`con_error`/`mal_nombrados`.
  `asegurar_estructura()` (o `batch --init`) crea el árbol; `scripts/migrar_estructura_ingesta.py` migra el
  árbol viejo (`inbox`/`procesados`/`incompletos`/`cuarentena`) y el runner **sigue leyendo** un `inbox/` viejo
  si existe (ver `ENTRADA_LEGACY`) para no dejar documentos huérfanos.
- **Catálogo CIE-10 y la señal «este diagnóstico no existe»** (`datos/cie10.csv`,
  `scripts/descargar_cie10.py`, `erp.Lookups.categoria_subdividida`): el catálogo público (14.484
  códigos, CIE-10 en español) se descarga UNA vez y se versiona — es un dato de referencia, no una
  API de IA, y en runtime la consulta es un `SELECT` local. Lo carga `scripts/sembrar_bd_prueba.py`
  **reemplazando** `lpdiagnosticos` por completo (mezclarlo con códigos puestos a mano TAPA los
  huecos reales del catálogo y rompe la guarda de abajo). Tres condiciones para que la señal marque
  sospecha, y ninguna es opcional: (1) el catálogo está cargado —`catalogo_diagnosticos_disponible`,
  sin él nada resuelve y marcaría el 100%—, (2) el código tiene FORMA de CIE-10 (letra + dígitos:
  un `FECHA` o `0039` del OCR es una lectura fallida, no un código falso), y (3) el catálogo
  **subdivide** la categoría de 3 (`categoria_subdividida`): la edición pública no subdivide 276 de
  sus 2070 categorías, así que un `A09.9` ausente es un hueco de la edición, no un fraude. Medido
  sobre el corpus: la detección pasó de 2 a 4 de 9 adulteradas manteniendo 0 falsos positivos
  sobre las 16 legítimas; sin la condición (3) aparecían 2. Al llegar `lpdiagnosticos` de ASTGU
  solo hay que cargarlo: el código no cambia.
- **Validación documental por tipo** (`erp.validar_documentacion`): el conjunto de `TIPODOC` presentes del caso
  se cruza contra los requeridos por el tipo — `lprequisitos_eps` (por `idlpentidad+idlptipoausentismo`,
  `obligatorio=1`) prevalece; si no hay filas, `erp.REQUISITOS_DEFAULT`. Se aplican **grupos de equivalencia**
  (`EQUIVALENCIAS_DOC`): p.ej. una `EPICRISIS` satisface el requisito de `HISTORIA_CLINICA` (soporte clínico), y
  `NACIDO_VIVO`≡`REGISTRO_CIVIL`. Caso incompleto → `documentacion_estado=INCOMPLETA` + fila en
  `lp_alertas_documentacion`; igual entra a staging como `PENDIENTE_REVISION` (el auxiliar decide).
- **Checklist de RADICACIÓN ante la EPS** (`lpeps.cheklistradicaciones`): exigencia **distinta y mayor** a la de
  la recepción interna — es lo que hay que entregarle a la EPS para **cobrar** el ausentismo. El campo es un JSON
  por EPS con la forma `{"ausentismos":[{"idlptipoausentismo":N,"documentos":[{"nombredocumento":…}]}]}`,
  configurado para los tipos **2/3/5/8/9/10/11**. **Gotcha del dato:** el ERP lo guarda ENVUELTO en comillas
  dobles sin escapar el contenido (`"{"ausentismos":…}"`) → **no es JSON válido tal cual**, hay que quitar esas
  comillas antes de parsear (`erp.documentos_checklist_radicacion`); y el certificado laboral viene escrito
  `CERTICADO LABORAL` (error de digitación del catálogo). Solo ~19 de 62 EPS lo tienen cargado y varios tipos
  quedan con lista vacía: **sin checklist NO se opina** (`radicacion_estado=None`), nunca se inventa un requisito.
  `erp.validar_radicacion` aplica las mismas equivalencias que la recepción **salvo entre documentos que la EPS
  pidió por separado** (si exige nacido vivo Y registro civil, se exigen los dos). Desde la ingesta
  (`batch.procesar_caso`) el faltante **avisa, no bloquea**: el caso NO se manda a `incompletos/` por esto — se
  registra una fila en `lp_alertas_documentacion` con `estado=PENDIENTE_RADICACION` (20 chars, justo el máximo
  de esa columna) y sale en el resumen del lote (`pendientes_radicacion`) y en la tabla de la UI.

## Restricciones / convenciones

- **100% local, sin API paga.** Nada de datos a internet en runtime.
- **Ollama desde el servidor, no el cliente** (anti-SSRF): la URL/modelo se fijan por env
  (`OLLAMA_URL`/`OCR_MODEL`/`LLM_MODEL`). La API NO acepta esos parámetros del cliente.
- **No fabricar PII:** si el OCR no da texto (`< MIN_OCR_CHARS`), NO llamar al extractor → registro vacío + `aviso`.
- **Errores al cliente genéricos** (sin rutas/internos); el detalle va al log del servidor; **no loguear** contenido (PII).
- **Imports perezosos** de `httpx`/`rapidocr`/`mysql.connector` (el módulo importa aunque falte la dependencia).
- **`moondream` NO sirve** para OCR (captioning); usar `qwen2.5vl:3b` para visión.
- **Híbrido** es el extractor por defecto (RapidOCR + LLM fusionados, degrada a solo reglas si Ollama no está).
  **Guardas anti-alucinación de `_merge_records`** (probadas con un `StubLLM` en `tests/test_processor.py`, sin
  Ollama): las fechas del LLM se aceptan solo si aparecen en el texto OCR (`_dates_in_text`) y **los días
  igual** (`_dias_llm` + `numeros_es.numerales_en_texto`: el dígito **o la palabra** tienen que estar en el
  documento), con entero forzado y rango 1..540. Si las reglas leyeron la duración con doble evidencia
  (dígito y palabra que concuerdan) o con el inicio anclado, **manda reglas**. `tipo_documento` es un escalar
  del esquema y lo fija el detector de formato de las REGLAS, nunca el LLM.
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
- **Documentos pesados:** subida hasta **50 MB** (`MAX_UPLOAD_BYTES`). El PDF se rasteriza **página a página en
  streaming** (`preprocess.load_pages` es un GENERADOR → una página en RAM a la vez), hasta `MAX_PDF_PAGES` (30);
  cada página se acota a `OCR_MAX_PIXELS` (40 MP) antes del OCR, y `MAX_IMAGE_PIXELS` (200 MP) frena bombas de
  descompresión. Si un doc pesado falla, subir esos topes por env o bajar `PDF_RENDER_SCALE`. NO volver a materializar
  todas las páginas en una lista (era la causa del pico de RAM).
- **Corrida programada** (`webapp.py`, APScheduler in-process): se activa solo si `INGESTA_CRON` está
  definido; corre en el contenedor web (1 worker uvicorn). Un `threading.Lock` (`_lote_lock`) es compartido
  por la corrida manual (`/api/lote/procesar`) y la programada → **nunca se solapan** (manual ocupada → 409;
  programada ocupada → se omite). Es un MVP: para multi-worker/multi-instancia habría que mover el lock a la
  BD (`GET_LOCK`, ver `PLAN_INGESTA_MASIVA.md` §5/§9.5) y/o usar el servicio `ocr-worker` dedicado del plan.
- La carpeta **`ingesta/` es un bind mount** (`./ingesta:/data/ingesta`, env `INGESTA_ROOT`); editar su contenido
  desde el host se ve al instante en el contenedor (no requiere reconstruir). El contenedor (usuario no-root)
  **escribe** ahí para mover archivos — en Docker Desktop Windows el bind mount lo permite. La ingesta por lotes
  **no tiene ledger/dedup ni concurrencia** todavía (es la Fase 2 del plan): reprocesar es seguro solo porque los
  archivos se mueven fuera de `1_entrada/` al terminar.
- **`_sistema/tmp` y `_sistema/control` se crean pero AÚN NO se usan** (son de la Fase 2 del plan: escrituras
  atómicas y centinela on-demand). Están en el árbol para que la estructura no cambie al implementarlas.
