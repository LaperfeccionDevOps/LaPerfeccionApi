# app/api/routers/auth.py
from datetime import timedelta
from typing import Optional
import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm  # Swagger Authorize (form-data)
from pydantic import BaseModel
from sqlalchemy.orm import Session
from sqlalchemy import text
from passlib.context import CryptContext

from infrastructure.db.deps import get_db
from domain.models.usuario import Usuario
from domain.models.rol import Rol
from domain.models.usuario_roles import UsuarioRol
from infrastructure.security.jwt_handler import create_access_token
from infrastructure.security.auth_dependencies import get_current_user

router = APIRouter()

# ------------------ Roles (IDs de tu BD) ------------------
ROL_ADMIN = 1
ROL_SELECCION = 2
ROL_CONTRATACION = 3
ROL_ASPIRANTE = 4
ROL_SUPER_ADMIN = 5
ROL_TALENTO_HUMANO = 13
ROL_DESARROLLADOR = 15

# Estos roles SIEMPRE pueden ver todo
GLOBAL_ROLES = {ROL_ADMIN, ROL_SUPER_ADMIN, ROL_DESARROLLADOR}


def require_roles_ids(*allowed_ids: int):
    """
    Dependency: permite acceso si el usuario tiene:
    - Cualquier rol global (Admin/SuperAdmin/Desarrollador), o
    - Alguno de los roles permitidos enviados por parámetro
    """
    allowed_set = set(int(x) for x in allowed_ids)

    def _dep(current=Depends(get_current_user)):
        roles_ids_raw = current.get("roles_ids") or []
        # ✅ Normalizar a int para evitar errores por tipos (str vs int)
        roles_ids = {int(x) for x in roles_ids_raw}

        if roles_ids & GLOBAL_ROLES:
            return current

        if roles_ids & allowed_set:
            return current

        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No tienes permisos para este recurso",
        )

    return _dep


# ------------------ Endpoints de prueba (TEMPORALES) ------------------
@router.get("/auth/protegido-dev")
def protegido_dev(current=Depends(require_roles_ids(ROL_DESARROLLADOR))):
    return {"ok": True, "msg": "Entraste: rol Desarrollador o Global (Admin/SuperAdmin/Dev)"}


@router.get("/auth/protegido-seleccion")
def protegido_seleccion(current=Depends(require_roles_ids(ROL_SELECCION))):
    return {"ok": True, "msg": "Entraste: rol Selección o Global (Admin/SuperAdmin/Dev)"}


# ✅ Config central
ACCESS_TOKEN_EXPIRE_MINUTES = 360

pwd_context = CryptContext(
    schemes=["pbkdf2_sha256"],
    deprecated="auto",
)

# ------------------ Schemas ------------------
class LoginRequest(BaseModel):
    nombre_usuario: str
    contrasena: str


class RegisterRequest(BaseModel):
    nombre_usuario: str
    contrasena: str
    usuario_creador: str
    id_rol: Optional[int] = None


class AsignarRolRequest(BaseModel):
    id_rol: int


# ------------------ Helpers ------------------
def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)


def _unauthorized():
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Usuario o contraseña incorrectos",
        headers={"WWW-Authenticate": "Bearer"},
    )


def _get_usuario_by_username(db: Session, username: str) -> Optional[Usuario]:
    return db.query(Usuario).filter(Usuario.NombreUsuario == username).first()


def _authenticate_user(db: Session, username: str, password: str) -> Usuario:
    usuario = _get_usuario_by_username(db, username)
    if not usuario or not verify_password(password, usuario.Contrasena):
        _unauthorized()
    return usuario


def _get_roles(db: Session, id_usuario) -> tuple[list[int], list[str]]:
    filas_roles = (
        db.query(Rol.IdRol, Rol.NombreRol)
        .join(UsuarioRol, UsuarioRol.IdRol == Rol.IdRol)
        .filter(UsuarioRol.IdUsuario == id_usuario)
        .all()
    )
    roles_ids = [int(r[0]) for r in filas_roles]
    roles = [r[1] for r in filas_roles]
    return roles_ids, roles


def _build_roles_and_token(usuario: Usuario, db: Session) -> dict:
    roles_ids, roles = _get_roles(db, usuario.IdUsuario)

    access_token = create_access_token(
        data={
            "sub": usuario.NombreUsuario,
            "uid": str(usuario.IdUsuario),
            "roles": roles,
            "roles_ids": roles_ids,
        },
        expires_delta=timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES),
    )

    # ✅ FIX: DEVOLVER access_token (tu front lo está esperando)
    return {
        "access_token": access_token,
        "token_type": "bearer",
        "usuario": usuario.NombreUsuario,
        "id_usuario": str(usuario.IdUsuario),
        "roles": roles,
        "roles_ids": roles_ids,
    }


# ------------------ Auth endpoints ------------------
@router.post("/auth/token")
def token(
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: Session = Depends(get_db),
):
    """
    Para Swagger Authorize (OAuth2 password flow).
    Swagger envía form-data: username, password.
    """
    usuario = _authenticate_user(db, form_data.username, form_data.password)
    return _build_roles_and_token(usuario, db)


