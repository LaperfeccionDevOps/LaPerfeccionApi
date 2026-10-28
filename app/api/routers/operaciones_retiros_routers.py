# ruff: noqa: B008, BLE001

import json
import os
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    UploadFile,
    status,
)
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.orm import Session

from infrastructure.db.deps import get_db
from infrastructure.security.auth_dependencies import get_current_user
from services.paz_salvo_operaciones_pdf_service import (
    generar_paz_salvo_operaciones_pdf,
    _obtener_requisitos_perfil_pdf,
)


router = APIRouter(
    prefix="/api/operaciones/retiros",
    tags=["Operaciones - Retiros"],
)


STORAGE_BASE_DIR = Path("C:/LaPerfeccionStorage/rrll/retiros")
ID_TIPO_DOCUMENTO_PAZ_Y_SALVO = 2
ID_ESTADO_CONTRATADO = 25
ID_ESTADO_RETIRO_ABIERTO = 30
TAMANO_MAXIMO_PDF = 10 * 1024 * 1024
TAMANO_MAXIMO_EVIDENCIA = 10 * 1024 * 1024

TIPOS_EVIDENCIA_PAZ_SALVO = {
    "NOVEDADES_NOMINA",
    "FORMATO_DESCUENTO_VACUNAS",
    "CARNET_ACCESO",
    "LISTADO_HERRAMIENTAS",
    "PLANILLA_NOMINA",
}

TAMANO_MAXIMO_ADJUNTO_RQ = 10 * 1024 * 1024

TIPOS_NOTIFICACION_RQ = {
    "RENUNCIA FORMAL",
    "RENUNCIA INFORMADA",
    "ABANDONO",
    "NUNCA INGRESO",
    "TERMINACION DE CONTRATO",
    "RENUNCIA POR EVASION DISCIPLINARIA",
}

TIPOS_NOTIFICACION_RQ_CON_CARTA = {
    "RENUNCIA FORMAL",
    "RENUNCIA POR EVASION DISCIPLINARIA",
}

TIPOS_NOTIFICACION_RQ_CON_ULTIMO_DIA = {
    "RENUNCIA FORMAL",
    "RENUNCIA INFORMADA",
    "ABANDONO",
    "TERMINACION DE CONTRATO",
}

TURNOS_RQ = {
    "DIURNO",
    "DIURNO - MAÑANA Y TARDE",
    "NOCTURNO",
    "ROTATIVO",
}

IDS_CIUDADES_RQ_PERSONAL_NUEVO = {
    10,   # Bogotá D.C.
    14,   # Cajica
    29,   # Facatativa
    33,   # Funza
    62,   # Mosquera
    103,  # Tocancipa
}
TIPO_DOCUMENTO_RQ_CARTA_RETIRO = "CARTA_RETIRO"


OPCIONES_ENTREGA_GENERAL = {"NO APLICA", "ACEPTADO", "RECHAZADO"}
OPCIONES_CUMPLIMIENTO = {"NO APLICA", "CUMPLE", "NO CUMPLE"}
OPCIONES_SI_NO = {"SI", "NO"}
OPCIONES_SI_NO_HISTORICO = {"SI", "NO", "NO APLICA"}
OPCIONES_ESTADO_PAZ_SALVO = {"ABIERTO", "CERRADO"}


ROL_ADMIN = 1
ROL_SUPER_ADMIN = 5
ROL_OPERACIONES = 6
ROL_DESARROLLADOR = 15

ROLES_GLOBALES = {
    ROL_ADMIN,
    ROL_SUPER_ADMIN,
    ROL_DESARROLLADOR,
}

PERMISO_OPERACIONES_RETIROS = "OPERACIONES_RETIROS"


def _roles_ids_actuales(current) -> set[int]:
    roles_ids = current.get("roles_ids") or []

    return {
        int(id_rol)
        for id_rol in roles_ids
        if str(id_rol).strip()
    }


def _permisos_actuales(current) -> set[str]:
    permisos = current.get("permisos") or []

    return {
        str(permiso).strip()
        for permiso in permisos
        if str(permiso).strip()
    }


def validar_acceso_operaciones_retiros(current) -> None:
    roles_ids = _roles_ids_actuales(current)
    permisos = _permisos_actuales(current)

    tiene_acceso = bool(
        roles_ids & ROLES_GLOBALES
        or ROL_OPERACIONES in roles_ids
        or PERMISO_OPERACIONES_RETIROS in permisos
    )

    if tiene_acceso:
        return

    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail={
            "mensaje": (
                "No tienes permiso para gestionar "
                "Retiros de Operaciones."
            ),
            "permisoRequerido": PERMISO_OPERACIONES_RETIROS,
        },
    )


def require_operaciones_retiros(
    current=Depends(get_current_user),
):
    validar_acceso_operaciones_retiros(current)

    return current


def _normalizar_usuario(usuario: str | None) -> str:
    valor = str(usuario or "").strip()
    return valor or "operaciones"


def _normalizar_texto_requerido(
    valor: str | None,
    nombre_campo: str,
) -> str:
    texto = str(valor or "").strip()

    if not texto:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"El campo {nombre_campo} es obligatorio.",
        )

    return texto


def _normalizar_texto_opcional(valor: str | None) -> str | None:
    texto = str(valor or "").strip()
    return texto or None


def _normalizar_opcion(
    valor: str | None,
    nombre_campo: str,
    opciones_validas: set[str],
) -> str:
    opcion = str(valor or "").strip().upper()

    if opcion not in opciones_validas:
        opciones = ", ".join(sorted(opciones_validas))
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"El campo {nombre_campo} contiene un valor no válido. "
                f"Opciones permitidas: {opciones}."
            ),
        )

    return opcion


def _validar_valor_descuento(
    aplica_descuento: str,
    valor_descuento: Decimal | None,
) -> Decimal | None:
    if valor_descuento is not None and valor_descuento < 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="El valor del descuento no puede ser negativo.",
        )

    # El valor del descuento no es obligatorio.
    # Si no aplica descuento, cualquier valor recibido se descarta.
    if aplica_descuento == "NO":
        return None

    return valor_descuento


def _validar_archivo_pdf(archivo: UploadFile, contenido: bytes) -> None:
    nombre_original = str(archivo.filename or "").strip()

    if not nombre_original:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="El archivo de paz y salvo no tiene un nombre válido.",
        )

    extension = Path(nombre_original).suffix.lower()

    if extension != ".pdf":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="El paz y salvo debe cargarse en formato PDF.",
        )

    content_type = str(archivo.content_type or "").lower()

    if content_type not in {
        "application/pdf",
        "application/octet-stream",
        "",
    }:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="El tipo de archivo recibido no corresponde a un PDF.",
        )

    if not contenido:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="El archivo de paz y salvo está vacío.",
        )

    if len(contenido) > TAMANO_MAXIMO_PDF:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="El archivo supera el tamaño máximo permitido de 10 MB.",
        )

    if not contenido.startswith(b"%PDF"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="El archivo cargado no contiene una estructura PDF válida.",
        )


def _validar_evidencia(
    archivo: UploadFile,
    contenido: bytes,
    nombre_campo: str,
) -> tuple[str, str, str]:
    nombre_original = Path(str(archivo.filename or "")).name.strip()

    if not nombre_original:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"El archivo de {nombre_campo} no tiene un nombre válido.",
        )

    if not contenido:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"El archivo de {nombre_campo} está vacío.",
        )

    if len(contenido) > TAMANO_MAXIMO_EVIDENCIA:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=(
                f"El archivo de {nombre_campo} supera el tamaño máximo "
                "permitido de 10 MB."
            ),
        )

    extension = Path(nombre_original).suffix.lower()
    mime_type = str(
        archivo.content_type or "application/octet-stream"
    ).strip()

    return nombre_original, extension, mime_type


def _guardar_evidencia_paz_salvo(
    db: Session,
    *,
    id_paz_y_salvo: int,
    id_retiro_laboral: int,
    tipo_evidencia: str,
    archivo: UploadFile,
    contenido: bytes,
    usuario: str,
    carpeta_evidencias: Path,
) -> tuple[int, Path]:
    if tipo_evidencia not in TIPOS_EVIDENCIA_PAZ_SALVO:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Tipo de evidencia no permitido: {tipo_evidencia}.",
        )

    nombre_original, extension, mime_type = _validar_evidencia(
        archivo=archivo,
        contenido=contenido,
        nombre_campo=tipo_evidencia,
    )

    extension_guardado = extension or ".bin"
    nombre_guardado = (
        f"{tipo_evidencia.lower()}_"
        f"{id_retiro_laboral}_{uuid4().hex}{extension_guardado}"
    )

    ruta_fisica = carpeta_evidencias / nombre_guardado
    ruta_fisica.write_bytes(contenido)

    ruta_archivo_bd = str(ruta_fisica).replace("\\", "/")

    query_insert = text("""
        INSERT INTO public."PazYSalvoOperacionesEvidencia" (
            "IdPazYSalvo",
            "IdRetiroLaboral",
            "TipoEvidencia",
            "NombreArchivo",
            "NombreArchivoOriginal",
            "RutaArchivo",
            "ExtensionArchivo",
            "MimeType",
            "PesoArchivo",
            "Observacion",
            "Activo",
            "Eliminado",
            "FechaCreacion",
            "FechaActualizacion",
            "CreadoPor",
            "UsuarioActualizacion"
        )
        VALUES (
            :id_paz_y_salvo,
            :id_retiro_laboral,
            :tipo_evidencia,
            :nombre_archivo,
            :nombre_archivo_original,
            :ruta_archivo,
            :extension_archivo,
            :mime_type,
            :peso_archivo,
            :observacion,
            true,
            false,
            CURRENT_TIMESTAMP,
            CURRENT_TIMESTAMP,
            :creado_por,
            :usuario_actualizacion
        )
        RETURNING "IdPazYSalvoEvidencia";
    """)

    id_evidencia = db.execute(
        query_insert,
        {
            "id_paz_y_salvo": id_paz_y_salvo,
            "id_retiro_laboral": id_retiro_laboral,
            "tipo_evidencia": tipo_evidencia,
            "nombre_archivo": nombre_guardado,
            "nombre_archivo_original": nombre_original,
            "ruta_archivo": ruta_archivo_bd,
            "extension_archivo": extension or None,
            "mime_type": mime_type,
            "peso_archivo": len(contenido),
            "observacion": "Evidencia adjunta desde Operaciones.",
            "creado_por": usuario,
            "usuario_actualizacion": usuario,
        },
    ).scalar_one()

    return id_evidencia, ruta_fisica


def _obtener_usuario_actual_rq(current) -> dict:
    """
    Obtiene la identidad del usuario autenticado para el RQ.

    IdUsuarioLider se guarda directamente desde la sesión autenticada.
    El front no puede escoger ni alterar el líder.
    """
    usuario = current.get("usuario")

    if usuario is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="No fue posible identificar el usuario autenticado.",
        )

    id_usuario = getattr(usuario, "IdUsuario", None)
    nombre_completo = str(
        getattr(usuario, "NombreUsuario", "") or ""
    ).strip()
    login_usuario = str(
        getattr(usuario, "Usuario", "") or ""
    ).strip()

    if id_usuario is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "El usuario autenticado no tiene IdUsuario y no puede "
                "registrarse como líder del RQ."
            ),
        )

    if not nombre_completo:
        nombre_completo = login_usuario or "Usuario Operaciones"

    return {
        "IdUsuario": id_usuario,
        "NombreCompleto": nombre_completo,
        "Usuario": login_usuario or nombre_completo,
    }


def _validar_perfil_rq(
    db: Session,
    id_perfil_rq: int,
):
    query = text("""
        SELECT
            "IdPerfilRQ",
            "CodigoPerfil",
            "DescripcionPerfil",
            "Genero",
            "NivelEscolaridad",
            "Observaciones"
        FROM public."PerfilRQ"
        WHERE "IdPerfilRQ" = :id_perfil_rq
          AND COALESCE("Activo", true) = true
        LIMIT 1;
    """)

    perfil = db.execute(
        query,
        {"id_perfil_rq": id_perfil_rq},
    ).mappings().first()

    if not perfil:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="El perfil RQ seleccionado no existe o está inactivo.",
        )

    return perfil


def _obtener_contexto_retiro_rq(
    db: Session,
    id_retiro_laboral: int,
    id_paz_y_salvo: int,
):
    """
    Valida que el retiro y el Paz y Salvo correspondan al mismo trabajador.

    IdRegistroPersonal e IdCliente se toman siempre de la base de datos;
    no se confían al front para evitar inconsistencias.
    """
    query = text("""
        SELECT
            rl."IdRetiroLaboral",
            rl."IdRegistroPersonal",
            rl."IdCliente",
            rl."EstadoCasoRRLL",
            ps."IdPazYSalvo",
            rp."NumeroIdentificacion",
            TRIM(
                COALESCE(rp."Nombres", '') || ' ' ||
                COALESCE(rp."Apellidos", '')
            ) AS "NombreCompleto",
            c."Nombre" AS "NombreCliente",
            acc."IdCargo",
            ca."NombreCargo",
            psd."EstadoPazYSalvo"
        FROM public."RetiroLaboral" rl
        INNER JOIN public."PazYSalvoOperaciones" ps
            ON ps."IdRetiroLaboral" = rl."IdRetiroLaboral"
           AND ps."IdPazYSalvo" = :id_paz_y_salvo
        INNER JOIN public."RegistroPersonal" rp
            ON rp."IdRegistroPersonal" = rl."IdRegistroPersonal"
        INNER JOIN public."Cliente" c
            ON c."IdCliente" = rl."IdCliente"
        LEFT JOIN LATERAL (
            SELECT
                x."IdCargo"
            FROM public."AsignacionCargoCliente" x
            WHERE x."IdRegistroPersonal" = rl."IdRegistroPersonal"
              AND x."IdCargo" IS NOT NULL
            ORDER BY
                x."FechaActualizacion" DESC NULLS LAST,
                x."FechaCreacion" DESC NULLS LAST,
                x."IdAsignacionCargoCliente" DESC
            LIMIT 1
        ) acc ON true
        LEFT JOIN public."Cargo" ca
            ON ca."IdCargo" = acc."IdCargo"
        LEFT JOIN LATERAL (
            SELECT
                d."EstadoPazYSalvo"
            FROM public."PazYSalvoOperacionesDetalle" d
            WHERE d."IdPazYSalvo" = ps."IdPazYSalvo"
            ORDER BY d."IdPazYSalvoDetalle" DESC
            LIMIT 1
        ) psd ON true
        WHERE rl."IdRetiroLaboral" = :id_retiro_laboral
          AND COALESCE(rl."Activo", true) = true
        LIMIT 1;
    """)

    contexto = db.execute(
        query,
        {
            "id_retiro_laboral": id_retiro_laboral,
            "id_paz_y_salvo": id_paz_y_salvo,
        },
    ).mappings().first()

    if not contexto:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=(
                "No se encontró un retiro activo asociado al Paz y Salvo "
                "indicado."
            ),
        )

    return contexto


def _validar_datos_rq(
    *,
    tipo_notificacion: str,
    fecha_retiro: date | None,
    fecha_ultimo_dia_laborado: date | None,
    requiere_reemplazo: bool,
    id_perfil_rq: int | None,
    ciudad: str | None,
    turno: str | None,
    motivo_vacante: str | None,
    observacion_cliente: str | None,
) -> dict:
    tipo = _normalizar_opcion(
        tipo_notificacion,
        "TipoNotificacion",
        TIPOS_NOTIFICACION_RQ,
    )

    fecha_retiro_normalizada = fecha_retiro
    fecha_ultimo_dia_normalizada = fecha_ultimo_dia_laborado

    if tipo == "NUNCA INGRESO":
        fecha_retiro_normalizada = None
        fecha_ultimo_dia_normalizada = None
    else:
        if fecha_retiro_normalizada is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    "La fecha de retiro es obligatoria para la notificación "
                    f"{tipo}."
                ),
            )

        if tipo in TIPOS_NOTIFICACION_RQ_CON_ULTIMO_DIA:
            if fecha_ultimo_dia_normalizada is None:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=(
                        "El último día laborado es obligatorio para la "
                        f"notificación {tipo}."
                    ),
                )
        else:
            fecha_ultimo_dia_normalizada = None

    ciudad_normalizada = _normalizar_texto_opcional(ciudad)
    turno_normalizado = _normalizar_texto_opcional(turno)
    motivo_vacante_normalizado = _normalizar_texto_opcional(motivo_vacante)
    observacion_cliente_normalizada = _normalizar_texto_opcional(
        observacion_cliente
    )

    if requiere_reemplazo:
        if id_perfil_rq is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="El perfil es obligatorio cuando requiere reemplazo.",
            )

        # Ciudad se consulta automáticamente desde DatosAdicionales.
        # No exigir digitación si el trabajador no tiene ciudad registrada.
        # Se conserva None en lugar de inventar una ciudad.
        ciudad_normalizada = _normalizar_texto_opcional(ciudad_normalizada)

        turno_normalizado = _normalizar_opcion(
            turno_normalizado,
            "Turno",
            TURNOS_RQ,
        )

        observacion_cliente_normalizada = _normalizar_texto_requerido(
            observacion_cliente_normalizada,
            "ObservacionCliente",
        )
    else:
        id_perfil_rq = None
        ciudad_normalizada = None
        turno_normalizado = None
        motivo_vacante_normalizado = None
        observacion_cliente_normalizada = None

    return {
        "TipoNotificacion": tipo,
        "FechaRetiro": fecha_retiro_normalizada,
        "FechaUltimoDiaLaborado": fecha_ultimo_dia_normalizada,
        "RequiereReemplazo": requiere_reemplazo,
        "IdPerfilRQ": id_perfil_rq,
        "Ciudad": ciudad_normalizada,
        "Turno": turno_normalizado,
        "MotivoVacante": motivo_vacante_normalizado,
        "ObservacionCliente": observacion_cliente_normalizada,
    }


def _validar_adjunto_rq(
    archivo: UploadFile,
    contenido: bytes,
) -> tuple[str, str, str]:
    nombre_original = Path(str(archivo.filename or "")).name.strip()

    if not nombre_original:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="El adjunto del RQ no tiene un nombre válido.",
        )

    if not contenido:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="El adjunto del RQ está vacío.",
        )

    if len(contenido) > TAMANO_MAXIMO_ADJUNTO_RQ:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="El adjunto del RQ supera el tamaño máximo de 10 MB.",
        )

    extension = Path(nombre_original).suffix.lower()
    mime_type = str(
        archivo.content_type or "application/octet-stream"
    ).strip()

    return nombre_original, extension, mime_type


def _existe_carta_retiro_rq(
    db: Session,
    id_rq_operaciones: int,
) -> bool:
    query = text("""
        SELECT 1
        FROM public."RQOperacionesAdjunto"
        WHERE "IdRQOperaciones" = :id_rq_operaciones
          AND "TipoDocumento" = :tipo_documento
          AND COALESCE("Activo", true) = true
          AND COALESCE("Eliminado", false) = false
        LIMIT 1;
    """)

    return db.execute(
        query,
        {
            "id_rq_operaciones": id_rq_operaciones,
            "tipo_documento": TIPO_DOCUMENTO_RQ_CARTA_RETIRO,
        },
    ).first() is not None


def _guardar_adjunto_rq(
    db: Session,
    *,
    id_rq_operaciones: int,
    id_retiro_laboral: int,
    archivo: UploadFile,
    contenido: bytes,
    usuario: str,
    carpeta_rq: Path,
) -> tuple[int, Path]:
    nombre_original, extension, mime_type = _validar_adjunto_rq(
        archivo,
        contenido,
    )

    carpeta_rq.mkdir(parents=True, exist_ok=True)

    extension_guardado = extension or ".bin"
    nombre_guardado = (
        f"carta_retiro_{id_rq_operaciones}_{uuid4().hex}"
        f"{extension_guardado}"
    )

    ruta_fisica = carpeta_rq / nombre_guardado
    ruta_fisica.write_bytes(contenido)
    ruta_archivo_bd = str(ruta_fisica).replace("\\", "/")

    db.execute(
        text("""
            UPDATE public."RQOperacionesAdjunto"
            SET
                "Activo" = false,
                "FechaActualizacion" = CURRENT_TIMESTAMP,
                "UsuarioActualizacion" = :usuario
            WHERE "IdRQOperaciones" = :id_rq_operaciones
              AND "TipoDocumento" = :tipo_documento
              AND COALESCE("Activo", true) = true
              AND COALESCE("Eliminado", false) = false;
        """),
        {
            "usuario": usuario,
            "id_rq_operaciones": id_rq_operaciones,
            "tipo_documento": TIPO_DOCUMENTO_RQ_CARTA_RETIRO,
        },
    )

    id_adjunto = db.execute(
        text("""
            INSERT INTO public."RQOperacionesAdjunto" (
                "IdRQOperaciones",
                "IdRetiroLaboral",
                "TipoDocumento",
                "NombreArchivo",
                "NombreArchivoOriginal",
                "RutaArchivo",
                "ExtensionArchivo",
                "MimeType",
                "PesoArchivo",
                "Activo",
                "Eliminado",
                "UsuarioCreacion",
                "FechaCreacion"
            )
            VALUES (
                :id_rq_operaciones,
                :id_retiro_laboral,
                :tipo_documento,
                :nombre_archivo,
                :nombre_archivo_original,
                :ruta_archivo,
                :extension_archivo,
                :mime_type,
                :peso_archivo,
                true,
                false,
                :usuario_creacion,
                CURRENT_TIMESTAMP
            )
            RETURNING "IdRQOperacionesAdjunto";
        """),
        {
            "id_rq_operaciones": id_rq_operaciones,
            "id_retiro_laboral": id_retiro_laboral,
            "tipo_documento": TIPO_DOCUMENTO_RQ_CARTA_RETIRO,
            "nombre_archivo": nombre_guardado,
            "nombre_archivo_original": nombre_original,
            "ruta_archivo": ruta_archivo_bd,
            "extension_archivo": extension or None,
            "mime_type": mime_type,
            "peso_archivo": len(contenido),
            "usuario_creacion": usuario,
        },
    ).scalar_one()

    return id_adjunto, ruta_fisica


def _serializar_rq(row) -> dict:
    return {
        "IdRQOperaciones": int(row["IdRQOperaciones"]),
        "TipoRQ": row.get("TipoRQ"),
        "CantidadSolicitada": int(row.get("CantidadSolicitada") or 1),
        "EnviadoSeleccion": bool(row.get("EnviadoSeleccion") or False),
        "FechaEnvioSeleccion": row.get("FechaEnvioSeleccion"),
        "IdRetiroLaboral": int(row["IdRetiroLaboral"]),
        "IdPazYSalvo": int(row["IdPazYSalvo"]),
        "IdRegistroPersonal": int(row["IdRegistroPersonal"]),
        "NumeroIdentificacion": row.get("NumeroIdentificacion"),
        "NombreCompleto": row.get("NombreCompleto"),
        "IdCliente": int(row["IdCliente"]),
        "NombreCliente": row.get("NombreCliente"),
        "IdCargo": (
            int(row["IdCargo"])
            if row.get("IdCargo") is not None
            else (
                int(row["IdCargoDerivado"])
                if row.get("IdCargoDerivado") is not None
                else None
            )
        ),
        "NombreCargo": row.get("NombreCargo"),
        "IdUsuarioLider": str(row["IdUsuarioLider"]),
        "NombreLider": row.get("NombreLider"),
        "IdPerfilRQ": (
            int(row["IdPerfilRQ"])
            if row.get("IdPerfilRQ") is not None
            else None
        ),
        "CodigoPerfil": row.get("CodigoPerfil"),
        "DescripcionPerfil": row.get("DescripcionPerfil"),
        "GeneroPerfil": row.get("GeneroPerfil"),
        "NivelEscolaridadPerfil": row.get("NivelEscolaridadPerfil"),
        "ObservacionesPerfil": row.get("ObservacionesPerfil"),
        "TipoNotificacion": row["TipoNotificacion"],
        "FechaRetiro": row["FechaRetiro"],
        "FechaUltimoDiaLaborado": row["FechaUltimoDiaLaborado"],
        "Observacion": row["Observacion"],
        "RequiereReemplazo": bool(row["RequiereReemplazo"]),
        "Ciudad": row["Ciudad"],
        "Turno": row["Turno"],
        "MotivoVacante": row["MotivoVacante"],
        "ObservacionCliente": row["ObservacionCliente"],
        "FechaRegistro": row["FechaRegistro"],
        "EstadoRQ": row["EstadoRQ"],
        "EnviadoRRLL": bool(row["EnviadoRRLL"]),
        "FechaEnvioRRLL": row["FechaEnvioRRLL"],
        "Activo": bool(row["Activo"]),
        "FechaCreacion": row["FechaCreacion"],
        "FechaActualizacion": row["FechaActualizacion"],
    }


def _obtener_trabajador_contratado(
    db: Session,
    id_registro_personal: int,
):
    query = text("""
        SELECT
            rp."IdRegistroPersonal",
            rp."NumeroIdentificacion",
            TRIM(
                COALESCE(rp."Nombres", '') || ' ' ||
                COALESCE(rp."Apellidos", '')
            ) AS "NombreCompleto",
            rp."IdEstadoProceso"
        FROM public."RegistroPersonal" rp
        WHERE rp."IdRegistroPersonal" = :id_registro_personal
        LIMIT 1;
    """)

    trabajador = db.execute(
        query,
        {"id_registro_personal": id_registro_personal},
    ).mappings().first()

    if not trabajador:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No se encontró el trabajador seleccionado.",
        )

    if int(trabajador["IdEstadoProceso"] or 0) != ID_ESTADO_CONTRATADO:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "El trabajador ya no se encuentra en estado CONTRATADO "
                "y no puede ser enviado a retiro desde Operaciones."
            ),
        )

    return trabajador


