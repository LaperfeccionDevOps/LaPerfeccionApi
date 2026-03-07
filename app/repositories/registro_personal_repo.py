from sqlalchemy.orm import Session
from sqlalchemy import text
from typing import Dict, Any

class RegistroPersonalRepository:
    TABLE = 'RegistroPersonal'

    def update_by_id(self, db: Session, id_registro_personal: int, data: Dict[str, Any]) -> int:
        set_clauses = []
        params = {"id_registro_personal": id_registro_personal}
        for key, value in data.items():
            set_clauses.append(f'"{key}" = :{key}')
            params[key] = value
        set_clause = ', '.join(set_clauses)
        sql = text(f"""
            UPDATE "{self.TABLE}"
            SET {set_clause}
            WHERE "IdRegistroPersonal" = :id_registro_personal
        """)
        result = db.execute(sql, params)
        db.commit()
        return result.rowcount

    def update_direccion_datos_adicionales(self, db: Session, id_registro_personal: int, nueva_direccion: str, id_grupo_sanguineo: int) -> int:
        """
        Actualiza el campo Direccion y IdGrupoSanguineo en DatosAdicionales por IdRegistroPersonal.
        """
        sql = text('''
            UPDATE "DatosAdicionales"
            SET "Direccion" = :nueva_direccion, "IdGrupoSanguineo" = :id_grupo_sanguineo
            WHERE "IdRegistroPersonal" = :id_registro_personal
        ''')
        result = db.execute(sql, {"nueva_direccion": nueva_direccion, "id_grupo_sanguineo": id_grupo_sanguineo, "id_registro_personal": id_registro_personal})
        db.commit()
        return result.rowcount
