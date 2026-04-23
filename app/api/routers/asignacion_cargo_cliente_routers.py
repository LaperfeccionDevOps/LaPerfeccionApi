from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import Optional, Dict
from sqlalchemy.orm import Session
from sqlalchemy import text
import datetime

from infrastructure.db.deps import get_db

router = APIRouter(
    prefix="/api/asignacion-cargo-cliente",
    tags=["asignacion cargo cliente"],
)

# 🔎 Cambia esta versión cada vez que modifiques el archivo, para validar en Postman
ROUTER_VERSION = "V6-POST-RETORNA-ASIGNACION-ACTUALIZADA"

# ----------------------------
# Schemas
# ----------------------------

class AsignacionUpsertIn(BaseModel):
    IdRegistroPersonal: int
    IdCargo: int
    IdCliente: Optional[int] = None
    Salario: Optional[float] = None
    UsuarioActualizacion: str

class AsignacionOut(BaseModel):
    IdRegistroPersonal: int
    IdCargo: int
    IdCliente: int
    Salario: float
    UsuarioActualizacion: Optional[str] = None
    FechaCreacion: Optional[str] = None
    FechaActualizacion: Optional[str] = None
    CargoNombre: Optional[str] = None
    ClienteNombre: Optional[str] = None


# ----------------------------
# Fallback Cargo (porque tus endpoints /api/cargos están 404)
# ----------------------------
CARGO_FALLBACK_MAP: Dict[int, str] = {
    1: "OPRARIO(A) ALTURAS",
    2: "Operario de alturas",
    3: "Todero",
    4: "OPRARIO(A) DE ASEO",
    5: "Supervisor",
    6: "Tecnico de mantenimiento",
    7: "Analista de contratacion",
    8: "Gerente admon y fininciero",
    9: "Auxiliar de contratacion",
    10: "Planeador de mantenimiento",
    11: "Supervisor piscinas",
    12: "Gerente planeacion y control",
    13: "Supervisor de mantenimiento",
    14: "Coordinador de alturas",
    15: "Desarrollador de Software",
    16: "Tecnologo de mantenimiento",
    17: "Lider de operaciones",
    18: "Coordinador hse",
    19: "Jardinero",
    20: "Steward",
    21: "Asistente Administrativo",
    22: "Gestor documental",
    23: "Coordinador calidad",
    24: "Analista hse",
    25: "Asistente contratacion",
    26: "Aprendiz",
    27: "Tecnologo administrativo",
    29: "Gerente talento humano",
    30: "Auxiliar contable",
    31: "Tecnico electromecanico",
    32: "Tecnico auxiliar administrativo aseo",
    33: "COORDINADOR CALIDAD",
    34: "ANALISTA HSE",
    35: "ASISTENTE CONTRATACION",
    36: "APRENDIZ",
    37: "TECNOLOGO ADMINISTRATIVO",
    38: "DESARROLLADOR DE SOFTWARE",
    39: "GERENTE TALENTO HUMANO",
    40: "AUXILIAR CONTABLE",
    41: "TECNICO ELECTROMECANICO",
    42: "TECNICO AUXILIAR ADMINISTRATIVO ASEO",
}


# ----------------------------
# Helpers
# ----------------------------
def _dt_to_iso(v):
    if v is None:
        return None
    if isinstance(v, (datetime.datetime, datetime.date)):
        try:
            return v.isoformat()
        except Exception:
            return str(v)
    return str(v)

def _safe_scalar(db: Session, sql: str, params: dict):
    """
    OJO: si un SQL falla en Postgres, la transacción queda abortada.
    Por eso hacemos rollback aquí para que el endpoint no se "rompa" después.
    """
    try:
        return db.execute(text(sql), params).scalar()
    except Exception:
        try:
            db.rollback()
        except Exception:
            pass
        return None


def _resolver_cliente_nombre(db: Session, id_cliente: Optional[int]) -> Optional[str]:
    if not id_cliente:
        return None

    candidatos = [
        ('SELECT "Nombre" FROM public."Cliente" WHERE "IdCliente" = :id LIMIT 1', {"id": id_cliente}),
        ('SELECT "RazonSocial" FROM public."Cliente" WHERE "IdCliente" = :id LIMIT 1', {"id": id_cliente}),
        ('SELECT "NombreCliente" FROM public."Cliente" WHERE "IdCliente" = :id LIMIT 1', {"id": id_cliente}),
    ]

    for sql, params in candidatos:
        val = _safe_scalar(db, sql, params)
        if val:
            return str(val).strip()

    return None


def _resolver_cargo_nombre(db: Session, id_cargo: Optional[int]) -> Optional[str]:
    if not id_cargo:
        return None

    # 1) Intentar resolver desde BD (si existe tabla Cargo)
    candidatos = [
        ('SELECT "NombreCargo" FROM public."Cargo" WHERE "IdCargo" = :id LIMIT 1', {"id": id_cargo}),
        ('SELECT "DescripcionCargo" FROM public."Cargo" WHERE "IdCargo" = :id LIMIT 1', {"id": id_cargo}),
        ('SELECT "Nombre" FROM public."Cargo" WHERE "IdCargo" = :id LIMIT 1', {"id": id_cargo}),
        ('SELECT "Descripcion" FROM public."Cargo" WHERE "IdCargo" = :id LIMIT 1', {"id": id_cargo}),
    ]

    for sql, params in candidatos:
        val = _safe_scalar(db, sql, params)
        if val:
            return str(val).strip()

    # 2) Fallback: mapa por ID (para que NO salga "—" en el front)
    return CARGO_FALLBACK_MAP.get(int(id_cargo))


