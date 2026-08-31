from datetime import datetime

from googleapiclient.http import MediaFileUpload

from utilidades.drive_oauth_service import (
    get_drive_service,
    get_sheets_service,
)
from utilidades.reporte_synergy_excel import (
    COLUMNAS_MAESTRO_DOTACION,
)


FOLDER_ID = "1mruy-fPbEEYLGrvpCBe7UkQ6Q2u1aeUq"
NOMBRE_SHEET_REGISTRO = "Registro_Contratacion_y_Dotacion"


# ============================================================
# MAPEO DEL FORMATO ANTERIOR AL NUEVO MAESTRO
#
# Se usa únicamente cuando el Google Sheet todavía conserva
# la estructura anterior. Permite migrar las filas existentes
# al maestro de Operaciones sin perderlas durante la mezcla.
# ============================================================

MAPEO_LEGACY_A_MAESTRO = {
    "empleado": "empleado",
    "pnombre": "pnombre",
    "snombre": "snombre",
    "papellido": "papellido",
    "sapellido": "sapellido",
    "fecha_nacimiento": "fnacimiento",
    "tipo_empleado": "tipo_empleado",
    "pais": "pais",
    "departamento": "departamento",
    "lugar_nacimiento": "lugar_nacimiento",
    "direccion": "direccion",
    "barrio": "barrio",
    "telefono": "telefono",
    "tipo_doc_id": "tipo_doc_identidad",
    "num_doc_id": "ndoc_identidad",
    "ciudad_doc_id": "ciudad_doc_ident",
    "pasaporte": "pasaporte",
    "depto_residencia": "dpto_resid",
    "municipio_resid": "ciudad_resid_empleado",
    "estado_civil": "desc_civil",
    "libreta_militar": "nmilitar",
    "licencia_conducir": "nlic_conducir",
    "certif_juducial": "njudicial",
    "nivel_estudios": "nivel_estudios",
    "sexo": "sexo",
    "sucursal": "sucursal",
    "centro_costos_1": "cen1",
    "centro_costos_2": "cen2",
    "centro_costos_3": "cen3",
    "centro_costos_4": "cen4",
    "centro_costos_5": "cen5",
    "escalafon": "escalafon",
    "tipo_contrato": "tipo_contrato",
    "regimen": "regimen_contrato",
    "ncontrato": "ncontrato",
    "fecha_ingreso": "fingreso",
    "fecha_terminacion": "fterminacion",
    "fecha_retiro": "fretiro",
    "motivo_retiro": "motivo_retiro",
    "estado": "activo_retirado",
    "entidad_salud": "entidad_salud",
    "sucursal_salud": "suc_salud",
    "entidad_pension": "entidad_pension",
    "sucursal_pension": "suc_pension",
    "entidad_riesgo": "entidad_riesgo",
    "sucur_Ent_riesgo": "suc_riesgo",
    "caja_compensacion": "caja_compensacion",
    "fondo_cesantias": "fondo_cesantias",
    "centro_trabajo": "centro_trabajo",
    "indicador_retencion": "indicador_reten",
    "porcentaje_retencion": "porc_retencion",
    "auxilio_seguro": "aux_seguro",
    "auxilio_pension": "aux_pension",
    "auxilio_solidaridad": "aux_solidaridad",
    "tarifa_especial": "tarifa_especial",
    "porcentaje_seguro": "porc_seguro",
    "tipo_cotizante": "tipo_cotizante",
    "subtipo_cotizante": "subtipo_cotizante",
    "extranjero_pension": "extranjero_pension",
    "reside_exterior": "reside_exterior",
    "activo_pensionado": "activo_pensionado",
    "posicion": "posicion",
    "empresa": "empresa",
    "tipo_sueldo": "tipo_sueldo",
    "tipo_pago": "forma_pago",
    "corporacion": "lugar_deposito",
    "cuenta": "cuenta",
    "tipo_cuenta": "tipo_cuenta",
    "email": "email_empleado",
    "trabaja_sabado": "indicador_sabado",
}


