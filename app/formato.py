"""Formateo de datos del negocio para texto en español.

Vive aparte porque lo usan dos módulos con propósitos distintos: `agent.py` para
armar el prompt de sistema y `respuestas.py` para componer el mensaje que ve el
paciente. Duplicarlo llevaría a que el precio se escriba de una forma en el
prompt y de otra en la respuesta.

Nada de acá conoce el negocio concreto: todo dato entra por parámetro desde
`ConfigNegocio` (CODESTYLE, "nada de lógica de negocio hardcodeada").
"""

from __future__ import annotations

from datetime import date, datetime, time

from app.config_loader import RangoHorario

# `strftime('%A')` depende del locale del sistema y en Windows suele devolver
# inglés. Se mapea a mano para que el texto sea siempre en español.
DIAS_SEMANA: list[str] = [
    "lunes",
    "martes",
    "miércoles",
    "jueves",
    "viernes",
    "sábado",
    "domingo",
]

MESES: list[str] = [
    "enero", "febrero", "marzo", "abril", "mayo", "junio",
    "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre",
]


def formato_precio(precio: int) -> str:
    """32000 -> '$32.000' (separador de miles argentino)."""
    return f"${precio:,}".replace(",", ".")


def formato_rango(rango: RangoHorario) -> str:
    return f"{rango.inicio:%H:%M} a {rango.fin:%H:%M}"


def formato_hora(hora: time) -> str:
    """time(9, 30) -> '09:30'. Formato único en prompt, respuesta y Sheet."""
    return f"{hora:%H:%M}"


def fecha_en_palabras(momento: date | datetime) -> str:
    """'miércoles 19 de agosto de 2026' — legible para el modelo y para un humano."""
    dia_semana = DIAS_SEMANA[momento.weekday()]
    return (
        f"{dia_semana} {momento.day} de {MESES[momento.month - 1]} "
        f"de {momento.year}"
    )


def listar_horas(horas: list[time]) -> str:
    """['09:30', '10:00'] -> '09:30 o 10:00'; tres o más -> '09:30, 10:00 o 10:30'."""
    textos = [formato_hora(h) for h in horas]
    if not textos:
        return ""
    if len(textos) == 1:
        return textos[0]
    return f"{', '.join(textos[:-1])} o {textos[-1]}"
