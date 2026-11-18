from pathlib import Path
from datetime import datetime
from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.shared import Inches, Pt
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

TEMPLATE_PAQUETE_RETIRO_VOLUNTARIO = BASE_DIR / "templates" / "rrll" / "paquete" / "paquete_retiro_voluntario.docx"

FIRMA_YENY = BASE_DIR / "assets" / "comunicaciones" / "FIRMA_YENY.png"

# ✅ RUTA CORRECTA:
# cada documento generado debe quedar dentro de:
# app/storage/rrll/retiros/{IdRetiroLaboral}/archivo.docx
OUTPUT_BASE_DIR = Path("C:/LaPerfeccionStorage/rrll/retiros")


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


def _upper_text(value):
    if value is None:
        return ""
    return str(value).upper().strip()


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



def _paragraph_has_image(paragraph) -> bool:
    """Indica si el párrafo contiene una imagen incrustada."""
    return bool(
        paragraph._p.xpath(".//w:drawing")
        or paragraph._p.xpath(".//w:pict")
    )


def _remove_images_from_paragraph(paragraph):
    """Elimina únicamente las imágenes contenidas en el párrafo indicado."""
    for drawing in paragraph._p.xpath(".//w:drawing"):
        parent = drawing.getparent()
        if parent is not None:
            parent.remove(drawing)

    for pict in paragraph._p.xpath(".//w:pict"):
        parent = pict.getparent()
        if parent is not None:
            parent.remove(pict)


def _clear_paragraph(paragraph):
    """Limpia el contenido del párrafo conservando su posición en la plantilla."""
    for child in list(paragraph._p):
        paragraph._p.remove(child)


def _remove_trailing_empty_paragraphs(paragraphs, start_index: int):
    """
    Elimina únicamente los párrafos vacíos que quedan después del bloque de firma.

    Se usa en modo compacto para la carta de finalización, evitando que Word
    empuje párrafos vacíos a una segunda hoja. No modifica el encabezado,
    el pie de página ni otros documentos.
    """
    for paragraph in list(paragraphs[start_index:]):
        if paragraph.text.strip():
            break

        if _paragraph_has_image(paragraph):
            break

        parent = paragraph._p.getparent()
        if parent is not None:
            parent.remove(paragraph._p)


def _iter_document_paragraph_groups(doc):
    """
    Devuelve grupos de párrafos del cuerpo y de las tablas para poder
    encontrar la firma sin modificar logos, encabezados u otras imágenes.
    """
    yield doc.paragraphs

    for table in doc.tables:
        for row in table.rows:
            for cell in row.cells:
                yield cell.paragraphs


def _replace_text_across_runs(paragraph, old_text: str, new_text: str):
    """Reemplaza texto aunque Word lo haya dividido entre varios runs."""
    if old_text not in paragraph.text:
        return False

    full_text = paragraph.text.replace(old_text, new_text)

    if paragraph.runs:
        paragraph.runs[0].text = full_text
        for run in paragraph.runs[1:]:
            run.text = ""
    else:
        paragraph.add_run(full_text)

    return True


def _resolve_empresa_logo(empresa_logo) -> Path:
    """Resuelve la ruta del logo guardada en EmpresaContratante."""
    logo_value = _clean_text(empresa_logo)
    if not logo_value:
        raise ValueError("La empresa contratante no tiene logo configurado.")

    logo_path = Path(logo_value.replace("\\", "/"))
    if not logo_path.is_absolute():
        logo_path = BASE_DIR / logo_path

    if not logo_path.exists():
        raise FileNotFoundError(f"No se encontró el logo de la empresa: {logo_path}")

    return logo_path


def _validar_empresa_rrll(datos: dict) -> str:
    """Valida que RRLL conozca la empresa exacta del ciclo laboral del retiro."""
    codigo = _upper_text(datos.get("EmpresaCodigo"))

    if codigo not in {"ALP", "MI"}:
        raise ValueError(
            "No fue posible determinar la empresa contratante del retiro. "
            "El documento RRLL no se generará para evitar usar un membrete incorrecto. "
            f"IdRetiroLaboral={datos.get('IdRetiroLaboral')}, "
            f"IdVinculacionLaboral={datos.get('IdVinculacionLaboral') or 'SIN VINCULACIÓN'}, "
            f"EmpresaCodigo={codigo or 'SIN CÓDIGO'}."
        )

    return codigo


