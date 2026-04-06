from pathlib import Path
from datetime import datetime
from typing import Optional, List

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session
from sqlalchemy import text

from infrastructure.db.deps import get_db

router = APIRouter(prefix="/api/rrll", tags=["RRLL - Adjuntos"])

APP_DIR = Path(__file__).resolve().parents[2]
BASE_STORAGE = APP_DIR / "storage" / "rrll" / "retiros"


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

    # ✅ NUEVO: ruta relativa para guardar en BD
    ruta_relativa = Path("storage") / "rrll" / "retiros" / str(id_retiro_laboral) / nombre_sanitizado

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
    ruta = Path(ruta_guardada)

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
        db.commit()
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Error eliminando adjunto: {str(e)}")

    ruta = Path(current["RutaArchivo"]) if current["RutaArchivo"] else None
    if ruta and ruta.exists():
        ruta.unlink(missing_ok=True)

    return {"ok": True, "message": "Adjunto eliminado correctamente."}