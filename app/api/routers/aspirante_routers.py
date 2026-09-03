# ruff: noqa: B008, BLE001, DTZ003
# app/api/routers/aspirante_routers.py
# ruff: noqa

from datetime import date, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from application.services.aspirante_service import (
    actualizar_registro,
    crear_experiencia_laboral_seleccion,
    crear_registro,
    eliminar_experiencia_laboral_seleccion,
)
from domain.models.aspirante import RegistroPersonal
from domain.schemas.aspirante import (
    ExperienciaLaboralCreateSeleccionSchema,
    RegistroPersonalCreate,
    RegistroPersonalOut,
)
from infrastructure.db.deps import get_db
from infrastructure.security.auth_dependencies import get_current_user
from infrastructure.security.role_guard import require_roles_ids

router = APIRouter()

# ------------------ Roles ------------------
ROL_ADMIN = 1
ROL_SELECCION = 2
ROL_CONTRATACION = 3
ROL_ASPIRANTE = 4
ROL_SUPER_ADMIN = 5
ROL_OPERACIONES = 6
ROL_HSE = 10
ROL_BIENESTAR = 16
ROL_TALENTO_HUMANO = 13
ROL_DESARROLLADOR = 15
ROL_NOMINA = 17

PERMISO_OPERACIONES_PROCESOS_DISCIPLINARIOS = "OPERACIONES_PROCESOS_DISCIPLINARIOS"
PERMISO_OPERACIONES_RETIROS = "OPERACIONES_RETIROS"

ROLES_CONSULTA_ASPIRANTES = {
    ROL_SUPER_ADMIN,
    ROL_SELECCION,
    ROL_TALENTO_HUMANO,
    ROL_CONTRATACION,
    ROL_OPERACIONES,
    ROL_HSE,
    ROL_BIENESTAR,
    ROL_NOMINA,
}


def require_consulta_aspirantes_operaciones(
    current=Depends(get_current_user),
):
    roles_ids = {
        int(rol_id)
        for rol_id in (current.get("roles_ids") or [])
        if str(rol_id).isdigit()
    }
    permisos = {
        str(permiso).strip().upper()
        for permiso in (current.get("permisos") or [])
        if permiso
    }

    tiene_rol = bool(roles_ids & ROLES_CONSULTA_ASPIRANTES)
    tiene_permiso_operaciones = bool(
        permisos
        & {
            PERMISO_OPERACIONES_PROCESOS_DISCIPLINARIOS,
            PERMISO_OPERACIONES_RETIROS,
        }
    )

    if not tiene_rol and not tiene_permiso_operaciones:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No tienes permisos para este recurso",
        )

    return current


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


@router.post("/registro-personal", status_code=status.HTTP_201_CREATED)
def crear_registro_personal(
    payload: RegistroPersonalCreate,
    db: Session = Depends(get_db),
):
    try:
        crear_registro(db, payload)
        return [{"mensaje": "Registro creado con exito"}]
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error controlado {e!s}",
        )


class RegistroPersonalUpdate(BaseModel):
    IdFondoPensiones: int | None = None
    IdFondoCesantias: int | None = None
    PesoKilogramos: float | None = None
    AlturaMetros: float | None = None
    ContactoEmergencia: str | None = None
    TelefonoContactoEmergencia: str | None = None
    UsuarioActualizacion: str | None = None


@router.put("/registro-personal/{id_registro}")
def actualizar_registro_personal(
    id_registro: int,
    payload: RegistroPersonalUpdate,
    db: Session = Depends(get_db),
    current=Depends(require_roles_ids(ROL_SELECCION, ROL_TALENTO_HUMANO, ROL_CONTRATACION)),
):
    if not _exists_registro_personal(db, id_registro):
        raise HTTPException(status_code=404, detail="Aspirante no encontrado")

    data = payload.model_dump(exclude_unset=True)

    if not data:
        return {"message": "No se recibieron campos para actualizar", "idRegistroPersonal": id_registro}

    set_parts = []
    params = {"id": id_registro}

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
        raise HTTPException(status_code=500, detail=f"Error al actualizar RegistroPersonal: {e!s}")

    return {"message": "Registro actualizado correctamente", "idRegistroPersonal": id_registro}


