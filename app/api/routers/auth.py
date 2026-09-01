# app/api/routers/auth.py

from datetime import timedelta
from typing import Optional
import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
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


# ------------------ Roles ------------------

ROL_ADMIN = 1
ROL_SELECCION = 2
ROL_CONTRATACION = 3
ROL_ASPIRANTE = 4
ROL_SUPER_ADMIN = 5
ROL_OPERACIONES = 6
ROL_TALENTO_HUMANO = 13
ROL_DESARROLLADOR = 15

GLOBAL_ROLES = {
    ROL_ADMIN,
    ROL_SUPER_ADMIN,
    ROL_DESARROLLADOR,
}


def require_roles_ids(*allowed_ids: int):
    allowed_set = set(int(x) for x in allowed_ids)

    def _dep(current=Depends(get_current_user)):
        roles_ids_raw = current.get("roles_ids") or []
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


# ------------------ Endpoints de prueba ------------------

@router.get("/auth/protegido-dev")
def protegido_dev(
    current=Depends(require_roles_ids(ROL_DESARROLLADOR)),
):
    return {
        "ok": True,
        "msg": "Entraste: rol Desarrollador o Global",
    }


@router.get("/auth/protegido-seleccion")
def protegido_seleccion(
    current=Depends(require_roles_ids(ROL_SELECCION)),
):
    return {
        "ok": True,
        "msg": "Entraste: rol Selección o Global",
    }


# ------------------ Config ------------------

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
    nombre_completo: str
    usuario: str
    correo_corporativo: Optional[str] = None
    contrasena: str
    estado: str = "ACTIVO"
    id_rol: int


class AsignarRolRequest(BaseModel):
    id_rol: int


class CambiarPasswordRequest(BaseModel):
    nueva_contrasena: str


# ------------------ Helpers ------------------

def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(
    plain_password: str,
    hashed_password: str,
) -> bool:
    return pwd_context.verify(
        plain_password,
        hashed_password,
    )


def _unauthorized():
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Usuario o contraseña incorrectos",
        headers={"WWW-Authenticate": "Bearer"},
    )


def _get_usuario_by_username(
    db: Session,
    username: str,
) -> Optional[Usuario]:
    """
    Busca un usuario manteniendo compatibilidad con los registros históricos.

    Usuarios nuevos:
        Usuario = login individual

    Usuarios históricos:
        NombreUsuario = login actual

    Primero intenta encontrar por Usuario.
    Si no existe, conserva la búsqueda histórica por NombreUsuario.
    """

    username = (username or "").strip()

    if not username:
        return None

    # Nuevos usuarios: login almacenado en Usuario.
    usuario = (
        db.query(Usuario)
        .filter(Usuario.Usuario == username)
        .first()
    )

    if usuario is not None:
        return usuario

    # Compatibilidad con todos los usuarios existentes.
    return (
        db.query(Usuario)
        .filter(Usuario.NombreUsuario == username)
        .first()
    )


def _authenticate_user(
    db: Session,
    username: str,
    password: str,
) -> Usuario:
    usuario = _get_usuario_by_username(
        db,
        username,
    )

    if not usuario:
        _unauthorized()

    # Se normaliza para soportar valores históricos como:
    # ACTIVO, Activo o activo.
    estado = (
        usuario.HashEstado or ""
    ).strip().upper()

    if estado != "ACTIVO":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="El usuario se encuentra inactivo",
        )

    if not verify_password(
        password,
        usuario.Contrasena,
    ):
        _unauthorized()

    return usuario


def _get_roles(
    db: Session,
    id_usuario,
) -> tuple[list[int], list[str]]:
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
            UsuarioRol.IdUsuario == id_usuario,
        )
        .all()
    )

    roles_ids = [
        int(r[0])
        for r in filas_roles
    ]

    roles = [
        r[1]
        for r in filas_roles
    ]

    return roles_ids, roles


