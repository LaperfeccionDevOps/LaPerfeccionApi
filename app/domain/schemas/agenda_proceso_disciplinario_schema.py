from datetime import date, datetime, time
from typing import Optional

from pydantic import BaseModel


class AgendaProcesoDisciplinarioBase(
    BaseModel
):
    IdProcesoDisciplinario: int
    IdRegistroPersonal: int
    IdTipoEventoDisciplinario: int

    FechaEvento: date
    HoraInicio: time
    HoraFin: time

    Modalidad: str

    Observacion: Optional[str] = None
    EstadoAgenda: Optional[str] = (
        "PROGRAMADO"
    )
    ColorAgenda: Optional[str] = None

    UsuarioAgenda: Optional[str] = None
    UsuarioActualizacion: Optional[
        str
    ] = None

    Activo: Optional[bool] = True

    # =============================================
    # INFORMACIÓN DILIGENCIADA POR OPERACIONES
    # =============================================

    LugarCitacion: Optional[str] = None
    SupervisorReporta: Optional[str] = None
    Sede: Optional[str] = None

    MotivoCitacion: Optional[str] = None
    RelatoHechos: Optional[str] = None

    ObservacionOperaciones: Optional[
        str
    ] = None

    ManifestacionSupervisor: Optional[
        str
    ] = None


class AgendaProcesoDisciplinarioCreate(
    AgendaProcesoDisciplinarioBase
):
    pass


class AgendaProcesoDisciplinarioUpdate(
    BaseModel
):
    IdTipoEventoDisciplinario: Optional[
        int
    ] = None

    FechaEvento: Optional[date] = None
    HoraInicio: Optional[time] = None
    HoraFin: Optional[time] = None

    Modalidad: Optional[str] = None

    Observacion: Optional[str] = None
    EstadoAgenda: Optional[str] = None
    ColorAgenda: Optional[str] = None

    UsuarioAgenda: Optional[str] = None
    UsuarioActualizacion: Optional[
        str
    ] = None

    Activo: Optional[bool] = None

    # =============================================
    # INFORMACIÓN DILIGENCIADA POR OPERACIONES
    # =============================================

    LugarCitacion: Optional[str] = None
    SupervisorReporta: Optional[str] = None
    Sede: Optional[str] = None

    MotivoCitacion: Optional[str] = None
    RelatoHechos: Optional[str] = None

    ObservacionOperaciones: Optional[
        str
    ] = None

    ManifestacionSupervisor: Optional[
        str
    ] = None


class AgendaProcesoDisciplinarioResponse(
    AgendaProcesoDisciplinarioBase
):
    IdAgendaProcesoDisciplinario: int

    FechaCreacion: Optional[
        datetime
    ] = None

    FechaActualizacion: Optional[
        datetime
    ] = None

    class Config:
        from_attributes = True