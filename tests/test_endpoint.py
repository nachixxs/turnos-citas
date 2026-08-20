"""Tests del endpoint del webhook (CP3).

Corren el pipeline completo —parseo, decisión, motor de disponibilidad,
persistencia y composición del mensaje— con la red reemplazada por dobles: un
cliente de Claude que devuelve bloques fijos y una Sheet en memoria. No hace
falta ANTHROPIC_API_KEY ni credenciales de Google.

Se verifica el shape del JSON y los datos concretos que salieron del payload,
nunca si el texto de la respuesta "suena bien" (CODESTYLE, sección Testing).

El caso que más importa acá no es el payload roto sino el **evento de estado**:
hay un test que comprueba que un "entregado" no llegue a llamar a la Claude API
ni a leer la Sheet. Sin ese filtro, cada notificación de WhatsApp dispara una
llamada paga y el bot falla de forma intermitente.
"""

from __future__ import annotations

from datetime import date, time
from typing import Any, Iterator

import pytest
from fastapi.testclient import TestClient

from app.availability import Turno
from app.config_loader import ConfigNegocio
from app.main import app, obtener_cliente_ia, obtener_config, obtener_sheets
from app.respuestas import MENSAJE_ERROR_AL_GUARDAR, MENSAJE_TIPO_NO_SOPORTADO
from tests.conftest import (
    PERFIL_PACIENTE,
    TELEFONO_PACIENTE,
    payload,
    proximo_dia_habil,
)

HORA_PEDIDA = time(10, 0)


# ── Dobles de red ─────────────────────────────────────────────────────────


class _Bloque:
    """Imita un bloque de contenido de la respuesta de la API (mismo truco que
    en `test_agent_routing.py`: `extraer_decision` es duck-typed)."""

    def __init__(self, **campos: Any) -> None:
        self.__dict__.update(campos)


class _Respuesta:
    def __init__(self, bloques: list[_Bloque]) -> None:
        self.content = bloques


class _Mensajes:
    def __init__(self, cliente: ClienteIAFalso) -> None:
        self._cliente = cliente

    def create(self, **kwargs: Any) -> _Respuesta:
        self._cliente.llamadas.append(kwargs)
        return _Respuesta(self._cliente.bloques)


class ClienteIAFalso:
    """Reemplaza al cliente de anthropic. Registra si lo llamaron y cuántas veces."""

    def __init__(self, *bloques: _Bloque) -> None:
        self.bloques = list(bloques)
        self.llamadas: list[dict] = []
        self.messages = _Mensajes(self)


class SheetsFalso:
    """Sheet en memoria. Registra lecturas y escrituras para poder asertarlas."""

    def __init__(
        self,
        turnos: list[Turno] | None = None,
        error_lectura: Exception | None = None,
        error_escritura: Exception | None = None,
    ) -> None:
        self._turnos = list(turnos or [])
        self._error_lectura = error_lectura
        self._error_escritura = error_escritura
        self.lecturas = 0
        self.guardados: list[Turno] = []

    def leer_turnos(self) -> list[Turno]:
        self.lecturas += 1
        if self._error_lectura:
            raise self._error_lectura
        return list(self._turnos)

    def guardar_turno(self, turno: Turno) -> None:
        if self._error_escritura:
            raise self._error_escritura
        self.guardados.append(turno)


# ── Bloques de decisión listos para usar ──────────────────────────────────


def bloque_crear_turno(fecha: date, hora: time = HORA_PEDIDA, **overrides: Any) -> _Bloque:
    argumentos = {
        "fecha": fecha.isoformat(),
        "hora": f"{hora:%H:%M}",
        "servicio": "limpieza",
        "nombre_paciente": PERFIL_PACIENTE,
    }
    argumentos.update(overrides)
    return _Bloque(type="tool_use", name="crear_turno", input=argumentos)


