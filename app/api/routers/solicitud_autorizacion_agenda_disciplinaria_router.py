# ruff: noqa: B008

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from domain.models.aspirante import RegistroPersonal
from domain.models.proceso_disciplinario import (
    ProcesoDisciplinario,
)
from domain.schemas.solicitud_autorizacion_agenda_disciplinaria_schema import (
    SolicitudAutorizacionAgendaDisciplinariaAprobar,
    SolicitudAutorizacionAgendaDisciplinariaCancelar,
    SolicitudAutorizacionAgendaDisciplinariaCreate,
    SolicitudAutorizacionAgendaDisciplinariaRechazar,
    SolicitudAutorizacionAgendaDisciplinariaResponse,
)
from infrastructure.db.deps import get_db
from repositories.solicitud_autorizacion_agenda_disciplinaria_repo import (
    aprobar_solicitud,
    cancelar_solicitud,
    crear_solicitud,
    listar_solicitudes,
    listar_solicitudes_pendientes,
    listar_solicitudes_por_proceso,
    listar_solicitudes_por_trabajador,
    obtener_solicitud_pendiente,
    obtener_solicitud_por_id,
    rechazar_solicitud,
)


router = APIRouter(
    prefix="/api/solicitudes-autorizacion-agenda-disciplinaria",
    tags=["Solicitudes Autorización Agenda Disciplinaria"],
)



ESTADOS_PERMITIDOS = {
    "PENDIENTE",
    "APROBADA",
    "RECHAZADA",
    "CANCELADA",
}


def obtener_proceso_o_error(
    db: Session,
    id_proceso_disciplinario: int,
) -> ProcesoDisciplinario:
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
            detail={
                "codigo": "PROCESO_NO_ENCONTRADO",
                "mensaje": (
                    "No se encontró el expediente "
                    "disciplinario indicado."
                ),
                "IdProcesoDisciplinario": (
                    id_proceso_disciplinario
                ),
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
                "codigo": "PROCESO_CERRADO",
                "mensaje": (
                    "No se puede solicitar autorización "
                    "para un expediente cerrado."
                ),
                "IdProcesoDisciplinario": (
                    proceso.IdProcesoDisciplinario
                ),
                "EstadoProceso": proceso.EstadoProceso,
            },
        )


def validar_trabajador_del_proceso(
    proceso: ProcesoDisciplinario,
    id_registro_personal: int,
) -> None:
    if (
        int(proceso.IdRegistroPersonal)
        != int(id_registro_personal)
    ):
        raise HTTPException(
            status_code=409,
            detail={
                "codigo": "TRABAJADOR_NO_CORRESPONDE",
                "mensaje": (
                    "El trabajador indicado no corresponde "
                    "al expediente disciplinario seleccionado."
                ),
                "IdProcesoDisciplinario": (
                    proceso.IdProcesoDisciplinario
                ),
                "IdRegistroPersonalProceso": (
                    proceso.IdRegistroPersonal
                ),
                "IdRegistroPersonalIngresado": (
                    id_registro_personal
                ),
            },
        )


def validar_fecha_viernes(
    fecha_solicitada: date,
) -> None:
    if fecha_solicitada.weekday() != 4:
        raise HTTPException(
            status_code=400,
            detail={
                "codigo": "FECHA_NO_ES_VIERNES",
                "mensaje": (
                    "La solicitud excepcional solo puede "
                    "registrarse para fechas que correspondan "
                    "a un viernes."
                ),
                "FechaSolicitada": (
                    fecha_solicitada.strftime("%d/%m/%Y")
                ),
            },
        )


@router.get("/configuracion")
def obtener_configuracion_solicitudes():
    return {
        "estadosPermitidos": sorted(
            ESTADOS_PERMITIDOS
        ),
        "flujo": (
            "Operaciones solicita un viernes y Relaciones "
            "Laborales aprueba o rechaza la fecha. "
            "El horario lo selecciona posteriormente Operaciones."
        ),
    }


@router.post(
    "/",
    response_model=(
        SolicitudAutorizacionAgendaDisciplinariaResponse
    ),
    status_code=201,
)
def registrar_solicitud(
    data: SolicitudAutorizacionAgendaDisciplinariaCreate,
    db: Session = Depends(get_db),
):
    proceso = obtener_proceso_o_error(
        db=db,
        id_proceso_disciplinario=(
            data.IdProcesoDisciplinario
        ),
    )

    validar_proceso_abierto(
        proceso
    )

    validar_trabajador_del_proceso(
        proceso=proceso,
        id_registro_personal=(
            data.IdRegistroPersonal
        ),
    )

    validar_fecha_viernes(
        data.FechaSolicitada
    )

    try:
        return crear_solicitud(
            db=db,
            data=data,
        )

    except ValueError as error:
        raise HTTPException(
            status_code=409,
            detail={
                "codigo": "SOLICITUD_NO_CREADA",
                "mensaje": str(error),
            },
        ) from error

    except SQLAlchemyError as error:
        raise HTTPException(
            status_code=500,
            detail={
                "codigo": "ERROR_CREAR_SOLICITUD",
                "mensaje": (
                    "No fue posible crear la solicitud "
                    "de autorización."
                ),
            },
        ) from error


