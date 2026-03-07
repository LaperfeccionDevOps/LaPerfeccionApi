from pydantic import BaseModel
from typing import Optional
from datetime import date
import datetime

class TipoIdentificacionResponse(BaseModel):
    IdTipoIdentificacion: int
    Descripcion: str

    class Config:
        orm_mode = True


class TipoCargo(BaseModel):
    IdTipoCargo: int
    Codigo: str
    Descripcion: str
    Estado: bool
    FechaCreacion: Optional[date]
    FechaActualizacion: Optional[date]

    class Config:
        orm_mode = True

class TipoEps(BaseModel):
    IdTipoEps: int
    Descripcion: str
    Estado: bool
    FechaCreacion: Optional[date]
    FechaActualizacion: Optional[date]

    class Config:
        orm_mode = True


class TipoEstadoCivil(BaseModel):
    IdTipoEstadoCivil: int
    Descripcion: str
    Estado: bool
    FechaCreacion: Optional[date]
    FechaActualizacion: Optional[date]

    class Config:
        orm_mode = True

class TipoFormacionAcademica(BaseModel):
    IdTipoFormacionAcademica: int
    Descripcion: str
    Estado: bool
    FechaCreacion: Optional[date]
    FechaActualizacion: Optional[date]

    class Config:
        orm_mode = True

class TipoGenero(BaseModel):
    IdTipoGenero: int
    Descripcion: str
    Estado: bool
    FechaCreacion: Optional[date]
    FechaActualizacion: Optional[date]

    class Config:
        orm_mode = True


class TipoPrueba(BaseModel):
    IdTipoPrueba: int
    Descripcion: str
    Estado: bool
    FechaCreacion: Optional[date]
    FechaActualizacion: Optional[date]

    class Config:
        orm_mode = True

class TipoReferencia(BaseModel):
    IdTipoReferencia: int
    Descripcion: str
    Estado: bool
    FechaCreacion: Optional[date]

    class Config:
        orm_mode = True 

class Localidades(BaseModel):
    IdLocalidad: Optional[int] = None
    Nombre: Optional[str] = None
    CodigoMunicipio: Optional[str] = None
    CodigoDepartamento: Optional[str] = None
    Estado: Optional[bool] = None
    FechaCreacion: Optional[datetime.datetime] = None
    FechaActualizacion: Optional[datetime.datetime] = None

    class Config:
        orm_mode = True

class LugarNacimiento(BaseModel):
    IdLugarNacimiento: Optional[int] = None
    Nombre: Optional[str] = None
    CodigoMunicipio: Optional[str] = None
    CodigoDepartamento: Optional[str] = None
    Estado: Optional[bool] = None
    FechaCreacion: Optional[datetime.datetime] = None
    FechaActualizacion: Optional[datetime.datetime] = None

    class Config:
        orm_mode = True

class Cargo(BaseModel):
    IdCargo: Optional[int] = None
    NombreCargo: Optional[str] = None
    IdTipoCargo: Optional[int] = None
    Activo: Optional[bool] = None
    FechaCreacion: Optional[datetime.datetime] = None
    FechaActualizacion: Optional[datetime.datetime] = None
    UsuarioActualizacion: Optional[str] = None

    class Config:
        orm_mode = True