# app/services/contratacion_basica_service.py

import inspect
from typing import Any

from sqlalchemy.orm import Session

from repositories.contratacion_basica_repo import ContratacionBasicaRepo


class ContratacionBasicaService:
    def __init__(self) -> None:
        self.repo = ContratacionBasicaRepo()

        # DEBUG TEMPORAL:
        # muestra el archivo real del repo en ejecución.
        print(
            "REPO REAL EN USO:",
            inspect.getsourcefile(self.repo.__class__),
        )

    def obtener(
        self,
        db: Session,
        id_registro_personal: int,
    ) -> dict[str, Any] | None:
        return self.repo.get_by_registro_personal(
            db,
            id_registro_personal,
        )

    def guardar(
        self,
        db: Session,
        data: dict[str, Any],
    ) -> dict[str, Any]:
        if not data.get("IdRegistroPersonal"):
            raise ValueError(
                "IdRegistroPersonal es obligatorio"
            )

        # IdVinculacionLaboral pertenece al flujo por ciclos,
        # pero ContratacionBasica no tiene esa columna.
        # Lo conservamos aparte para que el repo no intente
        # insertarlo o actualizarlo directamente.
        id_vinculacion_laboral = data.pop(
            "IdVinculacionLaboral",
            None,
        )

        riesgo = data.get("RiesgoLaboral")
        if riesgo is not None:
            riesgo = str(riesgo).strip().upper()
            data["RiesgoLaboral"] = riesgo or None

        pos = data.get("Posicion")
        if pos is not None:
            pos = str(pos).strip()
            data["Posicion"] = pos or None

        num_cuenta = data.get("NumeroCuenta")
        if num_cuenta is not None:
            num_cuenta = str(num_cuenta).strip()
            data["NumeroCuenta"] = num_cuenta or None

        esc = data.get("Escalafon")
        if esc is not None:
            esc = str(esc).strip()

            if esc == "":
                data["Escalafon"] = None
            else:
                if esc not in ("200", "210", "220"):
                    raise ValueError(
                        "Escalafon inválido. Valores permitidos: "
                        "200, 210 o 220."
                    )

                data["Escalafon"] = esc

        tetanos_dosis = data.get("TetanosDosis")
        if tetanos_dosis is not None:
            if str(tetanos_dosis).strip() == "":
                data["TetanosDosis"] = None
            else:
                try:
                    tetanos_dosis = int(tetanos_dosis)
                except (TypeError, ValueError) as exc:
                    raise ValueError(
                        "TetanosDosis debe ser un número entre 1 y 5."
                    ) from exc

                if not 1 <= tetanos_dosis <= 5:
                    raise ValueError(
                        "TetanosDosis inválida. "
                        "Valores permitidos: 1 a 5."
                    )

                data["TetanosDosis"] = tetanos_dosis

        hepatitis_dosis = data.get("HepatitisDosis")
        if hepatitis_dosis is not None:
            if str(hepatitis_dosis).strip() == "":
                data["HepatitisDosis"] = None
            else:
                try:
                    hepatitis_dosis = int(hepatitis_dosis)
                except (TypeError, ValueError) as exc:
                    raise ValueError(
                        "HepatitisDosis debe ser un número entre 1 y 4."
                    ) from exc

                if not 1 <= hepatitis_dosis <= 4:
                    raise ValueError(
                        "HepatitisDosis inválida. "
                        "Valores permitidos: 1 a 4."
                    )

                data["HepatitisDosis"] = hepatitis_dosis

        result = self.repo.upsert_by_registro_personal(
            db,
            data,
        )

        print(
            "RESULTADO UPSERT:",
            result,
        )

        if result is None:
            raise ValueError(
                "El repo upsert_by_registro_personal retornó None. "
                "Esto indica que se está usando un repo distinto "
                "al esperado o que falta un return."
            )

        # Se vuelve a incluir en la respuesta únicamente para
        # que el flujo pueda conservar el contexto del ciclo.
        if (
            id_vinculacion_laboral is not None
            and isinstance(result, dict)
        ):
            result["IdVinculacionLaboral"] = (
                id_vinculacion_laboral
            )

        return result