@router.get(
    "/",
    response_model=list[
        SolicitudAutorizacionAgendaDisciplinariaResponse
    ],
)
def consultar_solicitudes(
    estado_solicitud: str | None = Query(
        default=None
    ),
    fecha_desde: date | None = Query(
        default=None
    ),
    fecha_hasta: date | None = Query(
        default=None
    ),
    id_proceso_disciplinario: int | None = Query(
        default=None
    ),
    id_registro_personal: int | None = Query(
        default=None
    ),
    incluir_inactivas: bool = Query(
        default=False
    ),
    db: Session = Depends(get_db),
):
    if estado_solicitud:
        estado = estado_solicitud.strip().upper()

        if estado not in ESTADOS_PERMITIDOS:
            raise HTTPException(
                status_code=400,
                detail={
                    "codigo": "ESTADO_INVALIDO",
                    "mensaje": (
                        "El estado consultado no es válido."
                    ),
                    "EstadosPermitidos": sorted(
                        ESTADOS_PERMITIDOS
                    ),
                },
            )

        estado_solicitud = estado

    if (
        fecha_desde is not None
        and fecha_hasta is not None
        and fecha_desde > fecha_hasta
    ):
        raise HTTPException(
            status_code=400,
            detail={
                "codigo": "RANGO_FECHAS_INVALIDO",
                "mensaje": (
                    "La fecha inicial no puede ser "
                    "mayor que la fecha final."
                ),
            },
        )

    try:
        return listar_solicitudes(
            db=db,
            estado_solicitud=estado_solicitud,
            fecha_desde=fecha_desde,
            fecha_hasta=fecha_hasta,
            id_proceso_disciplinario=(
                id_proceso_disciplinario
            ),
            id_registro_personal=(
                id_registro_personal
            ),
            incluir_inactivas=incluir_inactivas,
        )

    except SQLAlchemyError as error:
        raise HTTPException(
            status_code=500,
            detail={
                "codigo": "ERROR_LISTAR_SOLICITUDES",
                "mensaje": (
                    "No fue posible consultar las "
                    "solicitudes de autorización."
                ),
            },
        ) from error


@router.get(
    "/pendientes",
    response_model=list[
        SolicitudAutorizacionAgendaDisciplinariaResponse
    ],
)
def consultar_solicitudes_pendientes(
    db: Session = Depends(get_db),
):
    try:
        solicitudes = listar_solicitudes_pendientes(
            db=db
        )

        ids_trabajadores = {
            int(solicitud.IdRegistroPersonal)
            for solicitud in solicitudes
            if solicitud.IdRegistroPersonal is not None
        }

        trabajadores = []

        if ids_trabajadores:
            trabajadores = (
                db.query(RegistroPersonal)
                .filter(
                    RegistroPersonal.IdRegistroPersonal.in_(
                        ids_trabajadores
                    )
                )
                .all()
            )

        trabajadores_por_id = {
            int(trabajador.IdRegistroPersonal): trabajador
            for trabajador in trabajadores
        }

        tipos_documento = {
            1: "CC",
            2: "CE",
            3: "PPT",
            4: "TI",
        }

        respuesta = []

        for solicitud in solicitudes:
            datos = (
                SolicitudAutorizacionAgendaDisciplinariaResponse
                .model_validate(solicitud)
                .model_dump()
            )

            trabajador = trabajadores_por_id.get(
                int(solicitud.IdRegistroPersonal)
            )

            if trabajador:
                nombre_completo = (
                    f"{trabajador.Nombres or ''} "
                    f"{trabajador.Apellidos or ''}"
                ).strip()

                datos["NombreCompleto"] = (
                    nombre_completo or None
                )
                datos["NumeroDocumento"] = (
                    trabajador.NumeroIdentificacion
                )
                datos["TipoDocumento"] = (
                    tipos_documento.get(
                        int(
                            trabajador.IdTipoIdentificacion
                            or 0
                        ),
                        "CC",
                    )
                )

            respuesta.append(datos)

        return respuesta

    except SQLAlchemyError as error:
        raise HTTPException(
            status_code=500,
            detail={
                "codigo": "ERROR_LISTAR_PENDIENTES",
                "mensaje": (
                    "No fue posible consultar las "
                    "solicitudes pendientes."
                ),
            },
        ) from error


