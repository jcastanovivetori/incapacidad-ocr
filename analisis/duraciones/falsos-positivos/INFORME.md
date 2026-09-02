# Verificación — frente "Caza de duraciones inventadas" (`falsos-positivos`)

**Rol:** verificador (no se tocó una línea del paquete ni de `tests/`).
**Cambio verificado:** lector de duraciones en números y letras (`numeros_es.py` como lector primario,
cableado en `extract.RuleBasedExtractor`, `_dias_de_celda`, `_merge_records`).
**Fecha:** 2026-09-02.

## Cómo reproducir

```bash
cd dataset-falsedad/duraciones/falsos-positivos
../../../incapacidad-ocr/.venv/Scripts/python.exe 00_baseline_corpus.py            # los 31 .txt cacheados
../../../incapacidad-ocr/.venv/Scripts/python.exe 01_ataque_falsos_positivos.py    # 86 casos de ataque
```

`salida.txt` es la corrida guardada. `probe.py` es la sonda de un solo texto.
**No se ejecutó OCR** (había otra medición de rendimiento en la máquina): todo sale de
`dataset-falsedad/ocr/**/*.txt`. **Ollama/Docker no están levantados**, así que el camino del LLM se
atacó con un extractor falso inyectado (`StubLLM`, mismo patrón que `StubOCR`) — cubre la política de
fusión, no el prompt ni el modelo.

Sin PII: los fragmentos son sintéticos o recortes de **estructura** de documentos reales; los
documentos se citan por nombre de archivo.

## Veredicto: **NO limpio.**

El frente NO está limpio. **8 hallazgos**, de los cuales **4 son GRAVES** y **3 de ellos son
regresiones**: entradas donde los patrones históricos devolvían `None` (o el valor correcto) y el
lector nuevo devuelve una duración inventada.

Lo bueno primero, porque es real y es la mayor parte del trabajo: **los 16 falsos positivos que
`01_evidencia.md` documenta contra documentos reales están cerrados** y los **31 textos cacheados no
producen ni una duración inventada** (`00_baseline_corpus.py`; incluidos los dos que fallaban antes:
el día del mes de `POR 4 DIAS DESDE EL 29-07-26` → 4, y el año de `Duracion`⏎`DE2026` → `None`).
Edad, horas, semanas de gestación, vigencia de dosis, cantidades de insumo, `hacetresdias`, artículos
indefinidos, números de trámite, registros médicos, signos vitales, régimen/nivel/página y los dos
permisos reales: **todos rechazados**, también en su versión en letras (lista completa al final).

El problema es de **cobertura del ancla**, no de los casos ya estudiados.

---

## La causa raíz común (H1 + H2)

`numeros_es` justifica un candidato con dos anclas —la **unidad pegada al valor** y el **rótulo de
duración**— y descarta con una **lista negra** de contextos (`_CONTEXTOS_PROHIBIDOS`,
`numeros_es.py:211`). Esa lista **solo se consulta a la IZQUIERDA**: en
`_candidatos_por_unidad` sobre el contexto previo al valor (`numeros_es.py:382`) y en
`_candidatos_por_etiqueta` sobre el texto previo al rótulo (`numeros_es.py:399`). **Nada mira a la
DERECHA del valor.** Consecuencia:

* cualquier `<N> DIAS` / `<PALABRA> DIAS` del documento cumple el ancla de unidad, y
* cualquier valor tras la palabra `duracion` cumple el ancla de rótulo, **aunque la unidad escrita a
  la derecha diga `HORAS`, `SEMANAS` o `MINUTOS`**.

La documentación del módulo dice que la unidad pegada al valor es lo que justifica la lectura
(`numeros_es.py:20-28`), y CLAUDE.md repite que "todo candidato exige un ANCLA". Pero en un documento
médico **la palabra "días" aparece muchas veces y casi ninguna es la duración de la incapacidad**:
recomendaciones ("control en 3 días"), plazos de trámite, validez del certificado, evolución del
cuadro clínico, y la fórmula de cierre notarial. El ancla de unidad no separa esos usos; la lista
negra tapa los 4 que estaban en el corpus (`edad`, `hace`, `vig`, `horas`/`cada`, `mes(es)`,
`semanas`) y deja pasar todo lo demás.

---

## Hallazgos

### H1 — GRAVE (regresión). Cualquier "N DÍAS" del documento se convierte en la duración

