# Frente `regresion-real` — ¿empeoró algo en los documentos reales?

**Veredicto: el frente está LIMPIO en la superficie de producción (texto de RapidOCR): 0 campos
empeoraron en los 31 documentos reales.** Hay **1 hallazgo GRAVE latente** que no dispara en esos 31
textos pero sí en el contenido de uno de esos mismos documentos leído por la otra vía, con
reproducción mínima y coste de arreglo de una línea.

> PII: este informe cita **nombres de ARCHIVO** y **patrones de texto** (protocolo del proyecto). No
> lleva nombres de persona, cédulas ni diagnósticos. La única línea de documento que se transcribe
> literal es la del hallazgo (`Profaslonal ce -,tl 295787.t1 DIAN`, un número de registro profesional
> degradado) porque es la ENTRADA exacta del fallo.

---

## 1. Método

| | |
|---|---|
| **ANTES** | `incapacidad_ocr/extract.py` de **git HEAD** (`a70cec7`), volcado en `extract_antes.py`. El `git diff` de trabajo de ese archivo es EXACTAMENTE el cambio de duraciones (nada más), así que HEAD es el estado previo exacto. Es un módulo autocontenido (HEAD no tiene imports relativos) → se carga suelto. |
| **AHORA** | el paquete del working tree tal cual. |
| **Entrada** | `dataset-falsedad/ocr/{falsas,falsa,reales,real}/*.txt` = **31 textos** (el `texto_plano` que guardó el shard, ya combinado por páginas relevantes). **NO se corrió OCR** (había otra medición en la máquina). |
| **Camino** | `RuleBasedExtractor().extract()` + `normalizar_fechas()` en los dos casos — es lo que hace `IncapacidadProcessor.run` y lo que produjo los `.json` cacheados. |
| **Validación de la línea base** | los 31 `.json` cacheados **se reproducen campo a campo** con el extractor de HEAD → el `.json` es una línea base válida (no un estado intermedio). |
| **Comparación** | los **26 campos** del esquema aplanados (`seccion.campo`) — los 29 de `empty_record()` menos los 3 que el cambio AÑADE (`dias_letra`, `dias_letra_coincide`, `fecha_fin_recalculada`), que se reportan aparte. |

Scripts (todos en `dataset-falsedad/duraciones/regresion-real/`):

| Script | Qué hace |
|---|---|
| `comparar.py` | diff ANTES vs. AHORA de los 26 campos en los 31 textos + cross-check contra los `.json` → `resultado.json` |
| `atacar.py` | fila de staging (`erp.mapear_a_staging`) antes vs. ahora · respaldo histórico ¿dispara? · `fecha_fin_recalculada` ¿completo? · coste · idempotencia |
| `rutas_dias.py` | de qué RUTA sale `dias` (rótulo viejo / módulo / respaldo / diferencia de fechas) para detectar aciertos por casualidad |
| `auditar_anclas.py` | el ANCLA y la evidencia con la que el módulo lee cada duración |
| `candidatos_ocr.py` | TODOS los candidatos por documento (mide si la elección es ajustada) |
| `capa_texto_docs.py` | 2ª superficie: capa de texto nativa de los 13 PDF de `docs/` con texto (sin OCR) |
| `ejemplos_capa_texto.py` | 3ª superficie: capa de texto de los PDF de `../Ejemplos` (1 de 8 la tiene) |
| `bateria_fp.py` | los 27 falsos positivos del inventario `01_evidencia.md` §5 |
| `exp_sin_dian.py` | mide qué aporta la corrección OCR `dian → dias` en las 44 entradas reales |
| `repro_dian.py` | reproducción mínima del hallazgo |
| `inspeccionar.py` | contexto de los candidatos en 3 PDF concretos |

---

## 2. Resultado: `dias` en los 31 textos OCR

```
dias: iguales=25   nuevos(antes None)=3   perdidos(ahora None)=1   cambiados=2
```

