from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import text
from sqlalchemy.orm import Session

from infrastructure.db.deps import get_db
from infrastructure.security.auth_dependencies import get_current_user


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
