from __future__ import annotations

from typing import Optional
import datetime

from sqlalchemy import String, Integer, Boolean, TIMESTAMP
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func
from infrastructure.db.base import Base

class TipoEstadoFormacion(Base):
    __tablename__ = "TipoEstadoFormacion"

    IdTipoEstadoFormacion: Mapped[int] = mapped_column(
        Integer, primary_key=True, autoincrement=True
    )
    Nombre: Mapped[str] = mapped_column(String(100), nullable=False)
    Estado: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    FechaCreacion: Mapped[datetime.datetime] = mapped_column(
        TIMESTAMP(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

