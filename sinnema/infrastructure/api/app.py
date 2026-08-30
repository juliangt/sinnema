"""Servicio HTTP de Sinnema (FastAPI): la API y la web de usuario final.

Expone el caso de uso existente como producto distribuible:

- ``POST /api/series``       crea un job de generación y lo encola,
- ``GET  /api/jobs/{id}``    consulta el estado y el entregable,
- ``GET  ``/api/jobs/{id}/events``  progreso en vivo (Server-Sent Events),
- ``GET  /api/jobs/{id}/viewer``    visor HTML del entregable,
- ``GET  /api/projects``     los shows disponibles,
- ``GET  /``                 la interfaz web (formulario + progreso).

El aislamiento por usuario es básico (header ``X-Owner``): los listados se
filtran por propietario. Autenticación real, rate limiting y TLS quedan para
el reverse proxy / capa de despliegue.
"""
from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path
from typing import Optional

import uvicorn
from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import (
    FileResponse,
    HTMLResponse,
    JSONResponse,
    StreamingResponse,
)
from pydantic import BaseModel, Field

from sinnema.application.requests import MAX_CRITIQUE_ATTEMPTS_LIMIT
from sinnema.domain.constants import SERIES_MAX_CHAPTERS
from sinnema.infrastructure.api.viewer import render_deliverable_html
from sinnema.infrastructure.projects import list_projects, load_project
from sinnema.infrastructure.runtime.jobs import (
    TERMINAL_STATUSES,
    Job,
    JobStatus,
    SqliteJobStore,
)
from sinnema.infrastructure.runtime.runner import SeriesWorker

logger = logging.getLogger("sinnema.api")

STATIC_DIR = Path(__file__).resolve().parent / "static"

#: Raíz de datos del servicio (jobs, checkpoints, auditoría, lore, salidas).
DEFAULT_DATA_DIR = Path(
    os.environ.get("SINNEMA_DATA_DIR", "datos-servidor")
)


class SeriesRequestBody(BaseModel):
    """Cuerpo de ``POST /api/series``."""

    project_id: str = Field(..., min_length=1)
    topic: Optional[str] = Field(None, description="Vacío = tema por defecto del proyecto.")
    num_chapters: int = Field(3, ge=1, le=SERIES_MAX_CHAPTERS)
    max_critique_attempts: int = Field(2, ge=1, le=MAX_CRITIQUE_ATTEMPTS_LIMIT)


def create_app(
    store: Optional[SqliteJobStore] = None,
    worker: Optional[SeriesWorker] = None,
    data_dir: Optional[Path] = None,
) -> FastAPI:
    """Fábrica de la aplicación (permite inyectar dobles en tests)."""
    data_dir = Path(data_dir) if data_dir else DEFAULT_DATA_DIR
    store = store or SqliteJobStore(data_dir / "jobs.sqlite")
    worker = worker or SeriesWorker(
        store,
        checkpoint_dir=data_dir / "checkpoints",
        audit_root=data_dir / "auditoria",
        lore_root=data_dir / "continuidad",
    )
    worker.start()

    app = FastAPI(title="Sinnema", version="0.1.0",
                  description="Motor multi-agente de series de micro-videos verticales.")

    def _owner(x_owner: Optional[str]) -> str:
        return (x_owner or "anon").strip()[:60] or "anon"

    def _job_or_404(job_id: str) -> Job:
        job = store.get_job(job_id)
        if job is None:
            raise HTTPException(404, f"No existe el job '{job_id}'.")
        return job

    # --------------------------------- API ---------------------------------

    @app.get("/api/health")
    def health() -> dict:
        return {
            "status": "ok",
            "worker_activo": worker._thread is not None and worker._thread.is_alive(),
            "jobs_en_cola": worker.pending(),
        }

    @app.get("/api/projects")
    def projects() -> list[dict]:
        return [
            {
                "project_id": p.project_id,
                "brand_name": p.brand_name,
                "default_topic": p.default_topic,
                "audience": p.audience,
                "language": p.language,
            }
            for p in list_projects()
        ]

    @app.post("/api/series", status_code=202)
    def create_series(cuerpo: SeriesRequestBody, x_owner: Optional[str] = Header(None)) -> dict:
        try:
            proyecto = load_project(cuerpo.project_id)
        except RuntimeError as exc:
            raise HTTPException(404, str(exc)) from exc
        tema = (cuerpo.topic or "").strip() or proyecto.default_topic
        job = store.create_job(
            owner=_owner(x_owner),
            project_id=proyecto.project_id,
            topic=tema,
            num_chapters=cuerpo.num_chapters,
            max_critique_attempts=cuerpo.max_critique_attempts,
        )
        worker.submit(job.job_id)
        return {"job_id": job.job_id, "status": job.status.value}

    @app.get("/api/jobs")
    def jobs(x_owner: Optional[str] = Header(None)) -> list[dict]:
        owner = _owner(x_owner)
        return [
            j.to_dict(with_deliverable=False)
            for j in store.list_jobs(owner)
            if j.owner == owner
        ]

    @app.get("/api/jobs/{job_id}")
    def get_job(job_id: str) -> dict:
        return _job_or_404(job_id).to_dict()

    @app.get("/api/jobs/{job_id}/events")
    async def job_events(job_id: str) -> StreamingResponse:
        """Progreso en vivo vía Server-Sent Events (stream de eventos JSON)."""
        _job_or_404(job_id)

        async def stream():
            last_id = 0
            while True:
                eventos = store.events_since(job_id, last_id)
                for ev in eventos:
                    last_id = ev.id
                    yield f"id: {ev.id}\nevent: {ev.kind}\ndata: {ev.message}\n\n"
                job = store.get_job(job_id)
                if job is not None and job.status in TERMINAL_STATUSES and not eventos:
                    yield "event: end\ndata: fin\n\n"
                    return
                await asyncio.sleep(0.5)

        return StreamingResponse(
            stream(), media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    @app.get("/api/jobs/{job_id}/deliverable")
    def job_deliverable(job_id: str):
        job = _job_or_404(job_id)
        if job.deliverable is None:
            raise HTTPException(
                409, f"El job '{job_id}' aún no tiene entregable "
                     f"(estado: {job.status.value})."
            )
        return JSONResponse(content=job.deliverable)

    @app.get("/api/jobs/{job_id}/viewer", response_class=HTMLResponse)
    def job_viewer(job_id: str):
        job = _job_or_404(job_id)
        if job.deliverable is None:
            raise HTTPException(
                409, f"El job '{job_id}' aún no tiene entregable "
                     f"(estado: {job.status.value})."
            )
        return HTMLResponse(render_deliverable_html(job.deliverable))

    # --------------------------------- web ---------------------------------

    @app.get("/", response_class=HTMLResponse)
    def index() -> FileResponse:
        return FileResponse(STATIC_DIR / "index.html")

    return app


def main() -> int:
    """Entry point ``sinnema-server``: levanta la API + web."""
    logging.basicConfig(
        level=os.environ.get("SINNEMA_LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)-7s %(name)s | %(message)s",
        datefmt="%H:%M:%S",
    )
    host = os.environ.get("SINNEMA_HOST", "127.0.0.1")
    port = int(os.environ.get("SINNEMA_PORT", "8000"))
    app = create_app()
    print(f"Sinnema sirviendo en http://{host}:{port}")
    uvicorn.run(app, host=host, port=port, log_level="warning")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
