from datetime import date, datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy import text
from sqlalchemy.orm import Session

from infrastructure.db.deps import get_db
from domain.models.cita import Cita
from domain.schemas.cita import CitaCreate, CitaOut

router = APIRouter()


# --- DEBUG (lo dejamos porque te sirve para probar) ---
@router.post("/citas/debug")
def crear_cita_debug(payload: dict):
    print("\n>>> ENTRO A /api/citas/debug")
    print("Payload recibido:", payload)
    return {
        "mensaje": "llegó bien al endpoint /api/citas/debug",
        "payload": payload,
    }


# --- ENDPOINT REAL ---
@router.post(
    "/citas",
    response_model=CitaOut,
    status_code=status.HTTP_201_CREATED,
)
def crear_cita(
    payload: CitaCreate,
    db: Session = Depends(get_db),
):
    """
    Crea una cita en AgendarEntrevista.
    """

    print("\n>>> ENTRO A /api/citas")
    print("Payload:", payload)

    # 1) Validar que IdRegistroPersonal exista en la tabla RegistroPersonal
    fila = db.execute(
        text(
            'SELECT 1 FROM "RegistroPersonal" '
            'WHERE "IdRegistroPersonal" = :id'
        ),
        {"id": payload.IdRegistroPersonal},
    ).first()

    if fila is None:
        # No existe el aspirante → devolvemos 400, no dejamos que explote la FK
        raise HTTPException(
            status_code=400,
            detail=f"El IdRegistroPersonal {payload.IdRegistroPersonal} no existe en RegistroPersonal",
        )

    # 2) Combinar fecha + hora en datetimes para la tabla (timestamptz/timestamp)
    fecha_programada_dt = datetime.combine(
        payload.FechaProgramada,
        datetime.min.time(),  # 00:00
    )

    hora_programada_dt = datetime.combine(
        payload.FechaProgramada,
        payload.HoraProgramada,
    )

    # 3) Crear la cita
    cita = Cita(
        IdRegistroPersonal=payload.IdRegistroPersonal,
        FechaProgramada=fecha_programada_dt,
        HoraProgramada=hora_programada_dt,
        Observaciones=payload.Observaciones,
    )

    db.add(cita)
    db.commit()
    db.refresh(cita)

    print(">>> Cita creada con IdAgendarEntrevista:", cita.IdAgendarEntrevista)

    return cita


@router.get("/citas/{id_agendar}", response_model=CitaOut)
def obtener_cita(
    id_agendar: int,
    db: Session = Depends(get_db),
):
    cita = (
        db.query(Cita)
        .filter(Cita.IdAgendarEntrevista == id_agendar)
        .first()
    )

    if not cita:
        raise HTTPException(status_code=404, detail="Cita no encontrada")

    return cita


@router.get("/citas", response_model=list[CitaOut])
def listar_citas(
    db: Session = Depends(get_db),
    id_aspirante: Optional[int] = Query(
        None, description="IdRegistroPersonal (aspirante)"
    ),
    fecha_desde: Optional[date] = Query(
        None, description="Filtrar desde esta fecha (FechaProgramada >=)"
    ),
    fecha_hasta: Optional[date] = Query(
        None, description="Filtrar hasta esta fecha (FechaProgramada <=)"
    ),
):
    query = db.query(Cita)

    if id_aspirante is not None:
        query = query.filter(Cita.IdRegistroPersonal == id_aspirante)

    if fecha_desde is not None:
        query = query.filter(Cita.FechaProgramada >= fecha_desde)

    if fecha_hasta is not None:
        query = query.filter(Cita.FechaProgramada <= fecha_hasta)

    return query.order_by(
        Cita.FechaProgramada.asc(),
        Cita.HoraProgramada.asc(),
    ).all()