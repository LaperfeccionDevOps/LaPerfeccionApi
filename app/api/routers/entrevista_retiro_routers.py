from datetime import datetime, timezone, timedelta
import uuid
from typing import List, Optional
from io import BytesIO
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, status, Query
from fastapi.responses import StreamingResponse, FileResponse
from sqlalchemy.orm import Session
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from pydantic import BaseModel

from reportlab.lib.pagesizes import letter
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_LEFT, TA_CENTER
from reportlab.lib.units import inch
from reportlab.platypus import (
    SimpleDocTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
)

from infrastructure.db.deps import get_db

router = APIRouter(
    tags=["Entrevista Retiro"]
)

BASE_DIR = Path(__file__).resolve().parent
PDF_DIR = BASE_DIR / "entrevistas_pdf"
PDF_DIR.mkdir(parents=True, exist_ok=True)

# =========================================================
#   SCHEMAS
# =========================================================
class ValidarAccesoEntrevistaRequest(BaseModel):
    token: str
    numero_identificacion: str


class RespuestaItem(BaseModel):
    id_pregunta: int
    respuesta: str



class GuardarEntrevistaRequest(BaseModel):
    token: Optional[str] = None
    numero_identificacion: str
    respuestas: List[RespuestaItem]

class ValidarIdentificacionEntrevistaRequest(BaseModel):
    numero_identificacion: str


# =========================================================
#   HELPERS PDF
# =========================================================
def _valor_respuesta(r):
    return r.get("RespuestaOpcion") or r.get("RespuestaTexto") or ""


def _formatear_fecha_colombia(fecha):
    if not fecha:
        return ""

    try:
        tz_col = timezone(timedelta(hours=-5))

        if isinstance(fecha, str):
            fecha = fecha.strip().replace("Z", "+00:00")
            fecha_dt = datetime.fromisoformat(fecha)
        else:
            fecha_dt = fecha

        # ✅ Si viene sin zona horaria, asumimos que ya está en hora Colombia
        if fecha_dt.tzinfo is None:
            fecha_col = fecha_dt
        else:
            fecha_col = fecha_dt.astimezone(tz_col)

        fecha_str = fecha_col.strftime("%d/%m/%Y")
        hora_str = fecha_col.strftime("%I:%M %p").lower()
        hora_str = hora_str.lstrip("0")
        hora_str = hora_str.replace("am", "a. m.").replace("pm", "p. m.")

        return f"{fecha_str} {hora_str}"

    except Exception as e:
        print("Error formateando fecha Colombia:", repr(e))
        return str(fecha)


