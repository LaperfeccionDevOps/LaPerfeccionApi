# ruff: noqa: B008, BLE001

from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    UploadFile,
    status,
)
from sqlalchemy import text
from sqlalchemy.orm import Session

from infrastructure.db.deps import get_db
from infrastructure.security.auth_dependencies import get_current_user
from services.paz_salvo_operaciones_pdf_service import (
    generar_paz_salvo_operaciones_pdf,
)


router = APIRouter(
    prefix="/api/operaciones/retiros",
    tags=["Operaciones - Retiros"],
)


STORAGE_BASE_DIR = Path("C:/LaPerfeccionStorage/rrll/retiros")
ID_TIPO_DOCUMENTO_PAZ_Y_SALVO = 2
ID_ESTADO_CONTRATADO = 25
ID_ESTADO_RETIRO_ABIERTO = 30
TAMANO_MAXIMO_PDF = 10 * 1024 * 1024
TAMANO_MAXIMO_EVIDENCIA = 10 * 1024 * 1024

TIPOS_EVIDENCIA_PAZ_SALVO = {
    "NOVEDADES_NOMINA",
    "FORMATO_DESCUENTO_VACUNAS",
    "CARNET_ACCESO",
    "LISTADO_HERRAMIENTAS",
    "PLANILLA_NOMINA",
}

OPCIONES_ENTREGA_GENERAL = {"NO APLICA", "ACEPTADO", "RECHAZADO"}
OPCIONES_CUMPLIMIENTO = {"NO APLICA", "CUMPLE", "NO CUMPLE"}
OPCIONES_SI_NO = {"SI", "NO"}
OPCIONES_ESTADO_PAZ_SALVO = {"ABIERTO", "CERRADO"}


ROL_ADMIN = 1
ROL_SUPER_ADMIN = 5
ROL_OPERACIONES = 6
ROL_DESARROLLADOR = 15

ROLES_GLOBALES = {
    ROL_ADMIN,
    ROL_SUPER_ADMIN,
    ROL_DESARROLLADOR,
}

PERMISO_OPERACIONES_RETIROS = "OPERACIONES_RETIROS"


def _roles_ids_actuales(current) -> set[int]:
    roles_ids = current.get("roles_ids") or []

    return {
        int(id_rol)
        for id_rol in roles_ids
        if str(id_rol).strip()
    }


def _permisos_actuales(current) -> set[str]:
    permisos = current.get("permisos") or []

    return {
        str(permiso).strip()
        for permiso in permisos
        if str(permiso).strip()
    }


def validar_acceso_operaciones_retiros(current) -> None:
    roles_ids = _roles_ids_actuales(current)
    permisos = _permisos_actuales(current)

    tiene_acceso = bool(
        roles_ids & ROLES_GLOBALES
        or ROL_OPERACIONES in roles_ids
        or PERMISO_OPERACIONES_RETIROS in permisos
    )

    if tiene_acceso:
        return

    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail={
            "mensaje": (
                "No tienes permiso para gestionar "
                "Retiros de Operaciones."
            ),
            "permisoRequerido": PERMISO_OPERACIONES_RETIROS,
        },
    )


def require_operaciones_retiros(
    current=Depends(get_current_user),
):
    validar_acceso_operaciones_retiros(current)

    return current


def _normalizar_usuario(usuario: str | None) -> str:
    valor = str(usuario or "").strip()
    return valor or "operaciones"


def _normalizar_texto_requerido(
    valor: str | None,
    nombre_campo: str,
) -> str:
    texto = str(valor or "").strip()

    if not texto:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"El campo {nombre_campo} es obligatorio.",
        )

    return texto


def _normalizar_texto_opcional(valor: str | None) -> str | None:
    texto = str(valor or "").strip()
    return texto or None


def _normalizar_opcion(
    valor: str | None,
    nombre_campo: str,
    opciones_validas: set[str],
) -> str:
    opcion = str(valor or "").strip().upper()

    if opcion not in opciones_validas:
        opciones = ", ".join(sorted(opciones_validas))
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"El campo {nombre_campo} contiene un valor no válido. "
                f"Opciones permitidas: {opciones}."
            ),
        )

    return opcion


def _validar_correo(correo: str | None) -> str:
    valor = _normalizar_texto_requerido(
        correo,
        "CorreoSupervisora",
    )

    dominio = valor.rsplit("@", 1)[-1] if "@" in valor else ""

    if "@" not in valor or "." not in dominio:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="El correo de la supervisora no tiene un formato válido.",
        )

    return valor


def _validar_valor_descuento(
    aplica_descuento: str,
    valor_descuento: Decimal | None,
) -> Decimal | None:
    if valor_descuento is not None and valor_descuento < 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="El valor del descuento no puede ser negativo.",
        )

    # El valor del descuento no es obligatorio.
    # Si no aplica descuento, cualquier valor recibido se descarta.
    if aplica_descuento == "NO":
        return None

    return valor_descuento


def _validar_archivo_pdf(archivo: UploadFile, contenido: bytes) -> None:
    nombre_original = str(archivo.filename or "").strip()

    if not nombre_original:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="El archivo de paz y salvo no tiene un nombre válido.",
        )

    extension = Path(nombre_original).suffix.lower()

    if extension != ".pdf":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="El paz y salvo debe cargarse en formato PDF.",
        )

    content_type = str(archivo.content_type or "").lower()

    if content_type not in {
        "application/pdf",
        "application/octet-stream",
        "",
    }:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="El tipo de archivo recibido no corresponde a un PDF.",
        )

    if not contenido:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="El archivo de paz y salvo está vacío.",
        )

    if len(contenido) > TAMANO_MAXIMO_PDF:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="El archivo supera el tamaño máximo permitido de 10 MB.",
        )

    if not contenido.startswith(b"%PDF"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="El archivo cargado no contiene una estructura PDF válida.",
        )


