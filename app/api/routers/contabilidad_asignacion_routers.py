# ruff: noqa: B008

from datetime import date, datetime, time, timedelta

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from api.routers.contabilidad_centros_costo_routers import _nombre_usuario, require_contabilidad
from infrastructure.db.deps import get_db
from services.contabilidad_horas_service import Horario, calcular_horas_semana

# Ruta propia (no bajo /centros-costo) para no chocar con "/{id_centro}" del
# router de centros de costo.
router = APIRouter(
    prefix="/api/contabilidad/asignaciones",
    tags=["Contabilidad - Asignación de operarios"],
)

SABADO = 6
DOMINGO = 7


# ─────────────────────────────────────────────
# Modelos
# ─────────────────────────────────────────────
class HorarioIn(BaseModel):
    hora_inicio: time
    hora_fin: time
    minutos_desayuno: int = Field(0, ge=0, le=120)
    minutos_almuerzo: int = Field(0, ge=0, le=120)
    minutos_cena: int = Field(0, ge=0, le=120)
    # Hora de inicio de cada descanso (obligatoria si tiene minutos).
    hora_desayuno: time | None = None
    hora_almuerzo: time | None = None
    hora_cena: time | None = None


class LineaIn(BaseModel):
    id_cargo: int
    cantidad_operarios: int = Field(..., ge=1, le=9999)
    codigo_modalidad: str = Field(..., min_length=1, max_length=10)
    horario_general: HorarioIn
    # Solo para modalidades que incluyen sábado (p. ej. medio día).
    horario_sabado: HorarioIn | None = None
    # Solo con domingo a domingo: cada operario descansa un día entre semana.
    descansa_dia_entre_semana: bool = False
    observacion: str | None = Field(None, max_length=500)


class CalculoIn(BaseModel):
    codigo_modalidad: str = Field(..., min_length=1, max_length=10)
    horario_general: HorarioIn
    horario_sabado: HorarioIn | None = None
    descansa_dia_entre_semana: bool = False
    # Fecha para elegir los parámetros legales vigentes (por defecto, hoy).
    fecha: date | None = None


class AsignacionIn(BaseModel):
    # Desde cuándo rige; reemplaza a la asignación vigente (que se finaliza).
    fecha_desde: date
    lineas: list[LineaIn] = Field(..., min_length=1, max_length=50)
    observacion: str | None = Field(None, max_length=500)


class FinalizarIn(BaseModel):
    fecha: date


class HorasOut(BaseModel):
    horas_semana: float
    horas_nocturnas_semana: float
    horas_dominicales_semana: float
    horas_nocturnas_dominicales_semana: float
    horas_maximas_semana: float
    supera_maximo: bool


class ModalidadOut(BaseModel):
    codigo: str
    nombre: str
    dias_semana: list[int]


class CargoOut(BaseModel):
    id: int
    nombre: str


class ParametroOut(BaseModel):
    fecha_desde: date
    hora_inicio_nocturna: time
    hora_fin_nocturna: time
    horas_maximas_semana: float
    porcentaje_recargo_nocturno: float
    porcentaje_recargo_dominical: float


class CatalogosOut(BaseModel):
    modalidades: list[ModalidadOut]
    cargos: list[CargoOut]
    # Parámetros que rigen hoy.
    parametro: ParametroOut


class HorarioOut(HorarioIn):
    pass


class LineaOut(BaseModel):
    id_detalle: int
    id_cargo: int
    cargo: str
    cantidad_operarios: int
    codigo_modalidad: str
    modalidad: str
    descansa_dia_entre_semana: bool
    horario_general: HorarioOut
    horario_sabado: HorarioOut | None = None
    horas_semana: float
    horas_nocturnas_semana: float
    horas_dominicales_semana: float
    horas_nocturnas_dominicales_semana: float
    observacion: str | None = None


class AsignacionOut(BaseModel):
    id_asignacion: int
    fecha_desde: date
    fecha_hasta: date | None = None
    estado: str
    observacion: str | None = None
    creado_por: str | None = None
    fecha_creacion: datetime
    actualizado_por: str | None = None
    total_operarios: int
    lineas: list[LineaOut] = []


class CentroResumenOut(BaseModel):
    id_centro_costo_contable: int
    codigo: str
    cliente: str
    sede: str
    estado: str


