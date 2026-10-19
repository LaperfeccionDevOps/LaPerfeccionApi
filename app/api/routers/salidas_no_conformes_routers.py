"""Catálogos y gestión de Salidas No Conformes (SNC) para QA y producción."""

from datetime import date, datetime, timezone
from uuid import UUID
import unicodedata

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from infrastructure.db.deps import get_db
from infrastructure.security.auth_dependencies import get_current_user


router = APIRouter(prefix="/api/salidas-no-conformes", tags=["Salidas No Conformes"])


def _verificar_base_permitida(db: Session) -> None:
    """Permite SNC solo en las bases de datos autorizadas de QA y producción."""
    nombre_bd = db.execute(text("SELECT current_database()")).scalar_one()
    if nombre_bd not in ("LA_PERFECCION_QA", "la_perfeccion"):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Módulo SNC no habilitado para la base de datos conectada.",
        )


def _validar_acceso(db: Session, current: dict) -> None:
    """Acceso operativo SNC para usuarios autenticados y activos.

    Las restricciones por creador/responsable se aplican en cada operación.
    El panel general conserva su comprobación exclusiva de SUPERADMIN.
    """
    _verificar_base_permitida(db)
    usuario = current.get("usuario") if isinstance(current, dict) else None
    if usuario is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Sesión sin usuario válido.",
        )
    if (getattr(usuario, "HashEstado", None) or "").strip().upper() != "ACTIVO":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="El usuario está inactivo.",
        )


@router.get("/catalogos/procesos")
def listar_procesos_snc(
    db: Session = Depends(get_db),
    current: dict = Depends(get_current_user),
):
    _validar_acceso(db, current)
    filas = db.execute(
        text('''
            SELECT "IdProcesoSNC" AS id, "NombreProceso" AS nombre
            FROM public."ProcesoSNC"
            WHERE "Activo" = TRUE
            ORDER BY "NombreProceso" ASC
        ''')
    ).mappings().all()
    return [{"id": fila["id"], "nombre": fila["nombre"]} for fila in filas]


@router.get("/catalogos/areas")
def listar_areas_snc(
    db: Session = Depends(get_db),
    current: dict = Depends(get_current_user),
):
    _validar_acceso(db, current)
    filas = db.execute(
        text('''
            SELECT "IdAreaResponsableSNC" AS id, "NombreArea" AS nombre
            FROM public."AreaResponsableSNC"
            WHERE "Activo" = TRUE
            ORDER BY "NombreArea" ASC
        ''')
    ).mappings().all()
    return [{"id": fila["id"], "nombre": fila["nombre"]} for fila in filas]


@router.get("/catalogos/correos")
def listar_correos_snc(
    db: Session = Depends(get_db),
    current: dict = Depends(get_current_user),
):
    _validar_acceso(db, current)
    filas = db.execute(
        text('''
            SELECT "IdCorreoSNC" AS id, "Correo" AS correo,
                   "Descripcion" AS descripcion
            FROM public."CorreoSNC"
            WHERE "Activo" = TRUE
            ORDER BY "Correo" ASC
        ''')
    ).mappings().all()
    return [dict(fila) for fila in filas]


@router.get("/catalogos/usuarios")
def listar_usuarios_snc(
    db: Session = Depends(get_db),
    current: dict = Depends(get_current_user),
):
    _validar_acceso(db, current)
    # No exponer contraseñas, hashes, roles ni permisos en este catálogo.
    filas = db.execute(
        text('''
            SELECT "IdUsuario" AS id, "NombreUsuario" AS nombre
            FROM public."Usuario"
            WHERE UPPER(TRIM(COALESCE("HashEstado", ''))) = 'ACTIVO'
            ORDER BY "NombreUsuario" ASC
        ''')
    ).mappings().all()
    return [{"id": str(fila["id"]), "nombre": fila["nombre"]} for fila in filas]


@router.get("/catalogos/responsables")
def listar_responsables_snc(
    db: Session = Depends(get_db),
    current: dict = Depends(get_current_user),
):
    """Lista los responsables activos en el orden definido por el Forms."""
    _validar_acceso(db, current)
    filas = db.execute(
        text('''
            SELECT "IdResponsableSNC" AS id,
                   "NombreResponsable" AS nombre,
                   "IdUsuario" AS id_usuario
            FROM public."ResponsableSNC"
            WHERE "Activo" = TRUE
            ORDER BY "OrdenVisualizacion" ASC
        ''')
    ).mappings().all()
    return [
        {
            "id": fila["id"],
            "nombre": fila["nombre"],
            "id_usuario": str(fila["id_usuario"]) if fila["id_usuario"] else None,
        }
        for fila in filas
    ]


class CrearSNC(BaseModel):
    fecha_snc: date
    id_proceso_snc: int = Field(gt=0)
    descripcion: str = Field(min_length=1, max_length=20000)
    impacto: str = Field(min_length=1, max_length=20000)
    id_area_responsable_snc: int = Field(gt=0)
    id_responsable_snc: int = Field(gt=0)
    id_correo_remitente: int = Field(gt=0)
    id_correo_destinatario: int = Field(gt=0)

    @field_validator("descripcion", "impacto")
    @classmethod
    def texto_no_vacio(cls, valor: str) -> str:
        valor = valor.strip()
        if not valor:
            raise ValueError("El texto no puede estar vacío.")
        return valor


