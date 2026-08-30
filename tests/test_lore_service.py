"""Tests de los servicios de lore: extracción y fusión de memorias."""
from __future__ import annotations

from sinnema.domain.services import extract_new_lore, merge_lore

from conftest import make_chapter, make_directives, make_lore_entry


def test_extrae_conceptos_y_terminos_con_categorias():
    capitulo = make_chapter(1)
    nuevas = extract_new_lore(capitulo, make_directives(new_terms=("red neuronal",)), [])
    terminos = {e.term: e.category for e in nuevas}
    assert terminos["concepto 1a"] == "concepto"
    assert terminos["concepto 1b"] == "concepto"
    assert terminos["red neuronal"] == "termino"
    assert all(e.chapter_id == "ch-01" for e in nuevas)


def test_deduplica_case_insensitive_contra_memoria_existente():
    capitulo = make_chapter(1)  # conceptos "concepto 1a" / "concepto 1b"
    existente = make_lore_entry(term="CONCEPTO 1A")
    nuevas = extract_new_lore(capitulo, None, [existente])
    assert [e.term for e in nuevas] == ["concepto 1b"]


def test_deduplica_dentro_del_mismo_capitulo():
    # El mismo término como concepto clave y término nuevo: cuenta una vez.
    capitulo = make_chapter(1, key_concepts=["modelo", "entrenamiento"])
    directivas = make_directives(new_terms=("modelo",))
    nuevas = extract_new_lore(capitulo, directivas, [])
    assert sorted(e.term for e in nuevas) == ["entrenamiento", "modelo"]


def test_sin_directivas_solo_conceptos_clave():
    capitulo = make_chapter(1)
    nuevas = extract_new_lore(capitulo, None, [])
    assert len(nuevas) == len(capitulo.key_concepts)


# ------------------------------- merge_lore -------------------------------


def test_merge_preserva_orden_y_deduplica_case_insensitive():
    existente = [make_lore_entry("modelo"), make_lore_entry("entrenamiento")]
    entrante = [make_lore_entry("MODELO"), make_lore_entry("par motor")]

    fusion = merge_lore(existente, entrante)

    assert [e.term for e in fusion] == ["modelo", "entrenamiento", "par motor"]


def test_merge_con_memorias_vacias():
    assert merge_lore([], []) == []
    entrante = [make_lore_entry("modelo")]
    assert merge_lore([], entrante) == entrante
