import os
from io import BytesIO
from datetime import datetime, date

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from pydantic import BaseModel
from fastapi.responses import StreamingResponse
from sqlalchemy import text
from sqlalchemy.orm import Session
from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

from infrastructure.db.deps import get_db

router = APIRouter(prefix="/api/nomina-retiros", tags=["Nómina Retiros"])


class ObservacionNominaRequest(BaseModel):
    observacion_nomina: str | None = None

class FinalizarRetiroNominaRequest(BaseModel):
    fecha_pago_liquidacion: date


def _consultar_retiros_nomina(db: Session):
    query = text("""
        SELECT
            rl."IdRetiroLaboral",
            rl."IdRegistroPersonal",
            rp."NumeroIdentificacion",
            rp."Nombres",
            rp."Apellidos",
            COALESCE(c."Nombre", 'SIN CLIENTE') AS "NombreCliente",
            rl."FechaProceso",
            rl."FechaRetiro",
            rl."FechaCierre",
            rl."FechaEnvioNomina",
            rl."FechaPagoLiquidacion",
            rl."EstadoCasoRRLL",
            rp."IdEstadoProceso",
            ep."Nombre" AS "EstadoProceso",
            mr."Nombre" AS "MotivoRetiro",
            tr."Nombre" AS "TipificacionRetiro",
            rl."ObservacionGeneral",
            rl."ObservacionRetiro",
            rl."ObservacionNomina",
            rl."UsuarioObservacionNomina",
            rl."FechaObservacionNomina",
            CASE
                WHEN rp."IdEstadoProceso" = 32 THEN true
                ELSE false
            END AS "PuedeGestionarNomina"
        FROM public."RetiroLaboral" rl
        INNER JOIN public."RegistroPersonal" rp
            ON rp."IdRegistroPersonal" = rl."IdRegistroPersonal"
        LEFT JOIN public."Cliente" c
            ON c."IdCliente" = rl."IdCliente"
        LEFT JOIN public."EstadoProceso" ep
            ON ep."IdEstadoProceso" = rp."IdEstadoProceso"
        LEFT JOIN public."MotivoRetiro" mr
            ON mr."IdMotivoRetiro" = rl."IdMotivoRetiro"
        LEFT JOIN public."TipificacionRetiro" tr
            ON tr."IdTipificacionRetiro" = rl."IdTipificacionRetiro"
        WHERE COALESCE(rl."Activo", true) = true
          AND rp."IdEstadoProceso" IN (30, 32, 35)
        ORDER BY
            CASE WHEN rp."IdEstadoProceso" = 32 THEN 0 ELSE 1 END,
            rl."FechaCreacion" DESC;
    """)

    return [dict(row) for row in db.execute(query).mappings().all()]


def _valor_fecha_excel(fecha):
    if not fecha:
        return ""

    if isinstance(fecha, datetime):
        return fecha.date()

    return fecha


def _nombre_completo(row):
    nombres = row.get("Nombres") or ""
    apellidos = row.get("Apellidos") or ""
    return f"{nombres} {apellidos}".strip()


