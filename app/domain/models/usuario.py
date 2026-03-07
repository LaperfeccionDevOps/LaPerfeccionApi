# app/domain/models/usuario.py
from datetime import datetime
from typing import Optional

from sqlalchemy import Integer, String, DateTime
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from infrastructure.db.base import Base


class Usuario(Base):
    __tablename__ = "Usuario"  # 👈 nombre de la tabla en la BD

    # PK
    IdUsuario: Mapped[int] = mapped_column(
        "IdUsuario", Integer, primary_key=True, autoincrement=True
    )

    # Nombre de usuario (login)
    NombreUsuario: Mapped[str] = mapped_column(
        "NombreUsuario", String(100), nullable=False, unique=True
    )

    # Aquí vamos a guardar el HASH de la contraseña (no la contraseña en texto)
    Contrasena: Mapped[str] = mapped_column(
        "Contraseña", String(250), nullable=False
    )

    HashEstado: Mapped[str] = mapped_column(
        "HashEstado", String(20), nullable=False, default="ACTIVO"
    )

    FechaCreacion: Mapped[datetime] = mapped_column(
        "FechaCreacion", DateTime, server_default=func.now()
    )

    FechaActualizacion: Mapped[Optional[datetime]] = mapped_column(
        "FechaActualizacion", DateTime, nullable=True
    )

    UsuarioCreador: Mapped[str] = mapped_column(
        "UsuarioCreador", String(60), nullable=False
    )

    UsuarioActualizacion: Mapped[Optional[str]] = mapped_column(
        "UsuarioActualizacion", String(60), nullable=True
    )
