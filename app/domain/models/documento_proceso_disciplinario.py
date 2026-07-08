from sqlalchemy import Column, Integer, String, Text, ForeignKey
from sqlalchemy.sql import func
from sqlalchemy.types import DateTime

from infrastructure.db.base import Base


class DocumentoProcesoDisciplinario(Base):
    __tablename__ = "DocumentoProcesoDisciplinario"

    IdDocumentoProcesoDisciplinario = Column(Integer, primary_key=True, index=True)

    IdProcesoDisciplinario = Column(
        Integer,
        ForeignKey("ProcesoDisciplinario.IdProcesoDisciplinario"),
        nullable=False,
    )

    TipoDocumento = Column(String(150), nullable=True)
    NombreArchivo = Column(String(300), nullable=True)
    RutaArchivo = Column(Text, nullable=True)
    Observacion = Column(Text, nullable=True)

    FechaCreacion = Column(DateTime(timezone=True), server_default=func.now())
    FechaActualizacion = Column(DateTime(timezone=True), nullable=True)