# Validación de TIEMPOS (fechas y duración)

> Encargo del cliente, literal: *"código sustantivo de trabajo, valida los tiempos, para cuando no
> coincida déjalo de tal forma que sea escalable y actualizado"*.

Motor de **reglas deterministas, 100 % local**: sin modelo entrenado, sin servicio remoto, sin red.
Vive en `incapacidad_ocr/reglas_tiempo.py` (catálogo + motor + configuración) y se usa a través de
`incapacidad_ocr/validacion_temporal.py` (API pública, sin lógica propia).

```
processor.run()  ──foto de lo leído──►  extract.normalizar_fechas()  ──►  erp.mapear_a_staging()
                   (tiempos_leidos)      (RECONCILIA: única verdad)        │
                                                                          ├─► reglas_tiempo.evaluar()
                                                                          │     hallazgos → problemas
                                                                          └─► validar_tiempos()
                                                                                informe completo
```

---

## 1. Qué valida — y qué NO

**Valida** la coherencia interna de las tres patas temporales **tal como las imprimía el papel**
(o como las tecleó una persona mirándolo): fecha de inicio, fecha fin y número de días; más la
plausibilidad de la ventana temporal y de la fecha de expedición. Cuando algo no cuadra emite un
hallazgo con **código de regla + severidad + mensaje en español** que cita los valores implicados.

**NO hace** (por diseño, no por falta de tiempo):

| No hace | Por qué |
|---|---|
| No **escribe** `fecha_inicio` / `fecha_fin` / `dias` | Reconciliar es de `extract.normalizar_fechas()`, y hay **una sola** implementación. Validar no es reconciliar. |
| No **rechaza** ni aprueba nada | El diseño es staging + revisión humana: el motor marca y explica, el auxiliar decide. Nunca escribe en `lpausentismos`. |
| No juzga un valor **CALCULADO** | Si la aritmética derivó el dato, cruzarlo contra su propio origen es una tautología… o un falso positivo contra un documento legítimo al que el OCR solo le leyó dos de las tres patas. |
| No detecta lo que el **lector no publica** | Si el extractor no saca la fecha, la regla queda `NO_EVALUABLE` (nunca "no cumple"). La cobertura de LECTURA es el techo real del motor: ver §6. |
| No dice si un documento es **falso** | La contradicción temporal es una señal, no un veredicto. La sospecha de manipulación es otro eje (`sospecha_manipulacion`). |
| No compara contra el **histórico** del empleado | Falta el acceso de solo lectura a `lpausentismos` (pregunta abierta P5). Las tres reglas que lo necesitan están escritas y **apagadas**. |

### La invariante central: LEÍDO ≠ CALCULADO

`normalizar_fechas()` completa huecos (regla del cliente: `inicio = fin − (días − 1)`) y re-deriva un
fin que no cuadre. El motor solo mira la **evidencia**. Cómo se garantiza *por construcción*:

1. A una regla no se le pasa el contexto completo, se le pasa `EvidenciaTiempos`: una vista inmutable
   que **no tiene ningún campo `*_efectivo`**. No hay forma de leer un valor reconciliado, ni por
   descuido ni con un `getattr` de nombre construido en ejecución.
2. `ReglaTiempo.requiere` solo admite nombres de `CAMPOS_EXIGIBLES` (que se **deriva** de esa vista), y
   la propia declaración lo rechaza **al importar el módulo**: una errata (`fin_leidoo`) no puede dejar
   una regla muda para siempre.
3. El motor descarta la regla ANTES de llamarla si le falta un dato leído → `NO_EVALUABLE` con el motivo.
4. La evidencia sobrevive a la reconciliación porque `processor` guarda una **foto**
   (`reglas_tiempo.CLAVE_SNAPSHOT`) antes de reconciliar, y llega al ERP en `fechafin_leida` /
   `dias_leidos`.
