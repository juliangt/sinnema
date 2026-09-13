"""Tests del flujo por proyecto (``[flujo]``) y del alcance (``hasta``).

Cubren el parseo y las validaciones de composición/alcance (§9 de la spec),
el truncado por hito, la topología del grafo por configuración, el pipeline
de punta a punta por hito (con el doble del puerto LLM) y el entregable 1.2.
"""
from __future__ import annotations

import pytest

from sinnema.application.graph import build_pipeline_graph
from sinnema.application.ports import ROLE_PLANNER, ROLE_SCRIPTWRITER
from sinnema.application.projects import FlowSpec, con_hasta, project_from_dict, resolver_flujo
from sinnema.application.requests import SeriesRequest, build_initial_state
from sinnema.application.settings import PipelineSettings
from sinnema.application.use_cases import build_deliverable, limite_de_recursion
from sinnema.domain.constants import ALCANCES
from sinnema.domain.models.deliverable import ArtefactoAdjunto, SeriesDeliverable

from conftest import (
    FakeGateway,
    gateway_con_serie,
    make_audit,
    make_directives,
    make_draft,
    make_adapted,
    make_package,
    make_plan,
    make_project,
    make_request,
)


def _datos_proyecto(**extra):
    """Dict TOML de proyecto válido, con secciones opcionales por parámetro."""
    datos = {
        "proyecto": {
            "id": "flujo-test",
            "marca": "Flujo Test",
            "concepto": "micro-videos de prueba verticales",
            "tema_por_defecto": "Un tema de prueba suficientemente largo",
            "idioma": "Español",
        },
        "voz": {
            "audiencia": "Audiencia de prueba",
            "contexto_cultural": "Contexto cultural de prueba",
            "tono": "tono de prueba",
            "guia_de_estilo": "guía de prueba",
            "restricciones": "restricciones de prueba",
        },
        "visual": {
            "estilo_maestro": "3D render style with clean environment and lighting",
        },
    }
    datos.update(extra)
    return datos


# --------------------- parseo y validaciones (§9) ---------------------


def test_seccion_flujo_valida_se_parsea():
    spec = project_from_dict(_datos_proyecto(flujo={
        "contexto": ["continuity"],
        "transformaciones": ["adapter"],
        "revisor": "critic",
        "enriquecimiento": ["technical_director"],
        "hasta": "auditado",
    }))
    assert spec.flujo is not None
    assert spec.flujo.contexto == ("continuity",)
    assert spec.flujo.transformaciones == ("adapter",)
    assert spec.flujo.revisor == "critic"
    assert spec.flujo.enriquecimiento == ("technical_director",)
    assert spec.flujo.hasta == "auditado"
    assert spec.flujo.declarado is True


def test_sin_seccion_flujo_el_spec_queda_en_none():
    spec = project_from_dict(_datos_proyecto())
    assert spec.flujo is None
    flujo = resolver_flujo(spec)
    # Legacy: los seis roles en el orden histórico, sin flujo declarado.
    assert flujo.contexto == ("continuity",)
    assert flujo.transformaciones == ("adapter",)
    assert flujo.revisor == "critic"
    assert flujo.enriquecimiento == ("technical_director",)
    assert flujo.hasta == "produccion"
    assert flujo.declarado is False


@pytest.mark.parametrize("flujo,fragmento", [
    # Rol desconocido: el error lista los roles del registro.
    ({"contexto": ["inexistente"]}, "roles del registro"),
    # Rol repetido entre fases.
    ({"contexto": ["adapter"], "transformaciones": ["adapter"]}, "repetido"),
    # Rol estructural listado.
    ({"contexto": ["scriptwriter"]}, "estructural"),
    # activo = false en un rol listado: la lista manda.
    (
        {
            "contexto": ["continuity"],
            "agentes_extra": {"continuity": False},
        },
        "quítalo del flujo",
    ),
    # Vocabulario cerrado del hito.
    ({"hasta": "video_renderizado"}, "debe ser uno de"),
    # auditado sin revisor declarado.
    ({"hasta": "auditado", "enriquecimiento": []}, "exige declarar un 'revisor'"),
])
def test_flujo_invalido_reporta_el_problema(flujo, fragmento):
    datos = _datos_proyecto(flujo={k: v for k, v in flujo.items() if k != "agentes_extra"})
    if "agentes_extra" in flujo:
        datos["agentes"] = {
            rol: {"activo": activo} for rol, activo in flujo["agentes_extra"].items()
        }
    with pytest.raises(ValueError, match=fragmento):
        project_from_dict(datos)


def test_flujo_reporta_todos_los_problemas_de_una_vez():
    with pytest.raises(ValueError) as exc:
        project_from_dict(_datos_proyecto(flujo={
            "contexto": ["desconocido_uno"],
            "hasta": "auditado",  # además: sin revisor
        }))
    mensaje = str(exc.value)
    assert "desconocido_uno" in mensaje
    assert "revisor" in mensaje