def buscar_archivo_en_carpeta(
    service,
    nombre_archivo,
    mime_type=None,
):
    query = (
        f"name = '{nombre_archivo}' "
        f"and '{FOLDER_ID}' in parents "
        f"and trashed = false"
    )

    if mime_type:
        query += f" and mimeType = '{mime_type}'"

    response = service.files().list(
        q=query,
        fields="files(id, name, webViewLink, mimeType)",
        supportsAllDrives=True,
        includeItemsFromAllDrives=True,
    ).execute()

    files = response.get("files", [])
    return files[0] if files else None


def subir_archivo_drive(
    ruta_archivo,
    nombre_archivo,
):
    service = get_drive_service()

    media = MediaFileUpload(
        ruta_archivo,
        mimetype=(
            "application/vnd.openxmlformats-officedocument."
            "spreadsheetml.sheet"
        ),
        resumable=True,
    )

    archivo_existente = buscar_archivo_en_carpeta(
        service,
        nombre_archivo,
    )

    if archivo_existente:
        return service.files().update(
            fileId=archivo_existente["id"],
            media_body=media,
            fields="id, name, webViewLink",
            supportsAllDrives=True,
        ).execute()

    file_metadata = {
        "name": nombre_archivo,
        "parents": [FOLDER_ID],
    }

    return service.files().create(
        body=file_metadata,
        media_body=media,
        fields="id, name, webViewLink",
        supportsAllDrives=True,
    ).execute()


def obtener_o_crear_sheet_registro():
    drive_service = get_drive_service()

    archivo_existente = buscar_archivo_en_carpeta(
        drive_service,
        NOMBRE_SHEET_REGISTRO,
        mime_type="application/vnd.google-apps.spreadsheet",
    )

    if archivo_existente:
        print(
            "Sheet existente encontrado:",
            archivo_existente,
        )
        return archivo_existente

    file_metadata = {
        "name": NOMBRE_SHEET_REGISTRO,
        "mimeType": "application/vnd.google-apps.spreadsheet",
        "parents": [FOLDER_ID],
    }

    archivo_nuevo = drive_service.files().create(
        body=file_metadata,
        fields="id, name, webViewLink",
        supportsAllDrives=True,
    ).execute()

    print(
        "Sheet nuevo creado:",
        archivo_nuevo,
    )

    return archivo_nuevo


def obtener_titulo_primera_hoja(spreadsheet_id):
    sheets_service = get_sheets_service()

    spreadsheet = sheets_service.spreadsheets().get(
        spreadsheetId=spreadsheet_id,
        fields="sheets(properties(title))",
    ).execute()

    sheets = spreadsheet.get("sheets", [])

    if not sheets:
        return "Sheet1"

    return sheets[0]["properties"]["title"]


def _parse_fecha(valor):
    if not valor:
        return datetime.min

    texto = str(valor).strip()

    formatos = (
        "%Y-%m-%d",
        "%d/%m/%Y",
        "%Y-%m-%d %H:%M:%S",
        "%d/%m/%Y %H:%M:%S",
    )

    for formato in formatos:
        try:
            return datetime.strptime(
                texto[:19],
                formato,
            )
        except ValueError:
            continue

    return datetime.min


def _es_valor_vacio(valor):
    return (
        valor is None
        or str(valor).strip() == ""
    )


def _es_fila_maestro_nuevo(fila):
    if not isinstance(fila, dict):
        return False

    return (
        "fnacimiento" in fila
        and "activo_retirado" in fila
        and "email_empleado" in fila
    )


def _headers_maestro():
    return [
        encabezado
        for _, encabezado
        in COLUMNAS_MAESTRO_DOTACION
    ]


def _fila_maestro_vacia():
    return {
        clave_interna: ""
        for clave_interna, _
        in COLUMNAS_MAESTRO_DOTACION
    }


