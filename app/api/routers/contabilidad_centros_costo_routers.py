# ruff: noqa: B008

import re
from io import BytesIO
import unicodedata
from datetime import date, datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Path, Query, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from infrastructure.db.deps import get_db
from infrastructure.security.auth_dependencies import get_current_user
from services import contabilidad_sheets_service
from services.contabilidad_horas_service import DOMINGO, resumen_salidas


router = APIRouter(
    prefix="/api/contabilidad/centros-costo",
    tags=["Contabilidad - Centros de costo"],
)

ROL_ADMIN = 1
ROL_SUPER_ADMIN = 5
ROL_CONTABILIDAD = 7
ROL_DESARROLLADOR = 15

ROLES_PERMITIDOS = {ROL_ADMIN, ROL_SUPER_ADMIN, ROL_CONTABILIDAD, ROL_DESARROLLADOR}

TAMANO_PAGINA_MAXIMO = 200


def require_contabilidad(current=Depends(get_current_user)):
    roles_ids = {
        int(id_rol)
        for id_rol in (current.get("roles_ids") or [])
        if str(id_rol).strip()
    }

    if roles_ids & ROLES_PERMITIDOS:
        return current

    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="No tienes permiso para gestionar los centros de costo.",
    )


# ─────────────────────────────────────────────
# Modelos
# ─────────────────────────────────────────────
class OpcionFiltroOut(BaseModel):
    id: int
    codigo: str
    nombre: str


class ProyectoFiltroOut(OpcionFiltroOut):
    nit: str
    cliente: str
    codigo_socio_negocio: str | None = None


class DepartamentoFiltroOut(OpcionFiltroOut):
    # Ubicación del CEN 2: departamento de Colombia (DANE) y municipio, si aplica.
    id_departamento_geografico: int | None = None
    codigo_dane: str | None = None
    departamento_geografico: str | None = None
    id_municipio: int | None = None
    municipio: str | None = None


class SedeFiltroOut(OpcionFiltroOut):
    # Para limitar las sedes al proyecto elegido en el filtro de CEN 1.
    id_proyecto: int
    # Centros de la sede y cuántos están abiertos (abierta = al menos uno).
    centros: int = 0
    abiertos: int = 0


class ServicioFiltroOut(OpcionFiltroOut):
    # Líneas de negocio (CEN 4) con las que ya se usa: código -> centros.
    lineas: dict[str, int] = {}


class FiltrosCentrosCostoOut(BaseModel):
    proyectos: list[ProyectoFiltroOut]
    departamentos: list[DepartamentoFiltroOut]
    sedes: list[SedeFiltroOut]
    lineas: list[OpcionFiltroOut]
    servicios: list[ServicioFiltroOut]


class DepartamentoGeograficoOut(BaseModel):
    id: int
    codigo_dane: str
    nombre: str


class MunicipioOut(BaseModel):
    id: int
    nombre: str


class SedeProyectoOut(BaseModel):
    id: int
    codigo: str
    descripcion: str
    # Códigos CEN 2 donde la sede ya tiene centros de costo.
    departamentos: list[str]
    # Líneas de negocio (CEN 4) de la sede: código -> cantidad de centros.
    lineas: dict[str, int]
    centros: int
    abiertos: int


class CombinacionOut(BaseModel):
    # Si la combinación CEN 2 a CEN 5 ya existe (el CEN 1 va implícito en la sede).
    existe: bool
    id_centro_costo_contable: int | None = None
    codigo: str | None = None
    estado: str | None = None
    pendiente_revision: bool | None = None


class CodigoSedeOut(BaseModel):
    codigo: str
    disponible: bool
    # Si ya existe: a qué proyecto pertenece y su descripción.
    codigo_proyecto: str | None = None
    descripcion: str | None = None


class CentroCostoOut(BaseModel):
    id_centro_costo_contable: int
    # Código completo de Synergy: CEN1-CEN2-CEN3-CEN4-CEN5.
    codigo: str
    nit: str
    cliente: str
    id_proyecto: int
    codigo_proyecto: str
    proyecto: str
    id_departamento: int
    codigo_departamento: str
    departamento: str
    codigo_sede: str
    sede: str
    id_linea: int
    codigo_linea: str
    linea: str
    id_servicio: int
    codigo_servicio: str
    servicio: str
    estado: str
    # Etapa según las fechas del proyecto: POR_INICIAR, EN_EJECUCION,
    # FIN_VENCIDO (abiertos) o CERRADO.
    etapa: str
    fecha_apertura: date | None = None
    fecha_cierre: date | None = None
    fecha_inicio_proyecto: date | None = None
    fecha_fin_proyecto: date | None = None
    pendiente_revision: bool
    observacion_revision: str | None = None
    fecha_creacion: datetime
    # Operarios equivalentes de la asignación vigente (personas × dedicación;
    # 0 si no tiene).
    operarios: float = 0


class CantidadOut(BaseModel):
    nombre: str
    operarios: float


class ResumenAsignacionOut(BaseModel):
    # Sobre los centros del resultado filtrado, con su asignación vigente.
    centros_con_asignacion: int
    abiertos_sin_asignacion: int
    # Operarios equivalentes (personas × dedicación) y número de personas.
    operarios: float
    personas: int = 0
    operarios_con_nocturnas: float
    operarios_con_dominicales: float
    operarios_con_nocturnas_dominicales: float
    # Suma semanal de todos los operarios (equivalentes × horas por operario).
    horas_nocturnas_semana: float
    horas_dominicales_semana: float
    horas_nocturnas_dominicales_semana: float
    por_cargo: list[CantidadOut]
    por_modalidad: list[CantidadOut]


class ResumenEstadosOut(BaseModel):
    total: int
    abiertos: int
    cerrados: int
    pendientes_revision: int
    # Abiertos que aún no inician y abiertos con la fecha de fin ya pasada.
    por_iniciar: int
    fin_vencido: int
    asignacion: ResumenAsignacionOut


class OpcionesDisponiblesOut(BaseModel):
    # Por filtro: valor -> cantidad de centros, aplicando todos los demás
    # filtros (no el propio), para que cada filtro muestre solo lo que da resultado.
    proyectos: dict[str, int]
    departamentos: dict[str, int]
    sedes: dict[str, int]
    lineas: dict[str, int]
    servicios: dict[str, int]
    estados: dict[str, int]
    revision: dict[str, int]


class ConsultaCentrosCostoOut(BaseModel):
    total: int
    pagina: int
    tamano_pagina: int
    # Conteos de todo el resultado filtrado (no solo de la página).
    resumen: ResumenEstadosOut
    disponibles: OpcionesDisponiblesOut
    centros: list[CentroCostoOut]


class MovimientoHistorialOut(BaseModel):
    id_historial_centro_costo: int
    accion: str
    estado_anterior: str | None = None
    estado_nuevo: str
    # Cuándo ocurrió realmente y cuándo se registró en el sistema.
    fecha_efectiva: date | None = None
    fecha_registro: datetime
    motivo: str | None = None
    detalle: str | None = None
    usuario: str


class CentroCostoDetalleOut(CentroCostoOut):
    codigo_socio_negocio: str | None = None
    creado_por: str | None = None
    fecha_actualizacion: datetime | None = None
    actualizado_por: str | None = None
    historial: list[MovimientoHistorialOut] = []


class ProyectoNuevoIn(BaseModel):
    # Cliente (NIT con dígito de verificación) y su proyecto (CEN 1). El nombre
    # del proyecto es la misma razón social.
    nit: str = Field(..., pattern=r"^[0-9]{5,15}-[0-9]$")
    razon_social: str = Field(..., min_length=1, max_length=200)
    codigo: str = Field(..., min_length=1, max_length=20)
    # Código del socio de negocio del cliente en Synergy.
    codigo_socio_negocio: str = Field(..., min_length=1, max_length=30)


class CatalogoIn(BaseModel):
    # Opción existente (solo el código) o nueva (`nuevo` con su nombre).
    codigo: str = Field(..., min_length=1, max_length=20)
    nombre: str | None = Field(None, max_length=200)
    nuevo: bool = False


class DepartamentoIn(CatalogoIn):
    # Ubicación, obligatoria para un CEN 2 nuevo; el municipio es opcional.
    id_departamento_geografico: int | None = None
    id_municipio: int | None = None


class SedeIn(BaseModel):
    codigo: str = Field(..., min_length=1, max_length=20)
    descripcion: str | None = Field(None, max_length=300)
    nuevo: bool = False


class CrearCentroCostoIn(BaseModel):
    # Proyecto existente (código CEN 1) o cliente y proyecto nuevos; uno de los dos.
    proyecto_codigo: str | None = Field(None, max_length=20)
    proyecto_nuevo: ProyectoNuevoIn | None = None
    departamento: DepartamentoIn
    sede: SedeIn
    linea: CatalogoIn
    servicio: CatalogoIn
    # Proyección del inicio (puede ser anterior a hoy) y fin opcional.
    fecha_inicio_proyecto: date
    fecha_fin_proyecto: date | None = None
    # Opcional; queda como motivo del registro CREADO en el historial.
    observacion: str | None = Field(None, max_length=500)


class FechasProyectoIn(BaseModel):
    fecha_inicio_proyecto: date
    # Vacía: sin fecha de fin pactada.
    fecha_fin_proyecto: date | None = None
    motivo: str = Field(..., max_length=500)


class CambioEstadoIn(BaseModel):
    # Fecha efectiva del cierre o de la reapertura (no puede ser futura).
    fecha: date
    motivo: str = Field(..., max_length=500)


