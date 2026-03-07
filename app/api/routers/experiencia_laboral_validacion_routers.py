from typing import List

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from infrastructure.db.deps import get_db
from services.experiencia_laboral_validacion_service import ExperienciaLaboralValidacionService
from domain.schemas.experiencia_laboral_validacion_schema import ExperienciaLaboralValidacionSchema
from domain.schemas.experiencia_laboral_validacion_schema import ExperienciaLaboralValidacionSchema
from domain.models.experiencia_laboral_validacion import ExperienciaLaboralValidacion


router = APIRouter(
    prefix="/api/experiencia-laboral-validacion",
    tags=["experiencia-laboral-validacion"],
)

service = ExperienciaLaboralValidacionService()


@router.get(
    "/experiencia/{id_experiencia_laboral}",
    response_model=List[ExperienciaLaboralValidacionSchema],
)
def listar_validaciones_por_experiencia(
    id_experiencia_laboral: int,
    db: Session = Depends(get_db),
):
    return service.listar_por_experiencia(db, id_experiencia_laboral)


@router.get(
    "/{id_validacion}",
    response_model=ExperienciaLaboralValidacionSchema,
)
def obtener_validacion_por_id(
    id_validacion: int,
    db: Session = Depends(get_db),
):
    data = service.obtener_por_id(db, id_validacion)
    if not data:
        raise HTTPException(status_code=404, detail="No existe la validación con ese IdValidacion")
    return data


@router.post("/insertar", status_code=201)
def insertar_validacion(
    payload: ExperienciaLaboralValidacionSchema,
    db: Session = Depends(get_db),
):
    # Validar si ya existe un registro con el mismo IdExperienciaLaboral
    existe = db.query(ExperienciaLaboralValidacion).filter(
        ExperienciaLaboralValidacion.IdExperienciaLaboral == payload.IdExperienciaLaboral
    ).first()
    if existe:
        # Actualizar el registro existente con los datos del payload
        for key, value in payload.model_dump(exclude_none=True).items():
            setattr(existe, key, value)
        db.commit()
        db.refresh(existe)
        return {"ok": True, "msg": "Validación actualizada", "IdValidacion": existe.IdValidacion}
    nuevo = ExperienciaLaboralValidacion(**payload.model_dump(exclude_none=True))
    db.add(nuevo)
    db.commit()
    db.refresh(nuevo)
    return {"ok": True, "IdValidacion": nuevo.IdValidacion}

