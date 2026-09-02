# Frente `medir-corpus` — el MOTOR de validación temporal medido sobre los 31 documentos

**Veredicto: PASA CON RESERVAS.**

El motor (`incapacidad_ocr/validacion_temporal.py` + `reglas_tiempo.py`) **funciona, no se cae y no
acusa a ningún documento legítimo**: 0 falsos positivos sobre las 14 reales evaluables, y detecta
**1/1** de las incoherencias temporales que son *observables* en los campos que hoy le llegan (F09,
con mensaje exacto y severidad GRAVE, que sí llega al auxiliar por el canal `problemas`).

La reserva es de RENDIMIENTO, no de corrección: sobre la única falsa cuyo motivo declarado por el
cliente es temporal (`FECHAS_INCOHERENTES`) **detecta 0/1**, y en **13 de 26** documentos (50 %) la
regla estrella `T01_DURACION_VS_RANGO` queda NO EVALUABLE. En los dos casos la causa está **aguas
arriba del motor**: el extractor no le pasa las fechas. Se demuestra con una sonda: entregándole a
mano la tripleta que **sí está impresa** en ese documento, T01 la marca GRAVE con el desfase exacto.
Es decir: la regla es correcta y el cuello de botella es la lectura.

A eso se añaden **2 defectos reproducibles** del camino degradado (registro sin la foto
`tiempos_leidos`), uno de ellos con veredicto **falso COHERENTE** sobre un documento adulterado.
Detalle en §6.

---

## 1. Qué se midió y con qué

- **Entrada: campos YA extraídos.** No se ejecutó OCR (había una medición de rendimiento corriendo en
  la máquina). Se usaron los 31 `.json` de `ocr/falsas/`, `ocr/falsa/`, `ocr/reales/`, `ocr/real/`
  (31/31 presentes, con su `.txt`).
- **Función de entrada del motor:** `validacion_temporal.validar_registro(registro, hoy=…, config=…)`
  → el informe completo de `validar_tiempos`. Y, para comprobar que el hallazgo **llega de verdad al
  auxiliar**, `erp.mapear_a_staging(..., lookups=LookupsNulos())`.
- **Sin BD y sin red:** `cargar_config()` reportó `fuentes = ('codigo',)` y `avisos = ()` → se midió
  contra los *defaults* del código. La medición se hizo con `config_por_defecto()` explícita para que
  no dependa del entorno.
- **`hoy` fijado en 2026-09-02** (no `date.today()`): T09/T10/T14 se miden contra hoy y sin fijarlo la
  medición cambia sola de un día para otro. La sensibilidad a ese valor se midió aparte (§5).
- **Tres pasadas por documento**, porque el motor se comporta distinto según cómo le llegue el registro:
  | pasada | qué es | para qué |
  |---|---|---|
  | **A** `almacenado` | `validar_registro(json['incapacidad'])`: el registro tal como quedó guardado (post-`normalizar_fechas`, **sin** la foto `tiempos_leidos`, porque el corpus se extrajo antes de que la foto existiera) | mide el camino degradado |
  | **B** `pipeline` | re-extracción desde `texto_plano` con el `RuleBasedExtractor` actual + foto igual que en `processor.run()` + `normalizar_fechas()` | **es la ruta de producción y la medición que vale** |
  | **C** `staging` | `erp.mapear_a_staging()` sobre (B) | comprueba `problemas` / `requiere_revision` / `alertas_tiempos` / `severidad_tiempos` |
- **Chequeo de REFERENCIA independiente del motor** (`medir_motor.py:chequeo_referencia`): aritmética
  pura sobre la tripleta leída, con la convención inclusiva de `CLAUDE.md`
  (`span = (fin − inicio) + 1`, `span == días`, `1 ≤ días ≤ 540`). Sirve para poder decir si el motor
  acierta contra algo que **no es el propio motor**.
- **Código medido** (huellas sha256[:16], verificadas al principio y al final):
  `reglas_tiempo.py=eb320f2a51641c50` · `validacion_temporal.py=aa13e158a828ff18` ·
  `erp.py=fcd48b542046df80` · `processor.py=8dc23242ed611dd6` · `extract.py=27f5fc882b4e0c35`.
  Durante la sesión otro trabajo cambió `numeros_es.py` (`48418a29…` → `8b723afc…`); se repitió la
  corrida completa y **la tabla salió byte a byte idéntica**, así que la medición no depende de ese
  cambio. `tests/test_validacion_temporal.py` pasa (`RESULTADO: TODO OK`) en el estado medido.
