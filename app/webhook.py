"""Parseo del payload del webhook de WhatsApp Cloud API.

Función pura y sin dependencias de FastAPI: recibe el body ya deserializado y
devuelve un `EventoWebhook`. Eso permite testear los tres casos reales con
fixtures, sin levantar el servidor (CODESTYLE: "si una función mezcla extraer
datos del payload y decidir qué tool llamar, se separa").

**Meta manda tres cosas distintas al mismo webhook, y las tres son válidas:**

| Qué llega | Dónde se ve | Qué hacemos |
|---|---|---|
| Un mensaje del paciente | `value.messages[]` | se procesa |
| Notificación de entregado/leído | `value.statuses[]` | se ignora |
| Cualquier otra cosa | ninguno de los dos | se ignora |

La trampa: **`changes[].field` vale `"messages"` en los tres casos**, así que no
sirve para discriminar. La única forma confiable es mirar qué lista viene
poblada dentro de `value`. Un webhook que no filtre los eventos de estado llama
a la Claude API por cada "leído" y falla de forma intermitente — es un error
aprendido en un proyecto anterior de la agencia con WhatsApp Cloud API.

Los modelos de acá usan `extra="ignore"`, al revés que los de
`config_loader.py`, que usan `extra="forbid"`. Es deliberado: en el JSON de
configuración un typo tiene que explotar, pero el payload lo define Meta y le
agrega campos nuevos sin avisar. Un campo desconocido no puede tumbar el bot.
"""

from __future__ import annotations

import logging
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

logger = logging.getLogger(__name__)

# WhatsApp permite ocultar el nombre de perfil. SPECS §6 fija el default de
# `nombre_paciente` en el nombre de perfil, pero no dice qué hacer cuando ese
# nombre no viene: se usa esta constante y el agente igual puede repreguntarlo.
NOMBRE_PERFIL_POR_DEFECTO = "paciente"

TipoEvento = Literal[
    "mensaje",        # un mensaje de texto de un paciente: se procesa
    "estado",         # notificación de enviado/entregado/leído: se ignora
    "no_soportado",   # audio, imagen, sticker, ubicación: se sabe quién escribió
    "invalido",       # no es un payload de WhatsApp reconocible
]


# ── Modelos del sobre de Meta ─────────────────────────────────────────────


class _PayloadBase(BaseModel):
    """Base de los modelos del payload: tolera claves que no conocemos."""

    model_config = ConfigDict(extra="ignore")


class PerfilMeta(_PayloadBase):
    name: str = ""


class ContactoMeta(_PayloadBase):
    """Quién escribió. De acá sale el nombre de perfil, nunca de la IA (SPECS §6)."""

    wa_id: str = ""
    profile: PerfilMeta = Field(default_factory=PerfilMeta)


class TextoMeta(_PayloadBase):
    body: str = ""


class MensajeMeta(_PayloadBase):
    """Un mensaje entrante. `from` es palabra reservada en Python: entra por alias."""

    id: str = ""
    telefono: str = Field(default="", alias="from")
    timestamp: str = ""
    type: str = ""
    text: TextoMeta | None = None


class ValorCambio(_PayloadBase):
    """El `value` de un cambio. `messages` y `statuses` son mutuamente excluyentes
    en la práctica, pero el código no lo asume: mira `messages` primero."""

    messages: list[MensajeMeta] = Field(default_factory=list)
    statuses: list[dict] = Field(default_factory=list)
    contacts: list[ContactoMeta] = Field(default_factory=list)


class CambioMeta(_PayloadBase):
    value: ValorCambio = Field(default_factory=ValorCambio)
    field: str = ""


class EntradaMeta(_PayloadBase):
    id: str = ""
    changes: list[CambioMeta] = Field(default_factory=list)


class PayloadWhatsApp(_PayloadBase):
    object: str = ""
    entry: list[EntradaMeta] = Field(default_factory=list)


# ── Resultado del parseo ──────────────────────────────────────────────────


