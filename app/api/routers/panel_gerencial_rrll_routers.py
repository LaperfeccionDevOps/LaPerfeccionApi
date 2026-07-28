import logging
from datetime import date, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from infrastructure.db.deps import get_db

logger = logging.getLogger(__name__)


router = APIRouter(
    prefix="/api/panel-gerencial-rrll",
    tags=["Panel Gerencial RRLL"],
)


def calcular_rango_periodo(
    periodo: str,
    fecha_inicial: Optional[date],
    fecha_final: Optional[date],
) -> tuple[date, date]:
    """
    Calcula el rango de fechas según el periodo seleccionado en el frontend.
    """

    hoy = date.today()
    periodo_normalizado = (periodo or "mes").strip().lower()

    if periodo_normalizado == "hoy":
        return hoy, hoy

    if periodo_normalizado == "semana":
        inicio = hoy - timedelta(days=hoy.weekday())
        return inicio, hoy

    if periodo_normalizado == "mes":
        return hoy.replace(day=1), hoy

    if periodo_normalizado == "anio":
        return hoy.replace(month=1, day=1), hoy

    if periodo_normalizado in {"todos", "historico", "global"}:
        return date(1900, 1, 1), hoy

    if periodo_normalizado == "personalizado":
        if not fecha_inicial or not fecha_final:
            raise HTTPException(
                status_code=400,
                detail=(
                    "Debe enviar fechaInicial y fechaFinal "
                    "para el periodo personalizado."
                ),
            )

        if fecha_inicial > fecha_final:
            raise HTTPException(
                status_code=400,
                detail="La fecha inicial no puede ser mayor que la fecha final.",
            )

        return fecha_inicial, fecha_final

    raise HTTPException(
        status_code=400,
        detail="Periodo de consulta no válido.",
    )


def normalizar_filtro_motivo(motivo: Optional[str]) -> Optional[str]:
    """
    Convierte los valores enviados por el frontend en textos que pueden
    compararse con el nombre real almacenado en MotivoRetiro.
    """

    if not motivo:
        return None

    valor = motivo.strip().lower()

    if not valor or valor == "todos":
        return None

    equivalencias = {
        "rotacion-voluntaria": "retiro volunt",
        "renuncia-voluntaria": "voluntaria",
        "abandono": "abandono",
        "terminacion": "terminaci",
        "nunca-ingreso": "nunca ingres",
    }

    return equivalencias.get(valor, valor.replace("-", " "))


def normalizar_filtro_sede(sede: Optional[str]) -> Optional[str]:
    """
    Convierte el valor seleccionado en el frontend en un texto comparable
    con Cliente.Nombre.
    """

    if not sede:
        return None

    valor = sede.strip().lower()

    if not valor or valor == "todas":
        return None

    # Conserva los guiones que forman parte del nombre real de la sede,
    # por ejemplo: "53C-50". Solo normaliza espacios internos.
    return " ".join(valor.split())


def convertir_decimal(valor, valor_defecto: float = 0.0) -> float:
    """
    Convierte Decimal, int, float o None a float para responder en JSON.
    """

    if valor is None:
        return valor_defecto

    try:
        return float(valor)
    except (TypeError, ValueError):
        return valor_defecto


def texto_retiros(cantidad: int) -> str:
    """
    Devuelve la cantidad de retiros con singular o plural correcto.
    """

    return "1 retiro" if cantidad == 1 else f"{cantidad} retiros"


def texto_casos(cantidad: int) -> str:
    """
    Devuelve la cantidad de casos con singular o plural correcto.
    """

    return "1 caso" if cantidad == 1 else f"{cantidad} casos"


def texto_registros(cantidad: int) -> str:
    """
    Devuelve la cantidad de registros con singular o plural correcto.
    """

    return "1 registro" if cantidad == 1 else f"{cantidad} registros"


def verbo_corresponder(cantidad: int) -> str:
    """
    Devuelve el verbo corresponder en singular o plural.
    """

    return "corresponde" if cantidad == 1 else "corresponden"


def texto_equivalencia(cantidad: int) -> str:
    """
    Devuelve equivalente o equivalentes según la cantidad.
    """

    return "equivalente" if cantidad == 1 else "equivalentes"


