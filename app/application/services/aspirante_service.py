from fastapi import HTTPException, status
from sqlalchemy import text
from sqlalchemy.orm import Session

from domain.models.aspirante import (
    RegistroPersonal,
    NucleoFamiliarORM,
    ReferenciaORM,
    ExperienciaLaboralORM,
    ExperienciaLaboralValidacion,
    DocumentacionORM,
    DatosAdicionalesORM,
)
from domain.schemas.aspirante import (
    RegistroPersonalCreate,
    ExperienciaLaboralCreateSeleccionSchema,
)
from infrastructure.repositories.aspirante_repo import create
from repositories.contador_registro_personal_repo import contador_registro_personal
from services.vinculacion_laboral_service import obtener_vinculacion_abierta

import base64
import re


_TABLAS_VINCULACION_PERMITIDAS = {
    "NucleoFamiliar": "IdNucleoFamiliar",
    "Referencia": "IdReferencia",
    "ExperienciaLaboral": "IdExperienciaLaboral",
    "RelacionTipoDocumentacion": "IdRelacion",
}


def _obtener_id_vinculacion_abierta(
    db: Session,
    id_registro_personal: int,
) -> int | None:
    vinculacion = obtener_vinculacion_abierta(
        db,
        id_registro_personal,
    )

    if not vinculacion:
        return None

    id_vinculacion = vinculacion.get("IdVinculacionLaboral")

    if id_vinculacion is None:
        return None

    return int(id_vinculacion)


def _es_reintegro_en_proceso(
    db: Session,
    id_registro_personal: int,
    id_vinculacion_laboral: int | None,
) -> bool:
    if id_vinculacion_laboral is None:
        return False

    row = db.execute(
        text(
            """
            SELECT 1
            FROM public."VinculacionLaboral"
            WHERE "IdVinculacionLaboral" = :id_vinculacion
              AND "IdRegistroPersonal" = :id_registro
              AND "TipoVinculacion" = 'REINTEGRO'
              AND "EstadoVinculacion" = 'EN_PROCESO'
            LIMIT 1;
            """
        ),
        {
            "id_vinculacion": id_vinculacion_laboral,
            "id_registro": id_registro_personal,
        },
    ).first()

    return row is not None


def _asignar_vinculacion(
    db: Session,
    tabla: str,
    id_fila: int,
    id_vinculacion_laboral: int | None,
) -> None:
    if id_vinculacion_laboral is None:
        return

    id_columna = _TABLAS_VINCULACION_PERMITIDAS.get(tabla)

    if not id_columna:
        raise ValueError(
            f"Tabla no permitida para asociación de vinculación: {tabla}"
        )

    sql = text(
        f'''
        UPDATE public."{tabla}"
        SET "IdVinculacionLaboral" = :id_vinculacion
        WHERE "{id_columna}" = :id_fila;
        '''
    )

    db.execute(
        sql,
        {
            "id_vinculacion": id_vinculacion_laboral,
            "id_fila": id_fila,
        },
    )


def _obtener_vinculacion_experiencia(
    db: Session,
    id_experiencia_laboral: int,
    id_registro_personal: int,
) -> int | None:
    row = db.execute(
        text(
            '''
            SELECT "IdVinculacionLaboral"
            FROM public."ExperienciaLaboral"
            WHERE "IdExperienciaLaboral" = :id_experiencia
              AND "IdRegistroPersonal" = :id_registro
            LIMIT 1;
            '''
        ),
        {
            "id_experiencia": id_experiencia_laboral,
            "id_registro": id_registro_personal,
        },
    ).mappings().first()

    if not row:
        return None

    value = row.get("IdVinculacionLaboral")
    return int(value) if value is not None else None