def _build_entrevista_pdf(cabecera: dict, respuestas: list[dict]) -> BytesIO:
    buffer = BytesIO()

    doc = SimpleDocTemplate(
        buffer,
        pagesize=letter,
        rightMargin=36,
        leftMargin=36,
        topMargin=36,
        bottomMargin=36,
        title="Entrevista de Retiro",
    )

    styles = getSampleStyleSheet()

    title_style = ParagraphStyle(
        "TitleCustom",
        parent=styles["Heading1"],
        alignment=TA_CENTER,
        fontSize=16,
        leading=20,
        spaceAfter=14,
    )

    subtitle_style = ParagraphStyle(
        "SubtitleCustom",
        parent=styles["Heading2"],
        alignment=TA_LEFT,
        fontSize=11,
        leading=14,
        textColor=colors.HexColor("#059669"),
        spaceAfter=8,
    )

    normal_style = ParagraphStyle(
        "NormalCustom",
        parent=styles["BodyText"],
        alignment=TA_LEFT,
        fontSize=9,
        leading=12,
    )

    question_style = ParagraphStyle(
        "QuestionCustom",
        parent=styles["BodyText"],
        alignment=TA_LEFT,
        fontSize=9,
        leading=12,
        textColor=colors.HexColor("#111827"),
    )

    answer_style = ParagraphStyle(
        "AnswerCustom",
        parent=styles["BodyText"],
        alignment=TA_LEFT,
        fontSize=9,
        leading=12,
        textColor=colors.HexColor("#374151"),
    )

    elements = []
    elements.append(Paragraph("ENTREVISTA DE RETIRO ASEOS LA PERFECCIÓN S.A.S", title_style))
    elements.append(Spacer(1, 8))

    nombre = (cabecera.get("NombreCompleto") or "").upper()
    documento = str(cabecera.get("NumeroIdentificacionConfirmada") or "").upper()
    fecha_envio = (_formatear_fecha_colombia(cabecera.get("FechaEnvio")) or "").upper()
    estado = (cabecera.get("Estado") or "").upper()

    cabecera_data = [
        ["Trabajador", nombre],
        ["Documento", str(documento)],
        ["Fecha envío", fecha_envio],
        ["Estado", estado],
    ]

    tabla_cabecera = Table(cabecera_data, colWidths=[1.6 * inch, 4.8 * inch])
    tabla_cabecera.setStyle(
        TableStyle([
            ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#e2e8f0")),
            ("TEXTCOLOR", (0, 0), (-1, -1), colors.black),
            ("FONTNAME", (0, 0), (-1, -1), "Helvetica"),
            ("FONTSIZE", (0, 0), (-1, -1), 9),
            ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#cbd5e1")),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("PADDING", (0, 0), (-1, -1), 6),
        ])
    )
    elements.append(tabla_cabecera)
    elements.append(Spacer(1, 14))

    descripcion_retiro = [r for r in respuestas if int(r.get("Orden", 0)) == 1]
    observaciones = [r for r in respuestas if 2 <= int(r.get("Orden", 0)) <= 9]
    dotacion = [r for r in respuestas if int(r.get("Orden", 0)) >= 10]

    def render_bloque(titulo: str, items: list[dict]):
        if not items:
            return

        elements.append(Paragraph(titulo, subtitle_style))
        elements.append(Spacer(1, 4))

        rows = [[
            Paragraph("<b>Pregunta</b>", normal_style),
            Paragraph("<b>Respuesta</b>", normal_style),
        ]]

        for r in items:
            pregunta = Paragraph(str(r.get("TextoPregunta", "")), question_style)
            respuesta = Paragraph(str(_valor_respuesta(r)), answer_style)
            rows.append([pregunta, respuesta])

        tabla = Table(rows, colWidths=[4.3 * inch, 2.3 * inch], repeatRows=1)
        tabla.setStyle(
            TableStyle([
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#10b981")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTNAME", (0, 0), (-1, -1), "Helvetica"),
                ("FONTSIZE", (0, 0), (-1, -1), 9),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#cbd5e1")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("PADDING", (0, 0), (-1, -1), 6),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f8fafc")]),
            ])
        )

        elements.append(tabla)
        elements.append(Spacer(1, 12))

    render_bloque("1. DESCRIPCIÓN DEL RETIRO", descripcion_retiro)
    render_bloque("2. OBSERVACIONES FINALES", observaciones)
    render_bloque("3. ENTREGA DE DOTACIÓN", dotacion)

    doc.build(elements)
    buffer.seek(0)
    return buffer


# =========================================================
#   GENERAR TOKEN DE ENTREVISTA DE RETIRO
# =========================================================
@router.post(
    "/entrevista-retiro/generar-token/{id_retiro_laboral}",
    summary="Generar token entrevista retiro"
)
def generar_token_entrevista_retiro(
    id_retiro_laboral: int,
    db: Session = Depends(get_db),
):
    try:
        retiro = db.execute(
            text("""
                SELECT
                    "IdRetiroLaboral",
                    "IdRegistroPersonal",
                    "Activo",
                    "TokenEntrevista",
                    "EstadoEntrevista"
                FROM "RetiroLaboral"
                WHERE "IdRetiroLaboral" = :id_retiro_laboral
                LIMIT 1
            """),
            {"id_retiro_laboral": id_retiro_laboral}
        ).mappings().first()

        if not retiro:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="No existe un retiro laboral con ese IdRetiroLaboral"
            )

        if retiro["Activo"] is False:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="El retiro laboral está inactivo y no permite generar token"
            )

        token = str(uuid.uuid4())
        fecha_generacion = datetime.utcnow()

        db.execute(
            text("""
                UPDATE "RetiroLaboral"
                SET
                    "TokenEntrevista" = :token,
                    "EstadoEntrevista" = :estado,
                    "FechaGeneracionToken" = :fecha_generacion,
                    "FechaActualizacion" = :fecha_actualizacion
                WHERE "IdRetiroLaboral" = :id_retiro_laboral
            """),
            {
                "token": token,
                "estado": "PENDIENTE",
                "fecha_generacion": fecha_generacion,
                "fecha_actualizacion": fecha_generacion,
                "id_retiro_laboral": id_retiro_laboral,
            }
        )

        db.commit()

        link_formulario = f"http://localhost:5173/entrevista-retiro?token={token}"

        return {
            "message": "Token generado correctamente",
            "data": {
                "IdRetiroLaboral": id_retiro_laboral,
                "IdRegistroPersonal": retiro["IdRegistroPersonal"],
                "TokenEntrevista": token,
                "EstadoEntrevista": "PENDIENTE",
                "FechaGeneracionToken": fecha_generacion.isoformat(),
                "LinkFormulario": link_formulario
            }
        }

    except HTTPException as e:
        raise e

    except SQLAlchemyError as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error SQL al generar token de entrevista: {str(e)}"
        )

    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error al generar token de entrevista: {str(e)}"
        )


