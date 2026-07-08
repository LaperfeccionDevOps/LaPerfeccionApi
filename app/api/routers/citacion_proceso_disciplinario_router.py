from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from infrastructure.db.deps import get_db
from domain.models.citacion_proceso_disciplinario import CitacionProcesoDisciplinario
from domain.schemas.citacion_proceso_disciplinario_schema import (
    CitacionProcesoDisciplinarioCreate,
    CitacionProcesoDisciplinarioUpdate,
    CitacionProcesoDisciplinarioResponse,
)

router = APIRouter(
    prefix="/api/citacion-proceso-disciplinario",
    tags=["Citación Proceso Disciplinario"],
)


@router.post("/", response_model=CitacionProcesoDisciplinarioResponse)
def crear_citacion(data: CitacionProcesoDisciplinarioCreate, db: Session = Depends(get_db)):
    nueva = CitacionProcesoDisciplinario(**data.model_dump())

    db.add(nueva)
    db.commit()
    db.refresh(nueva)

    return nueva


@router.get("/{id_citacion}", response_model=CitacionProcesoDisciplinarioResponse)
def obtener_citacion(id_citacion: int, db: Session = Depends(get_db)):
    citacion = db.query(CitacionProcesoDisciplinario).filter(
        CitacionProcesoDisciplinario.IdCitacionProcesoDisciplinario == id_citacion
    ).first()

    if not citacion:
        raise HTTPException(status_code=404, detail="Citación no encontrada")

    return citacion


@router.get("/proceso/{id_proceso}")
def obtener_citacion_por_proceso(id_proceso: int, db: Session = Depends(get_db)):
    return db.query(CitacionProcesoDisciplinario).filter(
        CitacionProcesoDisciplinario.IdProcesoDisciplinario == id_proceso
    ).first()


@router.put("/{id_citacion}", response_model=CitacionProcesoDisciplinarioResponse)
def actualizar_citacion(
    id_citacion: int,
    data: CitacionProcesoDisciplinarioUpdate,
    db: Session = Depends(get_db),
):
    citacion = db.query(CitacionProcesoDisciplinario).filter(
        CitacionProcesoDisciplinario.IdCitacionProcesoDisciplinario == id_citacion
    ).first()

    if not citacion:
        raise HTTPException(status_code=404, detail="Citación no encontrada")

    for campo, valor in data.model_dump(exclude_unset=True).items():
        setattr(citacion, campo, valor)

    citacion.FechaActualizacion = datetime.now()

    db.commit()
    db.refresh(citacion)

    return citacion