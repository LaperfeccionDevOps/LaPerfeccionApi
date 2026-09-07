# app/api/routers/trabajador_incapacidades_routers.py

from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    UploadFile,
    status,
)
from fastapi.responses import Response
from sqlalchemy.orm import Session

from domain.models.aspirante import RegistroPersonal
from domain.models.trabajador_incapacidades import (
    DocumentoIncapacidadTrabajador,
    IncapacidadTrabajador,
)
from infrastructure.db.deps import get_db
from infrastructure.security.auth_dependencies import (
    get_current_trabajador,
)


router = APIRouter(
    prefix="/trabajador/incapacidades",
    tags=["Portal Trabajador - Incapacidades"],
)


MAX_FILE_SIZE_MB = 10

MAX_FILE_SIZE_BYTES = (
    MAX_FILE_SIZE_MB
    * 1024
    * 1024
)


EXTENSIONES_PERMITIDAS = {
    "pdf",
    "jpg",
    "jpeg",
    "png",
}


MIME_TYPES_PERMITIDOS = {
    "application/pdf",
    "image/jpeg",
    "image/png",
}


TIPOS_INCAPACIDAD = {
    "INCAPACIDAD_1_2_DIAS": {
        "descripcion":
            "Incapacidad de 1 y 2 días",
        "documentos": {
            "Incapacidad",
        },
    },
    "ACCIDENTE_TRANSITO": {
        "descripcion":
            "Accidente de tránsito",
        "documentos": {
            "Incapacidad",
            "Epicrisis",
            "FURIPS",
            "Cédula",
            "SOAT",
        },
    },
    "ACCIDENTE_TRABAJO": {
        "descripcion":
            "Accidente de trabajo (ARL)",
        "documentos": {
            "Incapacidad",
            "Epicrisis",
        },
    },
    "INCAPACIDAD_3_MAS_DIAS": {
        "descripcion":
            "Incapacidad de 3 o más días",
        "documentos": {
            "Incapacidad",
            "Epicrisis",
        },
    },
    "LICENCIA_MATERNA": {
        "descripcion":
            "Licencia materna",
        "documentos": {
            "Incapacidad",
            "Epicrisis",
            "Registro civil o nacido vivo",
        },
    },
    "LICENCIA_PATERNA": {
        "descripcion":
            "Licencia paterna",
        "documentos": {
            "Registro civil o nacido vivo",
        },
    },
}


def _normalizar_texto(
    valor: str | None,
) -> str:
    return str(
        valor or ""
    ).strip()


def _normalizar_tipo_incapacidad(
    valor: str | None,
) -> str:
    return (
        _normalizar_texto(
            valor
        )
        .upper()
    )


def _convertir_es_prorroga(
    valor: str | None,
) -> bool:
    texto = (
        _normalizar_texto(
            valor
        )
        .upper()
    )

    if texto in {
        "SI",
        "SÍ",
        "TRUE",
        "1",
    }:
        return True

    if texto in {
        "NO",
        "FALSE",
        "0",
    }:
        return False

    raise HTTPException(
        status_code=
            status.HTTP_400_BAD_REQUEST,
        detail=(
            "El campo prórroga debe "
            "tener un valor válido."
        ),
    )


def _obtener_extension(
    nombre_archivo: str | None,
) -> str:
    nombre = _normalizar_texto(
        nombre_archivo
    )

    if not nombre:
        return ""

    extension = (
        Path(nombre)
        .suffix
        .lower()
        .replace(".", "")
    )

    return extension


def _validar_tipo_incapacidad(
    tipo_incapacidad: str,
) -> dict:
    configuracion = (
        TIPOS_INCAPACIDAD.get(
            tipo_incapacidad
        )
    )

    if not configuracion:
        raise HTTPException(
            status_code=
                status.HTTP_400_BAD_REQUEST,
            detail=(
                "El tipo de incapacidad "
                "seleccionado no es válido."
            ),
        )

    return configuracion