def _configurar_encabezado_empresa(doc, datos: dict):
    """
    Conserva el encabezado ALP original de la plantilla.
    Para Mantener reemplaza únicamente el logo del encabezado.
    """
    codigo = _validar_empresa_rrll(datos)
    if codigo == "ALP":
        return

    logo_path = _resolve_empresa_logo(datos.get("EmpresaLogo"))

    for section in doc.sections:
        header = section.header
        paragraphs = header.paragraphs

        if not paragraphs:
            paragraph = header.add_paragraph()
        else:
            paragraph = paragraphs[0]

        for p in paragraphs:
            for drawing in p._p.xpath(".//w:drawing"):
                parent = drawing.getparent()
                if parent is not None:
                    parent.remove(drawing)
            for pict in p._p.xpath(".//w:pict"):
                parent = pict.getparent()
                if parent is not None:
                    parent.remove(pict)

        _clear_paragraph(paragraph)
        paragraph.alignment = WD_ALIGN_PARAGRAPH.LEFT
        run = paragraph.add_run()
        run.add_picture(str(logo_path), width=Inches(2.15))


def _configurar_pie_empresa(doc, datos: dict):
    """
    Conserva el pie ALP original de la plantilla.
    Para Mantener usa el mismo pie institucional validado en Nómina.
    """
    codigo = _validar_empresa_rrll(datos)
    if codigo == "ALP":
        return

    lineas = [
        (
            "Soluciones integrales para el sector residencial, comercial e institucional, "
            "anticipándose a las necesidades de sus clientes con innovación, gestión eficiente "
            "y tecnología de vanguardia."
        ),
        (
            "Contamos con un equipo calificado y un firme compromiso con la calidad, "
            "el medio ambiente y el desarrollo sostenible."
        ),
        "______________________________________________________________________________________________",
        "Calle 25 # 32-22 de Bogotá D.C. – Colombia – +57 318 430 7338",
        "comercial@manteneringenieria.com",
        "www.manteneringenieria.com",
    ]

    for section in doc.sections:
        footer = section.footer
        paragraphs = footer.paragraphs

        if not paragraphs:
            paragraphs = [footer.add_paragraph()]

        # Limpia el contenido ALP existente, sin tocar el cuerpo del documento.
        for paragraph in paragraphs:
            _clear_paragraph(paragraph)

        while len(footer.paragraphs) < len(lineas):
            footer.add_paragraph()

        for index, linea in enumerate(lineas):
            paragraph = footer.paragraphs[index]
            paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
            paragraph.paragraph_format.space_before = 0
            paragraph.paragraph_format.space_after = 0
            run = paragraph.add_run(linea)
            run.font.size = Pt(5.5 if index < 2 else 6.5)

        # Si la plantilla tenía más párrafos en el pie, se dejan vacíos.
        for paragraph in footer.paragraphs[len(lineas):]:
            _clear_paragraph(paragraph)


def _configurar_texto_empresa_abandono(doc, datos: dict):
    """Ajusta la referencia a las oficinas según la empresa contratante."""
    codigo = _validar_empresa_rrll(datos)
    if codigo == "ALP":
        return

    texto_alp = "Aseos la perfección (Calle 4 bis N. 53 c – 50)"
    texto_mi = "Mantener Ingeniería (Calle 25 # 32-22)"

    for paragraph in doc.paragraphs:
        _replace_text_across_runs(paragraph, texto_alp, texto_mi)

    for table in doc.tables:
        for row in table.rows:
            for cell in row.cells:
                for paragraph in cell.paragraphs:
                    _replace_text_across_runs(paragraph, texto_alp, texto_mi)


def _aplicar_membrete_rrll(doc, datos: dict):
    """Aplica el branding empresarial únicamente a documentos RRLL de abandono."""
    _configurar_encabezado_empresa(doc, datos)
    _configurar_pie_empresa(doc, datos)
    _configurar_texto_empresa_abandono(doc, datos)


