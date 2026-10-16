"""Catálogos de Salidas No Conformes (SNC).

Fases 1 a 3: catálogos, registro y consultas personales de SNC en QA.
"""

from datetime import date
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from infrastructure.db.deps import get_db
from infrastructure.security.auth_dependencies import get_current_user


router = APIRouter(prefix="/api/salidas-no-conformes", tags=["Salidas No Conformes"])


def _verificar_base_qa(db: Session) -> None:
    """Impide consultar estos endpoints fuera de la BD QA durante desarrollo."""
    nombre_bd = db.execute(text("SELECT current_database()")).scalar_one()
    if nombre_bd != "LA_PERFECCION_QA":
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Módulo SNC en desarrollo: conexión distinta de LA_PERFECCION_QA.",
        )


def _usuario_autorizado(current: dict) -> None:
    """Fase piloto: acceso limitado a roles operativos previstos y globales."""
    roles = set(current.get("roles_ids") or [])
    roles = {int(rol) for rol in roles}
    roles_permitidos = {1, 2, 3, 5, 6, 13, 15}
    if not roles.intersection(roles_permitidos):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No tienes permisos para consultar los catálogos SNC.",
        )


def _validar_acceso(db: Session, current: dict) -> None:
    _verificar_base_qa(db)
    _usuario_autorizado(current)
    usuario = current["usuario"]
    if (usuario.HashEstado or "").strip().upper() != "ACTIVO":
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
    # Registra una SNC y su historial en una transacción; solo en QA.
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

    try:
        id_snc = db.execute(
            text('''
                INSERT INTO public."SalidaNoConforme" (
                    "FechaSNC", "IdUsuarioCreador", "IdProcesoSNC",
                    "Descripcion", "Impacto", "IdAreaResponsableSNC",
                    "IdResponsableSNC", "IdUsuarioResponsable",
                    "IdCorreoRemitente", "IdCorreoDestinatario", "Estado"
                ) VALUES (
                    :fecha, :creador, :proceso, :descripcion, :impacto, :area,
                    :responsable, :usuario_responsable, :remitente, :destinatario, 'ABIERTO'
                ) RETURNING "IdSalidaNoConforme"
            '''),
            {
                'fecha': datos.fecha_snc,
                'creador': id_creador,
                'proceso': datos.id_proceso_snc,
                'descripcion': datos.descripcion,
                'impacto': datos.impacto,
                'area': datos.id_area_responsable_snc,
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
        'mensaje': 'SNC registrada correctamente en QA.',
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
    return {"id": id_snc, "estado": "RESPONDIDO", "mensaje": "Respuesta registrada correctamente en QA."}


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
        "mensaje": "Salida no conforme cerrada correctamente en QA.",
    }
