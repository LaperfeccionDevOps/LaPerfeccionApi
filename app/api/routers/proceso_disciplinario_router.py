from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from infrastructure.db.deps import get_db
from domain.models.proceso_disciplinario import ProcesoDisciplinario
from domain.schemas.proceso_disciplinario_schema import (
    ProcesoDisciplinarioCreate,
    ProcesoDisciplinarioUpdate,
    ProcesoDisciplinarioResponse,
)

router = APIRouter(
    prefix="/api/procesos-disciplinarios",
    tags=["Procesos Disciplinarios"],
)


@router.post("/", response_model=ProcesoDisciplinarioResponse)
def crear_proceso_disciplinario(
    data: ProcesoDisciplinarioCreate,
    db: Session = Depends(get_db),
):
    nuevo = ProcesoDisciplinario(
        IdRegistroPersonal=data.IdRegistroPersonal,
        EstadoProceso=data.EstadoProceso or "INICIADO",
        OrigenProceso=data.OrigenProceso or "RRLL",
        UsuarioActualizacion=data.UsuarioActualizacion,
    )

    db.add(nuevo)
    db.commit()
    db.refresh(nuevo)

    return nuevo


@router.get("/{id_proceso}", response_model=ProcesoDisciplinarioResponse)
def obtener_proceso_disciplinario(
    id_proceso: int,
    db: Session = Depends(get_db),
):
    proceso = (
        db.query(ProcesoDisciplinario)
        .filter(ProcesoDisciplinario.IdProcesoDisciplinario == id_proceso)
        .first()
    )

    if not proceso:
        raise HTTPException(status_code=404, detail="Proceso disciplinario no encontrado")

    return proceso


@router.get("/trabajador/{id_registro_personal}")
def listar_procesos_por_trabajador(
    id_registro_personal: int,
    db: Session = Depends(get_db),
):
    procesos = (
        db.query(ProcesoDisciplinario)
        .filter(ProcesoDisciplinario.IdRegistroPersonal == id_registro_personal)
        .order_by(ProcesoDisciplinario.FechaCreacion.desc())
        .all()
    )

    return procesos


@router.put("/{id_proceso}", response_model=ProcesoDisciplinarioResponse)
def actualizar_proceso_disciplinario(
    id_proceso: int,
    data: ProcesoDisciplinarioUpdate,
    db: Session = Depends(get_db),
):
    proceso = (
        db.query(ProcesoDisciplinario)
        .filter(ProcesoDisciplinario.IdProcesoDisciplinario == id_proceso)
        .first()
    )

    if not proceso:
        raise HTTPException(status_code=404, detail="Proceso disciplinario no encontrado")

    if data.EstadoProceso is not None:
        proceso.EstadoProceso = data.EstadoProceso

    if data.OrigenProceso is not None:
        proceso.OrigenProceso = data.OrigenProceso

    if data.UsuarioActualizacion is not None:
        proceso.UsuarioActualizacion = data.UsuarioActualizacion

    proceso.FechaActualizacion = datetime.now()

    db.commit()
    db.refresh(proceso)

    return proceso