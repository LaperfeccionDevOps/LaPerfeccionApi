import os
import uuid
from pathlib import Path
from typing import List
from uuid import UUID as UUIDType

from fastapi import APIRouter, Depends, UploadFile, status, File, Form, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from infrastructure.db.deps import get_db
from domain.models.documento_seguridad import DocumentoSeguridad
from domain.schemas.documento_seguridad_schemas import DocumentoSeguridadOut
from domain.schemas.aspirante import RegistrarDocumentosContratacionSchema, RegistroPersonalOut
from domain.schemas.aspirante import DocumentacionSchema
from domain.models.aspirante import RelacionTipoDocumentacionORM, DocumentacionORM
import base64
import re

router = APIRouter(
    prefix="/documentos-contratacion",
    tags=["documentos contratacion"],
)

def limpiar_base64(base64_str: str) -> str:
    """
    Elimina el prefijo data:*;base64, si existe. Acepta bytes o string.
    """
    if isinstance(base64_str, bytes):
        base64_str = base64_str.decode('utf-8')
    match = re.match(r"^data:.*?;base64,(.*)", base64_str)
    if match:
        return match.group(1)
    return base64_str

@router.post("/upload", status_code=status.HTTP_201_CREATED)
async def subir_documento_contratacion(
    payload: RegistrarDocumentosContratacionSchema,
    db: Session = Depends(get_db),
):
    try:
        idRegistroPersonal = payload.idRegistroPersonal
        resultado = []
        for doc in payload.documentos_contratacion:
            doc_data = doc.dict()
            # Buscar si ya existe documento con ese tipo y registro personal
            existe_relacion = db.query(RelacionTipoDocumentacionORM).join(
                DocumentacionORM, RelacionTipoDocumentacionORM.IdDocumento == DocumentacionORM.IdDocumento
            ).filter(
                RelacionTipoDocumentacionORM.IdRegistroPersonal == idRegistroPersonal,
                DocumentacionORM.IdTipoDocumentacion == doc_data["IdTipoDocumentacion"]
            ).first()
            base64_str = doc_data.get("DocumentoCargado")
            if base64_str:
                try:
                    base64_str = limpiar_base64(base64_str)
                    doc_data["DocumentoCargado"] = base64.b64decode(base64_str)
                except Exception as e:
                    print(f"Error al procesar DocumentoCargado: {e}")
                    doc_data["DocumentoCargado"] = None
            if existe_relacion:
                # Actualizar el documento existente
                documento_existente = db.query(DocumentacionORM).filter(
                    DocumentacionORM.IdDocumento == existe_relacion.IdDocumento
                ).first()
                if documento_existente:
                    documento_existente.DocumentoCargado = doc_data["DocumentoCargado"]
                    documento_existente.Formato = doc_data["Formato"]
                    documento_existente.Nombre = doc_data["Nombre"]
                    resultado.append(documento_existente)
                continue
            # Si no existe, crear nuevo documento y relación
            nuevo_doc = DocumentacionORM(
                IdTipoDocumentacion=doc_data["IdTipoDocumentacion"],
                DocumentoCargado=doc_data["DocumentoCargado"],
                Formato=doc_data["Formato"],
                Nombre=doc_data["Nombre"],
            )
            db.add(nuevo_doc)
            db.flush()
            relacion = RelacionTipoDocumentacionORM(
                IdRegistroPersonal=idRegistroPersonal,
                IdDocumento=nuevo_doc.IdDocumento
            )
            db.add(relacion)
            resultado.append(nuevo_doc)
        db.commit()
        for d in resultado:
            db.refresh(d)
        return {"ok": True, "nombres": [d.Nombre for d in resultado]}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error al subir documentos: {str(e)}")