# =========================================================
#   VALIDAR ACCESO A ENTREVISTA DE RETIRO
# =========================================================
@router.post(
    "/entrevista-retiro/validar-acceso",
    summary="Validar acceso a entrevista retiro"
)
def validar_acceso_entrevista_retiro(
    payload: ValidarAccesoEntrevistaRequest,
    db: Session = Depends(get_db),
):
    try:
        retiro = db.execute(
            text("""
                SELECT
                    rl."IdRetiroLaboral",
                    rl."IdRegistroPersonal",
                    rl."TokenEntrevista",
                    rl."EstadoEntrevista",
                    rp."NumeroIdentificacion",
                    rp."Nombres",
                    rp."Apellidos"
                FROM "RetiroLaboral" rl
                INNER JOIN "RegistroPersonal" rp
                    ON rp."IdRegistroPersonal" = rl."IdRegistroPersonal"
                WHERE rl."TokenEntrevista" = :token
                LIMIT 1
            """),
            {"token": payload.token}
        ).mappings().first()

        if not retiro:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Token de entrevista no válido"
            )

        if retiro["EstadoEntrevista"] != "PENDIENTE":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="La entrevista ya no se encuentra disponible"
            )

        numero_bd = str(retiro["NumeroIdentificacion"]).strip()
        numero_in = str(payload.numero_identificacion).strip()

        if numero_bd != numero_in:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="El número de identificación no corresponde al trabajador del retiro"
            )

        entrevista = db.execute(
            text("""
                SELECT 1
                FROM "EntrevistaRetiro"
                WHERE "IdRetiroLaboral" = :id_retiro_laboral
                LIMIT 1
            """),
            {"id_retiro_laboral": retiro["IdRetiroLaboral"]}
        ).first()

        if entrevista:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="La entrevista de retiro ya fue diligenciada"
            )

        nombre_completo = f'{retiro["Nombres"]} {retiro["Apellidos"]}'.strip()

        return {
            "message": "Acceso validado correctamente",
            "data": {
                "IdRetiroLaboral": retiro["IdRetiroLaboral"],
                "IdRegistroPersonal": retiro["IdRegistroPersonal"],
                "NumeroIdentificacion": retiro["NumeroIdentificacion"],
                "NombreCompleto": nombre_completo,
                "EstadoEntrevista": retiro["EstadoEntrevista"],
                "PuedeContinuar": True
            }
        }

    except HTTPException as e:
        raise e

    except SQLAlchemyError as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error SQL al validar acceso de entrevista: {str(e)}"
        )

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error al validar acceso de entrevista: {str(e)}"
        )


