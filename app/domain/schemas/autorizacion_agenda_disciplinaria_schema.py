from datetime import date, datetime, time

from pydantic import BaseModel, ConfigDict, Field


class AutorizacionAgendaDisciplinariaBase(BaseModel):
    IdRegistroPersonal: int
    IdProcesoDisciplinario: int

    IdAgendaProcesoDisciplinario: int | None = None

    FechaAutorizada: date
    HoraInicio: time
    HoraFin: time

    TipoAutorizacion: str = "VIERNES"

    MotivoAutorizacion: str = Field(
        ...,
        min_length=5,
        max_length=2000,
    )

    UsuarioSolicita: str | None = Field(
        default=None,
        max_length=100,
    )

    UsuarioAutoriza: str = Field(
        ...,
        min_length=2,
        max_length=100,
    )

    Observacion: str | None = Field(
        default=None,
        max_length=2000,
    )


class AutorizacionAgendaDisciplinariaCreate(
    AutorizacionAgendaDisciplinariaBase
):
    pass


class AutorizacionAgendaDisciplinariaAnular(BaseModel):
    MotivoAnulacion: str = Field(
        ...,
        min_length=5,
        max_length=2000,
    )

    UsuarioAnula: str = Field(
        ...,
        min_length=2,
        max_length=100,
    )


class AutorizacionAgendaDisciplinariaResponse(
    AutorizacionAgendaDisciplinariaBase
):
    model_config = ConfigDict(
        from_attributes=True
    )

    IdAutorizacionAgendaDisciplinaria: int

    EstadoAutorizacion: str

    FechaAutorizacion: datetime
    FechaUtilizacion: datetime | None = None

    Activo: bool

    FechaCreacion: datetime
    FechaActualizacion: datetime