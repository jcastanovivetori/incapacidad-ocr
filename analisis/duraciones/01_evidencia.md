# Duraciones en números y en letras — evidencia del corpus real

**Objetivo del trabajo:** el sistema debe entender la duración escrita en NÚMEROS ("2"), en LETRAS
("DOS") y en las dos formas a la vez ("DOS (2)"). Este documento es la **fase de evidencia**: qué
formas existen DE VERDAD en los documentos, cómo las degrada el OCR y qué construcciones parecen una
duración pero no lo son. **No se ha tocado código todavía.**

## Alcance y método

| | |
|---|---|
| Textos OCR revisados | `dataset-falsedad/ocr/{falsas,falsa}/*.txt` + `{reales,real}/*.txt` = **31 archivos**, de los cuales **29 son textos distintos** (dos pares son byte-idénticos, ver abajo) |
| Capa de texto de los PDF originales | 13 de 28 PDF de `dataset-falsedad/docs/` traen capa de texto; se extrajo con **PDFium (`get_textpage`), sin OCR** — sirve para separar "así lo escribe el documento" de "así lo rompió el OCR" |
| `Ejemplos/` (8 documentos) | solo `Incapacidad (19)_unlocked.pdf` tiene capa de texto (se leyó); los otros 7 son escaneos. **No se les corrió OCR** (hay otra medición de rendimiento en esta máquina). Sus días se toman del ground-truth de `tests/test_ejemplos_reales.py`: 30, 3, 30, 2, 5, 15, 3, 3 |
| Baseline | se corrió `RuleBasedExtractor` sobre los 31 `.txt` cacheados (sin OCR) para ver qué días lee HOY |
| No ejecutado | el camino LLM (Ollama no está levantado en esta máquina). Todo lo relativo al LLM queda por inspección |

**Duplicados detectados** (mismo documento en las dos etiquetas, texto byte-idéntico):
`falsa/FALSA-03.txt` == `reales/REAL-15.txt` ·
`falsa/FALSA-11.txt` == `reales/REAL-01.txt`.

> Los recortes de texto de este informe van **sin nombres, cédulas ni diagnósticos** (Ley 1581). Los
> documentos se identifican por **nombre de archivo**, como pide el protocolo del proyecto.

---

## 1. Tabla de patrones

### A. Solo NÚMERO (10 formas)

| # | Patrón | Ejemplo real (recortado) | Archivos |
|---|---|---|---|
| A1 | `Dias de Incapacidad: <N>` (formato SYSNET/ESE) | `Dias de Incapacidad: 1` | `falsas/FALSA-01.txt` |
| A2 | `Dias:<N>` sin espacio | `Dias:3` | `reales/REAL-14.txt` |
| A3 | `Dias de Incapacidad: <N> Dias` (unidad **repetida** después del valor) | `Dias de Incapacidad: 2 Dias` | `reales/REAL-11.txt`, `reales/REAL-10.txt` |
| A4 | `DURACION:` + valor en la **línea siguiente** | `DURACION:`⏎`126` | `reales/REAL-09.txt` ← **máximo observado** |
| A5 | prosa `POR <N> DIAS DESDE EL <fecha> HASTA EL <fecha>` | `SE DA INCAPACIDAD MEDICA POR 4 DIAS DESDE EL 29-07-26 HASTA EL 01/07/29` | `falsa/FALSA-03.txt` == `reales/REAL-15.txt` |
| A6 | igual que A5 pero **todo pegado** | `SEGENERAINCAPACIDADMEDICAPOR1DIAAPARTIRDE18/05/2026HASTA18/05/2026` | `falsas/FALSA-02.txt` |
| A7 | `Descripcion: INCAPACIDAD POR <N> DIAS.` (línea redundante con el campo `Dias:`) | `Descripcion: INCAPACIDAD POR 2 DIAS.` · `DeSCripcIOn:INCAPACIDADMEDICADE2DIAS` | `falsas/FALSA-05.txt`, `…15.09.2025.txt`, `…31.10.2025.txt`, `falsa/…20.04.2026.txt` (`POR 1 DIA.`) |
| A8 | número **ANTES** del rótulo, con el rótulo degradado | `Dias de Incapacldad:` … (líneas más abajo) `3Dian` | `real/REAL-12.txt` |
| A9 | `<N> DIAS` como línea suelta redundante | `30 DIAS` (además de `DIAS: 30 (TREINTA)`) | `reales/REAL-13.txt` |
| A10 | rótulo presente y **valor perdido** por el OCR | `Dias de Incapacidad:` · `Dias Incapacidad` · `No.Total dias:` · `DIASDEINCAPACIDAD` (sin valor) | `real/CED-08`, `reales/CED-03`, `reales/CED-11`, `reales/CED-02`, `falsas/…<NOMBRE>…052122025`, `…12082026`, `real/CED-25` |

