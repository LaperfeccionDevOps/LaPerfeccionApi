from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, field_validator
from typing import Optional
from sqlalchemy.orm import Session
from sqlalchemy import text
import datetime

from infrastructure.db.deps import get_db

router = APIRouter(
    prefix="/datos-proceso-aspirante",
    tags=["datos-proceso-aspirante"],
)


class DatosProcesoAspiranteIn(BaseModel):
    # ✅ Acepta date y también datetime/strings tipo ISO y lo normaliza a DATE
    fecha_proceso: Optional[datetime.date] = None
    id_tipo_cargo: Optional[int] = None
    ha_trabajado_antes_empresa: Optional[bool] = None
    antecedentes_medicos: Optional[str] = None
    medicamentos: Optional[str] = None

    @field_validator("fecha_proceso", mode="before")
    @classmethod
    def parse_fecha_proceso(cls, v):
        if v is None or v == "":
            return None

        # Si llega datetime → lo bajamos a date
        if isinstance(v, datetime.datetime):
            return v.date()

        # Si ya es date → ok
        if isinstance(v, datetime.date):
            return v

        # Si llega string "2025-12-18T..." → "2025-12-18"
        if isinstance(v, str):
            if "T" in v:
                v = v.split("T")[0]
            return datetime.date.fromisoformat(v)

        return v


class DatosProcesoAspiranteOut(DatosProcesoAspiranteIn):
    id_registro_personal: int


@router.get("/{id_registro_personal}", response_model=DatosProcesoAspiranteOut)
def obtener_datos_proceso(id_registro_personal: int, db: Session = Depends(get_db)):
    sql = '''
    SELECT
      "IdRegistroPersonal"      AS id_registro_personal,
      "FechaProceso"            AS fecha_proceso,
      "IdTipoCargo"             AS id_tipo_cargo,
      "HaTrabajadoAntesEmpresa" AS ha_trabajado_antes_empresa,
      "AntecedentesMedicos"     AS antecedentes_medicos,
      "Medicamentos"            AS medicamentos
    FROM "DatosProcesoAspirante"
    WHERE "IdRegistroPersonal" = :id
    '''
    row = db.execute(text(sql), {"id": id_registro_personal}).mappings().first()

    # Si no existe aún, devolvemos vacío (para que el front muestre campos en blanco)
    if not row:
        return {
            "id_registro_personal": id_registro_personal,
            "fecha_proceso": None,
            "id_tipo_cargo": None,
            "ha_trabajado_antes_empresa": None,
            "antecedentes_medicos": None,
            "medicamentos": None,
        }

    return dict(row)


@router.put("/{id_registro_personal}", response_model=DatosProcesoAspiranteOut)
def upsert_datos_proceso(
    id_registro_personal: int,
    data: DatosProcesoAspiranteIn,
    db: Session = Depends(get_db),
):
    # Upsert: si existe actualiza; si no existe inserta.
    # COALESCE para que si mandan None no borre lo que ya estaba guardado.
    sql = '''
    INSERT INTO "DatosProcesoAspirante" (
      "IdRegistroPersonal",
      "FechaProceso",
      "IdTipoCargo",
      "HaTrabajadoAntesEmpresa",
      "AntecedentesMedicos",
      "Medicamentos",
      "FechaCreacion",
      "FechaActualizacion"
    ) VALUES (
      :id_registro_personal,
      :fecha_proceso,
      :id_tipo_cargo,
      :ha_trabajado_antes_empresa,
      :antecedentes_medicos,
      :medicamentos,
      now(),
      now()
    )
    ON CONFLICT ("IdRegistroPersonal") DO UPDATE SET
      "FechaProceso" = COALESCE(EXCLUDED."FechaProceso", "DatosProcesoAspirante"."FechaProceso"),
      "IdTipoCargo" = COALESCE(EXCLUDED."IdTipoCargo", "DatosProcesoAspirante"."IdTipoCargo"),
      "HaTrabajadoAntesEmpresa" = COALESCE(EXCLUDED."HaTrabajadoAntesEmpresa", "DatosProcesoAspirante"."HaTrabajadoAntesEmpresa"),
      "AntecedentesMedicos" = COALESCE(EXCLUDED."AntecedentesMedicos", "DatosProcesoAspirante"."AntecedentesMedicos"),
      "Medicamentos" = COALESCE(EXCLUDED."Medicamentos", "DatosProcesoAspirante"."Medicamentos"),
      "FechaActualizacion" = now()
    RETURNING
      "IdRegistroPersonal"      AS id_registro_personal,
      "FechaProceso"            AS fecha_proceso,
      "IdTipoCargo"             AS id_tipo_cargo,
      "HaTrabajadoAntesEmpresa" AS ha_trabajado_antes_empresa,
      "AntecedentesMedicos"     AS antecedentes_medicos,
      "Medicamentos"            AS medicamentos
    '''

    params = {
        "id_registro_personal": id_registro_personal,
        "fecha_proceso": data.fecha_proceso,
        "id_tipo_cargo": data.id_tipo_cargo,
        "ha_trabajado_antes_empresa": data.ha_trabajado_antes_empresa,
        "antecedentes_medicos": data.antecedentes_medicos,
        "medicamentos": data.medicamentos,
    }

    try:
        row = db.execute(text(sql), params).mappings().first()
        db.commit()
        return dict(row)
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Error upsert datos-proceso-aspirante: {str(e)}")
