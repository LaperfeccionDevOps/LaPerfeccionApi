# app/domain/schemas/aspirante.py

from datetime import date, datetime
from typing import TYPE_CHECKING

from pydantic import BaseModel, EmailStr


class RegistroPersonalOut(BaseModel):
    IdRegistroPersonal: int
    IdTipoIdentificacion: int
    NumeroIdentificacion: str
    Nombres: str
    Apellidos: str
    Cargo: str | None = None
    Email: str | None = None
    Celular: str | None = None
    IdEstadoProceso: int | None = None
    FechaCreacion: datetime | None = None
    EstadoProceso: str | None = None
    FechaExpedicion: date | None = None
    LugarExpedicion: str | None = None
    Direccion: str | None = None
    Ciudad: str | None = None
    Barrio: str | None = None
    NombreCargo: str | None = None
    Salario: float | None = None
    FechaIngreso: datetime | None = None
    NombreCliente: str | None = None
    FechaNacimiento: date | None = None

    class Config:
        orm_mode = True


class NucleoFamiliarSchema(BaseModel):
    TieneparentescoEnLaEmpresa: bool | None = None
    NombreFamiliarEmpresa: str | None = None
    CargoDesempenaEmpresa: str | None = None
    CedulaFamiliarEmpresa: str | None = None
    ParentescoFamiliarEmpresa: str | None = None
    Nombre: str
    Parentesco: str
    Edad: int
    Ocupacion: str | None = None
    Telefono: str | None = None
    DependeEconomicamente: bool | None = None
    Observaciones: str | None = None

    class Config:
        orm_mode = True

class ObservacionNucleoFamiliarSchema(BaseModel):
    IdNucleoFamiliar: int
    Observaciones: str | None = None
    FechaCreacion: datetime | None = None
    UsuarioActualizacion: str | None = None

    class Config:
        orm_mode = True

class Referenciachema(BaseModel):
    IdTipoReferencia: int
    Nombre: str
    Telefono: str | None = None
    Parentesco: str | None = None
    TiempoConocerlo: str | None = None

    class Config:
        orm_mode = True


class ExperienciaLaboralSchema(BaseModel):
    Cargo: str
    Compania: str
    TiempoDuracion: str
    Funciones: str
    JefeInmediato: str
    TelefonoJefe: str
    TieneExperienciaPrevia: bool | None = None

    class Config:
        orm_mode = True
        
class ExperienciaLaboralCreateSeleccionSchema(BaseModel):
    IdRegistroPersonal: int
    Cargo: str | None = None
    Compania: str | None = None
    TiempoDuracion: str | None = None
    Funciones: str | None = None
    JefeInmediato: str | None = None
    TelefonoJefe: str | None = None
    TieneExperienciaPrevia: bool | None = True

    class Config:
        orm_mode = True


class DocumentacionSchema(BaseModel):
    IdTipoDocumentacion: int
    Nombre: str
    DocumentoCargado: bytes | None = None
    Formato: str | None = None

    class Config:
        from_attributes = True


if TYPE_CHECKING:
    from .combos_schema import ComboSchema  # ejemplo de import para modelos relacionados


class TipoIdentificacionSchema(BaseModel):
    IdTipoIdentificacion: int
    Descripcion: str | None = None

    class Config:
        orm_mode = True


class TipoCargoSchema(BaseModel):
    IdTipoCargo: int
    Descripcion: str | None = None

    class Config:
        orm_mode = True


class TipoEpsSchema(BaseModel):
    IdTipoEps: int
    Descripcion: str | None = None

    class Config:
        orm_mode = True


class TipoEstadoCivilSchema(BaseModel):
    IdTipoEstadoCivil: int
    Descripcion: str | None = None

    class Config:
        orm_mode = True


class TipoGeneroSchema(BaseModel):
    IdTipoGenero: int
    Descripcion: str | None = None

    class Config:
        orm_mode = True


class EstadoProcesoSchema(BaseModel):
    IdEstadoProceso: int
    Nombre: str | None = None

    class Config:
        orm_mode = True


# ✅ CORREGIDO: el ID debe coincidir con tu modelo/tabla (IdFondoPensiones)
class FondoPensionesSchema(BaseModel):
    IdFondoPensiones: int
    Nombre: str | None = None

    class Config:
        orm_mode = True


# ✅ NUEVO: Fondo de Cesantías
class FondoCesantiasSchema(BaseModel):
    IdFondoCesantias: int
    Nombre: str | None = None

    class Config:
        orm_mode = True


class FormacionAcademicaSchema(BaseModel):
    IdFormacionAcademica: int
    Nombre: str | None = None

    class Config:
        orm_mode = True


class LimitacionFisicaHijoSchema(BaseModel):
    IdLimitacionFisicaHijo: int
    Nombre: str | None = None

    class Config:
        orm_mode = True


class NivelEducativoSchema(BaseModel):
    IdNivelEducativo: int
    Descripcion: str | None = None

    class Config:
        orm_mode = True


class LugarNacimientoSchema(BaseModel):
    IdLugarNacimiento: int
    CodigoMunicipio: str | None
    CodigoDepartamento: str | None
    Nombre: str | None
    Estado: bool = True
    FechaCreacion: datetime | None = None

    class Config:
        orm_mode = True