Con `POR5 DIAS` (pegado, sin espacio) también aparece en la capa de texto de
`docs/falsas/FALSA-15.pdf`.

### B. Solo LETRA (1 forma, y es un artefacto)

| # | Patrón | Ejemplo real | Archivos |
|---|---|---|---|
| B1 | el dígito de `NN - PALABRA` se pierde y sobrevive **solo la palabra** | línea `-DOS` inmediatamente **antes** de la línea `Duracion` (capa de texto del PDF: `f- DOS`) | `falsas/FALSA-04.txt` |

**No existe en el corpus ningún documento que escriba la duración únicamente en letras por diseño.**
El único "solo letra" es este, y es el formato Sura `NN - PALABRA` (ver C4) al que el OCR le comió el
número. Es decir: **la letra es la red de seguridad cuando el número se pierde** — ése es el valor
real de leer letras, más que un formato nuevo.

### C. LETRA y NÚMERO juntos (6 formas)

| # | Patrón | Ejemplo real (recortado) | Archivos |
|---|---|---|---|
| C1 | `Dias: <N> (<PALABRA> DIA/DIAS)` — nº primero, palabra **+ unidad** en paréntesis | `Dias: 2 (DOS DIAS)` · `Dias: 1 (UN DIA)` · `DiaS:2(DOSDIAS)` (pegado) | `falsas/FALSA-05.txt`, `…15.09.2025.txt`, `…31.10.2025.txt`, `falsa/…20.04.2026.txt` |
| C2 | `Dias de incapacidad: 0<N> <palabra> dia(s)` — **cero a la izquierda** + palabra en **minúscula** + unidad `dia(s)` | `Dias de incapacidad: 02 dos dia(s)` · `Dias de incapacidad:02dosdia(s)` | `falsas/FALSA-10.txt`, `…05062026.txt` |
| C3 | `DIAS: <N> (<PALABRA>)` — palabra **sola** en paréntesis, sin unidad | `DIAS: 30 (TREINTA)` · `1 DIAS: 30 (TREINTA) DESDE: 25/05/2026 HASTA: 23/06/2026` | `reales/REAL-13.txt` · `Ejemplos/Incapacidad (19)_unlocked.pdf` (capa de texto) |
| C4 | `Duracion  <N> - <PALABRA>` — número, guion, palabra | OCR: `Duracion`⏎`14- CATORCE` · PDF: `Duración 14 - CATORCE` | `reales/REAL-07.txt` |
| C5 | **`<PALABRA> (0<N>)`** — la **PALABRA VA PRIMERO** y el número entre paréntesis con cero a la izquierda | `DIASDEINCAPACIDAD`⏎`DOS (02)` | `falsas/FALSA-14.txt` |
| C6 | número y palabra en **líneas distintas** | `Dias de Incapacidad:  2`⏎`DOS` (nótese el doble espacio) | `reales/REAL-01.txt` == `falsa/FALSA-11.txt` |

**C5 es la forma que el cliente describe como "DOS (2)" y es exactamente la que el parser actual NO
lee** (el patrón vigente exige que el dígito vaya *antes* de la palabra).

---

## 2. Numerales en palabras que aparecen DE VERDAD

Búsqueda con límite de palabra **y** tolerante a pegado y a confusiones OCR (`0↔O`, `1↔l/I`, `5↔S`)
sobre los 31 textos. Resultado completo:

| Palabra | Nº de docs | Como DURACIÓN | Dónde |
|---|---|---|---|
| `UN` | 1 | **sí** | `Dias: 1 (UN DIA)` |
| `DOS` / `dos` | 7 textos (6 distintos) | **sí** | C1, C2, C5, C6, B1 |
| `CATORCE` | 1 | **sí** | `14- CATORCE` (licencia de maternidad) |
| `TREINTA` | 1 (+1 en `Ejemplos/`) | **sí** | `DIAS: 30 (TREINTA)` |
| `tres` | 1 | **NO** | pegado en la cita del síntoma que reporta el paciente (`…hacetresdias`) → falso positivo #1 |
| `Uno` / `Una` / `una` / `un` | varios | **NO** | cantidades de insumos `1 (Uno)` / `1 (Una)` y artículos indefinidos de la prosa legal |