def _build_roles_and_token(
    usuario: Usuario,
    db: Session,
) -> dict:
    roles_ids, roles = _get_roles(
        db,
        usuario.IdUsuario,
    )

    access_token = create_access_token(
        data={
            "sub": usuario.NombreUsuario,
            "uid": str(usuario.IdUsuario),
            "roles": roles,
            "roles_ids": roles_ids,
        },
        expires_delta=timedelta(
            minutes=ACCESS_TOKEN_EXPIRE_MINUTES
        ),
    )

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
    usuario = _authenticate_user(
        db,
        form_data.username,
        form_data.password,
    )

    return _build_roles_and_token(
        usuario,
        db,
    )


@router.post("/auth/login")
def login(
    payload: LoginRequest,
    db: Session = Depends(get_db),
):
    usuario = _authenticate_user(
        db,
        payload.nombre_usuario,
        payload.contrasena,
    )

    data = _build_roles_and_token(
        usuario,
        db,
    )

    data["message"] = "Inicio de sesión exitoso"

    return data


@router.get("/auth/me")
def me(
    current=Depends(get_current_user),
):
    u = current["usuario"]

    return {
        "usuario": u.NombreUsuario,
        "id_usuario": str(u.IdUsuario),
        "roles": current["roles"],
        "roles_ids": current["roles_ids"],
    }


@router.get("/auth/me-restringido")
def me_restringido(
    current=Depends(
        require_roles_ids(
            ROL_SELECCION,
            ROL_TALENTO_HUMANO,
        )
    ),
):
    u = current["usuario"]

    return {
        "usuario": u.NombreUsuario,
        "id_usuario": str(u.IdUsuario),
        "roles": current["roles"],
        "roles_ids": current["roles_ids"],
    }


# ------------------ Users / roles management ------------------

@router.post(
    "/auth/registro-usuario",
    status_code=status.HTTP_201_CREATED,
)
def registrar_usuario(
    payload: RegisterRequest,
    db: Session = Depends(get_db),
    current=Depends(require_roles_ids(ROL_SUPER_ADMIN)),
):
    nombre_completo = (payload.nombre_completo or "").strip()
    login_usuario = (payload.usuario or "").strip()
    correo_corporativo = ((payload.correo_corporativo or "").strip().lower() or None)
    estado_usuario = (payload.estado or "ACTIVO").strip().upper()

    if not nombre_completo:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="El nombre completo es obligatorio")

    if not login_usuario:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="El nombre de usuario es obligatorio")

    if not payload.contrasena:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="La contraseña es obligatoria")

    if len(payload.contrasena) < 8:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="La contraseña debe tener mínimo 8 caracteres")

    if estado_usuario not in {"ACTIVO", "INACTIVO"}:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="El estado debe ser ACTIVO o INACTIVO")

    existente_login = db.query(Usuario).filter(Usuario.Usuario == login_usuario).first()
    if existente_login:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="El nombre de usuario ya existe")

    existente_historico = db.query(Usuario).filter(Usuario.NombreUsuario == login_usuario).first()
    if existente_historico:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="El nombre de usuario ya existe")

    existente_nombre = db.query(Usuario).filter(Usuario.NombreUsuario == nombre_completo).first()
    if existente_nombre:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Ya existe un usuario registrado con ese nombre completo",
        )

    if correo_corporativo:
        existente_correo = (
            db.query(Usuario)
            .filter(Usuario.CorreoCorporativo == correo_corporativo)
            .first()
        )
        if existente_correo:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="El correo corporativo ya se encuentra registrado",
            )

    rol = db.query(Rol).filter(Rol.IdRol == payload.id_rol).first()
    if not rol:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="El rol especificado no existe")

    usuario_actual = current["usuario"]
    usuario_creador = (
        usuario_actual.Usuario
        or usuario_actual.NombreUsuario
        or "SISTEMA"
    ).strip()[:60]

    nuevo_usuario = Usuario(
        NombreUsuario=nombre_completo,
        Usuario=login_usuario,
        CorreoCorporativo=correo_corporativo,
        Contrasena=hash_password(payload.contrasena),
        HashEstado=estado_usuario,
        UsuarioCreador=usuario_creador,
    )

    try:
        db.add(nuevo_usuario)
        db.flush()

        db.add(
            UsuarioRol(
                IdUsuario=nuevo_usuario.IdUsuario,
                IdRol=rol.IdRol,
            )
        )

        db.commit()
        db.refresh(nuevo_usuario)

    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error registrando usuario/rol: {str(e)}",
        )

    return {
        "message": "Usuario registrado correctamente",
        "id_usuario": str(nuevo_usuario.IdUsuario),
        "nombre_completo": nuevo_usuario.NombreUsuario,
        "usuario": nuevo_usuario.Usuario,
        "correo_corporativo": nuevo_usuario.CorreoCorporativo,
        "estado": nuevo_usuario.HashEstado,
        "id_rol": rol.IdRol,
        "nombre_rol": rol.NombreRol,
    }


