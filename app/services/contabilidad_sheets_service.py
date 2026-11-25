"""Espejo de Centros de Costo en Google Sheets (vía Apps Script).

Cada cambio de Contabilidad (crear, cerrar, reabrir, fechas del proyecto,
asignaciones) programa un envío de la foto completa a la hoja; los cambios
seguidos se agrupan en un solo envío. Además hay un refresco diario a las 2:00
(hora de Bogotá) para las etapas que cambian con la fecha y lo que se cambie
fuera del portal. El envío es en segundo plano: si Google falla, el cambio ya
quedó guardado en la base y el siguiente envío pone la hoja al día.

Configuración (app/.env):
    CONTABILIDAD_APPSCRIPT_URL   URL /exec de la aplicación web del Apps Script.
    CONTABILIDAD_APPSCRIPT_CLAVE La misma clave de la propiedad CLAVE del script.
Sin ellas no se envía nada. El script está en app/integraciones/appscript/.
"""

import json
import logging
import os
import threading
import time as _time
import urllib.error
import urllib.request
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal

from sqlalchemy import text

logger = logging.getLogger("contabilidad_sheets")

# Registro propio en LaPerfeccionApi/logs/contabilidad_sheets.log (el envío
# corre en segundo plano y sin esto sus errores solo salen en la consola).
if not logger.handlers:
    try:
        from pathlib import Path

        _carpeta_logs = Path(__file__).resolve().parents[2] / "logs"
        _carpeta_logs.mkdir(exist_ok=True)
        _archivo = logging.FileHandler(_carpeta_logs / "contabilidad_sheets.log", encoding="utf-8")
        _archivo.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        logger.addHandler(_archivo)
        logger.setLevel(logging.INFO)
    except OSError:
        pass

ZONA = timezone(timedelta(hours=-5), "America/Bogota")  # sin horario de verano
ESPERA_SEGUNDOS = 10  # agrupa los cambios seguidos en un solo envío
TIEMPO_MAXIMO_SEGUNDOS = 90
ESPERA_CANDADO_SEGUNDOS = 420  # cubre un envío con sus reintentos; si tarda más, este se descarta
HORA_REFRESCO = time(2, 0)
# Reintentos ante cortes de conexión (segundos de espera antes de cada uno).
# Reenviar no duplica nada: cada envío reemplaza la hoja completa.
ESPERAS_REINTENTO = (15, 60)
# Llave del candado de PostgreSQL: un envío a la vez entre procesos.
LLAVE_CANDADO = 715_200_001


class ErrorSheets(Exception):
    """El envío a la hoja de Google no se pudo completar."""


class ErrorConexion(ErrorSheets):
    """Falla de red o de Google (se puede reintentar)."""


def _url() -> str:
    return os.getenv("CONTABILIDAD_APPSCRIPT_URL", "").strip()


def _clave() -> str:
    return os.getenv("CONTABILIDAD_APPSCRIPT_CLAVE", "").strip()


def configurado() -> bool:
    return bool(_url() and _clave() and _ambiente() in {"QA", "PRODUCCION"}
                and _destino() and _base_esperada() and _servidor_esperado())


def _ambiente():
    return os.getenv("CONTABILIDAD_SHEETS_AMBIENTE", "").strip().upper()


def _destino():
    return os.getenv("CONTABILIDAD_SHEETS_DESTINO_ID", "").strip()


def _base_esperada():
    return os.getenv("CONTABILIDAD_SHEETS_BASE", "").strip()


def _servidor_esperado():
    return os.getenv("CONTABILIDAD_SHEETS_SERVIDOR", "").strip()


def _validar_base(db):
    base, servidor = db.execute(text(
        "SELECT current_database(), inet_server_addr()::text || ':' || inet_server_port()::text"
    )).one()
    if base != _base_esperada() or servidor != _servidor_esperado():
        raise ErrorSheets("Base o servidor no autorizado para sincronizar.")
    if (_ambiente() == "QA") != (base == "LA_PERFECCION_QA"):
        raise ErrorSheets("Ambiente y base incompatibles.")
    return base


# ─── Paquete ───

