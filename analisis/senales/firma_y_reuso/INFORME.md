# Familia `firma_y_reuso` — firma del médico y reuso de recursos entre documentos

Cubre el motivo **FIRMA_MEDICO** ("FIRMA DEL MEDICO").
Sonda: `probe.py` · Detalle máquina: `resultado.json` · Inventario gráfico: `recursos.json`
Todo local: `pypdfium2`, `Pillow`, `numpy`, `rapidocr-onnxruntime`, `fpdf2` (autotest). Sin IA
externa, sin APIs pagas, sin Docker, sin Ollama.

---

## 0. Lo que esta familia NO puede concluir (límite duro)

**Verificar que una firma sea auténtica está fuera de alcance.** Decidir si un trazo lo hizo
la mano de la persona que dice haberlo hecho es peritaje grafológico: requiere muestras
indubitadas de la firma de ese médico, y ningún dato de ese tipo existe en el sistema. Un
motor local no puede, ni podrá con más código, responder "¿esta firma es de este médico?".

Lo que **sí** es detectable, y es lo único que esta familia afirma:

1. **REUSO**: la misma imagen de firma/sello/fondo aparece en documentos que deberían ser
   independientes (pacientes distintos, episodios distintos, emisores distintos).
2. **INCONSISTENCIA**: la identidad impresa *dentro* del sello contradice la identidad del
   médico impresa en el texto del documento.

Corolario operativo: la familia **nunca debe afirmar "firma falsa"**. Como máximo afirma
"este recurso gráfico se reutilizó" o "el sello y el texto no concuerdan".

---

## 1. Los checks

Notación: `det` = determinista (misma entrada ⇒ misma salida, sin umbrales de parecido);
`heu` = heurístico (depende de umbrales o de la calidad del OCR).
Umbrales declarados en `probe.py::UMB` (no escondidos en el cuerpo del código).

### Paso previo obligatorio — inventario y clasificación de rol

**No se usó el inventario de imágenes de la fase de OCR: está incompleto.** Medido: los dos
documentos byte-idénticos en cuarentena reportan conteos distintos de imágenes en sus JSON de
OCR (`0` vs `2`, y `0` vs `12`). La causa es que los XObject de imagen suelen venir anidados
dentro de Form XObjects y se pierden si se recorre la página sin recursión. La sonda vuelve a
extraerlos con `page.get_objects(filter=IMAGE, max_depth=15)`: **129 recursos gráficos** en 31
documentos, contra las cuentas inconsistentes de la fase previa. *Esto es un hallazgo que
afecta a cualquier familia que dependa de `estructura.paginas[].imagenes[]`.*

Por cada recurso se calcula: `sha256` del stream crudo, `sha256` de los píxeles decodificados,
`pHash64` y `dHash64` (DCT-II 32×32 y gradiente horizontal, implementados con `numpy` — 6
líneas — para no arrastrar `imagehash`+`scipy`), tamaño en px, bbox colocado en la página,
área relativa, posición vertical relativa, aspecto, ratio de tinta, desviación estándar y
número de niveles de gris.

Rol geométrico (determinista): `DEGENERADA` · `FONDO_PAGINA` · `MEMBRETE` · `PIE` ·
`FIRMA_SELLO_CAND` · `OTRA`, más `MARCA_HERRAMIENTA` / `MARCA_PROVEEDOR` por OCR del recorte.
Reparto medido sobre los 129 recursos: **42 degeneradas, 41 candidatas a firma/sello, 20 fondo
de página, 13 membrete, 6 marcas de herramienta, 5 pie, 2 otras** → 81 comparables.

Filtrar las degeneradas es indispensable, no cosmético: una imagen plana (máscara de
transparencia, relleno sólido, franja vacía) tiene hash perceptual constante y colisiona con
todas las demás. **Medido con el mismo umbral de la sonda (`dp ≤ 6` y `dd ≤ 10`): sin el filtro
salen 558 "pares casi idénticos" entre documentos; con el filtro, 34.** Umbrales de
degeneración: `std < 4.0`, `niveles < 8`, lado `< 12 px` o área `< 900 px`.

