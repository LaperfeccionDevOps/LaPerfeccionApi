-- =============================================================================
-- Contabilidad > Asignar operarios: hora de salida distinta según el día
-- Fecha: 2026-11-19
--
-- Reglas validadas con Contabilidad:
--   * En el turno de la TARDE la salida puede cambiar según el día (p. ej.
--     lunes y martes 20:20, miércoles y viernes 21:00, jueves 22:00, sábado
--     19:00). Las horas por día siguen siendo iguales (horas de la semana entre
--     los días); lo que cambia con la salida es la entrada.
--   * La salida de cada día va de 19:00 a 24:00, como la general. Las
--     nocturnas de cada día van desde las 19:00 hasta su salida; un día que
--     termina antes se registra a las 19:00 (no suma nocturnas).
--   * Salidas cada 10 minutos.
--   * Domingo a domingo con descanso entre semana: el día de descanso rota
--     entre lunes y viernes, así que las nocturnas de esos días se promedian
--     (suma de lunes a viernes × 4/5) y se suman las del sábado y el domingo.
--   * El domingo va en la misma lista (reemplaza a "el domingo termina a otra
--     hora" en esas líneas; las ya registradas no cambian).
--
-- "MinutosFinPorDia": 7 posiciones (1 = lunes ... 7 = domingo) con los
-- minutos desde la medianoche de la salida de cada día (NULL en los días que no
-- labora). NULL en toda la línea = todos los días salen a "MinutoFinTurno".
--
-- Se ejecuta después de 20261119_contabilidad_cargos_sugeridos.sql.
-- Se puede ejecutar más de una vez.
-- =============================================================================

BEGIN;

ALTER TABLE public."AsignacionCentroCostoDetalle"
    ADD COLUMN IF NOT EXISTS "MinutosFinPorDia" smallint[];

-- Se borra y se vuelve a crear para que quede siempre con la regla vigente.
ALTER TABLE public."AsignacionCentroCostoDetalle"
    DROP CONSTRAINT IF EXISTS "CK_AsignacionDetalle_MinutosFinPorDia";

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'CK_AsignacionDetalle_MinutosFinPorDia'
    ) THEN
        ALTER TABLE public."AsignacionCentroCostoDetalle"
            ADD CONSTRAINT "CK_AsignacionDetalle_MinutosFinPorDia"
            CHECK (
                "MinutosFinPorDia" IS NULL
                OR (
                    "TipoTurno" = 'TARDE'
                    AND "MinutoFinDomingo" IS NULL
                    AND cardinality("MinutosFinPorDia") = 7
                    -- Las posiciones NULL (días que no labora) no hacen fallar la regla.
                    AND 1140 <= ALL ("MinutosFinPorDia")
                    AND 1440 >= ALL ("MinutosFinPorDia")
                )
            );
    END IF;
END $$;

COMMENT ON COLUMN public."AsignacionCentroCostoDetalle"."MinutosFinPorDia" IS
    'Turno tarde con salida distinta por día: minutos desde la medianoche de la salida de lunes (1) a domingo (7); NULL en los días que no labora.';

COMMIT;

-- Reversa:
-- ALTER TABLE public."AsignacionCentroCostoDetalle"
--     DROP CONSTRAINT IF EXISTS "CK_AsignacionDetalle_MinutosFinPorDia",
--     DROP COLUMN IF EXISTS "MinutosFinPorDia";