def _configurar_hoja_detalle(ws, titulo, registros):
    verde = "008060"
    verde_claro = "E8F7F0"
    gris_texto = "374151"
    blanco = "FFFFFF"
    gris_fila = "F9FAFB"
    borde_color = "D9E2EC"

    header_fill = PatternFill("solid", fgColor=verde)
    title_fill = PatternFill("solid", fgColor=verde_claro)
    thin = Side(style="thin", color=borde_color)
    border = Border(left=thin, right=thin, top=thin, bottom=thin)

    ws.merge_cells("A1:F1")
    ws["A1"] = titulo
    ws["A1"].font = Font(bold=True, size=16, color=verde)
    ws["A1"].fill = title_fill
    ws["A1"].alignment = Alignment(horizontal="center", vertical="center")
    ws.row_dimensions[1].height = 30

    ws.merge_cells("A2:F2")
    ws["A2"] = f"Generado: {datetime.now().strftime('%d/%m/%Y %I:%M %p')}"
    ws["A2"].font = Font(italic=True, size=10, color="6B7280")
    ws["A2"].alignment = Alignment(horizontal="left", vertical="center")

    encabezados = [
        "Identificación",
        "Nombre completo",
        "Fecha de retiro",
        "Fecha pago liquidación",
        "Cliente",
        "Estado",
    ]

    for col, header in enumerate(encabezados, start=1):
        cell = ws.cell(row=4, column=col, value=header)
        cell.fill = header_fill
        cell.font = Font(bold=True, color=blanco)
        cell.alignment = Alignment(horizontal="center", vertical="center")
        cell.border = border

    ws.row_dimensions[4].height = 24

    for row_idx, registro in enumerate(registros, start=5):
        id_estado = int(registro.get("IdEstadoProceso") or 0)

        if id_estado == 30:
            estado_excel = "Abierto"
        elif id_estado == 32:
            estado_excel = "Cerrado"
        elif id_estado == 35:
            estado_excel = "Retirado"
        else:
            estado_excel = "Sin definir"

        valores = [
            registro.get("NumeroIdentificacion") or "",
            _nombre_completo(registro),
            _valor_fecha_excel(registro.get("FechaRetiro")),
            _valor_fecha_excel(registro.get("FechaPagoLiquidacion")),
            registro.get("NombreCliente") or "SIN CLIENTE",
            estado_excel,
        ]

        for col_idx, valor in enumerate(valores, start=1):
            cell = ws.cell(row=row_idx, column=col_idx, value=valor)
            cell.border = border
            cell.alignment = Alignment(vertical="center", wrap_text=True)
            cell.font = Font(color=gris_texto)

            if row_idx % 2 == 0:
                cell.fill = PatternFill("solid", fgColor=gris_fila)

            if col_idx in (3, 4) and valor:
                cell.number_format = "DD/MM/YYYY"

            if col_idx == 6:
                estado = str(valor).upper()
                if "RETIRADO" in estado:
                    cell.fill = PatternFill("solid", fgColor="DCFCE7")
                    cell.font = Font(color="166534", bold=True)
                elif "CERRADO" in estado or "NÓMINA" in estado or "NOMINA" in estado:
                    cell.fill = PatternFill("solid", fgColor="DBEAFE")
                    cell.font = Font(color="1D4ED8", bold=True)
                else:
                    cell.fill = PatternFill("solid", fgColor="FEF3C7")
                    cell.font = Font(color="92400E", bold=True)

        ws.row_dimensions[row_idx].height = 30

    widths = {
        "A": 20,
        "B": 42,
        "C": 18,
        "D": 24,
        "E": 60,
        "F": 24,
    }

    for col, width in widths.items():
        ws.column_dimensions[col].width = width

    ws.freeze_panes = "A5"
    ws.auto_filter.ref = f"A4:F{max(4, len(registros) + 4)}"


