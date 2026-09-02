# ESTADO DEL CORPUS DE FALSEDAD — para quien siga trabajando

Fecha de corte: **2026-09-02**. Fuentes: `manifest.csv`, `ground_truth.json`,
`senales/*/INFORME.md` y los `resultados.json` / `resultado.json` / `medicion.json` de cada familia.
Reconstruible con `_tabla_estado.py` (100 % local, sin PII en la salida).

> ## Léelo en 30 segundos
>
> - **31 documentos** (15 adulterados / 16 legítimos). Tras excluir la cuarentena: **26** (12 / 14).
> - **5 documentos en cuarentena** (16 % del corpus): 2 parejas byte-idénticas con **etiqueta
>   opuesta** + 1 archivo que comparte titular con la clase contraria.
> - Los 12 adulterados evaluables vienen de **5 titulares distintos**. El número de casos
>   independientes es **5, no 12**. Cualquier porcentaje calculado sobre 12 sobrecuenta.
> - **4 de las 8 señales de la taxonomía tienen 1 ó 0 ejemplos evaluables.** `TIPOGRAFIA_MIXTA`
>   tiene **cero** (su único caso está en cuarentena).
> - **3 documentos de 26** (todos legítimos) no tienen **ninguna** familia aplicable: el motor no
>   puede decir absolutamente nada de ellos.
> - **Este corpus NO alcanza para calibrar umbrales ni para reportar una precisión.** Sirve para
>   descartar checks malos (y ya descartó varios) y como suite de no-regresión.

**Convención de identificadores.** Los documentos se citan por los **8 primeros caracteres del
sha256**. Los titulares por un id opaco (`F1`…`F7` para los adulterados, `L1`…`L15` para los
legítimos) derivado de la agrupación, **nunca por nombre ni cédula**. La equivalencia con los nombres
de archivo está en `manifest.csv`.

---

## 1. Inventario

| | |
|---|---|
| Documentos | **31** = 15 adulterados + 16 legítimos |
| Contenedores | 28 PDF (25 de 1 página, 3 de 2 páginas) + 3 JPEG sueltos |
| En cuarentena | **5** (3 de la clase adulterada, 2 de la legítima) |
| Base evaluable | **26** = 12 adulterados + 14 legítimos |
| Titulares aparentes | adulterados: **7** para 15 documentos · legítimos: **15** para 16 documentos |
| Titulares en la base evaluable | adulterados: **5** para 12 documentos · legítimos: **13** para 14 documentos |
| Tipos de documento (legítimos) | 13 incapacidad · 2 permiso · 1 historia clínica |
| Tipos de documento (adulterados) | 15 incapacidad |
| Tabla de motivos | `Explicacion de archivos.jpeg`: 15 filas · **5 en rojo** · **3 sin motivo escrito** |

### Composición por origen del PDF (medido con `pypdfium2` + metadatos)

Esto determina qué familias pueden opinar, así que es más importante que el conteo de documentos:

| Cómo llega el documento | nº |
|---|---|
| JPEG suelto (sin objetos PDF) | 3 |
| PDF **sin capa de texto** = escaneo o foto pura (CamScanner ×9, Word con el escaneo pegado ×2, EPSON Scan, Quartz iOS, iLovePDF, sin metadatos) | **15** |
| PDF con capa de texto, exportación de Microsoft Word | 10 |
| PDF con capa de texto **sintetizada por OCR** (ClearScan / Paper Capture) | 1 |
| PDF con capa de texto generada por un **sistema** (iText) | **1** |
| PDF con capa de texto de *Print To PDF* (nombres de fuente anonimizados) | 1 |

**Un solo documento del corpus es un PDF emitido por un sistema.** La premisa «el portal de la EPS
genera un PDF homogéneo y el adulterado rompe esa homogeneidad» **no describe este flujo**: el flujo
real es «el prestador rellena una plantilla en Word y exporta» o «el trabajador fotografía el papel».
Cualquier diseño que asuma lo contrario se va a estrellar.

### Sesgo de nomenclatura — trampa nº1

