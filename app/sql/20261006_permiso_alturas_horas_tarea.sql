-- Permisos de trabajo en alturas: hora de inicio y fin de la tarea.
-- La sede deja de ser obligatoria (se omite del formulario por ahora).
-- Las columnas nuevas admiten NULL solo por los registros creados antes de
-- este cambio; el backend las exige para los permisos nuevos.

BEGIN;

ALTER TABLE public."PermisoTrabajoAlturas"
    ALTER COLUMN "Sede" DROP NOT NULL;

ALTER TABLE public."PermisoTrabajoAlturas"
    ADD COLUMN IF NOT EXISTS "FechaHoraInicioTarea" timestamptz,
    ADD COLUMN IF NOT EXISTS "FechaHoraFinTarea"    timestamptz;

ALTER TABLE public."PermisoTrabajoAlturas"
    ADD CONSTRAINT "CK_PermisoTrabajoAlturas_FinMayorInicio"
    CHECK ("FechaHoraFinTarea" > "FechaHoraInicioTarea");

COMMIT;

-- Reversa (solo si se necesita deshacer):
-- ALTER TABLE public."PermisoTrabajoAlturas" DROP CONSTRAINT IF EXISTS "CK_PermisoTrabajoAlturas_FinMayorInicio";
-- ALTER TABLE public."PermisoTrabajoAlturas" DROP COLUMN IF EXISTS "FechaHoraFinTarea";
-- ALTER TABLE public."PermisoTrabajoAlturas" DROP COLUMN IF EXISTS "FechaHoraInicioTarea";
-- ALTER TABLE public."PermisoTrabajoAlturas" ALTER COLUMN "Sede" SET NOT NULL;
