# 02 — Catálogo de reglas TEMPORALES (fechas y duraciones)

**Familia:** coherencia de tiempos de la incapacidad (fecha de inicio, fecha fin, número de días,
fecha de expedición, plazo de radicación, solapamiento y prórroga).
**Fecha:** 2026-09-02 · **Estado:** propuesta con medición, sin implementar.
**Insumos:** `manifest.csv`, `ground_truth.json`, `ocr/{falsas,falsa,reales,real}/*.{json,txt}`.
**Medición reproducible:** `validacion/_medir_tiempos.py` → `validacion/medicion_tiempos.json`.

> **PII (Ley 1581).** Este documento cita **nombres de archivo** del corpus (los mismos de
> `manifest.csv`, en la misma carpeta) y cifras agregadas. No transcribe datos clínicos ni
> identificadores de pacientes.

> **Alcance.** Esta familia NO cubre `dias_vs_diagnostico` (plausibilidad clínica de la duración,
> motivo «NO CONCUERDA EL NUMERO DE DIAS CON EL DIAGNOSTICO») — eso ya lo midió otra sonda en
> `senales/dias_vs_diagnostico/`. Aquí solo se valida **aritmética y orden de tiempos**, que no
> necesita conocimiento médico y por tanto es 100 % determinista.

---

## 0. Resumen ejecutivo (lo que hay que saber antes de escribir código)

1. **La regla estrella hoy no puede funcionar, y no por falta de reglas sino porque el pipeline
   borra la evidencia.** `extract.normalizar_fechas()` **sobrescribe la fecha fin leída** cuando no
   cuadra con `inicio + días`. Comprobado en el corpus: en
   `FALSA-09.jpeg` el documento imprime
   `Desde:05/06/2026-Hasta:06/07/2026` con `Dias de incapacidad:02` y el JSON de salida guarda
   `fecha_fin = 2026-06-06`. La única contradicción aritmética legible del corpus queda **corregida
   en silencio** antes de que la vea alguien.
2. **Falta procedencia (leído vs derivado).** `dias` también se rellena por diferencia de fechas y
   la fecha fin se re-deriva, sin marca. Solo existe una marca: `fecha_inicio_calculada`. Sin
   `fecha_fin_leida` / `dias_leidos` cualquier regla de coherencia grita incoherencia sobre
   documentos legítimos (o nunca dispara, porque el pipeline ya "arregló" los tres valores).
3. **Cobertura real de la regla estrella: 9 de 26 documentos** (35 %) traen los TRES datos
   **impresos y legibles**. De esos, **1 se contradice** (falsa) y **0 de los 3 reales evaluables**.
4. **La regla estrella NO detecta el caso que el cliente marcó como temporal.** El documento con
   motivo «ALTERACION EN FECHA DE INICIO, DURACION Y FECHA FIN…»
   (`FALSA-04.pdf`) sale del OCR **sin ninguno** de
   los tres datos: las fechas están escritas en español y el OCR devolvió `SEPT1EMBRE` (un `1` por
   la `I`), lo que rompe el mes en `extract._fecha_inicio_fin_escrita`. **Recall de la familia sobre
   su propio caso etiquetado: 0/1.** El cuello de botella es la LECTURA, no la regla.
5. **La duración en LETRAS es la vía más prometedora** y es justo lo que el otro trabajo está
   añadiendo: 9 de 26 documentos limpios imprimen el número en palabras junto a los días
   (`Dias: 2 (DOS DIAS)`, `Dias: 1 (UN DIA)`), y hay un caso más **pegado**
   (`Dias de incapacidad:02dosdia(s)`) que exige tolerar el glue del OCR.
6. **El plazo de radicación no se puede inventar y además hoy se mediría mal.** Con
   `hoy = 2026-09-02` la antigüedad del corpus va de 46 a 352 días: cualquier umbral por debajo de
   ~100 días marcaría **todos** los documentos reales. La causa es que `erp.mapear_a_staging` usa
   `fecharegistro = date.today()`, así que **reprocesar un lote viejo hace que todo parezca fuera de
   plazo**. La regla debe comparar contra la fecha de RECEPCIÓN del documento, no contra hoy.
7. **La antigüedad NO es señal de falsedad en este corpus.** Las falsas empiezan en 2025 (3 docs) y
   2026 (4); las reales, todas en 2026 (9). Eso es un artefacto de cómo el cliente recolectó la
   muestra, no una propiedad del fraude. Usar antigüedad como indicio de adulteración sería aprender
   el sesgo del muestreo.
8. **Peligro de diseño en el flujo actual:** `erp.mapear_a_staging` hace
   `requiere_revision = len(problemas) > 0` y `webapp.py` devuelve **409 al aprobar** si
   `requiere_revision`. Si las alertas temporales se meten en `problemas`, un aviso del tipo
   "documento antiguo" **bloquea la aprobación para siempre**: no hay campo que el auxiliar pueda
   editar para hacerlo desaparecer. Las alertas temporales necesitan **canal propio**.

---

## 1. Medición sobre la evidencia

### 1.1 Corpus y cuarentena

| | docs |
|---|---|
| Filas en `manifest.csv` | 31 |
| **En cuarentena — EXCLUIDOS de toda estadística** | **5** |
| Corpus limpio | **26** (12 falsas · 14 reales) |
| Con texto OCR utilizable | 26/26 |

Los 5 excluidos y por qué (`manifest.csv`, columna `motivo_cuarentena`):

- **Dos parejas byte-idénticas** (mismo `sha256` en ambas clases → 4 archivos): «INC <NOMBRE> <NOMBRE>
  <NOMBRE> <NOMBRE> 29072026.pdf» ≡ «REAL-15.pdf», y «INC <NOMBRE> <NOMBRE> <NOMBRE> <NOMBRE>
  13.05.2026.pdf» ≡ «REAL-01.pdf». El **mismo byte** está etiquetado a la vez como
  falso y como real: cualquier métrica que los incluya está midiendo ruido de etiquetado.
- **Un quinto** archivo, «FALSA-15.pdf», con la misma cédula que un real pero
  contenido distinto.

### 1.2 Cuántas veces se puede evaluar la coherencia inicio/fin/días

Los valores se reconstruyeron **con procedencia** desde los `.txt` guardados llamando a los mismos
helpers del extractor (`_find_date`, `_fecha_inicio_fin_escrita`, `_extraer_detalle_incapacidad`),
**sin** los respaldos que derivan: no se completa inicio desde `fin − (días−1)` ni días desde la
diferencia de fechas. Es decir, aquí «leído» significa **impreso en el papel**.

