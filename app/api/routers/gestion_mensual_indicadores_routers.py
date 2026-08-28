# ruff: noqa: B008, BLE001

import json
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

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


class ActividadPlanAccionEntrada(BaseModel):
    idActividad: Optional[int] = Field(
        default=None,
        ge=1,
    )
    actividad: str = Field(
        ...,
        min_length=1,
        max_length=1000,
    )
    fechaCompromiso: date


class GestionMensualActualizacion(BaseModel):
    analisisMes: Optional[str] = None

    # Se conserva por compatibilidad con el frontend anterior.
    # El nuevo frontend debe usar actividadesPlanAccion.
    planAccion: Optional[str] = None

    actividadesPlanAccion: Optional[
        List[ActividadPlanAccionEntrada]
    ] = None


class CalificacionActividadActualizacion(BaseModel):
    calificacion: float = Field(
        ...,
        ge=0,
        le=100,
    )


class CalificacionActividadLoteEntrada(BaseModel):
    idActividad: int = Field(
        ...,
        ge=1,
    )
    calificacion: Optional[float] = Field(
        default=None,
        ge=0,
        le=100,
    )


class CalificacionesActividadesLoteActualizacion(BaseModel):
    actividades: List[CalificacionActividadLoteEntrada]


class CalificacionMensualActualizacion(BaseModel):
    # Se conserva el modelo únicamente para mantener compatibilidad
    # de firma con el endpoint histórico. La calificación mensual
    # ya no se guarda manualmente.
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



def _parsear_plan_accion(
    valor: Optional[str],
) -> tuple[list[dict], Optional[str]]:
    """
    PlanAccion continúa almacenándose en la misma columna existente.

    Para no modificar la estructura de producción, el nuevo plan estructurado
    se serializa como JSON versión 2 dentro de GestionMensualIndicador.PlanAccion.

    Los registros históricos que contengan texto libre siguen siendo válidos
    y se devuelven como plan legacy.
    """
    texto = _texto_limpio(valor)

    if texto is None:
        return [], None

    try:
        data = json.loads(texto)
    except (json.JSONDecodeError, TypeError):
        return [], texto

    if not isinstance(data, dict):
        return [], texto

    if data.get("version") != 2:
        return [], texto

    actividades = data.get("actividades")

    if not isinstance(actividades, list):
        return [], texto

    resultado = []

    for item in actividades:
        if not isinstance(item, dict):
            continue

        try:
            id_actividad = int(
                item.get("idActividad")
            )
        except (TypeError, ValueError):
            continue

        actividad = _texto_limpio(
            item.get("actividad")
        )

        fecha_compromiso = _texto_limpio(
            item.get("fechaCompromiso")
        )

        if (
            actividad is None
            or fecha_compromiso is None
        ):
            continue

        calificacion = item.get(
            "calificacion"
        )

        if calificacion is not None:
            try:
                calificacion = float(
                    calificacion
                )
            except (TypeError, ValueError):
                calificacion = None

        resultado.append(
            {
                "idActividad": id_actividad,
                "actividad": actividad,
                "fechaCompromiso":
                    fecha_compromiso,
                "calificacion":
                    calificacion,
                "usuarioCalificacion":
                    item.get(
                        "usuarioCalificacion"
                    ),
                "fechaCalificacion":
                    item.get(
                        "fechaCalificacion"
                    ),
            }
        )

    return resultado, None


def _serializar_plan_accion(
    actividades: list[dict],
) -> str:
    return json.dumps(
        {
            "version": 2,
            "actividades": actividades,
        },
        ensure_ascii=False,
        separators=(",", ":"),
    )


def _texto_plan_compatible(
    actividades: list[dict],
    plan_legacy: Optional[str],
) -> Optional[str]:
    if plan_legacy is not None:
        return plan_legacy

    if not actividades:
        return None

    return "\\n".join(
        (
            f'{item["actividad"]} '
            f'- {item["fechaCompromiso"]}'
        )
        for item in actividades
    )


def _calcular_resultado_automatico(
    actividades: list[dict],
) -> tuple[Optional[float], int, int]:
    total = len(actividades)

    if total == 0:
        return None, 0, 0

    cantidad_calificadas = sum(
        1
        for item in actividades
        if item.get("calificacion") is not None
    )

    suma = sum(
        float(item.get("calificacion") or 0)
        for item in actividades
    )

    # Regla de negocio:
    # cada actividad comprometida participa en el resultado mensual.
    # Si una actividad no fue calificada al momento de cerrar la evaluación,
    # su aporte es 0 %, pero igualmente permanece en el denominador.
    resultado = round(
        suma / total,
        2,
    )

    return (
        resultado,
        cantidad_calificadas,
        total,
    )


