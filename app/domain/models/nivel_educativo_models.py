from __future__ import annotations

from typing import Optional
import datetime

from sqlalchemy import String, Integer, Boolean, TIMESTAMP
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func
from infrastructure.db.base import Base
from sqlalchemy.dialects.postgresql import BIT


class NivelEducativo(Base):
    __tablename__ = "NivelEducativo"

    IdNivelEducativo: Mapped[int] = mapped_column(
        Integer, primary_key=True, autoincrement=True
    )
    Descripcion: Mapped[Optional[str]] = mapped_column(String(130), nullable=True)
    Estado: Mapped[Optional[Boolean]] = mapped_column(Boolean, nullable=True)
    FechaCreacion: Mapped[datetime.datetime] = mapped_column(
        TIMESTAMP(timezone=True),
        server_default=func.now(),
        nullable=False,
    )