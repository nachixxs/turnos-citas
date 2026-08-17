"""Tests del agente: ruteo de los 4 caminos de SPECS §3.

Todo lo de acá es puro: no toca la Claude API, no necesita ANTHROPIC_API_KEY y
no usa red. Se verifica qué tool se eligió y con qué argumentos exactos, nunca
el texto conversacional de la respuesta (CODESTYLE, sección Testing).

La verificación contra la API real vive en `scripts/verificar_agente.py`.
"""

from __future__ import annotations

from datetime import date, datetime, time
from typing import Any

from app.agent import (
    TEMAS_FAQ,
    ArgumentosCrearTurno,
    DecisionAgente,
    aplicar_decision,
    construir_prompt_sistema,
    definir_tools,
    extraer_decision,
    mensaje_cancelacion,
    tool_crear_turno,
)
from app.config_loader import ConfigNegocio
from tests.conftest import AHORA, MIERCOLES, turno

PERFIL = "Ignacio"
TELEFONO = "5492610000001"


class _Bloque:
    """Imita un bloque de contenido de la respuesta de la API.

    `extraer_decision` es duck-typed a propósito: así el parseo se testea sin
    depender del SDK ni de una respuesta real.
    """

    def __init__(self, **campos: Any) -> None:
        self.__dict__.update(campos)


def _decision_crear_turno(**overrides: Any) -> DecisionAgente:
    argumentos = {
        "fecha": "2026-08-19",
        "hora": "10:00",
        "servicio": "control",
        "nombre_paciente": PERFIL,
    }
    argumentos.update(overrides)
    return DecisionAgente(tool="crear_turno", argumentos=argumentos)


# ── Prompt de sistema: la fecha se recalcula, nunca se cachea ─────────────


def test_el_prompt_lleva_la_fecha_del_momento(config: ConfigNegocio) -> None:
    prompt = construir_prompt_sistema(config, PERFIL, ahora=datetime(2026, 8, 19, 9, 0))
    assert "2026-08-19" in prompt
    assert "miércoles 19 de agosto de 2026" in prompt


def test_dos_dias_distintos_dan_prompts_distintos(config: ConfigNegocio) -> None:
    hoy = construir_prompt_sistema(config, PERFIL, ahora=datetime(2026, 8, 19, 9, 0))
    manana = construir_prompt_sistema(config, PERFIL, ahora=datetime(2026, 8, 20, 9, 0))

    assert hoy != manana
    assert "2026-08-20" in manana and "2026-08-20" not in hoy


def test_el_prompt_lleva_los_datos_reales_del_config(config: ConfigNegocio) -> None:
    prompt = construir_prompt_sistema(config, PERFIL, ahora=AHORA)

    assert config.negocio.nombre in prompt
    assert config.negocio.direccion in prompt
    assert config.negocio.telefono_contacto in prompt
    assert PERFIL in prompt
    for servicio in config.servicios:
        assert servicio.id in prompt


def test_el_prompt_incluye_el_mensaje_fijo_de_cancelacion(config: ConfigNegocio) -> None:
    assert mensaje_cancelacion(config) in construir_prompt_sistema(
        config, PERFIL, ahora=AHORA
    )


def test_el_mensaje_de_cancelacion_usa_el_telefono_del_config(
    config: ConfigNegocio,
) -> None:
    assert config.negocio.telefono_contacto in mensaje_cancelacion(config)


# ── Definición de las tools ──────────────────────────────────────────────


def test_el_agente_define_exactamente_dos_tools(config: ConfigNegocio) -> None:
    assert [t["name"] for t in definir_tools(config)] == [
        "crear_turno",
        "consulta_general",
    ]


def test_el_enum_de_servicios_sale_del_catalogo(config: ConfigNegocio) -> None:
    esquema = tool_crear_turno(config)["input_schema"]
    assert esquema["properties"]["servicio"]["enum"] == [s.id for s in config.servicios]


def test_crear_turno_pide_los_cuatro_campos_de_specs_6(config: ConfigNegocio) -> None:
    esquema = tool_crear_turno(config)["input_schema"]
    assert set(esquema["required"]) == {"fecha", "hora", "servicio", "nombre_paciente"}


