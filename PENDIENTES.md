# PENDIENTES — inventario real

Fecha de corte: 2026-09-02. Proyecto: middleware local de lectura de incapacidades (Gruppo).

Cómo leer este documento:

- **Sección 1** es lo que hay que pedirle al cliente. Está escrita para que Diana la entienda sin
  jerga técnica y agrupada en 6 peticiones, no en 22 mensajes.
- **Sección 2** son decisiones que necesitan a las dos partes; cada una lleva nuestra recomendación
  y qué pasa si se decide lo contrario.
- **Sección 3** es nuestro trabajo, ordenado por impacto.
- **Sección 4** son contradicciones internas del repositorio: hay que arreglarlas antes de que el
  cliente cite una cifra equivocada.
- **Sección 5** es lo que NO es pendiente, para que nadie lo vuelva a levantar.

Conteo: **22 del cliente · 13 conjuntos · 36 nuestros** (71 abiertos). 1 candidato se verificó como
ya cerrado y está en la sección 5.

Sin datos personales: los documentos del corpus se citan por seudónimo (FALSA-nn / REAL-nn) o por su
hallazgo. Nunca por nombre ni cédula.

---

## 1. Lo que necesitamos del cliente

### Petición A — Acceso de lectura al ERP y un volcado de 6 listados

**Es la petición que más desbloquea de toda la lista.** Sin ella el sistema lee los documentos
correctamente pero no puede registrar nada: hoy todo escribe en una base de datos de juguete con ~30
filas de prueba, y la única forma de correrlo es en modo simulación.

| Qué se pide | Para qué sirve | Qué se desbloquea |
|---|---|---|
| **A1.** Datos de conexión a la base de datos real del ERP (servidor, puerto, nombre de base, usuario, clave) y decir si vive en el mismo equipo, en la misma red o remota. Permiso de lectura sobre los listados de abajo y de escritura sobre las dos tablas del middleware. (C3) | Es el interruptor que convierte la demostración en piloto | Cualquier corrida real. Hoy solo funciona en simulación |
| **A2.** El **listado de personal** vigente: código interno de empleado, cédula, nombre completo y EPS. Puede venir tal cual sale del ERP; el sistema descarta solo las filas sin código o sin nombre. Decidir además si nos pasan un volcado periódico (cada cuánto) o consultamos en vivo. (C4) | Es el cruce cédula → empleado, que es obligatorio para poder registrar la fila. También es lo que corrige los nombres que el OCR devuelve pegados y lo que nombra la carpeta de cada persona | Sin esto **ninguna** cédula resuelve y los ~7.000 casos/mes caen a "datos por revisar", que es exactamente el trabajo manual que el proyecto elimina |
| **A3.** El **listado de diagnósticos que usa el ERP** (código y descripción; si existen, estado/activo y fecha de modificación), en CSV. Más tres precisiones: ¿hay códigos de 3 caracteres?, ¿usan la "X" de relleno colombiana (A09X, R50X) o guardan A09 a secas?, ¿hay códigos retirados y de qué año son las descripciones? (C1) | Permite responder "¿este diagnóstico está en el catálogo que usa Gruppo?" en vez de "¿existe en la CIE-10 pública?" | 2 de las 8 señales de fraude que el propio cliente declaró (hoy valen 0). Hay 3 documentos marcados por Gruppo con "no existe el diagnóstico" que hoy no podemos ni confirmar ni refutar. Al llegar, solo hay que cargarlo: no hay que cambiar código |
| **A4.** El **listado de EPS y ARL** (código interno, nombre, NIT, si es EPS o ARL) y el **listado de estados de recepción** (código y nombre). Y confirmar si existe una entidad tipo "SIN IDENTIFICAR" para cuando no se reconoce la EPS del paciente. (C6) | Son códigos que se copian tal cual en los ~7.000 registros/mes | Hoy, cuando no se reconoce la EPS, se escribe el código 1, que en el ERP real es una EPS concreta y no la del paciente. Y los códigos de canal (original / WhatsApp / correo) que usamos son inventados: están marcados en el código como "confirmar" |
| **A5.** El **listado de niveles de incapacidad** tal cual está en el ERP (`SELECT` de la tabla). Hay tres entradas que se leen igual — "NO APLICA", "NO APLICA." y "NO APLICA.." — y hoy le asignamos una distinta a cada tipo de ausentismo sin saber por qué. (C21) | Es otro campo que se copia al ERP en los ~7.000 registros/mes | Ya está estudiado que el nivel **no se puede deducir** del documento (el mismo diagnóstico aparece con niveles distintos y los rangos de días se solapan). O lo pone un valor por defecto acordado, o el auxiliar lo teclea 7.000 veces al mes |
| **A6.** El **histórico de ausentismos ya radicados**: certificados iniciales (no prórrogas) de los últimos 2 años o más, mínimo 5.000 filas, con días, diagnóstico, tipo, prórroga, ausentismo inicial, EPS/IPS emisora y fecha de radicación. **Sin nombres ni cédulas**: basta un identificador de empleado anonimizado para poder agrupar por persona. Y un usuario de solo lectura (o una vista) para consultar en caliente. (C2) | Es lo que permite decir "este emisor nunca ha expedido así" en vez de aplicar un umbral inventado por nosotros | 3 de las 17 reglas de fechas (solapamiento de incapacidades y prórroga sin antecedente) que están escritas y probadas y hoy apagadas por falta de acceso; el control central de "los días no cuadran con el diagnóstico" (hoy sin insumo en 31 de 31 casos); y la calibración de todos los umbrales contra radicaciones ya pagadas |

**Advertencia honesta que hay que decirle al pedir A6:** ya estudiamos ese histórico para otra cosa
(deducir el nivel de incapacidad) y la conclusión fue que ni los días ni el diagnóstico separan
limpiamente. Puede que la señal no exista. Por eso ese control nace apagado: si al probarlo marca
más del ~1% del propio histórico del cliente, no se enciende.

**Lo que ya NO hay que preguntar en A6** (para no parecer desinformados): los nombres de las columnas
del histórico y la convención de la fecha de vencimiento **ya están confirmados** — el esquema real
lo envió Diana el 11 de junio y está en disco, en la carpeta del cliente
(`/c/Projects/Vivetori/ocr/Mentoria Diana/Solucion Middleware IA SST/middleware-ia-gruppo/sql/01_tabla_erp_lpausentismos.sql`),
y ese mismo archivo anota que el vencimiento = inicio + días, que es justo lo que implementa nuestro
código. Lo que sí queda abierto de ese tema es otra cosa, y está en la petición D (C10).

**Lo mismo con la tabla de registro del middleware:** el diseño que propusimos ya se le entregó y
está en su carpeta (`.../middleware-ia-gruppo/sql/03_staging_y_alertas.sql`). La pregunta exacta no es
"pásanos el diseño" sino **"¿se creó tal cual en el ERP, o cambió algo? Si cambió, mándanos el
`SHOW CREATE TABLE`"**.

### Petición B — Los números que deciden qué servidor comprar

Todo esto va en un solo correo. Hoy son supuestos nuestros declarados y sostienen la compra.

| Qué se pide | Para qué sirve | Qué se desbloquea |
|---|---|---|
| **B1.** ¿Los 7.000 al mes son **trámites** o **archivos**? (C7) | Si son archivos, la CPU necesaria se parte por dos | Junto con B2 mueve el disco a 5 años entre 186 GB y 648 GB: entre un disco de 250 GB y uno de 1 TB |
| **B2.** ¿Cuántos documentos trae en promedio un trámite además de la incapacidad? (hoy asumimos entre 1,0 y 2,1) (C7) | Es el multiplicador del volumen de archivos | Igual que B1 |
| **B3.** ¿Cuántos **años hay que conservar el original** del soporte? Un número firmado por jurídico o SST. Hay tres plazos en tensión (soportes de nómina, historia clínica, prescripción del cobro a la EPS) y dan resultados muy distintos. (C9) | Es lo que decide la compra del disco | 3 años ≈ 194-206 GB · 5 años ≈ 324-337 GB · 15 años ≈ 971 GB. Decide entre 250 GB y 1 TB, y sin ese número no se puede escribir la política de borrado |
| **B4.** ¿Cuántos **empleados distintos** generan esos trámites? (C7) | Decide el número de carpetas del árbol | ~36.000 carpetas/año con 3.000 personas, ~180.000 a 5 años: es el coste del respaldo y del antivirus |
| **B5.** El conteo de radicados **por día de la semana** de un mes cualquiera. (C7) | El factor de día pico 2,5× es un supuesto nuestro | Decide si el tope de 500 casos por corrida se rompe todos los lunes o nunca |
| **B6.** ¿Hay que **cargar histórico** y de cuántos meses? (C7) | Un año de histórico son 199-222 horas de CPU | Decide si hace falta procesamiento en paralelo antes de arrancar (8,3 días con un proceso frente a 50 h con cuatro) |
| **B7.** ¿Qué porcentaje del volumen son **permisos escritos a mano**? (C7) | El lector automático lee muy mal el manuscrito; el modelo de visión cuesta 39-78 h de reloj al mes si se aplica a los 7.000 | Decide si hace falta tarjeta gráfica |
| **B8.** ¿Cuánto pesa una epicrisis escaneada típica? (hoy medimos 384,7 KB sobre 29 documentos) (C7) | Afina el cálculo de disco | — |
| **B9.** El reparto por **tipo de ausentismo** de un mes (enfermedad general, accidente, maternidad…). (C7) | Hoy es un supuesto | Afina CPU y el reparto de requisitos documentales |
| **B10.** Dos preguntas operativas: ¿a qué hora empieza a revisar el auxiliar?, ¿se acepta que la corrida nocturna use solo reglas y el auxiliar escale a mano los casos difíciles? (C7) | Fija la ventana horaria de la corrida | — |
| **B11.** ¿De cada 100 incapacidades radicadas, cuántas resultan adulteradas? Y ¿qué cuesta más: pagar una falsa que pasó, o retener el pago de una legítima durante N días? (C15) | Sin estos dos números el umbral de sospecha es una preferencia nuestra, no una decisión de negocio | El corpus que tenemos es ~50% adulterado y la realidad probablemente está dos órdenes de magnitud por debajo. Un motor calibrado sobre 50% se ahoga en falsas alarmas cuando la tasa real es 0,5% |
| **B12.** ¿Cuántos casos al día puede revisar el auxiliar? (C15) | Se lo pedimos como capacidad, no como calibración: **dennos la capacidad y nosotros fijamos el umbral que la respeta** | Dimensiona la cola de revisión |

### Petición C — Más documentos para poder dar cifras defendibles

Hoy el corpus tiene 31 documentos y **no sirve para calibrar ni para prometer precisión**; sirve para
descartar controles malos (ya descartó varios) y como prueba de no-regresión.

