from datetime import datetime, timezone

from sqlalchemy.orm import Session

from domain.models.notificacion_proceso_disciplinario import (
    NotificacionProcesoDisciplinario,
)


def _obtener_fecha_actual() -> datetime:
    """
    Retorna la fecha y hora actual con zona horaria UTC.

    PostgreSQL almacenará correctamente el valor en las columnas
    timestamp with time zone.
    """
    return datetime.now(timezone.utc)


def crear_notificacion(
    db: Session,
    id_proceso: int,
    destinatario: str,
    tipo_notificacion: str,
    asunto: str,
    usuario: str | None = None,
    id_agenda: int | None = None,
) -> NotificacionProcesoDisciplinario:
    """
    Crea una notificación en estado PENDIENTE.
    """
    destinatario_limpio = str(
        destinatario or ""
    ).strip()

    tipo_limpio = str(
        tipo_notificacion or ""
    ).strip().upper()

    asunto_limpio = str(
        asunto or ""
    ).strip()

    usuario_limpio = str(
        usuario or ""
    ).strip() or None

    if not destinatario_limpio:
        raise ValueError(
            "El destinatario de la notificación es obligatorio."
        )

    if not tipo_limpio:
        raise ValueError(
            "El tipo de notificación es obligatorio."
        )

    if not asunto_limpio:
        raise ValueError(
            "El asunto de la notificación es obligatorio."
        )

    notificacion = NotificacionProcesoDisciplinario(
        IdProcesoDisciplinario=id_proceso,
        IdAgendaProcesoDisciplinario=id_agenda,
        Destinatario=destinatario_limpio,
        TipoNotificacion=tipo_limpio,
        Estado="PENDIENTE",
        Asunto=asunto_limpio,
        MensajeError=None,
        FechaEnvio=None,
        UsuarioCreacion=usuario_limpio,
        UsuarioActualizacion=None,
    )

    db.add(notificacion)
    db.commit()
    db.refresh(notificacion)

    return notificacion


def marcar_notificacion_enviada(
    db: Session,
    notificacion: NotificacionProcesoDisciplinario,
    usuario: str | None = None,
) -> NotificacionProcesoDisciplinario:
    """
    Marca una notificación como enviada correctamente.
    """
    fecha_actual = _obtener_fecha_actual()

    usuario_limpio = str(
        usuario or ""
    ).strip() or None

    notificacion.Estado = "ENVIADO"
    notificacion.FechaEnvio = fecha_actual
    notificacion.FechaActualizacion = fecha_actual
    notificacion.UsuarioActualizacion = usuario_limpio
    notificacion.MensajeError = None

    db.commit()
    db.refresh(notificacion)

    return notificacion


def marcar_notificacion_error(
    db: Session,
    notificacion: NotificacionProcesoDisciplinario,
    error: str,
    usuario: str | None = None,
) -> NotificacionProcesoDisciplinario:
    """
    Marca una notificación como fallida y registra el error.
    """
    fecha_actual = _obtener_fecha_actual()

    mensaje_error = str(
        error or "Error desconocido durante el envío."
    ).strip()

    usuario_limpio = str(
        usuario or ""
    ).strip() or None

    notificacion.Estado = "ERROR"
    notificacion.MensajeError = mensaje_error
    notificacion.FechaEnvio = None
    notificacion.FechaActualizacion = fecha_actual
    notificacion.UsuarioActualizacion = usuario_limpio

    db.commit()
    db.refresh(notificacion)

    return notificacion