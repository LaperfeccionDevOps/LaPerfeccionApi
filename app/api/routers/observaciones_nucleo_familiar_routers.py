# app/api/routers/observaciones_nucleo_familiar_routers.py
from typing import Optional, List
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session
from sqlalchemy import text

from infrastructure.db.deps import get_db

router = APIRouter(
    prefix="/observaciones-nucleo-familiar",
    tags=["observaciones-nucleo-familiar"],
)

# -------------------------
# Schemas
# -------------------------
class ObservacionNFIn(BaseModel):
    observaciones: str
    usuarioActualizacion: Optional[str] = None

class ObservacionNFOut(BaseModel):
    IdNucleoFamiliar: int
    Observaciones: Optional[str] = None
    FechaCreacion: Optional[datetime] = None
    UsuarioActualizacion: Optional[str] = None

# -------------------------
# GET por IdNucleoFamiliar
# -------------------------
@router.get("/{id_nucleo_familiar}", response_model=ObservacionNFOut)
def get_observacion_por_nucleo(id_nucleo_familiar: int, db: Session = Depends(get_db)):
    q = text("""
        SELECT
            "IdNucleoFamiliar",
            "Observaciones",
            "FechaCreacion",
            "UsuarioActualizacion"
        FROM public."ObservacionesNucleoFamiliar"
        WHERE "IdNucleoFamiliar" = :id
        LIMIT 1
    """)
    row = db.execute(q, {"id": id_nucleo_familiar}).mappings().first()

    if not row:
        return {
            "IdNucleoFamiliar": id_nucleo_familiar,
            "Observaciones": None,
            "FechaCreacion": None,
            "UsuarioActualizacion": None
        }
    return dict(row)

# -------------------------
# GET por aspirante
# -------------------------
@router.get("/aspirante/{id_registro_personal}", response_model=List[ObservacionNFOut])
def get_observaciones_por_aspirante(id_registro_personal: int, db: Session = Depends(get_db)):
    q = text("""
        SELECT
            onf."IdNucleoFamiliar",
            onf."Observaciones",
            onf."FechaCreacion",
            onf."UsuarioActualizacion"
        FROM public."ObservacionesNucleoFamiliar" onf
        JOIN public."NucleoFamiliar" nf
          ON nf."IdNucleoFamiliar" = onf."IdNucleoFamiliar"
        WHERE nf."IdRegistroPersonal" = :id_registro
        ORDER BY onf."IdNucleoFamiliar" ASC
    """)
    rows = db.execute(q, {"id_registro": id_registro_personal}).mappings().all()
    return [dict(r) for r in rows]

# -------------------------
# PUT guardar/actualizar
# -------------------------
@router.put("/{id_nucleo_familiar}", response_model=ObservacionNFOut)
def upsert_observacion(id_nucleo_familiar: int, payload: ObservacionNFIn, db: Session = Depends(get_db)):
    obs = (payload.observaciones or "").strip()
    if obs == "":
        raise HTTPException(status_code=400, detail="observaciones no puede venir vacío")

    # Buscar si existe registro para ese IdNucleoFamiliar
    q_exist = text('SELECT "IdObservacionesNucleoFamiliar" FROM public."ObservacionesNucleoFamiliar" WHERE "IdNucleoFamiliar" = :id LIMIT 1')
    row = db.execute(q_exist, {"id": id_nucleo_familiar}).mappings().first()

    if row:
        # UPDATE
        upd = text('UPDATE public."ObservacionesNucleoFamiliar" SET "Observaciones" = :obs, "UsuarioActualizacion" = :usr WHERE "IdNucleoFamiliar" = :id')
        db.execute(upd, {"id": id_nucleo_familiar, "obs": obs, "usr": payload.usuarioActualizacion})
    else:
        # INSERT
        ins = text('INSERT INTO public."ObservacionesNucleoFamiliar" ("IdNucleoFamiliar", "Observaciones", "FechaCreacion", "UsuarioActualizacion") VALUES (:id, :obs, NOW(), :usr)')
        db.execute(ins, {"id": id_nucleo_familiar, "obs": obs, "usr": payload.usuarioActualizacion})
    db.commit()

    return get_observacion_por_nucleo(id_nucleo_familiar, db)
