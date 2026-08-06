from datetime import date, time
from html import escape

from sqlalchemy import text
from sqlalchemy.orm import Session

from services.email_service import enviar_correo_sin_adjunto
from services.notificacion_proceso_disciplinario_service import (
    crear_notificacion,
    marcar_notificacion_enviada,
    marcar_notificacion_error,
)


TIPO_CITACION_INICIAL = "CITACION_INICIAL"
TIPO_REPROGRAMACION = "REPROGRAMACION"
TIPO_CANCELACION = "CANCELACION"

DESTINATARIO_SIN_CORREO = "SIN_CORREO_REGISTRADO"


def _limpiar_texto(
    valor: object,
    valor_defecto: str = "",
) -> str:
    texto = str(
        valor if valor is not None else valor_defecto
    ).strip()

    return texto or valor_defecto


def _formatear_fecha_colombia(
    valor: date | None,
) -> str:
    if valor is None:
        return "Por confirmar"

    meses = (
        "enero",
        "febrero",
        "marzo",
        "abril",
        "mayo",
        "junio",
        "julio",
        "agosto",
        "septiembre",
        "octubre",
        "noviembre",
        "diciembre",
    )

    dias = (
        "lunes",
        "martes",
        "miércoles",
        "jueves",
        "viernes",
        "sábado",
        "domingo",
    )

    return (
        f"{dias[valor.weekday()]} "
        f"{valor.day} de "
        f"{meses[valor.month - 1]} de "
        f"{valor.year}"
    )


def _formatear_hora_colombia(
    valor: time | None,
) -> str:
    if valor is None:
        return "Por confirmar"

    hora = valor.hour
    minutos = valor.minute

    periodo = "a. m." if hora < 12 else "p. m."

    hora_12 = hora % 12

    if hora_12 == 0:
        hora_12 = 12

    return f"{hora_12}:{minutos:02d} {periodo}"


def obtener_datos_notificacion_agenda(
    db: Session,
    id_agenda: int,
) -> dict:
    consulta = text("""
        SELECT
            ag."IdAgendaProcesoDisciplinario",
            ag."IdProcesoDisciplinario",
            ag."IdRegistroPersonal",
            ag."IdTipoEventoDisciplinario",
            ag."FechaEvento",
            ag."HoraInicio",
            ag."HoraFin",
            ag."Modalidad" AS "ModalidadAgenda",
            ag."Observacion" AS "ObservacionAgenda",
            ag."EstadoAgenda",
            ag."UsuarioAgenda",

            rp."NumeroIdentificacion",
            rp."Nombres",
            rp."Apellidos",
            rp."Email",

            te."Nombre" AS "TipoEvento",

            citacion."IdCitacionProcesoDisciplinario",
            citacion."LugarCitacion",
            citacion."MotivoCitacion",
            citacion."ResponsableCitacion",
            citacion."Modalidad" AS "ModalidadCitacion",
            citacion."Cliente",
            citacion."Sede"

        FROM public."AgendaProcesoDisciplinario" ag

        INNER JOIN public."ProcesoDisciplinario" pd
            ON pd."IdProcesoDisciplinario"
             = ag."IdProcesoDisciplinario"

        INNER JOIN public."RegistroPersonal" rp
            ON rp."IdRegistroPersonal"
             = ag."IdRegistroPersonal"

        LEFT JOIN public."TipoEventoDisciplinario" te
            ON te."IdTipoEventoDisciplinario"
             = ag."IdTipoEventoDisciplinario"

        LEFT JOIN LATERAL (
            SELECT
                cp."IdCitacionProcesoDisciplinario",
                cp."LugarCitacion",
                cp."MotivoCitacion",
                cp."ResponsableCitacion",
                cp."Modalidad",
                cp."Cliente",
                cp."Sede"
            FROM public."CitacionProcesoDisciplinario" cp
            WHERE cp."IdProcesoDisciplinario"
                = ag."IdProcesoDisciplinario"
            ORDER BY
                cp."IdCitacionProcesoDisciplinario" DESC
            LIMIT 1
        ) citacion ON TRUE

        WHERE ag."IdAgendaProcesoDisciplinario" = :id_agenda
        LIMIT 1;
    """)

    fila = db.execute(
        consulta,
        {
            "id_agenda": id_agenda,
        },
    ).mappings().first()

    if not fila:
        raise ValueError(
            "No se encontró el evento de agenda disciplinaria."
        )

    return dict(fila)


