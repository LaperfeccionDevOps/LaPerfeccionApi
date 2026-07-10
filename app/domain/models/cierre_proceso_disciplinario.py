from sqlalchemy import Column, Date, ForeignKey, Integer, String, Text
from sqlalchemy.sql import func
from sqlalchemy.types import DateTime

from infrastructure.db.base import Base


class CierreProcesoDisciplinario(Base):
    __tablename__ = "CierreProcesoDisciplinario"

    IdCierreProcesoDisciplinario = Column(
        Integer,
        primary_key=True,
        index=True,
    )

    IdProcesoDisciplinario = Column(
        Integer,
        ForeignKey("ProcesoDisciplinario.IdProcesoDisciplinario"),
        nullable=False,
        index=True,
    )

    FechaCierre = Column(
        Date,
        nullable=True,
    )

    TipoCierre = Column(
        String(150),
        nullable=True,
    )

    MedidaDisciplinaria = Column(
        String(150),
        nullable=True,
    )

    ConclusionRRLL = Column(
        Text,
        nullable=True,
    )

    ResponsableCierre = Column(
        String(200),
        nullable=True,
    )

    FechaCreacion = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    FechaActualizacion = Column(
        DateTime(timezone=True),
        nullable=True,
        onupdate=func.now(),
    )