@router.post("", status_code=status.HTTP_201_CREATED)
def registrar_snc(
    datos: CrearSNC,
    db: Session = Depends(get_db),
    current: dict = Depends(get_current_user),
):
    # Registra una SNC y su historial en una transacción.
    _validar_acceso(db, current)
    try:
        id_creador = UUID(str(current["usuario"].IdUsuario))
    except (KeyError, AttributeError, ValueError, TypeError) as exc:
        raise HTTPException(status_code=401, detail="Sesión sin usuario válido.") from exc

    # Los valores de catálogos siempre se verifican contra la BD, no se confía
    # en el frontend. Se bloquea el responsable para evitar cambios concurrentes.
    for tabla, columna, identificador, etiqueta in (
        ('ProcesoSNC', 'IdProcesoSNC', datos.id_proceso_snc, 'Proceso'),
        ('AreaResponsableSNC', 'IdAreaResponsableSNC', datos.id_area_responsable_snc, 'Área'),
        ('CorreoSNC', 'IdCorreoSNC', datos.id_correo_remitente, 'Correo remitente'),
        ('CorreoSNC', 'IdCorreoSNC', datos.id_correo_destinatario, 'Correo destinatario'),
    ):
        # tabla/columna provienen de constantes del servidor, no del usuario.
        existe = db.execute(
            text(f'SELECT 1 FROM public."{tabla}" WHERE "{columna}" = :id AND "Activo" = TRUE'),
            {'id': identificador},
        ).scalar_one_or_none()
        if existe is None:
            raise HTTPException(status_code=422, detail=f'{etiqueta} no existe o está inactivo.')

    responsable = db.execute(
        text('''
            SELECT r."IdUsuario" AS id_usuario
            FROM public."ResponsableSNC" r
            WHERE r."IdResponsableSNC" = :id AND r."Activo" = TRUE
            FOR UPDATE OF r
        '''),
        {'id': datos.id_responsable_snc},
    ).mappings().first()
    if responsable is None:
        raise HTTPException(status_code=422, detail='Responsable no existe o está inactivo.')

    id_usuario_responsable = responsable['id_usuario']
    if id_usuario_responsable is not None:
        activo = db.execute(
            text('''
                SELECT 1 FROM public."Usuario"
                WHERE "IdUsuario" = :id
                  AND UPPER(TRIM(COALESCE("HashEstado", ''))) = 'ACTIVO'
            '''),
            {'id': id_usuario_responsable},
        ).scalar_one_or_none()
        if activo is None:
            raise HTTPException(status_code=422, detail='La cuenta vinculada al responsable no está activa.')

    # Capturar el área de origen al momento del registro. No se admite
    # crear una SNC sin una asignación activa y válida del usuario creador.
    areas_origen = db.execute(
        text('''
            SELECT ua."IdAreaResponsableSNC" AS id_area
            FROM public."UsuarioAreaSNC" ua
            INNER JOIN public."AreaResponsableSNC" a
                ON a."IdAreaResponsableSNC" = ua."IdAreaResponsableSNC"
            WHERE ua."IdUsuario" = :creador
              AND ua."Activo" = TRUE
              AND a."Activo" = TRUE
            LIMIT 2
        '''),
        {'creador': id_creador},
    ).scalars().all()
    if not areas_origen:
        raise HTTPException(
            status_code=422,
            detail='Tu usuario no tiene un área de trabajo activa configurada. Solicita su asignación antes de registrar la SNC.',
        )
    if len(areas_origen) > 1:
        raise HTTPException(
            status_code=409,
            detail='Tu usuario tiene más de un área de trabajo activa. Solicita corregir la asignación antes de registrar la SNC.',
        )
    id_area_origen = areas_origen[0]

    try:
        id_snc = db.execute(
            text('''
                INSERT INTO public."SalidaNoConforme" (
                    "FechaSNC", "IdUsuarioCreador", "IdProcesoSNC",
                    "Descripcion", "Impacto", "IdAreaResponsableSNC",
                    "IdResponsableSNC", "IdUsuarioResponsable",
                    "IdCorreoRemitente", "IdCorreoDestinatario", "Estado", "IdAreaOrigenSNC"
                ) VALUES (
                    :fecha, :creador, :proceso, :descripcion, :impacto, :area,
                    :responsable, :usuario_responsable, :remitente, :destinatario, 'ABIERTO',
                    :area_origen
                ) RETURNING "IdSalidaNoConforme"
            '''),
            {
                'fecha': datos.fecha_snc,
                'creador': id_creador,
                'proceso': datos.id_proceso_snc,
                'descripcion': datos.descripcion,
                'impacto': datos.impacto,
                'area': datos.id_area_responsable_snc,
                'area_origen': id_area_origen,
                'responsable': datos.id_responsable_snc,
                'usuario_responsable': id_usuario_responsable,
                'remitente': datos.id_correo_remitente,
                'destinatario': datos.id_correo_destinatario,
            },
        ).scalar_one()

        db.execute(
            text('''
                INSERT INTO public."HistorialSalidaNoConforme" (
                    "IdSalidaNoConforme", "IdUsuarioAccion", "TipoAccion",
                    "EstadoAnterior", "EstadoNuevo", "Observacion"
                ) VALUES (
                    :snc, :usuario, 'CREACION', NULL, 'ABIERTO',
                    'Registro inicial de salida no conforme'
                )
            '''),
            {'snc': id_snc, 'usuario': id_creador},
        )
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail='No se pudo registrar la SNC: conflicto con una relación o restricción de la base de datos.',
        ) from exc
    except Exception:
        db.rollback()
        raise

    return {
        'id': id_snc,
        'estado': 'ABIERTO',
        'id_responsable_snc': datos.id_responsable_snc,
        'id_usuario_responsable': str(id_usuario_responsable) if id_usuario_responsable else None,
        'asignacion_pendiente': id_usuario_responsable is None,
        'mensaje': 'SNC registrada correctamente.',
    }


