-- Listas de selección múltiple del paso 3 del permiso de trabajo en alturas.
--
-- Catálogo "OpcionPermisoAlturas" (una sola tabla, con tipo):
--   MECANISMO           -> Mecanismo / tipo de trabajo en alturas a realizar
--   SISTEMA_INGENIERIA  -> Sistemas de ingeniería
--   HERRAMIENTA         -> Herramientas a utilizar
--   SISTEMA_ACCESO      -> Sistemas de acceso a utilizar
-- Cada opción tiene su llave primaria y "Activo" para que, más adelante, HSEQ
-- pueda agregar o inactivar opciones sin cambiar tablas ni código.
--
-- "PermisoTrabajoAlturasOpcion" guarda las opciones elegidas en cada permiso
-- (una o varias por tipo).
--
-- Las columnas de texto anteriores ("TipoTrabajoAlturas",
-- "HerramientasUtensilios", "SistemasAcceso", "SistemasIngenieria") se
-- conservan solo como dato histórico de los permisos creados antes de este
-- cambio; los permisos nuevos usan estas listas.

BEGIN;

CREATE TABLE IF NOT EXISTS public."OpcionPermisoAlturas" (
    "IdOpcionPermisoAlturas" serial PRIMARY KEY,
    "Tipo"          varchar(30)  NOT NULL
        CHECK ("Tipo" IN ('MECANISMO', 'SISTEMA_INGENIERIA', 'HERRAMIENTA', 'SISTEMA_ACCESO')),
    "Codigo"        varchar(30)  NOT NULL UNIQUE,
    "Nombre"        varchar(150) NOT NULL,
    "Orden"         integer      NOT NULL,
    "Activo"        boolean      NOT NULL DEFAULT true,
    "FechaCreacion" timestamptz  NOT NULL DEFAULT now(),
    CONSTRAINT "UQ_OpcionPermisoAlturas_TipoNombre" UNIQUE ("Tipo", "Nombre")
);

CREATE TABLE IF NOT EXISTS public."PermisoTrabajoAlturasOpcion" (
    "IdPermisoTrabajoAlturas" bigint NOT NULL
        REFERENCES public."PermisoTrabajoAlturas"("IdPermisoTrabajoAlturas")
        ON DELETE CASCADE,
    "IdOpcionPermisoAlturas"  integer NOT NULL
        REFERENCES public."OpcionPermisoAlturas"("IdOpcionPermisoAlturas"),
    "FechaRegistro"           timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY ("IdPermisoTrabajoAlturas", "IdOpcionPermisoAlturas")
);

CREATE INDEX IF NOT EXISTS "IX_PermisoTrabajoAlturasOpcion_Opcion"
    ON public."PermisoTrabajoAlturasOpcion" ("IdOpcionPermisoAlturas");

