# app/services/vinculacion_laboral_service.py

from typing import Optional, Dict, Any

from sqlalchemy import text
from sqlalchemy.orm import Session


ESTADOS_CICLO_ABIERTO = (
    "EN_PROCESO",
    "ACTIVO",
)


def obtener_vinculacion_abierta(
    db: Session,
    id_registro_personal: int,
) -> Optional[Dict[str, Any]]:
    """
    Retorna la vinculación laboral abierta del trabajador.

    Se considera abierta una vinculación cuyo EstadoVinculacion sea:
    - EN_PROCESO
    - ACTIVO

    Si no existe una vinculación abierta, retorna None.

    Esta función:
    - SOLO CONSULTA;
    - NO INSERTA;
    - NO ACTUALIZA;
    - NO ELIMINA.
    """

    if not id_registro_personal:
        return None

    sql = text(
        """
        SELECT
            vl."IdVinculacionLaboral",
            vl."IdRegistroPersonal",
            vl."NumeroCiclo",
            vl."TipoVinculacion",
            vl."EstadoVinculacion",
            vl."FechaInicioProceso",
            vl."FechaIngreso",
            vl."FechaRetiro",
            vl."IdCargo",
            vl."IdCliente",
            vl."Salario",
            vl."IdTipoContrato",
            vl."FechaCreacion",
            vl."FechaActualizacion",
            vl."UsuarioActualizacion"
        FROM public."VinculacionLaboral" vl
        WHERE vl."IdRegistroPersonal" = :id_registro_personal
          AND vl."EstadoVinculacion" IN (
              'EN_PROCESO',
              'ACTIVO'
          )
        ORDER BY
            vl."NumeroCiclo" DESC,
            vl."IdVinculacionLaboral" DESC
        LIMIT 1;
        """
    )

    row = db.execute(
        sql,
        {
            "id_registro_personal": id_registro_personal,
        },
    ).mappings().first()

    return dict(row) if row else None


def obtener_ultima_vinculacion(
    db: Session,
    id_registro_personal: int,
) -> Optional[Dict[str, Any]]:
    """
    Retorna el último ciclo laboral registrado del trabajador.

    Esta función:
    - SOLO CONSULTA;
    - NO INSERTA;
    - NO ACTUALIZA;
    - NO ELIMINA.
    """

    if not id_registro_personal:
        return None

    sql = text(
        """
        SELECT
            vl."IdVinculacionLaboral",
            vl."IdRegistroPersonal",
            vl."NumeroCiclo",
            vl."TipoVinculacion",
            vl."EstadoVinculacion",
            vl."FechaInicioProceso",
            vl."FechaIngreso",
            vl."FechaRetiro",
            vl."IdCargo",
            vl."IdCliente",
            vl."Salario",
            vl."IdTipoContrato",
            vl."FechaCreacion",
            vl."FechaActualizacion",
            vl."UsuarioActualizacion"
        FROM public."VinculacionLaboral" vl
        WHERE vl."IdRegistroPersonal" = :id_registro_personal
        ORDER BY
            vl."NumeroCiclo" DESC,
            vl."IdVinculacionLaboral" DESC
        LIMIT 1;
        """
    )

    row = db.execute(
        sql,
        {
            "id_registro_personal": id_registro_personal,
        },
    ).mappings().first()

    return dict(row) if row else None