5. Un **override del auxiliar cuenta como evidencia solo si CAMBIA algo**. El formulario de revisión se
   rellena con el valor de la fila (que puede ser el derivado) y lo reenvía en cada `/api/mapear` y
   `/api/registrar` aunque no se toque nada: tomar ese eco por evidencia resucitaba el valor calculado
   como si lo hubiera impreso el papel (y bloqueaba la aprobación con un 409 sin salida).

### Tri-estado obligatorio

`CUMPLE` · `NO_CUMPLE` · `NO_EVALUABLE` (no pude mirarlo, con el motivo en español) · `DESACTIVADA`
(apagada por configuración, se reporta: apagar es una decisión trazable, no un silencio).
**Un dato ausente nunca es una violación.**

### Severidades y qué hacen

| Severidad | Efecto |
|---|---|
| `GRAVE` | entra en `problemas` → `requiere_revision` (bloquea la aprobación como cualquier otro problema) |
| `MEDIA` | idem |
| `LEVE` | solo avisa: viaja en `avisos_tiempos`, **no** bloquea |

`puntaje_coherencia` = `100 − (40·GRAVE + 20·MEDIA + 5·LEVE)`. Sirve para **ordenar** la cola de
~7000 casos/mes; **no** es una probabilidad de fraude ni sale de un modelo.
`resumen.cobertura` = qué parte de las reglas que miran el documento se pudo comprobar de verdad
(0..1). Es el número que evita leer un `COHERENTE` como "documento verificado": `COHERENTE` con
cobertura 0,33 significa *"no encontré nada raro porque casi no pude mirar"*.

---

## 2. Tabla de reglas

`activa hoy = NO` significa **declarada y apagada**: está escrita y probada, pero le falta un dato o un
acceso. Se enciende por configuración (`activa: true`) sin desplegar, el día que el dato exista.

| Regla | Qué afirma | Severidad | Activa hoy | Datos que exige | Campo |
|---|---|---|---|---|---|
| `T01_DURACION_VS_RANGO` | los días declarados no coinciden con el rango de fechas impreso | GRAVE | sí | inicio_leido, fin_leido, dias_leido | dias |
| `T02_FIN_ANTES_DE_INICIO` | la fecha fin es anterior a la de inicio (rango imposible) | GRAVE | sí | inicio_leido, fin_leido | fecha_fin |
| `T03_DIAS_FUERA_DE_RANGO` | los días leídos están fuera del rango legal 1..540 | GRAVE | sí | dias_leido | dias |
| `T04_RANGO_MAYOR_AL_MAXIMO` | el rango de fechas dura más que el máximo legal | GRAVE | sí | inicio_leido, fin_leido | fecha_fin |
| `T05_DIAS_NO_NUMERICO` | hay un valor de días leído que no es un entero utilizable | MEDIA | sí | dias_crudo | dias |
| `T06_FECHA_INICIO_ILEGIBLE` | hay una fecha de inicio leída que no es una fecha válida | MEDIA | sí | inicio_crudo | fecha_inicio |
| `T07_FECHA_FIN_ILEGIBLE` | hay una fecha fin leída que no es una fecha válida | MEDIA | sí | fin_crudo | fecha_fin |
| `T08_DURACION_SIN_RESPALDO` | duración sobre el umbral de aviso y sin rango de fechas que la respalde | **LEVE** | sí | dias_leido | dias |
| `T09_INICIO_EN_FUTURO` | la fecha de inicio está en el futuro más allá del margen admitido | MEDIA | sí | inicio_leido, hoy | fecha_inicio |
| `T10_INICIO_MUY_ANTIGUO` | la fecha de inicio es más antigua que la ventana de radicación | LEVE | sí | inicio_leido, hoy | fecha_inicio |
| `T11_FIN_REESCRITO_SIN_EVIDENCIA` | el lector re-derivó un fin que no cuadraba y el original no quedó registrado | GRAVE | sí | — (condición del sistema) | fecha_fin |
| `T12_DIAS_LETRA_DISCREPA` | la duración en letras no coincide con la del dígito | MEDIA | sí | dias_leido, dias_letra | dias |
| `T13_DIA_SEMANA_INCONSISTENTE` | el día de la semana impreso no corresponde a la fecha de inicio | LEVE | **NO** | inicio_leido, **dia_semana_inicio_leido** | fecha_inicio |
| `T14_EXPEDICION_POSTERIOR_AL_INICIO` | el certificado se expidió después de que la incapacidad empezara | LEVE | sí | expedicion_leida, inicio_leido | fecha_inicio |
| `T15_SOLAPAMIENTO_MISMO_EMPLEADO` | el periodo cruza otro ausentismo ya registrado del empleado | MEDIA | **NO** | inicio_leido, dias_leido, id_empleado, **historial** | fecha_inicio |
| `T16_PRORROGA_SIN_ANTECEDENTE` | declara prórroga pero no hay ausentismo previo contiguo | LEVE | **NO** | **prorroga_declarada**, inicio_leido, id_empleado, **historial** | fecha_inicio |
| `T17_DUPLICADO_TEMPORAL_EXACTO` | ya existe la misma terna (empleado, inicio, días) de otro archivo | MEDIA | **NO** | inicio_leido, dias_leido, id_empleado, **historial** | fecha_inicio |

