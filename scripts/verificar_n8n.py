"""Guion de verificación del flujo de n8n, sin Meta (CP4).

Corre el circuito completo —n8n → FastAPI → Claude API → Google Sheets → envío—
reemplazando **solo** a Meta por un doble local. Todo lo demás es real.

Por qué vale la pena: encontrar un error del workflow acá sale mucho más barato
que descubrirlo con Meta en el medio, donde cada intento fallido se mezcla con
tokens vencidos, URLs de ngrok que cambiaron y el enlace `subscribed_apps`.

Qué reemplaza el doble: levanta un servidor en `127.0.0.1:8099` que hace de
Graph API y **registra el POST que el workflow habría mandado a WhatsApp**. Eso
es lo que se verifica: que salga, a qué número y con qué texto exacto.

Preparación (el guion no la hace por vos, para que sepas qué está corriendo):

    # 1. FastAPI
    .venv\\Scripts\\python.exe -m uvicorn app.main:app --port 8000

    # 2. Workflow apuntando al doble, con valores de mentira para Meta
    $env:GRAPH_API_BASE="http://127.0.0.1:8099"
    $env:META_VERIFY_TOKEN="prueba-local"
    $env:WHATSAPP_PHONE_ID="000000000000000"
    $env:WHATSAPP_TOKEN="token-de-mentira"
    .venv\\Scripts\\python.exe scripts/configurar_n8n.py

    # 3. n8n, reiniciado DESPUES de importar
    n8n start

Uso:

    .venv\\Scripts\\python.exe scripts/verificar_n8n.py
    .venv\\Scripts\\python.exe scripts/verificar_n8n.py --caso 3

La verificación es estructural: se compara contra las constantes importadas del
propio código y contra los datos del `config/negocio.json`, nunca contra si el
texto "suena bien".
"""

from __future__ import annotations

import argparse
import json
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any

import httpx

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

from app.config_loader import cargar_config  # noqa: E402
from app.respuestas import MENSAJE_TIPO_NO_SOPORTADO, respuesta_faq  # noqa: E402

OK = "[OK]"
DIFF = "[DIFF]"

URL_N8N = "http://127.0.0.1:5678/webhook/turnos-citas"
PUERTO_DOBLE = 8099
VERIFY_TOKEN = "prueba-local"

RUTA_FIXTURES = RAIZ / "tests" / "fixtures"

# El `from` de los fixtures y cómo tiene que quedar después de que el workflow
# le saque el "9" — el formato que Meta acepta para números argentinos.
TELEFONO_FIXTURE = "5492615550199"
TELEFONO_ESPERADO = "542615550199"


# ── Doble de la Graph API ─────────────────────────────────────────────────


class DobleGraphAPI:
    """Servidor mínimo que hace de Meta y registra lo que le mandan."""

    def __init__(self, puerto: int = PUERTO_DOBLE) -> None:
        self.envios: list[dict[str, Any]] = []
        registro = self.envios

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self) -> None:  # noqa: N802
                largo = int(self.headers.get("Content-Length", 0))
                crudo = self.rfile.read(largo).decode("utf-8", errors="replace")
                try:
                    cuerpo = json.loads(crudo)
                except json.JSONDecodeError:
                    cuerpo = {"_crudo": crudo}

                registro.append({"path": self.path, "body": cuerpo})

                # Se responde con la forma real de Meta, para que el nodo de n8n
                # no marque la ejecución como fallida.
                respuesta = json.dumps(
                    {
                        "messaging_product": "whatsapp",
                        "messages": [{"id": "wamid.DOBLE_LOCAL"}],
                    }
                ).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(respuesta)))
                self.end_headers()
                self.wfile.write(respuesta)

            def log_message(self, *_args: Any) -> None:
                pass  # sin ruido en la salida del guion

        self._servidor = HTTPServer(("127.0.0.1", puerto), Handler)
        self._hilo = threading.Thread(target=self._servidor.serve_forever, daemon=True)

    def arrancar(self) -> None:
        self._hilo.start()

    def parar(self) -> None:
        self._servidor.shutdown()

    def limpiar(self) -> None:
        self.envios.clear()

    def esperar_envio(self, segundos: float) -> dict[str, Any] | None:
        """Espera hasta `segundos` a que llegue un envío. None si no llegó ninguno."""
        limite = time.monotonic() + segundos
        while time.monotonic() < limite:
            if self.envios:
                return self.envios[0]
            time.sleep(0.25)
        return None


