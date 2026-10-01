# app/infrastructure/security/auth_dependencies.py

from typing import Dict, Any, List, Optional

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy import text
from sqlalchemy.orm import Session

from infrastructure.db.deps import get_db
from infrastructure.security.jwt_handler import decode_access_token
from domain.models.usuario import Usuario
from domain.models.rol import Rol
from domain.models.usuario_roles import UsuarioRol


# Swagger usa esto para saber dónde pedir el token
# (tu FRONT puede seguir usando /api/auth/login con JSON)
oauth2_scheme = OAuth2PasswordBearer(
    tokenUrl="/api/auth/token",
    auto_error=False,
)


def get_current_user(
    token: Optional[str] = Depends(oauth2_scheme),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """
    Lee el Bearer token, valida JWT y devuelve:
    {
        usuario: <Usuario>,
        roles: [str],
        roles_ids: [int],
        permisos: [str],
        payload: {...}
    }
    """

    # 1) Si NO llegó el header Authorization
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=(
                "No autenticado. Falta el header: "
                "Authorization: Bearer <token>"
            ),
            headers={"WWW-Authenticate": "Bearer"},
        )

    # 2) Si llegó pero es inválido/expiró
    try:
        payload = decode_access_token(token)

    except Exception:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token inválido o expirado",
            headers={"WWW-Authenticate": "Bearer"},
        )

    username = payload.get("sub")

    if not username:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token sin 'sub'",
            headers={"WWW-Authenticate": "Bearer"},
        )

    usuario = (
        db.query(Usuario)
        .filter(Usuario.NombreUsuario == username)
        .first()
    )

    if not usuario:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Usuario no existe",
            headers={"WWW-Authenticate": "Bearer"},
        )

    filas_roles = (
        db.query(
            Rol.IdRol,
            Rol.NombreRol,
        )
        .join(
            UsuarioRol,
            UsuarioRol.IdRol == Rol.IdRol,
        )
        .filter(
            UsuarioRol.IdUsuario == usuario.IdUsuario,
        )
        .all()
    )

    roles_ids: List[int] = [
        int(r[0])
        for r in filas_roles
    ]

    roles: List[str] = [
        r[1]
        for r in filas_roles
    ]

    permisos_payload = payload.get("permisos") or []

    permisos: List[str] = [
        str(permiso).strip()
        for permiso in permisos_payload
        if str(permiso).strip()
    ]

    return {
        "usuario": usuario,
        "roles": roles,
        "roles_ids": roles_ids,
        "permisos": permisos,
        "payload": payload,
    }


def get_current_trabajador(
    token: Optional[str] = Depends(oauth2_scheme),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """
    Autenticación exclusiva del Portal del Trabajador.

    El trabajador no se valida contra Usuario,
    UsuarioRoles ni permisos corporativos.

    El JWT del trabajador debe contener:
    {
        "sub": "<numero_identificacion>",
        "tipo_acceso": "TRABAJADOR",
        "id_registro_personal": <int>
    }
    """

    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=(
                "No autenticado. Falta el header: "
                "Authorization: Bearer <token>"
            ),
            headers={"WWW-Authenticate": "Bearer"},
        )

    try:
        payload = decode_access_token(token)

    except Exception:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token inválido o expirado",
            headers={"WWW-Authenticate": "Bearer"},
        )

    tipo_acceso = str(
        payload.get("tipo_acceso") or ""
    ).strip().upper()

    if tipo_acceso != "TRABAJADOR":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                "El token no corresponde "
                "al Portal del Trabajador."
            ),
        )

    numero_identificacion = str(
        payload.get("sub") or ""
    ).strip()

    if not numero_identificacion:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=(
                "El token del trabajador "
                "no contiene identificación."
            ),
            headers={"WWW-Authenticate": "Bearer"},
        )

    id_registro_raw = payload.get(
        "id_registro_personal"
    )

    try:
        id_registro_personal = int(
            id_registro_raw
        )

    except (TypeError, ValueError):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=(
                "El token del trabajador "
                "no contiene un registro personal válido."
            ),
            headers={"WWW-Authenticate": "Bearer"},
        )

    if id_registro_personal <= 0:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=(
                "El token del trabajador "
                "no contiene un registro personal válido."
            ),
            headers={"WWW-Authenticate": "Bearer"},
        )

    trabajador = (
        db.execute(
            text(
                """
                SELECT
                    rp."IdRegistroPersonal",
                    rp."NumeroIdentificacion",
                    rp."Nombres",
                    rp."Apellidos",
                    rp."IdEstadoProceso",
                    rp."IdTipoEps",
                    te."Descripcion" AS "Eps",
                    EXISTS (
                        SELECT 1
                        FROM "VinculacionLaboral" vl
                        WHERE
                            vl."IdRegistroPersonal"
                                = rp."IdRegistroPersonal"
                            AND UPPER(
                                COALESCE(
                                    vl."EstadoVinculacion",
                                    ''
                                )
                            ) = 'ACTIVO'
                    ) AS "TieneVinculacionActiva"
                FROM "RegistroPersonal" rp
                LEFT JOIN "TipoEps" te
                    ON te."IdTipoEps" = rp."IdTipoEps"
                WHERE
                    rp."IdRegistroPersonal"
                        = :id_registro_personal
                    AND TRIM(
                        rp."NumeroIdentificacion"::text
                    ) = :numero_identificacion
                LIMIT 1;
                """
            ),
            {
                "id_registro_personal":
                    id_registro_personal,
                "numero_identificacion":
                    numero_identificacion,
            },
        )
        .mappings()
        .first()
    )

    if not trabajador:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=(
                "No fue posible validar "
                "la identidad del trabajador."
            ),
            headers={"WWW-Authenticate": "Bearer"},
        )

    estado_contratado = (
        int(
            trabajador["IdEstadoProceso"]
            or 0
        )
        == 25
    )

    tiene_vinculacion_activa = bool(
        trabajador[
            "TieneVinculacionActiva"
        ]
    )

    if not (
        estado_contratado
        or tiene_vinculacion_activa
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                "El trabajador no se encuentra "
                "activo para utilizar el portal."
            ),
        )

    nombres = str(
        trabajador["Nombres"]
        or ""
    ).strip()

    apellidos = str(
        trabajador["Apellidos"]
        or ""
    ).strip()

    nombre_completo = (
        f"{nombres} {apellidos}"
    ).strip()

    eps = str(
        trabajador["Eps"]
        or ""
    ).strip()

    return {
        "id_registro_personal": int(
            trabajador[
                "IdRegistroPersonal"
            ]
        ),
        "numero_identificacion": str(
            trabajador[
                "NumeroIdentificacion"
            ]
        ).strip(),
        "nombre_completo":
            nombre_completo,
        "id_tipo_eps":
            trabajador[
                "IdTipoEps"
            ],
        "eps":
            eps,
        "payload":
            payload,
    }