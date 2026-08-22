from sqlalchemy import (
    Boolean,
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


class DescargoProcesoDisciplinario(Base):
    __tablename__ = "DescargoProcesoDisciplinario"

    IdDescargoProcesoDisciplinario = Column(
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

    FechaDescargo = Column(
        Date,
        nullable=True,
    )

    HoraDescargo = Column(
        Time,
        nullable=True,
    )

    DescargoTrabajador = Column(
        Text,
        nullable=True,
    )

    # Se conserva por compatibilidad con los registros antiguos
    # que guardaban información combinada.
    Observaciones = Column(
        Text,
        nullable=True,
    )

    ResponsableDescargo = Column(
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

    ObservacionesRRLL = Column(
        Text,
        nullable=True,
    )

    EstadoBorrador = Column(
        Boolean,
        nullable=False,
        default=True,
        server_default="true",
    )

    UsuarioCreacion = Column(
        String(100),
        nullable=True,
    )

    UsuarioActualizacion = Column(
        String(100),
        nullable=True,
    )