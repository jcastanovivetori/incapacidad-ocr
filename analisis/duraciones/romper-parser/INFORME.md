# Frente `romper-parser` — ataque adversario al lector de numerales

**Objeto:** `incapacidad_ocr/numeros_es.py` (`normalizar`, `texto_a_entero`,
`duracion_en_texto`, `numerales_en_texto`) y sus dos consumidores en
`incapacidad_ocr/extract.py` (`_dias_por_etiqueta`, `_dias_de_celda`).

**Veredicto corto:** el **léxico** y las **guardas de palabra** son sólidos — no
conseguí romperlos con numerales compuestos, con palabras que contienen un numeral
ni con la ambigüedad de "un". Lo que **sí** rompí es el **anclaje**: las tres piezas
que deciden *dónde* buscar el valor (la ventana de 25 caracteres tras el rótulo, la
lista de rótulos y el veto de contexto) producen **6 clases GRAVES** —valor incorrecto,
plausible y en rango, que llegaría a nómina— más **7 clases MEDIAS** (dato perdido, o
guarda que filtra menos de lo que promete). En total **94 discrepancias sobre 251
entradas hostiles**
(196/57 en `ataque_parser.py`, 23/11 en `ataque2_ventanas.py`, 32/26 en
`ataque3_rotulos.py`).

**Buena noticia, y hay que decirla:** sobre los **31 textos OCR ya cacheados** no hay
ni una regresión (`corpus_vs_json.py`): 6 documentos cambian su `dias` respecto al
`.json` anterior y **los 6 cambian a mejor**. Y las dos suites del repo
(`tests/test_numeros_es.py`, `tests/test_processor.py`) siguen en `TODO OK`.
Los fallos de abajo son entradas que el corpus **no contiene todavía**, pero cuya
forma sí está atestiguada en él (lo señalo caso por caso).

## Cómo reproducir

```bash
P=str(_REPO / ".venv/Scripts/python.exe")
cd <dataset-falsedad>/duraciones/romper-parser
$P ataque_parser.py       # bateria general: 196 casos, 57 discrepancias
$P ataque2_ventanas.py    # ventanas y eleccion de vecino: 23 casos, 11 fallos
$P ataque3_rotulos.py     # rotulos, veto y frase parcial: 32 casos, 26 fallos
$P confirmar_hallazgos.py # causa + efecto en el extractor de reglas
$P impacto_nomina.py      # efecto en la fila staging (erp.mapear_a_staging)
$P realismo_corpus.py     # cuantos de los 31 .txt contienen el patron de cada ataque
$P corpus_vs_json.py      # no-regresion: modulo vs extractor vs .json de los 31 .txt
```

**NO se corrió OCR** (había otra medición en la máquina): todo sale de los `.txt`
cacheados en `dataset-falsedad/ocr/**`. Tampoco se ejecutó el camino LLM (Ollama
apagado); `numerales_en_texto` se atacó directamente, que es la parte de ese camino
que vive en este módulo.

---

## GRAVE-1 · La frase numeral se acepta RECORTADA → días de MENOS, en rango, sin señal

`_candidatos_por_etiqueta` solo mira `_VENTANA_ETIQUETA = 25` caracteres detrás del
rótulo (`numeros_es.py:229`, `numeros_es.py:401`), y `_RE_FRASE` acepta con gusto un
**prefijo** de la frase numeral: nadie comprueba que el numeral termine donde termina
el numeral **en el renglón completo**. Cualquier palabra extra en el rótulo consume
el presupuesto y el numeral se parte por la mitad. El prefijo de un numeral español
siempre vale MENOS que el total, así que el resultado es un número plausible, en
rango 1..540, con `origen="letra"` y `coincide=None`: **ninguna señal**.

| entrada | esperado | obtenido |
|---|---|---|
| `Dias de incapacidad autorizados: CIENTO OCHENTA` | 180 | **100** |
| `Duracion del periodo: TREINTA Y CINCO` | 35 | **30** |
| `No. Total dias de incapacidad: TREINTA Y CINCO` | 35 | **30** |
| `DIAS: DOSCIENTOS CINCUENTA Y CINCO (255)` | 255 | **250** |
| `DIAS DE INCAPACIDAD (CALENDARIO): ciento cincuenta y dos` | 152 | **100** |
| `Duracion: novecientos noventa y nueve` | 999 | **990** |
| `Duracion: doscientos setenta y tres dias` | 273 | **270** |

Detalles que agravan esto:

* **`No.Total dias:` es un rótulo REAL del corpus** (`reales/REAL-06.txt`,
  renglón 36) y ya gasta 15 de los 25 caracteres antes de empezar.
