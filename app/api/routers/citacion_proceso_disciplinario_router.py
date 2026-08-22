from datetime import datetime

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
)
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from infrastructure.db.deps import get_db

from domain.models.proceso_disciplinario import (
    ProcesoDisciplinario,
)
from domain.models.citacion_proceso_disciplinario import (
    CitacionProcesoDisciplinario,
)
from domain.schemas.citacion_proceso_disciplinario_schema import (
    CitacionProcesoDisciplinarioCreate,
    CitacionProcesoDisciplinarioResponse,
    CitacionProcesoDisciplinarioUpdate,
)


router = APIRouter(
    prefix="/api/citacion-proceso-disciplinario",
    tags=["Citación Proceso Disciplinario"],
)


def obtener_proceso_o_error(
    db: Session,
    id_proceso: int,
) -> ProcesoDisciplinario:
    proceso = (
        db.query(ProcesoDisciplinario)
        .filter(
            ProcesoDisciplinario.IdProcesoDisciplinario
            == id_proceso
        )
        .first()
    )

    if not proceso:
        raise HTTPException(
            status_code=404,
            detail={
                "mensaje": (
                    "Proceso disciplinario no encontrado."
                ),
                "IdProcesoDisciplinario": id_proceso,
            },
        )

    return proceso


def validar_proceso_abierto(
    db: Session,
    id_proceso: int,
) -> ProcesoDisciplinario:
    proceso = obtener_proceso_o_error(
        db=db,
        id_proceso=id_proceso,
    )

    estado_proceso = str(
        proceso.EstadoProceso or ""
    ).strip().upper()

    if estado_proceso == "CERRADO":
        raise HTTPException(
            status_code=409,
            detail={
                "mensaje": (
                    "El proceso disciplinario ya fue cerrado "
                    "y no admite modificaciones."
                ),
                "IdProcesoDisciplinario": id_proceso,
                "EstadoProceso": proceso.EstadoProceso,
            },
        )

    return proceso


def obtener_citacion_o_error(
    db: Session,
    id_citacion: int,
) -> CitacionProcesoDisciplinario:
    citacion = (
        db.query(CitacionProcesoDisciplinario)
        .filter(
            CitacionProcesoDisciplinario
            .IdCitacionProcesoDisciplinario
            == id_citacion
        )
        .first()
    )

    if not citacion:
        raise HTTPException(
            status_code=404,
            detail={
                "mensaje": "Citación no encontrada.",
                "IdCitacionProcesoDisciplinario": (
                    id_citacion
                ),
            },
        )

    return citacion


def obtener_ultima_citacion_por_proceso(
    db: Session,
    id_proceso: int,
) -> CitacionProcesoDisciplinario | None:
    return (
        db.query(CitacionProcesoDisciplinario)
        .filter(
            CitacionProcesoDisciplinario
            .IdProcesoDisciplinario
            == id_proceso
        )
        .order_by(
            CitacionProcesoDisciplinario
            .IdCitacionProcesoDisciplinario
            .desc()
        )
        .first()
    )


@router.post(
    "/",
    response_model=CitacionProcesoDisciplinarioResponse,
)
def crear_citacion(
    data: CitacionProcesoDisciplinarioCreate,
    db: Session = Depends(get_db),
):
    validar_proceso_abierto(
        db=db,
        id_proceso=data.IdProcesoDisciplinario,
    )

    citacion_existente = (
        obtener_ultima_citacion_por_proceso(
            db=db,
            id_proceso=data.IdProcesoDisciplinario,
        )
    )

    if citacion_existente:
        raise HTTPException(
            status_code=409,
            detail={
                "mensaje": (
                    "El proceso ya tiene una citación "
                    "registrada. Debe actualizarla."
                ),
                "IdProcesoDisciplinario": (
                    data.IdProcesoDisciplinario
                ),
                "IdCitacionProcesoDisciplinario": (
                    citacion_existente
                    .IdCitacionProcesoDisciplinario
                ),
            },
        )

    nueva = CitacionProcesoDisciplinario(
        **data.model_dump()
    )

    try:
        db.add(nueva)
        db.commit()
        db.refresh(nueva)

        return nueva

    except SQLAlchemyError as error:
        db.rollback()

        raise HTTPException(
            status_code=500,
            detail=(
                "No se pudo crear la citación "
                "del proceso disciplinario."
            ),
        ) from error


@router.get(
    "/proceso/{id_proceso}",
    response_model=(
        CitacionProcesoDisciplinarioResponse | None
    ),
)
def obtener_citacion_por_proceso(
    id_proceso: int,
    db: Session = Depends(get_db),
):
    obtener_proceso_o_error(
        db=db,
        id_proceso=id_proceso,
    )

    return obtener_ultima_citacion_por_proceso(
        db=db,
        id_proceso=id_proceso,
    )


@router.get(
    "/{id_citacion}",
    response_model=CitacionProcesoDisciplinarioResponse,
)
def obtener_citacion(
    id_citacion: int,
    db: Session = Depends(get_db),
):
    return obtener_citacion_o_error(
        db=db,
        id_citacion=id_citacion,
    )


@router.put(
    "/{id_citacion}",
    response_model=CitacionProcesoDisciplinarioResponse,
)
def actualizar_citacion(
    id_citacion: int,
    data: CitacionProcesoDisciplinarioUpdate,
    db: Session = Depends(get_db),
):
    citacion = obtener_citacion_o_error(
        db=db,
        id_citacion=id_citacion,
    )

    validar_proceso_abierto(
        db=db,
        id_proceso=citacion.IdProcesoDisciplinario,
    )

    datos_actualizados = data.model_dump(
        exclude_unset=True
    )

    for campo, valor in datos_actualizados.items():
        setattr(
            citacion,
            campo,
            valor,
        )

    citacion.FechaActualizacion = datetime.now()

    try:
        db.commit()
        db.refresh(citacion)

        return citacion

    except SQLAlchemyError as error:
        db.rollback()

        raise HTTPException(
            status_code=500,
            detail=(
                "No se pudo actualizar la citación "
                "del proceso disciplinario."
            ),
        ) from error