- **Scripts** (en esta carpeta, ejecutables con el Python del proyecto):
  `medir_motor.py` (las 3 pasadas) · `agregar_motor.py` (métricas + tabla) ·
  `probes_motor.py` (sondas P1/P2/P3) · `probe_sin_foto.py` (los 2 defectos de §6) ·
  `cobertura_lectura.py` (cuánta ceguera es recuperable en el extractor).
  Salidas: `resultados_motor.json`, `metricas_motor.json`, `tabla_motor.md`, `probes_motor.json`,
  `probe_sin_foto.json`, `cobertura_lectura.json`, `_salida_*.txt`.
  La medición **anterior** (hecha cuando el motor todavía no existía) se conservó en
  `_previo_sin_motor/`.

### PII (Ley 1581)

Los nombres de archivo de la clase `falsa` contienen nombres de pacientes. Este informe identifica
cada documento con el **ID estable del corpus** (`F01..F15` / `R01..R16`, orden de `manifest.csv` por
`(etiqueta, archivo)` — la misma numeración que usan los informes hermanos de `senales/`) **+
`sha256[:8]`**. La equivalencia ID → nombre de archivo queda sólo en `resultados_motor.json`, en esta
carpeta, que no se versiona. No se cita ningún dato de paciente (nombre, cédula, diagnóstico).

## 2. Exclusiones: los 5 documentos en cuarentena

`manifest.csv` marca 5 archivos con `cuarentena=si` y **no cuentan en ninguna métrica** (sí se
procesaron y aparecen en la tabla marcados `SÍ`, como caso de humo):

| ID | clase | motivo de cuarentena (de `manifest.csv`) |
|---|---|---|
| `F03` `28c4a946` | falsa | mismo sha256 en ambas clases (pareja de `R15`) |
| `F11` `d86ae595` | falsa | mismo sha256 en ambas clases (pareja de `R01`) |
| `F15` `58c1e091` | falsa | misma cédula que `R15`, contenido distinto |
| `R01` `d86ae595` | real | pareja sha256 de `F11` |
| `R15` `28c4a946` | real | pareja sha256 de `F03` |

Dos parejas byte-idénticas con etiqueta contradictoria: cualquier respuesta acierta 1 y falla 1, así
que usarlas como verdad movería precisión/recall varios puntos sobre 31 documentos. Su uso legítimo es
el de **caso de humo** y así se usaron (§5, P3).

**Universo evaluado: 26 documentos = 12 falsas + 14 reales.**

---

## 3. Métricas agregadas (26 evaluables, pasada B = producción)

### 3.1 La métrica que importa: falsas con motivo TEMPORAL declarado

| | |
|---|---|
| Universo (`ground_truth.json`, señal `FECHAS_INCOHERENTES`) | **1** — `F04` `e0ee54fd` |
| **Detectadas por el motor** | **0 / 1 (0 %)** |
| Veredicto que dio el motor a `F04` | `COHERENTE`, puntaje 100, **cobertura 0,39** |
| Causa | el extractor le pasó `días = 2` pero **ninguna de las dos fechas** → `T01` `NO_EVALUABLE` (`motivo: "no se pudo comprobar: falta la fecha de inicio impresa en el documento, la fecha fin impresa en el documento"`) |
| ¿Falla la regla o la lectura? | **la lectura.** Con la tripleta que sí imprime el papel (`2025-09-02 → 2025-09-04`, `2 días`) el motor responde `REVISAR / T01_DURACION_VS_RANGO` (GRAVE): *"el rango … son 3 día(s), pero declara 2 día(s) … desfase de 1 día(s)"* (`probes_motor.py`, P1) |

### 3.2 Falsas por OTROS motivos (no son responsabilidad de este motor)

