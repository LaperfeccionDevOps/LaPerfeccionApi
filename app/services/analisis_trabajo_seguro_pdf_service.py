"""
PDF del análisis de trabajo seguro (formato F-SS-006 del SG-SST).

Se arma por código para que crezca según lo diligenciado:
  * Pasos detallados de la tarea: una fila por peligro; la celda del paso
    abarca visualmente todos los peligros de su tarea.
  * Análisis de la tarea (verificación diaria): una columna por día de la
    semana del análisis.
  * Trabajadores que ejecutarán la tarea: una fila por trabajador con su firma.

Referencia de diseño: templates/alturas/ANALISIS DE TRABAJO EJEMPLO.pdf (no se
versiona porque contiene datos personales).
"""

from io import BytesIO
from datetime import timedelta

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import cm
from reportlab.platypus import (
    BaseDocTemplate,
    Frame,
    KeepTogether,
    PageTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
)
from sqlalchemy import text

from services.permiso_alturas_pdf_service import (
    PIE_DIRECCION,
    PIE_EMAIL,
    PIE_TELEFONOS,
    _imagen,
    _logo_recortado,
    _p,
    _p_html,
)

# ─────────────────────────────────────────────
# Datos del formato (control documental HSEQ)
# ─────────────────────────────────────────────
FORMATO_CODIGO = "F-SS-006"
FORMATO_VERSION = "V.04"
FORMATO_FECHA = "18-nov-19"
FORMATO_TITULO = "ANÁLISIS DE TRABAJO SEGURO"

ZONA_HORARIA = "America/Bogota"

# Filas de herramientas del formato: (etiqueta, Tipo del catálogo). Las que no
# tienen tipo se imprimen vacías (aún no se diligencian en el sistema).
FILAS_HERRAMIENTAS = [
    ("Manuales", "HERRAMIENTA_MANUAL"),
    ("Eléctricas", "HERRAMIENTA_ELECTRICA"),
    ("Neumáticas", None),
    ("Hidráulicas", None),
    ("Mecánicas", None),
    ("Otras. ¿Cuál?", None),
]

CODIGO_PERMISO_OTRO = "PER_OT"
RESPUESTAS = {"SI": "SÍ", "NO": "NO", "NA": "N/A"}
DIAS_SEMANA = ["lun", "mar", "mié", "jue", "vie", "sáb", "dom"]

# ─────────────────────────────────────────────
# Diseño (colores del formato F-SS-006)
# ─────────────────────────────────────────────
MARGEN_IZQ = 1.0 * cm
MARGEN_DER = 0.75 * cm
ALTO_ENCABEZADO = 2.4 * cm
ALTO_PIE = 1.8 * cm
ANCHO_UTIL = A4[0] - MARGEN_IZQ - MARGEN_DER

COLOR_BORDE = colors.HexColor("#1F2937")
VERDE_OSCURO = colors.HexColor("#375623")
VERDE_CLARO = colors.HexColor("#C4D79B")
ROJO_ALERTA = colors.HexColor("#B91C1C")

ESTILO = ParagraphStyle("ats", fontName="Helvetica", fontSize=7.5, leading=9.2)
ESTILO_NEGRITA = ParagraphStyle("ats_negrita", parent=ESTILO, fontName="Helvetica-Bold")
ESTILO_CENTRO = ParagraphStyle("ats_centro", parent=ESTILO, alignment=TA_CENTER)
ESTILO_CENTRO_NEGRITA = ParagraphStyle(
    "ats_centro_negrita", parent=ESTILO_NEGRITA, alignment=TA_CENTER
)
ESTILO_SECCION = ParagraphStyle(
    "ats_seccion", parent=ESTILO_CENTRO_NEGRITA, fontSize=8.5, leading=10.5,
    textColor=colors.white,
)
ESTILO_TITULO = ParagraphStyle(
    "ats_titulo", parent=ESTILO_CENTRO_NEGRITA, fontSize=13, leading=16
)
ESTILO_CODIGO = ParagraphStyle(
    "ats_codigo", parent=ESTILO_CENTRO_NEGRITA, fontSize=8.5, leading=11
)
ESTILO_ALERTA = ParagraphStyle(
    "ats_alerta", parent=ESTILO_CENTRO_NEGRITA, textColor=ROJO_ALERTA
)
ESTILO_PEQUENO = ParagraphStyle(
    "ats_pequeno", parent=ESTILO_CENTRO, fontSize=6.3, leading=7.6
)


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


