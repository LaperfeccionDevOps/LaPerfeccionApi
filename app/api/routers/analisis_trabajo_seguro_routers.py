# ruff: noqa: B008

from datetime import date, datetime, timedelta
from typing import Literal
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from api.routers.permisos_trabajo_alturas_routers import (
    TIPOS_OPCION_TAREA,
    OpcionSeleccionadaOut,
    _decodificar_firma,
    _persona_contratada,
    _texto_requerido,
    ZONA_HORARIA,
    require_operaciones_alturas,
)
from infrastructure.db.deps import get_db
from services.analisis_trabajo_seguro_pdf_service import (
    generar_pdf_analisis_trabajo_seguro,
)


# Los buscadores de clientes y de personal contratado se comparten con
# permisos de trabajo en alturas (/api/operaciones/alturas/clientes y
# /api/operaciones/alturas/trabajadores/buscar).

# Listas del catálogo "OpcionPermisoAlturas" que se eligen en el bloque 3
# (Equipos): campo de la API -> (Tipo en la base, nombre para los mensajes).
LISTAS_EQUIPOS = {
    "sistemas_acceso": (TIPOS_OPCION_TAREA["sistemas_acceso"], "sistemas de acceso"),
    "herramientas_manuales": (
        TIPOS_OPCION_TAREA["herramientas"],
        "herramientas manuales",
    ),
    "herramientas_electricas": ("HERRAMIENTA_ELECTRICA", "herramientas eléctricas"),
    "permisos_requeridos": ("PERMISO_REQUERIDO", "permisos requeridos"),
}

# Preguntas de la verificación diaria (bloque 5) en "ItemPermisoAlturas".
TIPO_ITEM_VERIFICACION_DIARIA = "ATS_DIARIA"

# Estados de cada día de la verificación diaria.
DIA_DILIGENCIADO = "DILIGENCIADO"
DIA_PENDIENTE = "PENDIENTE"
DIA_FUTURO = "FUTURO"

# Estados del análisis. Con el visto bueno del coordinador queda APROBADO y
# ya no se modifican los bloques 1 a 4 (la verificación diaria sigue abierta).
ESTADO_EN_DILIGENCIAMIENTO = "EN_DILIGENCIAMIENTO"
ESTADO_APROBADO = "APROBADO"

# Opción "Otro" de los permisos requeridos: exige escribir cuál.
CODIGO_PERMISO_OTRO = "PER_OT"

# Las opciones "No aplica" tienen un código terminado en este sufijo
# (p. ej. PER_NA, HEL_NA) y no se eligen junto con otras de la misma lista.
SUFIJO_NO_APLICA = "_NA"

router = APIRouter(
    prefix="/api/operaciones/alturas/analisis-trabajo-seguro",
    tags=["Operaciones - Alturas"],
)


class AnalisisTrabajoSeguroIn(BaseModel):
    # Temporal: mientras no existan los roles, el responsable puede ser
    # cualquier persona contratada. Luego se tomará del usuario autenticado.
    id_registro_personal_responsable: int = Field(..., gt=0)
    id_cliente: int = Field(..., gt=0)
    # Lugar físico del cliente donde se hace la tarea.
    lugar_trabajo: str = Field(..., max_length=300)
    # Se diligencia por semana o por cambio de actividad; no puede ser
    # anterior a hoy.
    fecha_finalizacion_actividad: date
    altura_aproximada_metros: Decimal = Field(
        ..., gt=0, le=Decimal("9999.99"), decimal_places=2
    )


class AnalisisTrabajoSeguroOut(BaseModel):
    id_analisis_trabajo_seguro: int
    id_registro_personal_responsable: int
    responsable: str
    numero_identificacion_responsable: str
    id_cliente: int
    cliente: str
    lugar_trabajo: str
    fecha_finalizacion_actividad: date
    altura_aproximada_metros: Decimal
    fecha_creacion: datetime
    cantidad_trabajadores: int = 0
    # 3. Equipos (catálogo OpcionPermisoAlturas).
    sistemas_acceso: list[OpcionSeleccionadaOut] = []
    herramientas_manuales: list[OpcionSeleccionadaOut] = []
    herramientas_electricas: list[OpcionSeleccionadaOut] = []
    # "Para este trabajo se necesita permiso de:"
    permisos_requeridos: list[OpcionSeleccionadaOut] = []
    descripcion_tarea: str | None = None
    otro_permiso_requerido: str | None = None
    # 4. Asignación de tareas e identificación de peligros.
    cantidad_tareas: int = 0
    # Tareas que aún no tienen ningún peligro (deben tener al menos uno).
    tareas_sin_peligro: int = 0
    # 5. Verificación diaria: días hasta hoy sin diligenciar y diligenciados.
    dias_pendientes: int = 0
    dias_diligenciados: int = 0
    # 6. Visto bueno del coordinador de alturas.
    estado: str = ESTADO_EN_DILIGENCIAMIENTO
    id_registro_personal_coordinador: int | None = None
    coordinador: str | None = None
    numero_identificacion_coordinador: str | None = None
    fecha_visto_bueno: datetime | None = None


class VistoBuenoIn(BaseModel):
    # El visto bueno lo da el responsable del análisis (temporal: luego será el
    # usuario autenticado); solo se recibe su firma como data URL PNG. El
    # tamaño se valida en _decodificar_firma.
    firma_png: str


class EquiposAnalisisIn(BaseModel):
    sistemas_acceso: list[int] = Field(..., min_length=1)
    herramientas_manuales: list[int] = Field(..., min_length=1)
    herramientas_electricas: list[int] = Field(..., min_length=1)
    permisos_requeridos: list[int] = Field(..., min_length=1)
    descripcion_tarea: str = Field(..., max_length=4000)
    # Obligatorio si se marcó "Otro" en los permisos requeridos.
    otro_permiso_requerido: str | None = Field(None, max_length=300)


class PreguntaDiariaOut(BaseModel):
    id_item_permiso_alturas: int
    codigo: str
    texto: str
    # Respuesta que indica un problema ("SI" o "NO").
    respuesta_alerta: str | None = None


class RegistroDiaOut(BaseModel):
    id_analisis_trabajo_seguro_dia: int
    id_registro_personal: int
    diligenciado_por: str
    numero_identificacion: str
    observaciones: str | None = None
    diligenciado_tarde: bool
    fecha_registro: datetime
    # id_item_permiso_alturas -> "SI" / "NO" / "NA"
    respuestas: dict[int, str]


class DiaVerificacionOut(BaseModel):
    fecha: date
    estado: Literal["DILIGENCIADO", "PENDIENTE", "FUTURO"]
    registro: RegistroDiaOut | None = None