| Qué se pide | Para qué sirve | Qué se desbloquea |
|---|---|---|
| **C1.** **100 o más documentos confirmados legítimos**, en PDF exportado desde Word (no escaneo ni foto), del flujo en que un auxiliar rellena una plantilla y la exporta, típicamente con dos o más tipografías en la misma página. De titulares y emisores distintos (dar un número, no "variados"). (C14) | Ese flujo es **exactamente** el generador de falsas alarmas del control de tipografías, que sostiene el 42% de la detección de esa familia — y el corpus no contiene ni uno | Sin ellos no podemos anticipar cuánto ruido va a generar ese control en producción |
| **C2.** **20 o más adulterados por señal**, con prioridad en las cuatro que hoy tienen 1 o 0 ejemplos: tipografía mixta (0 utilizables), días incoherentes con el diagnóstico (1), fechas incoherentes (1), formato del diagnóstico (1). (C14) | Los 15 adulterados actuales salen de solo **5 titulares**: a nivel de titular la detección real es 4 de 5, no 7 de 12 | Cualquier compromiso de precisión o de detección. Un informe que dice "1 de 1 detectada, 100%" con un solo caso no afirma nada |
| **C3.** **5 a 10 trámites reales** donde la incapacidad venga dentro de un paquete escaneado de 10-30 páginas (epicrisis, historia, cédula). Criterio: que en al menos 2 la incapacidad **no** esté en la página 1, y que vengan tal como los recibe recepción, sin recortar. (C23) | El corpus no tiene ni uno: todos los multipágina son de 2 páginas | Fija el tiempo máximo de proceso por documento. Un valor calculado sobre "el peor documento medido" reencolaría un paquete legítimo a mitad de proceso y duplicaría el registro |
| **C4.** Resolver **3 contradicciones de etiquetado** que afectan a 5 documentos (16% del corpus): una pareja de archivos idénticos entregada a la vez como adulterada y como legítima; otra pareja idéntica (¿archivada dos veces por error, o radicada dos veces por el trabajador?); y un archivo que comparte cédula con un legítimo pero con contenido distinto. Y la pregunta de fondo: **¿la carpeta de legítimos significa "verificado legítimo" o "no se detectó nada / no se revisó"?** (C13) | Mientras no se resuelva, **ningún porcentaje del motor es defendible**: en una pareja contradictoria el motor falla 1 de 2 responda lo que responda | Devuelve 5 documentos a toda métrica, incluido el único ejemplo de tipografía mixta y con él dos controles deterministas y sin umbrales, hoy con 0 disparos. Nuestra recomendación sobre la primera pareja: es **adulterado**, con evidencia de dos familias independientes (19 rectángulos blancos opacos sobre la imagen, 4 objetos de texto semitransparentes estampados al final en esas mismas coordenadas, herramienta de creación distinta a la de modificación, fecha de modificación 50 días posterior, y una contradicción aritmética de fechas comprobable sin OCR) |
| **C5.** Por cada uno de los 15 adulterados, **cómo se confirmó**: (a) lo dedujo el analista mirando el documento, (b) la EPS o la IPS negó haberlo expedido, (c) el médico o su registro no existe, (d) el trabajador lo admitió, (e) sigue en investigación. Como campo, no como texto libre. Y para las dos rachas marcadas en rojo: ¿el analista verificó el mismo defecto en cada documento, o marcó la racha completa por ser el mismo trabajador? (C16) | Una vía externa (b/c/d) vale más que cualquier control nuestro: es verdad dura y **cambia el diseño**, no el umbral | Los 5 documentos que hoy ninguna familia marca son justo donde el motor no puede opinar; saber cómo los cazó un humano es lo único útil ahí. Y si alguna fila sigue en investigación, ese documento debería salir de la clase "adulterada" hasta que se cierre |
| **C6.** El **Excel original** de la tabla de motivos (hoy solo tenemos un pantallazo que hubo que leer por OCR). (C19) | Los 15 motivos —nuestro único registro de verdad sobre qué se falsificó— están transcritos a mano desde una imagen y no se pueden verificar. Con el Excel se validan sin volver a leer nombres de pacientes por OCR | Ya **no** es bloqueante: el significado del rojo y el orden de las filas están resueltos. Es deseable |
| **C7.** Que los próximos lotes de corpus lleguen con el **mismo patrón de nombre en las dos clases**, o con la etiqueta en un archivo aparte y los documentos con nombre neutro (nosotros especificamos la convención). (C19) | Hoy las dos clases usan convenciones distintas: un clasificador que **solo lea el nombre del archivo** acierta el 100% sin abrir el documento | Esto **sí** bloquea cualquier medición futura, y nos obliga a auditar que ninguna sonda toque el nombre |

### Petición D — Preguntas de operación y de norma (respuestas cortas, alto efecto)

Cada respuesta se aplica cambiando un parámetro en la base de datos, **sin volver a instalar nada**.

| Qué se pide | Para qué sirve | Qué se desbloquea |
|---|---|---|
| **D1.** *(la más urgente)* Cuando el papel imprime los días **y** la fecha de fin y no cuadran, **¿qué manda: los días o la fecha de fin?** (C12 / P3) | Hoy el sistema decide en silencio que mandan inicio + días y **reescribe** la fecha de fin | Si la respuesta es la contraria, hay un defecto que está escribiendo un dato equivocado en nómina **hoy mismo**. Va primero y con un ejemplo del corpus delante |
| **D2.** ¿Hay alguna EPS o IPS que en "Fecha Fin" imprima el **día de reintegro** en vez del último día incapacitado? Si existen, cuáles. Y una muestra de 20-30 documentos por EPS grande **que impriman las tres cosas: inicio, fin y días**. (C10) | Es el riesgo abierto más caro del motor de fechas | Si existe un emisor así, el control de fechas (que bloquea la aprobación) marcaría el **100% de sus documentos legítimos** con un día de desfase y ahogaría la cola con 7.000 casos/mes. No preguntamos a ciegas: ya medimos 4 documentos legítimos con las tres cosas impresas y los 4 dan desfase 0. Pedimos confirmar o desmentir un indicio con n=4. La muestra hay que pedirla con el criterio explícito de las tres patas, porque hoy solo la mitad del corpus las trae |
| **D3.** ¿En **cuántos días hay que radicar** una incapacidad ante la EPS para que se pague, desde qué fecha se cuenta (inicio, expedición o entrega a RH), hábiles o calendario, y varía por EPS? Dato para arrancar: dos documentos del corpus imprimen "favor tramitar antes de 72 horas", pero es una instrucción del emisor, no una norma. (C11a — ver también la sección 2) | Es un control de **dinero**, no de fraude: un documento legítimo radicado tarde no es falso, pero ya no se cobra | Hoy ese control solo avisa, y con el umbral actual cualquier documento de menos de 2 años pasa sin señal |
| **D4.** ¿Es **normal** que el certificado se expida después de que la incapacidad empezó? (C11b) | Hoy toleramos 0 días de expedición posterior por suposición nuestra | El rótulo aparece en 13 documentos del corpus: si es normal, se sube el umbral y desaparece el ruido |
| **D5.** ¿Una incoherencia de fechas permite aprobar tras confirmar el papel, o se devuelve siempre? (C12 / P2) | Define si ese control bloquea o solo avisa | — |
| **D6.** ¿Puede un empleado tener **dos ausentismos a la vez** (accidente de trabajo + enfermedad general)? (C12 / P4) | Define la severidad del control de solapamiento | Si no puede, el solapamiento pasa de aviso a grave |
| **D7.** En vacaciones de varios periodos, ¿se registran los días **sumados** o el rango completo? (C12 / P9) | Hoy el rango se come los huecos entre periodos y ninguna regla lo ve | — |
| **D8.** ¿Qué **topes de días por tipo** aplica su nómina (maternidad, paternidad, luto) y quién los valida hoy? (C12, parte reasignada) | *No preguntamos de dónde sale el tope de 540 días: ese número lo pusimos nosotros y su origen normativo lo comprobamos nosotros* | — |
| **D9.** Aprobar las **10 filas de requisitos documentales internos** por tipo de ausentismo (p. ej. maternidad = incapacidad + historia clínica + nacido vivo o registro civil). (C22a) | Es lo que decide si un caso sale "incompleto" y genera una alerta al equipo de recepción | Con 7.000 trámites/mes, un requisito de más produce miles de alertas falsas y el equipo deja de mirarlas. El plan lo tiene escrito literalmente como "valores a confirmar con Diana". No se pueden deducir de sus datos: los tipos permiso y vacaciones no existen en su checklist de radicación |
| **D10.** Sobre el listado de radicación ante EPS que ya nos dieron (64 EPS, 19 con checklist, 133 combinaciones, 320 requisitos): las **45 EPS que vienen vacías**, ¿no exigen nada o no están configuradas todavía? ¿Qué significa el par "tipo de envío = 0 y medio = 0" (aparece en 56 de las 133 combinaciones y siempre juntos)? ¿Y "archivo = 0" (45 de las 320 filas, junto a documentos que sí se exigen)? (C18) | Para esas 45 EPS —el 70% del catálogo— hoy usamos una lista genérica nuestra | Si la respuesta es "no configurado", estamos exigiendo documentos que esa EPS nunca pidió y el aviso llega a recepción para que persiga un soporte inexistente. **Caso concreto que hay que mandarle:** hay una combinación con "tipo de envío = 0" que **sí** exige 5 documentos repartidos en 3 archivos, así que ese 0 no puede significar "no se radica" |
| **D11.** ¿Existe (o quién construye) el proceso del ERP que toma las filas **aprobadas** por el auxiliar y crea el ausentismo real? Tres preguntas, no una: ¿existe?, ¿por qué campo decide que una fila está pendiente de promover?, ¿dónde marca que ya la promovió? (C5) | Es el último eslabón del circuito. En nuestro repositorio se da por supuesto en 12 sitios de 9 archivos y no hay ninguna evidencia de que exista | Si no existe, el auxiliar aprueba y **no pasa nada en el ERP**: el proyecto entrega una bandeja de revisión, no automatización. Y la tabla de registro **no tiene ninguna columna para marcar que una fila ya se promovió**: un proceso que solo filtre por "aprobado" duplicaría el ausentismo en cada corrida |
| **D12.** ¿Gruppo tiene o puede tener acceso al **registro nacional de talento humano en salud** (RETHUS), aunque sea consulta manual? Sí/no + quién consultaría + en qué casos. (C20) | Es el único camino para pasar de "el sello se contradice con el texto" a "ese profesional no existe o no estaba habilitado" | Si la respuesta es no, **retiramos** ese control del alcance publicado en vez de dejarlo como promesa. Hoy solo ve contradicciones internas y es evaluable en 1 de 26 documentos, aunque el cliente declaró 2 casos de firma médica entre sus 15 adulterados |
| **D13.** Firma con **nombre, área y fecha** de la tabla de mínimos legales de días por diagnóstico (aborto o parto prematuro no viable: 14 a 28 días; maternidad: 126-140 días, 20 semanas si es múltiple). Si alguna cifra cambió, la nueva. (C17) | Es el único control de esa familia que es una norma y no una heurística | **Margen cero:** un documento legítimo del corpus trae exactamente el mínimo legal, así que un dígito mal leído (4 donde hay 14) produce una alerta sobre una incapacidad por aborto — el peor documento posible para equivocarse. Sin firma con nombre y fecha no se puede defender ante un reclamo. Orden correcto: primero nosotros sacamos la tabla del código a un archivo fechado, después se firma **ese** artefacto. Aviso: hoy ese control **no está en producción**, así que es habilitación, no incendio |

### Petición E — Infraestructura y seguridad (para TI, no para Diana)

| Qué se pide | Para qué sirve | Qué se desbloquea |
|---|---|---|
| **E1.** ¿El servidor tendrá **TPM** (o TPM virtual si es máquina virtual)? (C8) | Sin TPM **no se puede** tener cifrado del disco y reinicio desatendido a la vez | Es un requisito de **compra**, no de configuración: si no hay TPM hay que cambiar el servidor |
| **E2.** ¿La política de TI permite **virtualización** (Hyper-V)? (C8, y ver J1) | Los tres componentes del sistema son contenedores Linux | Si es Windows Server, la única variante sin un "pero" estructural es Windows como anfitrión + máquina virtual Linux de autoarranque, y hay que sumar 4-6 GB de RAM solo para el anfitrión |
| **E3.** ¿Existe política de **respaldo local** (no en la nube)? ¿Con qué herramienta? (C8, J11) | Un respaldo en la nube rompería el "100% local" y es el escenario de fuga de datos personales más probable del diseño: la cédula va en el nombre del archivo y el nombre de la persona en la ruta | El árbol de documentos es el **único** dato irremplazable del servidor |
| **E4.** ¿Quién queda con permiso de administración de contenedores? (C8) | Equivale a acceso total a todos los datos de salud del sistema, y hoy no está documentado en ningún sitio | Control de Ley 1581 |
| **E5.** **Exclusión del antivirus en tiempo real** sobre la carpeta de entrada, búsqueda de Windows desactivada en esa ruta, **más un escaneo diario programado en modo alertar, no borrar**, con una persona que lea la alerta. (C8) | No se pide por rendimiento (medido: el antivirus cuesta 8,3 min/mes, el 1,2% del coste de lectura) sino porque **la cuarentena de un PDF destruye la única copia de un soporte legal y pasa en silencio** | Los archivos llegan de WhatsApp y correo, así que quitar el antivirus sin escaneo programado cambia un riesgo por otro |
| **E6.** **Cifrado del disco de datos antes de escribir el primer documento** y permisos de la carpeta. (C8) | Control de Ley 1581 sobre datos de salud | Aprobación de seguridad y legal |
| **E7.** Confirmar **dónde vive la base de datos del ERP** respecto del servidor (mismo equipo, misma red, remota). (C8 / C3) | La latencia de la base **no se ha medido**; con base remota y varios procesos en paralelo puede dejar de ser despreciable | Decide si hay que medirla antes de fijar el paralelismo |

---

## 2. Decisiones conjuntas

