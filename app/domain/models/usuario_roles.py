# app/domain/models/usuario_roles.py
from uuid import UUID as UUIDType

from sqlalchemy import Integer, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from infrastructure.db.base import Base


class UsuarioRol(Base):
    __tablename__ = "UsuarioRoles"  # nombre EXACTO de la tabla

    IdUsuarioRol: Mapped[int] = mapped_column(
        "IdUsuarioRol",
        Integer,
        primary_key=True,
        autoincrement=True,
    )

    # En BD IdUsuario es UUID, por eso usamos el tipo UUID de postgres
    IdUsuario: Mapped[UUIDType] = mapped_column(
        "IdUsuario",
        UUID(as_uuid=True),
        ForeignKey("Usuario.IdUsuario"),
        nullable=False,
    )

    IdRol: Mapped[int] = mapped_column(
        "IdRol",
        Integer,
        ForeignKey("Roles.IdRol"),
        nullable=False,
    )