11 falsas evaluables con motivo declarado de firma / tipografía / diagnóstico / sin motivo. **No
marcarlas no es un fallo del motor de tiempos.** Marcadas de todas formas: **1** (`F09` `d5b72739`,
GT = `DX_INEXISTENTE` + `DX_FORMATO`), porque además de su diagnóstico su tripleta impresa se
contradice: `Desde 05/06/2026 – Hasta 06/07/2026` con `2 días` → span 32, **desfase +30**. Es una
detección **extra**, y coincide con la que el chequeo de referencia encuentra por su cuenta.

### 3.3 Coste: reales marcadas por error

| | |
|---|---|
| Reales evaluables | 14 |
| **Marcadas con severidad que exige revisión (GRAVE/MEDIA)** | **0 / 14 (0 %)** |
| Marcadas sólo con aviso LEVE | 0 / 14 |

Ninguna de las 14 reales recibió un hallazgo temporal. Incluye los casos que más fácilmente producen
un falso positivo: la licencia de maternidad de 126 días (`R09`, span 126 = días 126), la de 30 días
(`R13`) y la de 14 (`R07`).

### 3.4 Cuánto pudo comprobar de verdad (lo NO EVALUABLE)

| | |
|---|---|
| Veredictos | `COHERENTE` **21** · `REVISAR` **1** · `AVISOS` 0 · `SIN_DATOS` **4** |
| `SIN_DATOS` (el motor no pudo comprobar **nada**) | 4/26 = 15 % — `F12`, `F13`, `R05` (permiso), `R16` |
| `T01` NO EVALUABLE (tripleta leída incompleta) | **13/26 = 50 %** — `F02 F04 F06 F12 F13 F14 R02 R03 R04 R05 R10 R14 R16` |
| Tripleta leída COMPLETA (T01 sí opina) | **13/26 = 50 %** — `F01 F05 F07 F08 F09 F10 R06 R07 R08 R09 R11 R12 R13` |
| Cobertura media del informe (`resumen.cobertura`) | **0,577** (ninguna llega a 1,00: T13/T15/T16/T17 están declaradas y apagadas) |

**Contraste con la referencia:** el chequeo aritmético independiente encuentra exactamente **1**
tripleta incoherente (`F09`), **0** rangos invertidos y **0** días fuera de 1..540. El motor detecta
esa 1 y sólo esa: **1/1, sin falsos positivos y sin falsos negativos sobre lo observable.**

De los 13 documentos donde T01 no puede opinar, **10 tienen en el texto OCR al menos una fecha que el
extractor no publica** como inicio/fin (`cobertura_lectura.py`): `F02 F06 F12 F13 F14 R02 R03 R04` en
formato `dd/mm/aaaa` y `F04`/`R16` escritas en palabras. Sólo **3** (`R05` permiso, `R10` historia
clínica, `R14`) no traen ninguna fecha aprovechable en el texto. Ejemplos concretos: `F02` imprime
*"…POR 1 DIA A PARTIR DE 18/05/2026 HASTA 18/05/2026"* y el extractor le lee el fin y los días pero no
el inicio (el rótulo *"a partir de"* no está anclado); `R04` trae 5 tokens de fecha y sólo se publica
el inicio. Es decir: **el 77 % de la ceguera del motor es recuperable en el extractor, sin tocar el
motor.** (Para `F04` y `R16` el día y el mes caen en líneas OCR distintas, así que ahí el conteo
automático es indicativo y la verificación es manual — ver §3.1.)

### 3.5 Por regla (26 documentos evaluables)

