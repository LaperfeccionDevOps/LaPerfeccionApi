from datetime import datetime

from pydantic import BaseModel, ConfigDict


class NotificacionProcesoDisciplinarioBase(BaseModel):
    IdProcesoDisciplinario: int
    IdAgendaProcesoDisciplinario: int | None = None
    Destinatario: str
    TipoNotificacion: str
    Estado: str = "PENDIENTE"
    Asunto: str | None = None
    MensajeError: str | None = None
    FechaEnvio: datetime | None = None
    UsuarioCreacion: str | None = None
    UsuarioActualizacion: str | None = None


class NotificacionProcesoDisciplinarioCreate(
    NotificacionProcesoDisciplinarioBase
):
    pass


class NotificacionProcesoDisciplinarioUpdate(BaseModel):
    Estado: str | None = None
    MensajeError: str | None = None
    FechaEnvio: datetime | None = None
    UsuarioActualizacion: str | None = None


class NotificacionProcesoDisciplinarioResponse(
    NotificacionProcesoDisciplinarioBase
):
    model_config = ConfigDict(
        from_attributes=True
    )

    IdNotificacionProcesoDisciplinario: int
    FechaCreacion: datetime | None = None
    FechaActualizacion: datetime | None = None