def _titulo_seccion(titulo: str) -> Table:
    tabla = Table([[_p_html(titulo, ESTILO_SECCION)]], colWidths=[ANCHO_UTIL])
    tabla.setStyle(_estilo_tabla(("BACKGROUND", (0, 0), (-1, -1), VERDE_OSCURO)))
    return tabla


def _fecha(valor) -> str:
    return valor.strftime("%d/%m/%Y") if valor else "—"


def _lista(nombres: list[str]) -> str | None:
    return ", ".join(nombres) if nombres else None


# ─────────────────────────────────────────────
# Datos
# ─────────────────────────────────────────────
def _consultar_datos(db, id_analisis: int) -> dict | None:
    analisis = db.execute(
        text("""
            SELECT A."IdAnalisisTrabajoSeguro"   AS id,
                   C."Nombre"                    AS cliente,
                   A."LugarTrabajo"              AS lugar_trabajo,
                   (A."FechaCreacion" AT TIME ZONE :zona)::date AS fecha_inicio,
                   A."FechaFinalizacionActividad" AS fecha_fin,
                   A."AlturaAproximadaMetros"    AS altura,
                   A."DescripcionTarea"          AS descripcion,
                   A."OtroPermisoRequerido"      AS otro_permiso,
                   A."Estado"                    AS estado,
                   TRIM(RC."Nombres" || ' ' || RC."Apellidos") AS coordinador,
                   RC."NumeroIdentificacion"     AS cedula_coordinador,
                   A."FirmaCoordinador"          AS firma_coordinador,
                   (now() AT TIME ZONE :zona)::date AS hoy
            FROM public."AnalisisTrabajoSeguro" A
            JOIN public."Cliente" C ON C."IdCliente" = A."IdCliente"
            LEFT JOIN public."RegistroPersonal" RC
              ON RC."IdRegistroPersonal" = A."IdRegistroPersonalCoordinador"
            WHERE A."IdAnalisisTrabajoSeguro" = :id
        """),
        {"id": id_analisis, "zona": ZONA_HORARIA},
    ).mappings().first()

    if analisis is None:
        return None

    # Opciones elegidas por tipo (sistemas de acceso, herramientas, permisos).
    elegidas = db.execute(
        text("""
            SELECT O."Tipo" AS tipo, O."Nombre" AS nombre
            FROM public."AnalisisTrabajoSeguroOpcion" AO
            JOIN public."OpcionPermisoAlturas" O
              ON O."IdOpcionPermisoAlturas" = AO."IdOpcionPermisoAlturas"
            WHERE AO."IdAnalisisTrabajoSeguro" = :id
            ORDER BY O."Tipo", O."Orden"
        """),
        {"id": id_analisis},
    ).mappings().all()

    por_tipo: dict[str, list[str]] = {}
    for fila in elegidas:
        por_tipo.setdefault(fila["tipo"], []).append(fila["nombre"])

    # Las herramientas se muestran en orden alfabético, como en pantalla.
    for tipo in ("HERRAMIENTA_MANUAL", "HERRAMIENTA_ELECTRICA"):
        por_tipo.get(tipo, []).sort(key=str.casefold)

    # Casillas de "Para este trabajo se necesita permiso de": todas las
    # opciones activas más las elegidas que estén inactivas.
    permisos = db.execute(
        text("""
            SELECT O."Codigo" AS codigo,
                   O."Nombre" AS nombre,
                   EXISTS (
                       SELECT 1 FROM public."AnalisisTrabajoSeguroOpcion" AO
                       WHERE AO."IdAnalisisTrabajoSeguro" = :id
                         AND AO."IdOpcionPermisoAlturas" = O."IdOpcionPermisoAlturas"
                   ) AS elegido
            FROM public."OpcionPermisoAlturas" O
            WHERE O."Tipo" = 'PERMISO_REQUERIDO'
            ORDER BY O."Orden"
        """),
        {"id": id_analisis},
    ).mappings().all()
    permisos = [dict(p) for p in permisos]

    tareas = db.execute(
        text("""
            SELECT T."IdAnalisisTrabajoSeguroTarea" AS id,
                   T."PasoDetallado"                AS paso
            FROM public."AnalisisTrabajoSeguroTarea" T
            WHERE T."IdAnalisisTrabajoSeguro" = :id
            ORDER BY T."Orden"
        """),
        {"id": id_analisis},
    ).mappings().all()

    peligros = db.execute(
        text("""
            SELECT TP."IdAnalisisTrabajoSeguroTarea" AS id_tarea,
                   TP."Riesgo"               AS riesgo,
                   TP."Peligro"              AS peligro,
                   TP."PeligroAdicional"     AS peligro_adicional,
                   TP."RiesgoAsociado"       AS riesgo_asociado,
                   TP."ConsecuenciaAsociada" AS consecuencia
            FROM public."AnalisisTrabajoSeguroTareaPeligro" TP
            JOIN public."AnalisisTrabajoSeguroTarea" T
              ON T."IdAnalisisTrabajoSeguroTarea" = TP."IdAnalisisTrabajoSeguroTarea"
            WHERE T."IdAnalisisTrabajoSeguro" = :id
            ORDER BY TP."IdAnalisisTrabajoSeguroTareaPeligro"
        """),
        {"id": id_analisis},
    ).mappings().all()

    preguntas = db.execute(
        text("""
            SELECT "IdItemPermisoAlturas" AS id,
                   "Texto"                AS texto,
                   "RespuestaAlerta"      AS alerta
            FROM public."ItemPermisoAlturas"
            WHERE "TipoItem" = 'ATS_DIARIA'
              AND ("Activo" OR "IdItemPermisoAlturas" IN (
                  SELECT DR."IdItemPermisoAlturas"
                  FROM public."AnalisisTrabajoSeguroDiaRespuesta" DR
                  JOIN public."AnalisisTrabajoSeguroDia" D
                    ON D."IdAnalisisTrabajoSeguroDia" = DR."IdAnalisisTrabajoSeguroDia"
                  WHERE D."IdAnalisisTrabajoSeguro" = :id
              ))
            ORDER BY "Orden"
        """),
        {"id": id_analisis},
    ).mappings().all()

    dias = db.execute(
        text("""
            SELECT D."IdAnalisisTrabajoSeguroDia" AS id,
                   D."Fecha"                      AS fecha,
                   D."DiligenciadoTarde"          AS tarde,
                   TRIM(R."Nombres" || ' ' || R."Apellidos") AS persona
            FROM public."AnalisisTrabajoSeguroDia" D
            JOIN public."RegistroPersonal" R
              ON R."IdRegistroPersonal" = D."IdRegistroPersonal"
            WHERE D."IdAnalisisTrabajoSeguro" = :id
        """),
        {"id": id_analisis},
    ).mappings().all()

    respuestas = db.execute(
        text("""
            SELECT DR."IdAnalisisTrabajoSeguroDia" AS id_dia,
                   DR."IdItemPermisoAlturas"       AS id_item,
                   DR."Respuesta"                  AS respuesta
            FROM public."AnalisisTrabajoSeguroDiaRespuesta" DR
            JOIN public."AnalisisTrabajoSeguroDia" D
              ON D."IdAnalisisTrabajoSeguroDia" = DR."IdAnalisisTrabajoSeguroDia"
            WHERE D."IdAnalisisTrabajoSeguro" = :id
        """),
        {"id": id_analisis},
    ).mappings().all()

    trabajadores = db.execute(
        text("""
            SELECT TRIM(R."Nombres" || ' ' || R."Apellidos") AS nombre,
                   R."NumeroIdentificacion" AS cedula,
                   T."FirmaImagen"          AS firma
            FROM public."AnalisisTrabajoSeguroTrabajador" T
            JOIN public."RegistroPersonal" R
              ON R."IdRegistroPersonal" = T."IdRegistroPersonal"
            WHERE T."IdAnalisisTrabajoSeguro" = :id
            ORDER BY T."IdAnalisisTrabajoSeguroTrabajador"
        """),
        {"id": id_analisis},
    ).mappings().all()

    # Días de la semana del análisis con sus respuestas.
    registros = {d["fecha"]: dict(d) for d in dias}
    for registro in registros.values():
        registro["respuestas"] = {
            r["id_item"]: r["respuesta"] for r in respuestas if r["id_dia"] == registro["id"]
        }

    lista_dias = []
    dia = analisis["fecha_inicio"]
    while dia <= analisis["fecha_fin"]:
        lista_dias.append({"fecha": dia, "registro": registros.get(dia)})
        dia += timedelta(days=1)

    return {
        "analisis": dict(analisis),
        "opciones": por_tipo,
        "permisos": permisos,
        "tareas": [
            {
                "paso": t["paso"],
                "peligros": [dict(p) for p in peligros if p["id_tarea"] == t["id"]],
            }
            for t in tareas
        ],
        "preguntas": [dict(p) for p in preguntas],
        "dias": lista_dias,
        "trabajadores": [
            {**dict(t), "firma": bytes(t["firma"]) if t["firma"] else None}
            for t in trabajadores
        ],
    }


