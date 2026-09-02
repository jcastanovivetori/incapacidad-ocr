# Frente `medir-corpus` — el motor de tiempos medido sobre los 31 documentos reales

**Veredicto: FALLA.** El motor de validación temporal que pidió el cliente **no existe como tal**.
Lo que hay hoy (la aritmética de `extract.normalizar_fechas()` + tres `problemas.append()` dentro de
`erp.mapear_a_staging()`) **no detecta ni una sola incoherencia de tiempos**: sobre las tripletas
completas del corpus **detecta 0/1** de la única falsa cuyo motivo declarado es temporal y, peor,
**borra la evidencia** — reescribe la `fecha_fin` que leyó del documento para que cuadre, sin decírselo
al auxiliar. Eso es exactamente lo contrario de *"para cuando no coincida déjalo de tal forma que sea
escalable y actualizado"*.

## Qué se midió y con qué

- Entrada: los campos **ya extraídos** de los 31 documentos (`ocr/falsas/`, `ocr/falsa/`,
  `ocr/reales/`, `ocr/real/` — 31/31 con `.json` + `.txt`). **No se ejecutó OCR.**
- Función de entrada del motor: `erp.mapear_a_staging(resultado, lookups=LookupsNulos(), hoy=2026-09-02)`,
  precedida de `extract.normalizar_fechas()`. Sin BD (degradación por diseño, `LookupsNulos`).
- Dos pasadas por documento:
  - **stored**: el registro `incapacidad` tal como quedó en el JSON del corpus (ya post-`normalizar_fechas`).
  - **recalc**: re-extracción desde `texto_plano` con el `RuleBasedExtractor` **actual**, capturando los
    valores **crudos** antes de la reconciliación. Es la única forma de ver la incoherencia: después de
    `normalizar_fechas()` ya no es observable.
- Chequeo de **referencia** independiente (invariantes de `CLAUDE.md`): `fin = inicio + días − 1`
  (inclusivo), `días` válido 1..540. Implementado en `medir.py:chequeo_referencia`.
- Código medido (hash verificado antes y después de la corrida, no cambió):
  `extract.py` sha256 `8fc1918a62221ac8`, `erp.py` sha256 `c5e89a9298664cca`.
- Scripts: `medir.py` (corrida), `agregar.py` (métricas + tabla), `probe_tiempos.py` (probe dirigida).
  Salidas: `resultados.json`, `tabla.json`, `probe_tiempos.json`, `_salida.txt`.

### Estado real del repo (comprobado con `git status`/`git diff`)

No hay ningún módulo nuevo en `incapacidad_ocr/`. El diff sin commitear (`batch.py`, `webapp.py`,
`static/index.html`, docs) es **íntegramente** la reestructuración del árbol de ingesta
(`1_entrada/2_revisar/3_archivo`); **nada** sobre validación de tiempos. `grep` de
`severidad|umbral` en todo el repo: **0 resultados**. Es decir: los requisitos (3) *escalable* y
(4) *actualizable* no están empezados, y (2) *validar los tiempos* está solo en su forma de
"reconciliar y seguir", no de "validar y avisar".

## Exclusiones

**5 documentos excluidos por cuarentena** (`manifest.csv`, columna `cuarentena=si`), y se dicen:

| archivo | etiqueta | motivo de cuarentena |
|---|---|---|
| `FALSA-03.pdf` | falsa | mismo sha256 que `REAL-15.pdf` (real) |
| `FALSA-11.pdf` | falsa | mismo sha256 que `REAL-01.pdf` (real) |
| `FALSA-15.pdf` | falsa | misma cédula que `REAL-15.pdf`, contenido distinto |
| `REAL-01.pdf` | real | pareja sha256 de `INC <NOMBRE> <NOMBRE> ... 13.05.2026.pdf` |
| `REAL-15.pdf` | real | pareja sha256 de `INC <NOMBRE> <NOMBRE> ... 29072026.pdf` |

Se procesaron igual (aparecen en la tabla marcados `CUAR`) pero **no cuentan** en ninguna métrica.
Universo evaluado: **26 documentos = 12 falsas + 14 reales**.

## Métricas agregadas (26 evaluados)

### La métrica que importa: falsas con motivo TEMPORAL declarado

| | |
|---|---|
| Universo (motivo GT = `FECHAS_INCOHERENTES`) | **1** — `FALSA-04.pdf` |
| Detectadas como **incoherencia temporal** | **0 / 1  (0 %)** |
| Marcadas, pero solo con *"no leí el dato"* | 1 / 1 |