def _construir_actividades_desde_body(
    actividades_body: List[
        ActividadPlanAccionEntrada
    ],
    actividades_actuales: list[dict],
) -> list[dict]:
    cantidad = len(actividades_body)

    if cantidad < 1 or cantidad > 5:
        raise HTTPException(
            status_code=400,
            detail=(
                "El plan de acción debe contener "
                "entre 1 y 5 actividades."
            ),
        )

    actuales_por_id = {
        int(item["idActividad"]): item
        for item in actividades_actuales
        if item.get("idActividad")
        is not None
    }

    ids_usados = set()
    max_id = max(
        actuales_por_id.keys(),
        default=0,
    )

    nuevas = []

    for entrada in actividades_body:
        actividad = _texto_limpio(
            entrada.actividad
        )

        if actividad is None:
            raise HTTPException(
                status_code=400,
                detail=(
                    "La actividad del plan "
                    "no puede quedar vacía."
                ),
            )

        id_actividad = (
            int(entrada.idActividad)
            if entrada.idActividad
            is not None
            else None
        )

        if id_actividad is not None:
            if id_actividad in ids_usados:
                raise HTTPException(
                    status_code=400,
                    detail=(
                        "No se puede repetir "
                        "el id de una actividad."
                    ),
                )

            ids_usados.add(
                id_actividad
            )

        if (
            id_actividad is None
            or id_actividad
            not in actuales_por_id
        ):
            max_id += 1
            id_actividad = max_id

            calificacion = None
            usuario_calificacion = None
            fecha_calificacion = None
        else:
            actual = actuales_por_id[
                id_actividad
            ]

            calificacion = actual.get(
                "calificacion"
            )

            usuario_calificacion = (
                actual.get(
                    "usuarioCalificacion"
                )
            )

            fecha_calificacion = (
                actual.get(
                    "fechaCalificacion"
                )
            )

        nuevas.append(
            {
                "idActividad":
                    id_actividad,
                "actividad":
                    actividad,
                "fechaCompromiso":
                    entrada.fechaCompromiso.isoformat(),
                "calificacion":
                    calificacion,
                "usuarioCalificacion":
                    usuario_calificacion,
                "fechaCalificacion":
                    fecha_calificacion,
            }
        )

    return nuevas


