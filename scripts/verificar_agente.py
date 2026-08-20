"""Guion de verificación del agente contra la Claude API real (CP2 y CP5).

No es un test de pytest: necesita ANTHROPIC_API_KEY y red, así que lo corre la
persona en su propia terminal. Nunca imprime la API key.

Cada caso se verifica de forma estructural: qué tool se llamó (o ninguna) y con
qué argumentos exactos, más el estado que devuelve el motor de CP1. Nunca se
juzga si el texto conversacional "suena bien".

Los casos de CP5 agregan dos verificaciones sobre el texto que igual son
estructurales, porque ese texto ya no lo escribe el modelo sino el código:
comparación contra una constante importada (urgencia, cancelación) y ausencia de
literales tomados del propio mensaje del caso (repregunta).

La fecha se ancla a un miércoles fijo para que las expresiones relativas del
guion ("mañana", "el viernes") tengan una respuesta esperada determinista. La
fecha igual se calcula dentro del prompt en cada request, como en producción.

Uso:
    .venv\\Scripts\\python.exe scripts/verificar_agente.py
    .venv\\Scripts\\python.exe scripts/verificar_agente.py --caso 3
"""

from __future__ import annotations

import sys
from datetime import date, datetime, time
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from pydantic import BaseModel, ConfigDict, Field

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.agent import (  # noqa: E402
    DecisionAgente,
    aplicar_decision,
    cliente_anthropic,
    decidir,
    mensaje_cancelacion,
    mensaje_urgencia,
)
from app.availability import Turno  # noqa: E402
from app.config_loader import ConfigNegocio, cargar_config  # noqa: E402
from app.respuestas import componer_respuesta  # noqa: E402

OK = "[OK]"
DIFF = "[DIFF]"

# Miércoles 19 de agosto de 2026, 10:00. Ancla del guion: "mañana" es el
# jueves 20, "el viernes" es el 21.
ANCLA = datetime(2026, 8, 19, 10, 0)

PERFIL = "Ignacio"
TELEFONO = "5492610000001"

# Escenario de turnos ya tomados, en memoria: el guion no toca la Sheet real.
#
# El jueves 20 a las 11:00 está ocupado a propósito: es el slot exacto sobre el
# que el bot afirmó disponibilidad en producción durante CP4 (ESTADO.md,
# "Hallazgo abierto"). Con el slot tomado, esa afirmación pasa a ser
# demostrablemente falsa en vez de cierta por casualidad.
TURNOS_TOMADOS: list[Turno] = [
    Turno(
        fecha=date(2026, 8, 20),
        hora=time(11, 0),
        servicio_id="control",
        nombre_paciente="Paciente de prueba",
        telefono="5492610000000",
    ),
]


class Caso(BaseModel):
    """Un mensaje del guion, con lo que se espera estructuralmente de él."""

    model_config = ConfigDict(extra="forbid")

    descripcion: str
    mensaje: str
    tool_esperada: str | None
    argumentos_esperados: dict[str, Any] = Field(default_factory=dict)
    estado_esperado: str
    espera_mensaje_de_cancelacion: bool = False
    espera_mensaje_de_urgencia: bool = False
    # Tool que este caso nunca puede disparar, pase lo que pase. Se verifica
    # aparte de `tool_esperada` porque expresa otra cosa: no "qué debería hacer"
    # sino "qué sería un bug". Un servicio fuera del catálogo puede razonablemente
    # rutear a más de un lado, pero jamás a un turno con otro servicio.
    tool_prohibida: str | None = None
    # Literales que no pueden aparecer en el texto que se le manda al paciente,
    # derivados del propio mensaje del caso. No es una blocklist de frases: el
    # texto compuesto es determinista, así que esto verifica la cadena completa
    # —del mensaje al mensaje enviado— y no una redacción posible.
    respuesta_no_menciona: list[str] = Field(default_factory=list)


