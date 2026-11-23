-- =============================================================================
-- Contabilidad > Centros de costo: código del socio de negocio del cliente
-- Fecha: 2026-11-10
--
-- Al crear un cliente nuevo se registra su código de socio de negocio en
-- Synergy. La API lo exige para los clientes nuevos; en la tabla admite vacío
-- porque los clientes de la carga inicial no lo traen. No se puede repetir.
--
-- Se ejecuta después de 20261030_contabilidad_centros_costo.sql. Se puede
-- ejecutar más de una vez.
-- =============================================================================

BEGIN;

ALTER TABLE public."ClienteContable"
    ADD COLUMN IF NOT EXISTS "CodigoSocioNegocio" varchar(30);

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'CK_ClienteContable_CodigoSocioNegocio'
    ) THEN
        -- Si se registra: mayúsculas, números, guion, punto o guion bajo.
        ALTER TABLE public."ClienteContable"
            ADD CONSTRAINT "CK_ClienteContable_CodigoSocioNegocio"
            CHECK ("CodigoSocioNegocio" IS NULL
                   OR "CodigoSocioNegocio" ~ '^[A-Z0-9._-]{1,30}$');
    END IF;
END $$;

CREATE UNIQUE INDEX IF NOT EXISTS "UX_ClienteContable_CodigoSocioNegocio"
    ON public."ClienteContable" ("CodigoSocioNegocio")
    WHERE "CodigoSocioNegocio" IS NOT NULL;

COMMIT;

-- =============================================================================
-- Reversa (ejecutar manualmente si se necesita deshacer)
-- =============================================================================
-- BEGIN;
-- DROP INDEX IF EXISTS public."UX_ClienteContable_CodigoSocioNegocio";
-- ALTER TABLE public."ClienteContable"
--     DROP CONSTRAINT IF EXISTS "CK_ClienteContable_CodigoSocioNegocio",
--     DROP COLUMN IF EXISTS "CodigoSocioNegocio";
-- COMMIT;
