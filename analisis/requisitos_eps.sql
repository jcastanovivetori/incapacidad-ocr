-- ===========================================================================
--  requisitos_eps.sql - requisitos documentales REALES por EPS + tipo de ausentismo
--  Fuente: <descargas>/lpeps.csv, columna `cheklistradicaciones`
--          (JSON {"ausentismos":[...]} embebido). El CSV NO esta bien citado: el JSON
--          viene envuelto en comillas dobles DUPLICADAS y contiene comas, por lo que
--          csv.DictReader lo parte en la primera coma -> se recupero por subcadena
--          ('{"ausentismos"' .. ultimo '}') y se valido con json.loads: 19/19 OK, 0 errores.
--  Generado por dataset-falsedad/_gen_sql.py - 100% local, sin PII (solo catalogos).
--
--  COBERTURA MEDIDA
--    * 64 EPS en el catalogo; 19 traen checklist JSON (las otras 45 traen el literal 'I',
--      que es como el export escribe NULL - igual que observaciones_radicacion y codigoarl).
--    * 19 EPS x 7 tipos de ausentismo (2,3,5,8,9,10,11) = 133 combinaciones; 66 con documentos.
--    * 320 filas de requisito (este archivo) - 10 nombres de documento distintos.
--    * Los tipos 7/12/13 (permisos y vacaciones) NO existen en el checklist: no se radican
--      ante la EPS (son internos) -> para esos sigue mandando erp.REQUISITOS_DEFAULT.
--
--  DDL de destino (incapacidad-ocr/sql/init.sql):
--    lprequisitos_eps(id AI PK, idlpentidad INT NOT NULL, idlptipoausentismo INT NOT NULL,
--                     documento VARCHAR(60) NOT NULL, obligatorio TINYINT(1) NOT NULL DEFAULT 1)
--
--  MAPEO idlpeps -> idlpentidad
--    Se usa `idlpeps` TAL CUAL como `idlpentidad`: en el ERP real la vista que consulta
--    erp.Lookups (`vlpentidades_ss`) se define como `idlpentidad AS idlpeps`, o sea es la
--    MISMA llave. OJO: los ids DEMO de sql/init.sql (1..8) son OTROS (demo 1 = NUEVA EPS,
--    pero el id real de NUEVA EPS S.A es 36; demo 5 = SALUD MIA vs real 5 = ALIANZA SALUD)
--    -> cargar esto en la BD demo sin limpiarla primero le cuelga los requisitos a la EPS
--    equivocada. Ver el bloque OPCIONAL 1 al final.
--
--  MAPEO nombredocumento -> codigo de documento del repo (erp.DOC_CANON / erp.canon_doc)
--    'CERTIFICADO DE INCAPACIDAD'         -> INCAPACIDAD
--    'HISTORIA CLINICA'                   -> HISTORIA_CLINICA
--    'CEDULA DEL TRABAJADOR'              -> CEDULA
--    'CERTIFICADO NACIDO VIVO'            -> CERTIFICADO_NACIDO_VIVO
--    'REGISTRO CIVIL'                     -> REGISTRO_CIVIL_NACIMIENTO
--    'FURIPS'                             -> FURIPS
--    SIN equivalente hoy en erp.DOC_CANON -> se crean codigos NUEVOS (no se fuerza un
--    sinonimo existente, que enmascararia el requisito):
--    'SOAT'                               -> SOAT
--    'REPORTE ACCIDENTE DE TRANSITO RAT'  -> RAT
--    'FORMATO DE DESCARTE EVENTO LABORAL' -> DESCARTE_EVENTO_LABORAL
--    'CERTICADO LABORAL'                  -> CERTIFICADO_LABORAL  (typo del ERP: 'CERTICADO')
--    NO se mapeo nada a EPICRISIS ni a FURAT: ninguna EPS pide 'EPICRISIS' (piden 'HISTORIA
--    CLINICA'; el grupo de equivalencia EPICRISIS<->HISTORIA_CLINICA del repo ya la acepta),
--    y FURAT no aparece en NINGUNA de las 320 filas (el FURAT va a la ARL, no a la EPS).
--    PENDIENTE en el paquete (fase siguiente; aqui NO se toca codigo): el TIPODOC del nombre
--    de archivo solo admite letras (`{cedula}_{TIPODOC}`), asi que para que colapse a estos
--    codigos hay que agregar a erp.DOC_CANON:
--        'SOAT': 'SOAT', 'RAT': 'RAT',
--        'DESCARTELABORAL': 'DESCARTE_EVENTO_LABORAL',
--        'CERTIFICADOLABORAL': 'CERTIFICADO_LABORAL'
--    Sin eso, erp.canon_doc('DESCARTELABORAL') devuelve 'DESCARTELABORAL', que no iguala al
--    codigo de estas filas y el soporte se contaria como faltante.
--
--  obligatorio = 1 en TODAS las filas: el JSON de la EPS no tiene ningun flag de
--    opcionalidad, todo documento listado es exigido. (Nota: erp.Lookups.documentos_requeridos
--    hoy NO filtra por `obligatorio`, asi que cualquier fila cuenta como obligatoria.)
--
--  METADATOS QUE ESTE DDL NO PUEDE GUARDAR (quedan solo como comentario por EPS/tipo):
--    tipo_envio      1 = todo en UN archivo / 2 = varios archivos separados (medido: env=1 =>
--                    max(archivo)=1 en 21/21 combos; env=2 => max(archivo)>=2 en 47/47).
--    medioradicacion canal de radicacion; es CONSTANTE por EPS (ninguna mezcla 1 y 2).
--    archivo         en cual de los N archivos va cada documento (0 = sin asignar).
--    Ver el bloque OPCIONAL 2 al final si se decide persistirlos.
-- ===========================================================================

USE ASTGU;

-- Recarga idempotente: solo borra los requisitos de las 19 EPS que SI traen checklist.
DELETE FROM lprequisitos_eps WHERE idlpentidad IN (5, 7, 11, 19, 20, 23, 26, 27, 32, 36, 40, 45, 46, 47, 49, 53, 54, 62, 64);

INSERT INTO lprequisitos_eps (idlpentidad, idlptipoausentismo, documento, obligatorio) VALUES

-- ------------------------------------------------------------------
-- idlpeps=5  ALIANZA SALUD  (NIT 830113831)
--   tipos SIN documentos configurados (la EPS no exige nada / sin definir): 2 ACCIDENTE DE TRABAJO; 5 LICENCIA MATERNIDAD; 10 PRELICENCIA
--   tipo 3 ENFERMEDAD GENERAL | tipo_envio=1 medioradicacion=2 | 2 docs en 0 archivo(s): INCAPACIDAD#0, HISTORIA_CLINICA#0
  (5, 3, 'INCAPACIDAD', 1),
  (5, 3, 'HISTORIA_CLINICA', 1),
--   tipo 8 ENFERMEDAD LABORAL | tipo_envio=0 medioradicacion=0 | 5 docs en 3 archivo(s): INCAPACIDAD#3, HISTORIA_CLINICA#2, CEDULA#3, CERTIFICADO_NACIDO_VIVO#1, REGISTRO_CIVIL_NACIMIENTO#1
  (5, 8, 'INCAPACIDAD', 1),
  (5, 8, 'HISTORIA_CLINICA', 1),
  (5, 8, 'CEDULA', 1),
  (5, 8, 'CERTIFICADO_NACIDO_VIVO', 1),
  (5, 8, 'REGISTRO_CIVIL_NACIMIENTO', 1),
--   tipo 9 LICENCIA PATERNIDAD | tipo_envio=2 medioradicacion=2 | 4 docs en 2 archivo(s): HISTORIA_CLINICA#2, CEDULA#2, CERTIFICADO_NACIDO_VIVO#1, REGISTRO_CIVIL_NACIMIENTO#1
  (5, 9, 'HISTORIA_CLINICA', 1),
  (5, 9, 'CEDULA', 1),
  (5, 9, 'CERTIFICADO_NACIDO_VIVO', 1),
  (5, 9, 'REGISTRO_CIVIL_NACIMIENTO', 1),
--   tipo 11 TRANSITO NO LABORAL | tipo_envio=1 medioradicacion=2 | 5 docs en 1 archivo(s): INCAPACIDAD#1, HISTORIA_CLINICA#1, CEDULA#1, SOAT#1, FURIPS#1
  (5, 11, 'INCAPACIDAD', 1),
  (5, 11, 'HISTORIA_CLINICA', 1),
  (5, 11, 'CEDULA', 1),
  (5, 11, 'SOAT', 1),
  (5, 11, 'FURIPS', 1),

-- ------------------------------------------------------------------
-- idlpeps=7  ASMET SALUD  (NIT 900935126)
--   tipos SIN documentos configurados (la EPS no exige nada / sin definir): 2 ACCIDENTE DE TRABAJO; 8 ENFERMEDAD LABORAL; 10 PRELICENCIA
--   tipo 3 ENFERMEDAD GENERAL | tipo_envio=2 medioradicacion=2 | 2 docs en 2 archivo(s): INCAPACIDAD#1, HISTORIA_CLINICA#2
  (7, 3, 'INCAPACIDAD', 1),
  (7, 3, 'HISTORIA_CLINICA', 1),
--   tipo 5 LICENCIA MATERNIDAD | tipo_envio=2 medioradicacion=2 | 5 docs en 4 archivo(s): INCAPACIDAD#1, HISTORIA_CLINICA#2, CEDULA#1, CERTIFICADO_NACIDO_VIVO#4, REGISTRO_CIVIL_NACIMIENTO#3
  (7, 5, 'INCAPACIDAD', 1),
  (7, 5, 'HISTORIA_CLINICA', 1),
  (7, 5, 'CEDULA', 1),
  (7, 5, 'CERTIFICADO_NACIDO_VIVO', 1),
  (7, 5, 'REGISTRO_CIVIL_NACIMIENTO', 1),
--   tipo 9 LICENCIA PATERNIDAD | tipo_envio=2 medioradicacion=2 | 4 docs en 2 archivo(s): HISTORIA_CLINICA#2, CEDULA#2, CERTIFICADO_NACIDO_VIVO#1, REGISTRO_CIVIL_NACIMIENTO#1
  (7, 9, 'HISTORIA_CLINICA', 1),
  (7, 9, 'CEDULA', 1),
  (7, 9, 'CERTIFICADO_NACIDO_VIVO', 1),
  (7, 9, 'REGISTRO_CIVIL_NACIMIENTO', 1),
--   tipo 11 TRANSITO NO LABORAL | tipo_envio=2 medioradicacion=2 | 6 docs en 6 archivo(s): INCAPACIDAD#2, HISTORIA_CLINICA#1, SOAT#6, RAT#4, DESCARTE_EVENTO_LABORAL#3, FURIPS#5
  (7, 11, 'INCAPACIDAD', 1),
  (7, 11, 'HISTORIA_CLINICA', 1),
  (7, 11, 'SOAT', 1),
  (7, 11, 'RAT', 1),
  (7, 11, 'DESCARTE_EVENTO_LABORAL', 1),
  (7, 11, 'FURIPS', 1),

-- ------------------------------------------------------------------
-- idlpeps=11  CAPITAL SALUD  (NIT 900298372)
--   tipos SIN documentos configurados (la EPS no exige nada / sin definir): 2 ACCIDENTE DE TRABAJO; 8 ENFERMEDAD LABORAL; 10 PRELICENCIA
--   tipo 3 ENFERMEDAD GENERAL | tipo_envio=2 medioradicacion=1 | 2 docs en 2 archivo(s): INCAPACIDAD#2, HISTORIA_CLINICA#1
  (11, 3, 'INCAPACIDAD', 1),
  (11, 3, 'HISTORIA_CLINICA', 1),
--   tipo 5 LICENCIA MATERNIDAD | tipo_envio=2 medioradicacion=1 | 5 docs en 3 archivo(s): INCAPACIDAD#1, HISTORIA_CLINICA#3, CEDULA#0, CERTIFICADO_NACIDO_VIVO#2, REGISTRO_CIVIL_NACIMIENTO#2
  (11, 5, 'INCAPACIDAD', 1),
  (11, 5, 'HISTORIA_CLINICA', 1),
  (11, 5, 'CEDULA', 1),
  (11, 5, 'CERTIFICADO_NACIDO_VIVO', 1),
  (11, 5, 'REGISTRO_CIVIL_NACIMIENTO', 1),
--   tipo 9 LICENCIA PATERNIDAD | tipo_envio=2 medioradicacion=1 | 4 docs en 3 archivo(s): HISTORIA_CLINICA#1, CEDULA#3, CERTIFICADO_NACIDO_VIVO#2, REGISTRO_CIVIL_NACIMIENTO#2
  (11, 9, 'HISTORIA_CLINICA', 1),
  (11, 9, 'CEDULA', 1),
  (11, 9, 'CERTIFICADO_NACIDO_VIVO', 1),
  (11, 9, 'REGISTRO_CIVIL_NACIMIENTO', 1),
--   tipo 11 TRANSITO NO LABORAL | tipo_envio=2 medioradicacion=1 | 5 docs en 4 archivo(s): INCAPACIDAD#1, HISTORIA_CLINICA#2, CEDULA#4, SOAT#3, FURIPS#3
  (11, 11, 'INCAPACIDAD', 1),
  (11, 11, 'HISTORIA_CLINICA', 1),
  (11, 11, 'CEDULA', 1),
  (11, 11, 'SOAT', 1),
  (11, 11, 'FURIPS', 1),

-- ------------------------------------------------------------------
-- idlpeps=19  COMFENALCO VALLE  (NIT 890303093)
--   tipos SIN documentos configurados (la EPS no exige nada / sin definir): 2 ACCIDENTE DE TRABAJO; 8 ENFERMEDAD LABORAL; 10 PRELICENCIA
--   tipo 3 ENFERMEDAD GENERAL | tipo_envio=2 medioradicacion=2 | 2 docs en 2 archivo(s): INCAPACIDAD#1, HISTORIA_CLINICA#2
  (19, 3, 'INCAPACIDAD', 1),
  (19, 3, 'HISTORIA_CLINICA', 1),
--   tipo 5 LICENCIA MATERNIDAD | tipo_envio=2 medioradicacion=2 | 5 docs en 4 archivo(s): INCAPACIDAD#1, HISTORIA_CLINICA#2, CEDULA#1, CERTIFICADO_NACIDO_VIVO#4, REGISTRO_CIVIL_NACIMIENTO#3
  (19, 5, 'INCAPACIDAD', 1),
  (19, 5, 'HISTORIA_CLINICA', 1),
  (19, 5, 'CEDULA', 1),
  (19, 5, 'CERTIFICADO_NACIDO_VIVO', 1),
  (19, 5, 'REGISTRO_CIVIL_NACIMIENTO', 1),
--   tipo 9 LICENCIA PATERNIDAD | tipo_envio=2 medioradicacion=2 | 4 docs en 3 archivo(s): HISTORIA_CLINICA#3, CEDULA#3, CERTIFICADO_NACIDO_VIVO#2, REGISTRO_CIVIL_NACIMIENTO#1
  (19, 9, 'HISTORIA_CLINICA', 1),
  (19, 9, 'CEDULA', 1),
  (19, 9, 'CERTIFICADO_NACIDO_VIVO', 1),
  (19, 9, 'REGISTRO_CIVIL_NACIMIENTO', 1),
--   tipo 11 TRANSITO NO LABORAL | tipo_envio=2 medioradicacion=2 | 6 docs en 6 archivo(s): INCAPACIDAD#2, HISTORIA_CLINICA#1, SOAT#6, RAT#4, DESCARTE_EVENTO_LABORAL#3, FURIPS#5
  (19, 11, 'INCAPACIDAD', 1),
  (19, 11, 'HISTORIA_CLINICA', 1),
  (19, 11, 'SOAT', 1),
  (19, 11, 'RAT', 1),
  (19, 11, 'DESCARTE_EVENTO_LABORAL', 1),
  (19, 11, 'FURIPS', 1),

-- ------------------------------------------------------------------
-- idlpeps=20  COMPENSAR  (NIT 860066942)
--   tipos SIN documentos configurados (la EPS no exige nada / sin definir): 2 ACCIDENTE DE TRABAJO; 8 ENFERMEDAD LABORAL; 10 PRELICENCIA
--   tipo 3 ENFERMEDAD GENERAL | tipo_envio=1 medioradicacion=2 | 2 docs en 0 archivo(s): INCAPACIDAD#0, HISTORIA_CLINICA#0
  (20, 3, 'INCAPACIDAD', 1),
  (20, 3, 'HISTORIA_CLINICA', 1),
--   tipo 5 LICENCIA MATERNIDAD | tipo_envio=2 medioradicacion=2 | 5 docs en 0 archivo(s): INCAPACIDAD#0, HISTORIA_CLINICA#0, CEDULA#0, CERTIFICADO_NACIDO_VIVO#0, REGISTRO_CIVIL_NACIMIENTO#0
  (20, 5, 'INCAPACIDAD', 1),
  (20, 5, 'HISTORIA_CLINICA', 1),
  (20, 5, 'CEDULA', 1),
  (20, 5, 'CERTIFICADO_NACIDO_VIVO', 1),
  (20, 5, 'REGISTRO_CIVIL_NACIMIENTO', 1),
--   tipo 9 LICENCIA PATERNIDAD | tipo_envio=1 medioradicacion=2 | 5 docs en 0 archivo(s): INCAPACIDAD#0, HISTORIA_CLINICA#0, CEDULA#0, CERTIFICADO_NACIDO_VIVO#0, REGISTRO_CIVIL_NACIMIENTO#0
  (20, 9, 'INCAPACIDAD', 1),
  (20, 9, 'HISTORIA_CLINICA', 1),
  (20, 9, 'CEDULA', 1),
  (20, 9, 'CERTIFICADO_NACIDO_VIVO', 1),
  (20, 9, 'REGISTRO_CIVIL_NACIMIENTO', 1),
--   tipo 11 TRANSITO NO LABORAL | tipo_envio=1 medioradicacion=2 | 5 docs en 1 archivo(s): INCAPACIDAD#1, HISTORIA_CLINICA#1, CEDULA#1, SOAT#1, FURIPS#1
  (20, 11, 'INCAPACIDAD', 1),
  (20, 11, 'HISTORIA_CLINICA', 1),
  (20, 11, 'CEDULA', 1),
  (20, 11, 'SOAT', 1),
  (20, 11, 'FURIPS', 1),

-- ------------------------------------------------------------------
-- idlpeps=23  COOSALUD E.S.S.  (NIT 900226715)
--   tipos SIN documentos configurados (la EPS no exige nada / sin definir): 2 ACCIDENTE DE TRABAJO; 3 ENFERMEDAD GENERAL; 10 PRELICENCIA
--   tipo 5 LICENCIA MATERNIDAD | tipo_envio=2 medioradicacion=2 | 5 docs en 3 archivo(s): INCAPACIDAD#3, HISTORIA_CLINICA#2, CEDULA#3, CERTIFICADO_NACIDO_VIVO#1, REGISTRO_CIVIL_NACIMIENTO#1
  (23, 5, 'INCAPACIDAD', 1),
  (23, 5, 'HISTORIA_CLINICA', 1),
  (23, 5, 'CEDULA', 1),
  (23, 5, 'CERTIFICADO_NACIDO_VIVO', 1),
  (23, 5, 'REGISTRO_CIVIL_NACIMIENTO', 1),
--   tipo 8 ENFERMEDAD LABORAL | tipo_envio=2 medioradicacion=2 | 2 docs en 2 archivo(s): INCAPACIDAD#2, HISTORIA_CLINICA#1
  (23, 8, 'INCAPACIDAD', 1),
  (23, 8, 'HISTORIA_CLINICA', 1),
--   tipo 9 LICENCIA PATERNIDAD | tipo_envio=2 medioradicacion=2 | 4 docs en 2 archivo(s): HISTORIA_CLINICA#2, CEDULA#2, CERTIFICADO_NACIDO_VIVO#1, REGISTRO_CIVIL_NACIMIENTO#1
  (23, 9, 'HISTORIA_CLINICA', 1),
  (23, 9, 'CEDULA', 1),
  (23, 9, 'CERTIFICADO_NACIDO_VIVO', 1),
  (23, 9, 'REGISTRO_CIVIL_NACIMIENTO', 1),
--   tipo 11 TRANSITO NO LABORAL | tipo_envio=2 medioradicacion=2 | 5 docs en 2 archivo(s): INCAPACIDAD#2, HISTORIA_CLINICA#1, CEDULA#1, SOAT#2, FURIPS#2
  (23, 11, 'INCAPACIDAD', 1),
  (23, 11, 'HISTORIA_CLINICA', 1),
  (23, 11, 'CEDULA', 1),
  (23, 11, 'SOAT', 1),
  (23, 11, 'FURIPS', 1),

-- ------------------------------------------------------------------
-- idlpeps=26  EMSSANAR  (NIT 901021565)
--   tipos SIN documentos configurados (la EPS no exige nada / sin definir): 2 ACCIDENTE DE TRABAJO; 8 ENFERMEDAD LABORAL; 10 PRELICENCIA
--   tipo 3 ENFERMEDAD GENERAL | tipo_envio=2 medioradicacion=2 | 2 docs en 2 archivo(s): INCAPACIDAD#1, HISTORIA_CLINICA#2
  (26, 3, 'INCAPACIDAD', 1),
  (26, 3, 'HISTORIA_CLINICA', 1),
--   tipo 5 LICENCIA MATERNIDAD | tipo_envio=2 medioradicacion=2 | 5 docs en 4 archivo(s): INCAPACIDAD#1, HISTORIA_CLINICA#2, CEDULA#1, CERTIFICADO_NACIDO_VIVO#4, REGISTRO_CIVIL_NACIMIENTO#3
  (26, 5, 'INCAPACIDAD', 1),
  (26, 5, 'HISTORIA_CLINICA', 1),
  (26, 5, 'CEDULA', 1),
  (26, 5, 'CERTIFICADO_NACIDO_VIVO', 1),
  (26, 5, 'REGISTRO_CIVIL_NACIMIENTO', 1),
--   tipo 9 LICENCIA PATERNIDAD | tipo_envio=2 medioradicacion=2 | 4 docs en 3 archivo(s): HISTORIA_CLINICA#3, CEDULA#3, CERTIFICADO_NACIDO_VIVO#2, REGISTRO_CIVIL_NACIMIENTO#1
  (26, 9, 'HISTORIA_CLINICA', 1),
  (26, 9, 'CEDULA', 1),
  (26, 9, 'CERTIFICADO_NACIDO_VIVO', 1),
  (26, 9, 'REGISTRO_CIVIL_NACIMIENTO', 1),
--   tipo 11 TRANSITO NO LABORAL | tipo_envio=2 medioradicacion=2 | 6 docs en 6 archivo(s): INCAPACIDAD#2, HISTORIA_CLINICA#1, SOAT#6, RAT#4, DESCARTE_EVENTO_LABORAL#3, FURIPS#5
  (26, 11, 'INCAPACIDAD', 1),
  (26, 11, 'HISTORIA_CLINICA', 1),
  (26, 11, 'SOAT', 1),
  (26, 11, 'RAT', 1),
  (26, 11, 'DESCARTE_EVENTO_LABORAL', 1),
  (26, 11, 'FURIPS', 1),

-- ------------------------------------------------------------------
-- idlpeps=27  FAMISANAR LTDA. CAFAM COLSUBSIDIO  (NIT 830003564)
--   tipos SIN documentos configurados (la EPS no exige nada / sin definir): 2 ACCIDENTE DE TRABAJO; 8 ENFERMEDAD LABORAL; 10 PRELICENCIA
--   tipo 3 ENFERMEDAD GENERAL | tipo_envio=1 medioradicacion=2 | 3 docs en 1 archivo(s): INCAPACIDAD#1, HISTORIA_CLINICA#1, CEDULA#1
  (27, 3, 'INCAPACIDAD', 1),
  (27, 3, 'HISTORIA_CLINICA', 1),
  (27, 3, 'CEDULA', 1),
--   tipo 5 LICENCIA MATERNIDAD | tipo_envio=1 medioradicacion=2 | 5 docs en 1 archivo(s): INCAPACIDAD#1, HISTORIA_CLINICA#1, CEDULA#1, CERTIFICADO_NACIDO_VIVO#1, REGISTRO_CIVIL_NACIMIENTO#1
  (27, 5, 'INCAPACIDAD', 1),
  (27, 5, 'HISTORIA_CLINICA', 1),
  (27, 5, 'CEDULA', 1),
  (27, 5, 'CERTIFICADO_NACIDO_VIVO', 1),
  (27, 5, 'REGISTRO_CIVIL_NACIMIENTO', 1),
--   tipo 9 LICENCIA PATERNIDAD | tipo_envio=1 medioradicacion=2 | 4 docs en 1 archivo(s): HISTORIA_CLINICA#1, CEDULA#1, CERTIFICADO_NACIDO_VIVO#1, REGISTRO_CIVIL_NACIMIENTO#1
  (27, 9, 'HISTORIA_CLINICA', 1),
  (27, 9, 'CEDULA', 1),
  (27, 9, 'CERTIFICADO_NACIDO_VIVO', 1),
  (27, 9, 'REGISTRO_CIVIL_NACIMIENTO', 1),
--   tipo 11 TRANSITO NO LABORAL | tipo_envio=1 medioradicacion=2 | 5 docs en 1 archivo(s): INCAPACIDAD#1, HISTORIA_CLINICA#1, CEDULA#1, SOAT#1, FURIPS#1
  (27, 11, 'INCAPACIDAD', 1),
  (27, 11, 'HISTORIA_CLINICA', 1),
  (27, 11, 'CEDULA', 1),
  (27, 11, 'SOAT', 1),
  (27, 11, 'FURIPS', 1),

-- ------------------------------------------------------------------
-- idlpeps=32  MALLAMAS  (NIT 837000084)
--   tipos SIN documentos configurados (la EPS no exige nada / sin definir): 2 ACCIDENTE DE TRABAJO; 8 ENFERMEDAD LABORAL; 10 PRELICENCIA
--   tipo 3 ENFERMEDAD GENERAL | tipo_envio=2 medioradicacion=1 | 2 docs en 2 archivo(s): INCAPACIDAD#2, HISTORIA_CLINICA#1
  (32, 3, 'INCAPACIDAD', 1),
  (32, 3, 'HISTORIA_CLINICA', 1),
--   tipo 5 LICENCIA MATERNIDAD | tipo_envio=2 medioradicacion=1 | 5 docs en 0 archivo(s): INCAPACIDAD#0, HISTORIA_CLINICA#0, CEDULA#0, CERTIFICADO_NACIDO_VIVO#0, REGISTRO_CIVIL_NACIMIENTO#0
  (32, 5, 'INCAPACIDAD', 1),
  (32, 5, 'HISTORIA_CLINICA', 1),
  (32, 5, 'CEDULA', 1),
  (32, 5, 'CERTIFICADO_NACIDO_VIVO', 1),
  (32, 5, 'REGISTRO_CIVIL_NACIMIENTO', 1),
--   tipo 9 LICENCIA PATERNIDAD | tipo_envio=2 medioradicacion=1 | 4 docs en 0 archivo(s): HISTORIA_CLINICA#0, CEDULA#0, CERTIFICADO_NACIDO_VIVO#0, REGISTRO_CIVIL_NACIMIENTO#0
  (32, 9, 'HISTORIA_CLINICA', 1),
  (32, 9, 'CEDULA', 1),
  (32, 9, 'CERTIFICADO_NACIDO_VIVO', 1),
  (32, 9, 'REGISTRO_CIVIL_NACIMIENTO', 1),
--   tipo 11 TRANSITO NO LABORAL | tipo_envio=2 medioradicacion=1 | 5 docs en 5 archivo(s): INCAPACIDAD#1, HISTORIA_CLINICA#2, CEDULA#5, SOAT#4, FURIPS#3
  (32, 11, 'INCAPACIDAD', 1),
  (32, 11, 'HISTORIA_CLINICA', 1),
  (32, 11, 'CEDULA', 1),
  (32, 11, 'SOAT', 1),
  (32, 11, 'FURIPS', 1),

-- ------------------------------------------------------------------
-- idlpeps=36  NUEVA EPS S.A  (NIT 900156264)
--   tipos SIN documentos configurados (la EPS no exige nada / sin definir): 2 ACCIDENTE DE TRABAJO; 8 ENFERMEDAD LABORAL; 10 PRELICENCIA
--   tipo 3 ENFERMEDAD GENERAL | tipo_envio=1 medioradicacion=2 | 2 docs en 1 archivo(s): INCAPACIDAD#1, HISTORIA_CLINICA#1
  (36, 3, 'INCAPACIDAD', 1),
  (36, 3, 'HISTORIA_CLINICA', 1),
--   tipo 5 LICENCIA MATERNIDAD | tipo_envio=1 medioradicacion=2 | 5 docs en 1 archivo(s): INCAPACIDAD#1, HISTORIA_CLINICA#1, CEDULA#1, CERTIFICADO_NACIDO_VIVO#1, REGISTRO_CIVIL_NACIMIENTO#1
  (36, 5, 'INCAPACIDAD', 1),
  (36, 5, 'HISTORIA_CLINICA', 1),
  (36, 5, 'CEDULA', 1),
  (36, 5, 'CERTIFICADO_NACIDO_VIVO', 1),
  (36, 5, 'REGISTRO_CIVIL_NACIMIENTO', 1),
--   tipo 9 LICENCIA PATERNIDAD | tipo_envio=1 medioradicacion=2 | 4 docs en 1 archivo(s): HISTORIA_CLINICA#1, CEDULA#1, CERTIFICADO_NACIDO_VIVO#1, REGISTRO_CIVIL_NACIMIENTO#1
  (36, 9, 'HISTORIA_CLINICA', 1),
  (36, 9, 'CEDULA', 1),
  (36, 9, 'CERTIFICADO_NACIDO_VIVO', 1),
  (36, 9, 'REGISTRO_CIVIL_NACIMIENTO', 1),
--   tipo 11 TRANSITO NO LABORAL | tipo_envio=1 medioradicacion=2 | 6 docs en 1 archivo(s): INCAPACIDAD#1, HISTORIA_CLINICA#1, SOAT#1, RAT#1, DESCARTE_EVENTO_LABORAL#1, FURIPS#1
  (36, 11, 'INCAPACIDAD', 1),
  (36, 11, 'HISTORIA_CLINICA', 1),
  (36, 11, 'SOAT', 1),
  (36, 11, 'RAT', 1),
  (36, 11, 'DESCARTE_EVENTO_LABORAL', 1),
  (36, 11, 'FURIPS', 1),

-- ------------------------------------------------------------------
-- idlpeps=40  SALUD TOTAL S.A. EPS ARS  (NIT 800130907)
--   tipos SIN documentos configurados (la EPS no exige nada / sin definir): 2 ACCIDENTE DE TRABAJO; 3 ENFERMEDAD GENERAL; 10 PRELICENCIA
--   tipo 5 LICENCIA MATERNIDAD | tipo_envio=2 medioradicacion=2 | 5 docs en 4 archivo(s): INCAPACIDAD#1, HISTORIA_CLINICA#2, CEDULA#1, CERTIFICADO_NACIDO_VIVO#4, REGISTRO_CIVIL_NACIMIENTO#3
  (40, 5, 'INCAPACIDAD', 1),
  (40, 5, 'HISTORIA_CLINICA', 1),
  (40, 5, 'CEDULA', 1),
  (40, 5, 'CERTIFICADO_NACIDO_VIVO', 1),
  (40, 5, 'REGISTRO_CIVIL_NACIMIENTO', 1),
--   tipo 8 ENFERMEDAD LABORAL | tipo_envio=2 medioradicacion=2 | 2 docs en 2 archivo(s): INCAPACIDAD#1, HISTORIA_CLINICA#2
  (40, 8, 'INCAPACIDAD', 1),
  (40, 8, 'HISTORIA_CLINICA', 1),
--   tipo 9 LICENCIA PATERNIDAD | tipo_envio=2 medioradicacion=2 | 4 docs en 3 archivo(s): HISTORIA_CLINICA#3, CEDULA#3, CERTIFICADO_NACIDO_VIVO#2, REGISTRO_CIVIL_NACIMIENTO#1
  (40, 9, 'HISTORIA_CLINICA', 1),
  (40, 9, 'CEDULA', 1),
  (40, 9, 'CERTIFICADO_NACIDO_VIVO', 1),
  (40, 9, 'REGISTRO_CIVIL_NACIMIENTO', 1),
--   tipo 11 TRANSITO NO LABORAL | tipo_envio=2 medioradicacion=2 | 6 docs en 6 archivo(s): INCAPACIDAD#2, HISTORIA_CLINICA#1, SOAT#6, RAT#4, DESCARTE_EVENTO_LABORAL#3, FURIPS#5
  (40, 11, 'INCAPACIDAD', 1),
  (40, 11, 'HISTORIA_CLINICA', 1),
  (40, 11, 'SOAT', 1),
  (40, 11, 'RAT', 1),
  (40, 11, 'DESCARTE_EVENTO_LABORAL', 1),
  (40, 11, 'FURIPS', 1),

-- ------------------------------------------------------------------
-- idlpeps=45  SANITAS S.A.  (NIT 800251440)
--   tipos SIN documentos configurados (la EPS no exige nada / sin definir): 2 ACCIDENTE DE TRABAJO; 8 ENFERMEDAD LABORAL; 10 PRELICENCIA
--   tipo 3 ENFERMEDAD GENERAL | tipo_envio=1 medioradicacion=2 | 2 docs en 1 archivo(s): INCAPACIDAD#1, HISTORIA_CLINICA#1
  (45, 3, 'INCAPACIDAD', 1),
  (45, 3, 'HISTORIA_CLINICA', 1),
--   tipo 5 LICENCIA MATERNIDAD | tipo_envio=1 medioradicacion=2 | 5 docs en 1 archivo(s): INCAPACIDAD#1, HISTORIA_CLINICA#1, CEDULA#1, CERTIFICADO_NACIDO_VIVO#1, REGISTRO_CIVIL_NACIMIENTO#1
  (45, 5, 'INCAPACIDAD', 1),
  (45, 5, 'HISTORIA_CLINICA', 1),
  (45, 5, 'CEDULA', 1),
  (45, 5, 'CERTIFICADO_NACIDO_VIVO', 1),
  (45, 5, 'REGISTRO_CIVIL_NACIMIENTO', 1),
--   tipo 9 LICENCIA PATERNIDAD | tipo_envio=1 medioradicacion=2 | 5 docs en 1 archivo(s): INCAPACIDAD#1, HISTORIA_CLINICA#1, CEDULA#1, CERTIFICADO_NACIDO_VIVO#1, REGISTRO_CIVIL_NACIMIENTO#1
  (45, 9, 'INCAPACIDAD', 1),
  (45, 9, 'HISTORIA_CLINICA', 1),
  (45, 9, 'CEDULA', 1),
  (45, 9, 'CERTIFICADO_NACIDO_VIVO', 1),
  (45, 9, 'REGISTRO_CIVIL_NACIMIENTO', 1),
--   tipo 11 TRANSITO NO LABORAL | tipo_envio=1 medioradicacion=2 | 5 docs en 1 archivo(s): INCAPACIDAD#1, HISTORIA_CLINICA#1, CEDULA#1, SOAT#1, FURIPS#1
  (45, 11, 'INCAPACIDAD', 1),
  (45, 11, 'HISTORIA_CLINICA', 1),
  (45, 11, 'CEDULA', 1),
  (45, 11, 'SOAT', 1),
  (45, 11, 'FURIPS', 1),

-- ------------------------------------------------------------------
-- idlpeps=46  SAVIA SALUDEPS  (NIT 900604350)
--   tipos SIN documentos configurados (la EPS no exige nada / sin definir): 2 ACCIDENTE DE TRABAJO; 8 ENFERMEDAD LABORAL; 10 PRELICENCIA
--   tipo 3 ENFERMEDAD GENERAL | tipo_envio=2 medioradicacion=2 | 2 docs en 2 archivo(s): INCAPACIDAD#1, HISTORIA_CLINICA#2
  (46, 3, 'INCAPACIDAD', 1),
  (46, 3, 'HISTORIA_CLINICA', 1),
--   tipo 5 LICENCIA MATERNIDAD | tipo_envio=2 medioradicacion=2 | 5 docs en 4 archivo(s): INCAPACIDAD#1, HISTORIA_CLINICA#2, CEDULA#1, CERTIFICADO_NACIDO_VIVO#4, REGISTRO_CIVIL_NACIMIENTO#3
  (46, 5, 'INCAPACIDAD', 1),
  (46, 5, 'HISTORIA_CLINICA', 1),
  (46, 5, 'CEDULA', 1),
  (46, 5, 'CERTIFICADO_NACIDO_VIVO', 1),
  (46, 5, 'REGISTRO_CIVIL_NACIMIENTO', 1),
--   tipo 9 LICENCIA PATERNIDAD | tipo_envio=2 medioradicacion=2 | 4 docs en 3 archivo(s): HISTORIA_CLINICA#3, CEDULA#3, CERTIFICADO_NACIDO_VIVO#2, REGISTRO_CIVIL_NACIMIENTO#1
  (46, 9, 'HISTORIA_CLINICA', 1),
  (46, 9, 'CEDULA', 1),
  (46, 9, 'CERTIFICADO_NACIDO_VIVO', 1),
  (46, 9, 'REGISTRO_CIVIL_NACIMIENTO', 1),
--   tipo 11 TRANSITO NO LABORAL | tipo_envio=2 medioradicacion=2 | 6 docs en 6 archivo(s): INCAPACIDAD#2, HISTORIA_CLINICA#1, SOAT#6, RAT#4, DESCARTE_EVENTO_LABORAL#3, FURIPS#5
  (46, 11, 'INCAPACIDAD', 1),
  (46, 11, 'HISTORIA_CLINICA', 1),
  (46, 11, 'SOAT', 1),
  (46, 11, 'RAT', 1),
  (46, 11, 'DESCARTE_EVENTO_LABORAL', 1),
  (46, 11, 'FURIPS', 1),

-- ------------------------------------------------------------------
-- idlpeps=47  SERVICIO OCCIDENTAL DE SALUD S.A. S.O.S.  (NIT 805001157)
--   tipos SIN documentos configurados (la EPS no exige nada / sin definir): 2 ACCIDENTE DE TRABAJO; 3 ENFERMEDAD GENERAL; 10 PRELICENCIA
--   tipo 5 LICENCIA MATERNIDAD | tipo_envio=2 medioradicacion=2 | 5 docs en 4 archivo(s): INCAPACIDAD#3, HISTORIA_CLINICA#2, CEDULA#4, CERTIFICADO_NACIDO_VIVO#2, REGISTRO_CIVIL_NACIMIENTO#1
  (47, 5, 'INCAPACIDAD', 1),
  (47, 5, 'HISTORIA_CLINICA', 1),
  (47, 5, 'CEDULA', 1),
  (47, 5, 'CERTIFICADO_NACIDO_VIVO', 1),
  (47, 5, 'REGISTRO_CIVIL_NACIMIENTO', 1),
--   tipo 8 ENFERMEDAD LABORAL | tipo_envio=2 medioradicacion=2 | 2 docs en 2 archivo(s): INCAPACIDAD#1, HISTORIA_CLINICA#2
  (47, 8, 'INCAPACIDAD', 1),
  (47, 8, 'HISTORIA_CLINICA', 1),
--   tipo 9 LICENCIA PATERNIDAD | tipo_envio=2 medioradicacion=2 | 4 docs en 2 archivo(s): HISTORIA_CLINICA#2, CEDULA#2, CERTIFICADO_NACIDO_VIVO#1, REGISTRO_CIVIL_NACIMIENTO#1
  (47, 9, 'HISTORIA_CLINICA', 1),
  (47, 9, 'CEDULA', 1),
  (47, 9, 'CERTIFICADO_NACIDO_VIVO', 1),
  (47, 9, 'REGISTRO_CIVIL_NACIMIENTO', 1),
--   tipo 11 TRANSITO NO LABORAL | tipo_envio=2 medioradicacion=2 | 5 docs en 4 archivo(s): INCAPACIDAD#2, HISTORIA_CLINICA#1, CEDULA#1, SOAT#4, FURIPS#3
  (47, 11, 'INCAPACIDAD', 1),
  (47, 11, 'HISTORIA_CLINICA', 1),
  (47, 11, 'CEDULA', 1),
  (47, 11, 'SOAT', 1),
  (47, 11, 'FURIPS', 1),

-- ------------------------------------------------------------------
-- idlpeps=49  SURA  (NIT 800088702)
--   tipos SIN documentos configurados (la EPS no exige nada / sin definir): 3 ENFERMEDAD GENERAL; 10 PRELICENCIA
--   tipo 2 ACCIDENTE DE TRABAJO | tipo_envio=1 medioradicacion=2 | 1 docs en 1 archivo(s): INCAPACIDAD#1
  (49, 2, 'INCAPACIDAD', 1),
--   tipo 5 LICENCIA MATERNIDAD | tipo_envio=2 medioradicacion=2 | 5 docs en 0 archivo(s): INCAPACIDAD#0, HISTORIA_CLINICA#0, CEDULA#0, CERTIFICADO_NACIDO_VIVO#0, REGISTRO_CIVIL_NACIMIENTO#0
  (49, 5, 'INCAPACIDAD', 1),
  (49, 5, 'HISTORIA_CLINICA', 1),
  (49, 5, 'CEDULA', 1),
  (49, 5, 'CERTIFICADO_NACIDO_VIVO', 1),
  (49, 5, 'REGISTRO_CIVIL_NACIMIENTO', 1),
--   tipo 8 ENFERMEDAD LABORAL | tipo_envio=2 medioradicacion=2 | 2 docs en 0 archivo(s): INCAPACIDAD#0, HISTORIA_CLINICA#0
  (49, 8, 'INCAPACIDAD', 1),
  (49, 8, 'HISTORIA_CLINICA', 1),
--   tipo 9 LICENCIA PATERNIDAD | tipo_envio=2 medioradicacion=2 | 5 docs en 0 archivo(s): INCAPACIDAD#0, HISTORIA_CLINICA#0, CEDULA#0, CERTIFICADO_NACIDO_VIVO#0, REGISTRO_CIVIL_NACIMIENTO#0
  (49, 9, 'INCAPACIDAD', 1),
  (49, 9, 'HISTORIA_CLINICA', 1),
  (49, 9, 'CEDULA', 1),
  (49, 9, 'CERTIFICADO_NACIDO_VIVO', 1),
  (49, 9, 'REGISTRO_CIVIL_NACIMIENTO', 1),
--   tipo 11 TRANSITO NO LABORAL | tipo_envio=2 medioradicacion=2 | 5 docs en 0 archivo(s): INCAPACIDAD#0, HISTORIA_CLINICA#0, CEDULA#0, SOAT#0, FURIPS#0
  (49, 11, 'INCAPACIDAD', 1),
  (49, 11, 'HISTORIA_CLINICA', 1),
  (49, 11, 'CEDULA', 1),
  (49, 11, 'SOAT', 1),
  (49, 11, 'FURIPS', 1),

-- ------------------------------------------------------------------
-- idlpeps=53  COMFAORIENTE  (NIT 890500675)
--   tipos SIN documentos configurados (la EPS no exige nada / sin definir): 2 ACCIDENTE DE TRABAJO; 8 ENFERMEDAD LABORAL; 10 PRELICENCIA
--   tipo 3 ENFERMEDAD GENERAL | tipo_envio=2 medioradicacion=2 | 4 docs en 0 archivo(s): INCAPACIDAD#0, HISTORIA_CLINICA#0, CEDULA#0, CERTIFICADO_LABORAL#0
  (53, 3, 'INCAPACIDAD', 1),
  (53, 3, 'HISTORIA_CLINICA', 1),
  (53, 3, 'CEDULA', 1),
  (53, 3, 'CERTIFICADO_LABORAL', 1),
--   tipo 5 LICENCIA MATERNIDAD | tipo_envio=2 medioradicacion=2 | 5 docs en 5 archivo(s): INCAPACIDAD#3, HISTORIA_CLINICA#4, CEDULA#5, CERTIFICADO_NACIDO_VIVO#2, REGISTRO_CIVIL_NACIMIENTO#1
  (53, 5, 'INCAPACIDAD', 1),
  (53, 5, 'HISTORIA_CLINICA', 1),
  (53, 5, 'CEDULA', 1),
  (53, 5, 'CERTIFICADO_NACIDO_VIVO', 1),
  (53, 5, 'REGISTRO_CIVIL_NACIMIENTO', 1),
--   tipo 9 LICENCIA PATERNIDAD | tipo_envio=2 medioradicacion=2 | 4 docs en 2 archivo(s): HISTORIA_CLINICA#2, CEDULA#2, CERTIFICADO_NACIDO_VIVO#1, REGISTRO_CIVIL_NACIMIENTO#1
  (53, 9, 'HISTORIA_CLINICA', 1),
  (53, 9, 'CEDULA', 1),
  (53, 9, 'CERTIFICADO_NACIDO_VIVO', 1),
  (53, 9, 'REGISTRO_CIVIL_NACIMIENTO', 1),
--   tipo 11 TRANSITO NO LABORAL | tipo_envio=2 medioradicacion=2 | 5 docs en 4 archivo(s): INCAPACIDAD#2, HISTORIA_CLINICA#1, CEDULA#1, SOAT#4, FURIPS#3
  (53, 11, 'INCAPACIDAD', 1),
  (53, 11, 'HISTORIA_CLINICA', 1),
  (53, 11, 'CEDULA', 1),
  (53, 11, 'SOAT', 1),
  (53, 11, 'FURIPS', 1),

-- ------------------------------------------------------------------
-- idlpeps=54  SALUDMIA  (NIT 900914254)
--   tipos SIN documentos configurados (la EPS no exige nada / sin definir): 2 ACCIDENTE DE TRABAJO; 10 PRELICENCIA; 11 TRANSITO NO LABORAL
--   tipo 3 ENFERMEDAD GENERAL | tipo_envio=2 medioradicacion=1 | 2 docs en 2 archivo(s): INCAPACIDAD#2, HISTORIA_CLINICA#1
  (54, 3, 'INCAPACIDAD', 1),
  (54, 3, 'HISTORIA_CLINICA', 1),
--   tipo 5 LICENCIA MATERNIDAD | tipo_envio=2 medioradicacion=1 | 5 docs en 4 archivo(s): INCAPACIDAD#1, HISTORIA_CLINICA#3, CEDULA#4, CERTIFICADO_NACIDO_VIVO#2, REGISTRO_CIVIL_NACIMIENTO#2
  (54, 5, 'INCAPACIDAD', 1),
  (54, 5, 'HISTORIA_CLINICA', 1),
  (54, 5, 'CEDULA', 1),
  (54, 5, 'CERTIFICADO_NACIDO_VIVO', 1),
  (54, 5, 'REGISTRO_CIVIL_NACIMIENTO', 1),
--   tipo 8 ENFERMEDAD LABORAL | tipo_envio=2 medioradicacion=1 | 5 docs en 5 archivo(s): INCAPACIDAD#1, HISTORIA_CLINICA#2, CEDULA#5, SOAT#4, FURIPS#3
  (54, 8, 'INCAPACIDAD', 1),
  (54, 8, 'HISTORIA_CLINICA', 1),
  (54, 8, 'CEDULA', 1),
  (54, 8, 'SOAT', 1),
  (54, 8, 'FURIPS', 1),
--   tipo 9 LICENCIA PATERNIDAD | tipo_envio=2 medioradicacion=1 | 4 docs en 3 archivo(s): HISTORIA_CLINICA#1, CEDULA#3, CERTIFICADO_NACIDO_VIVO#2, REGISTRO_CIVIL_NACIMIENTO#2
  (54, 9, 'HISTORIA_CLINICA', 1),
  (54, 9, 'CEDULA', 1),
  (54, 9, 'CERTIFICADO_NACIDO_VIVO', 1),
  (54, 9, 'REGISTRO_CIVIL_NACIMIENTO', 1),

-- ------------------------------------------------------------------
-- idlpeps=62  PIJAOS SALUD EPSI  (NIT 809008362)
--   tipos SIN documentos configurados (la EPS no exige nada / sin definir): 2 ACCIDENTE DE TRABAJO; 8 ENFERMEDAD LABORAL; 10 PRELICENCIA
--   tipo 3 ENFERMEDAD GENERAL | tipo_envio=2 medioradicacion=1 | 2 docs en 2 archivo(s): INCAPACIDAD#1, HISTORIA_CLINICA#2
  (62, 3, 'INCAPACIDAD', 1),
  (62, 3, 'HISTORIA_CLINICA', 1),
--   tipo 5 LICENCIA MATERNIDAD | tipo_envio=2 medioradicacion=1 | 5 docs en 4 archivo(s): INCAPACIDAD#1, HISTORIA_CLINICA#2, CEDULA#1, CERTIFICADO_NACIDO_VIVO#4, REGISTRO_CIVIL_NACIMIENTO#3
  (62, 5, 'INCAPACIDAD', 1),
  (62, 5, 'HISTORIA_CLINICA', 1),
  (62, 5, 'CEDULA', 1),
  (62, 5, 'CERTIFICADO_NACIDO_VIVO', 1),
  (62, 5, 'REGISTRO_CIVIL_NACIMIENTO', 1),
--   tipo 9 LICENCIA PATERNIDAD | tipo_envio=2 medioradicacion=1 | 4 docs en 3 archivo(s): HISTORIA_CLINICA#3, CEDULA#3, CERTIFICADO_NACIDO_VIVO#2, REGISTRO_CIVIL_NACIMIENTO#1
  (62, 9, 'HISTORIA_CLINICA', 1),
  (62, 9, 'CEDULA', 1),
  (62, 9, 'CERTIFICADO_NACIDO_VIVO', 1),
  (62, 9, 'REGISTRO_CIVIL_NACIMIENTO', 1),
--   tipo 11 TRANSITO NO LABORAL | tipo_envio=2 medioradicacion=1 | 6 docs en 6 archivo(s): INCAPACIDAD#2, HISTORIA_CLINICA#1, SOAT#6, RAT#4, DESCARTE_EVENTO_LABORAL#3, FURIPS#5
  (62, 11, 'INCAPACIDAD', 1),
  (62, 11, 'HISTORIA_CLINICA', 1),
  (62, 11, 'SOAT', 1),
  (62, 11, 'RAT', 1),
  (62, 11, 'DESCARTE_EVENTO_LABORAL', 1),
  (62, 11, 'FURIPS', 1),

-- ------------------------------------------------------------------
-- idlpeps=64  MUTUAL SER ESS  (NIT 806008394)
--   tipos SIN documentos configurados (la EPS no exige nada / sin definir): 2 ACCIDENTE DE TRABAJO; 8 ENFERMEDAD LABORAL; 10 PRELICENCIA
--   tipo 3 ENFERMEDAD GENERAL | tipo_envio=2 medioradicacion=2 | 3 docs en 3 archivo(s): INCAPACIDAD#2, HISTORIA_CLINICA#1, CEDULA#3
  (64, 3, 'INCAPACIDAD', 1),
  (64, 3, 'HISTORIA_CLINICA', 1),
  (64, 3, 'CEDULA', 1),
--   tipo 5 LICENCIA MATERNIDAD | tipo_envio=1 medioradicacion=2 | 5 docs en 1 archivo(s): INCAPACIDAD#1, HISTORIA_CLINICA#1, CEDULA#1, CERTIFICADO_NACIDO_VIVO#1, REGISTRO_CIVIL_NACIMIENTO#1
  (64, 5, 'INCAPACIDAD', 1),
  (64, 5, 'HISTORIA_CLINICA', 1),
  (64, 5, 'CEDULA', 1),
  (64, 5, 'CERTIFICADO_NACIDO_VIVO', 1),
  (64, 5, 'REGISTRO_CIVIL_NACIMIENTO', 1),
--   tipo 9 LICENCIA PATERNIDAD | tipo_envio=1 medioradicacion=2 | 5 docs en 1 archivo(s): INCAPACIDAD#1, HISTORIA_CLINICA#1, CEDULA#1, CERTIFICADO_NACIDO_VIVO#1, REGISTRO_CIVIL_NACIMIENTO#1
  (64, 9, 'INCAPACIDAD', 1),
  (64, 9, 'HISTORIA_CLINICA', 1),
  (64, 9, 'CEDULA', 1),
  (64, 9, 'CERTIFICADO_NACIDO_VIVO', 1),
  (64, 9, 'REGISTRO_CIVIL_NACIMIENTO', 1),
--   tipo 11 TRANSITO NO LABORAL | tipo_envio=1 medioradicacion=2 | 5 docs en 1 archivo(s): INCAPACIDAD#1, HISTORIA_CLINICA#1, CEDULA#1, SOAT#1, FURIPS#1
  (64, 11, 'INCAPACIDAD', 1),
  (64, 11, 'HISTORIA_CLINICA', 1),
  (64, 11, 'CEDULA', 1),
  (64, 11, 'SOAT', 1),
  (64, 11, 'FURIPS', 1);

-- ===========================================================================
--  OPCIONAL 1 - sembrar `lpentidades` con los ids REALES (solo si se quiere probar
--  en la BD demo de docker compose). CHOCA con los ids demo 1..8 de sql/init.sql:
--  ejecutar antes `DELETE FROM lprequisitos_eps; DELETE FROM lpentidades;`.
--  `nombre` es la palabra clave con la que erp.Lookups matchea por contencion, asi que
--  conviene revisarla a mano (p.ej. 'FAMISANAR LTDA. CAFAM COLSUBSIDIO' no matchea un
--  documento que diga solo 'FAMISANAR').
-- ---------------------------------------------------------------------------
-- INSERT INTO lpentidades (idlpentidad, nombre, nit, tipoentidad) VALUES (5, 'ALIANZA SALUD', '830113831', 1);
-- INSERT INTO lpentidades (idlpentidad, nombre, nit, tipoentidad) VALUES (7, 'ASMET SALUD', '900935126', 1);
-- INSERT INTO lpentidades (idlpentidad, nombre, nit, tipoentidad) VALUES (11, 'CAPITAL SALUD', '900298372', 1);
-- INSERT INTO lpentidades (idlpentidad, nombre, nit, tipoentidad) VALUES (19, 'COMFENALCO VALLE', '890303093', 1);
-- INSERT INTO lpentidades (idlpentidad, nombre, nit, tipoentidad) VALUES (20, 'COMPENSAR', '860066942', 1);
-- INSERT INTO lpentidades (idlpentidad, nombre, nit, tipoentidad) VALUES (23, 'COOSALUD E.S.S.', '900226715', 1);
-- INSERT INTO lpentidades (idlpentidad, nombre, nit, tipoentidad) VALUES (26, 'EMSSANAR', '901021565', 1);
-- INSERT INTO lpentidades (idlpentidad, nombre, nit, tipoentidad) VALUES (27, 'FAMISANAR LTDA. CAFAM COLSUBSIDIO', '830003564', 1);
-- INSERT INTO lpentidades (idlpentidad, nombre, nit, tipoentidad) VALUES (32, 'MALLAMAS', '837000084', 1);
-- INSERT INTO lpentidades (idlpentidad, nombre, nit, tipoentidad) VALUES (36, 'NUEVA EPS S.A', '900156264', 1);
-- INSERT INTO lpentidades (idlpentidad, nombre, nit, tipoentidad) VALUES (40, 'SALUD TOTAL S.A. EPS ARS', '800130907', 1);
-- INSERT INTO lpentidades (idlpentidad, nombre, nit, tipoentidad) VALUES (45, 'SANITAS S.A.', '800251440', 1);
-- INSERT INTO lpentidades (idlpentidad, nombre, nit, tipoentidad) VALUES (46, 'SAVIA SALUDEPS', '900604350', 1);
-- INSERT INTO lpentidades (idlpentidad, nombre, nit, tipoentidad) VALUES (47, 'SERVICIO OCCIDENTAL DE SALUD S.A. S.O.S.', '805001157', 1);
-- INSERT INTO lpentidades (idlpentidad, nombre, nit, tipoentidad) VALUES (49, 'SURA', '800088702', 1);
-- INSERT INTO lpentidades (idlpentidad, nombre, nit, tipoentidad) VALUES (53, 'COMFAORIENTE', '890500675', 1);
-- INSERT INTO lpentidades (idlpentidad, nombre, nit, tipoentidad) VALUES (54, 'SALUDMIA', '900914254', 1);
-- INSERT INTO lpentidades (idlpentidad, nombre, nit, tipoentidad) VALUES (62, 'PIJAOS SALUD EPSI', '809008362', 1);
-- INSERT INTO lpentidades (idlpentidad, nombre, nit, tipoentidad) VALUES (64, 'MUTUAL SER ESS', '806008394', 1);

-- ===========================================================================
--  OPCIONAL 2 - persistir los metadatos de radicacion que el DDL actual no tiene
--  (propuesta; NO se ejecuta aqui porque cambia el esquema del repo).
-- ---------------------------------------------------------------------------
-- ALTER TABLE lprequisitos_eps
--   ADD COLUMN archivo         TINYINT     NOT NULL DEFAULT 0  COMMENT 'en cual de los N archivos va (0=sin asignar)',
--   ADD COLUMN iddocumento     INT         NULL                COMMENT 'id del catalogo de documentos del ERP (1..8,11,12)',
--   ADD COLUMN nombredocumento VARCHAR(60) NULL                COMMENT 'texto original del checklist de la EPS';
-- CREATE TABLE lpradicacion_eps (   -- 1 fila por (EPS, tipo de ausentismo)
--   idlpentidad        INT     NOT NULL,
--   idlptipoausentismo INT     NOT NULL,
--   tipo_envio         TINYINT NOT NULL,   -- 0=sin definir 1=un archivo 2=archivos separados
--   medioradicacion    TINYINT NOT NULL,   -- 0=sin definir 1/2=canal (etiqueta a confirmar con el cliente)
--   PRIMARY KEY (idlpentidad, idlptipoausentismo));
