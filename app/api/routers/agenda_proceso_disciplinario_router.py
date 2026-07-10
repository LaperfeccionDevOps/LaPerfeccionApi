from datetime import date, datetime

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

from domain.schemas.agenda_proceso_disciplinario_schema import (
    AgendaProcesoDisciplinarioCreate,
    AgendaProcesoDisciplinarioResponse,
    AgendaProcesoDisciplinarioUpdate,
)
from domain.schemas.tipo_evento_disciplinario_schema import (
    TipoEventoDisciplinarioResponse,
)


router = APIRouter(
    prefix="/api/agenda-disciplinaria",
    tags=["Agenda Disciplinaria"],
)


COLORES_POR_ESTADO = {
    "PROGRAMADO": "AZUL",
    "EN_CURSO": "AMARILLO",
    "ATENDIDO": "VERDE",
    "CANCELADO": "ROJO",
    "REPROGRAMADO": "GRIS",
}


def obtener_color_por_estado(
    estado_agenda: str,
) -> str | None:
    if not estado_agenda:
        return None

    return COLORES_POR_ESTADO.get(
        estado_agenda.upper()
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


@router.post(
    "/",
    response_model=AgendaProcesoDisciplinarioResponse,
)
def crear_evento_agenda(
    data: AgendaProcesoDisciplinarioCreate,
    db: Session = Depends(get_db),
):
    if data.HoraFin <= data.HoraInicio:
        raise HTTPException(
            status_code=400,
            detail=(
                "La hora fin debe ser mayor "
                "a la hora inicio"
            ),
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

    try:
        datos_evento = data.model_dump()

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
    """
    Cambia los eventos activos del proceso:

    PROGRAMADO -> EN_CURSO
    AZUL -> AMARILLO

    No modifica eventos ya atendidos,
    cancelados o reprogramados.
    """

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

            if estado_actual == "PROGRAMADO":
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

    datos = data.model_dump(
        exclude_unset=True
    )

    hora_inicio = datos.get(
        "HoraInicio",
        evento.HoraInicio,
    )

    hora_fin = datos.get(
        "HoraFin",
        evento.HoraFin,
    )

    if hora_fin <= hora_inicio:
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