from datetime import datetime
from io import BytesIO

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import cm
from reportlab.platypus import (
    SimpleDocTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
)

from infrastructure.db.deps import get_db
from domain.models.proceso_disciplinario import ProcesoDisciplinario
from domain.models.citacion_proceso_disciplinario import CitacionProcesoDisciplinario
from domain.models.descargo_proceso_disciplinario import DescargoProcesoDisciplinario
from domain.models.cierre_proceso_disciplinario import CierreProcesoDisciplinario
from domain.models.documento_proceso_disciplinario import DocumentoProcesoDisciplinario
from domain.schemas.proceso_disciplinario_schema import (
    ProcesoDisciplinarioCreate,
    ProcesoDisciplinarioUpdate,
    ProcesoDisciplinarioResponse,
)

router = APIRouter(
    prefix="/api/procesos-disciplinarios",
    tags=["Procesos Disciplinarios"],
)


def obtener_proceso_o_error(
    db: Session,
    id_proceso: int,
) -> ProcesoDisciplinario:
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

    return proceso


def validar_proceso_modificable(
    proceso: ProcesoDisciplinario,
) -> None:
    estado_actual = str(
        proceso.EstadoProceso or ""
    ).strip().upper()

    if estado_actual == "CERRADO":
        raise HTTPException(
            status_code=409,
            detail={
                "mensaje": (
                    "El proceso disciplinario ya fue cerrado "
                    "y no admite modificaciones."
                ),
                "IdProcesoDisciplinario": (
                    proceso.IdProcesoDisciplinario
                ),
                "EstadoProceso": proceso.EstadoProceso,
            },
        )


def _texto(valor):
    return str(valor) if valor not in [None, ""] else "—"


def _fecha(valor):
    return str(valor)[:10] if valor else "—"


def _parrafo(texto, estilo):
    return Paragraph(_texto(texto).replace("\n", "<br/>"), estilo)


@router.post("/", response_model=ProcesoDisciplinarioResponse)
def crear_proceso_disciplinario(
    data: ProcesoDisciplinarioCreate,
    db: Session = Depends(get_db),
):
    nuevo = ProcesoDisciplinario(
        IdRegistroPersonal=data.IdRegistroPersonal,
        EstadoProceso=data.EstadoProceso or "INICIADO",
        OrigenProceso=data.OrigenProceso or "RRLL",
        UsuarioActualizacion=data.UsuarioActualizacion,
    )

    db.add(nuevo)
    db.commit()
    db.refresh(nuevo)

    return nuevo


@router.get("/trabajador/{id_registro_personal}")
def listar_procesos_por_trabajador(
    id_registro_personal: int,
    db: Session = Depends(get_db),
):
    procesos = (
        db.query(ProcesoDisciplinario)
        .filter(ProcesoDisciplinario.IdRegistroPersonal == id_registro_personal)
        .order_by(ProcesoDisciplinario.FechaCreacion.desc())
        .all()
    )

    return procesos


@router.get("/trabajador/{id_registro_personal}/historial")
def obtener_historial_disciplinario_trabajador(
    id_registro_personal: int,
    db: Session = Depends(get_db),
):
    procesos = (
        db.query(ProcesoDisciplinario)
        .filter(ProcesoDisciplinario.IdRegistroPersonal == id_registro_personal)
        .order_by(ProcesoDisciplinario.FechaCreacion.desc())
        .all()
    )

    historial = []

    for proceso in procesos:
        citacion = (
            db.query(CitacionProcesoDisciplinario)
            .filter(
                CitacionProcesoDisciplinario.IdProcesoDisciplinario
                == proceso.IdProcesoDisciplinario
            )
            .first()
        )

        descargo = (
            db.query(DescargoProcesoDisciplinario)
            .filter(
                DescargoProcesoDisciplinario.IdProcesoDisciplinario
                == proceso.IdProcesoDisciplinario
            )
            .first()
        )

        cierre = (
            db.query(CierreProcesoDisciplinario)
            .filter(
                CierreProcesoDisciplinario.IdProcesoDisciplinario
                == proceso.IdProcesoDisciplinario
            )
            .first()
        )

        historial.append(
            {
                "IdProcesoDisciplinario": proceso.IdProcesoDisciplinario,
                "IdRegistroPersonal": proceso.IdRegistroPersonal,
                "FechaCreacion": proceso.FechaCreacion,
                "EstadoProceso": proceso.EstadoProceso,
                "OrigenProceso": proceso.OrigenProceso,
                "TieneCitacion": citacion is not None,
                "TieneDescargo": descargo is not None,
                "TieneCierre": cierre is not None,
                "FechaCitacion": citacion.FechaCitacion if citacion else None,
                "MotivoCitacion": citacion.MotivoCitacion if citacion else None,
                "FechaDescargo": descargo.FechaDescargo if descargo else None,
                "MedidaDisciplinaria": cierre.MedidaDisciplinaria if cierre else None,
                "TipoCierre": cierre.TipoCierre if cierre else None,
                "FechaCierre": cierre.FechaCierre if cierre else None,
            }
        )

    return historial


