-- =============================================================================
-- Contabilidad > Centros de costo: ubicación geográfica del CEN 2
-- Fecha: 2026-11-09
--
-- El CEN 2 ("DepartamentoContable") guarda el código de Synergy (CBOGO,
-- CCUNDI, CGIRAR...), que mezcla ciudades y departamentos. Este script:
--   1. Crea "DepartamentoGeografico": los 33 departamentos de Colombia con su
--      código DANE (incluye Bogotá D.C. = 11). Es el catálogo de nombres que le
--      falta a "LugarNacimiento", que solo trae el código del departamento.
--   2. Agrega a "DepartamentoContable" el departamento geográfico (obligatorio
--      para los nuevos, opcional en la tabla) y el municipio (opcional, de
--      "LugarNacimiento"; p. ej. CCUNDI no tiene municipio).
--   3. Valida con un trigger que el municipio pertenezca al departamento.
--   4. Enlaza los 14 CEN 2 cargados el 2026-10-30 buscando el municipio por
--      código de departamento y nombre (no por Id, que cambia entre bases).
--
-- No modifica "LugarNacimiento" ni ninguna tabla usada por otros módulos.
-- Se puede ejecutar más de una vez.
-- =============================================================================

BEGIN;

-- -----------------------------------------------------------------------------
-- 1. Departamentos de Colombia (DANE)
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS public."DepartamentoGeografico" (
    "IdDepartamentoGeografico" serial       PRIMARY KEY,
    -- Código DANE de dos dígitos; coincide con "LugarNacimiento"."CodigoDepartamento".
    "CodigoDane"               varchar(2)   NOT NULL UNIQUE CHECK ("CodigoDane" ~ '^[0-9]{2}$'),
    "Nombre"                   varchar(100) NOT NULL UNIQUE CHECK (btrim("Nombre") <> ''),
    "Activo"                   boolean      NOT NULL DEFAULT true,
    "FechaCreacion"            timestamptz  NOT NULL DEFAULT now()
);

INSERT INTO public."DepartamentoGeografico" ("CodigoDane", "Nombre") VALUES
    ('05', 'Antioquia'),
    ('08', 'Atlántico'),
    ('11', 'Bogotá D.C.'),
    ('13', 'Bolívar'),
    ('15', 'Boyacá'),
    ('17', 'Caldas'),
    ('18', 'Caquetá'),
    ('19', 'Cauca'),
    ('20', 'Cesar'),
    ('23', 'Córdoba'),
    ('25', 'Cundinamarca'),
    ('27', 'Chocó'),
    ('41', 'Huila'),
    ('44', 'La Guajira'),
    ('47', 'Magdalena'),
    ('50', 'Meta'),
    ('52', 'Nariño'),
    ('54', 'Norte de Santander'),
    ('63', 'Quindío'),
    ('66', 'Risaralda'),
    ('68', 'Santander'),
    ('70', 'Sucre'),
    ('73', 'Tolima'),
    ('76', 'Valle del Cauca'),
    ('81', 'Arauca'),
    ('85', 'Casanare'),
    ('86', 'Putumayo'),
    ('88', 'San Andrés, Providencia y Santa Catalina'),
    ('91', 'Amazonas'),
    ('94', 'Guainía'),
    ('95', 'Guaviare'),
    ('97', 'Vaupés'),
    ('99', 'Vichada')
ON CONFLICT ("CodigoDane") DO NOTHING;

-- -----------------------------------------------------------------------------
-- 2. Ubicación del CEN 2
-- -----------------------------------------------------------------------------
ALTER TABLE public."DepartamentoContable"
    ADD COLUMN IF NOT EXISTS "IdDepartamentoGeografico" integer
        REFERENCES public."DepartamentoGeografico"("IdDepartamentoGeografico"),
    -- Municipio del catálogo "LugarNacimiento" (municipios de todo el país).
    ADD COLUMN IF NOT EXISTS "IdMunicipio" integer
        REFERENCES public."LugarNacimiento"("IdLugarNacimiento");

CREATE INDEX IF NOT EXISTS "IX_DepartamentoContable_IdDepartamentoGeografico"
    ON public."DepartamentoContable" ("IdDepartamentoGeografico");

-- Un municipio sin departamento no tiene sentido.
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'CK_DepartamentoContable_MunicipioConDepartamento'
    ) THEN
        ALTER TABLE public."DepartamentoContable"
            ADD CONSTRAINT "CK_DepartamentoContable_MunicipioConDepartamento"
            CHECK ("IdMunicipio" IS NULL OR "IdDepartamentoGeografico" IS NOT NULL);
    END IF;
END $$;

