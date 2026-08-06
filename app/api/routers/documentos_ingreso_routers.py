import base64
import re
import unicodedata
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.orm import Session

from infrastructure.db.deps import get_db


router = APIRouter(
    prefix="/api/documentos-ingreso",
    tags=["documentos-ingreso"],
)


# Tipos documentales que permiten conservar y consultar
# varios archivos para un mismo trabajador.
TIPOS_DOCUMENTALES_MULTIPLES = (36, 64)


def _norm(s: str) -> str:
    if not s:
        return ""

    s = unicodedata.normalize("NFKD", s)

    s = "".join(
        caracter
        for caracter in s
        if not unicodedata.combining(caracter)
    )

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
    return {
        "ok": True,
        "message": "pong documentos-ingreso",
    }


def _detectar_columna_nombre_tipo(db: Session) -> str:
    cols = db.execute(
        text(
            """
            SELECT
                column_name
            FROM information_schema.columns
            WHERE table_schema = 'public'
              AND table_name = 'TipoDocumentacion'
            """
        )
    ).scalars().all()

    candidatos = [
        "Nombre",
        "Descripcion",
        "DescripcionTipo",
        "Tipo",
        "NombreTipo",
    ]

    for columna in candidatos:
        if columna in cols:
            return f'"{columna}"'

    raise HTTPException(
        status_code=500,
        detail=(
            "No pude detectar columna de nombre en "
            f"TipoDocumentacion. Columnas: {cols}"
        ),
    )


def _cargar_tipos_documentacion(
    db: Session,
    col_nombre: str,
) -> List[Dict[str, Any]]:
    rows = db.execute(
        text(
            f"""
            SELECT
                "IdTipoDocumentacion" AS id_tipo,
                {col_nombre} AS nombre
            FROM "TipoDocumentacion"
            """
        )
    ).mappings().all()

    salida: List[Dict[str, Any]] = []

    for row in rows:
        salida.append(
            {
                "id_tipo": int(row["id_tipo"]),
                "nombre": row["nombre"] or "",
                "nombre_norm": _norm(
                    str(row["nombre"] or "")
                ),
            }
        )

    return salida


def _encontrar_tipo_id_por_aliases(
    tipos: List[Dict[str, Any]],
    aliases: List[str],
) -> Optional[int]:
    aliases_norm = [
        _norm(alias)
        for alias in aliases
        if alias
    ]

    for alias in aliases_norm:
        for tipo in tipos:
            if alias and alias in tipo["nombre_norm"]:
                return tipo["id_tipo"]

    for alias in aliases_norm:
        for tipo in tipos:
            if (
                tipo["nombre_norm"]
                and tipo["nombre_norm"] in alias
            ):
                return tipo["id_tipo"]

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
        text(
            """
            SELECT
                resultado."IdTipoDocumentacion",
                resultado."IdDocumento",
                resultado."DocumentoCargado",
                resultado."Nombre",
                resultado."Formato",
                resultado."Descripcion"
            FROM (
                /*
                 * Documentos normales:
                 * devuelve solamente el documento más reciente
                 * para cada tipo documental.
                 */
                SELECT
                    documentos_normales."IdTipoDocumentacion",
                    documentos_normales."IdDocumento",
                    documentos_normales."DocumentoCargado",
                    documentos_normales."Nombre",
                    documentos_normales."Formato",
                    documentos_normales."Descripcion"
                FROM (
                    SELECT DISTINCT ON (
                        T."IdTipoDocumentacion"
                    )
                        T."IdTipoDocumentacion",
                        d."IdDocumento",
                        d."DocumentoCargado",
                        d."Nombre",
                        d."Formato",
                        T."Descripcion"
                    FROM "Documentos" d
                    INNER JOIN "RelacionTipoDocumentacion" r
                        ON r."IdDocumento" = d."IdDocumento"
                    INNER JOIN "TipoDocumentacion" T
                        ON T."IdTipoDocumentacion"
                        = d."IdTipoDocumentacion"
                    WHERE
                        r."IdRegistroPersonal" = :id
                        AND T."IdTipoDocumentacion"
                            NOT IN (36, 64)
                        AND (
                            T."IdCategoria" = :id_categoria
                            OR (
                                :id_categoria = 6
                                AND T."IdCategoria" = 7
                                AND T."IdTipoDocumentacion"
                                    IN (32, 76)
                            )
                        )
                    ORDER BY
                        T."IdTipoDocumentacion" ASC,
                        d."IdDocumento" DESC
                ) AS documentos_normales

                UNION ALL

                /*
                 * Documentos múltiples:
                 * 36 = Entrega de dotación
                 * 64 = Otro sí
                 *
                 * Para estos tipos se devuelven todos los documentos
                 * asociados al trabajador.
                 */
                SELECT
                    T."IdTipoDocumentacion",
                    d."IdDocumento",
                    d."DocumentoCargado",
                    d."Nombre",
                    d."Formato",
                    T."Descripcion"
                FROM "Documentos" d
                INNER JOIN "RelacionTipoDocumentacion" r
                    ON r."IdDocumento" = d."IdDocumento"
                INNER JOIN "TipoDocumentacion" T
                    ON T."IdTipoDocumentacion"
                    = d."IdTipoDocumentacion"
                WHERE
                    r."IdRegistroPersonal" = :id
                    AND T."IdTipoDocumentacion"
                        IN (36, 64)
                    AND (
                        T."IdCategoria" = :id_categoria
                        OR (
                            :id_categoria = 6
                            AND T."IdCategoria" = 7
                            AND T."IdTipoDocumentacion"
                                IN (32, 76)
                        )
                    )
            ) AS resultado
            ORDER BY
                resultado."IdTipoDocumentacion" ASC,
                resultado."IdDocumento" ASC
            """
        ),
        {
            "id": id_registro_personal,
            "id_categoria": id_categoria,
        },
    ).fetchall()

    documentos: List[DocIngresoDetalle] = []

    for row in rows:
        documento_cargado = row[2]

        if documento_cargado is None:
            continue

        documentos.append(
            DocIngresoDetalle(
                IdTipoDocumentacion=int(row[0]),
                IdDocumento=int(row[1]),
                DocumentoBase64=base64.b64encode(
                    documento_cargado
                ).decode("utf-8"),
                Nombre=row[3] or "",
                Formato=row[4] or "",
                Descripcion=row[5] or "",
            )
        )

    return documentos