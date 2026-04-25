# api/routers/datos_seleccion_routers.py
from datetime import datetime, timezone
from typing import Any, Optional
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Body
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
from sqlalchemy import text

from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill
from openpyxl.chart import PieChart, Reference, LineChart, BarChart
from openpyxl.chart.label import DataLabelList

from domain.schemas.registro_personal_update_schema import RegistroPersonalUpdateRequest
from repositories.registro_personal_repo import RegistroPersonalRepository
from infrastructure.db.deps import get_db
from services.datos_seleccion_service import DatosSeleccionService
from domain.schemas.datos_seleccion_schema import (
    DatosSeleccionUpsertRequest,
    DatosSeleccionResponse,
)


router = APIRouter(prefix="/api/datos-seleccion", tags=["datos-seleccion"])
service = DatosSeleccionService()
registro_personal_repo = RegistroPersonalRepository()


@router.put("/registro-personal/{id_registro_personal}")
def actualizar_registro_personal(
    id_registro_personal: int,
    body: RegistroPersonalUpdateRequest = Body(...),
    db: Session = Depends(get_db)
):
    data = body.model_dump(exclude_none=True)
    if not data:
        raise HTTPException(status_code=400, detail="No hay datos para actualizar")

    data_registro = {
        k: v for k, v in data.items()
        if k not in ("DireccionDatosAdicionales", "IdGrupoSanguineo")
    }

    if data_registro:
        updated = registro_personal_repo.update_by_id(db, id_registro_personal, data_registro)
        if updated == 0:
            raise HTTPException(status_code=404, detail="No se encontró el registro personal")

    if "DireccionDatosAdicionales" in data:
        updated_datos = registro_personal_repo.update_direccion_datos_adicionales(
            db,
            id_registro_personal,
            data["DireccionDatosAdicionales"],
            data.get("IdGrupoSanguineo", 0)
        )
        if updated_datos == 0:
            raise HTTPException(status_code=404, detail="No se encontró DatosAdicionales para este registro personal")

    return {"ok": True, "message": "Registro actualizado", "IdRegistroPersonal": id_registro_personal}


def _parse_bool(value: Any) -> Optional[bool]:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        s = value.strip().lower()
        if s in ("si", "sí", "true", "1"):
            return True
        if s in ("no", "false", "0"):
            return False
    return None


