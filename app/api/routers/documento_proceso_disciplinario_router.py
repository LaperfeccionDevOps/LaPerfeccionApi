from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from infrastructure.db.deps import get_db
from domain.models.documento_proceso_disciplinario import DocumentoProcesoDisciplinario
from domain.schemas.documento_proceso_disciplinario_schema import (
    DocumentoProcesoDisciplinarioCreate,
    DocumentoProcesoDisciplinarioUpdate,
    DocumentoProcesoDisciplinarioResponse,
)

router = APIRouter(
    prefix="/api/documento-proceso-disciplinario",
    tags=["Documento Proceso Disciplinario"],
)


@router.post("/", response_model=DocumentoProcesoDisciplinarioResponse)
def crear_documento(
    data: DocumentoProcesoDisciplinarioCreate,
    db: Session = Depends(get_db),
):
    nuevo = DocumentoProcesoDisciplinario(**data.model_dump())

    db.add(nuevo)
    db.commit()
    db.refresh(nuevo)

    return nuevo


@router.get("/{id_documento}", response_model=DocumentoProcesoDisciplinarioResponse)
def obtener_documento(
    id_documento: int,
    db: Session = Depends(get_db),
):
    documento = (
        db.query(DocumentoProcesoDisciplinario)
        .filter(
            DocumentoProcesoDisciplinario.IdDocumentoProcesoDisciplinario
            == id_documento
        )
        .first()
    )

    if not documento:
        raise HTTPException(status_code=404, detail="Documento no encontrado")

    return documento


@router.get("/proceso/{id_proceso}")
def obtener_documentos_por_proceso(
    id_proceso: int,
    db: Session = Depends(get_db),
):
    return (
        db.query(DocumentoProcesoDisciplinario)
        .filter(
            DocumentoProcesoDisciplinario.IdProcesoDisciplinario == id_proceso
        )
        .all()
    )


@router.put("/{id_documento}", response_model=DocumentoProcesoDisciplinarioResponse)
def actualizar_documento(
    id_documento: int,
    data: DocumentoProcesoDisciplinarioUpdate,
    db: Session = Depends(get_db),
):
    documento = (
        db.query(DocumentoProcesoDisciplinario)
        .filter(
            DocumentoProcesoDisciplinario.IdDocumentoProcesoDisciplinario
            == id_documento
        )
        .first()
    )

    if not documento:
        raise HTTPException(status_code=404, detail="Documento no encontrado")

    for campo, valor in data.model_dump(exclude_unset=True).items():
        setattr(documento, campo, valor)

    documento.FechaActualizacion = datetime.now()

    db.commit()
    db.refresh(documento)

    return documento