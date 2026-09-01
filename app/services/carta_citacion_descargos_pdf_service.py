import logging
from datetime import date, datetime, timedelta, timezone
from io import BytesIO
from pathlib import Path
from typing import Any
from xml.sax.saxutils import escape

from PIL import Image as PILImage
from fastapi import HTTPException
from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY, TA_LEFT, TA_RIGHT
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen.canvas import Canvas
from reportlab.platypus import (
    Image,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)
from sqlalchemy import text
from sqlalchemy.orm import Session

from domain.models.aspirante import RegistroPersonal
from domain.models.citacion_proceso_disciplinario import (
    CitacionProcesoDisciplinario,
)
from domain.models.proceso_disciplinario import (
    ProcesoDisciplinario,
)


logger = logging.getLogger(__name__)


# ============================================================
# CONFIGURACIÓN GENERAL
# ============================================================

ZONA_HORARIA_COLOMBIA = timezone(
    timedelta(hours=-5)
)

BASE_DIR = Path(__file__).resolve().parents[1]

RUTA_LOGO_EMPRESA = (
    BASE_DIR
    / "assets"
    / "comunicaciones"
    / "LOGO_EMPRESA_NIT.png"
)

RUTA_FIRMA_YENY = (
    BASE_DIR
    / "assets"
    / "comunicaciones"
    / "FIRMA_YENY.png"
)

CIUDAD_CARTA = "Bogotá D.C."

NOMBRE_RESPONSABLE_RRLL = "Yeny Cuesto Díaz"

CARGO_RESPONSABLE_RRLL = (
    "Analista Gestión del Talento Humano"
)

NOMBRE_EMPRESA = "Aseos La Perfección S.A.S."


# ============================================================
# HELPERS
# ============================================================

def _texto(
    valor: Any,
    valor_vacio: str = "",
) -> str:
    if valor is None:
        return valor_vacio

    texto = str(valor).strip()

    if not texto:
        return valor_vacio

    return texto


def _texto_html(
    valor: Any,
    valor_vacio: str = "",
) -> str:
    return escape(
        _texto(
            valor,
            valor_vacio,
        )
    ).replace(
        "\n",
        "<br/>",
    )


def _fecha(
    valor: date | datetime | None,
) -> str:
    if not valor:
        return ""

    if isinstance(valor, datetime):
        return valor.strftime(
            "%d/%m/%Y"
        )

    if isinstance(valor, date):
        return valor.strftime(
            "%d/%m/%Y"
        )

    return str(valor).strip()


def _fecha_larga(
    valor: date | datetime | None,
) -> str:
    if not valor:
        return ""

    if isinstance(valor, datetime):
        valor = valor.date()

    if not isinstance(valor, date):
        return _texto(valor)

    meses = (
        "enero",
        "febrero",
        "marzo",
        "abril",
        "mayo",
        "junio",
        "julio",
        "agosto",
        "septiembre",
        "octubre",
        "noviembre",
        "diciembre",
    )

    return (
        f"{valor.day:02d} de "
        f"{meses[valor.month - 1]} de "
        f"{valor.year}"
    )


def _hora(
    valor: Any,
) -> str:
    if not valor:
        return ""

    if hasattr(
        valor,
        "strftime",
    ):
        try:
            texto = valor.strftime(
                "%I:%M %p"
            )

            return (
                texto
                .replace(
                    "AM",
                    "a. m.",
                )
                .replace(
                    "PM",
                    "p. m.",
                )
                .lstrip("0")
            )

        except ValueError:
            pass

    texto = str(valor).strip()

    for formato in (
        "%H:%M:%S",
        "%H:%M",
    ):
        try:
            hora_convertida = (
                datetime.strptime(
                    texto,
                    formato,
                )
            )

            resultado = (
                hora_convertida.strftime(
                    "%I:%M %p"
                )
            )

            return (
                resultado
                .replace(
                    "AM",
                    "a. m.",
                )
                .replace(
                    "PM",
                    "p. m.",
                )
                .lstrip("0")
            )

        except ValueError:
            continue

    return texto