# ─────────────────────────────────────────────
# Secciones
# ─────────────────────────────────────────────
def _seccion_datos(a: dict, sistemas_acceso: list[str]) -> list:
    etiqueta = ESTILO_NEGRITA
    ancho_e = 2.6 * cm

    # Sede y lugar | sistema de acceso.
    anchos_1 = [ancho_e, 7.0 * cm, 2.9 * cm]
    anchos_1.append(ANCHO_UTIL - sum(anchos_1))
    tabla_1 = Table(
        [
            [_p("Sede de trabajo:", etiqueta), _p(a["cliente"]),
             _p("Sistema de acceso a utilizar:", etiqueta), _p(_lista(sistemas_acceso))],
            [_p("Lugar de trabajo:", etiqueta), _p(a["lugar_trabajo"]), "", ""],
        ],
        colWidths=anchos_1,
    )
    tabla_1.setStyle(_estilo_tabla(
        ("SPAN", (2, 0), (2, 1)),
        ("SPAN", (3, 0), (3, 1)),
    ))

    # Fechas y altura.
    altura = f"{a['altura']:g} metros" if a["altura"] is not None else None
    anchos_2 = [ancho_e, 2.6 * cm, 2.6 * cm, 2.6 * cm, 2.3 * cm]
    anchos_2.append(ANCHO_UTIL - sum(anchos_2))
    tabla_2 = Table(
        [[
            _p("Fecha de inicio", etiqueta), _p(_fecha(a["fecha_inicio"]), ESTILO_CENTRO),
            _p("Fecha de finalización", etiqueta), _p(_fecha(a["fecha_fin"]), ESTILO_CENTRO),
            _p("Altura aprox.", etiqueta), _p(altura, ESTILO_CENTRO),
        ]],
        colWidths=anchos_2,
    )
    tabla_2.setStyle(_estilo_tabla(
        *[("BACKGROUND", (c, 0), (c, 0), VERDE_CLARO) for c in (0, 2, 4)],
    ))

    tabla_3 = Table(
        [[_p("Descripción de la tarea a realizar:", etiqueta), _p(a["descripcion"])]],
        colWidths=[5.0 * cm, ANCHO_UTIL - 5.0 * cm],
    )
    tabla_3.setStyle(_estilo_tabla(("BACKGROUND", (0, 0), (0, 0), VERDE_CLARO)))

    return [KeepTogether([tabla_1, tabla_2, tabla_3])]


