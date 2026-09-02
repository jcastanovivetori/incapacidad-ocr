# Requisitos de software — `incapacidad-ocr`

**Inventario verificado contra el repo, no contra la documentación.** Fecha de medición: **2026-09-02**.
Alcance: qué hay que instalar, en qué versión, cuánto pesa, de dónde sale, y **cómo instalarlo en un
servidor sin salida a internet** (que es el escenario real del cliente: el runtime es offline por diseño
— PII de salud, Ley 1581).

---

## 0. Cómo se midió y qué NO se pudo medir

| Fuente | Qué salió de ahí |
|---|---|
| `.venv` del proyecto (`Python 3.14.5`, Windows x64) | versiones que **hoy funcionan**, tamaño en disco por paquete, precisión del pipeline |
| `pip download` real contra PyPI (2026-09-02) | tamaño exacto de los bundles de ruedas, tags de plataforma, resolución que produce `requirements.txt` hoy |
| Instalación real en un venv limpio con `--no-index` | validación end-to-end del procedimiento offline |
| `tests/test_ejemplos_reales.py` sobre los 8 documentos de `../Ejemplos` | precisión medida (76% / 82%, ver §1.3) |
| API de Docker Hub y de `registry.ollama.ai` | tamaño **comprimido** real de imágenes y modelos |
| Lectura de `Dockerfile`, `docker-compose.yml`, `requirements.txt`, `incapacidad_ocr/*.py` | dependencias declaradas vs usadas, límites, variables de entorno |

**No medible en esta máquina** (Docker Desktop requiere elevación UAC que la sesión no tiene, Ollama tampoco
corre): el tamaño **en disco (descomprimido)** de las imágenes Docker y el tamaño del volumen `db-data`.
Donde aparece un número de esos va marcado **[estimado, sin verificar]** y se indica el comando para medirlo.

---

## 1. Desajustes: `requirements.txt` ↔ código ↔ venv

### 1.1 Paquetes que el código USA y `requirements.txt` NO declara

| Paquete | Quién lo usa | Por qué funciona hoy | Riesgo |
|---|---|---|---|
| **`numpy`** | `incapacidad_ocr/ocr.py:99` — `import numpy as np` (import perezoso, dentro de `RapidOCRBackend.read_text`) | entra como dependencia transitiva de `rapidocr-onnxruntime` y `onnxruntime` | si alguna vez se cambia el backend de OCR, el OCR se rompe sin que nada lo avise. Es una dependencia **directa** y debe declararse. |
| **`fpdf2`** | `scripts/guia_a_pdf.py:14` — `from fpdf import FPDF` (genera `GUIA_RECEPCION_INCAPACIDADES.pdf`) | está instalado a mano en el venv (`REQUESTED` en su `dist-info`), nadie lo declaró | `pip install -r requirements.txt` en un equipo nuevo **no** lo instala → el script falla. Confirmado: es el caso que se sospechaba. |

Búsqueda completa de imports de terceros en el repo (incluidos los perezosos): `PIL`, `pypdfium2`,
`rapidocr_onnxruntime`, `httpx`, `numpy`, `fastapi`, `mysql.connector`, `apscheduler`, `fpdf`.
De esos, los dos de arriba son los únicos sin declarar. **No hay más casos.**

### 1.2 Paquetes instalados en el venv que NADIE usa

| Paquete | Estado | Nota |
|---|---|---|
| **`psutil==7.2.2`** | instalado explícitamente (`REQUESTED`), **no lo importa ningún archivo del repo** | solo aparece en `PLAN_INGESTA_MASIVA.md` §6.1 y §9.6 (watchdog de RSS por worker, Fase 4/5 no implementada). Es una dependencia **futura**, no actual → no debe entrar a `requirements.txt` hasta que exista el `ocr-worker`. |

Todo lo declarado en `requirements.txt` **sí se usa**: `Pillow` (`preprocess.py`), `pypdfium2`
(`preprocess.py:61`), `rapidocr-onnxruntime` (`ocr.py:94`), `httpx` (`ocr.py:32,137` y `extract.py:980`),
`fastapi` (`webapp.py`), `uvicorn` (`CMD` del Dockerfile, no se importa), `python-multipart`
(lo exige FastAPI para `File`/`Form`, no se importa), `mysql-connector-python` (`db.py:26`),
`apscheduler` (`webapp.py:126-127`), `tzdata` (no se importa: lo consume `zoneinfo`/`tzlocal` para
`BATCH_TZ=America/Bogota`; **es obligatorio** tanto en `python:*-slim` como en Windows, que no traen
la base IANA). **No hay declarados obsoletos.**

Detalle secundario: `Pillow` está declarado pero **no** aparece como `REQUESTED` en el venv — llegó como
transitiva de `rapidocr`/`fpdf2`. Está bien declararlo (se importa directo), pero indica que el venv no
se armó desde `requirements.txt` limpio.

### 1.3 Hallazgo grave: el venv y el contenedor Docker corren MOTORES DE OCR DISTINTOS

`rapidocr-onnxruntime` declara `requires-python = ">=3.6,<3.13"` **en todas sus versiones desde la 1.3.x
hasta la 1.4.4** (verificado en la metadata de PyPI). Solo la vieja **1.2.3** no declara `requires-python`.
Consecuencia medida, con el **mismo** `requirements.txt`:

| Destino | rapidocr que instala pip | Modelos ONNX que trae el wheel | Precisión medida (`test_ejemplos_reales.py`, 8 docs reales) |
|---|---|---|---|
| **Docker** (`python:3.12-slim`) | **1.4.4** | PP-OCR**v4** (det 4.75 MB + rec 10.86 MB) | **37/45 = 82 %** |
| **venv local** (Python 3.14.5) | **1.2.3** (2023) | PP-OCR**v3** (det 2.43 MB + rec 10.69 MB) | **34/45 = 76 %** |

Las dos filas se midieron en esta máquina, mismo código, mismos 8 documentos (la 1.4.4 se forzó en
Python 3.14 con `--ignore-requires-python` y **corre bien**). Es decir:

1. En Python ≥ 3.13 pip **degrada silenciosamente** al rapidocr de 2023 porque todo lo posterior está
   excluido por `requires-python`. No hay warning.
2. El **80 %** que citan `README.md` y `CONTEXT.md` §5.1 no corresponde a ninguna de las dos: hoy el venv
   da **76 %** y la resolución de Docker da **82 %**.
3. Qué motor de OCR acaba en producción lo decide **un accidente** de metadata de un paquete, no una
   decisión del proyecto. Con pin explícito (`rapidocr-onnxruntime==1.4.4`) son **+6 puntos porcentuales
   medidos**, gratis.

### 1.4 Deriva de versiones por no fijar (`>=` en todo `requirements.txt`)

Reejecutando la resolución hoy contra PyPI (`pip download -r requirements.txt`) sale un stack distinto al
del venv:

| Paquete | venv (funciona, 76 %) | Resolución de hoy | Salto |
|---|---|---|---|
| `opencv-python` | 4.13.0.92 | **5.0.0.93** | **major** |
| `onnxruntime` | 1.27.0 | 1.29.0 | minor |
| `numpy` | 2.4.6 | 2.5.2 | minor |
| `pypdfium2` | 5.10.1 | 5.13.0 | minor |
| `pillow` | 12.2.0 | 12.3.0 | patch |
| `protobuf` | 7.35.1 | 7.36.1 | minor |
| `packaging` | 26.2 | 26.3 | minor |
| `rapidocr-onnxruntime` | 1.2.3 | **1.2.3 en Win/3.14 · 1.4.4 en Linux/3.12** | ver §1.3 |
| `tqdm` | (no está) | **aparece** (nueva transitiva de rapidocr 1.4.x) | nueva |

Se **probó** el stack re-resuelto (venv limpio, `opencv 5.0.0.93` + `onnxruntime 1.29` + `numpy 2.5.2` +
`pypdfium2 5.13`): `tests/test_processor.py` pasa y `test_ejemplos_reales.py` da exactamente el mismo
**34/45 = 76 %**. O sea: esa deriva concreta hoy **no** rompe nada — pero eso es una constatación de un
día, no una garantía, y `opencv 4 → 5` es un cambio de major que ninguna prueba del repo vigila.

---

## 2. Inventario de componentes

### (a) Camino Docker — el recomendado

| Componente | Versión requerida | Para qué | Obligatorio | Tamaño | De dónde |
|---|---|---|---|---|---|
| **Docker Engine** (Linux) o **Docker Desktop** (Windows) | Engine **≥ 23.0** para que `docker compose` (plugin v2) venga incluido. Cualquier 20.10+ sirve si se instala el plugin aparte | runtime de contenedores | **sí** | Engine ≈ 400–500 MB [estimado, sin verificar]; Docker Desktop Windows ≈ 1,5–2 GB [estimado] | docker.com / repos de la distro |
| **Docker Compose v2** | **v2.x cualquiera** | orquesta los 3 servicios | **sí** | ≈ 60 MB [estimado] | plugin `docker-compose-plugin` |
| Imagen **`incapacidad-ocr:latest`** (se construye) | la del `Dockerfile`: base `python:3.12-slim` | la app (FastAPI + UI + OCR + batch) | **sí** | base 46 MB comprimido (**medido**); `site-packages` desempaquetado **476 MB (medido)** sobre los wheels linux/cp312; imagen final ≈ **0,8–1,1 GB en disco** [estimado, sin verificar] | `docker build` (necesita internet, ver §3) |
| Imagen **`ollama/ollama`** | el compose usa `:latest`; **hoy = v0.33.2** (release 2026-08-27, imagen empujada 2026-08-28) | servidor de inferencia local | **no** (solo si se usa IA) | **3,383 GB comprimido (medido)**; ≈ 8 GB en disco [estimado, sin verificar — incluye libs CUDA/ROCm] | Docker Hub |
| Imagen **`mysql:8`** | el tag `8` resuelve **hoy a 8.4.11-oraclelinux9** (verificado por digest) | BD de demo/staging local | **no** en producción (allí se apunta a la ASTGU real con `DB_*`) | **0,239 GB comprimido (medido)**; ≈ 0,6 GB en disco [estimado] | Docker Hub |
| Paquetes `apt` de la imagen | `libgl1`, `libglib2.0-0`, `libgomp1` (Debian bookworm) | OpenGL/GLib para `cv2`, OpenMP para `onnxruntime` | **sí** (los pide el `Dockerfile`) | sin medir (`apt-get install --print-uris`, §3.A4) | repos Debian |
| Volumen **`ollama-models`** | — | persiste los modelos | solo con IA | 3,34 GB (solo `gemma3:4b`) / **6,54 GB** (los dos) — **medido** | se llena con `ollama pull` |
| Volumen **`db-data`** | — | datadir de MySQL | solo con la BD local | sin medir (MySQL 8 crea un datadir inicial del orden de 200–300 MB) | `docker volume` |
| **`sql/init.sql`** | — | catálogos + tabla staging de demo | solo demo | 10 KB (medido) | el repo |
| Bind mount **`./ingesta`** | — | zona de ingesta masiva | sí para el flujo por lotes | ver §5 (dimensionado por volumen de documentos) | disco del host |

