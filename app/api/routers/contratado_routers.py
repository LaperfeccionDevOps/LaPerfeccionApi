from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import text
from infrastructure.db.deps import get_db
from pydantic import BaseModel
from datetime import datetime, timedelta
import traceback
import logging

from utilidades.reporte_synergy_excel import (
    consultar_datos_reporte_synergy,
    normalizar_filas_reporte,
    generar_excel_reporte,
    enriquecer_filas_para_sheet_con_cargo,
)

from utilidades.drive_service import (
    subir_archivo_drive,
    sincronizar_registro_contratacion_dotacion,
)
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[3]
LOG_DIR = BASE_DIR / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)

LOG_FILE = LOG_DIR / "contratado_debug.log"

logger = logging.getLogger("contratado_debug")
logger.setLevel(logging.INFO)

if not logger.handlers:
    handler = logging.FileHandler(LOG_FILE, encoding="utf-8")
    formatter = logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")
    handler.setFormatter(formatter)
    logger.addHandler(handler)

router = APIRouter(prefix="/api", tags=["Contratación - Contratado"])

ESTADO_CONTRATADO = 25


class ContratadoUpdate(BaseModel):
    IdRegistroPersonal: int


@router.put("/contratado")
def marcar_contratado(payload: ContratadoUpdate, db: Session = Depends(get_db)):
    try:
        logger.info("=== INICIO /api/contratado ===")
        logger.info(f"IdRegistroPersonal: {payload.IdRegistroPersonal}")

        # ------------------------------------------------------------
        # 1. Consultar y bloquear el registro para obtener el estado
        #    anterior real dentro de la misma transacción.
        # ------------------------------------------------------------
        registro_actual = db.execute(
            text("""
                SELECT
                    "IdRegistroPersonal",
                    "IdEstadoProceso"
                FROM public."RegistroPersonal"
                WHERE "IdRegistroPersonal" = :id
                FOR UPDATE;
            """),
            {"id": payload.IdRegistroPersonal},
        ).mappings().first()

        if not registro_actual:
            raise HTTPException(
                status_code=404,
                detail="IdRegistroPersonal no existe en RegistroPersonal."
            )

        estado_anterior = registro_actual.get("IdEstadoProceso")

        logger.info(f"Estado anterior: {estado_anterior}")
        logger.info(f"Estado nuevo: {ESTADO_CONTRATADO}")

        # ------------------------------------------------------------
        # 2. Actualizar el estado a CONTRATADO.
        #    Se conserva la lógica actual del botón C.
        # ------------------------------------------------------------
        updated = db.execute(
            text("""
                UPDATE public."RegistroPersonal"
                SET "IdEstadoProceso" = :estado
                WHERE "IdRegistroPersonal" = :id_registro
                RETURNING "IdRegistroPersonal", "IdEstadoProceso";
            """),
            {
                "estado": ESTADO_CONTRATADO,
                "id_registro": payload.IdRegistroPersonal,
            },
        ).mappings().first()

        logger.info(f"Resultado UPDATE: {updated}")

        # ------------------------------------------------------------
        # 3. Registrar la trazabilidad del botón C.
        #
        #    Solo se inserta cuando realmente existe una transición
        #    hacia el estado 25. Si ya estaba en 25, no duplica historial.
        # ------------------------------------------------------------
        historial_contratacion_registrado = False

        if estado_anterior != ESTADO_CONTRATADO:
            historial = db.execute(
                text("""
                    INSERT INTO public."HistorialEstadoContratacion"
                    (
                        "IdRegistroPersonal",
                        "EstadoAnterior",
                        "EstadoNuevo",
                        "FechaMovimiento",
                        "UsuarioMovimiento",
                        "OrigenMovimiento",
                        "Modulo"
                    )
                    VALUES
                    (
                        :id_registro,
                        :estado_anterior,
                        :estado_nuevo,
                        NOW(),
                        :usuario_movimiento,
                        :origen_movimiento,
                        :modulo
                    )
                    RETURNING
                        "IdHistorialEstadoContratacion",
                        "IdRegistroPersonal",
                        "EstadoAnterior",
                        "EstadoNuevo",
                        "FechaMovimiento",
                        "UsuarioMovimiento",
                        "OrigenMovimiento",
                        "Modulo";
                """),
                {
                    "id_registro": payload.IdRegistroPersonal,
                    "estado_anterior": estado_anterior,
                    "estado_nuevo": ESTADO_CONTRATADO,
                    "usuario_movimiento": "contratacion",
                    "origen_movimiento": "BOTON_C",
                    "modulo": "CONTRATACION",
                },
            ).mappings().first()

            historial_contratacion_registrado = historial is not None
            logger.info(f"Historial contratación registrado: {historial}")
        else:
            logger.info(
                "No se registra historial porque el aspirante ya estaba en estado 25."
            )

        # ------------------------------------------------------------
        # 3.1. Cerrar el ciclo de REINTEGRO cuando la contratación
        #      llega al estado CONTRATADO.
        #
        #      Este ajuste es intencionalmente limitado:
        #      - solo aplica al trabajador actual;
        #      - solo aplica a TipoVinculacion = REINTEGRO;
        #      - solo aplica a EstadoVinculacion = EN_PROCESO;
        #      - solo toma el ciclo abierto más reciente;
        #      - no modifica ciclos históricos;
        #      - no modifica contrataciones normales;
        #      - queda dentro de la misma transacción del botón C.
        # ------------------------------------------------------------
        reintegro_activado = db.execute(
            text("""
                UPDATE public."VinculacionLaboral"
                SET
                    "EstadoVinculacion" = 'ACTIVO',
                    "FechaActualizacion" = NOW(),
                    "UsuarioActualizacion" = 'contratacion'
                WHERE "IdVinculacionLaboral" = (
                    SELECT vl."IdVinculacionLaboral"
                    FROM public."VinculacionLaboral" vl
                    WHERE vl."IdRegistroPersonal" = :id_registro
                      AND vl."TipoVinculacion" = 'REINTEGRO'
                      AND vl."EstadoVinculacion" = 'EN_PROCESO'
                    ORDER BY
                        vl."NumeroCiclo" DESC,
                        vl."IdVinculacionLaboral" DESC
                    LIMIT 1
                )
                RETURNING
                    "IdVinculacionLaboral",
                    "IdRegistroPersonal",
                    "NumeroCiclo",
                    "TipoVinculacion",
                    "EstadoVinculacion",
                    "FechaIngreso",
                    "FechaRetiro",
                    "FechaActualizacion",
                    "UsuarioActualizacion";
            """),
            {
                "id_registro": payload.IdRegistroPersonal,
            },
        ).mappings().first()

        if reintegro_activado:
            logger.info(
                "Ciclo de reintegro activado al contratar: "
                f"{dict(reintegro_activado)}"
            )
        else:
            logger.info(
                "No existe ciclo REINTEGRO / EN_PROCESO para activar. "
                "Se conserva el flujo normal de contratación."
            )

        # UPDATE de RegistroPersonal, INSERT del historial y, cuando aplica,
        # activación del ciclo de reintegro quedan confirmados juntos
        # en la misma transacción.
        db.commit()
        logger.info("Commit BD exitoso")

        # ------------------------------------------------------------
        # 4. Flujo existente de Synergy, Excel y Google Sheet.
        #    No se modifica su comportamiento.
        # ------------------------------------------------------------
        hoy = datetime.now().date()
        hace_800_dias = hoy - timedelta(days=800)
        fecha_fin_reporte = hoy + timedelta(days=90)

        logger.info("Consultando datos reporte synergy")
        logger.info(f"Fecha inicio: {hace_800_dias.strftime('%Y-%m-%d')}")
        logger.info(f"Fecha fin: {fecha_fin_reporte.strftime('%Y-%m-%d')}")

        rows = consultar_datos_reporte_synergy(
            db,
            hace_800_dias.strftime("%Y-%m-%d"),
            fecha_fin_reporte.strftime("%Y-%m-%d")
        )

        logger.info(f"Rows obtenidas: {len(rows) if rows else 0}")

        filas = normalizar_filas_reporte(rows)
        logger.info(f"Filas normalizadas: {len(filas) if filas else 0}")

        for fila in filas or []:
            if "1014178009" in str(fila):
                logger.info(f"ANDREA EN FILAS NORMALIZADAS: {fila}")

        filas_excel = filas if filas else [{"sin_datos": "No hay registros"}]
        logger.info(f"Filas para excel: {len(filas_excel) if filas_excel else 0}")

        filas_sheet = enriquecer_filas_para_sheet_con_cargo(db, filas_excel)
        logger.info(f"Filas para sheet: {len(filas_sheet) if filas_sheet else 0}")

        for fila in filas_sheet or []:
            if "1014178009" in str(fila):
                logger.info(f"ANDREA EN FILAS SHEET: {fila}")

        ruta_archivo = generar_excel_reporte(filas_excel)
        logger.info(f"Ruta archivo: {ruta_archivo}")

        archivo_drive = None
        nombre_archivo = None
        archivo_sheet = None

        if ruta_archivo:
            nombre_archivo = ruta_archivo.split("\\")[-1].split("/")[-1]
            logger.info(f"Nombre archivo: {nombre_archivo}")

            logger.info(
                "Saltando subida de Excel a Drive temporalmente para no bloquear Sheet"
            )
            archivo_drive = None

        logger.info("Sincronizando Google Sheet")
        archivo_sheet = sincronizar_registro_contratacion_dotacion(filas_sheet)
        logger.info(f"Respuesta Sheet: {archivo_sheet}")

        logger.info("=== FIN /api/contratado OK ===")

        return {
            "message": "Aspirante marcado como CONTRATADO.",
            "data": updated,
            "historialContratacionRegistrado": historial_contratacion_registrado,
            "estadoAnterior": estado_anterior,
            "nuevoEstado": ESTADO_CONTRATADO,
            "archivoGenerado": nombre_archivo,
            "archivoDrive": {
                "id": archivo_drive["id"] if archivo_drive else None,
                "name": archivo_drive["name"] if archivo_drive else None,
                "webViewLink": archivo_drive["webViewLink"] if archivo_drive else None,
            },
            "archivoSheet": {
                "id": archivo_sheet["id"] if archivo_sheet else None,
                "name": archivo_sheet["name"] if archivo_sheet else None,
                "webViewLink": archivo_sheet["webViewLink"] if archivo_sheet else None,
            }
        }

    except HTTPException:
        db.rollback()
        raise

    except Exception as e:
        logger.error("=== ERROR EN /api/contratado ===")
        logger.error(f"TIPO: {type(e).__name__}")
        logger.error(f"MENSAJE: {str(e)}")
        logger.error(traceback.format_exc())

        db.rollback()

        raise HTTPException(
            status_code=500,
            detail=f"Error en /api/contratado: {str(e)}"
        )