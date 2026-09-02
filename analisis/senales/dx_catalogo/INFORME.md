# Familia `dx_catalogo` — Diagnóstico contra catálogo CIE-10

Sonda: `senales/dx_catalogo/probe.py` · Salida cruda: `salida.txt` · Detalle por documento: `resultados.json`
Corpus: 31 documentos (15 Falsas + 16 Reales) · Motor: 100% local (stdlib de Python; el OCR ya venía hecho con RapidOCR).

Cubre las señales `DX_INEXISTENTE`, `DX_FORMATO` y `DX_NOMBRE_DISTINTO` de la taxonomía del
`ground_truth.json`. **Solo `DX_FORMATO` es autónomo hoy**; los otros dos dependen del catálogo
real `lpdiagnosticos` (ASTGU), que no está en esta máquina.

---

## 1. La convención de código que asume toda la familia

El cliente anotó en su tabla de motivos: *"TODOS LOS DX SON DE 4 CARACTERES"*. Eso coincide con la
tabla CIE-10 que MinSalud/SISPRO distribuye en Colombia y que es la que se carga en `lpdiagnosticos`:

```
letra + 2 dígitos + 1 carácter          J06.9 -> J069
donde el 4º carácter es un dígito, o la letra 'X' de relleno cuando la
categoría no se subdivide:              N23   -> N23X      R51 -> R51X      A09 -> A09X
```

Consecuencia operativa, y es el eje de todo el informe: **`N23X` es válido (4 caracteres) y `N23`
no lo es**. Un check que no entienda la `X` de relleno convierte documentos legítimos en falsos.

### Hallazgo sobre el código del repo (no lo modifiqué, solo lo verifiqué)

`incapacidad_ocr.extract._normalize_cie10` **rechaza la `X` de relleno** y
`_extract_cie10` **la descarta silenciosamente**:

```
_normalize_cie10('N23X') -> (None, 99)      _normalize_cie10('A09X') -> (None, 99)
_extract_cie10('Dianostico:\nN23X: COLICO...') -> 'N23'      (perdió la X)
_extract_cie10('Diagnostico Ppal: R51X')       -> 'R51'      (perdió la X)
_extract_cie10('...incapacidad: Aoo Intoxicacion...') -> None (exige ≥1 dígito real)
```

Como `erp.Lookups.diagnostico_por_codigo` compara `REPLACE(codigo,'.','') = 'N23'` contra un catálogo
que guarda `N23X`, **el ERP hoy diría "Diagnóstico N23 no está en el catálogo CIE-10" para un
documento perfectamente legítimo**. En este corpus eso pasaría con 2 documentos (`N23X` y `R51X`).
Por eso la sonda **no usa** `incapacidad.diagnostico.cie10`: relee el código del `texto_plano` con su
propio localizador anclado a la etiqueta. Recomendación para una fase posterior (fuera del alcance de
esta tarea): aceptar `[0-9X]` en la 4ª posición y conservarla, y/o que el lookup pruebe `codigo` y
`codigo+'X'`.

---

## 2. Los checks

| id | qué afirma | determinista | autónomo hoy | severidad sugerida |
|---|---|---|---|---|
| `DX_FORMATO_LONGITUD` | el código impreso no tiene los 4 caracteres del catálogo | sí | **sí** | AVISO |
| `DX_INEXISTENTE` | el código no existe en `lpdiagnosticos` | sí | **no** (falta catálogo) | ALERTA (cuando exista) |
| `DX_NOMBRE_DISTINTO` | la descripción impresa no es la del catálogo para ese código | no (heurístico) | **no** (falta catálogo) | AVISO (cuando exista) |
| `DX_NO_LEIDO` | no se pudo aislar un código legible → *no verificable* | sí | sí | no acusa |
| `DX_AUSENTE_EN_DOC` | el propio papel imprime "NO REGISTRA" en el campo de DX | sí | sí | AVISO |
| `DX_SIN_PRINCIPAL` | hay etiqueta de DX secundario pero ningún DX principal legible | no (heurístico) | sí | AVISO (experimental) |
| `DX_CAPITULO_INCOHERENTE` | la descripción pertenece a otro capítulo CIE-10 que la letra del código | no (heurístico) | sí | AVISO (experimental) |