# ─────────────────────────────────────────────
# Filtros
# ─────────────────────────────────────────────
@router.get("/filtros", response_model=FiltrosCentrosCostoOut)
def obtener_filtros(
    db: Session = Depends(get_db),
    _current=Depends(require_contabilidad),
):
    """Listas para los filtros de la consulta: proyectos (con su cliente),
    departamentos, líneas de negocio y servicios asociados."""
    proyectos = db.execute(
        text("""
            SELECT P."IdProyectoContable" AS id,
                   P."Codigo"             AS codigo,
                   P."Nombre"             AS nombre,
                   C."Nit"                AS nit,
                   C."RazonSocial"        AS cliente,
                   C."CodigoSocioNegocio" AS codigo_socio_negocio
            FROM public."ProyectoContable" P
            JOIN public."ClienteContable" C
              ON C."IdClienteContable" = P."IdClienteContable"
            ORDER BY P."Nombre", P."Codigo"
        """)
    ).mappings().all()

    def catalogo(tabla: str, columna_id: str) -> list[dict]:
        filas = db.execute(
            text(f"""
                SELECT "{columna_id}" AS id, "Codigo" AS codigo, "Nombre" AS nombre
                FROM public."{tabla}"
                ORDER BY "Codigo"
            """)
        ).mappings().all()
        return [dict(f) for f in filas]

    departamentos = db.execute(
        text("""
            SELECT D."IdDepartamentoContable"    AS id,
                   D."Codigo"                    AS codigo,
                   D."Nombre"                    AS nombre,
                   DG."IdDepartamentoGeografico" AS id_departamento_geografico,
                   DG."CodigoDane"               AS codigo_dane,
                   DG."Nombre"                   AS departamento_geografico,
                   LN."IdLugarNacimiento"        AS id_municipio,
                   LN."Nombre"                   AS municipio
            FROM public."DepartamentoContable" D
            LEFT JOIN public."DepartamentoGeografico" DG
              ON DG."IdDepartamentoGeografico" = D."IdDepartamentoGeografico"
            LEFT JOIN public."LugarNacimiento" LN
              ON LN."IdLugarNacimiento" = D."IdMunicipio"
            ORDER BY D."Codigo"
        """)
    ).mappings().all()

    servicios = db.execute(
        text("""
            SELECT SA."IdServicioAsociado" AS id,
                   SA."Codigo"             AS codigo,
                   SA."Nombre"             AS nombre,
                   (
                       SELECT COALESCE(json_object_agg(X.codigo, X.centros), '{}'::json)
                       FROM (
                           SELECT L."Codigo" AS codigo, COUNT(*) AS centros
                           FROM public."CentroCostoContable" CC
                           JOIN public."LineaNegocio" L
                             ON L."IdLineaNegocio" = CC."IdLineaNegocio"
                           WHERE CC."IdServicioAsociado" = SA."IdServicioAsociado"
                           GROUP BY L."Codigo"
                       ) X
                   )                       AS lineas
            FROM public."ServicioAsociado" SA
            ORDER BY SA."Codigo"
        """)
    ).mappings().all()

    sedes = db.execute(
        text("""
            SELECT S."IdSedeContable"     AS id,
                   S."Codigo"             AS codigo,
                   S."Descripcion"        AS nombre,
                   S."IdProyectoContable" AS id_proyecto,
                   COUNT(CC."IdCentroCostoContable")                          AS centros,
                   COUNT(CC."IdCentroCostoContable") FILTER (WHERE CC."Estado" = 'ABIERTO') AS abiertos
            FROM public."SedeContable" S
            LEFT JOIN public."CentroCostoContable" CC ON CC."IdSedeContable" = S."IdSedeContable"
            GROUP BY S."IdSedeContable"
            ORDER BY S."Codigo"
        """)
    ).mappings().all()

    return {
        "proyectos": [dict(p) for p in proyectos],
        "departamentos": [dict(d) for d in departamentos],
        "sedes": [dict(sd) for sd in sedes],
        "lineas": catalogo("LineaNegocio", "IdLineaNegocio"),
        "servicios": [dict(s) for s in servicios],
    }


# ─────────────────────────────────────────────
# Geografía (para ubicar un CEN 2 nuevo)
# ─────────────────────────────────────────────
@router.get("/geografia/departamentos", response_model=list[DepartamentoGeograficoOut])
def listar_departamentos_geograficos(
    db: Session = Depends(get_db),
    _current=Depends(require_contabilidad),
):
    """Departamentos de Colombia con su código DANE."""
    filas = db.execute(
        text("""
            SELECT "IdDepartamentoGeografico" AS id,
                   "CodigoDane"               AS codigo_dane,
                   "Nombre"                   AS nombre
            FROM public."DepartamentoGeografico"
            WHERE "Activo"
            ORDER BY "Nombre"
        """)
    ).mappings().all()

    return [dict(f) for f in filas]


@router.get(
    "/geografia/departamentos/{codigo_dane}/municipios",
    response_model=list[MunicipioOut],
)
def listar_municipios(
    codigo_dane: str = Path(..., pattern=r"^[0-9]{2}$"),
    db: Session = Depends(get_db),
    _current=Depends(require_contabilidad),
):
    """Municipios de un departamento (catálogo "LugarNacimiento")."""
    filas = db.execute(
        text("""
            SELECT "IdLugarNacimiento" AS id,
                   btrim("Nombre")     AS nombre
            FROM public."LugarNacimiento"
            WHERE "CodigoDepartamento" = :codigo_dane
              AND COALESCE("Estado", true)
            ORDER BY "Nombre"
        """),
        {"codigo_dane": codigo_dane},
    ).mappings().all()

    return [dict(f) for f in filas]


# ─────────────────────────────────────────────
# Sedes (CEN 3)
# ─────────────────────────────────────────────
@router.get("/sedes", response_model=list[SedeProyectoOut])
def listar_sedes_proyecto(
    id_proyecto: int = Query(..., ge=1),
    db: Session = Depends(get_db),
    _current=Depends(require_contabilidad),
):
    """Sedes de un proyecto, con los departamentos (CEN 2) y las líneas de
    negocio (CEN 4) donde ya tienen centros de costo, para elegir una
    existente al crear un centro."""
    filas = db.execute(
        text("""
            SELECT S."IdSedeContable" AS id,
                   S."Codigo"         AS codigo,
                   S."Descripcion"    AS descripcion,
                   COALESCE(
                       array_agg(DISTINCT D."Codigo") FILTER (WHERE D."Codigo" IS NOT NULL),
                       '{}'
                   )                  AS departamentos,
                   (
                       SELECT COALESCE(json_object_agg(X.codigo, X.centros), '{}'::json)
                       FROM (
                           SELECT L."Codigo" AS codigo, COUNT(*) AS centros
                           FROM public."CentroCostoContable" CL
                           JOIN public."LineaNegocio" L
                             ON L."IdLineaNegocio" = CL."IdLineaNegocio"
                           WHERE CL."IdSedeContable" = S."IdSedeContable"
                           GROUP BY L."Codigo"
                       ) X
                   )                  AS lineas,
                   COUNT(CC."IdCentroCostoContable")                          AS centros,
                   COUNT(CC."IdCentroCostoContable") FILTER (WHERE CC."Estado" = 'ABIERTO') AS abiertos
            FROM public."SedeContable" S
            LEFT JOIN public."CentroCostoContable" CC
              ON CC."IdSedeContable" = S."IdSedeContable"
            LEFT JOIN public."DepartamentoContable" D
              ON D."IdDepartamentoContable" = CC."IdDepartamentoContable"
            WHERE S."IdProyectoContable" = :id_proyecto
              AND S."Activo"
            GROUP BY S."IdSedeContable", S."Codigo", S."Descripcion"
            ORDER BY S."Codigo"
        """),
        {"id_proyecto": id_proyecto},
    ).mappings().all()

    return [dict(f) for f in filas]


@router.get("/sedes/validar-codigo", response_model=CodigoSedeOut)
def validar_codigo_sede(
    codigo: str = Query(..., min_length=1, max_length=20),
    db: Session = Depends(get_db),
    _current=Depends(require_contabilidad),
):
    """Indica si un código CEN 3 está libre. El código es único en todos los
    proyectos, por eso se valida en el servidor y no solo con las sedes del
    proyecto elegido."""
    codigo = codigo.strip().upper()

    existente = db.execute(
        text("""
            SELECT P."Codigo" AS codigo_proyecto, S."Descripcion" AS descripcion
            FROM public."SedeContable" S
            JOIN public."ProyectoContable" P
              ON P."IdProyectoContable" = S."IdProyectoContable"
            WHERE upper(S."Codigo") = :codigo
        """),
        {"codigo": codigo},
    ).mappings().first()

    if existente:
        return {"codigo": codigo, "disponible": False, **existente}

    return {"codigo": codigo, "disponible": True}


# ─────────────────────────────────────────────
# Validación de la combinación completa
# ─────────────────────────────────────────────
@router.get("/combinacion", response_model=CombinacionOut)
def validar_combinacion(
    cen2: str = Query(..., min_length=1, max_length=20),
    cen3: str = Query(..., min_length=1, max_length=20),
    cen4: str = Query(..., min_length=1, max_length=20),
    cen5: str = Query(..., min_length=1, max_length=20),
    db: Session = Depends(get_db),
    _current=Depends(require_contabilidad),
):
    """Indica si ya existe un centro con esa sede, departamento, línea y
    servicio (la misma regla única de la tabla). Se busca por códigos: si
    alguno es nuevo, la combinación no puede existir."""
    centro = db.execute(
        text("""
            SELECT CC."IdCentroCostoContable" AS id_centro_costo_contable,
                   P."Codigo" || '-' || D."Codigo" || '-' || S."Codigo" || '-' ||
                   L."Codigo" || '-' || SA."Codigo" AS codigo,
                   CC."Estado"            AS estado,
                   CC."PendienteRevision" AS pendiente_revision
            FROM public."CentroCostoContable" CC
            JOIN public."SedeContable" S
              ON S."IdSedeContable" = CC."IdSedeContable"
            JOIN public."ProyectoContable" P
              ON P."IdProyectoContable" = S."IdProyectoContable"
            JOIN public."DepartamentoContable" D
              ON D."IdDepartamentoContable" = CC."IdDepartamentoContable"
            JOIN public."LineaNegocio" L
              ON L."IdLineaNegocio" = CC."IdLineaNegocio"
            JOIN public."ServicioAsociado" SA
              ON SA."IdServicioAsociado" = CC."IdServicioAsociado"
            WHERE upper(D."Codigo") = upper(:cen2)
              AND upper(S."Codigo") = upper(:cen3)
              AND upper(L."Codigo") = upper(:cen4)
              AND upper(SA."Codigo") = upper(:cen5)
        """),
        {"cen2": cen2.strip(), "cen3": cen3.strip(), "cen4": cen4.strip(), "cen5": cen5.strip()},
    ).mappings().first()

    if centro:
        return {"existe": True, **centro}

    return {"existe": False}


# ─────────────────────────────────────────────
# Consulta
# ─────────────────────────────────────────────
# Etapa del centro según las fechas del proyecto (fecha de hoy en Bogotá). Un
# abierto sin fecha de inicio (carga inicial) se considera en ejecución.
SQL_ETAPA = """
    CASE
        WHEN CC."Estado" = 'CERRADO' THEN 'CERRADO'
        WHEN CC."FechaInicioProyecto" > (now() AT TIME ZONE 'America/Bogota')::date THEN 'POR_INICIAR'
        WHEN CC."FechaFinProyecto" < (now() AT TIME ZONE 'America/Bogota')::date THEN 'FIN_VENCIDO'
        ELSE 'EN_EJECUCION'
    END
"""

