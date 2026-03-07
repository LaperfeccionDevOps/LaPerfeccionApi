# app/api/routers/validaciones_routers.py

import json
from datetime import datetime
from typing import List

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from infrastructure.db.deps import get_db
from infrastructure.security.role_guard import require_roles_ids

from domain.schemas.validaciones import (
    ApiResponse,
    ValidacionExperienciaLaboralUpsert,
    ValidacionExperienciaLaboralOut,
    ValidacionReferenciaPersonalUpsert,
    ValidacionReferenciaPersonalOut,
    ValidacionesAspiranteOut,
)

router = APIRouter()

# Roles (IDs de tu BD)
ROL_SELECCION = 2
ROL_TALENTO_HUMANO = 13
ROL_CONTRATACION = 3
ROL_DESARROLLADOR = 15


def _as_jsonb(extra: dict) -> str:
    """Convierte dict a JSON válido para CAST(:Extra AS jsonb)."""
    return json.dumps(extra or {}, ensure_ascii=False)


# =========================================================
#   GET: EXPERIENCIA LABORAL + VALIDACIÓN (por aspirante)
# =========================================================
@router.get(
    "/validaciones/experiencia-laboral/aspirante/{id_registro}",
    response_model=ApiResponse[List[ValidacionExperienciaLaboralOut]],
)
def listar_validacion_experiencia_laboral_por_aspirante(
    id_registro: int,
    db: Session = Depends(get_db),
    current=Depends(
        require_roles_ids(ROL_SELECCION, ROL_TALENTO_HUMANO, ROL_CONTRATACION, ROL_DESARROLLADOR)
    ),
):
    try:
        sql = text("""
            SELECT
              e."IdExperienciaLaboral",
              e."IdRegistroPersonal",
              e."Cargo",
              e."Compania",
              e."TiempoDuracion",
              e."Funciones",
              e."JefeInmediato",
              e."TelefonoJefe",

              v."IdValidacionExperienciaLaboral",
              v."Concepto",
              v."DesempenoReportado",
              v."MotivoRetiroReal",
              v."PersonaQueReferencia",
              v."TelefonoPersonaQueReferencia",
              v."Observaciones",
              v."VerificadoPor",
              v."FechaValidacion",
              v."FechaActualizacion",
              v."EstadoValidacion",
              v."Extra"
            FROM "ExperienciaLaboral" e
            LEFT JOIN "ValidacionExperienciaLaboral" v
              ON v."IdExperienciaLaboral" = e."IdExperienciaLaboral"
            WHERE e."IdRegistroPersonal" = :id_registro
            ORDER BY e."IdExperienciaLaboral" DESC
        """)
        rows = db.execute(sql, {"id_registro": id_registro}).mappings().all()
        data = [dict(r) for r in rows]
        return {"ok": True, "message": "OK", "data": data}
    except SQLAlchemyError as e:
        raise HTTPException(status_code=500, detail=f"Error listando validaciones experiencia laboral: {str(e)}")


