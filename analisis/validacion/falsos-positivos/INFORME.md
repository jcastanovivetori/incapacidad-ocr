# Frente `falsos-positivos` — caza de marcas indebidas sobre documentos LEGÍTIMOS

Verificación del motor de tiempos (`incapacidad_ocr/reglas_tiempo.py`, API
`validacion_temporal.py`) desde el único ángulo que importa a 7000 casos/mes: **¿marca
incapacidades legítimas?** Rol: verificador (no se editó nada del paquete ni de sus pruebas).

- Fecha de la corrida: **2026-09-02** · Python: `<repo>/.venv/Scripts/python.exe`
- 100 % local, sin OCR: se reutiliza el `texto_plano` ya extraído de
  `dataset-falsedad/ocr/{reales,real,falsas,falsa}/*.json` y se **replica el orden de
  `processor.run()`** (extractor → foto `CLAVE_SNAPSHOT` → `normalizar_fechas`), porque esos
  JSON se produjeron ANTES de que existiera la foto y evaluarlos tal cual mediría un
  pipeline que ya no existe.
- PII (Ley 1581): los documentos se citan por su ID del corpus (`R01`…`R16`, `F04`, `F09`) +
  los 8 primeros del sha256 y por nombre de ARCHIVO. Ningún dato de paciente.

## Léelo en 30 segundos

1. **Sobre los 16 documentos legítimos del corpus el motor no marca NADA**: 0 GRAVE,
   0 MEDIA, 0 LEVE, con dos fechas de proceso distintas. El frente está limpio ahí.
2. Pero de esos 16, **solo 3** (`R09`, `R11`, `R13`) reciben de verdad el cruce
   duración↔rango. En otros **4** (`R06`, `R07`, `R08`, `R12`) el número de días **lo
   calculó el propio extractor a partir de las dos fechas** y entra en la foto como si el
   papel lo imprimiera: T01 "CUMPLE" es una tautología y el informe dice `COHERENTE` con
   `cobertura 0.846`, indistinguible de una comprobación real. `R07` **sí imprime**
   `14- CATORCE` y el lector no lo ve.
3. **6 mecanismos reproducibles de falso positivo** salen a la luz en cuanto se sale del
   camino feliz, y **5 de los 6 no son del motor: son de la LECTURA** (emparejamiento
   rótulo↔valor sin coordenadas del OCR). Tres de ellos son GRAVE y en dos de ellos la fila
   que entra al ERP queda además con datos erróneos.
4. **Una caída**: `erp.mapear_a_staging` lanza `OverflowError` con una fecha de año 9999.
5. **Un falso positivo de dominio, seguro y frecuente**: `T09_INICIO_EN_FUTURO` (MEDIA)
   marca toda **notificación de vacaciones** y toda **prelicencia de maternidad**, cuyo
   inicio futuro es lo normal.

## Qué se atacó (para que se sepa qué NO se atacó)

| Ataque | Script | Casos | Falsos positivos |
|---|---|---|---|
| 16 documentos legítimos del corpus, catálogo completo, 2 fechas de proceso | `01_barrido_reales.py` | 32 evaluaciones | **0** |
| Procedencia del `dias` que juzga el motor (evidencia vs. derivado) | `02_procedencia_dias.py` | 16 | 4 tautológicos |
| Legítimos atípicos: 1 día, prórroga contigua, cruce de año, maternidad 126, un solo campo leído, vacaciones futuras, vacaciones multi-periodo, retroactiva, convención no inclusiva, prelicencia, 202 del rótulo, 210 días sin fin | `03_casos_legitimos_atipicos.py` | 16 | **1** + 3 riesgos materializados |
| Caminos que no son OCR: alcance real de cada regla, correcciones del auxiliar, registro sin foto, config en caliente | `04_caminos_no_ocr.py` | 4 + 6 + 3 + 8 | **1** |
| Lectura rótulo↔valor (valor antes del rótulo, celdas SURA invertidas, cruce de año, fechas mm/dd) y solape con `authenticity` | `05_lectura_y_solapes.py` | 4 + 33 | **3** |
| Respaldo de `Duracion` leyendo el día del mes + alcance de la 2ª implementación del cruce | `06_duracion_y_autenticidad.py` | 4 + 31 | **1** |
| Robustez: 17 registros degenerados × 2 caminos, 4 overrides raros, 4 configs rotas | `07_robustez.py` | 42 | 1 **caída** |
| Año emparejado por posición (pie legal con año) | `08_anio_por_posicion.py` | 4 + 16 | **1** + 1 fila silenciosamente errónea |

