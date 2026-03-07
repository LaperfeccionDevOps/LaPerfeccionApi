from pydantic import BaseModel
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
import pdfkit
import base64
import os

router = APIRouter(
    prefix="/api/descargar-documentos",
    tags=["descargar documentos"],
)

class DocumentoRequest(BaseModel):
    tipo: str  # entrevista, referencias, tratamiento_datos
    datos: dict


def leer_plantilla(tipo: str) -> str:
    base_path = os.path.join(os.path.dirname(__file__), "..\\..", "utilidades", "plantillas_html", "seleccion")
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

class DocumentoFactory:
    @staticmethod
    def crear_documento(tipo: str, datos: dict) -> str:
        plantilla_html = leer_plantilla(tipo)
        print(f"Plantilla HTML leída para tipo '{tipo}':\n{plantilla_html[:200]}...")  # Mostrar solo los primeros 200 caracteres
        return reemplazar_datos_plantilla(plantilla_html, datos)
    
def reemplazar_datos_plantilla(html: str, datos: dict) -> str:
    print(f"Reemplazando datos en la plantilla HTML con: {datos}")
    # Si datos viene como {'additionalProp1': {...}}, tomar el primer valor
    if len(datos) == 1 and isinstance(list(datos.values())[0], dict):
        datos = list(datos.values())[0]
    # Detectar el tipo desde el contexto de llamada
    import inspect
    tipo = None
    stack = inspect.stack()
    for frame in stack:
        if 'tipo' in frame.frame.f_locals:
            tipo = frame.frame.f_locals['tipo']
            break
    for key, value in datos.items():
        if tipo in ['entrevista', 'referencias']:
            html = html.replace(f"@{key}", str(value).upper())
        else:
            html = html.replace(f"@{key}", str(value))
    return html

async def html_to_pdf_base64(body):
    html_content = body["html"]
    if not html_content:
        return JSONResponse(status_code=400, content={"error": "HTML content is required"})
    try:
        print(f"Generando PDF a partir del HTML:\n{html_content[:200]}...")  # Mostrar solo los primeros 200 caracteres
        wkhtmltopdf_path = r"C:\Program Files\wkhtmltopdf\bin\wkhtmltopdf.exe"
        config = pdfkit.configuration(wkhtmltopdf=wkhtmltopdf_path)
        pdf_bytes = pdfkit.from_string(html_content, False, configuration=config)
        pdf_base64 = base64.b64encode(pdf_bytes).decode("utf-8")
        return {"pdf_base64": pdf_base64}
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})


@router.post("/descargar-documento-pdf")
async def descargar_documento_pdf(body: DocumentoRequest):
    try:
        html_modificado = DocumentoFactory.crear_documento(body.tipo, body.datos)
        print(f"HTML modificado generado:\n{html_modificado[:200]}...")  # Mostrar solo los primeros 200 caracteres
        html_request = {"html": html_modificado}
        return await html_to_pdf_base64(html_request)
    except Exception as e:
        return JSONResponse(status_code=400, content={"error": str(e)})









