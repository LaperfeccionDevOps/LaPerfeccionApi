from fastapi import HTTPException, status
from sqlalchemy.orm import Session
from domain.models.aspirante import (
    RegistroPersonal,
    NucleoFamiliarORM,
    ReferenciaORM,
    ExperienciaLaboralORM,
    DocumentacionORM,
    DatosAdicionalesORM,
)
from domain.schemas.aspirante import (
    RegistroPersonalCreate,
    ExperienciaLaboralCreateSeleccionSchema,
)
from infrastructure.repositories.aspirante_repo import create
import base64
import re
from repositories.contador_registro_personal_repo import contador_registro_personal


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

        # ✅ EXTRA SEGURO: aseguramos que el campo nuevo quede asignado
        # (no daña nada si ya venía en el dict; solo garantiza que se guarde)
        if hasattr(payload, "IdFondoCesantias"):
            nuevo.IdFondoCesantias = payload.IdFondoCesantias

        db.add(nuevo)
        db.flush()

        nucleo_familiar = [
            NucleoFamiliarORM(**{**nf.dict(), "IdRegistroPersonal": nuevo.IdRegistroPersonal})
            for nf in payload.NucleoFamiliar
        ]
        nuevo.nucleo_familiar = nucleo_familiar

        referencias = [
            ReferenciaORM(**{**rp.dict(), "IdRegistroPersonal": nuevo.IdRegistroPersonal})
            for rp in payload.Referencias
        ]
        nuevo.referencias = referencias

        experiencia_laboral = [
            ExperienciaLaboralORM(**{**el.dict(), "IdRegistroPersonal": nuevo.IdRegistroPersonal})
            for el in payload.ExperienciaLaboral
        ]
        nuevo.experiencia_laboral = experiencia_laboral

        from domain.models.aspirante import RelacionTipoDocumentacionORM

        documentacion_objs = []
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
            documentacion_objs.append(doc_obj)

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
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error controlado {str(e)}",
        )


def limpiar_base64(base64_str: str) -> str:
    """
    Elimina el prefijo data:*;base64, si existe. Acepta bytes o string.
    """
    if isinstance(base64_str, bytes):
        base64_str = base64_str.decode("utf-8")
    match = re.match(r"^data:.*?;base64,(.*)", base64_str)
    if match:
        return match.group(1)
    return base64_str


