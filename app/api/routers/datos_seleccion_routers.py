# api/routers/datos_seleccion_routers.py
from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Body
from sqlalchemy.orm import Session
from domain.schemas.registro_personal_update_schema import RegistroPersonalUpdateRequest
from repositories.registro_personal_repo import RegistroPersonalRepository

from infrastructure.db.deps import get_db
from services.datos_seleccion_service import DatosSeleccionService
from domain.schemas.datos_seleccion_schema import (
    DatosSeleccionUpsertRequest,
    DatosSeleccionResponse,
)


router = APIRouter(prefix="/api/datos-seleccion", tags=["datos-seleccion"])
service = DatosSeleccionService()
registro_personal_repo = RegistroPersonalRepository()

# Endpoint para actualizar datos de registro personal por IdRegistroPersonal
@router.put("/registro-personal/{id_registro_personal}")
def actualizar_registro_personal(
    id_registro_personal: int,
    body: RegistroPersonalUpdateRequest = Body(...),
    db: Session = Depends(get_db)
):
    data = body.model_dump(exclude_none=True)
    if not data:
        raise HTTPException(status_code=400, detail="No hay datos para actualizar")

    # Actualizar RegistroPersonal (excepto DireccionDatosAdicionales e IdGrupoSanguineo)
    data_registro = {k: v for k, v in data.items() if k not in ("DireccionDatosAdicionales", "IdGrupoSanguineo")}
    updated = 0
    if data_registro:
        updated = registro_personal_repo.update_by_id(db, id_registro_personal, data_registro)
        if updated == 0:
            raise HTTPException(status_code=404, detail="No se encontró el registro personal")

    # Actualizar Direccion en DatosAdicionales si viene en el body
    if "DireccionDatosAdicionales" in data:
        updated_datos = registro_personal_repo.update_direccion_datos_adicionales(
            db, id_registro_personal, data["DireccionDatosAdicionales"], data.get("IdGrupoSanguineo", 0)
        )
        if updated_datos == 0:
            raise HTTPException(status_code=404, detail="No se encontró DatosAdicionales para este registro personal")

    return {"ok": True, "message": "Registro personal y/o dirección adicional actualizados", "IdRegistroPersonal": id_registro_personal}


def _parse_bool(value: Any) -> Optional[bool]:
    """
    Normaliza valores que pueden venir como:
    - bool: True/False
    - int/float: 1/0
    - str: "SI"/"NO", "SÍ"/"NO", "true"/"false", "1"/"0", "yes"/"no"
    Retorna:
    - True / False si puede interpretarlo
    - None si no viene o no se puede interpretar
    """
    if value is None:
        return None

    if isinstance(value, bool):
        return value

    if isinstance(value, (int, float)):
        return bool(value)

    if isinstance(value, str):
        s = value.strip().lower()
        if s in ("si", "sí", "s", "true", "1", "yes", "y"):
            return True
        if s in ("no", "false", "0", "n"):
            return False

    # Si llega algo raro, mejor no “adivinar”; devolvemos None para no pisar.
    return None


@router.get("/{id_registro_personal}", response_model=DatosSeleccionResponse)
def obtener_datos_seleccion(id_registro_personal: int, db: Session = Depends(get_db)):
    data = service.obtener_por_registro_personal(db, id_registro_personal)
    if not data:
        raise HTTPException(
            status_code=404,
            detail="No existen datos de selección para este IdRegistroPersonal"
        )

    # ✅ Respaldo: si por alguna razón FechaActualizacion viene en NULL en BD
    if getattr(data, "FechaActualizacion", None) is None:
        data.FechaActualizacion = datetime.now(timezone.utc)

    return data


@router.post("/upsert", response_model=DatosSeleccionResponse)
def upsert_datos_seleccion(body: DatosSeleccionUpsertRequest, db: Session = Depends(get_db)):
    # ✅ IMPORTANTE: exclude_none=True para NO pisar campos con None (ej. booleano)
    payload = body.model_dump(exclude_none=True)

    # ✅ 1) Normalizar booleano de HaTrabajadoAntesEnLaEmpresa (sin pisar con False cuando no viene)
    # - Si llega el campo real, lo normalizamos (acepta SI/NO, true/false, 1/0, bool)
    if "HaTrabajadoAntesEnLaEmpresa" in payload:
        parsed = _parse_bool(payload.get("HaTrabajadoAntesEnLaEmpresa"))
        if parsed is None:
            # Si no se puede interpretar o viene vacío, lo quitamos para NO pisar el valor en BD
            payload.pop("HaTrabajadoAntesEnLaEmpresa", None)
        else:
            payload["HaTrabajadoAntesEnLaEmpresa"] = parsed

    # - Si NO llega el campo real, pero llega el alias corto "HaTrabajadoAntes", lo convertimos al campo real
    if payload.get("HaTrabajadoAntesEnLaEmpresa") is None and "HaTrabajadoAntes" in payload:
        parsed_alias = _parse_bool(payload.get("HaTrabajadoAntes"))
        if parsed_alias is not None:
            payload["HaTrabajadoAntesEnLaEmpresa"] = parsed_alias
        # Si no se pudo interpretar, no lo enviamos (no pisamos en BD)

    # Eliminamos el campo corto (no existe en la BD)
    payload.pop("HaTrabajadoAntes", None)

    # ✅ 2) Upsert
    data = service.upsert(db, payload)

    # ✅ 3) Respaldo de FechaActualizacion (evita ResponseValidationError)
    if getattr(data, "FechaActualizacion", None) is None:
        data.FechaActualizacion = datetime.now(timezone.utc)

    return data



