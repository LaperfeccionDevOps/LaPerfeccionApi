-- =============================================================================
-- Contabilidad > Asignar operarios: dedicación parcial (operarios equivalentes)
-- Fecha: 2026-11-12 (ajustada el 2026-11-19: la dedicación va en decimal)
--
-- Reglas validadas con Contabilidad:
--   * Hay sedes donde no se labora todos los días y una persona va solo una
--     parte de su tiempo. Cada línea lleva la dedicación que Contabilidad
--     define directamente, en decimal: 0,3 = 30 % del tiempo; 1 = tiempo
--     completo. Hasta 4 decimales (p. ej. 0,3333).
--   * La base es siempre 24 días hábiles al mes (0,3 = 7,2 días hábiles);
--     la equivalencia en días es solo informativa y no se guarda.
--   * Operarios equivalentes = CantidadOperarios × Dedicacion.
--     Es lo que se le carga al centro: totales, "Asignación vigente sede" y las
--     horas de recargo (horas por operario × equivalentes).
--   * CantidadOperarios sigue siendo el número de personas (entero).
--   * Las líneas ya registradas quedan en 1 (mismo resultado de antes).
--
-- Se ejecuta después de 20261110_contabilidad_tipo_turno.sql.
-- Se puede ejecutar más de una vez.
-- =============================================================================

BEGIN;

ALTER TABLE public."AsignacionCentroCostoDetalle"
    ADD COLUMN IF NOT EXISTS "Dedicacion" numeric(5,4) NOT NULL DEFAULT 1;

-- Solo en las bases donde se aplicó la primera versión de este script (en
-- porcentaje): se pasa el valor a decimal y se quita la columna anterior.
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'public'
          AND table_name = 'AsignacionCentroCostoDetalle'
          AND column_name = 'PorcentajeDedicacion'
    ) THEN
        UPDATE public."AsignacionCentroCostoDetalle"
        SET "Dedicacion" = round("PorcentajeDedicacion" / 100, 4);

        ALTER TABLE public."AsignacionCentroCostoDetalle"
            DROP CONSTRAINT IF EXISTS "CK_AsignacionDetalle_PorcentajeDedicacion",
            DROP COLUMN "PorcentajeDedicacion";
    END IF;
END $$;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'CK_AsignacionDetalle_Dedicacion'
    ) THEN
        ALTER TABLE public."AsignacionCentroCostoDetalle"
            ADD CONSTRAINT "CK_AsignacionDetalle_Dedicacion"
            CHECK ("Dedicacion" > 0 AND "Dedicacion" <= 1);
    END IF;
END $$;

COMMENT ON COLUMN public."AsignacionCentroCostoDetalle"."Dedicacion" IS
    'Parte del tiempo (base 24 días hábiles al mes) que cada operario de la línea dedica al centro, en decimal: 0,3 = 30 %; 1 = tiempo completo.';

COMMIT;

-- =============================================================================
-- Reversa (ejecutar manualmente si se necesita deshacer)
-- =============================================================================
-- BEGIN;
-- ALTER TABLE public."AsignacionCentroCostoDetalle"
--     DROP CONSTRAINT IF EXISTS "CK_AsignacionDetalle_Dedicacion",
--     DROP COLUMN IF EXISTS "Dedicacion";
-- COMMIT;
