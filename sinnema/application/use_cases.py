"""Caso de uso principal: generar una serie completa para un proyecto."""
from __future__ import annotations

import logging
from typing import Any, Callable, Dict, Iterator, List, Optional

from langgraph.checkpoint.base import BaseCheckpointSaver

from sinnema.application.graph import build_pipeline_graph
from sinnema.application.ports import (
    AuditTrailPort,
    LoreStorePort,
    NullAuditTrail,
    NullLoreStore,
    StructuredGenerationPort,
)
from sinnema.application.projects import ProjectSpec, resolver_flujo
from sinnema.application.requests import SeriesRequest, build_initial_state
from sinnema.application.settings import PipelineSettings
from sinnema.application.state import PipelineState
from sinnema.domain.constants import ALCANCE_DEFAULT
from sinnema.domain.exceptions import DomainValidationError
from sinnema.domain.models import SeriesDeliverable
from sinnema.domain.services import merge_lore

logger = logging.getLogger("sinnema.use_cases")


def build_deliverable(state: Optional[PipelineState]) -> SeriesDeliverable:
    """Consolida el estado final del grafo en el entregable de salida."""
    if state is None or state.get("series_plan") is None:
        raise DomainValidationError(
            "El estado final no contiene un plan de serie: no se puede construir "
            "el entregable."
        )
    plan = state["series_plan"]
    episodios = state.get("completed_episodes", [])
    # Solo episodios con auditoría aportan score: los proyectos sin crítico
    # reportan 0.0 en vez de un promedio inventado.
    con_auditoria = [e.audit.overall_score for e in episodios if e.audit]
    promedio = (
        round(sum(con_auditoria) / len(con_auditoria), 2)
        if con_auditoria
        else 0.0
    )
    return SeriesDeliverable(
        project_id=state["project_id"],
        language=state["language"],
        series_title=plan.series_title,
        topic=state["topic"],
        audience=state["audience"],
        style_guide=state["style_guide"],
        alcance=state.get("alcance", ALCANCE_DEFAULT),
        total_chapters_planned=len(plan.chapters),
        episodes=episodios,
        failed_chapters=state.get("failed_chapters", []),
        average_quality_score=promedio,
        lore_glossary=state.get("lore_entries", []),
    )


def limite_de_recursion(flujo, num_chapters: int, max_attempts: int) -> int:
    """Margen de pasos del grafo, derivado del flujo efectivo (§6.3).

    ``pasos_por_capitulo`` cubre el camino mínimo (contextos -> escritor ->
    transformaciones -> compuerta -> enriquecedores -> commit) y
    ``extra_por_reintento`` el ciclo de crítica (escritor -> ... -> revisor).
    """
    pasos_por_capitulo = (
        len(flujo.contexto)
        + 1  # escritor
        + len(flujo.transformaciones)
        + (1 if flujo.revisor is not None else 0)
        + len(flujo.enriquecimiento)
        + 1  # commit
    )
    extra_por_reintento = 1 + len(flujo.transformaciones) + 1  # escritor->..->revisor
    return (
        10
        + num_chapters * pasos_por_capitulo
        + num_chapters * (max_attempts + 1) * extra_por_reintento
    )


