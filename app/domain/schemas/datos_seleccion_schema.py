from datetime import date, datetime
from typing import Optional, Any
from pydantic import BaseModel, Field, field_validator


def _parse_bool(v: Any) -> Optional[bool]:
    if v is None:
        return None
    if isinstance(v, bool):
        return v
    if isinstance(v, (int, float)):
        return bool(v)
    if isinstance(v, str):
        s = v.strip().lower()
        if s in ("si", "sí", "s", "true", "1", "yes", "y"):
            return True
        if s in ("no", "false", "0", "n"):
            return False
    return None


class DatosSeleccionUpsertRequest(BaseModel):
    IdRegistroPersonal: int
    FechaProceso: date
    TipoCargo: str = Field(min_length=1, max_length=150)

    # ✅ Aceptamos ambos nombres (uno u otro)
    HaTrabajadoAntesEnLaEmpresa: Optional[bool] = None
    HaTrabajadoAntes: Optional[bool] = None

    Arl: Optional[str] = Field(default=None, max_length=130)
    AntecedentesMedicos: Optional[str] = None
    Medicamentos: Optional[str] = None

    UsuarioActualizacion: str = Field(min_length=1, max_length=120)

    # ✅ Validadores para aceptar SI/NO, true/false, 1/0 sin romper el esquema
    @field_validator("HaTrabajadoAntesEnLaEmpresa", mode="before")
    @classmethod
    def _val_ha_trabajado_empresa(cls, v):
        parsed = _parse_bool(v)
        return v if parsed is None else parsed

    @field_validator("HaTrabajadoAntes", mode="before")
    @classmethod
    def _val_ha_trabajado_alias(cls, v):
        parsed = _parse_bool(v)
        return v if parsed is None else parsed


class DatosSeleccionResponse(BaseModel):
    IdDatosSeleccion: int
    IdRegistroPersonal: int
    FechaProceso: date
    TipoCargo: str
    HaTrabajadoAntesEnLaEmpresa: bool

    Arl: Optional[str] = None
    AntecedentesMedicos: Optional[str] = None
    Medicamentos: Optional[str] = None

    FechaActualizacion: datetime
    UsuarioActualizacion: str

    class Config:
        from_attributes = True
