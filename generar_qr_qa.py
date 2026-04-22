import qrcode

url = "https://qa.laperfeccion.app/entrevista-retiro-publica"

qr = qrcode.QRCode(
    version=1,
    error_correction=qrcode.constants.ERROR_CORRECT_H,
    box_size=20,  # calidad alta
    border=4,
)

qr.add_data(url)
qr.make(fit=True)

img = qr.make_image(fill_color="black", back_color="white")
img.save("qr_qa_bueno.png")

print("QR generado correctamente")