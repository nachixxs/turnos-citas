"""Endpoint FastAPI del webhook de WhatsApp (CP3).

Este módulo solo cablea: no parsea el payload (eso es `webhook.py`), no decide
qué tool llamar (`agent.py`), no calcula disponibilidad (`availability.py`) y no
redacta el mensaje (`respuestas.py`). Su trabajo es el orden de los pasos y el
manejo de errores.

**El flujo de un mensaje:**

    parsear payload → leer turnos de la Sheet → decidir (Claude API)
    → aplicar contra el motor → persistir si se confirmó → componer el texto

**Siempre responde 200**, incluso ante un evento de estado o un payload roto. Un
4xx haría que n8n marque la ejecución como fallida y llene el historial de rojo
por notificaciones de "leído" que son perfectamente normales; Meta además
reintenta el envío ante cualquier respuesta que no sea 2xx. El campo `estado`
del body es lo que distingue un caso de otro, y es sobre lo que rutea el nodo IF
de n8n.

Levantarlo en local:

    .venv\\Scripts\\python.exe -m uvicorn app.main:app --reload --port 8000
"""

from __future__ import annotations

import logging
from functools import lru_cache
from typing import Any

import anthropic
from dotenv import load_dotenv
from fastapi import Depends, FastAPI, Request
from pydantic import BaseModel, ConfigDict, Field
from starlette.concurrency import run_in_threadpool

from app.agent import DecisionAgente, ResultadoAgente, aplicar_decision, cliente_anthropic, decidir
from app.availability import Turno
from app.config_loader import ConfigNegocio, cargar_config
from app.formato import formato_hora
from app.respuestas import (
    MENSAJE_ERROR_AL_GUARDAR,
    MENSAJE_ERROR_INTERNO,
    MENSAJE_TIPO_NO_SOPORTADO,
    componer_respuesta,
)
from app.sheets_client import SheetsClient
from app.webhook import MensajeEntrante, parsear_webhook

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="Turnos / Citas — webhook de WhatsApp",
    description="Endpoint que consume n8n para agendar turnos por WhatsApp con IA.",
)


# ── Dependencias ──────────────────────────────────────────────────────────
#
# Entran por `Depends` y no como globales para que los tests las reemplacen con
# `app.dependency_overrides` y corran sin credenciales ni red.


@lru_cache(maxsize=1)
def obtener_config() -> ConfigNegocio:
    """El JSON del negocio, cargado y validado una sola vez por proceso."""
    return cargar_config()


@lru_cache(maxsize=1)
def obtener_sheets() -> SheetsClient:
    """Cliente de Google Sheets. La worksheet se abre en el primer uso real."""
    return SheetsClient.desde_entorno()


@lru_cache(maxsize=1)
def obtener_cliente_ia() -> anthropic.Anthropic:
    return cliente_anthropic()


# ── Shape de la respuesta para n8n ────────────────────────────────────────


class DatosRespuesta(BaseModel):
    """Los datos estructurados del resultado, para el nodo IF de n8n y los logs.

    No hacen falta para mandar el mensaje —eso ya está resuelto en `respuesta`—
    pero permiten rutear por tipo de resultado sin parsear texto.
    """

    model_config = ConfigDict(extra="forbid")

    turno: Turno | None = None
    # "09:30", no "09:30:00": el mismo formato que ve el paciente y que se
    # escribe en la Sheet.
    alternativas: list[str] = Field(default_factory=list)
    tema: str | None = None


class RespuestaWebhook(BaseModel):
    """Lo que devuelve el endpoint, tal cual lo consume "Respond to Webhook".

    `respuesta` viene lista para enviarse al paciente: el texto se compone acá
    en Python, cubierto por pytest, y no con expresiones en la UI de n8n.

    `telefono` es a quién hay que mandarle ese texto. Va explícito porque
    responder 200 a Meta **no** envía un mensaje de WhatsApp: eso es un POST
    aparte a la Graph API, que arma n8n en CP4.
    """

    model_config = ConfigDict(extra="forbid")

    estado: str
    respuesta: str = ""
    telefono: str = ""
    datos: DatosRespuesta = Field(default_factory=DatosRespuesta)


def _ignorado(estado: str, detalle: str) -> RespuestaWebhook:
    """Respuesta para lo que no se procesa: sin texto y sin destinatario.

    n8n corta ahí: `respuesta` vacía significa que no hay nada que enviar.
    """
    logger.info("webhook ignorado (%s): %s", estado, detalle)
    return RespuestaWebhook(estado=estado)


