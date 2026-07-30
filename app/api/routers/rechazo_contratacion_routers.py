from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.orm import Session

from infrastructure.db.deps import get_db


router = APIRouter(
    prefix="/api",
    tags=["Rechazo Contratación"],
)


ESTADO_AVANZA_CONTRATACION = 24
ESTADO_RECHAZADO = 28


class RechazoCreate(BaseModel):
    IdRegistroPersonal: int = Field(
        ...,
        gt=0,
    )
    ObservacionesRechazo: str = Field(
        ...,
        min_length=3,
        max_length=500,
    )
    UsuarioActualizacion: Optional[str] = Field(
        default="contratacion",
        max_length=150,
    )


@router.post("/rechazo-contratacion")
def crear_o_actualizar_rechazo(
    payload: RechazoCreate,
    db: Session = Depends(get_db),
):
    observacion = (
        payload.ObservacionesRechazo or ""
    ).strip()

    usuario_movimiento = (
        payload.UsuarioActualizacion or "contratacion"
    ).strip()

    if len(observacion) < 3:
        raise HTTPException(
            status_code=422,
            detail="Debe ingresar el motivo del rechazo.",
        )

    if not usuario_movimiento:
        usuario_movimiento = "contratacion"

    try:
        # Bloquea el trabajador durante toda la transacción.
        trabajador = db.execute(
            text(
                """
                SELECT
                    rp."IdRegistroPersonal",
                    rp."IdEstadoProceso",
                    rp."UsuarioActualizacion"
                FROM public."RegistroPersonal" rp
                WHERE rp."IdRegistroPersonal" = :id_registro
                FOR UPDATE;
                """
            ),
            {
                "id_registro": payload.IdRegistroPersonal,
            },
        ).mappings().first()

        if not trabajador:
            raise HTTPException(
                status_code=404,
                detail=(
                    "El IdRegistroPersonal no existe en "
                    "RegistroPersonal."
                ),
            )

        estado_anterior = trabajador.get(
            "IdEstadoProceso"
        )

        if estado_anterior != ESTADO_AVANZA_CONTRATACION:
            raise HTTPException(
                status_code=409,
                detail=(
                    "El trabajador no se encuentra en estado "
                    "24 - Avanza a contratación. "
                    f"Estado actual: {estado_anterior}."
                ),
            )

        # Guarda o actualiza la última observación de rechazo.
        # FechaRechazo ahora guarda fecha y hora completas.
        rechazo = db.execute(
            text(
                """
                INSERT INTO public."ObsRechazoContratacion"
                (
                    "IdRegistroPersonal",
                    "ObservacionesRechazo",
                    "FechaRechazo"
                )
                VALUES
                (
                    :id_registro,
                    :observacion,
                    NOW()
                )
                ON CONFLICT ("IdRegistroPersonal")
                DO UPDATE SET
                    "ObservacionesRechazo" =
                        EXCLUDED."ObservacionesRechazo",
                    "FechaRechazo" = NOW()
                RETURNING
                    "IdObsRechazoContratacion",
                    "IdRegistroPersonal",
                    "ObservacionesRechazo",
                    "FechaRechazo";
                """
            ),
            {
                "id_registro": payload.IdRegistroPersonal,
                "observacion": observacion,
            },
        ).mappings().first()

        if not rechazo:
            raise HTTPException(
                status_code=500,
                detail=(
                    "No fue posible guardar la observación "
                    "del rechazo."
                ),
            )

        # Registra el movimiento histórico 24 -> 28.
        movimiento = db.execute(
            text(
                """
                INSERT INTO public."HistorialEstadoContratacion"
                (
                    "IdRegistroPersonal",
                    "EstadoAnterior",
                    "EstadoNuevo",
                    "FechaMovimiento",
                    "UsuarioMovimiento",
                    "OrigenMovimiento",
                    "Modulo"
                )
                VALUES
                (
                    :id_registro,
                    :estado_anterior,
                    :estado_nuevo,
                    NOW(),
                    :usuario_movimiento,
                    'BOTON_NC',
                    'CONTRATACION'
                )
                RETURNING
                    "IdHistorialEstadoContratacion",
                    "FechaMovimiento";
                """
            ),
            {
                "id_registro": payload.IdRegistroPersonal,
                "estado_anterior": estado_anterior,
                "estado_nuevo": ESTADO_RECHAZADO,
                "usuario_movimiento": usuario_movimiento,
            },
        ).mappings().first()

        if not movimiento:
            raise HTTPException(
                status_code=500,
                detail=(
                    "No fue posible registrar el movimiento "
                    "histórico del rechazo."
                ),
            )

        # Actualiza el estado actual, la fecha y el usuario.
        resultado_actualizacion = db.execute(
            text(
                """
                UPDATE public."RegistroPersonal"
                SET
                    "IdEstadoProceso" = :estado_nuevo,
                    "FechaActualizacion" = NOW(),
                    "UsuarioActualizacion" =
                        :usuario_movimiento
                WHERE
                    "IdRegistroPersonal" = :id_registro
                    AND "IdEstadoProceso" = :estado_anterior;
                """
            ),
            {
                "estado_nuevo": ESTADO_RECHAZADO,
                "usuario_movimiento": usuario_movimiento,
                "id_registro": payload.IdRegistroPersonal,
                "estado_anterior": estado_anterior,
            },
        )

        if resultado_actualizacion.rowcount != 1:
            raise HTTPException(
                status_code=409,
                detail=(
                    "No fue posible actualizar el estado del "
                    "trabajador. El registro pudo cambiar "
                    "durante la operación."
                ),
            )

        db.commit()

        return {
            "ok": True,
            "message": (
                "El trabajador fue rechazado correctamente "
                "desde Contratación."
            ),
            "IdRegistroPersonal": (
                payload.IdRegistroPersonal
            ),
            "EstadoAnterior": estado_anterior,
            "EstadoNuevo": ESTADO_RECHAZADO,
            "ObservacionesRechazo": rechazo.get(
                "ObservacionesRechazo"
            ),
            "FechaRechazo": rechazo.get(
                "FechaRechazo"
            ),
            "IdHistorialEstadoContratacion": (
                movimiento.get(
                    "IdHistorialEstadoContratacion"
                )
            ),
            "FechaMovimiento": movimiento.get(
                "FechaMovimiento"
            ),
            "OrigenMovimiento": "BOTON_NC",
            "Modulo": "CONTRATACION",
            "UsuarioMovimiento": usuario_movimiento,
        }

    except HTTPException:
        db.rollback()
        raise

    except Exception as error:
        db.rollback()
        raise HTTPException(
            status_code=500,
            detail=(
                "Error al registrar el rechazo: "
                f"{str(error)}"
            ),
        )