def _obtener_datos_laborales_trabajador(
    db: Session,
    id_registro_personal: int,
) -> tuple[str, str]:
    """
    Obtiene el cargo y la sede/cliente más recientes del trabajador
    desde la misma asignación registrada en AsignacionCargoCliente.
    """

    fila = (
        db.execute(
            text(
                """
                SELECT
                    cg."NombreCargo" AS "Cargo",
                    cl."Nombre" AS "Sede"
                FROM public."RegistroPersonal" rp

                LEFT JOIN LATERAL (
                    SELECT
                        acc."IdCargo",
                        acc."IdCliente"
                    FROM public."AsignacionCargoCliente" acc
                    WHERE
                        acc."IdRegistroPersonal"
                        = rp."IdRegistroPersonal"
                    ORDER BY
                        COALESCE(
                            acc."FechaActualizacion",
                            acc."FechaCreacion"
                        ) DESC NULLS LAST,
                        acc."IdAsignacionCargoCliente" DESC
                    LIMIT 1
                ) asignacion ON TRUE

                LEFT JOIN public."Cargo" cg
                    ON cg."IdCargo"
                    = asignacion."IdCargo"

                LEFT JOIN public."Cliente" cl
                    ON cl."IdCliente"
                    = asignacion."IdCliente"

                WHERE
                    rp."IdRegistroPersonal"
                    = :id_registro_personal

                LIMIT 1
                """
            ),
            {
                "id_registro_personal":
                    id_registro_personal
            },
        )
        .mappings()
        .first()
    )

    if not fila:
        return "", ""

    cargo = str(
        fila.get("Cargo") or ""
    ).strip()

    sede = str(
        fila.get("Sede") or ""
    ).strip()

    return cargo, sede


def _formatear_motivo(
    valor: Any,
) -> str:
    codigo = str(
        valor or ""
    ).strip()

    motivos = {
        "ACCIDENTE_LABORAL_SST":
            "Accidente laboral (SST)",

        "ACTOS_INSEGUROS_SST":
            "Actos inseguros (SST)",

        "ATENCION_LINEA_VERDE":
            "Atención línea verde",

        "AUSENCIA_INJUSTIFICADA":
            "Ausencia injustificada",

        "CLIMA_LABORAL":
            "Clima laboral",

        "DANOS_BIEN_AJENO_AFECTACION_CLIENTE":
            (
                "Daños en bien ajeno - "
                "afectación al cliente"
            ),

        "INCUMPLIMIENTO_FUNCIONES":
            "Incumplimiento de funciones",

        "INCUMPLIMIENTO_NORMAS":
            "Incumplimiento de normas",

        "NO_USAR_EPP_LABOR":
            "No usar EPP para la labor",

        "OMISION_REPORTE_CONFLICTO_INTERES":
            (
                "Omisión reporte "
                "conflicto de interés"
            ),

        "PERDIDA_OBJETOS_CLIENTE_COMPANEROS":
            (
                "Pérdida de objetos "
                "cliente / compañeros"
            ),

        "PERIODO_PRUEBA":
            "Período de prueba",

        "RETARDOS_INJUSTIFICADOS":
            "Retardos injustificados",
    }

    if codigo in motivos:
        return motivos[codigo]

    return (
        codigo
        .replace(
            "_",
            " ",
        )
        .strip()
    )


def _obtener_relato_valido(
    citacion: CitacionProcesoDisciplinario,
) -> str:
    """
    Obtiene el relato registrado por Operaciones.

    Se respeta exactamente el contenido diligenciado, incluso si se trata
    de un valor usado únicamente para pruebas. Si RelatoHechos está vacío,
    se intenta utilizar ObservacionOperaciones como respaldo.
    """

    candidatos = (
        getattr(citacion, "RelatoHechos", None),
        getattr(citacion, "ObservacionOperaciones", None),
    )

    for candidato in candidatos:
        relato = _texto(candidato)

        if relato:
            return relato

    raise HTTPException(
        status_code=422,
        detail={
            "mensaje": (
                "La citación no tiene un relato de hechos registrado. "
                "Revise el campo RelatoHechos antes de generar la carta."
            ),
            "campo": "RelatoHechos",
        },
    )