---

### C1 · `FIRMA_REUSO_EXACTO_CROSS_PACIENTE` — det

**Afirma:** un gráfico con geometría de firma/sello es *byte-idéntico* (o *píxel-idéntico*) a
uno de otro documento cuyo **paciente es distinto**. Copiar-pegar directo.

**Cómo se calcula:**
1. Extraer los XObject de imagen con `pypdfium2` (`max_depth=15`) y su stream crudo
   (`get_data(decode_simple=False)`) → `sha256_stream`.
2. Decodificar el bitmap (`get_bitmap(render=False).to_pil()`) → `sha256` de los bytes RGB
   (`sha256_pixeles`). Esto sobrevive un cambio de contenedor sin recompresión.
3. Descartar `DEGENERADA`, `MARCA_HERRAMIENTA`, `MARCA_PROVEEDOR`.
4. Conservar solo rol `FIRMA_SELLO_CAND`: no `FONDO_PAGINA` (área ≥ 55 % de la página),
   no `MEMBRETE` (centro en el 12 % superior), no `PIE` (6 % inferior); aspecto en
   [0.25, 14], área relativa en [0.0008, 0.30], tinta ≥ 0.5 %.
5. Indexar `hash → documentos` y disparar si dos documentos con `id_paciente` distinto
   comparten un hash.

**Falta:** nada externo para el cálculo. **Pero** falta el insumo que le da poder: el
**índice de hashes del histórico de radicaciones del ERP** (ver §5).

### C2 · `FIRMA_REUSO_PERCEPTUAL_CROSS_PACIENTE` — heu

**Afirma:** la misma firma **reescalada o recomprimida** aparece en documentos de pacientes
distintos (los bytes ya no coinciden, la imagen sí).

**Cómo:** igual que C1 pero comparando `pHash64` y `dHash64`: dispara si
`Hamming(pHash) ≤ 6` **y** `Hamming(dHash) ≤ 10` **y** los aspectos difieren < 10 %, y no es
ya un match exacto. La doble condición pHash+dHash es lo que evita los falsos pares (pHash
solo confunde bloques de texto rasterizado entre sí).

**Falta:** nada externo. Umbrales calibrados a ojo sobre 87 recursos comparables; no hay
suficientes positivos reales para ajustarlos con datos.

### C3 · `FIRMA_REUSO_RECOMPRIMIDA` — heu

**Afirma:** el mismo gráfico de firma es perceptualmente idéntico en dos documentos pero **no
byte-idéntico**: el activo pasó por un re-codificador entre un documento y el otro.

**Razonamiento:** un sistema institucional incrusta el mismo archivo de firma y produce el
mismo stream. Que los bytes cambien y los píxeles no significa que alguien re-exportó,
re-comprimió o re-armó el PDF.

**Cómo:** los pares de C2 con `exacto = False`, sin exigir que el paciente sea distinto.

**Falta:** nada externo. **Confusor propio grave:** los optimizadores de PDF, los
"comprimir para enviar por correo" y las pasarelas de email recomprimen imágenes de forma
rutinaria en documentos perfectamente legítimos.

### C4 · `FONDO_REUSO_CROSS_PACIENTE` — det

**Afirma:** una imagen de **página completa** (≥ 55 % del área) es byte-idéntica entre
documentos de pacientes distintos: el escaneo entero se reusó como plantilla y solo se
sobreescribió el texto. Es la evidencia más fuerte que la familia puede producir.

**Cómo:** C1 restringido a rol `FONDO_PAGINA`.

**Falta:** nada externo.

### C5 · `FIRMA_ID_INCOHERENTE` — heu (comparación det, insumo por OCR)

