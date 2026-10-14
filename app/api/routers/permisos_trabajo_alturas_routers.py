# ruff: noqa: B008

import base64
import binascii
from datetime import date, datetime, time
from decimal import Decimal
from typing import Literal

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    HTTPException,
    Query,
    Response,
    status,
)
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from infrastructure.db.deps import get_db
from infrastructure.security.auth_dependencies import get_current_user
from services.permiso_alturas_correo_service import (
    enviar_permiso_autorizado,
    obtener_correos_notificacion,
)
from services.permiso_alturas_pdf_service import generar_pdf_permiso_alturas


router = APIRouter(
    prefix="/api/operaciones/alturas",
    tags=["Operaciones - Alturas"],
)


ROL_ADMIN = 1
ROL_SUPER_ADMIN = 5
ROL_OPERACIONES = 6
ROL_DESARROLLADOR = 15

ROLES_PERMITIDOS = {
    ROL_ADMIN,
    ROL_SUPER_ADMIN,
    ROL_OPERACIONES,
    ROL_DESARROLLADOR,
}

# Colombia no tiene horario de verano. La fecha del permiso se calcula en
# PostgreSQL con esta zona para que "hoy" no dependa del equipo del usuario.
ZONA_HORARIA = "America/Bogota"

# Solo el personal vinculado puede incluirse en un permiso (mismo criterio
# que Operaciones - Retiros).
ID_ESTADO_CONTRATADO = 25

# Estados del permiso. Solo se puede editar mientras está en diligenciamiento;
# una vez autorizado ya no lo modifica quien lo diligenció.
ESTADO_EN_DILIGENCIAMIENTO = "EN_DILIGENCIAMIENTO"
ESTADO_AUTORIZADO = "AUTORIZADO"

# Firmas del paso 7 ("PermisoTrabajoAlturasFirma"."Rol").
ROLES_FIRMA = ("AUTORIZA", "COORDINADOR", "EMERGENCIAS", "AYUDANTE")

# Listas de preguntas del permiso (tabla "ItemPermisoAlturas").
TIPO_ITEM_PROTECCION = "PROTECCION"
TIPO_ITEM_VERIFICACION = "VERIFICACION"
TIPO_ITEM_PELIGRO = "PELIGRO"


def _sql_lista_completa(tipo: str) -> str:
    """
    Subconsulta: TRUE si el permiso P respondió todas las preguntas activas
    de la lista `tipo`. `tipo` es siempre una constante de este módulo.
    """
    return f"""(
               SELECT COUNT(*) > 0 AND COUNT(*) = COUNT(R."IdItemPermisoAlturas")
               FROM public."ItemPermisoAlturas" I
               LEFT JOIN public."PermisoTrabajoAlturasRespuesta" R
                 ON R."IdItemPermisoAlturas" = I."IdItemPermisoAlturas"
                AND R."IdPermisoTrabajoAlturas" = P."IdPermisoTrabajoAlturas"
               WHERE I."TipoItem" = '{tipo}'
                 AND I."Activo"
           )"""

# Firma del trabajador: imagen PNG dibujada en pantalla, enviada como data URL.
PREFIJO_FIRMA_PNG = "data:image/png;base64,"
FIRMA_PNG_ENCABEZADO = b"\x89PNG\r\n\x1a\n"
FIRMA_TAMANO_MAXIMO = 500 * 1024  # 500 KB; una firma suele pesar 10-30 KB.

# Condiciones o situaciones que impiden trabajar en alturas de manera segura.
# Se preguntan solo si el trabajador declara que presenta alguna; si no,
# quedan en NO. "consume_sustancias" usa la columna existente.
IMPEDIMENTOS_ALTURAS = {
    "ingirio_alcohol_12_horas": "IngirioAlcohol12Horas",
    "miedo_alturas_vertigo": "MiedoAlturasVertigo",
    "consume_sustancias": "ConsumeSustancias",
}

# Condiciones de salud específicas que se preguntan solo cuando el trabajador
# declara que presenta alguna condición de salud. Campo de la API -> columna.
CONDICIONES_SALUD = {
    "problemas_corazon": "ProblemasCorazon",
    "problemas_respiratorios": "ProblemasRespiratorios",
    "diabetes": "Diabetes",
    "epilepsia": "Epilepsia",
    "problemas_sistema_nervioso": "ProblemasSistemaNervioso",
    "problemas_audicion": "ProblemasAudicion",
    "problemas_visuales": "ProblemasVisuales",
}


class ClienteOut(BaseModel):
    id_cliente: int
    nombre: str


class CiudadOut(BaseModel):
    id_ciudad: int
    nombre: str


class PermisoTrabajoAlturasIn(BaseModel):
    # Temporal: mientras no existan los roles, el responsable puede ser
    # cualquier persona contratada. Luego se tomará del usuario autenticado
    # y dejará de venir en el cuerpo de la petición.
    id_registro_personal_responsable: int = Field(..., gt=0)
    id_cliente: int = Field(..., gt=0)
    id_ciudad: int = Field(..., gt=0)
    lugar_trabajo: str = Field(..., max_length=300)
    hora_inicio_tarea: time
    hora_fin_tarea: time


class PermisoTrabajoAlturasOut(BaseModel):
    id_permiso_trabajo_alturas: int
    id_registro_personal_responsable: int | None = None
    responsable: str | None = None
    numero_identificacion_responsable: str | None = None
    id_cliente: int
    cliente: str
    id_ciudad: int | None = None
    ciudad: str | None = None
    lugar_trabajo: str | None = None
    sede: str | None = None
    fecha_hora_inicio_tarea: datetime | None = None
    fecha_hora_fin_tarea: datetime | None = None
    fecha_creacion: datetime
    cantidad_trabajadores: int = 0
    estado: str = ESTADO_EN_DILIGENCIAMIENTO


class PermisoDetalleOut(PermisoTrabajoAlturasOut):
    # 2. Datos básicos y 3. Medidas de prevención (paso 3 del formulario).
    tipo_trabajo_alturas: str | None = None
    descripcion_procedimiento: str | None = None
    herramientas_utensilios: str | None = None
    altura_aproximada_metros: Decimal | None = None
    re_entrenamiento: bool | None = None
    sistemas_acceso: str | None = None
    sistemas_ingenieria: str | None = None
    medidas_colectivas: str | None = None
    trabajo_suspension: bool | None = None
    # 4. Elementos de protección.
    otro_elemento_proteccion: str | None = None
    proteccion_completa: bool = False
    # 5. Lista de verificación.
    verificacion_completa: bool = False
    # 6. Identificación de peligros.
    peligros_completa: bool = False
    # 7. Autorización.
    aplica_ayudante_seguridad: bool | None = None
    observaciones: str | None = None
    fecha_autorizacion: datetime | None = None
    firmas: list["FirmaPermisoOut"] = []
    # Destinatarios definidos en el servidor (no se editan en pantalla).
    correos_notificacion: list[str] = []
    correo_enviado_a: str | None = None
    fecha_envio_correo: datetime | None = None
    error_envio_correo: str | None = None