def _buscar_experiencia_en_ciclo(
    db: Session,
    id_registro_personal: int,
    id_vinculacion_laboral: int,
    cargo,
    compania,
) -> int | None:
    row = db.execute(
        text(
            '''
            SELECT "IdExperienciaLaboral"
            FROM public."ExperienciaLaboral"
            WHERE "IdRegistroPersonal" = :id_registro
              AND "IdVinculacionLaboral" = :id_vinculacion
              AND "Cargo" IS NOT DISTINCT FROM :cargo
              AND "Compania" IS NOT DISTINCT FROM :compania
            ORDER BY "IdExperienciaLaboral" DESC
            LIMIT 1;
            '''
        ),
        {
            "id_registro": id_registro_personal,
            "id_vinculacion": id_vinculacion_laboral,
            "cargo": cargo,
            "compania": compania,
        },
    ).mappings().first()

    if not row:
        return None

    return int(row["IdExperienciaLaboral"])


def crear_registro(db: Session, payload: RegistroPersonalCreate) -> None:
    try:
        nuevo = RegistroPersonal(
            **payload.dict(
                exclude={
                    "NucleoFamiliar",
                    "Referencias",
                    "ExperienciaLaboral",
                    "Documentacion",
                    "DatosAdicionales",
                }
            )
        )

        if hasattr(payload, "IdFondoCesantias"):
            nuevo.IdFondoCesantias = payload.IdFondoCesantias

        db.add(nuevo)
        db.flush()

        nucleo_familiar = [
            NucleoFamiliarORM(
                **{
                    **nf.dict(),
                    "IdRegistroPersonal": nuevo.IdRegistroPersonal,
                }
            )
            for nf in payload.NucleoFamiliar
        ]
        nuevo.nucleo_familiar = nucleo_familiar

        referencias = [
            ReferenciaORM(
                **{
                    **rp.dict(),
                    "IdRegistroPersonal": nuevo.IdRegistroPersonal,
                }
            )
            for rp in payload.Referencias
        ]
        nuevo.referencias = referencias

        experiencia_laboral = [
            ExperienciaLaboralORM(
                **{
                    **el.dict(),
                    "IdRegistroPersonal": nuevo.IdRegistroPersonal,
                }
            )
            for el in payload.ExperienciaLaboral
        ]
        nuevo.experiencia_laboral = experiencia_laboral

        from domain.models.aspirante import RelacionTipoDocumentacionORM

        for doc in payload.Documentacion:
            doc_data = doc.dict()
            base64_str = doc_data["DocumentoCargado"]

            try:
                base64_str = limpiar_base64(base64_str)
                doc_data["DocumentoCargado"] = base64.b64decode(base64_str)
            except Exception as e:
                print(f"Error al procesar base64: {e}")
                doc_data["DocumentoCargado"] = None

            doc_obj = DocumentacionORM(**doc_data)
            db.add(doc_obj)
            db.flush()

            relacion = RelacionTipoDocumentacionORM(
                IdRegistroPersonal=nuevo.IdRegistroPersonal,
                IdDocumento=doc_obj.IdDocumento,
            )
            db.add(relacion)

        if payload.DatosAdicionales:
            datos_adicionales_dict = payload.DatosAdicionales.dict()
            datos_adicionales_dict["IdRegistroPersonal"] = nuevo.IdRegistroPersonal
            datos_adicionales = DatosAdicionalesORM(**datos_adicionales_dict)
            db.add(datos_adicionales)

        db.commit()
        db.refresh(nuevo)
        contador_registro_personal(db, nuevo.IdRegistroPersonal)

        return nuevo

    except HTTPException:
        db.rollback()
        raise

    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error controlado {str(e)}",
        )


def limpiar_base64(base64_str: str) -> str:
    if isinstance(base64_str, bytes):
        base64_str = base64_str.decode("utf-8")

    match = re.match(r"^data:.*?;base64,(.*)", base64_str)

    if match:
        return match.group(1)

    return base64_str


