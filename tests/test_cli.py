"""Tests del adaptador CLI (parseo de argumentos y construcción de la petición)."""
from __future__ import annotations

import argparse
import json

import pytest

from sinnema.infrastructure.cli.main import (
    DEFAULT_PROJECT_ID,
    _int_en_rango,
    _parse_args,
    build_request_from_args,
    proyecto_para_corrida,
)

from conftest import TEMA, FakeGateway, make_draft, make_directives, make_plan, make_project


def _args(**overrides) -> argparse.Namespace:
    datos = dict(
        project=DEFAULT_PROJECT_ID,
        topic=None,
        chapters=3,
        max_critique_attempts=2,
        hasta=None,
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


# -------------------------------- --hasta --------------------------------


def test_hasta_por_defecto_es_none(monkeypatch):
    monkeypatch.setattr("sys.argv", ["sinnema"])
    assert _parse_args().hasta is None


def test_hasta_valido_se_parsea(monkeypatch):
    monkeypatch.setattr("sys.argv", ["sinnema", "--hasta", "guion_final"])
    assert _parse_args().hasta == "guion_final"


def test_hasta_invalido_corta_la_ejecucion_con_error_accionable(monkeypatch):
    monkeypatch.setattr("sys.argv", ["sinnema", "--hasta", "video"])
    with pytest.raises(SystemExit) as excinfo:
        _parse_args()
    assert excinfo.value.code == 2


def test_sin_flag_el_proyecto_manda_intacto():
    proyecto = make_project()  # sin [flujo]: la corrida no altera el spec
    assert proyecto_para_corrida(_args(), proyecto) is proyecto


def test_flag_hasta_gana_al_proyecto():
    from sinnema.domain.constants import ALCANCE_DEFAULT

    proyecto = make_project()
    corrida = proyecto_para_corrida(_args(hasta="guion"), proyecto)
    assert corrida is not proyecto
    assert corrida.flujo.hasta == "guion"
    assert proyecto.flujo is None  # el spec original no se muta
    # El default del vocabulario sigue siendo 'produccion' (§5).
    assert ALCANCE_DEFAULT == "produccion"


def test_flag_hasta_incoherente_con_flujo_es_error_accionable():
    from sinnema.application.projects import AgentConfig, FlowSpec

    proyecto = make_project(
        flujo=FlowSpec(contexto=("continuity",), hasta="guion"),
        agentes={"critic": AgentConfig(activo=True)},
    )
    with pytest.raises(ValueError, match="revisor"):
        proyecto_para_corrida(_args(hasta="auditado"), proyecto)


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


# ------------------------- corrida de punta a punta -------------------------


def test_corrida_cli_con_hasta_guion_entrega_borradores_sin_specs(
    monkeypatch, tmp_path, capsys
):
    """CLI de punta a punta con puertos nulos y ``--hasta guion``.

    El proyecto legacy corre con el FakeGateway y el hito de la flag corta el
    pipeline tras el escritor: episodios con ``technical`` nulo y cero
    invocaciones a adaptador/crítico/director. El resumen menciona el alcance.
    """
    import sinnema.infrastructure.cli.main as cli_main

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        "sys.argv",
        ["sinnema", "-p", "sinnema", "--hasta", "guion", "-n", "1",
         "-o", "salidas/serie.json"],
    )
    proyecto = make_project()
    monkeypatch.setattr(cli_main, "load_project", lambda pid: proyecto)

    gw = FakeGateway()
    gw.add("planner", [make_plan(1)])
    gw.add("continuity", [make_directives()])
    gw.add("scriptwriter", [make_draft("ch-01")])
    monkeypatch.setattr(cli_main, "build_gateway", lambda p: gw)

    assert cli_main.main() == 0

    salida = capsys.readouterr().out
    assert "Alcance de la corrida: guion" in salida
    datos = json.loads((tmp_path / "salidas" / "serie.json").read_text())
    assert datos["alcance"] == "guion"
    assert datos["schema_version"] == "1.2"
    assert len(datos["episodes"]) == 1
    assert datos["episodes"][0]["technical"] is None
    assert datos["episodes"][0]["audit"] is None
    assert set(gw.calls) == {"planner", "continuity", "scriptwriter"}