class FirmaPermisoOut(BaseModel):
    rol: str
    id_registro_personal: int
    nombre_completo: str
    numero_identificacion: str
    fecha_firma: datetime


# PermisoDetalleOut usa FirmaPermisoOut, definida después.
PermisoDetalleOut.model_rebuild()


class AutorizacionPermisoIn(BaseModel):
    id_registro_personal_autoriza: int = Field(..., gt=0)
    firma_autoriza: str
    # El coordinador es el responsable del permiso: solo se envía su firma.
    firma_coordinador: str
    id_registro_personal_emergencias: int = Field(..., gt=0)
    firma_emergencias: str
    aplica_ayudante_seguridad: bool
    id_registro_personal_ayudante: int | None = Field(None, gt=0)
    firma_ayudante: str | None = None
    observaciones: str | None = Field(None, max_length=4000)


class ItemRespuestaOut(BaseModel):
    id_item_permiso_alturas: int
    codigo: str
    texto: str
    orden: int
    respuesta: str | None = None


class ItemRespuestaIn(BaseModel):
    id_item_permiso_alturas: int = Field(..., gt=0)
    respuesta: Literal["SI", "NO", "NA"]


class ProteccionOut(BaseModel):
    items: list[ItemRespuestaOut]
    otro_elemento_proteccion: str | None = None


class ListaItemsOut(BaseModel):
    items: list[ItemRespuestaOut]


class ListaItemsIn(BaseModel):
    respuestas: list[ItemRespuestaIn]


class ProteccionIn(BaseModel):
    respuestas: list[ItemRespuestaIn]
    # "Otro ¿cuál?": único campo abierto del paso (opcional).
    otro_elemento_proteccion: str | None = Field(None, max_length=300)


class TareaPermisoIn(BaseModel):
    tipo_trabajo_alturas: str = Field(..., max_length=150)
    descripcion_procedimiento: str = Field(..., max_length=4000)
    herramientas_utensilios: str = Field(..., max_length=4000)
    altura_aproximada_metros: Decimal = Field(
        ..., gt=0, le=Decimal("9999.99"), decimal_places=2
    )
    re_entrenamiento: bool
    sistemas_acceso: str = Field(..., max_length=300)
    # ¿Cuál? / ¿Cuáles? — opcionales: no todas las tareas los tienen.
    sistemas_ingenieria: str | None = Field(None, max_length=300)
    medidas_colectivas: str | None = Field(None, max_length=300)
    trabajo_suspension: bool


class TrabajadorBusquedaOut(BaseModel):
    id_registro_personal: int
    numero_identificacion: str
    nombre_completo: str


class PermisoTrabajadorIn(BaseModel):
    id_registro_personal: int = Field(..., gt=0)
    fecha_examen_medico: date
    fecha_certificado_alturas: date
    seguridad_social_verificada: bool
    # ¿Presenta actualmente alguna condición o situación que le impida
    # realizar trabajo en alturas de manera segura? Si es True se responden
    # las tres subpreguntas; si es False quedan en NO.
    presenta_impedimento_alturas: bool
    ingirio_alcohol_12_horas: bool | None = None
    miedo_alturas_vertigo: bool | None = None
    # ¿Ha consumido recientemente sustancias psicoactivas, alcohol u otras
    # sustancias que puedan afectar su estado de alerta...?
    consume_sustancias: bool | None = None
    # Obligatorio si presenta impedimento pero responde NO a las tres.
    otro_impedimento_alturas: str | None = Field(None, max_length=300)
    # ¿Consume actualmente algún medicamento que deba ser informado para
    # realizar el trabajo en alturas? Si es True se responden las dos
    # subpreguntas; si es False ambas se guardan en NO.
    consume_medicamentos: bool
    medicamentos_presion_arterial: bool | None = None
    medicamentos_somnolencia: bool | None = None
    # Obligatorio si toma medicamentos que causan somnolencia.
    cual_medicamento_somnolencia: str | None = Field(None, max_length=300)
    # Obligatorio si consume medicamentos pero ninguno de los dos tipos.
    otro_medicamento: str | None = Field(None, max_length=300)
    presenta_condicion_salud: bool
    # Obligatorias solo si presenta_condicion_salud es True; si es False se
    # guardan en NO.
    problemas_corazon: bool | None = None
    problemas_respiratorios: bool | None = None
    diabetes: bool | None = None
    epilepsia: bool | None = None
    problemas_sistema_nervioso: bool | None = None
    problemas_audicion: bool | None = None
    problemas_visuales: bool | None = None
    # Obligatoria si presenta condición de salud pero ninguna de la lista aplica.
    otra_condicion_salud: str | None = Field(None, max_length=300)
    # Firma del trabajador como data URL PNG ("data:image/png;base64,...").
    # El tamaño se valida en _decodificar_firma para responder un mensaje
    # corto (la validación de Pydantic devolvería el contenido completo).
    firma_png: str


class PermisoTrabajadorOut(BaseModel):
    id_permiso_trabajo_alturas_trabajador: int
    id_permiso_trabajo_alturas: int
    id_registro_personal: int
    numero_identificacion: str
    nombre_completo: str
    fecha_examen_medico: date
    fecha_certificado_alturas: date
    seguridad_social_verificada: bool
    consume_sustancias: bool
    presenta_impedimento_alturas: bool | None = None
    ingirio_alcohol_12_horas: bool | None = None
    miedo_alturas_vertigo: bool | None = None
    otro_impedimento_alturas: str | None = None
    consume_medicamentos: bool
    # Solo en registros anteriores a la pregunta nueva de medicamentos.
    cuales_medicamentos: str | None = None
    medicamentos_presion_arterial: bool | None = None
    medicamentos_somnolencia: bool | None = None
    cual_medicamento_somnolencia: str | None = None
    otro_medicamento: str | None = None
    presenta_condicion_salud: bool | None = None
    problemas_corazon: bool | None = None
    problemas_respiratorios: bool | None = None
    diabetes: bool | None = None
    epilepsia: bool | None = None
    problemas_sistema_nervioso: bool | None = None
    problemas_audicion: bool | None = None
    problemas_visuales: bool | None = None
    otra_condicion_salud: str | None = None
    fecha_firma: datetime | None = None
    fecha_creacion: datetime


def require_operaciones_alturas(
    current=Depends(get_current_user),
):
    roles_ids = {
        int(id_rol)
        for id_rol in (current.get("roles_ids") or [])
        if str(id_rol).strip()
    }

    if roles_ids & ROLES_PERMITIDOS:
        return current

    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="No tienes permiso para gestionar permisos de trabajo en alturas.",
    )


@router.get("/clientes", response_model=list[ClienteOut])
def listar_clientes_activos(
    db: Session = Depends(get_db),
    _current=Depends(require_operaciones_alturas),
):
    filas = db.execute(
        text("""
            SELECT "IdCliente" AS id_cliente,
                   "Nombre"    AS nombre
            FROM public."Cliente"
            WHERE COALESCE("Activo", TRUE)
            ORDER BY "Nombre"
        """)
    ).mappings().all()

    return [dict(fila) for fila in filas]


