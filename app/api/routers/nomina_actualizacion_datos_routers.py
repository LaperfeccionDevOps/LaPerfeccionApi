from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.orm import Session

from infrastructure.db.deps import get_db


router = APIRouter(
    prefix="/api/nomina-actualizacion-datos",
    tags=["Nómina Actualización de Datos"],
)


class ActualizacionDatosRequest(BaseModel):
    Email: Optional[str] = None
    Direccion: Optional[str] = None
    Barrio: Optional[str] = None
    IdLocalidad: Optional[int] = None
    Celular: Optional[str] = None
    TieneWhatsapp: Optional[bool] = None
    NumeroWhatsapp: Optional[str] = None
    IdTipoEps: Optional[int] = None
    IdFondoPensiones: Optional[int] = None
    UsuarioActualizacion: str


@router.get("/health")
def health_nomina_actualizacion_datos(
    db: Session = Depends(get_db),
):
    """
    Valida que el router de Actualización de Datos esté activo
    y que exista conexión con la base de datos.
    """

    try:
        resultado = db.execute(
            text("""
                SELECT
                    current_database() AS "BaseDatos",
                    NOW() AS "FechaServidor";
            """)
        ).mappings().first()

        return {
            "success": True,
            "message": "Módulo Nómina Actualización de Datos disponible.",
            "data": {
                "BaseDatos": resultado["BaseDatos"],
                "FechaServidor": resultado["FechaServidor"],
            },
        }

    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=(
                "Error validando el módulo Nómina Actualización de Datos: "
                f"{e!s}"
            ),
        )


@router.get("/campos")
def obtener_campos_actualizacion(
    db: Session = Depends(get_db),
):
    """
    Retorna los campos activos configurados para el módulo
    Nómina > Actualización de Datos.
    """

    try:
        campos = db.execute(
            text("""
                SELECT
                    "IdCampoActualizacionDatos",
                    "CodigoCampo",
                    "NombreCampo",
                    "TipoControl",
                    "Orden",
                    "SoloLectura",
                    "Obligatorio"
                FROM public."CampoActualizacionDatos"
                WHERE "Activo" = TRUE
                ORDER BY
                    "Orden",
                    "IdCampoActualizacionDatos";
            """)
        ).mappings().all()

        return {
            "success": True,
            "data": [
                dict(campo)
                for campo in campos
            ],
        }

    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=(
                "Error consultando la configuración de campos: "
                f"{e!s}"
            ),
        )


@router.get("/catalogos")
def obtener_catalogos_actualizacion_datos(
    db: Session = Depends(get_db),
):
    """
    Retorna los catálogos activos requeridos por el formulario
    Nómina > Actualización de Datos.

    Catálogos:
    - Localidades
    - EPS
    - Fondos de pensión
    """

    try:
        localidades = db.execute(
            text("""
                SELECT
                    "IdLocalidad",
                    "Nombre"
                FROM public."Localidad"
                WHERE "Estado" = TRUE
                ORDER BY "Nombre", "IdLocalidad";
            """)
        ).mappings().all()

        eps = db.execute(
            text("""
                SELECT
                    "IdTipoEps",
                    "Codigo",
                    "Descripcion"
                FROM public."TipoEps"
                WHERE "Estado" = TRUE
                ORDER BY "Descripcion", "IdTipoEps";
            """)
        ).mappings().all()

        fondos_pension = db.execute(
            text("""
                SELECT
                    "IdFondoPensiones",
                    "Nombre",
                    "Codigo"
                FROM public."FondoPensiones"
                WHERE "Estado" = TRUE
                ORDER BY "Nombre", "IdFondoPensiones";
            """)
        ).mappings().all()

        return {
            "success": True,
            "data": {
                "Localidades": [
                    dict(localidad)
                    for localidad in localidades
                ],
                "Eps": [
                    dict(item_eps)
                    for item_eps in eps
                ],
                "FondosPension": [
                    dict(fondo)
                    for fondo in fondos_pension
                ],
            },
        }

    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=(
                "Error consultando los catálogos "
                "de actualización de datos: "
                f"{e!s}"
            ),
        )


