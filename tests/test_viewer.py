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


# ------------- Keyframes por escena (entregable 1.2, §9.2, Fase 5b) -------------


MANIFEST = {
    "proveedor": "gemini",
    "modelo": "gemini-2.0-flash-exp",
    "seed": 7,
    "prompt_final": "A friendly young guide with short dark hair in a neon lab",
    "anclas_usadas": [["protagonista", 1, "hero_portrait"]],
    "parametros": {"aspect_ratio": "9:16"},
    "id_externo": "fake-1",
    "creado_en": "2026-09-12T00:00:00+00:00",
}

INFORME_OK = {
    "escena": 1, "ancla_id": "protagonista", "metrica": "cara_coseno",
    "score": 0.81, "umbral": 0.35, "aprueba": True, "detalle": "",
}


def _entregable_con_media() -> dict:
    """Entregable 1.2: la escena 1 lleva keyframe (imagen + manifest + QA)
    y las anclas citadas por su spec visual; la escena 2 queda sin media."""
    entregable = _entregable()
    escenas = entregable["episodes"][0]["scenes"]
    escenas[0]["anclas"] = [
        {"ancla_id": "protagonista", "roles": ["hero_portrait", "expression_sheet"]},
    ]
    escenas[0]["keyframe"] = {
        "archivo": "mi-show/ch-01/escena_1.png",
        "manifest": MANIFEST,
        "qa": [INFORME_OK],
    }
    return entregable


def test_viewer_muestra_el_keyframe_con_su_ruta_de_serving():
    html = render_deliverable_html(_entregable_con_media())
    assert "/api/media/mi-show/ch-01/escena_1.png" in html
    assert "manifest (procedencia)" in html
    assert "gemini-2.0-flash-exp" in html  # el proveedor/modelo del manifest
    # El JSON viaja crudo PERO escapado (mismo patrón que los adjuntos 1.1).
    assert "&quot;seed&quot;: 7" in html


def test_viewer_renderiza_el_informe_qa_del_keyframe():
    html = render_deliverable_html(_entregable_con_media())
    assert "QA visual" in html
    assert "cara_coseno" in html
    assert "0.81" in html


def test_viewer_lista_las_anclas_citadas_por_la_escena():
    html = render_deliverable_html(_entregable_con_media())
    assert "@protagonista" in html
    assert "hero_portrait" in html
    assert "expression_sheet" in html


def test_viewer_keyframe_rechazado_por_qa_lleva_el_badge():
    entregable = _entregable_con_media()
    keyframe = entregable["episodes"][0]["scenes"][0]["keyframe"]
    keyframe["qa"] = [dict(INFORME_OK, aprueba=False, score=0.1)]
    html = render_deliverable_html(entregable)
    assert "rechaza" in html


def test_viewer_sin_keyframe_no_renderiza_media():
    """Paridad: un entregable sin media no menciona serving ni QA visual."""
    html = render_deliverable_html(_entregable())
    assert "/api/media/" not in html
    assert "QA visual" not in html
