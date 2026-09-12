"""Tests del almacén de recursos ancla (JsonAnchorStore) y su integración."""
from __future__ import annotations

import json
import logging
from pathlib import Path

import pytest

from sinnema.infrastructure.anclas import JsonAnchorStore
from sinnema.infrastructure.anclas.store import DEFAULT_ANCHAS_ROOT

from conftest import make_ancla, make_imagen_ancla


def test_default_root_apunta_a_anclas():
    assert DEFAULT_ANCHAS_ROOT == Path("anclas")


def test_carga_sin_archivo_devuelve_biblioteca_vacia(tmp_path):
    store = JsonAnchorStore(tmp_path)
    assert store.load("sinnema") == []


def test_guardar_y_cargar_roundtrip(tmp_path):
    store = JsonAnchorStore(tmp_path)
    anclas = [make_ancla("protagonista"), make_ancla("look-principal", tipo="estilo")]

    store.save("sinnema", anclas)

    cargadas = store.load("sinnema")
    assert [a.ancla_id for a in cargadas] == ["protagonista", "look-principal"]
    assert cargadas == anclas
    # UTF-8 real (ensure_ascii=False): los nombres viajan legibles, sin \u.
    volcado = (tmp_path / "sinnema" / "anclas.json").read_text(encoding="utf-8")
    assert "Protagonista" in volcado
    store.save("sinnema", [make_ancla("nita", nombre="Nita la guía")])
    assert "Nita la guía" in (tmp_path / "sinnema" / "anclas.json").read_text("utf-8")


def test_los_proyectos_no_pisan_la_biblioteca_del_otro(tmp_path):
    store = JsonAnchorStore(tmp_path)
    store.save("sinnema", [make_ancla("protagonista")])
    store.save("motores", [make_ancla("moto-roja", tipo="objeto")])

    assert [a.ancla_id for a in store.load("sinnema")] == ["protagonista"]
    assert [a.ancla_id for a in store.load("motores")] == ["moto-roja"]


def test_biblioteca_corrupta_falla_en_voz_alta(tmp_path):
    ruta = tmp_path / "sinnema" / "anclas.json"
    ruta.parent.mkdir(parents=True)
    ruta.write_text("{esto no es json valido", encoding="utf-8")

    with pytest.raises(RuntimeError, match="corrupta"):
        JsonAnchorStore(tmp_path).load("sinnema")


def test_biblioteca_con_anclas_invalidas_falla_en_voz_alta(tmp_path):
    ruta = tmp_path / "sinnema" / "anclas.json"
    ruta.parent.mkdir(parents=True)
    ruta.write_text(json.dumps([{"ancla_id": "sin los demas campos"}]), encoding="utf-8")

    with pytest.raises(RuntimeError, match="corrupta"):
        JsonAnchorStore(tmp_path).load("sinnema")


# ------------------------------- Unicidades -------------------------------


def test_ancla_id_duplicado_rechazado(tmp_path):
    store = JsonAnchorStore(tmp_path)
    with pytest.raises(ValueError, match="ancla_id duplicado"):
        store.save("sinnema", [make_ancla("prota"), make_ancla("prota")])
    assert not (tmp_path / "sinnema" / "anclas.json").exists()


def test_nombre_duplicado_case_insensitive_rechazado(tmp_path):
    store = JsonAnchorStore(tmp_path)
    with pytest.raises(ValueError, match="nombre de ancla duplicado"):
        store.save(
            "sinnema",
            [make_ancla("prota", nombre="Nita la guía"),
             make_ancla("guia", nombre="nita LA GUÍA")],
        )
    assert not (tmp_path / "sinnema" / "anclas.json").exists()


# --------------------- Versionado de anclas lockeadas ---------------------


def test_cambiar_bateria_de_lockeada_sube_version(tmp_path):
    store = JsonAnchorStore(tmp_path)
    store.save("sinnema", [make_ancla("prota", estado="lockeado")])

    editada = make_ancla(
        "prota", estado="lockeado",
        bateria=[
            make_imagen_ancla("hero_portrait"),
            make_imagen_ancla("turnaround_front"),
            make_imagen_ancla("turnaround_side"),
            make_imagen_ancla("turnaround_back"),
            make_imagen_ancla("expression_sheet"),
        ],
    )
    store.save("sinnema", [editada])

    assert store.load("sinnema")[0].version == 2


