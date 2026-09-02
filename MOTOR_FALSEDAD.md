# MOTOR DE FALSEDAD — especificación consolidada

Estado: **especificación. NO implementado en el paquete.** Fecha de consolidación: 2026-09-02.

> ### Veredicto de arranque, sin adornos
>
> **El motor NO está listo para producción.** Lo que existe hoy son 37 checks medidos como sondas
> exploratorias contra un corpus de 31 documentos (15 adulterados / 16 legítimos) del que **2 pares
> son byte-idénticos con etiquetas opuestas** y **3 adulterados llegaron sin motivo declarado**.
> Sobre los 26 documentos con etiqueta utilizable el conjunto completo de checks detecta **7 de 12
> adulterados (58 %) con 0 falsos positivos sobre 14 legítimos** — pero ese "0" está medido contra
> **11 incapacidades legítimas** (los otros 3 son un permiso, otro permiso y una historia clínica,
> que varias familias excluyen por diseño), y en la familia que carga el recall, contra **3
> documentos**. Las 5 adulteradas no detectadas **no son fallos de regla: son fallos de cobertura**
> (1 ó 2 familias aplicables cada una). Y hay **3 documentos de 26 (todos legítimos) sobre los que
> ninguna familia puede opinar**, más 10 de 14 legítimos que no alcanzan cobertura para un veredicto
> limpio con sentido.
>
> Lo que falta está en §6. Lo que hay que preguntarle al cliente, en §7.

Documentación de respaldo (fuera del repositorio, contiene datos de salud):
`../dataset-falsedad/LEEME.md`, `../dataset-falsedad/manifest.csv`,
`../dataset-falsedad/ground_truth.json`, `../dataset-falsedad/senales/*/INFORME.md`,
`../dataset-falsedad/ESTADO_CORPUS.md`.

**Convención de identificadores en este documento (Ley 1581).** Los documentos se citan por los
**8 primeros caracteres de su sha256** (`28c4a946`, `e0ee54fd`, …). Los nombres de archivo del corpus
contienen nombres de pacientes y cédulas, así que **no aparecen aquí**; la equivalencia vive en
`manifest.csv`, fuera del repo. Tampoco aparece ningún código CIE-10 concreto: se habla de bloques y
capítulos.

---

## 1. Qué es y qué NO es

### Es

Un **motor de reglas deterministas, 100 % local**, que verifica **invariantes comprobables** sobre un
documento de incapacidad y sobre su relación con datos que la empresa ya tiene. Corre en la misma
máquina que el OCR, con las mismas librerías que ya usa el paquete (`pypdfium2`, `Pillow`, `numpy`,
`rapidocr-onnxruntime`) más `re`/`datetime`/`hashlib`/`difflib` de la stdlib. No hay red en runtime.

Cada check responde una pregunta con respuesta verificable y una prueba adjunta. Ejemplos reales:

- «El documento imprime inicio, fin y días, y `(fin − inicio) + 1 ≠ días`.» → aritmética de
  calendario; la contradicción se puede señalar con el dedo en el papel.
- «Hay 19 rectángulos blancos opacos pintados encima de la imagen del documento y, justo en esas
  coordenadas, 4 objetos de texto con opacidad 191 cuando el resto del documento usa 255.» → lectura
  del content stream del PDF; ningún generador legítimo produce eso.
- «Este certificado declara menos días que el mínimo que fija el art. 237 del CST para ese bloque
  diagnóstico.» → comparación contra una norma escrita, fechada y citada.

### NO es

- **No es IA.** No hay modelo entrenado, ni clasificador, ni embeddings, ni pesos aprendidos de los
  datos. No hay llamadas a OpenAI / Gemini / Anthropic ni a ningún servicio remoto, y no habrá:
  el documento es historia clínica y no sale de la máquina.
- **No "predice" falsedad ni da una probabilidad.** No existe `P(falsa) = 0.87`. Existe «estos N
  checks dispararon, con esta evidencia, y estos M no pudieron opinar».
- **No es un peritaje.** En particular **no verifica que una firma sea auténtica**: eso es peritaje
  grafológico y requiere muestras indubitadas del médico que el sistema no tiene ni tendrá. Lo único
  detectable es el **reuso** de un gráfico y la **incoherencia interna** entre el sello y el texto.
- **No decide.** Nunca rechaza un trámite, nunca niega un pago, nunca cierra un caso.
- **No sustituye al analista.** Su producto es una **cola priorizada con la evidencia resaltada**,
  para que la persona que hoy revisa a mano mire primero lo que más lo amerita.

### Cómo encaja en el flujo que ya existe

El repo ya tiene exactamente el sitio donde esto va, y no hay que inventar nada:

```
1_entrada/  →  OCR + extracción  →  validación documental  →  lp_ausentismos_ia
                                    (erp.validar_documentacion)   estado=PENDIENTE_REVISION
                                              ↑                            ↓
                                    [ MOTOR DE FALSEDAD ]         UI de revisión → APROBADO
                                     marca el registro,             (una persona decide)
                                     no lo rechaza
```

El motor **anota el registro de staging** y **prioriza la bandeja**. Todo sigue entrando como
`PENDIENTE_REVISION`, igual que hoy pasa con `documentacion_estado=INCOMPLETA` y con
`fecha_inicio_calculada`: el aviso acompaña al caso, el auxiliar decide. La regla de dominio
**«staging, no directo»** no se toca.

**Regla dura de diseño, tomada de la medición:** *ningún check bloquea por sí solo en la v1.* No hay
un solo check en el conjunto cuya precisión esté medida con una muestra que justifique negar un pago.
Ver §4 para la puerta de promoción a `BLOQUEA`.

### Los cuatro estados de un check (y el más importante es el tercero)

| Estado | Significado | Cuenta como |
|---|---|---|
| `DISPARA` | la invariante se viola, con evidencia | señal |
| `OK` | la invariante se verificó y se cumple | limpio |
| `NO_APLICABLE` | el documento no permite ejecutar el check (es un JPEG, es un escaneo sin fuentes, es un permiso sin diagnóstico) | **ni señal ni limpio** |
| `NO_VERIFICABLE` / `SIN_INSUMO` | el check corre pero le falta el dato externo (catálogo CIE-10, histórico del ERP) o el campo no se leyó | **ni señal ni limpio** |

Confundir `NO_APLICABLE` con `OK` es el error que convertiría este motor en un generador de falsa
seguridad. Hoy, en el corpus, **17 de 26 documentos son `NO_APLICABLE` para la familia de tipografía**
y **16 de 26 para la de firma**. Un tablero que pintara eso de verde estaría mintiendo.

---

## 2. Taxonomía de señales → familia → checks

La taxonomía sale de `ground_truth.json`, que a su vez sale de la tabla de motivos que entregó
radicaciones. Es la lista de lo que **el analista humano ya revisa a mano**; el motor intenta
materializarla.

