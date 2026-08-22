from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from infrastructure.db.deps import get_db

from domain.models.asistente_descargo_proceso_disciplinario import (
    AsistenteDescargoProcesoDisciplinario,
)
from domain.models.descargo_proceso_disciplinario import (
    DescargoProcesoDisciplinario,
)
from domain.models.proceso_disciplinario import (
    ProcesoDisciplinario,
)
from domain.schemas.asistente_descargo_proceso_disciplinario_schema import (
    AsistenteDescargoProcesoDisciplinarioResponse,
    AsistenteDescargoProcesoDisciplinarioUpdate,
    GuardarAsistentesDescargoRequest,
)


router = APIRouter(
    prefix="/api/asistente-descargo-proceso-disciplinario",
    tags=["Asistente Descargo Proceso Disciplinario"],
)


def obtener_proceso_o_error(
    db: Session,
    id_proceso: int,
) -> ProcesoDisciplinario:
    proceso = (
        db.query(ProcesoDisciplinario)
        .filter(
            ProcesoDisciplinario.IdProcesoDisciplinario
            == id_proceso
        )
        .first()
    )

    if not proceso:
        raise HTTPException(
            status_code=404,
            detail={
                "mensaje": (
                    "El proceso disciplinario no fue encontrado."
                ),
                "IdProcesoDisciplinario": id_proceso,
            },
        )

    return proceso


def obtener_descargo_o_error(
    db: Session,
    id_descargo: int,
) -> DescargoProcesoDisciplinario:
    descargo = (
        db.query(DescargoProcesoDisciplinario)
        .filter(
            DescargoProcesoDisciplinario
            .IdDescargoProcesoDisciplinario
            == id_descargo
        )
        .first()
    )

    if not descargo:
        raise HTTPException(
            status_code=404,
            detail={
                "mensaje": (
                    "El descargo disciplinario no fue encontrado."
                ),
                "IdDescargoProcesoDisciplinario": id_descargo,
            },
        )

    return descargo


def obtener_asistente_o_error(
    db: Session,
    id_asistente: int,
) -> AsistenteDescargoProcesoDisciplinario:
    asistente = (
        db.query(AsistenteDescargoProcesoDisciplinario)
        .filter(
            AsistenteDescargoProcesoDisciplinario
            .IdAsistenteDescargoProcesoDisciplinario
            == id_asistente
        )
        .first()
    )

    if not asistente:
        raise HTTPException(
            status_code=404,
            detail={
                "mensaje": (
                    "El asistente de la diligencia no fue encontrado."
                ),
                "IdAsistenteDescargoProcesoDisciplinario": (
                    id_asistente
                ),
            },
        )

    return asistente


@router.post(
    "/guardar-borrador",
    response_model=list[
        AsistenteDescargoProcesoDisciplinarioResponse
    ],
)
def guardar_borrador_asistentes(
    data: GuardarAsistentesDescargoRequest,
    db: Session = Depends(get_db),
):
    proceso = obtener_proceso_o_error(
        db=db,
        id_proceso=data.IdProcesoDisciplinario,
    )

    if (
        str(proceso.EstadoProceso or "").strip().upper()
        == "CERRADO"
    ):
        raise HTTPException(
            status_code=409,
            detail=(
                "No se pueden modificar los asistentes porque "
                "el proceso disciplinario se encuentra cerrado."
            ),
        )

    if data.IdDescargoProcesoDisciplinario is not None:
        descargo = obtener_descargo_o_error(
            db=db,
            id_descargo=(
                data.IdDescargoProcesoDisciplinario
            ),
        )

        if (
            descargo.IdProcesoDisciplinario
            != data.IdProcesoDisciplinario
        ):
            raise HTTPException(
                status_code=409,
                detail=(
                    "El descargo indicado no pertenece al "
                    "proceso disciplinario enviado."
                ),
            )

    tipos_recibidos = [
        asistente.TipoAsistente
        for asistente in data.Asistentes
    ]

    if len(tipos_recibidos) != len(set(tipos_recibidos)):
        raise HTTPException(
            status_code=422,
            detail=(
                "No se puede guardar más de un registro "
                "para el mismo tipo de asistente."
            ),
        )

    try:
        asistentes_existentes = (
            db.query(AsistenteDescargoProcesoDisciplinario)
            .filter(
                AsistenteDescargoProcesoDisciplinario
                .IdProcesoDisciplinario
                == data.IdProcesoDisciplinario
            )
            .all()
        )

        asistentes_por_tipo = {
            asistente.TipoAsistente: asistente
            for asistente in asistentes_existentes
        }

        tipos_enviados = set()

        for asistente_data in data.Asistentes:
            tipos_enviados.add(
                asistente_data.TipoAsistente
            )

            asistente_existente = asistentes_por_tipo.get(
                asistente_data.TipoAsistente
            )

            nombre_asistente = (
                asistente_data.NombreAsistente
            )

            if nombre_asistente is not None:
                nombre_asistente = (
                    nombre_asistente.strip() or None
                )

            if asistente_existente:
                asistente_existente.IdDescargoProcesoDisciplinario = (
                    data.IdDescargoProcesoDisciplinario
                )
                asistente_existente.NombreAsistente = nombre_asistente
                asistente_existente.Asistio = asistente_data.Asistio
                asistente_existente.Activo = True
                asistente_existente.FechaActualizacion = datetime.now()
                asistente_existente.UsuarioActualizacion = (
                    data.UsuarioActualizacion
                )
            else:
                nuevo_asistente = (
                    AsistenteDescargoProcesoDisciplinario(
                        IdProcesoDisciplinario=(
                            data.IdProcesoDisciplinario
                        ),
                        IdDescargoProcesoDisciplinario=(
                            data.IdDescargoProcesoDisciplinario
                        ),
                        TipoAsistente=(
                            asistente_data.TipoAsistente
                        ),
                        NombreAsistente=nombre_asistente,
                        Asistio=asistente_data.Asistio,
                        Activo=True,
                        UsuarioCreacion=(
                            data.UsuarioActualizacion
                        ),
                        UsuarioActualizacion=(
                            data.UsuarioActualizacion
                        ),
                    )
                )

                db.add(nuevo_asistente)

        for asistente_existente in asistentes_existentes:
            if (
                asistente_existente.TipoAsistente
                not in tipos_enviados
            ):
                asistente_existente.Asistio = False
                asistente_existente.Activo = False
                asistente_existente.FechaActualizacion = datetime.now()
                asistente_existente.UsuarioActualizacion = (
                    data.UsuarioActualizacion
                )

        db.commit()

        resultado = (
            db.query(AsistenteDescargoProcesoDisciplinario)
            .filter(
                AsistenteDescargoProcesoDisciplinario
                .IdProcesoDisciplinario
                == data.IdProcesoDisciplinario
            )
            .filter(
                AsistenteDescargoProcesoDisciplinario
                .Activo
                .is_(True)
            )
            .order_by(
                AsistenteDescargoProcesoDisciplinario
                .IdAsistenteDescargoProcesoDisciplinario
                .asc()
            )
            .all()
        )

        return resultado

    except SQLAlchemyError as error:
        db.rollback()

        raise HTTPException(
            status_code=500,
            detail=(
                "No se pudo guardar el borrador de asistentes "
                "de la diligencia."
            ),
        ) from error


