"""Configura el webhook de Meta por Graph API, sin tocar el panel (CP4).

Lo único que hay que hacer a mano en developers.facebook.com es **crear la app**
y copiar sus valores a `.env`: no existe una Graph API para crear apps. Todo lo
demás —registrar la URL del webhook, suscribir la app al WABA, verificar que
quedó— se hace desde acá.

Es idempotente: se puede correr todas las veces que haga falta. Cuánto hace
falta depende del túnel: si la cuenta de ngrok tiene dominio estático la URL
sobrevive a los reinicios y no hay que volver a registrar nada; si el dominio es
aleatorio cambia en cada arranque y sí hay que correr esto de nuevo.

Uso:

    .venv\\Scripts\\python.exe scripts/configurar_meta.py
    .venv\\Scripts\\python.exe scripts/configurar_meta.py --solo-verificar
    .venv\\Scripts\\python.exe scripts/configurar_meta.py --enviar 5492615550199

Requiere el túnel de ngrok levantado (`ngrok http 5678`): la URL pública se lee
sola de su API local, no hay que copiarla a mano.

Nunca imprime tokens ni secretos.

**El paso 2 es el que más caro salió en el proyecto anterior.** El enlace `subscribed_apps`
entre el WABA y la app no aparece en ninguna pantalla del panel de Meta y sin él
no llega ningún mensaje, sin ningún error visible que lo explique.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

import httpx
from dotenv import load_dotenv

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

OK = "[OK]"
DIFF = "[DIFF]"

GRAPH = "https://graph.facebook.com/v21.0"
API_NGROK = "http://127.0.0.1:4040/api/tunnels"

# Tiene que coincidir con el `path` de los dos nodos Webhook de
# `n8n/flow.template.json`. La URL de producción de n8n es /webhook/<path>;
# /webhook-test/<path> solo vive mientras la UI está escuchando.
PATH_WEBHOOK = "turnos-citas"

VARIABLES = (
    "META_APP_ID",
    "META_APP_SECRET",
    "WHATSAPP_TOKEN",
    "WHATSAPP_WABA_ID",
    "META_VERIFY_TOKEN",
)


def url_publica_de_ngrok() -> str | None:
    """La URL https del túnel, leída de la API local de ngrok."""
    try:
        datos = httpx.get(API_NGROK, timeout=5.0).json()
    except Exception:
        return None

    for tunel in datos.get("tunnels", []):
        if tunel.get("public_url", "").startswith("https://"):
            return tunel["public_url"]
    return None


def _mostrar(respuesta: httpx.Response) -> None:
    try:
        print(f"    respuesta: {json.dumps(respuesta.json(), ensure_ascii=False)[:400]}")
    except Exception:
        print(f"    respuesta: {respuesta.text[:400]}")


def registrar_callback(app_id: str, app_secret: str, callback: str, verify: str) -> bool:
    """Paso 1 — registra la URL del webhook a nivel de la app.

    Usa el token de app (`app_id|app_secret`), no el de usuario: es el único que
    puede tocar las suscripciones de la app.
    """
    print("\n1. Registrando la URL del webhook en la app")
    print(f"   callback: {callback}")

    respuesta = httpx.post(
        f"{GRAPH}/{app_id}/subscriptions",
        data={
            "object": "whatsapp_business_account",
            "callback_url": callback,
            "verify_token": verify,
            "fields": "messages",
            "access_token": f"{app_id}|{app_secret}",
        },
        timeout=30.0,
    )

    if respuesta.status_code == 200 and respuesta.json().get("success"):
        print(f"   {OK} registrada")
        return True

    print(f"   {DIFF} fallo (status {respuesta.status_code})")
    _mostrar(respuesta)
    print("\n   Si dice que no puede verificar la URL, chequeá que:")
    print("   - el tunel de ngrok este levantado y apuntando al 5678")
    print("   - n8n este corriendo y el workflow PUBLICADO")
    print("   - hayas REINICIADO n8n despues de importar el workflow")
    print("   - META_VERIFY_TOKEN sea identico en .env y en el workflow importado")
    return False


def suscribir_waba(waba_id: str, token: str) -> bool:
    """Paso 2 — el enlace `subscribed_apps` entre el WABA y la app.

    No existe en ninguna pantalla del panel. Sin esto Meta acepta toda la
    configuración, no da ningún error, y los mensajes simplemente no llegan.
    """
    print("\n2. Suscribiendo la app al WABA (el enlace invisible)")

    respuesta = httpx.post(
        f"{GRAPH}/{waba_id}/subscribed_apps",
        headers={"Authorization": f"Bearer {token}"},
        timeout=30.0,
    )

    if respuesta.status_code == 200 and respuesta.json().get("success"):
        print(f"   {OK} suscrita")
        return True

    print(f"   {DIFF} fallo (status {respuesta.status_code})")
    _mostrar(respuesta)
    return False


def verificar(app_id: str, app_secret: str, waba_id: str, token: str) -> bool:
    """Paso 3 — lee de vuelta las dos cosas, en vez de darlas por hechas."""
    print("\n3. Verificando contra Meta")
    todo_bien = True

    subs = httpx.get(
        f"{GRAPH}/{app_id}/subscriptions",
        params={"access_token": f"{app_id}|{app_secret}"},
        timeout=30.0,
    )
    if subs.status_code == 200:
        for entrada in subs.json().get("data", []):
            if entrada.get("object") == "whatsapp_business_account":
                campos = [c.get("name") for c in entrada.get("fields", [])]
                print(f"   {OK} callback registrado: {entrada.get('callback_url')}")
                print(f"        campos suscritos: {campos}")
                if "messages" not in campos:
                    print(f"   {DIFF} falta el campo 'messages'")
                    todo_bien = False
                break
        else:
            print(f"   {DIFF} no hay suscripcion para whatsapp_business_account")
            todo_bien = False
    else:
        print(f"   {DIFF} no pude leer las suscripciones (status {subs.status_code})")
        _mostrar(subs)
        todo_bien = False

    apps = httpx.get(
        f"{GRAPH}/{waba_id}/subscribed_apps",
        headers={"Authorization": f"Bearer {token}"},
        timeout=30.0,
    )
    if apps.status_code == 200:
        datos = apps.json().get("data", [])
        if datos:
            nombres = [a.get("whatsapp_business_api_data", {}).get("name") for a in datos]
            print(f"   {OK} apps suscritas al WABA: {nombres}")
        else:
            print(f"   {DIFF} el WABA no tiene ninguna app suscrita")
            print("        es exactamente el bug invisible: corre el paso 2")
            todo_bien = False
    else:
        print(f"   {DIFF} no pude leer subscribed_apps (status {apps.status_code})")
        _mostrar(apps)
        todo_bien = False

    return todo_bien


def enviar_mensaje(phone_id: str, token: str, destino: str) -> bool:
    """Manda un mensaje real de prueba.

    Dos cosas distintas pueden hacer que no llegue, y conviene no confundirlas:

    - `131030 Recipient phone number not in allowed list` — falta cargar el
      numero como destinatario de prueba en el panel (WhatsApp -> API Setup,
      desplegable "To"). Es lo unico de todo esto que no tiene Graph API.
    - `131047 Re-engagement message` — pasaron mas de 24hs desde que esa persona
      escribio. WhatsApp solo deja mandar texto libre dentro de esa ventana, asi
      que un mensaje en frio no llega nunca. No hay nada que arreglar: la ventana
      la abre la persona escribiendo primero.

    Ninguno de los dos aparece en la respuesta del POST. Meta contesta 200 con un
    `wamid` igual, y recien despues reporta el fallo como evento de estado en el
    webhook. Que este guion diga "aceptado por Meta" no significa que llego.
    """
    print(f"\n4. Enviando mensaje de prueba a {destino}")

    # El "9" de los numeros argentinos: el formato tiene que coincidir exacto
    # con como quedo registrado el numero, o Meta rechaza el envio.
    normalizado = destino[:2] + destino[3:] if destino.startswith("549") else destino
    if normalizado != destino:
        print(f"   (normalizado sin el 9: {normalizado})")

    respuesta = httpx.post(
        f"{GRAPH}/{phone_id}/messages",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "messaging_product": "whatsapp",
            "to": normalizado,
            "type": "text",
            "text": {"body": "Prueba de conexion del bot de turnos."},
        },
        timeout=30.0,
    )

    if respuesta.status_code == 200:
        print(f"   {OK} aceptado por Meta")
        _mostrar(respuesta)
        return True

    print(f"   {DIFF} fallo (status {respuesta.status_code})")
    _mostrar(respuesta)
    return False


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--solo-verificar",
        action="store_true",
        help="no registra nada, solo lee el estado actual en Meta",
    )
    parser.add_argument(
        "--enviar",
        metavar="NUMERO",
        help="manda un mensaje de prueba a ese numero (formato 549261...)",
    )
    args = parser.parse_args()

    load_dotenv(RAIZ / ".env")

    print("=" * 70)
    print("Configuracion de Meta por Graph API - CP4")
    print("=" * 70)

    faltantes = [v for v in VARIABLES if not os.getenv(v)]
    if faltantes:
        print(f"\n{DIFF} faltan variables en .env: {', '.join(faltantes)}")
        print("    Salen del panel de Meta. Ver .env.example.")
        return 1

    app_id = os.environ["META_APP_ID"]
    app_secret = os.environ["META_APP_SECRET"]
    token = os.environ["WHATSAPP_TOKEN"]
    waba_id = os.environ["WHATSAPP_WABA_ID"]
    verify = os.environ["META_VERIFY_TOKEN"]

    if args.solo_verificar:
        return 0 if verificar(app_id, app_secret, waba_id, token) else 1

    publica = url_publica_de_ngrok()
    if not publica:
        print(f"\n{DIFF} no encuentro un tunel de ngrok activo")
        print("    levantalo en otra terminal con: ngrok http 5678")
        return 1

    print(f"\n   tunel detectado: {publica}")
    callback = f"{publica}/webhook/{PATH_WEBHOOK}"

    pasos = [
        registrar_callback(app_id, app_secret, callback, verify),
        suscribir_waba(waba_id, token),
        verificar(app_id, app_secret, waba_id, token),
    ]

    if args.enviar:
        phone_id = os.getenv("WHATSAPP_PHONE_ID", "")
        if not phone_id:
            print(f"\n{DIFF} falta WHATSAPP_PHONE_ID en .env para poder enviar")
            pasos.append(False)
        else:
            pasos.append(enviar_mensaje(phone_id, token, args.enviar))

    print("\n" + "=" * 70)
    if all(pasos):
        print(f"{OK} Meta configurado. La URL del webhook es:")
        print(f"    {callback}")
        print("\nSi el dominio de ngrok no es estatico, al reiniciarlo cambia la URL.")
        return 0

    print(f"{DIFF} quedaron pasos sin completar, revisa el detalle de arriba")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
