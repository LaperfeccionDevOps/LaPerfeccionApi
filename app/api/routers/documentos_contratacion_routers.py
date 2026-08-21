# app/api/routers/documentos_contratacion_routers.py

import base64
import re

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import text
from sqlalchemy.orm import Session

from domain.models.aspirante import (
    DocumentacionORM,
    RelacionTipoDocumentacionORM,
)
from domain.schemas.aspirante import RegistrarDocumentosContratacionSchema
from infrastructure.db.deps import get_db


router = APIRouter(
    prefix="/documentos-contratacion",
    tags=["documentos contratacion"],
)


# Solamente estos tipos permiten conservar varios documentos
# para el mismo trabajador dentro del mismo ciclo laboral.
TIPOS_DOCUMENTALES_MULTIPLES = {
    36,  # Entrega de dotación
    64,  # Otro sí
}


def limpiar_base64(base64_str: str) -> str:
    """
    Elimina el prefijo data:*;base64, si existe.
    Acepta bytes o string.
    """
    if isinstance(base64_str, bytes):
        base64_str = base64_str.decode("utf-8")

    match = re.match(
        r"^data:.*?;base64,(.*)",
        base64_str,
    )

    if match:
        return match.group(1)

    return base64_str


def obtener_vinculacion_actual(
    db: Session,
    id_registro_personal: int,
) -> int | None:
    """
    Obtiene la vinculación laboral abierta más reciente.

    Para reintegros permite que los documentos de contratación
    se guarden separados del ciclo histórico.

    Si el trabajador no tiene una vinculación abierta, retorna None
    y el flujo conserva el comportamiento anterior.
    """
    row = db.execute(
        text(
            """
            SELECT
                vl."IdVinculacionLaboral"
            FROM public."VinculacionLaboral" vl
            WHERE vl."IdRegistroPersonal" = :id_registro_personal
              AND UPPER(
                  COALESCE(vl."EstadoVinculacion", '')
              ) = 'EN_PROCESO'
            ORDER BY
                vl."NumeroCiclo" DESC,
                vl."IdVinculacionLaboral" DESC
            LIMIT 1
            """
        ),
        {
            "id_registro_personal": id_registro_personal,
        },
    ).mappings().first()

    if not row:
        return None

    return int(row["IdVinculacionLaboral"])


@router.post(
    "/upload",
    status_code=status.HTTP_201_CREATED,
)
async def subir_documento_contratacion(
    payload: RegistrarDocumentosContratacionSchema,
    db: Session = Depends(get_db),
):
    """
    Registra documentos de contratación.

    Reglas:
    - Si existe una vinculación laboral abierta, los documentos quedan
      asociados a esa vinculación.
    - Los documentos históricos de ciclos anteriores no se reemplazan.
    - Los tipos 36 y 64 permiten múltiples documentos dentro del ciclo.
    - Para personal sin vinculación abierta se conserva el comportamiento
      anterior por IdRegistroPersonal.
    """
    try:
        id_registro_personal = payload.idRegistroPersonal

        id_vinculacion_laboral = getattr(
            payload,
            "idVinculacionLaboral",
            None,
        )

        if id_vinculacion_laboral is None:
            id_vinculacion_laboral = obtener_vinculacion_actual(
                db,
                id_registro_personal,
            )

        resultado = []

        for doc in payload.documentos_contratacion:
            doc_data = doc.model_dump()

            tipo_documentacion = int(
                doc_data["IdTipoDocumentacion"]
            )

            permite_multiples = (
                tipo_documentacion
                in TIPOS_DOCUMENTALES_MULTIPLES
            )

            base64_str = doc_data.get(
                "DocumentoCargado"
            )

            if base64_str:
                try:
                    base64_str = limpiar_base64(
                        base64_str
                    )

                    doc_data["DocumentoCargado"] = (
                        base64.b64decode(base64_str)
                    )

                except Exception as error_base64:
                    print(
                        "Error al procesar DocumentoCargado: "
                        f"{error_base64}"
                    )

                    doc_data["DocumentoCargado"] = None

            existe_relacion = None

            if not permite_multiples:
                query = (
                    db.query(
                        RelacionTipoDocumentacionORM
                    )
                    .join(
                        DocumentacionORM,
                        (
                            RelacionTipoDocumentacionORM.IdDocumento
                            == DocumentacionORM.IdDocumento
                        ),
                    )
                    .filter(
                        (
                            RelacionTipoDocumentacionORM
                            .IdRegistroPersonal
                            == id_registro_personal
                        ),
                        (
                            DocumentacionORM
                            .IdTipoDocumentacion
                            == tipo_documentacion
                        ),
                    )
                )

                if id_vinculacion_laboral is not None:
                    query = query.filter(
                        (
                            RelacionTipoDocumentacionORM
                            .IdVinculacionLaboral
                            == id_vinculacion_laboral
                        )
                    )

                existe_relacion = query.first()

            if existe_relacion:
                documento_existente = (
                    db.query(DocumentacionORM)
                    .filter(
                        (
                            DocumentacionORM.IdDocumento
                            == existe_relacion.IdDocumento
                        )
                    )
                    .first()
                )

                if documento_existente:
                    documento_existente.DocumentoCargado = (
                        doc_data["DocumentoCargado"]
                    )

                    documento_existente.Formato = (
                        doc_data["Formato"]
                    )

                    documento_existente.Nombre = (
                        doc_data["Nombre"]
                    )

                    resultado.append(
                        documento_existente
                    )

                continue

            nuevo_documento = DocumentacionORM(
                IdTipoDocumentacion=tipo_documentacion,
                DocumentoCargado=doc_data[
                    "DocumentoCargado"
                ],
                Formato=doc_data["Formato"],
                Nombre=doc_data["Nombre"],
            )

            db.add(nuevo_documento)
            db.flush()

            nueva_relacion = RelacionTipoDocumentacionORM(
                IdRegistroPersonal=id_registro_personal,
                IdDocumento=nuevo_documento.IdDocumento,
                IdVinculacionLaboral=id_vinculacion_laboral,
            )

            db.add(nueva_relacion)
            resultado.append(nuevo_documento)

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

    except Exception as error:
        db.rollback()

        raise HTTPException(
            status_code=(
                status.HTTP_500_INTERNAL_SERVER_ERROR
            ),
            detail=(
                "Error al subir documentos: "
                f"{error}"
            ),
        ) from error


