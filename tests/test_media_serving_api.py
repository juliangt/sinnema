"""Serving de media del pipeline: ``GET /api/media/{ruta:path}`` (Fase 5b,
spec-recursos-ancla §9.2).

La ruta relativa de ``MediaGenerado.archivo`` se resuelve con el MISMO
``AlmacenMedia`` compartido worker/API (misma raíz de ``data_dir``), que ya
valida slugs, forma ``<project>/<chapter>/escena_<n>.<ext>``, lista blanca de
formatos y contención tras symlinks (§14, anti-traversal de la Fase 3).
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from sinnema.infrastructure.api.app import create_app
from sinnema.infrastructure.media import AlmacenMedia
from sinnema.infrastructure.runtime.jobs import SqliteJobStore
from sinnema.infrastructure.runtime.runner import SeriesWorker

PNG = b"\x89PNG\r\n\x1a\n" + b"keyframe-sintetico-de-prueba"


@pytest.fixture
def client(tmp_path):
    store = SqliteJobStore(tmp_path / "jobs.sqlite")
    worker = SeriesWorker(
        store,
        checkpoint_dir=tmp_path / "checkpoints",
        audit_root=tmp_path / "auditoria",
        lore_root=tmp_path / "continuidad",
    )
    app = create_app(store=store, worker=worker, data_dir=tmp_path)
    # Un keyframe real en la raíz de media compartida, como lo deja el nodo
    # render_keyframes (ruta relativa <project>/<chapter>/escena_<n>.<ext>).
    AlmacenMedia(root=tmp_path / "media").guardar_keyframe(
        "mi-show", "ch-01", 1, "png", PNG
    )
    return TestClient(app)


def test_sirve_un_keyframe_existente_con_content_type_y_cache(client):
    res = client.get("/api/media/mi-show/ch-01/escena_1.png")
    assert res.status_code == 200
    assert res.headers["content-type"] == "image/png"
    assert res.content == PNG
    assert res.headers["cache-control"] == "public, max-age=3600"


def test_sirve_los_formatos_de_la_lista_blanca(client, tmp_path):
    almacen = AlmacenMedia(root=tmp_path / "media")
    almacen.guardar_keyframe("mi-show", "ch-01", 2, "jpeg", b"jpeg-crudo")
    almacen.guardar_keyframe("mi-show", "ch-01", 3, "webp", b"webp-crudo")
    assert client.get("/api/media/mi-show/ch-01/escena_2.jpeg").headers[
        "content-type"
    ] == "image/jpeg"
    assert client.get("/api/media/mi-show/ch-01/escena_3.webp").headers[
        "content-type"
    ] == "image/webp"


def test_keyframe_inexistente_es_404(client):
    res = client.get("/api/media/mi-show/ch-01/escena_9.png")
    assert res.status_code == 404


@pytest.mark.parametrize(
    "ruta",
    [
        "mi-show/../../anclas.json",  # traversal crudo
        "mi-show/%2e%2e/anclas.json",  # encoded
        "..%2f..%2fanclas.json",  # el clásico §14 con raíz vacía
        "MI-SHOW/ch-01/escena_1.png",  # slug en mayúsculas: imposible
        "mi-show/ch-01/otro_1.png",  # forma de nombre fuera del almacén
    ],
)
def test_rutas_que_no_pasan_la_validacion_son_404(client, ruta):
    assert client.get(f"/api/media/{ruta}").status_code == 404


def test_extension_fuera_de_la_lista_blanca_es_404(client, tmp_path):
    """Aunque alguien siembre a mano un .txt con forma válida, el serving no
    lo sirve: la lista blanca vive en ``AlmacenMedia.ruta_de``."""
    sospechoso = tmp_path / "media" / "mi-show" / "ch-01"
    sospechoso.mkdir(parents=True, exist_ok=True)
    (sospechoso / "escena_1.txt").write_text("no soy una imagen")
    assert client.get("/api/media/mi-show/ch-01/escena_1.txt").status_code == 404