def _validar_dias_incapacidad(
    tipo_incapacidad: str,
    dias_incapacidad: int,
) -> None:
    if dias_incapacidad <= 0:
        raise HTTPException(
            status_code=
                status.HTTP_400_BAD_REQUEST,
            detail=(
                "Los días de incapacidad "
                "deben ser mayores a cero."
            ),
        )

    if (
        tipo_incapacidad
        == "INCAPACIDAD_1_2_DIAS"
        and dias_incapacidad
        not in {
            1,
            2,
        }
    ):
        raise HTTPException(
            status_code=
                status.HTTP_400_BAD_REQUEST,
            detail=(
                "La incapacidad de 1 y 2 días "
                "solamente permite registrar "
                "1 o 2 días."
            ),
        )

    if (
        tipo_incapacidad
        == "INCAPACIDAD_3_MAS_DIAS"
        and dias_incapacidad < 3
    ):
        raise HTTPException(
            status_code=
                status.HTTP_400_BAD_REQUEST,
            detail=(
                "La incapacidad de 3 o más días "
                "debe tener mínimo 3 días."
            ),
        )


def _calcular_fecha_final(
    fecha_inicio: date,
    dias_incapacidad: int,
) -> date:
    return (
        fecha_inicio
        + timedelta(
            days=dias_incapacidad - 1
        )
    )


async def _leer_y_validar_archivo(
    archivo: UploadFile,
    tipo_documento: str,
) -> dict:
    nombre_archivo = (
        _normalizar_texto(
            archivo.filename
        )
    )

    if not nombre_archivo:
        raise HTTPException(
            status_code=
                status.HTTP_400_BAD_REQUEST,
            detail=(
                f"El archivo de "
                f"{tipo_documento} "
                "no tiene un nombre válido."
            ),
        )

    extension = (
        _obtener_extension(
            nombre_archivo
        )
    )

    if (
        extension
        not in EXTENSIONES_PERMITIDAS
    ):
        raise HTTPException(
            status_code=
                status.HTTP_400_BAD_REQUEST,
            detail=(
                f"{tipo_documento}: "
                "solo se permiten archivos "
                "PDF, JPG, JPEG o PNG."
            ),
        )

    mime_type = (
        _normalizar_texto(
            archivo.content_type
        )
        .lower()
    )

    if (
        mime_type
        and mime_type
        not in MIME_TYPES_PERMITIDOS
    ):
        raise HTTPException(
            status_code=
                status.HTTP_400_BAD_REQUEST,
            detail=(
                f"{tipo_documento}: "
                "el tipo de archivo "
                "no está permitido."
            ),
        )

    contenido = await archivo.read()

    if not contenido:
        raise HTTPException(
            status_code=
                status.HTTP_400_BAD_REQUEST,
            detail=(
                f"{tipo_documento}: "
                "el archivo está vacío."
            ),
        )

    tamano_bytes = len(
        contenido
    )

    if (
        tamano_bytes
        > MAX_FILE_SIZE_BYTES
    ):
        raise HTTPException(
            status_code=
                status.HTTP_400_BAD_REQUEST,
            detail=(
                f"{tipo_documento}: "
                f"el archivo supera "
                f"el tamaño máximo de "
                f"{MAX_FILE_SIZE_MB} MB."
            ),
        )

    return {
        "nombre_archivo":
            nombre_archivo,
        "extension":
            extension,
        "mime_type":
            mime_type or None,
        "tamano_bytes":
            tamano_bytes,
        "contenido":
            contenido,
    }


def _validar_documentos_recibidos(
    configuracion_tipo: dict,
    tipos_documento: list[str],
    cantidad_archivos: int,
) -> list[str]:
    tipos_limpios = [
        _normalizar_texto(
            tipo
        )
        for tipo in tipos_documento
    ]

    if (
        len(tipos_limpios)
        != cantidad_archivos
    ):
        raise HTTPException(
            status_code=
                status.HTTP_400_BAD_REQUEST,
            detail=(
                "La cantidad de tipos de "
                "documento no coincide con "
                "la cantidad de archivos."
            ),
        )

    if any(
        not tipo
        for tipo in tipos_limpios
    ):
        raise HTTPException(
            status_code=
                status.HTTP_400_BAD_REQUEST,
            detail=(
                "Todos los documentos deben "
                "tener un tipo identificado."
            ),
        )

    if (
        len(
            set(
                tipos_limpios
            )
        )
        != len(
            tipos_limpios
        )
    ):
        raise HTTPException(
            status_code=
                status.HTTP_400_BAD_REQUEST,
            detail=(
                "No se puede adjuntar "
                "el mismo tipo de documento "
                "más de una vez."
            ),
        )

    documentos_requeridos = set(
        configuracion_tipo[
            "documentos"
        ]
    )

    documentos_recibidos = set(
        tipos_limpios
    )

    faltantes = (
        documentos_requeridos
        - documentos_recibidos
    )

    if faltantes:
        faltantes_texto = ", ".join(
            sorted(
                faltantes
            )
        )

        raise HTTPException(
            status_code=
                status.HTTP_400_BAD_REQUEST,
            detail=(
                "Faltan documentos "
                "obligatorios: "
                f"{faltantes_texto}."
            ),
        )

    adicionales = (
        documentos_recibidos
        - documentos_requeridos
    )

    if adicionales:
        adicionales_texto = ", ".join(
            sorted(
                adicionales
            )
        )

        raise HTTPException(
            status_code=
                status.HTTP_400_BAD_REQUEST,
            detail=(
                "Se recibieron documentos "
                "que no corresponden al "
                "tipo de incapacidad: "
                f"{adicionales_texto}."
            ),
        )

    return tipos_limpios


