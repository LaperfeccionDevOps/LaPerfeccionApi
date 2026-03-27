from typing import Optional
from datetime import date, datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Path
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from sqlalchemy import text
from sqlalchemy.exc import ProgrammingError

from infrastructure.db.deps import get_db


# =========================
# CONFIG: Estados globales
# =========================
# Estos IDs salen de public."EstadoProceso"
ESTADO_GLOBAL_CONTRATADO = 25
ESTADO_GLOBAL_ABIERTO = 30
ESTADO_GLOBAL_ENVIADO_NOMINA = 32

# FUTURO: cuando exista el módulo Nómina, Nómina pondrá el estado final RETIRADO.
# EJ: ESTADO_GLOBAL_RETIRADO = 34


# =========================
# Schemas
# =========================
class TrabajadorBusquedaOut(BaseModel):
    IdRegistroPersonal: int
    IdTipoIdentificacion: int
    NumeroDocumento: str
    Nombres: str
    Apellidos: str
    NombreCompleto: str


class TrabajadorBusquedaDetalleOut(BaseModel):
    IdRegistroPersonal: int
    IdTipoIdentificacion: int
    NumeroDocumento: str
    Nombres: str
    Apellidos: str
    NombreCompleto: str

    Direccion: Optional[str] = None
    Barrio: Optional[str] = None
    Telefono: Optional[str] = None
    Correo: Optional[str] = None
    Cargo: Optional[str] = None

    IdCliente: Optional[int] = None
    ClienteNombre: Optional[str] = None

    IdRetiroLaboral: Optional[int] = None
    IdMotivoRetiro: Optional[int] = None
    MotivoRetiroNombre: Optional[str] = None
    FechaProceso: Optional[str] = None
    FechaCierre: Optional[str] = None
    FechaEnvioOperaciones: Optional[str] = None

    IdTipificacionRetiro: Optional[int] = None
    ObservacionRetiro: Optional[str] = None
    DevolucionCarnet: Optional[bool] = None

    FechaInicio: Optional[str] = None
    FechaUltimoDiaLaborado: Optional[str] = None


class RetiroLaboralCreate(BaseModel):
    IdRegistroPersonal: int
    IdCliente: int
    IdMotivoRetiro: int
    FechaProceso: date
    FechaRetiro: Optional[date] = None
    ObservacionGeneral: Optional[str] = None
    UsuarioActualizacion: Optional[str] = None

    # ✅ Estado del caso RRLL (no del trabajador)
    EstadoCasoRRLL: str = Field(default="ABIERTO")


class RetiroLaboralCreateOut(BaseModel):
    IdRetiroLaboral: int
    IdRegistroPersonal: int
    IdCliente: int
    IdMotivoRetiro: int
    EstadoCasoRRLL: str
    FechaProceso: date
    FechaRetiro: Optional[date] = None
    ObservacionGeneral: Optional[str] = None
    Activo: bool


class RetiroLaboralUpdate(BaseModel):
    IdCliente: Optional[int] = None
    IdMotivoRetiro: Optional[int] = None
    FechaProceso: Optional[date] = None
    FechaRetiro: Optional[date] = None
    FechaCierre: Optional[datetime] = None
    FechaEnvioOperaciones: Optional[datetime] = None
    FechaEnvioNomina: Optional[datetime] = None
    ObservacionGeneral: Optional[str] = None
    Activo: Optional[bool] = None
    UsuarioActualizacion: Optional[str] = None

    # ✅ Estado del caso RRLL (ABIERTO | ENVIADO_NOMINA | CERRADO)
    EstadoCasoRRLL: Optional[str] = None


class RetiroLaboralUpdateOut(BaseModel):
    IdRetiroLaboral: int
    IdRegistroPersonal: int
    IdCliente: int
    IdMotivoRetiro: int
    EstadoCasoRRLL: str
    FechaProceso: date
    FechaRetiro: Optional[date] = None
    ObservacionGeneral: Optional[str] = None
    Activo: bool


