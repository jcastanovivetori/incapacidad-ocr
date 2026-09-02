# Familia `dias_vs_diagnostico` — plausibilidad de los dias segun el diagnostico

Cubre el motivo declarado por radicaciones **«NO CONCUERDA EL NUMERO DE DIAS CON EL
DIAGNOSTICO»** (`DIAS_VS_DIAGNOSTICO` en la taxonomia de `ground_truth.json`).

Todo lo de aqui es **100% local**: se leen los artefactos ya producidos en
`dataset-falsedad/` y la capa de texto de los PDF con `pypdfium2`. No se llama a ningun
servicio ni modelo remoto y no se modifico nada del paquete `incapacidad_ocr`.

> **Aviso PII.** Este informe y `medicion.json` son artefactos derivados de historia
> clinica (Ley 1581). No traen codigos CIE-10 completos: se habla de **bloques** y
> **capitulos**. La sonda tampoco los imprime salvo con `--con-codigos` (depuracion local).

---

## 1. Resumen ejecutable

```bash
<repo>/.venv/Scripts/python.exe \
  <dataset-falsedad>/senales/dias_vs_diagnostico/probe.py --json
```

| | |
|---|---|
| Corpus utilizable | **26** documentos (12 falsas + 14 reales) — se excluyen los **5 en cuarentena** |
| Pares `(diagnostico, dias)` legibles | **10 / 26 (38%)** ← el techo real de esta familia hoy |
| Falsas con SOSPECHA | **1 / 12** |
| Falsas del motivo `DIAS_VS_DIAGNOSTICO` detectadas | **1 / 1** |
| Reales marcadas por error (falsos positivos) | **0 / 14** |
| Reales en AVISO / en REVISION | 0 / **1** |
| Check central de la familia (percentiles del historico) | **SIN_INSUMO en 31/31**: no hay historico del ERP en esta maquina |

**Severidad recomendada: `ALERTA` para un unico check (piso legal de aborto) y
`DESACTIVADO` para el resto de la familia.** Justificacion en §6.

---

## 2. Los checks

| id | afirma | determinista | evaluable hoy | insumo que falta |
|---|---|---|---|---|
| `DXDIAS_PAR_LEGIBLE` | que el documento **permite** opinar: hay dias y hay CIE-10 de confianza ALTA | si | si | — |
| `DIAS_BAJO_MINIMO_LEGAL_ABORTO` | dias por debajo del **minimo legal** del bloque O00–O08 | si | **si** | validacion juridica de la tabla |
| `DIAS_VS_MINIMO_LEGAL_MATERNIDAD` | dias distintos de la **licencia legal** de maternidad (bloque O80–O84 / Z37) | si | si (0 casos) | validacion juridica; casos reales |
| `DIAS_LARGOS_SIN_DX_VERIFICABLE` | incapacidad prolongada que **ningun check** puede validar → ojo humano | si | si | — (no afirma falsedad) |
| `DIAS_VS_DX_RANGO_HISTORICO` | dias fuera del rango p05–p95 de **ese** CIE-10 en el historico del ERP | no (heuristico) | **NO** | `ASTGU.lpausentismos` (+ `lpdiagnosticos`) |

### 2.0 Antes de cualquier check: leer el par `(diagnostico, dias)`

Esto no es un detalle de implementacion, es **la mitad del problema de esta familia**.

1. **Dias.** Del JSON de OCR, `incapacidad.incapacidad.dias`. Si viene vacio y estan las
   dos fechas, `dias = (fin − inicio) + 1`. Se exige `1 ≤ dias ≤ 540` (regla de dominio ya
   escrita en el repo).
2. **CIE-10, con ancla y por orden de confianza** (`probe.cie_anclado`):
   1. **capa de texto del PDF** (`pypdfium2`, `get_textpage().get_text_range()`) buscando el
      primer codigo que aparece **despues** de una etiqueta (`DX Principal:`,
      `Diagnostico:`, `Diagnostico que genera la incapacidad:`, `Diagnostico(s)`) →
      confianza **ALTA**;
   2. el texto de **RapidOCR** con la misma ancla → confianza **ALTA**;
   3. el campo `diagnostico.cie10` del extractor **sin ancla** → confianza **BAJA**.
   El regex tolera el kerning del PDF y el ruido de OCR (`M 5 4. 5` → `M54.5`).
