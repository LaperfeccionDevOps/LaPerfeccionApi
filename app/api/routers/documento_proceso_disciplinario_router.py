# ruff: noqa: B008
import io
import mimetypes
import zipfile
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from xml.etree import ElementTree

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Request,
    UploadFile,
)
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel
from PIL import Image as PILImage
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY, TA_LEFT
from reportlab.lib.pagesizes import LETTER
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.lib.utils import ImageReader
from reportlab.platypus import (
    Image,
    KeepTogether,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)
from sqlalchemy import inspect, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from domain.models.documento_proceso_disciplinario import (
    DocumentoProcesoDisciplinario,
)
from domain.models.proceso_disciplinario import ProcesoDisciplinario
from domain.schemas.documento_proceso_disciplinario_schema import (
    DocumentoProcesoDisciplinarioCreate,
    DocumentoProcesoDisciplinarioResponse,
    DocumentoProcesoDisciplinarioUpdate,
)
from infrastructure.db.deps import get_db


router = APIRouter(
    prefix="/api/documento-proceso-disciplinario",
    tags=["Documento Proceso Disciplinario"],
)


APP_DIR = Path(__file__).resolve().parents[2]
STORAGE_DIR = (APP_DIR / "storage").resolve()

# Logos corporativos.
# Se reutilizan exactamente los mismos archivos que ya funcionan
# correctamente en el PDF de Paz y Salvo.
RUTA_LOGO_EMPRESA = (
    APP_DIR
    / "assets"
    / "comunicaciones"
    / "LOGO_EMPRESA.jpeg"
)

RUTA_LOGO_ISSA = (
    APP_DIR
    / "assets"
    / "comunicaciones"
    / "LOGO_ISSA.jpeg.png"
)

RUTA_LOGO_CERTIFICACIONES = (
    APP_DIR
    / "assets"
    / "comunicaciones"
    / "LOGO_CERTIFICACIONES.jpeg"
)

RUTA_FIRMA_YENY = (
    APP_DIR
    / "assets"
    / "comunicaciones"
    / "FIRMA_YENY.png"
)


