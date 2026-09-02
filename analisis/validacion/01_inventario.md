# 01 · Inventario de la lógica temporal que YA existe

Antes de escribir un motor de validación de tiempos hay que saber **qué se valida hoy y dónde**.
Este documento es ese censo. La conclusión de una línea:

> El pipeline **RECONCILIA** (si falta un dato lo calcula) pero casi no **DETECTA CONTRADICCIONES**:
> cuando los tres datos (inicio, fin, días) vienen impresos y no cuadran, el sistema **pisa el que
> le sobra y sigue**, sin dejar rastro y sin marcar el registro para revisión.

Alcance: solo lógica **temporal** (fechas y duraciones). No se toca extracción de cédula, CIE-10, EPS
ni documentación.

Regla de PII (Ley 1581): aquí se citan **nombres de archivo y rutas de código**, nunca datos de pacientes.

---

## 1. Censo de invariantes temporales

Leyenda de la columna **¿valida?**:

- **NO (rellena)** — la regla existe para *completar un hueco*: si falta un dato lo deriva. Nunca
  compara dos datos presentes entre sí, así que nunca puede contradecirse.
- **SÍ** — detecta una condición mala y la **reporta** por el canal del repo (`problemas` /
  `campos_faltantes`).
- **SILENCIOSA** — detecta una condición mala y la **descarta**, sin reportarla. Desde fuera es
  indistinguible de "el dato no venía en el documento".