@router.post(
    "/entrevista-retiro/validar-identificacion",
    summary="Validar trabajador para entrevista de retiro por identificación"
)
def validar_identificacion_entrevista_retiro(
    payload: ValidarIdentificacionEntrevistaRequest,
    db: Session = Depends(get_db),
):
    try:
        numero_in = str(payload.numero_identificacion).strip()

        trabajador = db.execute(
            text("""
                SELECT
                    rp."IdRegistroPersonal",
                    rp."NumeroIdentificacion",
                    rp."Nombres",
                    rp."Apellidos"
                FROM "RegistroPersonal" rp
                WHERE REPLACE(REPLACE(TRIM(rp."NumeroIdentificacion"),'.',''),' ','') = :numero_identificacion
                LIMIT 1
            """),
            {"numero_identificacion": numero_in}
        ).mappings().first()

        if not trabajador:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="No se encontró un trabajador con ese número de identificación"
            )

        retiro_activo = db.execute(
            text("""
                SELECT
                    rl."IdRetiroLaboral",
                    rl."TokenEntrevista",
                    rl."EstadoEntrevista",
                    rl."Activo",
                    rl."FechaProceso"
                FROM "RetiroLaboral" rl
                WHERE rl."IdRegistroPersonal" = :id_registro_personal
                  AND rl."Activo" = TRUE
                ORDER BY rl."IdRetiroLaboral" DESC
                LIMIT 1
            """),
            {"id_registro_personal": trabajador["IdRegistroPersonal"]}
        ).mappings().first()

        nombre_completo = f'{trabajador["Nombres"]} {trabajador["Apellidos"]}'.strip()

        return {
            "message": "Identificación validada correctamente",
            "data": {
                "IdRegistroPersonal": trabajador["IdRegistroPersonal"],
                "NumeroIdentificacion": str(trabajador["NumeroIdentificacion"]).strip(),
                "NombreCompleto": nombre_completo,
                "TieneRetiroActivo": bool(retiro_activo),
                "IdRetiroLaboral": retiro_activo["IdRetiroLaboral"] if retiro_activo else None,
                "EstadoEntrevista": retiro_activo["EstadoEntrevista"] if retiro_activo else None,
                "TokenEntrevista": retiro_activo["TokenEntrevista"] if retiro_activo else None
            }
        }

    except HTTPException as e:
        raise e

    except SQLAlchemyError as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error SQL al validar identificación de entrevista: {str(e)}"
        )

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error al validar identificación de entrevista: {str(e)}"
        )


# =========================================================
#   CONSULTAR FORMULARIO PÚBLICO POR TOKEN
# =========================================================
@router.get(
    "/entrevista-retiro/formulario-por-token",
    summary="Consultar formulario público de entrevista de retiro por token"
)
def consultar_formulario_entrevista_por_token(
    token: str,
    db: Session = Depends(get_db),
):
    try:
        retiro = db.execute(
            text("""
                SELECT
                    rl."IdRetiroLaboral",
                    rl."IdRegistroPersonal",
                    rl."TokenEntrevista",
                    rl."EstadoEntrevista",
                    rp."NumeroIdentificacion",
                    rp."Nombres",
                    rp."Apellidos"
                FROM "RetiroLaboral" rl
                INNER JOIN "RegistroPersonal" rp
                    ON rp."IdRegistroPersonal" = rl."IdRegistroPersonal"
                WHERE rl."TokenEntrevista" = :token
                LIMIT 1
            """),
            {"token": token}
        ).mappings().first()

        if not retiro:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Token de entrevista no válido"
            )

        if retiro["EstadoEntrevista"] != "PENDIENTE":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="La entrevista ya no se encuentra disponible"
            )

        entrevista_existente = db.execute(
            text("""
                SELECT 1
                FROM "EntrevistaRetiro"
                WHERE "IdRetiroLaboral" = :id_retiro_laboral
                LIMIT 1
            """),
            {"id_retiro_laboral": retiro["IdRetiroLaboral"]}
        ).first()

        if entrevista_existente:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="La entrevista de retiro ya fue diligenciada"
            )

        preguntas = db.execute(
            text("""
                SELECT
                    "IdPreguntaEntrevistaRetiro",
                    "CodigoPregunta",
                    "TextoPregunta",
                    "TipoRespuesta",
                    "EsObligatoria",
                    "Orden",
                    "Activa"
                FROM "EntrevistaRetiroPregunta"
                WHERE "Activa" = TRUE
                ORDER BY "Orden" ASC
            """)
        ).mappings().all()

        nombre_completo = f'{retiro["Nombres"]} {retiro["Apellidos"]}'.strip()

        return {
            "message": "Formulario consultado correctamente",
            "data": {
                "IdRetiroLaboral": retiro["IdRetiroLaboral"],
                "IdRegistroPersonal": retiro["IdRegistroPersonal"],
                "NumeroIdentificacion": str(retiro["NumeroIdentificacion"]).strip(),
                "NombreCompleto": nombre_completo,
                "EstadoEntrevista": retiro["EstadoEntrevista"],
                "Preguntas": [dict(p) for p in preguntas]
            }
        }

    except HTTPException as e:
        raise e

    except SQLAlchemyError as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error SQL al consultar formulario por token: {str(e)}"
        )

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error al consultar formulario por token: {str(e)}"
        )


