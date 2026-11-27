import logging
import os
from datetime import date
from decimal import Decimal

from sqlalchemy import text
from sqlalchemy.orm import Session

from utilidades.drive_oauth_service import get_sheets_service


logger = logging.getLogger(__name__)


NOMBRE_HOJA = "INCAPACIDADES"

ARL_ACCIDENTE_TRABAJO = (
    "SEGUROS DE VIDA SURAMERICANA S.A."
)

ESTADOS_GOOGLE_SHEETS = {
    "PAGADO": "PAGADA",
    "NEGADO": "NEGADA",
    "SIN RECOBRO": "SIN RECOBRO",
}

ENCABEZADOS = [
    "AÑO",
    "MES",
    "DOCUMENTO",
    "NOMBRES Y APELLIDOS",
    "FECHA INICIAL",
    "FECHA FINAL",
    "DIAS TOTALES",
    "INDICADOR DE PRORROGA",
    "VALOR 3 DIAS",
    "DIAS (3)",
    "VALOR 2 DIAS",
    "DIAS (2)",
    "TIPO DE INCAPACIDAD",
    "EPS",
    "# RADICADO",
    "FECHA DE RADICADO",
    "FECHA DE PAGO",
    "VALOR PAGADO",
    "DIFERENCIA",
    "ESTADO INCAPACIDADES",
    "OBSERVACIONES",
    "IdIncapacidadTrabajador",
]


def _obtener_spreadsheet_id() -> str:
    spreadsheet_id = os.getenv(
        "GOOGLE_SHEETS_INCAPACIDADES_ID", ""
    ).strip()

    if not spreadsheet_id:
        raise RuntimeError(
            "No se ha configurado "
            "GOOGLE_SHEETS_INCAPACIDADES_ID."
        )

    return spreadsheet_id


def _formatear_fecha(valor):
    if valor is None or valor == "":
        return ""

    if isinstance(valor, date):
        return (valor - date(1899, 12, 30)).days

    raise ValueError(
        f"Formato de fecha no válido: {valor}"
    )


def _formatear_texto(valor) -> str:
    if valor is None:
        return ""

    return str(valor).strip()


def _formatear_valor(valor):
    if valor is None:
        return ""

    if isinstance(valor, Decimal):
        return float(valor)

    return valor


def obtener_datos_incapacidad(
    db: Session,
    id_incapacidad: int,
):
    consulta = text(
        """
        SELECT
            i."IdIncapacidadTrabajador",
            rp."NumeroIdentificacion",
            rp."Nombres",
            rp."Apellidos",
            i."FechaInicio",
            i."FechaFinal",
            i."DiasIncapacidad",
            i."EsProrroga",
            i."TipoIncapacidad",
            i."DescripcionTipoIncapacidad",
            te."Descripcion" AS "Eps",
            i."NumeroRadicado",
            i."FechaRadicacion",
            i."FechaPago",
            i."ValorPagado",
            i."Estado"
        FROM public."IncapacidadTrabajador" i
        INNER JOIN public."RegistroPersonal" rp
            ON rp."IdRegistroPersonal" =
               i."IdRegistroPersonal"
        LEFT JOIN public."TipoEps" te
            ON te."IdTipoEps" = rp."IdTipoEps"
        WHERE
            i."IdIncapacidadTrabajador" = :id_incapacidad
            AND i."Activo" = TRUE
            AND UPPER(COALESCE(i."Estado", ''))
                <> 'BORRADOR'
        LIMIT 1
        """
    )

    return db.execute(
        consulta,
        {
            "id_incapacidad": id_incapacidad,
        },
    ).mappings().first()


def construir_datos_google_sheets(datos) -> dict:
    fecha_inicio = datos["FechaInicio"]

    nombre_completo = (
        f'{datos["Nombres"] or ""} '
        f'{datos["Apellidos"] or ""}'
    ).strip().upper()

    tipo_incapacidad = _formatear_texto(
        datos["TipoIncapacidad"]
    ).upper()

    estado = _formatear_texto(
        datos["Estado"]
    ).upper()

    if tipo_incapacidad == "ACCIDENTE_TRABAJO":
        eps = ARL_ACCIDENTE_TRABAJO
    else:
        eps = _formatear_texto(
            datos["Eps"]
        ).upper()

    return {
        "A": fecha_inicio.year if fecha_inicio else "",
        "C": _formatear_texto(
            datos["NumeroIdentificacion"]
        ),
        "D": nombre_completo,
        "E": _formatear_fecha(datos["FechaInicio"]),
        "F": _formatear_fecha(datos["FechaFinal"]),
        "G": datos["DiasIncapacidad"],
        "H": "S" if datos["EsProrroga"] else "N",
        "M": _formatear_texto(
            datos["DescripcionTipoIncapacidad"]
        ).upper(),
        "N": eps,
        "O": _formatear_texto(datos["NumeroRadicado"]),
        "P": _formatear_fecha(datos["FechaRadicacion"]),
        "Q": _formatear_fecha(datos["FechaPago"]),
        "R": _formatear_valor(datos["ValorPagado"]),
        "T": ESTADOS_GOOGLE_SHEETS.get(estado, ""),
        "V": str(datos["IdIncapacidadTrabajador"]),
    }


