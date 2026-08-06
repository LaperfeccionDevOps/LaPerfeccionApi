# ruff: noqa: B008, BLE001

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import or_, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from api.routers.agenda_proceso_disciplinario_router import (
    TIPO_EVENTO_CITACION_ID,
    calcular_hora_fin_citacion,
    validar_fecha_minima_citacion,
    validar_programacion_citacion,
)
from domain.models.agenda_proceso_disciplinario import (
    AgendaProcesoDisciplinario,
)
from domain.models.citacion_proceso_disciplinario import (
    CitacionProcesoDisciplinario,
)
from domain.models.cierre_proceso_disciplinario import (
    CierreProcesoDisciplinario,
)
from domain.models.descargo_proceso_disciplinario import (
    DescargoProcesoDisciplinario,
)
from domain.models.documento_proceso_disciplinario import (
    DocumentoProcesoDisciplinario,
)
from domain.models.proceso_disciplinario import ProcesoDisciplinario
from domain.models.solicitud_autorizacion_agenda_disciplinaria import (
    SolicitudAutorizacionAgendaDisciplinaria,
)
from domain.models.autorizacion_agenda_disciplinaria import (
    AutorizacionAgendaDisciplinaria,
)
from domain.schemas.proceso_disciplinario_schema import (
    ProcesoDisciplinarioCreate,
    ProcesoDisciplinarioResponse,
    ProcesoDisciplinarioUpdate,
)
from infrastructure.db.deps import get_db
from services.correo_proceso_disciplinario_service import (
    TIPO_CITACION_INICIAL,
    enviar_notificacion_agenda_disciplinaria,
)
from services.expediente_disciplinario_pdf_service import (
    generar_expediente_disciplinario_pdf,
)


router = APIRouter(
    prefix="/api/procesos-disciplinarios",
    tags=["Procesos Disciplinarios"],
)


ESTADOS_BORRADOR_OPERACIONES = {
    "BORRADOR_OPERACIONES",
    "PASO_2_COMPLETADO",
    "PASO_3_COMPLETADO",
}

ESTADOS_PROCESO_CERRADO = {
    "CERRADO",
}

ESTADOS_PROCESO_NO_ABIERTO = {
    "CERRADO",
    "FINALIZADO",
    "ATENDIDO",
    "ANULADO",
}

MAXIMO_PROCESOS_ABIERTOS_POR_TRABAJADOR = 2

ESTADOS_CAMBIO_PROTEGIDO = {
    "ENVIADO_A_RRLL",
    "EN_CURSO",
    "CERRADO",
}

ESTADOS_VISIBLES_RRLL_OPERACIONES = {
    "ENVIADO_A_RRLL",
    "EN_CURSO",
    "CERRADO",
}


class EnviarProcesoRRLLRequest(BaseModel):
    UsuarioActualizacion: str | None = None


def normalizar_texto(
    valor: str | None,
) -> str:
    return str(
        valor or ""
    ).strip().upper()


def intentar_enviar_citacion_inicial(
    db: Session,
    id_agenda: int,
    usuario: str | None = None,
) -> dict:
    """
    Envía la citación inicial después de confirmar el envío a RRLL.

    Un fallo de correo o trazabilidad no revierte el proceso ni la
    agenda que ya fueron guardados correctamente.
    """
    try:
        return enviar_notificacion_agenda_disciplinaria(
            db=db,
            id_agenda=id_agenda,
            tipo_notificacion=TIPO_CITACION_INICIAL,
            usuario=usuario,
        )

    except Exception as error:
        db.rollback()

        return {
            "enviado": False,
            "estado": "ERROR",
            "correo": None,
            "mensaje": str(error),
            "IdNotificacionProcesoDisciplinario": None,
        }


def formatear_codigo_expediente(
    id_proceso: int,
    fecha_creacion: datetime | None = None,
) -> str:
    anio = (
        fecha_creacion.year
        if fecha_creacion
        else datetime.now(timezone.utc).year
    )

    return f"PD-{anio}-{int(id_proceso):06d}"


def aplicar_filtro_visibilidad_rrll(
    consulta,
):
    return consulta.filter(
        or_(
            ProcesoDisciplinario
            .OrigenProceso
            != "OPERACIONES",
            ProcesoDisciplinario
            .OrigenProceso.is_(None),
            ProcesoDisciplinario
            .EstadoProceso.in_(
                list(
                    ESTADOS_VISIBLES_RRLL_OPERACIONES
                )
            ),
        )
    )