| Señal declarada | Qué afirma el cliente | Familia | Checks que la implementan | Estado |
|---|---|---|---|---|
| `DX_INEXISTENTE` | el código CIE-10 no existe en el catálogo | `dx_catalogo` | `DX_INEXISTENTE` (principal) · `DX_CAPITULO_INCOHERENTE` (sustituto autónomo) | **bloqueada**: falta `lpdiagnosticos` |
| `DX_FORMATO` | el código no tiene la longitud del catálogo (3 en vez de 4 caracteres) | `dx_catalogo` | `DX_FORMATO_LONGITUD` | activo, con contraejemplo grave |
| `DX_NOMBRE_DISTINTO` | la descripción impresa no es la del catálogo para ese código | `dx_catalogo` | `DX_NOMBRE_DISTINTO` · `DX_CAPITULO_INCOHERENTE` | **bloqueada**: falta `lpdiagnosticos` |
| `FECHAS_INCOHERENTES` | inicio, duración y fin no cuadran | `aritmetica_fechas` | `AF01`…`AF06` | activo |
| `DIAS_VS_DIAGNOSTICO` | los días no son plausibles para el diagnóstico | `dias_vs_diagnostico` | `DIAS_BAJO_MINIMO_LEGAL_ABORTO` · `DIAS_VS_MINIMO_LEGAL_MATERNIDAD` · `DIAS_VS_DX_RANGO_HISTORICO` | 1 check activo con ancla **legal**; el clínico **desactivado** por falta de histórico |
| `FIRMA_MEDICO` | la firma es sospechosa | `firma_y_reuso` | `C1`…`C10` (reuso exacto / perceptual / recomprimido / fondo / id incoherente / …) | activo pero casi ciego; **no verifica autenticidad** |
| `TIPOGRAFIA_MIXTA` | varios tipos de letra en un mismo documento | `tipografia_pdf` | `TP_FAMILIAS_MULTIPLES` · `TP_FUENTE_MINORITARIA` · `TP_ALFA_TEXTO_NO_UNIFORME` · `TP_PARCHE_BLANCO` · `TP_TEXTO_SOBRE_ESCANEO` | activo sobre 1/3 del flujo |
| `SIN_MOTIVO_REGISTRADO` | — (celda vacía en la tabla del cliente) | ninguna | ninguno | **no es una señal**: es un hueco de etiquetado. 3 documentos |

### Huecos de la taxonomía (lo que el cliente no pidió y el corpus demuestra que hace falta)

1. **Edición en el píxel.** 13 de los 26 documentos evaluables son escaneos/fotos puros (más 3 JPEG
   sueltos). Ahí la adulteración se hizo **dentro del mapa de bits** y **ninguna** de las cinco
   familias puede verla: `tipografia_pdf` es ciega por construcción y `firma_y_reuso` no puede
   aislar la firma. Hace falta una familia de **análisis de imagen** (binarización adaptativa,
   componentes conexos, discontinuidad de ruido/JPEG por región). Es la carencia estructural más
   grande del motor, no un pendiente menor.
2. **Coherencia contra el ERP.** Nadie verifica hoy que el titular esté **activo**, que la EPS del
   documento sea la del empleado en catálogo, que la IPS emisora exista/esté habilitada, ni que el
   documento **no se haya radicado ya**. Son checks baratos, deterministas y con datos que la
   empresa **ya tiene**. Deberían ser la primera familia nueva.
3. **Prórrogas solapadas y fechas reutilizadas** entre trámites del mismo titular. Requiere
   `lpausentismos` (§6).

---

## 3. Tabla por check

Leyenda. **Sev.**: severidad recomendada (`AVISO` anota · `ALERTA` exige revisión humana ·
`BLOQUEA` impide aprobar — hoy **ninguno**). **D/H**: determinista / heurístico; «det·H» = el cálculo
es determinista pero la **atribución** es ambigua (no se distingue «mal impreso» de «mal leído»).
**Detecta** y **FP** se miden sobre la base evaluable: **12 adulterados / 14 legítimos** (excluida la
cuarentena de 5 documentos). `n.ev` = documentos donde el check no puede dar ni positivo ni negativo,
sobre 26.

### Familia `aritmetica_fechas` — 6 checks · 2/12 · 0/14

| Check | Sev. | D/H | Dato externo que necesita | Detecta | FP | n.ev | Nota |
|---|---|---|---|---|---|---|---|
| `AF01_TRIPLE_IMPRESA_INCOHERENTE` | ALERTA | det | ninguno para decidir | **2/12** | 0/14 | 14 | El núcleo. En `e0ee54fd` la contradicción se confirma en la **capa de texto del PDF**, sin OCR |
| `AF02_RANGO_INVERTIDO` | ALERTA | det | ninguno | 0/12 | 0/14 | — | 0 casos en el corpus; autotest sintético OK |
| `AF03_DIAS_FUERA_DE_RANGO` | AVISO | det | ninguno (1..540 ya es regla del repo) | 0/12 | 0/14 | — | Tuvo **1 FP sobre un legítimo** en la primera corrida, por leer `dias=2026`; corregido |
| `AF04_DIA_SEMANA_INCONSISTENTE` | AVISO | det·H | coordenadas del OCR | 0/12 | 0/14 | 23 | 3 documentos imprimen día de la semana; los 3 cuadran |
| `AF05_FECHA_FUERA_DE_CALENDARIO` | ALERTA | det | ninguno | 0/12 | 0/14 | — | 0 casos; hoy el pipeline descarta la fecha imposible **en silencio** |
| `AF06_ANIO_ATIPICO` | AVISO | heur (umbral 2 años) | fecha de radicación del trámite | 0/12 | 0/14 | — | Solo dispara en la cuarentena |

### Familia `tipografia_pdf` — 9 checks · 5/12 · 0/14 (sobre 3 legítimos evaluables)

| Check | Sev. | D/H | Dato externo que necesita | Detecta | FP | n.ev | Nota |
|---|---|---|---|---|---|---|---|
| `TP_FAMILIAS_MULTIPLES` | ALERTA | **heur, umbral post-hoc** | línea base de fuentes por plantilla/IPS | **5/12** | 0/14 | 17 | Carga **todo** el recall de la familia. Umbral (≥2 familias) elegido después de ver el corpus |
| `TP_FUENTE_MINORITARIA` | AVISO | heur (15 %) | ídem | 4/12 | 0/14 | 17 | Casi duplicado del anterior; el umbral más arbitrario del conjunto |
| `TP_ALFA_TEXTO_NO_UNIFORME` | ALERTA (candidato a BLOQUEA) | **det, sin umbral** | ninguno | 0/12 | 0/14 | 17 | **Sin medir**: su único caso está en cuarentena (`28c4a946`) |
| `TP_PARCHE_BLANCO` | ALERTA (candidato a BLOQUEA) | det | ninguno | 0/12 | 0/14 | 17 | Ídem. Dispara **junto** con el anterior en `28c4a946` |
| `TP_TEXTO_SOBRE_ESCANEO` | ALERTA | heur (3 umbrales) | ninguno | 0/12 | 0/14 | 17 | Sin medir: 0 casos |
| `TP_SUBSET_MAS_COMPLETA` | AVISO (info) | det | — | 3/12 | **2/14** | — | **No vota.** `BCDGEE+` es un artefacto normal de Word |
| `TP_GENERACIONES_MULTIPLES` | AVISO (info) | det | — | 6/12 | **4/14** | — | **No vota.** Toda exportación de Word trae `%%EOF=2 /Prev=1` |
| `TP_CADENA_HERRAMIENTAS` | AVISO (info) | det | — | 1/12 | **1/14** | — | **No vota.** Reenviar una foto por iOS produce la misma firma |
| `TP_APLICABILIDAD` | puerta | det | — | — | — | — | Obligatoria. Sin ella, un documento con capa OCR sintética (ClearScan, 48 fuentes) da la detección más fuerte del corpus por la razón equivocada |

### Familia `dx_catalogo` — 7 checks · 2/12 · 0/14

