# app/api/routers/entrevista_routers.py

from datetime import datetime
from typing import Optional, List

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    status,
    UploadFile,
    File,
    Query,
)
from pydantic import BaseModel
from sqlalchemy.orm import Session
from sqlalchemy import text

from infrastructure.db.deps import get_db
from domain.models.cita import Cita
from domain.models.aspirante import RegistroPersonal

router = APIRouter(
    prefix="/entrevistas",      # luego en main se vuelve /api/entrevistas
    tags=["entrevistas"],
)

# ---------------------------
# MODELOS Pydantic
# ---------------------------

class EntrevistaUpdate(BaseModel):
    idEstadoProcesoAspirante: Optional[int] = None
    observacionesEntrevista: Optional[str] = None
    usuario: Optional[str] = None


class VerificacionReferenciaItem(BaseModel):
    idReferencia: int
    resultado: int
    contactoExitoso: Optional[bool] = False
    medioContacto: Optional[str] = None
    observaciones: Optional[str] = None


class VerificacionReferenciasUpdate(BaseModel):
    usuario: str
    items: List[VerificacionReferenciaItem]


# ---------------------------
# ENDPOINTS EXISTENTES
# ---------------------------

@router.get("/ping")
def ping_entrevistas():
    return {"ok": True, "message": "Ping entrevistas"}


@router.get("/{id_cita}/detalle")
def obtener_detalle_entrevista(
    id_cita: int,
    db: Session = Depends(get_db),
):
    """
    Devuelve la información principal para la pantalla
    'Información de la Entrevista'.
    """

    # 1) Buscar la cita
    cita = (
        db.query(Cita)
        .filter(Cita.IdAgendarEntrevista == id_cita)
        .first()
    )

    if not cita:
        raise HTTPException(
            status_code=404,
            detail="Cita no encontrada",
        )

    # 2) Buscar el aspirante asociado a la cita
    aspirante = (
        db.query(RegistroPersonal)
        .filter(RegistroPersonal.IdRegistroPersonal == cita.IdRegistroPersonal)
        .first()
    )

    if not aspirante:
        raise HTTPException(
            status_code=500,
            detail="Aspirante asociado a la cita no existe",
        )

    nombre_completo = f"{aspirante.Nombres} {aspirante.Apellidos}".strip()

    # 3) Armar la respuesta para el front
    return {
        "idCita": cita.IdAgendarEntrevista,
        "idRegistroPersonal": aspirante.IdRegistroPersonal,
        "candidato": nombre_completo,
        "cargo": aspirante.Cargo,
        "fechaProgramada": cita.FechaProgramada,
        "horaProgramada": cita.HoraProgramada,
        "idEstadoProcesoAspirante": aspirante.IdEstadoProceso,
        "observacionesEntrevista": cita.Observaciones,
        "estadoEntrevista": None,
    }


@router.put("/{id_cita}")
def actualizar_entrevista(
    id_cita: int,
    payload: EntrevistaUpdate,
    db: Session = Depends(get_db),
):
    """
    Actualiza información de la entrevista:

    - Observaciones de la cita (AgendarEntrevista.Observaciones)
    - (Opcional) IdEstadoProceso del aspirante en RegistroPersonal
    """

    # 1) Buscar la cita
    cita = (
        db.query(Cita)
        .filter(Cita.IdAgendarEntrevista == id_cita)
        .first()
    )

    if not cita:
        raise HTTPException(
            status_code=404,
            detail="Cita no encontrada",
        )

    # 2) Buscar el aspirante asociado
    aspirante = (
        db.query(RegistroPersonal)
        .filter(RegistroPersonal.IdRegistroPersonal == cita.IdRegistroPersonal)
        .first()
    )

    if not aspirante:
        raise HTTPException(
            status_code=500,
            detail="Aspirante asociado a la cita no existe",
        )

    ahora = datetime.utcnow()

    # 3) Actualizar observaciones de la entrevista (cita)
    if payload.observacionesEntrevista is not None:
        cita.Observaciones = payload.observacionesEntrevista

    cita.FechaActualizacion = ahora
    if payload.usuario:
        cita.NombreUsuarioActualizacion = payload.usuario

    # 4) Actualizar estado del proceso del aspirante (si viene en el payload)
    if (
        payload.idEstadoProcesoAspirante is not None
        and payload.idEstadoProcesoAspirante != aspirante.IdEstadoProceso
    ):
        aspirante.IdEstadoProceso = payload.idEstadoProcesoAspirante
        aspirante.FechaActualizacion = ahora
        if payload.usuario:
            aspirante.UsuarioActualizacion = payload.usuario

    # 5) Guardar cambios
    db.commit()
    db.refresh(cita)
    db.refresh(aspirante)

    nombre_completo = f"{aspirante.Nombres} {aspirante.Apellidos}".strip()

    # 6) Devolver un resumen actualizado
    return {
        "idCita": cita.IdAgendarEntrevista,
        "idRegistroPersonal": aspirante.IdRegistroPersonal,
        "candidato": nombre_completo,
        "cargo": aspirante.Cargo,
        "fechaProgramada": cita.FechaProgramada,
        "horaProgramada": cita.HoraProgramada,
        "idEstadoProcesoAspirante": aspirante.IdEstadoProceso,
        "observacionesEntrevista": cita.Observaciones,
        "estadoEntrevista": None,
        "usuarioActualizacion": payload.usuario,
        "fechaActualizacion": ahora,
    }