def _validar_evidencia(
    archivo: UploadFile,
    contenido: bytes,
    nombre_campo: str,
) -> tuple[str, str, str]:
    nombre_original = Path(str(archivo.filename or "")).name.strip()

    if not nombre_original:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"El archivo de {nombre_campo} no tiene un nombre válido.",
        )

    if not contenido:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"El archivo de {nombre_campo} está vacío.",
        )

    if len(contenido) > TAMANO_MAXIMO_EVIDENCIA:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=(
                f"El archivo de {nombre_campo} supera el tamaño máximo "
                "permitido de 10 MB."
            ),
        )

    extension = Path(nombre_original).suffix.lower()
    mime_type = str(
        archivo.content_type or "application/octet-stream"
    ).strip()

    return nombre_original, extension, mime_type


def _guardar_evidencia_paz_salvo(
    db: Session,
    *,
    id_paz_y_salvo: int,
    id_retiro_laboral: int,
    tipo_evidencia: str,
    archivo: UploadFile,
    contenido: bytes,
    usuario: str,
    carpeta_evidencias: Path,
) -> tuple[int, Path]:
    if tipo_evidencia not in TIPOS_EVIDENCIA_PAZ_SALVO:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Tipo de evidencia no permitido: {tipo_evidencia}.",
        )

    nombre_original, extension, mime_type = _validar_evidencia(
        archivo=archivo,
        contenido=contenido,
        nombre_campo=tipo_evidencia,
    )

    extension_guardado = extension or ".bin"
    nombre_guardado = (
        f"{tipo_evidencia.lower()}_"
        f"{id_retiro_laboral}_{uuid4().hex}{extension_guardado}"
    )

    ruta_fisica = carpeta_evidencias / nombre_guardado
    ruta_fisica.write_bytes(contenido)

    ruta_archivo_bd = str(ruta_fisica).replace("\\", "/")

    query_insert = text("""
        INSERT INTO public."PazYSalvoOperacionesEvidencia" (
            "IdPazYSalvo",
            "IdRetiroLaboral",
            "TipoEvidencia",
            "NombreArchivo",
            "NombreArchivoOriginal",
            "RutaArchivo",
            "ExtensionArchivo",
            "MimeType",
            "PesoArchivo",
            "Observacion",
            "Activo",
            "Eliminado",
            "FechaCreacion",
            "FechaActualizacion",
            "CreadoPor",
            "UsuarioActualizacion"
        )
        VALUES (
            :id_paz_y_salvo,
            :id_retiro_laboral,
            :tipo_evidencia,
            :nombre_archivo,
            :nombre_archivo_original,
            :ruta_archivo,
            :extension_archivo,
            :mime_type,
            :peso_archivo,
            :observacion,
            true,
            false,
            CURRENT_TIMESTAMP,
            CURRENT_TIMESTAMP,
            :creado_por,
            :usuario_actualizacion
        )
        RETURNING "IdPazYSalvoEvidencia";
    """)

    id_evidencia = db.execute(
        query_insert,
        {
            "id_paz_y_salvo": id_paz_y_salvo,
            "id_retiro_laboral": id_retiro_laboral,
            "tipo_evidencia": tipo_evidencia,
            "nombre_archivo": nombre_guardado,
            "nombre_archivo_original": nombre_original,
            "ruta_archivo": ruta_archivo_bd,
            "extension_archivo": extension or None,
            "mime_type": mime_type,
            "peso_archivo": len(contenido),
            "observacion": "Evidencia adjunta desde Operaciones.",
            "creado_por": usuario,
            "usuario_actualizacion": usuario,
        },
    ).scalar_one()

    return id_evidencia, ruta_fisica


def _obtener_trabajador_contratado(
    db: Session,
    id_registro_personal: int,
):
    query = text("""
        SELECT
            rp."IdRegistroPersonal",
            rp."NumeroIdentificacion",
            TRIM(
                COALESCE(rp."Nombres", '') || ' ' ||
                COALESCE(rp."Apellidos", '')
            ) AS "NombreCompleto",
            rp."IdEstadoProceso"
        FROM public."RegistroPersonal" rp
        WHERE rp."IdRegistroPersonal" = :id_registro_personal
        LIMIT 1;
    """)

    trabajador = db.execute(
        query,
        {"id_registro_personal": id_registro_personal},
    ).mappings().first()

    if not trabajador:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No se encontró el trabajador seleccionado.",
        )

    if int(trabajador["IdEstadoProceso"] or 0) != ID_ESTADO_CONTRATADO:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "El trabajador ya no se encuentra en estado CONTRATADO "
                "y no puede ser enviado a retiro desde Operaciones."
            ),
        )

    return trabajador


def _validar_motivo_retiro(
    db: Session,
    id_motivo_retiro: int,
):
    query = text("""
        SELECT
            "IdMotivoRetiro",
            "Nombre"
        FROM public."MotivoRetiro"
        WHERE "IdMotivoRetiro" = :id_motivo_retiro
          AND COALESCE("Activo", true) = true
        LIMIT 1;
    """)

    motivo = db.execute(
        query,
        {"id_motivo_retiro": id_motivo_retiro},
    ).mappings().first()

    if not motivo:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="El motivo de retiro seleccionado no existe o está inactivo.",
        )

    return motivo


