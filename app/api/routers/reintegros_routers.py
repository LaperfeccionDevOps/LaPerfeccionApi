# app/api/routers/reintegros_routers.py

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from infrastructure.db.deps import get_db


router = APIRouter(
    prefix="/api/reintegros",
    tags=["reintegros"],
)


ESTADO_RETIRADO = 35
ESTADO_RETIRO_CERRADO = "CERRADO"


class IniciarReintegroRequest(BaseModel):
    UsuarioActualizacion: str = Field(
        min_length=1,
        max_length=120,
    )


def _consultar_datos_reintegro(
    db: Session,
    id_registro_personal: int,
):
    trabajador = db.execute(
        text(
            """
            SELECT
                rp."IdRegistroPersonal",
                rp."NumeroIdentificacion",
                rp."Nombres",
                rp."Apellidos",
                rp."IdEstadoProceso"
            FROM public."RegistroPersonal" rp
            WHERE rp."IdRegistroPersonal" = :id_registro_personal
            LIMIT 1;
            """
        ),
        {
            "id_registro_personal": id_registro_personal,
        },
    ).mappings().first()

    if not trabajador:
        raise HTTPException(
            status_code=404,
            detail="No se encontró el trabajador.",
        )

    contratacion = db.execute(
        text(
            """
            SELECT
                cb."IdContratacionBasica",
                cb."FechaIngreso",
                cb."IdTipoContrato"
            FROM public."ContratacionBasica" cb
            WHERE cb."IdRegistroPersonal" = :id_registro_personal
            LIMIT 1;
            """
        ),
        {
            "id_registro_personal": id_registro_personal,
        },
    ).mappings().first()

    asignacion = db.execute(
        text(
            """
            SELECT
                acc."IdAsignacionCargoCliente",
                acc."IdCargo",
                acc."IdCliente",
                acc."Salario"
            FROM public."AsignacionCargoCliente" acc
            WHERE acc."IdRegistroPersonal" = :id_registro_personal
            LIMIT 1;
            """
        ),
        {
            "id_registro_personal": id_registro_personal,
        },
    ).mappings().first()

    retiro = db.execute(
        text(
            """
            SELECT
                rl."IdRetiroLaboral",
                rl."FechaProceso",
                rl."FechaRetiro",
                rl."FechaCierre",
                rl."EstadoCasoRRLL",
                rl."Activo"
            FROM public."RetiroLaboral" rl
            WHERE rl."IdRegistroPersonal" = :id_registro_personal
            ORDER BY
                COALESCE(
                    rl."FechaCierre",
                    rl."FechaActualizacion",
                    rl."FechaCreacion"
                ) DESC,
                rl."IdRetiroLaboral" DESC
            LIMIT 1;
            """
        ),
        {
            "id_registro_personal": id_registro_personal,
        },
    ).mappings().first()

    ciclos = db.execute(
        text(
            """
            SELECT
                vl."IdVinculacionLaboral",
                vl."NumeroCiclo",
                vl."TipoVinculacion",
                vl."EstadoVinculacion",
                vl."FechaInicioProceso",
                vl."FechaIngreso",
                vl."FechaRetiro"
            FROM public."VinculacionLaboral" vl
            WHERE vl."IdRegistroPersonal" = :id_registro_personal
            ORDER BY vl."NumeroCiclo" ASC;
            """
        ),
        {
            "id_registro_personal": id_registro_personal,
        },
    ).mappings().all()

    return {
        "trabajador": trabajador,
        "contratacion": contratacion,
        "asignacion": asignacion,
        "retiro": retiro,
        "ciclos": ciclos,
    }


