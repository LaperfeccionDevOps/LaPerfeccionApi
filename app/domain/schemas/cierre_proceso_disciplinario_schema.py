from datetime import date, datetime
from typing import Optional

from pydantic import BaseModel


class CierreProcesoDisciplinarioBase(BaseModel):
    IdProcesoDisciplinario: int
    FechaCierre: Optional[date] = None
    TipoCierre: Optional[str] = None
    MedidaDisciplinaria: Optional[str] = None
    ConclusionRRLL: Optional[str] = None
    ResponsableCierre: Optional[str] = None


class CierreProcesoDisciplinarioCreate(CierreProcesoDisciplinarioBase):
    pass


class CierreProcesoDisciplinarioUpdate(BaseModel):
    FechaCierre: Optional[date] = None
    TipoCierre: Optional[str] = None
    MedidaDisciplinaria: Optional[str] = None
    ConclusionRRLL: Optional[str] = None
    ResponsableCierre: Optional[str] = None


class CierreProcesoDisciplinarioResponse(CierreProcesoDisciplinarioBase):
    IdCierreProcesoDisciplinario: int
    FechaCreacion: Optional[datetime] = None
    FechaActualizacion: Optional[datetime] = None

    class Config:
        from_attributes = True