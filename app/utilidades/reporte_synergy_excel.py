from sqlalchemy import text
from openpyxl import Workbook
from openpyxl.styles import Font
from openpyxl.utils import get_column_letter
from datetime import datetime
from pathlib import Path


def consultar_datos_reporte_synergy(db, fecha_inicio: str, fecha_fin: str):
    sql = text("""
        SELECT *
        FROM public.fn_ReporteSinergy(:fecha_inicio, :fecha_fin);
    """)

    rows = db.execute(
        sql,
        {
            "fecha_inicio": fecha_inicio,
            "fecha_fin": fecha_fin
        }
    ).mappings().all()

    return rows


def normalizar_filas_reporte(rows):
    return [dict(row) for row in rows]


def generar_excel_reporte(filas):
    wb = Workbook()
    ws = wb.active
    ws.title = "Reporte"

    if not filas:
        return None

    # Encabezados
    headers = list(filas[0].keys())
    ws.append(headers)

    # Encabezados en negrilla
    for col_num in range(1, len(headers) + 1):
        ws.cell(row=1, column=col_num).font = Font(bold=True)

    # Datos
    for fila in filas:
        ws.append(list(fila.values()))

    # Filtros en encabezados
    ws.auto_filter.ref = ws.dimensions

    # Congelar primera fila
    ws.freeze_panes = "A2"

    # Ajustar ancho de columnas
    for col in ws.columns:
        max_length = 0
        col_letter = get_column_letter(col[0].column)

        for cell in col:
            try:
                if cell.value is not None:
                    max_length = max(max_length, len(str(cell.value)))
            except Exception:
                pass

        ws.column_dimensions[col_letter].width = max_length + 2

    # Nombre archivo
    nombre_archivo = "Registro_Dotacion_Actual.xlsx"

    # Guardado local temporal en app/dotacion
    base_dir = Path(__file__).resolve().parent.parent
    carpeta_dotacion = base_dir / "dotacion"
    carpeta_dotacion.mkdir(parents=True, exist_ok=True)

    ruta = carpeta_dotacion / nombre_archivo
    wb.save(str(ruta))

    return str(ruta)