Las dos clases usan convenciones de nombre distintas (los adulterados traen nombre del paciente y
fecha; los legítimos, cédula y tipo de documento). **Un clasificador que lea el nombre de archivo
acierta el 100 % sin abrir el documento.** Nada de lo que se compute puede tocar el nombre.
Corolario para el motor: `id_paciente` y `tipo_documento` deben venir de la **radicación**, no del
nombre, y en este corpus hubo que reconstruirlos con union-find y corroboración cruzada (la cédula
del OCR solo se acepta si aparece en el nombre de otro documento, porque en 4 de 31 el OCR confunde
la cédula del paciente con otro número del formato).

---

## 2. Cuarentena: los 5 documentos y su impacto real

| sha8 | Clase(s) | Motivo de cuarentena |
|---|---|---|
| `28c4a946` | **adulterado Y legítimo** | mismo sha256 en las dos carpetas (una sola pareja de archivos idénticos) |
| `d86ae595` | **adulterado Y legítimo** | mismo sha256 en las dos carpetas (segunda pareja) |
| `58c1e091` | adulterado | misma cédula que el legítimo de la pareja `28c4a946`, contenido distinto |

(5 archivos: las dos parejas son 4 archivos + 1 archivo suelto.)

### Por qué no se usan como verdad

Un par de documentos idénticos con etiquetas opuestas es una **contradicción lógica**: el mismo vector
de señales tiene que dar «adulterado» y «legítimo» a la vez. Envenena el ajuste de umbrales, miente
en las métricas (en un par contradictorio el motor falla exactamente 1 de 2, sea lo que responda) y
produce fuga entre particiones. **Se documentan, se excluyen de toda métrica, y solo se usan como
casos de humo** (que el motor no reviente y sea determinista). No se borran: la contradicción es un
hallazgo real sobre la calidad del etiquetado y hay que devolverla al área.

### Impacto medido, familia por familia

| Familia | Qué pierde por la cuarentena |
|---|---|
| `tipografia_pdf` | **Lo pierde todo lo bueno.** `28c4a946` es el **único** documento del corpus etiquetado `TIPOGRAFIA_MIXTA` y el único donde disparan sus dos checks deterministas y sin umbrales (`TP_ALFA_TEXTO_NO_UNIFORME`, `TP_PARCHE_BLANCO`). Sin él, esos dos checks miden **0** y todo el recall de la familia queda en manos de un único check heurístico |
| `firma_y_reuso` | Pierde el único disparo de `FONDO_REUSO_CROSS_PACIENTE` (la pareja `d86ae595` comparte el escaneo de página completa). Y ese caso deja una lección incómoda: el «paciente distinto» que dispara el check es un **error de archivado del área**, no un fraude |
| `dx_catalogo` | Pierde el contraejemplo más importante: `d86ae595` dispara `DX_FORMATO_LONGITUD` **en las dos carpetas**. Si se contara, la precisión del check bajaría a 3/4 y el mismo documento sería a la vez acierto y error |
| `aritmetica_fechas` | Pierde un `AF01` con desfase grueso confirmado en la capa de texto del PDF (`28c4a946`). Si la pareja se resolviera como adulterada, la familia pasaría de 2/12 a 3/13; si se resolviera como legítima, sería 1 falso positivo |
| `dias_vs_diagnostico` | Nada: los 5 caen en `NO_EVALUABLE` de todas formas |

### Recomendación con evidencia sobre `28c4a946`

Dos familias independientes acumulan evidencia fuerte sobre ese archivo: parches blancos opacos
cubriendo la imagen del documento original, 4 objetos de texto con opacidad 191 (resto 255) estampados
al final del content stream **en esas mismas coordenadas**, `Producer` de una librería distinta al
`Creator`, `ModDate` 50 días posterior al `CreationDate`, **y** una contradicción aritmética de fechas
presente en la capa de texto embebida del PDF (verificada sin OCR). La explicación benigna que
quedaría —«es un emisor con otro formato de fecha»— no explica los parches ni la opacidad.
**Proponemos resolver esa pareja a favor de `adulterado`.** Es la pieza de evidencia más fuerte del
corpus y hoy no vale nada.

### Fuga por titular (menos visible y más dañina)

El titular `F2` (adulterados) y `L14` (legítimos) **son la misma persona**, igual que `F6` y `L1`. Si
alguna vez se particiona este corpus, hay que agrupar por `sha256` **y por titular**: cualquier señal
ligada al titular (su EPS, su IPS, su plantilla habitual, su médico tratante) se filtra entre clases.

