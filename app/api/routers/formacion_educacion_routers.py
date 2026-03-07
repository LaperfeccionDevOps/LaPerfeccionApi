from typing import Optional, Union, Any, Dict
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from sqlalchemy import text

from infrastructure.db.deps import get_db

router = APIRouter(
    prefix="/api/candidatos",
    tags=["candidatos - formacion"],
)

# ─────────────────────────────────────────────
# Normalizador: EstudiaActualmente (DB es VARCHAR)
# ─────────────────────────────────────────────
def _normalizar_estudia_actualmente(valor: Optional[Union[bool, str]]) -> Optional[str]:
    if valor is None:
        return None
    if isinstance(valor, bool):
        return "Si" if valor else "No"

    s = str(valor).strip().lower()
    if s in {"si", "sí", "s", "true", "1", "y", "yes"}:
        return "Si"
    if s in {"no", "n", "false", "0"}:
        return "No"
    return str(valor).strip()


# ─────────────────────────────────────────────
# Schemas (solo los 4 campos pedidos)
# ─────────────────────────────────────────────
class FormacionEducacionUpdate(BaseModel):
    IdNivelEducativo: Optional[int] = Field(default=None)
    EstudiaActualmente: Optional[Union[bool, str]] = Field(default=None)
    DescripcionFormacionAcademica: Optional[str] = Field(default=None, max_length=500)
    IdTipoEstadoFormacion: Optional[int] = Field(default=None)

    UsuarioActualizacion: Optional[str] = Field(default=None, max_length=100)

    class Config:
        extra = "forbid"


class FormacionEducacionOut(BaseModel):
    IdRegistroPersonal: int
    IdNivelEducativo: Optional[int] = None
    EstudiaActualmente: Optional[str] = None
    DescripcionFormacionAcademica: Optional[str] = None
    IdTipoEstadoFormacion: Optional[int] = None


def _row_to_out(row: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "IdRegistroPersonal": row.get("IdRegistroPersonal"),
        "IdNivelEducativo": row.get("IdNivelEducativo"),
        "EstudiaActualmente": row.get("EstudiaActualmente"),
        "DescripcionFormacionAcademica": row.get("DescripcionFormacionAcademica"),
        "IdTipoEstadoFormacion": row.get("IdTipoEstadoFormacion"),
    }


# ─────────────────────────────────────────────
# SQL (con comillas porque tu tabla/columnas están en CamelCase)
# ─────────────────────────────────────────────
SQL_SELECT = """
SELECT
  "IdRegistroPersonal",
  "IdNivelEducativo",
  "EstudiaActualmente",
  "DescripcionFormacionAcademica",
  "IdTipoEstadoFormacion"
FROM public."RegistroPersonal"
WHERE "IdRegistroPersonal" = :id_registro_personal
"""

SQL_EXISTS = """
SELECT 1
FROM public."RegistroPersonal"
WHERE "IdRegistroPersonal" = :id_registro_personal
"""

SQL_UPDATE = """
UPDATE public."RegistroPersonal"
SET
  "IdNivelEducativo" = COALESCE(:id_nivel_educativo, "IdNivelEducativo"),
  "EstudiaActualmente" = COALESCE(:estudia_actualmente, "EstudiaActualmente"),
  "DescripcionFormacionAcademica" = COALESCE(:descripcion_formacion_academica, "DescripcionFormacionAcademica"),
  "IdTipoEstadoFormacion" = COALESCE(:id_tipo_estado_formacion, "IdTipoEstadoFormacion"),
  "FechaActualizacion" = NOW(),
  "UsuarioActualizacion" = COALESCE(:usuario_actualizacion, "UsuarioActualizacion")
WHERE "IdRegistroPersonal" = :id_registro_personal
RETURNING
  "IdRegistroPersonal",
  "IdNivelEducativo",
  "EstudiaActualmente",
  "DescripcionFormacionAcademica",
  "IdTipoEstadoFormacion"
"""


# ─────────────────────────────────────────────
# Endpoints
# ─────────────────────────────────────────────
@router.get("/{id_registro_personal}/formacion-educacion", response_model=FormacionEducacionOut)
def obtener_formacion_educacion(
    id_registro_personal: int,
    db: Session = Depends(get_db),
):
    row = db.execute(
        text(SQL_SELECT),
        {"id_registro_personal": id_registro_personal},
    ).mappings().first()

    if not row:
        raise HTTPException(
            status_code=404,
            detail=f"No existe RegistroPersonal con IdRegistroPersonal={id_registro_personal}",
        )

    return _row_to_out(row)


@router.put("/{id_registro_personal}/formacion-educacion", response_model=FormacionEducacionOut)
def guardar_actualizar_formacion_educacion(
    id_registro_personal: int,
    payload: FormacionEducacionUpdate,
    db: Session = Depends(get_db),
):
    exists = db.execute(
        text(SQL_EXISTS),
        {"id_registro_personal": id_registro_personal},
    ).first()

    if not exists:
        raise HTTPException(
            status_code=404,
            detail=f"No existe RegistroPersonal con IdRegistroPersonal={id_registro_personal}",
        )

    params = {
        "id_registro_personal": id_registro_personal,
        "id_nivel_educativo": payload.IdNivelEducativo,
        "estudia_actualmente": _normalizar_estudia_actualmente(payload.EstudiaActualmente),
        "descripcion_formacion_academica": payload.DescripcionFormacionAcademica,
        "id_tipo_estado_formacion": payload.IdTipoEstadoFormacion,
        "usuario_actualizacion": payload.UsuarioActualizacion,
    }

    try:
        row = db.execute(text(SQL_UPDATE), params).mappings().first()
        db.commit()
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=500,
            detail=f"Error actualizando Formación/Educación en RegistroPersonal: {str(e)}",
        )

    if not row:
        raise HTTPException(status_code=500, detail="No fue posible actualizar (sin retorno).")

    return _row_to_out(row)
