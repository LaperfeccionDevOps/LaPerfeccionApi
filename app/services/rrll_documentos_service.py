from pathlib import Path
from datetime import datetime
from docx import Document
from sqlalchemy import text


BASE_DIR = Path(__file__).resolve().parents[1]
TEMPLATE_PRIMER_LLAMADO = BASE_DIR / "templates" / "rrll" / "abandono" / "primer_llamado_abandono.docx"
TIPO_DOC_PRIMER_LLAMADO = 13

TEMPLATE_SEGUNDO_LLAMADO = BASE_DIR / "templates" / "rrll" / "abandono" / "segundo_llamado_abandono.docx"
TIPO_DOC_SEGUNDO_LLAMADO = 14

OUTPUT_DIR = BASE_DIR / "storage" / "rrll" / "generados"


def _replace_text_in_paragraph(paragraph, replacements: dict):
    for key, value in replacements.items():
        if key in paragraph.text:
            paragraph.text = paragraph.text.replace(key, str(value))


def _replace_text_in_table(table, replacements: dict):
    for row in table.rows:
        for cell in row.cells:
            for paragraph in cell.paragraphs:
                _replace_text_in_paragraph(paragraph, replacements)


def obtener_datos_primer_llamado(db, id_retiro_laboral: int):
    query = text("""
        SELECT
            rl."IdRetiroLaboral",
            rp."NumeroIdentificacion" AS "NumeroDocumento",
            TRIM(
                COALESCE(rp."Nombres", '') || ' ' ||
                COALESCE(rp."Apellidos", '')
            ) AS "NombreCompleto",
            COALESCE(da."Direccion", '') AS "Direccion",
            COALESCE(da."Barrio", '') AS "Barrio",
            COALESCE(rp."Celular", '') AS "Telefono",
            COALESCE(ca."NombreCargo", '') AS "Cargo",
            COALESCE(rl."FechaRetiro", CURRENT_DATE) AS "FechaAusencia"
        FROM public."RetiroLaboral" rl
        INNER JOIN public."RegistroPersonal" rp
            ON rl."IdRegistroPersonal" = rp."IdRegistroPersonal"
        LEFT JOIN public."DatosAdicionales" da
            ON rp."IdRegistroPersonal" = da."IdRegistroPersonal"
        LEFT JOIN public."Cargo" ca
            ON rp."IdCargo"::integer = ca."IdCargo"
        WHERE rl."IdRetiroLaboral" = :id_retiro_laboral
        LIMIT 1;
    """)

    row = db.execute(query, {"id_retiro_laboral": id_retiro_laboral}).mappings().first()

    if not row:
        raise ValueError(f"No se encontraron datos para IdRetiroLaboral={id_retiro_laboral}")

    return dict(row)


def generar_primer_llamado(db, id_retiro_laboral: int):
    if not TEMPLATE_PRIMER_LLAMADO.exists():
        raise FileNotFoundError(f"No se encontró la plantilla: {TEMPLATE_PRIMER_LLAMADO}")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    datos = obtener_datos_primer_llamado(db, id_retiro_laboral)

    doc = Document(str(TEMPLATE_PRIMER_LLAMADO))

    fecha_ausencia = datos.get("FechaAusencia")
    if fecha_ausencia:
        try:
            fecha_ausencia = fecha_ausencia.strftime("%d/%m/%Y")
        except Exception:
            fecha_ausencia = str(fecha_ausencia)
    else:
        fecha_ausencia = ""

    replacements = {
        "{{FECHA_HOY}}": datetime.today().strftime("%d/%m/%Y"),
        "{{NOMBRE_COMPLETO}}": datos.get("NombreCompleto", ""),
        "{{NUMERO_DOCUMENTO}}": datos.get("NumeroDocumento", ""),
        "{{DIRECCION}}": datos.get("Direccion", ""),
        "{{BARRIO}}": datos.get("Barrio", ""),
        "{{TELEFONO}}": datos.get("Telefono", ""),
        "{{CARGO}}": datos.get("Cargo", ""),
        "{{CIUDAD}}": "BOGOTÁ D.C.",
        "{{FECHA_AUSENCIA}}": fecha_ausencia,
        "{{NOMBRE_ANALISTA}}": "YENY CUESTO",
        "{{CARGO_ANALISTA}}": "ANALISTA TALENTO HUMANO",
        "{{ASUNTO}}": "PRIMER LLAMADO ABANDONO INASISTENCIA AL CARGO",
    }

    for paragraph in doc.paragraphs:
        _replace_text_in_paragraph(paragraph, replacements)

    for table in doc.tables:
        _replace_text_in_table(table, replacements)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_path = OUTPUT_DIR / f"primer_llamado_retiro_{id_retiro_laboral}_{timestamp}.docx"
    doc.save(str(output_path))

    return output_path