### Paso 0 (común): localizar el código tal como está IMPRESO

Todo lo demás depende de esto, así que va explícito. Solo `re` de la stdlib, sobre
`ocr/<etiqueta>/<doc>.json → texto_plano` (RapidOCR, ya generado).

1. **Anclas de diagnóstico**, tolerantes al OCR: `d[i1lí]a?g?n.{0,1}st[i1l]c` (cubre
   `Diagnostico`, `Dlagnostico`, `Dianostico`, `Diagndstico` — las cuatro variantes salen en este
   corpus), `(?<![A-Za-z])dx` (para `DXPrincipal:`, pegado) y `c[i1l]e\s*-?\s*1[o0]` (`CIE 10`, `CIE1O`).
   Cada ancla recibe **peso**: 0 si la cola dice `relacionad|secundari|\brel\b|otros diagn`, 2 si dice
   `principal|ppal|princ|genera la incapacidad|ingreso|egreso`, 1 en otro caso. Se evalúa primero lo
   secundario para que `DX Rel Ingreso` no se cuele como principal.
2. **Fin efectivo de la etiqueta** = hasta los `:` de la misma línea (`Diagnostico que genera la
   incapacidad:` cuenta como una sola etiqueta), si no, fin del ancla.
3. **Candidatos a código**: `(?<![A-Za-z0-9])([A-Za-z])[ ]?([0-9OoIiLlZzSs|]{2})`. El lookbehind evita
   partir cédulas (`C.CCED-06` ya no produce `C101`). Los 2 caracteres del medio se normalizan a
   dígitos con el mismo mapa de confusiones OCR del repo (`O→0, I/L/|→1, Z→2, S→5`) y se cuenta cuántas
   correcciones hubo (calidad de lectura).
4. **4º carácter, resuelto mirando el texto y no con el regex** (esto importa mucho):
   dígito real → es el 4º; `X`/`x` → relleno del catálogo → cuenta como 4º; letra confundible
   (`O I L Z S |`) → solo si el código **termina ahí** (el carácter siguiente no es letra). Así
   `"G43 DOLOR..."` se lee `G43` (3 caracteres, correcto) y no `G430`, y `"H1O2OTRASCONJUNTIVITIS"`
   se lee `H102` y no `H1020`.
5. **Guardas**: se descarta el candidato si justo después viene otro dígito (era un número largo) o si
   sigue el patrón letra+dígito de un serial/fecha compacta (`D22M01A2006`, que aparece en un real).
   Un candidato **sin ningún dígito real** (`Aoo`, `COLS`) solo se acepta si está pegado a la etiqueta
   (≤14 caracteres): la confusión `0↔O` es universal en OCR, pero fuera de la etiqueta produce basura.
6. **Puntaje** `(peso_ancla, pegado_a_etiqueta, −correcciones_OCR, −distancia)`; gana el máximo.
   Ventana: 70 caracteres antes del ancla (las tablas imprimen el valor **antes** del rótulo: en un
   real el código aparece 38 caracteres antes de `Diagnostico Ppal`) y 95 después.
7. **Descripción impresa**: (a) resto de la línea después del código; si no hay, (b) la línea siguiente
   *solo si no parece otro campo etiquetado* (sin `:` en los primeros 25 caracteres ni palabra de
   rótulo); si no, (c) lo que hay antes del código en la misma línea (hay un formato que imprime
   `Sindrome febril en estudio r509`).

Resultado en el corpus: **25 de 28 documentos aplicables con código legible** (18 con descripción).
Los 3 restantes salen como `DX_NO_LEIDO`, que es un *no verificable*, nunca una acusación.

### `DX_FORMATO_LONGITUD` — determinista, autónomo