# =========================================================
#   LISTAR PREGUNTAS DE ENTREVISTA DE RETIRO
# =========================================================
@router.get(
    "/entrevista-retiro/preguntas",
    summary="Listar preguntas de entrevista retiro"
)
def listar_preguntas_entrevista_retiro(
    db: Session = Depends(get_db),
):
    try:
        preguntas = db.execute(
            text("""
                SELECT
                    "IdPreguntaEntrevistaRetiro",
                    "CodigoPregunta",
                    "TextoPregunta",
                    "TipoRespuesta",
                    "EsObligatoria",
                    "Orden",
                    "Activa"
                FROM "EntrevistaRetiroPregunta"
                WHERE "Activa" = TRUE
                ORDER BY "Orden" ASC
            """)
        ).mappings().all()

        return {
            "message": "Preguntas consultadas correctamente",
            "data": [dict(p) for p in preguntas]
        }

    except SQLAlchemyError as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error SQL al consultar preguntas de entrevista: {str(e)}"
        )

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error al consultar preguntas de entrevista: {str(e)}"
        )


# =========================================================
#   GUARDAR ENTREVISTA DE RETIRO
# =========================================================
@router.post(
    "/entrevista-retiro/guardar",
    summary="Guardar entrevista de retiro"
)
def guardar_entrevista_retiro(
    payload: GuardarEntrevistaRequest,
    db: Session = Depends(get_db),
):
    try:
        numero_in = str(payload.numero_identificacion).strip()

        # =========================================
        # VALIDACIÓN: máximo 5 entrevistas
        # =========================================
        total_entrevistas = db.execute(
            text("""
                SELECT COUNT(*) AS total
                FROM "EntrevistaRetiro"
                WHERE "NumeroIdentificacionConfirmada" = :numero_identificacion
            """),
            {"numero_identificacion": numero_in}
        ).scalar()

        if total_entrevistas is not None and int(total_entrevistas) >= 5:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="El trabajador ya alcanzó el máximo de 5 entrevistas de retiro."
            )

        # =========================================
        # VALIDAR QUE ENVÍE RESPUESTAS
        # =========================================
        if not payload.respuestas:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Debe enviar al menos una respuesta"
            )

        # =========================================
        # OBTENER TRABAJADOR
        # =========================================
        trabajador = db.execute(
            text("""
                SELECT
                    rp."IdRegistroPersonal",
                    rp."NumeroIdentificacion"
                FROM "RegistroPersonal" rp
                WHERE REPLACE(REPLACE(TRIM(rp."NumeroIdentificacion"),'.',''),' ','') = :numero_identificacion
                LIMIT 1
            """),
            {"numero_identificacion": numero_in}
        ).mappings().first()

        if not trabajador:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Identificación incorrecta"
            )

        id_retiro_laboral = None

        # =========================================
        # CASO 1: CON TOKEN (flujo actual)
        # =========================================
        if payload.token:
            retiro = db.execute(
                text("""
                    SELECT
                        rl."IdRetiroLaboral",
                        rp."NumeroIdentificacion"
                    FROM "RetiroLaboral" rl
                    INNER JOIN "RegistroPersonal" rp
                        ON rp."IdRegistroPersonal" = rl."IdRegistroPersonal"
                    WHERE rl."TokenEntrevista" = :token
                    LIMIT 1
                """),
                {"token": payload.token}
            ).mappings().first()

            if not retiro:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Token inválido"
                )

            numero_bd = str(retiro["NumeroIdentificacion"]).strip()

            if numero_bd != numero_in:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Identificación incorrecta"
                )

            existe = db.execute(
                text("""
                    SELECT 1
                    FROM "EntrevistaRetiro"
                    WHERE "IdRetiroLaboral" = :id_retiro_laboral
                    LIMIT 1
                """),
                {"id_retiro_laboral": retiro["IdRetiroLaboral"]}
            ).first()

            if existe:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="La entrevista ya fue diligenciada"
                )

            id_retiro_laboral = retiro["IdRetiroLaboral"]

        # =========================================
        # INSERT ENTREVISTA
        # =========================================
        entrevista = db.execute(
            text("""
                INSERT INTO "EntrevistaRetiro" (
                    "IdRetiroLaboral",
                    "IdRegistroPersonal",
                    "NumeroIdentificacionConfirmada",
                    "Estado",
                    "FechaCreacion"
                )
                VALUES (
                    :id_retiro_laboral,
                    :id_registro_personal,
                    :numero_identificacion,
                    :estado,
                    NOW()
                )
                RETURNING "IdEntrevistaRetiro"
            """),
            {
                "id_retiro_laboral": id_retiro_laboral,
                "id_registro_personal": trabajador["IdRegistroPersonal"],
                "numero_identificacion": numero_in,
                "estado": "RESPONDIDA" if id_retiro_laboral else "PENDIENTE_VINCULAR"
            }
        ).mappings().first()

        id_entrevista = entrevista["IdEntrevistaRetiro"]

        # =========================================
        # VALIDAR PREGUNTAS
        # =========================================
        ids_preguntas = [r.id_pregunta for r in payload.respuestas]

        preguntas_db = db.execute(
            text("""
                SELECT
                    "IdPreguntaEntrevistaRetiro",
                    "TipoRespuesta",
                    "Activa"
                FROM "EntrevistaRetiroPregunta"
                WHERE "IdPreguntaEntrevistaRetiro" = ANY(:ids_preguntas)
            """),
            {"ids_preguntas": ids_preguntas}
        ).mappings().all()

        mapa_preguntas = {
            p["IdPreguntaEntrevistaRetiro"]: dict(p)
            for p in preguntas_db
        }

        for r in payload.respuestas:
            pregunta = mapa_preguntas.get(r.id_pregunta)
            if not pregunta:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"La pregunta {r.id_pregunta} no existe"
                )
            if pregunta["Activa"] is False:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"La pregunta {r.id_pregunta} está inactiva"
                )

        now = datetime.utcnow()

        # =========================================
        # INSERT RESPUESTAS
        # =========================================
        for r in payload.respuestas:
            pregunta = mapa_preguntas[r.id_pregunta]
            tipo_respuesta = str(pregunta["TipoRespuesta"]).strip().upper()
            valor = r.respuesta.strip() if r.respuesta else ""

            respuesta_texto = None
            respuesta_opcion = None

            if tipo_respuesta in ("SI_NO", "OPCION"):
                respuesta_opcion = valor
            else:
                respuesta_texto = valor

            db.execute(
                text("""
                    INSERT INTO "EntrevistaRetiroRespuesta"
                    (
                        "IdEntrevistaRetiro",
                        "IdPreguntaEntrevistaRetiro",
                        "RespuestaTexto",
                        "RespuestaOpcion",
                        "FechaRegistro"
                    )
                    VALUES
                    (
                        :id_entrevista,
                        :id_pregunta,
                        :respuesta_texto,
                        :respuesta_opcion,
                        :fecha_registro
                    )
                """),
                {
                    "id_entrevista": id_entrevista,
                    "id_pregunta": r.id_pregunta,
                    "respuesta_texto": respuesta_texto,
                    "respuesta_opcion": respuesta_opcion,
                    "fecha_registro": now,
                }
            )

        db.commit()

        return {
            "message": "Entrevista guardada correctamente",
            "data": {
                "IdEntrevistaRetiro": id_entrevista,
                "IdRetiroLaboral": id_retiro_laboral,
                "EstadoEntrevista": "RESPONDIDA" if id_retiro_laboral else "PENDIENTE_VINCULAR"
            }
        }

    except HTTPException as e:
        raise e

    except SQLAlchemyError as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error SQL al guardar entrevista: {str(e)}"
        )

    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error al guardar entrevista: {str(e)}"
        )