def actualizar_registro(
    db: Session,
    id_registro: int,
    payload: RegistroPersonalCreate,
) -> None:
    try:
        registro = (
            db.query(RegistroPersonal)
            .filter(
                RegistroPersonal.IdRegistroPersonal == id_registro
            )
            .first()
        )

        if not registro:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="RegistroPersonal no encontrado",
            )

        estado_antes_actualizacion = registro.IdEstadoProceso

        id_vinculacion_abierta = _obtener_id_vinculacion_abierta(
            db,
            id_registro,
        )

        es_reintegro_en_proceso = (
            int(estado_antes_actualizacion) == 35
            and _es_reintegro_en_proceso(
                db,
                id_registro,
                id_vinculacion_abierta,
            )
        )

        # RegistroPersonal sigue representando la información actual.
        for key, value in payload.dict(
            exclude={
                "NucleoFamiliar",
                "Referencias",
                "ExperienciaLaboral",
                "Documentacion",
                "DatosAdicionales",
            }
        ).items():
            setattr(registro, key, value)

        if hasattr(payload, "IdFondoCesantias"):
            registro.IdFondoCesantias = payload.IdFondoCesantias

        # NucleoFamiliar
        if payload.NucleoFamiliar:
            if id_vinculacion_abierta is not None:
                db.execute(
                    text(
                        '''
                        DELETE FROM public."NucleoFamiliar"
                        WHERE "IdRegistroPersonal" = :id_registro
                          AND "IdVinculacionLaboral" = :id_vinculacion;
                        '''
                    ),
                    {
                        "id_registro": id_registro,
                        "id_vinculacion": id_vinculacion_abierta,
                    },
                )

                for nf in payload.NucleoFamiliar:
                    nf_obj = NucleoFamiliarORM(
                        **{
                            **nf.dict(),
                            "IdRegistroPersonal": id_registro,
                        }
                    )
                    db.add(nf_obj)
                    db.flush()

                    _asignar_vinculacion(
                        db,
                        "NucleoFamiliar",
                        nf_obj.IdNucleoFamiliar,
                        id_vinculacion_abierta,
                    )
            else:
                db.query(NucleoFamiliarORM).filter(
                    NucleoFamiliarORM.IdRegistroPersonal == id_registro
                ).delete()

                nucleo_familiar = [
                    NucleoFamiliarORM(
                        **{
                            **nf.dict(),
                            "IdRegistroPersonal": id_registro,
                        }
                    )
                    for nf in payload.NucleoFamiliar
                ]
                registro.nucleo_familiar = nucleo_familiar

        # Referencias
        if payload.Referencias:
            if id_vinculacion_abierta is not None:
                db.execute(
                    text(
                        '''
                        DELETE FROM public."Referencia"
                        WHERE "IdRegistroPersonal" = :id_registro
                          AND "IdVinculacionLaboral" = :id_vinculacion;
                        '''
                    ),
                    {
                        "id_registro": id_registro,
                        "id_vinculacion": id_vinculacion_abierta,
                    },
                )

                for rp in payload.Referencias:
                    referencia_obj = ReferenciaORM(
                        **{
                            **rp.dict(),
                            "IdRegistroPersonal": id_registro,
                        }
                    )
                    db.add(referencia_obj)
                    db.flush()

                    _asignar_vinculacion(
                        db,
                        "Referencia",
                        referencia_obj.IdReferencia,
                        id_vinculacion_abierta,
                    )
            else:
                db.query(ReferenciaORM).filter(
                    ReferenciaORM.IdRegistroPersonal == id_registro
                ).delete()

                referencias = [
                    ReferenciaORM(
                        **{
                            **rp.dict(),
                            "IdRegistroPersonal": id_registro,
                        }
                    )
                    for rp in payload.Referencias
                ]
                registro.referencias = referencias

        # ExperienciaLaboral
        if payload.ExperienciaLaboral:
            if id_vinculacion_abierta is not None:
                for el in payload.ExperienciaLaboral:
                    el_data = el.dict()
                    id_exp = el_data.get("IdExperienciaLaboral")

                    if id_exp:
                        id_vinc_exp = _obtener_vinculacion_experiencia(
                            db,
                            id_exp,
                            id_registro,
                        )

                        if id_vinc_exp == id_vinculacion_abierta:
                            exp_obj = (
                                db.query(ExperienciaLaboralORM)
                                .filter(
                                    ExperienciaLaboralORM.IdExperienciaLaboral == id_exp,
                                    ExperienciaLaboralORM.IdRegistroPersonal == id_registro,
                                )
                                .first()
                            )

                            if exp_obj:
                                for key, value in el_data.items():
                                    if key != "IdExperienciaLaboral":
                                        setattr(exp_obj, key, value)
                                continue

                    # Si el ID es histórico, NO se modifica.
                    # Se busca/crea una fila equivalente en el ciclo actual.
                    existente_ciclo = _buscar_experiencia_en_ciclo(
                        db,
                        id_registro,
                        id_vinculacion_abierta,
                        el_data.get("Cargo"),
                        el_data.get("Compania"),
                    )

                    if existente_ciclo:
                        exp_obj = (
                            db.query(ExperienciaLaboralORM)
                            .filter(
                                ExperienciaLaboralORM.IdExperienciaLaboral == existente_ciclo
                            )
                            .first()
                        )

                        if exp_obj:
                            for key, value in el_data.items():
                                if key != "IdExperienciaLaboral":
                                    setattr(exp_obj, key, value)

                        continue

                    el_data.pop("IdExperienciaLaboral", None)

                    nueva_exp = ExperienciaLaboralORM(
                        **{
                            **el_data,
                            "IdRegistroPersonal": id_registro,
                        }
                    )
                    db.add(nueva_exp)
                    db.flush()

                    _asignar_vinculacion(
                        db,
                        "ExperienciaLaboral",
                        nueva_exp.IdExperienciaLaboral,
                        id_vinculacion_abierta,
                    )

            else:
                # Comportamiento actual para personal sin ciclo abierto.
                for el in payload.ExperienciaLaboral:
                    el_data = el.dict()
                    id_exp = el_data.get("IdExperienciaLaboral")

                    if id_exp:
                        exp_obj = (
                            db.query(ExperienciaLaboralORM)
                            .filter(
                                ExperienciaLaboralORM.IdExperienciaLaboral == id_exp,
                                ExperienciaLaboralORM.IdRegistroPersonal == id_registro,
                            )
                            .first()
                        )

                        if exp_obj:
                            for key, value in el_data.items():
                                if key != "IdExperienciaLaboral":
                                    setattr(exp_obj, key, value)
                            continue

                    existe = None

                    if not id_exp:
                        existe = (
                            db.query(ExperienciaLaboralORM)
                            .filter(
                                ExperienciaLaboralORM.IdRegistroPersonal == id_registro,
                                ExperienciaLaboralORM.Cargo == el_data.get("Cargo"),
                                ExperienciaLaboralORM.Compania == el_data.get("Compania"),
                            )
                            .first()
                        )

                    if not existe:
                        new_exp = ExperienciaLaboralORM(
                            **{
                                **el_data,
                                "IdRegistroPersonal": id_registro,
                            }
                        )
                        db.add(new_exp)

        # Documentos de ingreso, categorías 6 y 7
        from domain.models.aspirante import (
            RelacionTipoDocumentacionORM,
            TipoDocumentacion,
        )

        if payload.Documentacion:
            if id_vinculacion_abierta is not None:
                relaciones_ingreso = db.execute(
                    text(
                        '''
                        SELECT
                            rtd."IdRelacion",
                            rtd."IdDocumento"
                        FROM public."RelacionTipoDocumentacion" rtd
                        INNER JOIN public."Documentos" d
                            ON d."IdDocumento" = rtd."IdDocumento"
                        INNER JOIN public."TipoDocumentacion" td
                            ON td."IdTipoDocumentacion" = d."IdTipoDocumentacion"
                        WHERE rtd."IdRegistroPersonal" = :id_registro
                          AND rtd."IdVinculacionLaboral" = :id_vinculacion
                          AND td."IdCategoria" IN (6, 7);
                        '''
                    ),
                    {
                        "id_registro": id_registro,
                        "id_vinculacion": id_vinculacion_abierta,
                    },
                ).mappings().all()

                ids_relaciones = [
                    int(row["IdRelacion"])
                    for row in relaciones_ingreso
                ]
                ids_doc_ingreso = [
                    int(row["IdDocumento"])
                    for row in relaciones_ingreso
                ]

                if ids_relaciones:
                    db.execute(
                        text(
                            '''
                            DELETE FROM public."RelacionTipoDocumentacion"
                            WHERE "IdRelacion" = ANY(:ids_relaciones);
                            '''
                        ),
                        {
                            "ids_relaciones": ids_relaciones,
                        },
                    )

                if ids_doc_ingreso:
                    db.execute(
                        text(
                            '''
                            DELETE FROM public."Documentos"
                            WHERE "IdDocumento" = ANY(:ids_documentos);
                            '''
                        ),
                        {
                            "ids_documentos": ids_doc_ingreso,
                        },
                    )

                for doc in payload.Documentacion:
                    doc_data = doc.dict()

                    if doc_data.get("IdTipoDocumentacion"):
                        tipo_doc = (
                            db.query(TipoDocumentacion)
                            .filter(
                                TipoDocumentacion.IdTipoDocumentacion
                                == doc_data["IdTipoDocumentacion"]
                            )
                            .first()
                        )

                        if tipo_doc and tipo_doc.IdCategoria in [6, 7]:
                            base64_str = doc_data["DocumentoCargado"]

                            try:
                                base64_str = limpiar_base64(base64_str)
                                doc_data["DocumentoCargado"] = base64.b64decode(
                                    base64_str
                                )
                            except Exception as e:
                                print(f"Error al procesar base64: {e}")
                                doc_data["DocumentoCargado"] = None

                            doc_obj = DocumentacionORM(**doc_data)
                            db.add(doc_obj)
                            db.flush()

                            relacion = RelacionTipoDocumentacionORM(
                                IdRegistroPersonal=id_registro,
                                IdDocumento=doc_obj.IdDocumento,
                            )
                            db.add(relacion)
                            db.flush()

                            _asignar_vinculacion(
                                db,
                                "RelacionTipoDocumentacion",
                                relacion.IdRelacion,
                                id_vinculacion_abierta,
                            )

            else:
                # Comportamiento actual para personal sin ciclo abierto.
                relaciones_ingreso = (
                    db.query(RelacionTipoDocumentacionORM)
                    .join(
                        DocumentacionORM,
                        RelacionTipoDocumentacionORM.IdDocumento
                        == DocumentacionORM.IdDocumento,
                    )
                )

                relaciones_ingreso = relaciones_ingreso.join(
                    TipoDocumentacion,
                    DocumentacionORM.IdTipoDocumentacion
                    == TipoDocumentacion.IdTipoDocumentacion,
                )

                relaciones_ingreso = relaciones_ingreso.filter(
                    RelacionTipoDocumentacionORM.IdRegistroPersonal
                    == id_registro,
                    TipoDocumentacion.IdCategoria.in_([6, 7]),
                ).all()

                ids_doc_ingreso = [
                    rel.IdDocumento
                    for rel in relaciones_ingreso
                ]

                if ids_doc_ingreso:
                    db.query(RelacionTipoDocumentacionORM).filter(
                        RelacionTipoDocumentacionORM.IdDocumento.in_(
                            ids_doc_ingreso
                        ),
                        RelacionTipoDocumentacionORM.IdRegistroPersonal
                        == id_registro,
                    ).delete(synchronize_session=False)

                    db.query(DocumentacionORM).filter(
                        DocumentacionORM.IdDocumento.in_(
                            ids_doc_ingreso
                        )
                    ).delete(synchronize_session=False)

                for doc in payload.Documentacion:
                    doc_data = doc.dict()

                    if doc_data.get("IdTipoDocumentacion"):
                        tipo_doc = (
                            db.query(TipoDocumentacion)
                            .filter(
                                TipoDocumentacion.IdTipoDocumentacion
                                == doc_data["IdTipoDocumentacion"]
                            )
                            .first()
                        )

                        if tipo_doc and tipo_doc.IdCategoria in [6, 7]:
                            base64_str = doc_data["DocumentoCargado"]

                            try:
                                base64_str = limpiar_base64(base64_str)
                                doc_data["DocumentoCargado"] = base64.b64decode(
                                    base64_str
                                )
                            except Exception as e:
                                print(f"Error al procesar base64: {e}")
                                doc_data["DocumentoCargado"] = None

                            doc_obj = DocumentacionORM(**doc_data)
                            db.add(doc_obj)
                            db.flush()

                            relacion = RelacionTipoDocumentacionORM(
                                IdRegistroPersonal=id_registro,
                                IdDocumento=doc_obj.IdDocumento,
                            )
                            db.add(relacion)

        # DatosAdicionales se mantiene como información actual.
        if payload.DatosAdicionales:
            db.query(DatosAdicionalesORM).filter(
                DatosAdicionalesORM.IdRegistroPersonal == id_registro
            ).delete()

            datos_adicionales_dict = payload.DatosAdicionales.dict()
            datos_adicionales_dict["IdRegistroPersonal"] = id_registro
            datos_adicionales = DatosAdicionalesORM(**datos_adicionales_dict)
            db.add(datos_adicionales)

        # Cierre del retorno del reintegro hacia Selección.
        #
        # Este cambio se ejecuta únicamente cuando:
        # - el trabajador estaba realmente en estado 35 antes de este guardado;
        # - existe una VinculacionLaboral abierta;
        # - esa vinculación es REINTEGRO / EN_PROCESO.
        #
        # Un aspirante nuevo, un trabajador normal o un retirado sin reintegro
        # no entra en este bloque.
        if es_reintegro_en_proceso:
            usuario_movimiento = (
                getattr(payload, "UsuarioActualizacion", None)
                or getattr(registro, "UsuarioActualizacion", None)
                or "aspirante_reintegro"
            )

            resultado_reactivacion = db.execute(
                text(
                    """
                    UPDATE public."RegistroPersonal"
                    SET
                        "IdEstadoProceso" = 18,
                        "FechaActualizacion" = NOW(),
                        "UsuarioActualizacion" = :usuario
                    WHERE "IdRegistroPersonal" = :id_registro
                      AND "IdEstadoProceso" = 35
                    RETURNING "IdRegistroPersonal";
                    """
                ),
                {
                    "id_registro": id_registro,
                    "usuario": usuario_movimiento,
                },
            ).first()

            if not resultado_reactivacion:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=(
                        "La información del reintegro fue procesada, "
                        "pero el trabajador ya no se encuentra en estado 35."
                    ),
                )

            db.execute(
                text(
                    """
                    INSERT INTO public."HistorialEstadoContratacion"
                    (
                        "IdRegistroPersonal",
                        "EstadoAnterior",
                        "EstadoNuevo",
                        "FechaMovimiento",
                        "UsuarioMovimiento",
                        "OrigenMovimiento",
                        "Modulo"
                    )
                    SELECT
                        :id_registro,
                        35,
                        18,
                        NOW(),
                        :usuario,
                        'REINTEGRO',
                        'SELECCION'
                    WHERE NOT EXISTS
                    (
                        SELECT 1
                        FROM public."HistorialEstadoContratacion"
                        WHERE "IdRegistroPersonal" = :id_registro
                          AND "EstadoAnterior" = 35
                          AND "EstadoNuevo" = 18
                          AND "OrigenMovimiento" = 'REINTEGRO'
                          AND "Modulo" = 'SELECCION'
                    );
                    """
                ),
                {
                    "id_registro": id_registro,
                    "usuario": usuario_movimiento,
                },
            )

        contador_registro_personal(db, id_registro)

        db.commit()
        db.refresh(registro)

        return registro

    except HTTPException:
        db.rollback()
        raise

    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error controlado {str(e)}",
        )