@router.delete(
    "/documento/{id_documento}",
    status_code=status.HTTP_200_OK,
)
def eliminar_documento_contratacion(
    id_documento: int,
    db: Session = Depends(get_db),
):
    """
    Elimina un documento individual de contratación.

    Esta eliminación individual solamente está permitida
    para los siguientes tipos:

    36 = Entrega de dotación
    64 = Otro sí
    """
    try:
        relacion = (
            db.query(
                RelacionTipoDocumentacionORM
            )
            .filter(
                (
                    RelacionTipoDocumentacionORM
                    .IdDocumento
                    == id_documento
                )
            )
            .first()
        )

        if not relacion:
            raise HTTPException(
                status_code=(
                    status.HTTP_404_NOT_FOUND
                ),
                detail=(
                    "El documento no existe o no tiene "
                    "una relación asociada."
                ),
            )

        documento = (
            db.query(DocumentacionORM)
            .filter(
                (
                    DocumentacionORM.IdDocumento
                    == id_documento
                )
            )
            .first()
        )

        if not documento:
            raise HTTPException(
                status_code=(
                    status.HTTP_404_NOT_FOUND
                ),
                detail="El documento no existe.",
            )

        tipo_documentacion = int(
            documento.IdTipoDocumentacion
        )

        if (
            tipo_documentacion
            not in TIPOS_DOCUMENTALES_MULTIPLES
        ):
            raise HTTPException(
                status_code=(
                    status.HTTP_400_BAD_REQUEST
                ),
                detail=(
                    "La eliminación individual solamente "
                    "está habilitada para Entrega de "
                    "dotación y Otro sí."
                ),
            )

        db.delete(relacion)
        db.flush()

        db.delete(documento)

        db.commit()

        return {
            "ok": True,
            "message": (
                "Documento eliminado correctamente."
            ),
            "IdDocumento": id_documento,
            "IdTipoDocumentacion": (
                tipo_documentacion
            ),
            "IdVinculacionLaboral": getattr(
                relacion,
                "IdVinculacionLaboral",
                None,
            ),
        }

    except HTTPException:
        db.rollback()
        raise

    except Exception as error:
        db.rollback()

        raise HTTPException(
            status_code=(
                status.HTTP_500_INTERNAL_SERVER_ERROR
            ),
            detail=(
                "Error al eliminar el documento "
                f"de contratación: {error}"
            ),
        ) from error