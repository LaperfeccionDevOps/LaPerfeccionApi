from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from sqlalchemy import text
from io import BytesIO

from infrastructure.db.deps import get_db

router = APIRouter(
    prefix="/api/documentos-activos",
    tags=["documentos-activos"]
)


@router.get("/ping")
def ping_documentos_activos():
    return {"ok": True, "message": "pong documentos-activos"}


@router.get("/tipos")
def listar_tipos_documentos_activos(db: Session = Depends(get_db)):
    rows = db.execute(text("""
        SELECT "IdTipoDocumentacion", "Descripcion"
        FROM public."TipoDocumentacion"
        WHERE "IdCategoria" = 2
          AND "Estado" = true
        ORDER BY "IdTipoDocumentacion";
    """)).mappings().all()

    return [
        {
            "IdTipoDocumentacion": r["IdTipoDocumentacion"],
            "Descripcion": r["Descripcion"]
        }
        for r in rows
    ]


@router.get("/aspirante/{id_registro_personal}")
def listar_documentos_activos_por_trabajador(
    id_registro_personal: int,
    db: Session = Depends(get_db)
):
    rows = db.execute(
        text("""
            SELECT
                T."IdTipoDocumentacion",
                T."Descripcion",
                D."IdDocumento",
                D."Nombre",
                D."Formato",
                D."FechaCreacion"
            FROM public."TipoDocumentacion" T
            LEFT JOIN public."Documentos" D
                ON D."IdTipoDocumentacion" = T."IdTipoDocumentacion"
            LEFT JOIN public."RelacionTipoDocumentacion" R
                ON R."IdDocumento" = D."IdDocumento"
               AND R."IdRegistroPersonal" = :id_registro_personal
            WHERE T."IdCategoria" = 2
              AND T."Estado" = true
              AND (
                    D."IdDocumento" IS NULL
                    OR R."IdRegistroPersonal" = :id_registro_personal
                  )
            ORDER BY
                T."IdTipoDocumentacion",
                D."FechaCreacion" DESC,
                D."IdDocumento" DESC
        """),
        {"id_registro_personal": id_registro_personal}
    ).mappings().all()

    resultado = {}

    for row in rows:
        id_tipo = row["IdTipoDocumentacion"]

        if id_tipo not in resultado:
            resultado[id_tipo] = {
                "IdTipoDocumentacion": id_tipo,
                "Descripcion": row["Descripcion"],
                "documentos": []
            }

        if row["IdDocumento"]:
            resultado[id_tipo]["documentos"].append({
                "IdDocumento": row["IdDocumento"],
                "Nombre": row["Nombre"],
                "Formato": row["Formato"],
                "FechaCreacion": row["FechaCreacion"]
            })

    return list(resultado.values())


@router.post("/aspirante/{id_registro_personal}/subir")
async def subir_documento_activo(
    id_registro_personal: int,
    id_tipo_documentacion: int = Form(...),
    archivo: UploadFile = File(...),
    db: Session = Depends(get_db)
):
    contenido = await archivo.read()

    if not contenido:
        raise HTTPException(status_code=400, detail="El archivo está vacío")

    existe_tipo = db.execute(
        text("""
            SELECT 1
            FROM public."TipoDocumentacion"
            WHERE "IdTipoDocumentacion" = :id_tipo
              AND "IdCategoria" = 2
              AND "Estado" = true
        """),
        {"id_tipo": id_tipo_documentacion}
    ).first()

    if not existe_tipo:
        raise HTTPException(status_code=404, detail="Tipo documental activo no válido")

    formato = archivo.filename.split(".")[-1].lower() if "." in archivo.filename else "pdf"

    row_doc = db.execute(
        text("""
            INSERT INTO public."Documentos"
            ("IdTipoDocumentacion", "DocumentoCargado", "Formato", "Nombre", "FechaCreacion", "FechaActualizacion")
            VALUES
            (:id_tipo, :contenido, :formato, :nombre, NOW(), NOW())
            RETURNING "IdDocumento"
        """),
        {
            "id_tipo": id_tipo_documentacion,
            "contenido": contenido,
            "formato": formato,
            "nombre": archivo.filename
        }
    ).mappings().first()

    id_documento = row_doc["IdDocumento"]

    db.execute(
        text("""
            INSERT INTO public."RelacionTipoDocumentacion"
            ("IdDocumento", "IdRegistroPersonal")
            VALUES
            (:id_documento, :id_registro_personal)
        """),
        {
            "id_documento": id_documento,
            "id_registro_personal": id_registro_personal
        }
    )

    db.commit()

    return {
        "ok": True,
        "message": "Documento activo cargado correctamente",
        "IdDocumento": id_documento
    }


@router.get("/documento/{id_documento}/descargar")
def descargar_documento_activo(
    id_documento: int,
    inline: bool = False,
    db: Session = Depends(get_db)
):
    row = db.execute(
        text("""
            SELECT
                D."DocumentoCargado",
                COALESCE(D."Nombre", 'documento.pdf') AS nombre,
                COALESCE(D."Formato", 'pdf') AS formato
            FROM public."Documentos" D
            JOIN public."TipoDocumentacion" T
                ON T."IdTipoDocumentacion" = D."IdTipoDocumentacion"
            WHERE D."IdDocumento" = :id_documento
              AND T."IdCategoria" = 2
        """),
        {"id_documento": id_documento}
    ).mappings().first()

    if not row or row["DocumentoCargado"] is None:
        raise HTTPException(status_code=404, detail="Documento activo no encontrado")

    contenido = bytes(row["DocumentoCargado"])
    nombre = row["nombre"] or "documento.pdf"
    formato = (row["formato"] or "pdf").lower()

    media_type = "application/pdf" if formato in ("pdf", "application/pdf") else "application/octet-stream"

    return StreamingResponse(
        BytesIO(contenido),
        media_type=media_type,
        headers={
            "Content-Disposition": f'{"inline" if inline else "attachment"}; filename="{nombre}"'
        }
    )

@router.delete("/documento/{id_documento}")
def eliminar_documento_activo(
    id_documento: int,
    db: Session = Depends(get_db)
):
    existe = db.execute(
        text("""
            SELECT 1
            FROM public."Documentos" D
            JOIN public."TipoDocumentacion" T
                ON T."IdTipoDocumentacion" = D."IdTipoDocumentacion"
            WHERE D."IdDocumento" = :id_documento
              AND T."IdCategoria" = 2
        """),
        {"id_documento": id_documento}
    ).first()

    if not existe:
        raise HTTPException(status_code=404, detail="Documento activo no encontrado")

    db.execute(
        text("""
            DELETE FROM public."RelacionTipoDocumentacion"
            WHERE "IdDocumento" = :id_documento
        """),
        {"id_documento": id_documento}
    )

    db.execute(
        text("""
            DELETE FROM public."Documentos"
            WHERE "IdDocumento" = :id_documento
        """),
        {"id_documento": id_documento}
    )

    db.commit()

    return {
        "ok": True,
        "message": "Documento activo eliminado correctamente",
        "IdDocumento": id_documento
    }