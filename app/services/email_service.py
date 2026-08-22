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

    Esta función puede ser utilizada por Procesos Disciplinarios
    para notificaciones que no requieren documento adjunto.

    Si se proporciona cuerpo_html, el correo contiene una versión
    alternativa HTML conservando también el texto plano.
    """
    destinatario_limpio = str(destinatario or "").strip()
    asunto_limpio = str(asunto or "").strip()
    cuerpo_limpio = str(cuerpo or "").strip()

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
):
    """
    Envía un correo con un archivo PDF adjunto existente físicamente en disco.

    IMPORTANTE:
    Esta función conserva el contrato que ya tenía en producción:
    retorna True.

    Se mantiene compatible con Nómina Comunicaciones y cualquier otro
    consumidor existente que utilice una ruta física de archivo.
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

    archivo = Path(ruta_adjunto)

    if not archivo.exists():
        raise FileNotFoundError(
            f"No existe el archivo adjunto: {ruta_adjunto}"
        )

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


def enviar_correo_con_adjunto_bytes(
    destinatario: str,
    asunto: str,
    cuerpo: str,
    contenido_adjunto: bytes,
    nombre_adjunto: str,
    cuerpo_html: str | None = None,
) -> tuple[bool, str]:
    """
    Envía un correo con un PDF generado directamente en memoria.

    Esta función está separada de enviar_correo_con_adjunto para no
    modificar el comportamiento existente de Nómina Comunicaciones.

    Procesos Disciplinarios puede usar esta opción para adjuntar una carta
    o notificación PDF generada en memoria, sin crear archivos temporales.
    """
    destinatario_limpio = str(destinatario or "").strip()
    asunto_limpio = str(asunto or "").strip()
    cuerpo_limpio = str(cuerpo or "").strip()
    nombre_adjunto_limpio = str(nombre_adjunto or "").strip()

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

    if not contenido_adjunto:
        raise ValueError(
            "El contenido del archivo adjunto está vacío."
        )

    if not nombre_adjunto_limpio:
        raise ValueError(
            "El nombre del archivo adjunto es obligatorio."
        )

    if not nombre_adjunto_limpio.lower().endswith(".pdf"):
        nombre_adjunto_limpio = f"{nombre_adjunto_limpio}.pdf"

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

    mensaje.add_attachment(
        contenido_adjunto,
        maintype="application",
        subtype="pdf",
        filename=nombre_adjunto_limpio,
    )

    _enviar_mensaje_smtp(
        mensaje=mensaje,
        configuracion=configuracion,
    )

    return (
        True,
        destinatario_limpio,
    )