@router.get("/ciudades", response_model=list[CiudadOut])
def listar_ciudades(
    db: Session = Depends(get_db),
    _current=Depends(require_operaciones_alturas),
):
    filas = db.execute(
        text("""
            SELECT "IdCiudad" AS id_ciudad,
                   "Nombre"   AS nombre
            FROM public."Ciudad"
            WHERE COALESCE("Estado", TRUE)
              AND "Nombre" IS NOT NULL
            ORDER BY "Nombre"
        """)
    ).mappings().all()

    return [dict(fila) for fila in filas]


SQL_PERMISOS = """
    SELECT P."IdPermisoTrabajoAlturas" AS id_permiso_trabajo_alturas,
           P."IdRegistroPersonalResponsable" AS id_registro_personal_responsable,
           TRIM(RR."Nombres" || ' ' || RR."Apellidos") AS responsable,
           RR."NumeroIdentificacion"   AS numero_identificacion_responsable,
           P."IdCliente"               AS id_cliente,
           C."Nombre"                  AS cliente,
           P."IdCiudad"                AS id_ciudad,
           CI."Nombre"                 AS ciudad,
           P."LugarTrabajo"            AS lugar_trabajo,
           P."Sede"                    AS sede,
           P."FechaHoraInicioTarea"    AS fecha_hora_inicio_tarea,
           P."FechaHoraFinTarea"       AS fecha_hora_fin_tarea,
           P."FechaCreacion"           AS fecha_creacion,
           P."Estado"                  AS estado,
           P."TipoTrabajoAlturas"      AS tipo_trabajo_alturas,
           P."DescripcionProcedimiento" AS descripcion_procedimiento,
           P."HerramientasUtensilios"  AS herramientas_utensilios,
           P."AlturaAproximadaMetros"  AS altura_aproximada_metros,
           P."ReEntrenamiento"         AS re_entrenamiento,
           P."SistemasAcceso"          AS sistemas_acceso,
           P."SistemasIngenieria"      AS sistemas_ingenieria,
           P."MedidasColectivas"       AS medidas_colectivas,
           P."TrabajoSuspension"       AS trabajo_suspension,
           P."OtroElementoProteccion"  AS otro_elemento_proteccion,
           P."AplicaAyudanteSeguridad" AS aplica_ayudante_seguridad,
           P."Observaciones"           AS observaciones,
           P."FechaAutorizacion"       AS fecha_autorizacion,
           P."CorreoEnviadoA"          AS correo_enviado_a,
           P."FechaEnvioCorreo"        AS fecha_envio_correo,
           P."ErrorEnvioCorreo"        AS error_envio_correo,
           """ + _sql_lista_completa(TIPO_ITEM_PROTECCION) + """ AS proteccion_completa,
           """ + _sql_lista_completa(TIPO_ITEM_VERIFICACION) + """ AS verificacion_completa,
           """ + _sql_lista_completa(TIPO_ITEM_PELIGRO) + """ AS peligros_completa,
           (
               SELECT COUNT(*)
               FROM public."PermisoTrabajoAlturasTrabajador" T
               WHERE T."IdPermisoTrabajoAlturas" = P."IdPermisoTrabajoAlturas"
           )                           AS cantidad_trabajadores
    FROM public."PermisoTrabajoAlturas" P
    JOIN public."Cliente" C ON C."IdCliente" = P."IdCliente"
    LEFT JOIN public."Ciudad" CI ON CI."IdCiudad" = P."IdCiudad"
    LEFT JOIN public."RegistroPersonal" RR
      ON RR."IdRegistroPersonal" = P."IdRegistroPersonalResponsable"
"""


@router.get("/permisos", response_model=list[PermisoTrabajoAlturasOut])
def listar_permisos(
    # Temporal: mientras no existan los roles, la consulta se filtra por el
    # responsable que se elige en pantalla. Luego cada usuario verá solo los
    # permisos que creó y roles como Gerencia HSEQ verán todos (sin filtro).
    id_registro_personal_responsable: int | None = Query(None, gt=0),
    db: Session = Depends(get_db),
    _current=Depends(require_operaciones_alturas),
):
    filas = db.execute(
        text(
            SQL_PERMISOS
            + """
            WHERE CAST(:id_responsable AS bigint) IS NULL
               OR P."IdRegistroPersonalResponsable" = :id_responsable
            ORDER BY P."IdPermisoTrabajoAlturas" DESC
            LIMIT 200
            """
        ),
        {"id_responsable": id_registro_personal_responsable},
    ).mappings().all()

    return [dict(fila) for fila in filas]


@router.post(
    "/permisos",
    response_model=PermisoTrabajoAlturasOut,
    status_code=status.HTTP_201_CREATED,
)
def crear_permiso(
    payload: PermisoTrabajoAlturasIn,
    db: Session = Depends(get_db),
    _current=Depends(require_operaciones_alturas),
):
    if payload.hora_fin_tarea <= payload.hora_inicio_tarea:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "La hora de finalización debe ser mayor "
                "a la hora de inicio."
            ),
        )

    cliente = db.execute(
        text("""
            SELECT "Nombre"
            FROM public."Cliente"
            WHERE "IdCliente" = :id_cliente
              AND COALESCE("Activo", TRUE)
        """),
        {"id_cliente": payload.id_cliente},
    ).scalar()

    if cliente is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="El cliente seleccionado no existe o está inactivo.",
        )

    lugar_trabajo = _texto_requerido(payload.lugar_trabajo, "Lugar de trabajo")

    ciudad = db.execute(
        text("""
            SELECT "Nombre"
            FROM public."Ciudad"
            WHERE "IdCiudad" = :id_ciudad
              AND COALESCE("Estado", TRUE)
        """),
        {"id_ciudad": payload.id_ciudad},
    ).scalar()

    if ciudad is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="La ciudad seleccionada no existe o está inactiva.",
        )

    responsable = db.execute(
        text("""
            SELECT TRIM("Nombres" || ' ' || "Apellidos") AS nombre,
                   "NumeroIdentificacion"                AS numero_identificacion
            FROM public."RegistroPersonal"
            WHERE "IdRegistroPersonal" = :id_responsable
              AND "IdEstadoProceso" = :id_estado
        """),
        {
            "id_responsable": payload.id_registro_personal_responsable,
            "id_estado": ID_ESTADO_CONTRATADO,
        },
    ).mappings().first()

    if responsable is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="El responsable no existe o no está en estado Contratado.",
        )

    try:
        # La fecha siempre es la de hoy en Colombia; del usuario solo se
        # reciben las horas.
        fila = db.execute(
            text("""
                WITH hoy AS (
                    SELECT (now() AT TIME ZONE :zona)::date AS fecha
                )
                INSERT INTO public."PermisoTrabajoAlturas" (
                    "IdRegistroPersonalResponsable",
                    "IdCliente",
                    "IdCiudad",
                    "LugarTrabajo",
                    "FechaHoraInicioTarea",
                    "FechaHoraFinTarea"
                )
                SELECT :id_responsable,
                       :id_cliente,
                       :id_ciudad,
                       :lugar_trabajo,
                       (hoy.fecha + CAST(:hora_inicio AS time)) AT TIME ZONE :zona,
                       (hoy.fecha + CAST(:hora_fin AS time)) AT TIME ZONE :zona
                FROM hoy
                RETURNING "IdPermisoTrabajoAlturas" AS id_permiso_trabajo_alturas,
                          "IdRegistroPersonalResponsable" AS id_registro_personal_responsable,
                          "IdCliente"               AS id_cliente,
                          "IdCiudad"                AS id_ciudad,
                          "LugarTrabajo"            AS lugar_trabajo,
                          "Sede"                    AS sede,
                          "FechaHoraInicioTarea"    AS fecha_hora_inicio_tarea,
                          "FechaHoraFinTarea"       AS fecha_hora_fin_tarea,
                          "FechaCreacion"           AS fecha_creacion,
                          "Estado"                  AS estado
            """),
            {
                "id_responsable": payload.id_registro_personal_responsable,
                "id_cliente": payload.id_cliente,
                "id_ciudad": payload.id_ciudad,
                "lugar_trabajo": lugar_trabajo,
                "hora_inicio": payload.hora_inicio_tarea,
                "hora_fin": payload.hora_fin_tarea,
                "zona": ZONA_HORARIA,
            },
        ).mappings().one()
        db.commit()
    except Exception:
        db.rollback()
        raise

    return {
        **fila,
        "cliente": cliente,
        "ciudad": ciudad,
        "responsable": responsable["nombre"],
        "numero_identificacion_responsable": responsable["numero_identificacion"],
    }