No se atacó: el histórico del empleado (T15/T16/T17 están apagadas y sin adaptador), el día
de la semana (T13 apagada), el camino del LLM (`HybridExtractor` con Ollama arriba), ni la UI.

---

## H1 · GRAVE — el `dias` DERIVADO de las dos fechas viaja en la foto como si fuera el impreso

**Dónde.** `extract.py:932` (`RuleBasedExtractor`) y `extract.py:760` (permisos):

```python
rec["incapacidad"]["dias"] = dias_val if dias_val is not None else dias_calc   # dias_calc = _days_between(inicio, fin)
```

`processor.py:56` toma la foto **después** de eso, así que `snapshot['dias']` puede ser una
resta de fechas. `reglas_tiempo.valores_leidos` lo entrega como `dias_leido`, y
`ETIQUETA_DATO` lo describe al auxiliar como *"el número de días impreso en el documento"*.
El comentario de `reglas_tiempo.py:412-417` razona esto solo para el camino SIN foto; con foto
el mismo problema entra por delante.

**Medido** (`02_procedencia_dias.py`):

| Procedencia del `dias` que juzga el motor | Documentos legítimos |
|---|---|
| leído por rótulo/unidad/letra (**evidencia**) | 7 — `R01 R09 R10 R11 R13 R14 R15` |
| **derivado** de las dos fechas | 4 — `R06 R07 R08 R12` |
| no leído | 5 — `R02 R03 R04 R05 R16` |

De los 7 documentos donde T01 llegó a evaluarse (`R06 R07 R08 R09 R11 R12 R13`), **4 son
tautológicos**: el valor comparado se calculó de lo que se compara contra. `R07` es el caso
que más duele: el papel imprime `14- CATORCE` como `Duracion` (verificado en el `.txt` del
corpus y en `senales/aritmetica_fechas/INFORME.md`), `_dias_por_etiqueta` devuelve `None`
porque el valor cae dos renglones más abajo del rótulo, y el motor informa `T01 CUMPLE`,
`veredicto COHERENTE`, `cobertura 0.846`. El único cruce genuino disponible se salta en
silencio y el informe no lo dice.

**El falso positivo.** `fecha_fin` está en la lista blanca de overrides de la API
(`webapp.py:89 CAMPOS_OVERRIDE`). Caso B1 de `04_caminos_no_ocr.py`:

- entrada: documento con `inicio=2026-08-20`, `fin=2026-08-28` **leídos** y `dias=9`
  **derivado** de ellos (el OCR leyó mal el día del fin); el auxiliar corrige por API
  `campos = {"fecha_fin": "2026-08-22"}`.
- esperado: no hay nada que objetar al papel; los días deberían recalcularse a 3.
- obtenido: `T01_DURACION_VS_RANGO` **GRAVE** — *"Los tiempos del documento no cuadran: el
  rango 2026-08-20 → 2026-08-22 son 3 día(s), pero declara 9 día(s) … desfase de -6"*.
  El documento no dice eso; lo dice el pipeline. **Y la fila queda mal**:
  `Numerodias=9`, `fechavencimiento=2026-08-29`, `fechafin_leida=2026-08-22` — el
  vencimiento contradice la evidencia de la propia fila.

**Corrección propuesta** (no aplicada: `extract.py` es de solo lectura en este frente):

