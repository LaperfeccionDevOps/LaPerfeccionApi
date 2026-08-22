from sqlalchemy import Column, Integer, String, Boolean, DateTime
from sqlalchemy.sql import func
from infrastructure.db.base import Base


class TipoEventoDisciplinario(Base):
    __tablename__ = "TipoEventoDisciplinario"

    IdTipoEventoDisciplinario = Column(Integer, primary_key=True, index=True)
    Nombre = Column(String(100), nullable=False, unique=True)
    Activo = Column(Boolean, nullable=False, default=True)

    FechaCreacion = Column(DateTime(timezone=True), server_default=func.now())
    FechaActualizacion = Column(DateTime(timezone=True), nullable=True)
    UsuarioActualizacion = Column(String(100), nullable=True)