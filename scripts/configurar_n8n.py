"""Renderiza el workflow de n8n desde la plantilla y lo importa (CP4).

El repo versiona `n8n/flow.template.json`, con placeholders en lugar de secretos.
Este guion lo renderiza con los valores reales de `.env` en `n8n/flow.local.json`
—que está gitignoreado— y lo carga en n8n por CLI.

Se hace por CLI y no por la API de n8n a propósito: `publish:workflow` es el
`Publish` explícito que n8n 2.x separó de guardar, y evita el bug de que activar
un workflow por API no registre el webhook en la memoria del proceso.

Uso:

    .venv\\Scripts\\python.exe scripts/configurar_n8n.py --solo-render
    .venv\\Scripts\\python.exe scripts/configurar_n8n.py

**Después de importar hay que reiniciar n8n.** No es opcional: el proceso no
registra el webhook nuevo hasta que arranca de nuevo, y el síntoma es un 404 en
la URL aunque el workflow figure como publicado.

Este guion no toca Meta. Eso es `scripts/configurar_meta.py`.
"""

from __future__ import annotations

import argparse
import json
import os
import secrets
import shutil
import subprocess
import sys
from pathlib import Path

from dotenv import load_dotenv

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

OK = "[OK]"
DIFF = "[DIFF]"

PLANTILLA = RAIZ / "n8n" / "flow.template.json"
RENDERIZADO = RAIZ / "n8n" / "flow.local.json"

# Placeholder en la plantilla -> variable de entorno que lo reemplaza.
REEMPLAZOS: dict[str, str] = {
    "<VERIFY_TOKEN>": "META_VERIFY_TOKEN",
    "<WHATSAPP_PHONE_ID>": "WHATSAPP_PHONE_ID",
    "<WHATSAPP_TOKEN>": "WHATSAPP_TOKEN",
    "<GRAPH_API_BASE>": "GRAPH_API_BASE",
}

# La Graph API real. Se pisa con GRAPH_API_BASE para correr el flujo entero
# contra un doble local y verificar CP4 sin depender de Meta.
GRAPH_API_POR_DEFECTO = "https://graph.facebook.com/v21.0"

ID_WORKFLOW = "turnos-citas-cp4"


def ruta_n8n() -> str | None:
    """n8n instalado global por npm. En Windows el ejecutable es `n8n.cmd`."""
    return shutil.which("n8n") or shutil.which("n8n.cmd")


def renderizar() -> tuple[str, list[str]]:
    """Devuelve el workflow con los valores reales y qué variables faltaron."""
    plantilla = PLANTILLA.read_text(encoding="utf-8")

    faltantes: list[str] = []
    for marca, variable in REEMPLAZOS.items():
        valor = os.getenv(variable, "")
        if not valor and variable == "GRAPH_API_BASE":
            valor = GRAPH_API_POR_DEFECTO
        if not valor:
            faltantes.append(variable)
            continue
        # json.dumps escapa comillas y backslashes: un token con caracteres
        # raros no puede romper el JSON del workflow.
        plantilla = plantilla.replace(marca, json.dumps(valor)[1:-1])

    return plantilla, faltantes


def importar(ejecutable: str) -> bool:
    """Importa y publica el workflow. Devuelve True si las dos cosas salieron bien."""
    for descripcion, comando in (
        ("import", [ejecutable, "import:workflow", f"--input={RENDERIZADO}"]),
        ("publish", [ejecutable, "publish:workflow", f"--id={ID_WORKFLOW}"]),
    ):
        print(f"\n  $ n8n {comando[1]}")
        resultado = subprocess.run(comando, capture_output=True, text=True)
        salida = (resultado.stdout + resultado.stderr).strip()
        for linea in salida.splitlines():
            if "Error tracking disabled" not in linea:
                print(f"    {linea}")
        if resultado.returncode != 0:
            print(f"  {DIFF} fallo el {descripcion} (codigo {resultado.returncode})")
            return False

    return True


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--solo-render",
        action="store_true",
        help="renderiza el archivo pero no lo importa a n8n",
    )
    args = parser.parse_args()

    load_dotenv(RAIZ / ".env")

    print("=" * 70)
    print("Configuracion del workflow de n8n - CP4")
    print("=" * 70)

    contenido, faltantes = renderizar()

    if faltantes:
        print(f"\n{DIFF} faltan variables en .env: {', '.join(faltantes)}")
        if "META_VERIFY_TOKEN" in faltantes:
            # Lo elegimos nosotros: es un secreto compartido entre Meta y n8n,
            # no lo emite Meta. Tiene que ser el mismo string en los dos lados.
            print("\n    META_VERIFY_TOKEN lo elegis vos. Podes usar este:")
            print(f"    META_VERIFY_TOKEN=turnos-{secrets.token_hex(8)}")
        print("\n    El resto sale del panel de Meta (ver ESTADO.md, seccion CP4).")
        return 1

    RENDERIZADO.write_text(contenido, encoding="utf-8")
    print(f"\n{OK} renderizado en {RENDERIZADO.relative_to(RAIZ)}")

    # Chequeo de seguridad: que no haya quedado ningun placeholder sin sustituir.
    restantes = [m for m in REEMPLAZOS if m in contenido]
    if restantes:
        print(f"{DIFF} quedaron placeholders sin reemplazar: {restantes}")
        return 1

    if args.solo_render:
        print("\n(--solo-render: no se importo nada a n8n)")
        return 0

    ejecutable = ruta_n8n()
    if not ejecutable:
        print(f"\n{DIFF} no encuentro el ejecutable de n8n en el PATH")
        print("    instalalo con: npm install -g n8n")
        return 1

    if not importar(ejecutable):
        return 1

    print(f"\n{OK} workflow importado y publicado")
    print("\n" + "=" * 70)
    print("FALTA UN PASO: reinicia n8n.")
    print("Publicar no registra el webhook en el proceso que ya esta corriendo;")
    print("sin reiniciar, la URL devuelve 404 aunque el workflow figure activo.")
    print("=" * 70)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
