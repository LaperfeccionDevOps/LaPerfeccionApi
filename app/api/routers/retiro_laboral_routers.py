from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session

from infrastructure.db.deps import get_db
from domain.schemas.retiro_laboral import (
    RetiroLaboralCreate,
    RetiroLaboralEstadoUpdate,
    RetiroLaboralDetalleUpdate,
)
from services.rrll_documentos_service import (
    generar_y_registrar_primer_llamado,
    generar_y_registrar_segundo_llamado,
    generar_y_registrar_carta_finalizacion,
    generar_y_registrar_paquete_retiro,
)
from fastapi.responses import FileResponse
from pathlib import Path
from datetime import datetime

from typing import Optional
from fastapi import Query


router = APIRouter(prefix="/api/retiros-laborales", tags=["Retiros Laborales"])


@router.get("/motivos")
def listar_motivos_retiro(db: Session = Depends(get_db)):
    try:
        query = text("""
            SELECT 
                "IdMotivoRetiro",
                "Nombre",
                "Descripcion",
                "Activo",
                "FechaCreacion",
                "FechaActualizacion",
                "CreadoPor",
                "UsuarioActualizacion"
            FROM public."MotivoRetiro"
            WHERE "Activo" = true
            ORDER BY "IdMotivoRetiro";
        """)

        result = db.execute(query)
        motivos = result.mappings().all()

        return {
            "success": True,
            "message": "Motivos de retiro consultados correctamente.",
            "data": [dict(row) for row in motivos]
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error al consultar motivos de retiro: {str(e)}")


@router.get("/motivos/{id_motivo_retiro}/documentos")
def listar_documentos_por_motivo(id_motivo_retiro: int, db: Session = Depends(get_db)):
    try:
        query = text("""
            SELECT 
                mrd."IdMotivoRetiroDocumento",
                mrd."IdMotivoRetiro",
                tdr."IdTipoDocumentoRetiro",
                tdr."Nombre",
                tdr."Descripcion",
                mrd."EsObligatorio",
                mrd."Orden",
                mrd."Activo"
            FROM public."MotivoRetiroDocumento" mrd
            INNER JOIN public."TipoDocumentoRetiro" tdr
                ON mrd."IdTipoDocumentoRetiro" = tdr."IdTipoDocumentoRetiro"
            WHERE mrd."IdMotivoRetiro" = :id_motivo_retiro
              AND mrd."Activo" = true
              AND tdr."Activo" = true
            ORDER BY mrd."Orden";
        """)

        result = db.execute(query, {"id_motivo_retiro": id_motivo_retiro})
        documentos = result.mappings().all()

        return {
            "success": True,
            "message": "Documentos del motivo consultados correctamente.",
            "data": [dict(row) for row in documentos]
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error al consultar documentos del motivo: {str(e)}")


@router.post("")
def crear_retiro_laboral(payload: RetiroLaboralCreate, db: Session = Depends(get_db)):
    try:
        query = text("""
            INSERT INTO public."RetiroLaboral" (
                "IdRegistroPersonal",
                "IdCliente",
                "IdMotivoRetiro",
                "IdEstadoProceso",
                "FechaProceso",
                "FechaRetiro",
                "FechaCierre",
                "FechaEnvioNomina",
                "ObservacionGeneral",
                "Activo",
                "FechaCreacion",
                "UsuarioActualizacion"
            )
            VALUES (
                :IdRegistroPersonal,
                :IdCliente,
                :IdMotivoRetiro,
                :IdEstadoProceso,
                :FechaProceso,
                :FechaRetiro,
                :FechaCierre,
                :FechaEnvioNomina,
                :ObservacionGeneral,
                true,
                CURRENT_TIMESTAMP,
                :UsuarioActualizacion
            )
            RETURNING "IdRetiroLaboral";
        """)

        result = db.execute(query, {
            "IdRegistroPersonal": payload.IdRegistroPersonal,
            "IdCliente": payload.IdCliente,
            "IdMotivoRetiro": payload.IdMotivoRetiro,
            "IdEstadoProceso": payload.IdEstadoProceso,
            "FechaProceso": payload.FechaProceso,
            "FechaRetiro": payload.FechaRetiro,
            "FechaCierre": payload.FechaCierre,
            "FechaEnvioNomina": payload.FechaEnvioNomina,
            "ObservacionGeneral": payload.ObservacionGeneral,
            "UsuarioActualizacion": payload.UsuarioActualizacion
        })

        nuevo_id = result.scalar()
        db.commit()

        return {
            "success": True,
            "message": "Retiro laboral creado correctamente.",
            "data": {
                "IdRetiroLaboral": nuevo_id
            }
        }

    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Error al crear retiro laboral: {str(e)}")
    


@router.get("/dashboard-indicadores")
def dashboard_indicadores_rrll(
    anio: Optional[int] = Query(None),
    mes: Optional[int] = Query(None),
    db: Session = Depends(get_db)
):
    try:
        where_filtros = 'WHERE COALESCE(rl."Activo", true) = true'
        params = {}

        if anio:
            where_filtros += ' AND EXTRACT(YEAR FROM rl."FechaRetiro") = :anio'
            params["anio"] = anio

        if mes:
            where_filtros += ' AND EXTRACT(MONTH FROM rl."FechaRetiro") = :mes'
            params["mes"] = mes

        query_totales = text(f"""
            SELECT
                COUNT(*) AS total_retiros,
                COUNT(*) FILTER (WHERE UPPER(COALESCE(rl."EstadoCasoRRLL", '')) = 'ABIERTO') AS retiros_abiertos,
                COUNT(*) FILTER (WHERE UPPER(COALESCE(rl."EstadoCasoRRLL", '')) = 'CERRADO') AS retiros_cerrados,
                COUNT(*) FILTER (
                    WHERE UPPER(COALESCE(rl."RetiroLegalizado", 'NO')) NOT IN ('SI', 'SÍ', 'TRUE', '1')
                ) AS pendientes_documentacion
            FROM public."RetiroLaboral" rl
            {where_filtros};
        """)

        query_estados = text(f"""
            SELECT COALESCE(rl."EstadoCasoRRLL", 'SIN ESTADO') AS estado, COUNT(*) AS cantidad
            FROM public."RetiroLaboral" rl
            {where_filtros}
            GROUP BY rl."EstadoCasoRRLL"
            ORDER BY cantidad DESC;
        """)

        query_motivos = text(f"""
            SELECT COALESCE(mr."Nombre", 'SIN MOTIVO') AS motivo, COUNT(*) AS cantidad
            FROM public."RetiroLaboral" rl
            LEFT JOIN public."MotivoRetiro" mr ON rl."IdMotivoRetiro" = mr."IdMotivoRetiro"
            {where_filtros}
            GROUP BY mr."Nombre"
            ORDER BY cantidad DESC;
        """)

        query_tipificaciones = text(f"""
            SELECT COALESCE(tr."Nombre", 'SIN TIPIFICACIÓN') AS tipificacion, COUNT(*) AS cantidad
            FROM public."RetiroLaboral" rl
            LEFT JOIN public."TipificacionRetiro" tr ON rl."IdTipificacionRetiro" = tr."IdTipificacionRetiro"
            {where_filtros}
            GROUP BY tr."Nombre"
            ORDER BY cantidad DESC;
        """)

        query_documentos = text(f"""
            SELECT 
                tdr."Nombre" AS documento,
                COUNT(rla."IdRetiroLaboralAdjunto") AS cantidad
            FROM public."RetiroLaboral" rl
            CROSS JOIN public."TipoDocumentoRetiro" tdr
            LEFT JOIN public."RetiroLaboralAdjunto" rla
                ON rla."IdRetiroLaboral" = rl."IdRetiroLaboral"
                AND rla."IdTipoDocumentoRetiro" = tdr."IdTipoDocumentoRetiro"
                AND COALESCE(rla."Eliminado", false) = false
                AND COALESCE(rla."Activo", true) = true
            {where_filtros}
            AND tdr."IdTipoDocumentoRetiro" IN (2, 4, 10)
            GROUP BY tdr."Nombre"
            ORDER BY cantidad DESC;
        """)

        query_recientes = text(f"""
            SELECT
                rl."IdRetiroLaboral",
                rp."Nombres",
                rp."Apellidos",
                rp."NumeroIdentificacion",
                mr."Nombre" AS motivo_retiro,
                tr."Nombre" AS tipificacion_retiro,
                rl."EstadoCasoRRLL",
                rl."FechaRetiro"
            FROM public."RetiroLaboral" rl
            LEFT JOIN public."RegistroPersonal" rp ON rl."IdRegistroPersonal" = rp."IdRegistroPersonal"
            LEFT JOIN public."MotivoRetiro" mr ON rl."IdMotivoRetiro" = mr."IdMotivoRetiro"
            LEFT JOIN public."TipificacionRetiro" tr ON rl."IdTipificacionRetiro" = tr."IdTipificacionRetiro"
            {where_filtros}
            ORDER BY rl."FechaRetiro" DESC NULLS LAST
            LIMIT 10;
        """)

        return {
            "success": True,
            "message": "Indicadores RRLL consultados correctamente.",
            "data": {
                "filtros": {"anio": anio, "mes": mes},
                "totales": dict(db.execute(query_totales, params).mappings().first()),
                "estados": [dict(r) for r in db.execute(query_estados, params).mappings().all()],
                "motivos": [dict(r) for r in db.execute(query_motivos, params).mappings().all()],
                "tipificaciones": [dict(r) for r in db.execute(query_tipificaciones, params).mappings().all()],
                "documentos": [dict(r) for r in db.execute(query_documentos, params).mappings().all()],
                "retiros_recientes": [dict(r) for r in db.execute(query_recientes, params).mappings().all()],
            }
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error consultando dashboard RRLL: {str(e)}")

@router.get("/{id_retiro_laboral}")
def consultar_retiro_laboral(id_retiro_laboral: int, db: Session = Depends(get_db)):
    try:
        query = text("""
            SELECT
               rl."IdRetiroLaboral",
        rl."IdRegistroPersonal",
        rl."IdCliente",
        c."Nombre" AS "NombreCliente",
        rl."IdMotivoRetiro",
        mr."Nombre" AS "NombreMotivoRetiro",
        rl."FechaProceso",
        rl."FechaRetiro",
        rl."FechaCierre",
        rl."FechaEnvioNomina",
        rl."ObservacionGeneral",
        rl."IdTipificacionRetiro",
        rl."ObservacionRetiro",
        rl."DevolucionCarnet",
        rl."RetiroLegalizado",
        rl."EstadoCasoRRLL",
        rl."Activo",
        rl."FechaCreacion",
        rl."FechaActualizacion",
        rl."UsuarioActualizacion"
    FROM public."RetiroLaboral" rl
    LEFT JOIN public."Cliente" c
        ON rl."IdCliente" = c."IdCliente"
    LEFT JOIN public."MotivoRetiro" mr
        ON rl."IdMotivoRetiro" = mr."IdMotivoRetiro"
    WHERE rl."IdRetiroLaboral" = :id_retiro_laboral;
        """)

        result = db.execute(query, {"id_retiro_laboral": id_retiro_laboral})
        retiro = result.mappings().first()

        if not retiro:
            raise HTTPException(status_code=404, detail="Retiro laboral no encontrado.")

        return {
            "success": True,
            "message": "Retiro laboral consultado correctamente.",
            "data": dict(retiro)
        }

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error al consultar retiro laboral: {str(e)}")


@router.put("/{id_retiro_laboral}/estado")
def actualizar_estado_retiro_laboral(
    id_retiro_laboral: int,
    payload: RetiroLaboralEstadoUpdate,
    db: Session = Depends(get_db)
):
    try:
        retiro_row = db.execute(
            text("""
                SELECT
                    "IdRetiroLaboral",
                    "IdRegistroPersonal",
                    "FechaRetiro"
                FROM public."RetiroLaboral"
                WHERE "IdRetiroLaboral" = :id_retiro_laboral;
            """),
            {"id_retiro_laboral": id_retiro_laboral}
        ).mappings().first()

        if not retiro_row:
            db.rollback()
            raise HTTPException(status_code=404, detail="Retiro laboral no encontrado.")

        id_registro_personal = retiro_row["IdRegistroPersonal"]

        fecha_cierre = payload.FechaCierre
        fecha_envio_nomina = payload.FechaEnvioNomina

        if payload.EstadoCasoRRLL == "ENVIADO_NOMINA":
            fecha_cierre = payload.FechaCierre or datetime.utcnow()
            fecha_envio_nomina = None

        result_retiro = db.execute(
            text("""
               UPDATE public."RetiroLaboral"
                    SET
                        "EstadoCasoRRLL" = :EstadoCasoRRLL,
                        "FechaCierre" = :FechaCierre,
                        "FechaEnvioNomina" = :FechaEnvioNomina,
                        "Activo" = CASE
                            WHEN :EstadoCasoRRLL = 'ABIERTO' THEN true
                            WHEN :EstadoCasoRRLL IN ('ENVIADO_NOMINA', 'CERRADO') THEN false
                            ELSE "Activo"
                        END,
                        "FechaActualizacion" = CURRENT_TIMESTAMP,
                        "UsuarioActualizacion" = :UsuarioActualizacion
                WHERE "IdRetiroLaboral" = :id_retiro_laboral
                RETURNING
                    "IdRetiroLaboral",
                    "IdRegistroPersonal",
                    "FechaRetiro";
            """),
            {
                "EstadoCasoRRLL": payload.EstadoCasoRRLL,
                "FechaCierre": fecha_cierre,
                "FechaEnvioNomina": fecha_envio_nomina,
                "UsuarioActualizacion": payload.UsuarioActualizacion,
                "id_retiro_laboral": id_retiro_laboral
            }
        )

        retiro_actualizado = result_retiro.mappings().first()

        if not retiro_actualizado:
            db.rollback()
            raise HTTPException(status_code=404, detail="No se pudo actualizar el retiro laboral.")

        if retiro_actualizado["FechaRetiro"]:
            paz_existente = db.execute(
                text("""
                    SELECT "IdPazYSalvo"
                    FROM public."PazYSalvoOperaciones"
                    WHERE "IdRetiroLaboral" = :id_retiro_laboral
                       OR "IdRegistroPersonal" = :id_registro_personal
                    ORDER BY "IdPazYSalvo" DESC
                    LIMIT 1;
                """),
                {
                    "id_retiro_laboral": retiro_actualizado["IdRetiroLaboral"],
                    "id_registro_personal": retiro_actualizado["IdRegistroPersonal"],
                }
            ).mappings().first()

            if paz_existente:
                db.execute(
                    text("""
                        UPDATE public."PazYSalvoOperaciones"
                        SET
                            "IdRegistroPersonal" = :id_registro_personal,
                            "IdRetiroLaboral" = :id_retiro_laboral,
                            "FechaUltimoDiaLaborado" = :fecha_retiro,
                            "FechaCarga" = CURRENT_TIMESTAMP,
                            "UsuarioCreacion" = :usuario
                        WHERE "IdPazYSalvo" = :id_paz_y_salvo;
                    """),
                    {
                        "id_registro_personal": retiro_actualizado["IdRegistroPersonal"],
                        "id_retiro_laboral": retiro_actualizado["IdRetiroLaboral"],
                        "fecha_retiro": retiro_actualizado["FechaRetiro"],
                        "usuario": payload.UsuarioActualizacion or "RRLL",
                        "id_paz_y_salvo": paz_existente["IdPazYSalvo"],
                    }
                )
            else:
                db.execute(
                    text("""
                        INSERT INTO public."PazYSalvoOperaciones"
                        (
                            "IdRegistroPersonal",
                            "FechaUltimoDiaLaborado",
                            "Observacion",
                            "UsuarioCreacion",
                            "FechaCreacion",
                            "IdRetiroLaboral",
                            "FechaCarga"
                        )
                        VALUES
                        (
                            :id_registro_personal,
                            :fecha_retiro,
                            :observacion,
                            :usuario,
                            CURRENT_TIMESTAMP,
                            :id_retiro_laboral,
                            CURRENT_TIMESTAMP
                        );
                    """),
                    {
                        "id_registro_personal": retiro_actualizado["IdRegistroPersonal"],
                        "fecha_retiro": retiro_actualizado["FechaRetiro"],
                        "observacion": "Sincronizado desde cierre RRLL",
                        "usuario": payload.UsuarioActualizacion or "RRLL",
                        "id_retiro_laboral": retiro_actualizado["IdRetiroLaboral"],
                    }
                )

        db.execute(
            text("""
                UPDATE public."RegistroPersonal"
                SET "IdEstadoProceso" = :IdEstadoProceso
                WHERE "IdRegistroPersonal" = :IdRegistroPersonal;
            """),
            {
                "IdEstadoProceso": payload.IdEstadoProceso,
                "IdRegistroPersonal": id_registro_personal
            }
        )

        db.commit()

        return {
            "success": True,
            "message": "Estado del retiro laboral actualizado correctamente.",
            "data": {
                "IdRetiroLaboral": retiro_actualizado["IdRetiroLaboral"],
                "IdRegistroPersonal": id_registro_personal,
                "EstadoCasoRRLL": payload.EstadoCasoRRLL,
                "IdEstadoProceso": payload.IdEstadoProceso,
                "FechaCierre": fecha_cierre,
                "FechaEnvioNomina": fecha_envio_nomina
            }
        }

    except HTTPException:
        db.rollback()
        raise

    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=500,
            detail=f"Error al actualizar estado del retiro laboral: {str(e)}"
        )

@router.put("/{id_retiro_laboral}/detalle")
def actualizar_detalle_retiro_laboral(
    id_retiro_laboral: int,
    payload: RetiroLaboralDetalleUpdate,
    db: Session = Depends(get_db)
):
    try:
        query_retiro_actual = text("""
            SELECT
                "IdRetiroLaboral",
                "IdRegistroPersonal",
                "FechaRetiro"
            FROM public."RetiroLaboral"
            WHERE "IdRetiroLaboral" = :id_retiro_laboral;
        """)

        retiro_actual = db.execute(
            query_retiro_actual,
            {"id_retiro_laboral": id_retiro_laboral}
        ).mappings().first()

        if not retiro_actual:
            raise HTTPException(
                status_code=404,
                detail="No se encontró el retiro laboral para actualizar."
            )

        query = text("""
            UPDATE public."RetiroLaboral"
            SET
                "FechaRetiro" = COALESCE(:FechaRetiro, "FechaRetiro"),
                "IdTipificacionRetiro" = COALESCE(:IdTipificacionRetiro, "IdTipificacionRetiro"),
                "ObservacionRetiro" = COALESCE(:ObservacionRetiro, "ObservacionRetiro"),
                "DevolucionCarnet" = COALESCE(:DevolucionCarnet, "DevolucionCarnet"),
                "RetiroLegalizado" = COALESCE(:RetiroLegalizado, "RetiroLegalizado"),
                "FechaActualizacion" = CURRENT_TIMESTAMP,
                "UsuarioActualizacion" = :UsuarioActualizacion
            WHERE "IdRetiroLaboral" = :id_retiro_laboral
            RETURNING
                "IdRetiroLaboral",
                "IdRegistroPersonal",
                "FechaRetiro",
                "IdTipificacionRetiro",
                "ObservacionRetiro",
                "DevolucionCarnet",
                "RetiroLegalizado",
                "FechaActualizacion",
                "UsuarioActualizacion";
        """)

        result = db.execute(query, {
            "FechaRetiro": payload.FechaRetiro,
            "IdTipificacionRetiro": payload.IdTipificacionRetiro,
            "ObservacionRetiro": payload.ObservacionRetiro,
            "DevolucionCarnet": payload.DevolucionCarnet,
            "RetiroLegalizado": payload.RetiroLegalizado,
            "UsuarioActualizacion": payload.UsuarioActualizacion,
            "id_retiro_laboral": id_retiro_laboral
        })

        row = result.mappings().first()

        if not row:
            raise HTTPException(
                status_code=404,
                detail="No se encontró el retiro laboral para actualizar."
            )

        fecha_ultimo_dia_laborado = row["FechaRetiro"]

        if fecha_ultimo_dia_laborado:
            query_paz_salvo_existente = text("""
                SELECT "IdPazYSalvo"
                FROM public."PazYSalvoOperaciones"
                WHERE "IdRetiroLaboral" = :id_retiro_laboral
                   OR "IdRegistroPersonal" = :id_registro_personal
                ORDER BY "IdPazYSalvo" DESC
                LIMIT 1;
            """)

            paz_salvo_existente = db.execute(
                query_paz_salvo_existente,
                {
                    "id_retiro_laboral": id_retiro_laboral,
                    "id_registro_personal": row["IdRegistroPersonal"],
                }
            ).mappings().first()

            if paz_salvo_existente:
                query_update_paz_salvo = text("""
                    UPDATE public."PazYSalvoOperaciones"
                    SET
                        "IdRegistroPersonal" = :id_registro_personal,
                        "IdRetiroLaboral" = :id_retiro_laboral,
                        "FechaUltimoDiaLaborado" = :fecha_ultimo_dia_laborado,
                        "UsuarioCreacion" = :usuario_actualizacion,
                        "FechaCarga" = CURRENT_TIMESTAMP
                    WHERE "IdPazYSalvo" = :id_paz_y_salvo;
                """)

                db.execute(query_update_paz_salvo, {
                    "id_registro_personal": row["IdRegistroPersonal"],
                    "id_retiro_laboral": id_retiro_laboral,
                    "fecha_ultimo_dia_laborado": fecha_ultimo_dia_laborado,
                    "usuario_actualizacion": payload.UsuarioActualizacion or "RRLL",
                    "id_paz_y_salvo": paz_salvo_existente["IdPazYSalvo"],
                })

            else:
                query_insert_paz_salvo = text("""
                    INSERT INTO public."PazYSalvoOperaciones"
                    (
                        "IdRegistroPersonal",
                        "FechaUltimoDiaLaborado",
                        "Observacion",
                        "UsuarioCreacion",
                        "FechaCreacion",
                        "IdRetiroLaboral",
                        "FechaCarga"
                    )
                    VALUES
                    (
                        :id_registro_personal,
                        :fecha_ultimo_dia_laborado,
                        :observacion,
                        :usuario_creacion,
                        CURRENT_TIMESTAMP,
                        :id_retiro_laboral,
                        CURRENT_TIMESTAMP
                    );
                """)

                db.execute(query_insert_paz_salvo, {
                    "id_registro_personal": row["IdRegistroPersonal"],
                    "fecha_ultimo_dia_laborado": fecha_ultimo_dia_laborado,
                    "observacion": payload.ObservacionRetiro,
                    "usuario_creacion": payload.UsuarioActualizacion or "RRLL",
                    "id_retiro_laboral": id_retiro_laboral,
                })

        db.commit()

        return {
            "success": True,
            "message": "Detalle del retiro actualizado correctamente.",
            "data": dict(row)
        }

    except HTTPException:
        db.rollback()
        raise

    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=500,
            detail=f"Error actualizando detalle del retiro: {str(e)}"
        )        
@router.post("/{id_retiro_laboral}/documentos/primer-llamado/generar")
def generar_primer_llamado_endpoint(
    id_retiro_laboral: int,
    db: Session = Depends(get_db)
):
    try:
        row = generar_y_registrar_primer_llamado(
            db=db,
            id_retiro_laboral=id_retiro_laboral,
            usuario_actualizacion="RRLL"
        )

        return {
            "success": True,
            "message": "Primer llamado generado y registrado correctamente.",
            "data": row
        }

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=500,
            detail=f"Error al generar y registrar el primer llamado: {str(e)}"
        )