@router.get(
    "/proceso/{id_proceso_disciplinario}",
    response_model=list[
        SolicitudAutorizacionAgendaDisciplinariaResponse
    ],
)
def consultar_solicitudes_por_proceso(
    id_proceso_disciplinario: int,
    incluir_inactivas: bool = Query(
        default=True
    ),
    db: Session = Depends(get_db),
):
    obtener_proceso_o_error(
        db=db,
        id_proceso_disciplinario=(
            id_proceso_disciplinario
        ),
    )

    try:
        return listar_solicitudes_por_proceso(
            db=db,
            id_proceso_disciplinario=(
                id_proceso_disciplinario
            ),
            incluir_inactivas=incluir_inactivas,
        )

    except SQLAlchemyError as error:
        raise HTTPException(
            status_code=500,
            detail={
                "codigo": (
                    "ERROR_CONSULTAR_SOLICITUDES_PROCESO"
                ),
                "mensaje": (
                    "No fue posible consultar las "
                    "solicitudes del expediente."
                ),
            },
        ) from error


@router.get(
    "/trabajador/{id_registro_personal}",
    response_model=list[
        SolicitudAutorizacionAgendaDisciplinariaResponse
    ],
)
def consultar_solicitudes_por_trabajador(
    id_registro_personal: int,
    incluir_inactivas: bool = Query(
        default=True
    ),
    db: Session = Depends(get_db),
):
    try:
        return listar_solicitudes_por_trabajador(
            db=db,
            id_registro_personal=(
                id_registro_personal
            ),
            incluir_inactivas=incluir_inactivas,
        )

    except SQLAlchemyError as error:
        raise HTTPException(
            status_code=500,
            detail={
                "codigo": (
                    "ERROR_CONSULTAR_SOLICITUDES_TRABAJADOR"
                ),
                "mensaje": (
                    "No fue posible consultar las "
                    "solicitudes del trabajador."
                ),
            },
        ) from error


@router.get(
    "/trabajador/{id_registro_personal}/pendiente",
    response_model=(
        SolicitudAutorizacionAgendaDisciplinariaResponse
        | None
    ),
)
def consultar_solicitud_pendiente_trabajador(
    id_registro_personal: int,
    id_proceso_disciplinario: int = Query(
        ...
    ),
    fecha_solicitada: date = Query(
        ...
    ),
    db: Session = Depends(get_db),
):
    proceso = obtener_proceso_o_error(
        db=db,
        id_proceso_disciplinario=(
            id_proceso_disciplinario
        ),
    )

    validar_trabajador_del_proceso(
        proceso=proceso,
        id_registro_personal=(
            id_registro_personal
        ),
    )

    validar_fecha_viernes(
        fecha_solicitada
    )

    try:
        return obtener_solicitud_pendiente(
            db=db,
            id_registro_personal=(
                id_registro_personal
            ),
            id_proceso_disciplinario=(
                id_proceso_disciplinario
            ),
            fecha_solicitada=fecha_solicitada,
        )

    except SQLAlchemyError as error:
        raise HTTPException(
            status_code=500,
            detail={
                "codigo": (
                    "ERROR_CONSULTAR_SOLICITUD_PENDIENTE"
                ),
                "mensaje": (
                    "No fue posible consultar la "
                    "solicitud pendiente."
                ),
            },
        ) from error


@router.put(
    "/{id_solicitud}/aprobar",
    response_model=(
        SolicitudAutorizacionAgendaDisciplinariaResponse
    ),
)
def aprobar_solicitud_rrll(
    id_solicitud: int,
    data: SolicitudAutorizacionAgendaDisciplinariaAprobar,
    db: Session = Depends(get_db),
):
    solicitud = obtener_solicitud_por_id(
        db=db,
        id_solicitud=id_solicitud,
    )

    if not solicitud:
        raise HTTPException(
            status_code=404,
            detail={
                "codigo": "SOLICITUD_NO_ENCONTRADA",
                "mensaje": (
                    "No se encontró la solicitud indicada."
                ),
                "IdSolicitudAutorizacion": id_solicitud,
            },
        )

    proceso = obtener_proceso_o_error(
        db=db,
        id_proceso_disciplinario=(
            solicitud.IdProcesoDisciplinario
        ),
    )

    validar_proceso_abierto(
        proceso
    )

    try:
        return aprobar_solicitud(
            db=db,
            id_solicitud=id_solicitud,
            usuario_resuelve=data.UsuarioResuelve,
            observacion_resolucion=(
                data.ObservacionResolucion
            ),
        )

    except ValueError as error:
        raise HTTPException(
            status_code=409,
            detail={
                "codigo": "SOLICITUD_NO_APROBABLE",
                "mensaje": str(error),
            },
        ) from error

    except SQLAlchemyError as error:
        raise HTTPException(
            status_code=500,
            detail={
                "codigo": "ERROR_APROBAR_SOLICITUD",
                "mensaje": (
                    "No fue posible aprobar la solicitud."
                ),
            },
        ) from error