def _normalizar_fila_legacy_a_maestro(fila):
    nueva = _fila_maestro_vacia()

    if not isinstance(fila, dict):
        return nueva

    for clave_origen, clave_destino in (
        MAPEO_LEGACY_A_MAESTRO.items()
    ):
        valor = fila.get(clave_origen)

        if valor is not None:
            nueva[clave_destino] = valor

    # Documento canónico del nuevo maestro.
    if _es_valor_vacio(nueva.get("ndoc_identidad")):
        nueva["ndoc_identidad"] = (
            fila.get("empleado")
            or fila.get("cedula")
            or fila.get("NumeroIdentificacion")
            or fila.get("numero_identificacion")
            or ""
        )

    if _es_valor_vacio(nueva.get("empleado")):
        nueva["empleado"] = (
            nueva.get("ndoc_identidad")
            or ""
        )

    # En el maestro nuevo estas columnas aparecen dos veces.
    # Desde el formato anterior solo existe un valor, por lo que se
    # conserva también en la segunda posición mientras una fila nueva
    # del aplicativo no lo reemplace por información más actual.
    nueva["posicion_2"] = nueva.get("posicion") or ""
    nueva["empresa_2"] = nueva.get("empresa") or ""
    nueva["escalafon_2"] = nueva.get("escalafon") or ""
    nueva["tipo_contrato_2"] = (
        nueva.get("tipo_contrato")
        or ""
    )

    return nueva


def obtener_clave_fila(fila):
    if not isinstance(fila, dict):
        return None

    return str(
        fila.get("empleado")
        or fila.get("ndoc_identidad")
        or fila.get("num_doc_id")
        or fila.get("cedula")
        or fila.get("NumeroIdentificacion")
        or fila.get("numero_identificacion")
        or ""
    ).strip()


def ordenar_filas_por_fecha_ingreso(filas):
    if not filas:
        return filas

    return sorted(
        filas,
        key=lambda fila: (
            _parse_fecha(
                fila.get("fingreso")
                or fila.get("fecha_ingre")
                or fila.get("fecha_ingreso")
                or fila.get("FechaIngreso")
                or fila.get("FECHA_INGRESO")
            ),
            obtener_clave_fila(fila) or "",
        ),
    )


def construir_valores_para_sheet(filas):
    if not filas:
        return [
            ["sin_datos"],
            ["No hay registros"],
        ]

    # ========================================================
    # NUEVO MAESTRO DE OPERACIONES
    #
    # Se escribe por posición usando COLUMNAS_MAESTRO_DOTACION.
    # Así se conservan encabezados repetidos como posicion,
    # empresa, escalafon, tipo_contrato y descripcion.
    # ========================================================
    if _es_fila_maestro_nuevo(filas[0]):
        valores = [_headers_maestro()]

        for fila in filas:
            valores.append([
                (
                    ""
                    if fila.get(clave_interna) is None
                    else str(fila.get(clave_interna))
                )
                for clave_interna, _
                in COLUMNAS_MAESTRO_DOTACION
            ])

        return valores

    # ========================================================
    # FORMATO ANTERIOR
    #
    # Se conserva para que este archivo sea compatible con el
    # router actual mientras se realiza el siguiente ajuste.
    # ========================================================
    headers = []
    headers_vistos = set()

    for fila in filas:
        if not isinstance(fila, dict):
            continue

        for key in fila.keys():
            if key not in headers_vistos:
                headers.append(key)
                headers_vistos.add(key)

    valores = [headers]

    for fila in filas:
        valores.append([
            (
                ""
                if fila.get(header) is None
                else str(fila.get(header))
            )
            for header in headers
        ])

    return valores


def leer_filas_actuales_sheet(
    spreadsheet_id,
    titulo_hoja,
):
    sheets_service = get_sheets_service()
    rango = f"'{titulo_hoja}'!A:ZZ"

    response = (
        sheets_service
        .spreadsheets()
        .values()
        .get(
            spreadsheetId=spreadsheet_id,
            range=rango,
        )
        .execute()
    )

    values = response.get("values", [])

    if not values or len(values) < 2:
        return []

    headers = values[0]
    filas = []

    headers_maestro = _headers_maestro()

    # ========================================================
    # SHEET YA MIGRADO AL NUEVO MAESTRO
    #
    # No se usa el texto del encabezado como clave porque hay
    # encabezados repetidos. Cada columna se reconstruye por
    # su posición y su clave interna única.
    # ========================================================
    if headers[:len(headers_maestro)] == headers_maestro:
        for row in values[1:]:
            fila = _fila_maestro_vacia()

            for index, (
                clave_interna,
                _,
            ) in enumerate(
                COLUMNAS_MAESTRO_DOTACION
            ):
                fila[clave_interna] = (
                    row[index]
                    if index < len(row)
                    else ""
                )

            if obtener_clave_fila(fila):
                filas.append(fila)

        return filas

    # ========================================================
    # SHEET TODAVÍA EN FORMATO ANTERIOR
    # ========================================================
    for row in values[1:]:
        fila = {}

        for index, header in enumerate(headers):
            fila[header] = (
                row[index]
                if index < len(row)
                else ""
            )

        if obtener_clave_fila(fila):
            filas.append(fila)

    return filas