3. **Prorroga.** `pr[oó]rroga\s*:?\s*(si|no)` sobre el texto. Un certificado que se declara
   prorroga **no** se compara contra pisos ni contra la distribucion de certificados
   iniciales.

Los checks de la familia **solo actuan con confianza ALTA**. Es una decision costosa (baja
la cobertura de 17/26 a 10/26) y es la correcta, por dos hallazgos del corpus:

- En un documento el extractor devolvio como diagnostico un codigo que en realidad salio de
  la **cedula del medico** mal leida por el OCR (`C.C.1073168481` → `C.Q073168481` →
  `Q07.3`). Sin ancla, este check habria opinado sobre un numero de cedula. Ese documento es
  justamente el unico con motivo `DIAS_VS_DIAGNOSTICO`: sin el anclaje, la familia habria
  "acertado" comparando dias contra basura.
- En otros documentos el campo del extractor trae literalmente `IDENTI`, `FECHA` o `0039`
  (la letra `O` leida como cero).

> **Hallazgo colateral para el pipeline** (no se toca en esta fase, solo se reporta): en ese
> mismo documento **RapidOCR se salto la linea completa del `DX Principal`**, que si esta en
> la capa de texto del PDF. Es decir, el motor de falsedad necesita leer la **capa de texto**
> cuando existe, no solo el raster OCR-eado. Sin eso, esta familia pierde su unico caso.

### 2.1 `DXDIAS_PAR_LEGIBLE` — compuerta (determinista)

**Afirma:** nada sobre falsedad. Dice si el documento **habilita** a la familia.

**Como se calcula:** `NO_APLICA` si el documento es permiso/vacaciones (no llevan
diagnostico por diseno); `NO_EVALUABLE` si falta `dias`, falta CIE-10 o el CIE-10 no llega a
confianza ALTA; `OK` en otro caso.

**Por que es un check y no una utilidad:** es la metrica honesta de la familia. Cualquier
recall que se reporte esta acotado por ella. Hoy vale **10/26 (38%)**.

### 2.2 `DIAS_BAJO_MINIMO_LEGAL_ABORTO` — determinista, **el unico evaluable hoy**

**Afirma:** el certificado declara **menos dias que el minimo que fija la ley** para ese
bloque diagnostico, y no se declara prorroga.

**Como se calcula:**
1. leer el par `(CIE-10, dias)` con confianza ALTA (§2.0);
2. quitar el punto del codigo y mirar si empieza por `O00…O08` (bloque **«embarazo
   terminado en aborto»**);
3. si el texto declara `Prorroga: SI` → `NO_APLICA` (el piso aplica al **episodio**, no a
   cada certificado);
4. `dias < 14` → **SOSPECHA**; `dias > 28` → AVISO; en medio → OK.

**Ancla del rango (esto es lo importante: no es clinica inventada, es norma escrita):**
CST **art. 237** — la trabajadora que sufre aborto o parto prematuro no viable tiene derecho
a **dos a cuatro semanas** de descanso remunerado → **14 a 28 dias**. La tabla vive en
`probe.PISOS_LEGALES` con el texto de la norma al lado, fechada y en un solo lugar.

**Lo que le falta:** que el area de **SST/juridica del cliente valide la tabla** y su
vigencia (las licencias colombianas se han movido varias veces: Ley 2114 de 2021 es la
ultima). La tabla debe versionarse con fecha, no quedar clavada en el codigo para siempre.

**Advertencia de alcance:** este check **no** es "dias vs diagnostico" en general. Cubre 9
categorias CIE-10 de las ~14.000 del catalogo. No sabe nada de una lumbalgia con 30 dias.

### 2.3 `DIAS_VS_MINIMO_LEGAL_MATERNIDAD` — determinista, sin casos hoy

**Afirma:** los dias no corresponden a la licencia de maternidad legal.

**Como se calcula:** igual que 2.2, con bloque `O80…O84` / `Z37` y rango **126–140 dias**
(CST art. 236 mod. Ley 2114 de 2021: **18 semanas**; 20 semanas si es parto multiple).
Desviacion → **AVISO**, nunca SOSPECHA.

