from sqlalchemy import Column, BigInteger, Integer, Boolean, DateTime, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.sql import func

from infrastructure.db.base import Base  # ajusta si tu Base está en otra ruta

class ReferenciaPersonalValidacion(Base):
    __tablename__ = "ValidacionReferenciaPersonal"

    IdValidacionReferenciaPersonal = Column(Integer, primary_key=True, index=True)
    IdReferencia = Column(Integer, nullable=False)
    HaceCuantoLoConoce = Column("HaceCuantoLoConoce", __import__('sqlalchemy').Text, nullable=True)
    Descripcion = Column("Descripcion", __import__('sqlalchemy').Text, nullable=True)
    LugarVivienda = Column("LugarVivienda", __import__('sqlalchemy').Text, nullable=True)
    TieneHijos = Column(Boolean, nullable=True)
    Observaciones = Column("Observaciones", __import__('sqlalchemy').Text, nullable=True)
    FechaValidacion = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    FechaActualizacion = Column(DateTime(timezone=True), nullable=True)
    IdRegistroPersonal = Column(BigInteger, nullable=False)

    # Relación con ExperienciaLaboralValidacion
    from sqlalchemy.orm import relationship
    from sqlalchemy import ForeignKey
    ExperienciasLaboralesValidacion = relationship(
        "ExperienciaLaboralValidacion",
        primaryjoin="ReferenciaPersonalValidacion.IdRegistroPersonal == foreign(ExperienciaLaboralValidacion.IdExperienciaLaboral)",
        viewonly=True
    )
