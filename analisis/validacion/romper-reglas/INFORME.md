# Frente `romper-reglas` — ataque adversario al motor de reglas de tiempos

Objetivo: que `incapacidad_ocr.reglas_tiempo` / `validacion_temporal` dé un veredicto
INCORRECTO o se caiga. Ataque con contextos degenerados, configuración hostil, extensión
mal hecha del catálogo y el camino real de la revisión humana.

* Código de los ataques: `dataset-falsedad/validacion/romper-reglas/0{1..5}_*.py` (+ `_comun.py`).
* Python del proyecto, sin BD, sin red, sin OCR: `.venv/Scripts/python.exe 0X_....py`.
* `hoy` fijado a **2026-09-02** en todos los casos (deterministas hoy y en dos años).
* Baseline antes de juzgar: `tests/test_validacion_temporal.py` → **TODO OK**. Ninguno de
  los hallazgos de abajo es una regresión: son huecos de la especificación y del guardián.

## 1. Veredicto

**345 comprobaciones, 39 falladas → 13 hallazgos** (2 GRAVE, 5 MEDIA, 6 LEVE).

El núcleo del motor aguantó bien lo que más se le atacó: **la configuración externa es a
prueba de balas** (105 comprobaciones, 0 fallos reales) y **ningún contexto degenerado
—fechas imposibles, días 0/negativos/enormes, tipos mezclados, campos ausentes, bisiesto,
cambios de mes y de año— produjo un veredicto incorrecto ni una excepción**. El tri-estado
funciona: 19 formas distintas de fecha ilegible dan T06 `NO_CUMPLE` con T01/T02/T04
`NO_EVALUABLE`, nunca una violación inventada.

Lo que sí se rompió:

1. **La propiedad clave (ninguna regla juzga un valor CALCULADO) SE VIOLA** en el camino
   real de la revisión humana: el formulario de la UI devuelve el valor derivado como si el
   auxiliar lo hubiera tecleado. Ahí T09/T10/T14 pasan a `NO_CUMPLE` sobre un dato que el
   papel nunca imprimió, T01 se convierte en un `CUMPLE` tautológico, la confianza sube a
   1.0 y **la aprobación queda bloqueada con un 409 que el auxiliar no puede resolver**.
2. **La extensibilidad no es segura**: una errata en la severidad de una regla nueva
   (paso 2 de la receta) tumba el mapeo entero con `KeyError`, y la frontera
   leído/calculado que el docstring declara "por construcción" solo la vigila una prueba.

## 2. Hallazgos

Severidad: **GRAVE** = veredicto incorrecto que llega al auxiliar o caída del motor ·
**MEDIA** = regla que no evalúa cuando podría, mensaje confuso · **LEVE** = cosmético/estilo.

---

### H1 · GRAVE · Un valor CALCULADO entra como EVIDENCIA cuando el formulario de revisión devuelve lo que se le pintó

**Causa:** `incapacidad_ocr/reglas_tiempo.py:418-421` (`valores_leidos`: un override *siempre*
es evidencia y apaga `inicio_calculado`) + `incapacidad_ocr/erp.py:638`
(`… and "fecha_inicio" not in overrides`) + `incapacidad_ocr/static/index.html:518-519`
(el formulario se rellena con `row.fechainicio` / `row.Numerodias`, es decir el valor
EFECTIVO) y `:499-500` (`overrides()` lo reenvía en cada `/api/mapear` y `/api/registrar`,
tocado o no).

**Entrada** (`03_valor_calculado.py` §C, `05_consecuencias.py` §A y §B):

```python
# el documento solo imprime fin + días (la regla del cliente: inicio = fin − (días − 1))
inca = {"fecha_inicio": None, "fecha_fin": "2026-11-30", "dias": 5}
inca[CLAVE_SNAPSHOT] = snapshot_leidos(inca); normalizar_fechas(rec)   # -> inicio 2026-11-26
m1 = erp.mapear_a_staging(res, "WHATSAPP", lookups, hoy=date(2026, 9, 2))
# el auxiliar abre el caso y pulsa guardar SIN tocar nada -> index.html:499 manda esto:
m2 = erp.mapear_a_staging(res, "WHATSAPP", lookups, hoy=date(2026, 9, 2),
                          overrides={"fecha_inicio": m1["row"]["fechainicio"],   # 2026-11-26
                                     "dias": m1["row"]["Numerodias"]})           # 5
```