def _seccion_permisos(permisos: list, otro: str | None) -> list:
    # Tres casillas por fila: (nombre, X).
    ancho_x = 0.8 * cm
    ancho_nombre = ANCHO_UTIL / 3 - ancho_x
    celdas = []

    for permiso in permisos:
        nombre = permiso["nombre"].upper()
        if permiso["codigo"] == CODIGO_PERMISO_OTRO:
            nombre = f"OTRO, ¿CUÁL? {otro or ''}".strip()
        elif permiso["codigo"].endswith("_NA"):
            nombre = "N/A"
        celdas += [_p(nombre, ESTILO_NEGRITA),
                   _p("X", ESTILO_CENTRO_NEGRITA) if permiso["elegido"] else ""]

    while len(celdas) % 6:
        celdas.append("")

    filas = [celdas[i:i + 6] for i in range(0, len(celdas), 6)]
    tabla = Table(filas, colWidths=[ancho_nombre, ancho_x] * 3)
    tabla.setStyle(_estilo_tabla(
        *[("BACKGROUND", (c, 0), (c, -1), VERDE_CLARO) for c in (0, 2, 4)],
    ))
    return [KeepTogether([
        _titulo_seccion("PARA ESTE TRABAJO SE NECESITA PERMISO DE:"), tabla,
    ])]