def test_lockeada_sin_cambio_de_bateria_mantiene_version(tmp_path):
    store = JsonAnchorStore(tmp_path)
    ancla = make_ancla("prota", estado="lockeado")
    store.save("sinnema", [ancla])
    store.save("sinnema", [make_ancla("prota", estado="lockeado")])

    assert store.load("sinnema")[0].version == 1


def test_borrador_editado_no_sube_version(tmp_path):
    store = JsonAnchorStore(tmp_path)
    store.save("sinnema", [make_ancla("prota", bateria=[])])
    store.save("sinnema", [make_ancla("prota", bateria=[make_imagen_ancla()])])

    assert store.load("sinnema")[0].version == 1


def test_guardar_sobre_biblioteca_corrupta_aborta(tmp_path):
    """Sin versión previa legible no se pisa la biblioteca en silencio."""
    store = JsonAnchorStore(tmp_path)
    store.save("sinnema", [make_ancla("prota", estado="lockeado")])
    (tmp_path / "sinnema" / "anclas.json").write_text("{roto", encoding="utf-8")

    with pytest.raises(RuntimeError, match="corrupta"):
        store.save("sinnema", [make_ancla("prota", estado="lockeado")])


def test_fallo_de_disco_al_guardar_no_tumba(tmp_path, caplog, monkeypatch):
    """Espejo del lore: un OSError al persistir deja warning y sigue (el error
    accionable para la persona detrás de la acción lo levanta la capa API)."""
    store = JsonAnchorStore(tmp_path)

    def _disco_lleno(*_a, **_k):
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(Path, "write_text", _disco_lleno)
    with caplog.at_level(logging.WARNING, logger="sinnema.anclas"):
        store.save("sinnema", [make_ancla("prota")])

    assert "No se pudo persistir la biblioteca" in caplog.text


# --------------------- Localización de media (Fase 1) ---------------------


def test_carpeta_y_ruta_de_imagen_validas(tmp_path):
    store = JsonAnchorStore(tmp_path)
    carpeta = store.carpeta_de_ancla("sinnema", "prota")
    assert carpeta == tmp_path / "sinnema" / "prota"

    ruta = store.ruta_imagen("sinnema", "prota", "hero_portrait_1.png")
    assert ruta == (tmp_path / "sinnema" / "prota" / "hero_portrait_1.png").resolve()


@pytest.mark.parametrize(
    "archivo", ["../escape.png", "sub/dir.png", "/absoluta.png", "..", ".", ".oculta"]
)
def test_ruta_de_imagen_rechaza_traversal(tmp_path, archivo):
    store = JsonAnchorStore(tmp_path)
    with pytest.raises(ValueError, match="nombre simple"):
        store.ruta_imagen("sinnema", "prota", archivo)


def test_ruta_de_imagen_rechaza_symlink_que_escapa(tmp_path):
    store = JsonAnchorStore(tmp_path)
    carpeta = tmp_path / "sinnema" / "prota"
    carpeta.mkdir(parents=True)
    secreto = tmp_path / "fuera-de-la-raiz.txt"
    secreto.write_text("dato fuera de la biblioteca", encoding="utf-8")
    (carpeta / "trap.png").symlink_to(secreto)

    with pytest.raises(ValueError, match="escapa"):
        store.ruta_imagen("sinnema", "prota", "trap.png")


@pytest.mark.parametrize("ancla_id", ["../otro", "Prota", ""])
def test_carpeta_rechaza_ancla_id_no_slug(tmp_path, ancla_id):
    with pytest.raises(ValueError, match="ancla_id"):
        JsonAnchorStore(tmp_path).carpeta_de_ancla("sinnema", ancla_id)


def test_rutas_rechazan_project_id_no_slug(tmp_path):
    store = JsonAnchorStore(tmp_path)
    with pytest.raises(ValueError, match="project_id"):
        store.load("../otro")
    with pytest.raises(ValueError, match="project_id"):
        store.ruta_imagen("../otro", "prota", "x.png")


def test_null_anchor_store_es_no_op():
    from sinnema.application.ports import NullAnchorStore

    store = NullAnchorStore()
    assert store.load("sinnema") == []
    assert store.save("sinnema", [make_ancla()]) is None
