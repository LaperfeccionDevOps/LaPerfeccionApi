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


def enriquecer_filas_para_sheet_con_cargo(db, filas):
    if not filas:
        return filas

    ids_registro = []
    documentos = []

    for fila in filas:
        id_reg = fila.get("idregistropersonal") or fila.get("IdRegistroPersonal")
        if id_reg is not None:
            try:
                ids_registro.append(int(id_reg))
            except Exception:
                pass

        num_doc = (
            fila.get("num_doc_id")
            or fila.get("empleado")
            or fila.get("NumeroIdentificacion")
        )
        if num_doc is not None and str(num_doc).strip() != "":
            documentos.append(str(num_doc).strip())

    ids_registro = list(set(ids_registro))
    documentos = list(set(documentos))

    mapa_cargo_por_id = {}
    mapa_cargo_por_doc = {}

    if ids_registro:
        sql_ids = text("""
            SELECT
                acc."IdRegistroPersonal",
                cg."NombreCargo"
            FROM public."AsignacionCargoCliente" acc
            LEFT JOIN public."Cargo" cg
                ON cg."IdCargo" = acc."IdCargo"
            WHERE acc."IdRegistroPersonal" = ANY(:ids_registro)
        """)

        rows_ids = db.execute(
            sql_ids,
            {"ids_registro": ids_registro}
        ).mappings().all()

        for row in rows_ids:
            try:
                mapa_cargo_por_id[int(row["IdRegistroPersonal"])] = row.get("NombreCargo")
            except Exception:
                pass

    if documentos:
        sql_docs = text("""
            SELECT
                rp."NumeroIdentificacion",
                acc."IdRegistroPersonal",
                cg."NombreCargo"
            FROM public."RegistroPersonal" rp
            LEFT JOIN public."AsignacionCargoCliente" acc
                ON acc."IdRegistroPersonal" = rp."IdRegistroPersonal"
            LEFT JOIN public."Cargo" cg
                ON cg."IdCargo" = acc."IdCargo"
            WHERE CAST(rp."NumeroIdentificacion" AS TEXT) = ANY(:documentos)
        """)

        rows_docs = db.execute(
            sql_docs,
            {"documentos": documentos}
        ).mappings().all()

        for row in rows_docs:
            doc = row.get("NumeroIdentificacion")
            cargo = row.get("NombreCargo")
            if doc is not None and cargo:
                mapa_cargo_por_doc[str(doc).strip()] = cargo

    filas_enriquecidas = []

    for fila in filas:
        nueva = dict(fila)

        cargo_texto = None

        id_reg = nueva.get("idregistropersonal") or nueva.get("IdRegistroPersonal")
        if id_reg is not None:
            try:
                cargo_texto = mapa_cargo_por_id.get(int(id_reg))
            except Exception:
                pass

        if not cargo_texto:
            num_doc = (
                nueva.get("num_doc_id")
                or nueva.get("empleado")
                or nueva.get("NumeroIdentificacion")
            )
            if num_doc is not None:
                cargo_texto = mapa_cargo_por_doc.get(str(num_doc).strip())

        if cargo_texto:
            nueva["cargo"] = cargo_texto

        filas_enriquecidas.append(nueva)

    return filas_enriquecidas


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