def _actualizar_calificacion_mensual_automatica(
    db: Session,
    id_gestion: int,
    actividades: list[dict],
    usuario_calificacion: Optional[str],
    fecha: datetime,
) -> None:
    (
        resultado,
        cantidad_calificadas,
        total_actividades,
    ) = _calcular_resultado_automatico(
        actividades
    )

    tiene_calificaciones = (
        total_actividades > 0
        and cantidad_calificadas > 0
    )

    consulta = text(
        """
        UPDATE public."GestionMensualIndicador"
        SET
            "CalificacionMensual"
                = :calificacion,
            "UsuarioCalificacion"
                = :usuario,
            "FechaCalificacion"
                = :fecha_calificacion,
            "FechaActualizacion"
                = :fecha_actualizacion
        WHERE
            "IdGestionMensualIndicador"
                = :id
        """
    )

    db.execute(
        consulta,
        {
            "calificacion":
                resultado,
            "usuario": (
                usuario_calificacion
                if tiene_calificaciones
                else None
            ),
            "fecha_calificacion": (
                fecha
                if tiene_calificaciones
                else None
            ),
            "fecha_actualizacion":
                fecha,
            "id":
                id_gestion,
        },
    )


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

    plan_raw = (
        _texto_limpio(
            registro["PlanAccion"]
        )
        if registro
        else None
    )

    (
        actividades,
        plan_legacy,
    ) = _parsear_plan_accion(
        plan_raw
    )

    plan_accion = _texto_plan_compatible(
        actividades,
        plan_legacy,
    )

    (
        resultado_automatico,
        actividades_calificadas,
        total_actividades,
    ) = _calcular_resultado_automatico(
        actividades
    )

    # La fuente oficial del resultado mensual es el cálculo automático.
    # Si el registro todavía es legacy, se conserva el valor histórico
    # únicamente para lectura y no se usa para calificar actividades.
    if actividades:
        calificacion = (
            resultado_automatico
        )
    else:
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
            plan_raw is None
        )

    es_super_admin = (
        _es_super_administrador(
            current
        )
    )

    plan_calificado = (
        actividades_calificadas > 0
    )

    # En el momento en que Super Administrador registra una evaluación,
    # el área deja de poder modificar análisis, actividades o fechas.
    if plan_calificado:
        puede_editar_analisis = False
        puede_editar_plan = False

    puede_calificar_actividades = (
        es_super_admin
        and not es_futuro
        and len(actividades) > 0
    )

    actividades_respuesta = []

    for item in actividades:
        puede_calificar_item = (
            puede_calificar_actividades
            and (
                es_actual
                or item.get(
                    "calificacion"
                )
                is None
            )
        )

        actividades_respuesta.append(
            {
                **item,
                "puedeCalificar":
                    puede_calificar_item,
            }
        )

    calificacion_completa = (
        total_actividades > 0
        and actividades_calificadas
        == total_actividades
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

            # Compatibilidad con el frontend anterior.
            "planAccion":
                plan_accion,

            # Nueva estructura del plan.
            "actividadesPlanAccion":
                actividades_respuesta,
            "planAccionEstructurado":
                bool(actividades),
            "planAccionLegacy":
                plan_legacy is not None,

            "calificacionMensual": (
                float(calificacion)
                if calificacion
                is not None
                else None
            ),
            "calificacionAutomatica":
                bool(actividades),
            "calificacionCompleta":
                calificacion_completa,
            "planCalificado":
                plan_calificado,
            "planCerrado":
                plan_calificado,
            "actividadesCalificadas":
                actividades_calificadas,
            "totalActividades":
                total_actividades,
            "progresoCalificacion": (
                (
                    f"{actividades_calificadas} "
                    f"de {total_actividades} "
                    "actividades calificadas"
                )
                if total_actividades
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
            "calificacionAutomatica":
                True,
            "puedeEditarCalificacion":
                False,
            "puedeCalificarActividades":
                puede_calificar_actividades,
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

        plan_raw_actual = _texto_limpio(
            registro["PlanAccion"]
        )

        (
            actividades_actuales,
            plan_legacy_actual,
        ) = _parsear_plan_accion(
            plan_raw_actual
        )

        plan_ya_calificado = any(
            item.get("calificacion") is not None
            for item in actividades_actuales
        )

        if plan_ya_calificado and (
            body.analisisMes is not None
            or body.actividadesPlanAccion is not None
            or body.planAccion is not None
        ):
            raise HTTPException(
                status_code=409,
                detail=(
                    "La gestión mensual ya fue calificada por "
                    "Super Administrador y quedó cerrada. "
                    "El área ya no puede modificar el análisis, "
                    "las actividades ni las fechas de compromiso."
                ),
            )

        analisis_nuevo = _texto_limpio(
            body.analisisMes
        )

        plan_nuevo_legacy = (
            _texto_limpio(
                body.planAccion
            )
            if body.planAccion
            is not None
            else None
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

        plan_enviado = (
            body.actividadesPlanAccion
            is not None
            or body.planAccion
            is not None
        )

        actividades_nuevas = None
        plan_para_guardar = None

        if plan_enviado:
            if (
                es_periodo_anterior
                and plan_raw_actual
                is not None
            ):
                raise HTTPException(
                    status_code=409,
                    detail=(
                        "El plan de acción "
                        "ya fue diligenciado "
                        "y el periodo está cerrado."
                    ),
                )

            if (
                body.actividadesPlanAccion
                is not None
            ):
                actividades_nuevas = (
                    _construir_actividades_desde_body(
                        body.actividadesPlanAccion,
                        actividades_actuales,
                    )
                )

                plan_para_guardar = (
                    _serializar_plan_accion(
                        actividades_nuevas
                    )
                )

            else:
                if plan_nuevo_legacy is None:
                    raise HTTPException(
                        status_code=400,
                        detail=(
                            "El plan de acción "
                            "no puede quedar vacío."
                        ),
                    )

                # Compatibilidad temporal con el frontend anterior.
                # Un plan en texto sigue pudiendo guardarse, pero no puede
                # ser calificado por actividad hasta migrarse al nuevo formato.
                plan_para_guardar = (
                    plan_nuevo_legacy
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
                        plan_para_guardar,
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

        if actividades_nuevas is not None:
            _actualizar_calificacion_mensual_automatica(
                db=db,
                id_gestion=registro[
                    "IdGestionMensualIndicador"
                ],
                actividades=actividades_nuevas,
                usuario_calificacion=None,
                fecha=ahora,
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
    "/{modulo}/{codigo_indicador}/{anio}/{mes}/actividades/calificaciones"
)
def actualizar_calificaciones_actividades_lote(
    modulo: str,
    codigo_indicador: str,
    anio: int,
    mes: int,
    body: CalificacionesActividadesLoteActualizacion,
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
                "Las calificaciones de actividades "
                "solo pueden ser registradas "
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

    if not body.actividades:
        raise HTTPException(
            status_code=400,
            detail=(
                "Debe enviar al menos una actividad "
                "para guardar las calificaciones."
            ),
        )

    try:
        registro = _obtener_registro(
            db=db,
            modulo=modulo,
            codigo_indicador=codigo_indicador,
            anio=anio,
            mes=mes,
        )

        if not registro:
            raise HTTPException(
                status_code=404,
                detail=(
                    "No existe gestión mensual "
                    "para el periodo consultado."
                ),
            )

        (
            actividades,
            plan_legacy,
        ) = _parsear_plan_accion(
            registro["PlanAccion"]
        )

        if plan_legacy is not None:
            raise HTTPException(
                status_code=409,
                detail=(
                    "El plan de acción de este periodo "
                    "está en formato anterior. Debe "
                    "migrarse a actividades antes de "
                    "poder calificarlo."
                ),
            )

        if not actividades:
            raise HTTPException(
                status_code=409,
                detail=(
                    "El plan de acción todavía no "
                    "tiene actividades para calificar."
                ),
            )

        actividades_por_id = {
            int(item["idActividad"]): item
            for item in actividades
        }

        ids_enviados = set()

        for entrada in body.actividades:
            id_actividad = int(
                entrada.idActividad
            )

            if id_actividad in ids_enviados:
                raise HTTPException(
                    status_code=400,
                    detail=(
                        "No se puede repetir una actividad "
                        "en el mismo guardado."
                    ),
                )

            ids_enviados.add(
                id_actividad
            )

            if id_actividad not in actividades_por_id:
                raise HTTPException(
                    status_code=404,
                    detail=(
                        "Una de las actividades enviadas "
                        "no existe en el plan de acción."
                    ),
                )

        # Para el guardado en bloque se exige recibir todas las
        # actividades del plan. De esta forma el cierre es consistente
        # y las que se dejen sin nota cuentan como 0 %.
        if ids_enviados != set(
            actividades_por_id.keys()
        ):
            raise HTTPException(
                status_code=400,
                detail=(
                    "Debe enviar todas las actividades del plan "
                    "en un único guardado de calificaciones."
                ),
            )

        usuario_actual = _obtener_usuario(
            current
        )

        ahora = estado[
            "fechaActualColombia"
        ]

        for entrada in body.actividades:
            actividad_objetivo = actividades_por_id[
                int(entrada.idActividad)
            ]

            calificacion = (
                round(
                    float(entrada.calificacion),
                    2,
                )
                if entrada.calificacion is not None
                else None
            )

            actividad_objetivo[
                "calificacion"
            ] = calificacion

            actividad_objetivo[
                "usuarioCalificacion"
            ] = (
                usuario_actual
                if calificacion is not None
                else None
            )

            actividad_objetivo[
                "fechaCalificacion"
            ] = (
                ahora.isoformat()
                if calificacion is not None
                else None
            )

        # Debe existir por lo menos una calificación real para cerrar
        # el plan. Las actividades sin calificación se conservan como
        # pendientes y aportan 0 % al resultado automático.
        if not any(
            item.get("calificacion") is not None
            for item in actividades
        ):
            raise HTTPException(
                status_code=400,
                detail=(
                    "Debe registrar al menos una calificación "
                    "antes de cerrar la evaluación."
                ),
            )

        plan_actualizado = (
            _serializar_plan_accion(
                actividades
            )
        )

        consulta = text(
            """
            UPDATE public."GestionMensualIndicador"
            SET
                "PlanAccion" = :plan_accion,
                "FechaActualizacion" = :fecha
            WHERE
                "IdGestionMensualIndicador" = :id
            """
        )

        db.execute(
            consulta,
            {
                "plan_accion":
                    plan_actualizado,
                "fecha":
                    ahora,
                "id":
                    registro[
                        "IdGestionMensualIndicador"
                    ],
            },
        )

        _actualizar_calificacion_mensual_automatica(
            db=db,
            id_gestion=registro[
                "IdGestionMensualIndicador"
            ],
            actividades=actividades,
            usuario_calificacion=
                usuario_actual,
            fecha=ahora,
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
                "las calificaciones de las actividades."
            ),
        ) from error


@router.put(
    "/{modulo}/{codigo_indicador}/{anio}/{mes}/actividades/"
    "{id_actividad}/calificacion"
)
def actualizar_calificacion_actividad(
    modulo: str,
    codigo_indicador: str,
    anio: int,
    mes: int,
    id_actividad: int,
    body: CalificacionActividadActualizacion,
    db: Session = Depends(get_db),
    current: Dict[str, Any] = Depends(
        get_current_user
    ),
):
    _validar_periodo(
        anio,
        mes,
    )

    if id_actividad <= 0:
        raise HTTPException(
            status_code=400,
            detail=(
                "El id de la actividad "
                "no es válido."
            ),
        )

    if not _es_super_administrador(
        current
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                "La calificación de actividades "
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
                status_code=404,
                detail=(
                    "No existe gestión mensual "
                    "para el periodo consultado."
                ),
            )

        (
            actividades,
            plan_legacy,
        ) = _parsear_plan_accion(
            registro["PlanAccion"]
        )

        if plan_legacy is not None:
            raise HTTPException(
                status_code=409,
                detail=(
                    "El plan de acción de este periodo "
                    "está en formato anterior. Debe "
                    "migrarse a actividades antes de "
                    "poder calificarlo."
                ),
            )

        if not actividades:
            raise HTTPException(
                status_code=409,
                detail=(
                    "El plan de acción todavía no "
                    "tiene actividades para calificar."
                ),
            )

        actividad_objetivo = None

        for item in actividades:
            if (
                int(item["idActividad"])
                == id_actividad
            ):
                actividad_objetivo = item
                break

        if actividad_objetivo is None:
            raise HTTPException(
                status_code=404,
                detail=(
                    "La actividad indicada no existe "
                    "en el plan de acción."
                ),
            )

        if (
            estado["esPeriodoAnterior"]
            and actividad_objetivo.get(
                "calificacion"
            )
            is not None
        ):
            raise HTTPException(
                status_code=409,
                detail=(
                    "La calificación de esta actividad "
                    "ya fue registrada y el periodo "
                    "está cerrado."
                ),
            )

        usuario_actual = _obtener_usuario(
            current
        )

        ahora = estado[
            "fechaActualColombia"
        ]

        actividad_objetivo[
            "calificacion"
        ] = round(
            float(body.calificacion),
            2,
        )

        actividad_objetivo[
            "usuarioCalificacion"
        ] = usuario_actual

        actividad_objetivo[
            "fechaCalificacion"
        ] = ahora.isoformat()

        plan_actualizado = (
            _serializar_plan_accion(
                actividades
            )
        )

        consulta = text(
            """
            UPDATE public."GestionMensualIndicador"
            SET
                "PlanAccion"
                    = :plan_accion,
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
                "plan_accion":
                    plan_actualizado,
                "fecha":
                    ahora,
                "id":
                    registro[
                        "IdGestionMensualIndicador"
                    ],
            },
        )

        _actualizar_calificacion_mensual_automatica(
            db=db,
            id_gestion=registro[
                "IdGestionMensualIndicador"
            ],
            actividades=actividades,
            usuario_calificacion=
                usuario_actual,
            fecha=ahora,
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
                "la calificación de la actividad."
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
                "solo puede ser consultada "
                "por el flujo autorizado."
            ),
        )

    # Se conserva la ruta para no provocar un 404 en clientes antiguos,
    # pero ya no permite almacenar una calificación mensual manual.
    raise HTTPException(
        status_code=409,
        detail=(
            "La calificación mensual ahora es automática. "
            "Use el guardado de calificaciones por actividades; "
            "el sistema calculará el resultado mensual "
            "dividiendo entre todas las actividades del plan."
        ),
    )

