from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from infrastructure.db.deps import get_db

from domain.models.proceso_disciplinario import (
    ProcesoDisciplinario,
)
from domain.models.citacion_proceso_disciplinario import (
    CitacionProcesoDisciplinario,
)
from domain.models.descargo_proceso_disciplinario import (
    DescargoProcesoDisciplinario,
)
from domain.models.cierre_proceso_disciplinario import (
    CierreProcesoDisciplinario,
)
from domain.models.documento_proceso_disciplinario import (
    DocumentoProcesoDisciplinario,
)

from domain.schemas.proceso_disciplinario_schema import (
    ProcesoDisciplinarioCreate,
    ProcesoDisciplinarioUpdate,
    ProcesoDisciplinarioResponse,
)

from services.expediente_disciplinario_pdf_service import (
    generar_expediente_disciplinario_pdf,
)


router = APIRouter(
    prefix="/api/procesos-disciplinarios",
    tags=["Procesos Disciplinarios"],
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


def validar_proceso_modificable(
    proceso: ProcesoDisciplinario,
) -> None:
    estado_actual = str(
        proceso.EstadoProceso or ""
    ).strip().upper()

    if estado_actual == "CERRADO":
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


@router.post(
    "/",
    response_model=ProcesoDisciplinarioResponse,
)
def crear_proceso_disciplinario(
    data: ProcesoDisciplinarioCreate,
    db: Session = Depends(get_db),
):
    nuevo = ProcesoDisciplinario(
        IdRegistroPersonal=data.IdRegistroPersonal,
        EstadoProceso=(
            data.EstadoProceso or "INICIADO"
        ),
        OrigenProceso=(
            data.OrigenProceso or "RRLL"
        ),
        UsuarioActualizacion=(
            data.UsuarioActualizacion
        ),
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
                "No se pudo crear el proceso "
                "disciplinario."
            ),
        ) from error


@router.get(
    "/trabajador/{id_registro_personal}"
)
def listar_procesos_por_trabajador(
    id_registro_personal: int,
    db: Session = Depends(get_db),
):
    procesos = (
        db.query(ProcesoDisciplinario)
        .filter(
            ProcesoDisciplinario.IdRegistroPersonal
            == id_registro_personal
        )
        .order_by(
            ProcesoDisciplinario.FechaCreacion.desc()
        )
        .all()
    )

    return procesos


@router.get(
    "/trabajador/{id_registro_personal}/historial"
)
def obtener_historial_disciplinario_trabajador(
    id_registro_personal: int,
    db: Session = Depends(get_db),
):
    procesos = (
        db.query(ProcesoDisciplinario)
        .filter(
            ProcesoDisciplinario.IdRegistroPersonal
            == id_registro_personal
        )
        .order_by(
            ProcesoDisciplinario.FechaCreacion.desc()
        )
        .all()
    )

    historial = []

    for proceso in procesos:
        citacion = (
            db.query(
                CitacionProcesoDisciplinario
            )
            .filter(
                CitacionProcesoDisciplinario
                .IdProcesoDisciplinario
                == proceso.IdProcesoDisciplinario
            )
            .first()
        )

        descargo = (
            db.query(
                DescargoProcesoDisciplinario
            )
            .filter(
                DescargoProcesoDisciplinario
                .IdProcesoDisciplinario
                == proceso.IdProcesoDisciplinario
            )
            .first()
        )

        cierre = (
            db.query(
                CierreProcesoDisciplinario
            )
            .filter(
                CierreProcesoDisciplinario
                .IdProcesoDisciplinario
                == proceso.IdProcesoDisciplinario
            )
            .first()
        )

        historial.append(
            {
                "IdProcesoDisciplinario": (
                    proceso.IdProcesoDisciplinario
                ),
                "IdRegistroPersonal": (
                    proceso.IdRegistroPersonal
                ),
                "FechaCreacion": (
                    proceso.FechaCreacion
                ),
                "EstadoProceso": (
                    proceso.EstadoProceso
                ),
                "OrigenProceso": (
                    proceso.OrigenProceso
                ),
                "TieneCitacion": (
                    citacion is not None
                ),
                "TieneDescargo": (
                    descargo is not None
                ),
                "TieneCierre": (
                    cierre is not None
                ),
                "FechaCitacion": (
                    citacion.FechaCitacion
                    if citacion
                    else None
                ),
                "MotivoCitacion": (
                    citacion.MotivoCitacion
                    if citacion
                    else None
                ),
                "FechaDescargo": (
                    descargo.FechaDescargo
                    if descargo
                    else None
                ),
                "MedidaDisciplinaria": (
                    cierre.MedidaDisciplinaria
                    if cierre
                    else None
                ),
                "TipoCierre": (
                    cierre.TipoCierre
                    if cierre
                    else None
                ),
                "FechaCierre": (
                    cierre.FechaCierre
                    if cierre
                    else None
                ),
            }
        )

    return historial


