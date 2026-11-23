"""Cálculo de horas semanales de una línea de asignación de operarios.

Reglas validadas con Contabilidad: solo hay tres tipos de turno y cada
operario completa las horas máximas legales de la semana (hoy 42), repartidas
por igual entre los días que trabaja:

- DIURNO: dentro de la franja diurna; sin horas nocturnas.
- TARDE: termina entre las 19:00 y las 24:00; las horas desde el inicio de la
  franja nocturna hasta la salida son nocturnas.
- NOCHE: todas sus horas son nocturnas.

Los días (lunes a viernes, lunes a sábado o domingo a domingo) definen cuántas
horas trabaja por día y si hay horas dominicales: con domingo, las horas de ese
día son dominicales y, si además son nocturnas, nocturnas dominicales (llevan
los dos recargos; ya están incluidas en las nocturnas y en las dominicales).

En la TARDE la salida puede cambiar según el día (`minutos_salida_dia`): las
horas por día siguen iguales y cada día suma sus nocturnas desde las 19:00 hasta
su salida, que va de 19:00 a 24:00 como la general (un día que termina antes se
registra a las 19:00: no suma nocturnas). Con domingo a domingo
y descanso entre semana, el descanso rota de lunes a viernes: las nocturnas de
esos días se promedian (suma × 4/5) y se suman las del sábado y el domingo.
Las salidas van cada 10 minutos.
"""

from dataclasses import dataclass
from datetime import time

MINUTOS_DIA = 24 * 60
DOMINGO = 7

TIPOS_TURNO = ("DIURNO", "TARDE", "NOCHE")
# Hora de salida del turno de la tarde: entre las 19:00 y las 24:00.
SALIDA_TARDE_MINIMA = 19 * 60
SALIDA_TARDE_MAXIMA = 24 * 60
# Las salidas se eligen cada 10 minutos.
INTERVALO_SALIDA = 10
NOMBRES_DIA = {1: "Lun", 2: "Mar", 3: "Mié", 4: "Jue", 5: "Vie", 6: "Sáb", 7: "Dom"}


@dataclass(frozen=True)
class HorasSemana:
    horas: float
    nocturnas: float
    dominicales: float
    nocturnas_dominicales: float
    # Por día trabajado y, en la tarde, la entrada que resulta de la salida.
    horas_dia: float
    minuto_entrada: int | None = None
    # Entrada del domingo cuando termina a otra hora.
    minuto_entrada_domingo: int | None = None
    # Salida por día: {día: minutos nocturnos} de cada día que labora.
    minutos_nocturnos_dia: dict[int, float] | None = None


def _minutos(hora: time) -> int:
    return hora.hour * 60 + hora.minute


def dias_trabajados(dias_semana: list[int], descansa_dia_entre_semana: bool = False) -> list[int]:
    """Días que trabaja cada operario. Con descanso entre semana se quita un
    día de lunes a viernes (el miércoles, o el primero que haya); el domingo se
    sigue trabajando."""
    dias = sorted(set(dias_semana))
    entre_semana = [d for d in dias if d <= 5]

    if not descansa_dia_entre_semana:
        return dias
    if not entre_semana:
        raise ValueError("No hay días entre semana para el descanso.")

    descanso = 3 if 3 in entre_semana else entre_semana[0]
    return [d for d in dias if d != descanso]


def _texto(minutos: float) -> str:
    minutos = round(minutos)
    return f"{minutos // 60:02d}:{minutos % 60:02d}"


def resumen_salidas(minutos_salida_dia: dict[int, int], minutos_dia: float, incluir_domingo: bool = True) -> str:
    """"Lun, Mar 13:20 a 20:20 · Mié, Vie 14:00 a 21:00 · Jue 15:00 a 22:00":
    agrupa los días que salen a la misma hora."""
    grupos: dict[int, list[int]] = {}
    for dia in sorted(minutos_salida_dia):
        if dia == DOMINGO and not incluir_domingo:
            continue
        grupos.setdefault(minutos_salida_dia[dia], []).append(dia)
    return " · ".join(
        f"{', '.join(NOMBRES_DIA[d] for d in dias)} {_texto(salida - minutos_dia)} a {_texto(salida)}"
        for salida, dias in sorted(grupos.items(), key=lambda g: g[1][0])
    )


