from datetime import date
from decimal import Decimal
from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.orm import Session

from infrastructure.db.deps import get_db
from infrastructure.security.auth_dependencies import get_current_user
from services.email_service import enviar_correo_sin_adjunto


router = APIRouter(
    prefix="/api/nomina-incapacidades",
    tags=["Nómina - Incapacidades"],
)


ROLES_NOMINA_PERMITIDOS = {
    "Administrador",
    "Super Administrador",
    "Nómina",
    "Nomina",
}


NOTIFICACIONES_CORREO_ESTADO = {
    "APROBADA": True,
    "RECHAZADA": True,
    "NEGADO": True,
    "EN PROCESO DE PAGO": True,
    "PAGADO": True,
}


class RechazoIncapacidadRequest(BaseModel):
    observacion: str = Field(..., min_length=3, max_length=1000)


class RadicarIncapacidadRequest(BaseModel):
    numero_radicado: str = Field(..., min_length=1, max_length=100)
    fecha_radicacion: date


class NegarIncapacidadRequest(BaseModel):
    causal_negacion: str = Field(..., min_length=3, max_length=1000)


class PagarIncapacidadRequest(BaseModel):
    valor_pagado: Decimal = Field(..., gt=0, max_digits=14, decimal_places=2)


def _obtener_valor_usuario(usuario, *nombres):
    for nombre in nombres:
        if isinstance(usuario, dict) and nombre in usuario:
            return usuario.get(nombre)

        if hasattr(usuario, nombre):
            return getattr(usuario, nombre)

    return None


def _obtener_rol_actual(usuario) -> str:
    rol_directo = _obtener_valor_usuario(
        usuario,
        "role",
        "rol",
        "Rol",
        "NombreRol",
        "nombre_rol",
    )

    if rol_directo:
        return str(rol_directo).strip()

    roles = _obtener_valor_usuario(
        usuario,
        "roles",
        "Roles",
    )

    if isinstance(roles, (list, tuple, set)):
        for rol in roles:
            if isinstance(rol, str):
                valor = rol.strip()
            else:
                valor = (
                    getattr(rol, "Nombre", None)
                    or getattr(rol, "NombreRol", None)
                    or getattr(rol, "nombre", None)
                    or getattr(rol, "nombre_rol", None)
                    or ""
                )

            if valor:
                return str(valor).strip()

    return ""


def _obtener_usuario_gestion(usuario_actual) -> str:
    if isinstance(usuario_actual, dict):
        usuario_obj = usuario_actual.get("usuario")

        if usuario_obj is not None:
            nombre_usuario = getattr(
                usuario_obj,
                "NombreUsuario",
                None,
            )

            if nombre_usuario:
                return str(nombre_usuario).strip()[:150]

        payload = usuario_actual.get("payload")

        if isinstance(payload, dict):
            sub = payload.get("sub")

            if sub:
                return str(sub).strip()[:150]

    valor = _obtener_valor_usuario(
        usuario_actual,
        "NombreUsuario",
        "nombre_usuario",
        "Username",
        "username",
        "Email",
        "email",
        "Correo",
        "correo",
        "Nombre",
        "nombre",
    )

    if valor:
        return str(valor).strip()[:150]

    return "usuario_nomina"


def _validar_acceso_nomina(usuario_actual) -> None:
    rol = _obtener_rol_actual(usuario_actual)

    if rol not in ROLES_NOMINA_PERMITIDOS:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No tiene permisos para gestionar incapacidades de Nómina.",
        )


def _normalizar_estado(estado) -> str:
    valor = str(estado or "").strip()
    return valor or "REGISTRADA"


def _incapacidad_a_dict(fila):
    return {
        "id_incapacidad": fila["IdIncapacidadTrabajador"],
        "id_registro_personal": fila["IdRegistroPersonal"],
        "numero_identificacion": fila["NumeroIdentificacion"],
        "nombres": fila["Nombres"],
        "apellidos": fila["Apellidos"],
        "nombre_completo": (
            f'{fila["Nombres"] or ""} {fila["Apellidos"] or ""}'
        ).strip(),
        "eps": fila["Eps"],
        "tipo_incapacidad": fila["TipoIncapacidad"],
        "descripcion_tipo": fila["DescripcionTipoIncapacidad"],
        "fecha_inicio": fila["FechaInicio"],
        "dias_incapacidad": fila["DiasIncapacidad"],
        "fecha_final": fila["FechaFinal"],
        "es_prorroga": fila["EsProrroga"],
        "estado": _normalizar_estado(fila["Estado"]),
        "observacion_nomina": fila["ObservacionNomina"],
        "usuario_gestion_nomina": fila["UsuarioGestionNomina"],
        "fecha_gestion_nomina": fila["FechaGestionNomina"],
        "numero_radicado": fila["NumeroRadicado"],
        "fecha_radicacion": fila["FechaRadicacion"],
        "causal_negacion": fila["CausalNegacion"],
        "valor_pagado": fila["ValorPagado"],
        "fecha_creacion": fila["FechaCreacion"],
        "fecha_actualizacion": fila["FechaActualizacion"],
        "total_documentos": int(fila["TotalDocumentos"] or 0),
    }


