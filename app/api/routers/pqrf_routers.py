"""API de PQRF - Fase 1: catálogos. Desarrollo exclusivo en QA."""

import re
from datetime import date, datetime, timedelta, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from infrastructure.db.deps import get_db
from infrastructure.security.auth_dependencies import get_current_user


router = APIRouter(prefix="/api/pqrf", tags=["PQRF"])


def _validar_acceso(db: Session, current: dict) -> None:
    """Permite acceso únicamente a usuarios activos y a la BD QA."""
    nombre_bd = db.execute(text("SELECT current_database()")).scalar_one()

    if nombre_bd != "LA_PERFECCION_QA":
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="PQRF en desarrollo: conexión distinta de LA_PERFECCION_QA.",
        )

    usuario = current.get("usuario") if isinstance(current, dict) else None

    if usuario is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Sesión sin usuario válido.",
        )

    if (getattr(usuario, "HashEstado", None) or "").strip().upper() != "ACTIVO":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="El usuario está inactivo.",
        )


@router.get("/catalogos/tipos")
def listar_tipos(
    db: Session = Depends(get_db),
    current: dict = Depends(get_current_user),
):
    _validar_acceso(db, current)

    filas = db.execute(text("""
        SELECT
            "IdTipoPQRF" AS id,
            "NombreTipo" AS nombre
        FROM public."TipoPQRF"
        WHERE "Activo" = TRUE
        ORDER BY "IdTipoPQRF"
    """)).mappings().all()

    return [dict(fila) for fila in filas]


@router.get("/catalogos/procesos")
def listar_procesos(
    db: Session = Depends(get_db),
    current: dict = Depends(get_current_user),
):
    _validar_acceso(db, current)

    filas = db.execute(text("""
        SELECT
            "IdProcesoPQRF" AS id,
            "NombreProceso" AS nombre
        FROM public."ProcesoPQRF"
        WHERE "Activo" = TRUE
        ORDER BY "NombreProceso"
    """)).mappings().all()

    return [dict(fila) for fila in filas]


@router.get("/catalogos/correos")
def listar_correos(
    db: Session = Depends(get_db),
    current: dict = Depends(get_current_user),
):
    _validar_acceso(db, current)

    filas = db.execute(text("""
        SELECT
            "IdCorreoPQRF" AS id,
            "Correo" AS correo
        FROM public."CorreoPQRF"
        WHERE "Activo" = TRUE
        ORDER BY "Correo"
    """)).mappings().all()

    return [dict(fila) for fila in filas]


@router.get("/catalogos/clientes")
def listar_clientes(
    buscar: str = "",
    db: Session = Depends(get_db),
    current: dict = Depends(get_current_user),
):
    _validar_acceso(db, current)

    termino = buscar.strip()

    if len(termino) > 100:
        raise HTTPException(
            status_code=422,
            detail="El texto de búsqueda es demasiado largo.",
        )

    filas = db.execute(text("""
        SELECT
            "IdCliente" AS id,
            TRIM(
                REPLACE(
                    REPLACE("Nombre", CHR(13), ' '),
                    CHR(10), ' '
                )
            ) AS nombre
        FROM public."Cliente"
        WHERE "Activo" = TRUE
          AND "Nombre" ILIKE :buscar
        ORDER BY "Nombre", "IdCliente"
    """), {"buscar": f"%{termino}%"}).mappings().all()

    return [dict(fila) for fila in filas]


@router.get("/catalogos/responsables")
def listar_responsables(
    db: Session = Depends(get_db),
    current: dict = Depends(get_current_user),
):
    _validar_acceso(db, current)

    filas = db.execute(text("""
        SELECT
            "IdUsuario" AS id,
            "NombreUsuario" AS nombre,
            "CorreoCorporativo" AS correo
        FROM public."Usuario"
        WHERE UPPER(TRIM(COALESCE("HashEstado", ''))) = 'ACTIVO'
        ORDER BY "NombreUsuario"
    """)).mappings().all()

    return [
        {
            **dict(fila),
            "id": str(fila["id"]),
        }
        for fila in filas
    ]
# Fase 2: registro de PQRF e historial en una sola transacción.
class CrearPQRF(BaseModel):
    id_tipo_pqrf: int = Field(gt=0)
    correo_remitente: str = Field(min_length=3, max_length=180)
    nombre_remitente: str = Field(min_length=1, max_length=200)
    id_cliente: int = Field(gt=0)
    descripcion_pqrf: str = Field(min_length=1, max_length=20000)
    id_proceso_pqrf: int = Field(gt=0)
    id_correo_pqrf: int = Field(gt=0)
    id_usuario_responsable: UUID | None = None

    @field_validator('correo_remitente', 'nombre_remitente', 'descripcion_pqrf')
    @classmethod
    def no_vacio(cls, valor: str) -> str:
        valor = valor.strip()
        if not valor:
            raise ValueError('Este campo no puede estar vacío.')
        return valor

    @field_validator('correo_remitente')
    @classmethod
    def correo_valido(cls, valor: str) -> str:
        if not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+', valor):
            raise ValueError('Correo electrónico no válido.')
        return valor