def _validar_documentos_parciales(
    configuracion_tipo: dict,
    tipos_documento: list[str],
    cantidad_archivos: int,
) -> list[str]:
    tipos_limpios = [
        _normalizar_texto(
            tipo
        )
        for tipo in tipos_documento
    ]

    if (
        len(tipos_limpios)
        != cantidad_archivos
    ):
        raise HTTPException(
            status_code=
                status.HTTP_400_BAD_REQUEST,
            detail=(
                "La cantidad de tipos de "
                "documento no coincide con "
                "la cantidad de archivos."
            ),
        )

    if any(
        not tipo
        for tipo in tipos_limpios
    ):
        raise HTTPException(
            status_code=
                status.HTTP_400_BAD_REQUEST,
            detail=(
                "Todos los documentos deben "
                "tener un tipo identificado."
            ),
        )

    documentos_permitidos = set(
        configuracion_tipo[
            "documentos"
        ]
    )

    adicionales = (
        set(tipos_limpios)
        - documentos_permitidos
    )

    if adicionales:
        adicionales_texto = ", ".join(
            sorted(
                adicionales
            )
        )

        raise HTTPException(
            status_code=
                status.HTTP_400_BAD_REQUEST,
            detail=(
                "Se recibieron documentos "
                "que no corresponden al "
                "tipo de incapacidad: "
                f"{adicionales_texto}."
            ),
        )

    return tipos_limpios


def _obtener_borrador_actual(
    db: Session,
    id_registro_personal: int,
) -> IncapacidadTrabajador | None:
    return (
        db.query(
            IncapacidadTrabajador
        )
        .filter(
            IncapacidadTrabajador.IdRegistroPersonal
            == id_registro_personal,
            IncapacidadTrabajador.Estado
            == "BORRADOR",
            IncapacidadTrabajador.Activo
            .is_(True),
        )
        .order_by(
            IncapacidadTrabajador
            .IdIncapacidadTrabajador
            .desc()
        )
        .first()
    )


def _obtener_documentos_activos(
    db: Session,
    id_incapacidad: int,
) -> list[DocumentoIncapacidadTrabajador]:
    return (
        db.query(
            DocumentoIncapacidadTrabajador
        )
        .filter(
            DocumentoIncapacidadTrabajador
            .IdIncapacidadTrabajador
            == id_incapacidad,
            DocumentoIncapacidadTrabajador
            .Activo
            .is_(True),
        )
        .order_by(
            DocumentoIncapacidadTrabajador
            .IdDocumentoIncapacidadTrabajador
            .asc()
        )
        .all()
    )


def _documento_a_dict(
    documento: DocumentoIncapacidadTrabajador,
) -> dict:
    return {
        "id_documento":
            int(
                documento
                .IdDocumentoIncapacidadTrabajador
            ),
        "tipo_documento":
            documento.TipoDocumento,
        "nombre_archivo":
            documento.NombreArchivo,
        "formato":
            documento.Formato,
        "mime_type":
            documento.MimeType,
        "tamano_bytes":
            documento.TamanoBytes,
    }


def _borrador_a_dict(
    db: Session,
    borrador: IncapacidadTrabajador,
) -> dict:
    documentos = (
        _obtener_documentos_activos(
            db=db,
            id_incapacidad=int(
                borrador
                .IdIncapacidadTrabajador
            ),
        )
    )

    return {
        "id_incapacidad":
            int(
                borrador
                .IdIncapacidadTrabajador
            ),
        "estado":
            borrador.Estado,
        "tipo_incapacidad":
            borrador.TipoIncapacidad,
        "descripcion_tipo":
            borrador
            .DescripcionTipoIncapacidad,
        "fecha_inicio":
            borrador.FechaInicio,
        "dias_incapacidad":
            borrador.DiasIncapacidad,
        "fecha_final":
            borrador.FechaFinal,
        "es_prorroga":
            borrador.EsProrroga,
        "documentos": [
            _documento_a_dict(
                documento
            )
            for documento
            in documentos
        ],
    }



