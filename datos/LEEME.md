# `datos/` — catálogos públicos de referencia

Datos de referencia **públicos y sin datos personales**, así que sí se versionan: un `git pull`
los trae y el sistema funciona sin descargar nada.

| Archivo | Qué es | Cómo se regenera |
|---|---|---|
| `cie10.csv` | Clasificación CIE-10 en español, 14.484 entradas (`codigo,descripcion`) | `python scripts/descargar_cie10.py --forzar` |

## Por qué esto no rompe el «100% local, sin APIs de pago»

La descarga ocurre **una sola vez, al construir**, igual que los modelos ONNX que `rapidocr` trae
dentro de su wheel. No hay clave de API, no hay servicio de IA y **en runtime no se consulta nada
por red**: el catálogo se carga en `lpdiagnosticos` (MySQL) y la búsqueda es un `SELECT` local. En
un servidor aislado el CSV viaja con el repositorio y no hace falta internet ni una vez.

## Para qué hace falta

Es lo que convierte «este diagnóstico no existe» en una afirmación verificable. Sin catálogo
*ningún* código resuelve, así que la señal marcaría el 100% de los documentos legítimos y habría
que dejarla apagada. Con él, sobre el corpus real del cliente, la detección de documentos
adulterados pasó de **2 a 5 de 9**.

## Procedencia, y por qué importa

La fuente es un repositorio público con la CIE-10 de la OMS en español
(`cayasso/cie10`). **No es la tabla oficial del Ministerio de Salud de Colombia**: esa no está
publicada como dato abierto — se buscó en `datos.gov.co` y solo hay datasets que *usan* los
códigos, ninguno que los defina.

Dos consecuencias, y las dos están manejadas en el código:

1. **Se valida lo que se descarga.** `descargar_cie10.py` comprueba el archivo contra hechos que
   el cliente confirmó (que `R50.5` **no** exista, que `R50.9`/`M54.5`/`N20.0`/`S52.0`/`G43.0` sí,
   que haya >10.000 entradas y códigos de 4 caracteres) y **aborta sin escribir** si algo no
   cuadra. Un catálogo equivocado no es un catálogo incompleto: es una fábrica de acusaciones
   falsas contra documentos legítimos.

2. **Es una edición ANTIGUA de la CIE-10** y le faltan subdivisiones que las nuevas sí tienen
   (`A09.0`/`A09.9`, `B04.0`). Eso **no** se puede tratar como «el código no existe». Por eso la
   señal exige, además de que el código falte, que el catálogo **subdivida** su categoría de 3
   caracteres (`erp.Lookups.categoria_subdividida`):

   - `R50` tiene hijos en el catálogo (`R50.0`, `R50.1`, `R50.9`) → un `R50.5` ausente **sí** es
     un código que no existe → **señal**.
   - `A09` no tiene hijos en esta edición → un `A09.9` ausente es un hueco del catálogo →
     **no verificable**, se anota como problema para el auxiliar pero **no** como sospecha.

   Medido: 276 de las 2.070 categorías no están subdivididas. Sin esta guarda, dos documentos
   legítimos del corpus (`A09.9` y `B04.0`) quedaban acusados de manipulación.

## Cuando llegue el catálogo real del cliente

Es lo que hay que usar: `lpdiagnosticos` de ASTGU es el catálogo **autoritativo** y responde la
pregunta correcta («¿está en el catálogo que usa Gruppo?»), mientras que este responde una parecida
pero distinta («¿existe en la CIE-10?»). Al cargarlo, la guarda de subdivisión sigue siendo
correcta y probablemente deje de bloquear casos, porque un catálogo completo subdivide todo lo que
tiene que subdividir. No hay que cambiar código: solo cargar la tabla.