@router.get("/aspirantes")
def listar_aspirantes(
    db: Session = Depends(get_db),
    fecha_desde: date | None = Query(None),
    fecha_hasta: date | None = Query(None),
    id_estado: int | None = Query(None),
    search: str | None = Query(None),
    current=Depends(require_consulta_aspirantes_operaciones),
):
    try:
        sql = """
            SELECT
                rp."IdRegistroPersonal",
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
                COALESCE(
                CB."FechaIngreso",
                rp."FechaIngresoHistorica"
            ) AS "FechaIngreso",
                CL."Nombre" AS "NombreCliente",
                CASE
                    WHEN rp."IdEstadoProceso" = 25 THEN TRUE
                    WHEN rp."FechaIngresoHistorica" IS NOT NULL THEN TRUE
                    WHEN EXISTS (
                        SELECT 1
                        FROM "ContratacionBasica" CB_HIST
                        WHERE CB_HIST."IdRegistroPersonal" = rp."IdRegistroPersonal"
                    ) THEN TRUE
                    WHEN EXISTS (
                        SELECT 1
                        FROM "RetiroLaboral" RL_HIST
                        WHERE RL_HIST."IdRegistroPersonal" = rp."IdRegistroPersonal"
                    ) THEN TRUE
                    ELSE FALSE
                END AS "TuvoContratacion"
            FROM "RegistroPersonal" rp
            LEFT JOIN "EstadoProceso" esp ON rp."IdEstadoProceso" = esp."IdEstadoProceso"
            LEFT JOIN "DatosAdicionales" DA ON DA."IdRegistroPersonal" = rp."IdRegistroPersonal"
            LEFT JOIN "Localidad" L ON L."IdLocalidad" = DA."IdLocalidad"
            LEFT JOIN "AsignacionCargoCliente" ASCARGO ON ASCARGO."IdRegistroPersonal" = rp."IdRegistroPersonal"
            LEFT JOIN "Cargo" CARG ON CARG."IdCargo" = ASCARGO."IdCargo"
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

            terminos = [
                termino
                for termino in s.split()
                if termino.strip()
            ]

            for indice, termino in enumerate(terminos):
                parametro_nombre = f"search_nombre_{indice}"
                parametro_documento = f"search_documento_{indice}"

                sql += f"""
                    AND (
                        upper(
                            concat_ws(
                                ' ',
                                COALESCE(rp."Nombres", ''),
                                COALESCE(rp."Apellidos", '')
                            )
                        ) LIKE :{parametro_nombre}
                        OR COALESCE(
                            rp."NumeroIdentificacion",
                            ''
                        ) ILIKE :{parametro_documento}
                    )
                """

                params[parametro_nombre] = (
                    f"%{termino.upper()}%"
                )
                params[parametro_documento] = (
                    f"%{termino}%"
                )

        sql += """
            GROUP BY
                rp."IdRegistroPersonal",
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
                esp."Nombre",
                DA."Direccion",
                L."Nombre",
                DA."Barrio",
                CARG."NombreCargo",
                ASCARGO."Salario",
                CB."FechaIngreso",
                rp."FechaIngresoHistorica",
                CL."Nombre"
            ORDER BY rp."FechaCreacion" DESC
        """

        rows = db.execute(text(sql), params).mappings().all()
        return rows

    except SQLAlchemyError as e:
        raise HTTPException(
            status_code=500,
            detail=f"Error al listar aspirantes con detalles: {e!s}"
        )


@router.get("/aspirantes/busqueda", response_model=list[RegistroPersonalOut])
def buscar_aspirantes_por_fecha_y_estado(
    fecha: date = Query(...),
    estado: int = Query(...),
    db: Session = Depends(get_db),
    current=Depends(
        require_roles_ids(
        ROL_SELECCION,
        ROL_TALENTO_HUMANO,
        ROL_CONTRATACION,
        ROL_OPERACIONES,
        ROL_NOMINA,
    )
    ),
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
                AND "FechaCreacion" < :fin
                ORDER BY "FechaCreacion" DESC
            """),
            {"estado": estado, "inicio": inicio, "fin": fin},
        ).mappings().all()

        return [dict(r) for r in rows]

    except SQLAlchemyError as e:
        raise HTTPException(status_code=500, detail=f"Error en busqueda: {e!s}")