@router.get("/{id_proceso}/expediente")
def obtener_expediente_disciplinario(
    id_proceso: int,
    db: Session = Depends(get_db),
):
    proceso = (
        db.query(ProcesoDisciplinario)
        .filter(ProcesoDisciplinario.IdProcesoDisciplinario == id_proceso)
        .first()
    )

    if not proceso:
        raise HTTPException(
            status_code=404,
            detail="Proceso disciplinario no encontrado",
        )

    citacion = (
        db.query(CitacionProcesoDisciplinario)
        .filter(CitacionProcesoDisciplinario.IdProcesoDisciplinario == id_proceso)
        .first()
    )

    descargo = (
        db.query(DescargoProcesoDisciplinario)
        .filter(DescargoProcesoDisciplinario.IdProcesoDisciplinario == id_proceso)
        .first()
    )

    cierre = (
        db.query(CierreProcesoDisciplinario)
        .filter(CierreProcesoDisciplinario.IdProcesoDisciplinario == id_proceso)
        .first()
    )

    documentos = (
        db.query(DocumentoProcesoDisciplinario)
        .filter(DocumentoProcesoDisciplinario.IdProcesoDisciplinario == id_proceso)
        .order_by(DocumentoProcesoDisciplinario.FechaCreacion.desc())
        .all()
    )

    return {
        "Proceso": proceso,
        "Citacion": citacion,
        "Descargo": descargo,
        "Cierre": cierre,
        "Documentos": documentos,
    }


