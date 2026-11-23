-- Contabilidad > Centros de costo (alineados con la codificación de Synergy).
--
--   ClienteContable        Cliente real, identificado por su NIT.
--   ProyectoContable       CEN 1 (proyecto o contrato del cliente).
--   DepartamentoContable   CEN 2.
--   SedeContable           CEN 3 (subsede del cliente).
--   LineaNegocio           CEN 4.
--   ServicioAsociado       CEN 5.
--   CentroCostoContable    Combinación CEN 1 a CEN 5, con estado y fechas.
--   HistorialCentroCosto   Cada creación, cierre, reapertura o cambio.
--
-- El historial lo escribe siempre el trigger "TR_CentroCostoContable_Historial",
-- también cuando el cambio se hace por SQL directo. La API le indica quién hizo
-- el cambio, el motivo y la fecha efectiva con variables de la transacción:
--     SET LOCAL app.usuario        = '...';
--     SET LOCAL app.motivo         = '...';
--     SET LOCAL app.fecha_efectiva = 'AAAA-MM-DD';
--
-- Se nombran "Contable" para no confundirlas con las tablas existentes
-- "Cliente" (que en la práctica guarda proyecto + sede + servicio) y
-- "CentroCosto" (posiciones importadas de Synergy).

BEGIN;

-- ─────────────────────────────────────────────
-- Catálogos
-- ─────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS public."ClienteContable" (
    "IdClienteContable" serial       PRIMARY KEY,
    -- NIT con dígito de verificación, p. ej. 860066942-4.
    "Nit"               varchar(20)  NOT NULL UNIQUE
        CHECK ("Nit" ~ '^[0-9]{5,15}-[0-9]$'),
    "RazonSocial"       varchar(200) NOT NULL CHECK (btrim("RazonSocial") <> ''),
    "Activo"            boolean      NOT NULL DEFAULT true,
    "FechaCreacion"     timestamptz  NOT NULL DEFAULT now(),
    "CreadoPor"         varchar(100)
);

CREATE TABLE IF NOT EXISTS public."ProyectoContable" (
    "IdProyectoContable" serial       PRIMARY KEY,
    -- CEN 1, p. ej. COMPEN.
    "Codigo"             varchar(20)  NOT NULL UNIQUE CHECK (btrim("Codigo") <> ''),
    "Nombre"             varchar(200) NOT NULL CHECK (btrim("Nombre") <> ''),
    "IdClienteContable"  integer      NOT NULL
        REFERENCES public."ClienteContable"("IdClienteContable"),
    "Activo"             boolean      NOT NULL DEFAULT true,
    "FechaCreacion"      timestamptz  NOT NULL DEFAULT now(),
    "CreadoPor"          varchar(100)
);

CREATE INDEX IF NOT EXISTS "IX_ProyectoContable_IdCliente"
    ON public."ProyectoContable" ("IdClienteContable");