def _seccion_herramientas(opciones: dict) -> list:
    anchos = [ANCHO_UTIL * 0.4, ANCHO_UTIL * 0.6]
    filas = [[
        _p("EQUIPOS Y HERRAMIENTAS", ESTILO_CENTRO_NEGRITA),
        _p("INDIQUE CADA UNA DE LAS HERRAMIENTAS A UTILIZAR", ESTILO_CENTRO_NEGRITA),
    ]]
    for etiqueta, tipo in FILAS_HERRAMIENTAS:
        valor = _lista(opciones.get(tipo, [])) if tipo else ""
        filas.append([_p(etiqueta, ESTILO_CENTRO), _p(valor, ESTILO_CENTRO) if valor else ""])

    tabla = Table(filas, colWidths=anchos)
    tabla.setStyle(_estilo_tabla(("BACKGROUND", (0, 0), (-1, 0), VERDE_CLARO)))
    return [KeepTogether([_titulo_seccion("EQUIPOS Y HERRAMIENTAS A UTILIZAR"), tabla])]


def _texto_peligro(peligro: dict) -> str:
    def e(valor):
        from xml.sax.saxutils import escape
        return escape(valor or "")

    titulo = f"{e(peligro['riesgo'])} - {e(peligro['peligro'])}"
    detalle = e(peligro["peligro"])
    if peligro["peligro_adicional"]:
        detalle += f" · {e(peligro['peligro_adicional'])}"
    return (
        f"{titulo}<br/><b>Peligro:</b> {detalle}"
        f"<br/><b>Riesgos:</b> {e(peligro['riesgo_asociado'])}"
    )


