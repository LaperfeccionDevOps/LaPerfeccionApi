# app/domain/schemas/aspirante.py

from typing import Optional, List, TYPE_CHECKING
from datetime import date, datetime

from pydantic import BaseModel, EmailStr


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
    EstadoProceso: Optional[str] = None
    FechaExpedicion: Optional[date] = None
    LugarExpedicion: Optional[str] = None
    Direccion: Optional[str] = None
    Ciudad: Optional[str] = None
    Barrio: Optional[str] = None
    NombreCargo: Optional[str] = None
    Salario: Optional[float] = None
    FechaIngreso: Optional[datetime] = None
    NombreCliente: Optional[str] = None
    FechaNacimiento: Optional[date] = None

    class Config:
        orm_mode = True


class NucleoFamiliarSchema(BaseModel):
    TieneparentescoEnLaEmpresa: Optional[bool] = None
    NombreFamiliarEmpresa: Optional[str] = None
    CargoDesempenaEmpresa: Optional[str] = None
    CedulaFamiliarEmpresa: Optional[str] = None
    ParentescoFamiliarEmpresa: Optional[str] = None
    Nombre: str
    Parentesco: str
    Edad: int
    Ocupacion: Optional[str] = None
    Telefono: Optional[str] = None
    DependeEconomicamente: Optional[bool] = None
    Observaciones: Optional[str] = None

    class Config:
        orm_mode = True

class ObservacionNucleoFamiliarSchema(BaseModel):
    IdNucleoFamiliar: int
    Observaciones: Optional[str] = None
    FechaCreacion: Optional[datetime] = None
    UsuarioActualizacion: Optional[str] = None

    class Config:
        orm_mode = True

class Referenciachema(BaseModel):
    IdTipoReferencia: int
    Nombre: str
    Telefono: Optional[str] = None
    Parentesco: Optional[str] = None
    TiempoConocerlo: Optional[str] = None

    class Config:
        orm_mode = True


class ExperienciaLaboralSchema(BaseModel):
    Cargo: str
    Compania: str
    TiempoDuracion: str
    Funciones: str
    JefeInmediato: str
    TelefonoJefe: str
    TieneExperienciaPrevia: Optional[bool] = None

    class Config:
        orm_mode = True
        
class ExperienciaLaboralCreateSeleccionSchema(BaseModel):
    IdRegistroPersonal: int
    Cargo: Optional[str] = None
    Compania: Optional[str] = None
    TiempoDuracion: Optional[str] = None
    Funciones: Optional[str] = None
    JefeInmediato: Optional[str] = None
    TelefonoJefe: Optional[str] = None
    TieneExperienciaPrevia: Optional[bool] = True

    class Config:
        orm_mode = True


class DocumentacionSchema(BaseModel):
    IdTipoDocumentacion: int
    Nombre: str
    DocumentoCargado: Optional[bytes] = None
    Formato: Optional[str] = None

    class Config:
        from_attributes = True


if TYPE_CHECKING:
    from .combos_schema import ComboSchema  # ejemplo de import para modelos relacionados


class TipoIdentificacionSchema(BaseModel):
    IdTipoIdentificacion: int
    Descripcion: Optional[str] = None

    class Config:
        orm_mode = True


class TipoCargoSchema(BaseModel):
    IdTipoCargo: int
    Descripcion: Optional[str] = None

    class Config:
        orm_mode = True


class TipoEpsSchema(BaseModel):
    IdTipoEps: int
    Descripcion: Optional[str] = None

    class Config:
        orm_mode = True


class TipoEstadoCivilSchema(BaseModel):
    IdTipoEstadoCivil: int
    Descripcion: Optional[str] = None

    class Config:
        orm_mode = True


class TipoGeneroSchema(BaseModel):
    IdTipoGenero: int
    Descripcion: Optional[str] = None

    class Config:
        orm_mode = True