@router.get("/{id_proceso}/pdf")
def generar_pdf_expediente_disciplinario(
    id_proceso: int,
    db: Session = Depends(get_db),
):
    proceso = (
        db.query(ProcesoDisciplinario)
        .filter(ProcesoDisciplinario.IdProcesoDisciplinario == id_proceso)
        .first()
    )

    if not proceso:
        raise HTTPException(
            status_code=404,
            detail="Proceso disciplinario no encontrado",
        )

    citacion = (
        db.query(CitacionProcesoDisciplinario)
        .filter(CitacionProcesoDisciplinario.IdProcesoDisciplinario == id_proceso)
        .first()
    )

    descargo = (
        db.query(DescargoProcesoDisciplinario)
        .filter(DescargoProcesoDisciplinario.IdProcesoDisciplinario == id_proceso)
        .first()
    )

    cierre = (
        db.query(CierreProcesoDisciplinario)
        .filter(CierreProcesoDisciplinario.IdProcesoDisciplinario == id_proceso)
        .first()
    )

    documentos = (
        db.query(DocumentoProcesoDisciplinario)
        .filter(DocumentoProcesoDisciplinario.IdProcesoDisciplinario == id_proceso)
        .order_by(DocumentoProcesoDisciplinario.FechaCreacion.desc())
        .all()
    )

    buffer = BytesIO()

    doc = SimpleDocTemplate(
        buffer,
        pagesize=letter,
        rightMargin=1.5 * cm,
        leftMargin=1.5 * cm,
        topMargin=1.5 * cm,
        bottomMargin=1.5 * cm,
    )

    styles = getSampleStyleSheet()
    styles.add(
        ParagraphStyle(
            name="TituloVerde",
            parent=styles["Title"],
            textColor=colors.HexColor("#047857"),
            fontSize=18,
            leading=22,
            alignment=1,
            spaceAfter=14,
        )
    )
    styles.add(
        ParagraphStyle(
            name="Subtitulo",
            parent=styles["Heading2"],
            textColor=colors.HexColor("#064e3b"),
            fontSize=12,
            leading=14,
            spaceBefore=12,
            spaceAfter=8,
        )
    )
    styles.add(
        ParagraphStyle(
            name="TextoNormal",
            parent=styles["Normal"],
            fontSize=9,
            leading=12,
        )
    )

    contenido = []

    contenido.append(Paragraph("ASEOS LA PERFECCION S.A.S.", styles["TituloVerde"]))
    contenido.append(Paragraph("EXPEDIENTE DISCIPLINARIO", styles["TituloVerde"]))

    contenido.append(
        Paragraph(
            f"Expediente No. {id_proceso} - Estado: {_texto(proceso.EstadoProceso)}",
            styles["TextoNormal"],
        )
    )

    contenido.append(Spacer(1, 10))

    tabla_resumen = Table(
        [
            ["Fecha inicio", _fecha(proceso.FechaCreacion), "Fecha cierre", _fecha(cierre.FechaCierre if cierre else None)],
            ["Origen", _texto(proceso.OrigenProceso), "Usuario", _texto(proceso.UsuarioActualizacion)],
        ],
        colWidths=[3.5 * cm, 5 * cm, 3.5 * cm, 5 * cm],
    )
    tabla_resumen.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#ecfdf5")),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#a7f3d0")),
                ("FONTNAME", (0, 0), (-1, -1), "Helvetica"),
                ("FONTSIZE", (0, 0), (-1, -1), 8),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
                ("FONTNAME", (2, 0), (2, -1), "Helvetica-Bold"),
            ]
        )
    )
    contenido.append(tabla_resumen)

    contenido.append(Paragraph("CITACION", styles["Subtitulo"]))
    contenido.append(
        Table(
            [
                ["Fecha", _fecha(citacion.FechaCitacion if citacion else None)],
                ["Hora", _texto(citacion.HoraCitacion if citacion else None)],
                ["Lugar", _texto(citacion.LugarCitacion if citacion else None)],
            ],
            colWidths=[4 * cm, 12 * cm],
            style=[
                ("GRID", (0, 0), (-1, -1), 0.5, colors.lightgrey),
                ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), 8),
            ],
        )
    )
    contenido.append(Spacer(1, 6))
    contenido.append(_parrafo(citacion.MotivoCitacion if citacion else "Sin citación registrada.", styles["TextoNormal"]))

    contenido.append(Paragraph("DESCARGOS", styles["Subtitulo"]))
    contenido.append(
        Table(
            [
                ["Fecha", _fecha(descargo.FechaDescargo if descargo else None)],
                ["Hora", _texto(descargo.HoraDescargo if descargo else None)],
                ["Responsable", _texto(descargo.ResponsableDescargo if descargo else None)],
            ],
            colWidths=[4 * cm, 12 * cm],
            style=[
                ("GRID", (0, 0), (-1, -1), 0.5, colors.lightgrey),
                ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), 8),
            ],
        )
    )
    contenido.append(Spacer(1, 6))
    contenido.append(Paragraph("Manifestacion del trabajador", styles["Subtitulo"]))
    contenido.append(_parrafo(descargo.DescargoTrabajador if descargo else "Sin descargos registrados.", styles["TextoNormal"]))
    contenido.append(Paragraph("Observaciones", styles["Subtitulo"]))
    contenido.append(_parrafo(descargo.Observaciones if descargo else "Sin observaciones registradas.", styles["TextoNormal"]))

    contenido.append(Paragraph("CIERRE", styles["Subtitulo"]))
    contenido.append(
        Table(
            [
                ["Fecha cierre", _fecha(cierre.FechaCierre if cierre else None)],
                ["Tipo cierre", _texto(cierre.TipoCierre if cierre else None)],
                ["Medida disciplinaria", _texto(cierre.MedidaDisciplinaria if cierre else None)],
                ["Responsable", _texto(cierre.ResponsableCierre if cierre else None)],
            ],
            colWidths=[4 * cm, 12 * cm],
            style=[
                ("GRID", (0, 0), (-1, -1), 0.5, colors.lightgrey),
                ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), 8),
            ],
        )
    )
    contenido.append(Spacer(1, 6))
    contenido.append(Paragraph("Conclusion RRLL", styles["Subtitulo"]))
    contenido.append(_parrafo(cierre.ConclusionRRLL if cierre else "Sin conclusión registrada.", styles["TextoNormal"]))

    contenido.append(Paragraph("DOCUMENTOS ANEXOS", styles["Subtitulo"]))

    if documentos:
        filas = [["Tipo", "Nombre archivo", "Observación"]]
        for documento in documentos:
            filas.append(
                [
                    _texto(documento.TipoDocumento),
                    _texto(documento.NombreArchivo),
                    _texto(documento.Observacion),
                ]
            )

        tabla_documentos = Table(
            filas,
            colWidths=[4 * cm, 7 * cm, 5 * cm],
        )
        tabla_documentos.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#d1fae5")),
                    ("GRID", (0, 0), (-1, -1), 0.5, colors.lightgrey),
                    ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                    ("FONTSIZE", (0, 0), (-1, -1), 8),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ]
            )
        )
        contenido.append(tabla_documentos)
    else:
        contenido.append(Paragraph("No existen documentos anexos.", styles["TextoNormal"]))

    contenido.append(Spacer(1, 18))
    contenido.append(
        Paragraph(
            f"Generado automaticamente por el Sistema Integral de Recursos Humanos - {datetime.now().strftime('%Y-%m-%d %H:%M')}",
            styles["TextoNormal"],
        )
    )

    doc.build(contenido)

    buffer.seek(0)

    return StreamingResponse(
        buffer,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'inline; filename="expediente_disciplinario_{id_proceso}.pdf"'
        },
    )