def _documento_a_dict(fila):
    return {
        "id_documento": fila["IdDocumentoIncapacidadTrabajador"],
        "id_incapacidad": fila["IdIncapacidadTrabajador"],
        "tipo_documento": fila["TipoDocumento"],
        "nombre_archivo": fila["NombreArchivo"],
        "formato": fila["Formato"],
        "mime_type": fila["MimeType"],
        "tamano_bytes": fila["TamanoBytes"],
        "fecha_creacion": fila["FechaCreacion"],
    }


def _obtener_datos_correo_incapacidad(
    db: Session,
    id_incapacidad: int,
):
    consulta = text(
        """
        SELECT
            rp."Email",
            rp."Nombres",
            rp."Apellidos",
            i."FechaInicio",
            i."FechaFinal",
            i."DiasIncapacidad",
            i."ValorPagado"
        FROM public."IncapacidadTrabajador" i
        INNER JOIN public."RegistroPersonal" rp
            ON rp."IdRegistroPersonal" = i."IdRegistroPersonal"
        WHERE
            i."IdIncapacidadTrabajador" = :id_incapacidad
            AND i."Activo" = TRUE
        LIMIT 1
        """
    )

    return db.execute(
        consulta,
        {"id_incapacidad": id_incapacidad},
    ).mappings().first()


def _formatear_fecha_correo(fecha) -> str:
    if not fecha:
        return "Sin información"

    try:
        return fecha.strftime("%d/%m/%Y")
    except AttributeError:
        return str(fecha)


def _enviar_notificacion_gestion(
    db: Session,
    id_incapacidad: int,
    estado: str,
    observacion: str | None = None,
) -> tuple[bool, str]:
    estado_normalizado = _normalizar_estado(estado).upper()

    if not NOTIFICACIONES_CORREO_ESTADO.get(
        estado_normalizado,
        False,
    ):
        return (
            False,
            "La notificación por correo está desactivada para este estado.",
        )

    datos = _obtener_datos_correo_incapacidad(
        db,
        id_incapacidad,
    )

    if not datos:
        return (
            False,
            "No fue posible obtener los datos del trabajador.",
        )

    destinatario = str(
        datos["Email"] or ""
    ).strip()

    if not destinatario:
        return (
            False,
            "El trabajador no tiene correo registrado.",
        )

    nombre = (
        f'{datos["Nombres"] or ""} {datos["Apellidos"] or ""}'
    ).strip()

    fecha_inicio = _formatear_fecha_correo(
        datos["FechaInicio"]
    )
    fecha_final = _formatear_fecha_correo(
        datos["FechaFinal"]
    )
    dias = datos["DiasIncapacidad"] or 0

    if estado_normalizado == "APROBADA":
        asunto = "Incapacidad aprobada - Aseos La Perfección"
        cuerpo = (
            f"Hola {nombre},\n\n"
            "Te informamos que la incapacidad registrada "
            "fue aprobada por el área de Nómina.\n\n"
            f"Fecha de inicio: {fecha_inicio}\n"
            f"Fecha final: {fecha_final}\n"
            f"Días de incapacidad: {dias}\n\n"
            "Cordialmente,\n"
            "Aseos La Perfección"
        )

    elif estado_normalizado == "RECHAZADA":
        asunto = "Incapacidad rechazada - Aseos La Perfección"
        cuerpo = (
            f"Hola {nombre},\n\n"
            "Te informamos que la incapacidad registrada "
            "fue rechazada por el área de Nómina.\n\n"
            f"Fecha de inicio: {fecha_inicio}\n"
            f"Fecha final: {fecha_final}\n"
            f"Días de incapacidad: {dias}\n\n"
            "Motivo del rechazo:\n"
            f"{str(observacion or '').strip()}\n\n"
            "Por favor revisa la información correspondiente.\n\n"
            "Cordialmente,\n"
            "Aseos La Perfección"
        )

    elif estado_normalizado == "NEGADO":
        asunto = "Incapacidad negada - Aseos La Perfección"
        cuerpo = (
            f"Hola {nombre},\n\n"
            "Te informamos que la incapacidad radicada "
            "fue negada por la entidad correspondiente.\n\n"
            f"Fecha de inicio: {fecha_inicio}\n"
            f"Fecha final: {fecha_final}\n"
            f"Días de incapacidad: {dias}\n\n"
            "Causal de negación:\n"
            f"{str(observacion or '').strip()}\n\n"
            "Cordialmente,\n"
            "Aseos La Perfección"
        )

    elif estado_normalizado == "EN PROCESO DE PAGO":
        asunto = (
            "Incapacidad en proceso de pago - "
            "Aseos La Perfección"
        )
        cuerpo = (
            f"Hola {nombre},\n\n"
            "Te informamos que la incapacidad radicada "
            "se encuentra en proceso de pago.\n\n"
            f"Fecha de inicio: {fecha_inicio}\n"
            f"Fecha final: {fecha_final}\n"
            f"Días de incapacidad: {dias}\n\n"
            "Cordialmente,\n"
            "Aseos La Perfección"
        )

    elif estado_normalizado == "PAGADO":
        valor_pagado = datos["ValorPagado"]

        if valor_pagado is None:
            valor_texto = "Sin información"
        else:
            valor_texto = (
                f"${valor_pagado:,.2f}"
                .replace(",", "_")
                .replace(".", ",")
                .replace("_", ".")
            )

        asunto = "Incapacidad pagada - Aseos La Perfección"
        cuerpo = (
            f"Hola {nombre},\n\n"
            "Te informamos que la incapacidad registrada "
            "se encuentra en estado pagado.\n\n"
            f"Fecha de inicio: {fecha_inicio}\n"
            f"Fecha final: {fecha_final}\n"
            f"Días de incapacidad: {dias}\n"
            f"Valor pagado: {valor_texto}\n\n"
            "Cordialmente,\n"
            "Aseos La Perfección"
        )

    else:
        return (
            False,
            "No existe una plantilla de correo para este estado.",
        )

    try:
        enviar_correo_sin_adjunto(
            destinatario=destinatario,
            asunto=asunto,
            cuerpo=cuerpo,
        )

        return (
            True,
            f"Notificación enviada a {destinatario}.",
        )

    except Exception as exc:
        print(
            "No fue posible enviar la notificación "
            f"de incapacidad {id_incapacidad}: {exc}"
        )

        return (
            False,
            "La gestión quedó registrada, pero no fue posible "
            "enviar la notificación por correo.",
        )


