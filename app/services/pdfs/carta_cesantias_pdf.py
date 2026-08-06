from pathlib import Path
from datetime import datetime, date

from PIL import Image, ImageFilter, ImageOps
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
FIRMA = ASSETS / "FIRMA_EMPLEADORV1.png"

OUTPUT = BASE_DIR.parent / "storage" / "nomina" / "comunicaciones"
OUTPUT.mkdir(parents=True, exist_ok=True)

ASSETS_LIMPIOS = OUTPUT / "_assets_limpios"
ASSETS_LIMPIOS.mkdir(parents=True, exist_ok=True)


def limpiar_fondo_imagen(ruta_original: Path, nombre_salida: str) -> Path:
    ruta_salida = ASSETS_LIMPIOS / nombre_salida

    if not ruta_original.exists():
        return ruta_original

    with Image.open(ruta_original) as imagen_original:
        img = imagen_original.convert("RGBA")

    pixeles = list(img.getdata())
    nuevos_pixeles = []

    for r, g, b, a in pixeles:
        promedio = (r + g + b) / 3
        diferencia = max(r, g, b) - min(r, g, b)

        es_blanco = r > 235 and g > 235 and b > 235
        es_gris_claro = promedio > 205 and diferencia < 28
        es_azul_claro = r > 175 and g > 215 and b > 220
        es_fondo_suave = promedio > 220

        if es_blanco or es_gris_claro or es_azul_claro or es_fondo_suave:
            nuevos_pixeles.append((255, 255, 255, 0))
        else:
            nuevos_pixeles.append((r, g, b, a))

    img.putdata(nuevos_pixeles)
    img.save(ruta_salida, "PNG")
    return ruta_salida


def preparar_firma(ruta_original: Path, nombre_salida: str) -> Path:
    """
    Limpia la foto de la firma sin dejar el rectángulo gris del papel.

    El proceso:
    - corrige sombras e iluminación irregular del papel;
    - conserva únicamente los trazos oscuros de la firma;
    - convierte los trazos a negro;
    - deja el fondo completamente transparente;
    - recorta los espacios sobrantes.
    """
    ruta_salida = ASSETS_LIMPIOS / nombre_salida

    if not ruta_original.exists():
        print("No existe la firma original:", ruta_original)
        return ruta_original

    with Image.open(ruta_original) as imagen_original:
        imagen = imagen_original.convert("RGB")

    gris = ImageOps.grayscale(imagen)

    # Crear una referencia del fondo usando un desenfoque amplio.
    # Así se eliminan sombras, textura y cambios de iluminación del papel.
    fondo_estimado = gris.filter(
        ImageFilter.GaussianBlur(radius=28)
    )

    pixeles_gris = list(gris.getdata())
    pixeles_fondo = list(fondo_estimado.getdata())
    pixeles_salida = []

    for intensidad, fondo in zip(pixeles_gris, pixeles_fondo):
        # Diferencia local: los trazos de tinta son más oscuros
        # que el fondo cercano; la textura del papel casi no cambia.
        diferencia = max(0, fondo - intensidad)

        if diferencia <= 10:
            alfa = 0
        elif diferencia < 38:
            alfa = int(((diferencia - 10) / 28) * 255)
        else:
            alfa = 255

        pixeles_salida.append((0, 0, 0, alfa))

    firma_procesada = Image.new(
        "RGBA",
        gris.size,
        (255, 255, 255, 0),
    )
    firma_procesada.putdata(pixeles_salida)

    # Quitar puntos sueltos muy pequeños sin engrosar artificialmente la firma.
    alfa = firma_procesada.getchannel("A")
    alfa = alfa.filter(ImageFilter.MedianFilter(size=3))
    firma_procesada.putalpha(alfa)

    # Eliminar líneas horizontales aisladas que vienen de la fotografía.
    # Se borran únicamente componentes muy anchos, muy bajos y ubicados
    # en la parte inferior de la imagen, sin afectar los trazos de la firma.
    alfa = firma_procesada.getchannel("A")
    ancho_imagen, alto_imagen = alfa.size
    pixeles_alfa = alfa.load()
    visitados = set()

    for y in range(alto_imagen):
        for x in range(ancho_imagen):
            if pixeles_alfa[x, y] < 40 or (x, y) in visitados:
                continue

            pendientes = [(x, y)]
            componente = []
            visitados.add((x, y))

            minimo_x = maximo_x = x
            minimo_y = maximo_y = y

            while pendientes:
                actual_x, actual_y = pendientes.pop()
                componente.append((actual_x, actual_y))

                minimo_x = min(minimo_x, actual_x)
                maximo_x = max(maximo_x, actual_x)
                minimo_y = min(minimo_y, actual_y)
                maximo_y = max(maximo_y, actual_y)

                for vecino_x in range(actual_x - 1, actual_x + 2):
                    for vecino_y in range(actual_y - 1, actual_y + 2):
                        if (
                            0 <= vecino_x < ancho_imagen
                            and 0 <= vecino_y < alto_imagen
                            and (vecino_x, vecino_y) not in visitados
                            and pixeles_alfa[vecino_x, vecino_y] >= 40
                        ):
                            visitados.add((vecino_x, vecino_y))
                            pendientes.append((vecino_x, vecino_y))

            ancho_componente = maximo_x - minimo_x + 1
            alto_componente = maximo_y - minimo_y + 1
            relacion = ancho_componente / max(alto_componente, 1)

            es_linea_inferior = (
                minimo_y > int(alto_imagen * 0.55)
                and ancho_componente > int(ancho_imagen * 0.08)
                and alto_componente < int(alto_imagen * 0.10)
                and relacion > 4
            )

            if es_linea_inferior:
                for punto_x, punto_y in componente:
                    firma_procesada.putpixel(
                        (punto_x, punto_y),
                        (0, 0, 0, 0),
                    )

    # Recortar el área real de la firma.
    limites = firma_procesada.getchannel("A").getbbox()

    if limites:
        margen = 12

        izquierda = max(limites[0] - margen, 0)
        superior = max(limites[1] - margen, 0)
        derecha = min(limites[2] + margen, firma_procesada.width)
        inferior = min(limites[3] + margen, firma_procesada.height)

        firma_procesada = firma_procesada.crop(
            (izquierda, superior, derecha, inferior)
        )

    firma_procesada.save(
        ruta_salida,
        "PNG",
        optimize=True,
        dpi=(300, 300),
    )

    print("Firma limpia generada:", ruta_salida)
    return ruta_salida


