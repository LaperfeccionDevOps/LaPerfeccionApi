from typing import Optional, Dict, Any
from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session
from sqlalchemy import text

from infrastructure.security.role_guard import require_roles_ids
from api.routers.auth import require_roles_ids
from infrastructure.db.deps import get_db

router = APIRouter(prefix="/api/contratacion", tags=["contratacion"])

ROL_CONTRATACION = 3


class RegistroContratacionIn(BaseModel):
    IdRegistroPersonal: int
    FechaIngreso: Optional[date] = None
    IdBanco: Optional[int] = None
    IdRiesgoLaboral: Optional[int] = None
    IdTipoContrato: Optional[int] = None
    UsuarioActualizacion: Optional[str] = None


@router.get("/registro/{id_registro_personal}")
def obtener_registro_contratacion(id_registro_personal: int, db: Session = Depends(get_db)) -> Dict[str, Any]:
    row = db.execute(
        text("""
            SELECT
                "IdRegistroContratacion",
                "IdRegistroPersonal",
                "FechaIngreso",
                "IdBanco",
                "IdRiesgoLaboral",
                "IdTipoContrato",
                "FechaCreacion",
                "FechaActualizacion",
                "UsuarioActualizacion"
            FROM "RegistroContratacion"
            WHERE "IdRegistroPersonal" = :id
            LIMIT 1
        """),
        {"id": id_registro_personal},
    ).mappings().first()

    if not row:
        raise HTTPException(status_code=404, detail="No hay registro de contratación para este aspirante")

    return dict(row)


@router.post("/registro")
def guardar_registro_contratacion(payload: RegistroContratacionIn, db: Session = Depends(get_db)) -> Dict[str, Any]:
    """
    Crea o actualiza (UPSERT) el registro de contratación por IdRegistroPersonal.
    """
    db.execute(
        text("""
            INSERT INTO "RegistroContratacion"
                ("IdRegistroPersonal", "FechaIngreso", "IdBanco", "IdRiesgoLaboral", "IdTipoContrato", "UsuarioActualizacion")
            VALUES
                (:IdRegistroPersonal, :FechaIngreso, :IdBanco, :IdRiesgoLaboral, :IdTipoContrato, :UsuarioActualizacion)
            ON CONFLICT ("IdRegistroPersonal")
            DO UPDATE SET
                "FechaIngreso" = EXCLUDED."FechaIngreso",
                "IdBanco" = EXCLUDED."IdBanco",
                "IdRiesgoLaboral" = EXCLUDED."IdRiesgoLaboral",
                "IdTipoContrato" = EXCLUDED."IdTipoContrato",
                "UsuarioActualizacion" = EXCLUDED."UsuarioActualizacion",
                "FechaActualizacion" = NOW()
        """),
        payload.model_dump(),
    )
    db.commit()

    return {"ok": True, "message": "Registro de contratación guardado/actualizado", "IdRegistroPersonal": payload.IdRegistroPersonal}


@router.get("/reporte_synergy")
def obtener_reporte_synergy(
        fechaInicio: str,
        fechaFin: str,
        db: Session = Depends(get_db),
        current=Depends(require_roles_ids(ROL_CONTRATACION)),
    ):
    """
        Consume la FUNCIÓN en PostgreSQL que retorna tabla, por ejemplo:
        Ahora recibe fechaInicio y fechaFin como parámetros (formato 'YYYY-MM-DD').
    """

    sql = text("""
            SELECT *
            FROM public.fn_ReporteSinergy(:fecha_inicio, :fecha_fin);
        """)

    rows = db.execute(sql, {"fecha_inicio": fechaInicio, "fecha_fin": fechaFin}).mappings().all()
    
    return {
        "totalFilas": len(rows),
        "filas": rows
    }