| Check | Sev. | D/H | Dato externo que necesita | Detecta | FP | n.ev | Nota |
|---|---|---|---|---|---|---|---|
| `DX_FORMATO_LONGITUD` | AVISO | det | confirmación de la convención de longitud | **2/12** | 0/14 | 3 | Las 2 detecciones son **el mismo emisor y el mismo paciente**. Contraejemplo demoledor: el documento byte-idéntico presente en ambas clases dispara este check en las dos carpetas |
| `DX_INEXISTENTE` | ALERTA | det | **`ASTGU.lpdiagnosticos`** | 0/12 | — | **31/31** | `no_verificable` en todo el corpus, a propósito. Un catálogo parcial convertiría códigos raros pero válidos en acusaciones |
| `DX_NOMBRE_DISTINTO` | AVISO | heur | `lpdiagnosticos` + versión/año de la CIE-10 | 0/12 | — | **31/31** | El OCR destroza las descripciones; el umbral de similitud no está medido |
| `DX_CAPITULO_INCOHERENTE` | AVISO (experimental) | heur (léxico) | ninguno | 1/12 | 0/14 | — | Único check autónomo capaz de ver una descripción sustituida sin catálogo. n=1 |
| `DX_SIN_PRINCIPAL` | **desactivar** | heur | ninguno | 1/12 | **2/14** | — | Mide la calidad del escaneo, no la falsedad (el OCR perdió la letra inicial del código) |
| `DX_NO_LEIDO` | no acusa | det | — | — | — | — | Métrica de cobertura: código legible en 25/28 aplicables, con descripción en 18/28 |
| `DX_AUSENTE_EN_DOC` | no acusa | det | — | 0 | 0 | — | 2 legítimos quedan en `revisar` porque el OCR desordena las celdas de la tabla |

### Familia `firma_y_reuso` — 10 checks · 2/12 · 0/14

| Check | Sev. | D/H | Dato externo que necesita | Detecta | FP | n.ev | Nota |
|---|---|---|---|---|---|---|---|
| `FONDO_REUSO_CROSS_PACIENTE` | ALERTA (v1) | det | `id_paciente` de la radicación | 0/12 | 0/14 | 9 | Sin explicación benigna conocida. Su **único disparo del corpus está en cuarentena** — y ahí el "paciente distinto" es un artefacto del archivado, no un fraude |
| `FIRMA_REUSO_EXACTO_CROSS_PACIENTE` | ALERTA (v1) | det | `id_paciente` + índice de hashes histórico | 0/12 | 0/14 | 16 | El 0 es **medición, no bug**: autotest sintético 4/4. El corpus no contiene ni un caso de firma cruzando pacientes |
| `FIRMA_REUSO_PERCEPTUAL_CROSS_PACIENTE` | ALERTA | heur (pHash≤6 y dHash≤10) | ídem | 0/12 | 0/14 | 16 | Umbrales calibrados a ojo, sin positivos reales |
| `FIRMA_REUSO_RECOMPRIMIDA` | AVISO | heur | ninguno | **2/12** | 0/14 | 16 | El **único con recall y el más débil**: su explicación benigna (un optimizador de PDF) es frecuentísima |
| `FIRMA_ID_INCOHERENTE` | ALERTA | heur (insumo = OCR de un recorte) | **RETHUS** | 0/12 | 0/14 | 23 | Un dígito mal leído fabrica la contradicción |
| `MEMBRETE_COMPARTIDO` | info | det | catálogo de logos de EPS/IPS | 0 | 0 | — | Existe para explicar por qué un reuso **no** es sospechoso |
| `MARCA_HERRAMIENTA_CAPTURA` | AVISO (info) | det | ninguno | 3/12 | **1/14** | — | Procedencia, no falsedad. Es también el **filtro negativo** imprescindible de los 4 anteriores |
| `FIRMA_MEDICO_AUSENTE` | **no usar** | det | formatos con la etiqueta | 0/12 | 0/14 | **24** | La etiqueta existe en 8/31 documentos y en **0 de los 12 adulterados evaluables** |
| `RECURSO_REUSO_CROSS_EMISOR` | **no usar** | det | extractor fiable de IPS emisora + `lpeps` | 0/12 | 0/14 | **26** | Hoy `entidad.eps` devuelve fragmentos de dirección |
| `FIRMA_HISTORICO_ERP` | **no usar** | det | **índice de hashes del histórico de radicaciones** | 0/12 | 0/14 | **26** | Define el techo de toda la familia |

### Familia `dias_vs_diagnostico` — 5 checks · 1/12 · 0/14

| Check | Sev. | D/H | Dato externo que necesita | Detecta | FP | n.ev | Nota |
|---|---|---|---|---|---|---|---|
| `DIAS_BAJO_MINIMO_LEGAL_ABORTO` | ALERTA | det (ancla legal: CST art. 237) | validación jurídica fechada | **1/12** (1/1 de su motivo) | 0/14 | 16 | **Margen cero**: un legítimo del mismo bloque trae exactamente el mínimo. Cubre 9 categorías CIE-10 de ~14.000 |
| `DIAS_VS_MINIMO_LEGAL_MATERNIDAD` | AVISO | det (CST art. 236, Ley 2114/2021) | validación jurídica | 0/12 | 0/14 | 16 | Lecturas legítimas en **las dos colas** (licencia fraccionada, parto pretérmino, complicación posparto) |
| `DIAS_LARGOS_SIN_DX_VERIFICABLE` | AVISO (estado `REVISION`) | det | ninguno | 0/12 | 1/14 en `REVISION` | — | **Su único disparo del corpus es basura**: los "202 días" son un defecto vivo del extractor (§5) |
| `DIAS_VS_DX_RANGO_HISTORICO` | **DESACTIVADO** | heur (percentiles) | **`ASTGU.lpausentismos`** ≥2 años, ≥5.000 certificados iniciales | `SIN_INSUMO` 31/31 | — | 31 | El check central de la familia. Implementado y probado; no puede correr |
| `DXDIAS_PAR_LEGIBLE` | cobertura | det | — | 10/26 | — | — | El techo real de la familia: solo 10 de 26 documentos permiten opinar |

### Contradicciones entre familias — resueltas explícitamente

El material de origen se contradice en cinco puntos. No los promedio: los resuelvo y digo cómo.

1. **¿Existe algún `BLOQUEA`?** Cuatro familias dicen «nunca bloquear»; `firma_y_reuso` propone
   `BLOQUEA` para `FONDO_REUSO_CROSS_PACIENTE` y `FIRMA_REUSO_EXACTO_CROSS_PACIENTE`.
   **Resolución: no, ninguno bloquea en la v1.** El argumento decisivo es del propio corpus: el único
   disparo de `FONDO_REUSO_CROSS_PACIENTE` ocurre en el par `d86ae595`, dos archivos byte-idénticos
   que **el área archivó bajo dos titulares distintos**. Es decir, el mecanismo se dispara igual con
   un **error de archivado** que con un fraude, y ese error existe demostradamente en los datos del
   cliente. Bloquear un pago con eso es inaceptable.
2. **La condición de `BLOQUEA` de `AF01` está mal escrita en su propio informe.** El informe define
   `BLOQUEA` = «desfase ≠ 0 **y** nivel ALTA **y** confirmable sin OCR **y** clase = grueso», y luego
   afirma que en este corpus habría bloqueado `e0ee54fd`. **No es cierto:** `e0ee54fd` tiene
   `clase = off_by_one` (desfase +1) y `confirmable_sin_ocr = true`; el otro acierto (`d5b72739`) es
   `grueso` pero `confirmable_sin_ocr = false` (es un JPEG). Con la condición tal como está escrita,
   `BLOQUEA` dispara en **0 de 12** adulterados. **Resolución: la condición es la correcta y la nota
   es el error**; queda documentado para que nadie implemente el bloqueo creyendo que tiene un caso
   que lo respalde.