# ─────────────────────────────────────────────
# Trabajadores del permiso
# ─────────────────────────────────────────────
SQL_TRABAJADORES_PERMISO = """
    SELECT T."IdPermisoTrabajoAlturasTrabajador" AS id_permiso_trabajo_alturas_trabajador,
           T."IdPermisoTrabajoAlturas"           AS id_permiso_trabajo_alturas,
           T."IdRegistroPersonal"                AS id_registro_personal,
           R."NumeroIdentificacion"              AS numero_identificacion,
           TRIM(R."Nombres" || ' ' || R."Apellidos") AS nombre_completo,
           T."FechaExamenMedico"                 AS fecha_examen_medico,
           T."FechaCertificadoAlturas"           AS fecha_certificado_alturas,
           T."SeguridadSocialVerificada"         AS seguridad_social_verificada,
           T."ConsumeSustancias"                 AS consume_sustancias,
           T."PresentaImpedimentoAlturas"        AS presenta_impedimento_alturas,
           T."IngirioAlcohol12Horas"             AS ingirio_alcohol_12_horas,
           T."MiedoAlturasVertigo"               AS miedo_alturas_vertigo,
           T."OtroImpedimentoAlturas"            AS otro_impedimento_alturas,
           T."ConsumeMedicamentos"               AS consume_medicamentos,
           T."CualesMedicamentos"                AS cuales_medicamentos,
           T."MedicamentosPresionArterial"       AS medicamentos_presion_arterial,
           T."MedicamentosSomnolencia"           AS medicamentos_somnolencia,
           T."CualMedicamentoSomnolencia"        AS cual_medicamento_somnolencia,
           T."OtroMedicamento"                   AS otro_medicamento,
           T."PresentaCondicionSalud"            AS presenta_condicion_salud,
           T."OtraCondicionSalud"                AS otra_condicion_salud,
""" + "".join(
    f'           T."{columna}" AS {campo},\n'
    for campo, columna in CONDICIONES_SALUD.items()
) + """           T."FechaFirma"                        AS fecha_firma,
           T."FechaCreacion"                     AS fecha_creacion
    FROM public."PermisoTrabajoAlturasTrabajador" T
    JOIN public."RegistroPersonal" R
      ON R."IdRegistroPersonal" = T."IdRegistroPersonal"
"""


def _decodificar_firma(firma_png: str) -> bytes:
    """Convierte la data URL de la firma en bytes PNG validados."""
    error = HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail="La firma no es válida. Vuelve a firmar.",
    )

    if not firma_png.startswith(PREFIJO_FIRMA_PNG):
        raise error

    # Base64 ocupa ~4/3 del tamaño real: se descarta antes de decodificar.
    if len(firma_png) > FIRMA_TAMANO_MAXIMO * 4 // 3 + len(PREFIJO_FIRMA_PNG) + 4:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="La imagen de la firma es demasiado grande.",
        )

    try:
        imagen = base64.b64decode(
            firma_png[len(PREFIJO_FIRMA_PNG):], validate=True
        )
    except (binascii.Error, ValueError):
        raise error

    if not imagen.startswith(FIRMA_PNG_ENCABEZADO):
        raise error

    if len(imagen) > FIRMA_TAMANO_MAXIMO:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="La imagen de la firma es demasiado grande.",
        )

    return imagen


def _validar_permiso_editable(db: Session, id_permiso: int) -> None:
    """El permiso existe y todavía está en diligenciamiento."""
    estado = db.execute(
        text("""
            SELECT "Estado"
            FROM public."PermisoTrabajoAlturas"
            WHERE "IdPermisoTrabajoAlturas" = :id_permiso
        """),
        {"id_permiso": id_permiso},
    ).scalar()

    if estado is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="El permiso de trabajo en alturas no existe.",
        )

    if estado != ESTADO_EN_DILIGENCIAMIENTO:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="El permiso ya fue autorizado y no se puede modificar.",
        )


def _texto_requerido(valor: str, campo: str) -> str:
    texto = (valor or "").strip()

    if not texto:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"El campo {campo} es obligatorio.",
        )

    return texto


@router.get("/permisos/{id_permiso}", response_model=PermisoDetalleOut)
def obtener_permiso(
    id_permiso: int,
    db: Session = Depends(get_db),
    _current=Depends(require_operaciones_alturas),
):
    fila = db.execute(
        text(SQL_PERMISOS + ' WHERE P."IdPermisoTrabajoAlturas" = :id_permiso'),
        {"id_permiso": id_permiso},
    ).mappings().first()

    if fila is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="El permiso de trabajo en alturas no existe.",
        )

    firmas = db.execute(
        text("""
            SELECT F."Rol"                 AS rol,
                   F."IdRegistroPersonal"  AS id_registro_personal,
                   TRIM(R."Nombres" || ' ' || R."Apellidos") AS nombre_completo,
                   R."NumeroIdentificacion" AS numero_identificacion,
                   F."FechaFirma"          AS fecha_firma
            FROM public."PermisoTrabajoAlturasFirma" F
            JOIN public."RegistroPersonal" R
              ON R."IdRegistroPersonal" = F."IdRegistroPersonal"
            WHERE F."IdPermisoTrabajoAlturas" = :id_permiso
            ORDER BY F."IdPermisoTrabajoAlturasFirma"
        """),
        {"id_permiso": id_permiso},
    ).mappings().all()

    return {
        **fila,
        "firmas": [dict(firma) for firma in firmas],
        "correos_notificacion": obtener_correos_notificacion(),
    }


