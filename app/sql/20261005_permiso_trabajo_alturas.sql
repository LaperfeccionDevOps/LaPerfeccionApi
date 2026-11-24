-- Permisos de trabajo en alturas (Resolución 4272 de 2021)
-- Versión inicial: solo los primeros campos del formulario.
-- Los demás campos se agregarán en scripts posteriores con ALTER TABLE.

BEGIN;

CREATE TABLE IF NOT EXISTS public."PermisoTrabajoAlturas" (
    "IdPermisoTrabajoAlturas" bigserial PRIMARY KEY,
    "IdCliente"               integer NOT NULL
        REFERENCES public."Cliente"("IdCliente"),
    "Sede"                    varchar(150) NOT NULL,
    "FechaCreacion"           timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS "IX_PermisoTrabajoAlturas_IdCliente"
    ON public."PermisoTrabajoAlturas" ("IdCliente");

COMMIT;

-- Reversa (solo si se necesita deshacer):
-- DROP TABLE IF EXISTS public."PermisoTrabajoAlturas";