GUION: list[Caso] = [
    # ── Camino 1: crear turno ────────────────────────────────────────────
    Caso(
        descripcion="Turno completo (camino 1)",
        mensaje="Hola! Quería sacar un turno para una limpieza mañana a las 10.",
        tool_esperada="crear_turno",
        argumentos_esperados={
            "fecha": "2026-08-20",
            "hora": "10:00",
            "servicio": "limpieza",
            "nombre_paciente": PERFIL,
        },
        estado_esperado="turno_confirmado",
    ),
    Caso(
        descripcion="Turno para otra persona (camino 1, SPECS §6)",
        mensaje="Necesito un control para mi hijo Tomás el viernes a las 16.",
        tool_esperada="crear_turno",
        argumentos_esperados={
            "fecha": "2026-08-21",
            "hora": "16:00",
            "servicio": "control",
            "nombre_paciente": "Tomás",
        },
        estado_esperado="turno_confirmado",
    ),
    Caso(
        descripcion="Slot ya ocupado (camino 1, SPECS §8)",
        mensaje="Quiero un control mañana a las 11 de la mañana.",
        tool_esperada="crear_turno",
        argumentos_esperados={"fecha": "2026-08-20", "hora": "11:00"},
        estado_esperado="slot_no_disponible",
    ),
    Caso(
        descripcion="Horario que no calza con la grilla (camino 1, SPECS §8)",
        mensaje="Puede ser mañana 9 y cuarto para un control?",
        tool_esperada="crear_turno",
        argumentos_esperados={"fecha": "2026-08-20", "hora": "09:15"},
        estado_esperado="slot_no_disponible",
    ),
    # ── Camino 2: consulta general ───────────────────────────────────────
    Caso(
        descripcion="FAQ precios (camino 2)",
        mensaje="Cuánto sale una extracción?",
        tool_esperada="consulta_general",
        argumentos_esperados={"tema": "precios"},
        estado_esperado="consulta_general",
    ),
    Caso(
        descripcion="FAQ obra social (camino 2, SPECS §7)",
        mensaje="Atienden por obra social? Tengo OSDE.",
        tool_esperada="consulta_general",
        argumentos_esperados={"tema": "obra_social"},
        estado_esperado="consulta_general",
    ),
    Caso(
        descripcion="FAQ horarios (camino 2)",
        mensaje="A qué hora abren los martes?",
        tool_esperada="consulta_general",
        argumentos_esperados={"tema": "horarios"},
        estado_esperado="consulta_general",
    ),
    Caso(
        descripcion="FAQ dirección (camino 2)",
        mensaje="Dónde quedan?",
        tool_esperada="consulta_general",
        argumentos_esperados={"tema": "direccion"},
        estado_esperado="consulta_general",
    ),
    # ── Camino 3: cancelación / reprogramación ───────────────────────────
    Caso(
        descripcion="Cancelación (camino 3, SPECS §9)",
        mensaje="Necesito cancelar el turno que tengo mañana, no voy a poder ir.",
        tool_esperada=None,
        estado_esperado="sin_tool",
        espera_mensaje_de_cancelacion=True,
    ),
    Caso(
        descripcion="Reprogramación (camino 3, SPECS §9)",
        mensaje="Puedo pasar mi turno del jueves para la semana que viene?",
        tool_esperada=None,
        estado_esperado="sin_tool",
        espera_mensaje_de_cancelacion=True,
    ),
    # ── Camino 4: repregunta ─────────────────────────────────────────────
    Caso(
        descripcion="Falta el servicio (camino 4)",
        mensaje="Hola, quiero sacar un turno para mañana a las 12.",
        tool_esperada="pedir_dato_faltante",
        argumentos_esperados={"datos": ["servicio"]},
        estado_esperado="dato_faltante",
    ),
    Caso(
        descripcion="Falta fecha y horario (camino 4)",
        mensaje="Me gustaría hacerme una limpieza dental.",
        tool_esperada="pedir_dato_faltante",
        argumentos_esperados={"datos": ["fecha", "hora"]},
        estado_esperado="dato_faltante",
    ),
    Caso(
        # El mensaje real que reprodujo el hallazgo en producción durante CP4.
        # El jueves 20 a las 11:00 está ocupado en TURNOS_TOMADOS, así que
        # cualquier "tengo lugar" acá es demostrablemente falso. Lo que se
        # verifica es que el texto enviado ni siquiera nombre ese horario.
        descripcion="Repregunta sobre un slot ocupado (CP5, hallazgo abierto)",
        mensaje="quiero un turno el jueves a las 11",
        tool_esperada="pedir_dato_faltante",
        argumentos_esperados={"datos": ["servicio"]},
        estado_esperado="dato_faltante",
        respuesta_no_menciona=["11", "jueves", "20"],
    ),
    # ── Bordes de SPECS §7 y §8 (CP5) ────────────────────────────────────
    Caso(
        # El riesgo real no es un id inválido —el enum de la tool no lo deja
        # pasar— sino la sustitución silenciosa: que pida blanqueamiento y
        # termine con un turno de limpieza.
        descripcion="Servicio fuera del catálogo (CP5)",
        mensaje="Hola, quería hacerme un blanqueamiento dental mañana a las 10.",
        tool_esperada=None,
        estado_esperado="sin_tool",
        tool_prohibida="crear_turno",
    ),
    Caso(
        descripcion="Urgencia (CP5, fuera de alcance por SPECS §7)",
        mensaje="Me duele muchísimo una muela desde anoche, no aguanto más. Es una urgencia.",
        tool_esperada=None,
        estado_esperado="sin_tool",
        espera_mensaje_de_urgencia=True,
        tool_prohibida="crear_turno",
    ),
]


