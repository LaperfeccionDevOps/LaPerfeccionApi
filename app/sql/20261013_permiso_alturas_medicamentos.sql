-- Medicamentos de cada trabajador del permiso de trabajo en alturas.
-- "ConsumeMedicamentos" pasa a ser la pregunta: ¿consume actualmente algún
-- medicamento que deba ser informado para realizar el trabajo en alturas?
-- Si es SI se pregunta por presión arterial y por somnolencia:
--   * somnolencia SI          -> se indica cuál medicamento.
--   * presión NO y somnolencia NO -> se indica qué otro medicamento consume.
-- Si es NO, ambas quedan en NO.
--
-- "CualesMedicamentos" (pregunta anterior) deja de diligenciarse; se conserva
-- solo como dato histórico de los registros anteriores a este cambio.
-- Las columnas nuevas admiten NULL solo por esos registros anteriores; el
-- backend las exige para los registros nuevos.

BEGIN;

-- La regla anterior exigía "CualesMedicamentos" siempre que se respondía SI.
ALTER TABLE public."PermisoTrabajoAlturasTrabajador"
    DROP CONSTRAINT IF EXISTS "CK_PermisoAlturasTrabajador_Medicamentos";

ALTER TABLE public."PermisoTrabajoAlturasTrabajador"
    ADD COLUMN IF NOT EXISTS "MedicamentosPresionArterial" boolean,
    ADD COLUMN IF NOT EXISTS "MedicamentosSomnolencia"     boolean,
    ADD COLUMN IF NOT EXISTS "CualMedicamentoSomnolencia"  varchar(300),
    ADD COLUMN IF NOT EXISTS "OtroMedicamento"             varchar(300);

-- Si no consume medicamentos, ninguna subpregunta puede ser SI.
ALTER TABLE public."PermisoTrabajoAlturasTrabajador"
    ADD CONSTRAINT "CK_PermisoAlturasTrabajador_MedicamentosSub"
    CHECK (
        "ConsumeMedicamentos"
        OR NOT (
            COALESCE("MedicamentosPresionArterial", FALSE)
            OR COALESCE("MedicamentosSomnolencia", FALSE)
        )
    );

-- Si toma medicamentos que causan somnolencia, debe indicar cuál.
ALTER TABLE public."PermisoTrabajoAlturasTrabajador"
    ADD CONSTRAINT "CK_PermisoAlturasTrabajador_MedicamentoSomnolencia"
    CHECK (
        NOT COALESCE("MedicamentosSomnolencia", FALSE)
        OR NULLIF(TRIM("CualMedicamentoSomnolencia"), '') IS NOT NULL
    );

-- Si consume medicamentos pero ninguno de los dos tipos preguntados, debe
-- indicar cuál. (Los registros anteriores tienen las subpreguntas en NULL y
-- no se ven afectados.)
ALTER TABLE public."PermisoTrabajoAlturasTrabajador"
    ADD CONSTRAINT "CK_PermisoAlturasTrabajador_OtroMedicamento"
    CHECK (
        NOT (
            COALESCE("ConsumeMedicamentos", FALSE)
            AND "MedicamentosPresionArterial" IS FALSE
            AND "MedicamentosSomnolencia" IS FALSE
        )
        OR NULLIF(TRIM("OtroMedicamento"), '') IS NOT NULL
    );

COMMIT;

-- Reversa (solo si se necesita deshacer):
-- ALTER TABLE public."PermisoTrabajoAlturasTrabajador" DROP CONSTRAINT IF EXISTS "CK_PermisoAlturasTrabajador_OtroMedicamento";
-- ALTER TABLE public."PermisoTrabajoAlturasTrabajador" DROP CONSTRAINT IF EXISTS "CK_PermisoAlturasTrabajador_MedicamentoSomnolencia";
-- ALTER TABLE public."PermisoTrabajoAlturasTrabajador" DROP CONSTRAINT IF EXISTS "CK_PermisoAlturasTrabajador_MedicamentosSub";
-- ALTER TABLE public."PermisoTrabajoAlturasTrabajador"
--     DROP COLUMN IF EXISTS "MedicamentosPresionArterial",
--     DROP COLUMN IF EXISTS "MedicamentosSomnolencia",
--     DROP COLUMN IF EXISTS "CualMedicamentoSomnolencia",
--     DROP COLUMN IF EXISTS "OtroMedicamento";
-- ALTER TABLE public."PermisoTrabajoAlturasTrabajador"
--     ADD CONSTRAINT "CK_PermisoAlturasTrabajador_Medicamentos"
--     CHECK (NOT "ConsumeMedicamentos" OR "CualesMedicamentos" IS NOT NULL);