@router.post('', status_code=status.HTTP_201_CREATED)
def registrar_pqrf(
    datos: CrearPQRF,
    db: Session = Depends(get_db),
    current: dict = Depends(get_current_user),
):
    _validar_acceso(db, current)
    try:
        id_registrador = UUID(str(current['usuario'].IdUsuario))
    except (KeyError, AttributeError, ValueError, TypeError) as exc:
        raise HTTPException(status_code=401, detail='Sesión sin usuario válido.') from exc

    catalogos = (
        ('TipoPQRF', 'IdTipoPQRF', datos.id_tipo_pqrf, 'Tipo de PQRF'),
        ('ProcesoPQRF', 'IdProcesoPQRF', datos.id_proceso_pqrf, 'Proceso'),
        ('CorreoPQRF', 'IdCorreoPQRF', datos.id_correo_pqrf, 'Correo destinatario'),
        ('Cliente', 'IdCliente', datos.id_cliente, 'Cliente'),
    )
    for tabla, columna, identificador, etiqueta in catalogos:
        existe = db.execute(
            text(f'SELECT 1 FROM public."{tabla}" WHERE "{columna}" = :id AND "Activo" = TRUE'),
            {'id': identificador},
        ).scalar_one_or_none()
        if existe is None:
            raise HTTPException(status_code=422, detail=f'{etiqueta} no existe o está inactivo.')

    # La asignación inicial se determina exclusivamente por el proceso elegido.
    # No se acepta un responsable arbitrario enviado por el cliente.
    if datos.id_usuario_responsable is not None:
        raise HTTPException(status_code=422, detail='El responsable se asigna automáticamente según el proceso.')
    responsable_proceso = db.execute(text('''
        SELECT r."IdUsuarioResponsable"
        FROM public."ResponsableProcesoPQRF" r
        JOIN public."Usuario" u ON u."IdUsuario" = r."IdUsuarioResponsable"
        WHERE r."IdProcesoPQRF" = :proceso
          AND UPPER(TRIM(COALESCE(u."HashEstado", ''))) = 'ACTIVO'
    '''), {'proceso': datos.id_proceso_pqrf}).scalar_one_or_none()
    # Evita registrar solicitudes sin destino gestionable por error de parametrización.
    if responsable_proceso is None:
        raise HTTPException(status_code=409, detail='El proceso no tiene un responsable activo configurado en QA.')

    try:
        id_pqrf = db.execute(text('''
            INSERT INTO public."PQRF" (
                "IdTipoPQRF", "CorreoRemitente", "NombreRemitente",
                "IdCliente", "DescripcionPQRF", "IdProcesoPQRF",
                "IdCorreoPQRF", "IdUsuarioRegistro", "IdUsuarioResponsable", "Estado"
            ) VALUES (
                :tipo, :correo, :nombre, :cliente, :descripcion,
                :proceso, :destinatario, :registrador, :responsable, 'ABIERTA'
            ) RETURNING "IdPQRF"
        '''), {
            'tipo': datos.id_tipo_pqrf,
            'correo': datos.correo_remitente,
            'nombre': datos.nombre_remitente,
            'cliente': datos.id_cliente,
            'descripcion': datos.descripcion_pqrf,
            'proceso': datos.id_proceso_pqrf,
            'destinatario': datos.id_correo_pqrf,
            'registrador': id_registrador,
            'responsable': responsable_proceso,
        }).scalar_one()

        db.execute(text('''
            INSERT INTO public."HistorialPQRF" (
                "IdPQRF", "IdUsuario", "TipoMovimiento",
                "EstadoAnterior", "EstadoNuevo", "Observacion"
            ) VALUES (
                :pqrf, :usuario, 'CREACION', NULL, 'ABIERTA',
                'Registro inicial de PQRF'
            )
        '''), {'pqrf': id_pqrf, 'usuario': id_registrador})
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail='Conflicto con una restricción de la base de datos.') from exc
    except Exception:
        db.rollback()
        raise

    return {
        'id': id_pqrf,
        'estado': 'ABIERTA',
        'id_usuario_responsable': str(responsable_proceso),
        'asignacion_pendiente': False,
        'mensaje': 'PQRF registrada correctamente en QA.',
    }

# Fase 3: consultas personales. El usuario se obtiene únicamente de la sesión.
def _usuario_actual_pqrf(current: dict) -> UUID:
    try:
        return UUID(str(current["usuario"].IdUsuario))
    except (KeyError, AttributeError, ValueError, TypeError) as exc:
        raise HTTPException(status_code=401, detail="Sesión sin usuario válido.") from exc


