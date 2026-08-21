# ruff: noqa: F401
# app/domain/models/aspirante.py
from __future__ import annotations

import datetime

from sqlalchemy import (
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

from domain.models.combos_models import (
    FondoCesantias,
    FondoPensiones,
    Localidades,
    TipoCargo,
    TipoEps,
    TipoEstadoCivil,
    TipoGenero,
    TipoIdentificacion,
)
from domain.models.datos_seleccion import DatosSeleccion
from domain.models.estado_proceso_models import EstadoProceso
from domain.models.experiencia_laboral_validacion import ExperienciaLaboralValidacion
from domain.models.grupo_saguineo import GrupoSanguineo
from domain.models.limitacion_fisica_hijo_models import LimitacionFisicaHijo
from domain.models.nivel_educativo_models import NivelEducativo
from domain.models.referencia_personal_validacion import ReferenciaPersonalValidacion
from domain.models.tipo_estado_formacion_models import TipoEstadoFormacion
from infrastructure.db.base import Base

class RegistroPersonal(Base):
    __tablename__ = "RegistroPersonal"

    IdRegistroPersonal: Mapped[int] = mapped_column(
        Integer, primary_key=True, autoincrement=True
    )

    IdTipoIdentificacion: Mapped[int] = mapped_column(
        ForeignKey("TipoIdentificacion.IdTipoIdentificacion"), nullable=False
    )
    IdTipoCargo: Mapped[int] = mapped_column(
        ForeignKey("TipoCargo.IdTipoCargo"), nullable=False
    )
    IdTipoEps: Mapped[int | None] = mapped_column(
        ForeignKey("TipoEps.IdTipoEps"), nullable=True
    )
    IdTipoEstadoCivil: Mapped[int | None] = mapped_column(
        ForeignKey("TipoEstadoCivil.IdTipoEstadoCivil"), nullable=True
    )
    IdTipoGenero: Mapped[int | None] = mapped_column(
        ForeignKey("TipoGenero.IdTipoGenero"), nullable=True
    )
    IdEstadoProceso: Mapped[int | None] = mapped_column(
        ForeignKey("EstadoProceso.IdEstadoProceso"), nullable=True
    )

    IdFondoPensiones: Mapped[int | None] = mapped_column(
        ForeignKey("FondoPensiones.IdFondoPensiones"), nullable=True
    )

    # ✅ NUEVO: Fondo de Cesantías (FK)
    IdFondoCesantias: Mapped[int | None] = mapped_column(
        ForeignKey("FondoCesantias.IdFondoCesantias"),
        nullable=True
    )

    IdLimitacionFisicaHijo: Mapped[int | None] = mapped_column(
        ForeignKey("LimitacionFisicaHijo.IdLimitacionFisicaHijo"), nullable=True
    )
    IdNivelEducativo: Mapped[int | None] = mapped_column(
        ForeignKey("NivelEducativo.IdNivelEducativo"), nullable=True
    )

    # === Datos personales ===
    NumeroIdentificacion: Mapped[str] = mapped_column(String(50), nullable=False)
    FechaExpedicion: Mapped[datetime.date | None] = mapped_column(Date, nullable=True)
    LugarExpedicion: Mapped[str | None] = mapped_column(String(100), nullable=True)

    Nombres: Mapped[str] = mapped_column(String(100), nullable=False)
    Apellidos: Mapped[str] = mapped_column(String(100), nullable=False)
    Email: Mapped[str | None] = mapped_column(String(150), nullable=True)
    Celular: Mapped[str | None] = mapped_column(String(20), nullable=True)

    TieneWhatsapp: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    NumeroWhatsapp: Mapped[str | None] = mapped_column(String(20), nullable=True)

    PesoKilogramos: Mapped[float | None] = mapped_column(Numeric(5, 2), nullable=True)
    AlturaMetros: Mapped[float | None] = mapped_column(Numeric(4, 2), nullable=True)

    ContactoEmergencia: Mapped[str | None] = mapped_column(String(100), nullable=True)
    TelefonoContactoEmergencia: Mapped[str | None] = mapped_column(String(20), nullable=True)

    IdTipoEstadoFormacion: Mapped[int | None] = mapped_column(
        ForeignKey("TipoEstadoFormacion.IdTipoEstadoFormacion"), nullable=True
    )

    FechaCreacion: Mapped[datetime.datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=func.now(), nullable=False
    )
    FechaActualizacion: Mapped[datetime.datetime | None] = mapped_column(
        TIMESTAMP(timezone=True), nullable=True
    )
    FechaNacimiento: Mapped[datetime.date | None] = mapped_column(Date, nullable=True)
    UsuarioActualizacion: Mapped[str | None] = mapped_column(String(50), nullable=True)

    EstudiaActualmente: Mapped[str | None] = mapped_column(String, nullable=True)

    TieneHijos: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    CuantosHijos: Mapped[int | None] = mapped_column(Integer, nullable=True)

    ComoSeEnteroVacante: Mapped[str | None] = mapped_column(String(200), nullable=True)
    IdLugarNacimiento: Mapped[int | None] = mapped_column(
        ForeignKey("LugarNacimiento.IdLugarNacimiento"), nullable=True
    )
    TieneLimitacionesFisicas: Mapped[str | None] = mapped_column(String(100), nullable=True)
    DescripcionFormacionAcademica: Mapped[str | None] = mapped_column(String(500), nullable=True)

    # === Relaciones ORM ===
    tipo_identificacion = relationship("TipoIdentificacion", lazy="joined")
    tipo_cargo = relationship("TipoCargo", lazy="joined")
    tipo_eps = relationship("TipoEps", lazy="joined")
    tipo_estado_civil = relationship("TipoEstadoCivil", lazy="joined")
    tipo_genero = relationship("TipoGenero", lazy="joined")
    estado_proceso = relationship("EstadoProceso", lazy="joined")

    fondo_pensiones = relationship("FondoPensiones", lazy="joined")
    # ✅ NUEVO: relación Cesantías
    fondo_cesantias = relationship("FondoCesantias", lazy="joined")

    nivel_educativo = relationship("NivelEducativo", lazy="joined")
    estado_formacion = relationship("TipoEstadoFormacion", lazy="joined")
    lugar_nacimiento = relationship("LugarNacimientoORM", lazy="joined")

    experiencia_laboral = relationship(
        "ExperienciaLaboralORM",
        back_populates="registro_personal",
        cascade="all, delete-orphan",
        lazy="joined",
    )

    datos_adicionales = relationship(
        "DatosAdicionalesORM",
        back_populates="registro_personal",
        cascade="all, delete-orphan",
        lazy="joined",
    )

    nucleo_familiar = relationship(
        "NucleoFamiliarORM",
        back_populates="registro_personal",
        cascade="all, delete-orphan",
        lazy="joined",
    )

    referencias = relationship(
        "ReferenciaORM",
        back_populates="registro_personal",
        cascade="all, delete-orphan",
        lazy="joined",
    )

    referencias_personales_validacion = relationship(
        "ReferenciaPersonalValidacion",
        primaryjoin="RegistroPersonal.IdRegistroPersonal == foreign(ReferenciaPersonalValidacion.IdRegistroPersonal)",
        lazy="joined",
    )

    datos_seleccion = relationship(
        "DatosSeleccion",
        primaryjoin="RegistroPersonal.IdRegistroPersonal == foreign(DatosSeleccion.IdRegistroPersonal)",
        lazy="joined",
    )


class NucleoFamiliarORM(Base):
    __tablename__ = "NucleoFamiliar"

    IdNucleoFamiliar: Mapped[int] = mapped_column(
        Integer, primary_key=True, autoincrement=True
    )
    IdRegistroPersonal: Mapped[int] = mapped_column(
        ForeignKey("RegistroPersonal.IdRegistroPersonal"), nullable=False
    )

    IdVinculacionLaboral: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
    )

    TieneparentescoEnLaEmpresa: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    NombreFamiliarEmpresa: Mapped[str | None] = mapped_column(String(150), nullable=True)
    CargoDesempenaEmpresa: Mapped[str | None] = mapped_column(String(100), nullable=True)
    CedulaFamiliarEmpresa: Mapped[str | None] = mapped_column(String(50), nullable=True)
    ParentescoFamiliarEmpresa: Mapped[str | None] = mapped_column(String(60), nullable=True)

    Nombre: Mapped[str | None] = mapped_column(String(150), nullable=True)
    Parentesco: Mapped[str | None] = mapped_column(String(60), nullable=True)
    Edad: Mapped[int | None] = mapped_column(Integer, nullable=True)
    Ocupacion: Mapped[str | None] = mapped_column(String(100), nullable=True)
    Telefono: Mapped[str | None] = mapped_column(String(30), nullable=True)
    Observaciones: Mapped[str | None] = mapped_column(String(8000), nullable=True)
    DependeEconomicamente: Mapped[bool | None] = mapped_column(Boolean, nullable=True)

    registro_personal = relationship(
        "RegistroPersonal", back_populates="nucleo_familiar", lazy="joined"
    )

    observaciones = relationship(
        "ObservacionesNucleoFamiliarORM",
        back_populates="nucleo_familiar",
        uselist=False,
        lazy="joined"
    )


