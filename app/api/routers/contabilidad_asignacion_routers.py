# ruff: noqa: B008

import re
from datetime import date, datetime, time, timedelta
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from api.routers.contabilidad_centros_costo_routers import _nombre_usuario, require_contabilidad
from infrastructure.db.deps import get_db
from services import contabilidad_sheets_service
from services.contabilidad_horas_service import NOMBRES_DIA, calcular_horas_turno, resumen_salidas

# Ruta propia (no bajo /centros-costo) para no chocar con "/{id_centro}" del
# router de centros de costo.
router = APIRouter(
    prefix="/api/contabilidad/asignaciones",
    tags=["Contabilidad - Asignación de operarios"],
)

DOMINGO = 7
TipoTurno = Literal["DIURNO", "TARDE", "NOCHE"]
# "19:00" a "24:00" (la medianoche del final del día se escribe 24:00).
PATRON_HORA_FIN = r"^([01][0-9]|2[0-4]):[0-5][0-9]$"


# ─────────────────────────────────────────────
# Modelos
# ─────────────────────────────────────────────
class TurnoIn(BaseModel):
    codigo_modalidad: str = Field(..., min_length=1, max_length=10)
    tipo_turno: TipoTurno
    # Solo en la tarde: hora en que termina el turno ("19:00" a "24:00").
    hora_fin_turno: str | None = Field(None, pattern=PATRON_HORA_FIN)
    # Solo con domingo a domingo: cada operario descansa un día entre semana.
    descansa_dia_entre_semana: bool = False
    # Tarde o noche con domingo: hora a la que termina el domingo si es distinta.
    hora_fin_domingo: str | None = Field(None, pattern=PATRON_HORA_FIN)
    # Solo en la tarde: salida de cada día que labora si cambia según el día
    # ({"1": "20:20", ..., "6": "19:00"}; 1 = lunes ... 7 = domingo).
    salidas_por_dia: dict[int, str] | None = None


class LineaIn(TurnoIn):
    id_cargo: int
    cantidad_operarios: int = Field(..., ge=1, le=9999)
    # Parte del tiempo que cada operario dedica al centro, en decimal
    # (0.3 = 30 %; 1 = tiempo completo; base 24 días hábiles al mes).
    dedicacion: float = Field(1, gt=0, le=1)
    observacion: str | None = Field(None, max_length=500)


class CalculoIn(TurnoIn):
    # Fecha para elegir los parámetros legales vigentes (por defecto, hoy).
    fecha: date | None = None


class AsignacionIn(BaseModel):
    # Desde cuándo rige; reemplaza a la asignación vigente (que se finaliza).
    fecha_desde: date
    lineas: list[LineaIn] = Field(..., min_length=1, max_length=50)
    observacion: str | None = Field(None, max_length=500)


class FinalizarIn(BaseModel):
    fecha: date


class SalidaDiaOut(BaseModel):
    dia: int
    nombre: str
    hora_inicio: str
    hora_fin: str
    horas_nocturnas: float


class HorasOut(BaseModel):
    horas_semana: float
    horas_nocturnas_semana: float
    horas_dominicales_semana: float
    horas_nocturnas_dominicales_semana: float
    horas_maximas_semana: float
    supera_maximo: bool
    # Horas por día trabajado y, en la tarde, la entrada que resulta ("HH:MM").
    horas_dia: float
    hora_inicio_turno: str | None = None
    hora_fin_turno: str | None = None
    hora_inicio_domingo: str | None = None
    hora_fin_domingo: str | None = None
    # Tarde con salida distinta según el día: el detalle de cada día.
    salidas_por_dia: list[SalidaDiaOut] | None = None


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


class HorarioOut(BaseModel):
    # Horario de las asignaciones registradas antes de los tipos de turno.
    hora_inicio: time
    hora_fin: time
    minutos_desayuno: int = 0
    minutos_almuerzo: int = 0
    minutos_cena: int = 0
    hora_desayuno: time | None = None
    hora_almuerzo: time | None = None
    hora_cena: time | None = None


class LineaOut(BaseModel):
    id_detalle: int
    id_cargo: int
    cargo: str
    cantidad_operarios: int
    dedicacion: float = 1
    # Operarios × dedicación: lo que se le carga al centro.
    operarios_equivalentes: float
    codigo_modalidad: str
    modalidad: str
    descansa_dia_entre_semana: bool
    # Vacío en las líneas registradas antes de los tipos de turno.
    tipo_turno: str | None = None
    hora_fin_turno: str | None = None
    hora_inicio_turno: str | None = None
    hora_fin_domingo: str | None = None
    hora_inicio_domingo: str | None = None
    # Tarde con salida distinta según el día: {día: "HH:MM"} y su resumen.
    salidas_por_dia: dict[int, str] | None = None
    resumen_salidas: str | None = None
    horas_dia: float | None = None
    horario_general: HorarioOut | None = None
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
    # Operarios equivalentes (personas × dedicación) y número de personas.
    total_operarios: float
    total_personas: int
    lineas: list[LineaOut] = []