SQL_BASE = """
    FROM public."CentroCostoContable" CC
    JOIN public."SedeContable" S          ON S."IdSedeContable" = CC."IdSedeContable"
    JOIN public."ProyectoContable" P      ON P."IdProyectoContable" = S."IdProyectoContable"
    JOIN public."ClienteContable" CL      ON CL."IdClienteContable" = P."IdClienteContable"
    JOIN public."DepartamentoContable" D  ON D."IdDepartamentoContable" = CC."IdDepartamentoContable"
    JOIN public."LineaNegocio" L          ON L."IdLineaNegocio" = CC."IdLineaNegocio"
    JOIN public."ServicioAsociado" SA     ON SA."IdServicioAsociado" = CC."IdServicioAsociado"
    WHERE (CAST(:id_proyecto AS integer) IS NULL OR P."IdProyectoContable" = :id_proyecto)
      AND (CAST(:id_departamento AS integer) IS NULL OR D."IdDepartamentoContable" = :id_departamento)
      AND (CAST(:id_sede AS integer) IS NULL OR S."IdSedeContable" = :id_sede)
      AND (CAST(:id_linea AS integer) IS NULL OR L."IdLineaNegocio" = :id_linea)
      AND (CAST(:id_servicio AS integer) IS NULL OR SA."IdServicioAsociado" = :id_servicio)
      AND (CAST(:estado AS varchar) IS NULL OR CC."Estado" = :estado OR """ + SQL_ETAPA + """ = :estado)
      AND (CAST(:pendiente AS boolean) IS NULL OR CC."PendienteRevision" = :pendiente)
      AND (
          CAST(:texto AS varchar) IS NULL
          OR CL."Nit" ILIKE :texto
          OR CL."RazonSocial" ILIKE :texto
          OR P."Codigo" ILIKE :texto
          OR P."Nombre" ILIKE :texto
          OR S."Codigo" ILIKE :texto
          OR S."Descripcion" ILIKE :texto
      )
"""


@router.get("", response_model=ConsultaCentrosCostoOut)
def consultar_centros_costo(
    id_proyecto: int | None = Query(None, gt=0),
    id_departamento: int | None = Query(None, gt=0),
    id_sede: int | None = Query(None, gt=0),
    id_linea: int | None = Query(None, gt=0),
    id_servicio: int | None = Query(None, gt=0),
    # ABIERTO / CERRADO, o una etapa de los abiertos (POR_INICIAR,
    # EN_EJECUCION, FIN_VENCIDO).
    estado: Literal["ABIERTO", "CERRADO", "POR_INICIAR", "EN_EJECUCION", "FIN_VENCIDO"] | None = None,
    pendiente_revision: bool | None = None,
    # Búsqueda libre por NIT, cliente, proyecto o sede.
    q: str | None = Query(None, max_length=100),
    pagina: int = Query(1, ge=1),
    tamano_pagina: int = Query(50, ge=1, le=TAMANO_PAGINA_MAXIMO),
    db: Session = Depends(get_db),
    _current=Depends(require_contabilidad),
):
    texto = (q or "").strip()
    parametros = {
        "id_proyecto": id_proyecto,
        "id_departamento": id_departamento,
        "id_sede": id_sede,
        "id_linea": id_linea,
        "id_servicio": id_servicio,
        "estado": estado,
        "pendiente": pendiente_revision,
        "texto": f"%{texto}%" if texto else None,
    }

    resumen = db.execute(
        text("""
            SELECT COUNT(*)                                         AS total,
                   COUNT(*) FILTER (WHERE CC."Estado" = 'ABIERTO')  AS abiertos,
                   COUNT(*) FILTER (WHERE CC."Estado" = 'CERRADO')  AS cerrados,
                   COUNT(*) FILTER (WHERE CC."PendienteRevision")   AS pendientes_revision,
                   COUNT(*) FILTER (WHERE """ + SQL_ETAPA + """ = 'POR_INICIAR') AS por_iniciar,
                   COUNT(*) FILTER (WHERE """ + SQL_ETAPA + """ = 'FIN_VENCIDO') AS fin_vencido
        """ + SQL_BASE),
        parametros,
    ).mappings().one()

    # Líneas de las asignaciones vigentes de los centros filtrados.
    sql_lineas = """
        WITH filtrados AS (
            SELECT CC."IdCentroCostoContable" AS id, CC."Estado" AS estado
    """ + SQL_BASE + """
        ),
        lineas AS (
            SELECT F.id, AD."CantidadOperarios" * AD."Dedicacion" AS cantidad,
                   AD."CantidadOperarios" AS personas,
                   AD."HorasNocturnasSemana" AS nocturnas,
                   AD."HorasDominicalesSemana" AS dominicales,
                   AD."HorasNocturnasDominicalesSemana" AS nocturnas_dominicales,
                   btrim(C."NombreCargo") AS cargo, M."Nombre" AS modalidad
            FROM filtrados F
            JOIN public."AsignacionCentroCosto" A
              ON A."IdCentroCostoContable" = F.id AND A."Estado" = 'VIGENTE'
            JOIN public."AsignacionCentroCostoDetalle" AD
              ON AD."IdAsignacionCentroCosto" = A."IdAsignacionCentroCosto"
            JOIN public."Cargo" C ON C."IdCargo" = AD."IdCargo"
            JOIN public."ModalidadDias" M ON M."IdModalidadDias" = AD."IdModalidadDias"
        )
    """

    asignacion = db.execute(
        text(sql_lineas + """
            SELECT (SELECT COUNT(DISTINCT id) FROM lineas)                       AS centros_con_asignacion,
                   (SELECT COUNT(*) FROM filtrados F WHERE F.estado = 'ABIERTO'
                      AND NOT EXISTS (SELECT 1 FROM lineas L WHERE L.id = F.id)) AS abiertos_sin_asignacion,
                   COALESCE(ROUND(SUM(cantidad), 2), 0)                          AS operarios,
                   COALESCE(SUM(personas), 0)                                    AS personas,
                   COALESCE(ROUND(SUM(cantidad) FILTER (WHERE nocturnas > 0), 2), 0)   AS operarios_con_nocturnas,
                   COALESCE(ROUND(SUM(cantidad) FILTER (WHERE dominicales > 0), 2), 0) AS operarios_con_dominicales,
                   COALESCE(ROUND(SUM(cantidad) FILTER (WHERE nocturnas_dominicales > 0), 2), 0)
                                                                                 AS operarios_con_nocturnas_dominicales,
                   COALESCE(SUM(cantidad * nocturnas), 0)                        AS horas_nocturnas_semana,
                   COALESCE(SUM(cantidad * dominicales), 0)                      AS horas_dominicales_semana,
                   COALESCE(SUM(cantidad * nocturnas_dominicales), 0)            AS horas_nocturnas_dominicales_semana
            FROM lineas
        """),
        parametros,
    ).mappings().one()

    # Opciones de cada filtro según los demás filtros aplicados.
    facetas = {
        "proyectos": ("id_proyecto", 'P."IdProyectoContable"'),
        "departamentos": ("id_departamento", 'D."IdDepartamentoContable"'),
        "sedes": ("id_sede", 'S."IdSedeContable"'),
        "lineas": ("id_linea", 'L."IdLineaNegocio"'),
        "servicios": ("id_servicio", 'SA."IdServicioAsociado"'),
        "estados": ("estado", 'CC."Estado"'),
        "revision": ("pendiente", 'CC."PendienteRevision"'),
    }
    disponibles = {}
    for nombre, (parametro, columna) in facetas.items():
        filas = db.execute(
            text(f"SELECT {columna} AS valor, COUNT(*) AS centros" + SQL_BASE + f" GROUP BY {columna}"),
            {**parametros, parametro: None},
        ).all()
        # Claves en texto ("12", "ABIERTO", "true") para comparar con los filtros.
        disponibles[nombre] = {
            (str(valor).lower() if isinstance(valor, bool) else str(valor)): centros
            for valor, centros in filas
        }
    # Al filtro de estado se suman las etapas (POR_INICIAR, EN_EJECUCION, FIN_VENCIDO).
    filas = db.execute(
        text("SELECT " + SQL_ETAPA + " AS valor, COUNT(*) AS centros" + SQL_BASE + " GROUP BY 1"),
        {**parametros, "estado": None},
    ).all()
    disponibles["estados"].update({valor: centros for valor, centros in filas if valor != "CERRADO"})

    def agrupado(columna: str) -> list[dict]:
        filas = db.execute(
            text(sql_lineas + f"""
                SELECT {columna} AS nombre, ROUND(SUM(cantidad), 2) AS operarios
                FROM lineas
                GROUP BY {columna}
                ORDER BY SUM(cantidad) DESC, {columna}
            """),
            parametros,
        ).mappings().all()
        return [dict(f) for f in filas]

    centros = db.execute(
        text("""
            SELECT CC."IdCentroCostoContable" AS id_centro_costo_contable,
                   P."Codigo" || '-' || D."Codigo" || '-' || S."Codigo" || '-' ||
                       L."Codigo" || '-' || SA."Codigo" AS codigo,
                   CL."Nit"                  AS nit,
                   CL."RazonSocial"          AS cliente,
                   P."IdProyectoContable"    AS id_proyecto,
                   P."Codigo"                AS codigo_proyecto,
                   P."Nombre"                AS proyecto,
                   D."IdDepartamentoContable" AS id_departamento,
                   D."Codigo"                AS codigo_departamento,
                   D."Nombre"                AS departamento,
                   S."Codigo"                AS codigo_sede,
                   S."Descripcion"           AS sede,
                   L."IdLineaNegocio"        AS id_linea,
                   L."Codigo"                AS codigo_linea,
                   L."Nombre"                AS linea,
                   SA."IdServicioAsociado"   AS id_servicio,
                   SA."Codigo"               AS codigo_servicio,
                   SA."Nombre"               AS servicio,
                   CC."Estado"               AS estado,
                   """ + SQL_ETAPA + """     AS etapa,
                   CC."FechaApertura"        AS fecha_apertura,
                   CC."FechaCierre"          AS fecha_cierre,
                   CC."FechaInicioProyecto"  AS fecha_inicio_proyecto,
                   CC."FechaFinProyecto"     AS fecha_fin_proyecto,
                   CC."PendienteRevision"    AS pendiente_revision,
                   CC."ObservacionRevision"  AS observacion_revision,
                   COALESCE((
                       SELECT ROUND(SUM(AD."CantidadOperarios" * AD."Dedicacion"), 2)
                       FROM public."AsignacionCentroCosto" A
                       JOIN public."AsignacionCentroCostoDetalle" AD
                         ON AD."IdAsignacionCentroCosto" = A."IdAsignacionCentroCosto"
                       WHERE A."IdCentroCostoContable" = CC."IdCentroCostoContable"
                         AND A."Estado" = 'VIGENTE'
                   ), 0)                     AS operarios,
                   CC."FechaCreacion"        AS fecha_creacion
        """ + SQL_BASE + """
            ORDER BY P."Nombre", S."Codigo", L."Codigo", SA."Codigo"
            LIMIT :limite OFFSET :desplazamiento
        """),
        {
            **parametros,
            "limite": tamano_pagina,
            "desplazamiento": (pagina - 1) * tamano_pagina,
        },
    ).mappings().all()

    return {
        "total": resumen["total"],
        "pagina": pagina,
        "tamano_pagina": tamano_pagina,
        "resumen": {
            **resumen,
            "asignacion": {
                **asignacion,
                "por_cargo": agrupado("cargo"),
                "por_modalidad": agrupado("modalidad"),
            },
        },
        "disponibles": disponibles,
        "centros": [dict(c) for c in centros],
    }