@router.get("")
def listar_retiros_nomina(db: Session = Depends(get_db)):
    try:
        query = text("""
            SELECT
                rl."IdRetiroLaboral",
                rl."IdRegistroPersonal",
                rp."NumeroIdentificacion",
                rp."Nombres",
                rp."Apellidos",
                COALESCE(c."Nombre", 'SIN CLIENTE') AS "NombreCliente",
                rl."FechaProceso",
                rl."FechaRetiro",
                pso."FechaCreacion" AS "FechaPazYSalvo",
                rl."FechaCierre",
                rl."FechaEnvioNomina",
                rl."FechaPagoLiquidacion",
                rl."EstadoCasoRRLL",

                CASE
                    WHEN rl."FechaRetiro" IS NOT NULL
                     AND pso."FechaCreacion" IS NOT NULL
                    THEN DATE(pso."FechaCreacion") - rl."FechaRetiro"
                    ELSE NULL
                END AS "DiasRetiroPazYSalvo",

                CASE
                    WHEN pso."FechaCreacion" IS NOT NULL
                     AND rl."FechaCierre" IS NOT NULL
                    THEN DATE(rl."FechaCierre") - DATE(pso."FechaCreacion")
                    ELSE NULL
                END AS "DiasPazYSalvoCierreRRLL",

                CASE
                    WHEN rl."FechaCierre" IS NOT NULL
                     AND rl."FechaEnvioNomina" IS NOT NULL
                    THEN DATE(rl."FechaEnvioNomina") - DATE(rl."FechaCierre")
                    ELSE NULL
                END AS "DiasCierreRRLLNomina",

                rp."IdEstadoProceso",
                ep."Nombre" AS "EstadoProceso",
                mr."Nombre" AS "MotivoRetiro",
                tr."Nombre" AS "TipificacionRetiro",
                rl."ObservacionGeneral",
                rl."ObservacionRetiro",
                rl."ObservacionNomina",
                rl."UsuarioObservacionNomina",
                rl."FechaObservacionNomina",

                CASE
                    WHEN rp."IdEstadoProceso" = 32 THEN true
                    ELSE false
                END AS "PuedeGestionarNomina"

            FROM public."RetiroLaboral" rl
            INNER JOIN public."RegistroPersonal" rp
                ON rp."IdRegistroPersonal" = rl."IdRegistroPersonal"
            LEFT JOIN public."PazYSalvoOperaciones" pso
                ON pso."IdRetiroLaboral" = rl."IdRetiroLaboral"
            LEFT JOIN public."Cliente" c
                ON c."IdCliente" = rl."IdCliente"
            LEFT JOIN public."EstadoProceso" ep
                ON ep."IdEstadoProceso" = rp."IdEstadoProceso"
            LEFT JOIN public."MotivoRetiro" mr
                ON mr."IdMotivoRetiro" = rl."IdMotivoRetiro"
            LEFT JOIN public."TipificacionRetiro" tr
                ON tr."IdTipificacionRetiro" = rl."IdTipificacionRetiro"
            WHERE COALESCE(rl."Activo", true) = true
              AND rp."IdEstadoProceso" IN (30, 32, 35)
            ORDER BY
                CASE WHEN rp."IdEstadoProceso" = 32 THEN 0 ELSE 1 END,
                rl."FechaCreacion" DESC;
        """)

        rows = db.execute(query).mappings().all()

        return {
            "success": True,
            "message": "Retiros de nómina consultados correctamente.",
            "data": [dict(row) for row in rows],
        }

    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Error al consultar retiros de nómina: {str(e)}"
        )

@router.put("/{id_retiro_laboral}/observacion-nomina")
def guardar_observacion_nomina(
    id_retiro_laboral: int,
    payload: ObservacionNominaRequest,
    db: Session = Depends(get_db)
):
    try:
        query_retiro = text("""
            SELECT
                rl."IdRetiroLaboral",
                rp."IdEstadoProceso"
            FROM public."RetiroLaboral" rl
            INNER JOIN public."RegistroPersonal" rp
                ON rp."IdRegistroPersonal" = rl."IdRegistroPersonal"
            WHERE rl."IdRetiroLaboral" = :id_retiro_laboral
              AND COALESCE(rl."Activo", true) = true;
        """)

        retiro = db.execute(
            query_retiro,
            {"id_retiro_laboral": id_retiro_laboral}
        ).mappings().first()

        if not retiro:
            raise HTTPException(
                status_code=404,
                detail="Retiro laboral no encontrado."
            )

        if int(retiro["IdEstadoProceso"]) not in (32, 35):
            raise HTTPException(
                status_code=400,
                detail="Solo se puede registrar observación de nómina en retiros enviados a nómina o retirados."
            )

        query_update = text("""
            UPDATE public."RetiroLaboral"
            SET
                "ObservacionNomina" = :observacion_nomina,
                "UsuarioObservacionNomina" = 'nomina',
                "FechaObservacionNomina" = NOW(),
                "FechaActualizacion" = NOW(),
                "UsuarioActualizacion" = 'nomina'
            WHERE "IdRetiroLaboral" = :id_retiro_laboral
            RETURNING
                "IdRetiroLaboral",
                "ObservacionNomina",
                "UsuarioObservacionNomina",
                "FechaObservacionNomina";
        """)

        actualizado = db.execute(query_update, {
            "id_retiro_laboral": id_retiro_laboral,
            "observacion_nomina": payload.observacion_nomina,
        }).mappings().first()

        db.commit()

        return {
            "success": True,
            "message": "Observación de nómina guardada correctamente.",
            "data": dict(actualizado),
        }

    except HTTPException:
        db.rollback()
        raise

    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=500,
            detail=f"Error guardando observación de nómina: {str(e)}"
        )

