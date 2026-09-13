"""Tests de los servicios de lore: extracción y fusión de memorias."""
from __future__ import annotations

from sinnema.domain.services import extract_new_lore, merge_lore

from conftest import make_ancla, make_chapter, make_directives, make_lore_entry


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


# ---------------- Hito 4: lore enlazado (spec-recursos-ancla §4.4) ----------------


def test_termino_nuevo_que_coincide_con_ancla_se_enlaza():
    capitulo = make_chapter(1)
    directivas = make_directives(new_terms=("Protagonista",))
    ancla = make_ancla("protagonista", estado="lockeado")  # nombre: "Protagonista"
    nuevas = extract_new_lore(capitulo, directivas, [], anclas=[ancla])

    por_termino = {e.term: e for e in nuevas}
    enlazada = por_termino["Protagonista"]
    assert enlazada.ancla_id == "protagonista"
    assert enlazada.category == "personaje"
    # Los términos sin ancla quedan como siempre.
    assert por_termino["concepto 1a"].ancla_id is None
    assert por_termino["concepto 1a"].category == "concepto"


def test_cruce_determinista_casefold_y_por_tipo():
    capitulo = make_chapter(1, key_concepts=["La nave", "Entrenamiento"])
    anclas = [
        make_ancla("la-nave", tipo="lugar", estado="lockeado"),  # nombre "La nave"
        make_ancla("look-principal", tipo="estilo", estado="lockeado"),
    ]
    nuevas = extract_new_lore(capitulo, None, [], anclas=anclas)
    por_termino = {e.term: e for e in nuevas}
    assert por_termino["La nave"].ancla_id == "la-nave"
    assert por_termino["La nave"].category == "referencia"
    assert por_termino["Entrenamiento"].ancla_id is None


def test_cruce_solo_aplica_a_terminos_nuevos():
    capitulo = make_chapter(1, key_concepts=["protagonista", "entrenamiento"])
    existente = make_lore_entry("PROTAGONISTA")  # ya está en la memoria
    ancla = make_ancla("protagonista", estado="lockeado")
    nuevas = extract_new_lore(capitulo, None, [existente], anclas=[ancla])
    # "protagonista" ya estaba en la memoria: no se re-produce ni se enlaza.
    assert [e.term for e in nuevas] == ["entrenamiento"]
    assert all(e.ancla_id is None for e in nuevas)


def test_sin_anclas_el_lore_queda_exacto_como_hoy():
    capitulo = make_chapter(1)
    directivas = make_directives(new_terms=("red neuronal",))
    nuevas = extract_new_lore(capitulo, directivas, [], anclas=[])
    assert nuevas == extract_new_lore(capitulo, directivas, [])
    assert all(e.ancla_id is None for e in nuevas)
