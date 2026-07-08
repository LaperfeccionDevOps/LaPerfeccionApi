from datetime import datetime
from typing import Optional

from pydantic import BaseModel


class ProcesoDisciplinarioBase(BaseModel):
    IdRegistroPersonal: int
    EstadoProceso: Optional[str] = "INICIADO"
    OrigenProceso: Optional[str] = "RRLL"
    UsuarioActualizacion: Optional[str] = None


class ProcesoDisciplinarioCreate(ProcesoDisciplinarioBase):
    pass


class ProcesoDisciplinarioUpdate(BaseModel):
    EstadoProceso: Optional[str] = None
    OrigenProceso: Optional[str] = None
    UsuarioActualizacion: Optional[str] = None


class ProcesoDisciplinarioResponse(ProcesoDisciplinarioBase):
    IdProcesoDisciplinario: int
    FechaCreacion: Optional[datetime] = None
    FechaActualizacion: Optional[datetime] = None

    class Config:
        from_attributes = True