def bloque_consulta(tema: str = "precios") -> _Bloque:
    return _Bloque(type="tool_use", name="consulta_general", input={"tema": tema})


def bloque_pedir_dato(*datos: str) -> _Bloque:
    return _Bloque(
        type="tool_use", name="pedir_dato_faltante", input={"datos": list(datos)}
    )


def bloque_texto(texto: str) -> _Bloque:
    return _Bloque(type="text", text=texto)


# ── Cliente de test ───────────────────────────────────────────────────────


@pytest.fixture
def montar(config: ConfigNegocio) -> Iterator[Any]:
    """Devuelve una función que arma el TestClient con los dobles elegidos.

    Las tres dependencias se pisan siempre, también el config: así ningún test
    depende del directorio desde el que se corra pytest ni de variables de
    entorno.
    """
    def _montar(cliente_ia: ClienteIAFalso, sheets: SheetsFalso) -> TestClient:
        app.dependency_overrides[obtener_config] = lambda: config
        app.dependency_overrides[obtener_sheets] = lambda: sheets
        app.dependency_overrides[obtener_cliente_ia] = lambda: cliente_ia
        return TestClient(app)

    yield _montar
    app.dependency_overrides.clear()


# ── Caso 1: mensaje real ──────────────────────────────────────────────────


def test_un_mensaje_real_confirma_el_turno_y_responde_200(montar: Any) -> None:
    fecha = proximo_dia_habil()
    ia = ClienteIAFalso(bloque_crear_turno(fecha))
    sheets = SheetsFalso()

    respuesta = montar(ia, sheets).post("/webhook", json=payload("whatsapp_mensaje_texto"))

    assert respuesta.status_code == 200
    assert respuesta.json()["estado"] == "turno_confirmado"


def test_la_respuesta_tiene_el_shape_que_espera_n8n(montar: Any) -> None:
    """El contrato con "Respond to Webhook": estas cuatro claves, siempre."""
    fecha = proximo_dia_habil()
    cuerpo = (
        montar(ClienteIAFalso(bloque_crear_turno(fecha)), SheetsFalso())
        .post("/webhook", json=payload("whatsapp_mensaje_texto"))
        .json()
    )

    assert set(cuerpo) == {"estado", "respuesta", "telefono", "datos"}
    assert set(cuerpo["datos"]) == {"turno", "alternativas", "tema"}
    assert isinstance(cuerpo["respuesta"], str) and cuerpo["respuesta"]
    assert cuerpo["telefono"] == TELEFONO_PACIENTE


def test_el_turno_se_persiste_en_la_sheet(montar: Any) -> None:
    fecha = proximo_dia_habil()
    sheets = SheetsFalso()

    montar(ClienteIAFalso(bloque_crear_turno(fecha)), sheets).post(
        "/webhook", json=payload("whatsapp_mensaje_texto")
    )

    assert len(sheets.guardados) == 1
    guardado = sheets.guardados[0]
    assert guardado.fecha == fecha
    assert guardado.hora == HORA_PEDIDA
    assert guardado.servicio_id == "limpieza"


def test_el_telefono_guardado_sale_del_payload_no_de_la_ia(montar: Any) -> None:
    """SPECS §6: el teléfono no es campo de la tool, llega resuelto del webhook."""
    fecha = proximo_dia_habil()
    ia = ClienteIAFalso(bloque_crear_turno(fecha))
    sheets = SheetsFalso()

    montar(ia, sheets).post("/webhook", json=payload("whatsapp_mensaje_texto"))

    assert sheets.guardados[0].telefono == TELEFONO_PACIENTE
    # Y la tool nunca recibió un teléfono que extraer.
    assert "telefono" not in ia.llamadas[0]["tools"][0]["input_schema"]["properties"]


