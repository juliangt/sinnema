"""Tests de la API HTTP (FastAPI TestClient) con worker real + gateway falso."""
from __future__ import annotations

import time

import pytest
from fastapi.testclient import TestClient

from sinnema.infrastructure.api.app import create_app
from sinnema.infrastructure.runtime.jobs import JobStatus, SqliteJobStore
from sinnema.infrastructure.runtime.runner import SeriesWorker
from tests.conftest import gateway_con_serie


@pytest.fixture
def cliente(tmp_path):
    store = SqliteJobStore(tmp_path / "jobs.sqlite")
    worker = SeriesWorker(
        store,
        checkpoint_dir=tmp_path / "checkpoints",
        audit_root=tmp_path / "auditoria",
        lore_root=tmp_path / "continuidad",
        gateway_factory=lambda: gateway_con_serie(num_chapters=2),
    )
    app = create_app(store=store, worker=worker, data_dir=tmp_path)
    return TestClient(app), store


def esperar(store, job_id, timeout_s=10.0):
    limite = time.monotonic() + timeout_s
    while time.monotonic() < limite:
        job = store.get_job(job_id)
        if job.status in (JobStatus.COMPLETED, JobStatus.FAILED):
            return job
        time.sleep(0.1)
    raise AssertionError("Timeout esperando el job.")


def test_health(cliente):
    client, _ = cliente
    res = client.get("/api/health")
    assert res.status_code == 200
    assert res.json()["status"] == "ok"


def test_lista_proyectos(cliente):
    client, _ = cliente
    res = client.get("/api/projects")
    assert res.status_code == 200
    ids = {p["project_id"] for p in res.json()}
    assert "educativo" in ids


def test_crear_job_y_consultar(cliente):
    client, store = cliente
    res = client.post("/api/series", json={
        "project_id": "educativo", "topic": "Fotosíntesis en 60 segundos",
        "num_chapters": 2,
    }, headers={"X-Owner": "ana"})
    assert res.status_code == 202
    job_id = res.json()["job_id"]

    job = esperar(store, job_id)
    assert job.status is JobStatus.COMPLETED

    detalle = client.get(f"/api/jobs/{job_id}").json()
    assert detalle["status"] == "completed"
    assert len(detalle["deliverable"]["episodes"]) == 2


def test_tema_vacio_usa_el_del_proyecto(cliente):
    client, store = cliente
    res = client.post("/api/series", json={
        "project_id": "educativo", "num_chapters": 1,
    })
    assert res.status_code == 202
    job_id = res.json()["job_id"]
    esperar(store, job_id)
    assert store.get_job(job_id).topic  # resolvió el tema por defecto


def test_proyecto_inexistente_devuelve_404(cliente):
    client, _ = cliente
    res = client.post("/api/series", json={"project_id": "fantasma"})
    assert res.status_code == 404
    assert "fantasma" in res.json()["detail"]


def test_listado_de_jobs_queda_acotado_por_owner(cliente):
    client, store = cliente
    r1 = client.post("/api/series", json={"project_id": "educativo", "num_chapters": 1},
                     headers={"X-Owner": "ana"})
    r2 = client.post("/api/series", json={"project_id": "educativo", "num_chapters": 1},
                     headers={"X-Owner": "beto"})
    esperar(store, r1.json()["job_id"])
    esperar(store, r2.json()["job_id"])

    propios = client.get("/api/jobs", headers={"X-Owner": "ana"}).json()
    assert len(propios) == 1
    assert propios[0]["owner"] == "ana"
    assert "deliverable" not in propios[0]  # el listado no arrastra entregables


def test_entregable_y_viewer(cliente):
    client, store = cliente
    res = client.post("/api/series", json={
        "project_id": "educativo", "topic": "Fotosíntesis en 60 segundos",
        "num_chapters": 2,
    })
    job_id = res.json()["job_id"]
    esperar(store, job_id)

    datos = client.get(f"/api/jobs/{job_id}/deliverable").json()
    assert datos["series_title"]

    viewer = client.get(f"/api/jobs/{job_id}/viewer")
    assert viewer.status_code == 200
    assert "text/html" in viewer.headers["content-type"]
    assert datos["series_title"] in viewer.text


def test_entregable_antes_de_terminar_devuelve_409(cliente):
    client, store = cliente
    res = client.post("/api/series", json={"project_id": "educativo", "num_chapters": 2})
    job_id = res.json()["job_id"]
    job = store.get_job(job_id)
    if job.status in (JobStatus.QUEUED, JobStatus.RUNNING):
        assert client.get(f"/api/jobs/{job_id}/deliverable").status_code == 409
    esperar(store, job_id)  # dejamos terminar el hilo antes de cerrar
    assert client.get(f"/api/jobs/{job_id}/deliverable").status_code == 200


def test_eventos_sse_y_fin(cliente):
    client, store = cliente
    res = client.post("/api/series", json={
        "project_id": "educativo", "topic": "Fotosíntesis en 60 segundos",
        "num_chapters": 2,
    })
    job_id = res.json()["job_id"]
    esperar(store, job_id)
    job = store.get_job(job_id)
    eventos = store.events_since(job_id)
    assert eventos[-1].kind == "done"
    assert job.status is JobStatus.COMPLETED


def test_home_sirve_la_interfaz(cliente):
    client, _ = cliente
    res = client.get("/")
    assert res.status_code == 200
    assert "Sinnema" in res.text