**J1 — El servidor: sistema operativo y perfil de hardware.** *(prioridad media-alta; es la precondición
de todo el despliegue)*
Del cliente: ¿Linux (Ubuntu Server LTS / RHEL) o Windows Server?, quién lo administra, y si permiten
virtualización. Nuestro: ejecutar la prueba de aceptación — reiniciar en frío **sin iniciar sesión**,
esperar la hora programada y comprobar que la corrida movió documentos.
**Recomendación: Linux x86-64 con Docker como servicio del sistema.** Ahí no hay que escribir ningún
artefacto nuevo (basta habilitar el servicio y la política de reinicio que ya está en el archivo de
composición); lo único que falta en todos los caminos es ejecutar la prueba y dejar constancia.
**Si se decide Windows Server:** los tres componentes son contenedores **Linux** y Windows no los
ejecuta nativamente; la variante viable es Windows como anfitrión de virtualización + máquina virtual
Linux, con la carpeta de entrada **dentro** del disco virtual (no en un recurso compartido del
anfitrión), y 4-6 GB extra de RAM. El caso típico de fallo es Docker Desktop, que solo levanta el
motor cuando un usuario inicia sesión: si el contenedor no está vivo tras el reinicio, **no hay
corrida nocturna y nadie se entera**. Si además se descarta Docker, aparece un entregable nuestro
(N36).
Elegido el sistema operativo se elige entre el perfil mínimo (4 núcleos / 16 GB / 250 GB ≈ 3 años) y
el recomendado (8 núcleos / 16 GB / 500 GB NVMe ≈ 5 años).

**J2 — Cómo llegan los documentos a la carpeta de entrada, dónde vive y con qué permisos.**
*(prioridad media; es el único punto de escritura manual de todo el flujo)*
Reparto explícito, para que el cliente no reciba las tres cosas como suyas:
(a) **Cliente puro:** la vía concreta de cada uno de los tres canales (carpeta compartida, buzón de
correo con reglas, bot, escáner en red, exportación manual) y quién opera cada canal. La guía lo deja
literalmente como "se define en la implementación".
(b) **Conjunto:** el cliente da el disco y la ruta y TI los permisos; nosotros cambiamos el enlace de
carpeta, que hoy está cableado a una ruta del repositorio, y añadimos la variable que hoy no existe.
(c) **Mitad y mitad:** la comprobación de longitud de ruta, los permisos y una escritura de prueba
desde el contenedor son nuestros + TI en la instalación; pero **el patrón de escritura atómica en
origen (escribir con extensión temporal y renombrar al terminar) hay que exigírselo a quien escriba
en la carpeta**, y no es cosmético: el proceso de hoy no valida que el archivo esté completo, así que
sin ese patrón leerá documentos a medias.
**Si no se acuerda:** alguien tiene que copiar ~14.700 archivos/mes a mano, y si el contenedor no
puede escribir en la carpeta el sistema registra en la base y **no** mueve los archivos → la corrida
siguiente duplica las filas (ver N1).

**J3 — Validar la convención de nombres con el equipo de recepción, con una muestra real.**
Del cliente: que quien recibe nombre **20-30 documentos reales** con la convención
`cedula_TIPODOC[_NN].ext` (un documento por archivo, sin fecha, misma cédula para todo el trámite) y
nos los pase para medir cuántos llegan bien nombrados; **quién** renombra (el trabajador, el auxiliar
de recepción, alguien distinto por canal); y que el equipo confirme que puede sostenerlo a 7.000/mes.
**Corrección respecto a lo que se creía:** los 16 tipos de documento de la guía **sí** resuelven todos
en el código; ya no hay incompatibilidad de vocabulario. Lo que queda es nuestro: el patrón solo
acepta letras, así que la grafía natural con guion bajo (`..._HISTORIA_CLINICA.pdf`,
`..._CERTIFICADO_LABORAL.pdf`, que son los códigos canónicos del propio código) **no** se reconoce y
el archivo cae a "mal nombrados". O toleramos el guion bajo, o la guía lo advierte explícitamente.
**Si no se valida:** con 7.000/mes, un 10% mal nombrado son 700 renombrados manuales al mes, que es
justo el trabajo que el proyecto elimina.

**J4 — Cómo se nombra un segundo ausentismo del mismo empleado en el mismo lote.** *(prioridad media;
es pérdida de dato, no ruido)*
Hoy la llave de caso es **la cédula sola**, así que dos trámites del mismo empleado en la misma
entrada se agrupan en un solo caso: se lee **uno** y se registra **una** fila; del segundo solo queda
una nota de texto. Medido en el corpus: 31 documentos colapsan a 27 casos → 3 cédulas afectadas
(~11% de los casos), y del segundo trámite **no queda fila** en la tabla de registro.
Del cliente, solo tres respuestas: ¿pasa seguido?, ¿con qué dato distingue el área dos trámites del
mismo trabajador (fecha de inicio, número de orden, radicado)?, ¿se parten automáticamente o los
revisa el auxiliar? Nosotros cambiamos la llave y el agrupado.
**Recomendación:** partirlos por la fecha de inicio leída y, si no se puede leer, mandar el caso a
revisión. **Si se decide no partirlos:** hay que aceptar que el segundo trámite se teclea entero a
mano, y las prórrogas y las incapacidades consecutivas son cotidianas.

**J5 — Aplicar en el ERP el diseño de tablas de producción del middleware.**
Nuestro: un script que cree o actualice **solo** lo del middleware — la tabla de registro con sus
cuatro columnas de fechas, la tabla de alertas documentales, las dos tablas de configuración de
reglas, las tres columnas de sospecha de manipulación y el índice por severidad. Hoy las piezas están
repartidas entre dos archivos con coberturas distintas y **ninguno es aplicable tal cual**: uno es el
esquema de demostración (crea catálogos e inserta datos de prueba, y solo corre en el primer arranque
de un volumen vacío) y el otro cubre únicamente la parte de fechas. Del cliente: que el DBA lo
aplique y confirme.
**Si faltan las cuatro columnas de fechas, el registro FALLA**, así que el primer lote deja los
~7.000 casos/mes en la carpeta de error.

**J6 — Contra qué fecha se mide "empieza en el futuro" y "empezó hace mucho".**
Del cliente: ¿se van a reprocesar lotes históricos y de cuántos meses?; ¿existe una fecha de
**recepción** del archivo que podamos usar, y es fiable la fecha de llegada, o RH copia lotes viejos
(lo que destruye esa fecha)?; ¿el control de "inicio en el futuro" se queda bloqueando la aprobación
o baja a solo aviso? (esta última es en rigor conjunta: quien asume el riesgo de aprobar sin bloqueo
tiene que aceptarlo).
**Cuantificado sobre los 14 documentos legítimos del corpus, variando solo la fecha de "hoy":** ese
control marca 10 de 14 con hoy = 2025-01-01, 8 de 14 con 2026-05-01 y 0 de 14 con la fecha actual
(57-71%). Reprocesar un lote viejo, o un contenedor con el reloj mal puesto, mandaría hasta el 70% de
los documentos legítimos a revisión sin que nada esté mal. Se agrava con el defecto de zona horaria
(N16): el contenedor corre en UTC.
Nuestro: la fecha es inyectable de "procesar un caso" hacia abajo, pero la función que drena el lote
**no** la recibe y la fija una sola vez para toda la corrida; hay que exponerla y **resolverla por
caso**. Cuidado con el nombre: "recepción" ya existe en el sistema, pero es el **canal**
(WhatsApp/correo/ventanilla), no una fecha.
**Recomendación:** usar la fecha de recepción por caso y dejar el control bloqueando.

**J7 — ¿La bandeja se usa solo en el servidor o desde la red interna?**
**Recomendación: solo en el servidor** (escritorio remoto). Si es así, no hay nada que construir y se
cierra con una línea en el manual de operación.
**Si se abre a la red:** la aplicación **no tiene ninguna autenticación**, así que cualquiera que
alcance el puerto lista todo el registro, abre documentos, aprueba y rechaza — datos de salud de
~7.000 personas/mes sin credenciales en la red interna (Ley 1581). En ese caso N27 pasa de pendiente
a bloqueante (proxy con TLS + autenticación + validación de contenido).
**Aviso importante:** el "hoy solo escucha en el propio equipo" vale **solo para el camino con
Docker**. La instalación sin Docker que documenta nuestro README arranca escuchando en todas las
interfaces, así que si el cliente instala nativo **la decisión ya está tomada por omisión y a favor de
lo peor**. Hay que decírselo así.
Segundo punto: el vaciado de la base de prueba **sí** tiene una guarda, pero el botón de reiniciar
**mueve archivos sin ninguna guarda**: cualquiera que alcance el puerto puede devolver documentos del
archivo a la entrada y forzar reprocesamiento.

**J8 — Repetir la medición de rendimiento en el servidor definitivo.**
Nuestro el script y la ejecución; del cliente la máquina, la base y la ventana de mantenimiento.
Todas las cifras publicadas vienen de un portátil de 15 W con núcleos heterogéneos y bajo contención
(90-94% de la CPU en otros procesos), y el mismo documento varió ×1,55 (mediana) y hasta ×2,86 entre
dos pasadas: **los perfiles son un orden de magnitud (~10 segundos de CPU por documento y núcleo), no
un compromiso de servicio.** Hay que medir además lo que nadie midió: el escalado real del paralelismo
(sembrar ~200 documentos y correr con 1, 2, 4 y 8 procesos; el descuento del 25% es un supuesto), el
modelo de visión en CPU y en GPU (los únicos números son de junio de 2026), el tiempo de ida y vuelta
de una consulta al ERP con varios procesos, el sobrecoste del enlace de carpeta y los paquetes
multipágina profundos.
**Nota de orden:** medir "un hilo" hoy mide una configuración que el producto **no puede producir**
(el tope de hilos solo existe dentro del banco de pruebas, no en el paquete), así que N12 tiene que ir
antes o junto con la medición.

