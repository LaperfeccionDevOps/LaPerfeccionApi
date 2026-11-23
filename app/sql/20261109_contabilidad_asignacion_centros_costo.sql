-- =============================================================================
-- Contabilidad > Centros de costo > Asignar: operarios por centro de costo
-- Fecha: 2026-11-09
--
-- Contabilidad registra cuántos operarios de cada cargo trabajan en un centro
-- de costo, qué días y en qué horario. Es solo la cantidad (cupos), no las
-- personas. Tablas:
--   1. "ModalidadDias": lunes a viernes, lunes a sábado, domingo a domingo.
--   2. "ParametroJornadaLaboral": reglas legales con vigencia (franja nocturna,
--      horas máximas por semana, % de recargos). Se consultan por fecha.
--   3. "AsignacionCentroCosto": encabezado con vigencia. Un cambio de personal
--      no sobrescribe: se finaliza la vigente y se crea otra.
--   4. "AsignacionCentroCostoDetalle": una línea por grupo de operarios (cargo,
--      cantidad, modalidad) con las horas semanales que calcula la API.
--   5. "AsignacionCentroCostoHorario": horario GENERAL de la línea y, si aplica,
--      uno de SABADO (p. ej. medio día), con desayuno, almuerzo y cena.
-- Reglas en la base:
--   - Solo se asigna a centros ABIERTOS (trigger).
--   - Un centro tiene a lo sumo una asignación VIGENTE.
--   - Al cerrar un centro, su asignación vigente se finaliza con la fecha de
--     cierre (trigger).
-- Se ejecuta después de 20261030_contabilidad_centros_costo.sql. Se puede
-- ejecutar más de una vez.
-- =============================================================================

BEGIN;

-- -----------------------------------------------------------------------------
-- 1. Modalidades de días (ISO: 1 = lunes ... 7 = domingo)
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS public."ModalidadDias" (
    "IdModalidadDias" serial       PRIMARY KEY,
    "Codigo"          varchar(10)  NOT NULL UNIQUE,
    "Nombre"          varchar(100) NOT NULL,
    "DiasSemana"      smallint[]   NOT NULL
        CHECK (cardinality("DiasSemana") > 0 AND "DiasSemana" <@ ARRAY[1, 2, 3, 4, 5, 6, 7]::smallint[]),
    "Activo"          boolean      NOT NULL DEFAULT true,
    "FechaCreacion"   timestamptz  NOT NULL DEFAULT now()
);

INSERT INTO public."ModalidadDias" ("Codigo", "Nombre", "DiasSemana") VALUES
    ('LV', 'Lunes a viernes',   ARRAY[1, 2, 3, 4, 5]::smallint[]),
    ('LS', 'Lunes a sábado',    ARRAY[1, 2, 3, 4, 5, 6]::smallint[]),
    ('DD', 'Domingo a domingo', ARRAY[1, 2, 3, 4, 5, 6, 7]::smallint[])
ON CONFLICT ("Codigo") DO NOTHING;

-- -----------------------------------------------------------------------------
-- 2. Parámetros legales de la jornada, con vigencia
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS public."ParametroJornadaLaboral" (
    "IdParametroJornadaLaboral"  serial       PRIMARY KEY,
    -- Rige desde esta fecha hasta la siguiente fila.
    "FechaDesde"                 date         NOT NULL UNIQUE,
    "HoraInicioNocturna"         time         NOT NULL,
    "HoraFinNocturna"            time         NOT NULL,
    "HorasMaximasSemana"         numeric(4,1) NOT NULL CHECK ("HorasMaximasSemana" > 0),
    "PorcentajeRecargoNocturno"  numeric(5,2) NOT NULL CHECK ("PorcentajeRecargoNocturno" >= 0),
    "PorcentajeRecargoDominical" numeric(5,2) NOT NULL CHECK ("PorcentajeRecargoDominical" >= 0),
    "Observacion"                varchar(500),
    "FechaCreacion"              timestamptz  NOT NULL DEFAULT now(),
    "CreadoPor"                  varchar(100)
);