**Archivo:línea de la causa:** `incapacidad_ocr/numeros_es.py:377-390` (`_candidatos_por_unidad`; el
veto de `numeros_es.py:382` solo mira a la izquierda) + `_CONTEXTOS_PROHIBIDOS` (`numeros_es.py:211`)
como lista negra.

| Entrada (fragmento exacto) | Esperado | Obtenido | Pre-cambio |
|---|---|---|---|
| `La incapacidad debe radicarse dentro de los 3 dias habiles siguientes` | `None` | **3** (evidencia `'3 dias'`) | `None` |
| `Debe radicarse dentro de los tres dias habiles siguientes` | `None` | **3** (`'tres dias'`) | `None` |
| `Este certificado es valido por 30 dias` | `None` | **30** (`'30 dias'`) | `None` |
| `RECOMENDACIONES: CONTROL EN 3 DIAS POR CONSULTA EXTERNA` | `None` | **3** | `None` |
| `RECOMENDACIONES: CONTROL EN TRES DIAS` | `None` | **3** | `None` |
| `CUADRO CLINICO DE 3 DIAS DE EVOLUCION` | `None` | **3** | `None` |
| `CUADRO CLINICO DE TRES DIAS DE EVOLUCION` | `None` | **3** | `None` |
| `SE RECOMIENDA REPOSO POR 2 DIAS` | `None` | **2** | `None` |
| `Dada en Malambo a los 15 dias del mes de agosto de 2026` | `None` | **15** | `None` |
| `Dada en Malambo a los quince (15) dias del mes de agosto de 2026` | `None` | **15** | `None` |
| `Dada en Malambo a los quince dias del mes de agosto` | `None` | **15** | `None` |

Nótese la última terna: es la **fórmula de cierre** de cualquier certificación colombiana
("Dada en … a los N días del mes de …"). Ahí la palabra "días" **acompaña al día del mes**, que es
exactamente el falso positivo nº5 del corpus pero con el orden invertido, y el veto `mes` de
`numeros_es.py:215` no dispara porque "del mes" está **a la derecha**.

**Lo peor: el dato inventado GANA al rótulo verdadero.** `duracion_en_texto` ordena candidatos por
`(mixto?, nº de renglón, columna)` (`numeros_es.py:455`), así que si el falso positivo aparece antes
en el orden de lectura del OCR, se queda con el campo:

```
Dada en Malambo a los 15 dias del mes de agosto de 2026
Dias de Incapacidad: 2
Fecha Inicial: 10/06/2026
Fecha Final: 11/06/2026
```
→ esperado `dias=2`; obtenido **`dias=15`**, y `normalizar_fechas` re-deriva
`fecha_fin = 2026-06-24`. **Pre-cambio devolvía 2** (el patrón histórico exigía el dígito *después*
del rótulo). El mismo texto con el boilerplate al final sí da 2 → el resultado depende del orden que
le dé el OCR.

**Impacto en la fila de staging** (documento 10/06/2026 → 11/06/2026 = 2 días):

| Texto añadido | `Numerodias` | `fechavencimiento` | ¿aviso al revisor? |
|---|---|---|---|
| — (referencia) | 2 | 2026-06-12 | — |
| `dentro de los 3 dias habiles` | **3** | 2026-06-13 | sí (`fecha_fin_recalculada`) |
| `valido por 30 dias` | **30** | 2026-07-10 | sí |
| `valido por 30 dias`, doc **sin fecha fin** | **30** | 2026-07-10 | **NO** |
| `a los 15 dias del mes`, doc **sin fecha fin** | **15** | 2026-06-25 | **NO** |

La instrumentación `fecha_fin_recalculada` **sí** delata el caso cuando el documento traía una fecha
fin — es un acierto del cambio y hay que reconocerlo. Pero **7 de los 31 textos del corpus son la
forma A10** (rótulo de días presente, valor perdido por el OCR) y varios llegan sin fecha fin legible:
ahí no hay contradicción que avisar y la duración inventada entra **muda**, con `Numerodias` dentro de
1..540 (no la marca la validación de rango de `erp.mapear_a_staging`) y un `fechavencimiento` coherente
consigo mismo.

