-- =============================================================================
-- Contabilidad > Asignar operarios: tipo de turno (Diurno, Tarde, Noche)
-- Fecha: 2026-11-10
--
-- Reglas validadas con Contabilidad: cada línea de la asignación es de uno de
-- tres turnos y completa las horas máximas de la semana (hoy 42):
--   DIURNO  sin horas nocturnas.
--   TARDE   termina entre las 19:00 y las 24:00 (MinutoFinTurno 1140 a 1440);
--           las horas desde las 19:00 hasta la salida son nocturnas.
--   NOCHE   todas sus horas son nocturnas.
-- Domingo a domingo: la tarde o la noche pueden terminar el domingo a otra hora
-- (MinutoFinDomingo); las horas del día son las mismas, pero cambia cuántas
-- son nocturnas dominicales y cuántas dominicales diurnas.
-- Ya no se registran horarios de entrada/salida ni desayuno, almuerzo o cena.
-- AsignacionCentroCostoHorario se conserva solo para consultar las
-- asignaciones registradas antes de este cambio (TipoTurno vacío); las horas
-- calculadas de esas líneas no cambian.
--
-- Se ejecuta después de 20261109_contabilidad_asignacion_centros_costo.sql.
-- Se puede ejecutar más de una vez.
-- =============================================================================

BEGIN;

ALTER TABLE public."AsignacionCentroCostoDetalle"
    ADD COLUMN IF NOT EXISTS "TipoTurno"      varchar(10),
    -- Solo para TARDE: minutos desde la medianoche (1140 = 19:00, 1440 = 24:00).
    ADD COLUMN IF NOT EXISTS "MinutoFinTurno" smallint,
    -- Solo TARDE o NOCHE con domingo: salida del domingo si es distinta (1 a 1440).
    ADD COLUMN IF NOT EXISTS "MinutoFinDomingo" smallint;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'CK_AsignacionDetalle_TipoTurno'
    ) THEN
        ALTER TABLE public."AsignacionCentroCostoDetalle"
            ADD CONSTRAINT "CK_AsignacionDetalle_TipoTurno"
            CHECK ("TipoTurno" IS NULL OR "TipoTurno" IN ('DIURNO', 'TARDE', 'NOCHE'));
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'CK_AsignacionDetalle_FinTurnoTarde'
    ) THEN
        -- La hora de salida va solo en la tarde y entre las 19:00 y las 24:00.
        ALTER TABLE public."AsignacionCentroCostoDetalle"
            ADD CONSTRAINT "CK_AsignacionDetalle_FinTurnoTarde"
            CHECK (
                ("TipoTurno" = 'TARDE' AND "MinutoFinTurno" BETWEEN 1140 AND 1440)
                OR ("TipoTurno" IS DISTINCT FROM 'TARDE' AND "MinutoFinTurno" IS NULL)
            );
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'CK_AsignacionDetalle_FinDomingo'
    ) THEN
        ALTER TABLE public."AsignacionCentroCostoDetalle"
            ADD CONSTRAINT "CK_AsignacionDetalle_FinDomingo"
            CHECK (
                "MinutoFinDomingo" IS NULL
                OR ("TipoTurno" IN ('TARDE', 'NOCHE') AND "MinutoFinDomingo" BETWEEN 1 AND 1440)
            );
    END IF;
END $$;

COMMIT;

-- =============================================================================
-- Reversa (ejecutar manualmente si se necesita deshacer)
-- =============================================================================
-- BEGIN;
-- ALTER TABLE public."AsignacionCentroCostoDetalle"
--     DROP CONSTRAINT IF EXISTS "CK_AsignacionDetalle_FinDomingo",
--     DROP CONSTRAINT IF EXISTS "CK_AsignacionDetalle_FinTurnoTarde",
--     DROP COLUMN IF EXISTS "MinutoFinDomingo",
--     DROP CONSTRAINT IF EXISTS "CK_AsignacionDetalle_TipoTurno",
--     DROP COLUMN IF EXISTS "MinutoFinTurno",
--     DROP COLUMN IF EXISTS "TipoTurno";
-- COMMIT;