class VerificacionDiariaOut(BaseModel):
    hoy: date
    preguntas: list[PreguntaDiariaOut]
    dias: list[DiaVerificacionOut]


class RespuestaDiariaIn(BaseModel):
    id_item_permiso_alturas: int = Field(..., gt=0)
    respuesta: Literal["SI", "NO", "NA"]


class DiaVerificacionIn(BaseModel):
    fecha: date
    # Quien diligencia ese día.
    id_registro_personal: int = Field(..., gt=0)
    respuestas: list[RespuestaDiariaIn] = Field(..., min_length=1)
    observaciones: str | None = Field(None, max_length=1000)


class MatrizPeligroOut(BaseModel):
    id_matriz_peligro: int
    id_riesgo_matriz_peligro: int
    riesgo: str
    peligro: str
    peligro_adicional: str | None = None
    riesgo_asociado: str
    consecuencia_asociada: str


class PeligroTareaOut(BaseModel):
    id_analisis_trabajo_seguro_tarea_peligro: int
    id_matriz_peligro: int
    # Copia de los textos de la matriz al momento de elegir el peligro.
    riesgo: str
    peligro: str
    peligro_adicional: str | None = None
    riesgo_asociado: str
    consecuencia_asociada: str


class PeligroTareaIn(BaseModel):
    id_matriz_peligro: int = Field(..., gt=0)


class TareaAnalisisIn(BaseModel):
    paso_detallado: str = Field(..., max_length=4000)
    # Cada tarea se crea con su primer peligro: nunca queda sin peligros.
    id_matriz_peligro: int = Field(..., gt=0)


class TareaEdicionIn(BaseModel):
    paso_detallado: str = Field(..., max_length=4000)


class TareaAnalisisOut(BaseModel):
    id_analisis_trabajo_seguro_tarea: int
    id_analisis_trabajo_seguro: int
    orden: int
    paso_detallado: str
    fecha_creacion: datetime
    peligros: list[PeligroTareaOut] = []


class AnalisisTrabajadorIn(BaseModel):
    id_registro_personal: int = Field(..., gt=0)
    # Firma como data URL PNG ("data:image/png;base64,..."). El tamaño se
    # valida en _decodificar_firma.
    firma_png: str


class AnalisisTrabajadorOut(BaseModel):
    id_analisis_trabajo_seguro_trabajador: int
    id_analisis_trabajo_seguro: int
    id_registro_personal: int
    numero_identificacion: str
    nombre_completo: str
    fecha_firma: datetime


SQL_ANALISIS = """
    SELECT A."IdAnalisisTrabajoSeguro"       AS id_analisis_trabajo_seguro,
           A."IdRegistroPersonalResponsable" AS id_registro_personal_responsable,
           TRIM(RR."Nombres" || ' ' || RR."Apellidos") AS responsable,
           RR."NumeroIdentificacion"         AS numero_identificacion_responsable,
           A."IdCliente"                     AS id_cliente,
           C."Nombre"                        AS cliente,
           A."LugarTrabajo"                  AS lugar_trabajo,
           A."FechaFinalizacionActividad"    AS fecha_finalizacion_actividad,
           A."AlturaAproximadaMetros"        AS altura_aproximada_metros,
           A."DescripcionTarea"              AS descripcion_tarea,
           A."OtroPermisoRequerido"          AS otro_permiso_requerido,
           A."Estado"                        AS estado,
           A."IdRegistroPersonalCoordinador" AS id_registro_personal_coordinador,
           TRIM(RC."Nombres" || ' ' || RC."Apellidos") AS coordinador,
           RC."NumeroIdentificacion"         AS numero_identificacion_coordinador,
           A."FechaVistoBueno"               AS fecha_visto_bueno,
           A."FechaCreacion"                 AS fecha_creacion,
           (
               SELECT COUNT(*)
               FROM public."AnalisisTrabajoSeguroTrabajador" T
               WHERE T."IdAnalisisTrabajoSeguro" = A."IdAnalisisTrabajoSeguro"
           )                                 AS cantidad_trabajadores,
           (
               SELECT COUNT(*)
               FROM public."AnalisisTrabajoSeguroTarea" TA
               WHERE TA."IdAnalisisTrabajoSeguro" = A."IdAnalisisTrabajoSeguro"
           )                                 AS cantidad_tareas,
           (
               SELECT COUNT(*)
               FROM public."AnalisisTrabajoSeguroTarea" TA
               WHERE TA."IdAnalisisTrabajoSeguro" = A."IdAnalisisTrabajoSeguro"
                 AND NOT EXISTS (
                     SELECT 1
                     FROM public."AnalisisTrabajoSeguroTareaPeligro" TP
                     WHERE TP."IdAnalisisTrabajoSeguroTarea"
                           = TA."IdAnalisisTrabajoSeguroTarea"
                 )
           )                                 AS tareas_sin_peligro,
           (
               SELECT COUNT(*)
               FROM generate_series(
                   (A."FechaCreacion" AT TIME ZONE 'America/Bogota')::date,
                   LEAST(
                       A."FechaFinalizacionActividad",
                       (now() AT TIME ZONE 'America/Bogota')::date
                   ),
                   interval '1 day'
               ) AS D(dia)
               WHERE NOT EXISTS (
                   SELECT 1
                   FROM public."AnalisisTrabajoSeguroDia" AD
                   WHERE AD."IdAnalisisTrabajoSeguro" = A."IdAnalisisTrabajoSeguro"
                     AND AD."Fecha" = D.dia::date
               )
           )                                 AS dias_pendientes,
           (
               SELECT COUNT(*)
               FROM public."AnalisisTrabajoSeguroDia" AD
               WHERE AD."IdAnalisisTrabajoSeguro" = A."IdAnalisisTrabajoSeguro"
           )                                 AS dias_diligenciados
    FROM public."AnalisisTrabajoSeguro" A
    JOIN public."Cliente" C ON C."IdCliente" = A."IdCliente"
    JOIN public."RegistroPersonal" RR
      ON RR."IdRegistroPersonal" = A."IdRegistroPersonalResponsable"
    LEFT JOIN public."RegistroPersonal" RC
      ON RC."IdRegistroPersonal" = A."IdRegistroPersonalCoordinador"
"""