Notas verificadas del camino Docker:

- El `Dockerfile` copia **solo** `requirements.txt` y `incapacidad_ocr/`. `scripts/` y `tests/` quedan
  fuera (y `.dockerignore` excluye `tests/` y `*.md`). Por eso `sembrar_demo.py`,
  `migrar_estructura_ingesta.py` y `guia_a_pdf.py` **se ejecutan en el host** (así lo dice `CLAUDE.md`)
  → **el host también necesita un Python**: `migrar_estructura_ingesta.py` corre con stdlib pura
  (verificado: `import incapacidad_ocr.batch` funciona sin dependencias, los imports pesados son
  perezosos), pero `sembrar_demo.py` necesita **Pillow** y `guia_a_pdf.py` necesita **fpdf2**.
- El compose **no publica** el puerto de Ollama ni de MySQL, y publica la web solo en `127.0.0.1:8000`.
  Consecuencia de instalación: si la UI debe verse desde otro PC de la red hace falta un
  reverse-proxy + TLS + autenticación, que **no** están en el repo.
- `restart: unless-stopped` solo garantiza el arranque si el runtime de contenedores arranca en el boot:
  **Linux** `systemctl enable docker`; **Windows Server** Docker Engine/containerd como servicio de
  sistema. **Docker Desktop en Windows headless no levanta sin sesión iniciada** → hace falta el
  Programador de tareas (modo B de `PLAN_INGESTA_MASIVA.md` §5, **no implementado**). Esto sigue
  dependiendo de la precondición pendiente "SO del servidor".

### (b) Camino sin Docker

| Componente | Versión requerida | Para qué | Obligatorio | Tamaño | De dónde |
|---|---|---|---|---|---|
| **CPython x86-64** | **3.11 o 3.12 — recomendado 3.12** (es lo que usa el `Dockerfile`). 3.13/3.14 *funcionan* pero degradan el OCR a rapidocr 1.2.3, ver §1.3. Piso real: `from __future__ import annotations` + `X \| None` + `zoneinfo` ⇒ ≥ 3.9; el repo no declara nada (no hay `pyproject.toml` ni `setup.py`) | intérprete | **sí** | instalador Windows ≈ 30 MB; en disco ≈ 120 MB | python.org / distro |
| **Dependencias de `requirements.txt`** | ver el lock de §4 | todo el pipeline | **sí** | ruedas: **162 MB (linux/cp312, medido)** · **115 MB (win/cp314, medido)** · desempaquetado: **476 MB (linux, medido)** · **364 MB (venv Windows limpio, medido)** | PyPI |
| **`fpdf2`** | `==2.8.8` | `scripts/guia_a_pdf.py` | **no** (solo para regenerar la guía en PDF) | 3,3 MB + `fonttools` 22,9 MB (medido) | PyPI |
| Libs de sistema en **Linux** | `libgl1`, `libglib2.0-0`, `libgomp1` (o equivalentes) | `cv2` y `onnxruntime` | **sí en Linux** | sin medir | apt/yum |
| Libs de sistema en **Windows** | ninguna adicional: los wheels traen las DLL (`onnxruntime`, `libmysql.dll` 7 MB, `libcrypto-3-x64.dll` 7 MB, `pdfium.dll`) | — | — | incluido arriba | — |
| **MySQL / ASTGU** | MySQL **8.x** (la demo local resuelve a **8.4.11**) | tabla staging `lp_ausentismos_ia` | **sí** para registrar; sin BD la UI degrada (`db_disponible: false`) | — | el ERP del cliente |
| Servicio de arranque | Linux: unidad `systemd`. Windows: NSSM / `sc.exe` / Programador de tareas | mantener `uvicorn` vivo | **sí** en producción | — | **no está en el repo** |

Nota de instalación específica del camino sin Docker: `incapacidad_ocr/batch.py:33` fija
`INGESTA_ROOT = Path(os.environ.get("INGESTA_ROOT", "/data/ingesta"))`. En Windows nativo ese default
apunta a `C:\data\ingesta` (raíz de la unidad actual) — **hay que exportar `INGESTA_ROOT`
explícitamente**. Además, por el riesgo #19 del plan (MAX_PATH 260 con el árbol
`3_archivo/<Persona>/AAAA/MM/DD/`), en Windows hay que habilitar `LongPathsEnabled=1`
(`HKLM\SYSTEM\CurrentControlSet\Control\FileSystem`) — es un paso de instalación, no un detalle.

### (c) Opcional — IA local con Ollama

