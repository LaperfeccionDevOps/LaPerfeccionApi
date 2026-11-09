# ruff: noqa: B008

import re
import unicodedata
from datetime import date, datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Path, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from infrastructure.db.deps import get_db
from infrastructure.security.auth_dependencies import get_current_user


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
    fecha_apertura: date | None = None
    fecha_cierre: date | None = None
    pendiente_revision: bool
    observacion_revision: str | None = None
    fecha_creacion: datetime
    # Operarios de la asignación vigente (0 si no tiene).
    operarios: int = 0


class CantidadOut(BaseModel):
    nombre: str
    operarios: int


class ResumenAsignacionOut(BaseModel):
    # Sobre los centros del resultado filtrado, con su asignación vigente.
    centros_con_asignacion: int
    abiertos_sin_asignacion: int
    operarios: int
    operarios_con_nocturnas: int
    operarios_con_dominicales: int
    operarios_con_nocturnas_dominicales: int
    # Suma semanal de todos los operarios (cantidad × horas por operario).
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
    creado_por: str | None = None
    fecha_actualizacion: datetime | None = None
    actualizado_por: str | None = None
    historial: list[MovimientoHistorialOut] = []


class ProyectoNuevoIn(BaseModel):
    # Cliente (NIT con dígito de verificación) y su proyecto (CEN 1).
    nit: str = Field(..., pattern=r"^[0-9]{5,15}-[0-9]$")
    razon_social: str = Field(..., min_length=1, max_length=200)
    codigo: str = Field(..., min_length=1, max_length=20)
    nombre: str = Field(..., min_length=1, max_length=200)


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
    # Opcional; queda como motivo del registro CREADO en el historial.
    observacion: str | None = Field(None, max_length=500)


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
                   C."RazonSocial"        AS cliente
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
            SELECT "IdSedeContable"     AS id,
                   "Codigo"             AS codigo,
                   "Descripcion"        AS nombre,
                   "IdProyectoContable" AS id_proyecto
            FROM public."SedeContable"
            ORDER BY "Codigo"
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
      AND (CAST(:estado AS varchar) IS NULL OR CC."Estado" = :estado)
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
    estado: Literal["ABIERTO", "CERRADO"] | None = None,
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
                   COUNT(*) FILTER (WHERE CC."PendienteRevision")   AS pendientes_revision
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
            SELECT F.id, AD."CantidadOperarios" AS cantidad,
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
                   COALESCE(SUM(cantidad), 0)                                    AS operarios,
                   COALESCE(SUM(cantidad) FILTER (WHERE nocturnas > 0), 0)       AS operarios_con_nocturnas,
                   COALESCE(SUM(cantidad) FILTER (WHERE dominicales > 0), 0)     AS operarios_con_dominicales,
                   COALESCE(SUM(cantidad) FILTER (WHERE nocturnas_dominicales > 0), 0)
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

    def agrupado(columna: str) -> list[dict]:
        filas = db.execute(
            text(sql_lineas + f"""
                SELECT {columna} AS nombre, SUM(cantidad) AS operarios
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
                   CC."FechaApertura"        AS fecha_apertura,
                   CC."FechaCierre"          AS fecha_cierre,
                   CC."PendienteRevision"    AS pendiente_revision,
                   CC."ObservacionRevision"  AS observacion_revision,
                   COALESCE((
                       SELECT SUM(AD."CantidadOperarios")
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
           CC."FechaApertura"        AS fecha_apertura,
           CC."FechaCierre"          AS fecha_cierre,
           CC."PendienteRevision"    AS pendiente_revision,
           CC."ObservacionRevision"  AS observacion_revision,
           COALESCE((
               SELECT SUM(AD."CantidadOperarios")
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

    return _detalle(db, id_centro)


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
        raise _error(status.HTTP_400_BAD_REQUEST, f"{etiqueta} es obligatorio.")

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

    id_cliente = db.execute(
        text("""
            INSERT INTO public."ClienteContable" ("Nit", "RazonSocial", "CreadoPor")
            VALUES (:nit, :razon_social, :usuario)
            RETURNING "IdClienteContable"
        """),
        {
            "nit": nuevo.nit,
            "razon_social": _texto_obligatorio(nuevo.razon_social, "La razón social"),
            "usuario": usuario,
        },
    ).scalar()

    id_proyecto = db.execute(
        text("""
            INSERT INTO public."ProyectoContable" ("Codigo", "Nombre", "IdClienteContable", "CreadoPor")
            VALUES (:codigo, :nombre, :id_cliente, :usuario)
            RETURNING "IdProyectoContable"
        """),
        {
            "codigo": codigo,
            "nombre": _texto_obligatorio(nuevo.nombre, "El nombre del proyecto"),
            "id_cliente": id_cliente,
            "usuario": usuario,
        },
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
                    "PendienteRevision", "ObservacionRevision", "CreadoPor"
                ) VALUES (
                    :sede, :departamento, :linea, :servicio, 'ABIERTO', :hoy,
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

    return _detalle(db, id_centro)