class ExperienciaLaboralORM(Base):
    __tablename__ = "ExperienciaLaboral"

    IdExperienciaLaboral: Mapped[int] = mapped_column(
        Integer, primary_key=True, autoincrement=True
    )
    IdRegistroPersonal: Mapped[int] = mapped_column(
        ForeignKey("RegistroPersonal.IdRegistroPersonal"), nullable=False
    )

    IdVinculacionLaboral: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
    )

    Cargo: Mapped[str | None] = mapped_column(String(100), nullable=True)
    Compania: Mapped[str | None] = mapped_column(String(150), nullable=True)
    TiempoDuracion: Mapped[str | None] = mapped_column(String(50), nullable=True)
    Funciones: Mapped[str | None] = mapped_column(String(8000), nullable=True)
    JefeInmediato: Mapped[str | None] = mapped_column(String(100), nullable=True)
    TelefonoJefe: Mapped[str | None] = mapped_column(String(10), nullable=True)
    TieneExperienciaPrevia: Mapped[bool | None] = mapped_column(Boolean, nullable=True)

    registro_personal = relationship(
        "RegistroPersonal", back_populates="experiencia_laboral", lazy="joined"
    )

    validaciones = relationship(
        "ExperienciaLaboralValidacion",
        primaryjoin="ExperienciaLaboralORM.IdExperienciaLaboral == foreign(ExperienciaLaboralValidacion.IdExperienciaLaboral)",
        lazy="joined",
    )


