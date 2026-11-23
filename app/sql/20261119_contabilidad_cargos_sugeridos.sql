-- =============================================================================
-- Contabilidad > Asignar operarios: cargos sugeridos por línea y servicio
-- Fecha: 2026-11-19
--
-- Reglas validadas con Contabilidad:
--   * Cada combinación CEN4 (línea de negocio) + CEN5 (servicio asociado) tiene
--     los cargos que normalmente se le asignan (p. ej. 01ASGE + 0101ASE:
--     OPERARIO(A) ASEO y SUPERVISORA). Al asignar operarios, el selector de
--     cargo muestra primero esos (nombres exactos de la tabla Cargo: OPERARIO(A) DE ASEO, SUPERVISOR (A)) y deja ver todos los cargos activos.
--   * Se puede elegir cualquier cargo activo, sin aviso. Al guardar la
--     asignación, cada cargo usado queda registrado en su combinación (si es
--     nuevo, se agrega como sugerido para la próxima vez). Nadie edita la tabla
--     a mano: arranca con la lista inicial de Contabilidad y se va alimentando.
--   * Los de la lista inicial se sugieren siempre. Los aprendidos solo mientras
--     algún centro ABIERTO de la combinación los tenga en su asignación
--     vigente: si se asignó un cargo por error, al corregir (o finalizar) la
--     asignación deja de sugerirse. La fila se conserva como historial.
--   * Una combinación sin cargos registrados muestra todos los cargos.
--
-- Se ejecuta después de 20261112_contabilidad_dedicacion.sql.
-- Se puede ejecutar más de una vez.
-- =============================================================================

BEGIN;

CREATE TABLE IF NOT EXISTS public."CargoSugeridoLineaServicio" (
    "IdCargoSugeridoLineaServicio" integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    "IdLineaNegocio"     integer NOT NULL REFERENCES public."LineaNegocio" ("IdLineaNegocio"),
    "IdServicioAsociado" integer NOT NULL REFERENCES public."ServicioAsociado" ("IdServicioAsociado"),
    "IdCargo"            integer NOT NULL REFERENCES public."Cargo" ("IdCargo"),
    -- LISTA_INICIAL (carga de Contabilidad) o ASIGNACION (aprendido al guardar).
    "Origen"             varchar(20) NOT NULL DEFAULT 'ASIGNACION',
    -- Veces que se guardó una asignación con este cargo en la combinación.
    "VecesAsignado"      integer NOT NULL DEFAULT 0,
    "FechaUltimaAsignacion" timestamp NULL,
    "FechaCreacion"      timestamp NOT NULL DEFAULT now(),
    "CreadoPor"          varchar(150) NULL,
    CONSTRAINT "UQ_CargoSugerido_LineaServicioCargo" UNIQUE ("IdLineaNegocio", "IdServicioAsociado", "IdCargo"),
    CONSTRAINT "CK_CargoSugerido_Origen" CHECK ("Origen" IN ('LISTA_INICIAL', 'ASIGNACION'))
);

COMMENT ON TABLE public."CargoSugeridoLineaServicio" IS
    'Cargos que se sugieren al asignar operarios según la combinación CEN4 + CEN5; se alimenta sola con cada asignación guardada.';

-- ─────────────────────────────────────────────────────────────────────────────
-- Lista inicial de Contabilidad (precargue preliminar del 2026-11-19:
-- 34 cargos en 15 combinaciones), por códigos y nombre exacto del cargo.
-- Agregar una fila por cargo en cada combinación:  ('CEN4', 'CEN5', 'CARGO').
-- Los cargos o códigos que no existan se ignoran (revisar la consulta final).
-- ─────────────────────────────────────────────────────────────────────────────
INSERT INTO public."CargoSugeridoLineaServicio"
    ("IdLineaNegocio", "IdServicioAsociado", "IdCargo", "Origen", "CreadoPor")
