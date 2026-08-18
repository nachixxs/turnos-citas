"""Tests de la composición del mensaje al paciente (CP3).

Se verifica que el texto **contenga el dato concreto que corresponde** (el
nombre del servicio del config, la hora exacta, la dirección del config, los
horarios ofrecidos), nunca si la redacción "suena bien" — CODESTYLE, sección
Testing.

Los datos esperados salen del `ConfigNegocio` real del repo, no de literales
copiados a mano: si mañana cambia un precio en `config/negocio.json`, estos
tests siguen siendo válidos sin tocarlos.
"""

from __future__ import annotations

from datetime import date, time

from app.agent import TEMAS_FAQ, DecisionAgente, ResultadoAgente, mensaje_cancelacion
from app.availability import Turno
from app.config_loader import ConfigNegocio
from app.respuestas import (
    MENSAJE_NO_ENTENDIDO,
    componer_respuesta,
    respuesta_faq,
)
from tests.conftest import MIERCOLES, SABADO

TELEFONO = "5492615550199"


def _resultado_confirmado(servicio_id: str = "limpieza") -> ResultadoAgente:
    return ResultadoAgente(
        estado="turno_confirmado",
        turno=Turno(
            fecha=MIERCOLES,
            hora=time(10, 0),
            servicio_id=servicio_id,
            nombre_paciente="Ignacio",
            telefono=TELEFONO,
        ),
    )


# ── Turno confirmado ──────────────────────────────────────────────────────


def test_la_confirmacion_lleva_los_datos_exactos_del_turno(
    config: ConfigNegocio,
) -> None:
    """Lo que se le confirma al paciente tiene que ser lo que se guarda."""
    texto = componer_respuesta(_resultado_confirmado(), DecisionAgente(), config)

    assert "Ignacio" in texto
    assert "10:00" in texto
    assert "miércoles 19 de agosto" in texto
    assert config.negocio.direccion in texto


def test_la_confirmacion_usa_el_nombre_del_servicio_no_el_id(
    config: ConfigNegocio,
) -> None:
    texto = componer_respuesta(
        _resultado_confirmado("extraccion"), DecisionAgente(), config
    )
    servicio = config.servicio_por_id("extraccion")
    assert servicio is not None

    assert servicio.nombre in texto      # "Extracción"
    assert "extraccion" not in texto     # el id no se le muestra al paciente


def test_el_texto_del_modelo_no_pisa_la_confirmacion(config: ConfigNegocio) -> None:
    """Verificado en CP2: cuando el modelo llama a una tool no escribe texto. Si
    igual escribiera algo, la confirmación se compone acá y no de eso."""
    decision = DecisionAgente(
        tool="crear_turno", texto="Te lo agendo para el jueves a las 15."
    )
    texto = componer_respuesta(_resultado_confirmado(), decision, config)

    assert "jueves" not in texto
    assert "miércoles 19 de agosto" in texto


# ── Slot no disponible (SPECS §8) ─────────────────────────────────────────


def test_el_slot_ocupado_ofrece_las_alternativas_exactas(
    config: ConfigNegocio,
) -> None:
    resultado = ResultadoAgente(
        estado="slot_no_disponible",
        fecha=MIERCOLES,
        alternativas=[time(9, 30), time(10, 30), time(11, 0)],
    )
    texto = componer_respuesta(resultado, DecisionAgente(), config)

    for hora in ("09:30", "10:30", "11:00"):
        assert hora in texto
    assert "miércoles 19 de agosto" in texto


def test_sin_alternativas_no_se_ofrece_una_lista_vacia(
    config: ConfigNegocio,
) -> None:
    """Sábado: día cerrado, cero slots. No puede quedar 'tengo libre .'."""
    resultado = ResultadoAgente(
        estado="slot_no_disponible", fecha=SABADO, alternativas=[]
    )
    texto = componer_respuesta(resultado, DecisionAgente(), config)

    assert "tengo libre" not in texto
    assert "sábado 22 de agosto" in texto


def test_nunca_se_redondea_a_un_horario_solo(config: ConfigNegocio) -> None:
    """SPECS §8: se ofrecen opciones para elegir, no se elige por el paciente."""
    resultado = ResultadoAgente(
        estado="slot_no_disponible",
        fecha=MIERCOLES,
        alternativas=[time(9, 30), time(10, 30)],
    )
    texto = componer_respuesta(resultado, DecisionAgente(), config)

    assert "09:30" in texto and "10:30" in texto
    assert "?" in texto  # se le devuelve la decisión al paciente


