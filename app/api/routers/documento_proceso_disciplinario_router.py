# ruff: noqa: B008
import io
import mimetypes
import zipfile
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from xml.etree import ElementTree
from urllib.parse import quote

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
    "DOCUMENTO_CIERRE_DISCIPLINARIO": 82,
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



def _nombre_expediente_evidencias(
    proceso: ProcesoDisciplinario,
) -> str:
    """
    Construye el código visible del expediente para el consolidado
    de evidencias de Operaciones.
    """

    fecha_creacion = getattr(
        proceso,
        "FechaCreacion",
        None,
    )

    anio = (
        fecha_creacion.year
        if fecha_creacion
        else _fecha_generacion_colombia().year
    )

    return (
        f"PD-{anio}-"
        f"{int(proceso.IdProcesoDisciplinario):06d}"
    )


def _nombre_seguro_adjunto_pdf(
    nombre_archivo: str,
    indice: int,
) -> str:
    """
    Limpia únicamente caracteres problemáticos para adjuntar el
    archivo original dentro del PDF consolidado.
    """

    nombre = Path(
        str(nombre_archivo or "")
    ).name.strip()

    if not nombre:
        nombre = f"evidencia_{indice}"

    return (
        nombre
        .replace("\x00", "")
        .replace("\r", "")
        .replace("\n", "")
    )


def _crear_pdf_portada_evidencia_operaciones(
    indice: int,
    total: int,
    nombre_archivo: str,
    formato: str,
    expediente: str,
    nota: str | None = None,
    texto_adicional: str | None = None,
) -> bytes:
    """
    Crea una portada/hoja descriptiva para cada evidencia.

    Esta hoja permite que archivos que no pueden representarse
    visualmente en PDF (por ejemplo Excel o audio) sigan quedando
    identificados dentro del consolidado. El archivo original se
    conserva en DocumentoProcesoDisciplinario.
    """

    buffer = io.BytesIO()

    documento = SimpleDocTemplate(
        buffer,
        pagesize=LETTER,
        rightMargin=2.0 * cm,
        leftMargin=2.0 * cm,
        topMargin=3.55 * cm,
        bottomMargin=1.8 * cm,
        title="Evidencias de Operaciones",
        author="Aseos La Perfección",
    )

    estilos_base = getSampleStyleSheet()

    titulo = ParagraphStyle(
        "EvidenciasOperacionesTitulo",
        parent=estilos_base["Normal"],
        fontName="Helvetica-Bold",
        fontSize=14,
        leading=18,
        alignment=TA_CENTER,
        textColor=colors.black,
        spaceAfter=0,
    )

    subtitulo = ParagraphStyle(
        "EvidenciasOperacionesSubtitulo",
        parent=estilos_base["Normal"],
        fontName="Helvetica-Bold",
        fontSize=11,
        leading=15,
        alignment=TA_LEFT,
        textColor=colors.black,
        spaceAfter=0,
    )

    normal = ParagraphStyle(
        "EvidenciasOperacionesNormal",
        parent=estilos_base["Normal"],
        fontName="Helvetica",
        fontSize=10,
        leading=14,
        alignment=TA_LEFT,
        textColor=colors.black,
        spaceAfter=0,
    )

    def escapar(valor) -> str:
        return (
            str(valor or "")
            .replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
        )

    contenido = [
        Paragraph(
            "EVIDENCIAS APORTADAS POR OPERACIONES",
            titulo,
        ),
        Spacer(1, 0.45 * cm),
        Paragraph(
            f"Expediente: {escapar(expediente)}",
            subtitulo,
        ),
        Spacer(1, 0.35 * cm),
        Paragraph(
            (
                f"Evidencia {indice} de {total}: "
                f"{escapar(nombre_archivo)}"
            ),
            subtitulo,
        ),
        Spacer(1, 0.20 * cm),
        Paragraph(
            (
                "Tipo de archivo: "
                f"{escapar(formato or 'No identificado')}"
            ),
            normal,
        ),
    ]

    if nota:
        contenido.extend(
            [
                Spacer(1, 0.30 * cm),
                Paragraph(
                    escapar(nota),
                    normal,
                ),
            ]
        )

    if texto_adicional:
        contenido.extend(
            [
                Spacer(1, 0.35 * cm),
                Paragraph(
                    "Contenido textual recuperado:",
                    subtitulo,
                ),
                Spacer(1, 0.20 * cm),
            ]
        )

        lineas = (
            str(texto_adicional)
            .replace("\r\n", "\n")
            .replace("\r", "\n")
            .split("\n")
        )

        for linea in lineas:
            if linea.strip():
                contenido.append(
                    Paragraph(
                        escapar(linea.strip()),
                        normal,
                    )
                )
            else:
                contenido.append(
                    Spacer(1, 0.12 * cm)
                )

    documento.build(
        contenido,
        onFirstPage=_dibujar_encabezado_carta_descargos,
        onLaterPages=_dibujar_encabezado_carta_descargos,
    )

    buffer.seek(0)
    return buffer.getvalue()


def _convertir_imagen_a_pdf(
    contenido_archivo: bytes,
) -> bytes:
    """
    Convierte una imagen a PDF conservando su proporción.
    """

    with PILImage.open(
        io.BytesIO(contenido_archivo)
    ) as imagen_original:
        imagen = imagen_original.convert("RGB")

        buffer = io.BytesIO()

        imagen.save(
            buffer,
            format="PDF",
            resolution=150.0,
        )

        buffer.seek(0)
        return buffer.getvalue()