# =========================================================
#   CONSULTAR ENTREVISTA DE RETIRO POR ID RETIRO LABORAL
# =========================================================
@router.get(
    "/entrevista-retiro/{id_retiro_laboral}",
    summary="Consultar entrevista de retiro por IdRetiroLaboral"
)
def consultar_entrevista_retiro_por_retiro(
    id_retiro_laboral: int,
    db: Session = Depends(get_db),
):
    try:
        cabecera = db.execute(
            text("""
                SELECT
                    er."IdEntrevistaRetiro",
                    er."IdRetiroLaboral",
                    er."IdRegistroPersonal",
                    er."NumeroIdentificacionConfirmada",
                    er."FechaEnvio",
                    er."Estado",
                    er."PdfGenerado",
                    er."RutaPdf",
                    er."FechaCreacion",
                    rp."Nombres",
                    rp."Apellidos"
                FROM "EntrevistaRetiro" er
                INNER JOIN "RegistroPersonal" rp
                    ON rp."IdRegistroPersonal" = er."IdRegistroPersonal"
                WHERE er."IdRetiroLaboral" = :id_retiro_laboral
                ORDER BY er."FechaCreacion" DESC, er."IdEntrevistaRetiro" DESC
                LIMIT 1
            """),
            {"id_retiro_laboral": id_retiro_laboral}
        ).mappings().first()

        if not cabecera:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="No existe entrevista de retiro para ese IdRetiroLaboral"
            )

        respuestas = db.execute(
            text("""
                SELECT
                    r."IdRespuestaEntrevistaRetiro",
                    r."IdEntrevistaRetiro",
                    r."IdPreguntaEntrevistaRetiro",
                    p."CodigoPregunta",
                    p."TextoPregunta",
                    p."TipoRespuesta",
                    p."Orden",
                    r."RespuestaTexto",
                    r."RespuestaOpcion",
                    r."FechaRegistro"
                FROM "EntrevistaRetiroRespuesta" r
                INNER JOIN "EntrevistaRetiroPregunta" p
                    ON p."IdPreguntaEntrevistaRetiro" = r."IdPreguntaEntrevistaRetiro"
                WHERE r."IdEntrevistaRetiro" = :id_entrevista
                ORDER BY p."Orden" ASC
            """),
            {"id_entrevista": cabecera["IdEntrevistaRetiro"]}
        ).mappings().all()

        nombre_completo = f'{cabecera["Nombres"]} {cabecera["Apellidos"]}'.strip()

        data_cabecera = dict(cabecera)
        data_cabecera["NombreCompleto"] = nombre_completo

        return {
            "message": "Entrevista consultada correctamente",
            "data": {
                "cabecera": data_cabecera,
                "respuestas": [dict(r) for r in respuestas]
            }
        }

    except HTTPException as e:
        raise e

    except SQLAlchemyError as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error SQL al consultar entrevista: {str(e)}"
        )

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error al consultar entrevista: {str(e)}"
        )
    

