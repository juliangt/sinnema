"""Tests del registro de agentes y de la fábrica de nodos.

El registro es la fuente única del catálogo de agentes: aquí se pinnea su
consistencia con los catálogos históricos (ROLE_SCHEMAS, ROLES_CONFIGURABLES),
la semántica de tipos y el comportamiento de ``make_agent_node``.
"""
from __future__ import annotations

import pytest

from sinnema.application.graph import make_agent_node
from sinnema.application.ports import (
    ROLE_ADAPTER,
    ROLE_CONTINUITY,
    ROLE_CRITIC,
    ROLE_DIRECTOR,
    ROLE_PLANNER,
    ROLE_SCRIPTWRITER,
    ROLE_SCHEMAS,
    NullAuditTrail,
)
from sinnema.application.projects import ROLES_CONFIGURABLES, AgentConfig
from sinnema.application.prompts import build_role_system_prompts as build_desde_prompts
from sinnema.application.registry import (
    AGENT_REGISTRY,
    build_role_system_prompts,
    capitulo_actual,
    definicion,
    roles_de_tipo,
)

from conftest import (
    FakeGateway,
    make_directives,
    make_draft,
    make_plan,
    make_project,
)


# ----------------------------- catálogo -----------------------------


def test_el_registro_cubre_exactamente_los_roles_conocidos():
    assert set(AGENT_REGISTRY) == set(ROLE_SCHEMAS)
    assert set(AGENT_REGISTRY) == set(ROLES_CONFIGURABLES)


def test_cada_definicion_declara_el_esquema_de_su_rol():
    for rol, d in AGENT_REGISTRY.items():
        assert d.esquema is ROLE_SCHEMAS[rol]
        assert d.rol == rol


def test_tipos_nodos_y_esencialidad_del_catalogo():
    esperado = {
        ROLE_PLANNER: ("serie", True, "plan_series"),
        ROLE_CONTINUITY: ("contexto", False, "continuity_master"),
        ROLE_SCRIPTWRITER: ("escritor", True, "scriptwriter"),
        ROLE_ADAPTER: ("transformador", False, "persona_adapter"),
        ROLE_CRITIC: ("revisor", False, "chief_critic"),
        ROLE_DIRECTOR: ("enriquecedor", False, "technical_director"),
    }
    for rol, (tipo, esencial, nodo) in esperado.items():
        d = definicion(rol)
        assert d.tipo == tipo
        assert d.esencial is esencial
        # Nombres de nodo estables: compatibilidad con el checkpointer.
        assert d.nodo == nodo


def test_roles_de_tipo_filtra_por_fase():
    assert roles_de_tipo("serie") == [ROLE_PLANNER]
    assert roles_de_tipo("contexto") == [ROLE_CONTINUITY]
    assert roles_de_tipo("escritor") == [ROLE_SCRIPTWRITER]
    assert roles_de_tipo("transformador") == [ROLE_ADAPTER]
    assert roles_de_tipo("revisor") == [ROLE_CRITIC]
    assert roles_de_tipo("enriquecedor") == [ROLE_DIRECTOR]


def test_definicion_desconocida_da_error_accionable():
    with pytest.raises(KeyError, match="no está en el registro"):
        definicion("inexistente")


def test_capitulo_actual_sin_plan_falla_en_voz_alta():
    with pytest.raises(RuntimeError, match="plan de serie"):
        capitulo_actual({"series_plan": None})


# ----------------------------- prompts -----------------------------


def test_prompts_desde_prompts_y_desde_registro_son_identicos():
    proyecto = make_project()
    assert build_desde_prompts(proyecto) == build_role_system_prompts(proyecto)


def test_system_prompt_incluye_reglas_del_proyecto():
    proyecto = make_project(
        agentes={"critic": AgentConfig(reglas=("Cerrar con dato verificable",))}
    )
    prompts = build_role_system_prompts(proyecto)
    assert "REGLAS ADICIONALES DEL PROYECTO" in prompts[ROLE_CRITIC]
    assert "Cerrar con dato verificable" in prompts[ROLE_CRITIC]
    # Los roles sin reglas no llevan el bloque.
    assert "REGLAS ADICIONALES" not in prompts[ROLE_PLANNER]


# ----------------------------- make_agent_node -----------------------------


def test_nodo_generado_produce_su_slot_y_llama_a_su_rol():
    proyecto = make_project()
    d = definicion(ROLE_CONTINUITY)
    gw = FakeGateway()
    directivas = make_directives()
    gw.add(ROLE_CONTINUITY, [directivas])
    nodo = make_agent_node(
        d, gw, proyecto, build_role_system_prompts(proyecto), NullAuditTrail()
    )
    estado = {
        "series_plan": make_plan(1),
        "current_chapter_index": 0,
        "lore_entries": [],
    }
    actualizacion = nodo(estado)
    assert actualizacion == {"continuity_directives": directivas}
    assert gw.calls == [ROLE_CONTINUITY]


def test_nodo_de_agente_desactivado_se_cortocircuita_sin_llamar_al_llm():
    proyecto = make_project(agentes={"adapter": AgentConfig(activo=False)})
    d = definicion(ROLE_ADAPTER)
    gw = FakeGateway()
    nodo = make_agent_node(
        d, gw, proyecto, build_role_system_prompts(proyecto), NullAuditTrail()
    )
    draft = make_draft("ch-01")
    estado = {
        "series_plan": make_plan(1),
        "current_chapter_index": 0,
        "draft_script": draft,
    }
    actualizacion = nodo(estado)
    assert gw.calls == []  # adaptación identidad: sin LLM
    assert actualizacion["adapted_script"].adapted_title == draft.title


def test_nodo_del_escritor_limpia_el_feedback_pendiente():
    proyecto = make_project()
    d = definicion(ROLE_SCRIPTWRITER)
    gw = FakeGateway()
    borrador = make_draft("ch-01")
    gw.add(ROLE_SCRIPTWRITER, [borrador])
    nodo = make_agent_node(
        d, gw, proyecto, build_role_system_prompts(proyecto), NullAuditTrail()
    )
    estado = {
        "series_plan": make_plan(1),
        "current_chapter_index": 0,
        "continuity_directives": None,
        "pending_feedback": "corrige el hook",
        "qa_verdict": None,
    }
    actualizacion = nodo(estado)
    assert actualizacion["draft_script"] is borrador
    assert actualizacion["pending_feedback"] is None
    assert actualizacion["qa_verdict"] is None