def _incapacidad_historial_a_dict(
    db: Session,
    incapacidad: IncapacidadTrabajador,
) -> dict:
    documentos = (
        _obtener_documentos_activos(
            db=db,
            id_incapacidad=int(
                incapacidad
                .IdIncapacidadTrabajador
            ),
        )
    )

    return {
        "id_incapacidad":
            int(
                incapacidad
                .IdIncapacidadTrabajador
            ),
        "estado":
            incapacidad.Estado,
        "tipo_incapacidad":
            incapacidad.TipoIncapacidad,
        "descripcion_tipo":
            incapacidad
            .DescripcionTipoIncapacidad,
        "fecha_inicio":
            incapacidad.FechaInicio,
        "dias_incapacidad":
            incapacidad.DiasIncapacidad,
        "fecha_final":
            incapacidad.FechaFinal,
        "es_prorroga":
            incapacidad.EsProrroga,
        "fecha_creacion":
            incapacidad.FechaCreacion,
        "fecha_actualizacion":
            incapacidad.FechaActualizacion,
        "documentos": [
            _documento_a_dict(
                documento
            )
            for documento
            in documentos
        ],
    }


def _marcar_documentos_no_validos_por_tipo(
    db: Session,
    borrador: IncapacidadTrabajador,
    configuracion_tipo: dict,
) -> None:
    permitidos = set(
        configuracion_tipo[
            "documentos"
        ]
    )

    documentos = (
        _obtener_documentos_activos(
            db=db,
            id_incapacidad=int(
                borrador
                .IdIncapacidadTrabajador
            ),
        )
    )

    ahora = datetime.now(
        timezone.utc
    )

    for documento in documentos:
        if (
            documento.TipoDocumento
            not in permitidos
        ):
            documento.Activo = False

            if hasattr(
                documento,
                "FechaActualizacion",
            ):
                documento.FechaActualizacion = (
                    ahora
                )


def _reemplazar_documento_si_existe(
    db: Session,
    id_incapacidad: int,
    tipo_documento: str,
) -> None:
    existentes = (
        db.query(
            DocumentoIncapacidadTrabajador
        )
        .filter(
            DocumentoIncapacidadTrabajador
            .IdIncapacidadTrabajador
            == id_incapacidad,
            DocumentoIncapacidadTrabajador
            .TipoDocumento
            == tipo_documento,
            DocumentoIncapacidadTrabajador
            .Activo
            .is_(True),
        )
        .all()
    )

    ahora = datetime.now(
        timezone.utc
    )

    for documento in existentes:
        documento.Activo = False

        if hasattr(
            documento,
            "FechaActualizacion",
        ):
            documento.FechaActualizacion = (
                ahora
            )


def _crear_documento(
    incapacidad: IncapacidadTrabajador,
    documento: dict,
) -> DocumentoIncapacidadTrabajador:
    return (
        DocumentoIncapacidadTrabajador(
            IdIncapacidadTrabajador=
                incapacidad
                .IdIncapacidadTrabajador,
            TipoDocumento=
                documento[
                    "tipo_documento"
                ],
            NombreArchivo=
                documento[
                    "nombre_archivo"
                ],
            Formato=
                documento[
                    "extension"
                ],
            MimeType=
                documento[
                    "mime_type"
                ],
            TamanoBytes=
                documento[
                    "tamano_bytes"
                ],
            DocumentoCargado=
                documento[
                    "contenido"
                ],
            Activo=
                True,
        )
    )


@router.get(
    "",
    status_code=
        status.HTTP_200_OK,
)
def listar_incapacidades_trabajador(
    db: Session = Depends(get_db),
    current: dict = Depends(
        get_current_trabajador
    ),
):
    """
    Lista únicamente las incapacidades
    registradas del trabajador autenticado.

    El IdRegistroPersonal se obtiene
    exclusivamente del JWT.

    Los registros BORRADOR no se incluyen
    en el historial de Mis incapacidades.
    """

    id_registro_personal = int(
        current[
            "id_registro_personal"
        ]
    )

    incapacidades = (
        db.query(
            IncapacidadTrabajador
        )
        .filter(
            IncapacidadTrabajador
            .IdRegistroPersonal
            == id_registro_personal,
            IncapacidadTrabajador
            .Activo
            .is_(True),
            IncapacidadTrabajador
            .Estado
            != "BORRADOR",
        )
        .order_by(
            IncapacidadTrabajador
            .IdIncapacidadTrabajador
            .desc()
        )
        .all()
    )

    return {
        "total":
            len(
                incapacidades
            ),
        "incapacidades": [
            _incapacidad_historial_a_dict(
                db=db,
                incapacidad=
                    incapacidad,
            )
            for incapacidad
            in incapacidades
        ],
    }


