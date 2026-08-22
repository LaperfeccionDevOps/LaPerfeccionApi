from datetime import date, time
from html import escape

from sqlalchemy import text
from sqlalchemy.orm import Session

from services.email_service import (
    enviar_correo_con_adjunto_bytes,
    enviar_correo_sin_adjunto,
)
from services.carta_citacion_descargos_pdf_service import (
    generar_carta_citacion_descargos_pdf,
)
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


def _formatear_nombre_visible(
    valor: object,
    valor_defecto: str = "",
) -> str:
    """
    Formatea nombres únicamente para presentación.
    No modifica el valor almacenado en base de datos.
    """
    texto = _limpiar_texto(
        valor,
        valor_defecto,
    )

    if not texto:
        return valor_defecto

    return " ".join(
        palabra.capitalize()
        for palabra in texto.split()
    )


def _formatear_motivo_visible(
    valor: object,
    valor_defecto: str = "Citación laboral",
) -> str:
    """
    Convierte códigos internos de motivo a texto legible
    para correos y notificaciones.
    No modifica la información almacenada en base de datos.
    """
    texto = _limpiar_texto(
        valor,
        valor_defecto,
    )

    if not texto:
        return valor_defecto

    codigo = texto.upper()

    equivalencias = {
        "NO_USAR_EPP_LABOR": "No usar EPP para la labor",
        "PERIODO_PRUEBA": "Período de prueba",
        "INCUMPLIMIENTO_NORMAS": "Incumplimiento de normas",
        "DANOS_EN_BIEN_AJENO_AFECTACION_CLIENTE": (
            "Daños en bien ajeno - afectación al cliente"
        ),
        "PERDIDA_OBJETOS_CLIENTE_COMPANEROS": (
            "Pérdida de objetos cliente / compañeros"
        ),
        "OMISION_REPORTE_CONFLICTO_INTERES": (
            "Omisión reporte conflicto de interés"
        ),
    }

    if codigo in equivalencias:
        return equivalencias[codigo]

    if "_" not in texto:
        return texto

    texto_legible = texto.replace("_", " ").strip().lower()

    return texto_legible[:1].upper() + texto_legible[1:]


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

            pd."FechaCreacion" AS "FechaCreacionProceso",

            rp."NumeroIdentificacion",
            rp."Nombres",
            rp."Apellidos",
            rp."Email",

            te."Nombre" AS "TipoEvento",

            citacion."IdCitacionProcesoDisciplinario",
            citacion."LugarCitacion",
            citacion."MotivoCitacion",
            citacion."ResponsableCitacion",
            citacion."SupervisorReporta",
            citacion."CorreoSupervisorReporta",
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
                cp."SupervisorReporta",
                cp."CorreoSupervisorReporta",
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


def _formatear_codigo_expediente(
    id_proceso: int,
    fecha_creacion: object = None,
) -> str:
    """
    Genera el código visible del expediente disciplinario.

    Ejemplo:
    PD-2026-000046
    """

    anio = None

    if fecha_creacion is not None:
        anio = getattr(
            fecha_creacion,
            "year",
            None,
        )

    if not anio:
        anio = date.today().year

    return (
        f"PD-{int(anio)}-"
        f"{int(id_proceso):06d}"
    )


