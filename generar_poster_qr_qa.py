from PIL import Image, ImageDraw, ImageFont

# =========================
# CONFIG
# =========================
ANCHO = 1080
ALTO = 1920
COLOR_FONDO = "white"
COLOR_MORADO = (77, 45, 127)
COLOR_VERDE = (74, 153, 70)
COLOR_NEGRO = (30, 30, 30)

RUTA_QR = "qr_qa_bueno.png"
SALIDA = "poster_qr_entrevista_retiro_qa.png"

# =========================
# FUNCIONES
# =========================
def cargar_fuente(tamano, negrita=False):
    posibles = []
    if negrita:
        posibles = [
            "C:/Windows/Fonts/arialbd.ttf",
            "C:/Windows/Fonts/calibrib.ttf",
            "C:/Windows/Fonts/segoeuib.ttf",
        ]
    else:
        posibles = [
            "C:/Windows/Fonts/arial.ttf",
            "C:/Windows/Fonts/calibri.ttf",
            "C:/Windows/Fonts/segoeui.ttf",
        ]

    for ruta in posibles:
        try:
            return ImageFont.truetype(ruta, tamano)
        except:
            pass

    return ImageFont.load_default()


def texto_centrado(draw, texto, fuente, color, y, ancho_total):
    bbox = draw.textbbox((0, 0), texto, font=fuente)
    w = bbox[2] - bbox[0]
    x = (ancho_total - w) // 2
    draw.text((x, y), texto, font=fuente, fill=color)


# =========================
# LIENZO
# =========================
img = Image.new("RGB", (ANCHO, ALTO), COLOR_FONDO)
draw = ImageDraw.Draw(img)

# =========================
# FUENTES
# =========================
fuente_logo = cargar_fuente(42, negrita=True)
fuente_titulo = cargar_fuente(78, negrita=True)
fuente_subtitulo = cargar_fuente(42, negrita=True)
fuente_frase = cargar_fuente(28, negrita=True)
fuente_texto = cargar_fuente(24, negrita=False)
fuente_texto_bold = cargar_fuente(24, negrita=True)
fuente_exito = cargar_fuente(52, negrita=True)

# =========================
# CABECERA
# =========================
texto_centrado(draw, "LA PERFECCIÓN", fuente_titulo, COLOR_MORADO, 120, ANCHO)
texto_centrado(draw, "RECURSOS HUMANOS", fuente_subtitulo, COLOR_VERDE, 230, ANCHO)

# Línea decorativa
draw.line((260, 320, 820, 320), fill=COLOR_MORADO, width=3)
draw.ellipse((525, 308, 555, 338), fill=COLOR_VERDE)

# =========================
# MENSAJES
# =========================
texto_centrado(draw, "¡Gracias por ser parte de nuestra historia!", fuente_frase, COLOR_MORADO, 370, ANCHO)

texto_centrado(draw, "Tu compromiso y dedicación han sido valiosos", fuente_texto, COLOR_NEGRO, 445, ANCHO)
texto_centrado(draw, "para La Perfección.", fuente_texto_bold, COLOR_VERDE, 485, ANCHO)

# línea
draw.line((180, 585, 900, 585), fill=COLOR_MORADO, width=2)

# texto previo al QR
texto_centrado(draw, "Escanea este código QR para realizar", fuente_texto_bold, COLOR_MORADO, 640, ANCHO)
texto_centrado(draw, "tu entrevista de retiro.", fuente_texto, COLOR_NEGRO, 680, ANCHO)

# =========================
# QR
# =========================
qr = Image.open(RUTA_QR).convert("RGB")
qr = qr.resize((520, 520))

qr_x = (ANCHO - 520) // 2
qr_y = 760

# marco
draw.rounded_rectangle(
    (qr_x - 20, qr_y - 20, qr_x + 540, qr_y + 540),
    radius=30,
    outline=COLOR_MORADO,
    width=4
)

img.paste(qr, (qr_x, qr_y))

# =========================
# TEXTO FINAL
# =========================
texto_centrado(draw, "Tu opinión es importante para nosotros.", fuente_texto, COLOR_NEGRO, 1360, ANCHO)
texto_centrado(draw, "Gracias por tu tiempo y por haber", fuente_texto, COLOR_NEGRO, 1400, ANCHO)
texto_centrado(draw, "trabajado con La Perfección.", fuente_texto_bold, COLOR_VERDE, 1440, ANCHO)

texto_centrado(draw, "¡Éxitos siempre!", fuente_exito, COLOR_MORADO, 1560, ANCHO)

# =========================
# BASE DECORATIVA
# =========================
draw.pieslice((-200, 1660, 1280, 2150), start=0, end=180, fill=COLOR_VERDE)
draw.pieslice((-200, 1690, 1280, 2180), start=0, end=180, fill=COLOR_MORADO)

# =========================
# GUARDAR
# =========================
img.save(SALIDA)
print(f"Póster generado correctamente: {SALIDA}")