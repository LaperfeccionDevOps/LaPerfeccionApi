from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session
from sqlalchemy import text
from typing import Optional

from infrastructure.db.deps import get_db


router = APIRouter(
    prefix="/api/cargos",
    tags=["cargos"],
)


class CargoCrearIn(BaseModel):
    NombreCargo: str
    UsuarioActualizacion: Optional[str] = None


class CargoOut(BaseModel):
    IdCargo: int
    NombreCargo: str
    IdTipoCargo: Optional[int] = None
    Activo: bool
    UsuarioActualizacion: Optional[str] = None


@router.post("", response_model=CargoOut, status_code=201)
def crear_cargo(payload: CargoCrearIn, db: Session = Depends(get_db)):

    # Normaliza espacios al inicio, final y espacios repetidos
    nombre = " ".join((payload.NombreCargo or "").strip().split())

    if not nombre:
        raise HTTPException(
            status_code=400,
            detail="El nombre del cargo es obligatorio."
        )

    # Validación fuerte de duplicados
    existente = db.execute(
        text("""
            SELECT
                "IdCargo",
                "NombreCargo"
            FROM public."Cargo"
            WHERE LOWER(
                TRIM(
                    REGEXP_REPLACE(
                        "NombreCargo",
                        '[[:space:]]+',
                        ' ',
                        'g'
                    )
                )
            ) = LOWER(:nombre)
            LIMIT 1
        """),
        {"nombre": nombre}
    ).mappings().first()

    if existente:
        raise HTTPException(
            status_code=409,
            detail=(
                f'El cargo "{existente["NombreCargo"].strip()}" '
                f'ya existe con IdCargo {existente["IdCargo"]}.'
            )
        )

    try:
        nuevo_cargo = db.execute(
            text("""
                INSERT INTO public."Cargo" (
                    "NombreCargo",
                    "IdTipoCargo",
                    "Activo",
                    "FechaCreacion",
                    "UsuarioActualizacion"
                )
                VALUES (
                    :nombre,
                    NULL,
                    true,
                    NOW(),
                    :usuario
                )
                RETURNING
                    "IdCargo",
                    "NombreCargo",
                    "IdTipoCargo",
                    "Activo",
                    "UsuarioActualizacion"
            """),
            {
                "nombre": nombre,
                "usuario": payload.UsuarioActualizacion
            }
        ).mappings().first()

        db.commit()

        return dict(nuevo_cargo)

    except HTTPException:
        db.rollback()
        raise

    except Exception as e:
        db.rollback()
        print(f"ERROR creando cargo: {repr(e)}")

        raise HTTPException(
            status_code=500,
            detail="No fue posible crear el cargo."
        )