# Fase 3: consultas personales. El usuario se determina exclusivamente
# desde la sesión autenticada, nunca desde parámetros enviados por el cliente.
def _id_usuario_actual(current: dict) -> UUID:
    try:
        return UUID(str(current["usuario"].IdUsuario))
    except (KeyError, AttributeError, ValueError, TypeError) as exc:
        raise HTTPException(status_code=401, detail="Sesión sin usuario válido.") from exc


_CONSULTA_SNC = '''
    SELECT
        s."IdSalidaNoConforme" AS id,
        s."FechaSNC" AS fecha_snc,
        s."Descripcion" AS descripcion,
        s."Impacto" AS impacto,
        s."Estado" AS estado,
        s."FechaCreacion" AS fecha_creacion,
        s."FechaActualizacion" AS fecha_actualizacion,
        s."IdResponsableSNC" AS id_responsable_snc,
        s."IdUsuarioResponsable" AS id_usuario_responsable,
        p."NombreProceso" AS proceso,
        a."NombreArea" AS area_responsable,
        r."NombreResponsable" AS responsable,
        cr."Correo" AS correo_remitente,
        cd."Correo" AS correo_destinatario
    FROM public."SalidaNoConforme" s
    INNER JOIN public."ProcesoSNC" p ON p."IdProcesoSNC" = s."IdProcesoSNC"
    INNER JOIN public."AreaResponsableSNC" a
        ON a."IdAreaResponsableSNC" = s."IdAreaResponsableSNC"
    INNER JOIN public."ResponsableSNC" r
        ON r."IdResponsableSNC" = s."IdResponsableSNC"
    INNER JOIN public."CorreoSNC" cr
        ON cr."IdCorreoSNC" = s."IdCorreoRemitente"
    INNER JOIN public."CorreoSNC" cd
        ON cd."IdCorreoSNC" = s."IdCorreoDestinatario"
    WHERE {filtro}
    ORDER BY s."FechaCreacion" DESC, s."IdSalidaNoConforme" DESC
    LIMIT :limite OFFSET :desplazamiento
'''


def _listar_snc_personales(db: Session, filtro: str, id_usuario: UUID, limite: int, desplazamiento: int):
    # El filtro es una constante del backend, nunca una entrada del usuario.
    if filtro not in ('s."IdUsuarioCreador" = :usuario', 's."IdUsuarioResponsable" = :usuario'):
        raise ValueError("Filtro SNC no permitido")
    consulta = text(_CONSULTA_SNC.format(filtro=filtro))
    filas = db.execute(consulta, {
        "usuario": id_usuario, "limite": limite, "desplazamiento": desplazamiento,
    }).mappings().all()
    return [
        {
            **dict(fila),
            "id_usuario_responsable": (
                str(fila["id_usuario_responsable"]) if fila["id_usuario_responsable"] else None
            ),
            "asignacion_pendiente": fila["id_usuario_responsable"] is None,
        }
        for fila in filas
    ]


@router.get("/mis-registradas")
def mis_snc_registradas(
    limite: int = 50,
    desplazamiento: int = 0,
    db: Session = Depends(get_db),
    current: dict = Depends(get_current_user),
):
    _validar_acceso(db, current)
    if not 1 <= limite <= 100 or desplazamiento < 0:
        raise HTTPException(status_code=422, detail="Paginación inválida.")
    return _listar_snc_personales(
        db, 's."IdUsuarioCreador" = :usuario',
        _id_usuario_actual(current), limite, desplazamiento,
    )


@router.get("/mis-asignadas")
def mis_snc_asignadas(
    limite: int = 50,
    desplazamiento: int = 0,
    db: Session = Depends(get_db),
    current: dict = Depends(get_current_user),
):
    _validar_acceso(db, current)
    if not 1 <= limite <= 100 or desplazamiento < 0:
        raise HTTPException(status_code=422, detail="Paginación inválida.")
    return _listar_snc_personales(
        db, 's."IdUsuarioResponsable" = :usuario',
        _id_usuario_actual(current), limite, desplazamiento,
    )


