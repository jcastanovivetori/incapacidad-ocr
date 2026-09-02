# Cómo probar el sistema con las incapacidades falsas y reales

Guía para ejecutar la prueba de punta a punta con los **31 documentos reales del cliente**
(15 adulterados + 16 legítimos) y repetirla tantas veces como se quiera.

---

## 1. Levantar

```bash
docker compose up -d --build          # UI en http://localhost:8000
```

Sin Docker (para probar rápido en un equipo de desarrollo):

```bash
pip install -r requirements.txt
uvicorn incapacidad_ocr.webapp:app --host 127.0.0.1 --port 8000
```

> Sin base de datos el sistema **lee y extrae** pero no registra: la bandeja de revisión y el
> procesamiento por lotes necesitan MySQL. El `docker compose` ya trae uno con catálogos de prueba.

## 2. Dejar la base de datos lista (con catálogos del corpus)

El lote **registra** en `lp_ausentismos_ia`, así que sin base de datos no puede funcionar (el botón
«Procesar todos» devuelve 503 y te ofrece la corrida en seco). Y con los catálogos mínimos de
`sql/init.sql` —pensados para `../Ejemplos`— la prueba tampoco dice nada: ninguna cédula ni
diagnóstico del corpus real coincide, así que **todo** cae en «datos por revisar».

```bash
docker compose up -d db                              # MySQL en 127.0.0.1:3306
python scripts/sembrar_bd_prueba.py                  # catálogos calcados del corpus real
```

El sembrado deja:

| Catálogo | Qué siembra |
|---|---|
| `lpempleados` | las cédulas del corpus, con el nombre **bien escrito** (el catálogo es la fuente autoritativa y es lo que corrige los nombres que el OCR entrega pegados) |
| `lpdiagnosticos` | los CIE-10 de los documentos, **menos** `R50.5`, `A09`, `A00` y `G43` |
| `lpentidades` + `lpeps` | las EPS con su `cheklistradicaciones` **real** (el JSON del ERP). `lpeps` no existe en `init.sql`: sin ella el checklist de radicación nunca se evalúa |

> **Los cuatro diagnósticos ausentes son a propósito:** son los que el cliente declaró
> inexistentes. Si se sembraran, la señal «este CIE-10 no existe» no dispararía nunca y la prueba
> no podría detectar esos documentos. Es la diferencia entre una BD de demo y una BD que sirve
> para probar.
>
> `lprequisitos_eps` se deja con los requisitos internos de `init.sql` — **no** con los 320 del
> checklist de radicación: son exigencias distintas (radicar ante la EPS pide más que recibir
> internamente), y mezclarlas mandaría casi todo a `faltan_soportes`.

**Si la app corre fuera de Docker** (lo habitual al desarrollar), apúntala a esa BD y declara que
es de prueba para que el reinicio pueda vaciarla:

```bash
DB_HOST=127.0.0.1 RESET_BD_PRUEBA=1 uvicorn incapacidad_ocr.webapp:app --host 127.0.0.1 --port 8000
```

> Si `docker compose up -d db` levanta un volumen **ya existente**, `sql/init.sql` **no** se
> ejecuta (solo corre en el primer arranque de un volumen vacío) y el esquema puede quedar viejo,
> sin las columnas nuevas. Para rehacerlo: `docker compose down -v && docker compose up -d db`
> — ojo, eso **borra también el volumen de los modelos de Ollama**, que habría que volver a bajar.
>
> Justo después de arrancar, MySQL tarda unos segundos en aceptar conexiones y el lote puede
> responder 503 aunque el contenedor ya esté en pie. Espera a que `docker compose ps db` diga
> `healthy`.

## 3. Cargar el corpus de prueba

```bash
python scripts/sembrar_prueba_falsedad.py
```

Toma los documentos de `../dataset-falsedad/docs/`, los renombra a la nomenclatura de entrada
`cedula_TIPODOC.ext`, los reparte entre los tres canales y los deja en `ingesta/1_entrada/`.
Además guarda una **semilla inmutable** en `ingesta/_sistema/semilla/` para poder reiniciar.

Deja también `ingesta/_sistema/semilla/MAPEO.csv`, que es la clave para interpretar los
resultados: relaciona cada nombre nuevo con el original, su etiqueta (`falsa`/`real`), de dónde
salió la cédula (`ocr` / `nombre` / `sintetica`), las señales de adulteración que declaró el
cliente y si está en cuarentena.

**Qué esperar:** 31 documentos → **27 casos**. No es un error: la **llave de caso es la cédula**,
así que los documentos de un mismo empleado forman un solo trámite. Tres cédulas traen varios
documentos y el lote lo avisa con *«Hay N documentos base para la cédula X (¿trámites distintos?)»*.
Para evaluar un documento **suelto**, usa el arrastrar-y-soltar de la UI.

## 4. Procesar

En la UI, panel **«Procesamiento por lotes»** → **«⚙ Procesar todos»**. O por API:

```bash
curl -s http://localhost:8000/api/lote/pendientes    # cuenta lo que espera en 1_entrada
curl -s -X POST http://localhost:8000/api/lote/procesar \
     -H "Content-Type: application/json" -d '{"extractor":"rule"}'
```

Cada documento acaba en **una sola** zona, y la carpeta dice qué pasó:

| Zona | Significa |
|---|---|
| `3_archivo/<Persona>/<AAAA>/<MM>/<DD>/` | caso **completo**: soportes al día y datos leídos sin problemas |
| `2_revisar/faltan_soportes/` | falta un documento requerido → hay que pedirlo |
| `2_revisar/datos_por_revisar/` | los soportes están, pero algo no se leyó con certeza |
| `2_revisar/mal_nombrados/` | el nombre no cumple la nomenclatura |
| `2_revisar/con_error/` | fallo técnico |

La **bandeja de revisión** de abajo lista los registros. Los que el sistema considera
sospechosos quedan en estado `POSIBLE_MANIPULACION`, con el motivo.

## 5. Reiniciar y repetir

Botón **«↺ Reiniciar prueba»** (junto a «Procesar todos»), o:

```bash
curl -s -X POST http://localhost:8000/api/lote/reiniciar \
     -H "Content-Type: application/json" -d '{"limpiar_bd":true}'

python -m incapacidad_ocr.batch --reiniciar          # equivalente por CLI
python -m incapacidad_ocr.batch --reiniciar --conservar-bd   # sin tocar la base de datos
```

Devuelve los 31 documentos a `1_entrada/` **conservando el canal de cada uno** y reinicia también la
base de datos, para que la corrida siguiente empiece igual que la primera.

Qué hace con la BD depende de una **declaración explícita del entorno**, no del botón:

| `RESET_BD_PRUEBA` | Qué hace | Para qué |
|---|---|---|
| `=1` (lo pone `docker-compose.yml`) | **vacía** `lp_ausentismos_ia` y `lp_alertas_documentacion` | reinicio de verdad: la bandeja queda limpia incluso si en la corrida anterior se aprobó o rechazó algo |
| ausente | borra solo las filas **pendientes** de esos archivos | conservador: es lo que corre si alguien apunta esto a una BD que no declaró como de prueba |

Los **catálogos no se tocan** en ningún caso: son la entrada de la prueba, no su resultado. Y el
vaciado exige esa variable a propósito — es la única salvaguarda que impide vaciar el staging de la
BD ASTGU real, y por eso no debe existir en producción.

## 6. Qué mirar para juzgar el resultado

1. **¿Detecta las adulteradas?** Cruza la bandeja con la columna `senales_declaradas` de
   `MAPEO.csv`. Ojo con qué es responsabilidad de qué: los motivos de tipo fechas/días los cubre el
   motor de tiempos; los de firma y tipografía, el de autenticidad; los de diagnóstico necesitan el
   **catálogo CIE-10 real** (ver limitación abajo).
2. **¿Marca legítimas?** Es el fallo caro. Con 7000 casos al mes, una regla que marque documentos
   buenos ahoga al auxiliar y tapa las alertas de verdad. Revisa cuántos de los 16 reales quedan
   marcados y por qué.
3. **Cuarentena:** 5 documentos están marcados `cuarentena=si` en `MAPEO.csv` — dos pares son
   **byte-idénticos entre las dos clases** (el mismo archivo aparece como falso y como real) y uno
   comparte cédula con un real. **No los uses para medir precisión** hasta que el cliente resuelva
   la contradicción.

## 7. Pruebas automáticas

```bash
python tests/test_processor.py            # pipeline: OCR, extracción, fechas
python tests/test_numeros_es.py           # duraciones en letras ("DOS", "DOS (2)") y falsos positivos
python tests/test_validacion_temporal.py  # motor de tiempos: reglas, config en caliente
python tests/test_reinicio_prueba.py      # reinicio de la prueba y seguridad del borrado en BD
python tests/test_authenticity.py         # señales de manipulación del documento
python tests/test_erp_diagnostico.py      # diagnóstico contra el catálogo CIE-10
python tests/test_radicacion.py           # checklist de radicación por EPS
python tests/test_ejemplos_reales.py      # precisión sobre los 8 documentos de ../Ejemplos
```

## 8. Limitaciones de esta prueba (leer antes de concluir)

- **Sin el catálogo CIE-10 real** (`lpdiagnosticos` de ASTGU) no se puede afirmar que un
  diagnóstico no existe, así que esa familia de señales queda desactivada a propósito: sin
  catálogo *ningún* código resuelve y marcaría el 100% de los documentos. Lo que sí funciona sin
  catálogo es la validación de **formato** (un CIE-10 de 3 caracteres cuando todos los válidos
  tienen 4).
- **Sin el histórico `lpausentismos`** no se pueden validar solapamientos ni prórrogas.
- El corpus es **pequeño** (15 + 16, menos 5 en cuarentena). Sirve para ver el comportamiento, no
  para afirmar una precisión.
- Los documentos son **datos de salud**: viven fuera del repositorio (`../dataset-falsedad/`) y no
  se versionan (Ley 1581).
- En este entorno local el OCR corre una versión **más antigua** del motor que en Docker
  (Python 3.14 fuerza `rapidocr 1.2.3` / PP-OCRv3, 76% de acierto, frente a 1.4.4 / PP-OCRv4, 82%).
  En producción lee **mejor** que aquí.

Instalación y hardware para producción: [`INSTALACION_CLIENTE.md`](INSTALACION_CLIENTE.md).
Detección de adulteración: [`MOTOR_FALSEDAD.md`](MOTOR_FALSEDAD.md).
Carpetas de la ingesta: [`ingesta/LEEME.md`](ingesta/LEEME.md).