**Esperado:** el mismo veredicto que la 1ª pasada. Ningún dato nuevo entró: T09 y T01
siguen `NO_EVALUABLE`, `fecha_inicio_calculada` sigue `True`, la confianza no se mueve.

**Obtenido:** el veredicto cambia sin que nadie haya tecleado nada.

| | 1ª pasada | 2ª pasada (reenvío) |
|---|---|---|
| `requiere_revision` | `False` | **`True`** |
| `problemas` | `[]` | `['La fecha de inicio (2026-11-26) está en el futuro, más de 30 día(s) después de hoy (2026-09-02)']` |
| T09_INICIO_EN_FUTURO | `NO_EVALUABLE` | **`NO_CUMPLE` (MEDIA)** |
| T01_DURACION_VS_RANGO | `NO_EVALUABLE` | **`CUMPLE`** (tautológico: el inicio se derivó de ese mismo fin y esos mismos días) |
| `resumen.cobertura` | 0.385 | 0.846 |
| `fecha_inicio_calculada` | `True` | **`False`** → la UI deja de pintar "(calculada: fin − días)" (`index.html:569`) |
| `row.confianza_ocr` | 0.75 | **1.0** |

Con un documento antiguo (`fin 2023-01-10`, `dias 5`, `expedición 2023-02-01`) el reenvío
hace aparecer de la nada `alertas_tiempos = T10_INICIO_MUY_ANTIGUO; T14_EXPEDICION_POSTERIOR_AL_INICIO`
donde la 1ª pasada tenía `NULL`. En vacaciones pasa por el otro campo: los días los deriva
el extractor de las dos fechas, el reenvío los vuelve "leídos" y T01 pasa de
`NO_EVALUABLE` a `CUMPLE` (cobertura 0.538 → 0.846).

**Por qué es GRAVE, no cosmético:**
* `row.confianza_ocr = 1.0` es exactamente lo que `erp.py:873-875` dice que no debe pasar
  ("si contara, la UI mostraría 100% de confianza sobre una fecha de inicio que el
  documento no imprime") y ese valor **se guarda en la fila**.
* `/api/registrar` y `/api/guardar` responden **409 "No se puede aprobar: faltan datos
  obligatorios. La fecha de inicio (2026-11-26) está en el futuro…"** (`webapp.py:317-322`,
  `:398-405`). El auxiliar no tiene salida desde la UI: cada reenvío reproduce el bloqueo,
  y "arreglarlo" significa teclear otra fecha (falsear el dato) o apagar T09 por SQL. El
  documento (una prelicencia / procedimiento programado, que es legítimo) queda atascado.
* El informe pasa a afirmar que la regla estrella **comprobó** el documento cuando lo único
  que hizo fue comparar un valor con los valores de los que se derivó.

**Propuesta (NO aplicada; toca `erp`/`index.html`, y `index.html` lo está editando otro trabajo):**
que el override viaje solo si el auxiliar CAMBIÓ el campo (comparar contra el valor
pintado, en el JS o en `erp`), o que `valores_leidos` no acepte como evidencia un override
idéntico al valor derivado cuando `fecha_inicio_calculada` es `True`. La segunda es
suficiente y cabe en `reglas_tiempo`.

---

### H2 · GRAVE · Una errata en la severidad de una regla nueva tumba el mapeo entero (`KeyError`)

**Causa:** `reglas_tiempo.py:1055` (`hallazgos.sort(key=… ORDEN_SEVERIDAD[h.severidad])`),
`:292` (`severidad_max`) y `:306` (`puntaje` → `PENALIZACION_SEVERIDAD[…]`). `_aplicar`
valida a conciencia la severidad que llega de FUERA (archivo/BD), pero `config_por_defecto()`
copia la del CATÁLOGO **sin validar nada**.

