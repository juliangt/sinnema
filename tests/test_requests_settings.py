"""Tests de la petición de serie (DTO de entrada) y de los settings del grafo."""
from __future__ import annotations

import pytest

from sinnema.application.requests import build_initial_state
from sinnema.application.settings import PipelineSettings

from conftest import TEMA, make_project, make_request


# ------------------------------- SeriesRequest -------------------------------


def test_peticion_valida_genera_estado_inicial_completo():
    request = make_request(num_chapters=4, max_critique_attempts=3)
    estado = build_initial_state(request)

    assert estado["num_chapters"] == 4
    assert estado["max_critique_attempts"] == 3
    assert estado["project_id"] == "sinnema"
    assert estado["language"]
    assert estado["tone_of_voice"]
    assert estado["current_chapter_index"] == 0
    assert estado["critique_attempts"] == 0
    assert estado["lore_entries"] == []
    assert estado["completed_episodes"] == []
    assert estado["failed_chapters"] == []


def test_tema_nulo_resuelve_al_default_del_proyecto():
    estado = build_initial_state(make_request(topic=None))
    assert estado["topic"] == TEMA


def test_tema_con_espacios_se_recorta_en_el_estado():
    request = make_request(topic="  Regex desde cero para todos  ")
    estado = build_initial_state(request)
    assert estado["topic"] == "Regex desde cero para todos"


def test_tema_demasiado_corto_rechazado():
    with pytest.raises(ValueError, match="tema"):
        make_request(topic="corto").validate()


def test_tema_demasiado_largo_rechazado():
    with pytest.raises(ValueError, match="no puede superar"):
        make_request(topic="palabra " * 40).validate()


def test_tema_default_del_proyecto_invalido_rechazado():
    with pytest.raises(ValueError, match="tema por defecto"):
        make_project(default_topic="corto").validate()


@pytest.mark.parametrize(
    "campo, valor",
    [("num_chapters", 0), ("num_chapters", 21), ("max_critique_attempts", 0), ("max_critique_attempts", 6)],
)
def test_limites_numericos_rechazados(campo, valor):
    request = make_request(**{campo: valor})
    with pytest.raises(ValueError, match=campo):
        request.validate()


def test_reporta_todos_los_problemas_de_una_vez():
    request = make_request(topic="corto", num_chapters=99)
    with pytest.raises(ValueError) as excinfo:
        request.validate()
    mensaje = str(excinfo.value)
    assert "tema" in mensaje and "num_chapters" in mensaje
    assert " | " in mensaje


# ------------------------------ PipelineSettings ------------------------------


def test_settings_por_defecto_validos():
    settings = PipelineSettings()
    assert settings.max_critique_attempts == 2
    assert settings.retry_exhaustion_policy == "force_accept"


@pytest.mark.parametrize("intentos", [0, 6])
def test_settings_con_intentos_fuera_de_rango_rechazados(intentos):
    with pytest.raises(ValueError, match="max_critique_attempts"):
        PipelineSettings(max_critique_attempts=intentos)


def test_settings_con_politica_desconocida_rechazada():
    with pytest.raises(ValueError, match="retry_exhaustion_policy"):
        PipelineSettings(retry_exhaustion_policy="reintentar_para_siempre")
