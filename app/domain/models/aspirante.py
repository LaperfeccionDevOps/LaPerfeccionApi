# ruff: noqa: F401
# app/domain/models/aspirante.py
from __future__ import annotations

from typing import Optional
import datetime

from sqlalchemy import String, Integer, Boolean, Date, Numeric, TIMESTAMP, ForeignKey, LargeBinary
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from infrastructure.db.base import Base

# ✅ Imports para registrar modelos (aunque se usen por relationship("..."))
from domain.models.combos_models import (
    TipoIdentificacion,
    TipoCargo,
    TipoEps,
    TipoEstadoCivil,
    TipoGenero,
    FondoPensiones,
    FondoCesantias,
)

from domain.models.estado_proceso_models import EstadoProceso
from domain.models.limitacion_fisica_hijo_models import LimitacionFisicaHijo
from domain.models.nivel_educativo_models import NivelEducativo
from domain.models.tipo_estado_formacion_models import TipoEstadoFormacion
from domain.models.grupo_saguineo import GrupoSanguineo
from domain.models.experiencia_laboral_validacion import ExperienciaLaboralValidacion
from domain.models.referencia_personal_validacion import ReferenciaPersonalValidacion
from domain.models.datos_seleccion import DatosSeleccion
from domain.models.combos_models import Localidades


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
    IdTipoEps: Mapped[Optional[int]] = mapped_column(
        ForeignKey("TipoEps.IdTipoEps"), nullable=True
    )
    IdTipoEstadoCivil: Mapped[Optional[int]] = mapped_column(
        ForeignKey("TipoEstadoCivil.IdTipoEstadoCivil"), nullable=True
    )
    IdTipoGenero: Mapped[Optional[int]] = mapped_column(
        ForeignKey("TipoGenero.IdTipoGenero"), nullable=True
    )
    IdEstadoProceso: Mapped[Optional[int]] = mapped_column(
        ForeignKey("EstadoProceso.IdEstadoProceso"), nullable=True
    )

    IdFondoPensiones: Mapped[Optional[int]] = mapped_column(
        ForeignKey("FondoPensiones.IdFondoPensiones"), nullable=True
    )

    # ✅ NUEVO: Fondo de Cesantías (FK)
    IdFondoCesantias: Mapped[Optional[int]] = mapped_column(
        ForeignKey("FondoCesantias.IdFondoCesantias"),
        nullable=True
    )

    IdLimitacionFisicaHijo: Mapped[Optional[int]] = mapped_column(
        ForeignKey("LimitacionFisicaHijo.IdLimitacionFisicaHijo"), nullable=True
    )
    IdNivelEducativo: Mapped[Optional[int]] = mapped_column(
        ForeignKey("NivelEducativo.IdNivelEducativo"), nullable=True
    )

    # === Datos personales ===
    NumeroIdentificacion: Mapped[str] = mapped_column(String(50), nullable=False)
    FechaExpedicion: Mapped[Optional[datetime.date]] = mapped_column(Date, nullable=True)
    LugarExpedicion: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)

    Nombres: Mapped[str] = mapped_column(String(100), nullable=False)
    Apellidos: Mapped[str] = mapped_column(String(100), nullable=False)
    Email: Mapped[Optional[str]] = mapped_column(String(150), nullable=True)
    Celular: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)

    TieneWhatsapp: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    NumeroWhatsapp: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)

    PesoKilogramos: Mapped[Optional[float]] = mapped_column(Numeric(5, 2), nullable=True)
    AlturaMetros: Mapped[Optional[float]] = mapped_column(Numeric(4, 2), nullable=True)

    ContactoEmergencia: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    TelefonoContactoEmergencia: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)

    IdTipoEstadoFormacion: Mapped[Optional[int]] = mapped_column(
        ForeignKey("TipoEstadoFormacion.IdTipoEstadoFormacion"), nullable=True
    )

    FechaCreacion: Mapped[datetime.datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=func.now(), nullable=False
    )
    FechaActualizacion: Mapped[Optional[datetime.datetime]] = mapped_column(
        TIMESTAMP(timezone=True), nullable=True
    )
    FechaNacimiento: Mapped[Optional[datetime.date]] = mapped_column(Date, nullable=True)
    UsuarioActualizacion: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)

    EstudiaActualmente: Mapped[Optional[str]] = mapped_column(String, nullable=True)

    TieneHijos: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    CuantosHijos: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    ComoSeEnteroVacante: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    IdLugarNacimiento: Mapped[Optional[int]] = mapped_column(
        ForeignKey("LugarNacimiento.IdLugarNacimiento"), nullable=True
    )
    TieneLimitacionesFisicas: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    DescripcionFormacionAcademica: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)

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

    TieneparentescoEnLaEmpresa: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    NombreFamiliarEmpresa: Mapped[Optional[str]] = mapped_column(String(150), nullable=True)
    CargoDesempenaEmpresa: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    CedulaFamiliarEmpresa: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    ParentescoFamiliarEmpresa: Mapped[Optional[str]] = mapped_column(String(60), nullable=True)

    Nombre: Mapped[Optional[str]] = mapped_column(String(150), nullable=True)
    Parentesco: Mapped[Optional[str]] = mapped_column(String(60), nullable=True)
    Edad: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    Ocupacion: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    Telefono: Mapped[Optional[str]] = mapped_column(String(30), nullable=True)
    Observaciones: Mapped[Optional[str]] = mapped_column(String(8000), nullable=True)
    DependeEconomicamente: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)

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

    Cargo: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    Compania: Mapped[Optional[str]] = mapped_column(String(150), nullable=True)
    TiempoDuracion: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    Funciones: Mapped[Optional[str]] = mapped_column(String(8000), nullable=True)
    JefeInmediato: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    TelefonoJefe: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)
    TieneExperienciaPrevia: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)

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

    DocumentoCargado: Mapped[Optional[bytes]] = mapped_column(LargeBinary, nullable=True)

    FechaCreacion: Mapped[TIMESTAMP] = mapped_column(
        TIMESTAMP(timezone=True), server_default=func.now(), nullable=False
    )
    FechaActualizacion: Mapped[Optional[datetime.datetime]] = mapped_column(
        TIMESTAMP(timezone=True), nullable=True
    )

    Formato: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    Nombre: Mapped[Optional[str]] = mapped_column(String(150), nullable=True)