-- Valores según Ley 2101 de 2021 (42 h desde 15-jul-2026) y Ley 2466 de 2025
-- (nocturna desde las 19:00; dominical 90 % desde 1-jul-2026 y 100 % desde
-- 1-jul-2027). Deben confirmarse con Nómina.
INSERT INTO public."ParametroJornadaLaboral" (
    "FechaDesde", "HoraInicioNocturna", "HoraFinNocturna", "HorasMaximasSemana",
    "PorcentajeRecargoNocturno", "PorcentajeRecargoDominical", "Observacion", "CreadoPor"
) VALUES
    ('2026-07-15', '19:00', '06:00', 42, 35, 90,
     'Jornada de 42 h (Ley 2101/2021); nocturna 19:00-06:00 y dominical 90 % (Ley 2466/2025). Confirmar con Nómina.',
     'SCRIPT_INICIAL'),
    ('2027-07-01', '19:00', '06:00', 42, 35, 100,
     'Dominical 100 % (Ley 2466/2025). Confirmar con Nómina.',
     'SCRIPT_INICIAL')
ON CONFLICT ("FechaDesde") DO NOTHING;

-- -----------------------------------------------------------------------------
-- 3. Asignación (encabezado con vigencia)
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS public."AsignacionCentroCosto" (
    "IdAsignacionCentroCosto" serial       PRIMARY KEY,
    "IdCentroCostoContable"   integer      NOT NULL
        REFERENCES public."CentroCostoContable"("IdCentroCostoContable"),
    "FechaDesde"              date         NOT NULL,
    "FechaHasta"              date,
    "Estado"                  varchar(12)  NOT NULL DEFAULT 'VIGENTE'
        CHECK ("Estado" IN ('VIGENTE', 'FINALIZADA')),
    "Observacion"             varchar(500),
    "FechaCreacion"           timestamptz  NOT NULL DEFAULT now(),
    "CreadoPor"               varchar(100),
    "FechaActualizacion"      timestamptz,
    "ActualizadoPor"          varchar(100),
    -- Vigente sin fecha final; finalizada con fecha final.
    CONSTRAINT "CK_AsignacionCentroCosto_EstadoFechas"
        CHECK (("Estado" = 'VIGENTE') = ("FechaHasta" IS NULL)),
    CONSTRAINT "CK_AsignacionCentroCosto_Fechas"
        CHECK ("FechaHasta" IS NULL OR "FechaHasta" >= "FechaDesde")
);

-- A lo sumo una asignación vigente por centro de costo.
CREATE UNIQUE INDEX IF NOT EXISTS "UX_AsignacionCentroCosto_Vigente"
    ON public."AsignacionCentroCosto" ("IdCentroCostoContable")
    WHERE "Estado" = 'VIGENTE';

-- -----------------------------------------------------------------------------
-- 4. Líneas: grupo de operarios de un cargo con su modalidad de días
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS public."AsignacionCentroCostoDetalle" (
    "IdAsignacionCentroCostoDetalle" serial       PRIMARY KEY,
    "IdAsignacionCentroCosto"        integer      NOT NULL
        REFERENCES public."AsignacionCentroCosto"("IdAsignacionCentroCosto") ON DELETE CASCADE,
    -- Tipo de operario: catálogo de cargos existente.
    "IdCargo"                        integer      NOT NULL
        REFERENCES public."Cargo"("IdCargo"),
    "CantidadOperarios"              integer      NOT NULL CHECK ("CantidadOperarios" > 0),
    "IdModalidadDias"                integer      NOT NULL
        REFERENCES public."ModalidadDias"("IdModalidadDias"),
    -- Domingo a domingo: cada operario descansa un día entre semana (trabaja 6
    -- de 7); el centro sigue cubierto los 7 días.
    "DescansaDiaEntreSemana"         boolean      NOT NULL DEFAULT false,
    -- Calculadas por la API por operario y por semana (descansos descontados
    -- en las horas semanales; las nocturnas y dominicales son las del turno).
    "HorasSemana"                    numeric(5,2) NOT NULL CHECK ("HorasSemana" > 0),
    "HorasNocturnasSemana"           numeric(5,2) NOT NULL DEFAULT 0 CHECK ("HorasNocturnasSemana" >= 0),
    "HorasDominicalesSemana"         numeric(5,2) NOT NULL DEFAULT 0 CHECK ("HorasDominicalesSemana" >= 0),
    -- Domingo en franja nocturna (llevan los dos recargos); incluidas en las anteriores.
    "HorasNocturnasDominicalesSemana" numeric(5,2) NOT NULL DEFAULT 0 CHECK ("HorasNocturnasDominicalesSemana" >= 0),
    "Observacion"                    varchar(500)
);