CREATE TABLE IF NOT EXISTS public."DepartamentoContable" (
    "IdDepartamentoContable" serial       PRIMARY KEY,
    -- CEN 2, p. ej. CBOGO.
    "Codigo"                 varchar(20)  NOT NULL UNIQUE CHECK (btrim("Codigo") <> ''),
    "Nombre"                 varchar(100) NOT NULL CHECK (btrim("Nombre") <> ''),
    "Activo"                 boolean      NOT NULL DEFAULT true,
    "FechaCreacion"          timestamptz  NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS public."SedeContable" (
    "IdSedeContable"     serial       PRIMARY KEY,
    -- CEN 3, p. ej. COMPE20.
    "Codigo"             varchar(20)  NOT NULL UNIQUE CHECK (btrim("Codigo") <> ''),
    "Descripcion"        varchar(300) NOT NULL CHECK (btrim("Descripcion") <> ''),
    "IdProyectoContable" integer      NOT NULL
        REFERENCES public."ProyectoContable"("IdProyectoContable"),
    "Activo"             boolean      NOT NULL DEFAULT true,
    "FechaCreacion"      timestamptz  NOT NULL DEFAULT now(),
    "CreadoPor"          varchar(100)
);

CREATE INDEX IF NOT EXISTS "IX_SedeContable_IdProyecto"
    ON public."SedeContable" ("IdProyectoContable");

CREATE TABLE IF NOT EXISTS public."LineaNegocio" (
    "IdLineaNegocio" serial       PRIMARY KEY,
    -- CEN 4, p. ej. 01ASGE.
    "Codigo"         varchar(20)  NOT NULL UNIQUE CHECK (btrim("Codigo") <> ''),
    "Nombre"         varchar(150) NOT NULL CHECK (btrim("Nombre") <> ''),
    "Activo"         boolean      NOT NULL DEFAULT true,
    "FechaCreacion"  timestamptz  NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS public."ServicioAsociado" (
    "IdServicioAsociado" serial       PRIMARY KEY,
    -- CEN 5, p. ej. 0105REC.
    "Codigo"             varchar(20)  NOT NULL UNIQUE CHECK (btrim("Codigo") <> ''),
    "Nombre"             varchar(150) NOT NULL CHECK (btrim("Nombre") <> ''),
    "Activo"             boolean      NOT NULL DEFAULT true,
    "FechaCreacion"      timestamptz  NOT NULL DEFAULT now()
);

-- ─────────────────────────────────────────────
-- Centro de costo (CEN 1 a CEN 5)
-- ─────────────────────────────────────────────
-- El CEN 1 (proyecto) y el cliente salen de la sede.
CREATE TABLE IF NOT EXISTS public."CentroCostoContable" (
    "IdCentroCostoContable"  serial      PRIMARY KEY,
    "IdSedeContable"         integer     NOT NULL
        REFERENCES public."SedeContable"("IdSedeContable"),
    "IdDepartamentoContable" integer     NOT NULL
        REFERENCES public."DepartamentoContable"("IdDepartamentoContable"),
    "IdLineaNegocio"         integer     NOT NULL
        REFERENCES public."LineaNegocio"("IdLineaNegocio"),
    "IdServicioAsociado"     integer     NOT NULL
        REFERENCES public."ServicioAsociado"("IdServicioAsociado"),
    "Estado"                 varchar(10) NOT NULL DEFAULT 'ABIERTO'
        CHECK ("Estado" IN ('ABIERTO', 'CERRADO')),
    -- Período vigente. En la carga inicial quedan vacías (la matriz no las
    -- trae); desde entonces cada apertura y cierre registra su fecha.
    "FechaApertura"          date,
    "FechaCierre"            date,
    -- Casos del diagnóstico de la matriz que Contabilidad debe confirmar.
    "PendienteRevision"      boolean     NOT NULL DEFAULT false,
    "ObservacionRevision"    varchar(500),
    "FechaCreacion"          timestamptz NOT NULL DEFAULT now(),
    "CreadoPor"              varchar(100),
    "FechaActualizacion"     timestamptz,
    "ActualizadoPor"         varchar(100),
    -- La misma combinación de Synergy no se repite.
    CONSTRAINT "UQ_CentroCostoContable_Combinacion"
        UNIQUE ("IdSedeContable", "IdDepartamentoContable", "IdLineaNegocio", "IdServicioAsociado"),
    -- Un centro abierto no tiene fecha de cierre.
    CONSTRAINT "CK_CentroCostoContable_CierreAbierto"
        CHECK ("Estado" = 'CERRADO' OR "FechaCierre" IS NULL),
    CONSTRAINT "CK_CentroCostoContable_Fechas"
        CHECK ("FechaApertura" IS NULL OR "FechaCierre" IS NULL
               OR "FechaCierre" >= "FechaApertura"),
    CONSTRAINT "CK_CentroCostoContable_Revision"
        CHECK (NOT "PendienteRevision" OR "ObservacionRevision" IS NOT NULL)
);

CREATE INDEX IF NOT EXISTS "IX_CentroCostoContable_Estado"
    ON public."CentroCostoContable" ("Estado");

-- ─────────────────────────────────────────────
-- Historial
-- ─────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS public."HistorialCentroCosto" (
    "IdHistorialCentroCosto" bigserial    PRIMARY KEY,
    -- Sin cascada: un centro con historial no se puede borrar (se cierra).
    "IdCentroCostoContable"  integer      NOT NULL
        REFERENCES public."CentroCostoContable"("IdCentroCostoContable"),
    "Accion"                 varchar(20)  NOT NULL
        CHECK ("Accion" IN ('CREADO', 'CERRADO', 'REABIERTO', 'MODIFICADO')),
    "EstadoAnterior"         varchar(10),
    "EstadoNuevo"            varchar(10)  NOT NULL,
    -- Cuándo ocurrió realmente (cuenta para facturación) y cuándo se anotó.
    "FechaEfectiva"          date,
    "FechaRegistro"          timestamptz  NOT NULL DEFAULT now(),
    "Motivo"                 varchar(500),
    "Detalle"                varchar(1000),
    "Usuario"                varchar(100) NOT NULL
);

CREATE INDEX IF NOT EXISTS "IX_HistorialCentroCosto_IdCentro"
    ON public."HistorialCentroCosto" ("IdCentroCostoContable", "FechaRegistro");

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
            'Centro de costo creado en estado ' || NEW."Estado", v_usuario
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

DROP TRIGGER IF EXISTS "TR_CentroCostoContable_Historial" ON public."CentroCostoContable";

CREATE TRIGGER "TR_CentroCostoContable_Historial"
    AFTER INSERT OR UPDATE ON public."CentroCostoContable"
    FOR EACH ROW
    EXECUTE FUNCTION public."FN_CentroCostoContable_Historial"();

COMMIT;

-- Reversa (solo si se necesita deshacer; borra también la carga inicial):
-- BEGIN;
-- DROP TRIGGER IF EXISTS "TR_CentroCostoContable_Historial" ON public."CentroCostoContable";
-- DROP FUNCTION IF EXISTS public."FN_CentroCostoContable_Historial"();
-- DROP TABLE IF EXISTS public."HistorialCentroCosto";
-- DROP TABLE IF EXISTS public."CentroCostoContable";
-- DROP TABLE IF EXISTS public."ServicioAsociado";
-- DROP TABLE IF EXISTS public."LineaNegocio";
-- DROP TABLE IF EXISTS public."SedeContable";
-- DROP TABLE IF EXISTS public."DepartamentoContable";
-- DROP TABLE IF EXISTS public."ProyectoContable";
-- DROP TABLE IF EXISTS public."ClienteContable";
-- COMMIT;