---

## 3. Cobertura de la taxonomía

### Documentos por señal

| Señal | Total | Evaluables (sin cuarentena) | Estado |
|---|---|---|---|
| `DX_INEXISTENTE` | 4 | **3** | el mejor cubierto… y su check principal vale 0 por falta de catálogo |
| `DX_NOMBRE_DISTINTO` | 3 | **2** | check bloqueado por falta de catálogo |
| `SIN_MOTIVO_REGISTRADO` | 3 | **3** | **no es una señal**: es un hueco de etiquetado |
| `FIRMA_MEDICO` | 2 | **2** | ninguno de los 2 se detecta; y la autenticidad de firma está fuera de alcance |
| `DX_FORMATO` | 1 | **1** | ⚠ un solo ejemplo |
| `FECHAS_INCOHERENTES` | 1 | **1** | ⚠ un solo ejemplo (sí se detecta) |
| `DIAS_VS_DIAGNOSTICO` | 1 | **1** | ⚠ un solo ejemplo (sí se detecta) |
| `TIPOGRAFIA_MIXTA` | 1 | **0** | ⚠⚠ **cero ejemplos utilizables**: el único está en cuarentena |

Lectura obligada: **la mitad de la taxonomía descansa sobre un único documento o sobre ninguno.**
Cuando un informe dice «1/1 detectada, 100 % de recall», eso no es una precisión estimada: es un
**no-desmentido** con n=1.

### Señales que la taxonomía NO cubre y el corpus demuestra que hacen falta

1. **Edición en el píxel.** 13 de los 26 evaluables son escaneos/fotos puros (+3 JPEG). Ahí la
   adulteración se hizo dentro del mapa de bits y **ninguna** familia actual puede verla. Es el hueco
   más grande.
2. **Coherencia contra el ERP**: titular activo, EPS del documento = EPS del empleado, IPS emisora
   existente/habilitada, documento no radicado antes. Datos que la empresa **ya tiene**.
3. **Prórrogas solapadas y fechas reutilizadas** entre trámites del mismo titular.

---

## 4. Matriz documento × cobertura (la tabla que hay que mirar antes de creerse cualquier recall)

`Fam.` = cuántas de las 5 familias pudieron **aplicar** a ese documento. `Familias que marcan` =
familias con al menos un check acusatorio en `DISPARA`.

### Adulterados (15; los 3 de cuarentena marcados)

| sha8 | Titular | Contenedor | Señal declarada | Rojo | Cuar. | Fam. | Familias que marcan |
|---|---|---|---|---|---|---|---|
| `8b682a83` | F1 | pdf/1p | FIRMA_MEDICO | - | - | 5/5 | tipografia |
| `5c66d97e` | F1 | pdf/1p | DX_INEXISTENTE | - | - | 4/5 | tipografia |
| `28c4a946` | F2 | pdf/1p | TIPOGRAFIA_MIXTA | - | **SI** | 4/5 | fechas, tipografia |
| `e0ee54fd` | F3 | pdf/1p | FECHAS_INCOHERENTES | - | - | 3/5 | fechas |
| `8aeee4cd` | F4 | pdf/1p | DIAS_VS_DIAGNOSTICO | ROJO | - | 4/5 | tipografia, dias, firma |
| `9dcb4e35` | F4 | pdf/1p | SIN_MOTIVO_REGISTRADO | ROJO | - | **1/5** | **ninguna** |
| `9603c77b` | F4 | pdf/1p | DX_NOMBRE_DISTINTO | - | - | 5/5 | tipografia, firma |
| `ed2a4eeb` | F4 | pdf/1p | FIRMA_MEDICO | - | - | **2/5** | **ninguna** |
| `d5b72739` | F5 | jpeg | DX_INEXISTENTE, DX_FORMATO | - | - | 2/5 | fechas, dx |
| `717d3aad` | F5 | pdf/2p | DX_INEXISTENTE | - | - | 5/5 | tipografia, dx |
| `d86ae595` | F6 | pdf/1p | DX_INEXISTENTE | - | **SI** | 1/5 | dx, firma |
| `d08cba3f` | F7 | pdf/1p | SIN_MOTIVO_REGISTRADO | ROJO | - | **1/5** | **ninguna** |
| `99d74f47` | F7 | pdf/1p | DX_NOMBRE_DISTINTO | ROJO | - | **1/5** | **ninguna** |
| `758d3aff` | F7 | pdf/1p | SIN_MOTIVO_REGISTRADO | ROJO | - | **1/5** | **ninguna** |
| `58c1e091` | F2 | pdf/1p | DX_NOMBRE_DISTINTO | - | **SI** | 3/5 | tipografia |