**Realismo:** ninguna de estas frases está en los 31 textos cacheados (son sintéticas). Pero la clase
sí: `falsas/FALSA-10.txt` línea 25 imprime en el propio certificado la
nota de trámite `Favortramitar la incapacidad antes de 72 horas` — **la misma nota escrita en DÍAS
entra como duración**. Y `reales/REAL-10.txt` (que el pipeline procesa como incapacidad)
trae la evolución del cuadro clínico en horas (`CUADRO CLINICO DE 3 HORAS DE EVOLUCION`) y órdenes de
medicamento — en días son la forma de arriba.

### H2 — GRAVE (regresión). El rótulo `duracion` alcanza el valor de OTRA duración

**Archivo:línea de la causa:** `numeros_es.py:203` (`r"duracion"` como palabra suelta) +
`numeros_es.py:229` (`_VENTANA_ETIQUETA = 25`) + veto solo a la izquierda (`numeros_es.py:399`).

Los patrones históricos usaban una ventana de **10 caracteres sin dígitos** tras `duracion`; la nueva
son **25 caracteres del mismo renglón**, que es justo lo que hace falta para saltar el complemento
("del permiso", "del embarazo", "de la consulta") y llegar al valor de otra cosa.

| Entrada exacta | Esperado | Obtenido | Pre-cambio |
|---|---|---|---|
| `DURACION DEL PERMISO: 4 HORAS` | `None` | **4** días (`'duracion del permiso: 4'`) | `None` |
| `DURACION: CUATRO HORAS` | `None` | **4** días (`'duracion: cuatro'`) | `None` |
| `Duracion del reposo en horas: 8` | `None` | **8** días | `None` |
| `DURACION DEL EMBARAZO: 40 SEMANAS` | `None` | **40** días | `None` |
| `Duracion gestacion: 39 semanas` | `None` | **39** días | `None` |
| `DURACION DE LA CONSULTA: 20 MINUTOS` | `None` | **20** días | `None` |
| `DURACION DEL TRATAMIENTO: 7 DIAS` | `None` | **7** días | `None` |

Los dos primeros son el frente de **PERMISOS** que se me pidió atacar: en un permiso la duración se
mide en **horas**. Hoy están protegidos porque `RuleBasedExtractor` desvía el formato a
`_extraer_permiso` antes de llegar al lector (`extract.py:805`) — los **dos permisos reales del corpus
dan `None`, con el ancla de formato intacta y también destruida a propósito**. La exposición aparece
si el ancla `solicitud de permiso` falla **y** el formato escribe la duración en línea, o si el rótulo
aparece en una incapacidad (`Duracion gestacion`, `DURACION DEL TRATAMIENTO` son propios de
epicrisis/historia clínica, y `reales/REAL-07.txt` + `reales/REAL-09.txt`
son licencias de maternidad que traen semanas de gestación junto al rótulo `Duracion`).

### H3 — GRAVE. Un CIE-10 sin punto en la celda "Días Inc." se vuelve duración

**Archivo:línea de la causa:** `incapacidad_ocr/extract.py:322` —
`duracion_en_texto("Dias: " + celda)` **le regala el ancla** a lo que haya en la celda; combinado con
`numeros_es.normalizar`, que **separa letra de dígito** (`numeros_es.py:109-110`, `129-130`), y con
`_RE_NUM` (`numeros_es.py:177`), que no tiene guarda contra una letra pegada a la izquierda.

| Celda `Dias Inc.` | Esperado | Obtenido |
|---|---|---|
| `J069` | `None` | **69** |
| `A099` | `None` | **99** |
| `R074` | `None` | **74** |
| `S420` | `None` | **420** |
| `R509` | `None` | **509** |
| `K429` | `None` | **429** |
| `O039` | `None` | **39** |
| `B349` | `None` | **349** |
| `X 500 MG` | `None` | **500** |
| `1 de 1` (paginación) | `None` | **1** |
| `3` / `TRES` / `3 (TRES)` | 3 | 3 (correcto, sin regresión) |

`J069`, `A099`, `R074`, `S420`, `M544` son **la forma exacta en que el OCR emite los CIE-10** según
`01_evidencia.md §7` y el propio comentario de `extract.py:1101`. Todos los valores obtenidos caen
dentro de 1..540, así que ni el clamp de `_dias_de_celda` (`extract.py:326`) ni la validación de rango
de `erp.mapear_a_staging` los marcan. Con el bloque `DETALLE DE LA INCAPACIDAD` presente, `dias` del
bloque **sobrescribe** lo que hubieran leído las heurísticas genéricas (`extract.py:1005-1006`) y
`normalizar_fechas` re-deriva la fecha fin a partir de ese valor.