**Lo que NO aparece:** ningún numeral compuesto. Cero apariciones de `veintiuno`, `veintidos`,
`treinta y cinco`, `ciento veinte`, `cuarenta`, `cincuenta`, `noventa`, `mil` (como cantidad de días),
ni de `once`…`trece`, `quince`, `dieciséis`…`diecinueve`, `veinte`.

**Consecuencia de diseño:** las duraciones LARGAS se escriben **solo en dígitos**. El máximo del
corpus, 126 días (licencia de maternidad), aparece como `DURACION:`⏎`126`, sin palabra. Las palabras
solo acompañan a números **cortos** (1, 2, 14, 30).

## 3. Rango de días observado

**Mínimo 1 · Máximo 126.** Distribución (29 textos distintos + los 8 de `Ejemplos/`):

| Días | Documentos |
|---|---|
| 1 | 5 (`Dias de Incapacidad: 1`, `POR 1 DIA`, `1 (UN DIA)`, y dos donde inicio == fin) |
| 2 | 11 ← **la masa** |
| 3 | 4 (uno de ellos con la palabra `DOS` contradiciendo las fechas) |
| 4 | 1 |
| 5 | 2 (uno en `Ejemplos/`) |
| 14 | 1 (maternidad, parto no viable) |
| 15 | 1 (`Ejemplos/`) |
| 30 | 3 (1 real + 2 en `Ejemplos/`) |
| 126 | 1 (licencia de maternidad) |

**≈70 % del corpus está entre 1 y 3 días.** La regla del repo (`dias` válido = **1..540**) sigue
siendo la correcta y no hay que tocarla; pero el parser de letras solo necesita ser *bueno* en 1..30
y *correcto* hasta 540. Cubrir hasta 540 exige soportar `CIENTO…` y `QUINIENTOS…` aunque en este
corpus no aparezcan — cubrirlos es gratis y consistente con la regla; **no** es la parte que
determina la precisión.

---

## 4. Trampas del OCR (casos reales, no hipótesis)

1. **Palabras pegadas sin espacios** — `DiaS:2(DOSDIAS)`, `Dias de incapacidad:02dosdia(s)`,
   `SEGENERAINCAPACIDADMEDICAPOR1DIAAPARTIRDE18/05/2026HASTA18/05/2026`, `DIASDEINCAPACIDAD`,
   `DeSCripcIOn:INCAPACIDADMEDICADE2DIAS`, `hacetresdias`, `POR5 DIAS`.
   **Ojo:** `02dosdía(s)` ya viene pegado **en la capa de texto del PDF original**
   (`docs/falsas/FALSA-10.pdf`) → no todo lo pegado es culpa del OCR;
   ese formato lo emite así.
2. **`DIAS` sin tilde en TODO el texto OCR.** La tilde solo sobrevive en las capas de texto de los PDF
   (`Días de Incapacidad`, `Día`, `Duración`). Además el nombre de archivo
   `INC <NOMBRE> … 3 DÍAS 02.09.2025` sí trae tilde y **se rompe en cp1252** (aparece como `3 D?AS` en
   `ground_truth.json`) → el parser tiene que aceptar `DIAS`, `DÍAS`, `Días`, `DiaS`, `dia(s)`.
3. **Cero a la izquierda en el número de días** — `02 dos dia(s)`, `DOS (02)`. (También en códigos:
   `01-Consulta externa`, `01:Intramural`.)
4. **El dígito de la duración desaparece por completo y solo queda la palabra** — `-DOS`
   (`falsas/INC <NOMBRE>…02.09.2025.txt`), sobre el formato Sura `NN - PALABRA`.
5. **Rótulo degradado** — `Dias de Incapacldad:` (`l` por `i`), `3Dian` (`s`→`n`), `DiaS:`,
   `DeSCripcIOn:`, `Dianostico:`, `Observacion dNe Incapacidad`.
6. **Rótulo `Duracion` pegado al valor del campo vecino** — `VIERNES 10 DEJULIODuracion`
   (`reales/CED-12`), `MARTES 09 DE/JUNIO Duracion` (`real/CED-25`).