@router.get("/aspirantes/documento")
def obtener_registro_personal(
    id: str,
    db: Session = Depends(get_db)
):
    referencias = db.query(RegistroPersonal).filter(RegistroPersonal.NumeroIdentificacion == id).all()
    if not referencias:
        raise HTTPException(status_code=404, detail="No se encontraron registros de aspirante para ese ID")
    return referencias


@router.get("/aspirantes/{id_registro}", response_model=RegistroPersonalOut)
def obtener_aspirante(
    id_registro: int,
    db: Session = Depends(get_db),
    current=Depends(require_consulta_aspirantes_operaciones),
):
    aspirante = _get_registro_personal_by_id(db, id_registro)

    if not aspirante:
        raise HTTPException(status_code=404, detail="Aspirante no encontrado")

    return aspirante


@router.put("/aspirantes/{id_registro}/estado")
def actualizar_estado_aspirante(
    id_registro: int,
    nuevo_estado: int = Query(...),
    usuario: str = Query(...),
    db: Session = Depends(get_db),
    current=Depends(require_roles_ids(ROL_SELECCION, ROL_TALENTO_HUMANO, ROL_CONTRATACION)),
):
    """
    Actualiza el estado general del aspirante.

    Cuando el aspirante entra por primera vez al estado 24
    (Avanza a Contratación), registra el movimiento en
    HistorialEstadoContratacion dentro de la misma transacción.

    No altera los demás cambios de estado ni registra duplicados
    cuando el registro ya se encuentra en estado 24.
    """

    usuario_movimiento = (usuario or "sistema").strip() or "sistema"
    ahora = datetime.utcnow()

    try:
        # Bloquea el registro durante la transacción y obtiene
        # el estado real anterior antes de realizar el cambio.
        registro_actual = db.execute(
            text("""
                SELECT "IdEstadoProceso"
                FROM "RegistroPersonal"
                WHERE "IdRegistroPersonal" = :id
                FOR UPDATE
            """),
            {"id": id_registro},
        ).mappings().first()

        if not registro_actual:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Aspirante no encontrado",
            )

        estado_anterior = registro_actual.get("IdEstadoProceso")

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
                "usuario": usuario_movimiento,
                "id": id_registro,
            },
        )

        historial_registrado = False

        # Registra únicamente el ingreso real al estado 24.
        # Si ya estaba en 24 y vuelven a guardar el mismo estado,
        # no genera una fila duplicada.
        if nuevo_estado == 24 and estado_anterior != 24:
            db.execute(
                text("""
                    INSERT INTO public."HistorialEstadoContratacion"
                    (
                        "IdRegistroPersonal",
                        "EstadoAnterior",
                        "EstadoNuevo",
                        "FechaMovimiento",
                        "UsuarioMovimiento"
                    )
                    VALUES
                    (
                        :id_registro,
                        :estado_anterior,
                        :estado_nuevo,
                        NOW(),
                        :usuario
                    )
                """),
                {
                    "id_registro": id_registro,
                    "estado_anterior": estado_anterior,
                    "estado_nuevo": nuevo_estado,
                    "usuario": usuario_movimiento,
                },
            )
            historial_registrado = True

        db.commit()

    except HTTPException:
        db.rollback()
        raise
    except SQLAlchemyError as e:
        db.rollback()
        raise HTTPException(
            status_code=500,
            detail=f"Error al actualizar el estado: {e!s}",
        )

    return {
        "message": "Estado actualizado correctamente",
        "idRegistroPersonal": id_registro,
        "estadoAnterior": estado_anterior,
        "nuevoEstado": nuevo_estado,
        "usuario": usuario_movimiento,
        "historialContratacionRegistrado": historial_registrado,
    }


@router.get("/aspirante_detalle/{id}")
def obtener_registro_personal(
    id: int,
    db: Session = Depends(get_db),
    current=Depends(require_roles_ids(ROL_SELECCION)),
):
    """
    Endpoint legado del detalle de Selección.

    Se conserva exactamente con la forma de respuesta actual para no romper
    AspiranteDetailModal ni otros consumidores existentes. La separación por
    ciclos se expone en /aspirante_detalle/{id}/ciclos.
    """
    referencias = (
        db.query(RegistroPersonal)
        .filter(RegistroPersonal.IdRegistroPersonal == id)
        .all()
    )

    if not referencias:
        raise HTTPException(
            status_code=404,
            detail="No se encontraron registros de aspirante para ese ID",
        )

    return referencias