def _coincide(esperado: Any, obtenido: Any) -> bool:
    """Igualdad, salvo en listas: ahí compara sin importar el orden.

    `pedir_dato_faltante` devuelve qué datos faltan; que venga
    `["hora", "servicio"]` en vez de `["servicio", "hora"]` dice exactamente lo
    mismo y no tiene por qué marcar una diferencia.
    """
    if isinstance(esperado, list) and isinstance(obtenido, list):
        return sorted(map(str, esperado)) == sorted(map(str, obtenido))
    return esperado == obtenido


def _comparar_argumentos(esperados: dict, obtenidos: dict) -> list[str]:
    """Compara solo las claves esperadas; devuelve las diferencias."""
    return [
        f"{clave}: esperaba {valor!r}, vino {obtenidos.get(clave)!r}"
        for clave, valor in esperados.items()
        if not _coincide(valor, obtenidos.get(clave))
    ]


def _verificar(
    caso: Caso,
    decision: DecisionAgente,
    estado: str,
    respuesta: str,
    config: ConfigNegocio,
) -> list[str]:
    """Devuelve la lista de diferencias del caso. Vacía = pasó."""
    fallas: list[str] = []

    if decision.tool != caso.tool_esperada:
        fallas.append(
            f"tool: esperaba {caso.tool_esperada or 'ninguna'}, "
            f"vino {decision.tool or 'ninguna'}"
        )
    else:
        fallas.extend(_comparar_argumentos(caso.argumentos_esperados, decision.argumentos))

    if caso.tool_prohibida is not None and decision.tool == caso.tool_prohibida:
        fallas.append(f"llamó a una tool prohibida para este caso: {caso.tool_prohibida}")

    if estado != caso.estado_esperado:
        fallas.append(f"estado: esperaba {caso.estado_esperado}, vino {estado}")

    if caso.espera_mensaje_de_cancelacion and mensaje_cancelacion(config) not in respuesta:
        fallas.append("el texto no contiene el mensaje fijo de derivación")

    if caso.espera_mensaje_de_urgencia and mensaje_urgencia(config) not in respuesta:
        fallas.append("el texto no contiene el mensaje fijo de urgencia")

    for literal in caso.respuesta_no_menciona:
        if literal.lower() in respuesta.lower():
            fallas.append(f"la respuesta menciona {literal!r}, que no verificó")

    return fallas


def main() -> int:
    load_dotenv()
    config = cargar_config()

    seleccionado: int | None = None
    if "--caso" in sys.argv:
        seleccionado = int(sys.argv[sys.argv.index("--caso") + 1])

    print("=" * 70)
    print("Verificación del agente contra la Claude API — CP2 + bordes de CP5")
    print(f"Fecha anclada: {ANCLA:%A %Y-%m-%d %H:%M}  ·  perfil: {PERFIL}")
    print("=" * 70)

    try:
        cliente = cliente_anthropic()
    except RuntimeError as error:
        print(f"\n{DIFF} {error}")
        return 1

    casos = GUION if seleccionado is None else [GUION[seleccionado - 1]]
    con_fallas = 0

    for numero, caso in enumerate(casos, start=seleccionado or 1):
        print(f"\n{numero}. {caso.descripcion}")
        print(f'   mensaje: "{caso.mensaje}"')

        try:
            decision = decidir(caso.mensaje, config, PERFIL, cliente=cliente, ahora=ANCLA)
        except Exception as error:  # noqa: BLE001 — script manual, queremos ver todo
            print(f"   {DIFF} {type(error).__name__}: {error}")
            con_fallas += 1
            continue

        resultado = aplicar_decision(
            decision, TELEFONO, TURNOS_TOMADOS, config, ahora=ANCLA
        )

        # El texto que de verdad se le manda al paciente, no el que escribió el
        # modelo: en todos los caminos menos `sin_tool` lo compone el código.
        respuesta = componer_respuesta(resultado, decision, config)

        print(f"   tool:      {decision.tool or 'ninguna'}")
        print(f"   argumentos:{decision.argumentos or ' —'}")
        print(f"   estado:    {resultado.estado}")
        if resultado.alternativas:
            print(f"   alternativas: {[f'{h:%H:%M}' for h in resultado.alternativas]}")
        print(f"   se envía:  {respuesta[:160] or '—'}")

        fallas = _verificar(caso, decision, resultado.estado, respuesta, config)
        if fallas:
            con_fallas += 1
            for falla in fallas:
                print(f"   {DIFF} {falla}")
        else:
            print(f"   {OK} coincide con lo esperado")

    print("\n" + "=" * 70)
    print(f"{len(casos) - con_fallas}/{len(casos)} casos coincidieron con lo esperado.")
    print("=" * 70)
    return 1 if con_fallas else 0


if __name__ == "__main__":
    raise SystemExit(main())