Es un **cambio de modo de falla**: antes la celda se capturaba como `(\d{1,3})` y cualquier cosa que no
fueran dígitos puros hacía que el bloque entero no casara (se **perdía** el dato — el motivo declarado
del cambio). Ahora el bloque casa y **se inventa** el dato. Para que ocurra hace falta que el OCR
desplace una columna dentro del bloque, así que la probabilidad es menor que en H1/H2, pero el efecto
(69, 349 o 509 días de incapacidad) es peor.

### H4 — GRAVE. La regla de VACACIONES se cae si el OCR conserva la tilde de "Período"

**Archivo:línea de la causa:** `incapacidad_ocr/extract.py:184` —
`_VACACIONES_ANCHOR = re.compile(r"(?i)notificaci[oó]n\s*(?:de\s*)?periodos?\s*de\s*vacaciones")`.
Tolera la tilde de **notificaci*ó*n** pero **no** la de **per*í*odo**, en el mismo patrón.

| Título de la carta | Esperado | Obtenido |
|---|---|---|
| `NOTIFICACION DE PERIODO DE VACACIONES` | tipo `vacaciones`, `dias=14` | correcto (control) |
| `Notificacion Período de Vacaciones` | tipo `vacaciones`, `dias=14` | tipo **`incapacidad`**, **`dias=7`**, sin fechas |
| `NOTIFICACION DE VACACIONES` | idem | tipo `incapacidad`, `dias=7` |
| `PERIODO DE VACACIONES` | idem | tipo `incapacidad`, `dias=7` |
| `CARTA DE VACACIONES` | idem | tipo `incapacidad`, `dias=7` |

(cuerpo de la carta: el sintético de `tests/test_processor.py`, `a partir del dia siete (07) de julio
de dos mil veintiseis (2026) hasta el veinte (20) de julio…`)

Cuando la detección falla se cae **toda** la regla que CLAUDE.md protege: no se aplica
`_fechas_vacaciones` (no hay ni `fecha_inicio` ni `fecha_fin`), el tipo pasa de **13 VACACIONES** a
**3 ENFERMEDAD GENERAL**, y `_dias_por_etiqueta` sí corre y devuelve el **día del mes: 7**. El `7` que
CLAUDE.md pone como ejemplo de lo que nunca debe salir de esa carta es exactamente lo que sale.

La premisa es realista: **7 de los 31 textos OCR del corpus conservan tildes** (`Médico`, `Teléfono`,
`Término`, `Registro Médico`), o sea que el OCR de este proyecto sí las emite. Y una carta de RH es
prosa en minúsculas con acentos, no un formulario en mayúsculas sostenidas.

**Atenuante:** el registro sale sin fecha de inicio, así que `erp.mapear_a_staging` lo marca
`No se detectó la fecha de inicio` y va a revisión — el `7` no llega a nómina en silencio, pero se le
presenta al auxiliar como el dato leído.

**Nota:** el propio `01_evidencia.md` avisa de que **no hay ninguna carta de vacaciones real en el
corpus**; el título canónico usado en el patrón viene del sintético de `scripts/sembrar_demo.py`. Este
hallazgo dice que ese patrón es **demasiado estrecho para ser el único guardián** de la regla.

### H5 — MEDIA (preexistente). El respaldo histórico lee el día del mes de cualquier prosa

**Archivo:línea de la causa:** `incapacidad_ocr/extract.py:308` — el segundo patrón histórico
`d[ií]as?(?:\s*de\s*incapacidad)?\b[^\d\n]{0,15}<num>`: el `\b` acepta el **singular "dia"** y la
ventana de 15 caracteres cruza la preposición.

| Entrada (con rótulo de días sin valor, forma A10) | Esperado | Obtenido | Pre-cambio |
|---|---|---|---|
| `Se expide en Malambo el dia 15 de agosto de 2026` | `None` | **15** | 15 |
| `Certifico que el dia primero (01) de julio se atendio al paciente` | `None` | **1** | 1 |
| `Firmado el dia 21 de mayo de 2026` | `None` | **21** | 21 |
| (prosa de vacaciones) `dia siete (07) de julio` | `None` | **7** (match `'dia siete (07'`) | 7 |