def _consultar_estado_incapacidad(
    db: Session,
    id_incapacidad: int,
):
    consulta = text(
        """
        SELECT
            "IdIncapacidadTrabajador",
            "Estado",
            "Activo"
        FROM public."IncapacidadTrabajador"
        WHERE "IdIncapacidadTrabajador" = :id_incapacidad
        LIMIT 1
        """
    )

    return db.execute(
        consulta,
        {"id_incapacidad": id_incapacidad},
    ).mappings().first()


def _resolver_incapacidad_no_actualizada(
    db: Session,
    id_incapacidad: int,
):
    fila = _consultar_estado_incapacidad(
        db,
        id_incapacidad,
    )

    if not fila or fila["Activo"] is not True:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="La incapacidad no existe o no está disponible.",
        )

    estado_actual = _normalizar_estado(fila["Estado"])

    if estado_actual.upper() == "BORRADOR":
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="La incapacidad no existe o no está disponible.",
        )

    raise HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail=(
            "La incapacidad ya fue gestionada por Nómina "
            f"y actualmente se encuentra en estado {estado_actual}."
        ),
    )


@router.get("")
def listar_incapacidades_nomina(
    db: Session = Depends(get_db),
    usuario_actual=Depends(get_current_user),
):
    _validar_acceso_nomina(usuario_actual)

    consulta = text(
        '''
        SELECT
            i."IdIncapacidadTrabajador",
            i."IdRegistroPersonal",
            rp."NumeroIdentificacion",
            rp."Nombres",
            rp."Apellidos",
            COALESCE(te."Descripcion", 'No registrada') AS "Eps",
            i."TipoIncapacidad",
            i."DescripcionTipoIncapacidad",
            i."FechaInicio",
            i."DiasIncapacidad",
            i."FechaFinal",
            i."EsProrroga",
            i."Estado",
            i."ObservacionNomina",
            i."UsuarioGestionNomina",
            i."FechaGestionNomina",
            i."NumeroRadicado",
            i."FechaRadicacion",
            i."CausalNegacion",
            i."ValorPagado",
            i."FechaCreacion",
            i."FechaActualizacion",
            COUNT(d."IdDocumentoIncapacidadTrabajador") AS "TotalDocumentos"
        FROM public."IncapacidadTrabajador" i
        INNER JOIN public."RegistroPersonal" rp
            ON rp."IdRegistroPersonal" = i."IdRegistroPersonal"
        LEFT JOIN public."TipoEps" te
            ON te."IdTipoEps" = rp."IdTipoEps"
        LEFT JOIN public."DocumentoIncapacidadTrabajador" d
            ON d."IdIncapacidadTrabajador" = i."IdIncapacidadTrabajador"
            AND d."Activo" = TRUE
        WHERE
            i."Activo" = TRUE
            AND COALESCE(i."Estado", '') <> 'BORRADOR'
        GROUP BY
            i."IdIncapacidadTrabajador",
            i."IdRegistroPersonal",
            rp."NumeroIdentificacion",
            rp."Nombres",
            rp."Apellidos",
            te."Descripcion",
            i."TipoIncapacidad",
            i."DescripcionTipoIncapacidad",
            i."FechaInicio",
            i."DiasIncapacidad",
            i."FechaFinal",
            i."EsProrroga",
            i."Estado",
            i."ObservacionNomina",
            i."UsuarioGestionNomina",
            i."FechaGestionNomina",
            i."NumeroRadicado",
            i."FechaRadicacion",
            i."CausalNegacion",
            i."ValorPagado",
            i."FechaCreacion",
            i."FechaActualizacion"
        ORDER BY
            i."FechaCreacion" DESC,
            i."IdIncapacidadTrabajador" DESC
        '''
    )

    filas = db.execute(consulta).mappings().all()

    incapacidades = [
        _incapacidad_a_dict(fila)
        for fila in filas
    ]

    return {
        "success": True,
        "total": len(incapacidades),
        "data": incapacidades,
    }