SQL_TRABAJADORES_ANALISIS = """
    SELECT T."IdAnalisisTrabajoSeguroTrabajador" AS id_analisis_trabajo_seguro_trabajador,
           T."IdAnalisisTrabajoSeguro"           AS id_analisis_trabajo_seguro,
           T."IdRegistroPersonal"                AS id_registro_personal,
           R."NumeroIdentificacion"              AS numero_identificacion,
           TRIM(R."Nombres" || ' ' || R."Apellidos") AS nombre_completo,
           T."FechaFirma"                        AS fecha_firma
    FROM public."AnalisisTrabajoSeguroTrabajador" T
    JOIN public."RegistroPersonal" R
      ON R."IdRegistroPersonal" = T."IdRegistroPersonal"
"""


def _obtener_analisis(db: Session, id_analisis: int) -> dict:
    fila = db.execute(
        text(SQL_ANALISIS + ' WHERE A."IdAnalisisTrabajoSeguro" = :id_analisis'),
        {"id_analisis": id_analisis},
    ).mappings().first()

    if fila is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="El análisis de trabajo seguro no existe.",
        )

    elegidas = db.execute(
        text("""
            SELECT O."Tipo"                   AS tipo,
                   O."IdOpcionPermisoAlturas" AS id_opcion_permiso_alturas,
                   O."Nombre"                 AS nombre
            FROM public."AnalisisTrabajoSeguroOpcion" AO
            JOIN public."OpcionPermisoAlturas" O
              ON O."IdOpcionPermisoAlturas" = AO."IdOpcionPermisoAlturas"
            WHERE AO."IdAnalisisTrabajoSeguro" = :id_analisis
            ORDER BY O."Orden"
        """),
        {"id_analisis": id_analisis},
    ).mappings().all()

    listas = {
        campo: [
            {
                "id_opcion_permiso_alturas": o["id_opcion_permiso_alturas"],
                "nombre": o["nombre"],
            }
            for o in elegidas
            if o["tipo"] == tipo
        ]
        for campo, (tipo, _) in LISTAS_EQUIPOS.items()
    }

    return {**fila, **listas}


def _validar_editable(db: Session, id_analisis: int) -> None:
    """El análisis existe y no tiene visto bueno (bloques 1 a 4 editables)."""
    estado = db.execute(
        text("""
            SELECT "Estado"
            FROM public."AnalisisTrabajoSeguro"
            WHERE "IdAnalisisTrabajoSeguro" = :id_analisis
        """),
        {"id_analisis": id_analisis},
    ).scalar()

    if estado is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="El análisis de trabajo seguro no existe.",
        )

    if estado != ESTADO_EN_DILIGENCIAMIENTO:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="El análisis ya tiene visto bueno y no se puede modificar.",
        )


@router.get("", response_model=list[AnalisisTrabajoSeguroOut])
def listar_analisis(
    # Temporal: mientras no existan los roles, la consulta se filtra por el
    # responsable que se elige en pantalla.
    id_registro_personal_responsable: int | None = Query(None, gt=0),
    db: Session = Depends(get_db),
    _current=Depends(require_operaciones_alturas),
):
    filas = db.execute(
        text(
            SQL_ANALISIS
            + """
            WHERE CAST(:id_responsable AS bigint) IS NULL
               OR A."IdRegistroPersonalResponsable" = :id_responsable
            ORDER BY A."IdAnalisisTrabajoSeguro" DESC
            LIMIT 200
            """
        ),
        {"id_responsable": id_registro_personal_responsable},
    ).mappings().all()

    return [dict(fila) for fila in filas]


@router.post(
    "",
    response_model=AnalisisTrabajoSeguroOut,
    status_code=status.HTTP_201_CREATED,
)
def crear_analisis(
    payload: AnalisisTrabajoSeguroIn,
    db: Session = Depends(get_db),
    _current=Depends(require_operaciones_alturas),
):
    cliente_activo = db.execute(
        text("""
            SELECT 1
            FROM public."Cliente"
            WHERE "IdCliente" = :id_cliente
              AND COALESCE("Activo", TRUE)
        """),
        {"id_cliente": payload.id_cliente},
    ).scalar()

    if not cliente_activo:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="El cliente seleccionado no existe o está inactivo.",
        )

    lugar_trabajo = _texto_requerido(payload.lugar_trabajo, "Lugar de trabajo")
    _persona_contratada(db, payload.id_registro_personal_responsable, "Responsable")

    hoy = db.execute(
        text("SELECT (now() AT TIME ZONE :zona)::date"),
        {"zona": ZONA_HORARIA},
    ).scalar()

    if payload.fecha_finalizacion_actividad < hoy:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "La fecha de finalización de la actividad no puede ser "
                "anterior a hoy."
            ),
        )

    # El análisis cubre una semana real (lunes a domingo). Si la actividad
    # continúa, se crea un análisis nuevo la semana siguiente.
    domingo = hoy + timedelta(days=6 - hoy.weekday())

    if payload.fecha_finalizacion_actividad > domingo:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "El análisis cubre solo la semana actual: la fecha de "
                f"finalización no puede pasar del domingo {domingo:%d/%m/%Y}. "
                "Si la actividad continúa, crea un análisis nuevo la próxima semana."
            ),
        )

    try:
        id_nuevo = db.execute(
            text("""
                INSERT INTO public."AnalisisTrabajoSeguro" (
                    "IdRegistroPersonalResponsable",
                    "IdCliente",
                    "LugarTrabajo",
                    "FechaFinalizacionActividad",
                    "AlturaAproximadaMetros"
                )
                VALUES (
                    :id_responsable,
                    :id_cliente,
                    :lugar_trabajo,
                    :fecha_finalizacion_actividad,
                    :altura_aproximada_metros
                )
                RETURNING "IdAnalisisTrabajoSeguro"
            """),
            {
                "id_responsable": payload.id_registro_personal_responsable,
                "id_cliente": payload.id_cliente,
                "lugar_trabajo": lugar_trabajo,
                "fecha_finalizacion_actividad": payload.fecha_finalizacion_actividad,
                "altura_aproximada_metros": payload.altura_aproximada_metros,
            },
        ).scalar()
        db.commit()
    except Exception:
        db.rollback()
        raise

    return _obtener_analisis(db, id_nuevo)


@router.get("/matriz-peligros", response_model=list[MatrizPeligroOut])
def listar_matriz_peligros(
    db: Session = Depends(get_db),
    _current=Depends(require_operaciones_alturas),
):
    """Filas activas de la matriz de peligros, por categoría de riesgo."""
    filas = db.execute(
        text("""
            SELECT M."IdMatrizPeligro"       AS id_matriz_peligro,
                   R."IdRiesgoMatrizPeligro" AS id_riesgo_matriz_peligro,
                   R."Nombre"                AS riesgo,
                   M."Peligro"               AS peligro,
                   M."PeligroAdicional"      AS peligro_adicional,
                   M."RiesgoAsociado"        AS riesgo_asociado,
                   M."ConsecuenciaAsociada"  AS consecuencia_asociada
            FROM public."MatrizPeligroAlturas" M
            JOIN public."RiesgoMatrizPeligro" R
              ON R."IdRiesgoMatrizPeligro" = M."IdRiesgoMatrizPeligro"
            WHERE M."Activo" AND R."Activo"
            ORDER BY R."Orden", M."Orden"
        """)
    ).mappings().all()

    return [dict(fila) for fila in filas]