**Qué le falta a cada apagada**

| Regla | Le falta | Quién lo tiene que poner |
|---|---|---|
| `T13` | que el lector publique `dia_semana_inicio_leido` (el "MARTES" impreso junto a SU fecha). La versión "por posición" marca documentos legítimos cuando el OCR desordena las celdas (caso L14 del corpus) | `extract.py` |
| `T15` / `T17` | adaptador `ContextoTiempos.historial` (SELECT de solo lectura; las consultas y sus filtros anti-falso-positivo están escritos en comentario dentro de cada regla) + acceso a `lpausentismos` | pregunta P5 al cliente + `db.py` |
| `T16` | además, el flag `Prórroga: SI/No` del documento (lo imprimen 9 de 31 documentos del corpus y hoy no se lee) | `extract.py` |

**Umbrales** (todos configurables; ver §4):
`dias_min` 1 · `dias_max` 540 · `dias_sin_respaldo_aviso` 180 · `dias_futuro_max` 30 ·
`dias_antiguedad_max` 730 · `desfase_tolerado_dias` 0 · `dias_expedicion_posterior_tolerados` 0 ·
`dias_contiguidad_prorroga` 1.

Para ver la configuración **efectiva** dentro del contenedor (sirve para comprobar que un cambio en
caliente ya se aplicó):

```bash
docker compose exec incapacidad-ocr python -m incapacidad_ocr.validacion_temporal
```

---

## 3. Añadir una regla nueva, paso a paso

**Añadir una regla = añadir UNA declaración.** El motor no se toca: recorre el catálogo y no conoce
ninguna regla en particular. El sitio exacto está marcado con
`>>> AQUÍ se añade una regla nueva <<<` al final de la tupla `CATALOGO`.

### Ejemplo completo: "la incapacidad no puede empezar antes de la fecha del accidente"

**1) La función**, junto a las demás en `incapacidad_ocr/reglas_tiempo.py`:

```python
def _t18_inicio_antes_del_accidente(ctx: EvidenciaTiempos, u: dict[str, int]) -> Optional[str]:
    if ctx.inicio_leido >= ctx.accidente_leido:
        return None                                     # None = CUMPLE
    return (f"La incapacidad empieza el {ctx.inicio_leido.isoformat()}, ANTES de la fecha del "
            f"accidente impresa ({ctx.accidente_leido.isoformat()})")
```

Reglas del cuerpo (las tres importan):
* solo puede mirar campos de la **vista de evidencia** (`ctx` es un `EvidenciaTiempos`); un
  `*_efectivo` no existe ahí, así que no hay forma de juzgar un valor reconciliado;
* debe devolver **texto** (o `None`); cualquier otra cosa se trata como bug de la regla y queda
  `NO_EVALUABLE`, no acaba en la pantalla del auxiliar;
