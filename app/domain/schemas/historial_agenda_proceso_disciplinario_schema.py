from datetime import date, datetime, time
from typing import Optional

from pydantic import BaseModel, Field


class ReprogramarAgendaDisciplinariaRequest(BaseModel):
    FechaEventoNueva: date

    HoraInicioNueva: time

    Motivo: str = Field(
        ...,
        min_length=3,
        max_length=1000,
    )

    UsuarioMovimiento: Optional[str] = None


class CancelarAgendaDisciplinariaRequest(BaseModel):
    Motivo: str = Field(
        ...,
        min_length=3,
        max_length=1000,
    )

    UsuarioMovimiento: Optional[str] = None


class HistorialAgendaProcesoDisciplinarioResponse(BaseModel):
    IdHistorialAgendaProcesoDisciplinario: int

    IdAgendaProcesoDisciplinario: int
    IdProcesoDisciplinario: int
    IdRegistroPersonal: int

    TipoMovimiento: str

    FechaEventoAnterior: Optional[date] = None
    HoraInicioAnterior: Optional[time] = None
    HoraFinAnterior: Optional[time] = None

    EstadoAnterior: Optional[str] = None
    ColorAnterior: Optional[str] = None

    FechaEventoNueva: Optional[date] = None
    HoraInicioNueva: Optional[time] = None
    HoraFinNueva: Optional[time] = None

    EstadoNuevo: Optional[str] = None
    ColorNuevo: Optional[str] = None

    Motivo: str
    UsuarioMovimiento: Optional[str] = None
    FechaMovimiento: Optional[datetime] = None

    class Config:
        from_attributes = True