class CentroResumenOut(BaseModel):
    id_centro_costo_contable: int
    codigo: str
    cliente: str
    sede: str
    estado: str
    fecha_inicio_proyecto: date | None = None
    # Línea de negocio y servicio: dan los cargos sugeridos.
    cen4: str | None = None
    cen5: str | None = None


class CargosSugeridosOut(BaseModel):
    # Cargos activos de la combinación CEN4 + CEN5 (vacía: se muestran todos).
    ids: list[int]


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


def _texto_hora(minutos: int | None) -> str | None:
    """1290 -> "21:30"; 1440 -> "24:00"."""
    if minutos is None:
        return None
    return f"{minutos // 60:02d}:{minutos % 60:02d}"


def _minuto_fin(hora_fin_turno: str | None) -> int | None:
    if not hora_fin_turno:
        return None
    horas, minutos = (int(x) for x in hora_fin_turno.split(":"))
    return horas * 60 + minutos


def _minutos_por_dia(turno: TurnoIn, etiqueta: str) -> dict[int, int] | None:
    """{"1": "20:20"} -> {1: 1220}; valida el día y el formato de la hora."""
    if turno.salidas_por_dia is None:
        return None
    minutos = {}
    for dia, hora in turno.salidas_por_dia.items():
        if dia not in NOMBRES_DIA or not re.fullmatch(PATRON_HORA_FIN, hora or ""):
            raise _error(status.HTTP_400_BAD_REQUEST, f"{etiqueta}: salida por día no válida ({dia}: {hora}).")
        minutos[dia] = _minuto_fin(hora)
    return minutos


def _arreglo_por_dia(minutos: dict[int, int] | None) -> list[int | None] | None:
    """{1: 1220, 6: 1140} -> [1220, None, None, None, None, 1140, None] (lunes a domingo)."""
    if minutos is None:
        return None
    return [minutos.get(dia) for dia in range(1, 8)]


