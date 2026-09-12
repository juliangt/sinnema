"""Tests de las tools integradas (red-3d §7.3) y su registro por rol."""
from __future__ import annotations

import pytest

from sinnema.application.projects import AgentConfig
from sinnema.infrastructure.lore import JsonLoreStore
from sinnema.infrastructure.llm.tools import (
    construir_tools,
    construir_tools_por_rol,
)
from tests.conftest import make_project, make_lore_entry


def test_tools_implementan_el_vocabulario_del_catalogo():
    proyecto = make_project()
    tools = construir_tools(proyecto, JsonLoreStore(root=None or "/tmp/lore-inexistente"))
    assert set(tools) == {"buscar_lore", "leer_formato"}


def test_buscar_lore_encuentra_terminos_del_proyecto(tmp_path):
    from pathlib import Path

    lore = JsonLoreStore(root=tmp_path)
    lore.save("sinnema", [
        make_lore_entry(term="modelo", chapter_id="ch-01"),
    ])
    proyecto = make_project()
    buscar = construir_tools(proyecto, lore)["buscar_lore"]
    resultado = buscar.invoke({"consulta": "modelo"})
    assert "modelo" in resultado and "ch-01" in resultado

    vacio = buscar.invoke({"consulta": "zzz-inexistente"})
    assert "Sin resultados" in vacio


def test_leer_formato_devuelve_las_cotas(tmp_path):
    from pathlib import Path

    proyecto = make_project()
    leer = construir_tools(proyecto, JsonLoreStore(root=tmp_path))["leer_formato"]
    cotas = leer.invoke({})
    assert "narration_target_words" in cotas


def test_construir_tools_por_rol_solo_roles_con_tools(tmp_path):
    proyecto = make_project(agentes={
        "scriptwriter": AgentConfig(tools=("buscar_lore", "leer_formato")),
        "critic": AgentConfig(),  # sin tools: fuera del resultado
    })
    por_rol = construir_tools_por_rol(proyecto, JsonLoreStore(root=tmp_path))
    assert set(por_rol) == {"scriptwriter"}
    assert [t.name for t in por_rol["scriptwriter"]] == ["buscar_lore", "leer_formato"]


def test_tool_fuera_del_registro_rechazada(tmp_path):
    proyecto = make_project(agentes={
        "scriptwriter": AgentConfig(tools=("buscar_lore",)),
    })
    # Defensa en profundidad: §3.13 ya lo rechaza al cargar el TOML; acá se
    # muta el spec (config congelada) para probar el guard del adaptador.
    object.__setattr__(proyecto.agentes["scriptwriter"], "tools", ("navegar_web",))
    with pytest.raises(ValueError, match="fuera del registro"):
        construir_tools_por_rol(proyecto, JsonLoreStore(root=tmp_path))
