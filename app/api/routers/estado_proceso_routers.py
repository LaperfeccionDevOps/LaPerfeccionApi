# app/api/routers/estado_proceso_routers.py

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from sqlalchemy import text

from infrastructure.db.deps import get_db

router = APIRouter(
    prefix="/estados-proceso",     # quedará /api/estados-proceso
    tags=["estados-proceso"],
)


@router.get("")
def listar_estados_proceso(db: Session = Depends(get_db)):
    """
    Devuelve el catálogo de estados del proceso de selección,
    para llenar el combo "Estado del Proceso" en el front.
    """
    sql = text(
        """
        SELECT
            "IdEstadoProceso",
            "Descripcion",
            "Color",
            "Orden"
        FROM "EstadoProceso"
        ORDER BY "Orden" ASC, "Descripcion" ASC
        """
    )

    rows = db.execute(sql).mappings().all()
    return [dict(r) for r in rows]
