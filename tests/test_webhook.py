"""Tests del parseo del payload de WhatsApp (CP3).

Todo puro: no levanta el servidor, no toca la Claude API ni Google Sheets. Se
verifica contra la estructura del JSON y los datos concretos extraídos, nunca
contra el texto de una respuesta (CODESTYLE, sección Testing).

Los cuatro casos que Meta manda al mismo webhook tienen un test cada uno. El
caso que más aparece en la práctica no es el payload roto sino el **evento de
estado**: WhatsApp notifica "enviado", "entregado" y "leído" a la misma URL que
los mensajes reales, con un sobre idéntico salvo por la lista de adentro.
"""

from __future__ import annotations

from app.webhook import (
    NOMBRE_PERFIL_POR_DEFECTO,
    parsear_webhook,
)
from tests.conftest import PERFIL_PACIENTE, TELEFONO_PACIENTE, payload


# ── Caso 1: mensaje real de un paciente ───────────────────────────────────


def test_mensaje_de_texto_se_reconoce_como_mensaje() -> None:
    evento = parsear_webhook(payload("whatsapp_mensaje_texto"))

    assert evento.tipo == "mensaje"
    assert evento.mensaje is not None


def test_telefono_y_nombre_salen_del_payload_no_de_la_ia() -> None:
    """SPECS §6: los dos datos se resuelven del sobre de Meta, nunca extraídos."""
    evento = parsear_webhook(payload("whatsapp_mensaje_texto"))
    assert evento.mensaje is not None

    assert evento.mensaje.telefono == TELEFONO_PACIENTE
    assert evento.mensaje.nombre_perfil == PERFIL_PACIENTE


def test_el_texto_del_mensaje_se_extrae_completo() -> None:
    evento = parsear_webhook(payload("whatsapp_mensaje_texto"))
    assert evento.mensaje is not None

    assert evento.mensaje.texto == (
        "Hola, quiero sacar un turno para una limpieza el miércoles a las 10"
    )
    assert evento.mensaje.tipo_original == "text"
    assert evento.mensaje.message_id.startswith("wamid.")


def test_el_nombre_de_perfil_se_matchea_por_wa_id() -> None:
    """Con varios contactos, se toma el que coincide con quien escribió."""
    crudo = payload("whatsapp_mensaje_texto")
    contactos = crudo["entry"][0]["changes"][0]["value"]["contacts"]
    contactos.insert(0, {"profile": {"name": "Otra persona"}, "wa_id": "5492615550111"})

    evento = parsear_webhook(crudo)
    assert evento.mensaje is not None
    assert evento.mensaje.nombre_perfil == PERFIL_PACIENTE


def test_sin_nombre_de_perfil_cae_al_default() -> None:
    """WhatsApp permite ocultar el nombre de perfil; el bot no puede romperse."""
    crudo = payload("whatsapp_mensaje_texto")
    crudo["entry"][0]["changes"][0]["value"]["contacts"] = []

    evento = parsear_webhook(crudo)
    assert evento.mensaje is not None
    assert evento.mensaje.nombre_perfil == NOMBRE_PERFIL_POR_DEFECTO


def test_un_campo_nuevo_de_meta_no_rompe_el_parseo() -> None:
    """Meta agrega claves al sobre sin avisar: se ignoran, no explotan."""
    crudo = payload("whatsapp_mensaje_texto")
    crudo["entry"][0]["changes"][0]["value"]["campo_que_meta_invento"] = {"x": 1}
    crudo["entry"][0]["changes"][0]["value"]["messages"][0]["context"] = {"id": "wamid.X"}

    evento = parsear_webhook(crudo)
    assert evento.tipo == "mensaje"