@router.get("/indicadores")
def obtener_indicadores_nomina_retiros(db: Session = Depends(get_db)):
    try:
        query_totales = text("""
            SELECT
                COUNT(*) FILTER (WHERE rp."IdEstadoProceso" = 30) AS abiertos,
                COUNT(*) FILTER (WHERE rp."IdEstadoProceso" = 32) AS cerrados,
                COUNT(*) FILTER (WHERE rp."IdEstadoProceso" = 35) AS retirados,
                COUNT(*) AS total
            FROM public."RetiroLaboral" rl
            INNER JOIN public."RegistroPersonal" rp
                ON rp."IdRegistroPersonal" = rl."IdRegistroPersonal"
            WHERE COALESCE(rl."Activo", true) = true
              AND rp."IdEstadoProceso" IN (30, 32, 35);
        """)

        totales_row = db.execute(query_totales).mappings().first()

        abiertos = int(totales_row["abiertos"] or 0)
        cerrados = int(totales_row["cerrados"] or 0)
        retirados = int(totales_row["retirados"] or 0)
        total = int(totales_row["total"] or 0)

        query_retiros_mes = text("""
            SELECT
                EXTRACT(YEAR FROM fecha_base)::int AS anio,
                EXTRACT(MONTH FROM fecha_base)::int AS mes_numero,
                COUNT(*)::int AS cantidad
            FROM (
                SELECT
                    COALESCE(
                        rl."FechaRetiro",
                        pso."FechaCreacion",
                        rl."FechaCierre",
                        rl."FechaEnvioNomina",
                        rl."FechaPagoLiquidacion",
                        rl."FechaProceso",
                        rl."FechaCreacion"
                    ) AS fecha_base
                FROM public."RetiroLaboral" rl
                INNER JOIN public."RegistroPersonal" rp
                    ON rp."IdRegistroPersonal" = rl."IdRegistroPersonal"
                LEFT JOIN public."PazYSalvoOperaciones" pso
                    ON pso."IdRetiroLaboral" = rl."IdRetiroLaboral"
                WHERE COALESCE(rl."Activo", true) = true
                  AND rp."IdEstadoProceso" IN (30, 32, 35)
            ) datos
            WHERE fecha_base IS NOT NULL
            GROUP BY anio, mes_numero
            ORDER BY anio, mes_numero;
        """)

        meses_nombre = {
            1: "enero",
            2: "febrero",
            3: "marzo",
            4: "abril",
            5: "mayo",
            6: "junio",
            7: "julio",
            8: "agosto",
            9: "septiembre",
            10: "octubre",
            11: "noviembre",
            12: "diciembre",
        }

        retiros_por_mes_rows = db.execute(query_retiros_mes).mappings().all()

        retiros_por_mes = [
            {
                "mes": f"{meses_nombre.get(int(row['mes_numero']), 'sin-mes')}-{int(row['anio'])}",
                "cantidad": int(row["cantidad"] or 0),
            }
            for row in retiros_por_mes_rows
        ]

        query_promedios = text("""
            SELECT
                ROUND(AVG(
                    CASE
                        WHEN rl."FechaRetiro" IS NOT NULL
                         AND pso."FechaCreacion" IS NOT NULL
                        THEN DATE(pso."FechaCreacion") - rl."FechaRetiro"
                    END
                ), 2) AS promedio_paz_y_salvo,

                ROUND(AVG(
                    CASE
                        WHEN pso."FechaCreacion" IS NOT NULL
                         AND rl."FechaCierre" IS NOT NULL
                        THEN DATE(rl."FechaCierre") - DATE(pso."FechaCreacion")
                    END
                ), 2) AS promedio_rrll,

                ROUND(AVG(
                    CASE
                        WHEN rl."FechaCierre" IS NOT NULL
                         AND rl."FechaEnvioNomina" IS NOT NULL
                        THEN DATE(rl."FechaEnvioNomina") - DATE(rl."FechaCierre")
                    END
                ), 2) AS promedio_nomina
            FROM public."RetiroLaboral" rl
            INNER JOIN public."RegistroPersonal" rp
                ON rp."IdRegistroPersonal" = rl."IdRegistroPersonal"
            LEFT JOIN public."PazYSalvoOperaciones" pso
                ON pso."IdRetiroLaboral" = rl."IdRetiroLaboral"
            WHERE COALESCE(rl."Activo", true) = true
              AND rp."IdEstadoProceso" IN (30, 32, 35);
        """)

        promedios_row = db.execute(query_promedios).mappings().first()

        promedio_paz_y_salvo = float(promedios_row["promedio_paz_y_salvo"] or 0)
        promedio_rrll = float(promedios_row["promedio_rrll"] or 0)
        promedio_nomina = float(promedios_row["promedio_nomina"] or 0)

        return {
            "success": True,
            "message": "Indicadores de nómina retiros consultados correctamente.",
            "data": {
                "totales": {
                    "abiertos": abiertos,
                    "cerrados": cerrados,
                    "retirados": retirados,
                    "total": total,
                },
                "promedios": {
                    "pazYSalvo": promedio_paz_y_salvo,
                    "rrll": promedio_rrll,
                    "nomina": promedio_nomina,

                    # Compatibilidad temporal con el front actual
                    "operaciones": promedio_paz_y_salvo,
                },
                "distribucionEstados": [
                    {"estado": "Abierto", "cantidad": abiertos},
                    {"estado": "Cerrado", "cantidad": cerrados},
                    {"estado": "Retirado", "cantidad": retirados},
                ],
                "retirosPorMes": retiros_por_mes,
            },
        }

    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Error al consultar indicadores de nómina retiros: {str(e)}"
        )
    