@router.post("/{id_retiro_laboral}/documentos/segundo-llamado/generar")
def generar_segundo_llamado_endpoint(
    id_retiro_laboral: int,
    db: Session = Depends(get_db)
):
    try:
        row = generar_y_registrar_segundo_llamado(
            db=db,
            id_retiro_laboral=id_retiro_laboral,
            usuario_actualizacion="RRLL"
        )

        return {
            "success": True,
            "message": "Segundo llamado generado y registrado correctamente.",
            "data": row
        }

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=500,
            detail=f"Error al generar y registrar el segundo llamado: {str(e)}"
        )


@router.post("/{id_retiro_laboral}/documentos/carta-finalizacion/generar")
def generar_carta_finalizacion_endpoint(
    id_retiro_laboral: int,
    db: Session = Depends(get_db)
):
    try:
        row = generar_y_registrar_carta_finalizacion(
            db=db,
            id_retiro_laboral=id_retiro_laboral,
            usuario_actualizacion="RRLL"
        )

        return {
            "success": True,
            "message": "Carta de finalización generada y registrada correctamente.",
            "data": row
        }

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=500,
            detail=f"Error al generar y registrar la carta de finalización: {str(e)}"
        )


@router.post("/{id_retiro_laboral}/documentos/paquete-retiro/generar")
def generar_paquete_retiro_endpoint(
    id_retiro_laboral: int,
    db: Session = Depends(get_db)
):
    try:
        row = generar_y_registrar_paquete_retiro(
            db=db,
            id_retiro_laboral=id_retiro_laboral,
            usuario_actualizacion="RRLL"
        )

        return {
            "success": True,
            "message": "Paquete de retiro generado y registrado correctamente.",
            "data": row
        }

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=500,
            detail=f"Error al generar y registrar el paquete de retiro: {str(e)}"
        )
    
