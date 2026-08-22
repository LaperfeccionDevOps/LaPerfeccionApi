# ruff: noqa: B008

from datetime import date, time

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from domain.models.proceso_disciplinario import (
    ProcesoDisciplinario,
)
from domain.schemas.autorizacion_agenda_disciplinaria_schema import (
    AutorizacionAgendaDisciplinariaAnular,
    AutorizacionAgendaDisciplinariaCreate,
    AutorizacionAgendaDisciplinariaResponse,
)
from infrastructure.db.deps import get_db
from repositories.autorizacion_agenda_disciplinaria_repo import (
    anular_autorizacion,
    buscar_autorizacion_activa,
    crear_autorizacion,
    listar_autorizaciones,
    listar_autorizaciones_por_proceso,
    marcar_autorizaciones_vencidas,
    obtener_autorizacion_por_id,
)


router = APIRouter(
    prefix="/api/autorizaciones-agenda-disciplinaria",
    tags=["Autorizaciones Agenda Disciplinaria"],
)


HORARIOS_AUTORIZABLES = {
    time(7, 10): time(7, 50),
    time(7, 50): time(8, 30),
    time(8, 30): time(9, 10),
    time(9, 10): time(9, 50),
    time(9, 50): time(10, 30),
    time(10, 30): time(11, 10),
    time(11, 10): time(11, 50),
    time(11, 50): time(12, 30),
    time(14, 0): time(14, 40),
    time(14, 40): time(15, 20),
    time(15, 20): time(16, 0),
}


ESTADOS_PERMITIDOS = {
    "ACTIVA",
    "UTILIZADA",
    "ANULADA",
    "VENCIDA",
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
                    "No se puede autorizar una citación "
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
    fecha_autorizada: date,
) -> None:
    if fecha_autorizada.weekday() != 4:
        raise HTTPException(
            status_code=400,
            detail={
                "codigo": "FECHA_NO_ES_VIERNES",
                "mensaje": (
                    "La autorización excepcional de este "
                    "módulo solo puede registrarse para "
                    "fechas que correspondan a un viernes."
                ),
                "FechaAutorizada": (
                    fecha_autorizada.strftime(
                        "%d/%m/%Y"
                    )
                ),
            },
        )


def validar_fecha_no_vencida(
    fecha_autorizada: date,
) -> None:
    from repositories.autorizacion_agenda_disciplinaria_repo import (
        obtener_ahora_colombia,
    )

    fecha_actual = obtener_ahora_colombia().date()

    if fecha_autorizada < fecha_actual:
        raise HTTPException(
            status_code=400,
            detail={
                "codigo": "FECHA_AUTORIZACION_VENCIDA",
                "mensaje": (
                    "No se puede registrar una autorización "
                    "para una fecha anterior al día actual."
                ),
                "FechaServidor": (
                    fecha_actual.strftime("%d/%m/%Y")
                ),
                "FechaAutorizada": (
                    fecha_autorizada.strftime(
                        "%d/%m/%Y"
                    )
                ),
            },
        )


def validar_bloque_autorizado(
    hora_inicio: time,
    hora_fin: time,
) -> None:
    hora_fin_esperada = HORARIOS_AUTORIZABLES.get(
        hora_inicio
    )

    if (
        hora_fin_esperada is None
        or hora_fin != hora_fin_esperada
    ):
        horarios = [
            {
                "HoraInicio": inicio.strftime("%H:%M"),
                "HoraFin": fin.strftime("%H:%M"),
                "Etiqueta": (
                    f"{inicio.strftime('%H:%M')} "
                    f"- {fin.strftime('%H:%M')}"
                ),
            }
            for inicio, fin
            in HORARIOS_AUTORIZABLES.items()
        ]

        raise HTTPException(
            status_code=400,
            detail={
                "codigo": "HORARIO_NO_PERMITIDO",
                "mensaje": (
                    "La autorización debe corresponder "
                    "a uno de los bloques habilitados "
                    "de 40 minutos."
                ),
                "HorariosPermitidos": horarios,
            },
        )


def validar_tipo_autorizacion(
    tipo_autorizacion: str,
) -> None:
    tipo = str(
        tipo_autorizacion or ""
    ).strip().upper()

    if tipo != "VIERNES":
        raise HTTPException(
            status_code=400,
            detail={
                "codigo": "TIPO_AUTORIZACION_INVALIDO",
                "mensaje": (
                    "Por ahora únicamente se permiten "
                    "autorizaciones excepcionales de viernes."
                ),
                "TipoAutorizacionIngresado": (
                    tipo_autorizacion
                ),
            },
        )


