"""Catálogos y gestión de Salidas No Conformes (SNC) para QA y producción."""

from datetime import date, datetime, timezone
from uuid import UUID
import unicodedata
import os
import logging
import smtplib
import ssl
from email.message import EmailMessage
from html import escape
from urllib.parse import urlparse
import uuid
import zipfile
from pathlib import Path

from fastapi import File, Form, UploadFile
from fastapi.responses import FileResponse

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from infrastructure.db.deps import get_db
from infrastructure.security.auth_dependencies import get_current_user


router = APIRouter(prefix="/api/salidas-no-conformes", tags=["Salidas No Conformes"])

_logger_snc = logging.getLogger(__name__)

def _enviar_aviso_snc(id_snc: int, destinatario: str, responsable: str, descripcion: str, fecha: str, ambiente: str) -> None:
    """Notifica después del commit. Un error SMTP nunca revierte la SNC."""
    prefijo = "SNC_MAIL_QA" if ambiente == "qa" else "SNC_MAIL_PROD"
    # Por defecto producción mantiene su SMTP exclusivo. Solo el administrador
    # puede autorizar explícitamente reutilizar el SMTP general en PROD.
    variable_compartido = (
        "SNC_QA_USAR_SMTP_COMPARTIDO" if ambiente == "qa"
        else "SNC_PROD_USAR_SMTP_COMPARTIDO"
    )
    permitir_smtp_compartido = os.getenv(
        variable_compartido, "true" if ambiente == "qa" else "false"
    ).strip().lower() in ("true", "1", "yes", "si")

    def configuracion(campo: str, compartido: str = "") -> str:
        valor = os.getenv(f"{prefijo}_{campo}", "").strip()
        if not valor and permitir_smtp_compartido and compartido:
            valor = os.getenv(compartido, "").strip()
        return valor

    servidor = configuracion("HOST", "SMTP_HOST")
    remitente = configuracion("FROM", "SMTP_FROM")
    usuario = configuracion("USER", "SMTP_USER")
    clave = configuracion("PASSWORD", "SMTP_PASSWORD")
    if not servidor or not remitente:
        faltantes = [campo for campo, valor in (("HOST", servidor), ("FROM", remitente)) if not valor]
        _logger_snc.warning(
            "SNC %s: correo NO enviado (%s). Faltan variables %s_%s. "
            "SMTP compartido habilitado: %s",
            id_snc, ambiente, prefijo, ", ".join(faltantes), permitir_smtp_compartido,
        )
        return
    if bool(usuario) != bool(clave):
        _logger_snc.error(
            "SNC %s: correo NO enviado (%s); SMTP USER/PASSWORD incompletos",
            id_snc, ambiente,
        )
        return
    if not destinatario or "@" not in destinatario or "\n" in destinatario or "\r" in destinatario:
        _logger_snc.error("SNC %s: correo NO enviado; destinatario inválido", id_snc)
        return
    try:
        puerto = int(configuracion("PORT", "SMTP_PORT") or "587")
        mensaje = EmailMessage()
        mensaje["From"] = remitente
        mensaje["To"] = destinatario
        mensaje["Subject"] = f"Nueva Salida No Conforme asignada - SNC N.º {id_snc}"
        # El destino del enlace depende del ambiente detectado desde la BD.
        # Se puede personalizar sin tocar el código mediante SNC_APP_URL_QA / PROD.
        url_predeterminada = (
            "https://qa.laperfeccion.app" if ambiente == "qa"
            else "https://laperfeccion.app"
        )
        variable_url = "SNC_APP_URL_QA" if ambiente == "qa" else "SNC_APP_URL_PROD"
        url_app = os.getenv(variable_url, "").strip().rstrip("/") or url_predeterminada
        url_partes = urlparse(url_app)
        if (
            url_partes.scheme != "https" or not url_partes.hostname
            or url_partes.username or url_partes.password
            or url_partes.query or url_partes.fragment
        ):
            _logger_snc.warning("SNC %s: URL de aplicativo inválida; se usa la predeterminada", id_snc)
            url_app = url_predeterminada

        # Enlaces del correo: abrir directamente el acceso corporativo.
        # Evita duplicar /login cuando la variable de entorno ya lo incluye.
        if urlparse(url_app).path.rstrip("/") != "/login":
            url_app = url_app.rstrip("/") + "/login"

        mensaje.set_content(
            f"Hola {responsable},\n\n"
            f"Se te ha asignado la Salida No Conforme N.º {id_snc}.\n"
            f"Fecha de la novedad: {fecha}\n"
            f"Descripción: {descripcion[:1500]}\n\n"
            "Para consultar y gestionar el caso, ingresa al aplicativo La Perfección "
            "y abre Salidas No Conformes > SNC asignadas.\n"
            f"Ingresar al aplicativo: {url_app}\n\n"
            "Este es un mensaje automático.\n"
        )
        nombre_html = escape(responsable)
        descripcion_html = escape(descripcion[:1500]).replace("\n", "<br>")
        fecha_html = escape(fecha)
        url_html = escape(url_app, quote=True)
        mensaje.add_alternative(f"""\
<!DOCTYPE html>
<html lang="es">
<head><meta charset="utf-8"></head>
<body style="margin:0;padding:24px;background:#f4f6f8;font-family:Arial,sans-serif;color:#263238;">
  <table role="presentation" cellpadding="0" cellspacing="0" style="max-width:620px;width:100%;margin:auto;background:#ffffff;border:1px solid #e2e7e9;border-radius:8px;">
    <tr><td style="padding:28px;">
      <h2 style="color:#087653;margin:0 0 8px;">Nueva Salida No Conforme asignada</h2>
      <p style="color:#607078;margin:0 0 24px;">SNC N.º {id_snc} · La Perfección</p>
      <p>Hola <strong>{nombre_html}</strong>,</p>
      <p>Se te ha asignado la Salida No Conforme N.º <strong>{id_snc}</strong>.</p>
      <p><strong>Fecha de la novedad:</strong> {fecha_html}</p>
      <p><strong>Descripción:</strong> {descripcion_html}</p>
      <p>Para consultar y gestionar el caso, ingresa al aplicativo y abre
      <strong>Salidas No Conformes &gt; SNC asignadas</strong>.</p>
      <p style="margin:28px 0;text-align:center;">
        <a href="{url_html}" style="background:#087653;color:#ffffff;text-decoration:none;padding:14px 24px;border-radius:5px;font-weight:bold;display:inline-block;">Ingresar al aplicativo</a>
      </p>
      <p style="font-size:12px;color:#65747b;">Si el botón no funciona, copia esta dirección en tu navegador:<br>
        <a href="{url_html}" style="color:#087653;">{url_html}</a>
      </p>
      <p style="font-size:12px;color:#65747b;margin-top:24px;">Este es un mensaje automático.</p>
    </td></tr>
  </table>
</body>
</html>""", subtype="html")
        contexto = ssl.create_default_context()
        if puerto == 465:
            with smtplib.SMTP_SSL(servidor, puerto, timeout=15, context=contexto) as smtp:
                if usuario and clave:
                    smtp.login(usuario, clave)
                smtp.send_message(mensaje)
        else:
            with smtplib.SMTP(servidor, puerto, timeout=15) as smtp:
                usar_tls = configuracion("USE_TLS", "SMTP_USE_TLS").lower()
                if usar_tls not in ("false", "0", "no"):
                    smtp.starttls(context=contexto)
                if usuario and clave:
                    smtp.login(usuario, clave)
                smtp.send_message(mensaje)
        _logger_snc.info(
            "SNC %s: servidor SMTP aceptó la notificación (%s); "
            "la entrega al buzón aún depende del proveedor",
            id_snc, ambiente,
        )
    except (smtplib.SMTPException, OSError, ValueError) as exc:
        # No imprimir la excepción completa: algunos proveedores incluyen
        # direcciones u otros datos en sus mensajes de error.
        _logger_snc.error(
            "SNC %s: fallo SMTP (%s), tipo=%s. Revisar configuración, "
            "autenticación, TLS, conectividad y registros del proveedor.",
            id_snc, ambiente, type(exc).__name__,
        )
    except Exception:
        _logger_snc.exception("SNC %s: error inesperado preparando la notificación", id_snc)