@router.get("/carpeta-digital/{id_registro_personal}/documentos")
def obtener_documentos_retiro_carpeta_digital(
    id_registro_personal: int,
    db: Session = Depends(get_db)
):
    try:
        query_retiro = text("""
            SELECT "IdRetiroLaboral"
FROM public."RetiroLaboral"
WHERE "IdRegistroPersonal" = :id_registro_personal
ORDER BY "IdRetiroLaboral" DESC
LIMIT 1;
        """)

        retiro = db.execute(
            query_retiro,
            {"id_registro_personal": id_registro_personal}
        ).mappings().first()

        if not retiro:
            return {
                "success": True,
                "message": "El trabajador no tiene retiro laboral registrado.",
                "data": []
            }

        id_retiro_laboral = retiro["IdRetiroLaboral"]

        query_documentos = text("""
            SELECT
                tdr."IdTipoDocumentoRetiro",
                tdr."Nombre" AS "NombreDocumento",
                tdr."Descripcion",
                COALESCE(tdr."Activo", true) AS "TipoActivo",
                adj."IdRetiroLaboralAdjunto",
                :id_retiro_laboral AS "IdRetiroLaboral",
                adj."NombreArchivo",
                COALESCE(adj."NombreArchivoOriginal", adj."NombreArchivo") AS "NombreArchivoOriginal",
                adj."RutaArchivo",
                adj."ExtensionArchivo",
                adj."PesoArchivo",
                adj."Observacion",
                COALESCE(adj."OrigenArchivo", 'MANUAL') AS "OrigenArchivo",
                adj."MimeType",
                adj."FechaCreacion",
                adj."FechaActualizacion"
            FROM public."TipoDocumentoRetiro" tdr
            LEFT JOIN LATERAL (
                SELECT
                    rla."IdRetiroLaboralAdjunto",
                    rla."IdRetiroLaboral",
                    rla."IdTipoDocumentoRetiro",
                    rla."NombreArchivo",
                    rla."NombreArchivoOriginal",
                    rla."RutaArchivo",
                    rla."ExtensionArchivo",
                    rla."PesoArchivo",
                    rla."Observacion",
                    rla."OrigenArchivo",
                    rla."MimeType",
                    rla."FechaCreacion",
                    rla."FechaActualizacion"
                FROM public."RetiroLaboralAdjunto" rla
                WHERE rla."IdRetiroLaboral" = :id_retiro_laboral
                  AND rla."IdTipoDocumentoRetiro" = tdr."IdTipoDocumentoRetiro"
                  AND COALESCE(rla."Eliminado", false) = false
                  AND COALESCE(rla."Activo", true) = true
                ORDER BY rla."IdRetiroLaboralAdjunto" DESC
                LIMIT 1
            ) adj ON true
            WHERE COALESCE(tdr."Activo", true) = true
             AND tdr."IdTipoDocumentoRetiro" IN (1, 2, 4, 10, 15, 16)
            ORDER BY tdr."IdTipoDocumentoRetiro";
        """)

        documentos = db.execute(
            query_documentos,
            {"id_retiro_laboral": id_retiro_laboral}
        ).mappings().all()

        data = []

        for row in documentos:
            item = dict(row)
            item["Adjuntado"] = item.get("IdRetiroLaboralAdjunto") is not None
            data.append(item)

        query_entrevista = text("""
            SELECT
                "IdEntrevistaRetiro",
                "IdRetiroLaboral",
                "IdRegistroPersonal",
                "RutaPdf",
                "PdfGenerado",
                "FechaEnvio"
            FROM public."EntrevistaRetiro"
            WHERE "IdRegistroPersonal" = :id_registro_personal
              AND "IdRetiroLaboral" = :id_retiro_laboral
              AND COALESCE("PdfGenerado", false) = true
              AND "RutaPdf" IS NOT NULL
            ORDER BY "IdEntrevistaRetiro" DESC
            LIMIT 1;
        """)

        entrevista = db.execute(
            query_entrevista,
            {
                "id_registro_personal": id_registro_personal,
                "id_retiro_laboral": id_retiro_laboral
            }
        ).mappings().first()

        data.append({
            "IdTipoDocumentoRetiro": 999,
            "NombreDocumento": "Entrevista de retiro",
            "Descripcion": "Entrevista diligenciada por el trabajador.",
            "TipoActivo": True,
            "IdRetiroLaboralAdjunto": None,
            "IdEntrevistaRetiro": entrevista["IdEntrevistaRetiro"] if entrevista else None,
            "IdRetiroLaboral": entrevista["IdRetiroLaboral"] if entrevista else id_retiro_laboral,
            "NombreArchivo": "entrevista_retiro.pdf" if entrevista else None,
            "NombreArchivoOriginal": "entrevista_retiro.pdf" if entrevista else None,
            "RutaArchivo": entrevista["RutaPdf"] if entrevista else None,
            "ExtensionArchivo": ".pdf" if entrevista else None,
            "PesoArchivo": None,
            "Observacion": None,
            "OrigenArchivo": "ENTREVISTA",
            "MimeType": "application/pdf",
            "FechaCreacion": entrevista["FechaEnvio"] if entrevista else None,
            "FechaActualizacion": None,
            "Adjuntado": entrevista is not None
        })

        return {
            "success": True,
            "message": "Documentos de retiro consultados correctamente.",
            "data": data
        }

    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Error al consultar documentos de retiro para carpeta digital: {str(e)}"
        )
    
@router.get("/carpeta-digital/entrevista-retiro/{id_entrevista_retiro}/descargar")
def descargar_entrevista_retiro_carpeta_digital(
    id_entrevista_retiro: int,
    db: Session = Depends(get_db)
):
    try:
        query = text("""
            SELECT "RutaPdf"
            FROM public."EntrevistaRetiro"
            WHERE "IdEntrevistaRetiro" = :id_entrevista_retiro
              AND COALESCE("PdfGenerado", false) = true
              AND "RutaPdf" IS NOT NULL
            LIMIT 1;
        """)

        row = db.execute(
            query,
            {"id_entrevista_retiro": id_entrevista_retiro}
        ).mappings().first()

        if not row:
            raise HTTPException(status_code=404, detail="Entrevista de retiro no encontrada.")

        ruta_pdf = Path(row["RutaPdf"])

        if not ruta_pdf.exists():
            raise HTTPException(status_code=404, detail="El archivo PDF de entrevista no existe en el servidor.")

        return FileResponse(
            path=str(ruta_pdf),
            media_type="application/pdf",
            filename=f"entrevista_retiro_{id_entrevista_retiro}.pdf"
        )

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Error al descargar entrevista de retiro: {str(e)}"
        )
    
