-- =============================================================================
-- Contabilidad > Centros de costo: fechas de inicio y fin del proyecto
-- Fecha: 2026-11-10
--
-- Cada centro de costo registra:
--   FechaInicioProyecto  Proyección de cuándo empieza; se puede ajustar. Puede
--                        ser anterior a la creación (ajustes de la ficha).
--   FechaFinProyecto     Opcional: vacía si aún no hay fecha pactada.
--
-- No se agrega un estado nuevo: el centro sigue ABIERTO o CERRADO, y la API
-- calcula la etapa con estas fechas (POR_INICIAR, EN_EJECUCION, FIN_VENCIDO).
-- Un centro "por iniciar" está ABIERTO, así que se puede usar para asignar
-- operarios, dotación, etc. Al vencer el fin solo se avisa; Contabilidad lo
-- cierra manualmente.
--
-- Los centros existentes toman como inicio su fecha de apertura cuando la
-- tienen; si no, la fecha queda vacía (no se inventa).
-- Los cambios de estas fechas quedan en el historial (MODIFICADO).
--
-- Se ejecuta después de 20261030_contabilidad_centros_costo.sql. Se puede
-- ejecutar más de una vez.
-- =============================================================================

BEGIN;

ALTER TABLE public."CentroCostoContable"
    ADD COLUMN IF NOT EXISTS "FechaInicioProyecto" date,
    ADD COLUMN IF NOT EXISTS "FechaFinProyecto"    date;

UPDATE public."CentroCostoContable"
SET "FechaInicioProyecto" = "FechaApertura"
WHERE "FechaInicioProyecto" IS NULL
  AND "FechaApertura" IS NOT NULL;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'CK_CentroCostoContable_FechasProyecto'
    ) THEN
        ALTER TABLE public."CentroCostoContable"
            ADD CONSTRAINT "CK_CentroCostoContable_FechasProyecto"
            CHECK ("FechaFinProyecto" IS NULL
                   OR "FechaInicioProyecto" IS NULL
                   OR "FechaFinProyecto" >= "FechaInicioProyecto");
    END IF;
END $$;

-- Historial: igual que en 20261030, más las fechas del proyecto.
CREATE OR REPLACE FUNCTION public."FN_CentroCostoContable_Historial"()
RETURNS trigger
LANGUAGE plpgsql
AS $$
DECLARE
    v_usuario  varchar(100) := COALESCE(NULLIF(current_setting('app.usuario', true), ''),
                                        'SQL directo: ' || session_user);
    v_motivo   varchar(500) := NULLIF(current_setting('app.motivo', true), '');
    v_fecha    date         := NULLIF(current_setting('app.fecha_efectiva', true), '')::date;
    v_accion   varchar(20);
    v_detalle  text         := '';
