# app/api/routers/aspirante_routers.py

from datetime import date, datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.orm import Session
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from pydantic import BaseModel  # ✅ para el payload del PUT

from infrastructure.db.deps import get_db
from domain.schemas.aspirante import (
    RegistroPersonalCreate,
    RegistroPersonalOut,
    ExperienciaLaboralCreateSeleccionSchema,
)
from domain.models.aspirante import RegistroPersonal
from application.services.aspirante_service import (
    crear_registro,
    actualizar_registro,
    crear_experiencia_laboral_seleccion,
    eliminar_experiencia_laboral_seleccion,
)
from infrastructure.security.role_guard import require_roles_ids

router = APIRouter()

# ------------------ Roles (IDs de tu BD) ------------------
ROL_ADMIN = 1
ROL_SELECCION = 2
ROL_CONTRATACION = 3
ROL_ASPIRANTE = 4
ROL_SUPER_ADMIN = 5
ROL_TALENTO_HUMANO = 13
ROL_DESARROLLADOR = 15

# =========================================================
#   HELPERS SQL (parche para evitar el ORM cuando hay columnas desfasadas)
# =========================================================
def _exists_registro_personal(db: Session, id_registro: int) -> bool:
    row = db.execute(
        text("""
            SELECT 1
            FROM "RegistroPersonal"
            WHERE "IdRegistroPersonal" = :id
            LIMIT 1
        """),
        {"id": id_registro},
    ).first()
    return row is not None


def _get_registro_personal_by_id(db: Session, id_registro: int):
    row = db.execute(
        text("""
            SELECT *
            FROM "RegistroPersonal"
            WHERE "IdRegistroPersonal" = :id
            LIMIT 1
        """),
        {"id": id_registro},
    ).mappings().first()
    return dict(row) if row else None


def _get_registro_personal_by_documento(db: Session, numero: str):
    row = db.execute(
        text("""
            SELECT *
            FROM "RegistroPersonal"
            WHERE "NumeroIdentificacion" = :num
            LIMIT 1
        """),
        {"num": numero},
    ).mappings().first()
    return dict(row) if row else None


# =========================================================
#   CREAR REGISTRO PERSONAL  (Aspirante)
# =========================================================
@router.post("/registro-personal", status_code=status.HTTP_201_CREATED)
def crear_registro_personal(
    payload: RegistroPersonalCreate,
    db: Session = Depends(get_db),
):
    """
    Crea un nuevo RegistroPersonal en la base de datos.
    - Valida que no exista otro registro con la misma cédula (NumeroIdentificacion).
    """
    try:
        crear_registro(db, payload)
        return [{"mensaje": "Registro creado con exito"}]
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error controlado {str(e)}",
        )


# =========================================================
#   ✅ NUEVO: ACTUALIZAR REGISTRO PERSONAL (incluye IdFondoCesantias)
#   (Selección / TH / Contratación)
# =========================================================
class RegistroPersonalUpdate(BaseModel):
    IdFondoPensiones: Optional[int] = None
    IdFondoCesantias: Optional[int] = None
    PesoKilogramos: Optional[float] = None
    AlturaMetros: Optional[float] = None
    ContactoEmergencia: Optional[str] = None
    TelefonoContactoEmergencia: Optional[str] = None
    UsuarioActualizacion: Optional[str] = None


@router.put("/registro-personal/{id_registro}")
def actualizar_registro_personal(
    id_registro: int,
    payload: RegistroPersonalUpdate,
    db: Session = Depends(get_db),
    current=Depends(require_roles_ids(ROL_SELECCION, ROL_TALENTO_HUMANO, ROL_CONTRATACION)),
):
    """
    Actualiza campos puntuales del RegistroPersonal.
    ✅ Incluye IdFondoCesantias.
    """
    if not _exists_registro_personal(db, id_registro):
        raise HTTPException(status_code=404, detail="Aspirante no encontrado")

    data = payload.model_dump(exclude_unset=True)

    # Si no mandan nada, no hacemos update
    if not data:
        return {"message": "No se recibieron campos para actualizar", "idRegistroPersonal": id_registro}

    # Armamos SET dinámico
    set_parts = []
    params = {"id": id_registro}

    # Campos permitidos
    allowed = {
    "IdFondoPensiones",
    "IdFondoCesantias",
    "PesoKilogramos",
    "AlturaMetros",
    "ContactoEmergencia",
    "TelefonoContactoEmergencia",
    "UsuarioActualizacion",
}

    for k, v in data.items():
        if k in allowed:
            set_parts.append(f"\"{k}\" = :{k}")
            params[k] = v

    # Siempre actualizamos FechaActualizacion
    ahora = datetime.utcnow()
    set_parts.append("\"FechaActualizacion\" = :FechaActualizacion")
    params["FechaActualizacion"] = ahora

    if not set_parts:
        return {"message": "No hay campos válidos para actualizar", "idRegistroPersonal": id_registro}

    sql = f"""
        UPDATE "RegistroPersonal"
        SET {", ".join(set_parts)}
        WHERE "IdRegistroPersonal" = :id
    """

    try:
        db.execute(text(sql), params)
        db.commit()
    except SQLAlchemyError as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Error al actualizar RegistroPersonal: {str(e)}")

    return {"message": "Registro actualizado correctamente", "idRegistroPersonal": id_registro}