def _validar_retiro_abierto(
    db: Session,
    id_registro_personal: int,
) -> None:
    query = text("""
        SELECT
            "IdRetiroLaboral",
            "EstadoCasoRRLL"
        FROM public."RetiroLaboral"
        WHERE "IdRegistroPersonal" = :id_registro_personal
          AND COALESCE("Activo", true) = true
        ORDER BY "IdRetiroLaboral" DESC
        LIMIT 1;
    """)

    retiro_existente = db.execute(
        query,
        {"id_registro_personal": id_registro_personal},
    ).mappings().first()

    if retiro_existente:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "El trabajador ya tiene un proceso de retiro activo "
                f"con IdRetiroLaboral={retiro_existente['IdRetiroLaboral']}."
            ),
        )


def _obtener_cliente_actual(
    db: Session,
    id_registro_personal: int,
) -> int | None:
    query = text("""
        SELECT acc."IdCliente"
        FROM public."AsignacionCargoCliente" acc
        WHERE acc."IdRegistroPersonal" = :id_registro_personal
          AND acc."IdCliente" IS NOT NULL
        ORDER BY
            acc."FechaActualizacion" DESC NULLS LAST,
            acc."FechaCreacion" DESC NULLS LAST,
            acc."IdAsignacionCargoCliente" DESC
        LIMIT 1;
    """)

    row = db.execute(
        query,
        {"id_registro_personal": id_registro_personal},
    ).mappings().first()

    return int(row["IdCliente"]) if row and row["IdCliente"] is not None else None


def _obtener_cargo_actual(
    db: Session,
    id_registro_personal: int,
):
    """
    Obtiene el cargo vigente del trabajador desde AsignacionCargoCliente.

    Se toma la asignación más reciente por fecha de actualización,
    fecha de creación e identificador de asignación.
    """
    query = text("""
        SELECT
            acc."IdCargo",
            c."NombreCargo"
        FROM public."AsignacionCargoCliente" acc
        INNER JOIN public."Cargo" c
            ON c."IdCargo" = acc."IdCargo"
        WHERE acc."IdRegistroPersonal" = :id_registro_personal
          AND acc."IdCargo" IS NOT NULL
          AND COALESCE(c."Activo", true) = true
        ORDER BY
            acc."FechaActualizacion" DESC NULLS LAST,
            acc."FechaCreacion" DESC NULLS LAST,
            acc."IdAsignacionCargoCliente" DESC
        LIMIT 1;
    """)

    row = db.execute(
        query,
        {"id_registro_personal": id_registro_personal},
    ).mappings().first()

    if not row:
        return None

    return {
        "IdCargo": int(row["IdCargo"]),
        "NombreCargo": str(row["NombreCargo"] or "").strip(),
    }


def _validar_cliente(
    db: Session,
    id_cliente: int,
):
    query = text("""
        SELECT
            c."IdCliente",
            c."Nombre" AS "NombreCliente"
        FROM public."Cliente" c
        WHERE c."IdCliente" = :id_cliente
        LIMIT 1;
    """)

    cliente = db.execute(
        query,
        {"id_cliente": id_cliente},
    ).mappings().first()

    if not cliente:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="El cliente seleccionado no existe.",
        )

    return cliente


