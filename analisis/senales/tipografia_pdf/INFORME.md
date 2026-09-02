# Familia de señales `tipografia_pdf` — Tipografía y estructura del PDF (texto añadido)

Cubre la señal de la taxonomía **TIPOGRAFIA_MIXTA** (`"VARIOS TIPOS DE LETRAS EN EL
DOCUMENTO"`) y, en general, cualquier rastro estructural de que alguien abrió el PDF y
**añadió, tapó o reemplazó** texto.

- Sonda: `<dataset-falsedad>/senales/tipografia_pdf/probe.py`
- Detalle por documento: `.../senales/tipografia_pdf/resultado.json`
- Scratch de exploración (cómo se miraron las distribuciones antes de fijar umbrales):
  `_explora.py`, `_explora2.py`, `_explora3.py`, `_rasgos.json`
- Todo 100% local: solo `pypdfium2` (la misma librería que usa `incapacidad_ocr.preprocess`)
  y lectura de los bytes crudos del PDF. Cero red, cero IA, cero servicios pagos.

Reproducir:

```bash
<repo>/.venv/Scripts/python.exe \
  <dataset-falsedad>/senales/tipografia_pdf/probe.py --json
```

---

## 1. Hallazgo previo que cambia el diseño de la familia

La premisa de partida era: *"un PDF generado por el sistema de una EPS usa un juego de
fuentes homogéneo; si alguien lo editó, aparecen fuentes nuevas"*. **En este corpus esa
premisa casi no aplica**, y hay que decirlo antes de las métricas:

Partición exacta de los 31 documentos del manifest (cuarentena incluida):

| Cómo llega el documento | nº docs |
|---|---|
| **JPEG suelto** (sin objetos PDF) | 3 |
| **PDF sin capa de texto visible** = escaneo/foto pura | **15** (9 CamScanner/intsig, 2 Word 2021 con el escaneo pegado dentro, 1 EPSON Scan, 1 Quartz iOS, 1 iLovePDF, 1 sin metadatos) |
| PDF con capa de texto: exportación de **Microsoft Word** | 10 |
| PDF con capa de texto **sintetizada por OCR** (Acrobat Mobile Paper Capture + ClearScan) | 1 |
| PDF con capa de texto generado por un **sistema** (iText 2.0.8) | 1 |
| PDF con capa de texto de `Microsoft: Print To PDF` (fuentes anonimizadas) | 1 |

Es decir: **un solo documento del corpus (R21) es un PDF generado por un sistema**. El
flujo real es "el prestador imprime/rellena en Word y exporta" o "el trabajador fotografía
el papel". Por eso la familia se reformula así: no se compara contra "las fuentes del
emisor" (no existe ese catálogo), se compara **la homogeneidad tipográfica interna del
propio documento** y se buscan **artefactos de edición** (parches blancos, texto
semitransparente, texto vectorial estampado sobre un escaneo).

---

## 2. Puertas de aplicabilidad (el confusor, tratado primero)

La sonda declara **NO APLICABLE** (nunca "limpio") cuando la tipografía no se puede juzgar:

| id | Condición | Cómo se calcula | Determinista |
|---|---|---|---|
| `TP_APLICABILIDAD` (a) | contenedor no PDF (jpeg/png) | extensión del manifest | sí |
| `TP_APLICABILIDAD` (b) | **escaneo/foto puro**: ninguna página tiene un objeto de texto que pinte caracteres visibles | `page.get_objects()`; se cuentan los `FPDF_PAGEOBJ_TEXT` con `FPDFTextObj_GetTextRenderMode != INVISIBLE` y `obj.extract()` no vacío | sí |
| `TP_APLICABILIDAD` (c) | **capa de texto sintetizada por OCR**: `Creator`/`Producer` contiene ClearScan / Paper Capture / Tesseract / ABBYY / OCRmyPDF…, o ≥50% de las fuentes se llaman `*Nombre-NNNNN` (patrón con que pdfium bautiza las fuentes que ClearScan fabrica por glifo) | metadatos + nombres de fuente | sí |
| `TP_FAMILIAS_MULTIPLES` / `TP_FUENTE_MINORITARIA` → `NO_EVALUABLE` | el productor **anonimizó** los nombres de fuente (`CIDFont+F1`, familia `z@r2a13.tmp` de *Print To PDF*) | regex sobre nombre base y familia | sí |

