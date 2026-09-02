# 04 · Host y sistema operativo — cerrar la precondición «P2» (Windows Server vs Linux)

**Fecha:** 2026-09-02 · **Decisión que cierra:** el SO del servidor de producción, que
`PLAN_INGESTA_MASIVA.md` §5 dejó como *«Pendiente de definir en despliegue»* y `CONTEXT.md` §7 sigue
listando como pendiente.
**Documentos hermanos:** [`01_software.md`](01_software.md) (inventario, instalación offline, pines) ·
[`02_benchmark.md`](02_benchmark.md) (coste por documento medido).

Todas las cifras de este informe son (a) una **medición hecha hoy en esta máquina**, (b) un dato de un
**archivo del repo**, o (c) un **cálculo explícito** a partir de (a)/(b). Donde no hay base, dice
**«sin medir»** y explica cómo medirlo. Docker y Ollama **no corren en esta máquina** (Docker Desktop
exige elevación UAC que la sesión no tiene), así que todo lo relativo a contenedores está deducido del
`Dockerfile`/`docker-compose.yml` y marcado **[estimado, sin verificar aquí]**.

---

## 0. Cómo se midió y qué NO se pudo medir

**Máquina de medición** (la misma de `02_benchmark.md` §2): HP ProBook 440 G9, i7-1255U, 32 GB,
**Windows 11 Pro 10.0.26200**, disco del sistema NTFS, Python 3.14.5 del venv del repo.

Estado del host, leído hoy (relevante porque son justo las palancas que discute este informe):

| Qué | Valor leído | Cómo |
|---|---|---|
| `LongPathsEnabled` | **1 (ya activado)** | `(Get-ItemProperty 'HKLM:\SYSTEM\CurrentControlSet\Control\FileSystem').LongPathsEnabled` |
| Zona horaria del host | **SA Pacific Standard Time (UTC−05:00) — Bogotá** | `Get-TimeZone` |
| Defender | `AMServiceEnabled=True` · **`RealTimeProtectionEnabled=True`** · `BehaviorMonitor=True` · `IoavProtection=True` · `OnAccessProtection=True` | `Get-MpComputerStatus` |
| Exclusiones de Defender | **no legibles** (`Get-MpPreference` exige administrador) | — |

**Sí se midió** (en NTFS, con Defender en tiempo real ACTIVO, sobre el corpus real
`ingesta/_sistema/semilla/`: 32 archivos, 11 741 KB, media **367 KB/archivo**):

1. Coste de la **primera lectura** de un archivo recién escrito vs. lecturas siguientes (sha256 completo).
2. Coste de `shutil.move` a un destino anidado en el mismo volumen.
3. Frecuencia de `WinError 32` en el patrón «escribir → renombrar de inmediato» (300 intentos).
4. Coste del **escaneo recursivo** de `1_entrada/` con **11 000 archivos** (el volumen de un mes).
5. Coste de **crear** y de **borrar** esos 11 000 archivos (base para el tiempo de restauración).
6. Longitud real de las rutas que produce `batch.py`, llamando a sus propias funciones
   (`_sanit_carpeta`, `_carpeta_persona`, `_partes_destino`).
7. Comportamiento de rutas de 250/259/270/300 caracteres frente a `cmd.exe` y PowerShell 5.1.

**NO se pudo medir** (y por eso no hay ninguna cifra inventada sobre ello):

- **El sobrecoste del bind mount de Docker Desktop (gRPC-FUSE/VirtioFS)**: Docker no corre aquí. Lo que
  sí se hace es **acotar el problema**: se mide el coste nativo en NTFS y se calcula *a partir de qué
  factor de penalización empieza a doler* (§3.2). El factor en sí queda **sin medir**.
- **Linux**: no hay Linux en esta máquina. Ninguna cifra de este informe es una medición en Linux.
- **El hardware del servidor real**: desconocido (`02_benchmark.md` §11.4).
- **Licenciamiento y soporte de producto** (Docker Desktop, Mirantis, Windows Server): son condiciones
  contractuales del fabricante, no medibles aquí y **sin internet en esta sesión**. Van marcadas
  **[confirmar con el proveedor antes de firmar]**. Son el único punto de este informe que no se puede
  cerrar desde el repo, y es un punto que cambia la decisión, así que está señalado en §8.

---

## 1. La recomendación, en una línea

> **Linux x86-64 (Ubuntu Server LTS o RHEL-family), con Docker Engine habilitado como servicio del
> sistema** — *salvo* que la política de TI del cliente prohíba un host que no sea Windows o no tenga
> quién administre Linux; **en ese caso: Windows Server como HIPERVISOR (rol Hyper-V) con una VM Linux
> de autoarranque que corre el stack**, nunca Docker Desktop sobre Windows Server, y nunca el «modo B»
> del plan §5 tal como está escrito hoy.

**El argumento no es de preferencia, es de compatibilidad:** los **tres** servicios del
`docker-compose.yml` son contenedores **Linux** (`python:3.12-slim` en el `Dockerfile`, `mysql:8` →
8.4.11-oraclelinux9 y `ollama/ollama`, ambos verificados por digest en `01_software.md` §2a). Un host
Windows Server **no ejecuta contenedores Linux de forma nativa**: necesita WSL2 o una VM Linux por
debajo. Es decir, **la opción «Windows Server» real es «Windows Server + Linux por debajo»**, con dos
capas más que mantener para obtener exactamente el mismo runtime.

Ver §3.1 y §7 para el detalle de por qué la tabla del plan §5 («Windows Server con Docker
Engine/containerd como servicio → **camino preferido en Windows**») describe una configuración que,
para *este* stack, no existe.

---

## 2. El hecho que decide: el runtime ya es Linux

| Servicio del compose | Imagen | Plataforma |
|---|---|---|
| `incapacidad-ocr` | se construye del `Dockerfile`: `FROM python:3.12-slim` (Debian bookworm) + `apt-get install libgl1 libglib2.0-0 libgomp1` | **linux/amd64** |
| `db` | `mysql:8` (= 8.4.11-oraclelinux9, `01_software.md` §2a) | **linux/amd64** |
| `ollama` | `ollama/ollama:latest` (= v0.33.2, `01_software.md` §2a) | **linux/amd64** |

Consecuencias que no son opinables:

1. **No hay versión Windows de estas imágenes.** `python:3.12-slim` es Debian; no existe un `mysql`
   oficial en contenedor Windows. Reconstruir el stack para contenedores Windows significaría reescribir
   el `Dockerfile`, cambiar de base de datos y perder toda la evidencia de `01_software.md` y
   `02_benchmark.md`. No es una opción realista.
2. **Los runtimes de contenedores «nativos» de Windows Server** (Docker Engine transferido a Mirantis en
   2019 → *Mirantis Container Runtime*, o `containerd` con `hcsshim`) ejecutan **contenedores Windows**.
   *Linux Containers on Windows* (LCOW) fue experimental y quedó descontinuado. **[confirmar con el
   proveedor]** — pero es exactamente la premisa que la fila «camino preferido en Windows» del plan §5
   da por cierta sin verificarla.
3. **Docker Desktop** sí ejecuta contenedores Linux en Windows (vía WSL2), pero (a) **su plataforma
   soportada es Windows 10/11, no Windows Server**, y (b) **su motor lo arranca la aplicación de la
   sesión del usuario**, lo que choca de frente con el requisito «arrancar tras un reboot sin login».
   **[confirmar con el proveedor]**.
4. Por tanto, en Windows Server las únicas configuraciones que ejecutan **este** stack son:
   **(W1)** VM Linux sobre Hyper-V con Docker Engine dentro; **(W2)** WSL2 + Docker Engine dentro de la
   distro, arrancado por una tarea programada; **(W3)** abandonar Docker y correr la app **nativa** en
   Windows (`uvicorn` + venv), que es el camino «sin Docker» de `01_software.md` §2b.