class AsignacionCentroOut(BaseModel):
    centro: CentroResumenOut
    # Parámetros legales que rigen hoy (porcentajes de recargo).
    parametro: ParametroOut
    vigente: AsignacionOut | None = None
    # Asignaciones finalizadas, la más reciente primero (sin líneas).
    anteriores: list[AsignacionOut] = []


# ─────────────────────────────────────────────
# Apoyo
# ─────────────────────────────────────────────
def _error(codigo_http: int, detalle: str) -> HTTPException:
    return HTTPException(status_code=codigo_http, detail=detalle)


def _hoy(db: Session) -> date:
    return db.execute(text("SELECT (now() AT TIME ZONE 'America/Bogota')::date")).scalar()


def _parametro(db: Session, fecha: date):
    parametro = db.execute(
        text("""
            SELECT "FechaDesde"                 AS fecha_desde,
                   "HoraInicioNocturna"         AS hora_inicio_nocturna,
                   "HoraFinNocturna"            AS hora_fin_nocturna,
                   "HorasMaximasSemana"         AS horas_maximas_semana,
                   "PorcentajeRecargoNocturno"  AS porcentaje_recargo_nocturno,
                   "PorcentajeRecargoDominical" AS porcentaje_recargo_dominical
            FROM public."ParametroJornadaLaboral"
            WHERE "FechaDesde" <= :fecha
            ORDER BY "FechaDesde" DESC
            LIMIT 1
        """),
        {"fecha": fecha},
    ).mappings().first()

    if not parametro:
        raise _error(
            status.HTTP_400_BAD_REQUEST,
            f"No hay parámetros de jornada laboral vigentes al {fecha:%d/%m/%Y}.",
        )

    return parametro


def _modalidades(db: Session) -> dict[str, dict]:
    filas = db.execute(
        text("""
            SELECT "IdModalidadDias" AS id, "Codigo" AS codigo, "Nombre" AS nombre,
                   "DiasSemana" AS dias_semana
            FROM public."ModalidadDias"
            WHERE "Activo"
        """)
    ).mappings().all()
    return {f["codigo"]: dict(f) for f in filas}


def _horario(entrada: HorarioIn) -> Horario:
    return Horario(
        hora_inicio=entrada.hora_inicio,
        hora_fin=entrada.hora_fin,
        minutos_desayuno=entrada.minutos_desayuno,
        minutos_almuerzo=entrada.minutos_almuerzo,
        minutos_cena=entrada.minutos_cena,
        # Sin minutos, la hora no aplica.
        hora_desayuno=entrada.hora_desayuno if entrada.minutos_desayuno else None,
        hora_almuerzo=entrada.hora_almuerzo if entrada.minutos_almuerzo else None,
        hora_cena=entrada.hora_cena if entrada.minutos_cena else None,
    )


def _calcular(
    modalidad: dict,
    general: HorarioIn,
    sabado: HorarioIn | None,
    descansa_dia_entre_semana: bool,
    parametro,
    etiqueta: str,
):
    if sabado and SABADO not in modalidad["dias_semana"]:
        raise _error(
            status.HTTP_400_BAD_REQUEST,
            f"{etiqueta}: {modalidad['nombre']} no incluye sábado; quita el horario de sábado.",
        )

    if descansa_dia_entre_semana and DOMINGO not in modalidad["dias_semana"]:
        raise _error(
            status.HTTP_400_BAD_REQUEST,
            f"{etiqueta}: el descanso entre semana solo aplica cuando se trabaja de domingo a domingo.",
        )

    try:
        return calcular_horas_semana(
            modalidad["dias_semana"],
            _horario(general),
            _horario(sabado) if sabado else None,
            parametro["hora_inicio_nocturna"],
            parametro["hora_fin_nocturna"],
            descansa_dia_entre_semana,
        )
    except ValueError as error:
        raise _error(status.HTTP_400_BAD_REQUEST, f"{etiqueta}: {error}") from error