@router.get("/reporte-excel")
def generar_reporte_excel_seleccion(db: Session = Depends(get_db)):
    rows = db.execute(text("""
        SELECT
            rp."Nombres",
            rp."Apellidos",
            rp."NumeroIdentificacion" as cedula,
            COALESCE(rp."Celular", '') as telefono,
            COALESCE(rp."Email", '') as correo,
            cg."NombreCargo" as cargo,
            rp."FechaCreacion" as fecha_registro,
            mcp."MotivoCierre" as motivo_rechazo,
            CASE rp."IdEstadoProceso"
                WHEN 18 THEN 'Nuevo'
                WHEN 19 THEN 'Entrevista'
                WHEN 20 THEN 'Entrevista jefe inmediato'
                WHEN 21 THEN 'Exámenes'
                WHEN 22 THEN 'Seguridad'
                WHEN 24 THEN 'Avanza a contratación'
                WHEN 25 THEN 'Contratado'
                WHEN 26 THEN 'Referenciación'
                WHEN 27 THEN 'Desiste del proceso'
                WHEN 28 THEN 'Rechazado'
                WHEN 30 THEN 'Abierto'
                ELSE CONCAT('Estado ', rp."IdEstadoProceso")
            END as estado
        FROM public."RegistroPersonal" rp
        LEFT JOIN public."AsignacionCargoCliente" acc
            ON acc."IdRegistroPersonal" = rp."IdRegistroPersonal"
        LEFT JOIN public."Cargo" cg
            ON cg."IdCargo" = acc."IdCargo"
        LEFT JOIN (
            SELECT DISTINCT ON ("IdRegistroPersonal")
                "IdRegistroPersonal",
                "MotivoCierre",
                "FechaCreacion"
            FROM public."MotivoCierreProceso"
            ORDER BY "IdRegistroPersonal", "FechaCreacion" DESC
        ) mcp
            ON mcp."IdRegistroPersonal" = rp."IdRegistroPersonal"
    """)).mappings().all()

    filas = [dict(r) for r in rows]

    if not filas:
        raise HTTPException(status_code=404, detail="No hay datos")

    wb = Workbook()
    ws = wb.active
    ws.title = "Reporte"

    headers = list(filas[0].keys())
    ws.append(headers)

    header_fill = PatternFill("solid", fgColor="1F4E78")
    header_font = Font(bold=True, color="FFFFFF")

    for col in range(1, len(headers) + 1):
        cell = ws.cell(row=1, column=col)
        cell.font = header_font
        cell.fill = header_fill

    for fila in filas:
        fila_limpia = {}
        for key, value in fila.items():
            if isinstance(value, datetime):
                value = value.replace(tzinfo=None)
            fila_limpia[key] = value

        ws.append(list(fila_limpia.values()))

    ws.auto_filter.ref = ws.dimensions
    ws.freeze_panes = "A2"

    for column_cells in ws.columns:
        max_length = 0
        column_letter = column_cells[0].column_letter
        for cell in column_cells:
            if cell.value is not None:
                max_length = max(max_length, len(str(cell.value)))
        ws.column_dimensions[column_letter].width = max_length + 3

    total = len(filas)
    rechazados = len([f for f in filas if str(f.get("estado", "")).strip().lower() == "rechazado"])
    contratados = len([f for f in filas if str(f.get("estado", "")).strip().lower() == "contratado"])
    avanza = len([f for f in filas if str(f.get("estado", "")).strip().lower() == "avanza a contratación"])

    porcentaje_contratacion = round((contratados / total) * 100) if total else 0
    porcentaje_rechazo = round((rechazados / total) * 100) if total else 0

    motivos_rechazo = {}

    for fila in filas:
        estado = str(fila.get("estado", "")).strip().lower()
        motivo = fila.get("motivo_rechazo")

        if estado == "rechazado" and motivo and str(motivo).strip().upper() != "SIN_MOTIVO":
            motivo = str(motivo).strip()
            motivos_rechazo[motivo] = motivos_rechazo.get(motivo, 0) + 1

    tendencia_mensual = {}

    meses = {
        1: "enero", 2: "febrero", 3: "marzo", 4: "abril",
        5: "mayo", 6: "junio", 7: "julio", 8: "agosto",
        9: "septiembre", 10: "octubre", 11: "noviembre", 12: "diciembre"
    }

    for fila in filas:
        fecha = fila.get("fecha_registro")

        if isinstance(fecha, datetime):
            clave_orden = fecha.strftime("%Y-%m")
            etiqueta_mes = f"{meses[fecha.month]}-{str(fecha.year)[-2:]}"
        else:
            clave_orden = "9999-99"
            etiqueta_mes = "Sin fecha"

        if clave_orden not in tendencia_mensual:
            tendencia_mensual[clave_orden] = {
                "etiqueta": etiqueta_mes,
                "cantidad": 0
            }

        tendencia_mensual[clave_orden]["cantidad"] += 1

    tendencia_mensual = dict(sorted(tendencia_mensual.items()))

    ws_dash = wb.create_sheet("Dashboard")

    ws_dash["A1"] = "Dashboard Selección"
    ws_dash["A1"].font = Font(bold=True, size=18)

    dash_fill = PatternFill("solid", fgColor="70AD47")
    dash_font = Font(bold=True, color="FFFFFF")
    kpi_fill = PatternFill("solid", fgColor="E2F0D9")
    kpi_title_font = Font(bold=True, color="375623", size=11)
    kpi_value_font = Font(bold=True, color="000000", size=16)

    ws_dash["A2"] = "Total candidatos"
    ws_dash["B2"] = total
    ws_dash["D2"] = "Contratación"
    ws_dash["E2"] = f"{porcentaje_contratacion}%"
    ws_dash["G2"] = "Rechazo"
    ws_dash["H2"] = f"{porcentaje_rechazo}%"

    for cell_ref in ["A2", "D2", "G2"]:
        ws_dash[cell_ref].fill = kpi_fill
        ws_dash[cell_ref].font = kpi_title_font

    for cell_ref in ["B2", "E2", "H2"]:
        ws_dash[cell_ref].fill = kpi_fill
        ws_dash[cell_ref].font = kpi_value_font

    ws_dash["A4"] = "Resumen general"
    ws_dash["A4"].font = Font(bold=True, size=12)

    ws_dash["A5"] = "Métrica"
    ws_dash["B5"] = "Valor"

    for col in ["A", "B"]:
        cell = ws_dash[f"{col}5"]
        cell.fill = dash_fill
        cell.font = dash_font

    ws_dash["A6"] = "Total registros"
    ws_dash["B6"] = total

    ws_dash["A7"] = "Rechazados"
    ws_dash["B7"] = rechazados

    ws_dash["A8"] = "Avanza a contratación"
    ws_dash["B8"] = avanza

    ws_dash["A9"] = "Contratados"
    ws_dash["B9"] = contratados

    ws_dash["J2"] = "Registros por mes"
    ws_dash["J2"].font = Font(bold=True, size=12)

    ws_dash["J3"] = "Mes"
    ws_dash["K3"] = "Registros"

    for col in ["J", "K"]:
        cell = ws_dash[f"{col}3"]
        cell.fill = dash_fill
        cell.font = dash_font

    fila_tendencia = 4
    for _, item in tendencia_mensual.items():
        ws_dash[f"J{fila_tendencia}"] = item["etiqueta"]
        ws_dash[f"K{fila_tendencia}"] = item["cantidad"]
        fila_tendencia += 1

    if fila_tendencia > 5:
        line = LineChart()
        line.style = 2
        line.title = "Evolución mensual de candidatos registrados"
        line.y_axis.title = "Cantidad de registros"
        line.x_axis.title = "Mes"

        data_line = Reference(ws_dash, min_col=11, min_row=4, max_row=fila_tendencia - 1)
        labels_line = Reference(ws_dash, min_col=10, min_row=4, max_row=fila_tendencia - 1)

        line.add_data(data_line, titles_from_data=False, from_rows=False)
        line.set_categories(labels_line)

        line.series = line.series[:1]
        line.series[0].graphicalProperties.line.solidFill = "70AD47"
        line.series[0].graphicalProperties.line.width = 30000
        line.series[0].marker.symbol = "circle"
        line.series[0].marker.size = 8
        line.series[0].marker.graphicalProperties.solidFill = "70AD47"

        line.dLbls = DataLabelList()
        line.dLbls.showVal = False
        line.dLbls.showSerName = False
        line.dLbls.showCatName = False

        line.legend = None
        line.smooth = False
        line.height = 8
        line.width = 22

        ws_dash.add_chart(line, "J10")

    pie = PieChart()
    pie.title = "Distribución de candidatos en estados finales"

    data = Reference(ws_dash, min_col=2, min_row=7, max_row=9)
    labels = Reference(ws_dash, min_col=1, min_row=7, max_row=9)

    pie.add_data(data, titles_from_data=False)
    pie.set_categories(labels)

    pie.dataLabels = DataLabelList()
    pie.dataLabels.showVal = False
    pie.dataLabels.showPercent = True
    pie.dataLabels.showCatName = False
    pie.dataLabels.showSerName = False
    pie.dataLabels.showLeaderLines = True

    ws_dash.add_chart(pie, "A12")

    ws_dash["A33"] = "Distribución de candidatos en estados finales"
    ws_dash["A33"].font = Font(bold=True, size=14)

    estados_barra = [
        {"estado": "Rechazados", "cantidad": rechazados, "color": "4F81BD"},
        {"estado": "Avanza a contratación", "cantidad": avanza, "color": "C0504D"},
        {"estado": "Contratados", "cantidad": contratados, "color": "9BBB59"},
    ]

    estados_barra = sorted(estados_barra, key=lambda x: x["cantidad"], reverse=True)

    ws_dash["A34"] = "Estado"
    ws_dash["B34"] = "Cantidad"
    ws_dash["C34"] = "%"

    for col in ["A", "B", "C"]:
        cell = ws_dash[f"{col}34"]
        cell.fill = dash_fill
        cell.font = dash_font

    fila_barra = 35
    for item in estados_barra:
        porcentaje = round((item["cantidad"] / total) * 100) if total else 0
        ws_dash[f"A{fila_barra}"] = item["estado"]
        ws_dash[f"B{fila_barra}"] = item["cantidad"]
        ws_dash[f"C{fila_barra}"] = f"{porcentaje}%"
        fila_barra += 1

    bar = BarChart()
    bar.type = "bar"
    bar.style = 10
    bar.title = None
    bar.y_axis.title = None
    bar.x_axis.title = None

    data_bar = Reference(ws_dash, min_col=2, min_row=34, max_row=37)
    labels_bar = Reference(ws_dash, min_col=1, min_row=35, max_row=37)

    bar.add_data(data_bar, titles_from_data=True)
    bar.set_categories(labels_bar)

    bar.legend = None

    bar.dLbls = DataLabelList()
    bar.dLbls.showVal = True
    bar.dLbls.showSerName = False
    bar.dLbls.showCatName = False
    bar.dLbls.showLegendKey = False

    bar.height = 8
    bar.width = 16

    bar.y_axis.majorGridlines = None
    bar.x_axis.majorGridlines = None

    if bar.series:
        for idx, item in enumerate(estados_barra):
            try:
                bar.series[0].data_points[idx].graphicalProperties.solidFill = item["color"]
            except Exception:
                pass

    ws_dash.add_chart(bar, "D33")

    ws_dash["A50"] = "Motivos de rechazo"
    ws_dash["A50"].font = Font(bold=True, size=14)

    ws_dash["A51"] = "Motivo"
    ws_dash["B51"] = "Cantidad"
    ws_dash["C51"] = "%"
    ws_dash["D51"] = "Ref."

    for col in ["A", "B", "C", "D"]:
        cell = ws_dash[f"{col}51"]
        cell.fill = dash_fill
        cell.font = dash_font

    motivos_base = [
        "Desiste del Proceso",
        "No Cumple Perfil",
        "No asiste a Examenes Medicos",
        "Examenes No Aptos",
        "Documentacion Incompleta",
        "No asiste a Contratacion",
    ]

    equivalencias_motivos = {
        "DESISTE DEL PROCESO": "Desiste del Proceso",
        "NO CUMPLE PERFIL": "No Cumple Perfil",
        "NO ASISTE A EXAMENES MEDICOS": "No asiste a Examenes Medicos",
        "NO ASISTE A EXÁMENES MEDICOS": "No asiste a Examenes Medicos",
        "NO ASISTE A EXÁMENES MÉDICOS": "No asiste a Examenes Medicos",
        "EXAMENES NO APTOS": "Examenes No Aptos",
        "EXÁMENES NO APTOS": "Examenes No Aptos",
        "DOCUMENTACION INCOMPLETA": "Documentacion Incompleta",
        "DOCUMENTACIÓN INCOMPLETA": "Documentacion Incompleta",
        "NO ASISTE A CONTRATACION": "No asiste a Contratacion",
        "NO ASISTE A CONTRATACIÓN": "No asiste a Contratacion",
    }

    colores_motivos = {
        "Desiste del Proceso": "C0504D",
        "No Cumple Perfil": "4F81BD",
        "No asiste a Examenes Medicos": "F79646",
        "Examenes No Aptos": "8064A2",
        "Documentacion Incompleta": "9BBB59",
        "No asiste a Contratacion": "4BACC6",
    }

    motivos_normalizados = {motivo: 0 for motivo in motivos_base}

    for motivo, cantidad in motivos_rechazo.items():
        clave = str(motivo).strip().upper()
        motivo_final = equivalencias_motivos.get(clave, str(motivo).strip())

        if motivo_final not in motivos_normalizados:
            motivos_normalizados[motivo_final] = 0

        motivos_normalizados[motivo_final] += cantidad

    motivos_tabla = []
    for motivo, cantidad in motivos_normalizados.items():
        motivos_tabla.append({
            "motivo": motivo,
            "cantidad": cantidad,
            "color": colores_motivos.get(motivo, "70AD47")
        })

    motivos_tabla = sorted(
        motivos_tabla,
        key=lambda x: (x["cantidad"] == 0, -x["cantidad"], x["motivo"])
    )

    total_motivos = sum(item["cantidad"] for item in motivos_tabla)

    fila_motivo = 52
    for item in motivos_tabla:
        porcentaje = round((item["cantidad"] / total_motivos) * 100) if total_motivos else 0

        ws_dash[f"A{fila_motivo}"] = item["motivo"]
        ws_dash[f"B{fila_motivo}"] = item["cantidad"]
        ws_dash[f"C{fila_motivo}"] = f"{porcentaje}%"
        ws_dash[f"D{fila_motivo}"] = ""

        ws_dash[f"D{fila_motivo}"].fill = PatternFill("solid", fgColor=item["color"])

        fila_motivo += 1

    fila_grafica_inicio = fila_motivo + 2
    ws_dash[f"A{fila_grafica_inicio}"] = "Motivo grafica"
    ws_dash[f"B{fila_grafica_inicio}"] = "Cantidad"

    fila_grafica = fila_grafica_inicio + 1
    motivos_grafica = [item for item in motivos_tabla if item["cantidad"] > 0]

    for item in motivos_grafica:
        ws_dash[f"A{fila_grafica}"] = item["motivo"]
        ws_dash[f"B{fila_grafica}"] = item["cantidad"]
        fila_grafica += 1

    if motivos_grafica:
        bar_motivos = BarChart()
        bar_motivos.type = "bar"
        bar_motivos.style = 10
        bar_motivos.title = None
        bar_motivos.y_axis.title = None
        bar_motivos.x_axis.title = None

        data_motivos = Reference(
            ws_dash,
            min_col=2,
            min_row=fila_grafica_inicio,
            max_row=fila_grafica - 1
        )

        labels_motivos = Reference(
            ws_dash,
            min_col=1,
            min_row=fila_grafica_inicio + 1,
            max_row=fila_grafica - 1
        )

        bar_motivos.add_data(data_motivos, titles_from_data=True)
        bar_motivos.set_categories(labels_motivos)

        bar_motivos.legend = None

        bar_motivos.dLbls = DataLabelList()
        bar_motivos.dLbls.showVal = True
        bar_motivos.dLbls.showSerName = False
        bar_motivos.dLbls.showCatName = False
        bar_motivos.dLbls.showLegendKey = False

        bar_motivos.height = 8
        bar_motivos.width = 16

        bar_motivos.y_axis.majorGridlines = None
        bar_motivos.x_axis.majorGridlines = None

        if bar_motivos.series:
            for idx, item in enumerate(motivos_grafica):
                try:
                    bar_motivos.series[0].data_points[idx].graphicalProperties.solidFill = item["color"]
                except Exception:
                    pass

        ws_dash.add_chart(bar_motivos, "E50")

    ws_dash.column_dimensions["A"].width = 34
    ws_dash.column_dimensions["B"].width = 14
    ws_dash.column_dimensions["C"].width = 10
    ws_dash.column_dimensions["D"].width = 8
    ws_dash.column_dimensions["E"].width = 14
    ws_dash.column_dimensions["G"].width = 14
    ws_dash.column_dimensions["H"].width = 14
    ws_dash.column_dimensions["J"].width = 18
    ws_dash.column_dimensions["K"].width = 14

    ruta = Path("reporte_seleccion_backend.xlsx")
    wb.save(ruta)

    return FileResponse(
        path=ruta,
        filename="reporte_seleccion.xlsx",
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )


@router.get("/{id_registro_personal}", response_model=DatosSeleccionResponse)
def obtener_datos_seleccion(id_registro_personal: int, db: Session = Depends(get_db)):
    data = service.obtener_por_registro_personal(db, id_registro_personal)
    if not data:
        raise HTTPException(status_code=404, detail="No existen datos")

    if getattr(data, "FechaActualizacion", None) is None:
        data.FechaActualizacion = datetime.now(timezone.utc)

    return data


@router.post("/upsert", response_model=DatosSeleccionResponse)
def upsert_datos_seleccion(body: DatosSeleccionUpsertRequest, db: Session = Depends(get_db)):
    payload = body.model_dump(exclude_none=True)

    if "HaTrabajadoAntesEnLaEmpresa" in payload:
        parsed = _parse_bool(payload.get("HaTrabajadoAntesEnLaEmpresa"))
        if parsed is None:
            payload.pop("HaTrabajadoAntesEnLaEmpresa", None)
        else:
            payload["HaTrabajadoAntesEnLaEmpresa"] = parsed

    payload.pop("HaTrabajadoAntes", None)

    data = service.upsert(db, payload)

    if getattr(data, "FechaActualizacion", None) is None:
        data.FechaActualizacion = datetime.now(timezone.utc)

    return data