@router.get(
    "/borrador",
)
def obtener_borrador_trabajador(
    db: Session = Depends(get_db),
    current: dict = Depends(
        get_current_trabajador
    ),
):
    id_registro_personal = int(
        current[
            "id_registro_personal"
        ]
    )

    borrador = (
        _obtener_borrador_actual(
            db=db,
            id_registro_personal=
                id_registro_personal,
        )
    )

    if not borrador:
        return {
            "tiene_borrador":
                False,
            "borrador":
                None,
        }

    return {
        "tiene_borrador":
            True,
        "borrador":
            _borrador_a_dict(
                db=db,
                borrador=borrador,
            ),
    }


@router.post(
    "/borrador",
    status_code=
        status.HTTP_200_OK,
)
async def guardar_borrador_trabajador(
    tipo_incapacidad: str = Form(...),
    fecha_inicio: date = Form(...),
    dias_incapacidad: int = Form(...),
    es_prorroga: str = Form(...),
    tipos_documento: list[str] = Form(
        default=[]
    ),
    archivos: list[UploadFile] = File(
        default=[]
    ),
    db: Session = Depends(get_db),
    current: dict = Depends(
        get_current_trabajador
    ),
):
    tipo_normalizado = (
        _normalizar_tipo_incapacidad(
            tipo_incapacidad
        )
    )

    configuracion_tipo = (
        _validar_tipo_incapacidad(
            tipo_normalizado
        )
    )

    _validar_dias_incapacidad(
        tipo_incapacidad=
            tipo_normalizado,
        dias_incapacidad=
            dias_incapacidad,
    )

    prorroga = (
        _convertir_es_prorroga(
            es_prorroga
        )
    )

    fecha_final = (
        _calcular_fecha_final(
            fecha_inicio=
                fecha_inicio,
            dias_incapacidad=
                dias_incapacidad,
        )
    )

    tipos_limpios = (
        _validar_documentos_parciales(
            configuracion_tipo=
                configuracion_tipo,
            tipos_documento=
                tipos_documento,
            cantidad_archivos=
                len(archivos),
        )
    )

    documentos_validados = []

    for (
        tipo_documento,
        archivo,
    ) in zip(
        tipos_limpios,
        archivos,
    ):
        datos_archivo = (
            await _leer_y_validar_archivo(
                archivo=
                    archivo,
                tipo_documento=
                    tipo_documento,
            )
        )

        documentos_validados.append(
            {
                "tipo_documento":
                    tipo_documento,
                **datos_archivo,
            }
        )

    id_registro_personal = int(
        current[
            "id_registro_personal"
        ]
    )

    try:
        borrador = (
            _obtener_borrador_actual(
                db=db,
                id_registro_personal=
                    id_registro_personal,
            )
        )

        if not borrador:
            borrador = (
                IncapacidadTrabajador(
                    IdRegistroPersonal=
                        id_registro_personal,
                    TipoIncapacidad=
                        tipo_normalizado,
                    DescripcionTipoIncapacidad=
                        configuracion_tipo[
                            "descripcion"
                        ],
                    FechaInicio=
                        fecha_inicio,
                    DiasIncapacidad=
                        dias_incapacidad,
                    FechaFinal=
                        fecha_final,
                    EsProrroga=
                        prorroga,
                    Estado=
                        "BORRADOR",
                    Activo=
                        True,
                )
            )

            db.add(
                borrador
            )

            db.flush()

        else:
            borrador.TipoIncapacidad = (
                tipo_normalizado
            )

            borrador.DescripcionTipoIncapacidad = (
                configuracion_tipo[
                    "descripcion"
                ]
            )

            borrador.FechaInicio = (
                fecha_inicio
            )

            borrador.DiasIncapacidad = (
                dias_incapacidad
            )

            borrador.FechaFinal = (
                fecha_final
            )

            borrador.EsProrroga = (
                prorroga
            )

            if hasattr(
                borrador,
                "FechaActualizacion",
            ):
                borrador.FechaActualizacion = (
                    datetime.now(
                        timezone.utc
                    )
                )

        _marcar_documentos_no_validos_por_tipo(
            db=db,
            borrador=borrador,
            configuracion_tipo=
                configuracion_tipo,
        )

        for documento in (
            documentos_validados
        ):
            _reemplazar_documento_si_existe(
                db=db,
                id_incapacidad=int(
                    borrador
                    .IdIncapacidadTrabajador
                ),
                tipo_documento=
                    documento[
                        "tipo_documento"
                    ],
            )

            db.add(
                _crear_documento(
                    incapacidad=
                        borrador,
                    documento=
                        documento,
                )
            )

        db.commit()

        db.refresh(
            borrador
        )

    except HTTPException:
        db.rollback()
        raise

    except Exception as exc:
        db.rollback()

        raise HTTPException(
            status_code=
                status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=(
                "No fue posible guardar "
                "el borrador de la incapacidad."
            ),
        ) from exc

    return {
        "message":
            "Borrador guardado correctamente.",
        "tiene_borrador":
            True,
        "borrador":
            _borrador_a_dict(
                db=db,
                borrador=borrador,
            ),
    }


