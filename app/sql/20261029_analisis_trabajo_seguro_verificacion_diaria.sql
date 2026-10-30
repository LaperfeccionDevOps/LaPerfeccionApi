-- Bloque 5 del análisis de trabajo seguro: verificación diaria.
--
-- El análisis cubre una semana real (lunes a domingo): la fecha de
-- finalización de la actividad no puede pasar del domingo de la semana en que
-- se creó. Cada día de ese rango se responde una lista de preguntas
-- (Sí / No / No aplica) del catálogo "ItemPermisoAlturas" (TipoItem =
-- 'ATS_DIARIA'). Un día diligenciado después de su fecha queda marcado como
-- tardío.
--
-- Requiere 20261013_permiso_alturas_items.sql y
-- 20261021_analisis_trabajo_seguro.sql.

BEGIN;

-- 1. Semana real: la actividad termina a más tardar el domingo de la semana
--    de creación (hora de Colombia).
ALTER TABLE public."AnalisisTrabajoSeguro"
    DROP CONSTRAINT IF EXISTS "CK_AnalisisTrabajoSeguro_Semana";

ALTER TABLE public."AnalisisTrabajoSeguro"
    ADD CONSTRAINT "CK_AnalisisTrabajoSeguro_Semana"
    CHECK ("FechaFinalizacionActividad"
           <= date_trunc('week', "FechaCreacion" AT TIME ZONE 'America/Bogota')::date + 6);

-- 2. Catálogo de preguntas: nuevo tipo y respuesta que se considera alerta.
ALTER TABLE public."ItemPermisoAlturas"
    DROP CONSTRAINT IF EXISTS "ItemPermisoAlturas_TipoItem_check";

ALTER TABLE public."ItemPermisoAlturas"
    ADD CONSTRAINT "ItemPermisoAlturas_TipoItem_check"
    CHECK ("TipoItem" IN ('PROTECCION', 'VERIFICACION', 'PELIGRO', 'ATS_DIARIA'));

-- Respuesta que indica un problema (p. ej. "No" en "¿Se han establecido los
-- puntos de anclaje?" o "Sí" en "¿Existen hoyos...?"). Se resalta en pantalla
-- y en el PDF.
ALTER TABLE public."ItemPermisoAlturas"
    ADD COLUMN IF NOT EXISTS "RespuestaAlerta" varchar(2);

ALTER TABLE public."ItemPermisoAlturas"
    DROP CONSTRAINT IF EXISTS "CK_ItemPermisoAlturas_RespuestaAlerta";

ALTER TABLE public."ItemPermisoAlturas"
    ADD CONSTRAINT "CK_ItemPermisoAlturas_RespuestaAlerta"
    CHECK ("RespuestaAlerta" IS NULL OR "RespuestaAlerta" IN ('SI', 'NO'));

INSERT INTO public."ItemPermisoAlturas" ("TipoItem", "Codigo", "Texto", "Orden", "RespuestaAlerta")
VALUES
    ('ATS_DIARIA', 'VDA_01', '¿Se han establecido los puntos de anclaje?', 1, 'NO'),
    ('ATS_DIARIA', 'VDA_02', '¿Se han realizado los cálculos de la distancia de caída?', 2, 'NO'),
    ('ATS_DIARIA', 'VDA_03', '¿Cuenta con los sistemas de prevención requeridos?', 3, 'NO'),
    ('ATS_DIARIA', 'VDA_04', '¿Cuenta con los elementos de protección requeridos?', 4, 'NO'),
    ('ATS_DIARIA', 'VDA_05', '¿Cuenta con los materiales e insumos necesarios?', 5, 'NO'),
    ('ATS_DIARIA', 'VDA_06', '¿Existen hoyos o desniveles en el área de trabajo?', 6, 'SI'),
    ('ATS_DIARIA', 'VDA_07', '¿Hay peligro de resbalar o tropezar alrededor del área de trabajo?', 7, 'SI'),
    ('ATS_DIARIA', 'VDA_08', '¿Se encuentran líneas eléctricas en el área a intervenir?', 8, 'SI'),
    ('ATS_DIARIA', 'VDA_09', '¿Se encuentran superficies rotas o en mal estado (marquesinas, techos, vidrios, lámparas, fachadas o estructuras)?', 9, 'SI')
ON CONFLICT ("Codigo") DO NOTHING;

-- 3. Un registro por análisis y día.
CREATE TABLE IF NOT EXISTS public."AnalisisTrabajoSeguroDia" (
    "IdAnalisisTrabajoSeguroDia" bigserial PRIMARY KEY,
    "IdAnalisisTrabajoSeguro" bigint NOT NULL
        REFERENCES public."AnalisisTrabajoSeguro"("IdAnalisisTrabajoSeguro")
        ON DELETE CASCADE,
    "Fecha"                   date        NOT NULL,
    -- Persona que diligencia ese día.
    "IdRegistroPersonal"      bigint      NOT NULL
        REFERENCES public."RegistroPersonal"("IdRegistroPersonal"),
    "Observaciones"           varchar(1000),
    -- Se diligenció después de la fecha del día (para alertas).
    "DiligenciadoTarde"       boolean     NOT NULL,
    "FechaRegistro"           timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT "UQ_AnalisisTrabajoSeguroDia"
        UNIQUE ("IdAnalisisTrabajoSeguro", "Fecha")
);

-- 4. Respuesta de cada pregunta en cada día.
CREATE TABLE IF NOT EXISTS public."AnalisisTrabajoSeguroDiaRespuesta" (
    "IdAnalisisTrabajoSeguroDia" bigint NOT NULL
        REFERENCES public."AnalisisTrabajoSeguroDia"("IdAnalisisTrabajoSeguroDia")
        ON DELETE CASCADE,
    "IdItemPermisoAlturas"       integer NOT NULL
        REFERENCES public."ItemPermisoAlturas"("IdItemPermisoAlturas"),
    "Respuesta"                  varchar(2) NOT NULL
        CHECK ("Respuesta" IN ('SI', 'NO', 'NA')),
    PRIMARY KEY ("IdAnalisisTrabajoSeguroDia", "IdItemPermisoAlturas")
);

COMMIT;

-- Reversa (solo si se necesita deshacer; antes, regresar el código):
-- BEGIN;
-- DROP TABLE IF EXISTS public."AnalisisTrabajoSeguroDiaRespuesta";
-- DROP TABLE IF EXISTS public."AnalisisTrabajoSeguroDia";
-- DELETE FROM public."ItemPermisoAlturas" WHERE "TipoItem" = 'ATS_DIARIA';
-- ALTER TABLE public."ItemPermisoAlturas"
--     DROP CONSTRAINT "CK_ItemPermisoAlturas_RespuestaAlerta",
--     DROP COLUMN "RespuestaAlerta",
--     DROP CONSTRAINT "ItemPermisoAlturas_TipoItem_check";
-- ALTER TABLE public."ItemPermisoAlturas"
--     ADD CONSTRAINT "ItemPermisoAlturas_TipoItem_check"
--     CHECK ("TipoItem" IN ('PROTECCION', 'VERIFICACION', 'PELIGRO'));
-- ALTER TABLE public."AnalisisTrabajoSeguro"
--     DROP CONSTRAINT "CK_AnalisisTrabajoSeguro_Semana";
-- COMMIT;