Sin la puerta (c) el corpus da una detección espectacular y **falsa**: F03 tiene **48
fuentes distintas** y 427 objetos de texto encima de una imagen de página completa, pero
eso no es adulteración: es ClearScan, que sintetiza una fuente por grupo de glifos al
vectorizar un escaneo. El motivo real de F03 en el ground truth es `FECHAS_INCOHERENTES`.
Contarlo como acierto tipográfico sería inflar la métrica con un acierto por la razón
equivocada.

---

## 3. Los checks

### Votan el veredicto

#### `TP_FAMILIAS_MULTIPLES`
- **Afirma:** el documento está compuesto con más de una familia tipográfica ⇒ el texto no
  salió todo del mismo generador/tecleado.
- **Cómo se calcula:** con `pypdfium2`, para cada objeto de texto que pinta caracteres
  visibles: `obj.get_font()` → `get_base_name()`, `get_family_name()`, `is_embedded`.
  Se normaliza la familia: se quita el tag de subset (`ACWIYO+`), el sufijo de estilo
  (`-BoldMT`, `,Bold`, `PSMT`, `-Roman`…) y el sufijo de instancia (`-12358`), y se pasa a
  minúsculas sin espacios. `Arial`, `Arial,Bold`, `ArialMT`, `Arial-BoldMT` y
  `BCDGEE+ArialMT` cuentan como **una** familia (`arial`). pdfium resuelve `Helvetica` a
  familia `Arial` (sustituto métrico) y eso se acepta a propósito. Se cuentan familias
  distintas: **≥2 ⇒ SOSPECHA (por defecto), ≥3 ⇒ SOSPECHA siempre**.
- **Determinista:** el cálculo sí (misma entrada → mismo número). El **umbral es
  heurístico** y — hay que decirlo — se eligió *después* de ver el corpus (§6).
- **Dato externo que falta:** una **línea base por plantilla/IPS** (histórico del ERP: qué
  juego de fuentes trae habitualmente cada emisor). Sin ella, "2 familias" es una
  convención, no una norma.

#### `TP_FUENTE_MINORITARIA`
- **Afirma:** hay un bloque pequeño escrito con una letra distinta de la del cuerpo — el
  "párrafo pegado".
- **Cómo se calcula:** sobre las familias normalizadas, se marca la que use ≤15% de los
  objetos de texto visibles habiendo ≥2 familias, exigiendo ≥50 objetos en el documento
  para que la palabra "minoría" signifique algo. Se reporta además el bbox envolvente de
  esa familia (evidencia geométrica para el revisor humano, sin exponer el texto).
- **Determinista:** cálculo sí; **umbral 15% heurístico y ajustado al corpus** (§6).
- **Dato externo que falta:** el mismo histórico por plantilla.

#### `TP_ALFA_TEXTO_NO_UNIFORME`
- **Afirma:** el texto se pinta con más de un nivel de opacidad ⇒ una segunda herramienta
  estampó texto encima. Un generador único usa una sola opacidad para el cuerpo.
- **Cómo se calcula:** `FPDFPageObj_GetFillColor` por objeto de texto visible; se cuentan
  los valores distintos del canal alfa. `>1` ⇒ SOSPECHA.
- **Determinista:** **sí, y sin umbral arbitrario** (es el check más limpio de la familia).
- **Dato externo que falta:** ninguno.

#### `TP_TEXTO_SOBRE_ESCANEO`
- **Afirma:** hay texto vectorial estampado encima de un escaneo ⇒ campos reescritos sobre
  la foto del original.
- **Cómo se calcula:** imágenes cuyo bbox cubre ≥70% del área de la página = "escaneo";
  objetos de texto visibles cuyo bbox queda ≥60% dentro de esa imagen; **si el número está
  entre 1 y 40** ⇒ SOSPECHA. Si son cientos, es un documento nativo con fondo/marca de
  agua, no un sello: se declara LIMPIO (así se evita el falso positivo de F03 y de los
  Word con imagen de fondo).