* En `DIAS: DOSCIENTOS CINCUENTA Y CINCO (255)` el documento dice 255 **dos veces** y
  el módulo devuelve 250: el recorte se come el `(255)`, así que `dias_letra_coincide`
  se queda en `None` y el desacuerdo que el cambio instrumentó **no puede verse**.
* El caso `(CALENDARIO)` y el `autorizados` son peores que un simple recorte: dejan
  `ciento` solo, que el léxico traduce a **100** (un valor redondo y creíble), no a un
  numeral truncado raro.
* `impacto_nomina.py`: si el documento trae fecha inicio **y** fin, `erp` sí levanta
  "Los tiempos del documento no cuadran…". Si trae **solo fecha inicio** —o ninguna—
  la duración leída es la única fuente y **no se marca nada**:
  `dias=100` (real 180) con `problemas de tiempos: NINGUNO`.

`extract.py:905` (`dias = dias_val if dias_val is not None else dias_calc`) hace que
este valor **pise** el cálculo por fechas, que era correcto.

## GRAVE-2 · El rótulo `dias?\s*[:\-]` acepta el SINGULAR: `Dia:` / `Dia-` son campos de FECHA

`numeros_es.py:204`. En los formularios colombianos "Día:" nunca es una duración: es
la casilla del día del mes (`Dia: 27  Mes: 08  Año: 2026`) o prosa ("el día: …").

| entrada | esperado | obtenido |
|---|---|---|
| `EXPEDIDA EL DIA: 27 DE AGOSTO DE 2026` | None | **27** |
| `Se expide el dia: 27` + `Fecha Inicial: 01/09/2026` + `Fecha Final: 03/09/2026` | 3 | **27** |
| `FECHA DE EXPEDICION (DIA-MES-ANO)` ⏎ `27 08 2026` | None | **27** |
| `FECHA INICIAL DIA - MES - ANO` ⏎ `15 09 2026` | None | **15** |

Controles que confirman la causa: `EXPEDIDA EL DIA 27 …` (sin `:`) → None, y
`(DIA/MES/ANO)` (con `/` en vez de `-`) → None. El corpus tiene la rejilla como
`Dia MeAno Hora Atencion` y `DiaMesAno HoraAtencion` (2 archivos), es decir **a un
guion de distancia** de disparar. Esto reabre por otra puerta el falso positivo nº7
que el módulo declara cerrado: la restricción de renglón protege la rejilla **cuando
el encabezado va en su propio renglón**, no cuando comparte renglón con el rótulo.

## GRAVE-3 · El veto de contexto solo mira a la IZQUIERDA del rótulo → la unidad equivocada entra entera

`numeros_es.py:399` aplica `_RE_VETO` a `linea[:m.start()]`. Lo que va **detrás** del
rótulo no se revisa nunca, así que `horas`, `meses`, `semanas` y `años` —que están en
`_CONTEXTOS_PROHIBIDOS` precisamente para esto— no impiden nada.

| entrada | esperado | obtenido |
|---|---|---|
| `3.DURACION DEL PERMISO: 4 HORAS` | None | **4 días** |
| `DURACION: 2 HORAS` | None | **2** |
| `Duracion del tratamiento: 3 meses` | None | **3** |
| `Duracion: 40 semanas` | None | **40** |
| `Duracion: dos meses` | None | **2** |
| `Duracion aproximada: 2 anos` | None | **2** |

Realismo: `3.DURACIONDELPERMISO` es un rótulo **real**, presente en los 2 permisos del
corpus (`reales/REAL-05.txt:25`, `real/REAL-08.txt:28`), y es
además el único rótulo del corpus con texto a su derecha (`realismo_corpus.py`: 2/31).
Hoy devuelve `None` **solo porque el OCR dejó el valor en otro renglón**; en cuanto un
permiso salga con las horas en el mismo renglón, un permiso de 4 horas entra a nómina
como 4 días. La decisión "no toqué el camino de permisos porque el módulo devuelve
None en los 2 permisos del corpus" descansa en un accidente de layout, no en una guarda.

## GRAVE-4 · Que "mil" no esté en el léxico protege a `texto_a_entero`, no a `duracion_en_texto`

El docstring (`numeros_es.py:50-53`) explica que "mil" se deja fuera para que un año en
palabras devuelva `None`. Es cierto para `texto_a_entero("dos mil veintiseis") → None`,
pero `duracion_en_texto` se queda con el **fragmento anterior o posterior**:

| entrada | esperado | obtenido |
|---|---|---|
| `Duracion: mil ochenta` | None (1080 fuera de dominio) | **80** |
| `Dias de incapacidad: dos mil veintiseis` | None (es un año) | **2** |
| `Duracion: del dos de enero de dos mil veintiseis` | None | **2** |

