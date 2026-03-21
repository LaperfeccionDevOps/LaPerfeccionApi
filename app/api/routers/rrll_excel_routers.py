from datetime import datetime
from io import BytesIO

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from sqlalchemy import text
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
        ws.merge_cells("A1:M1")
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
            "FECHA LEGALIZADOR",
            "NUMERO DE IDENTIFICACION",
            "NOMBRE",
            "APELLIDO",
            "CARGO",
            "SEDE",
            "FECHA DE INGRESO",
            "FECHA DE RETIRO",
            "TOTAL TIEMPO DE TRABAJO",
            "RETIRO LEGALIZADO",
            "DESCRIPCIÓN MOTIVO ESPECIFICO DEL RETIRO",
            "TIPIFICACION DE RETIRO",
            "OBSERVACION ¿QUÉ DEBE MEJORAR LA COMPAÑÍA?"
        ]

        header_row = 5
        fill_header = PatternFill(
            fill_type="solid",
            start_color="D9EAD3",
            end_color="D9EAD3"
        )

        thin_side = Side(style="thin", color="B7B7B7")
        border_tabla = Border(
        left=thin_side,
        right=thin_side,
        top=thin_side,
        bottom=thin_side
)

        for col_num, header in enumerate(headers, start=1):
            cell = ws.cell(row=header_row, column=col_num, value=header)
            cell.font = Font(bold=True)
            cell.fill = fill_header
            cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
            cell.border = border_tabla

        # Datos reales desde la función SQL
        q = text("""
            SELECT *
            FROM public.fn_reporte_retiros_excel(:fecha_inicio, :fecha_fin)
        """)

        resultados = db.execute(q, {
            "fecha_inicio": fecha_inicio,
            "fecha_fin": fecha_fin
        }).mappings().all()

        datos = [
            [
                row["fecha_legalizador"],
                row["numero_identificacion"],
                row["nombre"],
                row["apellido"],
                row["cargo"],
                row["sede"],
                row["fecha_ingreso"],
                row["fecha_retiro"],
                row["total_tiempo_de_trabajo"],
                row["retiro_legalizado"],
                row["descripcion_motivo_especifico_del_retiro"],
                row["tipificacion_de_retiro"],
                row["observacion_que_debe_mejorar_la_compania"],
            ]
            for row in resultados
        ]

        fila_datos_inicio = header_row + 1

        for fila in datos:
            ws.append(fila)

        fila_datos_fin = header_row + len(datos)
        ws.auto_filter.ref = f"A{header_row}:M{fila_datos_fin}"

        ws.freeze_panes = "A6"

        for row in ws.iter_rows(min_row=header_row, max_row=fila_datos_fin, min_col=1, max_col=len(headers)):
         for cell in row:
          cell.border = border_tabla

        # Centrar algunas columnas
        columnas_centradas = ["A", "B", "G", "H", "I", "J", "L"]
        for row_num in range(fila_datos_inicio, fila_datos_inicio + len(datos)):
            for col in columnas_centradas:
                ws[f"{col}{row_num}"].alignment = Alignment(horizontal="center", vertical="center")

        # Ajuste manual de anchos
        anchos = {
            "A": 20,
            "B": 24,
            "C": 22,
            "D": 22,
            "E": 28,
            "F": 32,
            "G": 20,
            "H": 20,
            "I": 22,
            "J": 18,
            "K": 40,
            "L": 30,
            "M": 45,
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