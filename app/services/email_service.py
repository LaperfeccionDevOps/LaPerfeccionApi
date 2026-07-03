import os
import smtplib
from pathlib import Path
from email.message import EmailMessage


def enviar_correo_con_adjunto(
    destinatario: str,
    asunto: str,
    cuerpo: str,
    ruta_adjunto: str,
):
    smtp_host = os.getenv("SMTP_HOST")
    smtp_port = int(os.getenv("SMTP_PORT", "587"))
    smtp_user = os.getenv("SMTP_USER")
    smtp_password = os.getenv("SMTP_PASSWORD")
    smtp_from = os.getenv("SMTP_FROM", smtp_user)

    if not smtp_host or not smtp_user or not smtp_password:
        raise ValueError(
            "Falta configuración SMTP en el .env: SMTP_HOST, SMTP_USER o SMTP_PASSWORD."
        )

    archivo = Path(ruta_adjunto)

    if not archivo.exists():
        raise FileNotFoundError(f"No existe el archivo adjunto: {ruta_adjunto}")

    mensaje = EmailMessage()
    mensaje["From"] = smtp_from
    mensaje["To"] = destinatario
    mensaje["Subject"] = asunto
    mensaje.set_content(cuerpo)

    with open(archivo, "rb") as f:
        contenido = f.read()

    mensaje.add_attachment(
        contenido,
        maintype="application",
        subtype="pdf",
        filename=archivo.name,
    )

    with smtplib.SMTP(smtp_host, smtp_port) as smtp:
        smtp.starttls()
        smtp.login(smtp_user, smtp_password)
        smtp.send_message(mensaje)

    return True