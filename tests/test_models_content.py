"""Tests de los contratos de contenido micro (Scene, ScriptDraft, AdaptedScript).

Los contratos solo hacen cumplir los límites UNIVERSALES de sanidad; el sobre
editorial del proyecto (escenas 6-8, palabras 100-200, etc.) lo testea
``test_format_service`` a través de ``FormatProfile``.
"""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from sinnema.domain.models import AdaptedScene, Scene, ScriptDraft

from conftest import make_adapted, make_draft, make_scene


def test_borrador_valido_recalcula_metricas():
    borrador = make_draft()
    assert borrador.word_count == 142  # 12 hook + 6x20 narraciones + 10 cta
    assert borrador.total_duration_seconds == 60.0


def test_chapter_id_del_borrador_se_normaliza():
    borrador = make_draft()
    datos = borrador.model_dump()
    datos["chapter_id"] = "CH-01"
    assert ScriptDraft(**datos).chapter_id == "ch-01"


def test_escenas_no_secuenciales_rechazadas():
    escenas = [make_scene(n) for n in (1, 2, 3, 4, 5, 7)]
    with pytest.raises(ValidationError, match="secuenciales"):
        ScriptDraft(
            chapter_id="ch-01",
            title="Título de prueba del borrador",
            hook="gancho inicial del capítulo",
            scenes=escenas,
            call_to_action="suscríbete y mira el siguiente capítulo",
        )


def test_borrador_con_5_escenas_aceptado_por_contrato_universal():
    """Menos de 6 escenas ya no es rechazo de contrato: el rango editorial
    (6-8 en el show de 60 s) lo aplica el perfil del proyecto."""
    assert len(make_draft(num_scenes=5).scenes) == 5


def test_borrador_con_mas_de_12_escenas_rechazado():
    with pytest.raises(ValidationError):
        make_draft(num_scenes=13)


@pytest.mark.parametrize(
    "palabras_por_escena, esperado",
    [(1, "universales"), (100, "universales")],
)
def test_borrador_con_palabras_fuera_de_limite_rechazado(palabras_por_escena, esperado):
    # 12 hook + 6xN narraciones + 10 cta: N=1 -> 28 palabras (< 30);
    # N=100 -> 622 palabras (> 600), con narraciones en el techo universal (100).
    with pytest.raises(ValidationError, match=esperado):
        make_draft(words_per_scene=palabras_por_escena)


def test_borrador_con_duracion_fuera_de_rango_rechazado():
    # 6 escenas de 1.5 s = 9 s < 10 s (piso universal de sanidad).
    escenas = [make_scene(n, duration=1.5) for n in range(1, 7)]
    with pytest.raises(ValidationError, match="universales"):
        ScriptDraft(
            chapter_id="ch-01",
            title="Título de prueba del borrador",
            hook="gancho inicial del capítulo",
            scenes=escenas,
            call_to_action="suscríbete y mira el siguiente capítulo",
        )


def test_narracion_de_escena_demasiado_larga_rechazada():
    with pytest.raises(ValidationError, match="100 palabras"):
        make_scene(1, words=101)


def _escena(**overrides) -> Scene:
    datos = dict(
        scene_number=1,
        duration_seconds=10.0,
        visual_action="Acción visual descriptiva y concreta de la escena",
        narration="narración de prueba para la escena",
        on_screen_text=None,
        transition="corte_seco",
    )
    datos.update(overrides)
    return Scene(**datos)


def test_texto_en_pantalla_de_mas_de_12_palabras_rechazado():
    with pytest.raises(ValidationError, match="12 palabras"):
        _escena(on_screen_text="1 2 3 4 5 6 7 8 9 10 11 12 13")


def test_texto_en_pantalla_de_6_palabras_aceptado():
    escena = _escena(on_screen_text="una dos tres cuatro cinco seis")
    assert escena.on_screen_text == "una dos tres cuatro cinco seis"


def test_adaptacion_valida_recalcula_palabras():
    adaptada = make_adapted(make_draft())
    # 11 hook + 6x19 narraciones + 9 cta = 134 palabras.
    texto = " ".join(
        [adaptada.adapted_hook]
        + [s.narration for s in adaptada.adapted_scenes]
        + [adaptada.adapted_cta]
    )
    assert len(texto.split()) == 134


def test_adaptacion_con_palabras_fuera_de_limite_rechazada():
    borrador = make_draft()
    # 11 hook + 6x100 narraciones + 9 cta = 620 palabras (> 600 universal).
    with pytest.raises(ValidationError, match="universales"):
        make_adapted(borrador, words_per_scene=100)


def test_adaptada_con_texto_en_pantalla_largo_rechazado():
    with pytest.raises(ValidationError, match="12 palabras"):
        AdaptedScene(
            scene_number=1,
            narration="narración corta pero válida",
            on_screen_text="1 2 3 4 5 6 7 8 9 10 11 12 13",
        )
