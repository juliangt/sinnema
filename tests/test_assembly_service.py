"""Tests del servicio de ensamblaje y validación cruzada de artefactos."""
from __future__ import annotations

import pytest

from sinnema.domain.exceptions import DomainValidationError
from sinnema.domain.services import (
    assemble_episode,
    build_failed_record,
    validate_adaptation_matches_draft,
    validate_package_matches_draft,
    validate_plan_size,
)

from conftest import (
    make_adapted,
    make_audit,
    make_chapter,
    make_directives,
    make_draft,
    make_package,
    make_plan,
)


def _artefactos(chapter_id: str = "ch-01"):
    borrador = make_draft(chapter_id)
    return borrador, make_adapted(borrador), make_package(borrador)


def test_ensamblaje_prefiere_narracion_adaptada():
    borrador, adaptado, paquete = _artefactos()
    episodio = assemble_episode(
        chapter=make_chapter(1),
        order_index=1,
        draft=borrador,
        adapted=adaptado,
        package=paquete,
        audit=make_audit(approved=True),
    )
    assert episodio.scenes[0].narration == adaptado.adapted_scenes[0].narration
    assert episodio.scenes[0].on_screen_text == adaptado.adapted_scenes[0].on_screen_text
    assert episodio.scenes[0].duration_seconds == borrador.scenes[0].duration_seconds
    assert episodio.forced_acceptance is False


def test_ensamblaje_con_rechazo_marca_aceptacion_forzada():
    borrador, adaptado, paquete = _artefactos()
    episodio = assemble_episode(
        chapter=make_chapter(1),
        order_index=1,
        draft=borrador,
        adapted=adaptado,
        package=paquete,
        audit=make_audit(approved=False),
    )
    assert episodio.forced_acceptance is True


def test_ensamblaje_con_chapter_id_incoherente_rechazado():
    borrador, adaptado, paquete = _artefactos("ch-02")  # capítulo en curso: ch-01
    with pytest.raises(DomainValidationError, match="mezclados"):
        assemble_episode(
            chapter=make_chapter(1),
            order_index=1,
            draft=borrador,
            adapted=adaptado,
            package=paquete,
            audit=make_audit(approved=True),
        )


def test_adaptacion_que_no_cubre_las_escenas_rechazada():
    borrador = make_draft(num_scenes=7)  # 1..7
    adaptado = make_adapted(make_draft())  # cubre 1..6
    with pytest.raises(DomainValidationError, match="no conserva la numeración"):
        validate_adaptation_matches_draft(borrador, adaptado)


def test_paquete_que_no_cubre_las_escenas_rechazado():
    borrador = make_draft(num_scenes=7)  # 1..7
    paquete = make_package(make_draft())  # specs 1..6
    with pytest.raises(DomainValidationError, match="no cubre exactamente"):
        validate_package_matches_draft(borrador, paquete)


def test_adaptacion_con_id_distinto_rechazada():
    borrador = make_draft("ch-01")
    adaptado = make_adapted(make_draft("ch-02"))
    with pytest.raises(DomainValidationError, match="mezclados"):
        validate_adaptation_matches_draft(borrador, adaptado)


def test_tamano_de_plan_incoherente_rechazado():
    plan = make_plan(2)
    with pytest.raises(DomainValidationError, match="solicitaron 3"):
        validate_plan_size(plan, expected_chapters=3)
    validate_plan_size(plan, expected_chapters=2)  # coherente: no lanza


def test_registro_de_fallo_con_y_sin_dictamen():
    capitulo = make_chapter(1)
    con_dictamen = build_failed_record(
        chapter=capitulo, max_attempts=2, audit=make_audit(approved=False, score=3)
    )
    assert "QA rechazó el borrador 2 veces" in con_dictamen.reason
    assert "3/10" in con_dictamen.reason
    assert con_dictamen.last_feedback != ""

    sin_dictamen = build_failed_record(chapter=capitulo, max_attempts=2, audit=None)
    assert "n/d" in sin_dictamen.reason
    assert sin_dictamen.last_feedback == ""
