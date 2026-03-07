from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import Optional, Dict, Any
from sqlalchemy.orm import Session
from sqlalchemy import text

from infrastructure.db.deps import get_db

router = APIRouter(prefix="/api/entrevistas-candidato", tags=["entrevistas-candidato"])

ENT_SCHEMA = "public"
ENT_TABLE = "EntrevistaCandidato"
ENT_FULL = f'{ENT_SCHEMA}."{ENT_TABLE}"'


# ─────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────
def to_regclass(db: Session, full_name: str) -> Optional[str]:
    return db.execute(text("SELECT to_regclass(:t)"), {"t": full_name}).scalar()


def get_columns(db: Session, schema: str, table: str) -> set:
    rows = db.execute(
        text("""
            SELECT column_name
            FROM information_schema.columns
            WHERE table_schema = :s AND table_name = :t
        """),
        {"s": schema, "t": table},
    ).fetchall()
    return {r[0] for r in rows}


def split_schema_table(full: str) -> tuple[str, str]:
    if "." not in full:
        return ("public", full.replace('"', ""))
    schema, rest = full.split(".", 1)
    return (schema.replace('"', ""), rest.replace('"', ""))


def first_existing_table(db: Session, candidates: list[str]) -> Optional[str]:
    for t in candidates:
        if to_regclass(db, t):
            return t
    return None


def detect_first(cols: set, candidates: list[str]) -> Optional[str]:
    for c in candidates:
        if c in cols:
            return c
    return None


def model_dump(obj: BaseModel, **kwargs) -> dict:
    # Pydantic v2: model_dump; Pydantic v1: dict()
    if hasattr(obj, "model_dump"):
        return obj.model_dump(**kwargs)
    return obj.dict(**kwargs)


def normalize_date_value(val: Any) -> Any:
    """
    Evita el error: InvalidDatetimeFormat date: «»
    - '' / '   ' -> None
    - deja pasar date/datetime o 'YYYY-MM-DD'
    """
    if val is None:
        return None
    if isinstance(val, str):
        v = val.strip()
        return None if v == "" else v
    return val


# 🔁 Aliases: si el front manda nombres "cortos" pero en BD existen nombres "largos"
ALIAS_MAP: Dict[str, list[str]] = {
    "IdRegistroPerso": ["IdRegistroPerso", "IdRegistroPersonal"],
    "IdRegistroPersonal": ["IdRegistroPersonal", "IdRegistroPerso"],

    "HaTenidoAccide": ["HaTenidoAccide", "HaTenidoAccidentes", "HaTenidoAccidente"],
    "ConceptoFinalS": ["ConceptoFinalS", "ConceptoFinalSeleccion", "ConceptoFinal", "DecisionFinal", "EstadoDecision"],
    "ObservacionesF": ["ObservacionesF", "ObservacionesFinales", "Observaciones", "ObservacionFinal"],
    "EntrevistadorPo": ["EntrevistadorPo", "EntrevistadorPor", "Entrevistador", "NombreEntrevistador"],

    # ✅ NUEVO: Observaciones Núcleo Familiar en EntrevistaCandidato
    "ObservacionesNucleoFamiliar": ["ObservacionesNucleoFamiliar", "ObsNucleoFamiliar", "ObservacionesNF"],

    # ✅ NUEVO: Patologías / Enfermedades (compatibilidad por si llega con otros nombres)
    "HaTenidoPatologias": ["HaTenidoPatologias", "HaTenidoPatolo", "HaTenidoPatologia", "HaTenidoEnfermedades", "HaTenidoEnfermedad"],
    "HaTenidoPatolo": ["HaTenidoPatolo", "HaTenidoPatologias", "HaTenidoPatologia", "HaTenidoEnfermedades", "HaTenidoEnfermedad"],
    "PatologiaCual": ["PatologiaCual", "PatologiasCual", "EnfermedadCual", "EnfermedadesCual", "DetallePatologia", "CualPatologia"],
}


def resolve_column(ent_cols: set, incoming_key: str) -> Optional[str]:
    if incoming_key in ent_cols:
        return incoming_key
    if incoming_key in ALIAS_MAP:
        for cand in ALIAS_MAP[incoming_key]:
            if cand in ent_cols:
                return cand
    return None


