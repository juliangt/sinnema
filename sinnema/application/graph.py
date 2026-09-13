"""Orquestación del pipeline multi-agente como grafo LangGraph cíclico.

Topología del grafo se resuelve desde el flujo efectivo del proyecto
(``resolver_flujo``): composición de fases + corte por el hito ``hasta``:

    START
      -> plan_series                        (Strategic Planner, nivel de serie)
      -> [contexto]*                        (Lore Keeper, ...)
      -> scriptwriter                       (Content Creator, escritor)
      -> [transformaciones]*                (Audience Adapter, ...)
      -> (chief_critic                      (Auditor, compuerta opcional)
            |-- revise ----> scriptwriter   (ciclo de crítica con feedback)
            |-- approve ---> enriquecedores | commit
            |-- skip_chapter -> fail_chapter (reintentos agotados))?
      -> [enriquecedores]*                  (Visual/Audio Director, ...)
      -> commit_episode                     (consolida episodio + actualiza lore)
           |-- next_chapter ---> primer nodo del capítulo
           |-- series_complete -> END

Con ``hasta = "plan"`` no hay bucle de capítulos: ``START -> plan_series ->
consolidar_plan -> END`` (el entregable es el outline sin episodios).

El grafo se compila POR PROYECTO: los nodos cierran sobre el ``ProjectSpec``
(prompts del rol + sobre editorial ``FormatProfile``).

Los nodos de agente NO se escriben a mano: ``make_agent_node`` los genera a
partir de su ``AgentDefinition`` (``sinnema.application.registry``), que
declara mensajes, validadores de dominio, cortocircuitos y actualizaciones de
estado. Quedan escritos a mano solo los nodos ESTRUCTURALES —``plan_series``,
la compuerta de revisión (``chief_critic`` y sus aristas condicionales),
``commit_episode``, ``fail_chapter`` y ``consolidar_plan``— porque encapsulan
semántica del pipeline (iterador de capítulos, política de agotamiento,
ensamblado del entregable), no la de un agente en particular.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph
from pydantic import BaseModel

from sinnema.application.ports import (
    ROLE_CRITIC,
    ROLE_DIRECTOR,
    ROLE_PLANNER,
    ROLE_SCRIPTWRITER,
    AuditTrailPort,
    NullAuditTrail,
    StructuredGenerationPort,
)
from sinnema.application.projects import ProjectSpec, resolver_flujo
from sinnema.application.registry import (
    AGENT_REGISTRY,
    AgentDefinition,
    build_role_system_prompts,
    capitulo_actual,
    definiciones_del_proyecto,
)
from sinnema.application.settings import PipelineSettings
from sinnema.application.state import PipelineState
from sinnema.domain.models import ArtefactoAdjunto, RecursoAncla
from sinnema.domain.services import (
    anclas_referenciadas,
    assemble_episode,
    build_failed_record,
    cobertura_casting,
    extract_new_lore,
    identity_adaptation,
    registrar_vigencia_de_anclas,
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

        # Un agente custom adjunta a la pizarra ({"rol": artefacto}) para que
        # el reducer la fusione por clave y el commit lo adjunte al episodio.
        valor: Any = (
            {definicion.rol: artefacto} if definicion.adjunto else artefacto
        )
        actualizacion: Dict[str, Any] = {definicion.produce: valor}
        if definicion.actualizacion_extra is not None:
            actualizacion.update(definicion.actualizacion_extra(artefacto, state))
        return actualizacion

    return _nodo_agente


def _serializar_adjunto(artefacto: Any) -> Dict[str, Any]:
    """Artefacto del estado en JSON ( BaseModel -> dict; dict -> tal cual)."""
    if isinstance(artefacto, BaseModel):
        return artefacto.model_dump(mode="json")
    if isinstance(artefacto, dict):
        return artefacto
    raise TypeError(
        f"La pizarra solo guarda contratos validados (BaseModel) o JSON "
        f"dict; recibido: {type(artefacto).__name__}."
    )


def _adjuntos_del_estado(
    state: PipelineState,
    *,
    paquete: Optional[Any],
    dictamen: Optional[Any],
) -> list:
    """Adjuntos del episodio: specs, dictamen y artefactos de la pizarra.

    ``technical`` y ``audit`` se mantienen como campos propios por
    compatibilidad y además figuran en ``adjuntos`` cuando existen; los
    artefactos de los enriquecedores sin slot canónico viajan solo aquí.
    """
    adjuntos = []
    if paquete is not None:
        adjuntos.append(
            ArtefactoAdjunto(
                rol=ROLE_DIRECTOR, artefacto=_serializar_adjunto(paquete)
            )
        )
    if dictamen is not None:
        adjuntos.append(
            ArtefactoAdjunto(
                rol=ROLE_CRITIC, artefacto=_serializar_adjunto(dictamen)
            )
        )
    for clave, artefacto in sorted((state.get("artefactos") or {}).items()):
        adjuntos.append(
            ArtefactoAdjunto(rol=clave, artefacto=_serializar_adjunto(artefacto))
        )
    return adjuntos


def build_pipeline_graph(
    gateway: StructuredGenerationPort,
    project: ProjectSpec,
    settings: Optional[PipelineSettings] = None,
    audit: Optional[AuditTrailPort] = None,
    checkpointer: Optional[BaseCheckpointSaver] = None,
    anclas: Optional[List[RecursoAncla]] = None,
) -> CompiledStateGraph:
    """Compone y compila el grafo de estado cíclico para un proyecto.

    El ``checkpointer`` es opcional: presente, cada superstep persiste el
    estado y una corrida puede reanudarse (thread_id = id de ejecución).
    ``anclas`` es la biblioteca lockeada del proyecto (spec-recursos-ancla
    §5.1): presente y no vacía, los system prompts de los roles con conciencia
    visual componen sus reglas de identidad fija; ausente, los prompts son
    exactamente los de siempre.
    """
    settings = settings or PipelineSettings()
    audit = audit or NullAuditTrail()
    system_prompts = build_role_system_prompts(project, anclas=anclas)
    # Catálogo completo del proyecto: registro global + agentes custom del
    # TOML. El flujo solo referencia roles presentes aquí.
    definiciones = definiciones_del_proyecto(project)

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
        skip_chapter). Usa la definición del revisor del flujo (el crítico de
        código o un revisor custom, cuyo contrato ``dictamen`` es igualmente
        ``QualityAudit``). Sin revisor activo, aprueba sin dictamen.
        """
        _, capitulo, _ = capitulo_actual(state)
        auditor = definiciones[flujo.revisor] if flujo.revisor is not None else (
            AGENT_REGISTRY[ROLE_CRITIC]
        )
        if not project.agente_activo(auditor.rol):
            logger.info("Crítico desactivado: %s se aprueba sin auditoría.", capitulo.chapter_id)
            audit.log_step(
                auditor.nodo,
                f"Agente desactivado en el proyecto: {capitulo.chapter_id} "
                "se aprueba sin dictamen de calidad.",
            )
            return {"qa_verdict": None, "critique_attempts": 0, "pending_feedback": None}
        # Un flujo puede auditar sin transformaciones aguas arriba: el guion
        # auditado es entonces el borrador con adaptación identidad (determinista).
        estado_auditoria = state
        if state.get("adapted_script") is None and state.get("draft_script") is not None:
            estado_auditoria = {
                **state,
                "adapted_script": identity_adaptation(state["draft_script"]),
            }
        dictamen = gateway.generate(
            auditor.rol,
            auditor.esquema,
            system_prompts[auditor.rol],
            auditor.mensaje(project, estado_auditoria),
        )
        for validar in auditor.validadores:
            validar(dictamen, project, estado_auditoria)
        extras = (
            auditor.actualizacion_extra(dictamen, state)
            if auditor.actualizacion_extra is not None else {}
        )
        actualizacion: Dict[str, Any] = {"qa_verdict": dictamen, **(extras or {})}
        intento = state.get("critique_attempts", 0) + 1
        # El resumen reporta el intento YA incrementado: se evalúa sobre el
        # estado fusionado con la actualización que devuelve este nodo.
        resumen = (
            auditor.resumen(dictamen, {**estado_auditoria, **actualizacion, "critique_attempts": intento})
            if auditor.resumen else "Dictamen de calidad."
        )
        audit.log_step(auditor.nodo, resumen, artifact=dictamen)
        if dictamen.approved:
            logger.info(
                "QA APRUEBA %s (score %d/10, intento %d).",
                capitulo.chapter_id, dictamen.overall_score, intento,
            )
        else:
            logger.info(
                "QA RECHAZA %s (score %d/10, intento %d): %s",
                capitulo.chapter_id, dictamen.overall_score, intento,
                dictamen.correction_feedback[:120],
            )
        return actualizacion

    def _commit_episode(state: PipelineState) -> Dict[str, Any]:
        """Consolida el episodio aprobado, actualiza lore y avanza el índice.

        El guion final es el vigente al momento del commit: si el flujo cortó
        antes de las transformaciones, ``assemble_episode`` aplica la
        adaptación identidad sobre el borrador. Los adjuntos del episodio
        reúnen los artefactos de los enriquecedores (slots canónicos +
        pizarra) serializados en JSON.
        """
        _, capitulo, indice = capitulo_actual(state)
        paquete = state.get("technical_package")
        dictamen = state.get("qa_verdict")
        episodio = assemble_episode(
            chapter=capitulo,
            order_index=indice + 1,
            draft=state["draft_script"],
            adapted=state.get("adapted_script"),
            package=paquete,
            audit=dictamen,
            adjuntos=_adjuntos_del_estado(state, paquete=paquete, dictamen=dictamen),
        )
        lore_nuevo = extract_new_lore(
            capitulo, state.get("continuity_directives"), state.get("lore_entries", [])
        )
        # Libro contable de anclas (spec-recursos-ancla §5.4): las referencias
        # del paquete estampan la vigencia (first/last seen) en el catálogo en
        # memoria; la persistencia al final de la corrida va por el mismo
        # camino que consolida el lore (use case.save_anclas).
        usadas = anclas_referenciadas(paquete)
        anclas_actualizadas = registrar_vigencia_de_anclas(
            state.get("anclas") or [], usadas, capitulo.chapter_id
        )
        # Cobertura blanda casting↔specs (§5.3): no rechaza; queda como
        # hallazgo de auditoría para revisión humana.
        directivas = state.get("continuity_directives")
        if directivas is not None and paquete is not None:
            sin_cobertura = cobertura_casting(directivas.anclas_del_capitulo, paquete)
            if sin_cobertura:
                audit.log_event(
                    f"Cobertura de anclas de {capitulo.chapter_id}: el casting "
                    f"declara '{', '.join(sin_cobertura)}' pero ninguna spec "
                    "las referencia."
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
        actualizacion: Dict[str, Any] = {
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
            # None borra las claves de la pizarra (reducer fusionar_por_clave):
            # los adjuntos ya viajan dentro del episodio consolidado.
            "artefactos": {clave: None for clave in (state.get("artefactos") or {})},
        }
        if anclas_actualizadas is not None:
            actualizacion["anclas"] = anclas_actualizadas
        return actualizacion

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

    def _consolidar_plan(state: PipelineState) -> Dict[str, Any]:
        """Cierre de la corrida con ``hasta = 'plan'``: outline sin episodios.

        Nodo estructural: no hay bucle de capítulos ni lore; el consolidador
        del caso de uso arma el entregable con el plan y cero episodios.
        """
        plan = state["series_plan"]
        logger.info(
            "Alcance 'plan': outline de %d capítulo(s) sin episodios.",
            len(plan.chapters),
        )
        audit.log_step(
            "consolidar_plan",
            f"Alcance 'plan': serie planificada con {len(plan.chapters)} "
            "capítulo(s); la corrida termina sin guiones ni episodios.",
            details=[f"{c.chapter_id}: {c.title}" for c in plan.chapters],
        )
        return {}

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

    flujo = resolver_flujo(project)

    def _agregar_agente(rol: str) -> str:
        """Registra el nodo del rol (nombre estable) y devuelve su nombre."""
        definicion = definiciones[rol]
        workflow.add_node(
            definicion.nodo,
            make_agent_node(definicion, gateway, project, system_prompts, audit),
        )
        return definicion.nodo

    workflow = StateGraph(PipelineState)
    workflow.add_node("plan_series", _plan_series)

    if flujo.hasta == "plan":
        # Sin bucle de capítulos: planificar la serie y consolidar el outline.
        workflow.add_edge(START, "plan_series")
        workflow.add_node("consolidar_plan", _consolidar_plan)
        workflow.add_edge("plan_series", "consolidar_plan")
        workflow.add_edge("consolidar_plan", END)
        return workflow.compile(checkpointer=checkpointer)

    # Cableado por fases: el cursor avanza por el último nodo lineal y la
    # entrada del capítulo marca el regreso de next_chapter. El orden de
    # add_node/add_edge replica la declaración histórica: estable para el
    # diagrama (ver_grafo) y para la serialización del checkpointer.
    workflow.add_edge(START, "plan_series")
    cursor = "plan_series"
    entrada_capitulo: Optional[str] = None
    for rol in flujo.contexto:
        nodo = _agregar_agente(rol)
        workflow.add_edge(cursor, nodo)
        cursor = nodo
        if entrada_capitulo is None:
            entrada_capitulo = nodo

    nodo_escritor = _agregar_agente(ROLE_SCRIPTWRITER)
    workflow.add_edge(cursor, nodo_escritor)
    cursor = nodo_escritor
    if entrada_capitulo is None:
        entrada_capitulo = nodo_escritor

    for rol in flujo.transformaciones:
        nodo = _agregar_agente(rol)
        workflow.add_edge(cursor, nodo)
        cursor = nodo

    ultimo_enriquecedor: Optional[str] = None
    if flujo.revisor is not None:
        # El nodo de la compuerta lleva el nombre de su definición
        # ("chief_critic" para el crítico de código; el rol para un revisor
        # custom): estable para el checkpointer.
        nodo_compuerta = definiciones[flujo.revisor].nodo
        workflow.add_node(nodo_compuerta, _chief_critic)
        workflow.add_edge(cursor, nodo_compuerta)
        primero: Optional[str] = None
        anterior: Optional[str] = None
        for rol in flujo.enriquecimiento:
            nodo = _agregar_agente(rol)
            if primero is None:
                primero = nodo
            else:
                workflow.add_edge(anterior, nodo)
            anterior = nodo
        workflow.add_conditional_edges(
            nodo_compuerta,
            _route_after_critic,
            {
                "revise": nodo_escritor,
                "approve": primero or "commit_episode",
                "skip_chapter": "fail_chapter",
            },
        )
        ultimo_enriquecedor = anterior
        if anterior is not None:
            cursor = anterior
        else:
            cursor = None  # commit recibe el approve de la compuerta
    else:
        for rol in flujo.enriquecimiento:
            nodo = _agregar_agente(rol)
            workflow.add_edge(cursor, nodo)
            cursor = nodo

    workflow.add_node("commit_episode", _commit_episode)
    if cursor is not None:
        workflow.add_edge(cursor, "commit_episode")

    if flujo.revisor is not None:
        workflow.add_node("fail_chapter", _fail_chapter)
        workflow.add_conditional_edges(
            "fail_chapter",
            _route_after_commit,
            {"next_chapter": entrada_capitulo, "series_complete": END},
        )
    workflow.add_conditional_edges(
        "commit_episode",
        _route_after_commit,
        {"next_chapter": entrada_capitulo, "series_complete": END},
    )

    return workflow.compile(checkpointer=checkpointer)
