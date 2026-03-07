# app/core/security.py
from datetime import datetime, timedelta
from typing import Any, Dict

import os
from passlib.context import CryptContext
from jose import jwt

# Configuración del contexto de contraseñas (bcrypt)
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# Configuración de JWT (puedes sobreescribirlas con variables de entorno)
JWT_SECRET: str = os.getenv("JWT_SECRET", "super_clave_ultra_secreta")
JWT_ALGORITHM: str = os.getenv("JWT_ALGORITHM", "HS256")
JWT_EXPIRE_MINUTES: int = int(os.getenv("JWT_EXPIRE_MINUTES", 60))


def hash_password(password: str) -> str:
    """
    Genera un hash seguro para la contraseña en texto plano.
    Ejemplo:
        'MiClave123' -> '$2b$12$asdasd...'
    """
    return pwd_context.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """
    Verifica si la contraseña en texto plano coincide con el hash almacenado.
    Devuelve True si coincide, False si no.
    """
    return pwd_context.verify(plain_password, hashed_password)


def create_access_token(data: Dict[str, Any]) -> str:
    """
    Crea un token JWT con un tiempo de expiración en minutos
    definido por JWT_EXPIRE_MINUTES.
    """
    to_encode = data.copy()
    expire = datetime.utcnow() + timedelta(minutes=JWT_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})
    token = jwt.encode(to_encode, JWT_SECRET, algorithm=JWT_ALGORITHM)
    return token