**Entrada** (`04_motor_y_erp.py` §A1; paso 2 de la receta del catálogo, la severidad se
escribe a mano):

```python
ReglaTiempo("T90_SEVERIDAD_MAL_ESCRITA", "…", "ALTA", _t90, requiere=("inicio_leido",), campo="dias")
```

**Esperado:** lo mismo que con la config externa — se ignora con un aviso y se usa una
severidad válida. El propio docstring del motor promete que "una regla que revienta (bug en
una regla nueva) queda `NO_EVALUABLE` y **NO tumba el mapeo** del documento".

**Obtenido:** `KeyError: 'ALTA'` propagado desde `rt.evaluar()` **y desde
`erp.mapear_a_staging()`** → 500 en `/api/procesar`/`/api/mapear` y documento perdido en el
lote, para TODOS los documentos, no solo para los que disparan la regla nueva. Idéntico con
una `ConfigReglas` construida a mano con una severidad inválida (`02_config_hostil.py` §F).

**Fix mínimo:** validar el CATÁLOGO al importar el módulo (severidad ∈ `ORDEN_SEVERIDAD`,
códigos únicos, `requiere ⊆ CAMPOS_EXIGIBLES`) y/o `ORDEN_SEVERIDAD.get(s, …)` en los tres
sitios. Hoy el único guardián es `tests/test_validacion_temporal.py` [1], que hay que
acordarse de ejecutar; la receta del catálogo (paso 4) no lo pide.

---

### H3 · MEDIA · La frontera leído/calculado NO está garantizada "por construcción": `CAMPOS_EXIGIBLES` es documentación

**Causa:** `reglas_tiempo.py:1024` (`getattr(ctx, c, None)` sin comprobar
`CAMPOS_EXIGIBLES`) frente al docstring `:21-28` ("Cómo se garantiza en el código (no por
disciplina, por construcción)").

**Entradas y obtenido** (`04_motor_y_erp.py` §A2-A5):

| entrada | esperado | obtenido |
|---|---|---|
| `requiere=("dias_efectivo",)` | el motor rechaza la declaración | la evalúa: **`NO_CUMPLE` sobre un valor reconciliado** |
| cuerpo que lee `ctx.fin_efectivo`, `requiere` legal | idem | `NO_CUMPLE` "el fin efectivo es 2026-06-05" |
| `requiere=("fin_leidoo",)` (errata) | error visible al desarrollador | `NO_EVALUABLE` **para siempre**, y el motivo que lee el auxiliar es "no se pudo comprobar: falta fin_leidoo" |
| código duplicado (copiar-pegar la entrada) | rechazado | el informe lista `T01_DURACION_VS_RANGO` **dos veces** con `afirma`/severidad distintos, y `CATALOGO_POR_CODIGO` (→ `severidad_de`/`esta_activa`) se queda con la ÚLTIMA entrada |

La única defensa es la prueba [1], que además revisa el cuerpo con `inspect.getsource`: un
`getattr(ctx, "dias_" + "efectivo")` la evade. Con el mismo `assert` al importar que pide
H2 se cierran las cuatro.

---

### H4 · MEDIA · `dias_leidos` sin techo: un entero enorme por la API rompe el INSERT de la fila

**Causa:** `reglas_tiempo.py:353-371` — `entero_dias` acota las CADENAS a 6 cifras
(`_MAX_DIGITOS_DIAS`, y el docstring dice que es para que no entre basura como duración)
pero devuelve **cualquier `int` nativo tal cual**; `erp.py:950` escribe
`"dias_leidos": ctx_tiempos.dias_leido`; `sql/init.sql:124` declara `dias_leidos INT NULL`;
`webapp.py:112` deja pasar cualquier `int` (el tope `MAX_LARGO_OVERRIDE` solo se aplica a `str`).

**Entrada** (`04_motor_y_erp.py` §C1, `05_consecuencias.py` §D):
`POST /api/mapear` con `{"campos": {"dias": 999999999999}}` (o `10**10`, o 400 cifras).