Los modelos los **fija el servidor** en `docker-compose.yml` (anti-SSRF; el cliente no los elige):
`OCR_MODEL=qwen2.5vl:3b`, `LLM_MODEL=gemma3:4b`.

| Modelo | Rol en el repo | Obligatorio | Descarga real (medida en `registry.ollama.ai`) | RAM al inferir |
|---|---|---|---|---|
| **`gemma3:4b`** | `OllamaLLMExtractor` / `HybridExtractor` — texto → JSON (`LLM_MODEL`) | **no** (sin Ollama, `HybridExtractor` degrada solo a reglas) | **3 338 801 804 B = 3,339 GB (3,11 GiB)** | ~4–5 GB según README, sin medir aquí |
| **`qwen2.5vl:3b`** | `OllamaVisionOCR` — OCR de visión (`OCR_MODEL`). Necesario para **permisos manuscritos** (`CLAUDE.md`: RapidOCR los lee muy mal) | **no**, pero sin él los permisos manuscritos quedan a revisión manual | **3 200 627 168 B = 3,201 GB (2,98 GiB)** | sin medir |

Los dos juntos = **6,54 GB** en el volumen `ollama-models`. `moondream` **no sirve** (es captioning, no
transcribe) — está documentado en el repo y confirmado en `docker-compose.yml`.

La versión mínima de Ollama que soporta `gemma3` y `qwen2.5vl` **no se midió**; se determina probando el
`pull` en el equipo con internet (§3.A2) y **fijando ese tag** en el compose. Hoy `:latest` = v0.33.2.

---

## 3. INSTALACIÓN SIN INTERNET (equipo aislado)

Esto es lo que el repo **no documenta** y es el caso real: si el runtime no sale a internet, el servidor
de producción probablemente tampoco pueda salir para instalarse.

**Regla que hay que interiorizar antes de empezar:** el `Dockerfile` hace
`RUN apt-get update && apt-get install ...` y `RUN pip install -r requirements.txt`. **Por eso NO se puede
`docker build` en el equipo aislado.** La imagen de la app hay que **construirla en el equipo con
internet** y trasladarla ya construida. (Alternativa peor: llevar también los `.deb` y un índice local de
wheels, §3.A4.)

Segunda regla: el equipo con internet debe tener el **mismo SO y arquitectura que el destino** para las
imágenes Docker (`docker save` guarda binarios de una plataforma), y para las ruedas hay que declarar
plataforma y versión de Python a mano (§3.A3).

### PARTE A — equipo CON internet ("equipo puente")

#### A1. Imágenes Docker

```bash
# 1) Fijar tags EXACTOS. Nunca :latest en un despliegue reproducible.
#    (valores medidos 2026-09-02; confirmar con el pull real)
docker pull python:3.12-slim
docker pull ollama/ollama:0.33.2
docker pull mysql:8.4.11

# 2) Construir AQUÍ la imagen de la app (aquí sí hay internet para apt + pip)
cd incapacidad-ocr
docker build -t incapacidad-ocr:1.0.0 -t incapacidad-ocr:latest .

# 3) Anotar el digest exacto de lo que se va a trasladar (para auditar el traslado)
docker images --digests | grep -E "ollama|mysql|incapacidad-ocr|python"

# 4) Exportar todo en UN tar comprimido.
#    docker save escribe capas SIN comprimir -> gzip acerca el tamaño al del registro.
docker save incapacidad-ocr:1.0.0 ollama/ollama:0.33.2 mysql:8.4.11 \
  | gzip -9 > imagenes-incapacidad-ocr-2026-09-02.tgz
```

> Tamaño esperado del `.tgz`: del orden de **4 GB** (suma de comprimidos medidos: app ~0,4 GB
> [estimado] + ollama 3,383 GB + mysql 0,239 GB). Sin gzip el tar sería del orden de **10 GB**
> [estimado, sin verificar].
> Si **no** se va a usar IA, se omite `ollama/ollama` y el traslado baja a **< 1 GB**.

#### A2. Modelos de Ollama (el volumen `ollama-models`)

```bash
# El nombre del volumen es <proyecto>_<volumen>; el proyecto por defecto es el nombre de la carpeta
# -> incapacidad-ocr_ollama-models. Se fuerza con -p para no depender del nombre de la carpeta.
cd incapacidad-ocr
docker compose -p incapacidad-ocr up -d ollama

docker compose -p incapacidad-ocr exec ollama ollama pull gemma3:4b      # 3,339 GB
docker compose -p incapacidad-ocr exec ollama ollama pull qwen2.5vl:3b   # 3,201 GB (opcional)
docker compose -p incapacidad-ocr exec ollama ollama list                # verificar nombre:tag exactos

# Empaquetar el CONTENIDO del volumen (blobs + manifests de /root/.ollama)
docker volume ls | grep ollama-models
docker run --rm \
  -v incapacidad-ocr_ollama-models:/from \
  -v "$PWD":/to alpine \
  tar czf /to/ollama-models-2026-09-02.tgz -C /from .

docker compose -p incapacidad-ocr down
```

