import qrcode

url = "https://qa.laperfeccion.app/entrevista-retiro-publica"

img = qrcode.make(url)

img.save("qr_entrevista_retiro_qa.png")

print("QR generado correctamente")