| | falsas (12) | reales (14) | total (26) |
|---|---|---|---|
| `fecha_inicio` leída | 7 | 9 | 16 |
| `fecha_fin` leída | 7 | 7 | 14 |
| `dias` leídos **de un rótulo** | 7 | 6 | 13 |
| `fecha_expedicion` leída | 0 | 2 | 2 |
| **LOS TRES leídos** | **6** | **3** | **9** (35 %) |
| **…y se CONTRADICEN** | **1** | **0** | **1** |
| Orden invertido (inicio > fin) | 0 | 0 | 0 |
| `dias` fuera de 1..540 | 0 | 0 | 0 |
| Expedición posterior al inicio | 0 | 0 | 0 |

**El único incoherente**

| archivo | inicio | fin | días impresos | días por fechas | desfase |
|---|---|---|---|---|---|
| `FALSA-09.jpeg` (falsa) | 2026-06-05 | 2026-07-06 | 2 | 32 | −30 |

Texto: `Dias de incapacidad:02dosdia(s)` + `Desde:05/06/2026-Hasta:06/07/2026`.
El **documento hermano** del mismo formato, mismo paciente y misma clase
(`FALSA-10.pdf`) imprime
`Dias de incapacidad: 02 dos dia(s)` + `Desde: 09/06/2026 -Hasta: 10/06/2026`, lo que confirma que
el formato es `dd/mm/aaaa` y que lo esperable era `06/06/2026`.

**Honestidad sobre este caso:** el archivo es un JPEG con OCR visiblemente peor que su hermano PDF
(pierde dígitos de la cédula, parte el nombre). Que `06/06` se leyera como `06/07` es **tan plausible
como** que el documento esté adulterado en ese dígito. No se puede decidir desde el texto. Lo que sí
es cierto es que **el destino correcto es la revisión humana en ambos casos** — y que el motivo que
el cliente registró para ese archivo era otro (DX inexistente), así que la regla aportaría una
detección **independiente**, no redundante.

### 1.3 Lo que el pipeline reescribe hoy (por qué la regla estrella está ciega)

Comparación valor **leído** vs valor **en el JSON de salida** (post `normalizar_fechas`):

| archivo | qué cambió |
|---|---|
| `FALSA-09.jpeg` | **fin 2026-07-06 → 2026-06-06** (la evidencia de incoherencia, borrada) |
| `REAL-06.pdf` (real) | `dias` nada → **2** (derivado de las fechas, sin marca) |
| `REAL-07.pdf` (real) | `dias` nada → **14** (derivado, sin marca) |
| `REAL-12.jpeg` (real) | `dias` nada → **3** (derivado, sin marca) |
| `REAL-08.pdf` (real) | `dias` nada → **1** (derivado, sin marca) |
| `REAL-14.pdf` (real) | inicio derivado, `fecha_inicio_calculada = True` (correcto) |

Dos lecturas de esta tabla:

- **8 de 31 documentos** llegan a staging con al menos un dato temporal que el pipeline **derivó o
  reescribió**. Una regla ingenua que compare esos tres valores encontraría coherencia perfecta
  siempre (los derivó el propio pipeline) o incoherencia inventada — en ambos casos, inútil.
- **De esos 8, solo 3 quedan marcados; los otros 5 son invisibles.** `fecha_inicio_calculada` cubre
  bien los **3** casos de inicio derivado. Pero **4 documentos reales** con los **días** derivados
  por diferencia (`CED-11`, `CED-12`, `CED-13`, `CED-18`) y **1 documento con el fin
  reescrito** (`…<NOMBRE>…05062026.jpeg`) llegan a staging **sin ninguna señal**. No existen
  `fecha_fin_calculada` ni `dias_calculados` — y son exactamente las dos marcas que la regla estrella
  necesita para no dispararse sobre datos que ella misma calculó.

> **Nota de método (límite conocido de esta medición).** La reconstrucción de §1.2 replica la ruta
> genérica del extractor, **no** `extract._extraer_permiso`, que lee las fechas del bloque
> «3. DURACIÓN DEL PERMISO» por **posición** (primera fecha = desde, segunda = hasta) y tolera el
> D/M/A partido en celdas (`06 06 26`). Por eso los 2 permisos del corpus figuran en §1.2 sin fechas
> leídas cuando en realidad sí las tienen. **No afecta a las cifras de la regla estrella**: ninguno de
> los dos permisos imprime un número de días (su duración se deriva siempre por diferencia, igual que
> en vacaciones), así que no entran en el conteo de «los tres leídos» en ningún caso.

### 1.4 Duración en LETRAS — sustrato disponible

9 de 26 documentos limpios traen un numeral en palabras junto a `dias`/`Duracion`:

| formato observado | archivos | nota |
|---|---|---|
| `Dias: 2 (DOS DIAS)` / `Dias: 1 (UN DIA)` | 4 falsas (<NOMBRE> ×3, <NOMBRE> 16072026) | el más limpio |
| `DiaS:2(DOSDIAS)` | `FALSA-08.pdf` | **pegado** |
| `Dias de incapacidad: 02 dos dia(s)` | `FALSA-10.pdf` | |
| `Dias de incapacidad:02dosdia(s)` | `FALSA-09.jpeg` | **pegado, sin separador** |
| letras sin número legible | `CED-08`, `CED-12`, `CED-19` (reales), `INC <NOMBRE> … 25022026.pdf` (falsa) | aquí la letra **recupera** el dato que el número perdió |

Dos consecuencias para el trabajo que está en curso en `extract.py`:

- el patrón **debe tolerar el glue** (`02dosdia(s)`, `2(DOSDIAS)`): sin eso pierde los 2 casos más
  interesantes, incluido el único incoherente del corpus;
- en 4 documentos la letra está pero el número no se leyó → `dias_letra` sirve además como
  **fuente de respaldo del dato**, no solo como control cruzado. Eso amplía la cobertura de la regla
  estrella más que cualquier regla nueva.

### 1.5 Fecha de expedición: el rótulo que no se lee

`fecha_expedicion` se lee hoy en **2 de 26** documentos porque `extract.py` solo ancla en
«expedición». Pero **11 de 31 documentos imprimen una fecha de impresión/emisión** con otros
rótulos: `Impresion: 20/04/2026`, `Impreso: 09/06/2026 12:00:18`, `impresion:14/07/202613:05PM`,
`Impresion 10/06/2026 10:06:14`, `Impresopor:-18/07/202602:30am`.

En los **9** casos donde la fecha de impresión y el inicio son ambos legibles, el desfase es
**exactamente 0 días en los 9**. Conclusión doble:

