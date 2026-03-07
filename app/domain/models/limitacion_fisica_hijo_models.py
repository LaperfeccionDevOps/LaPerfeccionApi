from __future__ import annotations

from typing import Optional
import datetime

from sqlalchemy import String, Integer, Boolean, TIMESTAMP
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func
from infrastructure.db.base import Base
from sqlalchemy.dialects.postgresql import BIT


class LimitacionFisicaHijo(Base):
    __tablename__ = "LimitacionFisicaHijo"

    IdLimitacionFisicaHijo: Mapped[int] = mapped_column(
        Integer, primary_key=True, autoincrement=True
    )
    Nombre: Mapped[Optional[str]] = mapped_column(String(250), nullable=True)
    Estado: Mapped[Optional[str]] = mapped_column(BIT(1), nullable=True)
    FechaCreacion: Mapped[datetime.datetime] = mapped_column(
        TIMESTAMP(timezone=True),
        server_default=func.now(),
        nullable=False,
    )