@router.get("/trabajadores/buscar")
def buscar_trabajadores_actualizacion_datos(
    q: str,
    db: Session = Depends(get_db),
):
    """
    Busca trabajadores disponibles para actualización de datos
    por nombre, apellido o número de identificación.

    Estados permitidos:
    25 = Contratado
    30 = Abierto
    32 = Enviado a Nómina

    Estado excluido:
    35 = Retirado
    """

    termino = q.strip()

    if len(termino) < 2:
        raise HTTPException(
            status_code=400,
            detail=(
                "Debe ingresar al menos 2 caracteres "
                "para realizar la búsqueda."
            ),
        )

    try:
        trabajadores = db.execute(
            text("""
                SELECT
                    rp."IdRegistroPersonal",
                    rp."NumeroIdentificacion",
                    TRIM(
                        CONCAT(
                            COALESCE(rp."Nombres", ''),
                            ' ',
                            COALESCE(rp."Apellidos", '')
                        )
                    ) AS "NombreCompleto",
                    rp."IdEstadoProceso",
                    ep."Nombre" AS "EstadoProceso"

                FROM public."RegistroPersonal" rp

                LEFT JOIN public."EstadoProceso" ep
                    ON ep."IdEstadoProceso" = rp."IdEstadoProceso"

                WHERE rp."IdEstadoProceso" IN (25, 30, 32)

                  AND (
                        rp."NumeroIdentificacion" ILIKE :termino

                        OR TRIM(
                            CONCAT(
                                COALESCE(rp."Nombres", ''),
                                ' ',
                                COALESCE(rp."Apellidos", '')
                            )
                        ) ILIKE :termino
                  )

                ORDER BY
                    rp."Nombres",
                    rp."Apellidos",
                    rp."NumeroIdentificacion"

                LIMIT 50;
            """),
            {
                "termino": f"%{termino}%",
            },
        ).mappings().all()

        return {
            "success": True,
            "cantidad": len(trabajadores),
            "data": [
                dict(trabajador)
                for trabajador in trabajadores
            ],
        }

    except HTTPException:
        raise

    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=(
                "Error buscando trabajadores "
                "para actualización de datos: "
                f"{e!s}"
            ),
        )


@router.get("/trabajadores/{id_registro_personal}")
def obtener_detalle_trabajador_actualizacion_datos(
    id_registro_personal: int,
    db: Session = Depends(get_db),
):
    """
    Consulta los datos actuales de un trabajador para el módulo
    Nómina > Actualización de Datos.

    Estados permitidos:
    25 = Contratado
    30 = Abierto
    32 = Enviado a Nómina
    """

    try:
        trabajador = db.execute(
            text("""
                SELECT
                    rp."IdRegistroPersonal",
                    rp."NumeroIdentificacion",

                    TRIM(
                        CONCAT(
                            COALESCE(rp."Nombres", ''),
                            ' ',
                            COALESCE(rp."Apellidos", '')
                        )
                    ) AS "NombreCompleto",

                    rp."Email",
                    rp."Celular",
                    rp."TieneWhatsapp",
                    rp."NumeroWhatsapp",

                    da."Direccion",
                    da."Barrio",

                    da."IdLocalidad",
                    loc."Nombre" AS "Localidad",

                    rp."IdTipoEps",
                    eps."Descripcion" AS "Eps",

                    rp."IdFondoPensiones",
                    fp."Nombre" AS "FondoPension",

                    rp."IdEstadoProceso",
                    ep."Nombre" AS "EstadoProceso"

                FROM public."RegistroPersonal" rp

                LEFT JOIN public."EstadoProceso" ep
                    ON ep."IdEstadoProceso" = rp."IdEstadoProceso"

                LEFT JOIN LATERAL (
                    SELECT
                        da1."IdDatosAdicionales",
                        da1."Direccion",
                        da1."Barrio",
                        da1."IdLocalidad"
                    FROM public."DatosAdicionales" da1
                    WHERE da1."IdRegistroPersonal" =
                          rp."IdRegistroPersonal"
                    ORDER BY da1."IdDatosAdicionales" DESC
                    LIMIT 1
                ) da ON TRUE

                LEFT JOIN public."Localidad" loc
                    ON loc."IdLocalidad" = da."IdLocalidad"

                LEFT JOIN public."TipoEps" eps
                    ON eps."IdTipoEps" = rp."IdTipoEps"

                LEFT JOIN public."FondoPensiones" fp
                    ON fp."IdFondoPensiones" =
                       rp."IdFondoPensiones"

                WHERE rp."IdRegistroPersonal" =
                      :id_registro_personal

                  AND rp."IdEstadoProceso" IN (25, 30, 32)

                LIMIT 1;
            """),
            {
                "id_registro_personal": id_registro_personal,
            },
        ).mappings().first()

        if not trabajador:
            raise HTTPException(
                status_code=404,
                detail=(
                    "Trabajador no encontrado o no disponible "
                    "para actualización de datos."
                ),
            )

        return {
            "success": True,
            "data": dict(trabajador),
        }

    except HTTPException:
        raise

    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=(
                "Error consultando el detalle del trabajador: "
                f"{e!s}"
            ),
        )

