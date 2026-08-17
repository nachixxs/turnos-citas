"""Carga y validación del JSON de configuración del negocio (SPECS §5).

Único punto de lectura del archivo de configuración: el resto del código nunca
abre el JSON, siempre recibe un `ConfigNegocio` ya validado (ver CODESTYLE).
"""

from __future__ import annotations

import json
from datetime import time
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

RUTA_CONFIG_POR_DEFECTO = Path("config/negocio.json")


class _Base(BaseModel):
    """Base común: prohíbe claves desconocidas.

    Un typo en el JSON (`duracion_slot_minuto`) tiene que explotar al cargar,
    no convertirse en un default silencioso a las tres semanas.
    """

    model_config = ConfigDict(extra="forbid")


class RangoHorario(_Base):
    """Una franja continua de atención, ej. 09:00–13:00."""

    inicio: time
    fin: time

    @model_validator(mode="after")
    def _validar_orden(self) -> RangoHorario:
        if self.inicio >= self.fin:
            raise ValueError(
                f"rango horario invertido: {self.inicio:%H:%M}-{self.fin:%H:%M}"
            )
        return self


def _texto_a_rango(crudo: str) -> dict[str, str]:
    """Convierte '09:00-13:00' en las claves que espera `RangoHorario`."""
    partes = crudo.split("-")
    if len(partes) != 2:
        raise ValueError(f"rango horario inválido: {crudo!r} (se espera 'HH:MM-HH:MM')")
    return {"inicio": partes[0].strip(), "fin": partes[1].strip()}


class HorarioAtencion(_Base):
    lunes_a_viernes: list[RangoHorario] = Field(min_length=1)

    @field_validator("lunes_a_viernes", mode="before")
    @classmethod
    def _admitir_texto(cls, valor: object) -> object:
        """Acepta la forma corta del SPECS: ["09:00-13:00", "15:00-19:00"]."""
        if isinstance(valor, list):
            return [_texto_a_rango(v) if isinstance(v, str) else v for v in valor]
        return valor


class Servicio(_Base):
    id: str = Field(min_length=1)
    nombre: str = Field(min_length=1)
    precio: int = Field(ge=0)
    duracion_min: int = Field(gt=0)


class Negocio(_Base):
    nombre: str = Field(min_length=1)
    direccion: str = Field(min_length=1)
    # Contacto directo al que el bot deriva las cancelaciones y
    # reprogramaciones, que quedan fuera de alcance (SPECS §9).
    telefono_contacto: str = Field(min_length=1)
    atiende_obra_social: bool


class ConfigNegocio(_Base):
    """Configuración completa de un negocio. El motor es genérico: todo lo que
    cambia de un cliente a otro entra por acá, nunca hardcodeado en el código."""

    negocio: Negocio
    horario_atencion: HorarioAtencion
    duracion_slot_minutos: int = Field(gt=0)
    servicios: list[Servicio] = Field(min_length=1)

    @model_validator(mode="after")
    def _ids_de_servicio_unicos(self) -> ConfigNegocio:
        ids = [s.id for s in self.servicios]
        duplicados = {i for i in ids if ids.count(i) > 1}
        if duplicados:
            raise ValueError(f"ids de servicio duplicados: {sorted(duplicados)}")
        return self

    def servicio_por_id(self, servicio_id: str) -> Servicio | None:
        """Devuelve el servicio con ese id, o None si no existe en el catálogo."""
        return next((s for s in self.servicios if s.id == servicio_id), None)


def cargar_config(ruta: str | Path = RUTA_CONFIG_POR_DEFECTO) -> ConfigNegocio:
    """Lee y valida el JSON de configuración. Lanza si el archivo no existe,
    no es JSON válido, o no cumple el esquema."""
    camino = Path(ruta)
    if not camino.is_file():
        raise FileNotFoundError(f"no existe el archivo de configuración: {camino}")

    # encoding explícito: en Windows el default puede ser cp1252 y rompe con
    # los acentos de "Consultorio Odontológico".
    with camino.open(encoding="utf-8") as archivo:
        crudo = json.load(archivo)

    return ConfigNegocio.model_validate(crudo)
