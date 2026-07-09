from datetime import date, datetime, time
from typing import Optional

from pydantic import BaseModel


class CitacionProcesoDisciplinarioBase(BaseModel):
    IdProcesoDisciplinario: int
    FechaCitacion: date
    HoraCitacion: time
    LugarCitacion: str
    MotivoCitacion: str


class CitacionProcesoDisciplinarioCreate(CitacionProcesoDisciplinarioBase):
    pass


class CitacionProcesoDisciplinarioUpdate(BaseModel):
    FechaCitacion: Optional[date] = None
    HoraCitacion: Optional[time] = None
    LugarCitacion: Optional[str] = None
    MotivoCitacion: Optional[str] = None


class CitacionProcesoDisciplinarioResponse(CitacionProcesoDisciplinarioBase):
    IdCitacionProcesoDisciplinario: int
    FechaCreacion: Optional[datetime] = None

    class Config:
        from_attributes = True