* si otra regla ya explica ese caso, devuelve `None` y déjaselo a ella — el auxiliar no debe leer dos
  mensajes del mismo problema (así se callan `T04` ante `T01`/`T02`/`T03`).

**2) La declaración**, en el hueco marcado de `CATALOGO`:

```python
    ReglaTiempo(
        "T18_INICIO_ANTES_DEL_ACCIDENTE",
        "la incapacidad empieza antes de la fecha del accidente impresa",
        GRAVE, _t18_inicio_antes_del_accidente,
        requiere=("inicio_leido", "accidente_leido"), campo="fecha_inicio",
    ),
```

`requiere` solo admite nombres de `CAMPOS_EXIGIBLES`; si el dato no existe todavía, hay que añadirlo
primero a `EvidenciaTiempos` (y llenarlo en `valores_leidos`/`construir_contexto`). Si te equivocas en
un nombre, **el módulo no importa** y lo ves al arrancar o al correr las pruebas — no en producción
tres semanas después con la regla muda.

**3) Si el dato aún no lo publica el lector**, déjala `activa=False` con el motivo en un comentario:
queda **declarada** (sale en `tabla_reglas()` y en el CLI) y se enciende luego por configuración, sin
desplegar.

**4) Documentarla y probarla**: una entrada en `config/reglas_tiempo.example.json` (si no está, el
cliente no puede gobernarla) y en `tests/test_validacion_temporal.py` un caso que **CUMPLE** y otro que
**NO CUMPLE**.

**No hay paso 5.** `evaluar()`, `validar_tiempos()`, el canal `problemas` / `requiere_revision`, las
columnas `alertas_tiempos` / `severidad_tiempos`, la respuesta de la API y el enrutado del lote la
recogen solas. La prueba `[9]` del suite hace exactamente esto **en caliente**: declara una regla nueva,
comprueba que el motor la evalúa, que respeta `requiere` y que la configuración puede cambiarle la
severidad desde el primer día.

Invariantes que el suite exige a cualquier regla nueva (prueba `[1]`): código único, `afirma` escrito,
`campo` que exista en el formulario, `requiere` solo de evidencia, umbrales declarados en
`UMBRALES_DEFAULT` y con rango admisible en `LIMITES_UMBRAL`, y presencia en la plantilla de
configuración.

---

## 4. Cambiar una severidad o un umbral **sin volver a desplegar**

Se lee en **CADA** corrida con esta prioridad: **tabla en BD > archivo JSON del volumen > defaults del
código** (mismo patrón que `lprequisitos_eps` sobre `REQUISITOS_DEFAULT`). Nada de esto exige
reconstruir la imagen Docker ni reiniciar el contenedor: se guarda y el **siguiente** documento ya usa
el valor nuevo.

### (A) Por SQL — recomendado en producción (queda registrado quién y por qué)

```sql
-- bajar de tono una regla ruidosa (sigue avisando, deja de bloquear)
INSERT INTO lp_reglas_tiempo_ia (codigo, severidad, nota) VALUES
  ('T01_DURACION_VS_RANGO','LEVE','2026-09: RH pide que no bloquee mientras se calibra')
ON DUPLICATE KEY UPDATE severidad=VALUES(severidad), nota=VALUES(nota);

-- apagar una regla
INSERT INTO lp_reglas_tiempo_ia (codigo, activa, nota) VALUES
  ('T09_INICIO_EN_FUTURO', 0, '2026-09: se reprocesa un lote historico')
ON DUPLICATE KEY UPDATE activa=VALUES(activa), nota=VALUES(nota);

-- mover un umbral
INSERT INTO lp_umbrales_tiempo_ia (nombre, valor, nota) VALUES
  ('dias_sin_respaldo_aviso',365,'2026-09: prorrogas largas legitimas')
ON DUPLICATE KEY UPDATE valor=VALUES(valor), nota=VALUES(nota);
```

Las dos tablas se crean con `sql/migracion_reglas_tiempo.sql` (idempotente) y **pueden estar vacías**:
vacío = "usa los defaults del código".