def _ambiente_snc(db: Session) -> str:
    """Determina el ambiente desde la BD real, sin depender del .env del servidor."""
    nombre_bd = db.execute(text("SELECT current_database()")).scalar_one()
    ambientes = {"LA_PERFECCION_QA": "qa", "la_perfeccion": "prod"}
    ambiente = ambientes.get(nombre_bd)
    if ambiente is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Módulo SNC no habilitado para esta base de datos.",
        )
    return ambiente


def _validar_acceso(db: Session, current: dict) -> None:
    """Acceso operativo SNC para usuarios autenticados y activos.

    Las restricciones por creador/responsable se aplican en cada operación.
    El panel general conserva su comprobación exclusiva de SUPERADMIN.
    """
    _ambiente_snc(db)
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
    """Lista responsables activos con su correo vinculado, conservando el orden Forms."""
    _validar_acceso(db, current)
    filas = db.execute(
        text('''
            SELECT r."IdResponsableSNC" AS id,
                   r."NombreResponsable" AS nombre,
                   r."IdUsuario" AS id_usuario,
                   r."IdCorreoSNC" AS id_correo_snc,
                   c."Correo" AS correo
            FROM public."ResponsableSNC" r
            LEFT JOIN public."CorreoSNC" c
                ON c."IdCorreoSNC" = r."IdCorreoSNC"
               AND c."Activo" = TRUE
            WHERE r."Activo" = TRUE
            ORDER BY r."OrdenVisualizacion" ASC
        ''')
    ).mappings().all()
    return [
        {
            "id": fila["id"],
            "nombre": fila["nombre"],
            "id_usuario": str(fila["id_usuario"]) if fila["id_usuario"] else None,
            "id_correo_snc": fila["id_correo_snc"] if fila["correo"] else None,
            "correo": fila["correo"],
        }
        for fila in filas
    ]


