"""Cola persistente de incapacidades. Ejecutar desde app.
Configuracion explicita por ambiente; worker independiente.
"""
import argparse
import logging
import os
import time
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import text

load_dotenv(Path(__file__).resolve().parents[1] / '.env')
from infrastructure.db.session import SessionLocal
from utilidades.sheets_incapacidades_service import (
    sincronizar_incapacidad_google_sheets, _obtener_spreadsheet_id,
)

LOG = logging.getLogger(__name__)
LOCK_ID = 270112026


def validar_entorno(db):
    db_esperada = os.getenv('INCAPACIDADES_DB_ESPERADA', '').strip()
    sheet_esperado = os.getenv('INCAPACIDADES_SHEET_ESPERADO', '').strip()
    if not db_esperada or not sheet_esperado:
        raise RuntimeError('Configuracion de ambiente incompleta')
    if db.execute(text('SELECT current_database()')).scalar() != db_esperada:
        raise RuntimeError('Base de datos no autorizada')
    if _obtener_spreadsheet_id() != sheet_esperado:
        raise RuntimeError('Google Sheets no autorizado')
    if os.getenv('GOOGLE_SHEETS_INCAPACIDADES_WORKER_HABILITADO', '').lower().strip() != 'true':
        raise RuntimeError('Worker deshabilitado')


def encolar_incapacidad(db, id_incapacidad):
    """Usar en la misma transaccion del cambio de negocio. No hace commit."""
    db.execute(text('''
        INSERT INTO public."IncapacidadGoogleSheetsSincronizacion" AS q
            ("IdIncapacidadTrabajador")
        SELECT "IdIncapacidadTrabajador"
        FROM public."IncapacidadTrabajador"
        WHERE "IdIncapacidadTrabajador" = :id AND "Activo" = TRUE
          AND UPPER("Estado") <> 'BORRADOR'
        ON CONFLICT ("IdIncapacidadTrabajador") DO UPDATE SET
            "Estado" = 'PENDIENTE', "Intentos" = 0,
            "UltimoError" = NULL, "FechaActualizacion" = NOW(),
            "FechaProximoIntento" = NOW(), "Version" = q."Version" + 1
    '''), {'id': id_incapacidad})


def procesar_uno(id_incapacidad=None):
    # Conexion dedicada: bloqueo de sesion entre workers, sin bloquear filas
    # durante la llamada externa. No devolver una conexion bloqueada al pool.
    engine = SessionLocal.kw['bind']
    with engine.connect() as lock:
        try:
            validar_entorno(lock)
            adquirido = lock.execute(text('SELECT pg_try_advisory_lock(:k)'), {'k': LOCK_ID}).scalar()
            lock.commit()
            if not adquirido:
                return False
            try:
                with SessionLocal.begin() as db:
                    fila = db.execute(text('''
                        SELECT "IdIncapacidadTrabajador", "Intentos", "Version"
                        FROM public."IncapacidadGoogleSheetsSincronizacion"
                        WHERE ("Estado" = 'EN_PROCESO' OR
                              ("Estado" IN ('PENDIENTE', 'ERROR') AND "FechaProximoIntento" <= NOW()))
                          AND (CAST(:id AS BIGINT) IS NULL OR "IdIncapacidadTrabajador" = :id)
                        ORDER BY "FechaProximoIntento", "IdSincronizacion"
                        LIMIT 1 FOR UPDATE SKIP LOCKED
                    '''), {'id': id_incapacidad}).mappings().first()
                    if fila is None:
                        return False
                    ident = fila['IdIncapacidadTrabajador']
                    version = fila['Version']
                    intentos = fila['Intentos'] + 1
                    db.execute(text('''
                        UPDATE public."IncapacidadGoogleSheetsSincronizacion"
                        SET "Estado" = 'EN_PROCESO', "Intentos" = :intentos,
                            "FechaUltimoIntento" = clock_timestamp(),
                            "FechaActualizacion" = clock_timestamp()
                        WHERE "IdIncapacidadTrabajador" = :id
                    '''), {'id': ident, 'intentos': intentos})
                # La transaccion de la cola ya termino.
                try:
                    with SessionLocal() as lectura:
                        resultado = sincronizar_incapacidad_google_sheets(lectura, ident)
                    exito = resultado.get('success') is True
                except Exception:
                    LOG.exception('Error en sincronizacion de incapacidad %s', ident)
                    exito = False
                demora = min(3600, 30 * 2 ** min(intentos - 1, 7))
                with SessionLocal.begin() as db:
                    cambio = db.execute(text('''
                        UPDATE public."IncapacidadGoogleSheetsSincronizacion"
                        SET "Estado" = :estado, "UltimoError" = :error,
                            "FechaActualizacion" = clock_timestamp(),
                            "FechaProximoIntento" = CASE WHEN :exito THEN NULL
                                ELSE clock_timestamp() + :demora * INTERVAL '1 second' END,
                            "FechaSincronizacion" = CASE WHEN :exito THEN clock_timestamp()
                                ELSE "FechaSincronizacion" END
                        WHERE "IdIncapacidadTrabajador" = :id AND "Version" = :version
                          AND "Estado" = 'EN_PROCESO'
                    '''), {'estado': 'SINCRONIZADO' if exito else 'ERROR',
                           'error': None if exito else 'Sincronizacion no confirmada',
                           'exito': exito, 'demora': demora, 'id': ident, 'version': version})
                    if cambio.rowcount == 0:
                        LOG.info('Incapacidad %s: version nueva pendiente', ident)
                    else:
                        LOG.info('Incapacidad %s: %s', ident, 'SINCRONIZADO' if exito else 'ERROR')
                return True
            finally:
                liberado = lock.execute(text('SELECT pg_advisory_unlock(:k)'), {'k': LOCK_ID}).scalar()
                lock.commit()
                if not liberado:
                    raise RuntimeError('Bloqueo de sesion perdido')
        except BaseException:
            lock.invalidate()
            raise


def main():
    parser = argparse.ArgumentParser()
    grupo = parser.add_mutually_exclusive_group(required=True)
    grupo.add_argument('--una-vez', action='store_true')
    grupo.add_argument('--continuo', action='store_true')
    grupo.add_argument('--id', type=int)
    parser.add_argument('--intervalo', type=int, default=30)
    args = parser.parse_args()
    if args.intervalo < 30 or (args.id is not None and args.id <= 0):
        parser.error('Intervalo minimo 30 segundos; ID positivo')
    logging.basicConfig(level=logging.INFO)
    with SessionLocal() as db:
        validar_entorno(db)
    if args.id is not None:
        procesar_uno(args.id)
        return
    while True:
        try:
            for _ in range(10):
                if not procesar_uno():
                    break
        except Exception:
            LOG.exception('Error procesando cola')
            if not args.continuo:
                raise
        if not args.continuo:
            return
        time.sleep(args.intervalo)


if __name__ == '__main__':
    main()