@router.put(
    "/{id_solicitud}/rechazar",
    response_model=(
        SolicitudAutorizacionAgendaDisciplinariaResponse
    ),
)
def rechazar_solicitud_rrll(
    id_solicitud: int,
    data: SolicitudAutorizacionAgendaDisciplinariaRechazar,
    db: Session = Depends(get_db),
):
    solicitud = obtener_solicitud_por_id(
        db=db,
        id_solicitud=id_solicitud,
    )

    if not solicitud:
        raise HTTPException(
            status_code=404,
            detail={
                "codigo": "SOLICITUD_NO_ENCONTRADA",
                "mensaje": (
                    "No se encontró la solicitud indicada."
                ),
                "IdSolicitudAutorizacion": id_solicitud,
            },
        )

    try:
        return rechazar_solicitud(
            db=db,
            id_solicitud=id_solicitud,
            usuario_resuelve=data.UsuarioResuelve,
            observacion_resolucion=(
                data.ObservacionResolucion
            ),
        )

    except ValueError as error:
        raise HTTPException(
            status_code=409,
            detail={
                "codigo": "SOLICITUD_NO_RECHAZABLE",
                "mensaje": str(error),
            },
        ) from error

    except SQLAlchemyError as error:
        raise HTTPException(
            status_code=500,
            detail={
                "codigo": "ERROR_RECHAZAR_SOLICITUD",
                "mensaje": (
                    "No fue posible rechazar la solicitud."
                ),
            },
        ) from error


@router.put(
    "/{id_solicitud}/cancelar",
    response_model=(
        SolicitudAutorizacionAgendaDisciplinariaResponse
    ),
)
def cancelar_solicitud_operaciones(
    id_solicitud: int,
    data: SolicitudAutorizacionAgendaDisciplinariaCancelar,
    db: Session = Depends(get_db),
):
    solicitud = obtener_solicitud_por_id(
        db=db,
        id_solicitud=id_solicitud,
    )

    if not solicitud:
        raise HTTPException(
            status_code=404,
            detail={
                "codigo": "SOLICITUD_NO_ENCONTRADA",
                "mensaje": (
                    "No se encontró la solicitud indicada."
                ),
                "IdSolicitudAutorizacion": id_solicitud,
            },
        )

    try:
        return cancelar_solicitud(
            db=db,
            id_solicitud=id_solicitud,
            usuario_cancela=data.UsuarioCancela,
            motivo_cancelacion=data.MotivoCancelacion,
        )

    except ValueError as error:
        raise HTTPException(
            status_code=409,
            detail={
                "codigo": "SOLICITUD_NO_CANCELABLE",
                "mensaje": str(error),
            },
        ) from error

    except SQLAlchemyError as error:
        raise HTTPException(
            status_code=500,
            detail={
                "codigo": "ERROR_CANCELAR_SOLICITUD",
                "mensaje": (
                    "No fue posible cancelar la solicitud."
                ),
            },
        ) from error


@router.get(
    "/{id_solicitud}",
    response_model=(
        SolicitudAutorizacionAgendaDisciplinariaResponse
    ),
)
def consultar_solicitud_por_id(
    id_solicitud: int,
    db: Session = Depends(get_db),
):
    try:
        solicitud = obtener_solicitud_por_id(
            db=db,
            id_solicitud=id_solicitud,
        )

        if not solicitud:
            raise HTTPException(
                status_code=404,
                detail={
                    "codigo": "SOLICITUD_NO_ENCONTRADA",
                    "mensaje": (
                        "No se encontró la solicitud indicada."
                    ),
                    "IdSolicitudAutorizacion": (
                        id_solicitud
                    ),
                },
            )

        return solicitud

    except HTTPException:
        raise

    except SQLAlchemyError as error:
        raise HTTPException(
            status_code=500,
            detail={
                "codigo": "ERROR_CONSULTAR_SOLICITUD",
                "mensaje": (
                    "No fue posible consultar la solicitud."
                ),
            },
        ) from error