LOGO_EMPRESA_LIMPIO = limpiar_fondo_imagen(
    LOGO_EMPRESA,
    "LOGO_EMPRESA_limpio.png",
)

FIRMA_LIMPIA = FIRMA


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
        if LOGO_EMPRESA_LIMPIO.exists():
            self.pdf.drawImage(
                ImageReader(str(LOGO_EMPRESA_LIMPIO)),
                35,
                self.height - 75,
                width=155,
                height=55,
                preserveAspectRatio=True,
                mask="auto",
            )

        if LOGO_CERTIFICACIONES.exists():
            self.pdf.drawImage(
                ImageReader(str(LOGO_CERTIFICACIONES)),
                190,
                self.height - 73,
                width=85,
                height=45,
                preserveAspectRatio=True,
                mask="auto",
            )

        if LOGO_ISSA.exists():
            self.pdf.drawImage(
                ImageReader(str(LOGO_ISSA)),
                275,
                self.height - 70,
                width=65,
                height=35,
                preserveAspectRatio=True,
                mask="auto",
            )

        if LOGO_MANTENER.exists():
            self.pdf.drawImage(
                ImageReader(str(LOGO_MANTENER)),
                self.width - 175,
                self.height - 72,
                width=125,
                height=45,
                preserveAspectRatio=True,
                mask="auto",
            )

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
        if not FIRMA_LIMPIA.exists():
            print("No se encontró la firma procesada:", FIRMA_LIMPIA)
            return

        self.pdf.drawImage(
            ImageReader(str(FIRMA_LIMPIA)),
            65,
            175,
            width=145,
            height=65,
            preserveAspectRatio=True,
            mask="auto",
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
            size=9,
        )

        self.pdf.setFont("Helvetica", 9)
        self.pdf.drawString(x, self.height - 420, "Atentamente,")

        self.firma()

        self.pdf.line(65, 165, 240, 165)

        self.pdf.setFont("Helvetica-Bold", 9)
        self.pdf.drawString(65, 148, "YINA CUMBE BUESAQUILLO")
        self.pdf.drawString(65, 135, "Coordinadora de Nómina y Contratación")

        self.pdf.setFont("Helvetica", 8)
        self.pdf.drawString(65, 105, "Copia: Hoja de vida")

        self.pdf.setFont("Helvetica", 5)
        self.pdf.drawString(65, 96, "NMS")

    def pie(self):
        self.pdf.setFont("Helvetica", 5.4)
        self.pdf.drawCentredString(
            self.width / 2,
            58,
            "TÉCNICOS EN LIMPIEZA DE: EMPRESAS, BANCOS, COLEGIOS, UNIVERSIDADES, CENTROS COMERCIALES, CENTROS DE RECREACIÓN",
        )
        self.pdf.drawCentredString(
            self.width / 2,
            50,
            "EDIFICIOS OFICINAS Y VIVIENDAS, HOSPITALES, SUPERMERCADOS, LAVADO Y PINTURA DE FACHADAS, LAVADO DE VIDRIOS, TAPETES Y CORTINAS",
        )

        self.pdf.line(55, 44, self.width - 55, 44)

        self.pdf.setFont("Helvetica", 6)
        self.pdf.drawCentredString(
            self.width / 2,
            32,
            "Calle 4 Bis No. 53C-50 • Bogotá D.C. • PBX: 4204893",
        )

        self.pdf.drawCentredString(
            self.width / 2,
            21,
            "documentos@aseoslaperfeccion.com - comercial@aseoslaperfeccion.com",
        )

        self.pdf.drawCentredString(
            self.width / 2,
            11,
            "www.aseoslaperfeccion.com",
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