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

## 2. Cargar el corpus de prueba

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

## 3. Procesar

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

## 4. Reiniciar y repetir

Botón **«↺ Reiniciar prueba»** (junto a «Procesar todos»), o:

```bash
curl -s -X POST http://localhost:8000/api/lote/reiniciar \
     -H "Content-Type: application/json" -d '{"limpiar_bd":true}'

python -m incapacidad_ocr.batch --reiniciar          # equivalente por CLI
python -m incapacidad_ocr.batch --reiniciar --conservar-bd   # sin tocar la base de datos
```

Devuelve los 31 documentos a `1_entrada/` **conservando el canal de cada uno**, y borra las filas
de staging **pendientes** de esos archivos para que el lote no las duplique. Lo que un auxiliar ya
**aprobó o rechazó no se toca**, y el borrado se filtra por nombre de archivo: nunca es un borrado
masivo de la tabla.

## 5. Qué mirar para juzgar el resultado

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

## 6. Pruebas automáticas

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

## 7. Limitaciones de esta prueba (leer antes de concluir)

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
