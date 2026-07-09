from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from infrastructure.db.deps import get_db
from domain.models.cierre_proceso_disciplinario import CierreProcesoDisciplinario
from domain.models.proceso_disciplinario import ProcesoDisciplinario
from domain.schemas.cierre_proceso_disciplinario_schema import (
    CierreProcesoDisciplinarioCreate,
    CierreProcesoDisciplinarioUpdate,
    CierreProcesoDisciplinarioResponse,
)

router = APIRouter(
    prefix="/api/cierre-proceso-disciplinario",
    tags=["Cierre Proceso Disciplinario"],
)


@router.post("/", response_model=CierreProcesoDisciplinarioResponse)
def crear_cierre(
    data: CierreProcesoDisciplinarioCreate,
    db: Session = Depends(get_db),
):
    proceso = (
        db.query(ProcesoDisciplinario)
        .filter(
            ProcesoDisciplinario.IdProcesoDisciplinario
            == data.IdProcesoDisciplinario
        )
        .first()
    )

    if not proceso:
        raise HTTPException(
            status_code=404,
            detail="Proceso disciplinario no encontrado",
        )

    nuevo = CierreProcesoDisciplinario(**data.model_dump())

    proceso.EstadoProceso = "CERRADO"
    proceso.FechaActualizacion = datetime.now()

    db.add(nuevo)
    db.commit()
    db.refresh(nuevo)

    return nuevo


@router.get("/{id_cierre}", response_model=CierreProcesoDisciplinarioResponse)
def obtener_cierre(
    id_cierre: int,
    db: Session = Depends(get_db),
):
    cierre = (
        db.query(CierreProcesoDisciplinario)
        .filter(
            CierreProcesoDisciplinario.IdCierreProcesoDisciplinario == id_cierre
        )
        .first()
    )

    if not cierre:
        raise HTTPException(status_code=404, detail="Cierre no encontrado")

    return cierre


@router.get("/proceso/{id_proceso}")
def obtener_cierre_por_proceso(
    id_proceso: int,
    db: Session = Depends(get_db),
):
    return (
        db.query(CierreProcesoDisciplinario)
        .filter(
            CierreProcesoDisciplinario.IdProcesoDisciplinario == id_proceso
        )
        .first()
    )


@router.put("/{id_cierre}", response_model=CierreProcesoDisciplinarioResponse)
def actualizar_cierre(
    id_cierre: int,
    data: CierreProcesoDisciplinarioUpdate,
    db: Session = Depends(get_db),
):
    cierre = (
        db.query(CierreProcesoDisciplinario)
        .filter(
            CierreProcesoDisciplinario.IdCierreProcesoDisciplinario == id_cierre
        )
        .first()
    )

    if not cierre:
        raise HTTPException(status_code=404, detail="Cierre no encontrado")

    for campo, valor in data.model_dump(exclude_unset=True).items():
        setattr(cierre, campo, valor)

    proceso = (
        db.query(ProcesoDisciplinario)
        .filter(
            ProcesoDisciplinario.IdProcesoDisciplinario
            == cierre.IdProcesoDisciplinario
        )
        .first()
    )

    if proceso:
        proceso.EstadoProceso = "CERRADO"
        proceso.FechaActualizacion = datetime.now()

    cierre.FechaActualizacion = datetime.now()

    db.commit()
    db.refresh(cierre)

    return cierre