- **Determinista:** cálculo sí; los tres umbrales (70% / 60% / ≤40 objetos) son heurísticos.
- **Dato externo que falta:** ninguno.

#### `TP_PARCHE_BLANCO`
- **Afirma:** hay rectángulos blancos opacos pintados **encima** de contenido ya dibujado
  ⇒ se tapó algo para escribir otra cosa.
- **Cómo se calcula:** objetos `FPDF_PAGEOBJ_PATH` con relleno ≥(240,240,240) y alfa >200,
  de área entre 0.05% y 20% de la página, que cubran ≥30% de su propia área de un objeto de
  **texto o imagen** dibujado antes (el orden de `get_objects()` es el orden del content
  stream = z-order). **Se excluye a propósito el blanco sobre blanco**: Word dibuja cada
  figura como par relleno+borde, y contar eso producía un falso positivo (así se marcaba F00
  por dos figuras vacías de Word que no tapan nada).
- **Determinista:** cálculo sí; umbrales de área/solape heurísticos.
- **Dato externo que falta:** ninguno.

### Informativos — se calculan y se reportan, pero **NO votan** (medidos y descartados)

| id | Afirma | Por qué no vota |
|---|---|---|
| `TP_SUBSET_MAS_COMPLETA` | la misma raíz de fuente aparece embebida como subset (`BCDGEE+Arial`) y también sin embebir ⇒ dos generadores | **No discrimina.** Dispara en 3 falsas y **2 reales**. `BCDGEE+` es el tag que genera Microsoft Word al embeber un subset por un glifo que falta en la fuente base: es un artefacto de Word, no de adulteración. |
| `TP_GENERACIONES_MULTIPLES` | `%%EOF>1` o `/Prev≥1` sin `/Linearized` ⇒ guardado incremental, varias generaciones | **No discrimina.** Dispara en 6 falsas y **4 reales**: todas las exportaciones de Word del corpus traen `%%EOF=2 /Prev=1` de fábrica. Sirve como dato forense de apoyo, no como señal. |
| `TP_CADENA_HERRAMIENTAS` | `Creator` y `Producer` de familias distintas, o `ModDate ≠ CreationDate` ⇒ el PDF pasó por una segunda herramienta después de generarse | **No discrimina hoy:** 1 falsa (F03) y **1 real** (R18, una foto reguardada por Quartz de iOS). Reenviar una foto por el móvil produce exactamente esta firma. Es legítimo en el flujo del trabajador. |

Nota: el caso más elocuente del corpus para este bloque es F02/R29 (§5), donde
`Creator=Microsoft Word LTSC` pero `Producer=4-Heights PDF Library` y `ModDate` es **50
días posterior** a `CreationDate`. Ahí la cadena de herramientas sí es la pista, pero el
documento está en cuarentena y no puede contarse.

---

## 4. La medición real

Configuración por defecto (umbral de familias ≥2). **Se excluyen los 5 documentos en
cuarentena** (F02, F10, F14 de `Falsas/` y R15, R29 de `Reales/`), tal como los marcó
`manifest.csv`.

```
FALSAS no-cuarentena: 12  |  aplicables: 5  |  DETECTADAS: 5   (F00, F01, F04, F06, F09)
REALES no-cuarentena: 14  |  aplicables: 4  |  FALSOS POSITIVOS: 0
recall sobre falsas APLICABLES: 5/5 = 100%
recall sobre TODAS las falsas:  5/12 = 42%
precision:                      5/5  = 100%   <-- NO está medida de verdad (ver §6)
```

Con umbral de familias ≥3: 4/5 aplicables (se cae F09, cuya familia minoritaria pesa 19.5%),
4/12 = 33% del total, 0 falsos positivos.

Por check (solo no-cuarentena):