@router.put("/permisos/{id_permiso}/tarea", response_model=PermisoDetalleOut)
def guardar_tarea_permiso(
    id_permiso: int,
    payload: TareaPermisoIn,
    db: Session = Depends(get_db),
    _current=Depends(require_operaciones_alturas),
):
    """Paso 3: datos básicos de la tarea y medidas de prevención."""
    _validar_permiso_editable(db, id_permiso)

    datos = {
        "tipo_trabajo_alturas": _texto_requerido(
            payload.tipo_trabajo_alturas, "Tipo de trabajo en alturas"
        ),
        "descripcion_procedimiento": _texto_requerido(
            payload.descripcion_procedimiento,
            "Descripción y procedimiento de la tarea",
        ),
        "herramientas_utensilios": _texto_requerido(
            payload.herramientas_utensilios, "Herramientas y utensilios"
        ),
        "altura_aproximada_metros": payload.altura_aproximada_metros,
        "re_entrenamiento": payload.re_entrenamiento,
        "sistemas_acceso": _texto_requerido(
            payload.sistemas_acceso, "Sistemas de acceso"
        ),
        "sistemas_ingenieria": (payload.sistemas_ingenieria or "").strip()
        or None,
        "medidas_colectivas": (payload.medidas_colectivas or "").strip()
        or None,
        "trabajo_suspension": payload.trabajo_suspension,
    }

    try:
        db.execute(
            text("""
                UPDATE public."PermisoTrabajoAlturas"
                SET "TipoTrabajoAlturas"       = :tipo_trabajo_alturas,
                    "DescripcionProcedimiento" = :descripcion_procedimiento,
                    "HerramientasUtensilios"   = :herramientas_utensilios,
                    "AlturaAproximadaMetros"   = :altura_aproximada_metros,
                    "ReEntrenamiento"          = :re_entrenamiento,
                    "SistemasAcceso"           = :sistemas_acceso,
                    "SistemasIngenieria"       = :sistemas_ingenieria,
                    "MedidasColectivas"        = :medidas_colectivas,
                    "TrabajoSuspension"        = :trabajo_suspension
                WHERE "IdPermisoTrabajoAlturas" = :id_permiso
            """),
            {**datos, "id_permiso": id_permiso},
        )
        db.commit()
    except Exception:
        db.rollback()
        raise

    return obtener_permiso(id_permiso, db, _current)


def _listar_items_permiso(db: Session, id_permiso: int, tipo: str) -> list[dict]:
    """Preguntas activas de una lista con la respuesta del permiso (si hay)."""
    filas = db.execute(
        text("""
            SELECT I."IdItemPermisoAlturas" AS id_item_permiso_alturas,
                   I."Codigo"               AS codigo,
                   I."Texto"                AS texto,
                   I."Orden"                AS orden,
                   R."Respuesta"            AS respuesta
            FROM public."ItemPermisoAlturas" I
            LEFT JOIN public."PermisoTrabajoAlturasRespuesta" R
              ON R."IdItemPermisoAlturas" = I."IdItemPermisoAlturas"
             AND R."IdPermisoTrabajoAlturas" = :id_permiso
            WHERE I."TipoItem" = :tipo
              AND I."Activo"
            ORDER BY I."Orden"
        """),
        {"id_permiso": id_permiso, "tipo": tipo},
    ).mappings().all()

    return [dict(fila) for fila in filas]


def _guardar_respuestas_permiso(
    db: Session,
    id_permiso: int,
    tipo: str,
    respuestas: list[ItemRespuestaIn],
) -> None:
    """
    Guarda (o reemplaza) las respuestas de una lista. Exige que se respondan
    todas las preguntas activas de esa lista y solo esas. No hace commit.
    """
    activos = set(
        db.execute(
            text("""
                SELECT "IdItemPermisoAlturas"
                FROM public."ItemPermisoAlturas"
                WHERE "TipoItem" = :tipo
                  AND "Activo"
            """),
            {"tipo": tipo},
        ).scalars().all()
    )

    enviados = [r.id_item_permiso_alturas for r in respuestas]

    if len(enviados) != len(set(enviados)) or set(enviados) - activos:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Las respuestas no corresponden a las preguntas de este paso.",
        )

    if activos - set(enviados):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Responde todas las preguntas de este paso.",
        )

    for respuesta in respuestas:
        db.execute(
            text("""
                INSERT INTO public."PermisoTrabajoAlturasRespuesta" (
                    "IdPermisoTrabajoAlturas",
                    "IdItemPermisoAlturas",
                    "Respuesta"
                )
                VALUES (:id_permiso, :id_item, :respuesta)
                ON CONFLICT ("IdPermisoTrabajoAlturas", "IdItemPermisoAlturas")
                DO UPDATE SET "Respuesta"     = EXCLUDED."Respuesta",
                              "FechaRegistro" = now()
            """),
            {
                "id_permiso": id_permiso,
                "id_item": respuesta.id_item_permiso_alturas,
                "respuesta": respuesta.respuesta,
            },
        )


@router.get("/permisos/{id_permiso}/proteccion", response_model=ProteccionOut)
def obtener_proteccion_permiso(
    id_permiso: int,
    db: Session = Depends(get_db),
    _current=Depends(require_operaciones_alturas),
):
    """Paso 4: elementos de protección personal y contra caídas."""
    otro = db.execute(
        text("""
            SELECT "IdPermisoTrabajoAlturas", "OtroElementoProteccion"
            FROM public."PermisoTrabajoAlturas"
            WHERE "IdPermisoTrabajoAlturas" = :id_permiso
        """),
        {"id_permiso": id_permiso},
    ).first()

    if otro is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="El permiso de trabajo en alturas no existe.",
        )

    return {
        "items": _listar_items_permiso(db, id_permiso, TIPO_ITEM_PROTECCION),
        "otro_elemento_proteccion": otro[1],
    }


@router.put("/permisos/{id_permiso}/proteccion", response_model=PermisoDetalleOut)
def guardar_proteccion_permiso(
    id_permiso: int,
    payload: ProteccionIn,
    db: Session = Depends(get_db),
    _current=Depends(require_operaciones_alturas),
):
    """Paso 4: guarda las respuestas Sí / No / No aplica y "Otro ¿cuál?"."""
    _validar_permiso_editable(db, id_permiso)

    try:
        _guardar_respuestas_permiso(
            db, id_permiso, TIPO_ITEM_PROTECCION, payload.respuestas
        )
        db.execute(
            text("""
                UPDATE public."PermisoTrabajoAlturas"
                SET "OtroElementoProteccion" = :otro
                WHERE "IdPermisoTrabajoAlturas" = :id_permiso
            """),
            {
                "id_permiso": id_permiso,
                "otro": (payload.otro_elemento_proteccion or "").strip() or None,
            },
        )
        db.commit()
    except Exception:
        db.rollback()
        raise

    return obtener_permiso(id_permiso, db, _current)


@router.get("/permisos/{id_permiso}/verificacion", response_model=ListaItemsOut)
def obtener_verificacion_permiso(
    id_permiso: int,
    db: Session = Depends(get_db),
    _current=Depends(require_operaciones_alturas),
):
    """Paso 5: lista de verificación."""
    _validar_permiso_existe(db, id_permiso)

    return {
        "items": _listar_items_permiso(db, id_permiso, TIPO_ITEM_VERIFICACION),
    }


