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
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from infrastructure.db.deps import get_db

from domain.models.documento_proceso_disciplinario import (
    DocumentoProcesoDisciplinario,
)
from domain.models.proceso_disciplinario import (
    ProcesoDisciplinario,
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


TIPOS_CARPETA_DIGITAL_RRLL = {
    "PROCESO_DISCIPLINARIO": 82,
    "PROCESOS_DISCIPLINARIOS": 82,
    "AUSENTISMO": 83,
    "LLAMADO_ATENCION": 86,
    "LLAMADOS_ATENCION": 86,
    "DESCARGOS": 87,
    "SUSPENSION": 93,
}


def normalizar_tipo_documento(
    valor: str | None,
) -> str:
    """
    Normaliza el tipo recibido desde el frontend para poder
    relacionarlo con el catálogo de Carpeta Digital.
    """

    return (
        str(valor or "")
        .strip()
        .upper()
        .replace("Á", "A")
        .replace("É", "E")
        .replace("Í", "I")
        .replace("Ó", "O")
        .replace("Ú", "U")
        .replace("Ü", "U")
        .replace("Ñ", "N")
        .replace(" ", "_")
        .replace("-", "_")
    )


def obtener_tipo_carpeta_digital(
    tipo_documento: str | None,
) -> int | None:
    """
    Retorna el IdTipoDocumentacion de la carpeta de activos
    cuando el tipo seleccionado corresponde a un documento RRLL.

    Otros tipos usados por Operaciones, como EVIDENCIA_OPERACIONES,
    continúan guardándose únicamente en el expediente disciplinario.
    """

    codigo = normalizar_tipo_documento(
        tipo_documento
    )

    return TIPOS_CARPETA_DIGITAL_RRLL.get(
        codigo
    )


def obtener_proceso_o_error(
    db: Session,
    id_proceso: int,
) -> ProcesoDisciplinario:
    proceso = (
        db.query(ProcesoDisciplinario)
        .filter(
            ProcesoDisciplinario
            .IdProcesoDisciplinario
            == id_proceso
        )
        .first()
    )

    if not proceso:
        raise HTTPException(
            status_code=404,
            detail={
                "mensaje": (
                    "Proceso disciplinario no encontrado."
                ),
                "IdProcesoDisciplinario": id_proceso,
            },
        )

    return proceso


def registrar_documento_carpeta_digital(
    db: Session,
    id_registro_personal: int,
    id_tipo_documentacion: int,
    contenido_archivo: bytes,
    nombre_archivo: str,
    formato: str,
) -> int:
    """
    Inserta el archivo en Documentos y crea su relación con el
    trabajador en RelacionTipoDocumentacion.

    No ejecuta commit. La transacción se confirma desde el endpoint
    principal junto con DocumentoProcesoDisciplinario.
    """

    documento_carpeta = (
        db.execute(
            text(
                """
                INSERT INTO public."Documentos" (
                    "IdTipoDocumentacion",
                    "DocumentoCargado",
                    "FechaCreacion",
                    "FechaActualizacion",
                    "Formato",
                    "Nombre"
                )
                VALUES (
                    :id_tipo_documentacion,
                    :documento_cargado,
                    NOW(),
                    NOW(),
                    :formato,
                    :nombre
                )
                RETURNING "IdDocumento"
                """
            ),
            {
                "id_tipo_documentacion": (
                    id_tipo_documentacion
                ),
                "documento_cargado": contenido_archivo,
                "formato": formato,
                "nombre": nombre_archivo,
            },
        )
        .mappings()
        .first()
    )

    if not documento_carpeta:
        raise RuntimeError(
            "No fue posible crear el documento "
            "en la Carpeta Digital."
        )

    id_documento = int(
        documento_carpeta["IdDocumento"]
    )

    db.execute(
        text(
            """
            INSERT INTO public."RelacionTipoDocumentacion" (
                "IdRegistroPersonal",
                "IdDocumento"
            )
            VALUES (
                :id_registro_personal,
                :id_documento
            )
            """
        ),
        {
            "id_registro_personal": (
                id_registro_personal
            ),
            "id_documento": id_documento,
        },
    )

    return id_documento


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



def obtener_proceso_documento_o_error(
    db: Session,
    documento: DocumentoProcesoDisciplinario,
) -> ProcesoDisciplinario:
    """
    Obtiene el proceso relacionado con el documento.
    """

    proceso = (
        db.query(ProcesoDisciplinario)
        .filter(
            ProcesoDisciplinario
            .IdProcesoDisciplinario
            == documento.IdProcesoDisciplinario
        )
        .first()
    )

    if not proceso:
        raise HTTPException(
            status_code=404,
            detail={
                "mensaje": (
                    "No se encontró el proceso disciplinario "
                    "relacionado con el documento."
                ),
                "IdProcesoDisciplinario": (
                    documento.IdProcesoDisciplinario
                ),
                "IdDocumentoProcesoDisciplinario": (
                    documento.IdDocumentoProcesoDisciplinario
                ),
            },
        )

    return proceso


def validar_eliminacion_documento_operaciones(
    proceso: ProcesoDisciplinario,
    documento: DocumentoProcesoDisciplinario,
) -> None:
    """
    Permite eliminar evidencias únicamente mientras el
    expediente siga bajo control de Operaciones y todavía
    no haya sido enviado a Relaciones Laborales.
    """

    origen_proceso = str(
        proceso.OrigenProceso or ""
    ).strip().upper()

    estado_proceso = str(
        proceso.EstadoProceso or ""
    ).strip().upper()

    estados_editables = {
        "BORRADOR_OPERACIONES",
        "PASO_1_COMPLETADO",
        "PASO_2_COMPLETADO",
        "PASO_3_COMPLETADO",
    }

    if origen_proceso != "OPERACIONES":
        raise HTTPException(
            status_code=409,
            detail={
                "mensaje": (
                    "El documento no pertenece a un proceso "
                    "gestionado por Operaciones."
                ),
                "IdDocumentoProcesoDisciplinario": (
                    documento.IdDocumentoProcesoDisciplinario
                ),
                "OrigenProceso": proceso.OrigenProceso,
            },
        )

    if estado_proceso not in estados_editables:
        raise HTTPException(
            status_code=409,
            detail={
                "mensaje": (
                    "La evidencia ya no puede eliminarse porque "
                    "el proceso fue enviado a Relaciones Laborales "
                    "o dejó de estar en una etapa editable."
                ),
                "IdDocumentoProcesoDisciplinario": (
                    documento.IdDocumentoProcesoDisciplinario
                ),
                "IdProcesoDisciplinario": (
                    proceso.IdProcesoDisciplinario
                ),
                "EstadoProceso": proceso.EstadoProceso,
                "EstadosEditables": sorted(
                    estados_editables
                ),
            },
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
    proceso = obtener_proceso_o_error(
        db=db,
        id_proceso=IdProcesoDisciplinario,
    )

    nombre_archivo = Path(
        archivo.filename or ""
    ).name.strip()

    if not nombre_archivo:
        raise HTTPException(
            status_code=400,
            detail="El archivo debe tener un nombre válido.",
        )

    try:
        contenido_archivo = archivo.file.read()
    except OSError as error:
        raise HTTPException(
            status_code=500,
            detail=(
                "No se pudo leer el archivo recibido."
            ),
        ) from error

    if not contenido_archivo:
        raise HTTPException(
            status_code=400,
            detail="El archivo recibido está vacío.",
        )

    codigo_tipo_documento = (
        normalizar_tipo_documento(
            TipoDocumento
        )
    )

    id_tipo_carpeta_digital = (
        obtener_tipo_carpeta_digital(
            codigo_tipo_documento
        )
    )

    extension = (
        Path(nombre_archivo)
        .suffix
        .lstrip(".")
        .lower()
    )

    formato_documento = (
        archivo.content_type
        or extension
        or "application/octet-stream"
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
            buffer.write(
                contenido_archivo
            )

        nuevo = DocumentoProcesoDisciplinario(
            IdProcesoDisciplinario=(
                IdProcesoDisciplinario
            ),
            TipoDocumento=(
                codigo_tipo_documento
                or TipoDocumento
            ),
            NombreArchivo=nombre_archivo,
            RutaArchivo=str(
                ruta_archivo_relativa
            ),
            Observacion=Observacion,
        )

        db.add(nuevo)
        db.flush()

        if id_tipo_carpeta_digital is not None:
            registrar_documento_carpeta_digital(
                db=db,
                id_registro_personal=(
                    proceso.IdRegistroPersonal
                ),
                id_tipo_documentacion=(
                    id_tipo_carpeta_digital
                ),
                contenido_archivo=(
                    contenido_archivo
                ),
                nombre_archivo=nombre_archivo,
                formato=formato_documento,
            )

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
            detail={
                "mensaje": (
                    "El archivo fue recibido, pero no se pudo "
                    "registrar completamente en el expediente "
                    "disciplinario y la Carpeta Digital."
                ),
                "IdProcesoDisciplinario": (
                    IdProcesoDisciplinario
                ),
                "TipoDocumento": (
                    codigo_tipo_documento
                ),
            },
        ) from error

    except (OSError, RuntimeError) as error:
        db.rollback()

        if ruta_archivo_absoluta.exists():
            ruta_archivo_absoluta.unlink(
                missing_ok=True
            )

        raise HTTPException(
            status_code=500,
            detail={
                "mensaje": (
                    "No se pudo guardar el documento de forma "
                    "completa."
                ),
                "IdProcesoDisciplinario": (
                    IdProcesoDisciplinario
                ),
                "TipoDocumento": (
                    codigo_tipo_documento
                ),
            },
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
                "UrlVisualizar": (
                    (
                        f"{url_base}"
                        f"/api/documento-proceso-disciplinario/"
                        f"{documento.IdDocumentoProcesoDisciplinario}"
                        f"/archivo"
                    )
                    if archivo_disponible
                    else None
                ),
                "UrlDescargar": (
                    (
                        f"{url_base}"
                        f"/api/documento-proceso-disciplinario/"
                        f"{documento.IdDocumentoProcesoDisciplinario}"
                        f"/descargar"
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
    "/{id_documento}/descargar",
)
def descargar_archivo_documento(
    id_documento: int,
    db: Session = Depends(get_db),
):
    """
    Descarga el archivo como adjunto.

    Este endpoint se mantiene separado del endpoint
    de visualización para no mezclar los comportamientos
    de Ver y Descargar.
    """

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
        content_disposition_type="attachment",
    )



@router.delete(
    "/{id_documento}",
)
def eliminar_documento(
    id_documento: int,
    db: Session = Depends(get_db),
):
    """
    Elimina una evidencia registrada desde Operaciones.

    Reglas:
    - Solo permite procesos cuyo origen sea OPERACIONES.
    - Solo permite etapas anteriores al envío a RRLL.
    - Elimina el registro de base de datos.
    - Elimina el archivo físico cuando exista.
    """

    documento = obtener_documento_o_error(
        db=db,
        id_documento=id_documento,
    )

    proceso = obtener_proceso_documento_o_error(
        db=db,
        documento=documento,
    )

    validar_eliminacion_documento_operaciones(
        proceso=proceso,
        documento=documento,
    )

    ruta_original = (
        construir_ruta_absoluta_documento(
            documento
        )
    )

    ruta_temporal = None

    if ruta_original:
        marca_tiempo = datetime.now().strftime(
            "%Y%m%d%H%M%S%f"
        )

        ruta_temporal = ruta_original.with_name(
            (
                f".eliminando_"
                f"{documento.IdDocumentoProcesoDisciplinario}_"
                f"{marca_tiempo}_"
                f"{ruta_original.name}"
            )
        )

        try:
            ruta_original.rename(
                ruta_temporal
            )
        except OSError as error:
            raise HTTPException(
                status_code=500,
                detail={
                    "mensaje": (
                        "No se pudo preparar el archivo físico "
                        "para su eliminación."
                    ),
                    "IdDocumentoProcesoDisciplinario": (
                        documento
                        .IdDocumentoProcesoDisciplinario
                    ),
                },
            ) from error

    nombre_archivo = (
        documento.NombreArchivo
        or (
            ruta_original.name
            if ruta_original
            else None
        )
    )

    id_proceso = (
        documento.IdProcesoDisciplinario
    )

    try:
        db.delete(documento)
        db.commit()

    except SQLAlchemyError as error:
        db.rollback()

        if (
            ruta_temporal
            and ruta_temporal.exists()
            and ruta_original
            and not ruta_original.exists()
        ):
            try:
                ruta_temporal.rename(
                    ruta_original
                )
            except OSError:
                pass

        raise HTTPException(
            status_code=500,
            detail={
                "mensaje": (
                    "No se pudo eliminar el registro "
                    "del documento."
                ),
                "IdDocumentoProcesoDisciplinario": (
                    id_documento
                ),
            },
        ) from error

    archivo_fisico_eliminado = (
        ruta_temporal is None
    )

    advertencia = None

    if ruta_temporal:
        try:
            ruta_temporal.unlink(
                missing_ok=True
            )
            archivo_fisico_eliminado = True
        except OSError:
            archivo_fisico_eliminado = False
            advertencia = (
                "El registro fue eliminado, pero quedó "
                "un archivo temporal pendiente de limpieza."
            )

    return {
        "ok": True,
        "mensaje": (
            "La evidencia fue eliminada correctamente."
        ),
        "IdDocumentoProcesoDisciplinario": (
            id_documento
        ),
        "IdProcesoDisciplinario": (
            id_proceso
        ),
        "NombreArchivo": nombre_archivo,
        "ArchivoFisicoEliminado": (
            archivo_fisico_eliminado
        ),
        "Advertencia": advertencia,
    }


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