def _centro(db: Session, id_centro: int):
    centro = db.execute(
        text("""
            SELECT CC."IdCentroCostoContable" AS id_centro_costo_contable,
                   P."Codigo" || '-' || D."Codigo" || '-' || S."Codigo" || '-' ||
                   L."Codigo" || '-' || SA."Codigo" AS codigo,
                   C."RazonSocial"         AS cliente,
                   S."Descripcion"         AS sede,
                   CC."Estado"             AS estado,
                   CC."FechaApertura"      AS fecha_apertura
            FROM public."CentroCostoContable" CC
            JOIN public."SedeContable" S ON S."IdSedeContable" = CC."IdSedeContable"
            JOIN public."ProyectoContable" P ON P."IdProyectoContable" = S."IdProyectoContable"
            JOIN public."ClienteContable" C ON C."IdClienteContable" = P."IdClienteContable"
            JOIN public."DepartamentoContable" D ON D."IdDepartamentoContable" = CC."IdDepartamentoContable"
            JOIN public."LineaNegocio" L ON L."IdLineaNegocio" = CC."IdLineaNegocio"
            JOIN public."ServicioAsociado" SA ON SA."IdServicioAsociado" = CC."IdServicioAsociado"
            WHERE CC."IdCentroCostoContable" = :id
        """),
        {"id": id_centro},
    ).mappings().first()

    if not centro:
        raise _error(status.HTTP_404_NOT_FOUND, "Centro de costo no encontrado.")

    return centro


def _lineas(db: Session, id_asignacion: int) -> list[dict]:
    filas = db.execute(
        text("""
            SELECT D."IdAsignacionCentroCostoDetalle" AS id_detalle,
                   D."IdCargo"                AS id_cargo,
                   C."NombreCargo"            AS cargo,
                   D."CantidadOperarios"      AS cantidad_operarios,
                   M."Codigo"                 AS codigo_modalidad,
                   M."Nombre"                 AS modalidad,
                   D."DescansaDiaEntreSemana" AS descansa_dia_entre_semana,
                   D."HorasSemana"            AS horas_semana,
                   D."HorasNocturnasSemana"   AS horas_nocturnas_semana,
                   D."HorasDominicalesSemana" AS horas_dominicales_semana,
                   D."HorasNocturnasDominicalesSemana" AS horas_nocturnas_dominicales_semana,
                   D."Observacion"            AS observacion
            FROM public."AsignacionCentroCostoDetalle" D
            JOIN public."Cargo" C ON C."IdCargo" = D."IdCargo"
            JOIN public."ModalidadDias" M ON M."IdModalidadDias" = D."IdModalidadDias"
            WHERE D."IdAsignacionCentroCosto" = :id
            ORDER BY D."IdAsignacionCentroCostoDetalle"
        """),
        {"id": id_asignacion},
    ).mappings().all()

    horarios = db.execute(
        text("""
            SELECT H."IdAsignacionCentroCostoDetalle" AS id_detalle,
                   H."TipoDia"         AS tipo_dia,
                   H."HoraInicio"      AS hora_inicio,
                   H."HoraFin"         AS hora_fin,
                   H."MinutosDesayuno" AS minutos_desayuno,
                   H."MinutosAlmuerzo" AS minutos_almuerzo,
                   H."MinutosCena"     AS minutos_cena,
                   H."HoraDesayuno"    AS hora_desayuno,
                   H."HoraAlmuerzo"    AS hora_almuerzo,
                   H."HoraCena"        AS hora_cena
            FROM public."AsignacionCentroCostoHorario" H
            JOIN public."AsignacionCentroCostoDetalle" D
              ON D."IdAsignacionCentroCostoDetalle" = H."IdAsignacionCentroCostoDetalle"
            WHERE D."IdAsignacionCentroCosto" = :id
        """),
        {"id": id_asignacion},
    ).mappings().all()

    por_linea: dict[int, dict] = {}
    for h in horarios:
        datos = {k: v for k, v in h.items() if k not in ("id_detalle", "tipo_dia")}
        por_linea.setdefault(h["id_detalle"], {})[h["tipo_dia"]] = datos

    return [
        {
            **dict(f),
            "horario_general": por_linea.get(f["id_detalle"], {}).get("GENERAL"),
            "horario_sabado": por_linea.get(f["id_detalle"], {}).get("SABADO"),
        }
        for f in filas
    ]


