from sqlalchemy import (
    BigInteger,
    Boolean,
    Column,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.sql import func

from infrastructure.db.base import Base


class SolicitudAutorizacionAgendaDisciplinaria(Base):
    __tablename__ = "SolicitudAutorizacionAgendaDisciplinaria"

    IdSolicitudAutorizacion = Column(
        Integer,
        primary_key=True,
        index=True,
    )

    IdRegistroPersonal = Column(
        BigInteger,
        ForeignKey(
            "RegistroPersonal.IdRegistroPersonal"
        ),
        nullable=False,
        index=True,
    )

    IdProcesoDisciplinario = Column(
        Integer,
        ForeignKey(
            "ProcesoDisciplinario.IdProcesoDisciplinario"
        ),
        nullable=False,
        index=True,
    )

    FechaSolicitada = Column(
        Date,
        nullable=False,
    )

    MotivoSolicitud = Column(
        Text,
        nullable=False,
    )

    UsuarioSolicita = Column(
        String(100),
        nullable=False,
    )

    EstadoSolicitud = Column(
        String(20),
        nullable=False,
        default="PENDIENTE",
        server_default="PENDIENTE",
        index=True,
    )

    FechaSolicitud = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    UsuarioResuelve = Column(
        String(100),
        nullable=True,
    )

    FechaResolucion = Column(
        DateTime(timezone=True),
        nullable=True,
    )

    ObservacionResolucion = Column(
        Text,
        nullable=True,
    )

    IdAutorizacionAgendaDisciplinaria = Column(
        Integer,
        ForeignKey(
            "AutorizacionAgendaDisciplinaria.IdAutorizacionAgendaDisciplinaria"
        ),
        nullable=True,
    )

    Activo = Column(
        Boolean,
        nullable=False,
        default=True,
        server_default="true",
    )

    FechaCreacion = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    FechaActualizacion = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )