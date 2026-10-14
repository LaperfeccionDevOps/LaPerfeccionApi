-- 7. Autorización del permiso de trabajo en alturas.
--
-- Firmas del permiso (una por rol):
--   AUTORIZA     -> persona que autoriza el trabajo
--   COORDINADOR  -> el responsable del permiso
--   EMERGENCIAS  -> responsable de activar el plan de emergencias
--   AYUDANTE     -> ayudante de seguridad (solo si aplica)
--
-- Al autorizar, el permiso pasa a AUTORIZADO, queda bloqueado y se envía por
-- correo a los destinatarios configurados en el servidor. El resultado del
-- envío queda registrado en el permiso.

BEGIN;

CREATE TABLE IF NOT EXISTS public."PermisoTrabajoAlturasFirma" (
    "IdPermisoTrabajoAlturasFirma" bigserial PRIMARY KEY,
    "IdPermisoTrabajoAlturas" bigint NOT NULL
        REFERENCES public."PermisoTrabajoAlturas"("IdPermisoTrabajoAlturas")
        ON DELETE CASCADE,
    "Rol"                     varchar(20) NOT NULL
        CHECK ("Rol" IN ('AUTORIZA', 'COORDINADOR', 'EMERGENCIAS', 'AYUDANTE')),
    "IdRegistroPersonal"      bigint NOT NULL
        REFERENCES public."RegistroPersonal"("IdRegistroPersonal"),
    -- Firma como imagen PNG (unos 10-30 KB).
    "FirmaImagen"             bytea NOT NULL,
    "FechaFirma"              timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT "UQ_PermisoAlturasFirma_Rol"
        UNIQUE ("IdPermisoTrabajoAlturas", "Rol")
);

ALTER TABLE public."PermisoTrabajoAlturas"
    ADD COLUMN IF NOT EXISTS "AplicaAyudanteSeguridad" boolean,
    ADD COLUMN IF NOT EXISTS "Observaciones"           text,
    ADD COLUMN IF NOT EXISTS "FechaAutorizacion"       timestamptz,
    -- Envío del permiso por correo (destinatarios definidos en el servidor).
    ADD COLUMN IF NOT EXISTS "CorreoEnviadoA"          varchar(500),
    ADD COLUMN IF NOT EXISTS "FechaEnvioCorreo"        timestamptz,
    ADD COLUMN IF NOT EXISTS "ErrorEnvioCorreo"        text;

-- Un permiso autorizado (o cerrado) siempre tiene fecha de autorización.
ALTER TABLE public."PermisoTrabajoAlturas"
    ADD CONSTRAINT "CK_PermisoTrabajoAlturas_FechaAutorizacion"
    CHECK ("Estado" = 'EN_DILIGENCIAMIENTO' OR "FechaAutorizacion" IS NOT NULL);

COMMIT;

-- Reversa (solo si se necesita deshacer):
-- ALTER TABLE public."PermisoTrabajoAlturas" DROP CONSTRAINT IF EXISTS "CK_PermisoTrabajoAlturas_FechaAutorizacion";
-- ALTER TABLE public."PermisoTrabajoAlturas"
--     DROP COLUMN IF EXISTS "AplicaAyudanteSeguridad",
--     DROP COLUMN IF EXISTS "Observaciones",
--     DROP COLUMN IF EXISTS "FechaAutorizacion",
--     DROP COLUMN IF EXISTS "CorreoEnviadoA",
--     DROP COLUMN IF EXISTS "FechaEnvioCorreo",
--     DROP COLUMN IF EXISTS "ErrorEnvioCorreo";
-- DROP TABLE IF EXISTS public."PermisoTrabajoAlturasFirma";
