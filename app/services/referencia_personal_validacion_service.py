from sqlalchemy.orm import Session
from repositories.referencia_personal_validacion_repo import ReferenciaPersonalValidacionRepo

class ReferenciaPersonalValidacionService:
    @staticmethod
    def get(db: Session, aspirante_id: int, ref_idx: int):
        return ReferenciaPersonalValidacionRepo.get(db, aspirante_id, ref_idx)

    @staticmethod
    def upsert(db: Session, aspirante_id: int, ref_idx: int, data: dict):
        if ref_idx < 0:
            raise ValueError("ref_idx inválido")
        return ReferenciaPersonalValidacionRepo.upsert(db, aspirante_id, ref_idx, data)
