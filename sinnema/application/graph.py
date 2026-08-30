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
(prompts del rol + sobre editorial ``FormatProfile``). Cada nodo es una función
pura sobre el estado: pide al puerto ``StructuredGenerationPort`` la generación
estructurada de su rol, valida el resultado contra el perfil del proyecto y
contra las reglas cruzadas de dominio, y devuelve solo las claves que modifica.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, Optional, Tuple

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
from sinnema.application.prompts import (
    adapter as adapter_prompts,
    continuity as continuity_prompts,
    critic as critic_prompts,
    director as director_prompts,
    planner as planner_prompts,
    scriptwriter as scriptwriter_prompts,
)
from sinnema.application.prompts import build_role_system_prompts
from sinnema.application.settings import PipelineSettings
from sinnema.application.state import PipelineState
from sinnema.domain.models import (
    AdaptedScript,
    ChapterOutline,
    ContinuityDirectives,
    QualityAudit,
    ScriptDraft,
    SeriesPlan,
    TechnicalPackage,
)
from sinnema.domain.services import (
    assemble_episode,
    build_failed_record,
    extract_new_lore,
    validate_adaptation_format,
    validate_adaptation_matches_draft,
    validate_audit_verdict,
    validate_draft_format,
    validate_package_format,
    validate_package_matches_draft,
    validate_plan_format,
    validate_plan_size,
)
from sinnema.domain.text import count_words

logger = logging.getLogger("sinnema.graph")