Las tres se evalúan en la matriz. **W1 es la única que no tiene un «pero» estructural.**

---

## 3. Matriz de decisión, criterio por criterio

### 3.1 Arranque sin login y tras reboot — **el criterio que decide**

**Evidencia del repo:** el compose pone `restart: unless-stopped` en los tres servicios
(`docker-compose.yml` líneas 49, 63, 81). Eso **solo** garantiza el arranque si el *runtime* arranca en
el boot (`01_software.md` §2a lo dice igual). La corrida programada es **in-process**: APScheduler
`BackgroundScheduler` dentro del contenedor web (`webapp.py:150-163`), activado solo si `INGESTA_CRON`
no está vacío. Si el contenedor no está vivo, **no hay cron**.

| Configuración | ¿Arranca sin sesión iniciada? | Cómo |
|---|---|---|
| **Linux** | **Sí** | `systemctl enable --now docker` + `restart: unless-stopped`. Nada más. |
| **W1** Windows Server + VM Linux (Hyper-V) | **Sí** | VM con *Automatic Start Action = Always start*, delay 0; dentro, igual que Linux. |
| **W2** Windows Server + WSL2 | **Frágil** | WSL es *por usuario*; sin sesión hay que forzarlo con una tarea programada al arranque («ejecutar aunque el usuario no haya iniciado sesión») que haga `wsl -d <distro> -u root -- service docker start`, más `systemd=true` en `/etc/wsl.conf`. Funciona, pero no es una configuración soportada ni probada en este proyecto. |
| **W3** Windows Server nativo sin Docker | **Sí** | `uvicorn` como servicio con NSSM/`sc.exe`. **No hay artefacto en el repo** (verificado: no existe ninguna unidad systemd, `.xml` de tarea programada ni script NSSM en el repositorio). |
| Windows + **Docker Desktop** | **No** | El motor lo levanta la app de escritorio en la sesión del usuario. |

**Corrección al plan §5 (importante, es un agujero lógico, no un matiz):** el «modo B» que el plan
propone para *Windows headless solo con Docker Desktop* es

> «(a) *At startup* → `docker compose up -d`; (b) *diario* → `docker compose exec -T ocr-worker python -m incapacidad_ocr.batch run --once`»

y **eso no puede funcionar sobre Docker Desktop**: ambos comandos son clientes que necesitan un
**daemon ya en marcha**, y el daemon de Docker Desktop no existe hasta que un usuario inicia sesión y
arranca la aplicación. La tarea programada como `SYSTEM` fallaría con «cannot connect to the Docker
daemon». El modo B **solo tiene sentido si ya existe un motor en modo servicio** — y si existe, el
APScheduler in-process ya funciona y el modo B es innecesario. Dicho de otro modo: **el modo B no
resuelve el problema que el plan le asigna**, y sigue **sin implementar** (`CONTEXT.md` §7).

**Validación obligatoria, cualquiera sea el SO** (el plan §5 ya la pide y sigue sin hacerse):
**reinicio en frío sin login** → esperar el `INGESTA_CRON` → comprobar `GET /api/lote/estado` y que el
lote corrió. Es la única prueba que cierra este criterio.

### 3.2 Bind mount `./ingesta:/data/ingesta` y movimientos de archivo — **medido y acotado**

`docker-compose.yml:45` monta `./ingesta:/data/ingesta`. El runner lee cada documento y al final **mueve**
los archivos (`batch._mover` → `shutil.move`).

**Medido hoy, NTFS nativo, Defender en tiempo real activo:**

| Operación | p50 | máx | n |
|---|---|---|---|
| `shutil.move` al destino anidado, mismo volumen | **0.51 ms** | 25.85 ms | 32 |
| escribir 300 KB + `os.replace` inmediato | 0.75 ms | 2.25 ms | 300 |
| sha256 completo — **primera** lectura tras escribir | **45.19 ms/archivo** (8.3 MB/s) | — | 32 |
| sha256 completo — lecturas siguientes (caliente) | **1.28 ms/archivo** (293 MB/s) | — | 32×4 |
| escaneo recursivo de `1_entrada` con **11 000** archivos en 30 subcarpetas (`rglob` + `sorted` + `is_file` + sufijo, tal como `batch._archivos_entrada`) | **1.405 s** (127.7 µs/archivo) | 1.421 s | 4 pasadas |

**Cálculo 1 — el bind mount es irrelevante para el throughput.** El trabajo de sistema de archivos por
documento es ≈ una lectura completa + un rename = **45.7 ms medidos nativos**. El OCR del mismo documento
cuesta **9.92 CPU-s** (`02_benchmark.md` §9, media medida sobre 35 documentos reales). Es decir el FS es
el **0.46 %** del coste. Incluso con una penalización de **×10** del bind mount seguiría siendo **4.6 %**.
→ **Este criterio no debe pesar en la decisión de SO por rendimiento.** (El factor real de penalización
sigue **sin medir**; lo que se afirma es que hace falta un factor absurdo para que importe.)

**Cálculo 2 — donde sí puede doler: el escaneo, si se implementa el poll de la Fase 2.** El plan §5.2
propone `BATCH_POLL_SECONDS=30`. Con 11 000 archivos en la entrada, el escaneo nativo cuesta **1.405 s**;
supera los 30 s del poll a partir de un factor de penalización de **≈21×**:

| Penalización del bind mount | Escaneo de 11 000 archivos |
|---|---|
| ×1 (nativo, medido) | 1.4 s |
| ×5 | 7.0 s |
| ×10 | 14.0 s |
| **×20** | **28.1 s ← límite del poll de 30 s** |
| ×50 | 70.2 s |

Mitigación válida en cualquier SO y gratis: **la entrada se vacía en cada corrida** (los archivos se
mueven a `2_revisar/`/`3_archivo/`), así que 11 000 archivos simultáneos en `1_entrada/` es el caso
patológico de un backlog, no la operación normal. Si aparece, se sube `BATCH_POLL_SECONDS`.
→ **Ventaja de Linux: real pero pequeña, y acotada por cálculo.**

**Corrección al plan §9.2 («reintentos con backoff ante `WinError 32` (Defender/indexador)»):** se
intentó reproducir el fallo — **300 ciclos de «escribir 300 KB + `os.replace` inmediato» con Defender en
tiempo real activo: 0 fallos**, p50 0.75 ms, máx 2.25 ms. El `WinError 32` es real como clase de fallo,
pero **no es un coste medible en el caso normal**; el reintento con backoff se mantiene como seguro
barato, no como compensación de un problema medido. Lo que **sí** se midió del antivirus es otra cosa
(§3.5).

**Asimetría real y no medida (favorece Linux):** el runner escribe en el bind mount como usuario
**no-root** (`Dockerfile:25-26`, `useradd --create-home app` → uid/gid **1000** en Debian
[estimado; verificar con `docker compose exec incapacidad-ocr id`]). En **Linux** el bind mount preserva
uid/gid: si `ingesta/` del host no es escribible por uid 1000, **el move falla**. En **Docker Desktop
Windows** la traducción de permisos lo permite siempre (`CLAUDE.md` §Gotchas ya lo dice). Ese fallo tiene
una consecuencia grave que se explica en §5.7 y que hay que atajar en el checklist con un `chown`.

### 3.3 MAX_PATH 260 en Windows — **calculado; con el árbol nuevo ya NO es un riesgo**

El plan §4.1 dice que «el árbol destino se acorta agresivamente» por MAX_PATH y el riesgo #19 lo lista
como riesgo vivo. **Con el árbol actual (`1_entrada`/`2_revisar`/`3_archivo`) eso ya está resuelto con
holgura.** Peor caso, calculado llamando a las funciones reales de `batch.py`:

**(a) La carpeta de persona está acotada por código.** `batch._sanit_carpeta` termina en `return s[:60]`
— verificado: una entrada de 72 caracteres sale con **60**. Peor caso realista de 60 chars = nombre
**pegado por el OCR** sin cédula resuelta en catálogo. Con el nombre canónico del catálogo,
`primer_nombre_apellido` devuelve **dos tokens** (`ALEJANDRO ISAAC LINARES RICARDO` → `ALEJANDRO
LINARES`, **17 chars** medidos); el respaldo sin nombre es `SIN NOMBRE <cedula>` = **21 chars**.

**(b) Ruta relativa más larga del árbol** (medida con `_partes_destino`, persona = 60 chars):

| Zona | Ruta relativa | Chars |
|---|---|---|
| `3_archivo\<Persona>\AAAA\MM\DD` | `3_archivo\XXXX…XXXX\2026\09\02` | **81** |
| `2_revisar\faltan_soportes\<Persona>\AAAA\MM\DD` | — | **97** |
| **`2_revisar\datos_por_revisar\<Persona>\AAAA\MM\DD`** | — | **99 ← la más larga** |

**(c) Nombre de archivo** (`{cedula}_{TIPODOC}[_NN].ext`, más `_dupNN` si `_destino_libre` desambigua):

| Caso | Ejemplo | Chars |
|---|---|---|
| Típico | `REAL-03.pdf` | 26 |
| Peor del vocabulario real (cédula 10 + `REGISTROCIVIL` + `_NN`) | `CED-03_REGISTROCIVIL_02.jpeg` | 32 |
| …+ colisión | `CED-03_REGISTROCIVIL_02_dup99.jpeg` | **38** |
| Peor que **admite el regex** `\d{5,15}` + `\d{1,3}` (`batch._RE_NOMBRE`) | `123456789012345_REGISTROCIVIL_999_dup99.jpeg` | **44** |

**(d) Presupuesto.** El árbol consume, en el peor caso absoluto, `99 + 1 + 44 = ` **144 caracteres**.
MAX_PATH deja **259** utilizables (260 incluye el NUL) y **248** para *crear directorios* (`MAX_PATH−12`).
Por tanto:

```
INGESTA_ROOT (ruta del host) ≤ 259 − 144 = 115 caracteres   (para el archivo)
INGESTA_ROOT (ruta del host) ≤ 248 − 100 = 148 caracteres   (para crear el directorio)
→ límite práctico: INGESTA_ROOT ≤ 115 caracteres
```

Comprobado contra rutas concretas:

| `INGESTA_ROOT` del host | len | dir máx | + nombre típico | + peor real | + peor del regex |
|---|---|---|---|---|---|
| `<repo>\ingesta` (esta máquina) | 48 | 148 | 175 | 187 | **193** |
| `C:\Users\Administrador\Documents\incapacidad-ocr\ingesta` | 56 | 156 | 183 | 195 | **201** |
| `C:\ProgramData\incapacidad-ocr\ingesta` | 38 | 138 | 165 | 177 | **183** |
| `D:\incapacidad-ocr\ingesta` | 26 | 126 | 153 | 165 | **171** |
| `D:\ingesta` | 10 | 110 | 137 | 149 | **155** |

**Conclusión: sobran ≥ 66 caracteres en todos los casos plausibles.** El riesgo #19 del plan baja de
«riesgo» a **«una verificación de instalación de una línea»**: `len(INGESTA_ROOT) ≤ 115`. Y la decisión
de 2026-09-01 de **conservar el nombre original con cédula** en vez del renombrado corto `NN_<tipo>`
(plan §4.4) **no compromete MAX_PATH**: el nombre largo son 38 chars contra los 6-10 del corto, y hay 66
de holgura.

**Matiz que sí hay que dejar dicho:** el `os.replace`/`mkdir` los ejecuta el contenedor **Linux**, donde
el límite es 4096 — así que Windows **no impediría** crear una ruta larga; el que se rompería es el
*host* (Explorer, copia de seguridad, antivirus). Medido hoy con `LongPathsEnabled=1`: rutas de **250,
259, 270 y 300** caracteres se crearon desde Python y `cmd.exe /c dir` y PowerShell 5.1 las leyeron
**todas sin error**. Es decir, `LongPathsEnabled=1` funciona como red de seguridad en Windows moderno
(su comportamiento con `LongPathsEnabled=0`, y con las herramientas de backup del cliente, queda **sin
medir** — no se puede desactivar la clave sin administrador).
→ **Este criterio queda empatado**: no penaliza a Windows con el árbol actual.

### 3.4 Cifrado del volumen y ACL (Ley 1581)

Lo que hay que proteger y **dónde vive** (del compose):

| Dato | Dónde | Contiene PII |
|---|---|---|
| Documentos originales (`ingesta/`) | bind mount, disco del host | **sí** — datos de salud; y `LEEME.md` advierte que el **nombre de archivo lleva la cédula** y la **carpeta el nombre de la persona** (decisión 2026-09-01) |
| `db-data` | volumen Docker | **sí, si se usa la BD local**; en producción `DB_*` apunta a ASTGU y este volumen no guarda nada de valor |
| `ollama-models` | volumen Docker | no (pesos de modelo) |
| Logs (`_sistema/logs/`) | bind mount | el plan §9.4 exige redacción; **la Fase 2 no está implementada** |

**Cifrado en reposo — el punto que hay que decirle al cliente sin adornos:** BitLocker y LUKS resuelven
**el mismo** problema (disco robado, servidor dado de baja, disco enviado a garantía) y **ninguno de los
dos** protege un servidor encendido. Y ambos tienen **el mismo conflicto con «reinicio automático sin
login»**:

| | BitLocker (Windows) | LUKS (Linux) |
|---|---|---|
| Desbloqueo desatendido | TPM-only → automático en el boot | `systemd-cryptenroll --tpm2-device=auto` → automático |
| Con PIN/passphrase pre-boot | **rompe el reboot desatendido** (pide humano en consola) | idem |
| Sin TPM / VM sin vTPM | pide clave de recuperación en cada arranque | pide passphrase en cada arranque |
| Volumen de datos secundario (`D:` / `/datos`) | necesita *auto-unlock*, que exige que el volumen del SO también esté cifrado | keyfile en el root cifrado, o segundo enroll TPM2 |
| En W1 (VM Linux sobre Hyper-V) | el VHDX queda cubierto por el BitLocker del host — **basta uno de los dos**, no hace falta cifrar dos veces | — |

→ **Empate técnico.** El criterio no decide el SO; lo que decide es **exigir TPM (o vTPM) en el
servidor** para tener cifrado *y* reboot desatendido a la vez. Si el servidor es una VM sin vTPM, hay que
elegir entre las dos cosas — y eso hay que saberlo **antes de comprar**.

**ACL — sí hay una asimetría, y en los dos sentidos:**

- **Linux:** `ingesta/` propiedad del usuario de servicio con **uid/gid 1000** (el del contenedor),
  modo **0750**. Los volúmenes Docker viven bajo `/var/lib/docker/volumes` (root, 0700). Limpio y
  auditable, pero **el permiso *tiene* que estar bien o el runner no puede mover archivos** (§3.2, §5.7).
- **Windows:** ACL NTFS sobre `INGESTA_ROOT`: quitar `Usuarios`/`Usuarios autenticados`, dejar solo la
  cuenta de servicio + `Administradores`. Con Docker Desktop el contenedor **ignora** los permisos POSIX,
  así que la ACL del host es **la única** barrera — más simple de operar y más fácil de dejar abierta por
  descuido.
- **Simétrico y grave en ambos:** pertenecer al grupo `docker` (Linux) o `docker-users` (Windows) es
  equivalente a root en el host — cualquiera de ese grupo puede montar el disco entero dentro de un
  contenedor y leer toda la PII. La lista de miembros de ese grupo **es** un control de Ley 1581, y hay
  que auditarla. No está documentado en el repo.