class GenerateSeriesUseCase:
    """Orquesta el grafo completo para una petición de serie de un proyecto."""

    def __init__(
        self,
        gateway: StructuredGenerationPort,
        project: ProjectSpec,
        settings: Optional[PipelineSettings] = None,
        audit: Optional[AuditTrailPort] = None,
        lore_store: Optional[LoreStorePort] = None,
        checkpointer: Optional[BaseCheckpointSaver] = None,
    ) -> None:
        self._project = project
        self._settings = settings or PipelineSettings()
        self._audit = audit or NullAuditTrail()
        self._lore_store: LoreStorePort = lore_store or NullLoreStore()
        self._graph = build_pipeline_graph(
            gateway, project, self._settings, audit=self._audit,
            checkpointer=checkpointer,
        )

    @staticmethod
    def _recursion_limit(request: SeriesRequest) -> int:
        """Margen de pasos del grafo: fórmula generalizada desde el flujo
        efectivo del proyecto (plan + capítulos + ciclos de crítica)."""
        return limite_de_recursion(
            resolver_flujo(request.project),
            request.num_chapters,
            request.max_critique_attempts,
        )

    def stream(
        self,
        request: SeriesRequest,
        thread_id: Optional[str] = None,
        on_nodo: Optional[Callable[[str, List[str], int], None]] = None,
    ) -> Iterator[PipelineState]:
        """Ejecuta el grafo cediendo el estado tras cada superstep (progreso).

        Siembra el lore persistido del proyecto como memoria inicial de la
        corrida; usar ``save_lore`` al terminar para consolidar la memoria.
        Con ``thread_id`` (y un checkpointer inyectado) el estado persiste y
        la corrida es reanudable bajo ese hilo.

        Con ``on_nodo`` (spec-red-3d §7.2) el stream suma el modo
        ``updates``: por cada nodo que corrió se invoca
        ``on_nodo(nodo, claves_actualizadas, superstep)`` — el runner lo
        traduce a los eventos ``node_start``/``node_end``. El contrato de
        salida del generador no cambia: sigue cediendo snapshots ``values``.
        """
        proyecto = request.project
        flujo = resolver_flujo(proyecto)
        self._audit.log_step(
            "solicitud",
            f"Generación solicitada para el proyecto '{proyecto.project_id}': "
            f"'{request.resolved_topic()}' ({request.num_chapters} capítulos).",
            details=[
                f"proyecto: {proyecto.project_id} ({proyecto.brand_name})",
                f"idioma: {proyecto.language}",
                f"tono de voz: {proyecto.tone_of_voice}",
                f"tema: {request.resolved_topic()}",
                f"capítulos: {request.num_chapters}",
                f"reintentos máx. de crítica: {request.max_critique_attempts}",
                f"alcance (hasta): {flujo.hasta}",
                f"flujo efectivo: {flujo.cadena()}",
                f"audiencia: {proyecto.audience}",
                f"contexto cultural: {proyecto.cultural_context}",
                f"guía de estilo: {proyecto.style_guide}",
                f"restricciones: {proyecto.constraints}",
            ],
        )
        lore_inicial = self._lore_store.load(proyecto.project_id)
        if lore_inicial:
            self._audit.log_event(
                f"Continuidad cargada: {len(lore_inicial)} entrada(s) de lore "
                "persistida(s) del proyecto."
            )
        estado_inicial = build_initial_state(request, initial_lore=lore_inicial)
        config: Dict[str, Any] = {
            "recursion_limit": self._recursion_limit(request)
        }
        if thread_id is not None:
            config["thread_id"] = thread_id
        if on_nodo is None:
            yield from self._graph.stream(estado_inicial, config=config, stream_mode="values")
            return
        superstep = 0
        for modo, datos in self._graph.stream(
            estado_inicial, config=config, stream_mode=["values", "updates"]
        ):
            if modo == "updates":
                superstep += 1
                for nodo, claves in datos.items():
                    if nodo.startswith("__"):
                        continue
                    on_nodo(nodo, list(claves.keys()), superstep)
            else:
                yield datos

    def save_lore(self, state: Optional[PipelineState]) -> None:
        """Consolida el lore acumulado de la corrida en el almacén del proyecto."""
        if state is None:
            return
        entradas = state.get("lore_entries", [])
        consolidado = merge_lore(self._lore_store.load(self._project.project_id), entradas)
        self._lore_store.save(self._project.project_id, consolidado)

    def execute(self, request: SeriesRequest) -> SeriesDeliverable:
        """Ejecuta la serie completa, persiste el lore y devuelve el entregable."""
        estado_final: Optional[PipelineState] = None
        for estado_final in self.stream(request):
            pass
        self.save_lore(estado_final)
        return build_deliverable(estado_final)
