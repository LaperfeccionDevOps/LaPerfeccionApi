from pathlib import Path
from datetime import datetime, date
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy import text
from sqlalchemy.orm import Session

from infrastructure.db.deps import get_db
from services.pdfs.certificado_laboral_pdf import generar_certificado_laboral

router = APIRouter(
    prefix="/api/nomina-comunicaciones",
    tags=["Nómina Comunicaciones"]
)

BASE_DIR = Path("storage/nomina/comunicaciones")
BASE_DIR.mkdir(parents=True, exist_ok=True)


def obtener_datos_trabajador(db: Session, id_retiro_laboral: int):
    row = db.execute(text("""
        SELECT
            rl."IdRetiroLaboral",
            rl."IdRegistroPersonal",
            rl."FechaRetiro",

            rp."NumeroIdentificacion",
            rp."Nombres",
            rp."Apellidos",
            rp."Email",
            rp."Celular",
            rp."LugarExpedicion",

            ti."Codigo" AS "TipoDocumentoCodigo",
            ti."Descripcion" AS "TipoDocumentoNombre",

            COALESCE(c."NombreCargo", acc_c."NombreCargo") AS "CargoNombre",

            fc."Nombre" AS "FondoCesantiasNombre",
            cb."FechaIngreso" AS "FechaIngreso",
            acc."Salario" AS "Salario"

        FROM public."RetiroLaboral" rl
        INNER JOIN public."RegistroPersonal" rp
            ON rp."IdRegistroPersonal" = rl."IdRegistroPersonal"

        LEFT JOIN public."TipoIdentificacion" ti
            ON ti."IdTipoIdentificacion" = rp."IdTipoIdentificacion"

        LEFT JOIN public."Cargo" c
            ON c."IdCargo"::text = rp."IdCargo"::text

        LEFT JOIN public."FondoCesantias" fc
            ON fc."IdFondoCesantias" = rp."IdFondoCesantias"

        LEFT JOIN public."ContratacionBasica" cb
            ON cb."IdRegistroPersonal" = rp."IdRegistroPersonal"

        LEFT JOIN public."AsignacionCargoCliente" acc
            ON acc."IdRegistroPersonal" = rp."IdRegistroPersonal"      

        LEFT JOIN public."Cargo" acc_c
            ON acc_c."IdCargo" = acc."IdCargo"            

        WHERE rl."IdRetiroLaboral" = :id_retiro_laboral
        LIMIT 1;
    """), {"id_retiro_laboral": id_retiro_laboral}).mappings().first()

    if not row:
        raise HTTPException(status_code=404, detail="Retiro laboral no encontrado.")

    return dict(row)


def guardar_trazabilidad(db: Session, datos: dict, tipo_documento: str, ruta_pdf: str, usuario: str = "nomina"):
    db.execute(text("""
        INSERT INTO public."ComunicacionTrabajador" (
            "IdRegistroPersonal",
            "IdRetiroLaboral",
            "TipoDocumento",
            "CanalCorreo",
            "CanalWhatsapp",
            "CorreoDestino",
            "CelularDestino",
            "EstadoCorreo",
            "EstadoWhatsapp",
            "RutaPdf",
            "FechaGeneracion",
            "FechaEnvio",
            "UsuarioEnvio",
            "Activo",
            "FechaCreacion"
        )
        VALUES (
            :IdRegistroPersonal,
            :IdRetiroLaboral,
            :TipoDocumento,
            true,
            true,
            :CorreoDestino,
            :CelularDestino,
            'GENERADO',
            'GENERADO',
            :RutaPdf,
            CURRENT_TIMESTAMP,
            NULL,
            :UsuarioEnvio,
            true,
            CURRENT_TIMESTAMP
        );
    """), {
        "IdRegistroPersonal": datos["IdRegistroPersonal"],
        "IdRetiroLaboral": datos["IdRetiroLaboral"],
        "TipoDocumento": tipo_documento,
        "CorreoDestino": datos.get("Email"),
        "CelularDestino": datos.get("Celular"),
        "RutaPdf": ruta_pdf,
        "UsuarioEnvio": usuario,
    })