def _decodificar_archivo_texto(
    contenido_archivo: bytes,
) -> str:
    """
    Intenta recuperar texto plano sin romper el flujo cuando
    la codificación del archivo es diferente.
    """

    for codificacion in (
        "utf-8",
        "utf-8-sig",
        "latin-1",
    ):
        try:
            return contenido_archivo.decode(
                codificacion
            )
        except UnicodeDecodeError:
            continue

    return ""



def _es_evidencia_visual_pdf_o_imagen(
    nombre_archivo: str | None,
    formato: str | None,
) -> bool:
    """
    Retorna True cuando la evidencia puede incorporarse visualmente
    al documento 03 principal sin alterar su contenido: PDF o imagen.
    """

    nombre = str(nombre_archivo or "").strip()
    formato_normalizado = str(formato or "").strip().lower()
    extension = Path(nombre).suffix.lower()

    if (
        extension == ".pdf"
        or formato_normalizado == "application/pdf"
    ):
        return True

    if (
        extension
        in {
            ".png",
            ".jpg",
            ".jpeg",
            ".webp",
            ".bmp",
            ".tif",
            ".tiff",
        }
        or formato_normalizado.startswith("image/")
    ):
        return True

    return False


def _extension_evidencia(
    nombre_archivo: str | None,
    formato: str | None,
) -> str:
    """
    Conserva la extensión original cuando existe.
    Si no existe, intenta inferirla desde el MIME type.
    """

    nombre = str(nombre_archivo or "").strip()
    extension = Path(nombre).suffix.lower()

    if extension:
        return extension

    formato_normalizado = str(formato or "").strip().lower()

    extension_mime = mimetypes.guess_extension(
        formato_normalizado
    )

    return extension_mime or ""


def registrar_evidencias_no_visuales_operaciones_carpeta_digital(
    db: Session,
    proceso: ProcesoDisciplinario,
) -> dict:
    """
    Registra en Carpeta Digital las evidencias de Operaciones que no
    se incorporan visualmente al PDF 03 principal.

    Se nombran en suborden:
    03.1, 03.2, 03.3...

    Ejemplos:
    03.1 - Evidencia de Operaciones - PD-2026-000056.xlsx
    03.2 - Evidencia de Operaciones - PD-2026-000056.mp3

    Es idempotente por trabajador + nombre controlado.
    No ejecuta commit.
    """

    evidencias = obtener_evidencias_operaciones(
        db=db,
        id_proceso=proceso.IdProcesoDisciplinario,
    )

    expediente = _nombre_expediente_evidencias(
        proceso
    )

    evidencias_no_visuales = []

    for evidencia in evidencias:
        nombre_evidencia = (
            evidencia.NombreArchivo
            or ""
        )

        contenido_archivo, formato = (
            _obtener_contenido_documento(
                db=db,
                documento=evidencia,
            )
        )

        if not contenido_archivo:
            continue

        if _es_evidencia_visual_pdf_o_imagen(
            nombre_archivo=nombre_evidencia,
            formato=formato,
        ):
            continue

        evidencias_no_visuales.append(
            {
                "contenido": contenido_archivo,
                "formato": (
                    str(formato or "").strip()
                    or "application/octet-stream"
                ),
                "extension": _extension_evidencia(
                    nombre_archivo=nombre_evidencia,
                    formato=formato,
                ),
            }
        )

    documentos = []

    for indice, item in enumerate(
        evidencias_no_visuales,
        start=1,
    ):
        nombre_archivo = (
            f"03.{indice} - Evidencia de Operaciones - "
            f"{expediente}"
            f"{item['extension']}"
        )

        existente = (
            db.execute(
                text(
                    """
                    SELECT
                        d."IdDocumento"
                    FROM public."Documentos" d
                    INNER JOIN public."RelacionTipoDocumentacion" rtd
                        ON rtd."IdDocumento" = d."IdDocumento"
                    WHERE rtd."IdRegistroPersonal" = :id_registro_personal
                      AND d."IdTipoDocumentacion" = 82
                      AND d."Nombre" = :nombre_archivo
                    ORDER BY d."IdDocumento" DESC
                    LIMIT 1
                    """
                ),
                {
                    "id_registro_personal": (
                        proceso.IdRegistroPersonal
                    ),
                    "nombre_archivo": nombre_archivo,
                },
            )
            .mappings()
            .first()
        )

        if existente:
            id_documento = int(
                existente["IdDocumento"]
            )

            db.execute(
                text(
                    """
                    UPDATE public."Documentos"
                    SET
                        "DocumentoCargado" = :documento_cargado,
                        "FechaActualizacion" = NOW(),
                        "Formato" = :formato
                    WHERE "IdDocumento" = :id_documento
                    """
                ),
                {
                    "documento_cargado": item["contenido"],
                    "formato": item["formato"],
                    "id_documento": id_documento,
                },
            )
        else:
            id_documento = registrar_documento_carpeta_digital(
                db=db,
                id_registro_personal=(
                    proceso.IdRegistroPersonal
                ),
                id_tipo_documentacion=82,
                contenido_archivo=(
                    item["contenido"]
                ),
                nombre_archivo=(
                    nombre_archivo
                ),
                formato=(
                    item["formato"]
                ),
            )

        documentos.append(
            {
                "IdDocumentoCarpetaDigital": (
                    id_documento
                ),
                "NombreArchivo": nombre_archivo,
                "Formato": item["formato"],
            }
        )

    return {
        "cantidad": len(documentos),
        "documentos": documentos,
    }