| regla | NO_CUMPLE | CUMPLE | NO_EVALUABLE | lectura |
|---|---|---|---|---|
| `T01_DURACION_VS_RANGO` | **1** (`F09`) | 12 | 13 | la regla estrella; 50 % de cobertura |
| `T02_FIN_ANTES_DE_INICIO` | 0 | 13 | 13 | el corpus no trae ningún rango invertido |
| `T03_DIAS_FUERA_DE_RANGO` | 0 | 19 | 7 | ningún documento imprime días fuera de 1..540 |
| `T04_RANGO_MAYOR_AL_MAXIMO` | 0 | 13 | 13 | — |
| `T05_DIAS_NO_NUMERICO` | 0 | 19 | 7 | — |
| `T06_FECHA_INICIO_ILEGIBLE` | 0 | 17 | 9 | — |
| `T07_FECHA_FIN_ILEGIBLE` | 0 | 15 | 11 | — |
| `T08_DURACION_SIN_RESPALDO` | 0 | 19 | 7 | ver §6.3: en la pasada A **sí** dispara (y es útil) |
| `T09_INICIO_EN_FUTURO` | 0 | 17 | 9 | 0 con `hoy=2026-09-02`; ver §5 P2 |
| `T10_INICIO_MUY_ANTIGUO` | 0 | 17 | 9 | idem |
| `T11_FIN_REESCRITO_SIN_EVIDENCIA` | 0 | 26 | 0 | nunca disparó: en la ruta B la foto siempre existe |
| `T12_DIAS_LETRA_DISCREPA` | 0 | 5 | 21 | 5 documentos traen la duración en letras y los 5 coinciden |
| `T14_EXPEDICION_POSTERIOR_AL_INICIO` | 0 | 2 | 24 | cobertura mínima confirmada: sólo `R02`/`R03` traen expedición legible |
| `T13`, `T15`, `T16`, `T17` | — | — | — | `DESACTIVADA` por configuración (declaradas, sin dato/acceso) |

Las 12 reglas que reportan 0 NO_CUMPLE lo hacen **porque el corpus no contiene ningún caso suyo**, no
porque no funcionen: el suite del repo (`tests/test_validacion_temporal.py`) las ejercita una por una
y pasa completo en el estado medido.

### 3.6 El canal hasta el auxiliar (pasada C) y la fila de staging

Para `F09`, el único documento con hallazgo: `alertas_tiempos = "T01_DURACION_VS_RANGO"`,
`severidad_tiempos = "GRAVE"`, y el mensaje entra en `problemas` (4 problemas en total; los otros 3
son de lookup, porque sin BD no se resuelven cédula/CIE/EPS). La evidencia sobrevive:
`fechafin_leida = 2026-07-06` y `dias_leidos = 2`, aunque la fila registra
`fechainicio 2026-06-05 / Numerodias 2 / fechavencimiento 2026-06-07` (el fin re-derivado — es la
pregunta abierta P3 del cliente: quién manda en el conteo).

`requiere_revision = 26/26` en la pasada C, pero **no por los tiempos**: con `LookupsNulos()` ningún
documento resuelve cédula/CIE-10/EPS, así que todos entran a revisión por lookup. El eje temporal es
independiente y sólo se activó en `F09`. **Ningún documento fue rechazado ni aprobado por el motor**
(estado `PENDIENTE_REVISION` en toda la corrida): el contrato "nunca se rechaza solo" se cumple.

**Post-condición R-T05** (`fechavencimiento == fechainicio + Numerodias`, no inclusivo), que el motor
declara como propuesta *no* implementada: se comprobó a mano sobre las 26 filas → **0 violaciones**
(19 filas comprobables, 7 sin días o sin inicio). Hoy la aritmética de `erp` la respeta; que no haya
guardarraíl sigue siendo deuda, no un fallo observado.

---

## 4. Tabla por documento

(`—` = el dato no se leyó; `span/desfase` es el chequeo de referencia, independiente del motor;
`cobertura` y `puntaje` salen del informe del motor.)

<!-- generada por agregar_motor.py; copia idéntica en tabla_motor.md -->

