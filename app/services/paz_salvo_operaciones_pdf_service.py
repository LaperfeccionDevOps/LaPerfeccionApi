# ruff: noqa: BLE001

import logging
from datetime import date, datetime, timedelta, timezone
from io import BytesIO
from pathlib import Path
from typing import Any
from xml.sax.saxutils import escape

from fastapi import HTTPException
from PIL import Image as PILImage
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import (
    Image,
    KeepTogether,
    Paragraph,
    PageBreak,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)
from sqlalchemy import text
from sqlalchemy.orm import Session


logger = logging.getLogger(__name__)


# ============================================================
# CONFIGURACIÓN GENERAL
# ============================================================

ZONA_HORARIA_COLOMBIA = timezone(timedelta(hours=-5))

BASE_DIR = Path(__file__).resolve().parents[1]

RUTA_LOGO_EMPRESA = (
    BASE_DIR
    / "assets"
    / "comunicaciones"
    / "LOGO_EMPRESA.jpeg"
)

RUTA_LOGO_ISSA = (
    BASE_DIR
    / "assets"
    / "comunicaciones"
    / "LOGO_ISSA.jpeg.png"
)

RUTA_LOGO_CERTIFICACIONES = (
    BASE_DIR
    / "assets"
    / "comunicaciones"
    / "LOGO_CERTIFICACIONES.jpeg"
)

# Importante:
# El Paz y Salvo NO utiliza logo de Mantener Ingeniería.

CODIGO_DOCUMENTO = "F-TH-019"
VERSION_DOCUMENTO = "08"
VIGENTE_DESDE = "2024/10/07"

OBJETIVO_REPORTE = (
    "Dar información detallada sobre la terminación de contrato de los "
    "trabajadores de las distintas áreas de la compañía, con el fin de "
    "dar claridad al motivo del mismo."
)

PIE_LINEA_1 = (
    "TÉCNICOS EN LIMPIEZA DE: EMPRESAS, BANCOS, COLEGIOS, UNIVERSIDADES, "
    "CENTROS COMERCIALES, CENTRO DE RECREACIÓN, EDIFICIOS (OFICINAS Y "
    "VIVIENDA), HOSPITALES, SUPERMERCADOS, LAVADO Y PINTURA DE FACHADAS, "
    "LAVADO DE VIDRIOS, TAPETES Y CORTINAS."
)
PIE_LINEA_2 = "Calle 4 Bis No. 53 C-50 Bogotá, D.C – Colombia – PBX: 4204893"
PIE_LINEA_3 = (
    "dcomercial@aseoslaperfeccion.com – comercial2@aseoslaperfeccion.com"
)
PIE_LINEA_4 = "www.aseoslaperfeccion.com"


# ============================================================
# HELPERS DE TEXTO Y FORMATO
# ============================================================

def _texto(
    valor: Any,
    valor_vacio: str = "",
) -> str:
    if valor is None:
        return valor_vacio

    resultado = str(valor).strip()
    return resultado if resultado else valor_vacio


def _texto_html(
    valor: Any,
    valor_vacio: str = "",
) -> str:
    return escape(
        _texto(valor, valor_vacio)
    ).replace("\n", "<br/>")


def _fecha(
    valor: date | datetime | None,
) -> str:
    if not valor:
        return ""

    if isinstance(valor, (date, datetime)):
        return valor.strftime("%d/%m/%Y")

    return _texto(valor)


def _fecha_hora_colombia(
    valor: datetime | None,
) -> str:
    if not valor:
        return ""

    fecha_hora = valor

    if fecha_hora.tzinfo is None:
        fecha_hora = fecha_hora.replace(
            tzinfo=ZONA_HORARIA_COLOMBIA
        )
    else:
        fecha_hora = fecha_hora.astimezone(
            ZONA_HORARIA_COLOMBIA
        )

    return fecha_hora.strftime(
        "%d/%m/%Y %I:%M:%S %p"
    ).replace(
        "AM",
        "a. m.",
    ).replace(
        "PM",
        "p. m.",
    )


def _dinero(
    valor: Any,
) -> str:
    if valor in (None, ""):
        return ""

    try:
        numero = float(valor)
    except (TypeError, ValueError):
        return _texto(valor)

    return "$ {:,.0f}".format(numero).replace(",", ".")