> El `.tgz` no comprime casi nada (los GGUF ya están cuantizados): contar **~6,5 GB** con los dos
> modelos, **~3,4 GB** con solo `gemma3:4b`.
> Variante sin Docker en el puente: instalar Ollama nativo, hacer los `pull`, y copiar
> `~/.ollama/models` (Linux/macOS) o `%USERPROFILE%\.ollama\models` (Windows) — es el mismo layout
> `models/{blobs,manifests}` que va dentro del volumen.

#### A3. Ruedas de pip

Necesarias si el destino es **sin Docker**, o si además se quiere poder reinstalar dentro del contenedor.
**Hay que declarar plataforma y versión de Python del DESTINO** (`--platform` exige `--only-binary :all:`).

```bash
# DESTINO = la imagen Docker o un Linux x86-64 con Python 3.12
python -m pip download -r requirements-lock.txt -d wheels-linux-cp312 \
  --only-binary :all: --python-version 3.12 \
  --platform manylinux_2_28_x86_64 \
  --platform manylinux_2_17_x86_64 \
  --platform manylinux2014_x86_64

# DESTINO = Windows Server x86-64 con Python 3.12
python -m pip download -r requirements-lock.txt -d wheels-win-cp312 \
  --only-binary :all: --python-version 3.12 --platform win_amd64
```

**Tres trampas verificadas empíricamente en estas descargas** (no son teoría, fallaron aquí):

1. **Un solo `--platform manylinux2014_x86_64` NO alcanza** → `ERROR: ResolutionImpossible`.
   Causa medida: `onnxruntime` y `mysql-connector-python` solo publican
   `manylinux_2_28_x86_64` para cp312, mientras `shapely` solo publica `manylinux_2_17`.
   Hay que pasar **los tres** `--platform` (pip acepta el flag repetido). `manylinux_2_28` es
   compatible con `python:3.12-slim` (Debian bookworm, glibc 2.36).

2. **`pip download --platform` evalúa los *markers* de entorno con el SO del EQUIPO PUENTE, no del
   destino.** Consecuencia medida al descargar desde Windows para Linux: el bundle trajo
   **`colorama`** (marker `platform_system == "Windows"`, inútil en Linux) y **NO trajo `uvloop`**
   (`uvicorn[standard]` lo exige con marker `sys_platform != 'win32'`). Un
   `pip install --no-index` en el destino Linux **falla** por `uvloop` inexistente.
   *Arreglo:* generar el bundle en un puente con el **mismo SO** que el destino, o añadir a mano lo
   que el marker se comió:
   ```bash
   python -m pip download uvloop==0.22.1 -d wheels-linux-cp312 \
     --only-binary :all: --python-version 3.12 --platform manylinux_2_28_x86_64
   ```
   Verificar siempre el bundle antes de moverlo:
   `ls wheels-linux-cp312 | grep -E "uvloop|onnxruntime|rapidocr|opencv"`.

3. **Los modelos ONNX de RapidOCR van DENTRO del wheel** (verificado abriendo el `.whl`):
   `rapidocr_onnxruntime-1.2.3` → 12,3 MB de wheel con 13,7 MB de ONNX (PP-OCRv3);
   `rapidocr_onnxruntime-1.4.4` → 14,9 MB con 16,2 MB de ONNX (PP-OCRv4).
   El wheel es `py3-none-any` (sirve para cualquier SO). Y **no hay ninguna URL de descarga** en el
   paquete (comprobado por grep: solo enlaces de documentación en comentarios) → **no descarga nada en
   runtime**. Esa parte de la promesa offline se sostiene.

`pip` no hace falta descargarlo: `python -m venv` lo siembra con `ensurepip`, que es **offline**.

#### A4. Solo si hay que construir la imagen EN el equipo aislado (no recomendado)

```bash
# .deb de las dependencias de sistema del Dockerfile, resueltas con la MISMA base
docker run --rm python:3.12-slim sh -c \
  "apt-get update -qq && apt-get install -y --no-install-recommends --print-uris \
   libgl1 libglib2.0-0 libgomp1" | grep -o "http[^']*" > urls-deb.txt
wget -i urls-deb.txt -P debs/
# En el aislado: COPY debs/ + 'dpkg -i debs/*.deb' en vez de apt-get install,
# y 'pip install --no-index --find-links=wheels-linux-cp312' en vez de 'pip install'.
```

#### A5. Sellar el paquete

```bash
sha256sum imagenes-*.tgz ollama-models-*.tgz wheels-*/*.whl > MANIFEST.sha256
# Llevar también: el repo completo (git bundle o zip), MANIFEST.sha256 y requirements-lock.txt
git bundle create incapacidad-ocr-repo.bundle --all
```

### PARTE B — equipo AISLADO (sin salida a internet)

```bash
# B0. Verificar integridad del traslado
sha256sum -c MANIFEST.sha256

# B1. Cargar las imágenes (NO hay pull, NO hay build)
gunzip -c imagenes-incapacidad-ocr-2026-09-02.tgz | docker load
docker images        # deben aparecer incapacidad-ocr, ollama/ollama:0.33.2, mysql:8.4.11
```

```bash
# B2. Restaurar el volumen de modelos ANTES de levantar ollama
docker volume create incapacidad-ocr_ollama-models
docker run --rm \
  -v incapacidad-ocr_ollama-models:/to \
  -v "$PWD":/from alpine \
  tar xzf /from/ollama-models-2026-09-02.tgz -C /to
```

