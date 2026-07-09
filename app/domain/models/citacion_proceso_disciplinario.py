from sqlalchemy import Column, Integer, String, Date, Time, Text, ForeignKey
from sqlalchemy.sql import func
from sqlalchemy.types import DateTime
from infrastructure.db.base import Base


class CitacionProcesoDisciplinario(Base):
    __tablename__ = "CitacionProcesoDisciplinario"

    IdCitacionProcesoDisciplinario = Column(
        Integer,
        primary_key=True,
        index=True
    )

    IdProcesoDisciplinario = Column(
        Integer,
        ForeignKey("ProcesoDisciplinario.IdProcesoDisciplinario"),
        nullable=False
    )

    FechaCitacion = Column(Date, nullable=False)

    HoraCitacion = Column(Time, nullable=False)

    LugarCitacion = Column(String(300), nullable=False)

    MotivoCitacion = Column(Text, nullable=False)

    FechaCreacion = Column(
        DateTime(timezone=True),
        server_default=func.now()
    )