def _valor(valor):
    """Valor de celda en JSON: fechas en ISO, decimales como número."""
    if valor is None:
        return ""
    if isinstance(valor, datetime):
        return valor.strftime("%Y-%m-%dT%H:%M:%S")
    if isinstance(valor, date):
        return valor.isoformat()
    if isinstance(valor, Decimal):
        return float(valor)
    return valor


def _paquete(db, origen: str, usuario: str, evento: str) -> dict:
    # Import diferido: el router importa este servicio.
    from api.routers.contabilidad_centros_costo_routers import armar_exportacion

    base = _validar_base(db)
    datos = armar_exportacion(db, None, None, usuario)

    hojas = [
        {
            "nombre": "Resumen",
            "encabezados": ["Dato", "Valor"],
            "tipos": ["texto", "texto"],
            "filas": [
                [str(f[0]) if f else "", "" if len(f) < 2 else str(_valor(f[1]))]
                for f in datos["resumen"][2:]  # sin el título ni la fila en blanco
            ],
        }
    ]
    for h in datos["hojas"]:
        hojas.append({
            "nombre": h["nombre"],
            "encabezados": h["encabezados"],
            "tipos": h["tipos"],
            "filas": [[_valor(v) for v in fila] for fila in h["filas"]],
        })

    return {"ambiente": _ambiente(), "destino_id": _destino(), "base": base, "origen": origen, "usuario": usuario, "evento": evento[:300], "hojas": hojas}


def _enviar(paquete: dict) -> list[dict]:
    cuerpo = json.dumps({"clave": _clave(), **paquete}, ensure_ascii=False).encode("utf-8")
    solicitud = urllib.request.Request(
        _url(),
        data=cuerpo,
        headers={"Content-Type": "application/json; charset=utf-8"},
        method="POST",
    )
    # Apps Script responde con una redirección a googleusercontent.com, que
    # urllib sigue con GET (lo que Google espera).
    try:
        with urllib.request.urlopen(solicitud, timeout=TIEMPO_MAXIMO_SEGUNDOS) as respuesta:
            contenido = respuesta.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as error:
        # 5xx y 429 son pasajeros; 4xx (URL o acceso) no se arreglan reintentando.
        if error.code >= 500 or error.code == 429:
            raise ErrorConexion(f"Google respondió HTTP {error.code}.") from error
        raise ErrorSheets(f"Google respondió HTTP {error.code}.") from error
    except (urllib.error.URLError, TimeoutError, OSError) as error:
        raise ErrorConexion(f"No se pudo conectar con Google: {error}") from error

    try:
        resultado = json.loads(contenido)
    except ValueError as error:
        # Sin JSON suele ser la página de inicio de sesión: la implementación no
        # tiene "Quién tiene acceso: Cualquier usuario" o la URL no es la /exec.
        raise ErrorSheets("El Apps Script no respondió JSON; revisa la URL /exec y el acceso de la implementación.") from error

    if not resultado.get("ok"):
        raise ErrorSheets(f"El Apps Script rechazó el envío: {resultado.get('error') or 'sin detalle'}")
    if resultado.get("ambiente") != paquete["ambiente"] or resultado.get("destino_id") != paquete["destino_id"]:
        raise ErrorSheets("El receptor no confirmó el ambiente y destino autorizados.")
    return resultado.get("hojas") or []


def _enviar_con_reintentos(paquete: dict) -> list[dict]:
    for intento, espera in enumerate((*ESPERAS_REINTENTO, None), start=1):
        try:
            return _enviar(paquete)
        except ErrorConexion as error:
            if espera is None:
                raise
            logger.warning("Intento %s falló (%s); se reintenta en %s s.", intento, error, espera)
            _time.sleep(espera)
    return []  # no se alcanza