SELECT L."IdLineaNegocio", SA."IdServicioAsociado", C."IdCargo", 'LISTA_INICIAL', 'CARGA INICIAL'
FROM (VALUES
    ('01ASGE', '0101ASE', 'OPERARIO(A) DE ASEO'),
    ('01ASGE', '0101ASE', 'SUPERVISOR (A)'),
    ('06MPIS', '0101ASE', 'OPERARIO(A) DE ASEO'),
    ('01ASGE', '0101ASE', 'SUPERVISOR (A) JUNIOR'),
    ('01ASGE', '0101ASE', 'JARDINERO'),
    ('01ASGE', '0102CAF', 'OPERARIO(A) DE ASEO'),
    ('02MLOC', '0103JAR', 'JARDINERO'),
    ('01ASGE', '0103JAR', 'JARDINERO'),
    ('01ASGE', '0104LAV', 'OPERARIO(A) DE ASEO'),
    ('01ASGE', '0105REC', 'OPERARIO(A) DE ASEO'),
    ('01ASGE', '0105REC', 'SUPERVISOR (A)'),
    ('01ASGE', '0105REC', 'STEWARD'),
    ('01ASGE', '0106SAL', 'OPERARIO(A) DE ASEO'),
    ('01ASGE', '0106SAL', 'SUPERVISOR (A)'),
    ('02MLOC', '0203OCM', 'TODERO I'),
    ('02MLOC', '0203OCM', 'JARDINERO'),
    ('02MLOC', '0204MGE', 'TODERO II'),
    ('02MLOC', '0204MGE', 'TODERO III'),
    ('02MLOC', '0204MGE', 'JARDINERO'),
    ('05SADM', '0501ADM', 'COORDINADOR MANTENIMIENTO II'),
    ('05SADM', '0501ADM', 'COORDINADOR MANTENIMIENTO'),
    ('05SADM', '0501ADM', 'SUPERVISOR (A) MANTENIMIENTO II'),
    ('05SADM', '0501ADM', 'DIBUJANTE ARQUITECTONICO'),
    ('05SADM', '0501ADM', 'SUPERVISOR (A) MANTENIMIENTO I'),
    ('05SADM', '0501ADM', 'TECNOLOGO(A) ADMINISTRATIVO'),
    ('05SADM', '0501ADM', 'TECNOLOGO MANTENIMIENTO'),
    ('05SADM', '0501ADM', 'AUXILIAR ADMINISTRATIVO'),
    ('06MPIS', '0601PISC', 'PISCINERO'),
    ('06MPIS', '0601PISC', 'TODERO II'),
    ('11ASALT', '0802LIVI', 'COORDINADOR(A) ALTURAS'),
    ('11ASALT', '0802LIVI', 'OPERARIO(A) DE ALTURAS'),
    ('01ASGE', '1003APO', 'OPERARIO(A) DE ASEO'),
    ('02MLOC', '1003APO', 'TODERO II'),
    ('02MLOC', '1003APO', 'OPERARIO(A) DE ALTURAS')
) AS V (cen4, cen5, cargo)
JOIN public."LineaNegocio" L      ON upper(L."Codigo") = upper(V.cen4)
JOIN public."ServicioAsociado" SA ON upper(SA."Codigo") = upper(V.cen5)
JOIN public."Cargo" C             ON upper(btrim(C."NombreCargo")) = upper(btrim(V.cargo))
ON CONFLICT ("IdLineaNegocio", "IdServicioAsociado", "IdCargo") DO NOTHING;

COMMIT;

-- Revisión: combinaciones cargadas.
-- SELECT L."Codigo" AS cen4, SA."Codigo" AS cen5, btrim(C."NombreCargo") AS cargo, S."Origen", S."VecesAsignado"
-- FROM public."CargoSugeridoLineaServicio" S
-- JOIN public."LineaNegocio" L USING ("IdLineaNegocio")
-- JOIN public."ServicioAsociado" SA USING ("IdServicioAsociado")
-- JOIN public."Cargo" C USING ("IdCargo")
-- ORDER BY 1, 2, 3;

-- Reversa:
-- DROP TABLE IF EXISTS public."CargoSugeridoLineaServicio";
