-- Matriz de peligros del análisis de trabajo seguro (bloque 4: asignación
-- de tareas e identificación de peligros).
--
--   * "RiesgoMatrizPeligro": categorías de riesgo (Biológico, Físico, ...).
--   * "MatrizPeligroAlturas": filas de la matriz (peligro, peligro adicional,
--     riesgo asociado y consecuencia asociada), administrables por HSEQ.
--   * "AnalisisTrabajoSeguroTareaPeligro": peligros elegidos en cada tarea.
--     Guarda una copia de los textos de la matriz al momento de elegirlos,
--     para que los análisis diligenciados no cambien si HSEQ corrige la matriz.
--
-- Carga 51 filas (el CSV de HSEQ traía 4 filas de "Trabajo en alturas"
-- casi iguales que se unificaron en una, MP_014).
--
-- Requiere 20261021_analisis_trabajo_seguro.sql.

BEGIN;

CREATE TABLE IF NOT EXISTS public."RiesgoMatrizPeligro" (
    "IdRiesgoMatrizPeligro" serial       PRIMARY KEY,
    "Nombre"                varchar(100) NOT NULL UNIQUE,
    "Orden"                 integer      NOT NULL DEFAULT 0,
    "Activo"                boolean      NOT NULL DEFAULT true,
    "FechaCreacion"         timestamptz  NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS public."MatrizPeligroAlturas" (
    "IdMatrizPeligro"       serial        PRIMARY KEY,
    "IdRiesgoMatrizPeligro" integer       NOT NULL
        REFERENCES public."RiesgoMatrizPeligro"("IdRiesgoMatrizPeligro"),
    "Codigo"                varchar(20)   NOT NULL UNIQUE,
    "Peligro"               varchar(300)  NOT NULL CHECK (btrim("Peligro") <> ''),
    "PeligroAdicional"      varchar(300),
    "RiesgoAsociado"        varchar(1000) NOT NULL CHECK (btrim("RiesgoAsociado") <> ''),
    "ConsecuenciaAsociada"  varchar(1000) NOT NULL CHECK (btrim("ConsecuenciaAsociada") <> ''),
    "Orden"                 integer       NOT NULL DEFAULT 0,
    "Activo"                boolean       NOT NULL DEFAULT true,
    "FechaCreacion"         timestamptz   NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS "IX_MatrizPeligroAlturas_IdRiesgo"
    ON public."MatrizPeligroAlturas" ("IdRiesgoMatrizPeligro");

CREATE TABLE IF NOT EXISTS public."AnalisisTrabajoSeguroTareaPeligro" (
    "IdAnalisisTrabajoSeguroTareaPeligro" bigserial PRIMARY KEY,
    "IdAnalisisTrabajoSeguroTarea" bigint NOT NULL
        REFERENCES public."AnalisisTrabajoSeguroTarea"("IdAnalisisTrabajoSeguroTarea")
        ON DELETE CASCADE,
    "IdMatrizPeligro"       integer       NOT NULL
        REFERENCES public."MatrizPeligroAlturas"("IdMatrizPeligro"),
    -- Copia de los textos de la matriz al momento de elegir el peligro.
    "Riesgo"                varchar(100)  NOT NULL,
    "Peligro"               varchar(300)  NOT NULL,
    "PeligroAdicional"      varchar(300),
    "RiesgoAsociado"        varchar(1000) NOT NULL,
    "ConsecuenciaAsociada"  varchar(1000) NOT NULL,
    "FechaRegistro"         timestamptz   NOT NULL DEFAULT now(),
    -- Un mismo peligro de la matriz no se repite en una tarea.
    CONSTRAINT "UQ_AnalisisTrabajoSeguroTareaPeligro"
        UNIQUE ("IdAnalisisTrabajoSeguroTarea", "IdMatrizPeligro")
);

INSERT INTO public."RiesgoMatrizPeligro" ("Nombre", "Orden") VALUES
    ('BIOLÓGICO', 1),
    ('BIOMECÁNICO', 2),
    ('CONDICIONES DE SEGURIDAD', 3),
    ('FENÓMENOS NATURALES', 4),
    ('FÍSICO', 5),
    ('PSICOSOCIAL', 6),
    ('QUÍMICO', 7)
ON CONFLICT ("Nombre") DO NOTHING;

INSERT INTO public."MatrizPeligroAlturas" (
    "IdRiesgoMatrizPeligro", "Codigo", "Peligro", "PeligroAdicional",
    "RiesgoAsociado", "ConsecuenciaAsociada", "Orden"
)
SELECT R."IdRiesgoMatrizPeligro", V.codigo, V.peligro, V.adicional,
       V.asociado, V.consecuencia, V.orden
FROM (VALUES
    ('BIOLÓGICO', 'MP_001', 'Agentes biológicos', NULL, 'Contacto con heces de animales presentes en paredes y pisos del edificio.', 'Dolor abdominal, dolor de cabeza, irritación cutánea y enfermedades infecciosas.', 1),
    ('BIOLÓGICO', 'MP_002', 'Bacterias', NULL, 'Contacto con ambientes o superficies contaminadas.', 'Intoxicaciones y enfermedades infecciosas.', 2),
    ('BIOLÓGICO', 'MP_003', 'Hongos', NULL, 'Contacto o exposición a hongos.', 'Alergias, irritación cutánea y enfermedades infecciosas, según el agente y la vía de exposición.', 3),
    ('BIOLÓGICO', 'MP_004', 'Mordeduras', NULL, 'Mordedura de animales.', 'Infecciones, envenenamiento o rabia, según la especie y el estado de salud del animal, las características de la lesión y la atención sanitaria recibida.', 4),
    ('BIOLÓGICO', 'MP_005', 'Parásitos', NULL, 'Contacto o exposición a parásitos.', 'Enfermedades como malaria, tripanosomiasis africana, giardiasis, esquistosomiasis y fascioliasis, entre otras.', 5),
    ('BIOLÓGICO', 'MP_006', 'Picaduras', NULL, 'Picaduras de insectos u otros animales.', 'Dengue, malaria y reacciones alérgicas, según el agente causante.', 6),
    ('BIOLÓGICO', 'MP_007', 'Virus', NULL, 'Contacto o exposición a virus.', 'Enfermedades como resfriado común, gripe, varicela y herpes simple; algunos virus pueden causar enfermedades graves.', 7),
    ('BIOMECÁNICO', 'MP_008', 'Movimiento repetitivo', NULL, 'Ejecución repetitiva de movimientos que puede generar lesiones en los tendones.', 'Síndrome del túnel carpiano, tendinitis y tendinosis.', 8),
    ('BIOMECÁNICO', 'MP_009', 'Postura inadecuada', NULL, 'Adopción de una posición corporal inadecuada.', 'Lesiones musculoesqueléticas.', 9),
    ('BIOMECÁNICO', 'MP_010', 'Trabajo con escaleras', NULL, 'Adopción de posturas inadecuadas durante el uso de escaleras.', 'Lesiones musculoesqueléticas asociadas con posturas inadecuadas.', 10),
    ('BIOMECÁNICO', 'MP_011', 'Esfuerzo físico', NULL, 'Sobreesfuerzo físico.', 'Lumbalgia, trastornos por trauma acumulativo, lesiones musculoesqueléticas, fatiga y alteraciones lumbares, dorsales, cervicales, sacras o del sistema vascular.', 11),
    ('BIOMECÁNICO', 'MP_012', 'Manipulación manual de cargas', NULL, 'Manipulación manual de cargas con posibilidad de sobreesfuerzo.', 'Trastornos musculoesqueléticos, fatiga muscular y cansancio.', 12),
    ('BIOMECÁNICO', 'MP_013', 'Posturas prolongadas, mantenidas, forzadas o antigravitacionales', NULL, 'Sobreesfuerzo asociado con posturas prolongadas, mantenidas, forzadas o antigravitacionales.', 'Trastornos musculoesqueléticos, fatiga muscular y cansancio.', 13),
    ('CONDICIONES DE SEGURIDAD', 'MP_014', 'Trabajo en alturas', NULL, 'Caída de personas, objetos, materiales o herramientas desde altura o a distinto nivel.', 'Golpes, heridas, fracturas, lesiones por impacto, traumatismos, politraumatismos, lesiones graves o muerte.', 14),
    ('CONDICIONES DE SEGURIDAD', 'MP_015', 'Accidentes de tránsito', NULL, 'Exposición al tránsito vehicular durante los desplazamientos o la ejecución de actividades.', 'Golpes, traumatismos, fracturas o muerte.', 15),
    ('CONDICIONES DE SEGURIDAD', 'MP_016', 'Riesgo eléctrico (alta y baja tensión y electricidad estática)', NULL, 'Contacto eléctrico directo o indirecto.', 'Electrocución, quemaduras o muerte.', 16),
    ('CONDICIONES DE SEGURIDAD', 'MP_017', 'Espacios confinados', NULL, 'Atrapamiento y exposición a condiciones peligrosas en espacios confinados.', 'Asfixia, sofocación, choque eléctrico, caídas, estrés térmico, atrapamiento, intoxicación por atmósferas peligrosas o muerte.', 17),
    ('CONDICIONES DE SEGURIDAD', 'MP_018', 'Espacios confinados', 'Atmósferas', 'Exposición a atmósferas peligrosas.', 'Desmayos, mareos o asfixia.', 18),
    ('CONDICIONES DE SEGURIDAD', 'MP_019', 'Locativo', 'Caídas de personas', 'Caídas al mismo o a diferente nivel.', 'Golpes, raspaduras y esguinces.', 19),
    ('CONDICIONES DE SEGURIDAD', 'MP_020', 'Locativo', 'Caída de objetos', 'Caída de objetos.', 'Golpes, lesiones en las manos y cortes.', 20),
    ('CONDICIONES DE SEGURIDAD', 'MP_021', 'Locativo', 'Condiciones de orden y aseo', 'Condiciones deficientes de orden y aseo que pueden ocasionar caídas o caída de objetos.', 'Golpes, heridas, contusiones, fracturas, esguinces, luxaciones o muerte.', 21),
    ('CONDICIONES DE SEGURIDAD', 'MP_022', 'Locativo', 'Marquesina', 'Rotura de vidrios en la marquesina.', 'Heridas abiertas, caídas a distinto nivel, fracturas o muerte.', 22),
    ('CONDICIONES DE SEGURIDAD', 'MP_023', 'Locativo', 'Sistemas de almacenamiento', 'Condiciones inseguras de los sistemas y medios de almacenamiento.', 'Caídas al mismo nivel, golpes, hematomas y fracturas.', 23),
    ('CONDICIONES DE SEGURIDAD', 'MP_024', 'Locativo', 'Superficies de trabajo', 'Superficies de trabajo irregulares, deslizantes o con diferencias de nivel.', 'Caídas de personas, hematomas y fracturas.', 24),
    ('CONDICIONES DE SEGURIDAD', 'MP_025', 'Locativo', 'Obstáculos en las zonas de tránsito', 'Tropiezos con obstáculos, con riesgo de caída al mismo o a diferente nivel.', 'Golpes, fracturas, hematomas o muerte.', 25),
    ('CONDICIONES DE SEGURIDAD', 'MP_026', 'Locativo', 'Trabajo con planchones sobre marquesinas', 'Tránsito con planchones sobre la marquesina.', 'Daños a los bienes del cliente, caídas, fracturas, heridas abiertas, síndrome de suspensión en el arnés o muerte.', 26),
    ('CONDICIONES DE SEGURIDAD', 'MP_027', 'Mecánico', 'Herramientas cortopunzantes', 'Manipulación de herramientas cortopunzantes.', 'Heridas abiertas en las manos y cortes en distintas partes del cuerpo.', 27),
    ('CONDICIONES DE SEGURIDAD', 'MP_028', 'Mecánico', 'Partes de máquinas, golpes y cortes', 'Contacto con elementos o partes de máquinas, equipos, herramientas u objetos cortopunzantes.', 'Heridas abiertas, infecciones, aplastamientos, contusiones y hematomas.', 28),
    ('CONDICIONES DE SEGURIDAD', 'MP_029', 'Mecánico', 'Herramientas eléctricas', 'Uso y manipulación de herramientas eléctricas.', 'Amputaciones, cortes y heridas abiertas.', 29),
    ('CONDICIONES DE SEGURIDAD', 'MP_030', 'Mecánico', 'Equipos de protección contra caídas (EPCC)', 'Manipulación de equipos durante la inspección de los equipos de protección contra caídas (EPCC).', 'Golpes, machucones y hematomas.', 30),
    ('CONDICIONES DE SEGURIDAD', 'MP_031', 'Mecánico', 'Proyección de materiales', 'Proyección de materiales sólidos o líquidos.', 'Heridas, traumatismos y contusiones.', 31),
    ('CONDICIONES DE SEGURIDAD', 'MP_032', 'Mecánico', 'Atrapamiento de cuerpo completo', 'Atrapamiento de todo el cuerpo.', 'Ataques de pánico, claustrofobia y retrasos en las actividades; las consecuencias físicas dependerán de las circunstancias del evento.', 32),
    ('CONDICIONES DE SEGURIDAD', 'MP_033', 'Público', NULL, 'Exposición a robos, atracos, asaltos, atentados u otras situaciones de orden público.', 'Traumatismos, heridas, contusiones o muerte.', 33),
    ('CONDICIONES DE SEGURIDAD', 'MP_034', 'Tecnológico', NULL, 'Explosiones, fugas, derrames o incendios.', 'Quemaduras y daños a la infraestructura.', 34),
    ('FENÓMENOS NATURALES', 'MP_035', 'Sismos, terremotos, vendavales y tormentas eléctricas', NULL, 'Exposición a fenómenos naturales.', 'Heridas, daños a la infraestructura o muerte.', 35),
    ('FÍSICO', 'MP_036', 'Iluminación', NULL, 'Exposición a niveles de iluminación inadecuados o a fuentes luminosas intensas.', 'Daño visual, fatiga visual, cefalea, disminución de la destreza y la precisión, estrés y pérdida de capacidad visual.', 36),
    ('FÍSICO', 'MP_037', 'Radiaciones ionizantes (rayos X, gamma, beta y alfa)', NULL, 'Exposición a radiaciones ionizantes.', 'Cáncer y otros efectos sobre la salud, según la dosis y el tiempo de exposición.', 37),
    ('FÍSICO', 'MP_038', 'Radiaciones no ionizantes (láser, ultravioleta, infrarroja, radiofrecuencia y microondas)', NULL, 'Exposición a radiaciones no ionizantes.', 'Alteraciones cutáneas, irritación, deshidratación, insolación, golpe de calor y cáncer de piel, según el tipo y nivel de exposición.', 38),
    ('FÍSICO', 'MP_039', 'Ruido', NULL, 'Exposición a niveles elevados de ruido.', 'Hipoacusia.', 39),
    ('FÍSICO', 'MP_040', 'Vibración (cuerpo entero o segmentaria)', NULL, 'Exposición a vibraciones de cuerpo entero o segmentarias.', 'Trastornos musculoesqueléticos.', 40),
    ('PSICOSOCIAL', 'MP_041', 'Condiciones de la tarea', NULL, 'Demandas de la tarea relacionadas con la carga mental, el contenido, las exigencias emocionales, los sistemas de control, la definición de roles o la monotonía.', 'Estrés laboral y posibles afectaciones fisiológicas, cognitivas y motoras.', 41),
    ('PSICOSOCIAL', 'MP_042', 'Gestión organizacional y características de la organización del trabajo', NULL, 'Factores asociados con la gestión organizacional y la organización del trabajo.', 'Estrés laboral y posibles afectaciones fisiológicas, cognitivas y motoras.', 42),
    ('PSICOSOCIAL', 'MP_043', 'Interfaz persona-tarea', NULL, 'Desajuste entre los conocimientos, las habilidades y las demandas de la tarea, o limitaciones en la iniciativa, autonomía, reconocimiento e identificación con la tarea y la organización.', 'Estrés laboral y posibles afectaciones fisiológicas, cognitivas y motoras.', 43),
    ('QUÍMICO', 'MP_044', 'Aplicación de productos corrosivos', NULL, 'Aplicación y manipulación de productos corrosivos.', 'Quemaduras de primer, segundo o tercer grado.', 44),
    ('QUÍMICO', 'MP_045', 'Gases y vapores en espacios confinados', NULL, 'Exposición a atmósferas peligrosas por presencia de gases o vapores.', 'Intoxicación, asfixia o paro cardíaco.', 45),
    ('QUÍMICO', 'MP_046', 'Salpicaduras de jabón neutro o desengrasante', NULL, 'Salpicaduras durante la manipulación de jabón neutro o desengrasante.', 'Irritación, alergias y enrojecimiento de la piel o los ojos.', 46),
    ('QUÍMICO', 'MP_047', 'Material particulado', NULL, 'Contacto del material particulado con la piel o el sistema respiratorio.', 'Irritación de las vías respiratorias, los ojos y la piel.', 47),
    ('QUÍMICO', 'MP_048', 'Pintura', NULL, 'Aplicación y manipulación de pintura.', 'Irritación pulmonar, dolor de cabeza, mareos y problemas de visión.', 48),
    ('QUÍMICO', 'MP_049', 'Polvos orgánicos e inorgánicos', NULL, 'Exposición a polvo durante la limpieza de vidrios, muebles y estructuras.', 'Problemas respiratorios y alergias; los efectos dependerán del tipo de polvo.', 49),
    ('QUÍMICO', 'MP_050', 'Productos químicos', NULL, 'Manipulación de lavaloza.', 'Alergias e irritación o resequedad de la piel.', 50),
    ('QUÍMICO', 'MP_051', 'Impermeabilizante Sika de 10 años', NULL, 'Exposición a líquidos y vapores inflamables. El producto puede ser mortal si se ingiere y penetra en las vías respiratorias. Mantener alejado del calor y de fuentes de ignición.', 'Lesión pulmonar grave, edema pulmonar y neumonía.', 51)
) AS V (riesgo, codigo, peligro, adicional, asociado, consecuencia, orden)
JOIN public."RiesgoMatrizPeligro" R ON R."Nombre" = V.riesgo
ON CONFLICT ("Codigo") DO NOTHING;

-- Verificación: deben quedar 51 filas en la matriz.
DO $$
BEGIN
    IF (SELECT count(*) FROM public."MatrizPeligroAlturas") < 51 THEN
        RAISE EXCEPTION 'No se cargó completa la matriz de peligros.';
    END IF;
END $$;

COMMIT;

-- Reversa (solo si se necesita deshacer; antes, regresar el código):
-- BEGIN;
-- DROP TABLE IF EXISTS public."AnalisisTrabajoSeguroTareaPeligro";
-- DROP TABLE IF EXISTS public."MatrizPeligroAlturas";
-- DROP TABLE IF EXISTS public."RiesgoMatrizPeligro";
-- COMMIT;