@router.post("/auth/login")
def login(payload: LoginRequest, db: Session = Depends(get_db)):
    """
    Para tu FRONT (JSON).
    """
    usuario = _authenticate_user(db, payload.nombre_usuario, payload.contrasena)
    data = _build_roles_and_token(usuario, db)
    data["message"] = "Inicio de sesión exitoso"
    return data


@router.get("/auth/me")
def me(current=Depends(get_current_user)):
    """
    ✅ MODO PRODUCCIÓN:
    /auth/me solo valida token (NO roles).
    """
    u = current["usuario"]
    return {
        "usuario": u.NombreUsuario,
        "id_usuario": str(u.IdUsuario),
        "roles": current["roles"],
        "roles_ids": current["roles_ids"],
    }


# (Opcional) Si quieres mantener el "PUNTO 2" como prueba sin dañar /auth/me:
@router.get("/auth/me-restringido")
def me_restringido(current=Depends(require_roles_ids(ROL_SELECCION, ROL_TALENTO_HUMANO))):
    """
    ✅ ENDPOINT DE PRUEBA:
    - Pasa si es Selección o Talento Humano
    - O si es global (Admin/SuperAdmin/Desarrollador)
    """
    u = current["usuario"]
    return {
        "usuario": u.NombreUsuario,
        "id_usuario": str(u.IdUsuario),
        "roles": current["roles"],
        "roles_ids": current["roles_ids"],
    }


# ------------------ Users / roles management ------------------
@router.post("/auth/registro-usuario", status_code=status.HTTP_201_CREATED)
def registrar_usuario(payload: RegisterRequest, db: Session = Depends(get_db)):
    existente = _get_usuario_by_username(db, payload.nombre_usuario)
    if existente:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="El nombre de usuario ya existe",
        )

    rol = None
    if payload.id_rol is not None:
        rol = db.query(Rol).filter(Rol.IdRol == payload.id_rol).first()
        if not rol:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="El rol especificado no existe",
            )

    nuevo_usuario = Usuario(
        NombreUsuario=payload.nombre_usuario,
        Contrasena=hash_password(payload.contrasena),
        HashEstado="ACTIVO",
        UsuarioCreador=payload.usuario_creador,
    )

    try:
        db.add(nuevo_usuario)
        db.flush()

        if rol is not None:
            db.add(UsuarioRol(IdUsuario=nuevo_usuario.IdUsuario, IdRol=rol.IdRol))

        db.commit()
        db.refresh(nuevo_usuario)

    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error registrando usuario/rol: {str(e)}",
        )

    response = {
        "message": "Usuario registrado correctamente",
        "usuario": nuevo_usuario.NombreUsuario,
        "id_usuario": str(nuevo_usuario.IdUsuario),
    }
    if rol is not None:
        response["id_rol"] = rol.IdRol
        response["nombre_rol"] = rol.NombreRol

    return response


@router.put("/auth/usuario/{id_usuario}/rol", status_code=status.HTTP_200_OK)
def actualizar_rol_usuario(
    id_usuario: str,
    payload: AsignarRolRequest,
    db: Session = Depends(get_db),
):
    try:
        id_usuario_uuid = uuid.UUID(id_usuario)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="id_usuario no es un UUID válido",
        )

    usuario = db.query(Usuario).filter(Usuario.IdUsuario == id_usuario_uuid).first()
    if not usuario:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="El usuario no existe",
        )

    rol = db.query(Rol).filter(Rol.IdRol == payload.id_rol).first()
    if not rol:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="El rol especificado no existe",
        )

    usuario_rol = (
        db.query(UsuarioRol)
        .filter(UsuarioRol.IdUsuario == usuario.IdUsuario)
        .first()
    )

    if usuario_rol:
        usuario_rol.IdRol = rol.IdRol
    else:
        db.add(UsuarioRol(IdUsuario=usuario.IdUsuario, IdRol=rol.IdRol))

    db.commit()

    return {
        "message": "Rol asignado/actualizado correctamente",
        "id_usuario": str(usuario.IdUsuario),
        "usuario": usuario.NombreUsuario,
        "id_rol": rol.IdRol,
        "nombre_rol": rol.NombreRol,
    }


# ------------------ Debug ------------------
@router.get("/auth/debug/db-info")
def debug_db_info(db: Session = Depends(get_db)):
    info = db.execute(text("""
        SELECT
          current_database() AS db,
          current_user AS usuario,
          current_schema() AS schema,
          current_setting('search_path') AS search_path,
          inet_server_addr() AS server_ip;
    """)).mappings().first()

    tipos = db.execute(text("""
        SELECT table_schema, table_name, column_name, data_type
        FROM information_schema.columns
        WHERE table_name IN ('Usuario', 'UsuarioRoles')
          AND column_name = 'IdUsuario'
        ORDER BY table_schema, table_name;
    """)).mappings().all()

    return {"conexion": dict(info), "tipos": [dict(r) for r in tipos]}