def validar_citacion_completa_para_envio(
    citacion: CitacionProcesoDisciplinario,
) -> None:
    campos_obligatorios = {
        "FechaCitacion": citacion.FechaCitacion,
        "HoraCitacion": citacion.HoraCitacion,
        "LugarCitacion": citacion.LugarCitacion,
        "Modalidad": citacion.Modalidad,
        "MotivoCitacion": citacion.MotivoCitacion,
        "RelatoHechos": citacion.RelatoHechos,
        "SupervisorReporta": citacion.SupervisorReporta,
        "Cliente": citacion.Cliente,
    }

    faltantes = [
        nombre
        for nombre, valor in campos_obligatorios.items()
        if valor is None
        or not str(valor).strip()
    ]

    if faltantes:
        raise HTTPException(
            status_code=422,
            detail={
                "mensaje": (
                    "La citación de Operaciones está "
                    "incompleta y no puede enviarse a RRLL."
                ),
                "camposFaltantes": faltantes,
            },
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
                "IdProcesoDisciplinario": (
                    id_proceso
                ),
            },
        )

    return proceso


def obtener_trabajador_o_error(
    db: Session,
    id_registro_personal: int,
) -> dict:
    """
    Consulta directamente RegistroPersonal porque en este
    proyecto no existe el módulo:

    domain.models.registro_personal
    """

    trabajador = (
        db.execute(
            text(
                """
                SELECT
                    rp."IdRegistroPersonal",
                    rp."NumeroIdentificacion",
                    rp."Nombres",
                    rp."Apellidos",
                    rp."IdEstadoProceso"
                FROM public."RegistroPersonal" rp
                WHERE
                    rp."IdRegistroPersonal"
                    = :id_registro_personal
                LIMIT 1
                """
            ),
            {
                "id_registro_personal": (
                    id_registro_personal
                )
            },
        )
        .mappings()
        .first()
    )

    if not trabajador:
        raise HTTPException(
            status_code=404,
            detail={
                "mensaje": (
                    "El trabajador indicado "
                    "no existe."
                ),
                "IdRegistroPersonal": (
                    id_registro_personal
                ),
            },
        )

    return dict(
        trabajador
    )


def validar_trabajador_contratado(
    trabajador: dict,
) -> None:
    id_estado_proceso = int(
        trabajador.get(
            "IdEstadoProceso"
        )
        or 0
    )

    if id_estado_proceso != 25:
        raise HTTPException(
            status_code=409,
            detail={
                "mensaje": (
                    "Solo se puede iniciar un "
                    "proceso disciplinario desde "
                    "Operaciones para trabajadores "
                    "contratados."
                ),
                "IdRegistroPersonal": (
                    trabajador.get(
                        "IdRegistroPersonal"
                    )
                ),
                "IdEstadoProceso": (
                    trabajador.get(
                        "IdEstadoProceso"
                    )
                ),
            },
        )


def validar_proceso_modificable(
    proceso: ProcesoDisciplinario,
) -> None:
    estado_actual = normalizar_texto(
        proceso.EstadoProceso
    )

    if estado_actual in ESTADOS_PROCESO_CERRADO:
        raise HTTPException(
            status_code=409,
            detail={
                "mensaje": (
                    "El proceso disciplinario "
                    "ya fue cerrado y no admite "
                    "modificaciones."
                ),
                "IdProcesoDisciplinario": (
                    proceso.IdProcesoDisciplinario
                ),
                "EstadoProceso": (
                    proceso.EstadoProceso
                ),
            },
        )


def contar_procesos_abiertos_trabajador(
    db: Session,
    id_registro_personal: int,
) -> int:
    """
    Cuenta únicamente registros de ProcesoDisciplinario abiertos.

    Las agendas, reprogramaciones, historiales y notificaciones
    no aumentan esta cantidad.
    """
    cantidad = (
        db.query(
            ProcesoDisciplinario
        )
        .filter(
            ProcesoDisciplinario
            .IdRegistroPersonal
            == id_registro_personal,
            ~ProcesoDisciplinario
            .EstadoProceso
            .in_(
                list(
                    ESTADOS_PROCESO_NO_ABIERTO
                )
            ),
        )
        .count()
    )

    return int(
        cantidad or 0
    )