def _obtener_asunto(
    tipo_notificacion: str,
    id_proceso: int,
    fecha_creacion_proceso: object = None,
) -> str:
    """
    Construye un asunto único por expediente.

    Incluir el código PD evita que Gmail agrupe en un mismo hilo
    citaciones pertenecientes a procesos disciplinarios diferentes.
    """

    tipo = _limpiar_texto(
        tipo_notificacion
    ).upper()

    codigo_expediente = (
        _formatear_codigo_expediente(
            id_proceso=id_proceso,
            fecha_creacion=fecha_creacion_proceso,
        )
    )

    if tipo == TIPO_REPROGRAMACION:
        return (
            "Reprogramación de citación laboral "
            f"- {codigo_expediente} "
            "- Aseos La Perfección"
        )

    if tipo == TIPO_CANCELACION:
        return (
            "Cancelación de citación laboral "
            f"- {codigo_expediente} "
            "- Aseos La Perfección"
        )

    return (
        "Citación laboral "
        f"- {codigo_expediente} "
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
            _formatear_nombre_visible(
                datos.get("Nombres")
            ),
            _formatear_nombre_visible(
                datos.get("Apellidos")
            ),
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

    motivo = _formatear_motivo_visible(
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

    detalle_lugar_texto = (
        (
            "Enlace: será suministrado por Relaciones Laborales "
            "a través de WhatsApp interno"
        )
        if (
            _limpiar_texto(modalidad).upper() == "VIRTUAL"
            and (
                not lugar
                or lugar == "Por confirmar"
            )
        )
        else f"Lugar o enlace: {lugar}"
    )

    cuerpo_texto = (
        f"{titulo}\n\n"
        f"Señor(a): {nombre_completo}\n"
        f"Documento: {documento}\n\n"
        f"{introduccion}\n\n"
        f"Fecha: {fecha}\n"
        f"Hora: {hora_inicio} a {hora_fin}\n"
        f"Modalidad: {modalidad}\n"
        f"{detalle_lugar_texto}\n"
        f"Motivo: {motivo}\n"
        f"Cliente: {cliente or 'No registrado'}\n"
        f"Sede: {sede or 'No registrada'}\n"
        f"Responsable: {responsable or 'Relaciones Laborales'}\n\n"
        "Agradecemos atender la citación en la fecha y hora indicadas.\n\n"
        "Cordialmente,\n"
        "Relaciones Laborales\n"
        "Aseos La Perfección"
    )

    es_virtual = (
        _limpiar_texto(modalidad).upper()
        == "VIRTUAL"
    )

    bloque_acceso_virtual = ""

    if (
        es_virtual
        and lugar
        and lugar != "Por confirmar"
    ):
        enlace_seguro = escape(
            lugar,
            quote=True,
        )

        bloque_acceso_virtual = f"""
            <div style="
                margin:24px 0 8px;
                padding:20px;
                background:#ecfdf5;
                border:1px solid #a7f3d0;
                border-radius:12px;
                text-align:center;
            ">
                <p style="
                    margin:0 0 14px;
                    color:#065f46;
                    font-size:14px;
                    font-weight:700;
                ">
                    Acceso a la reunión virtual
                </p>

                <a
                    href="{enlace_seguro}"
                    style="
                        display:inline-block;
                        background:#0f766e;
                        color:#ffffff;
                        text-decoration:none;
                        padding:13px 22px;
                        border-radius:8px;
                        font-weight:700;
                        font-size:15px;
                    "
                >
                    Ingresar a la reunión
                </a>

                <p style="
                    margin:14px 0 0;
                    font-size:12px;
                    color:#475569;
                    line-height:1.5;
                    word-break:break-all;
                ">
                    {escape(lugar)}
                </p>
            </div>
        """

    filas_html = [
        ("Fecha", fecha),
        ("Hora", f"{hora_inicio} a {hora_fin}"),
        ("Modalidad", modalidad),
        ("Motivo", motivo),
    ]

    if not es_virtual:
        filas_html.append(
            (
                "Lugar",
                lugar,
            )
        )

    if cliente:
        filas_html.append(
            (
                "Cliente",
                cliente,
            )
        )

    if sede:
        filas_html.append(
            (
                "Sede",
                sede,
            )
        )

    if responsable:
        filas_html.append(
            (
                "Responsable",
                responsable,
            )
        )

    detalle_html = "".join(
        (
            '<tr>'
            '<td style="'
            'padding:12px 10px;'
            'border-bottom:1px solid #e5e7eb;'
            'font-weight:700;'
            'color:#475569;'
            'width:36%;'
            'vertical-align:top;'
            '">'
            f"{escape(etiqueta)}"
            "</td>"
            '<td style="'
            'padding:12px 10px;'
            'border-bottom:1px solid #e5e7eb;'
            'color:#111827;'
            'vertical-align:top;'
            'word-break:break-word;'
            '">'
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
        padding:0;
        background:#f1f5f9;
        font-family:Arial,Helvetica,sans-serif;
        color:#1f2937;
    ">
        <div style="
            width:100%;
            padding:24px 12px;
            box-sizing:border-box;
        ">
            <div style="
                max-width:640px;
                margin:0 auto;
                background:#ffffff;
                border:1px solid #e2e8f0;
                border-radius:16px;
                overflow:hidden;
                box-shadow:0 8px 24px rgba(15,23,42,0.08);
            ">
                <div style="
                    background:#0f6b4f;
                    color:#ffffff;
                    padding:26px 22px;
                    text-align:left;
                ">
                    <div style="
                        font-size:12px;
                        font-weight:700;
                        letter-spacing:1px;
                        text-transform:uppercase;
                        opacity:0.9;
                        margin-bottom:8px;
                    ">
                        Aseos La Perfección
                    </div>

                    <h1 style="
                        margin:0;
                        font-size:24px;
                        line-height:1.25;
                        font-weight:700;
                    ">
                        {escape(titulo)}
                    </h1>
                </div>

                <div style="
                    padding:26px 22px 28px;
                ">
                    <p style="
                        margin:0 0 10px;
                        font-size:15px;
                        line-height:1.6;
                    ">
                        Señor(a)
                    </p>

                    <p style="
                        margin:0 0 4px;
                        font-size:19px;
                        line-height:1.4;
                        font-weight:700;
                        color:#0f172a;
                    ">
                        {escape(nombre_completo)}
                    </p>

                    <p style="
                        margin:0 0 22px;
                        color:#64748b;
                        font-size:14px;
                    ">
                        Documento: {escape(documento)}
                    </p>

                    <p style="
                        margin:0 0 20px;
                        font-size:15px;
                        line-height:1.7;
                        color:#334155;
                    ">
                        {escape(introduccion)}
                    </p>

                    <div style="
                        border:1px solid #e2e8f0;
                        border-radius:12px;
                        overflow:hidden;
                    ">
                        <table style="
                            width:100%;
                            border-collapse:collapse;
                            font-size:14px;
                        ">
                            {detalle_html}
                        </table>
                    </div>

                    {bloque_acceso_virtual}

                    <div style="
                        margin-top:22px;
                        padding:16px 18px;
                        background:#f8fafc;
                        border-radius:10px;
                        color:#475569;
                        font-size:14px;
                        line-height:1.6;
                    ">
                        Agradecemos atender la citación en la fecha y hora
                        indicadas y seguir las instrucciones comunicadas
                        por la empresa.
                    </div>

                    <p style="
                        margin:28px 0 0;
                        font-size:14px;
                        line-height:1.6;
                        color:#475569;
                    ">
                        Cordialmente,<br>
                        <strong style="color:#0f172a;">
                            Relaciones Laborales
                        </strong><br>
                        Aseos La Perfección
                    </p>
                </div>
            </div>
        </div>
    </body>
    </html>
    """

    return cuerpo_texto, cuerpo_html


def _construir_contenido_correo_supervisor(
    datos: dict,
    tipo_notificacion: str,
) -> tuple[str, str]:
    """
    Construye el correo informativo dirigido al supervisor/líder
    que reportó el caso.
    """

    nombre_trabajador = " ".join(
        parte
        for parte in (
            _formatear_nombre_visible(
                datos.get("Nombres")
            ),
            _formatear_nombre_visible(
                datos.get("Apellidos")
            ),
        )
        if parte
    )

    documento = _limpiar_texto(
        datos.get("NumeroIdentificacion"),
        "No registrado",
    )

    supervisor = _formatear_nombre_visible(
        datos.get("SupervisorReporta"),
        "Supervisor(a)",
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

    lugar = _limpiar_texto(
        datos.get("LugarCitacion"),
        "Por confirmar",
    )

    motivo = _formatear_motivo_visible(
        datos.get("MotivoCitacion")
        or datos.get("TipoEvento"),
        "Citación laboral",
    )

    cliente = _limpiar_texto(
        datos.get("Cliente"),
    )

    sede = _limpiar_texto(
        datos.get("Sede"),
    )

    tipo_normalizado = _limpiar_texto(
        tipo_notificacion
    ).upper()

    if tipo_normalizado == TIPO_REPROGRAMACION:
        titulo_supervisor = (
            "Confirmación de reprogramación de citación"
        )
        introduccion_supervisor = (
            "Le informamos que la citación laboral del colaborador "
            "reportado fue reprogramada."
        )
        mensaje_cierre_supervisor = (
            "La fecha y hora mostradas corresponden a la nueva "
            "programación de la diligencia."
        )
    elif tipo_normalizado == TIPO_CANCELACION:
        titulo_supervisor = (
            "Confirmación de cancelación de citación"
        )
        introduccion_supervisor = (
            "Le informamos que la citación laboral del colaborador "
            "reportado fue cancelada."
        )
        mensaje_cierre_supervisor = (
            "La citación ya no se encuentra vigente en la programación "
            "disciplinaria."
        )
    else:
        titulo_supervisor = "Confirmación de citación"
        introduccion_supervisor = (
            "Le informamos que el colaborador reportado fue citado "
            "formalmente para diligencia de descargos."
        )
        mensaje_cierre_supervisor = (
            "Se adjunta copia de la carta oficial enviada al "
            "colaborador para su conocimiento y seguimiento."
        )

    detalle_lugar_texto = (
        (
            "Enlace: será suministrado por Relaciones Laborales "
            "a través de WhatsApp interno"
        )
        if (
            _limpiar_texto(modalidad).upper() == "VIRTUAL"
            and (
                not lugar
                or lugar == "Por confirmar"
            )
        )
        else f"Lugar o enlace: {lugar}"
    )

    cuerpo_texto = (
        f"{titulo_supervisor}\n\n"
        f"Señor(a): {supervisor}\n\n"
        f"{introduccion_supervisor}\n\n"
        f"Colaborador: {nombre_trabajador}\n"
        f"Documento: {documento}\n"
        f"Fecha: {fecha}\n"
        f"Hora: {hora_inicio} a {hora_fin}\n"
        f"Modalidad: {modalidad}\n"
        f"{detalle_lugar_texto}\n"
        f"Motivo: {motivo}\n"
        f"Cliente: {cliente or 'No registrado'}\n"
        f"Sede: {sede or 'No registrada'}\n\n"
        f"{mensaje_cierre_supervisor}\n\n"
        "Cordialmente,\n"
        "Relaciones Laborales\n"
        "Aseos La Perfección"
    )

    es_virtual = (
        _limpiar_texto(modalidad).upper()
        == "VIRTUAL"
    )

    bloque_acceso_virtual = ""

    if (
        es_virtual
        and lugar
        and lugar != "Por confirmar"
    ):
        enlace_seguro = escape(
            lugar,
            quote=True,
        )

        bloque_acceso_virtual = f"""
            <div style="
                margin:24px 0 8px;
                padding:20px;
                background:#ecfdf5;
                border:1px solid #a7f3d0;
                border-radius:12px;
                text-align:center;
            ">
                <p style="
                    margin:0 0 14px;
                    color:#065f46;
                    font-size:14px;
                    font-weight:700;
                ">
                    Enlace de la reunión virtual
                </p>

                <a
                    href="{enlace_seguro}"
                    style="
                        display:inline-block;
                        background:#0f766e;
                        color:#ffffff;
                        text-decoration:none;
                        padding:13px 22px;
                        border-radius:8px;
                        font-weight:700;
                        font-size:15px;
                    "
                >
                    Ver reunión
                </a>

                <p style="
                    margin:14px 0 0;
                    font-size:12px;
                    color:#475569;
                    line-height:1.5;
                    word-break:break-all;
                ">
                    {escape(lugar)}
                </p>
            </div>
        """

    filas_html = [
        ("Colaborador", nombre_trabajador),
        ("Documento", documento),
        ("Fecha", fecha),
        ("Hora", f"{hora_inicio} a {hora_fin}"),
        ("Modalidad", modalidad),
        ("Motivo", motivo),
    ]

    if not es_virtual:
        filas_html.append(
            (
                "Lugar",
                lugar,
            )
        )

    if cliente:
        filas_html.append(
            (
                "Cliente",
                cliente,
            )
        )

    if sede:
        filas_html.append(
            (
                "Sede",
                sede,
            )
        )

    detalle_html = "".join(
        (
            '<tr>'
            '<td style="'
            'padding:12px 10px;'
            'border-bottom:1px solid #e5e7eb;'
            'font-weight:700;'
            'color:#475569;'
            'width:36%;'
            'vertical-align:top;'
            '">'
            f"{escape(etiqueta)}"
            "</td>"
            '<td style="'
            'padding:12px 10px;'
            'border-bottom:1px solid #e5e7eb;'
            'color:#111827;'
            'vertical-align:top;'
            'word-break:break-word;'
            '">'
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
        padding:0;
        background:#f1f5f9;
        font-family:Arial,Helvetica,sans-serif;
        color:#1f2937;
    ">
        <div style="
            width:100%;
            padding:24px 12px;
            box-sizing:border-box;
        ">
            <div style="
                max-width:640px;
                margin:0 auto;
                background:#ffffff;
                border:1px solid #e2e8f0;
                border-radius:16px;
                overflow:hidden;
                box-shadow:0 8px 24px rgba(15,23,42,0.08);
            ">
                <div style="
                    background:#0f6b4f;
                    color:#ffffff;
                    padding:26px 22px;
                ">
                    <div style="
                        font-size:12px;
                        font-weight:700;
                        letter-spacing:1px;
                        text-transform:uppercase;
                        opacity:0.9;
                        margin-bottom:8px;
                    ">
                        Aseos La Perfección
                    </div>

                    <h1 style="
                        margin:0;
                        font-size:24px;
                        line-height:1.25;
                        font-weight:700;
                    ">
                        {escape(titulo_supervisor)}
                    </h1>
                </div>

                <div style="
                    padding:26px 22px 28px;
                ">
                    <p style="
                        margin:0 0 6px;
                        color:#64748b;
                        font-size:14px;
                    ">
                        Supervisor que reporta
                    </p>

                    <p style="
                        margin:0 0 22px;
                        font-size:19px;
                        font-weight:700;
                        color:#0f172a;
                    ">
                        {escape(supervisor)}
                    </p>

                    <p style="
                        margin:0 0 20px;
                        font-size:15px;
                        line-height:1.7;
                        color:#334155;
                    ">
                        {escape(introduccion_supervisor)}
                    </p>

                    <div style="
                        border:1px solid #e2e8f0;
                        border-radius:12px;
                        overflow:hidden;
                    ">
                        <table style="
                            width:100%;
                            border-collapse:collapse;
                            font-size:14px;
                        ">
                            {detalle_html}
                        </table>
                    </div>

                    {bloque_acceso_virtual}

                    <div style="
                        margin-top:22px;
                        padding:16px 18px;
                        background:#f8fafc;
                        border-radius:10px;
                        color:#475569;
                        font-size:14px;
                        line-height:1.6;
                    ">
                        {escape(mensaje_cierre_supervisor)}
                    </div>

                    <p style="
                        margin:28px 0 0;
                        font-size:14px;
                        line-height:1.6;
                        color:#475569;
                    ">
                        Cordialmente,<br>
                        <strong style="color:#0f172a;">
                            Relaciones Laborales
                        </strong><br>
                        Aseos La Perfección
                    </p>
                </div>
            </div>
        </div>
    </body>
    </html>
    """

    return cuerpo_texto, cuerpo_html


def _nombre_archivo_carta_citacion(
    id_proceso: int,
) -> str:
    """
    Genera un nombre estable y legible para la carta PDF adjunta.
    """

    return (
        "Carta_Citacion_Descargos_"
        f"PD-{int(id_proceso):06d}.pdf"
    )


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

    correo_trabajador = _limpiar_texto(
        datos.get("Email")
    )

    correo_supervisor = _limpiar_texto(
        datos.get("CorreoSupervisorReporta")
    )

    id_proceso = int(
        datos["IdProcesoDisciplinario"]
    )

    id_agenda_datos = int(
        datos["IdAgendaProcesoDisciplinario"]
    )

    fecha_creacion_proceso = datos.get(
        "FechaCreacionProceso"
    )

    codigo_expediente = (
        _formatear_codigo_expediente(
            id_proceso=id_proceso,
            fecha_creacion=fecha_creacion_proceso,
        )
    )

    asunto = _obtener_asunto(
        tipo_notificacion=tipo_notificacion,
        id_proceso=id_proceso,
        fecha_creacion_proceso=fecha_creacion_proceso,
    )

    tipo_normalizado = _limpiar_texto(
        tipo_notificacion
    ).upper()

    modalidad_normalizada = _limpiar_texto(
        datos.get("ModalidadAgenda")
        or datos.get("ModalidadCitacion")
    ).upper()

    destinatario_trabajador = (
        correo_trabajador
        if correo_trabajador
        else DESTINATARIO_SIN_CORREO
    )

    notificacion_trabajador = crear_notificacion(
        db=db,
        id_proceso=id_proceso,
        id_agenda=id_agenda_datos,
        destinatario=destinatario_trabajador,
        tipo_notificacion=tipo_notificacion,
        asunto=asunto,
        usuario=usuario,
    )

    if not correo_trabajador:
        mensaje_error = (
            "El trabajador no tiene correo registrado "
            "en RegistroPersonal.Email."
        )

        marcar_notificacion_error(
            db=db,
            notificacion=notificacion_trabajador,
            error=mensaje_error,
            usuario=usuario,
        )

        return {
            "enviado": False,
            "estado": "ERROR",
            "correo": None,
            "mensaje": mensaje_error,
            "IdNotificacionProcesoDisciplinario": (
                notificacion_trabajador
                .IdNotificacionProcesoDisciplinario
            ),
            "NotificacionSupervisor": None,
        }

    cuerpo_texto, cuerpo_html = (
        _construir_contenido_correo(
            datos=datos,
            tipo_notificacion=tipo_notificacion,
        )
    )

    carta_adjunta = False
    nombre_carta = None
    contenido_carta = None

    try:
        citacion_inicial_lista_para_envio = (
            tipo_normalizado == TIPO_CITACION_INICIAL
            and modalidad_normalizada in {
                "PRESENCIAL",
                "VIRTUAL",
            }
        )

        if citacion_inicial_lista_para_envio:
            buffer_carta = generar_carta_citacion_descargos_pdf(
                db=db,
                id_proceso=id_proceso,
            )

            contenido_carta = buffer_carta.getvalue()

            nombre_carta = _nombre_archivo_carta_citacion(
                id_proceso=id_proceso,
            )

            enviar_correo_con_adjunto_bytes(
                destinatario=correo_trabajador,
                asunto=asunto,
                cuerpo=cuerpo_texto,
                cuerpo_html=cuerpo_html,
                contenido_adjunto=contenido_carta,
                nombre_adjunto=nombre_carta,
            )

            carta_adjunta = True

        else:
            enviar_correo_sin_adjunto(
                destinatario=correo_trabajador,
                asunto=asunto,
                cuerpo=cuerpo_texto,
                cuerpo_html=cuerpo_html,
            )

        notificacion_trabajador = marcar_notificacion_enviada(
            db=db,
            notificacion=notificacion_trabajador,
            usuario=usuario,
        )

    except Exception as error:
        notificacion_trabajador = marcar_notificacion_error(
            db=db,
            notificacion=notificacion_trabajador,
            error=str(error),
            usuario=usuario,
        )

        return {
            "enviado": False,
            "estado": "ERROR",
            "correo": correo_trabajador,
            "CartaAdjunta": carta_adjunta,
            "NombreCartaAdjunta": nombre_carta,
            "mensaje": str(error),
            "IdNotificacionProcesoDisciplinario": (
                notificacion_trabajador
                .IdNotificacionProcesoDisciplinario
            ),
            "NotificacionSupervisor": None,
        }

    resultado_supervisor = None

    notificar_supervisor = (
        (
            tipo_normalizado == TIPO_CITACION_INICIAL
            and modalidad_normalizada in {
                "PRESENCIAL",
                "VIRTUAL",
            }
        )
        or tipo_normalizado == TIPO_REPROGRAMACION
        or tipo_normalizado == TIPO_CANCELACION
    )

    if notificar_supervisor:
        if not correo_supervisor:
            resultado_supervisor = {
                "enviado": False,
                "estado": "SIN_CORREO",
                "correo": None,
                "mensaje": (
                    "No se envió copia al supervisor porque "
                    "CorreoSupervisorReporta está vacío."
                ),
                "IdNotificacionProcesoDisciplinario": None,
            }

        else:
            nombre_trabajador_asunto = " ".join(
                parte
                for parte in (
                    _formatear_nombre_visible(
                        datos.get("Nombres")
                    ),
                    _formatear_nombre_visible(
                        datos.get("Apellidos")
                    ),
                )
                if parte
            )

            if tipo_normalizado == TIPO_REPROGRAMACION:
                asunto_supervisor = (
                    "Confirmación de reprogramación "
                    f"- {nombre_trabajador_asunto} "
                    f"- {codigo_expediente}"
                )
            elif tipo_normalizado == TIPO_CANCELACION:
                asunto_supervisor = (
                    "Confirmación de cancelación "
                    f"- {nombre_trabajador_asunto} "
                    f"- {codigo_expediente}"
                )
            else:
                asunto_supervisor = (
                    "Confirmación de citación "
                    f"- {nombre_trabajador_asunto} "
                    f"- {codigo_expediente}"
                )

            notificacion_supervisor = crear_notificacion(
                db=db,
                id_proceso=id_proceso,
                id_agenda=id_agenda_datos,
                destinatario=correo_supervisor,
                tipo_notificacion=tipo_notificacion,
                asunto=asunto_supervisor,
                usuario=usuario,
            )

            (
                cuerpo_supervisor_texto,
                cuerpo_supervisor_html,
            ) = _construir_contenido_correo_supervisor(
                datos=datos,
                tipo_notificacion=tipo_notificacion,
            )

            try:
                if contenido_carta and nombre_carta:
                    enviar_correo_con_adjunto_bytes(
                        destinatario=correo_supervisor,
                        asunto=asunto_supervisor,
                        cuerpo=cuerpo_supervisor_texto,
                        cuerpo_html=cuerpo_supervisor_html,
                        contenido_adjunto=contenido_carta,
                        nombre_adjunto=nombre_carta,
                    )
                else:
                    enviar_correo_sin_adjunto(
                        destinatario=correo_supervisor,
                        asunto=asunto_supervisor,
                        cuerpo=cuerpo_supervisor_texto,
                        cuerpo_html=cuerpo_supervisor_html,
                    )

                notificacion_supervisor = marcar_notificacion_enviada(
                    db=db,
                    notificacion=notificacion_supervisor,
                    usuario=usuario,
                )

                resultado_supervisor = {
                    "enviado": True,
                    "estado": "ENVIADO",
                    "correo": correo_supervisor,
                    "CartaAdjunta": bool(
                        contenido_carta and nombre_carta
                    ),
                    "NombreCartaAdjunta": (
                        nombre_carta
                        if contenido_carta
                        else None
                    ),
                    "mensaje": (
                        "Notificación enviada correctamente "
                        "al correo del supervisor que reportó el caso."
                    ),
                    "IdNotificacionProcesoDisciplinario": (
                        notificacion_supervisor
                        .IdNotificacionProcesoDisciplinario
                    ),
                }

            except Exception as error:
                notificacion_supervisor = marcar_notificacion_error(
                    db=db,
                    notificacion=notificacion_supervisor,
                    error=str(error),
                    usuario=usuario,
                )

                resultado_supervisor = {
                    "enviado": False,
                    "estado": "ERROR",
                    "correo": correo_supervisor,
                    "CartaAdjunta": False,
                    "NombreCartaAdjunta": None,
                    "mensaje": str(error),
                    "IdNotificacionProcesoDisciplinario": (
                        notificacion_supervisor
                        .IdNotificacionProcesoDisciplinario
                    ),
                }

    return {
        "enviado": True,
        "estado": "ENVIADO",
        "correo": correo_trabajador,
        "CartaAdjunta": carta_adjunta,
        "NombreCartaAdjunta": nombre_carta,
        "mensaje": (
            "Notificación enviada correctamente "
            "al correo del trabajador con la carta "
            "oficial de citación adjunta."
            if carta_adjunta
            else (
                "Notificación enviada correctamente "
                "al correo del trabajador."
            )
        ),
        "IdNotificacionProcesoDisciplinario": (
            notificacion_trabajador
            .IdNotificacionProcesoDisciplinario
        ),
        "NotificacionSupervisor": resultado_supervisor,
    }