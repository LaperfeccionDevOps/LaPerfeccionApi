from pydantic import BaseModel
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session
from sqlalchemy import text
import pdfkit
import base64
import os

from datetime import datetime, date, timezone, timedelta
from html import escape as escape_html
import re

from infrastructure.db.deps import get_db


router = APIRouter(
    prefix="/api/descargar-documentos",
    tags=["descargar documentos"],
)


class DocumentoRequest(BaseModel):
    tipo: str  # entrevista, referencias, tratamiento_datos
    datos: dict
    # Compatibilidad: un trabajador contratado puede enviar solo la vinculación,
    # mientras que el aspirante nuevo todavía no tiene ciclo laboral.
    IdVinculacionLaboral: int | None = None
    IdRegistroPersonal: int | None = None
    # Este dato se CONTRASTA con BD; nunca determina por sí solo la empresa.
    IdEmpresaContratante: int | None = None


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
    id_vinculacion_laboral: int,
    id_registro_personal: int | None = None,
) -> dict:
    """
    Flujo existente: obtiene la empresa del CICLO LABORAL solicitado.
    Si llega además la persona, comprueba que el ciclo le pertenezca.
    """
    filtro_persona = (
        'AND vl."IdRegistroPersonal" = :id_registro_personal'
        if id_registro_personal is not None else ''
    )
    parametros = {"id_vinculacion_laboral": id_vinculacion_laboral}
    if id_registro_personal is not None:
        parametros["id_registro_personal"] = id_registro_personal

    query = text(f"""
        SELECT
            ec."IdEmpresaContratante",
            ec."Codigo",
            ec."Nombre",
            ec."Logo"
        FROM public."VinculacionLaboral" vl
        INNER JOIN public."EmpresaContratante" ec
            ON ec."IdEmpresaContratante" = vl."IdEmpresaContratante"
        WHERE vl."IdVinculacionLaboral" = :id_vinculacion_laboral
          {filtro_persona}
          AND ec."Activo" = TRUE
        LIMIT 1
    """)
    row = db.execute(query, parametros).mappings().fetchone()
    if not row:
        raise HTTPException(
            status_code=400,
            detail=(
                "La vinculación laboral no existe para el trabajador indicado "
                "o no tiene una empresa contratante válida asignada."
            ),
        )
    return dict(row)


def obtener_empresa_contratante_desde_rq(
    db: Session,
    id_registro_personal: int,
) -> dict:
    """
    Aspirantes sin VinculacionLaboral: consulta la única RQ activa de la
    persona. La empresa se toma de RQOperaciones, jamás del ID enviado
    libremente por el navegador ni de una vinculación histórica.
    Solo lectura: no crea ni actualiza datos de BD.
    """
    rows = db.execute(
        text("""
            SELECT
                rq."IdRQOperaciones",
                ec."IdEmpresaContratante",
                ec."Codigo",
                ec."Nombre",
                ec."Logo",
                ec."Activo" AS "EmpresaActiva"
            FROM public."RQCandidato" rc
            INNER JOIN public."RQOperaciones" rq
                ON rq."IdRQOperaciones" = rc."IdRQOperaciones"
            LEFT JOIN public."EmpresaContratante" ec
                ON ec."IdEmpresaContratante" = rq."IdEmpresaContratante"
            WHERE rc."IdRegistroPersonal" = :id_registro_personal
              AND COALESCE(rc."Activo", true) = true
              AND COALESCE(rq."Activo", true) = true
            ORDER BY rc."FechaVinculacion" DESC, rc."IdRQCandidato" DESC
            LIMIT 2
        """),
        {"id_registro_personal": id_registro_personal},
    ).mappings().all()

    if not rows:
        raise HTTPException(
            status_code=409,
            detail=(
                "El aspirante no tiene una RQ activa con empresa contratante. "
                "Verifique su asociación antes de generar el documento."
            ),
        )
    if len(rows) > 1:
        raise HTTPException(
            status_code=409,
            detail=(
                "El aspirante figura en varias RQ activas. "
                "Corrija la asociación antes de generar el documento."
            ),
        )

    row = rows[0]
    if row["IdEmpresaContratante"] is None or row["EmpresaActiva"] is not True:
        raise HTTPException(
            status_code=409,
            detail="La RQ activa no tiene una empresa contratante válida y activa.",
        )
    return {
        "IdEmpresaContratante": int(row["IdEmpresaContratante"]),
        "Codigo": row["Codigo"],
        "Nombre": row["Nombre"],
        "Logo": row["Logo"],
    }