Afirma: *el código impreso no tiene la longitud que exige el catálogo del ERP (4 caracteres)*.
Cálculo: longitud del código reconstruido en el paso 0 (contando la `X` de relleno como carácter).
`==4` → ok; `==3` → dispara, con el detalle de qué se esperaba (`A09` → `A09X` o `A090..A099`);
otra longitud → dispara como "longitud inesperada"; sin código legible → `no_verificable`.
No necesita ningún dato externo. **No afirma que el código no exista**, solo que no puede existir
tal como está impreso.

### `DX_INEXISTENTE` — determinista, requiere catálogo

Afirma: *el código, ya bien formado, no está en `lpdiagnosticos`*.
Cálculo: `codigo.replace('.','')` contra el diccionario del catálogo (comparación sin punto, igual que
`erp.Lookups.diagnostico_por_codigo`). **Sin catálogo devuelve `no_verificable` y punto**: no hay lista
embebida ni "catálogo parcial", porque un catálogo incompleto convierte cualquier código raro pero
válido en una acusación de falsedad. Verificado con un catálogo de juguete de 4 códigos en `/tmp`
(borrado después): la rama funciona y marca inexistente todo lo que no está — exactamente el desastre
que ocurriría con un catálogo parcial.
Dato que falta: ver §6.

### `DX_NOMBRE_DISTINTO` — heurístico, requiere catálogo

Afirma: *la descripción impresa no corresponde a la del catálogo para ese código* (el motivo textual
del cliente: "EL NOMBRE DEL DX NO ES EXACTAMENTE IGUAL").
Cálculo: normalizar ambas descripciones (sin tildes, sin espacios ni signos, MAYÚSCULAS) y comparar con
`difflib.SequenceMatcher.ratio()` (stdlib): `≥0.90` ok · `0.60–0.90` revisar · `<0.60` dispara.
Es heurístico **por el OCR, no por el criterio**: en este corpus el OCR entrega
`GASTROENTERISTIS`, `TRAUMANO ESPECIFICADO DECABEZA`, `COLICORENAL` — un `!=` estricto marcaría casi
todo. Los umbrales son una propuesta a calibrar el día que exista catálogo; hoy no están medidos.

### `DX_CAPITULO_INCOHERENTE` — heurístico, autónomo, EXPERIMENTAL

Afirma: *la descripción impresa pertenece a un capítulo CIE-10 distinto del que indica la letra del
código*. Cálculo: léxico `palabra → letras admisibles` construido a partir de los **títulos oficiales
de los capítulos** CIE-10 (estructura pública, no del texto de este corpus), con multi-capítulo donde
el término cabe en varios (`INTOXICACION → A|T` porque A05 es intoxicación alimentaria y T es
intoxicación por sustancia; `CEFALEA → G|R`). Si ninguna palabra del léxico aparece → `no_verificable`.
Es el único check autónomo que puede detectar una descripción sustituida sin catálogo.

### `DX_NO_LEIDO`, `DX_AUSENTE_EN_DOC`, `DX_SIN_PRINCIPAL` — soporte

- `DX_NO_LEIDO`: no hubo candidato junto a una etiqueta. No acusa; mide calidad del insumo.
- `DX_AUSENTE_EN_DOC`: el papel imprime `NO REGISTRA`/`NO APLICA` junto a la etiqueta de DX. Dispara
  solo si además **no** se leyó ningún código; si hay código, baja a `revisar` porque el OCR mezcla el
  orden de las columnas de las tablas y ese `NO REGISTRA` suele ser del DX secundario (pasa en 2 reales).
- `DX_SIN_PRINCIPAL`: el formato trae rótulo de DX relacionado/secundario pero ningún código principal
  legible. Sugiere campo borrado, pero también se dispara con un escaneo malo (ver §4).

Exclusiones: `permiso`, `vacaciones` e `historia` no llevan diagnóstico (misma regla que `erp.py`), se
resuelven por el sufijo `_TIPODOC` del nombre y por `tipo_documento` del extractor → `no_aplica`.

---

## 3. La medición

