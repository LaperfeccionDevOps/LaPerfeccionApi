# app/api/routers/nucleo_familiar_routers.py
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from infrastructure.db.deps import get_db
from domain.models.aspirante import NucleoFamiliarORM  # <- donde tienes el ORM

router = APIRouter()

# ─────────────────────────────────────────────
# Schemas locales (para no tocar otros archivos)
# ─────────────────────────────────────────────
class NucleoFamiliarOut(BaseModel):
    IdNucleoFamiliar: int
    IdRegistroPersonal: int
    Nombre: Optional[str] = None
    Parentesco: Optional[str] = None
    Edad: Optional[int] = None
    Ocupacion: Optional[str] = None
    Telefono: Optional[str] = None
    DependeEconomicamente: Optional[bool] = None
    Observaciones: Optional[str] = None

    class Config:
        from_attributes = True


class UpdateObservacionesPayload(BaseModel):
    observaciones: str


class UpdateObservacionesOut(BaseModel):
    IdNucleoFamiliar: int
    #IdRegistroPersonal: int
    #Observaciones: Optional[str] = None

    class Config:
        from_attributes = True


# ─────────────────────────────────────────────
# ✅ GET: Listar núcleo familiar por candidato
# ─────────────────────────────────────────────
@router.get(
    "/nucleo-familiar/aspirante/{id_registro_personal}",
    response_model=List[NucleoFamiliarOut],
)
def listar_nucleo_familiar_por_aspirante(
    id_registro_personal: int,
    db: Session = Depends(get_db),
):
    familiares = (
        db.query(NucleoFamiliarORM)
        .filter(NucleoFamiliarORM.IdRegistroPersonal == id_registro_personal)
        .order_by(NucleoFamiliarORM.IdNucleoFamiliar.asc())
        .all()
    )
    # Devuelve [] si no hay, eso está bien
    return familiares


# ─────────────────────────────────────────────
# ✅ PATCH: Actualizar observaciones
# ─────────────────────────────────────────────
@router.put(
    "/nucleo-familiar/{id_nucleo_familiar}/observaciones",
    response_model=UpdateObservacionesOut,
)
def actualizar_observaciones_nucleo_familiar(
    id_nucleo_familiar: int,
    payload: UpdateObservacionesPayload,
    db: Session = Depends(get_db),
):
    familiar = (
        db.query(NucleoFamiliarORM)
        .filter(NucleoFamiliarORM.IdNucleoFamiliar == id_nucleo_familiar)
        .first()
    )

    if not familiar:
        raise HTTPException(status_code=404, detail="Núcleo familiar no encontrado")

    familiar.Observaciones = payload.observaciones
    db.commit()
    db.refresh(familiar)

    return familiar