def test_el_nombre_de_perfil_del_payload_llega_al_prompt(montar: Any) -> None:
    ia = ClienteIAFalso(bloque_crear_turno(proximo_dia_habil()))

    montar(ia, SheetsFalso()).post("/webhook", json=payload("whatsapp_mensaje_texto"))

    assert PERFIL_PACIENTE in ia.llamadas[0]["system"]


def test_el_texto_del_paciente_llega_al_modelo_sin_tocar(montar: Any) -> None:
    ia = ClienteIAFalso(bloque_crear_turno(proximo_dia_habil()))

    montar(ia, SheetsFalso()).post("/webhook", json=payload("whatsapp_mensaje_texto"))

    assert ia.llamadas[0]["messages"] == [
        {
            "role": "user",
            "content": (
                "Hola, quiero sacar un turno para una limpieza "
                "el miércoles a las 10"
            ),
        }
    ]


# ── Caso 2: evento de estado ──────────────────────────────────────────────


def test_un_evento_de_estado_responde_200_sin_procesar(montar: Any) -> None:
    ia = ClienteIAFalso()
    sheets = SheetsFalso()

    respuesta = montar(ia, sheets).post(
        "/webhook", json=payload("whatsapp_evento_estado")
    )

    assert respuesta.status_code == 200
    assert respuesta.json()["estado"] == "ignorado_evento_estado"


def test_un_evento_de_estado_no_llama_a_la_api_ni_lee_la_sheet(montar: Any) -> None:
    """La razón de ser del filtro: sin él, cada "entregado" y cada "leído"
    dispara una llamada paga a la Claude API y una lectura de la planilla."""
    ia = ClienteIAFalso()
    sheets = SheetsFalso()

    montar(ia, sheets).post("/webhook", json=payload("whatsapp_evento_estado"))

    assert ia.llamadas == []
    assert sheets.lecturas == 0
    assert sheets.guardados == []


def test_un_evento_de_estado_no_devuelve_nada_para_enviar(montar: Any) -> None:
    """`respuesta` vacía es la señal de que n8n no tiene que mandar mensaje."""
    cuerpo = (
        montar(ClienteIAFalso(), SheetsFalso())
        .post("/webhook", json=payload("whatsapp_evento_estado"))
        .json()
    )

    assert cuerpo["respuesta"] == ""
    assert cuerpo["telefono"] == ""


# ── Caso 3: payload malformado ────────────────────────────────────────────


def test_un_payload_malformado_responde_200_y_no_rompe(montar: Any) -> None:
    """DoD de CP3: manejo básico de payload malformado, sin tumbar el proceso."""
    ia = ClienteIAFalso()
    sheets = SheetsFalso()

    respuesta = montar(ia, sheets).post(
        "/webhook", json=payload("whatsapp_payload_malformado")
    )

    assert respuesta.status_code == 200
    assert respuesta.json()["estado"] == "payload_invalido"
    assert ia.llamadas == []
    assert sheets.lecturas == 0


def test_un_json_cualquiera_no_rompe_el_endpoint(montar: Any) -> None:
    cliente = montar(ClienteIAFalso(), SheetsFalso())

    for cuerpo in ({}, {"hola": "mundo"}, [1, 2, 3], "texto suelto"):
        respuesta = cliente.post("/webhook", json=cuerpo)
        assert respuesta.status_code == 200, cuerpo
        assert respuesta.json()["estado"] == "payload_invalido", cuerpo


def test_un_body_que_no_es_json_no_rompe_el_endpoint(montar: Any) -> None:
    """FastAPI devolvería 422 solo; por eso el body se lee a mano."""
    respuesta = montar(ClienteIAFalso(), SheetsFalso()).post(
        "/webhook",
        content=b"esto no es json {{{",
        headers={"Content-Type": "application/json"},
    )

    assert respuesta.status_code == 200
    assert respuesta.json()["estado"] == "payload_invalido"


# ── Caso 4: mensaje que no es de texto ────────────────────────────────────