1. Que el extractor publique la procedencia: `dias_calculado: bool` (igual que ya publica
   `fecha_inicio_calculada`). Es una línea en `extract.py:932`/`:760`.
2. Que `reglas_tiempo.snapshot_leidos` la conserve y `valores_leidos` **descarte
   `dias_crudo` cuando el valor fue derivado y no hay `dias_letra`**: T01 pasa a
   `NO_EVALUABLE`, la `cobertura` baja y el informe deja de prometer una comprobación que no
   hizo. Sin tocar el motor: es la misma mecánica de `inicio_calculado`.
   *Variante sin cambiar `extract`*: en `snapshot_leidos`, marcar
   `dias == (fin - inicio).days + 1` como sospechoso de derivación. Es una heurística
   (perdería el caso legítimo en que el papel imprime los tres y cuadran), así que se
   prefiere (1).
3. En `erp.py:668`, recalcular `num_dias` **también** cuando llega `overrides["fecha_fin"]`
   (hoy solo se recalcula si `num_dias` es falsy). Sin esto, la fila queda incoherente
   consigo misma aunque el motor calle.

---

## H2 · GRAVE — T01 / T02 / T04 se disparan por MALA ATRIBUCIÓN rótulo↔valor, no por el papel

El pipeline entrega **una sola cadena** sin cajas del OCR (`ocr._combinar_paginas`), así que
rótulo y valor se emparejan por orden del texto. Cuando ese orden no es el esperado, el motor
recibe una tripleta bien formada y **mal atribuida**, y las tres reglas GRAVE acusan a un
documento legítimo. Tres mecanismos, los tres reproducidos.

### H2a — el respaldo de `Duracion` lee el DÍA DEL MES de la celda vecina

`extract.py:330`: `duraci[oó]n\b[^\d]{0,10}` + `_NUM_DIAS`. En el formato SURA el rótulo
`Duracion` cae pegado a la celda de la fecha escrita, cuyo día del mes es un número suelto de
1-2 cifras — justo lo que `_NUM_DIAS` admite.

- entrada (`06_duracion_y_autenticidad.py`, variante `D_solo_rotulo`): certificado SURA
  **legítimo** `10/07/2026 → 23/07/2026`, 14 días, con el OCR omitiendo el rótulo
  `Fecha Fin` (`…Duracion\nJUEVES 23 DE JULIO…`).
- esperado: `dias = 14`, sin hallazgos.
- obtenido: `_dias_por_etiqueta → 23`, `T01_DURACION_VS_RANGO` **GRAVE**
  (*"el rango … son 14 día(s), pero declara 23"*) **y la fila entra con
  `dias=23`, `fecha_fin=2026-08-01`**: nueve días de incapacidad de más.
- precedente del corpus: `R16` (272d0d3d, **real**) leía `dias = 202` de `"Duracion\nDE2026"`
  (`senales/aritmetica_fechas/INFORME.md` §3.2). Hoy `R16` da `None` — el defecto sigue vivo
  y `R07` se salva por **un carácter**: con `Duracion\nFecha Fin\n` (11 caracteres hasta el
  dígito) no dispara; con `Duracion\n` (1 carácter) sí.
- corrección: exigir el valor en la **misma línea** que el rótulo (`[^\d\n]{0,10}`), como ya
  hace el segundo patrón de la misma función, y/o vetar el candidato cuando el dígito
  pertenece a una fecha escrita (`\d{1,2}\s*DE\s*<mes>`).

### H2b — las dos celdas de fecha escritas se asignan por orden de aparición

`extract._fecha_inicio_fin_escrita` (`extract.py:156-180`): 1ª pareja día+mes = inicio,
2ª = fin, sin comprobación. **El corpus demuestra que el OCR emite la celda del FIN primero**:
en `F04` (e0ee54fd) el texto real es `… JUEVES 04 DE\nMARTES 02\nFecha Inicio\n-DOS\nDuracion\nFecha Fin …`.