# ─────────────────────────────────────────────
# Exportar a Excel
# ─────────────────────────────────────────────
SQL_EXPORTAR_CENTROS = """
    SELECT CC."IdCentroCostoContable" AS id,
           P."Codigo" || '-' || D."Codigo" || '-' || S."Codigo" || '-' ||
               L."Codigo" || '-' || SA."Codigo" AS codigo,
           CL."RazonSocial" AS cliente, CL."Nit" AS nit, CL."CodigoSocioNegocio" AS socio,
           P."Codigo" AS cen1, P."Nombre" AS proyecto,
           D."Codigo" AS cen2, D."Nombre" AS departamento,
           S."Codigo" AS cen3, S."Descripcion" AS sede,
           L."Codigo" AS cen4, L."Nombre" AS linea,
           SA."Codigo" AS cen5, SA."Nombre" AS servicio,
           CC."Estado" AS estado, """ + SQL_ETAPA + """ AS etapa,
           CC."FechaInicioProyecto" AS inicio_proyecto, CC."FechaFinProyecto" AS fin_proyecto,
           CC."FechaApertura" AS apertura, CC."FechaCierre" AS cierre,
           CC."PendienteRevision" AS pendiente, CC."ObservacionRevision" AS observacion_revision,
           -- Observación que se escribió al crear el centro (hoja CC).
           (SELECT H."Motivo" FROM public."HistorialCentroCosto" H
             WHERE H."IdCentroCostoContable" = CC."IdCentroCostoContable" AND H."Accion" = 'CREADO'
             ORDER BY H."IdHistorialCentroCosto" LIMIT 1) AS observacion_creacion
    FROM public."CentroCostoContable" CC
    JOIN public."SedeContable" S          ON S."IdSedeContable" = CC."IdSedeContable"
    JOIN public."ProyectoContable" P      ON P."IdProyectoContable" = S."IdProyectoContable"
    JOIN public."ClienteContable" CL      ON CL."IdClienteContable" = P."IdClienteContable"
    JOIN public."DepartamentoContable" D  ON D."IdDepartamentoContable" = CC."IdDepartamentoContable"
    JOIN public."LineaNegocio" L          ON L."IdLineaNegocio" = CC."IdLineaNegocio"
    JOIN public."ServicioAsociado" SA     ON SA."IdServicioAsociado" = CC."IdServicioAsociado"
    WHERE (CAST(:estado AS varchar) IS NULL OR CC."Estado" = :estado)
      AND (CAST(:proyectos AS integer[]) IS NULL OR P."IdProyectoContable" = ANY(:proyectos))
    ORDER BY CL."RazonSocial", P."Codigo", S."Codigo", L."Codigo", SA."Codigo"
"""

# Líneas de las asignaciones vigentes de esos centros (con el horario anterior
# para las líneas registradas antes de los tipos de turno).
SQL_EXPORTAR_LINEAS = """
    SELECT A."IdCentroCostoContable" AS id_centro, A."FechaDesde" AS fecha_desde,
           A."Observacion" AS observacion_asignacion,
           btrim(C."NombreCargo") AS cargo, D."CantidadOperarios" AS personas,
           D."Dedicacion" AS dedicacion,
           D."CantidadOperarios" * D."Dedicacion" AS operarios,
           M."Nombre" AS dias, M."DiasSemana" AS dias_semana,
           D."DescansaDiaEntreSemana" AS descansa,
           D."TipoTurno" AS tipo_turno, D."MinutoFinTurno" AS fin_turno, D."MinutoFinDomingo" AS fin_domingo,
           D."MinutosFinPorDia" AS fin_por_dia,
           D."HorasSemana" AS horas, D."HorasNocturnasSemana" AS nocturnas,
           D."HorasDominicalesSemana" AS dominicales,
           D."HorasNocturnasDominicalesSemana" AS nocturnas_dominicales,
           D."HorasExtraDiurnasSemana" AS extra_diurnas,
           D."HorasExtraNocturnasSemana" AS extra_nocturnas,
           D."HorasExtraDiurnasFestivasSemana" AS extra_diurnas_festivas,
           D."HorasExtraNocturnasFestivasSemana" AS extra_nocturnas_festivas,
           H."HoraInicio" AS inicio_anterior, H."HoraFin" AS fin_anterior
    FROM public."AsignacionCentroCosto" A
    JOIN public."AsignacionCentroCostoDetalle" D ON D."IdAsignacionCentroCosto" = A."IdAsignacionCentroCosto"
    JOIN public."Cargo" C ON C."IdCargo" = D."IdCargo"
    JOIN public."ModalidadDias" M ON M."IdModalidadDias" = D."IdModalidadDias"
    LEFT JOIN public."AsignacionCentroCostoHorario" H
      ON H."IdAsignacionCentroCostoDetalle" = D."IdAsignacionCentroCostoDetalle" AND H."TipoDia" = 'GENERAL'
    WHERE A."Estado" = 'VIGENTE' AND A."IdCentroCostoContable" = ANY(:centros)
    ORDER BY A."IdCentroCostoContable", D."IdAsignacionCentroCostoDetalle"
"""

ETAPAS_TEXTO = {
    "POR_INICIAR": "Abierto · por iniciar",
    "EN_EJECUCION": "Abierto",
    "FIN_VENCIDO": "Abierto · fin vencido",
    "CERRADO": "Cerrado",
}
TURNOS_TEXTO = {"DIURNO": "Diurno", "TARDE": "Tarde", "NOCHE": "Noche"}


def _hora_texto(minutos: int | None) -> str:
    return "" if minutos is None else f"{int(minutos) // 60:02d}:{int(minutos) % 60:02d}"


def _recargos_linea(linea: dict) -> dict:
    """Horas de recargo por operario y semana, en categorías que no se cruzan:
    nocturnas (no domingo), dominicales diurnas y nocturnas dominicales."""
    nocturnas = float(linea["nocturnas"])
    dominicales = float(linea["dominicales"])
    nocturnas_dominicales = float(linea["nocturnas_dominicales"])
    return {
        "nocturnas": round(nocturnas - nocturnas_dominicales, 2),
        "dominicales_diurnas": round(dominicales - nocturnas_dominicales, 2),
        "nocturnas_dominicales": round(nocturnas_dominicales, 2),
    }


# Horas extras: clave, abreviatura y nombre (en el orden de las columnas).
TIPOS_HORA_EXTRA = [
    ("extra_diurnas", "HED", "extra diurnas"),
    ("extra_nocturnas", "HEN", "extra nocturnas"),
    ("extra_diurnas_festivas", "HEDF", "extra diurnas dominicales / festivas"),
    ("extra_nocturnas_festivas", "HENF", "extra nocturnas dominicales / festivas"),
]


def _extras_linea(linea: dict) -> dict:
    """Horas extras por operario y semana, a tiempo completo (sin la dedicación)."""
    return {clave: round(float(linea[clave] or 0), 2) for clave, _, _ in TIPOS_HORA_EXTRA}


def _horas_texto(valor: float) -> str:
    return f"{valor:g}".replace(".", ",")


def _recargos_texto(recargos: dict, extras: dict | None = None) -> str:
    """Horas de recargo por operario y semana, abreviadas en una celda:
    "RN 9,67 h · RD 0 h · RND 3 h" (nocturnas, dominicales diurnas y
    nocturnas dominicales) y, si tiene, las horas extras de cada tipo:
    "· HED 2 h · HENF 1 h"."""
    texto = (
        f"RN {_horas_texto(recargos['nocturnas'])} h · RD {_horas_texto(recargos['dominicales_diurnas'])} h"
        f" · RND {_horas_texto(recargos['nocturnas_dominicales'])} h"
    )
    for clave, abreviatura, _ in TIPOS_HORA_EXTRA:
        if extras and extras.get(clave):
            texto += f" · {abreviatura} {_horas_texto(extras[clave])} h"
    return texto


def _horario_linea(linea: dict) -> tuple[str, str, str]:
    """Turno, horario de los días y horario del domingo, para el Excel."""
    if not linea["tipo_turno"]:
        horario = ""
        if linea["inicio_anterior"]:
            horario = f"{linea['inicio_anterior']:%H:%M} a {linea['fin_anterior']:%H:%M}"
        return "Horario anterior", horario, ""

    dias = len(linea["dias_semana"]) - (1 if linea["descansa"] else 0)
    minutos_dia = float(linea["horas"]) * 60 / dias
    horario = ""
    if linea.get("fin_por_dia"):
        # Tarde con salida distinta según el día: "Lun, Mar 13:20 a 20:20 · ...".
        por_dia = {d: m for d, m in enumerate(linea["fin_por_dia"], start=1) if m is not None}
        domingo = ""
        if DOMINGO in por_dia:
            domingo = f"{_hora_texto(round(por_dia[DOMINGO] - minutos_dia))} a {_hora_texto(por_dia[DOMINGO])}"
        return TURNOS_TEXTO["TARDE"], resumen_salidas(por_dia, minutos_dia, incluir_domingo=False), domingo
    if linea["fin_turno"] is not None:
        horario = f"{_hora_texto(round(linea['fin_turno'] - minutos_dia))} a {_hora_texto(linea['fin_turno'])}"
    domingo = ""
    if linea["fin_domingo"] is not None:
        domingo = f"{_hora_texto(round(linea['fin_domingo'] - minutos_dia))} a {_hora_texto(linea['fin_domingo'])}"
    return TURNOS_TEXTO.get(linea["tipo_turno"], linea["tipo_turno"]), horario, domingo


def _hoja(libro, titulo: str, encabezados: list[str], filas: list[list], anchos: list[int]):
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.utils import get_column_letter

    hoja = libro.create_sheet(titulo)
    hoja.append(encabezados)
    for fila in filas:
        hoja.append(fila)

    relleno = PatternFill("solid", fgColor="0F6B4F")
    for celda in hoja[1]:
        celda.font = Font(bold=True, color="FFFFFF")
        celda.fill = relleno
        celda.alignment = Alignment(vertical="center", wrap_text=True)
    hoja.row_dimensions[1].height = 32
    hoja.freeze_panes = "A2"
    if filas:
        hoja.auto_filter.ref = f"A1:{get_column_letter(len(encabezados))}{len(filas) + 1}"
    for indice, ancho in enumerate(anchos, start=1):
        hoja.column_dimensions[get_column_letter(indice)].width = ancho
    return hoja