def _seccion_tareas(tareas: list) -> list:
    anchos = [4.4 * cm, 5.4 * cm, 4.6 * cm]
    anchos.append(ANCHO_UTIL - sum(anchos))
    encabezado = [
        _p_html(texto, ESTILO_SECCION) for texto in (
            "Pasos detallados de la tarea",
            "Peligros existentes y potenciales",
            "Consecuencias",
            "Controles requeridos",
        )
    ]
    filas = [encabezado]
    # La celda del paso no se combina (para poder partir la tabla entre
    # páginas): se escribe en la primera fila de la tarea y se ocultan las
    # líneas internas de esa columna.
    inicios = []

    for numero, tarea in enumerate(tareas, start=1):
        inicios.append(len(filas))
        peligros = tarea["peligros"] or [None]
        for indice, peligro in enumerate(peligros):
            filas.append([
                _p(f"{numero}. {tarea['paso']}") if indice == 0 else "",
                _p_html(_texto_peligro(peligro), ESTILO) if peligro else _p(None),
                _p(peligro["consecuencia"]) if peligro else _p(None),
                # Pendiente: HSEQ entregará los controles por riesgo y peligro.
                "",
            ])

    if not tareas:
        filas.append([_p("Sin tareas registradas."), "", "", ""])

    estilos = [
        ("BACKGROUND", (0, 0), (-1, 0), VERDE_OSCURO),
        ("VALIGN", (0, 1), (-1, -1), "TOP"),
        # Columna del paso: sin líneas internas, solo al inicio de cada tarea.
        ("LINEBELOW", (0, 1), (0, -1), 0, colors.white),
        ("LINEABOVE", (0, 1), (0, -1), 0, colors.white),
        ("LINEBEFORE", (0, 0), (0, -1), 0.6, COLOR_BORDE),
        ("LINEAFTER", (0, 0), (0, -1), 0.6, COLOR_BORDE),
        ("LINEBELOW", (0, -1), (-1, -1), 0.6, COLOR_BORDE),
    ]
    for inicio in inicios:
        estilos.append(("LINEABOVE", (0, inicio), (0, inicio), 0.6, COLOR_BORDE))
    if not tareas:
        estilos.append(("SPAN", (0, 1), (-1, 1)))

    tabla = Table(filas, colWidths=anchos, repeatRows=1)
    tabla.setStyle(_estilo_tabla(*estilos))
    return [tabla]


def _seccion_verificacion(preguntas: list, dias: list) -> list:
    if not dias:
        return []

    ancho_pregunta = 6.4 * cm
    ancho_dia = (ANCHO_UTIL - ancho_pregunta) / len(dias)
    anchos = [ancho_pregunta] + [ancho_dia] * len(dias)

    filas = [
        [_p_html("ANÁLISIS DE LA TAREA", ESTILO_SECCION), _p_html("DÍA", ESTILO_SECCION)]
        + [""] * (len(dias) - 1),
        [""] + [
            _p(f"{DIAS_SEMANA[d['fecha'].weekday()]} {d['fecha']:%d/%m}", ESTILO_CENTRO_NEGRITA)
            for d in dias
        ],
    ]
    estilos = [
        ("SPAN", (1, 0), (-1, 0)),
        ("BACKGROUND", (0, 0), (-1, 0), VERDE_OSCURO),
        ("BACKGROUND", (0, 1), (-1, 1), VERDE_CLARO),
        ("BACKGROUND", (0, 2), (0, -1), VERDE_CLARO),
    ]

    for numero, pregunta in enumerate(preguntas, start=1):
        fila = [_p(pregunta["texto"], ESTILO_CENTRO_NEGRITA)]
        for dia in dias:
            registro = dia["registro"]
            respuesta = registro["respuestas"].get(pregunta["id"]) if registro else None
            if not respuesta:
                fila.append("")
            else:
                # Respuesta que indica un problema: en rojo.
                alerta = respuesta == pregunta["alerta"]
                fila.append(_p(RESPUESTAS[respuesta], ESTILO_ALERTA if alerta else ESTILO_CENTRO))
        filas.append(fila)

    # Quién diligenció cada día (y si fue tarde).
    fila_persona = [_p("Diligenciado por", ESTILO_CENTRO_NEGRITA)]
    for dia in dias:
        registro = dia["registro"]
        if registro:
            texto = registro["persona"] + (" (tarde)" if registro["tarde"] else "")
        else:
            texto = ""
        fila_persona.append(_p(texto, ESTILO_PEQUENO) if texto else "")
    filas.append(fila_persona)

    tabla = Table(filas, colWidths=anchos, repeatRows=2)
    tabla.setStyle(_estilo_tabla(*estilos))
    # La lista es corta: se mantiene completa en una sola página.
    return [KeepTogether(tabla)]