def validar_maximo_procesos_abiertos(
    db: Session,
    id_registro_personal: int,
) -> None:
    cantidad_abiertos = (
        contar_procesos_abiertos_trabajador(
            db=db,
            id_registro_personal=(
                id_registro_personal
            ),
        )
    )

    if (
        cantidad_abiertos
        >= MAXIMO_PROCESOS_ABIERTOS_POR_TRABAJADOR
    ):
        procesos_abiertos = (
            db.query(
                ProcesoDisciplinario
            )
            .filter(
                ProcesoDisciplinario
                .IdRegistroPersonal
                == id_registro_personal,
                ~ProcesoDisciplinario
                .EstadoProceso
                .in_(
                    list(
                        ESTADOS_PROCESO_NO_ABIERTO
                    )
                ),
            )
            .order_by(
                ProcesoDisciplinario
                .FechaCreacion
                .desc()
            )
            .all()
        )

        raise HTTPException(
            status_code=409,
            detail={
                "codigo": (
                    "MAXIMO_PROCESOS_"
                    "DISCIPLINARIOS_ABIERTOS"
                ),
                "mensaje": (
                    "El trabajador ya tiene el máximo "
                    "permitido de 2 procesos disciplinarios "
                    "abiertos. Para registrar uno nuevo, "
                    "primero debe finalizar o cerrar uno "
                    "de los procesos existentes."
                ),
                "IdRegistroPersonal": (
                    id_registro_personal
                ),
                "CantidadProcesosAbiertos": (
                    cantidad_abiertos
                ),
                "MaximoPermitido": (
                    MAXIMO_PROCESOS_ABIERTOS_POR_TRABAJADOR
                ),
                "ProcesosAbiertos": [
                    {
                        "IdProcesoDisciplinario": (
                            proceso
                            .IdProcesoDisciplinario
                        ),
                        "EstadoProceso": (
                            proceso.EstadoProceso
                        ),
                        "OrigenProceso": (
                            proceso.OrigenProceso
                        ),
                        "FechaCreacion": (
                            proceso.FechaCreacion
                        ),
                    }
                    for proceso in procesos_abiertos
                ],
            },
        )


def obtener_borrador_operaciones(
    db: Session,
    id_registro_personal: int,
) -> ProcesoDisciplinario | None:
    return (
        db.query(
            ProcesoDisciplinario
        )
        .filter(
            ProcesoDisciplinario
            .IdRegistroPersonal
            == id_registro_personal,
            ProcesoDisciplinario
            .OrigenProceso
            == "OPERACIONES",
            ProcesoDisciplinario
            .EstadoProceso
            .in_(
                list(
                    ESTADOS_BORRADOR_OPERACIONES
                )
            ),
        )
        .order_by(
            ProcesoDisciplinario
            .FechaCreacion
            .desc()
        )
        .first()
    )



def serializar_documento_expediente(
    documento: DocumentoProcesoDisciplinario,
) -> dict:
    """
    Convierte el documento a JSON sin exponer el contenido binario.

    DocumentoCargado se utiliza únicamente para visualizar o descargar
    el archivo desde los endpoints documentales.
    """

    return {
        "IdDocumentoProcesoDisciplinario": (
            documento.IdDocumentoProcesoDisciplinario
        ),
        "IdProcesoDisciplinario": (
            documento.IdProcesoDisciplinario
        ),
        "TipoDocumento": documento.TipoDocumento,
        "NombreArchivo": documento.NombreArchivo,
        "RutaArchivo": documento.RutaArchivo,
        "Observacion": documento.Observacion,
        "Formato": getattr(
            documento,
            "Formato",
            None,
        ),
        "FechaCreacion": documento.FechaCreacion,
        "FechaActualizacion": documento.FechaActualizacion,
    }


