import base64
import re
import unicodedata
from typing import Any

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
    IdTipoDocumentacion: int | None = None
    adjuntado: bool
    IdDocumento: int | None = None


class DocIngresoDetalle(BaseModel):
    IdTipoDocumentacion: int
    IdDocumento: int
    DocumentoBase64: str
    Nombre: str
    Formato: str
    Descripcion: str


class DocIngresoDetalleCiclo(DocIngresoDetalle):
    IdRegistroPersonal: int
    IdVinculacionLaboral: int | None = None
    NumeroCiclo: int | None = None
    TipoVinculacion: str | None = None
    EstadoVinculacion: str | None = None
    EsHistoricoLegacy: bool = False


class DocumentosIngresoCicloResumen(BaseModel):
    IdVinculacionLaboral: int | None = None
    NumeroCiclo: int | None = None
    TipoVinculacion: str | None = None
    EstadoVinculacion: str | None = None
    EsHistoricoLegacy: bool = False
    SoloConsulta: bool
    documentos: list[DocIngresoDetalleCiclo]


class DocumentosIngresoPorCiclosResponse(BaseModel):
    ok: bool
    soloConsulta: bool
    IdRegistroPersonal: int
    IdVinculacionActual: int | None = None
    cicloActual: DocumentosIngresoCicloResumen | None = None
    historico: list[DocumentosIngresoCicloResumen]


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
) -> list[dict[str, Any]]:
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

    salida: list[dict[str, Any]] = []

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
    tipos: list[dict[str, Any]],
    aliases: list[str],
) -> int | None:
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


def _categoria_documental_sql() -> str:
    return """
        (
            T."IdCategoria" = :id_categoria
            OR (
                :id_categoria = 6
                AND T."IdCategoria" = 7
                AND T."IdTipoDocumentacion" IN (32, 76)
            )
        )
    """


def _consultar_documentos_ingreso(
    db: Session,
    id_registro_personal: int,
    id_categoria: int,
    id_vinculacion_laboral: int | None = None,
    filtrar_vinculacion: bool = False,
    incluir_legacy: bool = False,
):
    """
    Consulta base reutilizable.

    IMPORTANTE:
    - Si filtrar_vinculacion=False conserva exactamente el comportamiento
      histórico del endpoint legado: consulta solo por IdRegistroPersonal.
    - Si filtrar_vinculacion=True exige coincidencia con
      IdVinculacionLaboral y permite aislar un ciclo laboral.
    - incluir_legacy=True se usa únicamente para el primer ciclo histórico:
      incorpora relaciones antiguas con IdVinculacionLaboral NULL.
    - El ciclo actual nunca incluye documentos legacy.
    - No inserta, no actualiza y no elimina documentos.
    """

    filtro_vinculacion = ""

    if filtrar_vinculacion:
        if incluir_legacy:
            filtro_vinculacion = """
                AND (
                    r."IdVinculacionLaboral" = :id_vinculacion_laboral
                    OR r."IdVinculacionLaboral" IS NULL
                )
            """
        else:
            filtro_vinculacion = """
                AND r."IdVinculacionLaboral" = :id_vinculacion_laboral
            """

    sql = f"""
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
             * para cada tipo documental dentro del alcance solicitado.
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
                    {filtro_vinculacion}
                    AND T."IdTipoDocumentacion" NOT IN (36, 64)
                    AND {_categoria_documental_sql()}
                ORDER BY
                    T."IdTipoDocumentacion" ASC,
                    CASE
                        WHEN :preferir_vinculacion = TRUE
                         AND r."IdVinculacionLaboral" = :id_vinculacion_laboral
                        THEN 0
                        ELSE 1
                    END ASC,
                    d."IdDocumento" DESC
            ) AS documentos_normales

            UNION ALL

            /*
             * Documentos múltiples:
             * 36 = Entrega de dotación
             * 64 = Otro sí
             *
             * Para estos tipos se devuelven todos los documentos
             * asociados dentro del alcance solicitado.
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
                {filtro_vinculacion}
                AND T."IdTipoDocumentacion" IN (36, 64)
                AND {_categoria_documental_sql()}
        ) AS resultado
        ORDER BY
            resultado."IdTipoDocumentacion" ASC,
            resultado."IdDocumento" ASC
    """

    parametros = {
        "id": id_registro_personal,
        "id_categoria": id_categoria,
        "preferir_vinculacion": bool(
            filtrar_vinculacion and incluir_legacy
        ),
        "id_vinculacion_laboral": id_vinculacion_laboral,
    }

    return db.execute(
        text(sql),
        parametros,
    ).fetchall()


