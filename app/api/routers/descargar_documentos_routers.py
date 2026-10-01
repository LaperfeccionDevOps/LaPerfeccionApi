from pydantic import BaseModel
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session
from sqlalchemy import text
import pdfkit
import base64
import os

from infrastructure.db.deps import get_db


router = APIRouter(
    prefix="/api/descargar-documentos",
    tags=["descargar documentos"],
)


class DocumentoRequest(BaseModel):
    tipo: str  # entrevista, referencias, tratamiento_datos
    datos: dict
    IdVinculacionLaboral: int


def leer_plantilla(tipo: str) -> str:
    base_path = os.path.join(
        os.path.dirname(__file__),
        "..\\..",
        "utilidades",
        "plantillas_html",
        "seleccion"
    )

    print(f"Buscando plantilla en: {base_path}")

    archivos = {
        "entrevista": "entrevista_colaborador.txt",
        "referencias": "referencias.txt",
        "tratamiento_datos": "tratamiento_datos.txt"
    }

    archivo = archivos.get(tipo)

    if not archivo:
        raise ValueError("Tipo de documento no soportado")

    ruta = os.path.abspath(os.path.join(base_path, archivo))

    with open(ruta, encoding="utf-8") as f:
        return f.read()


def obtener_empresa_contratante(
    db: Session,
    id_vinculacion_laboral: int
) -> dict:
    """
    Obtiene la empresa contratante asociada al ciclo laboral actual.

    La empresa se obtiene desde VinculacionLaboral y no desde
    RegistroPersonal, ya que una misma persona puede tener diferentes
    ciclos laborales con distintas empresas contratantes.
    """

    query = text("""
        SELECT
            ec."IdEmpresaContratante",
            ec."Codigo",
            ec."Nombre",
            ec."Logo"
        FROM public."VinculacionLaboral" vl
        INNER JOIN public."EmpresaContratante" ec
            ON ec."IdEmpresaContratante" = vl."IdEmpresaContratante"
        WHERE vl."IdVinculacionLaboral" = :id_vinculacion_laboral
          AND ec."Activo" = TRUE
        LIMIT 1
    """)

    row = db.execute(
        query,
        {
            "id_vinculacion_laboral": id_vinculacion_laboral
        }
    ).mappings().fetchone()

    if not row:
        raise HTTPException(
            status_code=400,
            detail=(
                "La vinculación laboral no tiene una empresa contratante "
                "válida asignada."
            )
        )

    return dict(row)


def preparar_datos_empresa(
    datos: dict,
    empresa: dict
) -> dict:
    """
    Incorpora al documento la información correspondiente a la
    empresa contratante y deja todos los campos de la plantilla
    en un único nivel.

    El frontend conserva el formato histórico:
        {"additionalProp1": {...campos...}}

    Antes se agregaban los datos de empresa por fuera de
    additionalProp1. Eso impedía a reemplazar_datos_plantilla()
    aplanar el objeto y podía dejar marcadores como @FIRMA sin
    reemplazar dentro del HTML.

    El logo de la empresa se convierte a data URI Base64 para
    que wkhtmltopdf no dependa de rutas file:/// de Windows.

    Marcadores disponibles:

    @LOGO
    @LOGO_EMPRESA
    @EMPRESA_CODIGO
    @EMPRESA_NOMBRE
    @EMPRESA_RAZON_SOCIAL
    @EMPRESA_IDENTIFICACION

    ALP:
        ASEOS LA PERFECCIÓN S.A.S.
        NIT N.° 800.068.462-4

    MI:
        MANTENER INGENIERÍA

    No se asigna a MI el NIT de ALP.
    """

    # El frontend envía históricamente los campos dentro de
    # "additionalProp1". Se aplanan ANTES de agregar empresa.
    if (
        isinstance(datos, dict)
        and len(datos) == 1
        and isinstance(datos.get("additionalProp1"), dict)
    ):
        datos_documento = dict(datos["additionalProp1"])
    else:
        datos_documento = dict(datos)

    logo_relativo = empresa.get("Logo") or ""

    # La ruta almacenada en EmpresaContratante.Logo
    # es relativa a la carpeta /app.
    app_path = os.path.abspath(
        os.path.join(
            os.path.dirname(__file__),
            "..\\.."
        )
    )

    logo_absoluto = os.path.abspath(
        os.path.join(
            app_path,
            logo_relativo
        )
    )

    # Convertimos el logo seleccionado por la empresa a Base64.
    # Así wkhtmltopdf no tiene que resolver rutas locales file:///.
    logo_data_uri = ""

    if logo_relativo:
        if not os.path.isfile(logo_absoluto):
            raise HTTPException(
                status_code=500,
                detail=(
                    "No se encontró el logo de la empresa contratante en: "
                    f"{logo_absoluto}"
                )
            )

        extension = os.path.splitext(logo_absoluto)[1].lower()

        tipos_mime = {
            ".png": "image/png",
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".gif": "image/gif",
            ".webp": "image/webp",
        }

        mime_type = tipos_mime.get(extension, "image/png")

        with open(logo_absoluto, "rb") as archivo_logo:
            logo_base64 = base64.b64encode(
                archivo_logo.read()
            ).decode("utf-8")

        logo_data_uri = (
            f"data:{mime_type};base64,{logo_base64}"
        )

    codigo_empresa = (
        empresa.get("Codigo") or ""
    ).strip().upper()

    datos_documento["EMPRESA_CODIGO"] = codigo_empresa
    datos_documento["EMPRESA_NOMBRE"] = (
        empresa.get("Nombre") or ""
    )

    # Datos legales específicos de la empresa.
    if codigo_empresa == "ALP":
        datos_documento["EMPRESA_RAZON_SOCIAL"] = (
            "ASEOS LA PERFECCIÓN S.A.S."
        )

        datos_documento["EMPRESA_IDENTIFICACION"] = (
            ", identificada con NIT N.° 800.068.462-4"
        )

    elif codigo_empresa == "MI":
        datos_documento["EMPRESA_RAZON_SOCIAL"] = (
            "MANTENER INGENIERÍA"
        )

        # No se utiliza el NIT de ALP para MI.
        datos_documento["EMPRESA_IDENTIFICACION"] = ""

    else:
        datos_documento["EMPRESA_RAZON_SOCIAL"] = (
            empresa.get("Nombre") or ""
        )
        datos_documento["EMPRESA_IDENTIFICACION"] = ""

    # La empresa del ciclo manda sobre cualquier logo que
    # haya llegado previamente desde el frontend.
    datos_documento["LOGO"] = logo_data_uri
    datos_documento["LOGO_EMPRESA"] = logo_data_uri

    return datos_documento

class DocumentoFactory:

    @staticmethod
    def crear_documento(
        tipo: str,
        datos: dict
    ) -> str:

        plantilla_html = leer_plantilla(tipo)

        print(
            f"Plantilla HTML leída para tipo '{tipo}':\n"
            f"{plantilla_html[:200]}..."
        )

        return reemplazar_datos_plantilla(
            plantilla_html,
            datos,
            tipo
        )


def reemplazar_datos_plantilla(
    html: str,
    datos: dict,
    tipo: str
) -> str:

    print(
        f"Reemplazando datos en la plantilla HTML con: {datos}"
    )

    print(
        "VALOR DE FUNCIONES:",
        datos.get("FUNCIONES")
    )

    # Mantiene compatibilidad con el formato anterior,
    # donde los datos podían venir dentro de un único
    # objeto anidado.
    if (
        len(datos) == 1
        and isinstance(
            list(datos.values())[0],
            dict
        )
    ):
        datos = list(datos.values())[0]

    # Se ordenan las claves de mayor a menor longitud
    # para evitar reemplazos parciales entre marcadores
    # que tengan nombres similares.
    for key in sorted(
        datos.keys(),
        key=len,
        reverse=True
    ):
        value = datos[key]

        if value is None:
            value = ""

        # Los datos de empresa y las rutas de imágenes
        # deben conservar exactamente su contenido.
        if key in {
            "LOGO",
            "LOGO_EMPRESA",
            "EMPRESA_CODIGO",
            "EMPRESA_NOMBRE",
            "EMPRESA_RAZON_SOCIAL",
            "EMPRESA_IDENTIFICACION"
        }:
            valor_final = str(value)

        elif tipo in [
            "entrevista",
            "referencias"
        ]:
            valor_final = str(value).upper()

        else:
            valor_final = str(value)

        html = html.replace(
            f"@{key}",
            valor_final
        )

    return html


async def html_to_pdf_base64(body):
    html_content = body.get("html")

    if not html_content:
        return JSONResponse(
            status_code=400,
            content={
                "error": "HTML content is required"
            }
        )

    try:
        print(
            "Generando PDF a partir del HTML:\n"
            f"{html_content[:200]}..."
        )

        wkhtmltopdf_path = (
            r"C:\Program Files\wkhtmltopdf\bin\wkhtmltopdf.exe"
        )

        print(
            "RUTA WKHTMLTOPDF:",
            wkhtmltopdf_path
        )

        print(
            "EXISTE EL ARCHIVO?:",
            os.path.exists(wkhtmltopdf_path)
        )

        if not os.path.exists(wkhtmltopdf_path):
            return JSONResponse(
                status_code=500,
                content={
                    "error": (
                        "No se encontró wkhtmltopdf "
                        f"en la ruta: {wkhtmltopdf_path}"
                    )
                }
            )

        config = pdfkit.configuration(
            wkhtmltopdf=wkhtmltopdf_path
        )

        options = {
            "enable-local-file-access": None
        }

        pdf_bytes = pdfkit.from_string(
            html_content,
            False,
            configuration=config,
            options=options
        )

        pdf_base64 = base64.b64encode(
            pdf_bytes
        ).decode("utf-8")

        return {
            "pdf_base64": pdf_base64
        }

    except Exception as e:
        print(
            "ERROR GENERANDO PDF:",
            str(e)
        )

        return JSONResponse(
            status_code=500,
            content={
                "error": str(e)
            }
        )


@router.post("/descargar-documento-pdf")
async def descargar_documento_pdf(
    body: DocumentoRequest,
    db: Session = Depends(get_db)
):
    try:

        # 1. Obtener la empresa contratante desde
        #    el ciclo laboral específico.
        empresa = obtener_empresa_contratante(
            db,
            body.IdVinculacionLaboral
        )

        print(
            "EMPRESA CONTRATANTE DOCUMENTO:",
            empresa
        )

        # 2. Incorporar la información de la empresa
        #    dentro de los datos que utilizará la plantilla.
        datos_documento = preparar_datos_empresa(
            body.datos,
            empresa
        )

        # 3. Generar el HTML con la plantilla correspondiente.
        html_modificado = DocumentoFactory.crear_documento(
            body.tipo,
            datos_documento
        )

        print(
            "HTML modificado generado:\n"
            f"{html_modificado[:200]}..."
        )

        # 4. Convertir el HTML final a PDF.
        html_request = {
            "html": html_modificado
        }

        return await html_to_pdf_base64(
            html_request
        )

    except HTTPException:
        raise

    except Exception as e:
        print(
            "ERROR EN descargar_documento_pdf:",
            str(e)
        )

        return JSONResponse(
            status_code=400,
            content={
                "error": str(e)
            }
        )