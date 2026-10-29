"""Despacho manual y controlado de una notificación PQRF en QA.

No registra rutas ni tareas automáticas. Ejecutar desde la carpeta app:
    python -m services.pqrf_notificaciones_service --id 2
El envío real requiere además --enviar y PQRF_QA_PERMITIR_ENVIO_MANUAL=true.
"""

import argparse
import os
import smtplib
import ssl
from email.message import EmailMessage
from html import escape
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import text
from sqlalchemy.orm import Session

# IMPORTANTE: cargar .env ANTES de importar get_db, porque session.py
# crea el engine de SQLAlchemy al importarse.
ENV_FILE = Path(__file__).resolve().parents[1] / '.env'
load_dotenv(dotenv_path=ENV_FILE)

from infrastructure.db.deps import get_db  # noqa: E402

QA_DB = 'LA_PERFECCION_QA'
QA_DESTINO = 'desarrollo@aseoslaperfeccion.com'


def _smtp_config():
    """Usa la configuración ya existente del correo PQRF/SNC, sin exponer claves."""
    def cfg(k):
        return (os.getenv('PQRF_MAIL_QA_' + k) or os.getenv('SNC_MAIL_PROD_' + k) or '').strip()
    host, sender, user, password = cfg('HOST'), cfg('FROM'), cfg('USER'), cfg('PASSWORD')
    try:
        port = int(cfg('PORT') or '587')
    except ValueError as exc:
        raise RuntimeError('Puerto SMTP inválido') from exc
    if not host or not sender or not user or not password or port not in (465, 587):
        raise RuntimeError('Configuración SMTP incompleta o inválida')
    return host, port, sender, user, password, cfg('USE_TLS').lower() not in ('false', '0', 'no')


def _obtener_y_validar(db: Session, id_notificacion: int):
    nombre = db.execute(text('SELECT current_database()')).scalar_one()
    if nombre != QA_DB:
        raise RuntimeError('BLOQUEADO: este servicio solo permite LA_PERFECCION_QA')
    if os.getenv('PQRF_PUBLICO_HABILITADO', '').strip().lower() != 'true':
        raise RuntimeError('Portal público QA no habilitado')
    fila = db.execute(text('''
        SELECT n."IdNotificacionPQRF" AS id, n."IdPQRF" AS radicado,
               n."TipoNotificacion" AS tipo, n."CorreoDestino" AS destino,
               n."Asunto" AS asunto, n."Cuerpo" AS cuerpo,
               n."EstadoEnvio" AS estado, n."NumeroIntentos" AS intentos,
               p."OrigenPQRF" AS origen
        FROM public."NotificacionPQRF" n
        JOIN public."PQRF" p ON p."IdPQRF" = n."IdPQRF"
        WHERE n."IdNotificacionPQRF" = :id
    '''), {'id': id_notificacion}).mappings().first()
    if fila is None:
        raise RuntimeError('Notificación no encontrada')
    if fila['radicado'] != 20:
        raise RuntimeError('BLOQUEADO: esta prueba solo permite el radicado 20')
    if fila['origen'] != 'EXTERNA' or fila['tipo'] != 'NUEVA_PQRF_EXTERNA':
        raise RuntimeError('Esta prueba solo permite notificaciones iniciales externas')
    destino_actual = (fila['destino'] or '').strip().lower()
    if destino_actual != QA_DESTINO:
        raise RuntimeError(
            f'BLOQUEADO: destinatario leído en BD={destino_actual!r}; '
            f'destinatario autorizado={QA_DESTINO!r}. '
            'Verifica que el UPDATE de DBeaver se haya confirmado con COMMIT. '
            'No se ha enviado ningún correo.'
        )
    if fila['estado'] != 'PENDIENTE' or fila['intentos'] != 0:
        raise RuntimeError('BLOQUEADO: la notificación ya fue procesada o intentada')
    if not fila['asunto'] or not fila['cuerpo']:
        raise RuntimeError('Notificación sin asunto o contenido')
    return fila



def _html_correo(cuerpo: str, radicado: int) -> str:
    """HTML seguro desde el texto encolado; escapa datos externos."""
    parrafos = []
    for bloque in cuerpo.split("\n\n"):
        lineas = [escape(linea) for linea in bloque.splitlines()]
        parrafos.append('<p style="margin:0 0 16px;line-height:1.65">' + '<br>'.join(lineas) + '</p>')
    contenido = ''.join(parrafos)
    return (
        '<!doctype html><html lang="es"><head><meta charset="utf-8"></head>'
        '<body style="margin:0;background:#f3f6f8;font-family:Arial,Helvetica,sans-serif;color:#263744">'
        '<div style="max-width:640px;margin:28px auto;background:#ffffff;border:1px solid #e3e9ed;border-radius:10px;overflow:hidden">'
        '<div style="background:#153b5a;padding:26px 30px;color:#ffffff">'
        '<div style="font-size:12px;font-weight:bold;letter-spacing:1px">ASEOS LA PERFECCIÓN</div>'
        '<h1 style="margin:10px 0 5px;font-size:24px;color:#ffffff">Nueva PQRF registrada</h1>'
        '<div style="font-size:13px;color:#dcebf4">Notificación al área de Calidad</div>'
        '</div><div style="padding:28px 30px">'
        f'<div style="background:#edf6f3;padding:12px 16px;border-left:4px solid #00866b;margin-bottom:22px;font-weight:bold">Radicado N.º {int(radicado)}</div>'
        f'{contenido}'
        '</div><div style="background:#f5f8fa;padding:18px 30px;font-size:12px;color:#61717c">'
        'Sistema de Gestión PQRF · Mensaje automático</div></div></body></html>'
    )