# =========================================================
#   PUT: UPSERT VALIDACIÓN EXPERIENCIA LABORAL (y retorna el registro)
# =========================================================
@router.put(
    "/validaciones/experiencia-laboral/{id_experiencia}",
    response_model=ApiResponse[ValidacionExperienciaLaboralOut],
)
def upsert_validacion_experiencia_laboral(
    id_experiencia: int,
    payload: ValidacionExperienciaLaboralUpsert,
    db: Session = Depends(get_db),
    current=Depends(
        require_roles_ids(ROL_SELECCION, ROL_TALENTO_HUMANO, ROL_CONTRATACION, ROL_DESARROLLADOR)
    ),
):
    try:
        ahora = datetime.utcnow()

        # 1) Existe experiencia + traemos IdRegistroPersonal
        exp_sql = text("""
            SELECT "IdRegistroPersonal"
            FROM "ExperienciaLaboral"
            WHERE "IdExperienciaLaboral" = :id
            LIMIT 1
        """)
        exp = db.execute(exp_sql, {"id": id_experiencia}).mappings().first()
        if not exp:
            raise HTTPException(status_code=404, detail="ExperienciaLaboral no encontrada")

        id_registro = exp["IdRegistroPersonal"]

        # 2) Upsert
        upsert_sql = text("""
            INSERT INTO "ValidacionExperienciaLaboral" (
              "IdExperienciaLaboral",
              "IdRegistroPersonal",
              "Concepto",
              "DesempenoReportado",
              "MotivoRetiroReal",
              "PersonaQueReferencia",
              "TelefonoPersonaQueReferencia",
              "Observaciones",
              "VerificadoPor",
              "FechaValidacion",
              "FechaActualizacion",
              "EstadoValidacion",
              "Extra"
            ) VALUES (
              :IdExperienciaLaboral,
              :IdRegistroPersonal,
              :Concepto,
              :DesempenoReportado,
              :MotivoRetiroReal,
              :PersonaQueReferencia,
              :TelefonoPersonaQueReferencia,
              :Observaciones,
              :VerificadoPor,
              now(),
              :FechaActualizacion,
              :EstadoValidacion,
              CAST(:Extra AS jsonb)
            )
            ON CONFLICT ("IdExperienciaLaboral")
            DO UPDATE SET
              "Concepto" = EXCLUDED."Concepto",
              "DesempenoReportado" = EXCLUDED."DesempenoReportado",
              "MotivoRetiroReal" = EXCLUDED."MotivoRetiroReal",
              "PersonaQueReferencia" = EXCLUDED."PersonaQueReferencia",
              "TelefonoPersonaQueReferencia" = EXCLUDED."TelefonoPersonaQueReferencia",
              "Observaciones" = EXCLUDED."Observaciones",
              "VerificadoPor" = EXCLUDED."VerificadoPor",
              "FechaActualizacion" = EXCLUDED."FechaActualizacion",
              "EstadoValidacion" = EXCLUDED."EstadoValidacion",
              "Extra" = EXCLUDED."Extra"
        """)

        db.execute(
            upsert_sql,
            {
                "IdExperienciaLaboral": id_experiencia,
                "IdRegistroPersonal": id_registro,
                "Concepto": payload.Concepto,
                "DesempenoReportado": payload.DesempenoReportado,
                "MotivoRetiroReal": payload.MotivoRetiroReal,
                "PersonaQueReferencia": payload.PersonaQueReferencia,
                "TelefonoPersonaQueReferencia": payload.TelefonoPersonaQueReferencia,
                "Observaciones": payload.Observaciones,
                "VerificadoPor": payload.VerificadoPor,
                "FechaActualizacion": ahora,
                "EstadoValidacion": payload.EstadoValidacion or "PENDIENTE",
                "Extra": _as_jsonb(payload.Extra or {}),
            },
        )
        db.commit()

        # 3) Retornamos registro listo para el front
        select_sql = text("""
            SELECT
              e."IdExperienciaLaboral",
              e."IdRegistroPersonal",
              e."Cargo",
              e."Compania",
              e."TiempoDuracion",
              e."Funciones",
              e."JefeInmediato",
              e."TelefonoJefe",
              v."IdValidacionExperienciaLaboral",
              v."Concepto",
              v."DesempenoReportado",
              v."MotivoRetiroReal",
              v."PersonaQueReferencia",
              v."TelefonoPersonaQueReferencia",
              v."Observaciones",
              v."VerificadoPor",
              v."FechaValidacion",
              v."FechaActualizacion",
              v."EstadoValidacion",
              v."Extra"
            FROM "ExperienciaLaboral" e
            LEFT JOIN "ValidacionExperienciaLaboral" v
              ON v."IdExperienciaLaboral" = e."IdExperienciaLaboral"
            WHERE e."IdExperienciaLaboral" = :id
            LIMIT 1
        """)
        row = db.execute(select_sql, {"id": id_experiencia}).mappings().first()
        return {"ok": True, "message": "Validación guardada", "data": dict(row)}

    except HTTPException:
        raise
    except SQLAlchemyError as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Error guardando validación experiencia laboral: {str(e)}")