def test_un_audio_recibe_una_respuesta_fija_sin_llamar_a_la_api(montar: Any) -> None:
    ia = ClienteIAFalso()
    sheets = SheetsFalso()

    cuerpo = (
        montar(ia, sheets)
        .post("/webhook", json=payload("whatsapp_mensaje_audio"))
        .json()
    )

    assert cuerpo["estado"] == "tipo_no_soportado"
    assert cuerpo["respuesta"] == MENSAJE_TIPO_NO_SOPORTADO
    assert cuerpo["telefono"] == TELEFONO_PACIENTE  # hay a quién contestarle
    assert ia.llamadas == []
    assert sheets.lecturas == 0


# ── Los otros caminos del agente (SPECS §3) ───────────────────────────────


def test_un_slot_ocupado_devuelve_alternativas_y_no_guarda_nada(
    montar: Any,
) -> None:
    """SPECS §8: nunca rechazar sin ofrecer opciones."""
    fecha = proximo_dia_habil()
    ocupado = Turno(
        fecha=fecha,
        hora=HORA_PEDIDA,
        servicio_id="control",
        nombre_paciente="Otro paciente",
        telefono="5492615550111",
    )
    sheets = SheetsFalso(turnos=[ocupado])

    cuerpo = (
        montar(ClienteIAFalso(bloque_crear_turno(fecha)), sheets)
        .post("/webhook", json=payload("whatsapp_mensaje_texto"))
        .json()
    )

    assert cuerpo["estado"] == "slot_no_disponible"
    assert cuerpo["datos"]["alternativas"]
    assert "10:00" not in cuerpo["datos"]["alternativas"]
    assert cuerpo["datos"]["turno"] is None
    assert sheets.guardados == []


def test_una_consulta_de_faq_devuelve_el_tema_extraido(montar: Any) -> None:
    sheets = SheetsFalso()

    cuerpo = (
        montar(ClienteIAFalso(bloque_consulta("precios")), sheets)
        .post("/webhook", json=payload("whatsapp_mensaje_texto"))
        .json()
    )

    assert cuerpo["estado"] == "consulta_general"
    assert cuerpo["datos"]["tema"] == "precios"
    assert sheets.guardados == []


def test_una_cancelacion_devuelve_el_texto_del_modelo(
    montar: Any, config: ConfigNegocio
) -> None:
    """SPECS §9: sin tool, mensaje fijo con el teléfono del config."""
    from app.agent import mensaje_cancelacion

    fijo = mensaje_cancelacion(config)
    sheets = SheetsFalso()

    cuerpo = (
        montar(ClienteIAFalso(bloque_texto(fijo)), sheets)
        .post("/webhook", json=payload("whatsapp_mensaje_texto"))
        .json()
    )

    assert cuerpo["estado"] == "sin_tool"
    assert cuerpo["respuesta"] == fijo
    assert sheets.guardados == []


def test_una_repregunta_no_menciona_ningun_horario(
    montar: Any, config: ConfigNegocio
) -> None:
    """El hallazgo abierto de CP4, verificado sobre el body que sale a n8n.

    El paciente pidió un horario (`HORA_PEDIDA`) sin decir el servicio. Lo que
    n8n manda por WhatsApp no puede nombrar ese horario: nadie leyó la Sheet
    para saber si está libre. Con la repregunta compuesta en `respuestas.py` eso
    no depende de cómo redacte el modelo — de hecho acá el modelo no redacta.
    """
    sheets = SheetsFalso()

    cuerpo = (
        montar(ClienteIAFalso(bloque_pedir_dato("servicio")), sheets)
        .post("/webhook", json=payload("whatsapp_mensaje_texto"))
        .json()
    )

    assert cuerpo["estado"] == "dato_faltante"
    assert f"{HORA_PEDIDA:%H:%M}" not in cuerpo["respuesta"]
    assert not any(c.isdigit() for c in cuerpo["respuesta"])
    assert cuerpo["datos"]["turno"] is None
    assert sheets.guardados == []