router = APIRouter(prefix="/api/rrll", tags=["RRLL - Búsqueda"])


def _norm_tipo(tipo: str) -> str:
    return (tipo or "").strip().upper()


def _norm_num(num: str) -> str:
    return "".join([c for c in (num or "").strip() if c.isdigit()])


TIPO_DOC_TO_ID = {
    "CC": 1, "C": 1, "CEDULA DE CIUDADANIA": 1, "CÉDULA DE CIUDADANÍA": 1,
    "CE": 2, "E": 2, "CEDULA DE EXTRANJERIA": 2, "CÉDULA DE EXTRANJERÍA": 2,
    "PPT": 3, "U": 3, "PERMISO PROTECCION": 3, "PERMISO DE PROTECCION": 3,
    "TI": 4, "T": 4, "TARJETA DE IDENTIDAD": 4,
}


# =========================
# Helpers
# =========================
def _actualizar_estado_global_trabajador(db: Session, id_registro_personal: int, id_estado_proceso: int):
    q = text("""
        UPDATE public."RegistroPersonal"
        SET "IdEstadoProceso" = :id_estado
        WHERE "IdRegistroPersonal" = :id_rp
        RETURNING "IdRegistroPersonal", "IdEstadoProceso";
    """)
    row = db.execute(q, {"id_estado": id_estado_proceso, "id_rp": id_registro_personal}).mappings().first()
    if not row:
        raise HTTPException(status_code=404, detail="No existe el trabajador para actualizar estado global.")
    return row


def _validar_estado_caso(valor: str) -> str:
    v = (valor or "").strip().upper()
    if v not in ("ABIERTO", "ENVIADO_NOMINA", "CERRADO"):
        raise HTTPException(status_code=400, detail="EstadoCasoRRLL inválido. Usa ABIERTO, ENVIADO_NOMINA o CERRADO.")
    return v


def _obtener_fecha_ultimo_dia_laborado(db: Session, id_registro_personal: int):


    
    """
    Regla de negocio para cabecera:
    1) Intentar desde PazYSalvoOperaciones
    2) Si no existe tabla o falla, intentar desde PazYSalvo
    3) Si no hay dato, devolver None
    """
    try:
        q_paz_ops = text("""
            SELECT "FechaUltimoDiaLaborado"
            FROM public."PazYSalvoOperaciones"
            WHERE "IdRegistroPersonal" = :id_registro_personal
            ORDER BY "IdPazYSalvo" DESC
            LIMIT 1;
        """)
        paz = db.execute(q_paz_ops, {"id_registro_personal": id_registro_personal}).mappings().first()
        if paz and paz.get("FechaUltimoDiaLaborado"):
            return paz["FechaUltimoDiaLaborado"]
    except ProgrammingError:
        db.rollback()
    except Exception:
        db.rollback()

    try:
        q_paz = text("""
            SELECT "FechaUltimoDiaLaborado"
            FROM public."PazYSalvo"
            WHERE "IdRegistroPersonal" = :id_registro_personal
            ORDER BY "IdPazYSalvo" DESC
            LIMIT 1;
        """)
        paz2 = db.execute(q_paz, {"id_registro_personal": id_registro_personal}).mappings().first()
        if paz2 and paz2.get("FechaUltimoDiaLaborado"):
            return paz2["FechaUltimoDiaLaborado"]
    except Exception:
        db.rollback()

    return None