@router.get("/buscar-trabajadores")
def buscar_trabajadores_panel_rrll(
    busqueda: str = Query(
        ...,
        min_length=2,
        max_length=120,
        description="Nombre, apellido o número de identificación.",
    ),
    limite: int = Query(
        default=10,
        ge=1,
        le=20,
        description="Cantidad máxima de trabajadores a retornar.",
    ),
    db: Session = Depends(get_db),
):
    """
    Busca trabajadores por nombre, apellido o número de identificación.

    El resultado solo incluye personas que tienen por lo menos un registro
    en RetiroLaboral, porque son las que pueden consultarse en este panel.
    El frontend muestra nombre e identificación, pero conserva internamente
    el IdRegistroPersonal para enviarlo al endpoint principal.
    """

    texto_busqueda = " ".join((busqueda or "").strip().split())

    if len(texto_busqueda) < 2:
        raise HTTPException(
            status_code=400,
            detail="Ingrese al menos 2 caracteres para buscar al trabajador.",
        )

    numero_busqueda = "".join(
        caracter
        for caracter in texto_busqueda
        if caracter.isdigit()
    )

    query_busqueda = text(
        """
        SELECT
            rp."IdRegistroPersonal" AS "idRegistroPersonal",

            BTRIM(
                REGEXP_REPLACE(
                    COALESCE(rp."Nombres", '') || ' ' ||
                    COALESCE(rp."Apellidos", ''),
                    '[[:space:]]+',
                    ' ',
                    'g'
                )
            ) AS "nombreCompleto",

            BTRIM(
                COALESCE(rp."NumeroIdentificacion", '')
            ) AS "numeroIdentificacion"

        FROM public."RegistroPersonal" rp

        WHERE EXISTS (
            SELECT 1
            FROM public."RetiroLaboral" rl
            WHERE rl."IdRegistroPersonal" = rp."IdRegistroPersonal"
        )

        AND (
            (
                :numero_busqueda <> ''
                AND REGEXP_REPLACE(
                    COALESCE(rp."NumeroIdentificacion", ''),
                    '[^0-9]',
                    '',
                    'g'
                ) LIKE '%' || :numero_busqueda || '%'
            )

            OR UPPER(
                BTRIM(
                    REGEXP_REPLACE(
                        COALESCE(rp."Nombres", ''),
                        '[[:space:]]+',
                        ' ',
                        'g'
                    )
                )
            ) LIKE '%' || UPPER(:texto_busqueda) || '%'

            OR UPPER(
                BTRIM(
                    REGEXP_REPLACE(
                        COALESCE(rp."Apellidos", ''),
                        '[[:space:]]+',
                        ' ',
                        'g'
                    )
                )
            ) LIKE '%' || UPPER(:texto_busqueda) || '%'

            OR UPPER(
                BTRIM(
                    REGEXP_REPLACE(
                        COALESCE(rp."Nombres", '') || ' ' ||
                        COALESCE(rp."Apellidos", ''),
                        '[[:space:]]+',
                        ' ',
                        'g'
                    )
                )
            ) LIKE '%' || UPPER(:texto_busqueda) || '%'
        )

        ORDER BY
            CASE
                WHEN REGEXP_REPLACE(
                    COALESCE(rp."NumeroIdentificacion", ''),
                    '[^0-9]',
                    '',
                    'g'
                ) = :numero_busqueda
                AND :numero_busqueda <> ''
                THEN 0
                ELSE 1
            END,
            "nombreCompleto" ASC,
            rp."IdRegistroPersonal" DESC

        LIMIT :limite;
        """
    )

    try:
        filas = db.execute(
            query_busqueda,
            {
                "texto_busqueda": texto_busqueda,
                "numero_busqueda": numero_busqueda,
                "limite": limite,
            },
        ).mappings().all()

        resultados = [
            {
                "idRegistroPersonal": int(fila["idRegistroPersonal"]),
                "nombreCompleto": fila["nombreCompleto"],
                "numeroIdentificacion": fila["numeroIdentificacion"],
                "textoMostrar": (
                    f'{fila["nombreCompleto"]} - '
                    f'CC {fila["numeroIdentificacion"]}'
                ),
            }
            for fila in filas
        ]

        return {
            "ok": True,
            "mensaje": (
                "Trabajadores encontrados correctamente."
                if resultados
                else "No se encontraron trabajadores con la búsqueda realizada."
            ),
            "total": len(resultados),
            "resultados": resultados,
        }

    except SQLAlchemyError as error:
        db.rollback()

        logger.exception(
            "Error de base de datos buscando trabajadores para el Panel "
            "Gerencial RRLL."
        )

        raise HTTPException(
            status_code=500,
            detail=(
                "No fue posible buscar trabajadores para el "
                "Panel Gerencial RRLL."
            ),
        ) from error

    except Exception as error:
        db.rollback()

        logger.exception(
            "Error inesperado buscando trabajadores para el Panel "
            "Gerencial RRLL."
        )

        raise HTTPException(
            status_code=500,
            detail=(
                "Ocurrió un error inesperado buscando trabajadores para el "
                "Panel Gerencial RRLL."
            ),
        ) from error