@router.get("/elementos/trabajador/{id_registro_personal}")
def obtener_elementos_paz_salvo_por_trabajador(
    id_registro_personal: int,
    db: Session = Depends(get_db),
    current=Depends(require_operaciones_retiros),
):
    """
    Devuelve los elementos de Paz y Salvo aplicables al trabajador.

    Prioridad:
    1. Configuración específica del cargo en CargoElementoPazSalvo.
    2. Si el cargo no tiene elementos específicos activos, usa la
       clasificación ADMINISTRATIVO / OPERATIVO configurada en
       CargoClasificacionPazSalvo y toma los elementos generales desde
       ClasificacionElementoPazSalvo.
    """
    trabajador = _obtener_trabajador_contratado(
        db=db,
        id_registro_personal=id_registro_personal,
    )

    cargo = _obtener_cargo_actual(
        db=db,
        id_registro_personal=id_registro_personal,
    )

    if cargo is None:
        return {
            "success": True,
            "data": {
                "IdRegistroPersonal": id_registro_personal,
                "NumeroIdentificacion": trabajador["NumeroIdentificacion"],
                "NombreCompleto": trabajador["NombreCompleto"],
                "IdCargo": None,
                "NombreCargo": None,
                "TipoClasificacion": None,
                "OrigenConfiguracion": "SIN_CONFIGURACION",
                "Elementos": [],
            },
        }

    # ============================================================
    # PRIORIDAD 1: ELEMENTOS ESPECÍFICOS DEL CARGO
    # ============================================================
    query_elementos_cargo = text("""
        SELECT
            ceps."IdCargoElementoPazSalvo" AS "IdConfiguracionElemento",
            ceps."IdCargo",
            ceps."CodigoElemento",
            ceps."NombreElemento"
        FROM public."CargoElementoPazSalvo" ceps
        WHERE ceps."IdCargo" = :id_cargo
          AND COALESCE(ceps."Activo", true) = true
        ORDER BY
            ceps."IdCargoElementoPazSalvo" ASC;
    """)

    elementos_cargo = db.execute(
        query_elementos_cargo,
        {"id_cargo": cargo["IdCargo"]},
    ).mappings().all()

    if elementos_cargo:
        return {
            "success": True,
            "data": {
                "IdRegistroPersonal": id_registro_personal,
                "NumeroIdentificacion": trabajador["NumeroIdentificacion"],
                "NombreCompleto": trabajador["NombreCompleto"],
                "IdCargo": cargo["IdCargo"],
                "NombreCargo": cargo["NombreCargo"],
                "TipoClasificacion": None,
                "OrigenConfiguracion": "CARGO",
                "Elementos": [
                    {
                        "IdConfiguracionElemento": int(
                            row["IdConfiguracionElemento"]
                        ),
                        "CodigoElemento": str(
                            row["CodigoElemento"] or ""
                        ).strip(),
                        "NombreElemento": str(
                            row["NombreElemento"] or ""
                        ).strip(),
                    }
                    for row in elementos_cargo
                ],
            },
        }

    # ============================================================
    # PRIORIDAD 2: CLASIFICACIÓN ADMINISTRATIVO / OPERATIVO
    # ============================================================
    query_clasificacion = text("""
        SELECT
            ccps."TipoClasificacion"
        FROM public."CargoClasificacionPazSalvo" ccps
        WHERE ccps."IdCargo" = :id_cargo
          AND COALESCE(ccps."Activo", true) = true
        LIMIT 1;
    """)

    clasificacion = db.execute(
        query_clasificacion,
        {"id_cargo": cargo["IdCargo"]},
    ).mappings().first()

    if not clasificacion:
        return {
            "success": True,
            "data": {
                "IdRegistroPersonal": id_registro_personal,
                "NumeroIdentificacion": trabajador["NumeroIdentificacion"],
                "NombreCompleto": trabajador["NombreCompleto"],
                "IdCargo": cargo["IdCargo"],
                "NombreCargo": cargo["NombreCargo"],
                "TipoClasificacion": None,
                "OrigenConfiguracion": "SIN_CONFIGURACION",
                "Elementos": [],
            },
        }

    tipo_clasificacion = str(
        clasificacion["TipoClasificacion"] or ""
    ).strip().upper()

    query_elementos_clasificacion = text("""
        SELECT
            ceps."IdClasificacionElementoPazSalvo"
                AS "IdConfiguracionElemento",
            ceps."TipoClasificacion",
            ceps."CodigoElemento",
            ceps."NombreElemento"
        FROM public."ClasificacionElementoPazSalvo" ceps
        WHERE ceps."TipoClasificacion" = :tipo_clasificacion
          AND COALESCE(ceps."Activo", true) = true
        ORDER BY
            ceps."IdClasificacionElementoPazSalvo" ASC;
    """)

    elementos_clasificacion = db.execute(
        query_elementos_clasificacion,
        {"tipo_clasificacion": tipo_clasificacion},
    ).mappings().all()

    return {
        "success": True,
        "data": {
            "IdRegistroPersonal": id_registro_personal,
            "NumeroIdentificacion": trabajador["NumeroIdentificacion"],
            "NombreCompleto": trabajador["NombreCompleto"],
            "IdCargo": cargo["IdCargo"],
            "NombreCargo": cargo["NombreCargo"],
            "TipoClasificacion": tipo_clasificacion,
            "OrigenConfiguracion": (
                "CLASIFICACION"
                if elementos_clasificacion
                else "SIN_CONFIGURACION"
            ),
            "Elementos": [
                {
                    "IdConfiguracionElemento": int(
                        row["IdConfiguracionElemento"]
                    ),
                    "CodigoElemento": str(
                        row["CodigoElemento"] or ""
                    ).strip(),
                    "NombreElemento": str(
                        row["NombreElemento"] or ""
                    ).strip(),
                }
                for row in elementos_clasificacion
            ],
        },
    }


@router.get("/usuario-actual")
def obtener_usuario_actual_operaciones_retiros(
    current=Depends(require_operaciones_retiros),
):
    """
    Devuelve el nombre completo del usuario autenticado que está
    diligenciando el Paz y Salvo.

    Para los usuarios corporativos actuales, NombreUsuario contiene
    el nombre completo y Usuario contiene el login de ingreso.
    """
    usuario = current.get("usuario")

    nombre_completo = str(
        getattr(usuario, "NombreUsuario", "") or ""
    ).strip()

    login_usuario = str(
        getattr(usuario, "Usuario", "") or ""
    ).strip()

    if not nombre_completo:
        nombre_completo = login_usuario

    return {
        "success": True,
        "data": {
            "NombreCompleto": nombre_completo,
            "Usuario": login_usuario,
        },
    }


@router.get("/clientes")
def listar_clientes_operaciones_retiros(
    db: Session = Depends(get_db),
    current=Depends(require_operaciones_retiros),
):
    """
    Devuelve el catálogo de clientes registrado en la base de datos.

    Este catálogo se utiliza en el formulario de Paz y Salvo de Operaciones
    para permitir validar o corregir el cliente antes de enviar el retiro.
    """
    query = text("""
        SELECT
            c."IdCliente",
            c."Nombre" AS "NombreCliente"
        FROM public."Cliente" c
        WHERE TRIM(COALESCE(c."Nombre", '')) <> ''
        ORDER BY c."Nombre" ASC;
    """)

    rows = db.execute(query).mappings().all()

    return {
        "success": True,
        "data": [
            {
                "IdCliente": int(row["IdCliente"]),
                "NombreCliente": str(row["NombreCliente"]).strip(),
            }
            for row in rows
        ],
    }


@router.get("/clientes/trabajador/{id_registro_personal}")
def obtener_cliente_actual_operaciones_retiros(
    id_registro_personal: int,
    db: Session = Depends(get_db),
    current=Depends(require_operaciones_retiros),
):
    """
    Devuelve el último cliente asignado al trabajador según
    AsignacionCargoCliente.
    """
    id_cliente = _obtener_cliente_actual(
        db=db,
        id_registro_personal=id_registro_personal,
    )

    if id_cliente is None:
        return {
            "success": True,
            "data": None,
        }

    cliente = _validar_cliente(
        db=db,
        id_cliente=id_cliente,
    )

    return {
        "success": True,
        "data": {
            "IdCliente": int(cliente["IdCliente"]),
            "NombreCliente": str(cliente["NombreCliente"] or "").strip(),
        },
    }


