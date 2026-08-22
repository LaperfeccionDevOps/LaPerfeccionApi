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
    Time,
)
from sqlalchemy.sql import func

from infrastructure.db.base import Base


class AutorizacionAgendaDisciplinaria(Base):
    __tablename__ = "AutorizacionAgendaDisciplinaria"

    IdAutorizacionAgendaDisciplinaria = Column(
        Integer,
        primary_key=True,
        index=True,
    )

    IdRegistroPersonal = Column(
        BigInteger,
        ForeignKey("RegistroPersonal.IdRegistroPersonal"),
        nullable=False,
        index=True,
    )

    IdProcesoDisciplinario = Column(
        Integer,
        ForeignKey("ProcesoDisciplinario.IdProcesoDisciplinario"),
        nullable=False,
        index=True,
    )

    IdAgendaProcesoDisciplinario = Column(
        Integer,
        ForeignKey(
            "AgendaProcesoDisciplinario.IdAgendaProcesoDisciplinario"
        ),
        nullable=True,
    )

    FechaAutorizada = Column(
        Date,
        nullable=False,
        index=True,
    )

    HoraInicio = Column(
        Time,
        nullable=False,
    )

    HoraFin = Column(
        Time,
        nullable=False,
    )

    TipoAutorizacion = Column(
        String(30),
        nullable=False,
        default="VIERNES",
        server_default="VIERNES",
    )

    MotivoAutorizacion = Column(
        Text,
        nullable=False,
    )

    UsuarioSolicita = Column(
        String(100),
        nullable=True,
    )

    UsuarioAutoriza = Column(
        String(100),
        nullable=False,
    )

    EstadoAutorizacion = Column(
        String(20),
        nullable=False,
        default="ACTIVA",
        server_default="ACTIVA",
    )

    FechaAutorizacion = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    FechaUtilizacion = Column(
        DateTime(timezone=True),
        nullable=True,
    )

    Observacion = Column(
        Text,
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