# Replicar el proyecto en otra máquina

Qué trae el `git pull` y qué hay que aportar aparte, para dejar el sistema **funcionando y con la
prueba lista** en una máquina nueva.

---

## Lo que NO está en el repositorio (y por qué)

Una sola cosa, pero hay que tenerla clara: **los documentos**. Son incapacidades médicas reales,
con nombre y cédula de personas identificadas — datos sensibles de salud (Ley 1581). Este
repositorio se comparte fuera de Gruppo, y lo que entra en el historial de git no se puede
sacar. Por eso los documentos viven **fuera del árbol de git** y el repositorio trae, en su
lugar, **todo lo necesario para regenerar lo demás a partir de ellos**.

| Fuera del repo | Qué es | De dónde sale |
|---|---|---|
| `../dataset-falsedad/docs/{falsas,reales}/` | los 31 documentos del corpus de falsedad | los entrega el cliente |
| `../Ejemplos/` | los 8 documentos de la demo original | los entrega el cliente |
| `~/Downloads/lpeps.csv` | catálogo de EPS con `cheklistradicaciones` | export del ERP |
| `../dataset-falsedad/ocr/` | texto y campos extraídos | **se regenera** (paso 4) |
| `../dataset-falsedad/seed_bd_prueba.sql` | catálogos con cédulas reales | **se regenera** (paso 5) |
| `ingesta/**` (documentos) | el corpus repartido en la entrada | **se regenera** (paso 6) |
| `.env` | credenciales | copiar de `.env.example` |
| `.venv/` | entorno de Python | `pip install` |

Todo lo demás **sí** está versionado: código, pruebas, el análisis completo con seudónimos
(`analisis/`), los generadores, el esquema de la BD y la documentación.

---

## Los pasos

### 1. Traer el código y el entorno

```bash
git clone <repo> && cd incapacidad-ocr        # o: git pull
cp .env.example .env                           # y ajústalo si hace falta
python -m venv .venv && .venv/Scripts/activate # en Linux/Mac: source .venv/bin/activate
pip install -r requirements.txt
```

> **Usa Python 3.12.** Con 3.13+ `pip` degrada `rapidocr-onnxruntime` a la versión de 2023 y el
> OCR pierde ~6 puntos de precisión (76% en vez de 82%). Es el mismo intérprete que usa el
> `Dockerfile`, así que el entorno local se parece a producción.

Comprobación: `python tests/test_processor.py` debe terminar en `TODO OK` sin necesidad de nada
más (usa una imagen sintética generada al vuelo).

### 2. Levantar la base de datos

```bash
docker compose up -d db          # MySQL en 127.0.0.1:3306
docker compose ps db             # esperar a que diga (healthy)
```

En un volumen vacío esto deja la BD **operativa sola**: `sql/init.sql` crea el esquema y
`sql/catalogos_publicos.sql` carga el **catálogo CIE-10 completo** (14.484 códigos) y la tabla
`lpeps`. Los dos van montados en `docker-entrypoint-initdb.d` (ver `docker-compose.yml`).
Comprobación: `docker exec ocr-db mysql -uocr -pocr ASTGU -e "SELECT COUNT(*) FROM lpdiagnosticos;"`
debe dar **14484**.

> **`init.sql` solo corre en el primer arranque de un volumen vacío.** Si el volumen ya existía, el
> esquema puede estar viejo; volver a aplicarlo es idempotente:
> `docker exec -i ocr-db mysql -uroot -proot ASTGU < sql/init.sql`, y para los catálogos
> `python scripts/cargar_catalogos.py` (paso 5). Recrear el volumen desde cero es
> `docker compose rm -sf db && docker volume rm incapacidad-ocr_db-data`. **No uses
> `docker compose down -v`**: eso borra también el volumen `ollama-models` y hay que volver a
> descargar ~6,5 GB de modelos.

### 3. Poner el corpus en su sitio

```
<carpeta padre>/
├── incapacidad-ocr/          ← este repositorio
├── Ejemplos/                 ← los 8 documentos de la demo
└── dataset-falsedad/
    └── docs/
        ├── falsas/           ← los 15 adulterados
        └── reales/           ← los 16 legítimos
```

Los nombres de archivo importan: los legítimos vienen como `cedula_TIPODOC.ext` y los adulterados
como los entregó el cliente. De ahí salen las cédulas y los seudónimos.

### 4. Regenerar el manifiesto y el texto OCR

```bash
python analisis/build_manifest.py     # manifest.csv: hashes, etiquetas y CUARENTENA
```

El texto OCR de cada documento (`dataset-falsedad/ocr/`) lo produce el pipeline; la forma más
directa de tenerlo es correr el lote una vez (paso 7) o procesar los documentos por la UI. Sin él
funcionan el sistema y las pruebas, pero **no** las sondas de `analisis/`, que leen ese texto.

### 5. Sembrar los catálogos de la BD

**Si el volumen de la BD era nuevo, el catálogo ya quedó cargado en el paso 2** y este paso solo
añade los datos que dependen del corpus. Sobre una BD que ya existía, o para recargar el catálogo:

```bash
python scripts/cargar_catalogos.py     # catálogo CIE-10 + tabla lpeps + EPS. NO necesita el corpus.
```

Funciona con **solo Docker** (aplica el SQL con el cliente `mysql` dentro del contenedor, no
necesita `mysql-connector-python` en el host) y tarda ~3 s. El catálogo CIE-10
(`datos/cie10.csv`) **ya viene en el repositorio**; si alguna vez hace falta refrescarlo:
`python scripts/descargar_cie10.py --forzar` (una sola descarga, valida lo que baja y aborta si no
cuadra — ver [`datos/LEEME.md`](datos/LEEME.md)).

Y ahora sí, lo que **sí** depende del corpus (empleados y las EPS reales con su checklist):

```bash
python scripts/sembrar_bd_prueba.py
```

Sin esto la prueba no dice nada: los catálogos de `sql/init.sql` están hechos para `../Ejemplos`
y ninguna cédula ni diagnóstico del corpus coincide, así que los 27 casos caen en «datos por
revisar». El script siembra los empleados del corpus, los CIE-10 de los documentos y las EPS con
su `cheklistradicaciones` real, y crea la tabla `lpeps` (que `init.sql` no tiene). Detalle y la
razón por la que **cuatro diagnósticos se omiten a propósito**: [`PRUEBAS.md`](PRUEBAS.md) §2.

### 6. Cargar el corpus en la entrada

```bash
python scripts/sembrar_prueba_falsedad.py
```

Renombra los documentos a la nomenclatura de entrada, los reparte entre los tres canales, deja
una semilla inmutable para poder reiniciar, y escribe `MAPEO.csv` (la clave para interpretar los
resultados).

### 7. Levantar la aplicación y probar

```bash
DB_HOST=127.0.0.1 RESET_BD_PRUEBA=1 uvicorn incapacidad_ocr.webapp:app --host 127.0.0.1 --port 8000
```

O el stack completo en Docker: `docker compose up -d --build`.

Abre http://localhost:8000 → **«⚙ Procesar todos»**. Para repetir: **«↺ Reiniciar prueba»**.
Qué esperar y cómo juzgarlo: [`PRUEBAS.md`](PRUEBAS.md).

### 8. (Opcional) Regenerar el análisis

Si se rehace el análisis sobre el corpus, para volver a traerlo al repo sin PII:

```bash
python scripts/exportar_analisis.py
```

---

## Si no tienes el corpus

El sistema **funciona igual**: es un pipeline de OCR, no un modelo entrenado. Lo que no puedes
hacer sin los documentos es reproducir las mediciones. Con solo el `git pull` ya tienes:

- el sistema **operativo con dos comandos** (`git clone` + `docker compose up -d --build`), con el
  catálogo CIE-10 completo cargado solo — verificado arrancando un MySQL con el volumen vacío. Lo
  único que falta son los **empleados**: una cédula es un dato personal y no se inventa, así que sin
  el volcado de ASTGU los casos salen con «cédula no encontrada». Guía de prueba para el cliente:
  [`MANUAL_PRUEBA.md`](MANUAL_PRUEBA.md);
- las **8 baterías de pruebas** (`tests/`), que no necesitan corpus ni base de datos —
  verificado sobre un clon limpio;
- el escenario de demo: `python scripts/sembrar_demo.py`. Sin `../Ejemplos` genera los **3 casos
  sintéticos** (accidente de trabajo, vacaciones y permiso) y avisa de los 2 que omite, que son
  los que usan documentos reales. Con esos 3 se ve el flujo completo;
- el análisis y las métricas ya medidas, en `analisis/`, con seudónimos;
- el benchmark para medir en tu propio hardware: `python analisis/requisitos/bench_ocr.py`.

---

## Lo que hace falta para PRODUCCIÓN (y no está aquí)

Nada de lo anterior es suficiente para poner esto a trabajar de verdad. Falta, y depende del
cliente:

- **La BD ASTGU real** (`DB_*` en `.env`). Los catálogos de prueba son eso, de prueba.
- **El catálogo CIE-10 del cliente** (`lpdiagnosticos` de ASTGU). El repo ya trae uno público
  completo (`datos/cie10.csv`) que hace funcionar la señal, pero el del cliente es el autoritativo:
  responde «¿está en SU catálogo?» en vez de «¿existe en la CIE-10?».
- **El histórico `lpausentismos`**, para validar solapamientos y prórrogas.
- El servidor y su preparación: [`INSTALACION_CLIENTE.md`](INSTALACION_CLIENTE.md).