def _nocturnos_en_franja(entrada: int, salida: int, inicio_nocturna: int, fin_nocturna: int) -> float:
    """Minutos nocturnos de un turno dentro del mismo día (entrada y salida en
    minutos desde la medianoche): antes del fin de la franja (06:00) y desde su
    inicio (19:00) hasta la medianoche."""
    madrugada = max(0, min(salida, fin_nocturna) - entrada)
    noche = max(0, salida - max(entrada, inicio_nocturna))
    return madrugada + noche


def calcular_horas_turno(
    tipo_turno: str,
    dias_semana: list[int],
    horas_maximas_semana: float,
    hora_inicio_nocturna: time,
    minuto_salida: int | None = None,
    descansa_dia_entre_semana: bool = False,
    minuto_salida_domingo: int | None = None,
    hora_fin_nocturna: time = time(6, 0),
    minutos_salida_dia: dict[int, int] | None = None,
) -> HorasSemana:
    """`dias_semana` en ISO (1 = lunes ... 7 = domingo). `minuto_salida` solo
    para TARDE: minutos desde la medianoche (1140 = 19:00 ... 1440 = 24:00).
    `minuto_salida_domingo`: en TARDE o NOCHE con domingo, hora a la que
    termina el turno del domingo si es distinta a la de los demás días; las
    horas de ese día son las mismas, pero cambia cuántas caen en la franja
    nocturna (nocturnas dominicales) y cuántas en la diurna (dominicales diurnas).
    `minutos_salida_dia`: solo TARDE; salida de cada día que labora
    ({1: 1220, ...}), incluido el domingo (no se combina con la del domingo)."""
    if tipo_turno not in TIPOS_TURNO:
        raise ValueError("El tipo de turno debe ser Diurno, Tarde o Noche.")

    if tipo_turno == "TARDE":
        if minuto_salida is None:
            raise ValueError("Indica la hora en que termina el turno de la tarde.")
        if not SALIDA_TARDE_MINIMA <= minuto_salida <= SALIDA_TARDE_MAXIMA:
            raise ValueError("El turno de la tarde debe terminar entre las 19:00 y las 24:00.")
    elif minuto_salida is not None:
        raise ValueError("La hora de salida solo se indica en el turno de la tarde.")

    for salida in (minuto_salida, minuto_salida_domingo, *(minutos_salida_dia or {}).values()):
        if salida is not None and salida % INTERVALO_SALIDA:
            raise ValueError("Las horas de salida van cada 10 minutos.")

    if minutos_salida_dia is not None:
        if tipo_turno != "TARDE":
            raise ValueError("La salida por día solo aplica al turno de la tarde.")
        if minuto_salida_domingo is not None:
            raise ValueError("Con salida por día, la del domingo va en la misma lista.")
        if set(minutos_salida_dia) != set(dias_semana):
            raise ValueError("Indica la salida de cada uno de los días que labora.")

    dias = dias_trabajados(dias_semana, descansa_dia_entre_semana)
    if not dias:
        raise ValueError("No hay días de trabajo.")

    # Minutos por día, repartiendo por igual las horas de la semana.
    minutos_semana = round(float(horas_maximas_semana) * 60)
    minutos_dia = minutos_semana / len(dias)
    trabaja_domingo = DOMINGO in dias

    inicio_nocturna = _minutos(hora_inicio_nocturna)
    fin_nocturna = _minutos(hora_fin_nocturna)

    if minutos_salida_dia is not None:
        return _horas_salida_por_dia(
            sorted(set(dias_semana)), minutos_salida_dia, minutos_semana, minutos_dia,
            descansa_dia_entre_semana, inicio_nocturna, fin_nocturna,
        )

    minuto_entrada = None
    if tipo_turno == "DIURNO":
        nocturnos_dia = 0.0
    elif tipo_turno == "NOCHE":
        nocturnos_dia = minutos_dia
    else:
        # Desde el inicio de la franja nocturna (19:00) hasta la salida.
        minuto_entrada = round(minuto_salida - minutos_dia)
        nocturnos_dia = _nocturnos_en_franja(minuto_salida - minutos_dia, minuto_salida, inicio_nocturna, fin_nocturna)

    # Domingo con otra hora de salida (solo tarde o noche que trabajan domingo).
    minuto_entrada_domingo = None
    nocturnos_domingo = nocturnos_dia
    if minuto_salida_domingo is not None:
        if tipo_turno == "DIURNO" or not trabaja_domingo:
            raise ValueError("La hora de salida del domingo solo aplica a la tarde o la noche cuando se trabaja el domingo.")
        if not 0 < minuto_salida_domingo <= MINUTOS_DIA:
            raise ValueError("La hora de salida del domingo debe estar entre las 00:30 y las 24:00.")
        entrada_domingo = minuto_salida_domingo - minutos_dia
        if entrada_domingo < 0:
            raise ValueError(
                f"Con {minutos_dia / 60:g} h por día, el turno del domingo empezaría el sábado; "
                "elige una hora de salida más tarde."
            )
        minuto_entrada_domingo = round(entrada_domingo)
        nocturnos_domingo = _nocturnos_en_franja(entrada_domingo, minuto_salida_domingo, inicio_nocturna, fin_nocturna)

    dias_no_domingo = len(dias) - (1 if trabaja_domingo else 0)
    nocturnos = nocturnos_dia * dias_no_domingo + (nocturnos_domingo if trabaja_domingo else 0)
    dominicales = minutos_dia if trabaja_domingo else 0
    nocturnos_dominicales = nocturnos_domingo if trabaja_domingo else 0

    return HorasSemana(
        horas=round(minutos_semana / 60, 2),
        nocturnas=round(nocturnos / 60, 2),
        dominicales=round(dominicales / 60, 2),
        nocturnas_dominicales=round(nocturnos_dominicales / 60, 2),
        horas_dia=round(minutos_dia / 60, 2),
        minuto_entrada=minuto_entrada,
        minuto_entrada_domingo=minuto_entrada_domingo,
    )


