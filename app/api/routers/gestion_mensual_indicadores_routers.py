# ruff: noqa: B008, BLE001

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from infrastructure.db.deps import get_db
from infrastructure.security.auth_dependencies import get_current_user


router = APIRouter(
    prefix="/api/gestion-mensual-indicadores",
    tags=["Gestión Mensual Indicadores"],
)


# Hora oficial usada por el aplicativo para Bogotá, Colombia.
# Colombia opera en UTC-5 durante todo el año.
ZONA_HORARIA_COLOMBIA = timezone(
    timedelta(hours=-5),
    name="America/Bogota",
)


class GestionMensualActualizacion(BaseModel):
    analisisMes: Optional[str] = None
    planAccion: Optional[str] = None


class CalificacionMensualActualizacion(BaseModel):
    calificacionMensual: float = Field(
        ...,
        ge=0,
        le=100,
    )


def _texto_limpio(valor: Optional[str]) -> Optional[str]:
    if valor is None:
        return None

    texto_limpio = str(valor).strip()

    if not texto_limpio:
        return None

    return texto_limpio


def _obtener_usuario(current: Dict[str, Any]) -> str:
    usuario = current.get("usuario")

    nombre_usuario = getattr(
        usuario,
        "NombreUsuario",
        None,
    )

    if nombre_usuario:
        return str(nombre_usuario)

    payload = current.get("payload") or {}

    return str(
        payload.get("sub")
        or "usuario_sistema"
    )


def _es_super_administrador(
    current: Dict[str, Any],
) -> bool:
    roles = {
        str(rol).strip().lower()
        for rol in (current.get("roles") or [])
    }

    roles_ids = {
        int(rol_id)
        for rol_id in (current.get("roles_ids") or [])
        if str(rol_id).isdigit()
    }

    return (
        "super administrador" in roles
        or 5 in roles_ids
    )


def _validar_periodo(
    anio: int,
    mes: int,
) -> None:
    if anio < 2020:
        raise HTTPException(
            status_code=400,
            detail="El año indicado no es válido.",
        )

    if mes < 1 or mes > 12:
        raise HTTPException(
            status_code=400,
            detail="El mes debe estar entre 1 y 12.",
        )


def _obtener_periodo_actual():
    ahora_colombia = datetime.now(
        ZONA_HORARIA_COLOMBIA
    )

    return (
        ahora_colombia.year,
        ahora_colombia.month,
        ahora_colombia,
    )


def _estado_periodo(
    anio: int,
    mes: int,
):
    anio_actual, mes_actual, ahora = (
        _obtener_periodo_actual()
    )

    periodo_consultado = (anio, mes)
    periodo_actual = (
        anio_actual,
        mes_actual,
    )

    return {
        "esPeriodoActual":
            periodo_consultado
            == periodo_actual,
        "esPeriodoAnterior":
            periodo_consultado
            < periodo_actual,
        "esPeriodoFuturo":
            periodo_consultado
            > periodo_actual,
        "fechaActualColombia":
            ahora,
    }


def _obtener_registro(
    db: Session,
    modulo: str,
    codigo_indicador: str,
    anio: int,
    mes: int,
):
    consulta = text(
        """
        SELECT
            "IdGestionMensualIndicador",
            "Modulo",
            "CodigoIndicador",
            "Anio",
            "Mes",
            "AnalisisMes",
            "PlanAccion",
            "CalificacionMensual",
            "UsuarioAnalisis",
            "FechaAnalisis",
            "UsuarioPlanAccion",
            "FechaPlanAccion",
            "UsuarioCalificacion",
            "FechaCalificacion",
            "FechaCreacion",
            "FechaActualizacion"
        FROM public."GestionMensualIndicador"
        WHERE
            "Modulo" = :modulo
            AND "CodigoIndicador" = :codigo_indicador
            AND "Anio" = :anio
            AND "Mes" = :mes
        LIMIT 1
        """
    )

    return (
        db.execute(
            consulta,
            {
                "modulo": modulo,
                "codigo_indicador":
                    codigo_indicador,
                "anio": anio,
                "mes": mes,
            },
        )
        .mappings()
        .first()
    )