| Clase | Nº | Archivos | antes → ahora | Correcto (`01_evidencia.md`) | Juicio |
|---|---|---|---|---|---|
| **Igual** | 25 | — | — | — | sin cambio |
| **Nuevo** | 3 | `falsas/FALSA-02` | None → **1** | 1 | ✅ mejora (forma A6, `…POR1DIA…` pegado) |
| | | `falsas/FALSA-04` | None → **2** | lo que declara el campo `Duracion` = `-DOS` | ✅ mejora (forma B1, solo la palabra) |
| | | `falsas/FALSA-14` | None → **2** | 2 | ✅ mejora (forma C5, `DOS (02)`) |
| **Cambiado** | 2 | `falsa/FALSA-03` | **29 → 4** | 4 | ✅ arregla el falso positivo #5 (leía el día del mes de `DESDE EL 29-07-26`) |
| | | `reales/REAL-15` (mismo texto) | **29 → 4** | 4 | ✅ idem |
| **Perdido** | 1 | `real/REAL-16` | **202 → None** | 1 | ✅ arregla el falso positivo #6 (leía el AÑO de `Duracion`⏎`DE2026`). El 202 era un valor **inventado**; ahora el campo va a revisión marcado *"No se detectó el número de días"* |

**Ningún campo que antes fuera correcto cambió.** Los 3 valores que desaparecen o cambian (29, 29, 202)
eran los dos falsos positivos que el inventario marcaba `[FALLA HOY]`.

### Resto de campos

Diferencias en TODO el corpus, por campo:

| Campo | Documentos | Detalle |
|---|---|---|
| `incapacidad.dias` | 6 | tabla de arriba |
| `incapacidad.fecha_inicio` | 1 | `falsas/…<NOMBRE>…18.05.2026`: None → `2026-05-18`. Con `dias=1` y el fin ya leído (`2026-05-18`), la regla del cliente (`inicio = fin − (días − 1)`) la deriva **correctamente** |
| `incapacidad.fecha_inicio_calculada` | 1 | el mismo documento: False → True (aviso honesto: la fecha fue derivada, no leída) |

**Cero cambios** en `tipo_documento`, `paciente.*` (nombre/tipo/número), `entidad.eps`,
`entidad.ips_prestador`, `diagnostico.cie10`, `diagnostico.descripcion`, `medico.nombre`,
`medico.registro`, `incapacidad.fecha_fin`, `incapacidad.fecha_expedicion`, `incapacidad.tipo`,
`incapacidad.origen`, `incapacidad.tipo_licencia` y los 10 campos de `permiso.*`.

---

## 3. Lo que llega a la nómina (fila de staging)

`erp.mapear_a_staging` sobre los 31 registros, antes y ahora (sin BD, `LookupsNulos`). El **conjunto
de claves de la fila es idéntico** (los 3 campos nuevos se ignoran sin romper nada). Cambian 6 filas:

| Archivo | `Numerodias` | `fechainicio` | `fechavencimiento` | Juicio |
|---|---|---|---|---|
| `falsas/…<NOMBRE>…18.05.2026` | None → 1 | None → 2026-05-18 | None → 2026-05-19 | ✅ correcto |
| `falsas/…<NOMBRE>…02.09.2025` | None → 2 | None | None | ✅ dato nuevo; sigue **sin** fecha de inicio → no aprobable |
| `falsas/…<NOMBRE>…25022026` | None → 2 | None | None | ✅ idem |
| `falsa/…<NOMBRE> <NOMBRE>…29072026` | 29 → **4** | None | None | ✅ arregla un dato incorrecto |
| `reales/REAL-15` | 29 → **4** | None | None | ✅ idem |
| `real/REAL-16` | 202 → None | None | None | ✅ deja de mandar un valor inventado |

**Ningún documento pasó a ser aprobable con un dato no verificado**: los tres que ganan `Numerodias`
siguen teniendo obligatorios faltantes (cédula/CIE-10/EPS/fecha de inicio), así que siguen en
`PENDIENTE_REVISION` y el ERP no los promueve. Los `problemas`/`campos_faltantes` se mueven de forma
coherente (`CED-25` **gana** el problema *"No se detectó el número de días"*, que es lo que se quiere).