### Legítimos (16; los 2 de cuarentena marcados)

| sha8 | Titular | Tipo | Contenedor | Cuar. | Fam. | Familias que marcan |
|---|---|---|---|---|---|---|
| `f858510e` | L2 | incapacidad | pdf/1p | - | 1/5 | - |
| `b68fe146` | L3 | incapacidad | pdf/1p | - | 1/5 | - |
| `38f40c48` | L4 | incapacidad | pdf/1p | - | 1/5 | - |
| `087739e6` | L5 | permiso | pdf/2p | - | **0/5** | - |
| `eddf194a` | L6 | incapacidad | pdf/1p | - | 2/5 | - |
| `d6482e2a` | L7 | incapacidad | pdf/1p | - | 4/5 | - |
| `100e7770` | L8 | permiso | pdf/1p | - | **0/5** | - |
| `aa3512d4` | L9 | incapacidad | pdf/1p | - | 3/5 | - |
| `e25d5211` | L10 | historia clínica | pdf/2p | - | 2/5 | - |
| `c672e270` | L10 | incapacidad | pdf/1p | - | 5/5 | - |
| `942de664` | L11 | incapacidad | jpeg | - | 1/5 | - |
| `b6e8beb6` | L12 | incapacidad | pdf/1p | - | 5/5 | - |
| `691e0af0` | L13 | incapacidad | pdf/1p | - | 2/5 | - |
| `272d0d3d` | L15 | incapacidad | jpeg | - | **0/5** | - |
| `d86ae595` | L1 | incapacidad | pdf/1p | **SI** | 1/5 | dx, firma |
| `28c4a946` | L14 | incapacidad | pdf/1p | **SI** | 4/5 | fechas, tipografia |

### Agregados sobre la base evaluable (12 / 14)

| | Adulterados (12) | Legítimos (14) |
|---|---|---|
| Familias aplicables = 0 | 0 | **3** |
| = 1 | 4 | 4 |
| = 2 | 2 | 3 |
| = 3 | 1 | 1 |
| = 4 | 2 | 1 |
| = 5 | 3 | 2 |
| Con ≥1 familia marcando | **7 (58 %)** | **0** |
| Con ≥2 familias marcando | **4 (33 %)** — pero de solo **2 titulares** | 0 |
| Titulares distintos | **5** | 13 |

**Los tres hechos que se leen en esta tabla y que no están en ningún informe individual:**

1. **Las 5 adulteradas no detectadas son fallos de COBERTURA, no de regla.** Todas tienen 1 ó 2
   familias aplicables (`9dcb4e35`, `ed2a4eeb`, `d08cba3f`, `99d74f47`, `758d3aff`). Cuatro de esas
   cinco son documentos escaneados o fotografiados sin capa de texto. Mejorar los umbrales no las
   recupera; leer el píxel sí.
2. **Un titular completo (`F7`, 3 documentos) es invisible para el motor.** A nivel de titular el
   recall es 4/5, no 7/12: hay menos casos independientes de los que sugieren los conteos.
3. **El motor solo puede dar un «limpio» con sentido en 4 de 14 legítimos.** Los otros 10 tienen ≤2
   familias aplicables. Un tablero que los pintara de verde estaría mintiendo, y por eso el veredicto
   `SIN_COBERTURA` existe como estado de primera clase (ver `../incapacidad-ocr/MOTOR_FALSEDAD.md` §4).

---

## 5. Trampas conocidas del dataset (lee esto antes de tocar nada)

1. **Los informes usan DOS numeraciones incompatibles de documento, y chocan.**
   `senales/tipografia_pdf` numera **globalmente desde 0** (`F00`…`F14`, `R15`…`R30`);
   `senales/aritmetica_fechas` numera **por clase desde 1** (`F01`…`F15`, `R01`…`R16`). Consecuencia
   real: **`F04` significa dos documentos distintos** según el informe que leas, y **`R15` también**.
   `dx_catalogo`, `dias_vs_diagnostico` y `firma_y_reuso` usan el nombre de archivo. **Usa el sha8
   como único identificador** y, si tocas las sondas, unifícalas hacia el sha8.
