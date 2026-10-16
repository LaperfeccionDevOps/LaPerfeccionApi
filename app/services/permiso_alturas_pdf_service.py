"""
PDF del permiso de trabajo en alturas (formato F-SS-007 del SG-SST).

El documento se arma por código (no es una plantilla fija) para que crezca
según el número de trabajadores:
  * Tabla de trabajadores: una fila por trabajador.
  * Autodeclaración de aptitud: una columna por trabajador, en bloques de
    TRABAJADORES_POR_BLOQUE (si hay más, la tabla se repite debajo).
Los textos de las listas (protección, verificación, peligros y sus medidas
de control) salen del catálogo "ItemPermisoAlturas".

Referencia de diseño: templates/alturas/PLANTILLA_PERMISO_ALTURAS_DINAMICA.docx
"""

from functools import lru_cache
from io import BytesIO
from pathlib import Path
from xml.sax.saxutils import escape

from PIL import Image as PILImage
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import cm
from reportlab.platypus import (
    BaseDocTemplate,
    Frame,
    Image,
    KeepTogether,
    PageTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
)
from sqlalchemy import text

# ─────────────────────────────────────────────
# Datos del formato (control documental HSEQ)
# ─────────────────────────────────────────────
FORMATO_CODIGO = "F-SS-007"
FORMATO_VERSION = "V.05"
FORMATO_FECHA = "26-ago-2022"
FORMATO_TITULO = (
    "SISTEMA DE GESTIÓN DE LA SEGURIDAD Y SALUD EN EL TRABAJO SG-SST<br/>"
    "PERMISO DE TRABAJOS EN ALTURA"
)
PIE_DIRECCION = "Calle 4 bis No. 53 C 50, Bogotá Colombia"
PIE_TELEFONOS = "317-436-8309"
PIE_EMAIL = "servicioalcliente@aseoslaperfeccion.com"

TEXTO_RESOLUCION = (
    "Resolución 4272 de 2021, Artículo 15. Todos los trabajos en alturas deben "
    "obedecer a una acción planificada, organizada y ejecutada por trabajadores "
    "autorizados que debe verse reflejada en los controles administrativos como "
    "el permiso de trabajo o sus anexos. Siempre que un trabajador ingrese a una "
    "zona de peligro, debe contar con la debida autorización y si requiere "
    "exponerse al riesgo de caídas, debe contar con un aval a través de un "
    "permiso de trabajo en alturas acompañado de una lista de chequeo, más aún "
    "en caso de que no haya barandas, sistemas de control de acceso, "
    "demarcación o sistemas de barreras físicas que cumplan con las "
    "especificaciones descritas en la presente resolución."
)
TEXTOS_LEGALES = [
    "<b>Este permiso de trabajo en alturas debe ser diligenciado en el sitio de "
    "la labor a ejecutar, por el(los) trabajador(es) o por el empleador y debe "
    "ser revisado y suscrito por él.</b>",
    "<b>Esta autorización es solamente para el personal con permiso concedido "
    "para trabajo en alturas y cubre una sola solicitud; para cambios de turno, "
    "personas responsables del trabajo y/o finalización de la jornada diaria se "
    "requiere una nueva autorización.</b>",
    "<b>AUTORIZACIÓN:</b> Confirmo que las zonas han sido revisadas, que las "
    "precauciones señaladas han sido cumplidas y autorizo el trabajo.",
]

# Logo con NIT (el mismo de las cartas de citación y los certificados).
RUTA_LOGO = (
    Path(__file__).resolve().parents[1]
    / "assets"
    / "comunicaciones"
    / "LOGO_EMPRESA_NIT.png"
)

ZONA_HORARIA = "America/Bogota"
TRABAJADORES_POR_BLOQUE = 6

# ─────────────────────────────────────────────
# Diseño
# ─────────────────────────────────────────────
MARGEN_IZQ = 1.0 * cm
MARGEN_DER = 0.75 * cm
ALTO_ENCABEZADO = 2.4 * cm
ALTO_PIE = 1.8 * cm
ANCHO_UTIL = A4[0] - MARGEN_IZQ - MARGEN_DER

COLOR_BORDE = colors.HexColor("#4B5563")
COLOR_SECCION = colors.HexColor("#D5E1E6")
COLOR_ETIQUETA = colors.HexColor("#E8EFF2")

ESTILO = ParagraphStyle("texto", fontName="Helvetica", fontSize=7.5, leading=9.2)
ESTILO_NEGRITA = ParagraphStyle("negrita", parent=ESTILO, fontName="Helvetica-Bold")
ESTILO_CENTRO = ParagraphStyle("centro", parent=ESTILO, alignment=TA_CENTER)
ESTILO_SECCION = ParagraphStyle(
    "seccion", parent=ESTILO_NEGRITA, alignment=TA_CENTER
)
ESTILO_TITULO = ParagraphStyle(
    "titulo", parent=ESTILO_NEGRITA, fontSize=9, leading=11.5, alignment=TA_CENTER
)

