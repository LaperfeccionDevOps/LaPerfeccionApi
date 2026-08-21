import base64
import os
import re
from pathlib import Path
from typing import List
from uuid import UUID as UUIDType

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import FileResponse
from sqlalchemy import text
from sqlalchemy.orm import Session

from domain.models.aspirante import (
    DocumentacionORM,
    RelacionTipoDocumentacionORM,
)
from domain.models.documento_seguridad import DocumentoSeguridad
from domain.schemas.aspirante import RegistrarDocumentosSeguridadSchema
from domain.schemas.documento_seguridad_schemas import DocumentoSeguridadOut
from infrastructure.db.deps import get_db


router = APIRouter(
    prefix="/api/documentos-seguridad",
    tags=["documentos seguridad"],
)

UPLOAD_BASE = Path(os.getenv("UPLOAD_DIR", "uploads"))


def _safe_ext(filename: str) -> str:
    ext = (Path(filename).suffix or "").lower()
    allowed = {".pdf", ".jpg", ".jpeg", ".png"}
    return ext if ext in allowed else ""


def limpiar_base64(base64_str: str) -> str:
    """
    Elimina el prefijo data:*;base64, si existe.
    Acepta bytes o string.
    """
    if isinstance(base64_str, bytes):
        base64_str = base64_str.decode("utf-8")

    match = re.match(r"^data:.*?;base64,(.*)", base64_str)

    if match:
        return match.group(1)

    return base64_str


def _validar_vinculacion_trabajador(
    db: Session,
    id_registro_personal: int,
    id_vinculacion_laboral: int,
) -> None:
    """
    Valida que la vinculación enviada realmente pertenezca
    al trabajador indicado.
    """
    existe = db.execute(
        text(
            """
            SELECT 1
            FROM public."VinculacionLaboral"
            WHERE "IdVinculacionLaboral" = :id_vinculacion
              AND "IdRegistroPersonal" = :id_registro
            LIMIT 1
            """
        ),
        {
            "id_vinculacion": id_vinculacion_laboral,
            "id_registro": id_registro_personal,
        },
    ).first()

    if not existe:
        raise HTTPException(
            status_code=400,
            detail=(
                "La vinculación laboral indicada no pertenece "
                "al trabajador solicitado."
            ),
        )


@router.post(
    "/upload",
    status_code=status.HTTP_201_CREATED,
)
async def subir_documento_seguridad(
    payload: RegistrarDocumentosSeguridadSchema,
    db: Session = Depends(get_db),
):
    """
    Guarda documentos de seguridad de Selección.

    Comportamiento:
    - Si llega idVinculacionLaboral:
      trabaja exclusivamente sobre ese ciclo laboral.
    - Si no llega:
      conserva el comportamiento legado por IdRegistroPersonal.

    Esto evita modificar documentos históricos durante un reintegro.
    """

    try:
        id_registro_personal = payload.idRegistroPersonal
        id_vinculacion_laboral = payload.idVinculacionLaboral

        if id_vinculacion_laboral is not None:
            _validar_vinculacion_trabajador(
                db=db,
                id_registro_personal=id_registro_personal,
                id_vinculacion_laboral=id_vinculacion_laboral,
            )

        resultado = []

        for doc in payload.documentos_seguridad:
            doc_data = doc.dict()

            query_relacion = (
                db.query(RelacionTipoDocumentacionORM)
                .join(
                    DocumentacionORM,
                    RelacionTipoDocumentacionORM.IdDocumento
                    == DocumentacionORM.IdDocumento,
                )
                .filter(
                    RelacionTipoDocumentacionORM.IdRegistroPersonal
                    == id_registro_personal,
                    DocumentacionORM.IdTipoDocumentacion
                    == doc_data["IdTipoDocumentacion"],
                )
            )

            # Para reintegro/ciclo laboral:
            # jamás buscar ni actualizar un documento de otro ciclo.
            if id_vinculacion_laboral is not None:
                query_relacion = query_relacion.filter(
                    RelacionTipoDocumentacionORM.IdVinculacionLaboral
                    == id_vinculacion_laboral
                )

            existe_relacion = query_relacion.first()

            base64_str = doc_data.get("DocumentoCargado")

            if base64_str:
                try:
                    base64_str = limpiar_base64(base64_str)

                    doc_data["DocumentoCargado"] = base64.b64decode(
                        base64_str
                    )

                except Exception as error:
                    print(
                        "Error al procesar DocumentoCargado: "
                        f"{error}"
                    )
                    doc_data["DocumentoCargado"] = None

            if existe_relacion:
                documento_existente = (
                    db.query(DocumentacionORM)
                    .filter(
                        DocumentacionORM.IdDocumento
                        == existe_relacion.IdDocumento
                    )
                    .first()
                )

                if documento_existente:
                    documento_existente.DocumentoCargado = (
                        doc_data["DocumentoCargado"]
                    )
                    documento_existente.Formato = doc_data["Formato"]
                    documento_existente.Nombre = doc_data["Nombre"]

                    resultado.append(documento_existente)

                continue

            nuevo_doc = DocumentacionORM(
                IdTipoDocumentacion=doc_data["IdTipoDocumentacion"],
                DocumentoCargado=doc_data["DocumentoCargado"],
                Formato=doc_data["Formato"],
                Nombre=doc_data["Nombre"],
            )

            db.add(nuevo_doc)
            db.flush()

            relacion = RelacionTipoDocumentacionORM(
                IdRegistroPersonal=id_registro_personal,
                IdDocumento=nuevo_doc.IdDocumento,
                IdVinculacionLaboral=id_vinculacion_laboral,
            )

            db.add(relacion)
            resultado.append(nuevo_doc)

        db.commit()

        for documento in resultado:
            db.refresh(documento)

        return {
            "ok": True,
            "IdRegistroPersonal": id_registro_personal,
            "IdVinculacionLaboral": id_vinculacion_laboral,
            "nombres": [
                documento.Nombre
                for documento in resultado
            ],
        }

    except HTTPException:
        db.rollback()
        raise

    except Exception as error:
        db.rollback()

        raise HTTPException(
            status_code=500,
            detail=(
                "Error al subir documentos: "
                f"{error}"
            ),
        ) from error