Misma causa raíz que GRAVE-1: se acepta una frase numeral **parcial**.

## GRAVE-5 · Un renglón que "parece de valor" puede ser un fragmento de fecha

`_es_linea_de_valor` (`numeros_es.py:361-374`) acepta cualquier renglón sin letras
que no sean numerales, y el `-` y el `.` están en la lista de caracteres que se
descartan. Con eso, `Duracion` ⏎ `26` → **26 días** y `Dias Incapacidad` ⏎ `06` → **6**.
Eso **es** la forma A4 legítima (`DURACION:` ⏎ `126`), así que no hay bug en el caso
aislado; el problema es que el corpus demuestra que el OCR **parte las fechas en
renglones de un fragmento cada uno**: `real/REAL-08.txt` tiene siete
renglones así (`04`, `06`, `26`, `06`, `06`, `26`, `06`) y uno con la cédula. Que hoy
ese archivo dé `None` depende de qué renglón cayó al lado del rótulo. Un fragmento
`26` junto a un rótulo de duración da 26 días y es indistinguible de una duración real.
Ver también GRAVE-2, filas de rejilla.

## GRAVE-6 · Rótulos sin frontera de palabra por la izquierda

`numeros_es.py:198-205`: ni `dias?\s*[:\-]` ni `duracion` llevan `\b`.
`GUARDIAS: 3` → **3**, `MEDIAS: 2 PARES` → **2**, `Duraciones anteriores: 9` → **9**.
Realismo bajo (no hay nada así en los 31 textos), pero el coste de la guarda es un
`\b` y el fallo es un dato incorrecto.

---

## MEDIA-1 · El veto es tan amplio que se lleva por delante duraciones correctas

`_CONTEXTOS_PROHIBIDOS` (`numeros_es.py:211-220`) se evalúa sobre 40 caracteres a la
izquierda **del renglón entero**, sin exigir que el término vetado esté entre el
contexto y el valor. `\bhace` además no tiene frontera derecha, así que casa con
"hace **necesario**", "se hace entrega".

| entrada | esperado | obtenido |
|---|---|---|
| `Por lo anterior se hace entrega de incapacidad por 3 dias` | 3 | **None** |
| `Se hace necesario otorgar 5 dias de incapacidad` | 5 | **None** |
| `Reposo 24 horas y se otorgan 5 dias de incapacidad` | 5 | **None** |
| `Acetaminofen cada 8 horas. Se incapacita por 5 dias` | 5 | **None** |
| `Control en 1 mes. Incapacidad por 7 dias` | 7 | **None** |
| `Gestante de 40 semanas. Incapacidad de 30 dias` | 30 | **None** |
| `Hora Aten. 08:23 Dias de Incapacidad: 3` | 3 | **None** |
| `Fecha y Hora Ing: 01/09/2026 08:23 Dias: 3` | 3 | **None** |

Es MEDIA y no GRAVE porque el dato se **pierde** (cae al cálculo por fechas o a la
revisión humana), no se falsea. Pero las cuatro primeras son prosa médica corriente
en un resumen de atención; el patrón "horas/mes/semanas en el mismo renglón que
`dias`" ya aparece en **5 de los 31** textos (`realismo_corpus.py`); y las dos últimas
usan texto **literal** del corpus (`Hora Aten.` en `reales/REAL-10.txt:18`,
`Fecha y Hora Ing:` en otro real), que basta con que el OCR junte el encabezado con la
fila de valores —cosa que hace— para anular la duración correcta.

## MEDIA-2 · Un `:` o un `-` detrás de la unidad descarta el valor que va DELANTE

La guarda `(?![ \t]*[:\-])` de `_RE_UNIDAD` (`numeros_es.py:155-157`) existe para no
leer el índice de fila de `1 DIAS: 30 (TREINTA)`. El coste es que la unidad deja de
anclar cuando lo que sigue es un separador:

| entrada | esperado | obtenido |
|---|---|---|
| `INCAPACIDAD: 3 DIAS - INICIA 01/09/2026` | 3 | **None** |
| `Se otorgan 10 DIAS-CALENDARIO` | 10 | **None** |
| `30 DIAS : del 01/09/2026 al 30/09/2026` | 30 | **None** |

Relacionado y por diseño: el rótulo escueto sin separador (`Dias 3`, `Dias   5`) el
módulo lo rechaza a propósito, y ahí sí actúa el respaldo histórico de
`extract.py:307-308`. Conviene tenerlo presente antes de retirar ese respaldo.

