"""Cálculo de horas semanales de una línea de asignación de operarios.

Por operario y por semana:
- horas: duración de cada turno menos desayuno, almuerzo y cena;
- nocturnas: minutos del turno dentro de la franja nocturna (p. ej. 19:00-06:00);
- dominicales: minutos del turno que caen en domingo.
- nocturnas dominicales: los que son a la vez nocturnos y de domingo (llevan
  los dos recargos); ya están incluidos en las nocturnas y en las dominicales.
Cada descanso (desayuno, almuerzo, cena) tiene hora de inicio y duración: esos
minutos no cuentan como trabajados ni como nocturnos o dominicales. Un turno cuya salida es menor o igual a la entrada
termina al día siguiente (22:00 -> 06:00); si es el domingo, sigue en lunes.
"""

from dataclasses import dataclass
from datetime import time

MINUTOS_DIA = 24 * 60
MINUTOS_SEMANA = 7 * MINUTOS_DIA
SABADO = 6
DOMINGO = 7


@dataclass(frozen=True)
class Horario:
    hora_inicio: time
    hora_fin: time
    minutos_desayuno: int = 0
    minutos_almuerzo: int = 0
    minutos_cena: int = 0
    hora_desayuno: time | None = None
    hora_almuerzo: time | None = None
    hora_cena: time | None = None

    @property
    def minutos_descanso(self) -> int:
        return self.minutos_desayuno + self.minutos_almuerzo + self.minutos_cena

    def descansos(self) -> list[tuple[str, time | None, int]]:
        return [
            ("desayuno", self.hora_desayuno, self.minutos_desayuno),
            ("almuerzo", self.hora_almuerzo, self.minutos_almuerzo),
            ("cena", self.hora_cena, self.minutos_cena),
        ]


@dataclass(frozen=True)
class HorasSemana:
    horas: float
    nocturnas: float
    dominicales: float
    nocturnas_dominicales: float


def _minutos(hora: time) -> int:
    return hora.hour * 60 + hora.minute


def duracion_minutos(horario: Horario) -> int:
    """Duración del turno; si la salida es menor o igual a la entrada, al día siguiente."""
    duracion = (_minutos(horario.hora_fin) - _minutos(horario.hora_inicio)) % MINUTOS_DIA
    if duracion == 0:
        raise ValueError("La hora de entrada y la de salida no pueden ser iguales.")
    return duracion


def minutos_en_descanso(horario: Horario) -> set[int]:
    """Minutos del turno (contados desde la entrada) que son descanso. Cada
    descanso con minutos debe tener hora, quedar dentro del turno y no cruzarse
    con otro."""
    duracion = duracion_minutos(horario)
    inicio_turno = _minutos(horario.hora_inicio)
    ocupados: set[int] = set()

    for nombre, hora, minutos in horario.descansos():
        if not minutos:
            continue
        if hora is None:
            raise ValueError(f"Indica la hora del {nombre}.")

        desde = (_minutos(hora) - inicio_turno) % MINUTOS_DIA
        if desde + minutos > duracion:
            raise ValueError(f"El {nombre} debe quedar dentro del turno.")

        tramo = set(range(desde, desde + minutos))
        if tramo & ocupados:
            raise ValueError(f"El {nombre} se cruza con otro descanso.")
        ocupados |= tramo

    return ocupados


def _es_nocturno(minuto_del_dia: int, inicio_nocturna: int, fin_nocturna: int) -> bool:
    if inicio_nocturna > fin_nocturna:
        # Franja que pasa la medianoche (19:00 a 06:00).
        return minuto_del_dia >= inicio_nocturna or minuto_del_dia < fin_nocturna
    return inicio_nocturna <= minuto_del_dia < fin_nocturna


def dias_trabajados(dias_semana: list[int], descansa_dia_entre_semana: bool = False) -> list[int]:
    """Días que trabaja cada operario. Con descanso entre semana se quita un
    día de lunes a viernes (el miércoles, o el primero que haya): todos usan el
    horario general, así que cuál sea no cambia el cálculo, y el domingo se
    sigue trabajando."""
    dias = sorted(set(dias_semana))
    entre_semana = [d for d in dias if d <= 5]

    if not descansa_dia_entre_semana:
        return dias
    if not entre_semana:
        raise ValueError("No hay días entre semana para el descanso.")

    descanso = 3 if 3 in entre_semana else entre_semana[0]
    return [d for d in dias if d != descanso]


def calcular_horas_semana(
    dias_semana: list[int],
    horario_general: Horario,
    horario_sabado: Horario | None,
    hora_inicio_nocturna: time,
    hora_fin_nocturna: time,
    descansa_dia_entre_semana: bool = False,
) -> HorasSemana:
    """`dias_semana` en ISO (1 = lunes ... 7 = domingo). El sábado usa
    `horario_sabado` si se indica; los demás días, el general. Con
    `descansa_dia_entre_semana` cada operario trabaja un día menos (lunes a viernes)."""
    inicio_nocturna = _minutos(hora_inicio_nocturna)
    fin_nocturna = _minutos(hora_fin_nocturna)

    trabajados = nocturnos = dominicales = nocturnos_dominicales = 0

    for dia in dias_trabajados(dias_semana, descansa_dia_entre_semana):
        horario = horario_sabado if dia == SABADO and horario_sabado else horario_general
        duracion = duracion_minutos(horario)

        if horario.minutos_descanso >= duracion:
            raise ValueError("Los descansos no pueden sumar lo mismo o más que el turno.")

        descanso = minutos_en_descanso(horario)
        trabajados += duracion - len(descanso)
        inicio = (dia - 1) * MINUTOS_DIA + _minutos(horario.hora_inicio)

        # Minuto a minuto: a lo sumo 7 turnos de 24 h, sin casos especiales.
        for desplazamiento in range(duracion):
            if desplazamiento in descanso:
                continue
            en_semana = (inicio + desplazamiento) % MINUTOS_SEMANA
            nocturno = _es_nocturno(en_semana % MINUTOS_DIA, inicio_nocturna, fin_nocturna)
            dominical = en_semana // MINUTOS_DIA + 1 == DOMINGO
            nocturnos += nocturno
            dominicales += dominical
            nocturnos_dominicales += nocturno and dominical

    return HorasSemana(
        horas=round(trabajados / 60, 2),
        nocturnas=round(nocturnos / 60, 2),
        dominicales=round(dominicales / 60, 2),
        nocturnas_dominicales=round(nocturnos_dominicales / 60, 2),
    )