- entrada (`05_lectura_y_solapes.py`, `P2`): certificado SURA **legítimo**
  `10/07/2026 → 23/07/2026` con las celdas en el orden de `F04` (la mayor primero).
- esperado: sin hallazgos.
- obtenido: se lee `inicio=2026-07-23`, `fin=2026-07-10` → `T02_FIN_ANTES_DE_INICIO`
  **GRAVE**: *"La fecha fin leída (2026-07-10) es ANTERIOR a la de inicio (2026-07-23): el
  rango es imposible"*. La fila entra con `inicio=2026-07-23`, `fin=2026-08-01`, `dias=10`.
- hoy está **dormido**: en `F04` los meses salen degradados (`SEPT1EMBRE`) y el lector no casa
  ninguna pata; en `R07` (el único legítimo que usa esta vía) las celdas salieron en el orden
  correcto. Basta que las dos cosas coincidan una vez.
- corrección: sin coordenadas, **abstenerse o ordenar cronológicamente** las dos fechas y
  marcar `orden_incierto` (es lo que ya hace la sonda de `senales/aritmetica_fechas`, que en
  ese caso usa la prueba libre de orden `|span|+1 == dias`); y bajar T02/T04 a MEDIA mientras
  no exista procedencia por campo (cambio de configuración, sin desplegar).

### H2c — el AÑO se empareja por posición sobre TODO el texto

Misma función, `extract.py:168`: `years = re.findall(r"(?i)\bDE\s*(\d{4})\b", text)` y
`zip(dm[:2], years[:2])`. Ningún requisito de cercanía. Los certificados de EPS citan
resoluciones y decretos con año.

- entrada (`08_anio_por_posicion.py`, `P5b`): el mismo certificado legítimo
  `10/07/2026 → 23/07/2026` con `"Expedido conforme a la Resolucion 2388 DE 2016"` **antes**
  de las celdas.
- esperado: sin hallazgos, fila `2026-07-10 → 2026-07-23`, 14 días.
- obtenido: `inicio = 2016-07-10` → `T04_RANGO_MAYOR_AL_MAXIMO` **GRAVE**
  (*"dura 3666 día(s), por encima del máximo de 540"*) + `T10_INICIO_MUY_ANTIGUO` LEVE, y la
  fila entra con `fechainicio=2016-07-10`, `fecha_fin=None`, `dias=None`.
- **peor variante** (`P5d`, dos años en el pie legal): las **dos** fechas se van a 2016, la
  tripleta queda coherente consigo misma y **ninguna regla puede verlo** — la fila entra con
  diez años de error y solo un aviso LEVE. Un falso NEGATIVO producido por el mismo defecto.
- cuánto falta para que pase: de los 16 legítimos, `R07` es el único que usa esta vía (2
  parejas día+mes y exactamente 2 años, en el orden correcto). Está a **un** `DE <año>` de
  distancia.
- corrección: exigir que el año esté a ≤ N caracteres de su día+mes (o dentro del mismo
  bloque), y si hay más años que fechas, no emparejar.

---

## H3 · GRAVE — `mapear_a_staging` se cae con `OverflowError` (fecha de año 9999)

- dónde: `erp.py:864` → `fecha_venc = (di + timedelta(days=num_dias)).isoformat()`.
  `extract._norm_date` acepta cualquier año de 4 cifras, y `fecha_inicio` está en
  `CAMPOS_OVERRIDE`.
- entrada (`07_robustez.py`, caso *"año 9999"*): `{"fecha_inicio": "9999-12-30",
  "fecha_fin": "9999-12-31", "dias": 2}`.
- esperado: la fila entra a staging con los hallazgos que correspondan (el motor ya emite
  `T09_INICIO_EN_FUTURO`); nunca una excepción — *"nunca se rechaza solo"* implica que un
  documento legítimo con un dígito mal leído no puede perderse.