@router.get("/reporte-excel")
def descargar_reporte_excel_nomina_retiros(db: Session = Depends(get_db)):
    try:
        rows = _consultar_retiros_nomina(db)

        # Orden para que quede claro: abiertos, cerrados y retirados.
        rows = sorted(
            rows,
            key=lambda row: (
                1 if int(row.get("IdEstadoProceso") or 0) == 30 else
                2 if int(row.get("IdEstadoProceso") or 0) == 32 else
                3 if int(row.get("IdEstadoProceso") or 0) == 35 else
                4,
                str(row.get("FechaRetiro") or ""),
                _nombre_completo(row).upper(),
            )
        )

        wb = Workbook()
        ws = wb.active
        ws.title = "Nomina Retiros"

        _configurar_hoja_detalle(ws, "Reporte Nómina Retiros", rows)

        output = BytesIO()
        wb.save(output)
        output.seek(0)

        nombre_archivo = f"Reporte_Nomina_Retiros_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"

        headers = {
            "Content-Disposition": f'attachment; filename="{nombre_archivo}"'
        }

        return StreamingResponse(
            output,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers=headers,
        )

    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Error al generar reporte Excel de nómina retiros: {str(e)}"
        )

@router.put("/{id_retiro_laboral}/finalizar")
def finalizar_retiro_nomina(
    id_retiro_laboral: int,
    payload: FinalizarRetiroNominaRequest,
    db: Session = Depends(get_db)
):
    try:
        query_estado_retirado = text("""
            SELECT "IdEstadoProceso"
            FROM public."EstadoProceso"
            WHERE "Nombre" ILIKE 'Retirado'
              AND "Estado" = B'1'
            LIMIT 1;
        """)

        estado_retirado = db.execute(query_estado_retirado).mappings().first()

        if not estado_retirado:
            raise HTTPException(
                status_code=400,
                detail="No existe el estado Retirado activo en EstadoProceso."
            )

        id_estado_retirado = estado_retirado["IdEstadoProceso"]

        query_retiro = text("""
            SELECT
                rl."IdRetiroLaboral",
                rl."IdRegistroPersonal",
                rp."IdEstadoProceso"
            FROM public."RetiroLaboral" rl
            INNER JOIN public."RegistroPersonal" rp
                ON rp."IdRegistroPersonal" = rl."IdRegistroPersonal"
            WHERE rl."IdRetiroLaboral" = :id_retiro_laboral
              AND COALESCE(rl."Activo", true) = true;
        """)

        retiro = db.execute(
            query_retiro,
            {"id_retiro_laboral": id_retiro_laboral}
        ).mappings().first()

        if not retiro:
            raise HTTPException(
                status_code=404,
                detail="Retiro laboral no encontrado."
            )

        if int(retiro["IdEstadoProceso"]) != 32:
            raise HTTPException(
                status_code=400,
                detail="Solo se pueden finalizar retiros enviados a nómina."
            )

        # Validación obligatoria documentos de nómina:
        # 15 = Retiro ARL
        # 16 = Liquidación de contrato
        query_documentos_obligatorios = text("""
            SELECT
                tdr."IdTipoDocumentoRetiro",
                tdr."Nombre" AS "NombreDocumento",
                CASE
                    WHEN EXISTS (
                        SELECT 1
                        FROM public."RetiroLaboralAdjunto" rla
                        WHERE rla."IdRetiroLaboral" = :id_retiro_laboral
                          AND rla."IdTipoDocumentoRetiro" = tdr."IdTipoDocumentoRetiro"
                          AND COALESCE(rla."Activo", true) = true
                          AND COALESCE(rla."Eliminado", false) = false
                          AND rla."RutaArchivo" IS NOT NULL
                    ) THEN true
                    ELSE false
                END AS "Adjuntado"
            FROM public."TipoDocumentoRetiro" tdr
            WHERE tdr."IdTipoDocumentoRetiro" IN (15, 16)
            ORDER BY tdr."IdTipoDocumentoRetiro";
        """)

        documentos_estado = db.execute(
            query_documentos_obligatorios,
            {"id_retiro_laboral": id_retiro_laboral}
        ).mappings().all()

        documentos_faltantes = [
            doc["NombreDocumento"]
            for doc in documentos_estado
            if not bool(doc["Adjuntado"])
        ]

        if documentos_faltantes:
            raise HTTPException(
                status_code=400,
                detail={
                    "message": "No se puede finalizar el retiro. Faltan documentos obligatorios de nómina.",
                    "documentos_faltantes": documentos_faltantes,
                }
            )

        query_update_retiro = text("""
            UPDATE public."RetiroLaboral"
            SET
                "EstadoCasoRRLL" = 'CERRADO',
                "FechaEnvioNomina" = NOW(),                
                "FechaPagoLiquidacion" = :fecha_pago_liquidacion,
                "FechaActualizacion" = NOW(),
                "UsuarioActualizacion" = 'nomina'
            WHERE "IdRetiroLaboral" = :id_retiro_laboral;
        """)

        query_update_registro = text("""
            UPDATE public."RegistroPersonal"
            SET
                "IdEstadoProceso" = :id_estado_retirado
            WHERE "IdRegistroPersonal" = :id_registro_personal;
        """)

        db.execute(
            query_update_retiro,
            {
                "id_retiro_laboral": id_retiro_laboral,
                "fecha_pago_liquidacion": payload.fecha_pago_liquidacion,
            }
        )

        db.execute(query_update_registro, {
            "id_estado_retirado": id_estado_retirado,
            "id_registro_personal": retiro["IdRegistroPersonal"],
        })

        db.commit()

        return {
            "success": True,
            "message": "Retiro finalizado correctamente por nómina.",
            "data": {
                "IdRetiroLaboral": id_retiro_laboral,
                "IdRegistroPersonal": retiro["IdRegistroPersonal"],
                "IdEstadoProceso": id_estado_retirado,
                "EstadoProceso": "Retirado",
                "FechaPagoLiquidacion": payload.fecha_pago_liquidacion.isoformat(),
            },
        }

    except HTTPException:
        db.rollback()
        raise

    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=500,
            detail=f"Error al finalizar retiro desde nómina: {str(e)}"
        )

