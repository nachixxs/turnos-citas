"""Tests de carga y validación del JSON de configuración (SPECS §5)."""

from __future__ import annotations

import json
from datetime import time
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.config_loader import ConfigNegocio, cargar_config

CONFIG_VALIDO: dict = {
    "negocio": {"nombre": "Test", "direccion": "Calle 1", "atiende_obra_social": False},
    "horario_atencion": {"lunes_a_viernes": ["09:00-13:00"]},
    "duracion_slot_minutos": 30,
    "servicios": [
        {"id": "control", "nombre": "Control", "precio": 32000, "duracion_min": 20}
    ],
}


def _escribir(tmp_path: Path, datos: dict) -> Path:
    destino = tmp_path / "negocio.json"
    destino.write_text(json.dumps(datos), encoding="utf-8")
    return destino


# ── El config real del repo ───────────────────────────────────────────────


def test_el_config_del_repo_carga_sin_errores() -> None:
    config = cargar_config()
    assert isinstance(config, ConfigNegocio)


def test_el_config_del_repo_coincide_con_specs_seccion_4() -> None:
    config = cargar_config()

    assert config.negocio.nombre == "Consultorio Odontológico Dr. Franco Aguilar"
    assert config.negocio.direccion == "Av. San Martín 850"
    assert config.negocio.atiende_obra_social is False
    assert config.duracion_slot_minutos == 30
    assert [s.id for s in config.servicios] == ["control", "limpieza", "extraccion"]


def test_los_precios_coinciden_con_specs_seccion_4() -> None:
    config = cargar_config()
    precios = {s.id: s.precio for s in config.servicios}
    assert precios == {"control": 32000, "limpieza": 110000, "extraccion": 160000}


def test_los_rangos_horarios_se_parsean_a_time() -> None:
    config = cargar_config()
    manana, tarde = config.horario_atencion.lunes_a_viernes

    assert (manana.inicio, manana.fin) == (time(9, 0), time(13, 0))
    assert (tarde.inicio, tarde.fin) == (time(15, 0), time(19, 0))


def test_servicio_por_id_encuentra_y_falla_bien() -> None:
    config = cargar_config()
    assert config.servicio_por_id("limpieza").nombre == "Limpieza dental"
    assert config.servicio_por_id("blanqueamiento") is None


# ── Errores de esquema: tienen que explotar, no pasar silenciosos ─────────


def test_archivo_inexistente_lanza(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        cargar_config(tmp_path / "no-existe.json")


def test_clave_desconocida_lanza(tmp_path: Path) -> None:
    datos = {**CONFIG_VALIDO, "duracion_slot_minuto": 30}  # typo deliberado
    with pytest.raises(ValidationError):
        cargar_config(_escribir(tmp_path, datos))


def test_falta_una_clave_obligatoria_lanza(tmp_path: Path) -> None:
    datos = {k: v for k, v in CONFIG_VALIDO.items() if k != "servicios"}
    with pytest.raises(ValidationError):
        cargar_config(_escribir(tmp_path, datos))


def test_rango_horario_invertido_lanza(tmp_path: Path) -> None:
    datos = {**CONFIG_VALIDO, "horario_atencion": {"lunes_a_viernes": ["13:00-09:00"]}}
    with pytest.raises(ValidationError):
        cargar_config(_escribir(tmp_path, datos))


def test_rango_horario_con_formato_invalido_lanza(tmp_path: Path) -> None:
    datos = {**CONFIG_VALIDO, "horario_atencion": {"lunes_a_viernes": ["9 a 13"]}}
    with pytest.raises(ValidationError):
        cargar_config(_escribir(tmp_path, datos))


def test_ids_de_servicio_duplicados_lanzan(tmp_path: Path) -> None:
    datos = {
        **CONFIG_VALIDO,
        "servicios": [
            {"id": "control", "nombre": "Control", "precio": 1, "duracion_min": 20},
            {"id": "control", "nombre": "Otro", "precio": 2, "duracion_min": 30},
        ],
    }
    with pytest.raises(ValidationError):
        cargar_config(_escribir(tmp_path, datos))


def test_duracion_de_slot_en_cero_lanza(tmp_path: Path) -> None:
    with pytest.raises(ValidationError):
        cargar_config(_escribir(tmp_path, {**CONFIG_VALIDO, "duracion_slot_minutos": 0}))


def test_catalogo_de_servicios_vacio_lanza(tmp_path: Path) -> None:
    with pytest.raises(ValidationError):
        cargar_config(_escribir(tmp_path, {**CONFIG_VALIDO, "servicios": []}))