@router.get("/aspirante_detalle/{id}/ciclos")
def obtener_detalle_aspirante_por_ciclos(
    id: int,
    db: Session = Depends(get_db),
    current=Depends(
        require_roles_ids(
            ROL_SUPER_ADMIN,
            ROL_SELECCION,
            ROL_TALENTO_HUMANO,
            ROL_CONTRATACION,
            ROL_DESARROLLADOR,
        )
    ),
):
    """
    Consulta de apoyo para Selección que separa la información laboral
    dependiente de VinculacionLaboral.

    IMPORTANTE:
    - Solo consulta; no inserta, no actualiza y no elimina.
    - No reemplaza el endpoint legado /aspirante_detalle/{id}.
    - No toca Documentos, DatosSeleccion ni Entrevista en esta fase.
    - Conserva registros legacy cuyo IdVinculacionLaboral es NULL dentro
      del histórico, para no perder información anterior a la separación
      por ciclos.
    """

    persona = db.execute(
        text(
            """
            SELECT
                rp."IdRegistroPersonal",
                rp."NumeroIdentificacion",
                rp."Nombres",
                rp."Apellidos",
                rp."IdEstadoProceso",
                rp."FechaCreacion",
                rp."FechaActualizacion",
                rp."UsuarioActualizacion"
            FROM public."RegistroPersonal" rp
            WHERE rp."IdRegistroPersonal" = :id
            LIMIT 1;
            """
        ),
        {"id": id},
    ).mappings().first()

    if not persona:
        raise HTTPException(
            status_code=404,
            detail="No se encontraron registros de aspirante para ese ID",
        )

    vinculaciones = db.execute(
        text(
            """
            SELECT
                vl."IdVinculacionLaboral",
                vl."IdRegistroPersonal",
                vl."NumeroCiclo",
                vl."TipoVinculacion",
                vl."EstadoVinculacion",
                vl."FechaInicioProceso",
                vl."FechaIngreso",
                vl."FechaRetiro",
                vl."IdCargo",
                vl."IdCliente",
                vl."Salario",
                vl."IdTipoContrato",
                vl."FechaCreacion",
                vl."FechaActualizacion",
                vl."UsuarioActualizacion"
            FROM public."VinculacionLaboral" vl
            WHERE vl."IdRegistroPersonal" = :id
            ORDER BY
                vl."NumeroCiclo" DESC,
                vl."IdVinculacionLaboral" DESC;
            """
        ),
        {"id": id},
    ).mappings().all()

    vinculacion_actual = next(
        (
            dict(v)
            for v in vinculaciones
            if str(v.get("EstadoVinculacion") or "").strip().upper()
            in {"EN_PROCESO", "ACTIVO"}
        ),
        None,
    )

    if vinculacion_actual is None and vinculaciones:
        vinculacion_actual = dict(vinculaciones[0])

    id_vinculacion_actual = (
        int(vinculacion_actual["IdVinculacionLaboral"])
        if vinculacion_actual
        and vinculacion_actual.get("IdVinculacionLaboral") is not None
        else None
    )

    nucleo_rows = db.execute(
        text(
            """
            SELECT
                nf."IdNucleoFamiliar",
                nf."IdRegistroPersonal",
                nf."IdVinculacionLaboral",
                nf."Nombre",
                nf."Parentesco",
                nf."Edad",
                nf."Ocupacion",
                nf."Telefono",
                nf."Observaciones",
                nf."DependeEconomicamente",
                nf."TieneparentescoEnLaEmpresa",
                nf."NombreFamiliarEmpresa",
                nf."CargoDesempenaEmpresa",
                nf."CedulaFamiliarEmpresa",
                nf."ParentescoFamiliarEmpresa"
            FROM public."NucleoFamiliar" nf
            WHERE nf."IdRegistroPersonal" = :id
            ORDER BY nf."IdNucleoFamiliar";
            """
        ),
        {"id": id},
    ).mappings().all()

    referencias_rows = db.execute(
        text(
            """
            SELECT
                r."IdReferencia",
                r."IdRegistroPersonal",
                r."IdVinculacionLaboral",
                r."IdTipoReferencia",
                r."Nombre",
                r."Telefono",
                r."Parentesco",
                r."TiempoConocerlo",
                r."FechaCreacion",
                r."FechaActualizacion"
            FROM public."Referencia" r
            WHERE r."IdRegistroPersonal" = :id
            ORDER BY r."IdReferencia";
            """
        ),
        {"id": id},
    ).mappings().all()

    experiencia_rows = db.execute(
        text(
            """
            SELECT
                el."IdExperienciaLaboral",
                el."IdRegistroPersonal",
                el."IdVinculacionLaboral",
                el."Cargo",
                el."Compania",
                el."TiempoDuracion",
                el."Funciones",
                el."JefeInmediato",
                el."TelefonoJefe",
                el."TieneExperienciaPrevia"
            FROM public."ExperienciaLaboral" el
            WHERE el."IdRegistroPersonal" = :id
            ORDER BY el."IdExperienciaLaboral";
            """
        ),
        {"id": id},
    ).mappings().all()

    def separar_por_ciclo(rows):
        actuales = []
        historicos = []

        for row in rows:
            item = dict(row)
            id_vinc = item.get("IdVinculacionLaboral")

            if (
                id_vinculacion_actual is not None
                and id_vinc is not None
                and int(id_vinc) == id_vinculacion_actual
            ):
                actuales.append(item)
            else:
                historicos.append(item)

        return actuales, historicos

    nucleo_actual, nucleo_historico = separar_por_ciclo(nucleo_rows)
    referencias_actuales, referencias_historicas = separar_por_ciclo(
        referencias_rows
    )
    experiencia_actual, experiencia_historica = separar_por_ciclo(
        experiencia_rows
    )

    vinculaciones_historicas = [
        dict(v)
        for v in vinculaciones
        if (
            id_vinculacion_actual is None
            or v.get("IdVinculacionLaboral") is None
            or int(v["IdVinculacionLaboral"]) != id_vinculacion_actual
        )
    ]

    return {
        "ok": True,
        "soloConsulta": True,
        "persona": dict(persona),
        "esReintegroActual": bool(
            vinculacion_actual
            and str(
                vinculacion_actual.get("TipoVinculacion") or ""
            ).strip().upper()
            == "REINTEGRO"
        ),
        "vinculacionActual": vinculacion_actual,
        "vinculacionesHistoricas": vinculaciones_historicas,
        "actual": {
            "nucleoFamiliar": nucleo_actual,
            "referencias": referencias_actuales,
            "experienciaLaboral": experiencia_actual,
        },
        "historico": {
            "nucleoFamiliar": nucleo_historico,
            "referencias": referencias_historicas,
            "experienciaLaboral": experiencia_historica,
        },
        "pendienteSepararEnSiguientesFases": [
            "Documentos",
            "DatosSeleccion",
            "Entrevista",
        ],
    }


