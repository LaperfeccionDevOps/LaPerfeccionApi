from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session
from sqlalchemy import text
from typing import Optional

from infrastructure.db.deps import get_db


router = APIRouter(
    prefix="/api/clientes",
    tags=["clientes"],
)


# ---------------------------------------------------------
# SCHEMAS
# ---------------------------------------------------------

class ClienteCrearIn(BaseModel):
    Nombre: str
    CreadoPor: Optional[str] = None


class ClienteOut(BaseModel):
    IdCliente: int
    Nombre: str
    Activo: bool
    CreadoPor: Optional[str] = None


# ---------------------------------------------------------
# GET - LISTAR CLIENTES ACTIVOS
# ---------------------------------------------------------

@router.get("", response_model=list[ClienteOut])
def listar_clientes(db: Session = Depends(get_db)):

    clientes = db.execute(
        text("""
            SELECT
                "IdCliente",
                "Nombre",
                COALESCE("Activo", true) AS "Activo",
                "CreadoPor"
            FROM public."Cliente"
            WHERE COALESCE("Activo", true) = true
            ORDER BY LOWER(TRIM("Nombre")) ASC
        """)
    ).mappings().all()

    return [dict(cliente) for cliente in clientes]


# ---------------------------------------------------------
# POST - CREAR CLIENTE
# ---------------------------------------------------------

@router.post("", response_model=ClienteOut, status_code=201)
def crear_cliente(
    payload: ClienteCrearIn,
    db: Session = Depends(get_db)
):

    # -----------------------------------------------------
    # NORMALIZAR NOMBRE RECIBIDO
    # -----------------------------------------------------
    # Elimina espacios al inicio/final y convierte
    # múltiples espacios, tabs o saltos de línea
    # en un solo espacio.
    nombre = " ".join((payload.Nombre or "").strip().split())

    if not nombre:
        raise HTTPException(
            status_code=400,
            detail="El nombre del cliente es obligatorio."
        )

    # -----------------------------------------------------
    # VALIDAR DUPLICADO
    # -----------------------------------------------------
    # También normalizamos los nombres históricos de BD.
    #
    # Esto evita duplicados cuando un registro antiguo
    # contiene:
    # - espacios adicionales
    # - tabulaciones
    # - saltos de línea
    # - retornos de carro
    #
    # Ejemplo:
    # "MEDIPORT ... Salud\n"
    # será considerado igual a:
    # "MEDIPORT ... Salud"
    # -----------------------------------------------------

    existente = db.execute(
        text("""
            SELECT
                "IdCliente",
                "Nombre"
            FROM public."Cliente"
            WHERE LOWER(
                TRIM(
                    REGEXP_REPLACE(
                        "Nombre",
                        '[[:space:]]+',
                        ' ',
                        'g'
                    )
                )
            ) = LOWER(:nombre)
            LIMIT 1
        """),
        {
            "nombre": nombre
        }
    ).mappings().first()

    if existente:
        raise HTTPException(
            status_code=409,
            detail=(
                f'El cliente "{existente["Nombre"].strip()}" '
                f'ya existe con IdCliente {existente["IdCliente"]}.'
            )
        )

    # -----------------------------------------------------
    # CREAR CLIENTE
    # -----------------------------------------------------
    # IdCliente es GENERATED ALWAYS AS IDENTITY.
    # PostgreSQL genera el ID automáticamente.
    # -----------------------------------------------------

    try:

        nuevo_cliente = db.execute(
            text("""
                INSERT INTO public."Cliente" (
                    "Nombre",
                    "Activo",
                    "FechaCreacion",
                    "CreadoPor"
                )
                VALUES (
                    :nombre,
                    true,
                    NOW(),
                    :creado_por
                )
                RETURNING
                    "IdCliente",
                    "Nombre",
                    "Activo",
                    "CreadoPor"
            """),
            {
                "nombre": nombre,
                "creado_por": payload.CreadoPor
            }
        ).mappings().first()

        db.commit()

        return dict(nuevo_cliente)

    except HTTPException:
        db.rollback()
        raise

    except Exception as e:
        db.rollback()

        print(f"ERROR creando cliente: {repr(e)}")

        raise HTTPException(
            status_code=500,
            detail="No fue posible crear el cliente."
        )