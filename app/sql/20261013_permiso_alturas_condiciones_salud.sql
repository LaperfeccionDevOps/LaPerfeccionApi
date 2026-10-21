-- Condiciones de salud de cada trabajador del permiso de trabajo en alturas.
-- Pregunta principal: ¿presenta actualmente alguna condición de salud que deba
-- ser informada para realizar el trabajo en alturas? Si es NO, las condiciones
-- específicas quedan en NO. Si es SI pero ninguna condición de la lista aplica,
-- se debe describir la condición en "OtraCondicionSalud".
--
-- Las columnas admiten NULL solo por los trabajadores registrados antes de
-- este cambio (no respondieron estas preguntas y no deben quedar como "NO");
-- el backend las exige para los registros nuevos.

BEGIN;

ALTER TABLE public."PermisoTrabajoAlturasTrabajador"
    ADD COLUMN IF NOT EXISTS "PresentaCondicionSalud"   boolean,
    ADD COLUMN IF NOT EXISTS "ProblemasCorazon"         boolean,
    ADD COLUMN IF NOT EXISTS "ProblemasRespiratorios"   boolean,
    ADD COLUMN IF NOT EXISTS "Diabetes"                 boolean,
    ADD COLUMN IF NOT EXISTS "Epilepsia"                boolean,
    ADD COLUMN IF NOT EXISTS "ProblemasSistemaNervioso" boolean,
    ADD COLUMN IF NOT EXISTS "ProblemasAudicion"        boolean,
    ADD COLUMN IF NOT EXISTS "ProblemasVisuales"        boolean,
    ADD COLUMN IF NOT EXISTS "OtraCondicionSalud"       varchar(300);

-- Si la respuesta principal es NO, ninguna condición específica puede ser SI.
ALTER TABLE public."PermisoTrabajoAlturasTrabajador"
    ADD CONSTRAINT "CK_PermisoAlturasTrabajador_CondicionesSalud"
    CHECK (
        "PresentaCondicionSalud"
        OR NOT (
            COALESCE("ProblemasCorazon", FALSE)
            OR COALESCE("ProblemasRespiratorios", FALSE)
            OR COALESCE("Diabetes", FALSE)
            OR COALESCE("Epilepsia", FALSE)
            OR COALESCE("ProblemasSistemaNervioso", FALSE)
            OR COALESCE("ProblemasAudicion", FALSE)
            OR COALESCE("ProblemasVisuales", FALSE)
        )
    );

-- Si la respuesta principal es SI y ninguna condición de la lista aplica,
-- la otra condición de salud es obligatoria.
ALTER TABLE public."PermisoTrabajoAlturasTrabajador"
    ADD CONSTRAINT "CK_PermisoAlturasTrabajador_OtraCondicionSalud"
    CHECK (
        NOT COALESCE("PresentaCondicionSalud", FALSE)
        OR COALESCE("ProblemasCorazon", FALSE)
        OR COALESCE("ProblemasRespiratorios", FALSE)
        OR COALESCE("Diabetes", FALSE)
        OR COALESCE("Epilepsia", FALSE)
        OR COALESCE("ProblemasSistemaNervioso", FALSE)
        OR COALESCE("ProblemasAudicion", FALSE)
        OR COALESCE("ProblemasVisuales", FALSE)
        OR NULLIF(TRIM("OtraCondicionSalud"), '') IS NOT NULL
    );

COMMIT;

-- Reversa (solo si se necesita deshacer):
-- ALTER TABLE public."PermisoTrabajoAlturasTrabajador" DROP CONSTRAINT IF EXISTS "CK_PermisoAlturasTrabajador_OtraCondicionSalud";
-- ALTER TABLE public."PermisoTrabajoAlturasTrabajador" DROP CONSTRAINT IF EXISTS "CK_PermisoAlturasTrabajador_CondicionesSalud";
-- ALTER TABLE public."PermisoTrabajoAlturasTrabajador"
--     DROP COLUMN IF EXISTS "PresentaCondicionSalud",
--     DROP COLUMN IF EXISTS "ProblemasCorazon",
--     DROP COLUMN IF EXISTS "ProblemasRespiratorios",
--     DROP COLUMN IF EXISTS "Diabetes",
--     DROP COLUMN IF EXISTS "Epilepsia",
--     DROP COLUMN IF EXISTS "ProblemasSistemaNervioso",
--     DROP COLUMN IF EXISTS "ProblemasAudicion",
--     DROP COLUMN IF EXISTS "ProblemasVisuales",
--     DROP COLUMN IF EXISTS "OtraCondicionSalud";
