"""Fixtures compartidas de los tests.

Fechas ancla, elegidas para que el día de la semana sea explícito y no dependa
de cuándo se corran los tests:

    2026-08-19  miércoles  (día hábil)
    2026-08-22  sábado     (cerrado)
    2026-08-23  domingo    (cerrado)
"""

from __future__ import annotations

import json
from datetime import date, datetime, time, timedelta
from pathlib import Path

import pytest

from app.availability import DIAS_HABILES, Turno
from app.config_loader import ConfigNegocio, cargar_config

MIERCOLES = date(2026, 8, 19)
SABADO = date(2026, 8, 22)
DOMINGO = date(2026, 8, 23)

# Reloj fijo para todos los tests: un día antes de la fecha ancla, así el
# miércoles siempre cae en el futuro y ningún test depende del reloj real.
AHORA = datetime(2026, 8, 18, 10, 0)

# Grilla completa de un día hábil con el config del SPECS:
# 09:00–13:00 y 15:00–19:00 en slots de 30 min = 16 slots.
GRILLA_COMPLETA: list[time] = [
    time(9, 0), time(9, 30), time(10, 0), time(10, 30),
    time(11, 0), time(11, 30), time(12, 0), time(12, 30),
    time(15, 0), time(15, 30), time(16, 0), time(16, 30),
    time(17, 0), time(17, 30), time(18, 0), time(18, 30),
]


@pytest.fixture
def config() -> ConfigNegocio:
    """El config real del repo, no uno inventado: si `config/negocio.json` deja
    de validar, estos tests se enteran."""
    return cargar_config()


def turno(fecha: date, hora: time, servicio_id: str = "control") -> Turno:
    """Atajo para armar un turno tomado en los escenarios de test."""
    return Turno(
        fecha=fecha,
        hora=hora,
        servicio_id=servicio_id,
        nombre_paciente="Paciente de prueba",
        telefono="5492610000000",
    )


@pytest.fixture
def turnos_del_miercoles() -> list[Turno]:
    """Escenario fijo: tres turnos tomados el miércoles."""
    return [
        turno(MIERCOLES, time(9, 0)),
        turno(MIERCOLES, time(11, 30), servicio_id="limpieza"),
        turno(MIERCOLES, time(16, 0), servicio_id="extraccion"),
    ]


# ── Fixtures de payload de WhatsApp (CP3) ─────────────────────────────────

RUTA_FIXTURES = Path(__file__).parent / "fixtures"

# Datos de quien escribe en los fixtures de Meta. Ficticios, como todo el resto
# (CLAUDE.md del repo): no corresponden a ningún número real.
TELEFONO_PACIENTE = "5492615550199"
PERFIL_PACIENTE = "Ignacio"


def payload(nombre: str) -> dict:
    """Carga `tests/fixtures/<nombre>.json` como dict.

    Los fixtures son la estructura real de Meta, copiada tal cual: si Meta
    cambia el sobre, se cambia el JSON y no el código del test.
    """
    with (RUTA_FIXTURES / f"{nombre}.json").open(encoding="utf-8") as archivo:
        return json.load(archivo)


def proximo_dia_habil(dias_adelante: int = 7) -> date:
    """Un día hábil futuro respecto del reloj real del sistema.

    Los tests del endpoint corren el pipeline completo, que resuelve la
    disponibilidad contra `datetime.now()` — no hay reloj que inyectar desde
    afuera. Anclar a una fecha fija haría que estos tests empiecen a fallar solos
    el día que esa fecha quede en el pasado; esta función los deja siempre
    válidos sin volverlos no deterministas.
    """
    candidato = date.today() + timedelta(days=dias_adelante)
    while candidato.weekday() not in DIAS_HABILES:
        candidato += timedelta(days=1)
    return candidato