**Afirma:** el número de identificación impreso **dentro** del sello (`C.C.`, `R.M.`,
`Registro`) no coincide con el registro del médico impreso en el texto del documento.
Ningún documento legítimo tiene esa contradicción.

**Cómo:**
1. Recortar cada `FIRMA_SELLO_CAND` del PDF, ampliar a ≥ 320 px de lado (RapidOCR falla en
   recortes chicos) y pasarle **RapidOCR local**.
2. Extraer del texto del recorte los números de 4–12 dígitos, descartando celulares
   colombianos (10 dígitos que empiezan en 3).
3. Comparar contra `incapacidad.medico.registro` de la fase de OCR. Si el registro del texto
   no está entre los IDs del sello → dispara.

**Falta:** **RETHUS** (Registro Único Nacional del Talento Humano en Salud). Sin RETHUS este
check solo detecta contradicción *interna*; no puede decir si el registro existe, si
corresponde a ese nombre, ni si el profesional estaba habilitado en esa fecha.

### C6 · `MEMBRETE_COMPARTIDO` — det, **informativo**

Logo/membrete/pie compartido entre documentos de pacientes distintos. **Es lo esperable**
(el logo de una IPS aparece en todos sus documentos). Se reporta para separar explícitamente
el reuso normal del sospechoso, y **no cuenta como detección**.

### C7 · `MARCA_HERRAMIENTA_CAPTURA` — det, **informativo**

Presencia de la marca de agua de una app de escaneo/edición (lista negra: CamScanner,
TapScanner, Office Lens, Adobe Scan, iLovePDF, Smallpdf, Sejda, PDF24, Foxit, WPS, Canva,
"Powered by", "Free version"…), detectada por OCR del recorte. Es señal de **procedencia**
(el documento se fotografió con el celular), no de reuso de firma. Cumple doble papel: es el
**filtro negativo** de C1–C4 (ver §4) y un aviso por sí mismo.

### C8 · `FIRMA_MEDICO_AUSENTE` — det, **informativo, hoy inservible**

**Afirma:** el texto trae la etiqueta "FIRMA DEL MÉDICO / DEL PRESTADOR / DEL PROFESIONAL"
pero no hay ningún gráfico de firma en el documento.

**Medido y por eso descartado:** la etiqueta aparece en solo **8 de 31** documentos, y en
**0 de los 12 falsos evaluables**; además suele ser "FIRMA DEL PACIENTE", no del médico. Con
24 de 26 documentos evaluables marcados como no evaluables, el check no separa nada. Se deja
implementado y explícitamente marcado no evaluable en vez de borrarlo, porque en un corpus con
formatos etiquetados sí serviría.

### C9 · `RECURSO_REUSO_CROSS_EMISOR` — det, **no evaluable hoy**

**Afirma:** el mismo activo gráfico cruza **instituciones distintas** (una firma de la IPS A
en un documento de la IPS B).

**Falta:** una extracción fiable de EPS/IPS. Medido: `incapacidad.entidad.eps` del extractor
actual devuelve fragmentos de dirección (p. ej. `"Direccion: CALLE 26A # 17 -24"`). Con eso
como clave de agrupación el check produciría ruido, no señal. **0 detectadas, 26/26 no
evaluables.** Requiere el catálogo de EPS (`lpeps.csv` ya está en disco) más un extractor de
IPS emisora que hoy no existe.

### C10 · `FIRMA_HISTORICO_ERP` — det, **no evaluable hoy**

**Afirma:** la firma del documento que entra colisiona con la de un documento radicado
anteriormente, de otro paciente.

**Falta:** el **índice de hashes (`sha256` + `pHash`) del histórico de radicaciones**.
**0 detectadas, 26/26 no evaluables.** Ver §5: es la carencia que define el techo de toda la
familia.

---

## 2. La medición real

Corpus: 31 documentos (15 falsos + 16 reales).
**Se excluyen los 5 documentos en CUARENTENA** (3 falsos y 2 reales: los dos pares
byte-idénticos entre clases y el tercer archivo que comparte cédula), porque su etiqueta no es
verdad utilizable. Quedan **26 evaluables: 12 falsos y 14 reales**.