def get_ent_pk_column(db: Session) -> str:
    ent_cols = get_columns(db, ENT_SCHEMA, ENT_TABLE)
    pk = detect_first(ent_cols, ["IdEntrevista", "IdEntrevistaCandidato", "Id", "id"])
    if not pk:
        raise HTTPException(status_code=500, detail="No se encontró PK en EntrevistaCandidato (IdEntrevista, etc.)")
    return pk


def get_ent_fk_columns(db: Session) -> list[str]:
    """
    Devuelve TODAS las columnas FK posibles para registro (si existen).
    Esto arregla el caso donde unas filas quedan en IdRegistroPerso y otras en IdRegistroPersonal.
    """
    ent_cols = get_columns(db, ENT_SCHEMA, ENT_TABLE)
    fk_cols = [c for c in ["IdRegistroPersonal", "IdRegistroPerso"] if c in ent_cols]

    if not fk_cols:
        other = detect_first(ent_cols, ["IdRegistro", "IdAspirante", "IdPersona"])
        if other:
            fk_cols = [other]

    if not fk_cols:
        raise HTTPException(
            status_code=500,
            detail="No se encontró FK de registro en EntrevistaCandidato (IdRegistroPersonal / IdRegistroPerso).",
        )
    return fk_cols


def get_audit_columns(db: Session) -> tuple[Optional[str], Optional[str]]:
    ent_cols = get_columns(db, ENT_SCHEMA, ENT_TABLE)
    fecha_crea = detect_first(ent_cols, ["FechaCreacion", "Fecha_Creacion", "CreatedAt", "created_at"])
    fecha_act = detect_first(ent_cols, ["FechaActualizacion", "FechaActualiza", "Fecha_Actualizacion", "UpdatedAt", "updated_at"])
    return fecha_crea, fecha_act


def build_fk_where_clause(fk_cols: list[str]) -> str:
    ors = [f'"{c}" = :id' for c in fk_cols]
    return "(" + " OR ".join(ors) + ")"


# ─────────────────────────────────────────────
# Modelos
# ─────────────────────────────────────────────
class EntrevistaGuardar(BaseModel):
    IdRegistroPerso: Optional[int] = None
    IdRegistroPersonal: Optional[int] = None

    Cargo: Optional[str] = None
    HaTenidoAccide: Optional[bool] = None
    HaTenidoAccidentes: Optional[bool] = None
    AccidenteCual: Optional[str] = None

    Fortalezas: Optional[str] = None
    AreasDeMejora: Optional[str] = None

    ConceptoFinalS: Optional[str] = None
    ConceptoFinalSeleccion: Optional[str] = None
    ObservacionesF: Optional[str] = None
    ObservacionesFinales: Optional[str] = None
    EntrevistadorPo: Optional[str] = None
    EntrevistadorPor: Optional[str] = None

    # ✅ NUEVO
    ObservacionesNucleoFamiliar: Optional[str] = None

    # ✅ NUEVO: Patologías / Enfermedades (ya existen en BD)
    HaTenidoPatologias: Optional[bool] = None
    HaTenidoPatolo: Optional[bool] = None
    PatologiaCual: Optional[str] = None


class EntrevistaActualizar(BaseModel):
    Cargo: Optional[str] = None
    HaTenidoAccide: Optional[bool] = None
    HaTenidoAccidentes: Optional[bool] = None
    AccidenteCual: Optional[str] = None

    Fortalezas: Optional[str] = None
    AreasDeMejora: Optional[str] = None

    ConceptoFinalS: Optional[str] = None
    ConceptoFinalSeleccion: Optional[str] = None
    ObservacionesF: Optional[str] = None
    ObservacionesFinales: Optional[str] = None
    EntrevistadorPo: Optional[str] = None
    EntrevistadorPor: Optional[str] = None

    Expedicion: Optional[Any] = None
    Barrio: Optional[str] = None
    Localidad: Optional[str] = None
    Edad: Optional[int] = None
    EstadoCivil: Optional[Any] = None
    Hijos: Optional[int] = None
    Celular: Optional[str] = None

    # ✅ NUEVO
    ObservacionesNucleoFamiliar: Optional[str] = None

    # ✅ NUEVO: Patologías / Enfermedades (para PUT por id / por registro)
    HaTenidoPatologias: Optional[bool] = None
    HaTenidoPatolo: Optional[bool] = None
    PatologiaCual: Optional[str] = None


