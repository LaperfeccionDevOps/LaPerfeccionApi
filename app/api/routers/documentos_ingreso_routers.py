import base64
import re
import unicodedata
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session
from sqlalchemy import text

from infrastructure.db.deps import get_db

router = APIRouter(prefix="/api/documentos-ingreso", tags=["documentos-ingreso"])


def _norm(s: str) -> str:
    if not s:
        return ""
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = s.lower().strip()
    s = re.sub(r"\s+", " ", s)
    return s


class DocIngresoListItem(BaseModel):
    key: str
    label: str
    IdTipoDocumentacion: Optional[int] = None
    adjuntado: bool
    IdDocumento: Optional[int] = None


class DocIngresoDetalle(BaseModel):
    IdTipoDocumentacion: int
    IdDocumento: int
    DocumentoBase64: str
    Nombre: str
    Formato: str
    Descripcion: str


@router.get("/ping")
def ping_docs_ingreso():
    return {"ok": True, "message": "pong documentos-ingreso"}


def _detectar_columna_nombre_tipo(db: Session) -> str:
    cols = db.execute(
        text("""
            SELECT column_name
            FROM information_schema.columns
            WHERE table_schema='public'
              AND table_name='TipoDocumentacion'
        """)
    ).scalars().all()

    candidatos = ["Nombre", "Descripcion", "DescripcionTipo", "Tipo", "NombreTipo"]
    for c in candidatos:
        if c in cols:
            return f'"{c}"'

    raise HTTPException(
        status_code=500,
        detail=f"No pude detectar columna de nombre en TipoDocumentacion. Columnas: {cols}",
    )


def _cargar_tipos_documentacion(db: Session, col_nombre: str) -> List[Dict[str, Any]]:
    rows = db.execute(
        text(f"""
            SELECT "IdTipoDocumentacion" AS id_tipo,
                   {col_nombre} AS nombre
            FROM "TipoDocumentacion"
        """)
    ).mappings().all()

    salida = []
    for r in rows:
        salida.append({
            "id_tipo": int(r["id_tipo"]),
            "nombre": r["nombre"] or "",
            "nombre_norm": _norm(str(r["nombre"] or "")),
        })
    return salida


def _encontrar_tipo_id_por_aliases(
    tipos: List[Dict[str, Any]],
    aliases: List[str],
) -> Optional[int]:
    aliases_norm = [_norm(a) for a in aliases if a]

    for a in aliases_norm:
        for t in tipos:
            if a and a in t["nombre_norm"]:
                return t["id_tipo"]

    for a in aliases_norm:
        for t in tipos:
            if t["nombre_norm"] and t["nombre_norm"] in a:
                return t["id_tipo"]

    return None


@router.get(
    "/aspirante/{id_registro_personal}/categoria/{id_categoria}",
    response_model=List[DocIngresoDetalle],
)
def obtener_documento_ingreso(
    id_registro_personal: int,
    id_categoria: int,
    db: Session = Depends(get_db),
):
    rows = db.execute(
        text("""
            SELECT DISTINCT ON (T."IdTipoDocumentacion")
                T."IdTipoDocumentacion",
                d."IdDocumento",
                d."DocumentoCargado",
                d."Nombre",
                d."Formato",
                T."Descripcion"
            FROM "Documentos" d
            JOIN "RelacionTipoDocumentacion" r
                ON r."IdDocumento" = d."IdDocumento"
            JOIN "TipoDocumentacion" T
                ON T."IdTipoDocumentacion" = d."IdTipoDocumentacion"
            WHERE r."IdRegistroPersonal" = :id
              AND (
                    T."IdCategoria" = :id_categoria
                    OR (
                        :id_categoria = 6
                        AND T."IdCategoria" = 7
                        AND T."IdTipoDocumentacion" IN (32, 76)
                    )
              )
            ORDER BY T."IdTipoDocumentacion", d."IdDocumento" DESC
        """),
        {"id": id_registro_personal, "id_categoria": id_categoria},
    ).fetchall()

    documentos: List[DocIngresoDetalle] = []

    for row in rows:
        raw = row[2]

        if raw is None:
            continue

        documentos.append(
            DocIngresoDetalle(
                IdTipoDocumentacion=int(row[0]),
                IdDocumento=int(row[1]),
                DocumentoBase64=base64.b64encode(raw).decode("utf-8"),
                Nombre=row[3] or "",
                Formato=row[4] or "",
                Descripcion=row[5] or "",
            )
        )

    return documentos