---

## 4. Otras comprobaciones (todas OK)

| Ataque | Resultado |
|---|---|
| **Respaldo histórico** de `_dias_por_etiqueta` (los 2 patrones viejos que se conservaron) | **0 disparos** en los 31 textos: es inerte, como se declaró |
| **3er patrón viejo eliminado** (`nº + palabra + dias`) | **0 disparos** en los 31 textos ANTES del cambio → su eliminación no pierde nada |
| **Acierto por casualidad** (`rutas_dias.py`) | ningún documento en el que el rótulo viejo leyera un valor **correcto** y el módulo lo pierda. El único "rótulo perdido" es `CED-25`, y lo que perdió era el 202 inventado |
| **Elección ambigua** (`candidatos_ocr.py`) | en los 31 textos, **todo documento con candidatos produce un único valor**: 0 documentos con candidatos en conflicto → la elección no depende del orden de líneas |
| **`fecha_fin_recalculada`** | dispara en **exactamente 1** documento (`falsas/FALSA-09`: `Desde 05/06 – Hasta 06/07` = 32 días frente a `dias=2`), que es el caso de fraude #2 del inventario. Comprobado contra los valores CRUDOS: **0 falsos positivos y 0 falsos negativos** |
| **`dias_letra` / `dias_letra_coincide`** | **11** documentos leen la palabra: 10 con `coincide=True` (dígito y palabra concuerdan) y 1 con `coincide=None` (`…<NOMBRE>…02.09.2025`, solo palabra). Los 11 valores de letra son correctos. Ningún `coincide=False` en el corpus (esperado) |
| **Batería de falsos positivos** (`bateria_fp.py`) | los **27** falsos positivos documentados en `01_evidencia.md` §5 siguen rechazados (edad, `hacetresdias`, `1 (Uno)`, `Vig: 1 dia`, horas, semanas de gestación, consecutivos, régimen/nivel, signos vitales, rejilla `DIA/MES/ANO`, `3.DURACIONDELPERMISO`, artículo `una`…) |
| **Pruebas del repo** | `tests/test_processor.py` y `tests/test_numeros_es.py`: **TODO OK** |
| **Coste** | extracción por reglas 1.27 → **1.56 ms/documento** (+23 %). Irrelevante frente al OCR (segundos por página) |
| **Idempotencia** | el mismo texto da el mismo registro |
| **2ª superficie — capa de texto nativa de los 13 PDF de `docs/` con texto** (misma gente, otra degradación: tildes, `día(s)`, tablas de insumos) | **4 mejoras**: `falsas/…<NOMBRE>…18.05.2026` 18→**1** (¡y `fecha_inicio` 2026-05-01→**2026-05-18**), `falsas/…<NOMBRE> <NOMBRE>…29072026` 9→5, `falsas/FALSA-15` 14→**5** (correcto: `14-07`→`18-07`), `reales/REAL-15` 9→5. **1 regresión** → el hallazgo del §5 |
| **3ª superficie — `../Ejemplos`** | de los 8, solo `Incapacidad (19)_unlocked.pdf` tiene capa de texto: **sin cambio** (30 antes y ahora), y además lee bien la palabra (`letra=30`, `coincide=True`) pese al `1` de índice de fila pegado al rótulo (`1 DIAS: 30 (TREINTA)`) |

---

## 5. Hallazgo

### H1 — GRAVE (latente) · la corrección OCR `dian → dias` inventa una duración de 1 día a partir del renglón del registro profesional

**Dónde**: `incapacidad-ocr/incapacidad_ocr/numeros_es.py:101-103` (`_CORRECCIONES_OCR`, la pareja
`(r"\bdian\b", "dias")`), consumida por `normalizar()` (`numeros_es.py:131`) y de ahí por
`_candidatos_por_unidad` (`numeros_es.py:377`).