def _mezclar_fila_maestro(
    fila_actual,
    fila_nueva,
):
    actual = (
        dict(fila_actual)
        if isinstance(fila_actual, dict)
        else {}
    )

    nueva = (
        dict(fila_nueva)
        if isinstance(fila_nueva, dict)
        else {}
    )

    estado_nuevo = str(
        nueva.get("activo_retirado")
        or ""
    ).strip().upper()

    # Una fila ACTIVA proveniente del nuevo maestro es completa.
    # Debe reemplazar la fila anterior y además limpiar cualquier
    # dato de retiro de un ciclo previo.
    if estado_nuevo == "A":
        resultado = _fila_maestro_vacia()

        for clave_interna, _ in (
            COLUMNAS_MAESTRO_DOTACION
        ):
            resultado[clave_interna] = (
                nueva.get(clave_interna)
                if nueva.get(clave_interna) is not None
                else ""
            )

        resultado["activo_retirado"] = "A"
        resultado["fretiro"] = ""
        resultado["motivo_retiro"] = ""
        resultado["descripcion"] = ""

        return resultado

    # Para RETIRADOS se conserva la información existente cuando
    # la fila de retiro no dispone de algún campo. Esto es clave
    # para que un A -> R actualice el mismo registro sin perder
    # datos personales/contractuales ya almacenados en Dotación.
    resultado = _fila_maestro_vacia()

    for clave_interna, _ in COLUMNAS_MAESTRO_DOTACION:
        valor_actual = actual.get(
            clave_interna,
            "",
        )
        valor_nuevo = nueva.get(
            clave_interna,
            "",
        )

        if not _es_valor_vacio(valor_nuevo):
            resultado[clave_interna] = valor_nuevo
        else:
            resultado[clave_interna] = valor_actual

    # Los campos del estado laboral siempre obedecen a la nueva
    # información, incluso si alguno de ellos viene vacío porque
    # esa es la realidad registrada en RetiroLaboral.
    resultado["activo_retirado"] = (
        nueva.get("activo_retirado")
        or actual.get("activo_retirado")
        or ""
    )
    resultado["fretiro"] = (
        nueva.get("fretiro")
        if nueva.get("fretiro") is not None
        else ""
    )
    resultado["motivo_retiro"] = (
        nueva.get("motivo_retiro")
        if nueva.get("motivo_retiro") is not None
        else ""
    )
    resultado["descripcion"] = (
        nueva.get("descripcion")
        if nueva.get("descripcion") is not None
        else ""
    )

    return resultado


def mezclar_filas_por_documento(
    filas_actuales,
    filas_nuevas,
):
    if not filas_nuevas:
        return filas_actuales or []

    nuevas_son_maestro = (
        _es_fila_maestro_nuevo(filas_nuevas[0])
    )

    mapa = {}
    orden = []

    for fila in filas_actuales:
        fila_base = fila

        if (
            nuevas_son_maestro
            and not _es_fila_maestro_nuevo(fila)
        ):
            fila_base = (
                _normalizar_fila_legacy_a_maestro(
                    fila
                )
            )

        clave = obtener_clave_fila(fila_base)

        if not clave:
            continue

        if clave not in mapa:
            orden.append(clave)

        mapa[clave] = fila_base

    for fila in filas_nuevas:
        fila_nueva = fila
        clave = obtener_clave_fila(fila_nueva)

        if not clave:
            continue

        if clave not in mapa:
            orden.append(clave)
            mapa[clave] = fila_nueva
        elif nuevas_son_maestro:
            mapa[clave] = _mezclar_fila_maestro(
                mapa[clave],
                fila_nueva,
            )
        else:
            # Comportamiento anterior intacto mientras el router
            # continúe enviando el formato legacy.
            mapa[clave] = fila_nueva

        print(
            "Registro sincronizado/actualizado "
            f"en memoria: {clave}"
        )

    return [
        mapa[clave]
        for clave in orden
    ]