def _obtener_asunto(
    tipo_notificacion: str,
) -> str:
    tipo = _limpiar_texto(
        tipo_notificacion
    ).upper()

    if tipo == TIPO_REPROGRAMACION:
        return (
            "Reprogramación de citación laboral "
            "- Aseos La Perfección"
        )

    if tipo == TIPO_CANCELACION:
        return (
            "Cancelación de citación laboral "
            "- Aseos La Perfección"
        )

    return (
        "Citación laboral "
        "- Aseos La Perfección"
    )


def _obtener_titulo(
    tipo_notificacion: str,
) -> str:
    tipo = _limpiar_texto(
        tipo_notificacion
    ).upper()

    if tipo == TIPO_REPROGRAMACION:
        return "Reprogramación de citación laboral"

    if tipo == TIPO_CANCELACION:
        return "Cancelación de citación laboral"

    return "Citación laboral"


def _construir_contenido_correo(
    datos: dict,
    tipo_notificacion: str,
) -> tuple[str, str]:
    nombre_completo = " ".join(
        parte
        for parte in (
            _limpiar_texto(datos.get("Nombres")),
            _limpiar_texto(datos.get("Apellidos")),
        )
        if parte
    )

    documento = _limpiar_texto(
        datos.get("NumeroIdentificacion"),
        "No registrado",
    )

    fecha = _formatear_fecha_colombia(
        datos.get("FechaEvento")
    )

    hora_inicio = _formatear_hora_colombia(
        datos.get("HoraInicio")
    )

    hora_fin = _formatear_hora_colombia(
        datos.get("HoraFin")
    )

    modalidad = _limpiar_texto(
        datos.get("ModalidadAgenda")
        or datos.get("ModalidadCitacion"),
        "Por confirmar",
    )

    motivo = _limpiar_texto(
        datos.get("MotivoCitacion")
        or datos.get("TipoEvento"),
        "Citación laboral",
    )

    lugar = _limpiar_texto(
        datos.get("LugarCitacion"),
        "Por confirmar",
    )

    cliente = _limpiar_texto(
        datos.get("Cliente"),
    )

    sede = _limpiar_texto(
        datos.get("Sede"),
    )

    responsable = _limpiar_texto(
        datos.get("ResponsableCitacion"),
    )

    titulo = _obtener_titulo(
        tipo_notificacion
    )

    introduccion = (
        "Le informamos que su citación laboral "
        "ha sido reprogramada."
        if tipo_notificacion.upper()
        == TIPO_REPROGRAMACION
        else (
            "Le informamos que su citación laboral "
            "ha sido cancelada."
            if tipo_notificacion.upper()
            == TIPO_CANCELACION
            else (
                "Le informamos que ha sido citado(a) "
                "para atender un asunto laboral."
            )
        )
    )

    lineas_adicionales = []

    if cliente:
        lineas_adicionales.append(
            f"Cliente: {cliente}"
        )

    if sede:
        lineas_adicionales.append(
            f"Sede: {sede}"
        )

    if responsable:
        lineas_adicionales.append(
            f"Responsable: {responsable}"
        )

    informacion_adicional_texto = ""

    if lineas_adicionales:
        informacion_adicional_texto = (
            "\n"
            + "\n".join(lineas_adicionales)
        )

    cuerpo_texto = (
        f"{titulo}\n\n"
        f"Señor(a): {nombre_completo}\n"
        f"Documento: {documento}\n\n"
        f"{introduccion}\n\n"
        f"Fecha: {fecha}\n"
        f"Hora: {hora_inicio} a {hora_fin}\n"
        f"Modalidad: {modalidad}\n"
        f"Lugar o enlace: {lugar}\n"
        f"Motivo: {motivo}"
        f"{informacion_adicional_texto}\n\n"
        "Agradecemos presentarse puntualmente y atender "
        "las indicaciones comunicadas por la empresa.\n\n"
        "Cordialmente,\n"
        "Relaciones Laborales\n"
        "Aseos La Perfección"
    )

    filas_html = [
        ("Fecha", fecha),
        ("Hora", f"{hora_inicio} a {hora_fin}"),
        ("Modalidad", modalidad),
        ("Lugar o enlace", lugar),
        ("Motivo", motivo),
    ]

    if cliente:
        filas_html.append(
            ("Cliente", cliente)
        )

    if sede:
        filas_html.append(
            ("Sede", sede)
        )

    if responsable:
        filas_html.append(
            ("Responsable", responsable)
        )

    detalle_html = "".join(
        (
            "<tr>"
            '<td style="padding:8px;'
            'border-bottom:1px solid #e5e7eb;'
            'font-weight:bold;width:35%;">'
            f"{escape(etiqueta)}"
            "</td>"
            '<td style="padding:8px;'
            'border-bottom:1px solid #e5e7eb;">'
            f"{escape(valor)}"
            "</td>"
            "</tr>"
        )
        for etiqueta, valor in filas_html
    )

    cuerpo_html = f"""
    <!DOCTYPE html>
    <html lang="es">
    <body style="
        margin:0;
        padding:20px;
        background:#f3f4f6;
        font-family:Arial,Helvetica,sans-serif;
        color:#1f2937;
    ">
        <div style="
            max-width:650px;
            margin:0 auto;
            background:#ffffff;
            border-radius:12px;
            overflow:hidden;
            border:1px solid #e5e7eb;
        ">
            <div style="
                background:#166534;
                color:#ffffff;
                padding:24px;
                text-align:center;
            ">
                <h1 style="
                    margin:0;
                    font-size:22px;
                ">
                    {escape(titulo)}
                </h1>
                <p style="
                    margin:8px 0 0;
                    font-size:14px;
                ">
                    Aseos La Perfección
                </p>
            </div>

            <div style="padding:26px;">
                <p>
                    Señor(a):
                    <strong>{escape(nombre_completo)}</strong>
                </p>

                <p>
                    Documento:
                    <strong>{escape(documento)}</strong>
                </p>

                <p style="line-height:1.6;">
                    {escape(introduccion)}
                </p>

                <table style="
                    width:100%;
                    border-collapse:collapse;
                    margin:22px 0;
                    font-size:14px;
                ">
                    {detalle_html}
                </table>

                <p style="line-height:1.6;">
                    Agradecemos presentarse puntualmente y atender
                    las indicaciones comunicadas por la empresa.
                </p>

                <p style="margin-top:28px;">
                    Cordialmente,<br>
                    <strong>Relaciones Laborales</strong><br>
                    Aseos La Perfección
                </p>
            </div>
        </div>
    </body>
    </html>
    """

    return cuerpo_texto, cuerpo_html


