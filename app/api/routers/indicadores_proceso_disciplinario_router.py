# ruff: noqa: B008, BLE001

from datetime import date, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from infrastructure.db.deps import get_db


router = APIRouter(
    prefix="/api/indicadores-procesos-disciplinarios",
    tags=["Indicadores Procesos Disciplinarios"],
)


@router.get("/kpi3")
def obtener_kpi3_procesos_disciplinarios(
    fecha_inicio: date | None = Query(None),
    fecha_fin: date | None = Query(None),
    db: Session = Depends(get_db),
):
    """
    KPI 3 - Cobertura de atención de procesos disciplinarios.

    Universo:
    Procesos originados en Operaciones que fueron enviados a RRLL.

    - Sin fechas: retorna la información global del módulo.
    - Con fecha inicial y fecha final: retorna únicamente los procesos
      cuya primera entrada a RRLL se encuentra dentro del periodo consultado.

    Agendado:
    Tiene al menos una agenda activa creada en el periodo.

    Atendido:
    Tiene al menos un registro en DescargoProcesoDisciplinario.
    El descargo confirma que la atención disciplinaria realmente ocurrió,
    aunque el estado de la agenda no haya sido actualizado a ATENDIDO.

    Cerrado:
    Tiene al menos un registro en CierreProcesoDisciplinario.

    Cobertura de atención KPI 3:
    Se calcula con trabajadores únicos:
    trabajadores atendidos / trabajadores agendados * 100.

    Las tarjetas Agendados, Atendidos, Pendientes y Cerrados
    continúan expresadas en cantidad de procesos.
    """

    if (fecha_inicio is None) != (fecha_fin is None):
        raise HTTPException(
            status_code=400,
            detail={
                "mensaje": (
                    "Para filtrar por periodo debe enviar "
                    "la fecha inicial y la fecha final."
                )
            },
        )

    if (
        fecha_inicio is not None
        and fecha_fin is not None
        and fecha_fin < fecha_inicio
    ):
        raise HTTPException(
            status_code=400,
            detail={
                "mensaje": (
                    "La fecha final no puede ser menor "
                    "que la fecha inicial."
                )
            },
        )

    fecha_fin_exclusiva = (
        fecha_fin + timedelta(days=1)
        if fecha_fin is not None
        else None
    )

    consulta_resumen = text(
        """
        WITH procesos_periodo AS (
            SELECT
                pd."IdProcesoDisciplinario",
                pd."IdRegistroPersonal",

                MIN(
                    ag."FechaCreacion"
                ) AS "FechaEntradaRRLL"

            FROM public."ProcesoDisciplinario" pd

            INNER JOIN public."AgendaProcesoDisciplinario" ag
                ON ag."IdProcesoDisciplinario"
                = pd."IdProcesoDisciplinario"

            WHERE
                UPPER(
                    COALESCE(
                        pd."OrigenProceso",
                        ''
                    )
                ) = 'OPERACIONES'

                AND COALESCE(
                    ag."Activo",
                    TRUE
                ) = TRUE

            GROUP BY
                pd."IdProcesoDisciplinario",
                pd."IdRegistroPersonal"

            HAVING
                (
                    CAST(:fecha_inicio AS date) IS NULL
                    OR MIN(
                        ag."FechaCreacion"
                    ) >= CAST(:fecha_inicio AS date)
                )

                AND (
                    CAST(:fecha_fin_exclusiva AS date) IS NULL
                    OR MIN(
                        ag."FechaCreacion"
                    ) < CAST(:fecha_fin_exclusiva AS date)
                )
        ),

        resultado AS (
            SELECT
                pp."IdProcesoDisciplinario",
                pp."IdRegistroPersonal",

                EXISTS (
                    SELECT 1
                    FROM public."DescargoProcesoDisciplinario" dpd
                    WHERE
                        dpd."IdProcesoDisciplinario"
                        = pp."IdProcesoDisciplinario"
                ) AS "FueAtendido",

                EXISTS (
                    SELECT 1
                    FROM public."CierreProcesoDisciplinario" cp
                    WHERE
                        cp."IdProcesoDisciplinario"
                        = pp."IdProcesoDisciplinario"
                ) AS "FueCerrado"

            FROM procesos_periodo pp
        )

        SELECT
            COUNT(*) AS "Agendados",

            COUNT(*) FILTER (
                WHERE "FueAtendido" = TRUE
            ) AS "Atendidos",

            COUNT(*) FILTER (
                WHERE "FueAtendido" = FALSE
            ) AS "PendientesAtencion",

            COUNT(*) FILTER (
                WHERE "FueCerrado" = TRUE
            ) AS "Cerrados",

            COUNT(*) FILTER (
                WHERE
                    "FueAtendido" = TRUE
                    AND "FueCerrado" = FALSE
            ) AS "AtendidosPendientesCierre",

            COUNT(
                DISTINCT "IdRegistroPersonal"
            ) AS "TrabajadoresAgendados",

            COUNT(
                DISTINCT "IdRegistroPersonal"
            ) FILTER (
                WHERE "FueAtendido" = TRUE
            ) AS "TrabajadoresAtendidos",

            ROUND(
                COUNT(
                    DISTINCT "IdRegistroPersonal"
                ) FILTER (
                    WHERE "FueAtendido" = TRUE
                )::numeric
                / NULLIF(
                    COUNT(
                        DISTINCT "IdRegistroPersonal"
                    ),
                    0
                )
                * 100,
                2
            ) AS "CoberturaAtencion",

            ROUND(
                COUNT(*) FILTER (
                    WHERE "FueCerrado" = TRUE
                )::numeric
                / NULLIF(
                    COUNT(*),
                    0
                )
                * 100,
                2
            ) AS "CoberturaCierre"

        FROM resultado
        """
    )

    consulta_detalle = text(
        """
        WITH agenda_resumen AS (
            SELECT
                ag."IdProcesoDisciplinario",

                MIN(
                    ag."FechaCreacion"
                ) AS "FechaEntradaRRLL",

                MIN(
                    ag."FechaEvento"
                ) AS "PrimeraFechaEvento",

                COUNT(*) AS "CantidadAgendas"

            FROM public."AgendaProcesoDisciplinario" ag

            WHERE
                COALESCE(
                    ag."Activo",
                    TRUE
                ) = TRUE

            GROUP BY
                ag."IdProcesoDisciplinario"
        ),

        cierre_resumen AS (
            SELECT
                cp."IdProcesoDisciplinario",

                MIN(
                    cp."FechaCierre"
                ) AS "FechaCierre"

            FROM public."CierreProcesoDisciplinario" cp

            GROUP BY
                cp."IdProcesoDisciplinario"
        )

        SELECT
            pd."IdProcesoDisciplinario"
                AS "IdProcesoDisciplinario",

            pd."IdRegistroPersonal"
                AS "IdRegistroPersonal",

            rp."NumeroIdentificacion"
                AS "NumeroIdentificacion",

            TRIM(
                CONCAT(
                    COALESCE(
                        rp."Nombres",
                        ''
                    ),
                    ' ',
                    COALESCE(
                        rp."Apellidos",
                        ''
                    )
                )
            ) AS "Trabajador",

            pd."EstadoProceso"
                AS "EstadoProceso",

            pd."OrigenProceso"
                AS "OrigenProceso",

            ar."FechaEntradaRRLL"
                AS "FechaEntradaRRLL",

            ar."PrimeraFechaEvento"
                AS "FechaCita",

            ar."CantidadAgendas"
                AS "CantidadAgendas",

            EXISTS (
                SELECT 1
                FROM public."DescargoProcesoDisciplinario" dpd
                WHERE
                    dpd."IdProcesoDisciplinario"
                    = pd."IdProcesoDisciplinario"
            ) AS "FueAtendido",

            CASE
                WHEN cr."IdProcesoDisciplinario"
                    IS NOT NULL
                THEN TRUE
                ELSE FALSE
            END AS "FueCerrado",

            cr."FechaCierre"
                AS "FechaCierre"

        FROM public."ProcesoDisciplinario" pd

        INNER JOIN agenda_resumen ar
            ON ar."IdProcesoDisciplinario"
            = pd."IdProcesoDisciplinario"

        LEFT JOIN cierre_resumen cr
            ON cr."IdProcesoDisciplinario"
            = pd."IdProcesoDisciplinario"

        LEFT JOIN public."RegistroPersonal" rp
            ON rp."IdRegistroPersonal"
            = pd."IdRegistroPersonal"

        WHERE
            UPPER(
                COALESCE(
                    pd."OrigenProceso",
                    ''
                )
            ) = 'OPERACIONES'

            AND (
                CAST(:fecha_inicio AS date) IS NULL
                OR ar."FechaEntradaRRLL"
                    >= CAST(:fecha_inicio AS date)
            )

            AND (
                CAST(:fecha_fin_exclusiva AS date) IS NULL
                OR ar."FechaEntradaRRLL"
                    < CAST(:fecha_fin_exclusiva AS date)
            )

        ORDER BY
            ar."FechaEntradaRRLL" ASC,
            pd."IdProcesoDisciplinario" ASC
        """
    )

    parametros = {
        "fecha_inicio": fecha_inicio,
        "fecha_fin_exclusiva": fecha_fin_exclusiva,
    }

    try:
        resumen = (
            db.execute(
                consulta_resumen,
                parametros,
            )
            .mappings()
            .first()
        )

        detalle = (
            db.execute(
                consulta_detalle,
                parametros,
            )
            .mappings()
            .all()
        )

        agendados = int(
            resumen["Agendados"] or 0
        )

        atendidos = int(
            resumen["Atendidos"] or 0
        )

        pendientes_atencion = int(
            resumen["PendientesAtencion"] or 0
        )

        cerrados = int(
            resumen["Cerrados"] or 0
        )

        atendidos_pendientes_cierre = int(
            resumen[
                "AtendidosPendientesCierre"
            ]
            or 0
        )

        trabajadores_agendados = int(
            resumen["TrabajadoresAgendados"] or 0
        )

        trabajadores_atendidos = int(
            resumen["TrabajadoresAtendidos"] or 0
        )

        cobertura_atencion = float(
            resumen["CoberturaAtencion"] or 0
        )

        cobertura_cierre = float(
            resumen["CoberturaCierre"] or 0
        )

        return {
            "ok": True,
            "periodo": {
                "fechaInicio": fecha_inicio,
                "fechaFin": fecha_fin,
                "esGlobal": (
                    fecha_inicio is None
                    and fecha_fin is None
                ),
            },
            "kpi3": {
                "agendados": agendados,
                "atendidos": atendidos,
                "pendientesAtencion": (
                    pendientes_atencion
                ),
                "cerrados": cerrados,
                "atendidosPendientesCierre": (
                    atendidos_pendientes_cierre
                ),
                "trabajadoresAgendados": (
                    trabajadores_agendados
                ),
                "trabajadoresAtendidos": (
                    trabajadores_atendidos
                ),
                "coberturaAtencion": (
                    cobertura_atencion
                ),
                "coberturaCierre": (
                    cobertura_cierre
                ),
            },
            "detalle": [
                dict(registro)
                for registro in detalle
            ],
        }

    except SQLAlchemyError as error:
        raise HTTPException(
            status_code=500,
            detail={
                "mensaje": (
                    "No fue posible consultar los "
                    "indicadores de procesos "
                    "disciplinarios."
                )
            },
        ) from error