def _vincular_entrevista_pendiente_a_retiro(
    db: Session,
    id_registro_personal: int,
    id_retiro_laboral: int
):
    """
    Busca la entrevista de retiro más reciente pendiente de vincular
    para el trabajador y la asocia al retiro recién creado/actualizado.
    """
    entrevista_pendiente = db.execute(
        text("""
            SELECT "IdEntrevistaRetiro"
            FROM public."EntrevistaRetiro"
            WHERE "IdRegistroPersonal" = :id_registro_personal
              AND "IdRetiroLaboral" IS NULL
              AND "Estado" = 'PENDIENTE_VINCULAR'
            ORDER BY "FechaCreacion" DESC, "IdEntrevistaRetiro" DESC
            LIMIT 1
        """),
        {"id_registro_personal": id_registro_personal}
    ).mappings().first()

    if not entrevista_pendiente:
        return None

    vinculada = db.execute(
        text("""
            UPDATE public."EntrevistaRetiro"
            SET
                "IdRetiroLaboral" = :id_retiro_laboral,
                "Estado" = 'VINCULADA'
            WHERE "IdEntrevistaRetiro" = :id_entrevista
            RETURNING "IdEntrevistaRetiro", "IdRetiroLaboral", "Estado"
        """),
        {
            "id_retiro_laboral": id_retiro_laboral,
            "id_entrevista": entrevista_pendiente["IdEntrevistaRetiro"]
        }
    ).mappings().first()

    return vinculada


# =========================
# Endpoints Trabajador
# =========================
@router.get("/trabajador", response_model=TrabajadorBusquedaOut)
def buscar_trabajador_por_documento(
    tipo_documento: str = Query(..., description="CC | CE | TI | PPT"),
    numero_documento: str = Query(..., description="Número de documento (sin puntos)"),
    db: Session = Depends(get_db),
):
    tipo_txt = _norm_tipo(tipo_documento)
    numero = _norm_num(numero_documento)

    if not tipo_txt or not numero:
        raise HTTPException(status_code=400, detail="tipo_documento y numero_documento son obligatorios.")

    id_tipo = TIPO_DOC_TO_ID.get(tipo_txt)
    if not id_tipo:
        raise HTTPException(status_code=400, detail=f"tipo_documento inválido: {tipo_documento}. Usa CC, CE, TI o PPT.")

    q = text("""
        SELECT
          rp."IdRegistroPersonal"      AS "IdRegistroPersonal",
          rp."IdTipoIdentificacion"    AS "IdTipoIdentificacion",
          rp."NumeroIdentificacion"    AS "NumeroDocumento",
          rp."Nombres"                 AS "Nombres",
          rp."Apellidos"               AS "Apellidos",
          COALESCE(rp."Nombres",'') || ' ' || COALESCE(rp."Apellidos",'') AS "NombreCompleto"
        FROM public."RegistroPersonal" rp
        WHERE rp."IdTipoIdentificacion" = :id_tipo
          AND REPLACE(REPLACE(TRIM(rp."NumeroIdentificacion"),'.',''),' ','') = :numero
        LIMIT 1;
    """)

    row = db.execute(q, {"id_tipo": id_tipo, "numero": numero}).mappings().first()
    if not row:
        raise HTTPException(status_code=404, detail="No se encontró trabajador con ese documento.")
    return dict(row)


