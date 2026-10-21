-- Medidas de control de cada peligro (sección 7 del formato F-SS-007).
-- Texto fijo del formato que se imprime junto a cada peligro en el PDF.

BEGIN;

ALTER TABLE public."ItemPermisoAlturas"
    ADD COLUMN IF NOT EXISTS "MedidaControl" text;

UPDATE public."ItemPermisoAlturas" AS I
SET "MedidaControl" = V.medida
FROM (VALUES
    ('PEL_01', 'Guantes y recomendaciones generales, usar herramientas en buenas condiciones'),
    ('PEL_02', 'Demarcar y señalizar el área, uso de casco'),
    ('PEL_03', 'Obtener permiso de trabajo - SPCC - EPP'),
    ('PEL_04', 'Disponer de sistemas de comunicación o código de señales'),
    ('PEL_05', 'Dos o más personas según cargas'),
    ('PEL_06', 'Utilizar siempre protección auditiva cuando esté expuesto'),
    ('PEL_07', 'Utilizar siempre protección respiratoria cuando esté expuesto'),
    ('PEL_08', 'Hacer pausas durante la jornada de labor')
) AS V(codigo, medida)
WHERE I."Codigo" = V.codigo;

COMMIT;

-- Reversa (solo si se necesita deshacer):
-- ALTER TABLE public."ItemPermisoAlturas" DROP COLUMN IF EXISTS "MedidaControl";