@router.put("/permisos/{id_permiso}/verificacion", response_model=PermisoDetalleOut)
def guardar_verificacion_permiso(
    id_permiso: int,
    payload: ListaItemsIn,
    db: Session = Depends(get_db),
    _current=Depends(require_operaciones_alturas),
):
    """Paso 5: guarda las respuestas Sí / No / No aplica."""
    _validar_permiso_editable(db, id_permiso)

    try:
        _guardar_respuestas_permiso(
            db, id_permiso, TIPO_ITEM_VERIFICACION, payload.respuestas
        )
        db.commit()
    except Exception:
        db.rollback()
        raise

    return obtener_permiso(id_permiso, db, _current)


@router.get("/permisos/{id_permiso}/peligros", response_model=ListaItemsOut)
def obtener_peligros_permiso(
    id_permiso: int,
    db: Session = Depends(get_db),
    _current=Depends(require_operaciones_alturas),
):
    """Paso 6: identificación de peligros del trabajo a realizar."""
    _validar_permiso_existe(db, id_permiso)

    return {
        "items": _listar_items_permiso(db, id_permiso, TIPO_ITEM_PELIGRO),
    }


@router.put("/permisos/{id_permiso}/peligros", response_model=PermisoDetalleOut)
def guardar_peligros_permiso(
    id_permiso: int,
    payload: ListaItemsIn,
    db: Session = Depends(get_db),
    _current=Depends(require_operaciones_alturas),
):
    """Paso 6: guarda las respuestas Sí / No / No aplica."""
    _validar_permiso_editable(db, id_permiso)

    try:
        _guardar_respuestas_permiso(
            db, id_permiso, TIPO_ITEM_PELIGRO, payload.respuestas
        )
        db.commit()
    except Exception:
        db.rollback()
        raise

    return obtener_permiso(id_permiso, db, _current)


def _persona_contratada(db: Session, id_registro_personal: int, rol: str) -> None:
    contratada = db.execute(
        text("""
            SELECT 1
            FROM public."RegistroPersonal"
            WHERE "IdRegistroPersonal" = :id_registro_personal
              AND "IdEstadoProceso" = :id_estado
        """),
        {
            "id_registro_personal": id_registro_personal,
            "id_estado": ID_ESTADO_CONTRATADO,
        },
    ).scalar()

    if not contratada:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"{rol}: la persona no existe o no está en estado Contratado.",
        )


def _pasos_pendientes(permiso: dict) -> list[str]:
    pendientes = []

    if not permiso["cantidad_trabajadores"]:
        pendientes.append("2. Trabajadores")

    tarea_completa = all(
        permiso[campo] not in (None, "")
        for campo in (
            "tipo_trabajo_alturas",
            "descripcion_procedimiento",
            "herramientas_utensilios",
            "altura_aproximada_metros",
            "re_entrenamiento",
            "sistemas_acceso",
            "trabajo_suspension",
        )
    )

    if not tarea_completa:
        pendientes.append("3. Tarea")

    if not permiso["proteccion_completa"]:
        pendientes.append("4. Protección")

    if not permiso["verificacion_completa"]:
        pendientes.append("5. Verificación")

    if not permiso["peligros_completa"]:
        pendientes.append("6. Peligros")

    return pendientes


@router.post("/permisos/{id_permiso}/autorizar", response_model=PermisoDetalleOut)
def autorizar_permiso(
    id_permiso: int,
    payload: AutorizacionPermisoIn,
    tareas: BackgroundTasks,
    db: Session = Depends(get_db),
    _current=Depends(require_operaciones_alturas),
):
    """
    Paso 7: registra las firmas, pasa el permiso a AUTORIZADO (ya no se puede
    modificar) y lo envía por correo a los destinatarios del servidor.
    """
    _validar_permiso_editable(db, id_permiso)
    permiso = obtener_permiso(id_permiso, db, _current)

    pendientes = _pasos_pendientes(permiso)

    if pendientes:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Completa antes los pasos: " + ", ".join(pendientes) + ".",
        )

    if not permiso["id_registro_personal_responsable"]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="El permiso no tiene responsable (coordinador) que pueda firmar.",
        )

    _persona_contratada(
        db, payload.id_registro_personal_autoriza, "Quien autoriza el trabajo"
    )
    _persona_contratada(
        db,
        payload.id_registro_personal_emergencias,
        "Responsable del plan de emergencias",
    )

    firmas = [
        ("AUTORIZA", payload.id_registro_personal_autoriza,
         _decodificar_firma(payload.firma_autoriza)),
        ("COORDINADOR", permiso["id_registro_personal_responsable"],
         _decodificar_firma(payload.firma_coordinador)),
        ("EMERGENCIAS", payload.id_registro_personal_emergencias,
         _decodificar_firma(payload.firma_emergencias)),
    ]

    if payload.aplica_ayudante_seguridad:
        if not payload.id_registro_personal_ayudante or not payload.firma_ayudante:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Selecciona el ayudante de seguridad y registra su firma.",
            )

        _persona_contratada(
            db, payload.id_registro_personal_ayudante, "Ayudante de seguridad"
        )
        firmas.append(
            ("AYUDANTE", payload.id_registro_personal_ayudante,
             _decodificar_firma(payload.firma_ayudante))
        )

    try:
        # Solo se autoriza si sigue en diligenciamiento (evita autorizar dos
        # veces si se envía al mismo tiempo desde dos equipos).
        actualizado = db.execute(
            text("""
                UPDATE public."PermisoTrabajoAlturas"
                SET "Estado"                  = :autorizado,
                    "FechaAutorizacion"       = now(),
                    "AplicaAyudanteSeguridad" = :aplica_ayudante,
                    "Observaciones"           = :observaciones
                WHERE "IdPermisoTrabajoAlturas" = :id_permiso
                  AND "Estado" = :en_diligenciamiento
            """),
            {
                "id_permiso": id_permiso,
                "autorizado": ESTADO_AUTORIZADO,
                "en_diligenciamiento": ESTADO_EN_DILIGENCIAMIENTO,
                "aplica_ayudante": payload.aplica_ayudante_seguridad,
                "observaciones": (payload.observaciones or "").strip() or None,
            },
        ).rowcount

        if not actualizado:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="El permiso ya fue autorizado y no se puede modificar.",
            )

        for rol, id_registro_personal, imagen in firmas:
            db.execute(
                text("""
                    INSERT INTO public."PermisoTrabajoAlturasFirma" (
                        "IdPermisoTrabajoAlturas",
                        "Rol",
                        "IdRegistroPersonal",
                        "FirmaImagen"
                    )
                    VALUES (:id_permiso, :rol, :id_registro_personal, :imagen)
                """),
                {
                    "id_permiso": id_permiso,
                    "rol": rol,
                    "id_registro_personal": id_registro_personal,
                    "imagen": imagen,
                },
            )

        db.commit()
    except Exception:
        db.rollback()
        raise

    # El correo se envía después de responder; su resultado queda en el permiso.
    tareas.add_task(enviar_permiso_autorizado, id_permiso)

    return obtener_permiso(id_permiso, db, _current)


