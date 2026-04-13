from googleapiclient.http import MediaFileUpload

from utilidades.drive_oauth_service import get_drive_service


FOLDER_ID = "1v3wx84KYhRnibP97oc0xJ4zTSKmZLKi8"


def buscar_archivo_en_carpeta(service, nombre_archivo):
    query = (
        f"name = '{nombre_archivo}' "
        f"and '{FOLDER_ID}' in parents "
        f"and trashed = false"
    )

    response = service.files().list(
        q=query,
        fields="files(id, name, webViewLink)",
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