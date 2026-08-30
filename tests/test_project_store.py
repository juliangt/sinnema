"""Tests del almacén de proyectos respaldado en TOML (CRUD de la web)."""
from __future__ import annotations

import tomllib

import pytest

from sinnema.infrastructure.projects.store import (
    ProjectFileStore,
    resolve_writable_projects_dir,
)


def _proyecto_dict(id: str = "nuevo-show", **extra) -> dict:
    datos = {
        "proyecto": {
            "id": id,
            "marca": "Marca Nueva",
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
    datos.update(extra)
    return datos


@pytest.fixture
def store(tmp_path):
    return ProjectFileStore(tmp_path / "escribible", tmp_path / "empaquetado")


def test_create_escribe_toml_valido_y_carga(store):
    spec = store.create(_proyecto_dict(agentes={"critic": {"reglas": ["Ser implacable"]}}))
    assert spec.project_id == "nuevo-show"
    assert spec.config_de_agente("critic").reglas == ("Ser implacable",)

    # El archivo en disco es TOML válido y preserva la forma original.
    crudo = tomllib.loads(
        (store.writable_dir / "nuevo-show.toml").read_text(encoding="utf-8")
    )
    assert crudo["proyecto"]["marca"] == "Marca Nueva"
    assert crudo["agentes"]["critic"]["reglas"] == ["Ser implacable"]


def test_create_rechaza_proyecto_invalido_sin_escribir(store):
    datos = _proyecto_dict()
    datos["voz"]["tono"] = "  "  # campo requerido vacío
    with pytest.raises(ValueError, match="tone_of_voice"):
        store.create(datos)
    assert not store.exists("nuevo-show")


def test_create_rechaza_secciones_desconocidas(store):
    with pytest.raises(ValueError, match="Secciones desconocidas"):
        store.create(_proyecto_dict(voz2={"tono": "x"}))


def test_create_rechaza_duplicado(store):
    store.create(_proyecto_dict())
    with pytest.raises(FileExistsError, match="Ya existe"):
        store.create(_proyecto_dict())


def test_update_sobreescribe_y_mantiene_el_id(store):
    store.create(_proyecto_dict())
    datos = _proyecto_dict()
    datos["proyecto"]["marca"] = "Marca Editada"
    spec = store.update("nuevo-show", datos)
    assert spec.brand_name == "Marca Editada"
    assert store.read_raw("nuevo-show")["proyecto"]["marca"] == "Marca Editada"


def test_update_rechaza_cambio_de_id(store):
    store.create(_proyecto_dict())
    with pytest.raises(ValueError, match="inmutable"):
        store.update("nuevo-show", _proyecto_dict(id="otro-id"))


def test_update_de_proyecto_inexistente_da_file_not_found(store):
    with pytest.raises(FileNotFoundError):
        store.update("fantasma", _proyecto_dict(id="fantasma"))


def test_delete_quita_el_archivo(store):
    store.create(_proyecto_dict())
    store.delete("nuevo-show")
    assert not store.is_editable("nuevo-show")
    with pytest.raises(FileNotFoundError):
        store.read_raw("nuevo-show")


def test_list_merged_fusiona_escribible_con_empaquetado_sin_repetir(store, tmp_path):
    (tmp_path / "empaquetado").mkdir(parents=True, exist_ok=True)
    (tmp_path / "escribible").mkdir(parents=True, exist_ok=True)
    (tmp_path / "empaquetado" / "beta.toml").write_text("", encoding="utf-8")
    (tmp_path / "empaquetado" / "muestra.toml").write_text("", encoding="utf-8")

    # Un empaquetado inválido no debe tumbar el listado.
    store.create(_proyecto_dict(id="alpha"))
    ids = [p.project_id for p in store.list_merged()]
    assert "alpha" in ids
    assert "beta" not in ids and "muestra" not in ids  # vacíos = inválidos, se saltan

    # Override local de un empaquetado válido.
    (tmp_path / "empaquetado" / "gamma.toml").write_text(
        _toml_text("gamma"), encoding="utf-8"
    )
    store.create(_proyecto_dict(id="gamma", **{}))  # ya existe en empaquetado -> se permite crear override
    ids = [p.project_id for p in store.list_merged()]
    assert ids.count("gamma") == 1


def _toml_text(id: str) -> str:
    return f"""
[proyecto]
id = "{id}"
marca = "Empaquetado"
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
"""


def test_editar_empaquetado_escribe_override_local(store, tmp_path):
    (tmp_path / "empaquetado").mkdir(parents=True, exist_ok=True)
    (tmp_path / "empaquetado" / "muestra.toml").write_text(
        _toml_text("muestra"), encoding="utf-8"
    )
    assert store.exists("muestra") and not store.is_editable("muestra")

    datos = store.read_raw("muestra")
    datos["proyecto"]["marca"] = "Muestra Editada"
    store.update("muestra", datos)

    assert store.is_editable("muestra")
    assert store.read_raw("muestra")["proyecto"]["marca"] == "Muestra Editada"

    # Borrar el override restaura el empaquetado.
    store.delete("muestra")
    assert store.exists("muestra")
    assert store.read_raw("muestra")["proyecto"]["marca"] == "Empaquetado"


def test_resolucion_de_directorio_escribible_prefiere_env(monkeypatch, tmp_path):
    monkeypatch.setenv("SINNEMA_PROJECTS_DIR", str(tmp_path / "custom"))
    assert resolve_writable_projects_dir() == tmp_path / "custom"
