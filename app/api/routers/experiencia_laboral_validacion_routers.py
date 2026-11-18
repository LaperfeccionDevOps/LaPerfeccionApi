from typing import List

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session
from sqlalchemy import text
import pdfkit
import base64
from html import escape

from api.routers.descargar_documentos_routers import (
    obtener_empresa_contratante,
    obtener_empresa_contratante_desde_rq,
    preparar_datos_empresa,
)

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

        # El endpoint histórico recibe IdRegistroPersonal, no IdVinculacionLaboral.
        # Se identifica el último ciclo laboral para seleccionar el logo.
        # Si un candidato tiene varios ciclos, se debe validar que este sea
        # el ciclo que corresponde al documento solicitado.
        ciclo = db.execute(text("""
            SELECT vl."IdVinculacionLaboral"
            FROM public."VinculacionLaboral" vl
            WHERE vl."IdRegistroPersonal" = :id_registro_personal
            ORDER BY vl."IdVinculacionLaboral" DESC
            LIMIT 1
        """), {"id_registro_personal": id_registro_personal}).mappings().first()

        if ciclo:
            # Mantiene la ruta existente de quienes ya tienen un ciclo laboral.
            empresa = obtener_empresa_contratante(db, ciclo["IdVinculacionLaboral"])
        else:
            # Aspirantes nuevos: la empresa se consulta en la RQ activa,
            # sin crear una vinculación ni confiar en datos del frontend.
            # El servicio existente valida que haya una única RQ activa.
            empresa = obtener_empresa_contratante_desde_rq(db, id_registro_personal)
        datos_empresa = preparar_datos_empresa({}, empresa)
        logo = datos_empresa.get("LOGO", "")
        nombre_empresa = escape(str(datos_empresa.get("EMPRESA_NOMBRE") or ""))

        def valor(ref, campo):
            dato = ref.get(campo)
            if dato is None:
                return ""
            if hasattr(dato, "strftime"):
                dato = dato.strftime("%Y-%m-%d")
            return escape(str(dato))

        def fila(etiqueta, contenido):
            return f'<tr><td class="etiqueta">{etiqueta}</td><td>{contenido}</td></tr>'

        bloques_html = ""
        for i, ref in enumerate(referencias, start=1):
            campos = [
                ("EMPRESA REFERENCIADA", "Compania"),
                ("CARGO", "Cargo"),
                ("FUNCIONES", "Funciones"),
                ("JEFE INMEDIATO", "JefeInmediato"),
                ("TELÉFONO JEFE", "TelefonoJefe"),
                ("TIEMPO LABORADO", "TiempoDuracion"),
                ("CONCEPTO FINAL", "Concepto"),
                ("EVALUACIÓN GENERAL DEL DESEMPEÑO", "DesempenoReportado"),
                ("MOTIVO DEL RETIRO", "MotivoRetiroReal"),
                ("PERSONA QUE DA LA REFERENCIA", "PersonaQueReferencia"),
                ("TELÉFONO DE LA REFERENCIA", "Telefono"),
                ("REFERENCIADO POR", "ReferenciadoPor"),
                ("EPS", "Eps"),
                ("FECHA EXPEDICIÓN DOCUMENTO", "FechaExpedicionDocumentoIdentidad"),
                ("COMENTARIOS DEL REFERENCIADOR", "ComentariosDelReferenciado"),
            ]
            filas = "".join(fila(etiqueta, valor(ref, campo)) for etiqueta, campo in campos)
            # Cada referencia inicia en una hoja nueva, con su propio logo y título.
            # Sin ruptura antes de la primera para evitar una página vacía.
            salto_pagina = "always" if i > 1 else "auto"
            bloques_html += f"""
                <div class="referencia" style="page-break-before: {salto_pagina};">
                    <div class="encabezado"><img class="logo" src="{logo}" alt="{nombre_empresa}"></div>
                    <h1>CONFIRMACIÓN REFERENCIAS - F-GTH03 V.03</h1>
                    <table class="cabecera-tabla">
                        <tr>
                            <th>TIPO DE REFERENCIAS:</th><td>LABORALES</td>
                            <th>N.º REFERENCIA:</th><td>{i}</td>
                        </tr>
                    </table>
                    <table class="datos-tabla">{filas}</table>
                </div>
            """

        html_content = f"""
            <!DOCTYPE html>
            <html lang="es">
                <head>
                    <meta charset="utf-8">
                    <style>
                        body {{ font-family: "DejaVu Sans", Arial, sans-serif; font-size: 12px; line-height: 1.5; color: #111; margin: 22px; }}
                        .logo {{ max-height: 100px; max-width: 220px; height: auto; width: auto; }}
                        .encabezado {{ height: 120px; }}
                        h1 {{ font-size: 15px; line-height: 1.4; text-align: center; margin: 8px 0 20px; }}
                        table {{ width: 100%; border-collapse: collapse; table-layout: fixed; margin-bottom: 10px; }}
                        th, td {{ border: 1px solid #111; padding: 8px 9px; vertical-align: top; line-height: 1.5; overflow-wrap: break-word; word-wrap: break-word; }}
                        th {{ font-weight: bold; text-align: left; background: #f1f1f1; }}
                        .cabecera-tabla th {{ width: 22%; }}
                        .cabecera-tabla td {{ width: 28%; }}
                        .etiqueta {{ font-weight: bold; font-size: 11px; letter-spacing: 0.1px; width: 35%; background: #f6f6f6; }}
                        .referencia {{ margin-bottom: 24px; page-break-inside: avoid; }}
                        .datos-tabla td {{ white-space: pre-wrap; }}
                    </style>
                </head>
                <body>
                    {bloques_html}
                </body>
            </html>
        """

        wkhtmltopdf_path = r"C:\Program Files\wkhtmltopdf\bin\wkhtmltopdf.exe"
        config = pdfkit.configuration(wkhtmltopdf=wkhtmltopdf_path)
        pdf_bytes = pdfkit.from_string(html_content, False, configuration=config)
        pdf_base64 = base64.b64encode(pdf_bytes).decode("utf-8")

        return {"ok": True, "pdf_base64": pdf_base64}

    except HTTPException:
        raise

    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={"ok": False, "detail": str(e)}
        )