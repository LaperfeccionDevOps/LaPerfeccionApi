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

OPCIONES_ENTREGA_GENERAL = {"NO APLICA", "ACEPTADO", "RECHAZADO"}
OPCIONES_CUMPLIMIENTO = {"NO APLICA", "CUMPLE", "NO CUMPLE"}
OPCIONES_SI_NO = {"SI", "NO"}
OPCIONES_ESTADO_PAZ_SALVO = {"ABIERTO", "CERRADO"}


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


@router.post("/enviar")
async def enviar_retiro_a_relaciones_laborales(
    # Datos del retiro que ya utiliza RRLL.
    IdRegistroPersonal: int = Form(...),
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

    db: Session = Depends(get_db),
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

    Las evidencias adicionales del formulario se integrarán en la fase
    documental utilizando RetiroLaboralAdjunto.
    """

    ruta_fisica: Path | None = None
    contenido: bytes | None = None
    nombre_original: str | None = None
    ruta_archivo_bd: str | None = None
    id_adjunto: int | None = None

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

        id_cliente = _obtener_cliente_actual(
            db=db,
            id_registro_personal=IdRegistroPersonal,
        )

        if id_cliente is None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    "No fue posible determinar el cliente/sede actual del "
                    "trabajador. Valida su asignación antes de enviar el retiro."
                ),
            )

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
            },
        }

    except HTTPException:
        db.rollback()

        if ruta_fisica and ruta_fisica.exists():
            ruta_fisica.unlink(missing_ok=True)

        raise

    except Exception as error:
        db.rollback()

        if ruta_fisica and ruta_fisica.exists():
            ruta_fisica.unlink(missing_ok=True)

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