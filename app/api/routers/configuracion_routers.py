# app/api/routers/estado_proceso_routers.py

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from sqlalchemy import text
from utilidades.enum import Configuracion

from infrastructure.db.deps import get_db
from repositories.contador_registro_personal_repo import contador_registro_personal

router = APIRouter(
    prefix="/configuracion",
    tags=["configuracion"],
)

@router.post("/contador_registro_personal/{id_registro_personal}")
def endpoint_contador_registro_personal(id_registro_personal: int, db: Session = Depends(get_db)):
    contador = contador_registro_personal(db, id_registro_personal)
    return {"IdRegistroPersonal": id_registro_personal, "Contador": contador}

