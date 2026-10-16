"""
Envío por correo de los permisos de trabajo en alturas autorizados, con el
PDF del permiso (formato F-SS-007) adjunto.

Los destinatarios no se escriben en pantalla: se definen en el servidor con
la variable de entorno PERMISOS_ALTURAS_CORREOS (separados por coma). Mientras
se prueba se usa el correo de Operaciones por defecto.

El envío se ejecuta después de autorizar (tarea en segundo plano), con su
propia sesión de base de datos, y su resultado queda registrado en el permiso
("CorreoEnviadoA", "FechaEnvioCorreo", "ErrorEnvioCorreo").
"""

import html
import logging
import os

from sqlalchemy import text

from infrastructure.db.session import SessionLocal
from services.email_service import enviar_correo_con_adjunto_bytes
from services.permiso_alturas_pdf_service import generar_pdf_permiso_alturas

logger = logging.getLogger(__name__)

CORREOS_POR_DEFECTO = "operaciones2@aseoslaperfeccion.com"
ZONA_HORARIA = "America/Bogota"

ROLES_FIRMA = {
    "AUTORIZA": "Autoriza el trabajo",
    "COORDINADOR": "Coordinador (responsable del permiso)",
    "EMERGENCIAS": "Responsable de activar el plan de emergencias",
    "AYUDANTE": "Ayudante de seguridad",
}


def obtener_correos_notificacion() -> list[str]:
    valor = os.getenv("PERMISOS_ALTURAS_CORREOS") or CORREOS_POR_DEFECTO

    return [
        correo.strip()
        for correo in valor.split(",")
        if correo.strip()
    ]


def _consultar_resumen(db, id_permiso: int) -> dict | None:
    permiso = db.execute(
        text("""
            SELECT P."IdPermisoTrabajoAlturas" AS id,
                   C."Nombre" AS cliente,
                   TRIM(RR."Nombres" || ' ' || RR."Apellidos") AS responsable,
                   to_char(P."FechaHoraInicioTarea" AT TIME ZONE :zona, 'DD/MM/YYYY') AS fecha,
                   to_char(P."FechaHoraInicioTarea" AT TIME ZONE :zona, 'HH24:MI') AS hora_inicio,
                   to_char(P."FechaHoraFinTarea" AT TIME ZONE :zona, 'HH24:MI') AS hora_fin,
                   to_char(P."FechaAutorizacion" AT TIME ZONE :zona, 'DD/MM/YYYY HH24:MI') AS fecha_autorizacion,
                   COALESCE(
                       (SELECT string_agg(O."Nombre", ', ' ORDER BY O."Orden")
                        FROM public."PermisoTrabajoAlturasOpcion" PO
                        JOIN public."OpcionPermisoAlturas" O
                          ON O."IdOpcionPermisoAlturas" = PO."IdOpcionPermisoAlturas"
                        WHERE PO."IdPermisoTrabajoAlturas" = P."IdPermisoTrabajoAlturas"
                          AND O."Tipo" = 'MECANISMO'),
                       P."TipoTrabajoAlturas"
                   ) AS tipo_trabajo,
                   P."AlturaAproximadaMetros" AS altura,
                   P."DescripcionProcedimiento" AS descripcion,
                   P."Observaciones" AS observaciones
            FROM public."PermisoTrabajoAlturas" P
            JOIN public."Cliente" C ON C."IdCliente" = P."IdCliente"
            LEFT JOIN public."RegistroPersonal" RR
              ON RR."IdRegistroPersonal" = P."IdRegistroPersonalResponsable"
            WHERE P."IdPermisoTrabajoAlturas" = :id_permiso
        """),
        {"id_permiso": id_permiso, "zona": ZONA_HORARIA},
    ).mappings().first()

    if permiso is None:
        return None

    trabajadores = db.execute(
        text("""
            SELECT TRIM(R."Nombres" || ' ' || R."Apellidos") AS nombre,
                   R."NumeroIdentificacion" AS cedula
            FROM public."PermisoTrabajoAlturasTrabajador" T
            JOIN public."RegistroPersonal" R
              ON R."IdRegistroPersonal" = T."IdRegistroPersonal"
            WHERE T."IdPermisoTrabajoAlturas" = :id_permiso
            ORDER BY T."IdPermisoTrabajoAlturasTrabajador"
        """),
        {"id_permiso": id_permiso},
    ).mappings().all()

    firmas = db.execute(
        text("""
            SELECT F."Rol" AS rol,
                   TRIM(R."Nombres" || ' ' || R."Apellidos") AS nombre,
                   R."NumeroIdentificacion" AS cedula
            FROM public."PermisoTrabajoAlturasFirma" F
            JOIN public."RegistroPersonal" R
              ON R."IdRegistroPersonal" = F."IdRegistroPersonal"
            WHERE F."IdPermisoTrabajoAlturas" = :id_permiso
        """),
        {"id_permiso": id_permiso},
    ).mappings().all()

    return {
        "permiso": dict(permiso),
        "trabajadores": [dict(t) for t in trabajadores],
        "firmas": [dict(f) for f in firmas],
    }