def _obtener_vinculacion_para_retiro(
    db: Session,
    id_registro_personal: int,
    fecha_ultimo_dia_laborado: date,
) -> int:
    """Asocia exclusivamente el ciclo laboral ACTIVO del trabajador.

    Nunca deduce la empresa a partir del cliente ni reutiliza un ciclo histórico.
    Si hay cero o varios ciclos elegibles, exige corregir el dato de origen.
    """
    vinculaciones = db.execute(
        text("""
            SELECT vl."IdVinculacionLaboral"
            FROM public."VinculacionLaboral" vl
            INNER JOIN public."EmpresaContratante" ec
                ON ec."IdEmpresaContratante" = vl."IdEmpresaContratante"
            WHERE vl."IdRegistroPersonal" = :id_registro_personal
              AND UPPER(TRIM(COALESCE(vl."EstadoVinculacion", ''))) = 'ACTIVO'
              AND vl."FechaIngreso" IS NOT NULL
              AND vl."FechaIngreso" <= :fecha_ultimo_dia_laborado
            ORDER BY vl."IdVinculacionLaboral"
            LIMIT 2;
        """),
        {
            "id_registro_personal": id_registro_personal,
            "fecha_ultimo_dia_laborado": fecha_ultimo_dia_laborado,
        },
    ).mappings().all()

    if len(vinculaciones) != 1:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "No fue posible identificar una única vinculación laboral ACTIVA "
                "con empresa contratante y fecha de ingreso válida para este retiro. "
                "Revisa la vinculación del trabajador en Contratación antes de continuar."
            ),
        )

    return int(vinculaciones[0]["IdVinculacionLaboral"])


def _validar_motivo_retiro(
    db: Session,
    id_motivo_retiro: int,
):
    query = text("""
        SELECT
            "IdMotivoRetiro",
            "Nombre"
        FROM public."MotivoRetiro"
        WHERE "IdMotivoRetiro" = :id_motivo_retiro
          AND COALESCE("Activo", true) = true
        LIMIT 1;
    """)

    motivo = db.execute(
        query,
        {"id_motivo_retiro": id_motivo_retiro},
    ).mappings().first()

    if not motivo:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="El motivo de retiro seleccionado no existe o está inactivo.",
        )

    return motivo


def _validar_retiro_abierto(
    db: Session,
    id_registro_personal: int,
) -> None:
    query = text("""
        SELECT
            "IdRetiroLaboral",
            "EstadoCasoRRLL"
        FROM public."RetiroLaboral"
        WHERE "IdRegistroPersonal" = :id_registro_personal
          AND COALESCE("Activo", true) = true
        ORDER BY "IdRetiroLaboral" DESC
        LIMIT 1;
    """)

    retiro_existente = db.execute(
        query,
        {"id_registro_personal": id_registro_personal},
    ).mappings().first()

    if retiro_existente:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "El trabajador ya tiene un proceso de retiro activo "
                f"con IdRetiroLaboral={retiro_existente['IdRetiroLaboral']}."
            ),
        )


def _obtener_cliente_actual(
    db: Session,
    id_registro_personal: int,
) -> int | None:
    query = text("""
        SELECT acc."IdCliente"
        FROM public."AsignacionCargoCliente" acc
        WHERE acc."IdRegistroPersonal" = :id_registro_personal
          AND acc."IdCliente" IS NOT NULL
        ORDER BY
            acc."FechaActualizacion" DESC NULLS LAST,
            acc."FechaCreacion" DESC NULLS LAST,
            acc."IdAsignacionCargoCliente" DESC
        LIMIT 1;
    """)

    row = db.execute(
        query,
        {"id_registro_personal": id_registro_personal},
    ).mappings().first()

    return int(row["IdCliente"]) if row and row["IdCliente"] is not None else None


def _obtener_cargo_actual(
    db: Session,
    id_registro_personal: int,
):
    """
    Obtiene el cargo vigente del trabajador desde AsignacionCargoCliente.

    Se toma la asignación más reciente por fecha de actualización,
    fecha de creación e identificador de asignación.
    """
    query = text("""
        SELECT
            acc."IdCargo",
            c."NombreCargo"
        FROM public."AsignacionCargoCliente" acc
        INNER JOIN public."Cargo" c
            ON c."IdCargo" = acc."IdCargo"
        WHERE acc."IdRegistroPersonal" = :id_registro_personal
          AND acc."IdCargo" IS NOT NULL
          AND COALESCE(c."Activo", true) = true
        ORDER BY
            acc."FechaActualizacion" DESC NULLS LAST,
            acc."FechaCreacion" DESC NULLS LAST,
            acc."IdAsignacionCargoCliente" DESC
        LIMIT 1;
    """)

    row = db.execute(
        query,
        {"id_registro_personal": id_registro_personal},
    ).mappings().first()

    if not row:
        return None

    return {
        "IdCargo": int(row["IdCargo"]),
        "NombreCargo": str(row["NombreCargo"] or "").strip(),
    }


def _obtener_ciudad_trabajador(
    db: Session,
    id_registro_personal: int,
):
    """Obtiene la ciudad registrada en DatosAdicionales para el trabajador."""
    row = db.execute(
        text("""
            SELECT
                da."IdCiudad",
                c."Nombre" AS "NombreCiudad"
            FROM public."DatosAdicionales" da
            INNER JOIN public."Ciudad" c
                ON c."IdCiudad" = da."IdCiudad"
            WHERE da."IdRegistroPersonal" = :id_registro_personal
              AND COALESCE(c."Estado", true) = true
            ORDER BY da."IdDatosAdicionales" DESC
            LIMIT 1;
        """),
        {"id_registro_personal": id_registro_personal},
    ).mappings().first()

    if not row:
        return None

    return {
        "IdCiudad": int(row["IdCiudad"]),
        "NombreCiudad": str(row["NombreCiudad"] or "").strip(),
    }


def _validar_cliente(
    db: Session,
    id_cliente: int,
):
    query = text("""
        SELECT
            c."IdCliente",
            c."Nombre" AS "NombreCliente"
        FROM public."Cliente" c
        WHERE c."IdCliente" = :id_cliente
        LIMIT 1;
    """)

    cliente = db.execute(
        query,
        {"id_cliente": id_cliente},
    ).mappings().first()

    if not cliente:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="El cliente seleccionado no existe.",
        )

    return cliente


def _obtener_responsabilidades_perfil_paz_salvo(db: Session, id_cargo: int) -> dict:
    """Consulta informativa del perfil del cargo, sin alterar el flujo de guardado."""
    perfil = db.execute(
        text("""
            SELECT p.*
            FROM public."CargoPerfilPazSalvoOperaciones" cp
            INNER JOIN public."PerfilPazSalvoOperaciones" p
                ON p."IdPerfilPazSalvoOperaciones" = cp."IdPerfilPazSalvoOperaciones"
            WHERE cp."IdCargo" = :id_cargo
              AND COALESCE(cp."Activo", true) = true
              AND COALESCE(p."Activo", true) = true
            LIMIT 1;
        """),
        {"id_cargo": id_cargo},
    ).mappings().first()

    if not perfil:
        return {"IdPerfilPazSalvoOperaciones": None,
                "NombrePerfilPazSalvo": None, "Responsabilidades": []}

    id_perfil = int(perfil["IdPerfilPazSalvoOperaciones"])
    nombre = (perfil.get("NombrePerfil") or perfil.get("Nombre")
              or perfil.get("DescripcionPerfil") or perfil.get("CodigoPerfil"))
    filas = db.execute(
        text("""
            SELECT r.*, pr."Obligatorio"
            FROM public."PerfilResponsabilidadPazSalvoOperaciones" pr
            INNER JOIN public."ResponsabilidadPazSalvoOperaciones" r
                ON r."IdResponsabilidadPazSalvoOperaciones" = pr."IdResponsabilidadPazSalvoOperaciones"
            WHERE pr."IdPerfilPazSalvoOperaciones" = :id_perfil
              AND COALESCE(pr."Activo", true) = true
              AND COALESCE(r."Activo", true) = true
            ORDER BY r."IdResponsabilidadPazSalvoOperaciones";
        """),
        {"id_perfil": id_perfil},
    ).mappings().all()
    responsabilidades = []
    for fila in filas:
        responsabilidades.append({
            "IdResponsabilidadPazSalvoOperaciones": int(fila["IdResponsabilidadPazSalvoOperaciones"]),
            "CodigoResponsabilidad": fila.get("CodigoResponsabilidad") or fila.get("Codigo"),
            "NombreResponsabilidad": fila.get("NombreResponsabilidad") or fila.get("Nombre"),
            "Descripcion": fila.get("Descripcion"),
            "Obligatorio": bool(fila["Obligatorio"]),
        })
    return {"IdPerfilPazSalvoOperaciones": id_perfil,
            "NombrePerfilPazSalvo": str(nombre or "").strip(),
            "Responsabilidades": responsabilidades}


# Registro independiente de responsabilidades por perfil.
# No altera el guardado tradicional, PDF, RQ ni el envío a RRLL.
class RespuestaResponsabilidadPazSalvo(BaseModel):
    IdResponsabilidadPazSalvoOperaciones: int
    EstadoEntrega: str | None = None
    Observacion: str | None = None


class GuardarResponsabilidadesPazSalvo(BaseModel):
    Responsabilidades: list[RespuestaResponsabilidadPazSalvo]


@router.put("/paz-salvo/{id_paz_y_salvo}/responsabilidades")
def guardar_responsabilidades_paz_salvo(
    id_paz_y_salvo: int,
    payload: GuardarResponsabilidadesPazSalvo,
    db: Session = Depends(get_db),
    current=Depends(require_operaciones_retiros),
    _commit: bool = True,
):
    """Guarda las respuestas del perfil únicamente en casos pendientes de Operaciones."""
    try:
        caso = db.execute(text("""
            SELECT ps."IdRegistroPersonal", rl."EstadoCasoRRLL"
            FROM public."PazYSalvoOperaciones" ps
            INNER JOIN public."RetiroLaboral" rl
                ON rl."IdRetiroLaboral" = ps."IdRetiroLaboral"
            WHERE ps."IdPazYSalvo" = :id
              AND COALESCE(rl."Activo", true) = true
            FOR UPDATE OF ps
        """), {"id": id_paz_y_salvo}).mappings().first()
        if not caso:
            raise HTTPException(status_code=404, detail="Paz y Salvo no encontrado.")
        if str(caso["EstadoCasoRRLL"] or "").strip().upper() != "PENDIENTE_OPERACIONES":
            raise HTTPException(status_code=409, detail="Solo se pueden editar responsabilidades de casos pendientes en Operaciones.")

        cargo = _obtener_cargo_actual(db, int(caso["IdRegistroPersonal"]))
        if not cargo:
            raise HTTPException(status_code=409, detail="El trabajador no tiene un cargo vigente.")
        perfil = _obtener_responsabilidades_perfil_paz_salvo(db, cargo["IdCargo"])
        permitidos = {
            r["IdResponsabilidadPazSalvoOperaciones"]
            for r in perfil["Responsabilidades"]
        }
        ids = [r.IdResponsabilidadPazSalvoOperaciones for r in payload.Responsabilidades]
        if len(ids) != len(set(ids)) or set(ids) != permitidos:
            raise HTTPException(status_code=400, detail="Las responsabilidades deben coincidir exactamente con las configuradas para el perfil vigente, sin duplicados.")

        usuario = _obtener_usuario_actual_rq(current)["Usuario"]
        for respuesta in payload.Responsabilidades:
            estado = (respuesta.EstadoEntrega or "").strip().upper() or None
            if estado not in {None, "NO APLICA", "ENTREGADO", "PENDIENTE"}:
                raise HTTPException(status_code=400, detail="EstadoEntrega debe ser NO APLICA, ENTREGADO o PENDIENTE.")
            observacion = _normalizar_texto_opcional(respuesta.Observacion)
            db.execute(text("""
                INSERT INTO public."PazYSalvoOperacionesResponsabilidad" (
                    "IdPazYSalvo", "IdResponsabilidadPazSalvoOperaciones",
                    "EstadoEntrega", "Observacion", "Activo", "UsuarioCreacion"
                ) VALUES (:id, :responsabilidad, :estado, :observacion, true, :usuario)
                ON CONFLICT ("IdPazYSalvo", "IdResponsabilidadPazSalvoOperaciones")
                DO UPDATE SET "EstadoEntrega" = EXCLUDED."EstadoEntrega",
                    "Observacion" = EXCLUDED."Observacion", "Activo" = true,
                    "FechaActualizacion" = CURRENT_TIMESTAMP,
                    "UsuarioActualizacion" = :usuario
            """), {
                "id": id_paz_y_salvo,
                "responsabilidad": respuesta.IdResponsabilidadPazSalvoOperaciones,
                "estado": estado,
                "observacion": observacion,
                "usuario": usuario,
            })
        if _commit:
            db.commit()
        return {"success": True, "data": {"IdPazYSalvo": id_paz_y_salvo,
                "CantidadResponsabilidades": len(ids)}}
    except Exception:
        db.rollback()
        raise


@router.get("/paz-salvo/{id_paz_y_salvo}/responsabilidades")
def consultar_responsabilidades_guardadas(
    id_paz_y_salvo: int,
    db: Session = Depends(get_db),
    current=Depends(require_operaciones_retiros),
):
    """Consulta respuestas guardadas sin modificar registros."""
    existe = db.execute(text('SELECT 1 FROM public."PazYSalvoOperaciones" WHERE "IdPazYSalvo" = :id'),
                        {"id": id_paz_y_salvo}).first()
    if not existe:
        raise HTTPException(status_code=404, detail="Paz y Salvo no encontrado.")
    filas = db.execute(text("""
        SELECT "IdResponsabilidadPazSalvoOperaciones", "EstadoEntrega", "Observacion"
        FROM public."PazYSalvoOperacionesResponsabilidad"
        WHERE "IdPazYSalvo" = :id AND "Activo" = true
        ORDER BY "IdResponsabilidadPazSalvoOperaciones"
    """), {"id": id_paz_y_salvo}).mappings().all()
    return {"success": True, "data": [dict(fila) for fila in filas]}


# Catálogo funcional solicitado por Operaciones. No modifica tablas ni guardados.
# Los códigos son estables para permitir la futura persistencia individual.
VALIDACIONES_TRANSVERSALES_PAZ_SALVO = (
    ("CARNET_ALP", "Carné de Aseos La Perfección"),
    ("CARNET_ARL", "Carné o identificación de ARL (cuando corresponda)"),
    ("ACCESO_CLIENTE", "Carné, tarjeta o permiso de acceso del cliente"),
    ("LLAVES_CONTROLES", "Llaves y controles de acceso"),
    ("CASILLERO_LOCKER", "Casillero o locker"),
    ("DOTACION_EPP", "Dotación y EPP reutilizables asignados"),
    ("ELEMENTOS_ALP_CLIENTE", "Elementos asignados por ALP o por el cliente"),
    ("CONFIRMACION_CLIENTE", "Confirmación del cliente (cuando aplique)"),
    ("DESCUENTOS", "Novedades, faltantes o descuentos previa validación"),
    ("RESPONSABLE_RECIBE", "Responsable de recibir y aprobar la entrega"),
)

VALIDACIONES_ESPECIFICAS_PAZ_SALVO = {
    "OPERATIVO_BASICO": (
        ("EPP_PERSONAL", "Elementos de protección personal"),
    ),
    "OPERATIVO_TECNICO": (
        ("RELACION_HERRAMIENTAS", "Relación detallada de herramientas"),
        ("EQUIPOS_MAQUINARIA", "Equipos y maquinaria asignados"),
        ("CANTIDAD_ESTADO", "Cantidad y estado de los elementos"),
        ("PROPIEDAD_ELEMENTOS", "Identificar si el elemento pertenece a ALP o al cliente"),
        ("INVENTARIOS_CUSTODIA", "Inventarios y otros elementos bajo custodia"),
        ("RESPONSABLE_TECNICO", "Persona que recibe y valida la entrega"),
    ),
    "ADMINISTRATIVO_CAMPO": (
        ("EQUIPOS_COMUNICACION", "Equipos tecnológicos y de comunicación"),
        ("USUARIOS_ACCESOS", "Usuarios, correos, aplicaciones y accesos asignados"),
        ("DOCUMENTOS_ARCHIVOS", "Documentos, archivos e información bajo responsabilidad"),
        ("ACTA_PUESTO", "Acta de entrega del puesto de trabajo"),
        ("ACTIVIDADES", "Actividades finalizadas, en curso y pendientes"),
        ("UBICACION_ARCHIVOS", "Ubicación de archivos y documentos"),
        ("RECEPTOR_PUESTO", "Persona que recibe el puesto"),
    ),
    "SUPERVISION_LIDERAZGO": (
        ("HERRAMIENTAS_EQUIPOS", "Herramientas, equipos y elementos asignados"),
        ("USUARIOS_CLAVES", "Usuarios, claves y accesos tecnológicos"),
        ("REGISTROS_OPERACION", "Documentos, inventarios y registros de la operación"),
        ("ACTA_GESTION", "Acta de entrega de gestión"),
        ("ACTIVIDADES_PROGRAMADAS", "Estado de las actividades programadas"),
        ("PENDIENTES_CLIENTE", "Pendientes operativos, administrativos y compromisos con el cliente"),
        ("RECEPTOR_OPERACION", "Persona que recibe la operación"),
    ),
    "SERVICIOS_ESPECIALES": (
        ("HERRAMIENTAS_TECNICAS", "Herramientas y equipos técnicos"),
        ("INSTRUMENTOS_MEDICION", "Instrumentos de medición y control"),
        ("EPP_ESPECIALIZADO", "Elementos de protección personal especializados"),
        ("INSUMOS_CUSTODIA", "Insumos o elementos bajo custodia"),
        ("ESTADO_SERVICIO", "Estado de las actividades y pendientes del servicio"),
        ("SUMINISTROS_CLIENTE", "Elementos suministrados por el cliente"),
    ),
    "TRABAJO_ALTURAS": (
        ("EQUIPO_DESCRIPCION", "Descripción individual del equipo contra caídas"),
        ("EQUIPO_CODIGO", "Código o identificación del equipo"),
        ("EQUIPO_CANTIDAD", "Cantidad entregada"),
        ("EQUIPO_ESTADO", "Estado al momento de la devolución"),
        ("EQUIPO_NOVEDADES", "Faltantes o novedades"),
        ("CONCEPTO_COORDINADOR", "Concepto del coordinador de trabajo en alturas"),
        ("RECEPTOR_ALTURAS", "Nombre y confirmación de quien recibe"),
    ),
    # Perfil administrativo interno: validaciones transversales y de custodia.
    "ADMINISTRATIVO_INTERNO": (
        ("EQUIPOS_TECNOLOGICOS", "Equipos tecnológicos asignados"),
        ("USUARIOS_CORREOS", "Usuarios, correos y accesos tecnológicos"),
        ("DOCUMENTOS_CUSTODIA", "Documentos, archivos e inventarios bajo custodia"),
        ("ENTREGA_PENDIENTES", "Entrega de actividades y pendientes del puesto"),
    ),
}


# QA - Matriz de requisitos de William (cargos_ALP_perfiles).
# Este catálogo define exclusivamente los requisitos no cubiertos por la tabla
# PerfilElementoPazSalvoOperaciones. No se borran respuestas históricas.
# En OPERATIVO_BASICO, DOTACION_REUTILIZABLE y EPP_REUTILIZABLE se consultan
# por /elementos-perfil; los cuatro restantes por /validaciones.
REQUISITOS_EXCEL_POR_PERFIL = {
    "OPERATIVO_BASICO": (
        ("CARNET_ALP", "Carné de Aseos La Perfección"),
        ("ACCESO_CLIENTE", "Carnés o permisos de acceso otorgados por el cliente"),
        ("LLAVES_CONTROLES", "Llaves, casilleros o lockers"),
        ("DESCUENTOS", "Novedades, faltantes o descuentos aplicables"),
    ),
    "OPERATIVO_TECNICO": (
        ("RELACION_HERRAMIENTAS", "Relación detallada de herramientas"),
        ("EQUIPOS_MAQUINARIA", "Equipos y maquinaria asignados"),
        ("CANTIDAD_ESTADO", "Cantidad y estado de cada elemento"),
        ("PROPIEDAD_ELEMENTOS", "Identificación de si el elemento pertenece a ALP o al cliente"),
        ("INVENTARIOS_CUSTODIA", "Llaves, controles, inventarios y demás elementos bajo custodia"),
        ("RESPONSABLE_TECNICO", "Nombre del responsable que recibe y valida la entrega"),
    ),
    "ADMINISTRATIVO_CAMPO": (
        ("EQUIPOS_COMUNICACION", "Equipos tecnológicos y de comunicación"),
        ("USUARIOS_ACCESOS", "Usuarios, correos, aplicaciones y accesos asignados"),
        ("ACCESO_CLIENTE", "Carnés, tarjetas o permisos de acceso del cliente"),
        ("DOCUMENTOS_ARCHIVOS", "Llaves, documentos, archivos e información bajo su responsabilidad"),
        ("ACTA_PUESTO", "Acta de entrega del puesto de trabajo"),
        ("ACTIVIDADES", "Relación de actividades finalizadas, en curso y pendientes"),
        ("UBICACION_ARCHIVOS", "Ubicación de archivos y documentos"),
        ("RECEPTOR_PUESTO", "Identificación de la persona que recibe el puesto"),
    ),
    "SUPERVISION_LIDERAZGO": (
        ("HERRAMIENTAS_EQUIPOS", "Herramientas, equipos y elementos asignados"),
        ("USUARIOS_CLAVES", "Usuarios, claves y accesos tecnológicos"),
        ("LLAVES_CONTROLES", "Llaves, carnés y permisos de ingreso"),
        ("REGISTROS_OPERACION", "Documentos, inventarios y registros de la operación"),
        ("ACTA_GESTION", "Acta de entrega de gestión"),
        ("ACTIVIDADES_PROGRAMADAS", "Estado de las actividades programadas"),
        ("PENDIENTES_CLIENTE", "Pendientes operativos, administrativos y compromisos con el cliente"),
        ("RECEPTOR_OPERACION", "Identificación de la persona que recibe la operación"),
    ),
    "SERVICIOS_ESPECIALES": (
        ("HERRAMIENTAS_TECNICAS", "Herramientas y equipos técnicos"),
        ("INSTRUMENTOS_MEDICION", "Instrumentos de medición y control"),
        ("EPP_ESPECIALIZADO", "Elementos de protección personal especializados"),
        ("INSUMOS_CUSTODIA", "Insumos o elementos bajo custodia"),
        ("ESTADO_SERVICIO", "Estado de las actividades y pendientes del servicio"),
        ("SUMINISTROS_CLIENTE", "Elementos suministrados por el cliente"),
    ),
    # Perfil 6: exactamente seis requisitos del Excel. El catálogo anterior
    # VALIDACIONES_ESPECIFICAS_PAZ_SALVO queda solo como respaldo histórico.
    "TRABAJO_ALTURAS": (
        ("EQUIPO_DESCRIPCION", "Equipos de protección contra caídas y sus accesorios (registro individual por elemento)"),
        ("EQUIPO_CODIGO", "Descripción, código o identificación y cantidad de cada elemento"),
        ("EQUIPO_ESTADO", "Estado al momento de la devolución"),
        ("EQUIPO_NOVEDADES", "Faltantes o novedades"),
        ("CONCEPTO_COORDINADOR", "Concepto del coordinador de trabajo en alturas"),
        ("RECEPTOR_ALTURAS", "Nombre y confirmación de la persona que recibe"),
    ),
}


def _catalogo_validaciones_perfil(codigo_perfil: str) -> list[dict]:
    # ADMINISTRATIVO_INTERNO se conserva por compatibilidad histórica.
    requisitos = REQUISITOS_EXCEL_POR_PERFIL.get(codigo_perfil)
    if requisitos is None:
        requisitos = VALIDACIONES_ESPECIFICAS_PAZ_SALVO.get(codigo_perfil, ())
    resultado = []
    for codigo, nombre in requisitos:
        es_novedad = codigo == "DESCUENTOS"
        resultado.append({
            "CodigoElemento": codigo,
            "NombreElemento": nombre,
            "TipoValidacion": "PERFIL",  # nunca mostrar sección transversal
            "Obligatorio": False,
            "EstadosPermitidos": (["NO APLICA", "CON NOVEDAD"] if es_novedad
                                  else ["ENTREGADO", "PENDIENTE"]),
            "ObservacionObligatoria": not es_novedad,
        })
    return resultado


# Validaciones por perfil: persistencia independiente en QA.
# Se utiliza la tabla public."PazYSalvoOperacionesValidacion".
class RespuestaValidacionPazSalvo(BaseModel):
    CodigoElemento: str
    Estado: str | None = None
    Observacion: str | None = None


class GuardarValidacionesPazSalvo(BaseModel):
    Validaciones: list[RespuestaValidacionPazSalvo]


