"""Tests del caso de uso GenerateSeriesUseCase y del entregable final."""
from __future__ import annotations

import pytest

from sinnema.application.use_cases import GenerateSeriesUseCase, build_deliverable
from sinnema.domain.exceptions import DomainValidationError

from conftest import gateway_con_serie, make_project, make_request


def _use_case(gw, settings=None, **extra):
    return GenerateSeriesUseCase(gw, make_project(), settings, **extra)


def test_execute_devuelve_entregable_valido():
    use_case = _use_case(gateway_con_serie(num_chapters=2))
    entregable = use_case.execute(make_request(num_chapters=2))

    assert entregable.project_id == "sinnema"
    assert entregable.language
    assert entregable.total_chapters_planned == 2
    assert [e.order_index for e in entregable.episodes] == [1, 2]
    assert entregable.average_quality_score == 9.0
    assert len(entregable.lore_glossary) == 6
    assert entregable.failed_chapters == []


def test_execute_con_capitulos_fallidos_promedia_cero():
    from sinnema.application.settings import PipelineSettings
    from conftest import make_audit

    gw = gateway_con_serie(
        num_chapters=2,
        audits_por_capitulo=[[make_audit(approved=False, score=3)]] * 2,
    )
    settings = PipelineSettings(
        max_critique_attempts=1, retry_exhaustion_policy="skip_chapter"
    )
    use_case = _use_case(gw, settings)
    entregable = use_case.execute(make_request(num_chapters=2))

    assert entregable.episodes == []
    assert len(entregable.failed_chapters) == 2
    assert entregable.average_quality_score == 0.0


def test_stream_cede_snapshots_de_progreso():
    use_case = _use_case(gateway_con_serie(num_chapters=2))
    snapshots = list(use_case.stream(make_request(num_chapters=2)))
    # 1 plan + 6 nodos por capítulo x 2 capítulos (mínimo, sin revisiones).
    assert len(snapshots) >= 13


def test_build_deliverable_sin_estado_rechazado():
    with pytest.raises(DomainValidationError, match="plan de serie"):
        build_deliverable(None)


def test_build_deliverable_sin_plan_rechazado():
    with pytest.raises(DomainValidationError, match="plan de serie"):
        build_deliverable({"topic": "tema"})