```
FALSAS detectadas : 2 / 12
REALES marcadas   : 0 / 14   (falsos positivos)
```

Por check, sobre los 26 evaluables (`n.ev` = documentos donde el check **no puede** dar ni
positivo ni negativo):

| check | tipo | hit falsas | hit reales | n.ev |
|---|---|---|---|---|
| `FIRMA_REUSO_EXACTO_CROSS_PACIENTE` | acusatorio | 0/12 | 0/14 | 16 |
| `FIRMA_REUSO_PERCEPTUAL_CROSS_PACIENTE` | acusatorio | 0/12 | 0/14 | 16 |
| `FIRMA_REUSO_RECOMPRIMIDA` | acusatorio | **2/12** | 0/14 | 16 |
| `FONDO_REUSO_CROSS_PACIENTE` | acusatorio | 0/12 | 0/14 | 9 |
| `FIRMA_ID_INCOHERENTE` | acusatorio | 0/12 | 0/14 | 23 |
| `MEMBRETE_COMPARTIDO` | informativo | 0/12 | 0/14 | 0 |
| `MARCA_HERRAMIENTA_CAPTURA` | informativo | 3/12 | 1/14 | 0 |
| `FIRMA_MEDICO_AUSENTE` | informativo | 0/12 | 0/14 | 24 |
| `RECURSO_REUSO_CROSS_EMISOR` | informativo | 0/12 | 0/14 | 26 |
| `FIRMA_HISTORICO_ERP` | informativo | 0/12 | 0/14 | 26 |

**El número que importa más que el 2/12: `n.ev = 16`.** En **16 de los 26** documentos
evaluables (6 de 12 falsos, 10 de 14 reales) **no existe ningún XObject de firma aislable**:
son fotos de celular o escaneos de página completa donde la firma es parte de un único mapa de
bits. Los checks centrales están estructuralmente ciegos en el **62 %** del corpus. Sobre el
subconjunto donde la familia sí aplica (10 documentos: 6 falsos, 4 reales) el resultado es
**2/6 falsos detectados (33 %) y 0/4 reales marcados**.

### Las 2 detecciones (qué evidencia exactamente)

Dos incapacidades del mismo paciente con fechas de inicio separadas 5 meses comparten el mismo
bloque de firma-y-sello de 552×186 px: `pHash` y `dHash` con distancia **0**, dimensiones
idénticas, pero **`sha256` de stream distinto** y estadísticas de píxel ligeramente distintas
(`std` 70.95 vs 70.50, tinta 0.1559 vs 0.1568) → el mismo gráfico re-codificado. Dispara
`FIRMA_REUSO_RECOMPRIMIDA`. Es una señal de que el PDF se re-armó, no de que la firma sea
falsa; el sello y el registro del texto **sí** concuerdan en ambos (C5 no dispara).

### Cero falsos positivos, pero por poco

`0/14` no es mérito del diseño en dos casos, y hay que decirlo:

- Los dos documentos reales del mismo paciente (`REAL-10` + `REAL-11`)
  comparten el gráfico de firma-y-sello del médico (200×122 px) **byte a byte**. No se marca
  solo porque la agrupación por paciente funcionó. Cualquier check que ignore la identidad del
  paciente marca este par.
- Ese mismo par real comparte además el **logo** de la IPS de forma perceptualmente idéntica
  pero byte-distinta (`std` 51.57 vs 51.56): exactamente el fenómeno que dispara C3. No se
  marca solo porque ese gráfico cae en la banda `MEMBRETE` (y relativo 0.92 y 0.93) y queda
  excluido por rol. **Si una IPS legítima recomprimiera el gráfico de la firma en vez del
  logo, C3 daría un falso positivo.** El margen es la geometría, no la lógica.

