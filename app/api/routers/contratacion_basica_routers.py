# app/api/routers/contratacion_basica_routers.py

import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from infrastructure.db.deps import get_db
from services.contratacion_basica_service import ContratacionBasicaService


router = APIRouter(
    prefix="/api/contratacion-basica",
    tags=["contratacion-basica"],
)

service = ContratacionBasicaService()


# ---------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------
class ContratacionBasicaIn(BaseModel):
    IdRegistroPersonal: int

    # Se deja opcional para mantener compatibilidad con procesos
    # anteriores que todavía no trabajan por ciclo laboral.
    IdVinculacionLaboral: int | None = None

    IdBanco: int | None = None
    IdTipoContrato: int | None = None
    FechaIngreso: datetime.date | None = None
    RiesgoLaboral: str | None = None

    Posicion: str | None = Field(
        default=None,
        max_length=100,
    )

    Escalafon: str | None = Field(
        default=None,
        max_length=4,
        pattern=r"^(200|210|220)$",
    )

    NumeroCuenta: str | None = Field(
        default=None,
        max_length=40,
    )

    TetanosDosis: int | None = Field(
        default=None,
        ge=1,
        le=5,
    )
    TetanosFechaUltimaDosis: datetime.date | None = None
    TetanosDescontable: bool | None = None

    HepatitisDosis: int | None = Field(
        default=None,
        ge=1,
        le=4,
    )
    HepatitisFechaUltimaDosis: datetime.date | None = None
    HepatitisDescontable: bool | None = None


class ContratacionBasicaOut(ContratacionBasicaIn):
    IdContratacionBasica: int
    FechaCreacion: datetime.datetime
    FechaActualizacion: datetime.datetime


# ---------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------
@router.get(
    "/registro-personal/{id_registro_personal}",
    response_model=ContratacionBasicaOut | None,
)
def obtener_por_registro_personal(
    id_registro_personal: int,
    db: Session = Depends(get_db),
):
    return service.obtener(
        db,
        id_registro_personal,
    )


@router.post(
    "",
    response_model=ContratacionBasicaOut,
)
def upsert(
    payload: ContratacionBasicaIn,
    db: Session = Depends(get_db),
):
    try:
        result = service.guardar(
            db,
            payload.model_dump(),
        )

        if result is None:
            raise HTTPException(
                status_code=500,
                detail=(
                    "ContratacionBasicaService.guardar() retornó None. "
                    "Revisa create/update/returning y verifica que "
                    "el servicio esté retornando un dict."
                ),
            )

        if not isinstance(result, dict):
            raise HTTPException(
                status_code=500,
                detail=(
                    "Respuesta inesperada del servicio: "
                    f"{type(result)}. Se esperaba dict."
                ),
            )

        return result

    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail=str(exc),
        ) from exc

    except HTTPException:
        raise

    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=(
                "Error guardando ContratacionBasica: "
                f"{exc}"
            ),
        ) from exc