# Hoja "Centros de costo": (encabezado, tipo, ancho, valor). Las 16 primeras
# siguen el orden de la hoja que Contabilidad ya comparte en modo lectura; no
# cambiar su orden ni sus nombres. Lo nuevo va de la columna 17 en adelante.
# valor(centro, lineas_vigentes, operarios, recargos).
COLUMNAS_CENTROS = [
    ("Código socio de negocio", "texto", 16, lambda c, l, o, r: c["socio"] or ""),
    ("Nit", "texto", 14, lambda c, l, o, r: c["nit"]),
    ("Cen 1", "texto", 10, lambda c, l, o, r: c["cen1"]),
    ("Cliente", "texto", 32, lambda c, l, o, r: c["cliente"]),
    ("Cen 2", "texto", 10, lambda c, l, o, r: c["cen2"]),
    ("Departamento", "texto", 16, lambda c, l, o, r: c["departamento"]),
    ("Cen 3", "texto", 12, lambda c, l, o, r: c["cen3"]),
    ("Sede", "texto", 30, lambda c, l, o, r: c["sede"]),
    ("Cen 4", "texto", 10, lambda c, l, o, r: c["cen4"]),
    ("Linea de Negocio", "texto", 24, lambda c, l, o, r: c["linea"]),
    ("Cen 5", "texto", 12, lambda c, l, o, r: c["cen5"]),
    ("Servicio asociado", "texto", 26, lambda c, l, o, r: c["servicio"]),
    ("Fecha inicio", "fecha", 13, lambda c, l, o, r: c["inicio_proyecto"]),
    ("Estado", "texto", 20, lambda c, l, o, r: ETAPAS_TEXTO.get(c["etapa"], c["estado"])),
    ("Fecha finalización", "fecha", 13, lambda c, l, o, r: c["fin_proyecto"]),
    # Operarios equivalentes (personas × dedicación).
    ("Asignación vigente sede", "decimal", 13, lambda c, l, o, r: round(o, 2)),
    # ── Desde la columna 17 ──
    ("Código centro de costo", "texto", 38, lambda c, l, o, r: c["codigo"]),
    ("Proyecto", "texto", 28, lambda c, l, o, r: c["proyecto"]),
    ("Apertura", "fecha", 12, lambda c, l, o, r: c["apertura"]),
    ("Cierre", "fecha", 12, lambda c, l, o, r: c["cierre"]),
    ("Asignación vigente desde", "fecha", 14, lambda c, l, o, r: l[0]["fecha_desde"] if l else None),
    ("Personas asignadas", "entero", 11, lambda c, l, o, r: sum(x["personas"] for x in l)),
    ("Total h nocturnas / semana", "decimal", 14, lambda c, l, o, r: round(r["nocturnas"], 2)),
    ("Total h dominicales diurnas / semana", "decimal", 16, lambda c, l, o, r: round(r["dominicales_diurnas"], 2)),
    ("Total h nocturnas dominicales / semana", "decimal", 16, lambda c, l, o, r: round(r["nocturnas_dominicales"], 2)),
    # Horas extras de la asignación vigente (por operarios equivalentes).
    *[
        (f"Total h {nombre} / semana", "decimal", 16, lambda c, l, o, r, clave=clave: round(r[clave], 2))
        for clave, _, nombre in TIPOS_HORA_EXTRA
    ],
    ("Pendiente de revisión", "texto", 11, lambda c, l, o, r: "Sí" if c["pendiente"] else "No"),
    ("Observación de revisión", "texto", 40, lambda c, l, o, r: c["observacion_revision"] or ""),
]


def armar_exportacion(db: Session, estado: str | None, proyectos: list[int] | None, usuario: str) -> dict:
    """Datos de la exportación (Excel y Google Sheets): las hojas "Centros de
    costo", "Asignaciones vigentes" y "CC" (centros y turnos) con encabezados, tipos y filas, y las filas
    del resumen. Los centros sin asignación aparecen con 0 operarios."""
    centros = db.execute(
        text(SQL_EXPORTAR_CENTROS), {"estado": estado, "proyectos": proyectos}
    ).mappings().all()

    lineas = db.execute(
        text(SQL_EXPORTAR_LINEAS), {"centros": [c["id"] for c in centros] or [0]}
    ).mappings().all()

    por_centro: dict[int, list[dict]] = {}
    for linea in lineas:
        por_centro.setdefault(linea["id_centro"], []).append(dict(linea))

    ahora = db.execute(text("SELECT (now() AT TIME ZONE 'America/Bogota')::timestamp(0)")).scalar()
    hoy = ahora.date()
    parametro = db.execute(
        text("""
            SELECT "HoraInicioNocturna" AS inicio, "HoraFinNocturna" AS fin,
                   "HorasMaximasSemana" AS horas,
                   "PorcentajeRecargoNocturno" AS nocturno,
                   "PorcentajeRecargoDominical" AS dominical
            FROM public."ParametroJornadaLaboral"
            WHERE "FechaDesde" <= :hoy ORDER BY "FechaDesde" DESC LIMIT 1
        """),
        {"hoy": hoy},
    ).mappings().first()

    # Hoja 1: un centro por fila, con el total de su asignación vigente.
    filas_centros = []
    claves_extra = [clave for clave, _, _ in TIPOS_HORA_EXTRA]
    totales = {
        "operarios": 0.0, "personas": 0, "nocturnas": 0.0, "dominicales_diurnas": 0.0, "nocturnas_dominicales": 0.0,
        **{clave: 0.0 for clave in claves_extra},
    }
    sin_asignacion = 0
    for c in centros:
        suyas = por_centro.get(c["id"], [])
        operarios = sum(float(l["operarios"]) for l in suyas)
        suma = {
            "nocturnas": 0.0, "dominicales_diurnas": 0.0, "nocturnas_dominicales": 0.0,
            **{clave: 0.0 for clave in claves_extra},
        }
        for linea in suyas:
            # Recargos y horas extras por operario × operarios equivalentes.
            for clave, horas in {**_recargos_linea(linea), **_extras_linea(linea)}.items():
                suma[clave] += horas * float(linea["operarios"])
        if not suyas:
            sin_asignacion += 1
        totales["operarios"] += operarios
        totales["personas"] += sum(l["personas"] for l in suyas)
        for clave in suma:
            totales[clave] += suma[clave]

        filas_centros.append([valor(c, suyas, operarios, suma) for _, _, _, valor in COLUMNAS_CENTROS])

    hoja_centros = {
        "nombre": "Centros de costo",
        "encabezados": [encabezado for encabezado, _, _, _ in COLUMNAS_CENTROS],
        "tipos": [tipo for _, tipo, _, _ in COLUMNAS_CENTROS],
        "anchos": [ancho for _, _, ancho, _ in COLUMNAS_CENTROS],
        "filas": filas_centros,
    }

    # Hoja 2: una fila por línea de la asignación vigente.
    nombres = {c["id"]: c for c in centros}
    filas_lineas = []
    for linea in lineas:
        centro = nombres[linea["id_centro"]]
        recargos = _recargos_linea(linea)
        extras = _extras_linea(linea)
        turno, horario, domingo = _horario_linea(linea)
        equivalentes = float(linea["operarios"])
        filas_lineas.append([
            centro["codigo"], centro["cliente"], centro["sede"], linea["fecha_desde"],
            linea["cargo"], linea["personas"], float(linea["dedicacion"]), round(equivalentes, 2), linea["dias"],
            "Sí" if linea["descansa"] else "No", turno, horario, domingo,
            float(linea["horas"]),
            recargos["nocturnas"], recargos["dominicales_diurnas"], recargos["nocturnas_dominicales"],
            round(recargos["nocturnas"] * equivalentes, 2),
            round(recargos["dominicales_diurnas"] * equivalentes, 2),
            round(recargos["nocturnas_dominicales"] * equivalentes, 2),
            # Horas extras: por operario (tiempo completo) y total de la línea.
            *[extras[clave] for clave in claves_extra],
            *[round(extras[clave] * equivalentes, 2) for clave in claves_extra],
        ])

    hoja_lineas = {
        "nombre": "Asignaciones vigentes",
        "encabezados": [
            "Código centro de costo", "Cliente", "Sede", "Rige desde", "Cargo", "Personas",
            "Dedicación", "Operarios equivalentes",
            "Días", "Descansa 1 día entre semana", "Turno", "Horario", "Horario del domingo",
            "H / semana por operario", "H nocturnas por operario", "H dominicales diurnas por operario",
            "H nocturnas dominicales por operario", "Total h nocturnas", "Total h dominicales diurnas",
            "Total h nocturnas dominicales",
            *[f"H {nombre} por operario" for _, _, nombre in TIPOS_HORA_EXTRA],
            *[f"Total h {nombre}" for _, _, nombre in TIPOS_HORA_EXTRA],
        ],
        "tipos": ["texto", "texto", "texto", "fecha", "texto", "entero", "decimal", "decimal"] + ["texto"] * 5 + ["decimal"] * 15,
        "anchos": [38, 32, 30, 12, 28, 10, 11, 12, 18, 13, 16, 34, 14, 12, 13, 15, 15, 13, 15, 15] + [15] * 8,
        "filas": filas_lineas,
    }

    # Hoja 3 ("CC"): centros y turnos. El centro se repite una vez por cada línea de
    # su asignación vigente; sin asignación aparece una vez, con el turno en
    # blanco. PAX son los operarios equivalentes (personas × dedicación) y el
    # detalle del turno son las horas de recargo de una persona en este centro:
    # las del turno por su dedicación (0,4 → 40 % de las horas).
    filas_turnos = []
    for c in centros:
        base = [
            c["socio"] or "", c["nit"], c["cen1"], c["cliente"], c["cen2"], c["departamento"],
            c["cen3"], c["sede"], c["cen4"], c["linea"], c["cen5"], c["servicio"],
            c["inicio_proyecto"], "Activo" if c["estado"] == "ABIERTO" else "Cerrado", c["fin_proyecto"],
        ]
        for linea in por_centro.get(c["id"]) or [None]:
            if linea is None:
                turno = ["", "", None, "", ""]
            else:
                dedicacion = float(linea["dedicacion"])
                recargos = {k: round(v * dedicacion, 2) for k, v in _recargos_linea(linea).items()}
                extras = {k: round(v * dedicacion, 2) for k, v in _extras_linea(linea).items()}
                turno = [
                    # "PAX - Cerrado": observación de la asignación vigente.
                    linea["observacion_asignacion"] or "",
                    linea["cargo"], round(float(linea["operarios"]), 2), linea["dias"],
                    _recargos_texto(recargos, extras),
                ]
            filas_turnos.append(base + turno + [c["observacion_creacion"] or ""])

    hoja_turnos = {
        # Nombres de columna que definió Contabilidad (los "CODIGO" son Cen 1 a Cen 5).
        "nombre": "CC",
        "encabezados": [
            "Codigo S/N", "Nit", "CODIGO", "PROYECTO", "CODIGO", "DEPARTAMENTO", "CODIGO", "Sede",
            "CODIGO", "LINEA DE NEGOCIO", "CODIGO", "SERVICIO ASOCIADO - AREAS",
            "Fecha Inicio", "Estado Proyecto", "Fecha Final",
            "PAX - Cerrado", "PERFIL", "PAX", "TURNO",
            # Detalle: RN nocturnas · RD dominicales diurnas · RND nocturnas dominicales
            # y, si tiene, HED / HEN / HEDF / HENF horas extras (por persona y
            # semana, ya por la dedicación).
            "Detalle Turno",
            "Observación creación",
        ],
        "tipos": ["texto"] * 12 + ["fecha", "texto", "fecha", "texto", "texto", "decimal", "texto", "texto", "texto"],
        "anchos": [16, 14, 10, 32, 10, 16, 12, 30, 10, 24, 12, 26, 13, 10, 13, 40, 28, 10, 18, 34, 40],
        "filas": filas_turnos,
    }

    # Resumen y criterios.
    nombres_proyectos = []
    if proyectos:
        nombres_proyectos = db.execute(
            text('SELECT "Codigo" FROM public."ProyectoContable" WHERE "IdProyectoContable" = ANY(:p) ORDER BY 1'),
            {"p": proyectos},
        ).scalars().all()

    resumen = [
        ["Centros de costo y asignaciones vigentes"],
        [],
        ["Generado", f"{ahora:%d/%m/%Y %H:%M} por {usuario}"],
        ["Estado", {"ABIERTO": "Solo abiertos", "CERRADO": "Solo cerrados"}.get(estado, "Todos")],
        ["Clientes", ", ".join(nombres_proyectos) if proyectos else "Todos"],
        [],
        ["Centros de costo", len(centros)],
        ["Abiertos", sum(1 for c in centros if c["estado"] == "ABIERTO")],
        ["Cerrados", sum(1 for c in centros if c["estado"] == "CERRADO")],
        ["Sin asignación vigente", sin_asignacion],
        ["Operarios equivalentes asignados", round(totales["operarios"], 2)],
        ["Personas asignadas", totales["personas"]],
        ["Base de la dedicación", "24 días hábiles al mes"],
        [],
        ["Total horas de recargo por semana (operarios equivalentes)"],
        ["Nocturnas (lunes a sábado)", round(totales["nocturnas"], 2)],
        ["Dominicales diurnas", round(totales["dominicales_diurnas"], 2)],
        ["Nocturnas dominicales", round(totales["nocturnas_dominicales"], 2)],
        [],
        ["Total horas extras por semana (operarios equivalentes)"],
        *[
            [f"{abreviatura} · {nombre[0].upper()}{nombre[1:]}", round(totales[clave], 2)]
            for clave, abreviatura, nombre in TIPOS_HORA_EXTRA
        ],
    ]
    if parametro:
        resumen += [
            [],
            ["Parámetros vigentes"],
            ["Franja nocturna", f"{parametro['inicio']:%H:%M} a {parametro['fin']:%H:%M}"],
            ["Horas máximas por semana", float(parametro["horas"])],
            ["Recargo nocturno", f"{float(parametro['nocturno']):g} %"],
            ["Recargo dominical", f"{float(parametro['dominical']):g} %"],
        ]

    return {"hoy": hoy, "hojas": [hoja_centros, hoja_lineas, hoja_turnos], "resumen": resumen}


