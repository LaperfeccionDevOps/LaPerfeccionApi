from datetime import datetime
from typing import Optional

from pydantic import BaseModel


class TipoEventoDisciplinarioBase(BaseModel):
    Nombre: str
    Activo: Optional[bool] = True
    UsuarioActualizacion: Optional[str] = None


class TipoEventoDisciplinarioCreate(TipoEventoDisciplinarioBase):
    pass


class TipoEventoDisciplinarioUpdate(BaseModel):
    Nombre: Optional[str] = None
    Activo: Optional[bool] = None
    UsuarioActualizacion: Optional[str] = None


class TipoEventoDisciplinarioResponse(TipoEventoDisciplinarioBase):
    IdTipoEventoDisciplinario: int
    FechaCreacion: Optional[datetime] = None
    FechaActualizacion: Optional[datetime] = None

    class Config:
        from_attributes = True