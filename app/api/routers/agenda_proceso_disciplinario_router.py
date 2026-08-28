# ruff: noqa: B008, BLE001

from datetime import date, datetime, time, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from infrastructure.db.deps import get_db

from domain.models.agenda_proceso_disciplinario import (
    AgendaProcesoDisciplinario,
)
from domain.models.autorizacion_agenda_disciplinaria import (
    AutorizacionAgendaDisciplinaria,
)
from domain.models.citacion_proceso_disciplinario import (
    CitacionProcesoDisciplinario,
)
from domain.models.historial_agenda_proceso_disciplinario import (
    HistorialAgendaProcesoDisciplinario,
)
from domain.models.proceso_disciplinario import (
    ProcesoDisciplinario,
)
from domain.models.solicitud_autorizacion_agenda_disciplinaria import (
    SolicitudAutorizacionAgendaDisciplinaria,
)
from domain.models.tipo_evento_disciplinario import (
    TipoEventoDisciplinario,
)
from domain.schemas.agenda_proceso_disciplinario_schema import (
    AgendaProcesoDisciplinarioCreate,
    AgendaProcesoDisciplinarioResponse,
    AgendaProcesoDisciplinarioUpdate,
)
from domain.schemas.historial_agenda_proceso_disciplinario_schema import (
    CancelarAgendaDisciplinariaRequest,
    HistorialAgendaProcesoDisciplinarioResponse,
    ReprogramarAgendaDisciplinariaRequest,
)
from domain.schemas.tipo_evento_disciplinario_schema import (
    TipoEventoDisciplinarioResponse,
)
from services.correo_proceso_disciplinario_service import (
    TIPO_CANCELACION,
    TIPO_CITACION_INICIAL,
    TIPO_REPROGRAMACION,
    enviar_notificacion_agenda_disciplinaria,
)


router = APIRouter(
    prefix="/api/agenda-disciplinaria",
    tags=["Agenda Disciplinaria"],
)


TIPO_EVENTO_CITACION_ID = 1
DIAS_HABILES_MINIMOS_CITACION = 5
DIAS_HABILES_VENTANA_EXTRAORDINARIA = 5
MAXIMO_CITAS_EXTRAORDINARIAS_SEMANA = 6


class EnlaceVirtualRRLLRequest(BaseModel):
    EnlaceVirtual: str
    UsuarioMovimiento: str | None = None

HORA_INICIO_MANANA = time(7, 10)
HORA_FIN_MANANA = time(13, 0)
HORA_INICIO_TARDE = time(14, 0)
HORA_FIN_JORNADA = time(16, 0)

DURACION_CITACION_MINUTOS = 40
CAPACIDAD_MAXIMA_DIARIA = 11

BLOQUES_EXTRAORDINARIOS_CONTINGENCIA = (
    (time(12, 30), time(13, 0)),
    (time(16, 0), time(16, 30)),
)


COLORES_POR_ESTADO = {
    "PROGRAMADO": "AZUL",
    "EN_CURSO": "AMARILLO",
    "ATENDIDO": "VERDE",
    "CANCELADO": "ROJO",
    "REPROGRAMADO": "GRIS",
}


ZONA_COLOMBIA = timezone(
    timedelta(hours=-5)
)


def intentar_enviar_notificacion_agenda(
    db: Session,
    id_agenda: int,
    tipo_notificacion: str,
    usuario: str | None = None,
) -> dict:
    """
    Intenta enviar la notificación de una agenda ya confirmada.

    Un fallo del servicio de correo o de su trazabilidad no revierte
    la creación, reprogramación o cancelación ya guardada.
    """
    try:
        return enviar_notificacion_agenda_disciplinaria(
            db=db,
            id_agenda=id_agenda,
            tipo_notificacion=tipo_notificacion,
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


def obtener_ahora_colombia() -> datetime:
    return datetime.now(
        ZONA_COLOMBIA
    )


def obtener_fecha_actual_colombia() -> date:
    return obtener_ahora_colombia().date()


def calcular_domingo_pascua(
    anio: int,
) -> date:
    """
    Calcula el Domingo de Pascua mediante
    el algoritmo gregoriano de Meeus/Jones/Butcher.
    """

    a = anio % 19
    b = anio // 100
    c = anio % 100
    d = b // 4
    e = b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i = c // 4
    k = c % 4
    ajuste_semana = (
        32
        + 2 * e
        + 2 * i
        - h
        - k
    ) % 7

    ajuste_excepcion = (
        a
        + 11 * h
        + 22 * ajuste_semana
    ) // 451

    mes = (
        h
        + ajuste_semana
        - 7 * ajuste_excepcion
        + 114
    ) // 31

    dia = (
        (
            h
            + ajuste_semana
            - 7 * ajuste_excepcion
            + 114
        ) % 31
    ) + 1

    return date(
        anio,
        mes,
        dia,
    )


def mover_al_lunes_siguiente(
    fecha_festivo: date,
) -> date:
    dias_hasta_lunes = (
        7 - fecha_festivo.weekday()
    ) % 7

    return fecha_festivo + timedelta(
        days=dias_hasta_lunes
    )


def obtener_festivos_colombia(
    anio: int,
) -> set[date]:
    """
    Retorna los festivos nacionales de Colombia
    para el año indicado, incluidos los trasladados
    al lunes y los dependientes de Semana Santa.
    """

    pascua = calcular_domingo_pascua(
        anio
    )

    festivos = {
        date(anio, 1, 1),
        date(anio, 5, 1),
        date(anio, 7, 20),
        date(anio, 8, 7),
        date(anio, 12, 8),
        date(anio, 12, 25),
        pascua - timedelta(days=3),
        pascua - timedelta(days=2),
        pascua + timedelta(days=43),
        pascua + timedelta(days=64),
        pascua + timedelta(days=71),
    }

    festivos_trasladables = (
        date(anio, 1, 6),
        date(anio, 3, 19),
        date(anio, 6, 29),
        date(anio, 8, 15),
        date(anio, 10, 12),
        date(anio, 11, 1),
        date(anio, 11, 11),
    )

    for festivo in festivos_trasladables:
        festivos.add(
            mover_al_lunes_siguiente(
                festivo
            )
        )

    return festivos


def es_festivo_colombia(
    fecha_valor: date,
) -> bool:
    return fecha_valor in obtener_festivos_colombia(
        fecha_valor.year
    )


def es_dia_habil_colombia(
    fecha_valor: date,
) -> bool:
    return (
        fecha_valor.weekday() < 5
        and not es_festivo_colombia(
            fecha_valor
        )
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


def validar_proceso_abierto(
    db: Session,
    id_proceso: int,
) -> ProcesoDisciplinario:
    proceso = obtener_proceso_o_error(
        db=db,
        id_proceso=id_proceso,
    )

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
                "IdProcesoDisciplinario": id_proceso,
                "EstadoProceso": proceso.EstadoProceso,
            },
        )

    return proceso


def obtener_color_por_estado(
    estado_agenda: str,
) -> str | None:
    if not estado_agenda:
        return None

    return COLORES_POR_ESTADO.get(
        estado_agenda.upper()
    )


def obtener_fecha_sin_hora(
    valor: date | datetime,
) -> date:
    if isinstance(valor, datetime):
        return valor.date()

    return valor


def sumar_dias_habiles(
    fecha_inicial: date,
    cantidad_dias: int,
) -> date:
    fecha_resultado = fecha_inicial
    dias_sumados = 0

    while dias_sumados < cantidad_dias:
        fecha_resultado += timedelta(days=1)

        if es_dia_habil_colombia(
            fecha_resultado
        ):
            dias_sumados += 1

    return fecha_resultado


def obtener_ventana_extraordinaria(
    fecha_base: date | None = None,
) -> list[date]:
    """Devuelve los próximos cinco días hábiles, sin incluir hoy."""
    fecha_actual = fecha_base or obtener_fecha_actual_colombia()
    fechas: list[date] = []
    fecha_revision = fecha_actual

    while len(fechas) < DIAS_HABILES_VENTANA_EXTRAORDINARIA:
        fecha_revision += timedelta(days=1)
        if es_dia_habil_colombia(fecha_revision):
            fechas.append(fecha_revision)

    return fechas


def obtener_limites_semana(fecha_valor: date) -> tuple[date, date]:
    inicio = fecha_valor - timedelta(days=fecha_valor.weekday())
    return inicio, inicio + timedelta(days=6)


def contar_citaciones_extraordinarias_semana(
    db: Session,
    fecha_evento: date,
    id_proceso_excluir: int | None = None,
) -> int:
    inicio_semana, fin_semana = obtener_limites_semana(fecha_evento)
    consulta = (
        db.query(CitacionProcesoDisciplinario)
        .filter(
            CitacionProcesoDisciplinario.EsExtraordinaria.is_(True),
            CitacionProcesoDisciplinario.FechaCitacion >= inicio_semana,
            CitacionProcesoDisciplinario.FechaCitacion <= fin_semana,
        )
    )

    if id_proceso_excluir is not None:
        consulta = consulta.filter(
            CitacionProcesoDisciplinario.IdProcesoDisciplinario
            != id_proceso_excluir
        )

    return consulta.count()