ETIQUETAS_SEGURIDAD_SOCIAL = {True: "Válido", False: "No válido"}

# "TipoIdentificacion"."Codigo" -> abreviatura para el PDF.
ABREVIATURAS_DOCUMENTO = {"C": "C.C.", "E": "C.E.", "U": "PPT", "T": "T.I."}

# Autodeclaración de aptitud: una fila por cada pregunta del sistema, en el
# mismo orden de la pantalla. (etiqueta, campo, tipo)
#   tipo "si_no": Sí / No; "texto": texto libre.
FILAS_APTITUD = [
    ("¿Presenta actualmente alguna condición de salud que deba ser informada "
     "para realizar el trabajo en alturas?", "presenta_condicion_salud", "si_no"),
    ("¿Actualmente percibe problemas de corazón?", "problemas_corazon", "si_no"),
    ("¿Actualmente tiene problemas para respirar?", "problemas_respiratorios", "si_no"),
    ("¿Actualmente sufre de diabetes?", "diabetes", "si_no"),
    ("¿Actualmente sufre de epilepsia?", "epilepsia", "si_no"),
    ("¿Actualmente sufre del sistema nervioso?", "problemas_sistema_nervioso", "si_no"),
    ("¿Actualmente sufre de problemas de audición?", "problemas_audicion", "si_no"),
    ("¿Actualmente tiene problemas de capacidad visual que le limiten en el "
     "trabajo?", "problemas_visuales", "si_no"),
    ("¿Cuál otra condición o restricción de salud presenta?",
     "otra_condicion_salud", "texto"),
    ("¿Consume actualmente algún medicamento que deba ser informado para "
     "realizar el trabajo en alturas?", "consume_medicamentos", "si_no"),
    ("¿Actualmente toma medicamentos para la presión arterial alta/baja?",
     "medicamentos_presion_arterial", "si_no"),
    ("¿Está tomando medicamentos que pueden causar somnolencia? ¿Cuál?",
     "medicamentos_somnolencia", "somnolencia"),
    ("¿Cuál medicamento consume?", "otro_medicamento", "otro_medicamento"),
    ("¿Presenta actualmente alguna condición o situación que le impida "
     "realizar trabajo en alturas de manera segura?",
     "presenta_impedimento_alturas", "si_no"),
    ("¿Ha ingerido bebidas alcohólicas en las últimas 12 horas?",
     "ingirio_alcohol_12_horas", "si_no"),
    ("¿Le tiene miedo a las alturas o actualmente sufre de vértigo o mareo?",
     "miedo_alturas_vertigo", "si_no"),
    ("¿Ha consumido recientemente sustancias psicoactivas, alcohol u otras "
     "sustancias que puedan afectar su estado de alerta, coordinación, "
     "equilibrio o capacidad de reacción para realizar trabajos en alturas?",
     "consume_sustancias", "si_no"),
    ("¿Cuál condición o situación le impide trabajar en alturas de manera "
     "segura?", "otro_impedimento_alturas", "texto"),
]

ROLES_FIRMA = [
    ("AUTORIZA", "NOMBRE Y APELLIDO DE LA PERSONA QUE AUTORIZA EL TRABAJO"),
    ("COORDINADOR", "NOMBRE Y APELLIDOS DEL COORDINADOR"),
    ("EMERGENCIAS", "NOMBRE DE LA PERSONA RESPONSABLE DE ACTIVAR EL PLAN DE EMERGENCIAS"),
    ("AYUDANTE", "NOMBRE DEL AYUDANTE DE SEGURIDAD"),
]

RESPUESTAS_ITEM = {"SI": "Sí", "NO": "No", "NA": "No aplica"}


# ─────────────────────────────────────────────
# Utilidades
# ─────────────────────────────────────────────
def _p(valor, estilo=ESTILO) -> Paragraph:
    texto = "—" if valor is None or str(valor).strip() == "" else str(valor)
    return Paragraph(escape(texto).replace("\n", "<br/>"), estilo)


def _p_html(html: str, estilo=ESTILO) -> Paragraph:
    return Paragraph(html, estilo)


def _si_no(valor) -> str:
    if valor is None:
        return "—"
    return "Sí" if valor else "No"


def _valor_aptitud(trabajador: dict, campo: str, tipo: str) -> str:
    valor = trabajador.get(campo)

    if tipo == "si_no":
        return _si_no(valor)

    if tipo == "somnolencia":
        if valor and trabajador.get("cual_medicamento_somnolencia"):
            return f"Sí ({trabajador['cual_medicamento_somnolencia']})"
        return _si_no(valor)

    if tipo == "otro_medicamento":
        # Los registros anteriores a la pregunta nueva guardaban el texto en
        # "cuales_medicamentos".
        return valor or trabajador.get("cuales_medicamentos") or "—"

    return valor or "—"


