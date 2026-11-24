-- Listas de preguntas del permiso de trabajo en alturas (catálogo) y sus
-- respuestas por permiso. Se usa para:
--   PROTECCION   -> 4. Elementos de protección personal y contra caídas
--   VERIFICACION -> 5. Lista de verificación          (próximamente)
--   PELIGRO      -> 6. Identificación de peligros      (próximamente)
-- Así, agregar o corregir una pregunta no requiere cambiar tablas ni código:
-- basta con insertar/actualizar el catálogo (o desactivarla con "Activo").

BEGIN;

CREATE TABLE IF NOT EXISTS public."ItemPermisoAlturas" (
    "IdItemPermisoAlturas" serial PRIMARY KEY,
    "TipoItem"             varchar(20) NOT NULL
        CHECK ("TipoItem" IN ('PROTECCION', 'VERIFICACION', 'PELIGRO')),
    "Codigo"               varchar(60) NOT NULL UNIQUE,
    "Texto"                text        NOT NULL,
    "Orden"                integer     NOT NULL,
    "Activo"               boolean     NOT NULL DEFAULT true,
    "FechaCreacion"        timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS public."PermisoTrabajoAlturasRespuesta" (
    "IdPermisoTrabajoAlturasRespuesta" bigserial PRIMARY KEY,
    "IdPermisoTrabajoAlturas" bigint NOT NULL
        REFERENCES public."PermisoTrabajoAlturas"("IdPermisoTrabajoAlturas")
        ON DELETE CASCADE,
    "IdItemPermisoAlturas"    integer NOT NULL
        REFERENCES public."ItemPermisoAlturas"("IdItemPermisoAlturas"),
    -- SI, NO o NA (no aplica).
    "Respuesta"               varchar(2) NOT NULL
        CHECK ("Respuesta" IN ('SI', 'NO', 'NA')),
    "FechaRegistro"           timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT "UQ_PermisoAlturasRespuesta"
        UNIQUE ("IdPermisoTrabajoAlturas", "IdItemPermisoAlturas")
);

-- 4. "Otro ¿cuál?": único campo abierto del paso de protección (opcional).
ALTER TABLE public."PermisoTrabajoAlturas"
    ADD COLUMN IF NOT EXISTS "OtroElementoProteccion" varchar(300);

-- 4. Elementos de protección personal y elementos de protección contra caídas
INSERT INTO public."ItemPermisoAlturas" ("TipoItem", "Codigo", "Texto", "Orden")
VALUES
    ('PROTECCION', 'EPP_PROTECTOR_AUDITIVO',      'Protector auditivo',        1),
    ('PROTECCION', 'EPP_BOTAS_SEGURIDAD',         'Botas de seguridad',        2),
    ('PROTECCION', 'EPP_SISTEMA_ANCLAJE',         'Sistema de anclaje',        3),
    ('PROTECCION', 'EPP_TRAJE_IMPERMEABLE',       'Traje impermeable',         4),
    ('PROTECCION', 'EPP_PROTECTOR_RESPIRATORIO',  'Protector respiratorio',    5),
    ('PROTECCION', 'EPP_LINEA_VIDA_HORIZONTAL',   'Línea de vida horizontal',  6),
    ('PROTECCION', 'EPP_CONECTORES',              'Conectores',                7),
    ('PROTECCION', 'EPP_GAFAS_SEGURIDAD',         'Gafas de seguridad',        8),
    ('PROTECCION', 'EPP_LINEA_VIDA_VERTICAL',     'Línea de vida vertical',    9),
    ('PROTECCION', 'EPP_ARNES_CUERPO_COMPLETO',   'Arnés de cuerpo completo', 10),
    ('PROTECCION', 'EPP_GUANTES',                 'Guantes',                  11),
    ('PROTECCION', 'EPP_OVEROL',                  'Overol',                   12),
    ('PROTECCION', 'EPP_CASCO_BARBOQUEJO',        'Casco con barboquejo',     13)
ON CONFLICT ("Codigo") DO NOTHING;

COMMIT;

-- Reversa (solo si se necesita deshacer):
-- ALTER TABLE public."PermisoTrabajoAlturas" DROP COLUMN IF EXISTS "OtroElementoProteccion";
-- DROP TABLE IF EXISTS public."PermisoTrabajoAlturasRespuesta";
-- DROP TABLE IF EXISTS public."ItemPermisoAlturas";