# =========================================================
#   LISTAR ASPIRANTES
# =========================================================
@router.get("/aspirantes")
def listar_aspirantes(
    db: Session = Depends(get_db),
    fecha_desde: Optional[date] = Query(None),
    fecha_hasta: Optional[date] = Query(None),
    id_estado: Optional[int] = Query(None),
    search: Optional[str] = Query(None),
    current=Depends(
        require_roles_ids(ROL_SELECCION, ROL_TALENTO_HUMANO, ROL_CONTRATACION)
    ),
):
    try:
        sql = """
            SELECT      rp."IdRegistroPersonal", 
		    rp."IdTipoIdentificacion", 
			rp."IdTipoCargo", 
			rp."IdTipoEps", 
			rp."IdTipoEstadoCivil", 
			rp."IdTipoGenero", 
			rp."IdEstadoProceso", 
			rp."NumeroIdentificacion", 
			rp."FechaExpedicion", 
			rp."LugarExpedicion", 
			rp."Nombres", 
			rp."Apellidos", 
			rp."IdCargo", 
			rp."Email", 
			rp."Celular", 
			rp."TieneWhatsapp", 
			rp."NumeroWhatsapp", 
			rp."PesoKilogramos", 
			rp."AlturaMetros", 
			rp."NombreContactoEmergencia", 
			rp."ContactoEmergencia", 
			rp."FechaCreacion", 
			rp."FechaActualizacion", 
			rp."UsuarioActualizacion", 
			rp."FechaNacimiento", 
			rp."IdFondoPensiones", 
			rp."IdLimitacionFisicaHijo", 
			rp."IdNivelEducativo", 
			rp."TieneHijos", 
			rp."CuantosHijos", 
			rp."TelefonoContactoEmergencia", 
			rp."EstudiaActualmente", 
			rp."IdTipoEstadoFormacion", 
			rp."ComoSeEnteroVacante", 
			rp."IdLugarNacimiento", 
			rp."TieneLimitacionesFisicas", 
			rp."DescripcionFormacionAcademica", 
			rp."IdLimitacionFisica", 
			rp."IdFondoCesantias", 
			esp."Nombre" AS "EstadoProceso", 
			DA."Direccion", 
			L."Nombre" AS "Ciudad",
			DA."Barrio", 
			CARG."NombreCargo", 
			ASCARGO."Salario", 
			CB."FechaIngreso",
			CL."Nombre" AS "NombreCliente", 
			rp."FechaNacimiento"
            FROM "RegistroPersonal" rp
            LEFT JOIN "EstadoProceso" esp ON rp."IdEstadoProceso" = esp."IdEstadoProceso"
			JOIN "DatosAdicionales" DA ON DA."IdRegistroPersonal" = rp."IdRegistroPersonal"
			JOIN "Localidad" L ON L."IdLocalidad" = DA."IdLocalidad"
			LEFT JOIN "AsignacionCargoCliente" ASCARGO ON ASCARGO."IdRegistroPersonal" = rp."IdRegistroPersonal"
			LEFT JOIN "Cargo" CARG ON CARG."IdCargo" =  ASCARGO."IdCargo"
			LEFT JOIN "ContratacionBasica" CB ON CB."IdRegistroPersonal" = rp."IdRegistroPersonal"
			LEFT JOIN "Cliente" CL ON CL."IdCliente" = ASCARGO."IdCliente"
            WHERE 1=1
        """

        params = {}

        if fecha_desde:
            sql += ' AND rp."FechaCreacion"::date >= :fecha_desde'
            params["fecha_desde"] = fecha_desde

        if fecha_hasta:
            sql += ' AND rp."FechaCreacion"::date <= :fecha_hasta'
            params["fecha_hasta"] = fecha_hasta

        if id_estado:
            sql += ' AND rp."IdEstadoProceso" = :id_estado'
            params["id_estado"] = id_estado

        if search:
            s = search.strip()
            sql += """
                AND (
                    upper(rp."Nombres") LIKE :pattern
                    OR upper(rp."Apellidos") LIKE :pattern
                    OR rp."NumeroIdentificacion" ILIKE :docpattern
                )
            """
            params["pattern"] = f"%{s.upper()}%"
            params["docpattern"] = f"%{s}%"

        sql += """
         GROUP BY
			rp."IdRegistroPersonal", 
			rp."IdTipoIdentificacion", 
			rp."IdTipoCargo", rp."IdTipoEps", 
			rp."IdTipoEstadoCivil", 
			rp."IdTipoGenero", 
			rp."IdEstadoProceso", 
			rp."NumeroIdentificacion", 
			rp."FechaExpedicion", 
			rp."LugarExpedicion", 
			rp."Nombres", 
			rp."Apellidos", 
			rp."IdCargo", 
			rp."Email", 
			rp."Celular", 
			rp."TieneWhatsapp", 
			rp."NumeroWhatsapp", 
			rp."PesoKilogramos", 
			rp."AlturaMetros", 
			rp."NombreContactoEmergencia", 
			rp."ContactoEmergencia", 
			rp."FechaCreacion", 
			rp."FechaActualizacion", 
			rp."UsuarioActualizacion", 
			rp."FechaNacimiento", 
			rp."IdFondoPensiones", 
			rp."IdLimitacionFisicaHijo", 
			rp."IdNivelEducativo", 
			rp."TieneHijos", 
			rp."CuantosHijos", 
			rp."TelefonoContactoEmergencia", 
			rp."EstudiaActualmente", 
			rp."IdTipoEstadoFormacion", 
			rp."ComoSeEnteroVacante", 
			rp."IdLugarNacimiento", 
			rp."TieneLimitacionesFisicas", 
			rp."DescripcionFormacionAcademica", 
			rp."IdLimitacionFisica", 
			rp."IdFondoCesantias",
			esp."Nombre",
			DA."Direccion",
			L."Nombre",
			DA."Barrio", 
			CARG."NombreCargo", 
			ASCARGO."Salario", 
			CB."FechaIngreso",
			CL."Nombre", 
			rp."FechaNacimiento"
        """

        sql += """
        ORDER BY rp."FechaCreacion" DESC
        """

        rows = db.execute(text(sql), params).mappings().all()
        return rows

    except SQLAlchemyError as e:
        raise HTTPException(
            status_code=500,
            detail=f"Error al listar aspirantes con detalles: {str(e)}"
        )


