# ruff: noqa: B008

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import text
from sqlalchemy.orm import Session

from infrastructure.db.deps import get_db
from infrastructure.security.role_guard import require_roles_ids


# ============================================================
# RQ - SELECCION
# SOLO CONSULTA
# NO INSERTA
# NO ACTUALIZA
# NO ELIMINA
# NO USAR CASCADE
# ============================================================

router = APIRouter(
    prefix="/api/seleccion/rq",
    tags=["Seleccion - RQ"],
)


# ============================================================
# ROLES AUTORIZADOS
# El helper require_roles_ids ya permite los roles globales
# definidos por la aplicacion.
# ============================================================

ROL_SELECCION = 2

require_seleccion_rq = require_roles_ids(ROL_SELECCION)


def _serializar_rq_seleccion(row) -> dict:
    """
    Convierte una fila de RQOperaciones en la estructura que consume
    el submodulo RQ de Seleccion.

    Este helper no modifica informacion en base de datos.
    """
    return {
        "IdRQOperaciones": (
            int(row["IdRQOperaciones"])
            if row["IdRQOperaciones"] is not None
            else None
        ),
        "TipoRQ": row["TipoRQ"],
        "CantidadSolicitada": int(row["CantidadSolicitada"] or 1),
        "EnviadoSeleccion": bool(row["EnviadoSeleccion"]),
        "FechaEnvioSeleccion": row["FechaEnvioSeleccion"],
        "IdRetiroLaboral": (
            int(row["IdRetiroLaboral"])
            if row["IdRetiroLaboral"] is not None
            else None
        ),
        "IdPazYSalvo": (
            int(row["IdPazYSalvo"])
            if row["IdPazYSalvo"] is not None
            else None
        ),
        "IdRegistroPersonal": (
            int(row["IdRegistroPersonal"])
            if row["IdRegistroPersonal"] is not None
            else None
        ),
        "NumeroIdentificacion": row["NumeroIdentificacion"],
        "NombreCompleto": row["NombreCompleto"],
        "IdCliente": (
            int(row["IdCliente"])
            if row["IdCliente"] is not None
            else None
        ),
        "NombreCliente": row["NombreCliente"],
        "IdCargo": (
            int(row["IdCargo"])
            if row["IdCargo"] is not None
            else None
        ),
        "NombreCargo": row["NombreCargo"],
        "IdUsuarioLider": (
            str(row["IdUsuarioLider"])
            if row["IdUsuarioLider"] is not None
            else None
        ),
        "NombreLider": row["NombreLider"],
        "IdPerfilRQ": (
            int(row["IdPerfilRQ"])
            if row["IdPerfilRQ"] is not None
            else None
        ),
        "CodigoPerfil": row["CodigoPerfil"],
        "DescripcionPerfil": row["DescripcionPerfil"],
        "GeneroPerfil": row["GeneroPerfil"],
        "NivelEscolaridadPerfil": row["NivelEscolaridadPerfil"],
        "ObservacionesPerfil": row["ObservacionesPerfil"],
        "TipoNotificacion": row["TipoNotificacion"],
        "FechaRetiro": row["FechaRetiro"],
        "FechaUltimoDiaLaborado": row["FechaUltimoDiaLaborado"],
        "Observacion": row["Observacion"],
        "RequiereReemplazo": bool(row["RequiereReemplazo"]),
        "Ciudad": row["Ciudad"],
        "Turno": row["Turno"],
        "MotivoVacante": row["MotivoVacante"],
        "ObservacionCliente": row["ObservacionCliente"],
        "FechaRegistro": row["FechaRegistro"],
        "EstadoRQ": row["EstadoRQ"],
        "EnviadoRRLL": bool(row["EnviadoRRLL"]),
        "FechaEnvioRRLL": row["FechaEnvioRRLL"],
        "EstadoCasoRRLL": row["EstadoCasoRRLL"],
        "FechaEnvioOperaciones": row["FechaEnvioOperaciones"],
        "FechaCreacion": row["FechaCreacion"],
        "FechaActualizacion": row["FechaActualizacion"],
    }