@router.get("/exportar")
def exportar_centros_costo(
    estado: Literal["ABIERTO", "CERRADO"] | None = None,
    # Uno o varios proyectos (CEN 1); sin ninguno, todos los clientes.
    id_proyecto: list[int] | None = Query(None),
    db: Session = Depends(get_db),
    current=Depends(require_contabilidad),
):
    """Excel con los centros de costo (abiertos, cerrados o todos; de todos los
    clientes o de los elegidos), su asignación vigente y el total de horas de
    recargo por semana. Los centros sin asignación aparecen con 0 operarios."""
    from openpyxl import Workbook
    from openpyxl.styles import Font
    from openpyxl.utils import get_column_letter

    proyectos = sorted(set(id_proyecto)) if id_proyecto else None
    datos = armar_exportacion(db, estado, proyectos, _nombre_usuario(current))

    libro = Workbook()
    libro.remove(libro.active)

    for h in datos["hojas"]:
        hoja = _hoja(libro, h["nombre"], h["encabezados"], h["filas"], h["anchos"])
        for indice, tipo in enumerate(h["tipos"], start=1):
            if tipo == "fecha":
                for celda in hoja[get_column_letter(indice)][1:]:
                    celda.number_format = "DD/MM/YYYY"

    resumen = libro.create_sheet("Resumen")
    for fila in datos["resumen"]:
        resumen.append(fila)
    for numero, fila in enumerate(datos["resumen"], start=1):
        if len(fila) == 1:
            resumen.cell(row=numero, column=1).font = Font(bold=True, size=12 if numero == 1 else 11)
    resumen.column_dimensions["A"].width = 52
    resumen.column_dimensions["B"].width = 40
    libro.move_sheet("Resumen", offset=-(len(libro.sheetnames) - 1))

    salida = BytesIO()
    libro.save(salida)
    salida.seek(0)
    nombre = f"centros_costo_{datos['hoy']:%Y-%m-%d}.xlsx"
    return StreamingResponse(
        salida,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{nombre}"'},
    )


@router.post("/sincronizar-sheets")
def sincronizar_google_sheets(current=Depends(require_contabilidad)):
    """Envía ya mismo la foto completa a la hoja de Google (además del envío
    automático después de cada cambio y del refresco diario)."""
    if not contabilidad_sheets_service.configurado():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="La hoja de Google no está configurada (CONTABILIDAD_APPSCRIPT_URL y _CLAVE).",
        )
    try:
        hojas = contabilidad_sheets_service.sincronizar(
            origen="manual", usuario=_nombre_usuario(current), evento="Actualización manual"
        )
    except contabilidad_sheets_service.ErrorSheets as error:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(error)) from error
    return {"ok": True, "hojas": hojas}


# ─────────────────────────────────────────────
# Detalle, historial, cierre y reapertura
# ─────────────────────────────────────────────
SQL_COLUMNAS = """
    SELECT CC."IdCentroCostoContable" AS id_centro_costo_contable,
           P."Codigo" || '-' || D."Codigo" || '-' || S."Codigo" || '-' ||
               L."Codigo" || '-' || SA."Codigo" AS codigo,
           CL."Nit"                  AS nit,
           CL."RazonSocial"          AS cliente,
           P."IdProyectoContable"    AS id_proyecto,
           P."Codigo"                AS codigo_proyecto,
           P."Nombre"                AS proyecto,
           CL."CodigoSocioNegocio"   AS codigo_socio_negocio,
           D."IdDepartamentoContable" AS id_departamento,
           D."Codigo"                AS codigo_departamento,
           D."Nombre"                AS departamento,
           S."Codigo"                AS codigo_sede,
           S."Descripcion"           AS sede,
           L."IdLineaNegocio"        AS id_linea,
           L."Codigo"                AS codigo_linea,
           L."Nombre"                AS linea,
           SA."IdServicioAsociado"   AS id_servicio,
           SA."Codigo"               AS codigo_servicio,
           SA."Nombre"               AS servicio,
           CC."Estado"               AS estado,
           """ + SQL_ETAPA + """     AS etapa,
           CC."FechaApertura"        AS fecha_apertura,
           CC."FechaCierre"          AS fecha_cierre,
           CC."FechaInicioProyecto"  AS fecha_inicio_proyecto,
           CC."FechaFinProyecto"     AS fecha_fin_proyecto,
           CC."PendienteRevision"    AS pendiente_revision,
           CC."ObservacionRevision"  AS observacion_revision,
           COALESCE((
               SELECT ROUND(SUM(AD."CantidadOperarios" * AD."Dedicacion"), 2)
               FROM public."AsignacionCentroCosto" A
               JOIN public."AsignacionCentroCostoDetalle" AD
                 ON AD."IdAsignacionCentroCosto" = A."IdAsignacionCentroCosto"
               WHERE A."IdCentroCostoContable" = CC."IdCentroCostoContable"
                 AND A."Estado" = 'VIGENTE'
           ), 0)                     AS operarios,
           CC."FechaCreacion"        AS fecha_creacion,
           CC."CreadoPor"            AS creado_por,
           CC."FechaActualizacion"   AS fecha_actualizacion,
           CC."ActualizadoPor"       AS actualizado_por
    FROM public."CentroCostoContable" CC
    JOIN public."SedeContable" S          ON S."IdSedeContable" = CC."IdSedeContable"
    JOIN public."ProyectoContable" P      ON P."IdProyectoContable" = S."IdProyectoContable"
    JOIN public."ClienteContable" CL      ON CL."IdClienteContable" = P."IdClienteContable"
    JOIN public."DepartamentoContable" D  ON D."IdDepartamentoContable" = CC."IdDepartamentoContable"
    JOIN public."LineaNegocio" L          ON L."IdLineaNegocio" = CC."IdLineaNegocio"
    JOIN public."ServicioAsociado" SA     ON SA."IdServicioAsociado" = CC."IdServicioAsociado"
"""


def _detalle(db: Session, id_centro: int) -> dict:
    centro = db.execute(
        text(SQL_COLUMNAS + ' WHERE CC."IdCentroCostoContable" = :id'),
        {"id": id_centro},
    ).mappings().first()

    if centro is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="El centro de costo no existe.",
        )

    historial = db.execute(
        text("""
            SELECT "IdHistorialCentroCosto" AS id_historial_centro_costo,
                   "Accion"                 AS accion,
                   "EstadoAnterior"         AS estado_anterior,
                   "EstadoNuevo"            AS estado_nuevo,
                   "FechaEfectiva"          AS fecha_efectiva,
                   "FechaRegistro"          AS fecha_registro,
                   "Motivo"                 AS motivo,
                   "Detalle"                AS detalle,
                   "Usuario"                AS usuario
            FROM public."HistorialCentroCosto"
            WHERE "IdCentroCostoContable" = :id
            ORDER BY "FechaRegistro" DESC, "IdHistorialCentroCosto" DESC
        """),
        {"id": id_centro},
    ).mappings().all()

    return {**centro, "historial": [dict(h) for h in historial]}


