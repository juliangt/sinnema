"""Servicio HTTP de Sinnema (FastAPI): la API y la web de usuario final.

Expone el caso de uso existente como producto distribuible:

- ``POST /api/series``               crea un job de generación y lo encola,
- ``GET  /api/jobs/{id}``            consulta el estado y el entregable,
- ``GET  /api/jobs/{id}/events``     progreso en vivo (Server-Sent Events),
- ``GET  /api/jobs/{id}/viewer``     visor HTML del entregable,
- ``GET  /api/projects``             los shows disponibles,
- ``POST/PUT/DELETE /api/projects``  gestión de proyectos vía archivos TOML,
- ``GET  /api/projects/{id}/prompts`` vista previa de prompts compuestos,
- ``GET  /api/projects/{id}/flujo-efectivo`` fases resueltas + hito + Mermaid,
- ``GET/DELETE /api/projects/{id}/lore`` memoria de continuidad,
- ``GET  /api/meta/roles``           catálogo de agentes para el formulario,
- ``GET  /``                         la interfaz web (gestión + generación).

Los proyectos viven en archivos TOML (fuente de verdad): la API los lee y
escribe con escritura atómica; cada job carga el spec vigente al arrancar.

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

from sinnema.application.graph import build_pipeline_graph
from sinnema.application.ports import ROLE_PLANNER, ROLE_SCRIPTWRITER
from sinnema.application.projects import ROLES_ESENCIALES, resolver_flujo
from sinnema.application.prompts import build_role_system_prompts
from sinnema.application.registry import AGENT_REGISTRY
from sinnema.application.requests import MAX_CRITIQUE_ATTEMPTS_LIMIT
from sinnema.application.use_cases import limite_de_recursion
from sinnema.domain.constants import SERIES_MAX_CHAPTERS
from sinnema.infrastructure.api.viewer import render_deliverable_html
from sinnema.infrastructure.llm.providers import DEFAULT_ROLE_SPECS
from sinnema.infrastructure.lore import JsonLoreStore
from sinnema.infrastructure.projects import (
    ProjectFileStore,
    packaged_projects_dir,
    resolve_writable_projects_dir,
)
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
    max_critique_attempts: Optional[int] = Field(
        None, ge=1, le=MAX_CRITIQUE_ATTEMPTS_LIMIT,
        description="Vacío = default del proyecto (sección [pipeline]) o 2.",
    )


def create_app(
    store: Optional[SqliteJobStore] = None,
    worker: Optional[SeriesWorker] = None,
    data_dir: Optional[Path] = None,
    project_store: Optional[ProjectFileStore] = None,
) -> FastAPI:
    """Fábrica de la aplicación (permite inyectar dobles en tests)."""
    data_dir = Path(data_dir) if data_dir else DEFAULT_DATA_DIR
    store = store or SqliteJobStore(data_dir / "jobs.sqlite")
    if project_store is None:
        escribible = resolve_writable_projects_dir(data_dir)
        empaquetado = packaged_projects_dir()
        project_store = ProjectFileStore(
            escribible,
            builtin_dir=empaquetado if empaquetado != escribible else None,
        )
    worker = worker or SeriesWorker(
        store,
        checkpoint_dir=data_dir / "checkpoints",
        audit_root=data_dir / "auditoria",
        lore_root=data_dir / "continuidad",
        project_loader=project_store.load,
    )
    lore_store = JsonLoreStore(root=data_dir / "continuidad")
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

    def _proyecto_o_404(project_id: str):
        """Carga el ProjectSpec; 404 si no existe, 400 si el TOML es inválido."""
        try:
            return project_store.load(project_id)
        except FileNotFoundError as exc:
            raise HTTPException(404, str(exc)) from exc
        except RuntimeError as exc:
            raise HTTPException(400, str(exc)) from exc

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
                "concepto": p.show_concept,
                "default_topic": p.default_topic,
                "audience": p.audience,
                "language": p.language,
                "editable": project_store.is_editable(p.project_id),
            }
            for p in project_store.list_merged()
        ]

    @app.get("/api/projects/{project_id}")
    def get_project(project_id: str) -> dict:
        try:
            crudo = project_store.read_raw(project_id)
        except FileNotFoundError as exc:
            raise HTTPException(404, str(exc)) from exc
        crudo["editable"] = project_store.is_editable(project_id)
        return crudo

    @app.post("/api/projects", status_code=201)
    def create_project(cuerpo: dict) -> dict:
        try:
            spec = project_store.create(cuerpo)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        except FileExistsError as exc:
            raise HTTPException(409, str(exc)) from exc
        return {"project_id": spec.project_id, "creado": True}

    @app.put("/api/projects/{project_id}")
    def update_project(project_id: str, cuerpo: dict) -> dict:
        try:
            project_store.update(project_id, cuerpo)
        except FileNotFoundError as exc:
            raise HTTPException(404, str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        return {"project_id": project_id, "actualizado": True}

    @app.delete("/api/projects/{project_id}")
    def delete_project(project_id: str) -> dict:
        activos = [
            j for j in store.list_jobs(project_id=project_id)
            if j.status in (JobStatus.QUEUED, JobStatus.RUNNING)
        ]
        if activos:
            raise HTTPException(
                409,
                f"El proyecto '{project_id}' tiene {len(activos)} job(s) en cola "
                "o en ejecución: esperá a que terminen antes de borrarlo.",
            )
        try:
            project_store.delete(project_id)
        except FileNotFoundError as exc:
            raise HTTPException(404, str(exc)) from exc
        return {"project_id": project_id, "borrado": True}

    @app.get("/api/projects/{project_id}/prompts")
    def project_prompts(project_id: str) -> dict:
        proyecto = _proyecto_o_404(project_id)
        return build_role_system_prompts(proyecto)

    @app.get("/api/projects/{project_id}/flujo-efectivo")
    def project_flujo_efectivo(project_id: str) -> dict:
        """Fases resueltas del proyecto, hito, límite de recursión y Mermaid.

        Compila el grafo efectivo con un gateway nulo (nunca genera contenido)
        para obtener el diagrama Mermaid, como el modo diagrama de
        ``scripts/ver_grafo.py``. El límite de recursión se estima con los
        defaults de corrida (3 capítulos, 2 reintentos de crítica).
        """
        proyecto = _proyecto_o_404(project_id)
        flujo = resolver_flujo(proyecto)

        class _GatewayNulo:  # el diagrama nunca genera contenido
            def generate(self, *_a, **_k):  # pragma: no cover
                raise RuntimeError("El diagrama del grafo no ejecuta el pipeline.")

        grafo = build_pipeline_graph(_GatewayNulo(), proyecto)
        return {
            "project_id": proyecto.project_id,
            "declarado": flujo.declarado,
            "hasta": flujo.hasta,
            "fases": {
                "serie": [ROLE_PLANNER],
                "contexto": list(flujo.contexto),
                "escritor": [ROLE_SCRIPTWRITER],
                "transformaciones": list(flujo.transformaciones),
                "revisor": flujo.revisor,
                "enriquecimiento": list(flujo.enriquecimiento),
            },
            "limite_recursion": limite_de_recursion(flujo, 3, 2),
            "mermaid": grafo.get_graph().draw_mermaid(),
        }

    @app.get("/api/projects/{project_id}/lore")
    def project_lore(project_id: str) -> list[dict]:
        _proyecto_o_404(project_id)
        try:
            entradas = lore_store.load(project_id)
        except RuntimeError as exc:
            raise HTTPException(409, str(exc)) from exc
        return [e.model_dump(mode="json") for e in entradas]

    @app.delete("/api/projects/{project_id}/lore")
    def reset_project_lore(project_id: str) -> dict:
        _proyecto_o_404(project_id)
        lore_store.save(project_id, [])
        return {"project_id": project_id, "lore": []}

    @app.get("/api/meta/roles")
    def meta_roles() -> list[dict]:
        """Catálogo de agentes desde el registro (rol, tipo, descripción,
        esencial) con los defaults LLM de ``DEFAULT_ROLE_SPECS``."""
        defaults = {s.role: s for s in DEFAULT_ROLE_SPECS}
        respuesta = []
        for rol, definicion in AGENT_REGISTRY.items():
            item = {
                "rol": rol,
                "tipo": definicion.tipo,
                "descripcion": definicion.descripcion,
                "esencial": definicion.esencial,
                "desactivable": rol not in ROLES_ESENCIALES,
            }
            default = defaults.get(rol)
            if default is not None:
                item.update(
                    proveedor=default.provider,
                    modelo=default.model,
                    temperatura=default.temperature,
                )
            respuesta.append(item)
        return respuesta

    @app.post("/api/series", status_code=202)
    def create_series(cuerpo: SeriesRequestBody, x_owner: Optional[str] = Header(None)) -> dict:
        proyecto = _proyecto_o_404(cuerpo.project_id)
        tema = (cuerpo.topic or "").strip() or proyecto.default_topic
        intentos = (
            cuerpo.max_critique_attempts
            if cuerpo.max_critique_attempts is not None
            else (proyecto.pipeline.intentos_maximos_de_critica or 2)
        )
        job = store.create_job(
            owner=_owner(x_owner),
            project_id=proyecto.project_id,
            topic=tema,
            num_chapters=cuerpo.num_chapters,
            max_critique_attempts=intentos,
        )
        worker.submit(job.job_id)
        return {"job_id": job.job_id, "status": job.status.value}

    @app.get("/api/jobs")
    def jobs(
        x_owner: Optional[str] = Header(None),
        project_id: Optional[str] = None,
    ) -> list[dict]:
        owner = _owner(x_owner)
        return [
            j.to_dict(with_deliverable=False)
            for j in store.list_jobs(owner, project_id=project_id)
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
