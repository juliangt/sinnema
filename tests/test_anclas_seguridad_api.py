"""Endurecimiento del serving y del upload de anclas (Fase 1 hito 3).

Casos de ataque de la spec-recursos-ancla §14 a nivel API: traversal (crudo,
``..%2f`` y ruta absoluta), symlink externo, extensiones raras, archivo por
encima del límite y nombres de archivo que nunca vienen del cliente.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from sinnema.infrastructure.anclas import JsonAnchorStore
from sinnema.infrastructure.api.app import TAMANO_MAXIMO_DE_IMAGEN, create_app
from sinnema.infrastructure.projects import ProjectFileStore
from sinnema.infrastructure.runtime.jobs import SqliteJobStore
from sinnema.infrastructure.runtime.runner import SeriesWorker

from conftest import gateway_con_serie, make_imagen_ancla

PNG = b"\x89PNG\r\n\x1a\n" + b"imagen-sintetica-de-prueba"


@pytest.fixture
def cliente_anclas(tmp_path):
    """App aislada con un proyecto editable y un ancla con una imagen."""
    store = SqliteJobStore(tmp_path / "jobs.sqlite")
    project_store = ProjectFileStore(tmp_path / "escribible", tmp_path / "empaquetado")
    worker = SeriesWorker(
        store,
        checkpoint_dir=tmp_path / "checkpoints",
        audit_root=tmp_path / "auditoria",
        lore_root=tmp_path / "continuidad",
        gateway_factory=lambda proyecto: gateway_con_serie(num_chapters=1),
        project_loader=project_store.load,
    )
    client = TestClient(create_app(
        store=store, worker=worker, data_dir=tmp_path,
        project_store=project_store,
    ))
    cuerpo = {
        "proyecto": {
            "id": "mi-show", "marca": "Mi Show",
            "concepto": "micro-videos de prueba verticales",
            "tema_por_defecto": "Un tema de prueba suficientemente largo",
            "idioma": "Español",
        },
        "voz": {
            "audiencia": "Audiencia de prueba", "contexto_cultural": "Contexto",
            "tono": "tono cercano", "guia_de_estilo": "guía de estilo",
            "restricciones": "restricciones",
        },
        "visual": {"estilo_maestro": "3D render style with clean environment and lighting"},
    }
    assert client.post("/api/projects", json=cuerpo).status_code == 201
    alta = {
        "ancla_id": "protagonista", "tipo": "personaje", "nombre": "Nita",
        "descripcion_canonica": (
            "A friendly young guide with short dark hair, teal jacket and a "
            "glowing compass pendant"
        ),
    }
    assert client.post("/api/projects/mi-show/anclas", json=alta).status_code == 201
    res = client.post(
        "/api/projects/mi-show/anclas/protagonista/imagenes",
        data={"rol": "hero_portrait"},
        files={"archivo": ("cara.png", PNG, "image/png")},
    )
    assert res.status_code == 201
    return client, tmp_path


def _servir(client, project_id="mi-show", ancla_id="protagonista", archivo="hero_portrait_1.png"):
    return client.get(f"/api/projects/{project_id}/anclas/{ancla_id}/imagenes/{archivo}")


# ------------------------- Path traversal en serving -------------------------


@pytest.mark.parametrize(
    "archivo",
    [
        "..%2fanclas.json",            # encoded ../ (el clásico §14)
        "..%5canclas.json",            # encoded backslash
        "%2e%2e%2fjugoso.toml",        # encoded ../ con puntos
        "hero_portrait_1.png%2f..%2f..%2fanclas.json",
    ],
)
def test_serving_rechaza_traversal_codificado(cliente_anclas, archivo):
    client, _ = cliente_anclas
    assert _servir(client, archivo=archivo).status_code == 404


@pytest.mark.parametrize("project_id", ["..%2fmi-show", "..%2f..%2fetc", "MI-SHOW", ""])
def test_serving_rechaza_project_id_que_escapa(cliente_anclas, project_id):
    """Sin 500 ni escape: el slug imposible cae antes de tocar disco."""
    client, _ = cliente_anclas
    res = _servir(client, project_id=project_id, archivo="x.png")
    assert res.status_code == 404


def test_serving_no_confunde_ancla_con_ruta(cliente_anclas):
    client, _ = cliente_anclas
    res = _servir(client, ancla_id="..%2fotro-proyecto", archivo="x.png")
    assert res.status_code == 404


def test_serving_symlink_externo_rechazado_y_interno_permitido(cliente_anclas, tmp_path):
    """§14: un symlink registrado que apunta fuera se rechaza; uno que queda
    dentro de la carpeta del ancla sigue sirviendo (contención real)."""
    client, tmp_path = cliente_anclas
    carpeta = tmp_path / "anclas" / "mi-show" / "protagonista"

    secreto = tmp_path / "fuera-de-la-raiz.txt"
    secreto.write_text("dato fuera de la biblioteca", encoding="utf-8")

    almacen = JsonAnchorStore(tmp_path / "anclas")
    anclas = almacen.load("mi-show")
    anclas[0].bateria += [
        make_imagen_ancla("hero_portrait", archivo="trap.png"),
        make_imagen_ancla("turnaround_front", archivo="gemelo.png"),
    ]
    almacen.save("mi-show", anclas)
    (carpeta / "trap.png").symlink_to(secreto)                      # escapa
    (carpeta / "gemelo.png").symlink_to(carpeta / "hero_portrait_1.png")  # interno

    assert _servir(client, archivo="trap.png").status_code == 404
    ok = _servir(client, archivo="gemelo.png")
    assert ok.status_code == 200
    assert ok.content == PNG


def test_serving_de_archivo_registrado_sin_formato_de_imagen(cliente_anclas):
    """Lista blanca de content-types: aunque alguien siembre a mano un
    registro con extensión no imagen, el serving no lo sirve."""
    client, tmp_path = cliente_anclas
    almacen = JsonAnchorStore(tmp_path / "anclas")
    anclas = almacen.load("mi-show")
    anclas[0].bateria.append(make_imagen_ancla("expression_sheet", archivo="leeme.txt"))
    almacen.save("mi-show", anclas)

    assert _servir(client, archivo="leeme.txt").status_code == 404


# -------------------------- Uploads hostiles --------------------------


def test_upload_con_nombre_hostil_genera_nombre_del_servidor(cliente_anclas, tmp_path):
    """El nombre del archivo lo genera siempre el servidor: un filename de
    cliente con traversal no se usa ni escapa de la carpeta del ancla."""
    client, tmp_path = cliente_anclas
    res = client.post(
        "/api/projects/mi-show/anclas/protagonista/imagenes",
        data={"rol": "turnaround_side"},
        files={"archivo": ("../../escape.png", PNG, "image/png")},
    )
    assert res.status_code == 201
    assert res.json()["bateria"][-1]["archivo"] == "turnaround_side_1.png"

    carpeta = tmp_path / "anclas" / "mi-show" / "protagonista"
    assert (carpeta / "turnaround_side_1.png").is_file()
    # Nada escrito fuera de la carpeta del ancla.
    assert sorted(p.name for p in (tmp_path / "anclas" / "mi-show").iterdir()) == [
        "anclas.json", "protagonista",
    ]
    assert not (tmp_path / "escape.png").exists()


def test_upload_al_limite_exacto_de_tamanio(cliente_anclas):
    client, _ = cliente_anclas
    justo = b"0" * TAMANO_MAXIMO_DE_IMAGEN
    res = client.post(
        "/api/projects/mi-show/anclas/protagonista/imagenes",
        data={"rol": "expression_sheet"},
        files={"archivo": ("justo.png", justo, "image/png")},
    )
    assert res.status_code == 201

    res = client.post(
        "/api/projects/mi-show/anclas/protagonista/imagenes",
        data={"rol": "outfit_variant"},
        files={"archivo": ("pasado.png", justo + b"0", "image/png")},
    )
    assert res.status_code == 413


def test_alta_con_ancla_id_traversal_da_400(cliente_anclas):
    client, _ = cliente_anclas
    res = client.post("/api/projects/mi-show/anclas", json={
        "ancla_id": "../otro", "tipo": "lugar", "nombre": "Travesía",
        "descripcion_canonica": "A place descriptor in plain english text",
    })
    assert res.status_code == 400
    assert "ancla_id" in res.json()["detail"]
