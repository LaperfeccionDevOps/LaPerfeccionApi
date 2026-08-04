from datetime import date, datetime, time, timedelta, timezone

from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from domain.models.autorizacion_agenda_disciplinaria import (
    AutorizacionAgendaDisciplinaria,
)
from domain.models.solicitud_autorizacion_agenda_disciplinaria import (
    SolicitudAutorizacionAgendaDisciplinaria,
)
from domain.schemas.solicitud_autorizacion_agenda_disciplinaria_schema import (
    SolicitudAutorizacionAgendaDisciplinariaCreate,
)


ZONA_COLOMBIA = timezone(
    timedelta(hours=-5)
)


def obtener_ahora_colombia() -> datetime:
    return datetime.now(
        ZONA_COLOMBIA
    )


def normalizar_texto(
    valor: str | None,
) -> str | None:
    if valor is None:
        return None

    texto = str(valor).strip()

    return texto or None


def obtener_solicitud_por_id(
    db: Session,
    id_solicitud: int,
) -> SolicitudAutorizacionAgendaDisciplinaria | None:
    return (
        db.query(
            SolicitudAutorizacionAgendaDisciplinaria
        )
        .filter(
            SolicitudAutorizacionAgendaDisciplinaria
            .IdSolicitudAutorizacion
            == id_solicitud
        )
        .first()
    )


def listar_solicitudes(
    db: Session,
    estado_solicitud: str | None = None,
    fecha_desde: date | None = None,
    fecha_hasta: date | None = None,
    id_proceso_disciplinario: int | None = None,
    id_registro_personal: int | None = None,
    incluir_inactivas: bool = False,
) -> list[SolicitudAutorizacionAgendaDisciplinaria]:
    consulta = db.query(
        SolicitudAutorizacionAgendaDisciplinaria
    )

    if not incluir_inactivas:
        consulta = consulta.filter(
            SolicitudAutorizacionAgendaDisciplinaria
            .Activo
            .is_(True)
        )

    if estado_solicitud:
        consulta = consulta.filter(
            SolicitudAutorizacionAgendaDisciplinaria
            .EstadoSolicitud
            == estado_solicitud.strip().upper()
        )

    if fecha_desde:
        consulta = consulta.filter(
            SolicitudAutorizacionAgendaDisciplinaria
            .FechaSolicitada
            >= fecha_desde
        )

    if fecha_hasta:
        consulta = consulta.filter(
            SolicitudAutorizacionAgendaDisciplinaria
            .FechaSolicitada
            <= fecha_hasta
        )

    if id_proceso_disciplinario is not None:
        consulta = consulta.filter(
            SolicitudAutorizacionAgendaDisciplinaria
            .IdProcesoDisciplinario
            == id_proceso_disciplinario
        )

    if id_registro_personal is not None:
        consulta = consulta.filter(
            SolicitudAutorizacionAgendaDisciplinaria
            .IdRegistroPersonal
            == id_registro_personal
        )

    return (
        consulta
        .order_by(
            SolicitudAutorizacionAgendaDisciplinaria
            .FechaSolicitud
            .desc(),
            SolicitudAutorizacionAgendaDisciplinaria
            .IdSolicitudAutorizacion
            .desc(),
        )
        .all()
    )


def listar_solicitudes_pendientes(
    db: Session,
) -> list[SolicitudAutorizacionAgendaDisciplinaria]:
    return listar_solicitudes(
        db=db,
        estado_solicitud="PENDIENTE",
        incluir_inactivas=False,
    )


def listar_solicitudes_por_proceso(
    db: Session,
    id_proceso_disciplinario: int,
    incluir_inactivas: bool = True,
) -> list[SolicitudAutorizacionAgendaDisciplinaria]:
    return listar_solicitudes(
        db=db,
        id_proceso_disciplinario=id_proceso_disciplinario,
        incluir_inactivas=incluir_inactivas,
    )


def listar_solicitudes_por_trabajador(
    db: Session,
    id_registro_personal: int,
    incluir_inactivas: bool = True,
) -> list[SolicitudAutorizacionAgendaDisciplinaria]:
    return listar_solicitudes(
        db=db,
        id_registro_personal=id_registro_personal,
        incluir_inactivas=incluir_inactivas,
    )


