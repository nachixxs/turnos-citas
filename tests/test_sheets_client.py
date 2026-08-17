"""Tests de conversión entre filas de la planilla y objetos `Turno`.

Solo cubre las funciones puras de `sheets_client`: nada de esto toca la red ni
necesita credenciales. La conexión real contra Google se verifica a mano al
cerrar CP1 (ver ROADMAP).
"""

from __future__ import annotations

from datetime import date, datetime, time

import pytest

from app.availability import Turno
from app.sheets_client import (
    COLUMNAS,
    _a_fecha,
    _a_hora,
    _a_timestamp,
    _fila_a_turno,
    _turno_a_fila,
)

FILA_VALIDA: dict = {
    "fecha": "2026-08-19",
    "hora": "09:30",
    "servicio_id": "limpieza",
    "nombre_paciente": "Tomás Aguirre",
    "telefono": "5492610000000",
    "creado_en": "2026-08-18 10:15:00",
}


# ── Fila → Turno ──────────────────────────────────────────────────────────


def test_fila_valida_se_convierte_en_turno() -> None:
    resultado = _fila_a_turno(FILA_VALIDA)

    assert resultado.fecha == date(2026, 8, 19)
    assert resultado.hora == time(9, 30)
    assert resultado.servicio_id == "limpieza"
    assert resultado.nombre_paciente == "Tomás Aguirre"
    assert resultado.telefono == "5492610000000"
    assert resultado.creado_en == datetime(2026, 8, 18, 10, 15)


def test_se_recortan_los_espacios_sobrantes() -> None:
    fila = {**FILA_VALIDA, "servicio_id": "  control  ", "nombre_paciente": " Ana "}
    resultado = _fila_a_turno(fila)

    assert resultado.servicio_id == "control"
    assert resultado.nombre_paciente == "Ana"


def test_creado_en_vacio_queda_en_none() -> None:
    assert _fila_a_turno({**FILA_VALIDA, "creado_en": ""}).creado_en is None


def test_creado_en_ilegible_no_descarta_el_turno() -> None:
    # El timestamp es metadato: si está roto se pierde, pero el turno vale.
    resultado = _fila_a_turno({**FILA_VALIDA, "creado_en": "ayer a la tarde"})

    assert resultado.creado_en is None
    assert resultado.fecha == date(2026, 8, 19)


def test_fecha_invalida_lanza_para_que_la_fila_se_saltee() -> None:
    with pytest.raises(ValueError):
        _fila_a_turno({**FILA_VALIDA, "fecha": "19/08/2026"})


def test_hora_invalida_lanza_para_que_la_fila_se_saltee() -> None:
    with pytest.raises(ValueError):
        _fila_a_turno({**FILA_VALIDA, "hora": "media mañana"})


# ── Turno → fila ──────────────────────────────────────────────────────────


def test_turno_se_serializa_en_el_orden_de_columnas() -> None:
    turno = Turno(
        fecha=date(2026, 8, 19),
        hora=time(15, 0),
        servicio_id="extraccion",
        nombre_paciente="Franco Díaz",
        telefono="5492619999999",
        creado_en=datetime(2026, 8, 18, 9, 5, 30),
    )

    assert _turno_a_fila(turno) == [
        "2026-08-19",
        "15:00",
        "extraccion",
        "Franco Díaz",
        "5492619999999",
        "2026-08-18 09:05:30",
    ]


def test_la_fila_serializada_tiene_una_celda_por_columna() -> None:
    turno = Turno(
        fecha=date(2026, 8, 19),
        hora=time(9, 0),
        servicio_id="control",
        nombre_paciente="Ana",
        telefono="549261",
    )
    assert len(_turno_a_fila(turno)) == len(COLUMNAS)


def test_ida_y_vuelta_conserva_los_datos() -> None:
    original = _fila_a_turno(FILA_VALIDA)
    devuelta = dict(zip(COLUMNAS, _turno_a_fila(original)))

    assert _fila_a_turno(devuelta) == original


# ── Conversores sueltos ───────────────────────────────────────────────────


def test_hora_acepta_los_dos_formatos_que_devuelve_sheets() -> None:
    # Según cómo se cargó la celda, Sheets devuelve "09:00" o "09:00:00".
    assert _a_hora("09:00") == time(9, 0)
    assert _a_hora("09:00:00") == time(9, 0)


def test_los_tipos_nativos_pasan_sin_reconvertirse() -> None:
    assert _a_fecha(date(2026, 8, 19)) == date(2026, 8, 19)
    assert _a_hora(time(9, 0)) == time(9, 0)
    assert _a_timestamp(datetime(2026, 8, 18, 10, 0)) == datetime(2026, 8, 18, 10, 0)