def generar_segundo_llamado(db, id_retiro_laboral: int):
    if not TEMPLATE_SEGUNDO_LLAMADO.exists():
        raise FileNotFoundError(f"No se encontró la plantilla: {TEMPLATE_SEGUNDO_LLAMADO}")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    datos = obtener_datos_primer_llamado(db, id_retiro_laboral)

    doc = Document(str(TEMPLATE_SEGUNDO_LLAMADO))

    fecha_ausencia = datos.get("FechaAusencia")
    if fecha_ausencia:
        try:
            fecha_ausencia = fecha_ausencia.strftime("%d/%m/%Y")
        except Exception:
            fecha_ausencia = str(fecha_ausencia)
    else:
        fecha_ausencia = ""

    replacements = {
        "{{FECHA_HOY}}": datetime.today().strftime("%d/%m/%Y"),
        "{{NOMBRE_COMPLETO}}": datos.get("NombreCompleto", ""),
        "{{NUMERO_DOCUMENTO}}": datos.get("NumeroDocumento", ""),
        "{{DIRECCION}}": datos.get("Direccion", ""),
        "{{BARRIO}}": datos.get("Barrio", ""),
        "{{TELEFONO}}": datos.get("Telefono", ""),
        "{{CARGO}}": datos.get("Cargo", ""),
        "{{CIUDAD}}": "BOGOTÁ D.C.",
        "{{FECHA_AUSENCIA}}": fecha_ausencia,
        "{{NOMBRE_ANALISTA}}": "YENY CUESTO",
        "{{CARGO_ANALISTA}}": "ANALISTA TALENTO HUMANO",
        "{{ASUNTO}}": "SEGUNDO LLAMADO ABANDONO INASISTENCIA AL CARGO",
    }

    for paragraph in doc.paragraphs:
        _replace_text_in_paragraph(paragraph, replacements)

    for table in doc.tables:
        _replace_text_in_table(table, replacements)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_path = OUTPUT_DIR / f"segundo_llamado_retiro_{id_retiro_laboral}_{timestamp}.docx"
    doc.save(str(output_path))

    return output_path


def generar_y_registrar_primer_llamado(
    db,
    id_retiro_laboral: int,
    usuario_actualizacion: str = "RRLL"
):
    output_path = generar_primer_llamado(db, id_retiro_laboral)

    if not output_path.exists():
        raise FileNotFoundError("No se pudo generar físicamente el documento.")

    nombre_archivo = output_path.name
    nombre_original = output_path.name
    ruta_archivo = str(output_path).replace("\\", "/")
    extension_archivo = output_path.suffix.lower()
    peso_archivo = output_path.stat().st_size
    mime_type = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"

    q_old = text("""
        SELECT
            "IdRetiroLaboralAdjunto",
            "RutaArchivo"
        FROM public."RetiroLaboralAdjunto"
        WHERE "IdRetiroLaboral" = :id_retiro_laboral
          AND "IdTipoDocumentoRetiro" = :id_tipo_documento_retiro
          AND COALESCE("Eliminado", false) = false
          AND COALESCE("Activo", true) = true
        ORDER BY "IdRetiroLaboralAdjunto" DESC
        LIMIT 1;
    """)

    old = db.execute(q_old, {
        "id_retiro_laboral": id_retiro_laboral,
        "id_tipo_documento_retiro": TIPO_DOC_PRIMER_LLAMADO
    }).mappings().first()

    if old:
        q_desactivar = text("""
            UPDATE public."RetiroLaboralAdjunto"
            SET
                "Activo" = false,
                "Eliminado" = true,
                "FechaActualizacion" = now(),
                "UsuarioActualizacion" = :usuario_actualizacion
            WHERE "IdRetiroLaboralAdjunto" = :id_adjunto;
        """)
        db.execute(q_desactivar, {
            "id_adjunto": old["IdRetiroLaboralAdjunto"],
            "usuario_actualizacion": usuario_actualizacion
        })

        ruta_old = Path(old["RutaArchivo"]) if old.get("RutaArchivo") else None
        if ruta_old and ruta_old.exists():
            ruta_old.unlink(missing_ok=True)

    q_insert = text("""
        INSERT INTO public."RetiroLaboralAdjunto" (
            "IdRetiroLaboral",
            "IdTipoDocumentoRetiro",
            "NombreArchivo",
            "NombreArchivoOriginal",
            "RutaArchivo",
            "ExtensionArchivo",
            "PesoArchivo",
            "Observacion",
            "OrigenArchivo",
            "MimeType",
            "Activo",
            "Eliminado",
            "FechaCreacion",
            "FechaActualizacion",
            "CreadoPor",
            "UsuarioActualizacion"
        )
        VALUES (
            :id_retiro_laboral,
            :id_tipo_documento_retiro,
            :nombre_archivo,
            :nombre_archivo_original,
            :ruta_archivo,
            :extension_archivo,
            :peso_archivo,
            :observacion,
            'GENERADO',
            :mime_type,
            true,
            false,
            now(),
            now(),
            :creado_por,
            :usuario_actualizacion
        )
        RETURNING
            "IdRetiroLaboralAdjunto",
            "IdRetiroLaboral",
            "IdTipoDocumentoRetiro",
            "NombreArchivo",
            "NombreArchivoOriginal",
            "RutaArchivo",
            "ExtensionArchivo",
            "PesoArchivo",
            "Observacion",
            "OrigenArchivo",
            "MimeType",
            "Activo";
    """)

    row = db.execute(q_insert, {
        "id_retiro_laboral": id_retiro_laboral,
        "id_tipo_documento_retiro": TIPO_DOC_PRIMER_LLAMADO,
        "nombre_archivo": nombre_archivo,
        "nombre_archivo_original": nombre_original,
        "ruta_archivo": ruta_archivo,
        "extension_archivo": extension_archivo,
        "peso_archivo": peso_archivo,
        "observacion": "Documento generado automáticamente: Primer llamado",
        "mime_type": mime_type,
        "creado_por": usuario_actualizacion,
        "usuario_actualizacion": usuario_actualizacion,
    }).mappings().first()

    db.commit()
    return dict(row)