def bloquear_cupo_extraordinario_semana(
    db: Session,
    fecha_evento: date,
) -> None:
    """Serializa reservas de la misma semana dentro de la transacción."""
    inicio_semana, _ = obtener_limites_semana(fecha_evento)
    clave = int(inicio_semana.strftime("%Y%m%d"))
    db.execute(
        text("SELECT pg_advisory_xact_lock(:clave)"),
        {"clave": clave},
    )


def validar_cupo_extraordinario_semana(
    db: Session,
    fecha_evento: date,
    id_proceso_excluir: int | None = None,
    bloquear: bool = False,
) -> int:
    if bloquear:
        bloquear_cupo_extraordinario_semana(db, fecha_evento)

    usados = contar_citaciones_extraordinarias_semana(
        db=db,
        fecha_evento=fecha_evento,
        id_proceso_excluir=id_proceso_excluir,
    )

    if usados >= MAXIMO_CITAS_EXTRAORDINARIAS_SEMANA:
        inicio_semana, fin_semana = obtener_limites_semana(fecha_evento)
        raise HTTPException(
            status_code=409,
            detail={
                "codigo": "CUPO_EXTRAORDINARIO_SEMANAL_AGOTADO",
                "mensaje": (
                    "La semana seleccionada ya alcanzó el máximo de "
                    f"{MAXIMO_CITAS_EXTRAORDINARIAS_SEMANA} citas extraordinarias."
                ),
                "cupoMaximo": MAXIMO_CITAS_EXTRAORDINARIAS_SEMANA,
                "cuposUsados": usados,
                "inicioSemana": inicio_semana,
                "finSemana": fin_semana,
            },
        )

    return usados


def validar_fecha_minima_citacion(
    fecha_evento: date,
    fecha_creacion_evento: date | datetime,
) -> None:
    fecha_base = obtener_fecha_sin_hora(
        fecha_creacion_evento
    )

    fecha_minima = sumar_dias_habiles(
        fecha_base,
        DIAS_HABILES_MINIMOS_CITACION,
    )

    if fecha_evento < fecha_minima:
        raise HTTPException(
            status_code=400,
            detail={
                "mensaje": (
                    "La citación debe programarse como mínimo "
                    f"{DIAS_HABILES_MINIMOS_CITACION} días hábiles "
                    "después de la creación inicial del evento."
                ),
                "fechaCreacionEvento": (
                    fecha_base.strftime("%d/%m/%Y")
                ),
                "fechaIngresada": (
                    fecha_evento.strftime("%d/%m/%Y")
                ),
                "fechaMinimaPermitida": (
                    fecha_minima.strftime("%d/%m/%Y")
                ),
            },
        )


def convertir_hora_a_minutos(
    valor: time,
) -> int:
    return (
        valor.hour * 60
        + valor.minute
    )


def convertir_minutos_a_hora(
    minutos: int,
) -> time:
    horas = minutos // 60
    minutos_restantes = minutos % 60

    return time(
        hour=horas,
        minute=minutos_restantes,
    )


def calcular_hora_fin_citacion(
    hora_inicio: time,
) -> time:
    minutos_inicio = convertir_hora_a_minutos(
        hora_inicio
    )

    minutos_fin = (
        minutos_inicio
        + DURACION_CITACION_MINUTOS
    )

    return convertir_minutos_a_hora(
        minutos_fin
    )


def generar_bloques_citacion() -> list[tuple[time, time]]:
    bloques: list[tuple[time, time]] = []

    inicio_manana = convertir_hora_a_minutos(
        HORA_INICIO_MANANA
    )
    fin_manana = convertir_hora_a_minutos(
        HORA_FIN_MANANA
    )

    hora_actual = inicio_manana

    while (
        hora_actual
        + DURACION_CITACION_MINUTOS
        <= fin_manana
    ):
        hora_inicio = convertir_minutos_a_hora(
            hora_actual
        )
        hora_fin = calcular_hora_fin_citacion(
            hora_inicio
        )

        bloques.append(
            (hora_inicio, hora_fin)
        )

        hora_actual += (
            DURACION_CITACION_MINUTOS
        )

    inicio_tarde = convertir_hora_a_minutos(
        HORA_INICIO_TARDE
    )
    fin_jornada = convertir_hora_a_minutos(
        HORA_FIN_JORNADA
    )

    hora_actual = inicio_tarde

    while (
        hora_actual
        + DURACION_CITACION_MINUTOS
        <= fin_jornada
    ):
        hora_inicio = convertir_minutos_a_hora(
            hora_actual
        )
        hora_fin = calcular_hora_fin_citacion(
            hora_inicio
        )

        bloques.append(
            (hora_inicio, hora_fin)
        )

        hora_actual += (
            DURACION_CITACION_MINUTOS
        )

    return bloques


BLOQUES_CITACION = generar_bloques_citacion()


def validar_dia_habil_agenda(
    fecha_evento: date,
    permitir_viernes: bool = False,
) -> None:
    if (
        fecha_evento.weekday() == 4
        and not permitir_viernes
    ):
        raise HTTPException(
            status_code=409,
            detail={
                "codigo": "VIERNES_REQUIERE_AUTORIZACION",
                "mensaje": (
                    "Los viernes no se programan citaciones "
                    "disciplinarias de manera regular. Si se trata "
                    "de un caso crítico, solicite autorización previa "
                    "a Relaciones Laborales."
                ),
                "fechaIngresada": (
                    fecha_evento.strftime("%d/%m/%Y")
                ),
                "requiereAutorizacionRRLL": True,
            },
        )

    if fecha_evento.weekday() >= 5:
        raise HTTPException(
            status_code=400,
            detail={
                "mensaje": (
                    "Las citaciones no pueden programarse "
                    "los sábados ni domingos."
                ),
                "fechaIngresada": (
                    fecha_evento.strftime("%d/%m/%Y")
                ),
            },
        )

    if es_festivo_colombia(
        fecha_evento
    ):
        raise HTTPException(
            status_code=400,
            detail={
                "mensaje": (
                    "La fecha seleccionada es festivo "
                    "en Colombia y no admite citaciones."
                ),
                "fechaIngresada": (
                    fecha_evento.strftime("%d/%m/%Y")
                ),
            },
        )


def buscar_solicitud_viernes_aprobada(
    db: Session,
    id_registro_personal: int,
    id_proceso_disciplinario: int,
    fecha_evento: date,
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
            == fecha_evento,
            SolicitudAutorizacionAgendaDisciplinaria
            .EstadoSolicitud
            == "APROBADA",
            SolicitudAutorizacionAgendaDisciplinaria
            .Activo
            .is_(True),
        )
    )

    if bloquear_registro:
        consulta = consulta.with_for_update()

    return consulta.order_by(
        SolicitudAutorizacionAgendaDisciplinaria
        .IdSolicitudAutorizacion
        .desc()
    ).first()


def obtener_solicitud_viernes_aprobada_o_error(
    db: Session,
    id_registro_personal: int,
    id_proceso_disciplinario: int,
    fecha_evento: date,
    bloquear_registro: bool = False,
) -> SolicitudAutorizacionAgendaDisciplinaria | None:
    if fecha_evento.weekday() != 4:
        return None

    solicitud = buscar_solicitud_viernes_aprobada(
        db=db,
        id_registro_personal=id_registro_personal,
        id_proceso_disciplinario=(
            id_proceso_disciplinario
        ),
        fecha_evento=fecha_evento,
        bloquear_registro=bloquear_registro,
    )

    if solicitud:
        return solicitud

    raise HTTPException(
        status_code=409,
        detail={
            "codigo": "VIERNES_REQUIERE_AUTORIZACION",
            "mensaje": (
                "Relaciones Laborales no ha aprobado este "
                "viernes para el expediente indicado."
            ),
            "IdRegistroPersonal": id_registro_personal,
            "IdProcesoDisciplinario": (
                id_proceso_disciplinario
            ),
            "fechaIngresada": (
                fecha_evento.strftime("%d/%m/%Y")
            ),
            "requiereAutorizacionRRLL": True,
        },
    )


def marcar_autorizacion_como_utilizada(
    autorizacion: AutorizacionAgendaDisciplinaria,
    id_agenda: int,
    fecha_utilizacion: datetime,
) -> None:
    autorizacion.IdAgendaProcesoDisciplinario = (
        id_agenda
    )
    autorizacion.EstadoAutorizacion = "UTILIZADA"
    autorizacion.FechaUtilizacion = fecha_utilizacion
    autorizacion.FechaActualizacion = fecha_utilizacion


