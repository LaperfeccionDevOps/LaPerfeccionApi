import mimetypes
import shutil
from datetime import datetime
from pathlib import Path

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Request,
    UploadFile,
)
from fastapi.responses import FileResponse
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from infrastructure.db.deps import get_db

from domain.models.documento_proceso_disciplinario import (
    DocumentoProcesoDisciplinario,
)
from domain.schemas.documento_proceso_disciplinario_schema import (
    DocumentoProcesoDisciplinarioCreate,
    DocumentoProcesoDisciplinarioResponse,
    DocumentoProcesoDisciplinarioUpdate,
)


router = APIRouter(
    prefix="/api/documento-proceso-disciplinario",
    tags=["Documento Proceso Disciplinario"],
)


APP_DIR = Path(__file__).resolve().parents[2]
STORAGE_DIR = (APP_DIR / "storage").resolve()


def obtener_documento_o_error(
    db: Session,
    id_documento: int,
) -> DocumentoProcesoDisciplinario:
    documento = (
        db.query(DocumentoProcesoDisciplinario)
        .filter(
            DocumentoProcesoDisciplinario
            .IdDocumentoProcesoDisciplinario
            == id_documento
        )
        .first()
    )

    if not documento:
        raise HTTPException(
            status_code=404,
            detail={
                "mensaje": "Documento no encontrado.",
                "IdDocumentoProcesoDisciplinario": id_documento,
            },
        )

    return documento


def construir_ruta_absoluta_documento(
    documento: DocumentoProcesoDisciplinario,
) -> Path | None:
    """
    Construye y valida la ruta física del documento.

    Devuelve None cuando no hay ruta, la ruta está fuera
    del almacenamiento permitido o el archivo no existe.
    """

    ruta_relativa = str(
        documento.RutaArchivo or ""
    ).strip()

    if not ruta_relativa:
        return None

    ruta_normalizada = Path(
        ruta_relativa.replace("\\", "/")
    )

    ruta_absoluta = (
        APP_DIR / ruta_normalizada
    ).resolve()

    try:
        ruta_absoluta.relative_to(
            STORAGE_DIR
        )
    except ValueError:
        return None

    if not ruta_absoluta.is_file():
        return None

    return ruta_absoluta


def obtener_ruta_absoluta_documento(
    documento: DocumentoProcesoDisciplinario,
) -> Path:
    """
    Obtiene la ruta física del archivo o genera un error
    controlado cuando el registro no tiene un archivo disponible.
    """

    ruta_relativa = str(
        documento.RutaArchivo or ""
    ).strip()

    if not ruta_relativa:
        raise HTTPException(
            status_code=404,
            detail={
                "mensaje": (
                    "El documento no tiene una ruta "
                    "de archivo registrada."
                ),
                "IdDocumentoProcesoDisciplinario": (
                    documento.IdDocumentoProcesoDisciplinario
                ),
            },
        )

    ruta_normalizada = Path(
        ruta_relativa.replace("\\", "/")
    )

    ruta_absoluta = (
        APP_DIR / ruta_normalizada
    ).resolve()

    try:
        ruta_absoluta.relative_to(
            STORAGE_DIR
        )
    except ValueError as error:
        raise HTTPException(
            status_code=403,
            detail={
                "mensaje": (
                    "La ruta del documento no pertenece "
                    "al almacenamiento autorizado."
                ),
                "IdDocumentoProcesoDisciplinario": (
                    documento.IdDocumentoProcesoDisciplinario
                ),
            },
        ) from error

    if not ruta_absoluta.is_file():
        raise HTTPException(
            status_code=404,
            detail={
                "mensaje": (
                    "El registro existe, pero el archivo físico "
                    "no fue encontrado en el servidor."
                ),
                "IdDocumentoProcesoDisciplinario": (
                    documento.IdDocumentoProcesoDisciplinario
                ),
                "NombreArchivo": documento.NombreArchivo,
            },
        )

    return ruta_absoluta


def documento_tiene_archivo_fisico(
    documento: DocumentoProcesoDisciplinario,
) -> bool:
    return (
        construir_ruta_absoluta_documento(
            documento
        )
        is not None
    )


@router.post(
    "/",
    response_model=DocumentoProcesoDisciplinarioResponse,
)
def crear_documento(
    data: DocumentoProcesoDisciplinarioCreate,
    db: Session = Depends(get_db),
):
    nuevo = DocumentoProcesoDisciplinario(
        **data.model_dump()
    )

    try:
        db.add(nuevo)
        db.commit()
        db.refresh(nuevo)

        return nuevo

    except SQLAlchemyError as error:
        db.rollback()

        raise HTTPException(
            status_code=500,
            detail=(
                "No se pudo registrar el documento "
                "del proceso disciplinario."
            ),
        ) from error


