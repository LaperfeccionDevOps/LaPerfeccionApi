from datetime import datetime
from googleapiclient.http import MediaFileUpload

from utilidades.drive_oauth_service import get_drive_service, get_sheets_service


FOLDER_ID = "1mruy-fPbEEYLGrvpCBe7UkQ6Q2u1aeUq"
NOMBRE_SHEET_REGISTRO = "Registro_Contratacion_y_Dotacion"


def buscar_archivo_en_carpeta(service, nombre_archivo, mime_type=None):
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
        includeItemsFromAllDrives=True
    ).execute()

    files = response.get("files", [])
    return files[0] if files else None


def subir_archivo_drive(ruta_archivo, nombre_archivo):
    service = get_drive_service()

    media = MediaFileUpload(
        ruta_archivo,
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        resumable=True
    )

    archivo_existente = buscar_archivo_en_carpeta(service, nombre_archivo)

    if archivo_existente:
        return service.files().update(
            fileId=archivo_existente["id"],
            media_body=media,
            fields="id, name, webViewLink",
            supportsAllDrives=True
        ).execute()

    file_metadata = {
        "name": nombre_archivo,
        "parents": [FOLDER_ID]
    }

    return service.files().create(
        body=file_metadata,
        media_body=media,
        fields="id, name, webViewLink",
        supportsAllDrives=True
    ).execute()


def obtener_o_crear_sheet_registro():
    drive_service = get_drive_service()

    archivo_existente = buscar_archivo_en_carpeta(
        drive_service,
        NOMBRE_SHEET_REGISTRO,
        mime_type="application/vnd.google-apps.spreadsheet"
    )

    if archivo_existente:
        print("Sheet existente encontrado:", archivo_existente)
        return archivo_existente

    file_metadata = {
        "name": NOMBRE_SHEET_REGISTRO,
        "mimeType": "application/vnd.google-apps.spreadsheet",
        "parents": [FOLDER_ID]
    }

    archivo_nuevo = drive_service.files().create(
        body=file_metadata,
        fields="id, name, webViewLink",
        supportsAllDrives=True
    ).execute()

    print("Sheet nuevo creado:", archivo_nuevo)
    return archivo_nuevo


def obtener_titulo_primera_hoja(spreadsheet_id):
    sheets_service = get_sheets_service()

    spreadsheet = sheets_service.spreadsheets().get(
        spreadsheetId=spreadsheet_id,
        fields="sheets(properties(title))"
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
            return datetime.strptime(texto[:19], formato)
        except ValueError:
            continue

    return datetime.min


def obtener_clave_fila(fila):
    if not isinstance(fila, dict):
        return None

    return str(
        fila.get("empleado")
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
                fila.get("fecha_ingre")
                or fila.get("fecha_ingreso")
                or fila.get("FechaIngreso")
                or fila.get("FECHA_INGRESO")
            ),
            obtener_clave_fila(fila) or ""
        )
    )


def construir_valores_para_sheet(filas):
    if not filas:
        return [
            ["sin_datos"],
            ["No hay registros"]
        ]

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
            "" if fila.get(header) is None else str(fila.get(header))
            for header in headers
        ])

    return valores


def leer_filas_actuales_sheet(spreadsheet_id, titulo_hoja):
    sheets_service = get_sheets_service()
    rango = f"'{titulo_hoja}'!A:ZZ"

    response = sheets_service.spreadsheets().values().get(
        spreadsheetId=spreadsheet_id,
        range=rango
    ).execute()

    values = response.get("values", [])

    if not values or len(values) < 2:
        return []

    headers = values[0]
    filas = []

    for row in values[1:]:
        fila = {}
        for index, header in enumerate(headers):
            fila[header] = row[index] if index < len(row) else ""
        filas.append(fila)

    return filas


def mezclar_filas_por_documento(filas_actuales, filas_nuevas):
    mapa = {}

    for fila in filas_actuales:
        clave = obtener_clave_fila(fila)
        if clave:
            mapa[clave] = fila

    for fila in filas_nuevas:
        clave = obtener_clave_fila(fila)
        if clave:
            mapa[clave] = fila
            print(f"Registro sincronizado/actualizado en memoria: {clave}")

    return list(mapa.values())


def actualizar_contenido_sheet(spreadsheet_id, filas_nuevas):
    print("DEBUG SHEET 1 - inicio actualizar_contenido_sheet")

    sheets_service = get_sheets_service()
    print("DEBUG SHEET 2 - sheets_service creado")

    drive_service = get_drive_service()
    print("DEBUG SHEET 3 - drive_service creado")

    if not filas_nuevas:
        print("DEBUG SHEET 4 - no llegaron filas nuevas")
        return None

    if isinstance(filas_nuevas[0], dict) and "sin_datos" in filas_nuevas[0]:
        print("DEBUG SHEET 5 - sin_datos, no se actualiza")
        return None

    print("DEBUG SHEET 6 - antes obtener titulo hoja")
    titulo_hoja = obtener_titulo_primera_hoja(spreadsheet_id)
    print("DEBUG SHEET 7 - titulo obtenido:", titulo_hoja)

    rango_completo = f"'{titulo_hoja}'!A:ZZ"

    print("DEBUG SHEET 8 - filas nuevas recibidas:", len(filas_nuevas))

    filas_actuales = leer_filas_actuales_sheet(spreadsheet_id, titulo_hoja)
    print("DEBUG SHEET 9 - filas actuales:", len(filas_actuales))

    filas_finales = mezclar_filas_por_documento(filas_actuales, filas_nuevas)
    print("DEBUG SHEET 10 - filas mezcladas:", len(filas_finales))

    filas_finales = ordenar_filas_por_fecha_ingreso(filas_finales)
    print("DEBUG SHEET 11 - filas ordenadas")

    valores = construir_valores_para_sheet(filas_finales)
    print("DEBUG SHEET 12 - valores construidos:", len(valores))

    print("DEBUG SHEET 13 - SALTANDO CLEAR TEMPORAL")
    # sheets_service.spreadsheets().values().clear(
    #     spreadsheetId=spreadsheet_id,
    #     range=rango_completo,
    #     body={}
    # ).execute()
    print("DEBUG SHEET 14 - CLEAR OMITIDO")

   
    print("DEBUG SHEET 15 - antes update")
    sheets_service.spreadsheets().values().update(
        spreadsheetId=spreadsheet_id,
        range=f"'{titulo_hoja}'!A1",
        valueInputOption="RAW",
        body={"values": valores}
    ).execute()
    print("DEBUG SHEET 16 - UPDATE OK")

    print("DEBUG SHEET 17 - antes obtener archivo actualizado")
    archivo_actualizado = drive_service.files().get(
        fileId=spreadsheet_id,
        fields="id, name, webViewLink",
        supportsAllDrives=True
    ).execute()
    print("DEBUG SHEET 18 - Sheet actualizado correctamente:", archivo_actualizado)

    return archivo_actualizado
def sincronizar_registro_contratacion_dotacion(filas):
    archivo_sheet = obtener_o_crear_sheet_registro()
    return actualizar_contenido_sheet(archivo_sheet["id"], filas)