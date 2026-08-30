"""Tests del adaptador CLI (parseo de argumentos y construcción de la petición)."""
from __future__ import annotations

import argparse

import pytest

from sinnema.infrastructure.cli.main import (
    DEFAULT_PROJECT_ID,
    _int_en_rango,
    _parse_args,
    build_request_from_args,
)

from conftest import TEMA, make_project


def _args(**overrides) -> argparse.Namespace:
    datos = dict(
        project=DEFAULT_PROJECT_ID,
        topic=None,
        chapters=3,
        max_critique_attempts=2,
        output=None,
        verbose=False,
        list_projects=False,
    )
    datos.update(overrides)
    return argparse.Namespace(**datos)


# ------------------------------ _int_en_rango ------------------------------


def test_entero_valido_dentro_de_rango():
    validar = _int_en_rango(1, 5, "Mensaje de error")
    assert validar("3") == 3
    assert validar("1") == 1
    assert validar("5") == 5


def test_entero_fuera_de_rango_rechazado():
    validar = _int_en_rango(1, 5, "Número inválido")
    with pytest.raises(argparse.ArgumentTypeError):
        validar("6")
    with pytest.raises(argparse.ArgumentTypeError):
        validar("0")


def test_valor_no_numerico_rechazado():
    validar = _int_en_rango(1, 5, "Número inválido")
    with pytest.raises(argparse.ArgumentTypeError):
        validar("tres")
    with pytest.raises(argparse.ArgumentTypeError):
        validar("2.5")


# -------------------------------- _parse_args --------------------------------


def test_argumentos_por_defecto(monkeypatch):
    monkeypatch.setattr("sys.argv", ["sinnema"])
    args = _parse_args()
    assert args.project == DEFAULT_PROJECT_ID
    assert args.topic is None  # se resuelve con el tema del proyecto
    assert args.chapters == 3
    assert args.max_critique_attempts == 2
    assert args.output is None
    assert args.verbose is False
    assert args.list_projects is False


def test_argumentos_personalizados(monkeypatch):
    monkeypatch.setattr(
        "sys.argv",
        ["sinnema", "-p", "motores", "-t", "Motores híbridos", "-n", "5", "-m", "3",
         "-o", "salidas/prueba.json", "-v"],
    )
    args = _parse_args()
    assert args.project == "motores"
    assert args.topic == "Motores híbridos"
    assert args.chapters == 5
    assert args.max_critique_attempts == 3
    assert args.output == "salidas/prueba.json"
    assert args.verbose is True


def test_capitulos_fuera_de_rango_cortan_la_ejecucion(monkeypatch):
    monkeypatch.setattr("sys.argv", ["sinnema", "-n", "21"])
    with pytest.raises(SystemExit) as excinfo:
        _parse_args()
    assert excinfo.value.code == 2


def test_list_projects_se_parsea(monkeypatch):
    monkeypatch.setattr("sys.argv", ["sinnema", "--list-projects"])
    assert _parse_args().list_projects is True


# --------------------------- build_request_from_args ---------------------------


def test_peticion_sin_tema_resuelve_al_default_del_proyecto():
    proyecto = make_project()
    request = build_request_from_args(_args(chapters=4, max_critique_attempts=3), proyecto)
    assert request.project is proyecto
    assert request.resolved_topic() == TEMA
    assert request.num_chapters == 4
    assert request.max_critique_attempts == 3


def test_peticion_con_tema_explicito_gana_al_proyecto():
    request = build_request_from_args(
        _args(topic="Fotosíntesis en 60 segundos"), make_project()
    )
    assert request.resolved_topic() == "Fotosíntesis en 60 segundos"


def test_peticion_con_tema_corto_rechazada():
    with pytest.raises(ValueError, match="tema"):
        build_request_from_args(_args(topic="corto"), make_project())
