-- Permiso de trabajo en alturas: ciudad y lugar de trabajo (sección 1 del
-- formato F-SS-007). La ciudad se elige de la tabla "Ciudad"; el lugar de
-- trabajo es texto libre. Ambos son obligatorios.
-- Las columnas admiten NULL solo por los permisos creados antes de este
-- cambio; el backend los exige para los permisos nuevos.

BEGIN;

ALTER TABLE public."PermisoTrabajoAlturas"
    ADD COLUMN IF NOT EXISTS "IdCiudad" integer
        REFERENCES public."Ciudad"("IdCiudad"),
    ADD COLUMN IF NOT EXISTS "LugarTrabajo" varchar(300);

COMMIT;

-- Reversa (solo si se necesita deshacer):
-- ALTER TABLE public."PermisoTrabajoAlturas"
--     DROP COLUMN IF EXISTS "IdCiudad",
--     DROP COLUMN IF EXISTS "LugarTrabajo";