class EstadoProcesoSchema(BaseModel):
    IdEstadoProceso: int
    Nombre: Optional[str] = None

    class Config:
        orm_mode = True


# ✅ CORREGIDO: el ID debe coincidir con tu modelo/tabla (IdFondoPensiones)
class FondoPensionesSchema(BaseModel):
    IdFondoPensiones: int
    Nombre: Optional[str] = None

    class Config:
        orm_mode = True


# ✅ NUEVO: Fondo de Cesantías
class FondoCesantiasSchema(BaseModel):
    IdFondoCesantias: int
    Nombre: Optional[str] = None

    class Config:
        orm_mode = True


class FormacionAcademicaSchema(BaseModel):
    IdFormacionAcademica: int
    Nombre: Optional[str] = None

    class Config:
        orm_mode = True


class LimitacionFisicaHijoSchema(BaseModel):
    IdLimitacionFisicaHijo: int
    Nombre: Optional[str] = None

    class Config:
        orm_mode = True


class NivelEducativoSchema(BaseModel):
    IdNivelEducativo: int
    Descripcion: Optional[str] = None

    class Config:
        orm_mode = True


class LugarNacimientoSchema(BaseModel):
    IdLugarNacimiento: int
    CodigoMunicipio: Optional[str]
    CodigoDepartamento: Optional[str]
    Nombre: Optional[str]
    Estado: bool = True
    FechaCreacion: Optional[datetime] = None

    class Config:
        orm_mode = True


class RegistroPersonalRead(BaseModel):
    IdRegistroPersonal: int

    IdTipoIdentificacion: int
    IdCargo: str  # TEXTO, porque así está en la BD ahora

    IdEps: Optional[int] = None
    IdEstadoCivil: Optional[int] = None
    IdTipoGenero: Optional[int] = None
    IdEstadoProceso: Optional[int] = None

    # ✅ Pensiones + ✅ Cesantías
    IdFondoPensiones: Optional[int] = None
    IdFondoCesantias: Optional[int] = None

    IdFormacionAcademica: Optional[int] = None
    IdLimitacionFisica: Optional[int] = None
    IdNivelEducativo: Optional[int] = None

    NumeroIdentificacion: str
    FechaExpedicion: Optional[date] = None
    LugarExpedicion: Optional[str] = None

    Nombres: str
    Apellidos: str
    Cargo: Optional[str] = None
    Email: Optional[EmailStr] = None
    Celular: Optional[str] = None
    TieneWhatsapp: bool
    NumeroWhatsapp: Optional[str] = None

    PesoKilogramos: Optional[float] = None
    AlturaMetros: Optional[float] = None

    ContactoEmergencia: Optional[str] = None
    TelefonoContactoEmergencia: Optional[str] = None
    ComoSeEnteroVacante: Optional[str] = None
    IdLugarNacimiento: Optional[int] = None
    TieneLimitacionesFisicas: Optional[str] = None
    IdDatosAdicionales: Optional[int] = None
    DescripcionFormacionAcademica: Optional[str] = None

    # En la BD son TIMESTAMP, por eso aquí usamos datetime
    FechaCreacion: Optional[datetime] = None
    FechaActualizacion: Optional[datetime] = None
    UsuarioActualizacion: Optional[str] = None

    # Relaciones anidadas
    tipo_identificacion: Optional[TipoIdentificacionSchema] = None
    tipo_cargo: Optional[TipoCargoSchema] = None
    tipo_eps: Optional[TipoEpsSchema] = None
    tipo_estado_civil: Optional[TipoEstadoCivilSchema] = None
    tipo_genero: Optional[TipoGeneroSchema] = None
    estado_proceso: Optional[EstadoProcesoSchema] = None

    fondo_pensiones: Optional[FondoPensionesSchema] = None
    fondo_cesantias: Optional[FondoCesantiasSchema] = None

    formacion_academica: Optional[FormacionAcademicaSchema] = None
    limitacion_fisica_hijo: Optional[LimitacionFisicaHijoSchema] = None
    nivel_educativo: Optional[NivelEducativoSchema] = None
    lugar_nacimiento: Optional[LugarNacimientoSchema] = None

    experiencia_laboral_validacion: Optional[list] = None
    referencias_personales_validacion: Optional[list] = None
    datos_seleccion: Optional[list] = None
    observaciones_nucleo_familiar: Optional[ObservacionNucleoFamiliarSchema] = None

    class Config:
        orm_mode = True


