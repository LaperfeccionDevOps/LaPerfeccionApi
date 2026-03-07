from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import text
from infrastructure.db.deps import get_db
from pydantic import BaseModel

router = APIRouter(prefix="/api", tags=["Rechazo Contratación"])

ESTADO_RECHAZADO = 28

class RechazoCreate(BaseModel):
    IdRegistroPersonal: int
    ObservacionesRechazo: str

@router.post("/rechazo-contratacion")
def crear_o_actualizar_rechazo(payload: RechazoCreate, db: Session = Depends(get_db)):
    # 1) Validar que exista el aspirante
    existe = db.execute(
        text('SELECT 1 FROM public."RegistroPersonal" WHERE "IdRegistroPersonal" = :id'),
        {"id": payload.IdRegistroPersonal},
    ).fetchone()

    if not existe:
        raise HTTPException(status_code=404, detail="IdRegistroPersonal no existe en RegistroPersonal.")

    try:
        # 2) UPSERT (si existe, actualiza; si no, inserta)
        upsert_sql = text("""
            INSERT INTO public."ObsRechazoContratacion" ("IdRegistroPersonal", "ObservacionesRechazo")
            VALUES (:id_registro, :obs)
            ON CONFLICT ("IdRegistroPersonal")
            DO UPDATE SET
              "ObservacionesRechazo" = EXCLUDED."ObservacionesRechazo"
            RETURNING "IdObsRechazoContratacion", "IdRegistroPersonal", "ObservacionesRechazo", "FechaRechazo";
        """)

        rechazo = db.execute(upsert_sql, {
            "id_registro": payload.IdRegistroPersonal,
            "obs": payload.ObservacionesRechazo
        }).mappings().first()

        # 3) Actualizar estado del aspirante a 28
        db.execute(
            text("""
                UPDATE public."RegistroPersonal"
                SET "IdEstadoProceso" = :estado
                WHERE "IdRegistroPersonal" = :id_registro
            """),
            {"estado": ESTADO_RECHAZADO, "id_registro": payload.IdRegistroPersonal},
        )

        db.commit()
        return rechazo

    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Error BD: {str(e)}")
