from PIL import Image, ImageDraw, ImageFont
import os

# ----------------------------
# RUTAS
# ----------------------------
QR_PATH = "qr_entrevista_retiro_qa.png"
LOGO_PATH = "app/utilidades/img/logo/LOGO_EMPRESA.png"
OUTPUT_PATH = "poster_qr_entrevista_retiro_qa.png"

# ----------------------------
# FUNCION PARA CARGAR FUENTES
# ----------------------------
def cargar_fuente(tamano, negrita=False):
    posibles = []

    if negrita:
        posibles = [
            r"C:\Windows\Fonts\arialbd.ttf",
            r"C:\Windows\Fonts\calibrib.ttf",
            r"C:\Windows\Fonts\segoeuib.ttf",
        ]
    else:
        posibles = [
            r"C:\Windows\Fonts\arial.ttf",
            r"C:\Windows\Fonts\calibri.ttf",
            r"C:\Windows\Fonts\segoeui.ttf",
        ]

    for ruta in posibles:
        if os.path.exists(ruta):
            return ImageFont.truetype(ruta, tamano)

    return ImageFont.load_default()

# ----------------------------
# VALIDACIONES
# ----------------------------
print("QR_PATH:", QR_PATH, os.path.exists(QR_PATH))
print("LOGO_PATH:", LOGO_PATH, os.path.exists(LOGO_PATH))

if not os.path.exists(QR_PATH):
    raise FileNotFoundError(f"No existe el archivo QR: {QR_PATH}")

# ----------------------------
# COLORES
# ----------------------------
BLANCO = (250, 250, 250)
AZUL = (16, 35, 72)
DORADO = (190, 148, 62)

# ----------------------------
# LIENZO
# ----------------------------
ancho, alto = 1200, 1800
img = Image.new("RGB", (ancho, alto), BLANCO)
draw = ImageDraw.Draw(img)

# ----------------------------
# FUENTES
# ----------------------------
fuente_titulo = cargar_fuente(72, negrita=True)
fuente_subtitulo = cargar_fuente(42, negrita=True)
fuente_texto = cargar_fuente(36, negrita=False)
fuente_texto_bold = cargar_fuente(38, negrita=True)
fuente_footer = cargar_fuente(52, negrita=True)

# ----------------------------
# POSICIÓN INICIAL
# ----------------------------
y_actual = 70

# ----------------------------
# LOGO
# ----------------------------
if os.path.exists(LOGO_PATH):
    logo = Image.open(LOGO_PATH).convert("RGBA")
    logo.thumbnail((300, 300))

    logo_x = (ancho - logo.width) // 2
    img.paste(logo, (logo_x, y_actual), logo)

    y_actual += logo.height + 30
else:
    print(f"No se encontró el logo en: {LOGO_PATH}")

# ----------------------------
# TÍTULOS
# ----------------------------
titulo = "LA PERFECCIÓN"
subtitulo = "RECURSOS HUMANOS"

bbox = draw.textbbox((0, 0), titulo, font=fuente_titulo)
tw = bbox[2] - bbox[0]
draw.text(((ancho - tw) // 2, y_actual), titulo, fill=AZUL, font=fuente_titulo)
y_actual += 95

bbox = draw.textbbox((0, 0), subtitulo, font=fuente_subtitulo)
sw = bbox[2] - bbox[0]
draw.text(((ancho - sw) // 2, y_actual), subtitulo, fill=DORADO, font=fuente_subtitulo)
y_actual += 120

# ----------------------------
# MENSAJE SUPERIOR
# ----------------------------
lineas = [
    "¡Gracias por ser parte de nuestra historia!",
    "",
    "Tu compromiso y dedicación han sido valiosos",
    "para La Perfección.",
    "",
    "Escanea este código QR para realizar",
    "tu entrevista de retiro.",
]

for linea in lineas:
    if "Gracias" in linea:
        font = fuente_subtitulo
        color = DORADO
    else:
        font = fuente_texto
        color = AZUL

    bbox = draw.textbbox((0, 0), linea, font=font)
    lw = bbox[2] - bbox[0]
    draw.text(((ancho - lw) // 2, y_actual), linea, fill=color, font=font)

    if linea == "":
        y_actual += 30
    else:
        y_actual += 58

y_actual += 30

# ----------------------------
# QR
# ----------------------------
qr = Image.open(QR_PATH).convert("RGB")
qr = qr.resize((430, 430))

marco_padding = 26
marco_x = (ancho - (430 + marco_padding * 2)) // 2
marco_y = y_actual

draw.rounded_rectangle(
    [
        marco_x,
        marco_y,
        marco_x + 430 + marco_padding * 2,
        marco_y + 430 + marco_padding * 2,
    ],
    radius=28,
    outline=DORADO,
    width=5,
    fill=(255, 255, 255),
)

qr_x = marco_x + marco_padding
qr_y = marco_y + marco_padding
img.paste(qr, (qr_x, qr_y))

y_actual = marco_y + 430 + marco_padding * 2 + 70

# ----------------------------
# MENSAJE INFERIOR
# ----------------------------
lineas_finales = [
    "Tu opinión es importante para nosotros.",
    "Gracias por tu tiempo y por haber",
    "trabajado con La Perfección.",
    "",
    "¡Éxitos siempre!",
]

for linea in lineas_finales:
    if "Éxitos" in linea:
        font = fuente_footer
        color = DORADO
    else:
        font = fuente_texto_bold
        color = AZUL

    bbox = draw.textbbox((0, 0), linea, font=font)
    lw = bbox[2] - bbox[0]
    draw.text(((ancho - lw) // 2, y_actual), linea, fill=color, font=font)

    if linea == "":
        y_actual += 30
    else:
        y_actual += 58

# ----------------------------
# GUARDAR
# ----------------------------
img.save(OUTPUT_PATH)
print(f"Poster generado correctamente: {OUTPUT_PATH}")