# ── Espera de arranque ────────────────────────────────────────────────────


def esperar_webhook(segundos: float = 60.0) -> bool:
    """Espera a que n8n registre el webhook, no solo a que abra el puerto.

    El puerto 5678 acepta conexiones bastante antes de que los webhooks queden
    registrados: en el medio, la URL devuelve 404 aunque el workflow este
    publicado. Sin esta espera, el primer caso del guion falla siempre, y parece
    un problema del workflow cuando en realidad es del arranque.
    """
    limite = time.monotonic() + segundos
    while time.monotonic() < limite:
        try:
            sonda = httpx.get(
                URL_N8N,
                params={
                    "hub.mode": "subscribe",
                    "hub.verify_token": "sonda",
                    "hub.challenge": "0",
                },
                timeout=5.0,
            )
            if sonda.status_code != 404:
                return True
        except httpx.HTTPError:
            pass
        time.sleep(1.0)
    return False


# ── Fixtures ──────────────────────────────────────────────────────────────


def fixture(nombre: str) -> dict:
    with (RUTA_FIXTURES / f"{nombre}.json").open(encoding="utf-8") as archivo:
        return json.load(archivo)


def fixture_con_texto(texto: str) -> dict:
    crudo = fixture("whatsapp_mensaje_texto")
    crudo["entry"][0]["changes"][0]["value"]["messages"][0]["text"]["body"] = texto
    return crudo


# ── Casos ─────────────────────────────────────────────────────────────────


def caso_verificacion_ok() -> bool:
    """Meta valida la URL con un GET y espera el challenge en texto plano."""
    respuesta = httpx.get(
        URL_N8N,
        params={
            "hub.mode": "subscribe",
            "hub.verify_token": VERIFY_TOKEN,
            "hub.challenge": "1158201444",
        },
        timeout=30.0,
    )
    print(f"  status: {respuesta.status_code}   body: {respuesta.text[:60]!r}")

    if respuesta.status_code != 200:
        print(f"  {DIFF} se esperaba 200")
        return False
    if respuesta.text.strip() != "1158201444":
        print(f"  {DIFF} el challenge tiene que volver tal cual, sin comillas ni JSON")
        return False
    print(f"  {OK}")
    return True


def caso_verificacion_rechazada() -> bool:
    """Un token que no coincide no puede pasar: cualquiera podría registrar el webhook."""
    respuesta = httpx.get(
        URL_N8N,
        params={
            "hub.mode": "subscribe",
            "hub.verify_token": "token-incorrecto",
            "hub.challenge": "1158201444",
        },
        timeout=30.0,
    )
    print(f"  status: {respuesta.status_code}   body: {respuesta.text[:60]!r}")

    if respuesta.status_code == 200 and "1158201444" in respuesta.text:
        print(f"  {DIFF} devolvio el challenge con un token invalido")
        return False
    print(f"  {OK} rechazado")
    return True


def _postear(payload: dict) -> int:
    respuesta = httpx.post(URL_N8N, json=payload, timeout=30.0)
    return respuesta.status_code


def caso_sin_envio(doble: DobleGraphAPI, payload: dict, espera: float = 6.0) -> bool:
    """El workflow tiene que cortar sin mandarle nada a WhatsApp."""
    doble.limpiar()
    status = _postear(payload)
    print(f"  status del webhook: {status}")

    envio = doble.esperar_envio(espera)
    if envio is not None:
        print(f"  {DIFF} salio un envio que no deberia haber salido:")
        print(f"       {json.dumps(envio['body'], ensure_ascii=False)[:300]}")
        return False
    print(f"  {OK} ningun envio en {espera:.0f}s")
    return True