CONSULTA_BASE_RQ_SELECCION = """
    SELECT
        rq."IdRQOperaciones",
        rq."TipoRQ",
        rq."CantidadSolicitada",
        rq."EnviadoSeleccion",
        rq."FechaEnvioSeleccion",
        rq."IdRetiroLaboral",
        rq."IdPazYSalvo",
        rq."IdRegistroPersonal",
        rq."IdCliente",
        rq."IdUsuarioLider",
        rq."IdPerfilRQ",
        rq."TipoNotificacion",
        rq."FechaRetiro",
        rq."FechaUltimoDiaLaborado",
        rq."Observacion",
        rq."RequiereReemplazo",
        rq."Ciudad",
        rq."Turno",
        rq."MotivoVacante",
        rq."ObservacionCliente",
        rq."FechaRegistro",
        rq."EstadoRQ",
        rq."EnviadoRRLL",
        rq."FechaEnvioRRLL",
        rq."FechaCreacion",
        rq."FechaActualizacion",

        rp."NumeroIdentificacion",
        TRIM(
            COALESCE(rp."Nombres", '') || ' ' ||
            COALESCE(rp."Apellidos", '')
        ) AS "NombreCompleto",

        c."Nombre" AS "NombreCliente",

        rq."IdCargo",
        ca."NombreCargo",

        u."NombreUsuario" AS "NombreLider",

        prq."CodigoPerfil",
        prq."DescripcionPerfil",
        prq."Genero" AS "GeneroPerfil",
        prq."NivelEscolaridad" AS "NivelEscolaridadPerfil",
        prq."Observaciones" AS "ObservacionesPerfil",

        rl."EstadoCasoRRLL",
        rl."FechaEnvioOperaciones"

    FROM public."RQOperaciones" rq

    INNER JOIN public."RetiroLaboral" rl
        ON rl."IdRetiroLaboral" = rq."IdRetiroLaboral"

    INNER JOIN public."RegistroPersonal" rp
        ON rp."IdRegistroPersonal" = rq."IdRegistroPersonal"

    INNER JOIN public."Cliente" c
        ON c."IdCliente" = rq."IdCliente"

    INNER JOIN public."Usuario" u
        ON u."IdUsuario" = rq."IdUsuarioLider"

    LEFT JOIN public."PerfilRQ" prq
        ON prq."IdPerfilRQ" = rq."IdPerfilRQ"

    LEFT JOIN public."Cargo" ca
        ON ca."IdCargo" = rq."IdCargo"
"""


@router.get("")
@router.get("/")
def listar_rq_recibidas_seleccion(
    db: Session = Depends(get_db),
    current=Depends(require_seleccion_rq),
):
    """
    Lista unicamente las RQ que Operaciones envio formalmente a Seleccion.

    Reglas:
    - Una RQ PENDIENTE_OPERACIONES no aparece.
    - Una RQ LISTO_PARA_ENVIO no aparece.
    - Un retiro enviado solo a RRLL, sin necesidad de Seleccion, no aparece.
    - Solo aparece cuando EnviadoSeleccion = true.
    - TipoRQ debe identificar una requisicion real para Seleccion.
    - Para el flujo actual de retiros, el RQ tambien debe estar ENVIADO_RRLL.
    - Endpoint de solo consulta.
    """

    rows = db.execute(
        text(
            CONSULTA_BASE_RQ_SELECCION
            + """
            WHERE COALESCE(rq."Activo", true) = true
              AND COALESCE(rq."EnviadoSeleccion", false) = true
              AND rq."FechaEnvioSeleccion" IS NOT NULL
              AND rq."TipoRQ" IS NOT NULL
              AND UPPER(TRIM(COALESCE(rq."TipoRQ", '')))
                    = 'REEMPLAZO'
              AND COALESCE(rq."RequiereReemplazo", false) = true
              AND COALESCE(rq."EnviadoRRLL", false) = true
              AND UPPER(TRIM(COALESCE(rq."EstadoRQ", '')))
                    = 'ENVIADO_RRLL'
              AND rl."FechaEnvioOperaciones" IS NOT NULL
            ORDER BY
                rq."FechaEnvioSeleccion" DESC NULLS LAST,
                rq."FechaRegistro" DESC,
                rq."IdRQOperaciones" DESC;
            """
        )
    ).mappings().all()

    data = [_serializar_rq_seleccion(row) for row in rows]

    return {
        "success": True,
        "message": "RQ enviadas a Seleccion consultadas correctamente.",
        "total": len(data),
        "data": data,
    }


@router.get("/{id_rq_operaciones}")
def obtener_detalle_rq_seleccion(
    id_rq_operaciones: int,
    db: Session = Depends(get_db),
    current=Depends(require_seleccion_rq),
):
    """
    Devuelve el detalle de una RQ enviada formalmente a Seleccion.

    No permite consultar desde este modulo una RQ que todavia siga
    PENDIENTE_OPERACIONES o LISTO_PARA_ENVIO, ni un retiro que haya
    sido enviado a RRLL pero que no represente una requisicion real
    para Seleccion.
    """

    row = db.execute(
        text(
            CONSULTA_BASE_RQ_SELECCION
            + """
            WHERE rq."IdRQOperaciones" = :id_rq_operaciones
              AND COALESCE(rq."Activo", true) = true
              AND COALESCE(rq."EnviadoSeleccion", false) = true
              AND rq."FechaEnvioSeleccion" IS NOT NULL
              AND rq."TipoRQ" IS NOT NULL
              AND UPPER(TRIM(COALESCE(rq."TipoRQ", '')))
                    = 'REEMPLAZO'
              AND COALESCE(rq."RequiereReemplazo", false) = true
              AND COALESCE(rq."EnviadoRRLL", false) = true
              AND UPPER(TRIM(COALESCE(rq."EstadoRQ", '')))
                    = 'ENVIADO_RRLL'
              AND rl."FechaEnvioOperaciones" IS NOT NULL
            LIMIT 1;
            """
        ),
        {"id_rq_operaciones": id_rq_operaciones},
    ).mappings().first()

    if not row:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=(
                "La RQ no existe o todavia no ha sido enviada "
                "formalmente a Seleccion."
            ),
        )

    return {
        "success": True,
        "message": "Detalle de RQ consultado correctamente.",
        "data": _serializar_rq_seleccion(row),
    }