_CONSULTA_PERSONAL_PQRF = """
    SELECT
        p."IdPQRF" AS id,
        p."FechaPQRF" AS fecha_pqrf,
        p."Estado" AS estado,
        p."NombreRemitente" AS nombre_remitente,
        p."CorreoRemitente" AS correo_remitente,
        p."DescripcionPQRF" AS descripcion_pqrf,
        p."IdCliente" AS id_cliente,
        p."IdTipoPQRF" AS id_tipo_pqrf,
        p."IdProcesoPQRF" AS id_proceso_pqrf,
        p."IdCorreoPQRF" AS id_correo_pqrf,
        p."IdUsuarioRegistro" AS id_usuario_registro,
        p."IdUsuarioResponsable" AS id_usuario_responsable,
  (SELECT MIN(g."FechaGestion") FROM public."GestionPQRF" g
   WHERE g."IdPQRF" = p."IdPQRF") AS fecha_primera_respuesta,
        p."FechaCreacion" AS fecha_creacion,
        p."FechaActualizacion" AS fecha_actualizacion,
        TRIM(REPLACE(REPLACE(c."Nombre", CHR(13), ' '), CHR(10), ' ')) AS cliente,
        t."NombreTipo" AS tipo_pqrf,
        pr."NombreProceso" AS proceso,
        co."Correo" AS correo_destinatario,
        ur."NombreUsuario" AS usuario_registro,
        ua."NombreUsuario" AS usuario_responsable,
        EXISTS (
            SELECT 1 FROM public."ResponsableProcesoPQRF" rp
            WHERE rp."IdProcesoPQRF" = p."IdProcesoPQRF"
              AND rp."IdUsuarioResponsable" = :usuario
        ) AS es_gerente_proceso
    FROM public."PQRF" p
    JOIN public."Cliente" c ON c."IdCliente" = p."IdCliente"
    JOIN public."TipoPQRF" t ON t."IdTipoPQRF" = p."IdTipoPQRF"
    JOIN public."ProcesoPQRF" pr ON pr."IdProcesoPQRF" = p."IdProcesoPQRF"
    JOIN public."CorreoPQRF" co ON co."IdCorreoPQRF" = p."IdCorreoPQRF"
    JOIN public."Usuario" ur ON ur."IdUsuario" = p."IdUsuarioRegistro"
    LEFT JOIN public."Usuario" ua ON ua."IdUsuario" = p."IdUsuarioResponsable"
    WHERE {filtro}
    ORDER BY p."FechaCreacion" DESC, p."IdPQRF" DESC
    LIMIT :limite OFFSET :desplazamiento
"""


def _consultar_pqrf_personales(
    db: Session, campo: str, usuario: UUID, limite: int, desplazamiento: int
):
    # Lista blanca: nunca se interpolan columnas enviadas por el frontend.
    filtros = {
        "registradas": 'p."IdUsuarioRegistro" = :usuario',
        "asignadas": 'p."IdUsuarioResponsable" = :usuario',
        "delegadas": '''EXISTS (
            SELECT 1 FROM public."HistorialPQRF" hd
            WHERE hd."IdPQRF" = p."IdPQRF"
              AND hd."TipoMovimiento" = 'REASIGNACION'
              AND hd."IdUsuario" = :usuario
        ) AND EXISTS (
            SELECT 1 FROM public."ResponsableProcesoPQRF" rp
            WHERE rp."IdProcesoPQRF" = p."IdProcesoPQRF"
              AND rp."IdUsuarioResponsable" = :usuario
        )''', 
    }
    if campo not in filtros:
        raise ValueError("Tipo de consulta PQRF no permitido.")
    filas = db.execute(
        text(_CONSULTA_PERSONAL_PQRF.format(filtro=filtros[campo])),
        {"usuario": usuario, "limite": limite, "desplazamiento": desplazamiento},
    ).mappings().all()
    return [
        {
            **dict(fila),
            "id_usuario_registro": str(fila["id_usuario_registro"]),
            "id_usuario_responsable": (
                str(fila["id_usuario_responsable"])
                if fila["id_usuario_responsable"] is not None else None
            ),
        }
        for fila in filas
    ]


@router.get("/mis-registradas")
def mis_pqrf_registradas(
    limite: int = 50,
    desplazamiento: int = 0,
    db: Session = Depends(get_db),
    current: dict = Depends(get_current_user),
):
    _validar_acceso(db, current)
    if not 1 <= limite <= 100 or desplazamiento < 0:
        raise HTTPException(status_code=422, detail="Paginación no válida.")
    return _consultar_pqrf_personales(
        db, "registradas", _usuario_actual_pqrf(current), limite, desplazamiento
    )


@router.get("/mis-asignadas")
def mis_pqrf_asignadas(
    limite: int = 50,
    desplazamiento: int = 0,
    db: Session = Depends(get_db),
    current: dict = Depends(get_current_user),
):
    _validar_acceso(db, current)
    if not 1 <= limite <= 100 or desplazamiento < 0:
        raise HTTPException(status_code=422, detail="Paginación no válida.")
    return _consultar_pqrf_personales(
        db, "asignadas", _usuario_actual_pqrf(current), limite, desplazamiento
    )

@router.get("/mis-delegadas")
def mis_pqrf_delegadas(
    limite: int = 50,
    desplazamiento: int = 0,
    db: Session = Depends(get_db),
    current: dict = Depends(get_current_user),
):
    _validar_acceso(db, current)
    if not 1 <= limite <= 100 or desplazamiento < 0:
        raise HTTPException(status_code=422, detail="Paginación no válida.")
    return _consultar_pqrf_personales(
        db, "delegadas", _usuario_actual_pqrf(current), limite, desplazamiento
    )


# Fase 3B: reasignación por el gerente configurado del proceso.
class ReasignarPQRF(BaseModel):
    id_usuario_destino: UUID
    motivo: str = Field(min_length=5, max_length=1000)

    @field_validator("motivo")
    @classmethod
    def validar_motivo(cls, valor: str) -> str:
        valor = valor.strip()
        if len(valor) < 5:
            raise ValueError("Indique un motivo de al menos cinco caracteres.")
        return valor


