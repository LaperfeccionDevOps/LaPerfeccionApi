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
    preparar_filas_maestro_dotacion,
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

# Únicamente estos cinco documentos bloquean la transición al estado 25.
# Los demás documentos de contratación son opcionales.
DOCUMENTOS_OBLIGATORIOS_CONTRATACION = {
    37: "Constancia de inducción",
    36: "Entrega de dotación",
    65: "Carnet Aseos la Perfección",
    57: "Paquete contratación",
    20: "Descripción del cargo y manual de funciones",
}


def validar_documentos_para_contratar(db: Session, id_registro_personal: int) -> None:
    """Valida documentos con contenido real, exclusivamente del ciclo vigente.

    Sin vinculaciones laborales, mantiene compatibilidad con documentos legacy.
    Si existen vinculaciones, nunca usa archivos sin vinculación ni de ciclos previos.
    """
    vinculacion = db.execute(
        text('''
            SELECT "IdVinculacionLaboral", "EstadoVinculacion"
            FROM public."VinculacionLaboral"
            WHERE "IdRegistroPersonal" = :id
            ORDER BY
                CASE WHEN UPPER(COALESCE("EstadoVinculacion", '')) = 'EN_PROCESO' THEN 0
                     WHEN UPPER(COALESCE("EstadoVinculacion", '')) = 'ACTIVO' THEN 1
                     ELSE 2 END,
                "NumeroCiclo" DESC,
                "IdVinculacionLaboral" DESC
            LIMIT 1
        '''),
        {"id": id_registro_personal},
    ).mappings().first()

    # Un ciclo histórico cerrado no puede utilizarse para una nueva contratación.
    if vinculacion and str(vinculacion["EstadoVinculacion"] or "").strip().upper() not in {"EN_PROCESO", "ACTIVO"}:
        raise HTTPException(
            status_code=409,
            detail="No existe una vinculación laboral vigente para validar los documentos de contratación.",
        )

    filtro = (
        'AND r."IdVinculacionLaboral" = :id_vinculacion'
        if vinculacion else 'AND r."IdVinculacionLaboral" IS NULL'
    )
    documentos = db.execute(
        text(f'''
            SELECT DISTINCT d."IdTipoDocumentacion" AS id_tipo
            FROM public."Documentos" d
            INNER JOIN public."RelacionTipoDocumentacion" r
                ON r."IdDocumento" = d."IdDocumento"
            INNER JOIN public."TipoDocumentacion" t
                ON t."IdTipoDocumentacion" = d."IdTipoDocumentacion"
            WHERE r."IdRegistroPersonal" = :id
              {filtro}
              AND t."IdCategoria" = 7
              AND d."IdTipoDocumentacion" IN (37, 36, 65, 57, 20)
              AND d."DocumentoCargado" IS NOT NULL
              AND OCTET_LENGTH(d."DocumentoCargado") > 0
        '''),
        {
            "id": id_registro_personal,
            "id_vinculacion": vinculacion["IdVinculacionLaboral"] if vinculacion else None,
        },
    ).scalars().all()

    presentes = {int(tipo) for tipo in documentos}
    faltantes = [
        {"id": tipo, "nombre": nombre}
        for tipo, nombre in DOCUMENTOS_OBLIGATORIOS_CONTRATACION.items()
        if tipo not in presentes
    ]
    if faltantes:
        logger.info("Contratación bloqueada por documentos faltantes: %s", faltantes)
        raise HTTPException(
            status_code=409,
            detail={
                "mensaje": "No se puede marcar como contratado: faltan documentos obligatorios.",
                "documentosFaltantes": faltantes,
            },
        )



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

        # No repetir validación para registros ya contratados: preserva la
        # idempotencia y el comportamiento histórico del botón C.
        if estado_anterior != ESTADO_CONTRATADO:
            validar_documentos_para_contratar(db, payload.IdRegistroPersonal)

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

        # ------------------------------------------------------------
        # 4.1. Preparar una sola vez el maestro nuevo de Dotación.
        #
        #      Esta misma estructura se usa tanto para el Excel como
        #      para Google Sheet, evitando que cada salida maneje un
        #      formato diferente. Incluye activos y retiros finalizados.
        # ------------------------------------------------------------
        filas_maestro = preparar_filas_maestro_dotacion(
            filas_excel,
            db,
        )
        logger.info(
            f"Filas maestro Dotación: "
            f"{len(filas_maestro) if filas_maestro else 0}"
        )

        for fila in filas_maestro or []:
            if "1014178009" in str(fila):
                logger.info(f"ANDREA EN FILAS MAESTRO: {fila}")

        # El generador detecta que estas filas ya vienen en formato
        # maestro y conserva exactamente la misma estructura de 121
        # columnas utilizada por Google Sheet.
        ruta_archivo = generar_excel_reporte(
            filas_maestro,
            db=None,
        )
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
        archivo_sheet = sincronizar_registro_contratacion_dotacion(
            filas_maestro
        )
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