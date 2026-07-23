from datetime import datetime, date
from io import BytesIO
from collections import Counter

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.worksheet.datavalidation import DataValidation
from openpyxl.chart import BarChart, PieChart, Reference
from openpyxl.chart.label import DataLabelList
from sqlalchemy import text
from sqlalchemy.orm import Session

from infrastructure.db.deps import get_db


router = APIRouter(
    prefix="/api/rrll-excel",
    tags=["RRLL Excel"]
)


def _quote_identifier(identifier: str) -> str:
    """
    Protege nombres de tablas y columnas obtenidos desde information_schema.
    No recibe valores escritos por el usuario.
    """
    return '"' + str(identifier).replace('"', '""') + '"'


def _obtener_columnas_tabla(db: Session, nombre_tabla: str) -> dict:
    """
    Retorna las columnas reales de una tabla pública, conservando mayúsculas
    y minúsculas. La llave del diccionario queda normalizada en minúsculas.
    """
    filas = db.execute(
        text("""
            SELECT column_name
            FROM information_schema.columns
            WHERE table_schema = 'public'
              AND table_name = :nombre_tabla
        """),
        {"nombre_tabla": nombre_tabla},
    ).mappings().all()

    return {
        str(fila["column_name"]).lower(): str(fila["column_name"])
        for fila in filas
    }


def _buscar_columna(columnas: dict, candidatos: list[str]):
    for candidato in candidatos:
        columna_real = columnas.get(str(candidato).lower())
        if columna_real:
            return columna_real
    return None


def _normalizar_numero_identificacion(valor) -> str:
    return str(valor or "").strip().replace(".", "").replace(" ", "")


def _convertir_a_fecha(valor):
    """
    Convierte fechas provenientes de PostgreSQL o cadenas comunes a date.
    Si el valor no es válido, retorna None.
    """
    if valor is None or valor == "":
        return None

    if isinstance(valor, datetime):
        return valor.date()

    if isinstance(valor, date):
        return valor

    texto_fecha = str(valor).strip()
    if not texto_fecha:
        return None

    formatos = (
        "%Y-%m-%d",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%dT%H:%M:%S",
        "%d/%m/%Y",
    )

    for formato in formatos:
        try:
            return datetime.strptime(texto_fecha[:19], formato).date()
        except ValueError:
            continue

    try:
        return datetime.fromisoformat(texto_fecha.replace("Z", "+00:00")).date()
    except (ValueError, TypeError):
        return None


def _completar_total_tiempo_trabajo(resultados):
    """
    Conserva el total que ya venga calculado por la función SQL.

    Solo cuando está vacío y existen fecha de ingreso y fecha de retiro,
    calcula los días transcurridos como:

        fecha_retiro - fecha_ingreso

    Ejemplo:
        2026-07-10 a 2026-07-11 = 1 día.

    No actualiza la base de datos.
    """
    resultados_mutables = [dict(row) for row in resultados]

    for row in resultados_mutables:
        total_actual = row.get("total_tiempo_de_trabajo")

        if total_actual not in (None, ""):
            continue

        fecha_ingreso = _convertir_a_fecha(row.get("fecha_ingreso"))
        fecha_retiro = _convertir_a_fecha(row.get("fecha_retiro"))

        if not fecha_ingreso or not fecha_retiro:
            continue

        dias_trabajados = (fecha_retiro - fecha_ingreso).days

        if dias_trabajados >= 0:
            row["total_tiempo_de_trabajo"] = dias_trabajados

    return resultados_mutables


