from pathlib import Path
from datetime import datetime, date

from PIL import Image

from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import letter
from reportlab.lib.utils import ImageReader
from reportlab.platypus import Paragraph
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.enums import TA_JUSTIFY


BASE_DIR = Path(__file__).resolve().parents[2]
ASSETS = BASE_DIR / "assets" / "comunicaciones"

LOGO_EMPRESA = ASSETS / "LOGO_EMPRESA.jpeg"
LOGO_CERTIFICACIONES = ASSETS / "LOGO_CERTIFICACIONES.jpeg"
LOGO_ISSA = ASSETS / "LOGO_ISSA.jpeg.png"
LOGO_MANTENER = ASSETS / "LOGO_MANTENER_INGENIERIA.png"
FIRMA = ASSETS / "FIRMA_EMPLEADOR.png"

OUTPUT = BASE_DIR.parent / "storage" / "nomina" / "comunicaciones"
OUTPUT.mkdir(parents=True, exist_ok=True)

ASSETS_LIMPIOS = OUTPUT / "_assets_limpios"
ASSETS_LIMPIOS.mkdir(parents=True, exist_ok=True)


def limpiar_fondo_imagen(ruta_original: Path, tolerancia: int = 45) -> Path:
    if not ruta_original.exists():
        return ruta_original

    ruta_limpia = ASSETS_LIMPIOS / f"{ruta_original.stem}_limpio.png"

    imagen = Image.open(ruta_original).convert("RGBA")
    pixeles = imagen.load()
    ancho, alto = imagen.size

    fondo = pixeles[0, 0][:3]

    for y in range(alto):
        for x in range(ancho):
            r, g, b, a = pixeles[x, y]
            distancia = abs(r - fondo[0]) + abs(g - fondo[1]) + abs(b - fondo[2])

            if distancia <= tolerancia or (r > 235 and g > 235 and b > 235):
                pixeles[x, y] = (255, 255, 255, 0)

    imagen.save(ruta_limpia)
    return ruta_limpia


