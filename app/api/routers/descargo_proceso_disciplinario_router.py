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
from domain.models.descargo_proceso_disciplinario import (
    DescargoProcesoDisciplinario,
)
from domain.schemas.descargo_proceso_disciplinario_schema import (
    DescargoProcesoDisciplinarioCreate,
    DescargoProcesoDisciplinarioResponse,
    DescargoProcesoDisciplinarioUpdate,
)


router = APIRouter(
    prefix="/api/descargo-proceso-disciplinario",
    tags=["Descargo Proceso Disciplinario"],
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


def obtener_descargo_por_id_o_error(
    db: Session,
    id_descargo: int,
) -> DescargoProcesoDisciplinario:
    descargo = (
        db.query(DescargoProcesoDisciplinario)
        .filter(
            DescargoProcesoDisciplinario
            .IdDescargoProcesoDisciplinario
            == id_descargo
        )
        .first()
    )

    if not descargo:
        raise HTTPException(
            status_code=404,
            detail={
                "mensaje": "Descargo no encontrado.",
                "IdDescargoProcesoDisciplinario": (
                    id_descargo
                ),
            },
        )

    return descargo


def obtener_descargo_por_proceso_interno(
    db: Session,
    id_proceso: int,
) -> DescargoProcesoDisciplinario | None:
    return (
        db.query(DescargoProcesoDisciplinario)
        .filter(
            DescargoProcesoDisciplinario
            .IdProcesoDisciplinario
            == id_proceso
        )
        .order_by(
            DescargoProcesoDisciplinario
            .IdDescargoProcesoDisciplinario
            .desc()
        )
        .first()
    )


@router.post(
    "/",
    response_model=DescargoProcesoDisciplinarioResponse,
)
def crear_descargo(
    data: DescargoProcesoDisciplinarioCreate,
    db: Session = Depends(get_db),
):
    validar_proceso_abierto(
        db=db,
        id_proceso=data.IdProcesoDisciplinario,
    )

    descargo_existente = (
        obtener_descargo_por_proceso_interno(
            db=db,
            id_proceso=data.IdProcesoDisciplinario,
        )
    )

    if descargo_existente:
        raise HTTPException(
            status_code=409,
            detail={
                "mensaje": (
                    "El proceso ya tiene un descargo "
                    "registrado. Debe actualizar el registro "
                    "existente o usar guardar-borrador."
                ),
                "IdProcesoDisciplinario": (
                    data.IdProcesoDisciplinario
                ),
                "IdDescargoProcesoDisciplinario": (
                    descargo_existente
                    .IdDescargoProcesoDisciplinario
                ),
            },
        )

    nuevo = DescargoProcesoDisciplinario(
        **data.model_dump()
    )

    try:
        db.add(nuevo)
        db.commit()
        db.refresh(nuevo)

        return nuevo

    except SQLAlchemyError as error:
        db.rollback()

        raise HTTPException(
            status_code=500,
            detail=(
                "No se pudo crear el descargo "
                "del proceso disciplinario."
            ),
        ) from error


@router.post(
    "/guardar-borrador",
    response_model=DescargoProcesoDisciplinarioResponse,
)
def guardar_borrador_descargo(
    data: DescargoProcesoDisciplinarioCreate,
    db: Session = Depends(get_db),
):
    validar_proceso_abierto(
        db=db,
        id_proceso=data.IdProcesoDisciplinario,
    )

    descargo = obtener_descargo_por_proceso_interno(
        db=db,
        id_proceso=data.IdProcesoDisciplinario,
    )

    datos = data.model_dump()

    # Este endpoint siempre guarda el registro como borrador.
    datos["EstadoBorrador"] = True

    try:
        if descargo:
            for campo, valor in datos.items():
                if campo == "IdProcesoDisciplinario":
                    continue

                setattr(
                    descargo,
                    campo,
                    valor,
                )

            descargo.FechaActualizacion = datetime.now()

            if (
                datos.get("UsuarioActualizacion")
                is not None
            ):
                descargo.UsuarioActualizacion = (
                    datos["UsuarioActualizacion"]
                )

        else:
            descargo = DescargoProcesoDisciplinario(
                **datos
            )

            db.add(descargo)

        db.commit()
        db.refresh(descargo)

        return descargo

    except SQLAlchemyError as error:
        db.rollback()

        raise HTTPException(
            status_code=500,
            detail=(
                "No se pudo guardar el borrador "
                "del descargo disciplinario."
            ),
        ) from error


@router.get(
    "/proceso/{id_proceso}",
    response_model=(
        DescargoProcesoDisciplinarioResponse | None
    ),
)
def obtener_descargo_por_proceso(
    id_proceso: int,
    db: Session = Depends(get_db),
):
    obtener_proceso_o_error(
        db=db,
        id_proceso=id_proceso,
    )

    return obtener_descargo_por_proceso_interno(
        db=db,
        id_proceso=id_proceso,
    )


@router.get(
    "/{id_descargo}",
    response_model=DescargoProcesoDisciplinarioResponse,
)
def obtener_descargo(
    id_descargo: int,
    db: Session = Depends(get_db),
):
    return obtener_descargo_por_id_o_error(
        db=db,
        id_descargo=id_descargo,
    )


@router.put(
    "/{id_descargo}",
    response_model=DescargoProcesoDisciplinarioResponse,
)
def actualizar_descargo(
    id_descargo: int,
    data: DescargoProcesoDisciplinarioUpdate,
    db: Session = Depends(get_db),
):
    descargo = obtener_descargo_por_id_o_error(
        db=db,
        id_descargo=id_descargo,
    )

    validar_proceso_abierto(
        db=db,
        id_proceso=descargo.IdProcesoDisciplinario,
    )

    datos_actualizados = data.model_dump(
        exclude_unset=True
    )

    for campo, valor in datos_actualizados.items():
        setattr(
            descargo,
            campo,
            valor,
        )

    descargo.FechaActualizacion = datetime.now()

    try:
        db.commit()
        db.refresh(descargo)

        return descargo

    except SQLAlchemyError as error:
        db.rollback()

        raise HTTPException(
            status_code=500,
            detail=(
                "No se pudo actualizar el descargo "
                "del proceso disciplinario."
            ),
        ) from error