def _evaluar_reintegro(datos: dict):
    trabajador = datos["trabajador"]
    contratacion = datos["contratacion"]
    asignacion = datos["asignacion"]
    retiro = datos["retiro"]
    ciclos = datos["ciclos"]

    id_estado_actual = trabajador.get("IdEstadoProceso")

    tiene_contratacion_anterior = (
        contratacion is not None
        and contratacion.get("FechaIngreso") is not None
    )

    tiene_asignacion_anterior = asignacion is not None

    retiro_cerrado = (
        retiro is not None
        and str(
            retiro.get("EstadoCasoRRLL") or ""
        ).strip().upper() == ESTADO_RETIRO_CERRADO
        and retiro.get("Activo") is False
        and retiro.get("FechaCierre") is not None
        and retiro.get("FechaRetiro") is not None
    )

    estado_retirado = id_estado_actual == ESTADO_RETIRADO

    total_ciclos = len(ciclos)

    ultimo_ciclo = max(
        (
            int(ciclo.get("NumeroCiclo") or 0)
            for ciclo in ciclos
        ),
        default=0,
    )

    ciclos_abiertos = [
        ciclo
        for ciclo in ciclos
        if ciclo.get("EstadoVinculacion")
        in ("EN_PROCESO", "ACTIVO")
    ]

    tiene_ciclo_abierto = len(ciclos_abiertos) > 0

    requiere_ciclo_historico = (
        total_ciclos == 0
        and tiene_contratacion_anterior
        and tiene_asignacion_anterior
        and retiro_cerrado
    )

    if requiere_ciclo_historico:
        siguiente_ciclo = 2
    else:
        siguiente_ciclo = ultimo_ciclo + 1

    puede_reintegrarse = (
        estado_retirado
        and tiene_contratacion_anterior
        and tiene_asignacion_anterior
        and retiro_cerrado
        and not tiene_ciclo_abierto
    )

    motivos_bloqueo = []

    if not estado_retirado:
        motivos_bloqueo.append(
            "El trabajador no se encuentra en estado 35 - Retirado."
        )

    if not tiene_contratacion_anterior:
        motivos_bloqueo.append(
            "No existe una contratación anterior con fecha de ingreso."
        )

    if not tiene_asignacion_anterior:
        motivos_bloqueo.append(
            "No existe una asignación anterior de cargo y cliente."
        )

    if not retiro_cerrado:
        motivos_bloqueo.append(
            "El último retiro no se encuentra completamente cerrado "
            "o no tiene FechaRetiro registrada."
        )

    if tiene_ciclo_abierto:
        motivos_bloqueo.append(
            "El trabajador ya tiene un ciclo laboral EN_PROCESO o ACTIVO."
        )

    return {
        "estadoRetirado": estado_retirado,
        "tieneContratacionAnterior": tiene_contratacion_anterior,
        "tieneAsignacionAnterior": tiene_asignacion_anterior,
        "retiroCerrado": retiro_cerrado,
        "tieneCicloAbierto": tiene_ciclo_abierto,
        "requiereCicloHistorico": requiere_ciclo_historico,
        "totalCiclos": total_ciclos,
        "ultimoCiclo": ultimo_ciclo,
        "siguienteCiclo": siguiente_ciclo,
        "puedeReintegrarse": puede_reintegrarse,
        "motivosBloqueo": motivos_bloqueo,
    }


