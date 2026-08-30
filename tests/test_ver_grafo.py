"""Tests del script de visualización del grafo (scripts/ver_grafo.py).

Cubren el modo ``diagrama`` (Mermaid y exportación PNG, sin LLM) y el modo
``stream`` con un doble del puerto LLM, además de los resúmenes por nodo.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest

RAIZ = Path(__file__).resolve().parents[1]


def _cargar_script():
    """Importa ``scripts/ver_grafo.py`` como módulo (no es un paquete)."""
    ruta = RAIZ / "scripts" / "ver_grafo.py"
    spec = importlib.util.spec_from_file_location("ver_grafo", ruta)
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


ver_grafo = _cargar_script()

from conftest import (  # noqa: E402
    gateway_con_serie,
    make_audit,
    make_plan,
    make_project,
)


# ------------------------------ CLI básico ------------------------------


def test_sin_subcomando_reporta_error(monkeypatch, capsys):
    monkeypatch.setattr("sys.argv", ["ver_grafo"])
    assert ver_grafo.main() == 2
    assert "diagrama" in capsys.readouterr().err


def test_list_projects_lista_proyectos(monkeypatch, capsys):
    monkeypatch.setattr("sys.argv", ["ver_grafo", "--list-projects"])
    monkeypatch.chdir(RAIZ)

    assert ver_grafo.main() == 0

    salida = capsys.readouterr().out
    assert "Proyectos disponibles:" in salida


# ------------------------------ modo diagrama ------------------------------


@pytest.fixture
def proyecto_falso(monkeypatch):
    """Aisla el script del sistema de archivos de proyectos reales."""
    proyecto = make_project()
    monkeypatch.setattr(ver_grafo, "load_project", lambda _id: proyecto)
    return proyecto


def test_diagrama_imprime_mermaid_con_nodos(monkeypatch, capsys, proyecto_falso):
    monkeypatch.setattr("sys.argv", ["ver_grafo", "diagrama"])

    assert ver_grafo.main() == 0

    salida = capsys.readouterr().out
    assert "graph TD" in salida
    for nodo in ("plan_series", "chief_critic", "commit_episode", "fail_chapter"):
        assert nodo in salida


def test_diagrama_con_png_guarda_archivo(monkeypatch, tmp_path, proyecto_falso):
    png_falso = b"\x89PNG-fake"

    class _FakeGraph:
        def draw_mermaid(self):
            return "graph TD; plan_series;"

        def draw_mermaid_png(self):
            return png_falso

    monkeypatch.setattr("sys.argv", ["ver_grafo", "diagrama", "--png", str(tmp_path / "g.png")])
    monkeypatch.setattr(
        "langgraph.graph.state.CompiledStateGraph.get_graph",
        lambda _self: _FakeGraph(),
    )

    assert ver_grafo.main() == 0
    assert (tmp_path / "g.png").read_bytes() == png_falso


# ------------------------------ _resumen_nodo ------------------------------


def test_resumen_del_plan():
    actualizacion = {"series_plan": make_plan(3), "current_chapter_index": 0}
    resumen = ver_grafo._resumen_nodo("plan_series", actualizacion)
    assert "3 capítulo(s)" in resumen


def test_resumen_del_critic_aprueba():
    actualizacion = {"qa_verdict": make_audit(approved=True), "critique_attempts": 1}
    resumen = ver_grafo._resumen_nodo("chief_critic", actualizacion)
    assert "APRUEBA" in resumen and "intento 1" in resumen


def test_resumen_del_critic_rechaza():
    actualizacion = {"qa_verdict": make_audit(approved=False), "critique_attempts": 2}
    resumen = ver_grafo._resumen_nodo("chief_critic", actualizacion)
    assert "RECHAZA" in resumen


def test_resumen_de_commit_y_fallo():
    commit = ver_grafo._resumen_nodo(
        "commit_episode", {"completed_episodes": [object()], "current_chapter_index": 1}
    )
    assert "episodios listos: 1" in commit
    fallo = ver_grafo._resumen_nodo("fail_chapter", {"current_chapter_index": 2})
    assert "descartado" in fallo and "índice -> 2" in fallo


def test_resumen_por_defecto_lista_claves():
    resumen = ver_grafo._resumen_nodo("scriptwriter", {"draft_script": object()})
    assert resumen == "draft_script"


# ------------------------------ modo stream ------------------------------


def test_stream_recibe_gateway_e_imprime_pasos(monkeypatch, capsys, proyecto_falso):
    gateway = gateway_con_serie(num_chapters=2)
    recibidos: list = []
    monkeypatch.setattr(ver_grafo, "build_gateway", lambda: (recibidos.append(1), gateway)[1])
    monkeypatch.setattr("sys.argv", ["ver_grafo", "stream", "-n", "2"])

    assert ver_grafo.main() == 0

    assert recibidos, "el grafo debe compilarse con el gateway del puerto LLM"
    salida = capsys.readouterr().out
    assert "plan_series" in salida
    assert "chief_critic" in salida
    assert "Pipeline terminado" in salida
    # Dos capítulos: planner 1 + (continuity+script+adapter+critic+director+commit) * 2
    assert "[013]" in salida


def test_stream_sin_proveedor_reporta_error(monkeypatch, capsys, proyecto_falso):
    def _fallar():
        raise RuntimeError("ningún proveedor LLM configurado")

    monkeypatch.setattr(ver_grafo, "build_gateway", _fallar)
    monkeypatch.setattr("sys.argv", ["ver_grafo", "stream"])

    assert ver_grafo.main() == 2
    assert "ningún proveedor" in capsys.readouterr().err
