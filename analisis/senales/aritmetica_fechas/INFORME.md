# Familia `aritmetica_fechas` — coherencia aritmética de fechas y días

Cubre la señal **FECHAS_INCOHERENTES** del ground truth
(*"ALTERACION EN FECHA DE INICIO, DURACION Y FECHA FIN, LOS DIAS NO CORRESPONDEN A LA FECHA DE
FINALIZACION CALCULADA"*).

- Sonda: [`probe.py`](probe.py) · salida por documento: [`_salida.txt`](_salida.txt) ·
  detalle máquina: [`resultados.json`](resultados.json)
- Ejecutar: `<repo>/.venv/Scripts/python.exe probe.py`
  (`--solo-autoprueba` = sólo los casos sintéticos; `--con-nombres` = muestra el nombre real
  del archivo, que contiene PII)
- 100% local: `re` + `datetime` + helpers de sólo lectura del paquete `incapacidad_ocr`.
  Sin red, sin IA, sin Docker, sin Ollama.

> **PII (Ley 1581).** Los nombres de archivo del corpus contienen nombres de pacientes. Este
> informe identifica cada documento con un **ID estable + los 8 primeros del sha256**
> (`manifest.csv` da la equivalencia). El mapeo ID → nombre de archivo queda sólo en
> `resultados.json`, en disco.

---

## 1. La regla sobre la que se construye (no se reinventa nada)

El repo ya tiene la invariante y la reconciliación; esta familia sólo la **audita**.

| Fuente en el repo | Qué dice |
|---|---|
| `CLAUDE.md` §Reglas de dominio | `fechavencimiento = fechainicio + Numerodias` (**no inclusivo**, es el campo del ERP) · `dias` válido = **1..540** |
| `CLAUDE.md` §Reglas de dominio | Si falta el inicio → `inicio = fin − (días − 1)` (**inclusivo**) y se marca `fecha_inicio_calculada` (aviso, no bloquea) |
| `extract.normalizar_fechas()` | implementa la forma **inclusiva**: `df = di + timedelta(days=n-1)` y compara `(df - di).days + 1 != n` |

Las dos formas son la misma ecuación con distinto punto de corte: la **fecha fin impresa** en el
papel es el **último día de la incapacidad** (inclusiva), y `fechavencimiento` del ERP es el día de
**reintegro** (= fin + 1). El check usa la inclusiva, que es la que compara contra el papel:

```
span = (fin_impreso − inicio_impreso).days + 1
CHECK:  span == dias_impreso          desfase = span − dias_impreso
```

**Evidencia de que la convención inclusiva es la correcta para el papel:** los **4** documentos
REALES del corpus que traen las tres patas impresas dan `desfase = 0` exacto (R07 span 14/dias 14,
R09 126/126, R11 2/2, R13 30/30), incluidas dos EPS distintas y una licencia de maternidad de 126
días. Ningún emisor real del corpus usa la convención no inclusiva. Con n=4 es indicio, no prueba.

### 1.1 Por qué la sonda NO usa los campos ya extraídos del dataset

Los JSON de `dataset-falsedad/ocr/` se produjeron con `IncapacidadProcessor`, que aplica
`normalizar_fechas()`. Esa función **re-deriva `fecha_fin`** cuando inicio+días son fiables y la fin
no cuadra… **y no deja marca alguna** (el único aviso, `fecha_inicio_calculada`, es para el inicio).
Es decir: **el pipeline actual borra exactamente la evidencia que esta familia necesita.** Caso
concreto medido: en F09 el papel dice `Hasta:06/07/2026` y el JSON del pipeline guarda
`fecha_fin = 2026-06-06` (recalculada). Por eso la sonda vuelve al **texto plano** y relee cada pata
con su **procedencia**.

---

## 2. Los checks

Todos operan sobre el texto plano ya OCR-eado (RapidOCR, ONNX/CPU) y reutilizan del repo
`_find_date`, `_norm_date`, `_fecha_valida`, `_days_between`, `_extraer_detalle_incapacidad`,
`_DATE`, `_DMA_TRIPLET`, `_MESES_ES`.

### AF01_TRIPLE_IMPRESA_INCOHERENTE — el núcleo de la familia
- **Afirma:** las tres patas (inicio, fin, días) **están impresas en el documento** y se contradicen:
  `(fin − inicio) + 1 ≠ días`.
- **Cómo se calcula:**
  1. `leer_impresos(texto)` recupera cada pata con su procedencia, por estas vías (en orden):
     `tabla_detalle` (`_extraer_detalle_incapacidad`, 5 columnas del formato Clínica del Cesar) ·
     `etiqueta_inicio` / `etiqueta_fin` (`_find_date` con los rótulos estrictos del repo) ·
     `prosa_desde` / `prosa_hasta` (*"POR 4 DIAS DESDE EL … HASTA EL …"*, ventana de 8 caracteres) ·
     `escrita_sura` (fecha en palabras: *"MARTES 02 DE SEPTIEMBRE DE 2025"*) ·
     `emision_como_inicio` (respaldo del formato Clínica Medical Duarte, donde el repo ya asume
     emisión = inicio).
  2. Días impresos (`_dias_impresos`): `Duración`+dígitos · `Días [de incapacidad]`+dígitos **en la
     misma línea** · prosa `POR n DÍA(S)` · **número escrito en palabra** junto a `Duración`
     (`-DOS`, `14- CATORCE`).
  3. **Si falta una sola pata → `NO_APLICA`.** Si dos lectores dan valores distintos para la misma
     pata → `NO_APLICA` (lectura en conflicto). Nunca se juzga con un dato derivado.
  4. `span = (fin − inicio).days + 1`; se reporta `desfase = span − días`,
     `esperado_fin_inclusivo = inicio + (días − 1)` y la clase `off_by_one` (|desfase| = 1) o
     `grueso` (≥ 2).
- **Determinista:** sí (aritmética de calendario; ninguna probabilidad, ningún umbral aprendido).
  Lo único no determinista del conjunto es la **lectura** OCR, no el check.
- **Nivel:** `ALTA`, salvo cuando el inicio viene de `emision_como_inicio` (proxy semántico) →
  `MEDIA`.
- **Datos externos que le faltan:** ninguno para decidir. Para **subir la confianza** le falta
  (a) que el extractor exponga la **procedencia por campo** (`fin_impreso`, `dias_impreso`, como ya
  hace con `fecha_inicio_calculada`); (b) **coordenadas del OCR** (RapidOCR las produce, el pipeline
  no las expone) para emparejar rótulo↔celda sin heurística de orden.

### AF02_RANGO_INVERTIDO
- **Afirma:** la fecha fin impresa es **anterior** al inicio impreso (`span ≤ 0`).
- **Cómo:** con las dos fechas impresas y **orden conocido** (no aplica cuando las fechas vienen de
  `escrita_sura`, donde sin coordenadas no se sabe qué celda es cuál y se ordenan cronológicamente).
- **Determinista:** sí. **Datos externos:** ninguno.

### AF03_DIAS_FUERA_DE_RANGO
- **Afirma:** el número de días impreso está fuera del rango de dominio `1..540` del repo.
- **Cómo:** se usan los **candidatos crudos** de `_dias_impresos` (mismas guardas anti-fecha),
  filtrando ≥ 1000 (un valor de 4 cifras junto a `Duración` es un año mal leído, no una duración).
- **Determinista:** sí. **Datos externos:** ninguno (el tope 540 ya es regla del repo).

### AF04_DIA_SEMANA_INCONSISTENTE
- **Afirma:** el **día de la semana impreso** no corresponde a la fecha impresa
  (*"LUNES 02 DE SEPTIEMBRE DE 2025"*, cuando el 2 de septiembre de 2025 fue martes).
- **Cómo:** los certificados EPS tipo Sura imprimen el día de la semana; se compara con
  `date.fromisoformat(f).weekday()`. Es una **suma de verificación gratuita**: quien altera un día
  del mes casi nunca recalcula el día de la semana.
- **Determinista:** sí en el cálculo; **heurístico en la atribución**: si el OCR desordenó las
  celdas, el desajuste puede ser mío y no del papel. Por eso, cuando falla, la sonda **descarta el
  ensamblado** (no lo usa para AF01) y emite AF04 como señal aparte de nivel `MEDIA`.
- **Datos externos:** ninguno. Lo que le falta son **coordenadas del OCR** para separar
  "mal impreso" de "mal leído".

### AF05_FECHA_FUERA_DE_CALENDARIO
- **Afirma:** hay una fecha impresa imposible (`31/02/2026`) en cualquiera de los dos órdenes
  (dd/mm y mm/dd).
- **Cómo:** se escanean los tokens `dd/mm/aa(aa)` del texto y se validan con `_fecha_valida`.
  Importa porque el pipeline actual **descarta en silencio** la fecha inválida (`_norm_date`
  devuelve `None`) y el rastro se pierde.
- **Determinista:** sí. **Datos externos:** ninguno.

### AF06_ANIO_ATIPICO *(heurístico)*
- **Afirma:** el año de una pata de la tripleta se aparta **≥ 2 años** del año modal del documento.
- **Cómo:** año modal = moda de todos los `19xx|20xx` del texto; se compara con el año de
  inicio/fin impresos.
- **Determinista:** no (umbral arbitrario de 2 años, elegido para no castigar incapacidades que
  cruzan el fin de año). Es un **aviso**, nunca una decisión.
- **Datos externos:** le falta la **fecha de radicación/recepción del trámite** (del ERP) para
  contrastar contra algo que no sea el propio documento.

### Fuera de esta familia (no se implementan aquí)
`DIAS_VS_DIAGNOSTICO` (días plausibles para el CIE-10) necesita **catálogo CIE-10 + histórico de
`lpausentismos`** y es otra familia. Detectar **prórrogas solapadas** o una incapacidad que **repite
fechas** de un trámite anterior necesita el **histórico del ERP** (`lpausentismos` por cédula) —
tampoco está aquí, y es la extensión de mayor valor de esta familia.

---

## 3. Medición real (corrida del 2026-09-02)

Corpus: 31 documentos (15 falsas / 16 reales). **Se excluyen los 5 documentos en CUARENTENA**
(`F03`, `F11`, `F15`, `R01`, `R15`): dos parejas byte-idénticas etiquetadas en ambas clases y un
documento que comparte cédula con otro de la clase opuesta. Base evaluable: **12 falsas / 14 reales**.

| Métrica | Resultado |
|---|---|
| FALSAS detectadas | **2 / 12** (`F04`, `F09`) |
| REALES marcadas por error (falsos positivos) | **0 / 14** |
| Señal propia de la familia (`FECHAS_INCOHERENTES` en el ground truth) | **1 / 1** (`F04` = e0ee54fd) |
| Documentos con tripleta impresa COMPLETA (evaluables por AF01) | 12 / 26 (8 falsas, 4 reales) |
| Documentos `NO_APLICA` (falta una pata impresa) | 14 / 26 (**54 %** — la familia calla, por diseño) |
| Precisión sobre lo que marca | 2/2 = 100 % (n minúsculo: dos casos) |

Por check, sobre el corpus evaluable:

| Check | Falsas | Reales | Nota |
|---|---|---|---|
| AF01_TRIPLE_IMPRESA_INCOHERENTE | 2 | 0 | `F04` desfase +1 · `F09` desfase +30 |
| AF02_RANGO_INVERTIDO | 0 | 0 | el corpus no trae ningún rango invertido |
| AF03_DIAS_FUERA_DE_RANGO | 0 | 0 | ningún documento imprime días fuera de 1..540 |
| AF04_DIA_SEMANA_INCONSISTENTE | 0 | 0 | los 3 documentos con día de la semana impreso **cuadran** (F04, R07, R16) |
| AF05_FECHA_FUERA_DE_CALENDARIO | 0 | 0 | no hay fechas imposibles en el corpus |
| AF06_ANIO_ATIPICO | 0 | 0 | sólo dispara en la pareja en cuarentena |

**AF02/AF03/AF04/AF05 reportan 0 porque el corpus no contiene ningún caso suyo, no porque no
funcionen**: `probe.py --solo-autoprueba` corre **9 casos sintéticos** (datos inventados, sin PII)
que ejercen cada check y sus reglas de abstención — **9/9 correctos**.

### 3.1 Los dos aciertos

- **`F04` (e0ee54fd)** — es el documento que el cliente marcó como `FECHAS_INCOHERENTES`. Certificado
  EPS con fechas escritas en palabras: inicio **02**, fin **04**, duración **DOS**.
  `span = 3 ≠ 2` → `desfase = +1`. **Verificado sin depender del OCR:** la capa de texto embebida del
  propio PDF (2112 caracteres, ClearScan) contiene `MARTES 02`, `JUEVES 04 DE`, `SEPTIEMBRE DE` y la
  celda de duración `DOS`. La contradicción está **en el papel**, no en el OCR. Además el nombre del
  archivo del cliente dice "3 DÍAS", coherente con el rango y no con la duración impresa.
- **`F09` (d5b72739)** — el ground truth lo marcó por diagnóstico (`DX_INEXISTENTE`, `DX_FORMATO`),
  pero además su tripleta impresa se contradice: *"Dias de incapacidad: 02 dos dia(s)"* con
  *"Desde: 05/06/2026 – Hasta: 06/07/2026"* → `span = 32 ≠ 2` (`desfase = +30`, el mes de la fin
  cambiado). Es un **JPEG** (sin capa de texto), así que un dígito mal leído es posible, aunque un
  salto de mes completo es difícil de atribuir al OCR. Cuenta como acierto de la familia sobre un
  documento adulterado, con motivo distinto al registrado.

### 3.2 Falsos positivos: 0 en la versión final; 1 falso positivo real + 3 lecturas erróneas, medidos y corregidos

En la primera corrida hubo **1 falso positivo real** (AF03 sobre `R16`, un documento **REAL**) y
otras **3 lecturas erróneas** del número de días que no llegaron a marcar nada sólo porque a esos
documentos les faltaban las fechas — pero habrían corrompido la tripleta en cuanto se leyeran. Los
cuatro casos son la parte importante del informe: **todos venían de leer mal el número de días, no de
la aritmética.**

| Lectura ingenua | Documento | Qué leía | Causa | Corrección (genérica) |
|---|---|---|---|---|
| `Duración` + dígitos con patrón laxo → **marcó AF03** | `R16` (272d0d3d, **REAL**) | `dias = 2026` de `"Duracion\nDE2026"` | el año de la fecha escrita cae justo detrás del rótulo | guarda `(?<![\d/-])(\d{1,3})(?![\d/-])` (no toma trozos de un número mayor) y descarte de ≥ 1000 |
| dígitos **antes** del rótulo | `R16` (272d0d3d, **REAL**) | `dias = 9` de `"MARTES 09 DE JUNIO Duracion"` | el día del mes queda pegado al rótulo de duración | hacia atrás **sólo se aceptan palabras** (`-DOS`), nunca dígitos: la palabra es auto-identificable, un `09` no |
| `d[ií]as?` sin límite de palabra | `F13` (99d74f47) | `dias = 10` de `"DIAGNOSTICOCIE10"` | `DIA` casa dentro de `DIAGNOSTICO` | rótulo `\bd[ií]as?\b` o la frase completa `d[ií]as de incapacidad` |
| valor en otra línea | `R03` (b68fe146, **REAL**) | `dias = 25` de `"DIA\n25"` | el OCR de tabla pone el valor lejos del rótulo | el valor debe estar en la **misma línea** (`[^\S\n]`), salvo `Duración` |

**Este mismo defecto está VIVO en producción** (no se corrigió: esta fase es de sólo lectura). En
`extract.py` el patrón `duraci[oó]n\b[^\d]{0,10}(\d{1,3})` lee **`dias = 202`** para `R16`
(un documento **real**), valor que pasa el rango 1..540 de `normalizar_fechas()` y entraría a
`lp_ausentismos_ia` como 202 días de incapacidad. Está en `resultados.json`
(`campos_pipeline.dias = 202`). Vale reportarlo aparte de esta familia.

### 3.3 La pareja en cuarentena dispara el check

`F03` == `R15` (**mismo sha256**, 28c4a946, etiquetado a la vez como falsa y como real) contiene
impreso: *"SE DA INCAPACIDAD MEDICA POR 4 DIAS DESDE EL 29-07-26 HASTA EL 01/07/29"*. Con 4 días
desde el 29/07/2026 la fin debería ser 01/08/2026; el papel imprime `01/07/29`.
Confirmado en la **capa de texto embebida del PDF** (959 caracteres, leída con `pypdfium2`): la
cadena está así en el documento, no es error de OCR. Queda **fuera de la medición** porque su
etiqueta está corrupta, pero conviene decirlo: si esa pareja se resolviera como *falsa*, la familia
detectaría 3/13; si se resolviera como *real*, sería 1 falso positivo — y sería un falso positivo
**del emisor** (un formato que imprime la fin con otro formato/orden de campos), no del check.

---

## 4. El confusor principal de la familia

**No es la aritmética: es el emparejamiento rótulo ↔ valor sin coordenadas del OCR.**

El pipeline entrega **una sola cadena de texto** (`ocr._combinar_paginas`), sin cajas. En los
formularios reales el OCR colapsa las columnas y el valor aparece **antes** de su rótulo, o entre dos
rótulos ajenos. Ejemplos medidos:

- `R04` (38f40c48, real): el orden del texto es
  `"Dias de Incapacidad:\n11/7/2026\nFecha de Inicio de Incapacidad:\n12/7/2026\nFecha Fin de
  Incapacidad:"`. En este formato **cada valor precede a su rótulo**, así que el inicio impreso es
  `11/7/2026` y la fin `12/7/2026`; el ancla de rótulo (que mira primero hacia adelante) devuelve
  `2026-07-12` **como inicio** — es decir, la fin. Hoy no hace daño porque la tripleta queda
  incompleta (`NO_APLICA`), pero con un tercer valor legible el check se equivocaría.
- `F04` y `R07` (Sura): las celdas salen partidas
  (`JUEVES 04 DE` / `MARTES 02` / rótulos / `SEPT1EMBRE DE2025` / `DESEPTIEMBRE DE 2025`) y hay que
  ensamblarlas por posición. La sonda sólo acepta el ensamblado si **todos los días de la semana
  impresos cuadran** con las fechas resultantes (en F04 y R07 cuadran), y aun así marca
  `orden_incierto` y usa la prueba **libre de orden** (`|span| + 1 == días`), que no necesita saber
  cuál celda es inicio. Detalle relevante: en `F04` el pipeline actual **no lee ninguna** de las tres
  patas (`fecha_inicio`, `fecha_fin` y `dias` quedan en `null` en el JSON del dataset) — el documento
  adulterado entraría a staging sin fechas y sin señal. La sonda sí las recupera.

**Segundo confusor: la convención.** El único acierto propio de la familia (`F04`) falla por
**exactamente un día**, que es lo mismo que produciría un emisor que imprimiera en "Fecha Fin" el día
de **reintegro** (convención no inclusiva, la de `fechavencimiento` del ERP). Con este corpus la
distinción se sostiene (4/4 reales dan desfase 0), pero es la primera cosa que hay que revalidar
cuando entren EPS nuevas: **si aparece un emisor no inclusivo, `desfase = +1` deja de ser señal** y
habría que tratarlo por emisor (mantener una lista de convención por NIT/EPS).

**Tercer confusor: el OCR de un solo dígito.** En imágenes (`F09` es JPEG) un `06`↔`07` cambia el mes
y fabrica un desfase de 30 días. De ahí la escala de severidad de abajo.

---

## 5. Severidad recomendada

**ALERTA** para AF01 (y AF02/AF05), **AVISO** para AF03/AF04/AF06. **BLOQUEA** sólo en un caso
concreto y verificable:

| Condición | Severidad | Por qué |
|---|---|---|
| AF01 con `desfase ≠ 0`, nivel `ALTA`, y `confirmable_sin_ocr = True` (el PDF trae capa de texto propia: la contradicción se lee sin OCR) **y** `clase = grueso` | **BLOQUEA** | no hay explicación técnica: el documento se contradice consigo mismo en su propio texto digital. No debe llegar a pago sin resolución. |
| AF01 con `desfase ≠ 0` en cualquier otro caso (imagen escaneada, `clase = off_by_one`, o inicio tomado de `emision_como_inicio`) | **ALERTA** | un dígito mal leído (JPEG) o un emisor con convención no inclusiva producen exactamente esto. Debe pararse el trámite y exigir revisión humana con las tres cifras resaltadas, pero no acusar. |
| AF02 (rango invertido), AF05 (fecha imposible) | **ALERTA** | son imposibilidades, pero también los errores de OCR más típicos en tablas. |
| AF03, AF04, AF06 | **AVISO** | AF03 y AF04 son deterministas pero de atribución ambigua (mal impreso vs. mal leído); AF06 es heurístico con umbral arbitrario. Se anotan en la ficha de revisión y no cambian el estado. |

Encaja con el flujo actual sin inventar nada: `ALERTA`/`AVISO` = fila en
`lp_alertas_documentacion` + `estado = PENDIENTE_REVISION` (el auxiliar decide, como ya pasa con
`fecha_inicio_calculada`); `BLOQUEA` = no se permite APROBAR (el mismo 409 que ya usa `webapp.py`
para obligatorios faltantes).

**Nota operativa:** con este corpus, AF01 en `BLOQUEA` sólo se habría activado en `F04` (0 falsos
positivos) — pero `F09`, que es adulterado, se habría quedado en `ALERTA` por ser imagen. Es el
precio correcto de no bloquear por un dígito mal leído.

---

## 6. Qué le falta a esta familia para valer más

1. **Procedencia por campo en el extractor.** Que `RuleBasedExtractor` marque `fin_impreso` /
   `dias_impreso` igual que ya marca `fecha_inicio_calculada`, y que `normalizar_fechas()` **conserve**
   la fin leída (p. ej. en `fecha_fin_leida`) en vez de sobrescribirla en silencio. Hoy la sonda tiene
   que re-leer el texto porque el pipeline destruye la evidencia.
2. **Coordenadas del OCR.** RapidOCR devuelve cajas; `ocr.py` sólo devuelve texto. Con cajas, el
   emparejamiento rótulo↔celda deja de ser heurístico y AF01 sube de "ALERTA" a "BLOQUEA" en muchos
   más documentos (y AF04 se vuelve atribuible).
3. **Histórico del ERP (`lpausentismos` por cédula).** Es lo que permitiría los checks que hoy no
   existen: **prórroga que se solapa** con un ausentismo ya pagado, **misma fecha reutilizada** en dos
   trámites, y días acumulados por año. Es la extensión más rentable.
4. **Convención por emisor.** Una tabla NIT/EPS → inclusiva/no inclusiva (se llena en revisión) para
   que `desfase = +1` no se convierta en ruido cuando entren EPS nuevas.
5. **Corpus.** Un solo documento etiquetado con esta señal. Para medir de verdad hacen falta ~20
   casos de FECHAS_INCOHERENTES reales y, sobre todo, **reales de más emisores** para confirmar la
   convención inclusiva.

## 7. Nota de honestidad

- El check **no se ajustó para acertar en estos 15 documentos**: la ecuación es la que ya estaba en
  `extract.normalizar_fechas()` y `CLAUDE.md`, sin tolerancias ni umbrales elegidos a posteriori
  (`desfase ≠ 0`, tal cual). Lo que sí se ajustó contra el corpus fueron los **lectores** de la
  tripleta, y se ajustó en la dirección de **abstenerse**: 4 lecturas erróneas eliminadas (§3.2).
- **Un ajuste sí añadió un acierto y hay que decirlo:** en la primera corrida `F04` salía `NO_APLICA`
  porque el lector de meses exigía límite de palabra y el OCR pega la preposición al mes
  (`DESEPTIEMBRE`, `DEJULIO`). Al admitir `(?:DE)?` delante del mes, `F04` pasó a detectarse. No es
  un parche para ese documento: el mismo pegado ocurre en `R07` y `R16`, **ambos reales**, y tras el
  arreglo `R07` quedó `COHERENTE` y `R16` quedó `NO_APLICA` — es decir, la corrección amplía la
  cobertura del formato Sura sin introducir marcas nuevas sobre reales. Con todo, el que la única
  detección propia de la familia dependa de un arreglo de lectura muestra lo frágil que es la
  medición con n=1.
- La única pieza con riesgo real de memorización es el ensamblador de **fechas escritas tipo Sura**
  (`_fechas_escritas`): el emparejamiento por posición de día/mes/año está calibrado sobre 3
  documentos de ese formato. Mitigación implementada: se exige que el **día de la semana impreso
  valide** el ensamblado y, si no valida, la sonda se abstiene. Aun así, con otro formato de EPS
  puede fallar y habría que revalidarlo.
- `n = 1` para la señal propia de la familia. "1/1 detectada" y "0/14 falsos positivos" son números
  reales pero de muestra minúscula: **no son una precisión estimada**, son un no-desmentido.