### 3.5 Antivirus: qué excluir y **por qué** (medido)

**Medido hoy** (Defender en tiempo real ACTIVO, ver §0):

| | 1.ª lectura tras escribir | Lecturas siguientes | Factor |
|---|---|---|---|
| Documentos reales (PDF/JPEG, media 367 KB, n=32) | **45.19 ms/archivo** (8.3 MB/s) | 1.28 ms (293 MB/s) | **×35.2** |
| Control: bytes aleatorios `.dat` del mismo tamaño (n=32) | 27.17 ms/archivo (13.8 MB/s) | 2.1–3.2 ms | ×11 |

El patrón (penalización enorme solo en la **primera** lectura, y **mayor en formatos de documento** que
en bytes aleatorios) es el del **escaneo on-access**. No se puede *demostrar* la causalidad sin apagar
Defender, y eso exige administrador → **queda como «consistente con el escaneo on-access», no como
causa probada**.

**Extrapolación al volumen del cliente** (11 000 archivos/mes, `01_software.md` §5):

```
11 000 × 45.19 ms  =  497 s  =  8.3 min/mes     (con escaneo on-access en la 1.ª lectura)
11 000 ×  1.28 ms  =   14 s                     (sin él)
frente al OCR:      7000 × 9.92 CPU-s = 19.3 CPU-horas/mes  (02_benchmark.md §9)
→ el antivirus es el 1.2 % del coste de CPU del proceso
```

**Por tanto la exclusión de antivirus NO se pide por rendimiento.** Se pide por dos razones concretas:

1. **Cuarentena = destrucción de un soporte legal.** Un PDF de una EPS con JavaScript embebido o una
   heurística que se dispare hace que Defender **mueva o borre** el archivo de `1_entrada/`. Ese archivo
   es, en ese momento, **la única copia del original** — y el plan §9.4 y el riesgo #16 prohíben
   explícitamente perderla. El caso quedaría registrado en staging con un soporte que ya no existe, y
   nadie se enteraría (`batch._mover` traga las excepciones: `log.exception` y sigue).
2. **Bloqueos de archivo (`WinError 32`)** durante el rename. No se reprodujo en 300 intentos (§3.2),
   pero el fallo existe y la exclusión lo elimina de raíz.

**Qué excluir exactamente** (Windows):

- `INGESTA_ROOT` completo (**escaneo en tiempo real**) — es el árbol que el runner escribe y renombra.
- El directorio de datos de Docker Desktop / el `ext4.vhdx` de WSL2 (`%LOCALAPPDATA%\Docker`), causa
  conocida de degradación con Defender **[sin medir aquí]**.
- Si se elige W3 (nativo, sin Docker): además el venv y el directorio de trabajo de `uvicorn`.

**Y el contrapeso, que hay que escribir en el runbook:** excluir `INGESTA_ROOT` significa que archivos
que llegan **de WhatsApp y de correo** aterrizan en una carpeta **no escaneada**. `CONTEXT.md` §9 ya lo
tiene como pendiente de producción («antivirus/validación de contenido de los archivos si la fuente no
es de confianza»). La combinación correcta es: **exclusión de tiempo real + escaneo programado diario de
esa misma ruta configurado para ALERTAR, no para borrar**, y la alerta la revisa una persona. Nunca
dejar que el antivirus sea el que decide borrar un soporte.

En Linux normalmente **no hay antivirus on-access**, así que este bloque desaparece; si el cliente exige
uno (ClamAV/`fanotify`), aplican las mismas dos reglas.
→ **Ventaja de Linux: menos superficie operativa; el coste medido es despreciable en ambos.**

### 3.6 Licenciamiento y coste

| Componente | Linux | Windows Server |
|---|---|---|
| SO | **0** (Ubuntu Server LTS / Debian / Rocky). Soporte pagado opcional (Ubuntu Pro, RHEL) | licencia **por núcleo** (paquete mínimo de 16) + CAL si aplica. **Precio: pregunta abierta**, depende del acuerdo del cliente |
| Runtime de contenedores | **Docker Engine CE = 0** (Apache-2.0) | **W1/W2**: Docker Engine CE dentro de Linux = **0**. **Docker Desktop**: suscripción de pago para empresas > 250 empleados o > USD 10 M de ingresos **[confirmar]** — y además Windows Server no es plataforma soportada. **MCR (Mirantis)**: pago, y ejecuta contenedores *Windows* → no sirve (§2) |
| Hipervisor | — | Hyper-V incluido en la licencia de Windows Server; el invitado Linux no consume licencia Windows **[confirmar]** |
| MySQL | ya lo tiene el cliente (ASTGU). El `db` del compose es solo demo | idem |
| Ollama / modelos | 0 (pesos abiertos; 6.54 GB medidos, `01_software.md` §2c) | idem |

**Lo que el cliente ya tiene: no lo sé, y es una pregunta abierta que hay que hacerle** (§8). Es
determinante: si Gruppo ya tiene licencias de Windows Server ociosas y **cero** administración Linux, el
coste de licencia puede ser 0 y el coste de personal el que manda. Si no tiene ninguna de las dos cosas,
Linux es estrictamente más barato.

**El único gasto que este análisis puede afirmar que Windows *añade* sin dar nada a cambio:** el trabajo
de instalar y mantener **la capa extra** (Hyper-V + VM, o WSL2 + tarea programada) para llegar al mismo
runtime Linux.

### 3.7 Copias de seguridad y restauración