@router.get("/validar/{id_registro_personal}")
def validar_reintegro(
    id_registro_personal: int,
    db: Annotated[Session, Depends(get_db)],
):
    """
    Valida si un trabajador puede iniciar un reintegro.

    Este endpoint es solo consulta.
    """

    if id_registro_personal <= 0:
        raise HTTPException(
            status_code=400,
            detail="IdRegistroPersonal no válido.",
        )

    datos = _consultar_datos_reintegro(
        db,
        id_registro_personal,
    )

    evaluacion = _evaluar_reintegro(datos)

    trabajador = datos["trabajador"]
    contratacion = datos["contratacion"]
    asignacion = datos["asignacion"]
    retiro = datos["retiro"]

    mensaje = (
        "El trabajador cumple las condiciones para iniciar "
        "un proceso de reintegro."
        if evaluacion["puedeReintegrarse"]
        else
        "El trabajador no cumple actualmente las condiciones "
        "para iniciar un proceso de reintegro."
    )

    return {
        "ok": True,
        "soloConsulta": True,
        "puedeReintegrarse": evaluacion[
            "puedeReintegrarse"
        ],
        "mensaje": mensaje,

        "trabajador": {
            "IdRegistroPersonal": trabajador.get(
                "IdRegistroPersonal"
            ),
            "NumeroIdentificacion": trabajador.get(
                "NumeroIdentificacion"
            ),
            "Nombres": trabajador.get("Nombres"),
            "Apellidos": trabajador.get("Apellidos"),
            "IdEstadoProceso": trabajador.get(
                "IdEstadoProceso"
            ),
        },

        "validaciones": {
            "estadoRetirado": evaluacion[
                "estadoRetirado"
            ],
            "tieneContratacionAnterior": evaluacion[
                "tieneContratacionAnterior"
            ],
            "tieneAsignacionAnterior": evaluacion[
                "tieneAsignacionAnterior"
            ],
            "retiroCerrado": evaluacion[
                "retiroCerrado"
            ],
            "tieneCicloAbierto": evaluacion[
                "tieneCicloAbierto"
            ],
        },

        "ultimoRetiro": {
            "IdRetiroLaboral": (
                retiro.get("IdRetiroLaboral")
                if retiro
                else None
            ),
            "FechaProceso": (
                retiro.get("FechaProceso")
                if retiro
                else None
            ),
            "FechaRetiro": (
                retiro.get("FechaRetiro")
                if retiro
                else None
            ),
            "FechaCierre": (
                retiro.get("FechaCierre")
                if retiro
                else None
            ),
            "EstadoCasoRRLL": (
                retiro.get("EstadoCasoRRLL")
                if retiro
                else None
            ),
            "Activo": (
                retiro.get("Activo")
                if retiro
                else None
            ),
        },

        "contratacionAnterior": {
            "IdContratacionBasica": (
                contratacion.get(
                    "IdContratacionBasica"
                )
                if contratacion
                else None
            ),
            "FechaIngreso": (
                contratacion.get("FechaIngreso")
                if contratacion
                else None
            ),
            "IdTipoContrato": (
                contratacion.get("IdTipoContrato")
                if contratacion
                else None
            ),
        },

        "asignacionAnterior": {
            "IdAsignacionCargoCliente": (
                asignacion.get(
                    "IdAsignacionCargoCliente"
                )
                if asignacion
                else None
            ),
            "IdCargo": (
                asignacion.get("IdCargo")
                if asignacion
                else None
            ),
            "IdCliente": (
                asignacion.get("IdCliente")
                if asignacion
                else None
            ),
            "Salario": (
                asignacion.get("Salario")
                if asignacion
                else None
            ),
        },

        "ciclosLaborales": {
            "totalCiclos": evaluacion[
                "totalCiclos"
            ],
            "ultimoCiclo": evaluacion[
                "ultimoCiclo"
            ],
            "requiereCicloHistorico": evaluacion[
                "requiereCicloHistorico"
            ],
            "siguienteCicloReintegro": evaluacion[
                "siguienteCiclo"
            ],
        },

        "motivosBloqueo": evaluacion[
            "motivosBloqueo"
        ],
    }