def test_crear_turno_no_le_pide_el_telefono_a_la_ia(config: ConfigNegocio) -> None:
    # SPECS §6: el teléfono llega resuelto del payload del webhook.
    esquema = tool_crear_turno(config)["input_schema"]
    assert "telefono" not in esquema["properties"]


def test_consulta_general_solo_cubre_los_temas_del_faq(config: ConfigNegocio) -> None:
    faq = definir_tools(config)[1]
    assert faq["input_schema"]["properties"]["tema"]["enum"] == list(TEMAS_FAQ)


# ── Parseo de la respuesta ───────────────────────────────────────────────


def test_se_extrae_la_tool_y_sus_argumentos() -> None:
    decision = extraer_decision(
        [
            _Bloque(type="thinking", thinking=""),
            _Bloque(type="text", text="Dale, te lo agendo. "),
            _Bloque(
                type="tool_use",
                name="crear_turno",
                input={"fecha": "2026-08-19", "hora": "10:00"},
            ),
        ]
    )

    assert decision.tool == "crear_turno"
    assert decision.argumentos == {"fecha": "2026-08-19", "hora": "10:00"}
    assert decision.texto == "Dale, te lo agendo."
    assert decision.llamo_a_una_tool is True


def test_una_respuesta_sin_tool_use_no_llama_a_ninguna_tool() -> None:
    decision = extraer_decision([_Bloque(type="text", text="¿Para qué servicio?")])

    assert decision.tool is None
    assert decision.argumentos == {}
    assert decision.llamo_a_una_tool is False


# ── Camino 1: crear turno ────────────────────────────────────────────────


def test_slot_libre_confirma_el_turno(config: ConfigNegocio) -> None:
    resultado = aplicar_decision(
        _decision_crear_turno(), TELEFONO, [], config, ahora=AHORA
    )

    assert resultado.estado == "turno_confirmado"
    assert resultado.turno is not None
    assert resultado.turno.fecha == MIERCOLES
    assert resultado.turno.hora == time(10, 0)
    assert resultado.turno.servicio_id == "control"


def test_el_telefono_sale_del_payload_y_no_de_la_ia(config: ConfigNegocio) -> None:
    resultado = aplicar_decision(
        _decision_crear_turno(), TELEFONO, [], config, ahora=AHORA
    )
    assert resultado.turno.telefono == TELEFONO


def test_un_telefono_extraido_por_la_ia_se_rechaza(config: ConfigNegocio) -> None:
    # Si el modelo inventa el campo, el esquema lo tiene que rebotar en vez de
    # dejar entrar un teléfono alucinado a la planilla.
    decision = _decision_crear_turno(telefono="5492619999999")
    assert (
        aplicar_decision(decision, TELEFONO, [], config, ahora=AHORA).estado
        == "argumentos_invalidos"
    )


def test_turno_para_otra_persona_usa_ese_nombre(config: ConfigNegocio) -> None:
    # SPECS §6: el default es el nombre de perfil, pero un nombre explícito
    # en los argumentos lo pisa.
    decision = _decision_crear_turno(nombre_paciente="Tomás")
    resultado = aplicar_decision(decision, TELEFONO, [], config, ahora=AHORA)

    assert resultado.turno.nombre_paciente == "Tomás"
    assert resultado.turno.nombre_paciente != PERFIL


def test_slot_ocupado_devuelve_alternativas(
    config: ConfigNegocio, turnos_del_miercoles: list
) -> None:
    # 11:30 está tomado en el escenario fijo; las tres libres más cercanas son
    # 10:30, 11:00 y 12:00 (mismo resultado que el test del motor en CP1).
    decision = _decision_crear_turno(hora="11:30")
    resultado = aplicar_decision(
        decision, TELEFONO, turnos_del_miercoles, config, ahora=AHORA
    )

    assert resultado.estado == "slot_no_disponible"
    assert resultado.turno is None
    assert resultado.alternativas == [time(10, 30), time(11, 0), time(12, 0)]


