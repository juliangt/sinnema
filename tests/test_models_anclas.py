"""Tests de los contratos de dominio de los recursos ancla (spec §4.1/§11.1)."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from sinnema.domain.models import ImagenAncla, ManifestDeGeneracion, RecursoAncla, ReferenciaAncla
from sinnema.domain.models.anclas import (
    BATERIA_MINIMA,
    ESTADOS_DE_ANCLA,
    ROLES_POR_TIPO,
    TIPOS_DE_ANCLA,
    bateria_minima_cumplida,
)

from conftest import make_ancla, make_imagen_ancla


# ------------------------------- RecursoAncla -------------------------------


def test_ancla_valida_por_defecto():
    ancla = make_ancla()
    assert ancla.estado == "borrador"
    assert ancla.version == 1
    assert ancla.chapter_first_seen is None
    assert ancla.chapter_last_seen is None
    assert len(ancla.bateria) == 4


def test_ancla_borrador_sin_bateria_es_valida():
    """La batería mínima solo se exige al lockear, no en borrador."""
    ancla = make_ancla(bateria=[])
    assert ancla.estado == "borrador"
    assert ancla.bateria == []


def test_ancla_id_se_normaliza_y_valida_como_slug():
    assert make_ancla(ancla_id=" prota-1 ").ancla_id == "prota-1"


@pytest.mark.parametrize("ancla_id", ["Prota", "con espacios", "-guion", "a" * 61, ""])
def test_ancla_id_invalido_rechazado(ancla_id):
    with pytest.raises(ValidationError, match="ancla_id"):
        make_ancla(ancla_id=ancla_id)


@pytest.mark.parametrize("nombre", ["   ", ""])
def test_nombre_vacio_rechazado(nombre):
    with pytest.raises(ValidationError, match="nombre"):
        make_ancla(nombre=nombre)


def test_nombre_se_normaliza_a_espacios_simples():
    assert make_ancla(nombre="  Nita   la  guia ").nombre == "Nita la guia"


def test_descripcion_canonica_demasiado_corta_rechazada():
    with pytest.raises(ValidationError, match="descripcion_canonica"):
        make_ancla(descripcion_canonica="Short descriptor")


def test_descripcion_canonica_en_espanol_rechazada():
    with pytest.raises(ValidationError, match="descripcion_canonica"):
        make_ancla(
            descripcion_canonica=(
                "Descripción canónica de la protagonista con rasgos canónicos "
                "estables para modelos de imagen"
            )
        )


def test_descripcion_canonica_valida_en_ingles():
    descriptor = "A friendly robot guide with round glowing eyes and soft matte shell"
    assert make_ancla(descripcion_canonica=descriptor).descripcion_canonica == descriptor


def test_version_no_puede_ser_cero_o_negativa():
    with pytest.raises(ValidationError, match="version"):
        make_ancla(version=0)


@pytest.mark.parametrize("estado", ["borrador", "propuesto", "lockeado", "retirado"])
def test_estados_validos_con_bateria_minima(estado):
    ancla = make_ancla(estado=estado)
    assert ancla.estado == estado


def test_estado_invalido_rechazado():
    with pytest.raises(ValidationError, match="estado"):
        make_ancla(estado="aprobado")


# --------------------------- Coherencia rol ↔ tipo ---------------------------


@pytest.mark.parametrize(
    "tipo, rol",
    [
        ("lugar", "hero_portrait"),
        ("objeto", "establishing_shot"),
        ("estilo", "prop_hero"),
        ("personaje", "style_reference"),
        ("personaje", "prop_detail"),
        ("lugar", "outfit_variant"),
    ],
)
def test_rol_incoherente_con_el_tipo_rechazado(tipo, rol):
    with pytest.raises(ValidationError, match="incoherentes"):
        make_ancla(tipo=tipo, bateria=[make_imagen_ancla(rol)])


@pytest.mark.parametrize("tipo", TIPOS_DE_ANCLA)
def test_roles_validos_por_tipo_se_aceptan(tipo):
    ancla = make_ancla(
        tipo=tipo,
        bateria=[make_imagen_ancla(rol) for rol in ROLES_POR_TIPO[tipo]],
    )
    assert {i.rol for i in ancla.bateria} == set(ROLES_POR_TIPO[tipo])


def test_roles_por_tipo_cubren_el_vocabulario_completo():
    """Cada rol del Literal pertenece exactamente a un tipo (sin huérfanos)."""
    todos = {rol for roles in ROLES_POR_TIPO.values() for rol in roles}
    assert len(todos) == 13
    assert len([r for roles in ROLES_POR_TIPO.values() for r in roles]) == len(todos)


# --------------------------- Batería mínima y lock ---------------------------


@pytest.mark.parametrize(
    "tipo, roles, esperado",
    [
        ("personaje", ["hero_portrait", "turnaround_front", "turnaround_side",
                       "turnaround_back"], True),
        ("personaje", ["hero_portrait", "turnaround_front"], False),
        ("personaje", ["hero_portrait", "turnaround_front", "turnaround_side",
                       "turnaround_back", "expression_sheet"], True),
        ("personaje", [], False),
        ("lugar", ["establishing_shot"], True),
        ("lugar", ["coverage_angle"], False),
        ("objeto", ["prop_hero"], True),
        ("objeto", ["prop_detail"], False),
        ("estilo", ["style_reference"], True),
        ("estilo", [], False),
    ],
)
def test_bateria_minima_cumplida(tipo, roles, esperado):
    assert bateria_minima_cumplida(tipo, roles) is esperado


def test_lock_sin_bateria_minima_rechazado():
    with pytest.raises(ValidationError, match="batería mínima"):
        make_ancla(estado="lockeado", bateria=[make_imagen_ancla("expression_sheet")])


def test_lock_de_lugar_solo_exige_establishing_shot():
    ancla = make_ancla(tipo="lugar", estado="lockeado")
    assert ancla.bateria[0].rol == "establishing_shot"


def test_bateria_minima_esta_definida_para_todos_los_tipos():
    assert set(BATERIA_MINIMA) == set(TIPOS_DE_ANCLA)
    assert set(ESTADOS_DE_ANCLA) == {"borrador", "propuesto", "lockeado", "retirado"}


def test_lock_con_bateria_recomendada_extra_es_valido():
    ancla = make_ancla(
        estado="lockeado",
        bateria=[
            make_imagen_ancla("hero_portrait"),
            make_imagen_ancla("turnaround_front"),
            make_imagen_ancla("turnaround_quarter"),
            make_imagen_ancla("turnaround_side"),
            make_imagen_ancla("turnaround_back"),
            make_imagen_ancla("expression_sheet"),
            make_imagen_ancla("outfit_variant"),
        ],
    )
    assert ancla.version == 1


# ------------------------------ ImagenAncla ------------------------------


def test_imagen_por_defecto_es_subida_sin_manifest():
    imagen = make_imagen_ancla()
    assert imagen.origen == "subida"
    assert imagen.manifest is None


def test_imagen_generada_con_manifest_es_valida():
    manifest = ManifestDeGeneracion(
        proveedor="gemini",
        modelo="gemini-2.0-flash-preview-image-generation",
        prompt_final="Hero portrait of the robot guide, studio lighting, 9:16",
        anclas_usadas=[("protagonista", 1, "hero_portrait")],
        creado_en=datetime(2026, 9, 12, tzinfo=timezone.utc),
    )
    imagen = make_imagen_ancla(origen="generada", manifest=manifest)
    assert imagen.manifest.anclas_usadas == [("protagonista", 1, "hero_portrait")]


def test_imagen_subida_con_manifest_rechazada():
    manifest = ManifestDeGeneracion(
        proveedor="gemini",
        modelo="gemini-2.0-flash-preview-image-generation",
        prompt_final="Hero portrait of the robot guide, studio lighting, 9:16",
        creado_en=datetime(2026, 9, 12, tzinfo=timezone.utc),
    )
    with pytest.raises(ValidationError, match="manifest"):
        make_imagen_ancla(origen="subida", manifest=manifest)


@pytest.mark.parametrize(
    "archivo", ["../escape.png", "sub/dir.png", "/absoluta.png", "..", ".", ""]
)
def test_ruta_de_archivo_con_traversal_rechazada(archivo):
    with pytest.raises(ValidationError, match="archivo"):
        make_imagen_ancla(archivo=archivo)


def test_rol_invalido_rechazado():
    with pytest.raises(ValidationError, match="rol"):
        make_imagen_ancla(rol="primer_plano")


# --------------------------- ReferenciaAncla ---------------------------


def test_referencia_sin_roles_pide_la_bateria_completa():
    ref = ReferenciaAncla(ancla_id="look-principal")
    assert ref.roles == []


def test_referencia_con_roles_especificos():
    ref = ReferenciaAncla(ancla_id="protagonista", roles=["hero_portrait", "turnaround_side"])
    assert ref.roles == ["hero_portrait", "turnaround_side"]


def test_referencia_valida_el_slug_del_ancla():
    with pytest.raises(ValidationError, match="ancla_id"):
        ReferenciaAncla(ancla_id="Mala Referencia")


# ----------------------- ManifestDeGeneracion -----------------------


def test_manifest_exige_creado_en_y_prompt_valido():
    with pytest.raises(ValidationError, match="creado_en"):
        ManifestDeGeneracion(
            proveedor="openai", modelo="gpt-image-1",
            prompt_final="Hero portrait of the robot guide in neon lab",
        )


def test_manifest_con_prompt_en_espanol_rechazado():
    with pytest.raises(ValidationError, match="prompt_final"):
        ManifestDeGeneracion(
            proveedor="openai", modelo="gpt-image-1",
            prompt_final="Retrato del robot guía con iluminación de neón en laboratorio",
            creado_en=datetime(2026, 9, 12, tzinfo=timezone.utc),
        )


def test_ancla_hace_roundtrip_json():
    ancla = make_ancla(estado="lockeado", chapter_first_seen="ch-01")
    restaurada = RecursoAncla.model_validate_json(ancla.model_dump_json())
    assert restaurada == ancla
