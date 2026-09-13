"""Eventos ``media_start``/``media_end`` de la Fase 3 llegando al stream SSE
(spec-recursos-ancla §6/§9.1; mismos registros del job que token/tool_*).

Worker REAL (hilo + cola) con gateway falso y puerto de media falso: sin red,
sin claves, sin SDKs. La fábrica de dependencias es la real del sistema
(``construir_dependencias_de_media``) con el puerto reemplazado por el doble:
así el test cubre el wiring completo (None sin keyframes → cero eventos).
"""
from __future__ import annotations

import time
from dataclasses import replace
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from sinnema.infrastructure.anclas import JsonAnchorStore
from sinnema.infrastructure.api.app import create_app
from sinnema.infrastructure.media import (
    AlmacenMedia,
    construir_dependencias_de_media,
)
from sinnema.infrastructure.projects import ProjectFileStore
from sinnema.infrastructure.runtime.jobs import JobStatus, SqliteJobStore
from sinnema.infrastructure.runtime.runner import SeriesWorker

from conftest import gateway_con_serie
from tests.test_media_pipeline import PuertoMediaFalso


def _esperar(store, job_id, timeout_s=10.0):
    limite = time.monotonic() + timeout_s
    while time.monotonic() < limite:
        job = store.get_job(job_id)
        if job.status in (JobStatus.COMPLETED, JobStatus.FAILED):
            return job
        time.sleep(0.1)
    raise AssertionError("Timeout esperando el job.")


def _proyecto_json(id: str, media: dict | None) -> dict:
    datos = {
        "proyecto": {
            "id": id,
            "marca": "Show de Media",
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
    if media is not None:
        datos["media"] = media
    return datos


class ServicioDeMedia:
    """App real + worker real con puerto de media falso inyectable."""

    def __init__(self, tmp_path: Path, media: dict | None):
        self.tmp = tmp_path
        store = SqliteJobStore(tmp_path / "jobs.sqlite")
        (tmp_path / "checkpoints").mkdir(parents=True, exist_ok=True)
        project_store = ProjectFileStore(tmp_path / "escribible", tmp_path / "empaquetado")
        anchor_store = JsonAnchorStore(root=tmp_path / "anclas")
        self.puerto = PuertoMediaFalso()

        def media_factory(proyecto):
            deps = construir_dependencias_de_media(
                proyecto,
                almacen=AlmacenMedia(root=tmp_path / "media"),
                anchor_store=anchor_store,
            )
            if deps is None:
                return None
            return replace(deps, puerto=self.puerto)

        worker = SeriesWorker(
            store,
            checkpoint_dir=tmp_path / "checkpoints",
            audit_root=tmp_path / "auditoria",
            lore_root=tmp_path / "continuidad",
            anchor_root=tmp_path / "anclas",
            gateway_factory=lambda proyecto: gateway_con_serie(num_chapters=1),
            project_loader=project_store.load,
            media_factory=media_factory,
        )
        app = create_app(
            store=store, worker=worker, data_dir=tmp_path, project_store=project_store,
        )
        self.store = store
        self.client = TestClient(app)
        # Alta del proyecto con (o sin) sección [media].
        respuesta = self.client.post("/api/projects", json=_proyecto_json("media-show", media))
        assert respuesta.status_code == 201, respuesta.text

    def correr(self) -> str:
        respuesta = self.client.post("/api/series", json={
            "project_id": "media-show", "num_chapters": 1,
        }, headers={"X-Owner": "ana"})
        job_id = respuesta.json()["job_id"]
        _esperar(self.store, job_id)
        return job_id


def test_media_start_y_media_end_fluyen_hasta_el_stream_sse(tmp_path):
    servicio = ServicioDeMedia(tmp_path, media={
        "keyframes": True, "proveedor_imagen": "gemini", "encadenar_frames": True,
    })
    job_id = servicio.correr()

    with servicio.client.stream("GET", f"/api/jobs/{job_id}/events") as respuesta:
        assert respuesta.headers["content-type"].startswith("text/event-stream")
        cuerpo = "".join(respuesta.iter_text())

    assert "event: media_start" in cuerpo
    assert "event: media_end" in cuerpo
    assert '"escena": 1' in cuerpo
    assert '"proveedor": "gemini"' in cuerpo
    assert '"archivo": "media-show/ch-01/escena_1.png"' in cuerpo
    assert "event: end" in cuerpo  # el stream termina igual que siempre

    # El entregable del job lleva el adjunto media con el manifest completo.
    entregable = servicio.client.get(f"/api/jobs/{job_id}/deliverable").json()
    episodio = entregable["episodes"][0]
    adjunto = next(a for a in episodio["adjuntos"] if a["rol"] == "media")
    assert len(adjunto["artefacto"]["keyframes"]) == 6
    assert (tmp_path / "media" / "media-show" / "ch-01" / "escena_1.png").exists()


def test_proyecto_sin_media_no_emite_eventos_de_media_en_sse(tmp_path):
    servicio = ServicioDeMedia(tmp_path, media=None)
    job_id = servicio.correr()
    with servicio.client.stream("GET", f"/api/jobs/{job_id}/events") as respuesta:
        cuerpo = "".join(respuesta.iter_text())
    assert "media_start" not in cuerpo
    assert "event: end" in cuerpo


def test_catalogos_expone_proveedores_de_imagen(tmp_path):
    servicio = ServicioDeMedia(tmp_path, media=None)
    catalogos = servicio.client.get("/api/meta/catalogos").json()
    assert catalogos["proveedores_imagen"] == ["gemini", "openai"]