@router.get("/configuracion")
def obtener_configuracion_autorizaciones():
    return {
        "tipoAutorizacion": "VIERNES",
        "estadosPermitidos": sorted(
            ESTADOS_PERMITIDOS
        ),
        "horariosPermitidos": [
            {
                "HoraInicio": inicio.strftime("%H:%M"),
                "HoraFin": fin.strftime("%H:%M"),
                "Etiqueta": (
                    f"{inicio.strftime('%H:%M')} "
                    f"- {fin.strftime('%H:%M')}"
                ),
            }
            for inicio, fin
            in HORARIOS_AUTORIZABLES.items()
        ],
        "duracionMinutos": 40,
        "horaAlmuerzo": "13:00 - 14:00",
        "horaFinJornada": "16:00",
        "requiereExpediente": True,
        "requiereTrabajador": True,
        "usoUnico": True,
    }


@router.post(
    "/",
    response_model=(
        AutorizacionAgendaDisciplinariaResponse
    ),
    status_code=201,
)
def registrar_autorizacion_excepcional(
    data: AutorizacionAgendaDisciplinariaCreate,
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

    validar_tipo_autorizacion(
        data.TipoAutorizacion
    )

    validar_fecha_viernes(
        data.FechaAutorizada
    )

    validar_fecha_no_vencida(
        data.FechaAutorizada
    )

    validar_bloque_autorizado(
        hora_inicio=data.HoraInicio,
        hora_fin=data.HoraFin,
    )

    try:
        return crear_autorizacion(
            db=db,
            data=data,
        )

    except ValueError as error:
        raise HTTPException(
            status_code=409,
            detail={
                "codigo": (
                    "AUTORIZACION_DUPLICADA"
                ),
                "mensaje": str(error),
            },
        ) from error

    except SQLAlchemyError as error:
        raise HTTPException(
            status_code=500,
            detail={
                "codigo": (
                    "ERROR_CREAR_AUTORIZACION"
                ),
                "mensaje": (
                    "No fue posible crear la "
                    "autorización excepcional."
                ),
            },
        ) from error


@router.get(
    "/",
    response_model=list[
        AutorizacionAgendaDisciplinariaResponse
    ],
)
def consultar_autorizaciones(
    estado_autorizacion: str | None = Query(
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
    if estado_autorizacion:
        estado = estado_autorizacion.strip().upper()

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

        estado_autorizacion = estado

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
        marcar_autorizaciones_vencidas(
            db=db
        )

        return listar_autorizaciones(
            db=db,
            estado_autorizacion=(
                estado_autorizacion
            ),
            fecha_desde=fecha_desde,
            fecha_hasta=fecha_hasta,
            id_proceso_disciplinario=(
                id_proceso_disciplinario
            ),
            id_registro_personal=(
                id_registro_personal
            ),
            incluir_inactivas=(
                incluir_inactivas
            ),
        )

    except SQLAlchemyError as error:
        raise HTTPException(
            status_code=500,
            detail={
                "codigo": (
                    "ERROR_LISTAR_AUTORIZACIONES"
                ),
                "mensaje": (
                    "No fue posible consultar las "
                    "autorizaciones excepcionales."
                ),
            },
        ) from error


@router.get(
    "/proceso/{id_proceso_disciplinario}",
    response_model=list[
        AutorizacionAgendaDisciplinariaResponse
    ],
)
def consultar_autorizaciones_por_proceso(
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
        marcar_autorizaciones_vencidas(
            db=db
        )

        return listar_autorizaciones_por_proceso(
            db=db,
            id_proceso_disciplinario=(
                id_proceso_disciplinario
            ),
            incluir_inactivas=(
                incluir_inactivas
            ),
        )

    except SQLAlchemyError as error:
        raise HTTPException(
            status_code=500,
            detail={
                "codigo": (
                    "ERROR_CONSULTAR_AUTORIZACIONES"
                ),
                "mensaje": (
                    "No fue posible consultar las "
                    "autorizaciones del expediente."
                ),
            },
        ) from error


@router.get(
    "/validar",
)
def validar_autorizacion_excepcional(
    id_registro_personal: int = Query(
        ...
    ),
    id_proceso_disciplinario: int = Query(
        ...
    ),
    fecha_autorizada: date = Query(
        ...
    ),
    hora_inicio: time = Query(
        ...
    ),
    hora_fin: time = Query(
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
        fecha_autorizada
    )

    validar_bloque_autorizado(
        hora_inicio=hora_inicio,
        hora_fin=hora_fin,
    )

    try:
        marcar_autorizaciones_vencidas(
            db=db
        )

        autorizacion = buscar_autorizacion_activa(
            db=db,
            id_registro_personal=(
                id_registro_personal
            ),
            id_proceso_disciplinario=(
                id_proceso_disciplinario
            ),
            fecha_autorizada=(
                fecha_autorizada
            ),
            hora_inicio=hora_inicio,
            hora_fin=hora_fin,
        )

        return {
            "autorizado": (
                autorizacion is not None
            ),
            "requiereAutorizacion": True,
            "codigo": (
                "AUTORIZACION_ACTIVA"
                if autorizacion
                else "AUTORIZACION_NO_ENCONTRADA"
            ),
            "mensaje": (
                "Existe una autorización activa para "
                "el viernes y horario seleccionados."
                if autorizacion
                else (
                    "No existe una autorización activa "
                    "para el viernes y horario "
                    "seleccionados."
                )
            ),
            "autorizacion": (
                AutorizacionAgendaDisciplinariaResponse
                .model_validate(
                    autorizacion
                )
                if autorizacion
                else None
            ),
        }

    except SQLAlchemyError as error:
        raise HTTPException(
            status_code=500,
            detail={
                "codigo": (
                    "ERROR_VALIDAR_AUTORIZACION"
                ),
                "mensaje": (
                    "No fue posible validar la "
                    "autorización excepcional."
                ),
            },
        ) from error


@router.put(
    "/{id_autorizacion}/anular",
    response_model=(
        AutorizacionAgendaDisciplinariaResponse
    ),
)
def anular_autorizacion_excepcional(
    id_autorizacion: int,
    data: AutorizacionAgendaDisciplinariaAnular,
    db: Session = Depends(get_db),
):
    autorizacion = obtener_autorizacion_por_id(
        db=db,
        id_autorizacion=id_autorizacion,
    )

    if not autorizacion:
        raise HTTPException(
            status_code=404,
            detail={
                "codigo": (
                    "AUTORIZACION_NO_ENCONTRADA"
                ),
                "mensaje": (
                    "No se encontró la autorización "
                    "excepcional indicada."
                ),
                "IdAutorizacionAgendaDisciplinaria": (
                    id_autorizacion
                ),
            },
        )

    try:
        return anular_autorizacion(
            db=db,
            id_autorizacion=id_autorizacion,
            motivo_anulacion=(
                data.MotivoAnulacion
            ),
            usuario_anula=(
                data.UsuarioAnula
            ),
        )

    except ValueError as error:
        raise HTTPException(
            status_code=409,
            detail={
                "codigo": (
                    "AUTORIZACION_NO_ANULABLE"
                ),
                "mensaje": str(error),
            },
        ) from error

    except SQLAlchemyError as error:
        raise HTTPException(
            status_code=500,
            detail={
                "codigo": (
                    "ERROR_ANULAR_AUTORIZACION"
                ),
                "mensaje": (
                    "No fue posible anular la "
                    "autorización excepcional."
                ),
            },
        ) from error


@router.get(
    "/{id_autorizacion}",
    response_model=(
        AutorizacionAgendaDisciplinariaResponse
    ),
)
def consultar_autorizacion_por_id(
    id_autorizacion: int,
    db: Session = Depends(get_db),
):
    try:
        marcar_autorizaciones_vencidas(
            db=db
        )

        autorizacion = obtener_autorizacion_por_id(
            db=db,
            id_autorizacion=id_autorizacion,
        )

        if not autorizacion:
            raise HTTPException(
                status_code=404,
                detail={
                    "codigo": (
                        "AUTORIZACION_NO_ENCONTRADA"
                    ),
                    "mensaje": (
                        "No se encontró la autorización "
                        "excepcional indicada."
                    ),
                    "IdAutorizacionAgendaDisciplinaria": (
                        id_autorizacion
                    ),
                },
            )

        return autorizacion

    except HTTPException:
        raise

    except SQLAlchemyError as error:
        raise HTTPException(
            status_code=500,
            detail={
                "codigo": (
                    "ERROR_CONSULTAR_AUTORIZACION"
                ),
                "mensaje": (
                    "No fue posible consultar la "
                    "autorización excepcional."
                ),
            },
        ) from error