"""Tests del motor de disponibilidad (SPECS §8).

Todo se verifica contra listas de slots exactas, nunca contra "parece correcto"
(CODESTYLE, sección Testing).
"""

from __future__ import annotations

from datetime import date, datetime, time

from app.availability import (
    alternativas,
    es_dia_habil,
    esta_disponible,
    slots_del_dia,
    slots_disponibles,
)
from app.config_loader import ConfigNegocio
from tests.conftest import (
    AHORA,
    DOMINGO,
    GRILLA_COMPLETA,
    MIERCOLES,
    SABADO,
    turno,
)

# ── Grilla teórica ────────────────────────────────────────────────────────


def test_dia_habil_devuelve_la_grilla_completa(config: ConfigNegocio) -> None:
    assert slots_del_dia(MIERCOLES, config) == GRILLA_COMPLETA


def test_la_grilla_tiene_16_slots(config: ConfigNegocio) -> None:
    # 4 horas de mañana + 4 de tarde, en slots de 30 min.
    assert len(slots_del_dia(MIERCOLES, config)) == 16


def test_el_ultimo_slot_termina_antes_del_cierre(config: ConfigNegocio) -> None:
    # 18:30 + 30 min = 19:00 exacto. Un slot a las 19:00 se pasaría del cierre.
    grilla = slots_del_dia(MIERCOLES, config)
    assert grilla[-1] == time(18, 30)
    assert time(19, 0) not in grilla


def test_no_hay_slots_en_el_horario_de_almuerzo(config: ConfigNegocio) -> None:
    grilla = slots_del_dia(MIERCOLES, config)
    assert time(13, 0) not in grilla
    assert time(14, 0) not in grilla
    assert time(14, 30) not in grilla


# ── Días cerrados ─────────────────────────────────────────────────────────


def test_sabado_no_es_dia_habil() -> None:
    assert es_dia_habil(SABADO) is False


def test_domingo_no_es_dia_habil() -> None:
    assert es_dia_habil(DOMINGO) is False


def test_sabado_no_tiene_slots(config: ConfigNegocio) -> None:
    assert slots_del_dia(SABADO, config) == []
    assert slots_disponibles(SABADO, [], config, ahora=AHORA) == []


def test_domingo_no_tiene_slots(config: ConfigNegocio) -> None:
    assert slots_disponibles(DOMINGO, [], config, ahora=AHORA) == []


# ── Ocupación ─────────────────────────────────────────────────────────────


def test_los_turnos_tomados_se_excluyen(
    config: ConfigNegocio, turnos_del_miercoles: list
) -> None:
    libres = slots_disponibles(MIERCOLES, turnos_del_miercoles, config, ahora=AHORA)

    esperado = [s for s in GRILLA_COMPLETA
                if s not in {time(9, 0), time(11, 30), time(16, 0)}]
    assert libres == esperado
    assert len(libres) == 13


def test_un_turno_de_otro_dia_no_ocupa_este(config: ConfigNegocio) -> None:
    otro_dia = [turno(date(2026, 8, 20), time(9, 0))]
    assert slots_disponibles(MIERCOLES, otro_dia, config, ahora=AHORA) == GRILLA_COMPLETA


def test_dia_completamente_ocupado_no_deja_slots(config: ConfigNegocio) -> None:
    todos = [turno(MIERCOLES, hora) for hora in GRILLA_COMPLETA]
    assert slots_disponibles(MIERCOLES, todos, config, ahora=AHORA) == []


def test_sin_turnos_la_disponibilidad_es_la_grilla_completa(
    config: ConfigNegocio,
) -> None:
    assert slots_disponibles(MIERCOLES, [], config, ahora=AHORA) == GRILLA_COMPLETA


# ── Fechas pasadas y día en curso ─────────────────────────────────────────


def test_fecha_pasada_no_tiene_disponibilidad(config: ConfigNegocio) -> None:
    ayer = date(2026, 8, 17)  # lunes, día hábil, pero anterior a AHORA
    assert es_dia_habil(ayer) is True
    assert slots_disponibles(ayer, [], config, ahora=AHORA) == []


def test_en_el_dia_en_curso_los_slots_pasados_no_se_ofrecen(
    config: ConfigNegocio,
) -> None:
    # Son las 16:10 del propio miércoles: solo quedan 16:30 en adelante.
    media_tarde = datetime(2026, 8, 19, 16, 10)
    libres = slots_disponibles(MIERCOLES, [], config, ahora=media_tarde)

    assert libres == [time(16, 30), time(17, 0), time(17, 30), time(18, 0), time(18, 30)]


# ── esta_disponible ───────────────────────────────────────────────────────


def test_slot_libre_esta_disponible(config: ConfigNegocio) -> None:
    assert esta_disponible(MIERCOLES, time(10, 0), [], config, ahora=AHORA) is True


def test_slot_ocupado_no_esta_disponible(
    config: ConfigNegocio, turnos_del_miercoles: list
) -> None:
    assert esta_disponible(
        MIERCOLES, time(9, 0), turnos_del_miercoles, config, ahora=AHORA
    ) is False


def test_hora_que_no_calza_con_la_grilla_no_esta_disponible(
    config: ConfigNegocio,
) -> None:
    # 09:15 no existe en una grilla de 30 min: no se redondea a 09:00 ni a 09:30.
    assert esta_disponible(MIERCOLES, time(9, 15), [], config, ahora=AHORA) is False


def test_hora_fuera_del_horario_de_atencion_no_esta_disponible(
    config: ConfigNegocio,
) -> None:
    assert esta_disponible(MIERCOLES, time(8, 0), [], config, ahora=AHORA) is False
    assert esta_disponible(MIERCOLES, time(20, 0), [], config, ahora=AHORA) is False


# ── Alternativas (SPECS §8: nunca rechazar sin ofrecer opciones) ──────────


def test_alternativas_devuelve_los_slots_mas_cercanos(
    config: ConfigNegocio, turnos_del_miercoles: list
) -> None:
    # Pidió 11:30, que está ocupado. Los tres libres más cercanos son
    # 10:30, 11:00 y 12:00 (11:30 está tomado).
    assert alternativas(
        MIERCOLES, time(11, 30), turnos_del_miercoles, config, ahora=AHORA
    ) == [time(10, 30), time(11, 0), time(12, 0)]


def test_alternativas_respeta_el_limite(config: ConfigNegocio) -> None:
    assert len(alternativas(MIERCOLES, time(12, 0), [], config, limite=5, ahora=AHORA)) == 5


def test_alternativas_vienen_en_orden_cronologico(config: ConfigNegocio) -> None:
    resultado = alternativas(MIERCOLES, time(15, 0), [], config, ahora=AHORA)
    assert resultado == sorted(resultado)


def test_sin_disponibilidad_no_hay_alternativas(config: ConfigNegocio) -> None:
    todos = [turno(MIERCOLES, hora) for hora in GRILLA_COMPLETA]
    assert alternativas(MIERCOLES, time(10, 0), todos, config, ahora=AHORA) == []


def test_dia_cerrado_no_ofrece_alternativas(config: ConfigNegocio) -> None:
    assert alternativas(SABADO, time(10, 0), [], config, ahora=AHORA) == []