@router.get("/trabajador/detalle", response_model=TrabajadorBusquedaDetalleOut)
def buscar_trabajador_detalle_por_documento(
    tipo_documento: str = Query(..., description="CC | CE | TI | PPT"),
    numero_documento: str = Query(..., description="Número de documento (sin puntos)"),
    db: Session = Depends(get_db),
):
    tipo_txt = _norm_tipo(tipo_documento)
    numero = _norm_num(numero_documento)

    if not tipo_txt or not numero:
        raise HTTPException(status_code=400, detail="tipo_documento y numero_documento son obligatorios.")

    id_tipo = TIPO_DOC_TO_ID.get(tipo_txt)
    if not id_tipo:
        raise HTTPException(status_code=400, detail=f"tipo_documento inválido: {tipo_documento}. Usa CC, CE, TI o PPT.")

    q = text("""
        SELECT
          rp."IdRegistroPersonal"      AS "IdRegistroPersonal",
          rp."IdTipoIdentificacion"    AS "IdTipoIdentificacion",
          rp."NumeroIdentificacion"    AS "NumeroDocumento",
          rp."Nombres"                 AS "Nombres",
          rp."Apellidos"               AS "Apellidos",
          COALESCE(rp."Nombres",'') || ' ' || COALESCE(rp."Apellidos",'') AS "NombreCompleto",

          da."Direccion"               AS "Direccion",
          da."Barrio"                  AS "Barrio",
          rp."Celular"                 AS "Telefono",
          rp."Email"                   AS "Correo",

          cg."NombreCargo"             AS "Cargo",

          COALESCE(rrll."IdCliente", acc."IdCliente") AS "IdCliente",
          c."Nombre"                                  AS "ClienteNombre",

          rrll."IdRetiroLaboral"                      AS "IdRetiroLaboral",
          rrll."IdMotivoRetiro"                       AS "IdMotivoRetiro",
          mr."Nombre"                                 AS "MotivoRetiroNombre",
          rrll."FechaProceso"::text                   AS "FechaProceso",
          rrll."FechaCierre"::text                    AS "FechaCierre",
          pys."FechaCreacion"::text                   AS "FechaEnvioOperaciones",
          rrll."IdTipificacionRetiro"                 AS "IdTipificacionRetiro",
          rrll."ObservacionRetiro"                    AS "ObservacionRetiro",
          rrll."DevolucionCarnet"                     AS "DevolucionCarnet",

          cb."FechaIngreso"::text                     AS "FechaInicio"

        FROM public."RegistroPersonal" rp

        LEFT JOIN public."DatosAdicionales" da
          ON da."IdRegistroPersonal" = rp."IdRegistroPersonal"

        LEFT JOIN LATERAL (
            SELECT
              a."IdCliente",
              a."IdCargo"
            FROM public."AsignacionCargoCliente" a
            WHERE a."IdRegistroPersonal" = rp."IdRegistroPersonal"
            ORDER BY
              COALESCE(a."FechaActualizacion", a."FechaCreacion") DESC NULLS LAST,
              a."IdAsignacionCargoCliente" DESC
            LIMIT 1
        ) acc ON true

       LEFT JOIN LATERAL (
    SELECT
      rl."IdRetiroLaboral",
      rl."IdCliente",
      rl."IdMotivoRetiro",
      rl."FechaProceso",
      rl."FechaRetiro",
      rl."FechaCierre",
      rl."FechaEnvioOperaciones",
      rl."IdTipificacionRetiro",
      rl."ObservacionRetiro",
      rl."DevolucionCarnet",
      rl."EstadoCasoRRLL",
      rl."Activo"
    FROM public."RetiroLaboral" rl
    WHERE rl."IdRegistroPersonal" = rp."IdRegistroPersonal"
    ORDER BY rl."IdRetiroLaboral" DESC
    LIMIT 1
) rrll ON true
             
        LEFT JOIN LATERAL (
        SELECT
        p."FechaCreacion",
        p."FechaUltimoDiaLaborado",
        p."IdRetiroLaboral"
        FROM public."PazYSalvoOperaciones" p
        WHERE p."IdRetiroLaboral" = rrll."IdRetiroLaboral"
        ORDER BY p."IdPazYSalvo" DESC
        LIMIT 1
    ) pys ON true

        LEFT JOIN public."Cliente" c
          ON c."IdCliente" = COALESCE(rrll."IdCliente", acc."IdCliente")

        LEFT JOIN public."MotivoRetiro" mr
          ON mr."IdMotivoRetiro" = rrll."IdMotivoRetiro"

        LEFT JOIN public."Cargo" cg
          ON cg."IdCargo" = acc."IdCargo"

        LEFT JOIN LATERAL (
            SELECT cb2."FechaIngreso"
            FROM public."ContratacionBasica" cb2
            WHERE cb2."IdRegistroPersonal" = rp."IdRegistroPersonal"
            ORDER BY cb2."IdContratacionBasica" DESC
            LIMIT 1
        ) cb ON true

        WHERE rp."IdTipoIdentificacion" = :id_tipo
          AND REPLACE(REPLACE(TRIM(rp."NumeroIdentificacion"),'.',''),' ','') = :numero
        LIMIT 1;
    """)

    row = db.execute(q, {"id_tipo": id_tipo, "numero": numero}).mappings().first()
    if not row:
        raise HTTPException(status_code=404, detail="No se encontró trabajador con ese documento.")

    out = dict(row)

    fecha_ultimo_dia = _obtener_fecha_ultimo_dia_laborado(db, out["IdRegistroPersonal"])
    out["FechaUltimoDiaLaborado"] = fecha_ultimo_dia.isoformat() if fecha_ultimo_dia else None

    return out


