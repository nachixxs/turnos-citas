"""Guion de verificación del endpoint contra el servidor real (cierre de CP3).

No es un test de pytest: levanta tráfico HTTP real contra la app, que a su vez
llama a la Claude API y lee Google Sheets. Lo corre la persona en su terminal.
Nunca imprime credenciales.

Antes de correrlo, levantar el servidor en otra terminal:

    .venv\\Scripts\\python.exe -m uvicorn app.main:app --port 8000

Uso:

    .venv\\Scripts\\python.exe scripts/verificar_webhook.py
    .venv\\Scripts\\python.exe scripts/verificar_webhook.py --caso 3
    .venv\\Scripts\\python.exe scripts/verificar_webhook.py --con-turno

Por defecto **no escribe nada en la Sheet**: los casos que corren son los que se
resuelven sin crear un turno. `--con-turno` agrega el caso que sí reserva y deja
una fila real en la planilla — mismo criterio que `verificar_sheets.py --escribir`.

La verificación es estructural: se compara el `estado` que devuelve el endpoint
contra el esperado, y para los eventos ignorados se comprueba que no venga nada
para enviar. El texto de la respuesta se imprime para poder leerlo, pero no se
juzga si "suena bien".
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import httpx

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

OK = "[OK]"
DIFF = "[DIFF]"

URL_POR_DEFECTO = "http://127.0.0.1:8000/webhook"

# Los mismos fixtures que usan los tests: una sola fuente de verdad para la
# estructura del sobre de Meta.
RUTA_FIXTURES = RAIZ / "tests" / "fixtures"


def cargar_fixture(nombre: str) -> dict:
    with (RUTA_FIXTURES / f"{nombre}.json").open(encoding="utf-8") as archivo:
        return json.load(archivo)


def payload_con_texto(texto: str) -> dict:
    """El fixture de mensaje real, con otro cuerpo de texto."""
    crudo = cargar_fixture("whatsapp_mensaje_texto")
    crudo["entry"][0]["changes"][0]["value"]["messages"][0]["text"]["body"] = texto
    return crudo


def dia_habil_lejano(dias: int = 30) -> date:
    """Un día hábil bastante adelante, para que el slot esté libre en la Sheet real."""
    candidato = date.today() + timedelta(days=dias)
    while candidato.weekday() > 4:
        candidato += timedelta(days=1)
    return candidato


class Caso:
    def __init__(
        self,
        titulo: str,
        payload: dict,
        estado_esperado: str,
        espera_respuesta: bool = True,
    ) -> None:
        self.titulo = titulo
        self.payload = payload
        self.estado_esperado = estado_esperado
        self.espera_respuesta = espera_respuesta


def construir_casos(con_turno: bool) -> list[Caso]:
    fecha = dia_habil_lejano()
    legible = f"{fecha.day}/{fecha.month}"

    casos = [
        # Los tres casos del DoD, primero los que no gastan una llamada a la API.
        Caso(
            "Evento de estado (entregado) — se ignora sin llamar a la API",
            cargar_fixture("whatsapp_evento_estado"),
            "ignorado_evento_estado",
            espera_respuesta=False,
        ),
        Caso(
            "Payload malformado — no rompe el proceso",
            cargar_fixture("whatsapp_payload_malformado"),
            "payload_invalido",
            espera_respuesta=False,
        ),
        Caso(
            "Mensaje de audio — respuesta fija pidiendo texto",
            cargar_fixture("whatsapp_mensaje_audio"),
            "tipo_no_soportado",
        ),
        # A partir de acá se llama a la Claude API real, sin escribir en la Sheet.
        Caso(
            "FAQ de precios (SPECS §7)",
            payload_con_texto("hola, cuánto sale una limpieza?"),
            "consulta_general",
        ),
        Caso(
            "Cancelación — mensaje fijo, ninguna tool (SPECS §9)",
            payload_con_texto("necesito cancelar el turno que tengo mañana"),
            "sin_tool",
        ),
        Caso(
            "Repregunta — falta el servicio (SPECS §3.4)",
            payload_con_texto(f"quiero un turno el {legible} a las 10"),
            "sin_tool",
        ),
    ]

    if con_turno:
        casos.append(
            Caso(
                f"Turno real — ESCRIBE en la Sheet ({fecha.isoformat()} 10:00)",
                payload_con_texto(
                    f"hola, quiero un turno para una limpieza el {legible} a las 10"
                ),
                "turno_confirmado",
            )
        )

    return casos


def correr_caso(numero: int, caso: Caso, url: str) -> bool:
    print(f"\n{numero}. {caso.titulo}")

    try:
        respuesta = httpx.post(url, json=caso.payload, timeout=120.0)
    except httpx.ConnectError:
        print(f"  {DIFF} no hay servidor escuchando en {url}")
        print("       levantalo con: .venv\\Scripts\\python.exe -m uvicorn app.main:app --port 8000")
        return False

    if respuesta.status_code != 200:
        print(f"  {DIFF} status {respuesta.status_code}, se esperaba 200")
        print(f"       body: {respuesta.text[:300]}")
        return False

    cuerpo: dict[str, Any] = respuesta.json()
    estado = cuerpo.get("estado")
    texto = cuerpo.get("respuesta", "")

    print("  status  : 200")
    print(f"  estado  : {estado}   (esperado: {caso.estado_esperado})")
    print(f"  telefono: {cuerpo.get('telefono') or '(vacío)'}")
    print(f"  datos   : {json.dumps(cuerpo.get('datos', {}), ensure_ascii=False)}")
    print(f"  texto   : {texto or '(vacío)'}")

    if estado != caso.estado_esperado:
        # `slot_no_disponible` en el caso de turno real no es un bug del
        # endpoint: significa que ese horario ya está tomado en la Sheet.
        if caso.estado_esperado == "turno_confirmado" and estado == "slot_no_disponible":
            print(f"  {DIFF} el slot ya estaba ocupado en la Sheet; probá otra fecha")
            return False
        print(f"  {DIFF} estado distinto del esperado")
        return False

    if caso.espera_respuesta and not texto:
        print(f"  {DIFF} el caso esperaba un texto para enviarle al paciente")
        return False

    if not caso.espera_respuesta and (texto or cuerpo.get("telefono")):
        print(f"  {DIFF} un evento ignorado no debería devolver nada para enviar")
        return False

    print(f"  {OK}")
    return True


def main() -> int:
    # La consola de Windows usa cp1252 por defecto y acá se imprime texto que
    # viene del modelo, que puede traer cualquier caracter. Sin esto, un guion
    # que anda bien igual termina en UnicodeEncodeError al imprimir.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default=URL_POR_DEFECTO, help="URL del endpoint")
    parser.add_argument("--caso", type=int, help="correr un solo caso, por número")
    parser.add_argument(
        "--con-turno",
        action="store_true",
        help="agrega el caso que reserva de verdad y escribe una fila en la Sheet",
    )
    args = parser.parse_args()

    casos = construir_casos(args.con_turno)

    if args.caso is not None:
        if not 1 <= args.caso <= len(casos):
            print(f"caso fuera de rango: hay {len(casos)} casos")
            return 2
        casos = [casos[args.caso - 1]]
        numeros = [args.caso]
    else:
        numeros = list(range(1, len(casos) + 1))

    print(f"Verificando {args.url}")
    if not args.con_turno:
        print("(sin --con-turno: no se escribe nada en la Sheet)")

    resultados = [
        correr_caso(numero, caso, args.url) for numero, caso in zip(numeros, casos)
    ]

    print("\n" + "=" * 70)
    print(f"{sum(resultados)}/{len(resultados)} casos como se esperaba")
    return 0 if all(resultados) else 1


if __name__ == "__main__":
    raise SystemExit(main())
