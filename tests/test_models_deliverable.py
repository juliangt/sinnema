"""Tests de los contratos de salida (FinalScene, ApprovedEpisode, SeriesDeliverable)."""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from sinnema.domain.models import ApprovedEpisode, SeriesDeliverable
from sinnema.domain.services import assemble_episode

from conftest import make_adapted, make_audit, make_chapter, make_draft, make_package


def _episodio(indice: int = 1) -> ApprovedEpisode:
    capitulo = make_chapter(indice)
    borrador = make_draft(capitulo.chapter_id)
    return assemble_episode(
        chapter=capitulo,
        order_index=indice,
        draft=borrador,
        adapted=make_adapted(borrador),
        package=make_package(borrador),
        audit=make_audit(approved=True, score=9),
    )


def test_episodio_valido_por_defecto():
    episodio = _episodio()
    assert episodio.order_index == 1
    assert episodio.forced_acceptance is False
    assert episodio.scenes[0].image_prompt  # specs presentes


def test_episodio_con_escenas_no_secuenciales_rechazado():
    episodio = _episodio()
    datos = episodio.model_dump()
    datos["scenes"][5]["scene_number"] = 7
    with pytest.raises(ValidationError, match="secuenciales"):
        ApprovedEpisode(**datos)


def test_episodio_con_duracion_total_insuficiente_rechazado():
    episodio = _episodio()
    datos = episodio.model_dump()
    for escena in datos["scenes"]:
        escena["duration_seconds"] = 1.0  # 6 x 1 = 6 s < 10 s (piso universal)
    with pytest.raises(ValidationError, match="duración total"):
        ApprovedEpisode(**datos)


def test_escena_final_sin_prompt_de_imagen_rechazada():
    episodio = _episodio()
    datos = episodio.model_dump()
    datos["scenes"][0]["image_prompt"] = ""
    with pytest.raises(ValidationError):
        ApprovedEpisode(**datos)


def test_escena_final_con_transicion_invalida_rechazada():
    episodio = _episodio()
    datos = episodio.model_dump()
    datos["scenes"][0]["transition"] = "cruzado_de_disolvencia"
    with pytest.raises(ValidationError):
        ApprovedEpisode(**datos)


# --------------------------- SeriesDeliverable ---------------------------


def _entregable(**overrides) -> SeriesDeliverable:
    episodios = overrides.pop("episodes", [_episodio(1), _episodio(2)])
    datos = dict(
        project_id="sinnema",
        language="Español neutro latinoamericano",
        series_title="Serie de prueba sobre IA",
        topic="Tema de prueba suficientemente largo",
        audience="Adolescentes de 14 a 18 años",
        style_guide="Estética 3D isométrica tech vertical",
        total_chapters_planned=2,
        episodes=episodios,
        failed_chapters=[],
        average_quality_score=9.0,
    )
    datos.update(overrides)
    return SeriesDeliverable(**datos)


def test_entregable_valido_con_episodios_y_fallos():
    episodio = _episodio(1)
    fallido = _fallo("ch-02")
    entregable = _entregable(
        episodes=[episodio],
        failed_chapters=[fallido],
        average_quality_score=9.0,
    )
    assert len(entregable.episodes) == 1
    assert len(entregable.failed_chapters) == 1


def test_entregable_con_huecos_en_order_index_rechazado():
    episodios = [_episodio(1), _episodio(2)]
    episodios[1] = episodios[1].model_copy(update={"order_index": 3})
    with pytest.raises(ValidationError, match="order_index"):
        _entregable(episodes=episodios)


def test_entregable_con_capitulo_aprobado_y_descartado_rechazado():
    with pytest.raises(ValidationError, match="a la vez"):
        _entregable(failed_chapters=[_fallo("ch-01")])


def test_entregable_con_mas_reportes_que_planificados_rechazado():
    with pytest.raises(ValidationError, match="planificaron"):
        _entregable(
            episodes=[_episodio(1)],
            failed_chapters=[_fallo("ch-02"), _fallo("ch-03")],  # 3 reportes > 2 planificados
            average_quality_score=9.0,
        )


def test_entregable_con_promedio_incoherente_rechazado():
    with pytest.raises(ValidationError, match="average_quality_score"):
        _entregable(average_quality_score=5.0)


def test_entregable_sin_episodios_exige_promedio_cero():
    entregable = _entregable(
        episodes=[], failed_chapters=[_fallo("ch-01"), _fallo("ch-02")],
        average_quality_score=0.0,
    )
    assert entregable.average_quality_score == 0.0


def _fallo(chapter_id: str):
    from sinnema.domain.models import FailedChapterRecord

    return FailedChapterRecord(
        chapter_id=chapter_id,
        title="Capítulo descartado de prueba",
        reason="QA rechazó el borrador reiteradamente; reintentos agotados.",
        last_feedback="1. Corrige el ritmo del gancho inicial.",
    )
