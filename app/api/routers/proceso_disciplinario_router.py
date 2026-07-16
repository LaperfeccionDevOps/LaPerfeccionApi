from datetime import datetime

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Request,
)
from fastapi.responses import StreamingResponse
from sqlalchemy import or_, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session
from pydantic import BaseModel

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
from domain.models.agenda_proceso_disciplinario import (
    AgendaProcesoDisciplinario,
)

from domain.schemas.proceso_disciplinario_schema import (
    ProcesoDisciplinarioCreate,
    ProcesoDisciplinarioResponse,
    ProcesoDisciplinarioUpdate,
)

from services.expediente_disciplinario_pdf_service import (
    generar_expediente_disciplinario_pdf,
)
from api.routers.agenda_proceso_disciplinario_router import (
    TIPO_EVENTO_CITACION_ID,
    calcular_hora_fin_citacion,
    validar_fecha_minima_citacion,
    validar_programacion_citacion,
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

    fecha_actualizacion = datetime.now()

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
            "mensaje": (
                "El proceso fue enviado a Relaciones "
                "Laborales y quedó programado en la agenda."
            ),
        }

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
    obtener_proceso_o_error(
        db=db,
        id_proceso=id_proceso,
    )

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
        datetime.now()
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