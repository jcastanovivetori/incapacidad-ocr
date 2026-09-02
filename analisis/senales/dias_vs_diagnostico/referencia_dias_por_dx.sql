-- ===========================================================================
--  referencia_dias_por_dx.sql
--  De donde sale el RANGO ESPERADO DE DIAS POR DIAGNOSTICO del check
--  DIAS_VS_DX_RANGO_HISTORICO (familia dias_vs_diagnostico).
--
--  Fuente: BD ASTGU del ERP, tabla real `lpausentismos` (esquema en
--  ../../../Mentoria Diana/Solucion Middleware IA SST/middleware-ia-gruppo/sql/
--  01_tabla_erp_lpausentismos.sql) unida a `lpdiagnosticos` (codigo CIE-10).
--  Es 100% LOCAL: la BD es del cliente, no hay servicio externo ni IA.
--
--  IMPORTANTE - hoy NO se puede correr en esta maquina: Docker no esta arriba y no
--  existe ningun dump del historico en disco (`sql/init.sql` del repo solo trae 8
--  diagnosticos de demo). Por eso la sonda devuelve SIN_INSUMO para este check.
--
--  Salida esperada por la sonda: `referencia_dias_por_dx.json` con
--    {"celdas": {"<clave>": {"nivel","n","p05","p50","p95","p99","max"}}}
--  donde <clave> es el codigo de 4 caracteres (M54.5), la categoria de 3 (M54)
--  o el capitulo (M), segun el nivel que haya alcanzado n >= 30.
-- ===========================================================================

-- ---------------------------------------------------------------------------
-- 0) Cuanto historico hay, antes de calcular nada.
--    Si `n_utiles` es bajo (< ~5.000) o cubre < 2 anos, NO se activa el check.
-- ---------------------------------------------------------------------------
SELECT COUNT(*)                                   AS n_filas,
       SUM(a.prorroga = 0
           AND a.idlpausentismo_inicial IS NULL
           AND a.Numerodias BETWEEN 1 AND 540)    AS n_utiles,
       MIN(a.fechainicio)                         AS desde,
       MAX(a.fechainicio)                         AS hasta,
       COUNT(DISTINCT a.idlpdiagnosticos)         AS dx_distintos
FROM   lpausentismos a;

-- ---------------------------------------------------------------------------
-- 1) Universo de referencia (vista de trabajo).
--    Reglas de inclusion, todas explicitas:
--      * Solo CERTIFICADO INICIAL: `prorroga = 0 AND idlpausentismo_inicial IS NULL`.
--        Motivo: del documento leemos los dias de UN certificado, no del episodio
--        completo. Mezclar prorrogas infla la cola derecha y mata el check.
--      * Solo tipos con duracion CLINICA: 2 accidente trabajo, 3 enfermedad general,
--        8 enfermedad laboral, 11 transito no laboral. Se EXCLUYEN 5/9/10 (maternidad,
--        paternidad, prelicencia) y 7/12/13 (permisos y vacaciones) porque su duracion
--        la fija la ley, no el diagnostico -> para esos manda el piso legal, no el p95.
--      * `Numerodias` en el rango valido de dominio del repo (1..540).
-- ---------------------------------------------------------------------------
CREATE OR REPLACE VIEW v_dias_dx_base AS
SELECT UPPER(REPLACE(d.codigo, '.', '')) AS cie_plano,
       a.Numerodias                      AS dias
FROM   lpausentismos   a
JOIN   lpdiagnosticos  d ON d.idlpdiagnosticos = a.idlpdiagnosticos
WHERE  a.prorroga = 0
  AND  a.idlpausentismo_inicial IS NULL
  AND  a.idlptipoausentismo IN (2, 3, 8, 11)
  AND  a.Numerodias BETWEEN 1 AND 540
  AND  d.codigo IS NOT NULL AND d.codigo <> '';

