from datetime import date, datetime, time, timedelta

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from infrastructure.db.deps import get_db

from domain.models.agenda_proceso_disciplinario import (
    AgendaProcesoDisciplinario,
)
from domain.models.tipo_evento_disciplinario import (
    TipoEventoDisciplinario,
)
from domain.models.historial_agenda_proceso_disciplinario import (
    HistorialAgendaProcesoDisciplinario,
)
from domain.models.proceso_disciplinario import (
    ProcesoDisciplinario,
)

from domain.schemas.agenda_proceso_disciplinario_schema import (
    AgendaProcesoDisciplinarioCreate,
    AgendaProcesoDisciplinarioResponse,
    AgendaProcesoDisciplinarioUpdate,
)
from domain.schemas.tipo_evento_disciplinario_schema import (
    TipoEventoDisciplinarioResponse,
)
from domain.schemas.historial_agenda_proceso_disciplinario_schema import (
    ReprogramarAgendaDisciplinariaRequest,
    CancelarAgendaDisciplinariaRequest,
    HistorialAgendaProcesoDisciplinarioResponse,
)


router = APIRouter(
    prefix="/api/agenda-disciplinaria",
    tags=["Agenda Disciplinaria"],
)


TIPO_EVENTO_CITACION_ID = 1
DIAS_HABILES_MINIMOS_CITACION = 5

HORA_INICIO_MANANA = time(8, 0)
HORA_FIN_MANANA = time(13, 0)
HORA_INICIO_TARDE = time(14, 0)
HORA_FIN_JORNADA = time(17, 30)

DURACION_CITACION_MINUTOS = 40
CAPACIDAD_MAXIMA_DIARIA = 12


COLORES_POR_ESTADO = {
    "PROGRAMADO": "AZUL",
    "EN_CURSO": "AMARILLO",
    "ATENDIDO": "VERDE",
    "CANCELADO": "ROJO",
    "REPROGRAMADO": "GRIS",
}


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

        if fecha_resultado.weekday() < 5:
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
) -> None:
    if fecha_evento.weekday() >= 5:
        raise HTTPException(
            status_code=400,
            detail=(
                "Las citaciones solo pueden programarse "
                "de lunes a viernes."
            ),
        )


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
                    "17:30"
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
    id_agenda_excluir: int | None = None,
) -> None:
    validar_dia_habil_agenda(
        fecha_evento
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


@router.get("/horarios-disponibles/{fecha_evento}")
def obtener_horarios_disponibles(
    fecha_evento: date,
    db: Session = Depends(get_db),
):
    if fecha_evento.weekday() >= 5:
        return {
            "fecha": fecha_evento,
            "capacidadMaxima": (
                CAPACIDAD_MAXIMA_DIARIA
            ),
            "cuposDisponibles": 0,
            "horarios": [],
            "mensaje": (
                "No existen horarios disponibles "
                "los sábados ni domingos."
            ),
        }

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

    fecha_creacion_evento = datetime.now()
    datos_evento = data.model_dump()

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

        validar_programacion_citacion(
            db=db,
            fecha_evento=data.FechaEvento,
            hora_inicio=data.HoraInicio,
            hora_fin=hora_fin_calculada,
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
    fecha_hoy = date.today()

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
    fecha_actualizacion = datetime.now()

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

    fecha_movimiento = datetime.now()

    # La reprogramación vuelve a exigir cinco días hábiles,
    # contados desde el día en que Yeny realiza el cambio.
    validar_fecha_minima_citacion(
        fecha_evento=data.FechaEventoNueva,
        fecha_creacion_evento=fecha_movimiento,
    )

    hora_fin_nueva = calcular_hora_fin_citacion(
        data.HoraInicioNueva
    )

    validar_programacion_citacion(
        db=db,
        fecha_evento=data.FechaEventoNueva,
        hora_inicio=data.HoraInicioNueva,
        hora_fin=hora_fin_nueva,
        id_agenda_excluir=id_agenda,
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

        db.commit()
        db.refresh(evento)

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

    fecha_movimiento = datetime.now()

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

        validar_programacion_citacion(
            db=db,
            fecha_evento=fecha_evento_final,
            hora_inicio=hora_inicio_final,
            hora_fin=hora_fin_final,
            id_agenda_excluir=id_agenda,
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

        evento.FechaActualizacion = (
            datetime.now()
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
            datetime.now()
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