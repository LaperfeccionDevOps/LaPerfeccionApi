from pathlib import Path

# Ruta exacta que aparece en tu BD
ruta_relativa = r"storage/rrll/retiros/7/retiro_7_tipo_1_20260311_162019.pdf"

ruta = Path(ruta_relativa)

# Crear carpeta si no existe
ruta.parent.mkdir(parents=True, exist_ok=True)

# PDF mínimo válido
contenido_pdf = b"""%PDF-1.4
1 0 obj
<< /Type /Catalog /Pages 2 0 R >>
endobj
2 0 obj
<< /Type /Pages /Kids [3 0 R] /Count 1 >>
endobj
3 0 obj
<< /Type /Page /Parent 2 0 R /MediaBox [0 0 300 144] /Contents 4 0 R >>
endobj
4 0 obj
<< /Length 55 >>
stream
BT
/F1 12 Tf
72 100 Td
(Paz y Salvo - Prueba Operaciones) Tj
ET
endstream
endobj
xref
0 5
0000000000 65535 f
0000000010 00000 n
0000000060 00000 n
0000000117 00000 n
0000000204 00000 n
trailer
<< /Root 1 0 R /Size 5 >>
startxref
309
%%EOF
"""

with open(ruta, "wb") as f:
    f.write(contenido_pdf)

print("Archivo creado en:")
print(ruta.resolve())