@router.post(
    "/",
    response_model=(
        ProcesoDisciplinarioResponse
    ),
)
def crear_proceso_disciplinario(
    data: ProcesoDisciplinarioCreate,
    db: Session = Depends(get_db),
):
    trabajador = obtener_trabajador_o_error(
        db=db,
        id_registro_personal=(
            data.IdRegistroPersonal
        ),
    )

    validar_maximo_procesos_abiertos(
        db=db,
        id_registro_personal=(
            data.IdRegistroPersonal
        ),
    )

    origen_solicitado = normalizar_texto(
        data.OrigenProceso
    )

    if not origen_solicitado:
        origen_solicitado = "RRLL"

    estado_solicitado = normalizar_texto(
        data.EstadoProceso
    )

    if origen_solicitado == "OPERACIONES":
        validar_trabajador_contratado(
            trabajador
        )

        borrador_existente = (
            obtener_borrador_operaciones(
                db=db,
                id_registro_personal=(
                    data.IdRegistroPersonal
                ),
            )
        )

        if borrador_existente:
            raise HTTPException(
                status_code=409,
                detail={
                    "mensaje": (
                        "El trabajador ya tiene "
                        "un borrador de Operaciones "
                        "pendiente."
                    ),
                    "IdRegistroPersonal": (
                        data.IdRegistroPersonal
                    ),
                    "IdProcesoDisciplinario": (
                        borrador_existente
                        .IdProcesoDisciplinario
                    ),
                    "EstadoProceso": (
                        borrador_existente
                        .EstadoProceso
                    ),
                },
            )

        estado_final = (
            estado_solicitado
            or "BORRADOR_OPERACIONES"
        )

        if (
            estado_final
            not in ESTADOS_BORRADOR_OPERACIONES
        ):
            raise HTTPException(
                status_code=400,
                detail={
                    "mensaje": (
                        "Un proceso de Operaciones solo puede "
                        "crearse inicialmente como borrador."
                    ),
                    "EstadoSolicitado": estado_final,
                    "EstadosPermitidos": sorted(
                        ESTADOS_BORRADOR_OPERACIONES
                    ),
                },
            )

        origen_final = "OPERACIONES"

    else:
        estado_final = (
            estado_solicitado
            or "INICIADO"
        )

        origen_final = (
            origen_solicitado
            or "RRLL"
        )

    nuevo = ProcesoDisciplinario(
        IdRegistroPersonal=(
            data.IdRegistroPersonal
        ),
        EstadoProceso=estado_final,
        OrigenProceso=origen_final,
        UsuarioActualizacion=(
            str(
                data.UsuarioActualizacion
            ).strip()
            if data.UsuarioActualizacion
            else None
        ),
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
            detail={
                "mensaje": (
                    "No se pudo crear el "
                    "proceso disciplinario."
                ),
                "IdRegistroPersonal": (
                    data.IdRegistroPersonal
                ),
            },
        ) from error


@router.get(
    "/trabajador/"
    "{id_registro_personal}/"
    "borrador-operaciones",
    response_model=(
        ProcesoDisciplinarioResponse
        | None
    ),
)
def obtener_borrador_operaciones_trabajador(
    id_registro_personal: int,
    db: Session = Depends(get_db),
):
    obtener_trabajador_o_error(
        db=db,
        id_registro_personal=(
            id_registro_personal
        ),
    )

    return obtener_borrador_operaciones(
        db=db,
        id_registro_personal=(
            id_registro_personal
        ),
    )


@router.get(
    "/trabajador/{id_registro_personal}"
)
def listar_procesos_por_trabajador(
    id_registro_personal: int,
    db: Session = Depends(get_db),
):
    obtener_trabajador_o_error(
        db=db,
        id_registro_personal=(
            id_registro_personal
        ),
    )

    consulta = (
        db.query(
            ProcesoDisciplinario
        )
        .filter(
            ProcesoDisciplinario
            .IdRegistroPersonal
            == id_registro_personal
        )
    )

    procesos = (
        aplicar_filtro_visibilidad_rrll(
            consulta
        )
        .order_by(
            ProcesoDisciplinario
            .FechaCreacion
            .desc()
        )
        .all()
    )

    return procesos