def validar_bloque_citacion(
    hora_inicio: time,
    hora_fin: time,
) -> None:
    bloque_encontrado = any(
        hora_inicio == bloque_inicio
        and hora_fin == bloque_fin
        for bloque_inicio, bloque_fin
        in BLOQUES_CITACION
    )

    if not bloque_encontrado:
        horarios_permitidos = [
            bloque_inicio.strftime("%H:%M")
            for bloque_inicio, _
            in BLOQUES_CITACION
        ]

        raise HTTPException(
            status_code=400,
            detail={
                "mensaje": (
                    "La citación debe utilizar uno de los "
                    "bloques habilitados de 40 minutos."
                ),
                "duracionMinutos": (
                    DURACION_CITACION_MINUTOS
                ),
                "horariosPermitidos": (
                    horarios_permitidos
                ),
                "horarioAlmuerzo": (
                    "13:00 a 14:00"
                ),
                "finJornada": (
                    "16:00"
                ),
            },
        )


def buscar_cruce_horario(
    db: Session,
    fecha_evento: date,
    hora_inicio: time,
    hora_fin: time,
    id_agenda_excluir: int | None = None,
) -> AgendaProcesoDisciplinario | None:
    consulta = (
        db.query(AgendaProcesoDisciplinario)
        .filter(
            AgendaProcesoDisciplinario.FechaEvento
            == fecha_evento,
            AgendaProcesoDisciplinario.Activo
            .is_(True),
            AgendaProcesoDisciplinario.EstadoAgenda
            != "CANCELADO",
            AgendaProcesoDisciplinario.HoraInicio
            < hora_fin,
            AgendaProcesoDisciplinario.HoraFin
            > hora_inicio,
        )
    )

    if id_agenda_excluir is not None:
        consulta = consulta.filter(
            AgendaProcesoDisciplinario
            .IdAgendaProcesoDisciplinario
            != id_agenda_excluir
        )

    return consulta.first()


def validar_cruce_horario(
    db: Session,
    fecha_evento: date,
    hora_inicio: time,
    hora_fin: time,
    id_agenda_excluir: int | None = None,
) -> None:
    evento_cruzado = buscar_cruce_horario(
        db=db,
        fecha_evento=fecha_evento,
        hora_inicio=hora_inicio,
        hora_fin=hora_fin,
        id_agenda_excluir=id_agenda_excluir,
    )

    if evento_cruzado:
        raise HTTPException(
            status_code=409,
            detail={
                "mensaje": (
                    "El horario seleccionado ya se encuentra "
                    "ocupado por otro evento disciplinario."
                ),
                "fechaEvento": (
                    fecha_evento.strftime("%d/%m/%Y")
                ),
                "horaSolicitada": (
                    f"{hora_inicio.strftime('%H:%M')} "
                    f"a {hora_fin.strftime('%H:%M')}"
                ),
                "eventoEnConflicto": {
                    "IdAgendaProcesoDisciplinario": (
                        evento_cruzado
                        .IdAgendaProcesoDisciplinario
                    ),
                    "IdRegistroPersonal": (
                        evento_cruzado
                        .IdRegistroPersonal
                    ),
                    "HoraInicio": (
                        evento_cruzado
                        .HoraInicio
                        .strftime("%H:%M")
                    ),
                    "HoraFin": (
                        evento_cruzado
                        .HoraFin
                        .strftime("%H:%M")
                    ),
                    "EstadoAgenda": (
                        evento_cruzado
                        .EstadoAgenda
                    ),
                },
            },
        )


def obtener_bloques_ordinarios_disponibles(
    db: Session,
    fecha_evento: date,
) -> list[tuple[time, time]]:
    return [
        (hora_inicio, hora_fin)
        for hora_inicio, hora_fin in BLOQUES_CITACION
        if buscar_cruce_horario(
            db=db,
            fecha_evento=fecha_evento,
            hora_inicio=hora_inicio,
            hora_fin=hora_fin,
        ) is None
    ]


def obtener_bloques_extraordinarios_disponibles(
    db: Session,
    fecha_evento: date,
) -> tuple[list[tuple[time, time]], bool]:
    bloques_ordinarios = obtener_bloques_ordinarios_disponibles(
        db=db,
        fecha_evento=fecha_evento,
    )

    if bloques_ordinarios:
        return bloques_ordinarios, False

    bloques_contingencia = [
        (hora_inicio, hora_fin)
        for hora_inicio, hora_fin in BLOQUES_EXTRAORDINARIOS_CONTINGENCIA
        if buscar_cruce_horario(
            db=db,
            fecha_evento=fecha_evento,
            hora_inicio=hora_inicio,
            hora_fin=hora_fin,
        ) is None
    ]
    return bloques_contingencia, True


def validar_programacion_extraordinaria_citacion(
    db: Session,
    fecha_evento: date,
    hora_inicio: time,
    id_proceso_disciplinario: int | None = None,
    bloquear_cupo: bool = False,
) -> time:
    fechas_permitidas = obtener_ventana_extraordinaria()

    if fecha_evento not in fechas_permitidas:
        raise HTTPException(
            status_code=400,
            detail={
                "codigo": "FECHA_EXTRAORDINARIA_NO_PERMITIDA",
                "mensaje": (
                    "La cita extraordinaria solo puede programarse dentro "
                    "de los próximos cinco días hábiles."
                ),
                "fechasPermitidas": fechas_permitidas,
            },
        )

    # En extraordinarias el viernes es un día hábil permitido y no requiere RRLL.
    validar_dia_habil_agenda(fecha_evento, permitir_viernes=True)
    validar_cupo_extraordinario_semana(
        db=db,
        fecha_evento=fecha_evento,
        id_proceso_excluir=id_proceso_disciplinario,
        bloquear=bloquear_cupo,
    )

    bloques_disponibles, usa_contingencia = (
        obtener_bloques_extraordinarios_disponibles(
            db=db,
            fecha_evento=fecha_evento,
        )
    )
    bloque = next(
        (
            (inicio, fin)
            for inicio, fin in bloques_disponibles
            if inicio == hora_inicio
        ),
        None,
    )

    if bloque is None:
        raise HTTPException(
            status_code=409,
            detail={
                "codigo": "HORARIO_EXTRAORDINARIO_NO_DISPONIBLE",
                "mensaje": (
                    "El horario extraordinario seleccionado ya no está disponible."
                ),
                "usaHorariosContingencia": usa_contingencia,
            },
        )

    validar_cruce_horario(
        db=db,
        fecha_evento=fecha_evento,
        hora_inicio=bloque[0],
        hora_fin=bloque[1],
    )
    return bloque[1]


def validar_programacion_citacion(
    db: Session,
    fecha_evento: date,
    hora_inicio: time,
    hora_fin: time,
    id_registro_personal: int,
    id_proceso_disciplinario: int,
    id_agenda_excluir: int | None = None,
    bloquear_autorizacion: bool = False,
) -> SolicitudAutorizacionAgendaDisciplinaria | None:
    solicitud_viernes = (
        obtener_solicitud_viernes_aprobada_o_error(
            db=db,
            id_registro_personal=(
                id_registro_personal
            ),
            id_proceso_disciplinario=(
                id_proceso_disciplinario
            ),
            fecha_evento=fecha_evento,
            bloquear_registro=(
                bloquear_autorizacion
            ),
        )
    )

    validar_dia_habil_agenda(
        fecha_evento,
        permitir_viernes=(
            solicitud_viernes is not None
        ),
    )

    validar_bloque_citacion(
        hora_inicio=hora_inicio,
        hora_fin=hora_fin,
    )

    validar_cruce_horario(
        db=db,
        fecha_evento=fecha_evento,
        hora_inicio=hora_inicio,
        hora_fin=hora_fin,
        id_agenda_excluir=id_agenda_excluir,
    )

    return solicitud_viernes


def consultar_eventos_enriquecidos(
    db: Session,
    condicion_sql: str = "",
    parametros: dict | None = None,
):
    sql = text(
        f"""
        SELECT
            ag."IdAgendaProcesoDisciplinario",
            ag."IdProcesoDisciplinario",
            ag."IdRegistroPersonal",
            rp."NumeroIdentificacion",
            rp."Nombres",
            rp."Apellidos",
            CONCAT(
                COALESCE(rp."Nombres", ''),
                ' ',
                COALESCE(rp."Apellidos", '')
            ) AS "NombreCompleto",
            ag."IdTipoEventoDisciplinario",
            te."Nombre" AS "TipoEvento",
            ag."FechaEvento",
            ag."HoraInicio",
            ag."HoraFin",
            ag."Modalidad",
            ag."LugarCitacion",
            ag."Observacion",
            ag."EstadoAgenda",
            ag."ColorAgenda",
            pd."EstadoProceso",
            ag."UsuarioAgenda",
            ag."FechaCreacion",
            ag."FechaActualizacion",
            ag."UsuarioActualizacion",
            ag."Activo"
        FROM public."AgendaProcesoDisciplinario" ag
        INNER JOIN public."RegistroPersonal" rp
            ON rp."IdRegistroPersonal" =
               ag."IdRegistroPersonal"
        INNER JOIN public."TipoEventoDisciplinario" te
            ON te."IdTipoEventoDisciplinario" =
               ag."IdTipoEventoDisciplinario"
        INNER JOIN public."ProcesoDisciplinario" pd
            ON pd."IdProcesoDisciplinario" =
               ag."IdProcesoDisciplinario"
        WHERE ag."Activo" = TRUE
        {condicion_sql}
        ORDER BY
            ag."FechaEvento" ASC,
            ag."HoraInicio" ASC;
        """
    )

    return db.execute(
        sql,
        parametros or {},
    ).mappings().all()