class DecisionFinalPayload(BaseModel):
    ConceptoFinalSeleccion: Optional[str] = None
    ConceptoFinalS: Optional[str] = None
    ObservacionesFinales: Optional[str] = None
    ObservacionesF: Optional[str] = None
    EntrevistadorPor: Optional[str] = None
    EntrevistadorPo: Optional[str] = None


# ✅ NUEVO: payload para observaciones del Núcleo Familiar (en EntrevistaCandidato)
class ObservacionesNucleoFamiliarPayload(BaseModel):
    ObservacionesNucleoFamiliar: str


# ─────────────────────────────────────────────
# Datos personales (autollenado)
# ─────────────────────────────────────────────
def fetch_datos_personales(db: Session, id_registro_perso: int) -> Dict[str, Any]:
    candidates = [
        'public."RegistroPersonal"',
        'public."Registro_Personal"',
        "public.registro_personal",
        "public.registropersonal",
    ]
    reg_full = first_existing_table(db, candidates)
    if not reg_full:
        return {}

    reg_schema, reg_table = split_schema_table(reg_full)
    cols = get_columns(db, reg_schema, reg_table)

    id_col = detect_first(cols, ["IdRegistroPersonal", "IdRegistroPerso", "IdRegistro", "IdPersona", "IdAspirante"])
    if not id_col:
        return {}

    def pick(*names):
        for n in names:
            if n in cols:
                return f'rp."{n}"'
        return "NULL"

    if "NombreCompleto" in cols:
        nombre_expr = 'rp."NombreCompleto"'
    elif "Nombres" in cols and "Apellidos" in cols:
        nombre_expr = 'TRIM(COALESCE(rp."Nombres", \'\') || \' \' || COALESCE(rp."Apellidos", \'\'))'
    else:
        nombre_expr = pick("Nombre", "Nombres")

    tipo_doc_expr = pick("TipoDocumento", "TipoDocumentoID", "IdTipoDocumento", "IdTipoIdentificacion", "TipoIdentificacion")
    ident_expr = pick("Identificacion", "NumeroIdentificacion", "NumeroDocumento", "Documento")
    fecha_exp_expr = pick("FechaExpedicion", "Expedicion", "Fecha_Expedicion")
    lugar_exp_expr = pick("LugarExpedicion", "CiudadExpedicion", "ExpedicionLugar")

    edad_expr = pick("Edad")
    estado_civil_expr = pick("EstadoCivil", "EstadoCivilID", "IdEstadoCivil")
    hijos_expr = pick("Hijos", "NumeroHijos")
    celular_expr = pick("Celular", "TelefonoCelular", "Telefono")
    barrio_expr = pick("Barrio")
    localidad_expr = pick("Localidad", "LocalidadResidencia", "LocalidadVive")

    q = text(f"""
        SELECT
            {nombre_expr}          AS "NombreCompleto",
            {tipo_doc_expr}        AS "TipoDocumento",
            {ident_expr}           AS "Identificacion",
            {fecha_exp_expr}       AS "FechaExpedicion",
            {lugar_exp_expr}       AS "LugarExpedicion",
            {edad_expr}            AS "Edad",
            {estado_civil_expr}    AS "EstadoCivil",
            {hijos_expr}           AS "Hijos",
            {celular_expr}         AS "Celular",
            {barrio_expr}          AS "Barrio",
            {localidad_expr}       AS "Localidad"
        FROM {reg_schema}."{reg_table}" rp
        WHERE rp."{id_col}" = :id
        LIMIT 1
    """)
    row = db.execute(q, {"id": id_registro_perso}).fetchone()
    return dict(row._mapping) if row else {}


def fetch_ultima_entrevista_por_registro(db: Session, id_registro_perso: int) -> Optional[Dict[str, Any]]:
    fk_cols = get_ent_fk_columns(db)
    ent_cols = get_columns(db, ENT_SCHEMA, ENT_TABLE)
    pk_col = get_ent_pk_column(db)

    # ✅ FIX: cuando FechaCreacion tiene muchos NULL, el ORDER BY se vuelve incorrecto.
    # Usamos: FechaCreacion DESC NULLS LAST, y desempate por PK DESC.
    fecha_crea, _ = get_audit_columns(db)
    if fecha_crea and fecha_crea in ent_cols:
        order_by = f'"{fecha_crea}" DESC NULLS LAST, "{pk_col}" DESC'
    else:
        order_by = f'"{pk_col}" DESC'

    where_fk = build_fk_where_clause(fk_cols)

    q = text(f"""
        SELECT *
        FROM {ENT_FULL}
        WHERE {where_fk}
        ORDER BY {order_by}
        LIMIT 1
    """)
    row = db.execute(q, {"id": id_registro_perso}).fetchone()
    return dict(row._mapping) if row else None