def _configurar_texto_empresa_finalizacion(doc, datos: dict):
    """Ajusta las referencias empresariales de la carta de finalización."""
    codigo = _validar_empresa_rrll(datos)
    if codigo == "ALP":
        return

    reemplazos_empresa = {
        "Aseos la perfección S.A.S": "Mantener Ingeniería",
        "Aseos La Perfección S.A.S": "Mantener Ingeniería",
        "Aseos la Perfección": "Mantener Ingeniería",
        "Aseos La Perfección": "Mantener Ingeniería",
    }

    for paragraph in doc.paragraphs:
        for texto_alp, texto_mi in reemplazos_empresa.items():
            _replace_text_across_runs(paragraph, texto_alp, texto_mi)

    for table in doc.tables:
        for row in table.rows:
            for cell in row.cells:
                for paragraph in cell.paragraphs:
                    for texto_alp, texto_mi in reemplazos_empresa.items():
                        _replace_text_across_runs(paragraph, texto_alp, texto_mi)


def _aplicar_membrete_finalizacion(doc, datos: dict):
    """Aplica logo, pie y textos empresariales a la carta de finalización RRLL."""
    _configurar_encabezado_empresa(doc, datos)
    _configurar_pie_empresa(doc, datos)
    _configurar_texto_empresa_finalizacion(doc, datos)


def _configurar_texto_empresa_paquete(doc, datos: dict):
    """
    Ajusta únicamente las referencias textuales de empresa dentro del paquete
    de retiro. Conserva intacto el contenido jurídico y funcional del formato.
    """
    codigo = _validar_empresa_rrll(datos)
    if codigo == "ALP":
        return

    reemplazos_empresa = {
        "Aseos La Perfección S.A.S.": "Mantener Ingeniería",
        "Aseos la Perfección S.A.S.": "Mantener Ingeniería",
        "Aseos La Perfección S.A.S": "Mantener Ingeniería",
        "Aseos la Perfección S.A.S": "Mantener Ingeniería",
        "Aseos La Perfección": "Mantener Ingeniería",
        "Aseos la Perfección": "Mantener Ingeniería",
    }

    for paragraph in doc.paragraphs:
        for texto_alp, texto_mi in reemplazos_empresa.items():
            _replace_text_across_runs(paragraph, texto_alp, texto_mi)

    for table in doc.tables:
        for row in table.rows:
            for cell in row.cells:
                for paragraph in cell.paragraphs:
                    for texto_alp, texto_mi in reemplazos_empresa.items():
                        _replace_text_across_runs(paragraph, texto_alp, texto_mi)


def _aplicar_membrete_paquete(doc, datos: dict):
    """
    Aplica branding ALP/MI al paquete completo de retiro.
    Los encabezados y pies se procesan por sección, por lo que cubre las
    tres páginas del paquete sin alterar su estructura.
    """
    _configurar_encabezado_empresa(doc, datos)
    _configurar_pie_empresa(doc, datos)
    _configurar_texto_empresa_paquete(doc, datos)