def _asignaciones(db: Session, id_centro: int) -> list[dict]:
    filas = db.execute(
        text("""
            SELECT A."IdAsignacionCentroCosto" AS id_asignacion,
                   A."FechaDesde"     AS fecha_desde,
                   A."FechaHasta"     AS fecha_hasta,
                   A."Estado"         AS estado,
                   A."Observacion"    AS observacion,
                   A."CreadoPor"      AS creado_por,
                   A."FechaCreacion"  AS fecha_creacion,
                   A."ActualizadoPor" AS actualizado_por,
                   COALESCE((
                       SELECT SUM(D."CantidadOperarios")
                       FROM public."AsignacionCentroCostoDetalle" D
                       WHERE D."IdAsignacionCentroCosto" = A."IdAsignacionCentroCosto"
                   ), 0) AS total_operarios
            FROM public."AsignacionCentroCosto" A
            WHERE A."IdCentroCostoContable" = :id
            ORDER BY A."Estado" = 'VIGENTE' DESC, A."FechaDesde" DESC, A."IdAsignacionCentroCosto" DESC
        """),
        {"id": id_centro},
    ).mappings().all()
    return [dict(f) for f in filas]


def _respuesta(db: Session, id_centro: int) -> dict:
    centro = _centro(db, id_centro)
    asignaciones = _asignaciones(db, id_centro)
    vigente = next((a for a in asignaciones if a["estado"] == "VIGENTE"), None)

    if vigente:
        vigente = {**vigente, "lineas": _lineas(db, vigente["id_asignacion"])}

    return {
        "centro": dict(centro),
        "parametro": dict(_parametro(db, _hoy(db))),
        "vigente": vigente,
        "anteriores": [a for a in asignaciones if a["estado"] != "VIGENTE"],
    }


# ─────────────────────────────────────────────
# Endpoints
# ─────────────────────────────────────────────
@router.get("/catalogos", response_model=CatalogosOut)
def obtener_catalogos(
    db: Session = Depends(get_db),
    _current=Depends(require_contabilidad),
):
    """Modalidades de días, cargos activos (tipo de operario) y parámetros
    legales vigentes hoy."""
    cargos = db.execute(
        text("""
            SELECT "IdCargo" AS id, btrim("NombreCargo") AS nombre
            FROM public."Cargo"
            WHERE "Activo"
            ORDER BY btrim("NombreCargo")
        """)
    ).mappings().all()

    modalidades = sorted(_modalidades(db).values(), key=lambda m: len(m["dias_semana"]))

    return {
        "modalidades": modalidades,
        "cargos": [dict(c) for c in cargos],
        "parametro": dict(_parametro(db, _hoy(db))),
    }


@router.post("/calcular", response_model=HorasOut)
def calcular_horas(
    payload: CalculoIn,
    db: Session = Depends(get_db),
    _current=Depends(require_contabilidad),
):
    """Horas semanales de un horario sin guardar nada (para ver el cálculo en
    pantalla mientras se diligencia)."""
    modalidad = _modalidades(db).get(payload.codigo_modalidad.strip().upper())
    if not modalidad:
        raise _error(status.HTTP_400_BAD_REQUEST, "Modalidad de días no válida.")

    parametro = _parametro(db, payload.fecha or _hoy(db))
    horas = _calcular(
        modalidad,
        payload.horario_general,
        payload.horario_sabado,
        payload.descansa_dia_entre_semana,
        parametro,
        "Horario",
    )
    maximo = float(parametro["horas_maximas_semana"])

    return {
        "horas_semana": horas.horas,
        "horas_nocturnas_semana": horas.nocturnas,
        "horas_dominicales_semana": horas.dominicales,
        "horas_nocturnas_dominicales_semana": horas.nocturnas_dominicales,
        "horas_maximas_semana": maximo,
        "supera_maximo": horas.horas > maximo,
    }


@router.get("/centros/{id_centro}", response_model=AsignacionCentroOut)
def obtener_asignacion(
    id_centro: int,
    db: Session = Depends(get_db),
    _current=Depends(require_contabilidad),
):
    """Asignación vigente del centro (con líneas y horarios) y las anteriores."""
    return _respuesta(db, id_centro)


