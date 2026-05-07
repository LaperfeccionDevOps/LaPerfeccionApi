from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import text
from infrastructure.db.deps import get_db
from pydantic import BaseModel
from datetime import datetime, timedelta
import traceback
import logging

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
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[3]
LOG_DIR = BASE_DIR / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)

LOG_FILE = LOG_DIR / "contratado_debug.log"

logger = logging.getLogger("contratado_debug")
logger.setLevel(logging.INFO)

if not logger.handlers:
    handler = logging.FileHandler(LOG_FILE, encoding="utf-8")
    formatter = logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")
    handler.setFormatter(formatter)
    logger.addHandler(handler)

router = APIRouter(prefix="/api", tags=["Contratación - Contratado"])

ESTADO_CONTRATADO = 25


class ContratadoUpdate(BaseModel):
    IdRegistroPersonal: int


@router.put("/contratado")
def marcar_contratado(payload: ContratadoUpdate, db: Session = Depends(get_db)):
    existe = db.execute(
        text('SELECT 1 FROM public."RegistroPersonal" WHERE "IdRegistroPersonal" = :id'),
        {"id": payload.IdRegistroPersonal},
    ).fetchone()

    if not existe:
        raise HTTPException(
            status_code=404,
            detail="IdRegistroPersonal no existe en RegistroPersonal."
        )

    try:
        logger.info("=== INICIO /api/contratado ===")
        logger.info(f"IdRegistroPersonal: {payload.IdRegistroPersonal}")

        updated = db.execute(
            text("""
                UPDATE public."RegistroPersonal"
                SET "IdEstadoProceso" = :estado
                WHERE "IdRegistroPersonal" = :id_registro
                RETURNING "IdRegistroPersonal", "IdEstadoProceso";
            """),
            {
                "estado": ESTADO_CONTRATADO,
                "id_registro": payload.IdRegistroPersonal,
            },
        ).mappings().first()

        logger.info(f"Resultado UPDATE: {updated}")

        db.commit()
        logger.info("Commit BD exitoso")

        hoy = datetime.now().date()
        hace_800_dias = hoy - timedelta(days=800)
        fecha_fin_reporte = hoy + timedelta(days=90)

        logger.info("Consultando datos reporte synergy")
        logger.info(f"Fecha inicio: {hace_800_dias.strftime('%Y-%m-%d')}")
        logger.info(f"Fecha fin: {fecha_fin_reporte.strftime('%Y-%m-%d')}")

        rows = consultar_datos_reporte_synergy(
            db,
            hace_800_dias.strftime("%Y-%m-%d"),
            fecha_fin_reporte.strftime("%Y-%m-%d")
        )

        logger.info(f"Rows obtenidas: {len(rows) if rows else 0}")

        filas = normalizar_filas_reporte(rows)
        logger.info(f"Filas normalizadas: {len(filas) if filas else 0}")

        for fila in filas or []:
            if "1014178009" in str(fila):
                logger.info(f"ANDREA EN FILAS NORMALIZADAS: {fila}")

        filas_excel = filas if filas else [{"sin_datos": "No hay registros"}]
        logger.info(f"Filas para excel: {len(filas_excel) if filas_excel else 0}")

        filas_sheet = enriquecer_filas_para_sheet_con_cargo(db, filas_excel)
        logger.info(f"Filas para sheet: {len(filas_sheet) if filas_sheet else 0}")

        for fila in filas_sheet or []:
            if "1014178009" in str(fila):
                logger.info(f"ANDREA EN FILAS SHEET: {fila}")

        ruta_archivo = generar_excel_reporte(filas_excel)
        logger.info(f"Ruta archivo: {ruta_archivo}")

        archivo_drive = None
        nombre_archivo = None
        archivo_sheet = None
    

        if ruta_archivo:
            nombre_archivo = ruta_archivo.split("\\")[-1].split("/")[-1]
            logger.info(f"Nombre archivo: {nombre_archivo}")

            logger.info("Saltando subida de Excel a Drive temporalmente para no bloquear Sheet")
            archivo_drive = None

        logger.info("Sincronizando Google Sheet")
        archivo_sheet = sincronizar_registro_contratacion_dotacion(filas_sheet)
        logger.info(f"Respuesta Sheet: {archivo_sheet}")

        logger.info("=== FIN /api/contratado OK ===")

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
        logger.error("=== ERROR EN /api/contratado ===")
        logger.error(f"TIPO: {type(e).__name__}")
        logger.error(f"MENSAJE: {str(e)}")
        logger.error(traceback.format_exc())

        db.rollback()

        raise HTTPException(
            status_code=500,
            detail=f"Error en /api/contratado: {str(e)}"
        )