# =========================================================
#   BUSQUEDA POR FECHA + ESTADO
# =========================================================
@router.get("/aspirantes/busqueda", response_model=list[RegistroPersonalOut])
def buscar_aspirantes_por_fecha_y_estado(
    fecha: date = Query(...),
    estado: int = Query(...),
    db: Session = Depends(get_db),
    current=Depends(require_roles_ids(ROL_SELECCION, ROL_TALENTO_HUMANO, ROL_CONTRATACION)),
):
    try:
        inicio = datetime.combine(fecha, datetime.min.time())
        fin = inicio + timedelta(days=1)

        rows = db.execute(
            text("""
                SELECT *
                FROM "RegistroPersonal"
                WHERE "IdEstadoProceso" = :estado
                AND "FechaCreacion" >= :inicio
                AND "FechaCreacion" <  :fin
                ORDER BY "FechaCreacion" DESC
            """),
            {"estado": estado, "inicio": inicio, "fin": fin},
        ).mappings().all()

        return [dict(r) for r in rows]

    except SQLAlchemyError as e:
        raise HTTPException(status_code=500, detail=f"Error en busqueda: {str(e)}")


# =========================================================
#   OBTENER ASPIRANTE POR DOCUMENTO
# =========================================================
@router.get("/aspirantes/documento")
def obtener_registro_personal(
    id: str,
    db: Session = Depends(get_db)
):
    referencias = db.query(RegistroPersonal).filter(RegistroPersonal.NumeroIdentificacion == id).all()
    if not referencias:
        raise HTTPException(status_code=404, detail="No se encontraron registros de aspirante para ese ID")
    return referencias


# =========================================================
#   OBTENER ASPIRANTE POR ID
# =========================================================
@router.get("/aspirantes/{id_registro}", response_model=RegistroPersonalOut)
def obtener_aspirante(
    id_registro: int,
    db: Session = Depends(get_db),
    current=Depends(require_roles_ids(ROL_SELECCION, ROL_TALENTO_HUMANO, ROL_CONTRATACION)),
):
    aspirante = _get_registro_personal_by_id(db, id_registro)

    if not aspirante:
        raise HTTPException(status_code=404, detail="Aspirante no encontrado")

    return aspirante


