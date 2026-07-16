from datetime import date, datetime
from typing import Optional

from pydantic import BaseModel, Field, field_validator


TIPOS_CIERRE_VALIDOS = {
    "CON_MEDIDA_DISCIPLINARIA",
    "SIN_MEDIDA_DISCIPLINARIA",
    "ARCHIVO_DEL_PROCESO",
}


def limpiar_texto_opcional(
    valor: object,
) -> Optional[str]:
    if valor is None:
        return None

    texto = str(valor).strip()

    return texto or None


class CierreProcesoDisciplinarioBase(BaseModel):
    IdProcesoDisciplinario: int

    FechaCierre: Optional[date] = None
    TipoCierre: Optional[str] = None
    MedidaDisciplinaria: Optional[str] = None
    ConclusionRRLL: Optional[str] = None
    ResponsableCierre: Optional[str] = None


class CierreProcesoDisciplinarioCreate(BaseModel):
    IdProcesoDisciplinario: int = Field(
        ...,
        gt=0,
    )

    FechaCierre: Optional[date] = None

    TipoCierre: Optional[str] = Field(
        default=None,
        max_length=150,
    )

    MedidaDisciplinaria: Optional[str] = Field(
        default=None,
        max_length=500,
    )

    ConclusionRRLL: Optional[str] = Field(
        default=None,
        max_length=4000,
    )

    ResponsableCierre: Optional[str] = Field(
        default=None,
        max_length=200,
    )

    @field_validator(
        "TipoCierre",
        mode="before",
    )
    @classmethod
    def normalizar_tipo_cierre(
        cls,
        valor: object,
    ) -> Optional[str]:
        texto = limpiar_texto_opcional(valor)

        if texto is None:
            return None

        codigo = (
            texto.upper()
            .replace(" ", "_")
        )

        equivalencias = {
            "CON_MEDIDA_DISCIPLINARIA":
                "CON_MEDIDA_DISCIPLINARIA",
            "SIN_MEDIDA_DISCIPLINARIA":
                "SIN_MEDIDA_DISCIPLINARIA",
            "ARCHIVO_DEL_PROCESO":
                "ARCHIVO_DEL_PROCESO",
        }

        codigo = equivalencias.get(
            codigo,
            codigo,
        )

        if codigo not in TIPOS_CIERRE_VALIDOS:
            raise ValueError(
                "El tipo de cierre no es válido."
            )

        return codigo

    @field_validator(
        "MedidaDisciplinaria",
        "ConclusionRRLL",
        "ResponsableCierre",
        mode="before",
    )
    @classmethod
    def limpiar_textos(
        cls,
        valor: object,
    ) -> Optional[str]:
        return limpiar_texto_opcional(valor)


class CierreProcesoDisciplinarioUpdate(
    BaseModel
):
    FechaCierre: Optional[date] = None

    TipoCierre: Optional[str] = Field(
        default=None,
        max_length=150,
    )

    MedidaDisciplinaria: Optional[str] = Field(
        default=None,
        max_length=500,
    )

    ConclusionRRLL: Optional[str] = Field(
        default=None,
        max_length=4000,
    )

    ResponsableCierre: Optional[str] = Field(
        default=None,
        max_length=200,
    )

    @field_validator(
        "TipoCierre",
        mode="before",
    )
    @classmethod
    def normalizar_tipo_cierre(
        cls,
        valor: object,
    ) -> Optional[str]:
        return (
            CierreProcesoDisciplinarioCreate
            .normalizar_tipo_cierre(valor)
        )

    @field_validator(
        "MedidaDisciplinaria",
        "ConclusionRRLL",
        "ResponsableCierre",
        mode="before",
    )
    @classmethod
    def limpiar_textos(
        cls,
        valor: object,
    ) -> Optional[str]:
        return limpiar_texto_opcional(valor)


class CierreProcesoDisciplinarioResponse(
    CierreProcesoDisciplinarioBase
):
    IdCierreProcesoDisciplinario: int

    FechaCreacion: Optional[datetime] = None
    FechaActualizacion: Optional[datetime] = None

    class Config:
        from_attributes = True