def _horas_salida_por_dia(
    dias: list[int],
    minutos_salida_dia: dict[int, int],
    minutos_semana: int,
    minutos_dia: float,
    descansa_dia_entre_semana: bool,
    inicio_nocturna: int,
    fin_nocturna: int,
) -> HorasSemana:
    """Tarde con salida distinta según el día (ver el encabezado)."""
    nocturnos_dia: dict[int, float] = {}
    for dia in dias:
        salida = minutos_salida_dia[dia]
        entrada = salida - minutos_dia
        if not SALIDA_TARDE_MINIMA <= salida <= SALIDA_TARDE_MAXIMA:
            raise ValueError(f"{NOMBRES_DIA[dia]}: la salida debe estar entre las 19:00 y las 24:00.")
        nocturnos_dia[dia] = _nocturnos_en_franja(entrada, salida, inicio_nocturna, fin_nocturna)

    entre_semana = [d for d in dias if d <= 5]
    if descansa_dia_entre_semana:
        # El descanso rota de lunes a viernes: promedio de esos días.
        factor = (len(entre_semana) - 1) / len(entre_semana)
        nocturnos = factor * sum(nocturnos_dia[d] for d in entre_semana) + sum(
            nocturnos_dia[d] for d in dias if d > 5
        )
    else:
        nocturnos = sum(nocturnos_dia.values())

    trabaja_domingo = DOMINGO in dias
    return HorasSemana(
        horas=round(minutos_semana / 60, 2),
        nocturnas=round(nocturnos / 60, 2),
        dominicales=round(minutos_dia / 60, 2) if trabaja_domingo else 0,
        nocturnas_dominicales=round(nocturnos_dia[DOMINGO] / 60, 2) if trabaja_domingo else 0,
        horas_dia=round(minutos_dia / 60, 2),
        minutos_nocturnos_dia=nocturnos_dia,
    )
