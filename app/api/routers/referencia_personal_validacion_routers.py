from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from infrastructure.db.deps import get_db
from services.referencia_personal_validacion_service import ReferenciaPersonalValidacionService
from domain.schemas.referencia_personal_validacion_schema import (
    ReferenciaPersonalValidacionBase,
    ReferenciaPersonalValidacionOut,
)
from domain.models.referencia_personal_validacion import ReferenciaPersonalValidacion

router = APIRouter(
    prefix="/api/referencias-personales-validacion",
    tags=["referencias personales validacion"],
)

@router.get("/{aspirante_id}/{ref_idx}", response_model=ReferenciaPersonalValidacionOut)
def get_validacion(aspirante_id: int, ref_idx: int, db: Session = Depends(get_db)):
    row = ReferenciaPersonalValidacionService.get(db, aspirante_id, ref_idx)
    if not row:
        raise HTTPException(status_code=404, detail="No hay validación para esa referencia personal.")
    return row


@router.post("/upsert", response_model=ReferenciaPersonalValidacionOut)
def upsert_validacion(
    body: ReferenciaPersonalValidacionBase,
    db: Session = Depends(get_db),
):
    try:
        existe = db.query(ReferenciaPersonalValidacion).filter(
          ReferenciaPersonalValidacion.IdReferencia == body.IdReferencia
        ).first()
        if existe:
            # Actualizar el registro existente con los datos del payload
            for key, value in body.model_dump(exclude_none=True).items():
                setattr(existe, key, value)
            db.commit()
            db.refresh(existe)
            return existe
        nuevo = ReferenciaPersonalValidacion(**body.model_dump(exclude_none=True))
        db.add(nuevo)
        db.commit()
        db.refresh(nuevo)
        return nuevo
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