3. **El único disparo de `DIAS_LARGOS_SIN_DX_VERIFICABLE` está causado por un bug de otra familia.**
   `dias_vs_diagnostico` marca un legítimo (`272d0d3d`, un JPEG) como «202 días sin diagnóstico
   legible» y concluye que la marca «es correcta como revisar a mano». `aritmetica_fechas` demuestra
   que **ese documento no imprime días en absoluto** y que el `202` lo fabrica el patrón
   `duraci[oó]n\b[^\d]{0,10}(\d{1,3})` de `extract.py`. **Resolución: no es una marca correcta, es un
   check opinando sobre un valor inventado.** Este es el ejemplo canónico de por qué el motor
   necesita **procedencia por campo** antes que checks nuevos.
4. **Dos lectores distintos del mismo campo CIE-10.** `dx_catalogo` construyó un localizador anclado
   sobre el texto de RapidOCR; `dias_vs_diagnostico` prioriza la **capa de texto del PDF** y exige
   confianza ALTA. Sus resultados difieren, y ambas familias coinciden en que el campo
   `diagnostico.cie10` del extractor **no es usable** (difiere en 10 de 31 documentos; en un caso
   devuelve un código derivado de la **cédula del médico** mal leída). **Resolución: un solo lector
   compartido**, capa de texto primero, RapidOCR después, campo del extractor nunca, con
   `confianza` y `procedencia` explícitas; los checks solo actúan con confianza ALTA. La medición
   dice que eso baja la cobertura de 17/26 a 10/26 y que **es el precio correcto**.
5. **`DX_FORMATO_LONGITUD`: la longitud del código es convención del emisor, no huella de
   adulteración.** El cliente marcó `d86ae595` como falso *precisamente* porque imprime un código de
   3 caracteres… y tiene el **mismo archivo, byte a byte,** archivado como legítimo. El criterio del
   analista humano y el del check coinciden, y **en ese caso no separan**. **Resolución: se queda en
   `AVISO` con peso 1** y sube a `ALERTA` solo cuando el histórico demuestre que ese emisor imprime
   normalmente 4 caracteres.

### Lo que dos familias dicen del par en cuarentena `28c4a946` (y por qué importa)

Es el único documento del corpus donde **dos familias independientes** acumulan evidencia fuerte:

- `tipografia_pdf`: 4 objetos de texto con fuente embebida como subset frente al resto no embebido,
  **esos mismos 4 son los únicos con opacidad 191** (resto 255), están **al final del content stream**
  (pintados después de todo), y justo debajo hay **19 rectángulos blancos opacos** que cubren la
  imagen del documento original, en las mismas coordenadas. `Producer` de una librería distinta al
  `Creator`, y `ModDate` **50 días posterior** a `CreationDate`.
- `aritmetica_fechas`: `AF01` con desfase **grueso**, y la cadena contradictoria está **en la capa de
  texto embebida del PDF** (verificada con `pypdfium2`), no en la salida del OCR.

Ese documento está etiquetado **a la vez** como adulterado y como legítimo (mismo sha256 en las dos
carpetas). La explicación benigna que quedaría —«es un emisor que imprime la fecha fin con otro
formato»— no explica los parches blancos ni la opacidad. **Recomendación al cliente: resolver ese par
a favor de `falsa`.** Es la pieza de evidencia más fuerte de todo el corpus y hoy no cuenta para nada
porque la etiqueta está corrupta.

---

## 4. Modelo de puntuación

### Por qué los pesos NO se ajustan a los datos

Con 12 adulterados evaluables provenientes de **5 titulares distintos**, ajustar pesos contra el
corpus es memorizarlo. Así que los pesos **no se fitean**: se derivan de una **clasificación
declarada de la naturaleza de cada check**, y después se **verifica** que el modelo reproduce la
medición sin sorpresas. La medición valida; no calibra.

| Peso | Clase de check | Criterio declarado | Evidencia medida que lo sostiene |
|---|---|---|---|
| **0** | informativo | dispara en ambas clases con una proporción parecida a la base del corpus (12:14), o mide calidad del insumo | `TP_GENERACIONES_MULTIPLES` 6F/4R · `TP_SUBSET_MAS_COMPLETA` 3F/2R · `TP_CADENA_HERRAMIENTAS` 1F/1R · `MARCA_HERRAMIENTA_CAPTURA` 3F/1R · `DX_NO_LEIDO`, `DXDIAS_PAR_LEGIBLE`, `MEMBRETE_COMPARTIDO`, `FIRMA_MEDICO_AUSENTE` |
| **1** | AVISO | heurístico, o determinista con **atribución ambigua** (mal impreso vs. mal leído), o con contraejemplo conocido | `DX_FORMATO_LONGITUD` (contraejemplo byte-idéntico) · `DX_NOMBRE_DISTINTO` · `DX_CAPITULO_INCOHERENTE` · `AF03` · `AF04` · `AF06` · `TP_FUENTE_MINORITARIA` · `FIRMA_REUSO_RECOMPRIMIDA` · `DIAS_VS_MINIMO_LEGAL_MATERNIDAD` · `DIAS_LARGOS_SIN_DX_VERIFICABLE` |
| **2** | ALERTA heurística | heurístico con mecanismo plausible *a priori* y 0 FP medidos, **pero con un generador de FP conocido que este corpus no contiene** | `TP_FAMILIAS_MULTIPLES` (el flujo legítimo «plantilla Word rellenada a mano») · `FIRMA_REUSO_PERCEPTUAL_CROSS_PACIENTE` · `FIRMA_ID_INCOHERENTE` |
| **3** | ALERTA determinista | invariante verificable, 0 FP medidos, explicación benigna **posible pero acotada** (un dígito de OCR, convención de emisor) | `AF01` · `AF02` · `AF05` · `DIAS_BAJO_MINIMO_LEGAL_ABORTO` · `DX_INEXISTENTE` (cuando exista catálogo) |
| **5** | acto positivo de edición | determinista, **sin umbrales discutibles y sin explicación benigna conocida**; hoy **sin medir** fuera de cuarentena | `TP_ALFA_TEXTO_NO_UNIFORME` · `TP_PARCHE_BLANCO` · `TP_TEXTO_SOBRE_ESCANEO` · `FIRMA_REUSO_EXACTO_CROSS_PACIENTE` · `FONDO_REUSO_CROSS_PACIENTE` (los dos últimos **solo** si `id_paciente` viene de la radicación; si es inferido, bajan a 2) |

`score = Σ pesos de los checks en estado DISPARA`.

### Veredicto

```
SOSPECHOSO   score ≥ 4  Y  ≥1 check de peso ≥3 disparó  Y  ≥2 familias distintas dispararon
REVISAR      score ≥ 2, o cualquier check de peso ≥2 disparó
SIN_SEÑALES  score = 0  Y  ≥3 de las 5 familias pudieron opinar
SIN_COBERTURA score = 0 Y  ≤2 familias pudieron opinar     ← NO es "limpio"
```

Las tres reglas duras, y cada una responde a algo medido:

1. **Un solo check heurístico nunca alcanza `SOSPECHOSO`.** `TP_FAMILIAS_MULTIPLES` (2) +
   `TP_FUENTE_MINORITARIA` (1) = 3 < 4. Un documento legítimo tecleado en Word con dos tipografías
   —el generador de FP que este corpus **no contiene** y que la vida real produce a diario— cae en
   `REVISAR`, no en `SOSPECHOSO`. Y aunque sume un tercer heurístico débil
   (`FIRMA_REUSO_RECOMPRIMIDA`, +1 = 4), la puerta «≥1 determinista de peso ≥3» lo detiene.