@router.post("/{id_pqrf}/reasignar")
def reasignar_pqrf(
    id_pqrf: int,
    datos: ReasignarPQRF,
    db: Session = Depends(get_db),
    current: dict = Depends(get_current_user),
):
    """Solo el gerente del proceso reasigna PQRF abiertas; conserva historial."""
    _validar_acceso(db, current)
    usuario = _usuario_actual_pqrf(current)
    if id_pqrf <= 0:
        raise HTTPException(status_code=422, detail="Identificador de PQRF no válido.")

    try:
        pqrf = db.execute(text('''
            SELECT "Estado" AS estado, "IdProcesoPQRF" AS proceso,
                   "IdUsuarioResponsable" AS responsable
            FROM public."PQRF" WHERE "IdPQRF" = :id FOR UPDATE
        '''), {"id": id_pqrf}).mappings().first()
        if pqrf is None:
            raise HTTPException(status_code=404, detail="PQRF no encontrada.")
        if pqrf["estado"] != "ABIERTA":
            raise HTTPException(status_code=409, detail="Solo se pueden reasignar PQRF ABIERTAS.")

        gerente = db.execute(text('''
            SELECT "IdUsuarioResponsable" FROM public."ResponsableProcesoPQRF"
            WHERE "IdProcesoPQRF" = :proceso
        '''), {"proceso": pqrf["proceso"]}).scalar_one_or_none()
        if gerente is None or gerente != usuario:
            raise HTTPException(status_code=403, detail="Solo el gerente configurado del proceso puede reasignar esta PQRF.")
        if pqrf["responsable"] == datos.id_usuario_destino:
            raise HTTPException(status_code=409, detail="La PQRF ya está asignada a ese usuario.")

        destino = db.execute(text('''
            SELECT "NombreUsuario" AS nombre FROM public."Usuario"
            WHERE "IdUsuario" = :usuario
              AND UPPER(TRIM(COALESCE("HashEstado", ''))) = 'ACTIVO'
        '''), {"usuario": datos.id_usuario_destino}).mappings().first()
        if destino is None:
            raise HTTPException(status_code=422, detail="El usuario de destino no existe o está inactivo.")

        anterior = None
        if pqrf["responsable"] is not None:
            anterior = db.execute(text('''
                SELECT "NombreUsuario" FROM public."Usuario"
                WHERE "IdUsuario" = :usuario
            '''), {"usuario": pqrf["responsable"]}).scalar_one_or_none()

        db.execute(text('''
            UPDATE public."PQRF"
            SET "IdUsuarioResponsable" = :destino,
                "FechaActualizacion" = CURRENT_TIMESTAMP
            WHERE "IdPQRF" = :id
        '''), {"id": id_pqrf, "destino": datos.id_usuario_destino})

        observacion = (
            f"Reasignación de {anterior or 'SIN RESPONSABLE'} "
            f"a {destino['nombre']}. Motivo: {datos.motivo}"
        )
        db.execute(text('''
            INSERT INTO public."HistorialPQRF" (
                "IdPQRF", "IdUsuario", "TipoMovimiento",
                "EstadoAnterior", "EstadoNuevo", "Observacion"
            ) VALUES (:id, :usuario, 'REASIGNACION', 'ABIERTA', 'ABIERTA', :observacion)
        '''), {"id": id_pqrf, "usuario": usuario, "observacion": observacion})
        db.commit()
    except HTTPException:
        db.rollback()
        raise
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="Restricción de base de datos al reasignar. Verifique TipoMovimiento en QA.") from exc
    except Exception:
        db.rollback()
        raise

    return {
        "id": id_pqrf, "estado": "ABIERTA",
        "id_usuario_responsable": str(datos.id_usuario_destino),
        "usuario_responsable": destino["nombre"],
        "mensaje": "PQRF reasignada correctamente en QA.",
    }


# Fase 4: respuesta del responsable asignado, con trazabilidad transaccional.
class ResponderPQRF(BaseModel):
    analisis_gestion: str = Field(min_length=1, max_length=20000)
    respuesta_pqrf: str = Field(min_length=1, max_length=20000)
    acciones_realizadas: str | None = Field(default=None, max_length=20000)

    @field_validator("analisis_gestion", "respuesta_pqrf")
    @classmethod
    def validar_texto_obligatorio(cls, valor: str) -> str:
        valor = valor.strip()
        if not valor:
            raise ValueError("Este campo no puede estar vacío.")
        return valor

    @field_validator("acciones_realizadas")
    @classmethod
    def limpiar_acciones(cls, valor: str | None) -> str | None:
        return valor.strip() or None if valor is not None else None


