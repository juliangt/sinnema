"""Tests de los contratos de continuidad y lore."""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from sinnema.domain.models import ContinuityDirectives, LoreEntry

from conftest import make_directives, make_lore_entry


def test_directivas_validas_por_defecto():
    directivas = make_directives()
    assert directivas.new_terms_to_introduce == ["término canónico"]


def test_termino_de_lore_de_mas_de_4_palabras_rechazado():
    with pytest.raises(ValidationError, match="máximo 4 palabras"):
        make_lore_entry(term="un término demasiado largo de cinco palabras")


def test_termino_de_lore_4_palabras_aceptado():
    entrada = make_lore_entry(term="red neuronal convolucional profunda")
    assert entrada.term == "red neuronal convolucional profunda"


def test_termino_nuevo_de_mas_de_4_palabras_rechazado():
    with pytest.raises(ValidationError, match="demasiado largos"):
        make_directives(new_terms=("un término demasiado largo de cinco",))


def test_termino_nuevo_ya_cubierto_rechazado():
    with pytest.raises(ValidationError, match="concepts_already_covered"):
        make_directives(
            new_terms=("Modelo",),
            concepts_covered=("modelo",),
        )


def test_termino_nuevo_distinto_de_los_cubiertos_aceptado():
    directivas = make_directives(
        new_terms=("red neuronal",),
        concepts_covered=("modelo", "entrenamiento"),
    )
    assert directivas.new_terms_to_introduce == ["red neuronal"]
