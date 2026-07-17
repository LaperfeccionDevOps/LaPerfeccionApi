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
FIRMA = ASSETS / "FIRMA_EMPLEADOR.png"

OUTPUT = BASE_DIR.parent / "storage" / "nomina" / "comunicaciones"
OUTPUT.mkdir(parents=True, exist_ok=True)

ASSETS_LIMPIOS = OUTPUT / "_assets_limpios"
ASSETS_LIMPIOS.mkdir(parents=True, exist_ok=True)


def limpiar_fondo_imagen(ruta_original: Path, nombre_salida: str) -> Path:
    """
    Convierte fondos claros/blancos/azulados de los logos en transparencia.
    No modifica el archivo original.
    """
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
    Limpia la fotografía de la firma sin dejar el rectángulo gris del papel.

    - Corrige sombras e iluminación irregular.
    - Conserva únicamente los trazos oscuros.
    - Convierte la firma a negro.
    - Deja el fondo completamente transparente.
    - Recorta espacios sobrantes.
    """
    ruta_salida = ASSETS_LIMPIOS / nombre_salida

    if not ruta_original.exists():
        print("No existe la firma original:", ruta_original)
        return ruta_original

    with Image.open(ruta_original) as imagen_original:
        imagen = imagen_original.convert("RGB")

    gris = ImageOps.grayscale(imagen)

    # Estimar el fondo para eliminar textura, sombras y cambios de iluminación.
    fondo_estimado = gris.filter(
        ImageFilter.GaussianBlur(radius=28)
    )

    pixeles_gris = list(gris.getdata())
    pixeles_fondo = list(fondo_estimado.getdata())
    pixeles_salida = []

    for intensidad, fondo in zip(pixeles_gris, pixeles_fondo):
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

    # Quitar puntos sueltos sin engrosar la firma.
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

FIRMA_LIMPIA = preparar_firma(
    FIRMA,
    "FIRMA_EMPLEADOR_limpia_final_v2.png",
)


class CertificadoLaboralPDF:
    def __init__(self, datos):
        self.datos = datos
        self.width, self.height = letter
        self.fecha = datetime.now()

        carpeta = OUTPUT / str(self.datos["IdRetiroLaboral"])
        carpeta.mkdir(parents=True, exist_ok=True)

        self.ruta_pdf = (
            carpeta
            / f"certificado_laboral_{self.datos['IdRetiroLaboral']}.pdf"
        )
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
                45,
                self.height - 95,
                width=160,
                height=60,
                preserveAspectRatio=True,
                mask="auto",
            )

        if LOGO_CERTIFICACIONES.exists():
            self.pdf.drawImage(
                ImageReader(str(LOGO_CERTIFICACIONES)),
                215,
                self.height - 96,
                width=95,
                height=55,
                preserveAspectRatio=True,
                mask="auto",
            )

        if LOGO_ISSA.exists():
            self.pdf.drawImage(
                ImageReader(str(LOGO_ISSA)),
                315,
                self.height - 90,
                width=75,
                height=40,
                preserveAspectRatio=True,
                mask="auto",
            )

        if LOGO_MANTENER.exists():
            self.pdf.drawImage(
                ImageReader(str(LOGO_MANTENER)),
                self.width - 180,
                self.height - 92,
                width=130,
                height=48,
                preserveAspectRatio=True,
                mask="auto",
            )

        self.pdf.setFont("Helvetica-Bold", 12)
        self.pdf.drawCentredString(
            self.width / 2,
            self.height - 155,
            "EL DEPARTAMENTO DE TALENTO HUMANO",
        )

        self.pdf.setFont("Helvetica-Bold", 12)
        self.pdf.drawCentredString(
            self.width / 2,
            self.height - 190,
            "CERTIFICA",
        )

    def firma(self):
        if not FIRMA_LIMPIA.exists():
            print("No se encontró la firma procesada:", FIRMA_LIMPIA)
            return

        self.pdf.drawImage(
            ImageReader(str(FIRMA_LIMPIA)),
            120,
            178,
            width=145,
            height=65,
            preserveAspectRatio=True,
            mask="auto",
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
        salario = (
            f"$ {float(salario_raw):,.0f}".replace(",", ".")
            if salario_raw
            else "SEGÚN NÓMINA"
        )

        x = 120
        ancho = 360

        texto_principal = (
            f"Que el señor {nombre}, identificado con el número de {tipo} No. {documento} "
            f"de {ciudad}, laboró en nuestra empresa con contrato a término Labor Contratada "
            f"desde el {fecha_ingreso} hasta el {fecha_retiro}; desempeñando el cargo de {cargo}"
        )

        self.parrafo_justificado(
            texto_principal,
            x=x,
            y=self.height - 285,
            ancho=ancho,
            alto=80,
            size=8.5,
        )

        self.pdf.setFont("Helvetica", 8.5)
        self.pdf.drawString(
            170,
            self.height - 325,
            "Salario Básico mensual",
        )

        self.pdf.setFont("Helvetica-Bold", 8.5)
        self.pdf.drawString(
            355,
            self.height - 325,
            salario,
        )

        texto_info = (
            "Para mayor información de ser necesario, se pueden comunicar al PBX "
            "4204893 EXT 1046, ó al numero celular 3176456953, ó al correo "
            "electronico contratacion@aseoslaperfeccion.com ."
        )

        self.parrafo_justificado(
            texto_info,
            x=x,
            y=self.height - 425,
            ancho=ancho,
            alto=70,
            size=8.5,
        )

        texto_fecha = (
            f"La presente certificación se expide a solicitud del interesado, dado el "
            f"{self.fecha_texto()} en la ciudad de BOGOTA"
        )

        self.parrafo_justificado(
            texto_fecha,
            x=x,
            y=self.height - 510,
            ancho=ancho,
            alto=45,
            size=8.5,
        )

        self.pdf.setFont("Helvetica", 8.5)
        self.pdf.drawString(
            120,
            self.height - 535,
            "Cordialmente,",
        )

        self.firma()

        self.pdf.line(120, 170, 295, 170)

        self.pdf.setFont("Helvetica-Bold", 8.5)
        self.pdf.drawString(
            120,
            155,
            "Yina Cumbe",
        )

        self.pdf.setFont("Helvetica", 8.5)
        self.pdf.drawString(
            120,
            142,
            "Talento Humano",
        )

    def pie(self):
        self.pdf.setFont("Helvetica", 5.6)
        self.pdf.drawCentredString(
            self.width / 2,
            72,
            "TÉCNICOS EN LIMPIEZA DE: EMPRESAS, BANCOS, COLEGIOS, UNIVERSIDADES, CENTROS COMERCIALES, CENTROS DE RECREACIÓN",
        )
        self.pdf.drawCentredString(
            self.width / 2,
            63,
            "EDIFICIOS OFICINAS Y VIVIENDAS, HOSPITALES, SUPERMERCADOS, LAVADO Y PINTURA DE FACHADAS, LAVADO DE VIDRIOS, TAPETES Y CORTINAS",
        )

        self.pdf.line(40, 55, self.width - 40, 55)

        self.pdf.setFont("Helvetica", 6.5)
        self.pdf.drawCentredString(
            self.width / 2,
            40,
            "Calle 4 Bis No. 53C-50 • PBX: 420 48 93 - 261 32 74 - 261 46 25 • Bogotá, D.C. - Colombia",
        )
        self.pdf.drawCentredString(
            self.width / 2,
            27,
            "www.aseoslaperfeccion.com        comercial@aseoslaperfeccion.com",
        )

    def generar(self):
        self.encabezado()
        self.cuerpo()
        self.pie()
        self.pdf.save()
        return str(self.ruta_pdf)


def generar_certificado_laboral(datos):
    pdf = CertificadoLaboralPDF(datos)
    return pdf.generar()