@router.get("/{id_centro}", response_model=CentroCostoDetalleOut)
def obtener_centro_costo(
    id_centro: int,
    db: Session = Depends(get_db),
    _current=Depends(require_contabilidad),
):
    return _detalle(db, id_centro)


def _nombre_usuario(current: dict) -> str:
    usuario = current["usuario"]
    return (usuario.Usuario or usuario.NombreUsuario or "SIN USUARIO").strip()[:100]


def _cambiar_estado(
    db: Session,
    current: dict,
    id_centro: int,
    payload: CambioEstadoIn,
    estado_actual: str,
    estado_nuevo: str,
) -> dict:
    centro = _detalle(db, id_centro)
    motivo = (payload.motivo or "").strip()

    if not motivo:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="El motivo es obligatorio.",
        )

    if centro["estado"] != estado_actual:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"El centro de costo ya está {centro['estado'].lower()}.",
        )

    hoy = db.execute(text("SELECT (now() AT TIME ZONE 'America/Bogota')::date")).scalar()

    if payload.fecha > hoy:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="La fecha no puede ser futura.",
        )

    if estado_nuevo == "CERRADO":
        if centro["fecha_apertura"] and payload.fecha < centro["fecha_apertura"]:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    "La fecha de cierre no puede ser anterior a la apertura "
                    f"({centro['fecha_apertura']:%d/%m/%Y})."
                ),
            )
        sql_fechas = '"FechaCierre" = :fecha'
    else:
        if centro["fecha_cierre"] and payload.fecha < centro["fecha_cierre"]:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    "La fecha de reapertura no puede ser anterior al último "
                    f"cierre ({centro['fecha_cierre']:%d/%m/%Y})."
                ),
            )
        # Nuevo período: apertura con la fecha indicada y sin fecha de cierre.
        sql_fechas = '"FechaApertura" = :fecha, "FechaCierre" = NULL'

    usuario = _nombre_usuario(current)

    try:
        # Datos para el historial que escribe el trigger (solo esta transacción).
        db.execute(
            text("""
                SELECT set_config('app.usuario', :usuario, true),
                       set_config('app.motivo', :motivo, true),
                       set_config('app.fecha_efectiva', :fecha, true)
            """),
            {"usuario": usuario, "motivo": motivo, "fecha": payload.fecha.isoformat()},
        )
        actualizados = db.execute(
            text(f"""
                UPDATE public."CentroCostoContable"
                SET "Estado"             = :estado_nuevo,
                    {sql_fechas},
                    "FechaActualizacion" = now(),
                    "ActualizadoPor"     = :usuario
                WHERE "IdCentroCostoContable" = :id
                  AND "Estado" = :estado_actual
            """),
            {
                "id": id_centro,
                "estado_nuevo": estado_nuevo,
                "estado_actual": estado_actual,
                "fecha": payload.fecha,
                "usuario": usuario,
            },
        ).rowcount
        db.commit()
    except Exception:
        db.rollback()
        raise

    if not actualizados:
        # Otro usuario cambió el estado al mismo tiempo.
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="El estado del centro de costo cambió. Actualiza la consulta.",
        )

    detalle = _detalle(db, id_centro)
    contabilidad_sheets_service.programar_sincronizacion(
        usuario, f"{'Cierre' if estado_nuevo == 'CERRADO' else 'Reapertura'} de {detalle['codigo']}"
    )
    return detalle


@router.post("/{id_centro}/cerrar", response_model=CentroCostoDetalleOut)
def cerrar_centro_costo(
    id_centro: int,
    payload: CambioEstadoIn,
    db: Session = Depends(get_db),
    current=Depends(require_contabilidad),
):
    return _cambiar_estado(db, current, id_centro, payload, "ABIERTO", "CERRADO")


@router.post("/{id_centro}/reabrir", response_model=CentroCostoDetalleOut)
def reabrir_centro_costo(
    id_centro: int,
    payload: CambioEstadoIn,
    db: Session = Depends(get_db),
    current=Depends(require_contabilidad),
):
    return _cambiar_estado(db, current, id_centro, payload, "CERRADO", "ABIERTO")


def _validar_fechas_proyecto(inicio: date, fin: date | None) -> None:
    if fin and fin < inicio:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="La fecha de finalización no puede ser anterior a la de inicio del proyecto.",
        )


@router.post("/{id_centro}/fechas-proyecto", response_model=CentroCostoDetalleOut)
def ajustar_fechas_proyecto(
    id_centro: int,
    payload: FechasProyectoIn,
    db: Session = Depends(get_db),
    current=Depends(require_contabilidad),
):
    """Ajusta la proyección de inicio y la fecha de fin del proyecto. El cambio
    queda en el historial con el motivo. No cambia el estado del centro."""
    centro = _detalle(db, id_centro)
    motivo = (payload.motivo or "").strip()

    if not motivo:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="El motivo es obligatorio.")

    _validar_fechas_proyecto(payload.fecha_inicio_proyecto, payload.fecha_fin_proyecto)

    if (
        centro["fecha_inicio_proyecto"] == payload.fecha_inicio_proyecto
        and centro["fecha_fin_proyecto"] == payload.fecha_fin_proyecto
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Las fechas no cambiaron.",
        )

    usuario = _nombre_usuario(current)

    try:
        db.execute(
            text("""
                SELECT set_config('app.usuario', :usuario, true),
                       set_config('app.motivo', :motivo, true),
                       set_config('app.fecha_efectiva', (now() AT TIME ZONE 'America/Bogota')::date::text, true)
            """),
            {"usuario": usuario, "motivo": motivo},
        )
        db.execute(
            text("""
                UPDATE public."CentroCostoContable"
                SET "FechaInicioProyecto" = :inicio,
                    "FechaFinProyecto"    = :fin,
                    "FechaActualizacion"  = now(),
                    "ActualizadoPor"      = :usuario
                WHERE "IdCentroCostoContable" = :id
            """),
            {
                "id": id_centro,
                "inicio": payload.fecha_inicio_proyecto,
                "fin": payload.fecha_fin_proyecto,
                "usuario": usuario,
            },
        )
        db.commit()
    except Exception:
        db.rollback()
        raise

    detalle = _detalle(db, id_centro)
    contabilidad_sheets_service.programar_sincronizacion(usuario, f"Fechas del proyecto de {detalle['codigo']}")
    return detalle


# ─────────────────────────────────────────────
# Creación
# ─────────────────────────────────────────────
FORMATO_CODIGO = re.compile(r"^[A-Z0-9&]{2,20}$")


def _error(codigo_http: int, detalle: str) -> HTTPException:
    return HTTPException(status_code=codigo_http, detail=detalle)


def _normalizar_codigo(codigo: str, etiqueta: str) -> str:
    codigo = (codigo or "").strip().upper()

    if not FORMATO_CODIGO.fullmatch(codigo):
        raise _error(
            status.HTTP_400_BAD_REQUEST,
            f"El código de {etiqueta} solo admite letras mayúsculas y números (2 a 20).",
        )

    return codigo


def _texto_obligatorio(valor: str | None, etiqueta: str) -> str:
    valor = (valor or "").strip()

    if not valor:
        raise _error(status.HTTP_400_BAD_REQUEST, f"Falta {etiqueta[:1].lower()}{etiqueta[1:]}.")

    return valor


def _comparable(valor: str) -> str:
    """Minúsculas y sin tildes, para no repetir nombres ("Jardinería" = "jardineria")."""
    sin_tildes = unicodedata.normalize("NFD", valor or "")
    return "".join(c for c in sin_tildes if unicodedata.category(c) != "Mn").lower().strip()


def _buscar_por_codigo(db: Session, tabla: str, columna_id: str, codigo: str):
    return db.execute(
        text(f"""
            SELECT "{columna_id}" AS id, "Codigo" AS codigo
            FROM public."{tabla}"
            WHERE upper("Codigo") = :codigo
        """),
        {"codigo": codigo},
    ).mappings().first()


def _validar_nombre_libre(db: Session, tabla: str, nombre: str, etiqueta: str) -> None:
    filas = db.execute(text(f'SELECT "Codigo", "Nombre" FROM public."{tabla}"')).all()
    repetido = next((f for f in filas if _comparable(f.Nombre) == _comparable(nombre)), None)

    if repetido:
        raise _error(
            status.HTTP_409_CONFLICT,
            f"{etiqueta} {repetido.Nombre} ya existe con el código {repetido.Codigo}.",
        )


def _resolver_catalogo(
    db: Session, tabla: str, columna_id: str, entrada: CatalogoIn, etiqueta: str
) -> int:
    """Id de una línea o servicio existente, o lo crea si viene como nuevo."""
    codigo = _normalizar_codigo(entrada.codigo, etiqueta)
    existente = _buscar_por_codigo(db, tabla, columna_id, codigo)

    if not entrada.nuevo:
        if not existente:
            raise _error(status.HTTP_400_BAD_REQUEST, f"No existe {etiqueta} {codigo}.")
        return existente["id"]

    if existente:
        raise _error(status.HTTP_409_CONFLICT, f"Ya existe {etiqueta} con el código {codigo}.")

    nombre = _texto_obligatorio(entrada.nombre, f"El nombre de {etiqueta}")
    _validar_nombre_libre(db, tabla, nombre, f"El nombre de {etiqueta}")

    return db.execute(
        text(f"""
            INSERT INTO public."{tabla}" ("Codigo", "Nombre")
            VALUES (:codigo, :nombre)
            RETURNING "{columna_id}"
        """),
        {"codigo": codigo, "nombre": nombre},
    ).scalar()


