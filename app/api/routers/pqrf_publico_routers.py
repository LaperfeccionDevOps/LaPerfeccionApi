"""Registro público PQRF - fase QA. No modifica el router interno.

IMPORTANTE: No exponer a Internet sin rate limiting/CAPTCHA en el perímetro.
El correo se encola en NotificacionPQRF; este módulo NO envía SMTP.
"""
import logging
import os
import re
from datetime import date
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from infrastructure.db.deps import get_db

router = APIRouter(prefix="/api/pqrf-publico", tags=["PQRF Público (QA)"])
logger = logging.getLogger(__name__)

# Parámetros del proceso de Calidad, no se reciben del navegador.
_PROCESO_CALIDAD = 10
_CORREO_CALIDAD = 15
_EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")


def _validar_qa(db: Session) -> UUID:
    """Bloquea cualquier base distinta de QA y exige habilitación explícita."""
    nombre_bd = db.execute(text("SELECT current_database()")).scalar_one()
    if nombre_bd != "LA_PERFECCION_QA":
        raise HTTPException(status_code=503, detail="Portal público aún no habilitado para esta base de datos.")
    if os.getenv("PQRF_PUBLICO_HABILITADO", "").strip().lower() != "true":
        raise HTTPException(status_code=503, detail="Portal público deshabilitado en QA.")
    valor = os.getenv("PQRF_PUBLICO_REGISTRADOR_ID", "").strip()
    try:
        return UUID(valor)
    except (ValueError, AttributeError):
        raise HTTPException(status_code=503, detail="Falta configurar el registrador técnico de QA.")


class NuevaPQRFPublica(BaseModel):
    fecha_pqrf: date
    id_tipo_pqrf: int = Field(gt=0)
    nombre_remitente: str = Field(min_length=2, max_length=200)
    nombre_cliente_externo: str = Field(min_length=2, max_length=250)
    correo_respuesta_cliente: str = Field(min_length=5, max_length=180)
    descripcion_pqrf: str = Field(min_length=10, max_length=20000)
    sitio_web: str = Field(default="", max_length=100)  # Honeypot, debe quedar vacío.

    @field_validator("nombre_remitente", "nombre_cliente_externo", "correo_respuesta_cliente", "descripcion_pqrf")
    @classmethod
    def limpiar(cls, valor: str) -> str:
        valor = valor.strip()
        if not valor:
            raise ValueError("El campo es obligatorio.")
        return valor

    @field_validator("correo_respuesta_cliente")
    @classmethod
    def validar_correo(cls, valor: str) -> str:
        if not _EMAIL_RE.fullmatch(valor):
            raise ValueError("Correo electrónico inválido.")
        return valor


@router.get("/tipos")
def consultar_tipos_publicos(db: Session = Depends(get_db)):
    _validar_qa(db)
    filas = db.execute(text('''
        SELECT "IdTipoPQRF" AS id, "NombreTipo" AS nombre
        FROM public."TipoPQRF" WHERE "Activo" = TRUE
        ORDER BY "IdTipoPQRF"
    ''')).mappings().all()
    return [dict(fila) for fila in filas]