@router.get(
    "/aspirante/{aspirante_id}",
    response_model=List[DocumentoSeguridadOut],
)
def listar_documentos_seguridad(
    aspirante_id: UUIDType,
    db: Session = Depends(get_db),
):
    docs = (
        db.query(DocumentoSeguridad)
        .filter(
            DocumentoSeguridad.aspirante_id
            == aspirante_id
        )
        .order_by(
            DocumentoSeguridad.creado_en.desc()
        )
        .all()
    )

    return docs


@router.delete("/{documento_id}")
def eliminar_documento(
    documento_id: UUIDType,
    db: Session = Depends(get_db),
):
    doc = (
        db.query(DocumentoSeguridad)
        .filter(
            DocumentoSeguridad.id == documento_id
        )
        .first()
    )

    if not doc:
        raise HTTPException(
            status_code=404,
            detail="Documento no existe",
        )

    try:
        path = Path(doc.ruta_archivo)

        if path.exists():
            path.unlink()

    except Exception:
        pass

    db.delete(doc)
    db.commit()

    return {"ok": True}


@router.delete(
    "/registro/{id_registro_personal}/tipo/{id_tipo_documentacion}"
)
def eliminar_documento_seguridad_por_tipo(
    id_registro_personal: int,
    id_tipo_documentacion: int,
    id_vinculacion_laboral: int | None = None,
    db: Session = Depends(get_db),
):
    """
    Elimina un documento de seguridad.

    Si recibe id_vinculacion_laboral:
    elimina únicamente el documento perteneciente a ese ciclo.

    Si no recibe id_vinculacion_laboral:
    conserva el comportamiento legado.
    """

    try:
        if id_vinculacion_laboral is not None:
            _validar_vinculacion_trabajador(
                db=db,
                id_registro_personal=id_registro_personal,
                id_vinculacion_laboral=id_vinculacion_laboral,
            )

        query_relacion = (
            db.query(RelacionTipoDocumentacionORM)
            .join(
                DocumentacionORM,
                RelacionTipoDocumentacionORM.IdDocumento
                == DocumentacionORM.IdDocumento,
            )
            .filter(
                RelacionTipoDocumentacionORM.IdRegistroPersonal
                == id_registro_personal,
                DocumentacionORM.IdTipoDocumentacion
                == id_tipo_documentacion,
            )
        )

        # Cuando estamos dentro de un reintegro,
        # nunca tocar documentos históricos.
        if id_vinculacion_laboral is not None:
            query_relacion = query_relacion.filter(
                RelacionTipoDocumentacionORM.IdVinculacionLaboral
                == id_vinculacion_laboral
            )

        relacion = query_relacion.first()

        if not relacion:
            raise HTTPException(
                status_code=404,
                detail=(
                    "No existe documento de seguridad "
                    "para ese tipo, registro y vinculación."
                    if id_vinculacion_laboral is not None
                    else (
                        "No existe documento de seguridad "
                        "para ese tipo y registro."
                    )
                ),
            )

        documento = (
            db.query(DocumentacionORM)
            .filter(
                DocumentacionORM.IdDocumento
                == relacion.IdDocumento
            )
            .first()
        )

        db.delete(relacion)

        if documento:
            db.delete(documento)

        db.commit()

        return {
            "ok": True,
            "IdRegistroPersonal": id_registro_personal,
            "IdVinculacionLaboral": id_vinculacion_laboral,
            "detail": "Documento eliminado correctamente.",
        }

    except HTTPException:
        db.rollback()
        raise

    except Exception as error:
        db.rollback()

        raise HTTPException(
            status_code=500,
            detail=(
                "Error al eliminar documento: "
                f"{error}"
            ),
        ) from error