- obtenido: `EXCEPCION OverflowError: date value out of range`. Por la API es un 500 y el
  documento **no llega a staging**.
- el motor de reglas **sí** degrada bien (el `try/except` por regla de
  `reglas_tiempo.evaluar_reglas:1030` deja la regla `NO_EVALUABLE`); el que no protege es
  `erp`.
- corrección: envolver el cálculo de `fechavencimiento` (y el de `fecha_inicio` derivada,
  `erp.py:664`) en `try/except OverflowError` dejando la columna en `NULL` + problema para el
  auxiliar; o acotar el año en `extract._fecha_valida`.

---

## H4 · MEDIA — `T09_INICIO_EN_FUTURO` marca documentos cuyo inicio futuro es lo NORMAL

`T09` (MEDIA → `problemas` → `requiere_revision`) se aplica a **todos** los tipos de
documento. Dos tipos que el repo ya soporta tienen el inicio en el futuro por definición:

| entrada | esperado | obtenido |
|---|---|---|
| Carta *"Notificación Periodo de Vacaciones"* con el periodo a **45 días** (`03_…py`, `LF`); `hoy` = el día en que RH la radica | sin hallazgos: notificar por adelantado es el propósito del documento | `T09_INICIO_EN_FUTURO` **MEDIA** — *"La fecha de inicio (2026-10-17) está en el futuro, más de 30 día(s) después de hoy"* → `veredicto REVISAR`, `requiere_revision=True` |
| Prelicencia de maternidad de 126 días que empieza a 45 días (`03_…py`, `LJ`) — el tipo **10 Prelicencia** existe en `erp.ETIQUETAS_TIPO`/`NIVEL_INCAPACIDAD_DEFAULT` | sin hallazgos | `T09_INICIO_EN_FUTURO` **MEDIA** |

Es el falso positivo **más caro** de los encontrados: no depende de que el OCR falle, se
repite en el 100 % de las vacaciones notificadas con más de un mes de antelación, y las
vacaciones son un flujo completo del repo (`extract.es_formato_vacaciones`, tipo 13).

**Corrección.** Lo correcto es que T09 no opine sobre los tipos cuyo inicio futuro es
legítimo. El contrato del motor lo permite: `tipo_documento` e `id_tipo` **ya están en
`ContextoTiempos`** y no son producto de la reconciliación (el detector de formato los fija
en las reglas), solo faltan en `CAMPOS_EXIGIBLES` (`reglas_tiempo.py:488`). Propuesta:

1. añadir `"tipo_documento"`/`"id_tipo"` a `CAMPOS_EXIGIBLES` (son evidencia del documento,
   no un `*_efectivo`);
2. en `_t09_inicio_en_futuro`, `return None` para `tipo_documento in ("vacaciones",)` /
   `id_tipo in (10, 13)`, con el comentario de por qué;
3. mientras eso no exista, **hoy y sin desplegar**: `dias_futuro_max = 120` silencia el caso
   (medido: `04_caminos_no_ocr.py` §D) o `T09_INICIO_EN_FUTURO → LEVE` (medido: sigue
   avisando y deja de bloquear). Las dos opciones debilitan la regla para las incapacidades;
   la exención por tipo no.

---

## H5 · MEDIA — 4 de las 14 reglas activas NO pueden disparar por el camino del documento

`extract` **sanea o descarta antes** de que `processor` tome la foto, así que el valor
"detectado pero inutilizable" nunca llega al motor:

| Sonda (`04_caminos_no_ocr.py` §A) | El documento imprime | La foto recibe | Regla que debería opinar | Estado real |
|---|---|---|---|---|
| `fecha_imposible` | `Fecha Inicio: 31/02/2026`, `Fecha Fin: 05/13/2026` | `inicio=None`, `fin=None` | T06, T07 (MEDIA) | `NO_EVALUABLE` |
| `dias_0` | `Dias de Incapacidad: 0` | `dias=None` | T03 (GRAVE), T05 | `NO_EVALUABLE` |
| `dias_900` | `Dias de Incapacidad: 900` | `dias=None` | T03 (GRAVE) | `NO_EVALUABLE` |