@router.post("/{id_pqrf}/responder")
def responder_pqrf(
    id_pqrf: int,
    datos: ResponderPQRF,
    db: Session = Depends(get_db),
    current: dict = Depends(get_current_user),
):
    _validar_acceso(db, current)
    usuario = _usuario_actual_pqrf(current)
    if id_pqrf <= 0:
        raise HTTPException(status_code=422, detail="Identificador de PQRF no válido.")

    try:
        # Bloqueo de fila para impedir dos respuestas simultáneas.
        pqrf = db.execute(text('''
            SELECT "Estado" AS estado,
                   "IdUsuarioResponsable" AS responsable
            FROM public."PQRF"
            WHERE "IdPQRF" = :id
            FOR UPDATE
        '''), {"id": id_pqrf}).mappings().first()

        if pqrf is None:
            raise HTTPException(status_code=404, detail="PQRF no encontrada.")
        if pqrf["responsable"] != usuario:
            raise HTTPException(status_code=403, detail="Solo el responsable asignado puede responder esta PQRF.")
        if pqrf["estado"] != "ABIERTA":
            raise HTTPException(status_code=409, detail="Solo se pueden responder PQRF en estado ABIERTA.")

        id_gestion = db.execute(text('''
            INSERT INTO public."GestionPQRF" (
                "IdPQRF", "IdUsuarioGestion", "AnalisisGestion",
                "RespuestaPQRF", "AccionesRealizadas"
            ) VALUES (
                :id, :usuario, :analisis, :respuesta, :acciones
            ) RETURNING "IdGestionPQRF"
        '''), {
            "id": id_pqrf,
            "usuario": usuario,
            "analisis": datos.analisis_gestion,
            "respuesta": datos.respuesta_pqrf,
            "acciones": datos.acciones_realizadas,
        }).scalar_one()

        db.execute(text('''
            UPDATE public."PQRF"
            SET "Estado" = 'RESPONDIDA',
                "FechaActualizacion" = CURRENT_TIMESTAMP
            WHERE "IdPQRF" = :id
        '''), {"id": id_pqrf})

        db.execute(text('''
            INSERT INTO public."HistorialPQRF" (
                "IdPQRF", "IdUsuario", "TipoMovimiento",
                "EstadoAnterior", "EstadoNuevo", "Observacion"
            ) VALUES (
                :id, :usuario, 'RESPUESTA', 'ABIERTA', 'RESPONDIDA',
                'Respuesta registrada por el responsable asignado'
            )
        '''), {"id": id_pqrf, "usuario": usuario})
        db.commit()
    except HTTPException:
        db.rollback()
        raise
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="Conflicto con una restricción de la base de datos.") from exc
    except Exception:
        db.rollback()
        raise

    return {
        "id": id_pqrf,
        "id_gestion": id_gestion,
        "estado": "RESPONDIDA",
        "mensaje": "PQRF respondida correctamente en QA.",
    }

# Fase 5: consulta de respuesta, trazabilidad y cierre por quien registró la PQRF.
def _pqrf_visible_para_usuario(db: Session, id_pqrf: int, usuario: UUID):
    if id_pqrf <= 0:
        raise HTTPException(status_code=422, detail="Identificador de PQRF no válido.")
    pqrf = db.execute(text('''
        SELECT "IdPQRF" AS id, "Estado" AS estado,
               "IdUsuarioRegistro" AS registrador,
               "IdUsuarioResponsable" AS responsable
        FROM public."PQRF"
        WHERE "IdPQRF" = :id
    '''), {"id": id_pqrf}).mappings().first()
    if pqrf is None:
        raise HTTPException(status_code=404, detail="PQRF no encontrada.")
    if usuario not in (pqrf["registrador"], pqrf["responsable"]):
        delegado = db.execute(text('''
            SELECT 1
            FROM public."PQRF" p
            JOIN public."ResponsableProcesoPQRF" rp
              ON rp."IdProcesoPQRF" = p."IdProcesoPQRF"
             AND rp."IdUsuarioResponsable" = :usuario
            WHERE p."IdPQRF" = :id
              AND EXISTS (
                SELECT 1 FROM public."HistorialPQRF" h
                WHERE h."IdPQRF" = p."IdPQRF"
                  AND h."TipoMovimiento" = 'REASIGNACION'
                  AND h."IdUsuario" = :usuario
              )
        '''), {"id": id_pqrf, "usuario": usuario}).scalar_one_or_none()
        if delegado is None:
            raise HTTPException(status_code=403, detail="No tiene acceso a esta PQRF.")
    return pqrf


@router.get("/{id_pqrf}/respuesta")
def consultar_respuesta_pqrf(
    id_pqrf: int,
    db: Session = Depends(get_db),
    current: dict = Depends(get_current_user),
):
    _validar_acceso(db, current)
    usuario = _usuario_actual_pqrf(current)
    _pqrf_visible_para_usuario(db, id_pqrf, usuario)
    filas = db.execute(text('''
        SELECT g."IdGestionPQRF" AS id_gestion,
               g."IdPQRF" AS id_pqrf,
               g."IdUsuarioGestion" AS id_usuario_gestion,
               u."NombreUsuario" AS usuario_gestion,
               g."AnalisisGestion" AS analisis_gestion,
               g."RespuestaPQRF" AS respuesta_pqrf,
               g."AccionesRealizadas" AS acciones_realizadas,
               g."FechaGestion" AS fecha_gestion
        FROM public."GestionPQRF" g
        JOIN public."Usuario" u ON u."IdUsuario" = g."IdUsuarioGestion"
        WHERE g."IdPQRF" = :id
        ORDER BY g."FechaGestion" DESC, g."IdGestionPQRF" DESC
    '''), {"id": id_pqrf}).mappings().all()
    return [dict(fila) for fila in filas]


