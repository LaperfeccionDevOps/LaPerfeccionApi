import logging
from datetime import date, datetime, timedelta, timezone
from io import BytesIO
from pathlib import Path
from typing import Any
from xml.sax.saxutils import escape

from PIL import Image as PILImage
from fastapi import HTTPException
from reportlab.lib.enums import TA_JUSTIFY, TA_LEFT, TA_RIGHT
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen.canvas import Canvas
from reportlab.platypus import (
    Image,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
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


def _obtener_cargo_trabajador(
    db: Session,
    id_registro_personal: int,
) -> str:
    """
    Obtiene el cargo más reciente del trabajador desde
    AsignacionCargoCliente y Cargo.
    """

    fila = (
        db.execute(
            text(
                """
                SELECT
                    cg."NombreCargo" AS "Cargo"
                FROM public."RegistroPersonal" rp

                LEFT JOIN LATERAL (
                    SELECT
                        acc."IdCargo"
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
        return ""

    return str(
        fila.get("Cargo") or ""
    ).strip()


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
    Dibuja el encabezado oficial de la carta con:
    - logo de Aseos La Perfección sin fondo visible,
    - logo ISSA,
    - certificaciones ICONTEC / IQNET.

    No se incluye Mantener Ingeniería.
    """

    canvas.saveState()

    _, alto_pagina = letter
    margen_izquierdo = documento.leftMargin

    y_base = alto_pagina - 2.75 * cm

    # ========================================================
    # LOGO ASEOS LA PERFECCIÓN
    # ========================================================

    logo_empresa_memoria = (
        _logo_empresa_sin_fondo()
    )

    if logo_empresa_memoria is not None:
        try:
            canvas.drawImage(
                ImageReader(
                    logo_empresa_memoria
                ),
                margen_izquierdo,
                y_base,
                width=5.45 * cm,
                height=1.95 * cm,
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
                "No se pudo cargar el logo de Aseos La Perfección: %s",
                error,
            )
    else:
        logger.warning(
            "No se encontró o no se pudo preparar "
            "LOGO_EMPRESA.jpeg."
        )

    # ========================================================
    # LOGO ISSA
    # ========================================================

    if _imagen_disponible(
        RUTA_LOGO_ISSA
    ):
        try:
            canvas.drawImage(
                ImageReader(
                    str(RUTA_LOGO_ISSA)
                ),
                margen_izquierdo + 6.00 * cm,
                y_base + 0.12 * cm,
                width=1.85 * cm,
                height=1.55 * cm,
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
                "No se pudo cargar el logo ISSA: %s",
                error,
            )

    # ========================================================
    # LOGOS ICONTEC / IQNET
    # ========================================================

    if _imagen_disponible(
        RUTA_LOGO_CERTIFICACIONES
    ):
        try:
            canvas.drawImage(
                ImageReader(
                    str(
                        RUTA_LOGO_CERTIFICACIONES
                    )
                ),
                margen_izquierdo + 8.10 * cm,
                y_base - 0.02 * cm,
                width=3.25 * cm,
                height=1.95 * cm,
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
                "No se pudieron cargar los logos de certificaciones: %s",
                error,
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
            name="CartaTexto",
            parent=estilos["Normal"],
            fontName="Helvetica",
            fontSize=9.5,
            leading=13,
            alignment=TA_JUSTIFY,
            textColor="#111111",
            spaceAfter=10,
        )
    )

    estilos.add(
        ParagraphStyle(
            name="CartaTextoIzquierda",
            parent=estilos["Normal"],
            fontName="Helvetica",
            fontSize=9.5,
            leading=12,
            alignment=TA_LEFT,
            textColor="#111111",
        )
    )

    estilos.add(
        ParagraphStyle(
            name="CartaDatosTrabajador",
            parent=estilos["Normal"],
            fontName="Helvetica-Bold",
            fontSize=9.5,
            leading=11,
            alignment=TA_LEFT,
            textColor="#111111",
        )
    )

    estilos.add(
        ParagraphStyle(
            name="CartaReferencia",
            parent=estilos["Normal"],
            fontName="Helvetica-BoldOblique",
            fontSize=9.5,
            leading=12,
            alignment=TA_LEFT,
            textColor="#111111",
            leftIndent=4.2 * cm,
            spaceAfter=12,
        )
    )

    estilos.add(
        ParagraphStyle(
            name="CartaFirma",
            parent=estilos["Normal"],
            fontName="Helvetica-Bold",
            fontSize=9,
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
            fontSize=8.5,
            leading=10.5,
            alignment=TA_RIGHT,
            textColor="#444444",
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
    """
    Genera la carta oficial de citación a diligencia
    de descargos para citaciones presenciales o virtuales.
    """

    proceso = (
        db.query(
            ProcesoDisciplinario
        )
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
                    "Proceso disciplinario "
                    "no encontrado."
                ),
                "IdProcesoDisciplinario":
                    id_proceso,
            },
        )

    trabajador = (
        db.query(
            RegistroPersonal
        )
        .filter(
            RegistroPersonal
            .IdRegistroPersonal
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
        db.query(
            CitacionProcesoDisciplinario
        )
        .filter(
            CitacionProcesoDisciplinario
            .IdProcesoDisciplinario
            == id_proceso
        )
        .order_by(
            CitacionProcesoDisciplinario
            .IdCitacionProcesoDisciplinario
            .desc()
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
                "IdProcesoDisciplinario":
                    id_proceso,
            },
        )

    modalidad = str(
        citacion.Modalidad or ""
    ).strip().upper()

    modalidades_permitidas = {
        "PRESENCIAL",
        "VIRTUAL",
    }

    if modalidad not in modalidades_permitidas:
        raise HTTPException(
            status_code=409,
            detail={
                "mensaje": (
                    "La carta solo puede generarse para "
                    "citaciones presenciales o virtuales."
                ),
                "Modalidad":
                    citacion.Modalidad,
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

    cargo = _obtener_cargo_trabajador(
        db=db,
        id_registro_personal=(
            trabajador.IdRegistroPersonal
        ),
    )

    cliente = _texto(
        citacion.Cliente
    )

    sede = _texto(
        citacion.Sede
    )

    supervisor = _texto(
        citacion.SupervisorReporta
    )

    motivo = _formatear_motivo(
        citacion.MotivoCitacion
    )

    relato = _obtener_relato_valido(
        citacion=citacion,
    )

    lugar = _texto(
        citacion.LugarCitacion
    )

    fecha_citacion = _fecha(
        citacion.FechaCitacion
    )

    hora_citacion = _hora(
        citacion.HoraCitacion
    )

    fecha_hora_generacion = datetime.now(
        ZONA_HORARIA_COLOMBIA
    )

    fecha_generacion = (
        fecha_hora_generacion.strftime(
            "%d/%m/%Y"
        )
    )

    hora_generacion = _hora(
        fecha_hora_generacion
    )

    if modalidad == "PRESENCIAL" and not lugar:
        raise HTTPException(
            status_code=422,
            detail={
                "mensaje": (
                    "La citación presencial no tiene "
                    "lugar definido."
                ),
                "campo": "LugarCitacion",
                "Modalidad": modalidad,
            },
        )

    estilos = _crear_estilos()

    buffer = BytesIO()

    documento_pdf = SimpleDocTemplate(
        buffer,
        pagesize=letter,
        leftMargin=2.05 * cm,
        rightMargin=2.05 * cm,
        topMargin=3.85 * cm,
        bottomMargin=1.5 * cm,
        title=(
            "Citación a diligencia "
            "de descargos"
        ),
        author=NOMBRE_EMPRESA,
        subject=(
            "Citación a diligencia "
            "de descargos"
        ),
    )

    contenido = []

    # ========================================================
    # FECHA
    # ========================================================

    contenido.append(
        Paragraph(
            (
                f"{escape(CIUDAD_CARTA)}, "
                f"<b>{fecha_generacion}</b>"
            ),
            estilos[
                "CartaTextoIzquierda"
            ],
        )
    )

    contenido.append(
        Spacer(
            1,
            0.55 * cm,
        )
    )

    # ========================================================
    # DATOS DEL TRABAJADOR
    # ========================================================

    contenido.append(
        Paragraph(
            "Señor(a)",
            estilos[
                "CartaTextoIzquierda"
            ],
        )
    )

    contenido.append(
        Paragraph(
            escape(
                nombre_completo.upper()
            ),
            estilos[
                "CartaDatosTrabajador"
            ],
        )
    )

    contenido.append(
        Paragraph(
            (
                "CC "
                f"{escape(numero_identificacion)}"
            ),
            estilos[
                "CartaDatosTrabajador"
            ],
        )
    )

    contenido.append(
        Paragraph(
            escape(
                cargo.lower()
                if cargo
                else ""
            ),
            estilos[
                "CartaDatosTrabajador"
            ],
        )
    )

    cliente_encabezado = (
        cliente
        if cliente
        else sede
    )

    contenido.append(
        Paragraph(
            escape(
                cliente_encabezado.lower()
            ),
            estilos[
                "CartaDatosTrabajador"
            ],
        )
    )

    contenido.append(
        Paragraph(
            "Bogotá",
            estilos[
                "CartaTextoIzquierda"
            ],
        )
    )

    contenido.append(
        Spacer(
            1,
            0.35 * cm,
        )
    )

    # ========================================================
    # REFERENCIA
    # ========================================================

    contenido.append(
        Paragraph(
            (
                "Ref.: Citación a Diligencia "
                "de descargos por presunto "
                "incumplimiento."
            ),
            estilos[
                "CartaReferencia"
            ],
        )
    )

    contenido.append(
        Paragraph(
            "Respetado(a) Señor(a)",
            estilos[
                "CartaTextoIzquierda"
            ],
        )
    )

    contenido.append(
        Spacer(
            1,
            0.2 * cm,
        )
    )

    # ========================================================
    # PÁRRAFO 1
    # ========================================================

    parrafo_apertura = (
        "Mediante el presente documento, "
        "nos permitimos informarle que la compañía "
        "ha hecho apertura formal de proceso "
        "disciplinario fundamentado en el conocimiento "
        "sobre el presunto incumplimiento de sus "
        "obligaciones laborales, "
        f"<b>{escape(motivo)}</b>, "
        "perteneciente al cliente "
        f"<b>{escape(cliente)}</b>."
    )

    contenido.append(
        Paragraph(
            parrafo_apertura,
            estilos[
                "CartaTexto"
            ],
        )
    )

    # ========================================================
    # PÁRRAFO 2 - HECHOS
    # ========================================================

    parrafo_hechos = (
        f"<b>{_texto_html(relato)}</b>"
    )

    if supervisor:
        parrafo_hechos += (
            ", situación reportada por el supervisor "
            "que informa el caso, "
            f"<b>{escape(supervisor)}</b>, "
            "para la correspondiente gestión disciplinaria."
        )

    contenido.append(
        Paragraph(
            parrafo_hechos,
            estilos[
                "CartaTexto"
            ],
        )
    )

    # ========================================================
    # PÁRRAFO 3 - PROGRAMACIÓN DE LA CITACIÓN
    # ========================================================

    if modalidad == "VIRTUAL":
        parrafo_programacion = (
            "Por lo anterior, le solicitamos conectarse "
            "a la diligencia de descargos de manera "
            "<b>virtual</b>, "
            f"el día <b>{escape(fecha_citacion)}</b> "
            f"a las <b>{escape(hora_citacion)}</b>. "
            "El enlace de conexión será suministrado por "
            "Relaciones Laborales a través de WhatsApp interno "
            "antes de la diligencia. "
            "La conexión deberá realizarse de manera puntual "
            "con el fin de rendir diligencia de descargos "
            "por los hechos descritos anteriormente; "
            "de conformidad con el Código Sustantivo "
            "del Trabajo y el Reglamento Interno "
            "de la Compañía."
        )
    else:
        parrafo_programacion = (
            "Por lo anterior, le solicitamos presentarse "
            "en "
            f"<b>{escape(lugar)}</b>, "
            f"el día <b>{escape(fecha_citacion)}</b> "
            f"a las <b>{escape(hora_citacion)}</b>, "
            "con el fin de rendir diligencia de descargos "
            "por los hechos descritos anteriormente; "
            "de conformidad con el Código Sustantivo "
            "del Trabajo y el Reglamento Interno "
            "de la Compañía."
        )

    contenido.append(
        Paragraph(
            parrafo_programacion,
            estilos[
                "CartaTexto"
            ],
        )
    )

    # ========================================================
    # TEXTO LEGAL
    # ========================================================

    contenido.append(
        Paragraph(
            (
                "De esta forma, se da apertura formal "
                "a la investigación disciplinaria, "
                "garantizando su derecho a la defensa "
                "y al debido proceso. En esta diligencia "
                "Usted podrá controvertir las pruebas "
                "que se tienen y podrá aportar las que "
                "considere necesarias, y podrá estar "
                "acompañado(a) de uno o dos compañeros "
                "de trabajo que serán testigos del "
                "proceso disciplinario."
            ),
            estilos[
                "CartaTexto"
            ],
        )
    )

    contenido.append(
        Paragraph(
            (
                "En caso de no asistir a la diligencia "
                "programada deberá aportar inmediatamente "
                "la correspondiente justificación y en "
                "caso de no presentarse ni allegar "
                "justificación dentro de los tres (3) "
                "días a la fecha de la diligencia, "
                "entenderemos que es su decisión no "
                "ejercer su derecho de defensa dentro "
                "de esta diligencia y daremos por cierto "
                "la conducta."
            ),
            estilos[
                "CartaTexto"
            ],
        )
    )

    contenido.append(
        Spacer(
            1,
            0.1 * cm,
        )
    )

    contenido.append(
        Paragraph(
            "Sin otro particular,",
            estilos[
                "CartaTextoIzquierda"
            ],
        )
    )

    contenido.append(
        Spacer(
            1,
            0.65 * cm,
        )
    )

    # ========================================================
    # FIRMA
    # ========================================================

    contenido.extend(
        _crear_bloque_firma(
            estilos
        )
    )

    # ========================================================
    # NOTIFICACIÓN ELECTRÓNICA
    # ========================================================

    contenido.append(
        Spacer(
            1,
            0.35 * cm,
        )
    )

    correo_notificacion = (
        correo_trabajador
        if correo_trabajador
        else "Correo no registrado"
    )

    contenido.append(
        Paragraph(
            (
                "<b>Notificación electrónica</b><br/>"
                f"{escape(correo_notificacion)}<br/>"
                f"{escape(fecha_generacion)} - "
                f"{escape(hora_generacion)}"
            ),
            estilos[
                "CartaNotificacionElectronica"
            ],
        )
    )

    documento_pdf.build(
        contenido,
        onFirstPage=
            _dibujar_encabezado,
        onLaterPages=
            _dibujar_encabezado,
    )

    buffer.seek(0)

    return buffer