### Los 5 en cuarentena (documentados, no contados)

Los pares byte-idénticos entre clases disparan como se espera y confirman que la mecánica
funciona: el par `<NOMBRE>/CED-01` dispara `FONDO_REUSO_CROSS_PACIENTE` (comparten el
escaneo de página completa de 2166×3000 px), porque el pipeline ve dos radicaciones con
pacientes distintos sobre la misma imagen. El trío `<NOMBRE> / CED-21 / INCAPACIDAD-CED-21`
**no** dispara, porque la agrupación los une correctamente en un solo paciente (la cédula del
OCR de uno corrobora la cédula del nombre de archivo del otro). Antes de arreglar la
agrupación, ese trío producía un `FIRMA_REUSO_EXACTO_CROSS_PACIENTE` **espurio**: prueba de que
todo C1–C4 depende por completo de que `id_paciente` sea correcto.

### Control positivo (el 0/12 es medición, no bug)

Como el corpus no contiene **ni un solo** caso de la misma firma cruzando pacientes distintos,
los checks centrales devuelven `False` en los 26 documentos y no habría forma de distinguir eso
de un error de programación. `python probe.py --autotest` fabrica 4 PDFs sintéticos (firmas
generadas como garabatos con PIL, cero PII) y verifica:

| documento sintético | esperado | resultado |
|---|---|---|
| firma A, paciente 1 | EXACTO + PERCEPTUAL + RECOMPRIMIDA | OK |
| firma A idéntica, paciente 2 | EXACTO + PERCEPTUAL + RECOMPRIMIDA | OK |
| firma A reescalada a 392×133 y recomprimida a JPEG, paciente 3 | PERCEPTUAL + RECOMPRIMIDA | OK |
| firma B (distinta), paciente 4 | ninguno | OK |

Los checks disparan cuando deben y callan cuando no deben. **El 0/12 del corpus es una
medición.**

---

## 3. Falsos positivos concretos y su causa

Sobre los 14 reales evaluables, la configuración final produce **0 falsos positivos
acusatorios**. Los que aparecen en checks informativos, y los que aparecerían sin los filtros:

| documento | check | causa |
|---|---|---|
| `REAL-05.pdf` (real) | `MARCA_HERRAMIENTA_CAPTURA` | Trae la marca de agua de la app de escaneo, reescalada a 289×40. Es cierto y es informativo (el documento se fotografió), no acusatorio. |
| `REAL-01.pdf` (real, **cuarentena**) | `FONDO_REUSO_CROSS_PACIENTE` + `marca-tool` | Comparte el escaneo completo con su gemelo byte-idéntico etiquetado falso. La causa es la corrupción de etiqueta del corpus, no el check. |
| — sin la lista negra de marcas de herramienta — | `FIRMA_REUSO_EXACTO_CROSS_PACIENTE` | La marca de agua de la app de escaneo marcaría **1 real y 3 falsos** no-cuarentena, todos por el motivo equivocado. |
| — sin la agrupación por paciente — | `FIRMA_REUSO_EXACTO_CROSS_PACIENTE` | El par real `REAL-10/INCAPACIDAD` marcaría 2 reales. |
| — sin el filtro de degeneradas — | `FIRMA_REUSO_PERCEPTUAL_CROSS_PACIENTE` | 558 pares espurios en vez de 34: prácticamente todo el corpus contra todo el corpus. |

---

## 4. El confusor principal de la familia

**La marca de agua de la app de escaneo tiene exactamente la geometría de una firma.**

El gráfico "Powered by CamScanner" mide 407×56 px (aspecto 7.27), va abajo a la derecha, tiene
un ratio de tinta de 0.1496 y ocupa el 0.9 % de la página: un clasificador geométrico de
"tira ancha y delgada, poca tinta, parte inferior" no puede distinguirlo de un trazo de firma.
Y aparece **byte-idéntico en 5 documentos de 3 pacientes distintos**, más una **sexta copia
reescalada a 289×40** que el hash perceptual también captura (`dp=2, dd=2`). Es decir: es el
recurso **más reusado del corpus entero** y no tiene absolutamente nada que ver con falsedad
documental. Reparto medido: 4 falsos y 2 reales.

