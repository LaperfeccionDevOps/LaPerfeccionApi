# api/routers/datos_seleccion_routers.py
from datetime import datetime, timezone
from typing import Any, Optional
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Body
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
from sqlalchemy import text

from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill
from openpyxl.chart import PieChart, Reference, LineChart, BarChart
from openpyxl.chart.label import DataLabelList

from domain.schemas.registro_personal_update_schema import RegistroPersonalUpdateRequest
from repositories.registro_personal_repo import RegistroPersonalRepository
from infrastructure.db.deps import get_db
from services.datos_seleccion_service import DatosSeleccionService
from domain.schemas.datos_seleccion_schema import (
    DatosSeleccionUpsertRequest,
    DatosSeleccionResponse,
)


router = APIRouter(prefix="/api/datos-seleccion", tags=["datos-seleccion"])
service = DatosSeleccionService()
registro_personal_repo = RegistroPersonalRepository()


@router.put("/registro-personal/{id_registro_personal}")
def actualizar_registro_personal(
    id_registro_personal: int,
    body: RegistroPersonalUpdateRequest = Body(...),
    db: Session = Depends(get_db)
):
    data = body.model_dump(exclude_none=True)
    if not data:
        raise HTTPException(status_code=400, detail="No hay datos para actualizar")

    data_registro = {
        k: v for k, v in data.items()
        if k not in ("DireccionDatosAdicionales", "IdGrupoSanguineo")
    }

    if data_registro:
        updated = registro_personal_repo.update_by_id(db, id_registro_personal, data_registro)
        if updated == 0:
            raise HTTPException(status_code=404, detail="No se encontró el registro personal")

    if "DireccionDatosAdicionales" in data:
        updated_datos = registro_personal_repo.update_direccion_datos_adicionales(
            db,
            id_registro_personal,
            data["DireccionDatosAdicionales"],
            data.get("IdGrupoSanguineo", 0)
        )
        if updated_datos == 0:
            raise HTTPException(status_code=404, detail="No se encontró DatosAdicionales para este registro personal")

    return {"ok": True, "message": "Registro actualizado", "IdRegistroPersonal": id_registro_personal}


def _parse_bool(value: Any) -> Optional[bool]:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        s = value.strip().lower()
        if s in ("si", "sí", "true", "1"):
            return True
        if s in ("no", "false", "0"):
            return False
    return None


def _normalizar_estado_dashboard(estado: Any) -> str:
    estado = str(estado or "").strip().upper()
    estado = estado.replace("CONTRATACION", "CONTRATACIÓN")
    estado = estado.replace("EXAMENES", "EXÁMENES")
    estado = estado.replace("REFERENCIACION", "REFERENCIACIÓN")

    if estado.startswith("AVANZA"):
        return "AVANZA A CONTRATACIÓN"
    if estado.startswith("ENTREVISTA"):
        return "ENTREVISTA JEFE INMEDIATO" if "JEFE" in estado else "ENTREVISTA"
    if estado.startswith("PENDIENTE"):
        return "PENDIENTE DE CONTRATACIÓN"
    if estado.startswith("CONTRATADO"):
        return "CONTRATADO"
    if estado.startswith("RECHAZADO"):
        return "RECHAZADO"
    if estado.startswith("DESISTE"):
        return "DESISTE DEL PROCESO"
    if estado.startswith("SEGURIDAD"):
        return "SEGURIDAD"
    if estado.startswith("NUEVO"):
        return "NUEVO"
    if estado.startswith("REFERENCIACIÓN"):
        return "REFERENCIACIÓN"
    if estado.startswith("EXÁMENES"):
        return "EXÁMENES"
    if estado.startswith("ABIERTO"):
        return "ABIERTO"

    return estado or "SIN ESTADO"


def _normalizar_motivo_dashboard(motivo: Any) -> str:
    motivo = str(motivo or "").strip().upper()
    motivo = motivo.replace("CONTRATACION", "CONTRATACIÓN")
    motivo = motivo.replace("EXAMENES", "EXÁMENES")
    motivo = motivo.replace("DOCUMENTACION", "DOCUMENTACIÓN")
    return motivo


def _es_rechazo_contratacion(motivo: Any) -> bool:
    motivo_normalizado = _normalizar_motivo_dashboard(motivo)
    if not motivo_normalizado or motivo_normalizado == "SIN_MOTIVO":
        return False
    return "CONTRATACIÓN" in motivo_normalizado