def _respuesta_desde(
    resultado: ResultadoAgente,
    decision: DecisionAgente,
    mensaje: MensajeEntrante,
    config: ConfigNegocio,
) -> RespuestaWebhook:
    return RespuestaWebhook(
        estado=resultado.estado,
        respuesta=componer_respuesta(resultado, decision, config),
        telefono=mensaje.telefono,
        datos=DatosRespuesta(
            turno=resultado.turno,
            alternativas=[formato_hora(h) for h in resultado.alternativas],
            tema=resultado.tema,
        ),
    )


# ── Procesamiento de un mensaje ───────────────────────────────────────────


def procesar_mensaje(
    mensaje: MensajeEntrante,
    config: ConfigNegocio,
    sheets: SheetsClient,
    cliente_ia: anthropic.Anthropic,
) -> RespuestaWebhook:
    """El pipeline completo para un mensaje de texto ya parseado.

    Función aparte del handler HTTP a propósito: es sincrónica y bloqueante
    (red hacia Google y hacia la Claude API), así que el endpoint la corre en
    un threadpool en vez de trabar el event loop.
    """
    try:
        turnos = sheets.leer_turnos()
        decision = decidir(
            mensaje.texto, config, mensaje.nombre_perfil, cliente=cliente_ia
        )
        resultado = aplicar_decision(decision, mensaje.telefono, turnos, config)
    except Exception:
        # Cualquier fallo de red, de credenciales o de la API. Se loguea con
        # traceback y el paciente recibe un mensaje entendible, no un 500.
        logger.exception("fallo procesando el mensaje de %s", mensaje.telefono)
        return RespuestaWebhook(
            estado="error_interno",
            respuesta=MENSAJE_ERROR_INTERNO,
            telefono=mensaje.telefono,
        )

    if resultado.estado == "turno_confirmado" and resultado.turno is not None:
        try:
            sheets.guardar_turno(resultado.turno)
        except Exception:
            # No se le confirma un turno que no quedó guardado: sería peor que
            # decirle que falló, porque el paciente se presentaría al consultorio.
            logger.exception("el turno se validó pero no se pudo guardar en la Sheet")
            return RespuestaWebhook(
                estado="error_al_guardar",
                respuesta=MENSAJE_ERROR_AL_GUARDAR,
                telefono=mensaje.telefono,
            )

    return _respuesta_desde(resultado, decision, mensaje, config)


# ── Endpoint ──────────────────────────────────────────────────────────────


@app.post("/webhook", response_model=RespuestaWebhook)
async def recibir_webhook(
    request: Request,
    config: ConfigNegocio = Depends(obtener_config),
    sheets: SheetsClient = Depends(obtener_sheets),
    cliente_ia: anthropic.Anthropic = Depends(obtener_cliente_ia),
) -> RespuestaWebhook:
    """Recibe el payload de WhatsApp Cloud API y devuelve qué responder.

    El body se lee a mano en vez de declararlo como parámetro tipado porque
    FastAPI devolvería 422 ante un JSON roto, antes de llegar a este código, y
    acá todo tiene que salir 200 (ver el docstring del módulo).
    """
    try:
        body: Any = await request.json()
    except Exception:
        return _ignorado("payload_invalido", "el body no es JSON válido")

    evento = parsear_webhook(body)

    if evento.tipo == "estado":
        # El caso más frecuente en producción: "enviado", "entregado", "leído".
        # Se corta acá, sin llamar a la Claude API ni leer la Sheet.
        return _ignorado("ignorado_evento_estado", evento.detalle)

    if evento.tipo == "invalido" or evento.mensaje is None:
        return _ignorado("payload_invalido", evento.detalle)

    if evento.tipo == "no_soportado":
        # Audio, imagen, sticker: no se procesa, pero se le contesta al paciente
        # para que no le quede el mensaje sin respuesta.
        logger.info("mensaje '%s' no soportado", evento.mensaje.tipo_original)
        return RespuestaWebhook(
            estado="tipo_no_soportado",
            respuesta=MENSAJE_TIPO_NO_SOPORTADO,
            telefono=evento.mensaje.telefono,
        )

    return await run_in_threadpool(
        procesar_mensaje, evento.mensaje, config, sheets, cliente_ia
    )