| check | falsas + | reales + | ids |
|---|---|---|---|
| `TP_FAMILIAS_MULTIPLES` | 5 | 0 | F00, F01, F04, F06, F09 |
| `TP_FUENTE_MINORITARIA` | 4 | 0 | F00, F01, F04, F06 |
| `TP_ALFA_TEXTO_NO_UNIFORME` | **0** | 0 | — (solo dispara en la cuarentena F02/R29) |
| `TP_TEXTO_SOBRE_ESCANEO` | **0** | 0 | — |
| `TP_PARCHE_BLANCO` | **0** | 0 | — (solo dispara en la cuarentena F02/R29) |
| `TP_SUBSET_MAS_COMPLETA` (info) | 3 | 2 | F04,F06,F09 / R24,R25 |
| `TP_GENERACIONES_MULTIPLES` (info) | 6 | 4 | F00,F01,F03,F04,F06,F09 / R16,R24,R25,R28 |
| `TP_CADENA_HERRAMIENTAS` (info) | 1 | 1 | F03 / R18 |

Aplicabilidad (por qué 17 de 26 documentos no se pueden juzgar):

| | no PDF | escaneo puro | capa OCR sintética | evaluables |
|---|---|---|---|---|
| falsas (12) | 1 | 5 | 1 | **5** |
| reales (14) | 2 | 8 | 0 | **4** |

Evidencia de las 5 detecciones (solo tipografía, sin contenido):

| id | objetos de texto visibles | familias | creador |
|---|---|---|---|
| F00 | 149 | `arial:143` + `couriernew:6` (4.0%) | Word 2010 |
| F01 | 178 | `arial:160` + `couriernew:18` (10.1%) | Word 2016 |
| F04 | 156 | `arial:143` + `palatinolinotype:13` (8.3%) | Word 365 |
| F06 | 169 | `arial:157` + `palatinolinotype:12` (7.1%) | Word 365 |
| F09 | 128 | `calibri:103` + `arial:25` (19.5%) | Word |

Los 4 reales evaluables, en cambio: R21 `arial:102` (1 familia, iText),
R24 `arial:473` (1), R25 `arial:214` (1), R27 fuentes anonimizadas por *Print To PDF*
(tipografía `NO_EVALUABLE`; solo se le pudieron aplicar los checks geométricos).

### Checks que hoy reportan 0 detectadas, y por qué

- `TP_ALFA_TEXTO_NO_UNIFORME` y `TP_PARCHE_BLANCO`: **0 detectadas** no porque fallen, sino
  porque el único documento del corpus cuyo motivo etiquetado es `TIPOGRAFIA_MIXTA` está en
  cuarentena (§5). No falta ningún dato externo; falta corpus.
- `TP_TEXTO_SOBRE_ESCANEO`: **0 detectadas**. No hay en el corpus ningún caso de texto
  vectorial estampado sobre un escaneo (los adulterados con escaneo son imagen 100% pura, sin
  capa de texto: la edición se hizo *dentro del píxel*, que es territorio de la familia de
  análisis de imagen, no de esta).

---

## 5. Falsos positivos concretos y su causa

**Falsos positivos sobre reales no-cuarentena: 0.** Ese cero no es un mérito: solo 4 de los
14 reales son evaluables y uno de ellos (R27) tiene la tipografía `NO_EVALUABLE`, así que los
checks de fuente se probaron contra **3 documentos legítimos de 2 emisores**. Con n=3 el
resultado "0 FP" no distingue un check bueno de uno con suerte.

Falsos positivos que **sí** aparecieron y que por eso degradaron checks a informativos:

1. `TP_SUBSET_MAS_COMPLETA` → **R24 y R25** (reales). Causa: Microsoft Word embebe un subset
   `BCDGEE+ArialMT` de **un solo objeto** junto a la `ArialMT` no embebida, para un glifo que
   no está en la fuente base. Artefacto del generador, no de edición. Aparece idéntico en
   falsas (F04, F06, F09) y reales.
2. `TP_GENERACIONES_MULTIPLES` → **R16, R24, R25, R28** (reales). Causa: toda exportación de
   Word del corpus trae `%%EOF=2 /Prev=1`. "Guardado incremental" no implica manipulación.
3. `TP_CADENA_HERRAMIENTAS` → **R18** (real). Causa: una foto del papel reguardada por
   `iOS Quartz PDFContext` vía `pdftopdf`. Reenviar desde el móvil produce la misma firma que
   pasar el PDF por una segunda herramienta.