@router.get("/dashboard-indicadores")
def obtener_dashboard_indicadores_contratacion(
    anio: Optional[int] = None,
    mes: Optional[int] = None,
    db: Session = Depends(get_db)
):
    rows = db.execute(text("""
        SELECT
            rp."IdEstadoProceso",
            COALESCE(rp."FechaActualizacion", rp."FechaCreacion") AS fecha_registro,
            mcp."MotivoCierre" AS motivo_rechazo,
            CASE rp."IdEstadoProceso"
                WHEN 18 THEN 'NUEVO'
                WHEN 19 THEN 'ENTREVISTA'
                WHEN 20 THEN 'ENTREVISTA JEFE INMEDIATO'
                WHEN 21 THEN 'EXÁMENES'
                WHEN 22 THEN 'SEGURIDAD'
                WHEN 24 THEN 'AVANZA A CONTRATACIÓN'
                WHEN 25 THEN 'CONTRATADO'
                WHEN 26 THEN 'REFERENCIACIÓN'
                WHEN 27 THEN 'DESISTE DEL PROCESO'
                WHEN 28 THEN 'RECHAZADO'
                WHEN 30 THEN 'ABIERTO'
                WHEN 34 THEN 'PENDIENTE DE CONTRATACIÓN'
                ELSE CONCAT('ESTADO ', rp."IdEstadoProceso")
            END AS estado
        FROM public."RegistroPersonal" rp
        LEFT JOIN (
            SELECT DISTINCT ON ("IdRegistroPersonal")
                "IdRegistroPersonal",
                "MotivoCierre",
                "FechaCreacion"
            FROM public."MotivoCierreProceso"
            ORDER BY "IdRegistroPersonal", "FechaCreacion" DESC
        ) mcp
            ON mcp."IdRegistroPersonal" = rp."IdRegistroPersonal"
        WHERE
                COALESCE(rp."UsuarioActualizacion",'') <> 'ajuste_no_activos_maestro_2026_06_22'
                AND (:anio IS NULL OR EXTRACT(YEAR FROM COALESCE(rp."FechaActualizacion", rp."FechaCreacion")) = :anio)
                AND (:mes IS NULL OR EXTRACT(MONTH FROM COALESCE(rp."FechaActualizacion", rp."FechaCreacion")) = :mes)
    """), {
        "anio": anio,
        "mes": mes,
    }).mappings().all()

    filas = [dict(r) for r in rows]

    estados_base = [
        "NUEVO",
        "ENTREVISTA",
        "ENTREVISTA JEFE INMEDIATO",
        "EXÁMENES",
        "SEGURIDAD",
        "AVANZA A CONTRATACIÓN",
        "REFERENCIACIÓN",
        "DESISTE DEL PROCESO",
        "RECHAZADO",
        "PENDIENTE DE CONTRATACIÓN",
        "CONTRATADO",
        "ABIERTO",
    ]

    conteo_estados = {estado: 0 for estado in estados_base}

    for fila in filas:
        estado = _normalizar_estado_dashboard(fila.get("estado"))
        if estado not in conteo_estados:
            conteo_estados[estado] = 0
        conteo_estados[estado] += 1

    total = len(filas)

    estados_ordenados = estados_base + [
        estado for estado in conteo_estados.keys()
        if estado not in estados_base
    ]

    estados = [
        {
            "estado": estado,
            "cantidad": conteo_estados.get(estado, 0),
            "porcentaje": round((conteo_estados.get(estado, 0) / total) * 100) if total else 0,
        }
        for estado in estados_ordenados
    ]

    meses_nombre = {
        1: "enero", 2: "febrero", 3: "marzo", 4: "abril",
        5: "mayo", 6: "junio", 7: "julio", 8: "agosto",
        9: "septiembre", 10: "octubre", 11: "noviembre", 12: "diciembre",
    }

    registros_por_mes = {}

    for fila in filas:
        fecha = fila.get("fecha_registro")
        if isinstance(fecha, datetime):
            clave = fecha.strftime("%Y-%m")
            etiqueta = f"{meses_nombre[fecha.month]}-{str(fecha.year)[-2:]}"
        else:
            clave = "9999-99"
            etiqueta = "Sin fecha"

        if clave not in registros_por_mes:
            registros_por_mes[clave] = {"mes": etiqueta, "registros": 0}

        registros_por_mes[clave]["registros"] += 1

    registros_por_mes = dict(sorted(registros_por_mes.items()))

    motivos_base = [
        "Desiste del Proceso",
        "No Cumple Perfil",
        "No asiste a Examenes Medicos",
        "Examenes No Aptos",
        "Documentacion Incompleta",
        "No asiste a Contratacion",
    ]

    equivalencias_motivos = {
        "DESISTE DEL PROCESO": "Desiste del Proceso",
        "NO CUMPLE PERFIL": "No Cumple Perfil",
        "NO ASISTE A EXAMENES MEDICOS": "No asiste a Examenes Medicos",
        "NO ASISTE A EXÁMENES MEDICOS": "No asiste a Examenes Medicos",
        "NO ASISTE A EXÁMENES MÉDICOS": "No asiste a Examenes Medicos",
        "EXAMENES NO APTOS": "Examenes No Aptos",
        "EXÁMENES NO APTOS": "Examenes No Aptos",
        "DOCUMENTACION INCOMPLETA": "Documentacion Incompleta",
        "DOCUMENTACIÓN INCOMPLETA": "Documentacion Incompleta",
        "NO ASISTE A CONTRATACION": "No asiste a Contratacion",
        "NO ASISTE A CONTRATACIÓN": "No asiste a Contratacion",
    }

    motivos_generales = {motivo: 0 for motivo in motivos_base}
    motivos_contratacion = {"No asiste a Contratacion": 0}
    rechazados_contratacion = 0

    for fila in filas:
        estado = _normalizar_estado_dashboard(fila.get("estado"))
        motivo = fila.get("motivo_rechazo")

        if estado == "RECHAZADO" and motivo and str(motivo).strip().upper() != "SIN_MOTIVO":
            clave = _normalizar_motivo_dashboard(motivo)
            motivo_final = equivalencias_motivos.get(clave, str(motivo).strip())

            if motivo_final not in motivos_generales:
                motivos_generales[motivo_final] = 0

            motivos_generales[motivo_final] += 1

            if _es_rechazo_contratacion(motivo):
                rechazados_contratacion += 1

                if motivo_final not in motivos_contratacion:
                    motivos_contratacion[motivo_final] = 0

                motivos_contratacion[motivo_final] += 1

    total_motivos_generales = sum(motivos_generales.values())
    total_motivos_contratacion = sum(motivos_contratacion.values())

    motivos_rechazo_generales = [
        {
            "motivo": motivo,
            "cantidad": cantidad,
            "porcentaje": round((cantidad / total_motivos_generales) * 100) if total_motivos_generales else 0,
        }
        for motivo, cantidad in motivos_generales.items()
    ]

    motivos_rechazo_contratacion = [
        {
            "motivo": motivo,
            "cantidad": cantidad,
            "porcentaje": round((cantidad / total_motivos_contratacion) * 100) if total_motivos_contratacion else 0,
        }
        for motivo, cantidad in motivos_contratacion.items()
    ]

    contratados = conteo_estados.get("CONTRATADO", 0)
    rechazados_generales = conteo_estados.get("RECHAZADO", 0)
    desistidos = conteo_estados.get("DESISTE DEL PROCESO", 0)
    pendiente_contratacion = conteo_estados.get("PENDIENTE DE CONTRATACIÓN", 0)
    avanza_contratacion = conteo_estados.get("AVANZA A CONTRATACIÓN", 0)

    en_proceso = total - contratados - rechazados_generales - desistidos
    if en_proceso < 0:
        en_proceso = 0

    total_personas_avanzadas_contratacion = contratados + rechazados_contratacion

    return {
        "filtros": {"anio": anio, "mes": mes},
        "total": total,
        "rechazados_generales": rechazados_generales,
        "desistidos": desistidos,
        "en_proceso": en_proceso,
        "pendiente_contratacion": pendiente_contratacion,
        "avanza_contratacion": avanza_contratacion,
        "estados": estados,
        "estados_con_datos": [item for item in estados if item["cantidad"] > 0],
        "registros_por_mes": list(registros_por_mes.values()),
        "motivos_rechazo_generales": motivos_rechazo_generales,
        "motivos_rechazo_generales_con_datos": [
            item for item in motivos_rechazo_generales if item["cantidad"] > 0
        ],
        "total_personas_avanzadas_contratacion": total_personas_avanzadas_contratacion,
        "contratados": contratados,
        "rechazados": rechazados_contratacion,
        "motivos_rechazo": motivos_rechazo_contratacion,
        "motivos_rechazo_con_datos": [
            item for item in motivos_rechazo_contratacion if item["cantidad"] > 0
        ],
    }

# ============================================================
# DASHBOARD EXCLUSIVO DE CONTRATACIÓN
# ============================================================
# Este bloque es independiente del dashboard de Selección.
#
# No modifica:
# - Flujo de contratación
# - Endpoint /api/contratado
# - Endpoint /api/rechazo-contratacion
# - Reporte Synergy
# - Excel
# - Drive
# - Google Sheet
#
# Criterios temporales de la consulta general:
# - Registrados: RegistroPersonal.FechaCreacion.
# - Avanzan: fecha real del movimiento al estado 24.
# - Contratados: fecha real del movimiento al estado 25 por botón C.
# - Tiempo promedio: contrataciones finalizadas en el periodo consultado.
#
# Consulta individual:
# - El usuario busca visualmente por nombre o identificación.
# - El frontend conserva internamente IdRegistroPersonal.
# - El detalle individual consulta el historial completo del trabajador.
# ============================================================


def _formatear_duracion_segundos(total_segundos: Optional[int]) -> Optional[str]:
    """Convierte segundos a una duración legible en español."""
    if total_segundos is None:
        return None

    total_segundos = max(int(total_segundos), 0)
    dias, resto = divmod(total_segundos, 86400)
    horas, resto = divmod(resto, 3600)
    minutos, segundos = divmod(resto, 60)

    partes = []

    if dias > 0:
        partes.append(f"{dias} día" if dias == 1 else f"{dias} días")

    if horas > 0:
        partes.append(f"{horas} hora" if horas == 1 else f"{horas} horas")

    if minutos > 0:
        partes.append(
            f"{minutos} minuto" if minutos == 1 else f"{minutos} minutos"
        )

    # En tiempos de varios días se prioriza una lectura ejecutiva.
    # Para tiempos menores a un día se conservan también los segundos.
    if dias == 0 and (segundos > 0 or not partes):
        partes.append(
            f"{segundos} segundo" if segundos == 1 else f"{segundos} segundos"
        )

    return ", ".join(partes)


def _nombre_estado_proceso(id_estado: Optional[int]) -> str:
    estados = {
        18: "Nuevo",
        19: "Entrevista",
        20: "Entrevista jefe inmediato",
        21: "Exámenes",
        22: "Seguridad",
        24: "Avanza a contratación",
        25: "Contratado",
        26: "Referenciación",
        27: "Desiste del proceso",
        28: "Rechazado",
        30: "Abierto",
        34: "Pendiente de contratación",
    }
    return estados.get(id_estado, f"Estado {id_estado}" if id_estado else "Sin estado")


