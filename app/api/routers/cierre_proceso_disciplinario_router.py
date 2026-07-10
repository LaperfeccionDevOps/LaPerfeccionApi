from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from infrastructure.db.deps import get_db

from domain.models.agenda_proceso_disciplinario import (
    AgendaProcesoDisciplinario,
)
from domain.models.cierre_proceso_disciplinario import (
    CierreProcesoDisciplinario,
)
from domain.models.proceso_disciplinario import ProcesoDisciplinario

from domain.schemas.cierre_proceso_disciplinario_schema import (
    CierreProcesoDisciplinarioCreate,
    CierreProcesoDisciplinarioUpdate,
    CierreProcesoDisciplinarioResponse,
)


router = APIRouter(
    prefix="/api/cierre-proceso-disciplinario",
    tags=["Cierre Proceso Disciplinario"],
)


def sincronizar_cierre_con_agenda(
    db: Session,
    id_proceso_disciplinario: int,
) -> None:
    """
    Sincroniza el cierre del expediente disciplinario con su agenda.

    ProcesoDisciplinario:
        EstadoProceso = CERRADO

    AgendaProcesoDisciplinario:
        EstadoAgenda = ATENDIDO
        ColorAgenda = VERDE
    """

    fecha_actualizacion = datetime.now()

    proceso = (
        db.query(ProcesoDisciplinario)
        .filter(
            ProcesoDisciplinario.IdProcesoDisciplinario
            == id_proceso_disciplinario
        )
        .first()
    )

    if not proceso:
        raise HTTPException(
            status_code=404,
            detail="Proceso disciplinario no encontrado",
        )

    proceso.EstadoProceso = "CERRADO"
    proceso.FechaActualizacion = fecha_actualizacion
    proceso.UsuarioActualizacion = "rrll_cierre"

    eventos_agenda = (
        db.query(AgendaProcesoDisciplinario)
        .filter(
            AgendaProcesoDisciplinario.IdProcesoDisciplinario
            == id_proceso_disciplinario,
            AgendaProcesoDisciplinario.Activo.is_(True),
        )
        .all()
    )

    for evento in eventos_agenda:
        evento.EstadoAgenda = "ATENDIDO"
        evento.ColorAgenda = "VERDE"
        evento.FechaActualizacion = fecha_actualizacion
        evento.UsuarioActualizacion = "rrll_cierre"


@router.post(
    "/",
    response_model=CierreProcesoDisciplinarioResponse,
)
def crear_cierre(
    data: CierreProcesoDisciplinarioCreate,
    db: Session = Depends(get_db),
):
    proceso = (
        db.query(ProcesoDisciplinario)
        .filter(
            ProcesoDisciplinario.IdProcesoDisciplinario
            == data.IdProcesoDisciplinario
        )
        .first()
    )

    if not proceso:
        raise HTTPException(
            status_code=404,
            detail="Proceso disciplinario no encontrado",
        )

    cierre_existente = (
        db.query(CierreProcesoDisciplinario)
        .filter(
            CierreProcesoDisciplinario.IdProcesoDisciplinario
            == data.IdProcesoDisciplinario
        )
        .first()
    )

    if cierre_existente:
        raise HTTPException(
            status_code=409,
            detail="El proceso disciplinario ya tiene un cierre registrado",
        )

    try:
        nuevo_cierre = CierreProcesoDisciplinario(
            **data.model_dump()
        )

        db.add(nuevo_cierre)

        sincronizar_cierre_con_agenda(
            db=db,
            id_proceso_disciplinario=data.IdProcesoDisciplinario,
        )

        db.commit()
        db.refresh(nuevo_cierre)

        return nuevo_cierre

    except HTTPException:
        db.rollback()
        raise

    except SQLAlchemyError as error:
        db.rollback()

        raise HTTPException(
            status_code=500,
            detail=(
                "No se pudo registrar el cierre ni actualizar "
                "la agenda disciplinaria"
            ),
        ) from error


@router.get(
    "/{id_cierre}",
    response_model=CierreProcesoDisciplinarioResponse,
)
def obtener_cierre(
    id_cierre: int,
    db: Session = Depends(get_db),
):
    cierre = (
        db.query(CierreProcesoDisciplinario)
        .filter(
            CierreProcesoDisciplinario.IdCierreProcesoDisciplinario
            == id_cierre
        )
        .first()
    )

    if not cierre:
        raise HTTPException(
            status_code=404,
            detail="Cierre no encontrado",
        )

    return cierre


@router.get("/proceso/{id_proceso}")
def obtener_cierre_por_proceso(
    id_proceso: int,
    db: Session = Depends(get_db),
):
    cierre = (
        db.query(CierreProcesoDisciplinario)
        .filter(
            CierreProcesoDisciplinario.IdProcesoDisciplinario
            == id_proceso
        )
        .first()
    )

    if not cierre:
        raise HTTPException(
            status_code=404,
            detail="El proceso disciplinario no tiene cierre registrado",
        )

    return cierre


@router.put(
    "/{id_cierre}",
    response_model=CierreProcesoDisciplinarioResponse,
)
def actualizar_cierre(
    id_cierre: int,
    data: CierreProcesoDisciplinarioUpdate,
    db: Session = Depends(get_db),
):
    cierre = (
        db.query(CierreProcesoDisciplinario)
        .filter(
            CierreProcesoDisciplinario.IdCierreProcesoDisciplinario
            == id_cierre
        )
        .first()
    )

    if not cierre:
        raise HTTPException(
            status_code=404,
            detail="Cierre no encontrado",
        )

    try:
        datos_actualizacion = data.model_dump(
            exclude_unset=True
        )

        for campo, valor in datos_actualizacion.items():
            setattr(cierre, campo, valor)

        cierre.FechaActualizacion = datetime.now()

        sincronizar_cierre_con_agenda(
            db=db,
            id_proceso_disciplinario=cierre.IdProcesoDisciplinario,
        )

        db.commit()
        db.refresh(cierre)

        return cierre

    except HTTPException:
        db.rollback()
        raise

    except SQLAlchemyError as error:
        db.rollback()

        raise HTTPException(
            status_code=500,
            detail=(
                "No se pudo actualizar el cierre ni sincronizar "
                "la agenda disciplinaria"
            ),
        ) from error