def pick_current_value(current: Dict[str, Any], candidates: list[str]) -> Any:
    for c in candidates:
        if c in current:
            return current.get(c)
    return None


# ─────────────────────────────────────────────
# Endpoints
# ─────────────────────────────────────────────
@router.get("/ping")
def ping():
    return {"ok": True, "message": "Ping Entrevistas Candidato"}


@router.get("/prefill/{id_registro_perso}")
def prefill(id_registro_perso: int, db: Session = Depends(get_db)):
    datos = fetch_datos_personales(db, id_registro_perso)
    entrevista = fetch_ultima_entrevista_por_registro(db, id_registro_perso)
    return {"ok": True, "datos_personales": datos, "entrevista": entrevista}


@router.post("/guardar")
def guardar(payload: EntrevistaGuardar, db: Session = Depends(get_db)):
    """
    Guarda: si ya existe una entrevista para el registro, actualiza la ÚLTIMA.
    Si no existe, inserta.
    """
    try:
        ent_cols = get_columns(db, ENT_SCHEMA, ENT_TABLE)
        pk_col = get_ent_pk_column(db)
        fk_cols = get_ent_fk_columns(db)
        fecha_crea, fecha_act = get_audit_columns(db)

        id_registro = payload.IdRegistroPerso or payload.IdRegistroPersonal
        if not id_registro:
            raise HTTPException(status_code=400, detail="Falta IdRegistroPerso / IdRegistroPersonal")

        datos = fetch_datos_personales(db, id_registro)

        # data_to_save: GUARDA EN TODAS LAS FK QUE EXISTAN
        data_to_save: Dict[str, Any] = {}
        for fk in fk_cols:
            if fk in ent_cols:
                data_to_save[fk] = id_registro

        # Autollenado (si existen columnas en EntrevistaCandidato)
        mapping_personal = {
            "NombreCompleto": "Nombre",
            "TipoDocumento": "TipoDocumento",
            "Identificacion": "Identificacion",
            "FechaExpedicion": "Expedicion",
            "Barrio": "Barrio",
            "Localidad": "Localidad",
            "Edad": "Edad",
            "EstadoCivil": "EstadoCivil",
            "Hijos": "Hijos",
            "Celular": "Celular",
        }
        for src, dst in mapping_personal.items():
            if dst in ent_cols and src in datos:
                if dst == "Expedicion":
                    data_to_save[dst] = normalize_date_value(datos[src])
                else:
                    data_to_save[dst] = datos[src]

        # Manuales (con alias)
        manual = model_dump(payload, exclude_unset=True)

        # ✅ NUEVO: Normalización previa para Patologías (para no dejar incoherencias)
        pat_bool = manual.get("HaTenidoPatologias")
        if pat_bool is None:
            pat_bool = manual.get("HaTenidoPatolo")

        pat_cual = manual.get("PatologiaCual")
        if pat_bool is None and pat_cual is not None and str(pat_cual).strip() != "":
            pat_bool = True
            manual["HaTenidoPatologias"] = True
            manual["HaTenidoPatolo"] = True

        if manual.get("HaTenidoPatologias") is None and manual.get("HaTenidoPatolo") is not None:
            manual["HaTenidoPatologias"] = manual["HaTenidoPatolo"]

        if manual.get("HaTenidoPatolo") is None and manual.get("HaTenidoPatologias") is not None:
            manual["HaTenidoPatolo"] = manual["HaTenidoPatologias"]

        pat_bool_final = manual.get("HaTenidoPatologias")
        if pat_bool_final is None:
            pat_bool_final = manual.get("HaTenidoPatolo")

        if pat_bool_final is False:
            manual["PatologiaCual"] = None

        for k, v in manual.items():
            if k in ("IdRegistroPerso", "IdRegistroPersonal"):
                continue

            # normalizar inputs alternos
            if k == "ConceptoFinalSeleccion" and (manual.get("ConceptoFinalS") is None):
                manual["ConceptoFinalS"] = v
                continue
            if k == "ObservacionesFinales" and (manual.get("ObservacionesF") is None):
                manual["ObservacionesF"] = v
                continue
            if k == "EntrevistadorPor" and (manual.get("EntrevistadorPo") is None):
                manual["EntrevistadorPo"] = v
                continue
            if k == "HaTenidoAccidentes" and (manual.get("HaTenidoAccide") is None):
                manual["HaTenidoAccide"] = v
                continue

            # ✅ NUEVO: Patologías (alias entre sí, para compatibilidad)
            if k == "HaTenidoPatologias" and (manual.get("HaTenidoPatolo") is None):
               manual["HaTenidoPatolo"] = v
            if k == "HaTenidoPatolo" and (manual.get("HaTenidoPatologias") is None):
               manual["HaTenidoPatologias"] = v

            col = resolve_column(ent_cols, k)
            if not col:
                continue

            if col == "Expedicion":
                data_to_save[col] = normalize_date_value(v)
            else:
                data_to_save[col] = v

        current = fetch_ultima_entrevista_por_registro(db, id_registro)

        # ───────── UPDATE (última) ─────────
        if current and pk_col in current:
            set_parts = []
            params: Dict[str, Any] = {"pk": current[pk_col]}

            for col, val in data_to_save.items():
                if col not in ent_cols:
                    continue

                if col == "Expedicion":
                    val = normalize_date_value(val)
                    set_parts.append(
                        '"Expedicion" = CASE WHEN :Expedicion IS NULL THEN NULL ELSE CAST(:Expedicion AS date) END'
                    )
                    params["Expedicion"] = val
                else:
                    set_parts.append(f'"{col}" = :{col}')
                    params[col] = val

            if fecha_act and fecha_act in ent_cols:
                set_parts.append(f'"{fecha_act}" = NOW()')

            q = text(f"""
                UPDATE {ENT_FULL}
                SET {", ".join(set_parts)}
                WHERE "{pk_col}" = :pk
                RETURNING "{pk_col}";
            """)
            updated_id = db.execute(q, params).scalar()
            db.commit()
            return {"ok": True, "modo": "update", "IdEntrevista": updated_id}

        # ───────── INSERT ─────────
        cols = []
        vals = []
        params: Dict[str, Any] = {}

        for col, val in data_to_save.items():
            if col not in ent_cols:
                continue

            cols.append(f'"{col}"')
            if col == "Expedicion":
                val = normalize_date_value(val)
                vals.append("CASE WHEN :Expedicion IS NULL THEN NULL ELSE CAST(:Expedicion AS date) END")
                params["Expedicion"] = val
            else:
                vals.append(f":{col}")
                params[col] = val

        if fecha_crea and fecha_crea in ent_cols:
            cols.append(f'"{fecha_crea}"')
            vals.append("NOW()")

        if fecha_act and fecha_act in ent_cols:
            cols.append(f'"{fecha_act}"')
            vals.append("NOW()")

        q = text(f"""
            INSERT INTO {ENT_FULL} ({", ".join(cols)})
            VALUES ({", ".join(vals)})
            RETURNING "{pk_col}";
        """)
        new_id = db.execute(q, params).scalar()
        db.commit()
        return {"ok": True, "modo": "insert", "IdEntrevista": new_id}

    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Error guardando entrevista: {str(e)}")


