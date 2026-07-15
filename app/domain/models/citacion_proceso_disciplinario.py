from sqlalchemy import (
    Column,
    Date,
    ForeignKey,
    Integer,
    String,
    Text,
    Time,
)
from sqlalchemy.sql import func
from sqlalchemy.types import DateTime

from infrastructure.db.base import Base


class CitacionProcesoDisciplinario(Base):
    __tablename__ = "CitacionProcesoDisciplinario"

    IdCitacionProcesoDisciplinario = Column(
        Integer,
        primary_key=True,
        index=True,
    )

    IdProcesoDisciplinario = Column(
        Integer,
        ForeignKey(
            "ProcesoDisciplinario.IdProcesoDisciplinario"
        ),
        nullable=False,
    )

    FechaCitacion = Column(
        Date,
        nullable=True,
    )

    HoraCitacion = Column(
        Time,
        nullable=True,
    )

    LugarCitacion = Column(
        String(300),
        nullable=True,
    )

    MotivoCitacion = Column(
        Text,
        nullable=True,
    )

    ResponsableCitacion = Column(
        String(200),
        nullable=True,
    )

    FechaCreacion = Column(
        DateTime(timezone=True),
        server_default=func.now(),
    )

    FechaActualizacion = Column(
        DateTime(timezone=True),
        nullable=True,
    )

    # =========================================================
    # INFORMACIÓN MAPEADA DESDE OPERACIONES
    # =========================================================

    Modalidad = Column(
        String(20),
        nullable=True,
    )

    RelatoHechos = Column(
        Text,
        nullable=True,
    )

    ObservacionOperaciones = Column(
        Text,
        nullable=True,
    )

    SupervisorReporta = Column(
        String(200),
        nullable=True,
    )

    ManifestacionSupervisor = Column(
        Text,
        nullable=True,
    )

    Cliente = Column(
        String(300),
        nullable=True,
    )

    Sede = Column(
        String(250),
        nullable=True,
    )

    UsuarioCreacion = Column(
        String(100),
        nullable=True,
    )

    UsuarioActualizacion = Column(
        String(100),
        nullable=True,
    )