**Cuarentena excluida** (5 documentos, por `manifest.csv`): `INC <NOMBRE> <NOMBRE> ... 29072026.pdf` y
`REAL-15.pdf` (mismo sha256 en ambas clases), `INC <NOMBRE> ... 13.05.2026.pdf` y
`REAL-01.pdf` (mismo sha256 en ambas clases), `FALSA-15.pdf` (misma
cédula, contenido distinto). Quedan **12 falsas + 14 reales = 26**.

### [A] Solo el check determinista y autónomo (`DX_FORMATO_LONGITUD`)

| | |
|---|---|
| Falsas detectadas | **2 / 12** (16,7%) |
| Reales marcadas por error | **0 / 14** (0 falsos positivos) |
| Precisión | 2/2 = 100% **con n=2** (sin valor estadístico) |
| Recall dentro del subconjunto de la familia | **2 / 5** documentos falsos cuyo motivo es un `DX_*` y que no están en cuarentena |

Los 2 detectados: `FALSA-09.jpeg` (imprime un código de 3 caracteres) y
`FALSA-10.pdf` (3 caracteres, leído con 2 correcciones OCR `o→0`).
Ambos son del mismo emisor/plantilla y del mismo paciente: **es un solo caso, contado dos veces**.

### [B] Añadiendo los heurísticos experimentales

| | |
|---|---|
| Falsas detectadas | **4 / 12** |
| Reales marcadas por error | **2 / 14** |

- `+1 falsa` por `DX_CAPITULO_INCOHERENTE`: `FALSA-02.pdf`
  (código de capítulo R con una descripción de capítulo K). Es justo el documento que el cliente marcó
  como "NO EXISTE EL DX R505": el código está bien formado (4 caracteres), así que `DX_FORMATO` no
  puede verlo y solo el catálogo lo cerraría — pero la incoherencia código↔descripción lo delata sin
  catálogo. 1 acierto en 26 documentos = **cero evidencia estadística**, y el resultado depende del
  léxico que escribí.
- `+1 falsa y +2 reales` por `DX_SIN_PRINCIPAL` (ver falsos positivos abajo).

### [C] Lo que hoy NO es evaluable

| check | falsas detectadas | por qué |
|---|---|---|
| `DX_INEXISTENTE` | **0 / 12** | falta `lpdiagnosticos` (ASTGU). `no_verificable` en 31/31 documentos. **No inflo este número**: 3 de las 15 falsas están marcadas por el cliente con "NO EXISTE EL DX ..." y no puedo confirmar ni refutar ninguna. |
| `DX_NOMBRE_DISTINTO` | **0 / 12** | falta `lpdiagnosticos`. `no_verificable` en 31/31. |

### [D] Cobertura de lectura (calidad del insumo, no acusa)

Código legible 25/28 aplicables · con descripción 18/28 · `DX_NO_LEIDO` 3 · `DX_AUSENTE_EN_DOC` 0 (2 en `revisar`).

---

## 4. Falsos positivos concretos y su causa

Con el check determinista `[A]`: **ninguno**. Los que aparecen al activar los experimentales:

| documento (real) | check | causa real |
|---|---|---|
| `REAL-07.pdf` | `DX_SIN_PRINCIPAL` | El PDF imprime el código pero el OCR **perdió la letra inicial** y devolvió `0039`. Sin letra no hay candidato CIE-10 → parece "sin DX principal". Es un fallo de OCR, no una adulteración. |
| `REAL-16.jpeg` | `DX_SIN_PRINCIPAL` | Escaneo (jpeg) de baja calidad: junto a `Diagnostico principal` el OCR no leyó nada. Mismo patrón: ausencia de lectura ≠ ausencia de dato. |

Además, 2 reales quedan en `DX_AUSENTE_EN_DOC = revisar` (no acusa) porque el OCR devuelve las celdas
de la tabla desordenadas y el `NO REGISTRA` del DX secundario cae junto al rótulo del principal
(`REAL-02.pdf`, `REAL-03.pdf`).

Y el falso positivo que **no** cuento porque está en cuarentena, pero es el más importante de todos:
`FALSA-11.pdf` dispara `DX_FORMATO_LONGITUD` (código de 3
caracteres impreso por la IPS)… y es **byte a byte el mismo archivo** que
`Reales/REAL-01.pdf`. El mismo documento es, según las carpetas del cliente,
simultáneamente falso y legítimo, y mi check lo marca en las dos. Si lo contara, la precisión de `[A]`
bajaría a 3/4 = 75% y el mismo documento sería a la vez acierto y error.