def _convertir_rows_a_documentos(
    rows,
) -> list[DocIngresoDetalle]:
    documentos: list[DocIngresoDetalle] = []

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


def _obtener_vinculacion_actual(
    db: Session,
    id_registro_personal: int,
):
    vinculaciones = db.execute(
        text(
            """
            SELECT
                vl."IdVinculacionLaboral",
                vl."NumeroCiclo",
                vl."TipoVinculacion",
                vl."EstadoVinculacion"
            FROM public."VinculacionLaboral" vl
            WHERE vl."IdRegistroPersonal" = :id
            ORDER BY
                CASE
                    WHEN UPPER(
                        COALESCE(vl."EstadoVinculacion", '')
                    ) IN ('EN_PROCESO', 'ACTIVO')
                    THEN 0
                    ELSE 1
                END,
                vl."NumeroCiclo" DESC,
                vl."IdVinculacionLaboral" DESC;
            """
        ),
        {"id": id_registro_personal},
    ).mappings().all()

    if not vinculaciones:
        return None, []

    actual = next(
        (
            dict(v)
            for v in vinculaciones
            if str(
                v.get("EstadoVinculacion") or ""
            ).strip().upper() in {"EN_PROCESO", "ACTIVO"}
        ),
        None,
    )

    if actual is None:
        actual = dict(vinculaciones[0])

    return actual, [dict(v) for v in vinculaciones]