| ID | sha8 | clase | cuar | motivo GT | leído inicio→fin (días) | span/desfase | veredicto motor | códigos | severidad | cobertura | puntaje |
|---|---|---|---|---|---|---|---|---|---|---|---|
| `F01` | `8b682a83` | falsa |  | FIRMA_MEDICO | 2026-07-14 → 2026-07-14 (1) | 1/0 | **COHERENTE** | — | — | 0.85 | 100 |
| `F02` | `5c66d97e` | falsa |  | DX_INEXISTENTE | — → 2026-05-18 (1) | —/— | **COHERENTE** | — | — | 0.39 | 100 |
| `F03` | `28c4a946` | falsa | SÍ | TIPOGRAFIA_MIXTA | — → — (4) | —/— | **COHERENTE** | — | — | 0.31 | 100 |
| `F04` | `e0ee54fd` | falsa |  | **FECHAS_INCOHERENTES** | — → — (2) | —/— | **COHERENTE** | — | — | 0.39 | 100 |
| `F05` | `8aeee4cd` | falsa |  | DIAS_VS_DIAGNOSTICO | 2025-11-10 → 2025-11-11 (2) | 2/0 | **COHERENTE** | — | — | 0.85 | 100 |
| `F06` | `9dcb4e35` | falsa |  | SIN_MOTIVO_REGISTRADO | 2025-09-15 → — (2) | —/— | **COHERENTE** | — | — | 0.54 | 100 |
| `F07` | `9603c77b` | falsa |  | DX_NOMBRE_DISTINTO | 2026-04-20 → 2026-04-20 (1) | 1/0 | **COHERENTE** | — | — | 0.85 | 100 |
| `F08` | `ed2a4eeb` | falsa |  | FIRMA_MEDICO | 2025-10-31 → 2025-11-01 (2) | 2/0 | **COHERENTE** | — | — | 0.85 | 100 |
| `F09` | `d5b72739` | falsa |  | DX_INEXISTENTE, DX_FORMATO | 2026-06-05 → 2026-07-06 (2) | **32/+30** | **REVISAR** | T01_DURACION_VS_RANGO | GRAVE | 0.92 | 60 |
| `F10` | `717d3aad` | falsa |  | DX_INEXISTENTE | 2026-06-09 → 2026-06-10 (2) | 2/0 | **COHERENTE** | — | — | 0.92 | 100 |
| `F11` | `d86ae595` | falsa | SÍ | DX_INEXISTENTE | — → 2026-05-14 (2) | —/— | **COHERENTE** | — | — | 0.46 | 100 |
| `F12` | `d08cba3f` | falsa |  | SIN_MOTIVO_REGISTRADO | — → — (—) | —/— | **SIN_DATOS** | — | — | 0.08 | 100 |
| `F13` | `99d74f47` | falsa |  | DX_NOMBRE_DISTINTO | — → — (—) | —/— | **SIN_DATOS** | — | — | 0.08 | 100 |
| `F14` | `758d3aff` | falsa |  | SIN_MOTIVO_REGISTRADO | — → — (2) | —/— | **COHERENTE** | — | — | 0.39 | 100 |
| `F15` | `58c1e091` | falsa | SÍ | DX_NOMBRE_DISTINTO | — → — (—) | —/— | **SIN_DATOS** | — | — | 0.08 | 100 |
| `R01` | `d86ae595` | real | SÍ | — | — → 2026-05-14 (2) | —/— | **COHERENTE** | — | — | 0.46 | 100 |
| `R02` | `f858510e` | real |  | — | 2026-06-10 → — (—) | —/— | **COHERENTE** | — | — | 0.39 | 100 |
| `R03` | `b68fe146` | real |  | — | 2026-06-10 → — (—) | —/— | **COHERENTE** | — | — | 0.39 | 100 |
| `R04` | `38f40c48` | real |  | — | 2026-07-12 → — (—) | —/— | **COHERENTE** | — | — | 0.31 | 100 |
| `R05` | `087739e6` | real |  | — (permiso) | — → — (—) | —/— | **SIN_DATOS** | — | — | 0.08 | 100 |
| `R06` | `eddf194a` | real |  | — | 2026-06-09 → 2026-06-10 (2) | 2/0 | **COHERENTE** | — | — | 0.85 | 100 |
| `R07` | `d6482e2a` | real |  | — | 2026-07-10 → 2026-07-23 (14) | 14/0 | **COHERENTE** | — | — | 0.85 | 100 |
| `R08` | `100e7770` | real |  | — (permiso) | 2026-06-06 → 2026-06-06 (1) | 1/0 | **COHERENTE** | — | — | 0.85 | 100 |
| `R09` | `aa3512d4` | real |  | — (maternidad) | 2026-06-07 → 2026-10-10 (126) | 126/0 | **COHERENTE** | — | — | 0.85 | 100 |
| `R10` | `e25d5211` | real |  | — (historia) | — → — (2) | —/— | **COHERENTE** | — | — | 0.31 | 100 |
| `R11` | `c672e270` | real |  | — | 2026-07-18 → 2026-07-19 (2) | 2/0 | **COHERENTE** | — | — | 0.85 | 100 |
| `R12` | `942de664` | real |  | — | 2026-05-25 → 2026-05-27 (3) | 3/0 | **COHERENTE** | — | — | 0.85 | 100 |
| `R13` | `b6e8beb6` | real |  | — | 2026-05-24 → 2026-06-22 (30) | 30/0 | **COHERENTE** | — | — | 0.92 | 100 |
| `R14` | `691e0af0` | real |  | — | — → 2026-06-11 (3) | —/— | **COHERENTE** | — | — | 0.39 | 100 |
| `R15` | `28c4a946` | real | SÍ | — | — → — (4) | —/— | **COHERENTE** | — | — | 0.31 | 100 |
| `R16` | `272d0d3d` | real |  | — | — → — (—) | —/— | **SIN_DATOS** | — | — | 0.08 | 100 |