@router.get("/{id_pqrf}/historial")
def consultar_historial_pqrf(
    id_pqrf: int,
    db: Session = Depends(get_db),
    current: dict = Depends(get_current_user),
):
    _validar_acceso(db, current)
    usuario = _usuario_actual_pqrf(current)
    _pqrf_visible_para_usuario(db, id_pqrf, usuario)
    filas = db.execute(text('''
        SELECT h."IdHistorialPQRF" AS id_historial,
               h."IdPQRF" AS id_pqrf,
               h."IdUsuario" AS id_usuario,
               u."NombreUsuario" AS usuario,
               h."TipoMovimiento" AS tipo_movimiento,
               h."EstadoAnterior" AS estado_anterior,
               h."EstadoNuevo" AS estado_nuevo,
               h."Observacion" AS observacion,
               h."FechaMovimiento" AS fecha_movimiento
        FROM public."HistorialPQRF" h
        JOIN public."Usuario" u ON u."IdUsuario" = h."IdUsuario"
        WHERE h."IdPQRF" = :id
        ORDER BY h."FechaMovimiento" ASC, h."IdHistorialPQRF" ASC
    '''), {"id": id_pqrf}).mappings().all()
    return [dict(fila) for fila in filas]


@router.post("/{id_pqrf}/cerrar")
def cerrar_pqrf(
    id_pqrf: int,
    db: Session = Depends(get_db),
    current: dict = Depends(get_current_user),
):
    _validar_acceso(db, current)
    usuario = _usuario_actual_pqrf(current)
    if id_pqrf <= 0:
        raise HTTPException(status_code=422, detail="Identificador de PQRF no válido.")

    try:
        pqrf = db.execute(text('''
            SELECT "Estado" AS estado, "IdUsuarioRegistro" AS registrador
            FROM public."PQRF"
            WHERE "IdPQRF" = :id
            FOR UPDATE
        '''), {"id": id_pqrf}).mappings().first()
        if pqrf is None:
            raise HTTPException(status_code=404, detail="PQRF no encontrada.")
        if pqrf["registrador"] != usuario:
            raise HTTPException(
                status_code=403,
                detail="Solo el usuario que registró la PQRF puede cerrarla.",
            )
        if pqrf["estado"] != "RESPONDIDA":
            raise HTTPException(
                status_code=409,
                detail="Solo se pueden cerrar PQRF en estado RESPONDIDA.",
            )
        gestion = db.execute(text('''
            SELECT 1 FROM public."GestionPQRF" WHERE "IdPQRF" = :id LIMIT 1
        '''), {"id": id_pqrf}).scalar_one_or_none()
        if gestion is None:
            raise HTTPException(status_code=409, detail="La PQRF no tiene una respuesta registrada.")

        db.execute(text('''
            UPDATE public."PQRF"
            SET "Estado" = 'CERRADA', "FechaActualizacion" = CURRENT_TIMESTAMP
            WHERE "IdPQRF" = :id
        '''), {"id": id_pqrf})
        db.execute(text('''
            INSERT INTO public."HistorialPQRF" (
                "IdPQRF", "IdUsuario", "TipoMovimiento",
                "EstadoAnterior", "EstadoNuevo", "Observacion"
            ) VALUES (
                :id, :usuario, 'CIERRE', 'RESPONDIDA', 'CERRADA',
                'Cierre de PQRF posterior a la respuesta del responsable'
            )
        '''), {"id": id_pqrf, "usuario": usuario})
        db.commit()
    except HTTPException:
        db.rollback()
        raise
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=409, detail="Conflicto con una restricción de la base de datos."
        ) from exc
    except Exception:
        db.rollback()
        raise

    return {"id": id_pqrf, "estado": "CERRADA", "mensaje": "PQRF cerrada correctamente en QA."}

# Consultas globales PQRF para usuarios con rol SUPERADMIN (IdRol 5).
# Se valida contra UsuarioRoles y Roles en la BD QA, no por nombre ni UUID fijo.
# Solo lectura: no modifica las reglas operativas de PQRF.
ROL_SUPERADMIN_PQRF = 5


def _pqrf_admin(db: Session, current: dict) -> None:
    _validar_acceso(db, current)
    usuario_id = _usuario_actual_pqrf(current)
    autorizado = db.execute(text('''
        SELECT 1
        FROM public."UsuarioRoles" ur
        JOIN public."Roles" r ON r."IdRol" = ur."IdRol"
        WHERE ur."IdUsuario" = :usuario
          AND r."IdRol" = :rol
        LIMIT 1
    '''), {"usuario": usuario_id, "rol": ROL_SUPERADMIN_PQRF}).scalar_one_or_none()
    if autorizado is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Acceso exclusivo al panel PQRF de SUPERADMIN.",
        )

# Días calendario inclusivos según la fecha local de Colombia (UTC-5).
# Cuenta el día de registro y el día de primera respuesta, incluidos domingos y festivos.
_ZONA_HORARIA_PQRF = timezone(timedelta(hours=-5))


def _dias_calendario_respuesta(inicio, respuesta) -> int | None:
    if inicio is None or respuesta is None:
        return None

    def fecha_colombia(valor):
        if isinstance(valor, datetime):
            # Los timestamps sin zona se interpretan como hora local de Colombia.
            if valor.tzinfo is None:
                valor = valor.replace(tzinfo=_ZONA_HORARIA_PQRF)
            return valor.astimezone(_ZONA_HORARIA_PQRF).date()
        return valor

    fecha_inicio = fecha_colombia(inicio)
    fecha_respuesta = fecha_colombia(respuesta)
    return max(1, (fecha_respuesta - fecha_inicio).days + 1)


def _anexar_tiempo_respuesta(registro: dict) -> dict:
    registro['dias_respuesta'] = _dias_calendario_respuesta(
        registro.get('fecha_creacion'), registro.get('fecha_primera_respuesta'))
    return registro


