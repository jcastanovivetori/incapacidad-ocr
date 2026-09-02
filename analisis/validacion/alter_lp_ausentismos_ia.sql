-- ===========================================================================
--  PROPUESTA de columnas nuevas en la tabla STAGING lp_ausentismos_ia.
--  NO EJECUTADO: requiere autorización del cliente (pregunta abierta
--  "PERSISTIR EL FIN IMPRESO" del expediente de validación).
--
--  Copia para el expediente. El archivo CANÓNICO que se aplica en el proyecto es
--      incapacidad-ocr/sql/migracion_reglas_tiempo.sql
--  (idempotente, MySQL 8.4, incluye además las dos tablas de configuración de las
--  reglas). Si hay que cambiar algo, se cambia allí; esta copia es documental.
--
--  Aplicar (cuando el cliente lo autorice):
--      docker exec -i ocr-db mysql -uocr -pocr ASTGU < sql/migracion_reglas_tiempo.sql
--
--  POR QUÉ hacen falta estas cuatro columnas
--  -----------------------------------------
--  1) `fechafin_leida` / `dias_leidos` — EVIDENCIA de lo que el documento IMPRIME.
--     Hoy la fila guarda `fechainicio`, `Numerodias` y `fechavencimiento` CALCULADO;
--     la reconciliación (`extract.normalizar_fechas`) re-deriva una fecha fin que no
--     cuadre con los días, así que la contradicción —la señal de alteración más
--     barata de detectar y la única respaldada por el corpus— desaparecía del
--     registro y ni el motor ni la persona podían auditarla después contra el papel.
--     Son columnas de SOLO LECTURA para la revisión: `db._COLS_ACTUALIZABLES` NO las
--     incluye, para que una corrección manual no pise la evidencia.
--  2) `alertas_tiempos` / `severidad_tiempos` — canal propio del veredicto temporal.
--     Permite ORDENAR la cola por gravedad (~7000 casos/mes) y distinguir "los
--     tiempos no cuadran" de "no encontré la cédula", que hoy comparten la columna
--     `problemas` (TEXT) y por tanto no se pueden filtrar ni contar.
--
--  Alternativa si NO se autoriza el ALTER: dejar las dos primeras como texto dentro
--  de `observaciones`. Se pierde la posibilidad de consultar/ordenar por ellas y la
--  garantía de que la revisión manual no las sobre-escriba.
-- ===========================================================================
USE ASTGU;

ALTER TABLE lp_ausentismos_ia
  ADD COLUMN IF NOT EXISTS fechafin_leida    DATE         NULL AFTER documentos_faltantes,
  ADD COLUMN IF NOT EXISTS dias_leidos       INT          NULL AFTER fechafin_leida,
  ADD COLUMN IF NOT EXISTS alertas_tiempos   VARCHAR(255) NULL AFTER dias_leidos,
  ADD COLUMN IF NOT EXISTS severidad_tiempos VARCHAR(10)  NULL AFTER alertas_tiempos;

-- Índice para ordenar la cola de revisión por gravedad de los tiempos.
CREATE INDEX IF NOT EXISTS idx_ia_sev_tiempos ON lp_ausentismos_ia (severidad_tiempos);

-- Comprobación posterior (no modifica nada):
--   SELECT id, fechainicio, Numerodias, fechavencimiento,
--          fechafin_leida, dias_leidos, severidad_tiempos, alertas_tiempos
--     FROM lp_ausentismos_ia
--    WHERE severidad_tiempos IS NOT NULL
--    ORDER BY FIELD(severidad_tiempos,'GRAVE','MEDIA','LEVE'), id DESC;