def _completar_fechas_ingreso_migrados(db: Session, resultados):
    """
    Completa únicamente las fechas de ingreso que la función principal dejó
    vacías. Prioridad:

    1. ContratacionBasica.
    2. HistorialLaboral, incluyendo registros ACTIVO MIGRADO.
    3. Tabla histórica migracionactivossynergy, si existe y contiene columnas
       identificables de documento y fecha de ingreso.

    No modifica información en base de datos.
    """
    resultados_mutables = [dict(row) for row in resultados]

    numeros_faltantes = {
        _normalizar_numero_identificacion(row.get("numero_identificacion"))
        for row in resultados_mutables
        if not row.get("fecha_ingreso")
        and _normalizar_numero_identificacion(row.get("numero_identificacion"))
    }

    if not numeros_faltantes:
        return resultados_mutables

    fechas_por_documento = {}

    columnas_rp = _obtener_columnas_tabla(db, "RegistroPersonal")
    rp_id = _buscar_columna(columnas_rp, ["IdRegistroPersonal"])
    rp_documento = _buscar_columna(
        columnas_rp,
        ["NumeroIdentificacion", "NumeroDocumento", "Documento"],
    )

    if rp_id and rp_documento:
        fuentes_relacionadas = [
            (
                "ContratacionBasica",
                ["IdRegistroPersonal"],
                ["FechaIngreso", "FechaInicio", "FechaIngresoEmpresa"],
                None,
            ),
            (
                "HistorialLaboral",
                ["IdRegistroPersonal"],
                ["FechaIngreso", "FechaInicio", "FechaVinculacion"],
                ["FechaActualizacion", "FechaCreacion", "IdHistorialLaboral"],
            ),
        ]

        for nombre_tabla, candidatos_fk, candidatos_fecha, candidatos_orden in fuentes_relacionadas:
            columnas = _obtener_columnas_tabla(db, nombre_tabla)
            if not columnas:
                continue

            fk = _buscar_columna(columnas, candidatos_fk)
            fecha = _buscar_columna(columnas, candidatos_fecha)

            if not fk or not fecha:
                continue

            columna_orden = _buscar_columna(columnas, candidatos_orden or [])
            expresion_documento = (
                "REPLACE(REPLACE(TRIM(CAST("
                f"rp.{_quote_identifier(rp_documento)} AS TEXT"
                ")), '.', ''), ' ', '')"
            )

            columna_orden_real = columna_orden or fecha

            orden_sql = (
                "ORDER BY "
                f"{expresion_documento}, "
                f"fuente.{_quote_identifier(columna_orden_real)} DESC NULLS LAST"
            )

            consulta = text(f"""
                SELECT DISTINCT ON (
                    {expresion_documento}
                )
                    {expresion_documento} AS numero_identificacion,
                    fuente.{_quote_identifier(fecha)} AS fecha_ingreso
                FROM public.{_quote_identifier("RegistroPersonal")} rp
                INNER JOIN public.{_quote_identifier(nombre_tabla)} fuente
                    ON fuente.{_quote_identifier(fk)}
                     = rp.{_quote_identifier(rp_id)}
                WHERE REPLACE(REPLACE(TRIM(CAST(
                        rp.{_quote_identifier(rp_documento)} AS TEXT
                    )), '.', ''), ' ', '') = ANY(:numeros)
                  AND fuente.{_quote_identifier(fecha)} IS NOT NULL
                {orden_sql}
            """)

            filas = db.execute(
                consulta,
                {"numeros": list(numeros_faltantes)},
            ).mappings().all()

            for fila in filas:
                numero = _normalizar_numero_identificacion(
                    fila.get("numero_identificacion")
                )
                if numero and numero not in fechas_por_documento:
                    fechas_por_documento[numero] = fila.get("fecha_ingreso")

    # Último respaldo: fuente histórica usada en la migración.
    columnas_migracion = _obtener_columnas_tabla(db, "migracionactivossynergy")

    if columnas_migracion:
        columna_documento = _buscar_columna(
            columnas_migracion,
            [
                "NumeroIdentificacion",
                "NumeroDocumento",
                "Documento",
                "Cedula",
                "Identificacion",
                "CC",
            ],
        )
        columna_fecha = _buscar_columna(
            columnas_migracion,
            [
                "FechaIngreso",
                "FechaInicio",
                "FechaVinculacion",
                "FechaIngresoEmpresa",
                "FechaDeIngreso",
            ],
        )

        if columna_documento and columna_fecha:
            consulta_migracion = text(f"""
                SELECT DISTINCT ON (
                    REPLACE(REPLACE(TRIM(CAST(
                        {_quote_identifier(columna_documento)} AS TEXT
                    )), '.', ''), ' ', '')
                )
                    REPLACE(REPLACE(TRIM(CAST(
                        {_quote_identifier(columna_documento)} AS TEXT
                    )), '.', ''), ' ', '') AS numero_identificacion,
                    {_quote_identifier(columna_fecha)} AS fecha_ingreso
                FROM public.{_quote_identifier("migracionactivossynergy")}
                WHERE REPLACE(REPLACE(TRIM(CAST(
                        {_quote_identifier(columna_documento)} AS TEXT
                    )), '.', ''), ' ', '') = ANY(:numeros)
                  AND {_quote_identifier(columna_fecha)} IS NOT NULL
                ORDER BY
                    REPLACE(REPLACE(TRIM(CAST(
                        {_quote_identifier(columna_documento)} AS TEXT
                    )), '.', ''), ' ', ''),
                    {_quote_identifier(columna_fecha)} DESC NULLS LAST
            """)

            filas_migracion = db.execute(
                consulta_migracion,
                {"numeros": list(numeros_faltantes)},
            ).mappings().all()

            for fila in filas_migracion:
                numero = _normalizar_numero_identificacion(
                    fila.get("numero_identificacion")
                )
                if numero and numero not in fechas_por_documento:
                    fechas_por_documento[numero] = fila.get("fecha_ingreso")

    for row in resultados_mutables:
        if row.get("fecha_ingreso"):
            continue

        numero = _normalizar_numero_identificacion(
            row.get("numero_identificacion")
        )
        fecha_encontrada = fechas_por_documento.get(numero)

        if fecha_encontrada:
            row["fecha_ingreso"] = fecha_encontrada

    return resultados_mutables