@router.get(
    "/tipos-evento",
    response_model=list[
        TipoEventoDisciplinarioResponse
    ],
)
def listar_tipos_evento(
    db: Session = Depends(get_db),
):
    return (
        db.query(TipoEventoDisciplinario)
        .filter(
            TipoEventoDisciplinario.Activo.is_(True)
        )
        .order_by(
            TipoEventoDisciplinario
            .IdTipoEventoDisciplinario
            .asc()
        )
        .all()
    )


@router.get("/configuracion-citacion")
def obtener_configuracion_citacion():
    fecha_servidor = (
        obtener_fecha_actual_colombia()
    )

    fecha_minima = sumar_dias_habiles(
        fecha_servidor,
        DIAS_HABILES_MINIMOS_CITACION,
    )

    return {
        "fechaServidor": fecha_servidor,
        "fechaMinimaPermitida": fecha_minima,
        "diasHabilesMinimos": (
            DIAS_HABILES_MINIMOS_CITACION
        ),
        "duracionMinutos": (
            DURACION_CITACION_MINUTOS
        ),
        "capacidadMaxima": (
            CAPACIDAD_MAXIMA_DIARIA
        ),
        "viernesAtencionRegular": False,
        "viernesRequiereAutorizacion": True,
        "horaInicioJornada": (
            HORA_INICIO_MANANA.strftime("%H:%M")
        ),
        "horaInicioAlmuerzo": (
            HORA_FIN_MANANA.strftime("%H:%M")
        ),
        "horaFinAlmuerzo": (
            HORA_INICIO_TARDE.strftime("%H:%M")
        ),
        "horaFinJornada": (
            HORA_FIN_JORNADA.strftime("%H:%M")
        ),
        "horariosBase": [
            {
                "HoraInicio": (
                    hora_inicio.strftime(
                        "%H:%M"
                    )
                ),
                "HoraFin": (
                    hora_fin.strftime(
                        "%H:%M"
                    )
                ),
                "Etiqueta": (
                    f"{hora_inicio.strftime('%H:%M')} "
                    f"- {hora_fin.strftime('%H:%M')}"
                ),
            }
            for hora_inicio, hora_fin
            in BLOQUES_CITACION
        ],
    }


@router.get("/festivos/{anio}")
def listar_festivos_colombia(
    anio: int,
):
    if anio < 2000 or anio > 2100:
        raise HTTPException(
            status_code=400,
            detail=(
                "El año consultado debe estar "
                "entre 2000 y 2100."
            ),
        )

    festivos = sorted(
        obtener_festivos_colombia(
            anio
        )
    )

    return {
        "anio": anio,
        "total": len(festivos),
        "festivos": festivos,
    }


@router.get("/configuracion-citacion-extraordinaria")
def obtener_configuracion_citacion_extraordinaria(
    db: Session = Depends(get_db),
):
    fechas = obtener_ventana_extraordinaria()
    semanas: dict[str, dict] = {}

    for fecha_valor in fechas:
        inicio, fin = obtener_limites_semana(fecha_valor)
        clave = inicio.isoformat()
        if clave not in semanas:
            usados = contar_citaciones_extraordinarias_semana(
                db=db,
                fecha_evento=fecha_valor,
            )
            semanas[clave] = {
                "inicioSemana": inicio,
                "finSemana": fin,
                "cuposUsados": usados,
                "cuposDisponibles": max(
                    0,
                    MAXIMO_CITAS_EXTRAORDINARIAS_SEMANA - usados,
                ),
            }

    return {
        "fechaServidor": obtener_fecha_actual_colombia(),
        "cantidadDiasHabiles": DIAS_HABILES_VENTANA_EXTRAORDINARIA,
        "fechasPermitidas": fechas,
        "fechaMinimaPermitida": fechas[0],
        "fechaMaximaPermitida": fechas[-1],
        "maximoSemanal": MAXIMO_CITAS_EXTRAORDINARIAS_SEMANA,
        "semanas": list(semanas.values()),
        "horariosContingencia": [
            {
                "HoraInicio": inicio.strftime("%H:%M"),
                "HoraFin": fin.strftime("%H:%M"),
                "Etiqueta": f"{inicio.strftime('%H:%M')} - {fin.strftime('%H:%M')}",
            }
            for inicio, fin in BLOQUES_EXTRAORDINARIOS_CONTINGENCIA
        ],
    }


@router.get("/horarios-extraordinarios/{fecha_evento}")
def obtener_horarios_extraordinarios(
    fecha_evento: date,
    id_proceso_disciplinario: int | None = None,
    db: Session = Depends(get_db),
):
    fechas_permitidas = obtener_ventana_extraordinaria()
    if fecha_evento not in fechas_permitidas:
        raise HTTPException(
            status_code=400,
            detail={
                "codigo": "FECHA_EXTRAORDINARIA_NO_PERMITIDA",
                "mensaje": (
                    "Seleccione uno de los próximos cinco días hábiles "
                    "habilitados para citas extraordinarias."
                ),
                "fechasPermitidas": fechas_permitidas,
            },
        )

    validar_dia_habil_agenda(fecha_evento, permitir_viernes=True)
    usados = validar_cupo_extraordinario_semana(
        db=db,
        fecha_evento=fecha_evento,
        id_proceso_excluir=id_proceso_disciplinario,
    )
    bloques, usa_contingencia = obtener_bloques_extraordinarios_disponibles(
        db=db,
        fecha_evento=fecha_evento,
    )

    return {
        "fecha": fecha_evento,
        "esExtraordinaria": True,
        "maximoSemanal": MAXIMO_CITAS_EXTRAORDINARIAS_SEMANA,
        "cuposUsadosSemana": usados,
        "cuposDisponiblesSemana": (
            MAXIMO_CITAS_EXTRAORDINARIAS_SEMANA - usados
        ),
        "usaHorariosContingencia": usa_contingencia,
        "horarios": [
            {
                "HoraInicio": inicio.strftime("%H:%M"),
                "HoraFin": fin.strftime("%H:%M"),
                "Etiqueta": f"{inicio.strftime('%H:%M')} - {fin.strftime('%H:%M')}",
                "EsContingencia": usa_contingencia,
            }
            for inicio, fin in bloques
        ],
    }


@router.get("/horarios-disponibles/{fecha_evento}")
def obtener_horarios_disponibles(
    fecha_evento: date,
    id_registro_personal: int | None = None,
    id_proceso_disciplinario: int | None = None,
    db: Session = Depends(get_db),
):
    fecha_servidor = (
        obtener_fecha_actual_colombia()
    )

    fecha_minima = sumar_dias_habiles(
        fecha_servidor,
        DIAS_HABILES_MINIMOS_CITACION,
    )

    if fecha_evento < fecha_minima:
        raise HTTPException(
            status_code=400,
            detail={
                "mensaje": (
                    "La fecha seleccionada no cumple "
                    "el mínimo de cinco días hábiles."
                ),
                "fechaServidor": (
                    fecha_servidor.strftime(
                        "%d/%m/%Y"
                    )
                ),
                "fechaIngresada": (
                    fecha_evento.strftime(
                        "%d/%m/%Y"
                    )
                ),
                "fechaMinimaPermitida": (
                    fecha_minima.strftime(
                        "%d/%m/%Y"
                    )
                ),
            },
        )

    es_viernes = fecha_evento.weekday() == 4

    if es_viernes and (
        id_registro_personal is None
        or id_proceso_disciplinario is None
    ):
        raise HTTPException(
            status_code=409,
            detail={
                "codigo": "VIERNES_REQUIERE_AUTORIZACION",
                "mensaje": (
                    "Para consultar horarios de un viernes "
                    "debe indicar el trabajador y el expediente "
                    "disciplinario autorizados."
                ),
                "fechaIngresada": (
                    fecha_evento.strftime("%d/%m/%Y")
                ),
                "requiereAutorizacionRRLL": True,
            },
        )

    validar_dia_habil_agenda(
        fecha_evento,
        permitir_viernes=es_viernes,
    )

    solicitud_viernes_aprobada = None

    if es_viernes:
        solicitud_viernes_aprobada = (
            obtener_solicitud_viernes_aprobada_o_error(
                db=db,
                id_registro_personal=(
                    id_registro_personal
                ),
                id_proceso_disciplinario=(
                    id_proceso_disciplinario
                ),
                fecha_evento=fecha_evento,
            )
        )

    horarios_disponibles = []

    for hora_inicio, hora_fin in BLOQUES_CITACION:
        evento_cruzado = buscar_cruce_horario(
            db=db,
            fecha_evento=fecha_evento,
            hora_inicio=hora_inicio,
            hora_fin=hora_fin,
        )

        if evento_cruzado is None:
            horarios_disponibles.append(
                {
                    "HoraInicio": (
                        hora_inicio.strftime("%H:%M")
                    ),
                    "HoraFin": (
                        hora_fin.strftime("%H:%M")
                    ),
                    "Etiqueta": (
                        f"{hora_inicio.strftime('%H:%M')} "
                        f"- {hora_fin.strftime('%H:%M')}"
                    ),
                }
            )

    return {
        "fecha": fecha_evento,
        "duracionMinutos": (
            DURACION_CITACION_MINUTOS
        ),
        "capacidadMaxima": (
            CAPACIDAD_MAXIMA_DIARIA
        ),
        "cuposDisponibles": (
            len(horarios_disponibles)
        ),
        "esViernes": es_viernes,
        "requiereAutorizacionRRLL": (
            es_viernes
            and solicitud_viernes_aprobada is None
        ),
        "viernesAprobadoRRLL": (
            solicitud_viernes_aprobada is not None
        ),
        "horarios": horarios_disponibles,
    }


