from sqlalchemy import Column, Integer, String, Date, Boolean, Text
from sqlalchemy.dialects.postgresql import TIMESTAMP
from sqlalchemy.sql import func


from sqlalchemy.orm import relationship
from sqlalchemy import ForeignKey
from infrastructure.db.base import Base


class DatosSeleccion(Base):
    __tablename__ = "DatosSeleccion"
    __table_args__ = {"quote": True}

    IdDatosSeleccion = Column("IdDatosSeleccion", Integer, primary_key=True, index=True, quote=True)
    IdRegistroPersonal = Column("IdRegistroPersonal", Integer, ForeignKey("RegistroPersonal.IdRegistroPersonal", name="fk_datosseleccion_registropersonal"), nullable=False, index=True, quote=True)

    FechaProceso = Column("FechaProceso", Date, nullable=False, quote=True)
    TipoCargo = Column("TipoCargo", String(150), nullable=False, quote=True)

    # ✅ CAMBIO AQUÍ (nombre real en BD)
    HaTrabajadoAntesEnLaEmpresa = Column(
        "HaTrabajadoAntesEnLaEmpresa",
        Boolean,
        nullable=False,
        default=False,
        quote=True
    )

    Arl = Column("Arl", String(130), nullable=True, quote=True)
    AntecedentesMedicos = Column("AntecedentesMedicos", Text, nullable=True, quote=True)
    Medicamentos = Column("Medicamentos", Text, nullable=True, quote=True)

    FechaActualizacion = Column(
        "FechaActualizacion",
        TIMESTAMP(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
        quote=True
    )

    UsuarioActualizacion = Column("UsuarioActualizacion", String(120), nullable=False, quote=True)

    # Relación muchos-a-uno con RegistroPersonal
    registro_personal = relationship(
        "RegistroPersonal",
        back_populates="datos_seleccion",
        foreign_keys=[IdRegistroPersonal]
    )