@router.delete(
    "/borrador",
    status_code=
        status.HTTP_200_OK,
)
def eliminar_borrador_trabajador(
    db: Session = Depends(get_db),
    current: dict = Depends(
        get_current_trabajador
    ),
):
    id_registro_personal = int(
        current[
            "id_registro_personal"
        ]
    )

    borrador = (
        _obtener_borrador_actual(
            db=db,
            id_registro_personal=
                id_registro_personal,
        )
    )

    if not borrador:
        return {
            "message":
                "No existe un borrador pendiente.",
        }

    try:
        borrador.Activo = False

        if hasattr(
            borrador,
            "FechaActualizacion",
        ):
            borrador.FechaActualizacion = (
                datetime.now(
                    timezone.utc
                )
            )

        documentos = (
            _obtener_documentos_activos(
                db=db,
                id_incapacidad=int(
                    borrador
                    .IdIncapacidadTrabajador
                ),
            )
        )

        for documento in documentos:
            documento.Activo = False

            if hasattr(
                documento,
                "FechaActualizacion",
            ):
                documento.FechaActualizacion = (
                    datetime.now(
                        timezone.utc
                    )
                )

        db.commit()

    except Exception as exc:
        db.rollback()

        raise HTTPException(
            status_code=
                status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=(
                "No fue posible descartar "
                "el borrador de la incapacidad."
            ),
        ) from exc

    return {
        "message":
            "Borrador descartado correctamente.",
    }


@router.get(
    "/borrador/documentos/{id_documento}",
)
def ver_documento_borrador(
    id_documento: int,
    db: Session = Depends(get_db),
    current: dict = Depends(
        get_current_trabajador
    ),
):
    id_registro_personal = int(
        current[
            "id_registro_personal"
        ]
    )

    documento = (
        db.query(
            DocumentoIncapacidadTrabajador
        )
        .join(
            IncapacidadTrabajador,
            IncapacidadTrabajador
            .IdIncapacidadTrabajador
            == DocumentoIncapacidadTrabajador
            .IdIncapacidadTrabajador,
        )
        .filter(
            DocumentoIncapacidadTrabajador
            .IdDocumentoIncapacidadTrabajador
            == id_documento,
            DocumentoIncapacidadTrabajador
            .Activo
            .is_(True),
            IncapacidadTrabajador
            .IdRegistroPersonal
            == id_registro_personal,
            IncapacidadTrabajador.Estado
            == "BORRADOR",
            IncapacidadTrabajador.Activo
            .is_(True),
        )
        .first()
    )

    if not documento:
        raise HTTPException(
            status_code=
                status.HTTP_404_NOT_FOUND,
            detail=(
                "El documento del borrador "
                "no existe o no pertenece "
                "al trabajador autenticado."
            ),
        )

    contenido = (
        documento.DocumentoCargado
        or b""
    )

    if not contenido:
        raise HTTPException(
            status_code=
                status.HTTP_404_NOT_FOUND,
            detail=(
                "El documento no contiene "
                "información para visualizar."
            ),
        )

    headers = {
        "Content-Disposition":
            (
                'inline; filename="'
                f'{documento.NombreArchivo}"'
            )
    }

    return Response(
        content=contenido,
        media_type=(
            documento.MimeType
            or "application/octet-stream"
        ),
        headers=headers,
    )