@router.post(
    "/",
    response_model=AgendaProcesoDisciplinarioResponse,
)
def crear_evento_agenda(
    data: AgendaProcesoDisciplinarioCreate,
    db: Session = Depends(get_db),
):
    validar_proceso_abierto(
        db=db,
        id_proceso=data.IdProcesoDisciplinario,
    )

    tipo_evento = (
        db.query(TipoEventoDisciplinario)
        .filter(
            TipoEventoDisciplinario
            .IdTipoEventoDisciplinario
            == data.IdTipoEventoDisciplinario,
            TipoEventoDisciplinario.Activo.is_(True),
        )
        .first()
    )

    if not tipo_evento:
        raise HTTPException(
            status_code=404,
            detail=(
                "Tipo de evento disciplinario "
                "no encontrado"
            ),
        )

    fecha_creacion_evento = obtener_ahora_colombia()
    datos_evento = data.model_dump()
    solicitud_viernes_aprobada = None

    if (
        data.IdTipoEventoDisciplinario
        == TIPO_EVENTO_CITACION_ID
    ):
        hora_fin_calculada = (
            calcular_hora_fin_citacion(
                data.HoraInicio
            )
        )

        validar_fecha_minima_citacion(
            fecha_evento=data.FechaEvento,
            fecha_creacion_evento=fecha_creacion_evento,
        )

        solicitud_viernes_aprobada = (
            validar_programacion_citacion(
                db=db,
                fecha_evento=data.FechaEvento,
                hora_inicio=data.HoraInicio,
                hora_fin=hora_fin_calculada,
                id_registro_personal=(
                    data.IdRegistroPersonal
                ),
                id_proceso_disciplinario=(
                    data.IdProcesoDisciplinario
                ),
                bloquear_autorizacion=True,
            )
        )

        datos_evento["HoraFin"] = (
            hora_fin_calculada
        )
    else:
        if data.HoraFin <= data.HoraInicio:
            raise HTTPException(
                status_code=400,
                detail=(
                    "La hora fin debe ser mayor "
                    "a la hora inicio"
                ),
            )

    try:
        estado_agenda = (
            datos_evento.get("EstadoAgenda")
            or "PROGRAMADO"
        ).upper()

        datos_evento["EstadoAgenda"] = (
            estado_agenda
        )

        datos_evento["ColorAgenda"] = (
            obtener_color_por_estado(
                estado_agenda
            )
            or datos_evento.get("ColorAgenda")
            or "AZUL"
        )

        datos_evento["FechaCreacion"] = (
            fecha_creacion_evento
        )

        nuevo_evento = (
            AgendaProcesoDisciplinario(
                **datos_evento
            )
        )

        db.add(nuevo_evento)
        db.flush()

        db.commit()
        db.refresh(nuevo_evento)

        return nuevo_evento

    except SQLAlchemyError as error:
        db.rollback()

        raise HTTPException(
            status_code=500,
            detail=(
                "No se pudo crear el evento "
                "de agenda disciplinaria"
            ),
        ) from error


@router.get(
    "/",
    response_model=list[
        AgendaProcesoDisciplinarioResponse
    ],
)
def listar_agenda(
    db: Session = Depends(get_db),
):
    return (
        db.query(AgendaProcesoDisciplinario)
        .filter(
            AgendaProcesoDisciplinario
            .Activo
            .is_(True)
        )
        .order_by(
            AgendaProcesoDisciplinario
            .FechaEvento
            .asc(),
            AgendaProcesoDisciplinario
            .HoraInicio
            .asc(),
        )
        .all()
    )


@router.get("/general/rango")
def listar_agenda_general_por_rango(
    fecha_desde: date,
    fecha_hasta: date,
    estado: str | None = None,
    buscar: str | None = None,
    db: Session = Depends(get_db),
):
    """
    Consulta la agenda general de RRLL por rango de fechas.

    Permite consultar una semana o un mes completo y filtrar
    por estado, nombre del trabajador o número de documento.
    """
    if fecha_desde > fecha_hasta:
        raise HTTPException(
            status_code=400,
            detail={
                "mensaje": (
                    "La fecha inicial no puede ser mayor "
                    "que la fecha final."
                ),
                "fechaDesde": fecha_desde,
                "fechaHasta": fecha_hasta,
            },
        )

    cantidad_dias = (
        fecha_hasta - fecha_desde
    ).days + 1

    if cantidad_dias > 366:
        raise HTTPException(
            status_code=400,
            detail={
                "mensaje": (
                    "El rango consultado no puede superar "
                    "366 días calendario."
                ),
                "cantidadDias": cantidad_dias,
            },
        )

    condiciones = [
        'AND ag."FechaEvento" BETWEEN '
        ':fecha_desde AND :fecha_hasta'
    ]

    parametros = {
        "fecha_desde": fecha_desde,
        "fecha_hasta": fecha_hasta,
    }

    estado_normalizado = str(
        estado or ""
    ).strip().upper()

    if estado_normalizado:
        if estado_normalizado not in COLORES_POR_ESTADO:
            raise HTTPException(
                status_code=400,
                detail={
                    "mensaje": (
                        "El estado indicado no es válido "
                        "para la agenda disciplinaria."
                    ),
                    "estadoIngresado": estado_normalizado,
                    "estadosPermitidos": sorted(
                        COLORES_POR_ESTADO.keys()
                    ),
                },
            )

        condiciones.append(
            """
            AND UPPER(
                COALESCE(
                    ag."EstadoAgenda",
                    ''
                )
            ) = :estado
            """
        )
        parametros["estado"] = estado_normalizado

    buscar_normalizado = str(
        buscar or ""
    ).strip()

    if buscar_normalizado:
        condiciones.append(
            """
            AND (
                CONCAT(
                    COALESCE(rp."Nombres", ''),
                    ' ',
                    COALESCE(rp."Apellidos", '')
                ) ILIKE :buscar
                OR COALESCE(
                    rp."NumeroIdentificacion",
                    ''
                ) ILIKE :buscar
            )
            """
        )
        parametros["buscar"] = (
            f"%{buscar_normalizado}%"
        )

    rows = consultar_eventos_enriquecidos(
        db=db,
        condicion_sql="\n".join(
            condiciones
        ),
        parametros=parametros,
    )

    eventos = [
        dict(row)
        for row in rows
    ]

    resumen_estados = {
        estado_agenda: 0
        for estado_agenda in COLORES_POR_ESTADO
    }

    resumen_dias = {}

    for evento in eventos:
        estado_evento = str(
            evento.get("EstadoAgenda") or ""
        ).strip().upper()

        if estado_evento in resumen_estados:
            resumen_estados[estado_evento] += 1

        fecha_evento = evento.get(
            "FechaEvento"
        )

        fecha_clave = (
            fecha_evento.isoformat()
            if hasattr(fecha_evento, "isoformat")
            else str(fecha_evento or "")
        )

        if fecha_clave not in resumen_dias:
            resumen_dias[fecha_clave] = {
                "fecha": fecha_evento,
                "total": 0,
                "estados": {
                    estado_agenda: 0
                    for estado_agenda
                    in COLORES_POR_ESTADO
                },
            }

        resumen_dias[
            fecha_clave
        ]["total"] += 1

        if estado_evento in COLORES_POR_ESTADO:
            resumen_dias[
                fecha_clave
            ]["estados"][
                estado_evento
            ] += 1

    return {
        "fechaDesde": fecha_desde,
        "fechaHasta": fecha_hasta,
        "cantidadDias": cantidad_dias,
        "filtros": {
            "estado": (
                estado_normalizado or None
            ),
            "buscar": (
                buscar_normalizado or None
            ),
        },
        "total": len(eventos),
        "resumenEstados": resumen_estados,
        "resumenDias": list(
            resumen_dias.values()
        ),
        "eventos": eventos,
    }