def generar_y_registrar_segundo_llamado(
    db,
    id_retiro_laboral: int,
    usuario_actualizacion: str = "RRLL"
):
    output_path = generar_segundo_llamado(db, id_retiro_laboral)

    if not output_path.exists():
        raise FileNotFoundError("No se pudo generar físicamente el documento.")

    nombre_archivo = output_path.name
    nombre_original = output_path.name
    ruta_archivo = str(output_path).replace("\\", "/")
    extension_archivo = output_path.suffix.lower()
    peso_archivo = output_path.stat().st_size
    mime_type = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"

    q_old = text("""
        SELECT
            "IdRetiroLaboralAdjunto",
            "RutaArchivo"
        FROM public."RetiroLaboralAdjunto"
        WHERE "IdRetiroLaboral" = :id_retiro_laboral
          AND "IdTipoDocumentoRetiro" = :id_tipo_documento_retiro
          AND COALESCE("Eliminado", false) = false
          AND COALESCE("Activo", true) = true
        ORDER BY "IdRetiroLaboralAdjunto" DESC
        LIMIT 1;
    """)

    old = db.execute(q_old, {
        "id_retiro_laboral": id_retiro_laboral,
        "id_tipo_documento_retiro": TIPO_DOC_SEGUNDO_LLAMADO
    }).mappings().first()

    if old:
        q_desactivar = text("""
            UPDATE public."RetiroLaboralAdjunto"
            SET
                "Activo" = false,
                "Eliminado" = true,
                "FechaActualizacion" = now(),
                "UsuarioActualizacion" = :usuario_actualizacion
            WHERE "IdRetiroLaboralAdjunto" = :id_adjunto;
        """)
        db.execute(q_desactivar, {
            "id_adjunto": old["IdRetiroLaboralAdjunto"],
            "usuario_actualizacion": usuario_actualizacion
        })

        ruta_old = Path(old["RutaArchivo"]) if old.get("RutaArchivo") else None
        if ruta_old and ruta_old.exists():
            ruta_old.unlink(missing_ok=True)

    q_insert = text("""
        INSERT INTO public."RetiroLaboralAdjunto" (
            "IdRetiroLaboral",
            "IdTipoDocumentoRetiro",
            "NombreArchivo",
            "NombreArchivoOriginal",
            "RutaArchivo",
            "ExtensionArchivo",
            "PesoArchivo",
            "Observacion",
            "OrigenArchivo",
            "MimeType",
            "Activo",
            "Eliminado",
            "FechaCreacion",
            "FechaActualizacion",
            "CreadoPor",
            "UsuarioActualizacion"
        )
        VALUES (
            :id_retiro_laboral,
            :id_tipo_documento_retiro,
            :nombre_archivo,
            :nombre_archivo_original,
            :ruta_archivo,
            :extension_archivo,
            :peso_archivo,
            :observacion,
            'GENERADO',
            :mime_type,
            true,
            false,
            now(),
            now(),
            :creado_por,
            :usuario_actualizacion
        )
        RETURNING
            "IdRetiroLaboralAdjunto",
            "IdRetiroLaboral",
            "IdTipoDocumentoRetiro",
            "NombreArchivo",
            "NombreArchivoOriginal",
            "RutaArchivo",
            "ExtensionArchivo",
            "PesoArchivo",
            "Observacion",
            "OrigenArchivo",
            "MimeType",
            "Activo";
    """)

    row = db.execute(q_insert, {
        "id_retiro_laboral": id_retiro_laboral,
        "id_tipo_documento_retiro": TIPO_DOC_SEGUNDO_LLAMADO,
        "nombre_archivo": nombre_archivo,
        "nombre_archivo_original": nombre_original,
        "ruta_archivo": ruta_archivo,
        "extension_archivo": extension_archivo,
        "peso_archivo": peso_archivo,
        "observacion": "Documento generado automáticamente: Segundo llamado",
        "mime_type": mime_type,
        "creado_por": usuario_actualizacion,
        "usuario_actualizacion": usuario_actualizacion,
    }).mappings().first()

    db.commit()
    return dict(row)