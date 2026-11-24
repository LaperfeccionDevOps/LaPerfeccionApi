-- Trabajadores de cada permiso de trabajo en alturas.
-- Un permiso tiene varios trabajadores; cada uno con sus respuestas y firma.
-- Las respuestas se guardan tal cual se diligencian (no bloquean el registro)
-- porque luego se generará el PDF del permiso con todas ellas.

BEGIN;

CREATE TABLE IF NOT EXISTS public."PermisoTrabajoAlturasTrabajador" (
    "IdPermisoTrabajoAlturasTrabajador" bigserial PRIMARY KEY,
    "IdPermisoTrabajoAlturas" bigint NOT NULL
        REFERENCES public."PermisoTrabajoAlturas"("IdPermisoTrabajoAlturas")
        ON DELETE CASCADE,
    "IdRegistroPersonal"      bigint NOT NULL
        REFERENCES public."RegistroPersonal"("IdRegistroPersonal"),
    "FechaExamenMedico"         date    NOT NULL,
    "FechaCertificadoAlturas"   date    NOT NULL,
    "SeguridadSocialVerificada" boolean NOT NULL,
    "ConsumeSustancias"         boolean NOT NULL,
    "ConsumeMedicamentos"       boolean NOT NULL,
    "CualesMedicamentos"        varchar(300),
    -- Firma del trabajador como imagen PNG (unos 10-30 KB).
    "FirmaImagen"               bytea,
    "FechaFirma"                timestamptz,
    "FechaCreacion"             timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT "UQ_PermisoAlturasTrabajador"
        UNIQUE ("IdPermisoTrabajoAlturas", "IdRegistroPersonal"),
    CONSTRAINT "CK_PermisoAlturasTrabajador_Medicamentos"
        CHECK (NOT "ConsumeMedicamentos" OR "CualesMedicamentos" IS NOT NULL),
    -- La firma y su fecha se guardan siempre juntas.
    CONSTRAINT "CK_PermisoAlturasTrabajador_Firma"
        CHECK (("FirmaImagen" IS NULL) = ("FechaFirma" IS NULL))
);

CREATE INDEX IF NOT EXISTS "IX_PermisoAlturasTrabajador_IdRegistroPersonal"
    ON public."PermisoTrabajoAlturasTrabajador" ("IdRegistroPersonal");

COMMIT;

-- Reversa (solo si se necesita deshacer):
-- DROP TABLE IF EXISTS public."PermisoTrabajoAlturasTrabajador";