2. **`≥2 familias distintas`.** Un mecanismo de detección que falla (un umbral mal puesto, un lector
   de OCR roto) suele fallar en una sola familia. Exigir dos familias es exigir que la evidencia sea
   **independiente**. Coste medido: baja el `SOSPECHOSO` de 4/12 a 2/12; beneficio: los dos que
   quedan tienen dos y tres familias coincidiendo.
3. **`SIN_COBERTURA` es un veredicto de primera clase, no un `SIN_SEÑALES` degradado.** Es el estado
   que impide que el motor diga «limpio» donde en realidad dijo «no pude mirar».

### Verificación contra el corpus (12 adulterados / 14 legítimos, cuarentena excluida)

| Documento | Checks que disparan | Score | Familias | Veredicto |
|---|---|---|---|---|
| `8aeee4cd` | `DIAS_BAJO_MINIMO_LEGAL_ABORTO`(3) + `TP_FAMILIAS_MULTIPLES`(2) + `TP_FUENTE_MINORITARIA`(1) + `FIRMA_REUSO_RECOMPRIMIDA`(1) | **7** | 3 | **SOSPECHOSO** |
| `d5b72739` | `AF01`(3) + `DX_FORMATO_LONGITUD`(1) | **4** | 2 | **SOSPECHOSO** |
| `717d3aad` | `TP_FAMILIAS_MULTIPLES`(2) + `DX_FORMATO_LONGITUD`(1) | 3 | 2 | REVISAR |
| `9603c77b` | `TP_FAMILIAS_MULTIPLES`(2) + `TP_FUENTE_MINORITARIA`(1) + `FIRMA_REUSO_RECOMPRIMIDA`(1) | 4 | 2 | REVISAR *(sin determinista ≥3)* |
| `5c66d97e` | `TP_FAMILIAS_MULTIPLES`(2) + `TP_FUENTE_MINORITARIA`(1) + `DX_CAPITULO_INCOHERENTE`(1) | 4 | 2 | REVISAR *(sin determinista ≥3)* |
| `8b682a83` | `TP_FAMILIAS_MULTIPLES`(2) + `TP_FUENTE_MINORITARIA`(1) | 3 | 1 | REVISAR |
| `e0ee54fd` | `AF01`(3) | 3 | 1 | REVISAR |
| `9dcb4e35`, `ed2a4eeb`, `d08cba3f`, `99d74f47`, `758d3aff` | ninguno | 0 | 1–2 aplicables | **SIN_COBERTURA** (5 documentos) |
| **14 legítimos** | ninguno acusatorio | 0 | — | 4 × `SIN_SEÑALES` · **10 × `SIN_COBERTURA`** |

Resumen del modelo sobre este corpus:

| | |
|---|---|
| `SOSPECHOSO` | **2/12 adulterados** · **0/14 legítimos** |
| `SOSPECHOSO` + `REVISAR` (llegan a revisión humana con evidencia) | **7/12 (58 %)** · **0/14** |
| Adulterados con **≥2 familias** coincidiendo | 4/12 — pero de solo **2 titulares distintos** |
| Adulterados que el motor no puede ni mirar | **5/12**, todos por cobertura (1–2 familias aplicables) |
| Legítimos con veredicto limpio **con sentido** | **4/14**. Los otros 10 son `SIN_COBERTURA` |
| A nivel de **titular** (5 titulares entre los 12 adulterados) | 4/5 con al menos una señal; 1 titular (3 documentos) invisible |

**Cómo NO leer esta tabla.** «0 falsos positivos» sobre 14 legítimos de los cuales 11 son
incapacidades y 3 son otro tipo de documento, con la familia de más recall medida contra **3**
documentos, no es una precisión estimada: es un **no-desmentido**. Con estos tamaños, el intervalo de
confianza de cualquiera de estos porcentajes cubre casi todo el rango útil.

### Puerta de promoción a `BLOQUEA`

Un check pasa de `ALERTA` a `BLOQUEA` cuando, y solo cuando, se cumplen las cinco condiciones:

1. es **determinista** y no tiene umbrales elegidos a ojo;
2. **≥10 casos confirmados** por el área, con etiqueta no contradictoria;
3. **0 falsos positivos sobre ≥100 documentos legítimos de la misma clase de aplicabilidad** (no
   vale medir un check de fuentes contra escaneos: ahí es `NO_APLICABLE`);
4. sus insumos vienen de la **radicación** y no de inferencia (crítico para `id_paciente`: está
   demostrado que una agrupación mala fabrica positivos espurios en todo el bloque de reuso);
5. queda escrito **quién** autoriza el bloqueo y **cómo se apela**.

Candidatos naturales, en orden: `TP_ALFA_TEXTO_NO_UNIFORME` + `TP_PARCHE_BLANCO` disparando juntos ·
`FONDO_REUSO_CROSS_PACIENTE` · `FIRMA_REUSO_EXACTO_CROSS_PACIENTE` · `AF01` con desfase grueso y
confirmable en la capa de texto del PDF.

### Calibración obligatoria antes de encender cualquier check en producción

La misma disciplina que la familia de días propuso para su check histórico, generalizada:
**medir la tasa de marcado del check sobre el propio histórico de radicaciones ya pagadas**, que se
asume legítimo. Si un check marca más del ~1 % de ese histórico, **no se enciende**. Eso convierte
«¿sirve?» en un número en vez de una opinión, y es lo único que puede sustituir a un corpus grande
mientras no exista.

---

## 5. Integración en el código actual (propuesta, sin implementar)

### 5.0 Seis cosas que hay que arreglar ANTES, porque el motor las hereda

Todas salieron de esta fase (que fue de solo lectura) y **dos de ellas son defectos vivos hoy**:

| # | Dónde | Qué pasa | Por qué bloquea al motor |
|---|---|---|---|
| 1 | `extract._normalize_cie10` / `_extract_cie10` | descartan la **`X` de relleno** del catálogo colombiano (un código de 3 caracteres + `X` queda en 3 caracteres) | `erp.Lookups.diagnostico_por_codigo` compara sin punto contra un catálogo que guarda la `X`: **el ERP hoy acusaría de «diagnóstico inexistente» a documentos legítimos**. Medido: 2 documentos del corpus. Además, sin la `X` el check de longitud produce **1 falso positivo** sobre un legítimo |
| 2 | `extract.py`, patrón `duraci[oó]n\b[^\d]{0,10}(\d{1,3})` | lee **`dias = 202`** en un documento **legítimo** que no imprime días; 202 pasa el rango 1..540 y entraría a `lp_ausentismos_ia` | Es el insumo del único disparo de `DIAS_LARGOS_SIN_DX_VERIFICABLE` (§3, contradicción 3). Un check alimentado con un valor inventado no es débil: es aleatorio |
| 3 | `extract.normalizar_fechas()` | **re-deriva `fecha_fin`** cuando no cuadra con inicio+días y **no deja marca** (el aviso `fecha_inicio_calculada` es solo para el inicio) | **El pipeline borra exactamente la evidencia** que busca `AF01`. Hace falta conservar `fecha_fin_leida` y una **procedencia por campo** (`impreso` / `derivado` / `no_leido`) |
| 4 | `ocr.py` | devuelve una sola cadena (`_combinar_paginas`); RapidOCR **sí** produce cajas y se descartan | Sin coordenadas, emparejar rótulo↔celda es heurística de orden. Medido: hay formatos donde **cada valor precede a su rótulo**, y el ancla devuelve la fecha fin como si fuera el inicio |
| 5 | ningún módulo lee la **capa de texto** del PDF | el pipeline rasteriza y OCR-ea siempre | Es lo más barato con mayor retorno: en el único caso de la familia de días, el diagnóstico **estaba** en la capa de texto y **no** en la salida de RapidOCR. Y permite marcar `confirmable_sin_ocr`, que es la diferencia entre `ALERTA` y `BLOQUEA` |
| 6 | inventario de imágenes (`estructura.paginas[].imagenes[]`) | **incompleto**: no recorre Form XObjects. Medido: dos archivos byte-idénticos reportan `0` vs `2` y `0` vs `12` imágenes | Toda la familia de firma/reuso depende de ese inventario. La solución es `page.get_objects(filter=IMAGE, max_depth=15)` |

