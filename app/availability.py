"""Motor de disponibilidad: grilla fija de slots (SPECS §8).

Decisión de diseño: todo lo de este módulo es función pura. Recibe los turnos ya
leídos y devuelve slots — nunca habla con Google Sheets. Eso permite testear el
corazón del MVP sin red ni credenciales, y deja el I/O aislado en
`sheets_client.py`.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from typing import Sequence

from pydantic import BaseModel, ConfigDict, Field

from app.config_loader import ConfigNegocio, RangoHorario

# Lunes=0 … Viernes=4, según datetime.weekday(). El config del SPECS solo
# define la franja "lunes_a_viernes", así que sábado y domingo son días
# cerrados: devuelven cero slots, que no es un error sino la respuesta correcta.
DIAS_HABILES: frozenset[int] = frozenset({0, 1, 2, 3, 4})


class Turno(BaseModel):
    """Un turno ya tomado. Espeja las columnas de la Sheet."""

    model_config = ConfigDict(extra="forbid")

    fecha: date
    hora: time
    servicio_id: str = Field(min_length=1)
    nombre_paciente: str = Field(min_length=1)
    telefono: str = Field(min_length=1)
    creado_en: datetime | None = None


def es_dia_habil(fecha: date) -> bool:
    """True si el negocio atiende ese día de la semana."""
    return fecha.weekday() in DIAS_HABILES


def _slots_de_rango(rango: RangoHorario, duracion_minutos: int) -> list[time]:
    """Corta una franja en slots de duración fija.

    Un slot solo entra si termina dentro de la franja: con slots de 30 min,
    09:00–13:00 da hasta las 12:30, nunca un 13:00 que se pasaría del cierre.
    """
    paso = timedelta(minutes=duracion_minutos)
    # date.min es un ancla arbitraria: solo se usa para poder sumar timedeltas
    # a un `time`, que por sí solo no soporta aritmética.
    actual = datetime.combine(date.min, rango.inicio)
    cierre = datetime.combine(date.min, rango.fin)

    slots: list[time] = []
    while actual + paso <= cierre:
        slots.append(actual.time())
        actual += paso
    return slots


def slots_del_dia(fecha: date, config: ConfigNegocio) -> list[time]:
    """Grilla teórica del día, sin mirar qué está ocupado.

    Devuelve lista vacía si el negocio no atiende ese día.
    """
    if not es_dia_habil(fecha):
        return []

    slots: list[time] = []
    for rango in config.horario_atencion.lunes_a_viernes:
        slots.extend(_slots_de_rango(rango, config.duracion_slot_minutos))
    return sorted(slots)


def slots_ocupados(fecha: date, turnos: Sequence[Turno]) -> set[time]:
    """Horas ya tomadas en esa fecha, según los turnos recibidos."""
    return {t.hora for t in turnos if t.fecha == fecha}


def slots_disponibles(
    fecha: date,
    turnos: Sequence[Turno],
    config: ConfigNegocio,
    ahora: datetime | None = None,
) -> list[time]:
    """Slots libres de esa fecha, en orden cronológico.

    Devuelve lista vacía —nunca lanza— cuando el día está cerrado, la fecha ya
    pasó o no queda ningún hueco. Que no haya disponibilidad es una respuesta
    válida del dominio, no un error.

    `ahora` se inyecta para poder testear con un reloj fijo; si no se pasa, se
    usa la hora actual del sistema.
    """
    momento = ahora if ahora is not None else datetime.now()

    if fecha < momento.date():
        return []

    ocupados = slots_ocupados(fecha, turnos)
    libres = [s for s in slots_del_dia(fecha, config) if s not in ocupados]

    # En el día en curso, un slot que ya pasó no es reservable.
    if fecha == momento.date():
        libres = [s for s in libres if s > momento.time()]

    return libres


def esta_disponible(
    fecha: date,
    hora: time,
    turnos: Sequence[Turno],
    config: ConfigNegocio,
    ahora: datetime | None = None,
) -> bool:
    """True si ese horario exacto se puede reservar.

    False tanto si el slot está ocupado como si la hora no calza con la grilla
    (ej. 09:15 con slots de 30 min): en ambos casos el bot debe ofrecer
    alternativas en vez de redondear por su cuenta (SPECS §8).
    """
    return hora in slots_disponibles(fecha, turnos, config, ahora=ahora)


def alternativas(
    fecha: date,
    hora_pedida: time,
    turnos: Sequence[Turno],
    config: ConfigNegocio,
    limite: int = 3,
    ahora: datetime | None = None,
) -> list[time]:
    """Los `limite` slots libres más cercanos a la hora pedida, en orden
    cronológico. Es lo que el bot ofrece cuando el pedido no calza."""
    libres = slots_disponibles(fecha, turnos, config, ahora=ahora)
    if not libres:
        return []

    referencia = timedelta(hours=hora_pedida.hour, minutes=hora_pedida.minute)
    por_cercania = sorted(
        libres,
        key=lambda s: abs(timedelta(hours=s.hour, minutes=s.minute) - referencia),
    )
    return sorted(por_cercania[:limite])