@router.get(
    "/entrevista-retiro/historial/{id_registro_personal}",
    summary="Consultar historial de entrevistas de retiro por trabajador"
)
def consultar_historial_entrevista_retiro(
    id_registro_personal: int,
    db: Session = Depends(get_db),
):
    try:
        historial = db.execute(
            text("""
                SELECT
                    er."IdEntrevistaRetiro",
                    er."IdRetiroLaboral",
                    er."IdRegistroPersonal",
                    er."NumeroIdentificacionConfirmada",
                    er."FechaEnvio",
                    er."Estado",
                    er."PdfGenerado",
                    er."RutaPdf",
                    er."FechaCreacion",
                    rp."Nombres",
                    rp."Apellidos"
                FROM public."EntrevistaRetiro" er
                INNER JOIN public."RegistroPersonal" rp
                    ON rp."IdRegistroPersonal" = er."IdRegistroPersonal"
                WHERE er."IdRegistroPersonal" = :id_registro_personal
                ORDER BY er."FechaCreacion" DESC, er."IdEntrevistaRetiro" DESC
            """),
            {"id_registro_personal": id_registro_personal}
        ).mappings().all()

        data = []
        for row in historial:
            item = dict(row)
            item["NombreCompleto"] = f'{row["Nombres"]} {row["Apellidos"]}'.strip()
            data.append(item)

        return {
            "message": "Historial de entrevistas consultado correctamente",
            "total": len(data),
            "data": data
        }

    except SQLAlchemyError as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error SQL al consultar historial de entrevistas: {str(e)}"
        )

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error al consultar historial de entrevistas: {str(e)}"
        )