def test_hora_fuera_de_la_grilla_no_se_redondea(config: ConfigNegocio) -> None:
    # SPECS §8: 09:15 no se redondea a 09:00 ni a 09:30, se ofrecen opciones.
    resultado = aplicar_decision(
        _decision_crear_turno(hora="09:15"), TELEFONO, [], config, ahora=AHORA
    )

    assert resultado.estado == "slot_no_disponible"
    assert resultado.alternativas == [time(9, 0), time(9, 30), time(10, 0)]


def test_dia_cerrado_no_confirma_turno(config: ConfigNegocio) -> None:
    resultado = aplicar_decision(
        _decision_crear_turno(fecha="2026-08-22"), TELEFONO, [], config, ahora=AHORA
    )

    assert resultado.estado == "slot_no_disponible"
    assert resultado.alternativas == []


def test_servicio_fuera_del_catalogo_se_rechaza(config: ConfigNegocio) -> None:
    resultado = aplicar_decision(
        _decision_crear_turno(servicio="blanqueamiento"), TELEFONO, [], config, ahora=AHORA
    )

    assert resultado.estado == "servicio_invalido"
    assert resultado.turno is None


def test_hora_no_parseable_se_rechaza(config: ConfigNegocio) -> None:
    resultado = aplicar_decision(
        _decision_crear_turno(hora="a la mañana"), TELEFONO, [], config, ahora=AHORA
    )
    assert resultado.estado == "argumentos_invalidos"


def test_los_argumentos_se_parsean_a_tipos_reales() -> None:
    args = ArgumentosCrearTurno.model_validate(
        {
            "fecha": "2026-08-19",
            "hora": "10:30",
            "servicio": "limpieza",
            "nombre_paciente": "Ana",
        }
    )
    assert (args.fecha, args.hora) == (date(2026, 8, 19), time(10, 30))


# ── Camino 2: consulta general (FAQ) ─────────────────────────────────────


def test_consulta_general_devuelve_el_tema(config: ConfigNegocio) -> None:
    decision = DecisionAgente(tool="consulta_general", argumentos={"tema": "precios"})
    resultado = aplicar_decision(decision, TELEFONO, [], config, ahora=AHORA)

    assert resultado.estado == "consulta_general"
    assert resultado.tema == "precios"
    assert resultado.turno is None


def test_un_tema_fuera_del_faq_se_rechaza(config: ConfigNegocio) -> None:
    # "urgencias" está explícitamente fuera del FAQ (SPECS §7).
    decision = DecisionAgente(tool="consulta_general", argumentos={"tema": "urgencias"})
    assert (
        aplicar_decision(decision, TELEFONO, [], config, ahora=AHORA).estado
        == "argumentos_invalidos"
    )


# ── Caminos 3 y 4: cancelación y repregunta (ninguna tool) ───────────────


def test_sin_tool_no_toca_el_motor_de_turnos(config: ConfigNegocio) -> None:
    # Cubre los dos caminos que no disparan tool: cancelación (SPECS §9) y
    # repregunta por dato faltante.
    decision = DecisionAgente(tool=None, texto="¿Para qué servicio sería?")
    resultado = aplicar_decision(decision, TELEFONO, [], config, ahora=AHORA)

    assert resultado.estado == "sin_tool"
    assert resultado.turno is None
    assert resultado.alternativas == []


def test_una_tool_desconocida_no_rompe_el_proceso(config: ConfigNegocio) -> None:
    decision = DecisionAgente(tool="cancelar_turno", argumentos={})
    assert (
        aplicar_decision(decision, TELEFONO, [], config, ahora=AHORA).estado
        == "tool_desconocida"
    )


# ── El motor de CP1 sigue mandando ───────────────────────────────────────


def test_un_turno_ya_tomado_bloquea_el_mismo_horario(config: ConfigNegocio) -> None:
    tomados = [turno(MIERCOLES, time(10, 0))]
    resultado = aplicar_decision(
        _decision_crear_turno(hora="10:00"), TELEFONO, tomados, config, ahora=AHORA
    )
    assert resultado.estado == "slot_no_disponible"