@router.get(
    "/{id_incapacidad}/documentos/{id_documento}",
)
def ver_documento_incapacidad_trabajador(
    id_incapacidad: int,
    id_documento: int,
    db: Session = Depends(get_db),
    current: dict = Depends(
        get_current_trabajador
    ),
):
    """
    Permite visualizar un documento activo
    de una incapacidad registrada.

    Se valida que tanto la incapacidad como
    el documento pertenezcan al trabajador
    autenticado.
    """

    id_registro_personal = int(
        current[
            "id_registro_personal"
        ]
    )

    documento = (
        db.query(
            DocumentoIncapacidadTrabajador
        )
        .join(
            IncapacidadTrabajador,
            IncapacidadTrabajador
            .IdIncapacidadTrabajador
            == DocumentoIncapacidadTrabajador
            .IdIncapacidadTrabajador,
        )
        .filter(
            IncapacidadTrabajador
            .IdIncapacidadTrabajador
            == id_incapacidad,
            IncapacidadTrabajador
            .IdRegistroPersonal
            == id_registro_personal,
            IncapacidadTrabajador
            .Activo
            .is_(True),
            IncapacidadTrabajador
            .Estado
            != "BORRADOR",
            DocumentoIncapacidadTrabajador
            .IdDocumentoIncapacidadTrabajador
            == id_documento,
            DocumentoIncapacidadTrabajador
            .IdIncapacidadTrabajador
            == id_incapacidad,
            DocumentoIncapacidadTrabajador
            .Activo
            .is_(True),
        )
        .first()
    )

    if not documento:
        raise HTTPException(
            status_code=
                status.HTTP_404_NOT_FOUND,
            detail=(
                "El documento no existe, "
                "no está activo o no pertenece "
                "al trabajador autenticado."
            ),
        )

    contenido = (
        documento.DocumentoCargado
        or b""
    )

    if not contenido:
        raise HTTPException(
            status_code=
                status.HTTP_404_NOT_FOUND,
            detail=(
                "El documento no contiene "
                "información para visualizar."
            ),
        )

    headers = {
        "Content-Disposition":
            (
                'inline; filename="'
                f'{documento.NombreArchivo}"'
            )
    }

    return Response(
        content=contenido,
        media_type=(
            documento.MimeType
            or "application/octet-stream"
        ),
        headers=headers,
    )