**J9 — ¿La cédula del nombre del archivo es la verdad del trámite?**
Está **medido**: en 4 de 31 documentos el lector confunde la cédula del paciente con otro número del
formato (la del médico, un número de orden). Si la llave de paciente se infiere mal, **todo** el
bloque de controles de reuso de firmas y membretes fabrica acusaciones espurias ("misma firma entre
pacientes distintos" cuando es el mismo paciente); en el corpus hubo que reconstruir la llave a mano.
Cómo preguntarlo bien: la convención vigente es `cedula_TIPO[_NN]` **sin fecha** (la versión con fecha
que citan algunos informes está obsoleta). Y el comportamiento ante discrepancia **ya está construido
y probado** (el caso va a revisión, no se rechaza): hay que **mostrárselo** y pedir confirmación, no
preguntarlo en abstracto.
**La pregunta que sí está sin resolver:** en una discrepancia, **¿qué cédula queda en el registro?**
Hoy queda la del OCR y la carpeta se nombra con la del archivo → dos verdades distintas para el mismo
caso.
**Recomendación:** manda el nombre del archivo (viene de recepción) y el caso va a revisión.
**Si mandara el OCR:** los controles de reuso cruzado no pueden ser bloqueantes, bajan a aviso.

**J11 — Definir y probar el respaldo local del árbol de documentos.**
**Nuestra parte ya está hecha** (procedimiento escrito, con tiempos de restauración medidos en NTFS:
11.000 archivos creados en 23,3 s). Lo que queda es casi todo del cliente: confirmar que existe
política local, elegir la herramienta de su parque, configurarla sobre el árbol **por instantánea de
volumen** (no fichero a fichero: son 176.400 archivos/año y ~882.000 a cinco años) y **ejecutar una
restauración de prueba contando archivos**. Lo nuestro que falta es pequeño y conviene entregarlo con
la petición: el comando exacto de conteo posterior a la restauración.
**Antes de mandar cifras hay que cuadrar una inconsistencia nuestra:** un documento dimensiona con
14.700 archivos/mes y otro con ~11.000. Mandarle dos volumetrías del mismo árbol nos deja mal.
La base de datos de contenedores no contiene nada de valor en producción (la base es el ERP) y el
volumen de modelos se reconstruye descargándolos: **el árbol de documentos es lo único irremplazable.**

**J12 — Monitoreo: qué se vigila y a quién le llega la alerta.**
Del cliente: el destinatario y el canal, y si ya tienen herramienta corporativa de monitoreo.
Nuestro: el chequeo (los dos endpoints ya sirven de sensor; falta disco, "la corrida no ocurrió" y el
umbral de acumulación en la entrada). Umbrales ya calculados: disco al 20% libre (crecimiento
5,4 GB/mes de documentos + 6,54 GB del volumen de modelos si se usa IA), disco de contenedores (cada
reconstrucción deja capas huérfanas), servicio caído, corrida nocturna que no ocurrió, acumulación en
la entrada. **Y que la alerta la lea una persona.**
**Si no se define:** los fallos son silenciosos y el primer síntoma es que RH pregunta por
incapacidades que nunca se registraron.

**J13 — El título real de las cartas de vacaciones de Gruppo.**
Del cliente: el título exacto (o los títulos) que emite RH. **No existe ninguna carta de vacaciones
real en el corpus**: el patrón actual viene de un documento sintético que generamos nosotros.
Nuestro: relajar el patrón, que hoy exige simultáneamente las palabras "notificación" + "periodo" +
"vacaciones".
Verificado hoy: la tilde de "Período" ya se tolera, pero "NOTIFICACION DE VACACIONES", "PERIODO DE
VACACIONES" y "CARTA DE VACACIONES" siguen clasificándose como incapacidad → el registro sale sin
fechas y el tipo que llega al ERP pasa de vacaciones a enfermedad general.
**Riesgo que hay que decirle al cliente:** mientras no tengamos el título real, **vacaciones es el
único tipo de ausentismo cuyo soporte no está validado con un documento real.**

**C11a (reclasificado a conjunto) — El plazo de radicación.** El cliente da el plazo y desde qué fecha
se cuenta (y si es por EPS, para que vaya al catálogo por EPS y no a un valor global); **nosotros
tenemos que arreglar antes de qué fecha se mide**: hoy la antigüedad se mide contra la fecha de
proceso, no contra la de recepción (con la fecha de hoy el corpus real da 46-101 días, así que
cualquier umbral por debajo de ~100 marcaría los 14 documentos legítimos). Va en la misma
conversación que J6.

---

## 3. Nuestro trabajo pendiente

Ordenado por impacto. El esfuerzo es una estimación de ingeniería, no un compromiso.

### El siguiente paso con más retorno

**N1 — Cerrar la doble inserción en el registro.** Es el riesgo de corrección más caro del sistema y
lo que impide poner el lote en producción sin que un humano supervise cada corrida.
**Y el mínimo viable ya está casi escrito:** la regla de duplicado exacto existe, está probada y
consulta **nuestra** tabla de registro (misma persona + misma fecha de inicio + mismos días, ignorando
las rechazadas). Está apagada por una sola razón: falta el adaptador que le sirva los datos. El
veredicto se calcula **antes** de insertar, así que implementar ese adaptador y encender la regla da el
aviso previo al registro **sin escribir motor nuevo**. Y **no depende de la petición A**: consulta
nuestra tabla, no el ERP, así que no hay que esperar accesos.
Esfuerzo: **medio día** el aviso (N14); **2-3 días** la versión completa (tabla de control con
restricción única por caso+huella, y registro + cambio de estado en una sola transacción con
comprobación de propiedad).
Por qué duele: hoy el registro confirma fila por fila y el movimiento posterior del archivo **se traga
toda excepción** (registra el error y sigue). Si el registro se confirma y el movimiento falla, el
archivo se queda en la entrada **con la fila insertada** y la corrida siguiente inserta otra. No hay
umbral: es una probabilidad por archivo. A 14.700 archivos/mes, un 0,1% de fallos de movimiento son
~15 casos duplicados/mes. Vía garantizada: la política de reinicio del contenedor + un reinicio a
mitad del drenaje. Si el auxiliar aprueba los dos, el ERP promueve **dos ausentismos: se paga dos
veces la misma incapacidad.** Un permiso mal puesto en la carpeta lo dispara el día 1.

### Impacto alto

**N14 — Escribir el adaptador de histórico y encender el control de duplicados.** *(medio día)*
El gancho existe en el código y es la única aparición en todo el repositorio; la implementación no.
Precisión importante: el contrato tiene 4 métodos repartidos entre reglas distintas, y **encender el
control de duplicados requiere implementar uno solo**, contra nuestra tabla de registro. Los otros
tres son los que dependen del histórico del ERP (petición A6). Incluye un arreglo de documentación:
hoy tres sitios del repositorio (un comentario del código, el archivo de configuración de ejemplo y el
documento de validación temporal) afirman que las tres reglas esperan el acceso del cliente — es
cierto para dos y **falso** para la de duplicados. Mientras no se separe, cualquiera que lea el repo
—o el cliente— creerá que también espera a Gruppo.

**N2 — Publicar los 5 datos de procedencia que el motor ya sabe consumir.** *(1-2 días, cambios
aditivos; el motor no se toca)*
El techo del motor de fechas es la **cobertura de lectura**, no las reglas. Faltan: (1) las cadenas
**rechazadas** de fecha de inicio, fecha de fin y días — quien descarta el valor es el lector, que
acota los días a 1..540 y devuelve nada ante una fecha imposible, así que hay que escribir el original
además de anular el valor usable; (2) la marca de "los días los calculé yo"; (3) la marca simétrica
para la fecha de fin; (4) el día de la semana leído **anclado a su propia fecha** (la versión "por
posición" marca legítimos cuando el lector desordena las celdas); (5) la casilla "Prórroga: SÍ/No"
(clave `prorroga`, booleana).
Qué arregla, medido: un papel que imprime "Duración: 900 días" llega al registro con "no se detectó el
número de días" y el auxiliar sale a buscar un dato **que sí está impreso**; uno con "Fecha Inicio:
31/02/2026" se registra en silencio con la fecha derivada (reproducido: sale sin datos, cobertura 0,0
y cero hallazgos). Y quita el "cumple" tautológico de la regla estrella: un documento que solo imprime
las dos fechas sale coherente, la regla dice "cumple" y el informe afirma haber cruzado duración
contra rango **cuando el papel no imprimía ninguna duración**. Esa regla da "cumple" en 12 de 26
documentos y **4 de los 7 legítimos evaluables son tautológicos**. (4) y (5) encienden dos reglas más
que hoy están declaradas y apagadas — la casilla de prórroga la imprimen 9 de 31 documentos y hoy no
se lee ninguna. Rompe además una promesa escrita del catálogo: "el motor nunca debe decir que no
detectó un dato que el documento sí imprime".
Alcance: incluye **encender y medir** esas dos reglas.

**N3 — Arreglar los dos lectores de fechas.** *(2-3 días. Palanca de mayor impacto por unidad de
esfuerzo del frente de código.)*
(a) El lector de fechas escritas empareja el año **por posición** en todo el documento y no ordena las
dos fechas: hay que ordenarlas o abstenerse marcando "orden incierto", y usar la prueba libre de orden
(longitud del rango + 1 == días). (b) La vía en prosa "desde el X hasta el Y": las palabras *desde* y
*hasta* **ya** son anclas; lo que falta es concreto — el ancla "a partir de(l)" no existe y el patrón
de fecha **no admite año de 2 dígitos** (29-07-26). El lector que sí saca esa forma vive fuera del
paquete, en una sonda de análisis, y hay que portarlo con su guarda (aceptar el ensamblado solo si el
día de la semana impreso valida las fechas). (c) El patrón de respaldo de días no excluye el salto de
línea, así que "Duración"⏎"JUEVES 23 DE JULIO" se lee como **23 días**. Ya está medido que exigir la
misma línea **rompe** la forma legítima "DURACIÓN:"⏎"126", así que la salida es **vetar por contexto**
(rechazar el número si le sigue "DE \<mes\>"), no restringir el salto de línea. (d) Re-medir después.
Números: la regla estrella no es evaluable en 13 de 26 documentos (50%) y **en 10 de esos 13 la fecha
sí está en el texto leído**: el 77% de la ceguera es recuperable sin tocar el motor. El único documento
del corpus cuyo motivo declarado es "fechas incoherentes" sale hoy coherente, con cobertura 0,333 y
cero códigos, porque no se leen "MARTES 02 DE SEPTIEMBRE" ni "JUEVES 04 DE"; la sonda **sí** lo marca
y dándole las tres fechas a mano el mismo motor responde "revisar" + grave.
Dos precisiones honestas: los dos falsos positivos graves de (a) y (c) son **reproducibles**, no
"medidos" — nuestra propia métrica dice 0 de 14 falsos positivos sobre documentos reales, porque en
esos documentos el lector hoy no publica ninguna fecha. Y la re-medición **no** es porque el 13/26 sea
anterior a esa función (entró el 21 de julio y la medición es del 2 de septiembre, con la misma huella
del archivo): hay que re-medir porque el motor y el mapeador **sí** cambiaron después de esa corrida,
así que lo desactualizado son las métricas por regla, no la cobertura del lector.

**N7 — Construir y verificar de verdad la imagen, el paquete de traslado y la precisión del entorno de
producción.** *(2-3 días)*
El camino de producción **nunca se ejecutó de extremo a extremo**. Hay que: construir con el listado
de dependencias actual, medir los tamaños reales de imágenes y volúmenes, re-correr las pruebas
**dentro** del contenedor para confirmar el 82% de exactitud que publicamos, armar el paquete de
traslado (imagen + volumen de modelos + ruedas de instalación), sellarlo con huellas y repetir la
verificación completa **con la red deshabilitada**. Tres trampas ya verificadas al armar las ruedas.
Correcciones: **Docker funciona en esta máquina** (el "hace falta elevación de permisos" es texto
viejo), así que esto es 100% nuestro y se puede hacer aquí, sin pedirle una máquina al cliente. Y "los
tamaños están todos estimados" es impreciso: los de descarga están medidos y ya tengo tres reales
—nuestra imagen 1,16 GB en disco (estimado 0,8-1,2, cuadra), la base 1,12 GB (estimado ~0,6 → el
estimado se queda corto casi 2×), el motor de IA 8,29 GB (cuadra). Actualizar la tabla son minutos.
Añadir al alcance: la imagen existente usa etiquetas **no fijadas** mientras el procedimiento exige
versiones exactas.
Lo único validado de verdad hoy es la variante **sin** Docker: entorno limpio + instalación sin red
desde un paquete de 115 MB → 37 paquetes, cero accesos a red.

**N8 — Cablear las 5 familias de señales de falsedad y corregir el estado declarado del motor.**
*(1-2 semanas; conviene decidir el alcance de la primera versión antes de empezar)*
Hoy solo hay dos cosas cableadas: el motor de fechas y una versión **distinta y más débil** del
control de tipografías. Las sondas viven fuera del paquete y nadie las llama; dos familias no están
cableadas en absoluto.
**Medición nueva, que no está en ningún informe:** el control de tipografías **cableado** da **0 de 11
adulterados** detectados y **1 de 12 legítimos marcado** por error; la **sonda** da 5 de 12 y 0 de 14.
Es decir: en producción esa familia tiene detección cero y un falso positivo, donde la sonda tiene 5
aciertos y ningún falso positivo. Al cableado le faltan los 4 controles que votan y **todas** las
puertas de aplicabilidad.
Correcciones: **no existe** ningún archivo SQL escrito para las columnas de veredicto de falsedad — la
definición vive **solo** como especificación embebida en el documento del motor; hay que escribir la
migración y aplicarla. Y "decidir el alcance de la primera versión" mezcla dueños: elegir qué
controles entran y con qué severidad (avisa vs bloquea, quién puede aprobar un sospechoso con motivo
obligatorio) toca la operación de Gruppo y es **conjunto**; los 6 arreglos previos y el cableado son
nuestros.
Contexto: ninguna de las 8 señales que declaró el cliente llega hoy al auxiliar salvo las temporales y
la del diagnóstico — y el documento ejecutivo se lo promete como "especificada y medida".

**N9 — Poner en producción el cruce de huellas de imágenes embebidas.** *(1 semana. El ítem de mayor
retorno del motor de falsedad y el único que **crea su propio dato** sin pedirle nada al cliente.)*
Falta: extraer los objetos de imagen recorriendo también los contenedores anidados; el rol geométrico
más los 3 filtros que la sonda demostró imprescindibles (imágenes degeneradas, marca de la app de
escaneo, membrete); y la tabla de recursos gráficos que **se autoalimenta con cada radicación**.
Hoy los 10 controles dan 0 de 12 y el cruce contra histórico no es evaluable en 26 de 26. La sonda ya
probó con un autotest sintético (4 de 4) que la mecánica funciona: **el 0 de 12 es una medición, no un
error** — con 26 documentos la probabilidad de colisión es ~0; contra decenas de miles de radicaciones
al mes, una firma copiada colisiona casi con certeza.
Corrección: en el paquete **no hay inventario de imágenes que "arreglar"**. Lo único que existe se
queda con la imagen más grande, la usa solo para un análisis de compresión y **viene apagado por
defecto**. Así que la tarea es *crear* el inventario, no corregir un recorrido incompleto. Y hay que
**fijar una sola librería de PDF** para que las huellas sean reproducibles entre lo medido y lo
desplegado (hoy conviven dos).
Desbloquea los **dos únicos controles candidatos a bloquear** de toda la taxonomía (reuso de fondo y
de firma entre pacientes distintos). **Esto nunca va en la lista del cliente:** no se pide, se
construye.

**N10 — Exponer las coordenadas del lector.** *(2-3 días)*
El lector devuelve una sola cadena de texto y **descarta las cajas que sí produce**. Hay que devolver
texto + cajas por línea y usarlo para emparejar rótulo ↔ celda.
El emparejamiento rótulo ↔ valor sin coordenadas es el confusor número 1 de **dos** familias. Medido:
en un documento cada valor **precede** a su rótulo y el ancla devuelve la fecha de fin como si fuera
la de inicio (la fila entra con un día de más, **en silencio**); en el formato de una EPS grande las
celdas salen partidas y hay que ensamblarlas por posición. Tres de los falsos positivos graves
reproducidos son de esto y dos dejan además la fila del ERP con datos erróneos.
Precisiones: hay que decidir el tipo de retorno para los **tres** motores de lectura (dos no tienen
cajas, así que el contrato debe permitir cajas ausentes) y propagarlas por el cargador de páginas, que
**reescala** las imágenes grandes: si se reescala, las coordenadas hay que devolverlas normalizadas o
con el factor, o quedan desalineadas. Y N11 es una vía alternativa más barata para el mismo objetivo:
**decidirlas juntas**, no implementar dos mecanismos de posición.

**N13 — Hacer asíncrono el drenaje del lote y mover el candado a la base.** *(2-3 días)*
(1) El botón "procesar todos" ejecuta el drenaje **dentro de la petición HTTP** y puede durar horas:
hay que encolar, responder de inmediato y ofrecer un endpoint de progreso. (2) El candado es local al
proceso: pasarlo a un candado de la base con renovación. (3) La interfaz y el lote comparten el mismo
motor de lectura en el mismo proceso.
Sin (1) el botón es inusable a volumen real: cualquier proxy corta la conexión hacia los 300-600
documentos con tiempos de espera corporativos típicos y el auxiliar no recibe el resumen. Sin (2), el
primer intento de escalar produce N drenajes sobre la misma carpeta y duplica trabajo y filas. Con
(3) la latencia interactiva es impredecible durante el drenaje y puede haber dos documentos en vuelo
en un proceso (peor caso ~15 GB con el tope actual).

**N12 — Paralelismo con tope de hilos del motor de inferencia.** *(3-4 días)*
Hoy el drenaje es un bucle plano en un solo proceso. Hace falta un grupo de procesos con el tope de
hilos fijado **antes de importar el lector** — la variable de entorno **por sí sola no basta**, porque
la sesión de inferencia se construye sin tocar el número de hilos y usa su propio grupo (verificado: 0
resultados al buscarlo en el código). El punto exacto a envolver está identificado.
Capacidad de hoy: 1.400-2.100 documentos por ventana de 5 h — cubre el día pico (875) pero no una
ráfaga grande ni la carga inicial de histórico: un año son 199-222 horas de CPU ≈ 8,3-9,3 días con un
proceso frente a 50-56 h con cuatro. Y sin el tope, **un solo documento ocupa 8,67 núcleos para ir
1,7× más rápido** (~20% de eficiencia, 6,4× más CPU): el lote monopoliza la máquina aunque procese de
a uno, y la tabla de rendimiento por número de procesos deja de valer. Prerrequisito de J8.

### Impacto medio

**N11 — Usar la capa de texto del PDF en el camino de extracción.** *(2-3 días. Lo más barato con
mayor retorno según tres informes.)*
Redacción precisa: **el pipeline de extracción ignora la capa de texto**; el módulo de autenticidad
**sí** la lee (cuenta caracteres y saca fuentes con posición), pero solo para el control de
tipografías. Lo que falta no es la capacidad de leerla, es usarla en el camino de extracción como
fuente primaria (o segunda superficie que corrobore) y publicar la marca "confirmable sin OCR".
La capa existe en **13 de los 28 PDF** del corpus. En el único caso de la familia "días contra
diagnóstico", el lector se saltó la línea completa del diagnóstico principal **que sí estaba en la
capa de texto**: sin esto la familia pierde su único caso. Y "confirmable sin OCR" es exactamente la
condición que separa "avisa" de "bloquea" en la regla estrella.
No hace falta dependencia nueva (ya están las dos librerías). Sí hay una decisión nuestra que el
pendiente no mencionaba: **qué librería queda como lectora canónica**, porque hoy conviven tres usos.

**N16 — Arreglar el archivo de composición: zona horaria, topes, límite de memoria, versiones fijas y
valores por defecto seguros.** *(medio día)*
Verificado hoy: no hay zona horaria, ni topes de píxeles, ni escala de renderizado, ni límite de
memoria; dos imágenes usan etiquetas móviles; el reinicio de la base de prueba viene activado por
defecto y el servidor de base tiene un valor por defecto que apunta a la base de juguete.
(a) La zona horaria es un **defecto de datos**: cualquier corrida entre las 19:00 y las 23:59 de
Bogotá escribe la fecha de registro **un día adelantado** y desplaza el "hoy" de tres reglas. Hoy solo
se pasa la variable del programador de tareas; el contenedor corre en UTC.
(b) Es la **trampa silenciosa**: los topes de píxeles son justo la palanca que divide la RAM por 4,9 y
la CPU por 2,4 en los documentos patológicos, y el archivo de entorno **solo interpola** el YAML, así
que descomentarlos hoy no tiene ningún efecto dentro del contenedor. **Ojo:** añadirlos exige decidir
el **valor**, y eso está atado a N5 (el código trae 40 MP y el dimensionamiento razona con 8 MP: 7,6
GB frente a 1,6 GB de RAM por proceso).
(c) Sin límite de memoria, el matador por falta de memoria elige el proceso más gordo → se cae la
interfaz y la bandeja, no el documento.
(e) Elimina dos pérdidas silenciosas del día 1: con el reinicio activado, el botón "reiniciar prueba"
puede **vaciar el registro del ERP**; y con el servidor por defecto, el sistema escribe en la base de
juguete y nadie se da cuenta.
(f) Mover los servicios opcionales a perfiles hace que el arranque de producción sea un comando sin
editar el YAML a mano (hoy el procedimiento pide cuatro ediciones manuales) y ahorra ~0,6 GB.

**N17 — Pintar el panel de fechas en la interfaz, ordenar la cola por severidad y propagar el veredicto
en el lote.** *(2-3 días)*
Cuatro huecos del mismo canal. (1) La interfaz tiene el contenedor del panel y **nada más lo
referencia**: no hay código que pinte el veredicto, el estado por regla, la cobertura ni la evidencia
leída frente a derivada, aunque la API **ya** devuelve las tres cosas. (2) La consulta de la cola no
selecciona la severidad ni las alertas y ordena por identificador descendente; el índice por severidad
**no lo usa ninguna consulta**. (3) El resumen del lote se construye sin severidad ni hallazgos, y el
enrutado a carpeta no los mira. (4) Ampliar la columna de alertas a 512 caracteres para no perder
códigos cuando se enciendan cuatro reglas más (los 17 códigos suman 462 caracteres; hoy se recortan
con "(+N)", **no falla**).
Por qué importa: (1) es lo que permite distinguir "no encontré nada raro" de "casi no pude mirar" —
con cobertura media 0,554, un "coherente" sin ese número se lee como "documento verificado", y la
única falsa temporal del cliente sale coherente con cobertura 0,33. (2) es el propósito declarado de
todo el canal (columna propia, índice, puntaje para **ordenar** la cola): hoy el auxiliar ve la lista
en orden cronológico inverso y un grave de hace dos días queda enterrado. (3) hace que las tres reglas
de severidad leve **no bloqueen y tampoco avisen**: en el lote el caso va directo al archivo como
completo. **Mientras el panel no exista, "leve" equivale a "apagada".**
Matiz: un grave **sí** manda el caso a revisión (el motor mete esos hallazgos en la lista de
problemas); lo que se pierde en el lote es la **granularidad** y la trazabilidad, no el bloqueo.

**N20 — Resiliencia de conexión durante el drenaje.** *(1 día)*
El lote sostiene **una sola** conexión durante todo el drenaje, sin latido ni tiempo máximo de
sentencia. Cualquier reinicio o conmutación de la base a mitad del drenaje hace que **cada caso
restante** caiga al bucket de error: **cientos de archivos a "con error" por un fallo de red de 3
segundos.** La probabilidad crece con la duración del drenaje y por tanto con el volumen. No afecta a
la base local.

**N37 — Implementar la purga y la retención.** *(2-3 días; no bloqueado por el cliente)*
Ningún frente lo listó con dueño: todos lo citan solo como consecuencia de la pregunta jurídica.
Nuestra parte se puede hacer **ya**, con el plazo parametrizado y fallo temprano si no está puesto, de
modo que sin el dato del cliente el sistema simplemente **no purgue** (comportamiento seguro por
defecto): las dos guardas duras (no purgar la única copia por debajo del plazo, no purgar un caso no
terminal), la compresión del histórico, la limpieza del área de trabajo, las dos variables de
retención y un modo de simulación que reporte qué borraría. La retención **operativa** no depende de
nadie y se puede cerrar hoy.
Conjunto: si la purga corre sola o la dispara una persona con confirmación, y quién es esa persona.
**Recomendación:** automática solo para la retención operativa; la legal siempre con simulación +
confirmación humana, porque un error ahí borra originales irrecuperables.
Sin purga el árbol crece 5,4 GB/mes y 176.400 ficheros/año indefinidamente: el disco que se compre se
llena y el primer síntoma es un servidor sin espacio.

**N23 — Convertir la prueba de precisión en una prueba con umbral y darle un corpus que viva en el
repositorio.** *(1 día)*
La precisión de extracción —el número que le vamos a dar al cliente— **no tiene ninguna guarda de
regresión**: una caída del 76% al 40% no rompe nada. Es especialmente delicado ahora, que N2, N3, N11
y N15 tocan justo el extractor. Los otros 7 scripts de prueba sí son barreras y los 7 pasan.
Precisiones: no es que "devuelva 0 en todos los caminos" (hay un fallo si falta la carpeta de ejemplos
y un salto si falta el lector); lo que falta es el **umbral sobre la precisión**. Y peor que la falta
de umbral: si falta un documento individual, lo omite y **el denominador se encoge en silencio** — un
umbral porcentual seguiría pasando con 1 de 8 documentos, así que hay que fijar también el **número de
documentos evaluados**. Y el mínimo **no puede ser un único número**: la misma suite mide 76% con el
entorno del repositorio y 82% con el de producción, así que hay que anclarlo a la versión fijada del
lector o declarar dos.
Añadir un juego de textos ya extraídos y **anonimizados** dentro del repositorio, porque hoy depende
de una carpeta externa (fuera por datos personales) y no corre en un clon limpio. Y crear un ejecutor
único: hoy son 8 comandos a mano, así que es fácil que uno se quede sin correr.

**N21 — Dejar rastro de cada corrida y hacer que el chequeo de salud diga la verdad.** *(1 día)*
(a) Persistir el resumen de cada corrida (hoy solo se imprime en la salida del contenedor y la corrida
programada solo registra una línea). (b) Que el chequeo de salud compruebe la base: hoy devuelve
"ok" **fijo, sin comprobar nada**.
Responde las tres preguntas de la mañana siguiente: ¿corrió?, ¿cuánto quedó sin procesar?, ¿está sano?
Nota de prioridad: la mitad (b) es casi gratis (la función que comprueba la base ya existe y otro
endpoint ya la usa); el trabajo real es (a).

**N32 — Aplicar al plan de ingesta las 6 correcciones ya identificadas.** *(medio día)*
El plan es el documento técnico de referencia de toda la ingesta y el que se usará para las fases 2-5,
y sigue afirmando cosas medidas como falsas: (1) llama "camino preferido en Windows" a runtimes que
ejecutan contenedores **Windows** cuando las tres imágenes son **Linux**, y su plan alternativo no
puede funcionar; (2) dice que la corrida nocturna tiene un horario por defecto cuando el código viene
**vacío = desactivado**, así que si nadie pone la variable **no hay drenaje y no salta ningún aviso**;
(3) sus cifras de rendimiento son ~3× optimistas y su fórmula de paralelismo está mal en los dos
términos; (4) atribuye el pico de memoria a algo que no lo causa; (5) lista 4 extensiones de archivo
cuando el código acepta 8; (6) un riesgo de rutas largas baja a una verificación de una línea.
**Orden sugerido: (2) y (5) primero**, porque son las dos que producen un comportamiento distinto del
documentado en una instalación real. La corrección (1) no se puede escribir del todo sin J1.

**N26 — Validar el camino híbrido y de visión con el motor de IA vivo.** *(1-2 días; ejecutable hoy)*
El extractor híbrido es el **predeterminado de la interfaz** y sus guardas contra invención (aceptar
fechas y días del modelo solo si aparecen en el texto leído) **nunca se han ejercitado contra un
modelo real**: se validaron por inspección y con un extractor falso. Y el modelo del corpus ya
demostró inventar fechas a partir de números de contrato.
Corrección importante: **el motor de IA responde en esta máquina** (versión 0.33.2) y Docker también
funciona (la base lleva 16 h en marcha), así que el "falta elevación de permisos" que repiten dos
documentos es texto viejo. **Lo único que falta son los modelos**: hay que descargar los dos que el
proyecto declara (uno de ~3,3 GB). Pasa de "bloqueado" a **ejecutable hoy sin depender del cliente**.
Falta además medir el coste real (los únicos números son de junio de 2026: 20-40 s el híbrido, 1-2
min por imagen y ~4 min por PDF la visión) y fijar la **versión mínima** que se le exige al servidor
del cliente. El modelo de visión está declarado obligatorio para permisos manuscritos: si son el 5%
del volumen (350/mes) a 4 min son **23 h de reloj al mes solo de visión**, más que todo el OCR del mes.

**N25 — Impedir que el lote use el extractor híbrido o de visión.** *(2 horas)*
Corrección de la formulación: la interfaz **del lote** ya manda el extractor de reglas cableado, así
que **hoy no existe** el "un clic del auxiliar convierte el drenaje nocturno en uno de 10 h". La
exposición real, que sigue abierta, son tres: la API acepta el sustituto en el cuerpo de la petición;
la línea de comandos admite tanto el extractor híbrido como el lector de visión (~15-60 documentos/h);
y la variable de entorno. Restringir el lote al extractor de reglas, o encolar la escalada en una cola
separada de baja prioridad, nunca en línea.

### Impacto bajo (pero baratos y algunos con efecto visible)

**N15 — Aceptar la "X" de relleno del diagnóstico y poner guarda de catálogo al control de longitud.**
*(medio día)*
**Hallazgo nuevo que sube la urgencia:** el control de longitud produce falsos positivos **hoy**, con
el catálogo público que ya cargamos. Ese catálogo tiene **2.070 códigos de exactamente 3 caracteres**
y ninguno con la X de relleno. Es decir: un código de 3 caracteres **resuelve bien** contra el
catálogo y **aun así** se marca como "posible manipulación del documento: código incompleto".
Además, verificado de extremo a extremo: un documento que imprime un código con X final entra al
registro con la bandera de sospecha y el motivo "código incompleto (3 caracteres; se esperan 4)".
Medido 1 de 14 legítimos del corpus y 2 documentos afectados por la vía de la consulta.
Nuestro y hacible ya: aceptar y **conservar** la X, y probar el código con y sin ella en la consulta.
Conjunto acotado: **decidir si el control de longitud se retira o se mantiene** depende de qué
convención use el catálogo del cliente (petición A3), pero ver J10 — hoy ya hay razón suficiente para
retirarlo o guardarlo.

**J10 (reclasificado de conjunto a nuestro) — Decidir el destino del control de longitud del
diagnóstico.** *(2 horas)*
Ya **no** hace falta esperar la respuesta del cliente para decidir: con el catálogo público cargado hay
2.070 códigos válidos de 3 caracteres, así que **hoy el producto se autocontradice**. La contradicción
está incluso congelada en las pruebas: una prueba exige que un código de 3 caracteres **dispare** la
alerta y otra exige que el mismo código con subdivisión **no** dispare porque no tiene hijos.
Contraejemplo demoledor: el documento que el cliente marcó como "no existe el diagnóstico" por
imprimir 3 caracteres está archivado **byte a byte idéntico** en la carpeta de legítimos — el criterio
del analista humano es el mismo que implementa el control y en ese caso no separa.
Retirarlo, o condicionarlo a la misma guarda de catálogo que ya usa el control de "diagnóstico
inexistente", es trabajo nuestro. Al cliente le queda solo la pregunta acotada de A3(b), que decide si
podría reactivarse alguna vez, no si hoy está mal.

**N18 — Quitar el tope silencioso de 500 casos por lote y alertar de la acumulación.** *(medio día)*
(1) El drenaje corta en 500 casos y la interfaz lo llama **sin** pasar el límite, y **no hay ninguna
variable** para cambiarlo. Cambios: leerlo del entorno y ponerlo en 3× el día pico, contar y devolver
"no procesados" en el resumen (esa clave hoy no existe), y **alertar cuando queden archivos en la
entrada al terminar la corrida**.
Es lo **primero** que se rompe, y a 1,4× del pico supuesto: día medio 350 casos cabe; día pico 875 →
se drenan 500 y **375 se quedan sin ninguna alerta**; el operador ve un total mayor que la suma de los
cubos y nada se lo explica. Es una variable, no hardware.
(2) Un PDF de más de 30 páginas se recorta y solo se registra un aviso en el log: hay que propagar el
recorte **como problema del documento**. Precisión: ese tope **ya** es configurable por entorno; lo que
falta no es quitarlo, es hacerlo visible. Un paquete de WhatsApp donde la incapacidad va en la página
31 registra una fila **sin haber leído el documento**.
Precisión: la interfaz **sí** consume el endpoint de pendientes y pinta el contador en el botón; lo que
no existe es una alerta **automática** al terminar la corrida ni nada que vigile la cola sin que un
humano abra la pantalla.

**N19 — Hacer reconciliable el movimiento de archivos y visible su fallo.** *(1 día; complemento
necesario de N1)*
Escribir siempre a un área temporal y renombrar de forma atómica, registrar el estado del movimiento,
reintentar los pendientes al arrancar, y que un fallo deje de ser **solo una línea de log**: hoy se
captura toda excepción y se sigue, así que el archivo se queda en la entrada sin que nada lo sepa.
Cubre también el bloqueo de archivo por antivirus o indexador en un anfitrión Windows y la garantía
"cada archivo termina en exactamente una zona".
Corrección de la formulación: la carpeta de control **sí** se usa hoy (aloja la configuración de
reglas en caliente). La que se crea y nunca se escribe es **solo** la temporal. Redacción correcta:
"el área temporal se crea y nunca se escribe; el movimiento no es atómico ni reconciliable".

**N22 — Quitar la cédula de los registros de log y acotar su crecimiento.** *(medio día)*
(a) Hoy se registran nombres de archivo (que llevan la cédula por contrato de nomenclatura) y la llave
de caso, **que es la cédula**. Son **tres** sitios, no uno: el error de proceso de caso, el fallo al
crear la alerta, y **la subcarpeta de destino de casos con error se nombra con la cédula**, así que
queda también en la ruta que aparece en cualquier traza posterior. Los logs son legibles por todo el
que tenga permiso de contenedores: es un control de Ley 1581 que se incumple, y el plan ya lo exige.
(b) Límites de tamaño y rotación del log en **los tres servicios**, no solo el nuestro: los otros dos
también escriben sin tope y llenan el disco sin avisar. Esa parte conviene diseñarla de una vez con el
registro estructurado por corrida (fase 2), que tampoco existe, para no hacerla dos veces.

**N27 — Cerrar la documentación pública de la API (y preparar TLS + autenticación).** *(1 hora la
parte inmediata)*
**Separar el dueño, porque hoy están mezclados:** apagar la documentación interactiva y el esquema de
la API es **una línea, nuestra, y NO está condicionada a J7** — se puede cerrar hoy. Hoy la aplicación
se construye con los valores por defecto y publica el mapa completo de la API, **incluidos los
endpoints de escritura y de reinicio**, sin ninguna autenticación. Quita el mapa de ataque por el
coste de una línea.
Solo TLS + autenticación + validación de contenido de los archivos de entrada (que llegan de WhatsApp
y correo, o sea de fuentes no confiables) dependen de J7. Nada de eso existe en el repositorio.
**Detalle a cerrar en el mismo cambio:** el procedimiento de instalación trae como comprobación una
petición a la documentación de la API esperando respuesta 200; si se apaga sin tocar el procedimiento,
**la verificación de instalación va a "fallar" en casa del cliente por diseño**.

**N6 — Generar un listado de dependencias fijadas.** *(medio día. +6 puntos de precisión medidos,
gratis.)*
El **mismo** listado de dependencias instala la versión buena del lector en un entorno (modelos
nuevos, 37 de 45 campos = 82%) y **degrada en silencio** a la versión de 2023 en otro (modelos viejos,
34 de 45 = 76%), porque todas las versiones nuevas declaran incompatibilidad con Python 3.13+. **Hoy
qué motor de lectura acaba en producción lo decide un accidente de metadatos.** Re-resolviendo hoy sale
otro conjunto (salto de versión mayor en una librería de imágenes, y dos más) y **ninguna prueba del
repositorio vigila ese salto**.
Precisión: la deriva de versión mayor **ya no es hipotética** — la imagen construida trae la versión
nueva dentro (verificado ejecutando dentro de ella), así que el salto ya está en el artefacto. De esa
misma imagen salen versiones reales que sirven de semilla, **pero le falta una librería de PDF**, así
que el listado fijado no se puede congelar desde ella tal cual: **primero hay que reconstruir (N7) y
sacarlo de ahí.** Orden: N6 es prerrequisito de un paso de N7 — hacerlos en la misma sesión.
De paso, decidir si dos herramientas que solo se usan en el anfitrión se separan en un listado de
desarrollo.

**N5 — Medir si bajar el tope de píxeles degrada la exactitud.** *(1 día. Precondición de la compra,
no un detalle.)*
Decide la RAM por proceso: **1,6 GB con tope frente a 7,6 GB sin él.** Medido: 2 de 31 documentos
(páginas de 86,5 y 72,3 megapíxeles) piden 7.648 MB y 6.810 MB de pico y bajan a ~1.555/1.589 MB con
el tope, con 10,5% menos de CPU. A 6,5% de incidencia sobre 7.000 trámites son **~450 documentos/mes
pidiendo 7,6 GB cada uno: no es la cola, es la rutina.** Si no degrada, 16 GB cubren el perfil
recomendado; si degrada, hay que volver al tope alto y los perfiles propuestos dejan de servir
(harían falta 32 GB).
**El método propuesto no mide nada y hay que corregirlo o se gasta el tiempo en un no-op:** de las 35
páginas medidas, **solo dos** superan el tope; las otras 33 están en 3,5-4,5 megapíxeles. Como el tope
solo reescala si se supera, correr la suite de ejemplos con los dos topes da **el mismo resultado por
construcción** — los 8 documentos de esa suite están todos por debajo y **ninguno de los dos
patológicos está entre ellos**.
Método correcto: comparar **campo a campo** la extracción de esos **dos** documentos con tres topes
(40 / 12 / 8 megapíxeles), que son los únicos donde el tope actúa. Segundo hueco: **no existe** un
registro de verdad por campo de los 31 documentos (el archivo que parece serlo es la tabla de motivos
del cliente, no valores esperados); el único por campo es la tabla en línea de la suite de ejemplos (8
documentos / 45 campos). Así que **hay que construirlo** al menos para esos dos, y eso es parte del
trabajo. Tercero, a favor de la otra variante: bajar la **escala de renderizado** sí afecta a los 35
documentos (4,4 → ~2,0 megapíxeles), así que **esa** sí exige la suite completa — y es justo la que el
documento ejecutivo recomienda **sin haberla medido nunca**.

**N29 — Cerrar la deuda del esquema de demostración.** *(1 día. 100% nuestro: el dato ya está
versionado, no hay que pedirle nada al cliente.)*
Cinco síntomas del mismo problema: (1) la tabla de donde se lee el checklist de radicación **no se
crea**, así que en un clon limpio el validador de radicación está **silenciosamente apagado** (degrada
a lista vacía); (2) la tabla de histórico tampoco existe, así que dos reglas no se pueden probar en
local; (3) la carga de requisitos **no tiene protección contra duplicados** y el propio archivo
documenta re-correrlo a mano para migrar: al segundo pase duplica las 12 filas y el validador repite
el documento en dos listas — **el procedimiento de migración que le vamos a dar al cliente corrompe
los requisitos documentales**; (4) el índice por severidad solo lo crea la migración; (5) el sembrador
lee un CSV de una carpeta de descargas que **ya no está en disco** y devuelve lista vacía en silencio
— hay que apuntarlo a los artefactos versionados (19 EPS, 320 filas). Sexto síntoma medido: el parser
tiene una ruta de marcador de posición, así que **hoy no se puede regenerar** el JSON desde el export
original ni reproducir las cifras de cobertura de 64 EPS que citan dos documentos.
El validador de radicación es una funcionalidad completa con pruebas propias que **en el esquema del
repositorio no se ejerce nunca** (su prueba pasa porque usa un doble).

**N30 — Guarda de coherencia sobre la fila final.** *(2 horas. No es un defecto vivo: es red de
regresión.)*
Una comprobación de que la fecha de vencimiento sigue siendo inicio + días, justo después de construir
la fila. **No** puede ser una regla del catálogo: el contrato del motor prohíbe que una regla lea un
valor ya calculado.
Hoy la invariante se cumple por construcción (la fecha de vencimiento tiene una sola fuente y la fila
se recalcula completa en cada guardado o aprobación, así que un cambio manual de ese campo se
sobrescribe). Medido: **0 violaciones en las 19 filas comprobables** del corpus. Lo que falta es la
guarda que impida que un cambio futuro, o una escritura directa a la base, rompa la invariante en
silencio. Formularlo como comprobación + prueba de una línea, no como corrección de un defecto.

**N36 — Escribir el artefacto de servicio del sistema operativo.** *(medio día; **solo si J1 descarta
Docker**)*
Verificado: no existe nada de eso en el repositorio. Con Docker lo cubre la política de reinicio +
habilitar el servicio. Enunciarlo como dependiente y **no** mandárselo al cliente como tarea suya: "si
J1 elige Windows nativo sin Docker, nosotros escribimos el servicio (~medio día); si elige Linux con
Docker, no hace falta". En el camino nativo, sin este artefacto **no hay servicio**: la aplicación
muere al cerrar la sesión, no vuelve tras un reinicio y la corrida programada desaparece con ella.
Aparte del artefacto, **el arranque sin sesión no queda cerrado hasta ejecutar la prueba de reinicio en
frío**, que sigue sin hacerse en ninguno de los dos caminos.

### Documentación y limpieza interna (nuestra, no del cliente)

**N4 — Corregir el documento ejecutivo: publica cifras de hardware, disco y topes ya superadas.**
*(2 horas. La contradicción más caliente y la mejora más barata con impacto en la compra.)*
Es **el único documento que el cliente va a leer para comprar el servidor** y dice 4 núcleos / 16 GB /
250 GB, 6,3 GB/mes → 379 GB a 5 años con 2,5 archivos/trámite, y recomienda una escala y un tope de
píxeles concretos. La tabla vigente dice mínimo 4 / recomendado 8 núcleos, 250 GB como **mínimo** (≈3
años) y 500 GB NVMe recomendado (5 años), 5,4 GB/mes y 324 GB a 5 años con 2,1 archivos/trámite. Le
estamos dando un disco que se llena en ~3 años, un número de núcleos sin margen para el paralelismo ni
para la carga inicial (un año de histórico son 199-222 horas de CPU) y un tope de píxeles **que nunca
se midió**.
Para cerrarlo de una sola pasada: (1) el documento técnico **se contradice consigo mismo** en el disco
a 5 años (337 GB en una tabla, 324 GB en otra sección) — hay que decidir la cifra **antes** de
reescribir el ejecutivo, o se traslada la contradicción; (2) el mismo documento publica que en
producción el lector es "más preciso (82% frente al 76%)", y ese 82% **no está verificado dentro del
contenedor** (se midió forzando la versión nueva sobre otro Python), así que la misma edición debe
matizarlo; (3) **ninguno** de los dos valores de tope recomendados se midió jamás (lo medido es otro
par), así que N4 no se cierra del todo sin N5 o sin bajar la recomendación a los valores realmente
medidos.

**N28 — Re-exportar el análisis versionado con la regla del rojo y unificar la numeración de las
sondas.** *(1 día. 100% interno; no va en la lista del cliente.)*
El registro de verdad **vivo** ya está resuelto (0 etiquetas "sin motivo"), pero la **copia versionada
sigue con las etiquetas viejas** en varios archivos. **La vía de arreglo está mal descrita: correr el
script de exportación NO basta** — ese script copia desde la carpeta fuente, y **la fuente viva sigue
obsoleta** (4 apariciones en un documento y 4 más en el generador, donde está escrito a fuego). Orden
correcto: arreglar primero el generador y los documentos vivos, volver a correr las sondas, y **solo
entonces** exportar.
Además: actualizar el documento del motor de falsedad (su veredicto de arranque, su lista de huecos y
dos de sus preguntas piden lo que Diana **ya** respondió); **re-medir** con los 3 motivos recuperados
(1 de días contra diagnóstico y 2 de nombre del diagnóstico distinto); y **unificar la numeración de
documentos** a la huella corta, porque dos sondas numeran distinto y hoy el mismo identificador
significa **dos documentos distintos** según el informe que se lea — ya hace que los informes se
contradigan al cruzarlos. Consolidar también las carpetas duplicadas de texto extraído.
**Quitar del pendiente** la guía de prueba: ya está actualizada, y "arreglarla" sería tocar algo
correcto.
Por qué importa: el repositorio se comparte con el cliente. Los 3 motivos recuperados caen justo en
las dos familias bloqueadas por falta de datos del cliente, así que resolver el rojo **no añadió
detección** pero **sí refuerza con evidencia** las peticiones A3 y A6 — y hay que decirlo con el
número correcto.

**N33 — Unificar el vocabulario de tipos de documento y regenerar el PDF de la guía.** *(2 horas)*
Tres listas distintas del mismo vocabulario: la guía que **se entrega al equipo de recepción** incluye
cuatro tipos de radicación pero omite dos; el README, las instrucciones internas y el plan listan esos
dos y omiten los cuatro; el código tiene los diez. Un archivo con un tipo que no está en la lista que
le dieron acaba contado como adjunto sin clasificar (el lector de nombres acepta cualquier palabra, no
valida el vocabulario), y uno con un tipo que la guía omite se pide de vuelta sin necesidad.
**Decisión conjunta embutida que conviene sacar y preguntarle a Diana:** si al equipo de recepción se
le debe pedir que nombre los cuatro tipos que **solo** exige la radicación ante la EPS y que no
bloquean el trámite interno; meterlos alarga el vocabulario de 12 a 16 palabras para quien nombra
archivos a mano.
Y **regenerar el PDF**: es de las 23:34 y el texto se editó a la 01:41, así que el PDF que se imprima
puede no coincidir. Verificación de cierre: **comparar el texto del PDF con el del documento**, no los
tiempos de modificación.

**N34 — Sanear cifras y rutas desactualizadas de la documentación.** *(medio día. Cada dato ya está
medido y publicado en otro archivo del repositorio; el cliente no puede resolver nada de esto.)*
(1) Un documento dice que la detección "pasó de 2 a **5** de 9"; el número medido y publicado en otros
dos es **4 de 9** — y los tres son documentos que el cliente puede leer. **Prioridad máxima de esta
lista.**
(2) El "80% de exactitud" aparece en **cuatro** sitios y **no corresponde a ninguna configuración
real** (76% en el entorno del repositorio, 82% en el de producción). Es la cifra que el cliente va a
citar.
(3) Dos topes documentados no coinciden con el código (20 páginas vs 30; 64 megapíxeles vs 200
millones).
(4) "Sin GPU" es incorrecto: la máquina la tiene; lo correcto es que **no se aprovecha** porque el
motor de inferencia es solo-CPU. (La frase está en otra línea de la que dice el pendiente.)
(5) Varias rutas mandan a buscar **fuera** del repositorio archivos de análisis que ya están dentro —
justo lo que el documento de replicación prometió resolver. **Matiz para no romper nada: NO todas esas
rutas están obsoletas.** Los **documentos** del corpus siguen viviendo fuera a propósito por datos
personales, así que las referencias al corpus están bien; solo hay que reapuntar las de **análisis**.
Y hay una más que la lista no incluía: una **cita desde el código**.
(6) Se afirma que la carpeta de control "aún no se usa" cuando aloja la configuración de reglas.
(7) Un documento habla de ~46 GB/año de crecimiento y otro de 65 GB/año. **Si le vas a pedir un disco
al cliente, resuelve esto primero.**
(8) "~19 de 62 EPS" cuando lo medido es 19 de **64**.
(9) Dos sitios dicen que la plantilla de configuración "no existe en el repositorio": **sí existe** y
está completa — aunque ofrece dos variables que **por ese archivo no llegan al contenedor** (ver N16).

**N38 (reasignado desde C12) — Documentar la procedencia normativa del tope de 540 días.** *(2 horas)*
El tope de 540 días lo introdujimos **nosotros** y su origen normativo es público y comprobable por
nosotros, igual que hicimos con el catálogo de diagnósticos. Preguntarle a Diana "de dónde sale
vuestro 540" es preguntarle por un número que pusimos nosotros. Lo que sí se le pregunta es D8 (topes
por tipo en su nómina y quién los valida). Nota de redacción: **la numeración de preguntas choca entre
documentos** (en un archivo el tope de días es la pregunta 8, en otro la 8 es la de emisores no
inclusivos) → **al cliente hay que mandarle el texto de la pregunta, nunca el número.**