def _compactar_informacion_paquete_mantener(doc, empresa_codigo: str, es_voluntario: bool = False):
    """
    Compacta exclusivamente el bloque INFOR­MACIÓN IMPORTANTE del paquete MI.
    ALP queda intacto. No agrega ni elimina saltos de página.
    """
    if _upper_text(empresa_codigo) != "MI":
        return

    inicio_encontrado = False

    # Tomamos una sola instantánea de los párrafos. No usamos
    # doc.paragraphs.index(paragraph), porque python-docx crea objetos Paragraph
    # nuevos en cada acceso y eso puede producir ValueError / HTTP 500.
    paragraphs = list(doc.paragraphs)

    for indice_actual, paragraph in enumerate(paragraphs):
        texto = _clean_text(paragraph.text).upper()

        if "INFORMACIÓN IMPORTANTE" in texto or "INFORMACION IMPORTANTE" in texto:
            # Este recorte de párrafos vacíos corresponde EXCLUSIVAMENTE a la
            # plantilla de retiro VOLUNTARIO de Mantener. El paquete NORMAL
            # conserva intacta su estructura original.
            if es_voluntario:
                for previo in paragraphs[max(0, indice_actual - 4):indice_actual]:
                    if not previo.text.strip() and not _paragraph_has_image(previo):
                        parent = previo._p.getparent()
                        if parent is not None:
                            parent.remove(previo._p)

            inicio_encontrado = True
            paragraph.paragraph_format.space_before = 0
            paragraph.paragraph_format.space_after = Pt(2)
            paragraph.paragraph_format.keep_with_next = True

        if not inicio_encontrado:
            continue

        # Recupera espacio vertical únicamente en las hojas informativas de MI.
        paragraph.paragraph_format.space_before = 0
        paragraph.paragraph_format.space_after = 0
        paragraph.paragraph_format.line_spacing = 0.86

        # Conserva el título visible; compacta ligeramente el texto informativo.
        es_titulo = (
            "INFORMACIÓN IMPORTANTE" in texto
            or "INFORMACION IMPORTANTE" in texto
        )
        for run in paragraph.runs:
            if es_titulo:
                if run.font.size is None or run.font.size.pt > 8:
                    run.font.size = Pt(8)
            else:
                if run.font.size is None or run.font.size.pt > 7.5:
                    run.font.size = Pt(7.5)



def _ajustar_informacion_paquete_voluntario_alp(doc, empresa_codigo: str, es_voluntario: bool = False):
    """
    Ajusta exclusivamente ALP + retiro voluntario.
    Sube el inicio de INFORMACIÓN IMPORTANTE y distribuye mejor el texto
    entre las hojas informativas, sin tocar el paquete normal ni Mantener.
    """
    if _upper_text(empresa_codigo) != "ALP" or not es_voluntario:
        return

    paragraphs = list(doc.paragraphs)
    inicio = None

    for i, paragraph in enumerate(paragraphs):
        texto = _clean_text(paragraph.text).upper()
        if "INFORMACIÓN IMPORTANTE" in texto or "INFORMACION IMPORTANTE" in texto:
            inicio = i
            break

    if inicio is None:
        return

    # Elimina únicamente los párrafos vacíos inmediatamente anteriores al
    # encabezado informativo. Esto hace que el bloque suba en la hoja 2.
    for previo in paragraphs[max(0, inicio - 8):inicio]:
        if not previo.text.strip() and not _paragraph_has_image(previo):
            parent = previo._p.getparent()
            if parent is not None:
                parent.remove(previo._p)

    # Vuelve a tomar la lista porque acabamos de retirar párrafos vacíos.
    paragraphs = list(doc.paragraphs)
    inicio_encontrado = False

    for paragraph in paragraphs:
        texto = _clean_text(paragraph.text).upper()

        if "INFORMACIÓN IMPORTANTE" in texto or "INFORMACION IMPORTANTE" in texto:
            inicio_encontrado = True
            paragraph.paragraph_format.space_before = 0
            paragraph.paragraph_format.space_after = Pt(3)
            paragraph.paragraph_format.keep_with_next = True

        if not inicio_encontrado:
            continue

        # ALP voluntario: letra un poco mayor que la compactación de Mantener,
        # pero con espacios controlados para aprovechar mejor las hojas 2-4.
        paragraph.paragraph_format.space_before = 0
        paragraph.paragraph_format.space_after = 0
        paragraph.paragraph_format.line_spacing = 0.95

        es_titulo = (
            "INFORMACIÓN IMPORTANTE" in texto
            or "INFORMACION IMPORTANTE" in texto
        )

        for run in paragraph.runs:
            if es_titulo:
                if run.font.size is None or run.font.size.pt < 8.5:
                    run.font.size = Pt(8.5)
            else:
                if run.font.size is None or run.font.size.pt < 8:
                    run.font.size = Pt(8)