@lru_cache(maxsize=1)
def _logo_recortado() -> bytes | None:
    """Logo sin el margen claro que lo rodea en el archivo original."""
    if not RUTA_LOGO.exists():
        return None

    imagen = PILImage.open(RUTA_LOGO).convert("RGB")
    gris = imagen.convert("L").point(lambda v: 255 if v < 225 else 0)
    caja = gris.getbbox()

    if caja:
        margen = 8
        caja = (
            max(caja[0] - margen, 0),
            max(caja[1] - margen, 0),
            min(caja[2] + margen, imagen.width),
            min(caja[3] + margen, imagen.height),
        )
        imagen = imagen.crop(caja)

    # El original es grande (~900 KB); para el encabezado basta un ancho menor
    # y así el PDF no aumenta de peso.
    imagen.thumbnail((900, 900))

    salida = BytesIO()
    imagen.save(salida, format="PNG")
    return salida.getvalue()


def _imagen(contenido: bytes | None, ancho_max: float, alto_max: float):
    """Imagen ajustada a una caja, conservando su proporción."""
    if not contenido:
        return _p("Sin firma", ESTILO_CENTRO)

    ancho, alto = PILImage.open(BytesIO(contenido)).size
    escala = min(ancho_max / ancho, alto_max / alto)

    return Image(BytesIO(contenido), width=ancho * escala, height=alto * escala)


def _estilo_tabla(*extras) -> TableStyle:
    return TableStyle([
        ("GRID", (0, 0), (-1, -1), 0.6, COLOR_BORDE),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        *extras,
    ])


def _fila_seccion(titulo: str, columnas: int) -> list:
    return [_p_html(titulo, ESTILO_SECCION)] + [""] * (columnas - 1)


def _estilo_seccion(fila: int, columnas: int) -> list:
    return [
        ("SPAN", (0, fila), (columnas - 1, fila)),
        ("BACKGROUND", (0, fila), (columnas - 1, fila), COLOR_SECCION),
    ]


