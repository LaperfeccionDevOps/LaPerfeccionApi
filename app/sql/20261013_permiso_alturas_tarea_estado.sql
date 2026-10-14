-- Permiso de trabajo en alturas: estado del permiso y datos de la tarea.
--
-- Estado:
--   EN_DILIGENCIAMIENTO -> se está llenando por pasos; se puede editar.
--   AUTORIZADO          -> firmado por quien autoriza; ya no se edita.
--   CERRADO             -> la tarea terminó.
--
-- Paso 3 del formulario (secciones 2 y 3 del formato):
--   datos básicos de la tarea y medidas de prevención. Admiten NULL porque se
--   diligencian después de crear el permiso; el backend los exige al guardar
--   ese paso.

BEGIN;

ALTER TABLE public."PermisoTrabajoAlturas"
    ADD COLUMN IF NOT EXISTS "Estado" varchar(30) NOT NULL
        DEFAULT 'EN_DILIGENCIAMIENTO',
    -- 2. Datos básicos del permiso de trabajo en alturas
    ADD COLUMN IF NOT EXISTS "TipoTrabajoAlturas"       varchar(150),
    ADD COLUMN IF NOT EXISTS "DescripcionProcedimiento" text,
    ADD COLUMN IF NOT EXISTS "HerramientasUtensilios"   text,
    ADD COLUMN IF NOT EXISTS "AlturaAproximadaMetros"   numeric(6, 2),
    -- 3. Medidas de prevención
    ADD COLUMN IF NOT EXISTS "ReEntrenamiento"          boolean,
    ADD COLUMN IF NOT EXISTS "SistemasAcceso"           varchar(300),
    ADD COLUMN IF NOT EXISTS "SistemasIngenieria"       varchar(300),
    ADD COLUMN IF NOT EXISTS "MedidasColectivas"        varchar(300),
    ADD COLUMN IF NOT EXISTS "TrabajoSuspension"        boolean;

ALTER TABLE public."PermisoTrabajoAlturas"
    ADD CONSTRAINT "CK_PermisoTrabajoAlturas_Estado"
    CHECK ("Estado" IN ('EN_DILIGENCIAMIENTO', 'AUTORIZADO', 'CERRADO'));

ALTER TABLE public."PermisoTrabajoAlturas"
    ADD CONSTRAINT "CK_PermisoTrabajoAlturas_Altura"
    CHECK ("AlturaAproximadaMetros" IS NULL OR "AlturaAproximadaMetros" > 0);

CREATE INDEX IF NOT EXISTS "IX_PermisoTrabajoAlturas_Estado"
    ON public."PermisoTrabajoAlturas" ("Estado");

COMMIT;

-- Reversa (solo si se necesita deshacer):
-- DROP INDEX IF EXISTS public."IX_PermisoTrabajoAlturas_Estado";
-- ALTER TABLE public."PermisoTrabajoAlturas" DROP CONSTRAINT IF EXISTS "CK_PermisoTrabajoAlturas_Altura";
-- ALTER TABLE public."PermisoTrabajoAlturas" DROP CONSTRAINT IF EXISTS "CK_PermisoTrabajoAlturas_Estado";
-- ALTER TABLE public."PermisoTrabajoAlturas"
--     DROP COLUMN IF EXISTS "Estado",
--     DROP COLUMN IF EXISTS "TipoTrabajoAlturas",
--     DROP COLUMN IF EXISTS "DescripcionProcedimiento",
--     DROP COLUMN IF EXISTS "HerramientasUtensilios",
--     DROP COLUMN IF EXISTS "AlturaAproximadaMetros",
--     DROP COLUMN IF EXISTS "ReEntrenamiento",
--     DROP COLUMN IF EXISTS "SistemasAcceso",
--     DROP COLUMN IF EXISTS "SistemasIngenieria",
--     DROP COLUMN IF EXISTS "MedidasColectivas",
--     DROP COLUMN IF EXISTS "TrabajoSuspension";