def resolver_empresa_para_documento(db: Session, body: DocumentoRequest) -> dict:
    """Prioridad del ciclo laboral; si no existe, única RQ activa del aspirante."""
    id_vinculacion = body.IdVinculacionLaboral
    id_persona = body.IdRegistroPersonal
    id_empresa_cliente = body.IdEmpresaContratante

    if id_vinculacion is not None and id_vinculacion <= 0:
        raise HTTPException(status_code=400, detail="IdVinculacionLaboral debe ser positivo.")
    if id_persona is not None and id_persona <= 0:
        raise HTTPException(status_code=400, detail="IdRegistroPersonal debe ser positivo.")
    if id_empresa_cliente is not None and id_empresa_cliente <= 0:
        raise HTTPException(status_code=400, detail="IdEmpresaContratante debe ser positivo.")

    if id_vinculacion is not None:
        # Conserva la ruta histórica para contratados y reintegros.
        empresa = obtener_empresa_contratante(db, id_vinculacion, id_persona)
    else:
        if id_persona is None:
            raise HTTPException(
                status_code=422,
                detail=(
                    "Para generar documentos sin vinculación laboral se requiere "
                    "IdRegistroPersonal y una RQ activa."
                ),
            )
        empresa = obtener_empresa_contratante_desde_rq(db, id_persona)

    # Si el frontend suministra empresa, solo funciona como validación
    # adicional: jamás puede reemplazar el resultado de la base de datos.
    if (
        id_empresa_cliente is not None
        and id_empresa_cliente != int(empresa["IdEmpresaContratante"])
    ):
        raise HTTPException(
            status_code=409,
            detail=(
                "La empresa contratante enviada no coincide con la "
                "empresa del ciclo laboral o de la RQ activa."
            ),
        )
    return empresa


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


def ajustar_paginacion_entrevista(html: str) -> str:
    """Evita una página vacía al final sin eliminar contenido del documento."""
    css = (
        '<style media="print" id="entrevista-qa-sin-pagina-vacia">'
        'html,body{height:auto!important;min-height:0!important;}'
        'body > :last-child,body > :last-child > :last-child'
        '{page-break-after:auto!important;break-after:auto!important;}'
        '</style>'
    )
    cierre_head = re.search(r"</head\s*>", html, flags=re.I)
    if cierre_head:
        return html[:cierre_head.start()] + css + html[cierre_head.start():]
    return css + html


async def html_to_pdf_base64(body):
    html_content = body.get("html")
    es_entrevista = body.get("tipo") == "entrevista"
    if es_entrevista and html_content:
        html_content = ajustar_paginacion_entrevista(html_content)

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
        if es_entrevista:
            # Solo la entrevista: aprovecha el espacio de la hoja A4
            # para que el sello final no empuje una página vacía.
            options.update({
                "page-size": "A4",
                "margin-top": "6mm",
                "margin-bottom": "4mm",
                "zoom": "0.97",
            })

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




def obtener_ultimo_guardado_entrevista(db: Session, body: DocumentoRequest):
    """Lee exclusivamente la fecha auditada en BD; nunca utiliza hora de descarga."""
    id_persona = body.IdRegistroPersonal
    id_vinculacion = body.IdVinculacionLaboral
    if not id_persona and id_vinculacion:
        id_persona = db.execute(text('''SELECT "IdRegistroPersonal" FROM public."VinculacionLaboral"
            WHERE "IdVinculacionLaboral" = :id LIMIT 1'''), {"id": id_vinculacion}).scalar()
    if not id_persona:
        print('[PDF entrevista][fecha] Falta IdRegistroPersonal para consultar auditoría.')
        return None

    columnas = set(db.execute(text('''SELECT column_name FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = 'EntrevistaCandidato' ''')).scalars().all())
    fks = [c for c in ('IdRegistroPerso', 'IdRegistroPersonal') if c in columnas]
    fechas = [c for c in ('FechaActualizacion', 'FechaActualiza', 'Fecha_Actualizacion', 'ActualizadoEn', 'UpdatedAt', 'FechaCreacion', 'Fecha_Creacion', 'CreadoEn', 'CreatedAt') if c in columnas]
    if not fks or not fechas:
        print('[PDF entrevista][fecha] No se encontraron columnas de registro/fecha:', fks, fechas)
        return None
    # Las instalaciones pueden tener DATE y TIMESTAMP en columnas distintas.
    # Se convierten a texto para evitar incompatibilidades en COALESCE.
    expresion = 'COALESCE(' + ', '.join(
        f'CAST("{c}" AS TEXT)' for c in fechas
    ) + ')'
    parametros = {'id_persona': id_persona}
    filtro_ciclo = ''
    if id_vinculacion and 'IdVinculacionLaboral' in columnas:
        filtro_ciclo = ' AND "IdVinculacionLaboral" = :id_vinculacion'
        parametros['id_vinculacion'] = id_vinculacion
    filtro_persona = ' OR '.join(f'"{fk}" = :id_persona' for fk in fks)
    sql = text(f'''SELECT {expresion} AS fecha FROM public."EntrevistaCandidato"
       WHERE ({filtro_persona}) {filtro_ciclo}
       ORDER BY {expresion} DESC NULLS LAST LIMIT 1''')
    fecha = db.execute(sql, parametros).scalar()
    print('[PDF entrevista][fecha] Resultado auditoría:', 'ENCONTRADO' if fecha else 'SIN FECHA', 'columnas:', fechas)
    return fecha


