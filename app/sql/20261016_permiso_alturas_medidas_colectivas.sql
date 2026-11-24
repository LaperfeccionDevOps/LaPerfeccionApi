-- Medidas colectivas de prevención (paso 3 del permiso de trabajo en alturas).
-- Se pregunta si aplican o no:
--   * Aplica (TRUE)     -> se describe la medida en "MedidasColectivas" (obligatorio).
--   * No aplica (FALSE) -> "MedidasColectivas" queda vacío y el PDF muestra "No aplica".
-- La columna admite NULL solo por los permisos creados antes de este cambio;
-- el backend la exige para los permisos nuevos.

BEGIN;

ALTER TABLE public."PermisoTrabajoAlturas"
    ADD COLUMN IF NOT EXISTS "AplicaMedidasColectivas" boolean;

-- Si aplica, la medida es obligatoria; si no aplica, no se guarda texto.
ALTER TABLE public."PermisoTrabajoAlturas"
    ADD CONSTRAINT "CK_PermisoTrabajoAlturas_MedidasColectivas"
    CHECK (
        "AplicaMedidasColectivas" IS NULL
        OR ("AplicaMedidasColectivas" AND NULLIF(TRIM("MedidasColectivas"), '') IS NOT NULL)
        OR (NOT "AplicaMedidasColectivas" AND "MedidasColectivas" IS NULL)
    );

COMMIT;

-- Reversa (solo si se necesita deshacer):
-- ALTER TABLE public."PermisoTrabajoAlturas" DROP CONSTRAINT IF EXISTS "CK_PermisoTrabajoAlturas_MedidasColectivas";
-- ALTER TABLE public."PermisoTrabajoAlturas" DROP COLUMN IF EXISTS "AplicaMedidasColectivas";
