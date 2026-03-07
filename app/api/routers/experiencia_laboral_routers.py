from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from infrastructure.db.deps import get_db
from services.experiencia_laboral_validacion_service import ExperienciaLaboralValidacionService


router = APIRouter(
    prefix="/api/experiencia-laboral-validacion",
    tags=["experiencia-laboral-validacion"],
)


class ExperienciaLaboralValidacionPatch(BaseModel):
    validado: Optional[bool] = None
    payload: Optional[Dict[str, Any]] = Field(default=None)
    validado_por: Optional[int] = None


@router.get("/{aspirante_id}/{exp_idx}")
def get_validacion(
    aspirante_id: int,
    exp_idx: int,
    db: Session = Depends(get_db),
):
    svc = ExperienciaLaboralValidacionService(db)
    data = svc.get_one(aspirante_id, exp_idx)

    if not data:
        return {
            "aspirante_id": aspirante_id,
            "exp_idx": exp_idx,
            "validado": False,
            "payload": {},
            "validado_por": None,
        }
    return data


@router.patch("/{aspirante_id}/{exp_idx}")
def patch_validacion(
    aspirante_id: int,
    exp_idx: int,
    body: ExperienciaLaboralValidacionPatch,
    db: Session = Depends(get_db),
):
    svc = ExperienciaLaboralValidacionService(db)

    payload_dict = body.model_dump(exclude_none=True)
    if not payload_dict:
        raise HTTPException(status_code=400, detail="No enviaste datos para actualizar.")

    if "payload" in payload_dict and payload_dict["payload"] is None:
        payload_dict["payload"] = {}

    return svc.upsert(aspirante_id, exp_idx, payload_dict)
