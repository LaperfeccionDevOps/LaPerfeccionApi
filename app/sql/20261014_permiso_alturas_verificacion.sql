-- 5. Lista de verificación del permiso de trabajo en alturas.
-- Preguntas Sí / No / No aplica cargadas en el catálogo "ItemPermisoAlturas"
-- (creado en 20261013_permiso_alturas_items.sql). Sin campo abierto.

BEGIN;

INSERT INTO public."ItemPermisoAlturas" ("TipoItem", "Codigo", "Texto", "Orden")
VALUES
    ('VERIFICACION', 'VER_01', 'Cuenta con botiquín de primeros auxilios', 1),
    ('VERIFICACION', 'VER_02', 'Se realizó el análisis de trabajo seguro (ATS)', 2),
    ('VERIFICACION', 'VER_03', 'Cuenta con plan de rescate', 3),
    ('VERIFICACION', 'VER_04', 'El personal cumple con los requisitos de aptitud para realizar la tarea', 4),
    ('VERIFICACION', 'VER_05', 'El personal cuenta con el equipo de protección definido para la tarea', 5),
    ('VERIFICACION', 'VER_06', 'El personal cuenta con el equipo definido para acceder al sitio', 6),
    ('VERIFICACION', 'VER_07', 'El equipo para acceder al sitio y el de protección personal fueron inspeccionados', 7),
    ('VERIFICACION', 'VER_08', 'Se verificó que la formación en alturas del personal esté acorde al trabajo a realizar', 8),
    ('VERIFICACION', 'VER_09', 'Se garantiza que las personas que realizarán el diligenciamiento del permiso y las que ejecutarán el trabajo conocen el equipo y los procedimientos contemplados para solicitar un permiso', 9),
    ('VERIFICACION', 'VER_10', 'El área de ejecución de la labor se encuentra limpia, ordenada y es óptima para la ejecución de la tarea', 10),
    ('VERIFICACION', 'VER_11', 'El sitio donde se ejecutará el trabajo está aislado y señalizado completamente', 11),
    ('VERIFICACION', 'VER_12', 'Se controlaron los riesgos presentes en el sitio de trabajo', 12),
    ('VERIFICACION', 'VER_13', 'Se han instalado mamparas para no permitir el paso de vehículos o personas', 13),
    ('VERIFICACION', 'VER_14', 'Las barandas de los andamios cumplen con las especificaciones técnicas', 14),
    ('VERIFICACION', 'VER_15', 'Se realizó el preoperacional de herramientas', 15),
    ('VERIFICACION', 'VER_16', 'Los equipos y herramientas a utilizar en la labor se encuentran en buenas condiciones', 16),
    ('VERIFICACION', 'VER_17', 'Existen puntos de anclaje seguros (certificados, estructurales, autorizados)', 17),
    ('VERIFICACION', 'VER_18', 'Se ha dispuesto de los elementos necesarios para izar y descender la herramienta', 18),
    ('VERIFICACION', 'VER_19', 'El lugar donde se realizará la labor tiene instalada la línea de vida o una estructura donde el trabajador pueda asegurarse', 19),
    ('VERIFICACION', 'VER_20', 'Las escaleras cumplen las especificaciones técnicas', 20),
    ('VERIFICACION', 'VER_21', 'Los andamios se encuentran completos en sus partes y accesorios', 21),
    ('VERIFICACION', 'VER_22', 'Están operando los frenos de las ruedas de los andamios', 22),
    ('VERIFICACION', 'VER_23', 'Los andamios se encuentran asegurados cada tres partes', 23),
    ('VERIFICACION', 'VER_24', 'Las guayas de acero son del calibre definido para el tipo de andamio colgante, se encuentran en buen estado y aseguradas en forma correcta', 24),
    ('VERIFICACION', 'VER_25', 'Cuentan con frenos de seguridad certificados y apropiados para el tipo de línea de vida', 25),
    ('VERIFICACION', 'VER_26', 'Cuenta con eslinga de seguridad con absorbente de caídas', 26),
    ('VERIFICACION', 'VER_27', 'Se cuenta con líneas de vida para cada uno de los operarios', 27),
    ('VERIFICACION', 'VER_28', 'Los conectores o mosquetones son de doble seguro', 28),
    ('VERIFICACION', 'VER_29', 'Las cuerdas se encuentran libres de nudos', 29),
    ('VERIFICACION', 'VER_30', 'Cuenta con hoja de vida de los equipos', 30),
    ('VERIFICACION', 'VER_31', 'Si va a utilizar sustancias químicas, cuenta con los controles para su manipulación', 31),
    ('VERIFICACION', 'VER_32', 'Se han consultado otros permisos y se cumple con los requerimientos de estos', 32),
    ('VERIFICACION', 'VER_33', 'Todos los trabajadores autorizados conocen las medidas de precaución establecidas en la evaluación de riesgos', 33),
    ('VERIFICACION', 'VER_34', 'Está presente una persona para que active el plan de emergencias en caso de ser necesario', 34),
    ('VERIFICACION', 'VER_35', 'El personal que va a realizar la labor conoce el procedimiento de emergencias y rescate', 35),
    ('VERIFICACION', 'VER_36', 'Se requiere suspender actividades en condiciones ambientales con lluvia', 36)
ON CONFLICT ("Codigo") DO NOTHING;

COMMIT;

-- Reversa (solo si se necesita deshacer; borra también las respuestas dadas):
-- DELETE FROM public."PermisoTrabajoAlturasRespuesta"
--  WHERE "IdItemPermisoAlturas" IN (
--      SELECT "IdItemPermisoAlturas" FROM public."ItemPermisoAlturas"
--       WHERE "TipoItem" = 'VERIFICACION');
-- DELETE FROM public."ItemPermisoAlturas" WHERE "TipoItem" = 'VERIFICACION';
