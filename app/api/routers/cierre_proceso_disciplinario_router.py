from datetime import datetime, timedelta, timezone

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
)
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
    CierreProcesoDisciplinarioResponse,
    CierreProcesoDisciplinarioUpdate,
)


router = APIRouter(
    prefix="/api/cierre-proceso-disciplinario",
    tags=["Cierre Proceso Disciplinario"],
)


ZONA_COLOMBIA = timezone(
    timedelta(hours=-5)
)


def ahora_colombia() -> datetime:
    return datetime.now(
        ZONA_COLOMBIA
    )


def obtener_proceso_o_error(
    db: Session,
    id_proceso: int,
) -> ProcesoDisciplinario:
    proceso = (
        db.query(
            ProcesoDisciplinario
        )
        .filter(
            ProcesoDisciplinario
            .IdProcesoDisciplinario
            == id_proceso
        )
        .first()
    )

    if not proceso:
        raise HTTPException(
            status_code=404,
            detail={
                "mensaje": (
                    "Proceso disciplinario "
                    "no encontrado."
                ),
                "IdProcesoDisciplinario":
                    id_proceso,
            },
        )

    return proceso


def validar_proceso_abierto(
    proceso: ProcesoDisciplinario,
) -> None:
    estado = str(
        proceso.EstadoProceso or ""
    ).strip().upper()

    if estado == "CERRADO":
        raise HTTPException(
            status_code=409,
            detail={
                "mensaje": (
                    "El proceso disciplinario "
                    "ya fue cerrado y no admite "
                    "modificaciones."
                ),
                "IdProcesoDisciplinario": (
                    proceso
                    .IdProcesoDisciplinario
                ),
                "EstadoProceso":
                    proceso.EstadoProceso,
            },
        )


def obtener_cierre_o_error(
    db: Session,
    id_cierre: int,
) -> CierreProcesoDisciplinario:
    cierre = (
        db.query(
            CierreProcesoDisciplinario
        )
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
            detail="Cierre no encontrado.",
        )

    return cierre


def validar_cierre_completo(
    cierre: CierreProcesoDisciplinario,
) -> None:
    tipo = str(
        cierre.TipoCierre or ""
    ).strip().upper()

    conclusion = str(
        cierre.ConclusionRRLL or ""
    ).strip()

    responsable = str(
        cierre.ResponsableCierre or ""
    ).strip()

    medida = str(
        cierre.MedidaDisciplinaria or ""
    ).strip()

    errores = []

    if tipo not in {
        "CON_MEDIDA_DISCIPLINARIA",
        "SIN_MEDIDA_DISCIPLINARIA",
        "ARCHIVO_DEL_PROCESO",
    }:
        errores.append(
            "Debe seleccionar un tipo de cierre."
        )

    if not cierre.FechaCierre:
        errores.append(
            "La fecha de cierre es obligatoria."
        )

    if not responsable:
        errores.append(
            "El responsable del cierre "
            "es obligatorio."
        )

    if not conclusion:
        errores.append(
            "La conclusión de Relaciones "
            "Laborales es obligatoria."
        )

    if (
        tipo == "CON_MEDIDA_DISCIPLINARIA"
        and not medida
    ):
        errores.append(
            "Debe registrar la medida "
            "disciplinaria."
        )

    if errores:
        raise HTTPException(
            status_code=422,
            detail={
                "mensaje": errores[0],
                "errores": errores,
            },
        )


def sincronizar_cierre_con_agenda(
    db: Session,
    proceso: ProcesoDisciplinario,
    usuario: str,
) -> None:
    fecha_actualizacion = (
        ahora_colombia()
    )

    proceso.EstadoProceso = "CERRADO"
    proceso.FechaActualizacion = (
        fecha_actualizacion
    )
    proceso.UsuarioActualizacion = (
        usuario
    )

    eventos = (
        db.query(
            AgendaProcesoDisciplinario
        )
        .filter(
            AgendaProcesoDisciplinario
            .IdProcesoDisciplinario
            == proceso
            .IdProcesoDisciplinario,
            AgendaProcesoDisciplinario
            .Activo.is_(True),
        )
        .all()
    )

    for evento in eventos:
        evento.EstadoAgenda = "ATENDIDO"
        evento.ColorAgenda = "VERDE"
        evento.FechaActualizacion = (
            fecha_actualizacion
        )
        evento.UsuarioActualizacion = (
            usuario
        )