class CrearSNC(BaseModel):
    fecha_snc: date
    id_proceso_snc: int = Field(gt=0)
    descripcion: str = Field(min_length=1, max_length=20000)
    impacto: str | None = Field(default=None, max_length=20000)  # Compatibilidad con registros anteriores
    id_area_responsable_snc: int = Field(gt=0)
    id_responsable_snc: int = Field(gt=0)
    id_correo_remitente: int = Field(gt=0)
    id_correo_destinatario: int = Field(gt=0)

    @field_validator("descripcion")
    @classmethod
    def texto_no_vacio(cls, valor: str) -> str:
        valor = valor.strip()
        if not valor:
            raise ValueError("El texto no puede estar vacío.")
        return valor


@router.post("", status_code=status.HTTP_201_CREATED)
def registrar_snc(
    datos: CrearSNC,
    background_tasks: BackgroundTasks,
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
            SELECT r."IdUsuario" AS id_usuario,
                   r."NombreResponsable" AS nombre_responsable,
                   c."Correo" AS correo_responsable
            FROM public."ResponsableSNC" r
            LEFT JOIN public."CorreoSNC" c
              ON c."IdCorreoSNC" = r."IdCorreoSNC"
             AND c."Activo" = TRUE
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
    ambiente_notificacion = _ambiente_snc(db)

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
                'impacto': (datos.impacto or '').strip(),  # Columna histórica conservada; formulario ya no la solicita
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

    # La dirección procede de la relación vigente ResponsableSNC -> CorreoSNC,
    # no de un correo arbitrario enviado por el navegador.
    if responsable["correo_responsable"]:
        background_tasks.add_task(
            _enviar_aviso_snc, id_snc, responsable["correo_responsable"],
            responsable["nombre_responsable"], datos.descripcion,
            datos.fecha_snc.isoformat(), ambiente_notificacion,
        )
    else:
        _logger_snc.warning(
            "SNC %s: aviso NO programado; responsable %s sin correo activo vinculado "
            "(el correo destinatario seleccionado en el formulario no se usa "
            "para el aviso de asignación)",
            id_snc, datos.id_responsable_snc,
        )

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


# -----------------------------------------------------------------------------
# EVIDENCIAS SNC. No modifica el mecanismo documental de Retiros.
# El frontend debe llamar a /{id_snc}/responder-con-evidencias usando FormData.
# -----------------------------------------------------------------------------
_EXT_SNC = {
    ".pdf": "application/pdf", ".png": "image/png", ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg", ".webp": "image/webp",
    ".doc": "application/msword",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".xls": "application/vnd.ms-excel",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".csv": "text/csv", ".mp3": "audio/mpeg", ".wav": "audio/wav",
    ".m4a": "audio/mp4", ".ogg": "audio/ogg", ".mp4": "video/mp4",
    ".mov": "video/quicktime", ".webm": "video/webm",
}
_MAX_ARCHIVOS_SNC = 5
_MAX_DOCUMENTO_SNC = 20 * 1024 * 1024
_MAX_VIDEO_SNC = 100 * 1024 * 1024
_MAX_TOTAL_SNC = 150 * 1024 * 1024


def _storage_snc(db: Session) -> Path:
    """Separa físicamente evidencias QA y PROD según la BD conectada.

    SNC_STORAGE_ROOT conserva compatibilidad con la configuración local de QA.
    En producción solo se utiliza SNC_STORAGE_ROOT_PROD (o la ruta PROD).
    """
    ambiente = _ambiente_snc(db)
    if ambiente == "prod":
        configuracion = os.environ.get("SNC_STORAGE_ROOT_PROD")
        predeterminada = "C:/LaPerfeccionStorage/calidad/prod/snc"
    else:
        configuracion = os.environ.get("SNC_STORAGE_ROOT_QA") or os.environ.get("SNC_STORAGE_ROOT")
        predeterminada = "C:/LaPerfeccionStorage/calidad/qa/snc"
    raiz = Path(configuracion or predeterminada).expanduser().resolve()
    # Impide usar por error la carpeta de un ambiente en el otro.
    otra = Path("C:/LaPerfeccionStorage/calidad/qa/snc" if ambiente == "prod"
                else "C:/LaPerfeccionStorage/calidad/prod/snc").resolve()
    if raiz == otra:
        raise HTTPException(503, "La carpeta SNC configurada corresponde al otro ambiente.")
    return raiz


def _comprobar_cabecera_snc(extension: str, cabecera: bytes) -> bool:
    # Validación de firmas básicas; debe complementarse con análisis antivirus
    # en el servidor antes de habilitar archivos de terceros en producción.
    if extension == ".pdf":
        return cabecera.startswith(b"%PDF-")
    if extension == ".png":
        return cabecera.startswith(b"\x89PNG\r\n\x1a\n")
    if extension in (".jpg", ".jpeg"):
        return cabecera.startswith(b"\xff\xd8\xff")
    if extension == ".webp":
        return cabecera[:4] == b"RIFF" and cabecera[8:12] == b"WEBP"
    if extension in (".docx", ".xlsx"):
        return cabecera.startswith(b"PK\x03\x04")
    if extension in (".doc", ".xls"):
        return cabecera.startswith(bytes.fromhex("D0CF11E0A1B11AE1"))
    if extension == ".wav":
        return cabecera[:4] == b"RIFF" and cabecera[8:12] == b"WAVE"
    if extension == ".mp3":
        return cabecera.startswith(b"ID3") or (len(cabecera) > 1 and cabecera[0] == 255 and (cabecera[1] & 224) == 224)
    if extension in (".mp4", ".mov", ".m4a"):
        return cabecera[4:8] == b"ftyp"
    if extension in (".ogg",):
        return cabecera.startswith(b"OggS")
    if extension == ".webm":
        return cabecera.startswith(bytes.fromhex("1A45DFA3"))
    if extension == ".csv":
        return b"\x00" not in cabecera
    return False


async def _guardar_temporal_snc(archivo: UploadFile, carpeta: Path):
    nombre_original = Path((archivo.filename or "").replace("\\", "/")).name
    extension = Path(nombre_original).suffix.lower()
    if not nombre_original or extension not in _EXT_SNC:
        raise HTTPException(422, "Formato no permitido para evidencia SNC.")
    limite = _MAX_VIDEO_SNC if extension in (".mp4", ".mov", ".webm") else _MAX_DOCUMENTO_SNC
    carpeta.mkdir(parents=True, exist_ok=True)
    nombre_interno = uuid.uuid4().hex + extension
    ruta = carpeta / nombre_interno
    tamano = 0
    cabecera = b""
    try:
        with ruta.open("xb") as salida:
            while True:
                bloque = await archivo.read(1024 * 1024)
                if not bloque:
                    break
                if len(cabecera) < 32:
                    cabecera += bloque[:32 - len(cabecera)]
                tamano += len(bloque)
                if tamano > limite:
                    raise HTTPException(413, f"El archivo excede el límite de {limite // (1024*1024)} MB.")
                salida.write(bloque)
        if not tamano or not _comprobar_cabecera_snc(extension, cabecera):
            raise HTTPException(422, f"El archivo {nombre_original} está vacío o su formato no coincide.")
        if extension in (".docx", ".xlsx"):
            try:
                with zipfile.ZipFile(ruta) as z:
                    nombres = set(z.namelist())
                    esperado = "word/document.xml" if extension == ".docx" else "xl/workbook.xml"
                    if esperado not in nombres:
                        raise HTTPException(422, "Documento Office no válido.")
            except (zipfile.BadZipFile, OSError) as exc:
                raise HTTPException(422, "Documento Office dañado.") from exc
        return {
            "nombre_original": nombre_original[:255], "nombre_almacenado": nombre_interno,
            "ruta": ruta, "tipo_mime": _EXT_SNC[extension], "tamano": tamano,
        }
    except BaseException:
        ruta.unlink(missing_ok=True)
        raise
    finally:
        await archivo.close()


def _autorizar_evidencia_snc(db: Session, current: dict, id_snc: int):
    _validar_acceso(db, current)
    usuario = _id_usuario_actual(current)
    snc = db.execute(text('''
        SELECT "IdUsuarioCreador" AS creador, "IdUsuarioResponsable" AS responsable
        FROM public."SalidaNoConforme" WHERE "IdSalidaNoConforme" = :id
    '''), {"id": id_snc}).mappings().first()
    if snc is None:
        raise HTTPException(404, "SNC no encontrada.")
    nombres = {
        "".join(c for c in unicodedata.normalize("NFKD", str(n).upper())
                if not unicodedata.combining(c)).replace(" ", "").replace("_", "").replace("-", "")
        for n in (current.get("roles") or [])
    }
    admin = "SUPERADMIN" in nombres or "SUPERADMINISTRADOR" in nombres
    if usuario not in (snc["creador"], snc["responsable"]) and not admin:
        raise HTTPException(403, "No tiene permiso para consultar evidencias de esta SNC.")
    return usuario


@router.post("/{id_snc}/responder-con-evidencias", status_code=200)
async def responder_snc_con_evidencias(
    id_snc: int,
    analisis_causa: str = Form(...),
    plan_accion: str = Form(...),
    archivos: list[UploadFile] | None = File(None),
    db: Session = Depends(get_db),
    current: dict = Depends(get_current_user),
):
    _validar_acceso(db, current)
    usuario = _id_usuario_actual(current)
    if id_snc <= 0:
        raise HTTPException(422, "Número de SNC inválido.")
    # Validación explícita para el formulario multipart.
    if not analisis_causa.strip() or not plan_accion.strip():
        raise HTTPException(422, "Análisis de causa y plan de acción son obligatorios.")
    if len(analisis_causa) > 20000 or len(plan_accion) > 20000:
        raise HTTPException(422, "El texto supera el máximo de 20.000 caracteres.")
    datos = ResponderSNC(analisis_causa=analisis_causa, plan_accion=plan_accion)
    # Verificación previa para evitar subir archivos de SNC ajenas.
    previa = db.execute(text('''
        SELECT "IdUsuarioResponsable" AS responsable, "Estado" AS estado
        FROM public."SalidaNoConforme" WHERE "IdSalidaNoConforme" = :id
    '''), {"id": id_snc}).mappings().first()
    if not previa:
        raise HTTPException(404, "La SNC no existe.")
    if previa["responsable"] != usuario:
        raise HTTPException(403, "Solo el responsable asignado puede responder.")
    if previa["estado"] not in ("ABIERTO", "EN_GESTION"):
        raise HTTPException(409, "La SNC no admite respuestas en su estado actual.")
    archivos = archivos or []
    if len(archivos) > _MAX_ARCHIVOS_SNC:
        raise HTTPException(422, f"Máximo {_MAX_ARCHIVOS_SNC} evidencias por respuesta.")
    carpeta = _storage_snc(db) / str(id_snc)
    guardados = []
    try:
        # Primero validar y escribir archivos, sin cambiar aún el estado de SNC.
        total = 0
        for archivo in archivos:
            meta = await _guardar_temporal_snc(archivo, carpeta)
            guardados.append(meta)
            total += meta["tamano"]
            if total > _MAX_TOTAL_SNC:
                raise HTTPException(413, "Las evidencias superan 150 MB en total.")
        snc = db.execute(text('''
            SELECT "IdUsuarioResponsable" AS responsable, "Estado" AS estado
            FROM public."SalidaNoConforme"
            WHERE "IdSalidaNoConforme" = :id FOR UPDATE
        '''), {"id": id_snc}).mappings().first()
        if not snc:
            raise HTTPException(404, "La SNC no existe.")
        if snc["responsable"] != usuario:
            raise HTTPException(403, "Solo el responsable asignado puede responder.")
        if snc["estado"] not in ("ABIERTO", "EN_GESTION"):
            raise HTTPException(409, "La SNC no admite respuestas en su estado actual.")
        id_gestion = db.execute(text('''
            INSERT INTO public."GestionSalidaNoConforme" (
                "IdSalidaNoConforme", "IdUsuarioGestion", "DescripcionGestion",
                "AccionCorrectiva", "Observaciones", "EstadoResultante", "FechaGestion", "Activo"
            ) VALUES (:id, :usuario, :causa, :plan, NULL, 'RESPONDIDO', CURRENT_TIMESTAMP, TRUE)
            RETURNING "IdGestionSalidaNoConforme"
        '''), {"id": id_snc, "usuario": usuario,
               "causa": datos.analisis_causa, "plan": datos.plan_accion}).scalar_one()
        for meta in guardados:
            db.execute(text('''
                INSERT INTO public."GestionSalidaNoConformeAdjunto" (
                    "IdGestionSalidaNoConforme", "NombreOriginal", "NombreAlmacenado",
                    "RutaArchivo", "TipoMime", "TamanoBytes", "IdUsuarioCarga", "Activo"
                ) VALUES (:gestion, :original, :interno, :ruta, :mime, :tamano, :usuario, TRUE)
            '''), {"gestion": id_gestion, "original": meta["nombre_original"],
                   "interno": meta["nombre_almacenado"],
                   "ruta": str(meta["ruta"]), "mime": meta["tipo_mime"],
                   "tamano": meta["tamano"], "usuario": usuario})
        db.execute(text('''
            INSERT INTO public."HistorialSalidaNoConforme" (
                "IdSalidaNoConforme", "IdUsuarioAccion", "TipoAccion",
                "EstadoAnterior", "EstadoNuevo", "Observacion", "FechaAccion"
            ) VALUES (:id, :usuario, 'RESPUESTA', :anterior, 'RESPONDIDO',
                'El responsable registró análisis de causa, plan de acción y evidencias', CURRENT_TIMESTAMP)
        '''), {"id": id_snc, "usuario": usuario, "anterior": snc["estado"]})
        db.execute(text('''
            UPDATE public."SalidaNoConforme"
            SET "Estado" = 'RESPONDIDO', "FechaActualizacion" = CURRENT_TIMESTAMP
            WHERE "IdSalidaNoConforme" = :id
        '''), {"id": id_snc})
        db.commit()
        return {"id": id_snc, "id_gestion": id_gestion, "estado": "RESPONDIDO",
                "evidencias": len(guardados), "mensaje": "Respuesta y evidencias registradas correctamente."}
    except BaseException:
        db.rollback()
        for meta in guardados:
            meta["ruta"].unlink(missing_ok=True)
        raise


@router.get("/{id_snc}/evidencias")
def listar_evidencias_snc(
    id_snc: int, db: Session = Depends(get_db),
    current: dict = Depends(get_current_user),
):
    _autorizar_evidencia_snc(db, current, id_snc)
    filas = db.execute(text('''
        SELECT a."IdAdjuntoSNC" AS id, a."NombreOriginal" AS nombre,
               a."TipoMime" AS tipo_mime, a."TamanoBytes" AS tamano_bytes,
               a."FechaCreacion" AS fecha_creacion
        FROM public."GestionSalidaNoConformeAdjunto" a
        INNER JOIN public."GestionSalidaNoConforme" g
          ON g."IdGestionSalidaNoConforme" = a."IdGestionSalidaNoConforme"
        WHERE g."IdSalidaNoConforme" = :id AND a."Activo" = TRUE
        ORDER BY a."IdAdjuntoSNC"
    '''), {"id": id_snc}).mappings().all()
    return [dict(fila) for fila in filas]


@router.get("/evidencias/{id_adjunto}/descargar")
def descargar_evidencia_snc(
    id_adjunto: int, db: Session = Depends(get_db),
    current: dict = Depends(get_current_user),
):
    _validar_acceso(db, current)
    fila = db.execute(text('''
        SELECT a."IdAdjuntoSNC" AS id, a."NombreOriginal" AS nombre,
               a."NombreAlmacenado" AS interno, a."RutaArchivo" AS ruta,
               g."IdSalidaNoConforme" AS id_snc
        FROM public."GestionSalidaNoConformeAdjunto" a
        INNER JOIN public."GestionSalidaNoConforme" g
          ON g."IdGestionSalidaNoConforme" = a."IdGestionSalidaNoConforme"
        WHERE a."IdAdjuntoSNC" = :id AND a."Activo" = TRUE
    '''), {"id": id_adjunto}).mappings().first()
    if not fila:
        raise HTTPException(404, "Evidencia no encontrada.")
    _autorizar_evidencia_snc(db, current, fila["id_snc"])
    raiz = _storage_snc(db)
    # Se reconstruye la ruta desde IDs internos, nunca desde una ruta solicitada
    # por el cliente o una ruta arbitraria de base de datos.
    ruta = (raiz / str(fila["id_snc"]) / fila["interno"]).resolve()
    if ruta.parent != (raiz / str(fila["id_snc"])).resolve():
        raise HTTPException(403, "Ruta de archivo no permitida.")
    if not ruta.is_file():
        raise HTTPException(404, "El archivo físico no está disponible.")
    return FileResponse(
        path=str(ruta), media_type="application/octet-stream",
        filename=fila["nombre"], content_disposition_type="attachment",
        headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"},
    )