def crear_experiencia_laboral_seleccion(
    db: Session,
    payload: ExperienciaLaboralCreateSeleccionSchema,
) -> ExperienciaLaboralORM:
    try:
        registro = (
            db.query(RegistroPersonal)
            .filter(
                RegistroPersonal.IdRegistroPersonal == payload.IdRegistroPersonal
            )
            .first()
        )

        if not registro:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="RegistroPersonal no encontrado",
            )

        id_vinculacion_abierta = _obtener_id_vinculacion_abierta(
            db,
            payload.IdRegistroPersonal,
        )

        nueva_experiencia = ExperienciaLaboralORM(
            IdRegistroPersonal=payload.IdRegistroPersonal,
            Cargo=payload.Cargo,
            Compania=payload.Compania,
            TiempoDuracion=payload.TiempoDuracion,
            Funciones=payload.Funciones,
            JefeInmediato=payload.JefeInmediato,
            TelefonoJefe=payload.TelefonoJefe,
            TieneExperienciaPrevia=payload.TieneExperienciaPrevia,
        )

        db.add(nueva_experiencia)
        db.flush()

        if id_vinculacion_abierta is not None:
            _asignar_vinculacion(
                db,
                "ExperienciaLaboral",
                nueva_experiencia.IdExperienciaLaboral,
                id_vinculacion_abierta,
            )

        db.commit()
        db.refresh(nueva_experiencia)

        return nueva_experiencia

    except HTTPException:
        db.rollback()
        raise

    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error controlado creando experiencia laboral: {str(e)}",
        )


