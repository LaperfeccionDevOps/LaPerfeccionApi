-- Análisis de Trabajo Seguro (Operaciones > Alturas).
-- Versión inicial: responsable, cliente, lugar de trabajo y trabajadores con
-- su firma.
-- Los demás campos se agregarán en scripts posteriores con ALTER TABLE.

BEGIN;

CREATE TABLE IF NOT EXISTS public."AnalisisTrabajoSeguro" (
    "IdAnalisisTrabajoSeguro"       bigserial PRIMARY KEY,
    -- Temporal: mientras no existan los roles, el responsable se elige en
    -- pantalla. Luego se tomará del usuario autenticado.
    "IdRegistroPersonalResponsable" bigint NOT NULL
        REFERENCES public."RegistroPersonal"("IdRegistroPersonal"),
    "IdCliente"                     integer NOT NULL
        REFERENCES public."Cliente"("IdCliente"),
    -- Lugar físico del cliente donde se hace la tarea (campo abierto).
    "LugarTrabajo"                  varchar(300) NOT NULL,
    -- El análisis puede diligenciarse por semana o por cambio de actividad:
    -- aplica desde su creación hasta esta fecha.
    "FechaFinalizacionActividad"    date NOT NULL,
    -- Altura aproximada a la que se realiza la actividad, en metros.
    "AlturaAproximadaMetros"        numeric(6, 2) NOT NULL,
    -- Bloque 3: se diligencia después de crear el análisis.
    "DescripcionTarea"              varchar(4000),
    -- Cuál otro permiso se necesita (si se marcó "Otro" en el bloque 3).
    "OtroPermisoRequerido"          varchar(300),
    -- Bloque 6: visto bueno del coordinador de alturas. Al darlo, el análisis
    -- queda APROBADO y no se modifican los bloques 1 a 4.
    "Estado"                        varchar(30) NOT NULL
        DEFAULT 'EN_DILIGENCIAMIENTO'
        CHECK ("Estado" IN ('EN_DILIGENCIAMIENTO', 'APROBADO')),
    "IdRegistroPersonalCoordinador" bigint
        REFERENCES public."RegistroPersonal"("IdRegistroPersonal"),
    "FirmaCoordinador"              bytea,
    "FechaVistoBueno"               timestamptz,
    "FechaCreacion"                 timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT "CK_AnalisisTrabajoSeguro_LugarTrabajo"
        CHECK (btrim("LugarTrabajo") <> ''),
    CONSTRAINT "CK_AnalisisTrabajoSeguro_Altura"
        CHECK ("AlturaAproximadaMetros" > 0),
    CONSTRAINT "CK_AnalisisTrabajoSeguro_Descripcion"
        CHECK ("DescripcionTarea" IS NULL OR btrim("DescripcionTarea") <> ''),
    CONSTRAINT "CK_AnalisisTrabajoSeguro_OtroPermiso"
        CHECK ("OtroPermisoRequerido" IS NULL OR btrim("OtroPermisoRequerido") <> ''),
    -- Aprobado si y solo si tiene coordinador, firma y fecha del visto bueno.
    CONSTRAINT "CK_AnalisisTrabajoSeguro_VistoBueno"
        CHECK (("Estado" = 'APROBADO') = (
            "IdRegistroPersonalCoordinador" IS NOT NULL
            AND "FirmaCoordinador" IS NOT NULL
            AND "FechaVistoBueno" IS NOT NULL
        )),
    -- No puede terminar antes del día en que se creó (hora de Colombia).
    CONSTRAINT "CK_AnalisisTrabajoSeguro_FechaFinalizacion"
        CHECK ("FechaFinalizacionActividad"
               >= ("FechaCreacion" AT TIME ZONE 'America/Bogota')::date)
);

CREATE INDEX IF NOT EXISTS "IX_AnalisisTrabajoSeguro_IdResponsable"
    ON public."AnalisisTrabajoSeguro" ("IdRegistroPersonalResponsable");

