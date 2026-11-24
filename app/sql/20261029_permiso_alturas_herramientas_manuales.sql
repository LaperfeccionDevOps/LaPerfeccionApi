-- Cambia el tipo de la lista de herramientas del catálogo
-- "OpcionPermisoAlturas" de 'HERRAMIENTA' a 'HERRAMIENTA_MANUAL' y reemplaza
-- sus opciones por la lista de herramientas manuales definida por HSEQ.
-- Requiere 20261016_permiso_alturas_opciones y
-- 20261021_analisis_trabajo_seguro.
--
-- No borra permisos ni análisis:
--   * Las herramientas anteriores que ningún registro usa se eliminan.
--   * Las que ya se usaron se desactivan (Activo = false): dejan de ofrecerse,
--     pero los permisos que las tienen conservan el dato.
--   * Si una herramienta nueva ya existía con el mismo nombre, se reutiliza
--     ese registro (el catálogo no admite nombres repetidos por tipo).

BEGIN;

-- 0. Tipo: 'HERRAMIENTA' pasa a 'HERRAMIENTA_MANUAL'.
ALTER TABLE public."OpcionPermisoAlturas"
    DROP CONSTRAINT IF EXISTS "OpcionPermisoAlturas_Tipo_check";

UPDATE public."OpcionPermisoAlturas"
SET "Tipo" = 'HERRAMIENTA_MANUAL'
WHERE "Tipo" = 'HERRAMIENTA';

ALTER TABLE public."OpcionPermisoAlturas"
    ADD CONSTRAINT "OpcionPermisoAlturas_Tipo_check"
    CHECK ("Tipo" IN ('MECANISMO', 'SISTEMA_INGENIERIA', 'HERRAMIENTA_MANUAL', 'SISTEMA_ACCESO'));

CREATE TEMP TABLE "HerramientasManuales" (
    "Orden"  integer PRIMARY KEY,
    "Nombre" varchar(150) NOT NULL
) ON COMMIT DROP;

INSERT INTO "HerramientasManuales" ("Orden", "Nombre") VALUES
    (1,  'Raspador'),
    (2,  'Cuchilla limpia vidrios'),
    (3,  'Espátula'),
    (4,  'Destornilladores'),
    (5,  'Brocha'),
    (6,  'Alicates'),
    (7,  'Llave inglesa'),
    (8,  'Martillo'),
    (9,  'Rodillo'),
    (10, 'Palaustre'),
    (11, 'Puntero'),
    (12, 'Maceta'),
    (13, 'Aspersor'),
    (14, 'Manguera'),
    (15, 'Pistola de silicona');

-- 1. Herramientas anteriores que no están en la lista nueva: se desactivan…
UPDATE public."OpcionPermisoAlturas" O
SET "Activo" = false
WHERE O."Tipo" = 'HERRAMIENTA_MANUAL'
  AND NOT EXISTS (
      SELECT 1 FROM "HerramientasManuales" N
      WHERE lower(N."Nombre") = lower(O."Nombre")
  );

-- …y se eliminan las que ningún permiso ni análisis ha usado.
DELETE FROM public."OpcionPermisoAlturas" O
WHERE O."Tipo" = 'HERRAMIENTA_MANUAL'
  AND NOT O."Activo"
  AND NOT EXISTS (
      SELECT 1 FROM public."PermisoTrabajoAlturasOpcion" PO
      WHERE PO."IdOpcionPermisoAlturas" = O."IdOpcionPermisoAlturas"
  )
  AND NOT EXISTS (
      SELECT 1 FROM public."AnalisisTrabajoSeguroOpcion" AO
      WHERE AO."IdOpcionPermisoAlturas" = O."IdOpcionPermisoAlturas"
  );

-- 2. Las que ya existían con el mismo nombre se reutilizan: quedan activas,
--    con el orden y el código nuevos.
UPDATE public."OpcionPermisoAlturas" O
SET "Nombre" = N."Nombre",
    "Orden"  = N."Orden",
    "Codigo" = 'HMA_' || lpad(N."Orden"::text, 2, '0'),
    "Activo" = true
FROM "HerramientasManuales" N
WHERE O."Tipo" = 'HERRAMIENTA_MANUAL'
  AND lower(O."Nombre") = lower(N."Nombre");

-- 3. Se crean las que faltan.
INSERT INTO public."OpcionPermisoAlturas" ("Tipo", "Codigo", "Nombre", "Orden", "Activo")
SELECT 'HERRAMIENTA_MANUAL',
       'HMA_' || lpad(N."Orden"::text, 2, '0'),
       N."Nombre",
       N."Orden",
       true
FROM "HerramientasManuales" N
WHERE NOT EXISTS (
    SELECT 1 FROM public."OpcionPermisoAlturas" O
    WHERE O."Tipo" = 'HERRAMIENTA_MANUAL'
      AND lower(O."Nombre") = lower(N."Nombre")
);

-- Verificación: deben quedar exactamente 15 herramientas activas.
DO $$
BEGIN
    IF (SELECT count(*) FROM public."OpcionPermisoAlturas"
        WHERE "Tipo" = 'HERRAMIENTA_MANUAL' AND "Activo") <> 15 THEN
        RAISE EXCEPTION 'Se esperaban 15 herramientas manuales activas.';
    END IF;
END $$;

COMMIT;

-- Reversa: no es automática (las herramientas no usadas se eliminan). Para
-- volver a la lista anterior: devolver el tipo a 'HERRAMIENTA' (y la regla
-- "OpcionPermisoAlturas_Tipo_check" con ese valor), reactivar las
-- desactivadas y cargar de nuevo las eliminadas desde
-- 20261016_permiso_alturas_opciones.sql. Antes, regresar el código que usa
-- 'HERRAMIENTA_MANUAL'.