@router.get("/{id_analisis}", response_model=AnalisisTrabajoSeguroOut)
def obtener_analisis(
    id_analisis: int,
    db: Session = Depends(get_db),
    _current=Depends(require_operaciones_alturas),
):
    return _obtener_analisis(db, id_analisis)


def _validar_lista_equipos(
    db: Session, ids: list[int], tipo: str, nombre: str
) -> list[str]:
    """Las opciones existen, están activas, son de la lista y no se repiten.
    Devuelve sus códigos."""
    if len(set(ids)) != len(ids):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Hay opciones repetidas en {nombre}.",
        )

    codigos = db.execute(
        text("""
            SELECT "Codigo"
            FROM public."OpcionPermisoAlturas"
            WHERE "IdOpcionPermisoAlturas" = ANY(:ids)
              AND "Tipo" = :tipo
              AND "Activo"
        """),
        {"ids": ids, "tipo": tipo},
    ).scalars().all()

    if len(codigos) != len(ids):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Hay opciones de {nombre} que no existen o están inactivas.",
        )

    return codigos


@router.put("/{id_analisis}/equipos", response_model=AnalisisTrabajoSeguroOut)
def guardar_equipos(
    id_analisis: int,
    payload: EquiposAnalisisIn,
    db: Session = Depends(get_db),
    _current=Depends(require_operaciones_alturas),
):
    """Bloque 3: sistemas de acceso, herramientas manuales y eléctricas,
    permisos que necesita el trabajo y descripción de la tarea."""
    _validar_editable(db, id_analisis)
    _obtener_analisis(db, id_analisis)

    descripcion = _texto_requerido(
        payload.descripcion_tarea, "Descripción de la tarea a realizar"
    )

    codigos = {
        campo: _validar_lista_equipos(db, getattr(payload, campo), tipo, nombre)
        for campo, (tipo, nombre) in LISTAS_EQUIPOS.items()
    }

    for campo, (_, nombre) in LISTAS_EQUIPOS.items():
        elegidos = codigos[campo]

        if len(elegidos) > 1 and any(
            codigo.endswith(SUFIJO_NO_APLICA) for codigo in elegidos
        ):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    "«No aplica» no se puede elegir junto con otras opciones "
                    f"de {nombre}."
                ),
            )

    otro_permiso = None

    if CODIGO_PERMISO_OTRO in codigos["permisos_requeridos"]:
        otro_permiso = _texto_requerido(
            payload.otro_permiso_requerido, "¿Cuál otro permiso se necesita?"
        )

    ids = [id_opcion for campo in LISTAS_EQUIPOS for id_opcion in getattr(payload, campo)]
    tipos = [tipo for tipo, _ in LISTAS_EQUIPOS.values()]

    try:
        db.execute(
            text("""
                UPDATE public."AnalisisTrabajoSeguro"
                SET "DescripcionTarea"     = :descripcion,
                    "OtroPermisoRequerido" = :otro_permiso
                WHERE "IdAnalisisTrabajoSeguro" = :id_analisis
            """),
            {
                "id_analisis": id_analisis,
                "descripcion": descripcion,
                "otro_permiso": otro_permiso,
            },
        )
        # Se reemplaza la selección anterior de las listas del bloque.
        db.execute(
            text("""
                DELETE FROM public."AnalisisTrabajoSeguroOpcion" AO
                USING public."OpcionPermisoAlturas" O
                WHERE O."IdOpcionPermisoAlturas" = AO."IdOpcionPermisoAlturas"
                  AND AO."IdAnalisisTrabajoSeguro" = :id_analisis
                  AND O."Tipo" = ANY(:tipos)
            """),
            {"id_analisis": id_analisis, "tipos": tipos},
        )
        db.execute(
            text("""
                INSERT INTO public."AnalisisTrabajoSeguroOpcion" (
                    "IdAnalisisTrabajoSeguro",
                    "IdOpcionPermisoAlturas"
                )
                SELECT :id_analisis, UNNEST(CAST(:ids AS integer[]))
            """),
            {"id_analisis": id_analisis, "ids": ids},
        )
        db.commit()
    except Exception:
        db.rollback()
        raise

    return _obtener_analisis(db, id_analisis)


# ─────────────────────────────────────────────
# Bloque 4: tareas del análisis
# ─────────────────────────────────────────────
SQL_TAREAS_ANALISIS = """
    SELECT "IdAnalisisTrabajoSeguroTarea" AS id_analisis_trabajo_seguro_tarea,
           "IdAnalisisTrabajoSeguro"      AS id_analisis_trabajo_seguro,
           "Orden"                        AS orden,
           "PasoDetallado"                AS paso_detallado,
           "FechaCreacion"                AS fecha_creacion
    FROM public."AnalisisTrabajoSeguroTarea"
"""


SQL_PELIGROS_TAREA = """
    SELECT "IdAnalisisTrabajoSeguroTareaPeligro" AS id_analisis_trabajo_seguro_tarea_peligro,
           "IdAnalisisTrabajoSeguroTarea"        AS id_analisis_trabajo_seguro_tarea,
           "IdMatrizPeligro"                     AS id_matriz_peligro,
           "Riesgo"                              AS riesgo,
           "Peligro"                             AS peligro,
           "PeligroAdicional"                    AS peligro_adicional,
           "RiesgoAsociado"                      AS riesgo_asociado,
           "ConsecuenciaAsociada"                AS consecuencia_asociada
    FROM public."AnalisisTrabajoSeguroTareaPeligro"
"""


def _peligros_por_tarea(db: Session, ids_tareas: list[int]) -> dict[int, list[dict]]:
    if not ids_tareas:
        return {}

    filas = db.execute(
        text(
            SQL_PELIGROS_TAREA
            + """
            WHERE "IdAnalisisTrabajoSeguroTarea" = ANY(:ids)
            ORDER BY "IdAnalisisTrabajoSeguroTareaPeligro"
            """
        ),
        {"ids": ids_tareas},
    ).mappings().all()

    resultado: dict[int, list[dict]] = {id_tarea: [] for id_tarea in ids_tareas}

    for fila in filas:
        resultado[fila["id_analisis_trabajo_seguro_tarea"]].append(dict(fila))

    return resultado


