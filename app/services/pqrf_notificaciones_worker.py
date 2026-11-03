"""Worker independiente de notificaciones PQR externas para QA y producción.

Desde la carpeta app:
  python -m services.pqrf_notificaciones_worker --una-vez
  python -m services.pqrf_notificaciones_worker --continuo
  python -m services.pqrf_notificaciones_worker --id 9

Corte de pruebas QA: nunca despacha notificaciones con ID <= 8.
En producción no hay corte por ID; requiere habilitación explícita.
No se inicia desde main.py ni uvicorn.
"""
import argparse
import logging
import os
import time
from pathlib import Path

from dotenv import load_dotenv

# Cargar .env ANTES de importar módulos que crean el engine de PostgreSQL.
ENV_FILE = Path(__file__).resolve().parents[1] / ".env"
load_dotenv(dotenv_path=ENV_FILE)

from sqlalchemy import text

from infrastructure.db.deps import get_db
from services.pqrf_notificaciones_service import _validar_entorno, procesar, QA_DB, PROD_DB

LOG = logging.getLogger('pqrf_notificaciones_worker')
ID_CORTE_QA = 8
TIPOS = ('NUEVA_PQRF_EXTERNA', 'RESPUESTA_A_CALIDAD', 'RESPUESTA_FINAL_CLIENTE')


def _habilitado(nombre_bd):
    if nombre_bd == QA_DB:
        automatico = 'PQRF_QA_ENVIO_AUTOMATICO_HABILITADO'
        manual = 'PQRF_QA_PERMITIR_ENVIO_MANUAL'
    elif nombre_bd == PROD_DB:
        automatico = 'PQRF_PROD_ENVIO_AUTOMATICO_HABILITADO'
        manual = 'PQRF_PROD_PERMITIR_ENVIO_MANUAL'
    else:
        raise RuntimeError('Worker bloqueado: base de datos no autorizada')
    if os.getenv(automatico, '').strip().lower() != 'true':
        raise RuntimeError(f'Worker deshabilitado: {automatico} no es true')
    if os.getenv(manual, '').strip().lower() != 'true':
        raise RuntimeError(f'Servicio SMTP deshabilitado: {manual} no es true')


def _entorno_actual():
    generador = get_db()
    db = next(generador)
    try:
        return _validar_entorno(db)
    finally:
        db.close()
        generador.close()


def _seleccionar_pendientes(limite=10, id_unico=None):
    """Aplica el corte ANTES de LIMIT; así la notificación 6 no bloquea nuevas."""
    generador = get_db()
    db = next(generador)
    try:
        nombre_bd = _validar_entorno(db)
        corte = ID_CORTE_QA if nombre_bd == QA_DB else 0
        sql = '''
            SELECT n."IdNotificacionPQRF"
            FROM public."NotificacionPQRF" n
            JOIN public."PQRF" p ON p."IdPQRF" = n."IdPQRF"
            WHERE n."EstadoEnvio" = 'PENDIENTE'
              AND n."NumeroIntentos" = 0
              AND p."OrigenPQRF" = 'EXTERNA'
              AND n."TipoNotificacion" IN
                  ('NUEVA_PQRF_EXTERNA','RESPUESTA_A_CALIDAD','RESPUESTA_FINAL_CLIENTE')
              AND n."IdNotificacionPQRF" > :corte
        '''
        parametros = {'corte': corte, 'limite': limite}
        if id_unico is not None:
            sql += ' AND n."IdNotificacionPQRF" = :id_unico\n'
            parametros['id_unico'] = id_unico
        sql += ' ORDER BY n."IdNotificacionPQRF" LIMIT :limite'
        return db.execute(text(sql), parametros).scalars().all()
    finally:
        db.close()
        generador.close()


def ejecutar_lote(id_unico=None, limite=10):
    nombre_bd = _entorno_actual()
    _habilitado(nombre_bd)
    ids = _seleccionar_pendientes(limite=limite, id_unico=id_unico)
    if id_unico is not None and not ids:
        raise RuntimeError('Notificación no elegible, ya enviada o excluida por el corte del entorno')
    if not ids:
        LOG.info('Sin notificaciones nuevas pendientes en %s', nombre_bd)
    for ident in ids:
        try:
            procesar(ident, enviar=True)
        except Exception as exc:
            # Sin reintentos automáticos ante fallos o resultados SMTP inciertos.
            LOG.error('Notificación %s no enviada: %s', ident, type(exc).__name__)
    return len(ids)


def main():
    parser = argparse.ArgumentParser(description='Worker de correos PQR externas QA/producción')
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--id', type=int)
    group.add_argument('--una-vez', action='store_true')
    group.add_argument('--continuo', action='store_true')
    parser.add_argument('--intervalo', type=int, default=60)
    parser.add_argument('--limite', type=int, default=10)
    args = parser.parse_args()
    if args.id is not None and args.id <= 0:
        parser.error('--id debe ser positivo')
    if not 1 <= args.limite <= 100 or not 30 <= args.intervalo <= 3600:
        parser.error('limite 1-100; intervalo 30-3600 segundos')
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
    nombre_bd = _entorno_actual()
    _habilitado(nombre_bd)
    if args.id is not None:
        ejecutar_lote(id_unico=args.id, limite=1)
    elif args.una_vez:
        ejecutar_lote(limite=args.limite)
    else:
        LOG.info('Worker %s iniciado. Corte ID > %s. Detener con Ctrl+C', nombre_bd, ID_CORTE_QA if nombre_bd == QA_DB else 0)
        try:
            while True:
                ejecutar_lote(limite=args.limite)
                time.sleep(args.intervalo)
        except KeyboardInterrupt:
            LOG.info('Worker detenido')


if __name__ == '__main__':
    main()