Un check de "misma imagen entre pacientes distintos" sin lista negra reportaría 3 falsos
detectados y 1 real marcado, y quien leyera el informe creería que el motor encontró firmas
copiadas. Encontró el logo de una app de escáner. Por eso el filtro no es un detalle de
implementación: es la diferencia entre una señal y una métrica inflada.

Confusores secundarios, en orden de daño: (2) el **reuso legítimo intra-paciente** — la firma
del médico se repite por diseño entre la historia clínica y la incapacidad de la misma
consulta; (3) las **imágenes degeneradas** (42 de 129 recursos), cuyo hash perceptual constante
hace que todo colisione con todo; (4) los **logos y membretes** institucionales; (5) la
**recompresión rutinaria** de activos legítimos por optimizadores de PDF.

---

## 5. Lo que le falta (por orden de impacto)

1. **El índice de hashes del histórico de radicaciones del ERP.** Es la carencia que define el
   techo de la familia. El poder de un check de reuso crece con el tamaño del archivo contra el
   que cruza: con 26 documentos la probabilidad esperada de que dos firmas coincidan por
   casualidad —o por fraude— es prácticamente nula, y en efecto salió 0. Contra 100 000
   radicaciones históricas, una firma copiada colisiona casi con certeza. **Sobre un documento
   aislado, sin histórico, esta familia es casi ciega por construcción, no por implementación.**
2. **Un aislador de la región de firma para documentos fotografiados** (desbloquearía los 16
   documentos ciegos, 62 % del corpus). Obstáculos ya medidos: la etiqueta "FIRMA" solo existe
   en 8 de 31 documentos (0 de 12 falsos evaluables), así que no sirve como ancla; y la
   binarización global falla en las fotos de celular (tinta fuera de texto del 40–86 % en 5
   documentos por fondo oscuro). Requiere binarización adaptativa (`cv2.adaptiveThreshold`, ya
   instalado) + componentes conexos + morfología de trazo, con su propia tasa de falsos
   positivos por medir. No se implementó: es un trabajo aparte, no un ajuste.
3. **RETHUS** (Registro Único Nacional del Talento Humano en Salud), para validar
   nombre ↔ registro ↔ habilitación del profesional. Sin él, `FIRMA_ID_INCOHERENTE` solo ve
   contradicciones internas. Hoy es evaluable en **1 de 26** documentos.
4. **Extractor fiable de EPS/IPS emisora** (`lpeps.csv` ya está en disco, falta el extractor),
   para habilitar `RECURSO_REUSO_CROSS_EMISOR`.
5. **`id_paciente` desde la radicación**, no inferido. En producción ya está disponible por la
   nomenclatura de ingesta `{cedula}_{AAAAMMDD}_{TIPODOC}`; en este corpus hubo que
   reconstruirlo con union-find y una corroboración cruzada (la cédula del OCR solo se acepta
   si aparece en el nombre de archivo de otro documento, porque en 4 de 31 documentos el OCR
   confunde la cédula del paciente con otro número del formato).
6. **Catálogo de logos oficiales de EPS/IPS**, para incluir en lista blanca por referencia en
   vez de inferir "es un membrete" por geometría.
7. **No hace falta CIE-10** para esta familia.

---

## 6. Severidad recomendada

**Familia: ALERTA.** Nunca BLOQUEA por sí sola hoy.

Razón: el único check con recall sobre este corpus (`FIRMA_REUSO_RECOMPRIMIDA`, 2/12) es
justamente el más débil del conjunto, y su explicación benigna —un optimizador de PDF— es
frecuentísima en el mundo real. Los checks que sí merecerían bloquear tienen recall 0 aquí y
seguirán teniéndolo mientras no exista el histórico. Bloquear un pago de incapacidad con la
evidencia que esta familia produce **hoy** sería desproporcionado.