---

## 4. Contradicciones y documentos desactualizados

Estas son cosas que hay que corregir **antes** de que el cliente cite una cifra equivocada. La más
caliente está justo en el documento que usa para cotizar.

| # | Contradicción | Resolución | Dónde se arregla |
|---|---|---|---|
| 1 | **Hardware y disco.** El documento ejecutivo publica 4 núcleos / 16 GB / 250 GB y 379 GB a 5 años con 2,5 archivos/trámite; el técnico publica mínimo 4 / recomendado 8, 250 GB como mínimo y 500 GB recomendado, y 324 GB a 5 años con 2,1 archivos/trámite | El técnico ya declara la diferencia y la resuelve a favor de su tabla; el ejecutivo no se corrigió | **N4** |
| 2 | **Topes de píxeles.** El ejecutivo recomienda un par de valores; el técnico recomienda otro. Lo **único** medido es un tercer par, sobre 5 documentos y **una** pasada. La escala baja no se midió nunca | Hay que elegir un valor **antes** de escribirlo en el archivo de composición | **N5 + N16** |
| 3 | **Exactitud del lector: se publican tres cifras y solo dos son reales.** 76% = entorno del repositorio (re-ejecutado: 34/45). 82% = entorno de producción, medición anterior **no re-verificada**. **80% = no corresponde a ninguna configuración real** y aparece en cuatro sitios, incluido el README | La diferencia 76/82 la decide qué versión del lector elige el instalador según la versión de Python | **N6, N7, N34** |
| 4 | **Detección de adulteradas: "de 2 a 5 de 9" frente a "de 2 a 4 de 9".** Las tres apariciones están en documentos que el cliente puede leer; **4 es el número bueno** | Corregir antes de que cite el 5 | **N34** |
| 5 | **Crecimiento de disco: ~46 GB/año frente a 65 GB/año** en dos documentos de análisis | Resolver antes de pedirle un disco | **N34** |
| 6 | **Número de EPS: "~19 de 62" frente a 19 de 64** medidos | — | **N34, D10** |
| 7 | **El documento de validación temporal se contradice consigo mismo**: dice que leer fechas en palabras está pendiente y que "el lector que sí las saca existe fuera del paquete", y tres filas más abajo pide corregir esa misma función, que está **dentro** del paquete y sí lee ese formato | Verificado. Consecuencia: hay que re-medir la cobertura, aunque **no** por la razón que se creía (ver N3) | **N3** |
| 8 | **Causa mal atribuida del defecto "número de días fuera de rango".** La nota del proyecto culpa a la función de normalización de fechas; comprobado que esa función anula una variable **local** y **no** toca el valor. Quien descarta el valor es el **lector** | El efecto descrito es correcto; el arreglo está en otro sitio del que dice la nota | **N2** |
| 9 | **El documento del motor de falsedad dice "especificación, NO implementado"** cuando ya existe un subconjunto implementado (fuentes del PDF, análisis de compresión, periodos múltiples) más las señales de diagnóstico y el estado de posible manipulación | — | **N8** |
| 10 | **Entre frentes, la columna de alertas.** Un frente afirma que su ancho hace **fallar** el registro al encender cuatro reglas y lo marca bloqueante; el otro dice que está resuelto | **Verificado: el segundo tiene razón.** La función que recorta la lista cierra con "(+N)" y nunca deja un código a medias. **No bloquea nada.** Sí es cierto que se pierden códigos en silencio → ampliar la columna es mejora, no bloqueo | **N17 (sub-tarea)** |
| 11 | **Entre frentes, la prueba de precisión.** Un frente dice haberla ejecutado ahora con 34/45 = 76%; el otro la declara punto ciego porque 7 de los 8 documentos son escaneos que necesitan lector real y todas las mediciones recientes usaron textos **cacheados** | O el 76% salió del camino cacheado, o uno de los dos se equivoca. **Aclararlo ANTES de citar la cifra** | **N7, N23** |
| 12 | **Nomenclatura de ingesta.** La memoria del proyecto y un informe citan `{cedula}_{AAAAMMDD}_{TIPODOC}`; el código y las guías vigentes usan `cedula_TIPO[_NN]` **sin fecha** | El cambio fue **deliberado** y es justo lo que provoca J4. **No llevar la versión con fecha al cliente**; actualizar la memoria | **N28** |
| 13 | **Documentos que piden lo que Diana ya contestó**: el documento del motor de falsedad (dos preguntas), el estado del corpus y el registro de verdad versionado (4 apariciones cada uno) frente a la fuente viva (0). **Uno de esos se le iba a mostrar al cliente** | Re-exportar y reescribir. La guía de prueba **ya** está corregida | **N28** |
| 14 | **Vocabulario de tipos de documento: tres listas distintas**, y el PDF de la guía es anterior a la última edición del texto | — | **N33** |
| 15 | **El plan de ingesta contra el código**: llama "camino preferido en Windows" a runtimes que ejecutan contenedores Windows cuando las imágenes son Linux; dice que la corrida nocturna tiene horario por defecto cuando viene **desactivada**; sus cifras son ~3× optimistas; lista 4 extensiones cuando el código acepta 8 | La (2) y la (5) primero: producen comportamiento distinto del documentado en una instalación real | **N32** |
| 16 | **Convención de fecha de vencimiento: coherente pero sin confirmar por el cliente** en ningún documento nuestro | El esquema real que envió Diana en junio **sí** la confirma (vencimiento = inicio + días). Baja de "confirmación necesaria" a chequeo de cortesía; lo que queda abierto es si algún emisor **imprime** el día de reintegro | **A6 (nota), D2** |
| 17 | **Diagnóstico, longitud y "X" de relleno.** La nota del cliente dice "todos los diagnósticos son de 4 caracteres" y toda una familia se construyó sobre el relleno con X; el catálogo público que cargamos **no usa ese relleno** y lista 2.070 códigos de 3 caracteres válidos, **sin ninguna subdivisión de 4** | O el catálogo del cliente usa otra convención, o la nota describe lo que espera y no lo que hay en su tabla | **A3(b), J10, N15** |
| 18 | **Numeración de documentos entre sondas.** Una numera globalmente desde 0 y otra por clase desde 1, así que el **mismo identificador significa dos documentos distintos** según el informe; otras tres usan el nombre de archivo. Y hay carpetas de texto extraído duplicadas, cada sonda lee unas u otras | Ya hace que los informes se contradigan al cruzarlos | **N28** |
| 19 | **Instrucciones internas contra el código**: dos topes distintos de los reales, "sin GPU" cuando la hay, y "la carpeta de control aún no se usa" cuando aloja la configuración de reglas | — | **N34** |

