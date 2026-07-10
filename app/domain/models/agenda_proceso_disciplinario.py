from sqlalchemy import Column, Integer, String, Date, Time, Text, Boolean, DateTime, ForeignKey
from sqlalchemy.sql import func
from infrastructure.db.base import Base


class AgendaProcesoDisciplinario(Base):
    __tablename__ = "AgendaProcesoDisciplinario"

    IdAgendaProcesoDisciplinario = Column(Integer, primary_key=True, index=True)

    IdProcesoDisciplinario = Column(
        Integer,
        ForeignKey("ProcesoDisciplinario.IdProcesoDisciplinario"),
        nullable=False
    )

    IdRegistroPersonal = Column(
        Integer,
        ForeignKey("RegistroPersonal.IdRegistroPersonal"),
        nullable=False
    )

    IdTipoEventoDisciplinario = Column(
        Integer,
        ForeignKey("TipoEventoDisciplinario.IdTipoEventoDisciplinario"),
        nullable=False
    )

    FechaEvento = Column(Date, nullable=False)
    HoraInicio = Column(Time, nullable=False)
    HoraFin = Column(Time, nullable=False)

    Modalidad = Column(String(20), nullable=False)
    Observacion = Column(Text, nullable=True)

    EstadoAgenda = Column(String(30), nullable=False, default="PROGRAMADO")
    ColorAgenda = Column(String(20), nullable=True)

    UsuarioAgenda = Column(String(100), nullable=True)

    FechaCreacion = Column(DateTime(timezone=True), server_default=func.now())
    FechaActualizacion = Column(DateTime(timezone=True), nullable=True)
    UsuarioActualizacion = Column(String(100), nullable=True)

    Activo = Column(Boolean, nullable=False, default=True)