def _armar_mensaje(resumen: dict) -> tuple[str, str, str]:
    p = resumen["permiso"]
    e = lambda valor: html.escape(str(valor if valor is not None else "—"))

    asunto = (
        f"Permiso de trabajo en alturas N.° {p['id']} autorizado - {p['cliente']}"
    )

    filas = [
        ("Permiso N.°", p["id"]),
        ("Cliente", p["cliente"]),
        ("Responsable", p["responsable"]),
        ("Fecha", p["fecha"]),
        ("Horario", f"{p['hora_inicio']} - {p['hora_fin']}"),
        ("Tipo de trabajo", p["tipo_trabajo"]),
        ("Altura aproximada", f"{p['altura']} m" if p["altura"] is not None else None),
        ("Autorizado", p["fecha_autorizacion"]),
    ]

    firmas = [
        (ROLES_FIRMA.get(f["rol"], f["rol"]), f"{f['nombre']} (C.C. {f['cedula']})")
        for f in sorted(
            resumen["firmas"], key=lambda f: list(ROLES_FIRMA).index(f["rol"])
        )
    ]

    trabajadores = [
        f"{t['nombre']} (C.C. {t['cedula']})" for t in resumen["trabajadores"]
    ]

    texto = "\n".join(
        [f"Se autorizó el permiso de trabajo en alturas N.° {p['id']}.", ""]
        + [f"{etiqueta}: {valor or '—'}" for etiqueta, valor in filas]
        + ["", "Trabajadores:"]
        + [f"- {t}" for t in trabajadores]
        + ["", "Firmas:"]
        + [f"- {rol}: {persona}" for rol, persona in firmas]
        + (["", f"Observaciones: {p['observaciones']}"] if p["observaciones"] else [])
    )

    estilo_celda = "padding:6px 10px;border:1px solid #e5e7eb;"
    cuerpo_html = f"""
    <div style="font-family:Arial,sans-serif;color:#1f2937;">
      <h2 style="color:#047857;">Permiso de trabajo en alturas N.° {e(p['id'])} autorizado</h2>
      <table style="border-collapse:collapse;">
        {''.join(f'<tr><td style="{estilo_celda}font-weight:bold;">{e(k)}</td><td style="{estilo_celda}">{e(v)}</td></tr>' for k, v in filas)}
      </table>
      <h3>Trabajadores ({len(trabajadores)})</h3>
      <ul>{''.join(f'<li>{e(t)}</li>' for t in trabajadores)}</ul>
      <h3>Firmas</h3>
      <ul>{''.join(f'<li><b>{e(rol)}:</b> {e(persona)}</li>' for rol, persona in firmas)}</ul>
      {f'<p><b>Observaciones:</b> {e(p["observaciones"])}</p>' if p['observaciones'] else ''}
      <p style="color:#6b7280;font-size:12px;">Mensaje generado automáticamente por el portal La Perfección.</p>
    </div>
    """

    return asunto, texto, cuerpo_html


def enviar_permiso_autorizado(id_permiso: int) -> None:
    """Envía el permiso autorizado y registra el resultado. Nunca lanza error."""
    db = SessionLocal()

    try:
        resumen = _consultar_resumen(db, id_permiso)

        if resumen is None:
            return

        asunto, texto, cuerpo_html = _armar_mensaje(resumen)
        pdf = generar_pdf_permiso_alturas(db, id_permiso)
        nombre_pdf = f"permiso_alturas_{id_permiso}.pdf"
        enviados, errores = [], []

        for correo in obtener_correos_notificacion():
            try:
                enviar_correo_con_adjunto_bytes(
                    correo, asunto, texto, pdf, nombre_pdf, cuerpo_html
                )
                enviados.append(correo)
            except Exception as error:  # noqa: BLE001
                logger.exception("Error enviando permiso de alturas %s", id_permiso)
                errores.append(f"{correo}: {error}")

        db.execute(
            text("""
                UPDATE public."PermisoTrabajoAlturas"
                SET "CorreoEnviadoA"   = :enviados,
                    "FechaEnvioCorreo" = CASE WHEN :hubo_envio THEN now() END,
                    "ErrorEnvioCorreo" = :errores
                WHERE "IdPermisoTrabajoAlturas" = :id_permiso
            """),
            {
                "id_permiso": id_permiso,
                "enviados": ", ".join(enviados) or None,
                "hubo_envio": bool(enviados),
                "errores": "\n".join(errores) or None,
            },
        )
        db.commit()
    except Exception:  # noqa: BLE001
        db.rollback()
        logger.exception("No se pudo procesar el correo del permiso %s", id_permiso)
    finally:
        db.close()