**Por que solo AVISO:** la licencia se puede **fraccionar** (hasta una semana preparto), el
parto pretermino **suma** la diferencia (puede pasar de 140) y un codigo de parto tambien
aparece en certificados de **complicacion posparto**, que si son cortos y legitimos. Es
decir: es el mismo tipo de regla que 2.2 pero con lecturas legitimas en ambas colas.

**Evidencia del corpus:** un documento **real** trae 126 dias exactos con codigo del bloque
O80–O84 → el check da OK. Es la unica confirmacion que tenemos de que el rango esta bien
puesto, y es una sola observacion.

### 2.4 `DIAS_LARGOS_SIN_DX_VERIFICABLE` — determinista, **no afirma falsedad**

**Afirma:** "esta incapacidad es larga (`dias ≥ 30`) y no pude leer su diagnostico con
confianza, asi que **ninguna** senal de esta familia la esta vigilando".

**Como se calcula:** `dias ≥ 30` y confianza de CIE-10 distinta de ALTA → `REVISION`.

**Por que existe:** el riesgo economico se concentra en las incapacidades largas y es
exactamente ahi donde el OCR falla mas (documentos escaneados, sin capa de texto). Sin este
check, la familia devuelve un silencio que se lee como "todo bien". Su salida es `REVISION`,
un estado distinto de `SOSPECHA`, y **no cuenta como deteccion ni como falso positivo** en
la medicion. Hoy marca **1 documento real** (una imagen JPEG de 202 dias sin diagnostico
legible): esa marca es correcta como "revisar a mano", y seria un falso positivo si se
presentara como indicio de falsedad. Por eso se separan los estados.

### 2.5 `DIAS_VS_DX_RANGO_HISTORICO` — heuristico, **NO evaluable hoy**

Este es **el** check de la familia: el rango esperado de dias por diagnostico, con
percentiles. Esta implementado y probado, y hoy devuelve `SIN_INSUMO` en 31/31 documentos.

**Afirma:** los dias caen fuera de lo que la **propia empresa** ha visto historicamente para
ese diagnostico.

**De donde sale el rango — 100% local, del ERP del cliente** (consulta completa y comentada
en `referencia_dias_por_dx.sql`):

1. **Fuente:** BD **ASTGU**, tabla real `lpausentismos` (`Numerodias`, `idlpdiagnosticos`,
   `prorroga`, `idlpausentismo_inicial`, `idlptipoausentismo`) unida a `lpdiagnosticos` para
   obtener el codigo CIE-10. Es la misma tabla que el repo ya estudio para el nivel de
   incapacidad.
2. **Universo:** solo **certificados iniciales** (`prorroga = 0 AND idlpausentismo_inicial IS
   NULL`), porque del documento leemos los dias de **un** certificado, no del episodio; solo
   tipos con duracion **clinica** (2 accidente de trabajo, 3 enfermedad general, 8 enfermedad
   laboral, 11 transito) — se excluyen maternidad/paternidad/prelicencia/permisos/vacaciones,
   cuya duracion la fija la ley y no el diagnostico; `Numerodias` entre 1 y 540.
3. **Granularidad con backoff:** codigo de 4 caracteres → categoria de 3 → capitulo, subiendo
   solo mientras `n < 30`. Se guarda el nivel usado.
4. **Estadisticos por celda:** `n, p05, p50, p95, p99, max` (`PERCENT_RANK()` de MySQL 8.4).
   Resultado a `referencia_dias_por_dx.json`; si el archivo no esta, la sonda devuelve
   `SIN_INSUMO` y **no inventa nada**.
5. **Regla de decision, asimetrica a proposito:**
   - `dias > p99` **y** `dias > 3 × p50` → SOSPECHA;
   - `dias > p95` → AVISO;
   - `dias < p05` → AVISO **solo** si el bloque tiene piso legal. Fuera de esos bloques, que
     un medico de menos dias que la mediana **no es sospechoso**: puede dar 1 dia por
     cualquier cosa. La cola corta solo importa cuando la ley fija un minimo — o cuando lo
     que se sospecha es que **cambiaron el diagnostico**, que es el caso del corpus.
6. **Guardas de poblacion** (dos, y la prueba de humo demostro que son imprescindibles): si
   el bloque tiene duracion fijada por norma → `NO_APLICA` (manda el piso legal, y esos tipos
   estan **excluidos** del universo historico: compararlos es un error de poblacion); si el
   documento se declara prorroga → `NO_APLICA`.
