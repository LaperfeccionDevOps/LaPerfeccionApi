# services/datos_seleccion_service.py
from sqlalchemy.orm import Session
from repositories.datos_seleccion_repo import DatosSeleccionRepository


class DatosSeleccionService:
    def __init__(self):
        self.repo = DatosSeleccionRepository()

    def obtener_por_registro_personal(self, db: Session, id_registro_personal: int):
        return self.repo.get_by_registro_personal(db, id_registro_personal)

    def upsert(self, db: Session, payload: dict):
        return self.repo.upsert(db, payload)