class DatosAdicionalesCreate(BaseModel):
    Direccion: Optional[str] = None
    IdCiudad: Optional[int] = None
    IdLocalidad: Optional[int] = None
    Barrio: Optional[str] = None
    Estrato: Optional[int] = None
    IdGrupoSanguineo: int
    HobbyPasatiempo: Optional[str] = None

    class Config:
        from_attributes = True


class AspiranteBase(BaseModel):
    nombre: str
    correo: EmailStr


class RegistroPersonalCreate(BaseModel):
    """
    Datos que el frontend debe enviar para crear un registro personal.
    OJO: aquí usamos los mismos nombres que en la BD (IdTipo..., etc.)
    """

    IdTipoIdentificacion: int
    IdTipoCargo: int
    IdTipoEps: int
    IdTipoEstadoCivil: int
    IdTipoGenero: int
    IdEstadoProceso: int

    NumeroIdentificacion: str
    FechaExpedicion: Optional[date] = None
    FechaNacimiento: Optional[date] = None
    LugarExpedicion: Optional[str] = None

    Nombres: str
    Apellidos: str
    Email: Optional[EmailStr] = None
    Celular: Optional[str] = None
    TieneWhatsapp: bool = False
    NumeroWhatsapp: Optional[str] = None

    PesoKilogramos: Optional[float] = None
    AlturaMetros: Optional[float] = None

    ContactoEmergencia: Optional[str] = None
    TelefonoContactoEmergencia: Optional[str] = None

    IdTipoEstadoFormacion: int
    EstudiaActualmente: Optional[str] = None

    # ✅ Pensiones (como lo tenías)
    IdFondoPensiones: int

    # ✅ NUEVO: Cesantías (lo dejamos opcional por si no es obligatorio)
    IdFondoCesantias: Optional[int] = None

    IdLimitacionFisicaHijo: Optional[int] = None
    IdNivelEducativo: int

    TieneHijos: Optional[bool] = None
    CuantosHijos: Optional[int] = None

    UsuarioActualizacion: Optional[str] = None
    ComoSeEnteroVacante: Optional[str] = None
    IdLugarNacimiento: Optional[int] = None

    DescripcionFormacionAcademica: Optional[str] = None
    FechaActualizacion: Optional[date] = None
    TieneLimitacionesFisicas: Optional[str] = None

    NucleoFamiliar: List[NucleoFamiliarSchema] = []
    Referencias: List[Referenciachema] = []
    ExperienciaLaboral: List[ExperienciaLaboralSchema] = []
    Documentacion: List[DocumentacionSchema] = []
    DatosAdicionales: Optional[DatosAdicionalesCreate] = None

    class Config:
        from_attributes = True


class CambioEstadoRequest(BaseModel):
    """
    Payload para cambiar el estado de un aspirante desde Selección.
    """
    id_estado: int
    motivo: Optional[str] = None
    observaciones: Optional[str] = None
    usuario: str


class RegistrarDocumentosSeguridadSchema(BaseModel):
    idRegistroPersonal: int
    documentos_seguridad: List[DocumentacionSchema]

    class Config:
        from_attributes = True

class RegistrarDocumentosContratacionSchema(BaseModel):
    idRegistroPersonal: int
    documentos_contratacion: List[DocumentacionSchema]

    class Config:
        from_attributes = True