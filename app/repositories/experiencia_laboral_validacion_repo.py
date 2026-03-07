from sqlalchemy import text
from sqlalchemy.orm import Session


class ExperienciaLaboralValidacionRepo:
    def get_by_experiencia_laboral(self, db: Session, id_experiencia_laboral: int):
        q = text("""
            SELECT
                "IdValidacion",
                "IdExperienciaLaboral",
                "Concepto",
                "DesempenoReportado",
                "MotivoRetiroReal",
                "PersonaQueReferencia",
                "CreadoEn",
                "ActualizadoEn"
            FROM "ExperienciaLaboralValidacion"
            WHERE "IdExperienciaLaboral" = :id_exp
            ORDER BY "ActualizadoEn" DESC NULLS LAST, "IdValidacion" DESC
        """)
        rows = db.execute(q, {"id_exp": id_experiencia_laboral}).mappings().all()
        return [dict(r) for r in rows]

    def get_by_id(self, db: Session, id_validacion: int):
        q = text("""
            SELECT
                "IdValidacion",
                "IdExperienciaLaboral",
                "Concepto",
                "DesempenoReportado",
                "MotivoRetiroReal",
                "PersonaQueReferencia",
                "CreadoEn",
                "ActualizadoEn"
            FROM "ExperienciaLaboralValidacion"
            WHERE "IdValidacion" = :idv
            LIMIT 1
        """)
        row = db.execute(q, {"idv": id_validacion}).mappings().first()
        return dict(row) if row else None