def eliminar_experiencia_laboral_seleccion(
    db: Session,
    id_experiencia_laboral: int,
) -> dict:
    try:
        experiencia = (
            db.query(ExperienciaLaboralORM)
            .filter(
                ExperienciaLaboralORM.IdExperienciaLaboral
                == id_experiencia_laboral
            )
            .first()
        )

        if not experiencia:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Experiencia laboral no encontrada",
            )

        id_registro_personal = experiencia.IdRegistroPersonal

        id_vinculacion_abierta = _obtener_id_vinculacion_abierta(
            db,
            id_registro_personal,
        )

        if id_vinculacion_abierta is not None:
            id_vinc_experiencia = _obtener_vinculacion_experiencia(
                db,
                id_experiencia_laboral,
                id_registro_personal,
            )

            if id_vinc_experiencia != id_vinculacion_abierta:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=(
                        "No se puede eliminar una experiencia laboral "
                        "perteneciente a una vinculación anterior."
                    ),
                )

        db.query(ExperienciaLaboralValidacion).filter(
            ExperienciaLaboralValidacion.IdExperienciaLaboral
            == id_experiencia_laboral
        ).delete(synchronize_session=False)

        db.query(ExperienciaLaboralORM).filter(
            ExperienciaLaboralORM.IdExperienciaLaboral
            == id_experiencia_laboral
        ).delete(synchronize_session=False)

        db.commit()

        return {
            "message": "Experiencia laboral eliminada correctamente"
        }

    except HTTPException:
        db.rollback()
        raise

    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error controlado eliminando experiencia laboral: {str(e)}",
        )