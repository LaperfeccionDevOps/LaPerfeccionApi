from pathlib import Path
from datetime import datetime
from docx import Document
from sqlalchemy import text
import re


BASE_DIR = Path(__file__).resolve().parents[1]
TEMPLATE_PRIMER_LLAMADO = BASE_DIR / "templates" / "rrll" / "abandono" / "primer_llamado_abandono.docx"
TIPO_DOC_PRIMER_LLAMADO = 13

TEMPLATE_SEGUNDO_LLAMADO = BASE_DIR / "templates" / "rrll" / "abandono" / "segundo_llamado_abandono.docx"
TIPO_DOC_SEGUNDO_LLAMADO = 14

TEMPLATE_CARTA_FINALIZACION = BASE_DIR / "templates" / "rrll" / "finalizacion" / "carta_finalizacion_contrato.docx"
TIPO_DOC_CARTA_FINALIZACION = 4

TEMPLATE_PAQUETE_RETIRO = BASE_DIR / "templates" / "rrll" / "paquete" / "paquete_retiro.docx"
TIPO_DOC_PAQUETE_RETIRO = 10

OUTPUT_DIR = BASE_DIR / "storage" / "rrll" / "generados"


def _clean_text(value):
    """
    Limpia tabs, saltos de línea y espacios múltiples para que Word
    no distribuya el texto raro al reemplazar placeholders.
    """
    if value is None:
        return ""

    text_value = str(value)

    text_value = text_value.replace("\t", " ")
    text_value = text_value.replace("\r", " ")
    text_value = text_value.replace("\n", " ")

    text_value = re.sub(r"\s+", " ", text_value)

    return text_value.strip()