class DocumentacionORM(Base):
    __tablename__ = "Documentos"

    IdDocumento: Mapped[int] = mapped_column(
        Integer, primary_key=True, autoincrement=True
    )
    IdTipoDocumentacion: Mapped[int] = mapped_column(
        ForeignKey("TipoDocumentacion.IdTipoDocumentacion"), nullable=False
    )

    DocumentoCargado: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)

    FechaCreacion: Mapped[TIMESTAMP] = mapped_column(
        TIMESTAMP(timezone=True), server_default=func.now(), nullable=False
    )
    FechaActualizacion: Mapped[datetime.datetime | None] = mapped_column(
        TIMESTAMP(timezone=True), nullable=True
    )

    Formato: Mapped[str | None] = mapped_column(String(20), nullable=True)
    Nombre: Mapped[str | None] = mapped_column(String(150), nullable=True)


class TipoDocumentacion(Base):
    __tablename__ = "TipoDocumentacion"

    IdTipoDocumentacion: Mapped[int] = mapped_column(
        Integer, primary_key=True, autoincrement=True
    )
    Descripcion: Mapped[str | None] = mapped_column(String(130), nullable=True)
    Estado: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    IdCategoria: Mapped[int] = mapped_column(Integer, nullable=True)

    FechaCreacion: Mapped[TIMESTAMP] = mapped_column(
        TIMESTAMP(timezone=True), server_default=func.now(), nullable=False
    )
    FechaActualizacion: Mapped[datetime.datetime | None] = mapped_column(
        TIMESTAMP(timezone=True), nullable=True
    )


