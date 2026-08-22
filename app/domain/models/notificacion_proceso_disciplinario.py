from sqlalchemy import (
    BigInteger,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.sql import func

from infrastructure.db.base import Base


class NotificacionProcesoDisciplinario(Base):
    __tablename__ = "NotificacionProcesoDisciplinario"

    IdNotificacionProcesoDisciplinario = Column(
        BigInteger,
        primary_key=True,
        index=True,
        autoincrement=True,
    )

    IdProcesoDisciplinario = Column(
        Integer,
        ForeignKey(
            "ProcesoDisciplinario.IdProcesoDisciplinario"
        ),
        nullable=False,
        index=True,
    )

    IdAgendaProcesoDisciplinario = Column(
        Integer,
        ForeignKey(
            "AgendaProcesoDisciplinario."
            "IdAgendaProcesoDisciplinario"
        ),
        nullable=True,
        index=True,
    )

    Destinatario = Column(
        String(250),
        nullable=False,
    )

    TipoNotificacion = Column(
        String(50),
        nullable=False,
    )

    Estado = Column(
        String(30),
        nullable=False,
        default="PENDIENTE",
        server_default="PENDIENTE",
    )

    Asunto = Column(
        String(300),
        nullable=True,
    )

    MensajeError = Column(
        Text,
        nullable=True,
    )

    FechaEnvio = Column(
        DateTime(timezone=True),
        nullable=True,
    )

    FechaCreacion = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    FechaActualizacion = Column(
        DateTime(timezone=True),
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