@router.get("/{id_proceso}", response_model=ProcesoDisciplinarioResponse)
def obtener_proceso_disciplinario(
    id_proceso: int,
    db: Session = Depends(get_db),
):
    proceso = (
        db.query(ProcesoDisciplinario)
        .filter(ProcesoDisciplinario.IdProcesoDisciplinario == id_proceso)
        .first()
    )

    if not proceso:
        raise HTTPException(status_code=404, detail="Proceso disciplinario no encontrado")

    return proceso


@router.put(
    "/{id_proceso}",
    response_model=ProcesoDisciplinarioResponse,
)
def actualizar_proceso_disciplinario(
    id_proceso: int,
    data: ProcesoDisciplinarioUpdate,
    db: Session = Depends(get_db),
):
    proceso = obtener_proceso_o_error(
        db=db,
        id_proceso=id_proceso,
    )

    # Si ya estaba cerrado antes de esta petición,
    # no se permite modificar ni reabrir el expediente.
    validar_proceso_modificable(proceso)

    datos_actualizados = data.model_dump(
        exclude_unset=True
    )

    if "EstadoProceso" in datos_actualizados:
        estado_nuevo = datos_actualizados.get(
            "EstadoProceso"
        )

        if estado_nuevo is not None:
            estado_nuevo = str(
                estado_nuevo
            ).strip().upper()

            if not estado_nuevo:
                raise HTTPException(
                    status_code=400,
                    detail=(
                        "El estado del proceso "
                        "no puede quedar vacío."
                    ),
                )

            proceso.EstadoProceso = estado_nuevo

    if "OrigenProceso" in datos_actualizados:
        origen_nuevo = datos_actualizados.get(
            "OrigenProceso"
        )

        proceso.OrigenProceso = (
            str(origen_nuevo).strip()
            if origen_nuevo is not None
            else None
        )

    if "UsuarioActualizacion" in datos_actualizados:
        usuario_actualizacion = datos_actualizados.get(
            "UsuarioActualizacion"
        )

        proceso.UsuarioActualizacion = (
            str(usuario_actualizacion).strip()
            if usuario_actualizacion is not None
            else None
        )

    proceso.FechaActualizacion = datetime.now()

    try:
        db.commit()
        db.refresh(proceso)

        return proceso

    except SQLAlchemyError as error:
        db.rollback()

        raise HTTPException(
            status_code=500,
            detail=(
                "No se pudo actualizar "
                "el proceso disciplinario."
            ),
        ) from error