7. **Calibracion obligatoria antes de activar** (paso 3 del `.sql`): el historico se asume
   legitimo, asi que se mide **que porcentaje del propio historico marcaria** el umbral. Si
   pasa de ~1%, el check **no se activa**. Esto convierte "¿es usable?" en un numero, no en
   una opinion.

**Lo que le falta:** el historico. Hoy **no existe en esta maquina**: Docker no esta arriba
(requiere UAC), no hay ningun dump de `lpausentismos` en disco y `incapacidad-ocr/sql/init.sql`
solo trae **8 diagnosticos de demo**. Tampoco hay catalogo CIE-10 oficial local (para este
check no hace falta: los bloques se derivan del propio codigo).

**Advertencia que ya tenemos por escrito, y va en contra de este check:** el repo dejo
documentado (`CLAUDE.md` y `erp.py`, decision del 17-jul-2026) que al estudiar el mismo
historico para el **nivel de incapacidad** se concluyo que **«ni los dias ni el diagnostico
predicen el nivel de forma limpia: el mismo CIE-10 aparece con niveles distintos y los rangos
de dias se solapan»**. Eso describe una distribucion de dias por diagnostico **muy dispersa**.
Si `p05..p95` resulta ancho (p.ej. 1..30 dias para media tabla), este check tendra **recall
casi nulo** y solo cazara valores absurdos. Por eso el `.sql` incluye la consulta que mide la
dispersion (paso 4): hay que mirarla **antes** de implementar la regla, no despues.

### 2.6 Lo que deliberadamente NO se implemento

- **Rangos clinicos por diagnostico** ("una lumbalgia son 3–7 dias"). No hay fuente local ni
  norma; inventarlos convierte el motor en un generador de falsos positivos con apariencia de
  rigor, y encima expone a la empresa a discutirle el criterio a un medico tratante.
- **Un tope global de dias por capitulo CIE-10.** El corpus ya lo desmiente: hay documentos
  **reales** de **202** y **126** dias. Cualquier tope por debajo de 202 los marca.
- **`dias < mediana` como sospecha fuera de los bloques con piso legal** (§2.5, punto 5).

---

## 3. La medicion real

Corrida: `probe.py --json` (salida completa por documento en la consola y en `medicion.json`).

**Exclusiones declaradas:** los **5 documentos en cuarentena** de `manifest.csv` (2 parejas
byte-identicas con etiqueta opuesta + 1 que comparte cedula con un real) **no cuentan** en
ningun numerador ni denominador. Se corrieron igual como caso de humo y todos cayeron en
`NO_EVALUABLE` — la sonda no revienta y es determinista, pero no deciden nada.

| metrica | valor |
|---|---|
| Documentos utilizables | 26 (12 falsas, 14 reales) |
| Pares `(dx, dias)` legibles con confianza ALTA | 10 (4 falsas, 6 reales) |
| **Falsas detectadas (SOSPECHA)** | **1 / 12** |
| **Falsas del motivo `DIAS_VS_DIAGNOSTICO` detectadas** | **1 / 1** |
| **Reales marcadas por error (SOSPECHA)** | **0 / 14** |
| Reales en AVISO | 0 / 14 |
| Reales en REVISION (no es falsedad) | 1 / 14 |
| `DIAS_VS_DX_RANGO_HISTORICO` | `SIN_INSUMO` en 31/31 |

**El unico acierto:** la fila 5 de `ground_truth.json` — el unico documento del corpus cuyo
motivo declarado es `DIAS_VS_DIAGNOSTICO`. Diagnostico del bloque **O00–O08** (embarazo
terminado en aborto), certificado inicial (`Prorroga: No`), **2 dias** frente a un minimo
legal de **14**. Es un factor 7 por debajo de la norma, no un caso de frontera.

**Los otros 3 pares legibles de falsas dieron OK** — y esta bien: sus motivos declarados son
`FIRMA_MEDICO`, `DX_NOMBRE_DISTINTO` y `DX_INEXISTENTE`, que son de **otras** familias. La
familia no se esta comiendo aciertos ajenos.

### Honestidad sobre estos numeros

- **n = 1.** "1 de 1" es 100% de recall de la familia y no significa nada estadisticamente.
  Con un solo caso no hay precision, ni recall, ni intervalo de confianza que reportar.
