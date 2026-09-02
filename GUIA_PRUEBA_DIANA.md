# Prueba del lector automático de incapacidades — guía para la sesión

**Para:** Diana Gelvez (Gruppo) · **Duración:** 30–40 minutos · **Qué se prueba:** que el sistema
lea las incapacidades, las registre para revisión y avise de las que tienen algo raro.

Todo corre **dentro de la máquina**, sin internet: los documentos son datos de salud y no salen
a ningún servicio externo (Ley 1581).

---

## Lo que vas a ver

Cargamos **tus 31 documentos**: los 15 que marcaste como adulterados y 16 legítimos. El sistema
no sabe cuáles son cuáles — los procesa todos igual, y al final comparamos su resultado con tu
tabla de motivos.

---

## 1. Que lea un documento (5 min)

Arrastra una incapacidad a la aplicación y pulsa **Procesar**.

**Qué mirar:** ¿sacó bien el nombre, la cédula, el diagnóstico, las fechas y los días? Debajo
aparece el texto que leyó, para ver de dónde salió cada dato.

**Qué es normal:** que en fotos torcidas o borrosas falle algún campo. El sistema **no adivina**:
si no pudo leer un dato lo deja vacío y lo resalta para que se complete a mano. Preferimos que
falte un dato antes que inventarlo — un dato inventado entra a la nómina.

## 2. Que procese el lote completo (10 min)

Pulsa **⚙ Procesar todos**. Procesa los 31 documentos de una vez, que es como va a trabajar de
verdad (unos 7000 al mes).

**Qué mirar cuando termine:**

- Cada documento acaba en **una sola** carpeta, y la carpeta dice qué pasó:
  `3_archivo` = listo · `2_revisar/faltan_soportes` = falta un documento · `2_revisar/datos_por_revisar`
  = algo no se leyó con certeza · `2_revisar/mal_nombrados` = el nombre no cumple la convención.
- La **bandeja de revisión** de abajo lista todo lo registrado, con los problemas de cada caso.
- Los sospechosos quedan marcados como **POSIBLE MANIPULACIÓN**, con el motivo escrito.

**Un detalle importante:** 31 documentos dan **27 casos**, no 31. La llave es la cédula, así que
los documentos de una misma persona forman un solo trámite. Tres de tus cédulas traen varios
documentos y el sistema lo avisa: *«hay N documentos base para esta cédula, ¿son trámites
distintos?»*. Queremos saber si eso pasa seguido en la operación real.

## 3. Que la revisión funcione (10 min)

Abre un caso de la bandeja. Los campos que el sistema no pudo leer salen **resaltados**.

1. Completa uno a mano y pulsa **Recalcular IDs** → vuelve a resolver la cédula, el diagnóstico y
   la EPS contra los catálogos.
2. **Aprobar** / **Guardar para revisión** / **Rechazar**.

**Lo que hay que confirmar contigo:** que este es el trabajo que quieres que haga el auxiliar —
revisar y aprobar, no digitar. Y si el formulario tiene los campos que necesita o le falta alguno.

## 4. Repetir la prueba (1 min)

Pulsa **↺ Reiniciar prueba**: los 31 documentos vuelven a la entrada y la bandeja queda limpia.
Se puede repetir tantas veces como quieras, cambiando lo que sea.

---

## Qué detectó de tus documentos adulterados — sin adornos

De los 15 que marcaste, **9 se pueden evaluar hoy** (los otros 6 se explican abajo). De esos 9,
el sistema señaló **4**:

| Documento (por su hallazgo) | Cómo lo pilló |
|---|---|
| el que trae el diagnóstico `R50.5` | ese código **no existe** en la CIE-10 |
| el que trae `Q07.3` | tampoco existe |
| el que trae `S19.0` | tampoco existe |
| el que declara **2 días** con fechas del 05/06 al 06/07 | las fechas son **32 días**, no 2 → **desfase de 30 días** |

Los tres primeros los pilla porque ya cargamos un **catálogo CIE-10 completo** (14.484 códigos,
de fuente pública, incluido en el sistema y sin depender de internet). Antes solo detectábamos
uno, porque con un catálogo armado a mano no se puede afirmar que un código no exista.

*(Los documentos se identifican aquí por el hallazgo y no por el nombre del archivo: este
documento se versiona en el repositorio y los nombres que enviaste llevan datos de pacientes.
En la sesión los abrimos y los ves con su nombre.)*

