from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import text
from infrastructure.db.deps import get_db
from pydantic import BaseModel
from datetime import datetime, timedelta

from utilidades.reporte_synergy_excel import (
    consultar_datos_reporte_synergy,
    normalizar_filas_reporte,
    generar_excel_reporte,
    enriquecer_filas_para_sheet_con_cargo,
)

from utilidades.drive_service import (
    subir_archivo_drive,
    sincronizar_registro_contratacion_dotacion,
)

router = APIRouter(prefix="/api", tags=["Contratación - Contratado"])

ESTADO_CONTRATADO = 25  # ✅ según tu tabla EstadoProceso


class ContratadoUpdate(BaseModel):
    IdRegistroPersonal: int


@router.put("/contratado")
def marcar_contratado(payload: ContratadoUpdate, db: Session = Depends(get_db)):
    # 1) Validar que exista el aspirante
    existe = db.execute(
        text('SELECT 1 FROM public."RegistroPersonal" WHERE "IdRegistroPersonal" = :id'),
        {"id": payload.IdRegistroPersonal},
    ).fetchone()

    if not existe:
        raise HTTPException(status_code=404, detail="IdRegistroPersonal no existe en RegistroPersonal.")

    try:
        # 2) Actualizar estado a CONTRATADO
        updated = db.execute(
            text("""
                UPDATE public."RegistroPersonal"
                SET "IdEstadoProceso" = :estado
                WHERE "IdRegistroPersonal" = :id_registro
                RETURNING "IdRegistroPersonal", "IdEstadoProceso";
            """),
            {"estado": ESTADO_CONTRATADO, "id_registro": payload.IdRegistroPersonal},
        ).mappings().first()

        db.commit()

        hoy = datetime.now().date()
        hace_30_dias = hoy - timedelta(days=800)

        rows = consultar_datos_reporte_synergy(
            db,
            hace_30_dias.strftime("%Y-%m-%d"),
            hoy.strftime("%Y-%m-%d")
        )
        filas = normalizar_filas_reporte(rows)

        filas_excel = filas if filas else [{"sin_datos": "No hay registros"}]
        filas_sheet = enriquecer_filas_para_sheet_con_cargo(db, filas_excel)

        ruta_archivo = generar_excel_reporte(filas_excel)

        archivo_drive = None
        nombre_archivo = None
        archivo_sheet = None

        if ruta_archivo:
            nombre_archivo = ruta_archivo.split("\\")[-1].split("/")[-1]
            archivo_drive = subir_archivo_drive(ruta_archivo, nombre_archivo)

        archivo_sheet = sincronizar_registro_contratacion_dotacion(filas_sheet)

        return {
            "message": "Aspirante marcado como CONTRATADO.",
            "data": updated,
            "archivoGenerado": nombre_archivo,
            "archivoDrive": {
                "id": archivo_drive["id"] if archivo_drive else None,
                "name": archivo_drive["name"] if archivo_drive else None,
                "webViewLink": archivo_drive["webViewLink"] if archivo_drive else None,
            },
            "archivoSheet": {
                "id": archivo_sheet["id"] if archivo_sheet else None,
                "name": archivo_sheet["name"] if archivo_sheet else None,
                "webViewLink": archivo_sheet["webViewLink"] if archivo_sheet else None,
            }
        }

    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Error BD: {str(e)}")