-- Para bases donde la tabla ya existía antes de agregar la columna.
ALTER TABLE public."AsignacionCentroCostoDetalle"
    ADD COLUMN IF NOT EXISTS "DescansaDiaEntreSemana" boolean NOT NULL DEFAULT false,
    ADD COLUMN IF NOT EXISTS "HorasNocturnasDominicalesSemana" numeric(5,2) NOT NULL DEFAULT 0
        CHECK ("HorasNocturnasDominicalesSemana" >= 0);

CREATE INDEX IF NOT EXISTS "IX_AsignacionCentroCostoDetalle_Asignacion"
    ON public."AsignacionCentroCostoDetalle" ("IdAsignacionCentroCosto");

-- -----------------------------------------------------------------------------
-- 5. Horarios de cada línea: GENERAL y, opcionalmente, SABADO
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS public."AsignacionCentroCostoHorario" (
    "IdAsignacionCentroCostoHorario" serial      PRIMARY KEY,
    "IdAsignacionCentroCostoDetalle" integer     NOT NULL
        REFERENCES public."AsignacionCentroCostoDetalle"("IdAsignacionCentroCostoDetalle") ON DELETE CASCADE,
    "TipoDia"                        varchar(10) NOT NULL CHECK ("TipoDia" IN ('GENERAL', 'SABADO')),
    -- Si la salida es menor o igual a la entrada, sale al día siguiente (22:00 -> 06:00).
    "HoraInicio"                     time        NOT NULL,
    "HoraFin"                        time        NOT NULL,
    -- Descansos: minutos (0 = no tiene) y hora de inicio. Se descuentan de las
    -- horas semanales y de la franja donde caen (nocturna, dominical).
    "MinutosDesayuno"                smallint    NOT NULL DEFAULT 0 CHECK ("MinutosDesayuno" BETWEEN 0 AND 120),
    "MinutosAlmuerzo"                smallint    NOT NULL DEFAULT 0 CHECK ("MinutosAlmuerzo" BETWEEN 0 AND 120),
    "MinutosCena"                    smallint    NOT NULL DEFAULT 0 CHECK ("MinutosCena" BETWEEN 0 AND 120),
    "HoraDesayuno"                   time,
    "HoraAlmuerzo"                   time,
    "HoraCena"                       time,
    CONSTRAINT "CK_AsignacionCentroCostoHorario_Horas" CHECK ("HoraInicio" <> "HoraFin"),
    -- Con minutos hay hora; sin minutos no.
    CONSTRAINT "CK_AsignacionCentroCostoHorario_HoraDescansos" CHECK (
        ("MinutosDesayuno" = 0) = ("HoraDesayuno" IS NULL)
        AND ("MinutosAlmuerzo" = 0) = ("HoraAlmuerzo" IS NULL)
        AND ("MinutosCena" = 0) = ("HoraCena" IS NULL)
    ),
    CONSTRAINT "UQ_AsignacionCentroCostoHorario_TipoDia"
        UNIQUE ("IdAsignacionCentroCostoDetalle", "TipoDia")
);

-- Para bases donde la tabla ya existía antes de agregar la hora de los descansos.
-- La regla queda NOT VALID: aplica a los registros nuevos sin tocar los anteriores.
ALTER TABLE public."AsignacionCentroCostoHorario"
    ADD COLUMN IF NOT EXISTS "HoraDesayuno" time,
    ADD COLUMN IF NOT EXISTS "HoraAlmuerzo" time,
    ADD COLUMN IF NOT EXISTS "HoraCena" time;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'CK_AsignacionCentroCostoHorario_HoraDescansos'
    ) THEN
        ALTER TABLE public."AsignacionCentroCostoHorario"
            ADD CONSTRAINT "CK_AsignacionCentroCostoHorario_HoraDescansos" CHECK (
                ("MinutosDesayuno" = 0) = ("HoraDesayuno" IS NULL)
                AND ("MinutosAlmuerzo" = 0) = ("HoraAlmuerzo" IS NULL)
                AND ("MinutosCena" = 0) = ("HoraCena" IS NULL)
            ) NOT VALID;
    END IF;
