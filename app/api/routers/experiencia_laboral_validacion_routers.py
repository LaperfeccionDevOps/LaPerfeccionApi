from typing import List

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session
from sqlalchemy import text
import pdfkit
import base64

from infrastructure.db.deps import get_db
from services.experiencia_laboral_validacion_service import ExperienciaLaboralValidacionService
from domain.schemas.experiencia_laboral_validacion_schema import ExperienciaLaboralValidacionSchema
from domain.models.experiencia_laboral_validacion import ExperienciaLaboralValidacion


router = APIRouter(
    prefix="/api/experiencia-laboral-validacion",
    tags=["experiencia-laboral-validacion"],
)

service = ExperienciaLaboralValidacionService()


@router.get(
    "/experiencia/{id_experiencia_laboral}",
    response_model=List[ExperienciaLaboralValidacionSchema],
)
def listar_validaciones_por_experiencia(
    id_experiencia_laboral: int,
    db: Session = Depends(get_db),
):
    return service.listar_por_experiencia(db, id_experiencia_laboral)


@router.get(
    "/{id_validacion}",
    response_model=ExperienciaLaboralValidacionSchema,
)
def obtener_validacion_por_id(
    id_validacion: int,
    db: Session = Depends(get_db),
):
    data = service.obtener_por_id(db, id_validacion)
    if not data:
        raise HTTPException(status_code=404, detail="No existe la validación con ese IdValidacion")
    return data


@router.post("/insertar", status_code=201)
def insertar_validacion(
    payload: ExperienciaLaboralValidacionSchema,
    db: Session = Depends(get_db),
):
    existe = db.query(ExperienciaLaboralValidacion).filter(
        ExperienciaLaboralValidacion.IdExperienciaLaboral == payload.IdExperienciaLaboral
    ).first()

    if existe:
        for key, value in payload.model_dump(exclude_none=True).items():
            setattr(existe, key, value)
        db.commit()
        db.refresh(existe)
        return {"ok": True, "msg": "Validación actualizada", "IdValidacion": existe.IdValidacion}

    nuevo = ExperienciaLaboralValidacion(**payload.model_dump(exclude_none=True))
    db.add(nuevo)
    db.commit()
    db.refresh(nuevo)
    return {"ok": True, "IdValidacion": nuevo.IdValidacion}


@router.post("/generar-consolidado/{id_registro_personal}")
def generar_consolidado_referencias(
    id_registro_personal: int,
    db: Session = Depends(get_db),
):
    try:
        q = text("""
            SELECT
                el."IdExperienciaLaboral",
                el."Compania",
                el."Cargo",
                el."Funciones",
                el."JefeInmediato",
                el."TelefonoJefe",
                el."TiempoDuracion",
                ev."Concepto",
                ev."DesempenoReportado",
                ev."MotivoRetiroReal",
                ev."PersonaQueReferencia",
                ev."Telefono",
                ev."ReferenciadoPor",
                ev."Eps",
                ev."FechaExpedicionDocumentoIdentidad",
                ev."ComentariosDelReferenciado",
                ev."CreadoEn",
                ev."ActualizadoEn"
            FROM "ExperienciaLaboral" el
            INNER JOIN "ExperienciaLaboralValidacion" ev
                ON ev."IdExperienciaLaboral" = el."IdExperienciaLaboral"
            WHERE el."IdRegistroPersonal" = :id_registro_personal
            ORDER BY el."IdExperienciaLaboral" ASC
        """)
        rows = db.execute(q, {"id_registro_personal": id_registro_personal}).mappings().all()

        referencias = [dict(r) for r in rows]

        if not referencias:
            return {
                "ok": False,
                "detail": "No hay referencias laborales validadas para este candidato."
            }

        bloques_html = ""
        for i, ref in enumerate(referencias, start=1):
            bloques_html += f"""
                <div style="margin-bottom: 30px; page-break-inside: avoid;">
                    <h2 style="font-size: 16px; margin-bottom: 10px;">Referencia laboral {i}</h2>
                    <p><strong>Empresa:</strong> {ref.get('Compania') or ''}</p>
                    <p><strong>Cargo:</strong> {ref.get('Cargo') or ''}</p>
                    <p><strong>Funciones:</strong> {ref.get('Funciones') or ''}</p>
                    <p><strong>Jefe inmediato:</strong> {ref.get('JefeInmediato') or ''}</p>
                    <p><strong>Teléfono jefe:</strong> {ref.get('TelefonoJefe') or ''}</p>
                    <p><strong>Tiempo duración:</strong> {ref.get('TiempoDuracion') or ''}</p>
                    <p><strong>Concepto:</strong> {ref.get('Concepto') or ''}</p>
                    <p><strong>Desempeño reportado:</strong> {ref.get('DesempenoReportado') or ''}</p>
                    <p><strong>Motivo retiro real:</strong> {ref.get('MotivoRetiroReal') or ''}</p>
                    <p><strong>Persona que referencia:</strong> {ref.get('PersonaQueReferencia') or ''}</p>
                    <p><strong>Teléfono referencia:</strong> {ref.get('Telefono') or ''}</p>
                    <p><strong>Referenciado por:</strong> {ref.get('ReferenciadoPor') or ''}</p>
                    <p><strong>EPS:</strong> {ref.get('Eps') or ''}</p>
                    <p><strong>Fecha expedición documento:</strong> {ref.get('FechaExpedicionDocumentoIdentidad') or ''}</p>
                    <p><strong>Comentarios del referenciado:</strong> {ref.get('ComentariosDelReferenciado') or ''}</p>
                </div>
            """

        html_content = f"""
            <html>
                <head>
                    <meta charset="utf-8">
                    <style>
                        body {{
                            font-family: Arial, sans-serif;
                            font-size: 12px;
                            margin: 30px;
                        }}
                        h1 {{
                            text-align: center;
                            margin-bottom: 25px;
                        }}
                        p {{
                            margin: 4px 0;
                        }}
                    </style>
                </head>
                <body>
                    <h1>Confirmación de referencias laborales</h1>
                    {bloques_html}
                </body>
            </html>
        """

        wkhtmltopdf_path = r"C:\Program Files\wkhtmltopdf\bin\wkhtmltopdf.exe"
        config = pdfkit.configuration(wkhtmltopdf=wkhtmltopdf_path)
        pdf_bytes = pdfkit.from_string(html_content, False, configuration=config)
        pdf_base64 = base64.b64encode(pdf_bytes).decode("utf-8")

        return {"ok": True, "pdf_base64": pdf_base64}

    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={"ok": False, "detail": str(e)}
        )