@router.get("/buscar-trabajadores-contratacion")
def buscar_trabajadores_dashboard_contratacion(
    texto_busqueda: str,
    limite: int = 20,
    db: Session = Depends(get_db),
):
    """
    Busca candidatos por nombre, apellido o número de identificación.

    El IdRegistroPersonal se devuelve únicamente para uso interno del frontend.
    En la interfaz se debe mostrar nombre completo y número de identificación.
    """
    texto_limpio = (texto_busqueda or "").strip()

    if len(texto_limpio) < 2:
        raise HTTPException(
            status_code=400,
            detail="Escriba al menos 2 caracteres para buscar.",
        )

    limite_seguro = min(max(limite, 1), 50)
    patron = f"%{texto_limpio}%"

    rows = db.execute(
        text("""
            SELECT
                rp."IdRegistroPersonal" AS id_registro_personal,
                TRIM(
                    CONCAT_WS(
                        ' ',
                        NULLIF(TRIM(rp."Nombres"), ''),
                        NULLIF(TRIM(rp."Apellidos"), '')
                    )
                ) AS nombre_completo,
                rp."NumeroIdentificacion"::text AS numero_identificacion,
                rp."IdEstadoProceso" AS id_estado_proceso
            FROM public."RegistroPersonal" rp
            WHERE
                NOT EXISTS (
                    SELECT 1
                    FROM public."HistorialLaboral" hl
                    WHERE
                        hl."IdRegistroPersonal" = rp."IdRegistroPersonal"
                        AND UPPER(TRIM(COALESCE(hl."TipoVinculacion", ''))) = 'ACTIVO MIGRADO'
                )
                AND LOWER(COALESCE(rp."UsuarioActualizacion", '')) NOT LIKE '%migracion%'
                AND LOWER(COALESCE(rp."UsuarioActualizacion", '')) NOT LIKE '%migrado%'
                AND COALESCE(rp."UsuarioActualizacion", '')
                    <> 'ajuste_no_activos_maestro_2026_06_22'
                AND (
                    rp."NumeroIdentificacion"::text ILIKE :patron
                    OR CONCAT_WS(
                        ' ',
                        COALESCE(rp."Nombres", ''),
                        COALESCE(rp."Apellidos", '')
                    ) ILIKE :patron
                    OR COALESCE(rp."Nombres", '') ILIKE :patron
                    OR COALESCE(rp."Apellidos", '') ILIKE :patron
                )
            ORDER BY
                CASE
                    WHEN rp."NumeroIdentificacion"::text = :texto_exacto THEN 0
                    ELSE 1
                END,
                nombre_completo ASC,
                rp."IdRegistroPersonal" DESC
            LIMIT :limite;
        """),
        {
            "patron": patron,
            "texto_exacto": texto_limpio,
            "limite": limite_seguro,
        },
    ).mappings().all()

    resultados = []
    for row in rows:
        item = dict(row)
        item["estado_actual"] = _nombre_estado_proceso(
            item.get("id_estado_proceso")
        )
        resultados.append(item)

    return {
        "texto_busqueda": texto_limpio,
        "total_resultados": len(resultados),
        "resultados": resultados,
    }


def _obtener_dashboard_contratacion_individual(
    id_registro_personal: int,
    db: Session,
):
    trabajador = db.execute(
        text("""
            SELECT
                rp."IdRegistroPersonal" AS id_registro_personal,
                TRIM(
                    CONCAT_WS(
                        ' ',
                        NULLIF(TRIM(rp."Nombres"), ''),
                        NULLIF(TRIM(rp."Apellidos"), '')
                    )
                ) AS nombre_completo,
                rp."NumeroIdentificacion"::text AS numero_identificacion,
                rp."IdEstadoProceso" AS id_estado_proceso,
                rp."FechaCreacion" AS fecha_registro_seleccion
            FROM public."RegistroPersonal" rp
            WHERE
                rp."IdRegistroPersonal" = :id_registro_personal
                AND NOT EXISTS (
                    SELECT 1
                    FROM public."HistorialLaboral" hl
                    WHERE
                        hl."IdRegistroPersonal" = rp."IdRegistroPersonal"
                        AND UPPER(TRIM(COALESCE(hl."TipoVinculacion", ''))) = 'ACTIVO MIGRADO'
                )
                AND LOWER(COALESCE(rp."UsuarioActualizacion", '')) NOT LIKE '%migracion%'
                AND LOWER(COALESCE(rp."UsuarioActualizacion", '')) NOT LIKE '%migrado%'
                AND COALESCE(rp."UsuarioActualizacion", '')
                    <> 'ajuste_no_activos_maestro_2026_06_22';
        """),
        {"id_registro_personal": id_registro_personal},
    ).mappings().first()

    if not trabajador:
        raise HTTPException(
            status_code=404,
            detail=(
                "No se encontró el trabajador o el registro está excluido "
                "por corresponder a información migrada."
            ),
        )

    trazabilidad = db.execute(
        text("""
            WITH fecha_25 AS (
                SELECT MIN(hec."FechaMovimiento") AS fecha_estado_25
                FROM public."HistorialEstadoContratacion" hec
                WHERE
                    hec."IdRegistroPersonal" = :id_registro_personal
                    AND hec."EstadoNuevo" = 25
                    AND hec."OrigenMovimiento" = 'BOTON_C'
                    AND hec."Modulo" = 'CONTRATACION'
            ),
            fecha_24 AS (
                SELECT MAX(hec."FechaMovimiento") AS fecha_estado_24
                FROM public."HistorialEstadoContratacion" hec
                CROSS JOIN fecha_25 f25
                WHERE
                    hec."IdRegistroPersonal" = :id_registro_personal
                    AND hec."EstadoNuevo" = 24
                    AND hec."OrigenMovimiento" = 'CAMBIO_ESTADO'
                    AND hec."Modulo" = 'SELECCION'
                    AND (
                        f25.fecha_estado_25 IS NULL
                        OR hec."FechaMovimiento" <= f25.fecha_estado_25
                    )
            )
            SELECT
                f24.fecha_estado_24,
                f25.fecha_estado_25,
                CASE
                    WHEN f24.fecha_estado_24 IS NOT NULL
                         AND f25.fecha_estado_25 IS NOT NULL
                    THEN EXTRACT(
                        EPOCH FROM (f25.fecha_estado_25 - f24.fecha_estado_24)
                    )
                    ELSE NULL
                END AS tiempo_segundos
            FROM fecha_24 f24
            CROSS JOIN fecha_25 f25;
        """),
        {"id_registro_personal": id_registro_personal},
    ).mappings().first()

    rechazo = db.execute(
        text("""
            SELECT
                hec."FechaMovimiento" AS fecha_rechazo,
                hec."UsuarioMovimiento" AS usuario_rechazo,
                hec."OrigenMovimiento" AS origen_movimiento,
                CASE
                    WHEN hec."OrigenMovimiento" = 'BOTON_NC'
                    THEN COALESCE(
                        NULLIF(TRIM(orc."ObservacionesRechazo"), ''),
                        'Sin observación'
                    )
                    WHEN hec."OrigenMovimiento" = 'HISTORICO_MOTIVO_CIERRE'
                    THEN COALESCE(
                        NULLIF(TRIM(mcp."MotivoCierre"), ''),
                        'Sin motivo de cierre'
                    )
                    ELSE 'Sin motivo'
                END AS motivo_rechazo
            FROM public."HistorialEstadoContratacion" hec
            LEFT JOIN LATERAL (
                SELECT orc_detalle."ObservacionesRechazo"
                FROM public."ObsRechazoContratacion" orc_detalle
                WHERE
                    orc_detalle."IdRegistroPersonal"
                        = hec."IdRegistroPersonal"
                ORDER BY
                    orc_detalle."IdObsRechazoContratacion" DESC
                LIMIT 1
            ) orc ON hec."OrigenMovimiento" = 'BOTON_NC'
            LEFT JOIN LATERAL (
                SELECT mcp_detalle."MotivoCierre"
                FROM public."MotivoCierreProceso" mcp_detalle
                WHERE
                    mcp_detalle."IdRegistroPersonal"
                        = hec."IdRegistroPersonal"
                ORDER BY
                    COALESCE(
                        mcp_detalle."FechaActualizacion",
                        mcp_detalle."FechaCreacion"
                    ) DESC,
                    mcp_detalle."IdMotivoCierre" DESC
                LIMIT 1
            ) mcp
                ON hec."OrigenMovimiento" = 'HISTORICO_MOTIVO_CIERRE'
            WHERE
                hec."IdRegistroPersonal" = :id_registro_personal
                AND hec."EstadoNuevo" = 28
                AND hec."OrigenMovimiento" IN (
                    'BOTON_NC',
                    'HISTORICO_MOTIVO_CIERRE'
                )
                AND hec."Modulo" = 'CONTRATACION'
            ORDER BY
                hec."FechaMovimiento" DESC,
                hec."IdHistorialEstadoContratacion" DESC
            LIMIT 1;
        """),
        {"id_registro_personal": id_registro_personal},
    ).mappings().first()

    datos_trabajador = dict(trabajador)
    fecha_estado_24 = trazabilidad.get("fecha_estado_24") if trazabilidad else None
    fecha_estado_25 = trazabilidad.get("fecha_estado_25") if trazabilidad else None
    tiempo_segundos_raw = trazabilidad.get("tiempo_segundos") if trazabilidad else None
    tiempo_segundos = (
        int(round(float(tiempo_segundos_raw)))
        if tiempo_segundos_raw is not None
        else None
    )

    id_estado_actual = datos_trabajador.get("id_estado_proceso")
    fecha_rechazo = rechazo.get("fecha_rechazo") if rechazo else None
    usuario_rechazo = rechazo.get("usuario_rechazo") if rechazo else None
    origen_movimiento_rechazo = (
        rechazo.get("origen_movimiento") if rechazo else None
    )
    motivo_rechazo = rechazo.get("motivo_rechazo") if rechazo else None
    fue_rechazado = rechazo is not None

    return {
        "modo_consulta": "individual",
        "trabajador": {
            "id_registro_personal": datos_trabajador.get("id_registro_personal"),
            "nombre_completo": datos_trabajador.get("nombre_completo"),
            "numero_identificacion": datos_trabajador.get("numero_identificacion"),
            "id_estado_actual": id_estado_actual,
            "estado_actual": _nombre_estado_proceso(id_estado_actual),
        },
        "registro_seleccion": {
            "existe": datos_trabajador.get("fecha_registro_seleccion") is not None,
            "fecha": datos_trabajador.get("fecha_registro_seleccion"),
        },
        "avance_contratacion": {
            "existe": fecha_estado_24 is not None,
            "fecha": fecha_estado_24,
        },
        "contratacion": {
            "existe": fecha_estado_25 is not None,
            "fecha": fecha_estado_25,
            "confirmada_por_boton_c": fecha_estado_25 is not None,
        },
        "rechazo": {
            "existe": fue_rechazado,
            "fecha": fecha_rechazo,
            "usuario": usuario_rechazo,
            "origen_movimiento": origen_movimiento_rechazo,
            "motivo": motivo_rechazo,
            "fuente": "HistorialEstadoContratacion",
        },
        "tiempo_contratacion": {
            "total_segundos": tiempo_segundos,
            "total_minutos": (
                round(tiempo_segundos / 60, 2)
                if tiempo_segundos is not None
                else None
            ),
            "formateado": _formatear_duracion_segundos(tiempo_segundos),
            "disponible": tiempo_segundos is not None,
            "fecha_inicio": fecha_estado_24,
            "fecha_fin": fecha_estado_25,
            "fuente_inicio": "Estado 24 - CAMBIO_ESTADO - SELECCION",
            "fuente_fin": "Estado 25 - BOTON_C - CONTRATACION",
            "mensaje": (
                "Tiempo real del trabajador entre el avance a contratación "
                "y la confirmación mediante el botón C."
                if tiempo_segundos is not None
                else
                "El trabajador todavía no tiene una trazabilidad completa "
                "entre los estados 24 y 25 mediante el botón C."
            ),
        },
        "linea_tiempo": [
            {
                "evento": "Registro en Selección",
                "completado": datos_trabajador.get("fecha_registro_seleccion") is not None,
                "fecha": datos_trabajador.get("fecha_registro_seleccion"),
            },
            {
                "evento": "Avanza a Contratación",
                "completado": fecha_estado_24 is not None,
                "fecha": fecha_estado_24,
            },
            {
                "evento": "Contratado",
                "completado": fecha_estado_25 is not None,
                "fecha": fecha_estado_25,
            },
            {
                "evento": "Rechazado en Contratación",
                "completado": fue_rechazado,
                "fecha": fecha_rechazo,
                "usuario": usuario_rechazo,
                "origen_movimiento": origen_movimiento_rechazo,
                "motivo": motivo_rechazo,
            },
        ],
        "exclusiones": {
            "activo_migrado_historial_laboral": True,
            "usuarios_migracion": True,
            "ajuste_no_activos_maestro": True,
        },
    }


