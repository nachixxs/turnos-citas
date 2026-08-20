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

import logging
import os
from datetime import date, datetime, time
from typing import Any, Iterable, Literal, Sequence

import anthropic
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.availability import Turno, esta_disponible
from app.availability import alternativas as calcular_alternativas
from app.config_loader import ConfigNegocio
from app.formato import fecha_en_palabras, formato_precio, formato_rango

logger = logging.getLogger(__name__)

MODELO = "claude-opus-5"

# Tope duro de la respuesta (thinking + texto). Generoso a propósito: no es un
# objetivo, es un techo para que una respuesta no se corte por la mitad.
MAX_TOKENS = 16000

# El ruteo entre 4 caminos no necesita razonamiento profundo. Thinking queda
# ENCENDIDO igual (es el default en Opus 5): apagado, el modelo a veces emite la
# llamada a la tool como texto plano en vez de un bloque tool_use, el turno
# termina sin error y el turno nunca se crea.
EFFORT = "low"

# Mensaje fijo del camino de cancelación / reprogramación (SPECS §9). Es una
# plantilla y no un literal porque el teléfono cambia con cada cliente: el dato
# sale del JSON de configuración, nunca del código.
PLANTILLA_CANCELACION = (
    "Para cancelar o reprogramar un turno que ya tenés, escribí o llamá "
    "directamente al consultorio al {telefono}. Por acá solo puedo tomar "
    "turnos nuevos."
)


# Mensaje fijo del camino de urgencia (SPECS §7). Las urgencias están fuera del
# FAQ y fuera del alcance del MVP: no se ofrecen como opción ni se responden con
# información específica. Que el texto sea una plantilla y no prosa del modelo es
# lo que garantiza esa última parte — y es el peor lugar posible para improvisar,
# porque del otro lado hay alguien con dolor que necesita llegar a un humano.
PLANTILLA_URGENCIA = (
    "Una urgencia no la puedo resolver por acá. Llamá directamente al "
    "consultorio al {telefono} así te atienden lo antes posible."
)


def mensaje_urgencia(config: ConfigNegocio) -> str:
    """El texto exacto con el que el bot deriva una urgencia (SPECS §7).

    Mismo patrón que `mensaje_cancelacion`: el teléfono sale del JSON de
    configuración y los tests comparan contra esta constante.
    """
    return PLANTILLA_URGENCIA.format(telefono=config.negocio.telefono_contacto)


def mensaje_cancelacion(config: ConfigNegocio) -> str:
    """El texto exacto con el que el bot deriva una cancelación (SPECS §9).

    Los tests comparan la respuesta del modelo contra esta constante, no contra
    si el texto "suena bien" (CODESTYLE, sección Testing).
    """
    return PLANTILLA_CANCELACION.format(telefono=config.negocio.telefono_contacto)