4. `TP_PARCHE_BLANCO`, primera versión → **F00** (era un acierto por la razón equivocada).
   Los 4 "parches" eran 2 figuras de Word vacías (par relleno+borde blanco) que no tapaban
   nada. Se corrigió exigiendo que el parche cubra texto o imagen, no otro path blanco.
   Tras la corrección F00 sigue detectado, pero por tipografía.
5. `TP_FAMILIAS_MULTIPLES` sin la puerta de fuentes anónimas → **R27** (real): *Print To PDF*
   renombra las fuentes a `CIDFont+F1`/`CIDFont+F2` con familia `z@r2a13.tmp`, y eso se
   contaba como 2 familias distintas. Se corrigió declarando la tipografía `NO_EVALUABLE`
   cuando el productor anonimiza los nombres.

### El caso en cuarentena que hay que documentar

`Falsas/FALSA-03.pdf` (F02) es **byte-idéntico** (sha256
`28c4a946…`) a `Reales/REAL-15.pdf` (R29). Es, además, **el único documento
del corpus cuyo motivo etiquetado es TIPOGRAFIA_MIXTA**. La sonda dispara en él 4 checks a
la vez, con una firma de edición de libro de texto:

- 4 objetos de texto (de 122) con fuente **`ACWIYO+ArialMT` embebida como subset**, mientras
  todo el resto del documento usa `ArialMT` **no embebida**;
- esos mismos 4 objetos son los únicos con **alfa 191** (semitransparentes) frente a 255 del
  resto;
- están al **final del content stream** (índices 294–303, pintados después de todo);
- justo debajo hay **19 rectángulos blancos opacos** que cubren la imagen del documento
  original (índice 26), en las mismas coordenadas que los 4 textos nuevos;
- `Producer = 4-Heights PDF Library` con `Creator = Microsoft Word LTSC`, y `ModDate` 50 días
  posterior a `CreationDate`.

**No se cuenta como detección** porque su gemelo byte-idéntico está etiquetado como real: la
etiqueta está corrupta y usarlo sería premiarse por una verdad que no existe. Sirve solo como
validación de diseño de `TP_ALFA_TEXTO_NO_UNIFORME` y `TP_PARCHE_BLANCO`. Y deja una
advertencia: si la etiqueta correcta fuera "real", esos dos checks tendrían 100% de falsos
positivos.

---

## 6. Honestidad sobre el ajuste al corpus

- El umbral **≥2 familias** se eligió **después** de ver que los 4 reales evaluables usan
  exactamente 1 familia y las 5 falsas evaluables usan 2 o más. Eso es ajuste al corpus. Lo
  que lo salva parcialmente: las 5 falsas vienen de **3 plantillas distintas**
  (Arial+Courier New, Arial+Palatino, Calibri+Arial) y los reales de **3 emisores distintos**,
  y el mecanismo es plausible a priori (quien reescribe campos en Word deja su propia letra).
  No es un único documento memorizado, pero tampoco es evidencia sólida.
- El umbral **15%** de `TP_FUENTE_MINORITARIA` se fijó por encima de la banda observada
  (4–10%) y deja fuera F09 (19.5%). Es el parámetro más arbitrario de la familia; con solo
  2 familias por documento este check es casi un duplicado del anterior.
- Los 4 reales evaluables no incluyen **ningún** caso del flujo "auxiliar rellena una
  plantilla Word y exporta" con dos tipografías, que es legítimo y frecuentísimo en la vida
  real. **En producción este check va a generar falsos positivos que este corpus no puede
  mostrar.** R24/R25 son exactamente ese flujo y por casualidad usan una sola fuente.
- `TP_ALFA_TEXTO_NO_UNIFORME`, `TP_PARCHE_BLANCO` y `TP_TEXTO_SOBRE_ESCANEO` **no están
  medidos**: 0 disparos fuera de cuarentena. Están justificados mecánicamente, no
  empíricamente.

---

## 7. Confusor principal de la familia

**El documento sin fuentes**, en sus tres variantes, y es la mayoría del corpus
(**17 de 26** documentos no-cuarentena):

1. **JPEG suelto** (3 docs): no hay objetos PDF.
2. **Escaneo/foto puro** (13 docs: CamScanner, EPSON Scan, Quartz iOS, iLovePDF): imagen de
   página completa, cero objetos de texto. Aquí la adulteración se hace *en el píxel* y esta
   familia es estructuralmente ciega. **Nunca declarar "limpio" aquí.**
