# Qué hay que instalar y qué servidor hace falta

**Para:** el equipo de TI de Gruppo que va a montar `incapacidad-ocr` en el **servidor de producción**.
**Resumen en una línea:** un servidor Linux de **4 núcleos y 16 GB de RAM** con **Docker**, sin salida a
internet, y unos **250 GB de disco** para cinco años de soportes.

> Documento **ejecutivo**. El detalle (comandos exactos, traslado a un equipo aislado, matriz
> Windows vs Linux, aritmética completa) está en [`REQUISITOS_INSTALACION.md`](REQUISITOS_INSTALACION.md).

---

## 1. Software a instalar

Solo hace falta **una cosa**: Docker. Todo lo demás va dentro de los contenedores.

| Componente | Versión | ¿Obligatorio? | Espacio |
|---|---|---|---|
| **Docker Engine** + plugin **Compose v2** | Engine ≥ 23.0 | **Sí** | ~0,5 GB |
| Imagen de la aplicación (se construye una vez) | base `python:3.12-slim` | **Sí** | ~1,1 GB |
| Imagen **MySQL 8** | 8.4 | **No** en producción — allí se apunta a la BD **ASTGU** real | ~0,6 GB |
| Imagen **Ollama** + modelos de IA local | `gemma3:4b` (3,3 GB) y `qwen2.5vl:3b` (3,2 GB) | **No** — solo mejora los casos difíciles | ~8 GB + 6,5 GB |

**Sin Ollama el sistema funciona igual**, con el OCR rápido (RapidOCR) y las reglas: es la
configuración por defecto. Ollama solo se necesita para **permisos manuscritos**, que RapidOCR lee mal.
Si no se instala, esos casos quedan para revisión manual — no se pierden.

**No hace falta instalar Python, ni Poppler, ni Tesseract, ni ningún servicio de OCR:** todo viaja
dentro de la imagen.

### Lo que el sistema NO necesita

- **No necesita internet en funcionamiento.** Ni los documentos ni los datos salen del servidor
  (son datos de salud — Ley 1581). Internet solo se usa **una vez**, para bajar las imágenes; si el
  servidor está aislado, el traslado se hace con un archivo (procedimiento en el documento detallado).
- **No necesita GPU.** Todo corre en CPU. Una GPU solo aceleraría la IA local opcional.
- **No necesita licencias.** Todo el software es libre y no hay APIs de pago.

---

## 2. Hardware

| | Mínimo | **Recomendado** | Con IA local (Ollama) |
|---|---|---|---|
| **Núcleos** | 4 | **4** | 6 |
| **RAM** | 12 GB | **16 GB** | 24 GB |
| **Disco** | 120 GB SSD | **250 GB SSD** | 270 GB SSD |
| **GPU** | no | no | opcional |
| **SO** | Linux x86-64 (Ubuntu Server / RHEL) | igual | igual |

### De dónde salen esos números

Medido sobre los **31 documentos reales** del cliente, en un i7-1255U con un hilo de OCR por proceso:

- **Coste de CPU por documento:** mediana **8,6 s**, media **10 s** (imágenes ~3,5 s; PDF de 1 página
  ~8,6 s; PDF de varias páginas ~12 s). El **97 % del tiempo es el OCR**; convertir el PDF a imagen es
  el 3 %. Cada proceso usa **1 núcleo efectivo** (medido: 0,96).
- **Cálculo de CPU:** 7 000 trámites/mes × 10 s = **19,4 horas de CPU al mes** ≈ **53 minutos de un
  núcleo por día laboral**. Incluso asumiendo que las incapacidades llegan concentradas (lunes y
  después de festivos, ×3), un día pico son ~2,6 horas de CPU: **3 procesos en paralelo lo drenan en
  menos de una hora**. Por eso 4 núcleos bastan — el cuello de botella no es la CPU.
- **Disco:** el documento medio del corpus pesa **379 KB**. Con incapacidad + soportes (≈2,5 archivos
  por trámite): **~6,3 GB/mes → 76 GB/año → 379 GB a cinco años**. Los 250 GB recomendados cubren
  **~3 años**; hay que planear crecimiento o depuración según el plazo legal de conservación.