# =========================
# Validar retiro activo (por Activo=true)
# =========================
@router.get("/retiro/activo/{id_registro_personal}")
def validar_retiro_activo(
    id_registro_personal: int,
    db: Session = Depends(get_db)
):
    q = text("""
        SELECT
            "IdRetiroLaboral",
            "IdRegistroPersonal",
            "IdCliente",
            "IdMotivoRetiro",
            "IdTipificacionRetiro",
            "ObservacionRetiro",
            "DevolucionCarnet",
            "EstadoCasoRRLL",
            "FechaProceso",
            "FechaRetiro",
            "Activo",
            "FechaEnvioOperaciones"
            "FechaEnvioNomina",
            "FechaCierre"
        FROM public."RetiroLaboral"
        WHERE "IdRegistroPersonal" = :id_registro_personal
          AND "Activo" = true
        ORDER BY "IdRetiroLaboral" DESC
        LIMIT 1;
    """)
    active = db.execute(q, {"id_registro_personal": id_registro_personal}).mappings().first()

    fecha_ultimo_dia = _obtener_fecha_ultimo_dia_laborado(db, id_registro_personal)

    if active:
        retiro = dict(active)
        retiro["FechaUltimoDiaLaborado"] = fecha_ultimo_dia
        return {"tieneRetiroActivo": True, "retiro": retiro}

    return {
        "tieneRetiroActivo": False,
        "retiro": {
            "IdRegistroPersonal": id_registro_personal,
            "FechaUltimoDiaLaborado": fecha_ultimo_dia
        }
    }


# =========================
# POST: crear retiro
# =========================
@router.post("/retiro", response_model=RetiroLaboralCreateOut)
def crear_retiro_laboral(
    payload: RetiroLaboralCreate,
    db: Session = Depends(get_db),
):
    estado_caso = _validar_estado_caso(payload.EstadoCasoRRLL)

    # ✅ Regla: solo 1 retiro ACTIVO por trabajador
    q_active = text("""
        SELECT "IdRetiroLaboral"
        FROM public."RetiroLaboral"
        WHERE "IdRegistroPersonal" = :id_registro_personal
          AND "Activo" = true
        ORDER BY "IdRetiroLaboral" DESC
        LIMIT 1;
    """)
    active = db.execute(q_active, {"id_registro_personal": payload.IdRegistroPersonal}).mappings().first()
    if active:
        raise HTTPException(
            status_code=409,
            detail=f"Ya existe un retiro ACTIVO para este trabajador (IdRetiroLaboral={active['IdRetiroLaboral']})."
        )

    # ✅ Si lo crean como CERRADO o ENVIADO_NOMINA, debe nacer INACTIVO
    activo_inicial = True
    if estado_caso in ("CERRADO", "ENVIADO_NOMINA"):
        activo_inicial = False

    q_insert = text("""
        INSERT INTO public."RetiroLaboral" (
            "IdRegistroPersonal",
            "IdCliente",
            "IdMotivoRetiro",
            "EstadoCasoRRLL",
            "FechaProceso",
            "FechaRetiro",
            "ObservacionGeneral",
            "Activo",
            "FechaCreacion",
            "FechaActualizacion",
            "UsuarioActualizacion"
        )
        VALUES (
            :id_registro_personal,
            :id_cliente,
            :id_motivo_retiro,
            :estado_caso_rrll,
            :fecha_proceso,
            :fecha_retiro,
            :observacion_general,
            :activo,
            now(),
            now(),
            :usuario_actualizacion
        )
        RETURNING
            "IdRetiroLaboral",
            "IdRegistroPersonal",
            "IdCliente",
            "IdMotivoRetiro",
            "EstadoCasoRRLL",
            "FechaProceso",
            "FechaRetiro",
            "ObservacionGeneral",
            "Activo";
    """)

    try:
        row = db.execute(q_insert, {
            "id_registro_personal": payload.IdRegistroPersonal,
            "id_cliente": payload.IdCliente,
            "id_motivo_retiro": payload.IdMotivoRetiro,
            "estado_caso_rrll": estado_caso,
            "fecha_proceso": payload.FechaProceso,
            "fecha_retiro": payload.FechaRetiro,
            "observacion_general": payload.ObservacionGeneral,
            "activo": activo_inicial,
            "usuario_actualizacion": payload.UsuarioActualizacion,
        }).mappings().first()

        if row:
            _vincular_entrevista_pendiente_a_retiro(
                db=db,
                id_registro_personal=row["IdRegistroPersonal"],
                id_retiro_laboral=row["IdRetiroLaboral"]
            )

        db.commit()

    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Error creando retiro: {str(e)}")

    if not row:
        raise HTTPException(status_code=500, detail="No se pudo crear el retiro.")

    return dict(row)