@router.get("/{id_cita}/referencias")
def obtener_referencias_entrevista(
    id_cita: int,
    db: Session = Depends(get_db),
):
    """
    Devuelve las referencias del aspirante asociado a la cita,
    junto con la verificación si existe.
    """

    # 1) Buscar la cita
    cita = (
        db.query(Cita)
        .filter(Cita.IdAgendarEntrevista == id_cita)
        .first()
    )

    if not cita:
        raise HTTPException(
            status_code=404,
            detail="Cita no encontrada",
        )

    id_registro = cita.IdRegistroPersonal

    # 2) Traer referencias + verificación (LEFT JOIN)
    referencias_sql = text(
        """
        SELECT
            r."IdReferencia",
            r."IdRegistroPersonal",
            r."IdTipoReferencia",
            r."Nombre",
            r."Telefono",
            r."Parentesco",
            v."IdVerificacionReferencia",
            v."Resultado",
            v."ContactoExitoso",
            v."MedioContacto",
            v."Observaciones"       AS "ObservacionesVerificacion",
            v."UsuarioVerificacion",
            v."FechaVerificacion"
        FROM "Referencia" r
        LEFT JOIN "VerificacionReferencia" v
            ON v."IdReferencia" = r."IdReferencia"
        WHERE r."IdRegistroPersonal" = :id
        ORDER BY r."Nombre" ASC
        """
    )

    referencias_rows = db.execute(
        referencias_sql,
        {"id": id_registro},
    ).mappings().all()

    referencias = [dict(r) for r in referencias_rows]

    return {
        "idCita": id_cita,
        "idRegistroPersonal": id_registro,
        "referencias": referencias,
    }


@router.put("/{id_cita}/referencias")
def guardar_verificacion_referencias(
    id_cita: int,
    payload: VerificacionReferenciasUpdate,
    db: Session = Depends(get_db),
):
    """
    Guarda / actualiza la verificación de referencias para la cita dada.

    - Valida que cada IdReferencia pertenezca al aspirante de la cita.
    - Si ya existe registro en VerificacionReferencia -> UPDATE
    - Si no existe -> INSERT
    """

    # 1) Buscar la cita
    cita = (
        db.query(Cita)
        .filter(Cita.IdAgendarEntrevista == id_cita)
        .first()
    )

    if not cita:
        raise HTTPException(
            status_code=404,
            detail="Cita no encontrada",
        )

    id_registro = cita.IdRegistroPersonal
    usuario = payload.usuario
    ahora = datetime.utcnow()

    for item in payload.items:
        # 2) Validar que la referencia pertenece a este aspirante
        ref_row = db.execute(
            text(
                """
                SELECT "IdReferencia"
                FROM "Referencia"
                WHERE "IdReferencia" = :id_ref
                  AND "IdRegistroPersonal" = :id_registro
                """
            ),
            {
                "id_ref": item.idReferencia,
                "id_registro": id_registro,
            },
        ).first()

        if ref_row is None:
            raise HTTPException(
                status_code=400,
                detail=f"La referencia {item.idReferencia} no pertenece al aspirante {id_registro}",
            )

        # 3) Ver si ya existe verificación para esta referencia
        verif_row = db.execute(
            text(
                """
                SELECT "IdVerificacionReferencia"
                FROM "VerificacionReferencia"
                WHERE "IdReferencia" = :id_ref
                """
            ),
            {"id_ref": item.idReferencia},
        ).first()

        if verif_row is None:
            # INSERT
            db.execute(
                text(
                    """
                    INSERT INTO "VerificacionReferencia" (
                        "IdReferencia",
                        "Resultado",
                        "ContactoExitoso",
                        "MedioContacto",
                        "Observaciones",
                        "UsuarioVerificacion",
                        "FechaVerificacion",
                        "FechaCreacion"
                    )
                    VALUES (
                        :id_ref,
                        :resultado,
                        :contacto,
                        :medio,
                        :obs,
                        :usuario,
                        :fecha_verificacion,
                        :fecha_creacion
                    )
                    """
                ),
                {
                    "id_ref": item.idReferencia,
                    "resultado": item.resultado,
                    "contacto": item.contactoExitoso or False,
                    "medio": item.medioContacto,
                    "obs": item.observaciones,
                    "usuario": usuario,
                    "fecha_verificacion": ahora,
                    "fecha_creacion": ahora,
                },
            )
        else:
            # UPDATE
            db.execute(
                text(
                    """
                    UPDATE "VerificacionReferencia"
                    SET
                        "Resultado"            = :resultado,
                        "ContactoExitoso"      = :contacto,
                        "MedioContacto"        = :medio,
                        "Observaciones"        = :obs,
                        "UsuarioVerificacion"  = :usuario,
                        "FechaVerificacion"    = :fecha_verificacion,
                        "FechaActualizacion"   = :fecha_actualizacion,
                        "UsuarioActualizacion" = :usuario
                    WHERE "IdReferencia" = :id_ref
                    """
                ),
                {
                    "id_ref": item.idReferencia,
                    "resultado": item.resultado,
                    "contacto": item.contactoExitoso or False,
                    "medio": item.medioContacto,
                    "obs": item.observaciones,
                    "usuario": usuario,
                    "fecha_verificacion": ahora,
                    "fecha_actualizacion": ahora,
                },
            )

    # 4) Confirmar cambios
    db.commit()

    # 5) Devolver referencias + verificación actualizada
    return obtener_referencias_entrevista(id_cita=id_cita, db=db)