def _con_peligros(db: Session, tarea: dict) -> dict:
    id_tarea = tarea["id_analisis_trabajo_seguro_tarea"]
    return {**tarea, "peligros": _peligros_por_tarea(db, [id_tarea])[id_tarea]}


def _insertar_peligro_tarea(db: Session, id_tarea: int, id_matriz_peligro: int) -> int:
    """Agrega un peligro de la matriz a la tarea, copiando sus textos. Devuelve
    el id creado. No hace commit."""
    id_nuevo = db.execute(
        text("""
            INSERT INTO public."AnalisisTrabajoSeguroTareaPeligro" (
                "IdAnalisisTrabajoSeguroTarea",
                "IdMatrizPeligro",
                "Riesgo",
                "Peligro",
                "PeligroAdicional",
                "RiesgoAsociado",
                "ConsecuenciaAsociada"
            )
            SELECT :id_tarea,
                   M."IdMatrizPeligro",
                   R."Nombre",
                   M."Peligro",
                   M."PeligroAdicional",
                   M."RiesgoAsociado",
                   M."ConsecuenciaAsociada"
            FROM public."MatrizPeligroAlturas" M
            JOIN public."RiesgoMatrizPeligro" R
              ON R."IdRiesgoMatrizPeligro" = M."IdRiesgoMatrizPeligro"
            WHERE M."IdMatrizPeligro" = :id_matriz_peligro
              AND M."Activo" AND R."Activo"
            RETURNING "IdAnalisisTrabajoSeguroTareaPeligro"
        """),
        {"id_tarea": id_tarea, "id_matriz_peligro": id_matriz_peligro},
    ).scalar()

    if id_nuevo is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="El peligro elegido no existe o está inactivo en la matriz.",
        )

    return id_nuevo


def _validar_tarea(db: Session, id_analisis: int, id_tarea: int) -> None:
    existe = db.execute(
        text("""
            SELECT 1
            FROM public."AnalisisTrabajoSeguroTarea"
            WHERE "IdAnalisisTrabajoSeguroTarea" = :id_tarea
              AND "IdAnalisisTrabajoSeguro" = :id_analisis
        """),
        {"id_analisis": id_analisis, "id_tarea": id_tarea},
    ).scalar()

    if not existe:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="La tarea no existe en este análisis.",
        )


@router.get("/{id_analisis}/tareas", response_model=list[TareaAnalisisOut])
def listar_tareas_analisis(
    id_analisis: int,
    db: Session = Depends(get_db),
    _current=Depends(require_operaciones_alturas),
):
    _obtener_analisis(db, id_analisis)

    filas = db.execute(
        text(
            SQL_TAREAS_ANALISIS
            + """
            WHERE "IdAnalisisTrabajoSeguro" = :id_analisis
            ORDER BY "Orden"
            """
        ),
        {"id_analisis": id_analisis},
    ).mappings().all()

    peligros = _peligros_por_tarea(
        db, [fila["id_analisis_trabajo_seguro_tarea"] for fila in filas]
    )

    return [
        {**fila, "peligros": peligros[fila["id_analisis_trabajo_seguro_tarea"]]}
        for fila in filas
    ]


@router.post(
    "/{id_analisis}/tareas",
    response_model=TareaAnalisisOut,
    status_code=status.HTTP_201_CREATED,
)
def agregar_tarea_analisis(
    id_analisis: int,
    payload: TareaAnalisisIn,
    db: Session = Depends(get_db),
    _current=Depends(require_operaciones_alturas),
):
    _validar_editable(db, id_analisis)
    _obtener_analisis(db, id_analisis)
    paso_detallado = _texto_requerido(
        payload.paso_detallado, "Paso detallado de la tarea"
    )

    try:
        # La tarea nueva queda de última (Tarea N + 1).
        fila = db.execute(
            text("""
                INSERT INTO public."AnalisisTrabajoSeguroTarea" (
                    "IdAnalisisTrabajoSeguro",
                    "Orden",
                    "PasoDetallado"
                )
                SELECT :id_analisis,
                       COALESCE(MAX("Orden"), 0) + 1,
                       :paso_detallado
                FROM public."AnalisisTrabajoSeguroTarea"
                WHERE "IdAnalisisTrabajoSeguro" = :id_analisis
                RETURNING "IdAnalisisTrabajoSeguroTarea" AS id_analisis_trabajo_seguro_tarea,
                          "IdAnalisisTrabajoSeguro"      AS id_analisis_trabajo_seguro,
                          "Orden"                        AS orden,
                          "PasoDetallado"                AS paso_detallado,
                          "FechaCreacion"                AS fecha_creacion
            """),
            {"id_analisis": id_analisis, "paso_detallado": paso_detallado},
        ).mappings().one()
        _insertar_peligro_tarea(
            db, fila["id_analisis_trabajo_seguro_tarea"], payload.id_matriz_peligro
        )
        db.commit()
    except HTTPException:
        db.rollback()
        raise
    except IntegrityError:
        # Dos tareas agregadas al mismo tiempo tomaron el mismo número.
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Otra tarea se agregó al mismo tiempo. Intenta de nuevo.",
        )
    except Exception:
        db.rollback()
        raise

    return _con_peligros(db, dict(fila))


@router.put(
    "/{id_analisis}/tareas/{id_tarea}",
    response_model=TareaAnalisisOut,
)
def editar_tarea_analisis(
    id_analisis: int,
    id_tarea: int,
    payload: TareaEdicionIn,
    db: Session = Depends(get_db),
    _current=Depends(require_operaciones_alturas),
):
    _validar_editable(db, id_analisis)
    paso_detallado = _texto_requerido(
        payload.paso_detallado, "Paso detallado de la tarea"
    )

    try:
        fila = db.execute(
            text("""
                UPDATE public."AnalisisTrabajoSeguroTarea"
                SET "PasoDetallado" = :paso_detallado
                WHERE "IdAnalisisTrabajoSeguroTarea" = :id_tarea
                  AND "IdAnalisisTrabajoSeguro" = :id_analisis
                RETURNING "IdAnalisisTrabajoSeguroTarea" AS id_analisis_trabajo_seguro_tarea,
                          "IdAnalisisTrabajoSeguro"      AS id_analisis_trabajo_seguro,
                          "Orden"                        AS orden,
                          "PasoDetallado"                AS paso_detallado,
                          "FechaCreacion"                AS fecha_creacion
            """),
            {
                "id_analisis": id_analisis,
                "id_tarea": id_tarea,
                "paso_detallado": paso_detallado,
            },
        ).mappings().first()
        db.commit()
    except Exception:
        db.rollback()
        raise

    if fila is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="La tarea no existe en este análisis.",
        )

    return _con_peligros(db, dict(fila))