def _replace_text_in_paragraph(paragraph, replacements: dict):
    for key, value in replacements.items():
        if key in paragraph.text:
            for run in paragraph.runs:
                if key in run.text:
                    run.text = run.text.replace(key, str(value))


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
            psy."FechaUltimoDiaLaborado" AS "FechaAusencia"
        FROM public."RetiroLaboral" rl
        INNER JOIN public."RegistroPersonal" rp
            ON rl."IdRegistroPersonal" = rp."IdRegistroPersonal"
        LEFT JOIN public."DatosAdicionales" da
            ON rp."IdRegistroPersonal" = da."IdRegistroPersonal"
       LEFT JOIN public."AsignacionCargoCliente" acc
            ON acc."IdRegistroPersonal" = rp."IdRegistroPersonal"
       LEFT JOIN public."Cargo" ca
            ON acc."IdCargo" = ca."IdCargo"
        LEFT JOIN public."PazYSalvoOperaciones" psy
            ON psy."IdRetiroLaboral" = rl."IdRetiroLaboral"
        WHERE rl."IdRetiroLaboral" = :id_retiro_laboral
        LIMIT 1;
    """)

    row = db.execute(query, {"id_retiro_laboral": id_retiro_laboral}).mappings().first()

    if not row:
        raise ValueError(f"No se encontraron datos para IdRetiroLaboral={id_retiro_laboral}")

    datos = dict(row)

    datos["NumeroDocumento"] = _clean_text(datos.get("NumeroDocumento"))
    datos["NombreCompleto"] = _clean_text(datos.get("NombreCompleto"))
    datos["Direccion"] = _clean_text(datos.get("Direccion"))
    datos["Barrio"] = _clean_text(datos.get("Barrio"))
    datos["Telefono"] = _clean_text(datos.get("Telefono"))
    datos["Cargo"] = _clean_text(datos.get("Cargo"))

    return datos


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
            fecha_ausencia = _clean_text(fecha_ausencia)
    else:
        fecha_ausencia = ""

    replacements = {
        "{{FECHA_HOY}}": datetime.today().strftime("%d/%m/%Y"),
        "{{NOMBRE_COMPLETO}}": _upper_text(datos.get("NombreCompleto", "")),
        "{{NUMERO_DOCUMENTO}}": _upper_text(datos.get("NumeroDocumento", "")),
        "{{DIRECCION}}": _upper_text(datos.get("Direccion", "")),
        "{{BARRIO}}": _upper_text(datos.get("Barrio", "")),
        "{{TELEFONO}}": _upper_text(datos.get("Telefono", "")),
        "{{CARGO}}": _upper_text(datos.get("Cargo", "")),
        "{{CIUDAD}}": "CIUDAD",
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
            fecha_ausencia = _clean_text(fecha_ausencia)
    else:
        fecha_ausencia = ""

    replacements = {
        "{{FECHA_HOY}}": datetime.today().strftime("%d/%m/%Y"),
        "{{NOMBRE_COMPLETO}}": _upper_text(datos.get("NombreCompleto", "")),
        "{{NUMERO_DOCUMENTO}}": _upper_text(datos.get("NumeroDocumento", "")),
        "{{DIRECCION}}": _upper_text(datos.get("Direccion", "")),
        "{{BARRIO}}": _upper_text(datos.get("Barrio", "")),
        "{{TELEFONO}}": _upper_text(datos.get("Telefono", "")),
        "{{CARGO}}": _upper_text(datos.get("Cargo", "")),
        "{{CIUDAD}}": "CIUDAD",
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


def generar_carta_finalizacion(db, id_retiro_laboral: int):
    if not TEMPLATE_CARTA_FINALIZACION.exists():
        raise FileNotFoundError(f"No se encontró la plantilla: {TEMPLATE_CARTA_FINALIZACION}")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    datos = obtener_datos_primer_llamado(db, id_retiro_laboral)
    doc = Document(str(TEMPLATE_CARTA_FINALIZACION))

    fecha_ausencia = datos.get("FechaAusencia")
    if fecha_ausencia:
        try:
            fecha_ausencia = fecha_ausencia.strftime("%d/%m/%Y")
        except Exception:
            fecha_ausencia = _clean_text(fecha_ausencia)
    else:
        fecha_ausencia = ""

    replacements = {
        "{{FECHA_HOY}}": datetime.today().strftime("%d/%m/%Y"),
        "{{NOMBRE_COMPLETO}}": _upper_text(datos.get("NombreCompleto", "")),
        "{{NUMERO_DOCUMENTO}}": _upper_text(datos.get("NumeroDocumento", "")),
        "{{DIRECCION}}": _upper_text(datos.get("Direccion", "")),
        "{{BARRIO}}": _upper_text(datos.get("Barrio", "")),
        "{{TELEFONO}}": _upper_text(datos.get("Telefono", "")),
        "{{CARGO}}": _upper_text(datos.get("Cargo", "")),
        "{{CIUDAD}}": "CIUDAD",
        "{{FECHA_AUSENCIA}}": fecha_ausencia,
        "{{NOMBRE_ANALISTA}}": "YENY CUESTO",
        "{{CARGO_ANALISTA}}": "ANALISTA TALENTO HUMANO",
        "{{ASUNTO}}": "CARTA DE FINALIZACIÓN DEL CONTRATO",
    }

    for paragraph in doc.paragraphs:
        _replace_text_in_paragraph(paragraph, replacements)

    for table in doc.tables:
        _replace_text_in_table(table, replacements)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_path = OUTPUT_DIR / f"carta_finalizacion_retiro_{id_retiro_laboral}_{timestamp}.docx"
    doc.save(str(output_path))

    return output_path


def _upper_text(value):
    if value is None:
        return ""
    return str(value).upper().strip()


def generar_paquete_retiro(db, id_retiro_laboral: int):
    if not TEMPLATE_PAQUETE_RETIRO.exists():
        raise FileNotFoundError(f"No se encontró la plantilla: {TEMPLATE_PAQUETE_RETIRO}")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    datos = obtener_datos_primer_llamado(db, id_retiro_laboral)
    print("DEBUG DATOS PAQUETE:", datos)
    doc = Document(str(TEMPLATE_PAQUETE_RETIRO))

    fecha_fin = datos.get("FechaAusencia")
    if fecha_fin:
        try:
            fecha_fin = fecha_fin.strftime("%d/%m/%Y")
        except Exception:
            fecha_fin = str(fecha_fin)
    else:
        fecha_fin = ""

    replacements = {
        "{{FECHA_HOY}}": datetime.today().strftime("%d/%m/%Y"),
        "{{FECHA_FIN}}": fecha_fin,
        "{{NOMBRE_COMPLETO}}": _upper_text(datos.get("NombreCompleto", "")),
        "{{NUMERO_DOCUMENTO}}": _upper_text(datos.get("NumeroDocumento", "")),
        "{{DIRECCION}}": _upper_text(datos.get("Direccion", "")),
        "{{BARRIO}}": _upper_text(datos.get("Barrio", "")),
        "{{TELEFONO}}": _upper_text(datos.get("Telefono", "")),
        "{{CARGO}}": _upper_text(datos.get("Cargo", "")),
        "{{CIUDAD}}": "CIUDAD",
        "{{NOMBRE_ANALISTA}}": "YENY CUESTO",
        "{{CARGO_ANALISTA}}": "ANALISTA TALENTO HUMANO",
    }

    for paragraph in doc.paragraphs:
        _replace_text_in_paragraph(paragraph, replacements)

    for table in doc.tables:
        _replace_text_in_table(table, replacements)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_path = OUTPUT_DIR / f"paquete_retiro_{id_retiro_laboral}_{timestamp}.docx"
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


def generar_y_registrar_carta_finalizacion(
    db,
    id_retiro_laboral: int,
    usuario_actualizacion: str = "RRLL"
):
    output_path = generar_carta_finalizacion(db, id_retiro_laboral)

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
        "id_tipo_documento_retiro": TIPO_DOC_CARTA_FINALIZACION
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
        "id_tipo_documento_retiro": TIPO_DOC_CARTA_FINALIZACION,
        "nombre_archivo": nombre_archivo,
        "nombre_archivo_original": nombre_original,
        "ruta_archivo": ruta_archivo,
        "extension_archivo": extension_archivo,
        "peso_archivo": peso_archivo,
        "observacion": "Documento generado automáticamente: Carta de finalización",
        "mime_type": mime_type,
        "creado_por": usuario_actualizacion,
        "usuario_actualizacion": usuario_actualizacion,
    }).mappings().first()

    db.commit()
    return dict(row)

def generar_y_registrar_paquete_retiro(
    db,
    id_retiro_laboral: int,
    usuario_actualizacion: str = "RRLL"
):
    output_path = generar_paquete_retiro(db, id_retiro_laboral)

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
        "id_tipo_documento_retiro": TIPO_DOC_PAQUETE_RETIRO
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
        "id_tipo_documento_retiro": TIPO_DOC_PAQUETE_RETIRO,
        "nombre_archivo": nombre_archivo,
        "nombre_archivo_original": nombre_original,
        "ruta_archivo": ruta_archivo,
        "extension_archivo": extension_archivo,
        "peso_archivo": peso_archivo,
        "observacion": "Documento generado automáticamente: Paquete de retiro",
        "mime_type": mime_type,
        "creado_por": usuario_actualizacion,
        "usuario_actualizacion": usuario_actualizacion,
    }).mappings().first()

    db.commit()
    return dict(row)