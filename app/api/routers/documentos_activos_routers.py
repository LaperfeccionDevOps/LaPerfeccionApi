import base64
import re
from typing import List

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session
from sqlalchemy import text

from infrastructure.db.deps import get_db

router = APIRouter(
    prefix="/api/documentos-activos",
    tags=["documentos-activos"],
)

TIPOS_ACTIVOS = [
    77, 78, 79, 80, 81, 82, 83, 84,
    85, 86, 87, 90, 91, 92, 93, 60
]


class DocumentoActivoUpload(BaseModel):
    IdTipoDocumentacion: int
    Nombre: str
    Formato: str
    DocumentoCargado: str


class RegistrarDocumentosActivosSchema(BaseModel):
    idRegistroPersonal: int
    documentos: List[DocumentoActivoUpload]


def limpiar_base64(base64_str: str) -> str:
    if isinstance(base64_str, bytes):
        base64_str = base64_str.decode("utf-8")

    match = re.match(r"^data:.*?;base64,(.*)", base64_str)
    if match:
        return match.group(1)

    return base64_str


@router.get("/registro/{id_registro_personal}")
def listar_documentos_activos(
    id_registro_personal: int,
    db: Session = Depends(get_db),
):
    rows = db.execute(
        text("""
            SELECT
                td."IdTipoDocumentacion",
                td."Descripcion" AS tipo_documento,
                d."IdDocumento",
                d."Nombre",
                d."Formato"
            FROM public."TipoDocumentacion" td
            LEFT JOIN public."RelacionTipoDocumentacion" rtd
                ON rtd."IdRegistroPersonal" = :id_registro_personal
            LEFT JOIN public."Documentos" d
                ON d."IdDocumento" = rtd."IdDocumento"
               AND d."IdTipoDocumentacion" = td."IdTipoDocumentacion"
            WHERE td."IdTipoDocumentacion" = ANY(:tipos_activos)
            ORDER BY
                array_position(:tipos_activos, td."IdTipoDocumentacion"),
                d."IdDocumento" DESC
        """),
        {
            "id_registro_personal": id_registro_personal,
            "tipos_activos": TIPOS_ACTIVOS,
        },
    ).mappings().all()

    agrupado = {}

    for row in rows:
        id_tipo = row["IdTipoDocumentacion"]

        if id_tipo not in agrupado:
            agrupado[id_tipo] = {
                "IdTipoDocumentacion": id_tipo,
                "tipo_documento": "Certificaciones" if id_tipo == 60 else row["tipo_documento"],
                "documentos": [],
            }

        if row["IdDocumento"]:
            agrupado[id_tipo]["documentos"].append({
                "IdDocumento": row["IdDocumento"],
                "Nombre": row["Nombre"],
                "Formato": row["Formato"],
            })

    return list(agrupado.values())


@router.post("/upload", status_code=status.HTTP_201_CREATED)
def subir_documentos_activos(
    payload: RegistrarDocumentosActivosSchema,
    db: Session = Depends(get_db),
):
    try:
        resultado = []

        for doc in payload.documentos:
            if doc.IdTipoDocumentacion not in TIPOS_ACTIVOS:
                raise HTTPException(
                    status_code=400,
                    detail=f"El tipo {doc.IdTipoDocumentacion} no pertenece a carpeta Activos.",
                )

            documento_binario = base64.b64decode(
                limpiar_base64(doc.DocumentoCargado)
            )

            nuevo_doc = db.execute(
                text("""
                    INSERT INTO public."Documentos"
                    (
                        "IdTipoDocumentacion",
                        "DocumentoCargado",
                        "Formato",
                        "Nombre",
                        "FechaCreacion",
                        "FechaActualizacion"
                    )
                    VALUES
                    (
                        :id_tipo,
                        :documento,
                        :formato,
                        :nombre,
                        NOW(),
                        NOW()
                    )
                    RETURNING "IdDocumento"
                """),
                {
                    "id_tipo": doc.IdTipoDocumentacion,
                    "documento": documento_binario,
                    "formato": doc.Formato,
                    "nombre": doc.Nombre,
                },
            ).mappings().first()

            id_documento = nuevo_doc["IdDocumento"]

            db.execute(
                text("""
                    INSERT INTO public."RelacionTipoDocumentacion"
                    (
                        "IdRegistroPersonal",
                        "IdDocumento"
                    )
                    VALUES
                    (
                        :id_registro_personal,
                        :id_documento
                    )
                """),
                {
                    "id_registro_personal": payload.idRegistroPersonal,
                    "id_documento": id_documento,
                },
            )

            resultado.append({
                "IdDocumento": id_documento,
                "Nombre": doc.Nombre,
            })

        db.commit()

        return {"ok": True, "documentos": resultado}

    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=500,
            detail=f"Error al subir documentos activos: {str(e)}",
        )


@router.get("/documento/{id_documento}")
def obtener_documento_activo(
    id_documento: int,
    db: Session = Depends(get_db),
):
    row = db.execute(
        text("""
            SELECT
                d."IdDocumento",
                d."IdTipoDocumentacion",
                d."DocumentoCargado",
                d."Nombre",
                d."Formato"
            FROM public."Documentos" d
            WHERE d."IdDocumento" = :id_documento
              AND d."IdTipoDocumentacion" = ANY(:tipos_activos)
        """),
        {
            "id_documento": id_documento,
            "tipos_activos": TIPOS_ACTIVOS,
        },
    ).mappings().first()

    if not row:
        raise HTTPException(status_code=404, detail="Documento activo no encontrado.")

    return {
        "IdDocumento": row["IdDocumento"],
        "IdTipoDocumentacion": row["IdTipoDocumentacion"],
        "Nombre": row["Nombre"],
        "Formato": row["Formato"],
        "DocumentoBase64": base64.b64encode(row["DocumentoCargado"]).decode("utf-8"),
    }


@router.delete("/documento/{id_documento}")
def eliminar_documento_activo(
    id_documento: int,
    db: Session = Depends(get_db),
):
    try:
        row = db.execute(
            text("""
                SELECT "IdDocumento"
                FROM public."Documentos"
                WHERE "IdDocumento" = :id_documento
                  AND "IdTipoDocumentacion" = ANY(:tipos_activos)
            """),
            {
                "id_documento": id_documento,
                "tipos_activos": TIPOS_ACTIVOS,
            },
        ).mappings().first()

        if not row:
            raise HTTPException(status_code=404, detail="Documento activo no encontrado.")

        db.execute(
            text("""
                DELETE FROM public."RelacionTipoDocumentacion"
                WHERE "IdDocumento" = :id_documento
            """),
            {"id_documento": id_documento},
        )

        db.execute(
            text("""
                DELETE FROM public."Documentos"
                WHERE "IdDocumento" = :id_documento
            """),
            {"id_documento": id_documento},
        )

        db.commit()

        return {"ok": True, "detail": "Documento activo eliminado correctamente."}

    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=500,
            detail=f"Error al eliminar documento activo: {str(e)}",
        )