# Fase 4: respuesta del responsable, exclusivamente sobre sus SNC asignadas.
class ResponderSNC(BaseModel):
    analisis_causa: str = Field(min_length=1, max_length=20000)
    plan_accion: str = Field(min_length=1, max_length=20000)

    @field_validator("analisis_causa", "plan_accion")
    @classmethod
    def validar_texto_respuesta(cls, valor: str) -> str:
        valor = valor.strip()
        if not valor:
            raise ValueError("Este campo es obligatorio.")
        return valor


@router.post("/{id_snc}/responder")
def responder_snc(
    id_snc: int,
    datos: ResponderSNC,
    db: Session = Depends(get_db),
    current: dict = Depends(get_current_user),
):
    _validar_acceso(db, current)
    id_usuario = _id_usuario_actual(current)
    if id_snc <= 0:
        raise HTTPException(status_code=422, detail="Número de SNC inválido.")

    try:
        # Bloqueo transaccional: evita dos respuestas simultáneas.
        snc = db.execute(text('''
            SELECT "IdUsuarioResponsable" AS responsable, "Estado" AS estado
            FROM public."SalidaNoConforme"
            WHERE "IdSalidaNoConforme" = :id
            FOR UPDATE
        '''), {"id": id_snc}).mappings().first()
        if snc is None:
            raise HTTPException(status_code=404, detail="La SNC no existe.")
        if snc["responsable"] != id_usuario:
            raise HTTPException(status_code=403, detail="Solo el responsable asignado puede responder esta SNC.")
        if snc["estado"] not in ("ABIERTO", "EN_GESTION"):
            raise HTTPException(status_code=409, detail="Esta SNC no admite una nueva respuesta en su estado actual.")

        # Aprovecha las tablas de gestión e historial existentes.
        db.execute(text('''
            INSERT INTO public."GestionSalidaNoConforme" (
                "IdSalidaNoConforme", "IdUsuarioGestion", "DescripcionGestion",
                "AccionCorrectiva", "Observaciones", "EstadoResultante",
                "FechaGestion", "Activo"
            ) VALUES (
                :id, :usuario, :causa, :plan, NULL, 'RESPONDIDO',
                CURRENT_TIMESTAMP, TRUE
            )
        '''), {
            "id": id_snc, "usuario": id_usuario,
            "causa": datos.analisis_causa, "plan": datos.plan_accion,
        })
        db.execute(text('''
            INSERT INTO public."HistorialSalidaNoConforme" (
                "IdSalidaNoConforme", "IdUsuarioAccion", "TipoAccion",
                "EstadoAnterior", "EstadoNuevo", "Observacion", "FechaAccion"
            ) VALUES (
                :id, :usuario, 'RESPUESTA', :anterior, 'RESPONDIDO',
                'El responsable registró análisis de causa y plan de acción',
                CURRENT_TIMESTAMP
            )
        '''), {
            "id": id_snc, "usuario": id_usuario, "anterior": snc["estado"],
        })
        db.execute(text('''
            UPDATE public."SalidaNoConforme"
            SET "Estado" = 'RESPONDIDO', "FechaActualizacion" = CURRENT_TIMESTAMP
            WHERE "IdSalidaNoConforme" = :id
        '''), {"id": id_snc})
        db.commit()
    except HTTPException:
        db.rollback()
        raise
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="No se pudo guardar la respuesta por una restricción de datos.") from exc
    except Exception:
        db.rollback()
        raise
    return {"id": id_snc, "estado": "RESPONDIDO", "mensaje": "Respuesta registrada correctamente."}


@router.get("/{id_snc}/respuesta")
def consultar_respuesta_snc(
    id_snc: int,
    db: Session = Depends(get_db),
    current: dict = Depends(get_current_user),
):
    _validar_acceso(db, current)
    id_usuario = _id_usuario_actual(current)
    snc = db.execute(text('''
        SELECT "IdUsuarioCreador" AS creador, "IdUsuarioResponsable" AS responsable
        FROM public."SalidaNoConforme"
        WHERE "IdSalidaNoConforme" = :id
    '''), {"id": id_snc}).mappings().first()
    if snc is None:
        raise HTTPException(status_code=404, detail="La SNC no existe.")
    if id_usuario not in (snc["creador"], snc["responsable"]):
        raise HTTPException(status_code=403, detail="No tiene acceso a esta SNC.")
    fila = db.execute(text('''
        SELECT "DescripcionGestion" AS analisis_causa,
               "AccionCorrectiva" AS plan_accion,
               "FechaGestion" AS fecha_respuesta
        FROM public."GestionSalidaNoConforme"
        WHERE "IdSalidaNoConforme" = :id AND "EstadoResultante" = 'RESPONDIDO'
              AND "Activo" = TRUE
        ORDER BY "FechaGestion" DESC, "IdGestionSalidaNoConforme" DESC
        LIMIT 1
    '''), {"id": id_snc}).mappings().first()
    return dict(fila) if fila else None