```bash
# B3. Fijar en docker-compose.yml los tags que se cargaron (si no, compose intentará PULL y fallará):
#        ollama/ollama:latest -> ollama/ollama:0.33.2
#        mysql:8              -> mysql:8.4.11
#     y para la imagen propia basta con que exista localmente el tag del campo `image:`
#     (compose NO construye si la imagen ya está y no se pasa --build).
docker tag incapacidad-ocr:1.0.0 incapacidad-ocr:latest

# B4. Levantar. NUNCA con --build (intentaría apt-get/pip y no hay red).
docker compose -p incapacidad-ocr up -d
```

```bash
# B5. Verificación offline
curl -s http://localhost:8000/api/health                      # {"status":"ok",...}
docker compose -p incapacidad-ocr exec ollama ollama list     # gemma3:4b y qwen2.5vl:3b presentes
docker compose -p incapacidad-ocr exec incapacidad-ocr \
  python -c "import rapidocr_onnxruntime as r, os, glob; \
  print(r.__version__ if hasattr(r,'__version__') else 'ok', \
  [os.path.basename(p) for p in glob.glob(os.path.dirname(r.__file__)+'/models/*.onnx')])"
docker compose -p incapacidad-ocr exec incapacidad-ocr python -m incapacidad_ocr.batch --init
docker compose -p incapacidad-ocr exec incapacidad-ocr python -m incapacidad_ocr.batch --dry-run
# Prueba dura de la promesa offline: repetir lo anterior con la NIC del servidor deshabilitada.
```

#### B6. Camino sin Docker en el equipo aislado (validado en esta máquina)

```bash
# Python del destino ya instalado (offline: instalador .exe / paquete de la distro)
python -m venv C:\srv\incapacidad-ocr\.venv          # ensurepip: no necesita internet
C:\srv\incapacidad-ocr\.venv\Scripts\python -m pip install \
    --no-index --find-links=D:\traslado\wheels-win-cp312 \
    -r requirements-lock.txt
# Si se pinea rapidocr 1.4.4 sobre Python >= 3.13, añadir --ignore-requires-python
```

**Esto se probó de verdad aquí**: venv limpio en Python 3.14.5 +
`pip install --no-index --find-links=<bundle de 115 MB> -r requirements.txt` → **37 paquetes instalados,
cero accesos a red**, y después `tests/test_processor.py` y `tests/test_ejemplos_reales.py` corrieron
completos. El procedimiento funciona.

Falta después (no lo cubre el repo): variables `DB_*`, `INGESTA_ROOT`, `BATCH_TZ`, `INGESTA_CRON`;
`LongPathsEnabled` en Windows; servicio de arranque (`systemd` / NSSM); ACL sobre `ingesta/` y cifrado
del volumen (BitLocker/LUKS, `PLAN_INGESTA_MASIVA.md` §9.4).

---

## 4. Dependencias sin pin y pin propuesto

`requirements.txt` usa `>=` en **las 9 líneas** de dependencia: `Pillow>=10`, `pypdfium2>=4`,
`rapidocr-onnxruntime>=1.2`, `httpx>=0.27`, `fastapi>=0.110`, `uvicorn[standard]>=0.27`,
`python-multipart>=0.0.18`, `mysql-connector-python>=9.0`, `apscheduler>=3.10`, `tzdata>=2024.1`.
No hay `pyproject.toml`, ni lock, ni `constraints.txt`, ni pin de las **transitivas** (que son ~30
paquetes, incluidos los binarios pesados: `onnxruntime`, `opencv-python`, `numpy`, `shapely`,
`pyclipper`, `protobuf`).

**Por qué es grave justo en un despliegue offline y reproducible:**

1. El artefacto que se traslada al equipo aislado se congela el día que se hace `pip download`. Si seis
   meses después hay que reconstruirlo (servidor nuevo, disco muerto, auditoría), sale **otro** stack.
   Medido hoy: `opencv 4.13 → 5.0` (major), `onnxruntime 1.27 → 1.29`, `numpy 2.4.6 → 2.5.2`, y aparece
   `tqdm` de la nada. Nada en el repo detecta eso.
2. **La resolución depende de la plataforma**: con el mismo `requirements.txt`, Linux/3.12 instala
   rapidocr **1.4.4** y Windows/3.14 instala **1.2.3** — motores de OCR y modelos ONNX distintos, y una
   diferencia de precisión **medida** de 76 % vs 82 % (§1.3). Sin pin, "reproducible" es falso incluso
   el mismo día.
3. `>=` sin techo también deja pasar un major roto: `rapidocr-onnxruntime>=1.2` acepta la 1.4.x, que
   cambió los modelos por defecto (PP-OCRv3 → v4); `Pillow>=10` acepta la 12.x; `mysql-connector-python>=9.0`
   acepta la 26.x. Que hoy funcionen es suerte, no diseño.
4. Sin pin no se puede **firmar el bundle**: `MANIFEST.sha256` deja de servir si `pip` puede traer otra cosa.

**Pin propuesto** — `requirements-lock.txt`. Base: las versiones que **hoy funcionan** en el venv
(76 % medido), más las tres correcciones de §1.1/§1.3. Se verificó que este conjunto **se descarga
completo para linux/cp312** (41 wheels, **162 MB**), así que sirve tanto para el contenedor como para
Windows.