@router.post(
    "/permisos/{id_permiso}/reenviar-correo",
    status_code=status.HTTP_202_ACCEPTED,
)
def reenviar_correo_permiso(
    id_permiso: int,
    tareas: BackgroundTasks,
    db: Session = Depends(get_db),
    _current=Depends(require_operaciones_alturas),
):
    """Vuelve a enviar el permiso autorizado (por ejemplo, si el envío falló)."""
    estado = db.execute(
        text("""
            SELECT "Estado"
            FROM public."PermisoTrabajoAlturas"
            WHERE "IdPermisoTrabajoAlturas" = :id_permiso
        """),
        {"id_permiso": id_permiso},
    ).scalar()

    if estado is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="El permiso de trabajo en alturas no existe.",
        )

    if estado == ESTADO_EN_DILIGENCIAMIENTO:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Solo se puede enviar un permiso autorizado.",
        )

    tareas.add_task(enviar_permiso_autorizado, id_permiso)

    return {"mensaje": "El envío del permiso quedó en proceso."}


@router.get(
    "/permisos/{id_permiso}/pdf",
    response_class=Response,
    responses={200: {"content": {"application/pdf": {}}}},
)
def descargar_pdf_permiso(
    id_permiso: int,
    db: Session = Depends(get_db),
    _current=Depends(require_operaciones_alturas),
):
    """
    PDF del permiso (formato F-SS-007). Si aún no está autorizado, sale con la
    marca de agua "BORRADOR".
    """
    pdf = generar_pdf_permiso_alturas(db, id_permiso)

    if pdf is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="El permiso de trabajo en alturas no existe.",
        )

    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={
            "Content-Disposition": (
                f'inline; filename="permiso_alturas_{id_permiso}.pdf"'
            ),
        },
    )


@router.get(
    "/permisos/{id_permiso}/firmas/{rol}",
    response_class=Response,
    responses={200: {"content": {"image/png": {}}}},
)
def obtener_firma_permiso(
    id_permiso: int,
    rol: str,
    db: Session = Depends(get_db),
    _current=Depends(require_operaciones_alturas),
):
    if rol not in ROLES_FIRMA:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Rol de firma no válido.",
        )

    firma = db.execute(
        text("""
            SELECT "FirmaImagen"
            FROM public."PermisoTrabajoAlturasFirma"
            WHERE "IdPermisoTrabajoAlturas" = :id_permiso
              AND "Rol" = :rol
        """),
        {"id_permiso": id_permiso, "rol": rol},
    ).scalar()

    if not firma:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No hay firma registrada para ese rol en este permiso.",
        )

    return Response(content=bytes(firma), media_type="image/png")


def _validar_permiso_existe(db: Session, id_permiso: int) -> None:
    existe = db.execute(
        text("""
            SELECT 1
            FROM public."PermisoTrabajoAlturas"
            WHERE "IdPermisoTrabajoAlturas" = :id_permiso
        """),
        {"id_permiso": id_permiso},
    ).scalar()

    if not existe:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="El permiso de trabajo en alturas no existe.",
        )


@router.get(
    "/trabajadores/buscar",
    response_model=list[TrabajadorBusquedaOut],
)
def buscar_trabajadores(
    q: str = Query(..., min_length=3, max_length=100),
    db: Session = Depends(get_db),
    _current=Depends(require_operaciones_alturas),
):
    filas = db.execute(
        text("""
            SELECT "IdRegistroPersonal"   AS id_registro_personal,
                   "NumeroIdentificacion" AS numero_identificacion,
                   TRIM("Nombres" || ' ' || "Apellidos") AS nombre_completo
            FROM public."RegistroPersonal"
            WHERE "IdEstadoProceso" = :id_estado
              AND (
                  "NumeroIdentificacion" LIKE :inicio
                  OR ("Nombres" || ' ' || "Apellidos") ILIKE :contiene
              )
            ORDER BY "Nombres", "Apellidos"
            LIMIT 20
        """),
        {
            "id_estado": ID_ESTADO_CONTRATADO,
            "inicio": f"{q.strip()}%",
            "contiene": f"%{q.strip()}%",
        },
    ).mappings().all()

    return [dict(fila) for fila in filas]


@router.get(
    "/permisos/{id_permiso}/trabajadores",
    response_model=list[PermisoTrabajadorOut],
)
def listar_trabajadores_permiso(
    id_permiso: int,
    db: Session = Depends(get_db),
    _current=Depends(require_operaciones_alturas),
):
    _validar_permiso_existe(db, id_permiso)

    filas = db.execute(
        text(
            SQL_TRABAJADORES_PERMISO
            + """
            WHERE T."IdPermisoTrabajoAlturas" = :id_permiso
            ORDER BY T."IdPermisoTrabajoAlturasTrabajador"
            """
        ),
        {"id_permiso": id_permiso},
    ).mappings().all()

    return [dict(fila) for fila in filas]


