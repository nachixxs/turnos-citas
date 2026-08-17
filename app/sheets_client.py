"""Cliente de Google Sheets: persistencia de turnos confirmados.

Todo el I/O contra Google vive acá. El motor de disponibilidad
(`availability.py`) recibe los turnos ya leídos y no sabe de dónde salieron:
esa separación es lo que permite testear la lógica sin red ni credenciales.

Columnas esperadas en la fila 1 de la worksheet:

    fecha | hora | servicio_id | nombre_paciente | telefono | creado_en
"""

from __future__ import annotations

import logging
import os
from datetime import date, datetime, time
from pathlib import Path

import gspread
from google.oauth2.service_account import Credentials

from app.availability import Turno

logger = logging.getLogger(__name__)

# Alcance mínimo necesario: solo planillas, y solo las compartidas
# explícitamente con la service account.
ALCANCES: list[str] = ["https://www.googleapis.com/auth/spreadsheets"]

COLUMNAS: list[str] = [
    "fecha",
    "hora",
    "servicio_id",
    "nombre_paciente",
    "telefono",
    "creado_en",
]

FORMATO_FECHA = "%Y-%m-%d"
FORMATO_HORA = "%H:%M"
FORMATO_TIMESTAMP = "%Y-%m-%d %H:%M:%S"


class SheetsClient:
    """Lectura y escritura de turnos sobre una worksheet de Google Sheets."""

    def __init__(
        self,
        sheet_id: str,
        credentials_path: str | Path,
        worksheet: str = "Turnos",
    ) -> None:
        self._sheet_id = sheet_id
        self._credentials_path = Path(credentials_path)
        self._worksheet_name = worksheet
        self._worksheet: gspread.Worksheet | None = None

    @classmethod
    def desde_entorno(cls) -> SheetsClient:
        """Construye el cliente leyendo las variables de `.env` (ver .env.example).

        Falla ruidoso si falta alguna: es preferible a descubrir a mitad de una
        conversación real que el turno nunca se guardó.
        """
        faltantes = [
            nombre
            for nombre in ("SHEET_ID", "GOOGLE_APPLICATION_CREDENTIALS")
            if not os.getenv(nombre)
        ]
        if faltantes:
            raise RuntimeError(
                f"faltan variables de entorno: {', '.join(faltantes)}. "
                "Copiá .env.example a .env y completalas."
            )

        return cls(
            sheet_id=os.environ["SHEET_ID"],
            credentials_path=os.environ["GOOGLE_APPLICATION_CREDENTIALS"],
            worksheet=os.getenv("SHEET_WORKSHEET", "Turnos"),
        )

    def _abrir(self) -> gspread.Worksheet:
        """Abre la worksheet una sola vez y la reusa."""
        if self._worksheet is not None:
            return self._worksheet

        if not self._credentials_path.is_file():
            raise FileNotFoundError(
                f"no existe el JSON de la service account: {self._credentials_path}"
            )

        credenciales = Credentials.from_service_account_file(
            str(self._credentials_path), scopes=ALCANCES
        )
        cliente = gspread.authorize(credenciales)
        self._worksheet = cliente.open_by_key(self._sheet_id).worksheet(
            self._worksheet_name
        )
        logger.info("worksheet '%s' abierta", self._worksheet_name)
        return self._worksheet

    def leer_turnos(self) -> list[Turno]:
        """Devuelve todos los turnos de la planilla.

        Una fila malformada se saltea con un warning en vez de tumbar el
        proceso: un dato roto cargado a mano no puede dejar al bot sin
        responder (CODESTYLE, manejo de errores del MVP).
        """
        filas = self._abrir().get_all_records(expected_headers=COLUMNAS)

        turnos: list[Turno] = []
        for numero, fila in enumerate(filas, start=2):  # fila 1 = encabezados
            try:
                turnos.append(_fila_a_turno(fila))
            except (ValueError, TypeError) as error:
                logger.warning("fila %d ignorada por dato inválido: %s", numero, error)

        logger.info("%d turnos leídos de la planilla", len(turnos))
        return turnos

    def guardar_turno(self, turno: Turno) -> None:
        """Agrega el turno como una fila nueva al final de la planilla."""
        confirmado = (
            turno if turno.creado_en else turno.model_copy(
                update={"creado_en": datetime.now()}
            )
        )
        self._abrir().append_row(
            _turno_a_fila(confirmado), value_input_option="USER_ENTERED"
        )
        logger.info(
            "turno guardado: %s %s %s",
            confirmado.fecha,
            confirmado.hora,
            confirmado.servicio_id,
        )


def _fila_a_turno(fila: dict) -> Turno:
    """Convierte una fila de la planilla en un `Turno` validado."""
    return Turno(
        fecha=_a_fecha(fila["fecha"]),
        hora=_a_hora(fila["hora"]),
        servicio_id=str(fila["servicio_id"]).strip(),
        nombre_paciente=str(fila["nombre_paciente"]).strip(),
        telefono=str(fila["telefono"]).strip(),
        creado_en=_a_timestamp(fila.get("creado_en")),
    )


def _turno_a_fila(turno: Turno) -> list[str]:
    """Serializa un `Turno` en el orden exacto de COLUMNAS."""
    return [
        turno.fecha.strftime(FORMATO_FECHA),
        turno.hora.strftime(FORMATO_HORA),
        turno.servicio_id,
        turno.nombre_paciente,
        turno.telefono,
        (turno.creado_en or datetime.now()).strftime(FORMATO_TIMESTAMP),
    ]


def _a_fecha(valor: object) -> date:
    if isinstance(valor, date) and not isinstance(valor, datetime):
        return valor
    return datetime.strptime(str(valor).strip(), FORMATO_FECHA).date()


def _a_hora(valor: object) -> time:
    if isinstance(valor, time):
        return valor
    # Sheets puede devolver "9:00" o "09:00:00" según cómo se cargó la celda.
    crudo = str(valor).strip()
    for formato in (FORMATO_HORA, "%H:%M:%S"):
        try:
            return datetime.strptime(crudo, formato).time()
        except ValueError:
            continue
    raise ValueError(f"hora inválida: {crudo!r}")


def _a_timestamp(valor: object) -> datetime | None:
    if not valor:
        return None
    if isinstance(valor, datetime):
        return valor
    try:
        return datetime.strptime(str(valor).strip(), FORMATO_TIMESTAMP)
    except ValueError:
        # Un `creado_en` ilegible es metadato, no motivo para descartar el turno.
        return None