def _insertar_firma_yeny(
    doc,
    modo_compacto: bool = False,
    empresa_codigo: str = "ALP",
    preservar_estructura_paginas: bool = False,
):
    """
    Reemplaza los placeholders de nombre/cargo por la imagen completa de Yeny.
    Si existe una firma vieja inmediatamente antes de los placeholders,
    elimina solamente esa imagen y conserva el resto de la plantilla.
    """
    if not FIRMA_YENY.exists():
        raise FileNotFoundError(f"No se encontró la firma de Yeny: {FIRMA_YENY}")

    firma_insertada = False

    for paragraphs in _iter_document_paragraph_groups(doc):
        for index, paragraph in enumerate(paragraphs):
            if "{{NOMBRE_ANALISTA}}" not in paragraph.text:
                continue

            # Busca hacia atrás únicamente la imagen más cercana a la firma.
            for previous_index in range(index - 1, max(-1, index - 4), -1):
                previous_paragraph = paragraphs[previous_index]
                if _paragraph_has_image(previous_paragraph):
                    _remove_images_from_paragraph(previous_paragraph)
                    break

            _clear_paragraph(paragraph)
            paragraph.alignment = WD_ALIGN_PARAGRAPH.LEFT

            if modo_compacto:
                # Solo para la carta de finalización: evita que Word envíe
                # todo el bloque de firma a una segunda hoja.
                paragraph.paragraph_format.keep_together = False
                paragraph.paragraph_format.keep_with_next = False
                paragraph.paragraph_format.space_before = 0
                paragraph.paragraph_format.space_after = 0
                ancho_firma = Inches(2.10)
            else:
                # Primer y segundo llamado: firma compacta para conservar una sola hoja.
                paragraph.paragraph_format.keep_together = False
                paragraph.paragraph_format.keep_with_next = False
                paragraph.paragraph_format.space_before = 0
                paragraph.paragraph_format.space_after = 0
                ancho_firma = Inches(2.10)

            # Solo el paquete de Mantener necesita recuperar un poco de espacio
            # vertical. Los documentos ALP y las cartas individuales quedan intactos.
            if preservar_estructura_paginas and _upper_text(empresa_codigo) == "MI":
                ancho_firma = Inches(1.82)

            run = paragraph.add_run()
            run.add_picture(str(FIRMA_YENY), width=ancho_firma)

            empresa_firma = (
                "Mantener Ingeniería"
                if _upper_text(empresa_codigo) == "MI"
                else "Aseos La Perfección S.A.S."
            )

            # En los paquetes de Mantener compactamos exclusivamente el bloque
            # de firma para que nombre, cargo y empresa no salten a la hoja siguiente.
            # ALP queda exactamente con el comportamiento actual validado.
            es_paquete_mantener = (
                preservar_estructura_paginas
                and _upper_text(empresa_codigo) == "MI"
            )

            if es_paquete_mantener:
                # La imagen un poco más compacta recupera espacio vertical sin
                # alterar el contenido ni introducir saltos de página artificiales.
                inline_shape = paragraph.runs[-1]._r.xpath(".//wp:inline")
                if inline_shape:
                    # La imagen ya fue insertada arriba; el ancho se controla
                    # desde el run gráfico mediante el tamaño inicial.
                    pass

                texto_firma = paragraph.add_run(
                    "\nYENY CUESTO"
                    "\nANALISTA TALENTO HUMANO"
                    f"\n{empresa_firma}"
                )
                texto_firma.bold = True
                texto_firma.font.size = Pt(7.5)
                paragraph.paragraph_format.line_spacing = 0.85
                paragraph.paragraph_format.space_before = 0
                paragraph.paragraph_format.space_after = 0
                paragraph.paragraph_format.keep_together = True
                paragraph.paragraph_format.keep_with_next = False
            else:
                texto_firma = paragraph.add_run(
                    "\nYENY CUESTO"
                    "\nANALISTA TALENTO HUMANO"
                    f"\n{empresa_firma}"
                )
                texto_firma.bold = True

            firma_insertada = True

            # El cargo ya viene dentro de la nueva imagen.
            if index + 1 < len(paragraphs):
                next_paragraph = paragraphs[index + 1]
                if "{{CARGO_ANALISTA}}" in next_paragraph.text:
                    _clear_paragraph(next_paragraph)

                    # En algunas plantillas aparece también el nombre de la empresa
                    # debajo del cargo. Se retira para dejar únicamente el bloque
                    # completo de la firma nueva.
                    if index + 2 < len(paragraphs):
                        company_paragraph = paragraphs[index + 2]
                        if company_paragraph.text.strip().upper() in {
                            "ASEOS LA PERFECCIÓN S.A.S.",
                            "MANTENER INGENIERÍA",
                        }:
                            _clear_paragraph(company_paragraph)

            # En cartas individuales retiramos párrafos vacíos posteriores
            # a la firma para evitar una hoja residual. En el paquete de retiro
            # preservamos esos párrafos porque pueden formar parte de la
            # estructura/paginación original de la plantilla Word.
            if not preservar_estructura_paginas:
                _remove_trailing_empty_paragraphs(paragraphs, index + 1)

    if not firma_insertada:
        raise ValueError(
            "No se encontró el placeholder {{NOMBRE_ANALISTA}} "
            "en la plantilla seleccionada."
        )