@router.get("/calendario/listado")
def listar_agenda_calendario(
    db: Session = Depends(get_db),
):
    rows = consultar_eventos_enriquecidos(
        db=db
    )

    return {
        "total": len(rows),
        "eventos": [
            dict(row)
            for row in rows
        ],
    }


@router.get("/fecha/{fecha_evento}")
def listar_agenda_por_fecha(
    fecha_evento: date,
    db: Session = Depends(get_db),
):
    rows = consultar_eventos_enriquecidos(
        db=db,
        condicion_sql=(
            'AND ag."FechaEvento" = '
            ':fecha_evento'
        ),
        parametros={
            "fecha_evento": fecha_evento
        },
    )

    return {
        "fecha": fecha_evento,
        "total": len(rows),
        "eventos": [
            dict(row)
            for row in rows
        ],
    }


@router.get("/hoy/listado")
def listar_agenda_hoy(
    db: Session = Depends(get_db),
):
    fecha_hoy = obtener_fecha_actual_colombia()

    rows = consultar_eventos_enriquecidos(
        db=db,
        condicion_sql=(
            'AND ag."FechaEvento" = '
            ':fecha_hoy'
        ),
        parametros={
            "fecha_hoy": fecha_hoy
        },
    )

    return {
        "fecha": fecha_hoy,
        "total": len(rows),
        "eventos": [
            dict(row)
            for row in rows
        ],
    }


@router.put("/proceso/{id_proceso}/iniciar")
def iniciar_gestion_desde_agenda(
    id_proceso: int,
    db: Session = Depends(get_db),
):
    validar_proceso_abierto(
        db=db,
        id_proceso=id_proceso,
    )

    eventos = (
        db.query(AgendaProcesoDisciplinario)
        .filter(
            AgendaProcesoDisciplinario
            .IdProcesoDisciplinario
            == id_proceso,
            AgendaProcesoDisciplinario
            .Activo
            .is_(True),
        )
        .all()
    )

    if not eventos:
        raise HTTPException(
            status_code=404,
            detail=(
                "No se encontraron eventos "
                "activos para el proceso "
                "disciplinario"
            ),
        )

    eventos_actualizados = 0
    fecha_actualizacion = obtener_ahora_colombia()

    try:
        for evento in eventos:
            estado_actual = (
                evento.EstadoAgenda or ""
            ).upper()

            if estado_actual in ("PROGRAMADO", "REPROGRAMADO"):
                evento.EstadoAgenda = "EN_CURSO"
                evento.ColorAgenda = "AMARILLO"

                evento.FechaActualizacion = (
                    fecha_actualizacion
                )

                evento.UsuarioActualizacion = (
                    "rrll_inicio"
                )

                eventos_actualizados += 1

        db.commit()

        return {
            "ok": True,
            "IdProcesoDisciplinario": id_proceso,
            "eventosActualizados": (
                eventos_actualizados
            ),
            "EstadoAgenda": (
                "EN_CURSO"
                if eventos_actualizados > 0
                else eventos[0].EstadoAgenda
            ),
            "ColorAgenda": (
                "AMARILLO"
                if eventos_actualizados > 0
                else eventos[0].ColorAgenda
            ),
            "message": (
                "La gestión del proceso "
                "disciplinario fue iniciada"
                if eventos_actualizados > 0
                else (
                    "El evento no estaba en "
                    "estado PROGRAMADO"
                )
            ),
        }

    except SQLAlchemyError as error:
        db.rollback()

        raise HTTPException(
            status_code=500,
            detail=(
                "No se pudo iniciar la gestión "
                "del proceso disciplinario"
            ),
        ) from error


@router.get(
    "/proceso/{id_proceso}",
    response_model=list[
        AgendaProcesoDisciplinarioResponse
    ],
)
def listar_agenda_por_proceso(
    id_proceso: int,
    db: Session = Depends(get_db),
):
    return (
        db.query(AgendaProcesoDisciplinario)
        .filter(
            AgendaProcesoDisciplinario
            .IdProcesoDisciplinario
            == id_proceso,
            AgendaProcesoDisciplinario
            .Activo
            .is_(True),
        )
        .order_by(
            AgendaProcesoDisciplinario
            .FechaEvento
            .asc(),
            AgendaProcesoDisciplinario
            .HoraInicio
            .asc(),
        )
        .all()
    )


@router.get(
    "/trabajador/{id_registro_personal}",
    response_model=list[
        AgendaProcesoDisciplinarioResponse
    ],
)
def listar_agenda_por_trabajador(
    id_registro_personal: int,
    db: Session = Depends(get_db),
):
    return (
        db.query(AgendaProcesoDisciplinario)
        .filter(
            AgendaProcesoDisciplinario
            .IdRegistroPersonal
            == id_registro_personal,
            AgendaProcesoDisciplinario
            .Activo
            .is_(True),
        )
        .order_by(
            AgendaProcesoDisciplinario
            .FechaEvento
            .asc(),
            AgendaProcesoDisciplinario
            .HoraInicio
            .asc(),
        )
        .all()
    )



@router.get(
    "/{id_agenda}/historial",
    response_model=list[
        HistorialAgendaProcesoDisciplinarioResponse
    ],
)
def obtener_historial_evento_agenda(
    id_agenda: int,
    db: Session = Depends(get_db),
):
    evento = (
        db.query(AgendaProcesoDisciplinario)
        .filter(
            AgendaProcesoDisciplinario
            .IdAgendaProcesoDisciplinario
            == id_agenda,
        )
        .first()
    )

    if not evento:
        raise HTTPException(
            status_code=404,
            detail="Evento de agenda no encontrado",
        )

    return (
        db.query(
            HistorialAgendaProcesoDisciplinario
        )
        .filter(
            HistorialAgendaProcesoDisciplinario
            .IdAgendaProcesoDisciplinario
            == id_agenda
        )
        .order_by(
            HistorialAgendaProcesoDisciplinario
            .FechaMovimiento
            .desc(),
            HistorialAgendaProcesoDisciplinario
            .IdHistorialAgendaProcesoDisciplinario
            .desc(),
        )
        .all()
    )


@router.put(
    "/{id_agenda}/reprogramar",
    response_model=AgendaProcesoDisciplinarioResponse,
)
def reprogramar_evento_agenda(
    id_agenda: int,
    data: ReprogramarAgendaDisciplinariaRequest,
    db: Session = Depends(get_db),
):
    evento = (
        db.query(AgendaProcesoDisciplinario)
        .filter(
            AgendaProcesoDisciplinario
            .IdAgendaProcesoDisciplinario
            == id_agenda,
            AgendaProcesoDisciplinario
            .Activo
            .is_(True),
        )
        .first()
    )

    if not evento:
        raise HTTPException(
            status_code=404,
            detail="Evento de agenda no encontrado",
        )

    validar_proceso_abierto(
        db=db,
        id_proceso=evento.IdProcesoDisciplinario,
    )

    estado_actual = (
        evento.EstadoAgenda or ""
    ).strip().upper()

    if estado_actual == "ATENDIDO":
        raise HTTPException(
            status_code=400,
            detail=(
                "No se puede reprogramar una citación "
                "que ya fue atendida."
            ),
        )

    if estado_actual == "CANCELADO":
        raise HTTPException(
            status_code=400,
            detail=(
                "No se puede reprogramar una citación "
                "cancelada."
            ),
        )

    motivo = data.Motivo.strip()

    if not motivo:
        raise HTTPException(
            status_code=400,
            detail=(
                "El motivo de la reprogramación "
                "es obligatorio."
            ),
        )

    fecha_movimiento = obtener_ahora_colombia()

    # La reprogramación vuelve a exigir cinco días hábiles,
    # contados desde el día en que Yeny realiza el cambio.
    validar_fecha_minima_citacion(
        fecha_evento=data.FechaEventoNueva,
        fecha_creacion_evento=fecha_movimiento,
    )

    hora_fin_nueva = calcular_hora_fin_citacion(
        data.HoraInicioNueva
    )

    autorizacion_viernes = (
        validar_programacion_citacion(
            db=db,
            fecha_evento=data.FechaEventoNueva,
            hora_inicio=data.HoraInicioNueva,
            hora_fin=hora_fin_nueva,
            id_registro_personal=(
                evento.IdRegistroPersonal
            ),
            id_proceso_disciplinario=(
                evento.IdProcesoDisciplinario
            ),
            id_agenda_excluir=id_agenda,
            bloquear_autorizacion=True,
        )
    )

    historial = HistorialAgendaProcesoDisciplinario(
        IdAgendaProcesoDisciplinario=(
            evento.IdAgendaProcesoDisciplinario
        ),
        IdProcesoDisciplinario=(
            evento.IdProcesoDisciplinario
        ),
        IdRegistroPersonal=(
            evento.IdRegistroPersonal
        ),
        TipoMovimiento="REPROGRAMACION",
        FechaEventoAnterior=evento.FechaEvento,
        HoraInicioAnterior=evento.HoraInicio,
        HoraFinAnterior=evento.HoraFin,
        EstadoAnterior=evento.EstadoAgenda,
        ColorAnterior=evento.ColorAgenda,
        FechaEventoNueva=data.FechaEventoNueva,
        HoraInicioNueva=data.HoraInicioNueva,
        HoraFinNueva=hora_fin_nueva,
        EstadoNuevo="REPROGRAMADO",
        ColorNuevo="GRIS",
        Motivo=motivo,
        UsuarioMovimiento=(
            data.UsuarioMovimiento
            or "rrll_reprogramacion"
        ),
        FechaMovimiento=fecha_movimiento,
    )

    try:
        db.add(historial)

        evento.FechaEvento = (
            data.FechaEventoNueva
        )
        evento.HoraInicio = (
            data.HoraInicioNueva
        )
        evento.HoraFin = hora_fin_nueva
        evento.EstadoAgenda = "REPROGRAMADO"
        evento.ColorAgenda = "GRIS"
        evento.FechaActualizacion = (
            fecha_movimiento
        )
        evento.UsuarioActualizacion = (
            data.UsuarioMovimiento
            or "rrll_reprogramacion"
        )

        if autorizacion_viernes is not None:
            marcar_autorizacion_como_utilizada(
                autorizacion=autorizacion_viernes,
                id_agenda=id_agenda,
                fecha_utilizacion=fecha_movimiento,
            )

        db.commit()
        db.refresh(evento)

        intentar_enviar_notificacion_agenda(
            db=db,
            id_agenda=(
                evento.IdAgendaProcesoDisciplinario
            ),
            tipo_notificacion=TIPO_REPROGRAMACION,
            usuario=(
                data.UsuarioMovimiento
                or "rrll_reprogramacion"
            ),
        )

        return evento

    except SQLAlchemyError as error:
        db.rollback()

        raise HTTPException(
            status_code=500,
            detail=(
                "No se pudo reprogramar "
                "el evento de agenda."
            ),
        ) from error


