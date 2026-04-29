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
        archivo_actualizado = service.files().update(
            fileId=archivo_existente["id"],
            media_body=media,
            fields="id, name, webViewLink",
            supportsAllDrives=True
        ).execute()
        return archivo_actualizado

    file_metadata = {
        "name": nombre_archivo,
        "parents": [FOLDER_ID]
    }

    archivo_nuevo = service.files().create(
        body=file_metadata,
        media_body=media,
        fields="id, name, webViewLink",
        supportsAllDrives=True
    ).execute()

    return archivo_nuevo


def obtener_o_crear_sheet_registro():
    drive_service = get_drive_service()

    archivo_existente = buscar_archivo_en_carpeta(
        drive_service,
        NOMBRE_SHEET_REGISTRO,
        mime_type="application/vnd.google-apps.spreadsheet"
    )

    if archivo_existente:
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
    """
    Convierte la fecha de ingreso a datetime para ordenar.
    Si no se puede convertir, la manda al inicio sin romper el proceso.
    """
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


def ordenar_filas_por_fecha_ingreso(filas):
    """
    Ordena los registros para que en el Sheet queden:
    - Primero los contratados más antiguos.
    - Abajo los contratados más recientes.
    - Si tienen la misma fecha, ordena por cédula/empleado.
    """
    if not filas:
        return filas

    if not isinstance(filas[0], dict):
        return filas

    return sorted(
        filas,
        key=lambda fila: (
            _parse_fecha(
                fila.get("fecha_ingre")
                or fila.get("fecha_ingreso")
                or fila.get("FechaIngreso")
                or fila.get("fecha_ingre".upper())
            ),
            str(
                fila.get("empleado")
                or fila.get("num_doc_id")
                or fila.get("cedula")
                or ""
            )
        )
    )


def construir_valores_para_sheet(filas):
    if not filas:
        return [
            ["sin_datos"],
            ["No hay registros"]
        ]

    if isinstance(filas[0], dict):
        headers = []
        headers_vistos = set()

        for fila in filas:
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

    return filas


def actualizar_contenido_sheet(spreadsheet_id, filas):
    sheets_service = get_sheets_service()
    drive_service = get_drive_service()

    # Ordena antes de escribir en Google Sheets.
    filas = ordenar_filas_por_fecha_ingreso(filas)

    titulo_hoja = obtener_titulo_primera_hoja(spreadsheet_id)
    rango = f"'{titulo_hoja}'!A:ZZ"

    valores = construir_valores_para_sheet(filas)

    sheets_service.spreadsheets().values().clear(
        spreadsheetId=spreadsheet_id,
        range=rango,
        body={}
    ).execute()

    sheets_service.spreadsheets().values().update(
        spreadsheetId=spreadsheet_id,
        range=f"'{titulo_hoja}'!A1",
        valueInputOption="RAW",
        body={"values": valores}
    ).execute()

    archivo_actualizado = drive_service.files().get(
        fileId=spreadsheet_id,
        fields="id, name, webViewLink",
        supportsAllDrives=True
    ).execute()

    return archivo_actualizado


def sincronizar_registro_contratacion_dotacion(filas):
    archivo_sheet = obtener_o_crear_sheet_registro()
    return actualizar_contenido_sheet(archivo_sheet["id"], filas)