from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
)
from sqlalchemy.sql import func

from infrastructure.db.base import Base


class AsistenteDescargoProcesoDisciplinario(Base):
    __tablename__ = (
        "AsistenteDescargoProcesoDisciplinario"
    )

    IdAsistenteDescargoProcesoDisciplinario = Column(
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
        index=True,
    )

    IdDescargoProcesoDisciplinario = Column(
        Integer,
        ForeignKey(
            "DescargoProcesoDisciplinario."
            "IdDescargoProcesoDisciplinario"
        ),
        nullable=True,
        index=True,
    )

    TipoAsistente = Column(
        String(50),
        nullable=False,
    )

    NombreAsistente = Column(
        String(200),
        nullable=True,
    )

    Asistio = Column(
        Boolean,
        nullable=False,
        default=True,
        server_default="true",
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