def fecha_entrevista_formato_colombia(valor):
    """11/11/2026 · 2:23 p. m. (America/Bogota)."""
    if valor is None:
        return None
    if isinstance(valor, str):
        try:
            valor = datetime.fromisoformat(valor.replace('Z', '+00:00'))
        except ValueError:
            return None
    if isinstance(valor, datetime):
        if valor.tzinfo is None:
            # Los timestamps sin zona de este despliegue se leen en hora local.
            valor = valor.replace(tzinfo=timezone(timedelta(hours=-5)))
        valor = valor.astimezone(timezone(timedelta(hours=-5)))
        hora12 = valor.hour % 12 or 12
        meridiano = 'a. m.' if valor.hour < 12 else 'p. m.'
        return f'{valor:%d/%m/%Y} · {hora12}:{valor:%M} {meridiano}'
    if isinstance(valor, date):
        return f'{valor:%d/%m/%Y} · Hora no registrada'
    return None


def colocar_fecha_fuera_tablas_entrevista(html: str, fecha: str) -> str:
    """Sello discreto debajo de la última tabla, dentro de la misma página.

    No se pega al final de </body> (podría quedar fuera de contenedores y
    pasar a una página nueva). No cambia logos, estilos ni contenido de tablas.
    """
    if not fecha:
        return html
    pie = (
        '<div style="display:block;clear:none;margin:2px 0 0 0;'
        'padding:0;border:0;line-height:1.1;text-align:left;'
        'font-family:Arial,sans-serif;font-size:9px;font-weight:normal;'
        'color:#666;page-break-before:avoid;page-break-inside:avoid">'
        '<span style="font-size:7px;color:#888">&#9679;</span>&nbsp;'
        + escape_html(fecha) + '</div>'
    )
    # La fecha va justo DESPUÉS de la última tabla de la entrevista,
    # antes de cerrar cualquier contenedor principal de la plantilla.
    cierres = list(re.finditer(r'</table\s*>', html, flags=re.I))
    if cierres:
        pos = cierres[-1].end()
        return html[:pos] + pie + html[pos:]
    # Compatibilidad si en QA existe una plantilla sin tablas.
    cierre = re.search(r'</body\s*>', html, flags=re.I)
    if cierre:
        return html[:cierre.start()] + pie + html[cierre.start():]
    return html + pie


@router.post("/descargar-documento-pdf")
async def descargar_documento_pdf(
    body: DocumentoRequest,
    db: Session = Depends(get_db)
):
    try:

        # 1. Con vinculación laboral: empresa del ciclo.
        #    Sin ella: empresa de la RQ activa del aspirante.
        empresa = resolver_empresa_para_documento(db, body)

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

        # Solo para entrevistas: el sello proviene de la BD y NO del reloj
        # del navegador ni de la fecha de descarga.
        if body.tipo == 'entrevista':
            # Un problema al consultar la auditoría NUNCA debe impedir
            # generar el PDF ni guardar la entrevista (67).
            # El SAVEPOINT recupera la transacción si PostgreSQL rechaza la consulta.
            fecha_guardado = None
            try:
                with db.begin_nested():
                    fecha_auditada = obtener_ultimo_guardado_entrevista(db, body)
                fecha_guardado = fecha_entrevista_formato_colombia(fecha_auditada)
            except Exception as error_fecha:
                print('[PDF entrevista] No se pudo leer fecha de guardado:', str(error_fecha))
            if not fecha_guardado:
                # Fallback de presentación: mismo valor que muestra el historial
                # del aspirante (ya conocido ANTES de solicitar el PDF).
                # NO es la hora actual ni se calcula durante la descarga.
                datos_entrada = body.datos.get('additionalProp1', body.datos)
                if isinstance(datos_entrada, dict):
                    fecha_historial = datos_entrada.get('FECHA_ULTIMO_GUARDADO')
                    fecha_guardado = fecha_entrevista_formato_colombia(fecha_historial)
                if fecha_guardado:
                    print('[PDF entrevista][fecha] Se usó el último guardado mostrado en historial.')
                else:
                    print('[PDF entrevista][fecha] Sin fecha de guardado verificable; no se agrega sello.')
            if fecha_guardado:
                html_modificado = colocar_fecha_fuera_tablas_entrevista(
                    html_modificado, fecha_guardado
                )

        print(
            "HTML modificado generado:\n"
            f"{html_modificado[:200]}..."
        )

        # 4. Convertir el HTML final a PDF.
        html_request = {
            "html": html_modificado,
            "tipo": body.tipo
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