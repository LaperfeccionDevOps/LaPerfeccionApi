from pathlib import Path
from datetime import datetime
from typing import Optional, List
import shutil
import subprocess
import uuid

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session
from sqlalchemy import text

from infrastructure.db.deps import get_db

router = APIRouter(prefix="/api/rrll", tags=["RRLL - Adjuntos"])

APP_DIR = Path(__file__).resolve().parents[2]
BASE_STORAGE = Path("C:/LaPerfeccionStorage/rrll/retiros")


EXTENSIONES_IMAGEN = {".png", ".jpg", ".jpeg", ".webp"}
EXTENSIONES_WORD = {".doc", ".docx"}


def _resolver_ruta_archivo(row) -> Path:
    """
    Resuelve la ruta física del adjunto sin modificar el registro de base de datos.
    Mantiene compatibilidad con rutas antiguas y con C:/LaPerfeccionStorage.
    """
    ruta_guardada = str(row.get("RutaArchivo") or "").strip()
    id_retiro = row.get("IdRetiroLaboral")
    nombre_archivo = str(row.get("NombreArchivo") or "").strip()

    if not id_retiro or not nombre_archivo:
        raise HTTPException(
            status_code=500,
            detail="El adjunto no tiene información suficiente para localizar el archivo.",
        )

    ruta_storage = BASE_STORAGE / str(id_retiro) / nombre_archivo

    # Las rutas antiguas absolutas de Windows pueden pertenecer a otra instalación.
    if ruta_guardada.upper().startswith("C:"):
        ruta = Path(ruta_guardada)
        if not ruta.exists():
            ruta = ruta_storage
    elif ruta_guardada:
        ruta_configurada = Path(ruta_guardada)
        ruta = (
            ruta_configurada
            if ruta_configurada.is_absolute()
            else APP_DIR / ruta_configurada
        )
    else:
        ruta = ruta_storage

    if not ruta.exists():
        ruta = ruta_storage

    ruta = ruta.resolve()

    if not ruta.exists() or not ruta.is_file():
        raise HTTPException(
            status_code=404,
            detail=(
                "El archivo no fue encontrado en el almacenamiento actual. "
                "Puede ser un adjunto antiguo no disponible."
            ),
        )

    return ruta


def _buscar_libreoffice() -> Path:
    """
    Busca LibreOffice en PATH y en las rutas habituales de Windows.
    Se utiliza únicamente para convertir Word a PDF al presionar Ver.
    """
    candidatos = []

    for ejecutable in ("soffice.com", "soffice.exe", "soffice"):
        encontrado = shutil.which(ejecutable)
        if encontrado:
            candidatos.append(Path(encontrado))

    candidatos.extend(
        [
            Path("C:/Program Files/LibreOffice/program/soffice.com"),
            Path("C:/Program Files/LibreOffice/program/soffice.exe"),
            Path("C:/Program Files (x86)/LibreOffice/program/soffice.com"),
            Path("C:/Program Files (x86)/LibreOffice/program/soffice.exe"),
        ]
    )

    for candidato in candidatos:
        if candidato.exists() and candidato.is_file():
            return candidato.resolve()

    raise HTTPException(
        status_code=503,
        detail=(
            "No se encontró LibreOffice en el equipo o servidor. "
            "Es necesario para visualizar archivos Word conservando su formato."
        ),
    )