### 5.1 Nuevo subpaquete `incapacidad_ocr/falsedad/`

```
incapacidad_ocr/falsedad/
├── __init__.py         evaluar(doc) -> Veredicto        ← única entrada pública
├── contexto.py         Contexto: capa de texto, cajas OCR, id_paciente de la radicación,
│                       emisor, índice de hashes, catálogos (o su ausencia declarada)
├── lectura.py          UN solo lector por campo, con procedencia + confianza
│                       (fechas/días/CIE-10). Reemplaza los 4 lectores de las sondas
├── checks_fechas.py    AF01..AF06
├── checks_dx.py        DX_*
├── checks_dias.py      DIAS_*
├── checks_pdf.py       TP_*        (pypdfium2: fuentes, alfa, paths, z-order, metadatos)
├── checks_recursos.py  C1..C10     (hashes de imagen, roles geométricos, pHash/dHash)
├── registro.py         CHECKS: id -> {familia, peso, tipo, requiere, severidad, activo}
└── score.py            combinar(resultados) -> Veredicto
```

Contrato mínimo:

```python
Chequeo   = (id, familia, estado: DISPARA|OK|NO_APLICABLE|NO_VERIFICABLE|SIN_INSUMO,
             peso, evidencia: dict SIN PII, mensaje_humano: str)
Veredicto = (veredicto, score, checks: list[Chequeo],
             familias_aplicables: int, familias_totales: int, version_reglas: str)
```

Reglas de construcción, todas heredadas de la medición:

- **Los umbrales viven en un único diccionario por familia**, no escondidos en el cuerpo del código
  (las sondas ya lo hacen así). Cada uno con un comentario que diga de dónde salió.
- **`registro.py` es la fuente de verdad de pesos y severidades**, y `version_reglas` viaja con cada
  veredicto. Sin eso no se puede recalibrar sin invalidar el histórico de decisiones.
- **La evidencia se guarda sin PII**: coordenadas (bbox), hashes, longitudes, conteos, desfases en
  días. Nunca el recorte, nunca la descripción del diagnóstico, nunca el nombre.
- **Los checks que necesitan un catálogo devuelven `SIN_INSUMO`, jamás una lista embebida.** Está
  medido que un catálogo parcial convierte códigos raros pero válidos en acusaciones de falsedad.
- **Autotest sintético obligatorio por check acusatorio** (documentos fabricados con `fpdf2`/`PIL`,
  cero PII). Es lo único que distingue «el corpus no tiene casos» de «el check está roto»: la familia
  de firma ya lo demostró con 4/4.

### 5.2 Campos nuevos en `lp_ausentismos_ia` y una tabla de alertas

```sql
ALTER TABLE lp_ausentismos_ia
  ADD COLUMN falsedad_veredicto  VARCHAR(20)  NULL,  -- SOSPECHOSO|REVISAR|SIN_SENALES|SIN_COBERTURA
  ADD COLUMN falsedad_score      SMALLINT     NULL,
  ADD COLUMN falsedad_cobertura  VARCHAR(20)  NULL,  -- 'n/5' familias que pudieron opinar
  ADD COLUMN falsedad_checks     TEXT         NULL,  -- JSON compacto: id -> estado/peso/evidencia
  ADD COLUMN falsedad_version    VARCHAR(20)  NULL,  -- version_reglas con la que se evaluó
  ADD INDEX idx_ia_falsedad (falsedad_veredicto, falsedad_score);

-- Espeja lp_alertas_documentacion, que no sirve tal cual (documentos_faltantes es NOT NULL
-- y su semántica es «faltan soportes», distinta de «el documento se contradice»).
CREATE TABLE lp_alertas_falsedad (
  id               INT AUTO_INCREMENT PRIMARY KEY,
  id_ausentismo_ia INT          NULL,
  check_id         VARCHAR(48)  NOT NULL,
  familia          VARCHAR(32)  NOT NULL,
  severidad        VARCHAR(10)  NOT NULL,          -- AVISO|ALERTA|BLOQUEA
  peso             SMALLINT     NOT NULL,
  evidencia        VARCHAR(500) NOT NULL,          -- sin PII
  estado           VARCHAR(20)  NOT NULL DEFAULT 'PENDIENTE',
  creado_en        TIMESTAMP    NOT NULL DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB;

-- El índice de hashes que convierte la familia de reuso de "casi ciega" en útil.
-- Se llena SOLO con lo que ya entra por radicación: no hay que pedirle nada al cliente.
CREATE TABLE lp_recursos_graficos (
  id               INT AUTO_INCREMENT PRIMARY KEY,
  id_ausentismo_ia INT          NULL,
  idlpempleado     INT          NULL,
  sha256_stream    CHAR(64)     NOT NULL,
  sha256_pixeles   CHAR(64)     NOT NULL,
  phash64          BIGINT UNSIGNED NOT NULL,
  dhash64          BIGINT UNSIGNED NOT NULL,
  rol              VARCHAR(24)  NOT NULL,          -- FIRMA_SELLO_CAND|FONDO_PAGINA|MEMBRETE|...
  ancho_px         SMALLINT     NULL,
  alto_px          SMALLINT     NULL,
  creado_en        TIMESTAMP    NOT NULL DEFAULT CURRENT_TIMESTAMP,
  INDEX idx_rg_stream (sha256_stream),
  INDEX idx_rg_pixeles (sha256_pixeles),
  INDEX idx_rg_rol (rol)
) ENGINE=InnoDB;
```

`lp_recursos_graficos` es, con diferencia, **el ítem de mayor retorno de toda esta lista**: es la
única carencia del motor que se resuelve **sin pedirle nada al cliente**, porque se autoalimenta con
las radicaciones que ya entran. Está medido que el poder de un check de reuso crece con el tamaño del
archivo contra el que cruza: con 26 documentos la probabilidad de colisión es ~0, y contra decenas de
miles de radicaciones una firma copiada colisiona casi con certeza.

### 5.3 Dónde se llama

- **`batch.py`**, después del OCR/extracción del documento base y **antes** de
  `db.insertar_staging` — mismo sitio donde hoy corre `erp.validar_documentacion`. Se evalúa **solo
  el documento base** (el que ya se OCR-ea), no los adjuntos.
- **`webapp.py`**: `POST /api/procesar` devuelve el veredicto en el preview; `POST /api/registrar` lo
  persiste; `GET /api/staging?falsedad=SOSPECHOSO&orden=score` alimenta la bandeja.
- **`erp.mapear_a_staging()`** no cambia de responsabilidad: el motor de falsedad es un módulo
  paralelo que produce un veredicto, no un campo del mapeo.
- **Zona de ingesta**: un `SOSPECHOSO` va a `2_revisar/datos_por_revisar/`. **No** se crea una carpeta
  `sospechosos/`: expondría una acusación en el nombre de una ruta que ve todo el equipo, y la
  invariante «cada archivo termina en exactamente UNA zona» se mantiene.