def _consultar_documentos_por_vinculacion_para_historial(
    db: Session,
    id_registro_personal: int,
    id_categoria: int,
    id_vinculacion_laboral: int,
    numero_ciclo: int | None,
    tipo_vinculacion: str | None,
    estado_vinculacion: str | None,
    solo_consulta: bool,
) -> DocumentosIngresoCicloResumen:
    rows = db.execute(
        text(
            f"""
            SELECT
                resultado."IdTipoDocumentacion",
                resultado."IdDocumento",
                resultado."DocumentoCargado",
                resultado."Nombre",
                resultado."Formato",
                resultado."Descripcion"
            FROM (
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
                        AND r."IdVinculacionLaboral" = :id_vinculacion
                        AND T."IdTipoDocumentacion" NOT IN (36, 64)
                        AND {_categoria_documental_sql()}
                    ORDER BY
                        T."IdTipoDocumentacion" ASC,
                        d."IdDocumento" DESC
                ) AS documentos_normales

                UNION ALL

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
                    AND r."IdVinculacionLaboral" = :id_vinculacion
                    AND T."IdTipoDocumentacion" IN (36, 64)
                    AND {_categoria_documental_sql()}
            ) AS resultado
            ORDER BY
                resultado."IdTipoDocumentacion" ASC,
                resultado."IdDocumento" ASC
            """
        ),
        {
            "id": id_registro_personal,
            "id_vinculacion": id_vinculacion_laboral,
            "id_categoria": id_categoria,
        },
    ).fetchall()

    documentos: list[DocIngresoDetalleCiclo] = []

    for row in rows:
        documento_cargado = row[2]

        if documento_cargado is None:
            continue

        documentos.append(
            DocIngresoDetalleCiclo(
                IdRegistroPersonal=id_registro_personal,
                IdVinculacionLaboral=id_vinculacion_laboral,
                NumeroCiclo=numero_ciclo,
                TipoVinculacion=tipo_vinculacion,
                EstadoVinculacion=estado_vinculacion,
                EsHistoricoLegacy=False,
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

    return DocumentosIngresoCicloResumen(
        IdVinculacionLaboral=id_vinculacion_laboral,
        NumeroCiclo=numero_ciclo,
        TipoVinculacion=tipo_vinculacion,
        EstadoVinculacion=estado_vinculacion,
        EsHistoricoLegacy=False,
        SoloConsulta=solo_consulta,
        documentos=documentos,
    )


def _consultar_documentos_legacy(
    db: Session,
    id_registro_personal: int,
    id_categoria: int,
) -> DocumentosIngresoCicloResumen | None:
    """
    Documentos históricos creados antes de que la relación documental
    manejara IdVinculacionLaboral.

    Se exponen únicamente como histórico de solo consulta.
    Nunca se mezclan con el ciclo actual.
    """

    rows = db.execute(
        text(
            f"""
            SELECT
                resultado."IdTipoDocumentacion",
                resultado."IdDocumento",
                resultado."DocumentoCargado",
                resultado."Nombre",
                resultado."Formato",
                resultado."Descripcion"
            FROM (
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
                        AND r."IdVinculacionLaboral" IS NULL
                        AND T."IdTipoDocumentacion" NOT IN (36, 64)
                        AND {_categoria_documental_sql()}
                    ORDER BY
                        T."IdTipoDocumentacion" ASC,
                        d."IdDocumento" DESC
                ) AS documentos_normales

                UNION ALL

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
                    AND r."IdVinculacionLaboral" IS NULL
                    AND T."IdTipoDocumentacion" IN (36, 64)
                    AND {_categoria_documental_sql()}
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

    documentos: list[DocIngresoDetalleCiclo] = []

    for row in rows:
        documento_cargado = row[2]

        if documento_cargado is None:
            continue

        documentos.append(
            DocIngresoDetalleCiclo(
                IdRegistroPersonal=id_registro_personal,
                IdVinculacionLaboral=None,
                NumeroCiclo=None,
                TipoVinculacion="HISTORICO_LEGACY",
                EstadoVinculacion="HISTORICO",
                EsHistoricoLegacy=True,
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

    if not documentos:
        return None

    return DocumentosIngresoCicloResumen(
        IdVinculacionLaboral=None,
        NumeroCiclo=None,
        TipoVinculacion="HISTORICO_LEGACY",
        EstadoVinculacion="HISTORICO",
        EsHistoricoLegacy=True,
        SoloConsulta=True,
        documentos=documentos,
    )


@router.get(
    "/aspirante/{id_registro_personal}/categoria/{id_categoria}",
    response_model=list[DocIngresoDetalle],
)
def obtener_documento_ingreso(
    id_registro_personal: int,
    id_categoria: int,
    db: Session = Depends(get_db),
):
    """
    ENDPOINT LEGADO.

    Se conserva sin cambiar su contrato ni su comportamiento para no afectar
    Aspirante, Selección, Carpeta Digital u otros módulos que todavía consuman
    documentos por IdRegistroPersonal.

    Los flujos nuevos de reintegro deben usar los endpoints por vinculación.
    """

    rows = _consultar_documentos_ingreso(
        db=db,
        id_registro_personal=id_registro_personal,
        id_categoria=id_categoria,
        filtrar_vinculacion=False,
    )

    return _convertir_rows_a_documentos(rows)


@router.get(
    "/aspirante/{id_registro_personal}/vinculacion/{id_vinculacion_laboral}/categoria/{id_categoria}",
    response_model=list[DocIngresoDetalle],
)
def obtener_documento_ingreso_por_vinculacion(
    id_registro_personal: int,
    id_vinculacion_laboral: int,
    id_categoria: int,
    db: Session = Depends(get_db),
):
    """
    Documentos del CICLO LABORAL solicitado.

    Reglas:
    - Ciclo actual: consulta estrictamente su IdVinculacionLaboral.
    - Primer ciclo histórico: consulta su vinculación y además documentos
      legacy cuyo IdVinculacionLaboral es NULL.
    - Otros ciclos históricos: consulta únicamente su IdVinculacionLaboral.
    - Nunca modifica documentos.
    """

    vinculaciones = db.execute(
        text(
            """
            SELECT
                vl."IdVinculacionLaboral",
                vl."NumeroCiclo",
                vl."TipoVinculacion",
                vl."EstadoVinculacion"
            FROM public."VinculacionLaboral" vl
            WHERE vl."IdRegistroPersonal" = :id
            ORDER BY
                vl."NumeroCiclo" ASC,
                vl."IdVinculacionLaboral" ASC;
            """
        ),
        {"id": id_registro_personal},
    ).mappings().all()

    if not vinculaciones:
        raise HTTPException(
            status_code=404,
            detail=(
                "El trabajador no tiene vinculaciones laborales "
                "registradas."
            ),
        )

    vinculacion_solicitada = next(
        (
            dict(v)
            for v in vinculaciones
            if int(v["IdVinculacionLaboral"])
            == id_vinculacion_laboral
        ),
        None,
    )

    if vinculacion_solicitada is None:
        raise HTTPException(
            status_code=404,
            detail=(
                "La vinculación laboral indicada no pertenece "
                "al trabajador solicitado."
            ),
        )

    vinculacion_actual = next(
        (
            dict(v)
            for v in vinculaciones
            if str(
                v.get("EstadoVinculacion") or ""
            ).strip().upper() in {"EN_PROCESO", "ACTIVO"}
        ),
        None,
    )

    if vinculacion_actual is None:
        vinculacion_actual = dict(vinculaciones[-1])

    id_vinculacion_actual = int(
        vinculacion_actual["IdVinculacionLaboral"]
    )

    ciclos_validos = [
        int(v["NumeroCiclo"])
        for v in vinculaciones
        if v.get("NumeroCiclo") is not None
    ]

    numero_ciclo_mas_antiguo = (
        min(ciclos_validos)
        if ciclos_validos
        else None
    )

    numero_ciclo_solicitado = (
        int(vinculacion_solicitada["NumeroCiclo"])
        if vinculacion_solicitada.get("NumeroCiclo") is not None
        else None
    )

    es_historico = (
        id_vinculacion_laboral != id_vinculacion_actual
    )

    es_primer_ciclo_historico = (
        es_historico
        and numero_ciclo_mas_antiguo is not None
        and numero_ciclo_solicitado == numero_ciclo_mas_antiguo
    )

    rows = _consultar_documentos_ingreso(
        db=db,
        id_registro_personal=id_registro_personal,
        id_categoria=id_categoria,
        id_vinculacion_laboral=id_vinculacion_laboral,
        filtrar_vinculacion=True,
        incluir_legacy=es_primer_ciclo_historico,
    )

    return _convertir_rows_a_documentos(rows)


@router.get(
    "/aspirante/{id_registro_personal}/categoria/{id_categoria}/ciclos",
    response_model=DocumentosIngresoPorCiclosResponse,
)
def obtener_documentos_ingreso_por_ciclos(
    id_registro_personal: int,
    id_categoria: int,
    db: Session = Depends(get_db),
):
    """
    Vista documental separada por ciclos.

    Pensada para Carpeta Digital:
    - cicloActual: carpeta documental de la vinculación actual.
    - historico: carpetas anteriores congeladas en solo consulta.
    - registros legacy sin IdVinculacionLaboral aparecen en un bloque
      histórico separado y nunca se mezclan con el ciclo actual.

    Este endpoint es SOLO CONSULTA.
    """

    persona = db.execute(
        text(
            """
            SELECT 1
            FROM public."RegistroPersonal"
            WHERE "IdRegistroPersonal" = :id
            LIMIT 1;
            """
        ),
        {"id": id_registro_personal},
    ).first()

    if not persona:
        raise HTTPException(
            status_code=404,
            detail="No se encontró el trabajador solicitado.",
        )

    vinculacion_actual, vinculaciones = _obtener_vinculacion_actual(
        db,
        id_registro_personal,
    )

    id_vinculacion_actual = (
        int(vinculacion_actual["IdVinculacionLaboral"])
        if vinculacion_actual
        and vinculacion_actual.get("IdVinculacionLaboral") is not None
        else None
    )

    ciclo_actual: DocumentosIngresoCicloResumen | None = None
    historico: list[DocumentosIngresoCicloResumen] = []

    for vinculacion in vinculaciones:
        id_vinc = vinculacion.get("IdVinculacionLaboral")

        if id_vinc is None:
            continue

        id_vinc = int(id_vinc)

        resumen = _consultar_documentos_por_vinculacion_para_historial(
            db=db,
            id_registro_personal=id_registro_personal,
            id_categoria=id_categoria,
            id_vinculacion_laboral=id_vinc,
            numero_ciclo=vinculacion.get("NumeroCiclo"),
            tipo_vinculacion=vinculacion.get("TipoVinculacion"),
            estado_vinculacion=vinculacion.get("EstadoVinculacion"),
            solo_consulta=(id_vinc != id_vinculacion_actual),
        )

        if id_vinc == id_vinculacion_actual:
            ciclo_actual = resumen
        else:
            historico.append(resumen)

    legacy = _consultar_documentos_legacy(
        db=db,
        id_registro_personal=id_registro_personal,
        id_categoria=id_categoria,
    )

    if legacy is not None:
        historico.append(legacy)

    return DocumentosIngresoPorCiclosResponse(
        ok=True,
        soloConsulta=True,
        IdRegistroPersonal=id_registro_personal,
        IdVinculacionActual=id_vinculacion_actual,
        cicloActual=ciclo_actual,
        historico=historico,
    )