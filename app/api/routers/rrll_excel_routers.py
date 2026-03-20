from datetime import datetime
from io import BytesIO

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment
from sqlalchemy.orm import Session

from infrastructure.db.deps import get_db


router = APIRouter(
    prefix="/api/rrll-excel",
    tags=["RRLL Excel"]
)


@router.get("/exportar-retiros")
def exportar_excel_retiros(
    fecha_inicio: str = Query(..., description="Fecha inicio en formato YYYY-MM-DD"),
    fecha_fin: str = Query(..., description="Fecha fin en formato YYYY-MM-DD"),
    db: Session = Depends(get_db)
):
    try:
        fecha_inicio_dt = datetime.strptime(fecha_inicio, "%Y-%m-%d")
        fecha_fin_dt = datetime.strptime(fecha_fin, "%Y-%m-%d")
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail="Las fechas deben estar en formato YYYY-MM-DD."
        )

    if fecha_inicio_dt > fecha_fin_dt:
        raise HTTPException(
            status_code=400,
            detail="La fecha de inicio no puede ser mayor que la fecha final."
        )

    try:
        wb = Workbook()
        ws = wb.active
        ws.title = "Retiros RRLL"

        # Título
        ws.merge_cells("A1:J1")
        ws["A1"] = "REPORTE RRLL - RETIROS"
        ws["A1"].font = Font(bold=True, size=14)
        ws["A1"].alignment = Alignment(horizontal="center", vertical="center")

        # Fechas filtro
        ws["A2"] = "Fecha inicio"
        ws["B2"] = fecha_inicio
        ws["A3"] = "Fecha fin"
        ws["B3"] = fecha_fin

        ws["A2"].font = Font(bold=True)
        ws["A3"].font = Font(bold=True)

        # Encabezados
        headers = [
            "IdRetiroLaboral",
            "IdRegistroPersonal",
            "Cliente",
            "MotivoRetiro",
            "FechaProceso",
            "FechaRetiro",
            "FechaCierre",
            "FechaEnvioNomina",
            "EstadoCasoRRLL",
            "ObservacionGeneral"
        ]

        header_row = 5
        fill_header = PatternFill(fill_type="solid", start_color="D9EAD3", end_color="D9EAD3")

        for col_num, header in enumerate(headers, start=1):
            cell = ws.cell(row=header_row, column=col_num, value=header)
            cell.font = Font(bold=True)
            cell.fill = fill_header
            cell.alignment = Alignment(horizontal="center", vertical="center")

        # Datos de prueba por ahora
        datos = [
            [1, 101, "Cliente Prueba", "Retiro voluntario", fecha_inicio, fecha_inicio, "", "", "ABIERTO", "Observación de prueba 1"],
            [2, 102, "Cliente Demo", "Terminación contrato", fecha_fin, fecha_fin, "", "", "CERRADO", "Observación de prueba 2"],
        ]

        for fila in datos:
            ws.append(fila)

        # Ajuste manual de anchos
        anchos = {
            "A": 18,
            "B": 18,
            "C": 25,
            "D": 25,
            "E": 18,
            "F": 18,
            "G": 18,
            "H": 20,
            "I": 18,
            "J": 35,
        }

        for col, ancho in anchos.items():
            ws.column_dimensions[col].width = ancho

        output = BytesIO()
        wb.save(output)
        output.seek(0)

        nombre_archivo = f"reporte_retiros_rrll_{fecha_inicio}_a_{fecha_fin}.xlsx"

        return StreamingResponse(
            output,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={
                "Content-Disposition": f'attachment; filename="{nombre_archivo}"'
            }
        )

    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Error al generar el Excel de retiros: {str(e)}"
        )