El motivo literal del cliente para ese documento es *"ALTERACION EN FECHA DE INICIO, DURACION Y FECHA
FIN, LOS DIAS NO CORRESPONDEN A LA FECHA DE FINALIZACION CALCULADA"*. El motor no dice nada de eso:
dice *"No se detectó la fecha de inicio; No se detectó el número de días"*. Llega a revisión humana
—no se cuela— pero por el motivo equivocado, y el auxiliar no recibe **ninguna** pista de que el
documento se contradice a sí mismo.

### Falsas por otros motivos — **fuera del alcance de este motor** (no cuentan como fallo)

11 de las 12 falsas evaluadas. Desglose de señales GT: `DX_INEXISTENTE` 3, `DX_NOMBRE_DISTINTO` 2,
`DX_FORMATO` 1, `FIRMA_MEDICO` 2, `DIAS_VS_DIAGNOSTICO` 1, `SIN_MOTIVO_REGISTRADO` 3.
(`DIAS_VS_DIAGNOSTICO` es plausibilidad clínica días↔DX, no aritmética de fechas: la cubre el frente
`senales/dias_vs_diagnostico`, no este.)

### Marcas del motor

| señal | falsas | reales |
|---|---|---|
| **incoherencia temporal** ("los tiempos no cuadran") | **0 / 12** | **0 / 14** (0 falsos positivos) |
| falta de dato temporal (inicio/días no leídos, o días fuera de rango) | 5 / 12 | 6 / 14 |
| `requiere_revision` (bandera global) | **12 / 12** | **14 / 14** |

Los dos "0" de incoherencia temporal no son mérito: **la regla no existe**, así que no puede acertar
ni equivocarse. Y `requiere_revision` marca **31/31** documentos (sin BD toda cédula/CIE-10/EPS falla
el lookup), de modo que **la bandera global no discrimina nada**: no hay forma de que el auxiliar
distinga "los tiempos no cuadran" de "no encontré la cédula" — todo va al mismo string `problemas`.

### No evaluables por falta de datos leídos

| | tripleta 3/3 | par 2/3 | **NO EVALUABLE** (<2 datos) |
|---|---|---|---|
| falsas (12) | 6 | 1 | **5** |
| reales (14) | 7 | 1 | **6** |
| **total (26)** | 13 (50 %) | 2 | **11 (42 %)** |

Los datos **sí están en el texto OCR** en la mayoría de esos 11 casos; lo que falla es la adyacencia
etiqueta→valor porque RapidOCR devuelve las tablas con las líneas desordenadas. Dos pruebas del corpus:

- `REAL-04.pdf`: `Dias de Incapacidad:` / `11/7/2026` / `Fecha de Inicio de Incapacidad:`
  / `12/7/2026` / `Fecha Fin de Incapacidad:` — **los valores van ANTES de su etiqueta**.
- `FALSA-14.pdf`: `DIASDEINCAPACIDAD` / `DOS (02)` y luego
  `p2 / 25 / FECHADEINICIO / 2026 / FECHAFINAL / 2026` — columnas intercaladas.

Nota de frontera: el trabajo paralelo que añade duraciones en letras ("DOS (02)") debería llevar
ese último documento de 0/3 a 1/3 — **seguirá NO EVALUABLE**, porque las fechas siguen sin resolverse.

### Robustez

- **0 excepciones** en 31 documentos × 2 pasadas + 8 casos de probe. El motor no se cae sin BD.
- Invariante `fechavencimiento = fechainicio + Numerodias` (no inclusivo): **31/31 correcta**, y
  `fechavencimiento` es `NULL` en todas las filas donde falta inicio o días. Esa parte está bien.

## Hallazgos

### GRAVE-1 — `normalizar_fechas()` BORRA la incoherencia en vez de reportarla

`extract.py:1144-1148`. Si hay inicio + días, cualquier `fecha_fin` que no cuadre se **sobreescribe** en
silencio: `if not df or df < di or (df - di).days + 1 != n: df = di + timedelta(days=n - 1)`.
No queda bandera, ni aviso, ni el valor original.

Caso reproducible del corpus (no simulado): `FALSA-09.jpeg`.
Texto OCR (`ocr/falsas/FALSA-09.txt`):

```
Dias de incapacidad:02dosdia(s)
Desde:05/06/2026-Hasta:06/07/2026
```

- Leído crudo: `inicio=2026-06-05`, `fin=2026-07-06`, `dias=2`.
- Esperado (invariante `CLAUDE.md`): fin = `2026-06-06`. El documento dice `2026-07-06`: **30 días de
  desfase**.