# ─────────────────────────────────────────────
# Datos
# ─────────────────────────────────────────────
def _consultar_datos(db, id_permiso: int) -> dict | None:
    permiso = db.execute(
        text("""
            SELECT P."IdPermisoTrabajoAlturas" AS id,
                   P."Estado" AS estado,
                   C."Nombre" AS cliente,
                   CI."Nombre" AS ciudad,
                   P."LugarTrabajo" AS lugar_trabajo,
                   to_char(P."FechaHoraInicioTarea" AT TIME ZONE :zona, 'DD/MM/YYYY HH24:MI') AS inicio,
                   to_char(P."FechaHoraFinTarea" AT TIME ZONE :zona, 'DD/MM/YYYY HH24:MI') AS fin,
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
                   P."DescripcionProcedimiento" AS descripcion,
                   COALESCE(
                       (SELECT string_agg(O."Nombre", ', ' ORDER BY O."Orden")
                        FROM public."PermisoTrabajoAlturasOpcion" PO
                        JOIN public."OpcionPermisoAlturas" O
                          ON O."IdOpcionPermisoAlturas" = PO."IdOpcionPermisoAlturas"
                        WHERE PO."IdPermisoTrabajoAlturas" = P."IdPermisoTrabajoAlturas"
                          AND O."Tipo" = 'HERRAMIENTA'),
                       P."HerramientasUtensilios"
                   ) AS herramientas,
                   P."AlturaAproximadaMetros" AS altura,
                   P."ReEntrenamiento" AS re_entrenamiento,
                   P."TrabajoSuspension" AS trabajo_suspension,
                   COALESCE(
                       (SELECT string_agg(O."Nombre", ', ' ORDER BY O."Orden")
                        FROM public."PermisoTrabajoAlturasOpcion" PO
                        JOIN public."OpcionPermisoAlturas" O
                          ON O."IdOpcionPermisoAlturas" = PO."IdOpcionPermisoAlturas"
                        WHERE PO."IdPermisoTrabajoAlturas" = P."IdPermisoTrabajoAlturas"
                          AND O."Tipo" = 'SISTEMA_ACCESO'),
                       P."SistemasAcceso"
                   ) AS sistemas_acceso,
                   COALESCE(
                       (SELECT string_agg(O."Nombre", ', ' ORDER BY O."Orden")
                        FROM public."PermisoTrabajoAlturasOpcion" PO
                        JOIN public."OpcionPermisoAlturas" O
                          ON O."IdOpcionPermisoAlturas" = PO."IdOpcionPermisoAlturas"
                        WHERE PO."IdPermisoTrabajoAlturas" = P."IdPermisoTrabajoAlturas"
                          AND O."Tipo" = 'SISTEMA_INGENIERIA'),
                       P."SistemasIngenieria"
                   ) AS sistemas_ingenieria,
                   P."AplicaMedidasColectivas" AS aplica_medidas_colectivas,
                   P."MedidasColectivas" AS medidas_colectivas,
                   P."OtroElementoProteccion" AS otro_epp,
                   P."Observaciones" AS observaciones,
                   P."AplicaAyudanteSeguridad" AS aplica_ayudante
            FROM public."PermisoTrabajoAlturas" P
            JOIN public."Cliente" C ON C."IdCliente" = P."IdCliente"
            LEFT JOIN public."Ciudad" CI ON CI."IdCiudad" = P."IdCiudad"
            WHERE P."IdPermisoTrabajoAlturas" = :id_permiso
        """),
        {"id_permiso": id_permiso, "zona": ZONA_HORARIA},
    ).mappings().first()

    if permiso is None:
        return None

    trabajadores = db.execute(
        text("""
            SELECT TI."Codigo" AS tipo_documento,
                   R."NumeroIdentificacion" AS numero_identificacion,
                   TRIM(R."Nombres" || ' ' || R."Apellidos") AS nombre,
                   to_char(T."FechaExamenMedico", 'DD/MM/YYYY') AS fecha_examen,
                   to_char(T."FechaCertificadoAlturas", 'DD/MM/YYYY') AS fecha_certificado,
                   T."SeguridadSocialVerificada" AS seguridad_social,
                   T."FirmaImagen" AS firma,
                   T."PresentaCondicionSalud" AS presenta_condicion_salud,
                   T."ProblemasCorazon" AS problemas_corazon,
                   T."ProblemasRespiratorios" AS problemas_respiratorios,
                   T."Diabetes" AS diabetes,
                   T."Epilepsia" AS epilepsia,
                   T."ProblemasSistemaNervioso" AS problemas_sistema_nervioso,
                   T."ProblemasAudicion" AS problemas_audicion,
                   T."ProblemasVisuales" AS problemas_visuales,
                   T."OtraCondicionSalud" AS otra_condicion_salud,
                   T."ConsumeMedicamentos" AS consume_medicamentos,
                   T."CualesMedicamentos" AS cuales_medicamentos,
                   T."MedicamentosPresionArterial" AS medicamentos_presion_arterial,
                   T."MedicamentosSomnolencia" AS medicamentos_somnolencia,
                   T."CualMedicamentoSomnolencia" AS cual_medicamento_somnolencia,
                   T."OtroMedicamento" AS otro_medicamento,
                   T."PresentaImpedimentoAlturas" AS presenta_impedimento_alturas,
                   T."IngirioAlcohol12Horas" AS ingirio_alcohol_12_horas,
                   T."MiedoAlturasVertigo" AS miedo_alturas_vertigo,
                   T."ConsumeSustancias" AS consume_sustancias,
                   T."OtroImpedimentoAlturas" AS otro_impedimento_alturas
            FROM public."PermisoTrabajoAlturasTrabajador" T
            JOIN public."RegistroPersonal" R
              ON R."IdRegistroPersonal" = T."IdRegistroPersonal"
            LEFT JOIN public."TipoIdentificacion" TI
              ON TI."IdTipoIdentificacion" = R."IdTipoIdentificacion"
            WHERE T."IdPermisoTrabajoAlturas" = :id_permiso
            ORDER BY T."IdPermisoTrabajoAlturasTrabajador"
        """),
        {"id_permiso": id_permiso},
    ).mappings().all()

    items = db.execute(
        text("""
            SELECT I."TipoItem" AS tipo,
                   I."Texto" AS texto,
                   I."MedidaControl" AS medida_control,
                   R."Respuesta" AS respuesta
            FROM public."ItemPermisoAlturas" I
            LEFT JOIN public."PermisoTrabajoAlturasRespuesta" R
              ON R."IdItemPermisoAlturas" = I."IdItemPermisoAlturas"
             AND R."IdPermisoTrabajoAlturas" = :id_permiso
            WHERE I."Activo"
            ORDER BY I."TipoItem", I."Orden"
        """),
        {"id_permiso": id_permiso},
    ).mappings().all()

    firmas = db.execute(
        text("""
            SELECT F."Rol" AS rol,
                   TRIM(R."Nombres" || ' ' || R."Apellidos") AS nombre,
                   R."NumeroIdentificacion" AS numero_identificacion,
                   F."FirmaImagen" AS firma
            FROM public."PermisoTrabajoAlturasFirma" F
            JOIN public."RegistroPersonal" R
              ON R."IdRegistroPersonal" = F."IdRegistroPersonal"
            WHERE F."IdPermisoTrabajoAlturas" = :id_permiso
        """),
        {"id_permiso": id_permiso},
    ).mappings().all()

    listas = {"PROTECCION": [], "VERIFICACION": [], "PELIGRO": []}
    for item in items:
        listas.setdefault(item["tipo"], []).append(dict(item))

    return {
        "permiso": dict(permiso),
        "trabajadores": [
            {**dict(t), "firma": bytes(t["firma"]) if t["firma"] else None}
            for t in trabajadores
        ],
        "listas": listas,
        "firmas": {
            f["rol"]: {**dict(f), "firma": bytes(f["firma"]) if f["firma"] else None}
            for f in firmas
        },
    }