def enviar_notificacion_agenda_disciplinaria(
    db: Session,
    id_agenda: int,
    tipo_notificacion: str,
    usuario: str | None = None,
) -> dict:
    datos = obtener_datos_notificacion_agenda(
        db=db,
        id_agenda=id_agenda,
    )

    correo = _limpiar_texto(
        datos.get("Email")
    )

    asunto = _obtener_asunto(
        tipo_notificacion
    )

    destinatario_trazabilidad = (
        correo
        if correo
        else DESTINATARIO_SIN_CORREO
    )

    notificacion = crear_notificacion(
        db=db,
        id_proceso=datos[
            "IdProcesoDisciplinario"
        ],
        id_agenda=datos[
            "IdAgendaProcesoDisciplinario"
        ],
        destinatario=destinatario_trazabilidad,
        tipo_notificacion=tipo_notificacion,
        asunto=asunto,
        usuario=usuario,
    )

    if not correo:
        mensaje_error = (
            "El trabajador no tiene correo registrado "
            "en RegistroPersonal.Email."
        )

        marcar_notificacion_error(
            db=db,
            notificacion=notificacion,
            error=mensaje_error,
            usuario=usuario,
        )

        return {
            "enviado": False,
            "estado": "ERROR",
            "correo": None,
            "mensaje": mensaje_error,
            "IdNotificacionProcesoDisciplinario": (
                notificacion
                .IdNotificacionProcesoDisciplinario
            ),
        }

    cuerpo_texto, cuerpo_html = (
        _construir_contenido_correo(
            datos=datos,
            tipo_notificacion=tipo_notificacion,
        )
    )

    try:
        enviar_correo_sin_adjunto(
            destinatario=correo,
            asunto=asunto,
            cuerpo=cuerpo_texto,
            cuerpo_html=cuerpo_html,
        )

        notificacion = marcar_notificacion_enviada(
            db=db,
            notificacion=notificacion,
            usuario=usuario,
        )

        return {
            "enviado": True,
            "estado": "ENVIADO",
            "correo": correo,
            "mensaje": (
                "Notificación enviada correctamente "
                "al correo del trabajador."
            ),
            "IdNotificacionProcesoDisciplinario": (
                notificacion
                .IdNotificacionProcesoDisciplinario
            ),
        }

    except Exception as error:
        notificacion = marcar_notificacion_error(
            db=db,
            notificacion=notificacion,
            error=str(error),
            usuario=usuario,
        )

        return {
            "enviado": False,
            "estado": "ERROR",
            "correo": correo,
            "mensaje": str(error),
            "IdNotificacionProcesoDisciplinario": (
                notificacion
                .IdNotificacionProcesoDisciplinario
            ),
        }