def actualizar_contenido_sheet(
    spreadsheet_id,
    filas_nuevas,
):
    print(
        "DEBUG SHEET 1 - "
        "inicio actualizar_contenido_sheet"
    )

    sheets_service = get_sheets_service()
    print(
        "DEBUG SHEET 2 - "
        "sheets_service creado"
    )

    drive_service = get_drive_service()
    print(
        "DEBUG SHEET 3 - "
        "drive_service creado"
    )

    if not filas_nuevas:
        print(
            "DEBUG SHEET 4 - "
            "no llegaron filas nuevas"
        )
        return None

    if (
        isinstance(filas_nuevas[0], dict)
        and "sin_datos" in filas_nuevas[0]
    ):
        print(
            "DEBUG SHEET 5 - "
            "sin_datos, no se actualiza"
        )
        return None

    print(
        "DEBUG SHEET 6 - "
        "antes obtener titulo hoja"
    )

    titulo_hoja = obtener_titulo_primera_hoja(
        spreadsheet_id
    )

    print(
        "DEBUG SHEET 7 - titulo obtenido:",
        titulo_hoja,
    )

    rango_completo = (
        f"'{titulo_hoja}'!A:ZZ"
    )

    print(
        "DEBUG SHEET 8 - filas nuevas recibidas:",
        len(filas_nuevas),
    )

    filas_actuales = leer_filas_actuales_sheet(
        spreadsheet_id,
        titulo_hoja,
    )

    print(
        "DEBUG SHEET 9 - filas actuales:",
        len(filas_actuales),
    )

    filas_finales = mezclar_filas_por_documento(
        filas_actuales,
        filas_nuevas,
    )

    print(
        "DEBUG SHEET 10 - filas mezcladas:",
        len(filas_finales),
    )

    filas_finales = ordenar_filas_por_fecha_ingreso(
        filas_finales
    )

    print(
        "DEBUG SHEET 11 - filas ordenadas"
    )

    valores = construir_valores_para_sheet(
        filas_finales
    )

    print(
        "DEBUG SHEET 12 - valores construidos:",
        len(valores),
    )

    # Se conserva exactamente como estaba:
    # NO se activa el clear en este ajuste.
    print(
        "DEBUG SHEET 13 - "
        "SALTANDO CLEAR TEMPORAL"
    )

    # sheets_service.spreadsheets().values().clear(
    #     spreadsheetId=spreadsheet_id,
    #     range=rango_completo,
    #     body={}
    # ).execute()

    print(
        "DEBUG SHEET 14 - CLEAR OMITIDO"
    )

    print(
        "DEBUG SHEET 15 - antes update"
    )

    (
        sheets_service
        .spreadsheets()
        .values()
        .update(
            spreadsheetId=spreadsheet_id,
            range=f"'{titulo_hoja}'!A1",
            valueInputOption="RAW",
            body={"values": valores},
        )
        .execute()
    )

    print(
        "DEBUG SHEET 16 - UPDATE OK"
    )

    print(
        "DEBUG SHEET 17 - "
        "antes obtener archivo actualizado"
    )

    archivo_actualizado = (
        drive_service
        .files()
        .get(
            fileId=spreadsheet_id,
            fields="id, name, webViewLink",
            supportsAllDrives=True,
        )
        .execute()
    )

    print(
        "DEBUG SHEET 18 - "
        "Sheet actualizado correctamente:",
        archivo_actualizado,
    )

    return archivo_actualizado


def sincronizar_registro_contratacion_dotacion(filas):
    archivo_sheet = obtener_o_crear_sheet_registro()

    return actualizar_contenido_sheet(
        archivo_sheet["id"],
        filas,
    )