def caso_con_envio(
    doble: DobleGraphAPI,
    payload: dict,
    texto_esperado: str | None,
    espera: float = 120.0,
) -> bool:
    """Tiene que salir un envío, al número correcto y con el texto correcto."""
    doble.limpiar()
    status = _postear(payload)
    print(f"  status del webhook: {status}")

    envio = doble.esperar_envio(espera)
    if envio is None:
        print(f"  {DIFF} no salio ningun envio en {espera:.0f}s")
        return False

    cuerpo = envio["body"]
    print(f"  path : {envio['path']}")
    print(f"  to   : {cuerpo.get('to')}")
    print(f"  texto: {cuerpo.get('text', {}).get('body', '')}")

    todo_bien = True

    if cuerpo.get("messaging_product") != "whatsapp":
        print(f"  {DIFF} falta messaging_product=whatsapp")
        todo_bien = False

    # El "9" de los números argentinos: si no coincide exacto, Meta rechaza.
    if cuerpo.get("to") != TELEFONO_ESPERADO:
        print(f"  {DIFF} el numero tiene que quedar {TELEFONO_ESPERADO} (sin el 9)")
        todo_bien = False

    if texto_esperado is not None:
        real = cuerpo.get("text", {}).get("body", "")
        if real != texto_esperado:
            print(f"  {DIFF} el texto no coincide con la constante del codigo")
            print(f"       esperado: {texto_esperado!r}")
            todo_bien = False

    if todo_bien:
        print(f"  {OK}")
    return todo_bien


def construir_casos(doble: DobleGraphAPI) -> list[tuple[str, Any]]:
    config = cargar_config()

    return [
        (
            "Verificacion de Meta (GET) con el token correcto",
            caso_verificacion_ok,
        ),
        (
            "Verificacion de Meta (GET) con un token invalido",
            caso_verificacion_rechazada,
        ),
        (
            "Evento de estado (entregado) - no debe salir ningun envio",
            lambda: caso_sin_envio(doble, fixture("whatsapp_evento_estado")),
        ),
        (
            "Payload malformado - no debe salir ningun envio",
            lambda: caso_sin_envio(doble, fixture("whatsapp_payload_malformado")),
        ),
        (
            "Mensaje de audio - respuesta fija, sin llamar a Claude",
            lambda: caso_con_envio(
                doble, fixture("whatsapp_mensaje_audio"), MENSAJE_TIPO_NO_SOPORTADO, 30.0
            ),
        ),
        (
            "FAQ de precios - circuito completo con Claude real",
            lambda: caso_con_envio(
                doble,
                fixture_con_texto("hola, cuanto sale una limpieza?"),
                respuesta_faq("precios", config),
            ),
        ),
    ]


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--caso", type=int, help="correr un solo caso, por numero")
    args = parser.parse_args()

    print("=" * 70)
    print("Verificacion del flujo de n8n sin Meta - CP4")
    print("=" * 70)

    try:
        httpx.get("http://127.0.0.1:8000/openapi.json", timeout=5.0)
    except Exception:
        print(f"\n{DIFF} FastAPI no responde en 127.0.0.1:8000")
        print("    levantalo con: .venv\\Scripts\\python.exe -m uvicorn app.main:app --port 8000")
        return 2

    print("\nEsperando a que n8n registre el webhook...")
    if not esperar_webhook():
        print(f"{DIFF} el webhook sigue devolviendo 404 en {URL_N8N}")
        print("    revisa que n8n este corriendo, que el workflow este PUBLICADO")
        print("    y que lo hayas reiniciado despues de importarlo")
        return 2
    print(f"{OK} webhook registrado")

    doble = DobleGraphAPI()
    doble.arrancar()
    print(f"Doble de la Graph API escuchando en 127.0.0.1:{PUERTO_DOBLE}")

    try:
        casos = construir_casos(doble)

        if args.caso is not None:
            if not 1 <= args.caso <= len(casos):
                print(f"caso fuera de rango: hay {len(casos)} casos")
                return 2
            seleccion = [(args.caso, *casos[args.caso - 1])]
        else:
            seleccion = [(i, t, f) for i, (t, f) in enumerate(casos, start=1)]

        resultados = []
        for numero, titulo, correr in seleccion:
            print(f"\n{numero}. {titulo}")
            try:
                resultados.append(correr())
            except httpx.ConnectError:
                print(f"  {DIFF} no hay nada escuchando en {URL_N8N}")
                print("       arranca n8n y confirma que el workflow este publicado")
                resultados.append(False)
            except Exception as error:
                print(f"  {DIFF} {type(error).__name__}: {error}")
                resultados.append(False)

        print("\n" + "=" * 70)
        print(f"{sum(resultados)}/{len(resultados)} casos como se esperaba")
        return 0 if all(resultados) else 1
    finally:
        doble.parar()


if __name__ == "__main__":
    raise SystemExit(main())