@router.get("/dashboard-contratacion")
def obtener_dashboard_contratacion(
    anio: Optional[int] = None,
    mes: Optional[int] = None,
    id_registro_personal: Optional[int] = None,
    db: Session = Depends(get_db),
):
    """
    Dashboard independiente para el módulo de Contratación.

    Consulta general:
    - Registrados por Selección: RegistroPersonal.FechaCreacion.
    - Avanzan a Contratación: movimiento al estado 24.
    - Contratados: movimiento al estado 25 mediante el botón C.
    - Tiempo promedio: diferencia 24 a 25 de los casos contratados
      dentro del periodo consultado.

    Consulta individual:
    - Se recibe IdRegistroPersonal internamente después de que el usuario
      selecciona un resultado buscado por nombre o identificación.
    - Se consulta el historial completo del trabajador, sin limitar sus
      eventos por año o mes.
    """
    if mes is not None and (mes < 1 or mes > 12):
        raise HTTPException(
            status_code=400,
            detail="El mes debe estar entre 1 y 12.",
        )

    if anio is not None and anio < 2000:
        raise HTTPException(
            status_code=400,
            detail="El año consultado no es válido.",
        )

    if id_registro_personal is not None:
        if id_registro_personal <= 0:
            raise HTTPException(
                status_code=400,
                detail="El IdRegistroPersonal consultado no es válido.",
            )
        return _obtener_dashboard_contratacion_individual(
            id_registro_personal=id_registro_personal,
            db=db,
        )

    resultado = db.execute(
        text("""
            WITH universo_base AS (
                SELECT
                    rp."IdRegistroPersonal",
                    rp."IdEstadoProceso",
                    rp."FechaCreacion",
                    rp."UsuarioActualizacion"
                FROM public."RegistroPersonal" rp
                WHERE
                    NOT EXISTS (
                        SELECT 1
                        FROM public."HistorialLaboral" hl
                        WHERE
                            hl."IdRegistroPersonal" = rp."IdRegistroPersonal"
                            AND UPPER(
                                TRIM(COALESCE(hl."TipoVinculacion", ''))
                            ) = 'ACTIVO MIGRADO'
                    )
                    AND LOWER(
                        COALESCE(rp."UsuarioActualizacion", '')
                    ) NOT LIKE '%migracion%'
                    AND LOWER(
                        COALESCE(rp."UsuarioActualizacion", '')
                    ) NOT LIKE '%migrado%'
                    AND COALESCE(rp."UsuarioActualizacion", '')
                        <> 'ajuste_no_activos_maestro_2026_06_22'
            ),
            registrados_periodo AS (
                SELECT ub."IdRegistroPersonal"
                FROM universo_base ub
                WHERE
                    ub."FechaCreacion"
                        >= TIMESTAMPTZ '2026-03-01 00:00:00-05'
                    AND (
                        :anio IS NULL
                        OR EXTRACT(YEAR FROM ub."FechaCreacion") = :anio
                    )
                    AND (
                        :mes IS NULL
                        OR EXTRACT(MONTH FROM ub."FechaCreacion") = :mes
                    )
            ),
            movimientos_24_periodo AS (
                SELECT DISTINCT hec."IdRegistroPersonal"
                FROM public."HistorialEstadoContratacion" hec
                INNER JOIN universo_base ub
                    ON ub."IdRegistroPersonal" = hec."IdRegistroPersonal"
                WHERE
                    hec."EstadoNuevo" = 24
                    AND hec."OrigenMovimiento" = 'CAMBIO_ESTADO'
                    AND hec."Modulo" = 'SELECCION'
                    AND hec."FechaMovimiento"
                        >= TIMESTAMPTZ '2026-03-01 00:00:00-05'
                    AND (
                        :anio IS NULL
                        OR EXTRACT(YEAR FROM hec."FechaMovimiento") = :anio
                    )
                    AND (
                        :mes IS NULL
                        OR EXTRACT(MONTH FROM hec."FechaMovimiento") = :mes
                    )
            ),
            movimientos_25_periodo AS (
                SELECT
                    hec25."IdRegistroPersonal",
                    hec25."FechaMovimiento" AS fecha_estado_25,
                    inicio.fecha_estado_24
                FROM public."HistorialEstadoContratacion" hec25
                INNER JOIN universo_base ub
                    ON ub."IdRegistroPersonal" = hec25."IdRegistroPersonal"
                INNER JOIN LATERAL (
                    SELECT MAX(hec24."FechaMovimiento") AS fecha_estado_24
                    FROM public."HistorialEstadoContratacion" hec24
                    WHERE
                        hec24."IdRegistroPersonal" = hec25."IdRegistroPersonal"
                        AND hec24."EstadoNuevo" = 24
                        AND hec24."OrigenMovimiento" = 'CAMBIO_ESTADO'
                        AND hec24."Modulo" = 'SELECCION'
                        AND hec24."FechaMovimiento" <= hec25."FechaMovimiento"
                ) inicio ON inicio.fecha_estado_24 IS NOT NULL
                WHERE
                    hec25."EstadoNuevo" = 25
                    AND hec25."OrigenMovimiento" = 'BOTON_C'
                    AND hec25."Modulo" = 'CONTRATACION'
                    AND hec25."FechaMovimiento"
                        >= TIMESTAMPTZ '2026-03-01 00:00:00-05'
                    AND (
                        :anio IS NULL
                        OR EXTRACT(YEAR FROM hec25."FechaMovimiento") = :anio
                    )
                    AND (
                        :mes IS NULL
                        OR EXTRACT(MONTH FROM hec25."FechaMovimiento") = :mes
                    )
            ),
            contrataciones_periodo AS (
                SELECT DISTINCT ON ("IdRegistroPersonal")
                    "IdRegistroPersonal",
                    fecha_estado_24,
                    fecha_estado_25
                FROM movimientos_25_periodo
                ORDER BY "IdRegistroPersonal", fecha_estado_25 ASC
            ),
            rechazos_periodo AS (
                SELECT DISTINCT ON (hec."IdRegistroPersonal")
                    hec."IdRegistroPersonal",
                    hec."FechaMovimiento",
                    hec."UsuarioMovimiento",
                    hec."OrigenMovimiento"
                FROM public."HistorialEstadoContratacion" hec
                INNER JOIN universo_base ub
                    ON ub."IdRegistroPersonal" = hec."IdRegistroPersonal"
                WHERE
                    hec."EstadoNuevo" = 28
                    AND hec."OrigenMovimiento" IN (
                        'BOTON_NC',
                        'HISTORICO_MOTIVO_CIERRE'
                    )
                    AND hec."Modulo" = 'CONTRATACION'
                    AND hec."FechaMovimiento"
                        >= TIMESTAMPTZ '2026-03-01 00:00:00-05'
                    AND (
                        :anio IS NULL
                        OR EXTRACT(YEAR FROM hec."FechaMovimiento") = :anio
                    )
                    AND (
                        :mes IS NULL
                        OR EXTRACT(MONTH FROM hec."FechaMovimiento") = :mes
                    )
                ORDER BY
                    hec."IdRegistroPersonal",
                    hec."FechaMovimiento" DESC,
                    hec."IdHistorialEstadoContratacion" DESC
            )
            SELECT
                (SELECT COUNT(*) FROM registrados_periodo)
                    AS registrados_seleccion,
                (SELECT COUNT(*) FROM movimientos_24_periodo)
                    AS avanzan_contratacion,
                (SELECT COUNT(*) FROM contrataciones_periodo)
                    AS contratados,
                (
                    SELECT AVG(
                        EXTRACT(EPOCH FROM (fecha_estado_25 - fecha_estado_24))
                    )
                    FROM contrataciones_periodo
                ) AS promedio_segundos,
                (SELECT COUNT(*) FROM rechazos_periodo)
                    AS rechazados_contratacion;
        """),
        {"anio": anio, "mes": mes},
    ).mappings().first()

    registrados_seleccion = int(
        resultado.get("registrados_seleccion") or 0
    )
    avanzan_contratacion = int(
        resultado.get("avanzan_contratacion") or 0
    )
    contratados = int(resultado.get("contratados") or 0)
    rechazados_contratacion = int(
        resultado.get("rechazados_contratacion") or 0
    )

    promedio_segundos_raw = resultado.get("promedio_segundos")
    promedio_segundos = (
        int(round(float(promedio_segundos_raw)))
        if promedio_segundos_raw is not None
        else None
    )
    promedio_minutos = (
        round(promedio_segundos / 60, 2)
        if promedio_segundos is not None
        else None
    )
    promedio_formateado = _formatear_duracion_segundos(promedio_segundos)

    motivos_rows = db.execute(
        text("""
            WITH universo_base AS (
                SELECT
                    rp."IdRegistroPersonal",
                    rp."UsuarioActualizacion"
                FROM public."RegistroPersonal" rp
                WHERE
                    NOT EXISTS (
                        SELECT 1
                        FROM public."HistorialLaboral" hl
                        WHERE
                            hl."IdRegistroPersonal" = rp."IdRegistroPersonal"
                            AND UPPER(
                                TRIM(COALESCE(hl."TipoVinculacion", ''))
                            ) = 'ACTIVO MIGRADO'
                    )
                    AND LOWER(
                        COALESCE(rp."UsuarioActualizacion", '')
                    ) NOT LIKE '%migracion%'
                    AND LOWER(
                        COALESCE(rp."UsuarioActualizacion", '')
                    ) NOT LIKE '%migrado%'
                    AND COALESCE(rp."UsuarioActualizacion", '')
                        <> 'ajuste_no_activos_maestro_2026_06_22'
            ),
            rechazos_periodo AS (
                SELECT DISTINCT ON (hec."IdRegistroPersonal")
                    hec."IdRegistroPersonal",
                    hec."FechaMovimiento",
                    hec."UsuarioMovimiento",
                    hec."OrigenMovimiento"
                FROM public."HistorialEstadoContratacion" hec
                INNER JOIN universo_base ub
                    ON ub."IdRegistroPersonal" = hec."IdRegistroPersonal"
                WHERE
                    hec."EstadoNuevo" = 28
                    AND hec."OrigenMovimiento" IN (
                        'BOTON_NC',
                        'HISTORICO_MOTIVO_CIERRE'
                    )
                    AND hec."Modulo" = 'CONTRATACION'
                    AND hec."FechaMovimiento"
                        >= TIMESTAMPTZ '2026-03-01 00:00:00-05'
                    AND (
                        :anio IS NULL
                        OR EXTRACT(YEAR FROM hec."FechaMovimiento") = :anio
                    )
                    AND (
                        :mes IS NULL
                        OR EXTRACT(MONTH FROM hec."FechaMovimiento") = :mes
                    )
                ORDER BY
                    hec."IdRegistroPersonal",
                    hec."FechaMovimiento" DESC,
                    hec."IdHistorialEstadoContratacion" DESC
            ),
            rechazos_con_motivo AS (
                SELECT
                    rp."IdRegistroPersonal",
                    rp."OrigenMovimiento",
                    CASE
                        WHEN rp."OrigenMovimiento" = 'BOTON_NC'
                        THEN COALESCE(
                            NULLIF(TRIM(orc."ObservacionesRechazo"), ''),
                            'Sin observación'
                        )
                        WHEN rp."OrigenMovimiento"
                            = 'HISTORICO_MOTIVO_CIERRE'
                        THEN COALESCE(
                            NULLIF(TRIM(mcp."MotivoCierre"), ''),
                            'Sin motivo de cierre'
                        )
                        ELSE 'Sin motivo'
                    END AS motivo
                FROM rechazos_periodo rp
                LEFT JOIN LATERAL (
                    SELECT orc_detalle."ObservacionesRechazo"
                    FROM public."ObsRechazoContratacion" orc_detalle
                    WHERE
                        orc_detalle."IdRegistroPersonal"
                            = rp."IdRegistroPersonal"
                    ORDER BY
                        orc_detalle."IdObsRechazoContratacion" DESC
                    LIMIT 1
                ) orc ON rp."OrigenMovimiento" = 'BOTON_NC'
                LEFT JOIN LATERAL (
                    SELECT mcp_detalle."MotivoCierre"
                    FROM public."MotivoCierreProceso" mcp_detalle
                    WHERE
                        mcp_detalle."IdRegistroPersonal"
                            = rp."IdRegistroPersonal"
                    ORDER BY
                        COALESCE(
                            mcp_detalle."FechaActualizacion",
                            mcp_detalle."FechaCreacion"
                        ) DESC,
                        mcp_detalle."IdMotivoCierre" DESC
                    LIMIT 1
                ) mcp
                    ON rp."OrigenMovimiento" = 'HISTORICO_MOTIVO_CIERRE'
            )
            SELECT
                motivo,
                COUNT(*) AS cantidad
            FROM rechazos_con_motivo
            GROUP BY motivo
            ORDER BY cantidad DESC, motivo ASC;
        """),
        {"anio": anio, "mes": mes},
    ).mappings().all()

    motivos_rechazo_contratacion = []
    for motivo_row in motivos_rows:
        cantidad = int(motivo_row.get("cantidad") or 0)
        porcentaje = (
            round((cantidad / rechazados_contratacion) * 100, 2)
            if rechazados_contratacion > 0
            else 0
        )
        motivos_rechazo_contratacion.append({
            "motivo": motivo_row.get("motivo"),
            "cantidad": cantidad,
            "porcentaje": porcentaje,
        })

    porcentaje_contratados_sobre_registrados = (
        round((contratados / registrados_seleccion) * 100, 2)
        if registrados_seleccion > 0
        else 0
    )
    porcentaje_contratados_sobre_avanzan = (
        round((contratados / avanzan_contratacion) * 100, 2)
        if avanzan_contratacion > 0
        else 0
    )

    return {
        "modo_consulta": "general",
        "filtros": {"anio": anio, "mes": mes},
        "fecha_inicio_aplicativo": "2026-03-01",
        "criterio_fecha": {
            "registrados_seleccion": "RegistroPersonal.FechaCreacion",
            "avanzan_contratacion": (
                "HistorialEstadoContratacion.FechaMovimiento del estado 24"
            ),
            "contratados": (
                "HistorialEstadoContratacion.FechaMovimiento "
                "del estado 25 por BOTON_C"
            ),
            "rechazados_contratacion": (
                "HistorialEstadoContratacion.FechaMovimiento "
                "del estado 28 por BOTON_NC o HISTORICO_MOTIVO_CIERRE"
            ),
            "tiempo_contratacion": (
                "Casos cuyo estado 25 por BOTON_C ocurrió "
                "en el periodo consultado"
            ),
        },
        "registrados_seleccion": registrados_seleccion,
        "comparativo_registrados_contratados": {
            "registrados_seleccion": registrados_seleccion,
            "contratados": contratados,
            "porcentaje_contratados": porcentaje_contratados_sobre_registrados,
            "nota": "Cada valor usa la fecha real de su propio evento.",
        },
        "comparativo_avanzan_contratados": {
            "avanzan_contratacion": avanzan_contratacion,
            "contratados": contratados,
            "porcentaje_contratados": porcentaje_contratados_sobre_avanzan,
            "fuente": "HistorialEstadoContratacion",
            "nota": (
                "Avanzan se filtra por fecha del estado 24 y "
                "contratados por fecha del estado 25."
            ),
        },
        "rechazados": {
            "total": rechazados_contratacion,
            "fuente": "HistorialEstadoContratacion",
            "motivos": motivos_rechazo_contratacion,
            "pendiente_fuente_contratacion": False,
            "filtro_fecha": (
                "HistorialEstadoContratacion.FechaMovimiento"
            ),
            "origenes_incluidos": [
                "BOTON_NC",
                "HISTORICO_MOTIVO_CIERRE",
            ],
        },
        "tiempo_contratacion": {
            "promedio_minutos": promedio_minutos,
            "promedio_segundos": promedio_segundos,
            "promedio_formateado": promedio_formateado,
            "casos_medidos": contratados,
            "disponible": promedio_segundos is not None,
            "fuente_inicio": "Estado 24 - CAMBIO_ESTADO - SELECCION",
            "fuente_fin": "Estado 25 - BOTON_C - CONTRATACION",
            "criterio_periodo": (
                "Fecha del movimiento al estado 25 mediante BOTON_C"
            ),
            "mensaje": (
                "Tiempo promedio real entre el avance a contratación "
                "y la confirmación mediante el botón C."
                if promedio_segundos is not None
                else
                "No existen casos completos con trazabilidad 24 a 25 "
                "finalizados en el periodo seleccionado."
            ),
        },
        "exclusiones": {
            "fecha_anterior_inicio_aplicativo": True,
            "fecha_inicio_aplicativo": "2026-03-01",
            "activo_migrado_historial_laboral": True,
            "usuarios_migracion": True,
            "ajuste_no_activos_maestro": True,
        },
    }