@router.get(
    "/trabajador/"
    "{id_registro_personal}/"
    "historial"
)
def obtener_historial_disciplinario_trabajador(
    id_registro_personal: int,
    db: Session = Depends(get_db),
):
    obtener_trabajador_o_error(
        db=db,
        id_registro_personal=(
            id_registro_personal
        ),
    )

    consulta = (
        db.query(
            ProcesoDisciplinario
        )
        .filter(
            ProcesoDisciplinario
            .IdRegistroPersonal
            == id_registro_personal
        )
    )

    procesos = (
        consulta
        .filter(
            or_(
                ProcesoDisciplinario
                .OrigenProceso
                != "OPERACIONES",
                ProcesoDisciplinario
                .OrigenProceso
                .is_(None),
                ProcesoDisciplinario
                .EstadoProceso
                .in_(
                    list(
                        ESTADOS_VISIBLES_RRLL_OPERACIONES
                    )
                ),
                db.query(
                    SolicitudAutorizacionAgendaDisciplinaria
                    .IdSolicitudAutorizacion
                )
                .filter(
                    SolicitudAutorizacionAgendaDisciplinaria
                    .IdProcesoDisciplinario
                    == ProcesoDisciplinario
                    .IdProcesoDisciplinario,
                    SolicitudAutorizacionAgendaDisciplinaria
                    .Activo
                    .is_(True),
                )
                .exists(),
            )
        )
        .order_by(
            ProcesoDisciplinario
            .FechaCreacion
            .desc()
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
                == proceso
                .IdProcesoDisciplinario
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
                == proceso
                .IdProcesoDisciplinario
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
                == proceso
                .IdProcesoDisciplinario
            )
            .first()
        )

        documentos_rrll = (
            db.query(
                DocumentoProcesoDisciplinario
            )
            .filter(
                DocumentoProcesoDisciplinario
                .IdProcesoDisciplinario
                == proceso
                .IdProcesoDisciplinario,
                DocumentoProcesoDisciplinario
                .TipoDocumento
                != "EVIDENCIA_OPERACIONES",
            )
            .order_by(
                DocumentoProcesoDisciplinario
                .FechaCreacion
                .desc()
            )
            .all()
        )

        proceso_cerrado = (
            normalizar_texto(
                proceso.EstadoProceso
            )
            == "CERRADO"
        )

        solicitud_viernes = (
            db.query(
                SolicitudAutorizacionAgendaDisciplinaria
            )
            .filter(
                SolicitudAutorizacionAgendaDisciplinaria
                .IdProcesoDisciplinario
                == proceso.IdProcesoDisciplinario,
                SolicitudAutorizacionAgendaDisciplinaria
                .Activo.is_(True),
            )
            .order_by(
                SolicitudAutorizacionAgendaDisciplinaria
                .FechaSolicitud
                .desc(),
                SolicitudAutorizacionAgendaDisciplinaria
                .IdSolicitudAutorizacion
                .desc(),
            )
            .first()
        )

        autorizacion_viernes = None

        if (
            solicitud_viernes
            and solicitud_viernes
            .IdAutorizacionAgendaDisciplinaria
            is not None
        ):
            autorizacion_viernes = (
                db.query(
                    AutorizacionAgendaDisciplinaria
                )
                .filter(
                    AutorizacionAgendaDisciplinaria
                    .IdAutorizacionAgendaDisciplinaria
                    == solicitud_viernes
                    .IdAutorizacionAgendaDisciplinaria
                )
                .first()
            )

        historial.append(
            {
                "IdProcesoDisciplinario": (
                    proceso
                    .IdProcesoDisciplinario
                ),
                "IdRegistroPersonal": (
                    proceso
                    .IdRegistroPersonal
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
                    cierre
                    .MedidaDisciplinaria
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
                "CantidadDocumentosRRLL": (
                    len(documentos_rrll)
                ),
                "TieneDocumentosRRLL": (
                    len(documentos_rrll) > 0
                ),
                "RespuestaRRLLDisponible": (
                    proceso_cerrado
                    and cierre is not None
                    and len(documentos_rrll) > 0
                ),
                "TieneSolicitudViernes": (
                    solicitud_viernes is not None
                ),
                "IdSolicitudAutorizacionViernes": (
                    solicitud_viernes
                    .IdSolicitudAutorizacion
                    if solicitud_viernes
                    else None
                ),
                "EstadoSolicitudViernes": (
                    solicitud_viernes.EstadoSolicitud
                    if solicitud_viernes
                    else None
                ),
                "FechaSolicitadaViernes": (
                    solicitud_viernes.FechaSolicitada
                    if solicitud_viernes
                    else None
                ),
                "FechaSolicitudViernes": (
                    solicitud_viernes.FechaSolicitud
                    if solicitud_viernes
                    else None
                ),
                "UsuarioSolicitaViernes": (
                    solicitud_viernes.UsuarioSolicita
                    if solicitud_viernes
                    else None
                ),
                "UsuarioResuelveViernes": (
                    solicitud_viernes.UsuarioResuelve
                    if solicitud_viernes
                    else None
                ),
                "FechaResolucionViernes": (
                    solicitud_viernes.FechaResolucion
                    if solicitud_viernes
                    else None
                ),
                "ObservacionResolucionViernes": (
                    solicitud_viernes.ObservacionResolucion
                    if solicitud_viernes
                    else None
                ),
                "IdAutorizacionAgendaDisciplinaria": (
                    solicitud_viernes
                    .IdAutorizacionAgendaDisciplinaria
                    if solicitud_viernes
                    else None
                ),
                "AutorizacionViernesDisponible": (
                    solicitud_viernes is not None
                    and normalizar_texto(
                        solicitud_viernes.EstadoSolicitud
                    )
                    == "APROBADA"
                    and autorizacion_viernes is not None
                    and bool(
                        autorizacion_viernes.Activo
                    )
                    and normalizar_texto(
                        autorizacion_viernes
                        .EstadoAutorizacion
                    )
                    == "ACTIVA"
                ),
                "FechaAutorizadaViernes": (
                    autorizacion_viernes.FechaAutorizada
                    if autorizacion_viernes
                    else None
                ),
                "HoraInicioAutorizadaViernes": (
                    autorizacion_viernes.HoraInicio
                    if autorizacion_viernes
                    else None
                ),
                "HoraFinAutorizadaViernes": (
                    autorizacion_viernes.HoraFin
                    if autorizacion_viernes
                    else None
                ),
                "EstadoAutorizacionViernes": (
                    autorizacion_viernes.EstadoAutorizacion
                    if autorizacion_viernes
                    else None
                ),
            }
        )

    return historial


@router.post(
    "/{id_proceso}/enviar-rrll",
)
def enviar_proceso_a_rrll(
    id_proceso: int,
    data: EnviarProcesoRRLLRequest,
    db: Session = Depends(get_db),
):
    proceso = obtener_proceso_o_error(
        db=db,
        id_proceso=id_proceso,
    )

    validar_proceso_modificable(
        proceso
    )

    origen = normalizar_texto(
        proceso.OrigenProceso
    )
    estado = normalizar_texto(
        proceso.EstadoProceso
    )

    if origen != "OPERACIONES":
        raise HTTPException(
            status_code=409,
            detail={
                "mensaje": (
                    "Solo los procesos originados en "
                    "Operaciones pueden utilizar este envío."
                ),
                "OrigenProceso": proceso.OrigenProceso,
            },
        )

    if estado == "ENVIADO_A_RRLL":
        evento_existente = (
            db.query(
                AgendaProcesoDisciplinario
            )
            .filter(
                AgendaProcesoDisciplinario
                .IdProcesoDisciplinario
                == id_proceso,
                AgendaProcesoDisciplinario
                .Activo.is_(True),
            )
            .first()
        )

        return {
            "ok": True,
            "yaEnviado": True,
            "IdProcesoDisciplinario": id_proceso,
            "EstadoProceso": proceso.EstadoProceso,
            "IdAgendaProcesoDisciplinario": (
                evento_existente
                .IdAgendaProcesoDisciplinario
                if evento_existente
                else None
            ),
            "mensaje": (
                "El proceso ya había sido enviado "
                "a Relaciones Laborales."
            ),
        }

    estados_permitidos_envio = {
        "PASO_2_COMPLETADO",
        "PASO_3_COMPLETADO",
    }

    if estado not in estados_permitidos_envio:
        raise HTTPException(
            status_code=409,
            detail={
                "mensaje": (
                    "El proceso debe estar completamente "
                    "diligenciado y revisado antes de enviarse "
                    "a Relaciones Laborales."
                ),
                "EstadoActual": proceso.EstadoProceso,
                "EstadosPermitidos": sorted(
                    estados_permitidos_envio
                ),
            },
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
        .order_by(
            CitacionProcesoDisciplinario
            .IdCitacionProcesoDisciplinario
            .desc()
        )
        .first()
    )

    if not citacion:
        raise HTTPException(
            status_code=409,
            detail={
                "mensaje": (
                    "El proceso no tiene una citación "
                    "registrada por Operaciones."
                ),
                "IdProcesoDisciplinario": id_proceso,
            },
        )

    validar_citacion_completa_para_envio(
        citacion
    )

    validar_fecha_minima_citacion(
        fecha_evento=citacion.FechaCitacion,
        fecha_creacion_evento=proceso.FechaCreacion,
    )

    hora_fin = calcular_hora_fin_citacion(
        citacion.HoraCitacion
    )

    validar_programacion_citacion(
            db=db,
            fecha_evento=citacion.FechaCitacion,
            hora_inicio=citacion.HoraCitacion,
            hora_fin=hora_fin,
            id_registro_personal=proceso.IdRegistroPersonal,
            id_proceso_disciplinario=id_proceso,
            bloquear_autorizacion=True,
        )

    agenda_existente = (
        db.query(
            AgendaProcesoDisciplinario
        )
        .filter(
            AgendaProcesoDisciplinario
            .IdProcesoDisciplinario
            == id_proceso,
            AgendaProcesoDisciplinario
            .Activo.is_(True),
        )
        .first()
    )

    if agenda_existente:
        raise HTTPException(
            status_code=409,
            detail={
                "mensaje": (
                    "El proceso ya tiene un evento activo "
                    "en la agenda disciplinaria."
                ),
                "IdAgendaProcesoDisciplinario": (
                    agenda_existente
                    .IdAgendaProcesoDisciplinario
                ),
            },
        )

    tipo_evento = (
        db.execute(
            text(
                """
                SELECT
                    "IdTipoEventoDisciplinario"
                FROM public."TipoEventoDisciplinario"
                WHERE
                    "IdTipoEventoDisciplinario"
                    = :id_tipo_evento
                    AND "Activo" = TRUE
                LIMIT 1
                """
            ),
            {
                "id_tipo_evento": (
                    TIPO_EVENTO_CITACION_ID
                )
            },
        )
        .mappings()
        .first()
    )

    if not tipo_evento:
        raise HTTPException(
            status_code=409,
            detail={
                "mensaje": (
                    "No se encuentra activo el tipo de "
                    "evento Citación en la base de datos."
                ),
                "IdTipoEventoDisciplinario": (
                    TIPO_EVENTO_CITACION_ID
                ),
            },
        )

    usuario = str(
        data.UsuarioActualizacion
        or proceso.UsuarioActualizacion
        or "operaciones_envio_rrll"
    ).strip()

    fecha_actualizacion = datetime.now(timezone.utc)

    nuevo_evento = AgendaProcesoDisciplinario(
        IdProcesoDisciplinario=id_proceso,
        IdRegistroPersonal=proceso.IdRegistroPersonal,
        IdTipoEventoDisciplinario=(
            TIPO_EVENTO_CITACION_ID
        ),
        FechaEvento=citacion.FechaCitacion,
        HoraInicio=citacion.HoraCitacion,
        HoraFin=hora_fin,
        Modalidad=citacion.Modalidad,
        Observacion=citacion.RelatoHechos,
        EstadoAgenda="PROGRAMADO",
        ColorAgenda="AZUL",
        UsuarioAgenda=usuario,
        FechaCreacion=fecha_actualizacion,
        FechaActualizacion=fecha_actualizacion,
        UsuarioActualizacion=usuario,
        Activo=True,
        LugarCitacion=citacion.LugarCitacion,
        SupervisorReporta=(
            citacion.SupervisorReporta
        ),
        Sede=citacion.Sede,
        MotivoCitacion=citacion.MotivoCitacion,
        RelatoHechos=citacion.RelatoHechos,
        ObservacionOperaciones=(
            citacion.ObservacionOperaciones
        ),
        ManifestacionSupervisor=(
            citacion.ManifestacionSupervisor
        ),
    )

    proceso.EstadoProceso = "ENVIADO_A_RRLL"
    proceso.FechaActualizacion = fecha_actualizacion
    proceso.UsuarioActualizacion = usuario

    try:
        db.add(nuevo_evento)
        db.flush()
        db.commit()
        db.refresh(nuevo_evento)
        db.refresh(proceso)

    except SQLAlchemyError as error:
        db.rollback()

        raise HTTPException(
            status_code=500,
            detail={
                "mensaje": (
                    "No se pudo enviar el proceso a RRLL "
                    "ni crear la agenda disciplinaria."
                ),
                "IdProcesoDisciplinario": id_proceso,
            },
        ) from error

    resultado_notificacion = intentar_enviar_citacion_inicial(
        db=db,
        id_agenda=(
            nuevo_evento.IdAgendaProcesoDisciplinario
        ),
        usuario=usuario,
    )

    return {
        "ok": True,
        "yaEnviado": False,
        "IdProcesoDisciplinario": id_proceso,
        "EstadoProceso": proceso.EstadoProceso,
        "IdAgendaProcesoDisciplinario": (
            nuevo_evento
            .IdAgendaProcesoDisciplinario
        ),
        "FechaEvento": nuevo_evento.FechaEvento,
        "HoraInicio": nuevo_evento.HoraInicio,
        "HoraFin": nuevo_evento.HoraFin,
        "EstadoAgenda": nuevo_evento.EstadoAgenda,
        "ColorAgenda": nuevo_evento.ColorAgenda,
        "NotificacionCorreo": resultado_notificacion,
        "mensaje": (
            "El proceso fue enviado a Relaciones "
            "Laborales y quedó programado en la agenda."
        ),
    }


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
            .FechaCreacion
            .desc()
        )
        .all()
    )

    return {
        "Proceso": proceso,
        "Citacion": citacion,
        "Descargo": descargo,
        "Cierre": cierre,
        "Documentos": [
            serializar_documento_expediente(
                documento
            )
            for documento in documentos
        ],
    }


