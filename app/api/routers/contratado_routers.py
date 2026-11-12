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


class ContratadoUpdate(BaseModel):
    IdRegistroPersonal: int


def _asegurar_vinculacion_antes_de_contratar(
    db: Session, id_registro: int, estado_anterior: int | None
) -> dict | None:
    """Respaldo del botón C cuando falta un ciclo inicial con empresa de RQ.

    No crea ciclos para contrataciones legacy sin RQ ni sobre históricos
    (posibles reintegros). La persona ya está bloqueada FOR UPDATE.
    """
    if estado_anterior not in (24, ESTADO_CONTRATADO):
        return None

    ciclo_existente = db.execute(
        text("""
            SELECT "IdVinculacionLaboral", "EstadoVinculacion",
                   "IdEmpresaContratante"
            FROM public."VinculacionLaboral"
            WHERE "IdRegistroPersonal" = :id_registro
            ORDER BY "NumeroCiclo" DESC, "IdVinculacionLaboral" DESC
            LIMIT 1 FOR UPDATE;
        """),
        {"id_registro": id_registro},
    ).mappings().first()
    if ciclo_existente:
        # Validar que un ciclo EN_PROCESO no vaya a activarse con la empresa
        # equivocada si la RQ fue modificada despues de asociar al candidato.
        if ciclo_existente["EstadoVinculacion"] == "EN_PROCESO":
            empresas_ciclo = db.execute(
                text("""
                    SELECT DISTINCT rq."IdEmpresaContratante"
                    FROM public."RQCandidato" rc
                    JOIN public."RQOperaciones" rq
                      ON rq."IdRQOperaciones" = rc."IdRQOperaciones"
                    JOIN public."EmpresaContratante" ec
                      ON ec."IdEmpresaContratante" = rq."IdEmpresaContratante"
                    WHERE rc."IdRegistroPersonal" = :id_registro
                      AND rc."Activo" = TRUE
                      AND rq."TipoRQ" IN ('PERSONAL_NUEVO', 'REEMPLAZO')
                      AND rq."IdEmpresaContratante" IS NOT NULL
                      AND ec."Activo" = TRUE;
                """),
                {"id_registro": id_registro},
            ).scalars().all()
            if len(empresas_ciclo) > 1:
                raise HTTPException(
                    status_code=409,
                    detail="Hay RQ activas asociadas a distintas empresas.",
                )
            if empresas_ciclo:
                id_empresa_rq = int(empresas_ciclo[0])
                id_empresa_ciclo = ciclo_existente["IdEmpresaContratante"]
                if id_empresa_ciclo is not None and int(id_empresa_ciclo) != id_empresa_rq:
                    raise HTTPException(
                        status_code=409,
                        detail="La empresa de la RQ no coincide con el ciclo EN_PROCESO.",
                    )
                if id_empresa_ciclo is None:
                    db.execute(
                        text("""
                            UPDATE public."VinculacionLaboral"
                            SET "IdEmpresaContratante" = :id_empresa,
                                "FechaActualizacion" = NOW(),
                                "UsuarioActualizacion" = 'contratacion'
                            WHERE "IdVinculacionLaboral" = :id_vinculacion
                              AND "EstadoVinculacion" = 'EN_PROCESO'
                              AND "IdEmpresaContratante" IS NULL;
                        """),
                        {
                            "id_empresa": id_empresa_rq,
                            "id_vinculacion": ciclo_existente["IdVinculacionLaboral"],
                        },
                    )
        # Nunca recrear ciclos historicos ni sobreescribir empresa diferente.
        return {"accion": "CICLO_EXISTENTE_NO_MODIFICADO",
                "IdVinculacionLaboral": int(ciclo_existente["IdVinculacionLaboral"])}

    empresas = db.execute(
        text("""
            SELECT DISTINCT rq."IdEmpresaContratante"
            FROM public."RQCandidato" rc
            JOIN public."RQOperaciones" rq
              ON rq."IdRQOperaciones" = rc."IdRQOperaciones"
            JOIN public."EmpresaContratante" ec
              ON ec."IdEmpresaContratante" = rq."IdEmpresaContratante"
            WHERE rc."IdRegistroPersonal" = :id_registro
              AND rc."Activo" = TRUE
              AND rq."TipoRQ" IN ('PERSONAL_NUEVO', 'REEMPLAZO')
              AND rq."IdEmpresaContratante" IS NOT NULL
              AND ec."Activo" = TRUE;
        """),
        {"id_registro": id_registro},
    ).scalars().all()
    if len(empresas) > 1:
        raise HTTPException(
            status_code=409,
            detail=(
                "Hay RQ activas asociadas a distintas empresas. "
                "No es seguro crear el ciclo laboral automáticamente."
            ),
        )
    if not empresas:
        return {"accion": "SIN_RQ_UNIVOCA", "IdVinculacionLaboral": None}

    # No interpretar como contratación NUEVA a un retirado o migrado
    # cuyo ciclo histórico todavía no se haya cargado en QA.
    antecedente_laboral = db.execute(
        text("""
            SELECT (
                EXISTS (
                    SELECT 1 FROM public."RetiroLaboral"
                    WHERE "IdRegistroPersonal" = :id_registro
                )
                OR EXISTS (
                    SELECT 1 FROM public."RegistroPersonal"
                    WHERE "IdRegistroPersonal" = :id_registro
                      AND "FechaIngresoHistorica" IS NOT NULL
                )
            ) AS "EsHistorico";
        """),
        {"id_registro": id_registro},
    ).scalar()
    if antecedente_laboral:
        return {"accion": "HISTORICO_NO_MODIFICADO", "IdVinculacionLaboral": None}

    id_empresa = int(empresas[0])
    nuevo_ciclo = db.execute(
        text("""
            INSERT INTO public."VinculacionLaboral"
            (
                "IdRegistroPersonal", "NumeroCiclo", "TipoVinculacion",
                "EstadoVinculacion", "FechaInicioProceso", "FechaIngreso",
                "FechaRetiro", "IdCargo", "IdCliente", "Salario",
                "IdTipoContrato", "FechaCreacion", "FechaActualizacion",
                "UsuarioActualizacion", "IdEmpresaContratante"
            )
            VALUES
            (
                :id_registro, 1, 'NUEVO', 'EN_PROCESO', NOW(),
                NULL, NULL, NULL, NULL, NULL, NULL,
                NOW(), NOW(), 'contratacion', :id_empresa
            )
            RETURNING "IdVinculacionLaboral";
        """),
        {"id_registro": id_registro, "id_empresa": id_empresa},
    ).scalar_one()
    return {
        "accion": "CICLO_CREADO_DESDE_RQ",
        "IdVinculacionLaboral": int(nuevo_ciclo),
        "IdEmpresaContratante": id_empresa,
    }


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

        # Respaldo para flujos que llegaron a 24/25 sin vinculación inicial.
        # Si existe una RQ inequívoca, crea el ciclo antes de activarlo.
        # Los históricos y reintegros se conservan sin alteraciones.
        vinculacion_respaldo = _asegurar_vinculacion_antes_de_contratar(
            db, payload.IdRegistroPersonal, estado_anterior
        )
        if vinculacion_respaldo:
            logger.info(f"Respaldo vinculación desde RQ: {vinculacion_respaldo}")

        # ------------------------------------------------------------
        # 3.1. Consolidar el ciclo laboral actual cuando la contratación
        #      llega al estado CONTRATADO.
        #
        #      Aplica tanto para:
        #      - NUEVO / EN_PROCESO
        #      - REINTEGRO / EN_PROCESO
        #
        #      Reglas de seguridad:
        #      - solo aplica al trabajador actual;
        #      - solo toma el ciclo EN_PROCESO más reciente;
        #      - no modifica ciclos históricos;
        #      - no modifica IdEmpresaContratante;
        #      - conserva NumeroCiclo y TipoVinculacion;
        #      - toma FechaIngreso e IdTipoContrato de ContratacionBasica;
        #      - toma IdCargo, IdCliente y Salario de la asignación actual;
        #      - queda dentro de la misma transacción del botón C.
        # ------------------------------------------------------------
        ciclo_activado = db.execute(
            text("""
                WITH ciclo_actual AS (
                    SELECT vl."IdVinculacionLaboral"
                    FROM public."VinculacionLaboral" vl
                    WHERE vl."IdRegistroPersonal" = :id_registro
                      AND vl."TipoVinculacion" IN ('NUEVO', 'REINTEGRO')
                      AND vl."EstadoVinculacion" = 'EN_PROCESO'
                    ORDER BY
                        vl."NumeroCiclo" DESC,
                        vl."IdVinculacionLaboral" DESC
                    LIMIT 1
                    FOR UPDATE
                ),
                contratacion_actual AS (
                    SELECT
                        cb."FechaIngreso",
                        cb."IdTipoContrato"
                    FROM public."ContratacionBasica" cb
                    WHERE cb."IdRegistroPersonal" = :id_registro
                    ORDER BY cb."IdContratacionBasica" DESC
                    LIMIT 1
                ),
                asignacion_actual AS (
                    SELECT
                        acc."IdCargo",
                        acc."IdCliente",
                        acc."Salario"
                    FROM public."AsignacionCargoCliente" acc
                    WHERE acc."IdRegistroPersonal" = :id_registro
                    ORDER BY acc."IdAsignacionCargoCliente" DESC
                    LIMIT 1
                )
                UPDATE public."VinculacionLaboral" vl
                SET
                    "FechaIngreso" = COALESCE(
                        ca."FechaIngreso",
                        vl."FechaIngreso"
                    ),
                    "IdCargo" = COALESCE(
                        aa."IdCargo",
                        vl."IdCargo"
                    ),
                    "IdCliente" = COALESCE(
                        aa."IdCliente",
                        vl."IdCliente"
                    ),
                    "Salario" = COALESCE(
                        aa."Salario",
                        vl."Salario"
                    ),
                    "IdTipoContrato" = COALESCE(
                        ca."IdTipoContrato",
                        vl."IdTipoContrato"
                    ),
                    "EstadoVinculacion" = 'ACTIVO',
                    "FechaActualizacion" = NOW(),
                    "UsuarioActualizacion" = 'contratacion'
                FROM ciclo_actual cc
                LEFT JOIN contratacion_actual ca ON TRUE
                LEFT JOIN asignacion_actual aa ON TRUE
                WHERE vl."IdVinculacionLaboral" = cc."IdVinculacionLaboral"
                RETURNING
                    vl."IdVinculacionLaboral",
                    vl."IdRegistroPersonal",
                    vl."NumeroCiclo",
                    vl."TipoVinculacion",
                    vl."EstadoVinculacion",
                    vl."FechaIngreso",
                    vl."FechaRetiro",
                    vl."IdCargo",
                    vl."IdCliente",
                    vl."Salario",
                    vl."IdTipoContrato",
                    vl."IdEmpresaContratante",
                    vl."FechaActualizacion",
                    vl."UsuarioActualizacion";
            """),
            {
                "id_registro": payload.IdRegistroPersonal,
            },
        ).mappings().first()

        if ciclo_activado:
            logger.info(
                "Ciclo laboral activado al contratar: "
                f"{dict(ciclo_activado)}"
            )
        else:
            logger.info(
                "No existe ciclo NUEVO/REINTEGRO EN_PROCESO para activar. "
                "Se conserva compatibilidad con registros históricos."
            )

        # UPDATE de RegistroPersonal, INSERT del historial y, cuando aplica,
        # consolidación/activación del ciclo laboral quedan confirmados juntos
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
            "vinculacionRQ": vinculacion_respaldo,
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