def test_hasta_por_debajo_de_fases_declaradas_es_valido_y_trunca():
    """El flujo puede declararse completo; el hito decide qué corre."""
    spec = project_from_dict(_datos_proyecto(flujo={
        "contexto": ["continuity"],
        "transformaciones": ["adapter"],
        "revisor": "critic",
        "enriquecimiento": ["technical_director"],
        "hasta": "guion",
    }))
    efectivo = resolver_flujo(spec)
    assert efectivo.contexto == ("continuity",)
    assert efectivo.transformaciones == ()  # por debajo del hito: no corre
    assert efectivo.revisor is None
    assert efectivo.enriquecimiento == ()
    assert efectivo.hasta == "guion"


def test_truncado_por_hito_en_todos_los_niveles():
    completo = FlowSpec(
        contexto=("continuity",),
        transformaciones=("adapter",),
        revisor="critic",
        enriquecimiento=("technical_director",),
        hasta="produccion",
    )
    assert FlowSpec(hasta="plan").truncado().roles_completos() == (ROLE_PLANNER,)
    assert completo.truncado().__class__ is FlowSpec
    por_hito = {
        "plan": (),
        "guion": ("continuity", ROLE_SCRIPTWRITER),
        "guion_final": ("continuity", ROLE_SCRIPTWRITER, "adapter"),
        "auditado": ("continuity", ROLE_SCRIPTWRITER, "adapter", "critic"),
        "produccion": (
            "continuity", ROLE_SCRIPTWRITER, "adapter", "critic",
            "technical_director",
        ),
    }
    for hito, esperado in por_hito.items():
        truncado = completo.truncado() if hito == "produccion" else FlowSpec(
            contexto=("continuity",),
            transformaciones=("adapter",),
            revisor="critic",
            enriquecimiento=("technical_director",),
            hasta=hito,
        ).truncado()
        roles = truncado.roles_completos()
        for rol in esperado:
            assert rol in roles, hito
        if hito == "plan":
            assert roles == (ROLE_PLANNER,)


# ----------------------------- con_hasta (CLI) -----------------------------


def test_con_hasta_sobrescribe_el_hito_del_proyecto():
    spec = make_project()
    ajustado = con_hasta(spec, "guion")
    assert resolver_flujo(ajustado).hasta == "guion"
    assert resolver_flujo(spec).hasta == "produccion"  # el original no cambia


def test_con_hasta_vocabulary_invalido_es_error():
    with pytest.raises(ValueError, match="debe ser uno de"):
        con_hasta(make_project(), "render")


def test_con_hasta_por_encima_de_lo_declarado_es_error_accionable():
    spec = project_from_dict(_datos_proyecto(flujo={"hasta": "guion_final"}))
    with pytest.raises(ValueError, match="revisor"):
        con_hasta(spec, "produccion")


# ----------------------------- límite de recursión -----------------------------


def test_el_limite_de_recursion_crece_con_el_flujo():
    basico = FlowSpec(revisor="critic", hasta="produccion")
    largo = FlowSpec(
        contexto=("continuity",),
        transformaciones=("adapter",),
        revisor="critic",
        enriquecimiento=("technical_director",),
        hasta="produccion",
    )
    assert limite_de_recursion(largo, 3, 2) > limite_de_recursion(basico, 3, 2)


# ----------------------------- grafo por configuración -----------------------------


class _GatewayNulo:
    def generate(self, *_a, **_k):  # pragma: no cover
        raise RuntimeError("El diagrama no ejecuta el pipeline.")


def _mermaid_de(spec):
    grafo = build_pipeline_graph(_GatewayNulo(), spec, PipelineSettings())
    return grafo.get_graph().draw_mermaid()


def test_topologia_default_mantiene_los_seis_nodos():
    mermaid = _mermaid_de(make_project())
    for nodo in ("plan_series", "continuity_master", "scriptwriter",
                 "persona_adapter", "chief_critic", "technical_director",
                 "commit_episode", "fail_chapter"):
        assert nodo in mermaid


def test_topologia_guion_final_omite_compuerta_y_enriquecedores():
    spec = make_project(flujo=FlowSpec(
        contexto=("continuity",),
        transformaciones=("adapter",),
        revisor="critic",
        enriquecimiento=("technical_director",),
        hasta="guion_final",
    ))
    mermaid = _mermaid_de(spec)
    assert "scriptwriter" in mermaid and "persona_adapter" in mermaid
    assert "chief_critic" not in mermaid
    assert "technical_director" not in mermaid
    assert "fail_chapter" not in mermaid