Y —esto importa igual o más— **no marcó ni una sola de las 16 legítimas**. Con 7000 casos al mes,
un sistema que sospecha de documentos buenos ahoga al auxiliar y hace que deje de mirar las
alertas; preferimos detectar menos y no gritar en falso.

**Por qué 4 de 9 y no más, y qué haría falta:**

| Lo que falta | Cuántos casos desbloquea |
|---|---|
| **Tu** catálogo de diagnósticos (`lpdiagnosticos` de ASTGU) | 2 — el catálogo público que usamos es de una edición antigua y le faltan subdivisiones; donde falta una, el sistema se calla a propósito en vez de acusar (ver abajo) |
| El **histórico de ausentismos** (`lpausentismos`) | 1 — para saber si los días son plausibles para ese diagnóstico |
| Que nos digas el motivo | 3 — están en tu tabla **sin motivo escrito**, así que no sabemos qué buscar |

**Sobre el catálogo:** el que usamos hoy responde «¿existe este código en la CIE-10?». El tuyo
responde la pregunta que de verdad importa: «¿está en el catálogo que usa Gruppo?». Y hay un
detalle que preferimos resolver conservador: si el catálogo no subdivide una categoría (p.ej.
tiene `A09` pero no `A09.9`), el sistema **no** dice que `A09.9` sea falso — puede ser un hueco
del catálogo. Con el tuyo, esos casos se recuperan sin tocar una línea de código.

---

## Lo que necesitamos de ti

**Tres cosas para desbloquear la detección:**

1. **Los catálogos reales** de la BD ASTGU: diagnósticos (`lpdiagnosticos`) y el histórico
   (`lpausentismos`). Los diagnósticos ya los cubrimos con un catálogo CIE-10 público completo,
   pero el tuyo es el autoritativo; los empleados y las EPS sí son datos de prueba todavía.
2. **Los 5 documentos con etiqueta contradictoria.** Encontramos que **el mismo archivo, idéntico
   byte a byte**, está entregado como falso *y* como legítimo (dos parejas), y uno más comparte
   cédula con un legítimo. No los usamos para medir nada hasta que nos digas cuál es la correcta.
3. **Qué significa el rojo en tu tabla.** Cinco filas tienen el nombre del archivo en rojo, y las
   tres que no traen motivo escrito son de esas cinco. Si el rojo quiere decir algo, cambia cómo
   los tratamos.

**Y dos decisiones de operación:**

4. **La convención de nombres.** El sistema agrupa los documentos de un trámite por el nombre del
   archivo: `cédula_TIPO.pdf` (p.ej. `1000000001_INCAPACIDAD.pdf` + `1000000001_FURAT.pdf`,
   con una cédula de ejemplo ficticia). La
   fecha **no** va en el nombre, la lee del documento. Hay que validar que quien recibe por
   WhatsApp y correo pueda nombrarlos así — es la pieza de la que depende todo el flujo por lotes.
   Detalle en la [guía de recepción](GUIA_RECEPCION_INCAPACIDADES.md), pensada para ese equipo.
5. **Si nos envías el `.xlsx`** de la tabla de motivos en vez del pantallazo, evitamos leer
   nombres de pacientes por OCR y desaparece la duda del orden de las filas.

---

## Lo que todavía no está

Para que la prueba se juzgue por lo que es:

- **Apunta a una BD de prueba, no a la ASTGU real.** Es lo primero que cambia al instalar.
- **La detección de adulteración está a medias**, por lo de arriba: las señales están
  especificadas y medidas, pero dos de las cinco familias siguen necesitando datos que no tenemos
  (el histórico de ausentismos y tu catálogo de diagnósticos).
- **Los permisos manuscritos** los lee mal el motor rápido. Hay un segundo motor (IA local) que
  los lee mucho mejor, pero es lento en CPU y el recuadro remunerado/no remunerado **no** se
  detecta de forma confiable con ninguno de los dos: ese campo lo elige el auxiliar a mano.
- **Aún no está en un servidor.** Corre en un equipo de desarrollo y solo es accesible desde esa
  máquina, a propósito (los documentos tienen datos de salud). Para dejarlo en un servidor con
  acceso desde la red hace falta el equipo y añadirle cifrado de conexión y usuarios:
  [`INSTALACION_CLIENTE.md`](INSTALACION_CLIENTE.md) tiene el hardware y los pasos.
