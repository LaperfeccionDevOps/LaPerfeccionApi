-- Condiciones o situaciones que impiden realizar el trabajo en alturas de
-- manera segura, por cada trabajador del permiso.
-- Pregunta principal: ¿presenta actualmente alguna condición o situación que
-- le impida realizar trabajo en alturas de manera segura? Si es SI:
--   * ¿Ha ingerido bebidas alcohólicas en las últimas 12 horas?
--   * ¿Le tiene miedo a las alturas o actualmente sufre de vértigo o mareo?
--   * ¿Ha consumido recientemente sustancias psicoactivas, alcohol u otras
--     sustancias que puedan afectar su estado de alerta...? (usa la columna
--     existente "ConsumeSustancias", que deja de ser una pregunta suelta)
--   * Si responde NO a las tres, debe describir la condición o situación.
-- Si es NO, las tres quedan en NO.
--
-- Las columnas nuevas admiten NULL solo por los registros anteriores a este
-- cambio (conservan su respuesta de "ConsumeSustancias"); el backend las
-- exige para los registros nuevos.

BEGIN;

ALTER TABLE public."PermisoTrabajoAlturasTrabajador"
    ADD COLUMN IF NOT EXISTS "PresentaImpedimentoAlturas" boolean,
    ADD COLUMN IF NOT EXISTS "IngirioAlcohol12Horas"      boolean,
    ADD COLUMN IF NOT EXISTS "MiedoAlturasVertigo"        boolean,
    ADD COLUMN IF NOT EXISTS "OtroImpedimentoAlturas"     varchar(300);

-- Si la respuesta principal es NO, ninguna subpregunta puede ser SI.
-- (En los registros anteriores la principal es NULL y no se ven afectados.)
ALTER TABLE public."PermisoTrabajoAlturasTrabajador"
    ADD CONSTRAINT "CK_PermisoAlturasTrabajador_Impedimentos"
    CHECK (
        "PresentaImpedimentoAlturas"
        OR NOT (
            COALESCE("IngirioAlcohol12Horas", FALSE)
            OR COALESCE("MiedoAlturasVertigo", FALSE)
            OR "ConsumeSustancias"
        )
    );

-- Si la respuesta principal es SI y las tres subpreguntas son NO, debe
-- describir la condición o situación.
ALTER TABLE public."PermisoTrabajoAlturasTrabajador"
    ADD CONSTRAINT "CK_PermisoAlturasTrabajador_OtroImpedimento"
    CHECK (
        NOT (
            "PresentaImpedimentoAlturas" IS TRUE
            AND "IngirioAlcohol12Horas" IS FALSE
            AND "MiedoAlturasVertigo" IS FALSE
            AND "ConsumeSustancias" IS FALSE
        )
        OR NULLIF(TRIM("OtroImpedimentoAlturas"), '') IS NOT NULL
    );

COMMIT;

-- Reversa (solo si se necesita deshacer):
-- ALTER TABLE public."PermisoTrabajoAlturasTrabajador" DROP CONSTRAINT IF EXISTS "CK_PermisoAlturasTrabajador_OtroImpedimento";
-- ALTER TABLE public."PermisoTrabajoAlturasTrabajador" DROP CONSTRAINT IF EXISTS "CK_PermisoAlturasTrabajador_Impedimentos";
-- ALTER TABLE public."PermisoTrabajoAlturasTrabajador"
--     DROP COLUMN IF EXISTS "PresentaImpedimentoAlturas",
--     DROP COLUMN IF EXISTS "IngirioAlcohol12Horas",
--     DROP COLUMN IF EXISTS "MiedoAlturasVertigo",
--     DROP COLUMN IF EXISTS "OtroImpedimentoAlturas";