7. **`0`→`p` / `0`→`O` / `10`→`1O`** — `p2` por `02` en la casilla MES
   (`falsas/…<NOMBRE>…25022026.txt`), `O1-SEDEPRINCIPAL`, `DIAGNOSTICOCIE1O`, `H1O2O`, `Aoo` por
   `A00`, `RO7L`.
8. **Orden de lectura roto (formularios de tabla).** En el formato Sura el valor sale en la línea
   **anterior** al rótulo (`-DOS` antes de `Duracion`) o **después de otro campo**
   (`14- CATORCE` aparece tras `Fecha Fin`). En la rejilla Sofisis el valor de `DIASDEINCAPACIDAD`
   queda en la línea siguiente… o se pierde (2 de 3 documentos de ese formato).
9. **Un `1` de índice de fila pegado delante del rótulo** — `1 DIAS: 30 (TREINTA)`
   (`Ejemplos/Incapacidad (19)_unlocked.pdf`).
10. **Doble espacio tras los dos puntos** — `Dias de Incapacidad:  2`.
11. **Documentos donde el bloque de días se pierde casi entero** — `real/REAL-16.txt`
    llega con el layout totalmente desordenado y la palabra `SUR` repetida 10 veces; `Duracion` queda
    sin ningún valor cerca.

---

## 5. Falsos positivos a evitar (la parte crítica)

Cada uno con su caso real. Los marcados **[FALLA HOY]** los reproduce el `RuleBasedExtractor` actual.

| # | Falso positivo | Ejemplo real | Archivo | Valor correcto |
|---|---|---|---|---|
| 1 | **Duración de los síntomas que cuenta el PACIENTE, en palabras + `dias`** — es literalmente `<palabra> dias` y es el más peligroso para un parser de letras | `…desdo hacetresdias'.` (campo "Causa que motiva la atencion") | `reales/REAL-02.txt` | 2 días (10/06→11/06) |
| 2 | **Edad del paciente con `dia(s)`** | `Edad: 33 Ano(s), 1 mes(es), 8 dia(s)` · `Edad:31 ano(s), 3 mes(es), 22 dia(s)` · (PDF) `31 año(s), 1 mes(es), 26 días` | `falsas/…<NOMBRE>…16072026.txt`, `reales/REAL-15.txt` | 1 y 4 días |
| 3 | **Cantidad de insumo/medicamento en formato `N (Palabra)`** — sintaxis idéntica a C1/C3 | `1 (Una)` y `1 (Uno)` en la tabla de insumos | `reales/REAL-10.txt` | 2 días |
| 4 | **Vigencia de la dosis** — dice "1 dia" y no es la incapacidad | `Vig: 1 dia` | `reales/REAL-10.txt` | 2 días |
| 5 | **[FALLA HOY]** el **día del mes** que sigue al rótulo de días | `POR 4 DIAS DESDE EL 29-07-26 …` → el extractor devuelve **29** | `falsa/FALSA-03.txt` y `reales/REAL-15.txt` | 4 |
| 6 | **[FALLA HOY]** el **AÑO** leído como duración | `MARTES 09 DE/JUNIO Duracion`⏎`DE2026` → el extractor devuelve **202** | `real/REAL-16.txt` | 1 (inicio == fin) |
| 7 | la **rejilla `DIA / MES / ANO`** que sigue al rótulo de días | `DIASDEINCAPACIDAD`⏎`APARTIRDELAFECHA`⏎`VIGENCIAS`⏎`DIA`⏎`MES`⏎`ANO`⏎`FECHA DEINICIO`⏎`12`⏎`08`⏎`2026` | `falsas/…<NOMBRE>…12082026.txt`, `…052122025.txt` | 1 (12/08→12/08). **Hoy NO falla** solo porque el patrón de días prohíbe `\n`: **no relajar eso** |
| 8 | el **número de sección** pegado a `DURACION` | `3.DURACIONDELPERMISO` | `reales/REAL-05.txt`, `real/REAL-08.txt` | no es duración |
| 9 | **horas, no días** | `NUMERO TOTAL DE HORAS` / `4 irs`, `1:10 (m`, `5: 202m` · `CUADRO CLINICO DE 3 HORAS DE EVOLUCION` · `CADA 8 HORAS` | `reales/REAL-05.txt` · `reales/REAL-10.txt` | — |
| 10 | **semanas de gestación** | `EDADGESTASIONAL:`⏎`40.00 Semanas` · (PDF) `Edad gestacional en semanas 0` | `reales/REAL-09.txt`, `reales/REAL-07.txt` | 126 y 14 |
| 11 | **números de trámite / consecutivo / prestador / orden** | `IncapacidadN:362.355` · `Consecutivo:`⏎`0081523489` · `LICENCIA Nro. 0C41474361` · `INC15247` · `Codigo REPS`⏎`685470367113` · `Nro Orden:`⏎`9304040` · `INCAPACIDADMEDICA#146012` | varios | — |
| 12 | **régimen / nivel / grupo de servicio / paginación** | `Regimen: 1 - Contributivo` · `Nivel: 1` · `01-Consulta externa` · `Tipo de Usuario:COTIZANTE NIVEL1` · `Pagina 1 de 1` · `DX Relacionado 1:` | varios | — |
| 13 | **signos vitales** | `F. Cardiaca:`…`80`, `113`, `Peso:`…`95`, `Sat.Oxigeno:`…`98`, `glasgow 15/15` | `reales/REAL-10.txt` | — |
| 14 | **`un`/`uno`/`una` como ARTÍCULO en la prosa legal** — un diccionario de numerales que los incluya sin exigir la unidad "día(s)" cerca dispara aquí | `…salvo que se trate de una fuerza mayor…` · `…debera tener una cuenta bancaria inscrita…` | `reales/REAL-05.txt`, `real/REAL-08.txt`, `reales/REAL-07.txt`, `reales/REAL-03.txt` | — |
| 15 | **edad en años** | `Edad:22Anas` · `24 anos 05 meses` · `Rango de edad: 25-34` · `22 Anos` | varios | — |
| 16 | **CIE-10 con dígitos** | `M545`, `R505`, `A099`, `S09.9`, `T67.0`, `H1O2O`, `S52O` | varios | — |
| 17 | **VACACIONES** (regla ya escrita en `CLAUDE.md` §VACACIONES): fechas en prosa con el número en paréntesis. `el día siete (07) de julio` es un **día del mes**; `dos mil veintiseis (2026)` es el **AÑO en palabras** | (sintético) `a partir del primero (01) de julio de dos mil veintiseis (2026)` / `hasta el quince (15) de julio…` | **NO hay ninguna carta de vacaciones real en este corpus**; el único texto disponible es el sintético de `incapacidad-ocr/scripts/sembrar_demo.py` | los días se calculan **siempre** por diferencia de fechas |