### 5.4 Cómo se muestra

**Ficha de revisión** (panel nuevo «Verificación documental», debajo del formulario editable):

- Insignia del veredicto y el score. `SIN_COBERTURA` se pinta **gris, nunca verde**, con el texto
  «no verificable: N de 5 verificaciones no se pudieron aplicar a este documento».
- Lista de checks que dispararon, cada uno con **una frase en lenguaje llano** y su evidencia:
  las tres cifras de fechas resaltadas con el desfase calculado; el **recuadro (bbox)** de la zona
  escrita con la tipografía minoritaria; el mínimo legal citado con su artículo. La evidencia es lo
  que hace la revisión rápida — está medido que un revisor confirma o descarta en segundos mirando
  ese recuadro.
- Lista **colapsada** de lo que no se pudo verificar y por qué («documento fotografiado: sin fuentes
  que comparar», «falta el catálogo CIE-10»). Es lo que evita la falsa sensación de control.
- Al aprobar un `SOSPECHOSO`: **campo de motivo obligatorio** y registro de quién aprobó. Esa traza
  es lo que hace el motor defendible frente a un reclamo, y es la única razón por la que se puede
  operar sin `BLOQUEA`.

**Bandeja**: filtro por veredicto y orden por score descendente; columna con el nombre corto de las
familias que dispararon. Nunca autorrechazar, nunca ocultar un caso por el veredicto.

---

## 6. LIMITACIONES Y DATOS QUE FALTAN

Esto va antes que cualquier cifra buena que aparezca arriba.

### 6.1 El corpus es demasiado pequeño y su etiquetado está roto

- **31 documentos: 15 adulterados y 16 legítimos.** Para calibrar un umbral y afirmar una precisión
  hacen falta dos órdenes de magnitud más.
- **2 pares byte-idénticos con etiquetas opuestas** (sha256 confirmado, no parecido visual) y **1
  archivo adicional que comparte titular con uno de la clase contraria** → **5 documentos (16 % del
  corpus) en cuarentena**, excluidos de toda métrica. Uno de esos pares es **el único ejemplo de
  `TIPOGRAFIA_MIXTA`** y el único donde dos familias acumulan evidencia fuerte.
- **3 de los 15 adulterados llegaron sin motivo declarado** (celda vacía). No se puede saber qué
  debería haber disparado en ellos; casualmente son los que menos cobertura tienen.
- **Los 12 adulterados evaluables provienen de solo 5 titulares.** El número de **casos
  independientes** es 5, no 12. Y hay un titular con 3 documentos que **ninguna familia detecta**.
- **Las clases usan convenciones de nombre distintas.** Un clasificador que lea el nombre de archivo
  acertaría el 100 % sin abrir el documento. Nada de lo que se compute puede tocar el nombre.
- **«0 falsos positivos sobre 14 legítimos» está inflado por composición**: 11 son incapacidades, 1
  es una historia clínica y 2 son permisos (que varias familias excluyen por diseño, porque no llevan
  diagnóstico). Y en `tipografia_pdf` la precisión está medida contra **3** documentos legítimos.
- **La proporción del corpus (≈50 % adulterados) no es la de producción.** Si la tasa real fuese
  0,5 %, un check con 5 % de falsos positivos produciría diez veces más ruido que señal. Sin la
  prevalencia real, ningún umbral es defendible (§7, pregunta 10).

### 6.2 Familias no evaluables por falta de datos externos

| Falta | Bloquea | Impacto medido |
|---|---|---|
| **`ASTGU.lpdiagnosticos`** (export completo: `codigo`, `descripcion`, `estado/activo`, `fechamodificacion`) | `DX_INEXISTENTE`, `DX_NOMBRE_DISTINTO` | `no_verificable` en **31/31**. Son los dos checks que materializan lo que el cliente revisó a mano, y valen **0/12** |
| **`ASTGU.lpausentismos`** (≥2 años, ≥5.000 certificados iniciales, con `Numerodias`, `idlpdiagnosticos`, `prorroga`, `idlpausentismo_inicial`, IPS/EPS emisora) | `DIAS_VS_DX_RANGO_HISTORICO` (el check central de su familia), línea base de fuentes por plantilla/IPS, convención de fecha fin por emisor, prórrogas solapadas, fechas reutilizadas | `SIN_INSUMO` en **31/31**. Y hay una advertencia previa del propio repo: al estudiar ese mismo histórico para el nivel de incapacidad se concluyó que **ni los días ni el diagnóstico predicen limpiamente**. Es decir: puede que la señal **no exista**. Por eso el check nace desactivado con calibración obligatoria |
| **Índice de hashes del histórico de radicaciones** | `FIRMA_HISTORICO_ERP` y el poder real de C1–C4 | **26/26 no evaluables**. Se resuelve solo, con `lp_recursos_graficos` (§5.2) |
| **RETHUS** | validar nombre ↔ registro ↔ habilitación del profesional | `FIRMA_ID_INCOHERENTE` es evaluable en **1 de 26** documentos |
| **Extractor fiable de IPS/EPS emisora** | `RECURSO_REUSO_CROSS_EMISOR` | **26/26 no evaluables**: hoy el campo devuelve fragmentos de dirección |
| **Validación jurídica fechada** de la tabla de pisos legales (CST 236/237, Ley 2114/2021) | `DIAS_BAJO_MINIMO_LEGAL_ABORTO`, `DIAS_VS_MINIMO_LEGAL_MATERNIDAD` | El check corre, pero su umbral es una norma que alguien del cliente tiene que firmar y fechar |
| **~100 legítimos con capa de texto**, incluyendo el flujo «plantilla Word rellenada a mano» | medir de verdad `TP_FAMILIAS_MULTIPLES` | Es el generador de falsos positivos que este corpus **no contiene** y que la vida real produce a diario |

### 6.3 Limitaciones estructurales, que no se arreglan con más código

1. **La autenticidad de una firma está fuera de alcance.** Es peritaje grafológico y requiere
   muestras indubitadas que el sistema no tiene ni tendrá. Solo son detectables el **reuso** y la
   **incoherencia interna**. Cualquier expectativa distinta hay que desmontarla con el cliente.
2. **Los checks de reuso son casi ciegos sobre un documento aislado.** Su poder es proporcional al
   tamaño del archivo contra el que cruzan. No es un defecto de implementación.
3. **El motor es ciego en el píxel.** 13 escaneos/fotos puros de 26 (más 3 JPEG sueltos): ahí la
   edición se hizo dentro del mapa de bits y ninguna familia actual puede verla.
4. **El eslabón débil es la LECTURA, no la regla.** Las cinco familias coinciden. Cuatro de los
   cuatro errores encontrados durante la construcción de la familia de fechas fueron de lectura del
   número de días, no de aritmética; el campo CIE-10 del extractor difiere del código impreso en 10
   de 31 documentos y en 6 devuelve algo que no es un diagnóstico; los días de un legítimo se leen
   como 202. **Mientras el pipeline no exponga procedencia por campo, coordenadas del OCR y la capa
   de texto del PDF, cada check nuevo hereda ese ruido.**
5. **El motor no puede opinar sobre 3 de 26 documentos** (ninguna familia aplicable) y solo puede
   dar un limpio con sentido en 4 de 14 legítimos. La cobertura, no el recall, es la métrica que hay
   que perseguir primero.

---

## 7. Preguntas abiertas para el cliente

Concretas y respondibles. Las tres primeras desbloquean el corpus; las tres siguientes, familias
completas.