def _crear_registro_si_no_existe(
    db: Session,
    modulo: str,
    codigo_indicador: str,
    anio: int,
    mes: int,
):
    consulta = text(
        """
        INSERT INTO public."GestionMensualIndicador"
        (
            "Modulo",
            "CodigoIndicador",
            "Anio",
            "Mes"
        )
        VALUES
        (
            :modulo,
            :codigo_indicador,
            :anio,
            :mes
        )
        ON CONFLICT
        (
            "Modulo",
            "CodigoIndicador",
            "Anio",
            "Mes"
        )
        DO NOTHING
        """
    )

    db.execute(
        consulta,
        {
            "modulo": modulo,
            "codigo_indicador":
                codigo_indicador,
            "anio": anio,
            "mes": mes,
        },
    )


def _construir_respuesta(
    registro,
    anio: int,
    mes: int,
    current: Dict[str, Any],
):
    estado = _estado_periodo(
        anio,
        mes,
    )

    analisis = (
        _texto_limpio(
            registro["AnalisisMes"]
        )
        if registro
        else None
    )

    plan_accion = (
        _texto_limpio(
            registro["PlanAccion"]
        )
        if registro
        else None
    )

    calificacion = (
        registro["CalificacionMensual"]
        if registro
        else None
    )

    es_actual = estado[
        "esPeriodoActual"
    ]

    es_anterior = estado[
        "esPeriodoAnterior"
    ]

    es_futuro = estado[
        "esPeriodoFuturo"
    ]

    puede_editar_analisis = False
    puede_editar_plan = False

    if es_actual:
        puede_editar_analisis = True
        puede_editar_plan = True

    elif es_anterior:
        puede_editar_analisis = (
            analisis is None
        )

        puede_editar_plan = (
            plan_accion is None
        )

    puede_editar_calificacion = False

    if _es_super_administrador(current):
        if es_actual:
            puede_editar_calificacion = True

        elif es_anterior:
            puede_editar_calificacion = (
                calificacion is None
            )

    return {
        "ok": True,
        "periodo": {
            "anio": anio,
            "mes": mes,
            "esPeriodoActual":
                es_actual,
            "esPeriodoAnterior":
                es_anterior,
            "esPeriodoFuturo":
                es_futuro,
        },
        "gestionMensual": {
            "idGestionMensualIndicador": (
                registro[
                    "IdGestionMensualIndicador"
                ]
                if registro
                else None
            ),
            "modulo": (
                registro["Modulo"]
                if registro
                else None
            ),
            "codigoIndicador": (
                registro[
                    "CodigoIndicador"
                ]
                if registro
                else None
            ),
            "analisisMes":
                analisis,
            "planAccion":
                plan_accion,
            "calificacionMensual": (
                float(calificacion)
                if calificacion
                is not None
                else None
            ),
            "usuarioAnalisis": (
                registro[
                    "UsuarioAnalisis"
                ]
                if registro
                else None
            ),
            "fechaAnalisis": (
                registro[
                    "FechaAnalisis"
                ]
                if registro
                else None
            ),
            "usuarioPlanAccion": (
                registro[
                    "UsuarioPlanAccion"
                ]
                if registro
                else None
            ),
            "fechaPlanAccion": (
                registro[
                    "FechaPlanAccion"
                ]
                if registro
                else None
            ),
            "usuarioCalificacion": (
                registro[
                    "UsuarioCalificacion"
                ]
                if registro
                else None
            ),
            "fechaCalificacion": (
                registro[
                    "FechaCalificacion"
                ]
                if registro
                else None
            ),
        },
        "permisos": {
            "puedeEditarAnalisis":
                puede_editar_analisis
                and not es_futuro,
            "puedeEditarPlanAccion":
                puede_editar_plan
                and not es_futuro,
            "calificacionSoloLectura":
                True,
            "puedeEditarCalificacion":
                puede_editar_calificacion
                and not es_futuro,
        },
    }


@router.get(
    "/{modulo}/{codigo_indicador}/{anio}/{mes}"
)
def consultar_gestion_mensual(
    modulo: str,
    codigo_indicador: str,
    anio: int,
    mes: int,
    db: Session = Depends(get_db),
    current: Dict[str, Any] = Depends(
        get_current_user
    ),
):
    _validar_periodo(
        anio,
        mes,
    )

    try:
        registro = _obtener_registro(
            db=db,
            modulo=modulo,
            codigo_indicador=
                codigo_indicador,
            anio=anio,
            mes=mes,
        )

        return _construir_respuesta(
            registro=registro,
            anio=anio,
            mes=mes,
            current=current,
        )

    except SQLAlchemyError as error:
        raise HTTPException(
            status_code=500,
            detail=(
                "No fue posible consultar "
                "la gestión mensual del indicador."
            ),
        ) from error