3. **Capa de texto sintetizada por OCR** (1 doc, ClearScan): el peor confusor porque *sí*
   tiene fuentes — 48 familias inventadas y 427 objetos de texto sobre la imagen — y produce
   el disparo más fuerte de todo el corpus por una razón que no tiene nada que ver con
   falsedad. Sin filtrar ClearScan/Paper Capture/Tesseract/ABBYY esta familia miente.

Confusor secundario, ya medido: **los artefactos normales de Microsoft Word** (subset
`BCDGEE+`, `%%EOF=2 /Prev=1`) parecen manipulación y no lo son.

---

## 8. Severidad recomendada: **ALERTA** (nunca BLOQUEA)

- **BLOQUEA queda descartado.** El check que sostiene todo el recall (`TP_FAMILIAS_MULTIPLES`)
  no distingue "documento adulterado" de "documento legítimo tecleado en Word con dos
  tipografías". Su precisión real está medida contra 3 documentos legítimos. Bloquear una
  incapacidad por eso es inaceptable: se le niega el pago a un trabajador por la elección de
  fuente de una secretaria.
- **ALERTA** para el veredicto de la familia (`TP_FAMILIAS_MULTIPLES` / `TP_FUENTE_MINORITARIA`
  / `TP_TEXTO_SOBRE_ESCANEO`): la sonda entrega, sin exponer PII, el bbox de la zona escrita
  con la letra minoritaria; un revisor humano confirma o descarta en segundos mirando ese
  recuadro. Buen coste/beneficio: 42% de las falsas del corpus llegan a revisión humana con
  la zona señalada.
- **Excepción, BLOQUEA candidato para más adelante:** `TP_ALFA_TEXTO_NO_UNIFORME` +
  `TP_PARCHE_BLANCO` disparando juntos. Es determinista, sin umbrales discutibles, y describe
  un acto positivo de edición (tapar con blanco y estampar texto semitransparente encima) que
  ningún generador legítimo hace. **Hoy no se puede promover**: su única evidencia está en
  cuarentena (n=1, con etiqueta corrupta). Recomendación: mantenerlo en ALERTA con prioridad
  máxima y promoverlo a BLOQUEA cuando haya ≥10 casos confirmados y 0 falsos positivos sobre
  ≥100 legítimos con capa de texto.
- **AVISO** para los tres informativos (`TP_SUBSET_MAS_COMPLETA`,
  `TP_GENERACIONES_MULTIPLES`, `TP_CADENA_HERRAMIENTAS`): no deben cambiar el resultado, solo
  aparecer en el expediente forense del documento.
- **NO APLICABLE** debe propagarse como tal al motor global. Si el 65% de los documentos no
  tiene fuentes que comparar, marcar eso como "limpio" da una falsa sensación de control.

---

## 9. Qué le falta a esta familia para servir de verdad

1. **Línea base por plantilla/IPS** (histórico del ERP): para cada emisor, qué juego de
   fuentes, qué productor y qué geometría trae habitualmente. Con eso `TP_FAMILIAS_MULTIPLES`
   deja de ser un umbral inventado y pasa a ser "este emisor nunca ha usado Palatino".
   Es el dato externo que falta, y no es un catálogo público: hay que acumularlo con las
   radicaciones que ya entran.
2. **Más reales con capa de texto.** Hoy 3 documentos sostienen toda la precisión. Se
   necesitan ≥100 legítimos con capa de texto, y en particular ejemplos del flujo "plantilla
   Word rellenada a mano", que es el generador esperado de falsos positivos.
3. **Resolver las 2 etiquetas corruptas.** El único caso `TIPOGRAFIA_MIXTA` del corpus está
   en cuarentena; hasta que el cliente diga cuál de las dos etiquetas es la correcta, los dos
   mejores checks de la familia siguen sin medir.
4. **Complemento obligatorio de análisis de imagen.** Los 13 escaneos puros no-cuarentena
   (5 falsas entre ellos) son invisibles aquí por construcción. Esta familia no puede ser la
   única defensa.