- añadir la variante de rótulo sube la cobertura de 2 a ~11 documentos: es la mejora más barata;
- pero la señal **no discrimina nada** en este corpus (siempre 0) → la regla de expedición nace como
  **AVISO**, no como detector. Y «impresión» ≠ «expedición»: una **reimpresión** posterior es normal
  (dos archivos distintos del corpus comparten `Impresion: 14/07/2026`).

### 1.6 Retroactividad y prórroga: el documento ya lo declara

- **`Incapacidad retroactiva`** aparece como **rótulo de formulario** en 13 documentos (formato Sura
  y similares). Ojo: es la **etiqueta**, no el valor; el OCR casi siempre pierde el `Sí/No` de al
  lado. **Usar la presencia del rótulo como si fuera el valor es un falso positivo garantizado.**
- **`Prorroga: No` / `Es Prorroga: No` / `Prorroga SI`** se imprime en **9 de 31** documentos y el
  extractor **no lo lee**. Y `REAL-13.pdf` — documento **real**, 30 días — declara
  `Prorroga SI`. Es decir: **la prórroga legítima existe y es visible en el papel**. Cualquier regla
  de solapamiento/contigüidad que la ignore marcará documentos buenos.

### 1.7 Solapamiento: sin evidencia local

El corpus tiene 3 cédulas con más de un documento. El grupo mayor
(`INC <NOMBRE> <NOMBRE> …` ×4: 2025-09-15, 2025-10-31, 2025-11-10, 2026-04-20) **no solapa en ningún
par**. **0 solapamientos en 26 documentos** → la familia no se puede validar con el corpus; necesita
el histórico del ERP (`lpausentismos`), que **no existe** en `sql/init.sql` (la BD demo local solo
trae catálogos). Se declara **no evaluable** y se documenta la consulta exacta (§5).

### 1.8 Potencia estadística — advertencia obligatoria

Los reales evaluables por la regla estrella son **3**. Observar 0 falsos positivos en 3 casos es
compatible con una tasa real de hasta ~55 % (IC 95 % de 0/3). **La medición prueba que la regla es
implementable y que hoy está ciega; NO prueba que sea segura.** Antes de activarla en BLOQUEA hay que
calibrarla contra el histórico legítimo del ERP, exactamente como hizo la sonda hermana
(`senales/dias_vs_diagnostico/referencia_dias_por_dx.sql` §3).

---

## 2. Invariantes que YA viven en el repo

| invariante | dónde vive | ¿se valida? | hueco |
|---|---|---|---|
| Fecha de inicio preferida = la rotulada "Fecha Inicia/Inicial"; si falta, `inicio = fin − (días−1)` | `extract.normalizar_fechas`, `erp.mapear_a_staging` | **se aplica, no se valida** | derivar y validar están fundidos en la misma función; no hay forma de preguntar "¿esto lo leí o lo calculé?" salvo para el inicio |
| `fechavencimiento = fechainicio + Numerodias` (no inclusivo) | `erp.mapear_a_staging` (`fecha_venc`) | se **calcula**, nunca se comprueba | si el auxiliar edita `Numerodias` en la UI y el `INSERT` no recalcula, la fila rompe una invariante del ERP sin que nadie lo note |
| `dias` válido = 1..540 | `erp.mapear_a_staging` (problema + campo faltante) y `extract.normalizar_fechas` | **sí, en `erp`** | `normalizar_fechas` pone `n = None` **antes**, en silencio: el valor fuera de rango se descarta sin dejar rastro y el auxiliar ve "no se detectó el número de días" en vez de "el documento dice 900 días" |
| `0 ≤ (fin − inicio) ≤ 540`, si no se anula el dato menos fiable | `extract.normalizar_fechas` (saneo final) | se **corrige**, no se reporta | anula `fecha_inicio` o `fecha_fin` sin marca; la incoherencia de orden desaparece antes de poder reportarla |
| Fecha de inicio derivada se avisa y **no bloquea** | `extract.normalizar_fechas` → `fecha_inicio_calculada` → `erp` → UI | sí | no es fiable al 100 % (§1.3, `REAL-08.pdf`) y **no tiene gemelos** para fin ni para días |
| Fecha inválida nunca entra al `INSERT` | `erp.mapear_a_staging` (`_safe_date`) | sí | la fecha imposible se descarta en silencio: `2026-06-31` se vuelve "no se detectó la fecha", no "el documento trae una fecha imposible" |
| Vacaciones: días **siempre** por diferencia de fechas, nunca por rótulo | `extract` (`_fechas_vacaciones`) + CLAUDE.md | sí (por diseño) | por eso **toda** regla de coherencia y de letras debe excluir `tipo_documento = vacaciones`: sus días son derivados por construcción |
| Documentación incompleta → `INCOMPLETA` + alerta, **pero entra a staging** | `erp.validar_documentacion` | sí | **es el patrón a imitar**: marcar y explicar, dejar decidir |
| No se aprueba con obligatorios faltantes → 409 | `webapp.py` (`requiere_revision`) | sí | el gate es **binario y solo sobre `problemas`**: no distingue severidades y no se puede liberar con una confirmación humana |

---

## 3. Modelo de severidades

Tres niveles. La diferencia no es el color en la UI: es **qué le pasa al registro**.

| severidad | qué significa | efecto EXACTO en el flujo del repo | quién lo levanta |
|---|---|---|---|
| **BLOQUEA** | los datos temporales del documento se contradicen entre sí: alguno está mal *seguro* | el registro **entra igual** a `lp_ausentismos_ia` como `PENDIENTE_REVISION`. `POST /api/revisar?accion=aprobar` responde **409** hasta que el auxiliar (a) corrija el dato — y el remapeo haga desaparecer la alerta — **o** (b) marque la casilla «verifiqué las fechas contra el documento» | el auxiliar, con una acción explícita |
| **ALERTA** | patrón atípico que suele indicar adulteración, pero tiene lecturas legítimas | **no bloquea**. Se guarda en la fila y se muestra destacado; el auxiliar aprueba o rechaza | nadie: es informativo y queda auditado |
| **AVISO** | contexto para el revisor; mismo rango que `fecha_inicio_calculada` o `eps_de_empleado` | no bloquea, no destaca. Solo se muestra | nadie |

**Lo que BLOQUEA jamás significa** (restricción no negociable del proyecto):

- no rechaza el documento — `RECHAZADO` solo lo fija un humano;
- no impide el `INSERT` en staging — el auxiliar necesita ver la fila para poder juzgarla;
- no impide reprocesar ni corregir;
- **nunca** escribe en `lpausentismos`.