@router.get(
    "/{id_proceso}/expediente"
)
def obtener_expediente_disciplinario(
    id_proceso: int,
    db: Session = Depends(get_db),
):
    proceso = obtener_proceso_o_error(
        db=db,
        id_proceso=id_proceso,
    )

    citacion = (
        db.query(
            CitacionProcesoDisciplinario
        )
        .filter(
            CitacionProcesoDisciplinario
            .IdProcesoDisciplinario
            == id_proceso
        )
        .first()
    )

    descargo = (
        db.query(
            DescargoProcesoDisciplinario
        )
        .filter(
            DescargoProcesoDisciplinario
            .IdProcesoDisciplinario
            == id_proceso
        )
        .first()
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

    documentos = (
        db.query(
            DocumentoProcesoDisciplinario
        )
        .filter(
            DocumentoProcesoDisciplinario
            .IdProcesoDisciplinario
            == id_proceso
        )
        .order_by(
            DocumentoProcesoDisciplinario
            .FechaCreacion.desc()
        )
        .all()
    )

    return {
        "Proceso": proceso,
        "Citacion": citacion,
        "Descargo": descargo,
        "Cierre": cierre,
        "Documentos": documentos,
    }


@router.get(
    "/{id_proceso}/pdf"
)
def generar_pdf_expediente_disciplinario(
    id_proceso: int,
    request: Request,
    db: Session = Depends(get_db),
):
    url_base = str(
        request.base_url
    ).rstrip("/")

    buffer_pdf = (
        generar_expediente_disciplinario_pdf(
            db=db,
            id_proceso=id_proceso,
            url_base=url_base,
        )
    )

    return StreamingResponse(
        buffer_pdf,
        media_type="application/pdf",
        headers={
            "Content-Disposition": (
                f'inline; filename="'
                f'expediente_disciplinario_'
                f'{id_proceso}.pdf"'
            )
        },
    )

@router.get(
    "/{id_proceso}",
    response_model=ProcesoDisciplinarioResponse,
)
def obtener_proceso_disciplinario(
    id_proceso: int,
    db: Session = Depends(get_db),
):
    return obtener_proceso_o_error(
        db=db,
        id_proceso=id_proceso,
    )


@router.put(
    "/{id_proceso}",
    response_model=ProcesoDisciplinarioResponse,
)
def actualizar_proceso_disciplinario(
    id_proceso: int,
    data: ProcesoDisciplinarioUpdate,
    db: Session = Depends(get_db),
):
    proceso = obtener_proceso_o_error(
        db=db,
        id_proceso=id_proceso,
    )

    validar_proceso_modificable(
        proceso
    )

    datos_actualizados = (
        data.model_dump(
            exclude_unset=True
        )
    )

    if "EstadoProceso" in datos_actualizados:
        estado_nuevo = (
            datos_actualizados.get(
                "EstadoProceso"
            )
        )

        if estado_nuevo is not None:
            estado_nuevo = str(
                estado_nuevo
            ).strip().upper()

            if not estado_nuevo:
                raise HTTPException(
                    status_code=400,
                    detail={
                        "mensaje": (
                            "El estado del proceso "
                            "no puede quedar vacío."
                        ),
                        "IdProcesoDisciplinario": (
                            id_proceso
                        ),
                    },
                )

            proceso.EstadoProceso = (
                estado_nuevo
            )

    if "OrigenProceso" in datos_actualizados:
        origen_nuevo = (
            datos_actualizados.get(
                "OrigenProceso"
            )
        )

        proceso.OrigenProceso = (
            str(origen_nuevo).strip()
            if origen_nuevo is not None
            else None
        )

    if (
        "UsuarioActualizacion"
        in datos_actualizados
    ):
        usuario_actualizacion = (
            datos_actualizados.get(
                "UsuarioActualizacion"
            )
        )

        proceso.UsuarioActualizacion = (
            str(
                usuario_actualizacion
            ).strip()
            if usuario_actualizacion
            is not None
            else None
        )

    proceso.FechaActualizacion = (
        datetime.now()
    )

    try:
        db.commit()
        db.refresh(proceso)

        return proceso

    except SQLAlchemyError as error:
        db.rollback()

        raise HTTPException(
            status_code=500,
            detail={
                "mensaje": (
                    "No se pudo actualizar "
                    "el proceso disciplinario."
                ),
                "IdProcesoDisciplinario": (
                    id_proceso
                ),
            },
        ) from error