def sincronizar(origen: str, usuario: str, evento: str) -> list[dict]:
    """Arma la foto completa y la envía. Un envío a la vez (también entre
    procesos), para que una foto vieja no llegue después de una nueva."""
    if not configurado():
        return []

    from infrastructure.db.session import SessionLocal, engine

    logger.info("Enviando a Google Sheets (%s, %s): %s", origen, usuario, evento)

    # El candado vive en una conexión propia que se toma y se suelta en la
    # misma conexión (la sesión de SQLAlchemy devuelve su conexión al pool en
    # cada rollback, y el candado quedaba tomado en el pool).
    with engine.connect() as conexion:
        limite = _time.monotonic() + ESPERA_CANDADO_SEGUNDOS
        while not conexion.execute(text("SELECT pg_try_advisory_lock(:llave)"), {"llave": LLAVE_CANDADO}).scalar():
            conexion.rollback()
            if _time.monotonic() > limite:
                raise ErrorSheets("Otro envío a Google Sheets no terminó a tiempo; se reintentará en el próximo cambio.")
            _time.sleep(2)
        conexion.commit()
        try:
            db = SessionLocal()
            try:
                paquete = _paquete(db, origen, usuario, evento)
            finally:
                db.close()
            hojas = _enviar_con_reintentos(paquete)
        finally:
            conexion.rollback()
            conexion.execute(text("SELECT pg_advisory_unlock(:llave)"), {"llave": LLAVE_CANDADO})
            conexion.commit()

    logger.info(
        "Google Sheets actualizado (%s, %s): %s",
        origen, usuario, ", ".join(f"{h.get('nombre')}={h.get('filas')}" for h in hojas),
    )
    return hojas


# ─── Envío después de cada cambio ───

_candado = threading.Lock()
_temporizador: threading.Timer | None = None
_pendientes: list[tuple[str, str]] = []


def programar_sincronizacion(usuario: str, evento: str) -> None:
    """Llamar después del commit de un cambio. No bloquea ni falla."""
    global _temporizador
    if not configurado():
        logger.warning("Cambio sin enviar a Google Sheets (configuración de destino o ambiente incompleta): %s", evento)
        return
    logger.info("Envío programado en %s s: %s (%s)", ESPERA_SEGUNDOS, evento, usuario)
    with _candado:
        _pendientes.append((usuario, evento))
        if _temporizador:
            _temporizador.cancel()
        _temporizador = threading.Timer(ESPERA_SEGUNDOS, _enviar_pendientes)
        _temporizador.daemon = True
        _temporizador.start()


def _enviar_pendientes() -> None:
    global _temporizador
    with _candado:
        pendientes = list(_pendientes)
        _pendientes.clear()
        _temporizador = None
    if not pendientes:
        return

    usuarios = list(dict.fromkeys(u for u, _ in pendientes))
    eventos = [e for _, e in pendientes]
    evento = "; ".join(eventos[:5]) + (f" y {len(eventos) - 5} más" if len(eventos) > 5 else "")
    try:
        sincronizar("cambio", ", ".join(usuarios)[:100], evento)
    except Exception:
        logger.exception("No se pudo actualizar Google Sheets después de: %s", evento)


# ─── Refresco diario ───

_hilo_diario: threading.Thread | None = None
_detener = threading.Event()


def _segundos_hasta_refresco() -> float:
    ahora = datetime.now(ZONA)
    siguiente = datetime.combine(ahora.date(), HORA_REFRESCO, tzinfo=ZONA)
    if siguiente <= ahora:
        siguiente += timedelta(days=1)
    return (siguiente - ahora).total_seconds()


def _bucle_diario() -> None:
    while not _detener.wait(_segundos_hasta_refresco()):
        try:
            sincronizar("programado", "SISTEMA", "Refresco diario")
        except Exception:
            logger.exception("Falló el refresco diario de Google Sheets.")


def iniciar_refresco_diario() -> None:
    """Se llama al arrancar la API. Si la hoja no está configurada, no hace nada."""
    global _hilo_diario
    if not configurado() or (_hilo_diario and _hilo_diario.is_alive()):
        return
    _detener.clear()
    _hilo_diario = threading.Thread(target=_bucle_diario, name="contabilidad-sheets-diario", daemon=True)
    _hilo_diario.start()
    logger.info("Refresco diario de Google Sheets programado a las %s (Bogotá).", HORA_REFRESCO.strftime("%H:%M"))


def detener_refresco_diario() -> None:
    _detener.set()
