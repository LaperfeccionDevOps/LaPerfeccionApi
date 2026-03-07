from sqlalchemy import Column, Integer, String, DateTime
from sqlalchemy.sql import func

from infrastructure.db.base import Base  # ⚠️ ajusta si tu Base está en otro lado


class ObsRechazoContratacion(Base):
    __tablename__ = "ObsRechazoContratacion"

    IdObsRechazoContratacion = Column(Integer, primary_key=True, index=True)
    IdRegistroPersonal = Column(Integer, nullable=False, index=True)
    ObservacionesRechazo = Column(String, nullable=True)

    # Si tu BD ya tiene DEFAULT now() puedes dejar server_default=func.now()
    FechaRechazo = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