---

## 5. Sondas dirigidas (`probes_motor.py`)

**P1 — ¿falla la regla o la lectura, en `F04`?** La lectura. Ver §3.1: mismo motor, misma
configuración; con la tripleta impresa, `REVISAR / T01` GRAVE y el mensaje cita las dos fechas, el
span, los días y el desfase.

**P2 — sensibilidad a la fecha de proceso.** Se repitió la pasada B con cinco `hoy` distintos y se
contaron las **reales** marcadas:

| `hoy` | reales marcadas GRAVE/MEDIA | sólo aviso LEVE | regla |
|---|---|---|---|
| 2025-01-01 | **10 / 14** | 0 | `T09_INICIO_EN_FUTURO` |
| 2026-05-01 | **8 / 14** | 0 | `T09_INICIO_EN_FUTURO` |
| **2026-09-02** (base) | **0 / 14** | 0 | — |
| 2027-06-01 | 0 / 14 | 0 | — |
| 2028-09-02 | 0 / 14 | **10 / 14** | `T10_INICIO_MUY_ANTIGUO` |

Lectura: la ventana temporal es la parte más frágil del catálogo, y el diseño acertó al hacer `T10`
**LEVE** (dos años después, 10 documentos legítimos sólo avisan y no bloquean). El riesgo real está
en `T09`, que es **MEDIA y por tanto bloquea**: reprocesar un lote histórico, un contenedor con la
fecha mal puesta o una radicación anticipada convierten documentos legítimos en cola de revisión —
57 % de las reales con un desfase de 4 meses. Es la pregunta abierta P6 del propio módulo, ahora
cuantificada. La palanca ya existe (bajar `T09` a LEVE o subir `dias_futuro_max` por configuración,
sin desplegar).

**P3 — determinismo.** Las dos parejas byte-idénticas (`F03`/`R15` y `F11`/`R01`) y dos corridas del
mismo documento dan informes **idénticos** (4/4), comparando veredicto, códigos, puntaje, resumen y
evidencia. Es el uso legítimo de los documentos en cuarentena: caso de humo, no verdad.

---

## 6. Hallazgos

### 6.1 MEDIA — sin la foto `tiempos_leidos`, un fin DERIVADO se cuenta como leído: `T01` pasa a `CUMPLE` y la cobertura se infla

- **Entrada** (`probe_sin_foto.py`, CASO 1; sin PII): documento que imprime **inicio y días, no
  fecha fin** — la mitad del corpus. `registro = {"fecha_inicio": "2026-06-01", "fecha_fin": None,
  "dias": 5}` → `normalizar_fechas()` deja
  `{"fecha_inicio": "2026-06-01", "fecha_fin": "2026-06-05", "dias": 5,
  "fecha_inicio_calculada": false, "fecha_fin_recalculada": false}`. Ese registro (sin foto) se pasa a
  `validar_registro(...)`.
- **Esperado:** `T01 = NO_EVALUABLE` ("falta la fecha fin impresa en el documento") y la cobertura
  correspondiente — es lo que responde el MISMO caso **con** foto: `cobertura 0,54`.
- **Obtenido:** `T01 = CUMPLE` y `cobertura 0,85`. El informe afirma haber cruzado duración ↔ rango
  de fechas cuando el papel no imprimía ningún rango.
