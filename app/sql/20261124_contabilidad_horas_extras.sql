-- =============================================================================
-- Contabilidad > Asignar operarios: horas extras por línea
-- Fecha: 2026-11-24
--
-- Reglas validadas con Contabilidad:
--   * En algunos centros los operarios hacen horas extras. Cada línea de la
--     asignación indica si las tiene y cuántas por operario y por semana, de
--     cada tipo que aplique:
--       HED   extra diurna
--       HEN   extra nocturna
--       HEDF  extra diurna dominical o festiva
--       HENF  extra nocturna dominical o festiva
--   * Se registran a tiempo completo, como las horas de recargo, y se ajustan
--     con la dedicación: por persona = horas × Dedicacion; total de la línea =
--     horas × CantidadOperarios × Dedicacion (operarios equivalentes).
--   * Tope legal (Ley 2101 de 2021): 12 horas extras por semana por operario,
--     sumando los cuatro tipos. Lo valida la API.
--   * Las líneas ya registradas quedan sin horas extras (0).
--   * La salida del turno de la tarde pasa a elegirse cada 5 minutos (p. ej.
--     19:15); lo valida la API y no requiere cambios en la base.
--
-- Se ejecuta después de 20261119_contabilidad_salida_por_dia.sql.
-- Se puede ejecutar más de una vez.
-- =============================================================================

BEGIN;

ALTER TABLE public."AsignacionCentroCostoDetalle"
    ADD COLUMN IF NOT EXISTS "HorasExtraDiurnasSemana"             numeric(5,2) NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS "HorasExtraNocturnasSemana"           numeric(5,2) NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS "HorasExtraDiurnasFestivasSemana"     numeric(5,2) NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS "HorasExtraNocturnasFestivasSemana"   numeric(5,2) NOT NULL DEFAULT 0;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'CK_AsignacionDetalle_HorasExtra'
    ) THEN
        ALTER TABLE public."AsignacionCentroCostoDetalle"
            ADD CONSTRAINT "CK_AsignacionDetalle_HorasExtra"
            CHECK ("HorasExtraDiurnasSemana" >= 0
                   AND "HorasExtraNocturnasSemana" >= 0
                   AND "HorasExtraDiurnasFestivasSemana" >= 0
                   AND "HorasExtraNocturnasFestivasSemana" >= 0);
    END IF;
END $$;

COMMENT ON COLUMN public."AsignacionCentroCostoDetalle"."HorasExtraDiurnasSemana" IS
    'Horas extra diurnas por operario y semana, a tiempo completo (se multiplican por la dedicación).';
COMMENT ON COLUMN public."AsignacionCentroCostoDetalle"."HorasExtraNocturnasSemana" IS
    'Horas extra nocturnas por operario y semana, a tiempo completo (se multiplican por la dedicación).';
COMMENT ON COLUMN public."AsignacionCentroCostoDetalle"."HorasExtraDiurnasFestivasSemana" IS
    'Horas extra diurnas dominicales o festivas por operario y semana, a tiempo completo (se multiplican por la dedicación).';
COMMENT ON COLUMN public."AsignacionCentroCostoDetalle"."HorasExtraNocturnasFestivasSemana" IS
    'Horas extra nocturnas dominicales o festivas por operario y semana, a tiempo completo (se multiplican por la dedicación).';

COMMIT;

-- =============================================================================
-- Reversa (ejecutar manualmente si se necesita deshacer)
-- =============================================================================
-- BEGIN;
-- ALTER TABLE public."AsignacionCentroCostoDetalle"
--     DROP CONSTRAINT IF EXISTS "CK_AsignacionDetalle_HorasExtra",
--     DROP COLUMN IF EXISTS "HorasExtraNocturnasFestivasSemana",
--     DROP COLUMN IF EXISTS "HorasExtraDiurnasFestivasSemana",
--     DROP COLUMN IF EXISTS "HorasExtraNocturnasSemana",
--     DROP COLUMN IF EXISTS "HorasExtraDiurnasSemana";
-- COMMIT;
