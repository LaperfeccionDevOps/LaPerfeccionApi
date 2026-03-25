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
        query_retiro = text("""
            SELECT
                "IdRetiroLaboral",
                "IdRegistroPersonal"
            FROM public."RetiroLaboral"
            WHERE "IdRetiroLaboral" = :id_retiro_laboral;
        """)

        retiro_row = db.execute(
            query_retiro,
            {"id_retiro_laboral": id_retiro_laboral}
        ).mappings().first()

        if not retiro_row:
            db.rollback()
            raise HTTPException(status_code=404, detail="Retiro laboral no encontrado.")

        id_registro_personal = retiro_row["IdRegistroPersonal"]

        query_update_retiro = text("""
            UPDATE public."RetiroLaboral"
            SET
                "EstadoCasoRRLL" = :EstadoCasoRRLL,
                "FechaCierre" = :FechaCierre,
                "FechaEnvioNomina" = :FechaEnvioNomina,
                "FechaActualizacion" = CURRENT_TIMESTAMP,
                "UsuarioActualizacion" = :UsuarioActualizacion
            WHERE "IdRetiroLaboral" = :id_retiro_laboral
            RETURNING "IdRetiroLaboral";
        """)

        result_retiro = db.execute(query_update_retiro, {
            "EstadoCasoRRLL": payload.EstadoCasoRRLL,
            "FechaCierre": payload.FechaCierre,
            "FechaEnvioNomina": payload.FechaEnvioNomina,
            "UsuarioActualizacion": payload.UsuarioActualizacion,
            "id_retiro_laboral": id_retiro_laboral
        })

        retiro_actualizado = result_retiro.scalar()

        if not retiro_actualizado:
            db.rollback()
            raise HTTPException(status_code=404, detail="No se pudo actualizar el retiro laboral.")

        query_update_registro = text("""
            UPDATE public."RegistroPersonal"
            SET
                "IdEstadoProceso" = :IdEstadoProceso
            WHERE "IdRegistroPersonal" = :IdRegistroPersonal;
        """)

        db.execute(query_update_registro, {
            "IdEstadoProceso": payload.IdEstadoProceso,
            "IdRegistroPersonal": id_registro_personal
        })

        db.commit()

        return {
            "success": True,
            "message": "Estado del retiro laboral actualizado correctamente.",
            "data": {
                "IdRetiroLaboral": retiro_actualizado,
                "IdRegistroPersonal": id_registro_personal,
                "EstadoCasoRRLL": payload.EstadoCasoRRLL,
                "IdEstadoProceso": payload.IdEstadoProceso
            }
        }

    except HTTPException:
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
        query = text("""
            UPDATE public."RetiroLaboral"
            SET
                "IdTipificacionRetiro" = COALESCE(:IdTipificacionRetiro, "IdTipificacionRetiro"),
                "ObservacionRetiro" = COALESCE(:ObservacionRetiro, "ObservacionRetiro"),
                "DevolucionCarnet" = COALESCE(:DevolucionCarnet, "DevolucionCarnet"),
                "RetiroLegalizado" = COALESCE(:RetiroLegalizado, "RetiroLegalizado"),
                "FechaActualizacion" = CURRENT_TIMESTAMP,
                "UsuarioActualizacion" = :UsuarioActualizacion
            WHERE "IdRetiroLaboral" = :id_retiro_laboral
            RETURNING
                "IdRetiroLaboral",
                "IdTipificacionRetiro",
                "ObservacionRetiro",
                "DevolucionCarnet",
                "RetiroLegalizado",
                "FechaActualizacion",
                "UsuarioActualizacion";
        """)

        result = db.execute(query, {
            "IdTipificacionRetiro": payload.IdTipificacionRetiro,
            "ObservacionRetiro": payload.ObservacionRetiro,
            "DevolucionCarnet": payload.DevolucionCarnet,
            "RetiroLegalizado": payload.RetiroLegalizado,
            "UsuarioActualizacion": payload.UsuarioActualizacion,
            "id_retiro_laboral": id_retiro_laboral
        })

        row = result.fetchone()
        db.commit()

        if not row:
            raise HTTPException(
                status_code=404,
                detail="No se encontró el retiro laboral para actualizar."
            )

        return {
            "success": True,
            "message": "Detalle del retiro actualizado correctamente.",
            "data": dict(row._mapping)
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