@router.get("/por-registro/{id_registro_perso}")
def listar_por_registro(id_registro_perso: int, db: Session = Depends(get_db)):
    fk_cols = get_ent_fk_columns(db)
    ent_cols = get_columns(db, ENT_SCHEMA, ENT_TABLE)
    pk_col = get_ent_pk_column(db)
    fecha_crea, _ = get_audit_columns(db)

    # ✅ FIX: mismo orden robusto para listados
    if fecha_crea and fecha_crea in ent_cols:
        order_by = f'"{fecha_crea}" DESC NULLS LAST, "{pk_col}" DESC'
    else:
        order_by = f'"{pk_col}" DESC'

    where_fk = build_fk_where_clause(fk_cols)

    q = text(f"""
        SELECT *
        FROM {ENT_FULL}
        WHERE {where_fk}
        ORDER BY {order_by}
    """)
    rows = db.execute(q, {"id": id_registro_perso}).fetchall()
    data = [dict(r._mapping) for r in rows]

    return {"ok": True, "data": data, "datos": data}


# ─────────────────────────────────────────────
# ✅ NUEVO: OBSERVACIONES NÚCLEO FAMILIAR (GUARDAR/LEER)
# ─────────────────────────────────────────────

@router.get("/{id_registro_perso}/observaciones-nucleo-familiar")
def obtener_observaciones_nucleo_familiar(id_registro_perso: int, ObservacionesNucleoFamiliar: str, db: Session = Depends(get_db)):
    db.execute(
    text("""
        UPDATE "EntrevistaCandidato"
        SET "ObservacionesNucleoFamiliar" = :valor
        WHERE "IdRegistroPersonal" = :IdRegistroPersonal
    """),
    {"valor": ObservacionesNucleoFamiliar, "IdRegistroPersonal": id_registro_perso}
    )

    db.commit()
   
    return {
        "ok": True,
        "IdRegistroPersonal": id_registro_perso,
        "ObservacionesNucleoFamiliar": ObservacionesNucleoFamiliar,
    }


