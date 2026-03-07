# app/domain/schemas/cita.py
from datetime import datetime, date, time
from typing import Optional

from pydantic import BaseModel, ConfigDict


class CitaBase(BaseModel):
    IdRegistroPersonal: int
    FechaProgramada: date          # lo que manda el front: solo fecha
    HoraProgramada: time           # lo que manda el front: solo hora
    Observaciones: Optional[str] = None


class CitaCreate(CitaBase):
    """
    Datos para crear una cita.
    """
    pass


class CitaOut(BaseModel):
    """
    Datos que devuelve la API.
    """
    IdAgendarEntrevista: int
    IdRegistroPersonal: int
    FechaProgramada: datetime
    HoraProgramada: datetime
    Observaciones: Optional[str] = None

    # 👇 AQUÍ EL CAMBIO IMPORTANTE
    FechaCreacion: Optional[datetime] = None

    FechaActualizacion: Optional[datetime] = None
    NombreUsuarioActualizacion: Optional[str] = None

    # reemplazo de orm_mode=True en Pydantic v2
    model_config = ConfigDict(from_attributes=True)