def _convertir_word_a_pdf(
    ruta_word: Path,
    id_retiro_laboral: int,
) -> Path:
    """
    Convierte DOC/DOCX a PDF mediante LibreOffice en modo headless.
    Crea una copia de vista previa; nunca altera el Word original.
    """
    carpeta_preview = BASE_STORAGE / "_preview" / str(id_retiro_laboral)
    carpeta_preview.mkdir(parents=True, exist_ok=True)

    marca_archivo = ruta_word.stat().st_mtime_ns
    ruta_pdf_cache = carpeta_preview / f"{ruta_word.stem}_{marca_archivo}.pdf"

    if (
        ruta_pdf_cache.exists()
        and ruta_pdf_cache.is_file()
        and ruta_pdf_cache.stat().st_size > 0
    ):
        return ruta_pdf_cache.resolve()

    libreoffice = _buscar_libreoffice()
    carpeta_temporal = carpeta_preview / f"tmp_{uuid.uuid4().hex}"
    perfil_temporal = carpeta_preview / f"profile_{uuid.uuid4().hex}"

    carpeta_temporal.mkdir(parents=True, exist_ok=True)
    perfil_temporal.mkdir(parents=True, exist_ok=True)

    try:
        comando = [
            str(libreoffice),
            f"-env:UserInstallation={perfil_temporal.resolve().as_uri()}",
            "--headless",
            "--convert-to",
            "pdf",
            "--outdir",
            str(carpeta_temporal),
            str(ruta_word),
        ]

        resultado = subprocess.run(
            comando,
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )

        if resultado.returncode != 0:
            detalle = (
                resultado.stderr
                or resultado.stdout
                or "LibreOffice no informó el motivo."
            ).strip()

            raise HTTPException(
                status_code=500,
                detail=f"No se pudo convertir el archivo Word a PDF. Detalle: {detalle}",
            )

        ruta_generada = carpeta_temporal / f"{ruta_word.stem}.pdf"

        if not ruta_generada.exists():
            candidatos_pdf = list(carpeta_temporal.glob("*.pdf"))
            if candidatos_pdf:
                ruta_generada = candidatos_pdf[0]

        if (
            not ruta_generada.exists()
            or not ruta_generada.is_file()
            or ruta_generada.stat().st_size == 0
        ):
            raise HTTPException(
                status_code=500,
                detail="LibreOffice terminó el proceso, pero no generó el PDF.",
            )

        shutil.move(str(ruta_generada), str(ruta_pdf_cache))
        return ruta_pdf_cache.resolve()

    except subprocess.TimeoutExpired as exc:
        raise HTTPException(
            status_code=504,
            detail="La conversión del archivo Word tardó más de 120 segundos.",
        ) from exc

    finally:
        shutil.rmtree(carpeta_temporal, ignore_errors=True)
        shutil.rmtree(perfil_temporal, ignore_errors=True)


def _nombre_inline(nombre: str) -> str:
    """
    Evita caracteres que puedan romper el encabezado Content-Disposition.
    """
    nombre_limpio = str(nombre or "archivo").replace('"', "").replace("\r", "")
    return nombre_limpio.replace("\n", "")


class RetiroAdjuntoOut(BaseModel):
    IdRetiroLaboralAdjunto: int
    IdRetiroLaboral: int
    IdTipoDocumentoRetiro: int
    NombreArchivo: Optional[str] = None
    NombreArchivoOriginal: Optional[str] = None
    RutaArchivo: Optional[str] = None
    ExtensionArchivo: Optional[str] = None
    PesoArchivo: Optional[int] = None
    Observacion: Optional[str] = None
    OrigenArchivo: Optional[str] = None
    MimeType: Optional[str] = None
    Activo: Optional[bool] = True


def _validar_pdf(file: UploadFile):
    if not file.filename:
        raise HTTPException(status_code=400, detail="El archivo es obligatorio.")

    extension = Path(file.filename).suffix.lower()
    if extension != ".pdf":
        raise HTTPException(status_code=400, detail="Solo se permiten archivos PDF.")

    content_type = (file.content_type or "").lower()
    if content_type not in ("application/pdf", "application/octet-stream"):
        raise HTTPException(status_code=400, detail="El archivo debe ser un PDF válido.")

    return extension, content_type


