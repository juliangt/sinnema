"""Worker en proceso que ejecuta los jobs de generación encolados.

Modelo de ejecución: una cola + un hilo. La API encola ids de job; el worker
los consume uno a uno, compila el caso de uso con un checkpointer SQLite por
corrida (estado reanudable) y va publicando latidos de progreso en el store.

Este runner mantiene el servicio funcional sin dependencias de infraestructura
externa. Para escalar horizontalmente basta reemplazar la cola por un broker
(Celery/RQ/SQS) y este hilo por workers separados: los límites ya están en
los puertos.
"""
from __future__ import annotations

import inspect
import json
import logging
import queue
import sqlite3
import threading
from pathlib import Path
from typing import Callable, Optional

from langgraph.checkpoint.sqlite import SqliteSaver

from sinnema.application.registry import definiciones_del_proyecto
from sinnema.application.projects import ProjectSpec
from sinnema.application.requests import SeriesRequest
from sinnema.application.settings import PipelineSettings
from sinnema.application.use_cases import GenerateSeriesUseCase, build_deliverable
from sinnema.application.state import PipelineState
from sinnema.infrastructure.audit import FilesystemAuditTrail
from sinnema.infrastructure.llm.gateway import build_gateway
from sinnema.infrastructure.llm.tools import construir_tools_por_rol
from sinnema.infrastructure.lore import JsonLoreStore
from sinnema.infrastructure.projects import load_project
from sinnema.infrastructure.projects.store import fingerprint_spec
from sinnema.infrastructure.runtime.jobs import (
    JobStatus,
    SqliteJobStore,
)

logger = logging.getLogger("sinnema.worker")

#: (kind, message[, payload]): payload solo en los kinds estructurados (§6.1).
EventSink = Callable[..., None]


def describe_progress(paso: int, state: PipelineState) -> str:
    """Traduce un snapshot del grafo a un mensaje de progreso humano."""
    plan = state.get("series_plan")
    if plan is None:
        return f"Paso {paso}: planificando la serie..."
    total = len(plan.chapters)
    indice = min(state.get("current_chapter_index", 0), total - 1)
    capitulo = plan.chapters[indice]
    episodios = len(state.get("completed_episodes", []))
    return (
        f"Paso {paso}: capítulo {indice + 1}/{total} '{capitulo.title}' "
        f"· intentos de crítica: {state.get('critique_attempts', 0)} "
        f"· episodios listos: {episodios}"
    )