# Fase 5: cierre definitivo exclusivo del creador, después de la respuesta.
@router.post("/{id_snc}/cerrar")
def cerrar_snc(
    id_snc: int,
    db: Session = Depends(get_db),
    current: dict = Depends(get_current_user),
):
    _validar_acceso(db, current)
    id_usuario = _id_usuario_actual(current)
    if id_snc <= 0:
        raise HTTPException(status_code=422, detail="Número de SNC inválido.")

    try:
        # El bloqueo impide cierres concurrentes y conserva la trazabilidad.
        snc = db.execute(text('''
            SELECT "IdUsuarioCreador" AS creador, "Estado" AS estado
            FROM public."SalidaNoConforme"
            WHERE "IdSalidaNoConforme" = :id
            FOR UPDATE
        '''), {"id": id_snc}).mappings().first()

        if snc is None:
            raise HTTPException(status_code=404, detail="La SNC no existe.")
        if snc["creador"] != id_usuario:
            raise HTTPException(
                status_code=403,
                detail="Solo el usuario que creó la SNC puede realizar el cierre definitivo.",
            )
        if snc["estado"] != "RESPONDIDO":
            raise HTTPException(
                status_code=409,
                detail="Solo se puede cerrar una SNC que esté en estado RESPONDIDO.",
            )

        # Validar que exista la respuesta antes de permitir el cierre.
        respuesta = db.execute(text('''
            SELECT 1
            FROM public."GestionSalidaNoConforme"
            WHERE "IdSalidaNoConforme" = :id
              AND "EstadoResultante" = 'RESPONDIDO'
              AND "Activo" = TRUE
            LIMIT 1
        '''), {"id": id_snc}).scalar_one_or_none()
        if respuesta is None:
            raise HTTPException(
                status_code=409,
                detail="No se puede cerrar la SNC porque no tiene una respuesta registrada.",
            )

        db.execute(text('''
            UPDATE public."SalidaNoConforme"
            SET "Estado" = 'CERRADO',
                "FechaActualizacion" = CURRENT_TIMESTAMP
            WHERE "IdSalidaNoConforme" = :id
        '''), {"id": id_snc})

        db.execute(text('''
            INSERT INTO public."HistorialSalidaNoConforme" (
                "IdSalidaNoConforme", "IdUsuarioAccion", "TipoAccion",
                "EstadoAnterior", "EstadoNuevo", "Observacion", "FechaAccion"
            ) VALUES (
                :id, :usuario, 'CIERRE', 'RESPONDIDO', 'CERRADO',
                'El usuario creador realizó el cierre definitivo de la salida no conforme',
                CURRENT_TIMESTAMP
            )
        '''), {"id": id_snc, "usuario": id_usuario})

        db.commit()
    except HTTPException:
        db.rollback()
        raise
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail="No se pudo cerrar la SNC por una restricción de datos.",
        ) from exc
    except Exception:
        db.rollback()
        raise

    return {
        "id": id_snc,
        "estado": "CERRADO",
        "mensaje": "Salida no conforme cerrada correctamente.",
    }


# Fase SUPERADMIN: consultas globales de solo lectura. No modifica el flujo personal.
def _validar_superadmin(db: Session, current: dict) -> None:
    _validar_acceso(db, current)
    nombres = {
        "".join(c for c in unicodedata.normalize("NFKD", str(nombre).upper())
                if not unicodedata.combining(c)).replace(" ", "").replace("_", "").replace("-", "")
        for nombre in (current.get("roles") or [])
    }
    if "SUPERADMIN" not in nombres and "SUPERADMINISTRADOR" not in nombres:
        raise HTTPException(status_code=403, detail="Consulta exclusiva de SUPERADMIN.")


def _serializar_snc(fila):
    d = dict(fila)
    for k, v in d.items():
        if isinstance(v, UUID):
            d[k] = str(v)
    return d


# Fechas del historial: permiten medir etapas aun después del cierre.
_SNC_GENERAL_FROM = '''
    FROM public."SalidaNoConforme" s
    LEFT JOIN public."ProcesoSNC" p ON p."IdProcesoSNC" = s."IdProcesoSNC"
    LEFT JOIN public."AreaResponsableSNC" a ON a."IdAreaResponsableSNC" = s."IdAreaResponsableSNC"
    LEFT JOIN public."ResponsableSNC" r ON r."IdResponsableSNC" = s."IdResponsableSNC"
    LEFT JOIN public."Usuario" uc ON uc."IdUsuario" = s."IdUsuarioCreador"
    LEFT JOIN public."Usuario" ur ON ur."IdUsuario" = s."IdUsuarioResponsable"
    LEFT JOIN public."UsuarioAreaSNC" ua ON ua."IdUsuario" = s."IdUsuarioCreador" AND ua."Activo" = TRUE
    LEFT JOIN public."AreaResponsableSNC" ao ON ao."IdAreaResponsableSNC" = COALESCE(s."IdAreaOrigenSNC", ua."IdAreaResponsableSNC")
    LEFT JOIN LATERAL (
        SELECT MIN(h."FechaAccion") AS fecha_respuesta
        FROM public."HistorialSalidaNoConforme" h
        WHERE h."IdSalidaNoConforme" = s."IdSalidaNoConforme"
          AND h."TipoAccion" = 'RESPUESTA'
    ) hr ON TRUE
    LEFT JOIN LATERAL (
        SELECT MIN(h."FechaAccion") AS fecha_cierre
        FROM public."HistorialSalidaNoConforme" h
        WHERE h."IdSalidaNoConforme" = s."IdSalidaNoConforme"
          AND h."TipoAccion" = 'CIERRE'
    ) hc ON TRUE
'''