def _validar_archivo(file: UploadFile):
    if not file.filename:
        raise HTTPException(status_code=400, detail="El archivo es obligatorio.")

    extension = Path(file.filename).suffix.lower()

    extensiones_permitidas = {
        ".pdf",
        ".png",
        ".jpg",
        ".jpeg",
        ".webp",
        ".doc",
        ".docx",
    }

    mime_types_permitidos = {
        "application/pdf",
        "application/octet-stream",
        "image/png",
        "image/jpg",
        "image/jpeg",
        "image/webp",
        "application/msword",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    }

    if extension not in extensiones_permitidas:
        raise HTTPException(
            status_code=400,
            detail="Solo se permiten archivos PDF, imágenes (PNG, JPG, JPEG, WEBP) o Word (DOC, DOCX)."
        )

    content_type = (file.content_type or "").lower()

    if content_type and content_type not in mime_types_permitidos:
        raise HTTPException(
            status_code=400,
            detail="El tipo de archivo no es válido. Solo se permiten PDF, imágenes o Word."
        )

    return extension, content_type or "application/octet-stream"


def _obtener_retiro_activo(db: Session, id_retiro_laboral: int):
    q = text("""
        SELECT
            "IdRetiroLaboral",
            "IdRegistroPersonal",
            "Activo"
        FROM public."RetiroLaboral"
        WHERE "IdRetiroLaboral" = :id_retiro_laboral
        LIMIT 1;
    """)
    row = db.execute(q, {"id_retiro_laboral": id_retiro_laboral}).mappings().first()
    if not row:
        raise HTTPException(status_code=404, detail="No existe el retiro laboral.")
    return row


@router.get("/retiro/{id_retiro_laboral}/adjuntos", response_model=List[RetiroAdjuntoOut])
def listar_adjuntos_retiro(
    id_retiro_laboral: int,
    db: Session = Depends(get_db)
):
    _obtener_retiro_activo(db, id_retiro_laboral)

    q = text("""
        SELECT
            "IdRetiroLaboralAdjunto",
            "IdRetiroLaboral",
            "IdTipoDocumentoRetiro",
            "NombreArchivo",
            COALESCE("NombreArchivoOriginal", "NombreArchivo") AS "NombreArchivoOriginal",
            "RutaArchivo",
            "ExtensionArchivo",
            "PesoArchivo",
            "Observacion",
            COALESCE("OrigenArchivo", 'MANUAL') AS "OrigenArchivo",
            "MimeType",
            COALESCE("Activo", true) AS "Activo"
        FROM public."RetiroLaboralAdjunto"
        WHERE "IdRetiroLaboral" = :id_retiro_laboral
          AND COALESCE("Eliminado", false) = false
          AND COALESCE("Activo", true) = true
        ORDER BY "IdTipoDocumentoRetiro", "IdRetiroLaboralAdjunto";
    """)
    rows = db.execute(q, {"id_retiro_laboral": id_retiro_laboral}).mappings().all()
    return [dict(r) for r in rows]