INSERT INTO public."OpcionPermisoAlturas" ("Tipo", "Codigo", "Nombre", "Orden")
VALUES
    -- Mecanismo / tipo de trabajo en alturas
    ('MECANISMO', 'MEC_01', 'Suspensión', 1),
    ('MECANISMO', 'MEC_02', 'Plataformas elevadoras', 2),
    ('MECANISMO', 'MEC_03', 'Andamios, postes y torres', 3),
    ('MECANISMO', 'MEC_04', 'Pasarelas', 4),
    ('MECANISMO', 'MEC_05', 'Escalera fija y tipo gato', 5),
    ('MECANISMO', 'MEC_06', 'Trabajo en tejado o cubierta', 6),
    ('MECANISMO', 'MEC_07', 'Trabajos en profundidad', 7),
    ('MECANISMO', 'MEC_08', 'Escalera tipo tijera', 8),
    ('MECANISMO', 'MEC_09', 'Escalera de extensión', 9),
    ('MECANISMO', 'MEC_10', 'Trabajo en andamio eléctrico suspendido', 10),
    ('MECANISMO', 'MEC_11', 'Prueba para mecanismo', 11),
    -- Sistemas de ingeniería
    ('SISTEMA_INGENIERIA', 'ING_01', 'Barandas de seguridad', 1),
    ('SISTEMA_INGENIERIA', 'ING_02', 'Plataformas permanentes de trabajo', 2),
    ('SISTEMA_INGENIERIA', 'ING_03', 'Puntos de anclaje certificados', 3),
    ('SISTEMA_INGENIERIA', 'ING_04', 'Sistemas de riel horizontal', 4),
    ('SISTEMA_INGENIERIA', 'ING_05', 'Sistemas en guaya', 5),
    ('SISTEMA_INGENIERIA', 'ING_06', 'Cerramiento de bordes y aperturas', 6),
    ('SISTEMA_INGENIERIA', 'ING_07', 'Instalación de tapas resistentes para fosos o desniveles', 7),
    ('SISTEMA_INGENIERIA', 'ING_08', 'Protección de bordes', 8),
    ('SISTEMA_INGENIERIA', 'ING_09', 'Líneas de vida horizontales', 9),
    ('SISTEMA_INGENIERIA', 'ING_10', 'Líneas de vida verticales', 10),
    ('SISTEMA_INGENIERIA', 'ING_11', 'Pescantes', 11),
    -- Herramientas
    ('HERRAMIENTA', 'HER_01', 'Cuchilla de bisturí', 1),
    ('HERRAMIENTA', 'HER_02', 'Cuchilla limpia vidrios', 2),
    ('HERRAMIENTA', 'HER_03', 'Raspador', 3),
    ('HERRAMIENTA', 'HER_04', 'Toallas', 4),
    ('HERRAMIENTA', 'HER_05', 'Espátula', 5),
    ('HERRAMIENTA', 'HER_06', 'Destornillador', 6),
    ('HERRAMIENTA', 'HER_07', 'Taladro', 7),
    ('HERRAMIENTA', 'HER_08', 'Hidrolavadora', 8),
    ('HERRAMIENTA', 'HER_09', 'Manguera de alta presión', 9),
    ('HERRAMIENTA', 'HER_10', 'Boquilla o lanza de hidrolavadora', 10),
    ('HERRAMIENTA', 'HER_11', 'Balde plástico', 11),
    ('HERRAMIENTA', 'HER_12', 'Cepillo de cerdas duras', 12),
    ('HERRAMIENTA', 'HER_13', 'Escobilla o cepillo manual', 13),
    ('HERRAMIENTA', 'HER_14', 'Brocha', 14),
    ('HERRAMIENTA', 'HER_15', 'Escobillón', 15),
    ('HERRAMIENTA', 'HER_16', 'Aplicador para producto químico', 16),
    -- Sistemas de acceso
    ('SISTEMA_ACCESO', 'ACC_01', 'Cuerdas certificadas', 1),
    ('SISTEMA_ACCESO', 'ACC_02', 'Líneas de vida en guaya', 2),
    ('SISTEMA_ACCESO', 'ACC_03', 'Escaleras fijas', 3),
    ('SISTEMA_ACCESO', 'ACC_04', 'Escaleras tipo tijera', 4),
    ('SISTEMA_ACCESO', 'ACC_05', 'Escaleras de extensión', 5),
    ('SISTEMA_ACCESO', 'ACC_06', 'Plataformas elevadoras', 6),
    ('SISTEMA_ACCESO', 'ACC_07', 'Pasarelas', 7),
    ('SISTEMA_ACCESO', 'ACC_08', 'Cubiertas', 8),
    ('SISTEMA_ACCESO', 'ACC_09', 'Estructuras', 9),
    ('SISTEMA_ACCESO', 'ACC_10', 'Andamios', 10),
    ('SISTEMA_ACCESO', 'ACC_11', 'Torres de acceso', 11)
ON CONFLICT ("Codigo") DO NOTHING;

COMMIT;

-- Reversa (solo si se necesita deshacer):
-- DROP TABLE IF EXISTS public."PermisoTrabajoAlturasOpcion";
-- DROP TABLE IF EXISTS public."OpcionPermisoAlturas";