- **¿Esta memorizado el corpus?** El **umbral no** sale del corpus: sale del art. 237 del CST.
  Pero **la eleccion del bloque si esta guiada por el corpus**: mire el unico caso, vi que era
  obstetrico y de ahi fui a la norma. Si el unico caso hubiera sido una fractura, hoy no
  habria check. Eso es exactamente lo que hay que decir: **el check no generaliza mas alla de
  los bloques con norma escrita**, y la evidencia disponible es un documento.
- **La cobertura (38%) es el limite duro.** Aunque el check fuera perfecto, no puede opinar
  sobre 16 de 26 documentos porque no hay diagnostico legible, no hay dias, o ambos.

---

## 4. Falsos positivos

**En la medicion real: 0 de 14 reales marcados como SOSPECHA.** No hay falso positivo que
explicar. Lo que si hay que explicar es **por que no los hubo**, porque la familia estuvo a un
paso de producirlos:

1. **Real con 126 dias, bloque O80–O84** (licencia de maternidad). Un check de "dias
   demasiados para el diagnostico" con cualquier tope razonable lo marca. No se marca porque
   los bloques con **duracion legal** se sacan del check de percentiles y se evaluan contra su
   propia norma, donde 126 = exacto.
2. **Real con 30 dias y `Prorroga: SI`.** No se marca porque la guarda de prorroga lo saca:
   el historico de referencia solo contiene certificados iniciales.
3. **Real con 14 dias, bloque O00–O08.** Cae en el bloque del unico check activo y **pasa
   raspando**: 14 es exactamente el minimo legal. Es la mejor noticia del informe (la norma
   coincide con la practica real del prestador) y a la vez el aviso mas claro: **el margen es
   cero**. Un dia menos, o un OCR que lea 4 donde hay 14, y es un falso positivo sobre una
   incapacidad legitima por aborto — el peor documento posible para equivocarse.
4. **Real (imagen JPEG) con 202 dias sin diagnostico legible.** Sale como `REVISION`, no como
   `SOSPECHA`. Si esa marca se presentara como indicio de falsedad, seria un falso positivo.

**Prueba de humo con percentiles sinteticos** (`referencia_dias_por_dx.json` fabricado a mano,
borrado despues; ninguno de estos numeros entra en la medicion): con percentiles a nivel de
**capitulo** y **sin** las dos guardas de poblacion, el check historico marco **2 documentos
reales** como SOSPECHA — el de maternidad y el de la prorroga. Con las guardas puestas, 0.
Eso es la familia mostrando su naturaleza: **el error dominante no es el umbral, es comparar
contra la poblacion equivocada.**

---

## 5. El confusor principal

**Que el documento no diga lo suficiente para que "dias vs diagnostico" tenga sentido.** En
orden de dano:

1. **El diagnostico no se lee (o se lee mal).** 16 de 26 documentos no llegan a un par
   legible. Y cuando se lee mal, se lee **muy** mal: un numero de cedula convertido en codigo
   CIE-10, campos con `IDENTI` o `FECHA`. Un check de plausibilidad alimentado con eso no es
   debil, es aleatorio.
2. **El certificado no es el episodio.** Prorrogas, incapacidades fraccionadas y trámites que
   se parten en varios documentos hacen que los dias del papel **no** sean los dias de la
   enfermedad. Comparar un certificado inicial de 2 dias contra la duracion tipica de un
   episodio de 20 es un falso positivo garantizado. `prorroga` / `idlpausentismo_inicial`
   existen en `lpausentismos`, pero en el **documento** solo hay a veces un `Prorroga: No`.
3. **El diagnostico no determina la duracion, ni siquiera dentro de la misma empresa.** Ya
   esta medido en este proyecto para el nivel de incapacidad (§2.5): mismo CIE-10, rangos de
   dias solapados. El mismo codigo cubre casos leves y graves, y el criterio del medico
   tratante es soberano.
4. **La direccion del fraude es ambigua.** El fraude clasico **infla** dias (cola derecha),
   pero el caso real de este corpus es lo contrario: **muy pocos dias para un diagnostico
   grave**, señal de que lo adulterado fue el **diagnostico** (plantilla reusada, codigo
   cambiado). Un check de una sola cola se pierde la mitad del fenomeno; uno de dos colas
   duplica los falsos positivos. Esta familia, en el fondo, esta detectando **incoherencia
   interna del documento**, no implausibilidad clinica.

