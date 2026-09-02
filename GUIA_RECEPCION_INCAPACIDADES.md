# Guía de recepción de incapacidades

**Para quién:** el equipo que recibe las incapacidades (WhatsApp, correo, ventanilla) y las deja en el servidor.
**Objetivo:** que los documentos lleguen de una forma **estándar** para que el sistema los lea, valide y registre **solo**, y el auxiliar únicamente revise y apruebe.

---

## 1. En qué formato deben llegar

- **PDF o foto** (JPG / PNG). También se aceptan WEBP y TIFF.
- **Un documento por archivo.** Si un trámite tiene incapacidad + epicrisis + cédula, son **3 archivos separados**, no un solo PDF con todo.
- **Legible:** derecho, enfocado, completo (que se lea la cédula, el diagnóstico y las fechas). Una foto torcida o borrosa se marcará para revisión manual.
- Tamaño máximo por archivo: **50 MB**.

## 2. Cómo nombrar cada archivo (lo más importante)

El **nombre del archivo** le dice al sistema de quién es y qué documento es. El formato es sencillo:

```
cedula_TIPO.extensión
```

| Parte | Qué va | Ejemplo |
|---|---|---|
| **cedula** | Cédula del empleado (solo números) | `1005542119` |
| **TIPO** | Qué documento es (ver lista abajo) | `INCAPACIDAD` |
| **extensión** | `pdf`, `jpg`, `png`… | `.pdf` |

> **Regla clave:** todos los archivos de un mismo empleado/trámite llevan la **misma cédula** → así el sistema los agrupa como un solo caso. **La fecha NO va en el nombre:** el sistema la lee del propio documento.

**Ejemplos:**

```
1005542119_INCAPACIDAD.pdf     ← la incapacidad
1005542119_FURAT.pdf           ← su soporte (accidente de trabajo)

1023456789_INCAPACIDAD.pdf
1023456789_EPICRISIS.pdf
```

Si un trámite trae **dos del mismo tipo**, se numeran: `..._EPICRISIS_01.pdf`, `..._EPICRISIS_02.pdf`.

## 3. Qué documentos enviar según el caso

**Siempre** la incapacidad (o el permiso/vacaciones). Los **soportes adicionales dependen del tipo**:

| Tipo de ausentismo | Además de la incapacidad, enviar |
|---|---|
| Enfermedad general | Epicrisis o historia clínica |
| Accidente de trabajo / Enfermedad laboral | FURAT |
| Accidente de tránsito | FURIPS |
| Licencia de maternidad | Historia clínica + certificado de nacido vivo (o registro civil) |
| Licencia de paternidad | Registro civil de nacimiento (o certificado de nacido vivo) |
| Permiso / Vacaciones | Solo el documento del permiso o de vacaciones |

Si falta un soporte, **igual se puede enviar**: el sistema lo registra como **incompleto** y genera una alerta para pedir lo que falta.

> **Además — lo que pide la EPS para pagar.** Radicar el cobro ante la EPS suele exigir **más**
> documentos que el trámite interno (p. ej. copia de la cédula del trabajador o certificado
> laboral, según la EPS). Al procesar el lote, el sistema compara lo que llegó contra el
> checklist de radicación de esa EPS y avisa —sin frenar el trámite— **qué documento faltará
> a la hora de radicar**, para pedirlo desde ya.

## 4. Palabra para el "TIPO" del nombre

| Documento | Escribir en el nombre |
|---|---|
| Incapacidad médica | `INCAPACIDAD` |
| Solicitud de permiso | `PERMISO` |
| Notificación de vacaciones | `VACACIONES` |
| Epicrisis / resumen de atención | `EPICRISIS` |
| Historia clínica | `HISTORIA` |
| FURAT (accidente de trabajo) | `FURAT` |
| FURIPS (accidente de tránsito) | `FURIPS` |
| Certificado de nacido vivo | `NACIDOVIVO` |
| Registro civil de nacimiento | `REGISTROCIVIL` |
| Certificado de defunción | `DEFUNCION` |
| Copia de la cédula | `CEDULA` |
| SOAT (accidente de tránsito) | `SOAT` |
| Reporte de accidente de tránsito | `RAT` |
| Formato de descarte de evento laboral | `DESCARTE` |
| Certificado laboral | `CERTIFICADOLABORAL` |
| Otro soporte | `OTRO` |

## 5. Dónde se dejan

Los archivos, **ya nombrados**, se depositan en la **carpeta de entrada del servidor** — `1_entrada` —, en la subcarpeta según el canal por el que llegaron:

```
ingesta/
└── 1_entrada/
    ├── whatsapp/     ← llegaron por WhatsApp
    ├── correo/       ← llegaron por correo
    └── ventanilla/   ← físico / escaneados en ventanilla
```

**`1_entrada` es la única carpeta donde el punto de recepción escribe.** Se pueden crear subcarpetas dentro (por día, por sede…): el sistema busca de forma recursiva.

Las otras dos carpetas de la ingesta las llena **el sistema**, y solo hay que mirar una:

| Carpeta | Qué significa | Qué hacer |
|---|---|---|
| `2_revisar/mal_nombrados/` | El nombre no se pudo interpretar | Renombrar bien y volver a dejarlo en `1_entrada/` |
| `2_revisar/faltan_soportes/` | El caso quedó registrado pero falta un documento | Pedir el soporte; cuando llegue, dejarlo en `1_entrada/` con la misma cédula |
| `2_revisar/datos_por_revisar/` | Los documentos están completos, pero algo no se leyó con certeza | Nada en la carpeta: el auxiliar lo confirma en la aplicación |
| `2_revisar/con_error/` | Falló el procesamiento | Reportar a sistemas |
| `3_archivo/` | Caso **completo** — historial por persona/año/mes/día | Nada: es la consulta |

*(El mecanismo exacto para llevar los archivos a `1_entrada` —carpeta compartida, bot, etc.— se define en la implementación; lo importante para el punto de recepción es el **formato y el nombre**.)*

## 6. Qué hace el sistema después

1. **Agrupa** los archivos por cédula (un caso por trámite) y **lee la fecha del propio documento**.
2. **Lee** la incapacidad y saca los datos (paciente, diagnóstico, fechas, tipo).
3. **Valida** que estén los soportes requeridos según el tipo.
4. **Registra** el caso para revisión y **mueve** los archivos de `1_entrada/` a `3_archivo/`, organizados por **persona → año → mes → día** (para consultar fácil el historial de un empleado).
5. Si falta algo o algo no se leyó bien, lo deja en `2_revisar/` y lo **marca para revisión** (no se pierde nada).

El auxiliar solo **revisa y aprueba** (o completa lo que falte); ya no digita.

## 7. Recomendaciones rápidas

- ✅ Un documento = un archivo, bien nombrado (`cédula_TIPO`).
- ✅ Misma cédula para todos los archivos de un mismo trámite (la fecha la pone el sistema).
- ✅ Fotos derechas y legibles (o mejor, PDF).
- ✅ Dejarlos **solo** en `1_entrada/` (las carpetas `2_revisar/` y `3_archivo/` las maneja el sistema).
- ❌ No juntar varios documentos en un solo PDF.
- ❌ No usar nombres como `IMG_2026.jpg` o `escaneo.pdf` → el sistema no sabe de quién es y lo manda a `2_revisar/mal_nombrados/`.