# ============================================================
# ENCABEZADO
# ============================================================

def _imagen_disponible(
    ruta: Path,
) -> bool:
    return ruta.is_file()


def _logo_empresa_sin_fondo() -> BytesIO | None:
    """
    Convierte LOGO_EMPRESA.jpeg a PNG en memoria y hace transparente
    el fondo claro/gris para que se integre naturalmente al documento.

    El archivo original no se modifica.
    """

    if not _imagen_disponible(
        RUTA_LOGO_EMPRESA
    ):
        return None

    try:
        imagen = (
            PILImage.open(
                RUTA_LOGO_EMPRESA
            )
            .convert("RGBA")
        )

        pixeles = []

        for rojo, verde, azul, alfa in imagen.getdata():
            # El fondo original es blanco/gris muy claro.
            # Se vuelve transparente sin afectar el logo.
            if (
                rojo >= 220
                and verde >= 220
                and azul >= 220
            ):
                pixeles.append(
                    (255, 255, 255, 0)
                )
            else:
                pixeles.append(
                    (rojo, verde, azul, alfa)
                )

        imagen.putdata(
            pixeles
        )

        buffer = BytesIO()

        imagen.save(
            buffer,
            format="PNG",
        )

        buffer.seek(0)

        return buffer

    except (
        OSError,
        TypeError,
        ValueError,
    ) as error:
        logger.warning(
            "No se pudo preparar el logo de Aseos La Perfección "
            "con fondo transparente: %s",
            error,
        )

        return None


def _dibujar_encabezado(
    canvas: Canvas,
    documento: SimpleDocTemplate,
) -> None:
    """
    Encabezado y pie del nuevo formato oficial de apertura
    de procedimiento disciplinario.

    Solo utiliza el logo de Aseos La Perfección con NIT.
    """

    canvas.saveState()

    ancho_pagina, alto_pagina = letter
    margen_izquierdo = documento.leftMargin

    if _imagen_disponible(
        RUTA_LOGO_EMPRESA
    ):
        try:
            canvas.drawImage(
                ImageReader(
                    str(RUTA_LOGO_EMPRESA)
                ),
                margen_izquierdo,
                alto_pagina - 2.65 * cm,
                width=4.65 * cm,
                height=1.75 * cm,
                preserveAspectRatio=True,
                mask="auto",
                anchor="sw",
            )
        except (
            OSError,
            TypeError,
            ValueError,
        ) as error:
            logger.warning(
                "No se pudo cargar el logo de "
                "Aseos La Perfección con NIT: %s",
                error,
            )
    else:
        logger.warning(
            "No se encontró LOGO_EMPRESA_NIT.png."
        )

    centro_x = ancho_pagina / 2

    canvas.setFillColor("#111111")
    canvas.setFont(
        "Helvetica",
        4.4,
    )

    canvas.drawCentredString(
        centro_x,
        1.43 * cm,
        (
            "TECNICOS EN LIMPIEZA DE: EMPRESAS, BANCOS, COLEGIOS, "
            "UNIVERSIDADES, CENTROS COMERCIALES, CENTRO DE RECREACION,"
        ),
    )

    canvas.drawCentredString(
        centro_x,
        1.27 * cm,
        (
            "EDIFICIOS (OFICINAS Y VIVIENDA), HOSPITALES, SUPERMERCADOS, "
            "LAVADO Y PINTURA DE FACHADAS, LAVADO DE VIDRIOS, TAPETES Y CORTINAS."
        ),
    )

    canvas.setStrokeColor("#111111")
    canvas.setLineWidth(0.35)
    canvas.line(
        margen_izquierdo,
        1.14 * cm,
        ancho_pagina - documento.rightMargin,
        1.14 * cm,
    )

    canvas.setFillColor("#4B5563")
    canvas.setFont(
        "Helvetica",
        6.1,
    )
    canvas.drawCentredString(
        centro_x,
        0.88 * cm,
        (
            "Calle 4 Bis No. 53C-50 Bogotá, D.C. - Colombia "
            "- PBX: 4204893"
        ),
    )

    canvas.setFillColor("#2A6EBB")
    canvas.setFont(
        "Helvetica",
        5.7,
    )
    canvas.drawCentredString(
        centro_x,
        0.62 * cm,
        (
            "dcomercial@aseoslaperfeccion.com - "
            "comercial2@aseoslaperfeccion.com"
        ),
    )
    canvas.drawCentredString(
        centro_x,
        0.39 * cm,
        "www.aseoslaperfeccion.com",
    )

    canvas.restoreState()