_SNC_GENERAL_SELECT = '''
    SELECT s."IdSalidaNoConforme" AS id,
           s."FechaSNC" AS fecha_snc, s."FechaCreacion" AS fecha_creacion,
           s."Estado" AS estado, s."Descripcion" AS descripcion,
           s."Impacto" AS impacto, p."NombreProceso" AS proceso,
           a."NombreArea" AS area_responsable,
           ao."NombreArea" AS area_origen,
           COALESCE(s."IdAreaOrigenSNC", ua."IdAreaResponsableSNC") AS id_area_origen_snc,
           (s."IdAreaOrigenSNC" IS NOT NULL) AS origen_historico_confirmado,
           s."IdAreaResponsableSNC" AS id_area_responsable_snc,
           r."NombreResponsable" AS responsable,
           uc."NombreUsuario" AS creado_por,
           ur."NombreUsuario" AS usuario_responsable,
           hr.fecha_respuesta, hc.fecha_cierre,
           ROUND((EXTRACT(EPOCH FROM (COALESCE(hr.fecha_respuesta, CURRENT_TIMESTAMP) - s."FechaCreacion")) / 86400.0)::numeric, 2) AS dias_hasta_respuesta,
           CASE WHEN hr.fecha_respuesta IS NULL THEN NULL ELSE
             ROUND((EXTRACT(EPOCH FROM (COALESCE(hc.fecha_cierre, CURRENT_TIMESTAMP) - hr.fecha_respuesta)) / 86400.0)::numeric, 2)
           END AS dias_hasta_cierre_desde_respuesta,
           CASE WHEN hc.fecha_cierre IS NULL THEN NULL ELSE
             ROUND((EXTRACT(EPOCH FROM (hc.fecha_cierre - s."FechaCreacion")) / 86400.0)::numeric, 2)
           END AS dias_totales_cierre
'''


def _filtros_generales(estado, busqueda, id_area, fecha_desde, fecha_hasta, tipo='TODAS'):
    partes = []
    parametros = {}
    if estado:
        if estado not in ('ABIERTO', 'RESPONDIDO', 'CERRADO'):
            raise HTTPException(status_code=422, detail="Estado SNC inválido.")
        partes.append('s."Estado" = :estado')
        parametros['estado'] = estado
    if busqueda and busqueda.strip():
        partes.append('''(CAST(s."IdSalidaNoConforme" AS TEXT) ILIKE :busqueda
                         OR uc."NombreUsuario" ILIKE :busqueda
                         OR ur."NombreUsuario" ILIKE :busqueda
                         OR r."NombreResponsable" ILIKE :busqueda)''')
        parametros['busqueda'] = '%' + busqueda.strip() + '%'
    if tipo not in ('TODAS', 'EMITIDAS', 'RECIBIDAS', 'INTERNAS'):
        raise HTTPException(status_code=422, detail='Tipo de relación SNC inválido.')
    origen = 'COALESCE(s."IdAreaOrigenSNC", ua."IdAreaResponsableSNC")'
    destino = 's."IdAreaResponsableSNC"'
    if id_area is not None:
        parametros['id_area'] = id_area
        if tipo == 'EMITIDAS':
            partes.append(f'({origen} = :id_area AND {destino} <> :id_area)')
        elif tipo == 'RECIBIDAS':
            partes.append(f'({destino} = :id_area AND {origen} IS DISTINCT FROM :id_area)')
        elif tipo == 'INTERNAS':
            partes.append(f'({origen} = :id_area AND {destino} = :id_area)')
        else:
            partes.append(f'({origen} = :id_area OR {destino} = :id_area)')
    elif tipo != 'TODAS':
        if tipo == 'EMITIDAS':
            partes.append(f'({origen} IS NOT NULL AND {origen} <> {destino})')
        elif tipo == 'RECIBIDAS':
            partes.append(f'({origen} IS DISTINCT FROM {destino})')
        else:
            partes.append(f'({origen} = {destino})')
    if fecha_desde:
        partes.append('s."FechaCreacion"::date >= :desde')
        parametros['desde'] = fecha_desde
    if fecha_hasta:
        partes.append('s."FechaCreacion"::date <= :hasta')
        parametros['hasta'] = fecha_hasta
    if fecha_desde and fecha_hasta and fecha_desde > fecha_hasta:
        raise HTTPException(status_code=422, detail="Rango de fechas inválido.")
    return (' WHERE ' + ' AND '.join(partes)) if partes else '', parametros


