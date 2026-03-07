# app/infrastructure/security/role_guard.py
from __future__ import annotations

from typing import Callable, Set
from fastapi import Depends, HTTPException, status

from infrastructure.security.auth_dependencies import get_current_user

# ------------------ Roles globales (IDs de tu BD) ------------------
# Estos SIEMPRE pasan a cualquier endpoint protegido por roles.
GLOBAL_ROLES_IDS: Set[int] = {1, 5, 15}  # Admin, Super Admin, Desarrollador


def _to_int_set(values) -> Set[int]:
    """
    Convierte roles_ids a set[int] de forma robusta.
    (Por si vienen como int/str/Decimal desde BD o JWT).
    """
    out: Set[int] = set()
    for v in values or []:
        try:
            out.add(int(v))
        except Exception:
            pass
    return out


def require_roles(*allowed_roles: str) -> Callable:
    """
    ✅ Guard por NOMBRE de rol (strings).
    Uso:
      current = Depends(require_roles("Seleccion", "Talento Humano"))
    """
    allowed = set(allowed_roles)

    def _dep(current=Depends(get_current_user)):
        user_roles = set(current.get("roles") or [])
        if user_roles & allowed:
            return current

        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"No autorizado. Requiere uno de: {sorted(list(allowed))}",
        )

    return _dep


def require_roles_ids(*allowed_ids: int) -> Callable:
    """
    ✅ Guard por ID de rol (ints).
    Regla:
      - Si tiene rol global (Admin/SuperAdmin/Dev) -> PASA
      - Si tiene alguno de allowed_ids -> PASA
      - Si no -> 403
    """
    allowed = set(int(x) for x in allowed_ids)

    def _dep(current=Depends(get_current_user)):
        roles_ids = _to_int_set(current.get("roles_ids"))
        if roles_ids & GLOBAL_ROLES_IDS:
            return current
        if roles_ids & allowed:
            return current

        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No tienes permisos para este recurso",
        )

    return _dep