@router.post(
    "/",
    response_model=(
        CierreProcesoDisciplinarioResponse
    ),
)
def crear_borrador_cierre(
    data: CierreProcesoDisciplinarioCreate,
    db: Session = Depends(get_db),
):
    proceso = obtener_proceso_o_error(
        db=db,
        id_proceso=(
            data.IdProcesoDisciplinario
        ),
    )

    validar_proceso_abierto(
        proceso
    )

    cierre_existente = (
        db.query(
            CierreProcesoDisciplinario
        )
        .filter(
            CierreProcesoDisciplinario
            .IdProcesoDisciplinario
            == data.IdProcesoDisciplinario
        )
        .first()
    )

    if cierre_existente:
        raise HTTPException(
            status_code=409,
            detail={
                "mensaje": (
                    "El proceso ya tiene un "
                    "borrador de cierre."
                ),
                "IdCierreProcesoDisciplinario":
                    cierre_existente
                    .IdCierreProcesoDisciplinario,
            },
        )

    nuevo = (
        CierreProcesoDisciplinario(
            **data.model_dump()
        )
    )

    nuevo.FechaActualizacion = (
        ahora_colombia()
    )

    try:
        db.add(
            nuevo
        )
        db.commit()
        db.refresh(
            nuevo
        )

        return nuevo

    except SQLAlchemyError as error:
        db.rollback()

        raise HTTPException(
            status_code=500,
            detail=(
                "No se pudo guardar el "
                "borrador del cierre."
            ),
        ) from error


@router.get(
    "/proceso/{id_proceso}",
    response_model=(
        CierreProcesoDisciplinarioResponse
    ),
)
def obtener_cierre_por_proceso(
    id_proceso: int,
    db: Session = Depends(get_db),
):
    obtener_proceso_o_error(
        db=db,
        id_proceso=id_proceso,
    )

    cierre = (
        db.query(
            CierreProcesoDisciplinario
        )
        .filter(
            CierreProcesoDisciplinario
            .IdProcesoDisciplinario
            == id_proceso
        )
        .first()
    )

    if not cierre:
        raise HTTPException(
            status_code=404,
            detail={
                "mensaje": (
                    "El proceso disciplinario "
                    "no tiene borrador de cierre."
                ),
                "IdProcesoDisciplinario":
                    id_proceso,
            },
        )

    return cierre


@router.get(
    "/{id_cierre}",
    response_model=(
        CierreProcesoDisciplinarioResponse
    ),
)
def obtener_cierre(
    id_cierre: int,
    db: Session = Depends(get_db),
):
    return obtener_cierre_o_error(
        db=db,
        id_cierre=id_cierre,
    )


@router.put(
    "/{id_cierre}",
    response_model=(
        CierreProcesoDisciplinarioResponse
    ),
)
def actualizar_borrador_cierre(
    id_cierre: int,
    data: CierreProcesoDisciplinarioUpdate,
    db: Session = Depends(get_db),
):
    cierre = obtener_cierre_o_error(
        db=db,
        id_cierre=id_cierre,
    )

    proceso = obtener_proceso_o_error(
        db=db,
        id_proceso=(
            cierre.IdProcesoDisciplinario
        ),
    )

    validar_proceso_abierto(
        proceso
    )

    cambios = data.model_dump(
        exclude_unset=True
    )

    for campo, valor in cambios.items():
        setattr(
            cierre,
            campo,
            valor,
        )

    cierre.FechaActualizacion = (
        ahora_colombia()
    )

    try:
        db.commit()
        db.refresh(
            cierre
        )

        return cierre

    except SQLAlchemyError as error:
        db.rollback()

        raise HTTPException(
            status_code=500,
            detail=(
                "No se pudo actualizar el "
                "borrador del cierre."
            ),
        ) from error


@router.post(
    "/{id_cierre}/finalizar",
    response_model=(
        CierreProcesoDisciplinarioResponse
    ),
)
def finalizar_cierre(
    id_cierre: int,
    db: Session = Depends(get_db),
):
    cierre = obtener_cierre_o_error(
        db=db,
        id_cierre=id_cierre,
    )

    proceso = obtener_proceso_o_error(
        db=db,
        id_proceso=(
            cierre.IdProcesoDisciplinario
        ),
    )

    validar_proceso_abierto(
        proceso
    )

    validar_cierre_completo(
        cierre
    )

    usuario = (
        str(
            cierre.ResponsableCierre
            or "rrll"
        ).strip()
        or "rrll"
    )

    if (
        cierre.TipoCierre
        in {
            "SIN_MEDIDA_DISCIPLINARIA",
            "ARCHIVO_DEL_PROCESO",
        }
        and not str(
            cierre.MedidaDisciplinaria
            or ""
        ).strip()
    ):
        cierre.MedidaDisciplinaria = (
            "Sin medida disciplinaria"
        )

    cierre.FechaActualizacion = (
        ahora_colombia()
    )

    sincronizar_cierre_con_agenda(
        db=db,
        proceso=proceso,
        usuario=usuario,
    )

    try:
        db.commit()
        db.refresh(
            cierre
        )

        return cierre

    except SQLAlchemyError as error:
        db.rollback()

        raise HTTPException(
            status_code=500,
            detail=(
                "No se pudo finalizar el "
                "proceso disciplinario."
            ),
        ) from error