@router.delete(
    "/{id_analisis}/tareas/{id_tarea}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def quitar_tarea_analisis(
    id_analisis: int,
    id_tarea: int,
    db: Session = Depends(get_db),
    _current=Depends(require_operaciones_alturas),
):
    _validar_editable(db, id_analisis)
    try:
        eliminados = db.execute(
            text("""
                DELETE FROM public."AnalisisTrabajoSeguroTarea"
                WHERE "IdAnalisisTrabajoSeguroTarea" = :id_tarea
                  AND "IdAnalisisTrabajoSeguro" = :id_analisis
            """),
            {"id_analisis": id_analisis, "id_tarea": id_tarea},
        ).rowcount
        db.commit()
    except Exception:
        db.rollback()
        raise

    if not eliminados:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="La tarea no existe en este análisis.",
        )


@router.post(
    "/{id_analisis}/tareas/{id_tarea}/peligros",
    response_model=PeligroTareaOut,
    status_code=status.HTTP_201_CREATED,
)
def agregar_peligro_tarea(
    id_analisis: int,
    id_tarea: int,
    payload: PeligroTareaIn,
    db: Session = Depends(get_db),
    _current=Depends(require_operaciones_alturas),
):
    _validar_editable(db, id_analisis)
    _validar_tarea(db, id_analisis, id_tarea)

    try:
        id_nuevo = _insertar_peligro_tarea(db, id_tarea, payload.id_matriz_peligro)
        db.commit()
    except HTTPException:
        db.rollback()
        raise
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Ese peligro ya está registrado en la tarea.",
        )
    except Exception:
        db.rollback()
        raise

    fila = db.execute(
        text(
            SQL_PELIGROS_TAREA
            + ' WHERE "IdAnalisisTrabajoSeguroTareaPeligro" = :id_nuevo'
        ),
        {"id_nuevo": id_nuevo},
    ).mappings().one()

    return dict(fila)


@router.delete(
    "/{id_analisis}/tareas/{id_tarea}/peligros/{id_peligro_tarea}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def quitar_peligro_tarea(
    id_analisis: int,
    id_tarea: int,
    id_peligro_tarea: int,
    db: Session = Depends(get_db),
    _current=Depends(require_operaciones_alturas),
):
    _validar_editable(db, id_analisis)
    _validar_tarea(db, id_analisis, id_tarea)

    cantidad = db.execute(
        text("""
            SELECT COUNT(*)
            FROM public."AnalisisTrabajoSeguroTareaPeligro"
            WHERE "IdAnalisisTrabajoSeguroTarea" = :id_tarea
        """),
        {"id_tarea": id_tarea},
    ).scalar()

    try:
        eliminados = db.execute(
            text("""
                DELETE FROM public."AnalisisTrabajoSeguroTareaPeligro"
                WHERE "IdAnalisisTrabajoSeguroTareaPeligro" = :id_peligro_tarea
                  AND "IdAnalisisTrabajoSeguroTarea" = :id_tarea
                  AND :cantidad > 1
            """),
            {
                "id_tarea": id_tarea,
                "id_peligro_tarea": id_peligro_tarea,
                "cantidad": cantidad,
            },
        ).rowcount
        db.commit()
    except Exception:
        db.rollback()
        raise

    if eliminados:
        return

    existe = db.execute(
        text("""
            SELECT 1
            FROM public."AnalisisTrabajoSeguroTareaPeligro"
            WHERE "IdAnalisisTrabajoSeguroTareaPeligro" = :id_peligro_tarea
              AND "IdAnalisisTrabajoSeguroTarea" = :id_tarea
        """),
        {"id_tarea": id_tarea, "id_peligro_tarea": id_peligro_tarea},
    ).scalar()

    if existe:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="La tarea debe tener al menos un peligro.",
        )

    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail="El peligro no está registrado en esta tarea.",
    )


# ─────────────────────────────────────────────
# Bloque 5: verificación diaria
# ─────────────────────────────────────────────
def _preguntas_diarias(db: Session) -> list[dict]:
    filas = db.execute(
        text("""
            SELECT "IdItemPermisoAlturas" AS id_item_permiso_alturas,
                   "Codigo"               AS codigo,
                   "Texto"                AS texto,
                   "RespuestaAlerta"      AS respuesta_alerta
            FROM public."ItemPermisoAlturas"
            WHERE "TipoItem" = :tipo
              AND "Activo"
            ORDER BY "Orden"
        """),
        {"tipo": TIPO_ITEM_VERIFICACION_DIARIA},
    ).mappings().all()

    return [dict(fila) for fila in filas]


def _verificacion_diaria(db: Session, id_analisis: int) -> dict:
    rango = db.execute(
        text("""
            SELECT ("FechaCreacion" AT TIME ZONE :zona)::date AS inicio,
                   "FechaFinalizacionActividad"                AS fin,
                   (now() AT TIME ZONE :zona)::date            AS hoy
            FROM public."AnalisisTrabajoSeguro"
            WHERE "IdAnalisisTrabajoSeguro" = :id_analisis
        """),
        {"id_analisis": id_analisis, "zona": ZONA_HORARIA},
    ).mappings().first()

    if rango is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="El análisis de trabajo seguro no existe.",
        )

    registros = db.execute(
        text("""
            SELECT D."IdAnalisisTrabajoSeguroDia" AS id_analisis_trabajo_seguro_dia,
                   D."Fecha"                      AS fecha,
                   D."IdRegistroPersonal"         AS id_registro_personal,
                   TRIM(R."Nombres" || ' ' || R."Apellidos") AS diligenciado_por,
                   R."NumeroIdentificacion"       AS numero_identificacion,
                   D."Observaciones"              AS observaciones,
                   D."DiligenciadoTarde"          AS diligenciado_tarde,
                   D."FechaRegistro"              AS fecha_registro
            FROM public."AnalisisTrabajoSeguroDia" D
            JOIN public."RegistroPersonal" R
              ON R."IdRegistroPersonal" = D."IdRegistroPersonal"
            WHERE D."IdAnalisisTrabajoSeguro" = :id_analisis
        """),
        {"id_analisis": id_analisis},
    ).mappings().all()

    respuestas = db.execute(
        text("""
            SELECT DR."IdAnalisisTrabajoSeguroDia" AS id_dia,
                   DR."IdItemPermisoAlturas"       AS id_item,
                   DR."Respuesta"                  AS respuesta
            FROM public."AnalisisTrabajoSeguroDiaRespuesta" DR
            JOIN public."AnalisisTrabajoSeguroDia" D
              ON D."IdAnalisisTrabajoSeguroDia" = DR."IdAnalisisTrabajoSeguroDia"
            WHERE D."IdAnalisisTrabajoSeguro" = :id_analisis
        """),
        {"id_analisis": id_analisis},
    ).mappings().all()

    por_fecha = {}

    for registro in registros:
        por_fecha[registro["fecha"]] = {
            **{k: v for k, v in registro.items() if k != "fecha"},
            "respuestas": {
                fila["id_item"]: fila["respuesta"]
                for fila in respuestas
                if fila["id_dia"] == registro["id_analisis_trabajo_seguro_dia"]
            },
        }

    dias = []
    dia = rango["inicio"]

    while dia <= rango["fin"]:
        if dia in por_fecha:
            estado = DIA_DILIGENCIADO
        elif dia <= rango["hoy"]:
            estado = DIA_PENDIENTE
        else:
            estado = DIA_FUTURO

        dias.append({"fecha": dia, "estado": estado, "registro": por_fecha.get(dia)})
        dia += timedelta(days=1)

    return {"hoy": rango["hoy"], "preguntas": _preguntas_diarias(db), "dias": dias}


