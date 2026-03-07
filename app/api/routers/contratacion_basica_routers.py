# app/api/routers/contratacion_basica_routers.py

import datetime
from typing import Optional

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


# ---------- Schemas ----------
class ContratacionBasicaIn(BaseModel):
    IdRegistroPersonal: int
    IdBanco: Optional[int] = None
    IdTipoContrato: Optional[int] = None
    FechaIngreso: Optional[datetime.date] = None
    RiesgoLaboral: Optional[str] = None

    # ✅ NUEVOS CAMPOS (BD ya actualizada)
    Posicion: Optional[str] = Field(default=None, max_length=100)

    # Escalafón: solo 200 o 220 (si viene)
    Escalafon: Optional[str] = Field(default=None, max_length=4, pattern=r"^(200|220)$")

    # Número de cuenta: texto manual (no numérico)
    NumeroCuenta: Optional[str] = Field(default=None, max_length=40)


class ContratacionBasicaOut(ContratacionBasicaIn):
    IdContratacionBasica: int
    FechaCreacion: datetime.datetime
    FechaActualizacion: datetime.datetime


# ---------- Endpoints ----------
@router.get("/registro-personal/{id_registro_personal}", response_model=Optional[ContratacionBasicaOut])
def obtener_por_registro_personal(id_registro_personal: int, db: Session = Depends(get_db)):
    return service.obtener(db, id_registro_personal)


@router.post("", response_model=ContratacionBasicaOut)
def upsert(payload: ContratacionBasicaIn, db: Session = Depends(get_db)):
    try:
        result = service.guardar(db, payload.model_dump())

        # ✅ CLAVE: si el service/repo devuelve None, NO dejamos que FastAPI reviente con ResponseValidationError.
        if result is None:
            raise HTTPException(
                status_code=500,
                detail=(
                    "ContratacionBasicaService.guardar() retornó None. "
                    "Revisa el repo: create/update/returning y que upsert esté retornando dict."
                ),
            )

        # (opcional) si por alguna razón devuelve algo no-dict
        if not isinstance(result, dict):
            raise HTTPException(
                status_code=500,
                detail=f"Respuesta inesperada del service: {type(result)}. Se esperaba dict.",
            )

        return result

    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error guardando ContratacionBasica: {str(e)}")