**Esperado:** el mismo saneo que para `"1234567"` → `None`, y T05 explicando "el número de
días leído no es un entero utilizable".

**Obtenido:** `row["dias_leidos"] = 999999999999` (12 cifras; `Numerodias` sí queda `NULL`,
eso está bien). `db.insertar_staging` lo pasa verbatim al driver y MySQL 8 en modo estricto
(`docker-compose.yml` no cambia `sql_mode`) rechaza el INSERT con **1264 Out of range value
for column 'dias_leidos'** → `rollback` + `raise` → **el documento no queda en staging**.
Además, con un entero de 400 cifras el mensaje de T03 llega a **462 caracteres** en la
columna `problemas` y en la pantalla del auxiliar (`recortar()` existe justo para eso, pero
T03 imprime el `int` ya parseado).

*No pude ejecutar MySQL en esta máquina: el valor en la fila y el tipo de la columna están
comprobados; el error 1264 es la consecuencia documentada del modo estricto.*

---

### H5 · MEDIA · Un valor de solo espacios se reporta como "leí este dato y no sirve" (y silencia el mensaje claro)

**Causa:** `reglas_tiempo.py:499-500` — `_sin_dato` solo considera vacío `""`, no `"   "`.

**Entrada** (`01_contextos_degenerados.py` §B, `04_motor_y_erp.py` §C2):
`overrides={"fecha_inicio": "   "}` (pasa el filtro de `webapp.py:110` y el de `erp.py:617`,
porque `"   " not in (None, "")`).

**Esperado:** dato ausente → T06 `NO_EVALUABLE` y `erp` pidiendo el campo con
"No se detectó la fecha de inicio".

**Obtenido:** T06 `NO_CUMPLE` (MEDIA) con el mensaje
`"La fecha de inicio leída no es una fecha válida (=   ): se detectó el dato pero no se puede usar"`.
Y como T06 apunta al campo `fecha_inicio`, `erp` lo mete en `campos_explicados` (`erp.py:839`)
y **calla** el mensaje que sí se entendía. Igual con `dias=" "` → T05. Desde el navegador no
pasa (el JS hace `.trim()`), sí desde cualquier llamada directa a la API.

---

### H6 · MEDIA · `fecha_iso` acepta `datetime`: T01/T02/T04 se pierden o dan un GRAVE falso

**Causa:** `reglas_tiempo.py:340-341` — `if isinstance(valor, date): return valor`, y
`datetime` es subclase de `date`. El docstring presume de ser MÁS estricto que
`date.fromisoformat`.

**Entrada (a)** `inicio=datetime(2026,6,1,10,0)`, `fin=date(2026,6,5)`, `dias=9`
→ **esperado** `NO_CUMPLE` (hay desfase) → **obtenido** `NO_EVALUABLE`, motivo "la regla
falló al evaluarse (TypeError)" en T01, T02 y T04 (no se pueden comparar `datetime` y `date`).

**Entrada (b)** `inicio=datetime(2026,6,1,10,0)`, `fin=datetime(2026,6,3,9,0)`, `dias=3`
(un rango correcto de 3 días) → **esperado** `CUMPLE` → **obtenido** **`NO_CUMPLE` GRAVE**:
`"el rango 2026-06-01T10:00:00 → 2026-06-03T09:00:00 son 2 día(s), pero declara 3 día(s)"`
— `(fin-inicio).days` trunca las 23 h. Un falso positivo GRAVE, con la hora impresa en el
mensaje que lee el auxiliar y en `evidencia.leido`.

Hoy ningún llamador del repo mete `datetime` (todo son cadenas ISO y `db._iso_fechas`
convierte), así que es **latente**; la API pública `validar_registro` sí lo permite.
Un `if isinstance(valor, datetime): return valor.date()` lo cierra.

---

### H7 · MEDIA · T01 desaparece en silencio con fechas al final del calendario (`OverflowError`)

**Causa:** `reglas_tiempo.py:535` — `esperado = ctx.inicio_leido + timedelta(days=ctx.dias_leido - 1)`
sin protección contra `date.max`.

