from datetime import date, datetime
from typing import Optional

from pydantic import BaseModel, Field, field_validator


def limpiar_texto_obligatorio(
    valor: object,
    nombre_campo: str,
) -> str:
    """
    Limpia y valida los campos de texto obligatorios.

    Reglas:
    - No permite valores nulos.
    - No permite textos vacíos.
    - No permite guardar únicamente espacios.
    - Elimina espacios al inicio y al final.
    """
    if valor is None:
        raise ValueError(
            f"El campo {nombre_campo} es obligatorio."
        )

    texto_limpio = str(valor).strip()

    if not texto_limpio:
        raise ValueError(
            f"El campo {nombre_campo} no puede estar vacío."
        )

    return texto_limpio


class CierreProcesoDisciplinarioBase(BaseModel):
    """
    Base utilizada principalmente para las respuestas.

    Los campos permanecen opcionales aquí para conservar
    compatibilidad con registros históricos que puedan
    contener información incompleta.
    """

    IdProcesoDisciplinario: int
    FechaCierre: Optional[date] = None

    TipoCierre: Optional[str] = None
    MedidaDisciplinaria: Optional[str] = None
    ConclusionRRLL: Optional[str] = None
    ResponsableCierre: Optional[str] = None


class CierreProcesoDisciplinarioCreate(BaseModel):
    """
    Datos obligatorios para registrar un nuevo cierre.
    """

    IdProcesoDisciplinario: int = Field(
        ...,
        gt=0,
        description=(
            "Identificador del proceso disciplinario."
        ),
    )

    FechaCierre: Optional[date] = None

    TipoCierre: str = Field(
        ...,
        min_length=3,
        max_length=150,
        description=(
            "Descripción libre del tipo de cierre."
        ),
    )

    MedidaDisciplinaria: str = Field(
        ...,
        min_length=3,
        max_length=500,
        description=(
            "Descripción libre de la medida disciplinaria."
        ),
    )

    ConclusionRRLL: str = Field(
        ...,
        min_length=3,
        max_length=4000,
        description=(
            "Conclusión final registrada por Relaciones Laborales."
        ),
    )

    ResponsableCierre: str = Field(
        ...,
        min_length=3,
        max_length=150,
        description=(
            "Nombre o usuario responsable del cierre."
        ),
    )

    @field_validator(
        "TipoCierre",
        "MedidaDisciplinaria",
        "ConclusionRRLL",
        "ResponsableCierre",
        mode="before",
    )
    @classmethod
    def validar_textos_obligatorios(
        cls,
        valor: object,
        info,
    ) -> str:
        nombres_campos = {
            "TipoCierre": "Tipo de cierre",
            "MedidaDisciplinaria": (
                "Medida disciplinaria"
            ),
            "ConclusionRRLL": (
                "Conclusión de Relaciones Laborales"
            ),
            "ResponsableCierre": (
                "Responsable del cierre"
            ),
        }

        return limpiar_texto_obligatorio(
            valor=valor,
            nombre_campo=nombres_campos.get(
                info.field_name,
                info.field_name,
            ),
        )


class CierreProcesoDisciplinarioUpdate(BaseModel):
    """
    Permite actualizaciones parciales.

    Los campos pueden omitirse, pero si son enviados
    deben contener información válida.
    """

    FechaCierre: Optional[date] = None

    TipoCierre: Optional[str] = Field(
        default=None,
        min_length=3,
        max_length=150,
    )

    MedidaDisciplinaria: Optional[str] = Field(
        default=None,
        min_length=3,
        max_length=500,
    )

    ConclusionRRLL: Optional[str] = Field(
        default=None,
        min_length=3,
        max_length=4000,
    )

    ResponsableCierre: Optional[str] = Field(
        default=None,
        min_length=3,
        max_length=150,
    )

    @field_validator(
        "TipoCierre",
        "MedidaDisciplinaria",
        "ConclusionRRLL",
        "ResponsableCierre",
        mode="before",
    )
    @classmethod
    def validar_textos_actualizados(
        cls,
        valor: object,
        info,
    ) -> str:
        nombres_campos = {
            "TipoCierre": "Tipo de cierre",
            "MedidaDisciplinaria": (
                "Medida disciplinaria"
            ),
            "ConclusionRRLL": (
                "Conclusión de Relaciones Laborales"
            ),
            "ResponsableCierre": (
                "Responsable del cierre"
            ),
        }

        return limpiar_texto_obligatorio(
            valor=valor,
            nombre_campo=nombres_campos.get(
                info.field_name,
                info.field_name,
            ),
        )


class CierreProcesoDisciplinarioResponse(
    CierreProcesoDisciplinarioBase
):
    IdCierreProcesoDisciplinario: int
    FechaCreacion: Optional[datetime] = None
    FechaActualizacion: Optional[datetime] = None

    class Config:
        from_attributes = True