TIPOS_CARPETA_DIGITAL_RRLL = {
    "PROCESO_DISCIPLINARIO": 82,
    "PROCESOS_DISCIPLINARIOS": 82,
    "AUSENTISMO": 83,
    "LLAMADO_ATENCION": 86,
    "LLAMADOS_ATENCION": 86,
    "DESCARGOS": 87,
    "CARTA_DESCARGOS_FIRMADA": 82,
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


def obtener_respaldo_documento(
    db: Session,
    documento: DocumentoProcesoDisciplinario,
) -> tuple[bytes, str] | None:
    """
    Busca una copia binaria del documento.

    Orden de búsqueda:
    1. Respaldo propio de DocumentoProcesoDisciplinario.
    2. Copia enviada a la Carpeta Digital del trabajador.
    """

    contenido_propio = getattr(
        documento,
        "DocumentoCargado",
        None,
    )

    if contenido_propio:
        formato_propio = str(
            getattr(
                documento,
                "Formato",
                None,
            )
            or ""
        ).strip()

        return (
            bytes(contenido_propio),
            formato_propio,
        )

    id_tipo_documentacion = (
        obtener_tipo_carpeta_digital(
            documento.TipoDocumento
        )
    )

    if id_tipo_documentacion is None:
        return None

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
        return None

    respaldo = (
        db.execute(
            text(
                """
                SELECT
                    d."DocumentoCargado",
                    d."Formato",
                    d."Nombre"
                FROM public."Documentos" d
                INNER JOIN public."RelacionTipoDocumentacion" rtd
                    ON rtd."IdDocumento" = d."IdDocumento"
                WHERE rtd."IdRegistroPersonal" = :id_registro_personal
                  AND d."IdTipoDocumentacion" = :id_tipo_documentacion
                  AND d."Nombre" = :nombre_archivo
                  AND d."DocumentoCargado" IS NOT NULL
                ORDER BY d."IdDocumento" DESC
                LIMIT 1
                """
            ),
            {
                "id_registro_personal": (
                    proceso.IdRegistroPersonal
                ),
                "id_tipo_documentacion": (
                    id_tipo_documentacion
                ),
                "nombre_archivo": (
                    documento.NombreArchivo
                ),
            },
        )
        .mappings()
        .first()
    )

    if not respaldo:
        return None

    contenido = respaldo["DocumentoCargado"]

    if not contenido:
        return None

    return (
        bytes(contenido),
        str(
            respaldo["Formato"]
            or ""
        ).strip(),
    )


def documento_tiene_archivo_disponible(
    db: Session,
    documento: DocumentoProcesoDisciplinario,
) -> bool:
    if (
        construir_ruta_absoluta_documento(
            documento
        )
        is not None
    ):
        return True

    return (
        obtener_respaldo_documento(
            db=db,
            documento=documento,
        )
        is not None
    )


def construir_respuesta_documento(
    db: Session,
    documento: DocumentoProcesoDisciplinario,
    descargar: bool,
):
    """
    Devuelve el archivo físico cuando existe.

    Si el archivo físico ya no está disponible, devuelve la copia
    binaria almacenada en DocumentoProcesoDisciplinario o en la
    Carpeta Digital.
    """

    ruta_absoluta = (
        construir_ruta_absoluta_documento(
            documento
        )
    )

    nombre_archivo = (
        documento.NombreArchivo
        or "documento"
    )

    disposition = (
        "attachment"
        if descargar
        else "inline"
    )

    if ruta_absoluta:
        tipo_contenido, _ = (
            mimetypes.guess_type(
                ruta_absoluta.name
            )
        )

        return FileResponse(
            path=str(ruta_absoluta),
            media_type=(
                tipo_contenido
                or "application/octet-stream"
            ),
            filename=nombre_archivo,
            content_disposition_type=disposition,
        )

    respaldo = obtener_respaldo_documento(
        db=db,
        documento=documento,
    )

    if not respaldo:
        raise HTTPException(
            status_code=404,
            detail={
                "mensaje": (
                    "El registro existe, pero no se encontró "
                    "el archivo físico ni una copia binaria "
                    "disponible."
                ),
                "IdDocumentoProcesoDisciplinario": (
                    documento
                    .IdDocumentoProcesoDisciplinario
                ),
                "NombreArchivo": (
                    documento.NombreArchivo
                ),
            },
        )

    contenido_archivo, formato_guardado = (
        respaldo
    )

    tipo_contenido = (
        formato_guardado
        if "/" in formato_guardado
        else None
    )

    if not tipo_contenido:
        tipo_contenido, _ = (
            mimetypes.guess_type(
                nombre_archivo
            )
        )

    nombre_seguro = (
        nombre_archivo
        .replace('"', "")
        .replace("\r", "")
        .replace("\n", "")
    )

    return StreamingResponse(
        io.BytesIO(contenido_archivo),
        media_type=(
            tipo_contenido
            or "application/octet-stream"
        ),
        headers={
            "Content-Disposition": (
                f'{disposition}; '
                f'filename="{nombre_seguro}"'
            ),
            "Content-Length": str(
                len(contenido_archivo)
            ),
        },
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



class GenerarCartaDescargosRequest(BaseModel):
    IdProcesoDisciplinario: int
    IdDescargoProcesoDisciplinario: int | None = None
    Cargo: str | None = None


def _texto_seguro(valor) -> str:
    return str(valor or "").strip()


def _fecha_espanol(valor) -> str:
    if not valor:
        return ""

    if isinstance(valor, datetime):
        valor = valor.date()

    if isinstance(valor, date):
        meses = (
            "enero", "febrero", "marzo", "abril",
            "mayo", "junio", "julio", "agosto",
            "septiembre", "octubre", "noviembre", "diciembre",
        )
        return f"{valor.day} de {meses[valor.month - 1]} de {valor.year}"

    return _texto_seguro(valor)


def _obtener_valor_modelo(objeto, *nombres):
    for nombre in nombres:
        valor = getattr(objeto, nombre, None)
        if valor not in (None, ""):
            return valor
    return None


def _obtener_nombre_cargo(db: Session, id_cargo) -> str:
    if id_cargo in (None, ""):
        return ""

    try:
        inspector = inspect(db.bind)

        if not inspector.has_table("Cargo", schema="public"):
            return _texto_seguro(id_cargo)

        columnas = {
            columna["name"]
            for columna in inspector.get_columns("Cargo", schema="public")
        }

        columna_id = next(
            (nombre for nombre in ("IdCargo", "IdTipoCargo", "Id") if nombre in columnas),
            None,
        )
        columna_nombre = next(
            (
                nombre
                for nombre in ("Nombre", "NombreCargo", "Cargo", "Descripcion")
                if nombre in columnas
            ),
            None,
        )

        if not columna_id or not columna_nombre:
            return _texto_seguro(id_cargo)

        sql = (
            f'SELECT "{columna_nombre}" AS "NombreCargo" '
            f'FROM public."Cargo" '
            f'WHERE "{columna_id}" = :id_cargo LIMIT 1'
        )

        fila = (
            db.execute(text(sql), {"id_cargo": id_cargo})
            .mappings()
            .first()
        )

        if not fila:
            return _texto_seguro(id_cargo)

        return _texto_seguro(fila["NombreCargo"])

    except Exception:
        return _texto_seguro(id_cargo)


def _fecha_generacion_colombia() -> date:
    zona_colombia = timezone(
        timedelta(hours=-5)
    )

    return datetime.now(
        zona_colombia
    ).date()


def _formatear_hora_colombia(valor) -> str:
    if valor in (None, ""):
        return ""

    if isinstance(valor, datetime):
        valor = valor.time()

    if isinstance(valor, time):
        hora = valor.hour
        minuto = valor.minute
        sufijo = "a. m." if hora < 12 else "p. m."
        hora_12 = hora % 12 or 12
        return f"{hora_12}:{minuto:02d} {sufijo}"

    return _texto_seguro(valor)


def _obtener_horario_agenda_descargos(
    db: Session,
    id_proceso: int,
    fecha_descargo=None,
    hora_descargo=None,
) -> dict:
    sql = """
        SELECT
            a."IdAgendaProcesoDisciplinario",
            a."FechaEvento",
            a."HoraInicio",
            a."HoraFin",
            a."Modalidad",
            a."EstadoAgenda",
            a."LugarCitacion"
        FROM public."AgendaProcesoDisciplinario" a
        WHERE a."IdProcesoDisciplinario" = :id_proceso
          AND a."Activo" = TRUE
        ORDER BY
            CASE
                WHEN :fecha_descargo IS NOT NULL
                 AND a."FechaEvento" = :fecha_descargo
                THEN 0
                ELSE 1
            END,
            CASE
                WHEN :hora_descargo IS NOT NULL
                 AND a."HoraInicio" = :hora_descargo
                THEN 0
                ELSE 1
            END,
            a."FechaEvento" DESC,
            a."HoraInicio" DESC,
            a."IdAgendaProcesoDisciplinario" DESC
        LIMIT 1
    """

    fila = (
        db.execute(
            text(sql),
            {
                "id_proceso": id_proceso,
                "fecha_descargo": fecha_descargo,
                "hora_descargo": hora_descargo,
            },
        )
        .mappings()
        .first()
    )

    if not fila:
        return {}

    return dict(fila)


def _preparar_logo_sin_fondo(
    ruta: Path,
    umbral_blanco: int = 238,
) -> io.BytesIO:
    """
    Limpia el fondo claro del logo principal sin modificar el
    archivo original. Es la misma lógica usada en Paz y Salvo.
    """

    with PILImage.open(ruta) as imagen_original:
        imagen = imagen_original.convert("RGBA")

        pixeles = imagen.load()
        ancho, alto = imagen.size

        for y in range(alto):
            for x in range(ancho):
                rojo, verde, azul, alfa = pixeles[x, y]

                if (
                    rojo >= umbral_blanco
                    and verde >= umbral_blanco
                    and azul >= umbral_blanco
                ):
                    pixeles[x, y] = (
                        rojo,
                        verde,
                        azul,
                        0,
                    )

        canal_alfa = imagen.getchannel("A")
        caja = canal_alfa.getbbox()

        if caja:
            imagen = imagen.crop(caja)

        buffer = io.BytesIO()

        imagen.save(
            buffer,
            format="PNG",
            optimize=True,
        )

        buffer.seek(0)

        return buffer


def _dibujar_logo_canvas(
    canvas,
    ruta: Path,
    x: float,
    y: float,
    ancho_maximo: float,
    alto_maximo: float,
    limpiar_fondo: bool = False,
) -> bool:
    """
    Dibuja un logo manteniendo su proporción original dentro de
    un área máxima. Devuelve True cuando pudo dibujarlo.
    """

    if not ruta.is_file():
        return False

    try:
        fuente = (
            _preparar_logo_sin_fondo(ruta)
            if limpiar_fondo
            else str(ruta)
        )

        imagen = ImageReader(fuente)
        ancho_original, alto_original = imagen.getSize()

        if not ancho_original or not alto_original:
            return False

        escala = min(
            ancho_maximo / float(ancho_original),
            alto_maximo / float(alto_original),
        )

        ancho = float(ancho_original) * escala
        alto = float(alto_original) * escala

        x_centrado = x + (
            ancho_maximo - ancho
        ) / 2

        y_centrado = y + (
            alto_maximo - alto
        ) / 2

        canvas.drawImage(
            imagen,
            x_centrado,
            y_centrado,
            width=ancho,
            height=alto,
            preserveAspectRatio=True,
            mask="auto",
        )

        return True

    except Exception:
        return False


def _dibujar_encabezado_carta_descargos(
    canvas,
    documento,
):
    """
    Encabezado corporativo de la Carta de Descargos.

    Usa exactamente los recursos gráficos aprobados para el
    PDF de Paz y Salvo:
    - Aseos La Perfección.
    - ICONTEC / IQNET.
    - ISSA.

    Se ejecuta tanto en la primera página como en todas las
    páginas posteriores, incluidas las evidencias.
    """

    canvas.saveState()

    # Área superior disponible del documento.
    y_base = LETTER[1] - 2.55 * cm

    # 1. Aseos La Perfección.
    _dibujar_logo_canvas(
        canvas=canvas,
        ruta=RUTA_LOGO_EMPRESA,
        x=1.85 * cm,
        y=y_base,
        ancho_maximo=6.25 * cm,
        alto_maximo=1.90 * cm,
        limpiar_fondo=True,
    )

    # 2. Recurso combinado ICONTEC / IQNET.
    _dibujar_logo_canvas(
        canvas=canvas,
        ruta=RUTA_LOGO_CERTIFICACIONES,
        x=8.20 * cm,
        y=y_base + 0.10 * cm,
        ancho_maximo=3.00 * cm,
        alto_maximo=1.60 * cm,
    )

    # 3. ISSA inmediatamente después de las certificaciones.
    _dibujar_logo_canvas(
        canvas=canvas,
        ruta=RUTA_LOGO_ISSA,
        x=11.25 * cm,
        y=y_base + 0.18 * cm,
        ancho_maximo=1.75 * cm,
        alto_maximo=1.38 * cm,
    )

    canvas.restoreState()


def _crear_firma_yeny_pdf():
    """
    Crea la firma institucional de Yeny para ubicarla en la sección
    'Por la empresa' de la Carta de Descargos.

    Si el archivo no está disponible, retorna None y el PDF conserva
    el respaldo textual actual.
    """

    if not RUTA_FIRMA_YENY.is_file():
        return None

    try:
        firma = Image(
            str(RUTA_FIRMA_YENY)
        )

        ancho_maximo = 6.20 * cm
        alto_maximo = 2.75 * cm

        proporcion = min(
            ancho_maximo / firma.imageWidth,
            alto_maximo / firma.imageHeight,
            1,
        )

        firma.drawWidth = (
            firma.imageWidth * proporcion
        )

        firma.drawHeight = (
            firma.imageHeight * proporcion
        )

        firma.hAlign = "LEFT"

        return firma

    except Exception:
        return None


def _extraer_texto_docx(contenido: bytes) -> str:
    try:
        with zipfile.ZipFile(io.BytesIO(contenido)) as archivo_docx:
            xml = archivo_docx.read("word/document.xml")

        raiz = ElementTree.fromstring(xml)
        namespace = {
            "w": (
                "http://schemas.openxmlformats.org/"
                "wordprocessingml/2006/main"
            )
        }

        parrafos = []
        for parrafo in raiz.findall(".//w:p", namespace):
            fragmentos = [
                nodo.text or ""
                for nodo in parrafo.findall(".//w:t", namespace)
            ]
            texto_parrafo = "".join(fragmentos).strip()
            if texto_parrafo:
                parrafos.append(texto_parrafo)

        return "\n".join(parrafos)

    except Exception:
        return ""


def _obtener_contenido_documento(
    db: Session,
    documento: DocumentoProcesoDisciplinario,
) -> tuple[bytes | None, str]:
    ruta = construir_ruta_absoluta_documento(documento)

    if ruta:
        try:
            return ruta.read_bytes(), _texto_seguro(documento.Formato)
        except OSError:
            pass

    respaldo = obtener_respaldo_documento(db=db, documento=documento)
    if respaldo:
        return respaldo

    return None, ""


def _estilos_carta_descargos():
    estilos_base = getSampleStyleSheet()

    return {
        "normal": ParagraphStyle(
            "CartaDescargosNormal",
            parent=estilos_base["Normal"],
            fontName="Helvetica",
            fontSize=10,
            leading=14,
            alignment=TA_JUSTIFY,
            textColor=colors.black,
            spaceAfter=0,
        ),
        "izquierda": ParagraphStyle(
            "CartaDescargosIzquierda",
            parent=estilos_base["Normal"],
            fontName="Helvetica",
            fontSize=10,
            leading=14,
            alignment=TA_LEFT,
            textColor=colors.black,
            spaceAfter=0,
        ),
        "negrilla": ParagraphStyle(
            "CartaDescargosNegrilla",
            parent=estilos_base["Normal"],
            fontName="Helvetica-Bold",
            fontSize=10,
            leading=14,
            alignment=TA_LEFT,
            textColor=colors.black,
            spaceAfter=0,
        ),
        "titulo": ParagraphStyle(
            "CartaDescargosTitulo",
            parent=estilos_base["Normal"],
            fontName="Helvetica-Bold",
            fontSize=12,
            leading=15,
            alignment=TA_CENTER,
            textColor=colors.black,
            spaceAfter=0,
        ),
        "anexo": ParagraphStyle(
            "CartaDescargosAnexo",
            parent=estilos_base["Normal"],
            fontName="Helvetica-Bold",
            fontSize=11,
            leading=14,
            alignment=TA_LEFT,
            textColor=colors.black,
            spaceAfter=0,
        ),
        "asunto": ParagraphStyle(
            "CartaDescargosAsunto",
            parent=estilos_base["Normal"],
            fontName="Helvetica-Bold",
            fontSize=12.5,
            leading=15,
            alignment=TA_LEFT,
            textColor=colors.black,
            spaceAfter=0,
        ),
    }


def _parrafos_preservando_saltos(contenido: str, estilo: ParagraphStyle) -> list:
    resultado = []
    lineas = (
        str(contenido or "")
        .replace("\r\n", "\n")
        .replace("\r", "\n")
        .split("\n")
    )

    for linea in lineas:
        linea = linea.strip()
        if linea:
            linea_segura = (
                linea.replace("&", "&amp;")
                .replace("<", "&lt;")
                .replace(">", "&gt;")
            )
            resultado.append(Paragraph(linea_segura, estilo))
        else:
            resultado.append(Spacer(1, 0.16 * cm))

    return resultado


def _obtener_datos_descargo(
    db: Session,
    id_proceso: int,
    id_descargo: int | None,
) -> dict:
    filtros = ['d."IdProcesoDisciplinario" = :id_proceso']
    parametros = {"id_proceso": id_proceso}

    if id_descargo is not None:
        filtros.append(
            'd."IdDescargoProcesoDisciplinario" = :id_descargo'
        )
        parametros["id_descargo"] = id_descargo

    sql = (
        'SELECT '
        'd."IdDescargoProcesoDisciplinario", '
        'd."IdProcesoDisciplinario", '
        'd."FechaDescargo", '
        'd."HoraDescargo", '
        'd."DescargoTrabajador", '
        'd."Observaciones", '
        'd."ResponsableDescargo", '
        'd."ObservacionesRRLL", '
        'd."EstadoBorrador" '
        'FROM public."DescargoProcesoDisciplinario" d '
        f'WHERE {" AND ".join(filtros)} '
        'ORDER BY d."IdDescargoProcesoDisciplinario" DESC '
        'LIMIT 1'
    )

    fila = db.execute(text(sql), parametros).mappings().first()

    if not fila:
        raise HTTPException(
            status_code=404,
            detail=(
                "No se encontró el registro de descargos "
                "asociado al proceso disciplinario."
            ),
        )

    return dict(fila)


def _obtener_datos_trabajador(
    db: Session,
    proceso: ProcesoDisciplinario,
) -> dict:
    sql = (
        'SELECT '
        'rp."IdRegistroPersonal", '
        'rp."NumeroIdentificacion", '
        'rp."Nombres", '
        'rp."Apellidos", '
        'rp."IdCargo" '
        'FROM public."RegistroPersonal" rp '
        'WHERE rp."IdRegistroPersonal" = :id_registro_personal '
        'LIMIT 1'
    )

    fila = (
        db.execute(
            text(sql),
            {"id_registro_personal": proceso.IdRegistroPersonal},
        )
        .mappings()
        .first()
    )

    if not fila:
        raise HTTPException(
            status_code=404,
            detail=(
                "No se encontró la información del trabajador "
                "relacionado con el proceso disciplinario."
            ),
        )

    datos = dict(fila)
    datos["NombreCompleto"] = " ".join(
        parte
        for parte in (
            _texto_seguro(datos.get("Nombres")),
            _texto_seguro(datos.get("Apellidos")),
        )
        if parte
    ).strip()
    datos["Cargo"] = _obtener_nombre_cargo(
        db=db,
        id_cargo=datos.get("IdCargo"),
    )

    return datos


def _obtener_evidencias_trabajador(
    db: Session,
    id_proceso: int,
) -> list[DocumentoProcesoDisciplinario]:
    return (
        db.query(DocumentoProcesoDisciplinario)
        .filter(
            DocumentoProcesoDisciplinario.IdProcesoDisciplinario == id_proceso,
            DocumentoProcesoDisciplinario.TipoDocumento == "EVIDENCIA_TRABAJADOR",
        )
        .order_by(DocumentoProcesoDisciplinario.FechaCreacion.asc())
        .all()
    )



def _generar_pdf_carta_descargos(
    db: Session,
    proceso: ProcesoDisciplinario,
    descargo: dict,
    trabajador: dict,
    evidencias: list[DocumentoProcesoDisciplinario],
) -> bytes:
    buffer = io.BytesIO()

    documento_pdf = SimpleDocTemplate(
        buffer,
        pagesize=LETTER,
        rightMargin=2.0 * cm,
        leftMargin=2.0 * cm,
        topMargin=3.55 * cm,
        bottomMargin=1.8 * cm,
        title="Carta de Descargos",
        author="Aseos La Perfección",
    )

    estilos = _estilos_carta_descargos()
    contenido = []

    fecha_generacion = _fecha_generacion_colombia()
    fecha_descargo = descargo.get("FechaDescargo") or fecha_generacion

    nombre_trabajador = _texto_seguro(
        trabajador.get("NombreCompleto")
    )
    apellidos_trabajador = _texto_seguro(
        trabajador.get("Apellidos")
    )
    documento_trabajador = _texto_seguro(
        trabajador.get("NumeroIdentificacion")
    )
    cargo_trabajador = _texto_seguro(
        trabajador.get("Cargo")
    )
    responsable = _texto_seguro(
        descargo.get("ResponsableDescargo")
    )

    expediente = _texto_seguro(
        _obtener_valor_modelo(
            proceso,
            "NumeroExpediente",
            "ExpedienteDisciplinario",
            "CodigoProceso",
            "NumeroProceso",
        )
    )

    if not expediente:
        expediente = (
            f"PD-{fecha_descargo.year}-"
            f"{int(proceso.IdProcesoDisciplinario):06d}"
        )

    saludo = (
        apellidos_trabajador.upper()
        if apellidos_trabajador
        else nombre_trabajador.upper()
        if nombre_trabajador
        else "TRABAJADOR"
    )

    horario_agenda = _obtener_horario_agenda_descargos(
        db=db,
        id_proceso=proceso.IdProcesoDisciplinario,
        fecha_descargo=descargo.get("FechaDescargo"),
        hora_descargo=descargo.get("HoraDescargo"),
    )

    hora_inicio = _formatear_hora_colombia(
        horario_agenda.get("HoraInicio")
    )
    hora_fin = _formatear_hora_colombia(
        horario_agenda.get("HoraFin")
    )

    contenido.extend(
        [
            Paragraph(
                (
                    "Bogotá D.C., "
                    f"{_fecha_espanol(fecha_generacion)}."
                ),
                estilos["izquierda"],
            ),
            Spacer(1, 0.55 * cm),
            Paragraph("Señor(a):", estilos["izquierda"]),
            Paragraph(
                nombre_trabajador.upper(),
                estilos["negrilla"],
            ),
            Paragraph(
                f"C.C. No. {documento_trabajador}",
                estilos["izquierda"],
            ),
            Paragraph(
                f"Cargo: {cargo_trabajador}",
                estilos["izquierda"],
            ),
            Spacer(1, 0.55 * cm),
            Table(
                [[
                    Paragraph(
                        "Asunto:",
                        estilos["asunto"],
                    ),
                    Paragraph(
                        (
                            "Notificación de sanción disciplinaria "
                            "– Suspensión disciplinaria"
                        ),
                        estilos["asunto"],
                    ),
                ]],
                colWidths=[3.0 * cm, 12.6 * cm],
                style=TableStyle([
                    ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                    ("LEFTPADDING", (0, 0), (-1, -1), 0),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                    ("TOPPADDING", (0, 0), (-1, -1), 2),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
                ]),
            ),
            Spacer(1, 0.55 * cm),
            Paragraph(
                f"Respetado(a) señor(a) {saludo}:",
                estilos["izquierda"],
            ),
            Spacer(1, 0.35 * cm),
            Paragraph(
                (
                    "En la fecha señalada se realiza la diligencia de "
                    "descargos dentro del proceso disciplinario indicado. "
                    "A continuación se deja constancia de las preguntas "
                    "realizadas y de las respuestas manifestadas por el "
                    "trabajador."
                ),
                estilos["normal"],
            ),
            Spacer(1, 0.45 * cm),
            Paragraph(
                "MANIFESTACIÓN DEL TRABAJADOR",
                estilos["titulo"],
            ),
            Spacer(1, 0.30 * cm),
        ]
    )

    contenido.extend(
        _parrafos_preservando_saltos(
            descargo.get("DescargoTrabajador") or "",
            estilos["izquierda"],
        )
    )

    if hora_inicio and hora_fin:
        texto_cierre = (
            "No siendo otro el motivo de la presente diligencia "
            f"que inició a las {hora_inicio} se da por finalizada "
            f"siendo las {hora_fin}, procediendo a ser leída el acta "
            "por el trabajador y firmada por las partes que en ella "
            "intervinieron, haciendo entrega de un ejemplar de la "
            "misma al trabajador."
        )
    else:
        texto_cierre = (
            "No siendo otro el motivo de la presente diligencia, "
            "se da por finalizada una vez leída la presente acta por "
            "el trabajador y firmada por las partes que en ella "
            "intervinieron, haciendo entrega de un ejemplar de la "
            "misma al trabajador."
        )

    contenido.extend([
        Spacer(1, 0.55 * cm),
        Paragraph(
            texto_cierre,
            estilos["normal"],
        ),
        Spacer(1, 1.1 * cm),
    ])

    firma_yeny = _crear_firma_yeny_pdf()

    if firma_yeny is not None:
        contenido_firma_empresa = firma_yeny
        linea_empresa = Spacer(
            1,
            0.05 * cm,
        )
        nombre_empresa = Spacer(
            1,
            0.05 * cm,
        )
        cargo_empresa = Spacer(
            1,
            0.05 * cm,
        )
    else:
        contenido_firma_empresa = Spacer(
            1,
            1.30 * cm,
        )
        linea_empresa = Paragraph(
            "______________________________",
            estilos["izquierda"],
        )
        nombre_empresa = Paragraph(
            responsable.upper(),
            estilos["negrilla"],
        )
        cargo_empresa = Paragraph(
            "Relaciones Laborales",
            estilos["negrilla"],
        )

    tabla_firmas = Table(
        [
            [
                Paragraph(
                    "El trabajador.",
                    estilos["izquierda"],
                ),
                Paragraph(
                    "Por la empresa.",
                    estilos["izquierda"],
                ),
            ],
            [
                Spacer(
                    1,
                    1.30 * cm,
                ),
                contenido_firma_empresa,
            ],
            [
                Paragraph(
                    "______________________________",
                    estilos["izquierda"],
                ),
                linea_empresa,
            ],
            [
                Paragraph(
                    nombre_trabajador.upper(),
                    estilos["negrilla"],
                ),
                nombre_empresa,
            ],
            [
                Paragraph(
                    cargo_trabajador,
                    estilos["negrilla"],
                ),
                cargo_empresa,
            ],
        ],
        colWidths=[
            8.0 * cm,
            8.0 * cm,
        ],
        style=TableStyle([
            (
                "VALIGN",
                (0, 0),
                (-1, -1),
                "TOP",
            ),
            (
                "LEFTPADDING",
                (0, 0),
                (-1, -1),
                0,
            ),
            (
                "RIGHTPADDING",
                (0, 0),
                (-1, -1),
                0,
            ),
            (
                "TOPPADDING",
                (0, 0),
                (-1, -1),
                0,
            ),
            (
                "BOTTOMPADDING",
                (0, 0),
                (-1, -1),
                2,
            ),
        ]),
    )

    contenido.append(
        KeepTogether(tabla_firmas)
    )

    if evidencias:
        contenido.append(PageBreak())
        contenido.append(
            Paragraph(
                "EVIDENCIAS APORTADAS POR EL TRABAJADOR",
                estilos["titulo"],
            )
        )
        contenido.append(Spacer(1, 0.35 * cm))

        for indice, evidencia in enumerate(
            evidencias,
            start=1,
        ):
            nombre_evidencia = (
                evidencia.NombreArchivo
                or f"Evidencia {indice}"
            )

            contenido.append(
                Paragraph(
                    f"Anexo {indice}: {nombre_evidencia}",
                    estilos["anexo"],
                )
            )
            contenido.append(Spacer(1, 0.20 * cm))

            contenido_archivo, formato = (
                _obtener_contenido_documento(
                    db=db,
                    documento=evidencia,
                )
            )

            extension = (
                Path(nombre_evidencia)
                .suffix
                .lower()
            )

            es_imagen = (
                extension
                in {
                    ".png",
                    ".jpg",
                    ".jpeg",
                    ".webp",
                }
                or str(formato)
                .lower()
                .startswith("image/")
            )

            if contenido_archivo and es_imagen:
                try:
                    imagen = Image(
                        io.BytesIO(contenido_archivo)
                    )

                    ancho_maximo = 16.0 * cm
                    alto_maximo = 18.3 * cm

                    proporcion = min(
                        ancho_maximo / imagen.imageWidth,
                        alto_maximo / imagen.imageHeight,
                        1,
                    )

                    imagen.drawWidth = (
                        imagen.imageWidth * proporcion
                    )
                    imagen.drawHeight = (
                        imagen.imageHeight * proporcion
                    )

                    contenido.append(imagen)

                except Exception:
                    contenido.append(
                        Paragraph(
                            (
                                "La evidencia fue registrada en el "
                                "expediente, pero no fue posible "
                                "representar visualmente la imagen."
                            ),
                            estilos["izquierda"],
                        )
                    )

            elif contenido_archivo and extension == ".docx":
                texto_docx = _extraer_texto_docx(
                    contenido_archivo
                )

                if texto_docx:
                    contenido.append(
                        Paragraph(
                            "Contenido textual del documento aportado:",
                            estilos["negrilla"],
                        )
                    )
                    contenido.append(Spacer(1, 0.10 * cm))
                    contenido.extend(
                        _parrafos_preservando_saltos(
                            texto_docx,
                            estilos["izquierda"],
                        )
                    )
                else:
                    contenido.append(
                        Paragraph(
                            "Documento adjunto registrado como evidencia.",
                            estilos["izquierda"],
                        )
                    )
            else:
                contenido.append(
                    Paragraph(
                        (
                            "Documento adjunto registrado como evidencia "
                            "en el expediente disciplinario. El archivo "
                            "original se conserva asociado al proceso."
                        ),
                        estilos["izquierda"],
                    )
                )

            if indice < len(evidencias):
                contenido.extend([
                    Spacer(1, 0.45 * cm),
                    Table(
                        [[""]],
                        colWidths=[16.0 * cm],
                        rowHeights=[0.02 * cm],
                        style=TableStyle([
                            (
                                "LINEABOVE",
                                (0, 0),
                                (-1, -1),
                                0.5,
                                colors.grey,
                            )
                        ]),
                    ),
                    Spacer(1, 0.45 * cm),
                ])

    documento_pdf.build(
        contenido,
        onFirstPage=_dibujar_encabezado_carta_descargos,
        onLaterPages=_dibujar_encabezado_carta_descargos,
    )

    buffer.seek(0)
    return buffer.getvalue()


def _guardar_carta_descargos_generada(
    db: Session,
    id_proceso: int,
    contenido_pdf: bytes,
) -> DocumentoProcesoDisciplinario:
    carpeta_destino_absoluta = (
        STORAGE_DIR
        / "rrll"
        / "procesos_disciplinarios"
        / str(id_proceso)
    )
    carpeta_destino_absoluta.mkdir(parents=True, exist_ok=True)

    nombre_archivo = f"carta_descargos_{id_proceso}.pdf"
    ruta_absoluta = carpeta_destino_absoluta / nombre_archivo
    ruta_relativa = (
        Path("storage")
        / "rrll"
        / "procesos_disciplinarios"
        / str(id_proceso)
        / nombre_archivo
    )
    ruta_absoluta.write_bytes(contenido_pdf)

    existente = (
        db.query(DocumentoProcesoDisciplinario)
        .filter(
            DocumentoProcesoDisciplinario.IdProcesoDisciplinario == id_proceso,
            DocumentoProcesoDisciplinario.TipoDocumento
            == "CARTA_DESCARGOS_GENERADA",
        )
        .order_by(
            DocumentoProcesoDisciplinario
            .IdDocumentoProcesoDisciplinario
            .desc()
        )
        .first()
    )

    if existente:
        existente.NombreArchivo = nombre_archivo
        existente.RutaArchivo = str(ruta_relativa)
        existente.Observacion = (
            "Carta de Descargos generada por Relaciones Laborales."
        )
        existente.DocumentoCargado = contenido_pdf
        existente.Formato = "application/pdf"
        existente.FechaActualizacion = datetime.now(timezone.utc)
        return existente

    nuevo = DocumentoProcesoDisciplinario(
        IdProcesoDisciplinario=id_proceso,
        TipoDocumento="CARTA_DESCARGOS_GENERADA",
        NombreArchivo=nombre_archivo,
        RutaArchivo=str(ruta_relativa),
        Observacion="Carta de Descargos generada por Relaciones Laborales.",
        DocumentoCargado=contenido_pdf,
        Formato="application/pdf",
    )
    db.add(nuevo)
    return nuevo



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
            DocumentoCargado=contenido_archivo,
            Formato=formato_documento,
        )

        db.add(nuevo)
        db.flush()

        if id_tipo_carpeta_digital is not None:
            nombre_carpeta_digital = (
                f"Carta de descargos{Path(nombre_archivo).suffix.lower()}"
                if codigo_tipo_documento == "CARTA_DESCARGOS_FIRMADA"
                else nombre_archivo
            )

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
                nombre_archivo=nombre_carpeta_digital,
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



@router.post(
    "/descargos/generar",
)
def generar_carta_descargos(
    data: GenerarCartaDescargosRequest,
    db: Session = Depends(get_db),
):
    proceso = obtener_proceso_o_error(
        db=db,
        id_proceso=data.IdProcesoDisciplinario,
    )

    descargo = _obtener_datos_descargo(
        db=db,
        id_proceso=data.IdProcesoDisciplinario,
        id_descargo=data.IdDescargoProcesoDisciplinario,
    )

    manifestacion = _texto_seguro(descargo.get("DescargoTrabajador"))
    if not manifestacion:
        raise HTTPException(
            status_code=400,
            detail=(
                "Debe registrar la manifestación del trabajador "
                "antes de generar la Carta de Descargos."
            ),
        )

    trabajador = _obtener_datos_trabajador(db=db, proceso=proceso)

    cargo_paso_3 = _texto_seguro(data.Cargo)
    if cargo_paso_3:
        trabajador["Cargo"] = cargo_paso_3

    evidencias = _obtener_evidencias_trabajador(
        db=db,
        id_proceso=data.IdProcesoDisciplinario,
    )

    try:
        contenido_pdf = _generar_pdf_carta_descargos(
            db=db,
            proceso=proceso,
            descargo=descargo,
            trabajador=trabajador,
            evidencias=evidencias,
        )

        documento = _guardar_carta_descargos_generada(
            db=db,
            id_proceso=data.IdProcesoDisciplinario,
            contenido_pdf=contenido_pdf,
        )

        db.commit()
        db.refresh(documento)

        return {
            "success": True,
            "message": "La Carta de Descargos fue generada correctamente.",
            "data": {
                "IdDocumentoProcesoDisciplinario": (
                    documento.IdDocumentoProcesoDisciplinario
                ),
                "IdProcesoDisciplinario": documento.IdProcesoDisciplinario,
                "TipoDocumento": documento.TipoDocumento,
                "NombreArchivo": documento.NombreArchivo,
                "RutaArchivo": documento.RutaArchivo,
                "Formato": documento.Formato,
                "CantidadEvidencias": len(evidencias),
            },
        }

    except HTTPException:
        db.rollback()
        raise

    except (SQLAlchemyError, OSError, RuntimeError, ValueError) as error:
        db.rollback()
        raise HTTPException(
            status_code=500,
            detail={
                "mensaje": "No fue posible generar la Carta de Descargos.",
                "IdProcesoDisciplinario": data.IdProcesoDisciplinario,
                "IdDescargoProcesoDisciplinario": (
                    data.IdDescargoProcesoDisciplinario
                ),
            },
        ) from error



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
            documento_tiene_archivo_disponible(
                db=db,
                documento=documento,
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

    return construir_respuesta_documento(
        db=db,
        documento=documento,
        descargar=False,
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

    return construir_respuesta_documento(
        db=db,
        documento=documento,
        descargar=True,
    )


@router.delete(
    "/rrll/evidencia-trabajador/{id_documento}",
)
def eliminar_evidencia_trabajador_rrll(
    id_documento: int,
    db: Session = Depends(get_db),
):
    """
    Elimina únicamente una evidencia aportada por el trabajador
    durante el Paso 3 de Descargos en Relaciones Laborales.

    No modifica:
    - Evidencias de Operaciones.
    - Carta de Descargos generada.
    - Carta de Descargos firmada.
    - Documentos de Carpeta Digital.

    Si la carta ya había sido generada, RRLL debe usar
    "Generar nuevamente" para actualizar los anexos.
    """

    documento = obtener_documento_o_error(
        db=db,
        id_documento=id_documento,
    )

    tipo_documento = normalizar_tipo_documento(
        documento.TipoDocumento
    )

    if tipo_documento != "EVIDENCIA_TRABAJADOR":
        raise HTTPException(
            status_code=409,
            detail={
                "mensaje": (
                    "Este endpoint solo permite eliminar evidencias "
                    "aportadas por el trabajador."
                ),
                "TipoDocumento": documento.TipoDocumento,
                "IdDocumentoProcesoDisciplinario": (
                    documento.IdDocumentoProcesoDisciplinario
                ),
            },
        )

    ruta_original = construir_ruta_absoluta_documento(
        documento
    )

    ruta_temporal = None

    if ruta_original:
        marca_tiempo = datetime.now(timezone.utc).strftime(
            "%Y%m%d%H%M%S%f"
        )

        ruta_temporal = ruta_original.with_name(
            f".eliminando_rrll_"
            f"{documento.IdDocumentoProcesoDisciplinario}_"
            f"{marca_tiempo}_"
            f"{ruta_original.name}"
        )

        try:
            ruta_original.rename(ruta_temporal)
        except OSError as error:
            raise HTTPException(
                status_code=500,
                detail={
                    "mensaje": (
                        "No fue posible preparar el archivo físico "
                        "para eliminar la evidencia del trabajador."
                    ),
                    "IdDocumentoProcesoDisciplinario": (
                        documento.IdDocumentoProcesoDisciplinario
                    ),
                },
            ) from error

    try:
        db.delete(documento)
        db.commit()

        if ruta_temporal and ruta_temporal.exists():
            ruta_temporal.unlink(missing_ok=True)

        return {
            "success": True,
            "message": (
                "Evidencia del trabajador eliminada correctamente."
            ),
            "IdDocumentoProcesoDisciplinario": id_documento,
        }

    except SQLAlchemyError as error:
        db.rollback()

        if (
            ruta_temporal
            and ruta_temporal.exists()
            and ruta_original
            and not ruta_original.exists()
        ):
            try:
                ruta_temporal.rename(ruta_original)
            except OSError:
                pass

        raise HTTPException(
            status_code=500,
            detail={
                "mensaje": (
                    "No fue posible eliminar la evidencia del trabajador."
                ),
                "IdDocumentoProcesoDisciplinario": id_documento,
            },
        ) from error


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
        marca_tiempo = datetime.now(timezone.utc).strftime(
            "%Y%m%d%H%M%S%f"
        )

        ruta_temporal = ruta_original.with_name(
            f".eliminando_"
            f"{documento.IdDocumentoProcesoDisciplinario}_"
            f"{marca_tiempo}_"
            f"{ruta_original.name}"
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

    documento.FechaActualizacion = datetime.now(
        timezone.utc
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