2. **`ocr/` tiene carpetas duplicadas**: existen `falsa/` y `falsas/`, `real/` y `reales/`. Verifica
   cuál lee cada sonda antes de asumir.
3. **El inventario de imágenes de la fase de OCR está incompleto**: no recorre Form XObjects. Medido:
   los dos archivos byte-idénticos de una pareja reportan `0` vs `2` y `0` vs `12` imágenes. No
   confíes en `estructura.paginas[].imagenes[]`; re-extrae con `max_depth=15`.
4. **Los campos de la extracción no son fiables como insumo de un check.** Medido: el CIE-10 del
   extractor difiere del código impreso en **10 de 31** documentos y en 6 devuelve algo que no es un
   diagnóstico (incluido un código derivado de la **cédula del médico** mal leída); los días de un
   legítimo se leen como **202** cuando el documento no imprime días; y `normalizar_fechas()`
   **sobrescribe en silencio** la fecha fin leída, que es justo la evidencia que busca la familia de
   fechas. Cualquier sonda nueva debe releer del texto con **procedencia y confianza propias**.
5. **La capa de texto del PDF existe en 13 de 28 PDF y vale más que el OCR.** En el único caso de la
   familia de días el diagnóstico **estaba** en la capa de texto y **no** en la salida de RapidOCR; en
   dos casos la contradicción de fechas se confirma ahí sin OCR. Es lo más barato con mayor retorno.
6. **La marca de agua de la app de escaneo tiene exactamente la geometría de una firma** (tira ancha
   y delgada, poca tinta, abajo a la derecha) y es **el recurso más reusado del corpus**: byte-idéntica
   en 5 documentos de 3 titulares, más una sexta copia reescalada. Está en 4 adulterados y 2 legítimos.
   Sin lista negra, un check de «misma imagen entre pacientes distintos» reporta 3 adulterados y 1
   legítimo… y lo que encontró es el logo de un escáner. **El filtro no es cosmético.**
7. **Las imágenes degeneradas colisionan con todo.** 42 de los 129 recursos gráficos son planos
   (máscaras, rellenos, franjas vacías) y su hash perceptual es constante: sin filtrarlas salen **558**
   «pares casi idénticos» entre documentos en vez de 34.
8. **La capa de texto sintetizada por OCR (ClearScan) es el peor confusor de tipografía**: un documento
   del corpus tiene **48 familias de fuente** y 427 objetos de texto sobre la imagen, y eso no es
   adulteración. Sin filtrar ClearScan / Paper Capture / Tesseract / ABBYY, la familia miente.
9. **Los artefactos normales de Microsoft Word parecen manipulación**: el subset `BCDGEE+` y
   `%%EOF=2 /Prev=1` aparecen en adulterados y legítimos por igual (3F/2R y 6F/4R). Ya están
   degradados a informativos; no los rehabilites sin línea base por emisor.
10. **3 de los 14 legítimos evaluables no son incapacidades** (2 permisos + 1 historia clínica) y
    varias familias los excluyen por diseño. Cuando leas «0 falsos positivos sobre 14 reales»,
    entiende **11**. Y en tipografía, **3**.

---

## 6. Qué hay que pedirle al cliente para tener un corpus usable

Ordenado por lo que desbloquea. Los cuatro primeros son del **área de radicaciones**; los siguientes,
del **DBA / ASTGU**.

### A. Arreglar el etiquetado de lo que ya tenemos (barato, alto impacto)

1. **Resolver las 2 parejas byte-idénticas.** Un documento no puede ser adulterado y legítimo a la vez.
   Devuelve al corpus **4 archivos (16 %)**, incluido el **único** ejemplo de `TIPOGRAFIA_MIXTA` y los
   dos mejores checks deterministas de esa familia. Recomendación con evidencia para `28c4a946` en §2.
2. **Clasificar las 3 filas sin motivo.** Y decir **por qué evidencia** se confirmaron: si fue una vía
   externa (la EPS o la IPS negó haber expedido el documento, el médico no existe, el trabajador lo
   admitió), esa vía es más valiosa que cualquier check y hay que registrarla como campo. Si están
   pendientes, deberían salir de la clase «adulterado» hasta que se clasifiquen.
