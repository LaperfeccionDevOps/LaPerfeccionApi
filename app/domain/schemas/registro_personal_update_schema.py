from pydantic import BaseModel, Field
from typing import Optional
from datetime import date


class RegistroPersonalUpdateRequest(BaseModel):
    IdTipoIdentificacion: Optional[int]
    NumeroIdentificacion: Optional[str] = Field(None, max_length=50)
    FechaExpedicion: Optional[date]
    LugarExpedicion: Optional[str] = Field(None, max_length=100)
    Nombres: Optional[str] = Field(None, max_length=100)
    Apellidos: Optional[str] = Field(None, max_length=100)
    FechaNacimiento: Optional[date]
    IdLugarNacimiento: Optional[int]
    Email: Optional[str] = Field(None, max_length=100)
    Celular: Optional[str] = Field(None, max_length=20)
    DireccionDatosAdicionales: Optional[str] = Field(None, max_length=500, description="Dirección en DatosAdicionales")
    IdGrupoSanguineo: Optional[int]
    AlturaMetros: Optional[float]
    PesoKilogramos: Optional[float]
    IdTipoEps: Optional[int]
    IdFondoPensiones: Optional[int]