def actualizar_registro(db: Session, id_registro: int, payload: RegistroPersonalCreate) -> None:
    try:
        registro = db.query(RegistroPersonal).filter(RegistroPersonal.IdRegistroPersonal == id_registro).first()
        if not registro:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="RegistroPersonal no encontrado",
            )

        # Actualizar campos simples
        for key, value in payload.dict(exclude={
            "NucleoFamiliar",
            "Referencias",
            "ExperienciaLaboral",
            "Documentacion",
            "DatosAdicionales",
        }).items():
            setattr(registro, key, value)

        if hasattr(payload, "IdFondoCesantias"):
            registro.IdFondoCesantias = payload.IdFondoCesantias

        # Actualizar NucleoFamiliar
        if payload.NucleoFamiliar:
            db.query(NucleoFamiliarORM).filter(NucleoFamiliarORM.IdRegistroPersonal == id_registro).delete()
            nucleo_familiar = [
                NucleoFamiliarORM(**{**nf.dict(), "IdRegistroPersonal": id_registro})
                for nf in payload.NucleoFamiliar
            ]
            registro.nucleo_familiar = nucleo_familiar

        # Actualizar Referencias
        if payload.Referencias:
            db.query(ReferenciaORM).filter(ReferenciaORM.IdRegistroPersonal == id_registro).delete()
            referencias = [
                ReferenciaORM(**{**rp.dict(), "IdRegistroPersonal": id_registro})
                for rp in payload.Referencias
            ]
            registro.referencias = referencias

        # Actualizar ExperienciaLaboral (NO eliminar, solo agregar o actualizar, sin duplicar)
        if payload.ExperienciaLaboral:
            for el in payload.ExperienciaLaboral:
                el_data = el.dict()
                id_exp = el_data.get("IdExperienciaLaboral")
                if id_exp:
                    exp_obj = db.query(ExperienciaLaboralORM).filter(
                        ExperienciaLaboralORM.IdExperienciaLaboral == id_exp,
                        ExperienciaLaboralORM.IdRegistroPersonal == id_registro
                    ).first()
                    if exp_obj:
                        for key, value in el_data.items():
                            if key != "IdExperienciaLaboral":
                                setattr(exp_obj, key, value)
                        continue  # Ya actualizado, no crear nuevo

                # Si no existe (o no tiene IdExperienciaLaboral), verificar si ya existe uno igual
                existe = None
                if not id_exp:
                    existe = db.query(ExperienciaLaboralORM).filter(
                        ExperienciaLaboralORM.IdRegistroPersonal == id_registro,
                        ExperienciaLaboralORM.Cargo == el_data.get("Cargo"),
                        ExperienciaLaboralORM.Compania == el_data.get("Compania")
                    ).first()

                if not existe:
                    new_exp = ExperienciaLaboralORM(**{**el_data, "IdRegistroPersonal": id_registro})
                    db.add(new_exp)

        # Actualizar Documentacion SOLO documentos de ingreso (IdCategoria == 6)
        from domain.models.aspirante import RelacionTipoDocumentacionORM, TipoDocumentacion
        if payload.Documentacion:
            # Buscar relaciones de documentos de ingreso
            relaciones_ingreso = db.query(RelacionTipoDocumentacionORM).join(
                DocumentacionORM,
                RelacionTipoDocumentacionORM.IdDocumento == DocumentacionORM.IdDocumento
            )
            relaciones_ingreso = relaciones_ingreso.join(
                TipoDocumentacion,
                DocumentacionORM.IdTipoDocumentacion == TipoDocumentacion.IdTipoDocumentacion
            )
            relaciones_ingreso = relaciones_ingreso.filter(
                RelacionTipoDocumentacionORM.IdRegistroPersonal == id_registro,
                TipoDocumentacion.IdCategoria == 6
            ).all()

            # Eliminar relaciones y documentos de ingreso
            ids_doc_ingreso = [rel.IdDocumento for rel in relaciones_ingreso]
            if ids_doc_ingreso:
                db.query(RelacionTipoDocumentacionORM).filter(
                    RelacionTipoDocumentacionORM.IdDocumento.in_(ids_doc_ingreso),
                    RelacionTipoDocumentacionORM.IdRegistroPersonal == id_registro
                ).delete(synchronize_session=False)

                db.query(DocumentacionORM).filter(
                    DocumentacionORM.IdDocumento.in_(ids_doc_ingreso)
                ).delete(synchronize_session=False)

            # Agregar nuevos documentos de ingreso
            documentacion_objs = []
            for doc in payload.Documentacion:
                doc_data = doc.dict()

                # Solo agregar si es de ingreso
                if doc_data.get("IdTipoDocumentacion"):
                    tipo_doc = db.query(TipoDocumentacion).filter(
                        TipoDocumentacion.IdTipoDocumentacion == doc_data["IdTipoDocumentacion"]
                    ).first()

                    if tipo_doc and tipo_doc.IdCategoria == 6:
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
                            IdRegistroPersonal=id_registro,
                            IdDocumento=doc_obj.IdDocumento,
                        )
                        db.add(relacion)
                        documentacion_objs.append(doc_obj)

        # Actualizar DatosAdicionales
        if payload.DatosAdicionales:
            db.query(DatosAdicionalesORM).filter(
                DatosAdicionalesORM.IdRegistroPersonal == id_registro
            ).delete()

            datos_adicionales_dict = payload.DatosAdicionales.dict()
            datos_adicionales_dict["IdRegistroPersonal"] = id_registro
            datos_adicionales = DatosAdicionalesORM(**datos_adicionales_dict)
            db.add(datos_adicionales)

        contador_registro_personal(db, id_registro)
        db.commit()
        db.refresh(registro)
        return registro

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error controlado {str(e)}",
        )


def crear_experiencia_laboral_seleccion(
    db: Session,
    payload: ExperienciaLaboralCreateSeleccionSchema
) -> ExperienciaLaboralORM:
    try:
        registro = db.query(RegistroPersonal).filter(
            RegistroPersonal.IdRegistroPersonal == payload.IdRegistroPersonal
        ).first()

        if not registro:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="RegistroPersonal no encontrado",
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
        db.commit()
        db.refresh(nueva_experiencia)

        return nueva_experiencia

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error controlado creando experiencia laboral: {str(e)}",
        )