class SeriesWorker:
    """Consume la cola de jobs y ejecuta el pipeline completo por cada uno."""

    def __init__(
        self,
        store: SqliteJobStore,
        checkpoint_dir: Path,
        audit_root: Path = Path("auditoria"),
        lore_root: Path = Path("continuidad"),
        gateway_factory: Optional[Callable[["ProjectSpec"], object]] = None,
        project_loader: Optional[Callable[[str], ProjectSpec]] = None,
        spec_reader: Optional[Callable[[str], dict]] = None,
    ) -> None:
        self._store = store
        self._checkpoint_dir = Path(checkpoint_dir)
        self._audit_root = Path(audit_root)
        self._lore_root = Path(lore_root)
        #: Fábrica de gateway por proyecto: cada job aplica los overrides
        #: ``[agentes.<rol>]`` vigentes en el TOML al momento de arrancar.
        self._gateway_factory = gateway_factory or build_gateway
        #: Cargador de proyectos (el servicio inyecta el del almacén escribible).
        self._project_loader = project_loader or load_project
        #: Lector del dict TOML crudo, para congelar la huella del spec al
        #: arrancar (§11.4); None (CLI) = sin fingerprint.
        self._spec_reader = spec_reader
        self._queue: "queue.Queue[str]" = queue.Queue()
        self._thread: Optional[threading.Thread] = None

    # --------------------------------- API ---------------------------------

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._checkpoint_dir.mkdir(parents=True, exist_ok=True)
        self._thread = threading.Thread(
            target=self._loop, name="sinnema-worker", daemon=True
        )
        self._thread.start()

    def submit(self, job_id: str) -> None:
        """Encola un job ya creado en el store."""
        self._queue.put(job_id)

    def pending(self) -> int:
        return self._queue.qsize()

    # ------------------------------- ejecución -------------------------------

    def _loop(self) -> None:
        while True:
            job_id = self._queue.get()
            try:
                self._run_job(job_id)
            except Exception:  # noqa: BLE001 - el worker nunca muere por un job
                logger.exception("Fallo inesperado procesando el job %s.", job_id)
                self._store.set_status(
                    job_id, JobStatus.FAILED,
                    error="Fallo inesperado del worker; revisá los logs del servidor.",
                )

    def _run_job(self, job_id: str) -> None:
        job = self._store.get_job(job_id)
        if job is None:
            logger.error("Job %s inexistente en el store.", job_id)
            return

        def sink(kind: str, message: str, payload: Optional[dict] = None) -> None:
            self._store.add_event(job_id, kind, message, payload=payload)

        self._store.set_status(job_id, JobStatus.RUNNING)
        self._congelar_fingerprint(job_id)
        sink("progress", f"Job aceptado: '{job.topic}' ({job.num_chapters} capítulos).")
        try:
            deliverable = self._execute(job, sink)
            self._store.set_status(job_id, JobStatus.COMPLETED, deliverable=deliverable)
            sink("done", f"Serie completa: {len(deliverable['episodes'])} "
                         f"episodio(s) aprobado(s).")
        except Exception as exc:  # noqa: BLE001 - el fallo del job no tumba al worker
            logger.exception("El job %s falló.", job_id)
            self._store.set_status(job_id, JobStatus.FAILED, error=str(exc))
            sink("error", f"La generación falló: {exc}")

    def _congelar_fingerprint(self, job_id: str) -> None:
        """Registra sha256 del TOML con el que arranca el job (§11.4); la
        API lo compara contra el vigente para marcar ``spec_desfasado``."""
        if self._spec_reader is None:
            return
        try:
            huella = fingerprint_spec(self._spec_reader(self._store.get_job(job_id).project_id))
            self._store.set_spec_fingerprint(job_id, huella)
        except Exception:  # noqa: BLE001 - la huella no debe tumbar el job
            logger.warning(
                "No se pudo congelar el spec_fingerprint del job %s.", job_id,
                exc_info=True,
            )

    def _execute(self, job, sink: EventSink) -> dict:
        proyecto = self._project_loader(job.project_id)
        request = SeriesRequest(
            project=proyecto,
            topic=job.topic if job.topic else None,
            num_chapters=job.num_chapters,
            max_critique_attempts=job.max_critique_attempts,
        )
        request.validate()

        sink("progress", "Configurando proveedores LLM del proyecto...")
        gateway = self._gateway_factory(proyecto)

        marca = job.job_id
        audit = FilesystemAuditTrail(self._audit_root / job.project_id / f"serie_{marca}")
        lore_store = JsonLoreStore(root=self._lore_root)
        checkpoint_path = self._checkpoint_dir / f"{marca}.sqlite"
        conn = sqlite3.connect(str(checkpoint_path), check_same_thread=False)
        try:
            checkpointer = SqliteSaver(conn)

            # Streaming del job (§7.1): el gateway emite (rol, evento) y el
            # runner los publica como eventos `token` con el nodo resuelto
            # desde el rol (la misma correspondencia que anota /red).
            nodo_a_rol = {
                definicion.nodo: rol
                for rol, definicion in definiciones_del_proyecto(proyecto).items()
            }
            rol_a_nodo = {rol: nodo for nodo, rol in nodo_a_rol.items()}

            def sink_generacion(rol: str, evento: dict) -> None:
                tipo = evento.get("tipo")
                base = {"node": rol_a_nodo.get(rol), "rol": rol}
                if tipo == "token":
                    sink(
                        "token", f"{rol} emite texto",
                        payload={**base, "texto": evento.get("texto", "")},
                    )
                elif tipo == "tool_start":
                    sink(
                        "tool_start", f"{rol} invoca {evento.get('tool')}",
                        payload={
                            **base, "tool": evento.get("tool"),
                            "args": evento.get("args"),
                        },
                    )
                elif tipo == "tool_end":
                    sink(
                        "tool_end", f"{rol}: {evento.get('tool')} devolvió",
                        payload={
                            **base, "tool": evento.get("tool"),
                            "resumen": evento.get("resumen", ""),
                        },
                    )

            # La factory puede ser la build_gateway del sistema (que acepta
            # event_sink y tools) o una inyectada por tests/CLI con firma
            # (proyecto): se le pasan solo los kwargs que declare.
            kwargs: dict = {}
            try:
                parametros = inspect.signature(self._gateway_factory).parameters
                acepta = lambda nombre: nombre in parametros or any(  # noqa: E731
                    p.kind is inspect.Parameter.VAR_KEYWORD
                    for p in parametros.values()
                )
                if acepta("event_sink"):
                    kwargs["event_sink"] = sink_generacion
                if acepta("tools"):
                    kwargs["tools"] = construir_tools_por_rol(proyecto, lore_store)
            except (TypeError, ValueError):
                pass
            gateway = self._gateway_factory(proyecto, **kwargs)
            use_case = GenerateSeriesUseCase(
                gateway, proyecto,
                settings=PipelineSettings(
                    max_critique_attempts=job.max_critique_attempts,
                    retry_exhaustion_policy=(
                        proyecto.pipeline.politica_al_agotar or "force_accept"
                    ),
                ),
                audit=audit, lore_store=lore_store, checkpointer=checkpointer,
            )
            # Eventos por nodo (§7.2): el use case reporta qué nodos corrieron
            # por superstep y el runner los publica como node_start/node_end
            # con el rol y el paso; el texto `progress` se conserva como hoy.
            def on_nodo(nodo: str, claves: list, superstep: int) -> None:
                base = {
                    "node": nodo,
                    "rol": nodo_a_rol.get(nodo),
                    "paso": superstep,
                }
                sink("node_start", f"{nodo}: en marcha", dict(base))
                fin = dict(base)
                fin["claves"] = claves
                sink("node_end", f"{nodo}: terminó", fin)

            estado_final: Optional[PipelineState] = None
            for paso, snapshot in enumerate(
                use_case.stream(request, thread_id=job.job_id, on_nodo=on_nodo), start=1
            ):
                estado_final = snapshot
                sink("progress", describe_progress(paso, estado_final))
            deliverable = build_deliverable(estado_final)
            use_case.save_lore(estado_final)
            return deliverable.model_dump(mode="json")
        finally:
            conn.close()


def dump_deliverable_json(deliverable: dict, ruta: Path) -> None:
    """Exporta el entregable de un job completado como archivo JSON."""
    ruta.parent.mkdir(parents=True, exist_ok=True)
    ruta.write_text(
        json.dumps(deliverable, ensure_ascii=False, indent=2), encoding="utf-8"
    )
