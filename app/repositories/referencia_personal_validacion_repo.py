from sqlalchemy.orm import Session
from domain.models.referencia_personal_validacion import ReferenciaPersonalValidacion

class ReferenciaPersonalValidacionRepo:
    @staticmethod
    def get(db: Session, aspirante_id: int, ref_idx: int):
        return (
            db.query(ReferenciaPersonalValidacion)
            .filter(
                ReferenciaPersonalValidacion.aspirante_id == aspirante_id,
                ReferenciaPersonalValidacion.ref_idx == ref_idx,
            )
            .first()
        )

    @staticmethod
    def upsert(db: Session, aspirante_id: int, ref_idx: int, data: dict):
        row = ReferenciaPersonalValidacionRepo.get(db, aspirante_id, ref_idx)

        # construir payload (merge)
        payload_new = data.get("payload") or {}
        # si te llega por campos sueltos, también los metemos al payload
        for k in ["hace_cuanto_lo_conoce", "descripcion", "lugar_vivienda", "tiene_hijos", "observaciones_referenciador"]:
            if k in data and data[k] is not None:
                payload_new[k] = data[k]
        if "extra" in data and isinstance(data["extra"], dict):
            payload_new.update(data["extra"])

        if row:
            if "validado" in data and data["validado"] is not None:
                row.validado = data["validado"]
            if "validado_por" in data:
                row.validado_por = data["validado_por"]

            old = row.payload or {}
            row.payload = {**old, **payload_new}

            db.add(row)
            db.commit()
            db.refresh(row)
            return row

        row = ReferenciaPersonalValidacion(
            aspirante_id=aspirante_id,
            ref_idx=ref_idx,
            validado=data.get("validado") if data.get("validado") is not None else False,
            payload=payload_new,
            validado_por=data.get("validado_por"),
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        return row
