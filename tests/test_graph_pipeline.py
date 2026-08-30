"""Tests de integración del grafo con un doble del puerto LLM.

Cubren la topología, el ciclo de crítica (revise/approve), las políticas de
agotamiento (force_accept / skip_chapter) y las validaciones cruzadas que
los nodos aplican tras cada generación.
"""
from __future__ import annotations

import pytest

from sinnema.application.graph import build_pipeline_graph
from sinnema.application.projects import AgentConfig
from sinnema.application.requests import build_initial_state
from sinnema.application.settings import PipelineSettings
from sinnema.domain.exceptions import DomainValidationError

from conftest import (
    FakeGateway,
    gateway_con_serie,
    make_adapted,
    make_audit,
    make_directives,
    make_draft,
    make_package,
    make_plan,
    make_project,
    make_request,
)


def ejecutar_grafo(gateway, settings=None, request=None):
    request = request or make_request()
    grafo = build_pipeline_graph(
        gateway, request.project, settings or PipelineSettings()
    )
    final = None
    for snapshot in grafo.stream(
        build_initial_state(request),
        config={"recursion_limit": 200},
        stream_mode="values",
    ):
        final = snapshot
    return final


def test_serie_feliz_completa_dos_capitulos():
    gw = gateway_con_serie(num_chapters=2)
    final = ejecutar_grafo(gw)

    episodios = final["completed_episodes"]
    assert [e.order_index for e in episodios] == [1, 2]
    assert all(not e.forced_acceptance for e in episodios)
    assert final["failed_chapters"] == []

    # Lore acumulado: 2 conceptos + 1 término nuevo por capítulo = 6 entradas.
    assert len(final["lore_entries"]) == 6

    # Cada rol se invocó exactamente una vez por capítulo.
    for rol, esperado in [
        ("planner", 1),
        ("continuity", 2),
        ("scriptwriter", 2),
        ("adapter", 2),
        ("critic", 2),
        ("technical_director", 2),
    ]:
        assert gw.calls.count(rol) == esperado, f"rol {rol}"


def test_ciclo_de_critica_rechaza_y_revisa_hasta_aprobar():
    gw = gateway_con_serie(
        num_chapters=2,
        audits_por_capitulo=[
            [make_audit(approved=False, score=4), make_audit(approved=True, score=9)],
            [make_audit(approved=True, score=9)],
        ],
    )
    final = ejecutar_grafo(gw, settings=PipelineSettings(max_critique_attempts=2))

    # El capítulo 1 necesitó 2 pasadas de guionista/crítico; el 2 solo una.
    assert gw.calls.count("scriptwriter") == 3
    assert gw.calls.count("critic") == 3
    episodio_1 = final["completed_episodes"][0]
    assert episodio_1.audit.approved is True
    assert episodio_1.forced_acceptance is False


def test_agotamiento_con_force_accept_acepta_forzadamente():
    gw = gateway_con_serie(
        num_chapters=2,
        audits_por_capitulo=[[make_audit(approved=False, score=4)]] * 2,
    )
    final = ejecutar_grafo(
        gw, settings=PipelineSettings(max_critique_attempts=1, retry_exhaustion_policy="force_accept")
    )

    assert len(final["completed_episodes"]) == 2
    assert all(e.forced_acceptance for e in final["completed_episodes"])
    assert all(e.audit.approved is False for e in final["completed_episodes"])


def test_agotamiento_con_skip_chapter_descarta_el_capitulo():
    gw = gateway_con_serie(
        num_chapters=2,
        audits_por_capitulo=[[make_audit(approved=False, score=3)]] * 2,
    )
    final = ejecutar_grafo(
        gw, settings=PipelineSettings(max_critique_attempts=1, retry_exhaustion_policy="skip_chapter")
    )

    assert final["completed_episodes"] == []
    assert [f.chapter_id for f in final["failed_chapters"]] == ["ch-01", "ch-02"]
    assert "reintentos agotados" in final["failed_chapters"][0].reason
    # Los capítulos fallidos no aportan lore nuevo.
    assert final["lore_entries"] == []
    assert final["current_chapter_index"] == 2


def test_plan_con_tamano_incorrecto_falla_la_ejecucion():
    gw = gateway_con_serie(num_chapters=2)  # el plan trae 2 capítulos...
    with pytest.raises(DomainValidationError, match="solicitaron 3"):
        ejecutar_grafo(gw, request=make_request(num_chapters=3))  # ...pero se piden 3


