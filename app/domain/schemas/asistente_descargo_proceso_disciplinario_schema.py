from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel


class AsistenteDescargoProcesoDisciplinarioBase(BaseModel):
    IdProcesoDisciplinario: int
    IdDescargoProcesoDisciplinario: Optional[int] = None
    TipoAsistente: str
    NombreAsistente: Optional[str] = None
    Asistio: Optional[bool] = True
    Activo: Optional[bool] = True
    UsuarioCreacion: Optional[str] = None
    UsuarioActualizacion: Optional[str] = None


class AsistenteDescargoProcesoDisciplinarioCreate(
    AsistenteDescargoProcesoDisciplinarioBase
):
    pass


class AsistenteDescargoProcesoDisciplinarioUpdate(BaseModel):
    IdDescargoProcesoDisciplinario: Optional[int] = None
    TipoAsistente: Optional[str] = None
    NombreAsistente: Optional[str] = None
    Asistio: Optional[bool] = None
    Activo: Optional[bool] = None
    UsuarioActualizacion: Optional[str] = None


class AsistenteDescargoProcesoDisciplinarioResponse(
    AsistenteDescargoProcesoDisciplinarioBase
):
    IdAsistenteDescargoProcesoDisciplinario: int
    FechaCreacion: Optional[datetime] = None
    FechaActualizacion: Optional[datetime] = None

    class Config:
        from_attributes = True


class AsistenteItem(BaseModel):
    TipoAsistente: str
    NombreAsistente: Optional[str] = None
    Asistio: bool = True


class GuardarAsistentesDescargoRequest(BaseModel):
    IdProcesoDisciplinario: int
    IdDescargoProcesoDisciplinario: Optional[int] = None
    UsuarioActualizacion: Optional[str] = None
    Asistentes: List[AsistenteItem]


class GuardarAsistentesDescargoResponse(BaseModel):
    ok: bool
    mensaje: str