# ─────────────────────────────────────────────
# Secciones del documento
# ─────────────────────────────────────────────
def _seccion_datos_basicos(p: dict) -> list:
    anchos = [3.2 * cm, 6.3 * cm, 3.4 * cm, ANCHO_UTIL - 12.9 * cm]
    filas = [
        [_p_html(escape(TEXTO_RESOLUCION))] + [""] * 3,
        _fila_seccion("1. DATOS BÁSICOS DEL PERMISO DE TRABAJO EN ALTURA", 4),
        [_p("Cliente:", ESTILO_NEGRITA), _p(p["cliente"]),
         _p("Ciudad:", ESTILO_NEGRITA), _p(p["ciudad"])],
        [_p("Lugar de trabajo:", ESTILO_NEGRITA), _p(p["lugar_trabajo"]), "", ""],
        [_p("Fecha y hora de realización del trabajo:", ESTILO_NEGRITA), _p(p["inicio"]),
         _p("Fecha y hora de finalización del trabajo:", ESTILO_NEGRITA), _p(p["fin"])],
    ]
    tabla = Table(filas, colWidths=anchos)
    tabla.setStyle(_estilo_tabla(
        ("SPAN", (0, 0), (3, 0)),
        *_estilo_seccion(1, 4),
        ("SPAN", (1, 3), (3, 3)),
        ("BACKGROUND", (0, 2), (0, 4), COLOR_ETIQUETA),
        ("BACKGROUND", (2, 2), (2, 2), COLOR_ETIQUETA),
        ("BACKGROUND", (2, 4), (2, 4), COLOR_ETIQUETA),
    ))
    return [tabla]


def _seccion_trabajadores(trabajadores: list) -> list:
    anchos = [0.9 * cm, 2.8 * cm, 4.0 * cm, 2.3 * cm, 2.6 * cm, 2.5 * cm]
    anchos.append(ANCHO_UTIL - sum(anchos))
    encabezado = [
        _p(texto, ESTILO_SECCION) for texto in (
            "N°", "Tipo y cédula (autorizado)", "Nombres y apellidos (autorizado)",
            "Fecha del examen de aptitud", "Fecha certificado de trabajador autorizado",
            "Verificación de la seguridad social", "Firma",
        )
    ]
    filas = [encabezado]

    for numero, t in enumerate(trabajadores, start=1):
        codigo = (t.get("tipo_documento") or "").strip()
        documento = " ".join(
            filter(None, [
                ABREVIATURAS_DOCUMENTO.get(codigo, codigo),
                t["numero_identificacion"],
            ])
        )
        filas.append([
            _p(numero, ESTILO_CENTRO),
            _p(documento),
            _p(t["nombre"]),
            _p(t["fecha_examen"], ESTILO_CENTRO),
            _p(t["fecha_certificado"], ESTILO_CENTRO),
            _p(ETIQUETAS_SEGURIDAD_SOCIAL.get(t["seguridad_social"]), ESTILO_CENTRO),
            _imagen(t["firma"], anchos[-1] - 0.4 * cm, 1.3 * cm),
        ])

    if not trabajadores:
        filas.append([_p("Sin trabajadores registrados.")] + [""] * 6)

    tabla = Table(filas, colWidths=anchos, repeatRows=1)
    estilos = [
        ("BACKGROUND", (0, 0), (-1, 0), COLOR_SECCION),
        ("ALIGN", (-1, 1), (-1, -1), "CENTER"),
    ]
    if not trabajadores:
        estilos.append(("SPAN", (0, 1), (-1, 1)))
    tabla.setStyle(_estilo_tabla(*estilos))
    return [tabla]


def _seccion_tarea(p: dict) -> list:
    anchos = [5.0 * cm, ANCHO_UTIL - 5.0 * cm]
    altura = f"{p['altura']} m" if p["altura"] is not None else None
    filas = [
        _fila_seccion("2. DATOS BÁSICOS DEL PERMISO DE TRABAJO EN ALTURA", 2),
        [_p("Tipo de trabajo en alturas a realizar:", ESTILO_NEGRITA), _p(p["tipo_trabajo"])],
        [_p("Descripción detallada de la tarea:", ESTILO_NEGRITA), _p(p["descripcion"])],
        [_p("Herramientas a utilizar:", ESTILO_NEGRITA), _p(p["herramientas"])],
        [_p("Altura aproximada a la cual se va a desarrollar la actividad:", ESTILO_NEGRITA), _p(altura)],
    ]
    tabla = Table(filas, colWidths=anchos)
    tabla.setStyle(_estilo_tabla(
        *_estilo_seccion(0, 2),
        ("BACKGROUND", (0, 1), (0, -1), COLOR_ETIQUETA),
    ))
    return [KeepTogether(tabla)]