@router.post("/registrar", status_code=status.HTTP_201_CREATED)
def registrar_pqrf_publica(datos: NuevaPQRFPublica, db: Session = Depends(get_db)):
    registrador_id = _validar_qa(db)
    if datos.sitio_web.strip():
        raise HTTPException(status_code=422, detail="No fue posible validar la solicitud.")
    if datos.fecha_pqrf > date.today():
        raise HTTPException(status_code=422, detail="La fecha de PQRF no puede ser futura.")

    tipo_activo = db.execute(text('''
        SELECT 1 FROM public."TipoPQRF"
        WHERE "IdTipoPQRF" = :id AND "Activo" = TRUE
    '''), {"id": datos.id_tipo_pqrf}).scalar_one_or_none()
    if tipo_activo is None:
        raise HTTPException(status_code=422, detail="El tipo de PQRF no existe o está inactivo.")
    nombre_tipo = db.execute(text('''
        SELECT "NombreTipo" FROM public."TipoPQRF"
        WHERE "IdTipoPQRF" = :id AND "Activo" = TRUE
    '''), {"id": datos.id_tipo_pqrf}).scalar_one()

    # Validar la parametrización de Calidad en la propia base de QA.
    configuracion = db.execute(text('''
        SELECT p."IdCorreoPQRF" AS id_correo,
               c."Correo" AS correo_calidad,
               r."IdUsuarioResponsable" AS responsable
        FROM public."ProcesoPQRF" p
        JOIN public."CorreoPQRF" c ON c."IdCorreoPQRF" = p."IdCorreoPQRF"
        JOIN public."ResponsableProcesoPQRF" r ON r."IdProcesoPQRF" = p."IdProcesoPQRF"
        JOIN public."Usuario" u ON u."IdUsuario" = r."IdUsuarioResponsable"
        WHERE p."IdProcesoPQRF" = :proceso
          AND p."IdCorreoPQRF" = :correo
          AND p."Activo" = TRUE AND c."Activo" = TRUE
          AND UPPER(TRIM(COALESCE(u."HashEstado", ''))) = 'ACTIVO'
        LIMIT 1
    '''), {"proceso": _PROCESO_CALIDAD, "correo": _CORREO_CALIDAD}).mappings().first()
    if not configuracion or not _EMAIL_RE.fullmatch(configuracion["correo_calidad"] or ""):
        raise HTTPException(status_code=503, detail="Calidad no tiene una configuración activa para recibir PQRF.")

    # Solo QA: redirigir la notificación al buzón de pruebas configurado.
    # Se mantiene IdCorreoPQRF=15 y la asignación al responsable de Calidad.
    correo_pruebas = os.getenv("PQRF_PUBLICO_CORREO_PRUEBAS_QA", "").strip()
    if not correo_pruebas or not _EMAIL_RE.fullmatch(correo_pruebas):
        raise HTTPException(status_code=503, detail="Configure un correo de pruebas válido para PQRF público QA.")

    registrador_activo = db.execute(text('''
        SELECT 1 FROM public."Usuario"
        WHERE "IdUsuario" = :id
          AND UPPER(TRIM(COALESCE("HashEstado", ''))) = 'ACTIVO'
    '''), {"id": registrador_id}).scalar_one_or_none()
    if registrador_activo is None:
        raise HTTPException(status_code=503, detail="Registrador técnico de QA no disponible.")

    try:
        id_pqrf = db.execute(text('''
            INSERT INTO public."PQRF" (
                "FechaPQRF", "IdTipoPQRF", "CorreoRemitente",
                "CorreoRespuestaCliente", "NombreRemitente", "IdCliente",
                "NombreClienteExterno", "DescripcionPQRF", "IdProcesoPQRF",
                "IdCorreoPQRF", "IdUsuarioRegistro", "IdUsuarioResponsable",
                "Estado", "OrigenPQRF"
            ) VALUES (
                :fecha, :tipo, :correo_cliente, :correo_cliente, :nombre, NULL,
                :cliente, :descripcion, :proceso, :correo_calidad,
                :registrador, :responsable, 'ABIERTA', 'EXTERNA'
            ) RETURNING "IdPQRF"
        '''), {
            "fecha": datos.fecha_pqrf,
            "tipo": datos.id_tipo_pqrf,
            "correo_cliente": datos.correo_respuesta_cliente,
            "nombre": datos.nombre_remitente,
            "cliente": datos.nombre_cliente_externo,
            "descripcion": datos.descripcion_pqrf,
            "proceso": _PROCESO_CALIDAD,
            "correo_calidad": _CORREO_CALIDAD,
            "registrador": registrador_id,
            "responsable": configuracion["responsable"],
        }).scalar_one()

        db.execute(text('''
            INSERT INTO public."HistorialPQRF" (
                "IdPQRF", "IdUsuario", "TipoMovimiento", "EstadoAnterior",
                "EstadoNuevo", "Observacion"
            ) VALUES (
                :id, :registrador, 'CREACION', NULL, 'ABIERTA',
                'Registro externo desde portal público; remitido a Calidad'
            )
        '''), {"id": id_pqrf, "registrador": registrador_id})

        db.execute(text('''
            INSERT INTO public."NotificacionPQRF" (
                "IdPQRF", "TipoNotificacion", "CorreoDestino", "Asunto", "Cuerpo"
            ) VALUES (
                :id, 'NUEVA_PQRF_EXTERNA', :destino, :asunto, :cuerpo
            )
        '''), {
            "id": id_pqrf,
            "destino": correo_pruebas,
            "asunto": f"[PQRF N.º {id_pqrf}] Nueva solicitud externa para Calidad",
            "cuerpo": (
                "ASEOS LA PERFECCIÓN\n"
                "NUEVA PQRF REGISTRADA\n"
                "Notificación automática al área de Calidad\n\n"
                "Estimado equipo de Calidad:\n\n"
                "Se ha registrado una nueva solicitud a través del portal público "
                "de Aseos La Perfección. A continuación encontrará la información "
                "necesaria para iniciar su gestión.\n\n"
                f"Número de radicado: {id_pqrf}\n"
                f"Fecha de registro: {datos.fecha_pqrf.strftime('%d/%m/%Y')}\n"
                f"Tipo de solicitud: {nombre_tipo}\n"
                f"Cliente o sede: {datos.nombre_cliente_externo}\n"
                f"Nombre del remitente: {datos.nombre_remitente}\n"
                f"Correo para respuesta: {datos.correo_respuesta_cliente}\n"
                "Estado: ABIERTA\n\n"
                "DESCRIPCIÓN DE LA SOLICITUD\n"
                f"{datos.descripcion_pqrf}\n\n"
                "ACCIÓN REQUERIDA\n"
                "Ingrese al aplicativo interno de Aseos La Perfección, "
                "consulte el radicado y registre la gestión correspondiente.\n\n"
                "Este es un mensaje automático del Sistema de Gestión PQRF. "
                "Por favor, gestione la respuesta desde el aplicativo."
            ),
        })
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        logger.warning("Registro PQRF pública rechazado por restricción de BD: %s", type(exc).__name__)
        raise HTTPException(status_code=409, detail="No fue posible registrar la PQRF.") from exc
    except Exception:
        db.rollback()
        logger.exception("Error al registrar PQRF externa en QA")
        raise

    return {
        "id": id_pqrf,
        "radicado": str(id_pqrf),
        "estado": "ABIERTA",
        "mensaje": "PQRF registrada correctamente. Conserve su número de radicado.",
        "notificacion": "PENDIENTE",
    }
