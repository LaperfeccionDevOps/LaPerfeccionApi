# app/domain/models/cita.py
from __future__ import annotations

from typing import Optional
from datetime import datetime

from sqlalchemy import (
    Integer,
    String,
    Text,
    TIMESTAMP,
    ForeignKey,
)
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from infrastructure.db.base import Base


class Cita(Base):
    __tablename__ = "AgendarEntrevista"

    IdAgendarEntrevista: Mapped[int] = mapped_column(
        Integer, primary_key=True, autoincrement=True
    )

    IdRegistroPersonal: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("RegistroPersonal.IdRegistroPersonal"),
        nullable=False,
    )

    # En la BD SON timestamp with time zone → datetime en Python
    FechaProgramada: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True),
        nullable=False,
    )

    HoraProgramada: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True),
        nullable=False,
    )

    Observaciones: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
    )

    FechaCreacion: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    FechaActualizacion: Mapped[Optional[datetime]] = mapped_column(
        TIMESTAMP(timezone=True),
        nullable=True,
    )

    NombreUsuarioActualizacion: Mapped[Optional[str]] = mapped_column(
        String(100),
        nullable=True,
    )