def _medidas_colectivas(p: dict) -> str | None:
    # "No aplica" si así se respondió; en permisos anteriores a la pregunta,
    # el texto que se haya escrito.
    if p["aplica_medidas_colectivas"] is False:
        return "No aplica"
    return p["medidas_colectivas"]


def _seccion_medidas(p: dict) -> list:
    anchos = [2.9 * cm, 1.1 * cm, 2.6 * cm, 1.1 * cm, 3.4 * cm]
    anchos.append(ANCHO_UTIL - sum(anchos))
    filas = [
        _fila_seccion("3. MEDIDAS DE PREVENCIÓN", 6),
        [_p("Re-entrenamiento", ESTILO_NEGRITA), _p(_si_no(p["re_entrenamiento"])),
         _p("Trabajo en suspensión", ESTILO_NEGRITA), _p(_si_no(p["trabajo_suspension"])),
         _p("Medidas colectivas de prevención ¿Cuáles?", ESTILO_NEGRITA), _p(_medidas_colectivas(p))],
        [_p("Sistemas de acceso a utilizar ¿Cuál?", ESTILO_NEGRITA), _p(p["sistemas_acceso"]), "", "",
         _p("Sistemas de ingeniería ¿Cuál?", ESTILO_NEGRITA), _p(p["sistemas_ingenieria"])],
    ]
    tabla = Table(filas, colWidths=anchos)
    tabla.setStyle(_estilo_tabla(
        *_estilo_seccion(0, 6),
        ("SPAN", (1, 2), (3, 2)),
        ("BACKGROUND", (0, 1), (0, 2), COLOR_ETIQUETA),
        ("BACKGROUND", (2, 1), (2, 1), COLOR_ETIQUETA),
        ("BACKGROUND", (4, 1), (4, 2), COLOR_ETIQUETA),
    ))
    return [KeepTogether(tabla)]


def _seccion_proteccion(items: list, otro: str | None) -> list:
    # Tres pares (elemento, respuesta) por fila, como en el formato.
    ancho_par = ANCHO_UTIL / 3
    anchos = [ancho_par * 0.6, ancho_par * 0.4] * 3
    filas = [_fila_seccion(
        "4. ELEMENTOS DE PROTECCIÓN PERSONAL Y ELEMENTOS DE PROTECCIÓN CONTRA CAÍDAS", 6
    )]
    celdas = []
    for item in items:
        celdas += [_p(item["texto"], ESTILO_NEGRITA),
                   _p(RESPUESTAS_ITEM.get(item["respuesta"]))]

    celdas += [_p("Otro ¿Cuál?", ESTILO_NEGRITA), _p(otro or "Ninguno")]
    while len(celdas) % 6:
        celdas.append("")

    for inicio in range(0, len(celdas), 6):
        filas.append(celdas[inicio:inicio + 6])

    estilos = [*_estilo_seccion(0, 6)]
    for fila in range(1, len(filas)):
        for columna in (0, 2, 4):
            if filas[fila][columna] != "":
                estilos.append(("BACKGROUND", (columna, fila), (columna, fila), COLOR_ETIQUETA))

    # La última celda "Otro ¿Cuál?" ocupa el resto de la fila.
    ultima = len(filas) - 1
    columna_otro = next(
        c for c in range(5, -1, -1) if filas[ultima][c] != ""
    )
    if columna_otro < 5:
        estilos.append(("SPAN", (columna_otro, ultima), (5, ultima)))

    tabla = Table(filas, colWidths=anchos)
    tabla.setStyle(_estilo_tabla(*estilos))
    return [KeepTogether(tabla)]


def _seccion_aptitud(trabajadores: list) -> list:
    elementos = [
        Table(
            [[_p_html("5. AUTODECLARACIÓN DE APTITUD PARA REALIZAR TRABAJOS EN ALTURAS", ESTILO_SECCION)]],
            colWidths=[ANCHO_UTIL],
            style=_estilo_tabla(("BACKGROUND", (0, 0), (-1, -1), COLOR_SECCION)),
        ),
        Spacer(1, 0.15 * cm),
    ]

    if not trabajadores:
        elementos.append(_p("Sin trabajadores registrados."))
        return elementos

    for inicio in range(0, len(trabajadores), TRABAJADORES_POR_BLOQUE):
        bloque = trabajadores[inicio:inicio + TRABAJADORES_POR_BLOQUE]
        ancho_respuesta = 2.0 * cm
        anchos = [ANCHO_UTIL - ancho_respuesta * len(bloque)]
        anchos += [ancho_respuesta] * len(bloque)

        filas = [[_p("Número de trabajador", ESTILO_SECCION)] + [
            _p(inicio + n, ESTILO_SECCION) for n in range(1, len(bloque) + 1)
        ]]
        for numero, (etiqueta, campo, tipo) in enumerate(FILAS_APTITUD, start=1):
            filas.append(
                [_p(f"{numero}.  {etiqueta}")]
                + [_p(_valor_aptitud(t, campo, tipo), ESTILO_CENTRO) for t in bloque]
            )

        tabla = Table(filas, colWidths=anchos, repeatRows=1)
        tabla.setStyle(_estilo_tabla(("BACKGROUND", (0, 0), (-1, 0), COLOR_SECCION)))
        elementos += [tabla, Spacer(1, 0.25 * cm)]

    return elementos