@router.put("/{id_registro_perso}/observaciones-nucleo-familiar")
def guardar_observaciones_nucleo_familiar(
    id_registro_perso: int,
    payload: ObservacionesNucleoFamiliarPayload,
    db: Session = Depends(get_db),
):
    ent_cols = get_columns(db, ENT_SCHEMA, ENT_TABLE)
    if "ObservacionesNucleoFamiliar" not in ent_cols:
        raise HTTPException(
            status_code=400,
            detail="La columna ObservacionesNucleoFamiliar no existe en EntrevistaCandidato.",
        )

    current = fetch_ultima_entrevista_por_registro(db, id_registro_perso)
    if not current:
        raise HTTPException(status_code=404, detail="No existe entrevista para este registro (EntrevistaCandidato).")

    pk_col = get_ent_pk_column(db)
    id_entrevista = current.get(pk_col)
    if not id_entrevista:
        raise HTTPException(status_code=404, detail="Entrevista no encontrada")

    patch = EntrevistaActualizar(ObservacionesNucleoFamiliar=payload.ObservacionesNucleoFamiliar)
    return actualizar_por_id(id_entrevista, patch, db)


# ─────────────────────────────────────────────
# ✅ NUEVAS RUTAS: EXACTAMENTE COMO EL FRONT LAS LLAMA
# ─────────────────────────────────────────────

@router.get("/{id_registro_perso}")
def obtener_ultima_por_registro_alias(id_registro_perso: int, db: Session = Depends(get_db)):
    """
    ✅ FRONT: GET /api/entrevistas-candidato/{idRegistro}
    Devuelve la última entrevista del registro.
    """
    current = fetch_ultima_entrevista_por_registro(db, id_registro_perso)
    if not current:
        raise HTTPException(status_code=404, detail="Entrevista no encontrada")
    return {"ok": True, "data": current}


@router.put("/{id_registro_perso}")
def actualizar_ultima_por_registro_alias(id_registro_perso: int, payload: EntrevistaActualizar, db: Session = Depends(get_db)):
    """
    ✅ FRONT (fallback): PUT /api/entrevistas-candidato/{idRegistro}
    Actualiza la ÚLTIMA entrevista por registro.
    """
    current = fetch_ultima_entrevista_por_registro(db, id_registro_perso)
    if not current:
        raise HTTPException(status_code=404, detail="Entrevista no encontrada")

    pk_col = get_ent_pk_column(db)
    id_entrevista = current.get(pk_col)
    if not id_entrevista:
        raise HTTPException(status_code=404, detail="Entrevista no encontrada")

    return actualizar_por_id(id_entrevista, payload, db)


