"""Tests del visor HTML del entregable (badges de alcance y adjuntos 1.1)."""
from __future__ import annotations

from sinnema.domain.services import assemble_episode
from sinnema.domain.models import SeriesDeliverable
from sinnema.infrastructure.api.viewer import render_deliverable_html

from conftest import (
    make_adapted,
    make_audit,
    make_chapter,
    make_draft,
    make_lore_entry,
    make_package,
    make_plan,
)


def _entregable(alcance: str = "produccion", con_lore: bool = True) -> dict:
    """Entregable 1.1 de una serie de 1 capítulo, ensamblado como en el grafo."""
    capitulo = make_chapter(1)
    draft = make_draft(capitulo.chapter_id)
    episodio = assemble_episode(
        chapter=capitulo,
        order_index=1,
        draft=draft,
        adapted=make_adapted(draft),
        package=make_package(draft),
        audit=make_audit(approved=True),
        adjuntos=[{"rol": "technical_director", "artefacto": {"chapter_id": "ch-01"}}],
    )
    return SeriesDeliverable(
        project_id="sinnema",
        language="Español neutro latinoamericano",
        series_title="Serie de prueba sobre IA",
        topic="Un tema de prueba suficientemente largo",
        audience="Audiencia de prueba",
        style_guide="Guía de estilo de prueba",
        alcance=alcance,
        total_chapters_planned=1,
        episodes=[episodio],
        average_quality_score=9.0,
        lore_glossary=[make_lore_entry()] if con_lore else [],
    ).model_dump(mode="json")


def test_viewer_muestra_el_badge_de_alcance():
    html = render_deliverable_html(_entregable("guion_final"))
    assert "alcance:" in html
    assert "guion final" in html


def test_viewer_renderiza_adjuntos_como_acordeones_json_por_rol():
    html = render_deliverable_html(_entregable())
    assert "<details" in html
    assert "technical_director" in html
    assert "render_deliverable" not in html  # el JSON viaja escapado, crudo


def test_viewer_sin_lore_omite_el_glosario():
    html = render_deliverable_html(_entregable(con_lore=False))
    assert "Glosario de continuidad" not in html


def test_viewer_con_alcance_plan_explica_la_ausencia_de_episodios():
    entregable = _entregable("plan")
    entregable["episodes"] = []
    entregable["average_quality_score"] = 0.0
    html = render_deliverable_html(entregable)
    assert "sin guiones ni episodios" in html


def test_viewer_episodio_sin_auditoria_lleva_el_badge_sin_qa():
    entregable = _entregable("auditado")
    entregable["episodes"][0]["audit"] = None
    entregable["episodes"][0]["forced_acceptance"] = False
    entregable["average_quality_score"] = 0.0
    html = render_deliverable_html(entregable)
    assert "sin auditoría" in html