class RegistroPersonalRead(BaseModel):
    IdRegistroPersonal: int

    IdTipoIdentificacion: int
    IdCargo: str  # TEXTO, porque así está en la BD ahora

    IdEps: int | None = None
    IdEstadoCivil: int | None = None
    IdTipoGenero: int | None = None
    IdEstadoProceso: int | None = None

    # ✅ Pensiones + ✅ Cesantías
    IdFondoPensiones: int | None = None
    IdFondoCesantias: int | None = None

    IdFormacionAcademica: int | None = None
    IdLimitacionFisica: int | None = None
    IdNivelEducativo: int | None = None

    NumeroIdentificacion: str
    FechaExpedicion: date | None = None
    LugarExpedicion: str | None = None

    Nombres: str
    Apellidos: str
    Cargo: str | None = None
    Email: EmailStr | None = None
    Celular: str | None = None
    TieneWhatsapp: bool
    NumeroWhatsapp: str | None = None

    PesoKilogramos: float | None = None
    AlturaMetros: float | None = None

    ContactoEmergencia: str | None = None
    TelefonoContactoEmergencia: str | None = None
    ComoSeEnteroVacante: str | None = None
    IdLugarNacimiento: int | None = None
    TieneLimitacionesFisicas: str | None = None
    IdDatosAdicionales: int | None = None
    DescripcionFormacionAcademica: str | None = None

    # En la BD son TIMESTAMP, por eso aquí usamos datetime
    FechaCreacion: datetime | None = None
    FechaActualizacion: datetime | None = None
    UsuarioActualizacion: str | None = None

    # Relaciones anidadas
    tipo_identificacion: TipoIdentificacionSchema | None = None
    tipo_cargo: TipoCargoSchema | None = None
    tipo_eps: TipoEpsSchema | None = None
    tipo_estado_civil: TipoEstadoCivilSchema | None = None
    tipo_genero: TipoGeneroSchema | None = None
    estado_proceso: EstadoProcesoSchema | None = None

    fondo_pensiones: FondoPensionesSchema | None = None
    fondo_cesantias: FondoCesantiasSchema | None = None

    formacion_academica: FormacionAcademicaSchema | None = None
    limitacion_fisica_hijo: LimitacionFisicaHijoSchema | None = None
    nivel_educativo: NivelEducativoSchema | None = None
    lugar_nacimiento: LugarNacimientoSchema | None = None

    experiencia_laboral_validacion: list | None = None
    referencias_personales_validacion: list | None = None
    datos_seleccion: list | None = None
    observaciones_nucleo_familiar: ObservacionNucleoFamiliarSchema | None = None

    class Config:
        orm_mode = True


class DatosAdicionalesCreate(BaseModel):
    Direccion: str | None = None
    IdCiudad: int | None = None
    IdLocalidad: int | None = None
    Barrio: str | None = None
    Estrato: int | None = None
    IdGrupoSanguineo: int
    HobbyPasatiempo: str | None = None

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
    FechaExpedicion: date | None = None
    FechaNacimiento: date | None = None
    LugarExpedicion: str | None = None

    Nombres: str
    Apellidos: str
    Email: EmailStr | None = None
    Celular: str | None = None
    TieneWhatsapp: bool = False
    NumeroWhatsapp: str | None = None

    PesoKilogramos: float | None = None
    AlturaMetros: float | None = None

    ContactoEmergencia: str | None = None
    TelefonoContactoEmergencia: str | None = None

    IdTipoEstadoFormacion: int
    EstudiaActualmente: str | None = None

    # ✅ Pensiones (como lo tenías)
    IdFondoPensiones: int

    # ✅ NUEVO: Cesantías (lo dejamos opcional por si no es obligatorio)
    IdFondoCesantias: int | None = None

    IdLimitacionFisicaHijo: int | None = None
    IdNivelEducativo: int

    TieneHijos: bool | None = None
    CuantosHijos: int | None = None

    UsuarioActualizacion: str | None = None
    ComoSeEnteroVacante: str | None = None
    IdLugarNacimiento: int | None = None

    DescripcionFormacionAcademica: str | None = None
    FechaActualizacion: date | None = None
    TieneLimitacionesFisicas: str | None = None

    NucleoFamiliar: list[NucleoFamiliarSchema] = []
    Referencias: list[Referenciachema] = []
    ExperienciaLaboral: list[ExperienciaLaboralSchema] = []
    Documentacion: list[DocumentacionSchema] = []
    DatosAdicionales: DatosAdicionalesCreate | None = None

    class Config:
        from_attributes = True


class CambioEstadoRequest(BaseModel):
    """
    Payload para cambiar el estado de un aspirante desde Selección.
    """
    id_estado: int
    motivo: str | None = None
    observaciones: str | None = None
    usuario: str


class RegistrarDocumentosSeguridadSchema(BaseModel):
    idRegistroPersonal: int

    # Vinculación laboral actual del proceso.
    # Se deja opcional para mantener compatibilidad con flujos existentes
    # que todavía no envían este dato.
    idVinculacionLaboral: int | None = None

    documentos_seguridad: list[DocumentacionSchema]

    class Config:
        from_attributes = True

class RegistrarDocumentosContratacionSchema(BaseModel):
    idRegistroPersonal: int
    documentos_contratacion: list[DocumentacionSchema]

    class Config:
        from_attributes = True