def probar(id_notificacion: int, enviar: bool = False):
    if id_notificacion != 2:
        raise RuntimeError('BLOQUEADO: esta fase solo permite IdNotificacionPQRF=2')
    generador = get_db()
    db = next(generador)
    try:
        fila = _obtener_y_validar(db, id_notificacion)
        print(f"VALIDADO QA | Notificación {fila['id']} | PQRF {fila['radicado']} | Destino {QA_DESTINO} | Estado {fila['estado']}")
        if not enviar:
            print('SIMULACIÓN CORRECTA: no se envió correo y no se modificó la base de datos.')
            return
        if os.getenv('PQRF_QA_PERMITIR_ENVIO_MANUAL', '').strip().lower() != 'true':
            raise RuntimeError('Envío bloqueado: falta PQRF_QA_PERMITIR_ENVIO_MANUAL=true')
        host, port, sender, user, password, use_tls = _smtp_config()
        # Reserva atómica para evitar dos ejecuciones simultáneas de esta prueba.
        reservado = db.execute(text('''
            UPDATE public."NotificacionPQRF"
               SET "EstadoEnvio" = 'ENVIANDO',
                   "NumeroIntentos" = "NumeroIntentos" + 1,
                   "FechaUltimoIntento" = CURRENT_TIMESTAMP,
                   "UltimoError" = NULL
             WHERE "IdNotificacionPQRF" = :id
               AND "EstadoEnvio" = 'PENDIENTE' AND "NumeroIntentos" = 0
               AND LOWER(TRIM("CorreoDestino")) = :destino
            RETURNING "IdNotificacionPQRF"
        '''), {'id': id_notificacion, 'destino': QA_DESTINO}).scalar_one_or_none()
        if reservado is None:
            db.rollback()
            raise RuntimeError('La notificación cambió de estado; envío cancelado')
        db.commit()
        mensaje = EmailMessage()
        mensaje['From'] = sender
        mensaje['To'] = QA_DESTINO  # Nunca tomar destinatarios arbitrarios de QA.
        mensaje['Subject'] = fila['asunto']
        mensaje.set_content(fila['cuerpo'])
        mensaje.add_alternative(_html_correo(fila['cuerpo'], fila['radicado']), subtype='html')
        try:
            contexto = ssl.create_default_context()
            if port == 465:
                with smtplib.SMTP_SSL(host, port, timeout=20, context=contexto) as smtp:
                    smtp.login(user, password)
                    smtp.send_message(mensaje)
            else:
                with smtplib.SMTP(host, port, timeout=20) as smtp:
                    if use_tls:
                        smtp.starttls(context=contexto)
                    smtp.login(user, password)
                    smtp.send_message(mensaje)
        except Exception as exc:
            db.rollback()
            db.execute(text('''
                UPDATE public."NotificacionPQRF"
                   SET "EstadoEnvio" = 'ERROR', "UltimoError" = :error
                 WHERE "IdNotificacionPQRF" = :id AND "EstadoEnvio" = 'ENVIANDO'
            '''), {'id': id_notificacion, 'error': f'{type(exc).__name__}: envío no confirmado; revisar antes de reintentar'[:1000]})
            db.commit()
            raise RuntimeError('SMTP no confirmó el envío. Se marcó ERROR; no reintentar automáticamente.') from exc
        db.execute(text('''
            UPDATE public."NotificacionPQRF"
               SET "EstadoEnvio" = 'ENVIADO', "FechaEnvio" = CURRENT_TIMESTAMP,
                   "UltimoError" = NULL
             WHERE "IdNotificacionPQRF" = :id AND "EstadoEnvio" = 'ENVIANDO'
        '''), {'id': id_notificacion})
        db.commit()
        print('SMTP aceptó el mensaje para el correo de desarrollo. Verifica la bandeja; la entrega final depende del servidor de correo.')
    finally:
        db.close()
        generador.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Prueba manual PQRF QA, sin envío por defecto')
    parser.add_argument('--id', type=int, required=True)
    parser.add_argument('--enviar', action='store_true', help='Envía de verdad (requiere autorización adicional en .env)')
    args = parser.parse_args()
    probar(args.id, args.enviar)