---

## 6. Severidad recomendada

| check | estado inicial | severidad |
|---|---|---|
| `DIAS_BAJO_MINIMO_LEGAL_ABORTO` | **ACTIVO** | **ALERTA** (nunca BLOQUEA) |
| `DIAS_VS_MINIMO_LEGAL_MATERNIDAD` | ACTIVO | **AVISO** |
| `DIAS_LARGOS_SIN_DX_VERIFICABLE` | ACTIVO | **AVISO** (estado `REVISION`, no falsedad) |
| `DIAS_VS_DX_RANGO_HISTORICO` | **DESACTIVADO** | — hasta tener historico **y** pasar la calibracion del §2.5.7 |
| `DXDIAS_PAR_LEGIBLE` | ACTIVO | metrica de cobertura, sin severidad |

**Por que `ALERTA` y no `BLOQUEA`** para el piso de aborto, aun siendo determinista y con
ancla legal:

- La evidencia es **1 documento**. Bloquear con n=1 es bloquear con fe.
- El margen medido es **cero**: el real legitimo del mismo bloque trae 14 dias, el minimo
  exacto. Un error de OCR de un digito produce un bloqueo sobre una incapacidad por aborto.
  El costo de ese error no es operativo, es humano y reputacional.
- Existen lecturas legitimas del "por debajo del minimo": licencia fraccionada, certificado de
  complicacion, o un prestador que emite el primer certificado corto y prorroga despues. El
  documento no siempre permite distinguirlas.
- `ALERTA` ya logra lo que se necesita: el auxiliar mira **ese** documento. El flujo del repo
  esta hecho para eso — todo entra a `lp_ausentismos_ia` como `PENDIENTE_REVISION` y una
  persona aprueba.

**Por que `DESACTIVADO` para el check central:** hoy no tiene datos (no es que falle: no puede
correr), y cuando los tenga hay una advertencia previa y medida de que la señal puede no
existir. Que nazca apagado, con la tasa de marcado sobre el propio historico como condicion de
encendido, es la unica forma de no meter ruido en produccion.

---

## 7. Que le falta a esta familia, en orden

1. **Historico del ERP** (`ASTGU.lpausentismos` + `lpdiagnosticos`): idealmente ≥2 años y
   ≥5.000 certificados iniciales. Sin eso, el check central no existe. Consulta lista en
   `referencia_dias_por_dx.sql`.
2. **Leer la capa de texto del PDF en el pipeline de falsedad**, no solo el raster OCR-eado.
   Es lo mas barato del informe y sube la cobertura de golpe: en el unico caso de la familia,
   el diagnostico **estaba** en la capa de texto y **no** en la salida de RapidOCR.
3. **Mas casos etiquetados de este motivo.** Uno no alcanza. Y conviene pedirlos al area
   sabiendo que 3 de las 15 falsas llegaron **sin motivo escrito** y 2 estan en cuarentena por
   etiqueta contradictoria: el problema de fondo es la calidad de la etiquetacion.
4. **Validacion juridica de la tabla de pisos legales** por SST/juridica del cliente, con
   fecha de vigencia y responsable.
5. **Catalogo CIE-10 oficial local** — no lo necesita este check (los bloques se derivan del
   codigo), pero si lo necesitan las familias `DX_INEXISTENTE` / `DX_NOMBRE_DISTINTO`, y
   tenerlo permitiria filtrar aqui los codigos que **no existen** antes de opinar sobre dias.

---

## 8. Archivos de esta familia

```
senales/dias_vs_diagnostico/
├── probe.py                        sonda ejecutable (los 5 checks) — unica cosa que hay que correr
├── referencia_dias_por_dx.sql      de donde sale el rango: consulta al historico del ERP + calibracion
├── medicion.json                   salida por documento de la ultima corrida (derivado sensible)
└── INFORME.md                      este documento
```

`referencia_dias_por_dx.json` **no existe a proposito**. Es el archivo que activa el check
central; mientras no salga de la consulta del `.sql` contra la BD real, la sonda dice
`SIN_INSUMO`. Si alguien lo fabrica a mano, esta inventando rangos clinicos.
