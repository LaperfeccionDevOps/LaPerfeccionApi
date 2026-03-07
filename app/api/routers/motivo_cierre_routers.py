# app/api/routers/motivo_cierre_routers.py
from typing import Optional, Dict, Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session
from sqlalchemy import text

from infrastructure.db.deps import get_db

router = APIRouter(prefix="/api/motivo-cierre", tags=["motivo-cierre"])


class MotivoCierreUpsert(BaseModel):
    MotivoCierre: str
    Observaciones: Optional[str] = None
    UsuarioActualizacion: str


@router.get("/{id_registro_personal}")
def obtener_motivo_cierre(id_registro_personal: int, db: Session = Depends(get_db)) -> Dict[str, Any]:
    q = text("""
        SELECT
          "IdRegistroPersonal",
          "MotivoCierre",
          "Observaciones",
          "UsuarioActualizacion",
          "FechaCreacion",
          "FechaActualizacion"
        FROM "MotivoCierreProceso"
        WHERE "IdRegistroPersonal" = :id
        LIMIT 1;
    """)
    row = db.execute(q, {"id": id_registro_personal}).mappings().first()
    if not row:
        raise HTTPException(status_code=404, detail="No hay motivo de cierre para este IdRegistroPersonal")
    return dict(row)


@router.put("/{id_registro_personal}")
def upsert_motivo_cierre(
    id_registro_personal: int,
    payload: MotivoCierreUpsert,
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    if not payload.MotivoCierre or not payload.MotivoCierre.strip():
        raise HTTPException(status_code=422, detail="MotivoCierre es requerido")

    # (Opcional) Validar que exista el RegistroPersonal
    existe = db.execute(
        text('SELECT 1 FROM "RegistroPersonal" WHERE "IdRegistroPersonal" = :id LIMIT 1;'),
        {"id": id_registro_personal},
    ).first()
    if not existe:
        raise HTTPException(status_code=404, detail="IdRegistroPersonal no existe en RegistroPersonal")

    q = text("""
        INSERT INTO "MotivoCierreProceso"
          ("IdRegistroPersonal","MotivoCierre","Observaciones","UsuarioActualizacion","FechaCreacion","FechaActualizacion")
        VALUES
          (:id, :motivo, :obs, :usr, now(), now())
        ON CONFLICT ("IdRegistroPersonal") DO UPDATE
        SET
          "MotivoCierre" = EXCLUDED."MotivoCierre",
          "Observaciones" = EXCLUDED."Observaciones",
          "UsuarioActualizacion" = EXCLUDED."UsuarioActualizacion",
          "FechaActualizacion" = now()
        ;
    """)

    db.execute(q, {
        "id": id_registro_personal,
        "motivo": payload.MotivoCierre.strip(),
        "obs": payload.Observaciones,
        "usr": payload.UsuarioActualizacion.strip(),
    })
    db.commit()

    return {"ok": True, "message": "Motivo cierre guardado/actualizado", "IdRegistroPersonal": id_registro_personal}