- **RAM — el dato que hay que mirar:** el pipeline usa ~100 MB al arrancar, pero **un solo PDF del
  corpus llegó a un pico de 7,6 GB**. No es un caso raro: con los topes que trae hoy el sistema
  (`PDF_RENDER_SCALE=3.0`, `OCR_MAX_PIXELS=40 MP`), un escaneo de gran formato genera una imagen
  enorme y el OCR reserva memoria proporcional. Con esos valores por defecto, **8 GB no alcanzan ni
  para un proceso**. Dos opciones, y hay que elegir una antes de comprar:
  1. **Bajar los topes** (`PDF_RENDER_SCALE=2.0`, `OCR_MAX_PIXELS=12000000`) → la RAM por proceso baja
     a ~2 GB y 16 GB cubren varios procesos. Es la vía recomendada; hay que comprobar que no se pierde
     precisión en los escaneos de peor calidad.
  2. **Dejar los topes** y limitar a 1 proceso con 16 GB, o subir a 32 GB para trabajar en paralelo.

> Estas cifras se midieron en un **portátil con Python 3.14**. En producción (Docker, Python 3.12) el
> OCR corre una **versión más nueva y más precisa** del motor (82 % de acierto frente al 76 % del
> entorno local), así que la precisión será mejor; el tiempo puede variar. El script de medición
> (`bench_ocr.py`) se entrega para **repetir la medición en el servidor real antes de cerrar la compra**.

---

## 3. Instalación, en corto

**Servidor con internet:**

```bash
docker compose up -d --build          # construye y levanta
docker compose exec ollama ollama pull gemma3:4b     # opcional (IA local)
```

**Servidor aislado (lo habitual en producción):** las imágenes se preparan en un equipo con internet,
se trasladan en un archivo (~4 GB con IA, <1 GB sin ella) y se cargan en el servidor sin compilar nada.
Procedimiento completo, con los comandos de las dos partes, en `REQUISITOS_INSTALACION.md`.

La aplicación queda en **http://localhost:8000**, publicada **solo en el propio servidor** (no en la
red), porque los documentos contienen datos personales. Si tiene que abrirse a la red interna, hay que
añadir un proxy con TLS y autenticación — hoy no los trae.

**Comprobación de que quedó bien:**

```bash
curl http://localhost:8000/api/health          # {"status":"ok"}
curl http://localhost:8000/api/lote/pendientes # cuenta los documentos en la carpeta de entrada
```

---

## 4. Lo que necesitamos del cliente

| Qué | Para qué | Sin eso… |
|---|---|---|
| **Servidor** con las características de §2 y **Docker instalado como servicio** (que arranque solo tras un reinicio) | correr el sistema | el proceso programado no se levanta tras un reboot |
| **Acceso a la BD ASTGU** (host, puerto, usuario, clave) | escribir en `lp_ausentismos_ia` | el sistema lee documentos pero no registra nada |
| Catálogo real de **diagnósticos CIE-10** (`lpdiagnosticos`) | validar el diagnóstico y detectar códigos inexistentes | no se puede afirmar que un diagnóstico no existe |
| **Carpeta compartida** donde el punto de recepción deja los documentos | la ingesta por lotes | habría que copiarlos a mano al servidor |
| **Decisión: Linux o Windows Server** | preparar el servidor | recomendamos Linux (ver el documento detallado) |
| **Plazo legal de conservación** de los soportes | dimensionar el disco a 3 o 5 años | el disco se calcula a ciegas |
| **Exclusión del antivirus** sobre la carpeta de ingesta | evitar que bloquee archivos en uso | fallos intermitentes al mover documentos |
| **Cifrado del disco** y permisos de la carpeta | datos de salud, Ley 1581 | riesgo legal |

---

## 5. Qué se entrega hoy y qué falta

**Funciona y está probado:** lectura de incapacidades, permisos y vacaciones (imagen o PDF) →
extracción de los datos → registro en la tabla de revisión del ERP; ingesta masiva por carpetas con
validación de los soportes requeridos por tipo; bandeja para que el auxiliar complete, apruebe o
rechace; corrida programada; y un juego de pruebas con los **31 documentos reales** (15 adulterados y
16 legítimos) que se puede repetir con el botón **«↺ Reiniciar prueba»** de la aplicación.

**Pendiente antes de producción:** apuntar a la BD ASTGU real (hoy usa catálogos de prueba), repetir
la medición en el servidor definitivo, y cerrar la detección de documentos adulterados, que hoy está
especificada y medida pero necesita el catálogo CIE-10 real para funcionar completa.