@router.put("/{id_retiro_laboral}/devolver")
def devolver_retiro_rrll(
    id_retiro_laboral: int,
    db: Session = Depends(get_db)
):
    try:
        query_retiro = text("""
            SELECT
                rl."IdRetiroLaboral",
                rl."IdRegistroPersonal",
                rp."IdEstadoProceso"
            FROM public."RetiroLaboral" rl
            INNER JOIN public."RegistroPersonal" rp
                ON rp."IdRegistroPersonal" = rl."IdRegistroPersonal"
            WHERE rl."IdRetiroLaboral" = :id_retiro_laboral
              AND COALESCE(rl."Activo", true) = true;
        """)

        retiro = db.execute(
            query_retiro,
            {"id_retiro_laboral": id_retiro_laboral}
        ).mappings().first()

        if not retiro:
            raise HTTPException(
                status_code=404,
                detail="Retiro laboral no encontrado."
            )

        if int(retiro["IdEstadoProceso"]) != 32:
            raise HTTPException(
                status_code=400,
                detail="Solo se pueden devolver retiros enviados a nómina."
            )

        query_update_retiro = text("""
            UPDATE public."RetiroLaboral"
            SET
                "EstadoCasoRRLL" = 'ABIERTO',
                "FechaEnvioNomina" = NULL,
                "FechaActualizacion" = NOW(),
                "UsuarioActualizacion" = 'nomina'
            WHERE "IdRetiroLaboral" = :id_retiro_laboral;
        """)

        query_update_registro = text("""
            UPDATE public."RegistroPersonal"
            SET
                "IdEstadoProceso" = 30
            WHERE "IdRegistroPersonal" = :id_registro_personal;
        """)

        db.execute(
            query_update_retiro,
            {"id_retiro_laboral": id_retiro_laboral}
        )

        db.execute(
            query_update_registro,
            {"id_registro_personal": retiro["IdRegistroPersonal"]}
        )

        db.commit()

        return {
            "success": True,
            "message": "Retiro devuelto correctamente a Relaciones Laborales.",
            "data": {
                "IdRetiroLaboral": id_retiro_laboral,
                "IdRegistroPersonal": retiro["IdRegistroPersonal"],
                "IdEstadoProceso": 30,
                "EstadoProceso": "Abierto",
            },
        }

    except HTTPException:
        db.rollback()
        raise

    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=500,
            detail=f"Error al devolver retiro a RRLL: {str(e)}"
        )