def test_una_repregunta_le_pregunta_por_el_dato_que_falta(
    montar: Any, config: ConfigNegocio
) -> None:
    cuerpo = (
        montar(ClienteIAFalso(bloque_pedir_dato("servicio")), SheetsFalso())
        .post("/webhook", json=payload("whatsapp_mensaje_texto"))
        .json()
    )

    for servicio in config.servicios:
        assert servicio.nombre in cuerpo["respuesta"]


def test_una_repregunta_ignora_lo_que_el_modelo_haya_escrito(montar: Any) -> None:
    """La red de contención del fix: aunque el modelo afirme disponibilidad, no sale.

    Este es literalmente el texto que el bot mandó en producción durante CP4.
    Ahora, si viene acompañado de la tool, el paciente no lo ve.
    """
    de_produccion = "¡Hola! Para el jueves 20 a las 11 tengo lugar 🙂 ¿Qué necesitás?"

    cuerpo = (
        montar(
            ClienteIAFalso(bloque_texto(de_produccion), bloque_pedir_dato("servicio")),
            SheetsFalso(),
        )
        .post("/webhook", json=payload("whatsapp_mensaje_texto"))
        .json()
    )

    assert cuerpo["respuesta"] != de_produccion
    assert "tengo lugar" not in cuerpo["respuesta"]


def test_un_servicio_fuera_del_catalogo_no_guarda_nada(montar: Any) -> None:
    fecha = proximo_dia_habil()
    sheets = SheetsFalso()

    cuerpo = (
        montar(
            ClienteIAFalso(bloque_crear_turno(fecha, servicio="ortodoncia")), sheets
        )
        .post("/webhook", json=payload("whatsapp_mensaje_texto"))
        .json()
    )

    assert cuerpo["estado"] == "servicio_invalido"
    assert sheets.guardados == []


# ── Fallos de infraestructura ─────────────────────────────────────────────


def test_si_falla_la_lectura_de_la_sheet_no_se_devuelve_un_500(montar: Any) -> None:
    sheets = SheetsFalso(error_lectura=RuntimeError("403 de Google"))

    respuesta = montar(
        ClienteIAFalso(bloque_crear_turno(proximo_dia_habil())), sheets
    ).post("/webhook", json=payload("whatsapp_mensaje_texto"))

    assert respuesta.status_code == 200
    assert respuesta.json()["estado"] == "error_interno"


def test_si_falla_la_api_de_claude_no_se_devuelve_un_500(montar: Any) -> None:
    class IAQueFalla(ClienteIAFalso):
        def __init__(self) -> None:
            super().__init__()
            self.messages = self  # type: ignore[assignment]

        def create(self, **kwargs: Any) -> Any:
            raise RuntimeError("529 overloaded")

    respuesta = montar(IAQueFalla(), SheetsFalso()).post(
        "/webhook", json=payload("whatsapp_mensaje_texto")
    )

    assert respuesta.status_code == 200
    assert respuesta.json()["estado"] == "error_interno"


def test_si_no_se_puede_guardar_no_se_confirma_el_turno(montar: Any) -> None:
    """Confirmar un turno que no quedó guardado es peor que avisar que falló:
    el paciente se presentaría al consultorio y no estaría en la agenda."""
    fecha = proximo_dia_habil()
    sheets = SheetsFalso(error_escritura=RuntimeError("cuota de la API agotada"))

    cuerpo = (
        montar(ClienteIAFalso(bloque_crear_turno(fecha)), sheets)
        .post("/webhook", json=payload("whatsapp_mensaje_texto"))
        .json()
    )

    assert cuerpo["estado"] == "error_al_guardar"
    assert cuerpo["respuesta"] == MENSAJE_ERROR_AL_GUARDAR
    assert "agend" not in cuerpo["respuesta"]
    assert sheets.guardados == []