@router.get(
    "/{id_analisis}/verificacion-diaria",
    response_model=VerificacionDiariaOut,
)
def obtener_verificacion_diaria(
    id_analisis: int,
    db: Session = Depends(get_db),
    _current=Depends(require_operaciones_alturas),
):
    return _verificacion_diaria(db, id_analisis)


@router.post(
    "/{id_analisis}/verificacion-diaria",
    response_model=VerificacionDiariaOut,
    status_code=status.HTTP_201_CREATED,
)
def diligenciar_dia(
    id_analisis: int,
    payload: DiaVerificacionIn,
    db: Session = Depends(get_db),
    _current=Depends(require_operaciones_alturas),
):
    """Registra la verificación de un día. Un día guardado no se modifica; si
    se diligencia después de su fecha queda marcado como tardío."""
    verificacion = _verificacion_diaria(db, id_analisis)
    dia = next(
        (d for d in verificacion["dias"] if d["fecha"] == payload.fecha), None
    )

    if dia is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="La fecha no está dentro de los días del análisis.",
        )

    if dia["estado"] == DIA_FUTURO:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No se puede diligenciar un día que aún no llega.",
        )

    if dia["estado"] == DIA_DILIGENCIADO:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Ese día ya fue diligenciado y no se puede modificar.",
        )

    ids_preguntas = {p["id_item_permiso_alturas"] for p in verificacion["preguntas"]}
    ids_respondidos = [r.id_item_permiso_alturas for r in payload.respuestas]

    if len(set(ids_respondidos)) != len(ids_respondidos) or set(
        ids_respondidos
    ) != ids_preguntas:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Responde todas las preguntas de la verificación diaria.",
        )

    _persona_contratada(db, payload.id_registro_personal, "Quien diligencia")
    observaciones = (payload.observaciones or "").strip() or None

    try:
        id_dia = db.execute(
            text("""
                INSERT INTO public."AnalisisTrabajoSeguroDia" (
                    "IdAnalisisTrabajoSeguro",
                    "Fecha",
                    "IdRegistroPersonal",
                    "Observaciones",
                    "DiligenciadoTarde"
                )
                VALUES (
                    :id_analisis,
                    :fecha,
                    :id_registro_personal,
                    :observaciones,
                    :tarde
                )
                RETURNING "IdAnalisisTrabajoSeguroDia"
            """),
            {
                "id_analisis": id_analisis,
                "fecha": payload.fecha,
                "id_registro_personal": payload.id_registro_personal,
                "observaciones": observaciones,
                "tarde": payload.fecha < verificacion["hoy"],
            },
        ).scalar()

        for respuesta in payload.respuestas:
            db.execute(
                text("""
                    INSERT INTO public."AnalisisTrabajoSeguroDiaRespuesta" (
                        "IdAnalisisTrabajoSeguroDia",
                        "IdItemPermisoAlturas",
                        "Respuesta"
                    )
                    VALUES (:id_dia, :id_item, :respuesta)
                """),
                {
                    "id_dia": id_dia,
                    "id_item": respuesta.id_item_permiso_alturas,
                    "respuesta": respuesta.respuesta,
                },
            )

        db.commit()
    except IntegrityError:
        # Otro usuario diligenció el mismo día al mismo tiempo.
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Ese día ya fue diligenciado y no se puede modificar.",
        )
    except Exception:
        db.rollback()
        raise

    return _verificacion_diaria(db, id_analisis)


# ─────────────────────────────────────────────
# Bloque 6: visto bueno del coordinador de alturas y PDF
# ─────────────────────────────────────────────
def _bloques_pendientes(analisis: dict) -> list[str]:
    """Bloques 2 a 4 sin completar (deben estar completos para el visto bueno)."""
    pendientes = []

    if not analisis["cantidad_trabajadores"]:
        pendientes.append("2. Trabajadores")

    if not (
        all(analisis[campo] for campo in LISTAS_EQUIPOS)
        and analisis["descripcion_tarea"]
    ):
        pendientes.append("3. Equipos")

    if not analisis["cantidad_tareas"] or analisis["tareas_sin_peligro"]:
        pendientes.append("4. Tareas y peligros")

    return pendientes


@router.post("/{id_analisis}/visto-bueno", response_model=AnalisisTrabajoSeguroOut)
def dar_visto_bueno(
    id_analisis: int,
    payload: VistoBuenoIn,
    db: Session = Depends(get_db),
    _current=Depends(require_operaciones_alturas),
):
    """Firma del coordinador de alturas. El análisis queda APROBADO: los
    bloques 1 a 4 ya no se modifican y el PDF deja de ser borrador."""
    _validar_editable(db, id_analisis)

    analisis = _obtener_analisis(db, id_analisis)
    pendientes = _bloques_pendientes(analisis)

    if pendientes:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "Completa estos bloques antes del visto bueno: "
                + ", ".join(pendientes)
                + "."
            ),
        )

    firma = _decodificar_firma(payload.firma_png)
    # Coordinador = responsable del análisis.
    id_coordinador = analisis["id_registro_personal_responsable"]
    _persona_contratada(db, id_coordinador, "Coordinador de alturas")

    try:
        actualizados = db.execute(
            text("""
                UPDATE public."AnalisisTrabajoSeguro"
                SET "Estado"                        = :aprobado,
                    "IdRegistroPersonalCoordinador" = :id_coordinador,
                    "FirmaCoordinador"              = :firma,
                    "FechaVistoBueno"               = now()
                WHERE "IdAnalisisTrabajoSeguro" = :id_analisis
                  AND "Estado" = :en_diligenciamiento
            """),
            {
                "id_analisis": id_analisis,
                "id_coordinador": id_coordinador,
                "firma": firma,
                "aprobado": ESTADO_APROBADO,
                "en_diligenciamiento": ESTADO_EN_DILIGENCIAMIENTO,
            },
        ).rowcount
        db.commit()
    except Exception:
        db.rollback()
        raise

    if not actualizados:
        # Otro usuario dio el visto bueno al mismo tiempo.
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="El análisis ya tiene visto bueno y no se puede modificar.",
        )

    return _obtener_analisis(db, id_analisis)