def _contexto_validaciones_paz_salvo(db: Session, id_paz_y_salvo: int, bloquear: bool = False):
    sufijo_bloqueo = ' FOR UPDATE OF ps' if bloquear else ''
    caso = db.execute(text('''
        SELECT ps."IdRegistroPersonal", rl."EstadoCasoRRLL"
        FROM public."PazYSalvoOperaciones" ps
        INNER JOIN public."RetiroLaboral" rl
          ON rl."IdRetiroLaboral" = ps."IdRetiroLaboral"
        WHERE ps."IdPazYSalvo" = :id
          AND COALESCE(rl."Activo", true) = true
    ''' + sufijo_bloqueo), {"id": id_paz_y_salvo}).mappings().first()
    if not caso:
        raise HTTPException(status_code=404, detail="Paz y Salvo activo no encontrado.")
    cargo = _obtener_cargo_actual(db, int(caso["IdRegistroPersonal"]))
    if not cargo:
        raise HTTPException(status_code=409, detail="El trabajador no tiene cargo configurado.")
    perfil = db.execute(text('''
        SELECT p."CodigoPerfil", p."NombrePerfil"
        FROM public."CargoPerfilPazSalvoOperaciones" cp
        INNER JOIN public."PerfilPazSalvoOperaciones" p
          ON p."IdPerfilPazSalvoOperaciones" = cp."IdPerfilPazSalvoOperaciones"
        WHERE cp."IdCargo" = :cargo
          AND COALESCE(cp."Activo", true) = true
          AND COALESCE(p."Activo", true) = true
        LIMIT 1
    '''), {"cargo": cargo["IdCargo"]}).mappings().first()
    if not perfil:
        raise HTTPException(status_code=409, detail="El cargo no tiene perfil de Paz y Salvo activo.")
    codigo = str(perfil["CodigoPerfil"] or "").strip().upper()
    if codigo not in VALIDACIONES_ESPECIFICAS_PAZ_SALVO:
        raise HTTPException(status_code=409, detail="El perfil no tiene catálogo de validaciones configurado.")
    return caso, cargo, codigo, _catalogo_validaciones_perfil(codigo)


@router.get("/paz-salvo/{id_paz_y_salvo}/validaciones")
def consultar_validaciones_paz_salvo(
    id_paz_y_salvo: int,
    db: Session = Depends(get_db),
    current=Depends(require_operaciones_retiros),
):
    # Solo muestra las validaciones transversales y las del perfil del cargo.
    caso, cargo, codigo, catalogo = _contexto_validaciones_paz_salvo(db, id_paz_y_salvo)
    filas = db.execute(text('''
        SELECT "CodigoElemento", "CodigoPerfil", "Estado", "Observacion"
        FROM public."PazYSalvoOperacionesValidacion"
        WHERE "IdPazYSalvo" = :id AND "CodigoPerfil" = :perfil
    '''), {"id": id_paz_y_salvo, "perfil": codigo}).mappings().all()
    respuestas = {fila["CodigoElemento"]: fila for fila in filas}
    resultado = []
    for item in catalogo:
        registro = respuestas.get(item["CodigoElemento"])
        resultado.append({**item,
            "Estado": registro["Estado"] if registro else None,
            "Observacion": registro["Observacion"] if registro else None})
    return {"success": True, "data": {
        "IdPazYSalvo": id_paz_y_salvo,
        "IdCargo": cargo["IdCargo"], "NombreCargo": cargo["NombreCargo"],
        "CodigoPerfil": codigo, "Validaciones": resultado,
    }}


@router.put("/paz-salvo/{id_paz_y_salvo}/validaciones")
def guardar_validaciones_paz_salvo(
    id_paz_y_salvo: int,
    payload: GuardarValidacionesPazSalvo,
    db: Session = Depends(get_db),
    current=Depends(require_operaciones_retiros),
    _commit: bool = True,
):
    # Guarda solo las respuestas enviadas, sin exigir diligenciar todas.
    try:
        caso, cargo, codigo, catalogo = _contexto_validaciones_paz_salvo(db, id_paz_y_salvo, bloquear=True)
        if str(caso["EstadoCasoRRLL"] or "").strip().upper() != "PENDIENTE_OPERACIONES":
            raise HTTPException(status_code=409, detail="Solo se pueden editar casos pendientes de Operaciones.")
        permitidos = {item["CodigoElemento"] for item in catalogo}
        codigos = [str(r.CodigoElemento or "").strip().upper() for r in payload.Validaciones]
        if len(codigos) != len(set(codigos)) or any(c not in permitidos for c in codigos):
            raise HTTPException(status_code=400, detail="Hay validaciones duplicadas o ajenas al perfil del cargo.")
        usuario = _obtener_usuario_actual_rq(current)["Usuario"]
        for respuesta, elemento in zip(payload.Validaciones, codigos):
            estado = str(respuesta.Estado or "").strip().upper() or None
            if estado not in {None, "ENTREGADO", "PENDIENTE", "NO APLICA", "CON NOVEDAD"}:
                raise HTTPException(status_code=400, detail=f"Estado no permitido para {elemento}.")
            observacion = _normalizar_texto_opcional(respuesta.Observacion)
            if codigo in {"OPERATIVO_TECNICO", "ADMINISTRATIVO_CAMPO", "SUPERVISION_LIDERAZGO"} and estado and not observacion:
                raise HTTPException(
                    status_code=400,
                    detail=f"Debes registrar el detalle obligatorio de {elemento}.",
                )
            db.execute(text('''
                INSERT INTO public."PazYSalvoOperacionesValidacion" (
                    "IdPazYSalvo", "CodigoElemento", "CodigoPerfil", "Estado",
                    "Observacion", "UsuarioCreacion"
                ) VALUES (:id, :elemento, :perfil, :estado, :observacion, :usuario)
                ON CONFLICT ("IdPazYSalvo", "CodigoElemento")
                DO UPDATE SET "CodigoPerfil" = EXCLUDED."CodigoPerfil",
                  "Estado" = EXCLUDED."Estado", "Observacion" = EXCLUDED."Observacion",
                  "FechaActualizacion" = CURRENT_TIMESTAMP,
                  "UsuarioActualizacion" = :usuario
            '''), {"id": id_paz_y_salvo, "elemento": elemento,
                  "perfil": codigo, "estado": estado,
                  "observacion": observacion, "usuario": usuario})
        if _commit:
            db.commit()
        return {"success": True, "data": {"IdPazYSalvo": id_paz_y_salvo,
                "CodigoPerfil": codigo, "CantidadGuardada": len(codigos)}}
    except Exception:
        db.rollback()
        raise


# Respuestas individuales de los elementos parametrizados por perfil.
# Endpoints independientes: no modifican el formulario histórico, PDF ni RRLL.
class RespuestaElementoPerfilPazSalvo(BaseModel):
    IdPerfilElementoPazSalvoOperaciones: int
    Estado: str | None = None
    Observacion: str | None = None


class GuardarElementosPerfilPazSalvo(BaseModel):
    ElementosPerfil: list[RespuestaElementoPerfilPazSalvo]


def _contexto_elementos_perfil_paz_salvo(
    db: Session, id_paz_y_salvo: int, bloquear: bool = False
):
    sufijo = " FOR UPDATE OF ps" if bloquear else ""
    caso = db.execute(text("""
        SELECT ps."IdRegistroPersonal", rl."EstadoCasoRRLL"
        FROM public."PazYSalvoOperaciones" ps
        INNER JOIN public."RetiroLaboral" rl
            ON rl."IdRetiroLaboral" = ps."IdRetiroLaboral"
        WHERE ps."IdPazYSalvo" = :id
          AND COALESCE(rl."Activo", true) = true
    """ + sufijo), {"id": id_paz_y_salvo}).mappings().first()
    if not caso:
        raise HTTPException(status_code=404, detail="Paz y Salvo activo no encontrado.")

    cargo = _obtener_cargo_actual(db, int(caso["IdRegistroPersonal"]))
    if not cargo:
        raise HTTPException(status_code=409, detail="El trabajador no tiene cargo vigente.")

    perfil = db.execute(text("""
        SELECT p."IdPerfilPazSalvoOperaciones", p."CodigoPerfil"
        FROM public."CargoPerfilPazSalvoOperaciones" cp
        INNER JOIN public."PerfilPazSalvoOperaciones" p
            ON p."IdPerfilPazSalvoOperaciones" = cp."IdPerfilPazSalvoOperaciones"
        WHERE cp."IdCargo" = :cargo
          AND COALESCE(cp."Activo", true) = true
          AND COALESCE(p."Activo", true) = true
        LIMIT 1
    """), {"cargo": cargo["IdCargo"]}).mappings().first()
    if not perfil:
        raise HTTPException(status_code=409, detail="El cargo no tiene perfil de Paz y Salvo activo.")

    elementos = db.execute(text("""
        SELECT "IdPerfilElementoPazSalvoOperaciones", "CodigoElemento",
               "NombreElemento", "TipoGestion", "Obligatorio"
        FROM public."PerfilElementoPazSalvoOperaciones"
        WHERE "IdPerfilPazSalvoOperaciones" = :perfil AND "Activo" = true
        ORDER BY "IdPerfilElementoPazSalvoOperaciones"
    """), {"perfil": perfil["IdPerfilPazSalvoOperaciones"]}).mappings().all()
    return caso, cargo, perfil, elementos


@router.get("/paz-salvo/{id_paz_y_salvo}/elementos-perfil")
def consultar_elementos_perfil_paz_salvo(
    id_paz_y_salvo: int,
    db: Session = Depends(get_db),
    current=Depends(require_operaciones_retiros),
):
    """Consulta catálogo vigente y respuestas guardadas del caso, sin escribir datos."""
    caso, cargo, perfil, elementos = _contexto_elementos_perfil_paz_salvo(db, id_paz_y_salvo)
    filas = db.execute(text("""
        SELECT "IdPerfilElementoPazSalvoOperaciones", "Estado", "Observacion"
        FROM public."PazYSalvoOperacionesElementoPerfilRespuesta"
        WHERE "IdPazYSalvo" = :id AND "Activo" = true
    """), {"id": id_paz_y_salvo}).mappings().all()
    respuestas = {int(f["IdPerfilElementoPazSalvoOperaciones"]): f for f in filas}
    resultado = []
    for elemento in elementos:
        item = dict(elemento)
        respuesta = respuestas.get(int(item["IdPerfilElementoPazSalvoOperaciones"]))
        item["Estado"] = respuesta["Estado"] if respuesta else None
        item["Observacion"] = respuesta["Observacion"] if respuesta else None
        resultado.append(item)
    return {"success": True, "data": {
        "IdPazYSalvo": id_paz_y_salvo,
        "IdCargo": cargo["IdCargo"],
        "NombreCargo": cargo["NombreCargo"],
        "CodigoPerfil": perfil["CodigoPerfil"],
        "ElementosPerfil": resultado,
    }}


@router.put("/paz-salvo/{id_paz_y_salvo}/elementos-perfil")
def guardar_elementos_perfil_paz_salvo(
    id_paz_y_salvo: int,
    payload: GuardarElementosPerfilPazSalvo,
    db: Session = Depends(get_db),
    current=Depends(require_operaciones_retiros),
    _commit: bool = True,
):
    """Guarda solo elementos enviados y válidos del perfil en casos pendientes."""
    try:
        caso, cargo, perfil, elementos = _contexto_elementos_perfil_paz_salvo(
            db, id_paz_y_salvo, bloquear=True
        )
        if str(caso["EstadoCasoRRLL"] or "").strip().upper() != "PENDIENTE_OPERACIONES":
            raise HTTPException(status_code=409, detail="Solo se pueden editar casos pendientes de Operaciones.")

        permitidos = {int(e["IdPerfilElementoPazSalvoOperaciones"]) for e in elementos}
        ids = [r.IdPerfilElementoPazSalvoOperaciones for r in payload.ElementosPerfil]
        if len(ids) != len(set(ids)) or any(i not in permitidos for i in ids):
            raise HTTPException(status_code=400, detail="Hay elementos duplicados o ajenos al perfil vigente.")

        usuario = _obtener_usuario_actual_rq(current)["Usuario"]
        for respuesta in payload.ElementosPerfil:
            estado = str(respuesta.Estado or "").strip().upper() or None
            if estado not in {None, "ENTREGADO", "PENDIENTE", "NO APLICA", "CON NOVEDAD"}:
                raise HTTPException(status_code=400, detail="Estado no permitido para el elemento.")
            observacion = _normalizar_texto_opcional(respuesta.Observacion)
            if estado == "PENDIENTE" and not observacion:
                raise HTTPException(
                    status_code=400,
                    detail=(
                        "Cuando un elemento se marca como NO ENTREGÓ "
                        "(PENDIENTE), su observación es obligatoria."
                    ),
                )
            parametros = {
                "id": id_paz_y_salvo,
                "elemento": respuesta.IdPerfilElementoPazSalvoOperaciones,
                "estado": estado,
                "observacion": observacion,
                "usuario": usuario,
            }
            # El bloqueo del caso serializa escrituras concurrentes. No se presupone
            # una restricción UNIQUE no verificada en la tabla nueva.
            existente = db.execute(text("""
                SELECT "IdRespuestaElementoPerfil"
                FROM public."PazYSalvoOperacionesElementoPerfilRespuesta"
                WHERE "IdPazYSalvo" = :id
                  AND "IdPerfilElementoPazSalvoOperaciones" = :elemento
                FOR UPDATE
            """), parametros).scalar_one_or_none()
            if existente is None:
                db.execute(text("""
                    INSERT INTO public."PazYSalvoOperacionesElementoPerfilRespuesta" (
                        "IdPazYSalvo", "IdPerfilElementoPazSalvoOperaciones",
                        "Estado", "Observacion", "Activo", "UsuarioCreacion"
                    ) VALUES (:id, :elemento, :estado, :observacion, true, :usuario)
                """), parametros)
            else:
                parametros["respuesta"] = existente
                db.execute(text("""
                    UPDATE public."PazYSalvoOperacionesElementoPerfilRespuesta"
                    SET "Estado" = :estado, "Observacion" = :observacion,
                        "Activo" = true, "FechaActualizacion" = CURRENT_TIMESTAMP,
                        "UsuarioActualizacion" = :usuario
                    WHERE "IdRespuestaElementoPerfil" = :respuesta
                """), parametros)
        if _commit:
            db.commit()
        return {"success": True, "data": {
            "IdPazYSalvo": id_paz_y_salvo,
            "CodigoPerfil": perfil["CodigoPerfil"],
            "CantidadGuardada": len(ids),
        }}
    except Exception:
        db.rollback()
        raise


@router.get("/elementos/trabajador/{id_registro_personal}")
def obtener_elementos_paz_salvo_por_trabajador(
    id_registro_personal: int,
    db: Session = Depends(get_db),
    current=Depends(require_operaciones_retiros),
):
    # Carga elementos antiguos y validaciones por perfil sin cambiar guardados.
    trabajador = _obtener_trabajador_contratado(db, id_registro_personal)
    cargo = _obtener_cargo_actual(db, id_registro_personal)
    data = {
        "IdRegistroPersonal": id_registro_personal,
        "NumeroIdentificacion": trabajador["NumeroIdentificacion"],
        "NombreCompleto": trabajador["NombreCompleto"],
        "IdCargo": cargo["IdCargo"] if cargo else None,
        "NombreCargo": cargo["NombreCargo"] if cargo else None,
        "TipoClasificacion": None,
        "OrigenConfiguracion": "SIN_CONFIGURACION",
        "IdPerfilPazSalvoOperaciones": None,
        "NombrePerfilPazSalvo": None,
        "CodigoPerfilPazSalvo": None,
        "Responsabilidades": [],
        "Elementos": [],
        "ValidacionesPerfil": [],
        "ElementosPerfil": [],
    }
    if cargo is None:
        return {"success": True, "data": data}

    id_cargo = cargo["IdCargo"]
    perfil = _obtener_responsabilidades_perfil_paz_salvo(db, id_cargo)
    data.update({
        "IdPerfilPazSalvoOperaciones": perfil["IdPerfilPazSalvoOperaciones"],
        "NombrePerfilPazSalvo": perfil["NombrePerfilPazSalvo"],
        "Responsabilidades": perfil["Responsabilidades"],
    })
    perfil_row = db.execute(text('''
        SELECT p."CodigoPerfil"
        FROM public."CargoPerfilPazSalvoOperaciones" cp
        JOIN public."PerfilPazSalvoOperaciones" p
          ON p."IdPerfilPazSalvoOperaciones" = cp."IdPerfilPazSalvoOperaciones"
        WHERE cp."IdCargo" = :id_cargo
          AND COALESCE(cp."Activo", true) = true
          AND COALESCE(p."Activo", true) = true
        LIMIT 1
    '''), {"id_cargo": id_cargo}).mappings().first()
    codigo_perfil = str(perfil_row["CodigoPerfil"] or "").strip().upper() if perfil_row else ""
    data["CodigoPerfilPazSalvo"] = codigo_perfil or None
    data["ValidacionesPerfil"] = _catalogo_validaciones_perfil(codigo_perfil) if codigo_perfil else []

    # Catálogo adicional por perfil: solo lectura. No reemplaza "Elementos"
    # ni modifica la persistencia del Paz y Salvo existente.
    if perfil["IdPerfilPazSalvoOperaciones"] is not None:
        filas_perfil = db.execute(text('''
            SELECT "IdPerfilElementoPazSalvoOperaciones" AS "IdConfiguracionElemento",
                   "CodigoElemento", "NombreElemento", "TipoGestion", "Obligatorio"
            FROM public."PerfilElementoPazSalvoOperaciones"
            WHERE "IdPerfilPazSalvoOperaciones" = :id_perfil
              AND "Activo" = true
            ORDER BY "IdPerfilElementoPazSalvoOperaciones"
        '''), {"id_perfil": perfil["IdPerfilPazSalvoOperaciones"]}).mappings().all()
        data["ElementosPerfil"] = [dict(fila) for fila in filas_perfil]

    # Compatibilidad: conservar los elementos específicos ya parametrizados.
    filas_cargo = db.execute(text('''
        SELECT "IdCargoElementoPazSalvo" AS "IdConfiguracionElemento",
               "CodigoElemento", "NombreElemento"
        FROM public."CargoElementoPazSalvo"
        WHERE "IdCargo" = :id_cargo AND COALESCE("Activo", true) = true
        ORDER BY "IdCargoElementoPazSalvo"
    '''), {"id_cargo": id_cargo}).mappings().all()
    if filas_cargo:
        data["Elementos"] = [dict(fila) for fila in filas_cargo]
        data["OrigenConfiguracion"] = "CARGO"
    else:
        clasificacion = db.execute(text('''
            SELECT "TipoClasificacion" FROM public."CargoClasificacionPazSalvo"
            WHERE "IdCargo" = :id_cargo AND COALESCE("Activo", true) = true
            LIMIT 1
        '''), {"id_cargo": id_cargo}).mappings().first()
        if clasificacion:
            tipo = str(clasificacion["TipoClasificacion"] or "").strip().upper()
            data["TipoClasificacion"] = tipo
            filas = db.execute(text('''
                SELECT "IdClasificacionElementoPazSalvo" AS "IdConfiguracionElemento",
                       "CodigoElemento", "NombreElemento"
                FROM public."ClasificacionElementoPazSalvo"
                WHERE "TipoClasificacion" = :tipo AND COALESCE("Activo", true) = true
                ORDER BY "IdClasificacionElementoPazSalvo"
            '''), {"tipo": tipo}).mappings().all()
            if filas:
                data["Elementos"] = [dict(fila) for fila in filas]
                data["OrigenConfiguracion"] = "CLASIFICACION"

    # Si la clasificación antigua está vacía, mostrar los campos del perfil.
    # ID None indica que aún NO hay parametrización individual persistida.
    # No se inventan IDs que puedan confundirse con registros de la BD.
    if not data["Elementos"] and data["ValidacionesPerfil"]:
        data["Elementos"] = [
            {"IdConfiguracionElemento": None,
             "CodigoElemento": v["CodigoElemento"],
             "NombreElemento": v["NombreElemento"],
             "TipoValidacion": v["TipoValidacion"],
             "Obligatorio": False}
            for v in data["ValidacionesPerfil"]
        ]
        data["OrigenConfiguracion"] = "PERFIL"
    return {"success": True, "data": data}


@router.get("/usuario-actual")
def obtener_usuario_actual_operaciones_retiros(
    current=Depends(require_operaciones_retiros),
):
    """
    Devuelve el nombre completo del usuario autenticado que está
    diligenciando el Paz y Salvo.

    Para los usuarios corporativos actuales, NombreUsuario contiene
    el nombre completo y Usuario contiene el login de ingreso.
    """
    usuario = current.get("usuario")

    nombre_completo = str(
        getattr(usuario, "NombreUsuario", "") or ""
    ).strip()

    login_usuario = str(
        getattr(usuario, "Usuario", "") or ""
    ).strip()

    if not nombre_completo:
        nombre_completo = login_usuario

    return {
        "success": True,
        "data": {
            "IdUsuario": (
                str(getattr(usuario, "IdUsuario", ""))
                if getattr(usuario, "IdUsuario", None) is not None
                else None
            ),
            "NombreCompleto": nombre_completo,
            "Usuario": login_usuario,
        },
    }


@router.get("/clientes")
def listar_clientes_operaciones_retiros(
    db: Session = Depends(get_db),
    current=Depends(require_operaciones_retiros),
):
    """
    Devuelve el catálogo de clientes registrado en la base de datos.

    Este catálogo se utiliza en el formulario de Paz y Salvo de Operaciones
    para permitir validar o corregir el cliente antes de enviar el retiro.
    """
    query = text("""
        SELECT
            c."IdCliente",
            c."Nombre" AS "NombreCliente"
        FROM public."Cliente" c
        WHERE TRIM(COALESCE(c."Nombre", '')) <> ''
        ORDER BY c."Nombre" ASC;
    """)

    rows = db.execute(query).mappings().all()

    return {
        "success": True,
        "data": [
            {
                "IdCliente": int(row["IdCliente"]),
                "NombreCliente": str(row["NombreCliente"]).strip(),
            }
            for row in rows
        ],
    }


@router.get("/clientes/trabajador/{id_registro_personal}")
def obtener_cliente_actual_operaciones_retiros(
    id_registro_personal: int,
    db: Session = Depends(get_db),
    current=Depends(require_operaciones_retiros),
):
    """
    Devuelve el último cliente asignado al trabajador según
    AsignacionCargoCliente.
    """
    id_cliente = _obtener_cliente_actual(
        db=db,
        id_registro_personal=id_registro_personal,
    )

    if id_cliente is None:
        return {
            "success": True,
            "data": None,
        }

    cliente = _validar_cliente(
        db=db,
        id_cliente=id_cliente,
    )

    return {
        "success": True,
        "data": {
            "IdCliente": int(cliente["IdCliente"]),
            "NombreCliente": str(cliente["NombreCliente"] or "").strip(),
        },
    }



# ============================================================
# PROCESOS ABIERTOS - OPERACIONES
# ============================================================
@router.get("/procesos-abiertos")
def listar_procesos_abiertos_operaciones(
    db: Session = Depends(get_db),
    current=Depends(require_operaciones_retiros),
):
    """
    Lista únicamente los retiros que todavía están pendientes en Operaciones.

    Este endpoint es de solo consulta:
    - No inserta.
    - No actualiza.
    - No elimina.
    - No cambia el estado global del trabajador.
    - No envía información a Relaciones Laborales.

    Se toma el Paz y Salvo más reciente asociado al retiro y, si existe,
    el RQ activo más reciente del mismo retiro.
    """
    rows = db.execute(
        text("""
            SELECT
                rl."IdRetiroLaboral",
                rl."IdRegistroPersonal",
                rp."NumeroIdentificacion",
                TRIM(
                    COALESCE(rp."Nombres", '') || ' ' ||
                    COALESCE(rp."Apellidos", '')
                ) AS "NombreCompleto",
                rl."IdCliente",
                c."Nombre" AS "NombreCliente",
                rl."FechaProceso",
                rl."FechaCreacion" AS "FechaApertura",
                rl."FechaActualizacion",
                rl."EstadoCasoRRLL",

                ps."IdPazYSalvo",
                psd."EstadoPazYSalvo",

                rq."IdRQOperaciones",
                rq."TipoNotificacion",
                rq."RequiereReemplazo",
                rq."EstadoRQ",
                rq."EnviadoRRLL",
                rq."FechaRegistro" AS "FechaRegistroRQ"

            FROM public."RetiroLaboral" rl

            INNER JOIN public."RegistroPersonal" rp
                ON rp."IdRegistroPersonal" = rl."IdRegistroPersonal"

            LEFT JOIN public."Cliente" c
                ON c."IdCliente" = rl."IdCliente"

            LEFT JOIN LATERAL (
                SELECT
                    p."IdPazYSalvo"
                FROM public."PazYSalvoOperaciones" p
                WHERE p."IdRetiroLaboral" = rl."IdRetiroLaboral"
                ORDER BY p."IdPazYSalvo" DESC
                LIMIT 1
            ) ps ON true

            LEFT JOIN LATERAL (
                SELECT
                    d."EstadoPazYSalvo"
                FROM public."PazYSalvoOperacionesDetalle" d
                WHERE d."IdPazYSalvo" = ps."IdPazYSalvo"
                ORDER BY d."IdPazYSalvoDetalle" DESC
                LIMIT 1
            ) psd ON true

            LEFT JOIN LATERAL (
                SELECT
                    rqo."IdRQOperaciones",
                    rqo."TipoNotificacion",
                    rqo."RequiereReemplazo",
                    rqo."EstadoRQ",
                    rqo."EnviadoRRLL",
                    rqo."FechaRegistro"
                FROM public."RQOperaciones" rqo
                WHERE rqo."IdRetiroLaboral" = rl."IdRetiroLaboral"
                  AND COALESCE(rqo."Activo", true) = true
                ORDER BY rqo."IdRQOperaciones" DESC
                LIMIT 1
            ) rq ON true

            WHERE UPPER(TRIM(COALESCE(rl."EstadoCasoRRLL", '')))
                = 'PENDIENTE_OPERACIONES'
              AND COALESCE(rl."Activo", true) = true

            ORDER BY
                COALESCE(rl."FechaActualizacion", rl."FechaCreacion") DESC,
                rl."IdRetiroLaboral" DESC;
        """)
    ).mappings().all()

    data = []

    for row in rows:
        data.append({
            "IdRetiroLaboral": int(row["IdRetiroLaboral"]),
            "IdRegistroPersonal": int(row["IdRegistroPersonal"]),
            "NumeroIdentificacion": row["NumeroIdentificacion"],
            "NombreCompleto": row["NombreCompleto"],
            "IdCliente": (
                int(row["IdCliente"])
                if row["IdCliente"] is not None
                else None
            ),
            "NombreCliente": row["NombreCliente"],
            "FechaProceso": row["FechaProceso"],
            "FechaApertura": row["FechaApertura"],
            "FechaActualizacion": row["FechaActualizacion"],
            "EstadoCasoRRLL": row["EstadoCasoRRLL"],
            "IdPazYSalvo": (
                int(row["IdPazYSalvo"])
                if row["IdPazYSalvo"] is not None
                else None
            ),
            "EstadoPazYSalvo": row["EstadoPazYSalvo"],
            "IdRQOperaciones": (
                int(row["IdRQOperaciones"])
                if row["IdRQOperaciones"] is not None
                else None
            ),
            "TipoNotificacion": row["TipoNotificacion"],
            "RequiereReemplazo": (
                bool(row["RequiereReemplazo"])
                if row["RequiereReemplazo"] is not None
                else None
            ),
            "EstadoRQ": row["EstadoRQ"],
            "EnviadoRRLL": (
                bool(row["EnviadoRRLL"])
                if row["EnviadoRRLL"] is not None
                else False
            ),
            "FechaRegistroRQ": row["FechaRegistroRQ"],
        })

    return {
        "success": True,
        "total": len(data),
        "data": data,
    }



