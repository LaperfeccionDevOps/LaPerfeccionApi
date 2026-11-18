from __future__ import annotations

import datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    ForeignKey,
    Integer,
    LargeBinary,
    Numeric,
    String,
    TIMESTAMP,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from infrastructure.db.base import Base


class IncapacidadTrabajador(Base):
    __tablename__ = "IncapacidadTrabajador"

    IdIncapacidadTrabajador: Mapped[int] = mapped_column(
        BigInteger,
        primary_key=True,
        autoincrement=True,
    )

    IdRegistroPersonal: Mapped[int] = mapped_column(
        ForeignKey("RegistroPersonal.IdRegistroPersonal"),
        nullable=False,
        index=True,
    )

    TipoIncapacidad: Mapped[str] = mapped_column(
        String(60),
        nullable=False,
    )

    DescripcionTipoIncapacidad: Mapped[str] = mapped_column(
        String(150),
        nullable=False,
    )

    FechaInicio: Mapped[datetime.date] = mapped_column(
        Date,
        nullable=False,
    )

    DiasIncapacidad: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
    )

    FechaFinal: Mapped[datetime.date] = mapped_column(
        Date,
        nullable=False,
    )

    EsProrroga: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
    )

    Estado: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        default="REGISTRADA",
    )

    ObservacionNomina: Mapped[str | None] = mapped_column(
        String(1000),
        nullable=True,
    )

    UsuarioGestionNomina: Mapped[str | None] = mapped_column(
        String(150),
        nullable=True,
    )

    FechaGestionNomina: Mapped[datetime.datetime | None] = mapped_column(
        TIMESTAMP(timezone=True),
        nullable=True,
    )

    NumeroRadicado: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
    )

    FechaRadicacion: Mapped[datetime.date | None] = mapped_column(
        Date,
        nullable=True,
    )

    CausalNegacion: Mapped[str | None] = mapped_column(
        String(1000),
        nullable=True,
    )

    ValorPagado: Mapped[Decimal | None] = mapped_column(
        Numeric(14, 2),
        nullable=True,
    )

    Activo: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
    )

    FechaCreacion: Mapped[datetime.datetime] = mapped_column(
        TIMESTAMP(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    FechaActualizacion: Mapped[datetime.datetime | None] = mapped_column(
        TIMESTAMP(timezone=True),
        nullable=True,
    )

    registro_personal = relationship(
        "RegistroPersonal",
        lazy="joined",
    )

    documentos = relationship(
        "DocumentoIncapacidadTrabajador",
        back_populates="incapacidad",
        lazy="selectin",
    )


class DocumentoIncapacidadTrabajador(Base):
    __tablename__ = "DocumentoIncapacidadTrabajador"

    IdDocumentoIncapacidadTrabajador: Mapped[int] = mapped_column(
        BigInteger,
        primary_key=True,
        autoincrement=True,
    )

    IdIncapacidadTrabajador: Mapped[int] = mapped_column(
        ForeignKey(
            "IncapacidadTrabajador.IdIncapacidadTrabajador"
        ),
        nullable=False,
        index=True,
    )

    TipoDocumento: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
    )

    NombreArchivo: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
    )

    Formato: Mapped[str | None] = mapped_column(
        String(20),
        nullable=True,
    )

    MimeType: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
    )

    TamanoBytes: Mapped[int | None] = mapped_column(
        BigInteger,
        nullable=True,
    )

    DocumentoCargado: Mapped[bytes] = mapped_column(
        LargeBinary,
        nullable=False,
    )

    Activo: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
    )

    FechaCreacion: Mapped[datetime.datetime] = mapped_column(
        TIMESTAMP(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    FechaActualizacion: Mapped[datetime.datetime | None] = mapped_column(
        TIMESTAMP(timezone=True),
        nullable=True,
    )

    incapacidad = relationship(
        "IncapacidadTrabajador",
        back_populates="documentos",
    )