Por check:

| check | severidad | justificación |
|---|---|---|
| `FONDO_REUSO_CROSS_PACIENTE` | **BLOQUEA** | Determinista y sin explicación benigna: dos pacientes distintos no pueden compartir el escaneo de página completa byte a byte. Cuando dispara es casi concluyente; disparará poquísimo. |
| `FIRMA_REUSO_EXACTO_CROSS_PACIENTE` | **BLOQUEA** | Determinista, una vez excluidas marcas de herramienta, membretes y degeneradas, y con `id_paciente` proveniente de la radicación. Condición: si `id_paciente` es inferido, baja a ALERTA — se comprobó que una agrupación mala fabrica positivos espurios. |
| `FIRMA_REUSO_PERCEPTUAL_CROSS_PACIENTE` | **ALERTA** | Misma lógica pero con umbrales de parecido calibrados a ojo y sin positivos reales para validarlos. Necesita revisión humana del recorte. |
| `FIRMA_ID_INCOHERENTE` | **ALERTA** | La comparación es determinista y la contradicción no tiene explicación legítima, pero el insumo es OCR de un recorte pequeño: un dígito mal leído fabrica la contradicción. Revisión humana obligatoria. |
| `FIRMA_REUSO_RECOMPRIMIDA` | **AVISO** | Es el único que detecta algo aquí, y aun así solo dice "este PDF se re-armó". Los optimizadores de PDF producen el mismo patrón en documentos legítimos. Sirve para priorizar la cola de auditoría, no para decidir. |
| `MARCA_HERRAMIENTA_CAPTURA` | **AVISO** | Procedencia, no falsedad: medido 3 falsos y 1 real. Útil combinado con otras familias (un documento fotografiado con app de escáner no viene del portal de la EPS), inútil solo. |
| `MEMBRETE_COMPARTIDO` | **AVISO** | Puramente informativo, existe para explicar por qué un reuso *no* es sospechoso. |
| `FIRMA_MEDICO_AUSENTE` | **no usar** | 24 de 26 no evaluables. Reactivar solo con formatos que traigan la etiqueta. |
| `RECURSO_REUSO_CROSS_EMISOR`, `FIRMA_HISTORICO_ERP` | **no usar** | Faltan los datos externos. |

---

## 7. Reproducir

```bash
cd <dataset-falsedad>/senales/firma_y_reuso
PY=<repo>/.venv/Scripts/python.exe
PYTHONUTF8=1 $PY probe.py                # usa la cache recursos.json
PYTHONUTF8=1 $PY probe.py --recalcular   # re-extrae imágenes + OCR de recortes (~4 min)
PYTHONUTF8=1 $PY probe.py --autotest     # control positivo/negativo sintético
```

Archivos del directorio:

| archivo | qué es |
|---|---|
| `probe.py` | la sonda: los 10 checks + medición + autotest |
| `recursos.json` | inventario de los 129 recursos gráficos (hashes, geometría, rol, OCR del recorte) |
| `resultado.json` | resultado por documento y por check, umbrales usados, medición |
| `_final.log` | salida completa de la corrida limpia (`--recalcular`) que respalda las cifras |
| `_medicion_anclas_firma.py` + `_anclas.json` | medición auxiliar que respalda el descarte de C8: dónde aparece la etiqueta "FIRMA" y cuánta tinta queda fuera del texto reconocido |

Sobre PII: `probe.py` imprime nombre de archivo, etiqueta y resultado de los checks. Las
identidades del personal médico y las claves de agrupación salen por stdout como hash corto
(`id#xxxxxxxx`, `pac#xxxxxxxx`). Los datos con contenido (texto de los sellos) quedan en
`recursos.json` en disco. Los recortes PNG usados durante el análisis exploratorio se
eliminaron por contener datos de salud.