def test_topologia_plan_sin_bucle_de_capitulos():
    spec = make_project(flujo=FlowSpec(hasta="plan"))
    mermaid = _mermaid_de(spec)
    assert "consolidar_plan" in mermaid
    assert "scriptwriter" not in mermaid
    assert "commit_episode" not in mermaid


# ----------------------------- pipeline por hito -----------------------------


def _correr(spec, gw, num_chapters: int = 2):
    request = SeriesRequest(project=spec, num_chapters=num_chapters)
    request.validate()
    grafo = build_pipeline_graph(gw, spec, PipelineSettings(max_critique_attempts=2))
    final = None
    for snapshot in grafo.stream(
        build_initial_state(request), config={"recursion_limit": 300},
        stream_mode="values",
    ):
        final = snapshot
    return final


def test_corrida_hasta_plan_entrega_outline_sin_episodios():
    spec = make_project(flujo=FlowSpec(hasta="plan"))
    gw = FakeGateway()
    gw.add(ROLE_PLANNER, [make_plan(num_chapters=2)])
    final = _correr(spec, gw, num_chapters=2)

    assert gw.calls == [ROLE_PLANNER]  # solo el planificador trabaja
    entregable = build_deliverable(final)
    assert entregable.alcance == "plan"
    assert entregable.episodes == []
    assert entregable.total_chapters_planned == 2
    assert entregable.series_title


def test_corrida_hasta_guion_final_entrega_sin_specs_de_video():
    spec = make_project(flujo=FlowSpec(
        contexto=("continuity",),
        transformaciones=("adapter",),
        hasta="guion_final",
    ))
    gw = gateway_con_serie(num_chapters=2)
    final = _correr(spec, gw)

    assert gw.calls.count("critic") == 0
    assert gw.calls.count("technical_director") == 0
    episodios = final["completed_episodes"]
    assert len(episodios) == 2
    assert all(e.technical is None for e in episodios)
    assert all(e.audit is None for e in episodios)
    entregable = build_deliverable(final)
    assert entregable.alcance == "guion_final"
    assert len(entregable.episodes) == 2


def test_corrida_sin_flujo_conserva_el_pipeline_completo():
    gw = gateway_con_serie(num_chapters=1)
    final = _correr(make_project(), gw, num_chapters=1)
    for rol, esperado in [
        ("planner", 1), ("continuity", 1), ("scriptwriter", 1),
        ("adapter", 1), ("critic", 1), ("technical_director", 1),
    ]:
        assert gw.calls.count(rol) == esperado, rol
    entregable = build_deliverable(final)
    assert entregable.alcance == "produccion"
    assert entregable.schema_version == "1.2"


# ----------------------------- entregable 1.2 -----------------------------


def test_adjunto_de_artefacto_modelo_basico():
    adjunto = ArtefactoAdjunto(rol="technical_director", artefacto={"specs": []})
    assert adjunto.rol == "technical_director"
    assert adjunto.artefacto == {"specs": []}


def test_invariante_fallos_exigen_compuerta():
    gw = gateway_con_serie(num_chapters=1)
    final = _correr(make_project(), gw, num_chapters=1)
    episodios = final["completed_episodes"]
    assert episodios  # sanity: la serie feliz produce episodios

    base = {
        "project_id": "sinnema",
        "language": "Español",
        "series_title": "T",
        "topic": "tema de prueba",
        "audience": "audiencia",
        "style_guide": "guía",
        "total_chapters_planned": 2,
        "episodes": episodios,
    }
    # El promedio declarado debe coincidir con el recalculado (solo episodios
    # con auditoría aportan score).
    con_auditoria = [e.audit.overall_score for e in episodios if e.audit]
    promedio = round(sum(con_auditoria) / len(con_auditoria), 2)
    # Con episodios y sin fallos, cualquier alcance es coherente.
    entregable = SeriesDeliverable(**base, average_quality_score=promedio, alcance="guion")
    assert entregable.alcance == "guion"

    # Con fallos, un alcance por debajo de la compuerta es inválido.
    from sinnema.domain.models import FailedChapterRecord
    fallo = FailedChapterRecord(chapter_id="ch-99", title="t", reason="x" * 20)
    with pytest.raises(ValueError, match="compuerta"):
        SeriesDeliverable(
            **base, average_quality_score=promedio,
            failed_chapters=[fallo], alcance="guion",
        )
    # Y con el alcance correcto, pasa.
    ok = SeriesDeliverable(
        **base, average_quality_score=promedio,
        failed_chapters=[fallo], alcance="auditado",
    )
    assert ok.failed_chapters[0].chapter_id == "ch-99"


def test_vocabulario_de_alcances_ordenado():
    assert ALCANCES == ("plan", "guion", "guion_final", "auditado", "produccion")