@router.get('/general/catalogos/clientes')
def pqrf_general_clientes(
    db: Session = Depends(get_db), current: dict = Depends(get_current_user),
):
    _pqrf_admin(db, current)
    filas = db.execute(text('''SELECT "IdCliente" AS id,
        TRIM(REPLACE(REPLACE("Nombre", CHR(13), ' '), CHR(10), ' ')) AS nombre
        FROM public."Cliente" WHERE "Activo" = TRUE
        ORDER BY "Nombre", "IdCliente"''')).mappings().all()
    return [dict(fila) for fila in filas]


_PQRF_GENERAL_FROM = '''
 FROM public."PQRF" p
 JOIN public."Cliente" c ON c."IdCliente" = p."IdCliente"
 JOIN public."TipoPQRF" t ON t."IdTipoPQRF" = p."IdTipoPQRF"
 JOIN public."ProcesoPQRF" pr ON pr."IdProcesoPQRF" = p."IdProcesoPQRF"
 JOIN public."CorreoPQRF" co ON co."IdCorreoPQRF" = p."IdCorreoPQRF"
 JOIN public."Usuario" ur ON ur."IdUsuario" = p."IdUsuarioRegistro"
 LEFT JOIN public."Usuario" ua ON ua."IdUsuario" = p."IdUsuarioResponsable"
'''
_PQRF_GENERAL_SELECT = '''p."IdPQRF" AS id, p."FechaPQRF" AS fecha_pqrf,
 p."FechaCreacion" AS fecha_creacion, p."FechaActualizacion" AS fecha_actualizacion,
 (SELECT MIN(g."FechaGestion") FROM public."GestionPQRF" g
  WHERE g."IdPQRF" = p."IdPQRF") AS fecha_primera_respuesta,
 p."Estado" AS estado, p."NombreRemitente" AS nombre_remitente,
 p."CorreoRemitente" AS correo_remitente, p."DescripcionPQRF" AS descripcion_pqrf,
 p."IdCliente" AS id_cliente, c."Nombre" AS cliente,
 p."IdTipoPQRF" AS id_tipo_pqrf, t."NombreTipo" AS tipo_pqrf,
 p."IdProcesoPQRF" AS id_proceso_pqrf, pr."NombreProceso" AS proceso,
 co."Correo" AS correo_destinatario,
 ur."NombreUsuario" AS usuario_registro, ua."NombreUsuario" AS usuario_responsable,
 p."IdUsuarioRegistro" AS id_usuario_registro,
 p."IdUsuarioResponsable" AS id_usuario_responsable'''


def _pqrf_general_filters(busqueda, id_proceso, id_tipo, id_cliente, fecha_desde, fecha_hasta):
    parts, params = [], {}
    if len(busqueda) > 150 or (fecha_desde and fecha_hasta and fecha_desde > fecha_hasta):
        raise HTTPException(status_code=422, detail='Filtros inválidos.')
    if busqueda.strip():
        parts.append('''(CAST(p."IdPQRF" AS TEXT) ILIKE :q OR
          p."NombreRemitente" ILIKE :q OR c."Nombre" ILIKE :q OR
          ur."NombreUsuario" ILIKE :q OR COALESCE(ua."NombreUsuario", '') ILIKE :q)''')
        params['q'] = '%' + busqueda.strip() + '%'
    for key, column, value in (
        ('proceso', 'p."IdProcesoPQRF"', id_proceso),
        ('tipo', 'p."IdTipoPQRF"', id_tipo),
        ('cliente', 'p."IdCliente"', id_cliente),
    ):
        if value is not None:
            parts.append(column + ' = :' + key)
            params[key] = value
    if fecha_desde:
        parts.append('p."FechaPQRF" >= :desde')
        params['desde'] = fecha_desde
    if fecha_hasta:
        parts.append('p."FechaPQRF" < CAST(:hasta AS DATE) + INTERVAL \'1 day\'')
        params['hasta'] = fecha_hasta
    return ' AND '.join(parts) if parts else 'TRUE', params


def _pqrf_general_row(row):
    data = dict(row)
    for key in ('id_usuario_registro', 'id_usuario_responsable'):
        if data.get(key) is not None:
            data[key] = str(data[key])
    return _anexar_tiempo_respuesta(data)


