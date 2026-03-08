from typing import Optional
from pydantic import BaseModel

class TrabajadorBusquedaOut(BaseModel):
    IdRegistroPersonal: int
    TipoDocumento: str
    NumeroDocumento: str
    Nombres: Optional[str] = None
    Apellidos: Optional[str] = None
    NombreCompleto: Optional[str] = None
    Correo: Optional[str] = None
    Telefono: Optional[str] = None
    Direccion: Optional[str] = None
    Barrio: Optional[str] = None
    Cargo: Optional[str] = None