# ============================================================
# CONTINUAR PROCESO PENDIENTE - SOLO CONSULTA
# ============================================================
@router.get("/proceso/{id_retiro_laboral}/continuar")
def obtener_proceso_abierto_para_continuar(
    id_retiro_laboral: int,
    db: Session = Depends(get_db),
    current=Depends(require_operaciones_retiros),
):
    """
    Recupera un retiro que sigue pendiente en Operaciones para continuar
    diligenciándolo sin crear un nuevo RetiroLaboral, Paz y Salvo o RQ.

    SOLO CONSULTA:
    - No inserta.
    - No actualiza.
    - No elimina.
    - No cambia EstadoCasoRRLL.
    - No cambia IdEstadoProceso.
    - No envía el caso a RRLL.
    """

    proceso = db.execute(
        text("""
            SELECT
                rl."IdRetiroLaboral",
                rl."IdRegistroPersonal",
                rl."IdCliente",
                rl."IdMotivoRetiro",
                rl."FechaProceso",
                rl."FechaRetiro",
                rl."FechaEnvioOperaciones",
                rl."ObservacionGeneral",
                rl."EstadoCasoRRLL",
                rl."Activo" AS "RetiroActivo",
                rl."FechaCreacion" AS "FechaCreacionRetiro",
                rl."FechaActualizacion" AS "FechaActualizacionRetiro",

                rp."NumeroIdentificacion",
                rp."IdEstadoProceso",
                TRIM(
                    COALESCE(rp."Nombres", '') || ' ' ||
                    COALESCE(rp."Apellidos", '')
                ) AS "NombreCompleto",

                c."Nombre" AS "NombreCliente",
                mr."Nombre" AS "NombreMotivoRetiro",

                acc."IdCargo",
                ca."NombreCargo",

                ps."IdPazYSalvo",
                ps."FechaUltimoDiaLaborado",
                ps."Observacion" AS "ObservacionPazYSalvo",
                ps."UsuarioCreacion" AS "UsuarioCreacionPazYSalvo",
                ps."FechaCreacion" AS "FechaCreacionPazYSalvo",
                ps."FechaCarga" AS "FechaCargaPazYSalvo",

                psd."IdPazYSalvoDetalle",
                psd."FechaHoraInicioDiligenciamiento",
                psd."ElaboradoPor",
                psd."DescripcionMotivoRetiro",
                psd."Locker",
                psd."Llaves",
                psd."EntregaHerramientas",
                psd."TarjetaControlAcceso",
                psd."EntregaGuantes",
                psd."EntregaMonogafas",
                psd."EntregaPeto",
                psd."ObservacionesEntrega",
                psd."AplicaDescuento",
                psd."ValorDescuento",
                psd."NovedadesNomina",
                psd."PendienteEntregaUniforme",
                psd."UniformePatogeno",
                psd."Botas",
                psd."Zapatos",
                psd."Chaqueta",
                psd."CarnetAlpArl",
                psd."PendientePagoVacunas",
                psd."UsuariosClavesDispositivos",
                psd."CorreoSupervisora",
                psd."EstadoPazYSalvo",
                psd."FechaCreacion" AS "FechaCreacionDetalle",
                psd."FechaActualizacion" AS "FechaActualizacionDetalle"

            FROM public."RetiroLaboral" rl

            INNER JOIN public."RegistroPersonal" rp
                ON rp."IdRegistroPersonal" = rl."IdRegistroPersonal"

            LEFT JOIN public."Cliente" c
                ON c."IdCliente" = rl."IdCliente"

            LEFT JOIN public."MotivoRetiro" mr
                ON mr."IdMotivoRetiro" = rl."IdMotivoRetiro"

            LEFT JOIN LATERAL (
                SELECT
                    x."IdCargo"
                FROM public."AsignacionCargoCliente" x
                WHERE x."IdRegistroPersonal" = rl."IdRegistroPersonal"
                  AND x."IdCargo" IS NOT NULL
                ORDER BY
                    x."FechaActualizacion" DESC NULLS LAST,
                    x."FechaCreacion" DESC NULLS LAST,
                    x."IdAsignacionCargoCliente" DESC
                LIMIT 1
            ) acc ON true

            LEFT JOIN public."Cargo" ca
                ON ca."IdCargo" = acc."IdCargo"

            LEFT JOIN LATERAL (
                SELECT
                    p.*
                FROM public."PazYSalvoOperaciones" p
                WHERE p."IdRetiroLaboral" = rl."IdRetiroLaboral"
                ORDER BY p."IdPazYSalvo" DESC
                LIMIT 1
            ) ps ON true

            LEFT JOIN LATERAL (
                SELECT
                    d.*
                FROM public."PazYSalvoOperacionesDetalle" d
                WHERE d."IdPazYSalvo" = ps."IdPazYSalvo"
                ORDER BY d."IdPazYSalvoDetalle" DESC
                LIMIT 1
            ) psd ON true

            WHERE rl."IdRetiroLaboral" = :id_retiro_laboral
              AND COALESCE(rl."Activo", true) = true
              AND UPPER(TRIM(COALESCE(rl."EstadoCasoRRLL", '')))
                  = 'PENDIENTE_OPERACIONES'
            LIMIT 1;
        """),
        {"id_retiro_laboral": id_retiro_laboral},
    ).mappings().first()

    if not proceso:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=(
                "No se encontró un proceso activo pendiente en Operaciones "
                f"con IdRetiroLaboral={id_retiro_laboral}."
            ),
        )

    id_paz_y_salvo = proceso["IdPazYSalvo"]

    evidencias = []

    if id_paz_y_salvo is not None:
        rows_evidencias = db.execute(
            text("""
                SELECT
                    "IdPazYSalvoEvidencia",
                    "IdPazYSalvo",
                    "IdRetiroLaboral",
                    "TipoEvidencia",
                    "NombreArchivoOriginal",
                    "ExtensionArchivo",
                    "MimeType",
                    "PesoArchivo",
                    "Observacion",
                    "FechaCreacion",
                    "FechaActualizacion"
                FROM public."PazYSalvoOperacionesEvidencia"
                WHERE "IdRetiroLaboral" = :id_retiro_laboral
                  AND "IdPazYSalvo" = :id_paz_y_salvo
                  AND COALESCE("Activo", true) = true
                  AND COALESCE("Eliminado", false) = false
                ORDER BY "IdPazYSalvoEvidencia" ASC;
            """),
            {
                "id_retiro_laboral": id_retiro_laboral,
                "id_paz_y_salvo": id_paz_y_salvo,
            },
        ).mappings().all()

        evidencias = [
            {
                "IdPazYSalvoEvidencia": int(row["IdPazYSalvoEvidencia"]),
                "IdPazYSalvo": int(row["IdPazYSalvo"]),
                "IdRetiroLaboral": int(row["IdRetiroLaboral"]),
                "TipoEvidencia": row["TipoEvidencia"],
                "NombreArchivoOriginal": row["NombreArchivoOriginal"],
                "ExtensionArchivo": row["ExtensionArchivo"],
                "MimeType": row["MimeType"],
                "PesoArchivo": row["PesoArchivo"],
                "Observacion": row["Observacion"],
                "FechaCreacion": row["FechaCreacion"],
                "FechaActualizacion": row["FechaActualizacion"],
            }
            for row in rows_evidencias
        ]

    pdf_oficial = db.execute(
        text("""
            SELECT
                "IdRetiroLaboralAdjunto",
                "IdTipoDocumentoRetiro",
                "NombreArchivoOriginal",
                "ExtensionArchivo",
                "MimeType",
                "PesoArchivo",
                "Observacion",
                "OrigenArchivo",
                "FechaCreacion"
            FROM public."RetiroLaboralAdjunto"
            WHERE "IdRetiroLaboral" = :id_retiro_laboral
              AND "IdTipoDocumentoRetiro" = :id_tipo_documento
              AND COALESCE("Activo", true) = true
              AND COALESCE("Eliminado", false) = false
            ORDER BY "IdRetiroLaboralAdjunto" DESC
            LIMIT 1;
        """),
        {
            "id_retiro_laboral": id_retiro_laboral,
            "id_tipo_documento": ID_TIPO_DOCUMENTO_PAZ_Y_SALVO,
        },
    ).mappings().first()

    data = {
        "Retiro": {
            "IdRetiroLaboral": int(proceso["IdRetiroLaboral"]),
            "IdRegistroPersonal": int(proceso["IdRegistroPersonal"]),
            "IdCliente": (
                int(proceso["IdCliente"])
                if proceso["IdCliente"] is not None
                else None
            ),
            "IdMotivoRetiro": (
                int(proceso["IdMotivoRetiro"])
                if proceso["IdMotivoRetiro"] is not None
                else None
            ),
            "NombreMotivoRetiro": proceso["NombreMotivoRetiro"],
            "FechaProceso": proceso["FechaProceso"],
            "FechaRetiro": proceso["FechaRetiro"],
            "FechaEnvioOperaciones": proceso["FechaEnvioOperaciones"],
            "ObservacionGeneral": proceso["ObservacionGeneral"],
            "EstadoCasoRRLL": proceso["EstadoCasoRRLL"],
            "Activo": bool(proceso["RetiroActivo"]),
            "FechaCreacion": proceso["FechaCreacionRetiro"],
            "FechaActualizacion": proceso["FechaActualizacionRetiro"],
        },
        "Trabajador": {
            "IdRegistroPersonal": int(proceso["IdRegistroPersonal"]),
            "NumeroIdentificacion": proceso["NumeroIdentificacion"],
            "NombreCompleto": proceso["NombreCompleto"],
            "IdEstadoProceso": (
                int(proceso["IdEstadoProceso"])
                if proceso["IdEstadoProceso"] is not None
                else None
            ),
            "IdCargo": (
                int(proceso["IdCargo"])
                if proceso["IdCargo"] is not None
                else None
            ),
            "NombreCargo": proceso["NombreCargo"],
            "IdCliente": (
                int(proceso["IdCliente"])
                if proceso["IdCliente"] is not None
                else None
            ),
            "NombreCliente": proceso["NombreCliente"],
        },
        "PazYSalvo": None,
        "Evidencias": evidencias,
        "PdfOficial": None,
    }

    if id_paz_y_salvo is not None:
        data["PazYSalvo"] = {
            "IdPazYSalvo": int(proceso["IdPazYSalvo"]),
            "IdPazYSalvoDetalle": (
                int(proceso["IdPazYSalvoDetalle"])
                if proceso["IdPazYSalvoDetalle"] is not None
                else None
            ),
            "FechaUltimoDiaLaborado": proceso["FechaUltimoDiaLaborado"],
            "Observacion": proceso["ObservacionPazYSalvo"],
            "UsuarioCreacion": proceso["UsuarioCreacionPazYSalvo"],
            "FechaCreacion": proceso["FechaCreacionPazYSalvo"],
            "FechaCarga": proceso["FechaCargaPazYSalvo"],
            "FechaHoraInicioDiligenciamiento": (
                proceso["FechaHoraInicioDiligenciamiento"]
            ),
            "ElaboradoPor": proceso["ElaboradoPor"],
            "DescripcionMotivoRetiro": proceso["DescripcionMotivoRetiro"],
            "Locker": proceso["Locker"],
            "Llaves": proceso["Llaves"],
            "EntregaHerramientas": proceso["EntregaHerramientas"],
            "TarjetaControlAcceso": proceso["TarjetaControlAcceso"],
            "EntregaGuantes": proceso["EntregaGuantes"],
            "EntregaMonogafas": proceso["EntregaMonogafas"],
            "EntregaPeto": proceso["EntregaPeto"],
            "ObservacionesEntrega": proceso["ObservacionesEntrega"],
            "AplicaDescuento": proceso["AplicaDescuento"],
            "ValorDescuento": proceso["ValorDescuento"],
            "NovedadesNomina": proceso["NovedadesNomina"],
            "PendienteEntregaUniforme": proceso["PendienteEntregaUniforme"],
            "UniformePatogeno": proceso["UniformePatogeno"],
            "Botas": proceso["Botas"],
            "Zapatos": proceso["Zapatos"],
            "Chaqueta": proceso["Chaqueta"],
            "CarnetAlpArl": proceso["CarnetAlpArl"],
            "PendientePagoVacunas": proceso["PendientePagoVacunas"],
            "UsuariosClavesDispositivos": (
                proceso["UsuariosClavesDispositivos"]
            ),
            "CorreoSupervisora": proceso["CorreoSupervisora"],
            "EstadoPazYSalvo": proceso["EstadoPazYSalvo"],
            "FechaCreacionDetalle": proceso["FechaCreacionDetalle"],
            "FechaActualizacionDetalle": proceso["FechaActualizacionDetalle"],
        }

    if pdf_oficial:
        data["PdfOficial"] = {
            "IdRetiroLaboralAdjunto": int(
                pdf_oficial["IdRetiroLaboralAdjunto"]
            ),
            "IdTipoDocumentoRetiro": int(
                pdf_oficial["IdTipoDocumentoRetiro"]
            ),
            "NombreArchivoOriginal": pdf_oficial["NombreArchivoOriginal"],
            "ExtensionArchivo": pdf_oficial["ExtensionArchivo"],
            "MimeType": pdf_oficial["MimeType"],
            "PesoArchivo": pdf_oficial["PesoArchivo"],
            "Observacion": pdf_oficial["Observacion"],
            "OrigenArchivo": pdf_oficial["OrigenArchivo"],
            "FechaCreacion": pdf_oficial["FechaCreacion"],
        }

    return {
        "success": True,
        "data": data,
    }



def _guardar_bloques_perfil_en_transaccion(db, current, id_paz_y_salvo: int, raw: str | None):
    """Guarda bloques opcionales sin commit; el guardado principal controla la transacción."""
    if not raw:
        return
    try:
        bloques = json.loads(raw)
        if not isinstance(bloques, dict):
            raise ValueError("Se esperaba un objeto JSON")
        for clave in ("ElementosPerfil", "Validaciones", "Responsabilidades"):
            if clave in bloques and not isinstance(bloques[clave], list):
                raise ValueError(f"{clave} debe ser una lista")
    except (ValueError, TypeError) as exc:
        raise HTTPException(status_code=400, detail=f"BloquesPerfilJSON inválido: {exc}") from exc
    if bloques.get("ElementosPerfil"):
        guardar_elementos_perfil_paz_salvo(
            id_paz_y_salvo, GuardarElementosPerfilPazSalvo(ElementosPerfil=bloques["ElementosPerfil"]),
            db=db, current=current, _commit=False,
        )
    if bloques.get("Validaciones"):
        guardar_validaciones_paz_salvo(
            id_paz_y_salvo, GuardarValidacionesPazSalvo(Validaciones=bloques["Validaciones"]),
            db=db, current=current, _commit=False,
        )
    if bloques.get("Responsabilidades"):
        guardar_responsabilidades_paz_salvo(
            id_paz_y_salvo, GuardarResponsabilidadesPazSalvo(Responsabilidades=bloques["Responsabilidades"]),
            db=db, current=current, _commit=False,
        )