-- -----------------------------------------------------------------------------
-- 3. El municipio debe pertenecer al departamento elegido
-- -----------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION public."FN_DepartamentoContable_ValidarUbicacion"()
RETURNS trigger
LANGUAGE plpgsql
AS $$
DECLARE
    v_codigo_municipio  varchar;
    v_codigo_dane       varchar;
BEGIN
    IF NEW."IdMunicipio" IS NULL THEN
        RETURN NEW;
    END IF;

    SELECT "CodigoDepartamento" INTO v_codigo_municipio
    FROM public."LugarNacimiento"
    WHERE "IdLugarNacimiento" = NEW."IdMunicipio";

    SELECT "CodigoDane" INTO v_codigo_dane
    FROM public."DepartamentoGeografico"
    WHERE "IdDepartamentoGeografico" = NEW."IdDepartamentoGeografico";

    IF v_codigo_municipio IS DISTINCT FROM v_codigo_dane THEN
        RAISE EXCEPTION 'El municipio no pertenece al departamento elegido (municipio del departamento %, departamento %).',
            v_codigo_municipio, v_codigo_dane;
    END IF;

    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS "TR_DepartamentoContable_ValidarUbicacion" ON public."DepartamentoContable";
CREATE TRIGGER "TR_DepartamentoContable_ValidarUbicacion"
    BEFORE INSERT OR UPDATE OF "IdDepartamentoGeografico", "IdMunicipio"
    ON public."DepartamentoContable"
    FOR EACH ROW
    EXECUTE FUNCTION public."FN_DepartamentoContable_ValidarUbicacion"();

-- -----------------------------------------------------------------------------
-- 4. Ubicación de los CEN 2 actuales (solo donde todavía no tiene)
-- -----------------------------------------------------------------------------
WITH ubicacion (codigo, codigo_dane, municipio) AS (
    VALUES
        ('CBARRA', '08', 'BARRANQUILLA'),
        ('CBOGO',  '11', 'BOGOTÁ D.C.'),
        ('CBUCAR', '68', 'BUCARAMANGA'),
        ('CCAJIC', '25', 'CAJICA'),
        ('CCALI',  '76', 'CALI'),
        ('CCHIA',  '25', 'CHIA'),
        ('CCOTA',  '25', 'COTA'),
        ('CCUNDI', '25', NULL),
        ('CFACA',  '25', 'FACATATIVA'),
        ('CFUNZA', '25', 'FUNZA'),
        ('CGIRAR', '25', 'GIRARDOT'),
        ('CMOSQ',  '25', 'MOSQUERA'),
        ('CSOAC',  '25', 'SOACHA'),
        ('CTOCAN', '25', 'TOCANCIPA')
)
UPDATE public."DepartamentoContable" DC
SET "IdDepartamentoGeografico" = DG."IdDepartamentoGeografico",
    "IdMunicipio" = (
        SELECT LN."IdLugarNacimiento"
        FROM public."LugarNacimiento" LN
        WHERE LN."CodigoDepartamento" = U.codigo_dane
          AND upper(btrim(LN."Nombre")) = U.municipio
        ORDER BY LN."IdLugarNacimiento"
        LIMIT 1
    )
FROM ubicacion U
JOIN public."DepartamentoGeografico" DG ON DG."CodigoDane" = U.codigo_dane
WHERE DC."Codigo" = U.codigo
  AND DC."IdDepartamentoGeografico" IS NULL;

-- Verificación: avisa (sin fallar) los CEN 2 sin ubicación o con municipio esperado no encontrado.
DO $$
DECLARE
    r record;
BEGIN
    FOR r IN
        SELECT "Codigo", "Nombre"
        FROM public."DepartamentoContable"
        WHERE "IdDepartamentoGeografico" IS NULL
           OR ("IdMunicipio" IS NULL AND "Codigo" <> 'CCUNDI')
    LOOP
        RAISE NOTICE 'Revisar ubicación del CEN 2 % (%)', r."Codigo", r."Nombre";
    END LOOP;
END $$;

COMMIT;

-- =============================================================================
-- Reversa (ejecutar manualmente si se necesita deshacer)
-- =============================================================================
-- BEGIN;
-- DROP TRIGGER IF EXISTS "TR_DepartamentoContable_ValidarUbicacion" ON public."DepartamentoContable";
-- DROP FUNCTION IF EXISTS public."FN_DepartamentoContable_ValidarUbicacion"();
-- ALTER TABLE public."DepartamentoContable"
--     DROP CONSTRAINT IF EXISTS "CK_DepartamentoContable_MunicipioConDepartamento",
--     DROP COLUMN IF EXISTS "IdMunicipio",
--     DROP COLUMN IF EXISTS "IdDepartamentoGeografico";
-- DROP TABLE IF EXISTS public."DepartamentoGeografico";
-- COMMIT;
