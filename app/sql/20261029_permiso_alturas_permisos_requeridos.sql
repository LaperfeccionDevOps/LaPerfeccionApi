-- Nueva lista del catálogo "OpcionPermisoAlturas": permisos que necesita el
-- trabajo (Tipo = 'PERMISO_REQUERIDO'). La usa el bloque 3 (Equipos) del
-- análisis de trabajo seguro: "Para este trabajo se necesita permiso de:".
--
-- Ejecutar DESPUÉS de 20261029_permiso_alturas_herramientas_manuales.sql,
-- porque ambos redefinen la regla de tipos permitidos.

BEGIN;

ALTER TABLE public."OpcionPermisoAlturas"
    DROP CONSTRAINT IF EXISTS "OpcionPermisoAlturas_Tipo_check";

ALTER TABLE public."OpcionPermisoAlturas"
    ADD CONSTRAINT "OpcionPermisoAlturas_Tipo_check"
    CHECK ("Tipo" IN (
        'MECANISMO',
        'SISTEMA_INGENIERIA',
        'HERRAMIENTA_MANUAL',
        'SISTEMA_ACCESO',
        'PERMISO_REQUERIDO'
    ));

-- 'PER_NA' (No aplica) no se puede elegir junto con las demás; 'PER_OT' (Otro)
-- exige escribir cuál. La API usa esos códigos para validarlo.
INSERT INTO public."OpcionPermisoAlturas" ("Tipo", "Codigo", "Nombre", "Orden")
VALUES
    ('PERMISO_REQUERIDO', 'PER_01', 'Trabajo en alturas',  1),
    ('PERMISO_REQUERIDO', 'PER_02', 'Energías peligrosas', 2),
    ('PERMISO_REQUERIDO', 'PER_03', 'Espacio confinado',   3),
    ('PERMISO_REQUERIDO', 'PER_04', 'Trabajo en caliente', 4),
    ('PERMISO_REQUERIDO', 'PER_OT', 'Otro',                5),
    ('PERMISO_REQUERIDO', 'PER_NA', 'No aplica',           6)
ON CONFLICT ("Codigo") DO NOTHING;

COMMIT;

-- Reversa (solo si se necesita deshacer; antes, regresar el código):
-- BEGIN;
-- DELETE FROM public."AnalisisTrabajoSeguroOpcion" AO
--     USING public."OpcionPermisoAlturas" O
--     WHERE O."IdOpcionPermisoAlturas" = AO."IdOpcionPermisoAlturas"
--       AND O."Tipo" = 'PERMISO_REQUERIDO';
-- DELETE FROM public."OpcionPermisoAlturas" WHERE "Tipo" = 'PERMISO_REQUERIDO';
-- ALTER TABLE public."OpcionPermisoAlturas"
--     DROP CONSTRAINT "OpcionPermisoAlturas_Tipo_check";
-- ALTER TABLE public."OpcionPermisoAlturas"
--     ADD CONSTRAINT "OpcionPermisoAlturas_Tipo_check"
--     CHECK ("Tipo" IN ('MECANISMO', 'SISTEMA_INGENIERIA', 'HERRAMIENTA_MANUAL', 'SISTEMA_ACCESO'));
-- COMMIT;