# ============================================================
# ACTUALIZAR PROCESO PENDIENTE - PAZ Y SALVO EXISTENTE
# ============================================================
@router.put("/proceso/{id_retiro_laboral}/paz-salvo")
async def actualizar_paz_salvo_proceso_pendiente(
    id_retiro_laboral: int,
    IdPazYSalvo: int = Form(...),
    IdPazYSalvoDetalle: int = Form(...),
    IdCliente: int = Form(...),
    IdMotivoRetiro: int = Form(...),
    FechaUltimoDiaLaborado: date = Form(...),
    UsuarioActualizacion: str = Form("operaciones"),
    Observacion: str | None = Form(None),

    FechaHoraInicioDiligenciamiento: datetime = Form(...),
    ElaboradoPor: str = Form(...),
    DescripcionMotivoRetiro: str = Form(...),

    Locker: str = Form("NO APLICA"),
    Llaves: str = Form("NO APLICA"),
    EntregaHerramientas: str = Form("NO APLICA"),
    TarjetaControlAcceso: str = Form("NO APLICA"),

    EntregaGuantes: str = Form("NO APLICA"),
    EntregaMonogafas: str = Form("NO APLICA"),
    EntregaPeto: str = Form("NO APLICA"),
    ObservacionesEntrega: str = Form(""),

    AplicaDescuento: str = Form(...),
    ValorDescuento: Decimal | None = Form(None),
    NovedadesNomina: str | None = Form(None),

    PendienteEntregaUniforme: str = Form("NO APLICA"),
    UniformePatogeno: str = Form("NO APLICA"),
    Botas: str = Form("NO APLICA"),
    Zapatos: str = Form("NO APLICA"),
    Chaqueta: str = Form("NO APLICA"),
    CarnetAlpArl: str = Form("NO APLICA"),
    PendientePagoVacunas: str = Form("NO APLICA"),

    UsuariosClavesDispositivos: str | None = Form(None),
    CorreoSupervisora: str | None = Form(None),
    EstadoPazYSalvo: str = Form(...),
    BloquesPerfilJSON: str | None = Form(None),

    # Compatibilidad con un PDF manual.
    archivo: UploadFile | None = File(None),

    # Nuevas evidencias opcionales. Las evidencias ya existentes se conservan.
    novedadesNominaArchivo: list[UploadFile] | None = File(None),
    formatoDescuentoVacunasArchivo: UploadFile | None = File(None),
    fotoCarnetAccesoArchivo: UploadFile | None = File(None),
    fotoListadoHerramientasArchivo: UploadFile | None = File(None),
    fotoPlanillaNominaArchivo: UploadFile | None = File(None),

    db: Session = Depends(get_db),
    current=Depends(require_operaciones_retiros),
):
    """
    Actualiza el MISMO proceso pendiente de Operaciones.

    Reglas de seguridad:
    - No crea un nuevo RetiroLaboral.
    - No crea un nuevo PazYSalvoOperaciones.
    - No crea un nuevo PazYSalvoOperacionesDetalle.
    - No crea un nuevo RQOperaciones.
    - RetiroLaboral debe seguir en PENDIENTE_OPERACIONES.
    - RegistroPersonal.IdEstadoProceso no se modifica aquí.
    - FechaEnvioOperaciones no se modifica aquí.
    - Si el Paz y Salvo queda CERRADO y ya existe RQ, el mismo RQ pasa
      a LISTO_PARA_ENVIO.
    - Si queda ABIERTO y ya existe RQ, el mismo RQ queda
      PENDIENTE_OPERACIONES.
    - El PDF oficial se regenera. La versión anterior se inactiva y se
      conserva para trazabilidad.
    """

    ruta_pdf_nueva: Path | None = None
    rutas_evidencias_creadas: list[Path] = []
    ids_evidencias_nuevas: list[int] = []
    contenido_pdf: bytes | None = None
    nombre_original_pdf: str | None = None

    archivos_para_cerrar: list[UploadFile] = []

    if archivo is not None:
        archivos_para_cerrar.append(archivo)

    if novedadesNominaArchivo:
        archivos_para_cerrar.extend(novedadesNominaArchivo)

    for archivo_opcional in [
        formatoDescuentoVacunasArchivo,
        fotoCarnetAccesoArchivo,
        fotoListadoHerramientasArchivo,
        fotoPlanillaNominaArchivo,
    ]:
        if archivo_opcional is not None:
            archivos_para_cerrar.append(archivo_opcional)

    try:
        usuario = _normalizar_usuario(UsuarioActualizacion)
        observacion = _normalizar_texto_opcional(Observacion)

        elaborado_por = _normalizar_texto_requerido(
            ElaboradoPor,
            "ElaboradoPor",
        )
        descripcion_motivo = _normalizar_texto_requerido(
            DescripcionMotivoRetiro,
            "DescripcionMotivoRetiro",
        )

        locker = _normalizar_opcion(
            Locker,
            "Locker",
            OPCIONES_ENTREGA_GENERAL,
        )
        llaves = _normalizar_opcion(
            Llaves,
            "Llaves",
            OPCIONES_ENTREGA_GENERAL,
        )
        entrega_herramientas = _normalizar_opcion(
            EntregaHerramientas,
            "EntregaHerramientas",
            OPCIONES_ENTREGA_GENERAL,
        )
        tarjeta_control_acceso = _normalizar_opcion(
            TarjetaControlAcceso,
            "TarjetaControlAcceso",
            OPCIONES_ENTREGA_GENERAL,
        )

        entrega_guantes = _normalizar_opcion(
            EntregaGuantes,
            "EntregaGuantes",
            OPCIONES_CUMPLIMIENTO,
        )
        entrega_monogafas = _normalizar_opcion(
            EntregaMonogafas,
            "EntregaMonogafas",
            OPCIONES_CUMPLIMIENTO,
        )
        entrega_peto = _normalizar_opcion(
            EntregaPeto,
            "EntregaPeto",
            OPCIONES_ENTREGA_GENERAL,
        )
        observaciones_entrega = _normalizar_texto_opcional(ObservacionesEntrega) or ""

        aplica_descuento = _normalizar_opcion(
            AplicaDescuento,
            "AplicaDescuento",
            OPCIONES_SI_NO,
        )
        valor_descuento = _validar_valor_descuento(
            aplica_descuento,
            ValorDescuento,
        )
        # La observación de nómina es opcional para todos los perfiles.
        novedades_nomina = _normalizar_texto_opcional(NovedadesNomina)

        pendiente_entrega_uniforme = _normalizar_opcion(
            PendienteEntregaUniforme,
            "PendienteEntregaUniforme",
            OPCIONES_SI_NO_HISTORICO,
        )
        uniforme_patogeno = _normalizar_opcion(
            UniformePatogeno,
            "UniformePatogeno",
            OPCIONES_SI_NO_HISTORICO,
        )
        botas = _normalizar_opcion(Botas, "Botas", OPCIONES_SI_NO_HISTORICO)
        zapatos = _normalizar_opcion(Zapatos, "Zapatos", OPCIONES_SI_NO_HISTORICO)
        chaqueta = _normalizar_opcion(Chaqueta, "Chaqueta", OPCIONES_SI_NO_HISTORICO)
        carnet_alp_arl = _normalizar_opcion(
            CarnetAlpArl,
            "CarnetAlpArl",
            OPCIONES_SI_NO_HISTORICO,
        )
        pendiente_pago_vacunas = _normalizar_opcion(
            PendientePagoVacunas,
            "PendientePagoVacunas",
            OPCIONES_SI_NO_HISTORICO,
        )

        # QA: estos siete campos historicos son VARCHAR(2) en PostgreSQL.
        # El formulario nuevo no los diligencia; "NO APLICA" no cabe y tampoco
        # representa una respuesta del trabajador. Guardar NULL, sin alterar
        # los valores historicos validos SI/NO que si se reciban.
        pendiente_entrega_uniforme = (None if pendiente_entrega_uniforme == "NO APLICA" else pendiente_entrega_uniforme)
        uniforme_patogeno = (None if uniforme_patogeno == "NO APLICA" else uniforme_patogeno)
        botas = (None if botas == "NO APLICA" else botas)
        zapatos = (None if zapatos == "NO APLICA" else zapatos)
        chaqueta = (None if chaqueta == "NO APLICA" else chaqueta)
        carnet_alp_arl = (None if carnet_alp_arl == "NO APLICA" else carnet_alp_arl)
        pendiente_pago_vacunas = (None if pendiente_pago_vacunas == "NO APLICA" else pendiente_pago_vacunas)

        usuarios_claves_dispositivos = _normalizar_texto_opcional(
            UsuariosClavesDispositivos
        )
        correo_supervisora = _normalizar_texto_opcional(CorreoSupervisora)
        estado_paz_y_salvo = _normalizar_opcion(
            EstadoPazYSalvo,
            "EstadoPazYSalvo",
            OPCIONES_ESTADO_PAZ_SALVO,
        )

        # ============================================================
        # VALIDAR QUE LOS IDS CORRESPONDEN AL MISMO PROCESO PENDIENTE
        # ============================================================
        contexto = db.execute(
            text("""
                SELECT
                    rl."IdRetiroLaboral",
                    rl."IdRegistroPersonal",
                    rl."IdCliente",
                    rl."IdMotivoRetiro",
                    rl."FechaEnvioOperaciones",
                    rl."EstadoCasoRRLL",
                    rl."Activo",
                    rp."IdEstadoProceso",
                    rp."NumeroIdentificacion",
                    TRIM(
                        COALESCE(rp."Nombres", '') || ' ' ||
                        COALESCE(rp."Apellidos", '')
                    ) AS "NombreCompleto",
                    ps."IdPazYSalvo",
                    psd."IdPazYSalvoDetalle",
                    psd."EstadoPazYSalvo"
                FROM public."RetiroLaboral" rl
                INNER JOIN public."RegistroPersonal" rp
                    ON rp."IdRegistroPersonal" = rl."IdRegistroPersonal"
                INNER JOIN public."PazYSalvoOperaciones" ps
                    ON ps."IdRetiroLaboral" = rl."IdRetiroLaboral"
                   AND ps."IdPazYSalvo" = :id_paz_y_salvo
                INNER JOIN public."PazYSalvoOperacionesDetalle" psd
                    ON psd."IdPazYSalvo" = ps."IdPazYSalvo"
                   AND psd."IdPazYSalvoDetalle" = :id_paz_y_salvo_detalle
                WHERE rl."IdRetiroLaboral" = :id_retiro_laboral
                  AND COALESCE(rl."Activo", true) = true
                LIMIT 1
                FOR UPDATE OF rl, ps, psd;
            """),
            {
                "id_retiro_laboral": id_retiro_laboral,
                "id_paz_y_salvo": IdPazYSalvo,
                "id_paz_y_salvo_detalle": IdPazYSalvoDetalle,
            },
        ).mappings().first()

        if not contexto:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=(
                    "No se encontró el retiro pendiente con el Paz y Salvo "
                    "y detalle indicados. No se realizó ninguna actualización."
                ),
            )

        estado_caso_rrll = str(
            contexto["EstadoCasoRRLL"] or ""
        ).strip().upper()

        if estado_caso_rrll != "PENDIENTE_OPERACIONES":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    "El retiro ya no está pendiente en Operaciones y no puede "
                    "modificarse desde esta vista."
                ),
            )

        if contexto["FechaEnvioOperaciones"] is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    "El retiro ya registra fecha de envío desde Operaciones. "
                    "No se permite modificar el Paz y Salvo pendiente."
                ),
            )

        if int(contexto["IdEstadoProceso"] or 0) != ID_ESTADO_CONTRATADO:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    "El trabajador ya no se encuentra en estado CONTRATADO. "
                    "No se modificó el proceso pendiente."
                ),
            )

        cliente = _validar_cliente(
            db=db,
            id_cliente=IdCliente,
        )
        motivo = _validar_motivo_retiro(
            db=db,
            id_motivo_retiro=IdMotivoRetiro,
        )

        # Si existe RQ, debe ser el mismo RQ activo y aún no enviado.
        rq_existente = db.execute(
            text("""
                SELECT
                    "IdRQOperaciones",
                    "IdPazYSalvo",
                    "EnviadoRRLL",
                    "EstadoRQ"
                FROM public."RQOperaciones"
                WHERE "IdRetiroLaboral" = :id_retiro_laboral
                  AND COALESCE("Activo", true) = true
                ORDER BY "IdRQOperaciones" DESC
                LIMIT 1
                FOR UPDATE;
            """),
            {"id_retiro_laboral": id_retiro_laboral},
        ).mappings().first()

        if rq_existente:
            if int(rq_existente["IdPazYSalvo"]) != int(IdPazYSalvo):
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=(
                        "El RQ activo no corresponde al Paz y Salvo que se "
                        "está intentando actualizar."
                    ),
                )

            if bool(rq_existente["EnviadoRRLL"]):
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=(
                        "El RQ ya fue enviado a Relaciones Laborales. "
                        "No se permite modificar el Paz y Salvo."
                    ),
                )

        # ============================================================
        # VALIDAR PDF MANUAL Y NUEVAS EVIDENCIAS ANTES DE ACTUALIZAR
        # ============================================================
        if archivo is not None:
            contenido_pdf = await archivo.read()
            _validar_archivo_pdf(archivo, contenido_pdf)
            nombre_original_pdf = Path(str(archivo.filename)).name

        evidencias_recibidas: list[tuple[str, UploadFile, bytes]] = []

        if novedadesNominaArchivo:
            for archivo_evidencia in novedadesNominaArchivo:
                contenido_evidencia = await archivo_evidencia.read()
                _validar_evidencia(
                    archivo_evidencia,
                    contenido_evidencia,
                    "NOVEDADES_NOMINA",
                )
                evidencias_recibidas.append((
                    "NOVEDADES_NOMINA",
                    archivo_evidencia,
                    contenido_evidencia,
                ))

        evidencias_simples = [
            ("FORMATO_DESCUENTO_VACUNAS", formatoDescuentoVacunasArchivo),
            ("CARNET_ACCESO", fotoCarnetAccesoArchivo),
            ("LISTADO_HERRAMIENTAS", fotoListadoHerramientasArchivo),
            ("PLANILLA_NOMINA", fotoPlanillaNominaArchivo),
        ]

        for tipo_evidencia, archivo_evidencia in evidencias_simples:
            if archivo_evidencia is None:
                continue

            contenido_evidencia = await archivo_evidencia.read()
            _validar_evidencia(
                archivo_evidencia,
                contenido_evidencia,
                tipo_evidencia,
            )
            evidencias_recibidas.append((
                tipo_evidencia,
                archivo_evidencia,
                contenido_evidencia,
            ))

        # ============================================================
        # ACTUALIZAR LOS MISMOS REGISTROS
        # ============================================================
        db.execute(
            text("""
                UPDATE public."RetiroLaboral"
                SET
                    "IdCliente" = :id_cliente,
                    "IdMotivoRetiro" = :id_motivo_retiro,
                    "FechaRetiro" = :fecha_retiro,
                    "ObservacionGeneral" = :observacion_general,
                    "FechaActualizacion" = CURRENT_TIMESTAMP,
                    "UsuarioActualizacion" = :usuario
                WHERE "IdRetiroLaboral" = :id_retiro_laboral
                  AND UPPER(TRIM(COALESCE("EstadoCasoRRLL", '')))
                      = 'PENDIENTE_OPERACIONES'
                  AND COALESCE("Activo", true) = true;
            """),
            {
                "id_cliente": IdCliente,
                "id_motivo_retiro": IdMotivoRetiro,
                "fecha_retiro": FechaUltimoDiaLaborado,
                "observacion_general": observacion,
                "usuario": usuario,
                "id_retiro_laboral": id_retiro_laboral,
            },
        )

        db.execute(
            text("""
                UPDATE public."PazYSalvoOperaciones"
                SET
                    "FechaUltimoDiaLaborado" = :fecha_ultimo_dia_laborado,
                    "Observacion" = :observacion
                WHERE "IdPazYSalvo" = :id_paz_y_salvo
                  AND "IdRetiroLaboral" = :id_retiro_laboral;
            """),
            {
                "fecha_ultimo_dia_laborado": FechaUltimoDiaLaborado,
                "observacion": observacion,
                "id_paz_y_salvo": IdPazYSalvo,
                "id_retiro_laboral": id_retiro_laboral,
            },
        )

        resultado_detalle = db.execute(
            text("""
                UPDATE public."PazYSalvoOperacionesDetalle"
                SET
                    "FechaHoraInicioDiligenciamiento" =
                        :fecha_hora_inicio_diligenciamiento,
                    "ElaboradoPor" = :elaborado_por,
                    "DescripcionMotivoRetiro" = :descripcion_motivo_retiro,
                    "Locker" = :locker,
                    "Llaves" = :llaves,
                    "EntregaHerramientas" = :entrega_herramientas,
                    "TarjetaControlAcceso" = :tarjeta_control_acceso,
                    "EntregaGuantes" = :entrega_guantes,
                    "EntregaMonogafas" = :entrega_monogafas,
                    "EntregaPeto" = :entrega_peto,
                    "ObservacionesEntrega" = :observaciones_entrega,
                    "AplicaDescuento" = :aplica_descuento,
                    "ValorDescuento" = :valor_descuento,
                    "NovedadesNomina" = :novedades_nomina,
                    "PendienteEntregaUniforme" = :pendiente_entrega_uniforme,
                    "UniformePatogeno" = :uniforme_patogeno,
                    "Botas" = :botas,
                    "Zapatos" = :zapatos,
                    "Chaqueta" = :chaqueta,
                    "CarnetAlpArl" = :carnet_alp_arl,
                    "PendientePagoVacunas" = :pendiente_pago_vacunas,
                    "UsuariosClavesDispositivos" =
                        :usuarios_claves_dispositivos,
                    "CorreoSupervisora" = :correo_supervisora,
                    "EstadoPazYSalvo" = :estado_paz_y_salvo,
                    "FechaActualizacion" = CURRENT_TIMESTAMP,
                    "UsuarioActualizacion" = :usuario
                WHERE "IdPazYSalvoDetalle" = :id_paz_y_salvo_detalle
                  AND "IdPazYSalvo" = :id_paz_y_salvo;
            """),
            {
                "fecha_hora_inicio_diligenciamiento": (
                    FechaHoraInicioDiligenciamiento
                ),
                "elaborado_por": elaborado_por,
                "descripcion_motivo_retiro": descripcion_motivo,
                "locker": locker,
                "llaves": llaves,
                "entrega_herramientas": entrega_herramientas,
                "tarjeta_control_acceso": tarjeta_control_acceso,
                "entrega_guantes": entrega_guantes,
                "entrega_monogafas": entrega_monogafas,
                "entrega_peto": entrega_peto,
                "observaciones_entrega": observaciones_entrega,
                "aplica_descuento": aplica_descuento,
                "valor_descuento": valor_descuento,
                "novedades_nomina": novedades_nomina,
                "pendiente_entrega_uniforme": pendiente_entrega_uniforme,
                "uniforme_patogeno": uniforme_patogeno,
                "botas": botas,
                "zapatos": zapatos,
                "chaqueta": chaqueta,
                "carnet_alp_arl": carnet_alp_arl,
                "pendiente_pago_vacunas": pendiente_pago_vacunas,
                "usuarios_claves_dispositivos": (
                    usuarios_claves_dispositivos
                ),
                "correo_supervisora": correo_supervisora,
                "estado_paz_y_salvo": estado_paz_y_salvo,
                "usuario": usuario,
                "id_paz_y_salvo_detalle": IdPazYSalvoDetalle,
                "id_paz_y_salvo": IdPazYSalvo,
            },
        )

        if resultado_detalle.rowcount != 1:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    "No fue posible actualizar exactamente un detalle del "
                    "Paz y Salvo. La operación fue cancelada."
                ),
            )

        # El RQ existente cambia únicamente de estado según el Paz y Salvo.
        estado_rq = (
            "LISTO_PARA_ENVIO"
            if estado_paz_y_salvo == "CERRADO"
            else "PENDIENTE_OPERACIONES"
        )

        id_rq_operaciones = None

        if rq_existente:
            id_rq_operaciones = int(rq_existente["IdRQOperaciones"])

            db.execute(
                text("""
                    UPDATE public."RQOperaciones"
                    SET
                        "EstadoRQ" = :estado_rq,
                        "UsuarioActualizacion" = :usuario,
                        "FechaActualizacion" = CURRENT_TIMESTAMP
                    WHERE "IdRQOperaciones" = :id_rq_operaciones
                      AND COALESCE("Activo", true) = true
                      AND COALESCE("EnviadoRRLL", false) = false;
                """),
                {
                    "estado_rq": estado_rq,
                    "usuario": usuario,
                    "id_rq_operaciones": id_rq_operaciones,
                },
            )

        # Guardar las respuestas del perfil antes de generar el PDF.
        _guardar_bloques_perfil_en_transaccion(db, current, IdPazYSalvo, BloquesPerfilJSON)

        # ============================================================
        # REGENERAR PDF OFICIAL DEL MISMO PAZ Y SALVO
        # ============================================================
        if contenido_pdf is None:
            buffer_pdf = generar_paz_salvo_operaciones_pdf(
                db=db,
                id_paz_y_salvo=IdPazYSalvo,
            )
            contenido_pdf = buffer_pdf.getvalue()
            buffer_pdf.close()
            nombre_original_pdf = (
                f"paz_salvo_operaciones_{id_retiro_laboral}.pdf"
            )

        if not contenido_pdf:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=(
                    "No fue posible generar la nueva versión del PDF oficial "
                    "del Paz y Salvo."
                ),
            )

        carpeta_retiro = STORAGE_BASE_DIR / str(id_retiro_laboral)
        carpeta_retiro.mkdir(parents=True, exist_ok=True)

        nombre_guardado_pdf = (
            f"paz_salvo_operaciones_"
            f"{id_retiro_laboral}_{uuid4().hex}.pdf"
        )
        ruta_pdf_nueva = carpeta_retiro / nombre_guardado_pdf
        ruta_pdf_nueva.write_bytes(contenido_pdf)
        ruta_archivo_bd = str(ruta_pdf_nueva).replace("\\", "/")

        # La versión anterior queda inactiva; no se elimina físicamente.
        db.execute(
            text("""
                UPDATE public."RetiroLaboralAdjunto"
                SET
                    "Activo" = false,
                    "FechaActualizacion" = CURRENT_TIMESTAMP,
                    "UsuarioActualizacion" = :usuario
                WHERE "IdRetiroLaboral" = :id_retiro_laboral
                  AND "IdTipoDocumentoRetiro" = :id_tipo_documento_retiro
                  AND COALESCE("Activo", true) = true
                  AND COALESCE("Eliminado", false) = false;
            """),
            {
                "usuario": usuario,
                "id_retiro_laboral": id_retiro_laboral,
                "id_tipo_documento_retiro": ID_TIPO_DOCUMENTO_PAZ_Y_SALVO,
            },
        )

        id_adjunto_nuevo = db.execute(
            text("""
                INSERT INTO public."RetiroLaboralAdjunto" (
                    "IdRetiroLaboral",
                    "IdTipoDocumentoRetiro",
                    "NombreArchivo",
                    "NombreArchivoOriginal",
                    "RutaArchivo",
                    "ExtensionArchivo",
                    "PesoArchivo",
                    "Observacion",
                    "OrigenArchivo",
                    "MimeType",
                    "Activo",
                    "Eliminado",
                    "FechaCreacion",
                    "FechaActualizacion",
                    "CreadoPor",
                    "UsuarioActualizacion"
                )
                VALUES (
                    :id_retiro_laboral,
                    :id_tipo_documento_retiro,
                    :nombre_archivo,
                    :nombre_archivo_original,
                    :ruta_archivo,
                    '.pdf',
                    :peso_archivo,
                    :observacion,
                    'OPERACIONES',
                    'application/pdf',
                    true,
                    false,
                    CURRENT_TIMESTAMP,
                    CURRENT_TIMESTAMP,
                    :creado_por,
                    :usuario_actualizacion
                )
                RETURNING "IdRetiroLaboralAdjunto";
            """),
            {
                "id_retiro_laboral": id_retiro_laboral,
                "id_tipo_documento_retiro": ID_TIPO_DOCUMENTO_PAZ_Y_SALVO,
                "nombre_archivo": nombre_guardado_pdf,
                "nombre_archivo_original": nombre_original_pdf,
                "ruta_archivo": ruta_archivo_bd,
                "peso_archivo": len(contenido_pdf),
                "observacion": (
                    observacion
                    or (
                        "Paz y salvo actualizado desde el módulo "
                        "de Operaciones."
                    )
                ),
                "creado_por": usuario,
                "usuario_actualizacion": usuario,
            },
        ).scalar_one()

        # ============================================================
        # NUEVAS EVIDENCIAS OPCIONALES
        # Las existentes permanecen activas.
        # ============================================================
        if evidencias_recibidas:
            carpeta_evidencias = (
                carpeta_retiro / "evidencias_operaciones"
            )
            carpeta_evidencias.mkdir(parents=True, exist_ok=True)

            for (
                tipo_evidencia,
                archivo_evidencia,
                contenido_evidencia,
            ) in evidencias_recibidas:
                id_evidencia, ruta_evidencia = _guardar_evidencia_paz_salvo(
                    db=db,
                    id_paz_y_salvo=IdPazYSalvo,
                    id_retiro_laboral=id_retiro_laboral,
                    tipo_evidencia=tipo_evidencia,
                    archivo=archivo_evidencia,
                    contenido=contenido_evidencia,
                    usuario=usuario,
                    carpeta_evidencias=carpeta_evidencias,
                )
                ids_evidencias_nuevas.append(id_evidencia)
                rutas_evidencias_creadas.append(ruta_evidencia)

        # IMPORTANTE:
        # - NO se cambia RegistroPersonal.IdEstadoProceso.
        # - NO se cambia RetiroLaboral.EstadoCasoRRLL.
        # - NO se llena FechaEnvioOperaciones.
        # El envío formal sigue siendo un paso separado.
        db.commit()

        return {
            "success": True,
            "message": (
                "El Paz y Salvo existente fue actualizado correctamente. "
                "El caso continúa pendiente en Operaciones."
            ),
            "data": {
                "IdRetiroLaboral": int(id_retiro_laboral),
                "IdPazYSalvo": int(IdPazYSalvo),
                "IdPazYSalvoDetalle": int(IdPazYSalvoDetalle),
                "IdRetiroLaboralAdjunto": int(id_adjunto_nuevo),
                "IdRQOperaciones": id_rq_operaciones,
                "IdRegistroPersonal": int(contexto["IdRegistroPersonal"]),
                "NumeroIdentificacion": contexto["NumeroIdentificacion"],
                "NombreCompleto": contexto["NombreCompleto"],
                "IdCliente": int(IdCliente),
                "NombreCliente": str(
                    cliente["NombreCliente"] or ""
                ).strip(),
                "IdMotivoRetiro": int(IdMotivoRetiro),
                "NombreMotivoRetiro": motivo["Nombre"],
                "FechaUltimoDiaLaborado": FechaUltimoDiaLaborado,
                "EstadoPazYSalvo": estado_paz_y_salvo,
                "EstadoRQ": estado_rq if rq_existente else None,
                "EstadoCasoRRLL": "PENDIENTE_OPERACIONES",
                "IdEstadoProceso": int(contexto["IdEstadoProceso"]),
                "FechaEnvioOperaciones": None,
                "PendienteEnvioRRLL": True,
                "CantidadEvidenciasNuevas": len(ids_evidencias_nuevas),
                "IdsEvidenciasNuevas": ids_evidencias_nuevas,
            },
        }

    except HTTPException:
        db.rollback()

        if ruta_pdf_nueva and ruta_pdf_nueva.exists():
            ruta_pdf_nueva.unlink(missing_ok=True)

        for ruta in rutas_evidencias_creadas:
            if ruta.exists():
                ruta.unlink(missing_ok=True)

        raise

    except Exception as error:
        db.rollback()

        if ruta_pdf_nueva and ruta_pdf_nueva.exists():
            ruta_pdf_nueva.unlink(missing_ok=True)

        for ruta in rutas_evidencias_creadas:
            if ruta.exists():
                ruta.unlink(missing_ok=True)

        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=(
                "No fue posible actualizar el Paz y Salvo existente: "
                f"{str(error)}"
            ),
        ) from error

    finally:
        for archivo_abierto in archivos_para_cerrar:
            try:
                await archivo_abierto.close()
            except Exception:
                pass


# ============================================================
# RQ PERSONAL NUEVO - CATÁLOGOS Y CREACIÓN
# ============================================================
def _validar_cargo_rq_personal_nuevo(db: Session, id_cargo: int):
    row = db.execute(
        text("""
            SELECT
                c."IdCargo",
                c."NombreCargo"
            FROM public."Cargo" c
            WHERE c."IdCargo" = :id_cargo
              AND COALESCE(c."Activo", true) = true
            LIMIT 1;
        """),
        {"id_cargo": id_cargo},
    ).mappings().first()

    if not row:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="El cargo seleccionado no existe o está inactivo.",
        )

    return row


def _validar_ciudad_rq_personal_nuevo(db: Session, id_ciudad: int):
    row = db.execute(
        text("""
            SELECT
                c."IdCiudad",
                c."Nombre" AS "NombreCiudad"
            FROM public."Ciudad" c
            WHERE c."IdCiudad" = :id_ciudad
              AND COALESCE(c."Estado", true) = true
            LIMIT 1;
        """),
        {"id_ciudad": id_ciudad},
    ).mappings().first()

    if not row:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="La ciudad seleccionada no existe o está inactiva.",
        )

    if int(row["IdCiudad"]) not in IDS_CIUDADES_RQ_PERSONAL_NUEVO:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "La ciudad seleccionada no está habilitada para RQ de personal nuevo. "
                "Seleccione una ciudad disponible o utilice la opción OTRO."
            ),
        )

    return row


def _validar_tipo_contrato_rq_personal_nuevo(
    db: Session,
    id_tipo_contrato: int,
):
    row = db.execute(
        text("""
            SELECT
                tc."IdTipoContrato",
                tc."Descripcion"
            FROM public."TipoContrato" tc
            WHERE tc."IdTipoContrato" = :id_tipo_contrato
              AND COALESCE(tc."Estado", B'1') = B'1'
            LIMIT 1;
        """),
        {"id_tipo_contrato": id_tipo_contrato},
    ).mappings().first()

    if not row:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="El tipo de contrato seleccionado no existe o está inactivo.",
        )

    return row


def _validar_motivo_vacante_rq_personal_nuevo(
    db: Session,
    id_motivo_vacante_rq: int,
):
    # to_jsonb permite leer el texto descriptivo sin acoplar el endpoint a un
    # nombre alternativo de columna; el identificador sí es el FK oficial.
    row = db.execute(
        text("""
            SELECT
                mv."IdMotivoVacanteRQ",
                COALESCE(
                    to_jsonb(mv) ->> 'Nombre',
                    to_jsonb(mv) ->> 'Descripcion',
                    to_jsonb(mv) ->> 'MotivoVacante',
                    to_jsonb(mv) ->> 'NombreMotivoVacante'
                ) AS "NombreMotivoVacante",
                COALESCE(
                    NULLIF(to_jsonb(mv) ->> 'Activo', '')::boolean,
                    NULLIF(to_jsonb(mv) ->> 'Estado', '')::boolean,
                    true
                ) AS "ActivoCatalogo"
            FROM public."MotivoVacanteRQ" mv
            WHERE mv."IdMotivoVacanteRQ" = :id_motivo_vacante_rq
            LIMIT 1;
        """),
        {"id_motivo_vacante_rq": id_motivo_vacante_rq},
    ).mappings().first()

    if not row or not bool(row["ActivoCatalogo"]):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="El motivo de vacante seleccionado no existe o está inactivo.",
        )

    return row