@router.put(
    "/{id_agenda}/cancelar",
    response_model=AgendaProcesoDisciplinarioResponse,
)
def cancelar_evento_agenda(
    id_agenda: int,
    data: CancelarAgendaDisciplinariaRequest,
    db: Session = Depends(get_db),
):
    evento = (
        db.query(AgendaProcesoDisciplinario)
        .filter(
            AgendaProcesoDisciplinario
            .IdAgendaProcesoDisciplinario
            == id_agenda,
            AgendaProcesoDisciplinario
            .Activo
            .is_(True),
        )
        .first()
    )

    if not evento:
        raise HTTPException(
            status_code=404,
            detail="Evento de agenda no encontrado",
        )

    validar_proceso_abierto(
        db=db,
        id_proceso=evento.IdProcesoDisciplinario,
    )

    estado_actual = (
        evento.EstadoAgenda or ""
    ).strip().upper()

    if estado_actual == "ATENDIDO":
        raise HTTPException(
            status_code=400,
            detail=(
                "No se puede cancelar una citación "
                "que ya fue atendida."
            ),
        )

    if estado_actual == "CANCELADO":
        raise HTTPException(
            status_code=400,
            detail=(
                "La citación ya se encuentra "
                "cancelada."
            ),
        )

    motivo = data.Motivo.strip()

    if not motivo:
        raise HTTPException(
            status_code=400,
            detail=(
                "El motivo de la cancelación "
                "es obligatorio."
            ),
        )

    fecha_movimiento = obtener_ahora_colombia()

    historial = HistorialAgendaProcesoDisciplinario(
        IdAgendaProcesoDisciplinario=(
            evento.IdAgendaProcesoDisciplinario
        ),
        IdProcesoDisciplinario=(
            evento.IdProcesoDisciplinario
        ),
        IdRegistroPersonal=(
            evento.IdRegistroPersonal
        ),
        TipoMovimiento="CANCELACION",
        FechaEventoAnterior=evento.FechaEvento,
        HoraInicioAnterior=evento.HoraInicio,
        HoraFinAnterior=evento.HoraFin,
        EstadoAnterior=evento.EstadoAgenda,
        ColorAnterior=evento.ColorAgenda,
        FechaEventoNueva=evento.FechaEvento,
        HoraInicioNueva=evento.HoraInicio,
        HoraFinNueva=evento.HoraFin,
        EstadoNuevo="CANCELADO",
        ColorNuevo="ROJO",
        Motivo=motivo,
        UsuarioMovimiento=(
            data.UsuarioMovimiento
            or "rrll_cancelacion"
        ),
        FechaMovimiento=fecha_movimiento,
    )

    try:
        db.add(historial)

        # El evento permanece activo para conservarlo visible
        # dentro de la agenda y de la trazabilidad.
        evento.Activo = True
        evento.EstadoAgenda = "CANCELADO"
        evento.ColorAgenda = "ROJO"
        evento.FechaActualizacion = (
            fecha_movimiento
        )
        evento.UsuarioActualizacion = (
            data.UsuarioMovimiento
            or "rrll_cancelacion"
        )

        db.commit()
        db.refresh(evento)

        intentar_enviar_notificacion_agenda(
            db=db,
            id_agenda=(
                evento.IdAgendaProcesoDisciplinario
            ),
            tipo_notificacion=TIPO_CANCELACION,
            usuario=(
                data.UsuarioMovimiento
                or "rrll_cancelacion"
            ),
        )

        return evento

    except SQLAlchemyError as error:
        db.rollback()

        raise HTTPException(
            status_code=500,
            detail=(
                "No se pudo cancelar "
                "el evento de agenda."
            ),
        ) from error


@router.put(
    "/{id_agenda}/enlace-virtual",
)
def registrar_enlace_virtual_rrll(
    id_agenda: int,
    data: EnlaceVirtualRRLLRequest,
    db: Session = Depends(get_db),
):
    evento = (
        db.query(AgendaProcesoDisciplinario)
        .filter(
            AgendaProcesoDisciplinario
            .IdAgendaProcesoDisciplinario
            == id_agenda,
            AgendaProcesoDisciplinario
            .Activo
            .is_(True),
        )
        .first()
    )

    if not evento:
        raise HTTPException(
            status_code=404,
            detail={
                "mensaje": (
                    "Evento de agenda no encontrado."
                ),
                "IdAgendaProcesoDisciplinario": id_agenda,
            },
        )

    validar_proceso_abierto(
        db=db,
        id_proceso=evento.IdProcesoDisciplinario,
    )

    modalidad = str(
        evento.Modalidad or ""
    ).strip().upper()

    if modalidad != "VIRTUAL":
        raise HTTPException(
            status_code=409,
            detail={
                "mensaje": (
                    "El enlace de reunión solo puede "
                    "registrarse para citaciones virtuales."
                ),
                "Modalidad": evento.Modalidad,
            },
        )

    estado_actual = str(
        evento.EstadoAgenda or ""
    ).strip().upper()

    if estado_actual in {
        "ATENDIDO",
        "CANCELADO",
    }:
        raise HTTPException(
            status_code=409,
            detail={
                "mensaje": (
                    "La citación ya no admite la asignación "
                    "del enlace de reunión."
                ),
                "EstadoAgenda": evento.EstadoAgenda,
            },
        )

    enlace = str(
        data.EnlaceVirtual or ""
    ).strip()

    if not enlace:
        raise HTTPException(
            status_code=422,
            detail={
                "mensaje": (
                    "Debe ingresar el enlace de la reunión virtual."
                ),
            },
        )

    if not (
        enlace.lower().startswith("https://")
        or enlace.lower().startswith("http://")
    ):
        raise HTTPException(
            status_code=422,
            detail={
                "mensaje": (
                    "El enlace debe comenzar por "
                    "http:// o https://."
                ),
            },
        )

    if len(enlace) > 2000:
        raise HTTPException(
            status_code=422,
            detail={
                "mensaje": (
                    "El enlace de la reunión es demasiado largo."
                ),
                "longitudMaxima": 2000,
            },
        )

    enlace_existente = str(
        getattr(
            evento,
            "LugarCitacion",
            "",
        )
        or ""
    ).strip()

    if enlace_existente:
        raise HTTPException(
            status_code=409,
            detail={
                "mensaje": (
                    "La citación virtual ya tiene un enlace "
                    "asignado por Relaciones Laborales."
                ),
                "IdAgendaProcesoDisciplinario": id_agenda,
            },
        )

    citacion = (
        db.query(CitacionProcesoDisciplinario)
        .filter(
            CitacionProcesoDisciplinario
            .IdProcesoDisciplinario
            == evento.IdProcesoDisciplinario
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
                    "No se encontró la citación asociada "
                    "al proceso disciplinario."
                ),
                "IdProcesoDisciplinario": (
                    evento.IdProcesoDisciplinario
                ),
            },
        )

    modalidad_citacion = str(
        citacion.Modalidad or ""
    ).strip().upper()

    if modalidad_citacion != "VIRTUAL":
        raise HTTPException(
            status_code=409,
            detail={
                "mensaje": (
                    "La citación asociada al proceso "
                    "no está registrada como virtual."
                ),
                "ModalidadCitacion": citacion.Modalidad,
            },
        )

    usuario = str(
        data.UsuarioMovimiento
        or "rrll_enlace_virtual"
    ).strip()

    fecha_actualizacion = (
        obtener_ahora_colombia()
    )

    try:
        evento.LugarCitacion = enlace
        evento.FechaActualizacion = (
            fecha_actualizacion
        )
        evento.UsuarioActualizacion = usuario

        citacion.LugarCitacion = enlace
        citacion.FechaActualizacion = (
            fecha_actualizacion
        )
        citacion.UsuarioActualizacion = usuario

        db.commit()
        db.refresh(evento)
        db.refresh(citacion)

    except SQLAlchemyError as error:
        db.rollback()

        raise HTTPException(
            status_code=500,
            detail={
                "mensaje": (
                    "No se pudo guardar el enlace "
                    "de la reunión virtual."
                ),
                "IdAgendaProcesoDisciplinario": id_agenda,
            },
        ) from error

    resultado_notificacion = (
        intentar_enviar_notificacion_agenda(
            db=db,
            id_agenda=id_agenda,
            tipo_notificacion=(
                TIPO_CITACION_INICIAL
            ),
            usuario=usuario,
        )
    )

    correo_enviado = bool(
        resultado_notificacion.get(
            "enviado"
        )
    )

    if correo_enviado:
        mensaje = (
            "El enlace virtual fue registrado correctamente "
            "y la citación fue enviada al trabajador."
        )
    else:
        mensaje = (
            "El enlace virtual fue registrado correctamente, "
            "pero no fue posible confirmar el envío del correo "
            "al trabajador. Revise el resultado de la notificación."
        )

    return {
        "ok": True,
        "IdAgendaProcesoDisciplinario": (
            evento.IdAgendaProcesoDisciplinario
        ),
        "IdProcesoDisciplinario": (
            evento.IdProcesoDisciplinario
        ),
        "Modalidad": evento.Modalidad,
        "LugarCitacion": evento.LugarCitacion,
        "EnlaceVirtual": evento.LugarCitacion,
        "PendienteEnlaceVirtual": False,
        "NotificacionCorreo": (
            resultado_notificacion
        ),
        "mensaje": mensaje,
    }