# ---------------------------
# NUEVOS ENDPOINTS: DOCUMENTOS
# ---------------------------

@router.get("/{id_cita}/documentos")
def obtener_documentos_aspirante(
    id_cita: int,
    db: Session = Depends(get_db),
):
    """
    Devuelve todos los documentos asociados al aspirante de esta cita.
    """

    # 1) Buscar la cita
    cita = (
        db.query(Cita)
        .filter(Cita.IdAgendarEntrevista == id_cita)
        .first()
    )

    if not cita:
        raise HTTPException(status_code=404, detail="Cita no encontrada")

    id_registro = cita.IdRegistroPersonal

    # 2) Traer documentos del aspirante
    sql = text(
        """
        SELECT
            d."IdDocumento",
            d."IdTipoDocumentacion",
            td."Descripcion"          AS "TipoDocumentacion",
            d."Estado",
            d."FechaCreacion",
            d."FeachaActualizacion"   AS "FechaActualizacion"
        FROM "RelacionTipoDocumentacion" r
        JOIN "Documentos" d
            ON d."IdDocumento" = r."IdDocumento"
        JOIN "TipoDocumentacion" td
            ON td."IdTipoDocumentacion" = d."IdTipoDocumentacion"
        WHERE r."IdRegistroPersonal" = :id_registro
        ORDER BY d."FechaCreacion" DESC NULLS LAST
        """
    )

    filas = db.execute(sql, {"id_registro": id_registro}).mappings().all()
    documentos = [dict(f) for f in filas]

    return {
        "idCita": id_cita,
        "idRegistroPersonal": id_registro,
        "documentos": documentos,
    }


@router.post(
    "/{id_cita}/documentos",
    status_code=status.HTTP_201_CREATED,
)
async def subir_documento_aspirante(
    id_cita: int,
    id_tipo_documentacion: int = Query(
        ...,
        description="IdTipoDocumentacion del documento (según catálogo TipoDocumentacion)",
    ),
    usuario: str = Query(
        ...,
        description="Usuario que realiza la carga",
    ),
    archivo: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    """
    Sube un documento (PDF) y lo asocia al aspirante de la cita.

    - Guarda el archivo en la tabla Documentos (DocumentoCargado = bytea)
    - Crea la relación en RelacionTipoDocumentacion
    """

    # 1) Buscar la cita
    cita = (
        db.query(Cita)
        .filter(Cita.IdAgendarEntrevista == id_cita)
        .first()
    )

    if not cita:
        raise HTTPException(status_code=404, detail="Cita no encontrada")

    id_registro = cita.IdRegistroPersonal

    # 2) Leer contenido del archivo
    contenido = await archivo.read()

    if not contenido:
        raise HTTPException(
            status_code=400,
            detail="El archivo está vacío",
        )

    # 3) Insertar en Documentos
    sql_insert_doc = text(
        """
        INSERT INTO "Documentos" (
            "IdTipoDocumentacion",
            "DocumentoCargado",
            "Estado",
            "FechaCreacion",
            "FeachaActualizacion"
        )
        VALUES (
            :id_tipo,
            :contenido,
            :estado,
            now(),
            now()
        )
        RETURNING "IdDocumento"
        """
    )

    result = db.execute(
        sql_insert_doc,
        {
            "id_tipo": id_tipo_documentacion,
            "contenido": contenido,
            "estado": "activo",
        },
    )

    id_documento = result.scalar_one()

    # 4) Crear relación aspirante–documento
    sql_rel = text(
        """
        INSERT INTO "RelacionTipoDocumentacion" (
            "IdRegistroPersonal",
            "IdDocumento"
        )
        VALUES (
            :id_registro,
            :id_documento
        )
        """
    )

    db.execute(
        sql_rel,
        {
            "id_registro": id_registro,
            "id_documento": id_documento,
        },
    )

    db.commit()

    return {
        "message": "Documento cargado correctamente",
        "idCita": id_cita,
        "idRegistroPersonal": id_registro,
        "idDocumento": id_documento,
        "idTipoDocumentacion": id_tipo_documentacion,
        "nombreArchivo": archivo.filename,
        "usuario": usuario,
    }