def _seccion_verificacion(items: list, numero_inicial: int) -> list:
    # Dos ítems por fila: (n. texto, respuesta) x 2, numeración continua.
    ancho_resp = 1.6 * cm
    ancho_texto = ANCHO_UTIL / 2 - ancho_resp
    anchos = [ancho_texto, ancho_resp, ancho_texto, ancho_resp]
    filas = [_fila_seccion("6. LISTA DE VERIFICACIÓN", 4)]

    celdas = []
    for indice, item in enumerate(items):
        celdas += [_p(f"{numero_inicial + indice}.  {item['texto']}"),
                   _p(RESPUESTAS_ITEM.get(item["respuesta"]))]
    while len(celdas) % 4:
        celdas.append("")

    for inicio in range(0, len(celdas), 4):
        filas.append(celdas[inicio:inicio + 4])

    tabla = Table(filas, colWidths=anchos, repeatRows=1)
    tabla.setStyle(_estilo_tabla(*_estilo_seccion(0, 4)))
    return [tabla]


def _seccion_peligros(items: list, numero_inicial: int) -> list:
    anchos = [6.6 * cm, ANCHO_UTIL - 6.6 * cm - 2.0 * cm, 2.0 * cm]
    filas = [[
        _p("7. IDENTIFICACIÓN DE PELIGROS DEL TRABAJO A REALIZAR", ESTILO_SECCION),
        _p("MEDIDAS DE CONTROL", ESTILO_SECCION),
        _p("RESPUESTA", ESTILO_SECCION),
    ]]
    for indice, item in enumerate(items):
        filas.append([
            _p(f"{numero_inicial + indice}.  {item['texto']}"),
            _p(item.get("medida_control")),
            _p(RESPUESTAS_ITEM.get(item["respuesta"])),
        ])

    tabla = Table(filas, colWidths=anchos, repeatRows=1)
    tabla.setStyle(_estilo_tabla(("BACKGROUND", (0, 0), (-1, 0), COLOR_SECCION)))
    return [tabla]


def _seccion_textos_legales(observaciones: str | None) -> list:
    anchos = [4.5 * cm, ANCHO_UTIL - 4.5 * cm]
    filas = [[_p_html(texto), ""] for texto in TEXTOS_LEGALES]
    filas.append([_p("OBSERVACIONES", ESTILO_NEGRITA), _p(observaciones)])

    tabla = Table(filas, colWidths=anchos)
    tabla.setStyle(_estilo_tabla(
        *[("SPAN", (0, fila), (1, fila)) for fila in range(len(TEXTOS_LEGALES))],
        ("BACKGROUND", (0, 0), (-1, 1), COLOR_ETIQUETA),
        ("BACKGROUND", (0, 3), (0, 3), COLOR_ETIQUETA),
        ("VALIGN", (0, 3), (-1, 3), "TOP"),
        ("BOTTOMPADDING", (0, 3), (-1, 3), 18),
    ))
    return [KeepTogether(tabla)]


def _bloque_firma(titulo: str, firma: dict | None) -> KeepTogether:
    anchos = [ANCHO_UTIL * 0.36, ANCHO_UTIL * 0.26, ANCHO_UTIL * 0.38]
    filas = [
        [_p(titulo, ESTILO_SECCION), _p("CÉDULA", ESTILO_SECCION), _p("FIRMA", ESTILO_SECCION)],
        [
            _p(firma["nombre"] if firma else None),
            _p(firma["numero_identificacion"] if firma else None),
            _imagen(firma["firma"] if firma else None, anchos[2] - 0.6 * cm, 1.5 * cm),
        ],
    ]
    tabla = Table(filas, colWidths=anchos, rowHeights=[None, 1.9 * cm])
    tabla.setStyle(_estilo_tabla(
        ("BACKGROUND", (0, 0), (-1, 0), COLOR_SECCION),
        ("ALIGN", (2, 1), (2, 1), "CENTER"),
    ))
    return KeepTogether([tabla, Spacer(1, 0.2 * cm)])


