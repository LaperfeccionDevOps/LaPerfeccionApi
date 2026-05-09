import qrcode

url = "https://laperfeccion.app/entrevista-retiro-publica"

qr = qrcode.QRCode(
    version=1,
    error_correction=qrcode.constants.ERROR_CORRECT_H,
    box_size=20,
    border=4,
)

qr.add_data(url)
qr.make(fit=True)

img = qr.make_image(fill_color="black", back_color="white")
img.save("qr_produccion_entrevista_retiro.png")

print("QR de producción generado correctamente")