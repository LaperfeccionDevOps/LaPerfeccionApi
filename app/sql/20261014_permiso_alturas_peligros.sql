-- 6. Identificación de peligros del trabajo a realizar.
-- Preguntas Sí / No / No aplica cargadas en el catálogo "ItemPermisoAlturas"
-- (creado en 20261013_permiso_alturas_items.sql). Sin campo abierto.

BEGIN;

INSERT INTO public."ItemPermisoAlturas" ("TipoItem", "Codigo", "Texto", "Orden")
VALUES
    ('PELIGRO', 'PEL_01', 'Golpes y choques contra objetos o por herramientas', 1),
    ('PELIGRO', 'PEL_02', 'Caída de objetos', 2),
    ('PELIGRO', 'PEL_03', 'Caída de altura', 3),
    ('PELIGRO', 'PEL_04', 'Atropellamiento', 4),
    ('PELIGRO', 'PEL_05', 'Manipulación de cargas', 5),
    ('PELIGRO', 'PEL_06', 'Exposición al ruido o vibraciones', 6),
    ('PELIGRO', 'PEL_07', 'Exposición al polvo', 7),
    ('PELIGRO', 'PEL_08', 'Trastorno musculoesquelético', 8)
ON CONFLICT ("Codigo") DO NOTHING;

COMMIT;

-- Reversa (solo si se necesita deshacer; borra también las respuestas dadas):
-- DELETE FROM public."PermisoTrabajoAlturasRespuesta"
--  WHERE "IdItemPermisoAlturas" IN (
--      SELECT "IdItemPermisoAlturas" FROM public."ItemPermisoAlturas"
--       WHERE "TipoItem" = 'PELIGRO');
-- DELETE FROM public."ItemPermisoAlturas" WHERE "TipoItem" = 'PELIGRO';
