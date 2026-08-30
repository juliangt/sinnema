"""Orquestación del pipeline multi-agente como grafo LangGraph cíclico.

Topología del grafo (cíclica):

    START
      -> plan_series            (Strategic Planner)
      -> continuity_master      (Lore Keeper)
      -> scriptwriter           (Content Creator)
      -> persona_adapter        (Audience Adapter)
      -> chief_critic           (Auditor)
           |-- revise ----------> scriptwriter   (ciclo de crítica con feedback)
           |-- force_accept ----> technical_director
           |-- skip_chapter ----> fail_chapter   (política de reintentos agotados)
      -> technical_director     (Visual/Audio Director)
      -> commit_episode         (consolida episodio + actualiza lore)
           |-- next_chapter ----> continuity_master
           |-- series_complete -> END

El grafo se compila POR PROYECTO: los nodos cierran sobre el ``ProjectSpec``
(prompts del rol + sobre editorial ``FormatProfile``).

Los nodos de agente NO se escriben a mano: ``make_agent_node`` los genera a
partir de su ``AgentDefinition`` (``sinnema.application.registry``), que
declara mensajes, validadores de dominio, cortocircuitos y actualizaciones de
estado. Quedan escritos a mano solo los nodos ESTRUCTURALES —``plan_series``,
la compuerta de revisión (``chief_critic`` y sus aristas condicionales),
``commit_episode`` y ``fail_chapter``— porque encapsulan semántica del
pipeline (iterador de capítulos, política de agotamiento, ensamblado del
entregable), no la de un agente en particular.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from sinnema.application.ports import (
    ROLE_ADAPTER,
    ROLE_CONTINUITY,
    ROLE_CRITIC,
    ROLE_DIRECTOR,
    ROLE_PLANNER,
    ROLE_SCRIPTWRITER,
    AuditTrailPort,
    NullAuditTrail,
    StructuredGenerationPort,
)
from sinnema.application.projects import ProjectSpec
from sinnema.application.registry import (
    AGENT_REGISTRY,
    AgentDefinition,
    build_role_system_prompts,
    capitulo_actual,
)
from sinnema.application.settings import PipelineSettings
from sinnema.application.state import PipelineState
from sinnema.domain.services import (
    assemble_episode,
    build_failed_record,
    extract_new_lore,
)

logger = logging.getLogger("sinnema.graph")


def make_agent_node(
    definicion: AgentDefinition,
    gateway: StructuredGenerationPort,
    project: ProjectSpec,
    system_prompts: Dict[str, str],
    audit: AuditTrailPort,
):
    """Genera el nodo del grafo para un agente a partir de su definición.

    El nodo resultante: (1) se cortocircuita con el fallback determinista de
    la definición si el proyecto desactivó el rol; (2) pide al puerto de
    generación la salida estructurada del rol; (3) aplica los validadores de
    dominio declarados ANTES de que el artefacto circule por el estado; y
    (4) escribe su slot de ``produce`` junto con las claves extra declaradas.
    """

    def _nodo_agente(state: PipelineState) -> Dict[str, Any]:
        if definicion.al_desactivar is not None and not project.agente_activo(
            definicion.rol
        ):
            logger.info(
                "Agente '%s' desactivado en el proyecto: nodo cortocircuitado.",
                definicion.rol,
            )
            if definicion.resumen_desactivado is not None:
                resumen = definicion.resumen_desactivado(state)
            else:
                resumen = (
                    f"Agente desactivado en el proyecto: {definicion.rol} "
                    "no genera su artefacto."
                )
            audit.log_step(definicion.nodo, resumen)
            return definicion.al_desactivar(state)

        mensaje = definicion.mensaje(project, state)
        artefacto = gateway.generate(
            definicion.rol,
            definicion.esquema,
            system_prompts[definicion.rol],
            mensaje,
        )
        for validar in definicion.validadores:
            validar(artefacto, project, state)

        if definicion.resumen is not None:
            resumen = definicion.resumen(artefacto, state)
        else:
            resumen = (
                f"{definicion.rol} generó {definicion.esquema.__name__}."
            )
        logger.info("Nodo '%s' completado: %s", definicion.nodo, resumen)
        audit.log_step(definicion.nodo, resumen, artifact=artefacto)

        actualizacion: Dict[str, Any] = {definicion.produce: artefacto}
        if definicion.actualizacion_extra is not None:
            actualizacion.update(definicion.actualizacion_extra(artefacto, state))
        return actualizacion

    return _nodo_agente


def build_pipeline_graph(
    gateway: StructuredGenerationPort,
    project: ProjectSpec,
    settings: Optional[PipelineSettings] = None,
    audit: Optional[AuditTrailPort] = None,
    checkpointer: Optional[BaseCheckpointSaver] = None,
) -> CompiledStateGraph:
    """Compone y compila el grafo de estado cíclico para un proyecto.

    El ``checkpointer`` es opcional: presente, cada superstep persiste el
    estado y una corrida puede reanudarse (thread_id = id de ejecución).
    """
    settings = settings or PipelineSettings()
    audit = audit or NullAuditTrail()
    system_prompts = build_role_system_prompts(project)

    # ---------------------- NODOS ESTRUCTURALES ----------------------

    def _plan_series(state: PipelineState) -> Dict[str, Any]:
        """Strategic Planner: genera el plan macro de la serie.

        Nodo de nivel de serie (único agente fuera del bucle de capítulo);
        usa la definición del registro para mensaje, esquema y validadores.
        """
        planador = AGENT_REGISTRY[ROLE_PLANNER]
        plan = gateway.generate(
            planador.rol,
            planador.esquema,
            system_prompts[planador.rol],
            planador.mensaje(project, state),
        )
        for validar in planador.validadores:
            validar(plan, project, state)
        logger.info(
            "Plan maestro listo: '%s' con %d capítulo(s).",
            plan.series_title, len(plan.chapters),
        )
        audit.log_step(
            planador.nodo,
            planador.resumen(plan, state) if planador.resumen else "Plan de serie.",
            artifact=plan,
            details=[f"{c.chapter_id}: {c.title}" for c in plan.chapters],
        )
        return {"series_plan": plan, **(planador.actualizacion_extra(plan, state) or {})}

    def _chief_critic(state: PipelineState) -> Dict[str, Any]:
        """Compuerta de revisión: dictamen + incremento de reintentos.

        Nodo estructural: su salida alimenta el router (revise / approve /
        skip_chapter). Sin crítico activo, aprueba sin dictamen.
        """
        _, capitulo, _ = capitulo_actual(state)
        auditor = AGENT_REGISTRY[ROLE_CRITIC]
        if not project.agente_activo(ROLE_CRITIC):
            logger.info("Crítico desactivado: %s se aprueba sin auditoría.", capitulo.chapter_id)
            audit.log_step(
                auditor.nodo,
                f"Agente desactivado en el proyecto: {capitulo.chapter_id} "
                "se aprueba sin dictamen de calidad.",
            )
            return {"qa_verdict": None, "critique_attempts": 0, "pending_feedback": None}
        dictamen = gateway.generate(
            auditor.rol,
            auditor.esquema,
            system_prompts[auditor.rol],
            auditor.mensaje(project, state),
        )
        for validar in auditor.validadores:
            validar(dictamen, project, state)
        actualizacion: Dict[str, Any] = {
            "qa_verdict": dictamen,
            **(auditor.actualizacion_extra(dictamen, state) or {}),
        }
        # El resumen reporta el intento YA incrementado: se evalúa sobre el
        # estado fusionado con la actualización que devuelve este nodo.
        resumen = (
            auditor.resumen(dictamen, {**state, **actualizacion})
            if auditor.resumen else "Dictamen de calidad."
        )
        audit.log_step(auditor.nodo, resumen, artifact=dictamen)
        if dictamen.approved:
            logger.info(
                "QA APRUEBA %s (score %d/10, intento %d).",
                capitulo.chapter_id, dictamen.overall_score,
                actualizacion["critique_attempts"],
            )
        else:
            logger.info(
                "QA RECHAZA %s (score %d/10, intento %d): %s",
                capitulo.chapter_id, dictamen.overall_score,
                actualizacion["critique_attempts"],
                dictamen.correction_feedback[:120],
            )
        return actualizacion

    def _commit_episode(state: PipelineState) -> Dict[str, Any]:
        """Consolida el episodio aprobado, actualiza lore y avanza el índice."""
        _, capitulo, indice = capitulo_actual(state)
        episodio = assemble_episode(
            chapter=capitulo,
            order_index=indice + 1,
            draft=state["draft_script"],
            adapted=state["adapted_script"],
            package=state["technical_package"],
            audit=state["qa_verdict"],
        )
        lore_nuevo = extract_new_lore(
            capitulo, state.get("continuity_directives"), state.get("lore_entries", [])
        )
        logger.info(
            "Episodio commit: %s (%s) · +%d entradas de lore.",
            capitulo.chapter_id,
            "aceptación forzada" if episodio.forced_acceptance else "aprobado",
            len(lore_nuevo),
        )
        audit.log_step(
            "commit_episode",
            f"Episodio commit: {capitulo.chapter_id} "
            f"({'aceptación forzada' if episodio.forced_acceptance else 'aprobado'}) "
            f"· +{len(lore_nuevo)} entrada(s) de lore.",
            artifact=episodio,
        )
        return {
            "completed_episodes": [episodio],
            "lore_entries": lore_nuevo,
            "current_chapter_index": indice + 1,
            "critique_attempts": 0,
            "pending_feedback": None,
            "draft_script": None,
            "adapted_script": None,
            "qa_verdict": None,
            "technical_package": None,
            "continuity_directives": None,
        }

    def _fail_chapter(state: PipelineState) -> Dict[str, Any]:
        """Política 'skip_chapter': descarta el capítulo y registra el fallo."""
        _, capitulo, indice = capitulo_actual(state)
        registro = build_failed_record(
            chapter=capitulo,
            max_attempts=settings.max_critique_attempts,
            audit=state.get("qa_verdict"),
        )
        logger.warning(
            "Capítulo %s descartado tras agotar los reintentos de QA.",
            capitulo.chapter_id,
        )
        audit.log_failure(
            f"Capítulo {capitulo.chapter_id} descartado tras agotar los "
            f"{settings.max_critique_attempts} reintentos de QA."
        )
        audit.log_step(
            "fail_chapter",
            f"Capítulo {capitulo.chapter_id} '{capitulo.title}' descartado "
            f"tras agotar los reintentos de QA.",
            artifact=registro,
        )
        return {
            "failed_chapters": [registro],
            "current_chapter_index": indice + 1,
            "critique_attempts": 0,
            "pending_feedback": None,
            "draft_script": None,
            "adapted_script": None,
            "qa_verdict": None,
            "continuity_directives": None,
        }

    # ------------------------ ARISTAS CONDICIONALES ------------------------

    def _route_after_critic(state: PipelineState) -> str:
        """Ciclo de crítica: revisar, aceptar, o aplicar política de agotamiento."""
        dictamen = state.get("qa_verdict")
        if dictamen is None or dictamen.approved:
            return "approve"
        if state.get("critique_attempts", 0) >= settings.max_critique_attempts:
            return (
                "approve" if settings.retry_exhaustion_policy == "force_accept"
                else "skip_chapter"
            )
        return "revise"

    def _route_after_commit(state: PipelineState) -> str:
        """Iterador de lotes: siguiente capítulo o fin de la serie."""
        plan = state["series_plan"]
        indice = state.get("current_chapter_index", 0)
        return "next_chapter" if indice < len(plan.chapters) else "series_complete"

    # ----------------------------- GRAFO -----------------------------

    workflow = StateGraph(PipelineState)

    # El orden de add_node replica la declaración histórica: estable para el
    # diagrama (ver_grafo) y para la serialización del checkpointer.
    workflow.add_node("plan_series", _plan_series)
    for rol in (ROLE_CONTINUITY, ROLE_SCRIPTWRITER, ROLE_ADAPTER):
        definicion = AGENT_REGISTRY[rol]
        workflow.add_node(
            definicion.nodo,
            make_agent_node(definicion, gateway, project, system_prompts, audit),
        )
    workflow.add_node("chief_critic", _chief_critic)
    director = AGENT_REGISTRY[ROLE_DIRECTOR]
    workflow.add_node(
        director.nodo,
        make_agent_node(director, gateway, project, system_prompts, audit),
    )
    workflow.add_node("commit_episode", _commit_episode)
    workflow.add_node("fail_chapter", _fail_chapter)

    workflow.add_edge(START, "plan_series")
    workflow.add_edge("plan_series", "continuity_master")
    workflow.add_edge("continuity_master", "scriptwriter")
    workflow.add_edge("scriptwriter", "persona_adapter")
    workflow.add_edge("persona_adapter", "chief_critic")

    workflow.add_conditional_edges(
        "chief_critic",
        _route_after_critic,
        {
            "revise": "scriptwriter",
            "approve": "technical_director",
            "skip_chapter": "fail_chapter",
        },
    )

    workflow.add_edge("technical_director", "commit_episode")
    workflow.add_conditional_edges(
        "fail_chapter",
        _route_after_commit,
        {"next_chapter": "continuity_master", "series_complete": END},
    )
    workflow.add_conditional_edges(
        "commit_episode",
        _route_after_commit,
        {"next_chapter": "continuity_master", "series_complete": END},
    )

    return workflow.compile(checkpointer=checkpointer)
