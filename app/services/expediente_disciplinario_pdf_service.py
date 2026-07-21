from datetime import date, datetime
from io import BytesIO
from pathlib import Path
from typing import Any, Optional
from xml.sax.saxutils import escape

from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import (
    ParagraphStyle,
    getSampleStyleSheet,
)
from reportlab.lib.units import cm
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen.canvas import Canvas
from reportlab.platypus import (
    KeepTogether,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from domain.models.aspirante import RegistroPersonal
from domain.models.cierre_proceso_disciplinario import (
    CierreProcesoDisciplinario,
)
from domain.models.citacion_proceso_disciplinario import (
    CitacionProcesoDisciplinario,
)
from domain.models.descargo_proceso_disciplinario import (
    DescargoProcesoDisciplinario,
)
from domain.models.documento_proceso_disciplinario import (
    DocumentoProcesoDisciplinario,
)
from domain.models.proceso_disciplinario import (
    ProcesoDisciplinario,
)


BASE_DIR = Path(__file__).resolve().parents[1]

RUTA_LOGO_EMPRESA = (
    BASE_DIR
    / "utilidades"
    / "img"
    / "logo"
    / "LOGOPRINCIPAL.png"
)

RUTA_LOGO_EMPRESA_2 = (
    BASE_DIR
    / "utilidades"
    / "img"
    / "logo"
    / "LOGO_EMPRESA2.jpeg"
)


COLOR_VERDE_PRINCIPAL = colors.HexColor("#047857")
COLOR_VERDE_OSCURO = colors.HexColor("#064E3B")
COLOR_VERDE_CLARO = colors.HexColor("#ECFDF5")
COLOR_VERDE_BORDE = colors.HexColor("#A7F3D0")
COLOR_AZUL_CLARO = colors.HexColor("#EFF6FF")
COLOR_AZUL_BORDE = colors.HexColor("#BFDBFE")
COLOR_GRIS_CLARO = colors.HexColor("#F8FAFC")
COLOR_GRIS_BORDE = colors.HexColor("#D1D5DB")
COLOR_GRIS_TEXTO = colors.HexColor("#4B5563")
COLOR_NEGRO = colors.HexColor("#111827")
ANCHO_CONTENIDO = 17.8 * cm
MARGEN_HORIZONTAL = (letter[0] - ANCHO_CONTENIDO) / 2


def _texto(valor: Any, valor_vacio: str = "—") -> str:
    """
    Convierte un valor en texto seguro para ReportLab.
    """

    if valor is None:
        return valor_vacio

    texto = str(valor).strip()

    if not texto:
        return valor_vacio

    return texto


def _texto_html(valor: Any, valor_vacio: str = "—") -> str:
    """
    Escapa caracteres especiales y conserva saltos de línea.
    """

    texto = _texto(
        valor=valor,
        valor_vacio=valor_vacio,
    )

    return escape(texto).replace("\n", "<br/>")


def _fecha(
    valor: Optional[date | datetime],
    incluir_hora: bool = False,
) -> str:
    """
    Convierte fechas y timestamps a formato colombiano.
    """

    if not valor:
        return "—"

    if isinstance(valor, datetime):
        if incluir_hora:
            return valor.strftime("%d/%m/%Y %I:%M %p")

        return valor.strftime("%d/%m/%Y")

    if isinstance(valor, date):
        return valor.strftime("%d/%m/%Y")

    texto = str(valor).strip()

    try:
        valor_datetime = datetime.fromisoformat(
            texto.replace("Z", "+00:00")
        )

        if incluir_hora:
            return valor_datetime.strftime(
                "%d/%m/%Y %I:%M %p"
            )

        return valor_datetime.strftime("%d/%m/%Y")

    except ValueError:
        return texto[:10]


def _hora(valor: Any) -> str:
    """
    Convierte una hora a formato de 12 horas.
    """

    if valor is None:
        return "—"

    if hasattr(valor, "strftime"):
        try:
            return valor.strftime("%I:%M %p")
        except ValueError:
            pass

    texto = str(valor).strip()

    for formato in (
        "%H:%M:%S",
        "%H:%M",
    ):
        try:
            hora_convertida = datetime.strptime(
                texto,
                formato,
            )

            return hora_convertida.strftime("%I:%M %p")

        except ValueError:
            continue

    return texto or "—"



def _tipo_cierre_legible(valor: Any) -> str:
    """
    Convierte el código interno del cierre en un texto
    legible para el expediente disciplinario.
    """

    codigo = _texto(valor, "").strip().upper()

    tipos_cierre = {
        "CON_MEDIDA_DISCIPLINARIA": "Con medida disciplinaria",
        "SIN_MEDIDA_DISCIPLINARIA": "Sin medida disciplinaria",
        "ARCHIVO_PROCESO": "Archivo del proceso",
        "ARCHIVO_DEL_PROCESO": "Archivo del proceso",
    }

    if not codigo:
        return "—"

    return tipos_cierre.get(
        codigo,
        codigo.replace("_", " " ).capitalize(),
    )


def _obtener_cargo_trabajador(
    db: Session,
    id_registro_personal: int,
) -> str:
    """
    Consulta el cargo real y más reciente del trabajador desde
    AsignacionCargoCliente y la tabla maestra Cargo.

    Usa el mismo origen de información que la consulta de detalle
    de trabajador de Relaciones Laborales.
    """

    fila_cargo = (
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
                    ON cg."IdCargo" = asignacion."IdCargo"

                WHERE
                    rp."IdRegistroPersonal"
                    = :id_registro_personal
                LIMIT 1
                """
            ),
            {
                "id_registro_personal": (
                    id_registro_personal
                )
            },
        )
        .mappings()
        .first()
    )

    if fila_cargo:
        cargo = str(
            fila_cargo.get("Cargo") or ""
        ).strip()

        if cargo:
            return cargo

    return "—"

def _obtener_descripcion_relacion(
    objeto: Any,
    nombres_posibles: tuple[str, ...],
) -> str:
    """
    Intenta obtener la descripción de una relación ORM
    sin depender de un único nombre de columna.
    """

    if objeto is None:
        return "—"

    for nombre in nombres_posibles:
        valor = getattr(
            objeto,
            nombre,
            None,
        )

        if valor not in (
            None,
            "",
        ):
            return str(valor).strip()

    return "—"


def _crear_parrafo(
    valor: Any,
    estilo: ParagraphStyle,
    valor_vacio: str = "—",
) -> Paragraph:
    return Paragraph(
        _texto_html(
            valor=valor,
            valor_vacio=valor_vacio,
        ),
        estilo,
    )


def _crear_tabla_datos(
    filas: list[list[Any]],
    estilos,
    anchos: Optional[list[float]] = None,
) -> Table:
    """
    Construye una tabla estándar del expediente.

    Todas las tablas quedan centradas, con el mismo ancho
    visual y con los textos alineados de manera uniforme.
    """

    filas_formateadas = []

    for fila in filas:
        fila_formateada = []

        for indice, valor in enumerate(fila):
            if indice % 2 == 0:
                fila_formateada.append(
                    Paragraph(
                        f"<b>{_texto_html(valor)}</b>",
                        estilos["TextoTabla"],
                    )
                )
            else:
                fila_formateada.append(
                    _crear_parrafo(
                        valor,
                        estilos["TextoTabla"],
                    )
                )

        filas_formateadas.append(
            fila_formateada
        )

    tabla = Table(
        filas_formateadas,
        colWidths=anchos,
        repeatRows=0,
        hAlign="CENTER",
    )

    tabla.setStyle(
        TableStyle(
            [
                (
                    "BACKGROUND",
                    (0, 0),
                    (-1, -1),
                    colors.white,
                ),
                (
                    "BACKGROUND",
                    (0, 0),
                    (0, -1),
                    COLOR_GRIS_CLARO,
                ),
                (
                    "BACKGROUND",
                    (2, 0),
                    (2, -1),
                    COLOR_GRIS_CLARO,
                ),
                (
                    "GRID",
                    (0, 0),
                    (-1, -1),
                    0.5,
                    COLOR_GRIS_BORDE,
                ),
                (
                    "ALIGN",
                    (0, 0),
                    (-1, -1),
                    "LEFT",
                ),
                (
                    "VALIGN",
                    (0, 0),
                    (-1, -1),
                    "MIDDLE",
                ),
                (
                    "LEFTPADDING",
                    (0, 0),
                    (-1, -1),
                    8,
                ),
                (
                    "RIGHTPADDING",
                    (0, 0),
                    (-1, -1),
                    8,
                ),
                (
                    "TOPPADDING",
                    (0, 0),
                    (-1, -1),
                    8,
                ),
                (
                    "BOTTOMPADDING",
                    (0, 0),
                    (-1, -1),
                    8,
                ),
            ]
        )
    )

    return tabla

def _crear_titulo_seccion(
    titulo: str,
    estilos,
) -> Table:
    """
    Crea un encabezado verde alineado con todas las tablas
    y secciones del expediente.
    """

    tabla = Table(
        [
            [
                Paragraph(
                    escape(titulo),
                    estilos["TituloSeccion"],
                )
            ]
        ],
        colWidths=[ANCHO_CONTENIDO],
        hAlign="CENTER",
    )

    tabla.setStyle(
        TableStyle(
            [
                (
                    "BACKGROUND",
                    (0, 0),
                    (-1, -1),
                    COLOR_VERDE_CLARO,
                ),
                (
                    "BOX",
                    (0, 0),
                    (-1, -1),
                    0.7,
                    COLOR_VERDE_BORDE,
                ),
                (
                    "ALIGN",
                    (0, 0),
                    (-1, -1),
                    "LEFT",
                ),
                (
                    "VALIGN",
                    (0, 0),
                    (-1, -1),
                    "MIDDLE",
                ),
                (
                    "LEFTPADDING",
                    (0, 0),
                    (-1, -1),
                    10,
                ),
                (
                    "RIGHTPADDING",
                    (0, 0),
                    (-1, -1),
                    10,
                ),
                (
                    "TOPPADDING",
                    (0, 0),
                    (-1, -1),
                    8,
                ),
                (
                    "BOTTOMPADDING",
                    (0, 0),
                    (-1, -1),
                    8,
                ),
            ]
        )
    )

    return tabla

def _dibujar_encabezado_y_pie(
    canvas: Canvas,
    documento: SimpleDocTemplate,
) -> None:
    """
    Dibuja los logos corporativos, el encabezado,
    la línea institucional y el pie de página.

    Si alguno de los logos no existe o no puede leerse,
    el PDF se genera igualmente.
    """

    canvas.saveState()

    ancho_pagina, alto_pagina = letter
    numero_pagina = canvas.getPageNumber()

    margen_izquierdo = documento.leftMargin
    margen_derecho = ancho_pagina - documento.rightMargin

    y_encabezado = alto_pagina - 0.95 * cm
    y_linea_superior = alto_pagina - 1.68 * cm

    ancho_logo_izquierdo = 3.6 * cm
    alto_logo_izquierdo = 1.35 * cm

    ancho_logo_derecho = 3.4 * cm
    alto_logo_derecho = 1.35 * cm

    # Logo izquierdo
    try:
        if RUTA_LOGO_EMPRESA.exists():
            canvas.drawImage(
                ImageReader(str(RUTA_LOGO_EMPRESA)),
                margen_izquierdo,
                alto_pagina - 1.48 * cm,
                width=ancho_logo_izquierdo,
                height=alto_logo_izquierdo,
                preserveAspectRatio=True,
                mask="auto",
            )
    except Exception:
        pass

    # Logo derecho
    try:
        if RUTA_LOGO_EMPRESA_2.exists():
            canvas.drawImage(
                ImageReader(str(RUTA_LOGO_EMPRESA_2)),
                margen_derecho - ancho_logo_derecho,
                alto_pagina - 1.48 * cm,
                width=ancho_logo_derecho,
                height=alto_logo_derecho,
                preserveAspectRatio=True,
                mask="auto",
            )
    except Exception:
        pass

    # Texto central del encabezado
    canvas.setFillColor(COLOR_VERDE_OSCURO)
    canvas.setFont(
        "Helvetica-Bold",
        8.5,
    )

    canvas.drawCentredString(
        ancho_pagina / 2,
        y_encabezado,
        "ASEOS LA PERFECCIÓN S.A.S.",
    )

    canvas.setFillColor(COLOR_GRIS_TEXTO)
    canvas.setFont(
        "Helvetica",
        7.5,
    )

    canvas.drawCentredString(
        ancho_pagina / 2,
        alto_pagina - 1.2 * cm,
        "Expediente disciplinario",
    )

    # Línea corporativa superior
    canvas.setStrokeColor(COLOR_VERDE_PRINCIPAL)
    canvas.setLineWidth(1.2)

    canvas.line(
        margen_izquierdo,
        y_linea_superior,
        margen_derecho,
        y_linea_superior,
    )

    # Línea del pie
    canvas.setStrokeColor(COLOR_GRIS_BORDE)
    canvas.setLineWidth(0.5)

    canvas.line(
        margen_izquierdo,
        1.05 * cm,
        margen_derecho,
        1.05 * cm,
    )

    # Pie de página izquierdo
    canvas.setFillColor(COLOR_GRIS_TEXTO)
    canvas.setFont(
        "Helvetica",
        7.5,
    )

    canvas.drawString(
        margen_izquierdo,
        0.65 * cm,
        "Sistema Integral de Recursos Humanos",
    )

    # Pie de página derecho
    canvas.drawRightString(
        margen_derecho,
        0.65 * cm,
        f"Página {numero_pagina}",
    )

    canvas.restoreState()

def _crear_estilos():
    styles = getSampleStyleSheet()

    styles.add(
        ParagraphStyle(
            name="TituloPrincipalPDF",
            parent=styles["Title"],
            fontName="Helvetica-Bold",
            fontSize=18,
            leading=22,
            alignment=TA_CENTER,
            textColor=COLOR_VERDE_OSCURO,
            spaceAfter=5,
        )
    )

    styles.add(
        ParagraphStyle(
            name="SubtituloPrincipalPDF",
            parent=styles["Normal"],
            fontName="Helvetica-Bold",
            fontSize=11,
            leading=14,
            alignment=TA_CENTER,
            textColor=COLOR_GRIS_TEXTO,
            spaceAfter=12,
        )
    )

    styles.add(
        ParagraphStyle(
            name="TituloSeccion",
            parent=styles["Heading2"],
            fontName="Helvetica-Bold",
            fontSize=11,
            leading=14,
            textColor=COLOR_VERDE_OSCURO,
            alignment=TA_LEFT,
            spaceBefore=0,
            spaceAfter=0,
        )
    )

    styles.add(
        ParagraphStyle(
            name="SubtituloInterno",
            parent=styles["Heading3"],
            fontName="Helvetica-Bold",
            fontSize=10,
            leading=13,
            textColor=COLOR_NEGRO,
            spaceBefore=6,
            spaceAfter=5,
        )
    )

    styles.add(
        ParagraphStyle(
            name="TextoNormalPDF",
            parent=styles["Normal"],
            fontName="Helvetica",
            fontSize=9,
            leading=13,
            textColor=COLOR_NEGRO,
            alignment=TA_LEFT,
        )
    )

    styles.add(
        ParagraphStyle(
            name="TextoTabla",
            parent=styles["Normal"],
            fontName="Helvetica",
            fontSize=8,
            leading=11,
            textColor=COLOR_NEGRO,
        )
    )

    styles.add(
        ParagraphStyle(
            name="TextoPequeno",
            parent=styles["Normal"],
            fontName="Helvetica",
            fontSize=7.5,
            leading=10,
            textColor=COLOR_GRIS_TEXTO,
        )
    )

    styles.add(
        ParagraphStyle(
            name="EstadoCerrado",
            parent=styles["Normal"],
            fontName="Helvetica-Bold",
            fontSize=9,
            leading=12,
            alignment=TA_CENTER,
            textColor=COLOR_VERDE_OSCURO,
        )
    )

    return styles


def generar_expediente_disciplinario_pdf(
    db: Session,
    id_proceso: int,
    url_base: str,
) -> BytesIO:
    """
    Consulta la información del expediente y genera
    el PDF disciplinario completo.

    Devuelve:
        BytesIO listo para ser enviado por StreamingResponse.
    """

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
                "mensaje": (
                    "Proceso disciplinario no encontrado."
                ),
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
                    "No se encontró el trabajador asociado "
                    "al proceso disciplinario."
                ),
                "IdRegistroPersonal": (
                    proceso.IdRegistroPersonal
                ),
            },
        )

    citacion = (
        db.query(CitacionProcesoDisciplinario)
        .filter(
            CitacionProcesoDisciplinario
            .IdProcesoDisciplinario
            == id_proceso
        )
        .first()
    )

    descargo = (
        db.query(DescargoProcesoDisciplinario)
        .filter(
            DescargoProcesoDisciplinario
            .IdProcesoDisciplinario
            == id_proceso
        )
        .first()
    )

    cierre = (
        db.query(CierreProcesoDisciplinario)
        .filter(
            CierreProcesoDisciplinario
            .IdProcesoDisciplinario
            == id_proceso
        )
        .first()
    )

    documentos = (
        db.query(DocumentoProcesoDisciplinario)
        .filter(
            DocumentoProcesoDisciplinario
            .IdProcesoDisciplinario
            == id_proceso
        )
        .order_by(
            DocumentoProcesoDisciplinario
            .FechaCreacion.asc()
        )
        .all()
    )

    nombre_completo = " ".join(
        parte
        for parte in (
            _texto(
                getattr(
                    trabajador,
                    "Nombres",
                    None,
                ),
                "",
            ),
            _texto(
                getattr(
                    trabajador,
                    "Apellidos",
                    None,
                ),
                "",
            ),
        )
        if parte
    ).strip()

    if not nombre_completo:
        nombre_completo = "—"

    tipo_identificacion = (
        _obtener_descripcion_relacion(
            getattr(
                trabajador,
                "tipo_identificacion",
                None,
            ),
            (
                "Descripcion",
                "Nombre",
                "Codigo",
                "Abreviatura",
            ),
        )
    )

    cargo = _obtener_cargo_trabajador(
        db=db,
        id_registro_personal=(
            trabajador.IdRegistroPersonal
        ),
    )

    estilos = _crear_estilos()
    buffer = BytesIO()

    documento_pdf = SimpleDocTemplate(
        buffer,
        pagesize=letter,
        rightMargin=MARGEN_HORIZONTAL,
        leftMargin=MARGEN_HORIZONTAL,
        topMargin=2.35 * cm,
        bottomMargin=1.35 * cm,
        title=(
            f"Expediente disciplinario "
            f"{id_proceso}"
        ),
        author="Aseos La Perfección S.A.S.",
        subject="Expediente disciplinario",
    )

    contenido = []

    contenido.append(
        Spacer(
            1,
            0.25 * cm,
        )
    )

    contenido.append(
        Paragraph(
            "EXPEDIENTE DISCIPLINARIO",
            estilos["TituloPrincipalPDF"],
        )
    )

    contenido.append(
        Paragraph(
            (
                f"Expediente No. {id_proceso} · "
                f"Generado el "
                f"{datetime.now().strftime('%d/%m/%Y %I:%M %p')}"
            ),
            estilos["SubtituloPrincipalPDF"],
        )
    )

    estado_actual = _texto(
        proceso.EstadoProceso
    ).upper()

    tabla_estado = Table(
        [
            [
                Paragraph(
                    (
                        f"ESTADO DEL EXPEDIENTE: "
                        f"{escape(estado_actual)}"
                    ),
                    estilos["EstadoCerrado"],
                )
            ]
        ],
        colWidths=[ANCHO_CONTENIDO],
        hAlign="CENTER",
    )

    tabla_estado.setStyle(
        TableStyle(
            [
                (
                    "BACKGROUND",
                    (0, 0),
                    (-1, -1),
                    (
                        COLOR_VERDE_CLARO
                        if estado_actual == "CERRADO"
                        else COLOR_AZUL_CLARO
                    ),
                ),
                (
                    "BOX",
                    (0, 0),
                    (-1, -1),
                    0.8,
                    (
                        COLOR_VERDE_BORDE
                        if estado_actual == "CERRADO"
                        else COLOR_AZUL_BORDE
                    ),
                ),
                (
                    "TOPPADDING",
                    (0, 0),
                    (-1, -1),
                    8,
                ),
                (
                    "BOTTOMPADDING",
                    (0, 0),
                    (-1, -1),
                    8,
                ),
            ]
        )
    )

    contenido.append(tabla_estado)
    contenido.append(Spacer(1, 0.35 * cm))

    contenido.append(
        _crear_titulo_seccion(
            "1. Información del trabajador",
            estilos,
        )
    )

    contenido.append(Spacer(1, 0.15 * cm))

    contenido.append(
        _crear_tabla_datos(
            filas=[
                [
                    "Nombre completo",
                    nombre_completo,
                    "Documento",
                    (
                        f"{tipo_identificacion} "
                        f"{_texto(trabajador.NumeroIdentificacion)}"
                    ).strip(),
                ],
                [
                    "Cargo",
                    cargo,
                    "Id. trabajador",
                    trabajador.IdRegistroPersonal,
                ],
            ],
            estilos=estilos,
            anchos=[
                3.3 * cm,
                5.6 * cm,
                3.3 * cm,
                5.6 * cm,
            ],
        )
    )

    contenido.append(Spacer(1, 0.35 * cm))

    contenido.append(
        _crear_titulo_seccion(
            "2. Información general del proceso",
            estilos,
        )
    )

    contenido.append(Spacer(1, 0.15 * cm))

    contenido.append(
        _crear_tabla_datos(
            filas=[
                [
                    "Número de expediente",
                    id_proceso,
                    "Estado",
                    proceso.EstadoProceso,
                ],
                [
                    "Fecha de inicio",
                    _fecha(proceso.FechaCreacion),
                    "Fecha de cierre",
                    _fecha(
                        cierre.FechaCierre
                        if cierre
                        else None
                    ),
                ],
                [
                    "Origen",
                    proceso.OrigenProceso,
                    "Usuario actualización",
                    proceso.UsuarioActualizacion,
                ],
            ],
            estilos=estilos,
            anchos=[
                3.3 * cm,
                5.6 * cm,
                3.3 * cm,
                5.6 * cm,
            ],
        )
    )

    contenido.append(Spacer(1, 0.35 * cm))

    contenido.append(
        _crear_titulo_seccion(
            "3. Citación",
            estilos,
        )
    )

    contenido.append(Spacer(1, 0.15 * cm))

    if citacion:
        contenido.append(
            _crear_tabla_datos(
                filas=[
                    [
                        "Fecha",
                        _fecha(citacion.FechaCitacion),
                        "Hora",
                        _hora(citacion.HoraCitacion),
                    ],
                    [
                        "Lugar",
                        citacion.LugarCitacion,
                        "Estado",
                        "Registrada",
                    ],
                ],
                estilos=estilos,
                anchos=[
                    3.3 * cm,
                    5.6 * cm,
                    3.3 * cm,
                    5.6 * cm,
                ],
            )
        )

        contenido.append(
            Paragraph(
                "Motivo y hechos registrados",
                estilos["SubtituloInterno"],
            )
        )

        contenido.append(
            _crear_parrafo(
                citacion.MotivoCitacion,
                estilos["TextoNormalPDF"],
                "No se registró motivo para la citación.",
            )
        )

    else:
        contenido.append(
            _crear_parrafo(
                "No existe una citación asociada al expediente.",
                estilos["TextoNormalPDF"],
            )
        )

    contenido.append(Spacer(1, 0.35 * cm))

    contenido.append(
        _crear_titulo_seccion(
            "4. Diligencia de descargos",
            estilos,
        )
    )

    contenido.append(Spacer(1, 0.15 * cm))

    if descargo:
        contenido.append(
            _crear_tabla_datos(
                filas=[
                    [
                        "Fecha",
                        _fecha(descargo.FechaDescargo),
                        "Hora",
                        _hora(descargo.HoraDescargo),
                    ],
                    [
                        "Responsable",
                        descargo.ResponsableDescargo,
                        "Estado",
                        "Registrado",
                    ],
                ],
                estilos=estilos,
                anchos=[
                    3.3 * cm,
                    5.6 * cm,
                    3.3 * cm,
                    5.6 * cm,
                ],
            )
        )

        contenido.append(
            Paragraph(
                "Manifestación del trabajador",
                estilos["SubtituloInterno"],
            )
        )

        contenido.append(
            _crear_parrafo(
                descargo.DescargoTrabajador,
                estilos["TextoNormalPDF"],
                "No se registró manifestación del trabajador.",
            )
        )

        contenido.append(
            Paragraph(
                "Manifestación y observaciones",
                estilos["SubtituloInterno"],
            )
        )

        contenido.append(
            _crear_parrafo(
                descargo.Observaciones,
                estilos["TextoNormalPDF"],
                "No se registraron observaciones adicionales.",
            )
        )

    else:
        contenido.append(
            _crear_parrafo(
                "No existen descargos registrados para este expediente.",
                estilos["TextoNormalPDF"],
            )
        )

    contenido.append(PageBreak())

    contenido.append(
        _crear_titulo_seccion(
            "5. Decisión y cierre del proceso",
            estilos,
        )
    )

    contenido.append(Spacer(1, 0.15 * cm))

    if cierre:
        contenido.append(
            _crear_tabla_datos(
                filas=[
                    [
                        "Fecha de cierre",
                        _fecha(cierre.FechaCierre),
                        "Responsable",
                        cierre.ResponsableCierre,
                    ],
                    [
                        "Tipo de cierre",
                        _tipo_cierre_legible(
                            cierre.TipoCierre
                        ),
                        "Estado",
                        "Finalizado",
                    ],
                ],
                estilos=estilos,
                anchos=[
                    3.3 * cm,
                    5.6 * cm,
                    3.3 * cm,
                    5.6 * cm,
                ],
            )
        )

        contenido.append(
            Paragraph(
                "Medida disciplinaria",
                estilos["SubtituloInterno"],
            )
        )

        contenido.append(
            _crear_parrafo(
                cierre.MedidaDisciplinaria,
                estilos["TextoNormalPDF"],
                "No se registró medida disciplinaria.",
            )
        )

        contenido.append(
            Paragraph(
                "Conclusión de Relaciones Laborales",
                estilos["SubtituloInterno"],
            )
        )

        contenido.append(
            _crear_parrafo(
                cierre.ConclusionRRLL,
                estilos["TextoNormalPDF"],
                "No se registró conclusión de Relaciones Laborales.",
            )
        )

    else:
        contenido.append(
            _crear_parrafo(
                "El expediente todavía no tiene un cierre registrado.",
                estilos["TextoNormalPDF"],
            )
        )

    contenido.append(Spacer(1, 0.35 * cm))

    contenido.append(
        _crear_titulo_seccion(
            "6. Documentos asociados",
            estilos,
        )
    )

    contenido.append(Spacer(1, 0.15 * cm))

    if documentos:
        filas_documentos = [
            [
                Paragraph(
                    "<b>Documento</b>",
                    estilos["TextoTabla"],
                ),
                Paragraph(
                    "<b>Tipo</b>",
                    estilos["TextoTabla"],
                ),
                Paragraph(
                    "<b>Observación</b>",
                    estilos["TextoTabla"],
                ),
                Paragraph(
                    "<b>Fecha</b>",
                    estilos["TextoTabla"],
                ),
                Paragraph(
                    "<b>Acción</b>",
                    estilos["TextoTabla"],
                ),
            ]
        ]

        for documento in documentos:
            id_documento = (
                documento
                .IdDocumentoProcesoDisciplinario
            )

            ruta_relativa = str(
                documento.RutaArchivo or ""
            ).strip()

            if ruta_relativa:
                ruta_documento = (
                    BASE_DIR
                    / Path(
                        ruta_relativa.replace("\\", "/")
                    )
                ).resolve()
            else:
                ruta_documento = None

            archivo_disponible = (
                ruta_documento is not None
                and ruta_documento.is_file()
            )

            if archivo_disponible:
                url_documento = (
                    f"{url_base}"
                    f"/api/documento-proceso-disciplinario/"
                    f"{id_documento}/archivo"
                )

                enlace_documento = Paragraph(
                    (
                        f'<link href="{escape(url_documento)}" '
                        f'color="#047857">'
                        f"<u>Abrir documento</u>"
                        f"</link>"
                    ),
                    estilos["TextoTabla"],
                )
            else:
                enlace_documento = Paragraph(
                    (
                        '<font color="#6B7280">'
                        "Archivo no disponible"
                        "</font>"
                    ),
                    estilos["TextoTabla"],
                )

            filas_documentos.append(
                [
                    _crear_parrafo(
                        documento.NombreArchivo,
                        estilos["TextoTabla"],
                    ),
                    _crear_parrafo(
                        documento.TipoDocumento,
                        estilos["TextoTabla"],
                    ),
                    _crear_parrafo(
                        documento.Observacion,
                        estilos["TextoTabla"],
                    ),
                    _crear_parrafo(
                        _fecha(
                            documento.FechaCreacion
                        ),
                        estilos["TextoTabla"],
                    ),
                    enlace_documento,
                ]
            )

        tabla_documentos = Table(
            filas_documentos,
            colWidths=[
                4.6 * cm,
                2.7 * cm,
                4.8 * cm,
                2.3 * cm,
                3.4 * cm,
            ],
            repeatRows=1,
            hAlign="CENTER",
        )

        tabla_documentos.setStyle(
            TableStyle(
                [
                    (
                        "BACKGROUND",
                        (0, 0),
                        (-1, 0),
                        COLOR_VERDE_CLARO,
                    ),
                    (
                        "GRID",
                        (0, 0),
                        (-1, -1),
                        0.5,
                        COLOR_GRIS_BORDE,
                    ),
                    (
                        "VALIGN",
                        (0, 0),
                        (-1, -1),
                        "MIDDLE",
                    ),
                    (
                        "ALIGN",
                        (4, 1),
                        (4, -1),
                        "CENTER",
                    ),
                    (
                        "LEFTPADDING",
                        (0, 0),
                        (-1, -1),
                        6,
                    ),
                    (
                        "RIGHTPADDING",
                        (0, 0),
                        (-1, -1),
                        6,
                    ),
                    (
                        "TOPPADDING",
                        (0, 0),
                        (-1, -1),
                        7,
                    ),
                    (
                        "BOTTOMPADDING",
                        (0, 0),
                        (-1, -1),
                        7,
                    ),
                ]
            )
        )

        contenido.append(
            tabla_documentos
        )
    else:
        contenido.append(
                _crear_parrafo(
                    "No existen documentos asociados al expediente.",
                    estilos["TextoNormalPDF"],
                )
            )
    contenido.append(Spacer(1, 0.4 * cm))

    contenido.append(
        _crear_titulo_seccion(
            "7. Línea de tiempo",
            estilos,
        )
    )

    contenido.append(Spacer(1, 0.15 * cm))

    linea_tiempo = [
        [
            "Proceso iniciado",
            _fecha(proceso.FechaCreacion),
        ],
        [
            "Citación",
            (
                _fecha(citacion.FechaCitacion)
                if citacion
                else "Pendiente"
            ),
        ],
        [
            "Descargos",
            (
                _fecha(descargo.FechaDescargo)
                if descargo
                else "Pendiente"
            ),
        ],
        [
            "Cierre",
            (
                _fecha(cierre.FechaCierre)
                if cierre
                else "Pendiente"
            ),
        ],
    ]

    tabla_linea_tiempo = Table(
        [
            [
                Paragraph(
                    f"<b>{escape(etapa)}</b>",
                    estilos["TextoTabla"],
                ),
                Paragraph(
                    escape(_texto(fecha)),
                    estilos["TextoTabla"],
                ),
            ]
            for etapa, fecha in linea_tiempo
        ],
        colWidths=[
            8.9 * cm,
            8.9 * cm,
        ],
        hAlign="CENTER",
    )

    tabla_linea_tiempo.setStyle(
        TableStyle(
            [
                (
                    "GRID",
                    (0, 0),
                    (-1, -1),
                    0.5,
                    COLOR_GRIS_BORDE,
                ),
                (
                    "BACKGROUND",
                    (0, 0),
                    (0, -1),
                    COLOR_GRIS_CLARO,
                ),
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
                    7,
                ),
                (
                    "RIGHTPADDING",
                    (0, 0),
                    (-1, -1),
                    7,
                ),
                (
                    "TOPPADDING",
                    (0, 0),
                    (-1, -1),
                    7,
                ),
                (
                    "BOTTOMPADDING",
                    (0, 0),
                    (-1, -1),
                    7,
                ),
            ]
        )
    )

    contenido.append(tabla_linea_tiempo)
    contenido.append(Spacer(1, 0.55 * cm))

    contenido.append(
        _crear_titulo_seccion(
            "8. Firmas",
            estilos,
        )
    )

    contenido.append(Spacer(1, 0.35 * cm))

    bloque_firmas = Table(
        [
            [
                Paragraph(
                    "<br/><br/><br/>"
                    "_________________________________<br/>"
                    "<b>Firma del trabajador</b><br/>"
                    f"{escape(nombre_completo)}<br/>"
                    f"{escape(_texto(trabajador.NumeroIdentificacion))}",
                    estilos["TextoNormalPDF"],
                ),
                Paragraph(
                    "<br/><br/><br/>"
                    "_________________________________<br/>"
                    "<b>Firma de Relaciones Laborales</b><br/>"
                    f"{escape(_texto(cierre.ResponsableCierre if cierre else None))}<br/>"
                    "Aseos La Perfección S.A.S.",
                    estilos["TextoNormalPDF"],
                ),
            ]
        ],
        colWidths=[
            8.9 * cm,
            8.9 * cm,
        ],
        hAlign="CENTER",
    )

    bloque_firmas.setStyle(
        TableStyle(
            [
                (
                    "VALIGN",
                    (0, 0),
                    (-1, -1),
                    "BOTTOM",
                ),
                (
                    "ALIGN",
                    (0, 0),
                    (-1, -1),
                    "CENTER",
                ),
                (
                    "BOX",
                    (0, 0),
                    (-1, -1),
                    0.5,
                    COLOR_GRIS_BORDE,
                ),
                (
                    "INNERGRID",
                    (0, 0),
                    (-1, -1),
                    0.5,
                    COLOR_GRIS_BORDE,
                ),
                (
                    "TOPPADDING",
                    (0, 0),
                    (-1, -1),
                    10,
                ),
                (
                    "BOTTOMPADDING",
                    (0, 0),
                    (-1, -1),
                    10,
                ),
            ]
        )
    )

    contenido.append(
        KeepTogether(
            [
                bloque_firmas,
                Spacer(1, 0.35 * cm),
                Paragraph(
                    (
                        "Documento generado automáticamente por "
                        "el Sistema Integral de Recursos Humanos. "
                        "La firma y archivo definitivo serán gestionados "
                        "por Relaciones Laborales."
                    ),
                    estilos["TextoPequeno"],
                ),
            ]
        )
    )

    documento_pdf.build(
        contenido,
        onFirstPage=_dibujar_encabezado_y_pie,
        onLaterPages=_dibujar_encabezado_y_pie,
    )

    buffer.seek(0)

    return buffer