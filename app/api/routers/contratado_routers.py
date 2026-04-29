from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import text
from infrastructure.db.deps import get_db
from pydantic import BaseModel
from datetime import datetime, timedelta
import traceback

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

ESTADO_CONTRATADO = 25  # según tabla EstadoProceso


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
        raise HTTPException(
            status_code=404,
            detail="IdRegistroPersonal no existe en RegistroPersonal."
        )

    try:
        print("=== INICIO /api/contratado ===")
        print("IdRegistroPersonal:", payload.IdRegistroPersonal)

        # 2) Actualizar estado a CONTRATADO
        print("1. Antes de UPDATE RegistroPersonal")
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

        print("2. Resultado UPDATE:", updated)

        db.commit()
        print("3. Commit BD exitoso")

        hoy = datetime.now().date()
        hace_800_dias = hoy - timedelta(days=800)

        print("4. Consultando datos reporte synergy")
        print("   Fecha inicio:", hace_800_dias.strftime("%Y-%m-%d"))
        print("   Fecha fin:", hoy.strftime("%Y-%m-%d"))

        rows = consultar_datos_reporte_synergy(
            db,
            hace_800_dias.strftime("%Y-%m-%d"),
            hoy.strftime("%Y-%m-%d")
        )
        print("5. Rows obtenidas:", len(rows) if rows else 0)

        filas = normalizar_filas_reporte(rows)
        print("6. Filas normalizadas:", len(filas) if filas else 0)

        filas_excel = filas if filas else [{"sin_datos": "No hay registros"}]
        print("7. Filas para excel:", len(filas_excel) if filas_excel else 0)

        print("8. Enriqueciendo filas para sheet")
        filas_sheet = enriquecer_filas_para_sheet_con_cargo(db, filas_excel)
        print("9. Filas para sheet:", len(filas_sheet) if filas_sheet else 0)

        print("10. Generando excel")
        ruta_archivo = generar_excel_reporte(filas_excel)
        print("11. Ruta archivo:", ruta_archivo)

        archivo_drive = None
        nombre_archivo = None
        archivo_sheet = None

        if ruta_archivo:
            print("12. Preparando subida a Drive")
            nombre_archivo = ruta_archivo.split("\\")[-1].split("/")[-1]
            print("13. Nombre archivo:", nombre_archivo)

            archivo_drive = subir_archivo_drive(ruta_archivo, nombre_archivo)
            print("14. Respuesta Drive:", archivo_drive)

        print("15. Sincronizando Google Sheet")
        archivo_sheet = sincronizar_registro_contratacion_dotacion(filas_sheet)
        print("16. Respuesta Sheet:", archivo_sheet)

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
        print("=== ERROR EN /api/contratado ===")
        print("TIPO:", type(e).__name__)
        print("MENSAJE:", str(e))
        traceback.print_exc()
        db.rollback()
        raise HTTPException(
            status_code=500,
            detail=f"Error en /api/contratado: {str(e)}"
        )