@router.get("/{id_incapacidad}")
def obtener_detalle_incapacidad_nomina(
    id_incapacidad: int,
    db: Session = Depends(get_db),
    usuario_actual=Depends(get_current_user),
):
    _validar_acceso_nomina(usuario_actual)

    consulta_incapacidad = text(
        '''
        SELECT
            i."IdIncapacidadTrabajador",
            i."IdRegistroPersonal",
            rp."NumeroIdentificacion",
            rp."Nombres",
            rp."Apellidos",
            COALESCE(te."Descripcion", 'No registrada') AS "Eps",
            i."TipoIncapacidad",
            i."DescripcionTipoIncapacidad",
            i."FechaInicio",
            i."DiasIncapacidad",
            i."FechaFinal",
            i."EsProrroga",
            i."Estado",
            i."ObservacionNomina",
            i."UsuarioGestionNomina",
            i."FechaGestionNomina",
            i."NumeroRadicado",
            i."FechaRadicacion",
            i."CausalNegacion",
            i."ValorPagado",
            i."FechaCreacion",
            i."FechaActualizacion",
            (
                SELECT COUNT(*)
                FROM public."DocumentoIncapacidadTrabajador" d
                WHERE
                    d."IdIncapacidadTrabajador" = i."IdIncapacidadTrabajador"
                    AND d."Activo" = TRUE
            ) AS "TotalDocumentos"
        FROM public."IncapacidadTrabajador" i
        INNER JOIN public."RegistroPersonal" rp
            ON rp."IdRegistroPersonal" = i."IdRegistroPersonal"
        LEFT JOIN public."TipoEps" te
            ON te."IdTipoEps" = rp."IdTipoEps"
        WHERE
            i."IdIncapacidadTrabajador" = :id_incapacidad
            AND i."Activo" = TRUE
            AND COALESCE(i."Estado", '') <> 'BORRADOR'
        LIMIT 1
        '''
    )

    fila = db.execute(
        consulta_incapacidad,
        {"id_incapacidad": id_incapacidad},
    ).mappings().first()

    if not fila:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="La incapacidad no existe o no está disponible.",
        )

    consulta_documentos = text(
        '''
        SELECT
            d."IdDocumentoIncapacidadTrabajador",
            d."IdIncapacidadTrabajador",
            d."TipoDocumento",
            d."NombreArchivo",
            d."Formato",
            d."MimeType",
            d."TamanoBytes",
            d."FechaCreacion"
        FROM public."DocumentoIncapacidadTrabajador" d
        WHERE
            d."IdIncapacidadTrabajador" = :id_incapacidad
            AND d."Activo" = TRUE
        ORDER BY
            d."IdDocumentoIncapacidadTrabajador" ASC
        '''
    )

    documentos = db.execute(
        consulta_documentos,
        {"id_incapacidad": id_incapacidad},
    ).mappings().all()

    data = _incapacidad_a_dict(fila)
    data["documentos"] = [
        _documento_a_dict(documento)
        for documento in documentos
    ]

    return {
        "success": True,
        "data": data,
    }


