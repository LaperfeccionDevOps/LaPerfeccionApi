from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import text
import json

from infrastructure.db.deps import get_db

router = APIRouter(
    prefix="/api/perfil-aspirante",
    tags=["perfil-aspirante"],
)

@router.get("/{id_registro_personal}")
def get_perfil_aspirante(id_registro_personal: int, db: Session = Depends(get_db)):
    try:
        # ✅ llamada directa a tu función
        q = text("SELECT obtener_expediente_aspirante_json(:id) AS data")
        res = db.execute(q, {"id": id_registro_personal}).mappings().first()

        if not res or res.get("data") is None:
            raise HTTPException(status_code=404, detail="No hay expediente para este aspirante.")

        data = res["data"]

        # Si viene como texto JSON, lo convertimos
        if isinstance(data, str):
            data = data.strip()
            if not data:
                raise HTTPException(status_code=404, detail="Expediente vacío.")
            expediente = json.loads(data)
        else:
            expediente = data

        # Campos que la entrevistadora llena (quedan en blanco)
        entrevista_campos_en_blanco = {
            "fecha_proceso": None,
            "tipo_cargo": None,
            "ha_trabajado_antes_en_empresa": None,
            "antecedentes_medicos": None,
            "medicamentos": None,
            "observaciones": None,
        }

        documentos_esperados = [
            "Hoja de vida",
            "Cédula de ciudadanía",
            "Certificados laborales",
            "Certificados de estudio",
            "Certificado fondo de pensiones",
            "Certificado de cursos especiales",
        ]

        return {
            "id_registro_personal": id_registro_personal,
            "expediente": expediente,
            "entrevista_campos_en_blanco": entrevista_campos_en_blanco,
            "documentos_esperados": documentos_esperados,
        }

    except HTTPException:
        raise
    except Exception as e:
        # ✅ Esto te muestra el error REAL en la respuesta del 500
        raise HTTPException(status_code=500, detail=f"Error perfil-aspirante: {str(e)}")