### Nota sobre el #17

La regla del repo —*"los días NO se buscan por etiqueta en el formato de vacaciones; se calculan
siempre por diferencia de fechas"*— **no se puede validar contra documentos reales porque no hay
ninguno en el corpus**. Se conserva tal cual: es la única evidencia disponible y el riesgo que
describe (`el día siete (07) de julio` → 7 días) es exactamente la forma C5/C3 invertida, así que
**añadir soporte de letras aumenta el riesgo en ese formato, no lo reduce**. El parser de letras debe
seguir desactivado para `tipo_documento == "vacaciones"`.

---

## 6. Discrepancias letra ↔ número

**Dentro de un mismo campo: NINGUNA.** Las 6 formas mixtas del corpus coinciden siempre —
`1 (UN DIA)`, `2 (DOS DIAS)`, `02 dos`, `30 (TREINTA)`, `14 - CATORCE`, `DOS (02)`, `2`⏎`DOS`.
No aparece nada como "TRES (2)". Con 29 textos distintos el corpus es demasiado pequeño para concluir
que no ocurre; conviene **instrumentarlo** (registrar el desacuerdo como aviso) aunque no se haya
visto todavía.

**Lo que SÍ aparece — y en los tres casos el documento está etiquetado como ADULTERADO — es el
desacuerdo entre la duración (en palabra o dígito) y el RANGO DE FECHAS:**

1. `falsas/FALSA-04.txt` — **el caso oro.**
   `Duracion` = `-DOS` (sobrevive solo la **palabra**, el dígito lo perdió el OCR) frente a
   `Fecha Inicio MARTES 02 DE SEPTIEMBRE` → `Fecha Fin JUEVES 04 DE SEPTIEMBRE` = **3 días**. El
   propio nombre del archivo dice "3 DÍAS", y `ground_truth.json` lo marca `FECHAS_INCOHERENTES` con
   motivo *"ALTERACION EN FECHA DE INICIO, DURACION Y FECHA FIN, LOS DIAS NO CORRESPONDEN A LA FECHA
   DE FINALIZACION CALCULADA"*. Es decir: **leer la palabra es lo único que permite detectar este
   fraude**, porque el número no está.