# =========================================================
#   UPDATE ESTADO
# =========================================================
@router.put("/aspirantes/{id_registro}/estado")
def actualizar_estado_aspirante(
    id_registro: int,
    nuevo_estado: int = Query(...),
    usuario: str = Query(...),
    db: Session = Depends(get_db),
    current=Depends(require_roles_ids(ROL_SELECCION, ROL_TALENTO_HUMANO, ROL_CONTRATACION)),
):
    if not _exists_registro_personal(db, id_registro):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Aspirante no encontrado",
        )

    ahora = datetime.utcnow()

    try:
        db.execute(
            text("""
                UPDATE "RegistroPersonal"
                SET "IdEstadoProceso" = :nuevo_estado,
                    "FechaActualizacion" = :fecha,
                    "UsuarioActualizacion" = :usuario
                WHERE "IdRegistroPersonal" = :id
            """),
            {
                "nuevo_estado": nuevo_estado,
                "fecha": ahora,
                "usuario": usuario,
                "id": id_registro,
            },
        )
        db.commit()

    except SQLAlchemyError as e:
        db.rollback()
        raise HTTPException(
            status_code=500,
            detail=f"Error al actualizar el estado: {str(e)}",
        )

    return {
        "message": "Estado actualizado correctamente",
        "idRegistroPersonal": id_registro,
        "nuevoEstado": nuevo_estado,
        "usuario": usuario,
    }


@router.get("/aspirante_detalle/{id}")
def obtener_registro_personal(
    id: int,
    db: Session = Depends(get_db),
    current=Depends(require_roles_ids(ROL_SELECCION)),
):
    referencias = db.query(RegistroPersonal).filter(RegistroPersonal.IdRegistroPersonal == id).all()
    if not referencias:
        raise HTTPException(status_code=404, detail="No se encontraron registros de aspirante para ese ID")
    return referencias


# =========================================================
#   PUT /registro-personal/full/{id_registro}
# =========================================================
@router.put("/registro-personal/full/{id_registro}", response_model=RegistroPersonalOut)
def actualizar_registro_personal_full(
    id_registro: int,
    payload: RegistroPersonalCreate,
    db: Session = Depends(get_db)
):
    """
    Actualiza completamente un RegistroPersonal y sus relaciones asociadas.
    """
    try:
        config_row = db.execute(
            text('SELECT "Valor" FROM "Configuracion" WHERE "Nombre" = :nombre LIMIT 1'),
            {"nombre": "RegistrosActualzacionesPermitidos"}
        ).first()
        if not config_row:
            raise HTTPException(status_code=500, detail="No se encontró configuración para RegistrosActualizacionesPermitidos")
        valor_config = int(config_row[0])

        print('id_registro', id_registro)
        contador_row = db.execute(
            text('SELECT "Contador" FROM "ContadorRegistroPersonal" WHERE "IdRegistroPersonal" = :id LIMIT 1'),
            {"id": id_registro}
        ).first()
        if not contador_row:
            raise HTTPException(status_code=400, detail="No se encontró contador para el registro personal")
        contador_actual = int(contador_row[0])

        if valor_config <= contador_actual:
            raise HTTPException(
                status_code=400,
                detail="No es posible actualizar el registro ya que alcanzó el límite permitido para actualizar. Para más información, contactar con el área de Talento Humano."
            )

        registro = actualizar_registro(db, id_registro, payload)
        return registro
    except HTTPException as e:
        raise e
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error controlado {str(e)}",
        )


# =========================================================
#   CREAR EXPERIENCIA LABORAL (SELECCIÓN)
# =========================================================
@router.post("/experiencia-laboral")
def crear_experiencia_laboral_seleccion_endpoint(
    payload: ExperienciaLaboralCreateSeleccionSchema,
    db: Session = Depends(get_db),
):
    return crear_experiencia_laboral_seleccion(db, payload)


# =========================================================
#   ELIMINAR EXPERIENCIA LABORAL (SELECCIÓN)
# =========================================================
@router.delete("/experiencia-laboral/{id_experiencia_laboral}")
def eliminar_experiencia_laboral_endpoint(
    id_experiencia_laboral: int,
    db: Session = Depends(get_db),
):
    return eliminar_experiencia_laboral_seleccion(
        db,
        id_experiencia_laboral
    )