**No es una regresión** (misma lectura antes y después) y **es inerte en los 31 textos cacheados** —
verificado uno a uno: en los 11 documentos donde el módulo devuelve `None`, los dos patrones
históricos también devuelven `None`. Lo reporto porque **es el vector concreto de H4** y porque el
propio informe de decisiones lo declara como "más laxo que el módulo" y candidato a borrarse: aquí
queda documentado el caso que lo justifica.

### H6 — MEDIA. El índice de fila pegado delante del rótulo pegado se lee como duración

**Archivo:línea de la causa:** `numeros_es.py:148-157` — `_RE_UNIDAD` acepta `dias` de
`DIASDEINCAPACIDAD` como **unidad** por la continuación pegada `de` (`_CONTINUACIONES_PEGADAS`), y la
guarda `(?![ \t]*[:\-])` que se añadió para `1 DIAS: 30 (TREINTA)` (falso positivo nº9) **no aplica al
rótulo pegado**, que no lleva dos puntos.

Entrada: el texto **real** de `falsas/FALSA-13.txt` (rótulo
`DIASDEINCAPACIDAD` con el valor perdido, días correctos = 1 porque 12/08 → 12/08), con
`DIASDEINCAPACIDAD` → `3 DIASDEINCAPACIDAD`:

* esperado `dias=None`; obtenido **`dias=3`** (evidencia `'3 dias'`); pre-cambio `None` → **regresión**.
* control: el texto sin tocar devuelve `None` (correcto).
* control: con dos puntos (`3 DIAS:`) la guarda **sí** protege → `None`.

Las dos piezas son reales por separado (rótulo pegado en este archivo; índice de fila delante del
rótulo en `Ejemplos/Incapacidad (19)_unlocked.pdf`, falso positivo nº9), pero **no se han visto juntas**.

### H7 — MEDIA (preexistente + reproducido por el módulo). "DIA:" singular como rótulo de duración

**Archivo:línea de la causa:** `numeros_es.py:204` — `r"dias?\s*[:\-]"` casa con el **singular**
`DIA:`, que en los formularios de rejilla es un rótulo de **fecha** (falso positivo nº7).

| Entrada | Esperado | Obtenido | Pre-cambio |
|---|---|---|---|
| `FECHA DE INICIO` ⏎ `DIA: 12 MES: 08 ANO: 2026` | `None` | **12** (evidencia `'dia: 12'`) | 12 |
| `FECHA DE INICIO` ⏎ `DIA 12 MES 08 ANO 2026` | `None` | **12** (por el respaldo histórico) | 12 |
| `Fecha de expedicion` ⏎ `Dia: 12` ⏎ `Mes: 08` ⏎ `Ano: 2026` | `None` | **12** | 12 |

Los vetos `mes` y `ano` (`numeros_es.py:215-216`) existen justo para esto y no disparan porque están a
la derecha. La rejilla `DIA / MES / ANO` es real (Sofisis, falso positivo nº7) pero **en el corpus va
en renglones separados y sin dos puntos**, y ahí el diseño aguanta: no hay ningún `DIA:` singular en
los 31 textos. Es una variante de formato plausible, no observada.

### H8 — MEDIA. El año escrito en palabras ANCLA una duración del LLM

**Archivo:línea de la causa:** `numeros_es.py:462-486` (`numerales_en_texto`) usado como guarda en
`extract.py:1259` (`_dias_llm`).

`numerales_en_texto("de dos mil veintiseis (2026)")` = **`{2, 26}`**. El camino de **reglas** es
inmune (`mil` no está en el léxico a propósito, `numeros_es.py:51-53`), pero el de anclaje del LLM no:
con un `StubLLM` sobre un texto con el rótulo de días sin valor y el año en palabras,

* LLM `dias=26` → **se acepta** (esperado `None`), porque "veintiseis" (el AÑO) está en el texto;
* LLM `dias=2` → se acepta, por "dos" del mismo año;
* LLM `dias=20` → se descarta correctamente.

La guarda está documentada como "condición NECESARIA, no suficiente", así que esto no contradice el
diseño; lo reporto porque el frente pedía atacar los **años escritos en palabras** y éste es el único
camino por donde entran. Es la forma más peligrosa del anclaje: el `2026` de 4 cifras está bien
bloqueado por `_RE_NUM`, pero **escribirlo en palabras lo cuela**. No es ejecutable con Ollama en esta
máquina (no está levantado): validado por inspección + stub.

---

## Lo que se atacó y NO falla