**Por qué NO se puede reutilizar `problemas` tal cual.** Hoy `requiere_revision = len(problemas) > 0`
y `webapp.py:285` devuelve 409 con eso. Si una regla AVISO ("documento de hace 120 días") escribe en
`problemas`, el registro queda **inaprobable de forma permanente**: el auxiliar no tiene ningún campo
que editar para que la frase desaparezca. Por eso:

- se añade una lista **`alertas_temporales`** al retorno de `mapear_a_staging` (mismo estilo que
  `campos_faltantes`: lista de dicts con `id`, `severidad`, `mensaje`, `datos`);
- se añade **una** columna `alertas_temporales JSON NULL` a `lp_ausentismos_ia` (una sola, no una por
  regla — así añadir reglas no toca el DDL);
- el gate de aprobación pasa a ser
  `requiere_revision or (hay BLOQUEA and not confirmacion_tiempos)`. La confirmación es un campo
  nuevo del `POST /api/revisar`, y se registra en `observaciones` para auditoría.

**Sin BD** la fila no se puede insertar, exactamente como hoy; las reglas que necesitan BD devuelven
`NO_EVALUABLE` y el resto sigue funcionando.

---

## 4. Cómo se hace ESCALABLE y ACTUALIZABLE

Es lo que el cliente pidió con «que sea escalable y actualizado».

**Escalable = añadir una regla es añadir una declaración.** Una tabla de declaraciones en Python y un
motor que la recorre:

```
REGLAS_TEMPORALES = [
    ReglaTemporal(
        id="FECHAS_TRIPLE_INCOHERENTE",
        requiere=("inicio_leido", "fin_leido", "dias_leidos"),   # ← el motor verifica esto
        excluye_tipos=(13,),                                     # vacaciones: días derivados por diseño
        severidad_default="BLOQUEA",
        evalua=_triple,
        mensaje="El documento dice {dias} días pero de {inicio} a {fin} hay {dias_calc}",
    ),
    ...
]
```

Contratos del motor (uno solo, `evaluar_tiempos(hechos, config, lookups)`):

- **`requiere` es declarativo**: si algún dato falta, la regla devuelve `NO_EVALUABLE` con el motivo
  y **el motor no llama a `evalua`**. Ninguna regla puede explotar por un `None` ni por falta de BD;
  es el mismo contrato que `LookupsNulos` ya cumple.
- **`evalua` solo recibe `hechos`** (un objeto con procedencia: `inicio`, `inicio_leido: bool`, …).
  No lee `date.today()`, no abre conexiones, no importa nada perezoso: eso lo hace el motor. Así la
  regla es una función pura y testeable sin BD ni red.
- el motor devuelve **siempre** la lista completa de resultados (incluidos `OK` y `NO_EVALUABLE`)
  para que la cobertura sea medible en producción, y `mapear_a_staging` solo publica los que no
  son `OK`.

**Actualizable = severidades y umbrales sin volver a desplegar.** Tabla nueva
`lp_reglas_temporales(id VARCHAR(60) PK, activa TINYINT, severidad VARCHAR(10), parametros JSON,
actualizado_en TIMESTAMP)`, leída una vez por proceso con caché y **fallback a los valores declarados
en código si la BD no está o la fila no existe**. Un `UPDATE` cambia el umbral de radicación o baja
una regla de BLOQUEA a AVISO en caliente. Por encima, override por variable de entorno para el
arranque en frío. Precedencia: **BD > entorno > default declarado**.

Esto también resuelve el arranque: **toda regla nueva nace `activa = 1` con severidad `AVISO`**; se
sube a ALERTA/BLOQUEA solo cuando su tasa de falsos positivos esté medida contra el histórico.

**Prerrequisito de lectura — sin esto la familia no arranca.** El motor necesita **procedencia**.
Propuesta (a decidir por quien edita `extract.py`, aquí solo se describe):

- `normalizar_fechas()` **conserva** lo leído antes de reconciliar, en un sub-dict nuevo
  `incapacidad.leido = {fecha_inicio, fecha_fin, dias}`, y añade `fecha_fin_calculada` y
  `dias_calculados` junto a la ya existente `fecha_inicio_calculada`;
- no cambia **nada** de su comportamiento actual de reconciliación (la regla del cliente se queda
  igual): solo deja de **perder** el dato original.

Es un cambio aditivo y compatible: quien lee `inca["fecha_fin"]` sigue viendo lo mismo. **Este
documento no lo implementa** — `extract.py` y `tests/test_processor.py` están siendo editados por
otro trabajo y son de solo lectura aquí.

---

## 5. Catálogo de reglas

Severidad = **propuesta**; el valor efectivo lo manda `lp_reglas_temporales`.
«Evaluable hoy» = con el pipeline tal como está en disco hoy (2026-09-02).

### R-T01 · `FECHAS_TRIPLE_INCOHERENTE` — la regla estrella

- **Afirma:** si `fecha_inicio`, `fecha_fin` y `dias` están los **tres impresos en el documento**,
  entonces `(fin − inicio) + 1 == dias` (conteo inclusivo, el del dominio del repo).
- **Cálculo:** `dias_calc = (fin − inicio).days + 1`; dispara si `dias_calc != dias`. Adjunta el
  desfase con signo (`dias − dias_calc`) para que el auxiliar vea la magnitud.
- **Datos:** `leido.fecha_inicio`, `leido.fecha_fin`, `leido.dias` **con procedencia** = leída.
- **Severidad:** **BLOQUEA** (nace en AVISO hasta calibrar; ver §1.8).
- **Evaluable hoy:** **NO.** Falta la procedencia y `normalizar_fechas()` reescribe el fin.
  Con el cambio aditivo de §4: sí, en 9/26 documentos.
- **Falso positivo que la hunde:**
  1. **tomar un valor derivado por impreso** — es el escenario del enunciado y ya ocurre en 8/31
     documentos del corpus (§1.3): sin procedencia la regla es ruido puro;
  2. **error de un dígito del OCR** — el único positivo del corpus (`…05062026.jpeg`, mes `06`→`07`)
     puede ser exactamente esto. Mitigación: no auto-corregir nada, mostrar los dos valores leídos
     lado a lado y exigir confirmación humana (que es justo lo que hace BLOQUEA);
  3. **«Fecha de Emisión» tratada como inicio** — CLAUDE.md documenta que en el formato Clínica
     Medical Duarte la emisión se usa como inicio. Ahí los tres valores **no** son homogéneos y la
     aritmética inclusiva no aplica → la regla debe exigir que el inicio venga de un rótulo de
     inicio, no de emisión;
  4. **`Hasta:` robado a otro campo** por el desorden del OCR de tablas (`_find_date` ya tiene una
     defensa parcial para esto);
  5. **vacaciones y permisos**: días derivados por diseño → excluidos por `excluye_tipos`.