# ─────────────────────────────────────────────
# Encabezado, pie y marca de agua
# ─────────────────────────────────────────────
def _dibujar_pagina(canvas, documento, borrador: bool, id_permiso: int):
    canvas.saveState()
    ancho, alto = A4
    y_encabezado = alto - 0.6 * cm - ALTO_ENCABEZADO + 0.5 * cm

    # Encabezado: logo | título | código, versión y fecha.
    logo = _logo_recortado()
    celda_logo = _imagen(logo, 4.5 * cm, 1.7 * cm) if logo else ""
    encabezado = Table(
        [[
            celda_logo,
            _p_html(FORMATO_TITULO, ESTILO_TITULO),
            _p_html(
                f"<b>{FORMATO_CODIGO}<br/>{FORMATO_VERSION}<br/>{FORMATO_FECHA}</b>",
                ESTILO_TITULO,
            ),
        ]],
        colWidths=[4.9 * cm, ANCHO_UTIL - 4.9 * cm - 3.2 * cm, 3.2 * cm],
        rowHeights=[ALTO_ENCABEZADO - 0.5 * cm],
    )
    encabezado.setStyle(_estilo_tabla(("ALIGN", (0, 0), (0, 0), "CENTER")))
    encabezado.wrapOn(canvas, ANCHO_UTIL, ALTO_ENCABEZADO)
    encabezado.drawOn(canvas, MARGEN_IZQ, y_encabezado)

    # Pie: datos de contacto, número de permiso y página.
    for altura, etiqueta, valor in (
        (1.35 * cm, "Dirección:", PIE_DIRECCION),
        (1.0 * cm, "Teléfonos:", PIE_TELEFONOS),
        (0.65 * cm, "Email:", PIE_EMAIL),
    ):
        canvas.setFont("Helvetica-Bold", 7.5)
        canvas.drawString(MARGEN_IZQ, altura, etiqueta)
        ancho_etiqueta = canvas.stringWidth(etiqueta, "Helvetica-Bold", 7.5)
        canvas.setFont("Helvetica", 7.5)
        canvas.drawString(MARGEN_IZQ + ancho_etiqueta + 3, altura, valor)
    canvas.drawRightString(
        ancho - MARGEN_DER, 1.0 * cm,
        f"Permiso N.° {id_permiso}  ·  Página {documento.page}",
    )

    if borrador:
        canvas.setFont("Helvetica-Bold", 46)
        canvas.setFillColor(colors.Color(0.85, 0.2, 0.2, alpha=0.12))
        canvas.translate(ancho / 2, alto / 2)
        canvas.rotate(45)
        canvas.drawCentredString(0, 0, "BORRADOR")
        canvas.setFont("Helvetica-Bold", 16)
        canvas.drawCentredString(0, -1.0 * cm, "PERMISO NO AUTORIZADO")

    canvas.restoreState()


# ─────────────────────────────────────────────
# Generación
# ─────────────────────────────────────────────
def generar_pdf_permiso_alturas(db, id_permiso: int) -> bytes | None:
    """PDF del permiso, o None si no existe."""
    datos = _consultar_datos(db, id_permiso)

    if datos is None:
        return None

    p = datos["permiso"]
    listas = datos["listas"]
    borrador = p["estado"] == "EN_DILIGENCIAMIENTO"

    numero_verificacion = len(FILAS_APTITUD) + 1
    numero_peligros = numero_verificacion + len(listas["VERIFICACION"])
    espacio = Spacer(1, 0.3 * cm)

    contenido = [
        *_seccion_datos_basicos(p), espacio,
        *_seccion_trabajadores(datos["trabajadores"]), espacio,
        *_seccion_tarea(p), espacio,
        *_seccion_medidas(p), espacio,
        *_seccion_proteccion(listas["PROTECCION"], p["otro_epp"]), espacio,
        *_seccion_aptitud(datos["trabajadores"]), espacio,
        *_seccion_verificacion(listas["VERIFICACION"], numero_verificacion), espacio,
        *_seccion_peligros(listas["PELIGRO"], numero_peligros), espacio,
        *_seccion_textos_legales(p["observaciones"]), espacio,
    ]

    for rol, titulo in ROLES_FIRMA:
        # El recuadro del ayudante solo aparece si aplica.
        if rol == "AYUDANTE" and not p["aplica_ayudante"]:
            continue
        contenido.append(_bloque_firma(titulo, datos["firmas"].get(rol)))

    salida = BytesIO()
    documento = BaseDocTemplate(
        salida,
        pagesize=A4,
        leftMargin=MARGEN_IZQ,
        rightMargin=MARGEN_DER,
        topMargin=0.6 * cm + ALTO_ENCABEZADO,
        bottomMargin=ALTO_PIE + 0.2 * cm,
        title=f"Permiso de trabajo en alturas N.° {id_permiso}",
        author="Aseos La Perfección",
    )
    marco = Frame(
        documento.leftMargin,
        documento.bottomMargin,
        documento.width,
        documento.height,
        id="contenido",
        leftPadding=0,
        rightPadding=0,
        topPadding=0,
        bottomPadding=0,
    )
    documento.addPageTemplates([
        PageTemplate(
            id="permiso",
            frames=[marco],
            onPage=lambda c, d: _dibujar_pagina(c, d, borrador, id_permiso),
        )
    ])
    documento.build(contenido)

    return salida.getvalue()
