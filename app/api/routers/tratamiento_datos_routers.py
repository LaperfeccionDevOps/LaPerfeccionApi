# app/api/routers/tratamiento_datos_routers.py

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session
from sqlalchemy import text

from infrastructure.db.deps import get_db

router = APIRouter(prefix="/api/tratamiento-datos", tags=["tratamiento-datos"])


# ----------------------------
# Schemas
# ----------------------------
class TratamientoDatosCreate(BaseModel):
    IdRegistroPersonal: int
    AceptoTratamientoDatos: bool
    ConflictoInteres: bool


class TratamientoDatosUpdate(BaseModel):
    # Permite actualizar parcial
    AceptoTratamientoDatos: Optional[bool] = None
    ConflictoInteres: Optional[bool] = None


class TratamientoDatosOut(BaseModel):
    IdTratamientoDatos: int
    IdRegistroPersonal: int
    AceptoTratamientoDatos: bool
    ConflictoInteres: bool
    FechaCreacion: datetime


# ----------------------------
# Helpers
# ----------------------------
def _row_to_dict(row):
    return {
        "IdTratamientoDatos": row[0],
        "IdRegistroPersonal": row[1],
        "AceptoTratamientoDatos": row[2],
        "ConflictoInteres": row[3],
        "FechaCreacion": row[4],
    }


# ----------------------------
# Endpoints
# ----------------------------

@router.get("/por-registro/{id_registro_personal}", response_model=TratamientoDatosOut)
def obtener_por_registro(id_registro_personal: int, db: Session = Depends(get_db)):
    # Trae el último registro por si existieran varios (idealmente debería ser 1)
    q = text("""
        SELECT
            "IdTratamientoDatos",
            "IdRegistroPersonal",
            "AceptoTratamientoDatos",
            "ConflictoInteres",
            "FechaCreacion"
        FROM public."TratamientoDatos"
        WHERE "IdRegistroPersonal" = :id_registro_personal
        ORDER BY "IdTratamientoDatos" DESC
        LIMIT 1
    """)
    row = db.execute(q, {"id_registro_personal": id_registro_personal}).fetchone()

    if not row:
        raise HTTPException(status_code=404, detail="No existe TratamientoDatos para ese IdRegistroPersonal.")

    return _row_to_dict(row)


@router.post("/", response_model=TratamientoDatosOut)
def crear(payload: TratamientoDatosCreate, db: Session = Depends(get_db)):
    # Inserta un registro nuevo
    q = text("""
        INSERT INTO public."TratamientoDatos"
            ("IdRegistroPersonal", "AceptoTratamientoDatos", "ConflictoInteres", "FechaCreacion")
        VALUES
            (:IdRegistroPersonal, :AceptoTratamientoDatos, :ConflictoInteres, NOW())
        RETURNING
            "IdTratamientoDatos",
            "IdRegistroPersonal",
            "AceptoTratamientoDatos",
            "ConflictoInteres",
            "FechaCreacion"
    """)
    row = db.execute(q, payload.model_dump()).fetchone()
    db.commit()

    return _row_to_dict(row)


@router.put("/por-registro/{id_registro_personal}", response_model=TratamientoDatosOut)
def actualizar_por_registro(id_registro_personal: int, payload: TratamientoDatosUpdate, db: Session = Depends(get_db)):
    # Actualiza el último registro del IdRegistroPersonal
    # (si quieres forzar 1 único, luego te digo cómo poner UNIQUE)
    # 1) Encontrar el último IdTratamientoDatos
    q_find = text("""
        SELECT "IdTratamientoDatos"
        FROM public."TratamientoDatos"
        WHERE "IdRegistroPersonal" = :id_registro_personal
        ORDER BY "IdTratamientoDatos" DESC
        LIMIT 1
    """)
    row_id = db.execute(q_find, {"id_registro_personal": id_registro_personal}).fetchone()
    if not row_id:
        raise HTTPException(status_code=404, detail="No existe TratamientoDatos para ese IdRegistroPersonal.")

    id_tratamiento = row_id[0]

    q_upd = text("""
        UPDATE public."TratamientoDatos"
        SET
            "AceptoTratamientoDatos" = COALESCE(:AceptoTratamientoDatos, "AceptoTratamientoDatos"),
            "ConflictoInteres"       = COALESCE(:ConflictoInteres, "ConflictoInteres")
        WHERE "IdTratamientoDatos" = :IdTratamientoDatos
        RETURNING
            "IdTratamientoDatos",
            "IdRegistroPersonal",
            "AceptoTratamientoDatos",
            "ConflictoInteres",
            "FechaCreacion"
    """)
    params = {
        "IdTratamientoDatos": id_tratamiento,
        "AceptoTratamientoDatos": payload.AceptoTratamientoDatos,
        "ConflictoInteres": payload.ConflictoInteres,
    }
    row = db.execute(q_upd, params).fetchone()
    db.commit()

    return _row_to_dict(row)


@router.post("/upsert", response_model=TratamientoDatosOut)
def upsert_por_registro(payload: TratamientoDatosCreate, db: Session = Depends(get_db)):
    """
    Si existe TratamientoDatos para IdRegistroPersonal -> actualiza el último.
    Si no existe -> crea uno nuevo.
    """
    q_find = text("""
        SELECT "IdTratamientoDatos"
        FROM public."TratamientoDatos"
        WHERE "IdRegistroPersonal" = :id_registro_personal
        ORDER BY "IdTratamientoDatos" DESC
        LIMIT 1
    """)
    row_id = db.execute(q_find, {"id_registro_personal": payload.IdRegistroPersonal}).fetchone()

    if not row_id:
        # Crear
        q_ins = text("""
            INSERT INTO public."TratamientoDatos"
                ("IdRegistroPersonal", "AceptoTratamientoDatos", "ConflictoInteres", "FechaCreacion")
            VALUES
                (:IdRegistroPersonal, :AceptoTratamientoDatos, :ConflictoInteres, NOW())
            RETURNING
                "IdTratamientoDatos",
                "IdRegistroPersonal",
                "AceptoTratamientoDatos",
                "ConflictoInteres",
                "FechaCreacion"
        """)
        row = db.execute(q_ins, payload.model_dump()).fetchone()
        db.commit()
        return _row_to_dict(row)

    # Actualizar último
    id_tratamiento = row_id[0]
    q_upd = text("""
        UPDATE public."TratamientoDatos"
        SET
            "AceptoTratamientoDatos" = :AceptoTratamientoDatos,
            "ConflictoInteres"       = :ConflictoInteres
        WHERE "IdTratamientoDatos" = :IdTratamientoDatos
        RETURNING
            "IdTratamientoDatos",
            "IdRegistroPersonal",
            "AceptoTratamientoDatos",
            "ConflictoInteres",
            "FechaCreacion"
    """)
    params = {
        "IdTratamientoDatos": id_tratamiento,
        "AceptoTratamientoDatos": payload.AceptoTratamientoDatos,
        "ConflictoInteres": payload.ConflictoInteres,
    }
    row = db.execute(q_upd, params).fetchone()
    db.commit()

    return _row_to_dict(row)