@router.post("/{id_retiro_laboral}/adjuntos")
async def subir_adjunto_nomina_retiro(
    id_retiro_laboral: int,
    IdTipoDocumentoRetiro: int = Form(...),
    file: UploadFile = File(...),
    db: Session = Depends(get_db)
):
    try:
        documentos_permitidos = {
            15: "Retiro ARL",
            16: "Liquidación de contrato",
        }

        if IdTipoDocumentoRetiro not in documentos_permitidos:
            raise HTTPException(
                status_code=400,
                detail="Nómina solo puede adjuntar Retiro ARL o Liquidación de contrato."
            )

        query_retiro = text("""
            SELECT
                rl."IdRetiroLaboral",
                rl."IdRegistroPersonal",
                rp."IdEstadoProceso"
            FROM public."RetiroLaboral" rl
            INNER JOIN public."RegistroPersonal" rp
                ON rp."IdRegistroPersonal" = rl."IdRegistroPersonal"
            WHERE rl."IdRetiroLaboral" = :id_retiro_laboral
              AND COALESCE(rl."Activo", true) = true;
        """)

        retiro = db.execute(
            query_retiro,
            {"id_retiro_laboral": id_retiro_laboral}
        ).mappings().first()

        if not retiro:
            raise HTTPException(
                status_code=404,
                detail="Retiro laboral no encontrado."
            )

        if int(retiro["IdEstadoProceso"]) not in (32, 35):
            raise HTTPException(
                status_code=400,
                detail="Solo se pueden adjuntar documentos de nómina a retiros enviados a nómina o retirados."
            )

        contenido = await file.read()

        if not contenido:
            raise HTTPException(
                status_code=400,
                detail="El archivo está vacío."
            )

        extension = os.path.splitext(file.filename or "")[1].lower() or ".pdf"
        fecha_nombre = datetime.now().strftime("%Y%m%d_%H%M%S")

        nombre_archivo = (
            f"retiro_{id_retiro_laboral}_tipo_{IdTipoDocumentoRetiro}_{fecha_nombre}{extension}"
        )

        carpeta_destino = os.path.join(
            "storage",
            "rrll",
            "retiros",
            str(id_retiro_laboral)
        )

        os.makedirs(carpeta_destino, exist_ok=True)

        ruta_archivo = os.path.join(carpeta_destino, nombre_archivo)

        with open(ruta_archivo, "wb") as f:
            f.write(contenido)

        ruta_bd = ruta_archivo.replace("\\", "/")

        query_insert = text("""
            INSERT INTO public."RetiroLaboralAdjunto"
            (
                "IdRetiroLaboral",
                "IdTipoDocumentoRetiro",
                "NombreArchivo",
                "RutaArchivo",
                "ExtensionArchivo",
                "PesoArchivo",
                "Observacion",
                "Activo",
                "FechaCreacion",
                "FechaActualizacion",
                "CreadoPor",
                "UsuarioActualizacion",
                "OrigenArchivo",
                "MimeType",
                "NombreArchivoOriginal",
                "Eliminado"
            )
            VALUES
            (
                :id_retiro_laboral,
                :id_tipo_documento_retiro,
                :nombre_archivo,
                :ruta_archivo,
                :extension_archivo,
                :peso_archivo,
                :observacion,
                true,
                NOW(),
                NOW(),
                'nomina',
                'nomina',
                'NOMINA',
                :mime_type,
                :nombre_archivo_original,
                false
            )
            RETURNING "IdRetiroLaboralAdjunto";
        """)

        nuevo = db.execute(query_insert, {
            "id_retiro_laboral": id_retiro_laboral,
            "id_tipo_documento_retiro": IdTipoDocumentoRetiro,
            "nombre_archivo": nombre_archivo,
            "ruta_archivo": ruta_bd,
            "extension_archivo": extension,
            "peso_archivo": len(contenido),
            "observacion": "Carga desde módulo Nómina Retiros",
            "mime_type": file.content_type or "application/pdf",
            "nombre_archivo_original": file.filename or nombre_archivo,
        }).mappings().first()

        db.commit()

        return {
            "success": True,
            "message": "Documento de nómina adjuntado correctamente.",
            "data": {
                "IdRetiroLaboralAdjunto": nuevo["IdRetiroLaboralAdjunto"],
                "IdRetiroLaboral": id_retiro_laboral,
                "IdTipoDocumentoRetiro": IdTipoDocumentoRetiro,
                "NombreDocumento": documentos_permitidos[IdTipoDocumentoRetiro],
                "NombreArchivo": nombre_archivo,
            },
        }

    except HTTPException:
        db.rollback()
        raise

    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=500,
            detail=f"Error al adjuntar documento de nómina: {str(e)}"
        )