END $$;

-- -----------------------------------------------------------------------------
-- 6. Solo se asigna a centros de costo abiertos
-- -----------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION public."FN_AsignacionCentroCosto_ValidarCentroAbierto"()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    IF NEW."Estado" = 'VIGENTE' AND NOT EXISTS (
        SELECT 1
        FROM public."CentroCostoContable"
        WHERE "IdCentroCostoContable" = NEW."IdCentroCostoContable"
          AND "Estado" = 'ABIERTO'
    ) THEN
        RAISE EXCEPTION 'El centro de costo está cerrado; para asignarle operarios primero debe reabrirse.';
    END IF;

    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS "TR_AsignacionCentroCosto_ValidarCentroAbierto" ON public."AsignacionCentroCosto";
CREATE TRIGGER "TR_AsignacionCentroCosto_ValidarCentroAbierto"
    BEFORE INSERT OR UPDATE OF "Estado", "IdCentroCostoContable"
    ON public."AsignacionCentroCosto"
    FOR EACH ROW
    EXECUTE FUNCTION public."FN_AsignacionCentroCosto_ValidarCentroAbierto"();

-- -----------------------------------------------------------------------------
-- 7. Al cerrar un centro se finaliza su asignación vigente
-- -----------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION public."FN_CentroCostoContable_FinalizarAsignacion"()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    UPDATE public."AsignacionCentroCosto"
    SET "Estado"             = 'FINALIZADA',
        -- Sin fecha de cierre (o anterior al inicio) se usa la que no rompa el período.
        "FechaHasta"         = GREATEST(
                                   COALESCE(NEW."FechaCierre", (now() AT TIME ZONE 'America/Bogota')::date),
                                   "FechaDesde"
                               ),
        "FechaActualizacion" = now(),
        "ActualizadoPor"     = COALESCE(NULLIF(current_setting('app.usuario', true), ''),
                                        'SQL directo: ' || session_user)
    WHERE "IdCentroCostoContable" = NEW."IdCentroCostoContable"
      AND "Estado" = 'VIGENTE';

    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS "TR_CentroCostoContable_FinalizarAsignacion" ON public."CentroCostoContable";
CREATE TRIGGER "TR_CentroCostoContable_FinalizarAsignacion"
    AFTER UPDATE OF "Estado"
    ON public."CentroCostoContable"
    FOR EACH ROW
    WHEN (OLD."Estado" = 'ABIERTO' AND NEW."Estado" = 'CERRADO')
    EXECUTE FUNCTION public."FN_CentroCostoContable_FinalizarAsignacion"();

COMMIT;

-- =============================================================================
-- Reversa (ejecutar manualmente si se necesita deshacer)
-- =============================================================================
-- BEGIN;
-- DROP TRIGGER IF EXISTS "TR_CentroCostoContable_FinalizarAsignacion" ON public."CentroCostoContable";
-- DROP FUNCTION IF EXISTS public."FN_CentroCostoContable_FinalizarAsignacion"();
-- DROP TRIGGER IF EXISTS "TR_AsignacionCentroCosto_ValidarCentroAbierto" ON public."AsignacionCentroCosto";
-- DROP FUNCTION IF EXISTS public."FN_AsignacionCentroCosto_ValidarCentroAbierto"();
-- DROP TABLE IF EXISTS public."AsignacionCentroCostoHorario";
-- DROP TABLE IF EXISTS public."AsignacionCentroCostoDetalle";
-- DROP TABLE IF EXISTS public."AsignacionCentroCosto";
-- DROP TABLE IF EXISTS public."ParametroJornadaLaboral";
-- DROP TABLE IF EXISTS public."ModalidadDias";
-- COMMIT;