**Lo primero, para no gastar dinero en el sitio equivocado:** en producción `DB_*` apunta a la **BD ASTGU
del cliente** (`docker-compose.yml:30-34` con default `db`), así que el volumen **`db-data` no contiene
nada irremplazable** — su respaldo es responsabilidad del DBA del ERP. `ollama-models` se reconstruye con
un `ollama pull` (o desde el `.tgz` del traslado, `01_software.md` §3.A2). **El único dato irremplazable
que vive en este servidor es el árbol `ingesta/`**: los originales de los soportes, con periodo legal de
conservación (plan §9.4, riesgo #16).

**Volumen a respaldar** (calculado): media **367 KB/archivo** (medido hoy, n=32, corpus real de la
semilla — coincide con los 348 KB medidos sobre `../Ejemplos` en `01_software.md` §5) × ~11 000
archivos/mes = **≈3.9 GB/mes ≈ 46 GB/año**. A cinco años de retención, **≈230 GB** solo de documentos.
n es pequeño en ambas mediciones: **hay que remedirlo con un mes real antes de comprar disco**.

**Tiempo de restauración (medido en NTFS, hoy):** crear 11 000 archivos costó **23.3 s** (2.1 ms/archivo)
y borrar el árbol **9.4 s**. Es decir, restaurar **un mes** de documentos son ~23 s de metadatos + 3.9 GB
de transferencia; **un año** (132 000 archivos, 46 GB) son ~**4.7 min** de metadatos + la transferencia.
La restauración no es el problema; **el problema es tener la copia**.

| | Linux | Windows |
|---|---|---|
| `ingesta/` | directorio normal del host → cualquier herramienta (`restic`, `borg`, `rsync`, cinta) | directorio normal del host → cualquier herramienta (Windows Server Backup, Veeam, `robocopy`) |
| `db-data` (si se usa la BD local) | está en `/var/lib/docker/volumes/<proyecto>_db-data/_data`: ruta real del host, pero **nunca copiar en caliente un datadir de MySQL** → `mysqldump` o parar el contenedor | con Docker Desktop vive **dentro del `ext4.vhdx` de WSL2**: **no hay ruta del host que copiar**. Obligatorio pasar por un contenedor: `docker run --rm -v <proyecto>_db-data:/from -v "$PWD":/to alpine tar czf /to/db.tgz -C /from .` (la misma receta que `01_software.md` §3.A2 usa para `ollama-models`) |
| Consistencia | `mysqldump --single-transaction` | idem |

**Y la regla que la restricción del proyecto convierte en obligatoria:** el proyecto es **100 % local, sin
que nada salga a internet** (Ley 1581, `CLAUDE.md` §Restricciones). **Una copia de seguridad en la nube
rompería esa promesa** — es el escenario de fuga más probable de todo el diseño, porque la copia lleva la
PII completa, con cédula en el nombre y nombre de persona en la ruta. La copia tiene que quedarse
**on-premise, cifrada, con la misma ACL**, y hay que probar la restauración.
→ **Ventaja de Linux: pequeña pero real** (`db-data` accesible como ruta del host, y un solo camino de
respaldo en vez de dos).

### 3.8 Instalación offline y traslado

`01_software.md` §3 establece dos reglas: **(1)** `docker build` es **imposible** en el equipo aislado (el
`Dockerfile` hace `apt-get update` + `pip install`), y **(2)** el equipo puente debe coincidir en
**plataforma** con el destino.

- **Destino Linux (o W1/W2):** el puente produce imágenes `linux/amd64` — **incluso desde un portátil
  Windows con Docker Desktop**, que es lo que construye por defecto. El traslado es el `.tgz` de
  `docker save` (~4 GB con Ollama, < 1 GB sin él) + el `.tgz` del volumen de modelos (~6.5 GB medidos).
  Camino ya documentado y medido.
- **Destino W3 (Windows nativo):** hay que llevar **ruedas de Windows** en vez de imágenes:
  **115 MB medidos** (win/cp314) y **364 MB** desempaquetados en un venv Windows limpio
  (`01_software.md` §2b). Y hay que usar **Python 3.12**, no 3.13/3.14: en ≥3.13 pip **degrada
  silenciosamente** `rapidocr-onnxruntime` a la 1.2.3 de 2023 y el pipeline pierde **6 puntos medidos**
  de precisión (82 % → 76 %, `01_software.md` §1.3). Combinación Windows + Python 3.12 + rapidocr 1.4.4:
  **sin medir aquí**.
→ **Empate para W1/W2; W3 duplica la superficie de despliegue.**

### 3.9 Operación, diagnóstico y coincidencia con lo ya probado

- **Dentro del contenedor todo es idéntico** en cualquier SO — eso es lo que el plan §5 acierta al decir.
- **Capas que hay que diagnosticar cuando algo falla:** Linux = `systemd` → `dockerd` → contenedor.
  W1 = Windows → Hyper-V → VM Linux → `systemd` → `dockerd` → contenedor. W2 = Windows → WSL2 →
  `systemd` en WSL → `dockerd` → contenedor (más la tarea programada que lo arranca). **Cada capa es un
  dominio de fallo que este proyecto nunca ha probado.**
- **Toda la evidencia acumulada del proyecto que involucra contenedores es Linux:** el 82 % de precisión
  medido corresponde a la resolución de `python:3.12-slim`/rapidocr 1.4.4 (`01_software.md` §1.3), y los
  digests fijados en §3 son de imágenes `linux/amd64`. Elegir Linux **no requiere revalidar nada**;
  elegir W3 obliga a revalidar precisión y arranque desde cero.

### 3.10 Tabla resumen

| # | Criterio | Windows Server | Linux | Gana |
|---|---|---|---|---|
| 1 | **Arranque sin login tras reboot** | Solo con capa extra: VM Hyper-V (W1, sólido) o WSL2 + tarea programada (W2, frágil). Docker Desktop **no** arranca sin sesión; el «modo B» del plan §5 **no funciona** sobre Docker Desktop (§3.1) | `systemctl enable --now docker` + `restart: unless-stopped`. Un comando, camino soportado | **Linux** |
| 2 | **Compatibilidad del stack** | Los 3 servicios son contenedores **Linux**; Windows Server no los corre nativo. MCR ejecuta contenedores Windows; LCOW descontinuado | Es la plataforma nativa de las 3 imágenes | **Linux (decisivo)** |
| 3 | **Bind mount y moves** | Penalización de gRPC-FUSE/VirtioFS **sin medir**. Cálculo: el FS es 0.46 % del coste del OCR → irrelevante para throughput. El escaneo de 11 000 archivos supera el poll de 30 s a partir de ×21 | Bind mount nativo, sin traducción | Linux (margen pequeño, acotado por cálculo) |
| 4 | **MAX_PATH 260** | Peor caso calculado **193 chars** con la raíz de esta máquina; requisito: `len(INGESTA_ROOT) ≤ 115`. Sobran ≥66 chars. `LongPathsEnabled=1` verificado: `cmd.exe`/PS 5.1 leen rutas de 300 chars | Límite 4096; no aplica | Empate (deja de ser riesgo) |
| 5 | **Cifrado en reposo** | BitLocker; TPM-only para reboot desatendido; auto-unlock del volumen de datos exige cifrar también el del SO. En W1 el VHDX queda cubierto por el BitLocker del host | LUKS + `systemd-cryptenroll --tpm2-device=auto` | Empate (el requisito real es **TPM/vTPM**) |
| 6 | **ACL** | ACL NTFS es la **única** barrera (el contenedor ignora POSIX). Más simple, más fácil de dejar abierta | uid/gid 1000 + 0750; auditable, pero si está mal **el move falla** y se duplican filas (§5.7) | Empate con riesgos distintos |
| 7 | **Antivirus** | Exclusión de tiempo real obligatoria sobre `INGESTA_ROOT` + `%LOCALAPPDATA%\Docker`. Coste medido: ×35 en la 1.ª lectura = 8.3 min/mes = **1.2 %** del OCR. El riesgo real es **cuarentena de un soporte legal**, no velocidad | Normalmente sin AV on-access | Linux (menos superficie) |
| 8 | **Licencia y coste** | Licencia por núcleo + CAL **[precio: pregunta abierta]**; Docker Desktop de pago y no soportado en Server; MCR de pago y no sirve. W1/W2 usan Docker CE = 0 | SO 0, Docker CE 0 | **Linux**, salvo que el cliente ya tenga licencias y cero administración Linux |
| 9 | **Backup / restauración** | `ingesta/` es un directorio normal (igual). `db-data` vive dentro del `ext4.vhdx` de WSL2 → solo se respalda vía contenedor | `db-data` es ruta del host; un solo camino | Linux (margen pequeño) |
| 10 | **Instalación offline** | W1/W2 igual que Linux (el puente produce `linux/amd64`). W3 exige ruedas Windows + **Python 3.12** o se pierden 6 puntos medidos de precisión | Camino ya documentado y medido (`01_software.md` §3) | Empate (W1/W2) · Linux frente a W3 |
| 11 | **Coincidencia con lo ya medido** | W3 obliga a revalidar precisión y arranque; W1/W2 no cambian nada dentro del contenedor | Toda la evidencia del proyecto (82 %, digests) es `linux/amd64` | **Linux** |
| 12 | **Capas que diagnosticar** | 5-6 (Windows → Hyper-V/WSL2 → VM → systemd → dockerd → contenedor) | 3 (systemd → dockerd → contenedor) | **Linux** |

---

## 4. Recomendación y rutas de contingencia

**Recomendación: Linux x86-64 (Ubuntu Server LTS o RHEL-family), Docker Engine CE como servicio del
sistema.** Razón principal, en orden: (1) los tres contenedores son Linux y Windows Server no los corre
sin una capa extra; (2) el arranque sin login es un `systemctl enable` en vez de un mecanismo no
soportado o no implementado; (3) toda la evidencia medida del proyecto (precisión 82 %, digests, presupuesto de
disco) es `linux/amd64`; (4) coste de licencia 0.

**Condición explícita:** *salvo que* la política de TI del cliente prohíba un host que no sea Windows, o
no exista quién administre Linux ni proveedor que lo soporte. En ese caso, y **solo** en ese caso:

- **Contingencia preferida — W1: Windows Server como hipervisor.** Rol Hyper-V, VM Linux (Ubuntu LTS)
  con *Automatic Start Action = Always start*, Docker Engine dentro, `INGESTA_ROOT` en un disco virtual
  de la VM (**no** un recurso compartido SMB del host: eso reintroduce la penalización del FS y la
  fragilidad de estabilidad de archivo del riesgo #8 del plan). El host Windows aporta BitLocker,
  respaldo y política corporativa; el runtime sigue siendo el mismo Linux que ya está probado. Es la
  única contingencia sin un «pero» estructural.
- **Contingencia aceptable solo si se prohíbe la virtualización — W3: Windows nativo, sin Docker.**
  `uvicorn` como servicio con NSSM, Python **3.12** (no 3.13/3.14), `INGESTA_ROOT` exportado a mano
  (`batch.py:38` cae en `C:\data\ingesta` si no), `LongPathsEnabled=1`. Coste: hay que **escribir** el
  artefacto de servicio (no existe en el repo), revalidar la precisión en Windows + Python 3.12 (**sin
  medir**) y mantener dos caminos de despliegue.
- **Descartadas:** Docker Desktop sobre Windows Server (plataforma no soportada + no arranca sin sesión);
  MCR/contenedores Windows (no ejecutan estas imágenes); el «modo B» del plan §5 sobre Docker Desktop
  (no puede funcionar, §3.1).

**La decisión no se cierra con este documento: se cierra con una prueba.** Cualquiera de las rutas debe
pasar **un reinicio en frío sin login** que termine con `GET /api/lote/estado` respondiendo `programado:
true` y una corrida del lote ejecutada por el cron. El plan §5 ya lo pide; sigue sin hacerse.

---

## 5. Riesgos específicos y accionables si el cliente impone Windows Server

1. **El «camino preferido en Windows» del plan §5 no existe para este stack.** Docker Engine/MCR como
   servicio en Windows Server ejecuta **contenedores Windows**; estas tres imágenes son Linux. *Acción:*
   corregir esa fila del plan y elegir explícitamente W1 (VM Hyper-V) antes de comprar hardware.
   *Detección:* si alguien intenta `docker compose up` con el motor en modo Windows containers, falla con
   «no matching manifest for windows/amd64».
2. **El «modo B» (Programador de tareas) no arranca nada sobre Docker Desktop.** `docker compose up -d`
   y `docker compose exec` son clientes: necesitan un daemon vivo, y el de Docker Desktop lo levanta la
   app de la sesión del usuario. *Acción:* no planificar el modo B como red de seguridad; si el motor está
   en modo servicio, el APScheduler in-process ya basta.
3. **Docker Desktop: plataforma no soportada + licencia.** Windows Server no está en su matriz de
   soporte, y para empresas por encima del umbral la suscripción es de pago **[confirmar]**. *Acción:*
   pregunta a Gruppo sobre tamaño de empresa (§8) antes de asumir coste 0.
4. **Cuarentena de un soporte por Defender.** Es la pérdida de la **única copia del original** de un
   documento con periodo legal de conservación (plan §9.4, riesgo #16), y **pasa en silencio**:
   `batch._mover` captura toda excepción con `log.exception` y el lote continúa. *Acción:* exclusión de
   tiempo real sobre `INGESTA_ROOT` + escaneo programado que **alerta** en vez de borrar + conciliar por
   corrida «archivos vistos = archivos movidos».
5. **`WinError 32` durante el rename.** No reproducido en 300 intentos con Defender activo (§3.2), pero
   la clase de fallo existe (indexador, backup, previsualización de Explorer). *Acción:* mantener el
   reintento con backoff del plan §9.2 y **desactivar el Servicio de Windows Search** sobre esa ruta.
6. **`INGESTA_ROOT` largo.** Con `len(INGESTA_ROOT) > 115` el peor caso del árbol pasa de MAX_PATH y las
   herramientas del **host** (no el contenedor) dejan de poder leer/borrar el archivo. *Acción:* colocar
   la ingesta en una ruta corta (`D:\ingesta`, 10 chars → 155 en el peor caso) y poner
   `LongPathsEnabled=1` como red de seguridad.
7. **Docker Desktop + `db-data` sin ruta de host.** El volumen vive dentro del `ext4.vhdx` de WSL2: un
   backup por archivos del host **no lo incluye** y se descubriría el día de la restauración. *Acción:*
   respaldar por contenedor (`docker run --rm -v …:/from … tar czf`) o, mejor, apuntar `DB_*` a la ASTGU
   real y no depender del volumen local.
8. **Todo el `%LOCALAPPDATA%\Docker` en el perfil de un usuario.** Con Docker Desktop, imágenes y
   volúmenes cuelgan del perfil de la cuenta que instaló; si esa cuenta se deshabilita o se limpia el
   perfil, se pierden. *Acción:* cuenta de servicio dedicada, nunca la de una persona.
9. **Reloj y zona horaria mal alineados (aplica a los dos SO, pero en Windows se descubre más tarde).**
   Ver §6, paso común 4: el contenedor corre en **UTC** y `date.today()` alimenta `fecharegistro` y el
   «hoy» de las reglas temporales.
10. **Nadie ha ejecutado este stack en Windows Server jamás.** El repo ha corrido en Windows 11 con
    Docker Desktop (desarrollo) y en contenedores Linux; W1/W2/W3 son configuraciones nuevas.
    *Acción:* presupuestar una ventana de validación real (reboot en frío + lote programado + un mes de
    documentos de prueba), no darla por hecha.

---

## 6. Checklist de preparación del servidor (en orden)

Los pasos **A** son para Linux (la recomendación); los **B** para Windows Server con VM Linux (W1); los
**C** son **comunes a los dos** y son los que más se olvidan. Cada paso trae el comando y **cómo se
comprueba**.

### A — Linux (recomendado)

1. **Base:** Ubuntu Server LTS x86-64 (o Rocky/RHEL), instalación mínima, sin escritorio. Disco separado
   o partición dedicada para `INGESTA_ROOT` dimensionada con **≈3.9 GB/mes** de documentos (§3.7) + el
   presupuesto de software de `01_software.md` §5 (**~17 GB** con IA, **~2.4 GB** sin ella).
2. **Cifrado del volumen de datos ANTES de escribir un solo documento:** LUKS con desbloqueo por TPM2
   para que el reboot sea desatendido —
   `cryptsetup luksFormat /dev/sdX && systemd-cryptenroll --tpm2-device=auto /dev/sdX` — y entrada en
   `/etc/crypttab`. *Comprobación:* `lsblk -o NAME,FSTYPE,MOUNTPOINT` + **reboot** y que monte solo.
3. **Zona horaria del host:** `timedatectl set-timezone America/Bogota` y `timedatectl set-ntp true`.
   *Comprobación:* `timedatectl` muestra `America/Bogota` y `NTP synchronized: yes`.
4. **Docker Engine CE + Compose v2** (Engine ≥ 23.0 para que el plugin `compose` venga incluido,
   `01_software.md` §2a) y **habilitarlo como servicio**: `systemctl enable --now docker`.
   *Comprobación:* `systemctl is-enabled docker` → `enabled`.
5. **Usuario de servicio sin shell** y con el uid que espera el contenedor:
   `useradd -r -u 1000 -g 1000 -s /usr/sbin/nologin ocr-svc` (verificar el uid real del contenedor con
   `docker compose exec incapacidad-ocr id`). **No** poner cuentas de personas en el grupo `docker`: es
   equivalente a root (§3.4).
6. **Permisos de la carpeta de ingesta** — el paso que más rompe el día 1:
   `mkdir -p /datos/ingesta && chown -R 1000:1000 /datos/ingesta && chmod -R 0750 /datos/ingesta`.
   *Comprobación dura, no opcional:*
   `docker compose exec incapacidad-ocr touch /data/ingesta/_sistema/tmp/prueba && echo OK` — si esto
   falla, el runner insertará en staging y **no** moverá los archivos, y la corrida siguiente **duplicará
   las filas** (§5.7).
7. **Crear el árbol:** `docker compose exec incapacidad-ocr python -m incapacidad_ocr.batch --init`.
   *Comprobación:* existen `1_entrada/{whatsapp,correo,ventanilla}`, `2_revisar/{4 subcarpetas}`,
   `3_archivo`, `_sistema/{logs,tmp,control}`.

### B — Windows Server como hipervisor (contingencia W1)

1. **Rol Hyper-V** + una VM Linux (Ubuntu Server LTS), **Generación 2 con vTPM habilitado** (sin vTPM no
   se puede tener cifrado *y* reboot desatendido a la vez, §3.4).
2. **Autoarranque de la VM:** `Set-VM -Name ocr -AutomaticStartAction Start -AutomaticStartDelay 0
   -AutomaticStopAction ShutDown`. *Comprobación:* **reinicio en frío del host sin iniciar sesión** y la
   VM aparece corriendo.
3. **BitLocker en el volumen del host que aloja el VHDX**, con **TPM-only** (no PIN: el PIN rompe el
   reboot desatendido). *Comprobación:* `manage-bde -status` → `Protection On`, y reboot sin intervención.
4. **`INGESTA_ROOT` dentro de un disco virtual de la VM**, no en un recurso SMB del host (evita la
   penalización de FS y el riesgo #8 del plan, estabilidad de archivo sobre SMB). Si RH tiene que dejar
   archivos desde la red, se expone una **carpeta compartida desde la VM Linux (Samba)**, no al revés.
5. **Defender del host:** excluir del escaneo en tiempo real la carpeta de los VHDX y la de Hyper-V:
   `Add-MpPreference -ExclusionPath 'D:\Hyper-V'`. *Comprobación:* `(Get-MpPreference).ExclusionPath`
   (requiere administrador).
6. **Zona horaria del host:** `Set-TimeZone -Id 'SA Pacific Standard Time'` (= UTC−05:00 Bogotá,
   verificado hoy con `Get-TimeZone`) y `w32tm /resync`.
7. **Dentro de la VM: repetir A2–A7 completo.**
8. **Windows Search:** excluir la ruta de los VHDX y, si por alguna razón la ingesta vive en el host,
   también esa (`Servicios` → *Windows Search*, o Opciones de indización).
9. **Si en lugar de W1 se impone W3 (nativo, sin Docker):** Python **3.12** (no 3.13/3.14 — 6 puntos
   medidos de precisión, `01_software.md` §1.3), `LongPathsEnabled=1`
   (`Set-ItemProperty 'HKLM:\SYSTEM\CurrentControlSet\Control\FileSystem' LongPathsEnabled 1`),
   **exportar `INGESTA_ROOT` explícitamente** (si no, `batch.py:38` cae en `C:\data\ingesta`), y crear el
   servicio con NSSM (`nssm install incapacidad-ocr … uvicorn …`) **con cuenta de servicio dedicada**.
   Este artefacto **hay que escribirlo: no existe en el repo.**

### C — Común a los dos SO (no omitir ninguno)

1. **`.env` con la BD real, y quitar el `db` de demo.** El compose hace `DB_HOST=${DB_HOST:-db}`: si el
   `.env` falta, el sistema escribe **staging en un MySQL de juguete** dentro de un contenedor y nadie lo
   nota. **No hay `.env` ni `.env.example` en el repo** (verificado). *Comprobación:*
   `GET /api/health` reporta `db_disponible: true` y un `SELECT` contra ASTGU devuelve las filas nuevas.
2. **Fijar los tags de las imágenes** (`ollama/ollama:latest` → `0.33.2`, `mysql:8` → `8.4.11`) y pinear
   `requirements.txt` — en particular `rapidocr-onnxruntime==1.4.4`: son **+6 puntos medidos** de
   precisión y evita que el motor de OCR de producción lo decida un accidente de metadata
   (`01_software.md` §1.3, §4).
3. **Longitud de la ruta de ingesta:** verificar `len(INGESTA_ROOT) ≤ 115` (§3.3). Ruta corta y estable
   (`/datos/ingesta`, `D:\ingesta`). *Comprobación:* crear a mano la ruta más profunda posible
   (`2_revisar/datos_por_revisar/<60 chars>/2026/09/02/<38 chars>.pdf`) y abrirla desde el host.
4. **Zona horaria del CONTENEDOR — hoy falta y es un defecto real.** `docker-compose.yml` pasa
   `BATCH_TZ=America/Bogota`, pero eso **solo** configura el cron de APScheduler (`webapp.py:157-160`).
   **No hay ninguna variable `TZ`** en el compose ni en el `Dockerfile` (verificado), así que el
   contenedor corre en **UTC** y `date.today()` es el que alimenta `fecharegistro`
   (`erp.py:615`) y el «hoy» de las reglas temporales (`reglas_tiempo.py:553,561` — `dias_futuro_max` y
   `dias_antiguedad_max`). *Consecuencia concreta:* cualquier corrida entre las **19:00 y 23:59 de
   Bogotá** (00:00–04:59 UTC) estampa `fecharegistro` **un día adelantado** y desplaza un día los límites
   de las reglas de tiempo. *Acción:* añadir `- TZ=${BATCH_TZ:-America/Bogota}` al servicio
   `incapacidad-ocr`. *Comprobación:*
   `docker compose exec incapacidad-ocr python -c "from datetime import datetime;print(datetime.now())"`
   contra el reloj de pared de Bogotá.
5. **Corrida programada:** definir `INGESTA_CRON` (p. ej. `0 2 * * *`) en el `.env` — **vacío =
   desactivada** (`webapp.py:49`; el plan §9.3 dice erróneamente que el default es `0 2 * * *`).
   *Comprobación:* `curl -s http://localhost:8000/api/lote/estado` → `{"programado": true, "cron": "0 2 *
   * *", "tz": "America/Bogota", "proxima_ejecucion": …}`.
6. **Antivirus:** exclusión de **tiempo real** sobre `INGESTA_ROOT` (y `%LOCALAPPDATA%\Docker` /
   la carpeta de VHDX en Windows) + **escaneo programado diario de la misma ruta configurado para
   ALERTAR, no para borrar** (§3.5). *Comprobación:* copiar un PDF real a `1_entrada/` y confirmar que
   sigue ahí un minuto después.
7. **Reinicio automático:** los tres servicios ya llevan `restart: unless-stopped`. Lo que hay que
   verificar es el eslabón de arriba: `systemctl is-enabled docker` (A) / autoarranque de la VM (B).
   **Prueba de aceptación: reinicio en frío SIN LOGIN** → esperar el cron → el lote corrió. Es la prueba
   que cierra la precondición P2.
8. **Monitoreo de disco con umbrales calculados, no genéricos:** crecimiento **≈3.9 GB/mes** de
   documentos (§3.7) + 6.54 GB del volumen de modelos si se usa IA. Alertar al **20 % libre** y, sobre
   todo, vigilar que **el propio disco de Docker** no se llene (una imagen que se reconstruye deja capas
   huérfanas). *Comprobación:* `df -h`, `docker system df`, y una alerta que llegue a una persona.
9. **Respaldo de `ingesta/` + prueba de restauración**, **on-premise y cifrado — nunca a la nube**
   (rompería la promesa «100 % local», §3.7). Restauración medida: ~23 s de metadatos por mes de
   documentos. *Comprobación:* restaurar un mes en un directorio aparte y contar archivos.
10. **Auditar quién está en el grupo `docker` / `docker-users`:** es equivalente a root sobre todo el host
    y por tanto sobre toda la PII (§3.4). Debe ser una lista corta y revisada.
11. **Registrar la decisión y su prueba** en `CONTEXT.md` §7 (hoy dice «pendiente») y corregir
    `PLAN_INGESTA_MASIVA.md` §5 con lo de §7 de este documento.

---

## 7. Correcciones al repo que salen de este análisis

| # | Dónde | Dice | Debería decir |
|---|---|---|---|
| 1 | `PLAN_INGESTA_MASIVA.md` §5, tabla | «Windows Server con Docker Engine/containerd como servicio … **Camino preferido en Windows**» | Esos runtimes ejecutan contenedores **Windows**; las 3 imágenes del compose son **Linux**. El camino en Windows es una **VM Linux** (o WSL2). **[confirmar con el proveedor]** |
| 2 | `PLAN_INGESTA_MASIVA.md` §5, fila «Windows headless solo con Docker Desktop» | «Programador de tareas … `docker compose up -d` / `docker compose exec …`» | **No puede funcionar:** ambos son clientes de un daemon que Docker Desktop solo levanta en la sesión del usuario. El modo B únicamente tiene sentido con un motor en modo servicio — y entonces sobra |
| 3 | `PLAN_INGESTA_MASIVA.md` §11, riesgo #19 (MAX_PATH) | riesgo vivo, mitigado con «nombres cortos `NN_<tipo>`» | Con el árbol actual el peor caso es **193 chars** (raíz de 48) y sobran ≥66. Baja a **verificación de instalación**: `len(INGESTA_ROOT) ≤ 115`. Los nombres cortos **no** hacen falta (y ya se descartaron, §4.4) |
| 4 | `PLAN_INGESTA_MASIVA.md` §9.2 | «Reintentos con backoff ante `WinError 32` (Defender/indexador)» | Mantener el reintento, pero **0 fallos en 300 intentos** con Defender activo. El coste medido del AV es la **primera lectura** (×35 → 8.3 min/mes = 1.2 % del OCR); el riesgo real es la **cuarentena** de un soporte |
| 5 | `docker-compose.yml` (servicio `incapacidad-ocr`) | pasa `BATCH_TZ` pero **no** `TZ` | Añadir `- TZ=${BATCH_TZ:-America/Bogota}`: el contenedor corre en UTC y `date.today()` alimenta `fecharegistro` (`erp.py:615`) y el «hoy» de las reglas temporales. Corridas de 19:00–23:59 Bogotá estampan **un día adelantado** |
| 6 | `README.md` §Requisitos mínimos | «SO: Windows 10/11, macOS o Linux con Docker + Compose v2» | Correcto para probar; como requisito **de servidor** falta decir que un host **Windows Server** no ejecuta este stack como servicio de arranque sin una VM Linux por debajo |
| 7 | Repo completo | — | **No existe** ningún artefacto de arranque del SO (unidad systemd, tarea programada, script NSSM) ni `.env`/`.env.example`. Ambos son entregables del despliegue y hoy son un hueco |
| 8 | `CONTEXT.md` §5.6 y §7 | «el contenedor sube solo con `restart: unless-stopped` mientras Docker arranque en el boot: … **Docker Engine como servicio en Windows Server**» | Misma corrección que #1 |

---

## 8. Preguntas abiertas que hay que hacerle al cliente (bloquean el cierre)

1. **¿Tiene Gruppo licencias de Windows Server disponibles, y quién administra sus servidores?** Es la
   única variable que puede invertir la recomendación por coste de personal. **No lo sé.**
2. **¿Tamaño de la empresa (> 250 empleados o > USD 10 M de ingresos)?** Determina si Docker Desktop
   exigiría suscripción de pago **[confirmar con Docker]**. Solo importa si se insiste en Docker Desktop,
   que este informe descarta.
3. **¿El servidor tendrá TPM (o vTPM si es virtual)?** Sin él no se puede tener **cifrado en reposo y
   reboot desatendido a la vez** (§3.4). Es un requisito de compra, no de configuración.
4. **¿Se permite virtualización (Hyper-V) en su política de TI?** Si no, la única contingencia Windows es
   W3 (nativo sin Docker), que duplica la superficie de despliegue.
5. **¿Cuál es el periodo legal de conservación de los soportes?** El plan §9.4 lo deja «a confirmar con
   jurídico». Determina el disco: **≈46 GB/año** de documentos (§3.7).
6. **¿Dónde vive la BD ASTGU (mismo host, misma LAN, o remota)?** `02_benchmark.md` §11.3 no midió
   latencia de MySQL; con la BD remota y N workers puede dejar de ser despreciable.
7. **¿Existe una política de respaldo on-premise?** Un respaldo en la nube **rompe** la restricción
   «nada sale a internet» (§3.7) y es el escenario de fuga de PII más probable del diseño.

---

## 9. Cómo reproducir las mediciones de este informe

Todo corre con el venv del repo, sin red, sin Docker, sin MySQL. En el servidor definitivo hay que
repetir 2–5 y 7 (los de FS/AV) y comparar; el escalado del pool y el coste por documento se reproducen
con `bench_ocr.py` (`02_benchmark.md` §12).

```bash
PY="/c/Projects/Vivetori/ocr/incapacidad-ocr/.venv/Scripts/python.exe"   # Linux: .venv/bin/python

# 1) Estado del host (Windows)
powershell -NoProfile -Command "(Get-ItemProperty 'HKLM:\SYSTEM\CurrentControlSet\Control\FileSystem').LongPathsEnabled"
powershell -NoProfile -Command "Get-TimeZone | Select Id,BaseUtcOffset"
powershell -NoProfile -Command "Get-MpComputerStatus | Select RealTimeProtectionEnabled,OnAccessProtectionEnabled"

# 2) Peor caso de ruta, usando las funciones REALES del repo (no una estimación)
$PY -c "import sys;sys.path.insert(0,'.');from incapacidad_ocr.batch import _sanit_carpeta,_partes_destino,REVISAR,DATOS_POR_REVISAR;import os;print(len(_sanit_carpeta('X'*80)));print(len(os.path.join(*_partes_destino([REVISAR,DATOS_POR_REVISAR],'X'*60,'2026-09-02'))))"
# esperado: 60 y 99  ->  presupuesto: len(INGESTA_ROOT) <= 259-99-1-44 = 115

# 3) Coste de la 1.ª lectura vs. caliente (efecto del escaneo on-access): sha256 de
#    ingesta/_sistema/semilla copiado a un temporal, 5 pasadas. Medido aquí: 45.19 -> 1.28 ms/archivo.
# 4) shutil.move a destino anidado, mismo volumen. Medido: p50 0.51 ms.
# 5) 300 x (escribir 300 KB + os.replace inmediato) -> contar WinError 32. Medido: 0 fallos.
# 6) rglob+sorted+is_file sobre 11 000 archivos en 30 subcarpetas. Medido: 1.405 s.
# 7) crear/borrar esos 11 000 archivos (base del tiempo de restauración). Medido: 23.3 s / 9.4 s.
#    (los cuatro son bucles de ~20 líneas con time.perf_counter; ver el cuerpo de §0)

# 8) Rutas largas frente a las herramientas del host
$PY -c "import pathlib;p=pathlib.Path('X'*300);print(len(str(p)))"   # y luego: cmd.exe /c dir "<ruta>"
```

**Prueba de aceptación que cierra P2 (la única que no se puede sustituir por un cálculo):** reinicio en
frío del servidor **sin iniciar sesión** → esperar la hora de `INGESTA_CRON` → `curl -s
http://localhost:8000/api/lote/estado` responde `programado: true` con `proxima_ejecucion` coherente, y
la corrida movió los documentos de `1_entrada/` a `3_archivo/`/`2_revisar/`.
