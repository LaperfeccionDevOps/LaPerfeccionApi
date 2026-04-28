from pathlib import Path
import pickle

from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from google.auth.transport.requests import Request

SCOPES = [
    "https://www.googleapis.com/auth/drive.file",
    "https://www.googleapis.com/auth/spreadsheets"
]


def _get_credentials():
    base_dir = Path(__file__).resolve().parent.parent

    creds_path = base_dir / "credenciales" / "oauth_client.json"
    token_path = base_dir / "credenciales" / "token.pickle"

    creds = None

    if token_path.exists():
        with open(token_path, "rb") as token:
            creds = pickle.load(token)

    # Refrescar token vencido automáticamente
    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
        with open(token_path, "wb") as token:
            pickle.dump(creds, token)

    # Si no hay token válido, iniciar login manual
    if not creds or not creds.valid:
        flow = InstalledAppFlow.from_client_secrets_file(
            str(creds_path), SCOPES
        )
        creds = flow.run_local_server(port=0)

        with open(token_path, "wb") as token:
            pickle.dump(creds, token)

    return creds


def get_drive_service():
    creds = _get_credentials()
    return build("drive", "v3", credentials=creds)


def get_sheets_service():
    creds = _get_credentials()
    return build("sheets", "v4", credentials=creds)  