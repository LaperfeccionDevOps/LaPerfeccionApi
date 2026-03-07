from sqlalchemy.orm import Session
from domain.models.contador_registro_personal import ContadorRegistroPersonal

def contador_registro_personal(db: Session, id_registro_personal: int) -> int:
    registro = db.query(ContadorRegistroPersonal).filter_by(IdRegistroPersonal=id_registro_personal).first()
    print('registro contador', registro)
    if registro:
        registro.Contador += 1
        db.commit()
        db.refresh(registro)
        return registro.Contador
    else:
        nuevo = ContadorRegistroPersonal(IdRegistroPersonal=id_registro_personal, Contador=1)
        db.add(nuevo)
        db.commit()
        db.refresh(nuevo)
        print('nuevo registro contador', nuevo)
        return nuevo.Contador