@router.get("/{id_registro_perso}/decision-final")
def obtener_decision_final_alias(id_registro_perso: int, db: Session = Depends(get_db)):
    """
    ✅ FRONT: GET /api/entrevistas-candidato/{idRegistro}/decision-final
    """
    current = fetch_ultima_entrevista_por_registro(db, id_registro_perso)
    if not current:
        raise HTTPException(status_code=404, detail="Entrevista no encontrada")

    concepto = pick_current_value(current, ALIAS_MAP["ConceptoFinalS"])
    observ = pick_current_value(current, ALIAS_MAP["ObservacionesF"])
    entrev = pick_current_value(current, ALIAS_MAP["EntrevistadorPo"])

    return {
        "ok": True,
        "IdRegistroPersonal": id_registro_perso,
        "ConceptoFinalSeleccion": concepto,
        "ObservacionesFinales": observ,
        "EntrevistadorPor": entrev,
    }


@router.put("/{id_registro_perso}/decision-final")
def actualizar_decision_final_alias(id_registro_perso: int, payload: DecisionFinalPayload, db: Session = Depends(get_db)):
    """
    ✅ FRONT: PUT /api/entrevistas-candidato/{idRegistro}/decision-final
    Actualiza la decisión final en la ÚLTIMA entrevista por registro.
    """
    current = fetch_ultima_entrevista_por_registro(db, id_registro_perso)
    if not current:
        raise HTTPException(status_code=404, detail="Entrevista no encontrada")

    pk_col = get_ent_pk_column(db)
    id_entrevista = current.get(pk_col)
    if not id_entrevista:
        raise HTTPException(status_code=404, detail="Entrevista no encontrada")

    concepto = payload.ConceptoFinalSeleccion or payload.ConceptoFinalS
    observ = payload.ObservacionesFinales or payload.ObservacionesF
    entrev = payload.EntrevistadorPor or payload.EntrevistadorPo

    patch = EntrevistaActualizar(
        ConceptoFinalS=concepto,
        ObservacionesF=observ,
        EntrevistadorPo=entrev,
    )
    return actualizar_por_id(id_entrevista, patch, db)


# ─────────────────────────────────────────────
# ✅ RUTAS POR ID DE ENTREVISTA (SE MUEVEN A /id/ PARA NO CHOCAR)
# ─────────────────────────────────────────────

@router.get("/id/{id_entrevista}")
def obtener_por_id(id_entrevista: int, db: Session = Depends(get_db)):
    pk_col = get_ent_pk_column(db)
    q = text(f'SELECT * FROM {ENT_FULL} WHERE "{pk_col}" = :id')
    row = db.execute(q, {"id": id_entrevista}).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Entrevista no encontrada")
    return {"ok": True, "data": dict(row._mapping)}


@router.put("/id/{id_entrevista}")
def actualizar_por_id(id_entrevista: int, payload: EntrevistaActualizar, db: Session = Depends(get_db)):
    """
    ✅ UPDATE por IdEntrevista (para modo Editar desde el 👁️ del historial).
    """
    try:
        ent_cols = get_columns(db, ENT_SCHEMA, ENT_TABLE)
        pk_col = get_ent_pk_column(db)
        _, fecha_act = get_audit_columns(db)

        exists = db.execute(
            text(f'SELECT 1 FROM {ENT_FULL} WHERE "{pk_col}" = :id'),
            {"id": id_entrevista},
        ).fetchone()
        if not exists:
            raise HTTPException(status_code=404, detail="Entrevista no encontrada")

        data = model_dump(payload, exclude_unset=True)

        # normalizar inputs alternos (si llegan con nombre largo)
        if data.get("ConceptoFinalSeleccion") is not None and data.get("ConceptoFinalS") is None:
            data["ConceptoFinalS"] = data["ConceptoFinalSeleccion"]
        if data.get("ObservacionesFinales") is not None and data.get("ObservacionesF") is None:
            data["ObservacionesF"] = data["ObservacionesFinales"]
        if data.get("EntrevistadorPor") is not None and data.get("EntrevistadorPo") is None:
            data["EntrevistadorPo"] = data["EntrevistadorPor"]
        if data.get("HaTenidoAccidentes") is not None and data.get("HaTenidoAccide") is None:
            data["HaTenidoAccide"] = data["HaTenidoAccidentes"]

        # ✅ NUEVO: Patologías normalización (PUT)
        if data.get("HaTenidoPatologias") is not None and data.get("HaTenidoPatolo") is None:
            data["HaTenidoPatolo"] = data["HaTenidoPatologias"]
        if data.get("HaTenidoPatolo") is not None and data.get("HaTenidoPatologias") is None:
            data["HaTenidoPatologias"] = data["HaTenidoPatolo"]

        pat_bool = data.get("HaTenidoPatologias")
        if pat_bool is None:
            pat_bool = data.get("HaTenidoPatolo")

        if pat_bool is False:
            data["PatologiaCual"] = None
        elif pat_bool is None and data.get("PatologiaCual") is not None and str(data.get("PatologiaCual")).strip() != "":
            # si mandan solo detalle, asumimos true
            data["HaTenidoPatologias"] = True
            data["HaTenidoPatolo"] = True

        set_parts = []
        params: Dict[str, Any] = {"id": id_entrevista}

        for incoming_key, val in data.items():
            col = resolve_column(ent_cols, incoming_key)
            if not col:
                continue

            if col == "Expedicion":
                val = normalize_date_value(val)
                set_parts.append(
                    '"Expedicion" = CASE WHEN :Expedicion IS NULL THEN NULL ELSE CAST(:Expedicion AS date) END'
                )
                params["Expedicion"] = val
            else:
                set_parts.append(f'"{col}" = :{col}')
                params[col] = val

        if fecha_act and fecha_act in ent_cols:
            set_parts.append(f'"{fecha_act}" = NOW()')

        if not set_parts:
            return {"ok": True, "message": "Nada para actualizar", "IdEntrevista": id_entrevista}

        q = text(f"""
            UPDATE {ENT_FULL}
            SET {", ".join(set_parts)}
            WHERE "{pk_col}" = :id
            RETURNING "{pk_col}";
        """)
        updated_id = db.execute(q, params).scalar()
        db.commit()
        return {"ok": True, "modo": "update", "IdEntrevista": updated_id}

    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Error actualizando entrevista: {str(e)}")