### (B) Por archivo — útil si no hay acceso a la BD

Copiar `config/reglas_tiempo.example.json` (plantilla comentada; toda clave que empieza por `_` se
ignora al leer) a `ingesta/_sistema/control/reglas_tiempo.json` — esa carpeta es el bind mount del
contenedor — o apuntar a otra ruta con `REGLAS_TIEMPO_CONFIG`. Formato mínimo:

```json
{
  "reglas":   { "T01_DURACION_VS_RANGO": { "severidad": "LEVE", "activa": true } },
  "umbrales": { "dias_sin_respaldo_aviso": 365 }
}
```

### A prueba de errores

Cada entrada se valida **por separado**. Una severidad inexistente, un umbral que no es entero o que
sale de su rango admisible (`LIMITES_UMBRAL`), un código de regla desconocido o un JSON roto se
**IGNORAN**, el motor sigue con los defaults y el motivo sale en `tiempos.config.avisos` /
`avisos_config` (visible en la respuesta de la API y en el CLI). **Nunca** se apaga una regla en
silencio ni se cae el procesamiento de un documento. Lo mismo vale para una **errata en el código**: si
una regla nueva declara una severidad que no existe, se usa `SEVERIDAD_RESPALDO` (MEDIA) y la errata
sale como aviso — antes eso era un `KeyError` que tumbaba el mapeo de **todos** los documentos.

**Palanca preferida**: bajar una regla ruidosa a `LEVE` antes de apagarla (sigue avisando y deja
rastro). Mover un umbral es la última opción: los umbrales son de **dominio**, y ajustarlos para que
acierten en el corpus actual (31 documentos) es sobreajustar.

---

## 5. Cómo llega al auxiliar

* `problemas` / `requiere_revision` (el canal que ya existía): GRAVE y MEDIA.
* `avisos_tiempos`: LEVE.
* Fila de staging: `alertas_tiempos` (códigos, acotado al ancho de la columna),
  `severidad_tiempos` (la peor), y la **evidencia impresa** en `fechafin_leida` / `dias_leidos`
  aunque la fila registre otro valor.
* Respuesta de `/api/procesar` y `/api/mapear`: `tiempos` (informe completo: veredicto, estado de cada
  regla, evidencia leída vs. derivada, resumen y configuración aplicada), `hallazgos_tiempos`,
  `severidad_tiempos`.
* **Pendiente**: el panel dedicado en la UI. `static/index.html` tiene el contenedor (`div #erpTiempos`)
  pero no el JS que lo pinta, así que hoy el auxiliar ve los textos por `problemas` y **no** ve el
  veredicto ni la cobertura. Es lo que falta para que pueda distinguir "no encontré nada raro" de
  "casi no pude mirar" sin abrir el JSON.

**Requisito de despliegue (no opcional):** las columnas `fechafin_leida`, `dias_leidos`,
`alertas_tiempos`, `severidad_tiempos` tienen que existir. `sql/init.sql` solo corre en el primer
arranque de un volumen vacío; en una BD ya existente hay que correr **a mano**
`sql/migracion_reglas_tiempo.sql`. Sin esas columnas el INSERT de staging falla.

---

## 6. Medición real sobre el corpus

Corpus de falsedad: **31 documentos** (15 falsas + 16 reales) ya extraídos, **sin ejecutar OCR**
(se usan los JSON de `dataset-falsedad/ocr/`). **2 parejas quedan en cuarentena** por etiqueta
contradictoria (dos archivos byte-idénticos etiquetados falsa y real) + un titular compartido → **5
documentos excluidos**. Universo evaluado: **26 = 12 falsas + 14 reales**. `hoy` fijado en 2026-09-02,
configuración = defaults del código (sin BD y sin archivo), ruta de producción
(extractor → foto → `normalizar_fechas` → motor → `erp.mapear_a_staging`).