def obtener_evidencias_operaciones(
    db: Session,
    id_proceso: int,
) -> list[DocumentoProcesoDisciplinario]:
    """
    Obtiene únicamente las evidencias cargadas desde Operaciones,
    respetando el orden en que fueron registradas.
    """

    return (
        db.query(
            DocumentoProcesoDisciplinario
        )
        .filter(
            DocumentoProcesoDisciplinario
            .IdProcesoDisciplinario
            == id_proceso,
            DocumentoProcesoDisciplinario
            .TipoDocumento
            == "EVIDENCIA_OPERACIONES",
        )
        .order_by(
            DocumentoProcesoDisciplinario
            .FechaCreacion
            .asc(),
            DocumentoProcesoDisciplinario
            .IdDocumentoProcesoDisciplinario
            .asc(),
        )
        .all()
    )


def generar_pdf_evidencias_operaciones(
    db: Session,
    proceso: ProcesoDisciplinario,
) -> dict:
    """
    Consolida las evidencias de Operaciones en un único PDF limpio.

    Reglas:
    - Sin evidencias: no genera documento 03.
    - PDF: incorpora directamente todas sus páginas.
    - Imágenes: las convierte directamente a PDF y las incorpora.
    - Word, Excel, audio, video, texto y otros formatos:
      conserva el archivo original asociado al expediente y, cuando
      pypdf lo permite, lo adjunta internamente al PDF consolidado.
    - No crea portadas, índices, avisos ni páginas descriptivas
      antes de cada evidencia.
    - Las evidencias originales NO se eliminan ni se modifican.

    Importante:
    El documento 03 solo se genera cuando por lo menos una evidencia
    puede representarse visualmente como página PDF (PDF o imagen).
    """

    evidencias = obtener_evidencias_operaciones(
        db=db,
        id_proceso=(
            proceso.IdProcesoDisciplinario
        ),
    )

    if not evidencias:
        return {
            "generado": False,
            "cantidadEvidencias": 0,
            "cantidadIncorporadas": 0,
            "cantidadAdjuntasInternas": 0,
            "contenidoPdf": None,
            "nombreArchivo": None,
            "mensaje": (
                "El proceso no tiene evidencias de Operaciones. "
                "No se genera documento 03."
            ),
        }

    try:
        from pypdf import PdfReader, PdfWriter
    except ImportError as error:
        raise RuntimeError(
            "Para consolidar evidencias PDF se requiere "
            "la librería pypdf en el backend."
        ) from error

    escritor = PdfWriter()

    expediente = _nombre_expediente_evidencias(
        proceso
    )

    nombre_consolidado = (
        "03 - Evidencias de Operaciones - "
        f"{expediente}.pdf"
    )

    total = len(evidencias)
    cantidad_incorporadas = 0
    cantidad_adjuntas_internas = 0

    for indice, evidencia in enumerate(
        evidencias,
        start=1,
    ):
        nombre_evidencia = (
            evidencia.NombreArchivo
            or f"Evidencia {indice}"
        )

        contenido_archivo, formato = (
            _obtener_contenido_documento(
                db=db,
                documento=evidencia,
            )
        )

        if not contenido_archivo:
            # La evidencia continúa registrada en el expediente.
            # No se agrega ninguna página artificial al consolidado.
            continue

        formato_normalizado = str(
            formato or ""
        ).strip().lower()

        extension = (
            Path(nombre_evidencia)
            .suffix
            .lower()
        )

        es_pdf = (
            extension == ".pdf"
            or formato_normalizado
            == "application/pdf"
        )

        es_imagen = (
            extension
            in {
                ".png",
                ".jpg",
                ".jpeg",
                ".webp",
                ".bmp",
                ".tif",
                ".tiff",
            }
            or formato_normalizado
            .startswith("image/")
        )

        if es_pdf:
            try:
                lector_pdf = PdfReader(
                    io.BytesIO(
                        contenido_archivo
                    )
                )

                paginas_agregadas = 0

                for pagina in lector_pdf.pages:
                    escritor.add_page(
                        pagina
                    )
                    paginas_agregadas += 1

                if paginas_agregadas > 0:
                    cantidad_incorporadas += 1

            except Exception:
                # El PDF original se conserva en el expediente.
                # No se crea una portada de error.
                try:
                    escritor.add_attachment(
                        _nombre_seguro_adjunto_pdf(
                            nombre_archivo=(
                                nombre_evidencia
                            ),
                            indice=indice,
                        ),
                        contenido_archivo,
                    )
                    cantidad_adjuntas_internas += 1
                except Exception:
                    pass

            continue

        if es_imagen:
            try:
                pdf_imagen = (
                    _convertir_imagen_a_pdf(
                        contenido_archivo
                    )
                )

                lector_imagen = PdfReader(
                    io.BytesIO(
                        pdf_imagen
                    )
                )

                paginas_agregadas = 0

                for pagina in lector_imagen.pages:
                    escritor.add_page(
                        pagina
                    )
                    paginas_agregadas += 1

                if paginas_agregadas > 0:
                    cantidad_incorporadas += 1

            except Exception:
                # La imagen original se conserva en el expediente.
                # No se crea una portada de error.
                try:
                    escritor.add_attachment(
                        _nombre_seguro_adjunto_pdf(
                            nombre_archivo=(
                                nombre_evidencia
                            ),
                            indice=indice,
                        ),
                        contenido_archivo,
                    )
                    cantidad_adjuntas_internas += 1
                except Exception:
                    pass

            continue

        # Word, Excel, audio, video, texto y cualquier otro formato
        # permanecen como originales en DocumentoProcesoDisciplinario.
        # Cuando es posible, también se adjuntan internamente al PDF,
        # pero NO generan páginas artificiales ni contenido convertido.
        try:
            escritor.add_attachment(
                _nombre_seguro_adjunto_pdf(
                    nombre_archivo=(
                        nombre_evidencia
                    ),
                    indice=indice,
                ),
                contenido_archivo,
            )
            cantidad_adjuntas_internas += 1

        except Exception:
            # El original continúa disponible en el expediente.
            pass

    if len(escritor.pages) == 0:
        return {
            "generado": False,
            "cantidadEvidencias": total,
            "cantidadIncorporadas": 0,
            "cantidadAdjuntasInternas": (
                cantidad_adjuntas_internas
            ),
            "contenidoPdf": None,
            "nombreArchivo": None,
            "mensaje": (
                "El proceso tiene evidencias de Operaciones, pero "
                "ninguna puede representarse visualmente dentro de "
                "un PDF sin alterar el archivo original. "
                "Los archivos permanecen asociados al expediente."
            ),
        }

    buffer_salida = io.BytesIO()

    escritor.write(
        buffer_salida
    )

    buffer_salida.seek(0)

    return {
        "generado": True,
        "cantidadEvidencias": total,
        "cantidadIncorporadas": (
            cantidad_incorporadas
        ),
        "cantidadAdjuntasInternas": (
            cantidad_adjuntas_internas
        ),
        "contenidoPdf": (
            buffer_salida.getvalue()
        ),
        "nombreArchivo": (
            nombre_consolidado
        ),
        "mensaje": (
            "Las evidencias visuales de Operaciones fueron "
            "consolidadas directamente en un único PDF, sin "
            "portadas ni páginas descriptivas adicionales."
        ),
    }

def registrar_o_actualizar_evidencias_operaciones_carpeta_digital(
    db: Session,
    proceso: ProcesoDisciplinario,
) -> dict:
    """
    Genera el documento 03 de evidencias y lo registra en
    Carpeta Digital > Activos > Procesos disciplinarios.

    Es idempotente por trabajador y nombre controlado:
    si ya existe, actualiza el contenido y no crea duplicados.

    No ejecuta commit. El commit debe hacerlo el flujo principal
    que envía el proceso a Relaciones Laborales.
    """

    resultado = generar_pdf_evidencias_operaciones(
        db=db,
        proceso=proceso,
    )

    if not resultado.get("generado"):
        return {
            "generado": False,
            "guardadoCarpetaDigital": False,
            "IdDocumentoCarpetaDigital": None,
            "cantidadEvidencias": (
                resultado.get(
                    "cantidadEvidencias",
                    0,
                )
            ),
            "nombreArchivo": None,
            "mensaje": resultado.get(
                "mensaje"
            ),
        }

    contenido_pdf = resultado[
        "contenidoPdf"
    ]

    nombre_archivo = resultado[
        "nombreArchivo"
    ]

    id_tipo_documentacion = 82

    existente = (
        db.execute(
            text(
                """
                SELECT
                    d."IdDocumento"
                FROM public."Documentos" d
                INNER JOIN public."RelacionTipoDocumentacion" rtd
                    ON rtd."IdDocumento" = d."IdDocumento"
                WHERE rtd."IdRegistroPersonal" = :id_registro_personal
                  AND d."IdTipoDocumentacion" = :id_tipo_documentacion
                  AND d."Nombre" = :nombre_archivo
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
                    nombre_archivo
                ),
            },
        )
        .mappings()
        .first()
    )

    if existente:
        id_documento = int(
            existente["IdDocumento"]
        )

        db.execute(
            text(
                """
                UPDATE public."Documentos"
                SET
                    "DocumentoCargado" = :documento_cargado,
                    "FechaActualizacion" = NOW(),
                    "Formato" = 'application/pdf'
                WHERE "IdDocumento" = :id_documento
                """
            ),
            {
                "documento_cargado": (
                    contenido_pdf
                ),
                "id_documento": (
                    id_documento
                ),
            },
        )

    else:
        id_documento = (
            registrar_documento_carpeta_digital(
                db=db,
                id_registro_personal=(
                    proceso.IdRegistroPersonal
                ),
                id_tipo_documentacion=(
                    id_tipo_documentacion
                ),
                contenido_archivo=(
                    contenido_pdf
                ),
                nombre_archivo=(
                    nombre_archivo
                ),
                formato="application/pdf",
            )
        )

    # También se conserva una copia física del consolidado.
    carpeta_destino = (
        STORAGE_DIR
        / "rrll"
        / "procesos_disciplinarios"
        / str(
            proceso.IdProcesoDisciplinario
        )
    )

    carpeta_destino.mkdir(
        parents=True,
        exist_ok=True,
    )

    ruta_consolidado = (
        carpeta_destino
        / "03_evidencias_operaciones.pdf"
    )

    ruta_consolidado.write_bytes(
        contenido_pdf
    )

    resultado_no_visuales = (
        registrar_evidencias_no_visuales_operaciones_carpeta_digital(
            db=db,
            proceso=proceso,
        )
    )

    return {
        "generado": True,
        "guardadoCarpetaDigital": True,
        "IdDocumentoCarpetaDigital": (
            id_documento
        ),
        "cantidadEvidencias": (
            resultado[
                "cantidadEvidencias"
            ]
        ),
        "nombreArchivo": (
            nombre_archivo
        ),
        "EvidenciasNoVisuales": (
            resultado_no_visuales
        ),
        "mensaje": (
            "Las evidencias visuales de Operaciones fueron consolidadas "
            "como documento 03 y los archivos no visuales fueron "
            "registrados individualmente como 03.1, 03.2, 03.3, etc."
        ),
    }



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

        nombre_seguro = (
            nombre_archivo
            .replace('"', "")
            .replace("\r", "")
            .replace("\n", "")
        )

        nombre_codificado = quote(
            nombre_seguro,
            safe="",
        )

        return FileResponse(
            path=str(ruta_absoluta),
            media_type=(
                tipo_contenido
                or "application/octet-stream"
            ),
            headers={
                "Content-Disposition": (
                    f'{disposition}; '
                    f'filename="{nombre_seguro}"; '
                    f"filename*=UTF-8''{nombre_codificado}"
                ),
                "X-Content-Type-Options": "nosniff",
            },
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
                f'filename="{nombre_seguro}"; '
                f"filename*=UTF-8''"
                f"{quote(nombre_seguro, safe='')}"
            ),
            "Content-Length": str(
                len(contenido_archivo)
            ),
            "X-Content-Type-Options": "nosniff",
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
            a."EstadoAgenda"
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
    Encabezado corporativo del Acta de Descargos.

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
    'Por la empresa' del Acta de Descargos.

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
        .order_by(
            DocumentoProcesoDisciplinario.FechaCreacion.asc(),
            DocumentoProcesoDisciplinario
            .IdDocumentoProcesoDisciplinario.asc(),
        )
        .all()
    )




def _evidencia_trabajador_se_integra_en_acta(
    nombre_archivo: str | None,
    formato: str | None,
) -> bool:
    """
    Define si la evidencia del trabajador queda integrada dentro del
    documento 02 - Acta de Descargos.

    Se integran:
    - PDF: se incorpora completo al final del Acta.
    - Imágenes: se muestran visualmente dentro del Acta.
    - DOCX: se intenta recuperar y mostrar su contenido textual.

    Excel, audio, video y otros formatos se conservan como archivos
    originales independientes en Carpeta Digital con suborden
    02.1, 02.2, 02.3...
    """

    nombre = str(
        nombre_archivo or ""
    ).strip()

    formato_normalizado = str(
        formato or ""
    ).strip().lower()

    extension = (
        Path(nombre)
        .suffix
        .lower()
    )

    if (
        extension == ".pdf"
        or formato_normalizado == "application/pdf"
    ):
        return True

    if (
        extension
        in {
            ".png",
            ".jpg",
            ".jpeg",
            ".webp",
            ".bmp",
            ".gif",
            ".tif",
            ".tiff",
        }
        or formato_normalizado.startswith("image/")
    ):
        return True

    if (
        extension == ".docx"
        or formato_normalizado
        == (
            "application/vnd.openxmlformats-officedocument."
            "wordprocessingml.document"
        )
    ):
        return True

    return False


def registrar_evidencias_no_visuales_trabajador_carpeta_digital(
    db: Session,
    proceso: ProcesoDisciplinario,
    evidencias: list[DocumentoProcesoDisciplinario],
) -> dict:
    """
    Registra en Carpeta Digital las evidencias aportadas por el
    trabajador que no se integran visualmente dentro del Acta.

    Orden controlado:
    02.1, 02.2, 02.3...

    Ejemplos:
    02.1 - Evidencia del Trabajador - PD-2026-000056.xlsx
    02.2 - Evidencia del Trabajador - PD-2026-000056.mp3

    Los PDF, imágenes y DOCX que sí se integran en el Acta no crean
    documentos 02.x adicionales.

    Es idempotente por trabajador + nombre controlado.
    No ejecuta commit.
    """

    expediente = (
        _nombre_expediente_evidencias(
            proceso
        )
    )

    evidencias_no_visuales = []

    for evidencia in evidencias:
        nombre_evidencia = (
            evidencia.NombreArchivo
            or ""
        )

        contenido_archivo, formato = (
            _obtener_contenido_documento(
                db=db,
                documento=evidencia,
            )
        )

        if not contenido_archivo:
            continue

        if _evidencia_trabajador_se_integra_en_acta(
            nombre_archivo=nombre_evidencia,
            formato=formato,
        ):
            continue

        extension = (
            _extension_evidencia(
                nombre_archivo=nombre_evidencia,
                formato=formato,
            )
        )

        evidencias_no_visuales.append(
            {
                "contenido": contenido_archivo,
                "formato": (
                    str(formato or "").strip()
                    or "application/octet-stream"
                ),
                "extension": extension,
            }
        )

    documentos = []

    for indice, item in enumerate(
        evidencias_no_visuales,
        start=1,
    ):
        nombre_archivo = (
            f"02.{indice} - Evidencia del Trabajador - "
            f"{expediente}"
            f"{item['extension']}"
        )

        existente = (
            db.execute(
                text(
                    """
                    SELECT
                        d."IdDocumento"
                    FROM public."Documentos" d
                    INNER JOIN public."RelacionTipoDocumentacion" rtd
                        ON rtd."IdDocumento" = d."IdDocumento"
                    WHERE rtd."IdRegistroPersonal" = :id_registro_personal
                      AND d."IdTipoDocumentacion" = 82
                      AND d."Nombre" = :nombre_archivo
                    ORDER BY d."IdDocumento" DESC
                    LIMIT 1
                    """
                ),
                {
                    "id_registro_personal": (
                        proceso.IdRegistroPersonal
                    ),
                    "nombre_archivo": (
                        nombre_archivo
                    ),
                },
            )
            .mappings()
            .first()
        )

        if existente:
            id_documento = int(
                existente["IdDocumento"]
            )

            db.execute(
                text(
                    """
                    UPDATE public."Documentos"
                    SET
                        "DocumentoCargado" = :documento_cargado,
                        "FechaActualizacion" = NOW(),
                        "Formato" = :formato
                    WHERE "IdDocumento" = :id_documento
                    """
                ),
                {
                    "documento_cargado": (
                        item["contenido"]
                    ),
                    "formato": (
                        item["formato"]
                    ),
                    "id_documento": (
                        id_documento
                    ),
                },
            )

        else:
            id_documento = (
                registrar_documento_carpeta_digital(
                    db=db,
                    id_registro_personal=(
                        proceso.IdRegistroPersonal
                    ),
                    id_tipo_documentacion=82,
                    contenido_archivo=(
                        item["contenido"]
                    ),
                    nombre_archivo=(
                        nombre_archivo
                    ),
                    formato=(
                        item["formato"]
                    ),
                )
            )

        documentos.append(
            {
                "IdDocumentoCarpetaDigital": (
                    id_documento
                ),
                "NombreArchivo": (
                    nombre_archivo
                ),
                "Formato": (
                    item["formato"]
                ),
            }
        )

    return {
        "cantidad": len(documentos),
        "documentos": documentos,
    }


def _generar_pdf_carta_descargos(
    db: Session,
    proceso: ProcesoDisciplinario,
    descargo: dict,
    trabajador: dict,
    evidencias: list[DocumentoProcesoDisciplinario],
) -> bytes:
    """
    Genera el Acta de Descargos y trata las evidencias aportadas por
    el trabajador de acuerdo con su formato.

    Reglas:
    - Imágenes: se muestran visualmente dentro del Acta.
    - PDF: se incorporan completas al final del Acta.
    - DOCX: se intenta recuperar el texto y mostrarlo en el Acta.
    - Excel, audio, video y otros formatos no visuales:
      se identifican como anexos y el archivo original permanece
      asociado al expediente disciplinario para consulta/descarga.
    """

    buffer = io.BytesIO()

    documento_pdf = SimpleDocTemplate(
        buffer,
        pagesize=LETTER,
        rightMargin=2.0 * cm,
        leftMargin=2.0 * cm,
        topMargin=3.55 * cm,
        bottomMargin=1.8 * cm,
        title="Acta de Descargos",
        author="Aseos La Perfección",
    )

    estilos = _estilos_carta_descargos()
    contenido = []

    # Los PDF aportados por el trabajador se anexan después de
    # construir el Acta base para conservar todas sus páginas.
    pdfs_evidencias = []

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

            contenido_archivo, formato = (
                _obtener_contenido_documento(
                    db=db,
                    documento=evidencia,
                )
            )

            formato_normalizado = str(
                formato or ""
            ).strip().lower()

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
                    ".bmp",
                    ".gif",
                    ".tif",
                    ".tiff",
                }
                or formato_normalizado.startswith(
                    "image/"
                )
            )

            es_pdf = (
                extension == ".pdf"
                or formato_normalizado
                == "application/pdf"
            )

            es_docx = (
                extension == ".docx"
                or formato_normalizado
                == (
                    "application/vnd.openxmlformats-officedocument."
                    "wordprocessingml.document"
                )
            )

            contenido.append(
                Paragraph(
                    f"Anexo {indice}: {nombre_evidencia}",
                    estilos["anexo"],
                )
            )
            contenido.append(
                Spacer(1, 0.20 * cm)
            )

            if contenido_archivo and es_imagen:
                try:
                    imagen = Image(
                        io.BytesIO(
                            contenido_archivo
                        )
                    )

                    ancho_maximo = 16.0 * cm
                    alto_maximo = 18.3 * cm

                    proporcion = min(
                        ancho_maximo
                        / imagen.imageWidth,
                        alto_maximo
                        / imagen.imageHeight,
                        1,
                    )

                    imagen.drawWidth = (
                        imagen.imageWidth
                        * proporcion
                    )

                    imagen.drawHeight = (
                        imagen.imageHeight
                        * proporcion
                    )

                    imagen.hAlign = "CENTER"

                    contenido.append(
                        imagen
                    )

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

            elif contenido_archivo and es_pdf:
                # El PDF completo se agrega al final del Acta,
                # sin convertirlo en imagen ni perder páginas.
                pdfs_evidencias.append(
                    {
                        "indice": indice,
                        "nombre": (
                            nombre_evidencia
                        ),
                        "contenido": (
                            contenido_archivo
                        ),
                    }
                )

                contenido.append(
                    Paragraph(
                        (
                            "El documento PDF aportado por el trabajador "
                            "se incorpora completo al final del Acta."
                        ),
                        estilos["izquierda"],
                    )
                )

            elif contenido_archivo and es_docx:
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
                    contenido.append(
                        Spacer(
                            1,
                            0.10 * cm,
                        )
                    )
                    contenido.extend(
                        _parrafos_preservando_saltos(
                            texto_docx,
                            estilos["izquierda"],
                        )
                    )
                else:
                    contenido.append(
                        Paragraph(
                            (
                                "Documento Word registrado como evidencia. "
                                "El archivo original permanece asociado "
                                "al expediente."
                            ),
                            estilos["izquierda"],
                        )
                    )

            elif contenido_archivo:
                # Excel, audio, video y otros formatos no visuales
                # no se fuerzan a PDF para evitar alterar información.
                contenido.append(
                    Paragraph(
                        (
                            "Archivo original registrado como evidencia "
                            "del trabajador. Por su formato no se representa "
                            "visualmente dentro del Acta; permanece asociado "
                            "al expediente para consulta y descarga."
                        ),
                        estilos["izquierda"],
                    )
                )

            else:
                contenido.append(
                    Paragraph(
                        (
                            "La evidencia está registrada en el expediente, "
                            "pero actualmente no se encontró un archivo "
                            "disponible para incorporarlo al Acta."
                        ),
                        estilos["izquierda"],
                    )
                )

            if indice < len(evidencias):
                contenido.extend([
                    Spacer(
                        1,
                        0.45 * cm,
                    ),
                    Table(
                        [[""]],
                        colWidths=[
                            16.0 * cm
                        ],
                        rowHeights=[
                            0.02 * cm
                        ],
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
                    Spacer(
                        1,
                        0.45 * cm,
                    ),
                ])

    documento_pdf.build(
        contenido,
        onFirstPage=_dibujar_encabezado_carta_descargos,
        onLaterPages=_dibujar_encabezado_carta_descargos,
    )

    buffer.seek(0)

    contenido_acta_base = (
        buffer.getvalue()
    )

    if not pdfs_evidencias:
        return contenido_acta_base

    try:
        from pypdf import (
            PdfReader,
            PdfWriter,
        )
    except ImportError as error:
        raise RuntimeError(
            "Para incorporar evidencias PDF al Acta de Descargos "
            "se requiere la librería pypdf en el backend."
        ) from error

    escritor = PdfWriter()

    lector_acta = PdfReader(
        io.BytesIO(
            contenido_acta_base
        )
    )

    for pagina in lector_acta.pages:
        escritor.add_page(
            pagina
        )

    for evidencia_pdf in pdfs_evidencias:
        try:
            lector_evidencia = PdfReader(
                io.BytesIO(
                    evidencia_pdf[
                        "contenido"
                    ]
                )
            )

            for pagina in lector_evidencia.pages:
                escritor.add_page(
                    pagina
                )

        except Exception:
            # El archivo original sigue asociado al expediente.
            # No se rompe la generación completa del Acta por un
            # PDF de evidencia que resulte ilegible o esté dañado.
            continue

    salida = io.BytesIO()

    escritor.write(
        salida
    )

    salida.seek(0)

    return salida.getvalue()



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

    nombre_archivo = f"acta_descargos_{id_proceso}.pdf"
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
            "Acta de Descargos generada por Relaciones Laborales."
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
        Observacion="Acta de Descargos generada por Relaciones Laborales.",
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

    nombre_archivo_original = Path(
        archivo.filename or ""
    ).name.strip()

    if not nombre_archivo_original:
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

    extension_archivo = (
        Path(nombre_archivo_original)
        .suffix
        .lower()
    )

    extension = (
        extension_archivo
        .lstrip(".")
    )

    formato_documento = (
        archivo.content_type
        or extension
        or "application/octet-stream"
    )

    # Documento oficial de cierre:
    # se controla el nombre para que siempre quede como número 04
    # dentro del expediente y de la Carpeta Digital.
    if (
        codigo_tipo_documento
        == "DOCUMENTO_CIERRE_DISCIPLINARIO"
    ):
        codigo_expediente = (
            _nombre_expediente_evidencias(
                proceso
            )
        )

        nombre_archivo = (
            "04 - Documento de Cierre - "
            f"{codigo_expediente}"
            f"{extension_archivo}"
        )
    else:
        nombre_archivo = (
            nombre_archivo_original
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

        # Para el documento oficial de cierre se mantiene un único
        # registro por expediente. Si Yeny vuelve a adjuntar una
        # versión corregida, se actualiza el mismo documento.
        if (
            codigo_tipo_documento
            == "DOCUMENTO_CIERRE_DISCIPLINARIO"
        ):
            existente_proceso = (
                db.query(
                    DocumentoProcesoDisciplinario
                )
                .filter(
                    DocumentoProcesoDisciplinario
                    .IdProcesoDisciplinario
                    == IdProcesoDisciplinario,
                    DocumentoProcesoDisciplinario
                    .TipoDocumento
                    == (
                        "DOCUMENTO_CIERRE_DISCIPLINARIO"
                    ),
                )
                .order_by(
                    DocumentoProcesoDisciplinario
                    .IdDocumentoProcesoDisciplinario
                    .desc()
                )
                .first()
            )

            if existente_proceso:
                nuevo = existente_proceso
                nuevo.NombreArchivo = (
                    nombre_archivo
                )
                nuevo.RutaArchivo = str(
                    ruta_archivo_relativa
                )
                nuevo.Observacion = (
                    Observacion
                )
                nuevo.DocumentoCargado = (
                    contenido_archivo
                )
                nuevo.Formato = (
                    formato_documento
                )
                nuevo.FechaActualizacion = (
                    datetime.now(
                        timezone.utc
                    )
                )
            else:
                nuevo = (
                    DocumentoProcesoDisciplinario(
                        IdProcesoDisciplinario=(
                            IdProcesoDisciplinario
                        ),
                        TipoDocumento=(
                            "DOCUMENTO_CIERRE_DISCIPLINARIO"
                        ),
                        NombreArchivo=(
                            nombre_archivo
                        ),
                        RutaArchivo=str(
                            ruta_archivo_relativa
                        ),
                        Observacion=(
                            Observacion
                        ),
                        DocumentoCargado=(
                            contenido_archivo
                        ),
                        Formato=(
                            formato_documento
                        ),
                    )
                )

                db.add(nuevo)

        else:
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
            if (
                codigo_tipo_documento
                == "CARTA_DESCARGOS_FIRMADA"
            ):
                codigo_expediente = (
                    _nombre_expediente_evidencias(
                        proceso
                    )
                )

                extension_carpeta = (
                    Path(nombre_archivo)
                    .suffix
                    .lower()
                    or ".pdf"
                )

                nombre_carpeta_digital = (
                    "02 - Acta de Descargos - "
                    f"{codigo_expediente}"
                    f"{extension_carpeta}"
                )

                existente_carpeta = (
                    db.execute(
                        text(
                            """
                            SELECT
                                d."IdDocumento"
                            FROM public."Documentos" d
                            INNER JOIN public."RelacionTipoDocumentacion" rtd
                                ON rtd."IdDocumento" = d."IdDocumento"
                            WHERE rtd."IdRegistroPersonal" = :id_registro_personal
                              AND d."IdTipoDocumentacion" = :id_tipo_documentacion
                              AND d."Nombre" = :nombre_archivo
                            ORDER BY d."IdDocumento" DESC
                            LIMIT 1
                            """
                        ),
                        {
                            "id_registro_personal": (
                                proceso.IdRegistroPersonal
                            ),
                            "id_tipo_documentacion": (
                                id_tipo_carpeta_digital
                            ),
                            "nombre_archivo": (
                                nombre_carpeta_digital
                            ),
                        },
                    )
                    .mappings()
                    .first()
                )

                if existente_carpeta:
                    db.execute(
                        text(
                            """
                            UPDATE public."Documentos"
                            SET
                                "DocumentoCargado" = :documento_cargado,
                                "FechaActualizacion" = NOW(),
                                "Formato" = :formato
                            WHERE "IdDocumento" = :id_documento
                            """
                        ),
                        {
                            "documento_cargado": (
                                contenido_archivo
                            ),
                            "formato": (
                                formato_documento
                            ),
                            "id_documento": int(
                                existente_carpeta[
                                    "IdDocumento"
                                ]
                            ),
                        },
                    )
                else:
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
                        nombre_archivo=(
                            nombre_carpeta_digital
                        ),
                        formato=formato_documento,
                    )

            elif (
                codigo_tipo_documento
                == "DOCUMENTO_CIERRE_DISCIPLINARIO"
            ):
                # El cierre debe quedar como 04 y debe ser idempotente
                # para no crear duplicados en Carpeta Digital.
                nombre_carpeta_digital = (
                    nombre_archivo
                )

                existente_carpeta = (
                    db.execute(
                        text(
                            """
                            SELECT
                                d."IdDocumento"
                            FROM public."Documentos" d
                            INNER JOIN public."RelacionTipoDocumentacion" rtd
                                ON rtd."IdDocumento" = d."IdDocumento"
                            WHERE rtd."IdRegistroPersonal" = :id_registro_personal
                              AND d."IdTipoDocumentacion" = :id_tipo_documentacion
                              AND d."Nombre" = :nombre_archivo
                            ORDER BY d."IdDocumento" DESC
                            LIMIT 1
                            """
                        ),
                        {
                            "id_registro_personal": (
                                proceso.IdRegistroPersonal
                            ),
                            "id_tipo_documentacion": (
                                id_tipo_carpeta_digital
                            ),
                            "nombre_archivo": (
                                nombre_carpeta_digital
                            ),
                        },
                    )
                    .mappings()
                    .first()
                )

                if existente_carpeta:
                    db.execute(
                        text(
                            """
                            UPDATE public."Documentos"
                            SET
                                "DocumentoCargado" = :documento_cargado,
                                "FechaActualizacion" = NOW(),
                                "Formato" = :formato
                            WHERE "IdDocumento" = :id_documento
                            """
                        ),
                        {
                            "documento_cargado": (
                                contenido_archivo
                            ),
                            "formato": (
                                formato_documento
                            ),
                            "id_documento": int(
                                existente_carpeta[
                                    "IdDocumento"
                                ]
                            ),
                        },
                    )
                else:
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
                        nombre_archivo=(
                            nombre_carpeta_digital
                        ),
                        formato=formato_documento,
                    )

            else:
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
                "antes de generar el Acta de Descargos."
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

        evidencias_no_visuales = (
            registrar_evidencias_no_visuales_trabajador_carpeta_digital(
                db=db,
                proceso=proceso,
                evidencias=evidencias,
            )
        )

        db.commit()
        db.refresh(documento)

        return {
            "success": True,
            "message": "El Acta de Descargos fue generada correctamente.",
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
                "EvidenciasNoVisualesCarpetaDigital": (
                    evidencias_no_visuales
                ),
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
                "mensaje": "No fue posible generar el Acta de Descargos.",
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
    - Acta de Descargos generada.
    - Acta de Descargos firmada.
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