# ✅ Se dejan estas rutas tal cual estaban (compatibilidad)
@router.get("/por-registro/{id_registro_perso}/decision-final")
def obtener_decision_final(id_registro_perso: int, db: Session = Depends(get_db)):
    current = fetch_ultima_entrevista_por_registro(db, id_registro_perso)
    if not current:
        raise HTTPException(status_code=404, detail="Entrevista no encontrada")

    concepto = pick_current_value(current, ALIAS_MAP["ConceptoFinalS"])
    observ = pick_current_value(current, ALIAS_MAP["ObservacionesF"])
    entrev = pick_current_value(current, ALIAS_MAP["EntrevistadorPo"])

    return {
        "ok": True,
        "IdRegistroPersonal": id_registro_perso,
        "ConceptoFinalSeleccion": concepto,
        "ObservacionesFinales": observ,
        "EntrevistadorPor": entrev,
    }


@router.put("/por-registro/{id_registro_perso}/decision-final")
def actualizar_decision_final(id_registro_perso: int, payload: DecisionFinalPayload, db: Session = Depends(get_db)):
    current = fetch_ultima_entrevista_por_registro(db, id_registro_perso)
    if not current:
        raise HTTPException(status_code=404, detail="Entrevista no encontrada")

    pk_col = get_ent_pk_column(db)
    id_entrevista = current.get(pk_col)
    if not id_entrevista:
        raise HTTPException(status_code=404, detail="Entrevista no encontrada")

    concepto = payload.ConceptoFinalSeleccion or payload.ConceptoFinalS
    observ = payload.ObservacionesFinales or payload.ObservacionesF
    entrev = payload.EntrevistadorPor or payload.EntrevistadorPo

    patch = EntrevistaActualizar(
        ConceptoFinalS=concepto,
        ObservacionesF=observ,
        EntrevistadorPo=entrev,
    )
    return actualizar_por_id(id_entrevista, patch, db)


@router.put("/por-registro/{id_registro_perso}")
def actualizar_ultima_por_registro(id_registro_perso: int, payload: EntrevistaActualizar, db: Session = Depends(get_db)):
    current = fetch_ultima_entrevista_por_registro(db, id_registro_perso)
    if not current:
        raise HTTPException(status_code=404, detail="Entrevista no encontrada")

    pk_col = get_ent_pk_column(db)
    id_entrevista = current.get(pk_col)
    if not id_entrevista:
        raise HTTPException(status_code=404, detail="Entrevista no encontrada")

    return actualizar_por_id(id_entrevista, payload, db)