- **Por qué:** `reglas_tiempo.valores_leidos()` (`incapacidad_ocr/reglas_tiempo.py:410-411`) descarta
  el inicio si `fecha_inicio_calculada`, y el fin si `fecha_fin_recalculada`. Pero
  `normalizar_fechas()` sólo marca `fecha_fin_recalculada` cuando **había** un fin que no cuadraba
  (`extract.py`, rama `if df is not None`); cuando el fin simplemente **no venía** y se completó, no
  hay marca alguna, así que el valor derivado entra como evidencia. El comentario de esa rama dice
  "Un valor CALCULADO no es evidencia → se descarta", y para el fin *completado* no se cumple.
- **Impacto:** no es un falso positivo (T01 CUMPLE tautológicamente, la aritmética que derivó el fin
  garantiza que cuadra), pero **rompe justo el indicador que el diseño creó para no leer un
  `COHERENTE` como "documento verificado"**: `cobertura`. Un tablero que ordene por cobertura verá
  0,85 donde se comprobó 0,54.

### 6.2 MEDIA — el mismo documento adulterado da `COHERENTE` si el registro llega sin foto y sin la marca

- **Entrada** (`probe_sin_foto.py`, CASO 3 — es un archivo real del corpus):
  `validar_registro(json.load("ocr/falsas/…<NOMBRE>…05062026.json")["incapacidad"], hoy=2026-09-02)`,
  cuyo bloque guardado es `{"fecha_inicio": "2026-06-05", "fecha_fin": "2026-06-06", "dias": 2,
  "fecha_inicio_calculada": false}` (sin `fecha_fin_recalculada`, porque ese JSON se extrajo con un
  pipeline anterior a la marca). El papel dice `Desde 05/06/2026 – Hasta 06/07/2026`, `2 días`.
- **Esperado:** que **no** sea `COHERENTE`. Con foto el mismo documento da
  `REVISAR / T01_DURACION_VS_RANGO` (GRAVE); con la marca pero sin foto da
  `REVISAR / T11_FIN_REESCRITO_SIN_EVIDENCIA` (GRAVE), que es exactamente el caso que T11 cubre.
- **Obtenido:** `veredicto = COHERENTE`, puntaje 100, `cobertura 0,85`, `T01 = CUMPLE`,
  `T11 = CUMPLE`. La contradicción desapareció y el informe no deja ninguna señal de que se perdió.
- **Alcance real:** las rutas vivas de hoy **no** pasan por aquí — `processor.run()` guarda la foto y
  el front reenvía el `resultado` completo a `/api/mapear` (`static/index.html:642`, `body: {resultado:
  lastResult, …}`), y `batch.py` usa `IncapacidadProcessor`. Lo que sí pasa por aquí es cualquier
  registro **construido a mano o releído de disco**, que es justo el uso que documenta la API pública
  (`validar_registro`: *"Pensado para auditar un documento, para el CLI y para las pruebas"*) y lo que
  aceptan `/api/mapear` y `/api/guardar` (toman el `resultado` del cuerpo de la petición). Hoy los
  únicos registros persistidos que existen son los 31 del corpus, y **todos** caen en este camino.
- **Propuesta (no aplicada; `extract.py` y el paquete son de sólo lectura en este frente):** que el
  camino sin foto sea conservador de verdad — si `fecha_fin` está presente y no hay foto **ni** marca,
  tratarla como *no evidencia* (`fin_crudo = None`) en vez de como leída; o, mejor, que
  `normalizar_fechas()` marque también el fin **completado** (p.ej. `fecha_fin_calculada`, simétrico
  de `fecha_inicio_calculada`), que es el dato que hoy falta. Con cualquiera de las dos, 6.1 y 6.2
  desaparecen sin tocar el motor.

### 6.3 MEDIA (informativo) — `T08` es el único que marca una REAL, y lo hace por un dato basura del OCR

En la pasada A (registro tal como lo dejó el extractor anterior), `R16` `272d0d3d` — un documento
**real** — sale `REVISAR / T08_DURACION_SIN_RESPALDO` (MEDIA) porque ese extractor leyó
`dias = 202` de `"Duracion\nDE2026"`. Con el extractor actual `R16` no publica días y el resultado es
`SIN_DATOS`, así que hoy **no hay falso positivo**. Se reporta porque mide bien la relación coste/valor
de `T08`: cuando el OCR fabrica una duración larga, `T08` es lo único que lo detiene antes de que
`Numerodias = 202` entre en la fila (202 está dentro de 1..540, así que `T03` no lo ve). Es decir, el
"falso positivo" es en realidad la red de seguridad funcionando; el aviso que hay que dar al cliente es
que ese caso **bloquea** un documento legítimo, y la palanca (bajarlo a LEVE) existe por configuración.