@router.get("/rq/personal-nuevo/catalogos")
def obtener_catalogos_rq_personal_nuevo(
    db: Session = Depends(get_db),
    current=Depends(require_operaciones_retiros),
):
    """Catálogos necesarios para diligenciar un RQ de PERSONAL_NUEVO."""
    clientes = db.execute(
        text("""
            SELECT
                c."IdCliente",
                c."Nombre" AS "NombreCliente"
            FROM public."Cliente" c
            WHERE TRIM(COALESCE(c."Nombre", '')) <> ''
              AND COALESCE(c."Activo", true) = true
            ORDER BY c."Nombre" ASC;
        """)
    ).mappings().all()

    cargos = db.execute(
        text("""
            SELECT
                c."IdCargo",
                c."NombreCargo"
            FROM public."Cargo" c
            WHERE COALESCE(c."Activo", true) = true
              AND TRIM(COALESCE(c."NombreCargo", '')) <> ''
            ORDER BY c."NombreCargo" ASC;
        """)
    ).mappings().all()

    perfiles = db.execute(
        text("""
            SELECT
                p."IdPerfilRQ",
                p."CodigoPerfil",
                p."DescripcionPerfil",
                p."Genero",
                p."NivelEscolaridad",
                p."Observaciones"
            FROM public."PerfilRQ" p
            WHERE COALESCE(p."Activo", true) = true
            ORDER BY p."IdPerfilRQ" ASC;
        """)
    ).mappings().all()

    ciudades = db.execute(
        text("""
            SELECT
                c."IdCiudad",
                c."Nombre" AS "NombreCiudad"
            FROM public."Ciudad" c
            WHERE COALESCE(c."Estado", true) = true
              AND TRIM(COALESCE(c."Nombre", '')) <> ''
              AND c."IdCiudad" IN (10, 14, 29, 33, 62, 103)
            ORDER BY c."Nombre" ASC;
        """)
    ).mappings().all()

    tipos_contrato = db.execute(
        text("""
            SELECT
                tc."IdTipoContrato",
                tc."Descripcion"
            FROM public."TipoContrato" tc
            WHERE COALESCE(tc."Estado", B'1') = B'1'
            ORDER BY tc."IdTipoContrato" ASC;
        """)
    ).mappings().all()

    motivos = db.execute(
        text("""
            SELECT
                mv."IdMotivoVacanteRQ",
                COALESCE(
                    to_jsonb(mv) ->> 'Nombre',
                    to_jsonb(mv) ->> 'Descripcion',
                    to_jsonb(mv) ->> 'MotivoVacante',
                    to_jsonb(mv) ->> 'NombreMotivoVacante'
                ) AS "NombreMotivoVacante",
                COALESCE(
                    NULLIF(to_jsonb(mv) ->> 'Activo', '')::boolean,
                    NULLIF(to_jsonb(mv) ->> 'Estado', '')::boolean,
                    true
                ) AS "ActivoCatalogo"
            FROM public."MotivoVacanteRQ" mv
            ORDER BY mv."IdMotivoVacanteRQ" ASC;
        """)
    ).mappings().all()

    return {
        "success": True,
        "data": {
            "Clientes": [dict(row) for row in clientes],
            "Cargos": [dict(row) for row in cargos],
            "Perfiles": [dict(row) for row in perfiles],
            "Ciudades": [dict(row) for row in ciudades],
            "TiposContrato": [dict(row) for row in tipos_contrato],
            "MotivosVacante": [
                {
                    "IdMotivoVacanteRQ": int(row["IdMotivoVacanteRQ"]),
                    "NombreMotivoVacante": row["NombreMotivoVacante"],
                }
                for row in motivos
                if bool(row["ActivoCatalogo"])
            ],
            "Turnos": sorted(TURNOS_RQ),
        },
    }


@router.post("/rq/personal-nuevo")
def crear_rq_personal_nuevo(
    IdCliente: int = Form(...),
    IdCargo: int = Form(...),
    IdPerfilRQ: int = Form(...),
    CargoAprobadoPlanta: bool = Form(...),
    IdCiudad: str | None = Form(None),
    CiudadOtra: str | None = Form(None),
    IdTipoContrato: int = Form(...),
    Turno: str = Form(...),
    IdMotivoVacanteRQ: int = Form(...),
    CantidadSolicitada: int = Form(...),
    ObservacionCliente: str | None = Form(None),
    db: Session = Depends(get_db),
    current=Depends(require_operaciones_retiros),
):
    """
    Crea y envía a Selección una RQ independiente de PERSONAL_NUEVO.

    No crea RetiroLaboral, Paz y Salvo ni RegistroPersonal. El solicitante se
    toma exclusivamente de la sesión autenticada.
    """
    identidad = _obtener_usuario_actual_rq(current)
    usuario = _normalizar_usuario(identidad["Usuario"])

    try:
        if CantidadSolicitada <= 0:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="La cantidad solicitada debe ser mayor que cero.",
            )

        turno = _normalizar_opcion(Turno, "Turno", TURNOS_RQ)
        observacion_cliente = _normalizar_texto_opcional(ObservacionCliente)

        cliente = _validar_cliente(db, IdCliente)
        cargo = _validar_cargo_rq_personal_nuevo(db, IdCargo)
        perfil = _validar_perfil_rq(db, IdPerfilRQ)

        # IdCiudad llega desde application/x-www-form-urlencoded.
        # Swagger y el frontend pueden enviar el campo opcional como cadena
        # vacía (""). Primero se normaliza y solo después se convierte a int.
        id_ciudad_texto = _normalizar_texto_opcional(IdCiudad)
        ciudad_otra = _normalizar_texto_opcional(CiudadOtra)

        id_ciudad_normalizado = None
        if id_ciudad_texto is not None:
            try:
                id_ciudad_normalizado = int(id_ciudad_texto)
            except (TypeError, ValueError):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="El identificador de ciudad no es válido.",
                )

            if id_ciudad_normalizado <= 0:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="El identificador de ciudad no es válido.",
                )

        if id_ciudad_normalizado is not None and ciudad_otra is not None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    "Seleccione una ciudad del catálogo o escriba otra ciudad, "
                    "pero no ambas opciones."
                ),
            )

        if id_ciudad_normalizado is None and ciudad_otra is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Debe seleccionar una ciudad o especificar otra ciudad.",
            )

        if id_ciudad_normalizado is not None:
            ciudad = _validar_ciudad_rq_personal_nuevo(
                db,
                id_ciudad_normalizado,
            )
            id_ciudad_guardar = int(ciudad["IdCiudad"])
            nombre_ciudad_guardar = str(ciudad["NombreCiudad"] or "").strip()
        else:
            ciudad = None
            id_ciudad_guardar = None
            nombre_ciudad_guardar = ciudad_otra

        tipo_contrato = _validar_tipo_contrato_rq_personal_nuevo(
            db,
            IdTipoContrato,
        )
        motivo = _validar_motivo_vacante_rq_personal_nuevo(
            db,
            IdMotivoVacanteRQ,
        )

        id_rq_operaciones = db.execute(
            text("""
                INSERT INTO public."RQOperaciones" (
                    "IdRetiroLaboral",
                    "IdPazYSalvo",
                    "IdRegistroPersonal",
                    "IdCliente",
                    "IdUsuarioLider",
                    "IdPerfilRQ",
                    "TipoNotificacion",
                    "FechaRetiro",
                    "FechaUltimoDiaLaborado",
                    "Observacion",
                    "RequiereReemplazo",
                    "Ciudad",
                    "Turno",
                    "MotivoVacante",
                    "ObservacionCliente",
                    "FechaRegistro",
                    "EstadoRQ",
                    "EnviadoRRLL",
                    "FechaEnvioRRLL",
                    "Activo",
                    "UsuarioCreacion",
                    "FechaCreacion",
                    "TipoRQ",
                    "IdCargo",
                    "CantidadSolicitada",
                    "EnviadoSeleccion",
                    "FechaEnvioSeleccion",
                    "IdCiudad",
                    "IdTipoContrato",
                    "CargoAprobadoPlanta",
                    "IdMotivoVacanteRQ"
                )
                VALUES (
                    NULL,
                    NULL,
                    NULL,
                    :id_cliente,
                    :id_usuario_lider,
                    :id_perfil_rq,
                    NULL,
                    NULL,
                    NULL,
                    NULL,
                    false,
                    :nombre_ciudad,
                    :turno,
                    NULL,
                    :observacion_cliente,
                    CURRENT_DATE,
                    'ENVIADO_SELECCION',
                    false,
                    NULL,
                    true,
                    :usuario_creacion,
                    CURRENT_TIMESTAMP,
                    'PERSONAL_NUEVO',
                    :id_cargo,
                    :cantidad_solicitada,
                    true,
                    CURRENT_TIMESTAMP,
                    :id_ciudad,
                    :id_tipo_contrato,
                    :cargo_aprobado_planta,
                    :id_motivo_vacante_rq
                )
                RETURNING "IdRQOperaciones";
            """),
            {
                "id_cliente": IdCliente,
                "id_usuario_lider": identidad["IdUsuario"],
                "id_perfil_rq": IdPerfilRQ,
                "nombre_ciudad": nombre_ciudad_guardar,
                "turno": turno,
                "observacion_cliente": observacion_cliente,
                "usuario_creacion": usuario,
                "id_cargo": IdCargo,
                "cantidad_solicitada": CantidadSolicitada,
                "id_ciudad": id_ciudad_guardar,
                "id_tipo_contrato": IdTipoContrato,
                "cargo_aprobado_planta": CargoAprobadoPlanta,
                "id_motivo_vacante_rq": IdMotivoVacanteRQ,
            },
        ).scalar_one()

        db.commit()

        return {
            "success": True,
            "message": "La requisición de personal fue enviada correctamente a Selección.",
            "data": {
                "IdRQOperaciones": int(id_rq_operaciones),
                "TipoRQ": "PERSONAL_NUEVO",
                "IdCliente": int(IdCliente),
                "NombreCliente": str(cliente["NombreCliente"] or "").strip(),
                "IdCargo": int(IdCargo),
                "NombreCargo": str(cargo["NombreCargo"] or "").strip(),
                "IdPerfilRQ": int(IdPerfilRQ),
                "CodigoPerfil": perfil["CodigoPerfil"],
                "IdCiudad": id_ciudad_guardar,
                "NombreCiudad": nombre_ciudad_guardar,
                "IdTipoContrato": int(IdTipoContrato),
                "TipoContrato": tipo_contrato["Descripcion"],
                "CargoAprobadoPlanta": bool(CargoAprobadoPlanta),
                "Turno": turno,
                "IdMotivoVacanteRQ": int(IdMotivoVacanteRQ),
                "MotivoVacante": motivo["NombreMotivoVacante"],
                "CantidadSolicitada": int(CantidadSolicitada),
                "ObservacionCliente": observacion_cliente,
                "IdUsuarioLider": str(identidad["IdUsuario"]),
                "NombreLider": identidad["NombreCompleto"],
                "EstadoRQ": "ENVIADO_SELECCION",
                "EnviadoRRLL": False,
                "EnviadoSeleccion": True,
            },
        }

    except HTTPException:
        db.rollback()
        raise

    except Exception as error:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=(
                "No fue posible crear la requisición de personal nuevo: "
                f"{str(error)}"
            ),
        ) from error


@router.get("/rq/personal-nuevo")
def listar_rq_personal_nuevo_operaciones(
    db: Session = Depends(get_db),
    current=Depends(require_operaciones_retiros),
):
    """Lista las RQ PERSONAL_NUEVO creadas desde Operaciones."""
    rows = db.execute(
        text("""
            SELECT
                rq."IdRQOperaciones",
                rq."IdCliente",
                c."Nombre" AS "NombreCliente",
                rq."IdCargo",
                ca."NombreCargo",
                rq."IdPerfilRQ",
                prq."CodigoPerfil",
                prq."DescripcionPerfil",
                rq."IdCiudad",
                COALESCE(
                    NULLIF(TRIM(ci."Nombre"), ''),
                    NULLIF(TRIM(rq."Ciudad"), '')
                ) AS "NombreCiudad",
                rq."IdTipoContrato",
                tc."Descripcion" AS "TipoContrato",
                rq."CargoAprobadoPlanta",
                rq."Turno",
                rq."IdMotivoVacanteRQ",
                COALESCE(
                    to_jsonb(mv) ->> 'Nombre',
                    to_jsonb(mv) ->> 'Descripcion',
                    to_jsonb(mv) ->> 'MotivoVacante',
                    to_jsonb(mv) ->> 'NombreMotivoVacante'
                ) AS "NombreMotivoVacante",
                rq."CantidadSolicitada",
                rq."ObservacionCliente",
                rq."EstadoRQ",
                rq."EnviadoSeleccion",
                rq."FechaEnvioSeleccion",
                rq."IdUsuarioLider",
                u."NombreUsuario" AS "NombreLider",
                rq."FechaRegistro",
                rq."FechaCreacion",
                (
                    SELECT COUNT(*)
                    FROM public."RQCandidato" rc
                    INNER JOIN public."RegistroPersonal" rp
                        ON rp."IdRegistroPersonal" = rc."IdRegistroPersonal"
                    WHERE rc."IdRQOperaciones" = rq."IdRQOperaciones"
                      AND COALESCE(rc."Activo", true) = true
                      AND rp."IdEstadoProceso" = :id_estado_contratado
                ) AS "CantidadCubierta"
            FROM public."RQOperaciones" rq
            INNER JOIN public."Cliente" c
                ON c."IdCliente" = rq."IdCliente"
            LEFT JOIN public."Cargo" ca
                ON ca."IdCargo" = rq."IdCargo"
            LEFT JOIN public."PerfilRQ" prq
                ON prq."IdPerfilRQ" = rq."IdPerfilRQ"
            LEFT JOIN public."Ciudad" ci
                ON ci."IdCiudad" = rq."IdCiudad"
            LEFT JOIN public."TipoContrato" tc
                ON tc."IdTipoContrato" = rq."IdTipoContrato"
            LEFT JOIN public."MotivoVacanteRQ" mv
                ON mv."IdMotivoVacanteRQ" = rq."IdMotivoVacanteRQ"
            INNER JOIN public."Usuario" u
                ON u."IdUsuario" = rq."IdUsuarioLider"
            WHERE rq."TipoRQ" = 'PERSONAL_NUEVO'
              AND COALESCE(rq."Activo", true) = true
            ORDER BY rq."IdRQOperaciones" DESC;
        """),
        {"id_estado_contratado": ID_ESTADO_CONTRATADO},
    ).mappings().all()

    data = []
    for row in rows:
        solicitada = int(row["CantidadSolicitada"] or 1)
        cubierta = int(row["CantidadCubierta"] or 0)
        data.append({
            **dict(row),
            "IdRQOperaciones": int(row["IdRQOperaciones"]),
            "CantidadSolicitada": solicitada,
            "CantidadCubierta": cubierta,
            "CantidadPendiente": max(solicitada - cubierta, 0),
            "EnviadoSeleccion": bool(row["EnviadoSeleccion"]),
            "CargoAprobadoPlanta": (
                bool(row["CargoAprobadoPlanta"])
                if row["CargoAprobadoPlanta"] is not None
                else None
            ),
            "IdUsuarioLider": str(row["IdUsuarioLider"]),
        })

    return {"success": True, "total": len(data), "data": data}


@router.get("/rq/ciudad/trabajador/{id_registro_personal}")
def obtener_ciudad_rq_trabajador(
    id_registro_personal: int,
    db: Session = Depends(get_db),
    current=Depends(require_operaciones_retiros),
):
    ciudad = _obtener_ciudad_trabajador(
        db=db,
        id_registro_personal=id_registro_personal,
    )

    if ciudad is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=(
                "El trabajador no tiene una ciudad registrada en "
                "DatosAdicionales."
            ),
        )

    return {"success": True, "data": ciudad}


@router.get("/rq/perfiles")
def listar_perfiles_rq(
    db: Session = Depends(get_db),
    current=Depends(require_operaciones_retiros),
):
    rows = db.execute(
        text("""
            SELECT
                "IdPerfilRQ",
                "CodigoPerfil",
                "DescripcionPerfil",
                "Genero",
                "NivelEscolaridad",
                "Observaciones"
            FROM public."PerfilRQ"
            WHERE COALESCE("Activo", true) = true
            ORDER BY "IdPerfilRQ" ASC;
        """)
    ).mappings().all()

    return {
        "success": True,
        "data": [
            {
                "IdPerfilRQ": int(row["IdPerfilRQ"]),
                "CodigoPerfil": row["CodigoPerfil"],
                "DescripcionPerfil": row["DescripcionPerfil"],
                "Genero": row["Genero"],
                "NivelEscolaridad": row["NivelEscolaridad"],
                "Observaciones": row["Observaciones"],
            }
            for row in rows
        ],
    }


@router.get("/rq/retiro/{id_retiro_laboral}")
def obtener_rq_por_retiro(
    id_retiro_laboral: int,
    db: Session = Depends(get_db),
    current=Depends(require_operaciones_retiros),
):
    row = db.execute(
        text("""
            SELECT
                rq.*,
                rp."NumeroIdentificacion",
                TRIM(
                    COALESCE(rp."Nombres", '') || ' ' ||
                    COALESCE(rp."Apellidos", '')
                ) AS "NombreCompleto",
                c."Nombre" AS "NombreCliente",
                acc."IdCargo" AS "IdCargoDerivado",
                ca."NombreCargo",
                u."NombreUsuario" AS "NombreLider",
                prq."CodigoPerfil",
                prq."DescripcionPerfil",
                prq."Genero" AS "GeneroPerfil",
                prq."NivelEscolaridad" AS "NivelEscolaridadPerfil",
                prq."Observaciones" AS "ObservacionesPerfil"
            FROM public."RQOperaciones" rq
            INNER JOIN public."RegistroPersonal" rp
                ON rp."IdRegistroPersonal" = rq."IdRegistroPersonal"
            INNER JOIN public."Cliente" c
                ON c."IdCliente" = rq."IdCliente"
            INNER JOIN public."Usuario" u
                ON u."IdUsuario" = rq."IdUsuarioLider"
            LEFT JOIN public."PerfilRQ" prq
                ON prq."IdPerfilRQ" = rq."IdPerfilRQ"
            LEFT JOIN LATERAL (
                SELECT
                    x."IdCargo"
                FROM public."AsignacionCargoCliente" x
                WHERE x."IdRegistroPersonal" = rq."IdRegistroPersonal"
                  AND x."IdCargo" IS NOT NULL
                ORDER BY
                    x."FechaActualizacion" DESC NULLS LAST,
                    x."FechaCreacion" DESC NULLS LAST,
                    x."IdAsignacionCargoCliente" DESC
                LIMIT 1
            ) acc ON true
            LEFT JOIN public."Cargo" ca
                ON ca."IdCargo" = acc."IdCargo"
            WHERE rq."IdRetiroLaboral" = :id_retiro_laboral
              AND COALESCE(rq."Activo", true) = true
            ORDER BY rq."IdRQOperaciones" DESC
            LIMIT 1;
        """),
        {"id_retiro_laboral": id_retiro_laboral},
    ).mappings().first()

    if not row:
        return {
            "success": True,
            "data": None,
        }

    adjuntos = db.execute(
        text("""
            SELECT
                "IdRQOperacionesAdjunto",
                "TipoDocumento",
                "NombreArchivoOriginal",
                "ExtensionArchivo",
                "MimeType",
                "PesoArchivo",
                "FechaCreacion"
            FROM public."RQOperacionesAdjunto"
            WHERE "IdRQOperaciones" = :id_rq_operaciones
              AND COALESCE("Activo", true) = true
              AND COALESCE("Eliminado", false) = false
            ORDER BY "IdRQOperacionesAdjunto" ASC;
        """),
        {"id_rq_operaciones": row["IdRQOperaciones"]},
    ).mappings().all()

    data = _serializar_rq(row)
    data["Adjuntos"] = [
        {
            "IdRQOperacionesAdjunto": int(
                adjunto["IdRQOperacionesAdjunto"]
            ),
            "TipoDocumento": adjunto["TipoDocumento"],
            "NombreArchivoOriginal": adjunto["NombreArchivoOriginal"],
            "ExtensionArchivo": adjunto["ExtensionArchivo"],
            "MimeType": adjunto["MimeType"],
            "PesoArchivo": adjunto["PesoArchivo"],
            "FechaCreacion": adjunto["FechaCreacion"],
        }
        for adjunto in adjuntos
    ]

    return {
        "success": True,
        "data": data,
    }