def _crear_bloque_firma(
    estilos,
):
    """
    Crea el bloque de firma de Yeny.

    Usa FIRMA_YENY.png cuando está disponible y conserva
    un respaldo textual si el archivo no puede cargarse.
    """

    elementos = []

    if _imagen_disponible(
        RUTA_FIRMA_YENY
    ):
        try:
            firma = Image(
                str(RUTA_FIRMA_YENY),
                width=6.6 * cm,
                height=2.65 * cm,
            )
            firma.hAlign = "LEFT"
            elementos.append(firma)
            elementos.append(
                Spacer(
                    1,
                    0.03 * cm,
                )
            )
        except (
            OSError,
            TypeError,
            ValueError,
        ) as error:
            logger.warning(
                "No se pudo cargar la firma de Yeny: %s",
                error,
            )

    elementos.append(
        Paragraph(
            (
                f"<b>{escape(NOMBRE_RESPONSABLE_RRLL)}</b><br/>"
                f"{escape(CARGO_RESPONSABLE_RRLL)}<br/>"
                f"<b>{escape(NOMBRE_EMPRESA)}</b>"
            ),
            estilos[
                "CartaFirma"
            ],
        )
    )

    return elementos


# ============================================================
# ESTILOS
# ============================================================

def _crear_estilos():
    estilos = getSampleStyleSheet()

    estilos.add(
        ParagraphStyle(
            name="CartaTitulo",
            parent=estilos["Normal"],
            fontName="Helvetica-Bold",
            fontSize=10.5,
            leading=12.5,
            alignment=TA_CENTER,
            textColor="#111111",
            spaceAfter=4,
        )
    )

    estilos.add(
        ParagraphStyle(
            name="CartaTexto",
            parent=estilos["Normal"],
            fontName="Helvetica",
            fontSize=9.2,
            leading=12,
            alignment=TA_JUSTIFY,
            textColor="#111111",
            spaceAfter=8,
        )
    )

    estilos.add(
        ParagraphStyle(
            name="CartaTextoIzquierda",
            parent=estilos["Normal"],
            fontName="Helvetica",
            fontSize=9.2,
            leading=11.2,
            alignment=TA_LEFT,
            textColor="#111111",
        )
    )

    estilos.add(
        ParagraphStyle(
            name="CartaDatosTrabajador",
            parent=estilos["Normal"],
            fontName="Helvetica-Bold",
            fontSize=9.2,
            leading=11.2,
            alignment=TA_LEFT,
            textColor="#111111",
        )
    )

    estilos.add(
        ParagraphStyle(
            name="CartaSeccion",
            parent=estilos["Normal"],
            fontName="Helvetica-Bold",
            fontSize=9.5,
            leading=12,
            alignment=TA_LEFT,
            textColor="#111111",
            leftIndent=0.35 * cm,
            spaceAfter=8,
        )
    )

    estilos.add(
        ParagraphStyle(
            name="CartaSupervisor",
            parent=estilos["Normal"],
            fontName="Helvetica-Bold",
            fontSize=9.2,
            leading=11,
            alignment=TA_LEFT,
            textColor="#111111",
        )
    )

    estilos.add(
        ParagraphStyle(
            name="CartaNotificacionElectronica",
            parent=estilos["Normal"],
            fontName="Helvetica",
            fontSize=8.2,
            leading=10,
            alignment=TA_RIGHT,
            textColor="#444444",
        )
    )

    estilos.add(
        ParagraphStyle(
            name="CartaAsuntoEtiqueta",
            parent=estilos["Normal"],
            fontName="Helvetica-Bold",
            fontSize=9.2,
            leading=11.2,
            alignment=TA_LEFT,
            textColor="#111111",
        )
    )

    estilos.add(
        ParagraphStyle(
            name="CartaAsuntoTexto",
            parent=estilos["Normal"],
            fontName="Helvetica-Bold",
            fontSize=9.2,
            leading=11.6,
            alignment=TA_LEFT,
            textColor="#111111",
        )
    )

    return estilos