@router.get(
    "/proceso/{id_proceso}",
    response_model=list[
        AsistenteDescargoProcesoDisciplinarioResponse
    ],
)
def obtener_asistentes_por_proceso(
    id_proceso: int,
    incluir_inactivos: bool = False,
    db: Session = Depends(get_db),
):
    obtener_proceso_o_error(
        db=db,
        id_proceso=id_proceso,
    )

    consulta = (
        db.query(AsistenteDescargoProcesoDisciplinario)
        .filter(
            AsistenteDescargoProcesoDisciplinario
            .IdProcesoDisciplinario
            == id_proceso
        )
    )

    if not incluir_inactivos:
        consulta = consulta.filter(
            AsistenteDescargoProcesoDisciplinario
            .Activo
            .is_(True)
        )

    return (
        consulta.order_by(
            AsistenteDescargoProcesoDisciplinario
            .IdAsistenteDescargoProcesoDisciplinario
            .asc()
        )
        .all()
    )


@router.get(
    "/descargo/{id_descargo}",
    response_model=list[
        AsistenteDescargoProcesoDisciplinarioResponse
    ],
)
def obtener_asistentes_por_descargo(
    id_descargo: int,
    db: Session = Depends(get_db),
):
    obtener_descargo_o_error(
        db=db,
        id_descargo=id_descargo,
    )

    return (
        db.query(AsistenteDescargoProcesoDisciplinario)
        .filter(
            AsistenteDescargoProcesoDisciplinario
            .IdDescargoProcesoDisciplinario
            == id_descargo
        )
        .filter(
            AsistenteDescargoProcesoDisciplinario
            .Activo
            .is_(True)
        )
        .order_by(
            AsistenteDescargoProcesoDisciplinario
            .IdAsistenteDescargoProcesoDisciplinario
            .asc()
        )
        .all()
    )


@router.put(
    "/{id_asistente}",
    response_model=(
        AsistenteDescargoProcesoDisciplinarioResponse
    ),
)
def actualizar_asistente(
    id_asistente: int,
    data: AsistenteDescargoProcesoDisciplinarioUpdate,
    db: Session = Depends(get_db),
):
    asistente = obtener_asistente_o_error(
        db=db,
        id_asistente=id_asistente,
    )

    proceso = obtener_proceso_o_error(
        db=db,
        id_proceso=asistente.IdProcesoDisciplinario,
    )

    if (
        str(proceso.EstadoProceso or "").strip().upper()
        == "CERRADO"
    ):
        raise HTTPException(
            status_code=409,
            detail=(
                "No se puede modificar el asistente porque "
                "el proceso disciplinario se encuentra cerrado."
            ),
        )

    datos_actualizacion = data.model_dump(
        exclude_unset=True
    )

    if (
        "IdDescargoProcesoDisciplinario"
        in datos_actualizacion
        and datos_actualizacion[
            "IdDescargoProcesoDisciplinario"
        ]
        is not None
    ):
        descargo = obtener_descargo_o_error(
            db=db,
            id_descargo=datos_actualizacion[
                "IdDescargoProcesoDisciplinario"
            ],
        )

        if (
            descargo.IdProcesoDisciplinario
            != asistente.IdProcesoDisciplinario
        ):
            raise HTTPException(
                status_code=409,
                detail=(
                    "El descargo indicado no pertenece "
                    "al proceso del asistente."
                ),
            )

    for campo, valor in datos_actualizacion.items():
        if (
            campo == "NombreAsistente"
            and valor is not None
        ):
            valor = valor.strip() or None

        setattr(asistente, campo, valor)

    asistente.FechaActualizacion = datetime.now()

    try:
        db.commit()
        db.refresh(asistente)

        return asistente

    except SQLAlchemyError as error:
        db.rollback()

        raise HTTPException(
            status_code=500,
            detail=(
                "No se pudo actualizar el asistente "
                "de la diligencia."
            ),
        ) from error