def obtener_solicitud_pendiente(
    db: Session,
    id_registro_personal: int,
    id_proceso_disciplinario: int,
    fecha_solicitada: date,
    bloquear_registro: bool = False,
) -> SolicitudAutorizacionAgendaDisciplinaria | None:
    consulta = (
        db.query(
            SolicitudAutorizacionAgendaDisciplinaria
        )
        .filter(
            SolicitudAutorizacionAgendaDisciplinaria
            .IdRegistroPersonal
            == id_registro_personal,
            SolicitudAutorizacionAgendaDisciplinaria
            .IdProcesoDisciplinario
            == id_proceso_disciplinario,
            SolicitudAutorizacionAgendaDisciplinaria
            .FechaSolicitada
            == fecha_solicitada,
            SolicitudAutorizacionAgendaDisciplinaria
            .EstadoSolicitud
            == "PENDIENTE",
            SolicitudAutorizacionAgendaDisciplinaria
            .Activo
            .is_(True),
        )
    )

    if bloquear_registro:
        consulta = consulta.with_for_update()

    return consulta.first()


def existe_solicitud_pendiente(
    db: Session,
    id_registro_personal: int,
    id_proceso_disciplinario: int,
    fecha_solicitada: date,
) -> bool:
    solicitud = obtener_solicitud_pendiente(
        db=db,
        id_registro_personal=id_registro_personal,
        id_proceso_disciplinario=id_proceso_disciplinario,
        fecha_solicitada=fecha_solicitada,
    )

    return solicitud is not None


def crear_solicitud(
    db: Session,
    data: SolicitudAutorizacionAgendaDisciplinariaCreate,
) -> SolicitudAutorizacionAgendaDisciplinaria:
    datos = data.model_dump()

    motivo = normalizar_texto(
        datos.get("MotivoSolicitud")
    )
    usuario_solicita = normalizar_texto(
        datos.get("UsuarioSolicita")
    )
    fecha_solicitada = datos.get(
        "FechaSolicitada"
    )

    if not motivo:
        raise ValueError(
            "El motivo de la solicitud es obligatorio."
        )

    if not usuario_solicita:
        raise ValueError(
            "El usuario que solicita es obligatorio."
        )

    if not fecha_solicitada:
        raise ValueError(
            "La fecha solicitada es obligatoria."
        )

    if fecha_solicitada.weekday() != 4:
        raise ValueError(
            "La fecha solicitada debe corresponder "
            "a un viernes."
        )

    fecha_actual = obtener_ahora_colombia()

    if fecha_solicitada < fecha_actual.date():
        raise ValueError(
            "No se puede solicitar autorización para "
            "una fecha anterior al día actual."
        )

    solicitud_existente = obtener_solicitud_pendiente(
        db=db,
        id_registro_personal=datos["IdRegistroPersonal"],
        id_proceso_disciplinario=datos["IdProcesoDisciplinario"],
        fecha_solicitada=fecha_solicitada,
    )

    if solicitud_existente:
        raise ValueError(
            "Ya existe una solicitud pendiente para "
            "este trabajador, expediente y viernes."
        )

    nueva_solicitud = (
        SolicitudAutorizacionAgendaDisciplinaria(
            IdRegistroPersonal=datos["IdRegistroPersonal"],
            IdProcesoDisciplinario=datos["IdProcesoDisciplinario"],
            FechaSolicitada=fecha_solicitada,
            MotivoSolicitud=motivo,
            UsuarioSolicita=usuario_solicita,
            EstadoSolicitud="PENDIENTE",
            FechaSolicitud=fecha_actual,
            UsuarioResuelve=None,
            FechaResolucion=None,
            ObservacionResolucion=None,
            IdAutorizacionAgendaDisciplinaria=None,
            Activo=True,
            FechaCreacion=fecha_actual,
            FechaActualizacion=fecha_actual,
        )
    )

    try:
        db.add(nueva_solicitud)
        db.commit()
        db.refresh(nueva_solicitud)

        return nueva_solicitud

    except IntegrityError as error:
        db.rollback()

        raise ValueError(
            "No fue posible crear la solicitud debido "
            "a una validación de integridad."
        ) from error

    except SQLAlchemyError:
        db.rollback()
        raise