---

## 5. El confusor principal de la familia

**La longitud del código es una convención de impresión del EMISOR, no una huella de adulteración.**

- Una EPS/IPS del corpus imprime `Dlagnostico Princlpal: G43` (3 caracteres). El cliente marcó ese
  documento como falso *precisamente* por eso ("NO EXISTE EL DX G43") y a la vez lo tiene archivado en
  Reales, idéntico byte a byte. Es decir: el criterio del analista humano es el mismo que implementa
  este check y **en ese caso no separa**.
- Otra IPS imprime `N23X` (con relleno) y otra `A09` (sin relleno) en la misma familia de códigos.
- Toda la evidencia positiva de la familia en este corpus se reduce a: 2 documentos del mismo emisor y
  el mismo paciente (`A09`/`A00`), más 1 documento etiquetado en las dos clases (`G43`). No hay ni un
  solo caso de código corto que esté corroborado por un segundo motivo independiente.

Confusores secundarios, todos verificados en este corpus:
1. **La `X` de relleno**: `N23X`/`R51X` son válidos; quien la descarte (como hace hoy
   `_normalize_cie10`) genera acusaciones falsas de "código inexistente".
2. **Confusión OCR dígito↔letra** (`Aoo`→`A00`, `N2O0`→`N200`, `RO7L`→`R074`, `H1O2`→`H102`,
   `r509`): sin el mapa de correcciones y sin preferir el candidato con menos correcciones, el código
   leído es otro y cualquier veredicto posterior es ruido.
3. **Pérdida de la letra inicial** (`0039`) y **escaneos ilegibles**: producen "falta el DX" donde el
   dato sí está impreso.
4. **Orden de las celdas en tablas**: el valor aparece antes del rótulo y el `NO REGISTRA` de una
   columna cae junto al rótulo de otra.
5. **El extractor genérico del repo elige otro token**: comparado con la lectura anclada de la sonda,
   `incapacidad.diagnostico.cie10` difiere en 10 de 31 documentos, y en 6 de ellos devuelve algo que no
   es el código impreso junto al rótulo (`IDENTI`, `FECHA`, `C10.1`, `B04.0`, `S19.0`, `Q07.3`).
   Cualquier check de esta familia montado directamente sobre ese campo mediría el error del extractor,
   no la falsedad.

---

## 6. Qué hay que pedir (exacto)

Al equipo de ASTGU / al DBA del ERP:

1. **Export completo de `lpdiagnosticos`**: columnas `idlpdiagnosticos`, `codigo`, `descripcion`, más
   `estado`/`activo` y `fechamodificacion` si existen. CSV UTF-8 con cabecera `codigo,descripcion`,
   depositado en `senales/dx_catalogo/catalogo/lpdiagnosticos.csv` (o apuntado con la variable de
   entorno `DX_CATALOGO`). La sonda ya lo consume tal cual; es un archivo, no una API.
2. **Confirmación de la convención de longitud**:
   `SELECT LENGTH(REPLACE(codigo,'.','')) AS n, COUNT(*) FROM lpdiagnosticos GROUP BY n;` y una muestra
   de códigos terminados en `X`. Si aparecen códigos de 3 caracteres en el catálogo, `DX_FORMATO_LONGITUD`
   deja de tener sentido y hay que retirarlo.
3. **Versión/año de la CIE-10** de la que salieron las descripciones (cambiaron entre las
   actualizaciones de 2010 y 2018): sin eso, `DX_NOMBRE_DISTINTO` no se puede calibrar.
4. **Códigos retirados/inactivos**: ¿existen y cómo se marcan? Un código presente pero retirado es
   "no existe" para el analista y "existe" para un `IN (...)` ingenuo.