# =========================================================
#   GET: REFERENCIAS PERSONALES + VALIDACIÓN (por aspirante)
# =========================================================
@router.get(
    "/validaciones/referencias-personales/aspirante/{id_registro}",
    response_model=ApiResponse[List[ValidacionReferenciaPersonalOut]],
)
def listar_validacion_referencias_personales_por_aspirante(
    id_registro: int,
    db: Session = Depends(get_db),
    current=Depends(
        require_roles_ids(ROL_SELECCION, ROL_TALENTO_HUMANO, ROL_CONTRATACION, ROL_DESARROLLADOR)
    ),
):
    try:
        sql = text("""
            SELECT
              r."IdReferencia",
              r."IdRegistroPersonal",
              r."Nombre",
              r."Telefono",
              r."Ocupacion",

              v."IdValidacionReferenciaPersonal",
              v."ParentescoRelacion",
              v."TiempoConocerAspirante",
              v."HaceCuantoLoConoce",
              v."Descripcion",
              v."LugarVivienda",
              v."TieneHijos",
              v."Observaciones",
              v."VerificadoPor",
              v."FechaValidacion",
              v."FechaActualizacion",
              v."EstadoValidacion",
              v."Extra"
            FROM "Referencia" r
            LEFT JOIN "ValidacionReferenciaPersonal" v
              ON v."IdReferencia" = r."IdReferencia"
            WHERE r."IdRegistroPersonal" = :id_registro
            ORDER BY r."IdReferencia" DESC
        """)
        rows = db.execute(sql, {"id_registro": id_registro}).mappings().all()
        data = [dict(r) for r in rows]
        return {"ok": True, "message": "OK", "data": data}
    except SQLAlchemyError as e:
        raise HTTPException(status_code=500, detail=f"Error listando validaciones referencias personales: {str(e)}")


# =========================================================
#   PUT: UPSERT VALIDACIÓN REFERENCIA PERSONAL (y retorna el registro)
# =========================================================
@router.put(
    "/validaciones/referencias-personales/{id_referencia}",
    response_model=ApiResponse[ValidacionReferenciaPersonalOut],
)
def upsert_validacion_referencia_personal(
    id_referencia: int,
    payload: ValidacionReferenciaPersonalUpsert,
    db: Session = Depends(get_db),
    current=Depends(
        require_roles_ids(ROL_SELECCION, ROL_TALENTO_HUMANO, ROL_CONTRATACION, ROL_DESARROLLADOR)
    ),
):
    try:
        ahora = datetime.utcnow()

        ref_sql = text("""
            SELECT "IdRegistroPersonal"
            FROM "Referencia"
            WHERE "IdReferencia" = :id
            LIMIT 1
        """)
        ref = db.execute(ref_sql, {"id": id_referencia}).mappings().first()
        if not ref:
            raise HTTPException(status_code=404, detail="Referencia no encontrada")

        id_registro = ref["IdRegistroPersonal"]

        upsert_sql = text("""
            INSERT INTO "ValidacionReferenciaPersonal" (
              "IdReferencia",
              "IdRegistroPersonal",
              "ParentescoRelacion",
              "TiempoConocerAspirante",
              "HaceCuantoLoConoce",
              "Descripcion",
              "LugarVivienda",
              "TieneHijos",
              "Observaciones",
              "VerificadoPor",
              "FechaValidacion",
              "FechaActualizacion",
              "EstadoValidacion",
              "Extra"
            ) VALUES (
              :IdReferencia,
              :IdRegistroPersonal,
              :ParentescoRelacion,
              :TiempoConocerAspirante,
              :HaceCuantoLoConoce,
              :Descripcion,
              :LugarVivienda,
              :TieneHijos,
              :Observaciones,
              :VerificadoPor,
              now(),
              :FechaActualizacion,
              :EstadoValidacion,
              CAST(:Extra AS jsonb)
            )
            ON CONFLICT ("IdReferencia")
            DO UPDATE SET
              "ParentescoRelacion" = EXCLUDED."ParentescoRelacion",
              "TiempoConocerAspirante" = EXCLUDED."TiempoConocerAspirante",
              "HaceCuantoLoConoce" = EXCLUDED."HaceCuantoLoConoce",
              "Descripcion" = EXCLUDED."Descripcion",
              "LugarVivienda" = EXCLUDED."LugarVivienda",
              "TieneHijos" = EXCLUDED."TieneHijos",
              "Observaciones" = EXCLUDED."Observaciones",
              "VerificadoPor" = EXCLUDED."VerificadoPor",
              "FechaActualizacion" = EXCLUDED."FechaActualizacion",
              "EstadoValidacion" = EXCLUDED."EstadoValidacion",
              "Extra" = EXCLUDED."Extra"
        """)

        db.execute(
            upsert_sql,
            {
                "IdReferencia": id_referencia,
                "IdRegistroPersonal": id_registro,
                "ParentescoRelacion": payload.ParentescoRelacion,
                "TiempoConocerAspirante": payload.TiempoConocerAspirante,
                "HaceCuantoLoConoce": payload.HaceCuantoLoConoce,
                "Descripcion": payload.Descripcion,
                "LugarVivienda": payload.LugarVivienda,
                "TieneHijos": payload.TieneHijos,
                "Observaciones": payload.Observaciones,
                "VerificadoPor": payload.VerificadoPor,
                "FechaActualizacion": ahora,
                "EstadoValidacion": payload.EstadoValidacion or "PENDIENTE",
                "Extra": _as_jsonb(payload.Extra or {}),
            },
        )
        db.commit()

        select_sql = text("""
            SELECT
              r."IdReferencia",
              r."IdRegistroPersonal",
              r."Nombre",
              r."Telefono",
              r."Ocupacion",
              v."IdValidacionReferenciaPersonal",
              v."ParentescoRelacion",
              v."TiempoConocerAspirante",
              v."HaceCuantoLoConoce",
              v."Descripcion",
              v."LugarVivienda",
              v."TieneHijos",
              v."Observaciones",
              v."VerificadoPor",
              v."FechaValidacion",
              v."FechaActualizacion",
              v."EstadoValidacion",
              v."Extra"
            FROM "Referencia" r
            LEFT JOIN "ValidacionReferenciaPersonal" v
              ON v."IdReferencia" = r."IdReferencia"
            WHERE r."IdReferencia" = :id
            LIMIT 1
        """)
        row = db.execute(select_sql, {"id": id_referencia}).mappings().first()
        return {"ok": True, "message": "Validación guardada", "data": dict(row)}

    except HTTPException:
        raise
    except SQLAlchemyError as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Error guardando validación referencia personal: {str(e)}")


