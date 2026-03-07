from sqlalchemy.orm import Session
from app.domain.models.contador_registro_personal import ContadorRegistroPersonal
#from app.domain.models.configuracion import Configuracion

def get_contador_registro_personal(db: Session, id_registro_personal: int) -> int | None:
    registro = db.query(ContadorRegistroPersonal).filter_by(IdRegistroPersonal=id_registro_personal).first()
    return registro.Contador if registro else None

# def get_valor_configuracion(db: Session, nombre: str) -> int | None:
#     config = db.query(Configuracion).filter_by(Nombre=nombre).first()
#     return config.Valor if config else None
