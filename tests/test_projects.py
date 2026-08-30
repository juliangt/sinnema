"""Tests de ProjectSpec (política de aplicación) y del cargador TOML."""
from __future__ import annotations

import pytest

from sinnema.application.projects import FormatProfile, ProjectSpec, project_from_dict
from sinnema.infrastructure.projects import DEFAULT_PROJECTS_DIR, list_projects, load_project

from conftest import make_project


# ------------------------------- ProjectSpec -------------------------------


def test_proyecto_valido_por_defecto():
    proyecto = make_project()
    proyecto.validate()
    assert proyecto.project_id == "sinnema"
    assert proyecto.format == FormatProfile()


@pytest.mark.parametrize("project_id", ["Motores", "con espacios", "a" * 31, ""])
def test_project_id_invalido_rechazado(project_id):
    with pytest.raises(ValueError, match="project_id"):
        make_project(project_id=project_id).validate()


@pytest.mark.parametrize(
    "campo", ["brand_name", "show_concept", "language", "audience",
              "cultural_context", "tone_of_voice", "style_guide", "constraints"]
)
def test_campo_de_vacio_rechazado(campo):
    with pytest.raises(ValueError, match=campo):
        make_project(**{campo: "   "}).validate()


def test_estilo_visual_maestro_demasiado_corto_rechazado():
    with pytest.raises(ValueError, match="visual_master_style"):
        make_project(visual_master_style="3D render").validate()


def test_validacion_reporta_varios_problemas_a_la_vez():
    with pytest.raises(ValueError) as excinfo:
        make_project(project_id="Mal Id", language="  ").validate()
    mensaje = str(excinfo.value)
    assert "project_id" in mensaje and "language" in mensaje
    assert " | " in mensaje


# ------------------------------ project_from_dict ------------------------------


def _toml_minimo() -> dict:
    return {
        "proyecto": {
            "id": "prueba",
            "marca": "Prueba",
            "concepto": "micro-videos de prueba verticales",
            "tema_por_defecto": "Un tema de prueba suficientemente largo",
            "idioma": "Español",
        },
        "voz": {
            "audiencia": "Audiencia de prueba",
            "contexto_cultural": "Contexto cultural",
            "tono": "tono cercano",
            "guia_de_estilo": "guía de estilo",
            "restricciones": "restricciones",
        },
        "visual": {
            "estilo_maestro": "3D render style with clean environment and lighting",
        },
    }


def test_from_dict_minimo_usa_formato_por_defecto():
    proyecto = project_from_dict(_toml_minimo())
    assert proyecto.project_id == "prueba"
    assert proyecto.format == FormatProfile()  # [formato] ausente -> default


def test_from_dict_con_formato_personalizado():
    datos = _toml_minimo()
    datos["formato"] = {
        "escenas": [3, 5],
        "palabras_objetivo": [200, 240],
        "palabras_duras": [180, 280],
        "relacion_de_aspecto": "16:9",
        "score_minimo_aprobacion": 8,
    }
    perfil = project_from_dict(datos).format
    assert perfil.scenes_count == (3, 5)
    assert perfil.narration_target_words == (200, 240)
    assert perfil.narration_hard_words == (180, 280)
    assert perfil.aspect_ratio == "16:9"
    assert perfil.min_approval_score == 8


@pytest.mark.parametrize(
    "seccion", ["proyecto", "voz", "visual"]
)
def test_from_dict_sin_seccion_requerida_rechazado(seccion):
    datos = _toml_minimo()
    del datos[seccion]
    with pytest.raises(ValueError, match=f"\\[{seccion}\\]"):
        project_from_dict(datos)


def test_from_dict_con_clave_faltante_lista_el_campo_exacto():
    datos = _toml_minimo()
    del datos["voz"]["tono"]
    with pytest.raises(ValueError, match="'tono' en \\[voz\\]"):
        project_from_dict(datos)


def test_from_dict_con_formato_invalido_rollea_con_contexto():
    datos = _toml_minimo()
    datos["formato"] = {"escenas": [8, 6]}  # piso > techo
    with pytest.raises(ValueError, match=r"\[formato\] inválido"):
        project_from_dict(datos)


# --------------------------------- Loader ---------------------------------


def test_loader_carga_los_proyectos_de_referencia():
    proyectos = {p.project_id: p for p in list_projects()}
    assert set(proyectos) == {
        "comida", "educativo", "enfoque", "estafas", "finanzas", "futbol",
        "motores",
    }
    assert proyectos["educativo"].brand_name == "Educativo"
    assert proyectos["motores"].brand_name == "Duelo de Motores"
    assert proyectos["comida"].brand_name == "Etiqueta Negra"
    assert proyectos["estafas"].brand_name == "Escudo Digital"
    # Cada show mantiene lore y salidas separadas: ids distintos.
    temas = [p.default_topic for p in proyectos.values()]
    assert len(temas) == len(set(temas))


def test_loader_proyecto_inexistente_lista_disponibles():
    with pytest.raises(
        RuntimeError,
        match="comida, educativo, enfoque, estafas, finanzas, futbol, motores",
    ):
        load_project("inexistente")


def test_loader_lee_desde_directorio_temporal(tmp_path):
    # TOML equivalente al dict mínimo, con id "custom".
    (tmp_path / "custom.toml").write_text(
        """
[proyecto]
id = "custom"
marca = "Prueba"
concepto = "micro-videos de prueba verticales"
tema_por_defecto = "Un tema de prueba suficientemente largo"
idioma = "Español"

[voz]
audiencia = "Audiencia de prueba"
contexto_cultural = "Contexto cultural"
tono = "tono cercano"
guia_de_estilo = "guía de estilo"
restricciones = "restricciones"

[visual]
estilo_maestro = "3D render style with clean environment and lighting"
""",
        encoding="utf-8",
    )
    proyecto = load_project("custom", directorio=tmp_path)
    assert proyecto.project_id == "custom"
    assert [p.project_id for p in list_projects(directorio=tmp_path)] == ["custom"]


def test_loader_archivo_mal_formado_error_accionable(tmp_path):
    (tmp_path / "roto.toml").write_text("[proyecto\nid = ", encoding="utf-8")
    with pytest.raises(RuntimeError, match="roto"):
        load_project("roto", directorio=tmp_path)


def test_directorio_por_defecto_apunta_a_proyectos():
    assert DEFAULT_PROJECTS_DIR.name == "proyectos"