def _get_output_dir_for_retiro(id_retiro_laboral: int) -> Path:
    output_dir = OUTPUT_BASE_DIR / str(id_retiro_laboral)
    output_dir.mkdir(parents=True, exist_ok=True)
    return output_dir


def _build_output_path(id_retiro_laboral: int, prefix: str) -> Path:
    output_dir = _get_output_dir_for_retiro(id_retiro_laboral)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return output_dir / f"{prefix}_{id_retiro_laboral}_{timestamp}.docx"


def obtener_datos_primer_llamado(db, id_retiro_laboral: int):
    query = text("""
        SELECT
            rl."IdRetiroLaboral",
            rl."IdVinculacionLaboral",
            vl."IdEmpresaContratante",
            ec."Codigo" AS "EmpresaCodigo",
            ec."Nombre" AS "EmpresaNombre",
            ec."Logo" AS "EmpresaLogo",
            rp."NumeroIdentificacion" AS "NumeroDocumento",
            TRIM(
                COALESCE(rp."Nombres", '') || ' ' ||
                COALESCE(rp."Apellidos", '')
            ) AS "NombreCompleto",
            COALESCE(da."Direccion", '') AS "Direccion",
            COALESCE(da."Barrio", '') AS "Barrio",
            COALESCE(rp."Celular", '') AS "Telefono",
            COALESCE(ca."NombreCargo", '') AS "Cargo",
            COALESCE(psy."FechaUltimoDiaLaborado", rl."FechaRetiro") AS "FechaAusencia"
        FROM public."RetiroLaboral" rl
        INNER JOIN public."RegistroPersonal" rp
            ON rl."IdRegistroPersonal" = rp."IdRegistroPersonal"
        LEFT JOIN public."VinculacionLaboral" vl
            ON vl."IdVinculacionLaboral" = rl."IdVinculacionLaboral"
        LEFT JOIN public."EmpresaContratante" ec
            ON ec."IdEmpresaContratante" = vl."IdEmpresaContratante"
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
    datos["EmpresaCodigo"] = _upper_text(datos.get("EmpresaCodigo"))
    datos["EmpresaNombre"] = _clean_text(datos.get("EmpresaNombre"))
    datos["EmpresaLogo"] = _clean_text(datos.get("EmpresaLogo"))

    return datos


def generar_primer_llamado(db, id_retiro_laboral: int):
    if not TEMPLATE_PRIMER_LLAMADO.exists():
        raise FileNotFoundError(f"No se encontró la plantilla: {TEMPLATE_PRIMER_LLAMADO}")

    datos = obtener_datos_primer_llamado(db, id_retiro_laboral)
    empresa_codigo = _validar_empresa_rrll(datos)

    doc = Document(str(TEMPLATE_PRIMER_LLAMADO))
    _aplicar_membrete_rrll(doc, datos)
    _insertar_firma_yeny(doc, empresa_codigo=empresa_codigo)

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
        "{{ASUNTO}}": "PRIMER LLAMADO ABANDONO INASISTENCIA AL CARGO",
    }

    for paragraph in doc.paragraphs:
        _replace_text_in_paragraph(paragraph, replacements)

    for table in doc.tables:
        _replace_text_in_table(table, replacements)

    output_path = _build_output_path(id_retiro_laboral, "primer_llamado_retiro")
    doc.save(str(output_path))
    return output_path


def generar_segundo_llamado(db, id_retiro_laboral: int):
    if not TEMPLATE_SEGUNDO_LLAMADO.exists():
        raise FileNotFoundError(f"No se encontró la plantilla: {TEMPLATE_SEGUNDO_LLAMADO}")

    datos = obtener_datos_primer_llamado(db, id_retiro_laboral)
    empresa_codigo = _validar_empresa_rrll(datos)

    doc = Document(str(TEMPLATE_SEGUNDO_LLAMADO))
    _aplicar_membrete_rrll(doc, datos)
    _insertar_firma_yeny(doc, empresa_codigo=empresa_codigo)

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
        "{{ASUNTO}}": "SEGUNDO LLAMADO ABANDONO INASISTENCIA AL CARGO",
    }

    for paragraph in doc.paragraphs:
        _replace_text_in_paragraph(paragraph, replacements)

    for table in doc.tables:
        _replace_text_in_table(table, replacements)

    output_path = _build_output_path(id_retiro_laboral, "segundo_llamado_retiro")
    doc.save(str(output_path))
    return output_path


def generar_carta_finalizacion(db, id_retiro_laboral: int):
    if not TEMPLATE_CARTA_FINALIZACION.exists():
        raise FileNotFoundError(f"No se encontró la plantilla: {TEMPLATE_CARTA_FINALIZACION}")

    datos = obtener_datos_primer_llamado(db, id_retiro_laboral)
    empresa_codigo = _validar_empresa_rrll(datos)

    doc = Document(str(TEMPLATE_CARTA_FINALIZACION))
    _aplicar_membrete_finalizacion(doc, datos)
    _insertar_firma_yeny(
        doc,
        modo_compacto=True,
        empresa_codigo=empresa_codigo,
    )

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
        "{{ASUNTO}}": "FINALIZACION DE CONTRATO POR INASISTENCIA Y ABANDONO AL CARGO DE TRABAJO",
    }

    for paragraph in doc.paragraphs:
        _replace_text_in_paragraph(paragraph, replacements)

        # Solo en la carta de finalización:
        # desplaza el asunto hacia la derecha como en el formato de referencia.
        if "FINALIZACION DE CONTRATO POR INASISTENCIA Y ABANDONO AL CARGO DE TRABAJO" in paragraph.text:
            paragraph.alignment = WD_ALIGN_PARAGRAPH.RIGHT
            paragraph.paragraph_format.left_indent = Inches(1.50)
            paragraph.paragraph_format.keep_together = True
            paragraph.paragraph_format.keep_with_next = False

    for table in doc.tables:
        _replace_text_in_table(table, replacements)

    output_path = _build_output_path(id_retiro_laboral, "carta_finalizacion_retiro")
    doc.save(str(output_path))
    return output_path


def generar_paquete_retiro(db, id_retiro_laboral: int):
    if not TEMPLATE_PAQUETE_RETIRO.exists():
        raise FileNotFoundError(f"No se encontró la plantilla: {TEMPLATE_PAQUETE_RETIRO}")

    datos = obtener_datos_primer_llamado(db, id_retiro_laboral)
    print("DEBUG DATOS PAQUETE:", datos)

    q_motivo = text("""
        SELECT "IdMotivoRetiro"
        FROM public."RetiroLaboral"
        WHERE "IdRetiroLaboral" = :id_retiro_laboral
        LIMIT 1;
    """)

    row_motivo = db.execute(q_motivo, {
        "id_retiro_laboral": id_retiro_laboral
    }).mappings().first()

    id_motivo = row_motivo["IdMotivoRetiro"] if row_motivo else None
    print("DEBUG ID MOTIVO RETIRO:", id_motivo)

    es_voluntario = (id_motivo == 1)

    if es_voluntario:
        print("DEBUG PAQUETE: usando plantilla VOLUNTARIO")
        doc = Document(str(TEMPLATE_PAQUETE_RETIRO_VOLUNTARIO))
    else:
        print("DEBUG PAQUETE: usando plantilla NORMAL")
        doc = Document(str(TEMPLATE_PAQUETE_RETIRO))

    empresa_codigo = _validar_empresa_rrll(datos)
    _aplicar_membrete_paquete(doc, datos)
    _insertar_firma_yeny(
        doc,
        modo_compacto=False,
        empresa_codigo=empresa_codigo,
        preservar_estructura_paginas=True,
    )

    # Solo Mantener: sube y compacta el bloque informativo para conservar
    # el paquete en tres hojas. ALP no entra en este ajuste.
    _compactar_informacion_paquete_mantener(
        doc,
        empresa_codigo,
        es_voluntario=es_voluntario,
    )

    # ALP + retiro voluntario: mantiene carta y examen en hojas independientes,
    # y hace que INFORMACIÓN IMPORTANTE comience obligatoriamente en la hoja siguiente.
    if empresa_codigo == "ALP" and es_voluntario:
        paragraphs = list(doc.paragraphs)
        inicio_info = None

        for paragraph in paragraphs:
            texto = _clean_text(paragraph.text).upper()
            if "INFORMACIÓN IMPORTANTE" in texto or "INFORMACION IMPORTANTE" in texto:
                inicio_info = paragraph
                break

        if inicio_info is not None:
            # El título nunca puede quedar pegado al final de la hoja del examen.
            inicio_info.paragraph_format.page_break_before = True
            inicio_info.paragraph_format.space_before = 0
            inicio_info.paragraph_format.space_after = Pt(3)
            inicio_info.paragraph_format.keep_with_next = True

            # Desde INFORMACIÓN IMPORTANTE en adelante aumentamos ligeramente
            # la letra para aprovechar mejor las hojas 3 y 4 y mejorar legibilidad.
            encontrado = False
            for paragraph in paragraphs:
                texto = _clean_text(paragraph.text).upper()
                if paragraph._p is inicio_info._p:
                    encontrado = True

                if not encontrado:
                    continue

                paragraph.paragraph_format.space_before = 0
                paragraph.paragraph_format.space_after = 0
                paragraph.paragraph_format.line_spacing = 1.0

                es_titulo = (
                    "INFORMACIÓN IMPORTANTE" in texto
                    or "INFORMACION IMPORTANTE" in texto
                )

                for run in paragraph.runs:
                    if es_titulo:
                        if run.font.size is None or run.font.size.pt < 9:
                            run.font.size = Pt(9)
                    else:
                        if run.font.size is None or run.font.size.pt < 8.5:
                            run.font.size = Pt(8.5)

            # Recupera apenas el espacio necesario para que el bloque final
            # RECIBIDO / FECHA permanezca en la hoja 4. No toca hojas 1-2
            # ni modifica otros tipos de documento.
            for paragraph in paragraphs:
                texto = _clean_text(paragraph.text).upper()
                if "RECIBIDO" in texto or "{{FECHA_FIN}}" in paragraph.text:
                    paragraph.paragraph_format.space_before = 0
                    paragraph.paragraph_format.space_after = 0
                    paragraph.paragraph_format.line_spacing = 0.90
                    paragraph.paragraph_format.keep_together = False
                    paragraph.paragraph_format.keep_with_next = False

            # Compacta ligeramente el bloque informativo ALP voluntario.
            # La reducción es mínima para conservar la legibilidad ya validada,
            # pero evita que la fecha final quede sola en una quinta hoja.
            encontrado = False
            for paragraph in paragraphs:
                if paragraph._p is inicio_info._p:
                    encontrado = True
                if not encontrado:
                    continue
                texto = _clean_text(paragraph.text).upper()
                if "INFORMACIÓN IMPORTANTE" not in texto and "INFORMACION IMPORTANTE" not in texto:
                    paragraph.paragraph_format.line_spacing = 0.94

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
    }

    for paragraph in doc.paragraphs:
        _replace_text_in_paragraph(paragraph, replacements)

    for table in doc.tables:
        _replace_text_in_table(table, replacements)

    output_path = _build_output_path(id_retiro_laboral, "paquete_retiro")
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