"""Tests de los contratos de planificación macro (ChapterOutline, SeriesPlan)."""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from sinnema.domain.constants import SERIES_MAX_CHAPTERS
from sinnema.domain.models import ChapterOutline, SeriesPlan

from conftest import make_chapter, make_plan


def test_capitulo_valido_por_defecto():
    capitulo = make_chapter(1)
    assert capitulo.chapter_id == "ch-01"
    assert capitulo.word_budget == 140


def test_chapter_id_se_normaliza_a_minusculas():
    capitulo = make_chapter(1, chapter_id=" CH-01 ")
    assert capitulo.chapter_id == "ch-01"


def test_concepto_clave_demasiado_largo_rechazado():
    with pytest.raises(ValidationError, match="máximo 4 palabras"):
        make_chapter(1, key_concepts=["un concepto demasiado largo de cinco palabras", "ok"])


@pytest.mark.parametrize("presupuesto", [29, 601])
def test_word_budget_fuera_de_rango_rechazado(presupuesto):
    """Solo el rango universal de sanidad; el rango objetivo del proyecto
    (130-150 en el show de 60 s) lo aplica ``validate_plan_format``."""
    with pytest.raises(ValidationError):
        make_chapter(1, word_budget=presupuesto)


def test_serie_con_mas_de_20_capitulos_rechazada():
    capitulos = [make_chapter(i) for i in range(1, SERIES_MAX_CHAPTERS + 2)]
    with pytest.raises(ValidationError):
        make_plan(0, chapters=capitulos)


def test_ids_duplicados_rechazados():
    capitulos = [make_chapter(1), make_chapter(1)]
    with pytest.raises(ValidationError, match="duplicados"):
        make_plan(0, chapters=capitulos)


def test_dificultad_retrocedida_rechazada():
    capitulos = [
        make_chapter(1, difficulty="intermedio"),
        make_chapter(2, difficulty="inicial"),
    ]
    with pytest.raises(ValidationError, match="no decreciente"):
        make_plan(0, chapters=capitulos)


def test_dificultad_progresiva_aceptada():
    capitulos = [
        make_chapter(1, difficulty="inicial"),
        make_chapter(2, difficulty="intermedio"),
        make_chapter(3, difficulty="avanzado"),
    ]
    plan = make_plan(0, chapters=capitulos)
    assert len(plan.chapters) == 3


def test_prerrequisito_que_es_concepto_propio_rechazado():
    capitulo = make_chapter(
        2,
        key_concepts=["red neuronal", "entrenamiento"],
        prerequisites=["Red Neuronal"],  # mismo concepto, distinta capitalización
    )
    with pytest.raises(ValidationError, match="prerrequisito"):
        make_plan(0, chapters=[make_chapter(1), capitulo])


def test_prerrequisito_de_otro_capitulo_aceptado():
    capitulo = make_chapter(
        2,
        key_concepts=["red neuronal", "entrenamiento"],
        prerequisites=["concepto 1a"],  # concepto introducido en ch-01
    )
    plan = make_plan(0, chapters=[make_chapter(1), capitulo])
    assert plan.chapters[1].prerequisites == ["concepto 1a"]
