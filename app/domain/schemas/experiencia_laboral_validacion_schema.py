from datetime import datetime
from typing import Optional
from pydantic import BaseModel, ConfigDict
from datetime import date

class ExperienciaLaboralValidacionSchema(BaseModel):
    """
    Respuesta (output) para ExperienciaLaboralValidacion
    """
    model_config = ConfigDict(from_attributes=True)
    IdExperienciaLaboral: int
    Concepto: Optional[str] = None
    DesempenoReportado: Optional[str] = None
    MotivoRetiroReal: Optional[str] = None
    PersonaQueReferencia: Optional[str] = None
    CreadoEn: Optional[datetime] = None
    ActualizadoEn: Optional[datetime] = None
    Telefono: Optional[str] = None
    ReferenciadoPor: Optional[str] = None
    Eps: Optional[str] = None
    TiempoDuracion: Optional[str] = None
    FechaExpedicionDocumentoIdentidad: Optional[date] = None
    ComentariosDelReferenciado: Optional[str] = None