def generar_pdf_simple(datos: dict, tipo_documento: str):
    try:
        from reportlab.lib.pagesizes import letter
        from reportlab.pdfgen import canvas
    except Exception:
        raise HTTPException(
            status_code=500,
            detail="Falta instalar reportlab. Ejecuta: pip install reportlab"
        )

    def limpiar(valor, defecto=""):
        return str(valor or defecto).strip()

    def fecha_larga_colombia(valor=None):
        meses = [
            "enero", "febrero", "marzo", "abril", "mayo", "junio",
            "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre"
        ]

        if isinstance(valor, str) and valor:
            try:
                fecha = datetime.fromisoformat(valor.replace("Z", "")).date()
            except Exception:
                return valor
        elif isinstance(valor, datetime):
            fecha = valor.date()
        elif isinstance(valor, date):
            fecha = valor
        else:
            fecha = datetime.now().date()

        return f"{fecha.day} de {meses[fecha.month - 1]} de {fecha.year}"

    nombre = f'{limpiar(datos.get("Nombres"))} {limpiar(datos.get("Apellidos"))}'.upper()
    cedula = limpiar(datos.get("NumeroIdentificacion"))
    tipo_doc = limpiar(datos.get("TipoDocumentoCodigo"), "CC").upper()
    tipo_doc_nombre = limpiar(datos.get("TipoDocumentoNombre"), "CÉDULA DE CIUDADANÍA").upper()
    ciudad_exp = limpiar(datos.get("LugarExpedicion"), "BOGOTÁ").upper()
    cargo = limpiar(datos.get("CargoNombre"), "CARGO NO REGISTRADO").upper()
    fondo = limpiar(datos.get("FondoCesantiasNombre"), "FONDO DE CESANTÍAS").upper()
    fecha_retiro = fecha_larga_colombia(datos.get("FechaRetiro"))
    fecha_hoy = fecha_larga_colombia()

    carpeta = BASE_DIR / str(datos["IdRetiroLaboral"])
    carpeta.mkdir(parents=True, exist_ok=True)

    archivo = carpeta / f"{tipo_documento}_{datos['IdRetiroLaboral']}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"

    assets_dir = Path(__file__).resolve().parents[2] / "assets" / "comunicaciones"
    logo_lp = assets_dir / "LOGO_EMPRESA.jpeg"

    logo_mantener = assets_dir / "LOGO_MANTENER_INGENIERIA.png"

    firma_yina = assets_dir / "FIRMA_EMPLEADOR.png"

    c = canvas.Canvas(str(archivo), pagesize=letter)
    width, height = letter

    def dibujar_encabezado():
        if logo_lp.exists():
            c.drawImage(str(logo_lp), 70, height - 95, width=220, height=60, preserveAspectRatio=True, mask="auto")

        if logo_mantener.exists():
            c.drawImage(str(logo_mantener), width - 185, height - 92, width=125, height=50, preserveAspectRatio=True, mask="auto")

    def dibujar_firma(y, cargo_firma):
        if firma_yina.exists():
            c.drawImage(str(firma_yina), 80, y + 35, width=130, height=58, preserveAspectRatio=True, mask="auto")

        c.line(80, y + 30, 230, y + 30)
        c.setFont("Helvetica-Bold", 9)
        c.drawString(80, y + 15, "Yina Cumbe")
        c.setFont("Helvetica-Bold", 9)
        c.drawString(80, y, cargo_firma)

    def dibujar_pie():
        c.setFont("Helvetica", 5.4)
        c.drawCentredString(width / 2, 70, "TÉCNICOS EN LIMPIEZA DE: EMPRESAS, BANCOS, COLEGIOS, UNIVERSIDADES, CENTROS COMERCIALES, CENTROS DE RECREACIÓN,")
        c.drawCentredString(width / 2, 62, "EDIFICIOS OFICINAS Y VIVIENDAS, HOSPITALES, SUPERMERCADOS, LAVADO Y PINTURA DE FACHADAS, LAVADO DE VIDRIOS, TAPETES Y CORTINAS")
        c.line(70, 55, width - 70, 55)
        c.setFont("Helvetica", 6)
        c.drawCentredString(width / 2, 42, "Calle 4 Bis No. 53C-50 • PBX: 420 48 93 - 261 32 74 - 261 46 25 • Bogotá, D.C. - Colombia")
        c.drawCentredString(width / 2, 30, "www.aseoslaperfeccion.com        comercial@aseoslaperfeccion.com")

    dibujar_encabezado()

    if tipo_documento == "CERTIFICADO_LABORAL":
        c.setFont("Helvetica-Bold", 12)
        c.drawCentredString(width / 2, height - 145, "EL DEPARTAMENTO DE TALENTO HUMANO")
        c.drawCentredString(width / 2, height - 175, "CERTIFICA")

        c.setFont("Helvetica", 9)
        texto_cert = c.beginText(95, height - 235)
        texto_cert.setLeading(14)
        texto_cert.textLine(f"Que el señor {nombre}, identificado con el número")
        texto_cert.textLine(f"de {tipo_doc_nombre} No. {cedula} de {ciudad_exp}, laboró en nuestra")
        texto_cert.textLine("empresa con contrato a término Labor Contratada; desempeñando el cargo de")
        texto_cert.textLine(f"{cargo}.")
        c.drawText(texto_cert)

        c.setFont("Helvetica", 9)
        c.drawString(145, height - 335, "Salario Básico mensual")
        c.setFont("Helvetica-Bold", 9)
        salario = datos.get("Salario")

        if salario:
            salario = f"$ {salario:,.0f}".replace(",", ".")
        else:
            salario = "NO REGISTRADO"

        c.drawString(
            320,
            height - 335,
            salario
        )

        c.setFont("Helvetica", 8.5)
        texto_info = c.beginText(95, height - 385)
        texto_info.setLeading(13)
        texto_info.textLine("Para mayor información de ser necesario, se pueden comunicar al PBX")
        texto_info.textLine("4204893 EXT 1046, al número celular 3176456953, ó al correo")
        texto_info.textLine("electronico contratacion@aseoslaperfeccion.com.")
        c.drawText(texto_info)

        c.setFont("Helvetica", 8.5)
        texto_fecha = c.beginText(95, height - 465)
        texto_fecha.setLeading(13)
        texto_fecha.textLine("La presente certificación se expide a solicitud del interesado, dado el día")
        texto_fecha.textLine(f"{fecha_hoy} en la ciudad de BOGOTÁ D.C.")
        c.drawText(texto_fecha)

        c.setFont("Helvetica", 9)
        c.drawString(95, height - 540, "Cordialmente,")
        dibujar_firma(y=145, cargo_firma="Talento Humano")

    elif tipo_documento == "CARTA_CESANTIAS":
        c.setFont("Helvetica", 11)
        c.drawString(90, height - 135, f"Bogotá D.C., {fecha_hoy}")

        c.drawString(90, height - 205, "Señores")
        c.setFont("Helvetica-Bold", 11)
        c.drawString(90, height - 223, fondo)
        c.setFont("Helvetica", 11)
        c.drawString(90, height - 241, "Ciudad")

        c.rect(85, height - 315, width - 170, 22)
        c.setFont("Helvetica-Bold", 11)
        c.drawString(92, height - 309, "REF:")
        c.drawCentredString(width / 2, height - 309, "AUTORIZACION PAGO DE CESANTIAS")

        c.setFont("Helvetica", 11)
        texto_ces = c.beginText(90, height - 370)
        texto_ces.setLeading(16)
        texto_ces.textLine("Respetados señores:")
        texto_ces.textLine("Nos permitimos solicitar a ustedes se sirvan autorizar el pago de la referencia a favor")
        texto_ces.textLine(f"de señor(a) {nombre}, identificado(a)")
        texto_ces.textLine(f"con {tipo_doc} número {cedula} expedido en {ciudad_exp},")
        texto_ces.textLine(f"quien trabajó para la empresa hasta el día {fecha_retiro}.")
        c.drawText(texto_ces)

        c.setFont("Helvetica", 11)
        c.drawString(90, height - 525, "Atentamente,")
        dibujar_firma(y=135, cargo_firma="Coordinadora de Compensación y Beneficios")

        c.setFont("Helvetica", 9)
        c.drawString(90, 100, "Copia: Hoja de vida")
        c.setFont("Helvetica", 6)
        c.drawString(90, 91, "NMS")

    dibujar_pie()
    c.save()
    return str(archivo)


@router.get("/{id_retiro_laboral}/certificado-laboral/descargar")
def descargar_certificado_laboral(
    id_retiro_laboral: int,
    db: Session = Depends(get_db)
):
    datos = obtener_datos_trabajador(db, id_retiro_laboral)
    ruta_pdf = generar_certificado_laboral(datos)
    guardar_trazabilidad(db, datos, "CERTIFICADO_LABORAL", ruta_pdf)
    db.commit()

    return FileResponse(
        ruta_pdf,
        media_type="application/pdf",
        filename=f"certificado_laboral_{datos['NumeroIdentificacion']}.pdf"
    )


@router.get("/{id_retiro_laboral}/carta-cesantias/descargar")
def descargar_carta_cesantias(
    id_retiro_laboral: int,
    db: Session = Depends(get_db)
):
    datos = obtener_datos_trabajador(db, id_retiro_laboral)
    ruta_pdf = generar_pdf_simple(datos, "CARTA_CESANTIAS")
    guardar_trazabilidad(db, datos, "CARTA_CESANTIAS", ruta_pdf)
    db.commit()

    return FileResponse(
        ruta_pdf,
        media_type="application/pdf",
        filename=f"carta_cesantias_{datos['NumeroIdentificacion']}.pdf"
    )