class TipoDocumentacion(Base):
    __tablename__ = "TipoDocumentacion"

    IdTipoDocumentacion: Mapped[int] = mapped_column(
        Integer, primary_key=True, autoincrement=True
    )
    Descripcion: Mapped[Optional[str]] = mapped_column(String(130), nullable=True)
    Estado: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    IdCategoria: Mapped[int] = mapped_column(Integer, nullable=True)

    FechaCreacion: Mapped[TIMESTAMP] = mapped_column(
        TIMESTAMP(timezone=True), server_default=func.now(), nullable=False
    )
    FechaActualizacion: Mapped[Optional[datetime.datetime]] = mapped_column(
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

    IdTipoReferencia: Mapped[int] = mapped_column(Integer, nullable=True)
    Nombre: Mapped[Optional[str]] = mapped_column(String(150), nullable=True)
    Telefono: Mapped[Optional[str]] = mapped_column(String(30), nullable=True)
    Parentesco: Mapped[Optional[str]] = mapped_column(String(60), nullable=True)
    TiempoConocerlo: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)

    FechaCreacion: Mapped[TIMESTAMP] = mapped_column(
        TIMESTAMP(timezone=True), server_default=func.now(), nullable=False
    )
    FechaActualizacion: Mapped[Optional[datetime.datetime]] = mapped_column(
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

    Direccion: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    IdCiudad: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    IdLocalidad: Mapped[int] = mapped_column(
        ForeignKey("Localidad.IdLocalidad"), nullable=False
    )

    Barrio: Mapped[Optional[str]] = mapped_column(String(150), nullable=True)
    Estrato: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    IdGrupoSanguineo: Mapped[int] = mapped_column(
        ForeignKey("GrupoSanguineo.IdGrupoSanguineo"), nullable=True
    )
    HobbyPasatiempo: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)

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
    CodigoMunicipio: Mapped[Optional[str]] = mapped_column(String(30), nullable=True)
    CodigoDepartamento: Mapped[Optional[str]] = mapped_column(String(30), nullable=True)
    Nombre: Mapped[Optional[str]] = mapped_column(String(150), nullable=True)
    Estado: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)

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


class ObservacionesNucleoFamiliarORM(Base):
    __tablename__ = "ObservacionesNucleoFamiliar"

    IdObservacionesNucleoFamiliar: Mapped[int] = mapped_column(
        Integer, primary_key=True, autoincrement=True
    )
    IdNucleoFamiliar: Mapped[int] = mapped_column(
        ForeignKey("NucleoFamiliar.IdNucleoFamiliar"), nullable=False, unique=True
    )
    Observaciones: Mapped[Optional[str]] = mapped_column(String(8000), nullable=True)
    FechaCreacion: Mapped[TIMESTAMP] = mapped_column(
        TIMESTAMP(timezone=True), server_default=func.now(), nullable=False
    )
    UsuarioActualizacion: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)

    nucleo_familiar = relationship(
        "NucleoFamiliarORM", back_populates="observaciones", lazy="joined"
    )   