1. **Las 5 filas en ROJO de la tabla de motivos: ¿qué significa el color?** Está medido que el rojo
   **no** equivale a «sin motivo»: 3 filas rojas tienen la celda vacía pero **2 filas rojas sí traen
   motivo escrito**, y las filas rojas se concentran en 2 trabajadores (uno con 2 documentos, otro
   con 3, y ese segundo trabajador tiene **todas** sus filas en rojo). Hipótesis a confirmar o
   descartar: (a) caso aún en investigación / no confirmado; (b) caso ya escalado o reportado; (c) el
   analista no pudo verificar; (d) marca «reincidente» por trabajador. **La respuesta cambia si esas
   5 filas se pueden usar como verdad.**

2. **Las 3 filas sin motivo: ¿son adulteradas confirmadas, y por qué evidencia?** Si se confirmaron
   por una vía externa (la EPS o la IPS negó haber expedido el documento, el médico no existe, el
   trabajador lo admitió), **esa vía es más valiosa que cualquier check** y hay que registrarla. Si
   están pendientes de clasificar, deberían salir de la clase «adulterada» hasta que se clasifiquen.
   Son justamente los documentos donde el motor tiene menos cobertura.

3. **Los 2 pares byte-idénticos: ¿cuál etiqueta es la correcta?** Un documento **no puede** ser a la
   vez adulterado y legítimo. Recomendación con evidencia: el par `28c4a946` presenta parches blancos
   opacos sobre la imagen original, texto semitransparente estampado encima en esas mismas
   coordenadas, y una contradicción aritmética de fechas confirmada en la capa de texto del PDF; para
   ese par proponemos resolver a favor de **adulterado**. Para el par `d86ae595`, la pregunta
   concreta es: **¿es el mismo archivo archivado dos veces por error, o el trabajador lo radicó dos
   veces?** (Es el caso que nos impide activar el check de reuso de fondo como bloqueante.)
   Pregunta relacionada: ¿la carpeta `Reales/` significa «verificado legítimo» o «no se detectó nada
   / no se revisó»? Cambia por completo lo que valen los 14 legítimos como control negativo.

4. **`cheklistradicaciones`: semántica exacta de dos campos.** Del catálogo de 64 EPS, 19 traen el
   JSON y 45 traen el literal `'I'` (que es como el export escribe NULL). Medido: `tipo_envio = 1` ⇒
   `max(archivo) = 1` en 21/21 combinaciones y `tipo_envio = 2` ⇒ `max(archivo) ≥ 2` en 47/47, de
   donde deducimos «1 = todo en un archivo / 2 = archivos separados». Falta confirmar:
   **(a) ¿qué significa `tipo_envio = 0`?** ¿«sin configurar» o «no se radica»?
   **(b) ¿`archivo = 0` es «sin asignar» o «va en el archivo 0»?** (aparece junto a documentos que
   sí se exigen).
   **(c) ¿qué codifica `medioradicacion` (0/1/2)?** Es constante por EPS, nunca mezcla valores.
   **(d) las 45 EPS con `'I'`: no exigen nada, o simplemente no está configurado todavía?** Hoy para
   esas se sigue usando `erp.REQUISITOS_DEFAULT`, y si la respuesta es «no configurado» estamos
   exigiendo lo que no toca.

5. **¿Podemos recibir `lpdiagnosticos` y `lpausentismos`?** Como **archivo local** (CSV UTF-8 o dump),
   no como API; el motor no sale de la máquina. Concretamente:
   - `lpdiagnosticos`: `codigo`, `descripcion`, y `estado`/`activo` + `fechamodificacion` si existen.
   - `lpausentismos`: certificados **iniciales** (`prorroga = 0 AND idlpausentismo_inicial IS NULL`)
     de los últimos ≥2 años, con `Numerodias`, `idlpdiagnosticos`, `idlptipoausentismo`, IPS/EPS
     emisora y fecha de radicación. Sin PII de más: no hacen falta nombres ni cédulas.
   Sin el primero, 2 de los 8 motivos de la taxonomía valen 0. Sin el segundo, la familia de días no
   tiene check central y ninguna familia puede tener línea base por emisor.

6. **Sobre el catálogo CIE-10, tres preguntas que deciden si un check se queda o se retira.**
   (a) ¿De qué **versión/año** de la CIE-10 salieron las descripciones? Cambiaron entre las
   actualizaciones de 2010 y 2018, y sin eso `DX_NOMBRE_DISTINTO` no se puede calibrar.
   (b) ¿**Existen códigos de 3 caracteres** en el catálogo? Si existen, `DX_FORMATO_LONGITUD` **hay
   que retirarlo**, no ajustarlo. (`SELECT LENGTH(REPLACE(codigo,'.','')) n, COUNT(*) FROM
   lpdiagnosticos GROUP BY n;`)
   (c) ¿Hay **códigos retirados/inactivos** y cómo se marcan? Un código presente pero retirado es
   «no existe» para el analista y «existe» para una consulta ingenua.

7. **La fecha «Fin» del certificado: ¿último día de incapacidad o día de reintegro?** El corpus
   sugiere el primero (los 4 legítimos con las tres cifras impresas dan desfase 0), pero **el único
   acierto propio de la familia de fechas falla por exactamente un día**, que es lo mismo que
   produciría un emisor con la otra convención. Necesitamos saber **si hay EPS o IPS que impriman el
   día de reintegro**, para mantener una tabla por emisor. Sin esa respuesta, un desfase de +1 puede
   ser fraude o puede ser un formato.

8. **¿Quién valida y fecha la tabla de pisos legales?** (CST art. 237 para aborto: 2–4 semanas;
   art. 236 mod. Ley 2114/2021 para maternidad: 18 semanas, 20 si es múltiple.) Necesitamos nombre,
   área (SST o jurídica) y fecha de vigencia. Advertencia medida: **el margen es cero** — un
   documento legítimo del corpus trae exactamente el mínimo legal, así que un dígito mal leído
   produciría una alerta sobre una incapacidad por aborto.

9. **¿Tienen documentos confirmados LEGÍTIMOS del flujo «un auxiliar rellena una plantilla Word y la
   exporta a PDF», con dos o más tipografías?** Es el generador de falsos positivos del check que hoy
   carga todo el recall de tipografía, y este corpus no contiene ni uno. Con ~100 de esos podríamos
   medir el check de verdad; sin ellos, va a producir ruido en producción y no podemos anticipar
   cuánto.

10. **¿Cuál es la tasa real de adulteración y cuánto cuesta cada tipo de error?** ¿De cada 100
    incapacidades radicadas, cuántas resultan adulteradas? ¿Qué cuesta más: pagar una falsa que pasó,
    o retener el pago de una legítima durante N días? Sin esos dos números el umbral del veredicto es
    una preferencia nuestra, no una decisión de negocio — y es la decisión que fija cuánta cola de
    revisión está dispuesto a absorber el equipo.

11. **¿Hay acceso a RETHUS**, aunque sea consulta manual, para validar nombre ↔ registro médico ↔
    habilitación en la fecha de expedición? Es el único camino para pasar de «el sello se contradice
    con el texto» a «ese profesional no existe o no estaba habilitado».

12. **¿Cuál es el `id_paciente` autoritativo de una radicación?** En producción la nomenclatura de
    ingesta lo trae, pero está **medido** que si esa clave se infiere mal, **todo el bloque de checks
    de reuso fabrica positivos espurios**. Necesitamos confirmar que la cédula de la radicación es
    autoritativa y qué hacer cuando el OCR del documento lee otra distinta.