-- ---------------------------------------------------------------------------
-- 2) Percentiles por celda, en los 3 niveles de granularidad (backoff).
--    MySQL 8.4 tiene funciones de ventana -> PERCENTILE_CONT via NTILE no hace
--    falta: se usa PERCENT_RANK sobre la particion y se toma el primer valor que
--    supera el percentil. Se emite un solo resultado con la columna `nivel`.
-- ---------------------------------------------------------------------------
WITH clasificado AS (
    SELECT cie_plano, dias, 'categoria4' AS nivel,
           CONCAT(SUBSTRING(cie_plano, 1, 3), '.', SUBSTRING(cie_plano, 4, 1)) AS clave
    FROM   v_dias_dx_base WHERE CHAR_LENGTH(cie_plano) >= 4
    UNION ALL
    SELECT cie_plano, dias, 'categoria3', SUBSTRING(cie_plano, 1, 3) FROM v_dias_dx_base
    UNION ALL
    SELECT cie_plano, dias, 'capitulo',   SUBSTRING(cie_plano, 1, 1) FROM v_dias_dx_base
),
rankeado AS (
    SELECT clave, nivel, dias,
           PERCENT_RANK() OVER (PARTITION BY clave, nivel ORDER BY dias) AS pr,
           COUNT(*)       OVER (PARTITION BY clave, nivel)               AS n
    FROM   clasificado
)
SELECT clave,
       nivel,
       n,
       MIN(CASE WHEN pr >= 0.05 THEN dias END) AS p05,
       MIN(CASE WHEN pr >= 0.50 THEN dias END) AS p50,
       MIN(CASE WHEN pr >= 0.95 THEN dias END) AS p95,
       MIN(CASE WHEN pr >= 0.99 THEN dias END) AS p99,
       MAX(dias)                               AS max_dias
FROM   rankeado
GROUP  BY clave, nivel, n
HAVING n >= 30                 -- N_MIN_HISTORICO de la sonda; celdas con menos, SIN_INSUMO
ORDER  BY nivel, clave;

-- ---------------------------------------------------------------------------
-- 3) CALIBRACION OBLIGATORIA antes de activar el check.
--    El historico se asume LEGITIMO: cualquier umbral que marque mas del ~1% de
--    esas filas es inusable en produccion. Esta consulta mide exactamente eso
--    (tasa de falsos positivos esperada) para la regla dias > p99 AND dias > 3*p50.
--    Si `tasa_marcadas` > 0.01 -> el check nace DESACTIVADO.
-- ---------------------------------------------------------------------------
-- (se corre reemplazando `ref` por la tabla materializada del paso 2, nivel categoria4)
--
-- SELECT COUNT(*)                                             AS n,
--        SUM(b.dias > r.p99 AND b.dias > 3 * GREATEST(r.p50,1)) AS marcadas,
--        SUM(b.dias > r.p99 AND b.dias > 3 * GREATEST(r.p50,1)) / COUNT(*) AS tasa_marcadas
-- FROM   v_dias_dx_base b
-- JOIN   ref r ON r.clave = CONCAT(SUBSTRING(b.cie_plano,1,3),'.',SUBSTRING(b.cie_plano,4,1))
-- WHERE  r.nivel = 'categoria4';

-- ---------------------------------------------------------------------------
-- 4) Contra-evidencia que ya conocemos y que hay que revisar en el mismo query:
--    el repo dejo escrito que "ni los dias ni el diagnostico predicen el nivel de
--    incapacidad de forma limpia: el mismo CIE-10 aparece con niveles distintos y
--    los rangos de dias se solapan". Esta consulta mide la DISPERSION por dx: si
--    el rango p05..p95 de la mayoria de las celdas es muy ancho (p.ej. 1..30), el
--    check tendra recall casi nulo y hay que decirlo antes de implementarlo.
-- ---------------------------------------------------------------------------
-- SELECT nivel,
--        COUNT(*)                        AS celdas,
--        AVG(p95 - p05)                  AS ancho_medio_p05_p95,
--        AVG(p95 / GREATEST(p50, 1))     AS razon_media_p95_p50
-- FROM   ref GROUP BY nivel;
