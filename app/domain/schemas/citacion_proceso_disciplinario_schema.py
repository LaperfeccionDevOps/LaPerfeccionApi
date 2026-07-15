from datetime import date, datetime, time
from typing import Optional

from pydantic import BaseModel


class CitacionProcesoDisciplinarioBase(
    BaseModel
):
    IdProcesoDisciplinario: int

    FechaCitacion: Optional[date] = None
    HoraCitacion: Optional[time] = None

    LugarCitacion: Optional[str] = None
    MotivoCitacion: Optional[str] = None

    ResponsableCitacion: Optional[
        str
    ] = None

    # =============================================
    # INFORMACIÓN MAPEADA DESDE OPERACIONES
    # =============================================

    Modalidad: Optional[str] = None
    RelatoHechos: Optional[str] = None

    ObservacionOperaciones: Optional[
        str
    ] = None

    SupervisorReporta: Optional[str] = None

    ManifestacionSupervisor: Optional[
        str
    ] = None

    Cliente: Optional[str] = None
    Sede: Optional[str] = None

    UsuarioCreacion: Optional[str] = None
    UsuarioActualizacion: Optional[
        str
    ] = None


class CitacionProcesoDisciplinarioCreate(
    CitacionProcesoDisciplinarioBase
):
    pass


class CitacionProcesoDisciplinarioUpdate(
    BaseModel
):
    FechaCitacion: Optional[date] = None
    HoraCitacion: Optional[time] = None

    LugarCitacion: Optional[str] = None
    MotivoCitacion: Optional[str] = None

    ResponsableCitacion: Optional[
        str
    ] = None

    Modalidad: Optional[str] = None
    RelatoHechos: Optional[str] = None

    ObservacionOperaciones: Optional[
        str
    ] = None

    SupervisorReporta: Optional[str] = None

    ManifestacionSupervisor: Optional[
        str
    ] = None

    Cliente: Optional[str] = None
    Sede: Optional[str] = None

    UsuarioActualizacion: Optional[
        str
    ] = None


class CitacionProcesoDisciplinarioResponse(
    CitacionProcesoDisciplinarioBase
):
    IdCitacionProcesoDisciplinario: int

    FechaCreacion: Optional[
        datetime
    ] = None

    FechaActualizacion: Optional[
        datetime
    ] = None

    class Config:
        from_attributes = True