| Métrica | Resultado |
|---|---|
| Falsas cuyo motivo declarado es **temporal** (`FECHAS_INCOHERENTES`) | **1** (F04) — **detectadas 0/1** |
| Falsas marcadas por el motor (cualquier motivo) | **1/12** (F09, `T01` GRAVE, desfase +30) |
| **Falsos positivos sobre documentos reales** | **0/14** GRAVE·MEDIA · **0/14** avisos LEVE |
| Contraste con un chequeo aritmético independiente (`span = fin−inicio+1`) | incoherentes = {F09}; el motor detecta esa 1 y solo esa → **0 falsos negativos, 0 falsos positivos sobre lo observable** |
| Veredictos | COHERENTE 21 · REVISAR 1 · AVISOS 0 · SIN_DATOS 4 |
| `T01` (la regla estrella) | NO_CUMPLE 1 · CUMPLE 12 · **NO_EVALUABLE 13 (50 %)** |
| Cobertura media del informe | **0,554** |
| Nunca se rechaza solo | 31/31 filas en `PENDIENTE_REVISION` / `POSIBLE_MANIPULACION`; 0 excepciones |

### Los límites de esta medición — leer antes de sacar conclusiones

* **Solo 1 de las 15 falsas es falsa por un motivo temporal.** Un 1/12 de detección global NO es la
  tasa del motor: las otras 11 son de firma, tipografía o diagnóstico, y no le tocan.
* **F04 (la única temporal) NO se detecta, y no es culpa de la regla.** El papel imprime las dos fechas
  en palabras (formato Sura: `MARTES 02 DE SEPTIEMBRE DE 2025` / `JUEVES 04 DE SEPTIEMBRE DE 2025`) y el
  extractor solo saca los días (`Duracion -DOS` → 2), así que `T01` queda `NO_EVALUABLE`. Entregándole
  a mano la tripleta que sí imprime el papel, **el mismo motor responde REVISAR / `T01` GRAVE con el
  desfase exacto**. Es cobertura de LECTURA, y afecta al 50 % del corpus (13/26 sin tripleta completa);
  en 10 de esos 13 la fecha **sí está** en el texto OCR.
* **n = 4.** Solo 4 documentos legítimos traen las tres patas impresas (R07 14/14, R09 126/126,
  R11 2/2, R13 30/30) y los cuatro dan desfase 0. Con esa muestra se sostiene que la convención es
  inclusiva, pero es poca base: **revalidar en cuanto entre una EPS nueva**. Por eso `desfase_tolerado_dias`
  se queda en 0 — subirlo a 1 silenciaría también F04, el único acierto propio de la aritmética.
* **Los ceros por regla son "el corpus no trae ese caso"**, no "no funciona": cada regla tiene su caso
  CUMPLE y su caso NO_CUMPLE en el suite.
* **La ventana temporal depende del reloj del proceso.** Reales marcadas por `T09` variando solo `hoy`:
  10/14 con `hoy`=2025-01-01 · 8/14 con 2026-05-01 · **0/14 con 2026-09-02** · con 2028-09-02, 0
  bloqueantes y 10/14 solo aviso LEVE (`T10`). El diseño acertó dejando `T10` en LEVE; el riesgo vivo es
  `T09`, que es MEDIA y bloquea (ver P6).
* **En vacaciones y permisos los días los deriva el propio extractor de las dos fechas**, así que `T01`
  ahí es tautológicamente CUMPLE: no hay falso positivo, pero tampoco señal. El caso de vacaciones
  multi-periodo (el span se come los huecos entre periodos) no lo detecta ninguna regla.

### Decisiones tomadas por lo medido (y por qué no fueron "ajustar el umbral")

