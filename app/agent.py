"""Agente Claude: decide qué tool llamar en cada mensaje (SPECS §3).

Dos capas separadas a propósito, igual que en CP1:

- **Decisión** — habla con la Claude API y devuelve qué tool eligió el modelo
  y con qué argumentos. Necesita API key y red.
- **Ejecución** — función pura que aplica esa decisión contra el motor de
  disponibilidad. Se testea sin credenciales ni red.

El prompt de sistema se arma en cada request con la fecha real del momento:
cachearlo haría que el bot resuelva "mañana" contra una fecha vieja.
"""

from __future__ import annotations

from datetime import date, datetime, time
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.config_loader import ConfigNegocio, RangoHorario

# `datetime.strftime('%A')` depende del locale del sistema y en Windows suele
# devolver inglés. Se mapea a mano para que el prompt sea siempre en español.
DIAS_SEMANA: list[str] = [
    "lunes",
    "martes",
    "miércoles",
    "jueves",
    "viernes",
    "sábado",
    "domingo",
]

# Mensaje fijo del camino de cancelación / reprogramación (SPECS §9). Es una
# plantilla y no un literal porque el teléfono cambia con cada cliente: el dato
# sale del JSON de configuración, nunca del código.
PLANTILLA_CANCELACION = (
    "Para cancelar o reprogramar un turno que ya tenés, escribí o llamá "
    "directamente al consultorio al {telefono}. Por acá solo puedo tomar "
    "turnos nuevos."
)


def mensaje_cancelacion(config: ConfigNegocio) -> str:
    """El texto exacto con el que el bot deriva una cancelación (SPECS §9).

    Los tests comparan la respuesta del modelo contra esta constante, no contra
    si el texto "suena bien" (CODESTYLE, sección Testing).
    """
    return PLANTILLA_CANCELACION.format(telefono=config.negocio.telefono_contacto)


def _formato_precio(precio: int) -> str:
    """32000 -> '$32.000' (separador de miles argentino)."""
    return f"${precio:,}".replace(",", ".")


def _formato_rango(rango: RangoHorario) -> str:
    return f"{rango.inicio:%H:%M} a {rango.fin:%H:%M}"


def _fecha_en_palabras(momento: datetime) -> str:
    """'miércoles 19 de agosto de 2026' — legible para el modelo y para un humano."""
    meses = [
        "enero", "febrero", "marzo", "abril", "mayo", "junio",
        "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre",
    ]
    dia_semana = DIAS_SEMANA[momento.weekday()]
    return (
        f"{dia_semana} {momento.day} de {meses[momento.month - 1]} "
        f"de {momento.year}"
    )


def _catalogo_de_servicios(config: ConfigNegocio) -> str:
    """Una línea por servicio, con el id exacto que espera la tool."""
    return "\n".join(
        f"- id `{s.id}`: {s.nombre}, {_formato_precio(s.precio)}"
        for s in config.servicios
    )


def construir_prompt_sistema(
    config: ConfigNegocio,
    nombre_perfil: str,
    ahora: datetime | None = None,
) -> str:
    """Prompt de sistema del agente, con la fecha real del momento.

    `ahora` se inyecta para poder testear con un reloj fijo; si no se pasa, se
    usa la hora actual del sistema. Nunca se cachea el resultado: un prompt con
    la fecha de ayer hace que el bot resuelva mal "mañana" o "el viernes".
    """
    momento = ahora if ahora is not None else datetime.now()
    negocio = config.negocio

    horarios = " y ".join(
        _formato_rango(r) for r in config.horario_atencion.lunes_a_viernes
    )
    obra_social = (
        "Trabaja con obras sociales."
        if negocio.atiende_obra_social
        else "Atiende solo de forma particular, no trabaja con obras sociales."
    )

    return f"""Sos el asistente de WhatsApp de {negocio.nombre}. Atendés a pacientes que escriben para sacar un turno o hacer consultas.

Hoy es {_fecha_en_palabras(momento)} ({momento:%Y-%m-%d}). Resolvé contra esta fecha cualquier expresión relativa ("mañana", "el viernes", "la semana que viene"). Nunca asumas otra fecha ni inventes el año.

DATOS DEL CONSULTORIO
- Dirección: {negocio.direccion}
- Atención: lunes a viernes, {horarios}
- Obra social: {obra_social}
- Teléfono de contacto: {negocio.telefono_contacto}

SERVICIOS
{_catalogo_de_servicios(config)}

Todos los turnos ocupan un bloque fijo de {config.duracion_slot_minutos} minutos, sin importar el servicio.

QUIÉN ESCRIBE
El nombre de perfil de WhatsApp de quien escribe es "{nombre_perfil}".

QUÉ HACER CON CADA MENSAJE
1. Si quiere sacar un turno nuevo, llamá a la tool `crear_turno`.
2. Si pregunta por horarios, dirección, precios u obra social, llamá a la tool `consulta_general`.
3. Si quiere cancelar o reprogramar un turno que ya tiene, NO llames a ninguna tool. Respondé con este texto exacto, palabra por palabra, sin agregar ni sacar nada:

{mensaje_cancelacion(config)}

4. Si quiere un turno pero falta algún dato (no dijo qué servicio, o no dijo fecha u hora), NO llames a ninguna tool: preguntá por el dato que falta y esperá la respuesta. Nunca inventes un servicio, una fecha ni un horario que el paciente no dijo.

Si no dice para quién es el turno, es para quien escribe. Si dice que es para otra persona, usá el nombre de esa persona: eso no es un dato faltante y no hace falta repreguntarlo.

CÓMO RESPONDER
Escribí en español rioplatense, breve y cordial, como un mensaje de WhatsApp. Sin encabezados, sin listas largas, sin markdown."""


