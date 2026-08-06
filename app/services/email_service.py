import os
import smtplib
from email.message import EmailMessage
from pathlib import Path


def _obtener_configuracion_smtp() -> dict:
    """
    Obtiene y valida la configuración SMTP compartida por los módulos
    de Nómina, RRLL y Procesos Disciplinarios.
    """
    smtp_host = os.getenv("SMTP_HOST")
    smtp_port = int(os.getenv("SMTP_PORT", "587"))
    smtp_user = os.getenv("SMTP_USER")
    smtp_password = os.getenv("SMTP_PASSWORD")
    smtp_from = os.getenv("SMTP_FROM", smtp_user)

    if not smtp_host or not smtp_user or not smtp_password:
        raise ValueError(
            "Falta configuración SMTP en el .env: "
            "SMTP_HOST, SMTP_USER o SMTP_PASSWORD."
        )

    return {
        "host": smtp_host,
        "port": smtp_port,
        "user": smtp_user,
        "password": smtp_password,
        "from": smtp_from,
    }


def _enviar_mensaje_smtp(
    mensaje: EmailMessage,
    configuracion: dict,
) -> None:
    """
    Envía un EmailMessage utilizando la configuración SMTP existente.
    """
    with smtplib.SMTP(
        configuracion["host"],
        configuracion["port"],
    ) as smtp:
        smtp.starttls()
        smtp.login(
            configuracion["user"],
            configuracion["password"],
        )
        smtp.send_message(mensaje)


def enviar_correo_sin_adjunto(
    destinatario: str,
    asunto: str,
    cuerpo: str,
    cuerpo_html: str | None = None,
) -> bool:
    """
    Envía una notificación por correo sin archivo adjunto.

    Esta función será utilizada inicialmente por Procesos
    Disciplinarios para:

    - Citación inicial.
    - Reprogramación.
    - Cancelación futura.

    Si se proporciona cuerpo_html, el correo contiene una versión
    alternativa HTML conservando también el texto plano.
    """
    destinatario_limpio = str(
        destinatario or ""
    ).strip()

    asunto_limpio = str(
        asunto or ""
    ).strip()

    cuerpo_limpio = str(
        cuerpo or ""
    ).strip()

    if not destinatario_limpio:
        raise ValueError(
            "El destinatario del correo es obligatorio."
        )

    if not asunto_limpio:
        raise ValueError(
            "El asunto del correo es obligatorio."
        )

    if not cuerpo_limpio:
        raise ValueError(
            "El cuerpo del correo es obligatorio."
        )

    configuracion = _obtener_configuracion_smtp()

    mensaje = EmailMessage()
    mensaje["From"] = configuracion["from"]
    mensaje["To"] = destinatario_limpio
    mensaje["Subject"] = asunto_limpio

    mensaje.set_content(cuerpo_limpio)

    if cuerpo_html:
        mensaje.add_alternative(
            cuerpo_html,
            subtype="html",
        )

    _enviar_mensaje_smtp(
        mensaje=mensaje,
        configuracion=configuracion,
    )

    return True


def enviar_correo_con_adjunto(
    destinatario: str,
    asunto: str,
    cuerpo: str,
    ruta_adjunto: str,
) -> tuple[bool, str]:
    """
    Envía un correo con un archivo PDF adjunto.

    Se conserva para Nómina Comunicaciones y cualquier módulo
    que necesite enviar documentos generados.
    """
    destinatario_limpio = str(
        destinatario or ""
    ).strip()

    asunto_limpio = str(
        asunto or ""
    ).strip()

    cuerpo_limpio = str(
        cuerpo or ""
    ).strip()

    if not destinatario_limpio:
        raise ValueError(
            "El destinatario del correo es obligatorio."
        )

    if not asunto_limpio:
        raise ValueError(
            "El asunto del correo es obligatorio."
        )

    if not cuerpo_limpio:
        raise ValueError(
            "El cuerpo del correo es obligatorio."
        )

    configuracion = _obtener_configuracion_smtp()

    archivo = Path(ruta_adjunto)

    if not archivo.exists():
        raise FileNotFoundError(
            f"No existe el archivo adjunto: {ruta_adjunto}"
        )

    mensaje = EmailMessage()
    mensaje["From"] = configuracion["from"]
    mensaje["To"] = destinatario_limpio
    mensaje["Subject"] = asunto_limpio
    mensaje.set_content(cuerpo_limpio)

    with archivo.open("rb") as archivo_pdf:
        contenido = archivo_pdf.read()

    mensaje.add_attachment(
        contenido,
        maintype="application",
        subtype="pdf",
        filename=archivo.name,
    )

    _enviar_mensaje_smtp(
        mensaje=mensaje,
        configuracion=configuracion,
    )

    return True, destinatario_limpio