@router.put(
    "/{modulo}/{codigo_indicador}/{anio}/{mes}/gestion"
)
def actualizar_gestion_mensual(
    modulo: str,
    codigo_indicador: str,
    anio: int,
    mes: int,
    body: GestionMensualActualizacion,
    db: Session = Depends(get_db),
    current: Dict[str, Any] = Depends(
        get_current_user
    ),
):
    _validar_periodo(
        anio,
        mes,
    )

    estado = _estado_periodo(
        anio,
        mes,
    )

    if estado["esPeriodoFuturo"]:
        raise HTTPException(
            status_code=409,
            detail=(
                "No es posible diligenciar "
                "gestión para un periodo futuro."
            ),
        )

    try:
        _crear_registro_si_no_existe(
            db=db,
            modulo=modulo,
            codigo_indicador=
                codigo_indicador,
            anio=anio,
            mes=mes,
        )

        registro = _obtener_registro(
            db=db,
            modulo=modulo,
            codigo_indicador=
                codigo_indicador,
            anio=anio,
            mes=mes,
        )

        if not registro:
            raise HTTPException(
                status_code=500,
                detail=(
                    "No fue posible obtener "
                    "el registro mensual."
                ),
            )

        analisis_actual = _texto_limpio(
            registro["AnalisisMes"]
        )

        plan_actual = _texto_limpio(
            registro["PlanAccion"]
        )

        analisis_nuevo = _texto_limpio(
            body.analisisMes
        )

        plan_nuevo = _texto_limpio(
            body.planAccion
        )

        es_periodo_anterior = estado[
            "esPeriodoAnterior"
        ]

        usuario_actual = _obtener_usuario(
            current
        )

        ahora = estado[
            "fechaActualColombia"
        ]

        cambios = []
        parametros = {
            "id": registro[
                "IdGestionMensualIndicador"
            ],
            "fecha_actualizacion": ahora,
        }

        if body.analisisMes is not None:
            if (
                es_periodo_anterior
                and analisis_actual
                is not None
            ):
                raise HTTPException(
                    status_code=409,
                    detail=(
                        "El análisis del mes "
                        "ya fue diligenciado "
                        "y el periodo está cerrado."
                    ),
                )

            if analisis_nuevo is None:
                raise HTTPException(
                    status_code=400,
                    detail=(
                        "El análisis del mes "
                        "no puede quedar vacío."
                    ),
                )

            cambios.extend(
                [
                    '"AnalisisMes" = :analisis',
                    (
                        '"UsuarioAnalisis" '
                        '= :usuario_analisis'
                    ),
                    (
                        '"FechaAnalisis" '
                        '= :fecha_analisis'
                    ),
                ]
            )

            parametros.update(
                {
                    "analisis":
                        analisis_nuevo,
                    "usuario_analisis":
                        usuario_actual,
                    "fecha_analisis":
                        ahora,
                }
            )

        if body.planAccion is not None:
            if (
                es_periodo_anterior
                and plan_actual is not None
            ):
                raise HTTPException(
                    status_code=409,
                    detail=(
                        "El plan de acción "
                        "ya fue diligenciado "
                        "y el periodo está cerrado."
                    ),
                )

            if plan_nuevo is None:
                raise HTTPException(
                    status_code=400,
                    detail=(
                        "El plan de acción "
                        "no puede quedar vacío."
                    ),
                )

            cambios.extend(
                [
                    '"PlanAccion" = :plan_accion',
                    (
                        '"UsuarioPlanAccion" '
                        '= :usuario_plan'
                    ),
                    (
                        '"FechaPlanAccion" '
                        '= :fecha_plan'
                    ),
                ]
            )

            parametros.update(
                {
                    "plan_accion":
                        plan_nuevo,
                    "usuario_plan":
                        usuario_actual,
                    "fecha_plan":
                        ahora,
                }
            )

        if not cambios:
            raise HTTPException(
                status_code=400,
                detail=(
                    "Debe enviar el análisis "
                    "del mes o el plan de acción."
                ),
            )

        cambios.append(
            '"FechaActualizacion" '
            '= :fecha_actualizacion'
        )

        sentencia = text(
            f"""
            UPDATE public."GestionMensualIndicador"
            SET
                {", ".join(cambios)}
            WHERE
                "IdGestionMensualIndicador"
                = :id
            """
        )

        db.execute(
            sentencia,
            parametros,
        )

        db.commit()

        registro_actualizado = (
            _obtener_registro(
                db=db,
                modulo=modulo,
                codigo_indicador=
                    codigo_indicador,
                anio=anio,
                mes=mes,
            )
        )

        return _construir_respuesta(
            registro=registro_actualizado,
            anio=anio,
            mes=mes,
            current=current,
        )

    except HTTPException:
        db.rollback()
        raise

    except SQLAlchemyError as error:
        db.rollback()

        raise HTTPException(
            status_code=500,
            detail=(
                "No fue posible guardar "
                "la gestión mensual."
            ),
        ) from error


