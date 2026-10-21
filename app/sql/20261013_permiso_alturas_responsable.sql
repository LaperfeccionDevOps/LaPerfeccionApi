-- Responsable del permiso de trabajo en alturas.
-- Por ahora puede ser cualquier persona contratada (RegistroPersonal).
-- Cuando existan los roles, se tomará del usuario autenticado.
-- La columna admite NULL solo por los permisos creados antes de este cambio;
-- el backend la exige para los permisos nuevos.

BEGIN;

ALTER TABLE public."PermisoTrabajoAlturas"
    ADD COLUMN IF NOT EXISTS "IdRegistroPersonalResponsable" bigint
        REFERENCES public."RegistroPersonal"("IdRegistroPersonal");

CREATE INDEX IF NOT EXISTS "IX_PermisoTrabajoAlturas_Responsable"
    ON public."PermisoTrabajoAlturas" ("IdRegistroPersonalResponsable");

COMMIT;

-- Reversa (solo si se necesita deshacer):
-- ALTER TABLE public."PermisoTrabajoAlturas" DROP COLUMN IF EXISTS "IdRegistroPersonalResponsable";
