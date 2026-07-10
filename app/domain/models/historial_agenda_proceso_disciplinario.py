from sqlalchemy import (
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


class HistorialAgendaProcesoDisciplinario(Base):
    __tablename__ = "HistorialAgendaProcesoDisciplinario"

    IdHistorialAgendaProcesoDisciplinario = Column(
        Integer,
        primary_key=True,
        index=True,
    )

    IdAgendaProcesoDisciplinario = Column(
        Integer,
        ForeignKey(
            "AgendaProcesoDisciplinario.IdAgendaProcesoDisciplinario"
        ),
        nullable=False,
        index=True,
    )

    IdProcesoDisciplinario = Column(
        Integer,
        nullable=False,
        index=True,
    )

    IdRegistroPersonal = Column(
        Integer,
        nullable=False,
        index=True,
    )

    TipoMovimiento = Column(
        String(30),
        nullable=False,
    )

    FechaEventoAnterior = Column(
        Date,
        nullable=True,
    )

    HoraInicioAnterior = Column(
        Time,
        nullable=True,
    )

    HoraFinAnterior = Column(
        Time,
        nullable=True,
    )

    EstadoAnterior = Column(
        String(30),
        nullable=True,
    )

    ColorAnterior = Column(
        String(20),
        nullable=True,
    )

    FechaEventoNueva = Column(
        Date,
        nullable=True,
    )

    HoraInicioNueva = Column(
        Time,
        nullable=True,
    )

    HoraFinNueva = Column(
        Time,
        nullable=True,
    )

    EstadoNuevo = Column(
        String(30),
        nullable=True,
    )

    ColorNuevo = Column(
        String(20),
        nullable=True,
    )

    Motivo = Column(
        Text,
        nullable=False,
    )

    UsuarioMovimiento = Column(
        String(100),
        nullable=True,
    )

    FechaMovimiento = Column(
        DateTime(timezone=False),
        nullable=False,
        server_default=func.now(),
    )