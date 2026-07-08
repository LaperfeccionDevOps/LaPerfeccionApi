from datetime import datetime
from typing import Optional

from pydantic import BaseModel


class DocumentoProcesoDisciplinarioBase(BaseModel):
    IdProcesoDisciplinario: int
    TipoDocumento: Optional[str] = None
    NombreArchivo: Optional[str] = None
    RutaArchivo: Optional[str] = None
    Observacion: Optional[str] = None


class DocumentoProcesoDisciplinarioCreate(DocumentoProcesoDisciplinarioBase):
    pass


class DocumentoProcesoDisciplinarioUpdate(BaseModel):
    TipoDocumento: Optional[str] = None
    NombreArchivo: Optional[str] = None
    RutaArchivo: Optional[str] = None
    Observacion: Optional[str] = None


class DocumentoProcesoDisciplinarioResponse(DocumentoProcesoDisciplinarioBase):
    IdDocumentoProcesoDisciplinario: int
    FechaCreacion: Optional[datetime] = None
    FechaActualizacion: Optional[datetime] = None

    class Config:
        from_attributes = True