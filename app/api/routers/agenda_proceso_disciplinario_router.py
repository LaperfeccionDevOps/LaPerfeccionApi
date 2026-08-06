# ruff: noqa: B008, BLE001

from datetime import date, datetime, time, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException
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
from domain.models.historial_agenda_proceso_disciplinario import (
    HistorialAgendaProcesoDisciplinario,
)
from domain.models.proceso_disciplinario import (
    ProcesoDisciplinario,
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
    TIPO_REPROGRAMACION,
    enviar_notificacion_agenda_disciplinaria,
)


router = APIRouter(
    prefix="/api/agenda-disciplinaria",
    tags=["Agenda Disciplinaria"],
)


TIPO_EVENTO_CITACION_ID = 1
DIAS_HABILES_MINIMOS_CITACION = 5

HORA_INICIO_MANANA = time(7, 10)
HORA_FIN_MANANA = time(13, 0)
HORA_INICIO_TARDE = time(14, 0)
HORA_FIN_JORNADA = time(16, 0)

DURACION_CITACION_MINUTOS = 40
CAPACIDAD_MAXIMA_DIARIA = 11


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


def buscar_autorizacion_viernes_activa(
    db: Session,
    id_registro_personal: int,
    id_proceso_disciplinario: int,
    fecha_evento: date,
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
            == fecha_evento,
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


def obtener_autorizacion_viernes_o_error(
    db: Session,
    id_registro_personal: int,
    id_proceso_disciplinario: int,
    fecha_evento: date,
    hora_inicio: time,
    hora_fin: time,
    bloquear_registro: bool = False,
) -> AutorizacionAgendaDisciplinaria | None:
    if fecha_evento.weekday() != 4:
        return None

    autorizacion = buscar_autorizacion_viernes_activa(
        db=db,
        id_registro_personal=id_registro_personal,
        id_proceso_disciplinario=(
            id_proceso_disciplinario
        ),
        fecha_evento=fecha_evento,
        hora_inicio=hora_inicio,
        hora_fin=hora_fin,
        bloquear_registro=bloquear_registro,
    )

    if autorizacion:
        return autorizacion

    raise HTTPException(
        status_code=409,
        detail={
            "codigo": "VIERNES_REQUIERE_AUTORIZACION",
            "mensaje": (
                "No existe una autorización activa de "
                "Relaciones Laborales para este expediente, "
                "viernes y horario."
            ),
            "IdRegistroPersonal": id_registro_personal,
            "IdProcesoDisciplinario": (
                id_proceso_disciplinario
            ),
            "fechaIngresada": (
                fecha_evento.strftime("%d/%m/%Y")
            ),
            "horaInicio": (
                hora_inicio.strftime("%H:%M")
            ),
            "horaFin": (
                hora_fin.strftime("%H:%M")
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


def validar_programacion_citacion(
    db: Session,
    fecha_evento: date,
    hora_inicio: time,
    hora_fin: time,
    id_registro_personal: int,
    id_proceso_disciplinario: int,
    id_agenda_excluir: int | None = None,
    bloquear_autorizacion: bool = False,
) -> AutorizacionAgendaDisciplinaria | None:
    autorizacion_viernes = (
        obtener_autorizacion_viernes_o_error(
            db=db,
            id_registro_personal=(
                id_registro_personal
            ),
            id_proceso_disciplinario=(
                id_proceso_disciplinario
            ),
            fecha_evento=fecha_evento,
            hora_inicio=hora_inicio,
            hora_fin=hora_fin,
            bloquear_registro=(
                bloquear_autorizacion
            ),
        )
    )

    validar_dia_habil_agenda(
        fecha_evento,
        permitir_viernes=(
            autorizacion_viernes is not None
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

    return autorizacion_viernes


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
            ag."Observacion",
            ag."EstadoAgenda",
            ag."ColorAgenda",
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

    horarios_disponibles = []

    for hora_inicio, hora_fin in BLOQUES_CITACION:
        evento_cruzado = buscar_cruce_horario(
            db=db,
            fecha_evento=fecha_evento,
            hora_inicio=hora_inicio,
            hora_fin=hora_fin,
        )

        autorizacion_viernes = None

        if es_viernes:
            autorizacion_viernes = (
                buscar_autorizacion_viernes_activa(
                    db=db,
                    id_registro_personal=(
                        id_registro_personal
                    ),
                    id_proceso_disciplinario=(
                        id_proceso_disciplinario
                    ),
                    fecha_evento=fecha_evento,
                    hora_inicio=hora_inicio,
                    hora_fin=hora_fin,
                )
            )

        if (
            evento_cruzado is None
            and (
                not es_viernes
                or autorizacion_viernes is not None
            )
        ):
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
        "requiereAutorizacionRRLL": es_viernes,
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
    autorizacion_viernes = None

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

        autorizacion_viernes = (
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

        if autorizacion_viernes is not None:
            marcar_autorizacion_como_utilizada(
                autorizacion=autorizacion_viernes,
                id_agenda=(
                    nuevo_evento
                    .IdAgendaProcesoDisciplinario
                ),
                fecha_utilizacion=(
                    fecha_creacion_evento
                ),
            )

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