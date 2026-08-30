"""Tests de la fábrica de clientes LLM (specs, fallbacks y overrides de entorno)."""
from __future__ import annotations

import pytest

from sinnema.application.projects import AgentConfig
from sinnema.infrastructure.llm.gateway import build_gateway
from sinnema.infrastructure.llm.providers import (
    DEFAULT_ROLE_SPECS,
    apply_env_overrides,
    build_role_clients,
    provider_available,
    resolve_role_spec,
)

from conftest import entorno_llm_limpio, make_project  # noqa: F401 - fixture usada vía parámetro


def test_proveedor_desconocido_no_esta_disponible():
    assert provider_available("proveedor-fantasma") is False


def test_sin_credenciales_todo_resuelve_a_ollama(entorno_llm_limpio):
    clientes = build_role_clients()
    assert set(clientes) == {spec.role for spec in DEFAULT_ROLE_SPECS}
    assert all(
        type(cliente).__name__ == "ChatOllama" for cliente in clientes.values()
    )


def test_solo_con_clave_openai_todo_resuelve_a_openai(entorno_llm_limpio, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    clientes = build_role_clients()
    assert all(type(cliente).__name__ == "ChatOpenAI" for cliente in clientes.values())


def test_override_por_rol_gana_al_default(entorno_llm_limpio, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("LLM_PROVIDER_SCRIPTWRITER", "ollama")
    monkeypatch.setenv("LLM_MODEL_SCRIPTWRITER", "llama3.1")
    clientes = build_role_clients()
    assert type(clientes["scriptwriter"]).__name__ == "ChatOllama"
    assert type(clientes["adapter"]).__name__ == "ChatOpenAI"


def test_override_de_modelo_se_aplica(entorno_llm_limpio, monkeypatch):
    monkeypatch.setenv("LLM_MODEL_CRITIC", "mi-modelo-custom")
    spec = next(s for s in DEFAULT_ROLE_SPECS if s.role == "critic")
    assert apply_env_overrides(spec).model == "mi-modelo-custom"


def test_sin_proveedor_disponible_error_accionable(
    entorno_llm_limpio, monkeypatch
):
    import sinnema.infrastructure.llm.providers as providers

    monkeypatch.setattr(providers, "provider_available", lambda proveedor: False)
    with pytest.raises(RuntimeError, match="LLM_PROVIDER_PLANNER"):
        build_role_clients()


# ------------------- Overrides por proyecto ([agentes.<rol>]) -------------------


def _spec_de(rol):
    return next(s for s in DEFAULT_ROLE_SPECS if s.role == rol)


def test_override_de_proyecto_gana_a_entorno_y_default(entorno_llm_limpio, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("LLM_MODEL_SCRIPTWRITER", "modelo-de-entorno")
    config = AgentConfig(modelo="modelo-del-proyecto", temperatura=0.5)
    resuelto = resolve_role_spec(_spec_de("scriptwriter"), config)
    assert resuelto.model == "modelo-del-proyecto"
    assert resuelto.temperature == 0.5


def test_entorno_gana_a_default_cuando_el_proyecto_no_declara(entorno_llm_limpio, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("LLM_MODEL_SCRIPTWRITER", "modelo-de-entorno")
    resuelto = resolve_role_spec(_spec_de("scriptwriter"), AgentConfig())
    assert resuelto.model == "modelo-de-entorno"
    assert resuelto.temperature == _spec_de("scriptwriter").temperature


def test_proyecto_puede_cambiar_proveedor(entorno_llm_limpio):
    clientes = build_role_clients(
        overrides={"scriptwriter": AgentConfig(proveedor="ollama", modelo="llama3.1")}
    )
    assert type(clientes["scriptwriter"]).__name__ == "ChatOllama"


def test_solo_roles_no_incluye_los_desactivados(entorno_llm_limpio):
    clientes = build_role_clients(solo_roles=["planner", "scriptwriter"])
    assert set(clientes) == {"planner", "scriptwriter"}


def test_build_gateway_con_proyecto_filtra_roles_inactivos(entorno_llm_limpio):
    proyecto = make_project(
        agentes={
            "critic": AgentConfig(activo=False),
            "technical_director": AgentConfig(activo=False),
        }
    )
    gateway = build_gateway(proyecto)
    assert set(gateway._structured) == {
        "planner", "continuity", "scriptwriter", "adapter",
    }
