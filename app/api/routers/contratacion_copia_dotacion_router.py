from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from infrastructure.db.deps import get_db
from utilidades.reporte_synergy_excel import (
    consultar_datos_reporte_synergy,
    normalizar_filas_reporte,
    generar_excel_reporte,
)

router = APIRouter(prefix="/api/contratacion", tags=["Contratación - Copia Dotación"])


class CopiaDotacionRequest(BaseModel):
    fechaInicio: str
    fechaFin: str


@router.post("/reporte_synergy/copia-dotacion")
def probar_consulta_copia_dotacion(payload: CopiaDotacionRequest, db: Session = Depends(get_db)):
    rows = consultar_datos_reporte_synergy(db, payload.fechaInicio, payload.fechaFin)
    filas = normalizar_filas_reporte(rows)

    ruta_archivo = generar_excel_reporte(filas if filas else [{"sin_datos": "No hay registros"}])

    return {
        "ok": True,
        "totalFilas": len(filas),
        "archivoGenerado": ruta_archivo,
        "filas": filas
    }