### R-T02 · `DIAS_FUERA_DE_RANGO` — 1..540 y días no positivos

- **Afirma:** `1 ≤ dias ≤ 540`.
- **Cálculo:** comparación directa sobre el valor **leído**.
- **Datos:** `leido.dias`. **Severidad:** ALERTA. **Evaluable hoy:** **parcialmente**.
- **Ojo — NO reimplementar:** `erp.mapear_a_staging` **ya** emite
  «Número de días fuera de rango (=N)». Lo que falta es otra cosa: `normalizar_fechas()` pone
  `n = None` **antes** de llegar allí, así que en la práctica el mensaje casi nunca se ve y el
  auxiliar lee «no se detectó el número de días». La acción correcta es **conservar el valor crudo**,
  no añadir una regla nueva.
- **Falso positivo:** un día del mes leído como duración (`Dias de Incapacidad:` vacío seguido de
  `11/7/2026` en `REAL-04.pdf`) o basura numérica de un rótulo vecino — ver R-T03,
  que es el caso medido y real.
- **Medición:** 0 casos fuera de rango en el corpus limpio.

### R-T03 · `DIAS_IMPLAUSIBLE_SIN_FECHAS` — el número solo, sin nada que lo respalde

- **Afirma:** un `dias` grande (> `UMBRAL_DIAS_SOSPECHOSO`, propuesta 60) **sin ninguna fecha leída**
  que lo respalde es más probablemente un error de lectura que un dato.
- **Cálculo:** `dias > umbral AND not inicio_leido AND not fin_leido`.
- **Datos:** `leido.dias`, procedencia de fechas. **Severidad:** AVISO. **Evaluable hoy:** sí (con
  procedencia; sin ella, aproximable).
- **Por qué existe — caso medido:** `REAL-16.jpeg`, documento **REAL**, sale del
  pipeline con **`dias = 202`**. El texto es `MARTES 09 DE/JUNIO Duracion` y en la línea siguiente
  `DE2026`: el patrón `duraci[oó]n\b[^\d]{0,10}(\d{1,3})` capturó **`202` de `2026`**. Está dentro
  de 1..540, así que R-T02 **no lo ve**. Si además se hubieran leído las fechas,
  `normalizar_fechas()` habría reescrito el fin a inicio+201 días y esa fila habría llegado al ERP
  con una incapacidad de 202 días inventada. Esta regla es la red de seguridad de ese fallo.
- **Falso positivo:** licencias de maternidad (126 días, medido y legítimo en
  `REAL-09.pdf`) e incapacidades prolongadas reales. Por eso el umbral es
  parametrizable, la severidad es AVISO y la condición exige **ausencia total** de fechas.

### R-T04 · `ORDEN_FECHAS_INVERTIDO` — inicio ≤ fin

- **Afirma:** `fecha_inicio ≤ fecha_fin`.
- **Cálculo:** comparación sobre los valores **leídos**. **Datos:** ambas fechas leídas.
- **Severidad:** BLOQUEA. **Evaluable hoy:** **no de forma observable** — el saneo final de
  `normalizar_fechas()` ya **anula** una de las dos cuando el rango es imposible, así que la señal se
  destruye antes de poder reportarse (el auxiliar ve «no se detectó la fecha de inicio»).
- **Falso positivo:** ambigüedad `dd/mm` vs `mm/dd` (un `06/07/2026` se lee al revés y el orden se
  invierte solo); OCR de tabla que cruza los valores de dos rótulos vecinos. Mitigación: reportar
  ambas fechas tal como se leyeron y **no** deducir el formato.
- **Medición:** 0 casos en el corpus.

### R-T05 · `VENCIMIENTO_INCONSISTENTE` — la invariante del ERP

- **Afirma:** en la fila que se va a insertar, `fechavencimiento == fechainicio + Numerodias`
  (**no inclusivo**, como manda CLAUDE.md).
- **Cálculo:** comprobación de la fila final, después de aplicar `overrides` del auxiliar.
- **Datos:** los tres campos de la fila. **Severidad:** BLOQUEA. **Evaluable hoy:** **sí, ya**.
- **Por qué:** hoy el vencimiento se **calcula** y nunca se comprueba. Es una asercíon de
  post-condición: protege la promoción a `lpausentismos` de que una corrección manual en la UI o un
  camino de código futuro deje la fila fuera de la invariante. Coste ~0, valor alto.
- **Falso positivo:** ninguno mientras la comprobación se haga sobre la fila final y no sobre lo
  leído del documento (que usa conteo **inclusivo** — mezclar los dos conteos es el único error
  posible aquí, y es un error de programación, no un falso positivo de datos).

### R-T06 · `EXPEDICION_POSTERIOR_AL_INICIO`

- **Afirma:** `fecha_expedicion ≤ fecha_inicio + TOLERANCIA_EXPEDICION` (propuesta: 0 días; una
  incapacidad no se expide después de haber empezado, salvo retroactiva declarada).
- **Cálculo:** diferencia en días. **Datos:** `fecha_expedicion` leída + `fecha_inicio` leída.
- **Severidad:** **AVISO**. **Evaluable hoy:** **NO** — 2/26 documentos.
- **Prerrequisito barato y medido:** añadir los rótulos `Impres(o|ión)` / `Emisión` sube la cobertura
  a ~11/31 (§1.5).
- **Falso positivo (por esto es AVISO, no ALERTA):**
  1. **`Impresión` no es `expedición`**: una reimpresión posterior es normal y en el corpus dos
     archivos distintos comparten `Impresion: 14/07/2026`;
  2. **la incapacidad retroactiva es legítima y el propio documento tiene un campo para ella** — y el
     rótulo `Incapacidad retroactiva` aparece en 13 documentos **sin que el OCR recupere el valor**:
     leer el rótulo como si fuera un `Sí` es un falso positivo garantizado;
  3. en los 9 casos medibles el desfase es **0 en los 9** → la regla no discrimina nada en esta
     muestra; su valor es de saneo, no de detección.

### R-T07 · `FECHA_INICIO_MUY_FUTURA`