@router.get('/general')
def pqrf_general(
    busqueda: str = '', id_proceso: int | None = None,
    id_tipo: int | None = None, id_cliente: int | None = None,
    fecha_desde: date | None = None, fecha_hasta: date | None = None,
    estado: str = '', pagina: int = 1, limite: int = 15,
    db: Session = Depends(get_db), current: dict = Depends(get_current_user),
):
    _pqrf_admin(db, current)
    if pagina < 1 or not 1 <= limite <= 100 or (estado and estado not in ('ABIERTA', 'RESPONDIDA', 'CERRADA')):
        raise HTTPException(status_code=422, detail='Estado o paginación inválidos.')
    where, params = _pqrf_general_filters(busqueda, id_proceso, id_tipo, id_cliente, fecha_desde, fecha_hasta)
    if estado:
        where += ' AND p."Estado" = :estado'
        params['estado'] = estado
    total = db.execute(text('SELECT COUNT(*) ' + _PQRF_GENERAL_FROM + ' WHERE ' + where), params).scalar_one()
    rows = db.execute(text('SELECT ' + _PQRF_GENERAL_SELECT + _PQRF_GENERAL_FROM +
        ' WHERE ' + where + ' ORDER BY p."FechaCreacion" DESC, p."IdPQRF" DESC LIMIT :limite OFFSET :offset'),
        {**params, 'limite': limite, 'offset': (pagina - 1) * limite}).mappings().all()
    return {'registros': [_pqrf_general_row(r) for r in rows], 'total': total,
            'pagina': pagina, 'paginas': max(1, (total + limite - 1) // limite)}


@router.get('/general/indicadores')
def pqrf_general_indicadores(
    busqueda: str = '', id_proceso: int | None = None,
    id_tipo: int | None = None, id_cliente: int | None = None,
    fecha_desde: date | None = None, fecha_hasta: date | None = None,
    db: Session = Depends(get_db), current: dict = Depends(get_current_user),
):
    _pqrf_admin(db, current)
    where, params = _pqrf_general_filters(busqueda, id_proceso, id_tipo, id_cliente, fecha_desde, fecha_hasta)
    base = _PQRF_GENERAL_FROM + ' WHERE ' + where
    def grouped(column, label, limit=''):
        sql = 'SELECT ' + column + ' AS nombre, COUNT(*) AS total ' + base + ' GROUP BY ' + column + ' ORDER BY total DESC ' + limit
        return [dict(r) for r in db.execute(text(sql), params).mappings().all()]
    estados = grouped('p."Estado"', 'estado')
    counts = {'ABIERTA': 0, 'RESPONDIDA': 0, 'CERRADA': 0}
    counts.update({r['nombre']: r['total'] for r in estados})
    monthly_sql = '''SELECT TO_CHAR(DATE_TRUNC('month', p."FechaPQRF"), 'YYYY-MM') AS mes,
      COUNT(*) AS total,
      COUNT(*) FILTER (WHERE p."Estado" = 'ABIERTA') AS abiertas,
      COUNT(*) FILTER (WHERE p."Estado" = 'RESPONDIDA') AS respondidas,
      COUNT(*) FILTER (WHERE p."Estado" = 'CERRADA') AS cerradas ''' + base + '''
      GROUP BY DATE_TRUNC('month', p."FechaPQRF") ORDER BY DATE_TRUNC('month', p."FechaPQRF")'''
    tiempos = db.execute(text('''SELECT p."FechaCreacion" AS fecha_creacion,
        (SELECT MIN(g."FechaGestion") FROM public."GestionPQRF" g
         WHERE g."IdPQRF" = p."IdPQRF") AS fecha_primera_respuesta
        ''' + base), params).mappings().all()
    dias = [_dias_calendario_respuesta(r['fecha_creacion'], r['fecha_primera_respuesta'])
            for r in tiempos if r['fecha_primera_respuesta'] is not None]
    return {'cantidad_con_respuesta': len(dias),
            'promedio_dias_respuesta': round(sum(dias) / len(dias), 2) if dias else None,
            'total': sum(counts.values()), 'totales': counts,
            'tipos': grouped('t."NombreTipo"', 'tipo'),
            'procesos': grouped('pr."NombreProceso"', 'proceso'),
            'clientes': grouped('c."Nombre"', 'cliente'),
            'mensual': [dict(r) for r in db.execute(text(monthly_sql), params).mappings().all()]}


@router.get('/general/{id_pqrf}')
def pqrf_general_detalle(
    id_pqrf: int, db: Session = Depends(get_db),
    current: dict = Depends(get_current_user),
):
    _pqrf_admin(db, current)
    if id_pqrf <= 0:
        raise HTTPException(status_code=422, detail='Identificador inválido.')
    row = db.execute(text('SELECT ' + _PQRF_GENERAL_SELECT + _PQRF_GENERAL_FROM +
        ' WHERE p."IdPQRF" = :id'), {'id': id_pqrf}).mappings().first()
    if row is None:
        raise HTTPException(status_code=404, detail='PQRF no encontrada.')
    gestiones = db.execute(text('''SELECT g."IdGestionPQRF" AS id_gestion,
      g."AnalisisGestion" AS analisis_gestion, g."RespuestaPQRF" AS respuesta_pqrf,
      g."AccionesRealizadas" AS acciones_realizadas, g."FechaGestion" AS fecha_gestion,
      u."NombreUsuario" AS usuario_gestion
      FROM public."GestionPQRF" g JOIN public."Usuario" u ON u."IdUsuario" = g."IdUsuarioGestion"
      WHERE g."IdPQRF" = :id ORDER BY g."FechaGestion", g."IdGestionPQRF"'''), {'id': id_pqrf}).mappings().all()
    historial = db.execute(text('''SELECT h."IdHistorialPQRF" AS id_historial,
      h."TipoMovimiento" AS tipo_movimiento, h."EstadoAnterior" AS estado_anterior,
      h."EstadoNuevo" AS estado_nuevo, h."Observacion" AS observacion,
      h."FechaMovimiento" AS fecha_movimiento, u."NombreUsuario" AS usuario
      FROM public."HistorialPQRF" h JOIN public."Usuario" u ON u."IdUsuario" = h."IdUsuario"
      WHERE h."IdPQRF" = :id ORDER BY h."FechaMovimiento", h."IdHistorialPQRF"'''), {'id': id_pqrf}).mappings().all()
    return {'pqrf': _pqrf_general_row(row), 'gestiones': [dict(g) for g in gestiones],
            'historial': [dict(h) for h in historial]}