@router.post("/rq/guardar")
async def guardar_rq_operaciones(
    IdRetiroLaboral: int = Form(...),
    IdPazYSalvo: int = Form(...),
    TipoNotificacion: str = Form(...),
    FechaRetiro: date | None = Form(None),
    FechaUltimoDiaLaborado: date | None = Form(None),
    Observacion: str | None = Form(None),
    RequiereReemplazo: bool = Form(False),
    IdPerfilRQ: int | None = Form(None),
    Ciudad: str | None = Form(None),
    Turno: str | None = Form(None),
    MotivoVacante: str | None = Form(None),
    ObservacionCliente: str | None = Form(None),
    cartaRetiroArchivo: UploadFile | None = File(None),
    db: Session = Depends(get_db),
    current=Depends(require_operaciones_retiros),
):
    ruta_adjunto_creada: Path | None = None

    try:
        identidad = _obtener_usuario_actual_rq(current)
        usuario_auditoria = _normalizar_usuario(identidad["Usuario"])

        contexto = _obtener_contexto_retiro_rq(
            db=db,
            id_retiro_laboral=IdRetiroLaboral,
            id_paz_y_salvo=IdPazYSalvo,
        )

        estado_caso_rrll = str(
            contexto["EstadoCasoRRLL"] or ""
        ).strip().upper()

        if estado_caso_rrll != "PENDIENTE_OPERACIONES":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    "El retiro ya no se encuentra pendiente en Operaciones "
                    "y el RQ no puede ser modificado desde este módulo."
                ),
            )

        ciudad_trabajador = _obtener_ciudad_trabajador(
            db=db,
            id_registro_personal=int(contexto["IdRegistroPersonal"]),
        )

        ciudad_rq = (
            ciudad_trabajador["NombreCiudad"]
            if ciudad_trabajador is not None
            else None
        )

        datos = _validar_datos_rq(
            tipo_notificacion=TipoNotificacion,
            fecha_retiro=FechaRetiro,
            fecha_ultimo_dia_laborado=FechaUltimoDiaLaborado,
            requiere_reemplazo=RequiereReemplazo,
            id_perfil_rq=IdPerfilRQ,
            ciudad=ciudad_rq,
            turno=Turno,
            motivo_vacante=MotivoVacante,
            observacion_cliente=ObservacionCliente,
        )

        perfil = None
        if datos["IdPerfilRQ"] is not None:
            perfil = _validar_perfil_rq(
                db,
                int(datos["IdPerfilRQ"]),
            )

        estado_paz_salvo = str(
            contexto["EstadoPazYSalvo"] or ""
        ).strip().upper()

        estado_rq = (
            "LISTO_PARA_ENVIO"
            if estado_paz_salvo == "CERRADO"
            else "PENDIENTE_OPERACIONES"
        )

        rq_existente = db.execute(
            text("""
                SELECT
                    "IdRQOperaciones",
                    "EnviadoRRLL"
                FROM public."RQOperaciones"
                WHERE "IdRetiroLaboral" = :id_retiro_laboral
                  AND COALESCE("Activo", true) = true
                ORDER BY "IdRQOperaciones" DESC
                LIMIT 1;
            """),
            {"id_retiro_laboral": IdRetiroLaboral},
        ).mappings().first()

        if rq_existente and bool(rq_existente["EnviadoRRLL"]):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    "El RQ ya fue enviado a Relaciones Laborales y no puede "
                    "ser modificado desde Operaciones."
                ),
            )

        observacion = _normalizar_texto_opcional(Observacion)

        parametros_rq = {
            "id_paz_y_salvo": IdPazYSalvo,
            "id_registro_personal": contexto["IdRegistroPersonal"],
            "id_cliente": contexto["IdCliente"],
            "id_usuario_lider": identidad["IdUsuario"],
            "id_perfil_rq": datos["IdPerfilRQ"],
            "tipo_notificacion": datos["TipoNotificacion"],
            "fecha_retiro": datos["FechaRetiro"],
            "fecha_ultimo_dia_laborado": datos["FechaUltimoDiaLaborado"],
            "observacion": observacion,
            "requiere_reemplazo": datos["RequiereReemplazo"],
            "ciudad": datos["Ciudad"],
            "turno": datos["Turno"],
            "motivo_vacante": datos["MotivoVacante"],
            "observacion_cliente": datos["ObservacionCliente"],
            "estado_rq": estado_rq,
            "tipo_rq": (
                "REEMPLAZO"
                if datos["RequiereReemplazo"]
                else None
            ),
            "id_cargo": (
                int(contexto["IdCargo"])
                if datos["RequiereReemplazo"]
                and contexto["IdCargo"] is not None
                else None
            ),
            "cantidad_solicitada": 1,
        }

        if rq_existente:
            id_rq_operaciones = int(
                rq_existente["IdRQOperaciones"]
            )

            db.execute(
                text("""
                    UPDATE public."RQOperaciones"
                    SET
                        "IdPazYSalvo" = :id_paz_y_salvo,
                        "IdRegistroPersonal" = :id_registro_personal,
                        "IdCliente" = :id_cliente,
                        "IdUsuarioLider" = :id_usuario_lider,
                        "IdPerfilRQ" = :id_perfil_rq,
                        "TipoNotificacion" = :tipo_notificacion,
                        "FechaRetiro" = :fecha_retiro,
                        "FechaUltimoDiaLaborado" = :fecha_ultimo_dia_laborado,
                        "Observacion" = :observacion,
                        "RequiereReemplazo" = :requiere_reemplazo,
                        "Ciudad" = :ciudad,
                        "Turno" = :turno,
                        "MotivoVacante" = COALESCE(
                            :motivo_vacante,
                            "MotivoVacante"
                        ),
                        "ObservacionCliente" = :observacion_cliente,
                        "EstadoRQ" = :estado_rq,
                        "TipoRQ" = :tipo_rq,
                        "IdCargo" = :id_cargo,
                        "CantidadSolicitada" = :cantidad_solicitada,
                        "UsuarioActualizacion" = :usuario_actualizacion,
                        "FechaActualizacion" = CURRENT_TIMESTAMP
                    WHERE "IdRQOperaciones" = :id_rq_operaciones;
                """),
                {
                    **parametros_rq,
                    "usuario_actualizacion": usuario_auditoria,
                    "id_rq_operaciones": id_rq_operaciones,
                },
            )
        else:
            id_rq_operaciones = db.execute(
                text("""
                    INSERT INTO public."RQOperaciones" (
                        "IdRetiroLaboral",
                        "IdPazYSalvo",
                        "IdRegistroPersonal",
                        "IdCliente",
                        "IdUsuarioLider",
                        "IdPerfilRQ",
                        "TipoNotificacion",
                        "FechaRetiro",
                        "FechaUltimoDiaLaborado",
                        "Observacion",
                        "RequiereReemplazo",
                        "Ciudad",
                        "Turno",
                        "MotivoVacante",
                        "ObservacionCliente",
                        "FechaRegistro",
                        "EstadoRQ",
                        "TipoRQ",
                        "IdCargo",
                        "CantidadSolicitada",
                        "EnviadoRRLL",
                        "Activo",
                        "UsuarioCreacion",
                        "FechaCreacion"
                    )
                    VALUES (
                        :id_retiro_laboral,
                        :id_paz_y_salvo,
                        :id_registro_personal,
                        :id_cliente,
                        :id_usuario_lider,
                        :id_perfil_rq,
                        :tipo_notificacion,
                        :fecha_retiro,
                        :fecha_ultimo_dia_laborado,
                        :observacion,
                        :requiere_reemplazo,
                        :ciudad,
                        :turno,
                        :motivo_vacante,
                        :observacion_cliente,
                        CURRENT_DATE,
                        :estado_rq,
                        :tipo_rq,
                        :id_cargo,
                        :cantidad_solicitada,
                        false,
                        true,
                        :usuario_creacion,
                        CURRENT_TIMESTAMP
                    )
                    RETURNING "IdRQOperaciones";
                """),
                {
                    **parametros_rq,
                    "id_retiro_laboral": IdRetiroLaboral,
                    "usuario_creacion": usuario_auditoria,
                },
            ).scalar_one()

        carta_obligatoria = (
            datos["TipoNotificacion"]
            in TIPOS_NOTIFICACION_RQ_CON_CARTA
        )

        contenido_carta = None
        if cartaRetiroArchivo is not None:
            contenido_carta = await cartaRetiroArchivo.read()
            _validar_adjunto_rq(
                cartaRetiroArchivo,
                contenido_carta,
            )

        if carta_obligatoria:
            existe_carta = _existe_carta_retiro_rq(
                db,
                id_rq_operaciones,
            )

            if not existe_carta and contenido_carta is None:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=(
                        "La carta de retiro es obligatoria para la "
                        f"notificación {datos['TipoNotificacion']}."
                    ),
                )

        id_adjunto = None
        if (
            cartaRetiroArchivo is not None
            and contenido_carta is not None
        ):
            carpeta_rq = (
                STORAGE_BASE_DIR
                / str(IdRetiroLaboral)
                / "rq"
            )

            id_adjunto, ruta_adjunto_creada = _guardar_adjunto_rq(
                db=db,
                id_rq_operaciones=id_rq_operaciones,
                id_retiro_laboral=IdRetiroLaboral,
                archivo=cartaRetiroArchivo,
                contenido=contenido_carta,
                usuario=usuario_auditoria,
                carpeta_rq=carpeta_rq,
            )

        db.commit()

        # Si Operaciones confirma que NO requiere reemplazo y el Paz y Salvo
        # ya está CERRADO, no existe una vacante para Selección. El retiro
        # debe continuar directamente hacia Relaciones Laborales.
        enviado_rrll_automaticamente = False

        if (
            not datos["RequiereReemplazo"]
            and estado_paz_salvo == "CERRADO"
        ):
            db.execute(
                text("""
                    UPDATE public."RQOperaciones"
                    SET
                        "EstadoRQ" = 'ENVIADO_RRLL',
                        "EnviadoRRLL" = true,
                        "FechaEnvioRRLL" = CURRENT_TIMESTAMP,
                        "EnviadoSeleccion" = false,
                        "FechaEnvioSeleccion" = NULL,
                        "UsuarioActualizacion" = :usuario,
                        "FechaActualizacion" = CURRENT_TIMESTAMP
                    WHERE "IdRQOperaciones" = :id_rq_operaciones
                      AND COALESCE("Activo", true) = true;
                """),
                {
                    "usuario": usuario_auditoria,
                    "id_rq_operaciones": id_rq_operaciones,
                },
            )

            db.execute(
                text("""
                    UPDATE public."RetiroLaboral"
                    SET
                        "EstadoCasoRRLL" = 'ABIERTO',
                        "FechaEnvioOperaciones" = COALESCE(
                            "FechaEnvioOperaciones",
                            CURRENT_TIMESTAMP
                        ),
                        "FechaActualizacion" = CURRENT_TIMESTAMP,
                        "UsuarioActualizacion" = :usuario
                    WHERE "IdRetiroLaboral" = :id_retiro_laboral;
                """),
                {
                    "usuario": usuario_auditoria,
                    "id_retiro_laboral": IdRetiroLaboral,
                },
            )

            db.execute(
                text("""
                    UPDATE public."RegistroPersonal"
                    SET
                        "IdEstadoProceso" = :id_estado_proceso,
                        "FechaActualizacion" = CURRENT_TIMESTAMP,
                        "UsuarioActualizacion" = :usuario
                    WHERE "IdRegistroPersonal" = :id_registro_personal;
                """),
                {
                    "id_estado_proceso": ID_ESTADO_RETIRO_ABIERTO,
                    "usuario": usuario_auditoria,
                    "id_registro_personal": contexto["IdRegistroPersonal"],
                },
            )

            db.commit()
            enviado_rrll_automaticamente = True
            estado_rq = "ENVIADO_RRLL"

        return {
            "success": True,
            "message": (
                "Se confirmó que el retiro no requiere reemplazo y fue "
                "enviado correctamente a Relaciones Laborales."
                if enviado_rrll_automaticamente
                else "RQ guardado correctamente en Operaciones."
            ),
            "data": {
                "IdRQOperaciones": int(id_rq_operaciones),
                "IdRetiroLaboral": IdRetiroLaboral,
                "IdPazYSalvo": IdPazYSalvo,
                "IdRegistroPersonal": int(
                    contexto["IdRegistroPersonal"]
                ),
                "NumeroIdentificacion": contexto[
                    "NumeroIdentificacion"
                ],
                "NombreCompleto": contexto["NombreCompleto"],
                "IdCliente": int(contexto["IdCliente"]),
                "NombreCliente": contexto["NombreCliente"],
                "IdCargo": (
                    int(contexto["IdCargo"])
                    if contexto["IdCargo"] is not None
                    else None
                ),
                "NombreCargo": contexto["NombreCargo"],
                "IdUsuarioLider": str(identidad["IdUsuario"]),
                "NombreLider": identidad["NombreCompleto"],
                "IdPerfilRQ": datos["IdPerfilRQ"],
                "CodigoPerfil": (
                    perfil["CodigoPerfil"]
                    if perfil is not None
                    else None
                ),
                "TipoNotificacion": datos["TipoNotificacion"],
                "RequiereReemplazo": datos["RequiereReemplazo"],
                "TipoRQ": parametros_rq["tipo_rq"],
                "CantidadSolicitada": parametros_rq["cantidad_solicitada"],
                "EstadoRQ": estado_rq,
                "EnviadoRRLL": enviado_rrll_automaticamente,
                "EnviadoSeleccion": False,
                "EnvioAutomaticoRRLL": enviado_rrll_automaticamente,
                "IdRQOperacionesAdjunto": id_adjunto,
            },
        }

    except HTTPException:
        db.rollback()

        if ruta_adjunto_creada and ruta_adjunto_creada.exists():
            ruta_adjunto_creada.unlink(missing_ok=True)

        raise

    except Exception as error:
        db.rollback()

        if ruta_adjunto_creada and ruta_adjunto_creada.exists():
            ruta_adjunto_creada.unlink(missing_ok=True)

        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"No fue posible guardar el RQ: {str(error)}",
        ) from error

    finally:
        if cartaRetiroArchivo is not None:
            await cartaRetiroArchivo.close()



@router.post("/rq/retiro/{id_retiro_laboral}/enviar-rrll")
def enviar_rq_retiro_a_rrll(
    id_retiro_laboral: int,
    db: Session = Depends(get_db),
    current=Depends(require_operaciones_retiros),
):
    """
    Entrega formalmente a RRLL un retiro que ya fue preparado por Operaciones.

    Reglas:
    - RetiroLaboral debe seguir en PENDIENTE_OPERACIONES.
    - Debe existir un RQ activo y no enviado.
    - El RQ debe estar LISTO_PARA_ENVIO.
    - El Paz y Salvo asociado debe estar CERRADO.
    - Solo en este momento se registra FechaEnvioOperaciones.
    - Solo en este momento RegistroPersonal pasa al estado global 30.
    """
    identidad = _obtener_usuario_actual_rq(current)
    usuario = _normalizar_usuario(identidad["Usuario"])

    try:
        contexto = db.execute(
            text("""
                SELECT
                    rl."IdRetiroLaboral",
                    rl."IdRegistroPersonal",
                    rl."EstadoCasoRRLL",
                    rl."Activo",
                    rq."IdRQOperaciones",
                    rq."IdPazYSalvo",
                    rq."EstadoRQ",
                    rq."EnviadoRRLL",
                    psd."EstadoPazYSalvo"
                FROM public."RetiroLaboral" rl
                INNER JOIN LATERAL (
                    SELECT rq2.*
                    FROM public."RQOperaciones" rq2
                    WHERE rq2."IdRetiroLaboral" = rl."IdRetiroLaboral"
                      AND COALESCE(rq2."Activo", true) = true
                    ORDER BY rq2."IdRQOperaciones" DESC
                    LIMIT 1
                ) rq ON true
                LEFT JOIN LATERAL (
                    SELECT d."EstadoPazYSalvo"
                    FROM public."PazYSalvoOperacionesDetalle" d
                    WHERE d."IdPazYSalvo" = rq."IdPazYSalvo"
                    ORDER BY d."IdPazYSalvoDetalle" DESC
                    LIMIT 1
                ) psd ON true
                WHERE rl."IdRetiroLaboral" = :id_retiro_laboral
                LIMIT 1;
            """),
            {"id_retiro_laboral": id_retiro_laboral},
        ).mappings().first()

        if not contexto:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=(
                    "No se encontró un retiro con RQ activo para realizar "
                    "el envío a Relaciones Laborales."
                ),
            )

        estado_caso_rrll = str(
            contexto["EstadoCasoRRLL"] or ""
        ).strip().upper()

        if estado_caso_rrll != "PENDIENTE_OPERACIONES":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    "El retiro ya no está pendiente en Operaciones. "
                    f"Estado actual: {estado_caso_rrll or 'SIN ESTADO'}."
                ),
            )

        if not bool(contexto["Activo"]):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="El retiro se encuentra inactivo y no puede enviarse a RRLL.",
            )

        if bool(contexto["EnviadoRRLL"]):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="El RQ ya fue enviado a Relaciones Laborales.",
            )

        estado_rq = str(contexto["EstadoRQ"] or "").strip().upper()
        if estado_rq != "LISTO_PARA_ENVIO":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    "El RQ todavía no está listo para envío. "
                    "Debe guardar el RQ con el Paz y Salvo en estado CERRADO."
                ),
            )

        estado_paz_salvo = str(
            contexto["EstadoPazYSalvo"] or ""
        ).strip().upper()

        if estado_paz_salvo != "CERRADO":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    "El Paz y Salvo debe estar CERRADO antes de enviar "
                    "el caso a Relaciones Laborales."
                ),
            )

        db.execute(
            text("""
                UPDATE public."RQOperaciones"
                SET
                    "EstadoRQ" = 'ENVIADO_RRLL',
                    "EnviadoRRLL" = true,
                    "FechaEnvioRRLL" = CURRENT_TIMESTAMP,
                    "EnviadoSeleccion" = CASE
                        WHEN "TipoRQ" = 'REEMPLAZO'
                             AND COALESCE("RequiereReemplazo", false) = true
                        THEN true
                        ELSE "EnviadoSeleccion"
                    END,
                    "FechaEnvioSeleccion" = CASE
                        WHEN "TipoRQ" = 'REEMPLAZO'
                             AND COALESCE("RequiereReemplazo", false) = true
                        THEN COALESCE("FechaEnvioSeleccion", CURRENT_TIMESTAMP)
                        ELSE "FechaEnvioSeleccion"
                    END,
                    "UsuarioActualizacion" = :usuario,
                    "FechaActualizacion" = CURRENT_TIMESTAMP
                WHERE "IdRQOperaciones" = :id_rq_operaciones
                  AND COALESCE("Activo", true) = true;
            """),
            {
                "usuario": usuario,
                "id_rq_operaciones": contexto["IdRQOperaciones"],
            },
        )

        db.execute(
            text("""
                UPDATE public."RetiroLaboral"
                SET
                    "EstadoCasoRRLL" = 'ABIERTO',
                    "FechaEnvioOperaciones" = COALESCE(
                        "FechaEnvioOperaciones",
                        CURRENT_TIMESTAMP
                    ),
                    "FechaActualizacion" = CURRENT_TIMESTAMP,
                    "UsuarioActualizacion" = :usuario
                WHERE "IdRetiroLaboral" = :id_retiro_laboral;
            """),
            {
                "usuario": usuario,
                "id_retiro_laboral": id_retiro_laboral,
            },
        )

        db.execute(
            text("""
                UPDATE public."RegistroPersonal"
                SET
                    "IdEstadoProceso" = :id_estado_proceso,
                    "FechaActualizacion" = CURRENT_TIMESTAMP,
                    "UsuarioActualizacion" = :usuario
                WHERE "IdRegistroPersonal" = :id_registro_personal;
            """),
            {
                "id_estado_proceso": ID_ESTADO_RETIRO_ABIERTO,
                "usuario": usuario,
                "id_registro_personal": contexto["IdRegistroPersonal"],
            },
        )

        db.commit()

        return {
            "success": True,
            "message": (
                "El RQ y el retiro fueron enviados correctamente "
                "a Relaciones Laborales."
            ),
            "data": {
                "IdRetiroLaboral": int(contexto["IdRetiroLaboral"]),
                "IdRQOperaciones": int(contexto["IdRQOperaciones"]),
                "IdPazYSalvo": int(contexto["IdPazYSalvo"]),
                "IdRegistroPersonal": int(contexto["IdRegistroPersonal"]),
                "EstadoRQ": "ENVIADO_RRLL",
                "EnviadoRRLL": True,
                "EstadoCasoRRLL": "ABIERTO",
                "IdEstadoProceso": ID_ESTADO_RETIRO_ABIERTO,
            },
        }

    except HTTPException:
        db.rollback()
        raise

    except Exception as error:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=(
                "No fue posible enviar el retiro a Relaciones Laborales: "
                f"{str(error)}"
            ),
        ) from error


@router.get("/rq/adjuntos/{id_adjunto}/descargar")
def descargar_adjunto_rq(
    id_adjunto: int,
    db: Session = Depends(get_db),
    current=Depends(require_operaciones_retiros),
):
    row = db.execute(
        text("""
            SELECT
                "NombreArchivoOriginal",
                "RutaArchivo",
                "MimeType"
            FROM public."RQOperacionesAdjunto"
            WHERE "IdRQOperacionesAdjunto" = :id_adjunto
              AND COALESCE("Activo", true) = true
              AND COALESCE("Eliminado", false) = false
            LIMIT 1;
        """),
        {"id_adjunto": id_adjunto},
    ).mappings().first()

    if not row:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No se encontró el adjunto RQ solicitado.",
        )

    ruta_archivo = Path(str(row["RutaArchivo"] or ""))

    if not ruta_archivo.exists() or not ruta_archivo.is_file():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="El archivo físico del adjunto RQ no está disponible.",
        )

    return FileResponse(
        path=str(ruta_archivo),
        media_type=(
            str(row["MimeType"] or "").strip()
            or "application/octet-stream"
        ),
        filename=str(
            row["NombreArchivoOriginal"] or ruta_archivo.name
        ),
    )