```
# ---- DIRECTAS ----------------------------------------------------------
Pillow==12.2.0
pypdfium2==5.10.1
numpy==2.4.6                    # NUEVO: lo importa ocr.py:99, no estaba declarado
rapidocr-onnxruntime==1.4.4     # 1.2.3 es lo que hay hoy en el venv (76%); 1.4.4 mide 82% con
                                # los MISMOS 8 documentos. En Python >=3.13 exige
                                # --ignore-requires-python (probado, funciona).
                                # Alternativa conservadora: ==1.2.3 + Python 3.12.
httpx==0.28.1
fastapi==0.141.1
uvicorn[standard]==0.52.4
python-multipart==0.0.32        # >=0.0.18 por CVE-2024-53981 (el comentario del repo es correcto)
mysql-connector-python==26.7.0
apscheduler==3.11.3
tzdata==2026.3
fpdf2==2.8.8                    # NUEVO: scripts/guia_a_pdf.py

# ---- TRANSITIVAS (fijarlas también, o el lock no es un lock) ------------
annotated-doc==0.0.5
annotated-types==0.8.0
anyio==4.14.2
certifi==2026.7.22
click==8.5.0
defusedxml==0.7.1
flatbuffers==25.12.19
fonttools==4.64.0
h11==0.16.0
httpcore==1.0.9
httptools==0.8.0
idna==3.19
onnxruntime==1.27.0
opencv-python==4.13.0.92
packaging==26.2
protobuf==7.35.1
pyclipper==1.4.0
pydantic==2.13.5
pydantic-core==2.46.5
python-dotenv==1.2.3
PyYAML==6.0.3
shapely==2.1.2
six==1.17.0
starlette==1.6.0
tqdm==4.70.0                    # solo si se usa rapidocr 1.4.x
typing-extensions==4.16.0
typing-inspection==0.4.4
tzlocal==5.4.4
watchfiles==1.2.0
websockets==17.1
uvloop==0.22.1 ; sys_platform != "win32"   # uvicorn[standard] en Linux; se cae del bundle
                                           # si el pip download se hace desde Windows (§3.A3)
```

Además de los pines de pip, **fijar los tags de las imágenes** (mismo problema, otra capa):
`ollama/ollama:latest` → `ollama/ollama:0.33.2` y `mysql:8` → `mysql:8.4.11` (el tag `8` es móvil:
hoy resuelve a 8.4.11, hace unos meses resolvía a otra cosa). Idealmente por **digest**
(`mysql@sha256:1d6b6a8fcee8f...`, medido hoy).

Y añadir una prueba que vigile la deriva: `tests/test_ejemplos_reales.py` ya imprime la precisión —
convertirlo en un umbral que falle si baja de lo pineado (hoy 82 % con rapidocr 1.4.4).

`psutil` **no** entra al lock: no lo usa ningún archivo del repo (§1.2). Se añade cuando exista el
`ocr-worker` del plan.

---

## 5. Presupuesto de disco del servidor (con las cifras medidas)

| Concepto | Con IA (Ollama) | Solo RapidOCR |
|---|---|---|
| Docker Engine + Compose | ~0,5 GB [estimado] | ~0,5 GB [estimado] |
| Imagen `incapacidad-ocr` | ~1,0 GB [estimado; componente medido: 476 MB de `site-packages`] | ~1,0 GB |
| Imagen `ollama/ollama` | ~8 GB en disco [estimado] / 3,383 GB de descarga (**medido**) | — |
| Imagen `mysql:8.4.11` (solo si la BD es local) | ~0,6 GB [estimado] / 0,239 GB de descarga (**medido**) | ~0,6 GB |
| Volumen `ollama-models` (2 modelos) | **6,54 GB (medido)** | — |
| Volumen `db-data` | ~0,3 GB [sin medir] | ~0,3 GB |
| **Subtotal software** | **~17 GB** | **~2,4 GB** |
| Paquete de traslado offline (se puede borrar después) | ~10,5 GB | ~1 GB |
| Documentos en `ingesta/` | **~3,8 GB/mes** — calculado: 348 KB/archivo (media **medida** sobre los 8 documentos reales de `../Ejemplos`, 2 784 KB / 8) × ~11 000 archivos/mes (7 000 casos × ~1,6 archivos por caso). n=8, es una media pobre: **medir con un mes real antes de comprar disco.** | igual |

Los ~13 GB que cita el README quedan cortos: no cuentan `mysql:8`, ni el volumen `db-data`, ni el
paquete de traslado, ni los documentos.

---

## 6. Errores en la documentación del repo (lo que dice y ya no es cierto)

1. **`README.md` §Pruebas — "Resultado actual: 80% de los campos núcleo"**, y `CONTEXT.md` §5.1 igual.
   Medido hoy con el venv del repo: **34/45 = 76 %**. Con el stack que arma Docker
   (rapidocr 1.4.4): **37/45 = 82 %**. La cifra publicada no corresponde a ninguna de las dos
   configuraciones reales.
2. **`README.md` §Requisitos — "Sin Docker (local): Python 3.11–3.14"**. Técnicamente instala en 3.13/3.14,
   pero **omite que en ≥3.13 pip degrada `rapidocr-onnxruntime` a la 1.2.3 de 2023** (por
   `requires-python <3.13`) y con ello el pipeline pierde ~6 puntos de precisión. La recomendación
   correcta es **3.12** (que es además lo que usa el `Dockerfile`).
