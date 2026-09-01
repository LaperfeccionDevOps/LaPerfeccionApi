from datetime import date, datetime, time

from pydantic import BaseModel


class CitacionProcesoDisciplinarioBase(
    BaseModel
):
    IdProcesoDisciplinario: int

    FechaCitacion: date | None = None
    HoraCitacion: time | None = None

    LugarCitacion: str | None = None
    MotivoCitacion: str | None = None

    ResponsableCitacion: str | None = None

    # =============================================
    # INFORMACIÓN MAPEADA DESDE OPERACIONES
    # =============================================

    TipoGestionDisciplinaria: str | None = None

    Modalidad: str | None = None
    RelatoHechos: str | None = None

    ObservacionOperaciones: str | None = None

    FechaUltimoDiaLaborado: date | None = None
    FechaInicioAusencia: date | None = None
    FechaFinAusencia: date | None = None

    DesempenoContinua: str | None = None

    JustificacionDesempeno: str | None = None

    SupervisorReporta: str | None = None

    CorreoSupervisorReporta: str | None = None

    CargoSupervisorReporta: str | None = None

    SedeSupervisorReporta: str | None = None

    EnunciacionPruebas: str | None = None

    TelefonoTrabajador: str | None = None

    ManifestacionSupervisor: str | None = None

    Cliente: str | None = None
    Sede: str | None = None

    UsuarioCreacion: str | None = None
    UsuarioActualizacion: str | None = None

    # =============================================
    # INFORMACIÓN DE LA CITACIÓN EXTRAORDINARIA
    # =============================================

    EsExtraordinaria: bool = False
    MotivoExtraordinario: str | None = None
    JustificacionExtraordinaria: str | None = None


class CitacionProcesoDisciplinarioCreate(
    CitacionProcesoDisciplinarioBase
):
    pass


class CitacionProcesoDisciplinarioUpdate(
    BaseModel
):
    FechaCitacion: date | None = None
    HoraCitacion: time | None = None

    LugarCitacion: str | None = None
    MotivoCitacion: str | None = None

    ResponsableCitacion: str | None = None

    TipoGestionDisciplinaria: str | None = None

    Modalidad: str | None = None
    RelatoHechos: str | None = None

    ObservacionOperaciones: str | None = None

    FechaUltimoDiaLaborado: date | None = None
    FechaInicioAusencia: date | None = None
    FechaFinAusencia: date | None = None

    DesempenoContinua: str | None = None

    JustificacionDesempeno: str | None = None

    SupervisorReporta: str | None = None

    CorreoSupervisorReporta: str | None = None

    CargoSupervisorReporta: str | None = None

    SedeSupervisorReporta: str | None = None

    EnunciacionPruebas: str | None = None

    TelefonoTrabajador: str | None = None

    ManifestacionSupervisor: str | None = None

    Cliente: str | None = None
    Sede: str | None = None

    UsuarioActualizacion: str | None = None

    EsExtraordinaria: bool | None = None
    MotivoExtraordinario: str | None = None
    JustificacionExtraordinaria: str | None = None


class CitacionProcesoDisciplinarioResponse(
    CitacionProcesoDisciplinarioBase
):
    IdCitacionProcesoDisciplinario: int

    FechaCreacion: datetime | None = None
    FechaActualizacion: datetime | None = None

    class Config:
        from_attributes = True