@router.put("/{id_incapacidad}/aprobar")
def aprobar_incapacidad_nomina(
    id_incapacidad: int,
    db: Session = Depends(get_db),
    usuario_actual=Depends(get_current_user),
):
    _validar_acceso_nomina(usuario_actual)

    usuario_gestion = _obtener_usuario_gestion(usuario_actual)

    consulta = text(
        """
        UPDATE public."IncapacidadTrabajador"
        SET
            "Estado" = 'APROBADA',
            "ObservacionNomina" = NULL,
            "UsuarioGestionNomina" = :usuario_gestion,
            "FechaGestionNomina" = CURRENT_TIMESTAMP,
            "FechaActualizacion" = CURRENT_TIMESTAMP
        WHERE
            "IdIncapacidadTrabajador" = :id_incapacidad
            AND "Activo" = TRUE
            AND UPPER(COALESCE("Estado", '')) = 'REGISTRADA'
        RETURNING
            "IdIncapacidadTrabajador",
            "Estado",
            "ObservacionNomina",
            "UsuarioGestionNomina",
            "FechaGestionNomina",
            "FechaActualizacion"
        """
    )

    fila = db.execute(
        consulta,
        {
            "id_incapacidad": id_incapacidad,
            "usuario_gestion": usuario_gestion,
        },
    ).mappings().first()

    if not fila:
        db.rollback()
        _resolver_incapacidad_no_actualizada(db, id_incapacidad)

    db.commit()

    correo_enviado, detalle_correo = _enviar_notificacion_gestion(
        db=db,
        id_incapacidad=id_incapacidad,
        estado="APROBADA",
    )

    return {
        "success": True,
        "message": "Incapacidad aprobada correctamente.",
        "correo_enviado": correo_enviado,
        "detalle_correo": detalle_correo,
        "data": {
            "id_incapacidad": fila["IdIncapacidadTrabajador"],
            "estado": fila["Estado"],
            "observacion_nomina": fila["ObservacionNomina"],
            "usuario_gestion_nomina": fila["UsuarioGestionNomina"],
            "fecha_gestion_nomina": fila["FechaGestionNomina"],
            "fecha_actualizacion": fila["FechaActualizacion"],
        },
    }


@router.put("/{id_incapacidad}/rechazar")
def rechazar_incapacidad_nomina(
    id_incapacidad: int,
    payload: RechazoIncapacidadRequest,
    db: Session = Depends(get_db),
    usuario_actual=Depends(get_current_user),
):
    _validar_acceso_nomina(usuario_actual)

    observacion = payload.observacion.strip()

    if len(observacion) < 3:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Debe registrar un motivo de rechazo válido.",
        )

    usuario_gestion = _obtener_usuario_gestion(usuario_actual)

    consulta = text(
        """
        UPDATE public."IncapacidadTrabajador"
        SET
            "Estado" = 'RECHAZADA',
            "ObservacionNomina" = :observacion,
            "UsuarioGestionNomina" = :usuario_gestion,
            "FechaGestionNomina" = CURRENT_TIMESTAMP,
            "FechaActualizacion" = CURRENT_TIMESTAMP
        WHERE
            "IdIncapacidadTrabajador" = :id_incapacidad
            AND "Activo" = TRUE
            AND UPPER(COALESCE("Estado", '')) = 'REGISTRADA'
        RETURNING
            "IdIncapacidadTrabajador",
            "Estado",
            "ObservacionNomina",
            "UsuarioGestionNomina",
            "FechaGestionNomina",
            "FechaActualizacion"
        """
    )

    fila = db.execute(
        consulta,
        {
            "id_incapacidad": id_incapacidad,
            "observacion": observacion,
            "usuario_gestion": usuario_gestion,
        },
    ).mappings().first()

    if not fila:
        db.rollback()
        _resolver_incapacidad_no_actualizada(db, id_incapacidad)

    db.commit()

    correo_enviado, detalle_correo = _enviar_notificacion_gestion(
        db=db,
        id_incapacidad=id_incapacidad,
        estado="RECHAZADA",
        observacion=observacion,
    )

    return {
        "success": True,
        "message": "Incapacidad rechazada correctamente.",
        "correo_enviado": correo_enviado,
        "detalle_correo": detalle_correo,
        "data": {
            "id_incapacidad": fila["IdIncapacidadTrabajador"],
            "estado": fila["Estado"],
            "observacion_nomina": fila["ObservacionNomina"],
            "usuario_gestion_nomina": fila["UsuarioGestionNomina"],
            "fecha_gestion_nomina": fila["FechaGestionNomina"],
            "fecha_actualizacion": fila["FechaActualizacion"],
        },
    }


