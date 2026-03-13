from app.infrastructure.db.deps import get_db
from app.services.rrll_documentos_service import generar_primer_llamado

db = next(get_db())

try:
    ruta = generar_primer_llamado(db, 7)
    print("Documento generado en:", ruta)
finally:
    db.close()