def _calcular(modalidad: dict, turno: TurnoIn, parametro, etiqueta: str):
    if turno.descansa_dia_entre_semana and DOMINGO not in modalidad["dias_semana"]:
        raise _error(
            status.HTTP_400_BAD_REQUEST,
            f"{etiqueta}: el descanso entre semana solo aplica cuando se trabaja de domingo a domingo.",
        )
    minutos_dia = _minutos_por_dia(turno, etiqueta)

    try:
        return calcular_horas_turno(
            turno.tipo_turno,
            modalidad["dias_semana"],
            float(parametro["horas_maximas_semana"]),
            parametro["hora_inicio_nocturna"],
            _minuto_fin(turno.hora_fin_turno),
            turno.descansa_dia_entre_semana,
            _minuto_fin(turno.hora_fin_domingo),
            parametro["hora_fin_nocturna"],
            minutos_dia,
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
                   CC."FechaApertura"      AS fecha_apertura,
                   CC."FechaInicioProyecto" AS fecha_inicio_proyecto,
                   L."Codigo"              AS cen4,
                   SA."Codigo"             AS cen5
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
                   D."Dedicacion"             AS dedicacion,
                   ROUND(D."CantidadOperarios" * D."Dedicacion", 2) AS operarios_equivalentes,
                   M."Codigo"                 AS codigo_modalidad,
                   M."Nombre"                 AS modalidad,
                   D."DescansaDiaEntreSemana" AS descansa_dia_entre_semana,
                   D."TipoTurno"              AS tipo_turno,
                   D."MinutoFinTurno"         AS minuto_fin_turno,
                   D."MinutoFinDomingo"       AS minuto_fin_domingo,
                   D."MinutosFinPorDia"       AS minutos_por_dia,
                   M."DiasSemana"             AS dias_semana,
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

    def turno(f) -> dict:
        # Horas por día y entrada de la tarde, a partir de lo guardado.
        if not f["tipo_turno"]:
            return {}
        dias = len(f["dias_semana"]) - (1 if f["descansa_dia_entre_semana"] else 0)
        minutos_dia = float(f["horas_semana"]) * 60 / dias
        fin = f["minuto_fin_turno"]
        domingo = f["minuto_fin_domingo"]
        por_dia = (
            {dia: minutos for dia, minutos in enumerate(f["minutos_por_dia"], start=1) if minutos is not None}
            if f["minutos_por_dia"]
            else None
        )
        return {
            "salidas_por_dia": {d: _texto_hora(m) for d, m in por_dia.items()} if por_dia else None,
            "resumen_salidas": resumen_salidas(por_dia, minutos_dia) if por_dia else None,
            "horas_dia": round(minutos_dia / 60, 2),
            "hora_fin_turno": _texto_hora(fin),
            "hora_inicio_turno": _texto_hora(round(fin - minutos_dia)) if fin is not None else None,
            "hora_fin_domingo": _texto_hora(domingo),
            "hora_inicio_domingo": _texto_hora(round(domingo - minutos_dia)) if domingo is not None else None,
        }

    return [
        {
            **{k: v for k, v in f.items() if k not in ("minuto_fin_turno", "minuto_fin_domingo", "minutos_por_dia", "dias_semana")},
            **turno(f),
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
                       SELECT ROUND(SUM(D."CantidadOperarios" * D."Dedicacion"), 2)
                       FROM public."AsignacionCentroCostoDetalle" D
                       WHERE D."IdAsignacionCentroCosto" = A."IdAsignacionCentroCosto"
                   ), 0) AS total_operarios,
                   COALESCE((
                       SELECT SUM(D."CantidadOperarios")
                       FROM public."AsignacionCentroCostoDetalle" D
                       WHERE D."IdAsignacionCentroCosto" = A."IdAsignacionCentroCosto"
                   ), 0) AS total_personas
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


@router.get("/cargos-sugeridos", response_model=CargosSugeridosOut)
def obtener_cargos_sugeridos(
    cen4: str = Query(..., min_length=1, max_length=20),
    cen5: str = Query(..., min_length=1, max_length=20),
    db: Session = Depends(get_db),
    _current=Depends(require_contabilidad),
):
    """Cargos activos que se sugieren para la combinación CEN4 + CEN5: los de la
    lista inicial de Contabilidad siempre, y los aprendidos de las asignaciones
    solo mientras algún centro ABIERTO de la combinación los tenga en su
    asignación vigente (así un cargo puesto por error deja de sugerirse al
    corregir o finalizar la asignación; la fila queda como historial).
    Una combinación nueva o sin registros devuelve la lista vacía."""
    ids = db.execute(
        text("""
            SELECT S."IdCargo"
            FROM public."CargoSugeridoLineaServicio" S
            JOIN public."LineaNegocio" L ON L."IdLineaNegocio" = S."IdLineaNegocio"
            JOIN public."ServicioAsociado" SA ON SA."IdServicioAsociado" = S."IdServicioAsociado"
            JOIN public."Cargo" C ON C."IdCargo" = S."IdCargo"
            WHERE upper(L."Codigo") = upper(:cen4)
              AND upper(SA."Codigo") = upper(:cen5)
              AND C."Activo"
              AND (
                  S."Origen" = 'LISTA_INICIAL'
                  OR EXISTS (
                      SELECT 1
                      FROM public."AsignacionCentroCosto" A
                      JOIN public."AsignacionCentroCostoDetalle" D
                        ON D."IdAsignacionCentroCosto" = A."IdAsignacionCentroCosto"
                      JOIN public."CentroCostoContable" CC
                        ON CC."IdCentroCostoContable" = A."IdCentroCostoContable"
                      WHERE A."Estado" = 'VIGENTE'
                        AND CC."Estado" = 'ABIERTO'
                        AND CC."IdLineaNegocio" = S."IdLineaNegocio"
                        AND CC."IdServicioAsociado" = S."IdServicioAsociado"
                        AND D."IdCargo" = S."IdCargo"
                  )
              )
            ORDER BY btrim(C."NombreCargo")
        """),
        {"cen4": cen4.strip(), "cen5": cen5.strip()},
    ).scalars().all()

    return {"ids": list(ids)}


@router.post("/calcular", response_model=HorasOut)
def calcular_horas(
    payload: CalculoIn,
    db: Session = Depends(get_db),
    _current=Depends(require_contabilidad),
):
    """Horas semanales de un turno sin guardar nada (para ver el cálculo en
    pantalla mientras se diligencia)."""
    modalidad = _modalidades(db).get(payload.codigo_modalidad.strip().upper())
    if not modalidad:
        raise _error(status.HTTP_400_BAD_REQUEST, "Modalidad de días no válida.")

    parametro = _parametro(db, payload.fecha or _hoy(db))
    horas = _calcular(modalidad, payload, parametro, "Turno")
    maximo = float(parametro["horas_maximas_semana"])

    return {
        "horas_semana": horas.horas,
        "horas_nocturnas_semana": horas.nocturnas,
        "horas_dominicales_semana": horas.dominicales,
        "horas_nocturnas_dominicales_semana": horas.nocturnas_dominicales,
        "horas_maximas_semana": maximo,
        "supera_maximo": horas.horas > maximo,
        "horas_dia": horas.horas_dia,
        "hora_inicio_turno": _texto_hora(horas.minuto_entrada),
        "hora_fin_turno": payload.hora_fin_turno if payload.tipo_turno == "TARDE" else None,
        "hora_inicio_domingo": _texto_hora(horas.minuto_entrada_domingo),
        "hora_fin_domingo": payload.hora_fin_domingo,
        "salidas_por_dia": (
            [
                {
                    "dia": dia,
                    "nombre": NOMBRES_DIA[dia],
                    "hora_inicio": _texto_hora(round(_minuto_fin(payload.salidas_por_dia[dia]) - horas.horas_dia * 60)),
                    "hora_fin": payload.salidas_por_dia[dia],
                    "horas_nocturnas": round(nocturnos / 60, 2),
                }
                for dia, nocturnos in sorted(horas.minutos_nocturnos_dia.items())
            ]
            if horas.minutos_nocturnos_dia is not None
            else None
        ),
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
    # Un centro por iniciar se puede asignar desde la fecha de inicio del proyecto.
    fecha_maxima = max(hoy, centro["fecha_inicio_proyecto"] or hoy)
    if payload.fecha_desde > fecha_maxima:
        raise _error(
            status.HTTP_400_BAD_REQUEST,
            "La fecha desde no puede ser futura."
            if fecha_maxima == hoy
            else f"La fecha desde no puede ser posterior al inicio del proyecto ({fecha_maxima:%d/%m/%Y}).",
        )

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

        horas = _calcular(modalidad, linea, parametro, etiqueta)

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
            db.execute(
                text("""
                    INSERT INTO public."AsignacionCentroCostoDetalle" (
                        "IdAsignacionCentroCosto", "IdCargo", "CantidadOperarios", "Dedicacion", "IdModalidadDias",
                        "DescansaDiaEntreSemana", "TipoTurno", "MinutoFinTurno", "MinutoFinDomingo", "MinutosFinPorDia",
                        "HorasSemana", "HorasNocturnasSemana",
                        "HorasDominicalesSemana", "HorasNocturnasDominicalesSemana", "Observacion"
                    ) VALUES (
                        :asignacion, :cargo, :cantidad, :dedicacion, :modalidad,
                        :descansa, :tipo_turno, :minuto_fin, :minuto_fin_domingo, :minutos_por_dia,
                        :horas, :nocturnas, :dominicales, :nocturnas_dominicales, :observacion
                    )
                """),
                {
                    "asignacion": id_asignacion,
                    "cargo": linea.id_cargo,
                    "cantidad": linea.cantidad_operarios,
                    "dedicacion": round(linea.dedicacion, 4),
                    "modalidad": modalidad["id"],
                    "descansa": linea.descansa_dia_entre_semana,
                    "tipo_turno": linea.tipo_turno,
                    "minuto_fin": _minuto_fin(linea.hora_fin_turno) if linea.tipo_turno == "TARDE" else None,
                    "minuto_fin_domingo": _minuto_fin(linea.hora_fin_domingo),
                    "minutos_por_dia": _arreglo_por_dia(_minutos_por_dia(linea, "")),
                    "horas": horas.horas,
                    "nocturnas": horas.nocturnas,
                    "dominicales": horas.dominicales,
                    "nocturnas_dominicales": horas.nocturnas_dominicales,
                    "observacion": (linea.observacion or "").strip() or None,
                },
            )

        # Cada cargo usado queda como sugerido de la combinación CEN4 + CEN5
        # del centro (si es nuevo se agrega; si ya estaba, suma un uso).
        for id_cargo in sorted({linea.id_cargo for linea, _, _ in lineas}):
            db.execute(
                text("""
                    INSERT INTO public."CargoSugeridoLineaServicio" AS S (
                        "IdLineaNegocio", "IdServicioAsociado", "IdCargo",
                        "Origen", "VecesAsignado", "FechaUltimaAsignacion", "CreadoPor"
                    )
                    SELECT CC."IdLineaNegocio", CC."IdServicioAsociado", :cargo,
                           'ASIGNACION', 1, now(), :usuario
                    FROM public."CentroCostoContable" CC
                    WHERE CC."IdCentroCostoContable" = :centro
                    ON CONFLICT ("IdLineaNegocio", "IdServicioAsociado", "IdCargo") DO UPDATE
                    SET "VecesAsignado" = S."VecesAsignado" + 1,
                        "FechaUltimaAsignacion" = now()
                """),
                {"cargo": id_cargo, "usuario": usuario, "centro": id_centro},
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

    respuesta = _respuesta(db, id_centro)
    contabilidad_sheets_service.programar_sincronizacion(usuario, f"Asignación del centro {id_centro}")
    return respuesta


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

    respuesta = _respuesta(db, id_centro)
    contabilidad_sheets_service.programar_sincronizacion(usuario, f"Fin de la asignación del centro {id_centro}")
    return respuesta