- **Afirma:** `fecha_inicio ≤ fecha_recepcion + UMBRAL_FUTURO_DIAS` (propuesta: 8 días).
- **Cálculo:** diferencia en días contra la fecha de **recepción** del documento.
- **Datos:** `fecha_inicio` leída + fecha de recepción. **Severidad:** ALERTA. **Evaluable hoy:** sí.
- **Falso positivo:** **prelicencia (tipo 10)** y **licencia de maternidad (5)** se expiden por
  anticipado por definición; las **vacaciones (13)** se notifican con semanas de antelación (CLAUDE.md
  documenta una carta con periodo `2026-05-29 … 2026-07-06`). Sin `excluye_tipos = (5, 10, 13)` esta
  regla marca sistemáticamente documentos correctos.
- **Medición:** 0 casos (todas las fechas de inicio del corpus son pasadas).

### R-T08 · `RADICACION_FUERA_DE_PLAZO` — umbral a confirmar con el cliente

- **Afirma:** `fecha_recepcion − fecha_inicio ≤ UMBRAL_RADICACION_DIAS`.
- **Cálculo:** diferencia en días. **Datos:** `fecha_inicio` leída + fecha de recepción.
- **Severidad:** AVISO. **Evaluable hoy:** **NO** — el umbral **no se puede inventar** (§6, P1) y hay
  un defecto de medición que hay que arreglar primero.
- **El defecto, medido:** con `hoy = 2026-09-02` la antigüedad del corpus es 46..101 días (reales) y
  50..352 (falsas). **Cualquier umbral por debajo de ~100 días marca los 14 documentos reales.**
  La causa es que `erp.mapear_a_staging` usa `fecharegistro = date.today()`: **reprocesar un lote
  viejo hace que todo parezca fuera de plazo.** La regla debe usar la fecha en que el documento
  **llegó** (`mtime` del archivo en `1_entrada/`, o el timestamp de la corrida del lote), no la fecha
  de proceso.
- **Falso positivo:** además del anterior, un documento legítimamente antiguo que se radica tarde por
  culpa del trabajador o de la EPS **no es un documento falso**. Esta regla es un control
  **operativo** (¿se puede cobrar a la EPS?), no un detector de fraude: mezclar las dos cosas
  contamina la señal de falsedad.
- **Anclaje real disponible:** dos documentos del corpus imprimen su propio plazo —
  `Favor tramitar la incapacidad antes de 72 horas` (EPS Sanitas). Es una instrucción del emisor, no
  una norma general: **sirve como dato para preguntarle al cliente, no como umbral**.
- **NO usar la antigüedad como indicio de adulteración:** en este corpus correlaciona con la clase
  (falsas desde 2025, reales todas 2026) pero eso es el sesgo de recolección de la muestra (§1 punto 7).

### R-T09 · `DIAS_LETRA_VS_NUMERO` — discrepancia letras/números

- **Afirma:** si el documento imprime la duración en **números** y en **letras**, ambas coinciden.
- **Cálculo:** consume `dias_letra` y `dias_letra_coincide` del JSON (los está añadiendo otro
  trabajo). Si `dias_letra_coincide is False` → dispara. Si los campos no están → `NO_EVALUABLE`.
- **Datos:** `dias` leído, `dias_letra`, `dias_letra_coincide`. **Severidad:** **ALERTA**.
- **Evaluable hoy:** **NO** (los campos aún no existen). Sustrato medido: 9/26 (§1.4).
- **Por qué ALERTA y no AVISO:** es la señal **más específica** de adulteración de toda la familia.
  Quien altera un certificado retoca el **dígito**; reescribir además la palabra es más trabajo y más
  visible. Una discrepancia número/letra en un impreso generado por sistema no tiene lectura
  legítima. Es exactamente el mecanismo del motivo del cliente «ALTERACION EN FECHA DE INICIO,
  DURACION Y FECHA FIN».
- **Falso positivo:**
  1. **el numeral en letras no siempre es una duración** — CLAUDE.md ya advierte que en las cartas de
     vacaciones `el día siete (07) de julio` es un **día del mes**; hay que excluir
     `tipo_documento = vacaciones` y exigir adyacencia al rótulo de días;
  2. **glue del OCR** (`02dosdia(s)`, `2(DOSDIAS)`): si el patrón no lo tolera, la regla se declara
     no evaluable justo en los casos interesantes — mejor `NO_EVALUABLE` que un falso «no coincide»;
  3. **letras mal leídas** (`DOS`→`DDS`, `UN`→`UM`): la comparación debe fallar a `NO_EVALUABLE`
     cuando la palabra no está en el diccionario de numerales, **nunca** a «no coincide»;
  4. concordancia de plural (`1 (UN DIA)` vs `1 (UNA DIA)`) — irrelevante para el número, no debe
     influir.
- **Bonus medido:** en 4 documentos la letra está y el número **no** se leyó → `dias_letra` también
  sirve de respaldo del dato y **sube la cobertura de R-T01**, que es el mayor problema de la familia.

### R-T10 · `SOLAPAMIENTO_MISMO_EMPLEADO` — necesita BD

- **Afirma:** el intervalo `[inicio, inicio + dias − 1]` no se cruza con otro ausentismo del **mismo
  empleado** ya registrado, salvo prórroga declarada.
- **Datos:** `idlpempleado` resuelto, `fechainicio`, `Numerodias`, + BD (`lp_ausentismos_ia` y el
  histórico `lpausentismos`). **Severidad:** ALERTA. **Evaluable hoy:** **NO** (sin BD; y
  `lpausentismos` **no existe** en la BD demo local — solo en el ERP del cliente).
- **Degradación sin BD:** `NO_EVALUABLE` con motivo `sin_conexion_bd` / `tabla_historica_ausente`.
  El motor no debe importar `mysql.connector` para descubrirlo: se apoya en el `lookups` que ya
  recibe (`LookupsNulos` responde vacío por contrato).
- **Consulta exacta** (`%s` = placeholders de `mysql.connector`; método nuevo del estilo de
  `erp.Lookups.documentos_requeridos`, con `try/except` que degrada a `[]` si la tabla no existe):