@router.put(
    "/auth/usuario/{id_usuario}/rol",
    status_code=status.HTTP_200_OK,
)
def actualizar_rol_usuario(
    id_usuario: str,
    payload: AsignarRolRequest,
    db: Session = Depends(get_db),
):
    try:
        id_usuario_uuid = uuid.UUID(
            id_usuario
        )

    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="id_usuario no es un UUID válido",
        )

    usuario = (
        db.query(Usuario)
        .filter(
            Usuario.IdUsuario == id_usuario_uuid
        )
        .first()
    )

    if not usuario:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="El usuario no existe",
        )

    rol = (
        db.query(Rol)
        .filter(
            Rol.IdRol == payload.id_rol
        )
        .first()
    )

    if not rol:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="El rol especificado no existe",
        )

    usuario_rol = (
        db.query(UsuarioRol)
        .filter(
            UsuarioRol.IdUsuario
            == usuario.IdUsuario
        )
        .first()
    )

    if usuario_rol:
        usuario_rol.IdRol = rol.IdRol
    else:
        db.add(
            UsuarioRol(
                IdUsuario=usuario.IdUsuario,
                IdRol=rol.IdRol,
            )
        )

    db.commit()

    return {
        "message": "Rol asignado/actualizado correctamente",
        "id_usuario": str(usuario.IdUsuario),
        "usuario": usuario.NombreUsuario,
        "id_rol": rol.IdRol,
        "nombre_rol": rol.NombreRol,
    }


@router.put(
    "/auth/usuario/{id_usuario}/password",
    status_code=status.HTTP_200_OK,
)
def cambiar_password_usuario(
    id_usuario: str,
    payload: CambiarPasswordRequest,
    db: Session = Depends(get_db),
):
    try:
        id_usuario_uuid = uuid.UUID(
            id_usuario
        )

    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="id_usuario no es un UUID válido",
        )

    usuario = (
        db.query(Usuario)
        .filter(
            Usuario.IdUsuario == id_usuario_uuid
        )
        .first()
    )

    if not usuario:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="El usuario no existe",
        )

    usuario.Contrasena = hash_password(
        payload.nueva_contrasena
    )

    usuario.UsuarioActualizacion = "juan diaz"

    db.commit()

    return {
        "message": "Contraseña actualizada correctamente",
        "usuario": usuario.NombreUsuario,
        "id_usuario": str(usuario.IdUsuario),
    }


# ------------------ Debug ------------------

@router.get("/auth/debug/db-info")
def debug_db_info(
    db: Session = Depends(get_db),
):
    info = db.execute(
        text(
            """
            SELECT
                current_database() AS db,
                current_user AS usuario,
                current_schema() AS schema,
                current_setting('search_path') AS search_path,
                inet_server_addr() AS server_ip;
            """
        )
    ).mappings().first()

    tipos = db.execute(
        text(
            """
            SELECT
                table_schema,
                table_name,
                column_name,
                data_type
            FROM information_schema.columns
            WHERE table_name IN ('Usuario', 'UsuarioRoles')
              AND column_name = 'IdUsuario'
            ORDER BY table_schema, table_name;
            """
        )
    ).mappings().all()

    return {
        "conexion": dict(info),
        "tipos": [
            dict(r)
            for r in tipos
        ],
    }