# app/services/contratacion_basica_service.py

from typing import Optional, Dict, Any
from sqlalchemy.orm import Session
from repositories.contratacion_basica_repo import ContratacionBasicaRepo
import inspect


class ContratacionBasicaService:
    def __init__(self) -> None:
        self.repo = ContratacionBasicaRepo()

        # DEBUG TEMPORAL: muestra el archivo REAL del repo en ejecución
        print(" REPO REAL EN USO:", inspect.getsourcefile(self.repo.__class__))

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

        # TetanosDosis: de 1 a 5
        tetanos_dosis = data.get("TetanosDosis")
        if tetanos_dosis is not None:
            if str(tetanos_dosis).strip() == "":
                data["TetanosDosis"] = None
            else:
                try:
                    tetanos_dosis = int(tetanos_dosis)
                except ValueError:
                    raise ValueError("TetanosDosis debe ser un número entre 1 y 5.")

                if tetanos_dosis < 1 or tetanos_dosis > 5:
                    raise ValueError("TetanosDosis inválida. Valores permitidos: 1 a 5.")

                data["TetanosDosis"] = tetanos_dosis

        # HepatitisDosis: de 1 a 4
        hepatitis_dosis = data.get("HepatitisDosis")
        if hepatitis_dosis is not None:
            if str(hepatitis_dosis).strip() == "":
                data["HepatitisDosis"] = None
            else:
                try:
                    hepatitis_dosis = int(hepatitis_dosis)
                except ValueError:
                    raise ValueError("HepatitisDosis debe ser un número entre 1 y 4.")

                if hepatitis_dosis < 1 or hepatitis_dosis > 4:
                    raise ValueError("HepatitisDosis inválida. Valores permitidos: 1 a 4.")

                data["HepatitisDosis"] = hepatitis_dosis

        # Ejecutar UPSERT y mostrar qué devuelve realmente
        result = self.repo.upsert_by_registro_personal(db, data)
        print(" RESULTADO UPSERT:", result)

        # Si por alguna razón retorna None, explotamos con mensaje claro
        if result is None:
            raise ValueError(
                "El repo upsert_by_registro_personal retornó None. "
                "Esto indica que se está usando un repo distinto al que editaste o falta un return."
            )

        return result