# ── FAQ (SPECS §7) ────────────────────────────────────────────────────────


def test_los_cuatro_temas_del_faq_tienen_respuesta(config: ConfigNegocio) -> None:
    for tema in TEMAS_FAQ:
        texto = respuesta_faq(tema, config)  # type: ignore[arg-type]
        assert texto and texto != MENSAJE_NO_ENTENDIDO, tema


def test_el_faq_de_precios_lista_el_catalogo_del_config(
    config: ConfigNegocio,
) -> None:
    texto = respuesta_faq("precios", config)

    for servicio in config.servicios:
        assert servicio.nombre in texto
    assert "$32.000" in texto and "$110.000" in texto and "$160.000" in texto


def test_el_faq_de_horarios_sale_del_config(config: ConfigNegocio) -> None:
    texto = respuesta_faq("horarios", config)

    for rango in config.horario_atencion.lunes_a_viernes:
        assert f"{rango.inicio:%H:%M}" in texto
        assert f"{rango.fin:%H:%M}" in texto


def test_el_faq_de_direccion_sale_del_config(config: ConfigNegocio) -> None:
    assert config.negocio.direccion in respuesta_faq("direccion", config)


def test_el_faq_de_obra_social_respeta_el_flag_del_config(
    config: ConfigNegocio,
) -> None:
    """SPECS §4: el consultorio de la demo atiende solo particular."""
    assert config.negocio.atiende_obra_social is False
    assert "particular" in respuesta_faq("obra_social", config)

    con_obra_social = config.model_copy(deep=True)
    con_obra_social.negocio.atiende_obra_social = True
    assert "particular" not in respuesta_faq("obra_social", con_obra_social)


def test_el_faq_se_rutea_por_el_tema_del_resultado(config: ConfigNegocio) -> None:
    resultado = ResultadoAgente(estado="consulta_general", tema="direccion")
    texto = componer_respuesta(resultado, DecisionAgente(), config)

    assert texto == respuesta_faq("direccion", config)


# ── sin_tool: el único camino donde el texto lo escribe el modelo ─────────


def test_la_cancelacion_devuelve_el_texto_del_modelo_tal_cual(
    config: ConfigNegocio,
) -> None:
    """SPECS §9: el mensaje fijo con el teléfono del config, palabra por palabra."""
    fijo = mensaje_cancelacion(config)
    resultado = ResultadoAgente(estado="sin_tool")

    assert componer_respuesta(resultado, DecisionAgente(texto=fijo), config) == fijo
    assert config.negocio.telefono_contacto in fijo


def test_la_repregunta_devuelve_el_texto_del_modelo_tal_cual(
    config: ConfigNegocio,
) -> None:
    pregunta = "¿Para qué servicio querés el turno?"
    resultado = ResultadoAgente(estado="sin_tool")

    assert (
        componer_respuesta(resultado, DecisionAgente(texto=pregunta), config)
        == pregunta
    )


def test_sin_tool_y_sin_texto_no_deja_al_paciente_sin_respuesta(
    config: ConfigNegocio,
) -> None:
    resultado = ResultadoAgente(estado="sin_tool")
    assert componer_respuesta(resultado, DecisionAgente(), config) == MENSAJE_NO_ENTENDIDO


# ── Estados de error ──────────────────────────────────────────────────────


def test_el_servicio_invalido_ofrece_el_catalogo_del_config(
    config: ConfigNegocio,
) -> None:
    resultado = ResultadoAgente(estado="servicio_invalido", detalle="ortodoncia")
    texto = componer_respuesta(resultado, DecisionAgente(), config)

    for servicio in config.servicios:
        assert servicio.nombre in texto


def test_los_errores_internos_no_le_muestran_el_detalle_tecnico_al_paciente(
    config: ConfigNegocio,
) -> None:
    for estado in ("argumentos_invalidos", "tool_desconocida"):
        resultado = ResultadoAgente(
            estado=estado,  # type: ignore[arg-type]
            detalle="ValidationError: hora no es un time válido",
        )
        texto = componer_respuesta(resultado, DecisionAgente(), config)

        assert texto == MENSAJE_NO_ENTENDIDO
        assert "ValidationError" not in texto
