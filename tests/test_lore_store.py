"""Tests del almacén de lore persistente (JsonLoreStore) y su integración."""
from __future__ import annotations

import json

import pytest

from sinnema.application.use_cases import GenerateSeriesUseCase
from sinnema.infrastructure.lore import JsonLoreStore

from conftest import gateway_con_serie, make_lore_entry, make_project, make_request


def test_carga_sin_archivo_devuelve_memoria_vacia(tmp_path):
    store = JsonLoreStore(tmp_path)
    assert store.load("sinnema") == []


def test_guardar_y_cargar_roundtrip(tmp_path):
    store = JsonLoreStore(tmp_path)
    entradas = [make_lore_entry("modelo"), make_lore_entry("entrenamiento")]

    store.save("sinnema", entradas)

    assert [e.term for e in store.load("sinnema")] == ["modelo", "entrenamiento"]
    volcado = json.loads((tmp_path / "sinnema" / "lore.json").read_text(encoding="utf-8"))
    assert len(volcado) == 2


def test_los_proyectos_no_pisan_el_lore_del_otro(tmp_path):
    store = JsonLoreStore(tmp_path)
    store.save("sinnema", [make_lore_entry("modelo")])
    store.save("motores", [make_lore_entry("par motor")])

    assert [e.term for e in store.load("sinnema")] == ["modelo"]
    assert [e.term for e in store.load("motores")] == ["par motor"]


def test_lore_corrupto_falla_en_voz_alta(tmp_path):
    ruta = tmp_path / "sinnema" / "lore.json"
    ruta.parent.mkdir(parents=True)
    ruta.write_text("{esto no es json valido", encoding="utf-8")

    with pytest.raises(RuntimeError, match="corrupto"):
        JsonLoreStore(tmp_path).load("sinnema")


def test_lore_con_entradas_invalidas_falla_en_voz_alta(tmp_path):
    ruta = tmp_path / "sinnema" / "lore.json"
    ruta.parent.mkdir(parents=True)
    ruta.write_text(json.dumps([{"term": "sin los demas campos"}]), encoding="utf-8")

    with pytest.raises(RuntimeError, match="corrupto"):
        JsonLoreStore(tmp_path).load("sinnema")


# --------------------- Integración: use case + lore persistente ---------------------


def test_execute_siembra_y_persiste_el_lore_del_proyecto(tmp_path):
    store = JsonLoreStore(tmp_path)
    store.save("sinnema", [make_lore_entry("modelo")])  # historia previa
    use_case = GenerateSeriesUseCase(
        gateway_con_serie(num_chapters=1), make_project(), lore_store=store
    )

    entregable = use_case.execute(make_request(num_chapters=1))

    # El lore del entregable suma la historia previa y lo nuevo de la corrida.
    terminos = {e.term for e in entregable.lore_glossary}
    assert "modelo" in terminos
    # Y queda persistido para la próxima corrida del proyecto.
    persistido = {e.term for e in store.load("sinnema")}
    assert "modelo" in persistido
    assert len(persistido) == len(terminos)


def test_corridas_consecutivas_acumulan_lore_sin_duplicar(tmp_path):
    store = JsonLoreStore(tmp_path)

    for _ in range(2):
        use_case = GenerateSeriesUseCase(
            gateway_con_serie(num_chapters=1), make_project(), lore_store=store
        )
        use_case.execute(make_request(num_chapters=1))

    # La segunda corrida siembra el lore de la primera: los mismos conceptos
    # no se duplican (dedup case-insensitive) ni se pierden.
    terminos = [e.term for e in store.load("sinnema")]
    assert len(terminos) == len({t.lower() for t in terminos})
    assert set(terminos) == {"concepto 1a", "concepto 1b", "término nuevo 1"}