# =========================
# PUT: actualizar retiro (y sincroniza estado global)
# =========================
@router.put("/retiro/{id_retiro_laboral}", response_model=RetiroLaboralUpdateOut)
def actualizar_retiro_laboral(
    id_retiro_laboral: int = Path(..., description="IdRetiroLaboral a actualizar"),
    payload: RetiroLaboralUpdate = None,
    db: Session = Depends(get_db),
):
    q_get = text("""
        SELECT
            "IdRetiroLaboral",
            "IdRegistroPersonal",
            "IdCliente",
            "IdMotivoRetiro",
            "EstadoCasoRRLL",
            "FechaProceso",
            "FechaRetiro",
            "FechaEnvioOperaciones",
            "FechaEnvioNomina",
            "FechaCierre",
            "ObservacionGeneral",
            "Activo"
        FROM public."RetiroLaboral"
        WHERE "IdRetiroLaboral" = :id_retiro_laboral
        LIMIT 1;
    """)
    current = db.execute(q_get, {"id_retiro_laboral": id_retiro_laboral}).mappings().first()
    if not current:
        raise HTTPException(status_code=404, detail="No existe el retiro a actualizar.")

    nuevo_estado_caso = None
    if payload and payload.EstadoCasoRRLL is not None:
        nuevo_estado_caso = _validar_estado_caso(payload.EstadoCasoRRLL)

    # =========================
    # ✅ AJUSTE DE REGLAS:
    # - ABIERTO  => Activo = true
    # - CERRADO  => Activo = false (+ FechaCierre si no viene)
    # - ENVIADO_NOMINA => Activo = false (+ FechaEnvioNomina si no viene)
    # =========================
    activo_forzado = payload.Activo if payload else None
    fecha_cierre_forzada = payload.FechaCierre if payload else None
    fecha_envio_nomina_forzada = payload.FechaEnvioNomina if payload else None

    if nuevo_estado_caso == "CERRADO":
        activo_forzado = False
        if fecha_cierre_forzada is None:
            fecha_cierre_forzada = datetime.utcnow()

    elif nuevo_estado_caso == "ENVIADO_NOMINA":
        activo_forzado = False
        if fecha_envio_nomina_forzada is None:
            fecha_envio_nomina_forzada = datetime.utcnow()

    elif nuevo_estado_caso == "ABIERTO":
        activo_forzado = True

    # ✅ SI VA A QUEDAR Activo=true, validar que no exista otro Activo=true
    if activo_forzado is True:
        q_other = text("""
            SELECT "IdRetiroLaboral"
            FROM public."RetiroLaboral"
            WHERE "IdRegistroPersonal" = :id_registro_personal
              AND "Activo" = true
              AND "IdRetiroLaboral" <> :id_retiro_laboral
            ORDER BY "IdRetiroLaboral" DESC
            LIMIT 1;
        """)
        other = db.execute(q_other, {
            "id_registro_personal": current["IdRegistroPersonal"],
            "id_retiro_laboral": id_retiro_laboral
        }).mappings().first()
        if other:
            raise HTTPException(
                status_code=409,
                detail=f"No se puede activar. Ya existe otro retiro ACTIVO para este trabajador (IdRetiroLaboral={other['IdRetiroLaboral']})."
            )

    def _aplicar_estado_global_si_corresponde():
        if not nuevo_estado_caso:
            return

        if nuevo_estado_caso == "ABIERTO":
            _actualizar_estado_global_trabajador(db, current["IdRegistroPersonal"], ESTADO_GLOBAL_ABIERTO)

        elif nuevo_estado_caso == "ENVIADO_NOMINA":
            _actualizar_estado_global_trabajador(db, current["IdRegistroPersonal"], ESTADO_GLOBAL_ENVIADO_NOMINA)

        elif nuevo_estado_caso == "CERRADO":
            _actualizar_estado_global_trabajador(db, current["IdRegistroPersonal"], ESTADO_GLOBAL_ENVIADO_NOMINA)

    q_update = text("""
        UPDATE public."RetiroLaboral"
        SET
            "IdCliente" = COALESCE(:id_cliente, "IdCliente"),
            "IdMotivoRetiro" = COALESCE(:id_motivo_retiro, "IdMotivoRetiro"),
            "EstadoCasoRRLL" = COALESCE(:estado_caso_rrll, "EstadoCasoRRLL"),
            "FechaProceso" = COALESCE(:fecha_proceso, "FechaProceso"),
            "FechaRetiro" = COALESCE(:fecha_retiro, "FechaRetiro"),
            "FechaCierre" = COALESCE(:fecha_cierre, "FechaCierre"),
            "FechaEnvioOperaciones" = COALESCE(:fecha_envio_operaciones, "FechaEnvioOperaciones"),
            "FechaEnvioNomina" = COALESCE(:fecha_envio_nomina, "FechaEnvioNomina"),
            "ObservacionGeneral" = COALESCE(:observacion_general, "ObservacionGeneral"),
            "Activo" = COALESCE(:activo, "Activo"),
            "FechaActualizacion" = now(),
            "UsuarioActualizacion" = COALESCE(:usuario_actualizacion, "UsuarioActualizacion")
        WHERE "IdRetiroLaboral" = :id_retiro_laboral
        RETURNING
            "IdRetiroLaboral",
            "IdRegistroPersonal",
            "IdCliente",
            "IdMotivoRetiro",
            "EstadoCasoRRLL",
            "FechaProceso",
            "FechaRetiro",
            "ObservacionGeneral",
            "Activo";
    """)

    try:
        row = db.execute(q_update, {
            "id_retiro_laboral": id_retiro_laboral,
            "id_cliente": payload.IdCliente if payload else None,
            "id_motivo_retiro": payload.IdMotivoRetiro if payload else None,
            "estado_caso_rrll": nuevo_estado_caso,
            "fecha_proceso": payload.FechaProceso if payload else None,
            "fecha_retiro": payload.FechaRetiro if payload else None,
            "fecha_cierre": fecha_cierre_forzada,
            "fecha_envio_operaciones": payload.FechaEnvioOperaciones if payload else None,
            "fecha_envio_nomina": fecha_envio_nomina_forzada,
            "observacion_general": payload.ObservacionGeneral if payload else None,
            "activo": activo_forzado,
            "usuario_actualizacion": payload.UsuarioActualizacion if payload else None,
        }).mappings().first()

        if row:
            _vincular_entrevista_pendiente_a_retiro(
                db=db,
                id_registro_personal=row["IdRegistroPersonal"],
                id_retiro_laboral=row["IdRetiroLaboral"]
            )

        _aplicar_estado_global_si_corresponde()
        db.commit()

    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Error actualizando retiro: {str(e)}")

    if not row:
        raise HTTPException(status_code=500, detail="No se pudo actualizar el retiro.")

    return dict(row)