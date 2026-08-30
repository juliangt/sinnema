"""Tests de la fábrica de clientes LLM (specs, fallbacks y overrides de entorno)."""
from __future__ import annotations

import pytest

from sinnema.infrastructure.llm.providers import (
    DEFAULT_ROLE_SPECS,
    apply_env_overrides,
    build_role_clients,
    provider_available,
)

from conftest import entorno_llm_limpio  # noqa: F401 - fixture usada vía parámetro


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