- Obtenido: `fin` reescrito a `2026-06-06`; `problemas` **sin una sola mención temporal**; la fila que
  llega al auxiliar es `fechainicio=2026-06-05, Numerodias=2, fechavencimiento=2026-06-07` — impecable.
  El auxiliar nunca sabrá que el documento decía "Hasta 06/07/2026".

Y sobre el caso que el cliente marcó como temporal (`probe_tiempos.py`, tripleta leída del texto
`MARTES 02 ... DE SEPTIEMBRE DE 2025` / `Duracion -DOS` / `JUEVES 04 DE SEPT1EMBRE DE2025`):
`inicio=2025-09-02, fin=2025-09-04, dias=2` → el motor reescribe `fin` a `2025-09-03`, `problemas`
temporales = **ninguno**. Guinda: la fila lleva `fechavencimiento=2025-09-04`, que **coincide** con la
fecha fin falsificada del documento (porque el vencimiento es no inclusivo), así que ni comparando a
ojo se nota.

### GRAVE-2 — El "saneo final" descarta una fecha LEÍDA y luego el motor miente sobre ella

`extract.py:1159-1166`. Cuando `fin < inicio` (o el rango excede 540 días) y no hay días para
arreglarlo, se **anula** una de las dos fechas leídas: `fecha_fin` si el inicio venía anclado al
rótulo, `fecha_inicio` en caso contrario.

- Entrada: `inicio=2026-06-10`, `fin=2026-06-05`, `dias=None`, sin anclaje.
- Esperado: un problema del tipo *"la fecha fin (2026-06-05) es anterior a la fecha de inicio
  (2026-06-10)"*.
- Obtenido: `fecha_inicio` pasa a `None` y `mapear_a_staging` informa **"No se detectó la fecha de
  inicio"** (`erp.py:492`). Es **falso**: sí se detectó, la reconciliación la tiró. El auxiliar irá a
  buscar en el documento un dato que el lector ya había encontrado, y la inversión de fechas
  —que es justo el patrón de alteración que se persigue— no se menciona nunca.
- Variante con inicio anclado: se anula `fecha_fin` y el motor **no dice absolutamente nada**
  (`fecha_fin` no es campo obligatorio); la fila sale con el inicio y sin rastro del conflicto.

### GRAVE-3 — Duraciones absurdas leídas del ruido de OCR pasan como válidas

El único filtro de días es `1 <= n <= 540` (`extract.py:1140`, `erp.py:497`). No hay contraste contra
las fechas presentes en el texto ni banda de plausibilidad.

- `REAL-16.jpeg` (real, evaluado): el texto dice `Fecha lnicio` y `Fecha Fin` ambas
  `MARTES 09 DE JUNIO DE 2026` (1 día). El lector saca `dias=202` del ruido `09/0/202607:4624`.
- Esperado: rechazar o al menos cuestionar 202 días en un documento cuyas dos únicas fechas son el
  mismo día (o cuya cadena de origen es una hora, no una duración).
- Obtenido: `Numerodias=202` en la fila, `problemas` temporales = solo *"No se detectó la fecha de
  inicio"*. 202 días roza el umbral de los 180 (trámite pensional): un valor así prellenado en la
  pantalla de revisión es material.
- Mismo patrón en `FALSA-03.pdf` (cuarentena, no cuenta pero ilustra): el
  texto dice literalmente `SE DA INCAPACIDAD MEDICA POR 4 DIAS DESDE EL 29-07-26 HASTA EL 01/07/29`
  —una contradicción temporal servida en bandeja— y el motor emite `Numerodias=29` y ni una palabra.

### MEDIA-1 — `dias = 0`: mensaje contradictorio con el valor de la propia fila

`erp.py:494-499`. `if not num_dias:` captura el `0` como si fuera ausencia, así que la rama
`elif not (1 <= num_dias <= 540)` (el único chequeo de rango que existe) es **inalcanzable para 0**.

- Entrada: `inicio=2026-06-09`, `dias=0`.
- Esperado: *"Número de días fuera de rango (=0)"*.
- Obtenido: *"No se detectó el número de días"*, y `campos_faltantes` registra `valor: None`,
  mientras la fila de staging lleva `Numerodias: 0`. El auxiliar lee "no se detectó" con un 0 delante.
  (`normalizar_fechas` descarta el 0 para su propia aritmética pero **no limpia** `inc["dias"]`,
  `extract.py:1139-1141`, así que el 0 sobrevive hasta la fila.)

### MEDIA-2 — No hay veredicto temporal separado: todo se mezcla en un string