def _seccion_trabajadores(trabajadores: list) -> list:
    anchos = [ANCHO_UTIL * 0.38, ANCHO_UTIL * 0.17, ANCHO_UTIL * 0.45]
    filas = [
        [_p_html("TRABAJADORES QUE EJECUTARÁN LA TAREA", ESTILO_SECCION), "", ""],
        [_p("Nombre y apellidos", ESTILO_CENTRO_NEGRITA),
         _p("Cédula", ESTILO_CENTRO_NEGRITA), _p("Firma", ESTILO_CENTRO_NEGRITA)],
    ]
    for t in trabajadores:
        filas.append([
            _p(t["nombre"], ESTILO_CENTRO),
            _p(t["cedula"], ESTILO_CENTRO),
            _imagen(t["firma"], anchos[2] - 0.6 * cm, 1.4 * cm),
        ])
    if not trabajadores:
        filas.append([_p("Sin trabajadores registrados."), "", ""])

    estilos = [
        ("SPAN", (0, 0), (-1, 0)),
        ("BACKGROUND", (0, 0), (-1, 0), VERDE_OSCURO),
        ("BACKGROUND", (0, 1), (-1, 1), VERDE_CLARO),
        ("ALIGN", (2, 2), (2, -1), "CENTER"),
    ]
    if not trabajadores:
        estilos.append(("SPAN", (0, 2), (-1, 2)))

    tabla = Table(
        filas,
        colWidths=anchos,
        rowHeights=[None, None] + [1.7 * cm] * max(len(trabajadores), 1),
        repeatRows=2,
    )
    tabla.setStyle(_estilo_tabla(*estilos))
    return [tabla]


def _seccion_visto_bueno(a: dict) -> list:
    anchos = [ANCHO_UTIL * 0.38, ANCHO_UTIL * 0.17, ANCHO_UTIL * 0.45]
    firma = bytes(a["firma_coordinador"]) if a["firma_coordinador"] else None
    filas = [
        [_p("Vo.Bo. Planilla - Nombre Coordinador de Alturas", ESTILO_CENTRO_NEGRITA),
         _p("Cédula", ESTILO_CENTRO_NEGRITA), _p("Firma", ESTILO_CENTRO_NEGRITA)],
        [_p(a["coordinador"], ESTILO_CENTRO), _p(a["cedula_coordinador"], ESTILO_CENTRO),
         _imagen(firma, anchos[2] - 0.6 * cm, 1.4 * cm) if firma else ""],
    ]
    tabla = Table(filas, colWidths=anchos, rowHeights=[None, 1.7 * cm])
    tabla.setStyle(_estilo_tabla(
        ("BACKGROUND", (0, 0), (-1, 0), VERDE_CLARO),
        ("ALIGN", (2, 1), (2, 1), "CENTER"),
    ))
    return [KeepTogether(tabla)]