## MEDIA-3 · Se elige un solo renglón vecino y no se reintenta con el otro

`numeros_es.py:418-424`: `vecino_ok` toma el **primero** de `(idx+1, idx-1)` que
`_es_linea_de_valor` acepte; si de ese no sale valor, se hace `continue` y el otro
vecino **no se prueba**. Un consecutivo o una cédula en el renglón siguiente tapa el
valor del renglón anterior:

| entrada | esperado | obtenido |
|---|---|---|
| `-DOS` ⏎ `Duracion` ⏎ `0081523489` | 2 | **None** |
| `-DOS` ⏎ `Duracion` ⏎ `CED-13` | 2 | **None** |
| `126` ⏎ `DURACION:` ⏎ `0081523489` | 126 | **None** |
| `-DOS` ⏎ `Duracion` (control) | 2 | 2 ✔ |

Lo caro: la forma B1 (`Duracion` ⏎ arriba `-DOS`) es **el caso oro de fraude** del
corpus, el único donde leer letras es lo que permite tener el dato. Y las cédulas y
consecutivos de 10 cifras en renglón propio existen de verdad
(`real/REAL-08.txt`).

## MEDIA-4 · La preferencia por la forma mixta hace ganar a un valor POSTERIOR e irrelevante

`_armar`/orden de candidatos (`numeros_es.py:313-320`, `numeros_es.py:455`): `origen="ambos"`
gana a `"numero"` **sea cual sea su posición**.
`INCAPACIDAD POR 15 DIAS` ⏎ `FORMULA: DIAS: 3 (TRES) DE TRATAMIENTO` → **3** (esperado 15),
con `coincide=True`, que aparenta doble confirmación. Caso sintético: no hay nada así
en el corpus.

## MEDIA-5 · `numerales_en_texto` ancla el año en palabras y los numerales pegados

`numeros_es.py:462-486`. Es la guarda anti-alucinación del camino LLM, y admite de más:

* `numerales_en_texto("dos mil veintiseis (2026)")` → `{2, 26}`. O sea: en una carta que
  solo contiene el **año** en palabras, el LLM puede devolver `dias=26` o `dias=2` y la
  guarda lo acepta como "su expresión está en el documento". Es justo el texto que el
  módulo cita como motivo para excluir "mil".
* `numerales_en_texto("dosdiagnosticos")` → `{2}`, `("unadiabetes mellitus")` → `{1}`:
  `_RE_FRASE` cierra con `(?=dias?)`, y "diagnosticos"/"diabetes" empiezan por "dia".

No lo pude ejercitar con Ollama (apagado), así que el impacto real depende de la
política de fusión; como guarda, filtra menos de lo que su docstring promete.

## MEDIA-6 · Formas analíticas arcaicas → `None`

`diez y seis` → None, `diez y ocho` → None, `veinte y uno` → None (y también vía
`duracion_en_texto`). Están atestiguadas en redacción jurídica colombiana. Dato perdido,
no falseado. Arreglo trivial (3 entradas en `_ESPECIALES` o una rama en `_combinar`).

## MEDIA-7 · El rótulo `DIAS` degradado por OCR no tiene corrección

`D1AS DE INCAPACIDAD: 3` → None; `DlAS DE INCAPACIDAD: 3` → None. Hay correcciones
para `incapac[il]dad` y para `3Dian` (`numeros_es.py:95-104`) pero no para la I de
"DIAS" leída como `1`/`l`, que es la confusión más frecuente del OCR. Además
`normalizar` separa dígito de letra, así que `D1AS` se convierte en `d 1 as` y ni el
rótulo ni la unidad casan.

---

## LEVE-1 · `_dias_por_etiqueta` no aplica el rango 1..540 y `_dias_de_celda` sí