**Entrada:** `inicio = fin = "9999-12-31"`, `dias = 5` (año de 4 cifras: `fecha_iso` lo acepta
y `extract._DATE` también).

**Esperado:** `NO_CUMPLE` — el rango son 1 día y declara 5.

**Obtenido:** `NO_EVALUABLE`, motivo "la regla falló al evaluarse (OverflowError)". El
hallazgo GRAVE no llega a `problemas`. El documento no se cuela del todo porque T09 avisa
por otro motivo (inicio en el futuro), pero la regla estrella queda muda justo cuando los
tiempos NO cuadran. Basta calcular `esperado` dentro de un `try` o acotar el año.

---

### H8 · LEVE · T01 y T04 emiten dos GRAVES por el mismo rango y el puntaje se penaliza dos veces

**Entrada:** `inicio=2020-01-01`, `fin=2026-01-01`, `dias=5`.
**Esperado:** un solo mensaje (T04 ya se calla ante T02 y T03 — `reglas_tiempo.py:556-559` —
y la receta dice "si otra regla ya explica ese caso, devuelve None").
**Obtenido:** `['T01_DURACION_VS_RANGO', 'T04_RANGO_MAYOR_AL_MAXIMO', 'T10_INICIO_MUY_ANTIGUO']`
→ dos mensajes que citan el mismo span de 2193 días y **puntaje 15 en vez de 55**. El puntaje
existe para ORDENAR la cola de ~7000 casos/mes, así que el doble castigo distorsiona el orden.

---

### H9 · LEVE · Un override con `None` borra la evidencia impresa

**Causa:** `reglas_tiempo.py:418-423` — `if "fecha_fin" in overrides:` (la clave, no el valor).
**Entrada:** `validar_registro(registro_con_fin_2026-06-20_y_dias_5, overrides={"fecha_fin": None})`.
**Esperado:** un `None` no es una corrección; se conserva lo leído.
**Obtenido:** T01 pasa de `NO_CUMPLE` (GRAVE) a `NO_EVALUABLE`: el hallazgo desaparece.
No es alcanzable por `erp`/`webapp` (los dos filtran `None`/`""` antes), o sea que el módulo
solo está a salvo por cortesía de su llamador.

---

### H10 · LEVE · `hoy=None` tumba el informe con `AttributeError`

**Causa:** `reglas_tiempo.py:1073` — `resumen_evidencia` hace `ctx.hoy.isoformat()` sin guarda.
**Entrada:** `validar_tiempos(construir_contexto(reg, hoy=None))`.
**Esperado:** degradar (T09/T10 ya quedan `NO_EVALUABLE` gracias a `requiere=("hoy",)`).
**Obtenido:** `AttributeError: 'NoneType' object has no attribute 'isoformat'`. Las dos
puertas públicas (`validar_registro`, `mapear_a_staging`) ponen `date.today()`, así que solo
lo alcanza un llamador directo.

---

### H11 · LEVE · Una regla que devuelve algo que no es texto convierte el objeto en el mensaje del auxiliar

**Causa:** `reglas_tiempo.py:1037-1038` — `if mensaje: … str(mensaje)`.
**Entrada:** regla nueva que devuelve `True` / `1` / `3.14` / `["a"]` / `{"m": 1}`.
**Obtenido:** `NO_CUMPLE` con `problemas` = `"True"`, `"1"`, `"3.14"`, `"['a']"`, `"{'m': 1}"`.
(`0`, `[]` y `""` sí se leen como CUMPLE, que es lo razonable.)

---

### H12 · LEVE · `alertas_tiempos VARCHAR(255)` no crece con el catálogo

`sql/init.sql:125` + `erp.py:953` (`"; ".join(veredicto.codigos)`, sin recorte).
Hoy el peor caso realmente alcanzable son **133** caracteres (5 códigos) → sobra sitio.
Pero encender T13/T15/T16/T17 es la vía "actualizable" documentada (`activa: true`, sin
desplegar) y entonces el peor caso son **257 > 255** → MySQL 1406 *Data too long* y el
INSERT se cae; los 17 códigos del catálogo suman **462**. Queda ~122 caracteres de margen,
es decir 4 reglas nuevas.

