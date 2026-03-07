# app/infrastructure/security/jwt_handler.py

import os
from datetime import datetime, timedelta, timezone
from typing import Optional, Dict, Any

from jose import jwt, JWTError  # requiere python-jose

# Leemos variables de entorno (.env)
# ✅ Compatibilidad: si algún día manejas JWT_SECRET_KEY, igual funcionará
SECRET_KEY = os.getenv("JWT_SECRET") or os.getenv("JWT_SECRET_KEY") or "dev_secret_key"
ALGORITHM = os.getenv("JWT_ALGORITHM", "HS256")
DEFAULT_EXPIRE_MINUTES = int(os.getenv("JWT_EXPIRE_MINUTES", "60"))


def create_access_token(
    data: Dict[str, Any],
    expires_delta: Optional[timedelta] = None,
) -> str:
    """
    Genera un JWT firmado con SECRET_KEY.
    data: contenido del token (por ejemplo {"sub": username, "roles": [...]})
    """
    to_encode = data.copy()

    if expires_delta is None:
        expires_delta = timedelta(minutes=DEFAULT_EXPIRE_MINUTES)

    # ✅ UTC con timezone (evita problemas de validación)
    now = datetime.now(timezone.utc)
    expire = now + expires_delta

    # ✅ Campos estándar útiles (no rompen nada)
    to_encode.setdefault("type", "access")
    to_encode.setdefault("iat", int(now.timestamp()))
    to_encode.update({"exp": expire})

    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)


def decode_access_token(token: str) -> Dict[str, Any]:
    """
    Decodifica un token y devuelve el payload.
    Lanza JWTError si es inválido o expirado.
    """
    try:
        return jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    except JWTError as e:
        # ✅ mantenemos exactamente tu comportamiento: propagar JWTError
        raise e
