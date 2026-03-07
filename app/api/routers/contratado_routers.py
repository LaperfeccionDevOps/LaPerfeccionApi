from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import text
from infrastructure.db.deps import get_db
from pydantic import BaseModel

router = APIRouter(prefix="/api", tags=["Contratación - Contratado"])

ESTADO_CONTRATADO = 25  # ✅ según tu tabla EstadoProceso

class ContratadoUpdate(BaseModel):
    IdRegistroPersonal: int

@router.put("/contratado")
def marcar_contratado(payload: ContratadoUpdate, db: Session = Depends(get_db)):
    # 1) Validar que exista el aspirante
    existe = db.execute(
        text('SELECT 1 FROM public."RegistroPersonal" WHERE "IdRegistroPersonal" = :id'),
        {"id": payload.IdRegistroPersonal},
    ).fetchone()

    if not existe:
        raise HTTPException(status_code=404, detail="IdRegistroPersonal no existe en RegistroPersonal.")

    try:
        # 2) Actualizar estado a CONTRATADO
        updated = db.execute(
            text("""
                UPDATE public."RegistroPersonal"
                SET "IdEstadoProceso" = :estado
                WHERE "IdRegistroPersonal" = :id_registro
                RETURNING "IdRegistroPersonal", "IdEstadoProceso";
            """),
            {"estado": ESTADO_CONTRATADO, "id_registro": payload.IdRegistroPersonal},
        ).mappings().first()

        db.commit()

        return {
            "message": "Aspirante marcado como CONTRATADO.",
            "data": updated
        }

    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Error BD: {str(e)}")