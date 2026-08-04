from datetime import date, datetime, time, timedelta, timezone

from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from domain.models.autorizacion_agenda_disciplinaria import (
    AutorizacionAgendaDisciplinaria,
)
from domain.schemas.autorizacion_agenda_disciplinaria_schema import (
    AutorizacionAgendaDisciplinariaCreate,
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


def obtener_autorizacion_por_id(
    db: Session,
    id_autorizacion: int,
) -> AutorizacionAgendaDisciplinaria | None:
    return (
        db.query(
            AutorizacionAgendaDisciplinaria
        )
        .filter(
            AutorizacionAgendaDisciplinaria
            .IdAutorizacionAgendaDisciplinaria
            == id_autorizacion
        )
        .first()
    )


def listar_autorizaciones(
    db: Session,
    estado_autorizacion: str | None = None,
    fecha_desde: date | None = None,
    fecha_hasta: date | None = None,
    id_proceso_disciplinario: int | None = None,
    id_registro_personal: int | None = None,
    incluir_inactivas: bool = False,
) -> list[AutorizacionAgendaDisciplinaria]:
    consulta = db.query(
        AutorizacionAgendaDisciplinaria
    )

    if not incluir_inactivas:
        consulta = consulta.filter(
            AutorizacionAgendaDisciplinaria
            .Activo
            .is_(True)
        )

    if estado_autorizacion:
        consulta = consulta.filter(
            AutorizacionAgendaDisciplinaria
            .EstadoAutorizacion
            == estado_autorizacion.strip().upper()
        )

    if fecha_desde:
        consulta = consulta.filter(
            AutorizacionAgendaDisciplinaria
            .FechaAutorizada
            >= fecha_desde
        )

    if fecha_hasta:
        consulta = consulta.filter(
            AutorizacionAgendaDisciplinaria
            .FechaAutorizada
            <= fecha_hasta
        )

    if id_proceso_disciplinario is not None:
        consulta = consulta.filter(
            AutorizacionAgendaDisciplinaria
            .IdProcesoDisciplinario
            == id_proceso_disciplinario
        )

    if id_registro_personal is not None:
        consulta = consulta.filter(
            AutorizacionAgendaDisciplinaria
            .IdRegistroPersonal
            == id_registro_personal
        )

    return (
        consulta
        .order_by(
            AutorizacionAgendaDisciplinaria
            .FechaAutorizada
            .desc(),
            AutorizacionAgendaDisciplinaria
            .HoraInicio
            .asc(),
            AutorizacionAgendaDisciplinaria
            .IdAutorizacionAgendaDisciplinaria
            .desc(),
        )
        .all()
    )


def listar_autorizaciones_por_proceso(
    db: Session,
    id_proceso_disciplinario: int,
    incluir_inactivas: bool = True,
) -> list[AutorizacionAgendaDisciplinaria]:
    return listar_autorizaciones(
        db=db,
        id_proceso_disciplinario=(
            id_proceso_disciplinario
        ),
        incluir_inactivas=incluir_inactivas,
    )


def buscar_autorizacion_activa(
    db: Session,
    id_registro_personal: int,
    id_proceso_disciplinario: int,
    fecha_autorizada: date,
    hora_inicio: time,
    hora_fin: time,
    bloquear_registro: bool = False,
) -> AutorizacionAgendaDisciplinaria | None:
    consulta = (
        db.query(
            AutorizacionAgendaDisciplinaria
        )
        .filter(
            AutorizacionAgendaDisciplinaria
            .IdRegistroPersonal
            == id_registro_personal,
            AutorizacionAgendaDisciplinaria
            .IdProcesoDisciplinario
            == id_proceso_disciplinario,
            AutorizacionAgendaDisciplinaria
            .FechaAutorizada
            == fecha_autorizada,
            AutorizacionAgendaDisciplinaria
            .HoraInicio
            == hora_inicio,
            AutorizacionAgendaDisciplinaria
            .HoraFin
            == hora_fin,
            AutorizacionAgendaDisciplinaria
            .TipoAutorizacion
            == "VIERNES",
            AutorizacionAgendaDisciplinaria
            .EstadoAutorizacion
            == "ACTIVA",
            AutorizacionAgendaDisciplinaria
            .Activo
            .is_(True),
        )
    )

    if bloquear_registro:
        consulta = consulta.with_for_update()

    return consulta.first()


def existe_autorizacion_activa(
    db: Session,
    id_registro_personal: int,
    id_proceso_disciplinario: int,
    fecha_autorizada: date,
    hora_inicio: time,
    hora_fin: time,
) -> bool:
    autorizacion = buscar_autorizacion_activa(
        db=db,
        id_registro_personal=id_registro_personal,
        id_proceso_disciplinario=(
            id_proceso_disciplinario
        ),
        fecha_autorizada=fecha_autorizada,
        hora_inicio=hora_inicio,
        hora_fin=hora_fin,
    )

    return autorizacion is not None


def crear_autorizacion(
    db: Session,
    data: AutorizacionAgendaDisciplinariaCreate,
) -> AutorizacionAgendaDisciplinaria:
    datos = data.model_dump()

    datos["TipoAutorizacion"] = (
        normalizar_texto(
            datos.get("TipoAutorizacion")
        )
        or "VIERNES"
    ).upper()

    datos["MotivoAutorizacion"] = (
        normalizar_texto(
            datos.get("MotivoAutorizacion")
        )
        or ""
    )

    datos["UsuarioSolicita"] = (
        normalizar_texto(
            datos.get("UsuarioSolicita")
        )
    )

    datos["UsuarioAutoriza"] = (
        normalizar_texto(
            datos.get("UsuarioAutoriza")
        )
        or ""
    )

    datos["Observacion"] = (
        normalizar_texto(
            datos.get("Observacion")
        )
    )

    datos["EstadoAutorizacion"] = "ACTIVA"
    datos["Activo"] = True

    fecha_actual = obtener_ahora_colombia()

    datos["FechaAutorizacion"] = (
        fecha_actual
    )
    datos["FechaCreacion"] = (
        fecha_actual
    )
    datos["FechaActualizacion"] = (
        fecha_actual
    )

    autorizacion_existente = (
        buscar_autorizacion_activa(
            db=db,
            id_registro_personal=(
                datos["IdRegistroPersonal"]
            ),
            id_proceso_disciplinario=(
                datos["IdProcesoDisciplinario"]
            ),
            fecha_autorizada=(
                datos["FechaAutorizada"]
            ),
            hora_inicio=(
                datos["HoraInicio"]
            ),
            hora_fin=(
                datos["HoraFin"]
            ),
        )
    )

    if autorizacion_existente:
        raise ValueError(
            "Ya existe una autorización activa para "
            "este expediente, fecha y horario."
        )

    nueva_autorizacion = (
        AutorizacionAgendaDisciplinaria(
            **datos
        )
    )

    try:
        db.add(
            nueva_autorizacion
        )
        db.commit()
        db.refresh(
            nueva_autorizacion
        )

        return nueva_autorizacion

    except IntegrityError as error:
        db.rollback()

        raise ValueError(
            "No fue posible crear la autorización porque "
            "ya existe un registro activo con la misma "
            "fecha y horario."
        ) from error

    except SQLAlchemyError:
        db.rollback()
        raise


def marcar_autorizacion_utilizada(
    db: Session,
    id_autorizacion: int,
    id_agenda_proceso_disciplinario: int,
) -> AutorizacionAgendaDisciplinaria:
    autorizacion = (
        db.query(
            AutorizacionAgendaDisciplinaria
        )
        .filter(
            AutorizacionAgendaDisciplinaria
            .IdAutorizacionAgendaDisciplinaria
            == id_autorizacion,
            AutorizacionAgendaDisciplinaria
            .EstadoAutorizacion
            == "ACTIVA",
            AutorizacionAgendaDisciplinaria
            .Activo
            .is_(True),
        )
        .with_for_update()
        .first()
    )

    if not autorizacion:
        raise ValueError(
            "La autorización no existe, no está activa "
            "o ya fue utilizada."
        )

    fecha_actual = obtener_ahora_colombia()

    autorizacion.IdAgendaProcesoDisciplinario = (
        id_agenda_proceso_disciplinario
    )
    autorizacion.EstadoAutorizacion = (
        "UTILIZADA"
    )
    autorizacion.FechaUtilizacion = (
        fecha_actual
    )
    autorizacion.FechaActualizacion = (
        fecha_actual
    )

    try:
        db.commit()
        db.refresh(
            autorizacion
        )

        return autorizacion

    except SQLAlchemyError:
        db.rollback()
        raise


def consumir_autorizacion_activa(
    db: Session,
    id_registro_personal: int,
    id_proceso_disciplinario: int,
    fecha_autorizada: date,
    hora_inicio: time,
    hora_fin: time,
    id_agenda_proceso_disciplinario: int,
) -> AutorizacionAgendaDisciplinaria:
    autorizacion = buscar_autorizacion_activa(
        db=db,
        id_registro_personal=id_registro_personal,
        id_proceso_disciplinario=(
            id_proceso_disciplinario
        ),
        fecha_autorizada=fecha_autorizada,
        hora_inicio=hora_inicio,
        hora_fin=hora_fin,
        bloquear_registro=True,
    )

    if not autorizacion:
        raise ValueError(
            "No existe una autorización activa para "
            "programar este expediente el viernes "
            "seleccionado y en el horario indicado."
        )

    fecha_actual = obtener_ahora_colombia()

    autorizacion.IdAgendaProcesoDisciplinario = (
        id_agenda_proceso_disciplinario
    )
    autorizacion.EstadoAutorizacion = (
        "UTILIZADA"
    )
    autorizacion.FechaUtilizacion = (
        fecha_actual
    )
    autorizacion.FechaActualizacion = (
        fecha_actual
    )

    try:
        db.commit()
        db.refresh(
            autorizacion
        )

        return autorizacion

    except SQLAlchemyError:
        db.rollback()
        raise


def anular_autorizacion(
    db: Session,
    id_autorizacion: int,
    motivo_anulacion: str,
    usuario_anula: str,
) -> AutorizacionAgendaDisciplinaria:
    autorizacion = (
        db.query(
            AutorizacionAgendaDisciplinaria
        )
        .filter(
            AutorizacionAgendaDisciplinaria
            .IdAutorizacionAgendaDisciplinaria
            == id_autorizacion,
            AutorizacionAgendaDisciplinaria
            .Activo
            .is_(True),
        )
        .with_for_update()
        .first()
    )

    if not autorizacion:
        raise ValueError(
            "La autorización no existe o ya no está activa."
        )

    estado_actual = str(
        autorizacion.EstadoAutorizacion
        or ""
    ).strip().upper()

    if estado_actual == "UTILIZADA":
        raise ValueError(
            "No es posible anular una autorización "
            "que ya fue utilizada."
        )

    if estado_actual == "ANULADA":
        raise ValueError(
            "La autorización ya se encuentra anulada."
        )

    motivo = normalizar_texto(
        motivo_anulacion
    )
    usuario = normalizar_texto(
        usuario_anula
    )

    if not motivo:
        raise ValueError(
            "El motivo de anulación es obligatorio."
        )

    if not usuario:
        raise ValueError(
            "El usuario que anula es obligatorio."
        )

    observacion_anterior = normalizar_texto(
        autorizacion.Observacion
    )

    detalle_anulacion = (
        f"Anulada por {usuario}. "
        f"Motivo: {motivo}"
    )

    autorizacion.Observacion = (
        f"{observacion_anterior}\n"
        f"{detalle_anulacion}"
        if observacion_anterior
        else detalle_anulacion
    )

    autorizacion.EstadoAutorizacion = (
        "ANULADA"
    )
    autorizacion.Activo = False
    autorizacion.FechaActualizacion = (
        obtener_ahora_colombia()
    )

    try:
        db.commit()
        db.refresh(
            autorizacion
        )

        return autorizacion

    except SQLAlchemyError:
        db.rollback()
        raise


def marcar_autorizaciones_vencidas(
    db: Session,
    fecha_referencia: date | None = None,
) -> int:
    fecha_actual = (
        fecha_referencia
        or obtener_ahora_colombia().date()
    )

    autorizaciones = (
        db.query(
            AutorizacionAgendaDisciplinaria
        )
        .filter(
            AutorizacionAgendaDisciplinaria
            .EstadoAutorizacion
            == "ACTIVA",
            AutorizacionAgendaDisciplinaria
            .Activo
            .is_(True),
            AutorizacionAgendaDisciplinaria
            .FechaAutorizada
            < fecha_actual,
        )
        .with_for_update()
        .all()
    )

    if not autorizaciones:
        return 0

    fecha_actualizacion = (
        obtener_ahora_colombia()
    )

    for autorizacion in autorizaciones:
        autorizacion.EstadoAutorizacion = (
            "VENCIDA"
        )
        autorizacion.Activo = False
        autorizacion.FechaActualizacion = (
            fecha_actualizacion
        )

    try:
        db.commit()

        return len(
            autorizaciones
        )

    except SQLAlchemyError:
        db.rollback()
        raise