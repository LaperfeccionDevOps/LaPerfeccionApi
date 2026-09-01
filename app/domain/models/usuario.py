from datetime import datetime
from typing import Optional
import uuid

from sqlalchemy import String, DateTime
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from infrastructure.db.base import Base


class Usuario(Base):
    __tablename__ = "Usuario"

    # PK
    # PostgreSQL genera automáticamente el UUID mediante uuid_generate_v4().
    IdUsuario: Mapped[uuid.UUID] = mapped_column(
        "IdUsuario",
        UUID(as_uuid=True),
        primary_key=True,
        server_default=func.uuid_generate_v4(),
    )

    # Nombre completo de la persona.
    # Se mantiene el nombre de columna existente para compatibilidad.
    NombreUsuario: Mapped[str] = mapped_column(
        "NombreUsuario",
        String(100),
        nullable=False,
        unique=True,
    )

    # Login individual utilizado para ingresar al sistema.
    # Es nullable para mantener compatibilidad con usuarios históricos.
    Usuario: Mapped[Optional[str]] = mapped_column(
        "Usuario",
        String(120),
        nullable=True,
    )

    # La contraseña almacenada en esta columna siempre debe ser un hash.
    Contrasena: Mapped[str] = mapped_column(
        "Contraseña",
        String(250),
        nullable=False,
    )

    HashEstado: Mapped[str] = mapped_column(
        "HashEstado",
        String(20),
        nullable=False,
        default="ACTIVO",
    )

    FechaCreacion: Mapped[Optional[datetime]] = mapped_column(
        "FechaCreacion",
        DateTime(timezone=True),
        nullable=True,
        server_default=func.now(),
    )

    FechaActualizacion: Mapped[Optional[datetime]] = mapped_column(
        "FechaActualizacion",
        DateTime(timezone=True),
        nullable=True,
    )

    UsuarioCreador: Mapped[str] = mapped_column(
        "UsuarioCreador",
        String(60),
        nullable=False,
    )

    UsuarioActualizacion: Mapped[Optional[str]] = mapped_column(
        "UsuarioActualizacion",
        String(60),
        nullable=True,
    )

    CorreoCorporativo: Mapped[Optional[str]] = mapped_column(
        "CorreoCorporativo",
        String(120),
        nullable=True,
    )