@router.put("/{id_incapacidad}/pendiente-radicacion")
def marcar_pendiente_radicacion_nomina(
    id_incapacidad: int,
    db: Session = Depends(get_db),
    usuario_actual=Depends(get_current_user),
):
    _validar_acceso_nomina(usuario_actual)

    consulta = text(
        """
        UPDATE public."IncapacidadTrabajador"
        SET
            "Estado" = 'PENDIENTE RADICACION',
            "FechaActualizacion" = CURRENT_TIMESTAMP
        WHERE
            "IdIncapacidadTrabajador" = :id_incapacidad
            AND "Activo" = TRUE
            AND UPPER(COALESCE("Estado", '')) = 'APROBADA'
        RETURNING
            "IdIncapacidadTrabajador",
            "Estado",
            "ObservacionNomina",
            "UsuarioGestionNomina",
            "FechaGestionNomina",
            "FechaActualizacion"
        """
    )

    fila = db.execute(
        consulta,
        {
            "id_incapacidad": id_incapacidad,
        },
    ).mappings().first()

    if not fila:
        db.rollback()

        estado_actual = _consultar_estado_incapacidad(
            db,
            id_incapacidad,
        )

        if not estado_actual or estado_actual["Activo"] is not True:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="La incapacidad no existe o no está disponible.",
            )

        estado = _normalizar_estado(
            estado_actual["Estado"]
        )

        if estado.upper() == "BORRADOR":
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="La incapacidad no existe o no está disponible.",
            )

        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "Solo una incapacidad en estado APROBADA puede pasar "
                "a PENDIENTE RADICACION. "
                f"Estado actual: {estado}."
            ),
        )

    db.commit()

    return {
        "success": True,
        "message": (
            "Incapacidad marcada como pendiente de radicación correctamente."
        ),
        "data": {
            "id_incapacidad": fila["IdIncapacidadTrabajador"],
            "estado": fila["Estado"],
            "observacion_nomina": fila["ObservacionNomina"],
            "usuario_gestion_nomina": fila["UsuarioGestionNomina"],
            "fecha_gestion_nomina": fila["FechaGestionNomina"],
            "fecha_actualizacion": fila["FechaActualizacion"],
        },
    }


@router.put("/{id_incapacidad}/radicar")
def radicar_incapacidad_nomina(
    id_incapacidad: int,
    payload: RadicarIncapacidadRequest,
    db: Session = Depends(get_db),
    usuario_actual=Depends(get_current_user),
):
    _validar_acceso_nomina(usuario_actual)

    numero_radicado = payload.numero_radicado.strip()

    if not numero_radicado:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Debe registrar el número de radicado.",
        )

    consulta = text(
        """
        UPDATE public."IncapacidadTrabajador"
        SET
            "Estado" = 'RADICADO',
            "NumeroRadicado" = :numero_radicado,
            "FechaRadicacion" = :fecha_radicacion,
            "FechaActualizacion" = CURRENT_TIMESTAMP
        WHERE
            "IdIncapacidadTrabajador" = :id_incapacidad
            AND "Activo" = TRUE
            AND UPPER(COALESCE("Estado", '')) = 'PENDIENTE RADICACION'
        RETURNING
            "IdIncapacidadTrabajador",
            "Estado",
            "ObservacionNomina",
            "UsuarioGestionNomina",
            "FechaGestionNomina",
            "NumeroRadicado",
            "FechaRadicacion",
            "FechaActualizacion"
        """
    )

    fila = db.execute(
        consulta,
        {
            "id_incapacidad": id_incapacidad,
            "numero_radicado": numero_radicado,
            "fecha_radicacion": payload.fecha_radicacion,
        },
    ).mappings().first()

    if not fila:
        db.rollback()

        estado_actual = _consultar_estado_incapacidad(
            db,
            id_incapacidad,
        )

        if not estado_actual or estado_actual["Activo"] is not True:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="La incapacidad no existe o no está disponible.",
            )

        estado = _normalizar_estado(
            estado_actual["Estado"]
        )

        if estado.upper() == "BORRADOR":
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="La incapacidad no existe o no está disponible.",
            )

        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "Solo una incapacidad en estado PENDIENTE RADICACION "
                "puede pasar a RADICADO. "
                f"Estado actual: {estado}."
            ),
        )

    db.commit()

    return {
        "success": True,
        "message": "Incapacidad radicada correctamente.",
        "data": {
            "id_incapacidad": fila["IdIncapacidadTrabajador"],
            "estado": fila["Estado"],
            "observacion_nomina": fila["ObservacionNomina"],
            "usuario_gestion_nomina": fila["UsuarioGestionNomina"],
            "fecha_gestion_nomina": fila["FechaGestionNomina"],
            "numero_radicado": fila["NumeroRadicado"],
            "fecha_radicacion": fila["FechaRadicacion"],
            "fecha_actualizacion": fila["FechaActualizacion"],
        },
    }