@router.post("/retiro/{id_retiro_laboral}/adjuntos", response_model=RetiroAdjuntoOut)
async def cargar_adjunto_retiro(
    id_retiro_laboral: int,
    IdTipoDocumentoRetiro: int = Form(...),
    UsuarioActualizacion: Optional[str] = Form(None),
    Observacion: Optional[str] = Form(None),
    file: UploadFile = File(...),
    db: Session = Depends(get_db)
):
    _obtener_retiro_activo(db, id_retiro_laboral)

    extension, content_type = _validar_archivo(file)

    carpeta_retiro = BASE_STORAGE / str(id_retiro_laboral)
    carpeta_retiro.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    nombre_sanitizado = f"retiro_{id_retiro_laboral}_tipo_{IdTipoDocumentoRetiro}_{timestamp}{extension}"
    ruta_fisica = carpeta_retiro / nombre_sanitizado

    ruta_relativa = ruta_fisica

    contenido = await file.read()
    if not contenido:
        raise HTTPException(status_code=400, detail="El archivo está vacío.")

    with open(ruta_fisica, "wb") as f:
        f.write(contenido)

    peso_archivo = len(contenido)

    try:
        q_old = text("""
            SELECT
                "IdRetiroLaboralAdjunto",
                "RutaArchivo"
            FROM public."RetiroLaboralAdjunto"
            WHERE "IdRetiroLaboral" = :id_retiro_laboral
              AND "IdTipoDocumentoRetiro" = :id_tipo_documento_retiro
              AND COALESCE("Eliminado", false) = false
              AND COALESCE("Activo", true) = true
            ORDER BY "IdRetiroLaboralAdjunto" DESC
            LIMIT 1;
        """)
        old = db.execute(q_old, {
            "id_retiro_laboral": id_retiro_laboral,
            "id_tipo_documento_retiro": IdTipoDocumentoRetiro
        }).mappings().first()

        if old:
            q_desactivar = text("""
                UPDATE public."RetiroLaboralAdjunto"
                SET
                    "Activo" = false,
                    "Eliminado" = true,
                    "FechaActualizacion" = now(),
                    "UsuarioActualizacion" = :usuario_actualizacion
                WHERE "IdRetiroLaboralAdjunto" = :id_adjunto;
            """)
            db.execute(q_desactivar, {
                "id_adjunto": old["IdRetiroLaboralAdjunto"],
                "usuario_actualizacion": UsuarioActualizacion
            })

        q_insert = text("""
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
                :extension_archivo,
                :peso_archivo,
                :observacion,
                'MANUAL',
                :mime_type,
                true,
                false,
                now(),
                now(),
                :creado_por,
                :usuario_actualizacion
            )
            RETURNING
                "IdRetiroLaboralAdjunto",
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
                "Activo";
        """)

        row = db.execute(q_insert, {
            "id_retiro_laboral": id_retiro_laboral,
            "id_tipo_documento_retiro": IdTipoDocumentoRetiro,
            "nombre_archivo": nombre_sanitizado,
            "nombre_archivo_original": file.filename,
            "ruta_archivo": str(ruta_relativa).replace("\\", "/"),
            "extension_archivo": extension,
            "peso_archivo": peso_archivo,
            "observacion": Observacion,
            "mime_type": content_type,
            "creado_por": UsuarioActualizacion,
            "usuario_actualizacion": UsuarioActualizacion
        }).mappings().first()

        # ✅ TEMPORAL:
        # Si Yeny adjunta manualmente el Paz y Salvo (tipo 2),
        # guardar la fecha de envío a operaciones en RetiroLaboral.
        if IdTipoDocumentoRetiro == 2:
            q_upd_fecha_envio = text("""
                UPDATE public."RetiroLaboral"
                SET
                    "FechaEnvioOperaciones" = now(),
                    "FechaActualizacion" = now(),
                    "UsuarioActualizacion" = :usuario_actualizacion
                WHERE "IdRetiroLaboral" = :id_retiro_laboral;
            """)
            db.execute(q_upd_fecha_envio, {
                "id_retiro_laboral": id_retiro_laboral,
                "usuario_actualizacion": UsuarioActualizacion
            })

        db.commit()
        return dict(row)

    except Exception as e:
        db.rollback()
        if ruta_fisica.exists():
            ruta_fisica.unlink(missing_ok=True)
        raise HTTPException(status_code=500, detail=f"Error guardando adjunto: {str(e)}")


@router.get("/adjuntos/{id_adjunto}", response_model=RetiroAdjuntoOut)
def consultar_adjunto(
    id_adjunto: int,
    db: Session = Depends(get_db)
):
    q = text("""
        SELECT
            "IdRetiroLaboralAdjunto",
            "IdRetiroLaboral",
            "IdTipoDocumentoRetiro",
            "NombreArchivo",
            COALESCE("NombreArchivoOriginal", "NombreArchivo") AS "NombreArchivoOriginal",
            "RutaArchivo",
            "ExtensionArchivo",
            "PesoArchivo",
            "Observacion",
            COALESCE("OrigenArchivo", 'MANUAL') AS "OrigenArchivo",
            "MimeType",
            COALESCE("Activo", true) AS "Activo"
        FROM public."RetiroLaboralAdjunto"
        WHERE "IdRetiroLaboralAdjunto" = :id_adjunto
          AND COALESCE("Eliminado", false) = false
        LIMIT 1;
    """)
    row = db.execute(q, {"id_adjunto": id_adjunto}).mappings().first()
    if not row:
        raise HTTPException(status_code=404, detail="No existe el adjunto.")
    return dict(row)



