from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from infrastructure.db.deps import get_db
from domain.models.proceso_disciplinario import ProcesoDisciplinario
from domain.models.citacion_proceso_disciplinario import CitacionProcesoDisciplinario
from domain.models.descargo_proceso_disciplinario import DescargoProcesoDisciplinario
from domain.models.cierre_proceso_disciplinario import CierreProcesoDisciplinario
from domain.models.documento_proceso_disciplinario import DocumentoProcesoDisciplinario
from domain.schemas.proceso_disciplinario_schema import (
    ProcesoDisciplinarioCreate,
    ProcesoDisciplinarioUpdate,
    ProcesoDisciplinarioResponse,
)

router = APIRouter(
    prefix="/api/procesos-disciplinarios",
    tags=["Procesos Disciplinarios"],
)


@router.post("/", response_model=ProcesoDisciplinarioResponse)
def crear_proceso_disciplinario(
    data: ProcesoDisciplinarioCreate,
    db: Session = Depends(get_db),
):
    nuevo = ProcesoDisciplinario(
        IdRegistroPersonal=data.IdRegistroPersonal,
        EstadoProceso=data.EstadoProceso or "INICIADO",
        OrigenProceso=data.OrigenProceso or "RRLL",
        UsuarioActualizacion=data.UsuarioActualizacion,
    )

    db.add(nuevo)
    db.commit()
    db.refresh(nuevo)

    return nuevo


@router.get("/trabajador/{id_registro_personal}")
def listar_procesos_por_trabajador(
    id_registro_personal: int,
    db: Session = Depends(get_db),
):
    procesos = (
        db.query(ProcesoDisciplinario)
        .filter(ProcesoDisciplinario.IdRegistroPersonal == id_registro_personal)
        .order_by(ProcesoDisciplinario.FechaCreacion.desc())
        .all()
    )

    return procesos


@router.get("/trabajador/{id_registro_personal}/historial")
def obtener_historial_disciplinario_trabajador(
    id_registro_personal: int,
    db: Session = Depends(get_db),
):
    procesos = (
        db.query(ProcesoDisciplinario)
        .filter(ProcesoDisciplinario.IdRegistroPersonal == id_registro_personal)
        .order_by(ProcesoDisciplinario.FechaCreacion.desc())
        .all()
    )

    historial = []

    for proceso in procesos:
        citacion = (
            db.query(CitacionProcesoDisciplinario)
            .filter(
                CitacionProcesoDisciplinario.IdProcesoDisciplinario
                == proceso.IdProcesoDisciplinario
            )
            .first()
        )

        descargo = (
            db.query(DescargoProcesoDisciplinario)
            .filter(
                DescargoProcesoDisciplinario.IdProcesoDisciplinario
                == proceso.IdProcesoDisciplinario
            )
            .first()
        )

        cierre = (
            db.query(CierreProcesoDisciplinario)
            .filter(
                CierreProcesoDisciplinario.IdProcesoDisciplinario
                == proceso.IdProcesoDisciplinario
            )
            .first()
        )

        historial.append(
            {
                "IdProcesoDisciplinario": proceso.IdProcesoDisciplinario,
                "IdRegistroPersonal": proceso.IdRegistroPersonal,
                "FechaCreacion": proceso.FechaCreacion,
                "EstadoProceso": proceso.EstadoProceso,
                "OrigenProceso": proceso.OrigenProceso,
                "TieneCitacion": citacion is not None,
                "TieneDescargo": descargo is not None,
                "TieneCierre": cierre is not None,
                "FechaCitacion": citacion.FechaCitacion if citacion else None,
                "MotivoCitacion": citacion.MotivoCitacion if citacion else None,
                "FechaDescargo": descargo.FechaDescargo if descargo else None,
                "MedidaDisciplinaria": cierre.MedidaDisciplinaria if cierre else None,
                "TipoCierre": cierre.TipoCierre if cierre else None,
                "FechaCierre": cierre.FechaCierre if cierre else None,
            }
        )

    return historial


@router.get("/{id_proceso}/expediente")
def obtener_expediente_disciplinario(
    id_proceso: int,
    db: Session = Depends(get_db),
):
    proceso = (
        db.query(ProcesoDisciplinario)
        .filter(ProcesoDisciplinario.IdProcesoDisciplinario == id_proceso)
        .first()
    )

    if not proceso:
        raise HTTPException(
            status_code=404,
            detail="Proceso disciplinario no encontrado",
        )

    citacion = (
        db.query(CitacionProcesoDisciplinario)
        .filter(CitacionProcesoDisciplinario.IdProcesoDisciplinario == id_proceso)
        .first()
    )

    descargo = (
        db.query(DescargoProcesoDisciplinario)
        .filter(DescargoProcesoDisciplinario.IdProcesoDisciplinario == id_proceso)
        .first()
    )

    cierre = (
        db.query(CierreProcesoDisciplinario)
        .filter(CierreProcesoDisciplinario.IdProcesoDisciplinario == id_proceso)
        .first()
    )

    documentos = (
        db.query(DocumentoProcesoDisciplinario)
        .filter(DocumentoProcesoDisciplinario.IdProcesoDisciplinario == id_proceso)
        .order_by(DocumentoProcesoDisciplinario.FechaCreacion.desc())
        .all()
    )

    return {
        "Proceso": proceso,
        "Citacion": citacion,
        "Descargo": descargo,
        "Cierre": cierre,
        "Documentos": documentos,
    }


@router.get("/{id_proceso}", response_model=ProcesoDisciplinarioResponse)
def obtener_proceso_disciplinario(
    id_proceso: int,
    db: Session = Depends(get_db),
):
    proceso = (
        db.query(ProcesoDisciplinario)
        .filter(ProcesoDisciplinario.IdProcesoDisciplinario == id_proceso)
        .first()
    )

    if not proceso:
        raise HTTPException(status_code=404, detail="Proceso disciplinario no encontrado")

    return proceso


@router.put("/{id_proceso}", response_model=ProcesoDisciplinarioResponse)
def actualizar_proceso_disciplinario(
    id_proceso: int,
    data: ProcesoDisciplinarioUpdate,
    db: Session = Depends(get_db),
):
    proceso = (
        db.query(ProcesoDisciplinario)
        .filter(ProcesoDisciplinario.IdProcesoDisciplinario == id_proceso)
        .first()
    )

    if not proceso:
        raise HTTPException(status_code=404, detail="Proceso disciplinario no encontrado")

    if data.EstadoProceso is not None:
        proceso.EstadoProceso = data.EstadoProceso

    if data.OrigenProceso is not None:
        proceso.OrigenProceso = data.OrigenProceso

    if data.UsuarioActualizacion is not None:
        proceso.UsuarioActualizacion = data.UsuarioActualizacion

    proceso.FechaActualizacion = datetime.now()

    db.commit()
    db.refresh(proceso)

    return proceso