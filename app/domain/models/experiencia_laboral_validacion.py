from sqlalchemy import Column, BigInteger, Boolean, DateTime, Text, UniqueConstraint, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.sql import func
from sqlalchemy import Date

from infrastructure.db.base import Base

class ExperienciaLaboralValidacion(Base):
    __tablename__ = "ExperienciaLaboralValidacion"

    IdValidacion = Column(BigInteger, primary_key=True, index=True)
    IdExperienciaLaboral = Column(BigInteger, nullable=False, index=True)
    Concepto = Column(String, nullable=False, default="")
    DesempenoReportado = Column(String, nullable=True)
    MotivoRetiroReal = Column(String, nullable=False, default="")
    PersonaQueReferencia = Column(String, nullable=True)
    CreadoEn = Column(DateTime(timezone=False), server_default=func.now(), nullable=False)
    ActualizadoEn = Column(DateTime(timezone=False), server_default=func.now(), onupdate=func.now(), nullable=False)
    Telefono = Column(String, nullable=True)
    ReferenciadoPor = Column(String, nullable=True)
    Eps = Column(String, nullable=True)
    TiempoDuracion = Column(String, nullable=True)
    
    FechaExpedicionDocumentoIdentidad = Column(Date, nullable=True)
    ComentariosDelReferenciado = Column(Text, nullable=True)

    # Relación con ExperienciaLaboral
    from sqlalchemy.orm import relationship
    experiencia_laboral = relationship(
        "ExperienciaLaboralORM",
        primaryjoin="ExperienciaLaboralValidacion.IdExperienciaLaboral == foreign(ExperienciaLaboralORM.IdExperienciaLaboral)",
        lazy="joined"
    )


    __table_args__ = (
        UniqueConstraint("IdExperienciaLaboral", name="UQ_ExpLabVal_IdExperiencia"),
    )