def _resolver_proyecto(db: Session, payload: CrearCentroCostoIn, usuario: str) -> tuple[int, str]:
    if bool(payload.proyecto_codigo) == bool(payload.proyecto_nuevo):
        raise _error(
            status.HTTP_400_BAD_REQUEST,
            "Indica un proyecto existente o los datos del cliente nuevo (solo uno).",
        )

    if payload.proyecto_codigo:
        codigo = _normalizar_codigo(payload.proyecto_codigo, "el proyecto")
        proyecto = _buscar_por_codigo(db, "ProyectoContable", "IdProyectoContable", codigo)
        if not proyecto:
            raise _error(status.HTTP_400_BAD_REQUEST, f"No existe el proyecto {codigo}.")
        return proyecto["id"], codigo

    nuevo = payload.proyecto_nuevo
    codigo = _normalizar_codigo(nuevo.codigo, "el proyecto")

    if _buscar_por_codigo(db, "ProyectoContable", "IdProyectoContable", codigo):
        raise _error(status.HTTP_409_CONFLICT, f"Ya existe el proyecto {codigo}.")

    cliente = db.execute(
        text('SELECT "RazonSocial" FROM public."ClienteContable" WHERE "Nit" = :nit'),
        {"nit": nuevo.nit},
    ).scalar()

    if cliente:
        raise _error(
            status.HTTP_409_CONFLICT,
            f"El NIT {nuevo.nit} ya está registrado ({cliente}). Usa el cliente existente.",
        )

    socio = (nuevo.codigo_socio_negocio or "").strip().upper()
    if not re.fullmatch(r"[A-Z0-9._-]{1,30}", socio):
        raise _error(
            status.HTTP_400_BAD_REQUEST,
            "El código del socio de negocio solo admite letras, números, punto, guion y guion bajo (máximo 30).",
        )

    socio_registrado = db.execute(
        text('SELECT "RazonSocial" FROM public."ClienteContable" WHERE "CodigoSocioNegocio" = :socio'),
        {"socio": socio},
    ).scalar()

    if socio_registrado:
        raise _error(
            status.HTTP_409_CONFLICT,
            f"El código de socio de negocio {socio} ya es de {socio_registrado}.",
        )

    # El nombre del proyecto es la misma razón social.
    razon_social = _texto_obligatorio(nuevo.razon_social, "El nombre del proyecto / razón social")

    id_cliente = db.execute(
        text("""
            INSERT INTO public."ClienteContable" ("Nit", "RazonSocial", "CodigoSocioNegocio", "CreadoPor")
            VALUES (:nit, :razon_social, :socio, :usuario)
            RETURNING "IdClienteContable"
        """),
        {"nit": nuevo.nit, "razon_social": razon_social, "socio": socio, "usuario": usuario},
    ).scalar()

    id_proyecto = db.execute(
        text("""
            INSERT INTO public."ProyectoContable" ("Codigo", "Nombre", "IdClienteContable", "CreadoPor")
            VALUES (:codigo, :nombre, :id_cliente, :usuario)
            RETURNING "IdProyectoContable"
        """),
        {"codigo": codigo, "nombre": razon_social, "id_cliente": id_cliente, "usuario": usuario},
    ).scalar()

    return id_proyecto, codigo


def _resolver_departamento(db: Session, entrada: DepartamentoIn) -> int:
    codigo = _normalizar_codigo(entrada.codigo, "el departamento")
    existente = _buscar_por_codigo(db, "DepartamentoContable", "IdDepartamentoContable", codigo)

    if not entrada.nuevo:
        if not existente:
            raise _error(status.HTTP_400_BAD_REQUEST, f"No existe el departamento {codigo}.")
        return existente["id"]

    if existente:
        raise _error(status.HTTP_409_CONFLICT, f"Ya existe el departamento {codigo}.")

    if not entrada.id_departamento_geografico:
        raise _error(
            status.HTTP_400_BAD_REQUEST,
            "Elige el departamento de Colombia del CEN 2 nuevo.",
        )

    nombre = _texto_obligatorio(entrada.nombre, "El nombre del departamento")
    _validar_nombre_libre(db, "DepartamentoContable", nombre, "El departamento")

    # Una ubicación (municipio, o departamento sin municipio) tiene un solo CEN 2.
    misma_ubicacion = db.execute(
        text("""
            SELECT "Codigo"
            FROM public."DepartamentoContable"
            WHERE "IdDepartamentoGeografico" = :id_geografico
              AND "IdMunicipio" IS NOT DISTINCT FROM :id_municipio
        """),
        {
            "id_geografico": entrada.id_departamento_geografico,
            "id_municipio": entrada.id_municipio,
        },
    ).scalar()

    if misma_ubicacion:
        raise _error(
            status.HTTP_409_CONFLICT,
            f"Esa ubicación ya tiene el CEN 2 {misma_ubicacion}.",
        )

    try:
        # El trigger valida que el municipio sea del departamento elegido.
        with db.begin_nested():
            return db.execute(
                text("""
                    INSERT INTO public."DepartamentoContable"
                        ("Codigo", "Nombre", "IdDepartamentoGeografico", "IdMunicipio")
                    VALUES (:codigo, :nombre, :id_geografico, :id_municipio)
                    RETURNING "IdDepartamentoContable"
                """),
                {
                    "codigo": codigo,
                    "nombre": nombre,
                    "id_geografico": entrada.id_departamento_geografico,
                    "id_municipio": entrada.id_municipio,
                },
            ).scalar()
    except Exception as error:
        raise _error(
            status.HTTP_400_BAD_REQUEST,
            "La ubicación del departamento no es válida (el municipio debe ser del departamento elegido).",
        ) from error


def _resolver_sede(db: Session, entrada: SedeIn, id_proyecto: int, codigo_proyecto: str, usuario: str) -> int:
    codigo = _normalizar_codigo(entrada.codigo, "la sede")
    existente = db.execute(
        text("""
            SELECT "IdSedeContable" AS id, "IdProyectoContable" AS id_proyecto
            FROM public."SedeContable"
            WHERE upper("Codigo") = :codigo
        """),
        {"codigo": codigo},
    ).mappings().first()

    if not entrada.nuevo:
        if not existente:
            raise _error(status.HTTP_400_BAD_REQUEST, f"No existe la sede {codigo}.")
        if existente["id_proyecto"] != id_proyecto:
            raise _error(
                status.HTTP_400_BAD_REQUEST,
                f"La sede {codigo} no pertenece al proyecto {codigo_proyecto}.",
            )
        return existente["id"]

    if existente:
        raise _error(status.HTTP_409_CONFLICT, f"Ya existe la sede {codigo}.")

    return db.execute(
        text("""
            INSERT INTO public."SedeContable" ("Codigo", "Descripcion", "IdProyectoContable", "CreadoPor")
            VALUES (:codigo, :descripcion, :id_proyecto, :usuario)
            RETURNING "IdSedeContable"
        """),
        {
            "codigo": codigo,
            "descripcion": _texto_obligatorio(entrada.descripcion, "La descripción de la sede"),
            "id_proyecto": id_proyecto,
            "usuario": usuario,
        },
    ).scalar()


@router.post("", response_model=CentroCostoDetalleOut, status_code=status.HTTP_201_CREATED)
def crear_centro_costo(
    payload: CrearCentroCostoIn,
    db: Session = Depends(get_db),
    current=Depends(require_contabilidad),
):
    """Crea un centro de costo ABIERTO con fecha de apertura de hoy (Bogotá).
    En la misma transacción crea lo que venga como nuevo: cliente y proyecto,
    departamento, sede, línea y servicio. Si algo falla no queda nada."""
    usuario = _nombre_usuario(current)
    observacion = (payload.observacion or "").strip()
    _validar_fechas_proyecto(payload.fecha_inicio_proyecto, payload.fecha_fin_proyecto)

    try:
        id_proyecto, codigo_proyecto = _resolver_proyecto(db, payload, usuario)
        id_departamento = _resolver_departamento(db, payload.departamento)
        id_sede = _resolver_sede(db, payload.sede, id_proyecto, codigo_proyecto, usuario)
        id_linea = _resolver_catalogo(
            db, "LineaNegocio", "IdLineaNegocio", payload.linea, "la línea de negocio"
        )
        id_servicio = _resolver_catalogo(
            db, "ServicioAsociado", "IdServicioAsociado", payload.servicio, "el servicio asociado"
        )

        if db.execute(
            text("""
                SELECT 1 FROM public."CentroCostoContable"
                WHERE "IdSedeContable" = :sede AND "IdDepartamentoContable" = :departamento
                  AND "IdLineaNegocio" = :linea AND "IdServicioAsociado" = :servicio
            """),
            {"sede": id_sede, "departamento": id_departamento, "linea": id_linea, "servicio": id_servicio},
        ).first():
            raise _error(
                status.HTTP_409_CONFLICT,
                "Ya existe un centro de costo con esa combinación de sede, departamento, línea y servicio.",
            )

        # Misma regla de la carga inicial: una sede con centros en varios
        # departamentos queda pendiente de revisión.
        otros_departamentos = db.execute(
            text("""
                SELECT string_agg(DISTINCT D."Codigo", ', ' ORDER BY D."Codigo")
                FROM public."CentroCostoContable" CC
                JOIN public."DepartamentoContable" D
                  ON D."IdDepartamentoContable" = CC."IdDepartamentoContable"
                WHERE CC."IdSedeContable" = :sede
                  AND CC."IdDepartamentoContable" <> :departamento
            """),
            {"sede": id_sede, "departamento": id_departamento},
        ).scalar()

        observacion_revision = None
        if otros_departamentos:
            codigo_sede = payload.sede.codigo.strip().upper()
            codigo_departamento = payload.departamento.codigo.strip().upper()
            observacion_revision = (
                f"La sede {codigo_sede} tiene centros en varios departamentos "
                f"({otros_departamentos}, {codigo_departamento}); confirmar el correcto."
            )[:500]

        hoy = db.execute(text("SELECT (now() AT TIME ZONE 'America/Bogota')::date")).scalar()

        # Datos para el registro CREADO que escribe el trigger (solo esta transacción).
        db.execute(
            text("""
                SELECT set_config('app.usuario', :usuario, true),
                       set_config('app.motivo', :motivo, true),
                       set_config('app.fecha_efectiva', :fecha, true)
            """),
            {"usuario": usuario, "motivo": observacion, "fecha": hoy.isoformat()},
        )

        id_centro = db.execute(
            text("""
                INSERT INTO public."CentroCostoContable" (
                    "IdSedeContable", "IdDepartamentoContable", "IdLineaNegocio",
                    "IdServicioAsociado", "Estado", "FechaApertura",
                    "FechaInicioProyecto", "FechaFinProyecto",
                    "PendienteRevision", "ObservacionRevision", "CreadoPor"
                ) VALUES (
                    :sede, :departamento, :linea, :servicio, 'ABIERTO', :hoy,
                    :inicio_proyecto, :fin_proyecto,
                    :pendiente, :observacion_revision, :usuario
                )
                RETURNING "IdCentroCostoContable"
            """),
            {
                "sede": id_sede,
                "departamento": id_departamento,
                "linea": id_linea,
                "servicio": id_servicio,
                "hoy": hoy,
                "inicio_proyecto": payload.fecha_inicio_proyecto,
                "fin_proyecto": payload.fecha_fin_proyecto,
                "pendiente": observacion_revision is not None,
                "observacion_revision": observacion_revision,
                "usuario": usuario,
            },
        ).scalar()

        db.commit()
    except HTTPException:
        db.rollback()
        raise
    except IntegrityError as error:
        # Otro usuario registró lo mismo al mismo tiempo.
        db.rollback()
        raise _error(
            status.HTTP_409_CONFLICT,
            "Alguno de los datos ya fue registrado por otro usuario. Actualiza e intenta de nuevo.",
        ) from error
    except Exception:
        db.rollback()
        raise

    detalle = _detalle(db, id_centro)
    contabilidad_sheets_service.programar_sincronizacion(usuario, f"Creación de {detalle['codigo']}")
    return detalle