@router.get(
    "/{id_proceso}/pdf"
)
def generar_pdf_expediente_disciplinario(
    id_proceso: int,
    request: Request,
    db: Session = Depends(get_db),
):
    proceso = obtener_proceso_o_error(
        db=db,
        id_proceso=id_proceso,
    )

    codigo_expediente = formatear_codigo_expediente(
        id_proceso=proceso.IdProcesoDisciplinario,
        fecha_creacion=proceso.FechaCreacion,
    )

    url_base = str(
        request.base_url
    ).rstrip("/")

    buffer_pdf = generar_expediente_disciplinario_pdf(
        db=db,
        id_proceso=id_proceso,
        url_base=url_base,
    )

    return StreamingResponse(
        buffer_pdf,
        media_type="application/pdf",
        headers={
            "Content-Disposition": (
                f'inline; filename="'
                f'expediente_disciplinario_'
                f'{codigo_expediente}.pdf"'
            )
        },
    )


@router.get(
    "/{id_proceso}",
    response_model=(
        ProcesoDisciplinarioResponse
    ),
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
    response_model=(
        ProcesoDisciplinarioResponse
    ),
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
        estado_nuevo = normalizar_texto(
            datos_actualizados.get(
                "EstadoProceso"
            )
        )

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

        if (
            estado_nuevo
            in ESTADOS_CAMBIO_PROTEGIDO
        ):
            raise HTTPException(
                status_code=409,
                detail={
                    "mensaje": (
                        "Este estado solo puede alcanzarse "
                        "mediante el flujo oficial del módulo."
                    ),
                    "EstadoSolicitado": estado_nuevo,
                    "EstadosProtegidos": sorted(
                        ESTADOS_CAMBIO_PROTEGIDO
                    ),
                },
            )

        if (
            normalizar_texto(
                proceso.OrigenProceso
            )
            == "OPERACIONES"
            and estado_nuevo
            not in ESTADOS_BORRADOR_OPERACIONES
        ):
            raise HTTPException(
                status_code=409,
                detail={
                    "mensaje": (
                        "Mientras el proceso no haya sido "
                        "enviado a RRLL, Operaciones solo puede "
                        "usar estados de borrador."
                    ),
                    "EstadoSolicitado": estado_nuevo,
                    "EstadosPermitidos": sorted(
                        ESTADOS_BORRADOR_OPERACIONES
                    ),
                },
            )

        proceso.EstadoProceso = (
            estado_nuevo
        )

    if "OrigenProceso" in datos_actualizados:
        origen_nuevo = normalizar_texto(
            datos_actualizados.get(
                "OrigenProceso"
            )
        )

        proceso.OrigenProceso = (
            origen_nuevo
            if origen_nuevo
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
            else None
        )

    proceso.FechaActualizacion = (
        datetime.now(timezone.utc)
    )

    try:
        db.commit()
        db.refresh(
            proceso
        )

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