| Hallazgo medido | Decisión | Por qué no la otra |
|---|---|---|
| `T09` marcaba el **100 %** de las notificaciones de vacaciones (tipo 13) y de las prelicencias de maternidad (tipo 10): empezar en el futuro es el propósito de esos documentos | **exención por TIPO** dentro de la regla | Subir `dias_futuro_max` a 120 o bajar `T09` a LEVE debilita la regla para **todas** las incapacidades; la exención por tipo no |
| `T08` era la **única** regla que marcaba un documento REAL, y bloqueaba una prórroga legítima de 210 días impresa sin fecha fin | **severidad → LEVE** (avisa, no bloquea); umbral intacto en 180 | Mover el umbral a 365 es ajustarlo al corpus; 180 es la frontera de dominio (trámite pensional). Coste asumido: un `dias` basura de 202 pasa a ser aviso — se recupera cuando el lector publique el crudo (T05) |
| Riesgo de un emisor que imprima en "Fecha Fin" el día de REINTEGRO (convención no inclusiva) → `T01` GRAVE en todos sus documentos | **no se toca la tolerancia**; se documenta y se revalida por emisor (NIT/EPS) | Con `desfase_tolerado_dias = 1` desaparece también F04 |
| `T02`/`T04` pueden disparar por un defecto de LECTURA (el OCR emite las celdas al revés, o un `DE 2016` de un pie legal desplaza el emparejamiento de años) | **se mantiene GRAVE** y el mensaje de `T02` nombra las dos causas posibles ("o el documento trae el rango mal, o el lector invirtió las dos celdas") | Bajarlas a MEDIA no evita el bloqueo (MEDIA también bloquea): solo cambiaría el orden de la cola. El arreglo de fondo es en `extract.py` (§7) |

---

## 7. Lo que falta — y de quién depende

### Propuestas al LECTOR (`extract.py`) — el techo del motor está aquí

El motor ya sabe usar estos datos: son claves de evidencia que lee **si están** (constantes
`CLAVE_*` en `reglas_tiempo.py`) y tienen prueba en el suite. Hoy `extract.py` no las publica.

| Propuesta | Qué desbloquea |
|---|---|
| Leer las dos fechas **en palabras** (`MARTES 02 DE SEPTIEMBRE DE 2025`) y en prosa `desde/hasta` | F04 y ~10 documentos más del corpus: `T01` pasa de `NO_EVALUABLE` a evaluable en la mitad del corpus. El lector que sí las saca ya existe fuera del paquete: `dataset-falsedad/senales/aritmetica_fechas/probe.py` (vías `escrita_sura` y `prosa_desde/hasta`) |
| Publicar `dias_calculado` (True si los días los derivó de las dos fechas) | `T01` deja de dar CUMPLE tautológico y la cobertura deja de inflarse; y unos días **impresos** vuelven a contrastarse cuando el auxiliar corrige una fecha (hoy, sin la marca, el motor se pone del lado conservador) |
| Publicar `fecha_fin_calculada` (simétrico de `fecha_inicio_calculada`) para el fin **completado** | Hoy solo se marca el fin RE-derivado; el completado se deduce por aritmética, que es conservador pero impreciso |
| Conservar la cadena RECHAZADA: `fecha_inicio_cruda`, `fecha_fin_cruda`, `dias_crudo` | `T03`/`T05`/`T06`/`T07` dejan de ser inalcanzables por el camino del documento: con `31/02/2026` impreso, el auxiliar leería "se detectó el dato pero no se puede usar" en vez de "no se detectó la fecha de inicio" (y hoy sale a buscar lo que ya está impreso) |
| `_dias_por_etiqueta`: exigir el valor en la MISMA línea que el rótulo (`[^\d\n]{0,10}`) | Evita leer el DÍA DEL MES de la celda vecina como duración (`Duracion` ⏎ `JUEVES 23 DE JULIO` → 23 días): hoy es un `T01` GRAVE contra un documento legítimo y nueve días de más en la fila |
| `_fecha_inicio_fin_escrita`: no emparejar el año **por posición** en todo el documento, y ordenar las dos fechas (o abstenerse) marcando `orden_incierto` | Evita dos falsos positivos GRAVE (`T02` con las celdas invertidas, `T04` con un `DE 2016` de pie legal) y una fila silenciosamente errónea de 10 años que **ninguna** regla puede ver |
| Publicar `dia_semana_inicio_leido` y el flag `Prórroga: SI/No` | Enciende `T13` y `T16` (ya escritas) |