@router.get("/reporte-excel")
def generar_reporte_excel_seleccion(db: Session = Depends(get_db)):
    rows = db.execute(text("""
        SELECT
            rp."Nombres",
            rp."Apellidos",
            rp."NumeroIdentificacion" as cedula,
            COALESCE(rp."Celular", '') as telefono,
            COALESCE(rp."Email", '') as correo,
            cg."NombreCargo" as cargo,
            rp."FechaCreacion" as fecha_registro,
            mcp."MotivoCierre" as motivo_rechazo,
            CASE rp."IdEstadoProceso"
                WHEN 18 THEN 'Nuevo'
                WHEN 19 THEN 'Entrevista'
                WHEN 20 THEN 'Entrevista jefe inmediato'
                WHEN 21 THEN 'Exámenes'
                WHEN 22 THEN 'Seguridad'
                WHEN 24 THEN 'Avanza a contratación'
                WHEN 25 THEN 'Contratado'
                WHEN 26 THEN 'Referenciación'
                WHEN 27 THEN 'Desiste del proceso'
                WHEN 28 THEN 'Rechazado'
                WHEN 30 THEN 'Abierto'
                WHEN 34 THEN 'Pendiente de Contratación'
                ELSE CONCAT('Estado ', rp."IdEstadoProceso")
            END as estado
        FROM public."RegistroPersonal" rp
        LEFT JOIN public."AsignacionCargoCliente" acc
            ON acc."IdRegistroPersonal" = rp."IdRegistroPersonal"
        LEFT JOIN public."Cargo" cg
            ON cg."IdCargo" = acc."IdCargo"
        LEFT JOIN (
            SELECT DISTINCT ON ("IdRegistroPersonal")
                "IdRegistroPersonal",
                "MotivoCierre",
                "FechaCreacion"
            FROM public."MotivoCierreProceso"
            ORDER BY "IdRegistroPersonal", "FechaCreacion" DESC
        ) mcp
            ON mcp."IdRegistroPersonal" = rp."IdRegistroPersonal"
    """)).mappings().all()

    filas = [dict(r) for r in rows]

    if not filas:
        raise HTTPException(status_code=404, detail="No hay datos")

    wb = Workbook()
    ws = wb.active
    ws.title = "Reporte"

    headers = list(filas[0].keys())
    ws.append(headers)

    header_fill = PatternFill("solid", fgColor="1F4E78")
    header_font = Font(bold=True, color="FFFFFF")

    for col in range(1, len(headers) + 1):
        cell = ws.cell(row=1, column=col)
        cell.font = header_font
        cell.fill = header_fill

    for fila in filas:
        fila_limpia = {}
        for key, value in fila.items():
            if isinstance(value, datetime):
                value = value.replace(tzinfo=None)
            fila_limpia[key] = value

        ws.append(list(fila_limpia.values()))

    ws.auto_filter.ref = ws.dimensions
    ws.freeze_panes = "A2"

    for column_cells in ws.columns:
        max_length = 0
        column_letter = column_cells[0].column_letter
        for cell in column_cells:
            if cell.value is not None:
                max_length = max(max_length, len(str(cell.value)))
        ws.column_dimensions[column_letter].width = max_length + 3

    total = len(filas)
    rechazados = len([f for f in filas if str(f.get("estado", "")).strip().lower() == "rechazado"])
    contratados = len([f for f in filas if str(f.get("estado", "")).strip().lower() == "contratado"])
    avanza = len([f for f in filas if str(f.get("estado", "")).strip().lower() == "avanza a contratación"])

    porcentaje_contratacion = round((contratados / total) * 100) if total else 0
    porcentaje_rechazo = round((rechazados / total) * 100) if total else 0

    motivos_rechazo = {}

    for fila in filas:
        estado = str(fila.get("estado", "")).strip().lower()
        motivo = fila.get("motivo_rechazo")

        if estado == "rechazado" and motivo and str(motivo).strip().upper() != "SIN_MOTIVO":
            motivo = str(motivo).strip()
            motivos_rechazo[motivo] = motivos_rechazo.get(motivo, 0) + 1

    tendencia_mensual = {}

    meses = {
        1: "enero", 2: "febrero", 3: "marzo", 4: "abril",
        5: "mayo", 6: "junio", 7: "julio", 8: "agosto",
        9: "septiembre", 10: "octubre", 11: "noviembre", 12: "diciembre"
    }

    for fila in filas:
        fecha = fila.get("fecha_registro")

        if isinstance(fecha, datetime):
            clave_orden = fecha.strftime("%Y-%m")
            etiqueta_mes = f"{meses[fecha.month]}-{str(fecha.year)[-2:]}"
        else:
            clave_orden = "9999-99"
            etiqueta_mes = "Sin fecha"

        if clave_orden not in tendencia_mensual:
            tendencia_mensual[clave_orden] = {
                "etiqueta": etiqueta_mes,
                "cantidad": 0
            }

        tendencia_mensual[clave_orden]["cantidad"] += 1

    tendencia_mensual = dict(sorted(tendencia_mensual.items()))

    ws_dash = wb.create_sheet("Dashboard")

    ws_dash["A1"] = "Dashboard Selección"
    ws_dash["A1"].font = Font(bold=True, size=18)

    dash_fill = PatternFill("solid", fgColor="70AD47")
    dash_font = Font(bold=True, color="FFFFFF")
    kpi_fill = PatternFill("solid", fgColor="E2F0D9")
    kpi_title_font = Font(bold=True, color="375623", size=11)
    kpi_value_font = Font(bold=True, color="000000", size=16)

    ws_dash["A2"] = "Total candidatos"
    ws_dash["B2"] = total
    ws_dash["D2"] = "Contratación"
    ws_dash["E2"] = f"{porcentaje_contratacion}%"
    ws_dash["G2"] = "Rechazo"
    ws_dash["H2"] = f"{porcentaje_rechazo}%"

    for cell_ref in ["A2", "D2", "G2"]:
        ws_dash[cell_ref].fill = kpi_fill
        ws_dash[cell_ref].font = kpi_title_font

    for cell_ref in ["B2", "E2", "H2"]:
        ws_dash[cell_ref].fill = kpi_fill
        ws_dash[cell_ref].font = kpi_value_font

    ws_dash["A4"] = "Resumen general"
    ws_dash["A4"].font = Font(bold=True, size=12)

    ws_dash["A5"] = "Métrica"
    ws_dash["B5"] = "Valor"

    for col in ["A", "B"]:
        cell = ws_dash[f"{col}5"]
        cell.fill = dash_fill
        cell.font = dash_font

    ws_dash["A6"] = "Total registros"
    ws_dash["B6"] = total

    ws_dash["A7"] = "Rechazados"
    ws_dash["B7"] = rechazados

    ws_dash["A8"] = "Avanza a contratación"
    ws_dash["B8"] = avanza

    ws_dash["A9"] = "Contratados"
    ws_dash["B9"] = contratados

    ws_dash["J2"] = "Registros por mes"
    ws_dash["J2"].font = Font(bold=True, size=12)

    ws_dash["J3"] = "Mes"
    ws_dash["K3"] = "Registros"

    for col in ["J", "K"]:
        cell = ws_dash[f"{col}3"]
        cell.fill = dash_fill
        cell.font = dash_font

    fila_tendencia = 4
    for _, item in tendencia_mensual.items():
        ws_dash[f"J{fila_tendencia}"] = item["etiqueta"]
        ws_dash[f"K{fila_tendencia}"] = item["cantidad"]
        fila_tendencia += 1

    if fila_tendencia > 5:
        line = LineChart()
        line.style = 2
        line.title = "Evolución mensual de candidatos registrados"
        line.y_axis.title = "Cantidad de registros"
        line.x_axis.title = "Mes"

        data_line = Reference(ws_dash, min_col=11, min_row=4, max_row=fila_tendencia - 1)
        labels_line = Reference(ws_dash, min_col=10, min_row=4, max_row=fila_tendencia - 1)

        line.add_data(data_line, titles_from_data=False, from_rows=False)
        line.set_categories(labels_line)

        line.series = line.series[:1]
        line.series[0].graphicalProperties.line.solidFill = "70AD47"
        line.series[0].graphicalProperties.line.width = 30000
        line.series[0].marker.symbol = "circle"
        line.series[0].marker.size = 8
        line.series[0].marker.graphicalProperties.solidFill = "70AD47"

        line.dLbls = DataLabelList()
        line.dLbls.showVal = False
        line.dLbls.showSerName = False
        line.dLbls.showCatName = False

        line.legend = None
        line.smooth = False
        line.height = 8
        line.width = 22

        ws_dash.add_chart(line, "J10")

    pie = PieChart()
    pie.title = "Distribución de candidatos en estados finales"

    data = Reference(ws_dash, min_col=2, min_row=7, max_row=9)
    labels = Reference(ws_dash, min_col=1, min_row=7, max_row=9)

    pie.add_data(data, titles_from_data=False)
    pie.set_categories(labels)

    pie.dataLabels = DataLabelList()
    pie.dataLabels.showVal = False
    pie.dataLabels.showPercent = True
    pie.dataLabels.showCatName = False
    pie.dataLabels.showSerName = False
    pie.dataLabels.showLeaderLines = True

    ws_dash.add_chart(pie, "A12")

    ws_dash["A33"] = "Distribución de candidatos en estados finales"
    ws_dash["A33"].font = Font(bold=True, size=14)

    estados_barra = [
        {"estado": "Rechazados", "cantidad": rechazados, "color": "4F81BD"},
        {"estado": "Avanza a contratación", "cantidad": avanza, "color": "C0504D"},
        {"estado": "Contratados", "cantidad": contratados, "color": "9BBB59"},
    ]

    estados_barra = sorted(estados_barra, key=lambda x: x["cantidad"], reverse=True)

    ws_dash["A34"] = "Estado"
    ws_dash["B34"] = "Cantidad"
    ws_dash["C34"] = "%"

    for col in ["A", "B", "C"]:
        cell = ws_dash[f"{col}34"]
        cell.fill = dash_fill
        cell.font = dash_font

    fila_barra = 35
    for item in estados_barra:
        porcentaje = round((item["cantidad"] / total) * 100) if total else 0
        ws_dash[f"A{fila_barra}"] = item["estado"]
        ws_dash[f"B{fila_barra}"] = item["cantidad"]
        ws_dash[f"C{fila_barra}"] = f"{porcentaje}%"
        fila_barra += 1

    bar = BarChart()
    bar.type = "bar"
    bar.style = 10
    bar.title = None
    bar.y_axis.title = None
    bar.x_axis.title = None

    data_bar = Reference(ws_dash, min_col=2, min_row=34, max_row=37)
    labels_bar = Reference(ws_dash, min_col=1, min_row=35, max_row=37)

    bar.add_data(data_bar, titles_from_data=True)
    bar.set_categories(labels_bar)

    bar.legend = None

    bar.dLbls = DataLabelList()
    bar.dLbls.showVal = True
    bar.dLbls.showSerName = False
    bar.dLbls.showCatName = False
    bar.dLbls.showLegendKey = False

    bar.height = 8
    bar.width = 16

    bar.y_axis.majorGridlines = None
    bar.x_axis.majorGridlines = None

    if bar.series:
        for idx, item in enumerate(estados_barra):
            try:
                bar.series[0].data_points[idx].graphicalProperties.solidFill = item["color"]
            except Exception:
                pass

    ws_dash.add_chart(bar, "D33")

    ws_dash["A50"] = "Motivos de rechazo"
    ws_dash["A50"].font = Font(bold=True, size=14)

    ws_dash["A51"] = "Motivo"
    ws_dash["B51"] = "Cantidad"
    ws_dash["C51"] = "%"
    ws_dash["D51"] = "Ref."

    for col in ["A", "B", "C", "D"]:
        cell = ws_dash[f"{col}51"]
        cell.fill = dash_fill
        cell.font = dash_font

    motivos_base = [
        "Desiste del Proceso",
        "No Cumple Perfil",
        "No asiste a Examenes Medicos",
        "Examenes No Aptos",
        "Documentacion Incompleta",
        "No asiste a Contratacion",
    ]

    equivalencias_motivos = {
        "DESISTE DEL PROCESO": "Desiste del Proceso",
        "NO CUMPLE PERFIL": "No Cumple Perfil",
        "NO ASISTE A EXAMENES MEDICOS": "No asiste a Examenes Medicos",
        "NO ASISTE A EXÁMENES MEDICOS": "No asiste a Examenes Medicos",
        "NO ASISTE A EXÁMENES MÉDICOS": "No asiste a Examenes Medicos",
        "EXAMENES NO APTOS": "Examenes No Aptos",
        "EXÁMENES NO APTOS": "Examenes No Aptos",
        "DOCUMENTACION INCOMPLETA": "Documentacion Incompleta",
        "DOCUMENTACIÓN INCOMPLETA": "Documentacion Incompleta",
        "NO ASISTE A CONTRATACION": "No asiste a Contratacion",
        "NO ASISTE A CONTRATACIÓN": "No asiste a Contratacion",
    }

    colores_motivos = {
        "Desiste del Proceso": "C0504D",
        "No Cumple Perfil": "4F81BD",
        "No asiste a Examenes Medicos": "F79646",
        "Examenes No Aptos": "8064A2",
        "Documentacion Incompleta": "9BBB59",
        "No asiste a Contratacion": "4BACC6",
    }

    motivos_normalizados = {motivo: 0 for motivo in motivos_base}

    for motivo, cantidad in motivos_rechazo.items():
        clave = str(motivo).strip().upper()
        motivo_final = equivalencias_motivos.get(clave, str(motivo).strip())

        if motivo_final not in motivos_normalizados:
            motivos_normalizados[motivo_final] = 0

        motivos_normalizados[motivo_final] += cantidad

    motivos_tabla = []
    for motivo, cantidad in motivos_normalizados.items():
        motivos_tabla.append({
            "motivo": motivo,
            "cantidad": cantidad,
            "color": colores_motivos.get(motivo, "70AD47")
        })

    motivos_tabla = sorted(
        motivos_tabla,
        key=lambda x: (x["cantidad"] == 0, -x["cantidad"], x["motivo"])
    )

    total_motivos = sum(item["cantidad"] for item in motivos_tabla)

    fila_motivo = 52
    for item in motivos_tabla:
        porcentaje = round((item["cantidad"] / total_motivos) * 100) if total_motivos else 0

        ws_dash[f"A{fila_motivo}"] = item["motivo"]
        ws_dash[f"B{fila_motivo}"] = item["cantidad"]
        ws_dash[f"C{fila_motivo}"] = f"{porcentaje}%"
        ws_dash[f"D{fila_motivo}"] = ""

        ws_dash[f"D{fila_motivo}"].fill = PatternFill("solid", fgColor=item["color"])

        fila_motivo += 1

    fila_grafica_inicio = fila_motivo + 2
    ws_dash[f"A{fila_grafica_inicio}"] = "Motivo grafica"
    ws_dash[f"B{fila_grafica_inicio}"] = "Cantidad"

    fila_grafica = fila_grafica_inicio + 1
    motivos_grafica = [item for item in motivos_tabla if item["cantidad"] > 0]

    for item in motivos_grafica:
        ws_dash[f"A{fila_grafica}"] = item["motivo"]
        ws_dash[f"B{fila_grafica}"] = item["cantidad"]
        fila_grafica += 1

    if motivos_grafica:
        bar_motivos = BarChart()
        bar_motivos.type = "bar"
        bar_motivos.style = 10
        bar_motivos.title = None
        bar_motivos.y_axis.title = None
        bar_motivos.x_axis.title = None

        data_motivos = Reference(
            ws_dash,
            min_col=2,
            min_row=fila_grafica_inicio,
            max_row=fila_grafica - 1
        )

        labels_motivos = Reference(
            ws_dash,
            min_col=1,
            min_row=fila_grafica_inicio + 1,
            max_row=fila_grafica - 1
        )

        bar_motivos.add_data(data_motivos, titles_from_data=True)
        bar_motivos.set_categories(labels_motivos)

        bar_motivos.legend = None

        bar_motivos.dLbls = DataLabelList()
        bar_motivos.dLbls.showVal = True
        bar_motivos.dLbls.showSerName = False
        bar_motivos.dLbls.showCatName = False
        bar_motivos.dLbls.showLegendKey = False

        bar_motivos.height = 8
        bar_motivos.width = 16

        bar_motivos.y_axis.majorGridlines = None
        bar_motivos.x_axis.majorGridlines = None

        if bar_motivos.series:
            for idx, item in enumerate(motivos_grafica):
                try:
                    bar_motivos.series[0].data_points[idx].graphicalProperties.solidFill = item["color"]
                except Exception:
                    pass

        ws_dash.add_chart(bar_motivos, "E50")

    ws_dash.column_dimensions["A"].width = 34
    ws_dash.column_dimensions["B"].width = 14
    ws_dash.column_dimensions["C"].width = 10
    ws_dash.column_dimensions["D"].width = 8
    ws_dash.column_dimensions["E"].width = 14
    ws_dash.column_dimensions["G"].width = 14
    ws_dash.column_dimensions["H"].width = 14
    ws_dash.column_dimensions["J"].width = 18
    ws_dash.column_dimensions["K"].width = 14

    ruta = Path("reporte_seleccion_backend.xlsx")
    wb.save(ruta)

    return FileResponse(
        path=ruta,
        filename="reporte_seleccion.xlsx",
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )


@router.get("/{id_registro_personal}", response_model=DatosSeleccionResponse)
def obtener_datos_seleccion(id_registro_personal: int, db: Session = Depends(get_db)):
    data = service.obtener_por_registro_personal(db, id_registro_personal)
    if not data:
        raise HTTPException(status_code=404, detail="No existen datos")

    if getattr(data, "FechaActualizacion", None) is None:
        data.FechaActualizacion = datetime.now(timezone.utc)

    return data


@router.post("/upsert", response_model=DatosSeleccionResponse)
def upsert_datos_seleccion(body: DatosSeleccionUpsertRequest, db: Session = Depends(get_db)):
    payload = body.model_dump(exclude_none=True)

    if "HaTrabajadoAntesEnLaEmpresa" in payload:
        parsed = _parse_bool(payload.get("HaTrabajadoAntesEnLaEmpresa"))
        if parsed is None:
            payload.pop("HaTrabajadoAntesEnLaEmpresa", None)
        else:
            payload["HaTrabajadoAntesEnLaEmpresa"] = parsed

    payload.pop("HaTrabajadoAntes", None)

    data = service.upsert(db, payload)

    if getattr(data, "FechaActualizacion", None) is None:
        data.FechaActualizacion = datetime.now(timezone.utc)

    return data