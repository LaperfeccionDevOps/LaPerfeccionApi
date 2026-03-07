from pydantic import BaseModel, Field
from typing import Optional, Dict, Any
from datetime import datetime


class ReferenciaPersonalValidacionBase(BaseModel):
    IdReferencia: int
    HaceCuantoLoConoce: Optional[str] = None
    Descripcion: Optional[str] = None
    LugarVivienda: Optional[str] = None
    TieneHijos: Optional[bool] = None
    Observaciones: Optional[str] = None
    FechaValidacion: Optional[datetime] = None
    FechaActualizacion: Optional[datetime] = None
    IdRegistroPersonal: int


class ReferenciaPersonalValidacionUpdate(ReferenciaPersonalValidacionBase):
    pass

class ReferenciaPersonalValidacionOut(ReferenciaPersonalValidacionBase):
    IdValidacionReferenciaPersonal: int
    FechaValidacion: Optional[datetime] = None
    FechaActualizacion: Optional[datetime] = None

    class Config:
        from_attributes = True
        json_encoders = {
            __import__('datetime').datetime: lambda v: v.isoformat() if v else None
        }