# =========================================================
#   GET "COMBINADO": Todo lo de validaciones para un aspirante (para el front)
# =========================================================
@router.get(
    "/validaciones/aspirante/{id_registro}",
    response_model=ApiResponse[ValidacionesAspiranteOut],
)
def obtener_validaciones_aspirante(
    id_registro: int,
    db: Session = Depends(get_db),
    current=Depends(
        require_roles_ids(ROL_SELECCION, ROL_TALENTO_HUMANO, ROL_CONTRATACION, ROL_DESARROLLADOR)
    ),
):
    try:
        # Experiencia
        exp_sql = text("""
            SELECT
              e."IdExperienciaLaboral",
              e."IdRegistroPersonal",
              e."Cargo",
              e."Compania",
              e."TiempoDuracion",
              e."Funciones",
              e."JefeInmediato",
              e."TelefonoJefe",
              v."IdValidacionExperienciaLaboral",
              v."Concepto",
              v."DesempenoReportado",
              v."MotivoRetiroReal",
              v."PersonaQueReferencia",
              v."TelefonoPersonaQueReferencia",
              v."Observaciones",
              v."VerificadoPor",
              v."FechaValidacion",
              v."FechaActualizacion",
              v."EstadoValidacion",
              v."Extra"
            FROM "ExperienciaLaboral" e
            LEFT JOIN "ValidacionExperienciaLaboral" v
              ON v."IdExperienciaLaboral" = e."IdExperienciaLaboral"
            WHERE e."IdRegistroPersonal" = :id_registro
            ORDER BY e."IdExperienciaLaboral" DESC
        """)
        exp_rows = db.execute(exp_sql, {"id_registro": id_registro}).mappings().all()

        # Referencias personales
        ref_sql = text("""
            SELECT
              r."IdReferencia",
              r."IdRegistroPersonal",
              r."Nombre",
              r."Telefono",
              r."Ocupacion",
              v."IdValidacionReferenciaPersonal",
              v."ParentescoRelacion",
              v."TiempoConocerAspirante",
              v."HaceCuantoLoConoce",
              v."Descripcion",
              v."LugarVivienda",
              v."TieneHijos",
              v."Observaciones",
              v."VerificadoPor",
              v."FechaValidacion",
              v."FechaActualizacion",
              v."EstadoValidacion",
              v."Extra"
            FROM "Referencia" r
            LEFT JOIN "ValidacionReferenciaPersonal" v
              ON v."IdReferencia" = r."IdReferencia"
            WHERE r."IdRegistroPersonal" = :id_registro
            ORDER BY r."IdReferencia" DESC
        """)
        ref_rows = db.execute(ref_sql, {"id_registro": id_registro}).mappings().all()

        data = {
            "IdRegistroPersonal": id_registro,
            "ExperienciaLaboral": [dict(r) for r in exp_rows],
            "ReferenciasPersonales": [dict(r) for r in ref_rows],
        }
        return {"ok": True, "message": "OK", "data": data}

    except SQLAlchemyError as e:
        raise HTTPException(status_code=500, detail=f"Error obteniendo validaciones del aspirante: {str(e)}")
