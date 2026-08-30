"""Tests de los contratos del paquete técnico (visual / audio)."""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from sinnema.domain.models import TechnicalPackage

from conftest import make_draft, make_package


def test_paquete_valido_por_defecto():
    paquete = make_package(make_draft())
    assert len(paquete.visual_specs) == 6
    assert paquete.aspect_ratio == "9:16"


def test_chapter_id_del_paquete_se_normaliza():
    paquete = make_package(make_draft())
    datos = paquete.model_dump()
    datos["chapter_id"] = "CH-01"
    assert TechnicalPackage(**datos).chapter_id == "ch-01"


def test_prompt_de_imagen_en_espanol_rechazado():
    paquete = make_package(make_draft())
    datos = paquete.model_dump()
    datos["visual_specs"][0]["image_prompt"] = (
        "Un render isométrico de un robot explicando iluminación de neón en vertical"
    )
    with pytest.raises(ValidationError, match="image_prompt"):
        TechnicalPackage(**datos)


def test_negative_prompt_con_enie_rechazado():
    paquete = make_package(make_draft())
    datos = paquete.model_dump()
    datos["visual_specs"][0]["negative_prompt"] = "sin agua ni años"
    with pytest.raises(ValidationError, match="negative_prompt"):
        TechnicalPackage(**datos)


def test_motion_direction_con_signo_espanol_rechazado():
    paquete = make_package(make_draft())
    datos = paquete.model_dump()
    datos["visual_specs"][0]["motion_direction"] = "cámara lenta hacia el sujeto ¿verdad?"
    with pytest.raises(ValidationError, match="motion_direction"):
        TechnicalPackage(**datos)


def test_thumbnail_prompt_en_espanol_rechazado():
    paquete = make_package(make_draft())
    datos = paquete.model_dump()
    datos["thumbnail_prompt"] = "Una miniatura vertical con el robot y su corazón de datos"
    with pytest.raises(ValidationError, match="thumbnail_prompt"):
        TechnicalPackage(**datos)


def test_specs_no_secuenciales_rechazadas():
    borrador = make_draft()
    with pytest.raises(ValidationError, match="secuenciales"):
        make_package(borrador, scene_numbers=[1, 2, 3, 4, 5, 7])


def test_specs_con_numeros_validos_para_otro_borrador_aceptadas():
    # 7 escenas numeradas 1..7 es internamente válido (lo cruza el ensamblador).
    paquete = make_package(make_draft(), scene_numbers=[1, 2, 3, 4, 5, 6, 7])
    assert len(paquete.visual_specs) == 7


def test_style_tags_insuficientes_rechazados():
    paquete = make_package(make_draft())
    datos = paquete.model_dump()
    datos["visual_specs"][0]["style_tags"] = ["isometric", "neon"]
    with pytest.raises(ValidationError):
        TechnicalPackage(**datos)
