import base64
import re

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    status,
)
from sqlalchemy.orm import Session

from infrastructure.db.deps import get_db
from domain.schemas.aspirante import (
    RegistrarDocumentosContratacionSchema,
)
from domain.models.aspirante import (
    DocumentacionORM,
    RelacionTipoDocumentacionORM,
)


router = APIRouter(
    prefix="/documentos-contratacion",
    tags=["documentos contratacion"],
)


# Solamente estos tipos permiten conservar varios documentos
# para el mismo trabajador.
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

    Para los tipos documentales 36 y 64 se conserva cada carga
    como un documento independiente.

    Para los demás tipos se mantiene el comportamiento anterior:
    si ya existe un documento del mismo tipo para el trabajador,
    se actualiza.
    """
    try:
        id_registro_personal = payload.idRegistroPersonal
        resultado = []

        for doc in payload.documentos_contratacion:
            doc_data = doc.dict()

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
                        "Error al procesar "
                        f"DocumentoCargado: {error_base64}"
                    )

                    doc_data["DocumentoCargado"] = None

            existe_relacion = None

            # Para los tipos normales se conserva el comportamiento
            # actual: si el documento ya existe, se actualiza.
            #
            # Para Entrega de dotación y Otro sí no se busca un
            # documento anterior, porque cada carga debe crear un
            # registro nuevo.
            if not permite_multiples:
                existe_relacion = (
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
                    .first()
                )

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

            # Para los tipos 36 y 64 siempre entra aquí
            # y crea un documento nuevo sin reemplazar
            # los documentos anteriores.
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

            nueva_relacion = (
                RelacionTipoDocumentacionORM(
                    IdRegistroPersonal=(
                        id_registro_personal
                    ),
                    IdDocumento=(
                        nuevo_documento.IdDocumento
                    ),
                )
            )

            db.add(nueva_relacion)
            resultado.append(nuevo_documento)

        db.commit()

        for documento in resultado:
            db.refresh(documento)

        return {
            "ok": True,
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
                f"{str(error)}"
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

        # Primero se elimina la relación porque contiene
        # la llave foránea hacia la tabla Documentos.
        db.delete(relacion)
        db.flush()

        # Después se elimina únicamente el documento
        # seleccionado mediante su IdDocumento.
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
                f"de contratación: {str(error)}"
            ),
        ) from error