@router.post("/guardar")
@router.post("/enviar")
async def guardar_retiro_operaciones(
    # Datos base del retiro que posteriormente utilizará RRLL.
    IdRegistroPersonal: int = Form(...),
    IdCliente: int | None = Form(None),
    IdMotivoRetiro: int = Form(...),
    FechaUltimoDiaLaborado: date = Form(...),
    UsuarioActualizacion: str = Form("operaciones"),
    Observacion: str | None = Form(None),

    # Detalle del nuevo Paz y Salvo digital.
    FechaHoraInicioDiligenciamiento: datetime = Form(...),
    ElaboradoPor: str = Form(...),
    DescripcionMotivoRetiro: str = Form(...),

    Locker: str = Form("NO APLICA"),
    Llaves: str = Form("NO APLICA"),
    EntregaHerramientas: str = Form("NO APLICA"),
    TarjetaControlAcceso: str = Form("NO APLICA"),

    EntregaGuantes: str = Form("NO APLICA"),
    EntregaMonogafas: str = Form("NO APLICA"),
    EntregaPeto: str = Form("NO APLICA"),
    ObservacionesEntrega: str = Form(""),

    AplicaDescuento: str = Form(...),
    ValorDescuento: Decimal | None = Form(None),
    NovedadesNomina: str | None = Form(None),

    PendienteEntregaUniforme: str = Form("NO APLICA"),
    UniformePatogeno: str = Form("NO APLICA"),
    Botas: str = Form("NO APLICA"),
    Zapatos: str = Form("NO APLICA"),
    Chaqueta: str = Form("NO APLICA"),
    CarnetAlpArl: str = Form("NO APLICA"),
    PendientePagoVacunas: str = Form("NO APLICA"),

    UsuariosClavesDispositivos: str | None = Form(None),
    CorreoSupervisora: str | None = Form(None),
    EstadoPazYSalvo: str = Form(...),
    BloquesPerfilJSON: str | None = Form(None),

    # Compatibilidad con el flujo anterior.
    # El flujo actual genera automáticamente el PDF oficial cuando
    # no se recibe un archivo manual.
    archivo: UploadFile | None = File(None),

    # Evidencias de Operaciones asociadas al Paz y Salvo.
    novedadesNominaArchivo: list[UploadFile] | None = File(None),
    formatoDescuentoVacunasArchivo: UploadFile | None = File(None),
    fotoCarnetAccesoArchivo: UploadFile | None = File(None),
    fotoListadoHerramientasArchivo: UploadFile | None = File(None),
    fotoPlanillaNominaArchivo: UploadFile | None = File(None),

    db: Session = Depends(get_db),
    current=Depends(require_operaciones_retiros),
):
    """
    Envía a RRLL el retiro iniciado por Operaciones.

    Conserva el flujo existente y agrega el detalle digital del Paz y Salvo:

    - RetiroLaboral.
    - PazYSalvoOperaciones.
    - PazYSalvoOperacionesDetalle.
    - Paz y salvo PDF generado automáticamente y registrado en
      RetiroLaboralAdjunto como tipo 2.
    - Compatibilidad con un PDF manual si algún flujo anterior todavía
      lo envía.
    - Actualización del trabajador a estado de retiro abierto.

    Las evidencias adicionales del formulario se guardan en
    PazYSalvoOperacionesEvidencia. RRLL podrá consultarlas junto al Paz
    y Salvo, mientras Nómina conservará únicamente el PDF oficial.
    """

    ruta_fisica: Path | None = None
    contenido: bytes | None = None
    nombre_original: str | None = None
    ruta_archivo_bd: str | None = None
    id_adjunto: int | None = None
    rutas_evidencias_creadas: list[Path] = []
    ids_evidencias: list[int] = []

    try:
        usuario = _normalizar_usuario(UsuarioActualizacion)
        observacion = _normalizar_texto_opcional(Observacion)

        elaborado_por = _normalizar_texto_requerido(
            ElaboradoPor,
            "ElaboradoPor",
        )
        descripcion_motivo = _normalizar_texto_requerido(
            DescripcionMotivoRetiro,
            "DescripcionMotivoRetiro",
        )

        locker = _normalizar_opcion(
            Locker,
            "Locker",
            OPCIONES_ENTREGA_GENERAL,
        )
        llaves = _normalizar_opcion(
            Llaves,
            "Llaves",
            OPCIONES_ENTREGA_GENERAL,
        )
        entrega_herramientas = _normalizar_opcion(
            EntregaHerramientas,
            "EntregaHerramientas",
            OPCIONES_ENTREGA_GENERAL,
        )
        tarjeta_control_acceso = _normalizar_opcion(
            TarjetaControlAcceso,
            "TarjetaControlAcceso",
            OPCIONES_ENTREGA_GENERAL,
        )

        entrega_guantes = _normalizar_opcion(
            EntregaGuantes,
            "EntregaGuantes",
            OPCIONES_CUMPLIMIENTO,
        )
        entrega_monogafas = _normalizar_opcion(
            EntregaMonogafas,
            "EntregaMonogafas",
            OPCIONES_CUMPLIMIENTO,
        )
        entrega_peto = _normalizar_opcion(
            EntregaPeto,
            "EntregaPeto",
            OPCIONES_ENTREGA_GENERAL,
        )
        observaciones_entrega = _normalizar_texto_opcional(ObservacionesEntrega) or ""

        aplica_descuento = _normalizar_opcion(
            AplicaDescuento,
            "AplicaDescuento",
            OPCIONES_SI_NO,
        )
        valor_descuento = _validar_valor_descuento(
            aplica_descuento,
            ValorDescuento,
        )
        # La observación de nómina es opcional para todos los perfiles.
        novedades_nomina = _normalizar_texto_opcional(NovedadesNomina)

        pendiente_entrega_uniforme = _normalizar_opcion(
            PendienteEntregaUniforme,
            "PendienteEntregaUniforme",
            OPCIONES_SI_NO_HISTORICO,
        )
        uniforme_patogeno = _normalizar_opcion(
            UniformePatogeno,
            "UniformePatogeno",
            OPCIONES_SI_NO_HISTORICO,
        )
        botas = _normalizar_opcion(
            Botas,
            "Botas",
            OPCIONES_SI_NO_HISTORICO,
        )
        zapatos = _normalizar_opcion(
            Zapatos,
            "Zapatos",
            OPCIONES_SI_NO_HISTORICO,
        )
        chaqueta = _normalizar_opcion(
            Chaqueta,
            "Chaqueta",
            OPCIONES_SI_NO_HISTORICO,
        )
        carnet_alp_arl = _normalizar_opcion(
            CarnetAlpArl,
            "CarnetAlpArl",
            OPCIONES_SI_NO_HISTORICO,
        )
        pendiente_pago_vacunas = _normalizar_opcion(
            PendientePagoVacunas,
            "PendientePagoVacunas",
            OPCIONES_SI_NO_HISTORICO,
        )

        # QA: estos siete campos historicos son VARCHAR(2) en PostgreSQL.
        # El formulario nuevo no los diligencia; "NO APLICA" no cabe y tampoco
        # representa una respuesta del trabajador. Guardar NULL, sin alterar
        # los valores historicos validos SI/NO que si se reciban.
        pendiente_entrega_uniforme = (None if pendiente_entrega_uniforme == "NO APLICA" else pendiente_entrega_uniforme)
        uniforme_patogeno = (None if uniforme_patogeno == "NO APLICA" else uniforme_patogeno)
        botas = (None if botas == "NO APLICA" else botas)
        zapatos = (None if zapatos == "NO APLICA" else zapatos)
        chaqueta = (None if chaqueta == "NO APLICA" else chaqueta)
        carnet_alp_arl = (None if carnet_alp_arl == "NO APLICA" else carnet_alp_arl)
        pendiente_pago_vacunas = (None if pendiente_pago_vacunas == "NO APLICA" else pendiente_pago_vacunas)

        usuarios_claves_dispositivos = _normalizar_texto_opcional(
            UsuariosClavesDispositivos
        )
        correo_supervisora = _normalizar_texto_opcional(CorreoSupervisora)
        estado_paz_y_salvo = _normalizar_opcion(
            EstadoPazYSalvo,
            "EstadoPazYSalvo",
            OPCIONES_ESTADO_PAZ_SALVO,
        )

        if archivo is not None:
            contenido = await archivo.read()
            _validar_archivo_pdf(archivo, contenido)

        evidencias_recibidas: list[tuple[str, UploadFile, bytes]] = []

        if novedadesNominaArchivo:
            for archivo_evidencia in novedadesNominaArchivo:
                contenido_evidencia = await archivo_evidencia.read()
                _validar_evidencia(
                    archivo_evidencia,
                    contenido_evidencia,
                    "NOVEDADES_NOMINA",
                )
                evidencias_recibidas.append((
                    "NOVEDADES_NOMINA",
                    archivo_evidencia,
                    contenido_evidencia,
                ))

        evidencias_simples = [
            ("FORMATO_DESCUENTO_VACUNAS", formatoDescuentoVacunasArchivo),
            ("CARNET_ACCESO", fotoCarnetAccesoArchivo),
            ("LISTADO_HERRAMIENTAS", fotoListadoHerramientasArchivo),
            ("PLANILLA_NOMINA", fotoPlanillaNominaArchivo),
        ]

        for tipo_evidencia, archivo_evidencia in evidencias_simples:
            if archivo_evidencia is None:
                continue

            contenido_evidencia = await archivo_evidencia.read()
            _validar_evidencia(
                archivo_evidencia,
                contenido_evidencia,
                tipo_evidencia,
            )
            evidencias_recibidas.append((
                tipo_evidencia,
                archivo_evidencia,
                contenido_evidencia,
            ))

        trabajador = _obtener_trabajador_contratado(
            db=db,
            id_registro_personal=IdRegistroPersonal,
        )

        motivo = _validar_motivo_retiro(
            db=db,
            id_motivo_retiro=IdMotivoRetiro,
        )

        _validar_retiro_abierto(
            db=db,
            id_registro_personal=IdRegistroPersonal,
        )

        # El front puede enviar el cliente validado/corregido por Operaciones.
        # Se mantiene compatibilidad con el flujo anterior: si no llega
        # IdCliente, se utiliza la última asignación registrada del trabajador.
        id_cliente = IdCliente

        if id_cliente is None:
            id_cliente = _obtener_cliente_actual(
                db=db,
                id_registro_personal=IdRegistroPersonal,
            )

        if id_cliente is None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    "No fue posible determinar el cliente actual del trabajador. "
                    "Valida y selecciona un cliente antes de enviar el retiro."
                ),
            )

        cliente = _validar_cliente(
            db=db,
            id_cliente=int(id_cliente),
        )
        id_cliente = int(cliente["IdCliente"])

        # Vincular el retiro al contrato exacto antes de crear cualquier registro.
        id_vinculacion_laboral = _obtener_vinculacion_para_retiro(
            db=db,
            id_registro_personal=IdRegistroPersonal,
            fecha_ultimo_dia_laborado=FechaUltimoDiaLaborado,
        )

        query_insert_retiro = text("""
            INSERT INTO public."RetiroLaboral" (
                "IdVinculacionLaboral",
                "IdRegistroPersonal",
                "IdCliente",
                "IdMotivoRetiro",
                "FechaProceso",
                "FechaRetiro",
                "FechaEnvioOperaciones",
                "ObservacionGeneral",
                "EstadoCasoRRLL",
                "Activo",
                "FechaCreacion",
                "FechaActualizacion",
                "UsuarioActualizacion"
            )
            VALUES (
                :id_vinculacion_laboral,
                :id_registro_personal,
                :id_cliente,
                :id_motivo_retiro,
                CURRENT_DATE,
                :fecha_retiro,
                NULL,
                :observacion_general,
                'PENDIENTE_OPERACIONES',
                true,
                CURRENT_TIMESTAMP,
                CURRENT_TIMESTAMP,
                :usuario_actualizacion
            )
            RETURNING "IdRetiroLaboral";
        """)

        id_retiro_laboral = db.execute(
            query_insert_retiro,
            {
                "id_registro_personal": IdRegistroPersonal,
                "id_vinculacion_laboral": id_vinculacion_laboral,
                "id_cliente": id_cliente,
                "id_motivo_retiro": IdMotivoRetiro,
                "fecha_retiro": FechaUltimoDiaLaborado,
                "observacion_general": observacion,
                "usuario_actualizacion": usuario,
            },
        ).scalar_one()

        query_insert_paz_salvo = text("""
            INSERT INTO public."PazYSalvoOperaciones" (
                "IdRegistroPersonal",
                "FechaUltimoDiaLaborado",
                "Observacion",
                "UsuarioCreacion",
                "FechaCreacion",
                "IdRetiroLaboral",
                "FechaCarga"
            )
            VALUES (
                :id_registro_personal,
                :fecha_ultimo_dia_laborado,
                :observacion,
                :usuario_creacion,
                CURRENT_TIMESTAMP,
                :id_retiro_laboral,
                CURRENT_TIMESTAMP
            )
            RETURNING "IdPazYSalvo";
        """)

        id_paz_y_salvo = db.execute(
            query_insert_paz_salvo,
            {
                "id_registro_personal": IdRegistroPersonal,
                "fecha_ultimo_dia_laborado": FechaUltimoDiaLaborado,
                "observacion": observacion,
                "usuario_creacion": usuario,
                "id_retiro_laboral": id_retiro_laboral,
            },
        ).scalar_one()

        query_insert_detalle = text("""
            INSERT INTO public."PazYSalvoOperacionesDetalle" (
                "IdPazYSalvo",
                "FechaHoraInicioDiligenciamiento",
                "ElaboradoPor",
                "DescripcionMotivoRetiro",
                "Locker",
                "Llaves",
                "EntregaHerramientas",
                "TarjetaControlAcceso",
                "EntregaGuantes",
                "EntregaMonogafas",
                "EntregaPeto",
                "ObservacionesEntrega",
                "AplicaDescuento",
                "ValorDescuento",
                "NovedadesNomina",
                "PendienteEntregaUniforme",
                "UniformePatogeno",
                "Botas",
                "Zapatos",
                "Chaqueta",
                "CarnetAlpArl",
                "PendientePagoVacunas",
                "UsuariosClavesDispositivos",
                "CorreoSupervisora",
                "EstadoPazYSalvo",
                "FechaCreacion",
                "FechaActualizacion",
                "UsuarioActualizacion"
            )
            VALUES (
                :id_paz_y_salvo,
                :fecha_hora_inicio_diligenciamiento,
                :elaborado_por,
                :descripcion_motivo_retiro,
                :locker,
                :llaves,
                :entrega_herramientas,
                :tarjeta_control_acceso,
                :entrega_guantes,
                :entrega_monogafas,
                :entrega_peto,
                :observaciones_entrega,
                :aplica_descuento,
                :valor_descuento,
                :novedades_nomina,
                :pendiente_entrega_uniforme,
                :uniforme_patogeno,
                :botas,
                :zapatos,
                :chaqueta,
                :carnet_alp_arl,
                :pendiente_pago_vacunas,
                :usuarios_claves_dispositivos,
                :correo_supervisora,
                :estado_paz_y_salvo,
                CURRENT_TIMESTAMP,
                CURRENT_TIMESTAMP,
                :usuario_actualizacion
            )
            RETURNING "IdPazYSalvoDetalle";
        """)

        id_paz_y_salvo_detalle = db.execute(
            query_insert_detalle,
            {
                "id_paz_y_salvo": id_paz_y_salvo,
                "fecha_hora_inicio_diligenciamiento": (
                    FechaHoraInicioDiligenciamiento
                ),
                "elaborado_por": elaborado_por,
                "descripcion_motivo_retiro": descripcion_motivo,
                "locker": locker,
                "llaves": llaves,
                "entrega_herramientas": entrega_herramientas,
                "tarjeta_control_acceso": tarjeta_control_acceso,
                "entrega_guantes": entrega_guantes,
                "entrega_monogafas": entrega_monogafas,
                "entrega_peto": entrega_peto,
                "observaciones_entrega": observaciones_entrega,
                "aplica_descuento": aplica_descuento,
                "valor_descuento": valor_descuento,
                "novedades_nomina": novedades_nomina,
                "pendiente_entrega_uniforme": pendiente_entrega_uniforme,
                "uniforme_patogeno": uniforme_patogeno,
                "botas": botas,
                "zapatos": zapatos,
                "chaqueta": chaqueta,
                "carnet_alp_arl": carnet_alp_arl,
                "pendiente_pago_vacunas": pendiente_pago_vacunas,
                "usuarios_claves_dispositivos": usuarios_claves_dispositivos,
                "correo_supervisora": correo_supervisora,
                "estado_paz_y_salvo": estado_paz_y_salvo,
                "usuario_actualizacion": usuario,
            },
        ).scalar_one()

        # Guardar las respuestas del perfil antes de generar el PDF.
        _guardar_bloques_perfil_en_transaccion(db, current, id_paz_y_salvo, BloquesPerfilJSON)

        # ============================================================
        # PAZ Y SALVO PDF
        # ============================================================
        #
        # Flujo actual:
        # - Si un cliente anterior todavía envía un PDF manual, se conserva.
        # - Si no llega archivo, se genera automáticamente el PDF oficial
        #   a partir de PazYSalvoOperaciones + PazYSalvoOperacionesDetalle.
        #
        # En ambos casos el documento se registra como:
        # IdTipoDocumentoRetiro = 2 (Paz y salvo).
        # ============================================================

        if archivo is not None and contenido is not None:
            nombre_original = Path(str(archivo.filename)).name
        else:
            buffer_pdf = generar_paz_salvo_operaciones_pdf(
                db=db,
                id_paz_y_salvo=id_paz_y_salvo,
            )
            contenido = buffer_pdf.getvalue()
            buffer_pdf.close()

            nombre_original = (
                f"paz_salvo_operaciones_{id_retiro_laboral}.pdf"
            )

        if not contenido:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=(
                    "No fue posible obtener el contenido del PDF oficial "
                    "del Paz y Salvo."
                ),
            )

        carpeta_retiro = STORAGE_BASE_DIR / str(id_retiro_laboral)
        carpeta_retiro.mkdir(parents=True, exist_ok=True)

        nombre_guardado = (
            f"paz_salvo_operaciones_"
            f"{id_retiro_laboral}_{uuid4().hex}.pdf"
        )

        ruta_fisica = carpeta_retiro / nombre_guardado
        ruta_fisica.write_bytes(contenido)
        ruta_archivo_bd = str(ruta_fisica).replace("\\", "/")

        query_insert_adjunto = text("""
            INSERT INTO public."RetiroLaboralAdjunto" (
                "IdRetiroLaboral",
                "IdTipoDocumentoRetiro",
                "NombreArchivo",
                "NombreArchivoOriginal",
                "RutaArchivo",
                "ExtensionArchivo",
                "PesoArchivo",
                "Observacion",
                "OrigenArchivo",
                "MimeType",
                "Activo",
                "Eliminado",
                "FechaCreacion",
                "FechaActualizacion",
                "CreadoPor",
                "UsuarioActualizacion"
            )
            VALUES (
                :id_retiro_laboral,
                :id_tipo_documento_retiro,
                :nombre_archivo,
                :nombre_archivo_original,
                :ruta_archivo,
                '.pdf',
                :peso_archivo,
                :observacion,
                'OPERACIONES',
                'application/pdf',
                true,
                false,
                CURRENT_TIMESTAMP,
                CURRENT_TIMESTAMP,
                :creado_por,
                :usuario_actualizacion
            )
            RETURNING "IdRetiroLaboralAdjunto";
        """)

        id_adjunto = db.execute(
            query_insert_adjunto,
            {
                "id_retiro_laboral": id_retiro_laboral,
                "id_tipo_documento_retiro": (
                    ID_TIPO_DOCUMENTO_PAZ_Y_SALVO
                ),
                "nombre_archivo": nombre_guardado,
                "nombre_archivo_original": nombre_original,
                "ruta_archivo": ruta_archivo_bd,
                "peso_archivo": len(contenido),
                "observacion": (
                    observacion
                    or (
                        "Paz y salvo generado automáticamente "
                        "desde el módulo de Operaciones."
                    )
                ),
                "creado_por": usuario,
                "usuario_actualizacion": usuario,
            },
        ).scalar_one()

        carpeta_evidencias = carpeta_retiro / "evidencias_operaciones"
        carpeta_evidencias.mkdir(parents=True, exist_ok=True)

        for tipo_evidencia, archivo_evidencia, contenido_evidencia in evidencias_recibidas:
            id_evidencia, ruta_evidencia = _guardar_evidencia_paz_salvo(
                db=db,
                id_paz_y_salvo=id_paz_y_salvo,
                id_retiro_laboral=id_retiro_laboral,
                tipo_evidencia=tipo_evidencia,
                archivo=archivo_evidencia,
                contenido=contenido_evidencia,
                usuario=usuario,
                carpeta_evidencias=carpeta_evidencias,
            )
            ids_evidencias.append(id_evidencia)
            rutas_evidencias_creadas.append(ruta_evidencia)

        # Mientras el caso siga en PENDIENTE_OPERACIONES no se cambia
        # RegistroPersonal.IdEstadoProceso. El estado global 30 se asignará
        # únicamente cuando Operaciones haga el envío formal a RRLL.
        db.commit()

        return {
            "success": True,
            "message": (
                "El retiro, el detalle y el PDF oficial del Paz y Salvo "
                "fueron guardados correctamente en Operaciones. "
                "El caso aún no ha sido enviado a Relaciones Laborales."
            ),
            "data": {
                "IdRetiroLaboral": id_retiro_laboral,
                "IdPazYSalvo": id_paz_y_salvo,
                "IdPazYSalvoDetalle": id_paz_y_salvo_detalle,
                "IdRetiroLaboralAdjunto": id_adjunto,
                "IdRegistroPersonal": IdRegistroPersonal,
                "NumeroIdentificacion": trabajador["NumeroIdentificacion"],
                "NombreCompleto": trabajador["NombreCompleto"],
                "IdCliente": id_cliente,
                "NombreCliente": str(cliente["NombreCliente"] or "").strip(),
                "IdMotivoRetiro": IdMotivoRetiro,
                "NombreMotivoRetiro": motivo["Nombre"],
                "FechaUltimoDiaLaborado": FechaUltimoDiaLaborado,
                "FechaHoraInicioDiligenciamiento": (
                    FechaHoraInicioDiligenciamiento
                ),
                "EstadoPazYSalvo": estado_paz_y_salvo,
                "EstadoCasoRRLL": "PENDIENTE_OPERACIONES",
                "IdEstadoProceso": int(trabajador["IdEstadoProceso"]),
                "PendienteEnvioRRLL": True,
                "NombreArchivoOriginal": nombre_original,
                "RutaArchivo": ruta_archivo_bd,
                "CantidadEvidenciasOperaciones": len(ids_evidencias),
                "IdsEvidenciasOperaciones": ids_evidencias,
            },
        }

    except HTTPException:
        db.rollback()

        if ruta_fisica and ruta_fisica.exists():
            ruta_fisica.unlink(missing_ok=True)

        for ruta_evidencia in rutas_evidencias_creadas:
            if ruta_evidencia.exists():
                ruta_evidencia.unlink(missing_ok=True)

        raise

    except Exception as error:
        db.rollback()

        if ruta_fisica and ruta_fisica.exists():
            ruta_fisica.unlink(missing_ok=True)

        for ruta_evidencia in rutas_evidencias_creadas:
            if ruta_evidencia.exists():
                ruta_evidencia.unlink(missing_ok=True)

        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=(
                "No fue posible guardar el retiro en Operaciones: "
                f"{str(error)}"
            ),
        ) from error

    finally:
        if archivo is not None:
            await archivo.close()

        archivos_evidencia_cierre: list[UploadFile] = []

        if novedadesNominaArchivo:
            archivos_evidencia_cierre.extend(novedadesNominaArchivo)

        for archivo_evidencia in (
            formatoDescuentoVacunasArchivo,
            fotoCarnetAccesoArchivo,
            fotoListadoHerramientasArchivo,
            fotoPlanillaNominaArchivo,
        ):
            if archivo_evidencia is not None:
                archivos_evidencia_cierre.append(archivo_evidencia)

        for archivo_evidencia in archivos_evidencia_cierre:
            await archivo_evidencia.close()

@router.post("/qa/paz-salvo/62/regenerar-pdf")
def regenerar_pdf_federico_qa(
    db: Session = Depends(get_db),
    current=Depends(require_operaciones_retiros),
):
    '''Operación excepcional SOLO QA: Paz y Salvo 62, retiro 92.

    No edita retiro, detalle, validaciones ni estado RRLL.
    La operación se habilita temporalmente mediante variable de entorno.
    '''
    if os.getenv("ENABLE_QA_PAZ_SALVO_PDF_REGEN", "").strip() != "1":
        raise HTTPException(status_code=404, detail="Regeneración QA deshabilitada.")

    roles = _roles_ids_actuales(current)
    if not roles.intersection({ROL_SUPER_ADMIN, ROL_DESARROLLADOR}):
        raise HTTPException(status_code=403, detail="Solo SuperAdmin o Desarrollador.")

    database_name = db.execute(text("SELECT current_database()")).scalar_one()
    if str(database_name).upper() != "LA_PERFECCION_QA":
        raise HTTPException(status_code=403, detail="Solo se permite en LA_PERFECCION_QA.")

    ruta_nueva = None
    try:
        caso = db.execute(text('''
            SELECT ps."IdPazYSalvo", ps."IdRetiroLaboral", ps."IdRegistroPersonal"
            FROM public."PazYSalvoOperaciones" ps
            WHERE ps."IdPazYSalvo" = 62
            FOR UPDATE OF ps
        ''')).mappings().first()
        if (not caso or int(caso["IdRetiroLaboral"]) != 92
                or int(caso["IdRegistroPersonal"]) != 1869):
            raise HTTPException(status_code=409, detail="Identidad del caso QA no coincide.")

        requisitos = _obtener_requisitos_perfil_pdf(db, 62)
        if not requisitos or len(requisitos["requisitos"]) != 8:
            raise HTTPException(status_code=409, detail="No se identificaron los 8 requisitos del perfil 3.")
        faltantes = [r["nombre"] for r in requisitos["requisitos"]
                     if not str(r.get("estado") or "").strip()
                     or not str(r.get("observacion") or "").strip()]
        if faltantes:
            raise HTTPException(status_code=409, detail={
                "mensaje": "No se regeneró: faltan respuestas u observaciones.",
                "requisitos": faltantes,
            })

        adjuntos = db.execute(text('''
            SELECT "IdRetiroLaboralAdjunto"
            FROM public."RetiroLaboralAdjunto"
            WHERE "IdRetiroLaboral" = 92 AND "IdTipoDocumentoRetiro" = 2
              AND COALESCE("Activo", true) = true
              AND COALESCE("Eliminado", false) = false
            FOR UPDATE
        ''')).mappings().all()
        if len(adjuntos) != 1:
            raise HTTPException(status_code=409, detail="Se esperaba exactamente un PDF oficial activo.")
        id_anterior = int(adjuntos[0]["IdRetiroLaboralAdjunto"])

        buffer_pdf = generar_paz_salvo_operaciones_pdf(db=db, id_paz_y_salvo=62)
        try:
            contenido = buffer_pdf.getvalue()
        finally:
            buffer_pdf.close()
        if not contenido.startswith(b"%PDF"):
            raise HTTPException(status_code=500, detail="El servicio no produjo un PDF válido.")

        carpeta = STORAGE_BASE_DIR / "92"
        carpeta.mkdir(parents=True, exist_ok=True)
        nombre = f"paz_salvo_operaciones_92_qa_regenerado_{uuid4().hex}.pdf"
        ruta_nueva = carpeta / nombre
        ruta_nueva.write_bytes(contenido)

        usuario = _normalizar_usuario(_obtener_usuario_actual_rq(current)["Usuario"])
        db.execute(text('''
            UPDATE public."RetiroLaboralAdjunto"
            SET "Activo" = false, "FechaActualizacion" = CURRENT_TIMESTAMP,
                "UsuarioActualizacion" = :usuario
            WHERE "IdRetiroLaboralAdjunto" = :anterior
        '''), {"usuario": usuario, "anterior": id_anterior})
        id_nuevo = db.execute(text('''
            INSERT INTO public."RetiroLaboralAdjunto" (
                "IdRetiroLaboral", "IdTipoDocumentoRetiro", "NombreArchivo",
                "NombreArchivoOriginal", "RutaArchivo", "ExtensionArchivo",
                "PesoArchivo", "Observacion", "OrigenArchivo", "MimeType",
                "Activo", "Eliminado", "FechaCreacion", "FechaActualizacion",
                "CreadoPor", "UsuarioActualizacion"
            ) VALUES (
                92, 2, :nombre, 'paz_salvo_operaciones_92.pdf', :ruta,
                '.pdf', :peso, :observacion, 'OPERACIONES', 'application/pdf',
                true, false, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP,
                :usuario, :usuario
            ) RETURNING "IdRetiroLaboralAdjunto"
        '''), {
            "nombre": nombre,
            "ruta": str(ruta_nueva).replace("\\", "/"),
            "peso": len(contenido),
            "observacion": "Regeneración controlada QA del PDF perfil ADMINISTRATIVO_CAMPO; adjunto anterior conservado.",
            "usuario": usuario,
        }).scalar_one()
        db.commit()
        return {"success": True, "IdPazYSalvo": 62, "IdRetiroLaboral": 92,
                "IdAdjuntoAnterior": id_anterior, "IdAdjuntoNuevo": int(id_nuevo),
                "CantidadRequisitos": 8}
    except Exception:
        db.rollback()
        if ruta_nueva is not None:
            try:
                ruta_nueva.unlink(missing_ok=True)
            except OSError:
                pass
        raise


@router.post("/qa/paz-salvo/63/regenerar-pdf")
def regenerar_pdf_ingrith_qa(
    db: Session = Depends(get_db),
    current=Depends(require_operaciones_retiros),
):
    '''Operación excepcional SOLO QA: Paz y Salvo 63, retiro 93.

    No edita retiro, detalle, validaciones ni estado RRLL.
    La operación se habilita temporalmente mediante variable de entorno.
    '''
    if os.getenv("ENABLE_QA_PAZ_SALVO_PDF_REGEN", "").strip() != "1":
        raise HTTPException(status_code=404, detail="Regeneración QA deshabilitada.")

    roles = _roles_ids_actuales(current)
    if not roles.intersection({ROL_SUPER_ADMIN, ROL_DESARROLLADOR}):
        raise HTTPException(status_code=403, detail="Solo SuperAdmin o Desarrollador.")

    database_name = db.execute(text("SELECT current_database()")).scalar_one()
    if str(database_name).upper() != "LA_PERFECCION_QA":
        raise HTTPException(status_code=403, detail="Solo se permite en LA_PERFECCION_QA.")

    ruta_nueva = None
    try:
        caso = db.execute(text('''
            SELECT ps."IdPazYSalvo", ps."IdRetiroLaboral", ps."IdRegistroPersonal"
            FROM public."PazYSalvoOperaciones" ps
            WHERE ps."IdPazYSalvo" = 63
            FOR UPDATE OF ps
        ''')).mappings().first()
        if (not caso or int(caso["IdRetiroLaboral"]) != 93
                or str(db.execute(text('SELECT "NumeroIdentificacion" FROM public."RegistroPersonal" WHERE "IdRegistroPersonal" = :id'), {"id": int(caso["IdRegistroPersonal"])}).scalar_one()) != "64748601"):
            raise HTTPException(status_code=409, detail="Identidad del caso QA no coincide.")

        requisitos = _obtener_requisitos_perfil_pdf(db, 63)
        if not requisitos or len(requisitos["requisitos"]) != 8:
            raise HTTPException(status_code=409, detail="No se identificaron los 8 requisitos del perfil 4.")
        faltantes = [r["nombre"] for r in requisitos["requisitos"]
                     if not str(r.get("estado") or "").strip()
                     or not str(r.get("observacion") or "").strip()]
        if faltantes:
            raise HTTPException(status_code=409, detail={
                "mensaje": "No se regeneró: faltan respuestas u observaciones.",
                "requisitos": faltantes,
            })

        adjuntos = db.execute(text('''
            SELECT "IdRetiroLaboralAdjunto"
            FROM public."RetiroLaboralAdjunto"
            WHERE "IdRetiroLaboral" = 93 AND "IdTipoDocumentoRetiro" = 2
              AND COALESCE("Activo", true) = true
              AND COALESCE("Eliminado", false) = false
            FOR UPDATE
        ''')).mappings().all()
        if len(adjuntos) != 1:
            raise HTTPException(status_code=409, detail="Se esperaba exactamente un PDF oficial activo.")
        id_anterior = int(adjuntos[0]["IdRetiroLaboralAdjunto"])

        buffer_pdf = generar_paz_salvo_operaciones_pdf(db=db, id_paz_y_salvo=63)
        try:
            contenido = buffer_pdf.getvalue()
        finally:
            buffer_pdf.close()
        if not contenido.startswith(b"%PDF"):
            raise HTTPException(status_code=500, detail="El servicio no produjo un PDF válido.")

        carpeta = STORAGE_BASE_DIR / "93"
        carpeta.mkdir(parents=True, exist_ok=True)
        nombre = f"paz_salvo_operaciones_93_qa_regenerado_{uuid4().hex}.pdf"
        ruta_nueva = carpeta / nombre
        ruta_nueva.write_bytes(contenido)

        usuario = _normalizar_usuario(_obtener_usuario_actual_rq(current)["Usuario"])
        db.execute(text('''
            UPDATE public."RetiroLaboralAdjunto"
            SET "Activo" = false, "FechaActualizacion" = CURRENT_TIMESTAMP,
                "UsuarioActualizacion" = :usuario
            WHERE "IdRetiroLaboralAdjunto" = :anterior
        '''), {"usuario": usuario, "anterior": id_anterior})
        id_nuevo = db.execute(text('''
            INSERT INTO public."RetiroLaboralAdjunto" (
                "IdRetiroLaboral", "IdTipoDocumentoRetiro", "NombreArchivo",
                "NombreArchivoOriginal", "RutaArchivo", "ExtensionArchivo",
                "PesoArchivo", "Observacion", "OrigenArchivo", "MimeType",
                "Activo", "Eliminado", "FechaCreacion", "FechaActualizacion",
                "CreadoPor", "UsuarioActualizacion"
            ) VALUES (
                93, 2, :nombre, 'paz_salvo_operaciones_93.pdf', :ruta,
                '.pdf', :peso, :observacion, 'OPERACIONES', 'application/pdf',
                true, false, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP,
                :usuario, :usuario
            ) RETURNING "IdRetiroLaboralAdjunto"
        '''), {
            "nombre": nombre,
            "ruta": str(ruta_nueva).replace("\\", "/"),
            "peso": len(contenido),
            "observacion": "Regeneración controlada QA del PDF perfil SUPERVISION_LIDERAZGO; adjunto anterior conservado.",
            "usuario": usuario,
        }).scalar_one()
        db.commit()
        return {"success": True, "IdPazYSalvo": 63, "IdRetiroLaboral": 93,
                "IdAdjuntoAnterior": id_anterior, "IdAdjuntoNuevo": int(id_nuevo),
                "CantidadRequisitos": 8}
    except Exception:
        db.rollback()
        if ruta_nueva is not None:
            try:
                ruta_nueva.unlink(missing_ok=True)
            except OSError:
                pass
        raise
