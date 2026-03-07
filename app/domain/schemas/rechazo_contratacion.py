from datetime import datetime
from typing import Optional
from pydantic import BaseModel


class RechazoContratacionUpsertIn(BaseModel):
    IdRegistroPersonal: int
    ObservacionesRechazo: Optional[str] = None


class RechazoContratacionOut(BaseModel):
    IdObsRechazoContratacion: int
    IdRegistroPersonal: int
    ObservacionesRechazo: Optional[str] = None
    FechaRechazo: Optional[datetime] = None

    class Config:
        from_attributes = True