@router.post(
    "/centros/{id_centro}",
    response_model=AsignacionCentroOut,
    status_code=status.HTTP_201_CREATED,
)
def guardar_asignacion(
    id_centro: int,
    payload: AsignacionIn,
    db: Session = Depends(get_db),
    current=Depends(require_contabilidad),
):
    """Registra la asignación de operarios del centro desde `fecha_desde`. Si ya
    hay una vigente, se finaliza el día anterior (o el mismo día si empieza
    igual) y queda en el historial. Solo para centros ABIERTOS."""
    usuario = _nombre_usuario(current)
    centro = _centro(db, id_centro)

    if centro["estado"] != "ABIERTO":
        raise _error(
            status.HTTP_409_CONFLICT,
            "El centro de costo está cerrado; para asignarle operarios primero debe reabrirse.",
        )

    hoy = _hoy(db)
    if payload.fecha_desde > hoy:
        raise _error(status.HTTP_400_BAD_REQUEST, "La fecha desde no puede ser futura.")

    if centro["fecha_apertura"] and payload.fecha_desde < centro["fecha_apertura"]:
        raise _error(
            status.HTTP_400_BAD_REQUEST,
            f"La fecha desde no puede ser anterior a la apertura del centro ({centro['fecha_apertura']:%d/%m/%Y}).",
        )

    parametro = _parametro(db, payload.fecha_desde)
    maximo = float(parametro["horas_maximas_semana"])
    modalidades = _modalidades(db)
    cargos_activos = set(
        db.execute(text('SELECT "IdCargo" FROM public."Cargo" WHERE "Activo"')).scalars().all()
    )

    lineas = []
    for numero, linea in enumerate(payload.lineas, start=1):
        etiqueta = f"Línea {numero}"
        modalidad = modalidades.get(linea.codigo_modalidad.strip().upper())

        if not modalidad:
            raise _error(status.HTTP_400_BAD_REQUEST, f"{etiqueta}: modalidad de días no válida.")
        if linea.id_cargo not in cargos_activos:
            raise _error(status.HTTP_400_BAD_REQUEST, f"{etiqueta}: el cargo no existe o está inactivo.")

        horas = _calcular(
            modalidad,
            linea.horario_general,
            linea.horario_sabado,
            linea.descansa_dia_entre_semana,
            parametro,
            etiqueta,
        )

        if horas.horas > maximo:
            raise _error(
                status.HTTP_400_BAD_REQUEST,
                f"{etiqueta}: {horas.horas:g} horas semanales superan el máximo de {maximo:g}.",
            )

        lineas.append((linea, modalidad, horas))

    vigente = next((a for a in _asignaciones(db, id_centro) if a["estado"] == "VIGENTE"), None)

    if vigente and payload.fecha_desde < vigente["fecha_desde"]:
        raise _error(
            status.HTTP_400_BAD_REQUEST,
            f"La fecha desde no puede ser anterior a la de la asignación vigente ({vigente['fecha_desde']:%d/%m/%Y}).",
        )

    try:
        db.execute(text("SELECT set_config('app.usuario', :usuario, true)"), {"usuario": usuario})

        if vigente:
            # Hasta el día anterior; si empieza el mismo día, ese mismo día.
            fecha_hasta = max(payload.fecha_desde - timedelta(days=1), vigente["fecha_desde"])
            db.execute(
                text("""
                    UPDATE public."AsignacionCentroCosto"
                    SET "Estado" = 'FINALIZADA', "FechaHasta" = :fecha_hasta,
                        "FechaActualizacion" = now(), "ActualizadoPor" = :usuario
                    WHERE "IdAsignacionCentroCosto" = :id AND "Estado" = 'VIGENTE'
                """),
                {"fecha_hasta": fecha_hasta, "usuario": usuario, "id": vigente["id_asignacion"]},
            )

        id_asignacion = db.execute(
            text("""
                INSERT INTO public."AsignacionCentroCosto"
                    ("IdCentroCostoContable", "FechaDesde", "Observacion", "CreadoPor")
                VALUES (:centro, :fecha_desde, :observacion, :usuario)
                RETURNING "IdAsignacionCentroCosto"
            """),
            {
                "centro": id_centro,
                "fecha_desde": payload.fecha_desde,
                "observacion": (payload.observacion or "").strip() or None,
                "usuario": usuario,
            },
        ).scalar()

        for linea, modalidad, horas in lineas:
            id_detalle = db.execute(
                text("""
                    INSERT INTO public."AsignacionCentroCostoDetalle" (
                        "IdAsignacionCentroCosto", "IdCargo", "CantidadOperarios", "IdModalidadDias",
                        "DescansaDiaEntreSemana", "HorasSemana", "HorasNocturnasSemana",
                        "HorasDominicalesSemana", "HorasNocturnasDominicalesSemana", "Observacion"
                    ) VALUES (
                        :asignacion, :cargo, :cantidad, :modalidad,
                        :descansa, :horas, :nocturnas, :dominicales, :nocturnas_dominicales, :observacion
                    )
                    RETURNING "IdAsignacionCentroCostoDetalle"
                """),
                {
                    "asignacion": id_asignacion,
                    "cargo": linea.id_cargo,
                    "cantidad": linea.cantidad_operarios,
                    "modalidad": modalidad["id"],
                    "descansa": linea.descansa_dia_entre_semana,
                    "horas": horas.horas,
                    "nocturnas": horas.nocturnas,
                    "dominicales": horas.dominicales,
                    "nocturnas_dominicales": horas.nocturnas_dominicales,
                    "observacion": (linea.observacion or "").strip() or None,
                },
            ).scalar()

            for tipo_dia, horario in (("GENERAL", linea.horario_general), ("SABADO", linea.horario_sabado)):
                if horario is None:
                    continue
                db.execute(
                    text("""
                        INSERT INTO public."AsignacionCentroCostoHorario" (
                            "IdAsignacionCentroCostoDetalle", "TipoDia", "HoraInicio", "HoraFin",
                            "MinutosDesayuno", "MinutosAlmuerzo", "MinutosCena",
                            "HoraDesayuno", "HoraAlmuerzo", "HoraCena"
                        ) VALUES (
                            :detalle, :tipo_dia, :inicio, :fin, :desayuno, :almuerzo, :cena,
                            :hora_desayuno, :hora_almuerzo, :hora_cena
                        )
                    """),
                    {
                        "detalle": id_detalle,
                        "tipo_dia": tipo_dia,
                        "inicio": horario.hora_inicio,
                        "fin": horario.hora_fin,
                        "desayuno": horario.minutos_desayuno,
                        "almuerzo": horario.minutos_almuerzo,
                        "cena": horario.minutos_cena,
                        "hora_desayuno": horario.hora_desayuno if horario.minutos_desayuno else None,
                        "hora_almuerzo": horario.hora_almuerzo if horario.minutos_almuerzo else None,
                        "hora_cena": horario.hora_cena if horario.minutos_cena else None,
                    },
                )

        db.commit()
    except IntegrityError as error:
        db.rollback()
        raise _error(
            status.HTTP_409_CONFLICT,
            "La asignación cambió mientras se guardaba (otro usuario o el centro se cerró). Actualiza e intenta de nuevo.",
        ) from error
    except Exception:
        db.rollback()
        raise

    return _respuesta(db, id_centro)


