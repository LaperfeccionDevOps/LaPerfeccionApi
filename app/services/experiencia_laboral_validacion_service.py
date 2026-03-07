from sqlalchemy.orm import Session

from repositories.experiencia_laboral_validacion_repo import ExperienciaLaboralValidacionRepo


class ExperienciaLaboralValidacionService:
    def __init__(self):
        self.repo = ExperienciaLaboralValidacionRepo()

    def listar_por_experiencia(self, db: Session, id_experiencia_laboral: int):
        # Devuelve [] si no hay registros (más fácil para el front).
        return self.repo.get_by_experiencia_laboral(db, id_experiencia_laboral)

    def obtener_por_id(self, db: Session, id_validacion: int):
        return self.repo.get_by_id(db, id_validacion)
