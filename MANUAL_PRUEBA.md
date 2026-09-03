# Probar el lector de incapacidades — 15 minutos

**Para:** Diana Gelvez (Gruppo). **Objetivo:** que veas si lee bien **tus** documentos y nos digas
qué está mal. No es una demo de venta: lo que buscamos son los errores.

Todo corre **dentro del computador**, sin internet. Los documentos son datos de salud y no salen
a ningún servicio externo (Ley 1581).

---

## 1. Levantarlo (2 comandos, una sola vez)

Hace falta **Docker Desktop** instalado. Nada más: ni Python, ni bases de datos, ni licencias.

```bash
git clone <url-del-repositorio> && cd incapacidad-ocr
docker compose up -d --build
```

La primera vez tarda unos minutos (descarga e instala todo). Cuando termine, abre:

**http://localhost:8000**

Para saber si quedó bien: la página abre y arriba dice que la base de datos está disponible.
Si algo falla, `docker compose logs incapacidad-ocr` muestra el motivo.

> Queda con el catálogo CIE-10 completo (14.484 diagnósticos) ya cargado, pero **sin empleados**:
> las cédulas son datos personales y no las inventamos. Eso significa que en tus pruebas verás
> «cédula no encontrada» — es lo esperado hasta que nos pasen el catálogo de ASTGU, y no afecta
> a lo que sí queremos medir, que es la **lectura**.

---

## 2. La prueba que más nos sirve: un documento tuyo (5 min)

Arrastra una incapacidad tuya (foto o PDF) a la página y pulsa **Procesar**.

Mira los campos que sacó: **nombre, cédula, diagnóstico, fechas y días**. Debajo aparece el texto
que leyó el motor, para que veas de dónde salió cada dato.

**Repítelo con 5 o 6 documentos distintos**, y a propósito con los más difíciles: fotos torcidas,
oscuras, tomadas con el celular, formatos de EPS distintos, manuscritos.

**Lo que es normal:** que en un documento malo falle algún campo. El sistema **no adivina**: si no
puede leer un dato lo deja vacío y lo resalta para que se complete a mano. Preferimos que falte un
dato antes que inventarlo, porque un dato inventado entra a la nómina.

**Lo que NO es normal y queremos saber:** que ponga un dato **equivocado** con aparente seguridad
(fechas cambiadas, días que no son, un diagnóstico que no corresponde). Eso es lo grave.

## 3. El lote, que es como va a trabajar de verdad (5 min)

En la operación real los documentos no se suben de a uno: llegan por WhatsApp y correo, y el
sistema los procesa en bloque de noche.

1. Copia varios documentos a la carpeta `ingesta/1_entrada/whatsapp/`.
2. Renómbralos así: **`cedula_TIPODOC.pdf`** — por ejemplo `1000000001_INCAPACIDAD.pdf` y su
   soporte `1000000001_HISTORIA.pdf`. **La fecha no va en el nombre**, se lee del documento.
3. En la página, pulsa **⚙ Procesar todos**.

Cuando termine, cada documento queda en **una sola** carpeta, y la carpeta dice qué pasó:

| Carpeta | Significa |
|---|---|
| `3_archivo/` | completo, listo |
| `2_revisar/faltan_soportes/` | falta un documento que ese tipo exige |
| `2_revisar/datos_por_revisar/` | algo no se leyó con certeza |
| `2_revisar/mal_nombrados/` | el nombre no cumple la convención |

Abajo, la **bandeja** lista todo lo registrado con los problemas de cada caso, y los sospechosos
salen marcados como **POSIBLE MANIPULACIÓN** con el motivo escrito.

**Aquí hay una decisión tuya, no nuestra:** ¿puede quien recibe los documentos por WhatsApp
nombrarlos `cedula_TIPODOC`? De esa pieza depende todo el flujo por lotes. Si no es viable, hay
que buscar otra forma de agrupar y preferimos saberlo ahora.

## 4. Volver a empezar (10 segundos)

El botón **↺ Reiniciar prueba** devuelve los documentos a la entrada y limpia la bandeja. Puedes
repetir cuantas veces quieras.

---

## 5. Qué necesitamos que nos cuentes

No hace falta un informe. Con esto nos alcanza:

1. **De cada documento que leyó mal:** qué campo y qué decía el papel. (Si nos puedes mandar el
   documento, mejor — es lo que nos deja arreglarlo.)
2. **¿Marcó algo bueno como sospechoso?** Eso para nosotros es más grave que dejar pasar uno malo:
   con 7000 casos al mes, un sistema que desconfía de los documentos buenos hace que el auxiliar
   deje de mirar las alertas.
3. **¿Le falta algún campo** al formulario de revisión para que el auxiliar pueda trabajar?

---

## Lo que ya sabemos que falta (para que no lo reportes como hallazgo)

- **Sin empleados en el catálogo** → «cédula no encontrada». Se resuelve con el volcado de ASTGU.
- **Los permisos manuscritos se leen mal** con el motor rápido, y el recuadro
  remunerado/no remunerado no se detecta de forma confiable: ese lo elige el auxiliar a mano.
- **La detección de adulteración está a medias.** Hoy pilla códigos de diagnóstico que no existen
  y desfases entre las fechas y los días declarados. Nos falta comparar el **nombre** del
  diagnóstico —nuestro lector está tomando el rótulo de la columna en vez del texto, es un arreglo
  nuestro— y validar solapamientos y prórrogas, que necesita el histórico de ausentismos.
- **Esto no es un servidor todavía.** Corre en un computador y solo se ve desde ahí, a propósito.
  Montarlo para varios usuarios es un paso aparte y no es el de esta prueba.