class MensajeEntrante(BaseModel):
    """Los datos que el resto del sistema necesita de un mensaje.

    `telefono` y `nombre_perfil` salen de acá y viajan hasta la Sheet sin pasar
    nunca por la extracción de la IA (SPECS §6).
    """

    model_config = ConfigDict(extra="forbid")

    telefono: str = Field(min_length=1)
    nombre_perfil: str = Field(min_length=1)
    texto: str = ""
    message_id: str = ""
    # "text", "audio", "image", "sticker"... Se guarda para poder loguear qué
    # tipo llegó cuando el evento es `no_soportado`.
    tipo_original: str = ""


class EventoWebhook(BaseModel):
    """Qué llegó al webhook. `mensaje` viene poblado en 'mensaje' y en
    'no_soportado'; en 'estado' e 'invalido' es None."""

    model_config = ConfigDict(extra="forbid")

    tipo: TipoEvento
    mensaje: MensajeEntrante | None = None
    detalle: str = ""


# ── Parseo ────────────────────────────────────────────────────────────────


def _nombre_de_perfil(contactos: list[ContactoMeta], telefono: str) -> str:
    """Nombre de perfil del contacto que coincide con el teléfono que escribió.

    Se matchea por `wa_id` y no se toma el primero a ciegas: un payload puede
    traer varios contactos y agarrar el equivocado le pondría a un turno el
    nombre de otra persona.
    """
    for contacto in contactos:
        if contacto.wa_id == telefono and contacto.profile.name.strip():
            return contacto.profile.name.strip()
    return NOMBRE_PERFIL_POR_DEFECTO


def _primer_cambio_con(payload: PayloadWhatsApp, campo: str) -> ValorCambio | None:
    """El primer `value` del payload que traiga poblada esa lista."""
    for entrada in payload.entry:
        for cambio in entrada.changes:
            if getattr(cambio.value, campo):
                return cambio.value
    return None


def parsear_webhook(body: object) -> EventoWebhook:
    """Clasifica el body del webhook en uno de los cuatro tipos de evento.

    Nunca lanza: un payload irreconocible devuelve `tipo='invalido'`, que el
    endpoint traduce en un 200 sin procesar (DoD de CP3, "no rompe el proceso").
    """
    if not isinstance(body, dict):
        return EventoWebhook(
            tipo="invalido",
            detalle=f"el body no es un objeto JSON: {type(body).__name__}",
        )

    try:
        payload = PayloadWhatsApp.model_validate(body)
    except ValidationError as error:
        return EventoWebhook(tipo="invalido", detalle=f"payload que no valida: {error}")

    valor = _primer_cambio_con(payload, "messages")

    if valor is None:
        # Sin mensajes: puede ser una notificación de estado, que es normal y
        # frecuente, o un payload que no reconocemos.
        if _primer_cambio_con(payload, "statuses") is not None:
            logger.info("evento de estado de WhatsApp ignorado")
            return EventoWebhook(tipo="estado", detalle="notificación de estado")
        return EventoWebhook(
            tipo="invalido", detalle="el payload no trae ni 'messages' ni 'statuses'"
        )

    if len(valor.messages) > 1:
        # Meta puede batchear. Un request HTTP devuelve una sola respuesta, así
        # que se procesa el primero y se deja constancia del resto.
        logger.warning(
            "llegaron %d mensajes en un payload; se procesa solo el primero",
            len(valor.messages),
        )

    mensaje = valor.messages[0]
    if not mensaje.telefono:
        return EventoWebhook(
            tipo="invalido", detalle="el mensaje no trae el teléfono de origen ('from')"
        )

    entrante = MensajeEntrante(
        telefono=mensaje.telefono,
        nombre_perfil=_nombre_de_perfil(valor.contacts, mensaje.telefono),
        texto=(mensaje.text.body.strip() if mensaje.text else ""),
        message_id=mensaje.id,
        tipo_original=mensaje.type,
    )

    if mensaje.type != "text" or not entrante.texto:
        logger.info("mensaje de tipo '%s' sin texto procesable", mensaje.type)
        return EventoWebhook(
            tipo="no_soportado",
            mensaje=entrante,
            detalle=f"tipo de mensaje sin texto: {mensaje.type!r}",
        )

    logger.info(
        "mensaje de texto recibido de %s (%s)",
        entrante.nombre_perfil,
        entrante.telefono,
    )
    return EventoWebhook(tipo="mensaje", mensaje=entrante)
