# app/domain/models/rol.py
from datetime import datetime
from typing import Optional

from sqlalchemy import Integer, String, DateTime
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from infrastructure.db.base import Base


class Rol(Base):
    __tablename__ = "Roles"  # 👈 nombre EXACTO de la tabla en la BD

    IdRol: Mapped[int] = mapped_column(
        "IdRol", Integer, primary_key=True, autoincrement=True
    )

    NombreRol: Mapped[str] = mapped_column(
        "NombreRol", String(100), nullable=False, unique=True
    )

    UsuarioCreador: Mapped[str] = mapped_column(
        "UsuarioCreador", String(60), nullable=False
    )

    UsuarioActualizacion: Mapped[Optional[str]] = mapped_column(
        "UsuarioActualizacion", String(60), nullable=True
    )

    FechaCreacion: Mapped[datetime] = mapped_column(
        "FechaCreacion", DateTime, server_default=func.now()
    )

    FechaActualizacion: Mapped[Optional[datetime]] = mapped_column(
        "FechaActualizacion", DateTime, nullable=True
    )
