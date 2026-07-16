from sqlalchemy import (
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
)
from sqlalchemy.sql import func

from infrastructure.db.base import Base


class ProcesoDisciplinario(Base):
    __tablename__ = "ProcesoDisciplinario"

    IdProcesoDisciplinario = Column(
        Integer,
        primary_key=True,
        index=True,
    )

    IdRegistroPersonal = Column(
        Integer,
        ForeignKey(
            "RegistroPersonal.IdRegistroPersonal"
        ),
        nullable=False,
        index=True,
    )

    EstadoProceso = Column(
        String(50),
        nullable=False,
        default="INICIADO",
    )

    OrigenProceso = Column(
        String(50),
        nullable=True,
        default="RRLL",
    )

    FechaCreacion = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    FechaActualizacion = Column(
        DateTime(timezone=True),
        nullable=True,
    )

    UsuarioActualizacion = Column(
        String(100),
        nullable=True,
    )