@router.get('/general')
def listar_snc_general(
    estado: str | None = None, busqueda: str | None = None,
    id_area: int | None = None, fecha_desde: date | None = None,
    fecha_hasta: date | None = None, pagina: int = 1,
    limite: int = 15, tipo: str = 'TODAS', db: Session = Depends(get_db),
    current: dict = Depends(get_current_user),
):
    _validar_superadmin(db, current)
    if pagina < 1 or limite < 1 or limite > 15:
        raise HTTPException(status_code=422, detail="Paginación inválida (máximo 15).")
    where, params = _filtros_generales(estado, busqueda, id_area, fecha_desde, fecha_hasta, tipo)
    total = db.execute(text('SELECT COUNT(*) ' + _SNC_GENERAL_FROM + where), params).scalar_one()
    filas = db.execute(text(_SNC_GENERAL_SELECT + _SNC_GENERAL_FROM + where +
        ' ORDER BY s."FechaCreacion" DESC, s."IdSalidaNoConforme" DESC LIMIT :limite OFFSET :offset'),
        {**params, 'limite': limite, 'offset': (pagina - 1) * limite}).mappings().all()
    return {'total': total, 'pagina': pagina, 'limite': limite,
            'paginas': max(1, (total + limite - 1) // limite),
            'registros': [_serializar_snc(f) for f in filas]}


@router.get('/general/indicadores')
def indicadores_snc_general(
    id_area: int | None = None, busqueda: str | None = None,
    fecha_desde: date | None = None, fecha_hasta: date | None = None,
    tipo: str = 'TODAS',
    db: Session = Depends(get_db), current: dict = Depends(get_current_user),
):
    # Totales únicos; relaciones por dirección.
    _validar_superadmin(db, current)
    where, params = _filtros_generales(None, busqueda, id_area, fecha_desde, fecha_hasta, tipo)
    base = _SNC_GENERAL_SELECT + _SNC_GENERAL_FROM + where
    filas = db.execute(text('''
        SELECT estado, area_responsable, COUNT(*) AS total,
               ROUND(AVG(dias_hasta_respuesta) FILTER (WHERE fecha_respuesta IS NOT NULL), 2) AS promedio_dias_respuesta,
               ROUND(AVG(dias_totales_cierre) FILTER (WHERE fecha_cierre IS NOT NULL), 2) AS promedio_dias_cierre
        FROM (''' + base + ''') datos
        GROUP BY estado, area_responsable ORDER BY area_responsable, estado
    '''), params).mappings().all()
    meses = db.execute(text('''
        SELECT TO_CHAR(DATE_TRUNC('month', fecha_creacion), 'YYYY-MM') AS mes,
               COUNT(*) AS total,
               COUNT(*) FILTER (WHERE estado = 'ABIERTO') AS abiertos,
               COUNT(*) FILTER (WHERE estado = 'RESPONDIDO') AS respondidos,
               COUNT(*) FILTER (WHERE estado = 'CERRADO') AS cerrados,
               COUNT(*) FILTER (WHERE id_area_origen_snc IS NOT NULL AND id_area_origen_snc <> id_area_responsable_snc AND (CAST(:area_scope AS BIGINT) IS NULL OR id_area_origen_snc = :area_scope)) AS emitidas,
               COUNT(*) FILTER (WHERE id_area_origen_snc IS DISTINCT FROM id_area_responsable_snc AND (CAST(:area_scope AS BIGINT) IS NULL OR id_area_responsable_snc = :area_scope)) AS recibidas,
               COUNT(*) FILTER (WHERE id_area_origen_snc = id_area_responsable_snc AND (CAST(:area_scope AS BIGINT) IS NULL OR id_area_origen_snc = :area_scope)) AS internas
        FROM (''' + base + ''') datos
        GROUP BY DATE_TRUNC('month', fecha_creacion)
        ORDER BY DATE_TRUNC('month', fecha_creacion)
    '''), {**params, 'area_scope': id_area}).mappings().all()
    resumen = db.execute(text('''
        SELECT COUNT(*) AS total,
               COUNT(*) FILTER (WHERE fecha_respuesta IS NOT NULL) AS con_respuesta,
               COUNT(*) FILTER (WHERE fecha_cierre IS NOT NULL) AS con_cierre,
               ROUND(AVG(dias_hasta_respuesta) FILTER (WHERE fecha_respuesta IS NOT NULL), 2) AS promedio_dias_respuesta,
               ROUND(AVG(dias_totales_cierre) FILTER (WHERE fecha_cierre IS NOT NULL), 2) AS promedio_dias_cierre,
               COUNT(*) FILTER (WHERE id_area_origen_snc IS NULL) AS origen_sin_parametrizar,
               COUNT(*) FILTER (WHERE id_area_origen_snc IS NOT NULL AND NOT origen_historico_confirmado) AS origen_inferido,
               COUNT(*) FILTER (WHERE id_area_origen_snc = id_area_responsable_snc) AS internas
        FROM (''' + base + ''') datos
    '''), params).mappings().one()
    # Desglose para el área seleccionada; no se cuentan internas como cruzadas.
    if id_area is not None:
        where_scope, scope_params = _filtros_generales(None, busqueda, id_area, fecha_desde, fecha_hasta, 'TODAS')
        scope_base = _SNC_GENERAL_SELECT + _SNC_GENERAL_FROM + where_scope
        desglose = db.execute(text('''
            SELECT COUNT(*) FILTER (WHERE id_area_origen_snc = :area AND id_area_responsable_snc <> :area) AS emitidas,
                   COUNT(*) FILTER (WHERE id_area_responsable_snc = :area AND id_area_origen_snc IS DISTINCT FROM :area) AS recibidas,
                   COUNT(*) FILTER (WHERE id_area_origen_snc = :area AND id_area_responsable_snc = :area) AS internas,
                   COUNT(*) FILTER (WHERE id_area_responsable_snc = :area AND id_area_origen_snc IS NULL) AS recibidas_sin_origen
            FROM (''' + scope_base + ''') datos
        '''), {**scope_params, 'area': id_area}).mappings().one()
    else:
        desglose = {'emitidas': None, 'recibidas': None, 'internas': None, 'recibidas_sin_origen': None}
    # Ranking global independiente del área seleccionada: cada relación externa aporta
    # una emisión al origen (si está parametrizado) y una recepción al destino.
    where_global, global_params = _filtros_generales(None, busqueda, None, fecha_desde, fecha_hasta)
    ranking_base = _SNC_GENERAL_SELECT + _SNC_GENERAL_FROM + where_global
    ranking = db.execute(text('''
        WITH datos AS (''' + ranking_base + '''), relaciones AS (
          SELECT area_origen AS area, 'EMITIDAS' AS tipo, estado
          FROM datos WHERE id_area_origen_snc IS NOT NULL AND id_area_origen_snc <> id_area_responsable_snc
          UNION ALL
          SELECT area_responsable AS area, 'RECIBIDAS' AS tipo, estado
          FROM datos WHERE id_area_origen_snc IS DISTINCT FROM id_area_responsable_snc
        )
        SELECT COALESCE(area, 'Origen sin parametrizar') AS area,
               COUNT(*) FILTER (WHERE tipo = 'EMITIDAS') AS emitidas,
               COUNT(*) FILTER (WHERE tipo = 'RECIBIDAS') AS recibidas,
               COUNT(*) FILTER (WHERE estado = 'ABIERTO') AS abiertas,
               COUNT(*) FILTER (WHERE estado = 'RESPONDIDO') AS respondidas,
               COUNT(*) FILTER (WHERE estado = 'CERRADO') AS cerradas
        FROM relaciones GROUP BY area ORDER BY COUNT(*) DESC, area
    '''), global_params).mappings().all()
    return {
        'grupos': [dict(f) for f in filas],
        'totales': {e: sum(f['total'] for f in filas if f['estado'] == e)
                    for e in ('ABIERTO', 'RESPONDIDO', 'CERRADO')},
        'mensual': [dict(f) for f in meses],
        'resumen': dict(resumen), 'desglose': dict(desglose),
        'ranking': [dict(f) for f in ranking],
    }


@router.get('/general/{id_snc}')
def detalle_snc_general(id_snc: int, db: Session = Depends(get_db),
                        current: dict = Depends(get_current_user)):
    _validar_superadmin(db, current)
    if id_snc <= 0:
        raise HTTPException(status_code=422, detail="Número SNC inválido.")
    fila = db.execute(text(_SNC_GENERAL_SELECT + _SNC_GENERAL_FROM +
        ' WHERE s."IdSalidaNoConforme" = :id'), {'id': id_snc}).mappings().first()
    if not fila:
        raise HTTPException(status_code=404, detail="La SNC no existe.")
    gestion = db.execute(text('''SELECT "DescripcionGestion" AS analisis_causa,
        "AccionCorrectiva" AS plan_accion, "Observaciones" AS observaciones,
        "FechaGestion" AS fecha_respuesta
        FROM public."GestionSalidaNoConforme"
        WHERE "IdSalidaNoConforme" = :id AND "EstadoResultante" = 'RESPONDIDO'
        AND "Activo" = TRUE ORDER BY "FechaGestion" DESC LIMIT 1'''), {'id': id_snc}).mappings().first()
    historial = db.execute(text('''SELECT "TipoAccion" AS tipo_accion,
        "EstadoAnterior" AS estado_anterior, "EstadoNuevo" AS estado_nuevo,
        "Observacion" AS observacion, "FechaAccion" AS fecha_accion
        FROM public."HistorialSalidaNoConforme"
        WHERE "IdSalidaNoConforme" = :id ORDER BY "FechaAccion", "IdHistorialSalidaNoConforme"'''),
        {'id': id_snc}).mappings().all()
    return {'snc': _serializar_snc(fila), 'respuesta': dict(gestion) if gestion else None,
            'historial': [dict(h) for h in historial]}
