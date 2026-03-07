from sqlalchemy import Column, String, Text, BigInteger, DateTime
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func

from infrastructure.db.base import Base  # ajusta si tu Base está en otro lado

class DocumentoSeguridad(Base):
    __tablename__ = "documentos_seguridad"

    id = Column(UUID(as_uuid=True), primary_key=True, server_default="gen_random_uuid()")
    aspirante_id = Column(UUID(as_uuid=True), nullable=False)

    tipo_documento = Column(String(80), nullable=False)
    nombre_original = Column(Text, nullable=True)
    nombre_archivo = Column(Text, nullable=False)

    mime_type = Column(String(120), nullable=True)
    tamano_bytes = Column(BigInteger, nullable=True)

    ruta_archivo = Column(Text, nullable=False)
    creado_en = Column(DateTime, nullable=False, server_default=func.now())