def _current_chapter(state: PipelineState) -> Tuple[SeriesPlan, ChapterOutline, int]:
    plan = state["series_plan"]
    indice = state.get("current_chapter_index", 0)
    if plan is None:
        raise RuntimeError("El plan de serie no está disponible en el estado.")
    return plan, plan.chapters[indice], indice


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
    perfil = project.format
    system_prompts = build_role_system_prompts(project)

    # ----------------------------- NODOS -----------------------------

    def _plan_series(state: PipelineState) -> Dict[str, Any]:
        """Strategic Planner: genera el plan macro de la serie."""
        solicitados = state.get("num_chapters", 3)
        mensaje = planner_prompts.build_user_message(
            project, state["topic"], solicitados,
        )
        plan: SeriesPlan = gateway.generate(
            ROLE_PLANNER, SeriesPlan, system_prompts[ROLE_PLANNER], mensaje
        )
        validate_plan_size(plan, solicitados)
        validate_plan_format(plan, perfil)
        logger.info(
            "Plan maestro listo: '%s' con %d capítulo(s).",
            plan.series_title, len(plan.chapters),
        )
        audit.log_step(
            "plan_series",
            f"Plan maestro '{plan.series_title}' con {len(plan.chapters)} capítulo(s).",
            artifact=plan,
            details=[f"{c.chapter_id}: {c.title}" for c in plan.chapters],
        )
        return {"series_plan": plan, "current_chapter_index": 0, "critique_attempts": 0}

    def _continuity_master(state: PipelineState) -> Dict[str, Any]:
        """Lore Keeper: emite directivas de continuidad para el capítulo actual."""
        plan, capitulo, indice = _current_chapter(state)
        previo = plan.chapters[indice - 1] if indice > 0 else None
        mensaje = continuity_prompts.build_user_message(
            chapter=capitulo,
            previous_chapter=previo,
            lore_entries=state.get("lore_entries", []),
            recurring_elements=plan.recurring_elements,
        )
        directivas: ContinuityDirectives = gateway.generate(
            ROLE_CONTINUITY, ContinuityDirectives,
            system_prompts[ROLE_CONTINUITY], mensaje,
        )
        logger.info("Directivas de continuidad listas para %s.", capitulo.chapter_id)
        audit.log_step(
            "continuity_master",
            f"Directivas de continuidad para {capitulo.chapter_id} "
            f"({len(directivas.new_terms_to_introduce)} término(s) nuevos).",
            artifact=directivas,
        )
        return {"continuity_directives": directivas}

    def _scriptwriter(state: PipelineState) -> Dict[str, Any]:
        """Content Creator: escribe el borrador del capítulo (con feedback si es retry)."""
        _, capitulo, _ = _current_chapter(state)
        mensaje = scriptwriter_prompts.build_user_message(
            project,
            chapter=capitulo,
            directives=state["continuity_directives"],
            feedback=state.get("pending_feedback"),
        )
        borrador: ScriptDraft = gateway.generate(
            ROLE_SCRIPTWRITER, ScriptDraft,
            system_prompts[ROLE_SCRIPTWRITER], mensaje,
        )
        validate_draft_format(borrador, perfil)
        logger.info(
            "Borrador %s: %d palabras / %.1f s (intento de crítica #%s).",
            borrador.chapter_id, borrador.word_count, borrador.total_duration_seconds,
            state.get("critique_attempts", 0) + 1,
        )
        audit.log_step(
            "scriptwriter",
            f"Borrador de {borrador.chapter_id}: {borrador.word_count} palabras, "
            f"{borrador.total_duration_seconds:.1f} s "
            f"(intento de crítica #{state.get('critique_attempts', 0) + 1}).",
            artifact=borrador,
        )
        return {"draft_script": borrador, "pending_feedback": None, "qa_verdict": None}

    def _persona_adapter(state: PipelineState) -> Dict[str, Any]:
        """Audience Adapter: re-escribe al registro y cultura del público objetivo."""
        _, capitulo, _ = _current_chapter(state)
        borrador: ScriptDraft = state["draft_script"]
        mensaje = adapter_prompts.build_user_message(
            project,
            draft=borrador,
            directives=state["continuity_directives"],
        )
        adaptado: AdaptedScript = gateway.generate(
            ROLE_ADAPTER, AdaptedScript, system_prompts[ROLE_ADAPTER], mensaje
        )
        validate_adaptation_matches_draft(borrador, adaptado)
        validate_adaptation_format(adaptado, perfil)
        logger.info("Guión %s adaptado al público objetivo.", capitulo.chapter_id)
        audit.log_step(
            "persona_adapter",
            f"Guión de {capitulo.chapter_id} adaptado al público objetivo "
            f"({len(adaptado.adapted_scenes)} escenas conservadas).",
            artifact=adaptado,
        )
        return {"adapted_script": adaptado}

    def _chief_critic(state: PipelineState) -> Dict[str, Any]:
        """Auditor: dictamen booleano + feedback accionable; incrementa reintentos."""
        _, capitulo, _ = _current_chapter(state)
        adaptado: AdaptedScript = state["adapted_script"]
        borrador: ScriptDraft = state["draft_script"]
        texto = " ".join(
            [adaptado.adapted_hook]
            + [s.narration for s in adaptado.adapted_scenes]
            + [adaptado.adapted_cta]
        )
        mensaje = critic_prompts.build_user_message(
            project,
            chapter=capitulo,
            draft=borrador,
            adapted=adaptado,
            directives=state["continuity_directives"],
            actual_word_count=count_words(texto),
        )
        dictamen: QualityAudit = gateway.generate(
            ROLE_CRITIC, QualityAudit, system_prompts[ROLE_CRITIC], mensaje
        )
        validate_audit_verdict(dictamen, perfil)
        intentos = state.get("critique_attempts", 0) + 1
        actualizacion: Dict[str, Any] = {"qa_verdict": dictamen, "critique_attempts": intentos}
        veredicto_texto = "APRUEBA" if dictamen.approved else "RECHAZA"
        audit.log_step(
            "chief_critic",
            f"QA {veredicto_texto} {capitulo.chapter_id} "
            f"(score {dictamen.overall_score}/10, intento {intentos}).",
            artifact=dictamen,
        )
        if dictamen.approved:
            actualizacion["pending_feedback"] = None
            logger.info(
                "QA APRUEBA %s (score %d/10, intento %d).",
                capitulo.chapter_id, dictamen.overall_score, intentos,
            )
        else:
            actualizacion["pending_feedback"] = dictamen.correction_feedback
            logger.info(
                "QA RECHAZA %s (score %d/10, intento %d): %s",
                capitulo.chapter_id, dictamen.overall_score, intentos,
                dictamen.correction_feedback[:120],
            )
        return actualizacion

    def _technical_director(state: PipelineState) -> Dict[str, Any]:
        """Visual/Audio Director: traduce el guion aprobado a specs técnicas."""
        plan, capitulo, _ = _current_chapter(state)
        borrador: ScriptDraft = state["draft_script"]
        mensaje = director_prompts.build_user_message(
            project,
            chapter=capitulo,
            draft=borrador,
            adapted=state["adapted_script"],
            recurring_elements=plan.recurring_elements,
        )
        paquete: TechnicalPackage = gateway.generate(
            ROLE_DIRECTOR, TechnicalPackage,
            system_prompts[ROLE_DIRECTOR], mensaje,
        )
        validate_package_matches_draft(borrador, paquete)
        validate_package_format(paquete, perfil)
        logger.info("Paquete técnico listo para %s.", capitulo.chapter_id)
        audit.log_step(
            "technical_director",
            f"Paquete técnico de {capitulo.chapter_id}: "
            f"{len(paquete.visual_specs)} spec(s) visuales.",
            artifact=paquete,
        )
        return {"technical_package": paquete}

    def _commit_episode(state: PipelineState) -> Dict[str, Any]:
        """Consolida el episodio aprobado, actualiza lore y avanza el índice."""
        _, capitulo, indice = _current_chapter(state)
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
        _, capitulo, indice = _current_chapter(state)
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
    workflow.add_node("plan_series", _plan_series)
    workflow.add_node("continuity_master", _continuity_master)
    workflow.add_node("scriptwriter", _scriptwriter)
    workflow.add_node("persona_adapter", _persona_adapter)
    workflow.add_node("chief_critic", _chief_critic)
    workflow.add_node("technical_director", _technical_director)
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