---

## 5. Lo que NO es pendiente

Cerrado en las últimas horas (un barrido ingenuo lo volvería a sacar porque hay documentos con texto
viejo):

1. **El significado del rojo en la tabla de motivos.** Diana respondió: el rojo indica que el
   documento está mal y que la razón es la de la fila inmediatamente anterior. Ya está aplicado y la
   etiqueta "sin motivo registrado" **ya no existe**: los 15 adulterados tienen razón declarada. Lo
   único que queda de ese bloque son dos cosas **distintas** y sí listadas: la **vía** de confirmación
   de cada adulteración (C5 de la petición C) y re-exportar los artefactos versionados que aún traen
   el texto viejo (N28).
2. **El catálogo de diagnósticos público.** Hecho: 14.484 códigos versionados y cargados, con la
   guarda de categoría subdividida; la detección pasó de 2 a 4 de 9 casos con 0 falsos positivos. Lo
   que sigue abierto es el catálogo **del cliente**, que es el autoritativo (A3).
3. **La estructura de carpetas de la ingesta y el botón de reiniciar prueba.** Hechos y probados, con
   prueba automatizada propia.
4. **Versionar el análisis y el documento de replicación.** Hechos. Lo que queda es re-exportar con la
   regla del rojo (N28) y corregir las rutas de análisis que aún apuntan fuera (N34).

