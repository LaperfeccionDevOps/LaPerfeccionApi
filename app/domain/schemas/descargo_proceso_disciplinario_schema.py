from datetime import date, datetime, time
from typing import Optional

from pydantic import BaseModel


class DescargoProcesoDisciplinarioBase(BaseModel):
    IdProcesoDisciplinario: int
    FechaDescargo: Optional[date] = None
    HoraDescargo: Optional[time] = None
    DescargoTrabajador: Optional[str] = None
    Observaciones: Optional[str] = None
    ResponsableDescargo: Optional[str] = None


class DescargoProcesoDisciplinarioCreate(DescargoProcesoDisciplinarioBase):
    pass


class DescargoProcesoDisciplinarioUpdate(BaseModel):
    FechaDescargo: Optional[date] = None
    HoraDescargo: Optional[time] = None
    DescargoTrabajador: Optional[str] = None
    Observaciones: Optional[str] = None
    ResponsableDescargo: Optional[str] = None


class DescargoProcesoDisciplinarioResponse(DescargoProcesoDisciplinarioBase):
    IdDescargoProcesoDisciplinario: int
    FechaCreacion: Optional[datetime] = None
    FechaActualizacion: Optional[datetime] = None

    class Config:
        from_attributes = True