---

### H13 · LEVE · T11 cuenta como "regla comprobada" en un documento del que no se leyó nada

T11 tiene `requiere=()`, así que siempre se evalúa y siempre CUMPLE si no hay `fin_perdido`.
Con un registro **vacío** el resumen dice `cumplen: 1` y `cobertura: 0.077` en vez de `0.0`;
un documento del que solo se leyó la fecha de expedición sale `COHERENTE` con cobertura
0.077. La cobertura es precisamente el número que evita leer un COHERENTE como "documento
verificado", así que conviene que el denominador no cuente reglas que no miraron nada.

## 3. Lo que se atacó y NO se rompió (para no inflar el informe)

**Configuración externa (105 comprobaciones, 0 fallos reales)** — es la parte más sólida:

* 16 severidades inválidas (`"URGENTE"`, `""`, `None`, `5`, `2.5`, `[]`, `{}`, `True`,
  `"gravísimo"`, `"0"`, `" "`) × 2 vías (archivo y BD): se ignoran con aviso nominal y la
  severidad se queda en la del código. `"grave"`, `"Media"`, `"GRAVE "` sí se aplican (mayúsculas/strip).
* 12 valores de `activa` (`"true"`, `2`, `-1`, `[]`, `0.0`, `None`…): solo `bool` y `0/1`
  se aplican; el resto avisa y la regla **no se apaga en silencio**.
* 22 umbrales: tipo erróneo (`"540"`, `540.0`, `True`, `None`, `[540]`), fuera de
  `LIMITES_UMBRAL`, `10**30`, nombre inexistente, clave `_comentario`. Todos ignorados con
  aviso. `dias_min > dias_max` restaura los dos valores anteriores (probado también en dos
  capas: archivo `dias_max=10` + BD `dias_min=20` → sigue `min <= max`).
* 17 formas de JSON roto: `{no es json`, vacío, `[]`, `5`, `"hola"`, `null`, `true`,
  `reglas` como lista/cadena, `umbrales` como lista, regla como cadena, código desconocido,
  código vacío, BOM, severidad anidada. Nunca excepción, siempre config usable, y la capa
  BD inválida no borra los avisos ni la config del archivo. Prioridad BD > archivo > código
  y `fuentes` traza el origen.
* `datos_bd` con tipos de driver (`bytes`, `Decimal`) → ignorados con aviso.
* Los umbrales SÍ cambian el veredicto (`dias_max=10`, `desfase_tolerado_dias=1`) y bajar
  T01 a LEVE lo saca de `problemas` y lo deja en `avisos` (veredicto `AVISOS`).
* Encender T13/T15/T16/T17 sin el dato → `NO_EVALUABLE`, nunca `NO_CUMPLE`. Un `historial`
  que lanza (`RuntimeError("BD caida")`) o que devuelve basura (`"no soy una lista"`, `0`)
  → `NO_EVALUABLE`, sin tumbar el resto del veredicto.

**Contextos degenerados:** 19 fechas imposibles/basura (`2026-02-30`, `2026-02-29`,
`2026-13-01`, `2026-00-10`, `0000-00-00`, `26-06-01`, `2026-6-1`, `2026/06/01`,
`2026-06-01T00:00:00`, `2026-W23-1`, `20260601`, `9999-99-99`, `-`, `None`, `""`) → T06/T07
`NO_CUMPLE` y T01/T02/T04 `NO_EVALUABLE` en todas. 27 valores de `dias`
(`0`, `-3`, `-5`, `541`, `900`, `"05"`, `" 5 "`, `"+5"`, `5.0`, `5.5`, `"5.0"`, `"dos"`,
`"DOS (2) dias"`, `"1234567"`, `"٥"`, `"²"`, `True`, `False`, `[5]`, `{"d":5}`, `b"5"`,
`10**20`) → siempre el tri-estado correcto y un solo mensaje (T03 y T05 nunca a la vez).
Bisiesto (2024-02-27→03-01 = 4 días; 2023 = 3), cambio de mes y de año, span 540 exacto,
`fin < inicio` (solo T02, T01/T04 callados), bordes de T09 (hoy+30/+31) y T10 (hoy-730/-731).
7 formas raras de registro (`None`, cadena, lista, `int`, `{"incapacidad": None}`, anidado
de `process()`) y 4 de snapshot corrupto → sin excepción, informe serializable.