@router.post("/centros/{id_centro}/finalizar", response_model=AsignacionCentroOut)
def finalizar_asignacion(
    id_centro: int,
    payload: FinalizarIn,
    db: Session = Depends(get_db),
    current=Depends(require_contabilidad),
):
    """Finaliza la asignación vigente sin registrar otra (p. ej. el cliente ya
    no requiere operarios aunque el centro siga abierto)."""
    usuario = _nombre_usuario(current)
    _centro(db, id_centro)
    vigente = next((a for a in _asignaciones(db, id_centro) if a["estado"] == "VIGENTE"), None)

    if not vigente:
        raise _error(status.HTTP_409_CONFLICT, "El centro de costo no tiene una asignación vigente.")

    if payload.fecha > _hoy(db):
        raise _error(status.HTTP_400_BAD_REQUEST, "La fecha no puede ser futura.")

    if payload.fecha < vigente["fecha_desde"]:
        raise _error(
            status.HTTP_400_BAD_REQUEST,
            f"La fecha no puede ser anterior al inicio de la asignación ({vigente['fecha_desde']:%d/%m/%Y}).",
        )

    try:
        actualizados = db.execute(
            text("""
                UPDATE public."AsignacionCentroCosto"
                SET "Estado" = 'FINALIZADA', "FechaHasta" = :fecha,
                    "FechaActualizacion" = now(), "ActualizadoPor" = :usuario
                WHERE "IdAsignacionCentroCosto" = :id AND "Estado" = 'VIGENTE'
            """),
            {"fecha": payload.fecha, "usuario": usuario, "id": vigente["id_asignacion"]},
        ).rowcount
        db.commit()
    except Exception:
        db.rollback()
        raise

    if not actualizados:
        raise _error(status.HTTP_409_CONFLICT, "La asignación cambió. Actualiza la consulta.")

    return _respuesta(db, id_centro)