### 6.4 LEVE — el veredicto `COHERENTE` con cobertura baja se lee como "documento verificado"

`F04` (la falsa temporal del cliente) sale `COHERENTE` con `cobertura 0,39`, y `F14`/`F02` igual con
0,39. El informe **sí** publica la cobertura y el estado `NO_EVALUABLE` con su motivo en español, así
que la información está; lo que no hay es nada en el propio nombre del veredicto que lo distinga de un
`COHERENTE` con cobertura 0,92. Con ~7000 casos/mes leídos por un auxiliar, es un riesgo de
interpretación, no un defecto del cálculo. Refuerza lo que ya está anotado como limitación: **la UI
todavía no pinta el panel de tiempos** (`static/index.html:271`, `div #erpTiempos` sin renderizador),
así que hoy el auxiliar ve el mensaje de `problemas` pero **no** ve cobertura ni veredicto.

---

## 7. Lo que ataqué (y no encontró nada)

Para que quede claro qué está cubierto por esta medición y qué no:

- **Caída del motor / excepción:** 31 documentos × 3 pasadas + 26 × 5 fechas de proceso + 3 sondas =
  **0 excepciones**, 0 reglas en estado "la regla falló al evaluarse".
- **Falsos positivos sobre documentos legítimos:** 0/14 con `hoy` real. Incluye maternidad de 126
  días, incapacidad de 30, permisos y una historia clínica.
- **Falsos negativos sobre lo observable:** 0 — el motor encuentra la única incoherencia que el
  chequeo aritmético independiente encuentra.
- **Degradación sin BD:** `cargar_config()` = `('codigo',)`, sin avisos, sin excepción; `LookupsNulos`
  deja las reglas de histórico en `NO_EVALUABLE` (`T15/T16/T17` además `DESACTIVADA`).
- **"Nunca se rechaza solo":** ninguna fila salió con estado distinto de `PENDIENTE_REVISION`; el
  motor sólo añade texto a `problemas` y códigos a `alertas_tiempos`.
- **Determinismo:** 4/4 comparaciones idénticas, incluida la pareja byte-idéntica de clases opuestas.
- **Post-condición del vencimiento (R-T05):** 0 violaciones en 19 filas comprobables.
- **Evidencia preservada en la fila:** `fechafin_leida` / `dias_leidos` llegan con el valor **leído**
  (2026-07-06 / 2 en `F09`) aunque la fila registre el fin re-derivado.

**Lo que esta medición NO cubre** (otros frentes): calidad del OCR, señales de firma/tipografía/DX,
configuración en caliente por BD o archivo (`romper-reglas`), y el comportamiento de las reglas
apagadas `T15/T16/T17` contra un histórico real, que no existe.

## 8. Recomendación

1. **La palanca de mayor valor no está en el motor, está en el extractor.** Publicar las fechas
   escritas en palabras (formato tipo Sura: *"MARTES 02 DE SEPTIEMBRE DE 2025"*) y el par
   `Desde/Hasta` de los formatos donde hoy se pierde subiría la cobertura de `T01` del 50 % y, en
   particular, haría que la única falsa temporal declarada del corpus se detectara (probado en P1). El
   lector ya existe fuera del paquete: `senales/aritmetica_fechas/probe.py` (`escrita_sura`,
   `prosa_desde/hasta`) lo hace con `re` + `datetime`.
2. **Marcar el fin COMPLETADO** (§6.1/6.2), simétrico de `fecha_inicio_calculada`.
3. **Decidir la severidad de `T09`** con el cliente antes de producción (§5 P2): mientras el plazo de
   radicación sea pregunta abierta, MEDIA bloquea documentos legítimos en cuanto el reloj no coincide
   con el lote.
4. **Pintar el panel de tiempos en la UI**, para que la cobertura y el estado por regla lleguen al
   auxiliar (hoy sólo llega el texto del hallazgo).
