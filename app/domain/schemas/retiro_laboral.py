from typing import Optional
from datetime import date, datetime
from pydantic import BaseModel


class RetiroLaboralCreate(BaseModel):
    IdRegistroPersonal: int
    IdCliente: Optional[int] = None
    IdMotivoRetiro: int
    IdEstadoProceso: int
    FechaProceso: date
    FechaRetiro: Optional[date] = None
    FechaCierre: Optional[datetime] = None
    FechaEnvioNomina: Optional[datetime] = None
    ObservacionGeneral: Optional[str] = None
    UsuarioActualizacion: Optional[str] = None

class RetiroLaboralEstadoUpdate(BaseModel):
    EstadoCasoRRLL: str
    IdEstadoProceso: int
    FechaCierre: Optional[datetime] = None
    FechaEnvioNomina: Optional[datetime] = None
    UsuarioActualizacion: Optional[str] = None

class RetiroLaboralDetalleUpdate(BaseModel):
    IdTipificacionRetiro: Optional[int] = None
    ObservacionRetiro: Optional[str] = None
    DevolucionCarnet: Optional[bool] = None
    UsuarioActualizacion: Optional[str] = None