@router.post("/iniciar/{id_registro_personal}")
def iniciar_reintegro(
    id_registro_personal: int,
    body: IniciarReintegroRequest,
    db: Annotated[Session, Depends(get_db)],
):
    """
    Inicia formalmente un nuevo ciclo de reintegro.

    La operación se ejecuta en una sola transacción:
    - preserva el vínculo histórico anterior cuando sea necesario;
    - crea el nuevo ciclo REINTEGRO / EN_PROCESO;
    - mantiene RegistroPersonal en estado 35 mientras el trabajador
      actualiza nuevamente su información en el módulo Aspirante.

    La transición 35 -> 18 se realizará posteriormente, cuando el
    trabajador finalice correctamente la actualización de Aspirante
    y deba pasar nuevamente al flujo de Selección.

    No modifica:
    - RegistroPersonal.IdEstadoProceso;
    - HistorialEstadoContratacion;
    - DatosSeleccion;
    - ContratacionBasica;
    - AsignacionCargoCliente;
    - RetiroLaboral;
    - Synergy;
    - indicadores.
    """

    if id_registro_personal <= 0:
        raise HTTPException(
            status_code=400,
            detail="IdRegistroPersonal no válido.",
        )

    usuario = body.UsuarioActualizacion.strip()

    try:
        # Bloqueo del trabajador durante esta transacción.
        trabajador_bloqueado = db.execute(
            text(
                """
                SELECT
                    rp."IdRegistroPersonal"
                FROM public."RegistroPersonal" rp
                WHERE rp."IdRegistroPersonal"
                    = :id_registro_personal
                FOR UPDATE;
                """
            ),
            {
                "id_registro_personal":
                    id_registro_personal,
            },
        ).mappings().first()

        if not trabajador_bloqueado:
            raise HTTPException(
                status_code=404,
                detail="No se encontró el trabajador.",
            )

        # Bloqueo de ciclos existentes para evitar doble inicio.
        ciclos_bloqueados = db.execute(
            text(
                """
                SELECT
                    vl."IdVinculacionLaboral",
                    vl."NumeroCiclo",
                    vl."EstadoVinculacion"
                FROM public."VinculacionLaboral" vl
                WHERE vl."IdRegistroPersonal"
                    = :id_registro_personal
                ORDER BY vl."NumeroCiclo"
                FOR UPDATE;
                """
            ),
            {
                "id_registro_personal":
                    id_registro_personal,
            },
        ).mappings().all()

        datos = _consultar_datos_reintegro(
            db,
            id_registro_personal,
        )

        # Usamos los ciclos ya bloqueados como fuente definitiva
        # dentro de esta transacción.
        datos["ciclos"] = ciclos_bloqueados

        evaluacion = _evaluar_reintegro(datos)

        if not evaluacion["puedeReintegrarse"]:
            db.rollback()

            raise HTTPException(
                status_code=409,
                detail={
                    "mensaje": (
                        "No es posible iniciar el reintegro."
                    ),
                    "motivos": evaluacion[
                        "motivosBloqueo"
                    ],
                },
            )

        contratacion = datos["contratacion"]
        asignacion = datos["asignacion"]
        retiro = datos["retiro"]

        ciclo_historico = None

        # Cuando VinculacionLaboral aún no tiene información
        # de esta persona, preservamos primero su vínculo anterior.
        if evaluacion["requiereCicloHistorico"]:
            ciclo_historico = db.execute(
                text(
                    """
                    INSERT INTO public."VinculacionLaboral"
                    (
                        "IdRegistroPersonal",
                        "NumeroCiclo",
                        "TipoVinculacion",
                        "EstadoVinculacion",
                        "FechaInicioProceso",
                        "FechaIngreso",
                        "FechaRetiro",
                        "IdCargo",
                        "IdCliente",
                        "Salario",
                        "IdTipoContrato",
                        "FechaCreacion",
                        "FechaActualizacion",
                        "UsuarioActualizacion"
                    )
                    VALUES
                    (
                        :id_registro_personal,
                        1,
                        'NUEVO',
                        'RETIRADO',
                        COALESCE(
                            CAST(:fecha_ingreso AS TIMESTAMPTZ),
                            NOW()
                        ),
                        :fecha_ingreso,
                        :fecha_retiro,
                        :id_cargo,
                        :id_cliente,
                        :salario,
                        :id_tipo_contrato,
                        NOW(),
                        NOW(),
                        :usuario
                    )
                    RETURNING
                        "IdVinculacionLaboral",
                        "IdRegistroPersonal",
                        "NumeroCiclo",
                        "TipoVinculacion",
                        "EstadoVinculacion",
                        "FechaInicioProceso",
                        "FechaIngreso",
                        "FechaRetiro",
                        "IdCargo",
                        "IdCliente",
                        "Salario",
                        "IdTipoContrato",
                        "FechaCreacion",
                        "FechaActualizacion",
                        "UsuarioActualizacion";
                    """
                ),
                {
                    "id_registro_personal":
                        id_registro_personal,
                    "fecha_ingreso":
                        contratacion.get(
                            "FechaIngreso"
                        ),
                    "fecha_retiro":
                        retiro.get("FechaRetiro"),
                    "id_cargo":
                        asignacion.get("IdCargo"),
                    "id_cliente":
                        asignacion.get("IdCliente"),
                    "salario":
                        asignacion.get("Salario"),
                    "id_tipo_contrato":
                        contratacion.get(
                            "IdTipoContrato"
                        ),
                    "usuario": usuario,
                },
            ).mappings().first()

        numero_nuevo_ciclo = evaluacion[
            "siguienteCiclo"
        ]

        nuevo_reintegro = db.execute(
            text(
                """
                INSERT INTO public."VinculacionLaboral"
                (
                    "IdRegistroPersonal",
                    "NumeroCiclo",
                    "TipoVinculacion",
                    "EstadoVinculacion",
                    "FechaInicioProceso",
                    "FechaIngreso",
                    "FechaRetiro",
                    "IdCargo",
                    "IdCliente",
                    "Salario",
                    "IdTipoContrato",
                    "FechaCreacion",
                    "FechaActualizacion",
                    "UsuarioActualizacion"
                )
                VALUES
                (
                    :id_registro_personal,
                    :numero_ciclo,
                    'REINTEGRO',
                    'EN_PROCESO',
                    NOW(),
                    NULL,
                    NULL,
                    NULL,
                    NULL,
                    NULL,
                    NULL,
                    NOW(),
                    NOW(),
                    :usuario
                )
                RETURNING
                    "IdVinculacionLaboral",
                    "IdRegistroPersonal",
                    "NumeroCiclo",
                    "TipoVinculacion",
                    "EstadoVinculacion",
                    "FechaInicioProceso",
                    "FechaIngreso",
                    "FechaRetiro",
                    "IdCargo",
                    "IdCliente",
                    "Salario",
                    "IdTipoContrato",
                    "FechaCreacion",
                    "FechaActualizacion",
                    "UsuarioActualizacion";
                """
            ),
            {
                "id_registro_personal":
                    id_registro_personal,
                "numero_ciclo":
                    numero_nuevo_ciclo,
                "usuario":
                    usuario,
            },
        ).mappings().first()

        # ---------------------------------------------------------
        # El reintegro queda abierto para que el trabajador vuelva
        # al módulo Aspirante y actualice su información.
        #
        # En esta etapa NO se cambia RegistroPersonal de 35 a 18 y
        # NO se registra todavía la transición en el historial.
        # Ese movimiento ocurrirá al finalizar Aspirante.
        # ---------------------------------------------------------

        db.commit()

        return {
            "ok": True,
            "mensaje": (
                "Proceso de reintegro iniciado correctamente. "
                "El trabajador debe actualizar nuevamente su información "
                "en el módulo Aspirante antes de pasar a Selección."
            ),
            "IdRegistroPersonal":
                id_registro_personal,
            "cicloHistoricoCreado":
                ciclo_historico is not None,
            "cicloHistorico": (
                dict(ciclo_historico)
                if ciclo_historico
                else None
            ),
            "nuevoReintegro": (
                dict(nuevo_reintegro)
                if nuevo_reintegro
                else None
            ),
            "requiereActualizarAspirante": True,
            "estadoRegistroPersonalSeMantiene": ESTADO_RETIRADO,
        }

    except HTTPException:
        db.rollback()
        raise

    except SQLAlchemyError as e:
        db.rollback()

        raise HTTPException(
            status_code=500,
            detail=(
                "Error de base de datos iniciando "
                f"el reintegro: {str(e)}"
            ),
        )

    except Exception as e:
        db.rollback()

        raise HTTPException(
            status_code=500,
            detail=(
                "Error inesperado iniciando "
                f"el reintegro: {str(e)}"
            ),
        )