@router.put("/registro-personal/full/{id_registro}", response_model=RegistroPersonalOut)
def actualizar_registro_personal_full(
    id_registro: int,
    payload: RegistroPersonalCreate,
    db: Session = Depends(get_db)
):
    try:
        config_row = db.execute(
            text('SELECT "Valor" FROM "Configuracion" WHERE "Nombre" = :nombre LIMIT 1'),
            {"nombre": "RegistrosActualzacionesPermitidos"}
        ).first()

        if not config_row:
            raise HTTPException(status_code=500, detail="No se encontró configuración para RegistrosActualizacionesPermitidos")

        valor_config = int(config_row[0])

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
            detail=f"Error controlado {e!s}",
        )


@router.post("/experiencia-laboral")
def crear_experiencia_laboral_seleccion_endpoint(
    payload: ExperienciaLaboralCreateSeleccionSchema,
    db: Session = Depends(get_db),
):
    return crear_experiencia_laboral_seleccion(db, payload)


@router.delete("/experiencia-laboral/{id_experiencia_laboral}")
def eliminar_experiencia_laboral_endpoint(
    id_experiencia_laboral: int,
    db: Session = Depends(get_db),
):
    return eliminar_experiencia_laboral_seleccion(
        db,
        id_experiencia_laboral
    )