def test_con_varios_mensajes_se_procesa_el_primero() -> None:
    """Meta puede batchear; un request HTTP devuelve una sola respuesta."""
    crudo = payload("whatsapp_mensaje_texto")
    mensajes = crudo["entry"][0]["changes"][0]["value"]["messages"]
    mensajes.append(
        {
            "from": TELEFONO_PACIENTE,
            "id": "wamid.SEGUNDO",
            "timestamp": "1755518401",
            "text": {"body": "segundo mensaje"},
            "type": "text",
        }
    )

    evento = parsear_webhook(crudo)
    assert evento.mensaje is not None
    assert evento.mensaje.message_id != "wamid.SEGUNDO"
    assert evento.mensaje.texto.startswith("Hola, quiero sacar un turno")


# ── Caso 2: evento de estado (entregado / leído) ──────────────────────────


def test_evento_de_estado_no_se_confunde_con_un_mensaje() -> None:
    """El caso que más aparece en producción: WhatsApp notifica 'entregado' y
    'leído' a la misma URL que los mensajes, con un sobre casi idéntico."""
    evento = parsear_webhook(payload("whatsapp_evento_estado"))

    assert evento.tipo == "estado"
    assert evento.mensaje is None


def test_el_field_no_alcanza_para_distinguir_estado_de_mensaje() -> None:
    """La trampa concreta: `changes[].field` vale 'messages' en los dos casos.
    Si el filtro se hiciera por ese campo, cada 'leído' llamaría a la API."""
    estado = payload("whatsapp_evento_estado")
    mensaje = payload("whatsapp_mensaje_texto")

    assert estado["entry"][0]["changes"][0]["field"] == "messages"
    assert mensaje["entry"][0]["changes"][0]["field"] == "messages"
    assert parsear_webhook(estado).tipo != parsear_webhook(mensaje).tipo


def test_los_tres_estados_de_whatsapp_se_ignoran_igual() -> None:
    for estado in ("sent", "delivered", "read"):
        crudo = payload("whatsapp_evento_estado")
        crudo["entry"][0]["changes"][0]["value"]["statuses"][0]["status"] = estado
        assert parsear_webhook(crudo).tipo == "estado", estado


# ── Caso 3: payload malformado ────────────────────────────────────────────


def test_payload_sin_messages_ni_statuses_es_invalido() -> None:
    evento = parsear_webhook(payload("whatsapp_payload_malformado"))

    assert evento.tipo == "invalido"
    assert evento.mensaje is None
    assert evento.detalle


def test_un_json_que_no_es_de_whatsapp_es_invalido() -> None:
    assert parsear_webhook({"hola": "mundo"}).tipo == "invalido"
    assert parsear_webhook({}).tipo == "invalido"


def test_un_body_que_no_es_objeto_es_invalido() -> None:
    """El body podría llegar como lista o como texto suelto: tampoco rompe."""
    assert parsear_webhook([1, 2, 3]).tipo == "invalido"
    assert parsear_webhook("no soy JSON de Meta").tipo == "invalido"
    assert parsear_webhook(None).tipo == "invalido"


def test_un_mensaje_sin_telefono_de_origen_es_invalido() -> None:
    """Sin `from` no hay a quién responderle ni qué guardar en la Sheet."""
    crudo = payload("whatsapp_mensaje_texto")
    del crudo["entry"][0]["changes"][0]["value"]["messages"][0]["from"]

    assert parsear_webhook(crudo).tipo == "invalido"


# ── Caso 4: mensaje que no es de texto ────────────────────────────────────


def test_un_audio_se_marca_no_soportado_pero_conserva_quien_escribio() -> None:
    """Hace falta el teléfono para poder contestarle que mande texto."""
    evento = parsear_webhook(payload("whatsapp_mensaje_audio"))

    assert evento.tipo == "no_soportado"
    assert evento.mensaje is not None
    assert evento.mensaje.telefono == TELEFONO_PACIENTE
    assert evento.mensaje.nombre_perfil == PERFIL_PACIENTE
    assert evento.mensaje.tipo_original == "audio"
    assert evento.mensaje.texto == ""


def test_un_texto_vacio_tambien_es_no_soportado() -> None:
    crudo = payload("whatsapp_mensaje_texto")
    crudo["entry"][0]["changes"][0]["value"]["messages"][0]["text"]["body"] = "   "

    assert parsear_webhook(crudo).tipo == "no_soportado"
