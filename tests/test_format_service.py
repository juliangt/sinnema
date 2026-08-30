"""Tests del servicio de validación contra el perfil editorial del proyecto."""
from __future__ import annotations

import pytest

from sinnema.domain.exceptions import DomainValidationError
from sinnema.domain.models import FormatProfile, ScriptDraft
from sinnema.domain.services import (
    validate_adaptation_format,
    validate_audit_verdict,
    validate_draft_format,
    validate_package_format,
    validate_plan_format,
)

from conftest import (
    make_adapted,
    make_audit,
    make_chapter,
    make_draft,
    make_package,
    make_plan,
)

#: Perfil alternativo: show corto de 4-5 escenas y 80-120 palabras.
PERFIL_CORTO = FormatProfile(
    scenes_count=(4, 5),
    narration_target_words=(90, 110),
    narration_hard_words=(80, 120),
    total_duration_target_seconds=(35.0, 45.0),
    total_duration_hard_seconds=(30.0, 50.0),
    scene_duration_seconds=(2.0, 12.0),
    narration_max_words_per_scene=30,
    on_screen_text_max_words=4,
    min_approval_score=8,
)


def _regenerar_borrador(borrador: ScriptDraft, **cambios) -> ScriptDraft:
    """Reconstruye el borrador tras mutar sus escenas (para recalcula métricas)."""
    escenas = cambios.pop("escenas", None)
    datos = {**borrador.model_dump(), **cambios}
    if escenas is not None:
        datos["scenes"] = [e.model_dump() for e in escenas]
    return ScriptDraft(**datos)


# ------------------------------- validate_plan_format -------------------------------


def test_plan_con_budget_dentro_del_objetivo_aceptado():
    plan = make_plan(1, chapters=[make_chapter(1, word_budget=100)])
    validate_plan_format(plan, PERFIL_CORTO)


def test_plan_con_budget_fuera_del_objetivo_rechazado():
    plan = make_plan(1)  # word_budget 140; objetivo del perfil corto: 90-110
    with pytest.raises(DomainValidationError, match="word_budget"):
        validate_plan_format(plan, PERFIL_CORTO)


# ------------------------------- validate_draft_format -------------------------------


def test_borrador_show_60s_valido_con_perfil_por_defecto():
    validate_draft_format(make_draft(), FormatProfile())


def test_borrador_show_60s_rechazado_por_perfil_corto():
    """6 escenas y 142 palabras violan el perfil corto (4-5 escenas, 80-120)."""
    with pytest.raises(DomainValidationError, match="perfil editorial"):
        validate_draft_format(make_draft(), PERFIL_CORTO)


def test_borrador_valido_para_perfil_corto():
    # 12 hook + 5x18 narraciones + 10 cta = 112 palabras; 5 escenas de 10 s.
    validate_draft_format(make_draft(num_scenes=5, words_per_scene=18), PERFIL_CORTO)


def test_borrador_con_duracion_por_escena_fuera_de_perfil_rechazado():
    perfil = FormatProfile(scene_duration_seconds=(5.0, 15.0))
    borrador = make_draft()
    escenas = [s.model_copy(update={"duration_seconds": 3.0}) for s in borrador.scenes]
    with pytest.raises(DomainValidationError, match="duración fuera"):
        validate_draft_format(_regenerar_borrador(borrador, escenas=escenas), perfil)


def test_borrador_con_texto_en_pantalla_largo_para_perfil_rechazado():
    perfil = FormatProfile(on_screen_text_max_words=3)
    borrador = make_draft()
    escenas = [
        s.model_copy(update={"on_screen_text": "uno dos tres cuatro"})
        for s in borrador.scenes
    ]
    with pytest.raises(DomainValidationError, match="texto en pantalla"):
        validate_draft_format(_regenerar_borrador(borrador, escenas=escenas), perfil)


# ---------------------------- validate_adaptation_format ----------------------------


def test_adaptacion_show_60s_valida_con_perfil_por_defecto():
    validate_adaptation_format(make_adapted(make_draft()), FormatProfile())


def test_adaptacion_rechazada_por_perfil_corto():
    with pytest.raises(DomainValidationError, match="perfil editorial"):
        validate_adaptation_format(make_adapted(make_draft()), PERFIL_CORTO)


# ---------------------------- validate_package_format ----------------------------


def test_paquete_con_aspecto_del_proyecto_aceptado():
    validate_package_format(make_package(make_draft()), FormatProfile())


def test_paquete_con_aspecto_distinto_rechazado():
    perfil = FormatProfile(aspect_ratio="1:1")
    with pytest.raises(DomainValidationError, match="aspecto"):
        validate_package_format(make_package(make_draft()), perfil)


def test_paquete_con_specs_fuera_de_rango_rechazado():
    perfil = FormatProfile(scenes_count=(7, 8))
    with pytest.raises(DomainValidationError, match="specs visuales"):
        validate_package_format(make_package(make_draft()), perfil)  # 6 specs


# ---------------------------- validate_audit_verdict ----------------------------


def test_dictamen_aprobado_sobre_minimo_aceptado():
    validate_audit_verdict(make_audit(approved=True, score=9), FormatProfile())


def test_dictamen_aprobado_bajo_minimo_del_proyecto_rechazado():
    perfil = FormatProfile(min_approval_score=9)
    with pytest.raises(DomainValidationError, match="mínimo del proyecto"):
        validate_audit_verdict(make_audit(approved=True, score=7), perfil)


def test_dictamen_rechazado_con_score_bajo_no_altera_minimo():
    validate_audit_verdict(make_audit(approved=False, score=3), FormatProfile())


# ------------------------------ FormatProfile ------------------------------


def test_perfil_piso_mayor_que_techo_rechazado():
    with pytest.raises(Exception, match="supera el máximo"):
        FormatProfile(scenes_count=(8, 6))


def test_perfil_fuera_de_limites_universales_rechazado():
    with pytest.raises(Exception, match="universales"):
        FormatProfile(narration_hard_words=(20, 900))


def test_perfil_duro_que_no_envuelve_al_objetivo_rechazado():
    with pytest.raises(Exception, match="envolver"):
        FormatProfile(narration_target_words=(130, 150), narration_hard_words=(140, 200))
