# app/repositories/contratacion_basica_repo.py

from typing import Optional, Dict, Any
from sqlalchemy.orm import Session
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError


class ContratacionBasicaRepo:
    TABLE = '"ContratacionBasica"'

    # Campos que retornamos siempre (para no repetir tanto)
    RETURN_FIELDS = """
      "IdContratacionBasica",
      "IdRegistroPersonal",
      "IdBanco",
      "IdTipoContrato",
      "FechaIngreso",
      "RiesgoLaboral",
      "Posicion",
      "Escalafon",
      "NumeroCuenta",
      "FechaCreacion",
      "FechaActualizacion"
    """

    def get_by_registro_personal(self, db: Session, id_registro_personal: int) -> Optional[Dict[str, Any]]:
        sql = text(f"""
            SELECT
              {self.RETURN_FIELDS}
            FROM {self.TABLE}
            WHERE "IdRegistroPersonal" = :id_registro_personal
            LIMIT 1
        """)
        row = db.execute(sql, {"id_registro_personal": id_registro_personal}).mappings().first()
        return dict(row) if row else None

    def create(self, db: Session, data: Dict[str, Any]) -> Dict[str, Any]:
        sql = text(f"""
            INSERT INTO {self.TABLE} (
              "IdRegistroPersonal",
              "IdBanco",
              "IdTipoContrato",
              "FechaIngreso",
              "RiesgoLaboral",
              "Posicion",
              "Escalafon",
              "NumeroCuenta",
              "FechaCreacion",
              "FechaActualizacion"
            )
            VALUES (
              :IdRegistroPersonal,
              :IdBanco,
              :IdTipoContrato,
              :FechaIngreso,
              :RiesgoLaboral,
              :Posicion,
              :Escalafon,
              :NumeroCuenta,
              NOW(),
              NOW()
            )
            RETURNING
              {self.RETURN_FIELDS}
        """)

        # ✅ Payload seguro (todas las keys, aunque sean None)
        payload = {
            "IdRegistroPersonal": data.get("IdRegistroPersonal"),
            "IdBanco": data.get("IdBanco"),
            "IdTipoContrato": data.get("IdTipoContrato"),
            "FechaIngreso": data.get("FechaIngreso"),
            "RiesgoLaboral": data.get("RiesgoLaboral"),
            "Posicion": data.get("Posicion"),
            "Escalafon": data.get("Escalafon"),
            "NumeroCuenta": data.get("NumeroCuenta"),
        }

        try:
            row = db.execute(sql, payload).mappings().first()
            db.commit()
        except SQLAlchemyError as e:
            db.rollback()
            raise ValueError(f"Error SQL creando ContratacionBasica: {str(e)}")

        if not row:
            raise ValueError("No se pudo crear ContratacionBasica (INSERT no retornó fila).")

        return dict(row)

    def update_by_registro_personal(self, db: Session, id_registro_personal: int, data: Dict[str, Any]) -> Dict[str, Any]:
        # Actualiza SOLO lo que venga (COALESCE conserva si llega null)
        sql = text(f"""
            UPDATE {self.TABLE}
            SET
              "IdBanco" = COALESCE(:IdBanco, "IdBanco"),
              "IdTipoContrato" = COALESCE(:IdTipoContrato, "IdTipoContrato"),
              "FechaIngreso" = COALESCE(:FechaIngreso, "FechaIngreso"),
              "RiesgoLaboral" = COALESCE(:RiesgoLaboral, "RiesgoLaboral"),
              "Posicion" = COALESCE(:Posicion, "Posicion"),
              "Escalafon" = COALESCE(:Escalafon, "Escalafon"),
              "NumeroCuenta" = COALESCE(:NumeroCuenta, "NumeroCuenta"),
              "FechaActualizacion" = NOW()
            WHERE "IdRegistroPersonal" = :IdRegistroPersonal
            RETURNING
              {self.RETURN_FIELDS}
        """)

        payload = {
            "IdRegistroPersonal": id_registro_personal,
            "IdBanco": data.get("IdBanco"),
            "IdTipoContrato": data.get("IdTipoContrato"),
            "FechaIngreso": data.get("FechaIngreso"),
            "RiesgoLaboral": data.get("RiesgoLaboral"),
            "Posicion": data.get("Posicion"),
            "Escalafon": data.get("Escalafon"),
            "NumeroCuenta": data.get("NumeroCuenta"),
        }

        try:
            row = db.execute(sql, payload).mappings().first()
            db.commit()
        except SQLAlchemyError as e:
            db.rollback()
            raise ValueError(f"Error SQL actualizando ContratacionBasica: {str(e)}")

        if not row:
            raise ValueError(
                f"No se pudo actualizar ContratacionBasica (UPDATE no encontró fila) para IdRegistroPersonal={id_registro_personal}."
            )

        return dict(row)

    def upsert_by_registro_personal(self, db: Session, data: Dict[str, Any]) -> Dict[str, Any]:
        """
        ✅ UPSERT BLINDADO:
        - Si existe: update
        - Si no existe: create
        - Nunca retorna None (si falla, lanza ValueError)
        """
        id_reg = data.get("IdRegistroPersonal")
        if not id_reg:
            raise ValueError("IdRegistroPersonal es obligatorio para upsert.")

        existing = self.get_by_registro_personal(db, id_reg)

        if existing:
            result = self.update_by_registro_personal(db, id_reg, data)
        else:
            result = self.create(db, data)

        if not result:
            raise ValueError(f"upsert_by_registro_personal no retornó datos para IdRegistroPersonal={id_reg}")

        return result