### Propuestas al ERP / esquema

* `R-T05 VENCIMIENTO_INCONSISTENTE` (`fechavencimiento == fechainicio + Numerodias`): es una
  post-condición sobre la fila FINAL, y el contrato del motor prohíbe que una regla lea un valor
  efectivo. Debe comprobarse en `erp.mapear_a_staging` justo después de construir la fila, o como
  guardarraíl del INSERT. Medido: **0 violaciones** en las 19 filas comprobables del corpus.
* Adaptador `ContextoTiempos.historial` (SELECT de solo lectura) para encender `T15`/`T17`. `T17` es el
  más barato: consulta `lp_ausentismos_ia`, que es tabla local.
* Panel de tiempos en la UI (§5).

### Preguntas abiertas al cliente

| # | Pregunta | Por qué importa |
|---|---|---|
| **P1** | ¿Cuál es el **plazo de radicación** de una incapacidad? | Hoy `dias_antiguedad_max`=730 es un número de dominio, no una regla del cliente. Por eso `T10` nace LEVE. |
| **P3** | Cuando el papel imprime un fin que contradice `inicio + días`, **¿quién manda** en el conteo? | Hoy el fin efectivo que se registra es el re-derivado; la evidencia queda en `fechafin_leida` y `T01` lo marca, pero la fila registra el re-derivado. |
| **P4** | ¿Pueden coexistir **dos ausentismos concurrentes** (accidente de trabajo + enfermedad general)? | Define si `T15` es MEDIA o GRAVE. |
| **P5** | ¿Se puede dar un usuario de **solo lectura sobre `lpausentismos`**? | Sin eso `T15`/`T16`/`T17` no se pueden encender (y `lpausentismos` no existe en el esquema local). |
| **P6** | ¿Se van a **reprocesar lotes históricos**? ¿Existe fecha de RECEPCIÓN del archivo? | `T09`/`T10` se miden contra `hoy` (`fecharegistro`), no contra la recepción: reprocesar un lote viejo desplaza las dos reglas. |
| **P7** | ¿Es normal la incapacidad **retroactiva** (expedida días después de empezar)? | `dias_expedicion_posterior_tolerados`=0 hace que `T14` avise siempre; con la respuesta se calibra o se apaga. |
| **P8** | ¿Hay **emisores no inclusivos** (que imprimen en "Fecha Fin" el día de reintegro)? | Si existen, `T01` marcaría todos sus documentos legítimos con desfase +1. La recomendación es convención por emisor (NIT/EPS), no subir la tolerancia. |
| **P9** | En **vacaciones multi-periodo**, ¿se registran los días SUMADOS o el span completo? | Hoy el span se come los huecos entre periodos y ninguna regla lo ve. |

---

## 8. Probar

```bash
# suite del motor (sin OCR, sin BD, sin red; `hoy` inyectado → determinista)
.venv/Scripts/python.exe tests/test_validacion_temporal.py

# configuración efectiva (catálogo + severidades + umbrales que se están aplicando)
.venv/Scripts/python.exe -m incapacidad_ocr.validacion_temporal
```

El suite cubre, en este orden de importancia: la frontera leído/calculado, el tri-estado, la
extensibilidad en caliente (declara una regla nueva y comprueba que el motor la recoge), la
configuración externa (incluida la corrupta), la integración por el canal `problemas` que ya existía,
y dos secciones de **regresión**: `[12]` los 13 hallazgos del ataque adversario al motor y `[13]` los
falsos positivos sobre documentos legítimos. Cada comprobación de esas dos secciones falla si se
revierte su arreglo.

## 9. PII

Este documento no cita datos de pacientes (Ley 1581): el corpus se referencia por ID estable
(`F01..F15` / `R01..R16`) y por nombre de archivo cuando hace falta. Los informes de verificación con
más detalle viven fuera del repo, en `dataset-falsedad/validacion/`.