BEGIN
    IF TG_OP = 'INSERT' THEN
        INSERT INTO public."HistorialCentroCosto" (
            "IdCentroCostoContable", "Accion", "EstadoAnterior", "EstadoNuevo",
            "FechaEfectiva", "Motivo", "Detalle", "Usuario"
        ) VALUES (
            NEW."IdCentroCostoContable", 'CREADO', NULL, NEW."Estado",
            COALESCE(v_fecha, NEW."FechaApertura"), v_motivo,
            'Centro de costo creado en estado ' || NEW."Estado"
                || COALESCE('; inicio del proyecto ' || to_char(NEW."FechaInicioProyecto", 'DD/MM/YYYY'), '')
                || COALESCE('; fin del proyecto ' || to_char(NEW."FechaFinProyecto", 'DD/MM/YYYY'),
                            CASE WHEN NEW."FechaInicioProyecto" IS NOT NULL
                                 THEN '; sin fecha de fin pactada' ELSE '' END),
            v_usuario
        );
        RETURN NEW;
    END IF;

    -- UPDATE
    IF NEW."Estado" IS DISTINCT FROM OLD."Estado" THEN
        v_accion  := CASE WHEN NEW."Estado" = 'CERRADO' THEN 'CERRADO' ELSE 'REABIERTO' END;
        v_detalle := 'Estado ' || OLD."Estado" || ' → ' || NEW."Estado";
        v_fecha   := COALESCE(v_fecha,
                              CASE WHEN NEW."Estado" = 'CERRADO' THEN NEW."FechaCierre"
                                   ELSE NEW."FechaApertura" END);
    ELSE
        v_accion := 'MODIFICADO';
    END IF;

    IF NEW."IdSedeContable" IS DISTINCT FROM OLD."IdSedeContable" THEN
        v_detalle := v_detalle || '; sede ' || OLD."IdSedeContable" || ' → ' || NEW."IdSedeContable";
    END IF;
    IF NEW."IdDepartamentoContable" IS DISTINCT FROM OLD."IdDepartamentoContable" THEN
        v_detalle := v_detalle || '; departamento ' || OLD."IdDepartamentoContable" || ' → ' || NEW."IdDepartamentoContable";
    END IF;
    IF NEW."IdLineaNegocio" IS DISTINCT FROM OLD."IdLineaNegocio" THEN
        v_detalle := v_detalle || '; línea ' || OLD."IdLineaNegocio" || ' → ' || NEW."IdLineaNegocio";
    END IF;
    IF NEW."IdServicioAsociado" IS DISTINCT FROM OLD."IdServicioAsociado" THEN
        v_detalle := v_detalle || '; servicio ' || OLD."IdServicioAsociado" || ' → ' || NEW."IdServicioAsociado";
    END IF;
    IF NEW."FechaApertura" IS DISTINCT FROM OLD."FechaApertura" AND v_accion = 'MODIFICADO' THEN
        v_detalle := v_detalle || '; fecha de apertura ' || COALESCE(OLD."FechaApertura"::text, 'vacía') || ' → ' || COALESCE(NEW."FechaApertura"::text, 'vacía');
    END IF;
    IF NEW."FechaCierre" IS DISTINCT FROM OLD."FechaCierre" AND v_accion = 'MODIFICADO' THEN
        v_detalle := v_detalle || '; fecha de cierre ' || COALESCE(OLD."FechaCierre"::text, 'vacía') || ' → ' || COALESCE(NEW."FechaCierre"::text, 'vacía');
    END IF;
    IF NEW."FechaInicioProyecto" IS DISTINCT FROM OLD."FechaInicioProyecto" THEN
        v_detalle := v_detalle || '; inicio del proyecto '
            || COALESCE(to_char(OLD."FechaInicioProyecto", 'DD/MM/YYYY'), 'sin fecha') || ' → '
            || COALESCE(to_char(NEW."FechaInicioProyecto", 'DD/MM/YYYY'), 'sin fecha');
    END IF;
    IF NEW."FechaFinProyecto" IS DISTINCT FROM OLD."FechaFinProyecto" THEN
        v_detalle := v_detalle || '; fin del proyecto '
            || COALESCE(to_char(OLD."FechaFinProyecto", 'DD/MM/YYYY'), 'sin fecha') || ' → '
            || COALESCE(to_char(NEW."FechaFinProyecto", 'DD/MM/YYYY'), 'sin fecha');
    END IF;
    IF NEW."PendienteRevision" IS DISTINCT FROM OLD."PendienteRevision" THEN
        v_detalle := v_detalle || CASE WHEN NEW."PendienteRevision"
                                       THEN '; marcado pendiente de revisión'
                                       ELSE '; revisión resuelta' END;
    END IF;

    v_detalle := ltrim(v_detalle, '; ');

    -- Cambios solo en auditoría (fecha/usuario de actualización): no se registran.
    IF v_detalle = '' THEN
        RETURN NEW;
    END IF;

    INSERT INTO public."HistorialCentroCosto" (
        "IdCentroCostoContable", "Accion", "EstadoAnterior", "EstadoNuevo",
        "FechaEfectiva", "Motivo", "Detalle", "Usuario"
    ) VALUES (
        NEW."IdCentroCostoContable", v_accion, OLD."Estado", NEW."Estado",
        v_fecha, v_motivo, v_detalle, v_usuario
    );

    RETURN NEW;
END;
$$;

COMMIT;

-- =============================================================================
-- Reversa (ejecutar manualmente si se necesita deshacer)
-- Volver a ejecutar la función FN_CentroCostoContable_Historial de
-- 20261030_contabilidad_centros_costo.sql y luego:
-- =============================================================================
-- BEGIN;
-- ALTER TABLE public."CentroCostoContable"
--     DROP CONSTRAINT IF EXISTS "CK_CentroCostoContable_FechasProyecto",
--     DROP COLUMN IF EXISTS "FechaFinProyecto",
--     DROP COLUMN IF EXISTS "FechaInicioProyecto";
-- COMMIT;
