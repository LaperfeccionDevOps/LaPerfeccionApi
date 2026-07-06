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


class CartaCesantiasPDF:
    def __init__(self, datos):
        self.datos = datos
        self.width, self.height = letter
        self.fecha = datetime.now()

        carpeta = OUTPUT / str(self.datos["IdRetiroLaboral"])
        carpeta.mkdir(parents=True, exist_ok=True)

        self.ruta_pdf = carpeta / f"carta_cesantias_{self.datos['IdRetiroLaboral']}.pdf"
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
                35,
                self.height - 75,
                width=155,
                height=55,
                preserveAspectRatio=True,
                mask="auto"
            )

        if LOGO_CERTIFICACIONES.exists():
            self.pdf.drawImage(ImageReader(str(LOGO_CERTIFICACIONES)), 190, self.height - 73, width=85, height=45, preserveAspectRatio=True, mask="auto")

        if LOGO_ISSA.exists():
            self.pdf.drawImage(ImageReader(str(LOGO_ISSA)), 275, self.height - 70, width=65, height=35, preserveAspectRatio=True, mask="auto")

        if LOGO_MANTENER.exists():
            self.pdf.drawImage(ImageReader(str(LOGO_MANTENER)), self.width - 175, self.height - 72, width=125, height=45, preserveAspectRatio=True, mask="auto")

    def parrafo(self, texto, x, y, ancho, alto, size=8.5, bold=False):
        estilo = ParagraphStyle(
            name="parrafo",
            fontName="Helvetica-Bold" if bold else "Helvetica",
            fontSize=size,
            leading=size + 3,
            alignment=TA_JUSTIFY,
            spaceAfter=0,
            spaceBefore=0,
        )

        p = Paragraph(texto, estilo)
        p.wrapOn(self.pdf, ancho, alto)
        p.drawOn(self.pdf, x, y)

    def firma(self):
        if FIRMA.exists():
            firma_limpia = limpiar_fondo_imagen(FIRMA, tolerancia=70)
            self.pdf.drawImage(
                ImageReader(str(firma_limpia)),
                65,
                175,
                width=130,
                height=60,
                preserveAspectRatio=True,
                mask="auto"
            )

    def cuerpo(self):
        nombre = f"{self.valor('Nombres')} {self.valor('Apellidos')}".upper()
        documento = self.valor("NumeroIdentificacion")
        tipo = self.valor("TipoDocumentoNombre", "Cédula de Ciudadanía")
        ciudad = self.valor("LugarExpedicion", "BOGOTÁ").upper()
        fondo = self.valor("FondoCesantiasNombre", "FONDO DE CESANTÍAS").upper()
        fecha_retiro = self.fecha_texto(self.datos.get("FechaRetiro"))

        x = 65
        ancho = 465

        self.pdf.setFont("Helvetica", 9)
        self.pdf.drawString(x, self.height - 115, f"Bogotá D.C., {self.fecha_texto()}")

        self.pdf.setFont("Helvetica", 9)
        self.pdf.drawString(x, self.height - 175, "Señores")

        self.pdf.setFont("Helvetica-Bold", 9)
        self.pdf.drawString(x, self.height - 190, fondo)

        self.pdf.setFont("Helvetica", 9)
        self.pdf.drawString(x, self.height - 205, "Ciudad")

        self.pdf.rect(x - 5, self.height - 260, ancho, 18, stroke=1, fill=0)

        self.pdf.setFont("Helvetica-Bold", 9)
        self.pdf.drawString(x, self.height - 255, "REF:")
        self.pdf.drawString(x + 115, self.height - 255, "AUTORIZACION PAGO DE CESANTIAS")

        self.pdf.setFont("Helvetica", 9)
        self.pdf.drawString(x, self.height - 320, "Respetados señores:")

        texto = (
            f"Nos permitimos solicitar a ustedes se sirvan autorizar el pago de la referencia a favor "
            f"de señor(a) <b>{nombre}</b> identificado(a) con <b>{tipo}</b> número "
            f"<b>{documento}</b> expedido en <b>{ciudad}</b>, quien trabajó para la empresa "
            f"hasta el día <b>{fecha_retiro}</b>"
        )

        self.parrafo(
            texto,
            x=x,
            y=self.height - 375,
            ancho=ancho,
            alto=60,
            size=9
        )

        self.pdf.setFont("Helvetica", 9)
        self.pdf.drawString(x, self.height - 500, "Atentamente,")

        self.firma()

        self.pdf.line(65, 165, 240, 165)

        self.pdf.setFont("Helvetica-Bold", 9)
        self.pdf.drawString(65, 148, "YINA CUMBE BUESAQUILLO")
        self.pdf.drawString(65, 135, "Coordinadora de Compensación y Beneficios")

        self.pdf.setFont("Helvetica", 8)
        self.pdf.drawString(65, 105, "Copia: Hoja de vida")
        self.pdf.setFont("Helvetica", 5)
        self.pdf.drawString(65, 96, "NMS")

    def pie(self):
        self.pdf.setFont("Helvetica", 5.4)
        self.pdf.drawCentredString(
            self.width / 2,
            58,
            "TÉCNICOS EN LIMPIEZA DE: EMPRESAS, BANCOS, COLEGIOS, UNIVERSIDADES, CENTROS COMERCIALES, CENTROS DE RECREACIÓN"
        )
        self.pdf.drawCentredString(
            self.width / 2,
            50,
            "EDIFICIOS OFICINAS Y VIVIENDAS, HOSPITALES, SUPERMERCADOS, LAVADO Y PINTURA DE FACHADAS, LAVADO DE VIDRIOS, TAPETES Y CORTINAS"
        )

        self.pdf.line(55, 44, self.width - 55, 44)

        self.pdf.setFont("Helvetica", 6)
        self.pdf.drawCentredString(
            self.width / 2,
            32,
            "Calle 4 Bis No. 53C-50 • Bogotá D.C. • PBX: 4204893"
        )

        self.pdf.drawCentredString(
            self.width / 2,
            21,
            "documentos@aseoslaperfeccion.com - comercial@aseoslaperfeccion.com"
        )

        self.pdf.drawCentredString(
            self.width / 2,
            11,
            "www.aseoslaperfeccion.com"
        )

    def generar(self):
        self.encabezado()
        self.cuerpo()
        self.pie()
        self.pdf.save()
        return str(self.ruta_pdf)


def generar_carta_cesantias(datos):
    pdf = CartaCesantiasPDF(datos)
    return pdf.generar()