2. `falsas/FALSA-09.txt` — `Dias de incapacidad:02dosdia(s)`
   (el 02 y el "dos" concuerdan entre sí) frente a `Desde:05/06/2026-Hasta:06/07/2026` = **32 días**.
   Su gemelo `…09062026.txt` trae `Desde: 09/06/2026 -Hasta: 10/06/2026` = 2 días, coherente.
3. `falsa/FALSA-03.txt` (== `reales/REAL-15.txt`) —
   `POR 4 DIAS DESDE EL 29-07-26 HASTA EL 01/07/29` (fecha fin imposible) y la **capa de texto del PDF
   trae además una segunda página** con `POR 5 DIAS DESDE 09-06-26 HASTA EL 13-06-26`: **dos
   duraciones distintas en el mismo PDF**.

**Conclusión operativa:** la señal de adulteración soportada por evidencia es
**duración (dígito o palabra) vs. rango de fechas**, no palabra vs. dígito. El aviso palabra-vs-dígito
vale la pena implementarlo, pero como instrumentación, sin esperar que dispare en este corpus.

---

## 7. Baseline: qué lee HOY el `RuleBasedExtractor`

Corrido sobre los 31 `.txt` cacheados (sin OCR). Solo se listan los casos relevantes a duraciones:

| Archivo | `dias` que devuelve hoy | Correcto | Diagnóstico |
|---|---|---|---|
| `falsa/FALSA-03.txt` | **29** | 4 | FP #5: se come el día del mes de `DESDE EL 29-07-26` |
| `reales/REAL-15.txt` | **29** | 4 | idem (mismo texto) |
| `real/REAL-16.txt` | **202** | 1 | FP #6: `Duracion`⏎`DE2026` → `\d{1,3}` sobre "2026" |
| `falsas/…<NOMBRE>…25022026.txt` | **None** | 2 | forma **C5** `DOS (02)` no soportada (palabra antes del número) |
| `falsas/…<NOMBRE>…12082026.txt` | None | 1 | valor del formulario perdido por el OCR; fechas tampoco se leen |
| `falsas/…<NOMBRE>…052122025.txt` | None | ? | idem |
| `falsas/INC <NOMBRE>…02.09.2025.txt` | None | ver §6 | forma **B1** (`-DOS`, solo letra) no soportada |
| `falsas/INC <NOMBRE>…18.05.2026.txt` | None | 1 | forma **A6** (`…POR1DIA…` todo pegado) no soportada |
| `real/REAL-04.txt` | None | 2 | rótulo sin valor + fechas mal ancladas |
| `reales/REAL-03.txt` | None | 2 | rótulo `Dias Incapacidad` sin valor |
| `reales/REAL-02.txt` | None | 2 | idem |
| `reales/REAL-05.txt` | None | — | permiso por horas, sin días |
| resto (19 textos) | correcto | | C1, C2, C3, C4, C6, A1–A4, A9 ya funcionan |

Formas mixtas que **ya** funcionan hoy (por el dígito, no por la palabra): C1, C2, C3, C4, C6.
Formas que **faltan**: **C5** (`DOS (02)`), **B1** (`-DOS`), **A6** (`…POR1DIA…` pegado),
**A7** en solitario (`INCAPACIDAD POR 2 DIAS.` cuando es la única mención), **A8** (`3Dian`).
Y dos falsos positivos activos que hay que cerrar: **#5** (día del mes) y **#6** (año).

---

## 8. Qué NO se pudo verificar

- **Camino LLM (Ollama `gemma3:4b`)**: no está levantado en esta máquina (ni Docker, falta elevación
  UAC). Todo lo relativo a `OllamaLLMExtractor`/`HybridExtractor` y al prompt queda **por
  inspección**; validar con pruebas que simulen la respuesta del LLM (precedente: `StubOCR` en
  `ocr.py`).
- **OCR de los 7 escaneos de `Ejemplos/`**: no se ejecutó (otra medición de rendimiento corriendo).
  Sus duraciones (2, 3, 3, 5, 15, 30, 30) vienen del ground-truth de `tests/test_ejemplos_reales.py`;
  solo se leyó la capa de texto del único PDF que la tenía.
- **Cartas de VACACIONES reales**: no existe ninguna en el corpus (ver §5 nota #17).