**Coherencia del informe:** en 4 escenarios, `cumplen+no_cumplen+no_evaluables+desactivadas
== len(CATALOGO)`, `no_cumplen == graves+medias+leves`, `exige_revision ⟺ severidad_max ∈
{GRAVE,MEDIA}`, `veredicto == REVISAR ⟺ exige_revision`, puntaje en 0..100, `mensaje` solo
en `NO_CUMPLE` y `motivo` solo en el resto, y `json.dumps` siempre.

**Camino de producción (foto de `processor` + `normalizar_fechas` real):** 7 casos de
reconciliación (inicio derivado, fin derivado, días derivados, fin reescrito, todo vacío) →
ningún mensaje juzga ni cita el valor derivado; el saneo final que ANULA una fecha no borra
la evidencia (T02 sigue viendo el rango imposible); una regla con bug (`1/0`) queda
`NO_EVALUABLE` y el resto del veredicto sale; dos reglas contradictorias dan un veredicto
determinista y cada una con su `afirma`.

**`erp`:** `fechafin_leida` siempre `NULL` o ISO válido (probado con `2026-02-30`,
`0000-00-00`, `"   "`, `12345`); `Numerodias` nunca lleva un valor fuera de rango;
`severidad_tiempos` cabe en `VARCHAR(10)`; el hallazgo GRAVE viaja por `problemas` **y**
por `alertas_tiempos`/`severidad_tiempos`; y la post-condición pendiente **R-T05 se cumple
en todos los casos probados**: `fechavencimiento == fechainicio + Numerodias`.

## 4. Observaciones que no cuento como hallazgo

* **Apagar T01 por configuración deja la fila con `fechafin_leida = 2026-06-20` contra
  `fechavencimiento = 2026-06-06` y `alertas_tiempos = NULL`**: la contradicción sigue en la
  fila pero ya no hay ninguna marca en ella de que existió (la traza está en la config, no
  en el registro). Es la consecuencia esperada de apagar una regla, pero merece un comentario
  en el runbook: apagar T01 es distinto de bajarla a LEVE, que sí deja el código en la fila.
* T01 cita el fin HIPOTÉTICO ("con esos días la fecha fin sería X") — que coincide con el
  fin re-derivado. No es juzgar un valor calculado: es la explicación del desfase, y ayuda.
* `dias` derivado por el extractor en vacaciones queda fuera de la foto (`snapshot_leidos`
  lo toma antes), así que T01/T03 son `NO_EVALUABLE` y no hay CUMPLE tautológico… hasta que
  entra H1 por el reenvío del formulario.

## 5. Reproducir

```bash
cd /c/Projects/Vivetori/ocr/dataset-falsedad/validacion/romper-reglas
P=/c/Projects/Vivetori/ocr/incapacidad-ocr/.venv/Scripts/python.exe
$P 01_contextos_degenerados.py   # 156 comprobaciones, 11 fallas
$P 02_config_hostil.py           # 105 comprobaciones,  1 falla
$P 03_valor_calculado.py         #  31 comprobaciones,  6 fallas
$P 04_motor_y_erp.py             #  44 comprobaciones, 15 fallas
$P 05_consecuencias.py           #   9 comprobaciones,  6 fallas
```

Cada script imprime `ok` / `FALLA` por comprobación y el resumen al final; una `FALLA` es un
hallazgo (el propio texto dice qué se esperaba y qué salió). No tocan la BD, no llaman al
OCR, no escriben en el repo y no dependen de la red. `_comun.py` apunta
`REGLAS_TIEMPO_CONFIG` a un archivo inexistente para que no se cuele la configuración de la
máquina.
