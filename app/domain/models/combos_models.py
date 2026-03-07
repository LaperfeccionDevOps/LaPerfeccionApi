from __future__ import annotations

from typing import Optional
import datetime

from sqlalchemy import Column, Integer, String, Boolean, DateTime
from sqlalchemy.dialects.postgresql import TIMESTAMP
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from infrastructure.db.base import Base


class TipoIdentificacion(Base):
    __tablename__ = "TipoIdentificacion"

    IdTipoIdentificacion = Column(Integer, primary_key=True, index=True, autoincrement=True)
    Descripcion = Column(String(100), nullable=True)
    Estado = Column(Boolean, nullable=True)
    FechaCreacion = Column(DateTime(timezone=True), server_default=func.now())
    FechaActualizacion = Column(String(100), nullable=True)


class TipoCargo(Base):
    __tablename__ = "TipoCargo"

    IdTipoCargo = Column(Integer, primary_key=True, index=True, autoincrement=True)
    Codigo = Column(String(100), nullable=True)
    Descripcion = Column(String(100), nullable=True)
    Estado = Column(Boolean, nullable=True)
    FechaCreacion = Column(DateTime(timezone=True), server_default=func.now())
    FechaActualizacion = Column(String(100), nullable=True)


class TipoEps(Base):
    __tablename__ = "TipoEps"

    IdTipoEps = Column(Integer, primary_key=True, index=True, autoincrement=True)
    Descripcion = Column(String(100), nullable=True)
    Estado = Column(Boolean, nullable=True)
    FechaCreacion = Column(DateTime(timezone=True), server_default=func.now())
    FechaActualizacion = Column(String(100), nullable=True)


class TipoEstadoCivil(Base):
    __tablename__ = "TipoEstadoCivil"

    IdTipoEstadoCivil = Column(Integer, primary_key=True, index=True, autoincrement=True)
    Descripcion = Column(String(100), nullable=True)
    Estado = Column(Boolean, nullable=True)
    FechaCreacion = Column(DateTime(timezone=True), server_default=func.now())
    FechaActualizacion = Column(String(100), nullable=True)


class TipoFormacionAcademica(Base):
    __tablename__ = "TipoFormacionAcademica"

    IdTipoFormacionAcademica = Column(Integer, primary_key=True, index=True, autoincrement=True)
    Descripcion = Column(String(100), nullable=True)
    Estado = Column(Boolean, nullable=True)
    FechaCreacion = Column(DateTime(timezone=True), server_default=func.now())
    FechaActualizacion = Column(String(100), nullable=True)


class TipoGenero(Base):
    __tablename__ = "TipoGenero"

    IdTipoGenero = Column(Integer, primary_key=True, index=True, autoincrement=True)
    Descripcion = Column(String(100), nullable=True)
    Estado = Column(Boolean, nullable=True)
    FechaCreacion = Column(DateTime(timezone=True), server_default=func.now())
    FechaActualizacion = Column(String(100), nullable=True)


class TipoPrueba(Base):
    __tablename__ = "TipoPrueba"

    IdTipoPrueba = Column(Integer, primary_key=True, index=True, autoincrement=True)
    Descripcion = Column(String(100), nullable=True)
    Estado = Column(Boolean, nullable=True)
    FechaCreacion = Column(DateTime(timezone=True), server_default=func.now())
    FechaActualizacion = Column(String(100), nullable=True)


class TipoReferencia(Base):
    __tablename__ = "TipoReferencia"

    IdTipoReferencia = Column(Integer, primary_key=True, index=True, autoincrement=True)
    Descripcion = Column(String(100), nullable=True)
    Estado = Column(Boolean, nullable=True)
    FechaCreacion = Column(DateTime(timezone=True), server_default=func.now())


# ===========================
#  CATÁLOGOS (Mapped style)
# ===========================

class FondoPensiones(Base):
    __tablename__ = "FondoPensiones"

    IdFondoPensiones: Mapped[int] = mapped_column(
        Integer, primary_key=True, autoincrement=True
    )
    Nombre: Mapped[Optional[str]] = mapped_column(String(150), nullable=True)
    Nit: Mapped[Optional[str]] = mapped_column(String(30), nullable=True)

    FechaCreacion: Mapped[datetime.datetime] = mapped_column(
        TIMESTAMP(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    FechaActualizacion: Mapped[Optional[datetime.datetime]] = mapped_column(
        TIMESTAMP(timezone=True),
        nullable=True,
    )


# ✅ NUEVO: FondoCesantias (según tu tabla creada)
class FondoCesantias(Base):
    __tablename__ = "FondoCesantias"

    IdFondoCesantias: Mapped[int] = mapped_column(
        Integer, primary_key=True, autoincrement=True
    )

    # Si en la BD está NOT NULL, cambia nullable=False
    Nombre: Mapped[Optional[str]] = mapped_column(String(150), nullable=True)
    Nit: Mapped[Optional[str]] = mapped_column(String(30), nullable=True)
    Codigo: Mapped[Optional[str]] = mapped_column(String(30), nullable=True)

    Estado: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)

    FechaCreacion: Mapped[Optional[datetime.datetime]] = mapped_column(
        TIMESTAMP(timezone=True),
        nullable=True,
    )

    FechaActualizacion: Mapped[Optional[datetime.datetime]] = mapped_column(
        TIMESTAMP(timezone=True),
        nullable=True,
    )

    # En tu tabla quedó como timestamp, por eso datetime
    UsuarioCreacion: Mapped[Optional[datetime.datetime]] = mapped_column(
        TIMESTAMP(timezone=True),
        nullable=True,
    )


class EstadoFormacion(Base):
    __tablename__ = "EstadoFormacion"

    IdEstadoFormacion: Mapped[int] = mapped_column(
        Integer, primary_key=True, autoincrement=True
    )
    Nombre: Mapped[Optional[str]] = mapped_column(String(150), nullable=True)
    Estado: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)

    FechaCreacion: Mapped[datetime.datetime] = mapped_column(
        TIMESTAMP(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

class Localidades(Base):
    __tablename__ = "Localidad"

    IdLocalidad: Mapped[int] = mapped_column(
        Integer, primary_key=True, autoincrement=True
    )
    CodigoMunicipio: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    CodigoDepartamento: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    Nombre: Mapped[Optional[str]] = mapped_column(String(150), nullable=True)
    Estado: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    FechaCreacion: Mapped[datetime.datetime] = mapped_column(
        TIMESTAMP(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

class Cargo(Base):
    __tablename__ = "Cargo"

    IdCargo: Mapped[int] = mapped_column(
        Integer, primary_key=True, autoincrement=True
    )
    NombreCargo: Mapped[Optional[str]] = mapped_column(String(150), nullable=True)
    IdTipoCargo: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    Activo: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    FechaCreacion: Mapped[datetime.datetime] = mapped_column(
        TIMESTAMP(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    FechaActualizacion: Mapped[Optional[datetime.datetime]] = mapped_column(
        TIMESTAMP(timezone=True),
        nullable=True,
    )
    UsuarioActualizacion: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
