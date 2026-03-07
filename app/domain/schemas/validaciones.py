# app/domain/schemas/validaciones.py
from typing import Optional, Any, Dict, List, Generic, TypeVar
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

T = TypeVar("T")


# =========================
# Respuesta estándar para front
# =========================
class ApiResponse(BaseModel, Generic[T]):
    ok: bool = True
    message: str = "OK"
    data: T


# =========================================================
#   EXPERIENCIA LABORAL (VALIDACIÓN)
# =========================================================
class ValidacionExperienciaLaboralUpsert(BaseModel):
    model_config = ConfigDict(extra="ignore")

    Concepto: Optional[str] = None
    DesempenoReportado: Optional[str] = None
    MotivoRetiroReal: Optional[str] = None
    PersonaQueReferencia: Optional[str] = None
    TelefonoPersonaQueReferencia: Optional[str] = None
    Observaciones: Optional[str] = None
    VerificadoPor: Optional[str] = None

    EstadoValidacion: Optional[str] = "PENDIENTE"  # PENDIENTE | VALIDADO | RECHAZADO
    Extra: Optional[Dict[str, Any]] = None


class ValidacionExperienciaLaboralOut(BaseModel):
    model_config = ConfigDict(from_attributes=True, extra="ignore")

    # Base (ExperienciaLaboral)
    IdExperienciaLaboral: int
    IdRegistroPersonal: int
    Cargo: Optional[str] = None
    Compania: Optional[str] = None
    TiempoDuracion: Optional[str] = None
    Funciones: Optional[str] = None
    JefeInmediato: Optional[str] = None
    TelefonoJefe: Optional[str] = None

    # Validación
    IdValidacionExperienciaLaboral: Optional[int] = None
    Concepto: Optional[str] = None
    DesempenoReportado: Optional[str] = None
    MotivoRetiroReal: Optional[str] = None
    PersonaQueReferencia: Optional[str] = None
    TelefonoPersonaQueReferencia: Optional[str] = None
    Observaciones: Optional[str] = None
    VerificadoPor: Optional[str] = None
    FechaValidacion: Optional[datetime] = None
    FechaActualizacion: Optional[datetime] = None
    EstadoValidacion: Optional[str] = None
    Extra: Optional[Dict[str, Any]] = None


# =========================================================
#   REFERENCIA PERSONAL (VALIDACIÓN)
# =========================================================
class ValidacionReferenciaPersonalUpsert(BaseModel):
    model_config = ConfigDict(extra="ignore")

    ParentescoRelacion: Optional[str] = None
    TiempoConocerAspirante: Optional[str] = None
    HaceCuantoLoConoce: Optional[str] = None
    Descripcion: Optional[str] = None
    LugarVivienda: Optional[str] = None
    TieneHijos: Optional[bool] = None

    Observaciones: Optional[str] = None
    VerificadoPor: Optional[str] = None

    EstadoValidacion: Optional[str] = "PENDIENTE"
    Extra: Optional[Dict[str, Any]] = None


class ValidacionReferenciaPersonalOut(BaseModel):
    model_config = ConfigDict(from_attributes=True, extra="ignore")

    # Base (Referencia)
    IdReferencia: int
    IdRegistroPersonal: int
    Nombre: Optional[str] = None
    Telefono: Optional[str] = None
    Ocupacion: Optional[str] = None

    # Validación
    IdValidacionReferenciaPersonal: Optional[int] = None
    ParentescoRelacion: Optional[str] = None
    TiempoConocerAspirante: Optional[str] = None
    HaceCuantoLoConoce: Optional[str] = None
    Descripcion: Optional[str] = None
    LugarVivienda: Optional[str] = None
    TieneHijos: Optional[bool] = None

    Observaciones: Optional[str] = None
    VerificadoPor: Optional[str] = None
    FechaValidacion: Optional[datetime] = None
    FechaActualizacion: Optional[datetime] = None
    EstadoValidacion: Optional[str] = None
    Extra: Optional[Dict[str, Any]] = None


# =========================================================
#   ENDPOINT "GRANDE" SOLO PARA VALIDACIONES (útil para front)
# =========================================================
class ValidacionesAspiranteOut(BaseModel):
    model_config = ConfigDict(extra="ignore")

    IdRegistroPersonal: int
    ExperienciaLaboral: List[ValidacionExperienciaLaboralOut] = []
    ReferenciasPersonales: List[ValidacionReferenciaPersonalOut] = []