@router.put("/{id_incapacidad}/negar")
def negar_incapacidad_nomina(
    id_incapacidad: int,
    payload: NegarIncapacidadRequest,
    db: Session = Depends(get_db),
    usuario_actual=Depends(get_current_user),
):
    _validar_acceso_nomina(usuario_actual)

    causal_negacion = payload.causal_negacion.strip()

    if len(causal_negacion) < 3:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Debe registrar una causal de negación válida.",
        )

    consulta = text(
        """
        UPDATE public."IncapacidadTrabajador"
        SET
            "Estado" = 'NEGADO',
            "CausalNegacion" = :causal_negacion,
            "FechaActualizacion" = CURRENT_TIMESTAMP
        WHERE
            "IdIncapacidadTrabajador" = :id_incapacidad
            AND "Activo" = TRUE
            AND UPPER(COALESCE("Estado", '')) = 'RADICADO'
        RETURNING
            "IdIncapacidadTrabajador",
            "Estado",
            "ObservacionNomina",
            "UsuarioGestionNomina",
            "FechaGestionNomina",
            "NumeroRadicado",
            "FechaRadicacion",
            "CausalNegacion",
            "FechaActualizacion"
        """
    )

    fila = db.execute(
        consulta,
        {
            "id_incapacidad": id_incapacidad,
            "causal_negacion": causal_negacion,
        },
    ).mappings().first()

    if not fila:
        db.rollback()

        estado_actual = _consultar_estado_incapacidad(
            db,
            id_incapacidad,
        )

        if not estado_actual or estado_actual["Activo"] is not True:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="La incapacidad no existe o no está disponible.",
            )

        estado = _normalizar_estado(
            estado_actual["Estado"]
        )

        if estado.upper() == "BORRADOR":
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="La incapacidad no existe o no está disponible.",
            )

        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "Solo una incapacidad en estado RADICADO puede pasar "
                "a NEGADO. "
                f"Estado actual: {estado}."
            ),
        )

    db.commit()

    correo_enviado, detalle_correo = _enviar_notificacion_gestion(
        db=db,
        id_incapacidad=id_incapacidad,
        estado="NEGADO",
        observacion=causal_negacion,
    )

    return {
        "success": True,
        "message": "Incapacidad marcada como negada correctamente.",
        "correo_enviado": correo_enviado,
        "detalle_correo": detalle_correo,
        "data": {
            "id_incapacidad": fila["IdIncapacidadTrabajador"],
            "estado": fila["Estado"],
            "observacion_nomina": fila["ObservacionNomina"],
            "usuario_gestion_nomina": fila["UsuarioGestionNomina"],
            "fecha_gestion_nomina": fila["FechaGestionNomina"],
            "numero_radicado": fila["NumeroRadicado"],
            "fecha_radicacion": fila["FechaRadicacion"],
            "causal_negacion": fila["CausalNegacion"],
            "fecha_actualizacion": fila["FechaActualizacion"],
        },
    }


@router.put("/{id_incapacidad}/en-proceso-pago")
def marcar_en_proceso_pago_nomina(
    id_incapacidad: int,
    db: Session = Depends(get_db),
    usuario_actual=Depends(get_current_user),
):
    _validar_acceso_nomina(usuario_actual)

    consulta = text(
        """
        UPDATE public."IncapacidadTrabajador"
        SET
            "Estado" = 'EN PROCESO DE PAGO',
            "CausalNegacion" = NULL,
            "FechaActualizacion" = CURRENT_TIMESTAMP
        WHERE
            "IdIncapacidadTrabajador" = :id_incapacidad
            AND "Activo" = TRUE
            AND UPPER(COALESCE("Estado", '')) = 'RADICADO'
        RETURNING
            "IdIncapacidadTrabajador",
            "Estado",
            "ObservacionNomina",
            "UsuarioGestionNomina",
            "FechaGestionNomina",
            "NumeroRadicado",
            "FechaRadicacion",
            "CausalNegacion",
            "FechaActualizacion"
        """
    )

    fila = db.execute(
        consulta,
        {
            "id_incapacidad": id_incapacidad,
        },
    ).mappings().first()

    if not fila:
        db.rollback()

        estado_actual = _consultar_estado_incapacidad(
            db,
            id_incapacidad,
        )

        if not estado_actual or estado_actual["Activo"] is not True:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="La incapacidad no existe o no está disponible.",
            )

        estado = _normalizar_estado(
            estado_actual["Estado"]
        )

        if estado.upper() == "BORRADOR":
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="La incapacidad no existe o no está disponible.",
            )

        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "Solo una incapacidad en estado RADICADO puede pasar "
                "a EN PROCESO DE PAGO. "
                f"Estado actual: {estado}."
            ),
        )

    db.commit()

    correo_enviado, detalle_correo = _enviar_notificacion_gestion(
        db=db,
        id_incapacidad=id_incapacidad,
        estado="EN PROCESO DE PAGO",
    )

    return {
        "success": True,
        "message": (
            "Incapacidad marcada como en proceso de pago correctamente."
        ),
        "correo_enviado": correo_enviado,
        "detalle_correo": detalle_correo,
        "data": {
            "id_incapacidad": fila["IdIncapacidadTrabajador"],
            "estado": fila["Estado"],
            "observacion_nomina": fila["ObservacionNomina"],
            "usuario_gestion_nomina": fila["UsuarioGestionNomina"],
            "fecha_gestion_nomina": fila["FechaGestionNomina"],
            "numero_radicado": fila["NumeroRadicado"],
            "fecha_radicacion": fila["FechaRadicacion"],
            "causal_negacion": fila["CausalNegacion"],
            "fecha_actualizacion": fila["FechaActualizacion"],
        },
    }


