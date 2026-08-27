

from typing import Any

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session


class ContratacionBasicaRepo:
    TABLE = '"ContratacionBasica"'

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
      "TetanosDosis",
      "TetanosFechaUltimaDosis",
      "TetanosDescontable",
      "HepatitisDosis",
      "HepatitisFechaUltimaDosis",
      "HepatitisDescontable",
      "FechaCreacion",
      "FechaActualizacion"
    """

    def _get_row_by_registro_personal(
        self,
        db: Session,
        id_registro_personal: int,
    ) -> dict[str, Any] | None:
        """
        Consulta física de ContratacionBasica.

        Este helper NO aplica reglas de reintegro.
        Se usa internamente para decidir INSERT/UPDATE sin perder
        la fila operativa que ya existe para el trabajador.
        """
        sql = text(
            f"""
            SELECT
              {self.RETURN_FIELDS}
            FROM {self.TABLE}
            WHERE "IdRegistroPersonal" = :id_registro_personal
            LIMIT 1
            """
        )

        row = db.execute(
            sql,
            {"id_registro_personal": id_registro_personal},
        ).mappings().first()

        return dict(row) if row else None

    def _get_reintegro_activo(
        self,
        db: Session,
        id_registro_personal: int,
    ) -> dict[str, Any] | None:
        """
        Obtiene únicamente el ciclo de REINTEGRO abierto.

        Si el trabajador no está en reintegro, retorna None y todo
        conserva el comportamiento histórico del módulo.
        """
        row = db.execute(
            text(
                """
                SELECT
                    vl."IdVinculacionLaboral",
                    vl."NumeroCiclo",
                    vl."TipoVinculacion",
                    vl."EstadoVinculacion",
                    vl."FechaIngreso",
                    vl."IdCargo",
                    vl."IdCliente",
                    vl."Salario",
                    vl."IdTipoContrato"
                FROM public."VinculacionLaboral" vl
                WHERE vl."IdRegistroPersonal" = :id_registro_personal
                  AND UPPER(
                      COALESCE(vl."TipoVinculacion", '')
                  ) = 'REINTEGRO'
                  AND UPPER(
                      COALESCE(vl."EstadoVinculacion", '')
                  ) = 'EN_PROCESO'
                ORDER BY
                    vl."NumeroCiclo" DESC,
                    vl."IdVinculacionLaboral" DESC
                LIMIT 1
                """
            ),
            {"id_registro_personal": id_registro_personal},
        ).mappings().first()

        return dict(row) if row else None

    def _get_retiro_cerrado(
        self,
        db: Session,
        id_registro_personal: int,
    ) -> dict[str, Any] | None:
        """
        Obtiene el retiro más reciente que ya cerró/finalizó el ciclo laboral.

        Esta consulta se usa únicamente como protección de integridad:
        un retiro cerrado no debe ser alterado indirectamente por un guardado
        posterior de ContratacionBasica.

        Si existe un REINTEGRO EN_PROCESO, la regla de reintegro tiene
        prioridad y permite registrar la nueva FechaIngreso del nuevo ciclo.
        """
        row = db.execute(
            text(
                """
                SELECT
                    rl."IdRetiroLaboral",
                    rl."FechaRetiro",
                    rl."FechaCierre",
                    rl."FechaEnvioNomina",
                    rl."EstadoCasoRRLL",
                    rl."Activo",
                    rl."IdMotivoRetiro",
                    rl."ObservacionRetiro"
                FROM public."RetiroLaboral" rl
                WHERE rl."IdRegistroPersonal" = :id_registro_personal
                  AND (
                        COALESCE(rl."Activo", TRUE) = FALSE
                        OR UPPER(
                            COALESCE(rl."EstadoCasoRRLL", '')
                        ) = 'CERRADO'
                        OR rl."FechaEnvioNomina" IS NOT NULL
                      )
                ORDER BY
                    COALESCE(
                        rl."FechaActualizacion",
                        rl."FechaCreacion"
                    ) DESC,
                    rl."IdRetiroLaboral" DESC
                LIMIT 1
                """
            ),
            {"id_registro_personal": id_registro_personal},
        ).mappings().first()

        return dict(row) if row else None

    def get_by_registro_personal(
        self,
        db: Session,
        id_registro_personal: int,
    ) -> dict[str, Any] | None:
        """
        Consulta usada por el formulario de Contratación Básica.

        Regla de reintegro:
        - Si existe un REINTEGRO EN_PROCESO y todavía no se ha guardado
          su nueva FechaIngreso / IdTipoContrato, NO se devuelve la
          ContratacionBasica anterior.
        - De esta forma el modal no precarga silenciosamente los datos
          del ciclo histórico.
        - Una vez guardado el nuevo ciclo, el formulario vuelve a
          consultar la fila operativa actual de ContratacionBasica.

        Para trabajadores sin reintegro mantiene el comportamiento
        anterior.
        """
        actual = self._get_row_by_registro_personal(
            db,
            id_registro_personal,
        )

        if not actual:
            return None

        reintegro = self._get_reintegro_activo(
            db,
            id_registro_personal,
        )

        if not reintegro:
            return actual

        reintegro_sin_contratacion = (
            reintegro.get("FechaIngreso") is None
            and reintegro.get("IdTipoContrato") is None
        )

        if reintegro_sin_contratacion:
            return None

        return actual

    def _sincronizar_reintegro_activo(
        self,
        db: Session,
        id_registro_personal: int,
        contratacion: dict[str, Any],
    ) -> None:
        """
        Sincroniza SOLO el ciclo REINTEGRO / EN_PROCESO.

        Fuente de datos:
        - IdTipoContrato y FechaIngreso:
          ContratacionBasica recién guardada.
        - IdCargo, IdCliente y Salario:
          AsignacionCargoCliente operativa actual.

        No modifica ciclos históricos.
        No crea ni elimina vinculaciones.
        """
        reintegro = self._get_reintegro_activo(
            db,
            id_registro_personal,
        )

        if not reintegro:
            return

        asignacion = db.execute(
            text(
                """
                SELECT
                    acc."IdCargo",
                    acc."IdCliente",
                    acc."Salario"
                FROM public."AsignacionCargoCliente" acc
                WHERE acc."IdRegistroPersonal" = :id_registro_personal
                ORDER BY
                    acc."IdAsignacionCargoCliente" DESC
                LIMIT 1
                """
            ),
            {"id_registro_personal": id_registro_personal},
        ).mappings().first()

        id_cargo = (
            asignacion.get("IdCargo")
            if asignacion
            else None
        )
        id_cliente = (
            asignacion.get("IdCliente")
            if asignacion
            else None
        )
        salario = (
            asignacion.get("Salario")
            if asignacion
            else None
        )

        db.execute(
            text(
                """
                UPDATE public."VinculacionLaboral"
                SET
                    "FechaIngreso" = :fecha_ingreso,
                    "IdCargo" = :id_cargo,
                    "IdCliente" = :id_cliente,
                    "Salario" = :salario,
                    "IdTipoContrato" = :id_tipo_contrato,
                    "FechaActualizacion" = NOW()
                WHERE "IdVinculacionLaboral" = :id_vinculacion_laboral
                  AND "IdRegistroPersonal" = :id_registro_personal
                  AND UPPER(
                      COALESCE("TipoVinculacion", '')
                  ) = 'REINTEGRO'
                  AND UPPER(
                      COALESCE("EstadoVinculacion", '')
                  ) = 'EN_PROCESO'
                """
            ),
            {
                "fecha_ingreso": contratacion.get("FechaIngreso"),
                "id_cargo": id_cargo,
                "id_cliente": id_cliente,
                "salario": salario,
                "id_tipo_contrato": contratacion.get(
                    "IdTipoContrato"
                ),
                "id_vinculacion_laboral": reintegro[
                    "IdVinculacionLaboral"
                ],
                "id_registro_personal": id_registro_personal,
            },
        )

    def create(
        self,
        db: Session,
        data: dict[str, Any],
    ) -> dict[str, Any]:
        sql = text(
            f"""
            INSERT INTO {self.TABLE} (
              "IdRegistroPersonal",
              "IdBanco",
              "IdTipoContrato",
              "FechaIngreso",
              "RiesgoLaboral",
              "Posicion",
              "Escalafon",
              "NumeroCuenta",
              "TetanosDosis",
              "TetanosFechaUltimaDosis",
              "TetanosDescontable",
              "HepatitisDosis",
              "HepatitisFechaUltimaDosis",
              "HepatitisDescontable",
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
              :TetanosDosis,
              :TetanosFechaUltimaDosis,
              :TetanosDescontable,
              :HepatitisDosis,
              :HepatitisFechaUltimaDosis,
              :HepatitisDescontable,
              NOW(),
              NOW()
            )
            RETURNING
              {self.RETURN_FIELDS}
            """
        )

        payload = {
            "IdRegistroPersonal": data.get(
                "IdRegistroPersonal"
            ),
            "IdBanco": data.get("IdBanco"),
            "IdTipoContrato": data.get("IdTipoContrato"),
            "FechaIngreso": data.get("FechaIngreso"),
            "RiesgoLaboral": data.get("RiesgoLaboral"),
            "Posicion": data.get("Posicion"),
            "Escalafon": data.get("Escalafon"),
            "NumeroCuenta": data.get("NumeroCuenta"),
            "TetanosDosis": data.get("TetanosDosis"),
            "TetanosFechaUltimaDosis": data.get(
                "TetanosFechaUltimaDosis"
            ),
            "TetanosDescontable": data.get(
                "TetanosDescontable"
            ),
            "HepatitisDosis": data.get("HepatitisDosis"),
            "HepatitisFechaUltimaDosis": data.get(
                "HepatitisFechaUltimaDosis"
            ),
            "HepatitisDescontable": data.get(
                "HepatitisDescontable"
            ),
        }

        try:
            row = db.execute(
                sql,
                payload,
            ).mappings().first()

            if not row:
                raise ValueError(
                    "No se pudo crear ContratacionBasica "
                    "(INSERT no retornó fila)."
                )

            result = dict(row)

            self._sincronizar_reintegro_activo(
                db,
                int(result["IdRegistroPersonal"]),
                result,
            )

            db.commit()

        except SQLAlchemyError as exc:
            db.rollback()
            raise ValueError(
                "Error SQL creando ContratacionBasica: "
                f"{exc}"
            ) from exc

        except Exception:
            db.rollback()
            raise

        return result

    def update_by_registro_personal(
        self,
        db: Session,
        id_registro_personal: int,
        data: dict[str, Any],
    ) -> dict[str, Any]:
        actual = self._get_row_by_registro_personal(
            db,
            id_registro_personal,
        )
        reintegro = self._get_reintegro_activo(
            db,
            id_registro_personal,
        )
        retiro_cerrado = self._get_retiro_cerrado(
            db,
            id_registro_personal,
        )

        fecha_ingreso_solicitada = data.get("FechaIngreso")

        # Protección de integridad del retiro:
        # si el ciclo ya fue cerrado/finalizado y NO existe un reintegro
        # activo, ContratacionBasica no puede reescribir la FechaIngreso
        # histórica. Los demás campos sí pueden actualizarse normalmente.
        if actual and retiro_cerrado and not reintegro:
            fecha_ingreso_solicitada = actual.get("FechaIngreso")

        sql = text(
            f"""
            UPDATE {self.TABLE}
            SET
              "IdBanco" = COALESCE(:IdBanco, "IdBanco"),
              "IdTipoContrato" = COALESCE(
                  :IdTipoContrato,
                  "IdTipoContrato"
              ),
              "FechaIngreso" = COALESCE(
                  :FechaIngreso,
                  "FechaIngreso"
              ),
              "RiesgoLaboral" = COALESCE(
                  :RiesgoLaboral,
                  "RiesgoLaboral"
              ),
              "Posicion" = COALESCE(
                  :Posicion,
                  "Posicion"
              ),
              "Escalafon" = COALESCE(
                  :Escalafon,
                  "Escalafon"
              ),
              "NumeroCuenta" = COALESCE(
                  :NumeroCuenta,
                  "NumeroCuenta"
              ),
              "TetanosDosis" = COALESCE(
                  :TetanosDosis,
                  "TetanosDosis"
              ),
              "TetanosFechaUltimaDosis" = COALESCE(
                  :TetanosFechaUltimaDosis,
                  "TetanosFechaUltimaDosis"
              ),
              "TetanosDescontable" = COALESCE(
                  :TetanosDescontable,
                  "TetanosDescontable"
              ),
              "HepatitisDosis" = COALESCE(
                  :HepatitisDosis,
                  "HepatitisDosis"
              ),
              "HepatitisFechaUltimaDosis" = COALESCE(
                  :HepatitisFechaUltimaDosis,
                  "HepatitisFechaUltimaDosis"
              ),
              "HepatitisDescontable" = COALESCE(
                  :HepatitisDescontable,
                  "HepatitisDescontable"
              ),
              "FechaActualizacion" = NOW()
            WHERE "IdRegistroPersonal" = :IdRegistroPersonal
            RETURNING
              {self.RETURN_FIELDS}
            """
        )

        payload = {
            "IdRegistroPersonal": id_registro_personal,
            "IdBanco": data.get("IdBanco"),
            "IdTipoContrato": data.get("IdTipoContrato"),
            "FechaIngreso": fecha_ingreso_solicitada,
            "RiesgoLaboral": data.get("RiesgoLaboral"),
            "Posicion": data.get("Posicion"),
            "Escalafon": data.get("Escalafon"),
            "NumeroCuenta": data.get("NumeroCuenta"),
            "TetanosDosis": data.get("TetanosDosis"),
            "TetanosFechaUltimaDosis": data.get(
                "TetanosFechaUltimaDosis"
            ),
            "TetanosDescontable": data.get(
                "TetanosDescontable"
            ),
            "HepatitisDosis": data.get("HepatitisDosis"),
            "HepatitisFechaUltimaDosis": data.get(
                "HepatitisFechaUltimaDosis"
            ),
            "HepatitisDescontable": data.get(
                "HepatitisDescontable"
            ),
        }

        try:
            row = db.execute(
                sql,
                payload,
            ).mappings().first()

            if not row:
                raise ValueError(
                    "No se pudo actualizar ContratacionBasica "
                    "(UPDATE no encontró fila) para "
                    "IdRegistroPersonal="
                    f"{id_registro_personal}."
                )

            result = dict(row)

            self._sincronizar_reintegro_activo(
                db,
                id_registro_personal,
                result,
            )

            db.commit()

        except SQLAlchemyError as exc:
            db.rollback()
            raise ValueError(
                "Error SQL actualizando ContratacionBasica: "
                f"{exc}"
            ) from exc

        except Exception:
            db.rollback()
            raise

        return result

    def upsert_by_registro_personal(
        self,
        db: Session,
        data: dict[str, Any],
    ) -> dict[str, Any]:
        id_reg = data.get("IdRegistroPersonal")

        if not id_reg:
            raise ValueError(
                "IdRegistroPersonal es obligatorio para upsert."
            )

        # IMPORTANTE:
        # Para decidir INSERT/UPDATE se consulta la fila física,
        # no la vista lógica del formulario de reintegro.
        existing = self._get_row_by_registro_personal(
            db,
            int(id_reg),
        )

        if existing:
            result = self.update_by_registro_personal(
                db,
                int(id_reg),
                data,
            )
        else:
            retiro_cerrado = self._get_retiro_cerrado(
                db,
                int(id_reg),
            )
            reintegro = self._get_reintegro_activo(
                db,
                int(id_reg),
            )

            if retiro_cerrado and not reintegro:
                raise ValueError(
                    "No se puede crear ContratacionBasica para un "
                    "trabajador con retiro cerrado sin un reintegro "
                    "EN_PROCESO."
                )

            result = self.create(
                db,
                data,
            )

        if not result:
            raise ValueError(
                "upsert_by_registro_personal no retornó datos "
                f"para IdRegistroPersonal={id_reg}"
            )

        return result