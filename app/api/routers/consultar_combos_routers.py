from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from infrastructure.db.deps import get_db
from domain.schemas.combos_schema import (TipoIdentificacionResponse as 
                                        sch_identificacion, 
                                        TipoCargo as sch_TipoCargo, 
                                        TipoEps as sch_TipoEps, 
                                        TipoEstadoCivil as sch_TipoEstadoCivil, 
                                        TipoFormacionAcademica as sch_TipoFormacionAcademica, 
                                        TipoGenero as sch_TipoGenero, Localidades as sch_Localidades, LugarNacimiento as sch_LugarNacimiento, Cargo as sch_Cargo)
from domain.models.combos_models import (TipoIdentificacion, 
                                        TipoCargo as m_TipoCargo, 
                                        TipoEps as m_TipoEps, 
                                        TipoEstadoCivil as m_TipoEstadoCivil, 
                                        TipoFormacionAcademica as m_TipoFormacionAcademica, 
                                        TipoPrueba as m_tp,
                                        TipoGenero as m_TipoGenero,
                                        TipoReferencia as m_TipoReferencia, Localidades as m_Localidades, Cargo as m_Cargo)
# from infrastructure.db.session import SessionLocal
from datetime import datetime, date, time
from domain.models.aspirante import LugarNacimientoORM as m_LugarNacimiento

router = APIRouter()

@router.get("/tipos-identificacion", response_model=list[sch_identificacion])
def listar_tipos_identificacion(db: Session = Depends(get_db)):
    # db = SessionLocal()
    return db.query(TipoIdentificacion).all()

@router.get("/tipo-cargo", response_model=list[sch_TipoCargo])
def listar_tipos_cargo(db: Session = Depends(get_db)):
    return db.query(m_TipoCargo).all()


@router.get("/tipo-eps", response_model=list[sch_TipoEps])
def listar_tipos_eps(db: Session = Depends(get_db)):
    return db.query(m_TipoEps).all()


@router.get("/tipo-estado-civil", response_model=list[sch_TipoEstadoCivil])
def listar_tipos_estado_civil(db: Session = Depends(get_db)):
    return db.query(m_TipoEstadoCivil).all()

@router.get("/tipo-formacion-academica", response_model=list[sch_TipoFormacionAcademica])
def listar_tipo_formacion_academica(db: Session = Depends(get_db)):
    return db.query(m_TipoFormacionAcademica).all()


@router.get("/tipo-genero", response_model=list[sch_TipoGenero])
def listar_tipo_genero(db: Session = Depends(get_db)):
    return db.query(m_TipoGenero).all()


@router.get("/tipo-prueba", response_model=list[sch_identificacion])
def listar_prueba(db: Session = Depends(get_db)):
    return db.query(m_tp).all()


@router.get("/tipo-referencia", response_model=list[sch_identificacion])
def listar_referencia(db: Session = Depends(get_db)):
    return db.query(m_TipoReferencia).all()

@router.get("/localidades", response_model=list[sch_Localidades])
def listar_localidades(db: Session = Depends(get_db)):
    try:
        localidades = db.query(m_Localidades).all()
        for loc in localidades:
            fc = getattr(loc, 'FechaCreacion', None)
            if type(fc) is time:
                loc.FechaCreacion = datetime.combine(date.today(), fc)
        return localidades
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))


@router.get("/listado-lugar-nacimiento", response_model=list[sch_LugarNacimiento])
def listar_lugar_nacimiento(db: Session = Depends(get_db)):
    try:
        lugar_nacimiento = (db.query(m_LugarNacimiento).order_by(m_LugarNacimiento.Nombre).all()) 
        for loc in lugar_nacimiento:
            fc = getattr(loc, 'FechaCreacion', None)
            if type(fc) is time:
                loc.FechaCreacion = datetime.combine(date.today(), fc)
        return lugar_nacimiento
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))
    

@router.get("/listado-cargo", response_model=list[sch_Cargo])
def listar_cargo(db: Session = Depends(get_db)):
    try:
        cargos = db.query(m_Cargo).all()
        for cargo in cargos:
            fc = getattr(cargo, 'FechaCreacion', None)
            if type(fc) is time:
                cargo.FechaCreacion = datetime.combine(date.today(), fc)
        return cargos
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))