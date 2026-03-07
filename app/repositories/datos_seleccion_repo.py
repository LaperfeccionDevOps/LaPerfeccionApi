from sqlalchemy.orm import Session
from domain.models.datos_seleccion import DatosSeleccion


class DatosSeleccionRepository:
    def get_by_registro_personal(self, db: Session, id_registro_personal: int) -> DatosSeleccion | None:
        return (
            db.query(DatosSeleccion)
            .filter(DatosSeleccion.IdRegistroPersonal == id_registro_personal)
            .first()
        )

    def upsert(self, db: Session, payload: dict) -> DatosSeleccion:
        existente = self.get_by_registro_personal(db, payload["IdRegistroPersonal"])

        if existente:
            existente.FechaProceso = payload["FechaProceso"]
            existente.TipoCargo = payload["TipoCargo"]

            # ✅ CAMBIO AQUÍ
            existente.HaTrabajadoAntesEnLaEmpresa = payload["HaTrabajadoAntesEnLaEmpresa"]

            existente.Arl = payload.get("Arl")
            existente.AntecedentesMedicos = payload.get("AntecedentesMedicos")
            existente.Medicamentos = payload.get("Medicamentos")
            existente.UsuarioActualizacion = payload["UsuarioActualizacion"]

            db.add(existente)
            db.commit()
            db.refresh(existente)
            return existente

        nuevo = DatosSeleccion(**payload)
        db.add(nuevo)
        db.commit()
        db.refresh(nuevo)
        return nuevo