@router.get("/adjuntos/{id_adjunto}/ver")
def ver_adjunto(
    id_adjunto: int,
    db: Session = Depends(get_db),
):
    """
    Vista previa del adjunto:
    - PDF: se muestra directamente.
    - Imágenes: se muestran directamente.
    - DOC/DOCX: se convierten temporalmente a PDF.
    El archivo original nunca se modifica.
    """
    q = text("""
        SELECT
            "IdRetiroLaboralAdjunto",
            "IdRetiroLaboral",
            "NombreArchivo",
            COALESCE(
                "NombreArchivoOriginal",
                "NombreArchivo"
            ) AS "NombreDescarga",
            "RutaArchivo",
            "ExtensionArchivo",
            "MimeType"
        FROM public."RetiroLaboralAdjunto"
        WHERE "IdRetiroLaboralAdjunto" = :id_adjunto
          AND COALESCE("Eliminado", false) = false
          AND COALESCE("Activo", true) = true
        LIMIT 1;
    """)

    row = db.execute(
        q,
        {"id_adjunto": id_adjunto},
    ).mappings().first()

    if not row:
        raise HTTPException(status_code=404, detail="No existe el adjunto.")

    ruta_original = _resolver_ruta_archivo(row)

    nombre_original = str(
        row["NombreDescarga"]
        or row["NombreArchivo"]
        or ruta_original.name
    ).strip()

    extension = str(
        row["ExtensionArchivo"]
        or Path(nombre_original).suffix
        or ruta_original.suffix
        or ""
    ).strip().lower()

    if extension and not extension.startswith("."):
        extension = f".{extension}"

    if extension == ".pdf":
        ruta_vista = ruta_original
        media_type = "application/pdf"
        nombre_vista = f"{Path(nombre_original).stem}.pdf"

    elif extension in EXTENSIONES_IMAGEN:
        ruta_vista = ruta_original
        media_type_por_extension = {
            ".png": "image/png",
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".webp": "image/webp",
        }
        media_type = media_type_por_extension[extension]
        nombre_vista = nombre_original

    elif extension in EXTENSIONES_WORD:
        ruta_vista = _convertir_word_a_pdf(
            ruta_word=ruta_original,
            id_retiro_laboral=row["IdRetiroLaboral"],
        )
        media_type = "application/pdf"
        nombre_vista = f"{Path(nombre_original).stem}.pdf"

    else:
        raise HTTPException(
            status_code=415,
            detail=(
                "Este tipo de archivo no se puede visualizar. "
                "Utilice el botón Descargar."
            ),
        )

    return FileResponse(
        path=str(ruta_vista),
        media_type=media_type,
        headers={
            "Content-Disposition": (
                f'inline; filename="{_nombre_inline(nombre_vista)}"'
            ),
            "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.get("/adjuntos/{id_adjunto}/descargar")
def descargar_adjunto(
    id_adjunto: int,
    db: Session = Depends(get_db)
):
    q = text("""
        SELECT
            "IdRetiroLaboralAdjunto",
            "IdRetiroLaboral",
            "NombreArchivo",
            COALESCE("NombreArchivoOriginal", "NombreArchivo") AS "NombreDescarga",
            "RutaArchivo",
            "MimeType"
        FROM public."RetiroLaboralAdjunto"
        WHERE "IdRetiroLaboralAdjunto" = :id_adjunto
          AND COALESCE("Eliminado", false) = false
          AND COALESCE("Activo", true) = true
        LIMIT 1;
    """)

    row = db.execute(q, {"id_adjunto": id_adjunto}).mappings().first()
    if not row:
        raise HTTPException(status_code=404, detail="No existe el adjunto.")

    ruta_guardada = row["RutaArchivo"] or ""

# SI ES RUTA ABSOLUTA VIEJA → ignorarla
    if ruta_guardada.startswith("C:"):
     ruta = BASE_STORAGE / str(row["IdRetiroLaboral"]) / row["NombreArchivo"]
    else:
     ruta = APP_DIR / Path(ruta_guardada)

    if ruta.is_absolute():
        if not ruta.exists():
            ruta = BASE_STORAGE / str(row["IdRetiroLaboral"]) / row["NombreArchivo"]
    else:
        ruta = APP_DIR / ruta

    print("DEBUG RUTA_GUARDADA:", ruta_guardada)
    print("DEBUG APP_DIR:", APP_DIR)
    print("DEBUG BASE_STORAGE:", BASE_STORAGE)
    print("DEBUG RUTA_FINAL_ANTES_RESOLVE:", ruta)

    ruta = ruta.resolve()

    print("DEBUG RUTA_FINAL_RESUELTA:", ruta)
    print("DEBUG EXISTE?:", ruta.exists())
    print("RUTA QUE INTENTA ABRIR:", ruta)

    if not ruta.exists():
        raise HTTPException(
            status_code=404,
            detail="El archivo no fue encontrado en el almacenamiento actual. Puede ser un adjunto antiguo no disponible."
        )

    return FileResponse(
        path=str(ruta),
        media_type=row["MimeType"] or "application/pdf",
        filename=row["NombreDescarga"]
    )


@router.delete("/adjuntos/{id_adjunto}")
def eliminar_adjunto(
    id_adjunto: int,
    usuario_actualizacion: Optional[str] = None,
    db: Session = Depends(get_db)
):
    q_get = text("""
        SELECT
            "IdRetiroLaboralAdjunto",
            "IdRetiroLaboral",
            "IdTipoDocumentoRetiro",
            "RutaArchivo"
        FROM public."RetiroLaboralAdjunto"
        WHERE "IdRetiroLaboralAdjunto" = :id_adjunto
          AND COALESCE("Eliminado", false) = false
        LIMIT 1;
    """)
    current = db.execute(q_get, {"id_adjunto": id_adjunto}).mappings().first()
    if not current:
        raise HTTPException(status_code=404, detail="No existe el adjunto.")

    try:
        q_upd = text("""
            UPDATE public."RetiroLaboralAdjunto"
            SET
                "Activo" = false,
                "Eliminado" = true,
                "FechaActualizacion" = now(),
                "UsuarioActualizacion" = :usuario_actualizacion
            WHERE "IdRetiroLaboralAdjunto" = :id_adjunto;
        """)
        db.execute(q_upd, {
            "id_adjunto": id_adjunto,
            "usuario_actualizacion": usuario_actualizacion
        })

        # ✅ TEMPORAL:
        # Si se elimina el Paz y Salvo manual (tipo 2),
        # y ya no queda otro adjunto activo de ese tipo para el retiro,
        # limpiar la FechaEnvioOperaciones.
        if current["IdTipoDocumentoRetiro"] == 2:
            q_existe_otro = text("""
                SELECT 1
                FROM public."RetiroLaboralAdjunto"
                WHERE "IdRetiroLaboral" = :id_retiro_laboral
                  AND "IdTipoDocumentoRetiro" = 2
                  AND COALESCE("Eliminado", false) = false
                  AND COALESCE("Activo", true) = true
                LIMIT 1;
            """)
            otro = db.execute(q_existe_otro, {
                "id_retiro_laboral": current["IdRetiroLaboral"]
            }).first()

            if not otro:
                q_limpiar_fecha = text("""
                    UPDATE public."RetiroLaboral"
                    SET
                        "FechaEnvioOperaciones" = NULL,
                        "FechaActualizacion" = now(),
                        "UsuarioActualizacion" = :usuario_actualizacion
                    WHERE "IdRetiroLaboral" = :id_retiro_laboral;
                """)
                db.execute(q_limpiar_fecha, {
                    "id_retiro_laboral": current["IdRetiroLaboral"],
                    "usuario_actualizacion": usuario_actualizacion
                })

        db.commit()
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Error eliminando adjunto: {str(e)}")

    ruta = Path(current["RutaArchivo"]) if current["RutaArchivo"] else None
    if ruta and ruta.exists():
        ruta.unlink(missing_ok=True)

    return {"ok": True, "message": "Adjunto eliminado correctamente."}