@router.put("/{id_incapacidad}/pagar")
def pagar_incapacidad_nomina(
    id_incapacidad: int,
    payload: PagarIncapacidadRequest,
    db: Session = Depends(get_db),
    usuario_actual=Depends(get_current_user),
):
    _validar_acceso_nomina(usuario_actual)

    valor_pagado = payload.valor_pagado.quantize(
        Decimal("0.01")
    )

    consulta = text(
        """
        UPDATE public."IncapacidadTrabajador"
        SET
            "Estado" = 'PAGADO',
            "ValorPagado" = :valor_pagado,
            "FechaActualizacion" = CURRENT_TIMESTAMP
        WHERE
            "IdIncapacidadTrabajador" = :id_incapacidad
            AND "Activo" = TRUE
            AND UPPER(COALESCE("Estado", '')) = 'EN PROCESO DE PAGO'
        RETURNING
            "IdIncapacidadTrabajador",
            "Estado",
            "ObservacionNomina",
            "UsuarioGestionNomina",
            "FechaGestionNomina",
            "NumeroRadicado",
            "FechaRadicacion",
            "CausalNegacion",
            "ValorPagado",
            "FechaActualizacion"
        """
    )

    fila = db.execute(
        consulta,
        {
            "id_incapacidad": id_incapacidad,
            "valor_pagado": valor_pagado,
        },
    ).mappings().first()

    if not fila:
        db.rollback()

        estado_actual = _consultar_estado_incapacidad(
            db,
            id_incapacidad,
        )

        if not estado_actual or estado_actual["Activo"] is not True:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="La incapacidad no existe o no está disponible.",
            )

        estado = _normalizar_estado(
            estado_actual["Estado"]
        )

        if estado.upper() == "BORRADOR":
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="La incapacidad no existe o no está disponible.",
            )

        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "Solo una incapacidad en estado EN PROCESO DE PAGO "
                "puede pasar a PAGADO. "
                f"Estado actual: {estado}."
            ),
        )

    db.commit()

    correo_enviado, detalle_correo = _enviar_notificacion_gestion(
        db=db,
        id_incapacidad=id_incapacidad,
        estado="PAGADO",
    )

    return {
        "success": True,
        "message": "Pago de incapacidad registrado correctamente.",
        "correo_enviado": correo_enviado,
        "detalle_correo": detalle_correo,
        "data": {
            "id_incapacidad": fila["IdIncapacidadTrabajador"],
            "estado": fila["Estado"],
            "observacion_nomina": fila["ObservacionNomina"],
            "usuario_gestion_nomina": fila["UsuarioGestionNomina"],
            "fecha_gestion_nomina": fila["FechaGestionNomina"],
            "numero_radicado": fila["NumeroRadicado"],
            "fecha_radicacion": fila["FechaRadicacion"],
            "causal_negacion": fila["CausalNegacion"],
            "valor_pagado": fila["ValorPagado"],
            "fecha_actualizacion": fila["FechaActualizacion"],
        },
    }


@router.get("/{id_incapacidad}/documentos/{id_documento}")
def ver_documento_incapacidad_nomina(
    id_incapacidad: int,
    id_documento: int,
    db: Session = Depends(get_db),
    usuario_actual=Depends(get_current_user),
):
    _validar_acceso_nomina(usuario_actual)

    consulta = text(
        '''
        SELECT
            d."IdDocumentoIncapacidadTrabajador",
            d."IdIncapacidadTrabajador",
            d."NombreArchivo",
            d."MimeType",
            d."DocumentoCargado"
        FROM public."DocumentoIncapacidadTrabajador" d
        INNER JOIN public."IncapacidadTrabajador" i
            ON i."IdIncapacidadTrabajador" = d."IdIncapacidadTrabajador"
        WHERE
            i."IdIncapacidadTrabajador" = :id_incapacidad
            AND d."IdDocumentoIncapacidadTrabajador" = :id_documento
            AND i."Activo" = TRUE
            AND d."Activo" = TRUE
            AND COALESCE(i."Estado", '') <> 'BORRADOR'
        LIMIT 1
        '''
    )

    fila = db.execute(
        consulta,
        {
            "id_incapacidad": id_incapacidad,
            "id_documento": id_documento,
        },
    ).mappings().first()

    if not fila:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="El documento no existe o no está disponible.",
        )

    contenido = fila["DocumentoCargado"]

    if not contenido:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="El documento no contiene información para visualizar.",
        )

    nombre_archivo = (
        str(fila["NombreArchivo"] or "documento_incapacidad")
        .replace('"', "")
        .replace("\r", "")
        .replace("\n", "")
    )

    mime_type = (
        str(fila["MimeType"] or "").strip()
        or "application/octet-stream"
    )

    return Response(
        content=bytes(contenido),
        media_type=mime_type,
        headers={
            "Content-Disposition": (
                f'inline; filename="{nombre_archivo}"'
            ),
            "Cache-Control": "no-store",
        },
    )