def test_adaptacion_con_id_incoherente_falla_la_ejecucion():
    plan = make_plan(1)
    draft = make_draft("ch-01")
    gw = FakeGateway()
    gw.add("planner", [plan])
    gw.add("continuity", [make_directives()])
    gw.add("scriptwriter", [draft])
    gw.add("adapter", [make_adapted(draft).model_copy(update={"chapter_id": "ch-99"})])
    gw.add("critic", [make_audit(approved=True)])
    gw.add("technical_director", [make_package(draft)])

    with pytest.raises(DomainValidationError, match="mezclados"):
        ejecutar_grafo(gw, request=make_request(num_chapters=1))


def test_paquete_desalineado_falla_la_ejecucion():
    plan = make_plan(1)
    draft = make_draft("ch-01", num_scenes=7)
    gw = FakeGateway()
    gw.add("planner", [plan])
    gw.add("continuity", [make_directives()])
    gw.add("scriptwriter", [draft])
    gw.add("adapter", [make_adapted(draft)])
    gw.add("critic", [make_audit(approved=True)])
    gw.add("technical_director", [make_package(make_draft("ch-01"))])  # specs 1..6

    with pytest.raises(DomainValidationError, match="no cubre exactamente"):
        ejecutar_grafo(gw, request=make_request(num_chapters=1))


# --------------------- Agentes desactivados por proyecto ---------------------


def _proyecto_con_agentes(**agentes):
    return make_project(agentes=agentes)


def test_continuidad_desactivada_avanza_sin_directivas_y_extrae_lore_de_conceptos():
    proyecto = _proyecto_con_agentes(continuity=AgentConfig(activo=False))
    gw = gateway_con_serie(num_chapters=2)
    final = ejecutar_grafo(gw, request=make_request(project=proyecto))

    assert gw.calls.count("continuity") == 0
    assert gw.calls.count("scriptwriter") == 2  # el guionista tolera directivas None
    # El lore sigue creciendo: 2 conceptos clave por capítulo.
    assert len(final["lore_entries"]) == 4
    assert len(final["completed_episodes"]) == 2


def test_adapter_desactivado_pasa_el_borrador_con_adaptacion_identidad():
    proyecto = _proyecto_con_agentes(adapter=AgentConfig(activo=False))
    gw = gateway_con_serie(num_chapters=2)
    final = ejecutar_grafo(gw, request=make_request(project=proyecto))

    assert gw.calls.count("adapter") == 0
    episodios = final["completed_episodes"]
    # Adaptación identidad: el título del episodio es el del borrador original.
    assert all(e.title == "Título de prueba del borrador" for e in episodios)
    assert all(e.audit.approved for e in episodios)  # el crítico audita igual


def test_critico_desactivado_aprueba_sin_dictamen_y_sin_ciclo_de_critica():
    proyecto = _proyecto_con_agentes(critic=AgentConfig(activo=False))
    gw = gateway_con_serie(num_chapters=2)
    final = ejecutar_grafo(gw, request=make_request(project=proyecto))

    assert gw.calls.count("critic") == 0
    # Sin crítico no hay ciclo: una sola pasada de guionista por capítulo.
    assert gw.calls.count("scriptwriter") == 2
    episodios = final["completed_episodes"]
    assert all(e.audit is None for e in episodios)
    assert all(not e.forced_acceptance for e in episodios)


def test_director_tecnico_desactivado_entrega_episodios_sin_specs_visuales():
    proyecto = _proyecto_con_agentes(technical_director=AgentConfig(activo=False))
    gw = gateway_con_serie(num_chapters=2)
    final = ejecutar_grafo(gw, request=make_request(project=proyecto))

    assert gw.calls.count("technical_director") == 0
    episodios = final["completed_episodes"]
    assert all(e.technical is None for e in episodios)
    assert all(s.image_prompt == "" for e in episodios for s in e.scenes)


def test_pipeline_minimo_solo_planner_y_guionista():
    """Los cuatro roles opcionales apagados: queda la columna vertebral."""
    proyecto = _proyecto_con_agentes(
        continuity=AgentConfig(activo=False),
        adapter=AgentConfig(activo=False),
        critic=AgentConfig(activo=False),
        technical_director=AgentConfig(activo=False),
    )
    gw = gateway_con_serie(num_chapters=2)
    final = ejecutar_grafo(gw, request=make_request(project=proyecto))

    roles_invocados = set(gw.calls)
    assert roles_invocados == {"planner", "scriptwriter"}
    assert len(final["completed_episodes"]) == 2
    episodio = final["completed_episodes"][0]
    assert episodio.audit is None and episodio.technical is None
