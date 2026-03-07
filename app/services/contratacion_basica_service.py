# app/services/contratacion_basica_service.py

from typing import Optional, Dict, Any
from sqlalchemy.orm import Session
from repositories.contratacion_basica_repo import ContratacionBasicaRepo
import inspect


class ContratacionBasicaService:
    def __init__(self) -> None:
        self.repo = ContratacionBasicaRepo()

        # ✅ DEBUG TEMPORAL: muestra el archivo REAL del repo en ejecución
        print("📌 REPO REAL EN USO:", inspect.getsourcefile(self.repo.__class__))

    def obtener(self, db: Session, id_registro_personal: int) -> Optional[Dict[str, Any]]:
        return self.repo.get_by_registro_personal(db, id_registro_personal)

    def guardar(self, db: Session, data: Dict[str, Any]) -> Dict[str, Any]:
        # Reglas mínimas
        if not data.get("IdRegistroPersonal"):
            raise ValueError("IdRegistroPersonal es obligatorio")

        # Riesgo laboral opcional (validación suave)
        riesgo = data.get("RiesgoLaboral")
        if riesgo is not None:
            riesgo = str(riesgo).strip().upper()
            data["RiesgoLaboral"] = riesgo

        # ✅ NUEVOS CAMPOS (normalización/validación suave)

        # Posicion: texto manual (código numérico, pero lo guardamos como string)
        pos = data.get("Posicion")
        if pos is not None:
            pos = str(pos).strip()
            data["Posicion"] = pos if pos != "" else None

        # NumeroCuenta: texto manual (NO numérico)
        num_cuenta = data.get("NumeroCuenta")
        if num_cuenta is not None:
            num_cuenta = str(num_cuenta).strip()
            data["NumeroCuenta"] = num_cuenta if num_cuenta != "" else None

        # Escalafon: solo 200 o 220 (si viene)
        esc = data.get("Escalafon")
        if esc is not None:
            esc = str(esc).strip()
            if esc == "":
                data["Escalafon"] = None
            else:
                if esc not in ("200", "220"):
                    raise ValueError("Escalafon inválido. Valores permitidos: 200 o 220.")
                data["Escalafon"] = esc

        # ✅ Ejecutar UPSERT y mostrar qué devuelve realmente
        result = self.repo.upsert_by_registro_personal(db, data)
        print("📌 RESULTADO UPSERT:", result)

        # ✅ Si por alguna razón retorna None, explotamos con mensaje claro
        if result is None:
            raise ValueError(
                "El repo upsert_by_registro_personal retornó None. "
                "Esto indica que se está usando un repo distinto al que editaste o falta un return."
            )

        return result
