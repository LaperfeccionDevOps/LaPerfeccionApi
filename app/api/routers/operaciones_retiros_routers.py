# ruff: noqa: B008, BLE001

from datetime import date
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
from sqlalchemy import text
from sqlalchemy.orm import Session

from infrastructure.db.deps import get_db


router = APIRouter(
    prefix="/api/operaciones/retiros",
    tags=["Operaciones - Retiros"],
)


STORAGE_BASE_DIR = Path("C:/LaPerfeccionStorage/rrll/retiros")
ID_TIPO_DOCUMENTO_PAZ_Y_SALVO = 2
ID_ESTADO_CONTRATADO = 25
ID_ESTADO_RETIRO_ABIERTO = 30
TAMANO_MAXIMO_PDF = 10 * 1024 * 1024


def _normalizar_usuario(usuario: str | None) -> str:
    valor = str(usuario or "").strip()
    return valor or "operaciones"


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


@router.post("/enviar")
async def enviar_retiro_a_relaciones_laborales(
    IdRegistroPersonal: int = Form(...),
    IdMotivoRetiro: int = Form(...),
    FechaUltimoDiaLaborado: date = Form(...),
    UsuarioActualizacion: str = Form("operaciones"),
    Observacion: str | None = Form(None),
    archivo: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    """
    Crea el retiro desde Operaciones y deja disponible para RRLL:

    - Motivo de retiro.
    - Último día laborado.
    - Paz y salvo.
    - Fecha de envío desde Operaciones.
    """

    ruta_fisica: Path | None = None

    try:
        usuario = _normalizar_usuario(UsuarioActualizacion)
        observacion = str(Observacion or "").strip() or None

        contenido = await archivo.read()
        _validar_archivo_pdf(archivo, contenido)

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

        id_cliente = _obtener_cliente_actual(
            db=db,
            id_registro_personal=IdRegistroPersonal,
        )

        query_insert_retiro = text("""
            INSERT INTO public."RetiroLaboral" (
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
                :id_registro_personal,
                :id_cliente,
                :id_motivo_retiro,
                CURRENT_DATE,
                :fecha_retiro,
                CURRENT_TIMESTAMP,
                :observacion_general,
                'ABIERTO',
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
                "id_cliente": id_cliente,
                "id_motivo_retiro": IdMotivoRetiro,
                "fecha_retiro": FechaUltimoDiaLaborado,
                "observacion_general": observacion,
                "usuario_actualizacion": usuario,
            },
        ).scalar_one()

        carpeta_retiro = STORAGE_BASE_DIR / str(id_retiro_laboral)
        carpeta_retiro.mkdir(parents=True, exist_ok=True)

        nombre_original = Path(str(archivo.filename)).name
        nombre_guardado = (
            f"paz_salvo_operaciones_{id_retiro_laboral}_{uuid4().hex}.pdf"
        )
        ruta_fisica = carpeta_retiro / nombre_guardado
        ruta_fisica.write_bytes(contenido)

        ruta_archivo_bd = str(ruta_fisica).replace("\\", "/")

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
                "id_tipo_documento_retiro": ID_TIPO_DOCUMENTO_PAZ_Y_SALVO,
                "nombre_archivo": nombre_guardado,
                "nombre_archivo_original": nombre_original,
                "ruta_archivo": ruta_archivo_bd,
                "peso_archivo": len(contenido),
                "observacion": (
                    observacion
                    or "Paz y salvo cargado desde el módulo de Operaciones."
                ),
                "creado_por": usuario,
                "usuario_actualizacion": usuario,
            },
        ).scalar_one()

        query_update_registro_personal = text("""
            UPDATE public."RegistroPersonal"
            SET
                "IdEstadoProceso" = :id_estado_proceso,
                "FechaActualizacion" = CURRENT_TIMESTAMP,
                "UsuarioActualizacion" = :usuario_actualizacion
            WHERE "IdRegistroPersonal" = :id_registro_personal;
        """)

        db.execute(
            query_update_registro_personal,
            {
                "id_estado_proceso": ID_ESTADO_RETIRO_ABIERTO,
                "usuario_actualizacion": usuario,
                "id_registro_personal": IdRegistroPersonal,
            },
        )

        db.commit()

        return {
            "success": True,
            "message": (
                "El retiro fue enviado correctamente a Relaciones Laborales."
            ),
            "data": {
                "IdRetiroLaboral": id_retiro_laboral,
                "IdPazYSalvo": id_paz_y_salvo,
                "IdRetiroLaboralAdjunto": id_adjunto,
                "IdRegistroPersonal": IdRegistroPersonal,
                "NumeroIdentificacion": trabajador["NumeroIdentificacion"],
                "NombreCompleto": trabajador["NombreCompleto"],
                "IdCliente": id_cliente,
                "IdMotivoRetiro": IdMotivoRetiro,
                "NombreMotivoRetiro": motivo["Nombre"],
                "FechaUltimoDiaLaborado": FechaUltimoDiaLaborado,
                "EstadoCasoRRLL": "ABIERTO",
                "IdEstadoProceso": ID_ESTADO_RETIRO_ABIERTO,
                "NombreArchivoOriginal": nombre_original,
                "RutaArchivo": ruta_archivo_bd,
            },
        }

    except HTTPException:
        db.rollback()

        if ruta_fisica and ruta_fisica.exists():
            ruta_fisica.unlink(missing_ok=True)

        raise

    except Exception as error:
        db.rollback()

        if ruta_fisica and ruta_fisica.exists():
            ruta_fisica.unlink(missing_ok=True)

        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=(
                "No fue posible enviar el retiro a Relaciones Laborales: "
                f"{str(error)}"
            ),
        ) from error

    finally:
        await archivo.close()