# ruff: noqa: B008

from datetime import datetime, time

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.orm import Session

from infrastructure.db.deps import get_db
from infrastructure.security.auth_dependencies import get_current_user


router = APIRouter(
    prefix="/api/operaciones/alturas",
    tags=["Operaciones - Alturas"],
)


ROL_ADMIN = 1
ROL_SUPER_ADMIN = 5
ROL_OPERACIONES = 6
ROL_DESARROLLADOR = 15

ROLES_PERMITIDOS = {
    ROL_ADMIN,
    ROL_SUPER_ADMIN,
    ROL_OPERACIONES,
    ROL_DESARROLLADOR,
}

# Colombia no tiene horario de verano. La fecha del permiso se calcula en
# PostgreSQL con esta zona para que "hoy" no dependa del equipo del usuario.
ZONA_HORARIA = "America/Bogota"


class ClienteOut(BaseModel):
    id_cliente: int
    nombre: str


class PermisoTrabajoAlturasIn(BaseModel):
    id_cliente: int = Field(..., gt=0)
    hora_inicio_tarea: time
    hora_fin_tarea: time


class PermisoTrabajoAlturasOut(BaseModel):
    id_permiso_trabajo_alturas: int
    id_cliente: int
    cliente: str
    sede: str | None = None
    fecha_hora_inicio_tarea: datetime | None = None
    fecha_hora_fin_tarea: datetime | None = None
    fecha_creacion: datetime


def require_operaciones_alturas(
    current=Depends(get_current_user),
):
    roles_ids = {
        int(id_rol)
        for id_rol in (current.get("roles_ids") or [])
        if str(id_rol).strip()
    }

    if roles_ids & ROLES_PERMITIDOS:
        return current

    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="No tienes permiso para gestionar permisos de trabajo en alturas.",
    )


@router.get("/clientes", response_model=list[ClienteOut])
def listar_clientes_activos(
    db: Session = Depends(get_db),
    _current=Depends(require_operaciones_alturas),
):
    filas = db.execute(
        text("""
            SELECT "IdCliente" AS id_cliente,
                   "Nombre"    AS nombre
            FROM public."Cliente"
            WHERE COALESCE("Activo", TRUE)
            ORDER BY "Nombre"
        """)
    ).mappings().all()

    return [dict(fila) for fila in filas]


@router.get("/permisos", response_model=list[PermisoTrabajoAlturasOut])
def listar_permisos(
    db: Session = Depends(get_db),
    _current=Depends(require_operaciones_alturas),
):
    filas = db.execute(
        text("""
            SELECT P."IdPermisoTrabajoAlturas" AS id_permiso_trabajo_alturas,
                   P."IdCliente"               AS id_cliente,
                   C."Nombre"                  AS cliente,
                   P."Sede"                    AS sede,
                   P."FechaHoraInicioTarea"    AS fecha_hora_inicio_tarea,
                   P."FechaHoraFinTarea"       AS fecha_hora_fin_tarea,
                   P."FechaCreacion"           AS fecha_creacion
            FROM public."PermisoTrabajoAlturas" P
            JOIN public."Cliente" C ON C."IdCliente" = P."IdCliente"
            ORDER BY P."IdPermisoTrabajoAlturas" DESC
            LIMIT 200
        """)
    ).mappings().all()

    return [dict(fila) for fila in filas]


@router.post(
    "/permisos",
    response_model=PermisoTrabajoAlturasOut,
    status_code=status.HTTP_201_CREATED,
)
def crear_permiso(
    payload: PermisoTrabajoAlturasIn,
    db: Session = Depends(get_db),
    _current=Depends(require_operaciones_alturas),
):
    if payload.hora_fin_tarea <= payload.hora_inicio_tarea:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "La hora de finalización debe ser mayor "
                "a la hora de inicio."
            ),
        )

    cliente = db.execute(
        text("""
            SELECT "Nombre"
            FROM public."Cliente"
            WHERE "IdCliente" = :id_cliente
              AND COALESCE("Activo", TRUE)
        """),
        {"id_cliente": payload.id_cliente},
    ).scalar()

    if cliente is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="El cliente seleccionado no existe o está inactivo.",
        )

    try:
        # La fecha siempre es la de hoy en Colombia; del usuario solo se
        # reciben las horas.
        fila = db.execute(
            text("""
                WITH hoy AS (
                    SELECT (now() AT TIME ZONE :zona)::date AS fecha
                )
                INSERT INTO public."PermisoTrabajoAlturas" (
                    "IdCliente",
                    "FechaHoraInicioTarea",
                    "FechaHoraFinTarea"
                )
                SELECT :id_cliente,
                       (hoy.fecha + CAST(:hora_inicio AS time)) AT TIME ZONE :zona,
                       (hoy.fecha + CAST(:hora_fin AS time)) AT TIME ZONE :zona
                FROM hoy
                RETURNING "IdPermisoTrabajoAlturas" AS id_permiso_trabajo_alturas,
                          "IdCliente"               AS id_cliente,
                          "Sede"                    AS sede,
                          "FechaHoraInicioTarea"    AS fecha_hora_inicio_tarea,
                          "FechaHoraFinTarea"       AS fecha_hora_fin_tarea,
                          "FechaCreacion"           AS fecha_creacion
            """),
            {
                "id_cliente": payload.id_cliente,
                "hora_inicio": payload.hora_inicio_tarea,
                "hora_fin": payload.hora_fin_tarea,
                "zona": ZONA_HORARIA,
            },
        ).mappings().one()
        db.commit()
    except Exception:
        db.rollback()
        raise

    return {**fila, "cliente": cliente}
