from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session

from infrastructure.db.deps import get_db

router = APIRouter(prefix="/api/nomina-retiros", tags=["Nómina Retiros"])


@router.get("")
def listar_retiros_nomina(db: Session = Depends(get_db)):
    try:
        query = text("""
            SELECT
                rl."IdRetiroLaboral",
                rl."IdRegistroPersonal",
                rp."NumeroIdentificacion",
                rp."Nombres",
                rp."Apellidos",
                COALESCE(c."Nombre", 'SIN CLIENTE') AS "NombreCliente",
                rl."FechaProceso",
                rl."FechaRetiro",
                rl."FechaCierre",
                rl."FechaEnvioNomina",
                rl."EstadoCasoRRLL",
                rp."IdEstadoProceso",
                ep."Nombre" AS "EstadoProceso",
                mr."Nombre" AS "MotivoRetiro",
                tr."Nombre" AS "TipificacionRetiro",
                rl."ObservacionGeneral",
                rl."ObservacionRetiro",
                CASE
                    WHEN rp."IdEstadoProceso" = 32 THEN true
                    ELSE false
                END AS "PuedeGestionarNomina"
            FROM public."RetiroLaboral" rl
            INNER JOIN public."RegistroPersonal" rp
                ON rp."IdRegistroPersonal" = rl."IdRegistroPersonal"
            LEFT JOIN public."Cliente" c
                ON c."IdCliente" = rl."IdCliente"
            LEFT JOIN public."EstadoProceso" ep
                ON ep."IdEstadoProceso" = rp."IdEstadoProceso"
            LEFT JOIN public."MotivoRetiro" mr
                ON mr."IdMotivoRetiro" = rl."IdMotivoRetiro"
            LEFT JOIN public."TipificacionRetiro" tr
                ON tr."IdTipificacionRetiro" = rl."IdTipificacionRetiro"
            WHERE COALESCE(rl."Activo", true) = true
              AND rp."IdEstadoProceso" IN (30, 32)
            ORDER BY
                CASE WHEN rp."IdEstadoProceso" = 32 THEN 0 ELSE 1 END,
                rl."FechaCreacion" DESC;
        """)

        rows = db.execute(query).mappings().all()

        return {
            "success": True,
            "message": "Retiros de nómina consultados correctamente.",
            "data": [dict(row) for row in rows]
        }

    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Error al consultar retiros de nómina: {str(e)}"
        )