def aprobar_solicitud(
    db: Session,
    id_solicitud: int,
    hora_inicio: time,
    hora_fin: time,
    usuario_resuelve: str,
    observacion_resolucion: str | None = None,
) -> SolicitudAutorizacionAgendaDisciplinaria:
    solicitud = (
        db.query(
            SolicitudAutorizacionAgendaDisciplinaria
        )
        .filter(
            SolicitudAutorizacionAgendaDisciplinaria
            .IdSolicitudAutorizacion
            == id_solicitud,
            SolicitudAutorizacionAgendaDisciplinaria
            .Activo
            .is_(True),
        )
        .with_for_update()
        .first()
    )

    if not solicitud:
        raise ValueError(
            "La solicitud no existe o ya no está activa."
        )

    estado_actual = str(
        solicitud.EstadoSolicitud or ""
    ).strip().upper()

    if estado_actual != "PENDIENTE":
        raise ValueError(
            "Solo se pueden aprobar solicitudes "
            "que se encuentren PENDIENTES."
        )

    usuario = normalizar_texto(
        usuario_resuelve
    )
    observacion = normalizar_texto(
        observacion_resolucion
    )

    if not usuario:
        raise ValueError(
            "El usuario que aprueba es obligatorio."
        )

    if hora_fin <= hora_inicio:
        raise ValueError(
            "La hora final debe ser posterior "
            "a la hora inicial."
        )

    autorizacion_existente = (
        db.query(
            AutorizacionAgendaDisciplinaria
        )
        .filter(
            AutorizacionAgendaDisciplinaria
            .IdRegistroPersonal
            == solicitud.IdRegistroPersonal,
            AutorizacionAgendaDisciplinaria
            .IdProcesoDisciplinario
            == solicitud.IdProcesoDisciplinario,
            AutorizacionAgendaDisciplinaria
            .FechaAutorizada
            == solicitud.FechaSolicitada,
            AutorizacionAgendaDisciplinaria
            .HoraInicio
            == hora_inicio,
            AutorizacionAgendaDisciplinaria
            .HoraFin
            == hora_fin,
            AutorizacionAgendaDisciplinaria
            .EstadoAutorizacion
            == "ACTIVA",
            AutorizacionAgendaDisciplinaria
            .Activo
            .is_(True),
        )
        .first()
    )

    if autorizacion_existente:
        raise ValueError(
            "Ya existe una autorización activa para "
            "este expediente, fecha y horario."
        )

    fecha_actual = obtener_ahora_colombia()

    nueva_autorizacion = (
        AutorizacionAgendaDisciplinaria(
            IdRegistroPersonal=solicitud.IdRegistroPersonal,
            IdProcesoDisciplinario=solicitud.IdProcesoDisciplinario,
            IdAgendaProcesoDisciplinario=None,
            FechaAutorizada=solicitud.FechaSolicitada,
            HoraInicio=hora_inicio,
            HoraFin=hora_fin,
            TipoAutorizacion="VIERNES",
            MotivoAutorizacion=solicitud.MotivoSolicitud,
            UsuarioSolicita=solicitud.UsuarioSolicita,
            UsuarioAutoriza=usuario,
            EstadoAutorizacion="ACTIVA",
            FechaAutorizacion=fecha_actual,
            FechaUtilizacion=None,
            Observacion=observacion,
            Activo=True,
            FechaCreacion=fecha_actual,
            FechaActualizacion=fecha_actual,
        )
    )

    solicitud.EstadoSolicitud = "APROBADA"
    solicitud.UsuarioResuelve = usuario
    solicitud.FechaResolucion = fecha_actual
    solicitud.ObservacionResolucion = observacion
    solicitud.FechaActualizacion = fecha_actual

    try:
        db.add(nueva_autorizacion)
        db.flush()

        solicitud.IdAutorizacionAgendaDisciplinaria = (
            nueva_autorizacion
            .IdAutorizacionAgendaDisciplinaria
        )

        db.commit()
        db.refresh(solicitud)

        return solicitud

    except IntegrityError as error:
        db.rollback()

        raise ValueError(
            "No fue posible aprobar la solicitud porque "
            "ya existe una autorización activa con la "
            "misma fecha y horario."
        ) from error

    except SQLAlchemyError:
        db.rollback()
        raise


