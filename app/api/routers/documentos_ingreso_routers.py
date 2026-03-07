import base64
import re
import unicodedata
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel
from sqlalchemy.orm import Session
from sqlalchemy import text

from infrastructure.db.deps import get_db

router = APIRouter(prefix="/api/documentos-ingreso", tags=["documentos-ingreso"])


# ─────────────────────────────────────────────
# 🔎 Utilidades para buscar por nombre (tolerante a tildes y variantes)
# ─────────────────────────────────────────────
def _norm(s: str) -> str:
    """
    Normaliza texto: minúsculas, sin tildes, sin símbolos raros, espacios simples.
    """
    if not s:
        return ""
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = s.lower().strip()
    s = re.sub(r"\s+", " ", s)
    return s


# ─────────────────────────────────────────────
# ✅ Schemas
# ─────────────────────────────────────────────
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


# ─────────────────────────────────────────────
# ✅ Ping rápido (para probar que el router cargó)
# ─────────────────────────────────────────────
@router.get("/ping")
def ping_docs_ingreso():
    return {"ok": True, "message": "pong documentos-ingreso"}


# ─────────────────────────────────────────────
# Helpers DB
# ─────────────────────────────────────────────
def _detectar_columna_nombre_tipo(db: Session) -> str:
    """
    Detecta la columna "nombre/descripcion" dentro de TipoDocumentacion.
    """
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
    """
    Trae todos los tipos con su nombre para hacer matching local (más tolerante).
    """
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


def _encontrar_tipo_id_por_aliases(tipos: List[Dict[str, Any]], aliases: List[str]) -> Optional[int]:
    """
    Busca el IdTipoDocumentacion por coincidencia tolerante (contiene alias).
    """
    aliases_norm = [_norm(a) for a in aliases if a]

    # 1) match por "contiene"
    for a in aliases_norm:
        for t in tipos:
            if a and a in t["nombre_norm"]:
                return t["id_tipo"]

    # 2) match al revés (cuando el alias es más grande)
    for a in aliases_norm:
        for t in tipos:
            if t["nombre_norm"] and t["nombre_norm"] in a:
                return t["id_tipo"]

    return None

# ─────────────────────────────────────────────
# ✅ GET documento (bytea) a base64 para descargar/ver
# ─────────────────────────────────────────────
from typing import List

@router.get("/aspirante/{id_registro_personal}/categoria/{id_categoria}", response_model=List[DocIngresoDetalle])
def obtener_documento_ingreso(
    id_registro_personal: int,
    id_categoria: int,
    db: Session = Depends(get_db),
):
    rows = db.execute(
        text("""
            SELECT T."IdTipoDocumentacion", d."IdDocumento", d."DocumentoCargado", d."Nombre", d."Formato", T."Descripcion"
            FROM "Documentos" d
            JOIN "RelacionTipoDocumentacion" r ON r."IdDocumento" = d."IdDocumento"
            JOIN "TipoDocumentacion" T ON T."IdTipoDocumentacion" = d."IdTipoDocumentacion"
            WHERE r."IdRegistroPersonal" = :id
              AND T."IdCategoria" = :id_categoria
            ORDER BY d."IdDocumento" ASC
        """),
        {"id": id_registro_personal, "id_categoria": id_categoria},
    ).fetchall()

    if not rows:
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    documentos = []
    for row in rows:
        id_tipo_doc = int(row[0])
        id_doc = int(row[1])
        raw = row[2]
        nombre = row[3] or ""
        formato = row[4] or ""
        descripcion = row[5] or ""
        if raw is None:
            continue
        doc_b64 = base64.b64encode(raw).decode("utf-8")
        documentos.append(DocIngresoDetalle(
            IdTipoDocumentacion=id_tipo_doc,
            IdDocumento=id_doc,
            DocumentoBase64=doc_b64,
            Nombre=nombre,
            Formato=formato,
            Descripcion=descripcion,
        ))

    if not documentos:
        return Response(status_code=status.HTTP_204_NO_CONTENT, detail="No hay documentos válidos para ese tipo")

    return documentos