@router.get(
    "/{id_analisis}/firma-coordinador",
    response_class=Response,
    responses={200: {"content": {"image/png": {}}}},
)
def obtener_firma_coordinador(
    id_analisis: int,
    db: Session = Depends(get_db),
    _current=Depends(require_operaciones_alturas),
):
    firma = db.execute(
        text("""
            SELECT "FirmaCoordinador"
            FROM public."AnalisisTrabajoSeguro"
            WHERE "IdAnalisisTrabajoSeguro" = :id_analisis
        """),
        {"id_analisis": id_analisis},
    ).scalar()

    if not firma:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="El análisis no tiene firma del coordinador.",
        )

    return Response(content=bytes(firma), media_type="image/png")


@router.get(
    "/{id_analisis}/pdf",
    response_class=Response,
    responses={200: {"content": {"application/pdf": {}}}},
)
def descargar_pdf_analisis(
    id_analisis: int,
    db: Session = Depends(get_db),
    _current=Depends(require_operaciones_alturas),
):
    """PDF del análisis (formato F-SS-006). Sin visto bueno, sale con la marca
    de agua "BORRADOR"."""
    pdf = generar_pdf_analisis_trabajo_seguro(db, id_analisis)

    if pdf is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="El análisis de trabajo seguro no existe.",
        )

    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={
            "Content-Disposition": (
                f'inline; filename="analisis_trabajo_seguro_{id_analisis}.pdf"'
            ),
        },
    )


# ─────────────────────────────────────────────
# Trabajadores del análisis
# ─────────────────────────────────────────────
@router.get(
    "/{id_analisis}/trabajadores",
    response_model=list[AnalisisTrabajadorOut],
)
def listar_trabajadores_analisis(
    id_analisis: int,
    db: Session = Depends(get_db),
    _current=Depends(require_operaciones_alturas),
):
    _obtener_analisis(db, id_analisis)

    filas = db.execute(
        text(
            SQL_TRABAJADORES_ANALISIS
            + """
            WHERE T."IdAnalisisTrabajoSeguro" = :id_analisis
            ORDER BY T."IdAnalisisTrabajoSeguroTrabajador"
            """
        ),
        {"id_analisis": id_analisis},
    ).mappings().all()

    return [dict(fila) for fila in filas]


@router.post(
    "/{id_analisis}/trabajadores",
    response_model=AnalisisTrabajadorOut,
    status_code=status.HTTP_201_CREATED,
)
def agregar_trabajador_analisis(
    id_analisis: int,
    payload: AnalisisTrabajadorIn,
    db: Session = Depends(get_db),
    _current=Depends(require_operaciones_alturas),
):
    _validar_editable(db, id_analisis)
    _obtener_analisis(db, id_analisis)
    firma_imagen = _decodificar_firma(payload.firma_png)
    _persona_contratada(db, payload.id_registro_personal, "Trabajador")

    try:
        id_nuevo = db.execute(
            text("""
                INSERT INTO public."AnalisisTrabajoSeguroTrabajador" (
                    "IdAnalisisTrabajoSeguro",
                    "IdRegistroPersonal",
                    "FirmaImagen"
                )
                VALUES (:id_analisis, :id_registro_personal, :firma_imagen)
                RETURNING "IdAnalisisTrabajoSeguroTrabajador"
            """),
            {
                "id_analisis": id_analisis,
                "id_registro_personal": payload.id_registro_personal,
                "firma_imagen": firma_imagen,
            },
        ).scalar()
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="El trabajador ya está registrado en este análisis.",
        )
    except Exception:
        db.rollback()
        raise

    fila = db.execute(
        text(
            SQL_TRABAJADORES_ANALISIS
            + ' WHERE T."IdAnalisisTrabajoSeguroTrabajador" = :id_nuevo'
        ),
        {"id_nuevo": id_nuevo},
    ).mappings().one()

    return dict(fila)


@router.get(
    "/{id_analisis}/trabajadores/{id_analisis_trabajador}/firma",
    response_class=Response,
    responses={200: {"content": {"image/png": {}}}},
)
def obtener_firma_trabajador_analisis(
    id_analisis: int,
    id_analisis_trabajador: int,
    db: Session = Depends(get_db),
    _current=Depends(require_operaciones_alturas),
):
    firma = db.execute(
        text("""
            SELECT "FirmaImagen"
            FROM public."AnalisisTrabajoSeguroTrabajador"
            WHERE "IdAnalisisTrabajoSeguroTrabajador" = :id_trabajador
              AND "IdAnalisisTrabajoSeguro" = :id_analisis
        """),
        {"id_analisis": id_analisis, "id_trabajador": id_analisis_trabajador},
    ).scalar()

    if not firma:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="El trabajador no tiene firma registrada en este análisis.",
        )

    return Response(content=bytes(firma), media_type="image/png")


@router.delete(
    "/{id_analisis}/trabajadores/{id_analisis_trabajador}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def quitar_trabajador_analisis(
    id_analisis: int,
    id_analisis_trabajador: int,
    db: Session = Depends(get_db),
    _current=Depends(require_operaciones_alturas),
):
    _validar_editable(db, id_analisis)
    try:
        eliminados = db.execute(
            text("""
                DELETE FROM public."AnalisisTrabajoSeguroTrabajador"
                WHERE "IdAnalisisTrabajoSeguroTrabajador" = :id_trabajador
                  AND "IdAnalisisTrabajoSeguro" = :id_analisis
            """),
            {"id_analisis": id_analisis, "id_trabajador": id_analisis_trabajador},
        ).rowcount
        db.commit()
    except Exception:
        db.rollback()
        raise

    if not eliminados:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="El trabajador no está registrado en este análisis.",
        )