```sql
-- Solapamiento contra el HISTÓRICO del ERP (solo lectura).
-- El intervalo del documento es [%(inicio)s, %(inicio)s + %(dias)s - 1] (inclusivo);
-- el del ERP es [fechainicio, fechavencimiento - 1] porque `fechavencimiento` es
-- NO inclusivo (invariante del repo). Dos intervalos se cruzan si cada uno empieza
-- antes de que el otro termine.
SELECT a.idlpausentismos, a.fechainicio, a.Numerodias, a.fechavencimiento,
       a.idlptipoausentismo, a.prorroga, a.idlpausentismo_inicial
FROM   lpausentismos a
WHERE  a.idlpempleado = %(idlpempleado)s
  AND  a.fechainicio          <= DATE_ADD(%(inicio)s, INTERVAL %(dias)s - 1 DAY)
  AND  DATE_SUB(a.fechavencimiento, INTERVAL 1 DAY) >= %(inicio)s
  AND  a.prorroga = 0                     -- una prórroga legítima CONTINÚA el episodio
  AND  a.idlpausentismo_inicial IS NULL   -- (mismos filtros que usa la sonda hermana)
ORDER BY a.fechainicio
LIMIT  10;

-- Y contra el propio STAGING, para el caso mucho más frecuente: el mismo documento
-- reenviado por WhatsApp. `archivo_origen <> %(archivo)s` y `id <> %(id)s` evitan que
-- la fila se compare CONTRA SÍ MISMA (la ingesta aún no tiene ledger/dedup).
SELECT s.id, s.fechainicio, s.Numerodias, s.fechavencimiento, s.estado, s.archivo_origen
FROM   lp_ausentismos_ia s
WHERE  s.idlpempleado = %(idlpempleado)s
  AND  s.estado <> 'RECHAZADO'
  AND  (%(id)s IS NULL OR s.id <> %(id)s)
  AND  (s.archivo_origen IS NULL OR s.archivo_origen <> %(archivo)s)
  AND  s.fechainicio <= DATE_ADD(%(inicio)s, INTERVAL %(dias)s - 1 DAY)
  AND  DATE_SUB(s.fechavencimiento, INTERVAL 1 DAY) >= %(inicio)s
ORDER BY s.fechainicio
LIMIT  10;
```

- **Falso positivo (tres, todos reales):**
  1. **la prórroga legítima solapa o pega por definición.** Medido: `REAL-13.pdf`
     (real, 30 días) imprime `Prorroga SI`. Sin los filtros `prorroga = 0` /
     `idlpausentismo_inicial IS NULL` la regla marca continuaciones normales;
  2. **el mismo documento reprocesado.** CLAUDE.md dice explícitamente que la ingesta por lotes
     **no tiene ledger ni dedup**: sin excluir el propio `id`/`archivo_origen`, la primera fila que
     esta regla encuentre será ella misma. Falso positivo del 100 %;
  3. **dos ausentismos concurrentes de origen distinto** (accidente de trabajo + enfermedad general)
     existen en la práctica → la severidad es ALERTA, no BLOQUEA, y el mensaje debe mostrar el tipo
     de la fila que solapa para que el auxiliar decida en un vistazo.

### R-T11 · `PRORROGA_DECLARADA_SIN_ANTECEDENTE` — necesita BD + un campo nuevo

- **Afirma:** si el documento declara `Prorroga: SI`, debe existir un ausentismo previo del mismo
  empleado que termine el día anterior al inicio (o dentro de `TOLERANCIA_CONTIGUIDAD`, propuesta
  1 día).
- **Datos:** flag de prórroga **leído del documento** (campo nuevo, no existe hoy) +
  `idlpempleado` + BD. **Severidad:** AVISO. **Evaluable hoy:** **NO** (faltan ambos lados).
- **Sustrato medido:** 9/31 documentos imprimen el campo (`Prorroga: No`, `Es Prorroga:`,
  `Prorroga SI`); el ERP ya tiene la columna `prorroga` y `idlpausentismo_inicial`. Es una regla
  cerrada de extremo a extremo en cuanto se lea el campo.
- **Falso positivo:** que el ausentismo previo **no esté digitalizado** (es lo normal al arrancar un
  sistema nuevo: el histórico empieza vacío) → por eso AVISO, y por eso conviene una condición de
  guarda: **no evaluar si el empleado no tiene ningún ausentismo previo en el sistema**, porque
  entonces la ausencia de antecedente no informa nada. También: `Prorroga: No` leído como `SI` por
  OCR (el valor suele quedar en la línea siguiente).

### R-T12 · `DUPLICADO_TEMPORAL_EXACTO`

- **Afirma:** no existe ya en `lp_ausentismos_ia` otra fila **no rechazada** con el mismo
  `idlpempleado`, la misma `fechainicio` y el mismo `Numerodias`, proveniente de **otro archivo**.
- **Cálculo:** igualdad exacta de la terna (variante trivial de la 2ª consulta de R-T10).
- **Datos:** `idlpempleado`, `fechainicio`, `Numerodias`, `archivo_origen` + BD **local**
  (`lp_ausentismos_ia`; **no** necesita el histórico del ERP). **Severidad:** ALERTA.
  **Evaluable hoy:** **sí con BD**, `NO_EVALUABLE` sin ella.
- **Por qué está en el catálogo:** con ~7000 incapacidades/mes llegando por WhatsApp, correo y
  ventanilla y **sin dedup en la ingesta**, el reenvío del mismo soporte por dos canales es un
  suceso cotidiano, no un caso raro. Es la regla con mejor relación valor/coste de la lista.
- **Falso positivo:** un empleado con **dos certificados distintos** de la misma fecha y duración
  (posible en la práctica: dos IPS, dos diagnósticos) → ALERTA, nunca BLOQUEA, y el mensaje debe
  mostrar el `id` y el `archivo_origen` de la fila gemela.

---

### Tabla resumen

| id | severidad | evaluable hoy | datos que necesita | medición en el corpus limpio (26) |
|---|---|---|---|---|
| R-T01 `FECHAS_TRIPLE_INCOHERENTE` | BLOQUEA | **no** (falta procedencia) | 3 valores leídos | 9 evaluables · 1 dispara (falsa) · 0 reales |
| R-T02 `DIAS_FUERA_DE_RANGO` | ALERTA | parcial (**ya existe** en `erp`) | `dias` leído | 0 |
| R-T03 `DIAS_IMPLAUSIBLE_SIN_FECHAS` | AVISO | sí | `dias` + procedencia fechas | 1 (real, `dias=202` espurio) |
| R-T04 `ORDEN_FECHAS_INVERTIDO` | BLOQUEA | no (se sanea antes) | 2 fechas leídas | 0 |
| R-T05 `VENCIMIENTO_INCONSISTENTE` | BLOQUEA | **sí** | fila final | invariante, no señal |
| R-T06 `EXPEDICION_POSTERIOR_AL_INICIO` | AVISO | no (2/26) | expedición + inicio | 9 medibles vía `Impresión`, desfase 0 en los 9 |
| R-T07 `FECHA_INICIO_MUY_FUTURA` | ALERTA | sí | inicio + recepción | 0 |
| R-T08 `RADICACION_FUERA_DE_PLAZO` | AVISO | **no** (umbral por confirmar) | inicio + recepción | antigüedad 46..352 d — inusable con `hoy` |
| R-T09 `DIAS_LETRA_VS_NUMERO` | ALERTA | no (campos en curso) | `dias_letra*` | sustrato 9/26, 2 pegados |
| R-T10 `SOLAPAMIENTO_MISMO_EMPLEADO` | ALERTA | no (BD) | empleado + BD | 0 solapamientos en 3 grupos multi-doc |
| R-T11 `PRORROGA_DECLARADA_SIN_ANTECEDENTE` | AVISO | no (BD + campo) | flag prórroga + BD | sustrato 9/31 |
| R-T12 `DUPLICADO_TEMPORAL_EXACTO` | ALERTA | **sí con BD** | terna + `archivo_origen` | no medible sin BD |