`duracion_en_texto` devuelve `None` en todo esto (y también en la variante en letras cuando aplica):

* **Horas** — `CADA 8 HORAS` · `NUMERO TOTAL DE HORAS` + `4 irs` · `Favortramitar la incapacidad antes
  de 72 horas` (real) · `CUADRO CLINICO DE 3 HORAS DE EVOLUCION` (real) · `permiso de dos (2) horas` ·
  el bloque real `3.DURACIONDELPERMISO / DIAS / HORAS / DESDE / HASTA`.
* **Permisos reales completos** — `reales/REAL-05.txt` y `real/REAL-08.txt`, con
  el ancla de formato intacta **y destruida a propósito** (para simular que el OCR se come el título):
  `None` en los cuatro casos.
* **Años escritos en palabras por el camino de reglas** — `Duracion` ⏎ `de dos mil veintiseis` ·
  `Expedido a los dos mil veintiseis (2026) dias del mes`.
* **Día del mes de una fecha** — `POR 4 DIAS DESDE EL 29-07-2026 HASTA EL 01-08-2026` → **4**, no 29
  (falso positivo nº5, cerrado) · `Duracion` ⏎ `DE2026` → `None`, no 202 (nº6, cerrado).
* **Edad** — `Edad: 33 Ano(s), 1 mes(es), 8 dia(s)` · `24 anos 05 meses` · `Rango de edad: 25-34`.
* **Semanas de gestación** — `EDADGESTASIONAL:` ⏎ `40.00 Semanas`.
* **Vigencia de dosis / cantidades de insumo** — `Vig: 1 dia` · `ACETAMINOFEN 1 (Uno)`.
* **Queja del paciente** — `dolor desdo hacetresdias.` (el más peligroso para un lector de letras).
* **Artículos indefinidos de la prosa legal** — `una fuerza mayor` · `una cuenta bancaria`.
* **Órdenes de medicamento** — `CADA 8 HORAS POR 5 DIAS` y `CADA 8 HORAS POR CINCO DIAS` (aquí sí
  vetan `cada`/`horas`, que están a la izquierda).
* **Números de trámite / documento** — `IncapacidadN:362.355` · `Consecutivo:` ⏎ `0081523489` ·
  `INC15247`.
* **Registros médicos** — `Registro Medico: 123` · `R.M. 100946` · `Reg.Medico:1030539622` ·
  `R.M14035.1` (todos con un rótulo de días sin valor en el mismo texto).
* **Signos vitales / metadatos** — `glasgow 15/15` · `Regimen: 1 - Contributivo` · `Nivel: 1` ·
  `Pagina 1 de 1` · `01-Consulta externa`.
* **CIE-10 en texto libre** — `Diagnostico: M545 LUMBAGO NO ESPECIFICADO` (en **texto libre** sí; en la
  celda de la tabla, ver H3).
* **Carta de vacaciones con el título canónico** — tipo 13, fechas de la prosa, `dias=14` por
  diferencia de fechas, `dias_letra=None`: la regla de dominio funciona **cuando la detección acierta**.
* **Los 31 textos cacheados** — ninguna duración inventada; ningún cambio respecto del valor correcto.

Las dos suites del repo pasan (`tests/test_processor.py`, `tests/test_numeros_es.py`).

## Lo que NO se pudo verificar

* **Camino real del LLM**: Ollama no está levantado y Docker tampoco (falta elevación UAC). H8 se
  atacó con `StubLLM`; el prompt y el modelo quedan sin ejecutar.
* **Los 8 documentos de `../Ejemplos`**: `tests/test_ejemplos_reales.py` necesita RapidOCR sobre los
  escaneos y no se corrió OCR (había otra medición en la máquina). Es el punto ciego que ya declaraba
  el implementador y sigue abierto.
* **Cartas de vacaciones reales**: no existe ninguna en el corpus. H4 usa el sintético de
  `tests/test_processor.py`; el título canónico contra el que se compara viene de
  `scripts/sembrar_demo.py`, no de un documento del cliente.
* **Realismo de H1/H2/H3/H6/H7**: las construcciones son sintéticas (ninguna está en los 31 textos).
  Lo que sí está en el corpus es la **clase**: la nota de trámite impresa en el certificado, la
  evolución del cuadro clínico, los CIE-10 sin punto, el rótulo pegado y la rejilla DIA/MES/ANO.
