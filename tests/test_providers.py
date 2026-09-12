"""Tests de la fábrica de clientes LLM (specs, fallbacks y overrides de entorno)."""
from __future__ import annotations

import pytest

from sinnema.application.projects import AgentConfig
from sinnema.infrastructure.llm.gateway import build_gateway
from sinnema.infrastructure.llm.providers import (
    DEFAULT_CUSTOM_ROLE_SPEC,
    DEFAULT_ROLE_SPECS,
    _generation_kwargs,
    apply_env_overrides,
    build_provider_model,
    build_role_clients,
    default_role_spec,
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


# ----------------- Roles efectivos vía [flujo] (agentes dinámicos) -----------------


def test_build_gateway_con_flujo_declara_solo_los_roles_del_flujo(entorno_llm_limpio):
    """La lista de [flujo] manda sobre `activo`: los omitidos no reciben cliente."""
    from sinnema.application.projects import FlowSpec

    proyecto = make_project(
        flujo=FlowSpec(
            contexto=("continuity",),
            transformaciones=(),
            revisor=None,
            enriquecimiento=(),
            hasta="guion",
        ),
    )
    gateway = build_gateway(proyecto)
    assert set(gateway._structured) == {"planner", "continuity", "scriptwriter"}


def test_build_gateway_con_flujo_no_exige_clave_del_rol_omitido(
    entorno_llm_limpio, monkeypatch
):
    """Un rol fuera del flujo efectivo no exige clave de proveedor."""
    import sinnema.infrastructure.llm.providers as providers
    from sinnema.application.projects import FlowSpec

    # Sin claves de Google/Gemini el director técnico caería en fallback u
    # error; con [flujo] que lo omite, ni se le consulta.
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    proyecto = make_project(
        flujo=FlowSpec(
            contexto=("continuity",),
            transformaciones=("adapter",),
            revisor="critic",
            enriquecimiento=(),
            hasta="auditado",
        ),
    )
    gateway = build_gateway(proyecto)
    assert "technical_director" not in gateway._structured
    assert set(gateway._structured) == {
        "planner", "continuity", "scriptwriter", "adapter", "critic",
    }
    assert providers.provider_available("google") is False


def test_build_gateway_con_hasta_plan_solo_construye_el_planner(entorno_llm_limpio):
    from sinnema.application.projects import FlowSpec

    proyecto = make_project(
        flujo=FlowSpec(
            contexto=("continuity",),
            transformaciones=("adapter",),
            revisor="critic",
            enriquecimiento=("technical_director",),
            hasta="plan",
        ),
    )
    gateway = build_gateway(proyecto)
    assert set(gateway._structured) == {"planner"}


def test_build_gateway_sin_flujo_conserva_la_semantica_legacy(entorno_llm_limpio):
    """Sin [flujo], el comportamiento histórico: solo `activo` decide."""
    proyecto = make_project()  # todos los roles activos
    gateway = build_gateway(proyecto)
    assert set(gateway._structured) == {
        "planner", "continuity", "scriptwriter", "adapter", "critic",
        "technical_director",
    }


# ------------- top_p / max_tokens (spec-red-3d §3, Fase 1) -------------

@pytest.mark.parametrize(
    "proveedor, parametro_max",
    [
        ("anthropic", "max_tokens"),
        ("openai", "max_tokens"),
        ("google", "max_output_tokens"),
        ("ollama", "num_predict"),
    ],
)
def test_generation_kwargs_traduce_el_nombre_por_proveedor(proveedor, parametro_max):
    assert _generation_kwargs(proveedor, 0.9, 100) == {
        "top_p": 0.9, parametro_max: 100,
    }


def test_generation_kwargs_ausentes_no_se_pasan():
    """Sin override declarado rige el default del proveedor (spec §3)."""
    assert _generation_kwargs("openai", None, None) == {}
    assert _generation_kwargs("ollama", 0.5, None) == {"top_p": 0.5}


def test_build_provider_model_ollama_mapea_max_tokens_a_num_predict(entorno_llm_limpio):
    cliente = build_provider_model("ollama", "llama3.1", 0.5, top_p=0.9, max_tokens=512)
    assert cliente.top_p == 0.9
    assert cliente.num_predict == 512


def test_build_provider_model_sin_overlays_deja_los_defaults(entorno_llm_limpio):
    cliente = build_provider_model("ollama", "llama3.1", 0.5)
    assert cliente.top_p is None
    assert cliente.num_predict is None


def test_resolve_role_spec_propaga_los_overrides_del_proyecto(entorno_llm_limpio):
    resuelto = resolve_role_spec(
        _spec_de("scriptwriter"), AgentConfig(top_p=0.7, max_tokens=256)
    )
    assert resuelto.top_p == 0.7
    assert resuelto.max_tokens == 256
    assert resuelto.temperature == _spec_de("scriptwriter").temperature


def test_resolve_role_spec_sin_declaracion_queda_en_default(entorno_llm_limpio):
    resuelto = resolve_role_spec(_spec_de("scriptwriter"), AgentConfig())
    assert resuelto.top_p is None
    assert resuelto.max_tokens is None


def test_build_role_clients_lleva_los_overrides_al_constructor(entorno_llm_limpio):
    """La cadena completa: [agentes.<rol>] -> resolve -> constructor LangChain."""
    clientes = build_role_clients(overrides={
        "scriptwriter": AgentConfig(
            proveedor="ollama", modelo="llama3.1", top_p=0.6, max_tokens=128,
        ),
    })
    escritor = clientes["scriptwriter"]
    assert type(escritor).__name__ == "ChatOllama"
    assert escritor.top_p == 0.6
    assert escritor.num_predict == 128


def test_default_role_spec_cubre_el_registro_y_los_custom():
    assert default_role_spec("critic").model == "claude-3-5-sonnet-latest"
    generico = default_role_spec("fact_checker")  # rol custom cualquiera
    assert generico.model == DEFAULT_CUSTOM_ROLE_SPEC.model
    assert generico.fallback_providers == DEFAULT_CUSTOM_ROLE_SPEC.fallback_providers