@router.get(
    "/{id_agenda}",
    response_model=AgendaProcesoDisciplinarioResponse,
)
def obtener_evento_agenda(
    id_agenda: int,
    db: Session = Depends(get_db),
):
    evento = (
        db.query(AgendaProcesoDisciplinario)
        .filter(
            AgendaProcesoDisciplinario
            .IdAgendaProcesoDisciplinario
            == id_agenda,
            AgendaProcesoDisciplinario
            .Activo
            .is_(True),
        )
        .first()
    )

    if not evento:
        raise HTTPException(
            status_code=404,
            detail=(
                "Evento de agenda no encontrado"
            ),
        )

    return evento


@router.put(
    "/{id_agenda}",
    response_model=AgendaProcesoDisciplinarioResponse,
)
def actualizar_evento_agenda(
    id_agenda: int,
    data: AgendaProcesoDisciplinarioUpdate,
    db: Session = Depends(get_db),
):
    evento = (
        db.query(AgendaProcesoDisciplinario)
        .filter(
            AgendaProcesoDisciplinario
            .IdAgendaProcesoDisciplinario
            == id_agenda,
            AgendaProcesoDisciplinario
            .Activo
            .is_(True),
        )
        .first()
    )

    if not evento:
        raise HTTPException(
            status_code=404,
            detail=(
                "Evento de agenda no encontrado"
            ),
        )

    validar_proceso_abierto(
        db=db,
        id_proceso=evento.IdProcesoDisciplinario,
    )

    datos = data.model_dump(
        exclude_unset=True
    )
    autorizacion_viernes = None

    tipo_evento_final = datos.get(
        "IdTipoEventoDisciplinario",
        evento.IdTipoEventoDisciplinario,
    )

    fecha_evento_final = datos.get(
        "FechaEvento",
        evento.FechaEvento,
    )

    hora_inicio_final = datos.get(
        "HoraInicio",
        evento.HoraInicio,
    )

    modifica_programacion = any(
        campo in datos
        for campo in (
            "IdTipoEventoDisciplinario",
            "FechaEvento",
            "HoraInicio",
            "HoraFin",
        )
    )

    if (
        tipo_evento_final
        == TIPO_EVENTO_CITACION_ID
        and modifica_programacion
    ):
        hora_fin_final = (
            calcular_hora_fin_citacion(
                hora_inicio_final
            )
        )

        if evento.FechaCreacion is None:
            raise HTTPException(
                status_code=400,
                detail=(
                    "El evento no tiene una fecha de creación válida. "
                    "No es posible calcular la fecha mínima de citación."
                ),
            )

        validar_fecha_minima_citacion(
            fecha_evento=fecha_evento_final,
            fecha_creacion_evento=evento.FechaCreacion,
        )

        autorizacion_viernes = (
            validar_programacion_citacion(
                db=db,
                fecha_evento=fecha_evento_final,
                hora_inicio=hora_inicio_final,
                hora_fin=hora_fin_final,
                id_registro_personal=(
                    evento.IdRegistroPersonal
                ),
                id_proceso_disciplinario=(
                    evento.IdProcesoDisciplinario
                ),
                id_agenda_excluir=id_agenda,
                bloquear_autorizacion=True,
            )
        )

        datos["HoraFin"] = (
            hora_fin_final
        )
    elif (
        tipo_evento_final
        != TIPO_EVENTO_CITACION_ID
    ):
        hora_fin_final = datos.get(
            "HoraFin",
            evento.HoraFin,
        )

        if hora_fin_final <= hora_inicio_final:
            raise HTTPException(
                status_code=400,
                detail=(
                    "La hora fin debe ser mayor "
                    "a la hora inicio"
                ),
            )

    estado_nuevo = datos.get(
        "EstadoAgenda"
    )

    if estado_nuevo:
        estado_nuevo = estado_nuevo.upper()
        datos["EstadoAgenda"] = estado_nuevo

        color_estado = (
            obtener_color_por_estado(
                estado_nuevo
            )
        )

        if color_estado:
            datos["ColorAgenda"] = (
                color_estado
            )

    try:
        for campo, valor in datos.items():
            setattr(
                evento,
                campo,
                valor,
            )

        fecha_actualizacion = (
            obtener_ahora_colombia()
        )
        evento.FechaActualizacion = (
            fecha_actualizacion
        )

        if autorizacion_viernes is not None:
            marcar_autorizacion_como_utilizada(
                autorizacion=autorizacion_viernes,
                id_agenda=id_agenda,
                fecha_utilizacion=fecha_actualizacion,
            )

        db.commit()
        db.refresh(evento)

        return evento

    except SQLAlchemyError as error:
        db.rollback()

        raise HTTPException(
            status_code=500,
            detail=(
                "No se pudo actualizar "
                "el evento de agenda"
            ),
        ) from error


@router.delete("/{id_agenda}")
def eliminar_evento_agenda(
    id_agenda: int,
    db: Session = Depends(get_db),
):
    evento = (
        db.query(AgendaProcesoDisciplinario)
        .filter(
            AgendaProcesoDisciplinario
            .IdAgendaProcesoDisciplinario
            == id_agenda,
            AgendaProcesoDisciplinario
            .Activo
            .is_(True),
        )
        .first()
    )

    if not evento:
        raise HTTPException(
            status_code=404,
            detail=(
                "Evento de agenda no encontrado"
            ),
        )

    validar_proceso_abierto(
        db=db,
        id_proceso=evento.IdProcesoDisciplinario,
    )

    try:
        evento.Activo = False
        evento.EstadoAgenda = "CANCELADO"
        evento.ColorAgenda = "ROJO"

        evento.FechaActualizacion = (
            obtener_ahora_colombia()
        )

        evento.UsuarioActualizacion = (
            "cancelacion_agenda"
        )

        db.commit()

        return {
            "ok": True,
            "message": (
                "Evento de agenda cancelado "
                "correctamente"
            ),
        }

    except SQLAlchemyError as error:
        db.rollback()

        raise HTTPException(
            status_code=500,
            detail=(
                "No se pudo cancelar el evento "
                "de agenda"
            ),
        ) from error