5. **Histórico del ERP** (incapacidades ya radicadas con `idlpdiagnosticos`, IPS/EPS emisora y días):
   es lo único que rescataría a `DX_FORMATO` del contraejemplo de §5, porque permite responder "¿esta
   IPS suele imprimir 3 o 4 caracteres?" y convertir el check en "este emisor cambió de convención".
   También habilita el check de días vs diagnóstico, que es de otra familia.
6. Opcional y complementario: la tabla CIE-10 pública de MinSalud/SISPRO como archivo local, para las
   descripciones oficiales. La fuente **autoritativa de existencia** sigue siendo `lpdiagnosticos`,
   porque es la tabla contra la que el ERP hace la FK al radicar.

---

## 7. Severidad recomendada

| check | severidad | justificación |
|---|---|---|
| `DX_FORMATO_LONGITUD` | **AVISO** | Determinista y con 0 falsos positivos medidos, pero el contraejemplo de §5 es demoledor: el mismo archivo está en las dos clases y el check lo marca. Sirve para pedir el código completo a la IPS / anotar en el checklist de radicación, **no** para acusar de fraude. Sube a ALERTA solo si el histórico demuestra que ese emisor imprime normalmente 4 caracteres. |
| `DX_INEXISTENTE` | **ALERTA** (cuando exista catálogo) | Un código bien formado (4 caracteres) que no está en `lpdiagnosticos` no se explica por convención de impresión ni por OCR: alguien escribió un código que no existe. Sigue sin ser BLOQUEA porque bloquea de hecho la radicación en el ERP y porque el catálogo puede estar desactualizado. |
| `DX_NOMBRE_DISTINTO` | **AVISO** | El OCR destroza las descripciones (`GASTROENTERISTIS`); el umbral es una decisión de negocio y no está medido. Como AVISO alimenta la revisión humana con la descripción oficial al lado. |
| `DX_CAPITULO_INCOHERENTE` | **AVISO** (experimental) | 1 acierto y 0 falsos positivos en 26 documentos: prometedor y autónomo, pero sin evidencia. |
| `DX_SIN_PRINCIPAL` | **AVISO** (experimental) | 1 acierto y 2 falsos positivos: mide más la calidad del escaneo que la falsedad. |
| `DX_NO_LEIDO`, `DX_AUSENTE_EN_DOC` | **no acusan** | Son estados de "no verificable"/"documento incompleto"; su sitio es el checklist de radicación (pedir un escaneo legible), no el motor de falsedad. |

**Ningún check de esta familia debería BLOQUEAR por sí solo.** El único que podría hacerlo
(`DX_INEXISTENTE`) todavía no se puede ejecutar, y cuando se pueda seguirá dependiendo de que el
catálogo esté al día.

---

## 8. Nota de honestidad

- No ajusté ningún umbral para acertar en estos 15 documentos. Las dos decisiones que sí tomé mirando
  el corpus están declaradas: (a) aceptar la `X` de relleno como 4º carácter — que **quita**
  detecciones en lugar de añadirlas, y es correcta según la convención del catálogo colombiano; y
  (b) permitir un candidato sin dígitos reales cuando está pegado a la etiqueta (`Aoo`), que es una
  regla de robustez OCR con contexto, no un valor memorizado.
- Ablaciones ejecutadas para cuantificar exactamente cuánto pesa cada decisión (excluyendo cuarentena):

  | variante | falsas detectadas | reales marcadas |
  |---|---|---|
  | sonda tal como se entrega | 2 / 12 | 0 / 14 |
  | sin la relajación (b) (`Aoo` deja de ser código) | 1 / 12 | 0 / 14 |
  | sin tratar la `X` de relleno, como hace hoy el repo | 2 / 12 | **1 / 14** (`REAL-02.pdf`, `R51X` leído `R51`) |
- El léxico de capítulos lo escribí a partir de los títulos oficiales de los capítulos CIE-10, pero lo
  validé contra este corpus: su resultado (1 acierto, 0 falsos positivos) no es extrapolable.
- Con 12 falsas válidas y 2 detecciones que además son el mismo emisor y el mismo paciente, cualquier
  porcentaje de recall de esta familia es anecdótico.
