-- ===========================================================================
--  Migración: veredicto TEMPORAL con canal propio + configuración en caliente.
--
--  Por qué hace falta correrla a mano: `sql/init.sql` solo se ejecuta en el PRIMER
--  arranque de un volumen vacío (ver CLAUDE.md §Gotchas). En una BD que ya existe
--  —y en la BD ASTGU real del cliente— hay que aplicar estos ALTER/CREATE.
--
--  Es IDEMPOTENTE: se puede correr varias veces (usa IF NOT EXISTS, soportado por
--  MySQL 8.4, que es la versión del proyecto).
--
--    docker exec -i ocr-db mysql -uocr -pocr ASTGU < sql/migracion_reglas_tiempo.sql
-- ===========================================================================
USE ASTGU;

-- --------------------------------------------------------------- staging: evidencia
-- `fechafin_leida` y `dias_leidos` guardan lo que el documento IMPRIME, aunque no
-- cuadre. Sin estas columnas la reconciliación (extract.normalizar_fechas) re-deriva la
-- fecha fin y la contradicción temporal se pierde antes de llegar al auxiliar.
ALTER TABLE lp_ausentismos_ia
  ADD COLUMN IF NOT EXISTS fechafin_leida    DATE         NULL AFTER documentos_faltantes,
  ADD COLUMN IF NOT EXISTS dias_leidos       INT          NULL AFTER fechafin_leida,
  ADD COLUMN IF NOT EXISTS alertas_tiempos   VARCHAR(255) NULL AFTER dias_leidos,
  ADD COLUMN IF NOT EXISTS severidad_tiempos VARCHAR(10)  NULL AFTER alertas_tiempos;

-- Índice para ordenar la cola de revisión por gravedad de los tiempos (~7000 casos/mes).
CREATE INDEX IF NOT EXISTS idx_ia_sev_tiempos ON lp_ausentismos_ia (severidad_tiempos);

-- ------------------------------------------ configuración en caliente (sin desplegar)
CREATE TABLE IF NOT EXISTS lp_reglas_tiempo_ia (
  codigo         VARCHAR(48) PRIMARY KEY,
  severidad      VARCHAR(10)  NULL,
  activa         TINYINT(1)   NULL,
  nota           VARCHAR(200) NULL,
  actualizado_en TIMESTAMP    NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS lp_umbrales_tiempo_ia (
  nombre         VARCHAR(48) PRIMARY KEY,
  valor          INT          NOT NULL,
  nota           VARCHAR(200) NULL,
  actualizado_en TIMESTAMP    NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
) ENGINE=InnoDB;

-- Las tablas se dejan VACÍAS a propósito: vacío = "usa los defaults del código".
-- Ejemplos de uso (comentados; descomentar el que se necesite):
--
--   -- bajar de tono una regla ruidosa sin desactivarla (deja de bloquear, sigue avisando)
--   INSERT INTO lp_reglas_tiempo_ia (codigo, severidad, nota) VALUES
--     ('T12_DIAS_LETRA_DISCREPA','LEVE','2026-09: ruido del OCR en letras — pidio RH')
--   ON DUPLICATE KEY UPDATE severidad=VALUES(severidad), nota=VALUES(nota);
--
--   -- desactivar una regla por completo (última opción; queda registrado quién y por qué)
--   INSERT INTO lp_reglas_tiempo_ia (codigo, activa, nota) VALUES
--     ('T09_INICIO_EN_FUTURO', 0, '2026-09: la EPS X emite con fecha adelantada')
--   ON DUPLICATE KEY UPDATE activa=VALUES(activa), nota=VALUES(nota);
--
--   -- mover un umbral (fuera de su rango admisible se ignora con aviso, no se aplica)
--   INSERT INTO lp_umbrales_tiempo_ia (nombre, valor, nota) VALUES
--     ('dias_sin_respaldo_aviso', 120, '2026-09: Gruppo quiere avisar antes')
--   ON DUPLICATE KEY UPDATE valor=VALUES(valor), nota=VALUES(nota);
