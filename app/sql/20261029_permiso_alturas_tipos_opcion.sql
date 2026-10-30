-- Tipos (listas) del catálogo "OpcionPermisoAlturas" en su propia tabla, en
-- lugar de la regla fija "OpcionPermisoAlturas_Tipo_check". Así, crear una
-- lista nueva es un INSERT y HSEQ podrá administrar tipos y opciones desde
-- una pantalla, activándolos o inactivándolos sin borrar lo registrado.
--
-- Además agrega la lista de herramientas eléctricas (Tipo = 'HERRAMIENTA_ELECTRICA').
--
-- Ejecutar DESPUÉS de:
--   20261029_permiso_alturas_herramientas_manuales.sql
--   20261029_permiso_alturas_permisos_requeridos.sql

BEGIN;

CREATE TABLE IF NOT EXISTS public."TipoOpcionPermisoAlturas" (
    "Tipo"          varchar(30)  PRIMARY KEY,
    "Nombre"        varchar(100) NOT NULL,
    "Activo"        boolean      NOT NULL DEFAULT true,
    "FechaCreacion" timestamptz  NOT NULL DEFAULT now()
);

INSERT INTO public."TipoOpcionPermisoAlturas" ("Tipo", "Nombre") VALUES
    ('MECANISMO',             'Mecanismos de trabajo en alturas'),
    ('SISTEMA_INGENIERIA',    'Sistemas de ingeniería'),
    ('HERRAMIENTA_MANUAL',    'Herramientas manuales'),
    ('HERRAMIENTA_ELECTRICA', 'Herramientas eléctricas'),
    ('SISTEMA_ACCESO',        'Sistemas de acceso'),
    ('PERMISO_REQUERIDO',     'Permisos requeridos')
ON CONFLICT ("Tipo") DO NOTHING;

-- La regla fija se reemplaza por la llave foránea a la tabla de tipos.
-- ON UPDATE CASCADE: si un tipo cambia de código, sus opciones lo siguen.
ALTER TABLE public."OpcionPermisoAlturas"
    DROP CONSTRAINT IF EXISTS "OpcionPermisoAlturas_Tipo_check";

ALTER TABLE public."OpcionPermisoAlturas"
    DROP CONSTRAINT IF EXISTS "FK_OpcionPermisoAlturas_Tipo";

ALTER TABLE public."OpcionPermisoAlturas"
    ADD CONSTRAINT "FK_OpcionPermisoAlturas_Tipo"
    FOREIGN KEY ("Tipo") REFERENCES public."TipoOpcionPermisoAlturas"("Tipo")
    ON UPDATE CASCADE;

-- Herramientas eléctricas. Los códigos que terminan en '_NA' (No aplica) no
-- se pueden elegir junto con otras opciones de la misma lista.
INSERT INTO public."OpcionPermisoAlturas" ("Tipo", "Codigo", "Nombre", "Orden")
VALUES
    ('HERRAMIENTA_ELECTRICA', 'HEL_01', 'Hidrolavadora',        1),
    ('HERRAMIENTA_ELECTRICA', 'HEL_02', 'Taladro',              2),
    ('HERRAMIENTA_ELECTRICA', 'HEL_03', 'Pulidora',             3),
    ('HERRAMIENTA_ELECTRICA', 'HEL_04', 'Elevador unipersonal', 4),
    ('HERRAMIENTA_ELECTRICA', 'HEL_05', 'Demoledor',            5),
    ('HERRAMIENTA_ELECTRICA', 'HEL_NA', 'No aplica',            6)
ON CONFLICT ("Codigo") DO NOTHING;

COMMIT;

-- Reversa (solo si se necesita deshacer; antes, regresar el código):
-- BEGIN;
-- DELETE FROM public."AnalisisTrabajoSeguroOpcion" AO
--     USING public."OpcionPermisoAlturas" O
--     WHERE O."IdOpcionPermisoAlturas" = AO."IdOpcionPermisoAlturas"
--       AND O."Tipo" = 'HERRAMIENTA_ELECTRICA';
-- DELETE FROM public."OpcionPermisoAlturas" WHERE "Tipo" = 'HERRAMIENTA_ELECTRICA';
-- ALTER TABLE public."OpcionPermisoAlturas"
--     DROP CONSTRAINT "FK_OpcionPermisoAlturas_Tipo";
-- ALTER TABLE public."OpcionPermisoAlturas"
--     ADD CONSTRAINT "OpcionPermisoAlturas_Tipo_check"
--     CHECK ("Tipo" IN ('MECANISMO', 'SISTEMA_INGENIERIA', 'HERRAMIENTA_MANUAL',
--                       'SISTEMA_ACCESO', 'PERMISO_REQUERIDO'));
-- DROP TABLE public."TipoOpcionPermisoAlturas";
-- COMMIT;