# ─────────────────────────────────────────────
# Encabezado, pie y marca de agua
# ─────────────────────────────────────────────
def _dibujar_pagina(canvas, documento, borrador: bool, id_analisis: int):
    canvas.saveState()
    ancho, alto = A4
    y_encabezado = alto - 0.6 * cm - ALTO_ENCABEZADO + 0.5 * cm

    logo = _logo_recortado()
    encabezado = Table(
        [[
            _imagen(logo, 4.5 * cm, 1.7 * cm) if logo else "",
            _p_html(FORMATO_TITULO, ESTILO_TITULO),
            _p_html(f"{FORMATO_CODIGO}<br/>{FORMATO_VERSION}<br/>{FORMATO_FECHA}", ESTILO_CODIGO),
        ]],
        colWidths=[4.9 * cm, ANCHO_UTIL - 4.9 * cm - 3.2 * cm, 3.2 * cm],
        rowHeights=[ALTO_ENCABEZADO - 0.5 * cm],
    )
    encabezado.setStyle(_estilo_tabla(("ALIGN", (0, 0), (0, 0), "CENTER")))
    encabezado.wrapOn(canvas, ANCHO_UTIL, ALTO_ENCABEZADO)
    encabezado.drawOn(canvas, MARGEN_IZQ, y_encabezado)

    # Pie: línea verde, datos de contacto, número de análisis y página.
    canvas.setStrokeColor(VERDE_OSCURO)
    canvas.setLineWidth(1.5)
    canvas.line(MARGEN_IZQ, 1.65 * cm, ancho - MARGEN_DER, 1.65 * cm)
    for altura, etiqueta, valor in (
        (1.3 * cm, "Dirección:", PIE_DIRECCION),
        (0.95 * cm, "Teléfonos:", PIE_TELEFONOS),
        (0.6 * cm, "Email:", PIE_EMAIL),
    ):
        canvas.setFont("Helvetica-Bold", 7.5)
        canvas.drawString(MARGEN_IZQ, altura, etiqueta)
        ancho_etiqueta = canvas.stringWidth(etiqueta, "Helvetica-Bold", 7.5)
        canvas.setFont("Helvetica", 7.5)
        canvas.drawString(MARGEN_IZQ + ancho_etiqueta + 3, altura, valor)
    canvas.drawRightString(
        ancho - MARGEN_DER, 0.95 * cm,
        f"Análisis N.° {id_analisis}  ·  Página {documento.page}",
    )

    if borrador:
        canvas.setFont("Helvetica-Bold", 46)
        canvas.setFillColor(colors.Color(0.85, 0.2, 0.2, alpha=0.12))
        canvas.translate(ancho / 2, alto / 2)
        canvas.rotate(45)
        canvas.drawCentredString(0, 0, "BORRADOR")
        canvas.setFont("Helvetica-Bold", 16)
        canvas.drawCentredString(0, -1.0 * cm, "SIN VISTO BUENO DEL COORDINADOR")

    canvas.restoreState()


# ─────────────────────────────────────────────
# Generación
# ─────────────────────────────────────────────
def generar_pdf_analisis_trabajo_seguro(db, id_analisis: int) -> bytes | None:
    """PDF del análisis, o None si no existe."""
    datos = _consultar_datos(db, id_analisis)

    if datos is None:
        return None

    a = datos["analisis"]
    borrador = a["estado"] != "APROBADO"
    espacio = Spacer(1, 0.3 * cm)

    contenido = [
        *_seccion_datos(a, datos["opciones"].get("SISTEMA_ACCESO", [])), espacio,
        *_seccion_permisos(datos["permisos"], a["otro_permiso"]), espacio,
        *_seccion_herramientas(datos["opciones"]), espacio,
        *_seccion_tareas(datos["tareas"]), espacio,
        *_seccion_verificacion(datos["preguntas"], datos["dias"]), espacio,
        *_seccion_trabajadores(datos["trabajadores"]), espacio,
        *_seccion_visto_bueno(a),
    ]

    salida = BytesIO()
    documento = BaseDocTemplate(
        salida,
        pagesize=A4,
        leftMargin=MARGEN_IZQ,
        rightMargin=MARGEN_DER,
        topMargin=0.6 * cm + ALTO_ENCABEZADO,
        bottomMargin=ALTO_PIE + 0.2 * cm,
        title=f"Análisis de trabajo seguro N.° {id_analisis}",
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
            id="analisis",
            frames=[marco],
            onPage=lambda c, d: _dibujar_pagina(c, d, borrador, id_analisis),
        )
    ])
    documento.build(contenido)

    return salida.getvalue()
