# app/infrastructure/security/auth_dependencies.py
from typing import Dict, Any, List, Optional

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
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
    auto_error=False,  # 👈 CAMBIO: para que podamos dar un error más claro si falta el token
)

def get_current_user(
    token: Optional[str] = Depends(oauth2_scheme),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """
    Lee el Bearer token, valida JWT y devuelve:
    { usuario: <Usuario>, roles: [str], roles_ids: [int], payload: {...} }
    """

    # ✅ 1) Si NO llegó el header Authorization
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="No autenticado. Falta el header: Authorization: Bearer <token>",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # ✅ 2) Si llegó pero es inválido/expiró
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

    usuario = db.query(Usuario).filter(Usuario.NombreUsuario == username).first()
    if not usuario:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Usuario no existe",
            headers={"WWW-Authenticate": "Bearer"},
        )

    filas_roles = (
        db.query(Rol.IdRol, Rol.NombreRol)
        .join(UsuarioRol, UsuarioRol.IdRol == Rol.IdRol)
        .filter(UsuarioRol.IdUsuario == usuario.IdUsuario)
        .all()
    )

    roles_ids: List[int] = [int(r[0]) for r in filas_roles]
    roles: List[str] = [r[1] for r in filas_roles]

    return {
        "usuario": usuario,
        "roles": roles,
        "roles_ids": roles_ids,
        "payload": payload,
    }
