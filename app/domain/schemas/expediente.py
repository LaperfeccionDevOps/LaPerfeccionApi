# app/domain/schemas/expediente.py
from datetime import date, datetime
from typing import List, Optional

from pydantic import BaseModel, ConfigDict

# Si ya tienes un AspiranteOut/RegistroPersonalOut, úsalo.
# Aquí te dejo uno base por si no existe:
class RegistroPersonalOut(BaseModel):
    IdRegistroPersonal: int
    IdTipoIdentificacion: int
    NumeroIdentificacion: str
    Nombres: str
    Apellidos: str
    Cargo: Optional[str] = None
    Email: Optional[str] = None
    Celular: Optional[str] = None
    IdEstadoProceso: Optional[int] = None
    FechaCreacion: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


class DatosComplementariosOut(BaseModel):
    IdDatosComplementarios: int
    IdRegistroPersonal: int
    IdNivelEducativo: Optional[int] = None
    Hijos: Optional[bool] = None
    NumeroHijos: Optional[int] = None
    # agrega más campos si necesitas mostrarlos
    model_config = ConfigDict(from_attributes=True)


class NucleoFamiliarOut(BaseModel):
    IdNucleoFamiliar: int
    IdRegistroPersonal: int
    Nombre: str
    Parentesco: str
    Edad: Optional[int] = None
    Ocupacion: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)


class FormacionAcademicaOut(BaseModel):
    IdFormacionAcademica: int
    IdRegistroPersonal: int
    IdTipoFormacionAcademica: int
    Institucion: str
    Estado: bool
    FechaFin: Optional[date] = None

    model_config = ConfigDict(from_attributes=True)


class HistorialLaboralOut(BaseModel):
    IdHistorial: int
    IdRegistroPersonal: int
    Cargo: str
    Area: Optional[str] = None
    FechaIngreso: Optional[date] = None
    FechaRetiro: Optional[date] = None
    Activo: Optional[bool] = None

    model_config = ConfigDict(from_attributes=True)


class ReferenciaOut(BaseModel):
    IdReferencia: int
    IdRegistroPersonal: int
    IdTipoReferencia: int
    Nombre: str
    Telefono: Optional[str] = None
    Parentesco: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)


class DocumentoOut(BaseModel):
    IdDocumento: int
    IdTipoDocumentacion: int
    DescripcionTipo: Optional[str] = None  # viene de TipoDocumentacion
    Estado: Optional[str] = None           # campo Estado de Documentos
    # NO devolvemos el bytea completo si no quieres; puedes añadir una URL si la manejas
    # UrlArchivo: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)


class ExpedienteAspiranteOut(BaseModel):
    aspirante: RegistroPersonalOut
    datos_complementarios: Optional[DatosComplementariosOut] = None
    nucleo_familiar: List[NucleoFamiliarOut] = []
    formacion: List[FormacionAcademicaOut] = []
    experiencia: List[HistorialLaboralOut] = []
    referencias: List[ReferenciaOut] = []
    documentos: List[DocumentoOut] = []