# ============================================================
# GENERADOR PRINCIPAL
# ============================================================

def generar_carta_citacion_descargos_pdf(
    db: Session,
    id_proceso: int,
) -> BytesIO:
    proceso = (
        db.query(ProcesoDisciplinario)
        .filter(
            ProcesoDisciplinario.IdProcesoDisciplinario
            == id_proceso
        )
        .first()
    )

    if not proceso:
        raise HTTPException(
            status_code=404,
            detail={
                "mensaje": "Proceso disciplinario no encontrado.",
                "IdProcesoDisciplinario": id_proceso,
            },
        )

    trabajador = (
        db.query(RegistroPersonal)
        .filter(
            RegistroPersonal.IdRegistroPersonal
            == proceso.IdRegistroPersonal
        )
        .first()
    )

    if not trabajador:
        raise HTTPException(
            status_code=404,
            detail={
                "mensaje": (
                    "No se encontró el trabajador "
                    "asociado al proceso."
                ),
                "IdRegistroPersonal":
                    proceso.IdRegistroPersonal,
            },
        )

    citacion = (
        db.query(CitacionProcesoDisciplinario)
        .filter(
            CitacionProcesoDisciplinario.IdProcesoDisciplinario
            == id_proceso
        )
        .order_by(
            CitacionProcesoDisciplinario
            .IdCitacionProcesoDisciplinario.desc()
        )
        .first()
    )

    if not citacion:
        raise HTTPException(
            status_code=404,
            detail={
                "mensaje": (
                    "El proceso disciplinario "
                    "no tiene una citación registrada."
                ),
                "IdProcesoDisciplinario": id_proceso,
            },
        )

    modalidad = _texto(
        getattr(
            citacion,
            "Modalidad",
            None,
        )
    ).upper()

    if modalidad not in {
        "PRESENCIAL",
        "VIRTUAL",
    }:
        raise HTTPException(
            status_code=409,
            detail={
                "mensaje": (
                    "La carta solo puede generarse para "
                    "citaciones presenciales o virtuales."
                ),
                "Modalidad":
                    getattr(citacion, "Modalidad", None),
            },
        )

    nombre_completo = " ".join(
        parte
        for parte in (
            _texto(
                getattr(
                    trabajador,
                    "Nombres",
                    None,
                )
            ),
            _texto(
                getattr(
                    trabajador,
                    "Apellidos",
                    None,
                )
            ),
        )
        if parte
    ).strip()

    numero_identificacion = _texto(
        getattr(
            trabajador,
            "NumeroIdentificacion",
            None,
        )
    )

    correo_trabajador = _texto(
        getattr(
            trabajador,
            "Email",
            None,
        )
    )

    cargo, sede_asignacion = (
        _obtener_datos_laborales_trabajador(
            db=db,
            id_registro_personal=(
                trabajador.IdRegistroPersonal
            ),
        )
    )

    sede_citacion = _texto(
        getattr(
            citacion,
            "Sede",
            None,
        )
    )

    sede = (
        sede_asignacion
        or sede_citacion
    )

    lugar = _texto(
        getattr(
            citacion,
            "LugarCitacion",
            None,
        )
    )

    supervisor = _texto(
        getattr(
            citacion,
            "SupervisorReporta",
            None,
        )
    )

    cargo_supervisor = _texto(
        getattr(
            citacion,
            "CargoSupervisorReporta",
            None,
        )
    )

    relato = _obtener_relato_valido(
        citacion=citacion,
    )

    enunciacion_pruebas = _texto(
        getattr(
            citacion,
            "EnunciacionPruebas",
            None,
        )
    )

    fecha_citacion = _fecha(
        getattr(
            citacion,
            "FechaCitacion",
            None,
        )
    )

    hora_citacion = _hora(
        getattr(
            citacion,
            "HoraCitacion",
            None,
        )
    )

    fecha_hora_generacion = datetime.now(
        ZONA_HORARIA_COLOMBIA
    )

    fecha_generacion = (
        fecha_hora_generacion.strftime(
            "%d/%m/%Y"
        )
    )

    fecha_generacion_larga = _fecha_larga(
        fecha_hora_generacion
    )

    hora_generacion = _hora(
        fecha_hora_generacion
    )

    if modalidad == "PRESENCIAL":
        lugar_medio = (
            lugar
            or sede
            or "Presencial"
        )
    else:
        lugar_medio = "Virtual"

    estilos = _crear_estilos()
    buffer = BytesIO()

    documento_pdf = SimpleDocTemplate(
        buffer,
        pagesize=letter,
        leftMargin=2.05 * cm,
        rightMargin=2.05 * cm,
        topMargin=3.35 * cm,
        bottomMargin=1.75 * cm,
        title=(
            "Comunicación formal de apertura de "
            "procedimiento disciplinario laboral y "
            "citación a diligencia de descargos"
        ),
        author=NOMBRE_EMPRESA,
        subject=(
            "Apertura de procedimiento disciplinario "
            "y citación a diligencia de descargos"
        ),
    )

    contenido = []

    contenido.append(
        Paragraph(
            (
                "COMUNICACIÓN FORMAL DE APERTURA DE "
                "PROCEDIMIENTO DISCIPLINARIO<br/>"
                "LABORAL Y CITACIÓN A DILIGENCIA DE DESCARGOS"
            ),
            estilos["CartaTitulo"],
        )
    )

    contenido.append(Spacer(1, 0.68 * cm))

    contenido.append(
        Paragraph(
            (
                "Bogotá, "
                f"{escape(fecha_generacion_larga)}."
            ),
            estilos["CartaTextoIzquierda"],
        )
    )

    contenido.append(Spacer(1, 0.42 * cm))

    contenido.append(
        Paragraph(
            "Señor(a)",
            estilos["CartaDatosTrabajador"],
        )
    )

    contenido.append(
        Paragraph(
            escape(nombre_completo.upper()),
            estilos["CartaDatosTrabajador"],
        )
    )

    contenido.append(
        Paragraph(
            (
                "<b>DOC. DE ID Nº:</b> "
                f"{escape(numero_identificacion)}"
            ),
            estilos["CartaTextoIzquierda"],
        )
    )

    contenido.append(
        Paragraph(
            (
                "<b>Cargo:</b> "
                f"{escape(cargo)}"
            ),
            estilos["CartaTextoIzquierda"],
        )
    )

    contenido.append(
        Paragraph(
            (
                "<b>Sede o lugar de trabajo:</b> "
                f"{escape(sede or lugar)}"
            ),
            estilos["CartaTextoIzquierda"],
        )
    )

    contenido.append(
        Paragraph(
            (
                "<b>Email:</b> "
                f"{escape(correo_trabajador or 'No registrado')}"
            ),
            estilos["CartaTextoIzquierda"],
        )
    )

    contenido.append(Spacer(1, 0.78 * cm))

    tabla_asunto = Table(
        [
            [
                Paragraph(
                    "Asunto:",
                    estilos["CartaAsuntoEtiqueta"],
                ),
                Paragraph(
                    (
                        "COMUNICACIÓN FORMAL DE APERTURA DE PROCESO "
                        "DISCIPLINARIO<br/>"
                        "Y CITACIÓN A DILIGENCIA DE DESCARGOS "
                        "(LEY 2466 DE 2025)."
                    ),
                    estilos["CartaAsuntoTexto"],
                ),
            ]
        ],
        colWidths=[1.85 * cm, 13.15 * cm],
        hAlign="LEFT",
    )

    tabla_asunto.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                ("TOPPADDING", (0, 0), (-1, -1), 0),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
            ]
        )
    )

    contenido.append(tabla_asunto)

    contenido.append(Spacer(1, 0.58 * cm))

    contenido.append(
        Paragraph(
            "Estimado(a) colaborador(a),",
            estilos["CartaTextoIzquierda"],
        )
    )

    contenido.append(Spacer(1, 0.22 * cm))

    contenido.append(
        Paragraph(
            (
                "En nombre de <b>ASEOS LA PERFECCIÓN S.A.S.</b>, "
                "le comunicamos formalmente la apertura de un "
                "procedimiento disciplinario laboral, con fundamento "
                "en los hechos, conductas u omisiones que se describen "
                "en la presente comunicación."
            ),
            estilos["CartaTexto"],
        )
    )

    contenido.append(
        Paragraph(
            (
                "La apertura de este procedimiento no implica que se "
                "haya establecido previamente su responsabilidad ni "
                "constituye una sanción anticipada. Su finalidad es "
                "esclarecer los hechos y garantizarle la oportunidad "
                "de ejercer plenamente sus derechos de defensa y "
                "contradicción."
            ),
            estilos["CartaTexto"],
        )
    )

    contenido.append(
        Paragraph(
            (
                "Esta actuación se adelantará con observancia de los "
                "principios de dignidad, presunción de inocencia, "
                "debido proceso, proporcionalidad, derecho de defensa, "
                "contradicción y controversia de las pruebas, "
                "intimidad, lealtad y buena fe, imparcialidad, respeto "
                "al buen nombre y a la honra, de conformidad con el "
                "artículo 115 del Código Sustantivo del Trabajo, "
                "modificado por el artículo 7 de la Ley 2466 de 2025."
            ),
            estilos["CartaTexto"],
        )
    )

    contenido.append(
        Paragraph(
            (
                "1.&nbsp;&nbsp;&nbsp;HECHOS, CONDUCTAS U OMISIONES "
                "OBJETO DE INVESTIGACIÓN"
            ),
            estilos["CartaSeccion"],
        )
    )

    contenido.append(
        Paragraph(
            (
                "Dando cumplimiento al numeral 2º de la citada ley, "
                "se le comunica por escrito que los hechos que motivan "
                "la apertura del presente procedimiento disciplinario "
                "son los siguientes:"
            ),
            estilos["CartaTexto"],
        )
    )

    contenido.append(
        Paragraph(
            f"<b>{_texto_html(relato)}</b>",
            estilos["CartaTextoIzquierda"],
        )
    )

    contenido.append(Spacer(1, 0.28 * cm))

    contenido.append(
        Paragraph(
            (
                "Los hechos anteriormente descritos tienen carácter "
                "presunto y serán objeto de verificación y valoración "
                "dentro del procedimiento disciplinario."
            ),
            estilos["CartaTexto"],
        )
    )

    contenido.append(PageBreak())

    contenido.append(
        Paragraph(
            "2.&nbsp;&nbsp;&nbsp;TRASLADO DE PRUEBAS",
            estilos["CartaSeccion"],
        )
    )

    contenido.append(
        Paragraph(
            (
                "En cumplimiento del numeral 3º del artículo 115 del "
                "C.S.T., se le hace entrega formal y traslado de todas "
                "y cada una de las pruebas que fundamentan los hechos "
                "descritos:"
            ),
            estilos["CartaTexto"],
        )
    )

    contenido.append(
        Paragraph(
            (
                f"<b>{_texto_html(enunciacion_pruebas or 'Sin enunciación de pruebas registrada.')}</b>"
            ),
            estilos["CartaTextoIzquierda"],
        )
    )

    contenido.append(Spacer(1, 0.45 * cm))

    contenido.append(
        Paragraph(
            (
                "3.&nbsp;&nbsp;&nbsp;TÉRMINO PARA LA DEFENSA Y "
                "CITACIÓN A DILIGENCIA"
            ),
            estilos["CartaSeccion"],
        )
    )

    contenido.append(
        Paragraph(
            (
                "Según el numeral 4º de la norma vigente, usted cuenta "
                "con un término de cinco (5) días hábiles contados a "
                "partir del recibo de esta citación para que pueda "
                "manifestarse frente a los motivos del proceso, "
                "controvertir las pruebas, allegar las que considere "
                "necesarias para su defensa que tiendan a justificar, "
                "atenuar, o demostrar su no participación en los hechos, "
                "y solicitar, de manera concreta y justificada, la "
                "práctica de pruebas relacionadas con los hechos "
                "investigados."
            ),
            estilos["CartaTexto"],
        )
    )

    contenido.append(
        Paragraph(
            (
                "Sin perjuicio del término anteriormente indicado, se "
                "le cita a diligencia de descargos con el fin de que "
                "pueda rendir verbalmente su versión sobre los hechos "
                "objeto de investigación, presentar las explicaciones "
                "que considere pertinentes, controvertir las pruebas "
                "trasladadas y aportar o solicitar aquellas que estime "
                "necesarias para el ejercicio de su derecho de defensa."
            ),
            estilos["CartaTexto"],
        )
    )

    contenido.append(
        Paragraph(
            (
                "La diligencia de descargos de forma verbal se llevará "
                "a cabo:"
            ),
            estilos["CartaTextoIzquierda"],
        )
    )

    contenido.append(Spacer(1, 0.15 * cm))

    contenido.append(
        Paragraph(
            (
                "•&nbsp;&nbsp;<b>Fecha:</b> "
                f"{escape(fecha_citacion)}<br/>"
                "•&nbsp;&nbsp;<b>Hora:</b> "
                f"{escape(hora_citacion)}<br/>"
                "•&nbsp;&nbsp;<b>Lugar / Medio:</b> "
                f"{escape(lugar_medio)}"
            ),
            estilos["CartaTextoIzquierda"],
        )
    )

    contenido.append(Spacer(1, 0.28 * cm))

    contenido.append(
        Paragraph(
            (
                "En la referida diligencia podrá aportar las pruebas "
                "con las que ya cuente o si aún le quedan días de los "
                "5 que la ley le concede podrá manifestar su intención "
                "de que utilizará el tiempo restante para aportar más "
                "pruebas que permita exonerarla de responsabilidad."
            ),
            estilos["CartaTexto"],
        )
    )

    contenido.append(
        Paragraph(
            (
                "Si lo desea, podrá asistir a la diligencia en compañía "
                "de uno (1) o dos (2) compañeros de trabajo."
            ),
            estilos["CartaTexto"],
        )
    )

    contenido.append(Spacer(1, 0.25 * cm))

    contenido.append(
        Paragraph(
            "Atentamente,",
            estilos["CartaTextoIzquierda"],
        )
    )

    contenido.append(Spacer(1, 0.50 * cm))

    contenido.append(
        Paragraph(
            escape(
                supervisor.upper()
                if supervisor
                else "SUPERVISOR(A) NO REGISTRADO(A)"
            ),
            estilos["CartaSupervisor"],
        )
    )

    contenido.append(
        Paragraph(
            escape(
                cargo_supervisor
                if cargo_supervisor
                else "Cargo no registrado"
            ),
            estilos["CartaSupervisor"],
        )
    )

    contenido.append(Spacer(1, 0.55 * cm))

    contenido.append(
        Paragraph(
            (
                "<b>Notificación electrónica</b><br/>"
                f"{escape(correo_trabajador or 'Correo no registrado')}<br/>"
                f"{escape(fecha_generacion)} - "
                f"{escape(hora_generacion)}"
            ),
            estilos["CartaNotificacionElectronica"],
        )
    )

    documento_pdf.build(
        contenido,
        onFirstPage=_dibujar_encabezado,
        onLaterPages=_dibujar_encabezado,
    )

    buffer.seek(0)

    return buffer