@router.post(
    "",
    status_code=
        status.HTTP_201_CREATED,
)
async def registrar_incapacidad_trabajador(
    tipo_incapacidad: str = Form(...),
    fecha_inicio: date = Form(...),
    dias_incapacidad: int = Form(...),
    es_prorroga: str = Form(...),
    tipos_documento: list[str] = Form(
        default=[]
    ),
    archivos: list[UploadFile] = File(
        default=[]
    ),
    db: Session = Depends(get_db),
    current: dict = Depends(
        get_current_trabajador
    ),
):
    """
    Registra una incapacidad desde
    el Portal del Trabajador.

    Si existe un BORRADOR activo,
    se reutiliza el mismo registro
    y se convierte en REGISTRADA.

    El IdRegistroPersonal se obtiene
    exclusivamente del JWT del trabajador.
    """

    tipo_normalizado = (
        _normalizar_tipo_incapacidad(
            tipo_incapacidad
        )
    )

    configuracion_tipo = (
        _validar_tipo_incapacidad(
            tipo_normalizado
        )
    )

    _validar_dias_incapacidad(
        tipo_incapacidad=
            tipo_normalizado,
        dias_incapacidad=
            dias_incapacidad,
    )

    prorroga = (
        _convertir_es_prorroga(
            es_prorroga
        )
    )

    fecha_final = (
        _calcular_fecha_final(
            fecha_inicio=
                fecha_inicio,
            dias_incapacidad=
                dias_incapacidad,
        )
    )

    tipos_limpios = (
        _validar_documentos_parciales(
            configuracion_tipo=
                configuracion_tipo,
            tipos_documento=
                tipos_documento,
            cantidad_archivos=
                len(archivos),
        )
    )

    documentos_validados = []

    for (
        tipo_documento,
        archivo,
    ) in zip(
        tipos_limpios,
        archivos,
    ):
        datos_archivo = (
            await _leer_y_validar_archivo(
                archivo=
                    archivo,
                tipo_documento=
                    tipo_documento,
            )
        )

        documentos_validados.append(
            {
                "tipo_documento":
                    tipo_documento,
                **datos_archivo,
            }
        )

    id_registro_personal = int(
        current[
            "id_registro_personal"
        ]
    )

    try:
        incapacidad = (
            _obtener_borrador_actual(
                db=db,
                id_registro_personal=
                    id_registro_personal,
            )
        )

        if not incapacidad:
            incapacidad = (
                IncapacidadTrabajador(
                    IdRegistroPersonal=
                        id_registro_personal,
                    TipoIncapacidad=
                        tipo_normalizado,
                    DescripcionTipoIncapacidad=
                        configuracion_tipo[
                            "descripcion"
                        ],
                    FechaInicio=
                        fecha_inicio,
                    DiasIncapacidad=
                        dias_incapacidad,
                    FechaFinal=
                        fecha_final,
                    EsProrroga=
                        prorroga,
                    Estado=
                        "REGISTRADA",
                    Activo=
                        True,
                )
            )

            db.add(
                incapacidad
            )

            db.flush()

        else:
            incapacidad.TipoIncapacidad = (
                tipo_normalizado
            )

            incapacidad.DescripcionTipoIncapacidad = (
                configuracion_tipo[
                    "descripcion"
                ]
            )

            incapacidad.FechaInicio = (
                fecha_inicio
            )

            incapacidad.DiasIncapacidad = (
                dias_incapacidad
            )

            incapacidad.FechaFinal = (
                fecha_final
            )

            incapacidad.EsProrroga = (
                prorroga
            )

            if hasattr(
                incapacidad,
                "FechaActualizacion",
            ):
                incapacidad.FechaActualizacion = (
                    datetime.now(
                        timezone.utc
                    )
                )

            _marcar_documentos_no_validos_por_tipo(
                db=db,
                borrador=incapacidad,
                configuracion_tipo=
                    configuracion_tipo,
            )

        for documento in (
            documentos_validados
        ):
            _reemplazar_documento_si_existe(
                db=db,
                id_incapacidad=int(
                    incapacidad
                    .IdIncapacidadTrabajador
                ),
                tipo_documento=
                    documento[
                        "tipo_documento"
                    ],
            )

            db.add(
                _crear_documento(
                    incapacidad=
                        incapacidad,
                    documento=
                        documento,
                )
            )

        db.flush()

        documentos_finales = (
            _obtener_documentos_activos(
                db=db,
                id_incapacidad=int(
                    incapacidad
                    .IdIncapacidadTrabajador
                ),
            )
        )

        tipos_finales = [
            _normalizar_texto(
                documento.TipoDocumento
            )
            for documento
            in documentos_finales
        ]

        _validar_documentos_recibidos(
            configuracion_tipo=
                configuracion_tipo,
            tipos_documento=
                tipos_finales,
            cantidad_archivos=
                len(tipos_finales),
        )

        incapacidad.Estado = (
            "REGISTRADA"
        )

        if hasattr(
            incapacidad,
            "FechaActualizacion",
        ):
            incapacidad.FechaActualizacion = (
                datetime.now(
                    timezone.utc
                )
            )

        db.commit()

        db.refresh(
            incapacidad
        )

    except HTTPException:
        db.rollback()
        raise

    except Exception as exc:
        db.rollback()

        raise HTTPException(
            status_code=
                status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=(
                "No fue posible registrar "
                "la incapacidad."
            ),
        ) from exc

    return {
        "message":
            "Incapacidad registrada correctamente.",
        "id_incapacidad":
            int(
                incapacidad
                .IdIncapacidadTrabajador
            ),
        "estado":
            incapacidad.Estado,
        "tipo_incapacidad":
            incapacidad.TipoIncapacidad,
        "descripcion_tipo":
            incapacidad
            .DescripcionTipoIncapacidad,
        "fecha_inicio":
            incapacidad
            .FechaInicio,
        "dias_incapacidad":
            incapacidad
            .DiasIncapacidad,
        "fecha_final":
            incapacidad
            .FechaFinal,
        "es_prorroga":
            incapacidad
            .EsProrroga,
        "documentos_registrados":
            len(
                _obtener_documentos_activos(
                    db=db,
                    id_incapacidad=int(
                        incapacidad
                        .IdIncapacidadTrabajador
                    ),
                )
            ),
    }
