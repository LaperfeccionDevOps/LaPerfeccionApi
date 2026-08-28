from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field


class SolicitudAutorizacionAgendaDisciplinariaBase(BaseModel):
    IdRegistroPersonal: int

    IdProcesoDisciplinario: int

    FechaSolicitada: date

    MotivoSolicitud: str = Field(
        ...,
        min_length=5,
        max_length=2000,
    )

    UsuarioSolicita: str = Field(
        ...,
        min_length=2,
        max_length=100,
    )


class SolicitudAutorizacionAgendaDisciplinariaCreate(
    SolicitudAutorizacionAgendaDisciplinariaBase
):
    pass


class SolicitudAutorizacionAgendaDisciplinariaResolver(
    BaseModel
):
    UsuarioResuelve: str = Field(
        ...,
        min_length=2,
        max_length=100,
    )

    ObservacionResolucion: str | None = Field(
        default=None,
        max_length=2000,
    )


class SolicitudAutorizacionAgendaDisciplinariaAprobar(
    SolicitudAutorizacionAgendaDisciplinariaResolver
):
    pass


class SolicitudAutorizacionAgendaDisciplinariaRechazar(
    BaseModel
):
    UsuarioResuelve: str = Field(
        ...,
        min_length=2,
        max_length=100,
    )

    ObservacionResolucion: str = Field(
        ...,
        min_length=5,
        max_length=2000,
    )


class SolicitudAutorizacionAgendaDisciplinariaCancelar(
    BaseModel
):
    UsuarioCancela: str = Field(
        ...,
        min_length=2,
        max_length=100,
    )

    MotivoCancelacion: str = Field(
        ...,
        min_length=5,
        max_length=2000,
    )


class SolicitudAutorizacionAgendaDisciplinariaResponse(
    SolicitudAutorizacionAgendaDisciplinariaBase
):
    model_config = ConfigDict(
        from_attributes=True
    )

    IdSolicitudAutorizacion: int

    EstadoSolicitud: str

    FechaSolicitud: datetime

    UsuarioResuelve: str | None = None

    FechaResolucion: datetime | None = None

    ObservacionResolucion: str | None = None

    IdAutorizacionAgendaDisciplinaria: int | None = None

    # Datos del trabajador para mostrar en RRLL
    NombreCompleto: str | None = None

    NumeroDocumento: str | None = None

    TipoDocumento: str | None = None

    Activo: bool

    FechaCreacion: datetime

    FechaActualizacion: datetime