def _aplicar_descripcion_validada_rrll(db: Session, resultados):
    """
    Reemplaza únicamente la descripción específica del retiro cuando RRLL
    haya registrado una validación oficial.

    Prioridad de salida:
    1. RetiroLaboral.DescripcionRetiroRRLL, cuando tenga contenido.
    2. La descripción original ya devuelta por fn_reporte_retiros_excel.

    No modifica información en la base de datos.
    """
    resultados_mutables = [dict(row) for row in resultados]

    numeros = {
        _normalizar_numero_identificacion(row.get("numero_identificacion"))
        for row in resultados_mutables
        if _normalizar_numero_identificacion(row.get("numero_identificacion"))
    }

    if not numeros:
        return resultados_mutables

    filas_validacion = db.execute(
        text("""
            SELECT
                REPLACE(
                    REPLACE(
                        TRIM(CAST(rp."NumeroIdentificacion" AS TEXT)),
                        '.',
                        ''
                    ),
                    ' ',
                    ''
                ) AS numero_identificacion,
                rl."FechaRetiro" AS fecha_retiro,
                rl."DescripcionRetiroRRLL" AS descripcion_retiro_rrll,
                rl."IdRetiroLaboral" AS id_retiro_laboral
            FROM public."RetiroLaboral" rl
            INNER JOIN public."RegistroPersonal" rp
                ON rp."IdRegistroPersonal" = rl."IdRegistroPersonal"
            WHERE REPLACE(
                    REPLACE(
                        TRIM(CAST(rp."NumeroIdentificacion" AS TEXT)),
                        '.',
                        ''
                    ),
                    ' ',
                    ''
                ) = ANY(:numeros)
              AND NULLIF(
                    BTRIM(COALESCE(rl."DescripcionRetiroRRLL", '')),
                    ''
                  ) IS NOT NULL
            ORDER BY
                numero_identificacion,
                rl."FechaRetiro" DESC NULLS LAST,
                rl."IdRetiroLaboral" DESC
        """),
        {"numeros": list(numeros)},
    ).mappings().all()

    validacion_por_documento_y_fecha = {}
    validacion_mas_reciente_por_documento = {}

    for fila in filas_validacion:
        numero = _normalizar_numero_identificacion(
            fila.get("numero_identificacion")
        )
        descripcion = str(
            fila.get("descripcion_retiro_rrll") or ""
        ).strip()

        if not numero or not descripcion:
            continue

        fecha_retiro = _convertir_a_fecha(fila.get("fecha_retiro"))

        if fecha_retiro:
            clave = (numero, fecha_retiro)
            if clave not in validacion_por_documento_y_fecha:
                validacion_por_documento_y_fecha[clave] = descripcion

        if numero not in validacion_mas_reciente_por_documento:
            validacion_mas_reciente_por_documento[numero] = descripcion

    for row in resultados_mutables:
        numero = _normalizar_numero_identificacion(
            row.get("numero_identificacion")
        )
        fecha_retiro = _convertir_a_fecha(row.get("fecha_retiro"))

        descripcion_rrll = None

        if numero and fecha_retiro:
            descripcion_rrll = validacion_por_documento_y_fecha.get(
                (numero, fecha_retiro)
            )

        if not descripcion_rrll and numero:
            descripcion_rrll = validacion_mas_reciente_por_documento.get(
                numero
            )

        if descripcion_rrll:
            row["descripcion_motivo_especifico_del_retiro"] = descripcion_rrll

    return resultados_mutables


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

        # =========================
        # ESTILOS BASE
        # =========================
        fill_header = PatternFill(
            fill_type="solid",
            start_color="D9EAD3",
            end_color="D9EAD3"
        )

        fill_title = PatternFill(
            fill_type="solid",
            start_color="B6D7A8",
            end_color="B6D7A8"
        )

        fill_metric = PatternFill(
            fill_type="solid",
            start_color="EAF4E2",
            end_color="EAF4E2"
        )

        thin_side = Side(style="thin", color="B7B7B7")
        border_tabla = Border(
            left=thin_side,
            right=thin_side,
            top=thin_side,
            bottom=thin_side
        )

        def style_header(cell):
            cell.font = Font(bold=True)
            cell.fill = fill_header
            cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
            cell.border = border_tabla

        def style_metric_label(cell):
            cell.font = Font(bold=True)
            cell.fill = fill_metric
            cell.alignment = Alignment(horizontal="left", vertical="center", wrap_text=True)
            cell.border = border_tabla

        def style_metric_value(cell):
            cell.font = Font(bold=True)
            cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
            cell.border = border_tabla

        # =========================
        # TITULO Y FILTROS HOJA 1
        # =========================
        ws.merge_cells("A1:M1")
        ws["A1"] = "REPORTE RRLL - RETIROS"
        ws["A1"].font = Font(bold=True, size=14)
        ws["A1"].fill = fill_title
        ws["A1"].alignment = Alignment(horizontal="center", vertical="center")

        ws["A2"] = "Fecha inicio"
        ws["B2"] = fecha_inicio
        ws["A3"] = "Fecha fin"
        ws["B3"] = fecha_fin

        ws["A2"].font = Font(bold=True)
        ws["A3"].font = Font(bold=True)

        # =========================
        # ENCABEZADOS HOJA 1
        # =========================
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

        for col_num, header in enumerate(headers, start=1):
            cell = ws.cell(row=header_row, column=col_num, value=header)
            style_header(cell)

        ws.row_dimensions[header_row].height = 35

        # =========================
        # DATOS DESDE SQL
        # =========================
        q = text("""
            SELECT *
            FROM public.fn_reporte_retiros_excel(:fecha_inicio, :fecha_fin)
        """)

        resultados = db.execute(
            q,
            {
                "fecha_inicio": fecha_inicio,
                "fecha_fin": fecha_fin
            }
        ).mappings().all()

        # Completa solo las fechas de ingreso faltantes, especialmente para
        # trabajadores históricos provenientes de la migración.
        resultados = _completar_fechas_ingreso_migrados(db, resultados)

        # Si el total de tiempo viene vacío, lo calcula usando las fechas ya
        # consolidadas. Los valores existentes se conservan sin cambios.
        resultados = _completar_total_tiempo_trabajo(resultados)

        # Usa primero la validación oficial de RRLL cuando exista.
        # Si RRLL no registró una ampliación, conserva la respuesta original
        # devuelta por fn_reporte_retiros_excel.
        resultados = _aplicar_descripcion_validada_rrll(db, resultados)

        # =========================
        # TIPIFICACIONES PARA LISTA
        # =========================
        q_tipificaciones = text("""
            SELECT "Nombre"
            FROM public."TipificacionRetiro"
            ORDER BY "IdTipificacionRetiro"
        """)

        tipificaciones = [
            row["Nombre"]
            for row in db.execute(q_tipificaciones).mappings().all()
        ]

        # =========================
        # ARMAR DATOS HOJA 1
        # =========================
        datos = [
            [
                row.get("fecha_legalizador"),
                row.get("numero_identificacion"),
                row.get("nombre"),
                row.get("apellido"),
                row.get("cargo"),
                row.get("sede"),
                row.get("fecha_ingreso"),
                row.get("fecha_retiro"),
                row.get("total_tiempo_de_trabajo"),
                (
                    "PRESENCIAL"
                    if str(row.get("retiro_legalizado") or "").strip().upper() == "SI"
                    else "VIRTUAL"
                    if str(row.get("retiro_legalizado") or "").strip().upper() == "NO"
                    else ""
                ),
                row.get("descripcion_motivo_especifico_del_retiro"),
                row.get("tipificacion_de_retiro"),
                row.get("observacion_que_debe_mejorar_la_compania"),
            ]
            for row in resultados
        ]

        fila_datos_inicio = header_row + 1

        for fila in datos:
            ws.append(fila)

        fila_datos_fin = header_row + len(datos)

        # =========================
        # FILTROS Y CONGELAR PANELES
        # =========================
        ws.auto_filter.ref = f"A{header_row}:M{max(fila_datos_fin, header_row)}"
        ws.freeze_panes = "A6"

        # =========================
        # BORDES TABLA
        # =========================
        for row in ws.iter_rows(
            min_row=header_row,
            max_row=max(fila_datos_fin, header_row),
            min_col=1,
            max_col=len(headers)
        ):
            for cell in row:
                cell.border = border_tabla

        # =========================
        # ALTURAS DE FILA
        # =========================
        for row_num in range(fila_datos_inicio, fila_datos_fin + 1):
            ws.row_dimensions[row_num].height = 30

            texto_k = ws[f"K{row_num}"].value or ""
            texto_m = ws[f"M{row_num}"].value or ""

            if len(str(texto_k)) > 40 or len(str(texto_m)) > 40:
                ws.row_dimensions[row_num].height = 45

        # =========================
        # ALINEACIONES
        # =========================
        columnas_centradas = ["A", "B", "G", "H", "I", "J", "L"]
        for row_num in range(fila_datos_inicio, fila_datos_fin + 1):
            for col in columnas_centradas:
                ws[f"{col}{row_num}"].alignment = Alignment(
                    horizontal="center",
                    vertical="center",
                    wrap_text=True
                )

        columnas_texto_largo = ["K", "M"]
        for row_num in range(fila_datos_inicio, fila_datos_fin + 1):
            for col in columnas_texto_largo:
                ws[f"{col}{row_num}"].alignment = Alignment(
                    horizontal="left",
                    vertical="center",
                    wrap_text=True
                )

        # =========================
        # HOJA OCULTA PARA LISTAS
        # =========================
        ws_listas = wb.create_sheet(title="Listas")
        for idx, tip in enumerate(tipificaciones, start=1):
            ws_listas.cell(row=idx, column=1, value=tip)
        ws_listas.sheet_state = "hidden"

        # =========================
        # LISTA DESPLEGABLE TIPIFICACION
        # =========================
        if tipificaciones:
            dv_tipificacion = DataValidation(
                type="list",
                formula1=f"=Listas!$A$1:$A${len(tipificaciones)}",
                allow_blank=True
            )
            dv_tipificacion.prompt = "Seleccione una tipificación de retiro"
            dv_tipificacion.promptTitle = "Tipificación de Retiro"
            dv_tipificacion.error = "Seleccione una tipificación válida de la lista"
            dv_tipificacion.errorTitle = "Valor no válido"

            ws.add_data_validation(dv_tipificacion)
            dv_tipificacion.add(f"L6:L{max(fila_datos_fin, 1000)}")

        # =========================
        # ANCHOS HOJA 1
        # =========================
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

        # =========================
        # HOJA 2 - DASHBOARD
        # =========================
        ws_dashboard = wb.create_sheet(title="Dashboard")

        # -------------------------
        # TÍTULO PRINCIPAL
        # -------------------------
        ws_dashboard.merge_cells("A1:J1")
        ws_dashboard["A1"] = "DASHBOARD EJECUTIVO - RETIROS RRLL"
        ws_dashboard["A1"].font = Font(bold=True, size=15)
        ws_dashboard["A1"].fill = fill_title
        ws_dashboard["A1"].alignment = Alignment(horizontal="center", vertical="center")

        ws_dashboard.merge_cells("A2:J2")
        ws_dashboard["A2"] = f"Periodo analizado: {fecha_inicio} a {fecha_fin}"
        ws_dashboard["A2"].font = Font(italic=True, size=10)
        ws_dashboard["A2"].alignment = Alignment(horizontal="center", vertical="center")

        # -------------------------
        # NORMALIZADORES
        # -------------------------
        def normalizar_texto(valor, default):
            texto = str(valor or "").strip()
            return texto if texto else default

        def truncar_texto(texto, max_len=28):
            texto = normalizar_texto(texto, "")
            return texto if len(texto) <= max_len else texto[:max_len - 3] + "..."

        # -------------------------
        # CONTADORES
        # -------------------------
        legalizados_counter = Counter()
        tipificacion_counter = Counter()
        motivo_counter = Counter()

        for row in resultados:
            retiro_legalizado_raw = normalizar_texto(
                row.get("retiro_legalizado"),
                ""
            ).upper()

            if retiro_legalizado_raw == "SI":
                retiro_legalizado = "PRESENCIAL"
            elif retiro_legalizado_raw == "NO":
                retiro_legalizado = "VIRTUAL"
            else:
                retiro_legalizado = ""

            tipificacion = normalizar_texto(
                row.get("tipificacion_de_retiro"),
                "SIN TIPIFICACION"
            )

            motivo = (
                row.get("motivo_de_retiro")
                or row.get("motivo_retiro")
                or row.get("nombre_motivo_retiro")
                or row.get("descripcion_motivo_especifico_del_retiro")
            )
            motivo = normalizar_texto(motivo, "SIN MOTIVO REGISTRADO")

            if retiro_legalizado:
                legalizados_counter[retiro_legalizado] += 1

            tipificacion_counter[tipificacion] += 1
            motivo_counter[motivo] += 1

        total_retiros = len(resultados)
        total_legalizados_presencial = legalizados_counter.get("PRESENCIAL", 0)
        total_legalizados_virtual = legalizados_counter.get("VIRTUAL", 0)

        tipificacion_top = (
            max(tipificacion_counter.items(), key=lambda x: x[1])[0]
            if tipificacion_counter else "SIN DATOS"
        )
        motivo_top = (
            max(motivo_counter.items(), key=lambda x: x[1])[0]
            if motivo_counter else "SIN DATOS"
        )

        tipificaciones_ordenadas = sorted(
            tipificacion_counter.items(),
            key=lambda x: x[1],
            reverse=True
        )

        motivos_ordenados = sorted(
            motivo_counter.items(),
            key=lambda x: x[1],
            reverse=True
        )

        top_tipificaciones = tipificaciones_ordenadas[:5]
        top_motivos = motivos_ordenados[:5]

        # -------------------------
        # BLOQUE DE MÉTRICAS
        # -------------------------
        ws_dashboard["A4"] = "INDICADOR"
        ws_dashboard["B4"] = "VALOR"
        style_header(ws_dashboard["A4"])
        style_header(ws_dashboard["B4"])

        metricas = [
            ("Total de retiros analizados", total_retiros),
            ("Retiros presenciales", total_legalizados_presencial),
            ("Retiros virtuales", total_legalizados_virtual),
            ("Tipificación más frecuente", tipificacion_top),
            ("Motivo de retiro más frecuente", motivo_top),
        ]

        fila_metrica = 5
        for etiqueta, valor in metricas:
            ws_dashboard[f"A{fila_metrica}"] = etiqueta
            ws_dashboard[f"B{fila_metrica}"] = valor
            style_metric_label(ws_dashboard[f"A{fila_metrica}"])
            style_metric_value(ws_dashboard[f"B{fila_metrica}"])
            fila_metrica += 1

        # ==================================================
        # BLOQUE 1 - RETIRO LEGALIZADO (TABLA + GRÁFICA)
        # ==================================================
        ws_dashboard.merge_cells("A12:B12")
        ws_dashboard["A12"] = "RESUMEN DE RETIRO LEGALIZADO"
        ws_dashboard["A12"].font = Font(bold=True, size=11)
        ws_dashboard["A12"].fill = fill_title
        ws_dashboard["A12"].alignment = Alignment(horizontal="center", vertical="center")
        ws_dashboard["A12"].border = border_tabla
        ws_dashboard["B12"].border = border_tabla

        ws_dashboard["A13"] = "ESTADO"
        ws_dashboard["B13"] = "CANTIDAD"
        style_header(ws_dashboard["A13"])
        style_header(ws_dashboard["B13"])

        estados_legalizados = ["PRESENCIAL", "VIRTUAL"]
        fila_legalizados_inicio = 14

        for i, estado in enumerate(estados_legalizados, start=fila_legalizados_inicio):
            ws_dashboard[f"A{i}"] = estado
            ws_dashboard[f"B{i}"] = legalizados_counter.get(estado, 0)
            ws_dashboard[f"A{i}"].border = border_tabla
            ws_dashboard[f"B{i}"].border = border_tabla
            ws_dashboard[f"A{i}"].alignment = Alignment(horizontal="left", vertical="center")
            ws_dashboard[f"B{i}"].alignment = Alignment(horizontal="center", vertical="center")

        pie_legalizados = PieChart()
        pie_legalizados.title = "Distribución de retiros legalizados"
        pie_legalizados.height = 6.2
        pie_legalizados.width = 7.8
        pie_legalizados.varyColors = True
        pie_legalizados.legend = None

        labels_legalizados = Reference(ws_dashboard, min_col=1, min_row=14, max_row=15)
        data_legalizados = Reference(ws_dashboard, min_col=2, min_row=14, max_row=15)

        pie_legalizados.add_data(data_legalizados, titles_from_data=False)
        pie_legalizados.set_categories(labels_legalizados)

        pie_legalizados.dLbls = DataLabelList()
        pie_legalizados.dLbls.showCatName = True
        pie_legalizados.dLbls.showPercent = True
        pie_legalizados.dLbls.showVal = False
        pie_legalizados.dLbls.showLegendKey = False
        pie_legalizados.dLbls.showSerName = False

        ws_dashboard.add_chart(pie_legalizados, "E12")

        # ==================================================
        # BLOQUE 2 - TIPIFICACIONES (SOLO TABLA)
        # ==================================================
        ws_dashboard.merge_cells("A28:B28")
        ws_dashboard["A28"] = "RESUMEN DE TIPIFICACIONES"
        ws_dashboard["A28"].font = Font(bold=True, size=11)
        ws_dashboard["A28"].fill = fill_title
        ws_dashboard["A28"].alignment = Alignment(horizontal="center", vertical="center")
        ws_dashboard["A28"].border = border_tabla
        ws_dashboard["B28"].border = border_tabla

        ws_dashboard["A29"] = "TIPIFICACIÓN"
        ws_dashboard["B29"] = "CANTIDAD"
        style_header(ws_dashboard["A29"])
        style_header(ws_dashboard["B29"])

        fila_tip_inicio = 30
        for idx, (tip, cantidad) in enumerate(top_tipificaciones, start=fila_tip_inicio):
            ws_dashboard[f"A{idx}"] = tip
            ws_dashboard[f"B{idx}"] = cantidad

            ws_dashboard[f"A{idx}"].border = border_tabla
            ws_dashboard[f"B{idx}"].border = border_tabla

            ws_dashboard[f"A{idx}"].alignment = Alignment(
                horizontal="left",
                vertical="center",
                wrap_text=True
            )
            ws_dashboard[f"B{idx}"].alignment = Alignment(
                horizontal="center",
                vertical="center"
            )

            ws_dashboard[f"A{idx}"].font = Font(size=11)
            ws_dashboard[f"B{idx}"].font = Font(size=11, bold=True)

            ws_dashboard.row_dimensions[idx].height = 34

        fila_tip_fin = max(fila_tip_inicio, fila_tip_inicio + len(top_tipificaciones) - 1)

        # ==================================================
        # BLOQUE 3 - MOTIVOS DE RETIRO (TABLA + GRÁFICA)
        # ==================================================
        ws_dashboard.merge_cells("A44:B44")
        ws_dashboard["A44"] = "RESUMEN DE MOTIVOS DE RETIRO"
        ws_dashboard["A44"].font = Font(bold=True, size=11)
        ws_dashboard["A44"].fill = fill_title
        ws_dashboard["A44"].alignment = Alignment(horizontal="center", vertical="center")
        ws_dashboard["A44"].border = border_tabla
        ws_dashboard["B44"].border = border_tabla

        ws_dashboard["A45"] = "MOTIVO"
        ws_dashboard["B45"] = "CANTIDAD"
        style_header(ws_dashboard["A45"])
        style_header(ws_dashboard["B45"])

        fila_motivo_inicio = 46
        for idx, (motivo, cantidad) in enumerate(top_motivos, start=fila_motivo_inicio):
            ws_dashboard[f"A{idx}"] = motivo
            ws_dashboard[f"B{idx}"] = cantidad

            ws_dashboard[f"A{idx}"].border = border_tabla
            ws_dashboard[f"B{idx}"].border = border_tabla

            ws_dashboard[f"A{idx}"].alignment = Alignment(
                horizontal="left",
                vertical="center",
                wrap_text=True
            )
            ws_dashboard[f"B{idx}"].alignment = Alignment(
                horizontal="center",
                vertical="center"
            )

            ws_dashboard[f"A{idx}"].font = Font(size=11)
            ws_dashboard[f"B{idx}"].font = Font(size=11, bold=True)

            ws_dashboard.row_dimensions[idx].height = 34

        fila_motivo_fin = max(fila_motivo_inicio, fila_motivo_inicio + len(top_motivos) - 1)

        ws_dashboard["C45"] = "ETIQUETA_GRAFICA_MOT"
        for idx, (motivo, _) in enumerate(top_motivos, start=fila_motivo_inicio):
            ws_dashboard[f"C{idx}"] = truncar_texto(motivo, 24)

        bar_motivos = BarChart()
        bar_motivos.type = "bar"
        bar_motivos.style = 11
        bar_motivos.title = "Motivos de retiro"
        bar_motivos.height = 7.4
        bar_motivos.width = 8.8
        bar_motivos.legend = None
        bar_motivos.gapWidth = 110
        bar_motivos.overlap = 0

        bar_motivos.x_axis.title = None
        bar_motivos.y_axis.title = None

        data_mot = Reference(ws_dashboard, min_col=2, min_row=46, max_row=fila_motivo_fin)
        categories_mot = Reference(ws_dashboard, min_col=1, min_row=46, max_row=fila_motivo_fin)

        bar_motivos.add_data(data_mot, titles_from_data=False)
        bar_motivos.set_categories(categories_mot)

        bar_motivos.dLbls = DataLabelList()
        bar_motivos.dLbls.showVal = True
        bar_motivos.dLbls.showCatName = False
        bar_motivos.dLbls.showSerName = False
        bar_motivos.dLbls.showLegendKey = False
        bar_motivos.dLbls.position = "outEnd"

        try:
            bar_motivos.x_axis.delete = True
        except Exception:
            pass

        try:
            bar_motivos.y_axis.delete = True
        except Exception:
            pass

        try:
            bar_motivos.x_axis.majorGridlines = None
        except Exception:
            pass

        ws_dashboard.add_chart(bar_motivos, "D45")

        # -------------------------
        # AJUSTES VISUALES DASHBOARD
        # -------------------------
        ws_dashboard.column_dimensions["A"].width = 52
        ws_dashboard.column_dimensions["B"].width = 16
        ws_dashboard.column_dimensions["C"].width = 18
        ws_dashboard.column_dimensions["D"].width = 4
        ws_dashboard.column_dimensions["E"].width = 4
        ws_dashboard.column_dimensions["F"].width = 4
        ws_dashboard.column_dimensions["G"].width = 4
        ws_dashboard.column_dimensions["H"].width = 4
        ws_dashboard.column_dimensions["I"].width = 4
        ws_dashboard.column_dimensions["J"].width = 4

        for fila in range(1, 65):
            ws_dashboard.row_dimensions[fila].height = 22

        for fila in [1, 2, 12, 28, 44]:
            ws_dashboard.row_dimensions[fila].height = 26

        # =========================
        # GENERAR ARCHIVO
        # =========================
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