# ── Tool: crear_turno (SPECS §6) ──────────────────────────────────────────


class ArgumentosCrearTurno(BaseModel):
    """Argumentos que el modelo extrae del mensaje para `crear_turno`.

    Que sea un modelo Pydantic y no un dict suelto es lo que convierte un
    argumento mal formado ("hora": "a la mañana") en un error explícito en vez
    de un `KeyError` tres capas más abajo.
    """

    model_config = ConfigDict(extra="forbid")

    fecha: date
    hora: time
    servicio: str = Field(min_length=1)
    nombre_paciente: str = Field(min_length=1)


def tool_crear_turno(config: ConfigNegocio) -> dict:
    """Definición de la tool `crear_turno`, con el catálogo real del negocio.

    El `enum` de servicios sale del JSON de configuración: si mañana el cliente
    agrega un servicio, la tool lo refleja sin tocar el código.
    """
    return {
        "name": "crear_turno",
        "description": (
            "Reserva un turno nuevo. Llamala solo cuando tengas los cuatro "
            "datos: fecha, hora, servicio y nombre del paciente. Si falta "
            "alguno, preguntá por el que falta en vez de llamar a la tool."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "fecha": {
                    "type": "string",
                    "description": (
                        "Fecha del turno en formato YYYY-MM-DD, resuelta contra "
                        "la fecha de hoy que figura en el prompt."
                    ),
                },
                "hora": {
                    "type": "string",
                    "description": (
                        "Hora de inicio en formato HH:MM de 24 horas, por "
                        "ejemplo 09:30 o 16:00."
                    ),
                },
                "servicio": {
                    "type": "string",
                    "enum": [s.id for s in config.servicios],
                    "description": "Id del servicio del catálogo.",
                },
                "nombre_paciente": {
                    "type": "string",
                    "description": (
                        "Nombre de la persona que se va a atender. Por defecto "
                        "el nombre de perfil de WhatsApp de quien escribe; si "
                        "el mensaje indica que el turno es para otra persona "
                        "(por ejemplo 'para mi hijo Tomás'), usá ese nombre."
                    ),
                },
            },
            "required": ["fecha", "hora", "servicio", "nombre_paciente"],
            "additionalProperties": False,
        },
        "strict": True,
    }


# ── Tool: consulta_general (SPECS §7) ─────────────────────────────────────

# Vocabulario cerrado a propósito: el FAQ del MVP cubre exactamente estos
# cuatro temas. Que sea un enum y no texto libre permite verificar en los tests
# qué se preguntó, sin evaluar la redacción de la respuesta.
TemaFAQ = Literal["horarios", "direccion", "precios", "obra_social"]
TEMAS_FAQ: tuple[str, ...] = ("horarios", "direccion", "precios", "obra_social")


class ArgumentosConsultaGeneral(BaseModel):
    """Argumentos que el modelo extrae del mensaje para `consulta_general`."""

    model_config = ConfigDict(extra="forbid")

    tema: TemaFAQ


def tool_consulta_general(config: ConfigNegocio) -> dict:
    """Definición de la tool `consulta_general` (FAQ).

    Recibe el config por consistencia con `tool_crear_turno` y porque el motor
    es genérico, aunque el esquema de esta tool no dependa del catálogo.
    """
    del config  # el esquema del FAQ es igual para cualquier negocio

    return {
        "name": "consulta_general",
        "description": (
            "Responde una consulta sobre el consultorio. Cubre solo estos "
            "temas: horarios y días de atención, dirección, precios de los "
            "servicios, y obra social o formas de pago. No la uses para "
            "urgencias ni para reservar, cancelar o reprogramar turnos."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "tema": {
                    "type": "string",
                    "enum": list(TEMAS_FAQ),
                    "description": "Tema del FAQ sobre el que pregunta el paciente.",
                },
            },
            "required": ["tema"],
            "additionalProperties": False,
        },
        "strict": True,
    }


def definir_tools(config: ConfigNegocio) -> list[dict]:
    """Las dos tools del agente, en orden fijo.

    El orden importa para el caché de prompts de la API: una lista que cambia
    de orden entre requests invalida el prefijo cacheado.
    """
    return [tool_crear_turno(config), tool_consulta_general(config)]
