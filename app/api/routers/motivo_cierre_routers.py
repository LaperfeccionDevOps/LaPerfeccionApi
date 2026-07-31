# app/api/routers/motivo_cierre_routers.py
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.orm import Session

from infrastructure.db.deps import get_db

router = APIRouter(prefix="/api/motivo-cierre", tags=["motivo-cierre"])


class MotivoCierreUpsert(BaseModel):
    MotivoCierre: str
    Observaciones: str | None = None
    UsuarioActualizacion: str


@router.get("/{id_registro_personal}")
def obtener_motivo_cierre(
    id_registro_personal: int,
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, Any]:
    """
    Devuelve el motivo de cierre de Selección o, cuando el rechazo fue
    registrado desde Contratación, la observación libre del botón NC.

    Esta función solo consulta información. No modifica la base de datos.
    """

    q = text(
        """
        SELECT
            rp."IdRegistroPersonal",
            rp."IdEstadoProceso",

            mcp."MotivoCierre",
            mcp."Observaciones",
            mcp."UsuarioActualizacion",
            mcp."FechaCreacion",
            mcp."FechaActualizacion",

            CASE
                WHEN
                    rp."IdEstadoProceso" = 28
                    AND mcp."IdMotivoCierre" IS NULL
                    AND (
                        rechazo_contratacion."IdHistorialEstadoContratacion"
                            IS NOT NULL
                        OR NULLIF(
                            TRIM(
                                COALESCE(
                                    observacion_contratacion."ObservacionesRechazo",
                                    ''
                                )
                            ),
                            ''
                        ) IS NOT NULL
                    )
                THEN 'CONTRATACION'

                WHEN mcp."IdMotivoCierre" IS NOT NULL
                THEN 'SELECCION'

                ELSE NULL
            END AS "OrigenRechazo",

            CASE
                WHEN
                    rp."IdEstadoProceso" = 28
                    AND mcp."IdMotivoCierre" IS NULL
                    AND (
                        rechazo_contratacion."IdHistorialEstadoContratacion"
                            IS NOT NULL
                        OR NULLIF(
                            TRIM(
                                COALESCE(
                                    observacion_contratacion."ObservacionesRechazo",
                                    ''
                                )
                            ),
                            ''
                        ) IS NOT NULL
                    )
                THEN TRUE
                ELSE FALSE
            END AS "EsRechazoContratacion",

            observacion_contratacion."ObservacionesRechazo"
                AS "ObservacionContratacion",

            rechazo_contratacion."UsuarioMovimiento"
                AS "UsuarioRechazoContratacion",

            rechazo_contratacion."FechaMovimiento"
                AS "FechaRechazoContratacion"

        FROM public."RegistroPersonal" rp

        LEFT JOIN LATERAL (
            SELECT
                mcp_detalle."IdMotivoCierre",
                mcp_detalle."MotivoCierre",
                mcp_detalle."Observaciones",
                mcp_detalle."UsuarioActualizacion",
                mcp_detalle."FechaCreacion",
                mcp_detalle."FechaActualizacion"
            FROM public."MotivoCierreProceso" mcp_detalle
            WHERE
                mcp_detalle."IdRegistroPersonal"
                    = rp."IdRegistroPersonal"
            ORDER BY
                COALESCE(
                    mcp_detalle."FechaActualizacion",
                    mcp_detalle."FechaCreacion"
                ) DESC,
                mcp_detalle."IdMotivoCierre" DESC
            LIMIT 1
        ) mcp ON TRUE

        LEFT JOIN LATERAL (
            SELECT
                orc_detalle."ObservacionesRechazo"
            FROM public."ObsRechazoContratacion" orc_detalle
            WHERE
                orc_detalle."IdRegistroPersonal"
                    = rp."IdRegistroPersonal"
            ORDER BY
                orc_detalle."IdObsRechazoContratacion" DESC
            LIMIT 1
        ) observacion_contratacion ON TRUE

        LEFT JOIN LATERAL (
            SELECT
                hec."IdHistorialEstadoContratacion",
                hec."FechaMovimiento",
                hec."UsuarioMovimiento"
            FROM public."HistorialEstadoContratacion" hec
            WHERE
                hec."IdRegistroPersonal"
                    = rp."IdRegistroPersonal"
                AND hec."EstadoNuevo" = 28
                AND UPPER(
                    TRIM(COALESCE(hec."Modulo", ''))
                ) = 'CONTRATACION'
            ORDER BY
                hec."FechaMovimiento" DESC,
                hec."IdHistorialEstadoContratacion" DESC
            LIMIT 1
        ) rechazo_contratacion ON TRUE

        WHERE
            rp."IdRegistroPersonal" = :id

        LIMIT 1;
        """
    )

    row = db.execute(
        q,
        {"id": id_registro_personal},
    ).mappings().first()

    if not row:
        raise HTTPException(
            status_code=404,
            detail="IdRegistroPersonal no existe en RegistroPersonal",
        )

    resultado = dict(row)

    tiene_motivo_seleccion = bool(resultado.get("MotivoCierre"))
    es_rechazo_contratacion = bool(
        resultado.get("EsRechazoContratacion")
    )

    if not tiene_motivo_seleccion and not es_rechazo_contratacion:
        raise HTTPException(
            status_code=404,
            detail="No hay motivo de cierre para este IdRegistroPersonal",
        )

    return resultado


@router.put("/{id_registro_personal}")
def upsert_motivo_cierre(
    id_registro_personal: int,
    payload: MotivoCierreUpsert,
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, Any]:
    if not payload.MotivoCierre or not payload.MotivoCierre.strip():
        raise HTTPException(
            status_code=422,
            detail="MotivoCierre es requerido",
        )

    existe = db.execute(
        text(
            'SELECT 1 FROM "RegistroPersonal" '
            'WHERE "IdRegistroPersonal" = :id LIMIT 1;'
        ),
        {"id": id_registro_personal},
    ).first()

    if not existe:
        raise HTTPException(
            status_code=404,
            detail="IdRegistroPersonal no existe en RegistroPersonal",
        )

    q = text(
        """
        INSERT INTO "MotivoCierreProceso"
          (
            "IdRegistroPersonal",
            "MotivoCierre",
            "Observaciones",
            "UsuarioActualizacion",
            "FechaCreacion",
            "FechaActualizacion"
          )
        VALUES
          (:id, :motivo, :obs, :usr, now(), now())
        ON CONFLICT ("IdRegistroPersonal") DO UPDATE
        SET
          "MotivoCierre" = EXCLUDED."MotivoCierre",
          "Observaciones" = EXCLUDED."Observaciones",
          "UsuarioActualizacion" = EXCLUDED."UsuarioActualizacion",
          "FechaActualizacion" = now();
        """
    )

    db.execute(
        q,
        {
            "id": id_registro_personal,
            "motivo": payload.MotivoCierre.strip(),
            "obs": payload.Observaciones,
            "usr": payload.UsuarioActualizacion.strip(),
        },
    )
    db.commit()

    return {
        "ok": True,
        "message": "Motivo cierre guardado/actualizado",
        "IdRegistroPersonal": id_registro_personal,
    }
    