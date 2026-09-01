from sqlalchemy import (
    Boolean,
    Column,
    Date,
    ForeignKey,
    Integer,
    String,
    Text,
    Time,
)
from sqlalchemy.sql import func
from sqlalchemy.types import DateTime

from infrastructure.db.base import Base


class CitacionProcesoDisciplinario(Base):
    __tablename__ = "CitacionProcesoDisciplinario"

    IdCitacionProcesoDisciplinario = Column(
        Integer,
        primary_key=True,
        index=True,
    )

    IdProcesoDisciplinario = Column(
        Integer,
        ForeignKey(
            "ProcesoDisciplinario.IdProcesoDisciplinario"
        ),
        nullable=False,
    )

    FechaCitacion = Column(
        Date,
        nullable=True,
    )

    HoraCitacion = Column(
        Time,
        nullable=True,
    )

    LugarCitacion = Column(
        String(300),
        nullable=True,
    )

    MotivoCitacion = Column(
        Text,
        nullable=True,
    )

    ResponsableCitacion = Column(
        String(200),
        nullable=True,
    )

    FechaCreacion = Column(
        DateTime(timezone=True),
        server_default=func.now(),
    )

    FechaActualizacion = Column(
        DateTime(timezone=True),
        nullable=True,
    )

    # =========================================================
    # INFORMACIÓN MAPEADA DESDE OPERACIONES
    # =========================================================

    TipoGestionDisciplinaria = Column(
        String(50),
        nullable=True,
    )

    Modalidad = Column(
        String(20),
        nullable=True,
    )

    RelatoHechos = Column(
        Text,
        nullable=True,
    )

    ObservacionOperaciones = Column(
        Text,
        nullable=True,
    )

    FechaUltimoDiaLaborado = Column(
        Date,
        nullable=True,
    )

    FechaInicioAusencia = Column(
        Date,
        nullable=True,
    )

    FechaFinAusencia = Column(
        Date,
        nullable=True,
    )

    DesempenoContinua = Column(
        String(20),
        nullable=True,
    )

    JustificacionDesempeno = Column(
        Text,
        nullable=True,
    )

    SupervisorReporta = Column(
        String(200),
        nullable=True,
    )

    CorreoSupervisorReporta = Column(
        String(200),
        nullable=True,
    )

    CargoSupervisorReporta = Column(
        String(150),
        nullable=True,
    )

    SedeSupervisorReporta = Column(
        String(250),
        nullable=True,
    )

    EnunciacionPruebas = Column(
        Text,
        nullable=True,
    )

    TelefonoTrabajador = Column(
        String(30),
        nullable=True,
    )

    ManifestacionSupervisor = Column(
        Text,
        nullable=True,
    )

    Cliente = Column(
        String(300),
        nullable=True,
    )

    Sede = Column(
        String(250),
        nullable=True,
    )

    UsuarioCreacion = Column(
        String(100),
        nullable=True,
    )

    UsuarioActualizacion = Column(
        String(100),
        nullable=True,
    )

    # =========================================================
    # INFORMACIÓN DE LA CITACIÓN EXTRAORDINARIA
    # =========================================================

    EsExtraordinaria = Column(
        Boolean,
        nullable=False,
        default=False,
    )

    MotivoExtraordinario = Column(
        String(200),
        nullable=True,
    )

    JustificacionExtraordinaria = Column(
        Text,
        nullable=True,
    )