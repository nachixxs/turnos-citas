"""Composición del mensaje que lee el paciente.

**Por qué este módulo existe.** Verificado contra la API real en CP2: cuando el
modelo llama a una tool, no escribe texto — la respuesta trae el bloque
`tool_use` y nada más. Así que el mensaje de un turno confirmado o de un slot
ocupado no puede venir del modelo: se compone acá, de forma determinista, desde
el `ResultadoAgente`.

Eso además es lo correcto para el dominio. Una confirmación de turno con fecha,
hora y servicio tiene que decir exactamente lo que quedó guardado en la Sheet;
no es algo que convenga dejar a la redacción del modelo mensaje a mensaje.

El único camino donde el texto sí sale del modelo es `sin_tool` — cancelación y
repregunta (SPECS §3), donde no hay ningún dato que confirmar.

Todo dato del negocio entra por `ConfigNegocio`: los literales de acá son
plantillas, nunca precios, horarios ni direcciones (CODESTYLE).
"""

from __future__ import annotations

from app.agent import DecisionAgente, ResultadoAgente, TemaFAQ
from app.config_loader import ConfigNegocio
from app.formato import (
    fecha_en_palabras,
    formato_hora,
    formato_precio,
    formato_rango,
    listar_horas,
)

# Mensajes que no dependen del negocio: valen igual para cualquier cliente del
# motor, así que no tienen por qué vivir en `config/negocio.json`.
MENSAJE_TIPO_NO_SOPORTADO = (
    "Por ahora solo puedo leer mensajes de texto. ¿Me lo escribís?"
)
MENSAJE_NO_ENTENDIDO = (
    "Perdón, no te entendí bien. ¿Me lo repetís?"
)
MENSAJE_ERROR_INTERNO = (
    "Perdón, tuve un problema para procesar tu mensaje. ¿Probás de nuevo en un rato?"
)
MENSAJE_ERROR_AL_GUARDAR = (
    "Perdón, no pude confirmar el turno por un problema del sistema. "
    "Probá de nuevo en un rato, así no te queda un turno a medias."
)


def _catalogo_en_texto(config: ConfigNegocio) -> str:
    """'Control ($32.000), Limpieza dental ($110.000) o Extracción ($160.000)'."""
    items = [f"{s.nombre} ({formato_precio(s.precio)})" for s in config.servicios]
    if len(items) == 1:
        return items[0]
    return f"{', '.join(items[:-1])} o {items[-1]}"


# ── FAQ (SPECS §7) ────────────────────────────────────────────────────────


def respuesta_faq(tema: TemaFAQ, config: ConfigNegocio) -> str:
    """Texto del FAQ para uno de los cuatro temas, armado desde el config.

    El vocabulario de temas es cerrado (`TemaFAQ`), el mismo enum que declara la
    tool `consulta_general`: los tests verifican que los cuatro temas tengan
    respuesta, sin juzgar su redacción.
    """
    negocio = config.negocio

    if tema == "horarios":
        rangos = " y de ".join(
            formato_rango(r) for r in config.horario_atencion.lunes_a_viernes
        )
        return f"Atendemos de lunes a viernes, de {rangos}."

    if tema == "direccion":
        return f"Estamos en {negocio.direccion}. Te esperamos."

    if tema == "precios":
        lineas = ", ".join(
            f"{s.nombre} {formato_precio(s.precio)}" for s in config.servicios
        )
        return f"Estos son los valores: {lineas}."

    if tema == "obra_social":
        if negocio.atiende_obra_social:
            return "Trabajamos con obras sociales, consultanos por tu plan."
        return (
            "Atendemos solo de forma particular, no trabajamos con obras sociales."
        )

    return MENSAJE_NO_ENTENDIDO


# ── Composición por estado del resultado ──────────────────────────────────


def _texto_turno_confirmado(resultado: ResultadoAgente, config: ConfigNegocio) -> str:
    turno = resultado.turno
    if turno is None:  # defensivo: `turno_confirmado` siempre lo trae
        return MENSAJE_ERROR_INTERNO

    servicio = config.servicio_por_id(turno.servicio_id)
    nombre_servicio = servicio.nombre if servicio else turno.servicio_id

    return (
        f"Listo, {turno.nombre_paciente}. Te agendé {nombre_servicio} para el "
        f"{fecha_en_palabras(turno.fecha, con_anio=False)} a las "
        f"{formato_hora(turno.hora)}. "
        f"Te esperamos en {config.negocio.direccion}."
    )


def _texto_slot_no_disponible(resultado: ResultadoAgente) -> str:
    cuando = (
        f"el {fecha_en_palabras(resultado.fecha, con_anio=False)}"
        if resultado.fecha
        else "ese día"
    )

    if not resultado.alternativas:
        return (
            f"No me queda ningún horario libre {cuando}. "
            "¿Querés que busquemos otro día?"
        )

    # SPECS §8: nunca rechazar sin ofrecer opciones, nunca redondear por su cuenta.
    return (
        f"Ese horario no está disponible. {cuando.capitalize()} tengo libre "
        f"{listar_horas(resultado.alternativas)}. ¿Cuál te sirve?"
    )


def componer_respuesta(
    resultado: ResultadoAgente,
    decision: DecisionAgente,
    config: ConfigNegocio,
) -> str:
    """El texto exacto que se le manda al paciente para este resultado.

    `decision` entra solo por el camino `sin_tool`, que es el único donde el
    texto lo escribe el modelo (cancelación y repregunta, SPECS §3).
    """
    estado = resultado.estado

    if estado == "sin_tool":
        return decision.texto.strip() or MENSAJE_NO_ENTENDIDO

    if estado == "consulta_general":
        if resultado.tema is None:  # defensivo
            return MENSAJE_NO_ENTENDIDO
        return respuesta_faq(resultado.tema, config)

    if estado == "turno_confirmado":
        return _texto_turno_confirmado(resultado, config)

    if estado == "slot_no_disponible":
        return _texto_slot_no_disponible(resultado)

    if estado == "servicio_invalido":
        return (
            f"Ese servicio no lo tengo en la lista. Atendemos "
            f"{_catalogo_en_texto(config)}. ¿Cuál necesitás?"
        )

    # `argumentos_invalidos` y `tool_desconocida`: el modelo devolvió algo que
    # no sabemos aplicar. No se le muestra el detalle técnico al paciente.
    return MENSAJE_NO_ENTENDIDO
