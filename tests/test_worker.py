"""Tests del worker de jobs: ejecución end-to-end con gateway falso.

El worker corre de verdad (hilo + cola) pero contra un ``FakeGateway`` y
carpetas temporales: no hay LLM ni red en los tests.
"""
from __future__ import annotations

import time

import pytest

from sinnema.infrastructure.runtime.jobs import JobStatus, SqliteJobStore
from sinnema.infrastructure.runtime.runner import SeriesWorker
from tests.conftest import gateway_con_serie


class WorkerDePrueba:
    """Worker real con gateway falso y rutas temporales."""

    def __init__(self, tmp_path):
        self.store = SqliteJobStore(tmp_path / "jobs.sqlite")
        self.gateway = gateway_con_serie(num_chapters=2)
        self.proyectos_recibidos = []

        def fabrica(proyecto):
            self.proyectos_recibidos.append(proyecto)
            return self.gateway

        self.worker = SeriesWorker(
            self.store,
            checkpoint_dir=tmp_path / "checkpoints",
            audit_root=tmp_path / "auditoria",
            lore_root=tmp_path / "continuidad",
            gateway_factory=fabrica,
        )
        self.worker.start()

    def correr(self, **kwargs) -> str:
        job = self.store.create_job(**kwargs)
        self.worker.submit(job.job_id)
        for _ in range(100):  # hasta 10 s: el hilo real necesita margen
            leido = self.store.get_job(job.job_id)
            if leido.status in (JobStatus.COMPLETED, JobStatus.FAILED):
                return leido
            time.sleep(0.1)
        raise AssertionError("El job no terminó en 10 s.")


@pytest.fixture
def worker(tmp_path):
    prueba = WorkerDePrueba(tmp_path)
    yield prueba
    # sin apagado elegante: el hilo es daemon


def test_job_completo_produce_entregable(worker):
    job = worker.correr(owner="ana", project_id="educativo",
                        topic="Fotosíntesis en 60 segundos",
                        num_chapters=2, max_critique_attempts=2)
    assert job.status is JobStatus.COMPLETED
    assert job.error is None
    assert len(job.deliverable["episodes"]) == 2
    assert job.deliverable["total_chapters_planned"] == 2


def test_job_publica_eventos_de_progreso(worker):
    job = worker.correr(owner="ana", project_id="educativo",
                        topic="Fotosíntesis en 60 segundos",
                        num_chapters=2, max_critique_attempts=2)
    eventos = worker.store.events_since(job.job_id)
    mensajes = [e.message for e in eventos]
    assert any("planificando" in m for m in mensajes)
    assert any("capítulo 1/2" in m for m in mensajes)
    assert eventos[-1].kind == "done"


def test_job_fallido_reporta_error_accionable(worker):
    def gateway_roto(proyecto):
        raise RuntimeError("No hay proveedor LLM: configurá ANTHROPIC_API_KEY.")

    worker.worker._gateway_factory = gateway_roto
    job = worker.correr(owner="ana", project_id="educativo",
                        topic="Fotosíntesis en 60 segundos",
                        num_chapters=1, max_critique_attempts=1)
    assert job.status is JobStatus.FAILED
    assert "ANTHROPIC_API_KEY" in job.error


def test_la_fabrica_de_gateway_recibe_el_proyecto_del_job(worker):
    job = worker.correr(owner="ana", project_id="educativo",
                        topic="Fotosíntesis en 60 segundos",
                        num_chapters=2, max_critique_attempts=2)
    assert job.status is JobStatus.COMPLETED
    assert worker.proyectos_recibidos[-1].project_id == "educativo"


def test_proyecto_inexistente_falla_con_mensaje(worker):
    job = worker.correr(owner="ana", project_id="no-existe",
                        topic="Fotosíntesis en 60 segundos",
                        num_chapters=1, max_critique_attempts=1)
    assert job.status is JobStatus.FAILED
    assert "no-existe" in job.error