def _parrafo(
    valor: Any,
    estilo: ParagraphStyle,
    valor_vacio: str = "",
) -> Paragraph:
    return Paragraph(
        _texto_html(valor, valor_vacio),
        estilo,
    )


def _parrafo_markup(
    valor: str,
    estilo: ParagraphStyle,
) -> Paragraph:
    """
    Paragraph para texto interno controlado por el sistema que sí utiliza
    etiquetas compatibles con ReportLab, por ejemplo <b> y <br/>.
    """
    return Paragraph(
        valor,
        estilo,
    )


def _imagen_disponible(
    ruta: Path,
) -> bool:
    return ruta.is_file()


def _preparar_logo_sin_fondo(
    ruta: Path,
    umbral_blanco: int = 238,
) -> BytesIO:
    """
    Limpia únicamente la presentación del logo dentro del PDF.

    - No modifica el archivo original.
    - Elimina el rectángulo blanco/gris muy claro que rodea el logo.
    - Recorta automáticamente el espacio sobrante.
    - Conserva los colores verdes y grises reales del logotipo.
    - Devuelve un PNG transparente en memoria.
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

        buffer = BytesIO()
        imagen.save(
            buffer,
            format="PNG",
            optimize=True,
        )
        buffer.seek(0)

        return buffer


def _imagen_logo(
    ruta: Path,
    ancho_maximo: float,
    alto_maximo: float,
    limpiar_fondo: bool = False,
):
    """
    Carga un logo conservando siempre su proporción original.

    Cuando limpiar_fondo=True, elimina en memoria el fondo blanco/gris
    sobrante y recorta los márgenes antes de enviarlo a ReportLab.
    """
    if not _imagen_disponible(ruta):
        logger.warning(
            "No se encontró recurso gráfico: %s",
            ruta,
        )
        return Spacer(
            ancho_maximo,
            alto_maximo,
        )

    try:
        fuente_imagen = (
            _preparar_logo_sin_fondo(ruta)
            if limpiar_fondo
            else str(ruta)
        )

        imagen = Image(fuente_imagen)

        ancho_original = float(
            imagen.imageWidth or 1
        )
        alto_original = float(
            imagen.imageHeight or 1
        )

        escala = min(
            ancho_maximo / ancho_original,
            alto_maximo / alto_original,
        )

        imagen.drawWidth = (
            ancho_original * escala
        )
        imagen.drawHeight = (
            alto_original * escala
        )
        imagen.hAlign = "CENTER"

        return imagen

    except (
        OSError,
        TypeError,
        ValueError,
        ZeroDivisionError,
    ) as error:
        logger.warning(
            "No se pudo cargar recurso gráfico %s: %s",
            ruta,
            error,
        )
        return Spacer(
            ancho_maximo,
            alto_maximo,
        )


# ============================================================
# CONSULTA DE DATOS
# ============================================================

def _obtener_datos_paz_salvo(
    db: Session,
    id_paz_y_salvo: int,
):
    consulta = text(
        """
        SELECT
            pso."IdPazYSalvo",
            pso."IdRegistroPersonal",
            pso."IdRetiroLaboral",
            pso."FechaUltimoDiaLaborado",
            pso."Observacion" AS "ObservacionPazYSalvo",
            pso."UsuarioCreacion",
            pso."FechaCreacion" AS "FechaCreacionPazYSalvo",

            rp."NumeroIdentificacion",
            TRIM(
                COALESCE(rp."Nombres", '') || ' ' ||
                COALESCE(rp."Apellidos", '')
            ) AS "NombreCompleto",

            rl."IdCliente",
            rl."IdMotivoRetiro",
            rl."FechaProceso",
            rl."FechaRetiro",
            rl."FechaEnvioOperaciones",
            rl."EstadoCasoRRLL",

            c."Nombre" AS "NombreCliente",

            mr."Nombre" AS "NombreMotivoRetiro",

            psod."IdPazYSalvoDetalle",
            psod."FechaHoraInicioDiligenciamiento",
            psod."ElaboradoPor",
            psod."DescripcionMotivoRetiro",
            psod."Locker",
            psod."Llaves",
            psod."EntregaHerramientas",
            psod."TarjetaControlAcceso",
            psod."EntregaGuantes",
            psod."EntregaMonogafas",
            psod."EntregaPeto",
            psod."ObservacionesEntrega",
            psod."AplicaDescuento",
            psod."ValorDescuento",
            psod."NovedadesNomina",
            psod."PendienteEntregaUniforme",
            psod."UniformePatogeno",
            psod."Botas",
            psod."Zapatos",
            psod."Chaqueta",
            psod."CarnetAlpArl",
            psod."PendientePagoVacunas",
            psod."UsuariosClavesDispositivos",
            psod."CorreoSupervisora",
            psod."EstadoPazYSalvo",
            psod."FechaCreacion" AS "FechaCreacionDetalle",
            psod."FechaActualizacion" AS "FechaActualizacionDetalle",
            psod."UsuarioActualizacion" AS "UsuarioActualizacionDetalle"

        FROM public."PazYSalvoOperaciones" pso

        INNER JOIN public."RegistroPersonal" rp
            ON rp."IdRegistroPersonal"
            = pso."IdRegistroPersonal"

        LEFT JOIN public."RetiroLaboral" rl
            ON rl."IdRetiroLaboral"
            = pso."IdRetiroLaboral"

        LEFT JOIN public."Cliente" c
            ON c."IdCliente"
            = rl."IdCliente"

        LEFT JOIN public."MotivoRetiro" mr
            ON mr."IdMotivoRetiro"
            = rl."IdMotivoRetiro"

        INNER JOIN public."PazYSalvoOperacionesDetalle" psod
            ON psod."IdPazYSalvo"
            = pso."IdPazYSalvo"

        WHERE pso."IdPazYSalvo" = :id_paz_y_salvo

        LIMIT 1;
        """
    )

    fila = (
        db.execute(
            consulta,
            {
                "id_paz_y_salvo": id_paz_y_salvo,
            },
        )
        .mappings()
        .first()
    )

    if not fila:
        raise HTTPException(
            status_code=404,
            detail=(
                "No se encontró el Paz y Salvo digital "
                f"con IdPazYSalvo={id_paz_y_salvo}."
            ),
        )

    return fila


# ============================================================
# ESTILOS
# ============================================================

def _crear_estilos():
    estilos_base = getSampleStyleSheet()

    return {
        "titulo": ParagraphStyle(
            "PazSalvoTitulo",
            parent=estilos_base["Normal"],
            fontName="Helvetica-Bold",
            fontSize=11.0,
            leading=12.0,
            alignment=TA_CENTER,
            textColor=colors.black,
            spaceBefore=0,
            spaceAfter=0,
        ),
        "seccion": ParagraphStyle(
            "PazSalvoSeccion",
            parent=estilos_base["Normal"],
            fontName="Helvetica-Bold",
            fontSize=7.6,
            leading=8.4,
            alignment=TA_CENTER,
            textColor=colors.black,
            spaceBefore=0,
            spaceAfter=0,
        ),
        "etiqueta": ParagraphStyle(
            "PazSalvoEtiqueta",
            parent=estilos_base["Normal"],
            fontName="Helvetica-Bold",
            fontSize=7.0,
            leading=7.7,
            alignment=TA_CENTER,
            textColor=colors.black,
            spaceBefore=0,
            spaceAfter=0,
        ),
        "valor": ParagraphStyle(
            "PazSalvoValor",
            parent=estilos_base["Normal"],
            fontName="Helvetica",
            fontSize=6.6,
            leading=7.3,
            alignment=TA_CENTER,
            textColor=colors.black,
            spaceBefore=0,
            spaceAfter=0,
        ),
        "valor_izquierda": ParagraphStyle(
            "PazSalvoValorIzquierda",
            parent=estilos_base["Normal"],
            fontName="Helvetica",
            fontSize=6.6,
            leading=7.3,
            alignment=TA_LEFT,
            textColor=colors.black,
            spaceBefore=0,
            spaceAfter=0,
        ),
        "texto_pequeno": ParagraphStyle(
            "PazSalvoTextoPequeno",
            parent=estilos_base["Normal"],
            fontName="Helvetica",
            fontSize=5.6,
            leading=6.4,
            alignment=TA_CENTER,
            textColor=colors.black,
            spaceBefore=0,
            spaceAfter=0,
        ),
        "firma": ParagraphStyle(
            "PazSalvoFirma",
            parent=estilos_base["Normal"],
            fontName="Helvetica-BoldOblique",
            fontSize=7.0,
            leading=8.2,
            alignment=TA_LEFT,
            textColor=colors.black,
            spaceBefore=0,
            spaceAfter=0,
        ),
    }

def _estilo_tabla(
    encabezado: bool = False,
) -> TableStyle:
    instrucciones = [
        ("GRID", (0, 0), (-1, -1), 1.0, colors.black),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 2),
        ("RIGHTPADDING", (0, 0), (-1, -1), 2),
        ("TOPPADDING", (0, 0), (-1, -1), 1.2),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 1.2),
    ]

    if encabezado:
        instrucciones.append(
            ("BACKGROUND", (0, 0), (-1, 0), colors.whitesmoke)
        )

    return TableStyle(instrucciones)


# ============================================================
# BLOQUES DEL DOCUMENTO
# ============================================================

def _crear_encabezado(
    estilos,
    solo_logos: bool = False,
):
    """
    Encabezado corporativo del formato oficial.

    Orden visual:
    1. Aseos La Perfección
    2. Certificaciones ICONTEC / IQNET
    3. ISSA

    Los logos se muestran más grandes, juntos y conservando su proporción
    original para acercarse al formato físico de referencia.

    Importante:
    - No se incluye Mantener Ingeniería.
    """

    # Logo principal con mayor presencia, como en el formato original.
    logo_empresa = _imagen_logo(
        RUTA_LOGO_EMPRESA,
        5.85 * cm,
        1.78 * cm,
        limpiar_fondo=True,
    )

    # El recurso de certificaciones contiene ICONTEC / IQNET.
    logo_certificaciones = _imagen_logo(
        RUTA_LOGO_CERTIFICACIONES,
        2.75 * cm,
        1.48 * cm,
    )

    # ISSA se ubica inmediatamente después de las certificaciones.
    logo_issa = _imagen_logo(
        RUTA_LOGO_ISSA,
        1.55 * cm,
        1.30 * cm,
    )

    # Se deja el bloque compacto y alineado hacia la izquierda,
    # tal como se aprecia en el formato original.
    logos = Table(
        [[
            logo_empresa,
            logo_certificaciones,
            logo_issa,
        ]],
        colWidths=[
            6.10 * cm,
            2.80 * cm,
            1.70 * cm,
        ],
        rowHeights=[1.86 * cm],
        hAlign="LEFT",
    )
    logos.setStyle(
        TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("ALIGN", (0, 0), (-1, -1), "CENTER"),
            ("LEFTPADDING", (0, 0), (-1, -1), 0),
            ("RIGHTPADDING", (0, 0), (-1, -1), 0),
            ("TOPPADDING", (0, 0), (-1, -1), 0),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
        ])
    )

    if solo_logos:
        return [
            logos,
            Spacer(1, 0.18 * cm),
        ]

    bloque_codigo = Table(
        [
            [
                _parrafo_markup(
                    f"<b>CÓDIGO:</b> {CODIGO_DOCUMENTO}",
                    estilos["valor"],
                )
            ],
            [
                _parrafo_markup(
                    f"<b>VERSIÓN {VERSION_DOCUMENTO}</b>",
                    estilos["valor"],
                )
            ],
            [
                _parrafo_markup(
                    (
                        "<b>Vigente a partir de:</b><br/>"
                        f"{VIGENTE_DESDE}"
                    ),
                    estilos["valor"],
                )
            ],
        ],
        colWidths=[3.45 * cm],
    )
    bloque_codigo.setStyle(
        TableStyle([
            ("GRID", (0, 0), (-1, -1), 1.0, colors.black),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("LEFTPADDING", (0, 0), (-1, -1), 1),
            ("RIGHTPADDING", (0, 0), (-1, -1), 1),
            ("TOPPADDING", (0, 0), (-1, -1), 2.0),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 2.0),
        ])
    )

    titulo_codigo = Table(
        [[
            _parrafo(
                "PAZ Y SALVO",
                estilos["titulo"],
            ),
            bloque_codigo,
        ]],
        colWidths=[
            13.05 * cm,
            3.45 * cm,
        ],
        rowHeights=[1.90 * cm],
    )
    titulo_codigo.setStyle(
        TableStyle([
            ("GRID", (0, 0), (-1, -1), 1.0, colors.black),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("ALIGN", (0, 0), (-1, -1), "CENTER"),
            ("LEFTPADDING", (0, 0), (-1, -1), 0),
            ("RIGHTPADDING", (0, 0), (-1, -1), 0),
            ("TOPPADDING", (0, 0), (-1, -1), 0),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
        ])
    )

    objetivo = Table(
        [
            [
                _parrafo(
                    "OBJETIVO DEL REPORTE:",
                    estilos["seccion"],
                )
            ],
            [
                _parrafo(
                    OBJETIVO_REPORTE,
                    estilos["valor"],
                )
            ],
        ],
        colWidths=[16.5 * cm],
    )
    objetivo.setStyle(
        TableStyle([
            ("GRID", (0, 0), (-1, -1), 1.0, colors.black),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("LEFTPADDING", (0, 0), (-1, -1), 2),
            ("RIGHTPADDING", (0, 0), (-1, -1), 2),
            ("TOPPADDING", (0, 0), (-1, -1), 2.0),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 2.0),
        ])
    )

    return [
        logos,
        Spacer(1, 0.06 * cm),
        titulo_codigo,
        objetivo,
        Spacer(1, 0.30 * cm),
    ]



def _tabla_datos_realizacion(
    datos,
    estilos,
):
    cliente = _texto(
        datos.get("NombreCliente"),
        "SIN INFORMACIÓN",
    )

    # Según la regla definida para este flujo,
    # Cliente y Sede muestran el mismo valor.
    sede = cliente

    filas = [
        (
            "REALIZADO POR",
            datos.get("ElaboradoPor"),
        ),
        (
            "CORREO",
            datos.get("CorreoSupervisora"),
        ),
        (
            "FECHA Y HORA",
            _fecha_hora_colombia(
                datos.get(
                    "FechaHoraInicioDiligenciamiento"
                )
            ),
        ),
        (
            "CLIENTE",
            cliente,
        ),
        (
            "SEDE",
            sede,
        ),
    ]

    tabla = Table(
        [
            [
                _parrafo(
                    etiqueta,
                    estilos["etiqueta"],
                ),
                _parrafo(
                    valor,
                    estilos["valor"],
                    "SIN INFORMACIÓN",
                ),
            ]
            for etiqueta, valor in filas
        ],
        colWidths=[
            8.25 * cm,
            8.25 * cm,
        ],
    )
    tabla.setStyle(
        TableStyle([
            ("GRID", (0, 0), (-1, -1), 1.0, colors.black),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
            ("FONTNAME", (1, 0), (1, -1), "Helvetica"),
            ("LEFTPADDING", (0, 0), (-1, -1), 2),
            ("RIGHTPADDING", (0, 0), (-1, -1), 2),
            ("TOPPADDING", (0, 0), (-1, -1), 2.4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 2.4),
        ])
    )
    return tabla


def _tabla_datos_colaborador(
    datos,
    estilos,
):
    filas = [
        [
            _parrafo(
                "DATOS COLABORADOR",
                estilos["seccion"],
            ),
            "",
        ],
        [
            _parrafo(
                "NOMBRE",
                estilos["etiqueta"],
            ),
            _parrafo(
                datos.get("NombreCompleto"),
                estilos["valor"],
                "SIN INFORMACIÓN",
            ),
        ],
        [
            _parrafo(
                "ID COLABORADOR",
                estilos["etiqueta"],
            ),
            _parrafo(
                datos.get("NumeroIdentificacion"),
                estilos["valor"],
                "SIN INFORMACIÓN",
            ),
        ],
        [
            _parrafo(
                "ÚLTIMO DÍA LABORADO",
                estilos["etiqueta"],
            ),
            _parrafo(
                _fecha(
                    datos.get(
                        "FechaUltimoDiaLaborado"
                    )
                ),
                estilos["valor"],
                "SIN INFORMACIÓN",
            ),
        ],
    ]

    tabla = Table(
        filas,
        colWidths=[
            8.25 * cm,
            8.25 * cm,
        ],
    )
    tabla.setStyle(
        TableStyle([
            ("SPAN", (0, 0), (1, 0)),
            ("GRID", (0, 0), (-1, -1), 1.0, colors.black),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("FONTNAME", (0, 1), (0, -1), "Helvetica-Bold"),
            ("FONTNAME", (1, 1), (1, -1), "Helvetica"),
            ("LEFTPADDING", (0, 0), (-1, -1), 4),
            ("RIGHTPADDING", (0, 0), (-1, -1), 4),
            ("TOPPADDING", (0, 0), (-1, -1), 4.4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4.4),
        ])
    )
    return tabla


def _tabla_datos_paz_salvo(
    datos,
    estilos,
):
    tabla = Table(
        [
            [
                _parrafo(
                    "DATOS PAZ Y SALVO",
                    estilos["seccion"],
                ),
                "",
            ],
            [
                _parrafo(
                    "MOTIVO",
                    estilos["etiqueta"],
                ),
                _parrafo(
                    datos.get("NombreMotivoRetiro"),
                    estilos["valor"],
                    "SIN INFORMACIÓN",
                ),
            ],
            [
                _parrafo(
                    "DESCRIPCIÓN DEL MOTIVO",
                    estilos["etiqueta"],
                ),
                _parrafo(
                    datos.get("DescripcionMotivoRetiro"),
                    estilos["valor_izquierda"],
                    "SIN INFORMACIÓN",
                ),
            ],
        ],
        colWidths=[
            8.25 * cm,
            8.25 * cm,
        ],
    )
    tabla.setStyle(
        TableStyle([
            ("SPAN", (0, 0), (1, 0)),
            ("GRID", (0, 0), (-1, -1), 1.0, colors.black),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("FONTNAME", (0, 1), (0, -1), "Helvetica-Bold"),
            ("FONTNAME", (1, 1), (1, -1), "Helvetica"),
            ("LEFTPADDING", (0, 0), (-1, -1), 4),
            ("RIGHTPADDING", (0, 0), (-1, -1), 4),
            ("TOPPADDING", (0, 0), (-1, -1), 4.4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4.4),
        ])
    )
    return tabla


def _tabla_entrega_elementos(
    datos,
    estilos,
):
    filas = [
        (
            "ENTREGA DE LOCKER",
            datos.get("Locker"),
        ),
        (
            "ENTREGA DE LLAVES",
            datos.get("Llaves"),
        ),
        (
            "ENTREGA DE HERRAMIENTAS",
            datos.get("EntregaHerramientas"),
        ),
        (
            "ENTREGA TARJETA DE CONTROL DE ACCESO",
            datos.get("TarjetaControlAcceso"),
        ),
        (
            "ENTREGA DE GUANTES",
            datos.get("EntregaGuantes"),
        ),
        (
            "ENTREGA DE MONOGAFAS",
            datos.get("EntregaMonogafas"),
        ),
        (
            "ENTREGA DE PETO",
            datos.get("EntregaPeto"),
        ),
    ]

    contenido = [
        [
            _parrafo(
                "ENTREGA DE ELEMENTOS",
                estilos["seccion"],
            ),
            "",
        ]
    ]

    contenido.extend(
        [
            [
                _parrafo(
                    etiqueta,
                    estilos["etiqueta"],
                ),
                _parrafo(
                    valor,
                    estilos["valor"],
                    "SIN INFORMACIÓN",
                ),
            ]
            for etiqueta, valor in filas
        ]
    )

    observaciones = _texto(
        datos.get("ObservacionesEntrega"),
        "SIN OBSERVACIONES",
    )
    novedades = _texto(
        datos.get("NovedadesNomina"),
        "SIN NOVEDADES",
    )
    aplica_descuento = _texto(
        datos.get("AplicaDescuento"),
        "NO",
    )
    valor_descuento = _dinero(
        datos.get("ValorDescuento")
    )

    resumen = (
        f"<b>OBSERVACIONES:</b> "
        f"{_texto_html(observaciones)}"
        f"<br/><b>NOVEDADES DE NÓMINA:</b> "
        f"{_texto_html(novedades)}"
        f"<br/><b>APLICA DESCUENTO:</b> "
        f"{_texto_html(aplica_descuento)}"
    )

    if valor_descuento:
        resumen += (
            f"&nbsp;&nbsp;&nbsp;<b>VALOR:</b> "
            f"{_texto_html(valor_descuento)}"
        )

    contenido.append(
        [
            Paragraph(
                resumen,
                estilos["valor_izquierda"],
            ),
            "",
        ]
    )

    tabla = Table(
        contenido,
        colWidths=[
            8.25 * cm,
            8.25 * cm,
        ],
    )
    tabla.setStyle(
        TableStyle([
            ("SPAN", (0, 0), (1, 0)),
            ("SPAN", (0, -1), (1, -1)),
            ("GRID", (0, 0), (-1, -2), 1.0, colors.black),
            ("BOX", (0, -1), (1, -1), 1.0, colors.black),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("FONTNAME", (0, 1), (0, -1), "Helvetica-Bold"),
            ("FONTNAME", (1, 1), (1, -1), "Helvetica"),
            ("LEFTPADDING", (0, 0), (-1, -1), 4),
            ("RIGHTPADDING", (0, 0), (-1, -1), 4),
            ("TOPPADDING", (0, 0), (-1, -1), 4.0),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4.0),
        ])
    )
    return tabla


def _tabla_uniformes_alp_vacunas(
    datos,
    estilos,
):
    filas = [
        (
            "PENDIENTE ENTREGA DE UNIFORME",
            datos.get("PendienteEntregaUniforme"),
        ),
        (
            "UNIFORME PATÓGENO",
            datos.get("UniformePatogeno"),
        ),
        (
            "BOTAS",
            datos.get("Botas"),
        ),
        (
            "ZAPATOS",
            datos.get("Zapatos"),
        ),
        (
            "CHAQUETA",
            datos.get("Chaqueta"),
        ),
        (
            "CARNET ALP-ARL",
            datos.get("CarnetAlpArl"),
        ),
        (
            "PENDIENTE PAGO DE VACUNAS",
            datos.get("PendientePagoVacunas"),
        ),
        (
            "USUARIOS, CLAVES Y DISPOSITIVOS USADOS POR EL COLABORADOR",
            datos.get("UsuariosClavesDispositivos"),
        ),
    ]

    contenido = [
        [
            _parrafo(
                "UNIFORMES, ELEMENTOS ALP Y VACUNAS",
                estilos["seccion"],
            ),
            "",
        ]
    ]

    contenido.extend(
        [
            [
                _parrafo(
                    etiqueta,
                    estilos["etiqueta"],
                ),
                _parrafo(
                    valor,
                    (
                        estilos["valor_izquierda"]
                        if etiqueta.startswith("USUARIOS")
                        else estilos["valor"]
                    ),
                    (
                        "SIN INFORMACIÓN"
                        if etiqueta.startswith("USUARIOS")
                        else "NO"
                    ),
                ),
            ]
            for etiqueta, valor in filas
        ]
    )

    tabla = Table(
        contenido,
        colWidths=[
            9.2 * cm,
            7.3 * cm,
        ],
    )
    tabla.setStyle(
        TableStyle([
            ("SPAN", (0, 0), (1, 0)),
            ("GRID", (0, 0), (-1, -1), 1.0, colors.black),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("FONTNAME", (0, 1), (0, -1), "Helvetica-Bold"),
            ("FONTNAME", (1, 1), (1, -1), "Helvetica"),
            ("LEFTPADDING", (0, 0), (-1, -1), 4),
            ("RIGHTPADDING", (0, 0), (-1, -1), 4),
            ("TOPPADDING", (0, 0), (-1, -1), 4.6),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4.6),
        ])
    )
    return tabla


def _bloque_firma(
    datos,
    estilos,
):
    elaborado_por = _texto(
        datos.get("ElaboradoPor"),
        "SIN INFORMACIÓN",
    )

    return KeepTogether([
        Spacer(1, 1.35 * cm),
        Table(
            [
                [
                    "",
                    "",
                ],
                [
                    _parrafo(
                        "________________________________________",
                        estilos["valor_izquierda"],
                    ),
                    "",
                ],
                [
                    _parrafo(
                        "Persona que elabora",
                        estilos["firma"],
                    ),
                    "",
                ],
                [
                    _parrafo(
                        elaborado_por,
                        estilos["firma"],
                    ),
                    "",
                ],
            ],
            colWidths=[
                8.5 * cm,
                8.5 * cm,
            ],
            style=TableStyle([
                ("TOPPADDING", (0, 0), (-1, -1), 2.0),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 2.0),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 0),
            ]),
        ),
    ])


def _pie_pagina(
    canvas,
    documento,
):
    canvas.saveState()

    ancho_pagina, _ = letter
    margen_izquierdo = documento.leftMargin
    margen_derecho = ancho_pagina - documento.rightMargin
    centro = ancho_pagina / 2

    y = 0.78 * cm

    canvas.setStrokeColor(colors.black)
    canvas.setLineWidth(0.55)
    canvas.line(
        margen_izquierdo + 0.4 * cm,
        y + 0.88 * cm,
        margen_derecho - 0.4 * cm,
        y + 0.88 * cm,
    )

    linea_1a = (
        "TÉCNICOS EN LIMPIEZA DE: EMPRESAS, BANCOS, COLEGIOS, "
        "UNIVERSIDADES, CENTROS COMERCIALES, CENTRO DE RECREACIÓN,"
    )
    linea_1b = (
        "EDIFICIOS (OFICINAS Y VIVIENDA), HOSPITALES, SUPERMERCADOS, "
        "LAVADO Y PINTURA DE FACHADAS, LAVADO DE VIDRIOS, TAPETES Y CORTINAS."
    )

    canvas.setFont("Helvetica", 4.6)
    canvas.drawCentredString(
        centro,
        y + 0.66 * cm,
        linea_1a,
    )
    canvas.drawCentredString(
        centro,
        y + 0.49 * cm,
        linea_1b,
    )

    canvas.setFont("Helvetica", 6.8)
    canvas.drawCentredString(
        centro,
        y + 0.20 * cm,
        PIE_LINEA_2,
    )

    canvas.setFont("Helvetica", 5.8)
    canvas.drawCentredString(
        centro,
        y - 0.05 * cm,
        PIE_LINEA_3,
    )

    canvas.setFont("Helvetica", 5.8)
    canvas.drawCentredString(
        centro,
        y - 0.28 * cm,
        PIE_LINEA_4,
    )

    canvas.restoreState()


# ============================================================
# FUNCIÓN PRINCIPAL
# ============================================================

def generar_paz_salvo_operaciones_pdf(
    db: Session,
    id_paz_y_salvo: int,
) -> BytesIO:
    """
    Genera el PDF oficial del Paz y Salvo diligenciado por Operaciones.

    Este servicio únicamente construye y devuelve el PDF en memoria.
    No inserta registros en RetiroLaboralAdjunto y no modifica la base
    de datos. El router será responsable de guardar el archivo físico
    y registrar el adjunto tipo 2 cuando corresponda.
    """

    if not id_paz_y_salvo:
        raise HTTPException(
            status_code=400,
            detail="El IdPazYSalvo es obligatorio.",
        )

    datos = _obtener_datos_paz_salvo(
        db=db,
        id_paz_y_salvo=id_paz_y_salvo,
    )

    estilos = _crear_estilos()

    buffer = BytesIO()

    documento = SimpleDocTemplate(
        buffer,
        pagesize=letter,
        rightMargin=1.35 * cm,
        leftMargin=1.35 * cm,
        topMargin=0.7 * cm,
        bottomMargin=2.0 * cm,
        title=(
            "Paz y Salvo "
            f"{_texto(datos.get('NumeroIdentificacion'))}"
        ),
        author="Aseos La Perfección S.A.S.",
        subject="Paz y Salvo - Operaciones",
    )

    elementos = []

    elementos.extend(
        _crear_encabezado(estilos)
    )

    elementos.append(
        _tabla_datos_realizacion(
            datos,
            estilos,
        )
    )

    elementos.append(
        Spacer(1, 0.32 * cm)
    )

    elementos.append(
        _tabla_datos_colaborador(
            datos,
            estilos,
        )
    )

    elementos.append(
        Spacer(1, 0.32 * cm)
    )

    elementos.append(
        _tabla_datos_paz_salvo(
            datos,
            estilos,
        )
    )

    elementos.append(
        Spacer(1, 0.32 * cm)
    )

    elementos.append(
        _tabla_entrega_elementos(
            datos,
            estilos,
        )
    )

    # El formato oficial continúa en una segunda página.
    elementos.append(
        PageBreak()
    )

    elementos.extend(
        _crear_encabezado(
            estilos,
            solo_logos=True,
        )
    )

    elementos.append(
        _tabla_uniformes_alp_vacunas(
            datos,
            estilos,
        )
    )

    elementos.append(
        _bloque_firma(
            datos,
            estilos,
        )
    )

    try:
        documento.build(
            elementos,
            onFirstPage=_pie_pagina,
            onLaterPages=_pie_pagina,
        )
    except Exception as error:
        logger.exception(
            "Error generando Paz y Salvo IdPazYSalvo=%s",
            id_paz_y_salvo,
        )

        raise HTTPException(
            status_code=500,
            detail=(
                "No fue posible generar el PDF oficial "
                "del Paz y Salvo de Operaciones."
            ),
        ) from error

    buffer.seek(0)

    return buffer