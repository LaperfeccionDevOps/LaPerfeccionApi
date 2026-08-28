from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from api.routers.agenda_proceso_disciplinario_router import (
    validar_programacion_extraordinaria_citacion,
)
from infrastructure.db.deps import get_db
from domain.models.proceso_disciplinario import ProcesoDisciplinario
from domain.models.citacion_proceso_disciplinario import CitacionProcesoDisciplinario
from domain.schemas.citacion_proceso_disciplinario_schema import (
    CitacionProcesoDisciplinarioCreate,
    CitacionProcesoDisciplinarioResponse,
    CitacionProcesoDisciplinarioUpdate,
)


router = APIRouter(
    prefix="/api/citacion-proceso-disciplinario",
    tags=["Citación Proceso Disciplinario"],
)


def obtener_proceso_o_error(db: Session, id_proceso: int) -> ProcesoDisciplinario:
    proceso = (
        db.query(ProcesoDisciplinario)
        .filter(ProcesoDisciplinario.IdProcesoDisciplinario == id_proceso)
        .first()
    )
    if not proceso:
        raise HTTPException(
            status_code=404,
            detail={
                "mensaje": "Proceso disciplinario no encontrado.",
                "IdProcesoDisciplinario": id_proceso,
            },
        )
    return proceso


def validar_proceso_abierto(db: Session, id_proceso: int) -> ProcesoDisciplinario:
    proceso = obtener_proceso_o_error(db=db, id_proceso=id_proceso)
    if str(proceso.EstadoProceso or "").strip().upper() == "CERRADO":
        raise HTTPException(
            status_code=409,
            detail={
                "mensaje": (
                    "El proceso disciplinario ya fue cerrado y no admite modificaciones."
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
            CitacionProcesoDisciplinario.IdCitacionProcesoDisciplinario
            == id_citacion
        )
        .first()
    )
    if not citacion:
        raise HTTPException(
            status_code=404,
            detail={
                "mensaje": "Citación no encontrada.",
                "IdCitacionProcesoDisciplinario": id_citacion,
            },
        )
    return citacion


def obtener_ultima_citacion_por_proceso(
    db: Session,
    id_proceso: int,
) -> CitacionProcesoDisciplinario | None:
    return (
        db.query(CitacionProcesoDisciplinario)
        .filter(CitacionProcesoDisciplinario.IdProcesoDisciplinario == id_proceso)
        .order_by(
            CitacionProcesoDisciplinario.IdCitacionProcesoDisciplinario.desc()
        )
        .first()
    )


def validar_datos_extraordinarios(
    db: Session,
    id_proceso: int,
    es_extraordinaria: bool,
    fecha_citacion,
    hora_citacion,
    justificacion: str | None,
    validar_programacion: bool = True,
) -> None:
    if not es_extraordinaria:
        return

    if not fecha_citacion or not hora_citacion:
        raise HTTPException(
            status_code=400,
            detail="La fecha y la hora extraordinarias son obligatorias.",
        )

    if not str(justificacion or "").strip():
        raise HTTPException(
            status_code=400,
            detail="La justificación extraordinaria es obligatoria.",
        )

    if not validar_programacion:
        return

    validar_programacion_extraordinaria_citacion(
        db=db,
        fecha_evento=fecha_citacion,
        hora_inicio=hora_citacion,
        id_proceso_disciplinario=id_proceso,
        bloquear_cupo=True,
    )


@router.post("/", response_model=CitacionProcesoDisciplinarioResponse)
def crear_citacion(
    data: CitacionProcesoDisciplinarioCreate,
    db: Session = Depends(get_db),
):
    validar_proceso_abierto(db=db, id_proceso=data.IdProcesoDisciplinario)

    existente = obtener_ultima_citacion_por_proceso(
        db=db,
        id_proceso=data.IdProcesoDisciplinario,
    )

    if existente:
        raise HTTPException(
            status_code=409,
            detail={
                "mensaje": "El proceso ya tiene una citación registrada. Debe actualizarla.",
                "IdProcesoDisciplinario": data.IdProcesoDisciplinario,
                "IdCitacionProcesoDisciplinario": (
                    existente.IdCitacionProcesoDisciplinario
                ),
            },
        )

    validar_datos_extraordinarios(
        db=db,
        id_proceso=data.IdProcesoDisciplinario,
        es_extraordinaria=data.EsExtraordinaria,
        fecha_citacion=data.FechaCitacion,
        hora_citacion=data.HoraCitacion,
        justificacion=data.JustificacionExtraordinaria,
        validar_programacion=True,
    )

    nueva = CitacionProcesoDisciplinario(**data.model_dump())

    try:
        db.add(nueva)
        db.commit()
        db.refresh(nueva)
        return nueva
    except SQLAlchemyError as error:
        db.rollback()
        raise HTTPException(
            status_code=500,
            detail="No se pudo crear la citación del proceso disciplinario.",
        ) from error


@router.get(
    "/proceso/{id_proceso}",
    response_model=CitacionProcesoDisciplinarioResponse | None,
)
def obtener_citacion_por_proceso(
    id_proceso: int,
    db: Session = Depends(get_db),
):
    obtener_proceso_o_error(db=db, id_proceso=id_proceso)
    return obtener_ultima_citacion_por_proceso(db=db, id_proceso=id_proceso)


@router.get("/{id_citacion}", response_model=CitacionProcesoDisciplinarioResponse)
def obtener_citacion(
    id_citacion: int,
    db: Session = Depends(get_db),
):
    return obtener_citacion_o_error(db=db, id_citacion=id_citacion)


@router.put("/{id_citacion}", response_model=CitacionProcesoDisciplinarioResponse)
def actualizar_citacion(
    id_citacion: int,
    data: CitacionProcesoDisciplinarioUpdate,
    db: Session = Depends(get_db),
):
    citacion = obtener_citacion_o_error(db=db, id_citacion=id_citacion)
    validar_proceso_abierto(db=db, id_proceso=citacion.IdProcesoDisciplinario)

    datos = data.model_dump(exclude_unset=True)

    campos_programacion = {
        "FechaCitacion",
        "HoraCitacion",
        "EsExtraordinaria",
    }

    debe_validar_programacion = any(
        campo in datos
        for campo in campos_programacion
    )

    es_extraordinaria = datos.get(
        "EsExtraordinaria",
        citacion.EsExtraordinaria,
    )
    es_extraordinaria = bool(es_extraordinaria)
    datos["EsExtraordinaria"] = es_extraordinaria

    fecha = datos.get(
        "FechaCitacion",
        citacion.FechaCitacion,
    )
    hora = datos.get(
        "HoraCitacion",
        citacion.HoraCitacion,
    )
    justificacion = datos.get(
        "JustificacionExtraordinaria",
        citacion.JustificacionExtraordinaria,
    )

    validar_datos_extraordinarios(
        db=db,
        id_proceso=citacion.IdProcesoDisciplinario,
        es_extraordinaria=es_extraordinaria,
        fecha_citacion=fecha,
        hora_citacion=hora,
        justificacion=justificacion,
        validar_programacion=debe_validar_programacion,
    )

    if not es_extraordinaria:
        datos["MotivoExtraordinario"] = None
        datos["JustificacionExtraordinaria"] = None

    for campo, valor in datos.items():
        setattr(citacion, campo, valor)

    citacion.FechaActualizacion = datetime.now()

    try:
        db.commit()
        db.refresh(citacion)
        return citacion
    except SQLAlchemyError as error:
        db.rollback()
        raise HTTPException(
            status_code=500,
            detail="No se pudo actualizar la citación del proceso disciplinario.",
        ) from error