@router.put("/trabajadores/{id_registro_personal}")
def actualizar_datos_trabajador(
    id_registro_personal: int,
    payload: ActualizacionDatosRequest,
    db: Session = Depends(get_db),
):
    """
    Actualiza parcialmente los datos permitidos de un trabajador.

    Reglas:
    - Solo modifica los campos enviados.
    - Los campos no enviados conservan su valor actual.
    - Permite completar valores que actualmente estén NULL o vacíos.
    - Nombre e identificación son de solo lectura.
    - Registra historial únicamente cuando existe un cambio real.
    - Si el trabajador no tiene DatosAdicionales, crea el registro
      únicamente cuando se envía Dirección, Barrio o Localidad.
    - La operación completa se confirma o revierte como una unidad.
    """

    usuario = payload.UsuarioActualizacion.strip()

    if not usuario:
        raise HTTPException(
            status_code=400,
            detail="UsuarioActualizacion es obligatorio.",
        )

    campos_enviados = set(payload.model_fields_set)
    campos_enviados.discard("UsuarioActualizacion")

    if not campos_enviados:
        raise HTTPException(
            status_code=400,
            detail=(
                "Debe enviar al menos un campo "
                "para realizar la actualización."
            ),
        )

    campos_registro_personal = {
        "Email": {
            "columna": "Email",
            "codigo": "CORREO",
            "nombre": "Correo electrónico",
        },
        "Celular": {
            "columna": "Celular",
            "codigo": "TELEFONO",
            "nombre": "Teléfono",
        },
        "TieneWhatsapp": {
            "columna": "TieneWhatsapp",
            "codigo": "TIENE_WHATSAPP",
            "nombre": "¿Tiene WhatsApp?",
        },
        "NumeroWhatsapp": {
            "columna": "NumeroWhatsapp",
            "codigo": "NUMERO_WHATSAPP",
            "nombre": "Teléfono WhatsApp",
        },
        "IdTipoEps": {
            "columna": "IdTipoEps",
            "codigo": "EPS",
            "nombre": "EPS",
        },
        "IdFondoPensiones": {
            "columna": "IdFondoPensiones",
            "codigo": "FONDO_PENSION",
            "nombre": "Fondo de pensión",
        },
    }

    campos_datos_adicionales = {
        "Direccion": {
            "columna": "Direccion",
            "codigo": "DIRECCION",
            "nombre": "Dirección de residencia",
        },
        "Barrio": {
            "columna": "Barrio",
            "codigo": "BARRIO",
            "nombre": "Barrio",
        },
        "IdLocalidad": {
            "columna": "IdLocalidad",
            "codigo": "LOCALIDAD",
            "nombre": "Localidad",
        },
    }

    campos_permitidos = (
        set(campos_registro_personal.keys())
        | set(campos_datos_adicionales.keys())
    )

    campos_no_permitidos = campos_enviados - campos_permitidos

    if campos_no_permitidos:
        raise HTTPException(
            status_code=400,
            detail=(
                "Se enviaron campos no permitidos para actualización: "
                + ", ".join(sorted(campos_no_permitidos))
            ),
        )

    try:
        trabajador = db.execute(
            text("""
                SELECT
                    rp."IdRegistroPersonal",
                    rp."NumeroIdentificacion",
                    rp."Nombres",
                    rp."Apellidos",
                    rp."Email",
                    rp."Celular",
                    rp."TieneWhatsapp",
                    rp."NumeroWhatsapp",
                    rp."IdTipoEps",
                    rp."IdFondoPensiones",
                    rp."IdEstadoProceso"
                FROM public."RegistroPersonal" rp
                WHERE rp."IdRegistroPersonal" = :id_registro_personal
                  AND rp."IdEstadoProceso" IN (25, 30, 32)
                FOR UPDATE;
            """),
            {
                "id_registro_personal": id_registro_personal,
            },
        ).mappings().first()

        if not trabajador:
            raise HTTPException(
                status_code=404,
                detail=(
                    "Trabajador no encontrado o no disponible "
                    "para actualización de datos."
                ),
            )

        datos_adicionales = db.execute(
            text("""
                SELECT
                    da."IdDatosAdicionales",
                    da."Direccion",
                    da."Barrio",
                    da."IdLocalidad",
                    da."IdCiudad",
                    da."IdGrupoSanguineo"
                FROM public."DatosAdicionales" da
                WHERE da."IdRegistroPersonal" = :id_registro_personal
                ORDER BY da."IdDatosAdicionales" DESC
                LIMIT 1
                FOR UPDATE;
            """),
            {
                "id_registro_personal": id_registro_personal,
            },
        ).mappings().first()

        if "IdLocalidad" in campos_enviados:
            if payload.IdLocalidad is None:
                raise HTTPException(
                    status_code=400,
                    detail=(
                        "IdLocalidad no puede enviarse como NULL. "
                        "Seleccione una localidad válida."
                    ),
                )

            localidad_valida = db.execute(
                text("""
                    SELECT 1
                    FROM public."Localidad"
                    WHERE "IdLocalidad" = :id_localidad
                      AND "Estado" = TRUE
                    LIMIT 1;
                """),
                {
                    "id_localidad": payload.IdLocalidad,
                },
            ).first()

            if not localidad_valida:
                raise HTTPException(
                    status_code=400,
                    detail=(
                        "La localidad seleccionada "
                        "no es válida o está inactiva."
                    ),
                )

        if (
            "IdTipoEps" in campos_enviados
            and payload.IdTipoEps is not None
        ):
            eps_valida = db.execute(
                text("""
                    SELECT 1
                    FROM public."TipoEps"
                    WHERE "IdTipoEps" = :id_tipo_eps
                      AND "Estado" = TRUE
                    LIMIT 1;
                """),
                {
                    "id_tipo_eps": payload.IdTipoEps,
                },
            ).first()

            if not eps_valida:
                raise HTTPException(
                    status_code=400,
                    detail=(
                        "La EPS seleccionada "
                        "no es válida o está inactiva."
                    ),
                )

        if (
            "IdFondoPensiones" in campos_enviados
            and payload.IdFondoPensiones is not None
        ):
            fondo_valido = db.execute(
                text("""
                    SELECT 1
                    FROM public."FondoPensiones"
                    WHERE "IdFondoPensiones" = :id_fondo_pensiones
                      AND "Estado" = TRUE
                    LIMIT 1;
                """),
                {
                    "id_fondo_pensiones": payload.IdFondoPensiones,
                },
            ).first()

            if not fondo_valido:
                raise HTTPException(
                    status_code=400,
                    detail=(
                        "El fondo de pensión seleccionado "
                        "no es válido o está inactivo."
                    ),
                )

        valores_registro_personal = {
            "Email": payload.Email,
            "Celular": payload.Celular,
            "TieneWhatsapp": payload.TieneWhatsapp,
            "NumeroWhatsapp": payload.NumeroWhatsapp,
            "IdTipoEps": payload.IdTipoEps,
            "IdFondoPensiones": payload.IdFondoPensiones,
        }

        valores_datos_adicionales = {
            "Direccion": payload.Direccion,
            "Barrio": payload.Barrio,
            "IdLocalidad": payload.IdLocalidad,
        }

        cambios = []
        cambios_registro_personal = {}

        for campo, configuracion in campos_registro_personal.items():
            if campo not in campos_enviados:
                continue

            valor_anterior = trabajador[campo]
            valor_nuevo = valores_registro_personal[campo]

            if valor_anterior == valor_nuevo:
                continue

            cambios_registro_personal[
                configuracion["columna"]
            ] = valor_nuevo

            cambios.append({
                "CodigoCampo": configuracion["codigo"],
                "NombreCampo": configuracion["nombre"],
                "ValorAnterior": valor_anterior,
                "ValorNuevo": valor_nuevo,
            })

        if cambios_registro_personal:
            partes_set = []
            parametros = {
                "id_registro_personal": id_registro_personal,
                "usuario_actualizacion": usuario,
            }

            for indice, (columna, valor) in enumerate(
                cambios_registro_personal.items()
            ):
                parametro = f"valor_rp_{indice}"
                partes_set.append(f'"{columna}" = :{parametro}')
                parametros[parametro] = valor

            partes_set.append(
                '"FechaActualizacion" = CURRENT_TIMESTAMP'
            )
            partes_set.append(
                '"UsuarioActualizacion" = :usuario_actualizacion'
            )

            sql_actualizacion = f"""
                UPDATE public."RegistroPersonal"
                SET {", ".join(partes_set)}
                WHERE "IdRegistroPersonal" = :id_registro_personal;
            """

            db.execute(
                text(sql_actualizacion),
                parametros,
            )

        campos_da_enviados = (
            campos_enviados
            & set(campos_datos_adicionales.keys())
        )

        if campos_da_enviados:
            if datos_adicionales:
                cambios_datos_adicionales = {}

                for campo, configuracion in (
                    campos_datos_adicionales.items()
                ):
                    if campo not in campos_da_enviados:
                        continue

                    valor_anterior = datos_adicionales[campo]
                    valor_nuevo = valores_datos_adicionales[campo]

                    if valor_anterior == valor_nuevo:
                        continue

                    cambios_datos_adicionales[
                        configuracion["columna"]
                    ] = valor_nuevo

                    cambios.append({
                        "CodigoCampo": configuracion["codigo"],
                        "NombreCampo": configuracion["nombre"],
                        "ValorAnterior": valor_anterior,
                        "ValorNuevo": valor_nuevo,
                    })

                if cambios_datos_adicionales:
                    partes_set = []
                    parametros = {
                        "id_datos_adicionales": (
                            datos_adicionales[
                                "IdDatosAdicionales"
                            ]
                        ),
                    }

                    for indice, (columna, valor) in enumerate(
                        cambios_datos_adicionales.items()
                    ):
                        parametro = f"valor_da_{indice}"
                        partes_set.append(
                            f'"{columna}" = :{parametro}'
                        )
                        parametros[parametro] = valor

                    sql_actualizacion_da = f"""
                        UPDATE public."DatosAdicionales"
                        SET {", ".join(partes_set)}
                        WHERE "IdDatosAdicionales" =
                              :id_datos_adicionales;
                    """

                    db.execute(
                        text(sql_actualizacion_da),
                        parametros,
                    )

            else:
                # DatosAdicionales exige IdCiudad e IdGrupoSanguineo.
                # En QA se validó:
                # IdCiudad 10 = Bogotá D.C.
                # IdGrupoSanguineo 1 = Sin definir
                # IdLocalidad 40 = SIN DEFINIR
                id_ciudad_nuevo = 10
                id_grupo_sanguineo_nuevo = 1

                direccion_nueva = (
                    payload.Direccion
                    if "Direccion" in campos_da_enviados
                    else None
                )

                barrio_nuevo = (
                    payload.Barrio
                    if "Barrio" in campos_da_enviados
                    else None
                )

                id_localidad_nueva = (
                    payload.IdLocalidad
                    if "IdLocalidad" in campos_da_enviados
                    else 40
                )

                nuevo_dato_adicional = db.execute(
                    text("""
                        INSERT INTO public."DatosAdicionales" (
                            "Direccion",
                            "IdCiudad",
                            "IdLocalidad",
                            "Barrio",
                            "IdRegistroPersonal",
                            "IdGrupoSanguineo"
                        )
                        VALUES (
                            :direccion,
                            :id_ciudad,
                            :id_localidad,
                            :barrio,
                            :id_registro_personal,
                            :id_grupo_sanguineo
                        )
                        RETURNING "IdDatosAdicionales";
                    """),
                    {
                        "direccion": direccion_nueva,
                        "id_ciudad": id_ciudad_nuevo,
                        "id_localidad": id_localidad_nueva,
                        "barrio": barrio_nuevo,
                        "id_registro_personal": id_registro_personal,
                        "id_grupo_sanguineo": (
                            id_grupo_sanguineo_nuevo
                        ),
                    },
                ).scalar_one()

                for campo, configuracion in (
                    campos_datos_adicionales.items()
                ):
                    if campo not in campos_da_enviados:
                        continue

                    cambios.append({
                        "CodigoCampo": configuracion["codigo"],
                        "NombreCampo": configuracion["nombre"],
                        "ValorAnterior": None,
                        "ValorNuevo": (
                            valores_datos_adicionales[campo]
                        ),
                    })

                datos_adicionales = {
                    "IdDatosAdicionales": nuevo_dato_adicional,
                }

        if cambios:
            for cambio in cambios:
                valor_anterior = cambio["ValorAnterior"]
                valor_nuevo = cambio["ValorNuevo"]

                db.execute(
                    text("""
                        INSERT INTO public."HistorialActualizacionDatos" (
                            "IdRegistroPersonal",
                            "CodigoCampo",
                            "NombreCampo",
                            "ValorAnterior",
                            "ValorNuevo",
                            "UsuarioActualizacion"
                        )
                        VALUES (
                            :id_registro_personal,
                            :codigo_campo,
                            :nombre_campo,
                            :valor_anterior,
                            :valor_nuevo,
                            :usuario_actualizacion
                        );
                    """),
                    {
                        "id_registro_personal": id_registro_personal,
                        "codigo_campo": cambio["CodigoCampo"],
                        "nombre_campo": cambio["NombreCampo"],
                        "valor_anterior": (
                            None
                            if valor_anterior is None
                            else str(valor_anterior)
                        ),
                        "valor_nuevo": (
                            None
                            if valor_nuevo is None
                            else str(valor_nuevo)
                        ),
                        "usuario_actualizacion": usuario,
                    },
                )

        db.commit()

        return {
            "success": True,
            "message": (
                "Datos actualizados correctamente."
                if cambios
                else "No se detectaron cambios para guardar."
            ),
            "cantidadCambios": len(cambios),
            "camposActualizados": [
                cambio["CodigoCampo"]
                for cambio in cambios
            ],
        }

    except HTTPException:
        db.rollback()
        raise

    except Exception as e:
        db.rollback()

        raise HTTPException(
            status_code=500,
            detail=(
                "Error actualizando los datos del trabajador: "
                f"{e!s}"
            ),
        )

