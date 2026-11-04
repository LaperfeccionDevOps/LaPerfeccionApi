"""Despachador PQRF EXTERNAS, compatible con QA y producción.

Ejecutar desde la carpeta app:
    python -m services.pqrf_notificaciones_service --pendientes
    python -m services.pqrf_notificaciones_service --id 3
    python -m services.pqrf_notificaciones_service --id 3 --enviar
    python -m services.pqrf_notificaciones_service --pendientes --enviar

Por defecto SIMULA (sin SMTP ni cambios en BD). Para enviar realmente:
El envío manual requiere el permiso explícito del entorno y --enviar.
En QA todos los correos se redirigen al buzón de pruebas; en producción
se respetan los destinatarios validados según el tipo de notificación. No instala un programador:
--pendientes procesa un lote y termina; programar ejecuciones es otra fase.
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

# El .env debe cargarse ANTES de importar get_db (crea engine al importarse).
ENV_FILE = Path(__file__).resolve().parents[1] / '.env'
load_dotenv(dotenv_path=ENV_FILE)
from infrastructure.db.deps import get_db  # noqa: E402

QA_DB = 'LA_PERFECCION_QA'
QA_DESTINO = 'desarrollo@aseoslaperfeccion.com'
PROD_DB = 'la_perfeccion'
CALIDAD_PROD = 'calidad@aseoslaperfeccion.com'
TIPOS = {
    'NUEVA_PQRF_EXTERNA': ('Nueva PQRF registrada', 'Aviso al área de Calidad'),
    'RESPUESTA_A_CALIDAD': ('Respuesta a PQRF para revisión', 'Aviso al área de Calidad'),
    'RESPUESTA_FINAL_CLIENTE': ('Respuesta final a su PQRF', 'Comunicación de cierre'),
}


def _validar_entorno(db: Session):
    nombre = db.execute(text('SELECT current_database()')).scalar_one()
    if nombre not in (QA_DB, PROD_DB):
        raise RuntimeError('BLOQUEADO: base de datos no autorizada para PQRF público')
    if os.getenv('PQRF_PUBLICO_BASE_DATOS', '').strip() != nombre:
        raise RuntimeError('BLOQUEADO: PQRF_PUBLICO_BASE_DATOS no coincide con la conexión')
    if os.getenv('PQRF_PUBLICO_HABILITADO', '').strip().lower() != 'true':
        raise RuntimeError('BLOQUEADO: PQRF_PUBLICO_HABILITADO no es true')
    return nombre


def _smtp_config(nombre_bd):
    # Credenciales separadas por entorno; sin fallback.
    prefijo = 'PQRF_MAIL_QA_' if nombre_bd == QA_DB else 'PQRF_MAIL_PROD_'

    def cfg(clave):
        return (os.getenv(prefijo + clave) or '').strip()

    host, sender, user, password = (cfg(k) for k in ('HOST', 'FROM', 'USER', 'PASSWORD'))
    try:
        port = int(cfg('PORT') or '587')
    except ValueError as exc:
        raise RuntimeError('Puerto SMTP PQRF inválido') from exc
    if not all((host, sender, user, password)) or port not in (465, 587):
        raise RuntimeError(f'Configuración {prefijo}* incompleta o inválida')
    if port == 587 and cfg('USE_TLS').lower() in ('false', '0', 'no'):
        raise RuntimeError('BLOQUEADO: el puerto 587 requiere STARTTLS')
    return host, port, sender, user, password


def _destino_validado(db: Session, fila, nombre_bd: str):
    # QA redirige a pruebas; producción verifica destinatarios.
    if nombre_bd == QA_DB:
        return QA_DESTINO
    destino = (fila['destino'] or '').strip()
    if '\r' in destino or '\n' in destino or '@' not in destino:
        raise RuntimeError('BLOQUEADO: destinatario inválido')
    if fila['tipo'] in ('NUEVA_PQRF_EXTERNA', 'RESPUESTA_A_CALIDAD'):
        if destino.lower() != CALIDAD_PROD:
            raise RuntimeError('BLOQUEADO: notificación interna no dirigida a Calidad')
    elif fila['tipo'] == 'RESPUESTA_FINAL_CLIENTE':
        datos = db.execute(text('''
            SELECT "CorreoRespuestaCliente" AS correo, "Estado" AS estado
            FROM public."PQRF" WHERE "IdPQRF" = :id AND "OrigenPQRF" = 'EXTERNA'
        '''), {'id': fila['radicado']}).mappings().first()
        if not datos or (datos['correo'] or '').strip().lower() != destino.lower():
            raise RuntimeError('BLOQUEADO: destinatario no coincide con el correo del cliente')
        if (datos['estado'] or '').upper() not in ('CERRADA', 'CERRADO'):
            raise RuntimeError('BLOQUEADO: respuesta final sin cierre de Calidad')
    else:
        raise RuntimeError('BLOQUEADO: tipo de notificación desconocido')
    return destino


def _consultar(db: Session, id_notificacion: int):
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
        raise RuntimeError(f'Notificación {id_notificacion} no encontrada')
    if fila['origen'] != 'EXTERNA' or fila['tipo'] not in TIPOS:
        raise RuntimeError('BLOQUEADO: solo notificaciones de PQR externas')
    if fila['estado'] != 'PENDIENTE' or fila['intentos'] != 0:
        raise RuntimeError('BLOQUEADO: ya procesada o intentada; revisión manual requerida')
    if not (fila['destino'] or '').strip() or not fila['asunto'] or not fila['cuerpo']:
        raise RuntimeError('Notificación sin destino original, asunto o contenido')
    return fila


def _html_correo(cuerpo: str, radicado: int, tipo: str, nombre_bd: str = QA_DB) -> str:
    """Correo institucional compatible con Outlook de escritorio (tablas e inline CSS).

    El contenido proviene íntegramente de NotificacionPQRF.Cuerpo; no se
    reemplaza ni se inventa la respuesta del área responsable.
    """
    titulo, subtitulo = TIPOS[tipo]
    estados = {
        'NUEVA_PQRF_EXTERNA': 'Nueva solicitud',
        'RESPUESTA_A_CALIDAD': 'Pendiente de revisión',
        'RESPUESTA_FINAL_CLIENTE': 'Solicitud cerrada',
    }
    # Convertir párrafos a HTML escapando cualquier entrada de usuarios.
    bloques = []
    for bloque in cuerpo.replace('\r\n', '\n').replace('\r', '\n').split('\n\n'):
        if not bloque.strip():
            continue
        lineas = '<br>'.join(escape(linea) for linea in bloque.split('\n'))
        bloques.append(
            '<p style="font-family:Arial,Helvetica,sans-serif;font-size:15px;'
            'line-height:24px;color:#334155;margin:0 0 18px 0;">'
            + lineas + '</p>'
        )
    contenido = ''.join(bloques)
    return (
        '<!DOCTYPE html><html lang="es"><head><meta charset="UTF-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        '<title>Notificación PQRF</title></head>'
        '<body style="margin:0;padding:0;background-color:#f3f6f9;">'
        '<table role="presentation" cellpadding="0" cellspacing="0" border="0" '
        'width="100%" style="border-collapse:collapse;background-color:#f3f6f9;">'
        '<tr><td align="center" style="padding:30px 12px;">'
        '<table role="presentation" cellpadding="0" cellspacing="0" border="0" '
        'width="600" style="width:100%;max-width:600px;border-collapse:collapse;'
        'background-color:#ffffff;border:1px solid #dfe6ed;">'
        '<tr><td bgcolor="#153b5a" style="background-color:#153b5a;'
        'padding:24px 32px;">'
        '<p style="margin:0 0 7px 0;color:#ffffff;font-family:Arial,Helvetica,sans-serif;'
        'font-size:13px;font-weight:bold;letter-spacing:0.6px;">ASEOS LA PERFECCIÓN</p>'
        '<p style="margin:0;color:#dce9f2;font-family:Arial,Helvetica,sans-serif;'
        'font-size:13px;">Sistema de Gestión PQRF</p>'
        '</td></tr>'
        '<tr><td style="padding:30px 32px 12px 32px;">'
        f'<h1 style="font-family:Arial,Helvetica,sans-serif;font-size:23px;'
        f'line-height:30px;font-weight:bold;color:#17364d;margin:0 0 10px 0;">'
        f'{escape(titulo)}</h1>'
        f'<p style="font-family:Arial,Helvetica,sans-serif;font-size:14px;'
        f'line-height:21px;color:#64748b;margin:0 0 22px 0;">{escape(subtitulo)}</p>'
        '<table role="presentation" cellpadding="0" cellspacing="0" border="0" '
        'width="100%" style="border-collapse:collapse;background-color:#f0f5f8;">'
        '<tr><td style="padding:14px 18px;border-left:3px solid #17856f;">'
        '<p style="font-family:Arial,Helvetica,sans-serif;font-size:12px;'
        'color:#526779;margin:0 0 5px 0;">NÚMERO DE RADICADO</p>'
        f'<p style="font-family:Arial,Helvetica,sans-serif;font-size:17px;'
        f'font-weight:bold;color:#17364d;margin:0 0 5px 0;">PQRF N.º {int(radicado)}</p>'
        f'<p style="font-family:Arial,Helvetica,sans-serif;font-size:12px;'
        f'color:#526779;margin:0;">{escape(estados[tipo])}</p>'
        '</td></tr></table>'
        '</td></tr>'
        '<tr><td style="padding:12px 32px 22px 32px;">'
        f'{contenido}'
        '</td></tr>'
        '<tr><td style="padding:18px 32px;background-color:#f5f8fa;'
        'border-top:1px solid #e3eaf0;">'
        '<p style="font-family:Arial,Helvetica,sans-serif;font-size:12px;'
        'line-height:19px;color:#65778a;margin:0;">'
        'Comunicación automática de Aseos La Perfección<br>'
        f'Sistema de Gestión PQRF{" · Entorno de pruebas QA" if nombre_bd == QA_DB else ""}</p>'
        '</td></tr>'
        '</table></td></tr></table></body></html>'
    )


def _evidencias_respuesta(db: Session, fila):
    """Recupera evidencias de gestión solo para el correo final externo."""
    if fila['tipo'] != 'RESPUESTA_FINAL_CLIENTE':
        return []
    registros = db.execute(text('''
        SELECT "IdGestionPQRF" AS id_gestion,
               "EvidenciaNombre" AS nombre,
               "EvidenciaTipo" AS mime,
               "EvidenciaContenido" AS contenido
        FROM public."GestionPQRF"
        WHERE "IdPQRF" = :radicado
          AND "EvidenciaContenido" IS NOT NULL
          AND OCTET_LENGTH("EvidenciaContenido") > 0
        ORDER BY "FechaGestion" DESC, "IdGestionPQRF" DESC
    '''), {'radicado': fila['radicado']}).mappings().all()
    evidencias = []
    for registro in registros:
        nombre = Path((registro['nombre'] or '').replace('\\', '/')).name
        if not nombre or nombre in ('.', '..'):
            raise RuntimeError(f"Evidencia de gestión {registro['id_gestion']} sin nombre válido")
        mime = (registro['mime'] or '').strip().lower()
        if '/' not in mime or mime.count('/') != 1:
            raise RuntimeError(f"Evidencia de gestión {registro['id_gestion']} sin MIME válido")
        maintype, subtype = mime.split('/', 1)
        if not maintype or not subtype or not all(c.isalnum() or c in '.+-' for c in maintype + subtype):
            raise RuntimeError(f"Evidencia de gestión {registro['id_gestion']} con MIME inválido")
        evidencias.append((nombre, maintype, subtype, bytes(registro['contenido'])))
    return evidencias


def _enviar_smtp(fila, config, destino, nombre_bd, evidencias=None):
    host, port, sender, user, password = config
    mensaje = EmailMessage()
    mensaje['From'] = sender
    mensaje['To'] = destino
    mensaje['Subject'] = ('[QA PQR] ' if nombre_bd == QA_DB else '') + fila['asunto']
    if nombre_bd == QA_DB:
        mensaje.set_content('PRUEBA QA. Destinatario original registrado: '
                            + fila['destino'] + '\n\n' + fila['cuerpo'])
    else:
        mensaje.set_content(fila['cuerpo'])
    mensaje.add_alternative(_html_correo(fila['cuerpo'], fila['radicado'], fila['tipo'], nombre_bd), subtype='html')
    for nombre, maintype, subtype, contenido in (evidencias or []):
        mensaje.add_attachment(contenido, maintype=maintype, subtype=subtype, filename=nombre)
    contexto = ssl.create_default_context()
    if port == 465:
        with smtplib.SMTP_SSL(host, port, timeout=20, context=contexto) as smtp:
            smtp.login(user, password)
            smtp.send_message(mensaje)
    else:
        with smtplib.SMTP(host, port, timeout=20) as smtp:
            smtp.starttls(context=contexto)
            smtp.login(user, password)
            smtp.send_message(mensaje)


def procesar(id_notificacion: int, enviar: bool = False):
    generador = get_db()
    db = next(generador)
    try:
        nombre_bd = _validar_entorno(db)
        fila = _consultar(db, id_notificacion)
        destino = _destino_validado(db, fila, nombre_bd)
        print(f"{nombre_bd} | Notificación {fila['id']} | PQR {fila['radicado']} | "
              f"Tipo {fila['tipo']} | Destino autorizado {destino}")
        if not enviar:
            print('SIMULACIÓN: sin SMTP ni modificaciones a BD.')
            return True
        flag = ('PQRF_QA_PERMITIR_ENVIO_MANUAL' if nombre_bd == QA_DB
                else 'PQRF_PROD_PERMITIR_ENVIO_MANUAL')
        if os.getenv(flag, '').strip().lower() != 'true':
            raise RuntimeError(f'BLOQUEADO: requiere {flag}=true')
        evidencias = _evidencias_respuesta(db, fila)
        print(f'Evidencias de respuesta final para adjuntar: {len(evidencias)}')
        config = _smtp_config(nombre_bd)  # Validar antes de reservar el registro.
        reservado = db.execute(text('''
            UPDATE public."NotificacionPQRF"
               SET "EstadoEnvio" = 'ENVIANDO',
                   "NumeroIntentos" = "NumeroIntentos" + 1,
                   "FechaUltimoIntento" = CURRENT_TIMESTAMP,
                   "UltimoError" = NULL
             WHERE "IdNotificacionPQRF" = :id
               AND "EstadoEnvio" = 'PENDIENTE' AND "NumeroIntentos" = 0
               AND "TipoNotificacion" = :tipo
            RETURNING "IdNotificacionPQRF"
        '''), {'id': id_notificacion, 'tipo': fila['tipo']}).scalar_one_or_none()
        if reservado is None:
            db.rollback()
            raise RuntimeError('La notificación cambió de estado; envío cancelado')
        db.commit()  # Reserva atómica visible a otros despachadores.
        try:
            _enviar_smtp(fila, config, destino, nombre_bd, evidencias)
        except Exception as exc:
            db.rollback()
            db.execute(text('''
                UPDATE public."NotificacionPQRF"
                   SET "EstadoEnvio" = 'ERROR', "UltimoError" = :error
                 WHERE "IdNotificacionPQRF" = :id AND "EstadoEnvio" = 'ENVIANDO'
            '''), {'id': id_notificacion,
                   'error': f'{type(exc).__name__}: envío no confirmado; revisar antes de reintentar'[:1000]})
            db.commit()
            raise RuntimeError('SMTP no confirmó el envío; marcado ERROR. No reintentar automáticamente.') from exc
        db.execute(text('''
            UPDATE public."NotificacionPQRF"
               SET "EstadoEnvio" = 'ENVIADO', "FechaEnvio" = CURRENT_TIMESTAMP,
                   "UltimoError" = NULL
             WHERE "IdNotificacionPQRF" = :id AND "EstadoEnvio" = 'ENVIANDO'
        '''), {'id': id_notificacion})
        db.commit()
        print(f"SMTP aceptó notificación {id_notificacion} para {destino}; comprobar bandeja.")
        return True
    finally:
        db.close()
        generador.close()


def pendientes(limite: int):
    generador = get_db()
    db = next(generador)
    try:
        _validar_entorno(db)
        filas = db.execute(text('''
            SELECT n."IdNotificacionPQRF"
            FROM public."NotificacionPQRF" n
            JOIN public."PQRF" p ON p."IdPQRF" = n."IdPQRF"
            WHERE n."EstadoEnvio" = 'PENDIENTE' AND n."NumeroIntentos" = 0
              AND p."OrigenPQRF" = 'EXTERNA'
              AND n."TipoNotificacion" IN
                  ('NUEVA_PQRF_EXTERNA','RESPUESTA_A_CALIDAD','RESPUESTA_FINAL_CLIENTE')
            ORDER BY n."IdNotificacionPQRF"
            LIMIT :limite
        '''), {'limite': limite}).scalars().all()
        return filas
    finally:
        db.close()
        generador.close()


def main():
    parser = argparse.ArgumentParser(description='Despachador PQR externas, QA y producción')
    grupo = parser.add_mutually_exclusive_group(required=True)
    grupo.add_argument('--id', type=int, help='ID específico de NotificacionPQRF')
    grupo.add_argument('--pendientes', action='store_true', help='Procesar un lote de pendientes')
    parser.add_argument('--limite', type=int, default=20, help='Máximo de notificaciones por lote (1-100)')
    parser.add_argument('--enviar', action='store_true', help='Envío SMTP real, sujeto al permiso explícito del entorno')
    args = parser.parse_args()
    if not 1 <= args.limite <= 100:
        parser.error('--limite debe estar entre 1 y 100')
    if args.id is not None and args.id <= 0:
        parser.error('--id debe ser positivo')
    ids = pendientes(args.limite) if args.pendientes else [args.id]
    print(f'Notificaciones seleccionadas: {ids}')
    errores = 0
    for id_notificacion in ids:
        try:
            procesar(id_notificacion, enviar=args.enviar)
        except Exception as exc:
            errores += 1
            print(f'ERROR notificación {id_notificacion}: {exc}')
    if errores:
        raise SystemExit(f'{errores} notificación(es) con error; revisar antes de reintentar.')


if __name__ == '__main__':
    main()