def _validar_encabezados(
    service,
    spreadsheet_id: str,
) -> None:
    respuesta = (
        service.spreadsheets()
        .values()
        .get(
            spreadsheetId=spreadsheet_id,
            range=f"{NOMBRE_HOJA}!A1:V1",
        )
        .execute()
    )

    filas = respuesta.get("values", [])

    if not filas or filas[0] != ENCABEZADOS:
        raise RuntimeError(
            "Los encabezados del Google Sheets "
            "de incapacidades no coinciden "
            "con la estructura esperada."
        )


def _buscar_fila_incapacidad(
    service,
    spreadsheet_id: str,
    id_incapacidad: int,
):
    respuesta = (
        service.spreadsheets()
        .values()
        .get(
            spreadsheetId=spreadsheet_id,
            range=f"{NOMBRE_HOJA}!V2:V",
        )
        .execute()
    )

    filas = respuesta.get("values", [])
    identificador = str(id_incapacidad).strip()

    coincidencias = []

    for numero_fila, fila in enumerate(
        filas,
        start=2,
    ):
        if fila and str(fila[0]).strip() == identificador:
            coincidencias.append(numero_fila)

    if len(coincidencias) > 1:
        raise RuntimeError(
            f"Se encontraron filas duplicadas "
            f"para la incapacidad {id_incapacidad}."
        )

    return coincidencias[0] if coincidencias else None


def _crear_fila_incapacidad(
    service,
    spreadsheet_id: str,
    datos: dict,
):
    fila = [
        datos.get(chr(65 + indice), "")
        for indice in range(22)
    ]

    return (
        service.spreadsheets()
        .values()
        .append(
            spreadsheetId=spreadsheet_id,
            range=f"{NOMBRE_HOJA}!A1:V",
            valueInputOption="RAW",
            insertDataOption="INSERT_ROWS",
            body={
                "values": [fila],
            },
        )
        .execute()
    )


def _actualizar_fila_incapacidad(
    service,
    spreadsheet_id: str,
    numero_fila: int,
    datos: dict,
):
    actualizaciones = []

    for columna, valor in datos.items():
        actualizaciones.append(
            {
                "range": (
                    f"{NOMBRE_HOJA}!"
                    f"{columna}{numero_fila}"
                ),
                "values": [[valor]],
            }
        )

    return (
        service.spreadsheets()
        .values()
        .batchUpdate(
            spreadsheetId=spreadsheet_id,
            body={
                "valueInputOption": "RAW",
                "data": actualizaciones,
            },
        )
        .execute()
    )


def sincronizar_incapacidad_google_sheets(
    db: Session,
    id_incapacidad: int,
) -> dict:
    try:
        datos = obtener_datos_incapacidad(
            db=db,
            id_incapacidad=id_incapacidad,
        )

        if not datos:
            return {
                "success": False,
                "id_incapacidad": id_incapacidad,
                "message": (
                    "La incapacidad no existe, "
                    "está inactiva o es un borrador."
                ),
            }

        spreadsheet_id = _obtener_spreadsheet_id()

        service = get_sheets_service()

        _validar_encabezados(
            service=service,
            spreadsheet_id=spreadsheet_id,
        )

        datos_sheet = construir_datos_google_sheets(
            datos
        )

        numero_fila = _buscar_fila_incapacidad(
            service=service,
            spreadsheet_id=spreadsheet_id,
            id_incapacidad=id_incapacidad,
        )

        if numero_fila is None:
            _crear_fila_incapacidad(
                service=service,
                spreadsheet_id=spreadsheet_id,
                datos=datos_sheet,
            )

            accion = "CREADA"

        else:
            _actualizar_fila_incapacidad(
                service=service,
                spreadsheet_id=spreadsheet_id,
                numero_fila=numero_fila,
                datos=datos_sheet,
            )

            accion = "ACTUALIZADA"

        logger.info(
            "Incapacidad %s sincronizada: %s",
            id_incapacidad,
            accion,
        )

        return {
            "success": True,
            "id_incapacidad": id_incapacidad,
            "accion": accion,
        }

    except Exception:
        logger.exception(
            "Error sincronizando incapacidad %s "
            "con Google Sheets.",
            id_incapacidad,
        )

        return {
            "success": False,
            "id_incapacidad": id_incapacidad,
            "message": (
                "No fue posible sincronizar "
                "la incapacidad con Google Sheets."
            ),
        }
