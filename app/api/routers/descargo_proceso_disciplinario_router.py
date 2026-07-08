from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from infrastructure.db.deps import get_db
from domain.models.descargo_proceso_disciplinario import DescargoProcesoDisciplinario
from domain.schemas.descargo_proceso_disciplinario_schema import (
    DescargoProcesoDisciplinarioCreate,
    DescargoProcesoDisciplinarioUpdate,
    DescargoProcesoDisciplinarioResponse,
)

router = APIRouter(
    prefix="/api/descargo-proceso-disciplinario",
    tags=["Descargo Proceso Disciplinario"],
)


@router.post("/", response_model=DescargoProcesoDisciplinarioResponse)
def crear_descargo(
    data: DescargoProcesoDisciplinarioCreate,
    db: Session = Depends(get_db),
):
    nuevo = DescargoProcesoDisciplinario(**data.model_dump())

    db.add(nuevo)
    db.commit()
    db.refresh(nuevo)

    return nuevo


@router.get("/{id_descargo}", response_model=DescargoProcesoDisciplinarioResponse)
def obtener_descargo(
    id_descargo: int,
    db: Session = Depends(get_db),
):
    descargo = db.query(DescargoProcesoDisciplinario).filter(
        DescargoProcesoDisciplinario.IdDescargoProcesoDisciplinario == id_descargo
    ).first()

    if not descargo:
        raise HTTPException(status_code=404, detail="Descargo no encontrado")

    return descargo


@router.get("/proceso/{id_proceso}")
def obtener_descargo_por_proceso(
    id_proceso: int,
    db: Session = Depends(get_db),
):
    return db.query(DescargoProcesoDisciplinario).filter(
        DescargoProcesoDisciplinario.IdProcesoDisciplinario == id_proceso
    ).first()


@router.put("/{id_descargo}", response_model=DescargoProcesoDisciplinarioResponse)
def actualizar_descargo(
    id_descargo: int,
    data: DescargoProcesoDisciplinarioUpdate,
    db: Session = Depends(get_db),
):
    descargo = db.query(DescargoProcesoDisciplinario).filter(
        DescargoProcesoDisciplinario.IdDescargoProcesoDisciplinario == id_descargo
    ).first()

    if not descargo:
        raise HTTPException(status_code=404, detail="Descargo no encontrado")

    for campo, valor in data.model_dump(exclude_unset=True).items():
        setattr(descargo, campo, valor)

    descargo.FechaActualizacion = datetime.now()

    db.commit()
    db.refresh(descargo)

    return descargo