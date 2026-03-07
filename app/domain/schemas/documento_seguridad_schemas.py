from pydantic import BaseModel
from uuid import UUID
from datetime import datetime
from typing import Optional

class DocumentoSeguridadOut(BaseModel):
    id: UUID
    aspirante_id: UUID
    tipo_documento: str
    nombre_original: Optional[str] = None
    nombre_archivo: str
    mime_type: Optional[str] = None
    tamano_bytes: Optional[int] = None
    creado_en: datetime

    class Config:
        from_attributes = True