@router.put(
    "/{modulo}/{codigo_indicador}/{anio}/{mes}/calificacion"
)
def actualizar_calificacion_mensual(
    modulo: str,
    codigo_indicador: str,
    anio: int,
    mes: int,
    body: CalificacionMensualActualizacion,
    db: Session = Depends(get_db),
    current: Dict[str, Any] = Depends(
        get_current_user
    ),
):
    _validar_periodo(
        anio,
        mes,
    )

    if not _es_super_administrador(
        current
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                "La calificación mensual "
                "solo puede ser registrada "
                "por Super Administrador."
            ),
        )

    estado = _estado_periodo(
        anio,
        mes,
    )

    if estado["esPeriodoFuturo"]:
        raise HTTPException(
            status_code=409,
            detail=(
                "No es posible calificar "
                "un periodo futuro."
            ),
        )

    try:
        _crear_registro_si_no_existe(
            db=db,
            modulo=modulo,
            codigo_indicador=
                codigo_indicador,
            anio=anio,
            mes=mes,
        )

        registro = _obtener_registro(
            db=db,
            modulo=modulo,
            codigo_indicador=
                codigo_indicador,
            anio=anio,
            mes=mes,
        )

        if not registro:
            raise HTTPException(
                status_code=500,
                detail=(
                    "No fue posible obtener "
                    "el registro mensual."
                ),
            )

        calificacion_actual = registro[
            "CalificacionMensual"
        ]

        if (
            estado["esPeriodoAnterior"]
            and calificacion_actual
            is not None
        ):
            raise HTTPException(
                status_code=409,
                detail=(
                    "La calificación de este "
                    "periodo ya fue registrada "
                    "y quedó bloqueada."
                ),
            )

        usuario_actual = _obtener_usuario(
            current
        )

        ahora = estado[
            "fechaActualColombia"
        ]

        consulta = text(
            """
            UPDATE public."GestionMensualIndicador"
            SET
                "CalificacionMensual"
                    = :calificacion,
                "UsuarioCalificacion"
                    = :usuario,
                "FechaCalificacion"
                    = :fecha,
                "FechaActualizacion"
                    = :fecha
            WHERE
                "IdGestionMensualIndicador"
                    = :id
            """
        )

        db.execute(
            consulta,
            {
                "calificacion":
                    body.calificacionMensual,
                "usuario":
                    usuario_actual,
                "fecha":
                    ahora,
                "id":
                    registro[
                        "IdGestionMensualIndicador"
                    ],
            },
        )

        db.commit()

        registro_actualizado = (
            _obtener_registro(
                db=db,
                modulo=modulo,
                codigo_indicador=
                    codigo_indicador,
                anio=anio,
                mes=mes,
            )
        )

        return _construir_respuesta(
            registro=registro_actualizado,
            anio=anio,
            mes=mes,
            current=current,
        )

    except HTTPException:
        db.rollback()
        raise

    except SQLAlchemyError as error:
        db.rollback()

        raise HTTPException(
            status_code=500,
            detail=(
                "No fue posible guardar "
                "la calificación mensual."
            ),
        ) from error