`extract.py:304` devuelve `dur["valor"]` tal cual; `extract.py:326` sí acota.
`Duracion: 0 dias` → `dias=0`; `Duracion: 999 dias` → `dias=999`.
Mitigado: `erp.mapear_a_staging` lo marca ("El número de días leído (=0) está fuera
del rango válido 1..540"), así que no llega limpio a nómina. Es una asimetría entre dos
funciones hermanas, no un dato que se cuele.

## LEVE-2 · Contrato de tipos: cualquier entrada no-`str` revienta

Las cuatro funciones públicas anuncian `str | None` y hacen `if not texto` como única
defensa, así que un `int`, `float`, `bool`, `list` o `dict` provoca `AttributeError`
(20 combinaciones probadas, 20 excepciones). Hoy no hay ningún llamador que lo haga;
queda como contrato frágil de cara al camino LLM, donde los valores llegan del JSON
del modelo.

---

## Qué ataqué y NO conseguí romper

Esto es la otra mitad del resultado: el núcleo del lector es sólido.

1. **Numerales compuestos** — 27/27 correctos vía `texto_a_entero`: `cuarenta y uno`,
   `cuarentayuno`, `cuarenta uno` (sin "y"), `ciento uno`, `ciento un`, `cientouno`,
   `quinientos cuarenta`, `quinientos cuarenta y uno`, `novecientos noventa y nueve`,
   `doscientas veinte`, `treinta y cinco`, `treinta cinco`, `veintiun`, `veintiuna`,
   `dieciseis` con y sin tilde y en mayúsculas, `cero`, `un`/`uno`/`una`.
2. **Rechazos correctos**: `cien veinte` (cien es exacto), `doscientos trescientos`,
   `treinta y cero`, `treinta y`, `y`, `y y y`, `mil`, `dos mil veintiseis`,
   `cuarenta y i cinco` (separador ilegible).
3. **Palabras que CONTIENEN un numeral** — 16/16 dan `None`: `veinteava`, `veinteavo`,
   `ochentavo`, `quinceava`, `cientifico`, `docente`, `seismico`, `unidad`, `dosis`,
   `dosificacion`, `unicamente`, `tresillo`, `diario`, `nueves`, `doses`, `tresmil`.
   La guarda `(?<![a-z])` + el cierre en no-letra aguantan lo que les tiré.
   Y `seiscientos`/`seiscientas` → 600 (la alternación más-largo-primero funciona).
4. **Ambigüedad de "un"** — 8/8 correctos: `un paciente`, `una vez al dia`,
   `tomar una tableta cada dia`, `Aplicar una dosis por dia`, `hace un dia` → `None`;
   `Se concede un dia de incapacidad` → 1.
5. **Fechas, horas y consecutivos**: `18/05/2026`, `01-09-2026`, `0081523489`,
   `08:23:39`, `1.5 dias`, `Duracion` ⏎ `2026`, `Duracion` ⏎ `01-09-2026` → ninguno se
   lee como duración. `_RE_NUM` es una guarda eficaz.
6. **Recorte por la izquierda de la unidad**: imposible por construcción —
   `_VENTANA_IZQ = 40` > 28, la longitud del numeral más largo (`novecientos noventa y
   nueve `). Barrido de 60 longitudes de relleno × 4 numerales: 0 lecturas erróneas.
   El recorte de GRAVE-1 solo ocurre por el lado del rótulo, donde la ventana es 25.
7. **Entradas degeneradas (str)**: `None`, `""`, `"   "`, `"\n\n\n"`, `"\x00\x00"`,
   `"dias"`, `"DIAS:"`, `"Duracion"`, `"()"`, `"- - -"` → `None` sin excepción.
8. **Coste / ReDoS**: 11 cargas de 60 KB–400 KB, incluidas las clásicas de backtracking
   (`"dos"×20000 + "z"`, `"dos y "×20000`, numeral + 200 000 espacios + corte,
   `"DIAS DE INCAPACIDAD: 2 DIAS"×10000`) → **máximo 0,79 s**. No encontré explosión
   combinatoria. El colapso de espacios de `normalizar` además desactiva el ataque de
   "meter espacios para desbordar la ventana de 25".
9. **No-regresión sobre el corpus**: `corpus_vs_json.py`, 31 textos cacheados. 6 filas
   difieren del `.json` y las 6 mejoran (desaparecen el 202 de `DE2026` y el 29 de
   `DESDE EL 29-07-26`; tres documentos que antes daban `None` ahora dan valor, entre
   ellos el `duracion -dos` del caso oro). Las suites del repo siguen en `TODO OK`.

## Lo que NO pude verificar

* **Camino LLM**: Ollama y Docker apagados (falta elevación UAC). Ataqué
  `numerales_en_texto` de forma aislada, no la fusión con la respuesta del modelo.
* **Los 8 documentos de `../Ejemplos`**: `tests/test_ejemplos_reales.py` necesita
  RapidOCR y no corrí OCR. Si alguno trae un rótulo largo con la duración en letras,
  GRAVE-1 se aplica ahí y no se vería en las pruebas actuales.
* **Realismo de GRAVE-1 y GRAVE-2 en documentos reales**: no hay en el corpus ninguna
  duración en letras de más de dos palabras (`realismo_corpus.py`: 0/31), ni ninguna
  rejilla `DIA-MES-ANO` con guion. Los rótulos que los disparan (`No.Total dias`,
  `DURACION DEL PERMISO`, `Dia MesAno`) sí son reales.