def _catalogo_de_servicios(config: ConfigNegocio) -> str:
    """Una línea por servicio, con el id exacto que espera la tool."""
    return "\n".join(
        f"- id `{s.id}`: {s.nombre}, {formato_precio(s.precio)}"
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
        formato_rango(r) for r in config.horario_atencion.lunes_a_viernes
    )
    obra_social = (
        "Trabaja con obras sociales."
        if negocio.atiende_obra_social
        else "Atiende solo de forma particular, no trabaja con obras sociales."
    )

    return f"""Sos el asistente de WhatsApp de {negocio.nombre}. Atendés a pacientes que escriben para sacar un turno o hacer consultas.

Hoy es {fecha_en_palabras(momento)} ({momento:%Y-%m-%d}). Resolvé contra esta fecha cualquier expresión relativa ("mañana", "el viernes", "la semana que viene"). Nunca asumas otra fecha ni inventes el año.

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

4. Si quiere un turno pero falta algún dato (no dijo qué servicio, o no dijo qué día, o no dijo a qué hora), llamá a la tool `pedir_dato_faltante` con la lista de los datos que falten. No escribas texto en ese caso: la pregunta la arma el sistema. Nunca inventes un servicio, una fecha ni un horario que el paciente no dijo.

Si no dice para quién es el turno, es para quien escribe. Si dice que es para otra persona, usá el nombre de esa persona: eso no es un dato faltante y no hace falta repreguntarlo.

5. Si el mensaje plantea una urgencia (dolor fuerte, un golpe, sangrado, algo que no puede esperar), NO llames a ninguna tool y NO ofrezcas turnos, horarios ni ninguna indicación de qué hacer. Respondé con este texto exacto, palabra por palabra, sin agregar ni sacar nada:

{mensaje_urgencia(config)}

Esta regla tiene prioridad sobre las demás: si el mensaje mezcla una urgencia con un pedido de turno, se responde la urgencia.

QUÉ NO PODÉS SABER
No ves la agenda. La disponibilidad de un horario la verifica el sistema, y solo cuando llamás a `crear_turno` con los cuatro datos completos. Hasta entonces no sabés si ese horario está libre.

Por eso nunca digas ni des a entender que un horario está libre, disponible, reservado, anotado o confirmado si todavía no llamaste a `crear_turno`. Tampoco lo insinúes con un "perfecto", un "dale" ni un "buenísimo" antes de repreguntar: para el paciente eso significa que el horario ya es suyo.

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


# ── Tool: pedir_dato_faltante (camino 4, SPECS §3) ────────────────────────

# Vocabulario cerrado de lo que puede faltar para reservar. Los otros dos datos
# de `crear_turno` no entran acá: el teléfono llega del payload y el nombre del
# paciente tiene default (SPECS §6), así que nunca "faltan".
DatoFaltante = Literal["servicio", "fecha", "hora"]
DATOS_FALTANTES: tuple[str, ...] = ("servicio", "fecha", "hora")


class ArgumentosPedirDato(BaseModel):
    """Qué datos le faltan al modelo para poder llamar a `crear_turno`."""

    model_config = ConfigDict(extra="forbid")

    datos: list[DatoFaltante] = Field(min_length=1)


def tool_pedir_dato_faltante(config: ConfigNegocio) -> dict:
    """Definición de la tool con la que el modelo repregunta un dato faltante.

    **Por qué la repregunta es una tool y no texto libre.** Es el único camino
    donde el modelo habla de un horario que el sistema todavía no verificó, y
    ahí afirmaba disponibilidad que no tenía cómo saber (ver `ESTADO.md`,
    "Hallazgo abierto"). Convertirlo en una tool mueve el texto a
    `respuestas.py`, que compone la pregunta sin recibir la fecha ni la hora
    pedidas: no puede afirmar disponibilidad ni por accidente.
    """
    del config  # qué datos puede faltar no depende del catálogo del negocio

    return {
        "name": "pedir_dato_faltante",
        "description": (
            "Llamala cuando el paciente quiere un turno pero no dijo todos los "
            "datos que hacen falta para reservarlo. Pasá solo los que faltan. "
            "No la uses si ya tenés servicio, fecha y hora: en ese caso llamá "
            "a `crear_turno`."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "datos": {
                    "type": "array",
                    "items": {"type": "string", "enum": list(DATOS_FALTANTES)},
                    "minItems": 1,
                    "description": (
                        "Los datos que el paciente todavía no dijo. Nunca "
                        "incluyas uno que sí dijo."
                    ),
                },
            },
            "required": ["datos"],
            "additionalProperties": False,
        },
        "strict": True,
    }


def definir_tools(config: ConfigNegocio) -> list[dict]:
    """Las dos tools del agente, en orden fijo.

    El orden importa para el caché de prompts de la API: una lista que cambia
    de orden entre requests invalida el prefijo cacheado.
    """
    return [
        tool_crear_turno(config),
        tool_consulta_general(config),
        tool_pedir_dato_faltante(config),
    ]


# ── Decisión: qué tool eligió el modelo ───────────────────────────────────


class DecisionAgente(BaseModel):
    """Qué decidió el modelo para un mensaje: la tool, sus argumentos, el texto.

    `tool` en None es una decisión válida y frecuente, no un error: son los
    caminos de cancelación y de repregunta (SPECS §3).
    """

    model_config = ConfigDict(extra="forbid")

    tool: str | None = None
    argumentos: dict[str, Any] = Field(default_factory=dict)
    texto: str = ""

    @property
    def llamo_a_una_tool(self) -> bool:
        return self.tool is not None


def extraer_decision(bloques: Iterable[Any]) -> DecisionAgente:
    """Convierte los bloques de contenido de la respuesta en una `DecisionAgente`.

    Función pura y sin dependencias del SDK: recibe cualquier cosa con `.type`,
    así se puede testear el parseo sin red ni API key. Los bloques `thinking`
    se ignoran; nunca traen contenido en Opus 5.
    """
    tool: str | None = None
    argumentos: dict[str, Any] = {}
    partes: list[str] = []

    for bloque in bloques:
        tipo = getattr(bloque, "type", None)
        if tipo == "text":
            partes.append(bloque.text)
        elif tipo == "tool_use" and tool is None:
            # Solo la primera: la request desactiva el uso de tools en paralelo,
            # así que "qué tool se llamó" no es ambiguo.
            tool = bloque.name
            argumentos = dict(bloque.input)

    return DecisionAgente(tool=tool, argumentos=argumentos, texto="".join(partes).strip())


def cliente_anthropic() -> anthropic.Anthropic:
    """Construye el cliente leyendo `ANTHROPIC_API_KEY` del entorno.

    Falla ruidoso si falta, igual que `SheetsClient.desde_entorno`: es mejor
    que descubrirlo a mitad de una conversación real.
    """
    if not os.getenv("ANTHROPIC_API_KEY"):
        raise RuntimeError(
            "falta la variable de entorno ANTHROPIC_API_KEY. "
            "Copiá .env.example a .env y completala."
        )
    return anthropic.Anthropic()


def decidir(
    mensaje: str,
    config: ConfigNegocio,
    nombre_perfil: str,
    cliente: anthropic.Anthropic | None = None,
    ahora: datetime | None = None,
) -> DecisionAgente:
    """Una sola llamada a la API por mensaje: el modelo elige tool o ninguna.

    No hay loop agéntico ni ejecución de tools acá — eso lo hace
    `aplicar_decision`, que es puro. Esta función es la única que toca la red.
    """
    api = cliente if cliente is not None else cliente_anthropic()
    logger.info("mensaje recibido de '%s' (%d caracteres)", nombre_perfil, len(mensaje))

    respuesta = api.messages.create(
        model=MODELO,
        max_tokens=MAX_TOKENS,
        thinking={"type": "adaptive"},
        output_config={"effort": EFFORT},
        system=construir_prompt_sistema(config, nombre_perfil, ahora=ahora),
        tools=definir_tools(config),
        # Un mensaje, una decisión: sin tools en paralelo el ruteo es unívoco.
        tool_choice={"type": "auto", "disable_parallel_tool_use": True},
        messages=[{"role": "user", "content": mensaje}],
    )

    decision = extraer_decision(respuesta.content)
    logger.info("tool elegida: %s %s", decision.tool or "ninguna", decision.argumentos)
    return decision


# ── Ejecución: aplicar la decisión contra el motor de CP1 ─────────────────

EstadoResultado = Literal[
    "sin_tool",             # cancelación o urgencia: responde el texto del modelo
    "consulta_general",     # FAQ, con el tema extraído
    "dato_faltante",        # repregunta: falta algún dato para poder reservar
    "turno_confirmado",     # slot libre: queda un Turno listo para persistir
    "slot_no_disponible",   # ocupado o fuera de grilla: hay alternativas
    "servicio_invalido",    # el id no está en el catálogo del negocio
    "argumentos_invalidos",  # el modelo mandó algo que no parsea
    "tool_desconocida",     # defensivo: una tool que no definimos
]


class ResultadoAgente(BaseModel):
    """Qué hay que hacer después de aplicar la decisión del modelo.

    No persiste nada: devuelve el `Turno` listo y deja el guardado en la Sheet
    para quien la llame (CP3). Eso es lo que la mantiene pura y testeable sin
    red, igual que `availability.py`.
    """

    model_config = ConfigDict(extra="forbid")

    estado: EstadoResultado
    turno: Turno | None = None
    # Fecha pedida. Solo se puebla en `slot_no_disponible`: es el dato que le
    # falta a `alternativas` para poder decir "el miércoles 19 tengo libre...".
    # En `turno_confirmado` la fecha ya viaja adentro del `Turno`.
    fecha: date | None = None
    alternativas: list[time] = Field(default_factory=list)
    tema: TemaFAQ | None = None
    # Solo se puebla en `dato_faltante`. Deliberadamente NO viaja la fecha ni la
    # hora que el paciente pidió: quien compone la repregunta no las recibe, y
    # por eso no puede afirmar que ese horario esté libre.
    datos_faltantes: list[DatoFaltante] = Field(default_factory=list)
    detalle: str = ""


def aplicar_decision(
    decision: DecisionAgente,
    telefono: str,
    turnos: Sequence[Turno],
    config: ConfigNegocio,
    ahora: datetime | None = None,
) -> ResultadoAgente:
    """Aplica la decisión del modelo usando el motor de disponibilidad de CP1.

    Función pura: no habla con la API ni con Google Sheets. `telefono` llega
    resuelto del payload del webhook, nunca de la extracción de la IA (SPECS §6).
    """
    if decision.tool is None:
        return ResultadoAgente(estado="sin_tool")

    if decision.tool == "consulta_general":
        try:
            args_faq = ArgumentosConsultaGeneral.model_validate(decision.argumentos)
        except ValidationError as error:
            return ResultadoAgente(estado="argumentos_invalidos", detalle=str(error))
        return ResultadoAgente(estado="consulta_general", tema=args_faq.tema)

    if decision.tool == "pedir_dato_faltante":
        try:
            args_dato = ArgumentosPedirDato.model_validate(decision.argumentos)
        except ValidationError as error:
            return ResultadoAgente(estado="argumentos_invalidos", detalle=str(error))
        # Se deduplica conservando el orden: el modelo puede repetir un dato y
        # eso no es motivo para rechazar la repregunta.
        unicos = list(dict.fromkeys(args_dato.datos))
        return ResultadoAgente(estado="dato_faltante", datos_faltantes=unicos)

    if decision.tool != "crear_turno":
        return ResultadoAgente(
            estado="tool_desconocida", detalle=f"tool no definida: {decision.tool!r}"
        )

    try:
        args = ArgumentosCrearTurno.model_validate(decision.argumentos)
    except ValidationError as error:
        return ResultadoAgente(estado="argumentos_invalidos", detalle=str(error))

    if config.servicio_por_id(args.servicio) is None:
        return ResultadoAgente(
            estado="servicio_invalido", detalle=f"servicio inexistente: {args.servicio!r}"
        )

    if not esta_disponible(args.fecha, args.hora, turnos, config, ahora=ahora):
        # SPECS §8: nunca rechazar sin ofrecer opciones, nunca redondear solo.
        return ResultadoAgente(
            estado="slot_no_disponible",
            fecha=args.fecha,
            alternativas=calcular_alternativas(
                args.fecha, args.hora, turnos, config, ahora=ahora
            ),
            detalle=f"{args.fecha} {args.hora:%H:%M} no está disponible",
        )

    return ResultadoAgente(
        estado="turno_confirmado",
        turno=Turno(
            fecha=args.fecha,
            hora=args.hora,
            servicio_id=args.servicio,
            nombre_paciente=args.nombre_paciente,
            telefono=telefono,
        ),
    )