**Entrada exacta** (renglón 85 de la capa de texto de
`dataset-falsedad/docs/falsas/FALSA-04.pdf`, un
documento REAL del corpus; es el número de registro profesional degradado, sin PII):

```
Profaslonal ce -,tl 295787.t1 DIAN
```

`normalizar()` lo convierte en `profaslonal ce -,tl 295787.t 1 dias` (separa letra/dígito **y**
aplica `dian → dias`), con lo que `1` queda pegado a la unidad `dias` y `_candidatos_por_unidad` lo
acepta como duración anclada.

**Esperado**: `None` (no es una duración; en ese documento la duración vive en el campo `Duracion`).
**Obtenido**: `{'valor': 1, 'origen': 'numero', 'evidencia': '1 dias'}`.

**Efecto en un documento completo** (`repro_dian.py`, caso A10 del inventario — rótulo de días sin
valor, que pasa en **7 de los 31** textos reales):

```
CERTIFICADO DE INCAPACIDAD MEDICA
CC 1111111111 PACIENTE DE PRUEBA
Dias de Incapacidad:
Fecha Inicio: 02/09/2025
Fecha Fin: 04/09/2025
Registro Profaslonal ce -,tl 295787.t1 DIAN
```

| | `dias` | `fecha_inicio` | `fecha_fin` |
|---|---|---|---|
| ANTES | **3** | 2025-09-02 | **2025-09-04** |
| AHORA | **1** | 2025-09-02 | **2025-09-02** |
| Esperado | 3 | 2025-09-02 | 2025-09-04 |

No solo el `dias` sale mal: `normalizar_fechas` **sobrescribe la `fecha_fin` que traía el documento**
con la derivada (y lo marca `fecha_fin_recalculada=True`). En la fila de staging eso es
`Numerodias=1` y `fechavencimiento=2025-09-03` en vez de 3 días → dato incorrecto que llega a la
nómina si el auxiliar no lo detecta.

**Qué aporta la corrección, medido** (`exp_sin_dian.py`, 44 entradas reales = 31 textos OCR + 13
capas de texto): con y sin la corrección el resultado difiere en **1 sola entrada**, y es justo esta,
para peor:

```
capa/falsas/INC <NOMBRE> DE LA HOZ <NOMBRE> <NOMBRE> 3 DÍAS…  con=(1, None, None)  sin=(None, None, None)
```

En el documento que motivó la corrección (`real/REAL-12.txt`, `3Dian` en el renglón 42)
el resultado final es **3 con y sin corrección**: la diferencia de fechas (`2026-05-25` → `2026-05-27`)
ya daba 3 antes del cambio. O sea: **la corrección no gana nada en las 44 entradas reales y sí abre un
falso positivo.**

**Por qué "latente"**: el pipeline nunca lee la capa de texto del PDF (siempre OCR-ea), y en el texto
de RapidOCR de ese documento gana el candidato correcto (`duracion -dos` → 2). `\bdian\b` aparece
**una sola vez** en los 31 textos OCR y es la ocurrencia legítima. Es decir: **no está roto hoy**, pero
los glifos que lo rompen están en un documento real del corpus y basta que RapidOCR lea esa zona como
la lee PDFium.

**Arreglo sugerido** (no lo aplico, soy verificador): borrar la pareja `(r"\bdian\b", "dias")` de
`_CORRECCIONES_OCR` — coste cero medido — o, si se quiere conservar el rescate del `3Dian`, exigir que
`dian` venga pegado al dígito (`(?<=\d)\s*dian\b`), que es la forma en que se observó.

### Nota relacionada (no es hallazgo, es el borde del diseño)

La misma ruta acepta `Registro Profesional 295787 1 DIAS` → 1 y `Tarjeta Profesional 52369 2 DIAS` → 2
(construcciones mías, no del corpus). Es inherente al soporte de las formas **A5/A6/A8** (valor
pegado a la unidad, sin rótulo), que es lo que permite las 3 mejoras del §2: no se puede cerrar sin
perderlas, y en los 31 textos reales no dispara. Solo la variante `dian` es **neta negativa** y por eso
es la que se reporta.