| # | Invariante | Vive en | ¿valida? | Hueco |
|---|---|---|---|---|
| 1 | La fecha de inicio preferente es la rotulada "Fecha Inicia/Inicial"; el ancla de layout `Dias Fecha Inicia` marca `_inicio_anclada` | `extract.py:788-791`, `extract.py:834-851`; `CLAUDE.md:111` | NO (elige) | Elegir la mejor fuente no es comprobar que las demás coincidan |
| 2 | Si no hay inicio: `inicio = fin − (días − 1)` (inclusivo) y se marca `fecha_inicio_calculada` | `extract.py:1149-1153` | NO (rellena) | La marca es un **aviso** que llega a la UI; correcta y suficiente para su caso |
| 3 | Si hay inicio + días fiables, se **(re)deriva el fin** cuando falta *o es inconsistente* | `extract.py:1144-1148` | NO (rellena) | **HUECO CENTRAL**: `if not df or df < di or (df-di).days+1 != n` sobreescribe un fin **impreso** que contradice, y no existe ninguna marca equivalente a `fecha_inicio_calculada` para el fin |
| 4 | Si hay inicio + fin y faltan días: `días = (fin − inicio) + 1` | `extract.py:1154-1157`; `erp.py:392-397` | NO (rellena) | Si los días **sí venían impresos** pero fuera de 1..540, `n` se anula (`extract.py:1140-1141`) y esta rama los **reemplaza** por el span: el valor impreso desaparece sin aviso |
| 5 | `días` válido = 1..540 | `extract.py:1140-1141` (anula `n`), `extract.py:260` (`_days_between`), `extract.py:714` (tabla detalle), `erp.py:497-499` (reporta) | **SÍ (parcial)** | `erp` reporta "Número de días fuera de rango" solo del valor **efectivo**; el valor **impreso** puede haber sido sustituido antes (ver #4) |
| 6 | Saneo final: si `0 ≤ (fin − inicio) ≤ 540` no se cumple, se borra una de las dos fechas (gana la anclada) | `extract.py:1159-1166` | NO (descarta) | Borra la evidencia. El mensaje que acaba viendo el auxiliar es "No se detectó la fecha de inicio" (`erp.py:491-493`), que es **falso**: sí se detectó, y contradice al fin |
| 7 | `fechavencimiento = fechainicio + Numerodias` (no inclusivo) | `erp.py:501-504`; `CLAUDE.md:114` | NO (calcula) | La fila de staging **no tiene columna `fecha_fin`** (`sql/init.sql:88-123`): el fin impreso no se persiste ni entra en `observaciones` (`erp.py:286-300`). El "Fin" de la bandeja (`static/index.html:674`, `db.py:106`) es `fechavencimiento`, es decir el fin **derivado**. Ni el motor ni la persona pueden comparar contra el papel |
| 8 | Una fecha tiene que ser de calendario real (rechaza 31/02, día 54) | `extract.py:81-119` (`_fecha_valida`/`_norm_date`), `erp.py:377-380` (guarda antes del INSERT) | SILENCIOSA | Un `31/02/2026` impreso se convierte en `None` y se reporta como "no se detectó": se confunde **documento imposible** con **documento ilegible** |
| 9 | La reconciliación se reaplica al corregir a mano (override de días/fin) | `erp.py:385-397` | NO (rellena) | Copia parcial de `normalizar_fechas` (solo 2 de las 4 ramas). No valida la tripleta **corregida**; y la UI no expone `fecha_fin` (`static/index.html:480-492`) aunque la API lo acepta (`webapp.py:83`) |
| 10 | Vacaciones: los días **nunca** se leen por etiqueta, siempre por diferencia de fechas | `extract.py:820-831`; `CLAUDE.md:139-147` | NO (calcula) | Con varios periodos consecutivos se toma la 1ª "a partir del" y la última "hasta el" (`extract.py:197-204`): el span incluye los **huecos** entre periodos |
| 11 | Tabla "DETALLE DE LA INCAPACIDAD": las 3 patas salen tabuladas del mismo bloque | `extract.py:700-722`, aplicada en `extract.py:903-920` | NO (rellena) | Es el punto de **máxima confianza** del repo (las tres patas del mismo bloque, sin heurística de proximidad) y justamente ahí no se comprueba que cuadren |
| 12 | Fechas escritas en palabras (certificados EPS tipo Sura): día+mes y año se emparejan **por posición** | `extract.py:140-164` | NO (lee) | Ensamblado sin verificar. El **día de la semana impreso** ("VIERNES 10 DE JULIO") es una suma de verificación gratuita que hoy se ignora |
| 13 | Vacaciones en prosa: 1ª fecha tras "a partir del", última tras "hasta el" | `extract.py:197-204` (`_fechas_vacaciones`, `_fecha_parentesis`) | NO (lee) | No se comprueba que fin ≥ inicio ni que el nº de "a partir del" y de "hasta el" cuadre |
| 14 | Anclaje anti-alucinación: una fecha del LLM solo se acepta si **aparece en el texto OCR** | `extract.py:1041-1048`, `extract.py:1090-1105` | **SÍ** (pero silenciosa) | Es una validación real y buena; descarta sin avisar (aceptable: es defensa interna, no un hallazgo del documento) |
| 15 | Permisos: `días = _days_between(desde, hasta)`; un solo día ⇒ desde == hasta | `extract.py:658-667` | NO (calcula) | El formato de permiso no trae días impresos, así que no hay nada que contradecir |
| 16 | `fecharegistro = hoy`; `hoy` es inyectable como parámetro | `erp.py:349`, `erp.py:543` | NO | El reloj **ya está disponible** en la firma de `mapear_a_staging` y **nadie compara** las fechas del documento contra él: no hay detección de fechas futuras ni de documentos vencidos |
| 17 | Prórrogas | No existe. Solo aparece como pendiente en `CONTEXT.md:207` | NO | Sin concepto de prórroga no hay continuidad de cadena ni acumulado |
| 18 | `fecha_inicio_calculada` viaja hasta la UI como aviso **no bloqueante** | `erp.py:372`, `erp.py:584`, `static/index.html:552` | n/a | Es el **patrón a imitar** para todo aviso que no deba frenar la aprobación (ver §4) |

### Ya existe una sonda con provenance (no está en producción)

`<dataset-falsedad>/senales/aritmetica_fechas/probe.py` ya resuelve la parte
difícil: **releer la tripleta IMPRESA del texto plano, con la procedencia de cada pata**
(`leer_impresos()`), precisamente porque `normalizar_fechas()` borra la evidencia. Incluye guardas
anti-falso-positivo medidas contra el corpus (`_dias_impresos()`: nunca acepta un número suelto,
nunca lee dígitos hacia atrás del rótulo, marca `conflicto_dias` si dos fuentes discrepan) y el
checksum del día de la semana. Su medición (31 documentos, 5 en cuarentena excluidos):

| | falsas | reales |
|---|---|---|
| documentos evaluables | 12 | 14 |
| tripleta impresa **completa** (las 3 patas en el papel) | 6 | 4 |
| marcados por algún check | 1 | 1 |

Lectura honesta de esos números: la aritmética de fechas **no es un detector de fraude** (solo 1 de
12 falsas se cae por aquí), pero **sí es un detector de datos que entrarían mal al ERP**, que es
exactamente lo que pidió el cliente. Y el caso `F09` es la prueba: tripleta impresa
`inicio=2026-06-05 / fin=2026-07-06 / días=2`, y lo que el pipeline dejó en el JSON fue
`fecha_inicio=2026-06-05, fecha_fin=2026-06-06, dias=2, fecha_inicio_calculada=False`. El fin
impreso (32 días de span) fue reescrito a 1 día de distancia y **el registro no lleva ninguna marca**.

Nota metodológica: `F03` y `R15` son un par en **cuarentena** (mismo sha256, etiquetas opuestas) y
son el único "falso positivo" contra reales del check AF01 — no cuenta como error del check, cuenta
como contradicción del etiquetado (ver `dataset-falsedad/LEEME.md`).

### Segunda medición independiente (corrobora)

`<dataset-falsedad>/validacion/_medir_tiempos.py` (de otro trabajo en curso)
relee el corpus con **otro** lector de procedencia y llega al mismo sitio
(`medicion_tiempos.json`, 26 documentos limpios):

| | falsas (12) | reales (14) |
|---|---|---|
| las TRES patas impresas | 6 | 3 |
| tripleta impresa **incoherente** | **1** (desfase −30 días) | **0** |
| orden invertido · días fuera de rango · expedición posterior al inicio | 0 · 0 · 0 | 0 · 0 · 0 |
| `fecha_expedicion` leída | 0 | 2 |
| antigüedad del documento (días entre inicio y hoy) | 50 … 352 | 46 … 101 |

Tres consecuencias directas para el diseño:

1. **T01 no produjo ningún falso positivo** sobre reales en dos lecturas independientes. Es la regla
   con mejor relación valor/riesgo del conjunto.
2. **`fecha_expedicion` casi no se extrae hoy** (2 de 26 documentos): las reglas que dependen de ella
   (T06/T07) son correctas pero tendrán cobertura casi nula hasta que se mejore su extracción. No
   hay que venderlas como cobertura real.
3. **El umbral de antigüedad no se puede adivinar:** en este corpus los documentos tienen entre 46 y
   352 días, y las dos clases se solapan. Un umbral tipo "30 días" marcaría el 100% del corpus. Por
   eso T09 queda `evaluable_hoy=false` hasta que el cliente fije el plazo (y hasta saber cuánto de
   esa antigüedad es del proceso de recolección del corpus y cuánto del flujo real).

---

## 2. Los huecos, demostrados ejecutando el pipeline

Script: `<dataset-falsedad>/validacion/00_demo_huecos.py`
(texto **sintético**, sin PII; camino real `RuleBasedExtractor` → `normalizar_fechas()` →
`erp.mapear_a_staging()`; catálogos resueltos con un `FakeLookups` para que `problemas` no se llene
de ruido de BD y se vea que **ningún** problema habla de los tiempos).

```
<repo>/.venv/Scripts/python.exe 00_demo_huecos.py
```

### Caso A — tripleta impresa contradictoria (el hueco central)

El papel dice inicio `05/06/2026`, fin `06/07/2026` y `2` días. Son 32 días de span, no 2.

```
extractor LEE          : inicio=2026-06-05 fin=2026-07-06 dias=2
normalizar_fechas DEJA : inicio=2026-06-05 fin=2026-06-06 dias=2 calculada=False
fila staging           : fechainicio=2026-06-05 Numerodias=2 fechavencimiento=2026-06-07
problemas              : [] (ninguno)
requiere_revision      : False   confianza_ocr: 1.0
```

El fin impreso se reescribió, `problemas` está vacío, `confianza_ocr` es **1.0** y la UI muestra la
píldora verde **"✓ Listo para aprobar"** (`static/index.html:533-537`). El auxiliar no tiene forma de
enterarse: el fin impreso no aparece ni en la fila, ni en `observaciones`, ni en el JSON descargable
(el panel de la UI muestra el `fecha_fin` **ya reescrito**, `static/index.html:312`).

### Caso B — días impresos fuera de rango, con las dos fechas presentes

El papel dice `900` días e inicio/fin que dan 5.

```
extractor LEE          : inicio=2026-06-01 fin=2026-06-05 dias=900
normalizar_fechas DEJA : inicio=2026-06-01 fin=2026-06-05 dias=5
fila staging           : fechainicio=2026-06-01 Numerodias=5 fechavencimiento=2026-06-06
problemas              : [] (ninguno)
```

`erp.py:497-499` **sí** sabe reportar "Número de días fuera de rango", pero nunca lo ve: `n` se
anuló en `extract.py:1140-1141` y la rama `elif di and df and not n` lo sustituyó por 5. La regla de
rango existe y aun así este documento pasa limpio.

### Caso C — rango invertido (fin antes del inicio)

```
extractor LEE          : inicio=2026-06-20 fin=2026-06-10 dias=None
normalizar_fechas DEJA : inicio=None     fin=2026-06-10 dias=None
problemas              : ['No se detectó la fecha de inicio', 'No se detectó el número de días']
```

Aquí sí se marca para revisión, pero **por el motivo equivocado**: el saneo final
(`extract.py:1159-1166`) borró la fecha de inicio *que sí estaba impresa* y el mensaje dice que no se
detectó. El auxiliar irá a buscar un dato ilegible en lugar de resolver una contradicción.

### Casos D y E — dimensiones que hoy no se miran en absoluto

```
D  expedición 2026-07-20, incapacidad 05→06/06/2026  → problemas: []   (certificado emitido 6 semanas
                                                                        después de terminar)
E  inicio 2027-01-05 con hoy = 2026-09-02            → problemas: []   (inicio 4 meses en el futuro)
```

`fecha_expedicion` se extrae (`extract.py:783`) y solo se usa como texto en `observaciones`
(`erp.py:298-299`); jamás se compara con inicio/fin. Y `hoy` ya es parámetro de `mapear_a_staging`
(`erp.py:349`) pero solo alimenta `fecharegistro`.

### Resumen de los huecos

1. **Contradicción de la tripleta impresa** → se pisa el fin en silencio (A).
2. **Días impresos inválidos** → se sustituyen por el span en silencio (B).
3. **Rango invertido** → se borra una fecha y el motivo reportado miente (C).
4. **Fecha impresa fuera de calendario** → se convierte en `None`, indistinguible de ilegible (#8).
5. **Fecha de expedición** → extraída y nunca confrontada (D).
6. **Nada se compara con `hoy`** → ni futuro ni antigüedad (E).
7. **El fin impreso no se persiste** → ni el motor ni la persona pueden auditar a posteriori (#7).
8. **La tripleta corregida a mano no se valida** y la UI no deja editar el fin (#9).

---

## 3. Lo que el motor nuevo NO debe reimplementar

Duplicar `normalizar_fechas()` sería el peor resultado posible: quedarían **dos** reconciliaciones que
se contradicen en cuanto alguien toque una. La división de trabajo que sostiene esto:

- `extract.normalizar_fechas()` **decide qué dato queda** (rellena, deriva, sanea). Sigue siendo el
  único dueño de eso.
- el motor nuevo **opina sobre lo que había en el papel** (lee, compara, califica y explica). No
  escribe `fecha_inicio`/`fecha_fin`/`dias`.

Con eso, la lista concreta de lo que ya existe y funciona:

| No reimplementar | Está en | Para qué sirve al motor |
|---|---|---|
| `extract.normalizar_fechas()` | `extract.py:1121-1167` | Es la reconciliación. Se **consume** su salida; no se copia ni se sustituye |
| `extract._norm_date()` + `extract._fecha_valida()` | `extract.py:81-119` | Parseo de los 3 formatos + validez de calendario. No escribir otro parser de fechas |
| `extract._DATE`, `extract._DMA_TRIPLET` | `extract.py:123`, `extract.py:458` | Patrones de fecha ya ajustados a documentos reales |
| `extract._days_between()` | `extract.py:249-260` | Span **inclusivo** con el filtro 1..540 |
| `extract._find_date()` | `extract.py:223-246` | Fecha cerca de un rótulo, incluida la guarda de "no le robes el valor al campo vecino" |
| `extract._extraer_detalle_incapacidad()` | `extract.py:700-722` | La tripleta tabulada (Clínica del Cesar) — la lectura más fiable que hay |
| `extract._fecha_inicio_fin_escrita()`, `_fechas_vacaciones()`, `_fecha_parentesis()` | `extract.py:140-204` | Fechas escritas en palabras (Sura, cartas de vacaciones) |
| `extract._dates_in_text()` / `grounded()` | `extract.py:1041-1048`, `1090-1105` | Anclaje anti-alucinación: una fecha que no está en el OCR no existe |
| `erp.mapear_a_staging()` cálculo de `fechavencimiento` | `erp.py:501-504` | La fórmula no inclusiva del ERP ya está aquí |
| `erp.mapear_a_staging()` reporte de días fuera de rango | `erp.py:494-499` | Ya cubre el valor **efectivo**; la regla nueva debe hablar del valor **impreso**, con otro texto, para no duplicar el mensaje |
| `erp.validar_documentacion()` + `REQUISITOS_DEFAULT`/`lprequisitos_eps` | `erp.py:93-131`, `erp.py:246-258` | El **patrón** de "tabla de BD que manda sobre el default de código, degradando si no existe". Es exactamente el mecanismo de *actualizable sin desplegar* que pide el cliente |
| `erp.LookupsNulos` | `erp.py:261-280` | El patrón de degradación sin BD. Las reglas que necesiten BD se declaran *no evaluables*, no explotan |
| `db.insertar_alerta()` + `lp_alertas_documentacion` | `db.py:84-98`, `sql/init.sql:125-137` | Canal de alerta ya existente. No abrir un segundo canal |
| `senales/aritmetica_fechas/probe.py` (`leer_impresos`, `_dias_impresos`, `_fechas_escritas`) | `dataset-falsedad/senales/aritmetica_fechas/probe.py` | El lector de la **tripleta impresa con procedencia**, ya medido contra el corpus. Hay que **promoverlo** al paquete, no reescribirlo |
| `erp._norm()` | `erp.py:134-137` | Normalización de texto (minúsculas, sin tildes). No escribir otra |

---

## 4. El patrón de reporte del repo (encajar aquí, no traer uno nuevo)

El motor nuevo **no** define su propio formato de salida. El repo ya tiene un patrón completo, de
`erp.py` hasta el HTML, y hay que seguirlo tal cual.

### 4.1 Estructura de datos

`erp.mapear_a_staging()` devuelve (`erp.py:571-585`) un dict con tres canales distintos:

1. **`problemas: list[str]`** — frases en español, orientadas a acción, en primera lectura para el
   auxiliar ("No se detectó la fecha de inicio", "Cédula 1234 no encontrada en empleados"). Se
   construyen con `problemas.append(...)` a lo largo de la función.
2. **`campos_faltantes: list[dict]`** — `{"campo", "etiqueta", "valor"}` vía el helper local
   `_faltan()` (`erp.py:402-403`). `campo` es la clave de **override** (`cedula`, `cie10`, `eps`,
   `fecha_inicio`, `dias`, `tipo`), lo que permite a la UI resaltar el input exacto.
3. **avisos sueltos no bloqueantes** — claves booleanas en el dict: `fecha_inicio_calculada`,
   `eps_de_empleado`. **No** entran en `problemas`.

Y la fila persiste: `row["problemas"] = "; ".join(problemas) or None` (`erp.py:566`, columna `TEXT` en
`sql/init.sql:115`), `documentacion_estado`, `documentos_faltantes`.

### 4.2 La regla que decide todo el diseño

```python
"requiere_revision": len(problemas) > 0      # erp.py:573
```

y en la API:

```python
if flujo == ESTADO_APROBADO and mapeo["requiere_revision"]:   # webapp.py:285, webapp.py:350
    raise HTTPException(status_code=409, ...)
```

**Consecuencia para el implementador:** todo lo que se meta en `problemas` **bloquea la aprobación**
(HTTP 409). Por tanto:

- severidad **bloqueante** ⇒ se añade una frase a `problemas` (y, si aplica, un `_faltan(...)`).
- severidad **aviso** ⇒ **no** se toca `problemas`; se expone como clave aparte del dict (el patrón
  `fecha_inicio_calculada`) y/o en una lista nueva propia (p.ej. `avisos_tiempo`), que la UI pinta
  pero que no cambia `requiere_revision`.

Si esto se ignora, cualquier aviso menor convierte 7000 documentos/mes en 7000 bloqueos, y el
cliente pidió lo contrario: "**déjalo de tal forma que sea escalable**".

### 4.3 Recorrido completo (donde hay que enchufar cada cosa)

```
erp.mapear_a_staging() -> {problemas, campos_faltantes, requiere_revision, fecha_inicio_calculada, ...}
        │
        ├─ row["problemas"]  ──────────────► lp_ausentismos_ia.problemas (TEXT)  · sql/init.sql:115
        │                                    db.listar_staging (db.py:101-118)
        │                                    bandeja, columna "Pendiente"       · index.html:674,676
        │
        ├─ webapp /api/mapear  (webapp.py:235-249) devuelve el mapeo COMPLETO tal cual
        ├─ webapp /api/registrar (webapp.py:301-309) y /api/revisar (webapp.py:361-366)
        │        devuelven requiere_revision + problemas [+ campos_faltantes]
        │        y BLOQUEAN la aprobación con 409 si requiere_revision
        │
        └─ UI (static/index.html)
             ├─ píldora #pillRevision  "⚠ Requiere revisión" / "✓ Listo para aprobar"   (533-537)
             ├─ caja #erpProblemas     "⚠️ Pendiente: " + problemas.join(" · ")          (264, 578-582)
             ├─ markMissing()          campos_faltantes[].campo → input en rojo         (513-517)
             └─ aviso inline           fecha_inicio_calculada → "(calculada: fin − días)" (552)
```

Y en el lote (`batch.py:226-241`): se **extiende** la lista (`problemas = list(mapeo["problemas"])`,
se le añaden los hallazgos propios del lote, y solo si cambió se reescribe `row["problemas"]`). De ahí
sale el enrutado: `2_revisar/datos_por_revisar/` cuando hay `problemas` y la documentación está
completa (`batch.py:239-254`). El motor nuevo hereda ese enrutado **gratis** si respeta el canal.

### 4.4 Estilo de las reglas (escalabilidad y actualización)

- **Declaración, no código nuevo por regla.** El precedente exacto es `erp.REQUISITOS_DEFAULT` +
  `EQUIVALENCIAS_DOC` + `validar_documentacion()`: los requisitos son **datos**, el evaluador es una
  función de 10 líneas. Añadir un requisito es añadir una entrada al dict. El motor de tiempos debe
  ser igual: una tabla/lista de reglas declaradas y **un** evaluador.
- **Umbrales y severidades actualizables sin desplegar.** El precedente es
  `lprequisitos_eps` prevaleciendo sobre `REQUISITOS_DEFAULT`, con la consulta envuelta en
  `try/except` que degrada a "sin filas" si la tabla no existe (`erp.py:249-258`). Misma receta: los
  umbrales y severidades viven en una tabla de ASTGU (editable por el analista) con **default en
  código** para poder correr sin BD.
- **Ojo con el DDL:** `sql/init.sql` solo corre en el **primer** init de un volumen vacío
  (`CLAUDE.md:216-217`). Cualquier columna/tabla nueva necesita un `ALTER` para los entornos ya
  levantados; y si se añade una columna actualizable en revisión, hay que meterla en
  `db._COLS_ACTUALIZABLES` (`db.py:135-141`) o la revisión manual la perderá.
- **Mensajes en español, explicando el por qué**, como el resto del repo.

---

## 5. Reglas temporales que HOY no se validan (propuesta)

Detalle completo (severidad propuesta, cálculo, riesgo de falso positivo, evaluable o no) en la
salida estructurada de esta tarea. Resumen:

| id | afirma | sev. | evaluable hoy |
|---|---|---|---|
| T01 | la tripleta IMPRESA cuadra: `(fin − inicio) + 1 == días` | BLOQUEANTE | sí |
| T02 | el rango impreso no está invertido (`fin ≥ inicio`) | BLOQUEANTE | sí |
| T03 | los días IMPRESOS están en 1..540 | AVISO | sí |
| T04 | una fecha impresa es de calendario real (y si no, se dice) | AVISO | sí |
| T05 | si se reescribió el fin impreso, queda marcado (`fecha_fin_recalculada`) | AVISO | sí |
| T06 | el certificado no se expidió después de terminar la incapacidad | AVISO | sí (umbral a confirmar) |
| T07 | el certificado no se expidió mucho antes de empezar | AVISO | sí (umbral a confirmar) |
| T08 | la incapacidad no empieza en el futuro (salvo tipos 5/10/13) | AVISO | sí |
| T09 | el documento no llega fuera del plazo de radicación | AVISO | **no** (plazo normativo) |
| T10 | no es un duplicado exacto ya radicado | AVISO | sí (requiere BD, degrada) |
| T11 | el intervalo no se solapa con otro ausentismo del mismo empleado | AVISO | sí (requiere BD, degrada) |
| T12 | el día de la semana impreso cuadra con la fecha | AVISO | sí |
| T13 | vacaciones multi-periodo: los días no incluyen los huecos | AVISO | sí |
| T14 | la tripleta CORREGIDA A MANO cuadra | BLOQUEANTE | sí |
| T15 | la cadena de prórrogas es contigua y no excede el acumulado | — | **no** (normativa) |

---

## 6. Archivos de esta carpeta

| Archivo | Qué es |
|---|---|
| `01_inventario.md` | este documento |
| `00_demo_huecos.py` | demostración ejecutable de los huecos (§2). Texto sintético, sin PII, sin BD, sin red |
| `_medir_tiempos.py` · `medicion_tiempos.json` | medición del corpus de **otro trabajo** en curso (§1). No editar desde aquí |

Nada de lo escrito aquí toca `incapacidad_ocr/extract.py` ni `tests/test_processor.py` (frontera de
archivos: otro trabajo los está editando; los cambios que harían falta en `normalizar_fechas()` están
descritos como **propuesta** en T05, no aplicados).