@router.post("/enviar")
async def enviar_retiro_a_relaciones_laborales(
    # Datos del retiro que ya utiliza RRLL.
    IdRegistroPersonal: int = Form(...),
    IdCliente: int | None = Form(None),
    IdMotivoRetiro: int = Form(...),
    FechaUltimoDiaLaborado: date = Form(...),
    UsuarioActualizacion: str = Form("operaciones"),
    Observacion: str | None = Form(None),

    # Detalle del nuevo Paz y Salvo digital.
    FechaHoraInicioDiligenciamiento: datetime = Form(...),
    ElaboradoPor: str = Form(...),
    DescripcionMotivoRetiro: str = Form(...),

    Locker: str = Form(...),
    Llaves: str = Form(...),
    EntregaHerramientas: str = Form(...),
    TarjetaControlAcceso: str = Form(...),

    EntregaGuantes: str = Form(...),
    EntregaMonogafas: str = Form(...),
    EntregaPeto: str = Form(...),
    ObservacionesEntrega: str = Form(...),

    AplicaDescuento: str = Form(...),
    ValorDescuento: Decimal | None = Form(None),
    NovedadesNomina: str | None = Form(None),

    PendienteEntregaUniforme: str = Form(...),
    UniformePatogeno: str = Form(...),
    Botas: str = Form(...),
    Zapatos: str = Form(...),
    Chaqueta: str = Form(...),
    CarnetAlpArl: str = Form(...),
    PendientePagoVacunas: str = Form(...),

    UsuariosClavesDispositivos: str | None = Form(None),
    CorreoSupervisora: str = Form(...),
    EstadoPazYSalvo: str = Form(...),

    # Compatibilidad con el flujo anterior.
    # El flujo actual genera automáticamente el PDF oficial cuando
    # no se recibe un archivo manual.
    archivo: UploadFile | None = File(None),

    # Evidencias de Operaciones asociadas al Paz y Salvo.
    novedadesNominaArchivo: list[UploadFile] | None = File(None),
    formatoDescuentoVacunasArchivo: UploadFile | None = File(None),
    fotoCarnetAccesoArchivo: UploadFile | None = File(None),
    fotoListadoHerramientasArchivo: UploadFile | None = File(None),
    fotoPlanillaNominaArchivo: UploadFile | None = File(None),

    db: Session = Depends(get_db),
    current=Depends(require_operaciones_retiros),
):
    """
    Envía a RRLL el retiro iniciado por Operaciones.

    Conserva el flujo existente y agrega el detalle digital del Paz y Salvo:

    - RetiroLaboral.
    - PazYSalvoOperaciones.
    - PazYSalvoOperacionesDetalle.
    - Paz y salvo PDF generado automáticamente y registrado en
      RetiroLaboralAdjunto como tipo 2.
    - Compatibilidad con un PDF manual si algún flujo anterior todavía
      lo envía.
    - Actualización del trabajador a estado de retiro abierto.

    Las evidencias adicionales del formulario se guardan en
    PazYSalvoOperacionesEvidencia. RRLL podrá consultarlas junto al Paz
    y Salvo, mientras Nómina conservará únicamente el PDF oficial.
    """

    ruta_fisica: Path | None = None
    contenido: bytes | None = None
    nombre_original: str | None = None
    ruta_archivo_bd: str | None = None
    id_adjunto: int | None = None
    rutas_evidencias_creadas: list[Path] = []
    ids_evidencias: list[int] = []

    try:
        usuario = _normalizar_usuario(UsuarioActualizacion)
        observacion = _normalizar_texto_opcional(Observacion)

        elaborado_por = _normalizar_texto_requerido(
            ElaboradoPor,
            "ElaboradoPor",
        )
        descripcion_motivo = _normalizar_texto_requerido(
            DescripcionMotivoRetiro,
            "DescripcionMotivoRetiro",
        )

        locker = _normalizar_opcion(
            Locker,
            "Locker",
            OPCIONES_ENTREGA_GENERAL,
        )
        llaves = _normalizar_opcion(
            Llaves,
            "Llaves",
            OPCIONES_ENTREGA_GENERAL,
        )
        entrega_herramientas = _normalizar_opcion(
            EntregaHerramientas,
            "EntregaHerramientas",
            OPCIONES_ENTREGA_GENERAL,
        )
        tarjeta_control_acceso = _normalizar_opcion(
            TarjetaControlAcceso,
            "TarjetaControlAcceso",
            OPCIONES_ENTREGA_GENERAL,
        )

        entrega_guantes = _normalizar_opcion(
            EntregaGuantes,
            "EntregaGuantes",
            OPCIONES_CUMPLIMIENTO,
        )
        entrega_monogafas = _normalizar_opcion(
            EntregaMonogafas,
            "EntregaMonogafas",
            OPCIONES_CUMPLIMIENTO,
        )
        entrega_peto = _normalizar_opcion(
            EntregaPeto,
            "EntregaPeto",
            OPCIONES_ENTREGA_GENERAL,
        )
        observaciones_entrega = _normalizar_texto_requerido(
            ObservacionesEntrega,
            "ObservacionesEntrega",
        )

        aplica_descuento = _normalizar_opcion(
            AplicaDescuento,
            "AplicaDescuento",
            OPCIONES_SI_NO,
        )
        valor_descuento = _validar_valor_descuento(
            aplica_descuento,
            ValorDescuento,
        )
        novedades_nomina = _normalizar_texto_opcional(NovedadesNomina)

        pendiente_entrega_uniforme = _normalizar_opcion(
            PendienteEntregaUniforme,
            "PendienteEntregaUniforme",
            OPCIONES_SI_NO,
        )
        uniforme_patogeno = _normalizar_opcion(
            UniformePatogeno,
            "UniformePatogeno",
            OPCIONES_SI_NO,
        )
        botas = _normalizar_opcion(
            Botas,
            "Botas",
            OPCIONES_SI_NO,
        )
        zapatos = _normalizar_opcion(
            Zapatos,
            "Zapatos",
            OPCIONES_SI_NO,
        )
        chaqueta = _normalizar_opcion(
            Chaqueta,
            "Chaqueta",
            OPCIONES_SI_NO,
        )
        carnet_alp_arl = _normalizar_opcion(
            CarnetAlpArl,
            "CarnetAlpArl",
            OPCIONES_SI_NO,
        )
        pendiente_pago_vacunas = _normalizar_opcion(
            PendientePagoVacunas,
            "PendientePagoVacunas",
            OPCIONES_SI_NO,
        )

        usuarios_claves_dispositivos = _normalizar_texto_opcional(
            UsuariosClavesDispositivos
        )
        correo_supervisora = _validar_correo(CorreoSupervisora)
        estado_paz_y_salvo = _normalizar_opcion(
            EstadoPazYSalvo,
            "EstadoPazYSalvo",
            OPCIONES_ESTADO_PAZ_SALVO,
        )

        if archivo is not None:
            contenido = await archivo.read()
            _validar_archivo_pdf(archivo, contenido)

        evidencias_recibidas: list[tuple[str, UploadFile, bytes]] = []

        if novedadesNominaArchivo:
            for archivo_evidencia in novedadesNominaArchivo:
                contenido_evidencia = await archivo_evidencia.read()
                _validar_evidencia(
                    archivo_evidencia,
                    contenido_evidencia,
                    "NOVEDADES_NOMINA",
                )
                evidencias_recibidas.append((
                    "NOVEDADES_NOMINA",
                    archivo_evidencia,
                    contenido_evidencia,
                ))

        evidencias_simples = [
            ("FORMATO_DESCUENTO_VACUNAS", formatoDescuentoVacunasArchivo),
            ("CARNET_ACCESO", fotoCarnetAccesoArchivo),
            ("LISTADO_HERRAMIENTAS", fotoListadoHerramientasArchivo),
            ("PLANILLA_NOMINA", fotoPlanillaNominaArchivo),
        ]

        for tipo_evidencia, archivo_evidencia in evidencias_simples:
            if archivo_evidencia is None:
                continue

            contenido_evidencia = await archivo_evidencia.read()
            _validar_evidencia(
                archivo_evidencia,
                contenido_evidencia,
                tipo_evidencia,
            )
            evidencias_recibidas.append((
                tipo_evidencia,
                archivo_evidencia,
                contenido_evidencia,
            ))

        trabajador = _obtener_trabajador_contratado(
            db=db,
            id_registro_personal=IdRegistroPersonal,
        )

        motivo = _validar_motivo_retiro(
            db=db,
            id_motivo_retiro=IdMotivoRetiro,
        )

        _validar_retiro_abierto(
            db=db,
            id_registro_personal=IdRegistroPersonal,
        )

        # El front puede enviar el cliente validado/corregido por Operaciones.
        # Se mantiene compatibilidad con el flujo anterior: si no llega
        # IdCliente, se utiliza la última asignación registrada del trabajador.
        id_cliente = IdCliente

        if id_cliente is None:
            id_cliente = _obtener_cliente_actual(
                db=db,
                id_registro_personal=IdRegistroPersonal,
            )

        if id_cliente is None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    "No fue posible determinar el cliente actual del trabajador. "
                    "Valida y selecciona un cliente antes de enviar el retiro."
                ),
            )

        cliente = _validar_cliente(
            db=db,
            id_cliente=int(id_cliente),
        )
        id_cliente = int(cliente["IdCliente"])

        query_insert_retiro = text("""
            INSERT INTO public."RetiroLaboral" (
                "IdRegistroPersonal",
                "IdCliente",
                "IdMotivoRetiro",
                "FechaProceso",
                "FechaRetiro",
                "FechaEnvioOperaciones",
                "ObservacionGeneral",
                "EstadoCasoRRLL",
                "Activo",
                "FechaCreacion",
                "FechaActualizacion",
                "UsuarioActualizacion"
            )
            VALUES (
                :id_registro_personal,
                :id_cliente,
                :id_motivo_retiro,
                CURRENT_DATE,
                :fecha_retiro,
                CURRENT_TIMESTAMP,
                :observacion_general,
                'ABIERTO',
                true,
                CURRENT_TIMESTAMP,
                CURRENT_TIMESTAMP,
                :usuario_actualizacion
            )
            RETURNING "IdRetiroLaboral";
        """)

        id_retiro_laboral = db.execute(
            query_insert_retiro,
            {
                "id_registro_personal": IdRegistroPersonal,
                "id_cliente": id_cliente,
                "id_motivo_retiro": IdMotivoRetiro,
                "fecha_retiro": FechaUltimoDiaLaborado,
                "observacion_general": observacion,
                "usuario_actualizacion": usuario,
            },
        ).scalar_one()

        query_insert_paz_salvo = text("""
            INSERT INTO public."PazYSalvoOperaciones" (
                "IdRegistroPersonal",
                "FechaUltimoDiaLaborado",
                "Observacion",
                "UsuarioCreacion",
                "FechaCreacion",
                "IdRetiroLaboral",
                "FechaCarga"
            )
            VALUES (
                :id_registro_personal,
                :fecha_ultimo_dia_laborado,
                :observacion,
                :usuario_creacion,
                CURRENT_TIMESTAMP,
                :id_retiro_laboral,
                CURRENT_TIMESTAMP
            )
            RETURNING "IdPazYSalvo";
        """)

        id_paz_y_salvo = db.execute(
            query_insert_paz_salvo,
            {
                "id_registro_personal": IdRegistroPersonal,
                "fecha_ultimo_dia_laborado": FechaUltimoDiaLaborado,
                "observacion": observacion,
                "usuario_creacion": usuario,
                "id_retiro_laboral": id_retiro_laboral,
            },
        ).scalar_one()

        query_insert_detalle = text("""
            INSERT INTO public."PazYSalvoOperacionesDetalle" (
                "IdPazYSalvo",
                "FechaHoraInicioDiligenciamiento",
                "ElaboradoPor",
                "DescripcionMotivoRetiro",
                "Locker",
                "Llaves",
                "EntregaHerramientas",
                "TarjetaControlAcceso",
                "EntregaGuantes",
                "EntregaMonogafas",
                "EntregaPeto",
                "ObservacionesEntrega",
                "AplicaDescuento",
                "ValorDescuento",
                "NovedadesNomina",
                "PendienteEntregaUniforme",
                "UniformePatogeno",
                "Botas",
                "Zapatos",
                "Chaqueta",
                "CarnetAlpArl",
                "PendientePagoVacunas",
                "UsuariosClavesDispositivos",
                "CorreoSupervisora",
                "EstadoPazYSalvo",
                "FechaCreacion",
                "FechaActualizacion",
                "UsuarioActualizacion"
            )
            VALUES (
                :id_paz_y_salvo,
                :fecha_hora_inicio_diligenciamiento,
                :elaborado_por,
                :descripcion_motivo_retiro,
                :locker,
                :llaves,
                :entrega_herramientas,
                :tarjeta_control_acceso,
                :entrega_guantes,
                :entrega_monogafas,
                :entrega_peto,
                :observaciones_entrega,
                :aplica_descuento,
                :valor_descuento,
                :novedades_nomina,
                :pendiente_entrega_uniforme,
                :uniforme_patogeno,
                :botas,
                :zapatos,
                :chaqueta,
                :carnet_alp_arl,
                :pendiente_pago_vacunas,
                :usuarios_claves_dispositivos,
                :correo_supervisora,
                :estado_paz_y_salvo,
                CURRENT_TIMESTAMP,
                CURRENT_TIMESTAMP,
                :usuario_actualizacion
            )
            RETURNING "IdPazYSalvoDetalle";
        """)

        id_paz_y_salvo_detalle = db.execute(
            query_insert_detalle,
            {
                "id_paz_y_salvo": id_paz_y_salvo,
                "fecha_hora_inicio_diligenciamiento": (
                    FechaHoraInicioDiligenciamiento
                ),
                "elaborado_por": elaborado_por,
                "descripcion_motivo_retiro": descripcion_motivo,
                "locker": locker,
                "llaves": llaves,
                "entrega_herramientas": entrega_herramientas,
                "tarjeta_control_acceso": tarjeta_control_acceso,
                "entrega_guantes": entrega_guantes,
                "entrega_monogafas": entrega_monogafas,
                "entrega_peto": entrega_peto,
                "observaciones_entrega": observaciones_entrega,
                "aplica_descuento": aplica_descuento,
                "valor_descuento": valor_descuento,
                "novedades_nomina": novedades_nomina,
                "pendiente_entrega_uniforme": pendiente_entrega_uniforme,
                "uniforme_patogeno": uniforme_patogeno,
                "botas": botas,
                "zapatos": zapatos,
                "chaqueta": chaqueta,
                "carnet_alp_arl": carnet_alp_arl,
                "pendiente_pago_vacunas": pendiente_pago_vacunas,
                "usuarios_claves_dispositivos": usuarios_claves_dispositivos,
                "correo_supervisora": correo_supervisora,
                "estado_paz_y_salvo": estado_paz_y_salvo,
                "usuario_actualizacion": usuario,
            },
        ).scalar_one()

        # ============================================================
        # PAZ Y SALVO PDF
        # ============================================================
        #
        # Flujo actual:
        # - Si un cliente anterior todavía envía un PDF manual, se conserva.
        # - Si no llega archivo, se genera automáticamente el PDF oficial
        #   a partir de PazYSalvoOperaciones + PazYSalvoOperacionesDetalle.
        #
        # En ambos casos el documento se registra como:
        # IdTipoDocumentoRetiro = 2 (Paz y salvo).
        # ============================================================

        if archivo is not None and contenido is not None:
            nombre_original = Path(str(archivo.filename)).name
        else:
            buffer_pdf = generar_paz_salvo_operaciones_pdf(
                db=db,
                id_paz_y_salvo=id_paz_y_salvo,
            )
            contenido = buffer_pdf.getvalue()
            buffer_pdf.close()

            nombre_original = (
                f"paz_salvo_operaciones_{id_retiro_laboral}.pdf"
            )

        if not contenido:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=(
                    "No fue posible obtener el contenido del PDF oficial "
                    "del Paz y Salvo."
                ),
            )

        carpeta_retiro = STORAGE_BASE_DIR / str(id_retiro_laboral)
        carpeta_retiro.mkdir(parents=True, exist_ok=True)

        nombre_guardado = (
            f"paz_salvo_operaciones_"
            f"{id_retiro_laboral}_{uuid4().hex}.pdf"
        )

        ruta_fisica = carpeta_retiro / nombre_guardado
        ruta_fisica.write_bytes(contenido)
        ruta_archivo_bd = str(ruta_fisica).replace("\\", "/")

        query_insert_adjunto = text("""
            INSERT INTO public."RetiroLaboralAdjunto" (
                "IdRetiroLaboral",
                "IdTipoDocumentoRetiro",
                "NombreArchivo",
                "NombreArchivoOriginal",
                "RutaArchivo",
                "ExtensionArchivo",
                "PesoArchivo",
                "Observacion",
                "OrigenArchivo",
                "MimeType",
                "Activo",
                "Eliminado",
                "FechaCreacion",
                "FechaActualizacion",
                "CreadoPor",
                "UsuarioActualizacion"
            )
            VALUES (
                :id_retiro_laboral,
                :id_tipo_documento_retiro,
                :nombre_archivo,
                :nombre_archivo_original,
                :ruta_archivo,
                '.pdf',
                :peso_archivo,
                :observacion,
                'OPERACIONES',
                'application/pdf',
                true,
                false,
                CURRENT_TIMESTAMP,
                CURRENT_TIMESTAMP,
                :creado_por,
                :usuario_actualizacion
            )
            RETURNING "IdRetiroLaboralAdjunto";
        """)

        id_adjunto = db.execute(
            query_insert_adjunto,
            {
                "id_retiro_laboral": id_retiro_laboral,
                "id_tipo_documento_retiro": (
                    ID_TIPO_DOCUMENTO_PAZ_Y_SALVO
                ),
                "nombre_archivo": nombre_guardado,
                "nombre_archivo_original": nombre_original,
                "ruta_archivo": ruta_archivo_bd,
                "peso_archivo": len(contenido),
                "observacion": (
                    observacion
                    or (
                        "Paz y salvo generado automáticamente "
                        "desde el módulo de Operaciones."
                    )
                ),
                "creado_por": usuario,
                "usuario_actualizacion": usuario,
            },
        ).scalar_one()

        carpeta_evidencias = carpeta_retiro / "evidencias_operaciones"
        carpeta_evidencias.mkdir(parents=True, exist_ok=True)

        for tipo_evidencia, archivo_evidencia, contenido_evidencia in evidencias_recibidas:
            id_evidencia, ruta_evidencia = _guardar_evidencia_paz_salvo(
                db=db,
                id_paz_y_salvo=id_paz_y_salvo,
                id_retiro_laboral=id_retiro_laboral,
                tipo_evidencia=tipo_evidencia,
                archivo=archivo_evidencia,
                contenido=contenido_evidencia,
                usuario=usuario,
                carpeta_evidencias=carpeta_evidencias,
            )
            ids_evidencias.append(id_evidencia)
            rutas_evidencias_creadas.append(ruta_evidencia)

        query_update_registro_personal = text("""
            UPDATE public."RegistroPersonal"
            SET
                "IdEstadoProceso" = :id_estado_proceso,
                "FechaActualizacion" = CURRENT_TIMESTAMP,
                "UsuarioActualizacion" = :usuario_actualizacion
            WHERE "IdRegistroPersonal" = :id_registro_personal;
        """)

        db.execute(
            query_update_registro_personal,
            {
                "id_estado_proceso": ID_ESTADO_RETIRO_ABIERTO,
                "usuario_actualizacion": usuario,
                "id_registro_personal": IdRegistroPersonal,
            },
        )

        db.commit()

        return {
            "success": True,
            "message": (
                "El retiro, el detalle y el PDF oficial del paz y salvo "
                "fueron enviados correctamente a Relaciones Laborales."
            ),
            "data": {
                "IdRetiroLaboral": id_retiro_laboral,
                "IdPazYSalvo": id_paz_y_salvo,
                "IdPazYSalvoDetalle": id_paz_y_salvo_detalle,
                "IdRetiroLaboralAdjunto": id_adjunto,
                "IdRegistroPersonal": IdRegistroPersonal,
                "NumeroIdentificacion": trabajador["NumeroIdentificacion"],
                "NombreCompleto": trabajador["NombreCompleto"],
                "IdCliente": id_cliente,
                "NombreCliente": str(cliente["NombreCliente"] or "").strip(),
                "IdMotivoRetiro": IdMotivoRetiro,
                "NombreMotivoRetiro": motivo["Nombre"],
                "FechaUltimoDiaLaborado": FechaUltimoDiaLaborado,
                "FechaHoraInicioDiligenciamiento": (
                    FechaHoraInicioDiligenciamiento
                ),
                "EstadoPazYSalvo": estado_paz_y_salvo,
                "EstadoCasoRRLL": "ABIERTO",
                "IdEstadoProceso": ID_ESTADO_RETIRO_ABIERTO,
                "NombreArchivoOriginal": nombre_original,
                "RutaArchivo": ruta_archivo_bd,
                "CantidadEvidenciasOperaciones": len(ids_evidencias),
                "IdsEvidenciasOperaciones": ids_evidencias,
            },
        }

    except HTTPException:
        db.rollback()

        if ruta_fisica and ruta_fisica.exists():
            ruta_fisica.unlink(missing_ok=True)

        for ruta_evidencia in rutas_evidencias_creadas:
            if ruta_evidencia.exists():
                ruta_evidencia.unlink(missing_ok=True)

        raise

    except Exception as error:
        db.rollback()

        if ruta_fisica and ruta_fisica.exists():
            ruta_fisica.unlink(missing_ok=True)

        for ruta_evidencia in rutas_evidencias_creadas:
            if ruta_evidencia.exists():
                ruta_evidencia.unlink(missing_ok=True)

        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=(
                "No fue posible enviar el retiro a Relaciones Laborales: "
                f"{str(error)}"
            ),
        ) from error

    finally:
        if archivo is not None:
            await archivo.close()

        archivos_evidencia_cierre: list[UploadFile] = []

        if novedadesNominaArchivo:
            archivos_evidencia_cierre.extend(novedadesNominaArchivo)

        for archivo_evidencia in (
            formatoDescuentoVacunasArchivo,
            fotoCarnetAccesoArchivo,
            fotoListadoHerramientasArchivo,
            fotoPlanillaNominaArchivo,
        ):
            if archivo_evidencia is not None:
                archivos_evidencia_cierre.append(archivo_evidencia)

        for archivo_evidencia in archivos_evidencia_cierre:
            await archivo_evidencia.close()