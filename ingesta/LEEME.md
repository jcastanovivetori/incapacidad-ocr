# Carpeta de ingesta de ausentismos — cómo está organizada

Esta carpeta tiene **tres zonas numeradas**: se leen en el orden del flujo (1 → 2 → 3).
Cada documento está siempre en **una sola** de ellas, así que "¿dónde quedó?" tiene una
respuesta única.

```
ingesta/
├── 1_entrada/      ← AQUÍ se dejan los documentos
│   ├── whatsapp/         llegaron por WhatsApp
│   ├── correo/           llegaron por correo
│   └── ventanilla/       físico / escaneados en ventanilla
│
├── 2_revisar/      ← NECESITA QUE ALGUIEN HAGA ALGO
│   ├── mal_nombrados/     el nombre no cumple la convención → renombrar y volver a 1_entrada
│   ├── faltan_soportes/   el caso quedó registrado pero falta un documento → pedirlo
│   ├── datos_por_revisar/ los documentos están, pero algo no se leyó con certeza
│   └── con_error/         falló el procesamiento → avisar a sistemas
│
├── 3_archivo/      ← LISTO: historial de los casos completos
│   └── <Persona>/<AAAA>/<MM>/<DD>/
│
└── _sistema/       ← interno del programa (no hay que abrirlo)
    └── semilla/          copia del corpus de prueba, para poder repetir la demo
```

## Repetir una prueba: «↺ Reiniciar prueba»

Procesar el lote **mueve** los documentos fuera de `1_entrada/`, así que una demo solo se podría
hacer una vez. El botón **«↺ Reiniciar prueba»** de la aplicación (o
`python -m incapacidad_ocr.batch --reiniciar`) los devuelve a `1_entrada/` para volver a correr el
mismo lote:

- **Si hay semilla** (`_sistema/semilla/`, la crea `scripts/sembrar_prueba_falsedad.py`): se restaura
  el estado inicial **exacto**, con cada documento en su canal original. Es el modo repetible.
- **Si no hay semilla:** modo conservador — devuelve a `1_entrada/whatsapp/` lo que haya en
  `2_revisar/` y `3_archivo/` y **no borra nada**; se pierde el canal original (todo queda como
  WhatsApp). El modo que borra exige semilla a propósito: sin ella no habría cómo reconstruirlo.

También borra de la base de datos las filas de staging **PENDIENTES** de esos archivos, para que al
repetir el lote no queden duplicadas. Lo que un auxiliar ya **aprobó o rechazó no se toca nunca**, y
el borrado se filtra por nombre de archivo — nunca es un borrado masivo de la tabla.

## 1_entrada — la única carpeta donde se escribe a mano

Cada archivo se nombra así (**la fecha NO va en el nombre**: el sistema la lee del propio
documento):

```
cedula_TIPODOC.extensión          13742111_INCAPACIDAD.pdf
cedula_TIPODOC_NN.extensión       13742111_EPICRISIS_02.pdf   (si hay varios del mismo tipo)
```

Todos los archivos de un mismo trámite llevan **la misma cédula** → así se agrupan como un
solo caso. Un documento = un archivo (no juntar varios en un PDF). Detalle completo y la
lista de `TIPODOC` en [`../GUIA_RECEPCION_INCAPACIDADES.md`](../GUIA_RECEPCION_INCAPACIDADES.md).

Se pueden crear subcarpetas dentro de `whatsapp/`, `correo/` o `ventanilla/` (por día, por
sede…): el sistema busca de forma **recursiva**.

## 2_revisar — la bandeja física de pendientes

| Carpeta | Qué pasó | Qué hacer |
|---|---|---|
| `mal_nombrados/` | El nombre no se pudo interpretar (`IMG_2026.jpg`, `escaneo.pdf`) | Renombrar bien y mover de nuevo a `1_entrada/` |
| `faltan_soportes/` | El caso **sí** se registró en el sistema, pero falta un documento requerido (p.ej. la epicrisis) | Pedir el soporte; cuando llegue, dejarlo en `1_entrada/` con la misma cédula |
| `datos_por_revisar/` | Los soportes están **completos**, pero el sistema no leyó algo con certeza (cédula, EPS, diagnóstico, fechas) | Nada en la carpeta: el auxiliar lo confirma en la **bandeja de revisión** de la aplicación |
| `con_error/` | Falló técnicamente el procesamiento | Reportar a sistemas (queda el caso en su subcarpeta) |

`faltan_soportes/` y `datos_por_revisar/` usan la misma organización que el archivo: `<Persona>/<AAAA>/<MM>/<DD>/`. Cada carpeta dice **por qué** el caso está ahí, para que se sepa qué hacer sin abrir la aplicación.

## 3_archivo — el historial

Casos **completos** (documentación al día), organizados por **persona → año → mes → día**,
donde la fecha es la de **inicio** de la incapacidad. Sirve para consultar de un vistazo el
historial de ausentismos de un empleado. Si el sistema no pudo leer la fecha, la carpeta del
año queda como `sin_fecha` hasta que el auxiliar la corrija.

> La aprobación **no** ocurre en estas carpetas: se hace en la aplicación (bandeja de
> revisión sobre `lp_ausentismos_ia`). Estas carpetas son el respaldo documental.

## Notas

- **Datos personales (Ley 1581):** los documentos son datos de salud. Todo es local, sin
  copias a internet. Los nombres de archivo conservan la cédula y las carpetas el nombre de
  la persona → mantener ACL/cifrado sobre este volumen y no compartirlo por fuera.
- El contenido de esta carpeta **no se versiona** (solo la estructura). El escenario de
  demo se regenera con `python scripts/sembrar_demo.py`.
- Si vienes del árbol anterior (`inbox/`, `procesados/`, `incompletos/`, `cuarentena/`):
  `python scripts/migrar_estructura_ingesta.py`.
