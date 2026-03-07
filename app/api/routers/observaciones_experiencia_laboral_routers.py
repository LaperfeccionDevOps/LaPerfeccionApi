from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import Optional
from sqlalchemy.orm import Session
from sqlalchemy import text
import datetime

from infrastructure.db.deps import get_db

router = APIRouter(
    prefix="/observaciones-experiencia-laboral",
    tags=["observaciones experiencia laboral"],
)

# ----------------------------
# Schemas
# ----------------------------
class ObservacionUpsertIn(BaseModel):
    Observaciones: str
    UsuarioActualizacion: str

class ObservacionOut(BaseModel):
    IdExperienciaLaboral: int
    Observaciones: Optional[str] = None
    UsuarioActualizacion: Optional[str] = None
    FechaCreacion: Optional[str] = None
    FechaActualizacion: Optional[str] = None


def _dt_to_iso(v):
    if v is None:
        return None
    if isinstance(v, (datetime.datetime, datetime.date)):
        try:
            return v.isoformat()
        except Exception:
            return str(v)
    return str(v)

# ----------------------------
# GET
# ----------------------------
@router.get("/{id_experiencia_laboral}", response_model=ObservacionOut, summary="Get Observacion")
def get_observacion(id_experiencia_laboral: int, db: Session = Depends(get_db)):
    row = db.execute(text("""
        SELECT
            "IdExperienciaLaboral",
            "Observaciones",
            "UsuarioActualizacion",
            "FechaCreacion",
            "FechaActualizacion"
        FROM public."ObservacionExperienciaLaboral"
        WHERE "IdExperienciaLaboral" = :id
        LIMIT 1
    """), {"id": id_experiencia_laboral}).mappings().first()

    if not row:
        raise HTTPException(status_code=404, detail="No hay observación para esta experiencia laboral.")

    return {
        "IdExperienciaLaboral": row["IdExperienciaLaboral"],
        "Observaciones": row.get("Observaciones"),
        "UsuarioActualizacion": row.get("UsuarioActualizacion"),
        "FechaCreacion": _dt_to_iso(row.get("FechaCreacion")),
        "FechaActualizacion": _dt_to_iso(row.get("FechaActualizacion")),
    }

# ----------------------------
# PUT (UPSERT)
# ----------------------------
@router.put("/{id_experiencia_laboral}", summary="Upsert Observacion")
def upsert_observacion(id_experiencia_laboral: int, payload: ObservacionUpsertIn, db: Session = Depends(get_db)):
    db.execute(text("""
        INSERT INTO public."ObservacionExperienciaLaboral" (
            "IdExperienciaLaboral",
            "Observaciones",
            "UsuarioActualizacion",
            "FechaCreacion",
            "FechaActualizacion"
        )
        VALUES (
            :IdExperienciaLaboral,
            :Observaciones,
            :UsuarioActualizacion,
            now(),
            now()
        )
        ON CONFLICT ("IdExperienciaLaboral")
        DO UPDATE SET
            "Observaciones" = EXCLUDED."Observaciones",
            "UsuarioActualizacion" = EXCLUDED."UsuarioActualizacion",
            "FechaActualizacion" = now()
    """), {
        "IdExperienciaLaboral": id_experiencia_laboral,
        "Observaciones": payload.Observaciones,
        "UsuarioActualizacion": payload.UsuarioActualizacion,
    })

    db.commit()
    return {"ok": True, "IdExperienciaLaboral": id_experiencia_laboral}