def rechazar_solicitud(
    db: Session,
    id_solicitud: int,
    usuario_resuelve: str,
    observacion_resolucion: str,
) -> SolicitudAutorizacionAgendaDisciplinaria:
    solicitud = (
        db.query(
            SolicitudAutorizacionAgendaDisciplinaria
        )
        .filter(
            SolicitudAutorizacionAgendaDisciplinaria
            .IdSolicitudAutorizacion
            == id_solicitud,
            SolicitudAutorizacionAgendaDisciplinaria
            .Activo
            .is_(True),
        )
        .with_for_update()
        .first()
    )

    if not solicitud:
        raise ValueError(
            "La solicitud no existe o ya no está activa."
        )

    estado_actual = str(
        solicitud.EstadoSolicitud or ""
    ).strip().upper()

    if estado_actual != "PENDIENTE":
        raise ValueError(
            "Solo se pueden rechazar solicitudes "
            "que se encuentren PENDIENTES."
        )

    usuario = normalizar_texto(
        usuario_resuelve
    )
    observacion = normalizar_texto(
        observacion_resolucion
    )

    if not usuario:
        raise ValueError(
            "El usuario que rechaza es obligatorio."
        )

    if not observacion:
        raise ValueError(
            "El motivo del rechazo es obligatorio."
        )

    fecha_actual = obtener_ahora_colombia()

    solicitud.EstadoSolicitud = "RECHAZADA"
    solicitud.UsuarioResuelve = usuario
    solicitud.FechaResolucion = fecha_actual
    solicitud.ObservacionResolucion = observacion
    solicitud.FechaActualizacion = fecha_actual

    try:
        db.commit()
        db.refresh(solicitud)

        return solicitud

    except SQLAlchemyError:
        db.rollback()
        raise


def cancelar_solicitud(
    db: Session,
    id_solicitud: int,
    usuario_cancela: str,
    motivo_cancelacion: str,
) -> SolicitudAutorizacionAgendaDisciplinaria:
    solicitud = (
        db.query(
            SolicitudAutorizacionAgendaDisciplinaria
        )
        .filter(
            SolicitudAutorizacionAgendaDisciplinaria
            .IdSolicitudAutorizacion
            == id_solicitud,
            SolicitudAutorizacionAgendaDisciplinaria
            .Activo
            .is_(True),
        )
        .with_for_update()
        .first()
    )

    if not solicitud:
        raise ValueError(
            "La solicitud no existe o ya no está activa."
        )

    estado_actual = str(
        solicitud.EstadoSolicitud or ""
    ).strip().upper()

    if estado_actual != "PENDIENTE":
        raise ValueError(
            "Solo se pueden cancelar solicitudes "
            "que se encuentren PENDIENTES."
        )

    usuario = normalizar_texto(
        usuario_cancela
    )
    motivo = normalizar_texto(
        motivo_cancelacion
    )

    if not usuario:
        raise ValueError(
            "El usuario que cancela es obligatorio."
        )

    if not motivo:
        raise ValueError(
            "El motivo de cancelación es obligatorio."
        )

    fecha_actual = obtener_ahora_colombia()

    solicitud.EstadoSolicitud = "CANCELADA"
    solicitud.UsuarioResuelve = usuario
    solicitud.FechaResolucion = fecha_actual
    solicitud.ObservacionResolucion = motivo
    solicitud.Activo = False
    solicitud.FechaActualizacion = fecha_actual

    try:
        db.commit()
        db.refresh(solicitud)

        return solicitud

    except SQLAlchemyError:
        db.rollback()
        raise