3. **`README.md` — "la construcción descarga ~1 GB (imagen web) y la imagen de Ollama ~8 GB"**. Confunde
   descarga con disco: la **descarga** real de `ollama/ollama` medida en Docker Hub es
   **3,383 GB comprimidos**; los ~8 GB son el tamaño **en disco** descomprimido.
4. **`README.md` §Requisitos mínimos — "Disco ~13 GB"** no incluye `mysql:8` (0,239 GB de descarga /
   ~0,6 GB en disco), que **sí** está en el `docker-compose.yml` y arranca por defecto, ni el volumen
   `db-data`, ni los documentos de `ingesta/`.
5. **`README.md` — "gemma3:4b (~3.3 GB)" y "qwen2.5vl:3b (~3.2 GB)"**: son **correctos** (medidos:
   3,339 GB y 3,201 GB). Se confirman, no se corrigen.
6. **`README.md`/`CLAUDE.md`/`CONTEXT.md` no mencionan `fpdf2` ni `numpy`** como requisitos, aunque
   `scripts/guia_a_pdf.py` y `incapacidad_ocr/ocr.py` los importan (§1.1). Un `pip install -r
   requirements.txt` en un equipo nuevo deja `guia_a_pdf.py` roto.
7. **`CONTEXT.md` §9 "Pendiente (producción): ... fijar versiones (pin) de dependencias"** — sigue
   pendiente y hoy es el mayor riesgo de reproducibilidad del despliegue offline (§4). No es un
   "nice to have": determina qué motor de OCR acaba en producción.
8. **`CONTEXT.md` línea 58 — "venv con RapidOCR (onnxruntime 1.27 + opencv 4.13, wheels cp314 OK)"** es
   exacto para el venv, pero **describe un entorno distinto al del contenedor** (`python:3.12-slim`
   → onnxruntime 1.29 y opencv 5.0 si se reconstruye hoy, y rapidocr 1.4.4). En ninguna parte se
   advierte esa divergencia dev/prod.
9. **Ni el README ni `CLAUDE.md` documentan la instalación sin internet**, que es el escenario real del
   cliente. En particular no dicen que **`docker build` es imposible en el equipo aislado** (el
   `Dockerfile` hace `apt-get update` + `pip install`). Todo el §3 de este informe es hueco nuevo.
10. **`requirements.txt` línea 7 — "Ollama: NO requiere paquete pip; se instala aparte (ollama.com)"**:
    cierto para el camino sin Docker, pero el compose ya trae el contenedor `ollama/ollama` — el
    comentario induce a instalar Ollama nativo además del contenedor.
11. Los límites que cita el README (`MAX_UPLOAD_BYTES` 50 MB, `MAX_PDF_PAGES` 30, `OCR_MAX_PIXELS` 40 MP,
    `MAX_IMAGE_PIXELS` 200 MP, `PDF_RENDER_SCALE` 3.0, `MIN_OCR_CHARS`) **se verificaron uno por uno
    contra el código** (`webapp.py:32`, `preprocess.py:23-33`, `processor.py:13`): **todos correctos**.
12. `PLAN_INGESTA_MASIVA.md` §9.3 fija `INGESTA_CRON` con default `0 2 * * *`, pero el código
    (`webapp.py:49`) usa **default vacío = desactivado** (y el compose pasa `${INGESTA_CRON:-}`).
    El README describe bien el comportamiento real; **el plan es el que está desactualizado**.
13. Los números de sección que se suelen citar del plan están corridos: el **dimensionamiento** está en
    **§6.6** (no §10) y los **riesgos** en **§11** (no §9); §9 es "Robustez, errores, configuración,
    seguridad/PII, observabilidad" y §10 es el plan por fases.

---

## 7. Lo que sigue sin resolver y bloquea la compra

- **SO del servidor (precondición P2)**: sigue **pendiente**. Afecta el arranque programado
  (`PLAN_INGESTA_MASIVA.md` §5): en Windows headless con **Docker Desktop** el contenedor no levanta
  sin sesión iniciada y hace falta el modo B (Programador de tareas), **que no está implementado**.
  Con **Docker Engine/containerd como servicio** en Windows Server, o con Linux + `systemctl enable
  docker`, funciona el APScheduler in-process que ya existe. Ambos caminos quedan documentados arriba;
  la decisión hay que tomarla y validarla con un **reinicio en frío sin login**.
- **RAM/CPU para 7000 casos/mes**: la tabla de `PLAN_INGESTA_MASIVA.md` §6.6 (~1,5–2 docs/s con 6
  workers) es del propio plan y **no está medida**; el plan lo admite ("referencia, no compromiso").
  Este informe no la respalda: hoy el runner es **single-worker in-process** en el contenedor web,
  no el pool de la Fase 2. Medirlo = correr `python -m incapacidad_ocr.batch` sobre 100 documentos
  representativos y cronometrar.
- **Tamaño del volumen de MySQL** y **tamaño en disco de las imágenes**: requieren Docker corriendo.
- **Versión mínima de Ollama** para `gemma3:4b` / `qwen2.5vl:3b`: se determina en el equipo puente.
