-- ===========================================================================
--  incapacidad-ocr → ERP (BD ASTGU)  —  esquema mínimo para el flujo a STAGING
--
--  Replica (en versión mínima) lo confirmado con Diana (11 jun 2026):
--    • El middleware NO inserta en lpausentismos directo (se saltaría la lógica del ERP).
--    • Escribe en una tabla STAGING (lp_ausentismos_ia, estado PENDIENTE_REVISION) con los
--      MISMOS nombres de columna del ERP en los campos obligatorios → promover = 1:1.
--    • Catálogos para los LOOKUPS que faltaban en la prueba de la Sesión 1:
--        cédula → idlpempleado · CIE-10 → idlpdiagnosticos · EPS → idlpentidad
--    • Códigos de tipo de ausentismo entregados por Diana: 2/3/5/8/9/10/11.
--
--  Los datos de prueba COINCIDEN con los documentos de ../Ejemplos para demostrar el flujo.
-- ===========================================================================

CREATE DATABASE IF NOT EXISTS ASTGU CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
USE ASTGU;

-- ----------------------------------------------------------------- catálogos
CREATE TABLE IF NOT EXISTS lpempleados (
  idlpempleado INT AUTO_INCREMENT PRIMARY KEY,
  cedula       VARCHAR(20)  NOT NULL UNIQUE,
  nombre       VARCHAR(120) NOT NULL,
  activo       TINYINT(1)   NOT NULL DEFAULT 1
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS lpdiagnosticos (
  idlpdiagnosticos INT AUTO_INCREMENT PRIMARY KEY,
  codigo_cie10     VARCHAR(10)  NOT NULL UNIQUE,   -- guardado con punto (J06.9); el lookup compara sin punto
  descripcion      VARCHAR(200) NOT NULL
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS lpentidades (
  idlpentidad INT AUTO_INCREMENT PRIMARY KEY,
  nombre      VARCHAR(80)  NOT NULL,   -- palabra clave distintiva para el match (NUEVA EPS, SURA, ...)
  nit         VARCHAR(20)  NULL,
  tipoentidad INT          NOT NULL DEFAULT 1      -- 1=EPS, 2=ARL (a confirmar con catálogo real)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS lptipoausentismo (
  idlptipoausentismo INT PRIMARY KEY,
  nombre             VARCHAR(60) NOT NULL
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS lpestadosrecepausentismos (
  idlpestadosrecepausentismos INT PRIMARY KEY,
  nombre                      VARCHAR(30) NOT NULL
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS lprequisitos_eps (
  id                 INT AUTO_INCREMENT PRIMARY KEY,
  idlpentidad        INT NOT NULL,
  idlptipoausentismo INT NOT NULL,
  documento          VARCHAR(60) NOT NULL,
  obligatorio        TINYINT(1)  NOT NULL DEFAULT 1
) ENGINE=InnoDB;

-- ----------------------------------------------------------------- staging
CREATE TABLE IF NOT EXISTS lp_ausentismos_ia (
  id                           INT AUTO_INCREMENT PRIMARY KEY,
  -- campos que se promueven a lpausentismos (mismos nombres del ERP)
  fecharegistro                DATE          NULL,
  fechaaccidente               DATE          NULL,
  fechainicio                  DATE          NULL,
  Numerodias                   INT           NULL,
  fechavencimiento             DATE          NULL,
  numeroorden                  VARCHAR(45)   NULL,
  observaciones                LONGTEXT      NULL,
  original                     INT           NOT NULL DEFAULT 0,
  idlpdiagnosticos             INT           NULL,
  idlpempleado                 INT           NULL,
  idlptipoausentismo           INT           NULL,
  idlpentidad                  INT           NULL,
  tipoentidad                  INT           NULL,
  idlpestadosrecepausentismos  INT           NULL,
  -- metadatos de la extracción (para el revisor)
  cedula_leida                 VARCHAR(20)   NULL,
  codigo_diagnostico_leido     VARCHAR(10)   NULL,
  eps_leida                    VARCHAR(80)   NULL,
  paciente_leido               VARCHAR(120)  NULL,
  confianza_ocr                DECIMAL(4,3)  NULL,
  ocr_backend                  VARCHAR(30)   NULL,
  extractor                    VARCHAR(30)   NULL,
  archivo_origen               VARCHAR(255)  NULL,
  problemas                    TEXT          NULL,
  documentacion_estado         VARCHAR(20)   NULL,
  documentos_faltantes         VARCHAR(255)  NULL,
  -- control del flujo
  estado                       VARCHAR(20)   NOT NULL DEFAULT 'PENDIENTE_REVISION',
  creado_en                    TIMESTAMP     NOT NULL DEFAULT CURRENT_TIMESTAMP,
  INDEX idx_ia_estado (estado),
  INDEX idx_ia_empleado (idlpempleado)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS lp_alertas_documentacion (
  id                   INT AUTO_INCREMENT PRIMARY KEY,
  id_ausentismo_ia     INT           NULL,
  idlpempleado         INT           NULL,
  cedula               VARCHAR(20)   NULL,
  idlpentidad          INT           NULL,
  eps                  VARCHAR(80)   NULL,
  documentos_faltantes VARCHAR(255)  NOT NULL,
  mensaje              VARCHAR(500)  NOT NULL,
  canal                VARCHAR(20)   NULL,
  estado               VARCHAR(20)   NOT NULL DEFAULT 'PENDIENTE',
  creado_en            TIMESTAMP     NOT NULL DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB;

-- ----------------------------------------------------------------- datos de prueba
INSERT INTO lptipoausentismo (idlptipoausentismo, nombre) VALUES
  (2,'ACCIDENTE DE TRABAJO'),(3,'ENFERMEDAD GENERAL'),(5,'LICENCIA MATERNIDAD'),
  (8,'ENFERMEDAD LABORAL'),(9,'LICENCIA PATERNIDAD'),(10,'PRELICENCIA'),(11,'TRANSITO NO LABORAL')
ON DUPLICATE KEY UPDATE nombre=VALUES(nombre);

INSERT INTO lpestadosrecepausentismos (idlpestadosrecepausentismos, nombre) VALUES
  (1,'ORIGINAL'),(2,'WHATSAPP'),(3,'CORREO')
ON DUPLICATE KEY UPDATE nombre=VALUES(nombre);

-- Entidades: 'nombre' es la palabra clave distintiva con la que se hace el match por contención.
INSERT INTO lpentidades (idlpentidad, nombre, nit, tipoentidad) VALUES
  (1,'NUEVA EPS','900156264',1),
  (2,'SURAMERICANA','800088702',1),
  (3,'SALUD TOTAL','800130907',1),
  (4,'FAMISANAR','830003564',1),
  (5,'SALUD MIA','901097473',1),
  (6,'SEGUROS DEL ESTADO','860009578',2),
  (7,'COLPATRIA','860002184',2),
  (8,'SANITAS','800251440',1)
ON DUPLICATE KEY UPDATE nombre=VALUES(nombre);

-- Empleados: cédulas que coinciden con ../Ejemplos (+ la muestra sintética de las pruebas).
INSERT INTO lpempleados (cedula, nombre, activo) VALUES
  ('1151480134','ALEJANDRO ISAAC LINARES RICARDO',1),
  ('1095817662','CESAR ARMANDO LANCHEROS CHAPARRO',1),
  ('91349897','JAIME SEDINSON AFANADOR',1),
  ('1005542119','MICHAEL ALEXIZ MORENO VELANDIA',1),
  ('63523940','ALIX HERNANDEZ SANDOVAL',1),
  ('13742111','LEONARDO GARNICA REYES',1),
  ('1098757631','YARITZA CONTRERAS RIVERA',1),
  ('1095912481','JAIDER SEBASTIAN HERNANDEZ ARDILA',1),
  ('1098765432','JUAN PEREZ GOMEZ',1)
ON DUPLICATE KEY UPDATE nombre=VALUES(nombre);

-- Catálogo CIE-10 (con punto, como lo entrega el extractor) para los ejemplos.
INSERT INTO lpdiagnosticos (codigo_cie10, descripcion) VALUES
  ('S42.0','FRACTURA DE LA CLAVICULA'),
  ('M54.4','LUMBAGO CON CIATICA'),
  ('M75.1','SINDROME DE MANGUITO ROTATORIO'),
  ('A09.9','DIARREA Y GASTROENTERITIS DE PRESUNTO ORIGEN INFECCIOSO'),
  ('J39.9','ENFERMEDAD DE LAS VIAS RESPIRATORIAS SUPERIORES, NO ESPECIFICADA'),
  ('K42.9','HERNIA UMBILICAL SIN OBSTRUCCION NI GANGRENA'),
  ('R07.4','DOLOR EN EL PECHO, NO ESPECIFICADO'),
  ('J06.9','INFECCION AGUDA DE LAS VIAS RESPIRATORIAS SUPERIORES')
ON DUPLICATE KEY UPDATE descripcion=VALUES(descripcion);

-- Requisitos documentales por EPS + tipo (mínimos de prueba; el corazón del validador documental).
INSERT INTO lprequisitos_eps (idlpentidad, idlptipoausentismo, documento, obligatorio) VALUES
  (1,3,'INCAPACIDAD',1),(1,3,'EPICRISIS',1),
  (3,3,'INCAPACIDAD',1),(3,3,'HISTORIA_CLINICA',1),
  (4,3,'INCAPACIDAD',1),
  (5,3,'INCAPACIDAD',1),(5,3,'HISTORIA_CLINICA',1),
  (6,2,'INCAPACIDAD',1),(6,2,'FURAT',1),
  (7,2,'INCAPACIDAD',1),(7,2,'FURAT',1);