@router.post(
    "/permisos/{id_permiso}/trabajadores",
    response_model=PermisoTrabajadorOut,
    status_code=status.HTTP_201_CREATED,
)
def agregar_trabajador_permiso(
    id_permiso: int,
    payload: PermisoTrabajadorIn,
    db: Session = Depends(get_db),
    _current=Depends(require_operaciones_alturas),
):
    _validar_permiso_editable(db, id_permiso)

    firma_imagen = _decodificar_firma(payload.firma_png)

    hoy = db.execute(
        text("SELECT (now() AT TIME ZONE :zona)::date"),
        {"zona": ZONA_HORARIA},
    ).scalar()

    if payload.fecha_examen_medico > hoy:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="La fecha del examen médico no puede ser futura.",
        )

    if payload.fecha_certificado_alturas > hoy:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="La fecha del certificado de alturas no puede ser futura.",
        )

    medicamentos = {
        "medicamentos_presion_arterial": False,
        "medicamentos_somnolencia": False,
        "cual_medicamento_somnolencia": None,
        "otro_medicamento": None,
    }

    if payload.consume_medicamentos:
        if (
            payload.medicamentos_presion_arterial is None
            or payload.medicamentos_somnolencia is None
        ):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Responde las preguntas de medicamentos del trabajador.",
            )

        medicamentos["medicamentos_presion_arterial"] = (
            payload.medicamentos_presion_arterial
        )
        medicamentos["medicamentos_somnolencia"] = (
            payload.medicamentos_somnolencia
        )

        if payload.medicamentos_somnolencia:
            medicamentos["cual_medicamento_somnolencia"] = (
                (payload.cual_medicamento_somnolencia or "").strip() or None
            )

            if not medicamentos["cual_medicamento_somnolencia"]:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=(
                        "Indica cuál medicamento que causa somnolencia "
                        "toma el trabajador."
                    ),
                )

        # Consume medicamentos, pero ninguno de los dos tipos preguntados:
        # debe indicar cuál para que quede informado.
        if not (
            payload.medicamentos_presion_arterial
            or payload.medicamentos_somnolencia
        ):
            medicamentos["otro_medicamento"] = (
                (payload.otro_medicamento or "").strip() or None
            )

            if not medicamentos["otro_medicamento"]:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Indica cuál medicamento consume el trabajador.",
                )

    if payload.presenta_impedimento_alturas:
        if any(
            getattr(payload, campo) is None for campo in IMPEDIMENTOS_ALTURAS
        ):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    "Responde las preguntas sobre condiciones o situaciones "
                    "que impiden trabajar en alturas."
                ),
            )

        impedimentos = {
            campo: getattr(payload, campo) for campo in IMPEDIMENTOS_ALTURAS
        }
        otro_impedimento_alturas = None

        # Declaró un impedimento, pero ninguno de los preguntados: debe
        # describirlo para que quede informado.
        if not any(impedimentos.values()):
            otro_impedimento_alturas = (
                (payload.otro_impedimento_alturas or "").strip() or None
            )

            if not otro_impedimento_alturas:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=(
                        "Describe la condición o situación que le impide "
                        "realizar el trabajo en alturas de manera segura."
                    ),
                )
    else:
        # Sin impedimento declarado: las subpreguntas quedan en NO.
        impedimentos = {campo: False for campo in IMPEDIMENTOS_ALTURAS}
        otro_impedimento_alturas = None

    if payload.presenta_condicion_salud:
        sin_responder = [
            campo
            for campo in CONDICIONES_SALUD
            if getattr(payload, campo) is None
        ]

        if sin_responder:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    "Responde todas las condiciones de salud del trabajador."
                ),
            )

        condiciones = {
            campo: getattr(payload, campo) for campo in CONDICIONES_SALUD
        }

        otra_condicion_salud = None

        # Declaró una condición de salud, pero ninguna de la lista: debe
        # describirla para que quede informada.
        if not any(condiciones.values()):
            otra_condicion_salud = (
                (payload.otra_condicion_salud or "").strip() or None
            )

            if not otra_condicion_salud:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=(
                        "Describe la condición o restricción de salud del "
                        "trabajador."
                    ),
                )
    else:
        # Sin condición de salud declarada: todas las específicas quedan en NO.
        condiciones = {campo: False for campo in CONDICIONES_SALUD}
        otra_condicion_salud = None

    estado_trabajador = db.execute(
        text("""
            SELECT "IdEstadoProceso"
            FROM public."RegistroPersonal"
            WHERE "IdRegistroPersonal" = :id_registro_personal
        """),
        {"id_registro_personal": payload.id_registro_personal},
    ).scalar()

    if estado_trabajador != ID_ESTADO_CONTRATADO:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="El trabajador no existe o no está en estado Contratado.",
        )

    try:
        id_nuevo = db.execute(
            text("""
                INSERT INTO public."PermisoTrabajoAlturasTrabajador" (
                    "IdPermisoTrabajoAlturas",
                    "IdRegistroPersonal",
                    "FechaExamenMedico",
                    "FechaCertificadoAlturas",
                    "SeguridadSocialVerificada",
                    "ConsumeSustancias",
                    "PresentaImpedimentoAlturas",
                    "IngirioAlcohol12Horas",
                    "MiedoAlturasVertigo",
                    "OtroImpedimentoAlturas",
                    "ConsumeMedicamentos",
                    "MedicamentosPresionArterial",
                    "MedicamentosSomnolencia",
                    "CualMedicamentoSomnolencia",
                    "OtroMedicamento",
                    "FirmaImagen",
                    "FechaFirma",
                    "PresentaCondicionSalud",
                    "OtraCondicionSalud",
                    """ + ",\n                    ".join(
                        f'"{columna}"' for columna in CONDICIONES_SALUD.values()
                    ) + """
                )
                VALUES (
                    :id_permiso,
                    :id_registro_personal,
                    :fecha_examen_medico,
                    :fecha_certificado_alturas,
                    :seguridad_social_verificada,
                    :consume_sustancias,
                    :presenta_impedimento_alturas,
                    :ingirio_alcohol_12_horas,
                    :miedo_alturas_vertigo,
                    :otro_impedimento_alturas,
                    :consume_medicamentos,
                    :medicamentos_presion_arterial,
                    :medicamentos_somnolencia,
                    :cual_medicamento_somnolencia,
                    :otro_medicamento,
                    :firma_imagen,
                    now(),
                    :presenta_condicion_salud,
                    :otra_condicion_salud,
                    """ + ",\n                    ".join(
                        f":{campo}" for campo in CONDICIONES_SALUD
                    ) + """
                )
                RETURNING "IdPermisoTrabajoAlturasTrabajador"
            """),
            {
                **payload.model_dump(exclude={"firma_png"}),
                "id_permiso": id_permiso,
                "firma_imagen": firma_imagen,
                **impedimentos,
                "otro_impedimento_alturas": otro_impedimento_alturas,
                **medicamentos,
                **condiciones,
                "otra_condicion_salud": otra_condicion_salud,
            },
        ).scalar()
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="El trabajador ya está registrado en este permiso.",
        )
    except Exception:
        db.rollback()
        raise

    fila = db.execute(
        text(
            SQL_TRABAJADORES_PERMISO
            + """
            WHERE T."IdPermisoTrabajoAlturasTrabajador" = :id_nuevo
            """
        ),
        {"id_nuevo": id_nuevo},
    ).mappings().one()

    return dict(fila)


@router.get(
    "/permisos/{id_permiso}/trabajadores/{id_permiso_trabajador}/firma",
    response_class=Response,
    responses={200: {"content": {"image/png": {}}}},
)
def obtener_firma_trabajador(
    id_permiso: int,
    id_permiso_trabajador: int,
    db: Session = Depends(get_db),
    _current=Depends(require_operaciones_alturas),
):
    firma = db.execute(
        text("""
            SELECT "FirmaImagen"
            FROM public."PermisoTrabajoAlturasTrabajador"
            WHERE "IdPermisoTrabajoAlturasTrabajador" = :id_permiso_trabajador
              AND "IdPermisoTrabajoAlturas" = :id_permiso
        """),
        {
            "id_permiso": id_permiso,
            "id_permiso_trabajador": id_permiso_trabajador,
        },
    ).scalar()

    if not firma:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="El trabajador no tiene firma registrada en este permiso.",
        )

    return Response(content=bytes(firma), media_type="image/png")


@router.delete(
    "/permisos/{id_permiso}/trabajadores/{id_permiso_trabajador}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def quitar_trabajador_permiso(
    id_permiso: int,
    id_permiso_trabajador: int,
    db: Session = Depends(get_db),
    _current=Depends(require_operaciones_alturas),
):
    _validar_permiso_editable(db, id_permiso)

    try:
        eliminados = db.execute(
            text("""
                DELETE FROM public."PermisoTrabajoAlturasTrabajador"
                WHERE "IdPermisoTrabajoAlturasTrabajador" = :id_permiso_trabajador
                  AND "IdPermisoTrabajoAlturas" = :id_permiso
            """),
            {
                "id_permiso": id_permiso,
                "id_permiso_trabajador": id_permiso_trabajador,
            },
        ).rowcount
        db.commit()
    except Exception:
        db.rollback()
        raise

    if not eliminados:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="El trabajador no está registrado en este permiso.",
        )