Causa: `extract._norm_date` devuelve `None` ante una fecha fuera de calendario, y
`_dias_por_etiqueta` / `_dias_de_celda` / `_days_between` acotan a 1..540 devolviendo `None`.
Consecuencias:

- se rompe la promesa escrita en el `CATALOGO` (*"el motor NUNCA debe decir 'no se detectó' un
  dato que el documento sí imprime"*): con `31/02/2026` en el papel el auxiliar lee
  **"No se detectó la fecha de inicio"** y va a buscar lo que ya está impreso;
- la afirmación de que T03 recupera el mensaje *"cuando `normalizar_fechas` anula el valor"* no
  se cumple: el valor se anula antes, en `extract`;
- `cobertura` cuenta esas 4 reglas como `CUMPLE`, así que **infla** la sensación de
  verificación (mismo problema que H1).
- la prueba [8] del suite del repo pasa porque construye el registro **a mano**, sin pasar por
  `extract`.
- el corpus ya había detectado el mismo agujero desde el otro lado: el check `AF05` de
  `senales/aritmetica_fechas` existe justamente porque *"el pipeline actual descarta en
  silencio la fecha inválida y el rastro se pierde"*.

**Corrección propuesta** (`extract.py` es de solo lectura aquí): conservar la cadena
rechazada en el registro (`fecha_inicio_cruda`, `fecha_fin_cruda`, `dias_crudo`) y que
`snapshot_leidos` la incluya. Es aditivo: `fecha_iso`/`entero_dias` ya devuelven `None` sobre
esas cadenas, así que `*_leido` no cambia y T06/T07/T03/T05 pasan a poder opinar.

---

## H6 · MEDIA — dos implementaciones del MISMO cruce días↔rango, con tolerancias distintas

`authenticity._revisar_consistencia_fechas_dias` (`authenticity.py:104-134`) hace el mismo
cálculo que `T01_DURACION_VS_RANGO`, con **tolerancia ±1** frente a la de T01
(`desfase_tolerado_dias = 0`), y llega al auxiliar por otro canal: `problemas` +
`sospecha_manipulacion` + `estado = POSIBLE_MANIPULACION`.

- **Hoy está muerta**: medido sobre los 31 documentos del corpus (`06_…py` §2) dispara
  **0/16 legítimos y 0/15 falsas**, porque `processor.run()` llama a `normalizar_fechas()`
  (`processor.py:57`) **antes** de `analizar_autenticidad()` (`processor.py:60`) y el registro
  que recibe ya está reconciliado. Su propio docstring afirma lo contrario (*"esta señal es
  sobre lo que trae CRUDO el documento"*).
- Si despertara (registro armado a mano, otro llamador), el auxiliar leería **dos mensajes
  distintos del mismo hecho**. Reproducido en `05_lectura_y_solapes.py` §2:
  - `authenticity`: *"Los días declarados (2) no coinciden con el rango de fechas del
    documento (2026-06-05 a 2026-07-06 = 32 días)"*
  - motor: *"Los tiempos del documento no cuadran: el rango 2026-06-05 → 2026-07-06 son 32
    día(s), pero declara 2 día(s) …"*
- Y las dos discrepan **exactamente en el caso que importa**: con desfase +1 (el único acierto
  propio de la familia de aritmética en el corpus, `F04`) `authenticity` dice *no sospechosa*
  y el motor dice `T01` GRAVE.
- corrección: eliminar la comprobación de `authenticity` y dejar T01 como única verdad (ya
  tiene la tolerancia como umbral configurable), o pasarle `inca[CLAVE_SNAPSHOT]` y dejar el
  ±1 solo si el cliente confirma que hay emisores no inclusivos (ver H7).

---

## H7 · MEDIA (riesgo, sin evidencia en el corpus) — emisor con convención NO inclusiva

Si alguna EPS imprime en "Fecha Fin" el **día de reintegro**, `T01` marca GRAVE un documento
legítimo. Medido (`03_…py`, `LI`): `inicio 20/08`, `fin 23/08`, `dias 3` →
`T01_DURACION_VS_RANGO` GRAVE, desfase +1.

- El corpus **no** trae ningún emisor así: los 4 legítimos con las tres patas impresas dan
  desfase 0 (`R07 14/14`, `R09 126/126`, `R11 2/2`, `R13 30/30`).
- **No** se recomienda subir `desfase_tolerado_dias` a 1: medido en `04_…py` §D, eso silencia
  también `F04`, el único acierto propio de la aritmética en el corpus. La recomendación es la
  que ya dejó escrita `senales/aritmetica_fechas/INFORME.md` §4: **convención por emisor
  (NIT/EPS)**, y revalidar en cuanto entre una EPS nueva.

## H8 · MEDIA — `T08_DURACION_SIN_RESPALDO` marca una incapacidad larga legítima

Entrada (`03_…py`, `LN`): documento que imprime solo `Fecha Inicio 01/02/2026` y
`Dias de Incapacidad: 210` (prórroga larga de enfermedad general, sin fecha fin en el papel).
Esperado: sin hallazgos que exijan revisión. Obtenido: `T08` **MEDIA** →
`veredicto REVISAR`. El umbral 180 es de dominio y está declarado como no calibrado; queda
como pregunta de calibración, no como defecto. Palanca sin desplegar (medida):
`dias_sin_respaldo_aviso = 365` lo silencia, o `T08 → LEVE`.

## H9 · LEVE — `T11` (GRAVE) solo es alcanzable sin la foto, y su mensaje no es accionable

Medido (`04_…py` §C): con foto el hallazgo es `T01` (que cita los valores); sin foto y con
`fecha_fin_recalculada=True` es `T11_FIN_REESCRITO_SIN_EVIDENCIA` **GRAVE** con un mensaje que
el auxiliar no puede resolver (*"el valor original no quedó registrado"*). No es alcanzable
desde la UI (reenvía `lastResult` completo, `static/index.html:428`, con la foto dentro) ni
desde el lote (`batch.py:235` usa `IncapacidadProcessor`), pero sí desde `/api/mapear`,
`/api/registrar` y `/api/revisar` con cualquier registro anterior a la foto. Sin foto **y sin
marcas** no hay hallazgo (correcto). Corrección: conservar la foto en la fila (columna JSON) o
reformular T11 como condición del SISTEMA, no del documento.

## H10 · LEVE — un override en blanco produce un mensaje sin valor que citar

`webapp._limpiar_overrides` (`webapp.py:110`) descarta `v == ""` pero no `"   "`. Entrada
`{"fecha_fin": "   "}` → `T07_FECHA_FIN_ILEGIBLE` MEDIA: *"La fecha fin leída no es una fecha
válida (=   )"*. La UI hace `.trim()` (`index.html:493-504`), así que solo llega por API.
Corrección: `v.strip()` antes de la prueba de vacío.

---

## Lo que SÍ resistió (para no repetir el trabajo)

Casos legítimos atípicos que el motor trata correctamente (`03_casos_legitimos_atipicos.py`):

| Caso | Resultado |
|---|---|
| Incapacidad de **1 día** (`inicio == fin`, `dias=1`) | `COHERENTE`, sin off-by-one |
| **Prórroga contigua** (empieza el día siguiente al fin de la anterior, `Prorroga: SI`) | `COHERENTE`; T15/T16 apagadas, no opinan |
| Incapacidad que **cruza el fin de año** (28/12/2026 → 03/01/2027, 7 días) | `COHERENTE` |
| **Maternidad 126 días**, formato numérico y formato SURA en palabras | `COHERENTE`; 126 queda por debajo del umbral de T08 a propósito |
| **Un solo campo leído** (solo inicio / solo días / solo fin) | `COHERENTE` con `cobertura` 0.15-0.31 y todo lo demás `NO_EVALUABLE`: un dato ausente no es una violación |
| **Retroactiva** (expedida 2 días después del inicio) | `T14` **LEVE**: avisa y no bloquea (correcto) |
| Vacaciones **multi-periodo** | sin hallazgos (T01 tautológico); la fila registra 68 días de span por 10 reales — limitación ya declarada, no un falso positivo |
| Formato con el **valor antes del rótulo** (`R04`) | sin hallazgos… pero la fila entra con el fin como inicio (`2026-07-12` en vez de `2026-07-11`): silencio + dato erróneo, el reverso de H2 |
| **13 registros degenerados** (días como lista/dict/bool/float/dígito unicode/cadena de 5000 chars, fechas ISO de semana, `20260820`, fecha con hora, foto que no es dict) | el motor los explica sin caerse y el valor inutilizable no viaja a la columna |
| **4 configuraciones rotas** (`reglas` no-dict, umbral string, código inexistente, `dias_min > dias_max`) | ignoradas entrada por entrada con aviso; ninguna regla se apaga en silencio |

Y el dato de contexto: el motor dispara sobre **1 de las 15 falsas** (`F09`). Cualquier
propuesta de aflojar un umbral hay que pesarla contra eso.

## Orden de arreglo sugerido

1. **H3** (caída) — es un `try/except`.
2. **H4** (T09 sobre vacaciones/prelicencia) — falso positivo seguro y frecuente; hay
   paliativo por configuración hoy mismo.
3. **H1** + **H5** (procedencia del dato: derivado tratado como impreso, y valor inutilizable
   descartado en silencio) — las dos son la misma idea: *el motor tiene que saber de dónde
   salió cada número*. Sin eso, `cobertura` y `COHERENTE` prometen más de lo que hay.
4. **H2a/H2b/H2c** (lectura) — no son del motor, pero son las que producen los GRAVE
   indebidos y, en dos casos, la fila errónea. Mientras no haya procedencia por campo, bajar
   T02/T04 a MEDIA por configuración es un paliativo razonable; T01 **no** (es la regla que
   pidió el cliente y la única con respaldo del corpus).
5. **H6** (segunda implementación del mismo cruce) — hoy es código muerto; borrarla evita el
   mensaje duplicado y la contradicción de tolerancias.
6. **H7/H8** — preguntas de calibración al cliente, no defectos.
7. **H9/H10** — cosméticos.

## Reproducir

```bash
cd <dataset-falsedad>/validacion/falsos-positivos
PY=<repo>/.venv/Scripts/python.exe
PYTHONIOENCODING=utf-8 $PY 01_barrido_reales.py            # 16 legitimos, 2 fechas de proceso
PYTHONIOENCODING=utf-8 $PY 02_procedencia_dias.py          # evidencia vs. derivado
PYTHONIOENCODING=utf-8 $PY 03_casos_legitimos_atipicos.py  # 16 legitimos atipicos
PYTHONIOENCODING=utf-8 $PY 04_caminos_no_ocr.py            # alcance, overrides, sin foto, config
PYTHONIOENCODING=utf-8 $PY 05_lectura_y_solapes.py         # rotulo<->valor + authenticity
PYTHONIOENCODING=utf-8 $PY 06_duracion_y_autenticidad.py   # 'Duracion' y el dia del mes
PYTHONIOENCODING=utf-8 $PY 07_robustez.py                  # degenerados + config rota
PYTHONIOENCODING=utf-8 $PY 08_anio_por_posicion.py         # el anio del pie legal
```

Cada script deja su `resultados_*.json` al lado. No ejecutan OCR ni tocan la BD; los textos
sintéticos llevan datos inventados (sin PII). Baseline verificado antes de reportar:
`tests/test_validacion_temporal.py` y `tests/test_processor.py` → `RESULTADO: TODO OK`.