# =========================================================
#   GENERAR / VISUALIZAR PDF DE ENTREVISTA DE RETIRO
# =========================================================
@router.get(
    "/entrevista-retiro/{id_retiro_laboral}/pdf",
    summary="Generar/visualizar PDF de entrevista de retiro"
)
def generar_pdf_entrevista_retiro(
    id_retiro_laboral: int,
    descargar: bool = Query(False),
    db: Session = Depends(get_db),
):
    try:
        cabecera = db.execute(
            text("""
                SELECT
                    er."IdEntrevistaRetiro",
                    er."IdRetiroLaboral",
                    er."IdRegistroPersonal",
                    er."NumeroIdentificacionConfirmada",
                    er."FechaEnvio",
                    er."Estado",
                    er."PdfGenerado",
                    er."RutaPdf",
                    er."FechaCreacion",
                    rp."Nombres",
                    rp."Apellidos"
                FROM "EntrevistaRetiro" er
                INNER JOIN "RegistroPersonal" rp
                    ON rp."IdRegistroPersonal" = er."IdRegistroPersonal"
                WHERE er."IdRetiroLaboral" = :id_retiro_laboral
                ORDER BY er."FechaCreacion" DESC, er."IdEntrevistaRetiro" DESC
                LIMIT 1
            """),
            {"id_retiro_laboral": id_retiro_laboral}
        ).mappings().first()

        if not cabecera:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="No existe entrevista de retiro para ese IdRetiroLaboral"
            )

        # ✅ Si ya existe el PDF en disco de la última entrevista, devolverlo sin regenerar
        ruta_pdf_guardada = cabecera.get("RutaPdf")
        if ruta_pdf_guardada:
            archivo_pdf = Path(ruta_pdf_guardada)
            if archivo_pdf.exists() and archivo_pdf.is_file():
                return FileResponse(
                    path=str(archivo_pdf),
                    media_type="application/pdf",
                    filename=archivo_pdf.name,
                    headers={
                        "Content-Disposition": (
                            f'attachment; filename="{archivo_pdf.name}"'
                            if descargar
                            else f'inline; filename="{archivo_pdf.name}"'
                        )
                    }
                )

        respuestas = db.execute(
            text("""
                SELECT
                    r."IdRespuestaEntrevistaRetiro",
                    r."IdEntrevistaRetiro",
                    r."IdPreguntaEntrevistaRetiro",
                    p."CodigoPregunta",
                    p."TextoPregunta",
                    p."TipoRespuesta",
                    p."Orden",
                    r."RespuestaTexto",
                    r."RespuestaOpcion",
                    r."FechaRegistro"
                FROM "EntrevistaRetiroRespuesta" r
                INNER JOIN "EntrevistaRetiroPregunta" p
                    ON p."IdPreguntaEntrevistaRetiro" = r."IdPreguntaEntrevistaRetiro"
                WHERE r."IdEntrevistaRetiro" = :id_entrevista
                ORDER BY p."Orden" ASC
            """),
            {"id_entrevista": cabecera["IdEntrevistaRetiro"]}
        ).mappings().all()

        nombre_completo = f'{cabecera["Nombres"]} {cabecera["Apellidos"]}'.strip()

        data_cabecera = dict(cabecera)
        data_cabecera["NombreCompleto"] = nombre_completo

        pdf_buffer = _build_entrevista_pdf(data_cabecera, [dict(r) for r in respuestas])

        # ✅ PDF por entrevista, no por retiro
        nombre_archivo = f'entrevista_retiro_{cabecera["IdEntrevistaRetiro"]}.pdf'
        ruta_pdf = PDF_DIR / nombre_archivo

        with open(ruta_pdf, "wb") as f:
            f.write(pdf_buffer.getvalue())

        db.execute(
            text("""
                UPDATE "EntrevistaRetiro"
                SET
                    "PdfGenerado" = TRUE,
                    "RutaPdf" = :ruta_pdf
                WHERE "IdEntrevistaRetiro" = :id_entrevista
            """),
            {
                "ruta_pdf": str(ruta_pdf),
                "id_entrevista": cabecera["IdEntrevistaRetiro"]
            }
        )
        db.commit()

        pdf_buffer.seek(0)

        return StreamingResponse(
            pdf_buffer,
            media_type="application/pdf",
            headers={
                "Content-Disposition": (
                    f'attachment; filename="{nombre_archivo}"'
                    if descargar
                    else f'inline; filename="{nombre_archivo}"'
                )
            }
        )

    except HTTPException as e:
        raise e

    except SQLAlchemyError as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error SQL al generar PDF de entrevista: {str(e)}"
        )

    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error al generar PDF de entrevista: {str(e)}"
        )