class CertificadoLaboralPDF:
    def __init__(self, datos):
        self.datos = datos
        self.width, self.height = letter
        self.fecha = datetime.now()

        carpeta = OUTPUT / str(self.datos["IdRetiroLaboral"])
        carpeta.mkdir(parents=True, exist_ok=True)

        self.ruta_pdf = carpeta / f"certificado_laboral_{self.datos['IdRetiroLaboral']}.pdf"
        self.pdf = canvas.Canvas(str(self.ruta_pdf), pagesize=letter)

    def valor(self, campo, defecto=""):
        valor = self.datos.get(campo)
        if valor is None:
            return defecto
        return str(valor).strip()

    def fecha_texto(self, valor=None):
        meses = [
            "enero", "febrero", "marzo", "abril", "mayo", "junio",
            "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre"
        ]

        if isinstance(valor, datetime):
            fecha = valor.date()
        elif isinstance(valor, date):
            fecha = valor
        elif isinstance(valor, str) and valor:
            try:
                fecha = datetime.fromisoformat(valor.replace("Z", "")).date()
            except Exception:
                return valor
        else:
            fecha = datetime.now().date()

        return f"{fecha.day} de {meses[fecha.month - 1]} de {fecha.year}"

    def encabezado(self):
        if LOGO_EMPRESA.exists():
            logo_empresa_limpio = limpiar_fondo_imagen(LOGO_EMPRESA, tolerancia=55)
            self.pdf.drawImage(
                ImageReader(str(logo_empresa_limpio)),
                45,
                self.height - 95,
                width=160,
                height=60,
                preserveAspectRatio=True,
                mask="auto"
            )

        if LOGO_CERTIFICACIONES.exists():
            self.pdf.drawImage(ImageReader(str(LOGO_CERTIFICACIONES)), 215, self.height - 96, width=95, height=55, preserveAspectRatio=True, mask="auto")

        if LOGO_ISSA.exists():
            self.pdf.drawImage(ImageReader(str(LOGO_ISSA)), 315, self.height - 90, width=75, height=40, preserveAspectRatio=True, mask="auto")

        if LOGO_MANTENER.exists():
            self.pdf.drawImage(ImageReader(str(LOGO_MANTENER)), self.width - 180, self.height - 92, width=130, height=48, preserveAspectRatio=True, mask="auto")

        self.pdf.setFont("Helvetica-Bold", 12)
        self.pdf.drawCentredString(self.width / 2, self.height - 155, "EL DEPARTAMENTO DE TALENTO HUMANO")

        self.pdf.setFont("Helvetica-Bold", 12)
        self.pdf.drawCentredString(self.width / 2, self.height - 190, "CERTIFICA")

    def firma(self):
        if FIRMA.exists():
            firma_limpia = limpiar_fondo_imagen(FIRMA, tolerancia=70)
            self.pdf.drawImage(
                ImageReader(str(firma_limpia)),
                120,
                178,
                width=130,
                height=60,
                preserveAspectRatio=True,
                mask="auto"
            )

    def parrafo_justificado(self, texto, x, y, ancho, alto, size=8.5):
        estilo = ParagraphStyle(
            name="justificado",
            fontName="Helvetica",
            fontSize=size,
            leading=size + 4,
            alignment=TA_JUSTIFY,
            spaceAfter=0,
            spaceBefore=0,
        )

        p = Paragraph(texto, estilo)
        p.wrapOn(self.pdf, ancho, alto)
        p.drawOn(self.pdf, x, y)

    def cuerpo(self):
        nombre = f"{self.valor('Nombres')} {self.valor('Apellidos')}".upper()
        documento = self.valor("NumeroIdentificacion")
        tipo = self.valor("TipoDocumentoNombre", "Cédula de Ciudadanía")
        ciudad = self.valor("LugarExpedicion", "BOGOTÁ").upper()
        cargo = self.valor("CargoNombre", "NO REGISTRADO").upper()

        fecha_ingreso = self.fecha_texto(self.datos.get("FechaIngreso"))
        fecha_retiro = self.fecha_texto(self.datos.get("FechaRetiro"))

        salario_raw = self.datos.get("Salario")
        salario = f"$ {float(salario_raw):,.0f}".replace(",", ".") if salario_raw else "SEGÚN NÓMINA"

        x = 120
        ancho = 360

        texto_principal = (
            f"Que el señor {nombre}, identificado con el número de {tipo} No. {documento} "
            f"de {ciudad}, laboró en nuestra empresa con contrato a término Labor Contratada "
            f"desde el {fecha_ingreso} hasta el {fecha_retiro}; desempeñando el cargo de {cargo}"
        )

        self.parrafo_justificado(texto_principal, x=x, y=self.height - 285, ancho=ancho, alto=80, size=8.5)

        self.pdf.setFont("Helvetica", 8.5)
        self.pdf.drawString(170, self.height - 325, "Salario Básico mensual")

        self.pdf.setFont("Helvetica-Bold", 8.5)
        self.pdf.drawString(355, self.height - 325, salario)

        texto_info = (
            "Para mayor información de ser necesario, se pueden comunicar al PBX "
            "4204893 EXT 1046, ó al numero celular 3176456953, ó al correo "
            "electronico contratacion@aseoslaperfeccion.com ."
        )

        self.parrafo_justificado(texto_info, x=x, y=self.height - 425, ancho=ancho, alto=70, size=8.5)

        texto_fecha = (
            f"La presente certificación se expide a solicitud del interesado, dado el "
            f"{self.fecha_texto()} en la ciudad de BOGOTA"
        )

        self.parrafo_justificado(texto_fecha, x=x, y=self.height - 510, ancho=ancho, alto=45, size=8.5)

        self.pdf.setFont("Helvetica", 8.5)
        self.pdf.drawString(120, self.height - 560, "Cordialmente,")

        self.firma()

        self.pdf.line(120, 170, 295, 170)

        self.pdf.setFont("Helvetica-Bold", 8.5)
        self.pdf.drawString(120, 155, "Yina Cumbe")

        self.pdf.setFont("Helvetica", 8.5)
        self.pdf.drawString(120, 142, "Talento Humano")

    def pie(self):
        self.pdf.setFont("Helvetica", 5.6)
        self.pdf.drawCentredString(self.width / 2, 72, "TÉCNICOS EN LIMPIEZA DE: EMPRESAS, BANCOS, COLEGIOS, UNIVERSIDADES, CENTROS COMERCIALES, CENTROS DE RECREACIÓN")
        self.pdf.drawCentredString(self.width / 2, 63, "EDIFICIOS OFICINAS Y VIVIENDAS, HOSPITALES, SUPERMERCADOS, LAVADO Y PINTURA DE FACHADAS, LAVADO DE VIDRIOS, TAPETES Y CORTINAS")

        self.pdf.line(40, 55, self.width - 40, 55)

        self.pdf.setFont("Helvetica", 6.5)
        self.pdf.drawCentredString(self.width / 2, 40, "Calle 4 Bis No. 53C-50 • PBX: 420 48 93 - 261 32 74 - 261 46 25 • Bogotá, D.C. - Colombia")
        self.pdf.drawCentredString(self.width / 2, 27, "www.aseoslaperfeccion.com        comercial@aseoslaperfeccion.com")

    def generar(self):
        self.encabezado()
        self.cuerpo()
        self.pie()
        self.pdf.save()
        return str(self.ruta_pdf)


def generar_certificado_laboral(datos):
    pdf = CertificadoLaboralPDF(datos)
    return pdf.generar()