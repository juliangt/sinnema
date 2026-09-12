"""Tests del almacén de jobs SQLite (persistencia y aislamiento por owner)."""
from __future__ import annotations

import threading

import pytest

from sinnema.infrastructure.runtime.jobs import (
    JobStatus,
    SqliteJobStore,
)


@pytest.fixture
def store(tmp_path):
    return SqliteJobStore(tmp_path / "jobs.sqlite")


def _crear(store, **overrides):
    datos = dict(owner="ana", project_id="educativo", topic="Fotosíntesis en 60s",
                 num_chapters=3, max_critique_attempts=2)
    datos.update(overrides)
    return store.create_job(**datos)


def test_create_y_get_job(store):
    job = _crear(store)
    leido = store.get_job(job.job_id)
    assert leido is not None
    assert leido.status is JobStatus.QUEUED
    assert leido.owner == "ana"
    assert leido.deliverable is None


def test_get_job_inexistente_devuelve_none(store):
    assert store.get_job("no-existe") is None


def test_list_jobs_filtra_por_owner(store):
    _crear(store)
    _crear(store, owner="beto")
    propios = store.list_jobs("ana")
    assert len(propios) == 1
    assert propios[0].owner == "ana"
    assert len(store.list_jobs()) == 2


def test_ciclo_de_vida_completo(store):
    job = _crear(store)
    store.set_status(job.job_id, JobStatus.RUNNING)
    leido = store.get_job(job.job_id)
    assert leido.status is JobStatus.RUNNING
    assert leido.started_at is not None

    entregable = {"series_title": "Prueba", "episodes": []}
    store.set_status(job.job_id, JobStatus.COMPLETED, deliverable=entregable)
    leido = store.get_job(job.job_id)
    assert leido.status is JobStatus.COMPLETED
    assert leido.finished_at is not None
    assert leido.deliverable == entregable


def test_fallo_registra_error(store):
    job = _crear(store)
    store.set_status(job.job_id, JobStatus.FAILED, error="se rompió todo")
    leido = store.get_job(job.job_id)
    assert leido.status is JobStatus.FAILED
    assert leido.error == "se rompió todo"


def test_eventos_en_orden_y_solo_nuevos(store):
    job = _crear(store)
    for i in range(3):
        store.add_event(job.job_id, "progress", f"paso {i}")
    primeros = store.events_since(job.job_id)
    assert [e.message for e in primeros] == ["paso 0", "paso 1", "paso 2"]
    siguientes = store.events_since(job.job_id, last_id=primeros[-1].id)
    assert siguientes == []


def test_concurrencia_hilos(store):
    errores = []

    def escribir(owner):
        try:
            for _ in range(20):
                job = _crear(store, owner=owner)
                store.set_status(job.job_id, JobStatus.RUNNING)
                store.add_event(job.job_id, "progress", "latido")
                store.set_status(job.job_id, JobStatus.COMPLETED)
        except Exception as exc:  # pragma: no cover
            errores.append(exc)

    hilos = [threading.Thread(target=escribir, args=(f"user{i}",)) for i in range(4)]
    for h in hilos:
        h.start()
    for h in hilos:
        h.join()
    assert errores == []
    assert len(store.list_jobs()) == 80


# ------------------- Payload y fingerprint (red-3d §6.1) -------------------


def test_add_event_con_payload_hace_roundtrip(store):
    job = _crear(store)
    store.add_event(job.job_id, "progress", "latido legacy")  # sin payload
    store.add_event(
        job.job_id, "node_start", "scriptwriter arranca",
        payload={"node": "scriptwriter", "rol": "scriptwriter", "paso": 3},
    )
    eventos = store.events_since(job.job_id)
    assert eventos[0].payload is None
    assert eventos[1].payload == {
        "node": "scriptwriter", "rol": "scriptwriter", "paso": 3,
    }


def test_spec_fingerprint_persiste(store):
    job = _crear(store)
    assert store.get_job(job.job_id).spec_fingerprint is None
    store.set_spec_fingerprint(job.job_id, "abc123")
    assert store.get_job(job.job_id).spec_fingerprint == "abc123"


def test_migracion_sobre_base_vieja(tmp_path):
    """Una base pre-migración (sin payload ni spec_fingerprint) sigue
    legible y gana las columnas nuevas sin perder datos (§12.1)."""
    import sqlite3

    ruta = tmp_path / "vieja.sqlite"
    con = sqlite3.connect(str(ruta))
    con.executescript(
        """
        CREATE TABLE jobs (
            job_id TEXT PRIMARY KEY, owner TEXT NOT NULL,
            project_id TEXT NOT NULL, topic TEXT NOT NULL,
            num_chapters INTEGER NOT NULL, max_critique_attempts INTEGER NOT NULL,
            status TEXT NOT NULL, created_at TEXT NOT NULL,
            started_at TEXT, finished_at TEXT, error TEXT, deliverable TEXT
        );
        CREATE TABLE job_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT, job_id TEXT NOT NULL,
            ts TEXT NOT NULL, kind TEXT NOT NULL, message TEXT NOT NULL
        );
        INSERT INTO jobs VALUES ('j1', 'ana', 'comida', 'Milanesas', 2, 2,
                                 'completed', '2026-01-01T00:00:00+00:00',
                                 NULL, NULL, NULL, NULL);
        INSERT INTO job_events (job_id, ts, kind, message) VALUES
            ('j1', '2026-01-01T00:00:01+00:00', 'progress', 'Paso 1'),
            ('j1', '2026-01-01T00:00:02+00:00', 'done', 'Serie completa');
        """
    )
    con.commit()
    con.close()

    store = SqliteJobStore(ruta)
    leido = store.get_job("j1")
    assert leido is not None and leido.status is JobStatus.COMPLETED
    assert leido.spec_fingerprint is None

    # Eventos históricos: payload NULL se lee como None (solo texto).
    eventos = store.events_since("j1")
    assert [e.kind for e in eventos] == ["progress", "done"]
    assert all(e.payload is None for e in eventos)

    # Y la base migrada acepta escritura nueva sin recolocar el schema.
    store.add_event("j1", "node_start", "nuevo", payload={"node": "plan_series"})
    assert store.events_since("j1")[-1].payload == {"node": "plan_series"}
    store.set_spec_fingerprint("j1", "huella")
    assert store.get_job("j1").spec_fingerprint == "huella"