Descartado por la verificación (con el motivo):

- **"La plantilla de configuración no existe en el repositorio"** (afirmado en tres sitios): **existe**,
  completa y comentada. Solo queda corregir esos textos (N34) y advertir que dos de sus variables no
  llegan al contenedor (N16).
- **Los 6 hallazgos graves y 7 medios sobre el lector de números en letras: todos arreglados.**
  Verificado con una batería de 21 casos tomados literalmente de esos informes (frase numeral
  recortada, singular "DIA:", rejilla día-mes-año, veto solo a la izquierda, "mil", rótulo sin
  delimitador, "se hace entrega", separador tras la unidad, vecino único, "diez y seis", "D1AS",
  fórmula de cierre notarial, "válido por 30 días", "control en 3 días", "radicarse dentro de 3 días
  hábiles"): **21 de 21 correctos.**
- **Un código de diagnóstico sin punto en la celda de días se volvía duración** (J069 → 69 días):
  arreglado, devuelve nada en los 10 casos.
- **Desbordamiento con año 9999** al construir la fila: hay captura de la excepción en los dos sitios.
- **El control de "inicio en el futuro" marcando vacaciones y prelicencia**: hay exención por tipo. Lo
  que queda de ese control es contra qué fecha se mide (J6), no la exención.
- **Segunda implementación del cruce días ↔ rango** en el módulo de autenticidad: **eliminada**, y el
  módulo lo documenta.
- **El formulario reenviando el valor derivado como si fuera tecleado** y el fallo por severidad mal
  escrita: hay detección de corrección humana y acceso seguro al orden de severidades.
- **"El ancho de la columna de alertas hace fallar el registro (error 1406)"**: **falso.** Verificado:
  la lista se recorta al ancho cerrando con "(+N)" y nunca deja un código a medias. Lo que sí es cierto
  —que se pierden códigos en silencio— quedó como sub-tarea de N17.
- **"Leer las fechas escritas en palabras" como pendiente completo**: **parcialmente hecho.** La
  función existe y está cableada, así que el formato "MARTES 02 DE SEPTIEMBRE DE 2025" **sí** se lee.
  Lo que falta de verdad está en N3.
- **La causa anotada del defecto "número de días fuera de rango"**: la nota culpa a la función de
  normalización; comprobado que anula una variable **local** y no toca el valor. El efecto sigue
  abierto (N2), la causa anotada no es la correcta.
- **La degradación sin base de datos**: completa y **deliberada** — devuelve "no disponible" a
  propósito para no acusar de manipulación sin catálogo.
- **La validación del catálogo de reglas al importar** (código repetido, campo inexistente, errata en
  los requisitos): implementada y levanta al arrancar.
- **La configuración en caliente (base > archivo > código)**: completa, valida cada entrada y avisa de
  lo que ignora; atacada con 105 comprobaciones sin fallos. Su migración existe y es idempotente.
- **La casilla remunerado/no remunerado de los permisos manuscritos**: declarada comportamiento
  **esperado** (no se detecta de forma confiable con ninguno de los dos motores; el auxiliar elige el
  tipo a mano). Lo que sí queda abierto es **cuánto volumen** son permisos manuscritos (B7).
- **Pedirle al cliente el índice de huellas del histórico de radicaciones**: **no se pide, se
  construye** — se autoalimenta con las radicaciones que ya entran (N9). Pedirlo sería trabajo inútil
  para Diana.
- **"La prueba de precisión no se ha corrido con este cambio"**: corrida, 34/45 = 76%, idéntico a la
  medición previa → no hay regresión por los numerales en letras. Lo que queda es convertirla en
  barrera (N23) y medirla en el entorno de producción (N7).
- **"El banco de pruebas de rendimiento no está versionado"**: **está** en el repositorio con sus tres
  archivos de medición. Solo la **ruta** citada en dos documentos está mal (N34).
- **Tres dependencias "no declaradas"**: ya están en el listado. Lo único que queda es decidir si dos
  de ellas se separan en un listado de desarrollo (N6).
- **N31 — "Decidir qué se hace con la discrepancia palabra ↔ dígito de los días": CERRADO.** La
  decisión **ya se tomó y está implementada**: es una regla del motor de fechas, severidad media,
  activa. La afirmación de que el mapeador "los ignora" es **falsa hoy**: el hallazgo entra en la lista
  de problemas y sale en **tres** columnas de la fila. Lo comprobé ejecutándolo: con días=2 y letra=3
  el motor devuelve el código, severidad media y el texto "la duración escrita en letras (3) no
  coincide con el número de días registrado (2)", y ese texto **se le pinta al auxiliar** y bloquea la
  aprobación. Es cierto que la interfaz no muestra los dos campos crudos (usa lista blanca), pero es
  cosmético. Quedan dos residuos, ninguno es una decisión y ninguno es del cliente: borrar la
  limitación obsoleta de las notas internas, y la detección de **dos duraciones distintas** en el mismo
  texto (sigue leyéndose la primera), que es **cobertura del lector** y pertenece a la lista aditiva del
  extractor, no a un pendiente de decisión.

Fuera de alcance (no son pendientes, hay que **declararlo** en la reunión para no prometerlo):

- **Verificar que una firma sea auténtica.** Es peritaje grafológico y requiere muestras indubitadas
  del médico que el sistema no tiene ni tendrá. Solo son detectables el **reuso** y la incoherencia
  interna, y la familia **nunca** debe afirmar "firma falsa".
- **"El motor es ciego en el píxel."** No es accionable con datos del cliente: es una limitación que
  hay que declarar. 13 de los 26 documentos evaluables (más 3 fotos) son escaneos o fotos puras y ahí
  la edición se hizo dentro del mapa de bits; **4 de los 5 adulterados no detectados son de ese tipo**
  y ajustar umbrales no los recupera. Leer el píxel es trabajo nuestro (N8/N9); lo que **no** cabe es
  pedirle al cliente que lo resuelva.
- **"El motor solo puede dar un limpio con sentido en 4 de 14 legítimos"** y **"a nivel de titular la
  detección es 4 de 5, no 7 de 12"**: son advertencias de **interpretación**, no pendientes. Se
  traducen en una regla de interfaz (lo no aplicable nunca se pinta de verde) que ya cubre N17.
- **La nomenclatura con fecha**: obsoleta y deliberadamente cambiada. **No llevarla al cliente.**
- **La asimetría del validador de auditoría** (no pasa el tipo, así que una exención no aplica en el
  camino de línea de comandos aunque sí en producción): no es un defecto de producción ni un pendiente
  del cliente; es una inconsistencia menor que confundirá a quien audite un documento con la línea de
  comandos. Se anota, no se lista.
- **Volver a pedir el corpus** para la prueba con Diana: **está en disco** (15 + 16 documentos, más las
  31 copias renombradas en el árbol de siembra). Lo que sí se pide es **ampliarlo** (petición C).
  Recordatorio de datos personales: esa carpeta y sus derivados **no se versionan** y se borran o
  cifran al terminar el ajuste del motor.
- **Volver a pedir el CSV de EPS** para sembrar el checklist: el arreglo es **nuestro** (N29) porque
  los datos derivados ya están versionados. Solo pedirlo si se quiere el catálogo completo de 64 EPS
  con NIT, que sirve como listado de entidades (A4).
- **Una imprecisión de un informe de regresión** (cita un documento como "caso oro" de un aviso cuando
  el aviso dispara en otro): el propio informe la declara. Es nota de lectura, no pendiente de código.
- **Las carpetas de sistema "vacías"**: están en el árbol a propósito para que la estructura no cambie
  al implementar la fase 2 (la de control ya aloja la configuración de reglas). No es un pendiente por
  sí mismo; su uso está dentro de N19 y N21. Lo que **no** hay que hacer es venderlas como
  funcionalidad existente en la demostración.
