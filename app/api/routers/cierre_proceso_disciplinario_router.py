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
from domain.models.proceso_disciplinario import (
    ProcesoDisciplinario,
)

from domain.schemas.cierre_proceso_disciplinario_schema import (
    CierreProcesoDisciplinarioCreate,
    CierreProcesoDisciplinarioUpdate,
    CierreProcesoDisciplinarioResponse,
)


router = APIRouter(
    prefix="/api/cierre-proceso-disciplinario",
    tags=["Cierre Proceso Disciplinario"],
)


def obtener_proceso_o_error(
    db: Session,
    id_proceso: int,
) -> ProcesoDisciplinario:
    """
    Busca un proceso disciplinario.

    Genera error 404 cuando el proceso no existe.
    """

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
    proceso: ProcesoDisciplinario,
) -> None:
    """
    Impide modificar un proceso disciplinario
    que ya se encuentre cerrado.
    """

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
                "IdProcesoDisciplinario": (
                    proceso.IdProcesoDisciplinario
                ),
                "EstadoProceso": proceso.EstadoProceso,
            },
        )


def sincronizar_cierre_con_agenda(
    db: Session,
    id_proceso_disciplinario: int,
) -> None:
    """
    Sincroniza el cierre del expediente disciplinario
    con el proceso principal y con la agenda.

    ProcesoDisciplinario:
        EstadoProceso = CERRADO

    AgendaProcesoDisciplinario:
        EstadoAgenda = ATENDIDO
        ColorAgenda = VERDE
    """

    fecha_actualizacion = datetime.now()

    proceso = obtener_proceso_o_error(
        db=db,
        id_proceso=id_proceso_disciplinario,
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
    """
    Registra el cierre de un proceso disciplinario abierto.

    Después de guardar el cierre:
    - El proceso queda CERRADO.
    - La agenda queda ATENDIDA.
    - El color de agenda queda VERDE.
    """

    proceso = obtener_proceso_o_error(
        db=db,
        id_proceso=data.IdProcesoDisciplinario,
    )

    # Permite cerrar un proceso abierto,
    # pero impide registrar otro cierre si ya estaba cerrado.
    validar_proceso_abierto(proceso)

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
            detail={
                "mensaje": (
                    "El proceso disciplinario ya tiene "
                    "un cierre registrado."
                ),
                "IdProcesoDisciplinario": (
                    data.IdProcesoDisciplinario
                ),
                "IdCierreProcesoDisciplinario": (
                    cierre_existente
                    .IdCierreProcesoDisciplinario
                ),
            },
        )

    try:
        nuevo_cierre = CierreProcesoDisciplinario(
            **data.model_dump()
        )

        db.add(nuevo_cierre)

        sincronizar_cierre_con_agenda(
            db=db,
            id_proceso_disciplinario=(
                data.IdProcesoDisciplinario
            ),
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
                "No se pudo registrar el cierre ni "
                "actualizar la agenda disciplinaria."
            ),
        ) from error


@router.get(
    "/proceso/{id_proceso}",
)
def obtener_cierre_por_proceso(
    id_proceso: int,
    db: Session = Depends(get_db),
):
    """
    Consulta el cierre mediante el ID del proceso.

    Se permite consultar procesos abiertos y cerrados.
    """

    obtener_proceso_o_error(
        db=db,
        id_proceso=id_proceso,
    )

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
            detail={
                "mensaje": (
                    "El proceso disciplinario no tiene "
                    "cierre registrado."
                ),
                "IdProcesoDisciplinario": id_proceso,
            },
        )

    return cierre


@router.get(
    "/{id_cierre}",
    response_model=CierreProcesoDisciplinarioResponse,
)
def obtener_cierre(
    id_cierre: int,
    db: Session = Depends(get_db),
):
    """
    Consulta un cierre por su ID.

    Se permite consultar cierres de procesos finalizados.
    """

    cierre = (
        db.query(CierreProcesoDisciplinario)
        .filter(
            CierreProcesoDisciplinario
            .IdCierreProcesoDisciplinario
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


@router.put(
    "/{id_cierre}",
    response_model=CierreProcesoDisciplinarioResponse,
)
def actualizar_cierre(
    id_cierre: int,
    data: CierreProcesoDisciplinarioUpdate,
    db: Session = Depends(get_db),
):
    """
    Actualiza un cierre únicamente cuando el proceso
    todavía se encuentre abierto.

    Como la creación del cierre cambia el proceso a CERRADO,
    posteriormente el expediente queda bloqueado.
    """

    cierre = (
        db.query(CierreProcesoDisciplinario)
        .filter(
            CierreProcesoDisciplinario
            .IdCierreProcesoDisciplinario
            == id_cierre
        )
        .first()
    )

    if not cierre:
        raise HTTPException(
            status_code=404,
            detail="Cierre no encontrado",
        )

    proceso = obtener_proceso_o_error(
        db=db,
        id_proceso=cierre.IdProcesoDisciplinario,
    )

    validar_proceso_abierto(proceso)

    datos_actualizacion = data.model_dump(
        exclude_unset=True
    )

    for campo, valor in datos_actualizacion.items():
        setattr(
            cierre,
            campo,
            valor,
        )

    cierre.FechaActualizacion = datetime.now()

    try:
        sincronizar_cierre_con_agenda(
            db=db,
            id_proceso_disciplinario=(
                cierre.IdProcesoDisciplinario
            ),
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
                "No se pudo actualizar el cierre ni "
                "sincronizar la agenda disciplinaria."
            ),
        ) from error