CREATE INDEX IF NOT EXISTS "IX_AnalisisTrabajoSeguro_IdCliente"
    ON public."AnalisisTrabajoSeguro" ("IdCliente");

-- Trabajadores que realizan la tarea. Cada uno se agrega con su firma.
CREATE TABLE IF NOT EXISTS public."AnalisisTrabajoSeguroTrabajador" (
    "IdAnalisisTrabajoSeguroTrabajador" bigserial PRIMARY KEY,
    "IdAnalisisTrabajoSeguro" bigint NOT NULL
        REFERENCES public."AnalisisTrabajoSeguro"("IdAnalisisTrabajoSeguro")
        ON DELETE CASCADE,
    "IdRegistroPersonal"      bigint NOT NULL
        REFERENCES public."RegistroPersonal"("IdRegistroPersonal"),
    -- Firma del trabajador como imagen PNG (unos 10-30 KB).
    "FirmaImagen"             bytea NOT NULL,
    "FechaFirma"              timestamptz NOT NULL DEFAULT now(),
    "FechaCreacion"           timestamptz NOT NULL DEFAULT now(),
    -- Una persona no puede registrarse dos veces en el mismo análisis.
    CONSTRAINT "UQ_AnalisisTrabajoSeguroTrabajador"
        UNIQUE ("IdAnalisisTrabajoSeguro", "IdRegistroPersonal")
);

CREATE INDEX IF NOT EXISTS "IX_AnalisisTrabajoSeguroTrabajador_IdRegistroPersonal"
    ON public."AnalisisTrabajoSeguroTrabajador" ("IdRegistroPersonal");

-- Bloque 4 (asignación de tareas e identificación de peligros): tareas del
-- análisis, numeradas por "Orden". Cada tarea tendrá luego sus peligros y
-- riesgos asociados.
CREATE TABLE IF NOT EXISTS public."AnalisisTrabajoSeguroTarea" (
    "IdAnalisisTrabajoSeguroTarea" bigserial PRIMARY KEY,
    "IdAnalisisTrabajoSeguro" bigint NOT NULL
        REFERENCES public."AnalisisTrabajoSeguro"("IdAnalisisTrabajoSeguro")
        ON DELETE CASCADE,
    "Orden"                   integer NOT NULL CHECK ("Orden" > 0),
    "PasoDetallado"           varchar(4000) NOT NULL
        CHECK (btrim("PasoDetallado") <> ''),
    "FechaCreacion"           timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT "UQ_AnalisisTrabajoSeguroTarea_Orden"
        UNIQUE ("IdAnalisisTrabajoSeguro", "Orden")
);

-- Opciones elegidas en el análisis del catálogo compartido con permisos de
-- trabajo en alturas ("OpcionPermisoAlturas"). Por ahora solo los sistemas de
-- acceso (Tipo = 'SISTEMA_ACCESO'); otras listas del catálogo pueden usar la
-- misma tabla.
CREATE TABLE IF NOT EXISTS public."AnalisisTrabajoSeguroOpcion" (
    "IdAnalisisTrabajoSeguro" bigint NOT NULL
        REFERENCES public."AnalisisTrabajoSeguro"("IdAnalisisTrabajoSeguro")
        ON DELETE CASCADE,
    "IdOpcionPermisoAlturas"  integer NOT NULL
        REFERENCES public."OpcionPermisoAlturas"("IdOpcionPermisoAlturas"),
    "FechaRegistro"           timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY ("IdAnalisisTrabajoSeguro", "IdOpcionPermisoAlturas")
);

COMMIT;

-- Reversa (solo si se necesita deshacer):
-- BEGIN;
-- DROP TABLE IF EXISTS public."AnalisisTrabajoSeguroTarea";
-- DROP TABLE IF EXISTS public."AnalisisTrabajoSeguroOpcion";
-- DROP TABLE IF EXISTS public."AnalisisTrabajoSeguroTrabajador";
-- DROP TABLE IF EXISTS public."AnalisisTrabajoSeguro";
-- COMMIT;