@router.post(
    "/upload",
    response_model=DocumentoProcesoDisciplinarioResponse,
)
def subir_documento_proceso_disciplinario(
    IdProcesoDisciplinario: int = Form(...),
    TipoDocumento: str = Form(...),
    Observacion: str | None = Form(None),
    archivo: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    nombre_archivo = Path(
        archivo.filename or ""
    ).name.strip()

    if not nombre_archivo:
        raise HTTPException(
            status_code=400,
            detail="El archivo debe tener un nombre válido.",
        )

    carpeta_destino_absoluta = (
        STORAGE_DIR
        / "rrll"
        / "procesos_disciplinarios"
        / str(IdProcesoDisciplinario)
    )

    carpeta_destino_absoluta.mkdir(
        parents=True,
        exist_ok=True,
    )

    ruta_archivo_absoluta = (
        carpeta_destino_absoluta
        / nombre_archivo
    )

    ruta_archivo_relativa = (
        Path("storage")
        / "rrll"
        / "procesos_disciplinarios"
        / str(IdProcesoDisciplinario)
        / nombre_archivo
    )

    try:
        with ruta_archivo_absoluta.open(
            "wb"
        ) as buffer:
            shutil.copyfileobj(
                archivo.file,
                buffer,
            )

        nuevo = DocumentoProcesoDisciplinario(
            IdProcesoDisciplinario=(
                IdProcesoDisciplinario
            ),
            TipoDocumento=TipoDocumento,
            NombreArchivo=nombre_archivo,
            RutaArchivo=str(
                ruta_archivo_relativa
            ),
            Observacion=Observacion,
        )

        db.add(nuevo)
        db.commit()
        db.refresh(nuevo)

        return nuevo

    except SQLAlchemyError as error:
        db.rollback()

        if ruta_archivo_absoluta.exists():
            ruta_archivo_absoluta.unlink(
                missing_ok=True
            )

        raise HTTPException(
            status_code=500,
            detail=(
                "El archivo fue recibido, pero no se pudo "
                "registrar en la base de datos."
            ),
        ) from error

    except OSError as error:
        db.rollback()

        raise HTTPException(
            status_code=500,
            detail=(
                "No se pudo guardar el archivo en "
                "el almacenamiento del servidor."
            ),
        ) from error

    finally:
        archivo.file.close()


@router.get(
    "/proceso/{id_proceso}",
)
def obtener_documentos_por_proceso(
    id_proceso: int,
    request: Request,
    db: Session = Depends(get_db),
):
    documentos = (
        db.query(
            DocumentoProcesoDisciplinario
        )
        .filter(
            DocumentoProcesoDisciplinario
            .IdProcesoDisciplinario
            == id_proceso
        )
        .order_by(
            DocumentoProcesoDisciplinario
            .FechaCreacion.desc()
        )
        .all()
    )

    url_base = str(
        request.base_url
    ).rstrip("/")

    resultado = []

    for documento in documentos:
        archivo_disponible = (
            documento_tiene_archivo_fisico(
                documento
            )
        )

        resultado.append(
            {
                "IdDocumentoProcesoDisciplinario": (
                    documento
                    .IdDocumentoProcesoDisciplinario
                ),
                "IdProcesoDisciplinario": (
                    documento.IdProcesoDisciplinario
                ),
                "TipoDocumento": (
                    documento.TipoDocumento
                ),
                "NombreArchivo": (
                    documento.NombreArchivo
                ),
                "RutaArchivo": (
                    documento.RutaArchivo
                ),
                "Observacion": (
                    documento.Observacion
                ),
                "FechaCreacion": (
                    documento.FechaCreacion
                ),
                "FechaActualizacion": (
                    documento.FechaActualizacion
                ),
                "ArchivoDisponible": (
                    archivo_disponible
                ),
                "UrlArchivo": (
                    (
                        f"{url_base}"
                        f"/api/documento-proceso-disciplinario/"
                        f"{documento.IdDocumentoProcesoDisciplinario}"
                        f"/archivo"
                    )
                    if archivo_disponible
                    else None
                ),
            }
        )

    return resultado


@router.get(
    "/{id_documento}/archivo",
)
def visualizar_archivo_documento(
    id_documento: int,
    db: Session = Depends(get_db),
):
    documento = obtener_documento_o_error(
        db=db,
        id_documento=id_documento,
    )

    ruta_absoluta = (
        obtener_ruta_absoluta_documento(
            documento
        )
    )

    tipo_contenido, _ = mimetypes.guess_type(
        ruta_absoluta.name
    )

    return FileResponse(
        path=str(ruta_absoluta),
        media_type=(
            tipo_contenido
            or "application/octet-stream"
        ),
        filename=(
            documento.NombreArchivo
            or ruta_absoluta.name
        ),
        content_disposition_type="inline",
    )


@router.get(
    "/{id_documento}",
    response_model=DocumentoProcesoDisciplinarioResponse,
)
def obtener_documento(
    id_documento: int,
    db: Session = Depends(get_db),
):
    return obtener_documento_o_error(
        db=db,
        id_documento=id_documento,
    )


@router.put(
    "/{id_documento}",
    response_model=DocumentoProcesoDisciplinarioResponse,
)
def actualizar_documento(
    id_documento: int,
    data: DocumentoProcesoDisciplinarioUpdate,
    db: Session = Depends(get_db),
):
    documento = obtener_documento_o_error(
        db=db,
        id_documento=id_documento,
    )

    for campo, valor in data.model_dump(
        exclude_unset=True
    ).items():
        setattr(
            documento,
            campo,
            valor,
        )

    documento.FechaActualizacion = (
        datetime.now()
    )

    try:
        db.commit()
        db.refresh(documento)

        return documento

    except SQLAlchemyError as error:
        db.rollback()

        raise HTTPException(
            status_code=500,
            detail=(
                "No se pudo actualizar el documento "
                "del proceso disciplinario."
            ),
        ) from error