# ----------------------------
# 🔎 Endpoint para verificar que Postman pega a ESTE archivo
# ----------------------------
@router.get("/__version")
def version():
    return {"router": "asignacion-cargo-cliente", "version": ROUTER_VERSION}


# ----------------------------
# GET
# ----------------------------
@router.get(
    "/{id_registro_personal}",
    response_model=AsignacionOut,
    response_model_exclude_none=False,
)
def obtener_asignacion(id_registro_personal: int, db: Session = Depends(get_db)):
    print(f"✅ [asignacion-cargo-cliente] {ROUTER_VERSION} - GET: {id_registro_personal}")

    try:
        row = db.execute(text("""
            SELECT
                "IdRegistroPersonal",
                "IdCargo",
                "IdCliente",
                "Salario",
                "UsuarioActualizacion",
                "FechaCreacion",
                "FechaActualizacion"
            FROM public."AsignacionCargoCliente"
            WHERE "IdRegistroPersonal" = :id
            ORDER BY COALESCE("FechaActualizacion","FechaCreacion") DESC
            LIMIT 1
        """), {"id": id_registro_personal}).mappings().first()

        print(f"🔎 row crudo para {id_registro_personal}: {row}")

        if not row:
            raise HTTPException(
                status_code=404,
                detail="No existe asignación (cargo/cliente/salario) para este aspirante."
            )

        id_cargo = row.get("IdCargo")
        id_cliente = row.get("IdCliente")

        print(f"🔎 id_cargo={id_cargo} | id_cliente={id_cliente}")

        cargo_nombre = _resolver_cargo_nombre(db, id_cargo)
        cliente_nombre = _resolver_cliente_nombre(db, id_cliente)

        print(f"🔎 cargo_nombre={cargo_nombre} | cliente_nombre={cliente_nombre}")

        return AsignacionOut(
            IdRegistroPersonal=row["IdRegistroPersonal"],
            IdCargo=int(id_cargo) if id_cargo is not None else 0,
            IdCliente=int(id_cliente) if id_cliente is not None else 0,
            Salario=float(row["Salario"]) if row["Salario"] is not None else 0.0,
            UsuarioActualizacion=row.get("UsuarioActualizacion"),
            FechaCreacion=_dt_to_iso(row.get("FechaCreacion")),
            FechaActualizacion=_dt_to_iso(row.get("FechaActualizacion")),
            CargoNombre=cargo_nombre,
            ClienteNombre=cliente_nombre,
        )

    except HTTPException:
        raise
    except Exception as e:
        print(f"❌ ERROR REAL en obtener_asignacion({id_registro_personal}): {repr(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Error interno consultando asignación: {str(e)}"
        )

# ----------------------------
# POST (UPSERT) ✅ MODIFICADO: retorna el registro actualizado con nombres
# ----------------------------
@router.post(
    "",
    summary="Crea o actualiza (UPSERT) asignación cargo/cliente/salario",
    response_model=AsignacionOut,
    response_model_exclude_none=False,
)
def upsert_asignacion(payload: AsignacionUpsertIn, db: Session = Depends(get_db)):
    print(f"✅ [asignacion-cargo-cliente] {ROUTER_VERSION} - POST UPSERT:", payload.IdRegistroPersonal)

    # 1) Guardar/actualizar
    db.execute(text("""
        INSERT INTO public."AsignacionCargoCliente" (
            "IdRegistroPersonal",
            "IdCargo",
            "IdCliente",
            "Salario",
            "UsuarioActualizacion",
            "FechaCreacion",
            "FechaActualizacion"
        )
        VALUES (
            :IdRegistroPersonal,
            :IdCargo,
            :IdCliente,
            :Salario,
            :UsuarioActualizacion,
            now(),
            now()
        )
        ON CONFLICT ("IdRegistroPersonal")
        DO UPDATE SET
            "IdCargo" = EXCLUDED."IdCargo",
            "IdCliente" = EXCLUDED."IdCliente",
            "Salario" = EXCLUDED."Salario",
            "UsuarioActualizacion" = EXCLUDED."UsuarioActualizacion",
            "FechaActualizacion" = now()
    """), payload.model_dump())

    db.commit()

    # 2) Leer lo último guardado y devolverlo (con nombres)
    row = db.execute(text("""
        SELECT
            "IdRegistroPersonal",
            "IdCargo",
            "IdCliente",
            "Salario",
            "UsuarioActualizacion",
            "FechaCreacion",
            "FechaActualizacion"
        FROM public."AsignacionCargoCliente"
        WHERE "IdRegistroPersonal" = :id
        ORDER BY COALESCE("FechaActualizacion","FechaCreacion") DESC
        LIMIT 1
    """), {"id": payload.IdRegistroPersonal}).mappings().first()

    if not row:
        raise HTTPException(status_code=404, detail="No se pudo leer la asignación luego de guardar.")

    id_cargo = row.get("IdCargo")
    id_cliente = row.get("IdCliente")

    cargo_nombre = _resolver_cargo_nombre(db, id_cargo)
    cliente_nombre = _resolver_cliente_nombre(db, id_cliente)

    return AsignacionOut(
        IdRegistroPersonal=row["IdRegistroPersonal"],
        IdCargo=int(id_cargo) if id_cargo is not None else 0,
        IdCliente=int(id_cliente) if id_cliente is not None else 0,
        Salario=float(row["Salario"]) if row["Salario"] is not None else 0.0,
        UsuarioActualizacion=row.get("UsuarioActualizacion"),
        FechaCreacion=_dt_to_iso(row.get("FechaCreacion")),
        FechaActualizacion=_dt_to_iso(row.get("FechaActualizacion")),
        CargoNombre=cargo_nombre,
        ClienteNombre=cliente_nombre,
    )