@router.get("")
def obtener_panel_gerencial_rrll(
    periodo: str = Query(default="mes"),
    fecha_inicial: Optional[date] = Query(
        default=None,
        alias="fechaInicial",
    ),
    fecha_final: Optional[date] = Query(
        default=None,
        alias="fechaFinal",
    ),
    sede: Optional[str] = Query(default=None),
    motivo: Optional[str] = Query(default=None),
    id_registro_personal: Optional[int] = Query(
        default=None,
        alias="idRegistroPersonal",
        ge=1,
    ),
    db: Session = Depends(get_db),
):
    """
    Panel Gerencial de Relaciones Laborales.

    Indicadores del Panel Gerencial de Relaciones Laborales:

    - Rotación total, entendida como cantidad de retiros del periodo.
    - Rotación voluntaria.
    - Terminaciones.
    - Nunca ingreso.
    - Abandonos.
    - Motivos y tipificaciones del retiro.
    - Tiempo promedio laborado.
    - Tiempo promedio de desvinculación.
    - Sede con mayor rotación.
    - Pendientes actuales en RRLL.

    Todos los indicadores del periodo pueden filtrarse por sede, motivo
    y persona. Los pendientes en RRLL se mantienen como fotografía actual.
    """

    try:
        inicio, fin = calcular_rango_periodo(
            periodo=periodo,
            fecha_inicial=fecha_inicial,
            fecha_final=fecha_final,
        )

        fecha_fin_exclusiva = fin + timedelta(days=1)

        filtro_sede = normalizar_filtro_sede(sede)
        filtro_motivo = normalizar_filtro_motivo(motivo)

        parametros = {
            "fecha_inicio": inicio,
            "fecha_fin_exclusiva": fecha_fin_exclusiva,
            "fecha_corte": min(fin, date.today()),
            "filtro_sede": filtro_sede,
            "filtro_motivo": filtro_motivo,
            "id_registro_personal": id_registro_personal,
        }

        filtros_comunes = """
            AND (
                :id_registro_personal IS NULL
                OR rl."IdRegistroPersonal" = :id_registro_personal
            )

            AND (
                :filtro_sede IS NULL
                OR UPPER(
                    BTRIM(
                        REGEXP_REPLACE(
                            BTRIM(
                                COALESCE(c."Nombre", '')
                            ),
                            '[[:space:]]+',
                            ' ',
                            'g'
                        )
                    )
                ) LIKE '%' || UPPER(:filtro_sede) || '%'
            )

            AND (
                :filtro_motivo IS NULL
                OR UPPER(
                    BTRIM(
                        REGEXP_REPLACE(
                            BTRIM(
                                COALESCE(mr."Nombre", '')
                            ),
                            '[[:space:]]+',
                            ' ',
                            'g'
                        )
                    )
                ) LIKE '%' || UPPER(:filtro_motivo) || '%'
            )
        """

        cte_retiros_periodo = f"""
            WITH base_retiros AS (
                SELECT
                    rl."IdRetiroLaboral",
                    rl."IdRegistroPersonal",
                    rl."IdCliente",
                    rl."IdMotivoRetiro",
                    rl."IdTipificacionRetiro",
                    rl."FechaProceso",
                    rl."FechaRetiro",
                    rl."FechaCierre",
                    rl."FechaCreacion",
                    rl."FechaActualizacion",

                    COALESCE(
                        hl.ultima_fecha_ingreso_historial,
                        rc.ultima_fecha_ingreso_registro,
                        cb.ultima_fecha_ingreso_basica,
                        rp."FechaIngresoHistorica"
                    ) AS fecha_ingreso_seleccionada,

                    UPPER(
                        TRIM(
                             COALESCE(
                                rl."EstadoCasoRRLL",
                                'SIN ESTADO'
                            )
                        )
                    ) AS estado_rrll,

                   COALESCE(
                        NULLIF(
                            UPPER(
                                BTRIM(
                                    REGEXP_REPLACE(
                                        BTRIM(c."Nombre"),
                                        '[[:space:]]+',
                                        ' ',
                                        'g'
                                    )
                                )
                            ),
                            ''
                        ),
                        'SIN SEDE REGISTRADA'
                    ) AS sede,

                    COALESCE(
                        NULLIF(
                            UPPER(
                                BTRIM(
                                    REGEXP_REPLACE(
                                        BTRIM(mr."Nombre"),
                                        '[[:space:]]+',
                                        ' ',
                                        'g'
                                    )
                                )
                            ),
                            ''
                        ),
                        'SIN MOTIVO REGISTRADO'
                    ) AS motivo,

                    COALESCE(
                        NULLIF(
                            UPPER(
                                BTRIM(
                                    REGEXP_REPLACE(
                                        BTRIM(tr."Nombre"),
                                        '[[:space:]]+',
                                        ' ',
                                        'g'
                                    )
                                )
                            ),
                            ''
                        ),
                        'SIN CLASIFICACIÓN'
                    ) AS clasificacion

                FROM public."RetiroLaboral" rl

                LEFT JOIN public."Cliente" c
                    ON c."IdCliente" = rl."IdCliente"

                LEFT JOIN public."MotivoRetiro" mr
                    ON mr."IdMotivoRetiro" = rl."IdMotivoRetiro"

                LEFT JOIN public."TipificacionRetiro" tr
                    ON tr."IdTipificacionRetiro"
                       = rl."IdTipificacionRetiro"

                LEFT JOIN public."RegistroPersonal" rp
                    ON rp."IdRegistroPersonal" = rl."IdRegistroPersonal"

                LEFT JOIN LATERAL (
                    SELECT
                        MAX(hl2."FechaIngreso")
                            AS ultima_fecha_ingreso_historial
                    FROM public."HistorialLaboral" hl2
                    WHERE hl2."IdRegistroPersonal"
                          = rl."IdRegistroPersonal"
                      AND (
                            rl."FechaRetiro" IS NULL
                            OR hl2."FechaIngreso" <= rl."FechaRetiro"
                          )
                ) hl ON TRUE

                LEFT JOIN LATERAL (
                    SELECT
                        MAX(rc2."FechaIngreso")
                            AS ultima_fecha_ingreso_registro
                    FROM public."RegistroContratacion" rc2
                    WHERE rc2."IdRegistroPersonal"
                          = rl."IdRegistroPersonal"
                      AND (
                            rl."FechaRetiro" IS NULL
                            OR rc2."FechaIngreso" <= rl."FechaRetiro"
                          )
                ) rc ON TRUE

                LEFT JOIN LATERAL (
                    SELECT
                        MAX(cb2."FechaIngreso")
                            AS ultima_fecha_ingreso_basica
                    FROM public."ContratacionBasica" cb2
                    WHERE cb2."IdRegistroPersonal"
                          = rl."IdRegistroPersonal"
                      AND (
                            rl."FechaRetiro" IS NULL
                            OR cb2."FechaIngreso" <= rl."FechaRetiro"
                          )
                ) cb ON TRUE

             WHERE rl."FechaProceso" IS NOT NULL

                    AND rl."FechaProceso" >= :fecha_inicio

                    AND rl."FechaProceso" < :fecha_fin_exclusiva

                  {filtros_comunes}
            )
        """

        query_total_retiros = text(
            cte_retiros_periodo
            + """
            SELECT
                COUNT(*)::int AS total_retiros
            FROM base_retiros;
            """
        )

        query_indicadores_rotacion = text(
            cte_retiros_periodo
            + """
            SELECT
                COUNT(*)::int AS rotacion_total,

                COUNT(*) FILTER (
                    WHERE motivo LIKE '%VOLUNTAR%'
                )::int AS rotacion_voluntaria,

                COUNT(*) FILTER (
                    WHERE motivo LIKE '%ABANDONO%'
                )::int AS abandonos,

                COUNT(*) FILTER (
                    WHERE motivo LIKE '%NUNCA%INGRES%'
                )::int AS nunca_ingreso,

                COUNT(*) FILTER (
                    WHERE motivo LIKE '%TERMINA%'
                      AND motivo NOT LIKE '%ABANDONO%'
                      AND motivo NOT LIKE '%NUNCA%INGRES%'
                )::int AS terminaciones

            FROM base_retiros;
            """
        )

        query_tiempo_laborado = text(
            cte_retiros_periodo
            + """
            SELECT
                ROUND(
                    AVG(
                        ("FechaRetiro" - fecha_ingreso_seleccionada)
                    ) FILTER (
                        WHERE fecha_ingreso_seleccionada IS NOT NULL
                          AND "FechaRetiro" IS NOT NULL
                          AND "FechaRetiro" >= fecha_ingreso_seleccionada
                          AND "FechaRetiro" <= :fecha_corte
                    )::numeric,
                    2
                ) AS promedio_dias,

                COUNT(*) FILTER (
                    WHERE fecha_ingreso_seleccionada IS NOT NULL
                      AND "FechaRetiro" IS NOT NULL
                      AND "FechaRetiro" >= fecha_ingreso_seleccionada
                      AND "FechaRetiro" <= :fecha_corte
                )::int AS registros_validos,

                COUNT(*) FILTER (
                    WHERE fecha_ingreso_seleccionada IS NULL
                )::int AS registros_sin_fecha_ingreso,

                COUNT(*) FILTER (
                    WHERE "FechaRetiro" IS NULL
                )::int AS registros_sin_fecha_retiro,

                COUNT(*) FILTER (
                    WHERE fecha_ingreso_seleccionada IS NOT NULL
                      AND "FechaRetiro" IS NOT NULL
                      AND "FechaRetiro" < fecha_ingreso_seleccionada
                )::int AS registros_fecha_inconsistente,

                COUNT(*) FILTER (
                    WHERE "FechaRetiro" IS NOT NULL
                      AND "FechaRetiro" > :fecha_corte
                )::int AS registros_retiro_futuro

            FROM base_retiros;
            """
        )

        query_clasificacion = text(
            cte_retiros_periodo
            + """
            SELECT
                clasificacion AS nombre,
                COUNT(*)::int AS cantidad,

                ROUND(
                    COUNT(*) * 100.0
                    /
                    NULLIF(
                        SUM(COUNT(*)) OVER (),
                        0
                    ),
                    2
                ) AS porcentaje

            FROM base_retiros

            GROUP BY clasificacion

            ORDER BY
                cantidad DESC,
                clasificacion ASC;
            """
        )

        query_motivos = text(
            cte_retiros_periodo
            + """
            SELECT
                motivo AS nombre,
                COUNT(*)::int AS cantidad,

                ROUND(
                    COUNT(*) * 100.0
                    /
                    NULLIF(
                        SUM(COUNT(*)) OVER (),
                        0
                    ),
                    2
                ) AS porcentaje

            FROM base_retiros

            GROUP BY motivo

            ORDER BY
                cantidad DESC,
                motivo ASC;
            """
        )

        query_sedes = text(
            cte_retiros_periodo
            + """
            SELECT
                sede AS nombre,
                COUNT(*)::int AS cantidad,

                ROUND(
                    COUNT(*) * 100.0
                    /
                    NULLIF(
                        SUM(COUNT(*)) OVER (),
                        0
                    ),
                    2
                ) AS porcentaje

            FROM base_retiros

            GROUP BY sede

            ORDER BY
                cantidad DESC,
                sede ASC;
            """
        )

        query_tiempo_desvinculacion = text(
            cte_retiros_periodo
            + """
            SELECT
                ROUND(
                    AVG(
                        EXTRACT(
                            EPOCH FROM (
                                "FechaCierre" - "FechaProceso"
                            )
                        ) / 86400.0
                    ) FILTER (
                        WHERE "FechaProceso" IS NOT NULL
                          AND "FechaCierre" IS NOT NULL
                          AND "FechaCierre" >= "FechaProceso"
                          AND estado_rrll IN (
                              'ENVIADO_NOMINA',
                              'CERRADO'
                          )
                    )::numeric,
                    2
                ) AS promedio_dias,

                COUNT(*) FILTER (
                    WHERE "FechaProceso" IS NOT NULL
                      AND "FechaCierre" IS NOT NULL
                      AND "FechaCierre" >= "FechaProceso"
                      AND estado_rrll IN (
                          'ENVIADO_NOMINA',
                          'CERRADO'
                      )
                )::int AS registros_validos,

                COUNT(*) FILTER (
                    WHERE "FechaProceso" IS NOT NULL
                      AND "FechaCierre" IS NOT NULL
                      AND "FechaCierre" < "FechaProceso"
                      AND estado_rrll IN (
                          'ENVIADO_NOMINA',
                          'CERRADO'
                      )
                )::int AS registros_excluidos_fecha_inconsistente

            FROM base_retiros;
            """
        )

        # Pendientes en RRLL es una fotografía actual.
        # No se limita por el periodo seleccionado.
        query_pendientes_rrll = text(
            f"""
            SELECT
                COUNT(*)::int AS pendientes_rrll

            FROM public."RetiroLaboral" rl

            LEFT JOIN public."Cliente" c
                ON c."IdCliente" = rl."IdCliente"

            LEFT JOIN public."MotivoRetiro" mr
                ON mr."IdMotivoRetiro" = rl."IdMotivoRetiro"

            WHERE UPPER(
                TRIM(
                    COALESCE(
                        rl."EstadoCasoRRLL",
                        ''
                    )
                )
            ) = 'ABIERTO'

            {filtros_comunes};
            """
        )

        fila_total = db.execute(
            query_total_retiros,
            parametros,
        ).mappings().first()

        fila_indicadores_rotacion = db.execute(
            query_indicadores_rotacion,
            parametros,
        ).mappings().first()

        fila_tiempo_laborado = db.execute(
            query_tiempo_laborado,
            parametros,
        ).mappings().first()

        fila_pendientes = db.execute(
            query_pendientes_rrll,
            parametros,
        ).mappings().first()

        fila_tiempo = db.execute(
            query_tiempo_desvinculacion,
            parametros,
        ).mappings().first()

        filas_clasificacion = db.execute(
            query_clasificacion,
            parametros,
        ).mappings().all()

        filas_motivos = db.execute(
            query_motivos,
            parametros,
        ).mappings().all()

        filas_sedes = db.execute(
            query_sedes,
            parametros,
        ).mappings().all()

        total_retiros = (
            int(fila_total["total_retiros"])
            if fila_total
            else 0
        )

        rotacion_total = (
            int(fila_indicadores_rotacion["rotacion_total"])
            if fila_indicadores_rotacion
            else 0
        )

        rotacion_voluntaria = (
            int(fila_indicadores_rotacion["rotacion_voluntaria"])
            if fila_indicadores_rotacion
            else 0
        )

        terminaciones = (
            int(fila_indicadores_rotacion["terminaciones"])
            if fila_indicadores_rotacion
            else 0
        )

        nunca_ingreso = (
            int(fila_indicadores_rotacion["nunca_ingreso"])
            if fila_indicadores_rotacion
            else 0
        )

        abandonos = (
            int(fila_indicadores_rotacion["abandonos"])
            if fila_indicadores_rotacion
            else 0
        )

        tiempo_laborado_promedio_dias = (
            convertir_decimal(fila_tiempo_laborado["promedio_dias"])
            if fila_tiempo_laborado
            else 0.0
        )

        registros_validos_tiempo_laborado = (
            int(fila_tiempo_laborado["registros_validos"])
            if fila_tiempo_laborado
            else 0
        )

        registros_sin_fecha_ingreso = (
            int(fila_tiempo_laborado["registros_sin_fecha_ingreso"])
            if fila_tiempo_laborado
            else 0
        )

        registros_sin_fecha_retiro = (
            int(fila_tiempo_laborado["registros_sin_fecha_retiro"])
            if fila_tiempo_laborado
            else 0
        )

        registros_fecha_laboral_inconsistente = (
            int(fila_tiempo_laborado["registros_fecha_inconsistente"])
            if fila_tiempo_laborado
            else 0
        )

        registros_retiro_futuro = (
            int(fila_tiempo_laborado["registros_retiro_futuro"])
            if fila_tiempo_laborado
            else 0
        )

        pendientes_rrll = (
            int(fila_pendientes["pendientes_rrll"])
            if fila_pendientes
            else 0
        )

        tiempo_desvinculacion = (
            convertir_decimal(fila_tiempo["promedio_dias"])
            if fila_tiempo
            else 0.0
        )

        registros_validos_tiempo = (
            int(fila_tiempo["registros_validos"])
            if fila_tiempo
            else 0
        )

        registros_excluidos_tiempo = (
            int(
                fila_tiempo[
                    "registros_excluidos_fecha_inconsistente"
                ]
            )
            if fila_tiempo
            else 0
        )

        clasificacion = [
            {
                "nombre": fila["nombre"],
                "cantidad": int(fila["cantidad"]),
                "porcentaje": convertir_decimal(
                    fila["porcentaje"]
                ),
            }
            for fila in filas_clasificacion
        ]

        motivos_retiro = [
            {
                "nombre": fila["nombre"],
                "cantidad": int(fila["cantidad"]),
                "porcentaje": convertir_decimal(
                    fila["porcentaje"]
                ),
            }
            for fila in filas_motivos
        ]

        sedes_retiro = [
            {
                "nombre": fila["nombre"],
                "cantidad": int(fila["cantidad"]),
                "porcentaje": convertir_decimal(
                    fila["porcentaje"]
                ),
            }
            for fila in filas_sedes
        ]

        sede_mayor_rotacion = (
            sedes_retiro[0]
            if sedes_retiro
            else {
                "nombre": "SIN INFORMACIÓN",
                "cantidad": 0,
                "porcentaje": 0.0,
            }
        )

        resumen_ejecutivo = []
        prioridad = 1

        if pendientes_rrll > 0:
            resumen_ejecutivo.append(
                {
                    "id": prioridad,
                    "tipo": "alerta",
                    "prioridad": prioridad,
                    "indicador": "Pendientes en RRLL",
                    "texto": (
                        (
                            f"Actualmente existe 1 proceso pendiente "
                            if pendientes_rrll == 1
                            else (
                                f"Actualmente existen {pendientes_rrll} "
                                "procesos pendientes "
                            )
                        )
                        + "de gestión en Relaciones Laborales."
                    ),
                }
            )
            prioridad += 1

        if total_retiros > 0:
            resumen_ejecutivo.append(
                {
                    "id": prioridad,
                    "tipo": "informativo",
                    "prioridad": prioridad,
                    "indicador": "Retiros del periodo",
                    "texto": (
                        (
                            f"Se identificó {texto_retiros(total_retiros)} "
                            if total_retiros == 1
                            else (
                                f"Se identificaron "
                                f"{texto_retiros(total_retiros)} "
                            )
                        )
                        + f"entre {inicio.isoformat()} y "
                        + f"{fin.isoformat()}."
                    ),
                }
            )
            prioridad += 1

        if total_retiros > 0:
            resumen_ejecutivo.append(
                {
                    "id": prioridad,
                    "tipo": "informativo",
                    "prioridad": prioridad,
                    "indicador": "Distribución de retiros",
                    "texto": (
                        f"Del total consultado, "
                        f"{texto_casos(rotacion_voluntaria)} "
                        f"{verbo_corresponder(rotacion_voluntaria)} "
                        f"a rotación voluntaria, "
                        f"{texto_casos(terminaciones)} a terminaciones, "
                        f"{texto_casos(nunca_ingreso)} a nunca ingreso y "
                        f"{texto_casos(abandonos)} a abandonos."
                    ),
                }
            )
            prioridad += 1

        if registros_validos_tiempo_laborado > 0:
            resumen_ejecutivo.append(
                {
                    "id": prioridad,
                    "tipo": "informativo",
                    "prioridad": prioridad,
                    "indicador": "Tiempo laborado",
                    "texto": (
                        f"El tiempo promedio laborado fue de "
                        f"{tiempo_laborado_promedio_dias:.2f} días, "
                        f"calculado sobre "
                        f"{texto_retiros(registros_validos_tiempo_laborado)} "
                        "con fechas válidas."
                    ),
                }
            )
            prioridad += 1

        if motivos_retiro:
            motivo_principal = motivos_retiro[0]

            resumen_ejecutivo.append(
                {
                    "id": prioridad,
                    "tipo": "alerta",
                    "prioridad": prioridad,
                    "indicador": "Principal motivo",
                    "texto": (
                        f"El principal motivo de retiro fue "
                        f"{motivo_principal['nombre']}, con "
                        f"{texto_casos(motivo_principal['cantidad'])}, "
                        f"{texto_equivalencia(motivo_principal['cantidad'])} al "
                        f"{motivo_principal['porcentaje']:.2f}% "
                        "del total consultado."
                    ),
                }
            )
            prioridad += 1

        if sedes_retiro:
            sede_principal = sedes_retiro[0]

            resumen_ejecutivo.append(
                {
                    "id": prioridad,
                    "tipo": "alerta",
                    "prioridad": prioridad,
                    "indicador": "Sede con más retiros",
                    "texto": (
                        f"{sede_principal['nombre']} presentó "
                        f"{texto_retiros(sede_principal['cantidad'])}, "
                        f"{texto_equivalencia(sede_principal['cantidad'])} al "
                        f"{sede_principal['porcentaje']:.2f}% "
                        "del total del periodo."
                    ),
                }
            )
            prioridad += 1

        if clasificacion:
            clasificacion_principal = clasificacion[0]

            resumen_ejecutivo.append(
                {
                    "id": prioridad,
                    "tipo": "informativo",
                    "prioridad": prioridad,
                    "indicador": "Clasificación principal",
                    "texto": (
                        f"La clasificación con mayor participación fue "
                        f"{clasificacion_principal['nombre']}, con "
                        f"{texto_casos(clasificacion_principal['cantidad'])}, "
                        f"{texto_equivalencia(clasificacion_principal['cantidad'])} al "
                        f"{clasificacion_principal['porcentaje']:.2f}% "
                        "del total consultado."
                    ),
                }
            )
            prioridad += 1

        if registros_validos_tiempo > 0:
            resumen_ejecutivo.append(
                {
                    "id": prioridad,
                    "tipo": "informativo",
                    "prioridad": prioridad,
                    "indicador": "Tiempo de desvinculación",
                    "texto": (
                        f"El tiempo promedio de desvinculación fue de "
                        f"{tiempo_desvinculacion:.2f} días, calculado "
                        f"sobre {texto_registros(registros_validos_tiempo)} "
                        "con fechas válidas."
                    ),
                }
            )
            prioridad += 1

        if not resumen_ejecutivo:
            resumen_ejecutivo.append(
                {
                    "id": prioridad,
                    "tipo": "informativo",
                    "prioridad": prioridad,
                    "indicador": "Sin información",
                    "texto": (
                        "No se encontraron retiros ni procesos pendientes "
                        "para los filtros seleccionados."
                    ),
                }
            )

        return {
            "ok": True,
            "mensaje": (
                "Panel Gerencial RRLL consultado correctamente."
            ),
            "modo": (
                "individual"
                if id_registro_personal
                else "general"
            ),
            "periodoConsultado": (
                f"{inicio.isoformat()} al {fin.isoformat()}"
            ),
            "filtrosAplicados": {
                "periodo": periodo,
                "fechaInicial": inicio.isoformat(),
                "fechaFinal": fin.isoformat(),
                "sede": sede,
                "motivo": motivo,
                "idRegistroPersonal": id_registro_personal,
            },
            "indicadores": {
                "rotacionTotal": rotacion_total,
                "retirosPeriodo": total_retiros,
                "rotacionVoluntaria": rotacion_voluntaria,
                "terminaciones": terminaciones,
                "nuncaIngreso": nunca_ingreso,
                "abandonos": abandonos,
                "pendientesRRLL": pendientes_rrll,
                "tiempoLaboradoPromedioDias": (
                    tiempo_laborado_promedio_dias
                ),
                "tiempoDesvinculacion": tiempo_desvinculacion,
            },
            "detalleTiempoLaborado": {
                "promedioDias": tiempo_laborado_promedio_dias,
                "promedioMesesAproximado": round(
                    tiempo_laborado_promedio_dias / 30.4375,
                    2,
                ),
                "promedioAniosAproximado": round(
                    tiempo_laborado_promedio_dias / 365.25,
                    2,
                ),
                "registrosValidos": registros_validos_tiempo_laborado,
                "registrosSinFechaIngreso": registros_sin_fecha_ingreso,
                "registrosSinFechaRetiro": registros_sin_fecha_retiro,
                "registrosFechaInconsistente": (
                    registros_fecha_laboral_inconsistente
                ),
                "registrosRetiroFuturo": registros_retiro_futuro,
                "fechaInicialCalculo": (
                    "Última FechaIngreso disponible del vínculo"
                ),
                "fechaFinalCalculo": "FechaRetiro",
            },
            "detalleTiempoDesvinculacion": {
                "promedioDias": tiempo_desvinculacion,
                "registrosValidos": registros_validos_tiempo,
                "registrosExcluidosFechaInconsistente": (
                    registros_excluidos_tiempo
                ),
                "fechaInicialCalculo": "FechaProceso",
                "fechaFinalCalculo": "FechaCierre",
            },
            "resumenEjecutivo": resumen_ejecutivo,
            "sedeMayorRotacion": sede_mayor_rotacion,
            "clasificacion": clasificacion,
            "motivos": motivos_retiro,
            "sedes": sedes_retiro,
        }

    except HTTPException:
        raise

    except SQLAlchemyError as error:
        db.rollback()

        logger.exception(
            "Error de base de datos consultando el Panel Gerencial RRLL."
        )

        raise HTTPException(
            status_code=500,
            detail=(
                "No fue posible consultar la información del "
                "Panel Gerencial RRLL."
            ),
        ) from error

    except Exception as error:
        db.rollback()

        logger.exception(
            "Error inesperado consultando el Panel Gerencial RRLL."
        )

        raise HTTPException(
            status_code=500,
            detail=(
                "Ocurrió un error inesperado consultando el "
                "Panel Gerencial RRLL."
            ),
        ) from error