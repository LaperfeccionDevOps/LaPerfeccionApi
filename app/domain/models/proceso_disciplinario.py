from sqlalchemy import Column, Integer, String, DateTime, ForeignKey
from sqlalchemy.sql import func
from infrastructure.db.base import Base


class ProcesoDisciplinario(Base):
    __tablename__ = "ProcesoDisciplinario"

    IdProcesoDisciplinario = Column(Integer, primary_key=True, index=True)
    IdRegistroPersonal = Column(
        Integer,
        ForeignKey('RegistroPersonal.IdRegistroPersonal'),
        nullable=False
    )

    EstadoProceso = Column(String(50), nullable=False, default="INICIADO")
    OrigenProceso = Column(String(50), nullable=True, default="RRLL")

    FechaCreacion = Column(DateTime(timezone=True), server_default=func.now())
    FechaActualizacion = Column(DateTime(timezone=True), nullable=True)
    UsuarioActualizacion = Column(String(100), nullable=True)