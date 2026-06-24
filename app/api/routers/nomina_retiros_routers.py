import os
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from sqlalchemy import text
from sqlalchemy.orm import Session

from infrastructure.db.deps import get_db

router = APIRouter(prefix="/api/nomina-retiros", tags=["Nómina Retiros"])


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
                rl."FechaCierre",
                rl."FechaEnvioNomina",
                rl."EstadoCasoRRLL",
                rp."IdEstadoProceso",
                ep."Nombre" AS "EstadoProceso",
                mr."Nombre" AS "MotivoRetiro",
                tr."Nombre" AS "TipificacionRetiro",
                rl."ObservacionGeneral",
                rl."ObservacionRetiro",
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


@router.put("/{id_retiro_laboral}/finalizar")
def finalizar_retiro_nomina(
    id_retiro_laboral: int,
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

        query_update_retiro = text("""
            UPDATE public."RetiroLaboral"
            SET
                "EstadoCasoRRLL" = 'CERRADO',
                "FechaCierre" = NOW(),
                "FechaEnvioNomina" = NOW(),
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
            {"id_retiro_laboral": id_retiro_laboral}
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