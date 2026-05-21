from pathlib import Path
import pickle
import logging

from googleapiclient.discovery import build
from google.auth.transport.requests import Request
from google.auth.exceptions import RefreshError

SCOPES = [
    "https://www.googleapis.com/auth/drive.file",
    "https://www.googleapis.com/auth/spreadsheets"
]

logger = logging.getLogger("contratado_debug")


def _get_credentials():
    base_dir = Path(__file__).resolve().parent.parent

    creds_path = base_dir / "credenciales" / "oauth_client.json"
    token_path = base_dir / "credenciales" / "token.pickle"

    creds = None

    if token_path.exists():
        with open(token_path, "rb") as token:
            creds = pickle.load(token)

    if creds and creds.valid:
        return creds

    if creds and creds.expired and creds.refresh_token:
        try:
            logger.info("Token Google vencido. Intentando refrescar automáticamente...")
            creds.refresh(Request())

            with open(token_path, "wb") as token:
                pickle.dump(creds, token)

            logger.info("Token Google refrescado correctamente.")
            return creds

        except RefreshError as e:
            logger.error(f"No se pudo refrescar token Google: {str(e)}")
            raise Exception(
                "Token de Google vencido o revocado. "
                "Regenerar token.pickle manualmente usando entorno_venv."
            )

    raise Exception(
        "No existe token Google válido. "
        "Generar token.pickle manualmente usando entorno_venv."
    )


def get_drive_service():
    creds = _get_credentials()
    return build("drive", "v3", credentials=creds)


def get_sheets_service():
    creds = _get_credentials()
    return build("sheets", "v4", credentials=creds)