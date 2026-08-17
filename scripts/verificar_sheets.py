"""Verificación manual de la conexión con Google Sheets (cierre de CP1).

No es un test de pytest: necesita credenciales reales y red, así que lo corre
la persona en su propia terminal. Nunca imprime valores secretos.

Uso:
    .venv\\Scripts\\python.exe scripts/verificar_sheets.py            # solo lectura
    .venv\\Scripts\\python.exe scripts/verificar_sheets.py --escribir  # además escribe
"""

from __future__ import annotations

import os
import sys
from datetime import date, datetime, time
from pathlib import Path

from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.availability import Turno, slots_disponibles  # noqa: E402
from app.config_loader import cargar_config  # noqa: E402
from app.sheets_client import SheetsClient  # noqa: E402

OK = "[OK]"
ERROR = "[ERROR]"


def _revisar_entorno() -> bool:
    """Confirma que las variables estén cargadas, sin mostrar sus valores."""
    print("\n1. Variables de entorno")
    todo_bien = True

    for nombre in ("GOOGLE_SHEETS_CREDENTIALS_PATH", "SPREADSHEET_ID"):
        valor = os.getenv(nombre)
        if valor:
            # Solo el largo: alcanza para saber que está cargada y no filtra nada.
            print(f"   {OK} {nombre} cargada ({len(valor)} caracteres)")
        else:
            print(f"   {ERROR} {nombre} vacía o ausente")
            todo_bien = False

    print(f"   ... pestaña: {os.getenv('SHEET_WORKSHEET', 'Turnos')}")

    ruta = os.getenv("GOOGLE_SHEETS_CREDENTIALS_PATH", "")
    if ruta:
        if Path(ruta).is_file():
            print(f"   {OK} el JSON de credenciales existe en disco")
        else:
            print(f"   {ERROR} no hay ningún archivo en esa ruta")
            todo_bien = False

    return todo_bien


def _leer(cliente: SheetsClient) -> list[Turno]:
    print("\n2. Lectura de la planilla")
    turnos = cliente.leer_turnos()
    print(f"   {OK} conexión establecida, {len(turnos)} turno(s) leído(s)")

    for t in turnos[:5]:
        print(f"      · {t.fecha} {t.hora:%H:%M}  {t.servicio_id}  {t.nombre_paciente}")
    if len(turnos) > 5:
        print(f"      … y {len(turnos) - 5} más")

    return turnos


def _cruzar_con_el_motor(turnos: list[Turno]) -> None:
    """Confirma que lo leído de la Sheet alimenta bien el motor de slots."""
    print("\n3. Disponibilidad calculada sobre los turnos reales")
    config = cargar_config()

    objetivo = turnos[0].fecha if turnos else date.today()
    libres = slots_disponibles(objetivo, turnos, config, ahora=datetime(2000, 1, 1))
    ocupados = [t.hora for t in turnos if t.fecha == objetivo]

    print(f"   fecha analizada: {objetivo} ({objetivo.strftime('%A')})")
    print(f"   ocupados: {[f'{h:%H:%M}' for h in sorted(ocupados)] or 'ninguno'}")
    print(f"   libres:   {[f'{h:%H:%M}' for h in libres] or 'ninguno'}")
    print(f"   {OK} el motor procesó los turnos reales sin errores")


def _escribir(cliente: SheetsClient) -> None:
    print("\n4. Escritura de un turno de prueba")
    prueba = Turno(
        fecha=date(2030, 1, 1),  # fecha absurda a propósito: se reconoce y se borra fácil
        hora=time(9, 0),
        servicio_id="control",
        nombre_paciente="PRUEBA - borrar esta fila",
        telefono="5492610000000",
    )

    antes = len(cliente.leer_turnos())
    cliente.guardar_turno(prueba)
    despues = cliente.leer_turnos()

    if len(despues) == antes + 1 and despues[-1].nombre_paciente == prueba.nombre_paciente:
        print(f"   {OK} turno escrito y releído correctamente")
        print("   >> Borrá a mano la fila con fecha 2030-01-01 de la planilla.")
    else:
        print(f"   {ERROR} se escribió pero no se releyó como se esperaba")


def main() -> int:
    load_dotenv()

    print("=" * 60)
    print("Verificación de Google Sheets — CP1")
    print("=" * 60)

    if not _revisar_entorno():
        print(f"\n{ERROR} Falta configurar el .env. No sigo.")
        return 1

    try:
        cliente = SheetsClient.desde_entorno()
        turnos = _leer(cliente)
        _cruzar_con_el_motor(turnos)

        if "--escribir" in sys.argv:
            _escribir(cliente)
        else:
            print("\n4. Escritura omitida (pasá --escribir para probarla)")

    except Exception as error:  # noqa: BLE001 — script manual, queremos ver todo
        print(f"\n{ERROR} {type(error).__name__}: {error}")
        print(_pista(error))
        return 1

    print("\n" + "=" * 60)
    print("Verificación terminada sin errores.")
    print("=" * 60)
    return 0


def _pista(error: Exception) -> str:
    """Traduce los errores típicos de Google a algo accionable."""
    texto = str(error).lower()
    if "permission" in texto or "403" in texto:
        return (
            "   >> Pista: la Sheet no está compartida con la service account.\n"
            "      Abrí la planilla, Compartir, y pegá el email de la service\n"
            "      account con permiso de Editor."
        )
    if "404" in texto or "not found" in texto:
        return "   >> Pista: revisá el SPREADSHEET_ID, o el nombre de la pestaña."
    if "worksheet" in texto:
        return (
            "   >> Pista: no existe esa pestaña. Revisá SHEET_WORKSHEET contra\n"
            "      el nombre real de la solapa (sensible a mayúsculas)."
        )
    if "api has not been used" in texto or "disabled" in texto:
        return "   >> Pista: falta habilitar la Google Sheets API en el proyecto."
    return "   >> Revisá el mensaje de arriba."


if __name__ == "__main__":
    raise SystemExit(main())