class ReferenciaORM(Base):
    __tablename__ = "Referencia"

    IdReferencia: Mapped[int] = mapped_column(
        Integer, primary_key=True, autoincrement=True
    )
    IdRegistroPersonal: Mapped[int] = mapped_column(
        ForeignKey("RegistroPersonal.IdRegistroPersonal"), nullable=False
    )

    IdVinculacionLaboral: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
    )

    IdTipoReferencia: Mapped[int] = mapped_column(Integer, nullable=True)
    Nombre: Mapped[str | None] = mapped_column(String(150), nullable=True)
    Telefono: Mapped[str | None] = mapped_column(String(30), nullable=True)
    Parentesco: Mapped[str | None] = mapped_column(String(60), nullable=True)
    TiempoConocerlo: Mapped[str | None] = mapped_column(String(50), nullable=True)

    FechaCreacion: Mapped[TIMESTAMP] = mapped_column(
        TIMESTAMP(timezone=True), server_default=func.now(), nullable=False
    )
    FechaActualizacion: Mapped[datetime.datetime | None] = mapped_column(
        TIMESTAMP(timezone=True), nullable=True
    )

    registro_personal = relationship(
        "RegistroPersonal",
        back_populates="referencias",
        lazy="joined",
    )


class DatosAdicionalesORM(Base):
    __tablename__ = "DatosAdicionales"

    IdDatosAdicionales: Mapped[int] = mapped_column(
        Integer, primary_key=True, autoincrement=True
    )
    IdRegistroPersonal: Mapped[int] = mapped_column(
        ForeignKey("RegistroPersonal.IdRegistroPersonal"), nullable=False
    )

    Direccion: Mapped[str | None] = mapped_column(String(500), nullable=True)
    IdCiudad: Mapped[int | None] = mapped_column(Integer, nullable=True)
    IdLocalidad: Mapped[int] = mapped_column(
        ForeignKey("Localidad.IdLocalidad"), nullable=False
    )

    Barrio: Mapped[str | None] = mapped_column(String(150), nullable=True)
    Estrato: Mapped[int | None] = mapped_column(Integer, nullable=True)

    IdGrupoSanguineo: Mapped[int] = mapped_column(
        ForeignKey("GrupoSanguineo.IdGrupoSanguineo"), nullable=True
    )
    HobbyPasatiempo: Mapped[str | None] = mapped_column(String(200), nullable=True)

    registro_personal = relationship(
        "RegistroPersonal",
        back_populates="datos_adicionales",
        lazy="joined",
    )

    grupo_sanguineo = relationship(
        "GrupoSanguineo",
        lazy="joined",
    )

    localidad = relationship(
        "Localidades",
        lazy="joined",
    )

class LugarNacimientoORM(Base):
    __tablename__ = "LugarNacimiento"

    IdLugarNacimiento: Mapped[int] = mapped_column(
        Integer, primary_key=True, autoincrement=True
    )
    CodigoMunicipio: Mapped[str | None] = mapped_column(String(30), nullable=True)
    CodigoDepartamento: Mapped[str | None] = mapped_column(String(30), nullable=True)
    Nombre: Mapped[str | None] = mapped_column(String(150), nullable=True)
    Estado: Mapped[bool | None] = mapped_column(Boolean, nullable=True)

    FechaCreacion: Mapped[TIMESTAMP] = mapped_column(
        TIMESTAMP(timezone=True), server_default=func.now(), nullable=False
    )


class RelacionTipoDocumentacionORM(Base):
    __tablename__ = "RelacionTipoDocumentacion"

    IdRelacion: Mapped[int] = mapped_column(
        Integer, primary_key=True, autoincrement=True
    )
    IdRegistroPersonal: Mapped[int] = mapped_column(
        ForeignKey("RegistroPersonal.IdRegistroPersonal"), nullable=False
    )
    IdDocumento: Mapped[int] = mapped_column(
        ForeignKey("Documentos.IdDocumento"), nullable=False
    )

    IdVinculacionLaboral: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
    )


class ObservacionesNucleoFamiliarORM(Base):
    __tablename__ = "ObservacionesNucleoFamiliar"

    IdObservacionesNucleoFamiliar: Mapped[int] = mapped_column(
        Integer, primary_key=True, autoincrement=True
    )
    IdNucleoFamiliar: Mapped[int] = mapped_column(
        ForeignKey("NucleoFamiliar.IdNucleoFamiliar"), nullable=False, unique=True
    )
    Observaciones: Mapped[str | None] = mapped_column(String(8000), nullable=True)
    FechaCreacion: Mapped[TIMESTAMP] = mapped_column(
        TIMESTAMP(timezone=True), server_default=func.now(), nullable=False
    )
    UsuarioActualizacion: Mapped[str | None] = mapped_column(String(50), nullable=True)

    nucleo_familiar = relationship(
        "NucleoFamiliarORM", back_populates="observaciones", lazy="joined"
    )   