`erp.py:566` (`"problemas": "; ".join(problemas)`). No existe campo/estructura que diga "esto es un
problema de TIEMPOS" frente a "esto es un lookup que falló". Con `requiere_revision` en 31/31, el
auxiliar recibe la misma señal para un documento perfecto sin BD y para uno con las fechas alteradas.
Sin un canal propio (código de regla + severidad), no hay forma de priorizar los ~7000 casos/mes.

### MEDIA-3 — Requisitos (3) escalable y (4) actualizable: sin implementar

Añadir una regla temporal hoy = editar `mapear_a_staging()` (una función de ~250 líneas que ya mezcla
homologación de tipo, lookups, EPS, documentación y fechas) o `normalizar_fechas()`. No hay catálogo
declarativo de reglas, ni identificadores de regla, ni severidades, ni umbrales fuera del código: el
`1..540` está repetido como literal en `extract.py:850,1140,1156,1162` y `erp.py:387,497,503`.
Cambiar un umbral = tocar 7 sitios y redesplegar.

### LEVE-1 — Un adjunto entra al motor como si fuera documento base

`REAL-10.pdf` es una historia clínica (adjunto que, según `PLAN_INGESTA_MASIVA.md`, no se
OCR-ea) y sin embargo produce fila con `Numerodias=2`. No es defecto del motor de tiempos —el corpus
lo incluye a propósito— pero cualquier métrica de cobertura que lo cuente como incapacidad está
inflando el denominador. Aquí se contó como evaluado y sale `NO EVALUABLE`, lo cual es correcto.

## Propuesta (no implementada — soy verificador)

No se tocó `extract.py` ni `tests/test_processor.py` (frontera respetada). Lo que hace falta,
descrito para quien implemente:

1. **`normalizar_fechas()` no debe reparar en silencio.** Antes de reescribir `fecha_fin`, conservar lo
   leído (`fecha_fin_leida`) y dejar una marca estructurada (p. ej. `avisos_tiempo:
   [{"regla":"FIN_VS_INICIO_DIAS","leido":"2026-07-06","esperado":"2026-06-06","delta_dias":30}]`).
   Igual en el saneo final: `INVERSION_FECHAS` / `RANGO_EXCEDE_540` en vez de anular y callar.
2. **Nunca emitir "no se detectó X" cuando X sí se detectó y se descartó.** Mensaje distinto:
   *"la fecha de inicio leída (…) se descartó por contradecir la fecha fin (…)"*.
3. **Catálogo declarativo de reglas temporales** (una lista de dataclasses `ReglaTiempo(codigo,
   descripcion, severidad_default, evaluar(ctx) -> bool|None)`, donde `None` = *no evaluable* por falta
   de dato o de BD). El motor recorre la lista; añadir regla = añadir una entrada. Reglas mínimas
   derivadas del corpus: `FIN_VS_INICIO_DIAS`, `INVERSION_FECHAS`, `DIAS_FUERA_DE_RANGO` (arreglando
   el `0`), `DIAS_VS_FECHAS_DEL_TEXTO`, `INICIO_POSTERIOR_A_EXPEDICION`, `INICIO_MUY_ANTIGUO`.
4. **Severidades y umbrales en tabla** (`lp_reglas_tiempo_ia`: `codigo, severidad, umbral, activa`) con
   *defaults* en código para que funcione sin BD; releer por corrida. Así se actualiza sin desplegar,
   igual que `documentos_requeridos()` ya lee requisitos de BD.
5. **Canal propio en la fila de staging**: columna con los códigos de regla disparados y su severidad,
   separada de `problemas`, para que la UI ordene la cola por gravedad.
6. Y el techo real de todo esto: **42 % de los documentos no tiene ni 2 de 3 datos temporales** porque
   el OCR desordena las tablas. Ninguna regla, por buena que sea, sirve sin coordenadas de OCR
   (`ocr.py` no expone cajas hoy) o sin un parser de tabla por columnas para los formatos SURA/Medical/
   Sanitas. Esa es la inversión que multiplica el valor del motor.

## Qué se atacó exactamente

Aritmética `fin = inicio + días − 1` sobre las 13 tripletas completas del corpus · rango `1..540`
(0, 541, 600) · `fin < inicio` en ambas ramas (`_inicio_anclada` True/False) · derivación
`inicio = fin − (días − 1)` y bandera `fecha_inicio_calculada` · invariante
`fechavencimiento = fechainicio + Numerodias` en las 31 filas · degradación sin MySQL (`LookupsNulos`)
· ausencia de excepciones en 70 invocaciones · cruce con `ground_truth.json` separando motivo temporal
de los demás · exclusión de los 5 documentos en cuarentena · disponibilidad real de los datos
temporales en el texto OCR frente a lo que el lector logra atar a su etiqueta.