### Nota sobre el "caso oro" de fraude

La justificación del aviso `fecha_fin_recalculada` cita el caso
`falsas/INC <NOMBRE>…02.09.2025` (`Duracion` = `-DOS` frente a un rango de 3 días). En ese documento el
extractor **no lee ninguna fecha** (`fecha_inicio` y `fecha_fin` = None, antes y ahora), así que la
reconciliación no re-deriva nada y **el aviso queda en `False`**: la señal duración-vs-fechas de ese
documento sigue sin quedar registrada. El aviso sí funciona, pero el caso donde dispara es otro
(`falsas/FALSA-09`). Es una imprecisión de la justificación, no un
defecto de código, y no cambia ningún valor.

---

## 6. Lo que NO se pudo verificar en este frente

- **`tests/test_ejemplos_reales.py`** (los 8 documentos de `../Ejemplos`): 7 son escaneos sin capa de
  texto y necesitan RapidOCR → **no ejecutado** (había otra medición de rendimiento en la máquina).
  Cubierto solo el único con capa de texto (sin cambio). Es el punto ciego que ya declaraba el cambio.
- **Tabla `DETALLE DE LA INCAPACIDAD`**: **ningún** documento del corpus la trae (`grep` en los 31
  textos: 0 coincidencias), así que el ensanchado de su celda de días (`\d{1,3}` → `[^\n]{1,40}`) no
  se ejercita con documentos reales aquí; solo con las pruebas sintéticas del repo (que pasan).
- **Cartas de VACACIONES**: no hay ninguna real en el corpus. La regla (letras desactivadas) queda
  validada solo por la prueba sintética del repo.
- **Camino LLM / híbrido**: Ollama no está levantado (ni Docker, falta elevación UAC). Verificado por
  el `StubLLM` del repo, que pasa; **no** se ejecutó el modelo real.
- **Los dos textos duplicados** del corpus (`falsa/INC <NOMBRE>…29072026` == `reales/REAL-15`
  y `falsa/INC <NOMBRE>…13.05.2026` == `reales/REAL-01`) cuentan dos veces en las tablas;
  los documentos DISTINTOS son 29.

---

## 7. Nota de entorno: el repo se estaba modificando EN PARALELO

Durante esta verificación otro trabajo tocó el repo (`incapacidad_ocr/erp.py`,
`incapacidad_ocr/processor.py`, `sql/init.sql` y un módulo nuevo `reglas_tiempo`, con marcas de tiempo
01:15–01:19, posteriores al inicio de esta sesión). **Los dos archivos que este frente verifica NO
cambiaron** durante la corrida (`extract.py` 01:06, `numeros_es.py` 00:55), así que las conclusiones de
los §2–§5 son válidas.

La medición de la fila de staging (§3) se tomó con el `erp.py` anterior a esos cambios. **Repetida con
el `erp.py` actual, el resultado es el mismo**: los mismos **6** documentos cambian
`Numerodias`/`fechainicio`/`fechavencimiento`, con los mismos valores. Lo único que aparece de más son
dos efectos del trabajo concurrente, ambos coherentes:

- `falsas/FALSA-09`: el nuevo `fecha_fin_recalculada=True` ya lo
  consume `reglas_tiempo` y se traduce en `alertas_tiempos='T11_FIN_REESCRITO_SIN_EVIDENCIA'`
  (`severidad_tiempos='GRAVE'`) + `fechafin_leida=None`. Es decir: el aviso que añadió este cambio ya
  está alimentando la detección de alteración temporal.
- `real/REAL-16`: **pierde** la alerta `T08_DURACION_SIN_RESPALDO` (MEDIA) porque ya no
  hay duración que respaldar — el 202 inventado desapareció. Coherente.