3. **Explicar el significado del ROJO** en la tabla de motivos (5 filas). Medido: rojo **no** equivale
   a «sin motivo» —3 filas <NOMBRE> están vacías pero 2 traen motivo— y se concentra en 2 titulares, uno
   de ellos con **todas** sus filas en rojo. Hipótesis a confirmar: caso en investigación / caso
   escalado / no verificable / marca de reincidencia. Cambia si esas 5 filas se pueden usar como verdad.
4. **Aclarar qué significa la carpeta de legítimos**: ¿«verificado legítimo» o «no se detectó nada /
   no se revisó»? De eso depende si los 14 legítimos valen como control negativo o solo como muestra
   de formatos.

### B. Ampliar el corpus (lo único que permite reportar una precisión)

5. **≥100 legítimos con capa de texto**, y en particular del flujo **«un auxiliar rellena una plantilla
   Word y la exporta»** con dos o más tipografías. Es el generador de falsos positivos del único check
   que hoy carga el recall de tipografía, y este corpus **no contiene ni uno**.
6. **≥20 adulterados por señal**, con prioridad en las cuatro que tienen 1 ó 0 ejemplos
   (`TIPOGRAFIA_MIXTA`, `DIAS_VS_DIAGNOSTICO`, `FECHAS_INCOHERENTES`, `DX_FORMATO`).
7. **Adulterados de titulares distintos.** Hoy 12 documentos son 5 casos. Pedir «más documentos» sin
   pedir «más titulares y más emisores» no mejora nada: 2 de las detecciones de una familia son el
   mismo emisor y el mismo paciente contados dos veces.
8. **La tasa real de adulteración** (de cada 100 radicaciones, cuántas resultan adulteradas) y el coste
   relativo de cada tipo de error. Sin esos dos números, ningún umbral es defendible: el corpus tiene
   ≈50 % de adulterados y la realidad probablemente esté dos órdenes de magnitud por debajo.

### C. Datos del ERP (desbloquean familias completas, no documentos)

9. **`ASTGU.lpdiagnosticos`** completo, como CSV UTF-8 local (`codigo,descripcion` + `estado/activo` y
   `fechamodificacion` si existen). Hoy `DX_INEXISTENTE` y `DX_NOMBRE_DISTINTO` valen **0/12** y
   devuelven `no_verificable` en **31/31**. Con él, 2 de las 8 señales pasan de anécdota a check.
   Incluir: **versión/año de la CIE-10**, si hay **códigos retirados** y cómo se marcan, y
   `SELECT LENGTH(REPLACE(codigo,'.','')) n, COUNT(*) ... GROUP BY n` (si hay códigos de 3 caracteres,
   `DX_FORMATO_LONGITUD` **se retira**, no se ajusta).
10. **`ASTGU.lpausentismos`**, ≥2 años y ≥5.000 certificados **iniciales**
    (`prorroga = 0 AND idlpausentismo_inicial IS NULL`), con `Numerodias`, `idlpdiagnosticos`,
    `idlptipoausentismo`, IPS/EPS emisora y fecha de radicación; sin nombres ni cédulas. Desbloquea el
    check central de la familia de días, la línea base de fuentes por plantilla/IPS, la convención de
    fecha fin por emisor y los checks de prórrogas solapadas. **Advertencia previa del propio repo:** al
    estudiar ese mismo histórico para el nivel de incapacidad se concluyó que ni los días ni el
    diagnóstico separan limpiamente; puede que la señal **no exista**, y por eso el check nace apagado
    con calibración obligatoria (marcar ≤1 % del propio histórico).
11. **Validación jurídica fechada** de la tabla de pisos legales (CST art. 237 aborto: 2–4 semanas;
    art. 236 mod. Ley 2114/2021 maternidad: 18 semanas, 20 si es múltiple), con área y responsable.
    Advertencia medida: **el margen es cero** — un legítimo del corpus trae exactamente el mínimo legal.
12. **Semántica de `cheklistradicaciones`** (19 de 64 EPS traen el JSON; las otras 45 traen el literal
    `'I'` = NULL): ¿qué es `tipo_envio = 0`? ¿`archivo = 0` es «sin asignar» o «archivo 0»? ¿qué codifica
    `medioradicacion` (0/1/2)? ¿las 45 con `'I'` no exigen nada o no están configuradas?