**Evaluables hoy sin tocar nada:** R-T03, R-T05, R-T07 (+ R-T12 con BD).
**Se desbloquean con el cambio aditivo de procedencia (§4):** R-T01, R-T02, R-T04.
**Dependen de otro trabajo o del cliente:** R-T06, R-T08, R-T09, R-T10, R-T11.

---

## 6. Preguntas al cliente (Gruppo)

Ninguna se puede responder desde el repo ni desde el corpus. Cada una tiene un parámetro asociado en
`lp_reglas_temporales` para que la respuesta se aplique **sin desplegar código**.

- **P1 — Plazo de radicación.** ¿Cuántos días tiene Gruppo para radicar una incapacidad ante la EPS
  antes de perder el reconocimiento económico, y desde qué fecha se cuenta (inicio de la incapacidad,
  expedición del certificado, o entrega del trabajador a RH)? Dos documentos del corpus imprimen
  «tramitar la incapacidad antes de 72 horas» (EPS Sanitas): ¿es un plazo **por EPS** — y entonces
  el umbral va en `lprequisitos_eps` o similar, no global? → `UMBRAL_RADICACION_DIAS`.
- **P2 — Efecto de una incoherencia de tiempos.** Cuando el documento se contradice a sí mismo
  (dice 2 días pero de la fecha de inicio a la de fin hay 32), ¿el auxiliar debe poder aprobar tras
  confirmar que verificó el papel, o esa incapacidad tiene que devolverse al trabajador **siempre**?
  Esto decide si R-T01 es BLOQUEA-con-confirmación o BLOQUEA-duro. → `severidad` de R-T01.
- **P3 — Qué valor manda en el conteo.** Ante inicio + fin + días contradictorios, ¿cuál es el dato
  autoritativo para la nómina: los **días** impresos o la **fecha fin** impresa? Hoy
  `normalizar_fechas()` decide en silencio que mandan inicio+días y **reescribe el fin**; si el
  cliente dice lo contrario, hay un defecto en producción hoy mismo. → orden de preferencia del motor.
- **P4 — Solapamientos legítimos.** ¿Puede un empleado tener dos ausentismos activos a la vez
  (p. ej. accidente de trabajo + enfermedad general)? Y ¿se registra alguna vez una prórroga como
  fila nueva sin marcar `prorroga = 1` / `idlpausentismo_inicial`? → filtros y severidad de R-T10.
- **P5 — Acceso al histórico.** ¿Puede el middleware hacer `SELECT` sobre `lpausentismos` en ASTGU
  (usuario de solo lectura), y desde qué fecha hay datos fiables? Sin esto, R-T10 y R-T11 quedan
  permanentemente `NO_EVALUABLE` — la BD demo local **no** tiene esa tabla.
- **P6 — Fecha de recepción.** ¿Se puede confiar en la fecha de llegada del archivo a
  `ingesta/1_entrada/` como fecha de recepción, o RH copia documentos viejos en lotes (lo que
  destruiría `mtime`)? De esto dependen R-T07 y R-T08, y es la causa del defecto medido en §1.6.
- **P7 — Retroactividad.** Cuando la EPS marca «Incapacidad retroactiva», ¿es un caso normal o
  requiere revisión especial? Determina si R-T06 puede subir de AVISO a ALERTA.
- **P8 — Tope de días.** El repo usa 1..540 días como rango válido. ¿De dónde sale ese 540 y hay un
  tope distinto por tipo de ausentismo (maternidad 126, paternidad 14, …)? → `UMBRAL_DIAS_*` y los
  pisos legales, que ya empezó a tabular la sonda `dias_vs_diagnostico`.

---

## 7. Duplicaciones a evitar

1. **`erp.mapear_a_staging` ya valida el rango de días** («Número de días fuera de rango (=N)») y ya
   reporta «No se detectó la fecha de inicio» / «No se detectó el número de días». R-T02 **no debe
   reimplementarlo**: debe hacer que ese mensaje llegue a verse (hoy `normalizar_fechas` anula el
   valor antes).
2. **`fecha_inicio_calculada` ya es el aviso de "fecha derivada"** y ya viaja hasta la UI. No crear
   una segunda regla de "fecha calculada": extender el mismo mecanismo a fin y días.
3. **`erp.validar_documentacion` ya es el patrón de validación del repo** (estado + lista de
   faltantes, marca y no bloquea, degrada sin BD). El motor temporal debe **imitar esa forma**, no
   inventar otro estilo de reporte.
4. **La familia `dias_vs_diagnostico`** (`senales/dias_vs_diagnostico/`) ya cubre si la duración es
   plausible **para el diagnóstico**, con pisos legales y percentiles del histórico. Este catálogo
   **no** entra ahí: aquí solo hay aritmética, y R-T03 se limita a "el número no tiene ninguna fecha
   que lo respalde" (error de lectura), que es otra cosa.
5. **Las familias `dx_catalogo`, `firma_y_reuso` y `tipografia_pdf`** ya están asignadas a otras
   sondas. Nada de este catálogo mira el CIE-10, la firma ni las fuentes del PDF.
6. **`_safe_date` de `erp.py` y `extract.py`** ya normalizan y validan fechas. No añadir un tercer
   parser: reutilizar.
7. **`LookupsNulos` ya es el contrato de degradación sin BD.** Las reglas con BD deben pedir sus
   datos por ahí y recibir vacío, no abrir conexiones propias ni comprobar `db_disponible()`.
8. **`webapp.py` ya tiene el gate de aprobación con 409.** No crear un segundo gate: extender la
   condición existente con la confirmación temporal.
9. **`senales/aritmetica_fechas/` está vacía** (sin `INFORME.md`) a fecha de este documento: no hay
   trabajo previo de esta familia sobre el que construir. Si aparece después, hay que reconciliar
   los ids `R-T0x` con los suyos antes de implementar.