13. **Acceso a RETHUS** (aunque sea consulta manual) para validar nombre ↔ registro ↔ habilitación.
    Hoy `FIRMA_ID_INCOHERENTE` es evaluable en **1 de 26** documentos.
14. **`id_paciente` autoritativo de la radicación.** Está medido que si esa clave se infiere mal,
    **todo el bloque de checks de reuso fabrica positivos espurios**.

### D. Lo que NO hay que pedirle al cliente

**El índice de hashes del histórico de radicaciones** (la carencia que define el techo de la familia de
firma/reuso) **no se pide: se construye.** Se autoalimenta con las radicaciones que ya entran, mediante
la tabla `lp_recursos_graficos` propuesta en `../incapacidad-ocr/MOTOR_FALSEDAD.md` §5.2. Es el ítem de
mayor retorno de toda la lista porque no depende de nadie externo.

---

## 7. Reglas para quien siga trabajando

1. **La cuarentena se excluye de todo numerador y denominador.** Se usa solo como caso de humo.
2. **Si particionas, agrupa por `sha256` Y por titular.** Los titulares `F2`/`L14` y `F6`/`L1` son la
   misma persona a los dos lados.
3. **Nunca leas el nombre del archivo** para computar nada (§1, trampa nº1).
4. **`NO_APLICABLE` no es `OK`.** Cinco informes coinciden en esto y es el error que convertiría el
   motor en falsa seguridad. Reporta siempre cobertura junto al recall.
5. **Todo check acusatorio necesita autotest sintético** (documentos fabricados con `fpdf2`/`PIL`, cero
   PII). Es lo único que distingue «el corpus no tiene casos» de «el check está roto»: la familia de
   firma ya lo demostró con 4/4 y así probó que su `0/12` era una medición.
6. **Declara qué ajustaste mirando el corpus.** Los informes actuales lo hacen y hay que mantenerlo:
   los umbrales de tipografía se eligieron **después** de ver los datos, y la única detección propia de
   la familia de fechas depende de un arreglo del lector.
7. **PII (Ley 1581).** Ni esta carpeta ni sus derivados (`ocr/`, `senales/`) se versionan. En informes,
   issues, logs y resúmenes van **conteos, métricas, sha8 y nombres de regla**; nunca nombres, cédulas
   ni diagnósticos. Los recortes de imagen usados en exploración se borran al terminar.
8. **Al terminar el ajuste del motor, borra o cifra el corpus.** Solo se conserva lo necesario.

---

## 8. Archivos de esta carpeta

| Ruta | Qué es |
|---|---|
| `manifest.csv` | índice canónico: archivo, etiqueta, sha256, bytes, ext, páginas, ruta original, cuarentena y motivo |
| `ground_truth.json` | la tabla de motivos del cliente, parseada: fila, archivo, motivo, `en_rojo`, `motivo_vacio`, señales, + taxonomía |
| `Explicacion de archivos.jpeg` | la tabla de motivos original (**no es un documento del corpus**) |
| `LEEME.md` | de dónde salió el corpus, estructura, reglas de PII, detalle de la cuarentena |
| `ESTADO_CORPUS.md` | este documento |
| `docs/{falsas,reales}/` | los 31 documentos, con el nombre original (llave para cruzar con la tabla de motivos) |
| `ocr/` | salida de OCR por documento (⚠ carpetas duplicadas, §5 trampa nº2) |
| `senales/<familia>/INFORME.md` | una por familia: checks, medición, falsos positivos, confusores, severidad, qué falta |
| `senales/<familia>/probe.py` | la sonda ejecutable de cada familia (con `--autotest` donde existe) |
| `requisitos_eps.json` · `requisitos_eps.sql` | `cheklistradicaciones` normalizado: 19 EPS, 320 filas de requisito |
| `duraciones/`, `validacion/`, `requisitos/` | trabajo previo: formas de la duración en números y letras, censo de la lógica temporal existente, benchmark de OCR |
| `_tabla_estado.py` | regenera las tablas de §4 y §3 desde los artefactos medidos |
| `build_manifest.py` | reconstruye la carpeta y el manifest desde `Descargas` (idempotente, verifica sha256) |
